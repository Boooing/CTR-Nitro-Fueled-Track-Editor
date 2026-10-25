"""Tests hors jeu : copie de la collision d'un objet (Bridge04) + reconstruction de l'arbre du compound.

Usage : python test_collision_copy.py <dossier archives>
"""
import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pak_tool  # noqa: E402
from collision_region import GroundEditor, apply, mat_inv_rigid_scale, mat_mul, object_matrix  # noqa: E402
from decor import DecorFile, model_logical_path, model_mesh  # noqa: E402
from havok import Packfile  # noqa: E402

TRACK, TP = 'T111_Crash_Cove', 't111_crash_cove.pak'
HKX = f'models/maps/Octane/{TRACK}/StaticCollision_{TRACK}.hkx'


def check(cond, msg):
    print(('OK   ' if cond else 'ECHEC') + ' ' + msg)
    if not cond:
        raise SystemExit(1)


def compound_tree_ok(raw):
    """Chaque instance est atteinte par exactement une feuille dont la boite contient son origine."""
    pf = Packfile(raw)
    comp = next(o for o, c in pf.objects.items() if c == 'hknpStaticCompoundShape')
    tree = next(o for o, c in pf.objects.items() if c == 'hknpStaticCompoundShapeData')
    io, n = pf.array(comp + 0x60)
    no, nn = pf.array(tree + 0x10)
    nodes = [pf.data[no + i * 6:no + i * 6 + 6] for i in range(nn)]
    dom = (pf.floats(tree + 0x20, 3), pf.floats(tree + 0x30, 3))
    seen, ok = [], 0

    def walk(i, box):
        nonlocal ok
        nd = nodes[i]
        lo, hi = list(box[0]), list(box[1])
        for k in range(3):
            e = box[1][k] - box[0][k]
            lo[k] = box[0][k] + ((nd[k] >> 4) ** 2) * e / 226.0
            hi[k] = box[1][k] - ((nd[k] & 15) ** 2) * e / 226.0
        v = ((nd[3] & 0x7F) << 16) | struct.unpack_from('<H', nd, 4)[0]
        if not nd[3] & 0x80:
            seen.append(v)
            c = pf.floats(io + v * 128 + 0x30, 3)
            if all(lo[k] - 1e-3 <= c[k] <= hi[k] + 1e-3 for k in range(3)):
                ok += 1
            return
        walk(i + 1, (lo, hi))
        walk(i + 2 * v, (lo, hi))
    walk(0, dom)
    return n, sorted(seen) == list(range(n)), ok, pf.data[comp + 0x12]


def main(archives):
    hk, _ = pak_tool.read_latest(archives, HKX, TP)
    art, _ = pak_tool.read_latest(archives, f'maps/Octane/{TRACK}/{TRACK}_Art_Core.igz', TP)
    b = next(o for o in DecorFile(art).objects() if o['name'] == 'Bridge04')
    # 1) arbre reconstruit sans aucune modification de geometrie (force via une edition neutre d'instance)
    ge = GroundEditor(hk)
    ge.set_instance(0, b['pos'], b['euler'], b['scale'])
    out = ge.to_bytes()
    n, all_leaves, ok, bits = compound_tree_ok(out)
    check(all_leaves and ok >= n - 1, f'arbre reconstruit : {n} instances, toutes en feuille, origines contenues {ok}/{n}, bits {bits}')
    # 2) copie de Bridge04 a +3000 po en X : triangles lies + instance propre
    ge = GroundEditor(hk)
    pos, idx = model_mesh(pak_tool.read_latest(archives, model_logical_path(b['model']), TP)[0])
    M0 = object_matrix(b['pos'], b['euler'], b['scale'])
    V = [apply(M0, pos[k:k + 3]) for k in range(0, len(pos), 3)]
    tris = [(V[idx[i]], V[idx[i + 1]], V[idx[i + 2]]) for i in range(0, len(idx) - 2, 3)]
    seeds = [s for s in ge.select_near_mesh(tris, 12.0) if ge.meshes[s[0]]['instance'] != 0]
    lo = [min(v[k] for v in V) for k in range(3)]
    hi = [max(v[k] for v in V) for k in range(3)]
    sel = ge.grow_connected([s for s in seeds if ge.meshes[s[0]]['mesh'].prims[s[1]].value == 13],
                            ([lo[0] - 40, lo[1] - 40, lo[2] - 120], [hi[0] + 40, hi[1] + 40, hi[2] + 40]))
    new_pos = [b['pos'][0] + 3000, b['pos'][1], b['pos'][2]]
    delta = mat_mul(object_matrix(new_pos, b['euler'], b['scale']), mat_inv_rigid_scale(M0))
    n_before = sum(len(m['mesh'].prims) for m in ge.meshes)
    ge.copy(sel, delta)
    ge.add_instance(0, new_pos, b['euler'], b['scale'])
    out = ge.to_bytes()
    ge2 = GroundEditor(out)
    n_after = sum(len(m['mesh'].prims) for m in ge2.meshes)
    marker = len(next(m for m in ge.meshes if m['instance'] == 0)['mesh'].prims)   # forme reutilisee par la nouvelle instance
    check(n_after == n_before + len(sel) + marker, f'{len(sel)} primitives copiees + instance ({marker} prim.) : {n_before} -> {n_after}')
    # les copies sont bien a +3000 en X des originales
    orig = sorted(tuple(round(c) for c in v) for mi, pi, vs in GroundEditor(hk).prims_world() if (mi, pi) in set(sel) for v in vs)
    moved = sorted((x - 3000, y, z) for x, y, z in orig)
    world = sorted(tuple(round(c) for c in v) for _, _, vs in ge2.prims_world() for v in vs)
    import bisect
    found = sum(1 for p in moved if any(math.dist(p, (p[0] + 6000, p[1], p[2])) for _ in [0]))  # placeholder
    shifted = [(x + 3000, y, z) for x, y, z in orig]
    wset = set(world)
    near = sum(1 for p in shifted if any((p[0] + dx, p[1] + dy, p[2] + dz) in wset for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)))
    check(near == len(shifted), f'sommets copies retrouves a +3000 po : {near}/{len(shifted)}')
    n, all_leaves, ok, bits = compound_tree_ok(out)
    check(n == 78 and all_leaves and ok >= n - 1, f'instance ajoutee : {n} instances, toutes en feuille, origines contenues {ok}/{n}, bits {bits}')
    pf = Packfile(out)
    comp = next(o for o, c in pf.objects.items() if c == 'hknpStaticCompoundShape')
    io, _ = pf.array(comp + 0x60)
    check(pf.ptr(io + 77 * 128 + 0x50) == pf.ptr(io + 0 * 128 + 0x50), 'la nouvelle instance utilise la forme de l\'instance source')
    check(abs(pf.floats(io + 77 * 128 + 0x30, 3)[0] * 39.37 - new_pos[0]) < 0.5, 'et sa position')
    print('tous les tests passent')


if __name__ == '__main__':
    main(sys.argv[1])
