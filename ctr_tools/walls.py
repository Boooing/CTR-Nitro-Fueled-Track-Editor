"""Murs invisibles : collision seule, rien n'est affiche en jeu.

  pos, tris = ribbon(points, height)          # feuille verticale le long d'une polyligne posee au sol
  pieces = generate(ground, loop, road_ground=None, margin=120, piece=2000, sides='both', offroad=False)
      loop : trace de course ferme (points [x, y, z], pouces)
      -> [{'side': 'left' | 'right', 'reason': 'void' | 'offroad', 'points': [[x, y, z sol], ...]}]
  pieces = zone(ground, tris, Corridor(ground, loop), margin=40)   # le long des bords d'objets choisis, hors route

Bord de la route : depuis le trace, pas lateraux de ai_gen.STEP tant que le sol est de la route (meme surface, ou
route seule si on la connait) sans marche de plus de ai_gen.MAX_STEP. Au-dela du bord :
  * un mur ou un talus existe deja (le segment horizontal a hauteur de kart, du bord jusqu'a la marge, touche la
    collision) -> pas de mur ;
  * plus de sol a la hauteur de la route (vide, chute) -> mur ('void') ;
  * sol hors route a la meme hauteur (herbe, sable) -> mur seulement si offroad ('offroad').
Le mur est pose a `margin` au-dela du bord (largeur lissee), jamais sur une autre partie de la route (epingles,
croisements), jamais a l'interieur d'un virage plus serre que son decalage (il se replierait sur lui-meme).
Les murs sont decoupes en morceaux d'au plus `piece` pouces : un objet de decor chacun, deplacable ou supprimable.
"""
import math

import numpy as np

import ai_gen

HEIGHT = 400.0         # ~10 m au-dessus de la route
SINK = 100.0           # le mur descend 2,5 m sous la route : pas de fente sous le mur dans les creux
MARGIN = 120.0         # ~3 m au-dela du bord de la route
PIECE = 2000.0         # ~50 m par morceau
SAMPLE = 200.0         # pas le long du trace (~5 m)
KART_Z = 60.0          # hauteur du segment de detection des murs existants (~1,5 m)
MIN_RUN = 3            # morceau de mur d'au moins 3 echantillons (~10 m)


def ribbon(points, height=HEIGHT, sink=SINK):
    """Feuille verticale le long d'une polyligne [[x, y, z sol]] : (sommets, triangles) ; bas = z - sink,
    haut = z + height. La collision du jeu arrete les karts des deux cotes d'un triangle."""
    pos, tris = [], []
    for p in points:
        pos += [(float(p[0]), float(p[1]), float(p[2]) - sink), (float(p[0]), float(p[1]), float(p[2]) + height)]
    for i in range(len(points) - 1):
        a, b, c, d = 2 * i, 2 * i + 1, 2 * i + 2, 2 * i + 3
        tris += [(a, c, b), (b, c, d)]
    return pos, tris


def straight(length, height=HEIGHT, sink=SINK):
    """Mur droit centre sur l'origine, le long de X : (sommets, triangles)."""
    return ribbon([[-length / 2, 0.0, 0.0], [length / 2, 0.0, 0.0]], height, sink)


segment_blocked = ai_gen.segment_blocked     # le segment a -> b traverse-t-il la collision ?


def _smooth_valid(vals, valid, k):
    """Moyenne glissante sur k points (trace ferme : bouclee) des seules valeurs valides ; les autres gardees."""
    a, m = np.asarray(vals, np.float64), np.asarray(valid, np.float64)
    if k <= 1 or len(a) < k:
        return list(a)
    h = k // 2
    ker = np.ones(2 * h + 1)
    num = np.convolve(np.concatenate([(a * m)[-h:], a * m, (a * m)[:h]]), ker, 'valid')
    den = np.convolve(np.concatenate([m[-h:], m, m[:h]]), ker, 'valid')
    return list(np.where(den > 0, num / np.maximum(den, 1e-9), a))


def _edge(ground_w, p, side, z, road):
    """(distance au bord, hauteur de la route au bord) depuis p dans la direction `side` (comme ai_gen.road_width)."""
    here = ground_w.at(p[0], p[1], z)
    road = road | {here[1]} if here else road
    d, zp = 0.0, z
    while d < ai_gen.MAX_HALF_WIDTH:
        q = d + ai_gen.STEP
        g = ground_w.at(p[0] + side[0] * q, p[1] + side[1] * q, zp)
        if g is None or g[1] not in road or abs(g[0] - zp) > ai_gen.MAX_STEP:
            return d, zp
        d, zp = q, g[0]
    return d, zp


