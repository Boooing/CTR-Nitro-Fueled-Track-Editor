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
import collections
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
    # (2026-11-17) variables locales, memes expressions dans le meme ordre : resultats identiques, plus rapide
    out, dec_lo, dec_hi = [], [], []
    sqrt, floor = math.sqrt, math.floor
    for p0, p1, c0, c1 in zip(parent[0], parent[1], child[0], child[1]):
        ext = p1 - p0
        if ext <= 0:
            out.append(0)
            dec_lo.append(p0); dec_hi.append(p1)
            continue
        a = (c0 - p0) / ext * 226.0
        b = (p1 - c1) / ext * 226.0
        qa = min(15, int(floor(sqrt(a)))) if a > 0.0 else 0
        qb = min(15, int(floor(sqrt(b)))) if b > 0.0 else 0
        lo = p0 + qa * qa * ext / 226.0
        hi = p1 - qb * qb * ext / 226.0
        while lo > c0 and qa > 0:                   # securite flottante
            qa -= 1; lo = p0 + qa * qa * ext / 226.0
        while hi < c1 and qb > 0:
            qb -= 1; hi = p1 - qb * qb * ext / 226.0
        out.append(qa << 4 | qb)
        dec_lo.append(lo); dec_hi.append(hi)
    return bytes(out), (dec_lo, dec_hi)


# (2026-11-17) min / max / tri par colonnes (zip) au lieu d'un parcours par axe : memes valeurs, memes egalites
# departagees (tri stable, 1er axe le plus long), donc fichier identique a l'octet ; encodage ~3 fois plus rapide
def _aabb(points):
    cols = list(zip(*points))[:3]
    return [min(c) for c in cols], [max(c) for c in cols]


def _union(boxes):
    return ([min(c) for c in zip(*[b[0] for b in boxes])], [max(c) for c in zip(*[b[1] for b in boxes])])


def _center(b):
    return [(b[0][k] + b[1][k]) / 2 for k in range(3)]


def _split(items, box_of, h=None, center_of=None):
    """Coupe une liste en deux selon l'axe le plus long des centres (h : taille de la 1re partie, defaut moitie).
    center_of : centres deja calcules (sinon tires de box_of)."""
    cs = [center_of(i) for i in items] if center_of else [_center(box_of(i)) for i in items]
    cols = list(zip(*cs))
    spans = [max(c) - min(c) for c in cols]
    ax = max(range(3), key=spans.__getitem__)
    order = sorted(range(len(items)), key=cols[ax].__getitem__)
    if h is None:
        h = len(items) // 2
    return [items[j] for j in order[:h]], [items[j] for j in order[h:]]


