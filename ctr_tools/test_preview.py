"""Test : apercu texture (geometrie + UV + texture par draw call, textures decodees).

Usage : python test_preview.py <dossier archives>
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pak_tool  # noqa: E402
import preview  # noqa: E402
from decor import model_mesh  # noqa: E402

TP = 't111_crash_cove.pak'
BRIDGE = 'models/Levels/Octane/T111_Crash_Cove/T111_Woodbridge01.igz'
DECAL = 'models/Levels/Octane/T111_Crash_Cove/T111_Crash_Cove_Ground_Decal_04.igz'


def check(cond, msg):
    print(('OK   ' if cond else 'ECHEC') + ' ' + msg)
    if not cond:
        raise SystemExit(1)


def main(archives):
    def read(logical):
        try:
            return pak_tool.read_latest(archives, logical, TP)[0]
        except KeyError:
            return None
    data = read(BRIDGE)
    pv = preview.model_preview(data, read)
    pos, idx = model_mesh(data)
    check(len(pv['positions']) * 3 == len(pos) and list(pv['indices']) == list(idx),
          f"pont : meme geometrie que model_mesh ({len(pv['positions'])} sommets, {len(pv['indices']) // 3} triangles)")
    check(sum(n for _, n, _ in pv['groups']) == len(pv['indices']) and all(g[2] for g in pv['groups']),
          f"{len(pv['groups'])} parties, toutes avec une texture couleur")
    texs = {g[2][0] for g in pv['groups']}
    check(any('WoodBridge' in t for t in texs) and any('Grass' in t for t in texs),
          'chaque materiau du fichier a sa propre texture (bois du pont, herbe des decals)')
    uv = pv['uvs']
    check(np.isfinite(uv).all() and 0 < np.abs(uv).max() < 100, 'UV lus (half2), valeurs plausibles')
    decal = preview.model_preview(read(DECAL), read)
    check(all(g[2][1] for g in decal['groups']), 'decal de sol : materiaux reconnus comme decals (GBufferDecal)')
    for ns in sorted(texs):
        rgba, _ = preview.decode_texture(read(f'textures/{ns}.igz'), 256)
        check(rgba.shape[2] == 4 and max(rgba.shape[:2]) <= 256
              and np.abs(np.diff(rgba[..., :3].astype(np.float32), axis=1)).mean() < 25,
              f"texture {ns.split('!')[-1][:32]} decodee {rgba.shape[1]}x{rgba.shape[0]}, image coherente")
    print('tous les tests passent')


if __name__ == '__main__':
    main(sys.argv[1])
