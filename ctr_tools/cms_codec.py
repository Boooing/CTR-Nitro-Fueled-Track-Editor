"""Codec du hknpCompressedMeshShape (Havok 2014.1, CTR Nitro-Fueled) : lecture en primitives et re-encodage.

Structure (decodee et verifiee sur le sol de Crash Cove, voir README) :
  hknpCompressedMeshShape : +0x58 -> donnees ; +0x60 hkBitField quadIsFlat (mots, +0x70 nb bits) ;
      +0x78 hkBitField triangleIsInterior (mots, +0x88 nb bits)
  donnees : +0x10 arbre du haut (noeuds 5 o) ; +0x20/+0x30 domaine (w = -/+ rayon) ; +0x40 nb triangles,
      bits par cle, cle max ; +0x50 sections (0x60 o) ; +0x60 primitives (4 x u8) ; +0x70 indices partages (u16) ;
      +0x80 sommets compresses (u32 11/11/10) ; +0x90 sommets partages (u64 21/21/22, domaine) ;
      +0xa0 data runs (u16 valeur, u8 premier, u8 nombre) ; +0xb8 arbre SIMD (vide)
  section : +0x00 arbre (noeuds 4 o) ; +0x10/+0x20 domaine ; +0x30 codec (offset, echelle) ; +0x48 premier
      sommet compresse ; +0x4c (debut partages << 8 | nb compresses) ; +0x50 (debut << 8 | nb primitives) ;
      +0x54 (debut << 8 | nb runs) ; +0x58 nb compresses u8, nb partages u8, +0x5a indice de feuille u16
  noeud (5 o haut / 4 o section) : 3 octets de bornes relatives au parent (quartet haut : min += q^2/226 * etendue,
      bas : max -= q^2/226 * etendue) puis
      haut :    octet bit7 = interne ; valeur 15 bits ; interne : enfant droit = i + 2*valeur ; feuille : section
      section : impair = interne, enfant droit = i + 2*(d >> 1) ; pair = feuille, primitive = d >> 1
  cle de triangle = section << 8 | primitive << 1 | (0 premier triangle, 1 second du quad)
"""
import math
import struct
from dataclasses import dataclass, field

import progress

PACKED_MAX = (0x7FF, 0x7FF, 0x3FF)
SHARED_MAX = (0x1FFFFF, 0x1FFFFF, 0x3FFFFF)
MAX_PRIMS = 120          # <= 128 (7 bits dans la cle et dans les feuilles)
MAX_VERTS = 250          # indices u8 (compresses + partages)
MAX_EXTENT = (1e9, 1e9, 1e9)       # pas de limite de taille de section
# Tous les sommets en « partages » (21/21/22 bits sur le domaine du maillage : ~0,4 mm sur 1,4 km) plutot que
# compresses par section (11/11/10 bits : 5 a 13 cm sur des sections de 100 a 280 m) : precision et pas de fissure.
ALL_SHARED = True


@dataclass
class Prim:
    verts: list                  # 3 ou 4 points (repere du maillage)
    value: int                   # data run (surface)
    flat: bool = False           # quadIsFlat
    interior: tuple = (False, False)   # triangleIsInterior des deux triangles

    @property
    def is_quad(self):
        return len(self.verts) == 4

    def triangles(self):
        v = self.verts
        return [(v[0], v[1], v[2])] + ([(v[0], v[2], v[3])] if self.is_quad else [])


@dataclass
class Mesh:
    prims: list = field(default_factory=list)
    radius: float = 0.01         # rayon de convexite (w du domaine)


# ---------------------------------------------------------------------------------------------
def _bit(pf, words, idx):
    return bool(pf.u32(words + (idx >> 5) * 4) >> (idx & 31) & 1)


