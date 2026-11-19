"""Apercu texture dans l'editeur : geometrie avec UV et texture couleur par draw call, textures decodees en RGBA.

  model_preview(octets_modele, lire) -> {'positions', 'uvs', 'indices',
                                         'groups': [(debut, nb, (espace de noms de la texture, decal ?) | None)]}
  decode_texture(octets_texture, max_size) -> (rgba (h, w, 4) uint8, a_de_la_transparence)
`lire(logique)` rend les octets d'un fichier (materiau ou texture) ou None. Les draw calls doubles (passe d'ombre,
variante : meme nombre de triangles et meme boite) sont ignores comme dans decor.model_mesh.
"""
import math
import struct

import numpy as np

from igz import IgzFile
from model_build import tdep_entries
from texture_build import LUT, level_size, texture_info

FORMATS = {'833431f8': 'bc1', 'cf76b9f0': 'bc3'}      # 4 premiers octets de l'EXID des textures couleur


def material_color_texture(material_bytes, material_name):
    """(espace de noms de la texture « ColorMap », decal ?) du materiau `material_name` d'un fichier
    materialinstances. Decal = effet GBufferDecal (fondu sur le terrain en jeu)."""
    z = IgzFile(material_bytes)
    names = dict(z.root_objects())
    mats = [names[material_name]] if material_name in names else \
        [o for o, t in z.objects.items() if t == 'igGraphicsMaterial'][:1]
    for m in mats:
        decal = False
        try:
            v = z.u32(z.find_field(m, '_effectHandle')[0])
            decal = bool(v & 0x80000000) and 'decal' in z.ext_names[v & 0x7FFFFFFF][1].lower()
        except KeyError:
            pass
        for o in sorted(z.reachable(m)[0]):
            if z.objects[o] != 'igGraphicsTexture':
                continue
            v = z.u32(z.find_field(o, '_imageHandle')[0])
            if v & 0x80000000:
                ns = z.ext_names[v & 0x7FFFFFFF][1]
                if ns.startswith('ColorMap,'):
                    return ns, decal
    return None


def _quat_rows(x, y, z, w):
    """Matrice 3x3 d'un quaternion (x, y, z, w) des pieces de modele, a utiliser en v' = v @ R. Releve sur
    T232_Pipe_01_RotatingHandle (bornes du jeu) : c'est la matrice « colonnes » habituelle prise telle quelle, donc la
    rotation inverse de la convention lignes."""
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def model_transforms(z, md):
    """Pieces d'un modele (2026-11-18) : igModelData +0x40 liste des igAnimatedTransform, +0x58 parents (rang + 1, 0 =
    racine), +0x88 transformation de chaque appel de dessin (rang + 1, 0 = aucune). Une piece = matrice fixe (+0x20,
    convention lignes) ou source animee (+0x60 igAnimatedTransformSource : +0x10 nombre de valeurs, +0x18 valeurs,
    +0x28 nombre de cles ; +0x48 canaux 1 rotation (quaternion), 2 translation, 8 echelle ; +0x4C rangs : octet 0
    translation, 2 echelle, rotation en 0). Le jeu les applique (cartes de Hot Air Skyway montees de 6 m, kart des
    statues sur leur socle...) ; l'apercu les ignorait -> objets poses « au sol » dans l'editeur, en l'air en jeu.
    -> [matrice 4x4 monde a l'instant 0 | None] par appel de dessin (ordre de la liste +0x70), ou None si aucune."""
    n = z.u32(md + 0x40)
    lp = z.deref(md + 0x50) if n else None
    ip = z.deref(md + 0x98)
    if not n or lp is None or ip is None:
        return None
    local = []
    for i in range(n):
        t = z.deref(lp + i * 8)
        M = np.eye(4)
        if t is not None and z.objects.get(t) == 'igAnimatedTransform':
            M = np.array(struct.unpack_from('<16f', *z._loc(t + 0x20)), np.float64).reshape(4, 4)
            s = z.deref(t + 0x60) if z.is_ptr(t + 0x60) else None
            if s is not None and z.objects.get(s) == 'igAnimatedTransformSource':
                cnt, nkeys = z.u32(s + 0x10), z.u32(s + 0x28)
                mem, size = z.memory_ref(s + 0x18)
                stride = cnt // max(nkeys, 1)
                if mem is not None and stride and size >= stride * 4:
                    b, o = z._loc(mem)
                    k = struct.unpack_from(f'<{stride}f', b, o)               # 1re cle
                    ch, offs = z.u32(s + 0x48), z.u32(s + 0x4C)
                    to, so = offs & 0xFF, (offs >> 16) & 0xFF
                    S = np.diag(list(k[so:so + 3]) + [1.0]) if ch & 8 and so + 3 <= stride else np.eye(4)
                    R = np.eye(4)
                    if ch & 1 and stride >= 4:
                        R[:3, :3] = _quat_rows(*k[0:4])
                    T = np.eye(4)
                    if ch & 2 and to + 3 <= stride:
                        T[3, :3] = k[to:to + 3]
                    M = S @ R @ T
        local.append(M)
    hp = z.deref(md + 0x68)
    parents = [struct.unpack_from('<i', *z._loc(hp + 4 * i))[0] - 1 for i in range(min(n, z.u32(md + 0x58)))] if hp is not None else []
    world = [None] * n

    def get(i, depth=0):
        if world[i] is None:
            p = parents[i] if i < len(parents) else -1
            # enfant puis parent (convention lignes) ; l'ordre inverse donnait de moins bonnes bornes (167 / 174 modeles)
            world[i] = local[i] @ get(p, depth + 1) if 0 <= p < n and p != i and depth < 64 else local[i]
        return world[i]
    nd = z.u32(md + 0x88)
    out = []
    for d in range(nd):
        k = struct.unpack_from('<i', *z._loc(ip + 4 * d))[0]
        out.append(get(k - 1) if 1 <= k <= n else None)
    return out


