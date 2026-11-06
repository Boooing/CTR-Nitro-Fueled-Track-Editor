"""Terrain jamais au-dessus de la route, meme dans un virage releve : anneau de 400 m, bord releve de 5 m sur un quart.
    python ctr_tools/test_creator_clear.py [creation.json]
Avec un fichier <piste>_creator.json : mesure sur cette creation."""
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import track_creator as tc  # noqa: E402

IN = 39.37


def ring():
    pts, n, r = [], 160, 200 * IN
    for k in range(n):
        a = 2 * math.pi * k / n
        raised = 5 * IN * (0.45 if k in (60, 72) else 1.0 if 60 < k < 72 else 0.0)      # releve brusque, comme a la main
        pts.append([r * math.cos(a), r * math.sin(a), 0.0, 40 * IN, 0, 20 * IN, 20 * IN, 0.0, raised])
    n = 201
    t = {'x0': -400 * IN, 'y0': -400 * IN, 'cell': 8 * IN, 'n': n, 'size': 1600, 'full': True, 'h': [0.0] * (n * n), 'paint': [0] * (n * n)}
    return pts, True, 0.0, 'sable', t


def measure(points, closed, gz, kit, terrain, barriers='none'):
    C = tc.centerline(points, closed)
    xs, ys, H, _, _ = tc._terrain_grid(terrain, C, gz / IN)
    T, L = tc._frames(C, closed)
    half, road_z = C[:, 3:4] / 2, C[:, 2] + tc.ROAD_LIFT
    left = tc._unfold(np.hstack([C[:, :2] + L * half, (road_z + C[:, 5])[:, None]]), T)
    right = tc._unfold(np.hstack([C[:, :2] - L * half, (road_z - C[:, 5])[:, None]]), T)
    rows = list(range(len(C))) + ([0] if closed else [])
    gap = C[:, 4] > 0.5
    H0 = tc._conform(xs, ys, H, C, closed, left, right)
    H1, first = tc._clear_road(xs, ys, H0, left, right, rows, gap)
    S = tc._road_samples(left, right, rows, gap)
    S = S[(S[:, 0] >= xs[0]) & (S[:, 0] <= xs[-1]) & (S[:, 1] >= ys[0]) & (S[:, 1] <= ys[-1])]
    a = tc._mesh_heights(xs, ys, H0, S)[4] - S[:, 2]
    b = tc._mesh_heights(xs, ys, H1, S)[4] - S[:, 2]
    moved = np.abs(H1 - H0)
    print(f'points de route controles : {len(S)}')
    print(f'avant : {np.count_nonzero(a > 0)} points recouverts, jusqu\'a {a.max():.2f} m au-dessus')
    print(f'apres : {np.count_nonzero(b > 0)} points recouverts, ecart maximal {b.max():.2f} m')
    print(f'sommets abaisses : {np.count_nonzero(moved > 1e-6)} sur {moved.size}, de {moved.max():.2f} m au plus')
    # ecart entre le bord de la route et le sol juste a cote (espacement visible)
    side = []
    for e, sgn in ((left, 1), (right, -1)):
        Q = np.column_stack([e[:, :2] + sgn * L * 0.5, e[:, 2]])[~gap]
        Q = Q[(Q[:, 0] >= xs[0]) & (Q[:, 0] <= xs[-1]) & (Q[:, 1] >= ys[0]) & (Q[:, 1] <= ys[-1])]
        side.append(tc._mesh_heights(xs, ys, H1, Q)[4] - Q[:, 2])
    side = np.concatenate(side)
    print(f'sol a 0,5 m du bord / bord : median {np.median(side):.2f} m, de {side.min():.2f} a {side.max():.2f} m, sous 2 m d\'ecart {np.mean(np.abs(side) < 2) * 100:.1f} %')
    return a, b


if __name__ == '__main__':
    if len(sys.argv) > 1:
        d = json.load(open(sys.argv[1], encoding='utf-8'))
        measure(d['points'], bool(d.get('closed')), d.get('ground_z') or 0.0, d.get('kit') or 'sable', d.get('terrain'))
    else:
        a, b = measure(*ring())
        assert b.max() <= 0, 'terrain encore au-dessus de la route'
        print('ok')
