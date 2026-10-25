"""Assemble la geometrie visuelle d'une piste : modeles places par les fichiers maps/.../<Piste>_Art*.igz.

Usage : python level_geometry.py <dossier extrait de la piste> <Piste> <sortie.obj> [--filtre Art] [--max-tri N]
  ex. : python level_geometry.py extracted/t111_crash_cove T111_Crash_Cove out/T111_Crash_Cove.level.obj

Modele (.igz) : igModelDrawCallData +0x48 -> igGraphicsVertexBuffer (+0x20 igVertexBuffer),
  +0x50 -> igGraphicsIndexBuffer (+0x20 igIndexBuffer). igVertexBuffer : +0x0C nb sommets, +0x20 igMemoryRef
  des donnees, +0x30 igVertexFormat (+0x0C taille d'un sommet, +0x10 elements de 12 octets {type, usage, offset}).
  Positions : float3 (type 2, usage 0). Indices : u16, listes de triangles (type 3).
Placement : igEntity (+0x20 position, +0x30 igEntityTransform, +0x40 igEntityData -> table de composants ->
  CModelComponentData._fileName). igEntityTransform : +0x60 Euler (radians), +0x6C echelle, +0x70 echelle xyz.
"""
import glob
import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from igz import IgzFile  # noqa: E402


def decode_model(path):
    """[(sommets, triangles)] de chaque draw call d'un modele, en repere modele."""
    z = IgzFile(path)
    meshes = []
    for o, t in z.objects.items():
        if t != 'igModelDrawCallData':
            continue
        gvb, gib = z.deref(o + 0x48), z.deref(o + 0x50)
        if gvb is None or gib is None:
            continue
        vb, ib = z.deref(gvb + 0x20), z.deref(gib + 0x20)
        if vb is None or ib is None:
            continue
        nv = z.u32(vb + 0x0C)
        vdata, _ = z.memory_ref(vb + 0x20)
        fmt = z.deref(vb + 0x30)
        if vdata is None or fmt is None:
            continue
        stride = z.u32(fmt + 0x0C)
        el, el_size = z.memory_ref(fmt + 0x10)
        pos_off = 0
        if el is not None:
            ebuf, eo = z._loc(el)
            for i in range(el_size // 12):
                e = ebuf[eo + i * 12:eo + i * 12 + 12]
                if e[4] == 0 and e[0] == 2:
                    pos_off = struct.unpack_from('<H', e, 8)[0]
                    break
        vbuf, vo = z._loc(vdata)
        verts = [struct.unpack_from('<3f', vbuf, vo + i * stride + pos_off) for i in range(nv)]
        ni = z.u32(ib + 0x0C)
        idata, _ = z.memory_ref(ib + 0x20)
        if idata is None:
            continue
        ibuf, io = z._loc(idata)
        idx = struct.unpack_from(f'<{ni}H', ibuf, io)
        tris = [idx[i:i + 3] for i in range(0, ni - 2, 3)]
        meshes.append((verts, tris))
    return meshes


def euler_matrix(rx, ry, rz):
    """R = Rz * Ry * Rx (lignes)."""
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    return [[cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx],
            [sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx],
            [-sy, cy * sx, cy * cx]]


def placements(map_file):
    """[(nom, fichier modele, position, euler, echelle xyz, types de composants)] des entites a modele d'un fichier de carte."""
    z = IgzFile(map_file)
    names = {o: n for n, o in z.root_objects()}
    out = []
    for o, t in z.objects.items():
        if t not in ('igEntity', 'CEntity', 'CGameEntity'):
            continue
        data = z.deref(o + 0x40)
        if data is None:
            continue
        table = z.deref(data + 0x10)
        model, comps = None, set()
        for _, v in (z.hash_items(table) if table is not None else []):
            off = int(v['@ref'], 16) if isinstance(v, dict) and '@ref' in v else None
            if off is not None:
                comps.add(z.objects.get(off))
            if off is not None and z.objects.get(off) == 'CModelComponentData':
                d = z.dump_object(off)
                model = d.get('_fileName')
        if not model:
            continue
        pos = z.vec3(o + 0x20)
        tr = z.deref(o + 0x30)
        if tr is not None:
            euler = list(struct.unpack_from('<3f', *z._loc(tr + 0x60)))
            s = z.f32(tr + 0x6C)
            scale = [c * s for c in struct.unpack_from('<3f', *z._loc(tr + 0x70))]
        else:
            euler, scale = [0, 0, 0], [1, 1, 1]
        out.append((names.get(o) or f'entity@{o:#x}', model, pos, euler, scale, comps))
    return out


def model_path(root, file_name):
    rel = file_name.replace('\\', '/').split(':', 1)[-1].lstrip('/')
    rel = os.path.splitext(rel)[0] + '.igz'
    p = os.path.join(root, 'models', *rel.split('/'))
    return p if os.path.exists(p) else None


def build(root, track, out, name_filter='Art', max_tri=None):
    maps = sorted(glob.glob(os.path.join(root, 'maps', 'Octane', track, f'{track}_*.igz')))
    maps = [m for m in maps if name_filter.lower() in os.path.basename(m).lower()]
    cache, lines, nv, stats = {}, [f'# geometrie {track} (unites du jeu : pouces, Z vertical)'], 0, \
        {'instances': 0, 'missing': set(), 'tri': 0}
    for mf in maps:
        for name, model, pos, euler, scale, _ in placements(mf):
            p = model_path(root, model)
            if p is None:
                stats['missing'].add(model)
                continue
            if p not in cache:
                try:
                    cache[p] = decode_model(p)
                except Exception as e:  # noqa: BLE001
                    print('  modele illisible', p, e)
                    cache[p] = []
            R = euler_matrix(*euler)
            lines.append(f'o {os.path.basename(mf)[len(track) + 1:-4]}__{name}')
            for verts, tris in cache[p]:
                for v in verts:
                    x, y, z = v[0] * scale[0], v[1] * scale[1], v[2] * scale[2]
                    lines.append('v %.2f %.2f %.2f' % tuple(R[i][0] * x + R[i][1] * y + R[i][2] * z + pos[i]
                                                           for i in range(3)))
                lines += [f'f {a + nv + 1} {b + nv + 1} {c + nv + 1}' for a, b, c in tris]
                nv += len(verts)
                stats['tri'] += len(tris)
            stats['instances'] += 1
            if max_tri and stats['tri'] > max_tri:
                break
    with open(out, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    return stats


if __name__ == '__main__':
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)
    flt = sys.argv[sys.argv.index('--filtre') + 1] if '--filtre' in sys.argv else 'Art'
    st = build(sys.argv[1], sys.argv[2], sys.argv[3], flt)
    print(f'{st["instances"]} instances, {st["tri"]} triangles -> {sys.argv[3]}')
    if st['missing']:
        print(f'{len(st["missing"])} modeles absents de ce dossier (autres archives ?), ex. : {sorted(st["missing"])[:3]}')
