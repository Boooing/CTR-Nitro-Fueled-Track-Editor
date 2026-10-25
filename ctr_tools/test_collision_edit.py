"""Tests hors jeu : deplacement de la collision de Bridge04 (Crash Cove).

Usage : python test_collision_edit.py <dossier archives>
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pak_tool  # noqa: E402
from collision import decode_compressed_mesh, transform  # noqa: E402
from collision_edit import CollisionFile  # noqa: E402
from decor import DecorFile  # noqa: E402
from havok import Packfile  # noqa: E402

TRACK = 'T111_Crash_Cove'
HKX = f'models/maps/Octane/{TRACK}/StaticCollision_{TRACK}.hkx'
ART = f'maps/Octane/{TRACK}/{TRACK}_Art_Core.igz'


def check(cond, msg):
    print(('OK   ' if cond else 'ECHEC') + ' ' + msg)
    if not cond:
        raise SystemExit(1)


def main(archives):
    hk, _ = pak_tool.read_latest(archives, HKX, TRACK.lower() + '.pak')
    art, _ = pak_tool.read_latest(archives, ART, TRACK.lower() + '.pak')
    bridge = next(o for o in DecorFile(art).objects() if o['name'] == 'Bridge04')
    cf = CollisionFile(hk)
    i = cf.find(bridge['pos'])
    check(i is not None, f'instance de collision de Bridge04 : {i} ({cf.instances()[i]["kind"]})')

    # reproduire la transformation d'origine doit redonner (presque) la meme matrice
    pf0 = Packfile(hk)
    m0 = pf0.floats(cf.inst_off + i * 128, 16)
    cf.set_instance(i, bridge['pos'], bridge['euler'], bridge['scale'])
    m1 = cf._floats(cf.inst_off + i * 128, 16)
    check(max(abs(a - b) for a, b in zip(m0, m1)) < 1e-3, 'matrice recalculee depuis le decor = matrice d\'origine')

    # deplacement +57 m en hauteur, verifie sur le maillage reel
    new_pos = [bridge['pos'][0], bridge['pos'][1], bridge['pos'][2] + 2236]
    cf.set_instance(i, new_pos, bridge['euler'], bridge['scale'])
    cf.neutralize_tree()
    out = cf.to_bytes()
    pf = Packfile(out)
    b = pf.array(next(o for o, c in pf.objects.items() if c == 'hknpStaticCompoundShape') + 0x60)[0] + i * 128
    verts, _ = decode_compressed_mesh(pf, pf.ptr(pf.ptr(b + 0x50) + 0x58))
    old_z = [transform(m0, pf0.floats(b + 0x40, 3), v)[2] for v in verts]
    new_z = [transform(pf.floats(b, 16), pf.floats(b + 0x40, 3), v)[2] for v in verts]
    dz = (sum(new_z) / len(new_z) - sum(old_z) / len(old_z)) * 39.37
    check(abs(dz - 2236) < 1, f'collision du pont deplacee de {dz:.0f} po en Z')
    d = next(o for o, c in pf.objects.items() if c == 'hknpStaticCompoundShapeData')
    hi = pf.floats(d + 0x30, 3)
    check(max(new_z) <= hi[2] + 1e-3, f'domaine de l\'arbre agrandi (z max {hi[2]:.1f} m >= {max(new_z):.1f} m)')
    no, nn = pf.array(d + 0x10)
    check(all(pf.data[no + k * 6:no + k * 6 + 3] == b'\0\0\0' for k in range(nn)), f'{nn} noeuds neutralises')
    check(len(out) == len(hk), 'taille du fichier inchangee (modification en place)')
    print('tous les tests passent')


if __name__ == '__main__':
    main(sys.argv[1])
