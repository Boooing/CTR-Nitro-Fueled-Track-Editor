"""Decoupe de la carte loin de la route (trim_m) : elle contourne les objets semes et l'eau (2026-11-14).

python ctr_tools/test_creator_trim.py
"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import track_creator as tc

IN = tc.INCH
ok = True


def check(c, msg):
    global ok
    print(('OK   ' if c else 'ECHEC ') + msg)
    ok &= bool(c)


def terrain(n=121, cell=20.0, trim=None, hollow=None):
    """Terrain plat de n x n sommets (cell m), centre en 0 ; hollow = (x, y, rayon, profondeur) m : creux."""
    x0 = -(n - 1) * cell / 2
    h = np.zeros((n, n))
    if hollow:
        hx, hy, r, d = hollow
        g = x0 + np.arange(n) * cell
        X, Y = np.meshgrid(g, g)
        h -= d * np.clip(1 - np.hypot(X - hx, Y - hy) / r, 0, 1)
    t = {'x0': x0 * IN, 'y0': x0 * IN, 'cell': cell * IN, 'n': n, 'h': (h * IN).ravel().tolist(),
         'paint': [0] * (n * n), 'full': True}
    if trim:
        t['trim_m'] = trim
    return t


# boucle de 300 m de rayon au centre d'un terrain de 2,4 km : les coins sont loin de la route
pts = [[300 * math.cos(a) * IN, 300 * math.sin(a) * IN, 0.0, 14 * IN] for a in np.linspace(0, 2 * math.pi, 240, endpoint=False)]
prop = (900.0, 900.0, 6.0)                      # objet a ~970 m du centre (coin), rayon 6 m
water = {'x': -900 * IN, 'y': 900 * IN, 'dz': -5 * IN, 'type': 'clear'}
T = terrain(trim=300, hollow=(-900, 900, 150, 20))

import time
t0 = time.time()
_, _, a = tc.build(pts, True, 0.0, 'sable', T, 'none', [water], {})
obj_b, _, b = tc.build(pts, True, 0.0, 'sable', terrain(trim=300, hollow=(-900, 900, 150, 20)), 'none', [water], {}, keep=[prop])
dt = time.time() - t0
xs, ys, _, hole_a = a['_ground'][:4]
hole_b = b['_ground'][3]


def cell_at(x, y):
    return int(np.searchsorted(ys, y) - 1), int(np.searchsorted(xs, x) - 1)


check(a['trimmed_pct'] > 30, f"decoupe active ({a['trimmed_pct']} % retires)")
check(not hole_a[cell_at(-900, 900)], "eau loin de la route : sol garde sous l'eau (sans objet a garder)")
check(a['waters'] == 1 and b['waters'] == 1, 'eau generee dans les deux cas')
check(hole_a[cell_at(900, 900)], 'sans keep : sol retire sous un objet loin de la route')
check(not hole_b[cell_at(900, 900)], 'avec keep : sol garde sous l\'objet')
check(not hole_b[cell_at(900 + 6 + 3, 900)], 'avec keep : marge autour de l\'objet gardee')
# objet a ~970 m du centre, route a 300 m : bande de sol jusqu'a la carte principale (plus d'ilot)
mid = 300 + (970 - 300) / 2
check(not hole_b[cell_at(mid / math.sqrt(2), mid / math.sqrt(2))], 'avec keep : sol garde entre l\'objet et la carte principale')
check(not hole_a[cell_at(-600 / math.sqrt(2) * 1.2, 600 / math.sqrt(2) * 1.2)], "eau : sol garde entre l'eau et la carte principale")
check(hole_b[cell_at(900 + 200, 900 - 200)], 'avec keep : sur le cote de la bande, sol retire (pas tout garde)')
check(hole_b[cell_at(-900, -900)], 'coin sans objet ni eau : sol retire')
check(b['trimmed_pct'] < a['trimmed_pct'] and b['trimmed_pct'] > a['trimmed_pct'] - 10, f"retrait un peu moindre ({a['trimmed_pct']} -> {b['trimmed_pct']} %)")
# bord lisse : des faces du sol passent par des points interpoles (hors de la grille de 20 m), pas que des cases entieres
vx = [l.split()[1:3] for l in obj_b.splitlines() if l.startswith('v ')]
off = sum(1 for x, y in vx if abs(float(x) / 20 - round(float(x) / 20)) > 0.02 or abs(float(y) / 20 - round(float(y) / 20)) > 0.02)
check(off > 50, f'bord de decoupe interpole (non en escalier) : {off} sommets hors grille')
check(dt < 60, f'deux generations en {dt:.1f} s')
print('TOUT OK' if ok else 'DES ECHECS')
sys.exit(0 if ok else 1)
