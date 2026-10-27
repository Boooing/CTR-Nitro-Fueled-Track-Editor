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

    # route droite synthetique (120 m x 24 m) : rocher pose dessus (la route continue dessous), trou de 25 m, tremplin
    def quad(x0, x1, y0, y1, z0=0.0, z1=None):
        z1 = z0 if z1 is None else z1
        p = [(x0, y0, z0), (x1, y0, z1), (x1, y1, z1), (x0, y1, z0)]
        return [(p[0], p[1], p[2]), (p[0], p[2], p[3])]
    road = quad(0, 2000, -480, 480) + quad(3000, 6000, -480, 480)          # trou de x = 2000 a 3000
    rock = []
    cx, cy, rr, hh = 4500.0, 150.0, 200.0, 300.0                           # rocher : prisme a 8 pans, 5 m, 7,6 m de haut
    ring = [(cx + rr * math.cos(a), cy + rr * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 9)[:-1]]
    for (ax, ay), (bx, by) in zip(ring, ring[1:] + ring[:1]):
        rock += [((ax, ay, 0.0), (bx, by, 0.0), (bx, by, hh)), ((ax, ay, 0.0), (bx, by, hh), (ax, ay, hh))]
        rock += [((cx, cy, hh), (ax, ay, hh), (bx, by, hh))]
    ramp = quad(1200, 1800, -200, 200, 0.0, 120.0)                         # tremplin : on y monte en pente douce
    gs = ai_gen.GroundQuery(road + rock + ramp, [38] * len(road) + [6] * len(rock) + [38] * len(ramp))
    ref2 = [[x, 0.0, 0.0] for x in np.arange(0, 6001, 1000)]
    rs2 = ai_gen.generate_lanes(gs, ref2, n=5, randomness=0.0, seed=1, keep_air=True)
    obs = ai_gen.Obstacles(gs)
    cross = sum(obs.crosses(a, b) for l in rs2['lanes'] for a, b in (lambda c: zip(c, c[1:]))(ai_gen.curve_uniform(l, 16)[0]))
    inside = sum(1 for l in rs2['lanes'] for c in ai_gen.curve_uniform(l, 16)[0] if math.hypot(c[0] - cx, c[1] - cy) < rr)
    check(cross == 0 and inside == 0, f'rocher pose sur la route : {cross} traversee(s), {inside} point(s) de voie dedans')
    ys = [np.interp(2500, [p[0] for p in l], [p[1] for p in l]) for l in rs2['lanes']]
    check(max(ys) - min(ys) > 400, f'au-dessus du trou : voies ecartees de {(max(ys) - min(ys)) / 39.37:.0f} m (pas resserrees en un point)')
    yr = [np.interp(1500, [p[0] for p in l], [p[1] for p in l]) for l in rs2['lanes']]
    check(any(abs(y) < 150 for y in yr), 'tremplin : pas un obstacle (une voie passe dessus)')
    print('tous les tests passent')


if __name__ == '__main__':
    main(sys.argv[1])
