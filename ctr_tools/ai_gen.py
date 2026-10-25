"""Generation automatique de splines IA d'apres le sol (collision de la piste).

  ground = GroundQuery.from_hkx(octets_hkx)          # triangles monde + surface de chaque triangle
  ground.at(x, y, z_attendu) -> (z, surface) | None   # sol sous un point (le plus proche de z_attendu)
  lanes = generate_lanes(ground, reference, n=5, randomness=0.5, margin=0.15, seed=1)
      reference : polyligne (points de controle d'une spline de position ou IA)
      -> {'lanes': [[points]], 'widths': [(gauche, droite)], 'road_surfaces': [...]}

Largeur de route : depuis le trace de reference, on avance lateralement par pas de STEP pouces tant que le sol
existe, qu'il est d'une surface « de route » (les surfaces majoritaires sous la reference) et sans marche de plus de
MAX_STEP pouces (mur, chute). Les voies sont reparties sur cette largeur (moins une marge), avec une variation
laterale douce et aleatoire (somme de sinusoides), puis posees sur le sol.
"""
import collections
import math
import random

import numpy as np

STEP = 40.0            # pas de la recherche des bords (pouces)
MAX_HALF_WIDTH = 4000  # demi-largeur maximale cherchee
MAX_STEP = 80.0        # marche maximale entre deux pas (au-dela : mur ou chute)
CELL = 400.0           # cellule de la grille d'acces aux triangles
CLEARANCE = 120.0      # route libre minimale entre une voie et le bord (~3 m)


class GroundQuery:
    def __init__(self, tris, values):
        self.t = np.asarray(tris, np.float64)                 # (n, 3, 3)
        self.v = np.asarray(values)
        lo, hi = self.t[:, :, :2].min(1), self.t[:, :, :2].max(1)
        self.grid = collections.defaultdict(list)
        for i, (a, b) in enumerate(zip(np.floor(lo / CELL).astype(int), np.floor(hi / CELL).astype(int))):
            for cx in range(a[0], b[0] + 1):
                for cy in range(a[1], b[1] + 1):
                    self.grid[(cx, cy)].append(i)
        self.grid = {k: np.array(v) for k, v in self.grid.items()}

    @classmethod
    def from_hkx(cls, hkx):
        from collision_region import GroundEditor, apply
        ge = GroundEditor(hkx)
        tris, vals = [], []
        for m in ge.meshes:
            for p in m['mesh'].prims:
                for t in p.triangles():
                    tris.append([apply(m['to_world'], v) for v in t])
                    vals.append(p.value)
        return cls(tris, vals)

    def heights(self, x, y):
        """Hauteurs de tous les niveaux de sol sous (x, y), du plus haut au plus bas."""
        idx = self.grid.get((math.floor(x / CELL), math.floor(y / CELL)))
        if idx is None:
            return []
        t = self.t[idx]
        a, b, c = t[:, 0], t[:, 1], t[:, 2]
        v0, v1 = b[:, :2] - a[:, :2], c[:, :2] - a[:, :2]
        p = np.array([x, y]) - a[:, :2]
        den = v0[:, 0] * v1[:, 1] - v1[:, 0] * v0[:, 1]
        ok = np.abs(den) > 1e-9
        den = np.where(ok, den, 1.0)
        u = (p[:, 0] * v1[:, 1] - v1[:, 0] * p[:, 1]) / den
        v = (v0[:, 0] * p[:, 1] - p[:, 0] * v0[:, 1]) / den
        inside = ok & (u >= -1e-6) & (v >= -1e-6) & (u + v <= 1 + 1e-6)
        z = a[:, 2] + u * (b[:, 2] - a[:, 2]) + v * (c[:, 2] - a[:, 2])
        return sorted((float(h) for h in z[inside]), reverse=True)

    def top(self, x, y, z_ref, above=300.0):
        """Surface la plus haute sous (x, y) qui ne depasse pas z_ref + above (dessus de la route plutot qu'un niveau
        enfoui dessous ; un pont ou un tunnel plus haut est ignore). None si rien."""
        return next((h for h in self.heights(x, y) if h <= z_ref + above), None)

    def at(self, x, y, z_hint=None, window=400.0):
        """(z, surface) du sol sous (x, y) ; parmi plusieurs niveaux (pont), le plus proche de z_hint."""
        idx = self.grid.get((math.floor(x / CELL), math.floor(y / CELL)))
        if idx is None:
            return None
        t = self.t[idx]
        a, b, c = t[:, 0], t[:, 1], t[:, 2]
        v0, v1 = b[:, :2] - a[:, :2], c[:, :2] - a[:, :2]
        p = np.array([x, y]) - a[:, :2]
        den = v0[:, 0] * v1[:, 1] - v1[:, 0] * v0[:, 1]
        ok = np.abs(den) > 1e-9
        den = np.where(ok, den, 1.0)
        u = (p[:, 0] * v1[:, 1] - v1[:, 0] * p[:, 1]) / den
        v = (v0[:, 0] * p[:, 1] - p[:, 0] * v0[:, 1]) / den
        inside = ok & (u >= -1e-6) & (v >= -1e-6) & (u + v <= 1 + 1e-6)
        if not inside.any():
            return None
        z = a[:, 2] + u * (b[:, 2] - a[:, 2]) + v * (c[:, 2] - a[:, 2])
        cand = np.nonzero(inside)[0]
        if z_hint is None:
            k = cand[np.argmax(z[cand])]
        else:
            k = cand[np.argmin(np.abs(z[cand] - z_hint))]
            if abs(z[k] - z_hint) > window:
                return None
        return float(z[k]), int(self.v[idx[k]])


