"""Survol d'introduction d'une piste (cinematique jouee avant la course).

Archives propres a chaque piste : <piste>_*flyby*.pak (ex. t111_crash_cove_newflyby.pak, 4 plans de 3 a 4 s, et
..._newflyby_short02.pak, 1 plan de 6 s). Chaque plan a une camera cutscene/.../cameras/c_<...>_shotN.igz :
  * CCutsceneCamera : pose de depart (_position, _rotation en DEGRES) ;
  * CCameraKeyframeAnimation : une cle tous les 1/30 s — _times (igFloatList), _positions (igVec3fList, coordonnees
    du jeu, celles de la piste), _rotations (igVec3fList : roulis X, tangage Y, cap Z en RADIANS ; tangage negatif =
    regard vers le bas), _fovs (radians).
Une map importee n'est plus aux coordonnees de l'originale : le survol filmait le vide. Ici un plan est decrit par
deux poses (debut / fin : position de la camera + point regarde) ; les cles sont recalculees (mouvement adouci,
roulis nul) sans changer leur nombre ni leur minutage : la structure de la cinematique reste celle du jeu."""
import math
import struct

import numpy as np

from igz import IgzFile

LOOK_DIST = 3000.0          # po : point regarde derive d'une cle d'origine (direction de la camera)


def flyby_paks(pak_names, track):
    """Archives de survol de la piste (noms de fichiers du dossier des archives)."""
    pre = track.lower() + '_'
    return sorted(n for n in pak_names if n.lower().startswith(pre) and 'flyby' in n.lower() and n.lower().endswith('.pak'))


def is_camera(logical):
    return '/cameras/' in logical.lower() and logical.lower().endswith('.igz')


def _lists(z):
    anim = next(o for o, t in z.objects.items() if t == 'CCameraKeyframeAnimation')
    d = z.dump_object(anim)
    ref = lambda k: int(d[k]['@ref'], 16)
    return {k: z.list_info(ref(k)) for k in ('_times', '_positions', '_rotations', '_fovs')}


def read_camera(data):
    """{'times', 'positions', 'rotations', 'fovs'} (listes) d'un fichier camera de plan."""
    z = IgzFile(data)
    out = {}
    for k, (count, _, mem) in _lists(z).items():
        n = 3 if k in ('_positions', '_rotations') else 1
        vals = [struct.unpack_from(f'<{n}f', *z._loc(mem + i * 4 * n)) for i in range(count)]
        out[k[1:]] = [list(v) if n == 3 else v[0] for v in vals]
    return out


def look_rotation(pos, target):
    """[roulis, tangage, cap] (radians) d'une camera en pos qui regarde target."""
    d = np.asarray(target, float) - np.asarray(pos, float)
    return [0.0, math.atan2(d[2], math.hypot(d[0], d[1])), math.atan2(d[1], d[0])]


def direction(rot):
    _, pitch, yaw = rot
    return np.array([math.cos(yaw) * math.cos(pitch), math.sin(yaw) * math.cos(pitch), math.sin(pitch)])


def model_of(cam):
    """Poses de debut et de fin d'un plan d'origine (point regarde a LOOK_DIST dans l'axe)."""
    P, R = cam['positions'], cam['rotations']
    pose = lambda p, r: {'pos': [round(v, 1) for v in p],
                         'look': [round(float(v), 1) for v in np.asarray(p) + direction(r) * LOOK_DIST]}
    return {'start': pose(P[0], R[0]), 'end': pose(P[-1], R[-1])}


def _ease(t):
    return t * t * (3 - 2 * t)


def keys_for(model, count):
    """Cles (positions, rotations) d'un plan : de la pose de debut a celle de fin, mouvement adouci ; le point
    regarde glisse de meme. Rotations continues (pas de saut de 360 degres entre deux cles)."""
    a, b = model['start'], model['end']
    P, R, prev = [], [], None
    for i in range(count):
        s = _ease(i / max(1, count - 1))
        pos = [a['pos'][k] + (b['pos'][k] - a['pos'][k]) * s for k in range(3)]
        look = [a['look'][k] + (b['look'][k] - a['look'][k]) * s for k in range(3)]
        r = look_rotation(pos, look)
        if prev is not None:                            # cap deroule : continu d'une cle a l'autre
            r[2] = prev + (r[2] - prev + math.pi) % (2 * math.pi) - math.pi
        prev = r[2]
        P.append(pos)
        R.append(r)
    return P, R