def _beyond(ground, p, side, d, z, margin):
    """Ce qu'il y a au-dela du bord : 'wall' (mur / talus deja la), 'offroad' (sol a la meme hauteur), 'void'."""
    a = [p[0] + side[0] * d, p[1] + side[1] * d, z + KART_Z]
    b = [p[0] + side[0] * (d + margin + ai_gen.STEP), p[1] + side[1] * (d + margin + ai_gen.STEP), z + KART_Z]
    if segment_blocked(ground, a, b):
        return 'wall'
    for k in (ai_gen.STEP, margin):
        hs = ground.heights(p[0] + side[0] * (d + k), p[1] + side[1] * (d + k))
        if any(z + ai_gen.MAX_STEP < h < z + 1000 for h in hs):
            return 'wall'                                   # talus plus haut (bord releve, falaise)
        if not any(abs(h - z) <= ai_gen.MAX_STEP for h in hs):
            return 'void'
    return 'offroad'


def _line(ground, loop, road_ground, sample):
    """Trace ferme echantillonne : (points, hauteur de la route sous chacun ou None, tangentes horizontales,
    surfaces de route, sol ou mesurer la largeur)."""
    pts = ai_gen.catmull_rom(list(loop) + [loop[0]], sample)
    if len(pts) > 2 and np.linalg.norm(np.asarray(pts[-1]) - np.asarray(pts[0])) < sample * 0.5:
        pts = pts[:-1]
    n = len(pts)
    zs = []
    for p in pts:
        # trace pose sur la route ; None : saut, ou route connue (objets de route) absente sous le trace (passage
        # sous un pont fait d'un autre objet) : bords inconnus, pas de mur
        g = road_ground.at(p[0], p[1], p[2], window=1500.0) if road_ground is not None \
            else ground.at(p[0], p[1], p[2], window=1500.0)
        zs.append(g[0] if g else None)
    if road_ground is not None:
        road, ground_w = set(int(v) for v in np.unique(road_ground.v)), road_ground
    else:
        road = set(ai_gen.road_surfaces(ground, [(p[0], p[1], z) for p, z in zip(pts, zs) if z is not None]))
        ground_w = ground
    tang = []
    for i in range(n):
        a, b = pts[(i - 1) % n], pts[(i + 1) % n]
        t = np.array([b[0] - a[0], b[1] - a[1]])
        tang.append(t / (np.linalg.norm(t) or 1.0))
    return pts, zs, tang, road, ground_w


class Corridor:
    """Bande de la route autour du trace (largeur mesuree de chaque cote, comme les murs le long de la route) :
    un mur n'y est jamais pose. inside(x, y, z) : a moins de la largeur (+ tol) du trace, a sa hauteur (+-600 po)."""

    def __init__(self, ground, loop, road_ground=None, sample=SAMPLE, tol=40.0):
        pts, zs, tang, road, ground_w = _line(ground, loop, road_ground, sample)
        self.xy = np.array([[p[0], p[1]] for p in pts])
        self.z = np.array([z if z is not None else p[2] for p, z in zip(pts, zs)])
        self.t = np.array(tang)
        lw, rw = [], []
        for p, z, t in zip(pts, zs, tang):
            if z is None:                               # saut / passage sous un pont : largeur de route courante
                lw.append(None), rw.append(None)
                continue
            lw.append(_edge(ground_w, p, (-t[1], t[0]), z, road)[0])
            rw.append(_edge(ground_w, p, (t[1], -t[0]), z, road)[0])
        fill = float(np.median([w for w in lw + rw if w]) if any(lw + rw) else 600.0)
        self.left = np.array([w if w else fill for w in lw]) + tol
        self.right = np.array([w if w else fill for w in rw]) + tol

    def tangent(self, x, y, z, reach=3000.0):
        """Direction du trace (unitaire) au point le plus proche, s'il est a moins de reach po (et +-600 po en hauteur)."""
        d = np.hypot(self.xy[:, 0] - x, self.xy[:, 1] - y)
        d[np.abs(self.z - z) > 600] = np.inf
        i = int(np.argmin(d))
        return self.t[i] if d[i] <= reach else None

    def shrunk(self, d):
        """La meme bande, d pouces plus etroite de chaque cote (un mur pose sur une barriere au bord de la route)."""
        c = object.__new__(Corridor)
        c.xy, c.z, c.t = self.xy, self.z, self.t
        c.left, c.right = np.maximum(self.left - d, 0.0), np.maximum(self.right - d, 0.0)
        return c

    def inside(self, x, y, z, lo=None, hi=None):
        """lo / hi : bas et haut d'un mur en (x, y) ; la route compte si l'espace d'un kart dessus (-100 a +300 po)
        croise le mur (route sous un mur pose sur un pont, ou au-dessus d'un mur trop haut). Sinon : a +-600 po."""
        d = np.hypot(self.xy[:, 0] - x, self.xy[:, 1] - y)
        if lo is None:
            d[np.abs(self.z - z) > 600] = np.inf
        else:
            d[(self.z + 300 < lo) | (self.z - 100 > hi)] = np.inf
        i = int(np.argmin(d))
        if not np.isfinite(d[i]):
            return False
        v = np.array([x, y]) - self.xy[i]
        along, lat = v @ self.t[i], v @ np.array([-self.t[i][1], self.t[i][0]])   # lat > 0 : a gauche
        return abs(along) < SAMPLE and (lat <= self.left[i] if lat >= 0 else -lat <= self.right[i])


