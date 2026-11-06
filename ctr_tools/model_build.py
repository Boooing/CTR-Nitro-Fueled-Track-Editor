"""Creation de modeles .igz a partir d'un gabarit + import OBJ.

Gabarit : un modele du jeu a UN draw call et au format de sommet standard (40 o : position f32x3,
normale f32x3, UV half2, tangente f32x3), ex. models/Levels/Octane/T111_Crash_Cove/T111_RockGroundSide_b.igz.
Le materiau (texture) du gabarit est conserve, ou remplace par celui d'un autre modele (set_material) a condition
que son draw call ait exactement le meme format de sommet (le shader lit les memes attributs). On remplace :
  igModelData +0x20/+0x30 et igModelDrawCallData +0x20/+0x30 : boite englobante (w = 1 / 0 comme l'original)
  igVertexBuffer +0x0C nb sommets, +0x10 bloc « vertexCountArray » (u32), +0x20 igMemoryRef des donnees
  igIndexBuffer  +0x0C nb indices, +0x10 bloc « indexCountArray » (u32), +0x20 igMemoryRef des donnees
  section GPU (donnees n°1) : sommets puis indices u16 ; noms internes (.igb, « (0/1) ») renommes.
Conventions verifiees sur le gabarit : triangles anti-horaires (a, b, c) -> normale sortante, Z vertical,
unites du jeu = pouces.
"""
import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from igz import IgzFile, fnv1a_lower  # noqa: E402

TEMPLATE = 'models/Levels/Octane/T111_Crash_Cove/T111_RockGroundSide_b.igz'


def _half(f):
    return struct.unpack('<H', struct.pack('<e', max(-65504.0, min(65504.0, f))))[0]


MAX_MODEL_VERTS = 0xFFFF          # indices u16


def _parse_faces(text, scale, up):
    """Lecture brute : sommets/UV/normales globaux + triangles [(objet, materiau, (c0, c1, c2))]."""
    vs, vts, vns, faces = [], [], [], []
    obj, mtl = '', ''
    for line in text.splitlines():
        p = line.split()
        if not p or p[0].startswith('#'):
            continue
        if p[0] == 'v':
            x, y, z = map(float, p[1:4])
            vs.append((x * scale, -z * scale, y * scale) if up == 'y' else (x * scale, y * scale, z * scale))
        elif p[0] == 'vt':
            vts.append((float(p[1]), float(p[2]) if len(p) > 2 else 0.0))
        elif p[0] == 'vn':
            x, y, z = map(float, p[1:4])
            vns.append((x, -z, y) if up == 'y' else (x, y, z))
        elif p[0] in ('o', 'g'):
            obj = ' '.join(p[1:])
        elif p[0] == 'usemtl':
            mtl = ' '.join(p[1:])
        elif p[0] == 'f':
            corners = []
            for c in p[1:]:
                idx = (c.split('/') + ['', ''])[:3]
                fix = lambda s, n: (int(s) - 1 if int(s) > 0 else n + int(s)) if s else None
                corners.append((fix(idx[0], len(vs)), fix(idx[1], len(vts)), fix(idx[2], len(vns))))
            for k in range(1, len(corners) - 1):              # eventail
                faces.append((obj, mtl, (corners[0], corners[k], corners[k + 1])))
    return vs, vts, vns, faces


def _assemble(vs, vts, vns, faces, max_verts=None):
    """Triangles -> [(positions, normales|None, uvs|None, triangles)] sur des sommets uniques ; un nouveau
    morceau commence quand max_verts serait depasse."""
    has_uv = bool(vts) and all(c[1] is not None for f in faces for c in f)
    has_n = bool(vns) and all(c[2] is not None for f in faces for c in f)
    out, verts, index, tris = [], [], {}, []

    def flush():
        if tris:
            out.append(([vs[k[0]] for k in verts], [vns[k[2]] for k in verts] if has_n else None,
                        [vts[k[1]] for k in verts] if has_uv else None, list(tris)))
    for f in faces:
        keys = [(c[0], c[1] if has_uv else None, c[2] if has_n else None) for c in f]
        if max_verts and len(verts) + sum(k not in index for k in keys) > max_verts:
            flush()
            verts, index, tris = [], {}, []
        tri = []
        for key in keys:
            if key not in index:
                index[key] = len(verts)
                verts.append(key)
            tri.append(index[key])
        tris.append(tuple(tri))
    flush()
    return out


