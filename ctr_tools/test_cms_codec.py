"""Aller-retour du maillage de collision : sol de Crash Cove decode -> encode -> reecrit -> relu.

Usage : python test_cms_codec.py <dossier archives> [sortie.hkx]
"""
import collections
import math
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pak_tool  # noqa: E402
from cms_codec import encode_mesh, read_mesh, write_mesh  # noqa: E402
from havok import Packfile  # noqa: E402
from havok_writer import PackfileWriter  # noqa: E402

TRACK = 'T111_Crash_Cove'
HKX = f'models/maps/Octane/{TRACK}/StaticCollision_{TRACK}.hkx'


def check(cond, msg):
    print(('OK   ' if cond else 'ECHEC') + ' ' + msg)
    if not cond:
        raise SystemExit(1)


def ground_shape(pf):
    c = next(o for o, k in pf.objects.items() if k == 'hknpStaticCompoundShape')
    io, n = pf.array(c + 0x60)
    best = None
    for i in range(n):
        s = pf.ptr(io + i * 128 + 0x50)
        if pf.objects.get(s) == 'hknpCompressedMeshShape':
            cnt = pf.array(pf.ptr(s + 0x58) + 0x60)[1]
            if best is None or cnt > best[0]:
                best = (cnt, s)
    return best[1]


def tri_records(mesh):
    out = []
    for p in mesh.prims:
        for t, tri in enumerate(p.triangles()):
            out.append((tri, p.value, p.interior[t], p.flat))
    return out


def tree_check(pf, shape):
    """Verifie les deux niveaux d'arbre du maillage (memes regles que le decodage valide sur l'original)."""
    d = pf.ptr(shape + 0x58)
    dom = (pf.floats(d + 0x20, 3), pf.floats(d + 0x30, 3))

    def child(nd, box):
        lo, hi = list(box[0]), list(box[1])
        for k in range(3):
            e = box[1][k] - box[0][k]
            lo[k] = box[0][k] + ((nd[k] >> 4) ** 2) * e / 226.0
            hi[k] = box[1][k] - ((nd[k] & 15) ** 2) * e / 226.0
        return lo, hi
    inside = lambda b, lo, hi, eps=1e-3: all(b[0][k] - eps <= lo[k] and hi[k] <= b[1][k] + eps for k in range(3))
    sec_off, nsec = pf.array(d + 0x50)
    tn_off, tn = pf.array(d + 0x10)
    top = [pf.data[tn_off + i * 5:tn_off + i * 5 + 5] for i in range(tn)]
    ok = [0, 0]
    leaf_nodes = {}

    def walk(i, box):
        nd = top[i]
        b = child(nd, box)
        v = ((nd[3] & 0x7f) << 8) | nd[4]
        if not nd[3] & 0x80:
            leaf_nodes[v] = i
            o = sec_off + v * 0x60
            ok[0 if inside(b, pf.floats(o + 0x10, 3), pf.floats(o + 0x20, 3)) else 1] += 1
            return
        walk(i + 1, b)
        walk(i + 2 * v, b)
    walk(0, dom)
    leaf_ok = sum(1 for s in range(nsec) if leaf_nodes.get(s) == pf.u16(sec_off + s * 0x60 + 0x5a))
    return ok, leaf_ok, nsec