JUMP = 80 * 39.37     # po : trou franchi au plus (comme « Creer le parcours »)


def _jump_edge(sel, corridor, m, nrm):
    """Bord d'un saut (tremplin ou reception) : tourne vers le sens de la course (pas le cote de la route) et la route
    choisie reprend en face, a moins de JUMP, jusqu'a JUMP plus bas ou plus haut (Crash Cove : reception 43 m sous le
    tremplin). Un bord le long d'un vide (falaise, epingle au-dessus d'un ravin) n'en est pas un."""
    if corridor is None:
        return False
    t = corridor.tangent(m[0], m[1], m[2])
    if t is None or abs(nrm @ t) < 0.6:
        return False
    for s in np.arange(300.0, JUMP, 100.0):
        x, y = m[0] + nrm[0] * s, m[1] + nrm[1] * s
        if any(abs(h - m[2]) <= JUMP for h in sel.heights(x, y)):
            return True
    return False


def _chains(keys):
    """Aretes (i, j) -> chaines de sommets voisins (fermee : premier sommet = dernier)."""
    adj = {}
    for (i, j) in keys:
        adj.setdefault(i, []).append((i, j))
        adj.setdefault(j, []).append((i, j))
    used, chains = set(), []
    for e0 in keys:
        if e0 in used:
            continue
        used.add(e0)
        chain = [e0[0], e0[1]]
        for end in (1, 0):                              # prolonge par les deux bouts
            while True:
                v = chain[-1] if end else chain[0]
                nxt = next((e for e in adj[v] if e not in used), None)
                if nxt is None:
                    break
                used.add(nxt)
                w = nxt[1] if nxt[0] == v else nxt[0]
                if end:
                    chain.append(w)
                else:
                    chain.insert(0, w)
                if w == (chain[0] if end else chain[-1]):
                    break
        chains.append(chain)
    return chains


def _plen(pts):
    return sum(math.dist(p[:2], q[:2]) for p, q in zip(pts, pts[1:]))