def _section_cut(n, cap=MAX_PRIMS):
    """Coupe d'un groupe trop grand en sections pleines (2026-11-07) : la 1re partie = un multiple de `cap` proche
    de la moitie, au lieu de la moitie exacte (sections remplies a ~75 % en moyenne : 32 791 sections sur une carte
    de ~2,9 M primitives, au-dela des 32 767 du format ; pleines, ~25 % de sections en moins)."""
    k = -(-n // cap)                             # nombre minimal de sections
    return (k // 2) * cap if k >= 2 else n // 2


def _sections(prims, pkeys, box_of_prim, cap, full=False):
    """Decoupe spatiale jusqu'a `cap` primitives et MAX_VERTS sommets par section. full : sections pleines (moins
    nombreuses mais plus etendues, donc sommets compresses un peu moins precis : ~2,2 cm au lieu de ~1,2 sur la route)."""
    groups, stack = [], [list(range(len(prims)))]
    centers = [_center(box_of_prim(i)) for i in range(len(prims))]
    C = None
    if len(prims) >= BIG_SPLIT:
        import numpy as np
        C = np.array(centers, dtype=np.float64)              # memes valeurs (float Python = float64)
    while stack:
        g = stack.pop()
        # sommets et etendue comptes seulement pour un groupe assez petit (un gros groupe est coupe de toute facon) :
        # le comptage sur les 272 000 primitives d'une grande carte prenait la moitie du decoupage
        keep = False
        if len(g) <= cap and len({k for i in g for k in pkeys[i]}) <= MAX_VERTS:
            gb = _union([box_of_prim(i) for i in g])
            keep = len(g) == 1 or all(gb[1][k] - gb[0][k] <= MAX_EXTENT[k] for k in range(3))
        if keep:
            groups.append(g)
        else:
            h = _section_cut(len(g), cap) if full and len(g) > cap else None
            if C is not None and len(g) >= BIG_SPLIT:
                a, b = _split_np(g, C, h)
            else:
                a, b = _split(g, box_of_prim, h, center_of=centers.__getitem__)
            stack += [b, a]
    return groups


# gros groupes (debut du decoupage d'une grande carte) : meme coupe que _split, en numpy (2026-11-17)
BIG_SPLIT = 4096


def _split_np(items, C, h=None):
    """_split pour un gros groupe : etendue des centres par axe (1er axe le plus long en cas d'egalite, comme max()),
    tri STABLE sur cet axe (egalites dans l'ordre de la liste, comme sorted()) -> meme coupe a l'identique."""
    import numpy as np
    idx = np.asarray(items)
    c = C[idx]
    spans = (c.max(0) - c.min(0)).tolist()
    ax = max(range(3), key=spans.__getitem__)
    order = np.argsort(c[:, ax], kind='stable')
    if h is None:
        h = len(items) // 2
    o = idx[order].tolist()
    return o[:h], o[h:]


def _build_tree(leaves, box_of, root_box, node_size, encode_leaf, encode_internal):
    """Arbre binaire en profondeur : gauche = i+1, droite = i + 2*(feuilles a gauche). Renvoie (octets, {feuille: indice})."""
    nodes, where = [], {}
    boxes = {i: box_of(i) for i in leaves}                    # boites et centres calcules une seule fois
    box_of = boxes.__getitem__
    center_of = {i: _center(b) for i, b in boxes.items()}.__getitem__

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
        left, right = _split(items, box_of, center_of=center_of)
        rec(left, dec, False)
        nodes[idx] = q + encode_internal(len(left))    # enfant droit a i + 2*len(left)
        rec(right, dec, False)
    rec(list(leaves), root_box, True)
    return b''.join(nodes), where


def _quantize(v, lo, ext, maxq):
    return tuple(min(maxq[k], max(0, int(round((v[k] - lo[k]) / ext[k] * maxq[k])))) if ext[k] > 0 else 0
                 for k in range(3))


def _shared_priority(prims, pkeys, ext):
    """{sommet: (0 si une primitive plate l'utilise, sinon 1 ; plus petite arete)} : plus c'est petit, plus une fissure
    s'y verrait sous les roues. Le haut est l'axe le moins etendu du maillage (une piste est plus large que haute)."""
    up = min(range(3), key=lambda k: ext[k])
    score = {}
    for p, keys in zip(prims, pkeys):
        a, b, c = p.verts[:3]
        u = [b[k] - a[k] for k in range(3)]
        w = [c[k] - a[k] for k in range(3)]
        n = (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])
        flat = abs(n[up]) >= 0.7 * (math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]) or 1.0)
        v = p.verts
        edge = max(math.dist(v[i], v[(i + 1) % len(v)]) for i in range(len(v)))
        s = (0 if flat else 1, round(edge, 2))
        for k in keys:
            if k not in score or s < score[k]:
                score[k] = s
    return score


def _encode_section(sec, shared, dlo):
    """Une section : sec = [(sommets, surface, cles des sommets)] de ses primitives, shared = {cle: (indice partage,
    position decodee)} des sommets partages qu'elle utilise. Tout est local a la section (meme code qu'avant le
    decoupage en taches) ; les debuts dans les tableaux communs sont ajoutes a l'assemblage (encode_mesh)."""
    # sommets de la section (ensemble des deja vus : meme ordre d'ajout que la liste reconstruite d'avant)
    pk, sh, seen = [], [], set()
    for verts, _, keys in sec:
        for v, k in zip(verts, keys):
            if k not in seen:
                seen.add(k)
                (sh if k in shared else pk).append((k, v))
    if pk:
        plo, phi = _aabb([v for _, v in pk])
        sc = [max(phi[k] - plo[k], 1e-6) / PACKED_MAX[k] for k in range(3)]
    else:
        plo, sc = list(dlo), [1e-6] * 3
    local_index, dec_points = {}, []
    packed, shidx, prim_bin, runs = bytearray(), bytearray(), bytearray(), bytearray()
    for n, (k, v) in enumerate(pk):
        q = tuple(min(PACKED_MAX[j], max(0, int(round((v[j] - plo[j]) / sc[j])))) for j in range(3))
        packed += struct.pack('<I', q[0] | q[1] << 11 | q[2] << 22)
        local_index[k] = n
        dec_points.append(tuple(plo[j] + sc[j] * q[j] for j in range(3)))
    for n, (k, v) in enumerate(sh):
        shidx += struct.pack('<H', shared[k][0])
        local_index[k] = len(pk) + n
        dec_points.append(shared[k][1])
    slo, shi = _aabb(dec_points)
    for _, _, keys in sec:
        idx = [local_index[k] for k in keys]
        if len(idx) == 3:
            idx.append(idx[2])
        prim_bin += bytes(idx)
    run_start, nruns = 0, 0
    for p_local in range(1, len(sec) + 1):
        if p_local == len(sec) or sec[p_local][1] != sec[run_start][1]:
            runs += struct.pack('<HBB', sec[run_start][1], run_start, p_local - run_start)
            run_start = p_local
            nruns += 1
    # arbre de la section (feuille = primitive locale)
    dec_prim_box = lambda pl: _aabb([dec_points[local_index[k]] for k in sec[pl][2]])
    tree, _ = _build_tree(list(range(len(sec))), dec_prim_box, (slo, shi), 4,
                          lambda pl: bytes([pl << 1]), lambda nleft: bytes([(nleft << 1) | 1]))
    return {'packed': bytes(packed), 'shidx': bytes(shidx), 'prims': bytes(prim_bin), 'runs': bytes(runs),
            'nruns': nruns, 'tree': tree, 'lo': slo, 'hi': shi, 'codec': list(plo) + list(sc),
            'np': len(pk), 'ns': len(sh)}


