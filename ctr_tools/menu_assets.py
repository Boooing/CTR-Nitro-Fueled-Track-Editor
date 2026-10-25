"""Nom et images d'une piste dans les menus du jeu (sans renommer aucun fichier).

  * nom : maps/Octane/<P>/<P>_zoneInfo_<langue>.lng (chunkinfos.pak) = IGZ de 3 igLocalizedStringData ; le 1er
    (objet CZoneInfo) est le nom affiche (fr : « Crique Crash »), le 2e l'indice, le 3e la zone (« Zone N. Sanity
    Beach », champ CZoneInfo::_displayName de la zone). Langues : en, fr, mx (espagnol), pt ;
  * images (textures d'interface BC3 a un niveau, LIGNES DE BAS EN HAUT, archives juicedomain_* / piste) : fond de l'ecran de choix de
    course (1288 x 1080, opaque), vignette de la liste (100 x 100) et embleme de l'intro (164 x 164) (formes blanches
    sur transparent), trace du menu (600 x 600 : silhouette blanche pleine de la route). Le fond anime de l'ecran de
    choix est une video Bink 2 hors archive (archives/octane_ui_race_select_<piste>.bk2) : non generee ici.
"""
import io
import re

import numpy as np

from igz import IgzFile

LANGS = {'fr': 'français', 'en': 'anglais', 'mx': 'espagnol', 'pt': 'portugais'}
IMAGES = {'background': ('Fond de l\'écran de choix de course', 'RaceSelect!octane_ui_raceselect_bg_{}'),
          'icon': ('Vignette de la liste des courses', 'RaceSelect!octane_ui_raceselect_ico_{}'),
          'intro': ('Emblème de l\'intro de course', 'RaceIntro!ui_octane_raceintro_icons_{}'),
          'outline': ('Tracé de la piste (menu)', 'RaceSelect!octane_ui_raceselect_minimap_{}')}


def slug(track):
    """'T111_Crash_Cove' -> 'crashcove' (nom des textures d'interface)."""
    return re.sub(r'^T\d+_', '', track).replace('_', '').lower()


def name_file(track, lang):
    return f'maps/Octane/{track}/{track}_zoneInfo_{lang}.lng'


def image_file(track, key):
    return f'textures/GuiStandard_diffuse,textures@!ui!Octane!{IMAGES[key][1].format(slug(track))}`tga,101.igz'


def _name_entry(z):
    """Offset du champ _string du nom affiche (1er igLocalizedStringData)."""
    off = next(o for o, t in sorted(z.objects.items()) if t == 'igLocalizedStringData')
    return off + next(fo for fo, (n, _) in z.fields_of('igLocalizedStringData').items() if n == '_string')


# les chaines IGZ sont lues / ecrites octet pour octet (latin-1) ; le jeu les stocke en UTF-8 (« Baía do Crash »)
def read_name(data):
    z = IgzFile(data)
    return z.string(z.u32(_name_entry(z))).encode('latin1').decode('utf-8', 'replace')


def write_name(data, name):
    z = IgzFile(data)
    z.set_string_ref(_name_entry(z), name.encode('utf-8').decode('latin1'))
    return z.to_bytes()


def fit_image(image_bytes, w, h, cover):
    """Image -> RGBA w x h : cover = remplit en recadrant au centre (fond), sinon contenue avec marges transparentes."""
    from PIL import Image
    im = Image.open(io.BytesIO(image_bytes)).convert('RGBA')
    k = (max if cover else min)(w / im.width, h / im.height)
    im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
    out = Image.new('RGBA', (w, h), (0, 0, 0, 0 if not cover else 255))
    out.alpha_composite(im, ((w - im.width) // 2, (h - im.height) // 2))
    return np.asarray(out, np.uint8)


def outline(size, path, road_tris=None, road_width=1400.0, margin=0.08):
    """Silhouette blanche pleine de la route (vue de dessus, nord en haut), centree avec une marge : comme le
    trace du menu du jeu. path : trace (pouces) ; road_tris : triangles de la route si elle est connue."""
    from PIL import Image, ImageDraw
    P = np.asarray(path, np.float64)[:, :2]
    pts = P if road_tris is None or not len(road_tris) else np.asarray(road_tris, np.float64)[:, :, :2].reshape(-1, 2)
    lo, hi = pts.min(0), pts.max(0)
    span = float((hi - lo).max()) or 1.0
    k = size * (1 - 2 * margin) / span
    c_world, c_px = (lo + hi) / 2, size / 2
    to_px = lambda p: (c_px + (p[0] - c_world[0]) * k, c_px - (p[1] - c_world[1]) * k)
    ss = 4                                              # sur-echantillonnage (bords lisses)
    im = Image.new('L', (size * ss, size * ss), 0)
    d = ImageDraw.Draw(im)
    big = lambda q: (q[0] * ss, q[1] * ss)
    if road_tris is not None and len(road_tris):
        for t in road_tris:
            d.polygon([big(to_px(p)) for p in t], fill=255)
    else:
        line = [big(to_px(p)) for p in P] + [big(to_px(P[0]))]
        d.line(line, fill=255, width=max(2, int(road_width * k * ss)), joint='curve')
    a = np.asarray(im.resize((size, size), Image.LANCZOS), np.uint8)
    rgba = np.zeros((size, size, 4), np.uint8)
    rgba[..., :3] = 255
    rgba[..., 3] = a
    return rgba