# -- trace ----------------------------------------------------------------------------------------
def catmull_rom(points, spacing):
    """Polyligne lissee (Catmull-Rom centripete) echantillonnee tous les `spacing` pouces."""
    P = [np.array(p, np.float64) for p in points]
    if len(P) < 2:
        return P
    P = [2 * P[0] - P[1]] + P + [2 * P[-1] - P[-2]]
    dense = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        t0 = 0.0
        t1 = t0 + max(np.linalg.norm(p1 - p0), 1e-6) ** 0.5
        t2 = t1 + max(np.linalg.norm(p2 - p1), 1e-6) ** 0.5
        t3 = t2 + max(np.linalg.norm(p3 - p2), 1e-6) ** 0.5
        for s in np.linspace(t1, t2, 20, endpoint=False):
            a1 = (t1 - s) / (t1 - t0) * p0 + (s - t0) / (t1 - t0) * p1
            a2 = (t2 - s) / (t2 - t1) * p1 + (s - t1) / (t2 - t1) * p2
            a3 = (t3 - s) / (t3 - t2) * p2 + (s - t2) / (t3 - t2) * p3
            b1 = (t2 - s) / (t2 - t0) * a1 + (s - t0) / (t2 - t0) * a2
            b2 = (t3 - s) / (t3 - t1) * a2 + (s - t1) / (t3 - t1) * a3
            dense.append((t2 - s) / (t2 - t1) * b1 + (s - t1) / (t2 - t1) * b2)
    dense.append(P[-2])
    # reechantillonnage a pas constant
    out, acc = [dense[0]], 0.0
    for a, b in zip(dense, dense[1:]):
        seg = np.linalg.norm(b - a)
        while acc + seg >= spacing and seg > 0:
            k = (spacing - acc) / seg
            a = a + (b - a) * k
            seg = np.linalg.norm(b - a)
            out.append(a)
            acc = 0.0
        acc += seg
    if np.linalg.norm(out[-1] - dense[-1]) > spacing * 0.3:
        out.append(dense[-1])
    return out


def curve_uniform(points, per_seg=16):
    """Courbe Catmull-Rom uniforme passant par les points de controle (approximation de la courbe du jeu et de
    l'editeur) : sert a verifier ce que l'IA suivra vraiment entre deux points espaces."""
    P = [np.array(p, np.float64) for p in points]
    if len(P) < 2:
        return P, [0] * len(P)
    P = [2 * P[0] - P[1]] + P + [2 * P[-1] - P[-2]]
    out, seg = [], []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for t in np.linspace(0, 1, per_seg, endpoint=False):
            t2, t3 = t * t, t * t * t
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3))
            seg.append(i - 1)
    out.append(P[-2])
    seg.append(len(points) - 2)
    return out, seg


def offroad_ratio(ground, lanes, road, per_seg=16):
    """Part des echantillons de la courbe suivie (entre les points de controle) qui ne sont pas au-dessus de la
    route vue de dessus (sol cherche jusqu'a 1000 po plus haut ou plus bas : sauts et creux ne comptent pas)."""
    bad = tot = 0
    for lane in lanes:
        curve, _ = curve_uniform(lane, per_seg)
        for p in curve:
            g = ground.at(p[0], p[1], p[2] - 80, window=1000.0)
            tot += 1
            bad += not (g and g[1] in road)
    return bad / max(1, tot)


