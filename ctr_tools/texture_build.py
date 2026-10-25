"""Textures personnalisees (image PNG/JPG -> texture du jeu) et materiaux qui les utilisent.

Format des textures PS4 (igImage2, verifie sur Crash Cove) :
  igImage2 +0x18 largeur u16, +0x1A hauteur u16, +0x1C profondeur, +0x1E niveaux, +0x28 format (reference
  externe : 833431f8 = BC1, cf76b9f0 = BC3, 6a1e087d = BC5), +0x38 memref des pixels (section de donnees 2).
  Pixels : niveaux du plus grand au plus petit ; chaque niveau = blocs 4x4 compresses, ranges par tuiles de
  8x8 blocs (tuiles ligne par ligne, completees a 8x8 blocs meme pour les petits niveaux), ordre de Morton dans
  la tuile (bit x0, y0, x1, y1, x2, y2). Ex. BC1 1024^2 9 niveaux = 700 416 octets.
Pour rester au plus pres des fichiers du jeu, on CLONE une texture existante de meme taille et de meme format et
on ne remplace que les pixels (et le nom interne) ; idem pour le materiau (on n'y change que des textures).
"""
import io
import struct

import numpy as np

from igz import IgzFile


# -- pavage PS4 ---------------------------------------------------------------------------------
def _morton_lut():
    lut = np.zeros((8, 8), np.int64)
    for y in range(8):
        for x in range(8):
            bits = [x & 1, y & 1, x >> 1 & 1, y >> 1 & 1, x >> 2 & 1, y >> 2 & 1]
            lut[y, x] = sum(b << i for i, b in enumerate(bits))
    return lut


LUT = _morton_lut()


