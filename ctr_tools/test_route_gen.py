"""Test : trace deduit de la route seule (Crash Cove) compare au trace du jeu, decoupage en sections.

Usage : python test_route_gen.py <dossier archives>
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ai_gen  # noqa: E402
import pak_tool  # noqa: E402
import route_gen  # noqa: E402
import start_finish  # noqa: E402
from race_entities import RaceSystemEditor  # noqa: E402
from race_system import RaceSystem  # noqa: E402

T, TP = 'T111_Crash_Cove', 't111_crash_cove.pak'


def check(cond, msg):
    print(('OK   ' if cond else 'ECHEC') + ' ' + msg)
    if not cond:
        raise SystemExit(1)


def main(archives):
    g = ai_gen.GroundQuery.from_hkx(pak_tool.read_latest(archives, f'models/maps/Octane/{T}/StaticCollision_{T}.hkx', TP)[0])
    race = pak_tool.read_latest(archives, f'maps/Octane/{T}/{T}_RaceSystem.igz', TP)[0]
    rs = RaceSystem(race, file_ns=f'{T}_RaceSystem').decode()
    pos0, yaw, _ = start_finish.transition_pose(RaceSystemEditor(race, T), 'RaceSystem_SplineTransition_01')
    tris = g.t[np.isin(g.v, [38, 13, 5])]                        # sable, bois, surfaces sous le trace du jeu
    z0 = g.at(pos0[0], pos0[1], pos0[2] - 660, window=1500.0)[0]
    loop = route_gen.road_loop(tris, pos0[:2], yaw, ground=g, start_z=z0)
    L = np.array(loop['points'])
    check(1800 * 39.37 < loop['length'] < 2800 * 39.37, f"boucle fermee de {loop['length'] / 39.37:.0f} m")
    ref = np.vstack([np.array(ai_gen.catmull_rom(p['control_points'], 200))[:, :2] for p in rs['position_paths']])
    d = np.array([np.min(np.linalg.norm(ref - q[:2], axis=1)) for q in L])
    check(np.median(d) < 300 and d.max() < 2500,
          f'proche du trace du jeu : ecart median {np.median(d) / 39.37:.1f} m, max {d.max() / 39.37:.0f} m (zones tres larges)')
    check(L[:, 2].max() < 1700, f'hauteur continue (max {L[:, 2].max():.0f} po : pas de saut sur une passerelle)')
    first_step = L[1, :2] - L[0, :2]
    check(first_step @ np.array([np.cos(yaw), np.sin(yaw)]) > 0, 'parcouru dans le sens de la course depuis la ligne')
    lay = route_gen.layout(loop, 4)
    check(len(lay['sections']) == 4 and all(len(s) >= 4 for s in lay['sections']), f"4 sections de {[len(s) for s in lay['sections']]} points")
    t0 = lay['transitions'][0]
    check(np.linalg.norm(np.array(t0['position'][:2]) - np.array(pos0[:2])) < 600 and t0['dimensions'][0] == 1000.0,
          'ligne d\'arrivee recalculee au depart, zone plus profonde')
    poses = route_gen.spread_on_path(lay['section_paths'][1], 3)
    check(len(poses) == 3 and all(g.at(p['pos'][0], p['pos'][1], p['pos'][2] - 50, window=400.0) for p in poses),
          '3 points de reapparition poses sur le sol de la section 2')
    overpass(check)
    jump(check)
    print('tous les tests passent')


def jump(check):
    """Stade de 1,4 km avec un trou de 30 m sous un saut (tremplins a 300 po) : le trace franchit le trou (hauteur
    gardee au-dessus), et aucun point de reapparition n'y est pose."""
    import falls
    M = 39.37
    L, R, w, gap = 400 * M, 100 * M, 600.0, 30 * M
    C = np.vstack([np.stack([np.linspace(-L / 2, L / 2, 200, endpoint=False), np.full(200, -R)], 1),
                   [(L / 2 + R * np.cos(a), R * np.sin(a)) for a in np.linspace(-np.pi / 2, np.pi / 2, 100, endpoint=False)],
                   np.stack([np.linspace(L / 2, -L / 2, 200, endpoint=False), np.full(200, R)], 1),
                   [(-L / 2 + R * np.cos(a), R * np.sin(a)) for a in np.linspace(np.pi / 2, 3 * np.pi / 2, 100, endpoint=False)]])
    zf = lambda p: 300.0 if p[1] < -R + 1 and abs(p[0]) < 60 * M else 0.0
    tris = []
    for i in range(len(C)):
        j = (i + 1) % len(C)
        if abs((C[i][1] + C[j][1]) / 2 + R) < 1 and abs((C[i][0] + C[j][0]) / 2) < gap / 2:
            continue
        d = C[j] - C[i]
        n = np.array([-d[1], d[0]]) / np.linalg.norm(d) * w
        a, b, c, e = (np.r_[C[i] + n, zf(C[i])], np.r_[C[i] - n, zf(C[i])], np.r_[C[j] + n, zf(C[j])], np.r_[C[j] - n, zf(C[j])])
        tris += [[a, b, c], [b, e, c]]
    tris = np.array(tris)
    try:
        route_gen.road_loop(tris, [-150 * M, -R], 0.0, max_gap=0)
        cut = False
    except ValueError:
        cut = True
    loop = route_gen.road_loop(tris, [-150 * M, -R], 0.0, max_gap=40 * M)
    P, air = np.array(loop['points']), np.array(loop['air'])
    check(cut and loop['jumps'] == 1 and loop['length'] > 1350 * M,
          f"saut : sans franchissement pas de boucle ; avec, trou de 30 m franchi ({loop['length'] / M:.0f} m)")
    check(air.any() and np.allclose(P[air, 2], 300.0), f'au-dessus du trou : {air.sum()} point(s) a la hauteur des tremplins')
    S = falls.arc(P)
    pts = falls.respawn_layout(P, [0.0], S[-1], 8 * M, air=air)            # un point tous les 8 m : certains tombent sur le trou
    over = [p for p in pts if abs(p[1][1] + R) < 2 * M and abs(p[1][0]) < gap / 2]
    check(len(pts) > 100 and not over, f'{len(pts)} points de reapparition, aucun au-dessus du trou')