def parse_obj(text, scale=39.37, up='y'):
    """OBJ -> (positions, normales ou None, uvs ou None, triangles [(i, j, k)] sur des sommets uniques).

    up='y' : export Blender par defaut (Y vers le haut, -Z vers l'avant) -> converti en Z vers le haut.
    scale : unites OBJ -> pouces (39.37 si l'OBJ est en metres)."""
    vs, vts, vns, faces = _parse_faces(text, scale, up)
    parts = _assemble(vs, vts, vns, [f for _, _, f in faces])
    return parts[0] if parts else ([], None, None, [])


def parse_mtl(text):
    """Fichier .mtl -> {materiau: {'texture': fichier map_Kd ou None, 'color': Kd (r, g, b) ou None}}."""
    out, cur = {}, None
    for line in text.splitlines():
        p = line.strip().split(None, 1)
        if not p:
            continue
        key, rest = p[0], (p[1].strip() if len(p) > 1 else '')
        if key == 'newmtl':
            cur = out.setdefault(rest, {'texture': None, 'color': None})
        elif cur is None:
            continue
        elif key == 'map_Kd' and rest:
            # options eventuelles (-s 1 1 1, -o ...) avant le nom : le nom est la fin de la ligne
            parts = rest.split()
            while parts and parts[0].startswith('-'):
                parts = parts[1 + {'-s': 3, '-o': 3, '-t': 3, '-mm': 2, '-bm': 1, '-boost': 1, '-texres': 1,
                                   '-clamp': 1, '-blendu': 1, '-blendv': 1, '-imfchan': 1}.get(parts[0], 0):]
            cur['texture'] = ' '.join(parts) or None
        elif key == 'Kd':
            try:
                cur['color'] = tuple(float(v) for v in rest.split()[:3])
            except ValueError:
                pass
    return out


def obj_summary(text):
    """Lecture rapide d'un OBJ : bibliotheques mtllib, triangles par materiau, nombre de sommets, boite brute."""
    mtllibs, tris, mtl, nv = [], {}, '', 0
    lo, hi = [math.inf] * 3, [-math.inf] * 3
    for line in text.splitlines():
        if line.startswith('v '):
            nv += 1
            c = line.split()[1:4]
            for k in range(3):
                v = float(c[k])
                lo[k], hi[k] = min(lo[k], v), max(hi[k], v)
        elif line.startswith('f '):
            tris[mtl] = tris.get(mtl, 0) + len(line.split()) - 3
        elif line.startswith('usemtl'):
            mtl = line[6:].strip()
        elif line.startswith('mtllib'):
            mtllibs.append(line[6:].strip())
    return {'mtllibs': mtllibs, 'triangles': tris, 'vertices': nv, 'bounds': [lo, hi] if nv else None}


def obj_material_extents(text, up='y'):
    """{materiau: (plus grand cote horizontal, hauteur) (unites du fichier)} des sommets utilises par ses faces."""
    import numpy as np
    vs, used, mtl = [], {}, ''
    for line in text.splitlines():
        if line.startswith('v '):
            vs.append(tuple(float(c) for c in line.split()[1:4]))
        elif line.startswith('usemtl'):
            mtl = line[6:].strip()
        elif line.startswith('f '):
            s = used.setdefault(mtl, set())
            for c in line.split()[1:]:
                i = int(c.split('/')[0])
                s.add(i - 1 if i > 0 else len(vs) + i)
    V = np.array(vs) if vs else np.zeros((0, 3))
    h, vert = ([0, 1], 2) if up == 'z' else ([0, 2], 1)
    out = {}
    for m, idx in used.items():
        P = V[sorted(idx)]
        out[m] = ((float((P[:, h].max(0) - P[:, h].min(0)).max()), float(P[:, vert].max() - P[:, vert].min()))
                  if len(P) else (0.0, 0.0))
    return out


