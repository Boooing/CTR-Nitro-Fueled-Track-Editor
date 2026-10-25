"""Apercu texture dans l'editeur : geometrie avec UV et texture couleur par draw call, textures decodees en RGBA.

  model_preview(octets_modele, lire) -> {'positions', 'uvs', 'indices',
                                         'groups': [(debut, nb, (espace de noms de la texture, decal ?) | None)]}
  decode_texture(octets_texture, max_size) -> (rgba (h, w, 4) uint8, a_de_la_transparence)
`lire(logique)` rend les octets d'un fichier (materiau ou texture) ou None. Les draw calls doubles (passe d'ombre,
variante : meme nombre de triangles et meme boite) sont ignores comme dans decor.model_mesh.
"""
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


def model_preview(data, read):
    z = IgzFile(data)
    deps = dict(tdep_entries(z))
    pos, uvs, idx, groups, seen = [], [], [], [], set()
    mat_cache = {}
    nverts = 0
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
        p_off, uv_off = 0, None
        for i in range(el_size // 12):
            e = eb[eo + i * 12:eo + i * 12 + 12]
            off = struct.unpack_from('<H', e, 8)[0]
            if e[4] == 0 and e[0] == 2:
                p_off = off
            elif e[4] == 5 and e[0] == 0x2a and uv_off is None:     # premier jeu d'UV, half2
                uv_off = off
        vbuf, vo = z._loc(vdata)
        raw = np.frombuffer(bytes(vbuf[vo:vo + nv * stride]), np.uint8).reshape(nv, stride)
        pos.append(raw[:, p_off:p_off + 12].copy().view(np.float32).reshape(nv, 3))
        uvs.append(raw[:, uv_off:uv_off + 4].copy().view(np.float16).astype(np.float32).reshape(nv, 2)
                   if uv_off is not None else np.zeros((nv, 2), np.float32))
        ibuf, io = z._loc(idata)
        tri = np.frombuffer(bytes(ibuf[io:io + ni * 2]), np.uint16).astype(np.uint32) + nverts
        groups.append((sum(len(a) for a in idx), ni, _texture_of(z, o, deps, read, mat_cache)))
        idx.append(tri)
        nverts += nv
    cat = lambda arrs, shape, dt: np.concatenate(arrs) if arrs else np.zeros(shape, dt)
    return {'positions': cat(pos, (0, 3), np.float32), 'uvs': cat(uvs, (0, 2), np.float32),
            'indices': cat(idx, (0,), np.uint32), 'groups': groups}


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
