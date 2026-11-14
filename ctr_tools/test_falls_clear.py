"""Zones de chute sous une route en hauteur (2026-11-14) : jamais a hauteur de kart (sol ou route du dessous).

python ctr_tools/test_falls_clear.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ai_gen  # noqa: E402
import falls  # noqa: E402

M = falls.M
ok = True


def check(c, msg):
    global ok
    print(('OK   ' if c else 'ECHEC ') + msg)
    ok &= bool(c)


def rect(x0, y0, x1, y1, z):
    a, b, c, d = (x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)
    return [[a, b, c], [a, c, d]]


def scene(h_bridge, void=False):
    """Sol plat a 0 (void : pas de sol, sauf la route du dessous), route du dessous (axe y, 20 m de large) au sol,
    route en hauteur (axe x, 14 m de large) a h_bridge."""
    ground_tris = [] if void else rect(-400 * M, -400 * M, 400 * M, 400 * M, 0.0)
    low = rect(-10 * M, -400 * M, 10 * M, 400 * M, 0.0)
    high = rect(-300 * M, -7 * M, 300 * M, 7 * M, h_bridge * M)
    ground = ai_gen.GroundQuery(np.array(ground_tris + low + high), [0] * (len(ground_tris) + len(low) + len(high)))
    road = ai_gen.GroundQuery(np.array(low + high), [0] * (len(low) + len(high)))
    path = np.array([[x * M, 0.0, h_bridge * M] for x in np.arange(-280, 281, 2.0)])
    return path, ground, road


def kart_level(zones, z0, z1):
    """Une zone touche-t-elle la tranche z0..z1 (pouces) ?"""
    return [z for z in zones if z['center'][2] - z['dims'][2] / 2 < z1 and z['center'][2] + z['dims'][2] / 2 > z0]


for hb in (8.0, 15.0, 30.0):                     # sol sous le pont : le kart qui tombe y atterrit
    P, g, r = scene(hb)
    zones = falls.find_fall_zones(P, g, r, killz=-200 * M)
    check(not zones, f'route a {hb:.0f} m au-dessus du sol : pas de zone de chute ({len(zones)})')

P, g, r = scene(15.0, void=True)                  # pas de sol : vraie chute
zones = falls.find_fall_zones(P, g, r, killz=-200 * M)
check(zones, f'route au-dessus du vide : des zones de chute ({len(zones)})')
over_low = [z for z in zones if abs(z['center'][0]) - z['dims'][0] / 2 < 10 * M and z['center'][2] - z['dims'][2] / 2 < falls.KART_CLEAR]
check(not over_low, 'au-dessus du vide : rien sur la route du dessous')
print('TOUT OK' if ok else 'DES ECHECS')
sys.exit(0 if ok else 1)