def main(archives, out_path=None):
    hk, src = pak_tool.read_latest(archives, HKX, TRACK.lower() + '.pak')
    pf = Packfile(hk)
    shape = ground_shape(pf)
    t = time.time()
    mesh = read_mesh(pf, shape)
    orig = tri_records(mesh)
    print(f'sol ({os.path.basename(src)}) : {len(mesh.prims)} primitives, {len(orig)} triangles, lu en {time.time() - t:.1f} s')
    t = time.time()
    enc = encode_mesh(mesh)
    print(f'encode en {time.time() - t:.1f} s : {len(enc["sections"])} sections, {len(enc["shared"]) // 8} sommets partages, '
          f'{len(enc["packed"]) // 4} compresses, cle max {enc["max_key"]} ({enc["bits_per_key"]} bits)')
    w = PackfileWriter(hk)
    write_mesh(w, shape, enc)
    out = w.to_bytes()
    pf2 = Packfile(out)
    mesh2 = read_mesh(pf2, ground_shape(pf2))
    new = tri_records(mesh2)
    check(len(new) == len(orig), f'{len(new)} triangles relus (original {len(orig)})')
    # appariement : l'ordre change (rangement par section) -> triangle relu le plus proche (centres, grille 2 m)
    cen = lambda tri: tuple(sum(v[k] for v in tri) / 3 for k in range(3))
    grid = collections.defaultdict(list)
    for j, r in enumerate(new):
        c = cen(r[0])
        grid[(int(c[0] // 2), int(c[1] // 2), int(c[2] // 2))].append(j)
    pairs, used = [], set()
    for r in orig:
        c = cen(r[0])
        g = (int(c[0] // 2), int(c[1] // 2), int(c[2] // 2))
        best = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for j in grid.get((g[0] + dx, g[1] + dy, g[2] + dz), ()):
                        if j in used:
                            continue
                        e = max(math.dist(a, b) for a, b in zip(r[0], new[j][0]))
                        if best is None or e < best[0]:
                            best = (e, j)
        if best:
            used.add(best[1])
            pairs.append((r, new[best[1]], best[0]))
    check(len(pairs) == len(orig), f'{len(pairs)}/{len(orig)} triangles apparies (meme ordre de sommets)')
    errs = [e for _, _, e in pairs]
    check(max(errs) < 0.08, f'ecart de position max {max(errs) * 100:.1f} cm, moyen {sum(errs) / len(errs) * 100:.2f} cm')
    # triangles superposes (meme geometrie a 1 mm pres) : l'appariement peut les croiser -> on compare par groupe
    gkey = lambda tri: tuple(tuple(round(c / 0.001) for c in v) for v in tri)
    groups_o, groups_n = collections.defaultdict(list), collections.defaultdict(list)
    for a, b, _ in pairs:
        groups_o[gkey(a[0])].append(a[1:])
        groups_n[gkey(a[0])].append(b[1:])
    bad = sum(1 for k in groups_o if sorted(groups_o[k]) != sorted(groups_n[k]))
    dup = sum(1 for k in groups_o if len(groups_o[k]) > 1)
    check(bad == 0, f'surfaces et drapeaux interior/flat identiques ({dup} groupes de triangles superposes compares en bloc)')
    (ok, bad), leaf_ok, nsec = tree_check(pf2, ground_shape(pf2))
    check(bad == 0 and ok == nsec and leaf_ok == nsec, f'arbre du haut : {ok}/{nsec} sections contenues, indices de feuille {leaf_ok}/{nsec}')
    # arbres de section : reutilise la verification de la sonde (toutes les primitives contenues)
    d = pf2.ptr(ground_shape(pf2) + 0x58)
    sec_off, nsec = pf2.array(d + 0x50)
    total = contained = 0
    idx = 0
    for s in range(nsec):
        o = sec_off + s * 0x60
        no, nn = pf2.array(o)
        nodes = [pf2.data[no + i * 4:no + i * 4 + 4] for i in range(nn)]
        box0 = (pf2.floats(o + 0x10, 3), pf2.floats(o + 0x20, 3))
        pcount = pf2.u32(o + 0x50) & 0xff
        sec_prims = mesh2.prims[idx:idx + pcount]
        idx += pcount

        def walk(i, box):
            nonlocal total, contained
            nd = nodes[i]
            lo, hi = list(box[0]), list(box[1])
            for k in range(3):
                e = box[1][k] - box[0][k]
                lo[k] = box[0][k] + ((nd[k] >> 4) ** 2) * e / 226.0
                hi[k] = box[1][k] - ((nd[k] & 15) ** 2) * e / 226.0
            if not nd[3] & 1:
                total += 1
                p = sec_prims[nd[3] >> 1]
                if all(all(lo[k] - 1e-3 <= v[k] <= hi[k] + 1e-3 for k in range(3)) for v in p.verts):
                    contained += 1
                return
            walk(i + 1, (lo, hi))
            walk(i + (nd[3] >> 1) * 2, (lo, hi))
        walk(0, box0)
    check(total == len(mesh2.prims) and contained == total, f'arbres de section : {contained}/{total} primitives contenues')
    if out_path:
        open(out_path, 'wb').write(out)
        print('ecrit', out_path, len(out), 'octets')
    print('tous les tests passent')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
