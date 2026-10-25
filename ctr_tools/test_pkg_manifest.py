"""Test : ajout d'entrees au manifeste de streaming d'une piste (lecture seule des archives).

Usage : python test_pkg_manifest.py <dossier archives> [Piste]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pak_tool  # noqa: E402
import pkg_manifest as pm  # noqa: E402


def check(cond, msg):
    print(('OK   ' if cond else 'ECHEC') + ' ' + msg)
    if not cond:
        raise SystemExit(1)


def main(archives, track='T111_Crash_Cove'):
    data, _ = pak_tool.read_latest(archives, pm.manifest_logical(track), f'{track.lower()}.pak')
    rows = pm.entries(data)
    check(any(t == 'model' for t, _ in rows), f'{len(rows)} entrees dont {sum(t == "model" for t, _ in rows)} modeles')
    existing = next(p for t, p in rows if t == 'model')
    new = [('model', 'models/Levels/Octane/Custom/MonModele.igz'), ('model', existing)]
    out, added = pm.add_entries(data, new)
    check(added == [('model', 'models/levels/octane/custom/monmodele.igz')], 'seul le modele absent est ajoute (minuscules)')
    rows2 = pm.entries(out)
    check(len(rows2) == len(rows) + 1 and [r for r in rows2 if r != added[0]] == rows, 'entrees d\'origine intactes et dans l\'ordre')
    i = rows2.index(added[0])
    check(rows2[i - 1][0] == 'model' and (i + 1 == len(rows2) or rows2[i + 1][0] != 'model'), 'inseree apres le dernier modele')
    check(pm.add_entries(out, new)[1] == [], 'second ajout : rien (deja liste)')
    print('tous les tests passent')


if __name__ == '__main__':
    main(*sys.argv[1:])
