"""Mini-carte d'une piste refaite d'apres le nouveau parcours.

Fichiers (Crash Cove) :
  * maps/.../<Piste>_Minimap.igz : entite « Minimap » (script common_Octane_Minimap) dont la memoire dynamique est
    l'evenement CGuiEventRacingMinimapSetup envoye a l'interface : +0x00 _rotationAngle (f), +0x04 _textureSize
    (2 f, 300 x 300), +0x0C _topLeft (2 f), +0x14 _bottomRight (2 f), +0x20 materiau, +0x30 sens des pilotes ; plus
    deux entites reperes « MinimapTopLeft » / « MinimapBottomRight ».
  * l'image : texture d'interface BC3 800 x 800 a un niveau (route gris clair + lisere, fond transparent, damier
    sur la ligne d'arrivee).
Correspondance monde -> image MESUREE sur Crash Cove (trace d'origine cale sur son image : 97 %, sans rotation) :
  u = A x + BU, v = -A y + BV (pixels). Les coins _topLeft / _bottomRight d'origine y tombent a la meme echelle (40 000
  po -> 596 px) : l'image depend affinement des coins. On n'a donc pas besoin de la formule exacte de l'interface :
  coins (et reperes) transformes par la similitude T qui amene la zone du nouveau parcours a la place de celle de
  Crash Cove, image dessinee avec la correspondance d'origine composee par T^-1.
"""
import math
import struct

import numpy as np

import texture_build
from igz import IgzFile

A, BU, BV = 0.01491, 630.8, 414.4          # Crash Cove : pixels par pouce et decalages (u vers la droite, v vers le bas)
# Reglage de reference : celui de Crash Cove, ou la correspondance ci-dessus a ete mesuree (et validee en jeu). Chaque
# piste a sa propre orientation d'image et ses propres coins (Roo's Tubes : image retournee de haut en bas, 380 x 420) :
# transformer SES coins avec la correspondance de Crash Cove donnait une mini-carte a l'envers. Toutes les pistes
# recoivent donc ce reglage (taille, coins, reperes), transforme pour le nouveau trace.
REFERENCE = {'texture_size': (300.0, 300.0), 'top_left': (6000.0, -22000.0), 'bottom_right': (-34000.0, 17000.0),
             'markers': {'MinimapTopLeft': (-23000.0, 23000.0), 'MinimapBottomRight': (13739.400390625, -24640.140625)}}
CONTENT = (476, 64, 794, 734)             # zone dessinee de l'image d'origine (px) : on y place le nouveau trace
# reglage fin du DESSIN seul (px) par rapport a la zone suivie par les pastilles : le calage mesure est precis a
# ~3 px pres ; en jeu (Mario Circuit 3) les pastilles etaient un tout petit peu trop haut -> dessin remonte de 4 px
NUDGE_DEFAULT = (0, -4)
ROAD = (221, 221, 221, 255)
EDGE = (236, 236, 236, 255)


def minimap_file(track):
    return f'maps/Octane/{track}/{track}_Minimap.igz'


def _script_memory(z):
    vsc = next(o for o, t in z.objects.items() if t == 'CVscComponentData')
    return z.deref(vsc + 0x10)


def read_setup(data):
    """{'rotation', 'texture_size', 'top_left', 'bottom_right', 'markers': {nom: (x, y)}}."""
    z = IgzFile(data)
    m = _script_memory(z)
    f = struct.unpack_from('<7f', *z._loc(m))
    marks = {n: z.vec3(o + 0x20)[:2] for n, o in z.root_objects() if n in ('MinimapTopLeft', 'MinimapBottomRight')}
    return {'rotation': f[0], 'texture_size': f[1:3], 'top_left': f[3:5], 'bottom_right': f[5:7], 'markers': marks}


def layout(points):
    """Similitude pour un nouveau trace (points monde [x, y, ...]) : -> (k px/po, centre monde, centre px)."""
    P = np.asarray(points, np.float64)[:, :2]
    lo, hi = P.min(0), P.max(0)
    w, h = CONTENT[2] - CONTENT[0], CONTENT[3] - CONTENT[1]
    k = min(w / max(hi[0] - lo[0], 1.0), h / max(hi[1] - lo[1], 1.0)) * 0.92        # petite marge
    return k, (lo + hi) / 2, np.array([(CONTENT[0] + CONTENT[2]) / 2, (CONTENT[1] + CONTENT[3]) / 2])


