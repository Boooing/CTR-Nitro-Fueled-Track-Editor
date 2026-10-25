"""Chutes et reapparitions automatiques le long du parcours (pouces).

  respawn_layout(path, starts, spacing)   -> points de reapparition regulierement espaces, section de chacun
  find_fall_zones(path, ground, road)     -> zones de chute (trous / vides a cote de la route)

Rappels (fichiers de Crash Cove) :
  * point de reapparition = CPlayerStartEntity du _Design (« Respawn_waypointNNN »), position +0x20, cap dans sa
    transformation ; chaque spline de position liste les siens (CRaceTrackSplineComponentData._respawnPoints) ;
  * zone de chute = CEntity « Respawn_Trigger_* » : boite CTriggerVolumeBoxComponentData (dimensions completes,
    centree sur l'entite) + CRespawnTriggerComponentData._respawnPoints (tag EntityTags::PlayerStart puis 3 points) ;
  * plancher du monde = CWorldEntityData._killz (fichier principal de la piste) : en dessous, le kart est « tombe ».
"""
import math

import numpy as np

M = 39.37


def arc(P):
    """Abscisse curviligne (vue de dessus) de chaque point."""
    seg = np.linalg.norm(np.diff(P[:, :2], axis=0), axis=1)
    return np.concatenate([[0.0], np.cumsum(seg)])


def project(P, S, q):
    """Abscisse du point du chemin le plus proche de q (vue de dessus)."""
    return float(S[int(np.argmin(np.linalg.norm(P[:, :2] - np.asarray(q[:2]), axis=1)))])


def pose_at(P, S, s, lift=50.0):
    """Position (+ lift) et cap du chemin a l'abscisse s."""
    s = min(max(s, 0.0), S[-1])
    i = int(min(len(P) - 2, max(0, np.searchsorted(S, s, side='right') - 1)))
    k = (s - S[i]) / max(S[i + 1] - S[i], 1e-9)
    p = P[i] + (P[i + 1] - P[i]) * k
    t = P[min(len(P) - 1, i + 1), :2] - P[i, :2]
    return [float(p[0]), float(p[1]), float(p[2]) + lift], math.atan2(t[1], t[0])


def section_starts(path, positions):
    """Abscisses des transitions sur le chemin raccorde (splines de position qui se chevauchent : la ligne
    d'arrivee est pres du debut ET de la fin). positions = transitions dans l'ordre de course, la 1re = ligne
    d'arrivee. -> (debuts des sections, fin du tour)."""
    P = np.asarray(path, np.float64)
    S = arc(P)
    near = lambda q, lo, hi: lo + int(np.argmin(np.linalg.norm(P[lo:hi, :2] - np.asarray(q[:2]), axis=1)))
    half = len(P) // 2
    i0 = near(positions[0], 0, half)
    starts, i = [S[i0]], i0
    for q in positions[1:]:
        i = near(q, i + 1, len(P))
        starts.append(S[i])
    end = S[near(positions[0], max(i + 1, half), len(P))] if i + 1 < len(P) else S[-1]
    return starts, end


def _off_air(S, air, s, margin=4 * M):
    """Abscisse deplacee hors d'un trou (air : booleens par point du chemin) : apres la reception si possible (le
    point le plus proche sur la route, `margin` plus loin que le bord), sinon avant le tremplin."""
    if air is None:
        return s
    i = int(min(len(S) - 1, max(0, np.searchsorted(S, s, side='right') - 1)))
    if not air[i] and not air[min(i + 1, len(S) - 1)]:
        return s
    after = next((k for k in range(i, len(S)) if not air[k]), None)
    if after is not None:
        return min(S[after] + margin, S[-1])
    before_ = next((k for k in range(i, -1, -1) if not air[k]), None)
    return max(S[before_] - margin, 0.0) if before_ is not None else s


def respawn_layout(path, starts, end, spacing, minimum=0, lift=50.0, air=None):
    """Points de reapparition tous les ~`spacing` po sur un tour (au moins `minimum`), au milieu de parts egales.
    starts = debuts des sections (la 1re = ligne d'arrivee), end = fin du tour (section_starts). air : booleens par
    point du chemin (au-dessus d'un trou franchi par un saut) : aucun point n'y est pose (deplace a la reception).
    -> [(section, pos, cap, abscisse)] dans l'ordre de course."""
    P = np.asarray(path, np.float64)
    S = arc(P)
    lap = end - starts[0]
    n = max(int(minimum), int(round(lap / max(spacing, 1.0))), len(starts))
    out = []
    for j in range(n):
        s = _off_air(S, air, starts[0] + (j + 0.5) * lap / n)
        sec = max(k for k in range(len(starts)) if starts[k] <= s)
        pos, yaw = pose_at(P, S, s, lift)
        out.append((sec, pos, yaw, s))
    for k in range(len(starts)):                       # chaque section a au moins un point
        if not any(o[0] == k for o in out):
            s = _off_air(S, air, (starts[k] + (starts[k + 1] if k + 1 < len(starts) else end)) / 2)
            pos, yaw = pose_at(P, S, s, lift)
            out.append((k, pos, yaw, s))
    return sorted(out, key=lambda o: o[3])