def obj_extents(text, pattern=None):
    """Emprise brute (lo, hi) des sommets utilises par les faces dont le materiau correspond a `pattern` (regex,
    insensible a la casse ; None = toutes), et emprise « coeur » de toute la scene (2e - 98e centile : sans le decor
    de fond tres lointain, nuages, montagnes). -> {'match': (lo, hi) | None, 'core': (lo, hi) | None}."""
    import re
    import numpy as np
    rx = re.compile(pattern, re.I) if pattern else None
    vs, used, mtl = [], set(), ''
    for line in text.splitlines():
        if line.startswith('v '):
            vs.append(tuple(float(c) for c in line.split()[1:4]))
        elif line.startswith('usemtl'):
            mtl = line[6:].strip()
        elif line.startswith('f ') and rx and rx.search(mtl):
            for c in line.split()[1:]:
                i = int(c.split('/')[0])
                used.add(i - 1 if i > 0 else len(vs) + i)
    out = {'match': None, 'core': None}
    if vs:
        V = np.array(vs)
        out['core'] = (np.percentile(V, 2, axis=0).tolist(), np.percentile(V, 98, axis=0).tolist())
        if used:
            U = V[sorted(used)]
            out['match'] = (U.min(0).tolist(), U.max(0).tolist())
    return out


def parse_obj_groups(text, scale=39.37, up='y', max_verts=MAX_MODEL_VERTS):
    """OBJ multi-objets / multi-materiaux -> [{'object', 'material', 'part', 'pos', 'nrm', 'uvs', 'tris'}] :
    un groupe par couple (objet `o`/`g`, materiau `usemtl`), decoupe en morceaux de max_verts sommets."""
    vs, vts, vns, faces = _parse_faces(text, scale, up)
    order, by_key = [], {}
    for obj, mtl, f in faces:
        if (obj, mtl) not in by_key:
            by_key[(obj, mtl)] = []
            order.append((obj, mtl))
        by_key[(obj, mtl)].append(f)
    groups = []
    for obj, mtl in order:
        for i, (pos, nrm, uvs, tris) in enumerate(_assemble(vs, vts, vns, by_key[(obj, mtl)], max_verts)):
            groups.append({'object': obj, 'material': mtl, 'part': i, 'pos': pos, 'nrm': nrm, 'uvs': uvs, 'tris': tris})
    return groups


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a):
    n = math.sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)


def complete_mesh(pos, nrm, uvs, tris, uv_scale=1.0 / 200.0):
    """Normales lissees si absentes, UV par projection selon l'axe dominant (1 repetition / 200 po) si
    absentes, tangentes (orthogonales aux normales)."""
    if nrm is None:
        acc = [(0.0, 0.0, 0.0)] * len(pos)
        for a, b, c in tris:
            n = _cross(_sub(pos[b], pos[a]), _sub(pos[c], pos[a]))
            for i in (a, b, c):
                acc[i] = (acc[i][0] + n[0], acc[i][1] + n[1], acc[i][2] + n[2])
        nrm = [_norm(n) for n in acc]
    if uvs is None:
        uvs = []
        for p, n in zip(pos, nrm):
            ax = max(range(3), key=lambda k: abs(n[k]))
            u, v = [p[k] for k in range(3) if k != ax]
            uvs.append((u * uv_scale, v * uv_scale))
    tan = []
    for p, n in zip(pos, nrm):
        ref = (0.0, 0.0, 1.0) if abs(n[2]) < 0.9 else (1.0, 0.0, 0.0)
        tan.append(_norm(_cross(ref, n)))
    return pos, nrm, uvs, tan


def vertex_layout(z, dc):
    """Signature du format de sommet d'un draw call (taille + elements bruts de 12 o)."""
    fmt = z.deref(z.deref(z.deref(dc + 0x48) + 0x20) + 0x30)
    n = (z.u32(fmt + 0x10) & 0xFFFFFF) // 12
    buf, bo = z._loc(z.deref(fmt + 0x18))
    return f'{z.u32(fmt + 0x0C)}:' + bytes(buf[bo:bo + 12 * n]).hex()


def tdep_entries(z):
    """[(espace de noms, chemin materials:/...igz)] du fixup TDEP."""
    cnt, body = z.fixups.get('TDEP', (0, b''))
    parts = body.split(b'\0')
    return [(parts[2 * i].decode('latin1'), parts[2 * i + 1].decode('latin1')) for i in range(cnt)]


def encode_tdep(pairs):
    """Corps du fixup TDEP : chaines (espace, chemin) terminees par \\0, PUIS une chaine vide de fin, aligne sur 4.
    Regle verifiee sur les 141 modeles de Crash Cove qui ont des dependances ; son absence est la cause probable
    du chargement infini observe avec des modeles dont le materiau avait ete change."""
    body = b''.join(s.encode('latin1') + b'\0' for p in pairs for s in p) + b'\0'
    return body + b'\0' * (-len(body) % 4)


