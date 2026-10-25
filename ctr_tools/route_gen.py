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


def largest_component(m):
    lab = np.zeros(m.shape, np.int32)
    best, best_n, cur = 0, 0, 0
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
        if n > best_n:
            best, best_n = cur, n
    return lab == best


def fill_small_holes(m, keep_ratio=0.25):
    """Bouche les trous (zones hors route entourees de route) plus petits que keep_ratio x le plus grand :
    obstacles, rochers, piliers au milieu de la route. Le grand trou (l'interieur du circuit) reste."""
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
        if len(h) < keep_ratio * big:
            ys, xs = zip(*h)
            out[list(ys), list(xs)] = True
    return out


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
    cos_max = math.cos(math.radians(max_angle))
    n, done = 0, set()
    for i, (e, d) in enumerate(ends):
        best = None
        for j, (t, dt) in enumerate(ends):
            if j == i or (min(i, j), max(i, j)) in done:
                continue
            v = np.subtract(t, e).astype(float)
            dist = float(np.linalg.norm(v))
            if not 3 < dist <= reach:
                continue
            u = v / dist
            if u @ d < cos_max or -u @ dt < cos_max:    # chacun doit pointer vers l'autre
                continue
            k = max(2, int(dist))
            ys = np.round(np.linspace(e[0], t[0], k)).astype(int)
            xs = np.round(np.linspace(e[1], t[1], k)).astype(int)
            out = ~mask[ys, xs]
            if out.sum() < 2 or out.sum() > 1.1 * max_gap_px + 3:   # pas de vide traverse, ou trou trop long
                continue
            if best is None or dist < best[0]:
                best = (dist, j, t)
        if best is None:
            continue
        _, j, t = best
        done.add((min(i, j), max(i, j)))
        w = max(3, int(2 * min(dm[e], dm[t])))
        draw.line([(e[1], e[0]), (t[1], t[0])], fill=255, width=w)
        n += 1
    bridge = (np.asarray(img) > 0) & ~mask
    return mask | bridge, bridge, n


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
    traverse plusieurs fois (huit, route qui repasse sous un pont), un troncon une seule fois.
    -> pixels [(y, x)], ou None si le squelette n'a pas de carrefour (boucle simple : walk_loop)."""
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
        if best is None:
            return None                                              # bloque : ancien parcours
        _, i, fwd, c = best
        gap = np.subtract(c[0], path[-1])                            # traversee du carrefour (noeud fusionne)
        n = int(max(abs(gap[0]), abs(gap[1])))
        path += [(int(round(path[-1][0] + gap[0] * u / n)), int(round(path[-1][1] + gap[1] * u / n))) for u in range(1, n)]
        if i == ei:                                                  # retour sur le troncon du depart : boucle fermee
            path += list(c[:si + 1] if fwd else c[:len(c) - si])
            return path[:-1]
        path += list(c)
        used.add(i)
        node = edges[i]['b'] if fwd else edges[i]['a']
    return None


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


def layout(loop, n_sections, overlap=2000.0, spacing=2500.0, finish_lift=660.0, height=2600.0, margin=800.0):
    """Decoupe une boucle (points tous les ~300 po, depart = ligne d'arrivee) en n sections egales.
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
        sections.append(fit_controls([list(P[i]) for i in ids], spacing))
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


def road_loop(tris, start_xy, heading, ground=None, step=300.0, cell=CELL, start_z=None, max_gap=0.0):
    """Boucle centrale de la route (voir l'en-tete du module). `ground` : GroundQuery pour poser le trace sur
    la route ; start_z : hauteur du sol au depart (sinon hauteur max de la route a cet endroit). max_gap (po) :
    trous franchis (saut au-dessus d'un vide, morceaux de route separes) : le trace continue en ligne droite
    jusqu'au morceau suivant, hauteur interpolee entre le tremplin et la reception ; 0 = aucun."""
    check_extent(tris, cell)
    progress.step('image de la route', 0.05)
    mask, zmap, lo, cell = rasterize(tris, cell)
    raw = mask                                          # route reelle (sans les ponts au-dessus des trous)
    progress.step('nettoyage de la route', 0.25)
    closed = close_holes(mask, 2)
    bridge, n_jumps = np.zeros(mask.shape, bool), 0
    if max_gap > 0:
        closed, bridge, n_jumps = bridge_gaps(closed, max_gap / cell)
    road = largest_component(closed)
    dmap = depth(road)                                  # largeur reelle (avant bouchage des obstacles)
    mask = fill_small_holes(road)
    progress.step('ligne centrale', 0.45)
    skel = prune(thin(mask))
    progress.step('parcours de la boucle', 0.8)
    if not skel.any():
        raise ValueError('la route ne forme pas de boucle fermee (rien ne reste apres ebarbage)')
    start_px = ((start_xy[1] - lo[1]) / cell, (start_xy[0] - lo[0]) / cell)
    path = walk_graph(skel, dmap, start_px, heading)          # carrefours, croisements sous un pont
    if path is None or len(path) < 30:
        path = walk_loop(skel, dmap, start_px, heading)        # boucle simple (aucun carrefour)
    if len(path) < 30:
        raise ValueError('boucle trop courte : le circuit est-il bien ferme ?')
    P = np.array([[lo[0] + (x + 0.5) * cell, lo[1] + (y + 0.5) * cell] for y, x in path])
    P = _smooth_closed(P, max(2, int(round(600 / cell))))
    P, total = _resample_closed(P, step)
    # hauteur : on suit la route en continuite depuis le depart (niveau le plus proche du point precedent),
    # pour ne pas monter sur une passerelle ou une arche qui passe au-dessus
    def zmap_at(x, y):
        iy, ix = int((y - lo[1]) / cell), int((x - lo[0]) / cell)
        zz = zmap[max(0, min(iy, zmap.shape[0] - 1)), max(0, min(ix, zmap.shape[1] - 1))]
        return float(zz) if np.isfinite(zz) else None
    # hauteur : d'abord la ROUTE elle-meme (zmap = dessus des triangles de route) ; le sol le plus proche pouvait
    # etre un niveau enfoui sous la route (sable de Mario Circuit 3, 1,1 m dessous : trace, zones et caisses dessous)
    z_prev = zmap_at(*P[0]) if zmap_at(*P[0]) is not None else (start_z if start_z is not None else 0.0)
    near_bridge = _dilate(_dilate(bridge)) & ~raw if n_jumps else bridge
    on_bridge = lambda x, y: bool(near_bridge[min(max(int((y - lo[1]) / cell), 0), raw.shape[0] - 1),
                                              min(max(int((x - lo[0]) / cell), 0), raw.shape[1] - 1)])
    pts, air = [], []
    for x, y in P:
        if on_bridge(x, y):                            # au-dessus du trou : hauteur interpolee ensuite
            pts.append([float(x), float(y), None])
            air.append(True)
            continue
        z = None
        zm = zmap_at(x, y)
        if zm is not None and abs(zm - z_prev) < 400:
            z = zm
        if z is None and ground is not None:
            g = ground.at(x, y, z_prev, window=300.0)
            z = g[0] if g else None
        if z is None:
            z = z_prev
        pts.append([float(x), float(y), z])
        air.append(False)
        z_prev = z
    _interpolate_air(pts)
    widths = [float(dmap[int((y - lo[1]) / cell), int((x - lo[0]) / cell)]) * cell for x, y, _ in pts]
    return {'points': pts, 'half_widths': widths, 'length': float(total), 'air': air, 'jumps': n_jumps}


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