def model_preview(data, read):
    z = IgzFile(data)
    deps = dict(tdep_entries(z))
    pos, uvs, idx, groups, seen = [], [], [], [], set()
    joints, weights = [], []                               # skin d'acteur : os (index de matrice) et poids par sommet
    mat_cache = {}
    nverts = 0
    # palette commune des skins : igModelData +0xb8 nombre, +0xc0 bloc (int32 : index de matrice du squelette)
    palette = None
    md = next((o for o, t in z.objects.items() if t == 'igModelData'), None)
    if md is not None and z.size_of('igModelData') >= 0xd0:
        try:
            pm, ps = z.memory_ref(md + 0xc0)
            if pm is not None and ps:
                pb, po = z._loc(pm)
                palette = np.frombuffer(bytes(pb[po:po + ps]), np.int32).copy()
        except Exception:  # noqa: BLE001 - pas de palette : modele sans os
            palette = None
    # pieces du modele (model_transforms) : matrice de chaque appel de dessin, comme en jeu
    dc_mat = {}
    if md is not None:
        try:
            mats = model_transforms(z, md)
            dp = z.deref(md + 0x80)
            if mats and dp is not None:
                for i, m in enumerate(mats):
                    d = z.deref(dp + 8 * i)
                    if d is not None and m is not None and not np.allclose(m, np.eye(4)):
                        dc_mat[d] = m
        except Exception:  # noqa: BLE001 - pieces illisibles : apercu brut
            dc_mat = {}
    for o, t in sorted(z.objects.items()):
        if t != 'igModelDrawCallData':
            continue
        gvb, gib = z.deref(o + 0x48), z.deref(o + 0x50)
        if gvb is None or gib is None:
            continue
        vb, ib = z.deref(gvb + 0x20), z.deref(gib + 0x20)
        ni = z.u32(ib + 0x0C)
        key = (ni, tuple(round(c, 1) for c in struct.unpack_from('<6f', *z._loc(o + 0x20))))
        if key in seen:
            continue
        seen.add(key)
        nv = z.u32(vb + 0x0C)
        vdata, _ = z.memory_ref(vb + 0x20)
        idata, _ = z.memory_ref(ib + 0x20)
        fmt = z.deref(vb + 0x30)
        if vdata is None or idata is None or fmt is None:
            continue
        stride = z.u32(fmt + 0x0C)
        el, el_size = z.memory_ref(fmt + 0x10)
        eb, eo = z._loc(el)
        p_off, uv_off, w_off, j_off = 0, None, None, None
        for i in range(el_size // 12):
            e = eb[eo + i * 12:eo + i * 12 + 12]
            off = struct.unpack_from('<H', e, 8)[0]
            if e[4] == 0 and e[0] == 2:
                p_off = off
            elif e[4] == 5 and e[0] == 0x2a and uv_off is None:     # premier jeu d'UV, half2
                uv_off = off
            elif e[4] == 6 and e[0] == 0x1a:                         # poids : 4 octets normalises
                w_off = off
            elif e[4] == 8 and e[0] == 0x0d:                         # os : 4 x uint32 locaux a l'appel de dessin
                j_off = off
        vbuf, vo = z._loc(vdata)
        raw = np.frombuffer(bytes(vbuf[vo:vo + nv * stride]), np.uint8).reshape(nv, stride)
        P = raw[:, p_off:p_off + 12].copy().view(np.float32).reshape(nv, 3)
        if o in dc_mat:
            m = dc_mat[o]
            P = (P.astype(np.float64) @ m[:3, :3] + m[3, :3]).astype(np.float32)
        pos.append(P)
        uvs.append(raw[:, uv_off:uv_off + 4].copy().view(np.float16).astype(np.float32).reshape(nv, 2)
                   if uv_off is not None else np.zeros((nv, 2), np.float32))
        if w_off is not None and j_off is not None and palette is not None:
            # plage de la palette de cet appel : mot +0x60 = (nombre << 16) | debut
            word = z.u32(o + 0x60)
            start = word & 0xFFFF
            loc = raw[:, j_off:j_off + 16].copy().view(np.uint32).reshape(nv, 4).astype(np.int64)
            glob = palette[np.clip(start + loc, 0, len(palette) - 1)]
            joints.append(glob.astype(np.float32))
            weights.append(raw[:, w_off:w_off + 4].astype(np.float32) / 255.0)
        else:
            joints.append(np.zeros((nv, 4), np.float32))
            weights.append(np.zeros((nv, 4), np.float32))
        ibuf, io = z._loc(idata)
        tri = np.frombuffer(bytes(ibuf[io:io + ni * 2]), np.uint16).astype(np.uint32) + nverts
        groups.append((sum(len(a) for a in idx), ni, _texture_of(z, o, deps, read, mat_cache)))
        idx.append(tri)
        nverts += nv
    cat = lambda arrs, shape, dt: np.concatenate(arrs) if arrs else np.zeros(shape, dt)
    out = {'positions': cat(pos, (0, 3), np.float32), 'uvs': cat(uvs, (0, 2), np.float32),
           'indices': cat(idx, (0,), np.uint32), 'groups': groups}
    W = cat(weights, (0, 4), np.float32)
    if len(W) and W.sum() > 0:                             # skin : os et poids (apercu anime)
        out['joints'], out['weights'] = cat(joints, (0, 4), np.float32), W
    return out


def _texture_of(z, dc, deps, read, cache):
    h = z.u32(dc + 0x40)
    if dc + 0x40 not in z.offset_sets.get('RHND', ()) or not h & 0x80000000:
        return None
    name, ns = z.ext_names[h & 0x7FFFFFFF]
    dep = deps.get(ns, '')
    if not dep.startswith('materials:/'):
        return None
    logical = 'materialinstances/' + dep[len('materials:/'):]
    if (logical, name) not in cache:
        data = read(logical)
        try:
            cache[(logical, name)] = material_color_texture(data, name) if data else None
        except Exception:  # noqa: BLE001 - materiau illisible : sans texture
            cache[(logical, name)] = None
    return cache[(logical, name)]


# -- decodage -----------------------------------------------------------------------------------
def _rgb565(v):
    r, g, b = (v >> 11) & 31, (v >> 5) & 63, v & 31
    return np.stack([(r * 255 + 15) // 31, (g * 255 + 31) // 63, (b * 255 + 15) // 31], -1).astype(np.float32)


def _color(b, bc1):
    """b (n, 8) blocs couleur -> (n, 16, 4) RGBA (alpha 0 pour le noir transparent du mode 3 couleurs BC1)."""
    b = b.astype(np.int32)
    c0, c1 = b[:, 0] | b[:, 1] << 8, b[:, 2] | b[:, 3] << 8
    p0, p1 = _rgb565(c0), _rgb565(c1)
    four = (c0 > c1)[:, None] if bc1 else np.ones((len(b), 1), bool)
    pal = np.stack([p0, p1, np.where(four, (2 * p0 + p1) / 3, (p0 + p1) / 2), np.where(four, (p0 + 2 * p1) / 3, 0)], 1)
    alpha = np.full((len(b), 4), 255.0)
    if bc1:
        alpha[:, 3] = np.where(four[:, 0], 255, 0)
    pal = np.concatenate([pal, alpha[:, :, None]], 2)
    bits = (b[:, 4] | b[:, 5] << 8 | b[:, 6] << 16 | b[:, 7] << 24).astype(np.uint32)
    sel = np.stack([(bits >> (2 * i)) & 3 for i in range(16)], 1).astype(np.int64)
    return np.take_along_axis(pal, sel[:, :, None].repeat(4, 2), 1)


def _alpha(b):
    """b (n, 8) blocs alpha BC3 -> (n, 16) alpha."""
    a0, a1 = b[:, 0].astype(np.float32), b[:, 1].astype(np.float32)
    eight = (a0 > a1)[:, None]
    k = np.arange(8, dtype=np.float32)
    pal8 = np.where(k == 0, a0[:, None], np.where(k == 1, a1[:, None], ((8 - k) * a0[:, None] + (k - 1) * a1[:, None]) / 7))
    pal6 = np.where(k == 0, a0[:, None], np.where(k == 1, a1[:, None], ((6 - k) * a0[:, None] + (k - 1) * a1[:, None]) / 5))
    pal6[:, 6], pal6[:, 7] = 0, 255
    pal = np.where(eight, pal8, pal6)
    bits = np.zeros(len(b), np.uint64)
    for i in range(6):
        bits |= b[:, 2 + i].astype(np.uint64) << np.uint64(8 * i)
    sel = np.stack([(bits >> np.uint64(3 * i)) & np.uint64(7) for i in range(16)], 1).astype(np.int64)
    return np.take_along_axis(pal, sel, 1)


def decode_texture(data, max_size=256):
    """Texture couleur BC1/BC3 -> (rgba, transparence ?) au plus grand niveau de mipmap <= max_size."""
    z = IgzFile(data)
    fmt = FORMATS.get(bytes(z.fixups['EXID'][1][:4]).hex())
    info = texture_info(data)
    if fmt is None or info['bytes_per_block'] is None:
        raise ValueError('format de texture non pris en charge')
    bpb = info['bytes_per_block']
    w, h, off, lvl = info['width'], info['height'], 0, 0
    while lvl < info['levels'] - 1 and max(w >> lvl, h >> lvl) > max_size:
        off += level_size(max(1, w >> lvl), max(1, h >> lvl), bpb)
        lvl += 1
    lw, lh = max(4, w >> lvl), max(4, h >> lvl)
    bw, bh = lw // 4, lh // 4
    tw = (bw + 7) // 8
    by, bx = np.mgrid[0:bh, 0:bw]
    src = (((by // 8) * tw + bx // 8) * 64 + LUT[by % 8, bx % 8]).reshape(-1)
    raw = np.frombuffer(bytes(z.data[1]), np.uint8, count=level_size(lw, lh, bpb), offset=off).reshape(-1, bpb)[src]
    if fmt == 'bc1':
        px = _color(raw, True)
    else:
        px = _color(raw[:, 8:16], False)
        px[:, :, 3] = _alpha(raw[:, :8])
    rgba = np.clip(np.rint(px), 0, 255).astype(np.uint8).reshape(bh, bw, 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(lh, lw, 4)
    return rgba, bool((rgba[:, :, 3] < 250).any())