def to_px(p, k, c_world, c_px):
    return (k * (p[0] - c_world[0]) + c_px[0], -k * (p[1] - c_world[1]) + c_px[1])


def transform_corner(q, k, c_world, c_px):
    """Coin d'origine (repere Crash Cove) -> coin pour le nouveau trace : T(q) avec M' = M_crash o T^-1."""
    # M_crash(q) = (A qx + BU, -A qy + BV) ; M'(p) = to_px(p) ; T = M'^-1 o M_crash
    u, v = A * q[0] + BU, -A * q[1] + BV
    return ((u - c_px[0]) / k + c_world[0], -(v - c_px[1]) / k + c_world[1])


def write_setup(data, k, c_world, c_px):
    """Fichier _Minimap reconstruit : rotation 0, taille et coins du script et reperes = ceux de Crash Cove transformes
    (le reste inchange)."""
    z = IgzFile(data)
    m = _script_memory(z)
    tl = transform_corner(REFERENCE['top_left'], k, c_world, c_px)
    br = transform_corner(REFERENCE['bottom_right'], k, c_world, c_px)
    struct.pack_into('<f2f4f', *z._loc(m), 0.0, *REFERENCE['texture_size'], tl[0], tl[1], br[0], br[1])
    for n, o in z.root_objects():
        if n in REFERENCE['markers']:
            zz = z.vec3(o + 0x20)[2]
            nx, ny = transform_corner(REFERENCE['markers'][n], k, c_world, c_px)
            struct.pack_into('<3f', *z._loc(o + 0x20), nx, ny, zz)
    return z.to_bytes(), {'top_left': tl, 'bottom_right': br}


def draw(size, road_tris, path, finish, k, c_world, c_px, road_width=None):
    """Image RGBA (size x size) : route (triangles monde vus de dessus, sinon trace epais), lisere, damier."""
    from PIL import Image, ImageDraw, ImageFilter
    mask = Image.new('L', (size, size), 0)
    d = ImageDraw.Draw(mask)
    if road_tris is not None and len(road_tris):
        for t in road_tris:
            d.polygon([to_px(p, k, c_world, c_px) for p in t], fill=255)
    else:
        w = max(4, int(round((road_width or 1000.0) * k)))
        pts = [to_px(p, k, c_world, c_px) for p in path]
        d.line(pts + pts[:1], fill=255, width=w, joint='curve')
    mask = mask.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))       # trous entre triangles
    edge = mask.filter(ImageFilter.MaxFilter(5))
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    img.paste(Image.new('RGBA', (size, size), EDGE), mask=edge)
    img.paste(Image.new('RGBA', (size, size), ROAD), mask=mask)
    # damier sur la ligne d'arrivee : 4 x 2 cases en travers de la route
    if finish is not None:
        (fx, fy), yaw = finish[0][:2], finish[1]
        u, v = to_px((fx, fy), k, c_world, c_px)
        f = np.array([math.cos(yaw), -math.sin(yaw)])           # sens de course a l'ecran (v vers le bas)
        n = np.array([-f[1], f[0]])
        cell = 6.0
        dc = ImageDraw.Draw(img)
        for i in range(-2, 2):
            for j in range(-1, 1):
                col = (255, 255, 255, 255) if (i + j) % 2 else (150, 150, 150, 255)
                o = np.array([u, v]) + n * i * cell + f * j * cell
                quad = [o, o + n * cell, o + n * cell + f * cell, o + f * cell]
                dc.polygon([tuple(q) for q in quad], fill=col)
    return np.asarray(img)


# Orientation d'affichage : le jeu n'affiche pas l'image de la meme facon sur toutes les pistes (Roo's Tubes : retournee
# de haut en bas par rapport a Crash Cove, son image d'origine etant dessinee retournee en consequence ; meme en-tete
# de texture, memes reglages). On la retrouve sur les donnees d'origine : parmi les 8 orientations (rotations x miroir),
# celle qui amene l'image d'origine sur le trace d'origine vu comme a Crash Cove (u = x, v = -y). Le dessin est range
# avec l'orientation inverse. op = (quarts de tour np.rot90, miroir haut/bas).
OPS = [(k, f) for f in (False, True) for k in range(4)]


def apply_op(a, op):
    a = np.rot90(a, op[0])
    return a[::-1] if op[1] else a


def inverse_op(a, op):
    a = a[::-1] if op[1] else a
    return np.rot90(a, -op[0])


