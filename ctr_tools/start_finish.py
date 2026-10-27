"""Grille de depart et ligne d'arrivee (zone de changement de tour).

Grille : 8 CWaypoint « Starting_Waypoint_1st..8th » (ou « AIWaypoint001..008 » selon la piste, voir GRID_RE) du fichier maps/Octane/<P>/<P>_Design.igz (8 pistes : du _RaceSystem.igz, meme structure) :
  _position (vec3, coordonnees monde, pouces) et _rotation (vec3 radians, seul Z = cap utilise).
Repere de depart : entite CPlayerStartEntity « PlayerStartAll » du fichier maps/Octane/<P>/<P>.igz
  (+0x20 position, transformation +0x60 Euler) : suit la grille quand on la deplace en bloc.
Ligne d'arrivee : transition du RaceSystem (CRaceTrackSplineTransitionComponentData, _incrementLap) ; sa zone de
  declenchement est le CTriggerVolumeBoxComponentData de la meme entite : boite de _dimensions (profondeur dans
  le sens de la course, largeur, hauteur) centree sur la position de l'entite (+ _offset), tournee du cap de
  l'entite (transformation +0x60, Z). Deplacer l'entite deplace la zone.
"""
import re
import struct

from igz import IgzFile

# noms selon la piste : Crash Cove « Starting_Waypoint_1st », Roo's Tubes « AIWaypoint001 », Mystery Caves
# « AI_Waypoint_001 », Coco Park « AIWaypoint_01 », Tiny Arena « StartingPosition_01 », Hot Air Skyway
# « StartingPosition_000..007 » (8 places en 2 rangees de 4, a cote du repere de depart). Les 8 plus petits numeros.
GRID_RE = re.compile(r'^(?:Starting_Waypoint_(\d+)(?:st|nd|rd|th)'
                     r'|(?:AI_?Waypoint|Starting_?Position|Starting_?Waypoint|Grid_Start_Waypoint)_?(\d+))$', re.I)


def design_file(track):
    return f'maps/Octane/{track}/{track}_Design.igz'


def main_map_file(track):
    return f'maps/Octane/{track}/{track}.igz'


def _grid_objects(z):
    found = []
    for name, o in z.root_objects():
        m = GRID_RE.match(name or '')
        if m and z.objects.get(o) == 'CWaypoint':
            found.append((int(m.group(1) or m.group(2)), name, o))
    return sorted(found)[:8]


def read_grid(design_bytes):
    """[{name, pos, yaw}] dans l'ordre des places (1re, 2e...)."""
    return read_grid_igz(IgzFile(design_bytes))


def read_grid_igz(z):
    out = []
    for _, name, o in _grid_objects(z):
        d = z.dump_object(o)
        out.append({'name': name, 'pos': list(d['_position']), 'yaw': d['_rotation'][2]})
    return out


def write_grid(design_bytes, slots):
    """slots = {nom : {pos, yaw}} -> octets du fichier _Design modifie."""
    z = IgzFile(design_bytes)
    write_grid_igz(z, slots)
    return z.to_bytes()


def write_grid_igz(z, slots):
    """Grille ecrite dans un fichier deja ouvert (le _RaceSystem en cours d'edition, pour les 8 pistes qui y
    gardent leur grille : Sewer Speedway, Slide Coliseum, Turbo Track, Dingo Canyon, N. Gin Labs, Cortex Castle,
    Barin Ruins, Android Alley). -> nombre de places ecrites."""
    n = 0
    for _, name, o in _grid_objects(z):
        if name in slots:
            s = slots[name]
            z.set_field(o, '_position', [float(c) for c in s['pos']])
            rot = list(z.dump_object(o)['_rotation'])
            rot[2] = float(s['yaw'])
            z.set_field(o, '_rotation', rot)
            n += 1
    return n


def _player_start(z):
    return next((o for n, o in z.root_objects() if z.objects.get(o) == 'CPlayerStartEntity'), None)


