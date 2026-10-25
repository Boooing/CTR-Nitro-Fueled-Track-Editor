"""Test : generation automatique de splines IA d'apres le sol (Crash Cove, section Position_Spline_02).

Usage : python test_ai_gen.py <dossier archives>
"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ai_gen  # noqa: E402
import pak_tool  # noqa: E402
from race_system import RaceSystem  # noqa: E402

T, TP = 'T111_Crash_Cove', 't111_crash_cove.pak'


def check(cond, msg):
    print(('OK   ' if cond else 'ECHEC') + ' ' + msg)
    if not cond:
        raise SystemExit(1)


def main(archives):
    g = ai_gen.GroundQuery.from_hkx(pak_tool.read_latest(archives, f'models/maps/Octane/{T}/StaticCollision_{T}.hkx', TP)[0])
    rs = RaceSystem(pak_tool.read_latest(archives, f'maps/Octane/{T}/{T}_RaceSystem.igz', TP)[0], file_ns=f'{T}_RaceSystem').decode()
    pos = next(p for p in rs['position_paths'] if p['name'].endswith('02'))
    ref = pos['control_points']
    q = g.at(ref[3][0], ref[3][1], ref[3][2])
    check(q is not None and abs(q[0] - ref[3][2]) < 400, f'sol sous la reference : z {q[0]:.0f} (point {ref[3][2]:.0f}), surface {q[1]}')
    r = ai_gen.generate_lanes(g, ref, n=4, randomness=0.5, seed=7)
    check(len(r['lanes']) == 4 and all(len(l) >= 4 for l in r['lanes']), f"4 voies de {[len(l) for l in r['lanes']]} points")
    check(38 in r['road_surfaces'], f"surface de route detectee : {r['road_surfaces']}")
    w = [a + b for a, b in r['widths']]
    check(400 < np.median(w) < 6000, f'largeur de route mediane {np.median(w) / 39.37:.0f} m')
    on, total = 0, 0
    for lane in r['lanes']:
        for p in ai_gen.catmull_rom(lane, 300):
            gq = g.at(p[0], p[1], p[2] - 80)
            total += 1
            on += bool(gq and abs(gq[0] - (p[2] - 80)) < 150)
    # hauteur : le reste passe en l'air au-dessus du creux du saut (position horizontale verifiee plus bas)
    check(on / total > 0.85, f'{100 * on / total:.0f} % des points des voies a ~80 po au-dessus du sol')
    gaps = [math.dist(a, b) for lane in r['lanes'] for a, b in zip(lane, lane[1:])]
    check(600 < np.median(gaps) < 3500, f'espacement des points ~{np.median(gaps):.0f} po (jeu : ~2700, resserre dans les virages)')
    # la courbe lissee entre les points de controle reste sur la route (c'est elle que l'IA suit)
    road = set(r['road_surfaces']) | {g.at(p[0], p[1], p[2])[1] for p in ai_gen.catmull_rom(ref, 300) if g.at(p[0], p[1], p[2])}
    off = ai_gen.offroad_ratio(g, r['lanes'], road)
    check(off < 0.005, f'courbe suivie hors de la route : {100 * off:.1f} % (avant le correctif : 0,8 %)')
    # fidelite : une voie en S serre, la courbe passant par les points de controle reste a moins de 150 po de la voie
    path = [[x, 3000 * math.sin(x / 2000), 0] for x in np.arange(0, 20000, 300)]
    ctrl = ai_gen.fit_controls(path, 2500)
    curve, _ = ai_gen.curve_uniform(ctrl, 12)
    dev = max(ai_gen._dist_to_polyline(np.array(c[:2]), np.array(path)[:, :2]) for c in curve)
    check(dev <= 150 + 1e-6 and len(ctrl) > 20000 / 2500 + 1, f'S serre : {len(ctrl)} points de controle, ecart max {dev:.0f} po')
    r0 = ai_gen.generate_lanes(g, ref, n=3, randomness=0.0, seed=1)
    mid = r0['lanes'][1]
    dmid = min(math.dist(mid[len(mid) // 2][:2], s[:2]) for s in ai_gen.catmull_rom(ref, 100))
    check(dmid < 600, f'sans aleatoire, la voie du milieu suit la reference ({dmid:.0f} po au milieu)')
    # aucun noeud : toutes les sections, voies tres aleatoires, plusieurs graines ; segments voisins equilibres
    lanes = [l for p in rs['position_paths'] for seed in (1, 2) for l in
             ai_gen.generate_lanes(g, p['control_points'], n=6, randomness=1.0, margin=0.05, seed=seed)['lanes']]
    knots = sum(ai_gen.self_crossings(l) for l in lanes)
    ratio = max(max(a, b) / max(min(a, b), 1) for l in lanes
                for a, b in zip(*(lambda d: (d, d[1:]))([math.dist(p[:2], q[:2]) for p, q in zip(l, l[1:])])))
    check(knots == 0 and ratio < 4, f'{len(lanes)} voies tres aleatoires : {knots} noeud(s), rapport entre segments voisins {ratio:.1f}')
    print('tous les tests passent')


if __name__ == '__main__':
    main(sys.argv[1])