def _encode_batch(batch, dlo):
    """Tache d'un processus de calcul : plusieurs sections a la suite."""
    return [_encode_section(sec, shared, dlo) for sec, shared in batch]


# Calcul en parallele (2026-11-17, demande utilisateur : enregistrements et generation plus rapides). Python ne
# calcule qu'un fil a la fois (GIL) : des PROCESSUS, crees une fois et reutilises (le lancement coute ~1 s chacun).
# Petites collisions : sur place (le lancement couterait plus que le calcul). Toute erreur du parallele (processus
# refuses, exe sans freeze_support...) : on refait sur place, meme resultat.
PARALLEL_MIN_SECTIONS = 256
_pool = None


def _workers():
    import os
    return max(1, min(8, (os.cpu_count() or 2) - 1))


def _get_pool():
    global _pool
    if _pool is None:
        import concurrent.futures
        import multiprocessing
        _pool = concurrent.futures.ProcessPoolExecutor(_workers(), mp_context=multiprocessing.get_context('spawn'))
    return _pool


def _encode_all(groups, section_input, dlo):
    """Resultats de _encode_section pour chaque groupe, dans l'ordre."""
    global _pool
    n = len(groups)
    if n >= PARALLEL_MIN_SECTIONS and _workers() > 1:
        try:
            pool = _get_pool()
            size = max(16, -(-n // (_workers() * 6)))             # ~6 lots par processus : charge equilibree
            futures = [pool.submit(_encode_batch, [section_input(g) for g in groups[a:a + size]], dlo)
                       for a in range(0, n, size)]
            out = []
            for f in futures:
                out += f.result()
                progress.step(f'encodage de la collision : section {len(out)} / {n}', len(out) / n)
            return out
        except Exception as e:  # noqa: BLE001 - repli sur place, meme resultat
            print(f'encodage de la collision en parallele impossible ({e!r}) : calcul sur place', flush=True)
            _pool = None
    return [_encode_section(*section_input(g), dlo)
            for g in progress.items(groups, 'encodage de la collision : section {i} / {n}')]


# memoire des encodages (2026-11-18) : la collision est faite de plusieurs maillages (15 sur T922) ; deplacer UN objet
# n'en change qu'un ou deux -> les autres reprennent leur encodage precedent (cle = empreinte des primitives et du
# rayon ; sortie identique a un encodage complet). 14,1 s -> voir pending-ingame-tests 118.
_ENC_MEMO = collections.OrderedDict()
ENC_MEMO_MAX = 48


def mesh_key(mesh):
    """Empreinte du contenu d'un Mesh (sommets, surface, drapeaux, rayon)."""
    import hashlib
    from array import array
    h = hashlib.blake2b(digest_size=20)
    h.update(struct.pack('<d', float(mesh.radius)))
    coords, meta = array('d'), array('i')
    for p in mesh.prims:
        coords.extend(c for v in p.verts for c in v)
        meta.extend((len(p.verts), int(p.value), int(bool(p.flat)), int(bool(p.interior[0])), int(bool(p.interior[1]))))
    h.update(coords.tobytes())
    h.update(meta.tobytes())
    return h.hexdigest()


def encode_mesh(mesh):
    """Encode un Mesh -> dict de tableaux binaires + valeurs scalaires (voir write_mesh). Resultat garde en memoire
    (_ENC_MEMO) : un maillage inchange n'est pas reencode. Le dict rendu ne doit pas etre modifie."""
    key = mesh_key(mesh)
    if key in _ENC_MEMO:
        _ENC_MEMO.move_to_end(key)
        progress.step(f'encodage de la collision : {len(mesh.prims)} primitives inchangées (reprises)')
        return _ENC_MEMO[key]
    enc = _encode_mesh(mesh)
    _ENC_MEMO[key] = enc
    while len(_ENC_MEMO) > ENC_MEMO_MAX:
        _ENC_MEMO.popitem(last=False)
    return enc


def _encode_mesh(mesh):
    """Encodage complet d'un Mesh (voir encode_mesh)."""
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
    groups = _sections(prims, pkeys, box_of_prim, MAX_PRIMS)
    # carte enorme (2026-11-07, T901 : 32 791 sections) : sections pleines, puis de 127 primitives (maximum des cles)
    for cap in (MAX_PRIMS, 127):
        if len(groups) <= 0x7FFF:
            break
        progress.step(f'encodage de la collision : {len(groups)} sections, nouveau découpage plus serré')
        groups = _sections(prims, pkeys, box_of_prim, cap, full=True)
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
        # piste longue : encore trop de sommets communs -> les 65 535 ou une fissure compterait le plus restent partages
        # (surfaces plates a maille fine : la route), les autres sont compresses dans chacune de leurs sections : quelques
        # cm d'ecart possibles au raccord de deux sections de sol ou de mur, sans detail perdu
        score = _shared_priority(prims, pkeys, ext)
        shared_keys = sorted(sorted(shared_keys, key=lambda k: (score[k], k))[:0xFFFF])
    if len(groups) > 0x7FFF:
        raise ValueError(f'collision trop grande : {len(groups)} sections, le format en autorise 32 767 '
                         f'(environ 3,9 millions de triangles)')
    shared_index = {k: n for n, k in enumerate(shared_keys)}
    shared_pos = {}
    for g in groups:
        for i in g:
            for v, k in zip(prims[i].verts, pkeys[i]):       # cles deja calculees (pkeys) : memes valeurs que vkey(v)
                if k in shared_index:
                    shared_pos[k] = v
    shared_bin, shared_dec = bytearray(), {}
    for k in shared_keys:                                # quantifie une seule fois (avant : deux fois, meme valeur)
        q = _quantize(shared_pos[k], dlo, ext, SHARED_MAX)
        shared_bin += struct.pack('<Q', q[0] | q[1] << 21 | q[2] << 42)
        shared_dec[k] = tuple(dlo[j] + ext[j] * q[j] / SHARED_MAX[j] for j in range(3))

    # sections encodees une par une (_encode_section), en parallele sur une grande carte (2026-11-17), puis assemblees
    # dans l'ordre : les debuts dans les tableaux communs et les cles (section << 8 | primitive << 1) se calculent ici
    def section_input(g):
        used = {k for i in g for k in pkeys[i] if k in shared_index}
        return ([(prims[i].verts, prims[i].value, pkeys[i]) for i in g],
                {k: (shared_index[k], shared_dec[k]) for k in used})
    results = _encode_all(groups, section_input, list(dlo))

    sections, packed_bin, shidx_bin, prim_bin, runs_bin = [], bytearray(), bytearray(), bytearray(), bytearray()
    sec_trees, flat_bits, int_bits, n_tris, max_key = [], set(), set(), 0, 0
    for si, (g, r) in enumerate(zip(groups, results)):
        first_packed, first_shared = len(packed_bin) // 4, len(shidx_bin) // 2
        first_prim, first_run = len(prim_bin) // 4, len(runs_bin) // 4
        packed_bin += r['packed']; shidx_bin += r['shidx']; prim_bin += r['prims']; runs_bin += r['runs']
        for p_local, i in enumerate(g):
            p = prims[i]
            key = si << 8 | p_local << 1
            n_tris += 2 if p.is_quad else 1
            max_key = max(max_key, key | (1 if p.is_quad else 0))
            if p.flat:
                flat_bits.add(key >> 1)
            if p.interior[0]:
                int_bits.add(key)
            if p.is_quad and p.interior[1]:
                int_bits.add(key | 1)
        sec_trees.append(r['tree'])
        sections.append({'lo': r['lo'], 'hi': r['hi'], 'codec': r['codec'], 'fp': first_packed,
                         'sh': first_shared << 8 | r['np'], 'pr': first_prim << 8 | len(g),
                         'dr': first_run << 8 | r['nruns'], 'np': r['np'], 'ns': r['ns']})
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