def overpass(check):
    """Circuit en 8 dont une branche passe sur un pont au croisement (Roo's Tubes importe) : le trace doit suivre
    toute la route (traverser le croisement deux fois, tout droit), pas couper au plus court."""
    A, w = 20000.0, 600.0                                          # ~500 m, route de 30 m
    t = np.linspace(0, 2 * np.pi, 1200, endpoint=False)
    C = np.stack([A * np.sin(t), A * np.sin(t) * np.cos(t)], 1)
    tw = (t + np.pi) % (2 * np.pi) - np.pi
    Z = 700.0 * np.exp(-(tw / 0.5) ** 2)                            # pont au croisement de t = 0, dessous a t = pi
    tris = []
    for i in range(len(t)):
        j = (i + 1) % len(t)
        d = C[j] - C[i]
        n = np.array([-d[1], d[0]]) / np.linalg.norm(d) * w
        a, b = np.r_[C[i] + n, Z[i]], np.r_[C[i] - n, Z[i]]
        c, e = np.r_[C[j] + n, Z[j]], np.r_[C[j] - n, Z[j]]
        tris += [[a, b, c], [b, e, c]]
    length = float(np.linalg.norm(np.roll(C, -1, 0) - C, axis=1).sum())
    loop = route_gen.road_loop(np.array(tris), [A, 0.0], -np.pi / 2)
    P = np.array(loop['points'])
    check(loop['length'] > 0.9 * length, f"8 avec pont : boucle de {loop['length'] / 39.37:.0f} m sur {length / 39.37:.0f} m (pas de raccourci)")
    near = P[np.hypot(P[:, 0], P[:, 1]) < 1500]
    check(near[:, 2].max() > 500 and near[:, 2].min() < 200, 'croisement traverse deux fois : sur le pont puis dessous')


if __name__ == '__main__':
    main(sys.argv[1])