def _smooth(vals, k):
    if k <= 1:
        return list(vals)
    a = np.asarray(vals, np.float64)
    pad = np.pad(a, (k // 2, k // 2), mode='edge')
    return list(np.convolve(pad, np.ones(k) / k, mode='valid')[:len(a)])


def road_surfaces(ground, samples):
    """Surfaces « de route » : celles qui couvrent l'essentiel du sol sous le trace de reference."""
    cnt = collections.Counter()
    for p in samples:
        g = ground.at(p[0], p[1], p[2])
        if g:
            cnt[g[1]] += 1
    total = sum(cnt.values()) or 1
    keep, acc = [], 0
    for s, n in cnt.most_common():
        keep.append(s)
        acc += n
        if acc >= 0.9 * total:
            break
    return keep


def road_width(ground, p, side, z, road):
    """Distance jusqu'au bord de la route depuis p dans la direction `side` (vecteur horizontal unitaire).
    La surface sous le trace a cet endroit compte toujours comme route (pont en bois au milieu du sable...)."""
    here = ground.at(p[0], p[1], z)
    road = road | {here[1]} if here else road
    d, zp = 0.0, z
    while d < MAX_HALF_WIDTH:
        q = d + STEP
        g = ground.at(p[0] + side[0] * q, p[1] + side[1] * q, zp)
        if g is None or g[1] not in road or abs(g[0] - zp) > MAX_STEP:
            return d
        d, zp = q, g[0]
    return d


def generate_lanes(ground, reference, n=5, randomness=0.5, margin=0.15, seed=1, sample=300.0, point_spacing=2500.0,
                   lift=80.0, keep_air=False, road_ground=None):
    """Voies IA le long de `reference`. Retourne {'lanes', 'widths', 'road_surfaces'}.
    keep_air : la hauteur de la reference est gardee quand elle passe au-dessus du sol (sauts) : z = max(sol + lift,
    hauteur de la reference).
    road_ground : GroundQuery de la route SEULE (objets de route d'une map importee) : largeur et marges mesurees
    dessus, au lieu de reconnaitre la route a sa surface de collision (une map importee a souvent la meme surface
    partout : herbe, bordures et decor comptaient comme de la route)."""
    samples = catmull_rom(reference, sample)
    zs = []
    for p in samples:                                   # trace pose sur le sol (la route si on la connait)
        g = (road_ground.at(p[0], p[1], p[2], window=1500.0) if road_ground is not None else None) \
            or ground.at(p[0], p[1], p[2])
        zs.append(g[0] if g else p[2])
    if road_ground is not None:
        road = set(int(v) for v in np.unique(road_ground.v))
        ground_w = road_ground
    else:
        road = set(road_surfaces(ground, [(p[0], p[1], z) for p, z in zip(samples, zs)]))
        ground_w = ground
    lefts, rights, normals = [], [], []
    for i, p in enumerate(samples):
        a, b = samples[max(0, i - 1)], samples[min(len(samples) - 1, i + 1)]
        t = np.array([b[0] - a[0], b[1] - a[1]])
        t /= np.linalg.norm(t) or 1.0
        nrm = np.array([-t[1], t[0]])                   # gauche
        normals.append(nrm)
        lefts.append(road_width(ground_w, p, nrm, zs[i], road))
        rights.append(road_width(ground_w, p, -nrm, zs[i], road))
    k = max(1, int(round(2000 / sample)))               # largeurs lissees sur ~50 m
    lefts, rights = _smooth(lefts, k), _smooth(rights, k)
    rnd = random.Random(seed)
    ds = [float(np.linalg.norm(np.array(b[:2]) - np.array(a[:2]))) for a, b in zip(samples, samples[1:])]
    total = sum(ds) or 1.0
    # courbure du trace (cap / distance, lissee) : rayon signe, > 0 = virage a gauche (centre du cote de la normale)
    heads = [math.atan2(normals[i][0], -normals[i][1]) for i in range(len(samples))]
    turn = [0.0] + [math.remainder(heads[i] - heads[i - 1], 2 * math.pi) / max(ds[i - 1], 1.0)
                    for i in range(1, len(samples))]
    turn = _smooth(_smooth(turn, max(1, int(round(1200 / sample)))), 3)
    lanes = []
    for j in range(n):
        base = -1 + 2 * (j + 0.5) / n                   # -1 (gauche) .. +1 (droite)
        waves = [(rnd.uniform(0.5, 1.0), rnd.uniform(1.0, 4.0), rnd.uniform(0, 2 * math.pi)) for _ in range(3)]
        want, lo, hi, s_acc = [], [], [], 0.0
        for i, p in enumerate(samples):
            if i:
                s_acc += ds[i - 1]
            u = s_acc / total
            noise = sum(a * math.sin(2 * math.pi * f * u + ph) for a, f, ph in waves) / 2.5
            frac = max(-1.0, min(1.0, base + randomness * 0.6 * noise))
            # frac > 0 : vers la droite (-normale) ; marge laissee aux bords (pourcentage ET distance minimale)
            side = rights[i] if frac > 0 else lefts[i]
            mag = min(abs(frac) * side * (1 - margin), max(0.0, side - CLEARANCE))
            want.append(-math.copysign(mag, frac))
            # bornes sures de chaque cote (route libre + CLEARANCE) ; a l'interieur d'un virage, pas plus de 60 % du
            # rayon (au-dela, la voie decalee se replie sur elle-meme : boucle)
            left = _safe_offset(ground_w, p, normals[i], zs[i], max(0.0, lefts[i] - CLEARANCE), road)
            right = -_safe_offset(ground_w, p, normals[i], zs[i], -max(0.0, rights[i] - CLEARANCE), road)
            if abs(turn[i]) > 1e-6:
                r = 0.6 / abs(turn[i])
                if turn[i] > 0:
                    left = min(left, r)
                else:
                    right = min(right, r)
            hi.append(left)
            lo.append(-right)
        # decalage final : voulu, lisse, dans les bornes, et dont la variation est limitee (pas de zigzag :
        # au plus ~0,35 de deplacement lateral par unite d'avance, bornes elles-memes « erodees » a cette pente)
        slope = [0.35 * d for d in ds]
        hi_e, lo_e = _slope_envelope(hi, slope, upper=True), _slope_envelope(lo, slope, upper=False)
        off = _smooth(_smooth(want, max(1, int(round(1500 / sample)))), 3)
        off = [min(h, max(l, o)) if l <= h else 0.0 for o, l, h in zip(off, lo_e, hi_e)]
        pts = []
        for i, p in enumerate(samples):
            x, y = p[0] + normals[i][0] * off[i], p[1] + normals[i][1] * off[i]
            g = ground.at(x, y, zs[i])
            z = (g[0] if g else zs[i]) + lift
            if keep_air:
                z = max(z, float(p[2])) if g else float(p[2])
            pts.append([x, y, z])
        lanes.append(fit_controls(pts, point_spacing))
    return {'lanes': lanes, 'widths': list(zip(lefts, rights)), 'road_surfaces': sorted(road)}


def _slope_envelope(bound, slope, upper=True):
    """Borne « erodee » : la plus proche de la borne d'origine qui ne varie pas plus vite que `slope` (par pas).
    upper=True : borne haute (min) ; sinon basse (max)."""
    b = list(bound)
    sgn = 1.0 if upper else -1.0
    for i in range(1, len(b)):
        b[i] = sgn * min(sgn * b[i], sgn * b[i - 1] + slope[i - 1])
    for i in range(len(b) - 2, -1, -1):
        b[i] = sgn * min(sgn * b[i], sgn * b[i + 1] + slope[i])
    return b


def _on_road(ground, x, y, z, road):
    g = ground.at(x, y, z)
    return g is not None and g[1] in road and abs(g[0] - z) <= MAX_STEP * 2


def _safe_offset(ground, p, nrm, z, off, road):
    """Ramene un decalage lateral vers le trace tant que le point, ou la route a CLEARANCE de part et d'autre
    (dans le sens du decalage), n'est pas sur la route."""
    here = ground.at(p[0], p[1], z)
    road = road | {here[1]} if here else road
    sgn = 1.0 if off >= 0 else -1.0
    mag = abs(off)
    while mag > 0:
        x, y = p[0] + nrm[0] * sgn * mag, p[1] + nrm[1] * sgn * mag
        xo, yo = x + nrm[0] * sgn * CLEARANCE, y + nrm[1] * sgn * CLEARANCE
        if _on_road(ground, x, y, z, road) and _on_road(ground, xo, yo, z, road):
            break
        mag = max(0.0, mag - STEP)
    return sgn * mag


MIN_SPACING = 500.0       # ecart minimal entre points de controle (~13 m)
MAX_RATIO = 1.8           # rapport maximal entre deux segments voisins (au-dela, la courbe deborde : boucles)


def fit_controls(path, spacing, tol=150.0, max_points=120):
    """Points de controle pris sur `path` (voie voulue, echantillonnee finement). Ecart local = ~moitie du rayon de
    virage (entre MIN_SPACING et `spacing`), variant progressivement ; resserre la ou la courbe Catmull-Rom qui
    passe par les points s'ecarte de plus de `tol` de la voie (interieur des virages : murs), puis segments voisins
    equilibres (des points tres proches a cote de segments longs faisaient des noeuds)."""
    P = np.array(path, np.float64)
    if len(P) < 3:
        return [[round(float(c), 3) for c in p] for p in P]
    d = np.linalg.norm(np.diff(P[:, :2], axis=0), axis=1)
    head = np.unwrap(np.arctan2(np.diff(P[:, 1]), np.diff(P[:, 0])))
    k = np.abs(np.gradient(head)) / np.maximum(d, 1.0)
    win = max(1, int(round(1000.0 / max(float(np.median(d)), 1.0))))
    k = np.convolve(np.pad(k, win, mode='edge'), np.ones(2 * win + 1) / (2 * win + 1), mode='valid')
    L = np.clip(0.5 / np.maximum(k, 1e-9), MIN_SPACING, spacing)            # ecart voulu par segment

    def place(L):
        idx, acc = [0], 0.0
        for i in range(1, len(P)):
            acc += d[i - 1] / L[i - 1]
            if acc >= 1.0:
                idx.append(i)
                acc = 0.0
        if idx[-1] != len(P) - 1:
            if len(idx) > 1 and acc < 0.4:
                idx[-1] = len(P) - 1
            else:
                idx.append(len(P) - 1)
        return idx

    def smooth_spacing(L):
        # variation progressive : un ecart ne depasse pas MAX_RATIO fois celui d'un voisin a ~un ecart de distance
        L = L.copy()
        for rng in (range(1, len(L)), range(len(L) - 2, -1, -1)):
            for i in rng:
                j = i - 1 if rng.step == 1 else i + 1
                L[i] = min(L[i], L[j] + (MAX_RATIO - 1) * d[min(i, j)] * L[j] / max(L[j], 1.0))
        return L
    L = smooth_spacing(L)
    idx = place(L)
    for _ in range(8):                                   # resserrer la ou la courbe s'ecarte de la voie
        curve, seg = curve_uniform(P[idx], 12)
        bad = set()
        for c, kk in zip(curve, seg):
            a, b = idx[kk], idx[min(kk + 1, len(idx) - 1)]
            if b - a >= 2 and _dist_to_polyline(c[:2], P[a:b + 1, :2]) > tol:
                bad.add(kk)
        if not bad or len(idx) >= max_points:
            break
        for kk in bad:
            a, b = idx[kk], idx[min(kk + 1, len(idx) - 1)]
            L[a:b + 1] = np.maximum(L[a:b + 1] * 0.6, MIN_SPACING)
        L = smooth_spacing(L)
        idx = place(L)
    # equilibre final : un segment plus de MAX_RATIO fois plus long que son voisin est coupe en deux
    for _ in range(4 * len(idx)):
        seg_len = [float(np.sum(d[a:b])) for a, b in zip(idx, idx[1:])]
        worst = next((i for i in range(len(seg_len) - 1)
                      if max(seg_len[i], seg_len[i + 1]) > MAX_RATIO * max(min(seg_len[i], seg_len[i + 1]), 1.0)), None)
        if worst is None or len(idx) >= max_points:
            break
        long = worst if seg_len[worst] > seg_len[worst + 1] else worst + 1
        a, b = idx[long], idx[long + 1]
        if b - a < 2:
            break
        idx.insert(long + 1, (a + b) // 2)
    return [[round(float(c), 3) for c in P[i]] for i in idx]


def self_crossings(points, per_seg=16):
    """Nombre de croisements (vue de dessus) de la courbe suivie par l'IA avec elle-meme : noeuds / boucles."""
    curve, _ = curve_uniform(points, per_seg)
    P = np.array([c[:2] for c in curve])
    A, B = P[:-1], P[1:]

    def orient(p, q, r):
        return (q[..., 0] - p[..., 0]) * (r[..., 1] - p[..., 1]) - (q[..., 1] - p[..., 1]) * (r[..., 0] - p[..., 0])
    n = 0
    for i in range(len(A) - 2):
        c, e = A[i + 2:], B[i + 2:]
        o1, o2 = orient(A[i], B[i], c), orient(A[i], B[i], e)
        o3, o4 = orient(c, e, A[i]), orient(c, e, B[i])
        n += int(((o1 * o2 < 0) & (o3 * o4 < 0)).sum())
    return n


def _dist_to_polyline(p, Q):
    a, b = Q[:-1], Q[1:]
    ab = b - a
    t = np.clip(((p - a) * ab).sum(1) / np.maximum((ab * ab).sum(1), 1e-9), 0, 1)
    return float(np.min(np.linalg.norm(a + ab * t[:, None] - p, axis=1)))