def tile_blocks(blocks):
    """blocks (bh, bw, octets par bloc) -> octets pavés (tuiles de 8x8 blocs, Morton), niveau complete a 8x8."""
    bh, bw, bpb = blocks.shape
    th, tw = (bh + 7) // 8, (bw + 7) // 8
    out = np.zeros((th * tw * 64, bpb), np.uint8)
    by, bx = np.mgrid[0:bh, 0:bw]
    dst = ((by // 8) * tw + bx // 8) * 64 + LUT[by % 8, bx % 8]
    out[dst.reshape(-1)] = blocks.reshape(-1, bpb)
    return out.tobytes()


def untile_blocks(data, bh, bw, bpb):
    """Inverse de tile_blocks (pour les tests et l'apercu)."""
    th, tw = (bh + 7) // 8, (bw + 7) // 8
    raw = np.frombuffer(data[:th * tw * 64 * bpb], np.uint8).reshape(-1, bpb)
    by, bx = np.mgrid[0:bh, 0:bw]
    src = ((by // 8) * tw + bx // 8) * 64 + LUT[by % 8, bx % 8]
    return raw[src.reshape(-1)].reshape(bh, bw, bpb)


def level_size(w, h, bpb):
    return ((max(1, w // 4) + 7) // 8) * ((max(1, h // 4) + 7) // 8) * 64 * bpb


# -- BC1 ----------------------------------------------------------------------------------------
def _to565(c):
    c = np.clip(np.rint(c), 0, 255).astype(np.int32)
    return (c[..., 0] * 31 + 127) // 255 << 11 | (c[..., 1] * 63 + 127) // 255 << 5 | (c[..., 2] * 31 + 127) // 255


def _from565(v):
    r, g, b = (v >> 11) & 31, (v >> 5) & 63, v & 31
    return np.stack([(r * 255 + 15) // 31, (g * 255 + 31) // 63, (b * 255 + 15) // 31], -1).astype(np.float32)


def bc1_encode(rgb):
    """rgb (H, W, 3) uint8, H et W multiples de 4 -> blocs (H/4, W/4, 8) en BC1 4 couleurs (opaque).
    Extremites : projection sur l'axe principal de chaque bloc."""
    h, w, _ = rgb.shape
    px = rgb.reshape(h // 4, 4, w // 4, 4, 3).transpose(0, 2, 1, 3, 4).reshape(-1, 16, 3).astype(np.float32)
    mean = px.mean(1, keepdims=True)
    d = px - mean
    cov = np.einsum('nki,nkj->nij', d, d)
    axis = np.ones((len(px), 3), np.float32)
    for _ in range(4):                                         # iteration de puissance : axe principal
        axis = np.einsum('nij,nj->ni', cov, axis)
        axis /= np.linalg.norm(axis, axis=1, keepdims=True) + 1e-9
    t = np.einsum('nki,ni->nk', d, axis)
    lo = mean[:, 0] + axis * t.min(1, keepdims=True)
    hi = mean[:, 0] + axis * t.max(1, keepdims=True)
    c0, c1 = _to565(hi), _to565(lo)
    swap = c0 < c1
    c0, c1 = np.where(swap, c1, c0), np.where(swap, c0, c1)
    p0, p1 = _from565(c0), _from565(c1)
    pal = np.stack([p0, p1, (2 * p0 + p1) / 3, (p0 + 2 * p1) / 3], 1)          # (n, 4, 3)
    dist = ((px[:, :, None, :] - pal[:, None, :, :]) ** 2).sum(-1)              # (n, 16, 4)
    idx = dist.argmin(-1).astype(np.uint32)
    idx = np.where((c0 == c1)[:, None], 0, idx)                                 # bloc uni
    bits = np.zeros(len(px), np.uint32)
    for i in range(16):
        bits |= idx[:, i] << (2 * i)
    out = np.zeros((len(px), 8), np.uint8)
    out[:, 0], out[:, 1] = c0 & 255, c0 >> 8
    out[:, 2], out[:, 3] = c1 & 255, c1 >> 8
    for k in range(4):
        out[:, 4 + k] = (bits >> (8 * k)) & 255
    return out.reshape(h // 4, w // 4, 8)


def bc1_decode(blocks):
    """blocs (bh, bw, 8) -> rgb (bh*4, bw*4, 3) uint8 (tests / apercu)."""
    bh, bw, _ = blocks.shape
    b = blocks.reshape(-1, 8).astype(np.int32)
    c0, c1 = b[:, 0] | b[:, 1] << 8, b[:, 2] | b[:, 3] << 8
    p0, p1 = _from565(c0), _from565(c1)
    four = (c0 > c1)[:, None]
    pal = np.stack([p0, p1, np.where(four, (2 * p0 + p1) / 3, (p0 + p1) / 2), np.where(four, (p0 + 2 * p1) / 3, 0)], 1)
    bits = (b[:, 4] | b[:, 5] << 8 | b[:, 6] << 16 | b[:, 7] << 24).astype(np.uint32)
    sel = np.stack([(bits >> (2 * i)) & 3 for i in range(16)], 1)
    px = np.take_along_axis(pal, sel[:, :, None].repeat(3, 2).astype(np.int64), 1)
    return np.clip(np.rint(px), 0, 255).astype(np.uint8).reshape(bh, bw, 4, 4, 3).transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 3)


def bc3_encode(rgba):
    """rgba (H, W, 4) uint8 -> blocs (H/4, W/4, 16) BC3 : bloc alpha (2 extremites + indices 3 bits, mode 8 valeurs)
    puis bloc couleur BC1 (toujours 4 couleurs en BC3)."""
    h, w, _ = rgba.shape
    a = rgba[:, :, 3].reshape(h // 4, 4, w // 4, 4).transpose(0, 2, 1, 3).reshape(-1, 16).astype(np.int32)
    a0, a1 = a.max(1), a.min(1)
    pal = np.stack([a0, a1] + [((7 - k) * a0 + k * a1) / 7 for k in range(1, 7)], 1)          # (n, 8)
    idx = np.abs(a[:, :, None] - pal[:, None, :]).argmin(-1).astype(np.uint64)
    idx = np.where((a0 == a1)[:, None], 0, idx)
    bits = np.zeros(len(a), np.uint64)
    for i in range(16):
        bits |= idx[:, i] << np.uint64(3 * i)
    alpha = np.zeros((len(a), 8), np.uint8)
    alpha[:, 0], alpha[:, 1] = a0, a1
    for k in range(6):
        alpha[:, 2 + k] = (bits >> np.uint64(8 * k)) & np.uint64(255)
    color = bc1_encode(np.ascontiguousarray(rgba[:, :, :3])).reshape(-1, 8)
    return np.concatenate([alpha, color], 1).reshape(h // 4, w // 4, 16)


def build_bc3_image(template, rgba):
    """Texture BC3 a niveau unique (images d'interface : mini-carte) : clone de `template`, pixels remplaces.
    rgba doit avoir la taille du gabarit."""
    info = texture_info(template)
    if info['bytes_per_block'] != 16 or info['levels'] != 1:
        raise ValueError('le gabarit doit etre en BC3 a un seul niveau')
    if rgba.shape[:2] != (info['height'], info['width']):
        raise ValueError(f"image {rgba.shape[1]}x{rgba.shape[0]} au lieu de {info['width']}x{info['height']}")
    out = tile_blocks(bc3_encode(rgba))
    if len(out) != info['size']:
        raise ValueError(f'taille de texture inattendue ({len(out)} au lieu de {info["size"]})')
    z = IgzFile(template)
    z.data[1] = bytearray(out)
    return z.to_bytes()


# -- fichiers -----------------------------------------------------------------------------------
def _image(z):
    return next(o for o, t in z.objects.items() if t == 'igImage2')


def texture_info(data):
    z = IgzFile(data)
    img = _image(z)
    w, h, depth, levels = struct.unpack_from('<4H', *z._loc(img + 0x18))
    size = len(z.data[1])
    total = lambda bpb: sum(level_size(max(1, w >> i), max(1, h >> i), bpb) for i in range(levels))
    bpb = 8 if total(8) == size else 16 if total(16) == size else None
    return {'width': w, 'height': h, 'levels': levels, 'bytes_per_block': bpb, 'size': size}


def build_color_texture(template, image_bytes, internal_name):
    """Texture couleur BC1 depuis une image (PNG/JPG...) : clone de `template` (texture BC1 du jeu), image
    redimensionnee a sa taille, mipmaps recalcules. Haut de l'image = premiere ligne (convention DirectX, comme
    les UV ecrits par model_build)."""
    from PIL import Image
    info = texture_info(template)
    if info['bytes_per_block'] not in (8, 16):
        raise ValueError('le gabarit de texture doit etre en BC1 (opaque) ou BC3 (transparence)')
    alpha = info['bytes_per_block'] == 16                     # gabarit BC3 : canal alpha garde (decoupe)
    w, h, levels = info['width'], info['height'], info['levels']
    src = Image.open(io.BytesIO(image_bytes)).convert('RGBA' if alpha else 'RGB')
    if alpha:
        # couleur des pixels transparents = couleur moyenne des pixels voisins opaques (pas de liseré sombre / blanc
        # autour des feuilles quand le filtrage melange les texels aux bords de la decoupe)
        src = _bleed_alpha(src)
    out = b''
    for i in range(levels):
        lw, lh = max(4, w >> i), max(4, h >> i)
        px = np.asarray(src.resize((lw, lh), Image.LANCZOS), np.uint8)
        out += tile_blocks(bc3_encode(px) if alpha else bc1_encode(px))
    if len(out) != info['size']:
        raise ValueError(f'taille de texture inattendue ({len(out)} au lieu de {info["size"]})')
    z = IgzFile(template)
    z.data[1] = bytearray(out)
    z.set_string_ref(_image(z) + 0x10, internal_name)
    return z.to_bytes()


def image_has_alpha(image_bytes, threshold=0.002):
    """L'image a-t-elle une DECOUPE (feuillage, grillage) : plus de 0,2 % de pixels transparents, pas
    entierement transparente, et un alpha presque tout-ou-rien (moins de 25 % de valeurs intermediaires) ? Un alpha
    progressif sert souvent a autre chose (brillance, masques des textures extraites de jeux) : pas de trous."""
    from PIL import Image
    im = Image.open(io.BytesIO(image_bytes))
    if im.mode not in ('RGBA', 'LA', 'PA') and not (im.mode == 'P' and 'transparency' in im.info):
        return False
    im.thumbnail((256, 256))
    a = np.asarray(im.convert('RGBA'))[:, :, 3]
    clear = float((a < 128).mean())
    mid = float(((a > 24) & (a < 232)).mean())
    return threshold < clear < 0.98 and mid < 0.25


def _bleed_alpha(img):
    """Couleur des pixels transparents = moyenne ponderee des pixels opaques voisins (rayons croissants), alpha
    inchange : pas de liseré de couleur parasite quand le filtrage / les mipmaps melangent les bords."""
    from PIL import Image
    px = np.asarray(img, np.float32)
    rgb, a = px[:, :, :3].copy(), px[:, :, 3]
    known = (a >= 128).astype(np.float32)
    if known.all() or not known.any():
        return img

    def box(ch, r):                                     # flou moyen (2r+1)^2 par sommes cumulees, bords tronques
        out = ch
        for axis in (0, 1):
            c = np.cumsum(np.pad(out, [(r + 1, r) if k == axis else (0, 0) for k in range(2)]), axis=axis)
            hi = np.take(c, np.arange(2 * r + 1, c.shape[axis]), axis=axis)
            lo = np.take(c, np.arange(0, c.shape[axis] - 2 * r - 1), axis=axis)
            out = hi - lo
        return out
    for r in (1, 2, 4, 8, 16, 32, 64):
        blur = lambda ch: box(ch, r)
        den = blur(known)
        num = np.stack([blur(rgb[:, :, c] * known) for c in range(3)], -1)
        fill = (known == 0) & (den > 1e-3)
        rgb[fill] = num[fill] / den[fill][:, None]
        known = np.maximum(known, fill.astype(np.float32))
        if known.all():
            break
    out = np.concatenate([np.clip(rgb, 0, 255), a[:, :, None]], -1).astype(np.uint8)
    return Image.fromarray(out, 'RGBA')


def build_flat_normal(template):
    """Carte de normales plate (BC5, R = G = 128) : clone d'une carte de normales du jeu."""
    info = texture_info(template)
    if info['bytes_per_block'] != 16:
        raise ValueError('le gabarit de normales doit etre en BC5 (16 octets par bloc)')
    block = bytes([128, 128, 0, 0, 0, 0, 0, 0]) * 2           # deux canaux constants a 128
    z = IgzFile(template)
    z.data[1] = bytearray(block * (info['size'] // 16))
    z.set_string_ref(_image(z) + 0x10, '_custom_flat_N')
    return z.to_bytes()


def retarget_material(template, replace):
    """Materiau (materialinstances) avec des textures remplacees : replace = {ancien espace de noms : nouveau}.
    Change les entrees EXNM ('image', espace) et les dependances TDEP correspondantes (liste triee comme le jeu)."""
    from model_build import encode_tdep, tdep_entries
    z = IgzFile(template)
    for i, (name, ns) in enumerate(z.ext_names):
        if ns in replace:
            z.ext_names[i] = (name, replace[ns])
            z._exnm_raw[i] = (z.add_string(name), z.add_string(replace[ns]) | 0x80000000)
    deps = []
    for ns, path in tdep_entries(z):
        if ns in replace:
            ns, path = replace[ns], f'textures:/{replace[ns]}.igz'
        deps.append((ns, path))
    deps.sort(key=lambda d: d[0].lower())
    z.fixups['TDEP'] = (len(deps), encode_tdep(deps))
    return z.to_bytes()