def choose_orientation(original_rgba, points):
    """Op retenue : celle detectee seulement si elle est nette (Roo's Tubes : retournee 0,58, suivante 0,31, normale
    < 0,24) ; normale si son score approche le meilleur ou si deux ops se valent (traces presque symetriques : Crash
    Cove, ovale, sortait retourne a 0,53 contre 0,47). -> (op, sure, scores)."""
    scores = sorted(detect_orientation(original_rgba, points, all_scores=True), key=lambda x: -x[1])
    if not scores:
        return (0, False), False, scores
    ident = dict(scores).get((0, False), 0.0)
    best, second = scores[0], (scores[1] if len(scores) > 1 else (None, 0.0))
    if best[0] == (0, False) or ident >= 0.85 * best[1]:
        return (0, False), True, scores
    if best[1] < 1.25 * second[1]:
        return (0, False), False, scores                       # incertain : comme Crash Cove, a verifier en jeu
    return best[0], True, scores


def detect_orientation(original_rgba, points, all_scores=False):
    """Orientation (op) de l'image d'origine par rapport au trace d'origine (points monde) : -> (op, score), ou
    [(op, score)] pour toutes les ops (all_scores).
    Pour chaque op : meilleur calage (echelle, decalage) du trace dans la route de l'image, puis score = intersection /
    union entre la route de l'image et le trace dessine a la largeur de cette route (une ligne fine seule tombait dans
    une route epaisse dans plusieurs orientations : Crash Cove sortait « retourne »)."""
    from PIL import Image, ImageDraw
    P = np.asarray(points, np.float64)[:, :2]
    Q = np.stack([P[:, 0], -P[:, 1]], 1)                       # comme a Crash Cove : u = x, v = -y
    best, every = None, []
    for op in OPS:
        mask = apply_op(original_rgba[:, :, 3] > 128, op)
        ys, xs = np.nonzero(mask)
        if not len(xs):
            continue
        k0 = min((xs.max() - xs.min()) / max(np.ptp(Q[:, 0]), 1.0), (ys.max() - ys.min()) / max(np.ptp(Q[:, 1]), 1.0))
        fit = None
        for k in k0 * np.linspace(0.75, 1.05, 13):
            u, v = k * Q[:, 0], k * Q[:, 1]
            bu = (xs.min() + xs.max()) / 2 - (u.min() + u.max()) / 2
            bv = (ys.min() + ys.max()) / 2 - (v.min() + v.max()) / 2
            for du in range(-24, 25, 8):
                for dv in range(-24, 25, 8):
                    uu = np.clip((u + bu + du).astype(int), 0, mask.shape[1] - 1)
                    vv = np.clip((v + bv + dv).astype(int), 0, mask.shape[0] - 1)
                    sc = float(mask[vv, uu].mean())
                    if fit is None or sc > fit[0]:
                        fit = (sc, u + bu + du, v + bv + dv)
        _, u, v = fit
        length = float(np.hypot(np.diff(u), np.diff(v)).sum()) or 1.0
        width = max(4, int(round(mask.sum() / length)))          # largeur de route de l'image (aire / longueur)
        img = Image.new('L', (mask.shape[1], mask.shape[0]), 0)
        ImageDraw.Draw(img).line(list(zip(u, v)), fill=255, width=width, joint='curve')
        drawn = np.asarray(img) > 0
        iou = float((drawn & mask).sum() / max(1, (drawn | mask).sum()))
        every.append((op, iou))
        if best is None or iou > best[1]:
            best = (op, iou)
    return every if all_scores else best


def build(minimap_data, texture_template, path, road_tris=None, finish=None, road_width=None, nudge=NUDGE_DEFAULT,
          orientation=(0, False)):
    """-> (octets _Minimap, octets texture, image RGBA, coins). path : trace de course (points monde).
    nudge : decalage (px) du dessin seul, les coins (zone suivie par les pastilles) ne bougent pas.
    orientation : op d'affichage de la piste (detect_orientation) ; l'image renvoyee est celle VUE en jeu."""
    k, cw, cp = layout(path if road_tris is None or not len(road_tris) else np.asarray(road_tris).reshape(-1, 3))
    info = texture_build.texture_info(texture_template)
    rgba = draw(info['width'], road_tris, path, finish, k, cw, cp + np.asarray(nudge, np.float64), road_width)
    stored = inverse_op(rgba, tuple(orientation)) if tuple(orientation) != (0, False) else rgba
    tex = texture_build.build_bc3_image(texture_template, np.ascontiguousarray(stored))
    setup, corners = write_setup(minimap_data, k, cw, cp)
    return setup, tex, rgba, corners