def read_mesh(pf, shape):
    """Primitives d'un hknpCompressedMeshShape (repere du maillage)."""
    d = pf.ptr(shape + 0x58)
    dlo, dhi = pf.floats(d + 0x20, 3), pf.floats(d + 0x30, 3)
    radius = pf.f32(d + 0x3c)
    sec_off, nsec = pf.array(d + 0x50)
    prim_off, _ = pf.array(d + 0x60)
    shidx_off, _ = pf.array(d + 0x70)
    packed_off, _ = pf.array(d + 0x80)
    shared_off, _ = pf.array(d + 0x90)
    runs_off, _ = pf.array(d + 0xa0)
    flat_w = pf.ptr(shape + 0x60)
    int_w = pf.ptr(shape + 0x78)
    ext = [dhi[k] - dlo[k] for k in range(3)]
    mesh = Mesh(radius=radius)
    for s in range(nsec):
        o = sec_off + s * 0x60
        codec = pf.floats(o + 0x30, 6)
        fp, shf, prf, drf = pf.u32(o + 0x48), pf.u32(o + 0x4c), pf.u32(o + 0x50), pf.u32(o + 0x54)
        npk, nsh = pf.u8(o + 0x58), pf.u8(o + 0x59)
        local = []
        for k in range(npk):
            v = pf.u32(packed_off + (fp + k) * 4)
            q = (v & 0x7FF, (v >> 11) & 0x7FF, v >> 22)
            local.append(tuple(codec[i] + codec[3 + i] * q[i] for i in range(3)))
        for k in range(nsh):
            g = pf.u16(shidx_off + ((shf >> 8) + k) * 2)
            v = pf.u64(shared_off + g * 8)
            q = (v & 0x1FFFFF, (v >> 21) & 0x1FFFFF, v >> 42)
            local.append(tuple(dlo[i] + ext[i] * q[i] / SHARED_MAX[i] for i in range(3)))
        values = {}
        for r in range(drf >> 8, (drf >> 8) + (drf & 0xFF)):
            run = pf.u32(runs_off + r * 4)
            for p in range((run >> 16) & 0xFF, ((run >> 16) & 0xFF) + (run >> 24)):
                values[p] = run & 0xFFFF
        for p in range(prf & 0xFF):
            a, b, c, dd = pf.data[prim_off + ((prf >> 8) + p) * 4:prim_off + ((prf >> 8) + p) * 4 + 4]
            key = s << 8 | p << 1
            verts = [local[a], local[b], local[c]] + ([local[dd]] if c != dd else [])
            mesh.prims.append(Prim(verts, values.get(p, 0), _bit(pf, flat_w, key >> 1) if flat_w else False,
                                   (_bit(pf, int_w, key) if int_w else False,
                                    _bit(pf, int_w, key | 1) if int_w else False)))
    return mesh


# ---------------------------------------------------------------------------------------------
def _quant_bounds(child, parent):
    """3 octets de bornes : quartets tels que la boite decodee contienne child (conservatif)."""
    out, dec_lo, dec_hi = [], [], []
    for k in range(3):
        ext = parent[1][k] - parent[0][k]
        if ext <= 0:
            out.append(0)
            dec_lo.append(parent[0][k]); dec_hi.append(parent[1][k])
            continue
        a = max(0.0, (child[0][k] - parent[0][k]) / ext * 226.0)
        b = max(0.0, (parent[1][k] - child[1][k]) / ext * 226.0)
        qa = min(15, int(math.floor(math.sqrt(a))))
        qb = min(15, int(math.floor(math.sqrt(b))))
        lo = parent[0][k] + qa * qa * ext / 226.0
        hi = parent[1][k] - qb * qb * ext / 226.0
        while lo > child[0][k] and qa > 0:          # securite flottante
            qa -= 1; lo = parent[0][k] + qa * qa * ext / 226.0
        while hi < child[1][k] and qb > 0:
            qb -= 1; hi = parent[1][k] - qb * qb * ext / 226.0
        out.append(qa << 4 | qb)
        dec_lo.append(lo); dec_hi.append(hi)
    return bytes(out), (dec_lo, dec_hi)


def _aabb(points):
    return ([min(p[k] for p in points) for k in range(3)], [max(p[k] for p in points) for k in range(3)])


def _union(boxes):
    return ([min(b[0][k] for b in boxes) for k in range(3)], [max(b[1][k] for b in boxes) for k in range(3)])