def read_player_start(main_bytes):
    z = IgzFile(main_bytes)
    o = _player_start(z)
    if o is None:
        return None
    tr = z.deref(o + 0x30)
    yaw = struct.unpack_from('<f', *z._loc(tr + 0x68))[0] if tr is not None else 0.0
    return {'pos': list(z.vec3(o + 0x20)), 'yaw': yaw}


def write_player_start(main_bytes, pos, yaw):
    z = IgzFile(main_bytes)
    o = _player_start(z)
    struct.pack_into('<3f', *z._loc(o + 0x20), *[float(c) for c in pos])
    tr = z.deref(o + 0x30)
    if tr is not None:
        struct.pack_into('<f', *z._loc(tr + 0x68), float(yaw))
        struct.pack_into('<I', *z._loc(tr + 0x7C), 1)          # _isDirty
    return z.to_bytes()


def _entity_by_name(z, name):
    return next((o for n, o in z.root_objects() if n == name), None)


def read_entity_poses(data, names):
    """{nom : {pos, yaw}} d'entites (position +0x20, cap = transformation +0x68 si elle existe)."""
    z = IgzFile(data)
    out = {}
    for name in names:
        o = _entity_by_name(z, name)
        if o is None:
            continue
        tr = z.deref(o + 0x30)
        out[name] = {'pos': list(z.vec3(o + 0x20)),
                     'yaw': struct.unpack_from('<f', *z._loc(tr + 0x68))[0] if tr is not None else 0.0}
    return out


def write_entity_poses(data, poses):
    """poses = {nom : {pos, yaw?}} -> octets ; le cap n'est ecrit que si l'entite a une transformation."""
    z = IgzFile(data)
    for name, p in poses.items():
        o = _entity_by_name(z, name)
        if o is None:
            raise KeyError(f'entite introuvable : {name}')
        set_entity_pose(z, o, p)
    return z.to_bytes()


def set_entity_pose(z, o, p):
    """Position (+0x20) et cap (transformation +0x68, si elle existe) de l'entite o du fichier z."""
    struct.pack_into('<3f', *z._loc(o + 0x20), *[float(c) for c in p['pos']])
    tr = z.deref(o + 0x30)
    if tr is not None:
        if p.get('yaw') is not None:
            struct.pack_into('<f', *z._loc(tr + 0x68), float(p['yaw']))
        struct.pack_into('<I', *z._loc(tr + 0x7C), 1)


def transition_pose(ed, name):
    """(position, cap, dimensions de la zone) d'une transition (RaceSystemEditor)."""
    z = ed.igz
    ent = ed.by_name[name]
    tr = z.deref(ent + 0x30)
    yaw = struct.unpack_from('<f', *z._loc(tr + 0x68))[0] if tr is not None else 0.0
    box = ed.component(ent, 'CTriggerVolumeBoxComponentData')
    dims = list(z.dump_object(box)['_dimensions']) if box is not None else None
    return list(z.vec3(ent + 0x20)), yaw, dims


def set_transition_pose(ed, name, pos=None, yaw=None, dims=None):
    z = ed.igz
    ent = ed.by_name[name]
    if pos is not None:
        struct.pack_into('<3f', *z._loc(ent + 0x20), *[float(c) for c in pos])
    tr = z.deref(ent + 0x30)
    if yaw is not None:
        if tr is None:
            raise ValueError(f'{name} n\'a pas de transformation : rotation impossible')
        struct.pack_into('<f', *z._loc(tr + 0x68), float(yaw))
    if tr is not None and (pos is not None or yaw is not None):
        struct.pack_into('<I', *z._loc(tr + 0x7C), 1)
    if dims is not None:
        box = ed.component(ent, 'CTriggerVolumeBoxComponentData')
        z.set_field(box, '_dimensions', [float(c) for c in dims])
