"""Test : OBJ (rampe) -> modele .igz depuis le gabarit -> relecture.

Usage : python test_model_build.py <dossier archives> [sortie.igz]
"""
import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pak_tool  # noqa: E402
from decor import model_mesh  # noqa: E402
from igz import IgzFile  # noqa: E402
from model_build import TEMPLATE, build_model, complete_mesh, model_materials, parse_obj, parse_obj_groups  # noqa: E402

# rampe 8 m x 4 m montant a 2 m (Blender, metres, Y vers le haut), faces orientees vers l'exterieur
RAMP_OBJ = """
# rampe
v 0 0 0
v 4 0 0
v 4 0 -8
v 0 0 -8
v 0 2 -8
v 4 2 -8
f 1 2 6 5
f 4 3 2 1
f 3 4 5 6
f 1 5 4
f 2 3 6
"""


def check(cond, msg):
    print(('OK   ' if cond else 'ECHEC') + ' ' + msg)
    if not cond:
        raise SystemExit(1)


def main(archives, out=None):
    template, _ = pak_tool.read_latest(archives, TEMPLATE, 't111_crash_cove.pak')
    pos, nrm, uvs, tris = parse_obj(RAMP_OBJ)
    check(len(pos) == 6 and len(tris) == 8, f'OBJ lu : {len(pos)} sommets, {len(tris)} triangles')
    check(max(p[2] for p in pos) == 2 * 39.37 and min(p[1] for p in pos) == 0 and max(p[1] for p in pos) == 8 * 39.37,
          'axes Blender convertis (Y haut -> Z haut, -Z avant -> +Y), metres -> pouces')
    pos, nrm, uvs, tan = complete_mesh(pos, nrm, uvs, tris)
    # orientation : la pente doit regarder vers le haut
    a, b, c = (pos[i] for i in tris[0])
    n = ((b[1] - a[1]) * (c[2] - a[2]) - (b[2] - a[2]) * (c[1] - a[1]),
         (b[2] - a[2]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[2] - a[2]),
         (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))
    check(n[2] > 0, 'triangle de pente oriente vers le haut (anti-horaire, comme le jeu)')
    data = build_model(template, pos, nrm, uvs, tan, tris, 'Levels/Octane/Custom/Rampe')
    z = IgzFile(data)
    check(z.to_bytes() == data, 'modele relu et reecrit a l\'identique')
    p2, i2 = model_mesh(data)
    pts = [tuple(round(p2[k + j], 3) for j in range(3)) for k in range(0, len(p2), 3)]
    check(len(pts) == 6 and len(i2) == 24, f'relu : {len(pts)} sommets, {len(i2) // 3} triangles')
    check(all(math.dist(a, b) < 1e-3 for a, b in zip(pts, pos)), 'positions identiques')
    check(list(i2) == [i for t in tris for i in t], 'indices identiques')
    md = next(o for o, t in z.objects.items() if t == 'igModelData')
    lo, hi = z.vec3(md + 0x20), z.vec3(md + 0x30)
    check(abs(hi[1] - 8 * 39.37) < 1e-3 and abs(hi[2] - 2 * 39.37) < 1e-3, f'boite englobante {lo} {hi}')
    check(z.dump_object(md)['_name'].endswith('Custom/Rampe.igb'), 'nom interne renomme')
    # changement de materiau : celui d'un autre modele au meme format de sommet
    src = 'models/Levels/Octane/T111_Crash_Cove/T111_WoodArrow.igz'
    _, name, ns, dep, sig, _ = model_materials(pak_tool.read_latest(archives, src, 't111_crash_cove.pak')[0])[0]
    check(sig == model_materials(template)[0][4], f'{name} : meme format de sommet que le gabarit')
    d2 = build_model(template, pos, nrm, uvs, tan, tris, 'Levels/Octane/Custom/Rampe', (name, ns, dep))
    z2 = IgzFile(d2)
    check(model_materials(d2)[0][1:4] == (name, ns, dep), 'handle du draw call + TDEP -> nouveau materiau')
    ht = next(o for o, t in z2.objects.items() if t == 'igStringInsensitiveStringHashTable')
    check(z2.hash_items(ht) == [(f"{ns.split(',')[0]}.{name}", z2.strings.index(f'{ns}.{name}'))],
          'table CMaterialHandleTableInfo mise a jour')
    check(model_mesh(d2) == model_mesh(data), 'geometrie inchangee')
    m0 = model_materials(template)[0]
    d3 = build_model(template, pos, nrm, uvs, tan, tris, 'Levels/Octane/Custom/Rampe', m0[1:4])
    check(IgzFile(d3).fixups['TDEP'] == IgzFile(template).fixups['TDEP'],
          'TDEP reecrit avec le materiau du gabarit = octets d\'origine (terminateur vide + alignement)')
    # scene : groupes (objet, materiau) + decoupage au-dela d'un nombre de sommets
    scene = 'o A\nusemtl Bois\n' + RAMP_OBJ.replace('f 3 4 5 6', 'usemtl Roche\nf 3 4 5 6') + '\no B\nusemtl Bois\nf 1 2 3\n'
    gs = parse_obj_groups(scene)
    check([(g['object'], g['material'], len(g['tris'])) for g in gs] == [('A', 'Bois', 4), ('A', 'Roche', 4), ('B', 'Bois', 1)],
          'scene : un groupe par (objet, materiau)')
    parts = parse_obj_groups(RAMP_OBJ, max_verts=4)
    check(len(parts) > 1 and all(len(g['pos']) <= 4 for g in parts) and sum(len(g['tris']) for g in parts) == 8,
          f'decoupage a 4 sommets : {len(parts)} morceaux, aucun triangle perdu')
    if out:
        open(out, 'wb').write(data)
        print('ecrit', out)
    print('tous les tests passent')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