def write_camera(data, model):
    """Fichier camera reecrit en place : positions / rotations recalculees, pose de depart de la camera."""
    z = IgzFile(data)
    lists = _lists(z)
    count = lists['_positions'][0]
    P, R = keys_for(model, count)
    for (n, _, mem), vals in ((lists['_positions'], P), (lists['_rotations'], R)):
        for i, v in enumerate(vals):
            struct.pack_into('<3f', *z._loc(mem + i * 12), *v)
    cam = next(o for o, t in z.objects.items() if t == 'CCutsceneCamera')
    struct.pack_into('<3f', *z._loc(z.find_field(cam, '_position')[0]), *P[0])
    struct.pack_into('<3f', *z._loc(z.find_field(cam, '_rotation')[0]), *[math.degrees(v) for v in R[0]])
    return z.to_bytes()


# -- plans proposes ---------------------------------------------------------------------------------
def _route_frame(route, s):
    """(point, direction horizontale unitaire) a l'abscisse s (po) du trace (polyligne fermee)."""
    P = np.asarray(route, float)
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    cum = np.concatenate([[0], np.cumsum(seg)])
    s = s % cum[-1]
    i = min(int(np.searchsorted(cum, s, side='right')) - 1, len(seg) - 1)
    t = (s - cum[i]) / max(seg[i], 1e-6)
    p = P[i] + (P[i + 1] - P[i]) * t
    d = P[i + 1] - P[i]
    d = d[:2] / max(np.linalg.norm(d[:2]), 1e-6)
    return p, d


def auto_models(route, shots, finish, grid_center=None, ground=None):
    """Plans proposes d'apres le parcours. route : points du tour dans l'ordre (po) ; shots : [(cle, nombre de cles,
    final)] ; finish : (position, cap) de la ligne d'arrivee ; ground(x, y, z) -> hauteur du sol ou None.
      * plans ordinaires : travelling de drone le long de la route (alternativement a gauche / a droite, bas puis
        haut), regard sur la route devant ;
      * plan final (dernier du survol complet, plan du survol court) : descend de haut devant la ligne vers
        l'arriere de la grille, regard sur la grille puis dans le sens de la course (la camera de course prend
        ensuite le relais derriere les karts)."""
    P = np.asarray(route, float)
    lap = float(np.sum(np.linalg.norm(np.diff(P, axis=0), axis=1)))
    above = lambda p, h: [float(p[0]), float(p[1]), float(max(p[2], (ground(p[0], p[1], p[2] + 500) or p[2]) if ground else p[2]) + h)]
    fpos, fyaw = np.asarray(finish[0], float), float(finish[1])
    fwd = np.array([math.cos(fyaw), math.sin(fyaw)])
    side = np.array([-fwd[1], fwd[0]])
    gc = np.asarray(grid_center if grid_center is not None else fpos, float)
    gz = above(gc, 0)[2]
    normal = [s for s in shots if not s[2]]
    out = {}
    for k, (key, count, final) in enumerate(shots):
        if final:
            start = [*(gc[:2] + fwd * 3200 + side * 1600), gz + 1400]
            end = [*(gc[:2] - fwd * 1300), gz + 260]
            out[key] = {'start': {'pos': start, 'look': [*gc[:2], gz]},
                        'end': {'pos': end, 'look': [*(gc[:2] + fwd * 2500), gz + 100]}}
            continue
        j = normal.index((key, count, final))
        centre = lap * (0.18 + 0.64 * (j + 0.5) / max(1, len(normal)))
        travel = 700.0 * count / 30.0                   # ~18 m/s
        sgn = 1 if j % 2 == 0 else -1
        lat, high = 900.0 * sgn, (350.0 if j % 2 == 0 else 1100.0)
        pose = {}
        for name, s in (('start', centre - travel / 2), ('end', centre + travel / 2)):
            p, d = _route_frame(P, s)
            n = np.array([-d[1], d[0]])
            q, _ = _route_frame(P, s + 2200)
            cam = above([*(p[:2] + n * lat), p[2]], high)
            pose[name] = {'pos': cam, 'look': above(q, 80)}
        out[key] = pose
    return {k: {n: {kk: [round(float(v), 1) for v in vv] for kk, vv in pose.items()} for n, pose in m.items()}
            for k, m in out.items()}


def fixed_models(shots, finish, grid_center=None, ground=None):
    """Plan fixe derriere la grille pour tous les plans (le survol ne montre plus rien de faux)."""
    fpos, fyaw = np.asarray(finish[0], float), float(finish[1])
    fwd = np.array([math.cos(fyaw), math.sin(fyaw)])
    gc = np.asarray(grid_center if grid_center is not None else fpos, float)
    gz = float(max(gc[2], (ground(gc[0], gc[1], gc[2] + 500) or gc[2]) if ground else gc[2]))
    pose = {'pos': [*(gc[:2] - fwd * 1300), gz + 300], 'look': [*(gc[:2] + fwd * 2500), gz + 100]}
    pose = {k: [round(float(v), 1) for v in vv] for k, vv in pose.items()}
    return {key: {'start': dict(pose), 'end': dict(pose)} for key, _, _ in shots}