def _split(items, box_of):
    """Coupe une liste en deux selon l'axe le plus long des centres."""
    cs = [[(b[0][k] + b[1][k]) / 2 for k in range(3)] for b in map(box_of, items)]
    ax = max(range(3), key=lambda k: max(c[k] for c in cs) - min(c[k] for c in cs))
    order = sorted(range(len(items)), key=lambda j: cs[j][ax])
    h = len(items) // 2
    return [items[j] for j in order[:h]], [items[j] for j in order[h:]]


def _build_tree(leaves, box_of, root_box, node_size, encode_leaf, encode_internal):
    """Arbre binaire en profondeur : gauche = i+1, droite = i + 2*(feuilles a gauche). Renvoie (octets, {feuille: indice})."""
    nodes, where = [], {}
    box_of = {i: box_of(i) for i in leaves}.__getitem__      # boites calculees une seule fois

    def rec(items, parent_box, is_root):
        box = _union([box_of(i) for i in items])
        if is_root:
            q, dec = b'\0\0\0', parent_box
        else:
            q, dec = _quant_bounds(box, parent_box)
        idx = len(nodes)
        nodes.append(None)
        if len(items) == 1:
            nodes[idx] = q + encode_leaf(items[0])
            where[items[0]] = idx
            return
        left, right = _split(items, box_of)
        rec(left, dec, False)
        nodes[idx] = q + encode_internal(len(left))    # enfant droit a i + 2*len(left)
        rec(right, dec, False)
    rec(list(leaves), root_box, True)
    return b''.join(nodes), where


def _quantize(v, lo, ext, maxq):
    return tuple(min(maxq[k], max(0, int(round((v[k] - lo[k]) / ext[k] * maxq[k])))) if ext[k] > 0 else 0
                 for k in range(3))


