"""Test : textures importees (pavage PS4, BC1, normales plates, materiau clone).

Usage : python test_texture_build.py <dossier archives>
"""
import io
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pak_tool  # noqa: E402
import texture_build as tb  # noqa: E402
from igz import IgzFile  # noqa: E402
from model_build import tdep_entries  # noqa: E402

TP = 't111_crash_cove.pak'
COLOR = 'textures/ColorMap,textures@!levels!Octane!T111_Crash_Cove!T111_rockgroundside!T111_rockgroundside_C`tga,111.igz'
NORMAL = 'textures/NormalMap,textures@!levels!Octane!T111_Crash_Cove!T111_rockgroundside!T111_rockgroundside_N`tga,111.igz'
MAT = 'materialinstances/octane/t111_crash_cove/t111_props_materials,t111_rockgroundside_b,00020.igz'


def check(cond, msg):
    print(('OK   ' if cond else 'ECHEC') + ' ' + msg)
    if not cond:
        raise SystemExit(1)


def main(archives):
    tc, tn, tm = (pak_tool.read_latest(archives, p, TP)[0] for p in (COLOR, NORMAL, MAT))
    info = tb.texture_info(tc)
    check(info == {'width': 1024, 'height': 1024, 'levels': 9, 'bytes_per_block': 8, 'size': 700416},
          'texture du jeu : BC1 1024^2, 9 niveaux completes a 8x8 blocs = 700 416 octets')
    check(tb.texture_info(tn)['bytes_per_block'] == 16, 'carte de normales du jeu : 16 octets par bloc (BC5)')
    data = bytes(IgzFile(tc).data[1])
    lvl0 = data[:tb.level_size(1024, 1024, 8)]
    check(tb.tile_blocks(tb.untile_blocks(lvl0, 256, 256, 8)) == lvl0, 'depavage puis repavage du niveau 0 = octets du jeu')
    rock = tb.bc1_decode(tb.untile_blocks(lvl0, 256, 256, 8)).astype(np.float32)
    # une image coherente varie peu d'un pixel a l'autre ; un mauvais pavage donne du bruit de blocs
    check(np.abs(np.diff(rock, axis=1)).mean() < 12, 'texture du jeu decodee coherente (pavage de Morton correct)')
    im = Image.new('RGB', (640, 480), (30, 90, 200))
    ImageDraw.Draw(im).ellipse([100, 100, 500, 400], fill=(250, 220, 30))
    buf = io.BytesIO()
    im.save(buf, 'PNG')
    out = tb.build_color_texture(tc, buf.getvalue(), '_Test_C')
    z = IgzFile(out)
    check(len(out) and len(z.data[1]) == info['size'] and z.to_bytes() == out, 'texture creee : meme taille, relue a l\'identique')
    dec = tb.bc1_decode(tb.untile_blocks(bytes(z.data[1]), 256, 256, 8)).astype(np.float32)
    ref = np.asarray(im.resize((1024, 1024), Image.LANCZOS), np.float32)
    psnr = 10 * np.log10(255 ** 2 / ((dec - ref) ** 2).mean())
    check(psnr > 35, f'image relue apres encodage BC1 : {psnr:.1f} dB')
    flat = IgzFile(tb.build_flat_normal(tn))
    check(set(bytes(flat.data[1])) == {0, 128}, 'normales plates : blocs BC5 constants a 128')
    old = {ns.split(',')[0]: ns for n, ns in IgzFile(tm).ext_names if n == 'image'}
    mat = IgzFile(tb.retarget_material(tm, {old['ColorMap']: 'ColorMap,textures@!custom!Test_C`png,111'}))
    deps = tdep_entries(mat)
    check(('image', 'ColorMap,textures@!custom!Test_C`png,111') in mat.ext_names
          and ('ColorMap,textures@!custom!Test_C`png,111', 'textures:/ColorMap,textures@!custom!Test_C`png,111.igz') in deps
          and len(deps) == len(tdep_entries(IgzFile(tm))), 'materiau : poignee + dependance de la texture remplacees')
    # transparence (decoupe) : feuille verte sur fond transparent -> BC3 + mipmaps, alpha et couleur conserves
    leaf = Image.new('RGBA', (512, 512), (0, 0, 0, 0))
    ImageDraw.Draw(leaf).ellipse([96, 96, 416, 416], fill=(40, 180, 60, 255))
    buf = io.BytesIO()
    leaf.save(buf, 'PNG')
    check(tb.image_has_alpha(buf.getvalue()), 'decoupe detectee sur une image a fond transparent')
    grad = Image.new('RGBA', (256, 256))
    grad.putdata([(120, 120, 120, x) for y in range(256) for x in range(256)])
    gb = io.BytesIO()
    grad.save(gb, 'PNG')
    check(not tb.image_has_alpha(gb.getvalue()), 'alpha progressif (brillance) : pas pris pour une decoupe')
    bc3 = pak_tool.read_latest(archives, 'textures/colormap,textures@!levels!crash1!jungle!c1_dirt01_c`tga,111.igz', TP)[0]
    za = IgzFile(tb.build_color_texture(bc3, buf.getvalue(), '_Leaf_C'))
    blk = tb.untile_blocks(bytes(za.data[1]), 256, 256, 16)
    alpha0 = blk[:, :, 0].astype(int)            # extremite alpha haute de chaque bloc
    check(len(za.data[1]) == tb.texture_info(bc3)['size'] and alpha0[128, 128] > 200 and alpha0[5, 5] < 30,
          'texture BC3 a decoupe : opaque au centre, transparente au bord, taille du gabarit')
    print('tous les tests passent')


if __name__ == '__main__':
    main(sys.argv[1])
