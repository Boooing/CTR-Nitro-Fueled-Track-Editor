"""Test : murs invisibles le long d'une route en anneau (synthetique) et sur Crash Cove.

  * anneau de route de 20 m de large au-dessus du vide : murs des deux cotes, a la marge voulue du bord, aucun
    sur la route ;
  * meme anneau borde d'herbe au niveau de la route : aucun mur sans « hors route », des murs avec ;
  * meme anneau avec un muret deja la cote exterieur : pas de mur de ce cote ;
  * ribbon / segment_blocked : feuille verticale qui arrete un segment qui la traverse ;
  * Crash Cove : murs seulement au bord des vides, jamais sur la route du jeu.

Usage : python test_walls.py <dossier archives>
"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ai_gen  # noqa: E402
import pak_tool  # noqa: E402
import walls  # noqa: E402
from race_system import RaceSystem  # noqa: E402

T, TP = 'T111_Crash_Cove', 't111_crash_cove.pak'
R, HALF = 4000.0, 400.0                     # anneau : rayon 100 m, route de 20 m


def check(cond, msg):
    print(('OK   ' if cond else 'ECHEC') + ' ' + msg)
    if not cond:
        raise SystemExit(1)


def ring(r_in, r_out, z, n=96):
    """Triangles d'un anneau horizontal (n, 3, 3)."""
    tris = []
    for k in range(n):
        a, b = 2 * math.pi * k / n, 2 * math.pi * (k + 1) / n
        p = [(r_in * math.cos(a), r_in * math.sin(a), z), (r_out * math.cos(a), r_out * math.sin(a), z),
             (r_out * math.cos(b), r_out * math.sin(b), z), (r_in * math.cos(b), r_in * math.sin(b), z)]
        tris += [(p[0], p[1], p[2]), (p[0], p[2], p[3])]
    return tris


def cylinder(r, z0, z1, n=96):
    tris = []
    for k in range(n):
        a, b = 2 * math.pi * k / n, 2 * math.pi * (k + 1) / n
        p = [(r * math.cos(a), r * math.sin(a), z0), (r * math.cos(b), r * math.sin(b), z0),
             (r * math.cos(b), r * math.sin(b), z1), (r * math.cos(a), r * math.sin(a), z1)]
        tris += [(p[0], p[1], p[2]), (p[0], p[2], p[3])]
    return tris


def radii(pieces):
    return np.array([math.hypot(p[0], p[1]) for pc in pieces for p in pc['points']])