def encode_mesh(mesh):
    """Encode un Mesh -> dict de tableaux binaires + valeurs scalaires (voir write_mesh)."""
    prims = mesh.prims
    allv = [v for p in prims for v in p.verts]
    dlo, dhi = _aabb(allv)
    ext = [max(dhi[k] - dlo[k], 1e-6) for k in range(3)]
    box_of_prim = [_aabb(p.verts) for p in prims].__getitem__

    # 1) sections : decoupe spatiale jusqu'a MAX_PRIMS primitives et MAX_VERTS sommets
    progress.step(f'encodage de la collision : découpage de {len(prims)} primitives')

    def vkey(v):
        return (round(v[0], 4), round(v[1], 4), round(v[2], 4))
    pkeys = [[vkey(v) for v in p.verts] for p in prims]
    groups, stack = [], [list(range(len(prims)))]
    while stack:
        g = stack.pop()
        nverts = len({k for i in g for k in pkeys[i]})
        gb = _union([box_of_prim(i) for i in g])
        small = all(gb[1][k] - gb[0][k] <= MAX_EXTENT[k] for k in range(3))
        if len(g) <= MAX_PRIMS and nverts <= MAX_VERTS and (small or len(g) == 1):
            groups.append(g)
        else:
            a, b = _split(g, box_of_prim)
            stack += [b, a]
    # 2) sommets partages = utilises par plusieurs sections (evite les fissures entre sections)
    users = {}
    for si, g in enumerate(groups):
        for i in g:
            for k in pkeys[i]:
                users.setdefault(k, set()).add(si)
    # indices des sommets partages en u16 : au-dela de 65 535 sommets, seuls ceux communs a plusieurs sections
    # restent partages, les autres sont compresses dans leur section (11/11/10 bits sur la boite de la section,
    # comme le sol d'origine du jeu)
    all_shared = ALL_SHARED and len(users) <= 0xFFFF
    shared_keys = sorted(k for k, s in users.items() if all_shared or len(s) > 1)
    if len(shared_keys) > 0xFFFF:
        raise ValueError(f'collision trop detaillee : {len(shared_keys)} sommets communs a plusieurs sections '
                         f'(65 535 au plus) — retirer la collision du decor qui n\'est pas roulable')
    shared_index = {k: n for n, k in enumerate(shared_keys)}
    shared_pos = {}
    for g in groups:
        for i in g:
            for v in prims[i].verts:
                if vkey(v) in shared_index:
                    shared_pos[vkey(v)] = v
    shared_bin = bytearray()
    for k in shared_keys:
        q = _quantize(shared_pos[k], dlo, ext, SHARED_MAX)
        shared_bin += struct.pack('<Q', q[0] | q[1] << 21 | q[2] << 42)
    shared_dec = {k: tuple(dlo[j] + ext[j] * _quantize(shared_pos[k], dlo, ext, SHARED_MAX)[j] / SHARED_MAX[j]
                           for j in range(3)) for k in shared_keys}

    sections, packed_bin, shidx_bin, prim_bin, runs_bin = [], bytearray(), bytearray(), bytearray(), bytearray()
    sec_trees, flat_bits, int_bits, n_tris, max_key = [], set(), set(), 0, 0
    for si, g in enumerate(progress.items(groups, 'encodage de la collision : section {i} / {n}')):
        # sommets de la section
        pk, sh = [], []
        for i in g:
            for v in prims[i].verts:
                k = vkey(v)
                lst = sh if k in shared_index else pk
                if k not in [x[0] for x in lst]:
                    lst.append((k, v))
        if pk:
            plo, phi = _aabb([v for _, v in pk])
            sc = [max(phi[k] - plo[k], 1e-6) / PACKED_MAX[k] for k in range(3)]
        else:
            plo, sc = list(dlo), [1e-6] * 3
        local_index, dec_points = {}, []
        first_packed = len(packed_bin) // 4
        for n, (k, v) in enumerate(pk):
            q = tuple(min(PACKED_MAX[j], max(0, int(round((v[j] - plo[j]) / sc[j])))) for j in range(3))
            packed_bin += struct.pack('<I', q[0] | q[1] << 11 | q[2] << 22)
            local_index[k] = n
            dec_points.append(tuple(plo[j] + sc[j] * q[j] for j in range(3)))
        first_shared = len(shidx_bin) // 2
        for n, (k, v) in enumerate(sh):
            shidx_bin += struct.pack('<H', shared_index[k])
            local_index[k] = len(pk) + n
            dec_points.append(shared_dec[k])
        slo, shi = _aabb(dec_points)
        # primitives + runs
        first_prim = len(prim_bin) // 4
        first_run = len(runs_bin) // 4
        local_prims = []
        for p_local, i in enumerate(g):
            p = prims[i]
            idx = [local_index[vkey(v)] for v in p.verts]
            if len(idx) == 3:
                idx.append(idx[2])
            prim_bin += bytes(idx)
            key = si << 8 | p_local << 1
            n_tris += 2 if p.is_quad else 1
            max_key = max(max_key, key | (1 if p.is_quad else 0))
            if p.flat:
                flat_bits.add(key >> 1)
            if p.interior[0]:
                int_bits.add(key)
            if p.is_quad and p.interior[1]:
                int_bits.add(key | 1)
            local_prims.append(p_local)
        run_start = 0
        for p_local in range(1, len(g) + 1):
            if p_local == len(g) or prims[g[p_local]].value != prims[g[run_start]].value:
                runs_bin += struct.pack('<HBB', prims[g[run_start]].value, run_start, p_local - run_start)
                run_start = p_local
        nruns = len(runs_bin) // 4 - first_run
        # arbre de la section (feuille = primitive locale)
        dec_prim_box = lambda pl: _aabb([dec_points[local_index[k]] for k in pkeys[g[pl]]])
        tree, _ = _build_tree(local_prims, dec_prim_box, (slo, shi), 4,
                              lambda pl: bytes([pl << 1]), lambda nleft: bytes([(nleft << 1) | 1]))
        sec_trees.append(tree)
        sections.append({'lo': slo, 'hi': shi, 'codec': list(plo) + list(sc), 'fp': first_packed,
                         'sh': first_shared << 8 | len(pk), 'pr': first_prim << 8 | len(g),
                         'dr': first_run << 8 | nruns, 'np': len(pk), 'ns': len(sh)})
    # 3) arbre du haut (feuille = section)
    dlo_q, dhi_q = list(dlo), list(dhi)
    top_tree, leaf_of = _build_tree(list(range(len(sections))), lambda s: (sections[s]['lo'], sections[s]['hi']),
                                    (dlo_q, dhi_q), 5,
                                    lambda s: bytes([(s >> 8) & 0x7F, s & 0xFF]),
                                    lambda nleft: bytes([0x80 | ((nleft >> 8) & 0x7F), nleft & 0xFF]))
    for s, sec in enumerate(sections):
        sec['leaf'] = leaf_of[s]
    bits_per_key = max(1, max_key.bit_length())

    def bitfield(bits, nbits):
        words = [0] * ((nbits + 31) // 32)
        for b in bits:
            words[b >> 5] |= 1 << (b & 31)
        return struct.pack(f'<{len(words)}I', *words), nbits
    return {
        'domain': (dlo, dhi), 'radius': mesh.radius, 'sections': sections, 'section_trees': sec_trees,
        'n_top_nodes': len(top_tree) // 5,
        'top_tree': top_tree, 'prims': bytes(prim_bin), 'shared_index': bytes(shidx_bin),
        'packed': bytes(packed_bin), 'shared': bytes(shared_bin), 'runs': bytes(runs_bin),
        'num_tris': n_tris, 'bits_per_key': bits_per_key, 'max_key': max_key,
        'quad_is_flat': bitfield(flat_bits, (max_key >> 1) + 1),
        'triangle_is_interior': bitfield(int_bits, max_key + 1),
    }


def write_mesh(writer, shape, enc):
    """Remplace le contenu d'un hknpCompressedMeshShape (PackfileWriter, offset de la forme) par enc."""
    pf = writer.pf
    d = pf.ptr(shape + 0x58)
    # arbre du haut, domaine, cles
    writer.set_array(d + 0x10, enc['top_tree'], enc['n_top_nodes'])
    lo, hi = enc['domain']
    writer.write(d + 0x20, struct.pack('<4f', *lo, -enc['radius']))
    writer.write(d + 0x30, struct.pack('<4f', *hi, enc['radius']))
    writer.write(d + 0x40, struct.pack('<IIII', enc['num_tris'], enc['bits_per_key'], enc['max_key'], 0))
    # arbres de section (ajoutes avant le tableau des sections qui les reference)
    tree_offs = [writer.append(t, 16) for t in enc['section_trees']]
    blob = bytearray()
    for s in enc['sections']:
        e = bytearray(0x60)
        struct.pack_into('<4f', e, 0x10, *s['lo'], -enc['radius'])
        struct.pack_into('<4f', e, 0x20, *s['hi'], enc['radius'])
        struct.pack_into('<6f', e, 0x30, *s['codec'])
        struct.pack_into('<IIIIBBH', e, 0x48, s['fp'], s['sh'], s['pr'], s['dr'], s['np'], s['ns'], s['leaf'])
        blob += e
    secs = len(enc['sections'])
    writer.set_array(d + 0x50, bytes(blob), secs)
    sec_base = writer.local[writer._local_index[d + 0x50]][1]
    for i, (s, toff) in enumerate(zip(enc['sections'], tree_offs)):
        n = len(enc['section_trees'][i]) // 4
        writer.set_pointer(sec_base + i * 0x60, toff)
        struct.pack_into('<iI', writer.data, sec_base + i * 0x60 + 8, n, n | 0x80000000)
    writer.set_array(d + 0x60, enc['prims'], len(enc['prims']) // 4)
    writer.set_array(d + 0x70, enc['shared_index'], len(enc['shared_index']) // 2)
    writer.set_array(d + 0x80, enc['packed'], len(enc['packed']) // 4)
    writer.set_array(d + 0x90, enc['shared'], len(enc['shared']) // 8)
    writer.set_array(d + 0xa0, enc['runs'], len(enc['runs']) // 4)
    # forme : nombre de bits de cle, champs de bits
    writer.write(shape + 0x12, bytes([enc['bits_per_key']]))
    for field, (words, nbits) in ((0x60, enc['quad_is_flat']), (0x78, enc['triangle_is_interior'])):
        writer.set_array(shape + field, words, len(words) // 4)
        writer.write(shape + field + 0x10, struct.pack('<i', nbits))
