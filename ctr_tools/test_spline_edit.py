"""Tests de l'edition structurelle IGZ sur un _RaceSystem.igz.

Usage : python test_spline_edit.py <..._RaceSystem.igz>
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from igz import IgzFile  # noqa: E402
from race_system import RaceSystem  # noqa: E402
from spline_edit import SplineEditor, catmull_rom_length  # noqa: E402


def check(cond, msg):
    print(('OK   ' if cond else 'ECHEC') + ' ' + msg)
    if not cond:
        raise SystemExit(1)


def main(path):
    ent = 'AI_Spline_01'
    ed = SplineEditor(path)
    pts = ed.points(ent)
    n0, len0 = len(pts), ed.length(ent)
    check(abs(catmull_rom_length(pts) - len0) / len0 < 0.002, f'longueur recalculee ~ stockee ({len0:.0f})')

    # 1) insertion d'un point au milieu du segment 5-6, decale de 600 unites lateralement
    mid = [(pts[5][i] + pts[6][i]) / 2 for i in range(3)]
    mid[0] += 600
    ed.insert_point(ent, 6, mid)
    data = ed.to_bytes()

    re = SplineEditor(data)
    p2 = re.points(ent)
    check(len(p2) == n0 + 1, f'{n0} -> {len(p2)} points apres insertion')
    check(all(abs(p2[6][i] - mid[i]) < 1e-2 for i in range(3)), 'le nouveau point est a la bonne position')
    check(p2[:6] == pts[:6] and p2[7:] == pts[6:], 'les autres points sont inchanges')
    check(abs(re.length(ent) - catmull_rom_length(p2)) < 1, f'_length mis a jour ({len0:.0f} -> {re.length(ent):.0f})')
    check(IgzFile(data).to_bytes() == data, 'le fichier modifie se relit et se reecrit a l\'identique')
    names = [n for n, _ in IgzFile(data).root_objects()]
    check(any(n.endswith('_spline_data_12') for n in names if n), 'le nouveau point est nomme dans la liste racine')

    # 2) les autres splines et le systeme de course se decodent toujours
    # meme nom de fichier : il sert d'espace de noms aux handles internes
    with tempfile.TemporaryDirectory() as d:
        tmp = os.path.join(d, os.path.basename(path))
        open(tmp, 'wb').write(data)
        res = RaceSystem(tmp).decode()
        check(len(res['ai_paths']) == 21 and len(res['position_paths']) == 4 and len(res['transitions']) == 4,
              'race_system decode toujours tout')

    # 3) suppression
    re.remove_point(ent, 6)
    p3 = SplineEditor(re.to_bytes()).points(ent)
    check(p3 == pts, 'suppression : retour aux points d\'origine')

    # 4) deplacement
    ed2 = SplineEditor(path)
    target = [pts[3][0], pts[3][1] + 250, pts[3][2]]
    ed2.move_point(ent, 3, target)
    p4 = SplineEditor(ed2.to_bytes()).points(ent)
    check(all(abs(p4[3][i] - target[i]) < 1e-2 for i in range(3)), 'deplacement d\'un point')
    print('tous les tests passent')


if __name__ == '__main__':
    main(sys.argv[1])