def _mesh_router(T, top, corridor, height):
    """route(a, b, limit) : chemin (points intermediaires) de a a b le long des objets choisis eux-memes — aretes
    des faces non horizontales (panneaux d'une barriere) et bords du dessus, jamais a travers un dessus — d'au plus
    `limit` pouces, hors de la route (bande retrecie : la barriere peut border la route) ; None sinon."""
    import heapq
    V, inv = np.unique(np.round(T.reshape(-1, 3) / 2.0).astype(np.int64), axis=0, return_inverse=True)
    F = inv.reshape(-1, 3)
    X = V * 2.0
    count = {}
    for f, up in zip(F, top):
        if up:
            for k in range(3):
                e = (min(f[k], f[(k + 1) % 3]), max(f[k], f[(k + 1) % 3]))
                count[e] = count.get(e, 0) + 1
    # aretes gardees, recoupees tous les STEP pouces (un panneau de 60 m n'a de sommets qu'a ses bouts)
    STEP_, HOP = 100.0, 250.0
    pts_, index, adj = list(X), {}, {}

    def link(u, v):
        w = float(np.linalg.norm(pts_[u][:2] - pts_[v][:2]))
        adj.setdefault(u, {})[v] = w
        adj.setdefault(v, {})[u] = w
    done = set()
    for f, up in zip(F, top):
        for k in range(3):
            e = (min(f[k], f[(k + 1) % 3]), max(f[k], f[(k + 1) % 3]))
            if e[0] == e[1] or e in done or (up and count.get(e, 0) != 1):
                continue
            done.add(e)
            n_ = int(np.linalg.norm(X[e[0], :2] - X[e[1], :2]) // STEP_)
            prev = e[0]
            for s in range(1, n_ + 1):
                pts_.append(X[e[0]] + (X[e[1]] - X[e[0]]) * (s / (n_ + 1)))
                link(prev, len(pts_) - 1)
                prev = len(pts_) - 1
            link(prev, e[1])
    X = np.array(pts_)
    # morceaux voisins sans sommet commun (poteaux et panneaux d'une barriere) : sauts d'au plus HOP pouces entre
    # points du graphe (jamais depuis l'interieur d'un dessus : ils n'y sont pas)
    grid = {}
    for v in adj:
        grid.setdefault((int(X[v, 0] // HOP), int(X[v, 1] // HOP)), []).append(v)
    for (gx, gy), vs in grid.items():
        near_vs = [w for dx in (-1, 0, 1) for dy in (-1, 0, 1) for w in grid.get((gx + dx, gy + dy), ())]
        W = np.array(near_vs)
        for v in vs:
            d = np.hypot(X[W, 0] - X[v, 0], X[W, 1] - X[v, 1])
            ok = (d <= HOP) & (np.abs(X[W, 2] - X[v, 2]) <= 400) & (W != v)
            for w, dw in zip(W[ok], d[ok]):
                w = int(w)
                if w not in adj[v]:
                    adj[v][w] = adj[w][v] = float(dw) * 1.5   # un saut coute plus que de suivre l'objet
    if not adj:
        return None
    keys = np.array(sorted(adj))
    tight = corridor.shrunk(120.0) if corridor is not None else None

    def near(p):
        d = np.hypot(X[keys, 0] - p[0], X[keys, 1] - p[1]) + np.where(np.abs(X[keys, 2] - p[2]) > 800, np.inf, 0)
        i = int(np.argmin(d))
        return int(keys[i]) if d[i] <= 300 else None

    def route(a, b, limit):
        s, g = near(a), near(b)
        if s is None or g is None or s == g:
            return None
        dist, prev, heap = {s: 0.0}, {}, [(0.0, s)]
        while heap:
            d, v = heapq.heappop(heap)
            if v == g:
                break
            if d > dist.get(v, np.inf) or d > limit:
                continue
            for w, c in adj[v].items():
                nd = d + c
                if nd < dist.get(w, np.inf) and nd <= limit:
                    dist[w], prev[w] = nd, v
                    heapq.heappush(heap, (nd, w))
        if g not in dist:
            return None
        path, v = [], g
        while v != s:
            path.append(v)
            v = prev[v]
        path = [s] + path[::-1]
        L = dist[g] or 1.0
        pts, acc = [], 0.0
        for u, v in zip(path, path[1:]):          # z : de a vers b (les sommets d'un panneau vont du bas au haut)
            acc += adj[u][v]
            pts.append([float(X[v, 0]), float(X[v, 1]), float(a[2] + (b[2] - a[2]) * acc / L)])
        full = _simplify([list(a)] + pts[:-1] + [list(b)], 20.0)
        if tight is not None:
            for p, q in zip(full, full[1:]):            # tout le long (un bord coupe de route traverse la bande)
                for s in np.linspace(0, 1, max(2, int(math.dist(p[:2], q[:2]) // 100) + 1)):
                    x, y, z = (p[i] + (q[i] - p[i]) * s for i in range(3))
                    if tight.inside(x, y, z, z - SINK, z + height):
                        return None
        return full[1:-1]
    return route


def _join(lines, join, clear, route=None):
    """Relie les bouts de murs proches (au plus `join` pouces) : lines = [{'points', 'reason'}] ; une petite boucle
    fermee (dessus d'un poteau de barriere) compte comme un point de passage. clear(a, b) : le segment a -> b peut
    porter un mur. Plus courts raccords d'abord, chaque bout une fois ; le raccord suit l'objet choisi s'il le peut
    (route(a, b, limit) : barriere entre deux poteaux), sinon un coin quand les deux murs prolonges se croisent tout
    pres, sinon tout droit. -> lignes reliees."""
    if join <= 0 or len(lines) < 1:
        return lines
    nodes = []                                      # (points, raison, petite boucle ?)
    for ln in lines:
        P = ln['points']
        closed = len(P) > 2 and math.dist(P[0][:2], P[-1][:2]) < 1.0
        if closed:
            A = np.array(P)
            if np.ptp(A[:, 0]) <= 200 and np.ptp(A[:, 1]) <= 200:
                nodes.append(([list(A[:-1].mean(0))], ln['reason'], P))
            else:
                nodes.append((P, ln['reason'], None))   # grande boucle : deja fermee, pas de bouts
                continue
        else:
            nodes.append((P, ln['reason'], None))
    closed_big = [k for k, (P, _, small) in enumerate(nodes)
                  if small is None and len(P) > 2 and math.dist(P[0][:2], P[-1][:2]) < 1.0]
    ends = []                                       # (noeud, bout 0|1, point, direction vers l'exterieur ou None)
    for k, (P, _, small) in enumerate(nodes):
        if k in closed_big:
            continue
        for e in (0, 1):
            p = P[0] if e == 0 else P[-1]
            d = None
            if len(P) >= 2:
                q = P[1] if e == 0 else P[-2]
                v = np.array(p[:2]) - np.array(q[:2])
                if np.linalg.norm(v) >= 100:
                    d = v / np.linalg.norm(v)
            ends.append((k, e, p, d))
    size = {k: _plen(P) for k, (P, _, _) in enumerate(nodes)}
    root = list(range(len(nodes)))

    def find(k):
        while root[k] != k:
            root[k] = root[root[k]]
            k = root[k]
        return k
    cand = []
    for a in range(len(ends)):
        for b in range(a + 1, len(ends)):
            ka, ea, pa, da = ends[a]
            kb, eb, pb, db = ends[b]
            if ka == kb and (nodes[ka][2] is not None or len(nodes[ka][0]) < 2):
                continue
            dist = math.dist(pa[:2], pb[:2])
            if dist > join or abs(pa[2] - pb[2]) > max(400.0, 0.3 * dist):
                continue
            cand.append((dist, a, b))
    cand.sort()
    taken, links = set(), {}
    for dist, a, b in cand:
        if a in taken or b in taken:
            continue
        ka, ea, pa, da = ends[a]
        kb, eb, pb, db = ends[b]
        ra, rb = find(ka), find(kb)
        if ra == rb and size[ra] < 3 * dist:
            continue                                # refermer un mur sur lui-meme : seulement un grand tour
        c = np.array(pb[:2]) - np.array(pa[:2])
        cn = c / (np.linalg.norm(c) or 1.0)
        if (da is not None and da @ cn < -0.34) or (db is not None and db @ -cn < -0.34):
            continue                                # demi-tour : le raccord repasserait le long du mur
        via = route(pa, pb, 1.4 * dist + 200) if route is not None else None   # le long de l'objet
        if via is None and da is not None and db is not None:   # coin : les murs prolonges se croisent pres des bouts
            M = np.array([da, -db]).T
            if abs(np.linalg.det(M)) > 0.2:
                t1, t2 = np.linalg.solve(M, c)
                if 0 < t1 <= 0.75 * join and 0 < t2 <= 0.75 * join:
                    x = np.array(pa[:2]) + da * t1
                    via = [[float(x[0]), float(x[1]), float(pa[2] + (pb[2] - pa[2]) * t1 / (t1 + t2))]]
                    if not (clear(pa, via[0]) and clear(via[0], pb)):
                        via = None
        if via is None:
            if not clear(pa, pb):
                continue
            via = []
        taken.update((a, b))
        links[(ka, ea)] = (kb, eb, via)
        links[(kb, eb)] = (ka, ea, via[::-1])
        root[ra] = rb
        if ra != rb:
            size[rb] += size[ra] + dist
    # assemblage : on suit les raccords de noeud en noeud
    out, seen = [], set()
    for k in closed_big:
        seen.add(k)
        out.append({'points': nodes[k][0], 'reason': nodes[k][1]})
    order = sorted(range(len(nodes)), key=lambda k: ((k, 0) in links) + ((k, 1) in links))   # bouts libres d'abord
    for start in order:
        if start in seen:
            continue
        e_in = 0 if (start, 0) not in links else (1 if (start, 1) not in links else 0)
        pts, reasons, k, e = [], [], start, e_in
        loop = False
        while True:
            seen.add(k)
            P, reason, small = nodes[k]
            if not links.get((k, e)) and small is not None and not pts and (k, 1 - e) not in links:
                P = small                            # petite boucle restee seule : gardee telle quelle
            seg = P if e == 0 else P[::-1]
            pts += seg if not pts or math.dist(pts[-1][:2], seg[0][:2]) > 1e-3 else seg[1:]
            reasons.append(reason)
            nxt = links.get((k, 1 - e))
            if nxt is None:
                break
            k2, e2, via = nxt
            pts += via
            if k2 in seen:
                pts.append(nodes[k2][0][0] if e2 == 0 else nodes[k2][0][-1])
                loop = True
                break
            k, e = k2, e2
        if loop and math.dist(pts[0][:2], pts[-1][:2]) > 1e-3:
            pts.append(pts[0])
        out.append({'points': pts, 'reason': max(set(reasons), key=reasons.count)})
    return out


def zone(ground, tris, corridor=None, margin=40.0, piece=PIECE, offroad=False, min_len=200.0, height=HEIGHT,
         join=0.0):
    """Murs le long des bords des objets choisis (triangles monde (n, 3, 3) de la selection) :
      * bords = aretes du dessus (triangles tournes vers le haut) qui n'appartiennent qu'a un triangle (sommets
        fusionnes a 2 po pres) ;
      * au-dela d'un bord (vers l'exterieur) : sol de la selection au meme niveau (raccord entre deux objets choisis),
        mur ou talus deja la -> rien ; plus de sol au niveau du bord -> mur ; autre sol au meme niveau -> mur seulement
        si offroad ;
      * jamais dans la bande de la route (corridor) : raccords de la route, croisements du trace.
    Mur pose a `margin` vers l'exterieur. join (pouces) : les trous du contour d'au plus join sont fermes en suivant
    le bord, puis les bouts de murs a moins de join sont relies (barriere : de poteau en poteau) ; jamais sur la route
    ni a travers le dessus des objets choisis. -> morceaux [{'reason', 'points'}] (comme generate)."""
    T = np.asarray(tris, np.float64)
    if not len(T):
        return []
    n = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
    a = np.linalg.norm(n, axis=1)
    top = n[:, 2] > 0.5 * np.maximum(a, 1e-9)
    T_all, top_all = T[a > 1e-6], top[a > 1e-6]
    T = T[(a > 1e-6) & top]
    if not len(T):
        return []
    sel = ai_gen.GroundQuery(T, [0] * len(T))
    V, inv = np.unique(np.round(T.reshape(-1, 3) / 2.0).astype(np.int64), axis=0, return_inverse=True)
    F = inv.reshape(-1, 3)
    P = np.zeros((len(V), 3))
    np.add.at(P, F.reshape(-1), T.reshape(-1, 3))
    P /= np.bincount(F.reshape(-1), minlength=len(V))[:, None]
    edges = {}
    for f in F:
        for k in range(3):
            e = (min(f[k], f[(k + 1) % 3]), max(f[k], f[(k + 1) % 3]))
            edges.setdefault(e, []).append(f[(k + 2) % 3])
    # bords du dessus : (normale exterieure, etat) ; etat 'void' | 'offroad' (mur), 'road' (sur la route), 'seam'
    # (raccord entre deux objets choisis), 'skip' (mur deja la, ou autre sol sans offroad)
    border = {}
    for (i, j), opp in edges.items():
        if len(opp) != 1 or i == j:
            continue
        pa, pb, pc = P[i], P[j], P[opp[0]]
        d = pb[:2] - pa[:2]
        L = float(np.linalg.norm(d))
        if L < 1e-3:
            continue
        nrm = np.array([d[1], -d[0]]) / L
        if nrm @ (pc[:2] - pa[:2]) > 0:
            nrm = -nrm
        m = (pa + pb) / 2
        out = m[:2] + nrm * ai_gen.STEP
        # le mur serait sur la route (raccord, croisement, dessous) : teste tout le long du bord (bout coupe d'une
        # route au bord d'un saut : un seul long bord en travers, sa moitie hors de la bande mesuree trop etroite)
        on_road = corridor is not None and any(
            corridor.inside(*(q[:2] + nrm * (margin + 40)), q[2], q[2] - SINK, q[2] + height)
            for q in (pa + (pb - pa) * s for s in np.linspace(0, 1, max(2, int(L // 150) + 1))))
        if on_road:
            state = 'road'
        elif any(abs(h - m[2]) <= ai_gen.MAX_STEP for h in sel.heights(*out)):
            state = 'seam'
        else:
            r = _beyond(ground, m[:2] - nrm * 20, nrm, 20, m[2], max(margin, ai_gen.STEP))
            state = r if r == 'void' or (r == 'offroad' and offroad) else 'skip'
            if state == 'void' and _jump_edge(sel, corridor, m, nrm):
                state = 'road'                          # bout de route au bord d'un saut : jamais de mur devant
        border[(i, j)] = (nrm, state)
    wall = ('void', 'offroad')
    # trous du contour (bord deja ferme, autre sol) d'au plus `join` entre deux murs : fermes en suivant le bord
    if join > 0:
        for chain in _chains(list(border)):
            ks = [(min(a_, b_), max(a_, b_)) for a_, b_ in zip(chain, chain[1:])]
            st = [border[k][1] for k in ks]
            n_, ring = len(ks), chain[0] == chain[-1]
            if not any(s in wall for s in st) or all(s in wall for s in st):
                continue
            idx = list(range(n_))
            if ring:                                    # commence sur un mur : chaque trou est entre deux murs
                s0 = next(q for q in idx if st[q] in wall)
                idx = idx[s0:] + idx[:s0]
            runs, cur = [], []
            for r in idx:
                if st[r] not in wall:
                    cur.append(r)
                    continue
                if cur and cur[0] != idx[0]:            # (chaine ouverte : trou au bout, rien a relier)
                    runs.append(cur)
                cur = []
            if cur and ring:
                runs.append(cur)
            for run in runs:
                ln = sum(float(np.linalg.norm(P[ks[r][0]][:2] - P[ks[r][1]][:2])) for r in run)
                if ln <= join and all(st[r] == 'skip' for r in run):
                    reason = st[(run[0] - 1) % n_]
                    for r in run:
                        border[ks[r]] = (border[ks[r]][0], reason)
    kept = {k: (nrm, s) for k, (nrm, s) in border.items() if s in wall}
    chains = _chains(list(kept))
    lines = []
    for chain in chains:
        # normale exterieure de chaque sommet : moyenne de celles de ses bords dans la chaine
        nv = {}
        for a_, b_ in zip(chain, chain[1:]):
            e = (min(a_, b_), max(a_, b_))
            for v in (a_, b_):
                nv[v] = nv.get(v, np.zeros(2)) + kept[e][0]
        pts = []
        for v in chain:
            k = nv[v] / (np.linalg.norm(nv[v]) or 1.0)
            pts.append([float(P[v][0] + k[0] * margin), float(P[v][1] + k[1] * margin), float(P[v][2])])
        reasons = [kept[(min(a_, b_), max(a_, b_))][1] for a_, b_ in zip(chain, chain[1:])]
        lines.append({'points': _simplify(pts, 20.0), 'reason': max(set(reasons), key=reasons.count)})

    def clear(a, b):
        """Raccord a -> b : ni sur la route, ni a travers le dessus des objets choisis (bouts exclus)."""
        L = math.dist(a[:2], b[:2])
        for k in range(1, max(2, int(L // 100))):
            t = k / max(2, int(L // 100))
            if min(t * L, (1 - t) * L) < 150:
                continue
            x, y, z = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)
            if corridor is not None and corridor.inside(x, y, z, z - SINK, z + height):
                return False
            if any(abs(h - z) <= 150 for h in sel.heights(x, y)):
                return False
        return True
    out = []
    for ln in _join(lines, join, clear, _mesh_router(T_all, top_all, corridor, height) if join > 0 else None):
        pts, reason = ln['points'], ln['reason']
        length = _plen(pts)
        if length < min_len or len(pts) < 2:
            continue
        seg, acc = [pts[0]], 0.0
        for p, q in zip(pts, pts[1:]):
            acc += math.dist(p[:2], q[:2])
            seg.append(q)
            if acc >= piece:
                out.append({'reason': reason, 'points': seg})
                seg, acc = [q], 0.0
        if len(seg) >= 2:
            out.append({'reason': reason, 'points': seg})
    return out


def _simplify(pts, tol):
    """Douglas-Peucker (plan horizontal) : polyligne allegee a tol pouces pres, bouts gardes."""
    if len(pts) < 3:
        return pts
    P = np.array(pts)
    a, b = P[0, :2], P[-1, :2]
    d = b - a
    L = np.linalg.norm(d)
    dist = (np.abs(d[0] * (P[:, 1] - a[1]) - d[1] * (P[:, 0] - a[0])) / L) if L > 1e-6 else np.linalg.norm(P[:, :2] - a, axis=1)
    k = int(np.argmax(dist))
    if dist[k] <= tol:
        return [pts[0], pts[-1]]
    return _simplify(pts[:k + 1], tol)[:-1] + _simplify(pts[k:], tol)


def generate(ground, loop, road_ground=None, margin=MARGIN, piece=PIECE, sides='both', offroad=False, sample=SAMPLE):
    """Morceaux de murs invisibles le long des deux bords du trace ferme `loop` (voir l'en-tete) ; la hauteur est
    celle de ribbon, a la construction."""
    pts, zs, tang, road, ground_w = _line(ground, loop, road_ground, sample)
    n = len(pts)
    heads = [math.atan2(t[1], t[0]) for t in tang]
    turn = [math.remainder(heads[(i + 1) % n] - heads[(i - 1) % n], 2 * math.pi) / (2 * sample) for i in range(n)]
    turn = ai_gen._smooth(turn, 5)
    xy = np.array([[p[0], p[1]] for p in pts])
    zarr = np.array([z if z is not None else p[2] for p, z in zip(pts, zs)])
    want = []
    for name, sgn in (('left', 1.0), ('right', -1.0)):
        if sides not in ('both', name):
            continue
        dist, zedge, keep, reason = [], [], [], []
        for i, p in enumerate(pts):
            side = (-tang[i][1] * sgn, tang[i][0] * sgn)
            if zs[i] is None:
                dist.append(0.0), zedge.append(p[2]), keep.append(False), reason.append('')
                continue
            d, ze = _edge(ground_w, p, side, zs[i], road)
            r = _beyond(ground, p, side, d, ze, margin) if d > 0 else ''
            dist.append(d), zedge.append(ze), reason.append(r)
            keep.append(r == 'void' or (r == 'offroad' and offroad))
        # bord lisse sur ~30 m, sans les points ou le trace n'a pas de route dessous (largeur 0 : sous un pont, la
        # moyenne ramenait le mur sur le trace)
        valid = [z is not None for z in zs]
        dist = _smooth_valid(dist, valid, max(1, int(round(1200 / sample))))
        zedge = _smooth_valid(zedge, valid, 3)
        wall = []
        for i, p in enumerate(pts):
            off = dist[i] + margin
            side = (-tang[i][1] * sgn, tang[i][0] * sgn)
            inner = turn[i] * sgn > 0                   # virage vers ce cote
            if keep[i] and inner and abs(turn[i]) > 1e-6 and off > 0.8 / abs(turn[i]):
                keep[i] = False                         # interieur d'un virage trop serre : le mur se replierait
            x, y = p[0] + side[0] * off, p[1] + side[1] * off
            if keep[i]:                                 # pas sur une autre partie de la route (epingle, croisement)
                g = ground_w.at(x, y, zedge[i], window=300.0)
                if g is not None and g[1] in road and road_ground is not None:
                    keep[i] = False
            if keep[i]:                                 # ni plus pres d'un autre point du trace que de son propre
                near = np.hypot(xy[:, 0] - x, xy[:, 1] - y)
                near = near[np.abs(zarr - zedge[i]) < 600]
                if len(near) and near.min() < 0.85 * off:
                    keep[i] = False
            wall.append([x, y, zedge[i]])
        # tronçons consecutifs (le trace est ferme : un tronçon peut passer par le point de depart)
        if all(keep):
            runs = [list(range(n)) + [0]]
        else:
            start = next(i for i in range(n) if not keep[i])
            runs, cur = [], []
            for j in range(1, n + 1):
                i = (start + j) % n
                if keep[i] and (not cur or math.dist(wall[cur[-1]][:2], wall[i][:2]) < 3 * sample):
                    cur.append(i)
                    continue
                if len(cur) >= MIN_RUN:
                    runs.append(cur)
                cur = [i] if keep[i] else []
            if len(cur) >= MIN_RUN:
                runs.append(cur)
        pieces = []
        for run in runs:
            seg, length = [run[0]], 0.0
            for a, b in zip(run, run[1:]):
                length += math.dist(wall[a][:2], wall[b][:2])
                seg.append(b)
                if length >= piece:
                    pieces.append(seg)
                    seg, length = [b], 0.0
            if len(seg) >= 2:
                pieces.append(seg)
        for seg in pieces:
            rs = [reason[i] for i in seg]
            want.append({'side': name, 'reason': max(set(rs), key=rs.count),
                         'points': [[float(v) for v in wall[i]] for i in seg]})
    return want