def main(archives):
    loop = [[R * math.cos(a), R * math.sin(a), 100.0] for a in np.linspace(0, 2 * math.pi, 40, endpoint=False)]
    road = ring(R - HALF, R + HALF, 0.0)
    margin = 120.0

    g = ai_gen.GroundQuery(road, [38] * len(road))
    pcs = walls.generate(g, loop, margin=margin)
    r = radii(pcs)
    inner, outer = r[r < R], r[r > R]
    check(len(inner) and len(outer), f'route au-dessus du vide : murs des deux cotes ({len(pcs)} morceaux)')
    want_in, want_out = R - HALF - margin, R + HALF + margin
    check(np.abs(inner - want_in).max() < 80 and np.abs(outer - want_out).max() < 80,
          f'a ~{margin / 39.37:.0f} m du bord (interieur {inner.min():.0f}..{inner.max():.0f}, voulu {want_in:.0f} ; '
          f'exterieur {outer.min():.0f}..{outer.max():.0f}, voulu {want_out:.0f})')
    check(all(p['reason'] == 'void' for p in pcs), 'raison : vide')
    lens = [sum(math.dist(a[:2], b[:2]) for a, b in zip(pc['points'], pc['points'][1:])) for pc in pcs]
    check(max(lens) < walls.PIECE + 2 * walls.SAMPLE, f'morceaux de {min(lens) / 39.37:.0f} a {max(lens) / 39.37:.0f} m')
    total = sum(lens)
    check(total > 0.9 * 2 * math.pi * (want_in + want_out), f'tour complet ferme : {total / 39.37:.0f} m de murs')

    grass = ring(R - HALF - 2000, R - HALF, 0.0) + ring(R + HALF, R + HALF + 2000, 0.0)
    g2 = ai_gen.GroundQuery(road + grass, [38] * len(road) + [5] * len(grass))
    check(not walls.generate(g2, loop, margin=margin), 'bordee d\'herbe au niveau de la route : aucun mur par defaut')
    check(len(walls.generate(g2, loop, margin=margin, offroad=True)) > 4, 'herbe + « hors route » : murs')

    curb = cylinder(R + HALF + 60, -50.0, 150.0)
    g3 = ai_gen.GroundQuery(road + curb, [38] * len(road) + [4] * len(curb))
    r3 = radii(walls.generate(g3, loop, margin=margin))
    check(len(r3) and (r3 < R).all(), 'muret deja la a l\'exterieur : murs a l\'interieur seulement')

    # --- murs autour d'objets choisis ---
    cor = walls.Corridor(g, loop)
    half = [t for k, t in enumerate(road) if k < len(road) // 2]           # moitie de l'anneau (y >= 0)
    zp = walls.zone(g, half, cor, margin=40)
    pts = np.array([p for pc in zp for p in pc['points']])
    rr = np.hypot(pts[:, 0], pts[:, 1])
    check(len(zp) and ((rr < R - HALF) | (rr > R + HALF)).all(),
          f'moitie de la route choisie : {len(zp)} morceaux le long des bords, aucun en travers de la route')
    check((pts[:, 1] > -100).all(), 'rien sur la moitie non choisie')

    def square(x0, y0, s, z=0.0):
        p = [(x0, y0, z), (x0 + s, y0, z), (x0 + s, y0 + s, z), (x0, y0 + s, z)]
        return [(p[0], p[1], p[2]), (p[0], p[2], p[3])]
    plat = square(-600, -600, 1200)                                       # plateforme 30 m au centre, sur le vide
    gp = ai_gen.GroundQuery(road + plat, [38] * (len(road) + len(plat)))
    zq = walls.zone(gp, plat, walls.Corridor(gp, loop), margin=40)
    per = sum(math.dist(a[:2], b[:2]) for pc in zq for a, b in zip(pc['points'], pc['points'][1:]))
    check(abs(per - 4 * 1280) < 200, f'plateforme seule : mur tout autour ({per / 39.37:.0f} m, attendu ~{4 * 1280 / 39.37:.0f})')
    two = square(-600, -600, 600) + square(0, -600, 600)                  # deux objets cote a cote
    zt = walls.zone(ai_gen.GroundQuery(road + two, [38] * (len(road) + len(two))), two, None, margin=40)
    per2 = sum(math.dist(a[:2], b[:2]) for pc in zt for a, b in zip(pc['points'], pc['points'][1:]))
    check(abs(per2 - 2 * (1280 + 680)) < 200, f'deux objets voisins : pas de mur au raccord ({per2 / 39.37:.0f} m de tour)')
    def over_road(zb):                       # plateforme de 30 m en travers de la route (angle 0), a zb
        b = square(R - 600, -600, 1200, zb)
        pcs_ = walls.zone(ai_gen.GroundQuery(road + b, [38] * (len(road) + len(b))), b, cor, margin=40, height=400)
        # segments de mur qui passent au-dessus de la chaussee (R - HALF < x < R + HALF)
        return [(a, b) for pc in pcs_ for a, b in zip(pc['points'], pc['points'][1:])
                if min(a[0], b[0]) < R + HALF and max(a[0], b[0]) > R - HALF]
    check(not len(over_road(250)), 'plateforme 6 m au-dessus de la route : aucun mur qui descendrait sur la route')
    check(len(over_road(1500)), 'plateforme 38 m au-dessus : ses bords ont leurs murs')

    # barriere : poteaux (dessus de 1 m) tous les ~50 m, panneaux verticaux sans sommet commun entre eux
    RB, posts, panels = 7000.0, [], []
    angs = np.linspace(0.3, 1.5, 8)
    for a in angs:
        c = (RB * math.cos(a), RB * math.sin(a))
        p = [(c[0] - 20, c[1] - 20, 200.0), (c[0] + 20, c[1] - 20, 200.0), (c[0] + 20, c[1] + 20, 200.0), (c[0] - 20, c[1] + 20, 200.0)]
        posts += [(p[0], p[1], p[2]), (p[0], p[2], p[3])]
    for a, b in zip(angs, angs[1:]):
        for k in range(4):                     # panneau courbe en 4 quads, decolle des poteaux de 30 po
            u, v = a + (b - a) * k / 4 + (0.005 if k == 0 else 0), a + (b - a) * (k + 1) / 4 - (0.005 if k == 3 else 0)
            q = [(RB * math.cos(u), RB * math.sin(u), 0.0), (RB * math.cos(v), RB * math.sin(v), 0.0),
                 (RB * math.cos(v), RB * math.sin(v), 150.0), (RB * math.cos(u), RB * math.sin(u), 150.0)]
            panels += [(q[0], q[1], q[2]), (q[0], q[2], q[3])]
    bar = posts + panels
    gb = ai_gen.GroundQuery(road + bar, [38] * len(road) + [4] * len(bar))
    sep = walls.zone(gb, bar, cor, margin=40)
    joined = walls.zone(gb, bar, cor, margin=40, join=3000.0)
    arc = RB * (angs[-1] - angs[0])
    jl = sum(math.dist(a[:2], b[:2]) for pc in joined for a, b in zip(pc['points'], pc['points'][1:]))
    rj = radii(joined)
    check(len(sep) == len(angs) and jl > 0.95 * arc and np.abs(rj - RB).max() < 150,
          f'barriere : {len(sep)} bouts separes -> relies le long de la barriere ({jl / 39.37:.0f} m pour {arc / 39.37:.0f} m, '
          f'ecart au rayon {np.abs(rj - RB).max():.0f} po)')

    # route coupee (saut de 30 m) choisie : jamais de mur en travers de la route aux bouts du trou
    gap = [t for t in road if not all(abs(math.atan2(p[1], p[0])) < 0.15 for p in t)]
    gg = ai_gen.GroundQuery(gap, [38] * len(gap))
    cg = walls.Corridor(gg, loop)
    zg = walls.zone(gg, gap, cg, margin=40, join=3000.0)
    def crosses(a, b, c, d):
        f = lambda p, q, r: (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return f(a, b, c) * f(a, b, d) < 0 and f(c, d, a) * f(c, d, b) < 0
    L = loop + [loop[0]]
    n_cross = sum(crosses(a, b, c, d) for pc in zg for a, b in zip(pc['points'], pc['points'][1:]) for c, d in zip(L, L[1:]))
    check(len(zg) and not n_cross, f'route coupee par un saut : {len(zg)} morceaux, aucun en travers du trace')
    ends_ = [p for pc in zg for p in pc['points']
             if abs(abs(math.atan2(p[1], p[0])) - 0.15) * R < 200 and R - HALF + 60 < math.hypot(p[0], p[1]) < R + HALF - 60]
    check(not ends_, f'aucun mur sur les bouts de route au bord du saut ({len(ends_)} point(s))')

    pos, tris = walls.ribbon([[0, 0, 0], [1000, 0, 0], [2000, 300, 50]], 400)
    W = np.array([[pos[i] for i in t] for t in tris])
    gw = ai_gen.GroundQuery(W, [4] * len(W))
    check(len(pos) == 6 and len(tris) == 4 and W[..., 2].min() == -walls.SINK and W[..., 2].max() == 450,
          'ribbon : feuille de 2 segments, de -SINK a la hauteur voulue')
    check(walls.segment_blocked(gw, [500, -100, 60], [500, 100, 60]) and not walls.segment_blocked(gw, [500, -100, 60], [500, -10, 60])
          and not walls.segment_blocked(gw, [500, -100, 500], [500, 100, 500]), 'segment_blocked : traverse / avant / au-dessus')

    hk = pak_tool.read_latest(archives, f'models/maps/Octane/{T}/StaticCollision_{T}.hkx', TP)[0]
    gc = ai_gen.GroundQuery.from_hkx(hk)
    rs = RaceSystem(pak_tool.read_latest(archives, f'maps/Octane/{T}/{T}_RaceSystem.igz', TP)[0], file_ns=f'{T}_RaceSystem').decode()
    pts = [p for s in rs['position_paths'] for p in s['control_points']]
    pc = walls.generate(gc, pts, margin=margin)
    check(0 < len(pc) < 60, f'Crash Cove : {len(pc)} morceau(x) au bord des vides')
    on_road = sum(1 for p in pc for q in p['points']
                  if (lambda h: h is not None and h[1] in (38, 13) and abs(h[0] - q[2]) < 40)(gc.at(q[0], q[1], q[2], window=60.0)))
    n_pts = sum(len(p['points']) for p in pc)
    check(on_road <= 0.05 * n_pts, f'Crash Cove : {on_road} / {n_pts} points de mur sur le sable ou le bois au niveau de la route')


if __name__ == '__main__':
    main(sys.argv[1])
