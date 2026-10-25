"""Exporte la collision statique Havok d'une piste (StaticCollision_<Piste>.hkx) en OBJ.

Usage : python collision.py <StaticCollision_X.hkx> <sortie.obj> [--scale 39.37]

Structures (hk_2014.1, deduites des donnees ; offsets 64 bits) :
  hknpStaticCompoundShape +0x60 hkArray<instance 128 o> : rotation 3x vec4 (w = drapeaux), translation vec4,
      echelle vec4 (+0x40), forme* (+0x50)
  hknpCompressedMeshShape +0x58 -> hknpCompressedMeshShapeData
  hknpCompressedMeshShapeData (arbre hkcdStaticMeshTree a +0x10) :
      +0x10 noeuds, +0x20 domaine (min vec4, max vec4), +0x50 sections[0x60], +0x60 primitives u8[4],
      +0x70 indices partages u16, +0x80 sommets compresses u32, +0x90 sommets partages u64, +0xA0 data runs
  section : +0x30 codec (offset xyz, echelle xyz), +0x48 premier sommet compresse,
      +0x4C (debut indices partages << 8 | nb compresses), +0x50 (debut << 8 | nb primitives),
      +0x58 nb sommets compresses (u8), nb indices partages (u8)
  sommet compresse u32 : x 11 bits, y 11 bits, z 10 bits -> offset + echelle * q (repere de la section)
  sommet partage u64 : x 21 bits, y 21 bits, z 22 bits -> domaine de l'arbre
  primitive : 4 indices (< nb compresses : sommet compresse, sinon partage) ; quad si c != d
  hknpConvexPolytopeShape : sommets = hkRelArray (u16 nombre, u16 offset relatif au champ) a +0x28, vec4 xyz + w
  hknpSphereShape : rayon a +0x14, centre = premier sommet
Les unites Havok sont des metres et celles du jeu des POUCES : --scale 39.37 (defaut). Verifie sur Crash Cove :
281/282 points de spline ont le sol juste en dessous (2 m mediane) avec 39.37, presque aucun avec 10..100.
"""
import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from havok import Packfile  # noqa: E402


def decode_compressed_mesh(pf, data):
    """Retourne (sommets, triangles) d'un hknpCompressedMeshShapeData, dans le repere de la forme."""
    dom_min, dom_max = pf.floats(data + 0x20, 3), pf.floats(data + 0x30, 3)
    sec_off, nsec = pf.array(data + 0x50)
    prim_off, _ = pf.array(data + 0x60)
    shidx_off, _ = pf.array(data + 0x70)
    packed_off, _ = pf.array(data + 0x80)
    shared_off, nshared = pf.array(data + 0x90)

    ext = [dom_max[i] - dom_min[i] for i in range(3)]
    shared = []
    for i in range(nshared):
        v = pf.u64(shared_off + i * 8)
        q = (v & 0x1FFFFF, (v >> 21) & 0x1FFFFF, v >> 42)
        div = (0x1FFFFF, 0x1FFFFF, 0x3FFFFF)
        shared.append([dom_min[k] + ext[k] * q[k] / div[k] for k in range(3)])

    verts, tris, index_of_shared = [], [], {}
    for s in range(nsec):
        sec = sec_off + s * 0x60
        codec = pf.floats(sec + 0x30, 6)
        first_packed = pf.u32(sec + 0x48)
        sh_field, prim_field = pf.u32(sec + 0x4C), pf.u32(sec + 0x50)
        n_packed, n_shared = pf.u8(sec + 0x58), pf.u8(sec + 0x59)
        sh_start = sh_field >> 8
        p_start, p_count = prim_field >> 8, prim_field & 0xFF
        local = []
        for k in range(n_packed):
            v = pf.u32(packed_off + (first_packed + k) * 4)
            q = (v & 0x7FF, (v >> 11) & 0x7FF, v >> 22)
            verts.append([codec[i] + codec[3 + i] * q[i] for i in range(3)])
            local.append(len(verts) - 1)
        for k in range(n_shared):
            g = pf.u16(shidx_off + (sh_start + k) * 2)
            if g not in index_of_shared:
                verts.append(shared[g])
                index_of_shared[g] = len(verts) - 1
            local.append(index_of_shared[g])
        for p in range(p_start, p_start + p_count):
            a, b, c, d = pf.data[prim_off + p * 4:prim_off + p * 4 + 4]
            if max(a, b, c, d) >= len(local):
                continue
            tris.append((local[a], local[b], local[c]))
            if c != d:
                tris.append((local[a], local[c], local[d]))
    return verts, tris


