"""Creation : route inclinee progressivement et route descendue sous le sol de depart. Generation de la geometrie seule
(track_creator.build), rien n'est ecrit. Le terrain doit se creuser sous la route et les bords suivre l'inclinaison.
python test_creator_bank.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
import track_creator as tc  # noqa: E402

IN, GZ, W = 39.37, 2000.0, 30 * 39.37


def obj_parts(text):
    verts, faces, cur = [], {}, None
    for line in text.splitlines():
        if line.startswith('v '):
            verts.append([float(x) for x in line.split()[1:4]])
        elif line.startswith('usemtl'):
            cur = line.split()[1]
        elif line.startswith('f '):
            faces.setdefault(cur, []).extend(int(x.split('/')[0]) - 1 for x in line.split()[1:])
    return np.array(verts), faces


def track(depth, roll_deg):
    """Ligne droite de 600 m : plate, puis descente / inclinaison progressives, puis maintenues."""
    pts = []
    for i in range(150):
        s = i * 4 * IN
        k = np.clip((i - 40) / 40, 0, 1)
        p = [s, 0.0, GZ - depth * IN * k, W, 0]
        if roll_deg:
            d = W / 2 * np.sin(np.radians(roll_deg) * k)
            p += [W / 2, W / 2, float(-d), float(d)]
        pts.append(p)
    return pts


# 1) sous le sol : la route atteint la profondeur, le terrain la suit dessous, le sol reste a sa hauteur au loin
obj, _, info = tc.build(track(40, 0), False, GZ, 'sable', None, 'none')
V, F = obj_parts(obj)
road = V[np.unique(F['Road'])]
ground = V[np.unique(np.concatenate([np.array(v) for k, v in F.items() if k not in ('Road', 'StartLine', 'Wall', 'Bridge')]))]
gz = GZ / IN
assert road[:, 2].min() < gz - 38, road[:, 2].min()
assert ground[:, 2].min() < road[:, 2].min(), 'le terrain doit passer sous la route'
assert abs(ground[:, 2].max() - gz) < 2, f'sol lointain garde : {ground[:, 2].max()} contre {gz}'
print(f'ok sous le sol : route jusqu a {road[:, 2].min() - gz:.1f} m, terrain {ground[:, 2].min() - gz:.1f} m, sol {ground[:, 2].max() - gz:.1f} m')
assert info['min_z'] < GZ - 38 * IN if 'min_z' in info else True

# 2) inclinaison : au bout, le bord gauche (+y) plus bas que le droit de largeur x sin(angle), progressivement
obj, _, _ = tc.build(track(0, 25), False, GZ, 'sable', None, 'none')
V, F = obj_parts(obj)
R = V[np.unique(F['Road'])]
at = lambda x: R[np.abs(R[:, 0] - x) < 3]
tilt = lambda x: np.degrees(np.arctan2(at(x)[at(x)[:, 1].argmin(), 2] - at(x)[at(x)[:, 1].argmax(), 2], np.ptp(at(x)[:, 1])))
t0, t1, t2 = tilt(100), tilt(240), tilt(500)
assert abs(t0) < 1, t0
assert 3 < t1 < t2, (t1, t2)
assert 22 < t2 < 28, t2
print(f'ok inclinaison : {t0:.1f} puis {t1:.1f} puis {t2:.1f} degres')

# 3) aux limites de l'editeur (H_MAX 300 m, H_MIN 200 m) : geometrie saine, terrain raccorde, pas de valeur invalide
for depth, label in ((200, 'profondeur'), (-300, 'hauteur')):
    obj, _, info = tc.build(track(depth, 0), False, GZ, 'sable', None, 'none')
    V, F = obj_parts(obj)
    road = V[np.unique(F['Road'])]
    ends = road[:, 2] - gz
    assert np.isfinite(V).all(), label
    assert abs(ends.min() + depth) < 1.5 if depth > 0 else abs(ends.max() + depth) < 1.5, (label, ends.min(), ends.max())
    print(f'ok {label} : route de {ends.min():.1f} a {ends.max():.1f} m, terrain {V[:, 2].min() - gz:.1f} a {V[:, 2].max() - gz:.1f} m, etendue {np.ptp(V[:, 0]):.0f} x {np.ptp(V[:, 1]):.0f} m')


def ground_of(obj):
    V, F = obj_parts(obj)
    ids = np.unique(np.concatenate([np.array(v) for k, v in F.items() if k not in ('Road', 'StartLine', 'Wall', 'Bridge')]))
    return V[ids], V[np.unique(F['Road'])], F, V


def no_talus(pts, i0, i1):
    """Morceau [i0, i1[ sans talus (colonnes de bord par defaut)."""
    out = []
    for i, p in enumerate(pts):
        q = list(p)
        if i0 <= i < i1:
            q = q[:5] + (q[5:9] if len(q) > 5 else [W / 2, W / 2, 0.0, 0.0]) + [1]
        out.append(q)
    return out


# 4) talus : route montee a 40 m. Avec : le sol monte. Sans : il reste au niveau de depart sous le morceau choisi, seulement la
up = track(-40, 0)
ga, ra, _, _ = ground_of(tc.build(up, False, GZ, 'sable', None, 'none')[0])
gb, rb, Fb, Vb = ground_of(tc.build(no_talus(up, 90, 150), False, GZ, 'sable', None, 'none')[0])
under = lambda G, x0, x1: G[(G[:, 0] > x0) & (G[:, 0] < x1) & (np.abs(G[:, 1]) < 8)][:, 2].max() - gz
assert under(ga, 450, 540) > 35, under(ga, 450, 540)                   # avec talus : remblai jusqu'a la route
assert under(gb, 450, 540) < 1, under(gb, 450, 540)                    # sans talus : sol d'origine
assert under(gb, 240, 300) > 25, under(gb, 240, 300)                   # avant le morceau : talus garde
assert np.allclose(np.sort(ra[:, 2]), np.sort(rb[:, 2]), atol=0.01), 'la route ne doit pas changer'
assert 'Bridge' in Fb, 'tablier attendu sous la route sans talus'
print(f"ok talus : sol sous la route {under(ga, 450, 540):.1f} m avec, {under(gb, 450, 540):.1f} m sans, {under(gb, 240, 300):.1f} m avant le morceau")
# sous le sol, sans talus : la route ne doit pas etre enterree
down = track(40, 0)
gd, rd, _, _ = ground_of(tc.build(no_talus(down, 90, 150), False, GZ, 'sable', None, 'none')[0])
assert under(gd, 450, 540) < rd[:, 2].min() - gz + 1, 'tranchee gardee'
print('ok sans talus sous le sol : tranchee gardee')
# ancien trace (points sans colonne talus) : generation identique a un trace au talus explicitement actif
assert tc.build(up, False, GZ, 'sable', None, 'none')[0] == tc.build(no_talus(up, 0, 0), False, GZ, 'sable', None, 'none')[0]
print('ok anciens traces inchanges')


# 5) aucun coup de falaise au raccord : pente du talus BLEND_SLOPE, soit au plus ~1 m par m (8 m entre deux sommets)
def steps(pts):
    C = tc.centerline(pts, False)
    T, L = tc._frames(C, False)
    half = C[:, 3:4] / 2
    rz = C[:, 2] + tc.ROAD_LIFT
    left = tc._unfold(np.hstack([C[:, :2] + L * half, (rz + C[:, 5])[:, None]]), T)
    right = tc._unfold(np.hstack([C[:, :2] - L * half, (rz - C[:, 5])[:, None]]), T)
    c, n = 8 * IN, 251
    terrain = {'n': n, 'cell': c, 'x0': -200 * IN, 'y0': -(n - 1) / 2 * c, 'h': [0.0] * n * n, 'paint': [0] * n * n, 'full': True}
    xs, ys, H, _, _ = tc._terrain_grid(terrain, C, GZ / IN)
    O = tc._conform(xs, ys, H, C, False, left, right)
    return max(np.abs(np.diff(O, axis=1)).max(), np.abs(np.diff(O, axis=0)).max())


for depth, label in ((-80, '+80 m'), (-300, '+300 m'), (200, '-200 m')):
    s = steps(track(depth, 0))
    # le trace d'essai monte sur 160 m, bien plus raide que le paveur (28 %) : le sol suit aussi cette pente-la
    allowed = max(12.0, 8 * abs(depth) / 160 * 1.3)
    assert s < allowed, f'falaise au raccord, route a {label} : {s:.1f} m (au plus {allowed:.1f})'
    print(f'ok raccord route a {label} : marche max {s:.1f} m entre sommets')


# 6) largeur du talus (terrain['blend']) et relief sculpte pres de la route, a la generation complete
def grid_terrain(blend, h_fn=None):
    c, n = 8 * IN, 251
    x0, y0 = -200 * IN, -(n - 1) / 2 * c
    X, Y = np.meshgrid(x0 + np.arange(n) * c, y0 + np.arange(n) * c)
    h = h_fn(X / IN, Y / IN) * IN if h_fn else np.zeros((n, n))
    return {'n': n, 'cell': c, 'x0': x0, 'y0': y0, 'h': h.ravel().tolist(), 'paint': [0] * n * n, 'full': True, 'size': 2000, 'blend': blend}


def ground_at(obj, x, y):
    G = ground_of(obj)[0]
    d = np.hypot(G[:, 0] - x, G[:, 1] - y)
    return G[d.argmin(), 2] - gz


def talus_width(blend):
    """Distance au bord de la route ou le sol redescend a 1 m, route a 40 m."""
    obj = tc.build(track(-40, 0), False, GZ, 'sable', grid_terrain(blend), 'none')[0]
    for y in range(16, 240, 4):
        if ground_at(obj, 500, y) < 1:
            return y - 15
    return 999


w15, w075, w025 = talus_width(1.5), talus_width(0.75), talus_width(0.25)
assert w025 < w075 < w15, (w025, w075, w15)
assert abs(w075 / w15 - 0.5) < 0.2, (w075, w15)
print(f'ok largeur du talus, route a 40 m : {w15} m a 15 m/10 m, {w075} m a 7,5, {w025} m a 2,5')

# relief +50 m sculpte le long de la route plate : atteint a moins de 15 m du bord ; la route ne bouge pas
wall = lambda X, Y: 50.0 * (np.abs(Y) > 25)
flat = [[i * 4 * IN, 0.0, GZ, W, 0] for i in range(150)]
ob0 = tc.build(flat, False, GZ, 'sable', grid_terrain(0.75), 'none')[0]
ob1 = tc.build(flat, False, GZ, 'sable', grid_terrain(0.75, wall), 'none')[0]
near = ground_at(ob1, 300, 32)
assert near > 40, f'relief ecrase pres de la route : {near:.1f} m'
assert ground_at(ob0, 300, 32) < 1
assert np.allclose(np.sort(ground_of(ob0)[1][:, 2]), np.sort(ground_of(ob1)[1][:, 2]), atol=0.01), 'la route ne doit pas changer'
print(f'ok relief pres de la route : {near:.1f} m a 17 m du bord (route intacte)')

# route posee sur une colline sculptee : pas de mur au-dessus d'elle, sol raccorde
hill = lambda X, Y: np.full_like(X, 40.0)
on_hill = [[i * 4 * IN, 0.0, GZ + 40 * IN, W, 0] for i in range(150)]
ob2 = tc.build(on_hill, False, GZ, 'sable', grid_terrain(0.75, hill), 'none')[0]
assert abs(ground_at(ob2, 300, 40) - 40) < 1, ground_at(ob2, 300, 40)
print('ok route sur une colline : sol a sa hauteur')


# 7) fondu entre peintures : plusieurs niveaux, images sans couture, surfaces, reglage 0 = ancien rendu
def painted(fade):
    t = grid_terrain(0.75)
    n, x0, c = t['n'], t['x0'], t['cell']
    t['paint'] = [1 if x0 + (k % n) * c > 300 * IN else 0 for k in range(n * n)]
    if fade is not None:
        t['fade'] = fade
    return tc.build(flat, False, GZ, 'sable', t, 'none')


ob, mt, inf = painted(4)
assert sorted(x[3] for x in inf['mixes']) == [1, 2, 3], inf['mixes']
assert all(f'newmtl {x[0]}\n' in mt and f'map_Kd {x[0]}.png' in mt for x in inf['mixes'])
assert all(any(line == f'usemtl {x[0]}' for line in ob.splitlines()) for x in inf['mixes'])
mats = tc.paint_materials('sable')
assert inf['mix_surfaces'][inf['mixes'][0][0]] == mats[0][3] and inf['mix_surfaces'][inf['mixes'][-1][0]] in (mats[0][3], mats[1][3])
assert painted(None)[2]['mixes'] == inf['mixes'], 'ancien terrain sans reglage : fondu moyen'
assert not painted(0)[2]['mixes']
assert [x[3] for x in painted(2)[2]['mixes']] == [2], 'fondu court, bord droit : une rangee a 50 %'
# plus de melanges que MIX_MAX : plafonne, chaque case garde une matiere
M = np.random.RandomState(1).randint(0, 40, (64, 64))
CM, mx = tc._cell_materials(M, 40, 4)
assert len(mx) == tc.MIX_MAX and CM.max() < 40 + tc.MIX_MAX and CM.shape == (63, 63)
print(f"ok fondu : {len(inf['mixes'])} images, surfaces et plafond {tc.MIX_MAX}")

# images : proportions, raccord des bords (le sol se repete), 2 tailles differentes
import io  # noqa: E402
from PIL import Image  # noqa: E402


def png(col, size):
    b = io.BytesIO()
    Image.new('RGB', (size, size), col).save(b, 'PNG')
    return b.getvalue()


tex = {'a.png': png((0, 0, 0), 1024), 'b.png': png((255, 255, 255), 512)}
out = tc.mix_textures(tex, [('M1', 'a.png', 'b.png', 1), ('M2', 'a.png', 'b.png', 2), ('M3', 'a.png', 'b.png', 3)])
av = [np.asarray(Image.open(io.BytesIO(out[f'M{k}.png']))).astype(float) for k in (1, 2, 3)]
for k, im in zip((0.25, 0.5, 0.75), av):
    assert im.shape == (1024, 1024, 3) and abs(im.mean() / 255 - k) < 0.02, (k, im.mean())
    assert 0 < (im[..., 0] > 127).mean() < 1
    assert np.abs(im[0] - im[-1]).mean() < 40 and np.abs(im[:, 0] - im[:, -1]).mean() < 40, 'bords raccordes'
assert (av[1] + 2 >= av[0]).all() and (av[2] + 2 >= av[1]).all(), 'niveaux empiles'
print('ok images de fondu')


# 8) pose des objets sur une pente de 30 % : rien ne flotte ; herbes et rochers inclines, arbres presque droits
def slope_terrain():
    return grid_terrain(0.75, lambda X, Y: 0.3 * np.clip(np.abs(Y) - 40, 0, None))


obs = tc.build(flat, False, GZ, 'sable', slope_terrain(), 'none')
ground = obs[2]['_ground']
dims = lambda k: {t: [{'r': 6.0, 'zmin': 0.0, 'zmax': 5.0}] * len(p['models']) for t, p in tc.KITS[k]['props'].items()}
props = [{'k': 'sable', 't': t, 'm': 0, 'x': 300 * IN, 'y': 120 * IN, 'yaw': 0.7, 's': 1.0} for t in ('grass', 'palm', 'big')]
items, drop = tc.props_items('sable', props, ground, dims)
assert len(items) == 3 and not drop, (len(items), drop)
slope_deg = np.degrees(np.arctan(0.3))
for it, role in zip(items, ('cover', 'tree', 'big')):
    rx, ry = it['rot']
    c, s = np.cos(it['yaw']), np.sin(it['yaw'])
    Rx = np.array([[1, 0, 0], [0, np.cos(rx), -np.sin(rx)], [0, np.sin(rx), np.cos(rx)]])
    Ry = np.array([[np.cos(ry), 0, np.sin(ry)], [0, 1, 0], [-np.sin(ry), 0, np.cos(ry)]])
    Rz = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    R = Rz @ Ry @ Rx
    up = R[:, 2]
    ang = np.degrees(np.arccos(up[2]))
    assert ang <= min(tc.PROP_ROLES[role][0], slope_deg) + 0.5, (role, ang)
    if role == 'cover':
        assert ang > slope_deg - 1 and up[1] < 0, (ang, up)                    # sol qui monte vers +y : penche vers -y
    # base du modele : sous le sol sur toute l'emprise qui doit reposer
    seat = tc.PROP_ROLES[role][1] * 6.0
    for a in np.linspace(0, 2 * np.pi, 16, endpoint=False):
        lx, ly = np.linalg.solve(R[:2, :2], [seat * np.cos(a), seat * np.sin(a)])
        wx, wy = 300 + seat * np.cos(a), 120 + seat * np.sin(a)
        base = it['pos'][2] / IN + R[2, 0] * lx + R[2, 1] * ly
        g = tc.ground_height(ground, wx * IN, wy * IN) / IN
        assert base <= g + 0.2, (role, base, g)
    print(f'ok pose {role} : inclinaison {ang:.1f} degres (pente {slope_deg:.1f})')

# 9) inclinaison donnee a la main (outil Modifier, rx / ry en radians) : ajoutee a celle de la pente
tilted = [dict(props[1], rx=0.5, ry=-0.25)]
it2, _ = tc.props_items('sable', tilted, ground, dims)
assert abs(it2[0]['rot'][0] - (items[1]['rot'][0] + 0.5)) < 1e-9 and abs(it2[0]['rot'][1] - (items[1]['rot'][1] - 0.25)) < 1e-9, \
    (it2[0]['rot'], items[1]['rot'])
print('ok inclinaison a la main ajoutee a celle du sol')
print('TOUT EST BON')
