"""Trace d'un circuit deduit de la geometrie de sa route (sans aucune spline existante).

  loop = road_loop(tris, start_xy, heading)
      tris     : triangles monde de la route (pouces) — modeles importes ou collision filtree par surface
      start_xy : point de depart (ligne d'arrivee) ; heading : direction de course (radians) a ce point
      -> {'points': boucle fermee [[x, y, z]] tous les ~300 po, 'widths': [(gauche, droite)], 'length': po}

Methode : la route est rasterisee vue de dessus (CELL pouces par pixel), les petits trous bouches, le plus grand
morceau garde, les obstacles au milieu de la route (trous bien plus petits que l'interieur du circuit) bouches ;
squelette par amincissement (Zhang-Suen) ; les impasses sont ebarbees, il ne reste que les boucles ;
on parcourt la boucle depuis le pixel le plus proche du depart, dans la direction de course, sur le graphe des
troncons entre carrefours (walk_graph) : a chaque carrefour le troncon pas encore emprunte le plus dans l'axe, puis
le plus large (route principale plutot que raccourci) ; un carrefour peut etre traverse plusieurs fois (route qui
passe sous un pont : croisement en X vu de dessus, Roo's Tubes importe). Le trace est lisse puis pose sur la route.
"""
import math
from collections import deque

import numpy as np

import progress

CELL = 60.0
MAX_EXTENT = 3000 * 39.37      # po : au-dela, la map a ete importee trop grande (et le calcul n'en finit plus)


def rasterize(tris, cell=CELL):
    """Masque booleen de la route vue de dessus + hauteur max par pixel, origine et taille de cellule."""
    T = np.asarray(tris, np.float64)
    lo = T[:, :, :2].min((0, 1)) - 4 * cell
    hi = T[:, :, :2].max((0, 1)) + 4 * cell
    W, H = (np.ceil((hi - lo) / cell).astype(int) + 1)
    mask = np.zeros((H, W), bool)
    zmap = np.full((H, W), -np.inf)
    for t in T:
        a, b, c = t[:, :2]
        x0, y0 = np.floor((t[:, :2].min(0) - lo) / cell).astype(int)
        x1, y1 = np.ceil((t[:, :2].max(0) - lo) / cell).astype(int)
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
        px, py = lo[0] + (gx + 0.5) * cell, lo[1] + (gy + 0.5) * cell
        v0, v1 = b - a, c - a
        den = v0[0] * v1[1] - v1[0] * v0[1]
        if abs(den) < 1e-9:
            continue
        qx, qy = px - a[0], py - a[1]
        u = (qx * v1[1] - v1[0] * qy) / den
        v = (v0[0] * qy - qx * v0[1]) / den
        ins = (u >= -0.02) & (v >= -0.02) & (u + v <= 1.02)
        if not ins.any():
            continue
        z = t[0, 2] + u * (t[1, 2] - t[0, 2]) + v * (t[2, 2] - t[0, 2])
        yy, xx = gy[ins], gx[ins]
        mask[yy, xx] = True
        zmap[yy, xx] = np.maximum(zmap[yy, xx], z[ins])
    return mask, zmap, lo, cell


def _shift(m, dy, dx):
    out = np.zeros_like(m)
    H, W = m.shape
    out[max(0, dy):H + min(0, dy), max(0, dx):W + min(0, dx)] = m[max(0, -dy):H + min(0, -dy), max(0, -dx):W + min(0, -dx)]
    return out


def _dilate(m):
    r = m.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            r |= _shift(m, dy, dx)
    return r


def _erode(m):
    r = m.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            r &= _shift(m, dy, dx)
    return r


def close_holes(m, n=2):
    for _ in range(n):
        m = _dilate(m)
    for _ in range(n):
        m = _erode(m)
    return m


def _labels(m):
    """Morceaux 4-connexes -> (etiquettes, {etiquette: nombre de pixels})."""
    lab = np.zeros(m.shape, np.int32)
    sizes, cur = {}, 0
    H, W = m.shape
    for y0, x0 in zip(*np.nonzero(m)):
        if lab[y0, x0]:
            continue
        cur += 1
        n, q = 0, deque([(y0, x0)])
        lab[y0, x0] = cur
        while q:
            y, x = q.popleft()
            n += 1
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                yy, xx = y + dy, x + dx
                if 0 <= yy < H and 0 <= xx < W and m[yy, xx] and not lab[yy, xx]:
                    lab[yy, xx] = cur
                    q.append((yy, xx))
        sizes[cur] = n
    return lab, sizes


def largest_component(m):
    lab, sizes = _labels(m)
    return lab == max(sizes, key=sizes.get) if sizes else m


def join_pieces(mask, max_gap_px, min_share=0.02):
    """Morceaux de route separes par une coupure courte (bande d'une autre surface, porte, trou) : relies a chaque
    endroit ou ils se touchent presque (moins de max_gap_px). Complete bridge_gaps quand les bords de la coupure sont
    irreguliers (les bouts du squelette ne se font plus face : Mystery Caves, route coupee deux fois -> la boucle
    trouvee etait un petit tour de 600 m). Seuls les gros morceaux (>= min_share de la route) sont relies.
    -> (masque complete, pixels ajoutes, nombre de liaisons)."""
    from PIL import Image, ImageDraw
    lab, sizes = _labels(mask)
    if not sizes:
        return mask, np.zeros(mask.shape, bool), 0
    total = sum(sizes.values())
    big = [k for k, n in sizes.items() if n >= min_share * total]
    if len(big) < 2:
        return mask, np.zeros(mask.shape, bool), 0
    edge = mask & ~_erode(mask)
    dm = depth(mask)
    width = 2 * float(np.median(dm[mask])) + 1          # largeur de route courante (pixels)
    border = {k: np.argwhere(edge & (lab == k)) for k in big}
    img = Image.fromarray(np.zeros(mask.shape, np.uint8))
    draw = ImageDraw.Draw(img)
    n = 0
    for i, a in enumerate(big):
        for b in big[i + 1:]:
            A, B = border[a], border[b]
            if not len(A) or not len(B):
                continue
            near = []                                           # (distance, pixel de A, pixel de B) sous le seuil
            for k in range(0, len(A), 256):
                d = np.linalg.norm(A[k:k + 256, None, :] - B[None, :, :], axis=2)
                j = d.argmin(1)
                dd = d[np.arange(len(j)), j]
                for t in np.nonzero(dd <= max_gap_px)[0]:
                    near.append((float(dd[t]), tuple(A[k + t]), tuple(B[j[t]])))
            # un lien par endroit de contact (les contacts a plus de 2 x max_gap l'un de l'autre sont distincts)
            near.sort()
            spots = []
            for dist, pa, pb in near:
                if all(math.hypot(pa[0] - s[1][0], pa[1] - s[1][1]) > 2 * max_gap_px for s in spots):
                    spots.append((dist, pa, pb))
            for dist, pa, pb in spots:
                if not _face_bridge(draw, A, B, pa, pb, dist, width):
                    w = max(3, int(2 * min(dm[_inner(dm, pa)], dm[_inner(dm, pb)])))
                    draw.line([(pa[1], pa[0]), (pb[1], pb[0])], fill=255, width=w)
                n += 1
    added = (np.asarray(img) > 0) & ~mask
    return mask | added, added, n


def _face_bridge(draw, A, B, pa, pb, dist, width):
    """Pont = enveloppe des deux bords qui se font face (pixels de bord A pres de pa, B pres de pb, a moins de ~l'ecart
    + une largeur de route l'un de l'autre). Un trait entre les deux pixels (ou bouts de squelette) les plus proches
    partait d'un coin quand les bouts de route sont en biais : le trace traversait le trou sur le cote de la route
    (Crash Cove). -> False si pas d'enveloppe (trait a tracer)."""
    reach, near_r = max(1.5 * dist, dist + width), dist + 2 * width
    face = []
    for P_, Q_, c in ((A, B, pa), (B, A, pb)):
        loc = P_[np.hypot(P_[:, 0] - c[0], P_[:, 1] - c[1]) <= near_r]
        if len(loc) and len(Q_):
            dq = np.min(np.linalg.norm(loc[:, None, :] - Q_[None, :, :], axis=2), axis=1) \
                if len(loc) * len(Q_) < 4e6 else np.full(len(loc), dist)
            face.append(loc[dq <= reach])
    face = np.concatenate(face) if face else np.zeros((0, 2))
    hull = _hull(face) if len(face) >= 3 else []
    if len(hull) < 3:
        return False
    draw.polygon([(float(q[1]), float(q[0])) for q in hull], fill=255)
    return True