def decode_polytope(pf, shape):
    """Sommets d'un hknpConvexPolytopeShape (enveloppe convexe : on exporte les points)."""
    count, rel_off = struct.unpack_from('<HH', pf.data, shape + 0x28)
    base = shape + 0x28 + rel_off
    return [pf.floats(base + i * 16, 3) for i in range(count)]


def transform(m, scale, p):
    x, y, z = (p[i] * scale[i] for i in range(3))
    return [m[0] * x + m[4] * y + m[8] * z + m[12],
            m[1] * x + m[5] * y + m[9] * z + m[13],
            m[2] * x + m[6] * y + m[10] * z + m[14]]


def export(path, out, unit_scale=39.37):
    pf = Packfile(path)
    compound = next(o for o, c in pf.objects.items() if c == 'hknpStaticCompoundShape')
    inst_off, ninst = pf.array(compound + 0x60)
    lines = [f'# collision {os.path.basename(path)} ({ninst} instances, echelle x{unit_scale})']
    nv, stats = 0, {'mesh': 0, 'tri': 0, 'polytope': 0, 'sphere': 0}
    for i in range(ninst):
        b = inst_off + i * 128
        m = pf.floats(b, 16)
        sc = pf.floats(b + 0x40, 3)
        shape = pf.ptr(b + 0x50)
        kind = pf.objects.get(shape)
        if kind == 'hknpCompressedMeshShape':
            verts, tris = decode_compressed_mesh(pf, pf.ptr(shape + 0x58))
            lines.append(f'o mesh_{i:02d}')
            lines += ['v %.3f %.3f %.3f' % tuple(c * unit_scale for c in transform(m, sc, v)) for v in verts]
            lines += [f'f {a + nv + 1} {b2 + nv + 1} {c + nv + 1}' for a, b2, c in tris]
            nv += len(verts)
            stats['mesh'] += 1
            stats['tri'] += len(tris)
        elif kind == 'hknpConvexPolytopeShape':
            pts = decode_polytope(pf, shape)
            lines.append(f'o polytope_{i:02d}')
            lines += ['v %.3f %.3f %.3f' % tuple(c * unit_scale for c in transform(m, sc, v)) for v in pts]
            lines.append('p ' + ' '.join(str(nv + k + 1) for k in range(len(pts))))
            nv += len(pts)
            stats['polytope'] += 1
        elif kind == 'hknpSphereShape':
            radius = pf.f32(shape + 0x14) * sc[0]
            c = transform(m, sc, [0, 0, 0])
            lines.append(f'o sphere_{i:02d}_r{radius * unit_scale:.0f}')
            # octaedre approximant la sphere
            for d in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                lines.append('v %.3f %.3f %.3f' % tuple((c[k] + d[k] * radius) * unit_scale for k in range(3)))
            for f in ((0, 2, 4), (2, 1, 4), (1, 3, 4), (3, 0, 4), (2, 0, 5), (1, 2, 5), (3, 1, 5), (0, 3, 5)):
                lines.append('f ' + ' '.join(str(nv + k + 1) for k in f))
            nv += 6
            stats['sphere'] += 1
    with open(out, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    return stats


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    scale = float(sys.argv[sys.argv.index('--scale') + 1]) if '--scale' in sys.argv else 39.37
    st = export(sys.argv[1], sys.argv[2], scale)
    print(f'{st["mesh"]} maillages ({st["tri"]} triangles), {st["polytope"]} polytopes, {st["sphere"]} spheres -> {sys.argv[2]}')
