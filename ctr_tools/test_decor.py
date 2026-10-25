"""Tests hors jeu du module decor (Crash Cove, Art_Core le plus recent).

Usage : python test_decor.py <dossier archives>
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pak_tool  # noqa: E402
from decor import DecorFile, model_logical_path, model_mesh  # noqa: E402
from igz import IgzFile  # noqa: E402

TRACK = 'T111_Crash_Cove'
ART = f'maps/Octane/{TRACK}/{TRACK}_Art_Core.igz'


def check(cond, msg):
    print(('OK   ' if cond else 'ECHEC') + ' ' + msg)
    if not cond:
        raise SystemExit(1)


def main(archives):
    data, src = pak_tool.read_latest(archives, ART, TRACK.lower() + '.pak')
    t = time.time()
    df = DecorFile(data)
    objs = df.objects()
    check(len(objs) == 703, f'{len(objs)} objets de decor dans Art_Core ({os.path.basename(src)}, {time.time() - t:.1f} s)')
    bridge = next(o for o in objs if o['name'] == 'Bridge01')
    check(abs(bridge['euler'][2] + 1.5708) < 1e-3, f'Bridge01 : {bridge["model"]}, rotation z {bridge["euler"][2]:.3f}')

    # deplacement + rotation + echelle
    df.set_transform(bridge['id'], pos=[bridge['pos'][0] + 1000, bridge['pos'][1], bridge['pos'][2]],
                     euler=[0, 0, 0.5], scale=[2, 2, 2])
    # duplication
    palm = next(o for o in objs if 'Palm' in o['model'])
    t = time.time()
    new = df.duplicate(palm['id'], df.unique_name(palm['name']), pos=[palm['pos'][0] + 500, palm['pos'][1], palm['pos'][2]])
    dt = time.time() - t
    # suppression
    victim = next(o for o in objs if o['name'] not in ('Bridge01', palm['name']) and o['has_transform'])
    df.delete(victim['id'])
    out = df.to_bytes()
    check(IgzFile(out).to_bytes() == out, f'fichier modifie stable (duplication en {dt:.1f} s)')

    re = DecorFile(out)
    o2 = {o['name']: o for o in re.objects()}
    b2 = o2['Bridge01']
    check(abs(b2['pos'][0] - bridge['pos'][0] - 1000) < 1e-2 and abs(b2['euler'][2] - 0.5) < 1e-5
          and all(abs(s - 2) < 1e-5 for s in b2['scale']), 'Bridge01 deplace, tourne, agrandi')
    copies = [n for n in o2 if n.startswith(palm['name'] + '_copie')]
    check(len(copies) == 1 and o2[copies[0]]['model'] == palm['model'], f'copie {copies} du modele {palm["model"]}')
    check(abs(o2[copies[0]]['pos'][0] - palm['pos'][0] - 500) < 1e-2, 'la copie est a sa nouvelle position')
    check(o2[palm['name']]['pos'] == palm['pos'], 'l\'original est intact')
    check(victim['name'] not in o2 and len(o2) == 703, f'{victim["name"]} supprime ; 703 objets (1 ajout, 1 retrait)')

    md, _ = pak_tool.read_latest(archives, model_logical_path(bridge['model']), TRACK.lower() + '.pak')
    pos, idx = model_mesh(md)
    check(len(idx) % 3 == 0 and max(idx) < len(pos) // 3, f'maillage du pont : {len(pos) // 3} sommets, {len(idx) // 3} triangles')
    print('tous les tests passent')


if __name__ == '__main__':
    main(sys.argv[1])