def _end_bridge(draw, edge, dm, e, t):
    """Pont entre deux bouts de squelette : enveloppe des bords coupes autour de chaque bout (le squelette s'arrete a
    une demi-largeur du bout de la route : bord coupe et coins a moins de ~1,8 demi-largeur), en plus du trait."""
    face = []
    for c in (e, t):
        r = 1.8 * float(dm[_inner(dm, c)]) + 2
        face.append(edge[np.hypot(edge[:, 0] - c[0], edge[:, 1] - c[1]) <= r])
    face = np.concatenate(face)
    hull = _hull(face) if len(face) >= 3 else []
    if len(hull) >= 3:
        draw.polygon([(float(q[1]), float(q[0])) for q in hull], fill=255)


def _hull(P):
    """Enveloppe convexe (chaine monotone) de points (n, 2) -> sommets dans l'ordre."""
    pts = sorted(set(map(tuple, np.asarray(P).tolist())))
    if len(pts) < 3:
        return pts
    cross = lambda o, a, b: (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def join_cuts(mask, max_gap_px, blocked=None):
    """Route coupee a un seul endroit (en « C » : un seul morceau, ses deux bouts presque face a face) : deux bouts du
    squelette proches a vol d'oiseau mais tres loin le long de la route sont relies, sans exiger qu'ils pointent l'un
    vers l'autre (bords de coupure irreguliers : Dingo Canyon). blocked(p, q) -> True si un mur / obstacle se dresse
    entre les deux (route parallele derriere une separation : pas une coupure). -> (masque, pixels ajoutes, n)."""
    from PIL import Image, ImageDraw
    skel = thin(mask)
    ends = [tuple(p) for p in np.argwhere(skeleton_ends(skel))]
    if len(ends) < 2:
        return mask, np.zeros(mask.shape, bool), 0
    dm = depth(mask)
    H, W = mask.shape

    def along(a, limit):
        """Distance le long du squelette depuis a (pixels atteints en moins de limit pas)."""
        dist, q = {a: 0}, deque([a])
        while q:
            cur = q.popleft()
            if dist[cur] >= limit:
                continue
            for dy, dx in OFFS:
                p = (cur[0] + dy, cur[1] + dx)
                if 0 <= p[0] < H and 0 <= p[1] < W and skel[p] and p not in dist:
                    dist[p] = dist[cur] + 1
                    q.append(p)
        return dist
    reach = max_gap_px + 2 * float(np.median(dm[skel])) + 3
    edge = np.argwhere(mask & ~_erode(mask))
    E = np.array(ends)
    img = Image.fromarray(np.zeros(mask.shape, np.uint8))
    draw = ImageDraw.Draw(img)
    used, n = set(), 0
    for i, e in enumerate(ends):
        if i in used:
            continue
        d = np.linalg.norm(E - e, axis=1)
        cand = [j for j in np.argsort(d) if j != i and j not in used and 3 < d[j] <= reach]
        if not cand:
            continue
        near = along(e, int(8 * reach) + 20)
        for j in cand:
            t = ends[j]
            if t in near:                                 # meme bout de route (ou bavure) : pas une coupure
                continue
            k = max(2, int(d[j]))
            ys = np.round(np.linspace(e[0], t[0], k)).astype(int)
            xs = np.round(np.linspace(e[1], t[1], k)).astype(int)
            if (~mask[ys, xs]).sum() < 2 or (blocked is not None and blocked(e, t)):
                continue
            w = max(3, int(2 * min(dm[_inner(dm, e)], dm[_inner(dm, t)])))
            draw.line([(e[1], e[0]), (t[1], t[0])], fill=255, width=w)
            _end_bridge(draw, edge, dm, e, t)
            used |= {i, j}
            n += 1
            break
    added = (np.asarray(img) > 0) & ~mask
    return mask | added, added, n


RAMP_SLOPE = 0.47     # pente qu'un kart monte (~25 deg) : une rampe posee dans la coupure n'est pas un mur


def _wall_between(ground, zmap, lo, cell, rise=150.0, top=1500.0):
    """-> blocked(p, q) pour join_cuts : un sol plus de `rise` po au-dessus du chemin entre les deux bouts = mur,
    separation, rocher : les deux routes ne sont pas reliees. Le chemin suit le sol en continuite depuis le premier
    bout (on monte une pente de RAMP_SLOPE au plus, on redescend librement ; rien dessous : ligne droite) : une
    rampe / une marche posee dans la coupure (T901 Boo Lake : « StepJA », 2,1 m au-dessus de la ligne droite) se
    franchit, un mur (sol qui monte d'un coup) bloque toujours."""
    def z_at(p):
        win = zmap[max(0, p[0] - 4):p[0] + 5, max(0, p[1] - 4):p[1] + 5]
        ok = win[np.isfinite(win)]
        return float(ok.max()) if len(ok) else None

    def blocked(p, q):
        # mur = bloque dans les deux sens ; une rampe ne se suit souvent que depuis son bas (T901 : sens unique)
        return one_way(p, q) and one_way(q, p)

    def one_way(p, q):
        za, zb = z_at(p), z_at(q)
        if za is None or zb is None:
            return True
        n = 24
        # rampe seulement entre deux bouts de meme niveau (T901 : 1,7 m d'ecart) ; sinon ligne droite comme avant
        # (Polar Pass : bouts 54 m l'un au-dessus de l'autre = falaise, pas une coupure a relier)
        follow = abs(za - zb) <= 2 * rise
        climb = max(30.0, RAMP_SLOPE * math.hypot(q[0] - p[0], q[1] - p[1]) * cell / (n - 1)) if follow else 0.0
        level = za
        for u in np.linspace(0, 1, n):
            y, x = p[0] + (q[0] - p[0]) * u, p[1] + (q[1] - p[1]) * u
            wx, wy = lo[0] + (x + 0.5) * cell, lo[1] + (y + 0.5) * cell
            zi = za + (zb - za) * u
            hs = ground.heights(wx, wy)
            reach = [h for h in hs if level - 3 * climb <= h <= level + climb] if follow else []
            level = max(reach) if reach else zi             # sol suivi (le plus haut atteignable) ; vide : ligne droite
            ref = max(zi, level)
            if any(ref + rise < h <= ref + top for h in hs):
                return True
        return False
    return blocked


def _inner(dm, p, r=6):
    """Pixel le plus profond (le plus loin du bord) pres de p : largeur de la route a cet endroit."""
    y, x = p
    win = dm[max(0, y - r):y + r + 1, max(0, x - r):x + r + 1]
    k = np.unravel_index(int(win.argmax()), win.shape)
    return (max(0, y - r) + k[0], max(0, x - r) + k[1])


def fill_small_holes(m, keep_ratio=0.25, is_void=None):
    """Bouche les trous (zones hors route entourees de route) plus petits que keep_ratio x le plus grand :
    obstacles, rochers, piliers au milieu de la route. Le grand trou (l'interieur du circuit) reste. is_void(cells)
    -> True : vrai vide (eau, chute : rien de solide au niveau de la route) garde aussi, le trace le contourne
    (T901 Boo Lake : trou au milieu de l'ilot, traverse en ligne droite)."""
    H, W = m.shape
    lab = np.zeros(m.shape, np.int32)
    holes, cur = [], 0
    for y0, x0 in zip(*np.nonzero(~m)):
        if lab[y0, x0]:
            continue
        cur += 1
        cells, border, q = [], False, deque([(y0, x0)])
        lab[y0, x0] = cur
        while q:
            y, x = q.popleft()
            cells.append((y, x))
            if y in (0, H - 1) or x in (0, W - 1):
                border = True
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                yy, xx = y + dy, x + dx
                if 0 <= yy < H and 0 <= xx < W and not m[yy, xx] and not lab[yy, xx]:
                    lab[yy, xx] = cur
                    q.append((yy, xx))
        if not border:
            holes.append(cells)
    if not holes:
        return m
    big = max(len(h) for h in holes)
    out = m.copy()
    for h in holes:
        if len(h) < keep_ratio * big and not (is_void is not None and is_void(h)):
            ys, xs = zip(*h)
            out[list(ys), list(xs)] = True
    return out


def _void_test(ground, road, zmap, lo, cell, min_cells=500, solid_ratio=0.3):
    """-> is_void(cells) pour fill_small_holes : trou d'au moins min_cells pixels ou moins de solid_ratio des points
    ont la moindre surface de collision de 100 m sous la route a 38 m au-dessus (vrai vide : T901 Boo Lake, rien du
    tout dans le trou de l'ilot). Rocher, pilier, herbe ou terrain un peu plus bas (pistes du jeu) : le trou reste
    bouche comme avant (un seuil a 4 m sous la route changeait 13 pistes du jeu). min_cells = 500 pixels (~1100 m²,
    trou de l'ilot T901 : 2676) : un petit vide garde (Tiger Temple, 101) faisait une petite boucle qui piegeait le
    trace (37 % -> 10 % du parcours du jeu)."""
    def is_void(cells):
        if len(cells) < min_cells:
            return False
        ys, xs = np.array(cells).T
        y0, y1, x0, x1 = max(0, ys.min() - 3), ys.max() + 4, max(0, xs.min() - 3), xs.max() + 4
        z = zmap[y0:y1, x0:x1][road[y0:y1, x0:x1] & np.isfinite(zmap[y0:y1, x0:x1])]
        if not len(z):
            return False
        zr = float(np.median(z))
        pick = np.linspace(0, len(cells) - 1, min(80, len(cells))).astype(int)
        solid = sum(1 for i in pick if any(zr - 4000 <= h <= zr + 1500 for h in
                                            ground.heights(lo[0] + (xs[i] + 0.5) * cell, lo[1] + (ys[i] + 0.5) * cell)))
        return solid < solid_ratio * len(pick)
    return is_void


def _end_direction(s, e, back=12):
    """Direction (dy, dx) vers l'exterieur d'un bout de squelette : des pixels situes a `back` pas (le long du
    squelette) vers le bout. None si la branche est plus courte (petite branche, pas un bout de route)."""
    dist, q, far = {e: 0}, deque([e]), []
    H, W = s.shape
    while q:
        cur = q.popleft()
        if dist[cur] >= back:
            far.append(cur)
            continue
        for dy, dx in OFFS:
            p = (cur[0] + dy, cur[1] + dx)
            if 0 <= p[0] < H and 0 <= p[1] < W and s[p] and p not in dist:
                dist[p] = dist[cur] + 1
                q.append(p)
    if not far:
        return None
    d = np.subtract(e, np.mean(far, axis=0)).astype(float)
    return d / (np.linalg.norm(d) or 1.0)


def skeleton_ends(s):
    """Bouts du squelette : pixels dont les voisins forment un seul groupe (un bout en escalier a 2 ou 3 voisins
    colles en est un aussi), comme pour l'ebarbage."""
    nb = _neighbors(s)
    return s & ((nb <= 1) | ((_ring_groups(s) == 1) & (nb <= 3)))


def bridge_gaps(mask, max_gap_px, max_angle=35.0):
    """Trous dans la route (sous un saut, entre deux morceaux) : deux bouts de route qui se font face (le tremplin et
    la reception : chacun pointe vers l'autre, a moins de max_angle degres) a moins de max_gap_px, et dont le segment
    passe surtout hors de la route, sont relies. Une petite branche laterale ou une route parallele ne le sont pas.
    Le pont est dessine de la largeur de la route au tremplin.
    -> (masque complete, pixels du pont (masque), nombre de sauts relies)."""
    from PIL import Image, ImageDraw
    skel = thin(mask)
    ends = []
    for p in np.argwhere(skeleton_ends(skel)):
        d = _end_direction(skel, tuple(p))
        if d is not None:
            ends.append((tuple(p), d))
    dm = depth(mask)
    # le squelette s'arrete a une demi-largeur de route avant chaque bord du trou : l'ecart entre les bouts est le
    # trou PLUS une largeur de route
    reach = 1.1 * max_gap_px + 3 + 2 * float(np.median(dm[skel])) if skel.any() else max_gap_px
    img = Image.fromarray(np.zeros(mask.shape, np.uint8))
    draw = ImageDraw.Draw(img)
    seam_img = Image.fromarray(np.zeros(mask.shape, np.uint8))
    seam_draw = ImageDraw.Draw(seam_img)
    cos_max = math.cos(math.radians(max_angle))
    # toutes les paires de bouts qui se font face ; la plus proche d'abord, chaque bout relie une seule fois. Une
    # fente (un ou deux pixels de vide entre deux morceaux de route jointifs, T901) est une couture, pas un saut :
    # sans elle, le bout de route le plus proche suivant etait relie a la place (route coupee en travers)
    pairs = []
    for i, (e, d) in enumerate(ends):
        for j, (t, dt) in enumerate(ends):
            if j <= i:
                continue
            v = np.subtract(t, e).astype(float)
            dist = float(np.linalg.norm(v))
            if not 1 < dist <= reach:
                continue
            u = v / dist
            if u @ d < cos_max or -u @ dt < cos_max:    # chacun doit pointer vers l'autre
                continue
            k = max(2, int(dist))
            ys = np.round(np.linspace(e[0], t[0], k)).astype(int)
            xs = np.round(np.linspace(e[1], t[1], k)).astype(int)
            gap = int((~mask[ys, xs]).sum())
            if gap > 1.1 * max_gap_px + 3:               # trou trop long
                continue
            pairs.append((dist, gap < 3, i, j))
    # un saut relie deux bouts que la route ne relie autrement que par le reste du tour ; deux bouts deja relies par
    # un court chemin de route (T901 : bout d'une diagonale et route voisine, 300 px par la boucle en V) : le pont
    # serait un raccourci, et refermerait le vide entre les deux (bouche ensuite comme un petit trou)
    near = max(60, int(0.3 * skel.sum()))
    reach_cache = {}

    def road_reach(p):
        if p not in reach_cache:
            seen, q = {p: 0}, deque([p])
            H, W = mask.shape
            while q:
                cur = q.popleft()
                if seen[cur] >= near:
                    continue
                for dy, dx in OFFS:
                    r = (cur[0] + dy, cur[1] + dx)
                    if 0 <= r[0] < H and 0 <= r[1] < W and mask[r] and r not in seen:
                        seen[r] = seen[cur] + 1
                        q.append(r)
            reach_cache[p] = seen
        return reach_cache[p]
    n, used = 0, set()
    edge = np.argwhere(mask & ~_erode(mask))
    for dist, seam, i, j in sorted(pairs):
        if i in used or j in used:
            continue
        if not seam and ends[j][0] in road_reach(ends[i][0]):
            continue
        used |= {i, j}
        e, t = ends[i][0], ends[j][0]
        w = max(3, int(2 * min(dm[e], dm[t])))
        if seam:
            seam_draw.line([(e[1], e[0]), (t[1], t[0])], fill=255, width=w)
            continue
        draw.line([(e[1], e[0]), (t[1], t[0])], fill=255, width=w)
        _end_bridge(draw, edge, dm, e, t)
        n += 1
    seam = np.asarray(seam_img) > 0
    bridge = (np.asarray(img) > 0) & ~mask & ~seam
    return mask | bridge | seam, bridge, n


def depth(m):
    """Nombre d'erosions avant disparition (≈ distance au bord, en pixels)."""
    d = np.zeros(m.shape, np.int32)
    cur = m.copy()
    while cur.any():
        d += cur
        cur = _erode(cur)
    return d


def thin(m):
    """Squelette (Zhang-Suen), vectorise."""
    img = m.astype(np.uint8)
    while True:
        changed = False
        for step in (0, 1):
            P = [_shift(img, dy, dx) for dy, dx in ((1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1), (0, 1), (1, 1))]
            # voisins dans l'ordre P2..P9 (haut, haut-droite, droite...) avec y vers le bas de la grille
            p2, p3, p4, p5, p6, p7, p8, p9 = P
            B = sum(P)
            seq = [p2, p3, p4, p5, p6, p7, p8, p9, p2]
            A = sum(((seq[i] == 0) & (seq[i + 1] == 1)).astype(np.uint8) for i in range(8))
            if step == 0:
                c1, c2 = p2 * p4 * p6, p4 * p6 * p8
            else:
                c1, c2 = p2 * p4 * p8, p2 * p6 * p8
            rm = (img == 1) & (B >= 2) & (B <= 6) & (A == 1) & (c1 == 0) & (c2 == 0)
            if rm.any():
                img[rm] = 0
                changed = True
        if not changed:
            return img.astype(bool)


RING = ((1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1), (0, 1), (1, 1))   # voisins en tournant


def _neighbors(s):
    return sum(_shift(s, dy, dx).astype(np.int32) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx)


def _ring_groups(s):
    """Nombre de groupes de voisins autour de chaque pixel (transitions 0 -> 1 sur l'anneau des 8 voisins)."""
    P = [_shift(s, dy, dx) for dy, dx in RING]
    return sum((~P[i] & P[(i + 1) % 8]).astype(np.int32) for i in range(8))


def prune(s):
    """Retire les impasses jusqu'a ce qu'il ne reste que des boucles. Bout de ligne = pixel dont les voisins
    forment un seul groupe (un bout en escalier a 2 voisins colles : ce n'est pas un passage)."""
    s = s.copy()
    while True:
        nb = _neighbors(s)
        ends = s & ((nb <= 1) | ((_ring_groups(s) == 1) & (nb <= 3)))
        if not ends.any():
            return s
        s[ends] = False


def walk_loop(s, dmap, start_px, heading):
    """Parcours de la boucle du squelette depuis start_px dans la direction `heading` (radians, repere monde :
    x vers la droite, y vers le haut ; dans la grille y croit aussi avec l'indice de ligne)."""
    pts = np.argwhere(s)
    if not len(pts):
        raise ValueError('aucune boucle trouvee dans la route (circuit ferme ?)')
    d2 = ((pts - np.array(start_px)) ** 2).sum(1)
    start = tuple(pts[int(d2.argmin())])
    H, W = s.shape

    def options(cur, direction, visited):
        cand = []
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if not (dy or dx):
                    continue
                y, x = cur[0] + dy, cur[1] + dx
                if 0 <= y < H and 0 <= x < W and s[y, x] and (y, x) not in visited:
                    v = np.array([dy, dx], float) / math.hypot(dy, dx)
                    align = float(v @ direction)
                    if align > -0.2:                       # pas de demi-tour
                        cand.append((align + 0.05 * dmap[y, x], (y, x), v))
        return [c[1:] for c in sorted(cand, key=lambda c: -c[0])]

    # parcours en profondeur : meilleure branche d'abord (alignee + large), retour au carrefour sur impasse
    d0 = np.array([math.sin(heading), math.cos(heading)])                 # (dy, dx)
    path, dirs, visited = [start], [d0], {start}
    alts = [options(start, d0, visited)]
    for _ in range(4 * int(s.sum()) + 100):
        cur, direction = path[-1], dirs[-1]
        if len(path) > 30 and max(abs(cur[0] - start[0]), abs(cur[1] - start[1])) <= 1:
            return path                                                  # boucle fermee
        if not alts[-1]:
            path.pop(); dirs.pop(); alts.pop()                           # impasse : retour
            if not path:
                break
            continue
        p, v = alts[-1].pop(0)
        nd = 0.7 * direction + 0.3 * v
        nd /= np.linalg.norm(nd)
        visited.add(p)
        path.append(p); dirs.append(nd)
        # retour au depart autorise une fois la boucle assez longue
        opts = options(p, nd, visited - ({start} if len(path) > 30 else set()))
        alts.append(opts)
    raise ValueError('impossible de refermer la boucle depuis le depart : verifie que la route forme un circuit ferme')


# -- parcours en graphe : routes qui se croisent (pont au-dessus de la route) ---------------------------------
OFFS = [(dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx]


def _components(pixels):
    """Groupes 8-connexes d'un ensemble de pixels -> {pixel: numero}."""
    lab, n = {}, 0
    for p in pixels:
        if p in lab:
            continue
        q = deque([p])
        lab[p] = n
        while q:
            y, x = q.popleft()
            for dy, dx in OFFS:
                r = (y + dy, x + dx)
                if r in pixels and r not in lab:
                    lab[r] = n
                    q.append(r)
        n += 1
    return lab


def skeleton_graph(s, dmap):
    """Squelette -> (noeuds {pixel de carrefour: noeud}, troncons [{'a', 'b', 'px': pixels de a vers b, 'w'}]).
    Carrefour = pixel dont les voisins forment au moins 3 groupes. Un croisement en X sort de l'amincissement en
    deux Y relies par un bout de la largeur de la route : les carrefours relies par un troncon plus court que la
    largeur de route sont fusionnes (un seul noeud a 4 branches)."""
    pix = set(map(tuple, np.argwhere(s)))
    junc = {tuple(p) for p in np.argwhere(s & (_ring_groups(s) >= 3))}
    if not junc:
        return {}, []
    node = _components(junc)

    def trace(j, q):
        chain, seen = [j, q], {j, q}
        while True:
            cur = chain[-1]
            nb = [(cur[0] + dy, cur[1] + dx) for dy, dx in OFFS]
            nb = [r for r in nb if r in pix and (r not in seen or (r == j and len(chain) >= 4))]   # boucle : retour a j
            hit = [r for r in nb if r in junc and not (r == j and len(chain) < 4)]
            if hit:
                chain.append(hit[0])
                return chain
            nb = [r for r in nb if r not in junc]
            if not nb:
                return None                                  # bout perdu (ne devrait pas rester apres ebarbage)
            prev = chain[-2]                                 # escalier : le voisin le plus loin du pixel precedent
            nxt = max(nb, key=lambda r: (r[0] - prev[0]) ** 2 + (r[1] - prev[1]) ** 2)
            chain.append(nxt)
            seen.add(nxt)
    edges, keys = [], []
    for j in junc:
        for dy, dx in OFFS:
            q = (j[0] + dy, j[1] + dx)
            if q not in pix or q in junc:
                continue
            ch = trace(j, q)
            if ch is None:
                continue
            key = frozenset(ch[1:-1])
            # meme troncon trace depuis l'autre bout (escaliers parcourus un peu differemment) : deja connu
            if key in keys or any(len(key & k) > 0.6 * min(len(key), len(k)) for k in keys):
                continue
            keys.append(key)
            edges.append({'a': node[ch[0]], 'b': node[ch[-1]], 'px': ch,
                          'w': float(np.mean([dmap[p] for p in ch]))})
    # fusion des carrefours voisins (croisement en X)
    width = float(np.median([dmap[p] for p in pix]))
    short = max(4.0, 2.2 * width)
    parent = {}
    find = lambda k: k if parent.get(k, k) == k else find(parent[k])
    for e in edges:
        if e['a'] != e['b'] and len(e['px']) < short:
            parent[find(e['a'])] = find(e['b'])
    out = []
    for e in edges:
        a, b = find(e['a']), find(e['b'])
        if a == b and len(e['px']) < short:
            continue                                         # bout absorbe par le noeud fusionne
        out.append(dict(e, a=a, b=b))
    return {p: find(k) for p, k in node.items()}, out


def walk_graph(s, dmap, start_px, heading, k=10):
    """Boucle de course sur le graphe du squelette : depuis le troncon du depart dans la direction de course,
    a chaque carrefour le troncon pas encore emprunte le plus dans l'axe (puis le plus large). Un carrefour peut etre
    traverse plusieurs fois (huit, route qui repasse sous un pont), un troncon une seule fois. Candidate en plus : la
    boucle la plus longue sans demi-tour (_longest_cycle) ; road_loop garde la plus longue une fois lissee.
    -> [pixels [(y, x)] par boucle candidate], ou None si le squelette n'a pas de carrefour (boucle simple : walk_loop)."""
    nodes, edges = skeleton_graph(s, dmap)
    if not edges:
        return None
    on_edge = {}
    for i, e in enumerate(edges):
        for j, p in enumerate(e['px'][1:-1], 1):
            on_edge[p] = (i, j)
    pts = np.array(list(on_edge))
    start = tuple(pts[int(((pts - np.array(start_px)) ** 2).sum(1).argmin())])
    ei, si = on_edge[start]
    d0 = np.array([math.sin(heading), math.cos(heading)])            # (dy, dx)
    px = edges[ei]['px']
    t = np.subtract(px[min(len(px) - 1, si + 3)], px[max(0, si - 3)])
    forward = float(t @ d0) >= 0
    unit = lambda v: np.asarray(v, float) / max(1e-9, float(np.linalg.norm(v)))
    wmax = max(e['w'] for e in edges)
    # boucle la plus longue sans demi-tour, ou le choix glouton (ci-dessous) s'il fait plus long : un vrai virage
    # en epingle a un carrefour (Cortex Castle) peut passer pour un demi-tour
    longest = _longest_cycle(edges, ei, si, forward, k)
    path = list(px[si:]) if forward else list(px[si::-1])
    node = edges[ei]['b'] if forward else edges[ei]['a']
    used = {ei}
    for _ in range(len(edges) + 2):
        tin = unit(np.subtract(path[-1], path[max(0, len(path) - 1 - k)]))
        best = None
        for i, e in enumerate(edges):
            for fwd in (True, False):
                if (e['a'] if fwd else e['b']) != node:
                    continue
                if i in used and not (i == ei and fwd == forward):
                    continue
                c = e['px'] if fwd else e['px'][::-1]
                tout = unit(np.subtract(c[min(k, len(c) - 1)], c[0]))
                score = float(tin @ tout) + 0.15 * e['w'] / wmax
                if best is None or score > best[0]:
                    best = (score, i, fwd, c)
        if best is None:                                             # bloque : ancien parcours
            return [longest] if longest is not None else None
        _, i, fwd, c = best
        gap = np.subtract(c[0], path[-1])                            # traversee du carrefour (noeud fusionne)
        n = int(max(abs(gap[0]), abs(gap[1])))
        path += [(int(round(path[-1][0] + gap[0] * u / n)), int(round(path[-1][1] + gap[1] * u / n))) for u in range(1, n)]
        if i == ei:                                                  # retour sur le troncon du depart : boucle fermee
            path += list(c[:si + 1] if fwd else c[:len(c) - si])
            return [p for p in (path[:-1], longest) if p is not None]
        path += list(c)
        used.add(i)
        node = edges[i]['b'] if fwd else edges[i]['a']
    return [longest] if longest is not None else None


MAX_TURN = -0.3          # cos : virage de plus de ~107 deg a un carrefour = demi-tour, interdit
MAX_EXPAND = 200000      # etats explores au plus (sinon : choix glouton de walk_graph)


def _longest_cycle(edges, ei, si, forward, k=10):
    """Boucle la plus longue depuis le troncon du depart (dans le sens de course) jusqu'a y revenir, chaque troncon
    une fois, sans demi-tour aux carrefours. Le vrai tour passe partout ; un raccourci, une route interieure ou un
    detour evite sont plus courts (Turbo Track : la route du milieu coupait 1,5 km ; Android Alley, Cortex Castle).
    A longueur presque egale (5 %), la plus droite. -> pixels, ou None (pas de boucle / recherche trop longue)."""
    unit = lambda v: np.asarray(v, float) / max(1e-9, float(np.linalg.norm(v)))
    by_node = {}
    for i, e in enumerate(edges):
        by_node.setdefault(e['a'], []).append((i, True))
        by_node.setdefault(e['b'], []).append((i, False))
    seq = lambda i, fwd: edges[i]['px'] if fwd else edges[i]['px'][::-1]
    tout = {(i, f): unit(np.subtract(seq(i, f)[min(k, len(seq(i, f)) - 1)], seq(i, f)[0])) for i in range(len(edges)) for f in (True, False)}
    tin = {(i, f): unit(np.subtract(seq(i, f)[-1], seq(i, f)[max(0, len(seq(i, f)) - 1 - k)])) for i in range(len(edges)) for f in (True, False)}
    first = seq(ei, forward)
    s0 = si if forward else len(first) - 1 - si          # position du depart dans le troncon parcouru
    head = len(first) - s0                                # du depart au bout du troncon
    best = [None, -1.0, 0.0]                              # (chemin de troncons, longueur, rectitude)
    expand = [0]

    def dfs(node, last, used, length, straight, route):
        expand[0] += 1
        if expand[0] > MAX_EXPAND:
            return
        for i, fwd in by_node.get(node, []):
            turn = float(tin[last] @ tout[(i, fwd)])
            if turn < MAX_TURN:
                continue
            if i == ei:
                if fwd != forward:
                    continue
                total = length + s0
                better = total > best[1] * 1.05 or (total > best[1] * 0.95 and straight + turn > best[2])
                if better:
                    best[:] = [route + [(i, fwd)], total, straight + turn]
                continue
            if i in used:
                continue
            e = edges[i]
            dfs(e['b'] if fwd else e['a'], (i, fwd), used | {i}, length + len(e['px']), straight + turn, route + [(i, fwd)])
    dfs(edges[ei]['b'] if forward else edges[ei]['a'], (ei, forward), {ei}, head, 0.0, [(ei, forward)])
    if best[0] is None or expand[0] > MAX_EXPAND:
        return None
    path = list(first[s0:])
    for i, fwd in best[0][1:]:
        c = seq(i, fwd)
        gap = np.subtract(c[0], path[-1])                 # traversee du carrefour (noeud fusionne)
        n = int(max(abs(gap[0]), abs(gap[1])))
        path += [(int(round(path[-1][0] + gap[0] * u / n)), int(round(path[-1][1] + gap[1] * u / n))) for u in range(1, n)]
        path += list(c[:s0 + 1]) if i == ei else list(c)
    return path[:-1]


def _smooth_closed(P, k):
    n = len(P)
    if n < 3:
        return P
    out = np.zeros_like(P)
    for i in range(-k, k + 1):
        out += np.roll(P, i, axis=0)
    return out / (2 * k + 1)


def _resample_closed(P, step):
    seg = np.linalg.norm(np.roll(P, -1, axis=0) - P, axis=1)
    cum = np.concatenate([[0], np.cumsum(seg)])
    total = cum[-1]
    out = []
    Q = np.vstack([P, P[:1]])
    for s in np.arange(0, total, step):
        i = int(np.searchsorted(cum, s, side='right') - 1)
        k = (s - cum[i]) / max(seg[i], 1e-9)
        out.append(Q[i] + (Q[i + 1] - Q[i]) * k)
    return np.array(out), total


def layout(loop, n_sections, overlap=2000.0, spacing=2500.0, finish_lift=660.0, height=2600.0, margin=800.0,
           avoid=None):
    """Decoupe une boucle (points tous les ~300 po, depart = ligne d'arrivee) en n sections egales. avoid(point) :
    obstacle touche (points de controle resserres la, voir ai_gen.fit_controls).
    -> {'sections': [points de controle de la spline de position (chevauchent de `overlap` les transitions)],
        'transitions': [{position, yaw, dimensions}] (la 1re = ligne d'arrivee, au debut de la boucle),
        'section_paths': [points denses de chaque section (pour placer les reapparitions)]}"""
    from ai_gen import fit_controls
    P = np.array(loop['points'], np.float64)
    n = len(P)
    seg = np.linalg.norm(np.roll(P[:, :2], -1, axis=0) - P[:, :2], axis=1)
    cum = np.concatenate([[0], np.cumsum(seg)])
    total = cum[-1]
    step = total / n
    hw = np.array(loop['half_widths'])
    idx_at = lambda s: int(round((s % total) / step)) % n
    sections, transitions, paths = [], [], []
    for k in range(n_sections):
        s0, s1 = k * total / n_sections, (k + 1) * total / n_sections
        ids = [idx_at(s) for s in np.arange(s0 - overlap, s1 + overlap + 1, step)]
        sections.append(fit_controls([list(P[i]) for i in ids], spacing, avoid=avoid))
        paths.append([list(P[i]) for i in (idx_at(s) for s in np.arange(s0, s1, step))])
        i0 = idx_at(s0)
        t = P[(i0 + 1) % n, :2] - P[(i0 - 1) % n, :2]
        yaw = math.atan2(t[1], t[0])
        w = 2 * float(hw[max(0, i0 - 3):i0 + 4].max()) + margin
        transitions.append({'position': [float(P[i0, 0]), float(P[i0, 1]), float(P[i0, 2]) + finish_lift],
                            'yaw': yaw, 'dimensions': [1000.0 if k == 0 else 500.0, w, height]})
    return {'sections': sections, 'transitions': transitions, 'section_paths': paths}


def spread_on_path(path, count, lift=50.0):
    """`count` poses (position, cap) reparties le long d'un chemin (milieu de chaque part egale)."""
    P = np.array(path, np.float64)
    out = []
    for j in range(count):
        i = min(len(P) - 1, int((j + 0.5) * len(P) / count))
        t = P[min(len(P) - 1, i + 1), :2] - P[max(0, i - 1), :2]
        out.append({'pos': [float(P[i, 0]), float(P[i, 1]), float(P[i, 2]) + lift], 'yaw': math.atan2(t[1], t[0])})
    return out


def check_extent(tris, cell=CELL):
    """Erreur claire si la route est minuscule ou geante (map importee a une mauvaise echelle)."""
    T = np.asarray(tris, np.float64)
    ext = float((T[:, :, :2].max((0, 1)) - T[:, :, :2].min((0, 1))).max())
    if ext < 60 * cell:
        raise ValueError(f'route minuscule : {ext / 39.37:.0f} m d\'un bout a l\'autre (un circuit fait des centaines de '
                         f'metres) — la map a ete importee a une echelle trop petite : re-importe-la (echelle proposee '
                         f'd\'apres la route)')
    if ext > MAX_EXTENT:
        # a l'echelle 1 au lieu de 0,1 (map3 : 4 km), l'image de la route faisait 2 700 x 2 700 pixels et
        # l'amincissement ne finissait jamais (serveur bloque, 10 Go de memoire)
        raise ValueError(f'route geante : {ext / 39.37:.0f} m d\'un bout a l\'autre (un circuit CTR : quelques centaines '
                         f'de metres) — la map a ete importee a une echelle trop grande : annule l\'import et '
                         f're-importe-la a l\'echelle proposee')


def _guide_path(guide, raw, dmap, lo, cell, start_xy, heading, snap=8 * 39.37):
    """Trace dessine par l'utilisateur (vue de dessus de l'editeur, boucle fermee [[x, y]]) -> boucle lissee : chaque
    point sur la route est ramene vers le milieu de la route (au plus `snap` po, le long de la normale) ; ceux hors de
    la route (au-dessus d'un trou) restent ou ils sont. Depart = point le plus proche de la ligne d'arrivee, sens de
    course = heading."""
    G = np.asarray(guide, np.float64)[:, :2]
    if len(G) < 8:
        raise ValueError('dessin trop court : trace tout le tour (ou un morceau a corriger) sur l\'apercu')
    G, _ = _resample_closed(G, cell)
    G = _smooth_closed(G, 2)
    H, W = raw.shape
    pix = lambda p: (int((p[1] - lo[1]) / cell), int((p[0] - lo[0]) / cell))
    inside = lambda iy, ix: 0 <= iy < H and 0 <= ix < W
    t = np.roll(G, -1, axis=0) - np.roll(G, 1, axis=0)
    t /= np.maximum(np.linalg.norm(t, axis=1), 1e-9)[:, None]
    out = G.copy()
    offs = np.arange(-snap, snap + cell, cell)
    for i, (p, d) in enumerate(zip(G, t)):
        iy, ix = pix(p)
        if not (inside(iy, ix) and raw[iy, ix]):
            continue
        nrm = np.array([-d[1], d[0]])
        best, best_d = 0.0, dmap[iy, ix]
        for side in (1, -1):                       # vers chaque bord, tant qu'on reste sur la route
            for o in offs[offs > 0]:
                q = p + nrm * o * side
                jy, jx = pix(q)
                if not (inside(jy, jx) and raw[jy, jx]):
                    break
                if dmap[jy, jx] > best_d:
                    best, best_d = o * side, dmap[jy, jx]
        out[i] = p + nrm * best
    P = _smooth_closed(out, max(2, int(round(600 / cell))))
    k = int(np.argmin(np.linalg.norm(P - np.asarray(start_xy[:2], np.float64), axis=1)))
    P = np.roll(P, -k, axis=0)
    ahead = P[min(len(P) - 1, max(1, int(round(1500 / cell))))] - P[0]
    if ahead @ np.array([math.cos(heading), math.sin(heading)]) < 0:
        P = np.roll(P[::-1], 1, axis=0)
    return P


def preview_png(raw, lo, cell, pts, air, max_px=900):
    """Vue de dessus pour l'editeur (nord en haut) : route en gris, parcours en jaune (rouge au-dessus d'un trou),
    depart en vert. -> {png (base64), x0, y1, px (po par pixel), w, h} : pixel (u, v) = monde
    (x0 + (u + 0.5) * px, y1 - (v + 0.5) * px)."""
    import base64
    import io
    from PIL import Image, ImageDraw
    H, W = raw.shape
    f = max(1, int(math.ceil(max(H, W) / max_px)))           # pixels de route par pixel d'image
    m = raw[:H - H % f or H, :W - W % f or W]
    if f > 1:
        m = m.reshape(m.shape[0] // f, f, m.shape[1] // f, f).any((1, 3))
    m = m[::-1]                                              # nord en haut
    h, w = m.shape
    img = Image.new('RGB', (w, h), (22, 25, 30))
    img.paste(Image.new('RGB', (w, h), (92, 98, 110)), mask=Image.fromarray((m * 255).astype(np.uint8)))
    px = cell * f
    y1 = lo[1] + h * px
    uv = lambda p: ((p[0] - lo[0]) / px - 0.5, (y1 - p[1]) / px - 0.5)
    d = ImageDraw.Draw(img)
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        d.line([uv(a), uv(b)], fill=(255, 80, 80) if air[i] or air[(i + 1) % n] else (242, 177, 52), width=3)
    for i in range(0, n, max(1, n // 24)):                   # sens de course
        a, b = np.array(uv(pts[i])), np.array(uv(pts[(i + 2) % n]))
        v = b - a
        if np.linalg.norm(v) < 1e-6:
            continue
        v /= np.linalg.norm(v)
        c, nrm = a + v * 4, np.array([-v[1], v[0]])
        d.polygon([tuple(c + v * 6), tuple(c - v * 3 + nrm * 5), tuple(c - v * 3 - nrm * 5)], fill=(255, 220, 120))
    s = uv(pts[0])
    d.ellipse([s[0] - 7, s[1] - 7, s[0] + 7, s[1] + 7], fill=(95, 207, 128), outline=(255, 255, 255), width=2)
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    return {'png': base64.b64encode(buf.getvalue()).decode(), 'x0': float(lo[0]), 'y1': float(y1), 'px': float(px),
            'w': w, 'h': h}


MARCH_FAN = (0, 8, -8, 16, -16, 24, -24, 32, -32, 44, -44, 56, -56, 68, -68)    # degres essayes autour de la direction
MARCH_MIN_STEPS = 40
MARCH_MAX_GAP = 80 * 39.37      # sauts franchis (comme le second essai de route_layout : T114 a un saut de 50 m)
MARCH_OVERLAP_DZ = 315.0        # 8 m d'ecart de hauteur au meme endroit vu de dessus : deux passages l'un sur l'autre


def _march_3d(q, start_xy, start_z, heading, step=300.0, scan=60.0, max_gap=0.0, max_half=2400.0):
    """Suivi de la route en 3D, en restant sur son niveau : la vue de dessus (squelette) ne voit qu'un anneau dans une
    spirale qui monte (T114 importee : 2 tours superposes, 3 niveaux a -63, -8 et +44 m ; tour trouve : 596 m, l'anneau).
    Chaque pas : point suivant sur le meme niveau dans l'axe (sinon en tournant), recentre entre les bords de la route a ce
    niveau ; coupure de la route : ligne droite jusqu'a max_gap. q : GroundQuery des triangles de la route.
    -> {'points': [[x, y, z]], 'air': [bool], 'length': po} si le tour se referme, sinon None."""
    def level(x, y, z, tol):
        c = [h for h in q.heights(x, y) if abs(h - z) <= tol]
        return min(c, key=lambda h: abs(h - z)) if c else None

    def half_width(x, y, z, nx, ny, sign):
        o, zc = 0.0, z
        while o < max_half:
            h = level(x + nx * sign * (o + scan), y + ny * sign * (o + scan), zc, scan * 0.9 + 20)
            if h is None:
                break
            zc, o = h, o + scan
        return o

    def centred(x, y, z, dx, dy):
        nx, ny = -dy, dx
        shift = (half_width(x, y, z, nx, ny, 1) - half_width(x, y, z, nx, ny, -1)) / 2
        shift = max(-0.6 * step, min(0.6 * step, shift))
        cx, cy = x + nx * shift, y + ny * shift
        return cx, cy, level(cx, cy, z, scan + 40) or z

    x, y = float(start_xy[0]), float(start_xy[1])
    here = q.heights(x, y)
    if not here:
        return None
    z = min(here, key=lambda h: abs(h - start_z)) if start_z is not None else max(here)
    d0 = np.array([math.cos(heading), math.sin(heading)])
    d = d0.copy()
    x, y, z = centred(x, y, z, *d)
    start = (x, y, z)
    pts, air = [[x, y, z]], [False]
    tol = step * 0.75 + 60
    for _ in range(6000):
        px, py, pz = pts[-1]
        hit = None
        for deg in MARCH_FAN:
            c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
            r = np.array([d[0] * c - d[1] * s, d[0] * s + d[1] * c])
            h = level(px + r[0] * step, py + r[1] * step, pz, tol)
            if h is not None:
                hit = (px + r[0] * step, py + r[1] * step, h, r)
                break
        if hit is None:                                     # coupure : on continue tout droit jusqu'a la reprise
            # direction : celle des derniers metres (le bord irregulier du bout de route fausse le recentrage)
            back = next((p for p in pts[max(0, len(pts) - 9):] if p[2] is not None), pts[-1])
            chord = np.array([px - back[0], py - back[1]])
            dj = chord / np.linalg.norm(chord) if np.linalg.norm(chord) > step else d
            for g in np.arange(2 * step, max(max_gap, 0) + step, step):
                for deg in (0, 6, -6, 12, -12, 20, -20):
                    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
                    r = np.array([dj[0] * c - dj[1] * s, dj[0] * s + dj[1] * c])
                    qx, qy = px + r[0] * g, py + r[1] * g
                    h = level(qx, qy, pz, g * 0.6 + 200)
                    if h is not None:
                        n = int(g / step)
                        for u in range(1, n):
                            pts.append([px + r[0] * step * u, py + r[1] * step * u, None])
                            air.append(True)
                        hit = (qx, qy, h, r)
                        break
                if hit is not None:
                    break
            if hit is None:
                return None
        cx, cy, cz = centred(hit[0], hit[1], hit[2], hit[3][0], hit[3][1])
        last = pts[-1]
        v = np.array([cx - last[0], cy - last[1]])
        nv = float(np.linalg.norm(v))
        if nv < 1e-6:
            return None
        d = 0.5 * d + 0.5 * v / nv
        d /= np.linalg.norm(d)
        n = len(pts)
        if n >= MARCH_MIN_STEPS and math.hypot(cx - start[0], cy - start[1]) < 1.5 * step and abs(cz - start[2]) < tol and d @ d0 > 0.2:
            P = np.array([[p[0], p[1], p[2] if p[2] is not None else np.nan] for p in pts])
            xy = _smooth_closed(P[:, :2], 2)
            ok = ~np.isnan(P[:, 2])
            z3 = np.interp(np.arange(n), np.nonzero(ok)[0], P[ok, 2])
            seg = np.linalg.norm(np.diff(np.column_stack([xy, z3]), axis=0, append=[[*xy[0], z3[0]]]), axis=1)
            return {'points': np.column_stack([xy, z3]).tolist(), 'air': air, 'length': float(seg.sum())}
        recent = np.array([[p[0], p[1], p[2] if p[2] is not None else 1e12] for p in pts[:max(0, n - 20)]])
        if len(recent) and ((np.hypot(recent[:, 0] - cx, recent[:, 1] - cy) < 0.7 * step) & (np.abs(recent[:, 2] - cz) < tol)).any():
            return None                                     # repasse sur son propre trace : demi-tour ou impasse
        pts.append([cx, cy, cz])
        air.append(False)
    return None


def _overlaps_itself(points, step=300.0):
    """Le tour passe-t-il au-dessus de lui-meme (meme endroit vu de dessus, hauteurs nettement differentes) ?"""
    P = np.asarray(points, np.float64)
    n = len(P)
    for i in range(0, n, 2):
        near = np.hypot(P[:, 0] - P[i, 0], P[:, 1] - P[i, 1]) < 2 * step
        far = np.minimum(np.abs(np.arange(n) - i), n - np.abs(np.arange(n) - i)) > 20
        if (near & far & (np.abs(P[:, 2] - P[i, 2]) > MARCH_OVERLAP_DZ)).any():
            return True
    return False


def road_loop(tris, start_xy, heading, ground=None, step=300.0, cell=CELL, start_z=None, max_gap=0.0, min_z=None,
              guide=None):
    """Boucle centrale de la route (voir l'en-tete du module). `ground` : GroundQuery pour poser le trace sur
    la route ; start_z : hauteur du sol au depart (sinon hauteur max de la route a cet endroit). max_gap (po) :
    trous franchis (saut au-dessus d'un vide, morceaux de route separes) : le trace continue en ligne droite
    jusqu'au morceau suivant, hauteur interpolee entre le tremplin et la reception ; 0 = aucun. min_z : plancher de
    chute du monde (les niveaux de route dessous sont ignores). guide : trace dessine sur l'apercu ([[x, y]], boucle) :
    remplace la recherche de la ligne centrale (voir _guide_path) ; hors de la route = au-dessus d'un trou."""
    check_extent(tris, cell)
    progress.step('image de la route', 0.05)
    mask, zmap, lo, cell = rasterize(tris, cell)
    raw = mask                                          # route reelle (sans les ponts au-dessus des trous)
    progress.step('nettoyage de la route', 0.25)
    closed = close_holes(mask, 2)
    bridge, n_jumps = np.zeros(mask.shape, bool), 0
    if max_gap > 0:
        closed, bridge, n_jumps = bridge_gaps(closed, max_gap / cell)
        closed, joined, _ = join_pieces(closed, max_gap / cell)
        bridge |= joined                                # hauteur interpolee puis posee sur le sol, comme un saut
        if ground is not None:
            closed, joined, _ = join_cuts(closed, max_gap / cell, _wall_between(ground, zmap, lo, cell))
            bridge |= joined
    road = largest_component(closed)
    dmap = depth(road)                                  # largeur reelle (avant bouchage des obstacles)
    start_px = ((start_xy[1] - lo[1]) / cell, (start_xy[0] - lo[0]) / cell)

    def centre_paths(mask):
        progress.step('ligne centrale', 0.45)
        skel = prune(thin(mask))
        progress.step('parcours de la boucle', 0.8)
        if not skel.any():
            raise ValueError('la route ne forme pas de boucle fermee (rien ne reste apres ebarbage)')
        paths = [p for p in walk_graph(skel, dmap, start_px, heading) or [] if len(p) >= 30]   # carrefours, ponts
        if not paths:
            paths = [walk_loop(skel, dmap, start_px, heading)]     # boucle simple (aucun carrefour)
        if len(paths[0]) < 30:
            raise ValueError('boucle trop courte : le circuit est-il bien ferme ?')
        return paths
    from ai_gen import GroundQuery
    road_q = GroundQuery(tris, np.zeros(len(tris), int))
    marched = None
    if guide is not None:                                # trace dessine sur l'apercu de dessus
        progress.step('trace dessine', 0.45)
        P, total = _resample_closed(_guide_path(guide, raw, dmap, lo, cell, start_xy, heading), step)
    else:
        # grands vides gardes (le trace les contourne) ; si la boucle ne se referme plus ainsi (Tiny Arena), tous les
        # trous bouches comme avant
        mask = fill_small_holes(road)
        void_mask = fill_small_holes(road, is_void=_void_test(ground, road, zmap, lo, cell)) if ground is not None else mask
        paths = None
        if not np.array_equal(void_mask, mask):
            try:
                paths, mask = centre_paths(void_mask), void_mask
            except ValueError:
                paths = None
        if paths is None:
            paths = centre_paths(mask)
        # candidates (choix glouton, boucle la plus longue) : la plus longue une fois lissee (le vrai tour, pas un raccourci)
        best = None
        for path in paths:
            P = np.array([[lo[0] + (x + 0.5) * cell, lo[1] + (y + 0.5) * cell] for y, x in path])
            P = _smooth_closed(P, max(2, int(round(600 / cell))))
            P, total = _resample_closed(P, step)
            if best is None or total > best[1]:
                best = (P, total)
        P, total = best
        # route qui passe au-dessus d'elle-meme (spirale) : suivi 3D, garde seulement s'il referme un tour nettement plus long
        progress.step('suivi de la route en 3D', 0.88)
        m = _march_3d(road_q, start_xy, start_z, heading, step, cell, max(max_gap, MARCH_MAX_GAP))
        if m is not None and m['length'] > 1.05 * total and _overlaps_itself(m['points'], step):
            marched = m
            P, total = np.array(m['points'])[:, :2], m['length']
    # hauteur : on suit la route en continuite depuis le depart (niveau le plus proche du point precedent),
    # pour ne pas monter sur une passerelle ou une arche qui passe au-dessus
    def zmap_at(x, y):
        iy, ix = int((y - lo[1]) / cell), int((x - lo[0]) / cell)
        zz = zmap[max(0, min(iy, zmap.shape[0] - 1)), max(0, min(ix, zmap.shape[1] - 1))]
        return float(zz) if np.isfinite(zz) else None
    # hauteur : d'abord la ROUTE elle-meme (ses triangles seuls) ; le sol le plus proche pouvait etre un niveau enfoui
    # sous la route (sable de Mario Circuit 3, 1,1 m dessous : trace, zones et caisses dessous). Parmi les niveaux de
    # route, le plus proche du point precedent, pas le plus haut : dans un tuyau (Sewer Speedway) la voute est de la
    # meme surface que le fond, le trace passait 15 a 38 m au-dessus du sol, sur la voute.
    z_prev = start_z if start_z is not None else (zmap_at(*P[0]) if zmap_at(*P[0]) is not None else 0.0)
    near_bridge = _dilate(_dilate(bridge)) & ~raw if bridge.any() else bridge
    if guide is not None:                                # dessin : tout ce qui n'est pas sur la route = au-dessus d'un trou
        near_bridge = ~_dilate(raw)
    on_bridge = lambda x, y: bool(near_bridge[min(max(int((y - lo[1]) / cell), 0), raw.shape[0] - 1),
                                              min(max(int((x - lo[0]) / cell), 0), raw.shape[1] - 1)])
    pts, air, guess = [], [], set()                    # guess : hauteur reprise du point precedent (rien trouve)
    for i, (x, y) in enumerate(P):
        if (marched['air'][i] if marched else on_bridge(x, y)):   # au-dessus du trou : hauteur interpolee ensuite
            pts.append([float(x), float(y), None])
            air.append(True)
            continue
        if marched:                                    # suivi 3D : son niveau, pas celui du dessus ou du dessous
            z_prev = marched['points'][i][2]
        z = None
        # sinon le niveau de route le plus proche, a n'importe quelle hauteur : apres une chute de plus de 10 m (Android
        # Alley), la hauteur gardee restait 40 m au-dessus (ou sous) la route sur tout le reste du tour
        # (jamais sous le plancher de chute : fond de riviere de Barin Ruins, tuyau inaccessible de Sewer Speedway)
        levels = [h for h in road_q.heights(x, y) if min_z is None or h > min_z + 100]
        if levels:
            z = min(levels, key=lambda v: abs(v - z_prev))
        if z is None and ground is not None:
            g = ground.at(x, y, z_prev, window=300.0)
            z = g[0] if g else None
        guess.add(len(pts))
        if z is None:
            z = z_prev
        else:
            guess.discard(len(pts))
        pts.append([float(x), float(y), z])
        air.append(False)
        z_prev = z
    _interpolate_air(pts)
    if ground is not None:
        _lift_onto_ground(pts, [a or i in guess for i, a in enumerate(air)], ground)
    H, W = dmap.shape
    widths = [float(dmap[min(max(int((y - lo[1]) / cell), 0), H - 1), min(max(int((x - lo[0]) / cell), 0), W - 1)]) * cell
              for x, y, _ in pts]
    if guide is not None:
        # largeur au-dessus d'un trou (0) : celle du bord de route le plus proche le long du trace
        known = [i for i, w in enumerate(widths) if w > 0]
        if known:
            widths = [w if w > 0 else widths[min(known, key=lambda k: min(abs(k - i), len(pts) - abs(k - i)))]
                      for i, w in enumerate(widths)]
        n_jumps = sum(1 for i in range(len(air)) if air[i] and not air[i - 1])
    if marched:
        n_jumps = sum(1 for i in range(len(air)) if air[i] and not air[i - 1])
    moved = _avoid_obstacles(pts, air, widths, ground) if ground is not None else 0
    return {'points': pts, 'half_widths': widths, 'length': float(total), 'air': air, 'jumps': n_jumps,
            'obstacles': moved, 'marched': bool(marched), 'preview': preview_png(raw, lo, cell, pts, air)}


def _avoid_obstacles(pts, air, half_widths, ground):
    """Ligne centrale ecartee des objets solides poses sur la route (rocher, pilier : la route continue dessous, la
    ligne et les IA passaient au travers) : cote libre le plus proche, decalage progressif (pente 0,35 au plus).
    pts modifies sur place -> nombre de points deplaces."""
    from ai_gen import CLEARANCE, Obstacles, _slope_envelope, avoid_bounds
    n = len(pts)
    if n < 4:
        return 0
    P = np.array(pts, np.float64)
    t = np.roll(P[:, :2], -1, axis=0) - np.roll(P[:, :2], 1, axis=0)
    t /= np.maximum(np.linalg.norm(t, axis=1), 1e-9)[:, None]
    normals = [np.array([-v[1], v[0]]) for v in t]
    ds = np.linalg.norm(np.roll(P[:, :2], -1, axis=0) - P[:, :2], axis=1)
    slope = list(0.35 * ds)
    hw = [max(0.0, w - CLEARANCE) for w in half_widths]
    lo, hi, off = [-w for w in hw], list(hw), [0.0] * n
    obs, total = Obstacles(ground), 0
    for _ in range(3):
        lo, hi, moved = avoid_bounds(obs, P.tolist(), normals, list(P[:, 2]), off, lo, hi, air)
        if not moved:
            break
        total += moved
        hi_e, lo_e = _slope_envelope(hi, slope, upper=True), _slope_envelope(lo, slope, upper=False)
        off = [min(h, max(l, o)) if l <= h else o for o, l, h in zip(off, lo_e, hi_e)]
    if not total:
        return 0
    for i, p in enumerate(pts):
        if off[i]:
            x, y = p[0] + normals[i][0] * off[i], p[1] + normals[i][1] * off[i]
            g = ground.at(x, y, p[2], window=300.0)
            p[0], p[1], p[2] = float(x), float(y), float(g[0]) if g else p[2]
    return total


LIFT_MAX = 1000.0     # po : sol au-dessus d'un trou franchi jusqu'a ~25 m plus haut = le kart roule dessus


def _lift_onto_ground(pts, air, ground):
    """Points franchis (trou de la route, hauteur interpolee ou devinee) sous un sol qui n'est pas de la route : posés
    dessus. Crash Cove : la route de sable s'interrompt sous une butte d'herbe (la rampe du saut) ; la ligne droite
    interpolee passait 14 m sous la butte, et les IA avec. Le niveau le plus proche au-dessus est pris (pas un plafond
    plus haut)."""
    for p, a in zip(pts, air):
        if not a:
            continue
        above = [h for h in ground.heights(p[0], p[1]) if p[2] < h <= p[2] + LIFT_MAX]
        if above:
            p[2] = float(min(above))


def _interpolate_air(pts):
    """Hauteurs manquantes (None, au-dessus d'un trou) : interpolees entre le dernier point avant et le premier
    apres, le long de la boucle (fermee)."""
    n = len(pts)
    known = [i for i in range(n) if pts[i][2] is not None]
    if not known:
        for p in pts:
            p[2] = 0.0
        return
    for i in range(n):
        if pts[i][2] is not None:
            continue
        a = max((k for k in known if k < i), default=known[-1] - n)
        b = min((k for k in known if k > i), default=known[0] + n)
        za, zb = pts[a % n][2], pts[b % n][2]
        pts[i][2] = float(za + (zb - za) * (i - a) / max(b - a, 1))