def model_materials(data):
    """[(index du draw call, materiau, espace de noms, chemin TDEP, signature de sommet, nb triangles)]."""
    z = IgzFile(data)
    deps = dict(tdep_entries(z))
    out = []
    for i, dc in enumerate(o for o, t in sorted(z.objects.items()) if t == 'igModelDrawCallData'):
        h = z.u32(dc + 0x40)
        if not (dc + 0x40 in z.offset_sets.get('RHND', ()) and h & 0x80000000):
            continue
        name, ns = z.ext_names[h & 0x7FFFFFFF]
        ib = z.deref(z.deref(dc + 0x50) + 0x20)
        out.append((i, name, ns, deps.get(ns), vertex_layout(z, dc), z.u32(ib + 0x0C) // 3))
    return out


def set_material(z, name, ns, dep_path):
    """Remplace le materiau (unique) du modele : handle EXNM, dependance TDEP, table CMaterialHandleTableInfo."""
    struct.pack_into('<I', *z._loc(next(o for o in z.offset_sets['RHND'])), 0x80000000)   # handle -> EXNM[0]
    z.ext_names[0] = (name, ns)
    z._exnm_raw[0] = (z.add_string(name), z.add_string(ns) | 0x80000000)
    z.fixups['TDEP'] = (1, encode_tdep([(ns, dep_path)]))
    # table de hachage « bibliotheque.materiau » -> « espace.materiau » ; emplacement = FNV-1a % capacite
    ht = next(o for o, t in z.objects.items() if t == 'igStringInsensitiveStringHashTable')
    cap, vals, keys = z.u32(ht + 0x10) // 8, z.deref(ht + 0x18), z.deref(ht + 0x28)
    for i in range(cap):
        z.set_string_ref(vals + 8 * i, None)
        z.set_string_ref(keys + 8 * i, None)
    key = f"{ns.split(',')[0]}.{name}"
    slot = fnv1a_lower(key) % cap
    z.set_string_ref(keys + 8 * slot, key)
    z.set_string_ref(vals + 8 * slot, f'{ns}.{name}')


def build_model_multi(template, parts, model_name):
    """Modele a PLUSIEURS textures (2026-11-06) : un draw call par partie, comme les modeles du jeu a plusieurs
    materiaux (T111_WoodPost : 2 draw calls, chacun ses tampons de sommets / indices, handle de materiau 0, 1...).
    parts = [{'pos', 'nrm', 'uvs', 'tan', 'tris', 'material': (nom, espace, chemin TDEP)}] ; meme format de sommet
    (40 o) que le gabarit. igModelData : +0x70 nombre / +0x78 taille / +0x80 tableau des draw calls ; +0x88 / +0x90 /
    +0x98 : un u32 par draw call (0 dans les modeles du jeu). Draw call : +0x10 nom « .igb (i/N) », +0x20 / +0x30
    bornes, +0x40 handle du materiau, +0x48 / +0x50 tampons de sommets / indices. -> octets."""
    parts = [p for p in parts if len(p['tris'])]
    if not parts:
        raise ValueError('modele vide')
    if len(parts) == 1:
        p = parts[0]
        return build_model(template, p['pos'], p['nrm'], p['uvs'], p['tan'], p['tris'], model_name, p.get('material'))
    for p in parts:
        if len(p['pos']) > 0xFFFF:
            raise ValueError(f"{len(p['pos'])} sommets dans une partie : maximum 65535")
    z = IgzFile(template)
    dc0 = next(o for o, t in z.objects.items() if t == 'igModelDrawCallData')
    md = next(o for o, t in z.objects.items() if t == 'igModelData')
    vb0 = z.deref(z.deref(dc0 + 0x48) + 0x20)
    sec = (z.deref(vb0 + 0x28) or 0) >> 27                    # section des donnees GPU
    # draw calls supplementaires : copies du draw call du gabarit (objets et blocs propres, hors donnees GPU)
    objs, mem = z.reachable(dc0)
    mem = {m: s for m, s in mem.items() if m >> 27 != sec}
    names = {o: n for n, o in z.root_objects()}
    dcs = [dc0]
    for k in range(1, len(parts)):
        new, pairs = z.clone_owned(dc0, f'dc{k}', (objs, mem), names)
        if pairs:
            z.add_roots(pairs)
        dcs.append(new)
    # donnees GPU : sommets puis indices de chaque partie, a la suite
    gpu = bytearray()
    base = sec << 27
    spans = []
    for p in parts:
        voff = len(gpu)
        for q, n, uv, t in zip(p['pos'], p['nrm'], p['uvs'], p['tan']):
            gpu += struct.pack('<3f3fHH3f', *q, *n, _half(uv[0]), _half(1.0 - uv[1]), *t)
        gpu += b'\0' * (-len(gpu) % 16)
        ioff = len(gpu)
        idx = [i for t in p['tris'] for i in t]
        gpu += struct.pack(f'<{len(idx)}H', *idx)
        gpu += b'\0' * (-len(gpu) % 16)
        spans.append((voff, ioff, len(idx)))
    z.data[sec] = bytearray(gpu)

    def memref(off, size, data_off):
        flags = z.u32(off) & 0xF8000000
        struct.pack_into('<I', *z._loc(off), flags | size)
        z.set_ptr(off + 8, base | data_off)
    igb = f'data/octane/models/{model_name}.igb'
    n = len(parts)
    lo_all, hi_all = [float('inf')] * 3, [float('-inf')] * 3
    for i, (dc, p, (voff, ioff, nidx)) in enumerate(zip(dcs, parts, spans)):
        vb = z.deref(z.deref(dc + 0x48) + 0x20)
        ib = z.deref(z.deref(dc + 0x50) + 0x20)
        struct.pack_into('<I', *z._loc(vb + 0x0C), len(p['pos']))
        struct.pack_into('<I', *z._loc(z.deref(vb + 0x18)), len(p['pos']))
        memref(vb + 0x20, len(p['pos']) * 40, voff)
        struct.pack_into('<I', *z._loc(ib + 0x0C), nidx)
        struct.pack_into('<I', *z._loc(z.deref(ib + 0x18)), nidx)
        memref(ib + 0x20, nidx * 2, ioff)
        lo = [min(q[k] for q in p['pos']) for k in range(3)]
        hi = [max(q[k] for q in p['pos']) for k in range(3)]
        lo_all = [min(a, b) for a, b in zip(lo_all, lo)]
        hi_all = [max(a, b) for a, b in zip(hi_all, hi)]
        struct.pack_into('<3f', *z._loc(dc + 0x20), *lo)
        struct.pack_into('<3f', *z._loc(dc + 0x30), *hi)
        z.set_string_ref(dc + 0x10, f'{igb} ({i}/{n})')
        struct.pack_into('<I', *z._loc(dc + 0x40), 0x80000000 | i)          # materiau i (EXNM drapeau 1)
    struct.pack_into('<3f', *z._loc(md + 0x20), *lo_all)
    struct.pack_into('<3f', *z._loc(md + 0x30), *hi_all)
    z.set_string_ref(md + 0x10, igb)
    # liste des draw calls et liste d'un u32 par draw call
    arr = z.alloc(n * 8, 16)
    for i, dc in enumerate(dcs):
        z.set_ptr(arr + 8 * i, dc)
    struct.pack_into('<Q', *z._loc(md + 0x70), n)
    struct.pack_into('<I', *z._loc(md + 0x78), (z.u32(md + 0x78) & 0xF8000000) | n * 8)
    z.set_ptr(md + 0x80, arr)
    ints = z.alloc(max(n * 4, 8), 16)
    struct.pack_into('<Q', *z._loc(md + 0x88), n)
    struct.pack_into('<I', *z._loc(md + 0x90), (z.u32(md + 0x90) & 0xF8000000) | n * 4)
    z.set_ptr(md + 0x98, ints)
    # materiaux : une entree EXNM (handle nomme) par partie, dependances TDEP, table « bibliotheque.materiau »
    mats = [p['material'] for p in parts]
    z.ext_names = [(m[0], m[1]) for m in mats]
    z._exnm_raw = [(z.add_string(m[0]), z.add_string(m[1]) | 0x80000000) for m in mats]
    deps = list(dict.fromkeys((m[1], m[2]) for m in mats))
    z.fixups['TDEP'] = (len(deps), encode_tdep(deps))
    ht = next(o for o, t in z.objects.items() if t == 'igStringInsensitiveStringHashTable')
    cap = z.u32(ht + 0x10) // 8
    want = max(cap, 2 * n + 1)
    if want > cap:                                           # table agrandie (2 cases par entree au moins)
        cap = want
        for fo in (0x10, 0x20):                              # _values, _keys : memoires de cap * 8 octets
            blk = z.alloc(cap * 8, 16)
            struct.pack_into('<I', *z._loc(ht + fo), (z.u32(ht + fo) & 0xF8000000) | cap * 8)
            z.set_ptr(ht + fo + 8, blk)
    vals, keys = z.deref(ht + 0x18), z.deref(ht + 0x28)
    for i in range(cap):
        z.set_string_ref(vals + 8 * i, None)
        z.set_string_ref(keys + 8 * i, None)
    used = set()
    for name, ns, _ in dict.fromkeys(mats):
        key = f"{ns.split(',')[0]}.{name}"
        slot = fnv1a_lower(key) % cap
        while slot in used:                                  # case prise : la suivante
            slot = (slot + 1) % cap
        used.add(slot)
        z.set_string_ref(keys + 8 * slot, key)
        z.set_string_ref(vals + 8 * slot, f'{ns}.{name}')
    struct.pack_into('<I', *z._loc(z.find_field(ht, '_hashItemCount')[0]), len(used))
    return z.to_bytes()


def build_model(template, pos, nrm, uvs, tan, tris, model_name, material=None):
    """Octets du nouveau .igz. model_name : chemin logique sans extension, ex. 'Levels/Octane/Custom/Rampe'.

    material : None (celui du gabarit) ou (nom, espace de noms, chemin TDEP) d'un draw call au meme format de sommet."""
    if len(pos) > 0xFFFF:
        raise ValueError(f'{len(pos)} sommets : maximum 65535 (indices u16) — simplifier le modele')
    z = IgzFile(template)
    dcs = [o for o, t in z.objects.items() if t == 'igModelDrawCallData']
    if len(dcs) != 1:
        raise ValueError('le gabarit doit avoir un seul draw call')
    dc = dcs[0]
    md = next(o for o, t in z.objects.items() if t == 'igModelData')
    vb = z.deref(z.deref(dc + 0x48) + 0x20)
    ib = z.deref(z.deref(dc + 0x50) + 0x20)
    fmt = z.deref(vb + 0x30)
    if z.u32(fmt + 0x0C) != 40:
        raise ValueError('le gabarit doit avoir des sommets de 40 octets')
    # donnees GPU : sommets puis indices
    vdata = bytearray()
    for p, n, uv, t in zip(pos, nrm, uvs, tan):
        vdata += struct.pack('<3f3fHH3f', *p, *n, _half(uv[0]), _half(1.0 - uv[1]), *t)
    vdata += b'\0' * (-len(vdata) % 16)
    ioff = len(vdata)
    idx = [i for t in tris for i in t]
    idata = struct.pack(f'<{len(idx)}H', *idx)
    gpu = bytes(vdata) + idata
    sec = (z.deref(vb + 0x28) or 0) >> 27                     # section des donnees GPU
    z.data[sec] = bytearray(gpu + b'\0' * (-len(gpu) % 16))
    base = sec << 27

    def memref(off, size, data_off):
        flags = z.u32(off) & 0xF8000000
        struct.pack_into('<I', *z._loc(off), flags | size)
        z.set_ptr(off + 8, base | data_off)
    struct.pack_into('<I', *z._loc(vb + 0x0C), len(pos))
    struct.pack_into('<I', *z._loc(z.deref(vb + 0x18)), len(pos))
    memref(vb + 0x20, len(pos) * 40, 0)
    struct.pack_into('<I', *z._loc(ib + 0x0C), len(idx))
    struct.pack_into('<I', *z._loc(z.deref(ib + 0x18)), len(idx))
    memref(ib + 0x20, len(idx) * 2, ioff)
    lo = [min(p[k] for p in pos) for k in range(3)]
    hi = [max(p[k] for p in pos) for k in range(3)]
    for o, wmax in ((md, z.f32(md + 0x3C)), (dc, z.f32(dc + 0x3C))):
        struct.pack_into('<3f', *z._loc(o + 0x20), *lo)
        struct.pack_into('<3f', *z._loc(o + 0x30), *hi)
    igb = f'data/octane/models/{model_name}.igb'
    z.set_string_ref(md + 0x10, igb)
    z.set_string_ref(dc + 0x10, f'{igb} (0/1)')
    if material:
        set_material(z, *material)
    return z.to_bytes()