def before(points, s, count=3):
    """Indices des `count` points de reapparition qui precedent l'abscisse s (tour boucle)."""
    prev = [i for i, p in enumerate(points) if p[3] <= s]
    order = prev[::-1] + [i for i in range(len(points) - 1, -1, -1) if i not in prev]
    return order[:count]


def find_fall_zones(path, ground, road=None, step=5 * M, reach=40 * M, drop=6 * M, max_half=60 * M, killz=None):
    """Zones ou un kart qui quitte la route tombe : a cote de la route (de son bord jusqu'a `reach`), pas de sol a
    moins de `drop` sous la route (vide, trou, eau sans collision). ground / road : GroundQuery (sol complet / route
    seule). -> [{'center', 'dims', 's', 'side', 'samples'}] (boites alignees sur les axes, sommet 4 m sous la route,
    profondeur 20 m). Les morceaux du parcours lui-meme (route qui passe dessous) ne sont jamais pris."""
    P = np.asarray(path, np.float64)
    S = arc(P)
    idx = [0]
    for i in range(1, len(P)):
        if S[i] - S[idx[-1]] >= step:
            idx.append(i)
    holes = []                                         # (indice d'echantillon, cote, x, y, z route)
    for j, i in enumerate(idx):
        p = P[i]
        t = P[min(len(P) - 1, i + 1), :2] - P[max(0, i - 1), :2]
        t = t / (np.linalg.norm(t) or 1.0)
        nrm = np.array([-t[1], t[0]])
        for side in (-1, 1):
            # bord de la route : premier point sans route (route seule connue) ou 6 m (a defaut)
            edge = 6 * M
            if road is not None:
                edge = max_half
                for d in np.arange(2 * M, max_half, 2 * M):
                    x, y = p[:2] + side * d * nrm
                    if road.top(x, y, p[2] + 300) is None:
                        edge = d
                        break
            for d in np.arange(edge + 2 * M, edge + reach, 4 * M):
                x, y = p[:2] + side * d * nrm
                # un autre morceau du parcours plus pres : ce n'est plus le bord de celui-ci
                if np.min(np.linalg.norm(P[:, :2] - [x, y], axis=1)) < d - 1:
                    break
                if road is not None and road.heights(x, y):
                    continue                           # route (plus haut ou plus bas) : pas un trou
                h = ground.top(x, y, p[2] + 300)
                z = h[0] if isinstance(h, (tuple, list)) else h
                if z is None or z < p[2] - drop:
                    holes.append((j, side, x, y, p[2]))
    zones = []
    for side in (-1, 1):
        pts = sorted((h for h in holes if h[1] == side), key=lambda h: h[0])
        run = []
        for h in pts + [None]:
            if h is not None and (not run or h[0] - run[-1][0] <= 2):
                run.append(h)
                continue
            if len(run) >= 2:
                A = np.array([[r[2], r[3]] for r in run])
                ztop = min(r[4] for r in run) - 4 * M
                lo, hi = A.min(0) - 3 * M, A.max(0) + 3 * M
                depth = 20 * M if killz is None else min(20 * M, max(4 * M, ztop - killz))
                box = {'center': [float((lo[0] + hi[0]) / 2), float((lo[1] + hi[1]) / 2), float(ztop - depth / 2)],
                       'dims': [float(hi[0] - lo[0]), float(hi[1] - lo[1]), float(depth)],
                       's': float(S[idx[run[0][0]]]), 'side': side, 'samples': len(run)}
                if not _crosses_route(box, P):
                    zones.append(box)
            run = [h] if h is not None else []
    return sorted(zones, key=lambda z: z['s'])


def _crosses_route(box, P):
    """La boite contient-elle un point du parcours (route qui passe sous un pont, par ex.) ?"""
    c, d = np.asarray(box['center']), np.asarray(box['dims']) / 2 + [2 * M, 2 * M, 3 * M]
    return bool(np.any(np.all(np.abs(P - c) <= d, axis=1)))


def killz_for(path, margin=30 * M):
    """Plancher du monde propose : `margin` sous le point le plus bas du parcours."""
    return float(np.asarray(path, np.float64)[:, 2].min() - margin)
