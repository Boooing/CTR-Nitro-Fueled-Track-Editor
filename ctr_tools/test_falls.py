"""Test : chutes et reapparitions automatiques (falls.py + server.auto_falls).

Usage : python test_falls.py <dossier archives>
"""
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'editor'))
import falls  # noqa: E402
from ai_gen import GroundQuery  # noqa: E402

M = 39.37


def check(cond, msg):
    print(('OK   ' if cond else 'ECHEC') + ' ' + msg)
    if not cond:
        raise SystemExit(1)


def quad(x0, y0, x1, y1, z):
    return [[[x0, y0, z], [x1, y0, z], [x1, y1, z]], [[x0, y0, z], [x1, y1, z], [x0, y1, z]]]


def synthetic():
    """Boucle carree de 400 m (route de 20 m) sur un sol plat, sauf un trou de 60 m a l'exterieur du cote sud."""
    L, w = 400 * M, 10 * M
    road = (quad(-w, -w, L + w, w, 0) + quad(-w, L - w, L + w, L + w, 0) + quad(-w, -w, w, L + w, 0)
            + quad(L - w, -w, L + w, L + w, 0))
    cells = []
    for x in range(-100, 500, 20):
        for y in range(-100, 500, 20):
            if 150 <= x < 210 and -100 <= y < -10:
                continue                                   # le trou (exterieur, au sud)
            cells += quad(x * M, y * M, (x + 20) * M, (y + 20) * M, -2 * M)
    ground = GroundQuery(np.array(road + cells), [38] * (len(road) + len(cells)))
    road_q = GroundQuery(np.array(road), [38] * len(road))
    loop = [[x * M, 0, 0] for x in range(0, 400, 5)] + [[400 * M, y * M, 0] for y in range(0, 400, 5)] \
        + [[x * M, 400 * M, 0] for x in range(400, 0, -5)] + [[0, y * M, 0] for y in range(400, -5, -5)]
    return ground, road_q, np.array(loop, float)


def main(archives):
    ground, road, P = synthetic()
    zones = falls.find_fall_zones(P, ground, road)
    check(len(zones) == 1, f'trou de 60 m a cote de la route : {len(zones)} zone(s) de chute')
    z = zones[0]
    check(150 * M - 4 * M <= z['center'][0] <= 210 * M + 4 * M and z['center'][1] < 0 and z['center'][2] < -4 * M,
          f"zone sous le trou : centre ({z['center'][0] / M:.0f}, {z['center'][1] / M:.0f}, {z['center'][2] / M:.0f}) m, "
          f"{z['dims'][0] / M:.0f} x {z['dims'][1] / M:.0f} x {z['dims'][2] / M:.0f} m")
    starts, end = falls.section_starts(P, [[0, 0, 0], [400 * M, 0, 0], [400 * M, 400 * M, 0], [0, 400 * M, 0]])
    pts = falls.respawn_layout(P, starts, end, 50 * M)
    secs = [p[0] for p in pts]
    check(len(pts) == 32 and secs == sorted(secs) and all(secs.count(k) == 8 for k in range(4)),
          f'1 600 m, un point tous les 50 m : {len(pts)} points, 8 par section, dans l\'ordre')
    check(abs(pts[0][2]) < 1e-6 and abs(pts[8][2] - np.pi / 2) < 1e-6, 'caps dans le sens de la course')
    check(falls.before(pts, z['s']) == [11, 10, 9] or len(falls.before(pts, z['s'])) == 3,
          f"reapparitions de la zone : points {falls.before(pts, z['s'])} (juste avant le trou)")
    # piste du jeu : Crash Cove d'origine (eau, falaises) dans un dossier temporaire
    import server
    server.ARCHIVES = archives
    with tempfile.TemporaryDirectory() as d:
        server.OUT_DIR = d
        T = 'T111_Crash_Cove'
        r = server.auto_falls({'track': T, 'spacing': 40, 'killz': True, 'zones': True})
        print('      ' + ' · '.join(r['report']))
        tr = server.load_track(T)
        n = sum(len(s.get('respawn_points') or []) for s in tr['splines'] if s['kind'] == 'position_paths')
        check(n == len(r['points']) and n >= 22, f'{n} points de reapparition relus dans les splines de position')
        kz = server.world_killz(T)
        check(abs(kz - r['killz']) < 1, f'plancher de chute relu : {kz:.0f}')
        r2 = server.auto_falls({'track': T, 'spacing': 200, 'killz': False, 'zones': True})
        n2 = sum(len(s.get('respawn_points') or []) for s in server.load_track(T)['splines'] if s['kind'] == 'position_paths')
        check(n2 == 22, f'2e calcul (200 m) : {n2} points (les 22 d\'origine), clones en trop retires des listes')
    print('tous les tests passent')


if __name__ == '__main__':
    main(sys.argv[1])
