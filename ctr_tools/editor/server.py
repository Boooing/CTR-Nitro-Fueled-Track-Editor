"""Editeur de pistes CTR Nitro-Fueled : serveur local.

Usage : python ctr_tools/editor/server.py [--archives "<dossier archives du jeu>"] [--port 8765]
(sans --archives : dossier memorise dans ctr_editor_config.json, sinon la page le demande a l'ouverture)
Puis ouvrir http://localhost:8765


API :
  GET  /api/tracks                 pistes disponibles (archives tNNN_*.pak)
  GET  /api/track?name=T111_Crash_Cove
        -> splines (monde, pouces), transitions (+ liens), embranchements, splines de depart, collision
  POST /api/save    {track, splines: {nom: points}, new_splines: [{name, template}], deleted: [noms],
                     transitions: {nom: {increment_lap, previous_ai, next_ai, previous_position, next_position}},
                     starting_splines: [noms]}   (splines IA du tour 1, TTRStats CStartingSplineInfo)
        -> ecrit <Piste>_RaceSystem.igz et <Piste>_TTRStats.igz dans out/editor/
  POST /api/install {track}   installe les fichiers sauves dans chaque archive qui les contient (reversible)
  POST /api/uninstall {track} restaure les archives d'origine
  POST /api/reset {track, what: all|race|decor}   oublie les fichiers sauves (on repart de l'original)
  GET  /api/decor?name=<Piste>          objets de decor des fichiers _Art* (id, nom, modele, position, euler, echelle)
  GET  /api/model?track=..&file=..      maillage binaire d'un modele (u32 nv, u32 ni, float32[3nv], uint32[ni])
  POST /api/decor_save {track, files: {fichier: {moves, duplicates, deleted}}}

La base d'une sauvegarde est la derniere version sauvee (si elle existe), sinon l'original le plus recent
(update2 > update > archive de la piste, lu a travers une eventuelle installation de mod).
"""
import collections
import gzip
import io
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
import traceback
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
if HERE not in sys.path:                               # modules de l'editeur (mappack) : absent avec « python -I »
    sys.path.insert(0, HERE)
import pak_tool  # noqa: E402
import ai_gen  # noqa: E402
import numpy as np  # noqa: E402
import obj_export  # noqa: E402
import library  # noqa: E402
import pkg_manifest  # noqa: E402
import powerup  # noqa: E402
import progress  # noqa: E402
import minimap  # noqa: E402
import music  # noqa: E402
import race_times
import collision_materials  # noqa: E402
import preview  # noqa: E402
import route_gen  # noqa: E402
import flyby  # noqa: E402
import lights  # noqa: E402
import custom_category  # noqa: E402
import menu_assets  # noqa: E402
import track_clone  # noqa: E402
import quick_test  # noqa: E402
import track_creator  # noqa: E402
import updater  # noqa: E402
import mappack  # noqa: E402
mappack.bind(sys.modules[__name__])                    # ce module, meme lance en script (__main__)
import octr_export  # noqa: E402
octr_export.bind(sys.modules[__name__])                # export en mod pour le portage PC (OCTR)
import start_finish  # noqa: E402
import teleport  # noqa: E402
import texture_build  # noqa: E402
import walls  # noqa: E402
from collision import decode_compressed_mesh, transform  # noqa: E402
from collision_edit import CollisionFile  # noqa: E402
from collision_region import GroundEditor, apply, mat_inv_rigid_scale, mat_mul, object_matrix  # noqa: E402
from decor import ENTITY_TYPES, DecorFile, model_logical_path, model_mesh  # noqa: E402
from igz import IgzFile  # noqa: E402
from model_build import (TEMPLATE, build_model, build_model_multi, complete_mesh, model_materials, obj_extents, obj_material_extents,  # noqa: E402
                         obj_summary, parse_mtl,
                         parse_obj_groups, set_material)
from havok import Packfile  # noqa: E402
from race_entities import RaceSystemEditor, TTRStatsEditor  # noqa: E402
from race_system import RaceSystem  # noqa: E402

ARCHIVES = ''                  # dossier « archives » du jeu : --archives, sinon ctr_editor_config.json, sinon demande par la page
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(HERE)), 'out', 'editor')
HAVOK_TO_GAME = 39.37          # metres -> pouces
LIST_KEYS = ('previous_ai', 'next_ai', 'previous_position', 'next_position')
RACE_TRANSITION = b'CRaceTrackSplineTransitionComponentData'
APP_QUIT = None                # fermeture propre de la fenetre de l'application (app.py), pour une mise a jour
WRITE_LOCK = threading.Lock()


def track_pak(track):
    return track.lower() + '.pak'


def race_file(track):
    """Fichier qui porte le parcours : _RaceSystem ; T231, T243 et leurs copies : _Race_System ; T212, T213, T221, T223,
    T232, T241, T255 et leurs copies : _Design (le meme fichier sert alors aux deux, voir save_track)."""
    usual = f'maps/Octane/{track}/{track}_RaceSystem.igz'
    try:
        index = pak_tool.cached_archive(os.path.join(ARCHIVES, track_pak(track)))[1]
    except OSError:
        return usual
    for logical in (usual, f'maps/Octane/{track}/{track}_Race_System.igz', start_finish.design_file(track)):
        if logical.lower() in index:
            return logical
    return usual


def race_ns(track):
    """Espace de noms du fichier de course (nom sans extension)."""
    return os.path.splitext(os.path.basename(race_file(track)))[0]


def ttr_file(track):
    return f'ttrStats/{track}_TTRStats.igz'


def collision_file(track):
    return f'models/maps/Octane/{track}/StaticCollision_{track}.hkx'


_dir_names = {}                # dossier -> (date, {nom minuscule: nom}) : casse des fichiers deja ecrits


def ci_path(folder, name):
    """folder/name sans tenir compte de la casse, comme sous Windows : sous Linux, le fichier existant qui a ce nom
    a la casse pres (les noms logiques arrivent en minuscules du manifeste ou avec la casse de l'archive)."""
    p = os.path.join(folder, name)

    # Windows deja insensible ; nom exact present : rien a chercher
    if os.name == 'nt' or os.path.exists(p):
        return p
    try:
        stamp = os.stat(folder).st_mtime_ns
    except OSError:
        return p
    hit = _dir_names.get(folder)

    # liste relue seulement si le dossier a change (ajout / retrait)
    if not hit or hit[0] != stamp:
        hit = _dir_names[folder] = (stamp, {n.lower(): n for n in os.listdir(folder)})
    return os.path.join(folder, hit[1].get(name.lower(), name))


def saved_path(logical):
    return ci_path(OUT_DIR, os.path.basename(logical))


def list_tracks():
    out = []
    for f in sorted(os.listdir(ARCHIVES)):
        m = re.match(r'^(t\d{3}_[a-z_]+)\.pak$', f)
        if m and 'flyby' not in f:
            arc = pak_tool.IgaArchive(os.path.join(ARCHIVES, f))
            names = [e.logical_name for e in arc.entries if e.logical_name.lower().endswith(('_racesystem.igz', '_race_system.igz'))]
            designs = [e.logical_name for e in arc.entries if e.logical_name.lower().endswith('_design.igz')
                       and e.logical_name.lower().startswith('maps/')]
            arc.f.close()
            # sans fichier de course : parcours dans le _Design (T212, T213...), s'il a bien des transitions
            names += [d for d in designs if not names and RACE_TRANSITION in pak_tool.read_latest(ARCHIVES, d, f)[0]]
            if names:
                out.append(names[0].split('/')[2])
    return out


def base_file(track, logical):
    """(octets, source) : version sauvee si elle existe, sinon original le plus recent."""
    p = saved_path(logical)
    if os.path.exists(p):
        return open(p, 'rb').read(), p
    return pak_tool.read_latest(ARCHIVES, logical, track_pak(track))


def load_collision(track):
    col = {'positions': [], 'indices': []}
    try:
        hk, _ = base_file(track, collision_file(track))          # collision modifiee si enregistree
        pf = Packfile(hk)
        comp = next(o for o, c in pf.objects.items() if c == 'hknpStaticCompoundShape')
        inst, n = pf.array(comp + 0x60)
        for i in range(n):
            b = inst + i * 128
            shape = pf.ptr(b + 0x50)
            if pf.objects.get(shape) != 'hknpCompressedMeshShape':
                continue
            m, sc = pf.floats(b, 16), pf.floats(b + 0x40, 3)
            verts, tris = decode_compressed_mesh(pf, pf.ptr(shape + 0x58))
            base = len(col['positions']) // 3
            for v in verts:
                col['positions'] += [round(c * HAVOK_TO_GAME, 1) for c in transform(m, sc, v)]
            for t in tris:
                col['indices'] += [base + t[0], base + t[1], base + t[2]]
    except Exception:  # noqa: BLE001
        traceback.print_exc()
    col['pending'] = collision_pending(track)      # sol affiche en retard sur le decor jusqu'a « Enregistrer »
    return col


def load_track(track):
    data, src = base_file(track, race_file(track))
    rs = RaceSystem(data, file_ns=race_ns(track)).decode()
    ed = RaceSystemEditor(data, track)
    splines = [dict(s, kind=k) for k in ('position_paths', 'ai_paths') for s in rs[k]]
    transitions = []
    for t in rs['transitions']:
        links = ed.transition_paths(t['name'])
        pos, yaw, dims = start_finish.transition_pose(ed, t['name'])
        transitions.append(dict(t, **links, position=pos, yaw=yaw, dimensions=dims))
    try:
        gf = grid_file(track)
        grid = start_finish.read_grid(data if gf == race_file(track) else base_file(track, gf)[0])
    except KeyError:
        grid = []
    try:
        player_start = start_finish.read_player_start(base_file(track, start_finish.main_map_file(track))[0])
    except KeyError:
        player_start = None
    try:
        ttr_data, _ = base_file(track, ttr_file(track))
        starting = TTRStatsEditor(ttr_data).starting_splines()
    except KeyError:
        starting = []
    try:
        crates = read_track_crates(track)
    except KeyError:
        crates = []
    cols = iter(boost_colors(track))                   # couleur de la plaque au sol de chaque booster
    for c in crates:
        if c['kind'] == 'boost':
            c['color'] = next(cols, 'bleu' if c.get('super') else 'orange')
    return {'track': track, 'source': src, 'saved': src.startswith(OUT_DIR), 'splines': splines,
            'transitions': transitions, 'forks': rs['fork_checkers'], 'player_starts': rs['player_starts'],
            'starting_splines': starting, 'start_grid': grid, 'player_start': player_start, 'crates': crates,
            'teleporters': teleporters_of(track, ed), 'portals': portals_of(track, ed), 'flyby': flyby_info(track), 'original_start': original_start(track),
            'collision': load_collision(track), 'fall_zones': read_fall_zones(track)}


# -- zones de chute (CEntity + CTriggerVolumeBoxComponentData + CRespawnTriggerComponentData du _Design) -----------
# Visibles et modifiables dans l'editeur (mode Course) : un raccourci pris au-dessus d'une zone « sans sol a cote de
# la route » faisait reapparaitre le kart (T901 Boo Lake). Boite alignee sur les axes, centree sur l'entite,
# _dimensions = tailles completes. Supprimer = ecarter sous la carte (FAR_BELOW), comme les zones auto en trop.
def read_fall_zones(track):
    """[{name, pos, dims, points}] des zones de chute en place (pas celles ecartees sous la carte)."""
    try:
        dz = IgzFile(base_file(track, start_finish.design_file(track))[0])
    except KeyError:
        return []
    out = []
    for name, ent in dz.root_objects():
        if not name or dz.objects.get(ent) not in DESIGN_ENTITY_TYPES:
            continue
        rt = _component(dz, ent, 'CRespawnTriggerComponentData')
        box = _component(dz, ent, 'CTriggerVolumeBoxComponentData') if rt is not None else None
        if box is None:
            continue
        pos = [round(v, 1) for v in dz.vec3(ent + 0x20)]
        if pos[2] < FAR_BELOW / 2:
            continue
        lst = dz.deref(rt + _field(dz, 'CRespawnTriggerComponentData', '_respawnPoints'))
        points = [h[0] for h in dz.handle_list(lst) if h]               # (nom, espace)
        out.append({'name': name, 'pos': pos, 'dims': [round(v, 1) for v in dz.vec3(dz.find_field(box, '_dimensions')[0])],
                    'points': points})
    return out


def write_fall_zones(track, zones):
    """Zones modifiees dans l'editeur : [{name, pos, dims, deleted}] -> _Design enregistre. -> lignes du rapport."""
    logical = start_finish.design_file(track)
    dz = IgzFile(base_file(track, logical)[0])
    roots = {n: o for n, o in dz.root_objects() if n}
    moved = removed = 0
    for z in zones:
        ent = roots.get(z.get('name'))
        box = _component(dz, ent, 'CTriggerVolumeBoxComponentData') if ent is not None else None
        if box is None:
            continue
        if z.get('deleted'):
            p = list(dz.vec3(ent + 0x20))
            struct.pack_into('<3f', *dz._loc(ent + 0x20), p[0], p[1], FAR_BELOW)
            removed += 1
            continue
        struct.pack_into('<3f', *dz._loc(ent + 0x20), *[float(c) for c in z['pos']])
        struct.pack_into('<3f', *dz._loc(dz.find_field(box, '_dimensions')[0]), *[max(100.0, float(c)) for c in z['dims']])
        moved += 1
    open(saved_path(logical), 'wb').write(dz.to_bytes())
    return [f'zones de chute : {moved} placée(s)' + (f', {removed} supprimée(s)' if removed else '')]


# -- teleporteurs (mecanisme de Spyro Circuit, voir teleport.py) ---------------------------------
def transition_ents(ed):
    """{nom: entite} des transitions. Le script de teleportation pose sur un autre objet (Teleporter_02 de T255) n'en
    fait pas partie : voir portals_of."""
    return {n: ed.by_name[n] for n in ed.transitions() if ed.igz.objects.get(ed.by_name[n]) in DESIGN_ENTITY_TYPES}


def _arrival_pose(dz, roots, arrival):
    """(position, cap) de l'entite d'arrivee du _Design ; (None, 0) si elle n'existe pas."""
    ent = roots.get(arrival)
    if ent is None:
        return None, 0.0
    tr = dz.deref(ent + 0x30)
    return [round(v, 2) for v in dz.vec3(ent + 0x20)], round(struct.unpack_from('<f', *dz._loc(tr + 0x68))[0], 5) if tr is not None else 0.0


def portals_of(track, ed):
    """Teleporteurs qui ne sont pas des transitions (Teleporter_02 de T255) : ils n'ont aucun lien avec le parcours.
    {nom: {position, yaw, dimensions, arrival: {name, pos, yaw}}} ; pas ceux ecartes sous la carte."""
    trans = ed.transitions()
    ents = {n: o for n, o in ed.by_name.items() if n not in trans and ed.igz.objects.get(o) in DESIGN_ENTITY_TYPES}
    tps = teleport.read_teleporters(ed.igz, ents)
    if not tps:
        return {}
    dz = IgzFile(base_file(track, start_finish.design_file(track))[0])
    roots = {n: o for n, o in dz.root_objects() if n}
    out = {}
    for name, arrival in tps.items():
        pos, yaw, dims = start_finish.transition_pose(ed, name)
        if pos[2] <= FAR_BELOW + 1:
            continue
        apos, ayaw = _arrival_pose(dz, roots, arrival)
        out[name] = {'position': pos, 'yaw': yaw, 'dimensions': dims, 'arrival': {'name': arrival, 'pos': apos, 'yaw': ayaw}}
    return out


def apply_portals(track, ed, rs_data, portals):
    """Zones et arrivees modifiees dans l'editeur. Arrivee deplacee : entite propre a ce portail, car elle peut etre
    partagee (Teleport_Destination_02 sert aussi a la transition Teleporter_01). -> lignes du rapport."""
    report, arrivals, current = [], {}, portals_of(track, ed)
    near = lambda a, b: all(abs(x - y) < 1e-3 for x, y in zip(a, b))
    for name, p in portals.items():
        cur = current.get(name)
        if cur is None:
            continue
        if p.get('deleted'):
            start_finish.set_transition_pose(ed, name, pos=cur['position'][:2] + [FAR_BELOW])
            report.append(f'{name} : portail supprimé (écarté sous la carte)')
            continue
        pos, yaw, dims = p.get('position', cur['position']), p.get('yaw', cur['yaw']), p.get('dimensions', cur['dimensions'])
        if not near(pos + [yaw] + list(dims or []), cur['position'] + [cur['yaw']] + list(cur['dimensions'] or [])):
            start_finish.set_transition_pose(ed, name, pos, yaw if ed.igz.deref(ed.by_name[name] + 0x30) is not None else None, dims)
            report.append(f'{name} : zone du portail modifiée')
        a, ca = p.get('arrival') or {}, cur['arrival']
        if a.get('pos') and (ca['pos'] is None or not near(a['pos'] + [a.get('yaw') or 0.0], ca['pos'] + [ca['yaw']])):
            arrivals[name] = a
    if arrivals:
        _write_arrivals(track, ed, rs_data, {teleport.dest_name(n): a for n, a in arrivals.items()})
        for n, a in arrivals.items():
            teleport.set_destination(ed.igz, ed.by_name[n], teleport.dest_name(n), f'{track}_Design')
            report.append(f'{n} : arrivée du portail placée ({", ".join(str(round(c)) for c in a["pos"])})')
    return report


def teleporters_of(track, ed):
    """{transition: {'arrival': entite du _Design, 'pos', 'yaw'}} des transitions teleporteurs."""
    tps = teleport.read_teleporters(ed.igz, transition_ents(ed))
    if not tps:
        return {}
    try:
        dz = IgzFile(base_file(track, start_finish.design_file(track))[0])
    except KeyError:
        dz = None
    roots = {n: o for n, o in dz.root_objects() if n} if dz else {}
    out = {}
    for tname, arrival in tps.items():
        pos, yaw = _arrival_pose(dz, roots, arrival) if dz else (None, 0.0)
        out[tname] = {'arrival': arrival, 'pos': pos, 'yaw': yaw}
    return out


def apply_teleporters(track, ed, want, rs_data):
    """Teleporteurs voulus : want = {transition: {'pos': [x, y, z], 'yaw'}} (les autres redeviennent ordinaires).
    Arrivees = entites du _Design clonees d'un point de reapparition (ecrit tout de suite) ; RaceSystem modifie
    dans ed (ecrit par save_track). Retourne les lignes du rapport."""
    report = []
    ents = transition_ents(ed)
    current = teleport.read_teleporters(ed.igz, ents)
    for tname in current:
        if tname not in want and teleport.clear_teleporter(ed.igz, ents[tname]):
            report.append(f'{tname} : plus un téléporteur')
    want = {t: w for t, w in want.items() if t in ents and w.get('pos')}
    if not want:
        return report
    _write_arrivals(track, ed, rs_data, {teleport.dest_name(t): w for t, w in want.items()})
    # RaceSystem : drapeau, script de teleportation, handle vers l'arrivee
    src = teleport.donor(lambda lg, pak: pak_tool.read_latest(ARCHIVES, lg, pak)[0])
    for t, w in want.items():
        teleport.set_teleporter(ed.igz, ents[t], t, teleport.dest_name(t), f'{track}_Design', src)
        report.append(f'{t} : téléporteur vers ({", ".join(str(round(c)) for c in w["pos"])})')
    return report


def _write_arrivals(track, ed, rs_data, want):
    """Arrivees des teleporteurs : want = {nom de l'entite : {'pos', 'yaw'}}, creees au besoin. Dans le _Design : entite
    sans composant, comme Destination_01 de Spyro Circuit."""
    design = start_finish.design_file(track)
    same_file = design == race_file(track)                 # parcours dans le _Design : un seul fichier en cours d'edition
    dz = ed.igz if same_file else IgzFile(base_file(track, design)[0])
    roots = {n: o for n, o in dz.root_objects() if n}
    missing = [n for n in want if n not in roots]
    if missing:
        rs = RaceSystem(rs_data, file_ns=race_ns(track)).decode()
        respawns = [str(r).split('::')[-1] for s in rs['position_paths'] for r in (s.get('respawn_points') or [])]
        cands = [n for n in respawns if n in roots]
        template = next((n for n in cands if f'{n}_camera' not in roots), cands[0] if cands else None)
        if template is None:                               # pas de point de reapparition : un repere sans composant
            template = _plain_marker(dz)
        if template is not None:
            owned = dz.owned_by(DESIGN_ENTITY_TYPES)
            names = {o: n for n, o in dz.root_objects()}
            pairs = []
            for n in missing:
                pairs += dz.clone_owned(roots[template], n, owned[roots[template]], names)[1]
            dz.add_roots(pairs)
        else:
            # _Design sans aucun repere (Roo's Tubes : creatures animees et grille seulement) : repere importe du
            # _Design de Crash Cove (copie d'entite d'un autre fichier, comme les boosters)
            T = 'T111_Crash_Cove'
            donor = IgzFile(pak_tool.read_latest(ARCHIVES, start_finish.design_file(T), track_pak(T))[0])
            dn = _plain_marker(donor)
            if dn is None:
                raise ValueError('aucun repère à copier pour l\'arrivée du téléporteur')
            src_ent = dict(donor.root_objects())[dn]
            for n in missing:
                dz.import_entity(donor, src_ent, n, old_name=dn)
        roots = {n: o for n, o in dz.root_objects() if n}
    for n, w in want.items():
        _set_pose(dz, roots[n], [float(c) for c in w['pos']], float(w.get('yaw') or 0.0))
    if same_file:
        ed._names()
    else:
        safe_compact(track, design, dz)
        dz.save(saved_path(design))


def _plain_marker(z):
    """Nom d'une entite repere du fichier : avec transformation et sans composant (point de reapparition
    CPlayerStartEntity de Crash Cove, Destination_01 CEntity de Spyro Circuit), ou None."""
    for n, o in sorted((n, o) for n, o in z.root_objects() if n):
        if z.objects.get(o) not in ('CEntity', 'CPlayerStartEntity') or z.deref(o + 0x30) is None or n.endswith('_camera'):
            continue
        data = z.deref(o + 0x40)
        table = z.deref(data + 0x10) if data is not None else None
        if table is not None and not z.hash_items(table):
            return n
    return None


def teleport_install_files(track):
    """(entrees du manifeste, {chemin: archive source} a copier) si la piste enregistree a des teleporteurs."""
    p = saved_path(race_file(track))
    if not os.path.exists(p):
        return [], {}
    ed = RaceSystemEditor(open(p, 'rb').read(), track)
    # un teleporteur retire laisse ses dependances (TDEP : script, effet) dans le RaceSystem : sans ces fichiers,
    # le jeu refuse de charger le RaceSystem (« Required file ... failed to load », plantage au chargement : T902)
    tdep = ed.igz.fixups.get('TDEP', (0, b''))[1]
    if not teleport.read_teleporters(ed.igz, {n: o for n, o in ed.by_name.items()
                                              if ed.igz.objects.get(o) in DESIGN_ENTITY_TYPES}) \
            and b'common_teleport_entity' not in tdep:
        return [], {}
    copies = {}
    for _, lg in teleport.FILES:
        if not library.available(ARCHIVES, lg, track_pak(track)):
            src = library.find_pak(ARCHIVES, lg, (teleport.DONOR[0],))
            if src is None:
                raise KeyError(f'fichier du téléporteur introuvable dans les archives : {lg}')
            copies[_archive_case(src, lg)] = src
    return list(teleport.FILES), copies


# -- survol d'introduction (cinematique avant la course, voir flyby.py) ----------------------------
_flyby_cache = {}


def flyby_path(track):
    return os.path.join(OUT_DIR, f'{track}_flyby.json')


def flyby_shots(track):
    """[{'key' (chemin logique de la camera), 'pak', 'label', 'frames', 'duration', 'final', 'original'}] des plans
    des archives de survol de la piste (le dernier plan de chaque survol est le plan final, sur la grille)."""
    if track not in _flyby_cache:
        shots = []
        for pak in flyby.flyby_paks(os.listdir(ARCHIVES), track):
            arc, idx, _ = pak_tool.cached_archive(os.path.join(ARCHIVES, pak))
            cams = sorted((e.logical_name for e in arc.entries if flyby.is_camera(e.logical_name)), key=str.lower)
            short = 'short' in pak.lower()
            for k, lg in enumerate(cams):
                cam = flyby.read_camera(pak_tool.read_latest(ARCHIVES, lg, pak)[0])
                shots.append({'key': lg, 'pak': pak, 'frames': len(cam['times']),
                              'duration': round(cam['times'][-1] + 1 / 30, 2), 'final': k == len(cams) - 1,
                              'label': ('Survol court' if short else 'Survol') + (f' · plan {k + 1}' if len(cams) > 1 else ''),
                              'original': flyby.model_of(cam)})
        _flyby_cache[track] = shots
    return _flyby_cache[track]


def load_flyby(track):
    try:
        return json.load(open(flyby_path(track), encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def flyby_info(track):
    """Plans pour l'editeur : modele courant (enregistre, sinon celui d'origine) et s'il est modifie."""
    saved = load_flyby(track)
    return [dict(s, model=saved.get(s['key'], s['original']), custom=s['key'] in saved) for s in flyby_shots(track)]


def apply_flyby(track, models):
    """Enregistre les plans modifies : models = {cle: {'start', 'end'}} (absents : plan d'origine). Cameras
    reecrites depuis l'original (memes cles, meme minutage)."""
    shots = {s['key']: s for s in flyby_shots(track)}
    models = {k: m for k, m in (models or {}).items() if k in shots}
    for key, s in shots.items():
        p = saved_path(key)
        if key in models:
            data = pak_tool.read_latest(ARCHIVES, key, s['pak'])[0]
            open(p, 'wb').write(flyby.write_camera(data, models[key]))
        elif os.path.exists(p):
            os.remove(p)
    if models:
        json.dump(models, open(flyby_path(track), 'w', encoding='utf-8'), indent=1)
    elif os.path.exists(flyby_path(track)):
        os.remove(flyby_path(track))
    return [f'survol : {len(models)} plan(s) modifié(s)' if models else 'survol : plans d\'origine']


def flyby_auto(req):
    """Plans proposes d'apres le parcours enregistre : req = {track, mode: 'auto' | 'fixed'} -> {cle: modele}."""
    track = req['track']
    shots = flyby_shots(track)
    if not shots:
        raise ValueError('aucune archive de survol pour cette piste')
    path, tr = race_path_points(track)
    fin = next((t for t in tr['transitions'] if t['increment_lap']), None)
    if fin is None or len(path) < 2:
        raise ValueError('pas de parcours enregistré (ligne d\'arrivée reliée aux splines de position)')
    grid = tr.get('start_grid') or []
    gc = np.mean([g['pos'] for g in grid], axis=0) if grid else None
    g = ground_for(track)
    ground = lambda x, y, z: g.top(x, y, z)
    spec = [(s['key'], s['frames'], s['final']) for s in shots]
    finish = (fin['position'], fin.get('yaw') or 0.0)
    models = flyby.fixed_models(spec, finish, gc, ground) if req.get('mode') == 'fixed' \
        else flyby.auto_models(path, spec, finish, gc, ground)
    return {'models': models}


FLYBY_FINAL_MAX = 100 * 39.37    # fin du dernier plan <-> centre de la grille : 28 a 67 m sur toutes les pistes du jeu


def flyby_far_from_grid(track, tr=None):
    """Distance (m) entre la grille et la fin du dernier plan le plus eloigne, si elle depasse FLYBY_FINAL_MAX ; 0 sinon."""
    tr = tr or load_track(track)
    grid = tr.get('start_grid') or []
    if not grid:
        return 0
    gc = np.mean([g['pos'] for g in grid], axis=0)
    d = max((float(np.linalg.norm(np.asarray(s['model']['end']['pos']) - gc)) for s in tr.get('flyby') or [] if s['final']),
            default=0.0)
    return d / 39.37 if d > FLYBY_FINAL_MAX else 0


def fix_flyby(track):
    """Plans generes d'apres le parcours. Les plans deja refaits restent, sauf si le survol ne finit plus sur la grille."""
    models = flyby_auto({'track': track, 'mode': 'auto'})['models']
    if not flyby_far_from_grid(track):
        models.update(load_flyby(track))
    return apply_flyby(track, models)[0]


def flyby_install_files(track):
    """{archive: {camera: octets}} des plans modifies (archives de survol de la piste, et mises a jour qui les
    contiendraient). Cameras recalculees a chaque installation depuis les poses memorisees : les fichiers ecrits
    avant la correction du sens du tangage (camera qui regardait le ciel) sont refaits justes sans rien rouvrir."""
    out = defaultdict(dict)
    models = load_flyby(track)
    for s in flyby_shots(track):
        if s['key'] in models:
            data = flyby.write_camera(pak_tool.read_latest(ARCHIVES, s['key'], s['pak'])[0], models[s['key']])
            open(saved_path(s['key']), 'wb').write(data)
            for arc in pak_tool.archives_with(ARCHIVES, s['key'], s['pak']):
                out[arc][s['key']] = data
    return out


_grid_file_cache = {}


def grid_file(track):
    """Fichier qui porte la grille de depart : le _Design (Crash Cove, Roo's Tubes...) ou, pour 8 pistes, le
    _RaceSystem (Sewer Speedway, Dingo Canyon, Android Alley...). D'apres les fichiers d'origine."""
    if track not in _grid_file_cache:
        read = lambda lg: pak_tool.read_latest(ARCHIVES, lg, track_pak(track))[0]
        try:
            in_design = bool(start_finish.read_grid(read(start_finish.design_file(track))))
        except KeyError:
            in_design = False
        _grid_file_cache[track] = start_finish.design_file(track) if in_design else race_file(track)
    return _grid_file_cache[track]


def original_start(track):
    """Grille, repere de depart et ligne d'arrivee du jeu d'origine : « Replacer la grille derriere la ligne » part
    de cette disposition (la version enregistree peut avoir une ligne deplacee sans la grille : Roo's Tubes, dont la
    grille « AIWaypoint001.. » n'etait pas reconnue). None si incomplet."""
    try:
        read = lambda lg: pak_tool.read_latest(ARCHIVES, lg, track_pak(track))[0]
        grid = start_finish.read_grid(read(grid_file(track)))
        ed = RaceSystemEditor(read(race_file(track)), track)
        fin = next(t for t in RaceSystem(read(race_file(track)), file_ns=race_ns(track)).decode()['transitions']
                   if t['increment_lap'])
        pos, yaw, _ = start_finish.transition_pose(ed, fin['name'])
        ps = start_finish.read_player_start(read(start_finish.main_map_file(track)))
    except (KeyError, StopIteration):
        return None
    return {'grid': grid, 'ps': ps, 'finish': {'position': pos, 'yaw': yaw}} if grid else None


def _orphan_points(z):
    """[(nom, objet)] des points de spline encore en liste racine mais qu'aucune spline n'utilise."""
    roots = z.root_objects()
    used = set()
    for _, o in roots:
        if z.objects.get(o) != 'igSplineControlPoint2':
            used |= z.reachable(o)[0]
    return [(n, o) for n, o in roots if z.objects.get(o) == 'igSplineControlPoint2' and o not in used]


def drop_orphan_points(track, z):
    """Fichier de course : points retires des splines par l'editeur (spline_edit.remove_point les laisse en liste racine, 2 207
    points stockes pour 590 utilises sur T113). Ceux du fichier d'origine (1 a 8 par piste) et ceux cites par nom sont gardes.
    -> nombre de points retires (blocs liberes par safe_compact)."""
    try:
        native = {n for n, _ in _orphan_points(IgzFile(pak_tool.read_latest(ARCHIVES, race_file(track), track_pak(track))[0]))}
    except KeyError:
        return 0
    cited = {n for n, _ in z.ext_names}
    drop = [o for n, o in _orphan_points(z) if n not in native and n not in cited]
    if drop:
        z.remove_roots(drop)
    return len(drop)


def set_points(ed, name, pts):
    cur = ed.points(name)
    while len(cur) > len(pts):
        ed.remove_point(name, len(cur) - 1)
        cur = ed.points(name)
    if len(cur) < len(pts):
        ed.extend_points(name, pts[len(cur):])
        cur = ed.points(name)
    moved = 0
    for i, p in enumerate(pts):
        if any(abs(p[k] - cur[i][k]) > 1e-3 for k in range(3)):
            ed.move_point(name, i, p)
            moved += 1
    return moved


_ground_cache = {}
FAR_BELOW = -100000.0          # entites ecartees (zones de chute, embranchements) : sous la carte, jamais atteintes


def ground_key(track):
    """Empreinte de la collision enregistree (change quand le decor ou la collision change)."""
    import hashlib
    ensure_collision(track)
    return hashlib.md5(base_file(track, collision_file(track))[0]).hexdigest()


def ground_for(track):
    """Sol (collision enregistree, decor importe compris), en cache tant qu'il ne change pas."""
    ensure_collision(track)                     # modifications en attente (collision differee) : sol a jour
    hk = base_file(track, collision_file(track))[0]
    key = ground_key(track)
    if key not in _ground_cache:
        _ground_cache.clear()
        _ground_cache[key] = ai_gen.GroundQuery.from_hkx(hk)
    return _ground_cache[key]


def route_layout(req):
    """Parcours deduit de la route, sans spline existante. req = {track, source: {objects: [{file, id}]} |
    {surfaces: [..]}, start: [x, y], heading (rad), reverse, sections, respawns: [[noms de la section k]]}.
    -> boucle, points des splines de position, transitions, reapparitions et entites a ecarter."""
    track = req['track']
    src = req.get('source') or {}
    dropped = []
    if src.get('objects'):                               # ids -> noms (les ids changent a chaque reecriture du decor)
        named = []
        for ref in src['objects']:
            df = DecorFile(base_file(track, ref['file'])[0])
            if int(ref['id']) not in df.names:
                raise ValueError(f"objet {ref['id']} introuvable (enregistre le decor d'abord)")
            one = {'file': ref['file'], 'name': df.names[int(ref['id'])]}
            # decor de fond (montagnes, ciel, sol lointain : plusieurs km) pris dans la selection, souvent par un clic
            # sur la map qui touche ce grand maillage : ecarte au lieu de faire echouer toute la route
            T = road_tris(track, {'objects': [one]})
            ext = float((T[:, :, :2].max((0, 1)) - T[:, :, :2].min((0, 1))).max()) if len(T) else 0.0
            if ext > route_gen.MAX_EXTENT:
                dropped.append(f"{one['name']} ({ext / 39.37:.0f} m)")
            else:
                named.append(one)
        if not named and dropped:
            raise ValueError(f"la sélection ne contient que du décor géant ({', '.join(dropped)}) : coche ou "
                             f"sélectionne l'objet de la ROUTE (nom contenant « Road »)")
        src = {'objects': named}
    progress.step('lecture de la route', 0.02)
    tris = road_tris(track, src)
    bad = None
    try:
        if not len(tris):                                 # surfaces sous un ancien trace loin de la map importee
            raise ValueError('aucun triangle de route sous le tracé actuel')
        route_gen.check_extent(tris)                      # avant de lire le sol (long sur une map geante)
    except ValueError as e:
        if not len(tris) and not _road_candidates(track, src):
            raise
        # route minuscule (ligne de depart choisie) ou geante (surfaces du sol d'une map importee qui couvrent aussi
        # le decor de fond) : route importee / memorisee essayee a la place (plus bas) ; geante sans autre choix :
        # erreur tout de suite, avant de lire le sol (tres long sur une map geante)
        if 'geante' in str(e) and not _road_candidates(track, src):
            raise
        bad = e
    progress.step('lecture du sol', 0.05)
    ground = ground_for(track)
    # plancher enregistre = celui de « Chutes et reapparitions » d'un parcours precedent (refait apres celui-ci) :
    # seul celui du jeu (ou plus bas) borne la route ; une map deplacee plus bas que l'ancien parcours restait refusee
    kz_saved = world_killz(track)
    kz = min(kz_saved, world_killz(track, original=True))
    if len(tris) and float(np.median(tris[:, :, 2])) < kz:
        raise ValueError(f'la route est a z = {float(np.median(tris[:, :, 2])):.0f}, sous le plancher de chute du monde '
                         f'({kz:.0f}) : les karts y seraient « tombes ». Remonte la map (mode Decor), ou refais « Chutes '
                         f'et reapparitions » apres avoir cree le parcours.')
    heading = float(req.get('heading', 0)) + (math.pi if req.get('reverse') else 0.0)
    start = req['start']
    z0 = None
    if len(start) > 2:                                  # sol sous la ligne d'arrivee (zone placee au-dessus du sol)
        g0 = ground.at(start[0], start[1], start[2] - 660, window=1500.0)
        z0 = g0[0] if g0 else None
    note = None
    max_gap = max(0.0, float(req.get('max_jump', 40))) * 39.37     # trous franchis (sauts), en m
    guide = req.get('guide')                            # trace dessine sur l'apercu de dessus (editeur)
    exact = req.get('exact')                            # ligne centrale connue (onglet Creation : [[x, y, z, largeur]])
    try:
        if exact:
            loop = exact_loop(exact)
        else:
            if bad:
                raise bad
            with progress.span(0.15, 0.9):
                loop = route_gen.road_loop(tris, start[:2], heading, ground=ground, start_z=z0, max_gap=max_gap,
                                           min_z=kz, guide=guide)
    except ValueError as e:
        if guide or exact:
            raise
        # selection qui n'est pas la route (ex. « START_LINE2 », le decor de la ligne de depart, ou les surfaces du
        # sol d'une map importee) : essai avec la route importee (materiau « road »)
        found = None
        for cand in _road_candidates(track, src):
            try:
                ctris = road_tris(track, cand)
                route_gen.check_extent(ctris)
                with progress.span(0.15, 0.9, f"essai avec {cand['objects'][0]['name']}"):
                    found = (cand, ctris, route_gen.road_loop(ctris, start[:2], heading, ground=ground, start_z=z0,
                                                                          max_gap=max_gap, min_z=kz))
                break
            except ValueError:
                continue
        if not found:
            raise ValueError(f'{e} — la selection ne forme pas un circuit ferme : en mode Decor, selectionne la ROUTE '
                             f'importee (objet dont le nom contient « Road »), pas la ligne de depart ou le decor') from None
        what = ', '.join(o['name'] for o in src.get('objects', [])) or 'les surfaces du sol'
        src, tris, loop = found
        note = f"{what} ne forme pas un circuit ferme : route utilisee a la place : {src['objects'][0]['name']}"
    # boucle qui ne couvre qu'une petite partie de la route (route coupee par des trous : petite boucle d'une place
    # ou d'un rond-point, 333 m sur une route de 1,6 km) : second essai en franchissant des trous plus grands
    ext = lambda P: float((np.asarray(P)[..., :2].reshape(-1, 2).max(0) - np.asarray(P)[..., :2].reshape(-1, 2).min(0)).max()) \
        if len(P) else 0.0
    if ext(loop['points']) < 0.5 * ext(tris) and max_gap < 80 * 39.37 and not guide and not exact:
        try:
            with progress.span(0.9, 0.97, 'boucle trop petite : essai en franchissant des trous jusqu\'à 80 m'):
                wide = route_gen.road_loop(tris, start[:2], heading, ground=ground, start_z=z0, max_gap=80 * 39.37, min_z=kz)
            if wide['length'] > 1.5 * loop['length']:
                note = (note + ' ; ' if note else '') + (f"la route choisie est coupée par des trous de plus de "
                                                         f"{max_gap / 39.37:.0f} m : franchis jusqu'à 80 m ({loop['length'] / 39.37:.0f}"
                                                         f" m → {wide['length'] / 39.37:.0f} m). Vérifie les sauts (Visite virtuelle)")
                loop = wide
        except ValueError:
            pass
    if ext(loop['points']) < 0.5 * ext(tris) and not guide and not exact:
        note = (note + ' ; ' if note else '') + (f"ATTENTION : le tour trouvé ({loop['length'] / 39.37:.0f} m) ne couvre qu'une "
                                                 f"petite partie de la route choisie ({ext(tris) / 39.37:.0f} m d'un bout à l'autre) : "
                                                 f"coche aussi les morceaux qui bouchent ses trous (pont, autre matériau) ou augmente "
                                                 f"« Franchir les trous »")
    if loop.get('marched'):
        note = (note + ' ; ' if note else '') + 'route superposée à elle-même (spirale) : tour suivi en 3D'
    if dropped:
        note = (note + ' ; ' if note else '') + f"décor de fond écarté de la sélection : {', '.join(dropped)}"
    low = min(p[2] for p in loop['points'])
    if low - 1000 < kz_saved:
        note = (note + ' ; ' if note else '') + (f'plancher de chute enregistré (z = {kz_saved:.0f}) trop près ou au-dessus '
                                                 f'du parcours (plus bas : {low:.0f}) : refais « Chutes et réapparitions » '
                                                 f'(ou « Vérifier » → corriger)')
    progress.step('sections et réapparitions', 0.9)
    if loop.get('obstacles'):
        note = (note + ' ; ' if note else '') + (f"tracé écarté d'objets solides posés sur la route "
                                                 f"({loop['obstacles']} point(s) déplacé(s))")
    obs = ai_gen.Obstacles(ground)
    lay = route_gen.layout(loop, max(1, int(req.get('sections', 4))), avoid=obs.crosses)
    respawns = {}
    for k, names in enumerate(req.get('respawns') or []):
        if k < len(lay['section_paths']) and names:
            poses = route_gen.spread_on_path(lay['section_paths'][k], len(names))
            respawns.update(zip(names, _respawns_on_ground(poses, lay['section_paths'][k], ground)))
    design_moves, race_moves = old_route_moves(track)
    if src.get('objects'):                               # route memorisee : sert aussi aux splines IA
        os.makedirs(OUT_DIR, exist_ok=True)
        json.dump(src, open(road_source_path(track), 'w'), indent=1)
    return {'loop': loop['points'], 'length': round(loop['length']), 'sections': lay['sections'], 'note': note,
            'transitions': lay['transitions'], 'respawns': respawns, 'design_moves': design_moves,
            'race_moves': race_moves, 'jumps': loop.get('jumps', 0), 'preview': loop.get('preview')}


def exact_loop(line, step=300.0):
    """Boucle de route_gen.road_loop tiree d'une ligne centrale connue (onglet Creation) : [[x, y, z, largeur]]
    (pouces, depart en premier, sens de course) -> points tous les ~step po, demi-largeurs, rien en l'air."""
    E = np.asarray(line, np.float64)
    if len(E) < 4:
        raise ValueError('ligne centrale trop courte')
    Q = np.vstack([E, E[:1]])
    cum = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(Q[:, :2], axis=0), axis=1))])
    total = float(cum[-1])
    s = np.arange(0, total, step)
    R = np.stack([np.interp(s, cum, Q[:, j]) for j in range(Q.shape[1])], 1)
    pts = R[:, :3].tolist()
    air = (R[:, 4] > 0.5).tolist() if R.shape[1] > 4 else [False] * len(pts)          # 5e colonne : saut
    return {'points': pts, 'half_widths': (R[:, 3] / 2).tolist(), 'length': total, 'air': air,
            'jumps': sum(1 for i in range(len(air)) if air[i] and not air[i - 1]), 'obstacles': 0}


# -- point de depart du parcours : objet « Start / Finish », sinon damier, sinon ligne d'arrivee actuelle -----------
START_NAME_RE = re.compile(r'start|finish|goal|d[ée]part|arriv', re.I)
START_MAX_SIZE = 80 * 39.37              # po : une ligne de depart en damier ; au-dela, c'est la route entiere
START_NAMED_MAX = 150 * 39.37            # po : objet nomme Start / Finish (ligne + arche, tribunes : Boo Lake 93 m)
_checker_cache, _model_groups_cache = {}, {}


def checker_score(rgba):
    """0..1 : l'image est-elle un damier ? Binarisee a la mediane ; pour chaque taille de case s, deux cases voisines
    (s a droite, s en bas) doivent etre opposees et deux cases en diagonale identiques. Rayures, bruit, aplat ~0,5."""
    g = np.asarray(rgba, np.float32)[..., :3].mean(axis=2)
    H, W = g.shape

    def score(g):
        if g.size < 64 or np.percentile(g, 95) - np.percentile(g, 5) < 80:
            return 0.0
        b = g > np.median(g)
        if not 0.25 < b.mean() < 0.75:
            return 0.0
        best = 0.0
        for s in range(1, min(b.shape) // 2):
            h = (b[:, :-s] != b[:, s:]).mean()
            v = (b[:-s, :] != b[s:, :]).mean()
            d = (b[:-s, :-s] == b[s:, s:]).mean()
            best = max(best, min(h, v, d))
        return best
    # image entiere, moitie et quarts : damier dans une partie de la texture (bande d'un atlas)
    parts = [g, g[:H // 2], g[H // 2:], g[:, :W // 2], g[:, W // 2:],
             g[:H // 4], g[H // 4:H // 2], g[H // 2:3 * H // 4], g[3 * H // 4:]]
    return float(max(score(p) for p in parts))


def _texture_checker(track, ns):
    if ns not in _checker_cache:
        try:
            rgba, _ = preview.decode_texture(preview_read(track, f'textures/{ns}.igz'), 128)
            _checker_cache[ns] = checker_score(rgba)
        except Exception:  # noqa: BLE001 - texture illisible : pas un damier
            _checker_cache[ns] = 0.0
    return _checker_cache[ns]


def _model_groups(track, logical):
    """(positions (n, 3), indices, [(debut, nb, ns)]) d'un modele, par texture."""
    if logical not in _model_groups_cache:
        try:
            pv = preview.model_preview(model_bytes(track, logical), lambda lg: preview_read(track, lg))
            _model_groups_cache[logical] = (np.asarray(pv['positions'], np.float64).reshape(-1, 3),
                                            np.asarray(pv['indices'], np.int64),
                                            [(s, n, t[0]) for s, n, t in pv['groups'] if t])
        except Exception:  # noqa: BLE001 - modele illisible
            _model_groups_cache[logical] = (np.zeros((0, 3)), np.zeros(0, np.int64), [])
    return _model_groups_cache[logical]


def _footprint_pose(T, yaw0):
    """Triangles monde (n, 3, 3) d'une ligne de depart -> (point [x, y, z], cap, taille). La bande est en travers de la
    route : cap perpendiculaire a sa plus grande longueur, du cote de yaw0 (ligne actuelle) ; forme ronde : yaw0."""
    V = np.asarray(T, np.float64).reshape(-1, 3)
    xy = V[:, :2]
    c = (xy.min(0) + xy.max(0)) / 2
    w, vec = np.linalg.eigh(np.cov((xy - xy.mean(0)).T) if len(xy) > 2 else np.eye(2))
    proj = (xy - c) @ vec
    span = proj.max(0) - proj.min(0)
    long_axis = vec[:, int(np.argmax(span))]
    yaw = yaw0
    if span.max() > 1.5 * max(span.min(), 1.0):
        yaw = math.atan2(long_axis[1], long_axis[0]) + math.pi / 2
        if math.cos(yaw - yaw0) < 0:
            yaw += math.pi
    yaw = math.atan2(math.sin(yaw), math.cos(yaw))
    return [float(c[0]), float(c[1]), float(V[:, 2].min())], yaw, float(span.max())


def route_start_guess(track):
    """Depart propose pour « Creer le parcours » : objet du decor nomme Start / Finish (depart, arrivee, goal) ; sinon
    objet importe (modele, bibliotheque) dont une texture est un damier ; sinon rien (ligne d'arrivee actuelle).
    -> {source: 'name' | 'checker' | None, object, file, pos [x, y, z + 660 : comme une ligne d'arrivee], yaw, size_m}."""
    try:
        _, tr = race_path_points(track)
        fin = next((t for t in tr['transitions'] if t['increment_lap']), None)
    except Exception:  # noqa: BLE001 - pas de parcours : cap 0
        fin = None
    yaw0 = float((fin or {}).get('yaw') or 0.0)
    objs = [(art, o) for art in art_files(track) for o in DecorFile(base_file(track, art)[0]).objects()]
    out = lambda src, art, o, T: (lambda p, y, s: {'source': src, 'object': o['name'], 'file': art,
                                                    'pos': [p[0], p[1], p[2] + 660.0], 'yaw': y,
                                                    'size_m': round(s / 39.37, 1)})(*_footprint_pose(T, yaw0))
    size = lambda T: float((T.reshape(-1, 3)[:, :2].max(0) - T.reshape(-1, 3)[:, :2].min(0)).max()) if len(T) else 0.0

    def checker_tris(o, flat=True):
        """Triangles monde des textures en damier de l'objet ; flat : seulement s'ils sont surtout a plat (ligne sur la
        route, pas un drapeau ni un panneau vertical)."""
        P, I, groups = _model_groups(track, model_logical_path(o['model']))
        tris = [I[s:s + n] for s, n, ns in groups if _texture_checker(track, ns) > 0.8]
        if not tris:
            return None
        M = np.asarray(object_matrix(o['pos'], o['euler'], o['scale']), np.float64)
        idx = np.concatenate(tris)
        T = (P @ M[:3, :3].T + M[:3, 3])[idx[:len(idx) // 3 * 3]].reshape(-1, 3, 3)
        if not len(T):
            return None
        n = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
        area = np.linalg.norm(n, axis=1)
        flat_share = float(area[np.abs(n[:, 2]) > 0.7 * np.maximum(area, 1e-9)].sum() / max(area.sum(), 1e-9))
        return T if (flat_share > 0.5 or not flat) else None

    found = []
    for art, o in objs:
        if START_NAME_RE.search(o['name'] or '') or START_NAME_RE.search(re.split(r'[\\/]', o['model'] or '')[-1]):
            T = object_world_array(track, o)
            if len(T) and size(T) < START_NAMED_MAX:
                Tc = checker_tris(o)                      # ligne en damier de l'objet : elle seule
                found.append((size(T), art, o, Tc if Tc is not None else T))
    if found:
        _, art, o, T = min(found, key=lambda f: f[0])
        return out('name', art, o, T)
    links = load_links(track)
    for art, o in objs:
        lk = links.get(art, {}).get(str(o['id']))
        if not (isinstance(lk, dict) and ('custom' in lk or 'library' in lk)):
            continue                                      # objets importes seulement (le decor du jeu est deja juste)
        T = checker_tris(o)
        if T is not None and 0 < size(T) < START_MAX_SIZE:
            found.append((size(T), art, o, T))
    if found:
        _, art, o, T = min(found, key=lambda f: f[0])
        return out('checker', art, o, T)
    return {'source': None}


def old_route_moves(track):
    """Entites liees a l'ancien trace, a ecarter sous la carte : zones de reapparition / succes du _Design
    ({nom: {pos, yaw}}), embranchements du RaceSystem ({nom: pos})."""
    dz = base_file(track, start_finish.design_file(track))[0]
    zd = IgzFile(dz)
    trig = [n for n, o in zd.root_objects() if zd.objects.get(o) in ('CEntity', 'CGameEntity', 'igEntity')]
    design_moves = {n: {'pos': p['pos'][:2] + [FAR_BELOW], 'yaw': p['yaw']}
                    for n, p in start_finish.read_entity_poses(dz, trig).items()}
    rs = RaceSystem(base_file(track, race_file(track))[0], file_ns=race_ns(track)).decode()
    race_moves = {f['name']: f['position'][:2] + [FAR_BELOW] for f in rs['fork_checkers']}
    return design_moves, race_moves


AIR = 150.0        # po : sol a plus de ~4 m sous le trace = au-dessus d'un trou (saut) : pas de reapparition la


def _respawns_on_ground(poses, path, ground, lift=50.0):
    """Points de reapparition deplaces hors des trous : un point au-dessus du vide (saut franchi) va au point du
    chemin le plus proche qui a du sol juste dessous (sinon le kart reapparaitrait en l'air ou au fond du trou)."""
    P = np.asarray(path, np.float64)
    grounded = [ground.top(p[0], p[1], p[2] + 100) is not None and p[2] - ground.top(p[0], p[1], p[2] + 100) <= AIR
                for p in P]
    out = []
    for pose in poses:
        x, y, z = pose['pos']
        top = ground.top(x, y, z)
        if top is not None and z - lift - top <= AIR:
            out.append(pose)
            continue
        i0 = int(np.argmin(np.linalg.norm(P[:, :2] - [x, y], axis=1)))
        ok = [i for i in range(len(P)) if grounded[i]]
        if not ok:
            out.append(pose)
            continue
        i = min(ok, key=lambda k: (abs(k - i0), k < i0))       # le plus proche, de preference apres (la reception)
        t = P[min(i + 1, len(P) - 1), :2] - P[max(i - 1, 0), :2]
        out.append({'pos': [float(P[i, 0]), float(P[i, 1]), float(P[i, 2]) + lift], 'yaw': math.atan2(t[1], t[0])})
    return out


def _road_candidates(track, tried):
    """Sources de route a essayer quand la selection ne forme pas de boucle : objets importes de materiau « road »
    (la route d'abord, « RoadObj » / lignes ensuite), un par un, puis la route memorisee."""
    objs = [o for o in imported_road_objects(track) if o not in (tried.get('objects') or [])]
    rank = lambda o: (bool(re.search(r'road_?obj|start|line|goal', o['name'], re.I)), not re.search(r'road', o['name'], re.I))
    out = [{'objects': [o]} for o in sorted(objs, key=rank)]
    p = road_source_path(track)
    if os.path.exists(p):
        mem = json.load(open(p))
        if mem.get('objects') and mem != tried and mem not in out:
            out.append(mem)
    return out


def road_source_path(track):
    return os.path.join(OUT_DIR, f'{track}_road.json')


def road_tris(track, src):
    """Triangles monde de la route : objets du decor ({'objects': [{file, name | id}]}) ou surfaces de la collision
    ({'surfaces': [...]}, vide = celles sous les splines de position actuelles)."""
    if src.get('objects'):
        tris = []
        for ref in src['objects']:
            objs = DecorFile(base_file(track, ref['file'])[0]).objects()
            o = next((o for o in objs if (o['name'] == ref['name'] if 'name' in ref else o['id'] == int(ref['id']))), None)
            if o is None:
                raise ValueError(f"objet de route introuvable : {ref.get('name', ref.get('id'))} (supprime ou renomme ?)")
            tris.append(object_world_array(track, o))
        return np.concatenate(tris).reshape(-1, 3, 3) if tris else np.zeros((0, 3, 3))
    ground = ground_for(track)
    surfaces = [int(s) for s in src.get('surfaces') or []]
    if not surfaces:                    # auto : surfaces sous les splines de position actuelles
        rs0 = RaceSystem(base_file(track, race_file(track))[0], file_ns=race_ns(track)).decode()
        cnt = collections.Counter()
        for pos in rs0['position_paths']:
            for p in ai_gen.catmull_rom(pos['control_points'], 100):
                q = ground.at(p[0], p[1], p[2])
                if q:
                    cnt[q[1]] += 1
        # meme un court passage compte (pont, bande de bois, booster en travers) : sinon la route est coupee la et
        # la boucle trouvee est un petit tour (Mystery Caves : 685 m au lieu de 3 672 m)
        surfaces = [s for s, n in cnt.items() if n >= 2]
    return ground.t[np.isin(ground.v, surfaces)]


_road_cache = {}


def road_ground(track):
    """Sol de la ROUTE seule (objets memorises par « Creer le parcours ») pour mesurer la largeur des voies IA, ou
    None (route d'origine : reconnue a sa surface). Une map importee a souvent une seule surface partout (route,
    herbe, bordures, montagnes) : la largeur mesuree sur la surface debordait jusqu'a 100 m de chaque cote."""
    p = road_source_path(track)
    if os.path.exists(p):
        src = json.load(open(p))
    else:                                    # pas encore memorisee : modeles importes dont le materiau est « road »
        src = {'objects': imported_road_objects(track)}
        if not src['objects']:
            return None
    if not newmap_settings(track).get('strip_ground') and not src.get('objects'):
        return None
    key = (json.dumps(src, sort_keys=True), ground_key(track))
    if key not in _road_cache:
        _road_cache.clear()
        try:
            tris = road_tris(track, src)
        except ValueError:
            return None
        _road_cache[key] = ai_gen.GroundQuery(tris, [38] * len(tris)) if len(tris) else None
    return _road_cache[key]


def imported_road_objects(track):
    """[{file, name}] des objets de decor dont le modele importe vient d'un materiau OBJ/DAE contenant « road »."""
    reg, links, out = custom_models(track), load_links(track), []
    for art in art_files(track):
        p = saved_path(art)
        if not os.path.exists(p):
            continue
        for o in DecorFile(open(p, 'rb').read()).objects():
            lk = links.get(art, {}).get(str(o['id']))
            info = reg.get(lk['custom']) if isinstance(lk, dict) and 'custom' in lk else None
            if info and re.search(r'road', info.get('obj_material') or '', re.I) and lk.get('surface') != 'none' \
                    and not info.get('invisible'):
                out.append({'file': art, 'name': o['name']})
    return out


def route_objects(track):
    """Morceaux de route possibles pour « Creer le parcours » : objets importes du decor enregistre (modeles importes
    et objets de la bibliotheque), la route d'abord. -> {objects: [{file, id, name, road, size_m}], checked: [ids
    pre-coches : route memorisee, sinon objets dont le materiau est « road »]}."""
    reg, links = custom_models(track), load_links(track)
    mem = json.load(open(road_source_path(track))) if os.path.exists(road_source_path(track)) else {}
    mem_names = {(o['file'], o.get('name')) for o in mem.get('objects') or []}
    out, checked = [], []
    for art in art_files(track):
        for o in DecorFile(base_file(track, art)[0]).objects():
            lk = links.get(art, {}).get(str(o['id']))
            if not (isinstance(lk, dict) and 'custom' in lk):
                continue
            info = reg.get(lk['custom']) or {}
            if info.get('invisible'):                       # mur invisible : jamais un morceau de route
                continue
            road =bool(re.search(r'road', (info.get('obj_material') or '') + ' ' + (o['name'] or ''), re.I))
            try:
                T = object_world_array(track, o)
                ext = (T.reshape(-1, 3).max(0) - T.reshape(-1, 3).min(0))[:2].max() / 39.37 if len(T) else 0.0
            except Exception:  # noqa: BLE001 - modele illisible : taille inconnue
                ext = 0.0
            out.append({'file': art, 'id': o['id'], 'name': o['name'], 'road': road, 'size_m': round(float(ext))})
            if (art, o['name']) in mem_names or (not mem_names and road and lk.get('surface') != 'none'):
                checked.append(o['id'])
    out.sort(key=lambda r: (not r['road'], -r['size_m'], r['name'] or ''))
    return {'objects': out, 'checked': checked}


def gen_ai_splines(req):
    """Voies IA generees le long d'un trace d'apres le sol (collision enregistree, donc decor importe compris) :
    req = {track, reference: [[x,y,z]...], lanes, randomness (0..1), margin (0..0.9), seed, spacing}.
    Largeur de la route : mesuree sur les objets de route memorises s'il y en a (road_ground)."""
    progress.step('lecture du sol', 0.05)
    ground, road = ground_for(req['track']), road_ground(req['track'])
    progress.step('calcul des voies', 0.3)
    r = ai_gen.generate_lanes(ground, req['reference'], n=max(1, min(12, int(req.get('lanes', 5)))),
                              randomness=float(req.get('randomness', 0.5)), margin=float(req.get('margin', 0.15)),
                              seed=int(req.get('seed', 1)), point_spacing=float(req.get('spacing', 2500)),
                              keep_air=bool(req.get('keep_air')), road_ground=road)
    w = [a + b for a, b in r['widths']]
    r['width_summary'] = {'min': round(min(w)), 'median': round(float(np.median(w))), 'max': round(max(w))}
    r['widths'] = [[round(a), round(b)] for a, b in r['widths']]
    return r


def crates_auto(req):
    """Caisses placees en rangees le long du trace : req = {track, paths: [splines de position dans l'ordre de course
    depuis la ligne d'arrivee] (ou path : trace deja raccorde), rows, per_row, spacing (po), skip (part du tour laissee libre apres la ligne), fruit}."""
    path = powerup.chain_paths(req['paths']) if req.get('paths') else req['path']
    out, rep = powerup.auto_rows(ground_for(req['track']), path, rows=max(1, min(30, int(req.get('rows', 4)))),
                                 per_row=max(1, min(8, int(req.get('per_row', 4)))), spacing=float(req.get('spacing', 575)),
                                 skip=float(req.get('skip', 0.12)), fruit=max(0, min(30, int(req.get('fruit', 0)))),
                                 tnt=max(0, min(30, int(req.get('tnt', 0)))), nitro=max(0, min(30, int(req.get('nitro', 0)))),
                                 wumpa_lines=max(0, min(30, int(req.get('wumpa_lines', 0)))),
                                 wumpa_per_line=max(1, min(12, int(req.get('wumpa_per_line', 5)))))
    return {'crates': out, 'report': rep}


_aggressive_ok = {}


def safe_compact(track, logical, z):
    """Retire les blocs abandonnes par les reecritures (listes racine, tables de noms...) avant d'ecrire.
    Mode complet (tout ce qui n'est plus atteignable, y compris les dechets laisses par des versions precedentes
    de l'editeur) seulement si l'ORIGINAL de ce fichier en ressort identique (sinon il contient des donnees utiles
    non atteignables : mode normal)."""
    if logical not in _aggressive_ok:
        try:
            o = IgzFile(pak_tool.read_latest(ARCHIVES, logical, track_pak(track))[0])
            _aggressive_ok[logical] = o.compact(aggressive=True) == 0
        except Exception:  # noqa: BLE001
            _aggressive_ok[logical] = False
    return z.compact(aggressive=_aggressive_ok[logical])


def _crate_height_at(track):
    g = ground_for(track)
    return lambda x, y, z: (lambda q: q[0] if q else None)(g.at(x, y, z + 100, window=250.0))


_crate_file_cache = {}


def crate_file(track):
    """Fichier des caisses : le _Power_Up (table des noms presente), sinon le _Design quand il porte les caisses
    (Coco Park, Turbo Track, Blizzard Bluff : _Power_Up vide, un seul objet sans noms). None : aucun des deux."""
    if track not in _crate_file_cache:
        read = lambda p: pak_tool.read_latest(ARCHIVES, p, track_pak(track))[0]
        found = None
        try:
            if IgzFile(read(powerup.powerup_file(track))).names_offset is not None:
                found = powerup.powerup_file(track)
        except KeyError:
            pass
        if found is None:
            try:
                if any(c['kind'] in powerup.KINDS for c in powerup.read_crates(read(start_finish.design_file(track)), True)):
                    found = start_finish.design_file(track)
            except KeyError:
                pass
        _crate_file_cache[track] = found
    return _crate_file_cache[track]


def crates_in_design(track):
    """Caisses dans le _Design : seules les caisses y sont reecrites, depuis le fichier enregistre (grille,
    reapparitions, arrivees de teleporteur et le reste du fichier gardes)."""
    return crate_file(track) == start_finish.design_file(track)


BOOST_COLORS = ('orange', 'bleu', 'vert', 'violet', 'rouge', 'rose')


def boost_settings(c):
    """Reglages d'un booster recu de l'editeur : couleur de la plaque, vitesse du turbo, duree (s) ; anciens boosters
    (« super » seul) : bleu 1400 / 1,6 s, sinon orange 700 / 0,5 s."""
    sup = bool(c.get('super'))
    dsp, ddu = powerup.BOOST_SUPER if sup and 'speed' not in c else powerup.BOOST_CLASSIC
    sp = min(10000.0, max(0.0, float(c.get('speed', dsp))))
    du = min(30.0, max(0.05, float(c.get('duration', ddu))))
    col = c.get('color') if c.get('color') in BOOST_COLORS else ('bleu' if sup else 'orange')
    out = {'color': col, 'speed': round(sp, 1), 'duration': round(du, 2)}
    out['super'] = powerup.boost_needs_data(out)
    return out


def boost_colors(track):
    """Couleur de chaque booster de l'editeur, dans l'ordre, d'apres le modele de sa plaque au sol."""
    try:
        df = DecorFile(base_file(track, main_art(track))[0])
    except KeyError:
        return []
    vis = sorted((o for o in df.objects() if (o['name'] or '').startswith(BOOST_VISUAL_PREFIX)), key=lambda o: o['name'])
    return [boost_color_of_model(o['model']) for o in vis]


def boost_color_of_model(model):
    base = os.path.basename((model or '').replace('\\', '/'))[:-4].lower()
    if base == 'boostpadsuper':
        return 'bleu'
    if base.startswith('boostpad_') and base[9:] in BOOST_COLORS:
        return base[9:]
    return 'orange'


def read_track_crates(track):
    """Caisses du fichier en cours (enregistre, sinon d'origine) ; [] si la piste n'en a pas."""
    logical = crate_file(track)
    if logical is None:
        return []
    out = powerup.read_crates(base_file(track, logical)[0], crates_in_design(track))
    return out if crates_in_design(track) else out + design_boosts(track)


def design_boosts(track):
    """Boosters ajoutes par l'editeur dans le _Design ; ceux du jeu (TurboPad_001, GPI_SpeedBoostZone...) n'en font pas partie."""
    try:
        data = base_file(track, start_finish.design_file(track))[0]
    except KeyError:
        return []
    return [c for c in powerup.read_crates(data, True) if c['name'].startswith(powerup.BOOST_OWN)]


def migrate_boosters(track):
    """Boosters enregistres par une version precedente dans le _Power_Up : passes dans le _Design, sinon ils
    n'agissent pas en contre-la-montre. -> True si le fichier a ete refait."""
    if not crates_supported(track) or crates_in_design(track):
        return False
    logical = crate_file(track)
    p = saved_path(logical)
    if not os.path.exists(p) or not any(c['kind'] == 'boost' for c in powerup.read_crates(open(p, 'rb').read())):
        return False
    z, _ = write_crates_file(track, read_track_crates(track))
    safe_compact(track, logical, z)
    z.save(p)
    return True


def crates_tilt_outdated(track, data):
    """Caisses enregistrees dont l'inclinaison ne suit pas (ou plus) la pente : une sauvegarde sans changement de
    caisse les corrige aussi."""
    orig = pak_tool.read_latest(ARCHIVES, crate_file(track), track_pak(track))[0]
    return powerup.tilt_outdated(data, _crate_height_at(track), orig, crates_only=crates_in_design(track))


def crates_supported(track):
    """Caisses modifiables : dans le _Power_Up, ou dans le _Design (Coco Park, Turbo Track, Blizzard Bluff)."""
    return crate_file(track) is not None


def write_crates_file(track, want):
    """Fichier des caisses reconstruit (caisses, boosters, TNT / Nitro / fruits), caisses inclinees comme la pente du
    sol : _Power_Up depuis l'original ; _Design depuis le fichier enregistre, seules ses caisses changent. Boosters
    toujours dans le _Design (enregistre ici quand le fichier des caisses est le _Power_Up) : c'est la que le jeu
    range les siens, et ils agissent alors aussi en contre-la-montre. -> (IgzFile du fichier des caisses, rapport)."""
    if not crates_supported(track):
        raise ValueError(f'{track} : fichier des caisses introuvable (ni _Power_Up ni _Design)')
    read = lambda p, pak: pak_tool.read_latest(ARCHIVES, p, pak)[0]
    boosts = [c for c in want if c['kind'] == 'boost']
    # plaques modeles : classique (Sewer Speedway) et / ou super turbo (Polar Pass), seulement celles utilisees
    donor = {s: powerup.boost_donor(read, s) for s in {powerup.boost_needs_data(c) for c in boosts}} if boosts else None
    extras = {k: powerup.extra_donor(k, read) for k in {c['kind'] for c in want} if k in powerup.EXTRAS}
    logical = crate_file(track)
    ns = lambda lg: os.path.splitext(os.path.basename(lg))[0]          # espace de noms du fichier (handles)
    orig = read(logical, track_pak(track))
    if crates_in_design(track):
        keep = {(c['name'], tuple(c['pos'])) for c in powerup.read_crates(orig, True)}
        z, msg, _ = powerup.write_crates(base_file(track, logical)[0], want, donor, extras, _crate_height_at(track),
                                         crates_only=True, keep_tilt=keep, ns=ns(logical))
        return z, msg
    z, msg, _ = powerup.write_crates(orig, [c for c in want if c['kind'] != 'boost'], None, extras, _crate_height_at(track))
    if boosts or design_boosts(track):
        design = start_finish.design_file(track)
        dz, more = powerup.write_boosts(base_file(track, design)[0], boosts, donor, ns(design))
        safe_compact(track, design, dz)
        dz.save(saved_path(design))
        msg += more
    return z, msg


# -- sections (transitions) ajoutees / retirees ---------------------------------------------------
# Section = spline de position entre deux transitions. Ajout : une transition (copie d'une transition ordinaire du
# jeu) coupe une section en deux, la seconde moitie est une nouvelle spline de position (copie de la premiere) ; IA de
# la section inchangees (transition « de passage » : IA precedentes = suivantes, comme Coco Park
# Spline_Transition_002). Retrait : les deux sections autour de la transition fusionnent (la page refait leurs IA).
# Les points de reapparition et les embranchements des sections touchees vont a la plus proche.
def transition_template(ed, wanted):
    """Transition a copier : `wanted` si ordinaire (pas teleporteur), sinon une autre transition ordinaire."""
    ts = ed.transitions()
    ents = {n: ed.by_name[n] for n in ts}
    tps = set(teleport.read_teleporters(ed.igz, ents))
    if wanted in ts and wanted not in tps:
        return wanted
    plain = [n for n in ts if n not in tps]
    if not plain and wanted not in ts:
        raise ValueError('aucune transition a copier')
    return (plain or [wanted])[0]


def _section_points(ed, pts_by_name, name):
    return np.asarray(pts_by_name.get(name) or ed.points(ed.by_name[name]), np.float64)


def _dist_to_path(P, p):
    """Distance (vue de dessus) d'un point a une polyligne, et rang du segment le plus proche."""
    if len(P) < 2:
        return float(np.linalg.norm(P[0, :2] - p[:2])) if len(P) else 1e18, 0
    a, b = P[:-1, :2], P[1:, :2]
    ab = b - a
    t = np.clip(np.einsum('ij,ij->i', p[:2] - a, ab) / np.maximum(np.einsum('ij,ij->i', ab, ab), 1e-9), 0, 1)
    d = np.linalg.norm(a + ab * t[:, None] - p[:2], axis=1)
    k = int(np.argmin(d))
    return float(d[k]), k + float(t[k])


def _section_links_before(ed, req):
    """Sections touchees par un ajout / retrait et leurs points de reapparition (lus avant les suppressions)."""
    new = {ns['name']: ns['template'] for ns in req.get('new_position_splines') or []}
    merges = req.get('section_merges') or {}
    affected = set(new) | set(new.values()) | set(merges) | set(merges.values())
    if not affected:
        return None
    off = _field(ed.igz, 'CRaceTrackSplineComponentData', '_respawnPoints')
    respawns, owner = [], {}
    for n in sorted(affected - set(new)):
        if n in ed.by_name:
            comp = ed.component(ed.by_name[n], 'CRaceTrackSplineComponentData')
            for h in ed.igz.handle_list(ed.igz.deref(comp + off)):
                if h and h not in respawns:
                    respawns.append(h)
                    owner[h] = n
    return {'affected': affected, 'respawns': respawns, 'owner': owner, 'merges': merges}


def _section_links_after(ed, track, pts_by_name, links, design_poses):
    alive = [n for n in sorted(links['affected']) if n in ed.by_name]
    if not alive:
        return []
    paths = {n: _section_points(ed, pts_by_name, n) for n in alive}
    nearest = lambda p: min(((n,) + _dist_to_path(paths[n], np.asarray(p, np.float64)) for n in alive), key=lambda x: x[1])
    out = []
    # points de reapparition : a la section la plus proche, dans l'ordre du trace
    if links['respawns']:
        poses = start_finish.read_entity_poses(base_file(track, start_finish.design_file(track))[0],
                                               [h[0] for h in links['respawns']])
        poses.update({n: p for n, p in design_poses.items() if n in poses})   # replaces dans la meme sauvegarde
        per = {n: [] for n in alive}
        for k, h in enumerate(links['respawns']):
            if h[0] in poses:
                n, _, s = nearest(poses[h[0]]['pos'])
            else:
                # point hors du _Design (Sewer Speedway : RespawnPoint du _RaceSystem) : garde sa section, ou celle
                # dans laquelle elle a ete fusionnee
                n, seen = links['owner'].get(h), set()
                while n not in per and n in links['merges'] and n not in seen:
                    seen.add(n)
                    n = links['merges'][n]
                n, s = (n, 1e9 + k) if n in per else (alive[0], 1e9 + k)
            per[n].append((s, h))
        off = _field(ed.igz, 'CRaceTrackSplineComponentData', '_respawnPoints')
        for n in alive:
            comp = ed.component(ed.by_name[n], 'CRaceTrackSplineComponentData')
            lst = ed.igz.deref(comp + off)
            if lst is not None:
                ed.igz.set_handle_list(lst, [h for _, h in sorted(per[n], key=lambda x: x[0])])
        out.append('points de réapparition répartis : ' + ', '.join(f'{n} {len(per[n])}' for n in alive))
    # embranchements poses sur une section touchee : rattaches a la plus proche
    moved = 0
    for fname, comp in ed.forks().items():
        off = _field(ed.igz, 'CRaceTrackForkCheckerComponentData', '_positionPath')
        h = ed.igz.named_handle(ed.igz.u32(comp + off))
        if not h or h[0] not in links['affected']:
            continue
        n = nearest(ed.igz.vec3(ed.by_name[fname] + 0x20))[0]
        if n != h[0]:
            struct.pack_into('<Q', *ed.igz._loc(comp + off), 0x80000000 | ed.igz.ext_index(n, h[1]))
            ed.igz._mark('RHND', comp + off)
            moved += 1
    if moved:
        out.append(f'{moved} embranchement(s) rattaché(s) à leur nouvelle section')
    return out


def next_entity_name(template, taken):
    """Nom libre derive du modele : dernier nombre incremente (meme largeur), sinon suffixe _2, _3..."""
    m = re.match(r'^(.*?)(\d+)(\D*)$', template)
    if m:
        pre, digits, post = m.groups()
        k = int(digits)
        while True:
            k += 1
            name = f'{pre}{k:0{len(digits)}d}{post}'
            if name not in taken:
                return name
    k = 1
    while f'{template}_{k + 1}' in taken:
        k += 1
    return f'{template}_{k + 1}'


def plan_sections(tr, n):
    """Tour principal de tr (load_track) ramene a n sections, sur place : transitions ajoutees (section la plus
    longue coupee en deux) ou retirees (fusion, en partant de la fin du tour). -> champs de requete save_track
    {new_position_splines, new_transitions, deleted_transitions, deleted, section_merges}, ou None si impossible
    (transitions a plusieurs splines de position). Les points des sections et les poses des transitions sont a
    recalculer ensuite (route_gen.layout)."""
    pos = {s['name']: s for s in tr['splines'] if s['kind'] == 'position_paths'}
    ts = {t['name']: t for t in tr['transitions']}
    taken = {s['name'] for s in tr['splines']} | set(ts)
    out = {'new_position_splines': [], 'new_transitions': [], 'deleted_transitions': [], 'deleted': [], 'section_merges': {}}
    chain = race_chain(tr)
    if not chain:
        return None
    single = lambda t: len(t.get('previous_position') or []) == 1 and len(t.get('next_position') or []) == 1
    while len(chain) > n:
        k = next((k for k in range(len(chain) - 1, 0, -1) if single(chain[k][0])
                  and chain[k][0]['previous_position'][0] != chain[k][0]['next_position'][0]), None)
        if k is None:
            return None
        t, nxt = chain[k]
        prev = chain[k - 1][1]
        prev['control_points'] = prev['control_points'] + nxt['control_points']
        for x in ts.values():
            for key in ('previous_position', 'next_position'):
                if nxt['name'] in (x.get(key) or []) and x is not t:
                    x[key] = [prev['name'] if v == nxt['name'] else v for v in x[key]]
        out['section_merges'][nxt['name']] = prev['name']
        if nxt['name'] in [d['name'] for d in out['new_position_splines']]:
            out['new_position_splines'] = [d for d in out['new_position_splines'] if d['name'] != nxt['name']]
        else:
            out['deleted'].append(nxt['name'])
        if t['name'] in [d['name'] for d in out['new_transitions']]:
            out['new_transitions'] = [d for d in out['new_transitions'] if d['name'] != t['name']]
        else:
            out['deleted_transitions'].append(t['name'])
        tr['splines'] = [s for s in tr['splines'] if s['name'] != nxt['name']]
        tr['transitions'] = [x for x in tr['transitions'] if x is not t]
        del ts[t['name']], pos[nxt['name']]
        chain = race_chain(tr)
    while len(chain) < n:
        k = max(range(len(chain)), key=lambda i: len(chain[i][1]['control_points']))
        t0, s = chain[k]
        pts = s['control_points']
        m = max(1, len(pts) // 2)
        s2 = dict(s, name=next_entity_name(s['name'], taken), control_points=pts[m - 1:] if len(pts) > 2 else pts)
        taken.add(s2['name'])
        s['control_points'] = pts[:m + 1] if len(pts) > 2 else pts
        tmpl = next((x['name'] for x in tr['transitions'] if not x.get('increment_lap') and not x.get('teleporter')), t0['name'])
        nt = dict(ts[tmpl], name=next_entity_name(tmpl, taken), increment_lap=False, teleporter=False,
                  previous_position=[s['name']], next_position=[s2['name']],
                  previous_ai=list(t0.get('next_ai') or []), next_ai=list(t0.get('next_ai') or []))
        taken.add(nt['name'])
        for x in tr['transitions']:
            if s['name'] in (x.get('previous_position') or []):
                x['previous_position'] = [s2['name'] if v == s['name'] else v for v in x['previous_position']]
        tr['splines'].append(s2)
        tr['transitions'].append(nt)
        ts[nt['name']], pos[s2['name']] = nt, s2
        out['new_position_splines'].append({'name': s2['name'], 'template': s['name']})
        out['new_transitions'].append({'name': nt['name'], 'template': tmpl})
        out['section_merges'][s2['name']] = s['name']
        chain = race_chain(tr)
    return out


def save_track(req):
    track = req['track']
    rs_data, _ = base_file(track, race_file(track))
    ttr_data, _ = base_file(track, ttr_file(track))
    progress.step('splines et checkpoints', 0.05)
    ed = RaceSystemEditor(rs_data, track)
    ttr = TTRStatsEditor(ttr_data)
    report = []
    pts_by_name = req.get('splines', {})

    # creations d'abord (le modele d'une copie peut etre supprime ensuite)
    deleted = set(req.get('deleted', []))
    for ns in req.get('new_splines', []):
        name, template = ns['name'], ns['template']
        if name in deleted:
            continue
        pts = pts_by_name[name]
        ed.add_ai_spline(name, template=template, points=pts, wire=False)
        ttr.add_spline_stats(name, template=template, segments=len(pts) - 1)
        report.append(f'{name} : creee (modele {template}, {len(pts)} points)')

    # sections ajoutees / retirees : splines de position et transitions copiees d'entites du jeu (avant les listes)
    deleted_t = set(req.get('deleted_transitions') or [])
    for ns in req.get('new_position_splines') or []:
        if ns['name'] not in deleted:
            ed.add_ai_spline(ns['name'], template=ns['template'], points=pts_by_name[ns['name']], wire=False)
            report.append(f"{ns['name']} : section creee (modele {ns['template']})")
    for nt in req.get('new_transitions') or []:
        if nt['name'] in deleted_t:
            continue
        ent = ed.add_entity_copy(nt['name'], transition_template(ed, nt['template']))
        if teleport.read_teleporters(ed.igz, {nt['name']: ent}):          # copie d'un teleporteur : ordinaire
            teleport.clear_teleporter(ed.igz, ent)
            teleport.set_trigger_events(ed.igz, ent, False)
        report.append(f"{nt['name']} : transition creee")
    section_links = _section_links_before(ed, req)

    # splines remplacees par des splines generees : les remplacantes prennent leur place dans les embranchements
    for old, news in req.get('replaced', {}).items():
        news = [n for n in news if n in ed.by_name]
        for fcomp in ed.forks().values():
            lst = ed.igz.deref(fcomp + 0x18)                       # _aiPaths
            if lst is None:                                        # embranchement sans liste (Sewer Speedway)
                continue
            cur = ed.igz.handle_list(lst)
            if any(h and h[0] == old for h in cur):
                ns = cur[0][1] if cur and cur[0] else ed.ns
                ed.igz.set_handle_list(lst, [h for h in cur if h] + [(n, ns) for n in news if (n, ns) not in cur])
                report.append(f'embranchement : {old} -> {", ".join(news)}')

    for d in deleted:
        if d in ed.by_name:
            ed.remove_ai_spline(d)
            ttr.remove_spline_stats(d)
            report.append(f'{d} : supprimee')

    new_names = {ns['name'] for ns in req.get('new_splines', [])}
    for name, pts in pts_by_name.items():
        if name in new_names or name not in ed.by_name:
            continue
        before = len(ed.points(name))
        moved = set_points(ed, name, pts)
        if len(pts) != before:
            ttr.resize_segments(name, len(pts) - 1)
        if moved or len(pts) != before:
            report.append(f'{name} : {len(pts)} points, {moved} deplaces')

    for tname, t in req.get('transitions', {}).items():
        lists = {k: t[k] for k in LIST_KEYS if k in t}
        if lists:
            ed.set_transition_paths(tname, **lists)
        if 'increment_lap' in t:
            ed.set_increment_lap(tname, t['increment_lap'])
        # zone de declenchement (ligne d'arrivee) : position, cap, dimensions
        pos, yaw, dims = start_finish.transition_pose(ed, tname)
        new = (t.get('position', pos), t.get('yaw', yaw), t.get('dimensions', dims))
        if any(abs(a - b) > 1e-3 for a, b in zip(list(pos) + [yaw] + list(dims or []),
                                                     list(new[0]) + [new[1]] + list(new[2] or []))):
            start_finish.set_transition_pose(ed, tname, *new)
            report.append(f'{tname} : zone deplacee ({", ".join(str(round(c)) for c in new[0])}, cap '
                          f'{math.degrees(new[1]):.0f} deg)')

    # teleporteurs (avant le _Design ci-dessous : il relit la version enregistree, arrivees comprises)
    if req.get('teleporters') is not None:
        report += apply_teleporters(track, ed, req['teleporters'], rs_data)
    if req.get('portals') is not None:                   # portails hors transition (Teleporter_02 de T255)
        report += apply_portals(track, ed, rs_data, req['portals'])
    if req.get('flyby') is not None:                     # survol d'introduction : plans modifies (ou {} : origine)
        report += apply_flyby(track, req['flyby'])
    # teleporteurs deja enregistres sans les evenements de zone (version precedente de l'editeur) : repares
    tp_ents = transition_ents(ed)
    for tname in teleport.read_teleporters(ed.igz, tp_ents):
        if teleport.set_trigger_events(ed.igz, tp_ents[tname], True):
            report.append(f'{tname} : zone du téléporteur réparée (entrée des karts transmise au script)')

    for name in sorted(deleted_t):
        if name in ed.by_name:
            ed.remove_entity(name)
            report.append(f'{name} : transition supprimee')
    if section_links:
        report += _section_links_after(ed, track, pts_by_name, section_links, req.get('design_poses') or {})

    # entites du RaceSystem deplacees (embranchements ecartes par « Creer le parcours »)
    for name, pos in (req.get('race_entity_positions') or {}).items():
        if name in ed.by_name:
            struct.pack_into('<3f', *ed.igz._loc(ed.by_name[name] + 0x20), *[float(c) for c in pos])
            report.append(f'{name} deplace')

    # reapparitions rangees dans le _RaceSystem (Sewer Speedway, Slide Coliseum, Turbo Track...) : ecrites ici, le
    # reste va au _Design ci-dessous (« Creer le parcours » les envoie toutes dans design_poses)
    design_poses = dict(req.get('design_poses') or {})
    if design_poses:
        dnames = {n for n, _ in IgzFile(base_file(track, start_finish.design_file(track))[0]).root_objects()}
        in_rs = {n: p for n, p in design_poses.items() if (n not in dnames or start_finish.design_file(track) == race_file(track))
                 and n in ed.by_name}
        for name, p in in_rs.items():
            start_finish.set_entity_pose(ed.igz, ed.by_name[name], p)
            del design_poses[name]
        if in_rs:
            report.append(f'_RaceSystem : {len(in_rs)} entite(s) placee(s) (reapparitions)')

    # grille dans le _RaceSystem (8 pistes) : ecrite dans le fichier en cours d'edition
    in_race = grid_file(track) == race_file(track)
    if in_race and req.get('start_grid'):
        cur = {s['name']: s for s in start_finish.read_grid_igz(ed.igz)}
        want = {s['name']: s for s in req['start_grid'] if s['name'] in cur}
        if any(abs(a - b) > 1e-3 for n, s in want.items() for a, b in zip(s['pos'] + [s['yaw']], cur[n]['pos'] + [cur[n]['yaw']])):
            start_finish.write_grid_igz(ed.igz, want)
            report.append(f'grille de depart : {len(want)} places (_RaceSystem)')
    # grille de depart et autres entites du _Design (reapparitions, zones), repere PlayerStartAll (fichier principal)
    logical = start_finish.design_file(track)
    # parcours dans le _Design (T212, T213...) : ecrit maintenant, la suite (zones, caisses, boosters) part de cette version
    same_file = logical == race_file(track)
    if same_file:
        os.makedirs(OUT_DIR, exist_ok=True)
        safe_compact(track, logical, ed.igz)
        ed.igz.save(saved_path(logical))
        ed = RaceSystemEditor(open(saved_path(logical), 'rb').read(), track)     # relu : le compactage deplace les objets
    if (req.get('start_grid') and not in_race) or design_poses:
        data = base_file(track, logical)[0]
        out = data
        if req.get('start_grid') and not in_race:
            cur = {s['name']: s for s in start_finish.read_grid(data)}
            want = {s['name']: s for s in req['start_grid'] if s['name'] in cur}
            if any(abs(a - b) > 1e-3 for n, s in want.items() for a, b in zip(s['pos'] + [s['yaw']], cur[n]['pos'] + [cur[n]['yaw']])):
                out = start_finish.write_grid(out, want)
                report.append(f'grille de depart : {len(want)} places')
        if design_poses:
            out = start_finish.write_entity_poses(out, design_poses)
            report.append(f"_Design : {len(design_poses)} entite(s) placee(s) (reapparitions, zones)")
        if out is not data:
            open(saved_path(logical), 'wb').write(out)
    if req.get('fall_zones') is not None:                 # zones de chute deplacees / redimensionnees / supprimees
        report += write_fall_zones(track, req['fall_zones'])
    if req.get('player_start'):
        logical = start_finish.main_map_file(track)
        data = base_file(track, logical)[0]
        cur, ps = start_finish.read_player_start(data), req['player_start']
        if cur and any(abs(a - b) > 1e-3 for a, b in zip(ps['pos'] + [ps['yaw']], cur['pos'] + [cur['yaw']])):
            open(saved_path(logical), 'wb').write(start_finish.write_player_start(data, ps['pos'], ps['yaw']))
            report.append('repere de depart deplace')
    if req.get('killz') is not None:                     # map mise a l'echelle : plancher du monde suivi
        set_world_killz(track, req['killz'])
        report.append(f"plancher de chute : z = {float(req['killz']):.0f}")

    # caisses d'objets : fichier reconstruit depuis l'original (positions, ajouts, suppressions)
    progress.step('caisses et boosters', 0.4)
    if req.get('crates') is not None and crates_supported(track):
        logical = crate_file(track)
        cur = read_track_crates(track)
        want = []
        for c in req['crates']:
            w = {'name': c.get('name'), 'kind': c['kind'], 'pos': [round(float(v), 2) for v in c['pos']]}
            if c['kind'] == 'boost':
                w['yaw'] = round(float(c.get('yaw') or 0.0), 5)
                w['tilt'] = [round(float(v), 5) for v in (c.get('tilt') or [0.0, 0.0])]   # inclinaison X, Y
                w['dims'] = [round(float(v), 1) for v in (c.get('dims') or powerup.BOOST_DIMS)]
                w.update(boost_settings(c))                     # couleur, vitesse, duree (+ super : donnees propres)
            elif c['kind'] != 'wumpa':                          # cap des caisses (2026-11-07) ; fruit au sol : sans
                w['yaw'] = round(float(c.get('yaw') or 0.0), 5)
            want.append(w)
        named = lambda c: c['kind'] in ('question', 'fruit')             # copies d'origine : le nom compte
        key = lambda lst: [(c['name'] if named(c) else None, c['kind'], c['pos'], round(float(c.get('yaw') or 0.0), 4), c.get('dims'),
                            [round(v, 4) for v in c['tilt']] if c.get('tilt') else None, c.get('super'),
                            round(float(c['speed']), 1) if 'speed' in c else None,
                            round(float(c['duration']), 2) if 'duration' in c else None) for c in lst]
        if key(cur) != key(want) or crates_tilt_outdated(track, base_file(track, logical)[0]):
            z, msg = write_crates_file(track, want)
            safe_compact(track, logical, z)
            z.save(saved_path(logical))
            report.append(msg)
        # dessin au sol des boosters (aussi s'il n'est plus a jour : sol modifie, ancienne version mal placee)
        vis = sync_boost_visuals(track, [c for c in want if c['kind'] == 'boost'])
        if vis and vis != 'aucun booster':
            report.append(vis)

    # splines de depart : choix de l'utilisateur (meme nombre d'emplacements que le fichier), puis
    # remplacement de celles qui n'existent plus par les IA qui suivent la ligne d'arrivee
    ai_names = set(ed.entities_with_spline())
    wanted = req.get('starting_splines')
    if wanted is not None:
        slots = len(ttr.starting_splines())
        if len(wanted) != slots:
            raise ValueError(f'{slots} splines de depart attendues, {len(wanted)} recues')
        current = ttr.starting_splines()
        if list(wanted) != current:
            ttr.set_starting_splines([w or current[i] for i, w in enumerate(wanted)])
            report.append(f'splines de depart choisies : {ttr.starting_splines()}')
    starts = ttr.starting_splines()
    if any(s not in ai_names for s in starts):
        finish = [n for n, t in req.get('transitions', {}).items() if t.get('increment_lap')]
        cand = [n for n in (ed.transition_paths(finish[0])['next_ai'] if finish else []) if n in ai_names] \
            or sorted(ai_names)
        fixed = [s if s in ai_names else cand[i % len(cand)] for i, s in enumerate(starts)]
        ttr.set_starting_splines(fixed)
        report.append(f'splines de depart : {fixed}')

    os.makedirs(OUT_DIR, exist_ok=True)
    progress.step('écriture des fichiers de course', 0.85)
    gain = safe_compact(track, ttr_file(track), ttr.igz)
    if not same_file:
        drop_orphan_points(track, ed.igz)
        gain += safe_compact(track, race_file(track), ed.igz)
        ed.igz.save(saved_path(race_file(track)))
    if gain > 4096:
        report.append(f'fichiers compactes : {gain // 1024} Ko de blocs abandonnes retires')
    open(saved_path(ttr_file(track)), 'wb').write(ttr.to_bytes())
    return {'saved': [saved_path(race_file(track)), saved_path(ttr_file(track))], 'report': report}


# -- decor --------------------------------------------------------------------------------------
_art_cache, _model_cache = {}, {}


def art_files(track):
    """Fichiers de carte qui placent du decor (maps/Octane/<Piste>/<Piste>_Art*.igz)."""
    if track not in _art_cache:
        arc = pak_tool.IgaArchive(os.path.join(ARCHIVES, track_pak(track)))
        _art_cache[track] = sorted(e.logical_name for e in arc.entries
                                   if e.logical_name.startswith(f'maps/Octane/{track}/{track}_Art')
                                   and e.logical_name.endswith('.igz'))
        arc.f.close()
    return _art_cache[track]


_main_art_cache, _template_cache = {}, {}


def main_art(track):
    """Fichier de decor ou vont les objets ajoutes (imports, bibliotheque, plaques de booster) : celui de l'entite qui
    active le sol de collision, toujours charge (Crash Cove : Art_Core ; Roo's Tubes : Art_Level_Core ; Coco Park :
    Art). Sinon Art_Core, sinon le fichier qui a le plus d'objets transformables."""
    if track not in _main_art_cache:
        arts = art_files(track)
        try:
            owner = ground_owner(track)
        except Exception:  # noqa: BLE001 - collision illisible : autres criteres
            traceback.print_exc()
            owner = None
        art = owner[0] if owner and owner[0] in arts else next((a for a in arts if a.endswith('_Art_Core.igz')), None)
        if art is None:
            count = lambda a: sum(o['has_transform'] for o in DecorFile(pak_tool.read_latest(ARCHIVES, a, track_pak(track))[0]).objects())
            art = max(arts, key=count)
        _main_art_cache[track] = art
    return _main_art_cache[track]


def template_object(track, art):
    """Id de l'objet modele copie pour les objets ajoutes : dans le fichier d'ORIGINE, l'objet transformable au plus
    petit nombre de composants (modele + statique), hors entite du sol de collision. None si le fichier n'en a pas."""
    if (track, art) not in _template_cache:
        df = DecorFile(pak_tool.read_latest(ARCHIVES, art, track_pak(track))[0])
        z = df.igz
        owner = (ground_owner(track) or (None, None))[1] if art == main_art(track) else None

        def n_components(o):
            data = z.deref(o['id'] + 0x40)
            table = z.deref(data + 0x10) if data is not None else None
            return len(list(z.hash_items(table))) if table is not None else 99
        # objets autonomes : atteignables depuis eux seuls (pas un enfant de prefabrique : Tiger Temple)
        owned = z.owned_by(ENTITY_TYPES)
        cands = [o for o in df.objects() if o['has_transform'] and o['name'] != owner and o['id'] in owned[o['id']][0]]
        _template_cache[(track, art)] = min(cands, key=lambda o: (n_components(o), o['id']))['id'] if cands else None
    return _template_cache[(track, art)]


def original_bounds(track):
    """Emprise de la piste d'origine (boite de la collision du jeu, pouces) : [[min x, y, z], [max x, y, z]].
    Quitter une course depuis la pause plantait (liberation d'un objet deja decharge, thread de streaming) quand
    les karts avaient roule HORS de cette emprise (map importee placee ailleurs) : la course doit y tenir."""
    try:
        cf = CollisionFile(pak_tool.read_latest(ARCHIVES, collision_file(track), track_pak(track))[0])
        lo, hi = cf._floats(cf.compound + 0x80, 3), cf._floats(cf.compound + 0x90, 3)
        return [[v * HAVOK_TO_GAME for v in lo], [v * HAVOK_TO_GAME for v in hi]]
    except Exception:  # noqa: BLE001 - piste sans collision lisible
        return None


def load_decor(track):
    files = []
    reg = custom_models(track)
    labels = {m['id']: m['label'] for m in material_catalog(track)} if reg else {}
    links = load_links(track)
    alpha = {i['material_id']: bool(i.get('alpha')) for i in custom_textures(track).values()}
    glow = {i['material_id']: bool(i.get('glow')) for i in custom_textures(track).values()}
    for logical in art_files(track):
        data, src = base_file(track, logical)
        objs = DecorFile(data).objects()
        for o in objs:                                   # modeles importes : texture, surface, transparence
            info = reg.get(model_logical_path(o['model']))
            lk = links.get(logical, {}).get(str(o['id']))
            if info:
                o['custom_material'] = labels.get(info.get('material'), 'roche du gabarit')
                o['surface'] = lk.get('surface', 'auto') if isinstance(lk, dict) else 'auto'
                o['phys'] = lk.get('phys') if isinstance(lk, dict) else None       # vitesse / glissade propres
                o['double'] = bool(info.get('double'))          # visible des deux cotes (faces doublees)
                o['alpha'] = alpha.get(info.get('material'))
                o['glow'] = glow.get(info.get('material'))           # None : texture du jeu (non modifiable)
                if info.get('invisible'):                # mur invisible : 'auto' | 'manual' | 'obj'
                    o['invisible'] = info.get('wall', 'obj')
                    o['alpha'] = None
            elif isinstance(lk, dict) and lk.get('library'):  # objet de la bibliotheque : piste d'origine, surface
                o['library'] = library.nice(lk['library'])
                o['surface'] = lk.get('surface', 'auto')
                o['phys'] = lk.get('phys')
        files.append({'file': logical, 'label': os.path.basename(logical)[len(track) + 1:-4],
                      'source': os.path.basename(src), 'saved': src.startswith(OUT_DIR), 'objects': objs})
    groups = move_away_files(track)
    return {'track': track, 'files': files, 'newmap': newmap_settings(track), 'lights': read_lights(track),
            'orig_bounds': original_bounds(track), 'collision_pending': collision_pending(track),
            'light_presets': {k: {'label': p[0], 'color': p[1], 'intensity': p[2], 'radius': p[3], 'from': p[4]}
                              for k, p in lights.PRESETS.items()},
            'added': added_groups(track, {f['file']: f['objects'] for f in files}),
            'move_away_groups': [{'key': k, 'label': l, 'files': [os.path.basename(p)[len(track) + 1:-4] for p in groups.get(k, [])]}
                                 for k, l, _ in MOVE_AWAY_GROUPS if groups.get(k)]}


def model_binary(track, file_name):
    """Maillage d'un modele : u32 nb sommets, u32 nb indices, float32[3n], uint32[m]."""
    logical = model_logical_path(file_name)
    if logical not in _model_cache:
        try:
            pos, idx = model_or_wall_mesh(track, logical)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            pos, idx = [], []
        _model_cache[logical] = struct.pack(f'<II{len(pos)}f{len(idx)}I', len(pos) // 3, len(idx), *pos, *idx)
    return _model_cache[logical]


REMAINING_LABELS = [('lighting', 'éclairage et géométrie lointaine (paysage du fond)'), ('power_up', 'caisses d\'objets'),
                    ('relic', 'reliques (contre-la-montre)'), ('token', 'jetons CTR'), ('trophy', 'trophée'),
                    ('animation', 'objets animés'), ('audio', 'sons d\'ambiance localisés'), ('vfx', 'effets visuels'),
                    ('design_ex', 'éléments de jeu exclus en écran partagé'), ('minimap', 'mini-carte'),
                    ('moderrace', 'objets de modes de course'), ('occlusion', 'occultation (rendu)')]


def remaining_elements(track):
    """Ce qui reste de l'ancienne piste hors fichiers _Art (non modifie par « nouvelle map ») : fichiers de carte
    du manifeste qui placent des entites, avec leur nombre et une description."""
    out = []
    rows = pkg_manifest.entries(pak_tool.read_latest(ARCHIVES, pkg_manifest.manifest_logical(track), track_pak(track))[0])
    skip = {a.lower() for a in art_files(track)} | {race_file(track).lower(), start_finish.design_file(track).lower(),
                                                     start_finish.main_map_file(track).lower()}
    for t, p in rows:
        if not p.startswith('maps/') or p in skip:
            continue
        try:
            z = IgzFile(pak_tool.read_latest(ARCHIVES, p, track_pak(track))[0])
        except KeyError:
            continue
        n = sum(1 for o, ty in z.objects.items() if ty in ('CEntity', 'CGameEntity', 'igEntity', 'CPlayerStartEntity'))
        models = sum(1 for ty in z.objects.values() if ty == 'CModelComponentData')
        if not n:
            continue
        name = os.path.basename(p)[len(track) + 1:-4]
        label = next((l for k, l in REMAINING_LABELS if k in name.lower()), 'autres entités')
        out.append({'file': name, 'entities': n, 'models': models, 'label': label,
                    'moved': os.path.exists(saved_path(p))})
    out.append({'file': 'ciel / eau', 'entities': 0, 'models': 0,
                'label': 'ciel (sky_model du manifeste) et surface de l\'eau : rendus globaux, non retirés'})
    return out


# Restes visibles de l'ancienne map hors fichiers _Art : entites animees, effets, lumieres. Le _Design y fait
# reference (handles) : plutot que les supprimer, toutes les entites du fichier sont descendues sous la carte
# (meme decalage pour toutes : trajets des bateaux / oiseaux, enfants... restent coherents). Non concernes :
# _Animation (cameras de fin de course), _VFX (generateur de caisses), modes relique / jetons / anneaux.
# Fichiers reconnus a leur nom (apres « <Piste>_ ») : les noms varient d'une piste a l'autre (Crash Cove
# design_excl_4p / lighting_exclu_4p-switch, Roo's Tubes design_ps4_nsp / lighting_level_ex_4p...). Fichiers sans
# entite ignores. Jamais : _Design (course), _Boss_race, _Animation, modes relique / jetons / trophee.
MOVE_AWAY_GROUPS = [
    ('animated', 'Bateaux, oiseaux, poissons, crabes, mines, public… (décor animé)', r'^(design_.+|crowd|spider)$'),
    ('vfx', 'Effets visuels (vent de sable, papillons, cascades, gouttes, brume…)', r'^vfx(_.+)?$'),
    ('lighting', 'Lumières, zones d\'ambiance et ombres', r'^lighting(_.+)?$'),
    ('audio', 'Sons d\'ambiance placés (mouettes, bulles, grincements…)', r'^audio(_.+)?$'),
    # declencheurs (COcclusionTrigger : position, taille) qui masquent tout ce qui est dans leurs boites
    # (COcclusionBox, centre en +0x68) : Roo's Tubes masquait route et sol importes selon la camera
    ('occlusion', 'Zones d\'occultation (masquent des morceaux de ta map selon la caméra)', r'^(new_?)?occlusion'),
]
OCCLUSION_TYPES = ('COcclusionTrigger', 'COcclusionBox')
MOVE_AWAY_DZ = FAR_BELOW
# generateur de caisses (Crate_Spawner, PowerUpCrate_gen du fichier _VFX de Crash Cove) : reste. Seulement dans les
# fichiers d'effets : ailleurs une « caisse » est du decor (Chicken_Crate de Crash Cove, MetalCrate de Dragon Mines,
# restee sous la route de T901 une fois le sol retire)
MOVE_AWAY_KEEP = re.compile(r'crate|power_?up', re.I)
MOVE_AWAY_KEEP_FILE = re.compile(r'_vfx(_[^/]*)?\.igz$', re.I)


def move_away_files(track, keys=None):
    """{cle de groupe: [fichiers de carte du manifeste]} (tous les groupes, ou ceux de keys)."""
    if track not in _move_away_cache:
        rows = pkg_manifest.entries(pak_tool.read_latest(ARCHIVES, pkg_manifest.manifest_logical(track), track_pak(track))[0])
        prefix = f'maps/octane/{track.lower()}/{track.lower()}_'
        found = defaultdict(list)
        for t, p in rows:
            if not p.startswith(prefix) or not p.endswith('.igz'):
                continue
            name = p[len(prefix):-4]
            key = next((k for k, _, rx in MOVE_AWAY_GROUPS if re.match(rx, name)), None)
            if key is None:
                continue
            try:
                z = IgzFile(pak_tool.read_latest(ARCHIVES, p, track_pak(track))[0])
            except KeyError:
                continue
            if any((z.objects.get(o) or '').endswith('Entity') or z.objects.get(o) in OCCLUSION_TYPES
                   for _, o in z.root_objects()):
                found[key].append(p)
        _move_away_cache[track] = dict(found)
    return {k: v for k, v in _move_away_cache[track].items() if keys is None or k in keys}


_move_away_cache = {}


def _logical_case(track, p):
    """Nom logique avec la casse de l'archive (le manifeste est en minuscules)."""
    arc, index, _ = pak_tool.cached_archive(os.path.join(ARCHIVES, track_pak(track)))
    e = index.get(p.lower())
    return e.logical_name if e else p


def sink_leftover_crates(logical, data):
    """Fichier descendu par une ancienne « Nouvelle map » : les entites « caisse » de decor gardees en place a tort
    (Chicken_Crate de Crash Cove, sous la route de T901) descendues a leur tour. Fichiers d'effets : inchanges."""
    if MOVE_AWAY_KEEP_FILE.search(logical):
        return data
    z = IgzFile(data)
    n = 0
    for name, o in z.root_objects():
        if (z.objects.get(o) or '').endswith('Entity') and MOVE_AWAY_KEEP.search(name or ''):
            x, y, zz = z.vec3(o + 0x20)
            if zz > MOVE_AWAY_DZ / 2:
                struct.pack_into('<3f', *z._loc(o + 0x20), x, y, zz + MOVE_AWAY_DZ)
                n += 1
    return z.to_bytes() if n else data


def write_moved_away(track, keys):
    """Fichiers des groupes coches : toutes les entites racine descendues de MOVE_AWAY_DZ (copie enregistree) ;
    groupes decoches : copie enregistree retiree (l'original revient a l'installation)."""
    report = []
    for key, files in move_away_files(track).items():
        for p in files:
            msg = rebuild_map_file(track, _logical_case(track, p), key in keys)
            if msg:
                report.append(msg)
    return report


def rebuild_map_file(track, logical, moved):
    """Fichier de carte reconstruit depuis l'original : entites descendues sous la carte (moved, « Nouvelle
    map ») et, pour le fichier _Lighting principal, ambiance (jour / soir / nuit). Ni l'un ni l'autre : copie
    enregistree retiree (l'original revient a l'installation). -> rapport ou None."""
    path = saved_path(logical)
    main = logical.lower() == lighting_file(track).lower()
    amb = ambiance_values(track) if main else None
    sky = ambiance_sky(track) if main else None
    added = read_lights(track) if main else []
    if not moved and not amb and not sky and not added:
        if os.path.exists(path):
            os.remove(path)
            return f'{os.path.basename(logical)} : remis a sa place'
        return None
    z = IgzFile(pak_tool.read_latest(ARCHIVES, logical, track_pak(track))[0])
    msg = []
    if moved:
        n = 0
        keep = MOVE_AWAY_KEEP if MOVE_AWAY_KEEP_FILE.search(logical) else None
        for name, o in z.root_objects():
            t = z.objects.get(o) or ''
            if t in OCCLUSION_TYPES:                   # position : champ _position du declencheur, +0x68 de la boite
                off = z.find_field(o, '_position')[0] if t == 'COcclusionTrigger' else o + 0x68
                x, y, zz = z.vec3(off)
                struct.pack_into('<3f', *z._loc(off), x, y, zz + MOVE_AWAY_DZ)
                n += 1
            elif t.endswith('Entity') and not (keep and keep.search(name or '')):
                x, y, zz = z.vec3(o + 0x20)
                struct.pack_into('<3f', *z._loc(o + 0x20), x, y, zz + MOVE_AWAY_DZ)
                n += 1
        msg.append(f'{n} entite(s) descendue(s) sous la carte')
    if sky:                                            # d'abord l'atmosphere de la piste source, puis l'ambiance
        msg.append(f"ciel et éclairage de {sky['label']} ({apply_sky(z, sky)} réglages)")
    if amb:
        msg.append(f'ambiance : {apply_ambiance(z, amb)} reglage(s)')
    if added:                                          # apres la descente : les lumieres ajoutees restent en place
        donor = IgzFile(pak_tool.read_latest(ARCHIVES, lights.DONOR_FILE, track_pak(lights.DONOR_TRACK))[0])
        msg.append(f'{lights.add_lights(z, donor, added)} lumière(s) ajoutée(s)')
    z.save(path)
    return f'{os.path.basename(logical)} : ' + ', '.join(msg)


# -- ambiance (jour / soir / nuit) --------------------------------------------------------------
# Eclairage de la piste = CWorldVisualDataGroup « worldVisualData_defaultGroup » de <Piste>_Lighting.igz
# (soleil, ciel, brouillard, etalonnage...) ; les boites locales (CVisualDataGroup des CVisualDataBoxComponentData :
# sous le pont, interieurs...) ne remplacent que les champs dont l'indicateur « ...State » est vrai. Reperes pris
# sur les pistes du jeu : coucher de soleil = Dingo Canyon / Out of Time (soleil orange [1 ; 0,51 ; 0,29], 7) ;
# sombre = Roo's Tubes (soleil bleute 0,75, brouillard bleu fonce, ambiance x0,3), Slide Coliseum (soleil 0,2).
AMBIANCE_FIELDS = {
    'sun_color': ['_sunColor'], 'sun_intensity': ['_sunIntensity'], 'exposure': ['_colorGlobalExposure'],
    'saturation': ['_colorGlobalSaturation'], 'contrast': ['_colorGlobalContrast'], 'tint': ['_colorGlobalTint'],
    'fog_color': ['_fogColor'], 'fog_sun_color': ['_fogSunColor'], 'fog_density': ['_fogDensity'],
    'fog_start': ['_fogStart'], 'ambient': ['_ambientDiffuseScale', '_ambientSpecularScale'],
    'sky_sun': ['_skySunIntensity'], 'sky_fade': ['_skyFade'], 'sunshaft': ['_skySunshaftIntensity'],
    'sunshaft_color': ['_skySunshaftColor'], 'clouds_color': ['_cloudsHighlightColor'], 'toon': ['_toonFade']}
AMBIANCE_PRESETS = {
    'day': {},
    'evening': {'sun_color': [1.0, 0.55, 0.3], 'sun_intensity': 5.5, 'exposure': 2.0, 'tint': [1.0, 0.92, 0.84],
                'fog_color': [1.0, 0.55, 0.4], 'fog_sun_color': [1.0, 0.6, 0.3], 'fog_density': 0.0022,
                'ambient': 0.85, 'sky_sun': 3.0, 'sunshaft_color': [1.0, 0.6, 0.35], 'clouds_color': [1.0, 0.5, 0.3]},
    'night': {'sun_color': [0.45, 0.6, 1.0], 'sun_intensity': 0.7, 'exposure': -4.0, 'saturation': -5.0,
              'tint': [0.72, 0.8, 1.0], 'fog_color': [0.05, 0.08, 0.16], 'fog_sun_color': [0.1, 0.15, 0.3],
              'fog_density': 0.0028, 'fog_start': 2500.0, 'ambient': 0.35, 'sky_sun': 0.0, 'sunshaft': 0.0,
              'sky_fade': 0.7, 'clouds_color': [0.3, 0.4, 0.7]}}


_lighting_cache = {}


def lighting_file(track):
    """Fichier de l'eclairage principal (CWorldVisualData : ciel, soleil, brouillard...) parmi les fichiers de carte du
    manifeste : <Piste>_Lighting d'habitude, mais Mystery Caves utilise <Piste>_Lighting_New (son _Lighting, encore
    dans l'archive, est vide : le ciel y etait ecrit pour rien)."""
    if track not in _lighting_cache:
        found = None
        try:
            rows = pkg_manifest.entries(pak_tool.read_latest(ARCHIVES, pkg_manifest.manifest_logical(track), track_pak(track))[0])
            prefix = f'maps/octane/{track.lower()}/{track.lower()}_lighting'
            for _, p in sorted(rows, key=lambda r: len(r[1])):      # <Piste>_Lighting d'abord
                if not (p.startswith(prefix) and p.endswith('.igz')):
                    continue
                try:
                    z = IgzFile(pak_tool.read_latest(ARCHIVES, p, track_pak(track))[0])
                except KeyError:
                    continue
                if any(t == 'CWorldVisualData' for t in z.objects.values()):
                    found = p
                    break
        except KeyError:
            pass
        _lighting_cache[track] = _logical_case(track, found or f'maps/Octane/{track}/{track}_Lighting.igz')
    return _lighting_cache[track]


def ambiance_path(track):
    return os.path.join(OUT_DIR, f'{track}_ambiance.json')


def ambiance_values(track):
    p = ambiance_path(track)
    return (json.load(open(p)).get('values') or None) if os.path.exists(p) else None


def _ambiance_read(z):
    """Valeurs actuelles du groupe par defaut, aux cles d'AMBIANCE_FIELDS."""
    o = next(o for o, t in z.objects.items() if t == 'CWorldVisualDataGroup')
    out = {}
    for key, names in AMBIANCE_FIELDS.items():
        off, ftype = z.find_field(o, names[0])
        out[key] = ([round(v, 4) for v in struct.unpack_from('<3f', *z._loc(off))] if ftype == 'igVec4fMetaField'
                    else round(struct.unpack_from('<f', *z._loc(off))[0], 6))
    return out


def apply_ambiance(z, values):
    """Ecrit values dans le groupe par defaut (indicateur « State » mis a vrai) et dans chaque boite locale qui
    remplace deja ce champ. -> nb de champs ecrits."""
    n = 0
    groups = [(o, True) for o, t in z.objects.items() if t == 'CWorldVisualDataGroup'] + \
             [(o, False) for o, t in z.objects.items() if t == 'CVisualDataGroup']
    fields = z.fields_of('CWorldVisualDataGroup')
    names = {nm for nm, _ in fields.values()}
    for key, val in values.items():
        for name in AMBIANCE_FIELDS.get(key, []):
            state = name + 'State'
            for o, default in groups:
                st = z.find_field(o, state)[0] if state in names else None
                if not default and (st is None or not z._byte(st)):
                    continue
                off, ftype = z.find_field(o, name)
                if ftype == 'igVec4fMetaField':
                    struct.pack_into('<3f', *z._loc(off), *[float(c) for c in val[:3]])
                else:
                    struct.pack_into('<f', *z._loc(off), float(val))
                if default and st is not None:
                    z._set_byte(st, 1)
                n += 1
    return n


# -- ciel ---------------------------------------------------------------------------------------
# Ciel = modele « sky_model » du manifeste (sky/octane/t111_skybox.igz) nomme dans CWorldVisualData._farSkyModelName4
# du _Lighting (« Octane\T111_Skybox »). Roo's Tubes n'en a pas : son fond est un modele de decor (la grotte sous-marine
# t112_roos_tube_vista) ; retire par « Nouvelle map », plus rien n'est dessine derriere la map et l'image precedente
# reste a l'ecran (grosses trainees). Choisir le ciel d'une autre piste : nom ecrit dans le _Lighting, modele +
# materiaux + textures declares au manifeste (et copies s'ils ne sont pas dans une archive montee) a l'installation.
_sky_cache = []


def _sky_name(z):
    o = next((o for o, t in z.objects.items() if t == 'CWorldVisualData'), None)
    return z.dump_object(o).get('_farSkyModelName4') if o is not None else None


def sky_catalog():
    """[{key (piste), label, model (chemin logique), name (« Octane\\T111_Skybox »), pak}] des pistes qui ont un ciel."""
    if not _sky_cache:
        for t in list_tracks():
            try:
                rows = pkg_manifest.entries(pak_tool.read_latest(ARCHIVES, pkg_manifest.manifest_logical(t), track_pak(t))[0])
                model = next((p for ty, p in rows if ty == 'sky_model'), None)
                name = _sky_name(IgzFile(pak_tool.read_latest(ARCHIVES, lighting_file(t), track_pak(t))[0])) if model else None
            except (KeyError, StopIteration):
                continue
            if model and name:
                e = pak_tool.cached_archive(os.path.join(ARCHIVES, track_pak(t)))[1].get(model.lower())
                model = e.logical_name if e else (library._common_case(ARCHIVES, model) or model)
                _sky_cache.append({'key': t, 'label': library.nice(track_pak(t)), 'name': name, 'pak': track_pak(t),
                                   'model': model})
    return _sky_cache


def ambiance_sky(track):
    """Ciel choisi (entree de sky_catalog) ou None (ciel d'origine de la piste)."""
    p = ambiance_path(track)
    key = (json.load(open(p)).get('sky') or None) if os.path.exists(p) else None
    return next((s for s in sky_catalog() if s['key'] == key), None) if key else None


# + courbes (igVfxRangedCurveMetaField, 84 o sans pointeur) : degrade du ciel et couleur de la lumiere d'ambiance
SKY_SIMPLE_FIELDS = ('igBoolMetaField', 'igFloatMetaField', 'igVec2fMetaField', 'igVec3fMetaField', 'igVec4fMetaField',
                     'igVfxRangedCurveMetaField')


def sky_source(sky):
    """_Lighting d'origine de la piste dont on prend le ciel."""
    return IgzFile(pak_tool.read_latest(ARCHIVES, lighting_file(sky['key']), sky['pak'])[0])


def apply_sky(z, sky):
    """Ciel ET atmosphere de la piste choisie. Le nom seul ne suffisait pas (valide en jeu sur Roo's Tubes : ciel
    invisible, piste sombre, trainees) : Roo's Tubes a le degrade du ciel coupe, _skyFade = 1 (ciel fondu), un
    eclairage de grotte sous-marine et des reflets « sous l'eau ». Repris de la piste source : nom du ciel, degrade,
    reflets (sondes), tous les reglages simples (nombres, couleurs, indicateurs) du groupe d'eclairage par defaut ;
    le reflet local propre a la piste (_environmentMap1) est retire."""
    src = sky_source(sky)
    wvd = lambda f: next(o for o, t in f.objects.items() if t == 'CWorldVisualData')
    o, so = wvd(z), wvd(src)
    sd = src.dump_object(so)
    z.set_string_ref(z.find_field(o, '_farSkyModelName4')[0], sky['name'])
    z.set_field(o, '_skyGradientEnabled', bool(sd.get('_skyGradientEnabled')))
    for f in ('_environmentMap', '_specularEnvironmentMap'):
        z.set_string_ref(z.find_field(o, f)[0], sd.get(f))
    off = z.find_field(o, '_environmentMap1')[0]
    if z.u64(off):
        struct.pack_into('<Q', *z._loc(off), 0)
        z._mark('ROFS', off, False)
    grp = lambda f: next(o for o, t in f.objects.items() if t == 'CWorldVisualDataGroup')
    g, sg = grp(z), grp(src)
    fields = sorted(z.fields_of('CWorldVisualDataGroup').items())
    size = z.size_of('CWorldVisualDataGroup')
    fixed = z.offset_sets.get('ROFS', set()) | z.offset_sets.get('RSTT', set()) | z.offset_sets.get('RHND', set())
    n = 0
    for i, (fo, (name, ftype)) in enumerate(fields):
        if ftype not in SKY_SIMPLE_FIELDS:
            continue
        end = fields[i + 1][0] if i + 1 < len(fields) else size
        if any(g + fo <= p < g + end for p in fixed):
            continue                                       # jamais de pointeur recopie
        width = {'igBoolMetaField': 1, 'igFloatMetaField': 4, 'igVec2fMetaField': 8, 'igVec3fMetaField': 12,
                 'igVec4fMetaField': 16}.get(ftype, end - fo)
        sb, sof = src._loc(sg + fo)
        db, dof = z._loc(g + fo)
        db[dof:dof + min(width, end - fo)] = sb[sof:sof + min(width, end - fo)]
        n += 1
    return n


def _probe_logical(s):
    """'loosetextures:\\probes\\T111_Crash_Cove_Probe.dds' -> 'loosetextures/probes/t111_crash_cove_probe.igz'."""
    rel = s.replace('\\', '/').split(':', 1)[-1].lstrip('/')
    return 'loosetextures/' + os.path.splitext(rel)[0].lower() + '.igz'


def sky_install_files(track):
    """(entrees du manifeste, {fichier: archive source} a copier) du ciel de la piste : celui choisi, sinon le sien.
    Le sien aussi : sur une piste copiee (Piste / categorie), le manifeste declare les textures du ciel sous le nouveau
    nom (skybox!T901_Custom_Map!...), alors que le materiau, partage et lu dans update2, demande celles de la piste source
    (skybox!T111_Crash_Cove!...) : presentes dans l'archive mais jamais chargees, plus de ciel en jeu."""
    sky, own, probes = ambiance_sky(track), False, []
    if sky:
        sd = sky_source(sky).dump_object(next(o for o, t in sky_source(sky).objects.items() if t == 'CWorldVisualData'))
        probes = [('texture', _probe_logical(sd[f])) for f in ('_environmentMap', '_specularEnvironmentMap') if sd.get(f)]
    else:
        rows = pkg_manifest.entries(pak_tool.read_latest(ARCHIVES, pkg_manifest.manifest_logical(track), track_pak(track))[0])
        model = next((p for ty, p in rows if ty == 'sky_model'), None)
        if not model:
            return [], {}
        sky, own = {'model': model, 'pak': track_pak(track)}, True
    entries, copies = [], {}
    deps = library.dependencies(lambda lg: read_game_file(track, lg, (sky['pak'],)), sky['model'])
    for typ, lg in list(dict.fromkeys(probes)) + deps:
        if not library.available(ARCHIVES, lg, track_pak(track)):
            src = library.find_pak(ARCHIVES, lg, (sky['pak'],))
            if src is None:
                if own:                                      # ciel d'origine : l'installation n'en depend pas
                    continue
                raise KeyError(f'fichier du ciel introuvable : {lg}')
            copies[_archive_case(src, lg)] = src
        entries.append(('sky_model' if lg.lower() == sky['model'].lower() else typ, lg))
    return entries, copies


def ambiance_info(track):
    z = IgzFile(pak_tool.read_latest(ARCHIVES, lighting_file(track), track_pak(track))[0])
    p = ambiance_path(track)
    cur = json.load(open(p)) if os.path.exists(p) else {}
    stripped = bool(newmap_settings(track).get('strip_art'))
    sky = ambiance_sky(track)                          # ciel d'une autre piste : son eclairage sert de reference
    return {'original': _ambiance_read(sky_source(sky) if sky else z), 'values': cur.get('values') or {},
            'preset': cur.get('preset', 'day'),
            'presets': AMBIANCE_PRESETS, 'skies': [{k: s[k] for k in ('key', 'label')} for s in sky_catalog()],
            'sky': cur.get('sky') or '', 'original_sky': _sky_name(z), 'stripped': stripped}


def set_ambiance(req):
    """req = {track, preset, values, sky} : ambiance enregistree puis fichier _Lighting reconstruit (avec « Nouvelle
    map » s'il y a lieu). values vide = eclairage d'origine ; sky = piste dont on prend le ciel ('' : celui d'origine)."""
    track = req['track']
    values = {k: v for k, v in (req.get('values') or {}).items() if k in AMBIANCE_FIELDS}
    sky = req.get('sky') or ''
    if sky == track and _sky_name(IgzFile(pak_tool.read_latest(ARCHIVES, lighting_file(track), track_pak(track))[0])):
        sky = ''                                           # son propre ciel = celui d'origine
    if sky and sky not in {s['key'] for s in sky_catalog()}:
        raise ValueError(f'ciel inconnu : {sky}')
    os.makedirs(OUT_DIR, exist_ok=True)
    if values or sky:
        json.dump({'preset': req.get('preset', 'custom'), 'values': values, 'sky': sky}, open(ambiance_path(track), 'w'), indent=1)
    elif os.path.exists(ambiance_path(track)):
        os.remove(ambiance_path(track))
    moved = 'lighting' in (newmap_settings(track).get('move_away') or [])
    rep = rebuild_map_file(track, lighting_file(track), moved)
    return {'report': [rep or 'éclairage d\'origine']}


def lights_path(track):
    return os.path.join(OUT_DIR, f'{track}_lights.json')


def read_lights(track):
    """Lumieres ponctuelles ajoutees (lights.py) : [{pos, color, intensity, radius, preset?}]."""
    p = lights_path(track)
    return lights.clean(json.load(open(p))) if os.path.exists(p) else []


def write_lights(track, items):
    """Enregistre les lumieres ajoutees puis reconstruit le _Lighting principal. -> rapport."""
    items = lights.clean(items)
    if items:
        json.dump(items, open(lights_path(track), 'w'), indent=1)
    elif os.path.exists(lights_path(track)):
        os.remove(lights_path(track))
    moved = 'lighting' in (newmap_settings(track).get('move_away') or [])
    return rebuild_map_file(track, lighting_file(track), moved) or 'éclairage d\'origine'


def moved_away_logicals(track):
    """Fichiers « descendus » enregistres (a installer / suivre dans l'historique)."""
    return [_logical_case(track, p) for files in move_away_files(track).values() for p in files
            if os.path.exists(saved_path(_logical_case(track, p)))]


_orig_ids_cache = {}


def original_ids(track, art):
    """Ids des objets du fichier de decor d'origine (les objets ajoutes ont d'autres ids)."""
    if (track, art) not in _orig_ids_cache:
        _orig_ids_cache[(track, art)] = {o['id'] for o in DecorFile(pak_tool.read_latest(ARCHIVES, art, track_pak(track))[0]).objects()}
    return _orig_ids_cache[(track, art)]


def _import_label(info):
    """Lot d'import d'un modele importe. Anciens imports (sans 'import') : nom donne a l'import, retrouve devant
    l'objet OBJ dans le nom du modele (« Mario_Circuit_3_B0__M_... _6 » -> « Mario_Circuit_3 (n°6) »)."""
    if info.get('import'):
        return info['import']
    name, obj = info.get('name') or '?', _clean_name(info.get('obj_object') or '', '')[:6]
    i = name.find('_' + obj) if obj else -1
    if i <= 0:
        return re.sub(r'_p\d+$', '', name)
    m = re.search(r'_(\d+)$', name)                        # suffixe ajoute quand le nom etait deja pris
    return name[:i] + (f' (n°{m.group(1)})' if m else '')


def added_groups(track, current=None):
    """Objets ajoutes au decor enregistre, par groupe : [{key, label, kind ('import' | 'library' | 'copies'),
    count, objects: [[fichier, id]]}]. Plaques de booster exclues (elles suivent les boosters du mode Course).
    current : {fichier: objets} deja lus (sinon lus ici)."""
    reg, links = custom_models(track), load_links(track)
    groups = {}
    for art in art_files(track):
        orig = original_ids(track, art)
        objs = current[art] if current else DecorFile(base_file(track, art)[0]).objects()
        for o in objs:
            if o['id'] in orig or (o['name'] or '').startswith(BOOST_VISUAL_PREFIX):
                continue
            lk = links.get(art, {}).get(str(o['id']))
            logical = model_logical_path(o['model'])
            if isinstance(lk, dict) and lk.get('library'):
                name = os.path.basename(logical)[:-4]
                key, label, kind = 'lib:' + name.lower(), f'{name} (de {library.nice(lk["library"])})', 'library'
            elif logical in reg:
                label = _import_label(reg[logical])
                key, kind = 'imp:' + label, 'import'
            else:
                key, label, kind = 'copies', 'Copies d\'objets d\'origine', 'copies'
            g = groups.setdefault(key, {'key': key, 'label': label, 'kind': kind, 'count': 0, 'objects': []})
            g['count'] += 1
            g['objects'].append([art, o['id']])
    order = {'import': 0, 'library': 1, 'copies': 2}
    return sorted(groups.values(), key=lambda g: (order[g['kind']], g['label'].lower()))


def apply_newmap(req):
    """req = {track, strip_ground, strip_art: [fichiers _Art], move_away: [groupes], remove: [cles de
    added_groups]} : enregistre les reglages, reecrit les fichiers de decor (tous les objets d'origine retires des
    fichiers coches ; un fichier decoche retrouve les siens ; objets ajoutes des groupes de remove supprimes) et
    recalcule la collision (seulement les modeles importes si strip_ground)."""
    track = req['track']
    remove = defaultdict(set)
    for g in added_groups(track):
        if g['key'] in (req.get('remove') or []):
            for art, oid in g['objects']:
                remove[art].add(oid)
    before = newmap_settings(track)
    s = {'strip_ground': bool(req.get('strip_ground')),
         'strip_art': [a for a in (req.get('strip_art') or []) if a in art_files(track)],
         'move_away': [k for k in (req.get('move_away') or []) if k in dict((g[0], g) for g in MOVE_AWAY_GROUPS)]}
    if 'disable_instances' in before:                  # reglage de diagnostic conserve
        s['disable_instances'] = before['disable_instances']
    os.makedirs(OUT_DIR, exist_ok=True)
    json.dump(s, open(newmap_path(track), 'w'), indent=1)
    # piste sans vrai ciel (Roo's Tubes, Mystery Caves : le fond est un decor) videe : sans ciel, grosses trainees en
    # jeu -> ciel et eclairage de Crash Cove, si aucun ciel n'est choisi (modifiable : Ambiance > Ciel)
    auto_sky = False
    if s['strip_art'] and not ambiance_sky(track) and \
            not _sky_name(IgzFile(pak_tool.read_latest(ARCHIVES, lighting_file(track), track_pak(track))[0])):
        p = ambiance_path(track)
        cur = json.load(open(p)) if os.path.exists(p) else {}
        json.dump({'preset': cur.get('preset', 'day'), 'values': cur.get('values') or {}, 'sky': 'T111_Crash_Cove'},
                  open(p, 'w'), indent=1)
        auto_sky = True
    report = write_moved_away(track, s['move_away'])
    if auto_sky:
        rebuild_map_file(track, lighting_file(track), 'lighting' in s['move_away'])
        report.append('piste sans ciel : ciel et éclairage de Crash Cove ajoutés (modifiable : Ambiance › Ciel)')
    for art in art_files(track):
        was, now = art in (before.get('strip_art') or []), art in s['strip_art']
        if was == now and not now and not remove[art]:
            continue
        df = DecorFile(base_file(track, art)[0])
        n0 = len(df.objects())
        df.delete_many(remove[art])                       # tes ajouts retires (definitif : « ↶ Annuler » pour revenir)
        write_art(track, art, df, restore_originals=was and not now)
        n1 = len(DecorFile(open(saved_path(art), 'rb').read()).objects())
        report.append(f'{os.path.basename(art)[len(track) + 1:-4]} : {n0} -> {n1} objets'
                      + (f' dont {len(remove[art])} ajout(s) supprime(s)' if remove[art] else ''))
    if s['strip_ground'] or s['strip_art']:              # map videe : boosters de l'ancien sol retires (apres les
        msg = remove_boosters(track)                     # fichiers de decor : leurs ids d'ajouts sont remappes)
        if msg:
            report.append(msg)
    report.append(defer_collision(track))
    return {'report': report, 'settings': s, 'remaining': remaining_elements(track)}


def remove_boosters(track):
    """Boosters ajoutes par l'editeur (zones du _Design, ou d'un ancien _Power_Up) et leurs plaques au sol retires :
    « Nouvelle map », generation de l'onglet Creation (le sol change, ils restaient poses sur l'ancien). Caisses et
    boosters du jeu inchanges. -> rapport ou None."""
    if not crates_supported(track):
        return None
    cur = read_track_crates(track)
    n = sum(c['kind'] == 'boost' for c in cur)
    if n:
        logical = crate_file(track)
        z, _ = write_crates_file(track, [c for c in cur if c['kind'] != 'boost'])
        safe_compact(track, logical, z)
        z.save(saved_path(logical))
    vis = sync_boost_visuals(track, [])
    return f'{n} booster(s) retiré(s)' if n else (None if vis == 'aucun booster' else 'plaques de booster retirées')


def write_art(track, logical, df, restore_originals=False):
    """Ecrit le fichier de decor `df` RECONSTRUIT depuis l'original : suppressions, transformations, puis toutes
    les copies / imports en un seul passage (duplicate_many). Les editions successives sur la version sauvee
    laissaient des blocs abandonnes (anciennes listes racine, ~500 Ko par objet ajoute) : le fichier reste ainsi
    a la taille de l'original + les objets ajoutes. Les ids des objets ajoutes changent : liens remappes.
    Retourne {ancien id: nouvel id}."""
    links = load_links(track)
    fl = links.get(logical, {})
    orig = DecorFile(pak_tool.read_latest(ARCHIVES, logical, track_pak(track))[0])
    z = orig.igz
    oobjs = {o['id']: o for o in orig.objects()}
    cur = df.objects()
    cids = {o['id'] for o in cur}
    holders, sunk = [], set()
    if logical in (newmap_settings(track).get('strip_art') or []):
        # entites animees / scriptees (CGameEntity, CEntity : voiles et drapeaux des bateaux de Crash Cove avec leur
        # script d'animation, son « bolte ») : descendues sous la carte, PAS supprimees (supprimees : plantage au
        # debut du chargement de la piste suivante, liste parent / enfants du jeu corrompue)
        # nouvelle map : tous les objets d'origine retires, SAUF l'entite qui active le maillage de sol ou vont les
        # triangles des modeles importes (sans elle le jeu ne charge pas ce maillage : on passe au travers)
        owner = ground_owner(track)
        keep = {i for i, o in oobjs.items() if owner and (logical, o['name']) == owner}
        sunk = {r for r in orig.roots if z.objects.get(r) in ('CGameEntity', 'CEntity')} - keep
        cids = (cids - set(oobjs)) | keep | sunk
        cur = [o for o in cur if o['id'] not in oobjs or o['id'] in keep] + \
              [oobjs[i] for i in keep if i not in {o['id'] for o in cur}]
        # entites sans modele qui en regroupent d'autres (prefabriques : Roo's Tubes « C3_Sea_KelpBunch01 » ->
        # igPrefabComponentData -> liste d'entites) : retirees aussi, sinon leurs enfants restaient atteignables
        holders = [r for r in orig.roots if z.objects.get(r) in ENTITY_TYPES and r not in oobjs and r not in sunk]
    elif restore_originals:                            # fin du mode « nouvelle map » : les objets d'origine reviennent
        cur = cur + [o for i, o in oobjs.items() if i not in cids]
        cids |= set(oobjs)
    orig.delete_many([i for i in oobjs if i not in cids] + holders)
    for r in sunk:
        x, y, zz = z.vec3(r + 0x20)
        struct.pack_into('<3f', *z._loc(r + 0x20), x, y, zz + MOVE_AWAY_DZ)
    for o in cur:
        if o['id'] in oobjs:
            a = oobjs[o['id']]
            if any(abs(x - y) > 1e-6 for x, y in zip(o['pos'] + o['euler'] + o['scale'], a['pos'] + a['euler'] + a['scale'])):
                orig.set_transform(o['id'], o['pos'], o['euler'] if a['has_transform'] else None,
                                   o['scale'] if a['has_transform'] else None)
    added = sorted((o for o in cur if o['id'] not in oobjs), key=lambda o: o['id'])
    tmpl = template_object(track, logical) if added else None   # entite minimale : modele + statique
    specs = []
    for o in added:
        info = fl.get(str(o['id']))
        src = int(info) if info is not None and not isinstance(info, dict) and int(info) in z.objects else tmpl
        if src is None:
            raise ValueError(f'{os.path.basename(logical)} : aucun objet modèle à copier dans ce fichier '
                             f'(ajoute plutôt dans {os.path.basename(main_art(track))})')
        tr = z.deref(src + 0x30) is not None
        specs.append((src, o['name'], o['pos'], o['euler'] if tr else None, o['scale'] if tr else None))
    new_ids = orig.duplicate_many(specs)
    for o, (src, *_), nid in zip(added, specs, new_ids):
        if orig._model_of(nid) != o['model']:          # import (ou copie sans source connue) : son propre modele
            orig.set_model(nid, o['model'])
    idmap = {o['id']: nid for o, nid in zip(added, new_ids)}
    links[logical] = {str(idmap[int(k)]): v for k, v in fl.items() if int(k) in idmap}
    save_links(track, links)
    # pas de compact() ici : l'id d'un objet de decor est son adresse dans le fichier (le suivi des objets d'origine
    # en depend) ; la reconstruction depuis l'original ne laisse qu'une liste racine abandonnee (~70 Ko)
    open(saved_path(logical), 'wb').write(orig.to_bytes())
    return idmap


# -- apercu texture ---------------------------------------------------------------------------
_preview_cache, _texture_png_cache = {}, {}


def preview_read(track, logical):
    """Octets d'un materiau / d'une texture : importe (out/editor/textures) sinon archives ; None si absent."""
    p = custom_file_path(logical)
    if os.path.exists(p):
        return open(p, 'rb').read()
    try:
        return read_game_file(track, logical)
    except KeyError:
        return None


def model_preview_binary(track, file_name):
    """u32 nb sommets, nb indices, nb groupes ; float32 positions[3n], uv[2n] ; uint32 indices[m] ;
    groupes (u32 debut, nb, 1 + indice de texture ou 0) ; u32 longueur + JSON [{ns, decal}] des textures."""
    logical = model_logical_path(file_name)
    if logical not in _preview_cache and wall_mesh(track, logical):           # mur invisible : sa collision, sans texture
        pos, tris = wall_mesh(track, logical)
        P, I = np.asarray(pos, '<f4').reshape(-1, 3), np.asarray(tris, '<u4').reshape(-1)
        _preview_cache[logical] = (struct.pack('<III', len(P), len(I), 0) + P.tobytes() + np.zeros((len(P), 2), '<f4').tobytes()
                                   + I.tobytes() + struct.pack('<I', 2) + b'[]')
    if logical not in _preview_cache:
        try:
            pv = preview.model_preview(model_bytes(track, logical), lambda lg: preview_read(track, lg))
        except Exception:  # noqa: BLE001 - modele illisible : vide
            traceback.print_exc()
            pv = {'positions': np.zeros((0, 3), np.float32), 'uvs': np.zeros((0, 2), np.float32),
                  'indices': np.zeros(0, np.uint32), 'groups': []}
        texs = sorted({g[2] for g in pv['groups'] if g[2]})
        head = struct.pack('<III', len(pv['positions']), len(pv['indices']), len(pv['groups']))
        groups = b''.join(struct.pack('<III', s, n, texs.index(t) + 1 if t else 0) for s, n, t in pv['groups'])
        js = json.dumps([{'ns': ns, 'decal': decal} for ns, decal in texs]).encode()
        _preview_cache[logical] = (head + pv['positions'].astype('<f4').tobytes() + pv['uvs'].astype('<f4').tobytes()
                                   + pv['indices'].astype('<u4').tobytes() + groups + struct.pack('<I', len(js)) + js)
    return _preview_cache[logical]


def texture_png(track, ns, max_size=256):
    """Texture couleur decodee (PNG RGBA, niveau de mipmap <= max_size), cache memoire + disque par contenu."""
    import hashlib
    from PIL import Image
    data = preview_read(track, f'textures/{ns}.igz')
    if data is None:
        raise KeyError(f'texture absente : {ns}')
    key = hashlib.md5(data).hexdigest() + f'_{max_size}'
    if key not in _texture_png_cache:
        cache_dir = os.path.join(OUT_DIR, 'cache', 'textures')
        p = os.path.join(cache_dir, key + '.png')
        if os.path.exists(p):
            _texture_png_cache[key] = open(p, 'rb').read()
        else:
            rgba, _ = preview.decode_texture(data, max_size)
            buf = io.BytesIO()
            Image.fromarray(rgba, 'RGBA').save(buf, 'PNG', compress_level=1)
            os.makedirs(cache_dir, exist_ok=True)
            open(p, 'wb').write(buf.getvalue())
            _texture_png_cache[key] = buf.getvalue()
    return _texture_png_cache[key]


def save_decor(req):
    """req = {track, files: {logique: {moves: {id: {pos, euler, scale}}, duplicates: [{src, pos, euler, scale}],
    deleted: [id]}}, ops: [modifications du clic droit gardees en attente : {op: 'surface', objects, surface} |
    {op: 'invisible', model, invisible}]}. Les ids sont ceux de la version chargee (sauvee ou originale) ; la
    collision n'est recalculee qu'une fois, a la fin."""
    track, report = req['track'], []
    os.makedirs(OUT_DIR, exist_ok=True)
    if req.get('lights') is not None:                # lumieres ajoutees (lampadaires...) : fichier _Lighting
        report.append('lumières : ' + write_lights(track, req['lights']))
    for op in req.get('ops') or []:                  # avant les suppressions / copies : ids encore valables
        sub = dict(op, track=track)
        if op.get('op') == 'surface':
            report += set_surface(sub, sync=False)['report']
        elif op.get('op') == 'invisible':
            report += set_invisible(sub, sync=False)['report']
        else:
            raise ValueError(f"modification inconnue : {op.get('op')}")
    for logical, ed in progress.items(req.get('files', {}).items(), 'écriture du décor ({i} / {n})', 0.0, 0.25):
        if logical not in art_files(track):
            raise ValueError(f'{logical} n\'est pas un fichier de decor de {track}')
        data, _ = base_file(track, logical)
        df = DecorFile(data)
        names = {o['id']: o['name'] for o in df.objects()}
        links = load_links(track)
        file_links = links.setdefault(logical, {})
        for sid, m in ed.get('moves', {}).items():
            # objet sans transformation (position seule) : rotation / echelle neutres envoyees quand meme (pack de
            # maps : decor d'origine deplace par « Deplacer / Changer l'echelle de toute la map ») -> ignorees
            has_tr = df.igz.deref(int(sid) + 0x30) is not None
            df.set_transform(int(sid), m.get('pos'), m.get('euler') if has_tr else None, m.get('scale') if has_tr else None)
        specs, used = [], set(df.names.values())
        for d in ed.get('duplicates', []):
            src = int(d['src'])
            has_tr = df.igz.deref(src + 0x30) is not None
            base, k = names.get(src) or 'objet', 1
            while f'{base}_copie{k:02d}' in used:
                k += 1
            used.add(f'{base}_copie{k:02d}')
            specs.append((src, f'{base}_copie{k:02d}', d.get('pos'),
                          d.get('euler') if has_tr else None, d.get('scale') if has_tr else None))
        for (src, *_), new_id in zip(specs, df.duplicate_many(specs)):
            # copie -> objet d'origine, ou meme lien que la source (copie de copie / de modele importe)
            file_links[str(new_id)] = file_links.get(str(src), src)
        save_links(track, links)
        df.delete_many([int(s) for s in ed.get('deleted', [])])
        write_art(track, logical, df)
        report.append(f'{os.path.basename(logical)} : {len(ed.get("moves", {}))} modifies, '
                      f'{len(ed.get("duplicates", []))} dupliques, {len(ed.get("deleted", []))} supprimes')
    if not req.get('files') and not req.get('ops') and not collision_pending(track):
        return {'report': report, 'boosts_changed': False}  # lumieres seules : decor et collision inchanges
    with progress.span(0.25, 0.95):
        # defer : modifications en attente enregistrees avant une operation immediate (page) ; collision a « Enregistrer »
        report.append(defer_collision(track) if req.get('defer') else sync_collision(track))
    progress.step('boosters', 0.95)
    boosts = boosts_from_decor(track)
    if boosts:
        report.append(boosts)
    return {'report': report, 'boosts_changed': bool(boosts)}


def boosts_from_decor(track):
    """Plaques de booster deplacees / tournees / redimensionnees / dupliquees / supprimees en mode Decor : les
    boosters (zones de turbo du fichier _Power_Up) suivent. Une plaque = un booster (modele BoostPad), position au
    sol = plaque - BOOST_VISUAL_LIFT, cap = cap de la plaque, profondeur / largeur = echelle x 100 ; la hauteur de
    zone est gardee. Retourne un rapport, ou None si rien n'a change."""
    art = main_art(track)
    p = saved_path(art)
    if not os.path.exists(p):
        return None
    vis = sorted((o for o in DecorFile(open(p, 'rb').read()).objects()
                  if re.search(r'\\boostpad(super|_[a-z]+)?\.igb$', (o['model'] or '').lower())), key=lambda o: o['name'])
    logical = crate_file(track)
    if logical is None:
        return None
    cur = read_track_crates(track)
    old = [c for c in cur if c['kind'] == 'boost']
    if not vis and not old:
        return None
    new = []
    for k, v in enumerate(vis):
        h = old[k]['dims'][2] if k < len(old) else powerup.BOOST_DIMS[2]
        # reglages (vitesse, duree) gardes : la plaque ne les porte pas ; couleur = celle de la plaque
        prev = {x: old[k][x] for x in ('speed', 'duration') if k < len(old) and x in old[k]}
        new.append({'kind': 'boost', 'pos': [round(v['pos'][0], 2), round(v['pos'][1], 2), round(v['pos'][2] - BOOST_VISUAL_LIFT, 2)],
                    'yaw': round(v['euler'][2], 5), 'tilt': [round(v['euler'][0], 5), round(v['euler'][1], 5)],
                    'dims': [round(abs(v['scale'][0]) * 100, 1), round(abs(v['scale'][1]) * 100, 1), h],
                    **boost_settings({**prev, 'color': boost_color_of_model(v['model']),
                                      'super': boost_color_of_model(v['model']) == 'bleu' and not prev})})
    same = len(new) == len(old) and all(
        n['super'] == bool(o.get('super')) and
        max(abs(a - b) for a, b in zip(n['pos'] + [n['yaw']] + n['tilt'] + n['dims'],
                                       o['pos'] + [o['yaw']] + list(o.get('tilt') or [0.0, 0.0]) + o['dims'])) < 1.0
        for n, o in zip(new, old))
    if same:
        return None
    want = [c for c in cur if c['kind'] != 'boost'] + new
    z, _ = write_crates_file(track, want)
    safe_compact(track, logical, z)
    z.save(saved_path(logical))
    return f'boosters mis a jour depuis les plaques du decor : {len(new)}'


def links_path(track):
    return os.path.join(OUT_DIR, f'{track}_decor_links.json')


def load_links(track):
    """{fichier: {id de copie: id de l'objet d'origine}} : memorise a l'enregistrement des copies."""
    p = links_path(track)
    return json.load(open(p)) if os.path.exists(p) else {}


def save_links(track, links):
    os.makedirs(OUT_DIR, exist_ok=True)
    json.dump(links, open(links_path(track), 'w'), indent=1)


# -- historique des enregistrements (« Annuler le dernier enregistrement ») ---------------------
HISTORY_KEEP = 20


def history_dir(track):
    return os.path.join(OUT_DIR, 'history', track)


def _tracked_files(track):
    """Fichiers enregistres d'une piste : (nom dans la copie, chemin courant)."""
    names = [race_file(track), ttr_file(track), collision_file(track), start_finish.design_file(track),
             start_finish.main_map_file(track), powerup.powerup_file(track)] + list(art_files(track))
    names += [_logical_case(track, p) for files in move_away_files(track).values() for p in files]
    names += [lighting_file(track)] if lighting_file(track) not in names else []
    names += minimap_logicals(track)
    names += list(menu_logicals(track).values())               # nom et images de menu (saved_path : nom de base)
    names += [s['key'] for s in flyby_shots(track)]            # cameras du survol d'introduction
    out = [(os.path.basename(n), saved_path(n)) for n in names]
    out += [(os.path.basename(flyby_path(track)), flyby_path(track))]
    out += [(os.path.basename(links_path(track)), links_path(track)),
            (f'{track}_custom_models.json', os.path.join(OUT_DIR, f'{track}_custom_models.json')),
            (f'{track}_custom_textures.json', custom_textures_path(track)),
            (f'{track}_newmap.json', newmap_path(track)), (f'{track}_road.json', road_source_path(track)),
            (f'{track}_minimap.json', os.path.join(OUT_DIR, f'{track}_minimap.json')),
            (f'{track}_light.json', light_path(track)),
            (f'{track}_menu.json', menu_settings_path(track)),
            (f'{track}_lights.json', lights_path(track)),
            (f'{track}_ambiance.json', ambiance_path(track)),
            (f'{track}_music.json', music_settings_path(track)),
            (f'{track}_times.json', times_path(track))]
    out += [('music_'+ os.path.basename(lg), music_path(track, lg)) for lg, _ in music_streams(track)]
    reg = custom_models(track)
    out += [('models/' + os.path.basename(k), custom_model_path(k)) for k in reg]
    out += [('models/' + os.path.basename(wall_mesh_path(k)), wall_mesh_path(k)) for k, v in reg.items() if v.get('invisible')]
    return out


# -- musique de la piste (voir music.py) ------------------------------------------------------
# Fichiers par piste dans out/editor/music/<piste>/ : deux pistes creees sur la meme base ont les memes noms de fichiers.
MUSIC_KINDS = ('main', 'fl')
MUSIC_FAST = 1.06                                       # « un peu plus rapide » : ecart habituel du jeu au dernier tour
_music_cache = {}


def _music_bank(track):
    """Banque de musique de la piste, designee par sa carte (une piste creee utilise celle de sa base)."""
    main = base_file(track, start_finish.main_map_file(track))[0]
    m = re.search(rb'sounds:/(banks/MUS/[^\0]+?\.igz)', main, re.I)
    bank = 'sounds/' + (m.group(1).decode('latin1') if m else f'banks/MUS/MUS_{track}_bank.igz')
    return pak_tool.read_latest(ARCHIVES, bank, track_pak(track))[0]


def music_streams(track):
    """[(fichier .snd, 'main' | 'fl')] references par la banque de musique de la piste (les pistes de boss en ont deux
    de chaque)."""
    if track in _music_cache:
        return _music_cache[track]
    out = []
    try:
        data = _music_bank(track)
        for raw in dict.fromkeys(re.findall(rb'data:/(sound_streams/[^\0]+?\.snd)', data, re.I)):
            lg = raw.decode('latin1')
            if pak_tool.archives_with(ARCHIVES, lg, track_pak(track)):
                out.append((lg, 'fl' if os.path.basename(lg).split(',')[0].lower().endswith('_fl') else 'main'))
    except (KeyError, OSError, ValueError):             # piste sans musique propre : fonction indisponible
        traceback.print_exc()
    _music_cache[track] = out
    return out


def music_path(track, logical):
    return os.path.join(OUT_DIR, 'music', track, os.path.basename(logical))


def music_settings_path(track):
    return os.path.join(OUT_DIR, f'{track}_music.json')


def music_settings(track):
    p = music_settings_path(track)
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {}


def _music_write_settings(track, st):
    if st:
        json.dump(st, open(music_settings_path(track), 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    elif os.path.exists(music_settings_path(track)):
        os.remove(music_settings_path(track))


def _music_original(track, logical):
    return pak_tool.read_latest(ARCHIVES, logical, track_pak(track))[0]


def music_install_files(track):
    return {lg: open(music_path(track, lg), 'rb').read() for lg, _ in music_streams(track) if os.path.exists(music_path(track, lg))}


def music_continues(track):
    """Dernier tour : la musique de la course continue (copie du script de musique, voir music.py) ?"""
    return music_settings(track).get('fl', {}).get('mode') == 'continue'


def music_continue_files(track):
    """-> (fichier de la carte, carte qui utilise la copie du script, copie du script)."""
    script = pak_tool.read_latest(ARCHIVES, music.MANAGER_SCRIPT, track_pak(track))[0]
    logical = start_finish.main_map_file(track)
    return logical, music.continue_map(base_file(track, logical)[0], script), music.continue_script(script)


def music_info(track):
    st, kinds = music_settings(track), {}
    for k in MUSIC_KINDS:
        files = [lg for lg, x in music_streams(track) if x == k]
        info = {'available': bool(files), 'custom': False, 'name': None, 'seconds': None}
        if files:
            custom = os.path.exists(music_path(track, files[0]))
            data = open(music_path(track, files[0]), 'rb').read(4096) if custom else _music_original(track, files[0])   # en-tetes jusqu'a 17 Ko
            info.update(custom=custom, seconds=round(music.read_header(data)['seconds'], 1), name=st.get(k, {}).get('name') if custom else None)
        kinds[k] = info
    exe = find_ffmpeg()
    return {'ffmpeg': bool(exe), 'ffmpeg_path': exe, 'continues': music_continues(track), **kinds}


def find_ffmpeg():
    """ffmpeg : celui indique dans la fenetre Musique (reglage 'ffmpeg'), sinon a cote de l'exe, sinon dans le PATH."""
    music.FFMPEG_PATH = load_config().get('ffmpeg')
    return music.find_ffmpeg()


def pick_ffmpeg(req):
    """POST /api/pick_ffmpeg {track, path?} : ffmpeg n'est pas distribue avec l'editeur. path (dossier ou programme),
    sinon fenetre de choix du dossier ; verifie (se lance, sait encoder en MP3) puis retenu.
    -> etat de la musique, {'cancelled': True} si la fenetre est fermee sans choix."""
    path = (req.get('path') or '').strip()
    if not path:
        path = ask_folder('Dossier qui contient ffmpeg (ffmpeg.exe, ou son dossier bin)', os.path.dirname(find_ffmpeg() or '') or None)
        if not path:
            return {'cancelled': True}
    exe = music.ffmpeg_in(path)
    if not exe:
        return {'invalid': 'Aucun ffmpeg à cet endroit (ni dans son dossier bin)'}
    try:
        music.check_ffmpeg(exe)
    except ValueError as e:
        return {'invalid': str(e)}
    save_config(ffmpeg=os.path.normpath(exe))
    return music_info(req['track'])


def music_audio(track, kind):
    """Flux joue en course, en MP3, pour l'ecoute dans la page."""
    lg = next((x for x, k in music_streams(track) if k == kind), None)
    if lg is None:
        raise KeyError(kind)
    p = music_path(track, lg)
    return music.stream_mp3(open(p, 'rb').read() if os.path.exists(p) else _music_original(track, lg))


def _music_upload_dir():
    return os.path.join(OUT_DIR, 'music', '_uploads')


def music_upload(data, filename, keep=False):
    """Fichier audio recu de la page, en attente de « music_apply » ; -> {id}. keep : 2e fichier du meme import."""
    d = _music_upload_dir()
    if not keep:
        shutil.rmtree(d, ignore_errors=True)            # envois abandonnes
    os.makedirs(d, exist_ok=True)
    ext = re.sub(r'[^a-z0-9.]', '', os.path.splitext(filename)[1].lower())[:8]
    name = f'{time.time_ns()}{ext}'
    open(os.path.join(d, name), 'wb').write(data)
    return {'id': name}


def _music_upload_file(upload):
    if not upload or not re.fullmatch(r'\d+(\.[a-z0-9]+)?', upload):
        raise ValueError('fichier audio manquant')
    p = os.path.join(_music_upload_dir(), upload)
    if not os.path.exists(p):
        raise ValueError('fichier audio envoyé introuvable : recommence')
    return p


def _music_store(track, kind, pcm, name, extra=None):
    """Encode et enregistre une musique sur tous les fichiers de ce type ; -> duree."""
    files = [lg for lg, k in music_streams(track) if k == kind]
    if not files:
        raise ValueError('cette piste n\'a pas ce type de musique')
    first = None
    os.makedirs(os.path.dirname(music_path(track, files[0])), exist_ok=True)
    for lg in files:
        orig = _music_original(track, lg)
        first = music.build(orig, pcm) if first is None else music.rebuild_for(orig, first)
        open(music_path(track, lg), 'wb').write(first)
    st = music_settings(track)
    st[kind] = {'name': name, **(extra or {})}
    _music_write_settings(track, st)
    return music.read_header(first)['seconds']


def music_apply(req):
    """req = {track, main: envoi ou null (garder), fl: {mode: 'keep' | 'continue' | 'same' | 'fast' | 'file', upload},
    main_name, fl_name, fade (bool), normalize (bool)} ; enregistre les .snd de la piste."""
    find_ffmpeg()                                     # chemin retenu (nouvelle session : la fenetre n'est pas toujours rouverte)
    track, fl = req['track'], req.get('fl') or {'mode': 'keep'}
    fade = 2.0 if req.get('fade', True) else 0.0
    normalize = req.get('normalize', True)
    if not music_streams(track):
        raise ValueError('musique de cette piste introuvable')
    report = []
    src = _music_upload_file(req['main']) if req.get('main') else None
    if fl.get('mode') in ('same', 'fast') and not src:
        raise ValueError('choisis d\'abord le morceau principal')
    try:
        if src:
            progress.step('décodage du morceau', 0.05)
            pcm = music.prepare(music.decode(src, normalize=normalize), fade)
            progress.step('encodage du morceau', 0.25)
            s = _music_store(track, 'main', pcm, req.get('main_name') or 'morceau importé')
            report.append(f'musique : {s:.0f} s')
        mode = fl.get('mode')
        if mode == 'continue':
            music_continue_files(track)                 # erreur ici si la piste ne s'y prete pas : rien d'enregistre
            music_clear(track, ['fl'])                  # plus de morceau a part
            _music_write_settings(track, {**music_settings(track), 'fl': {'mode': 'continue'}})
            report.append('dernier tour : la musique continue')
        elif mode == 'keep' and music_continues(track):  # retour au changement de morceau, la carte reste d'origine
            music_clear(track, ['fl'])
            report.append('dernier tour : musique d\'origine')
        elif mode != 'keep' and any(k == 'fl' for _, k in music_streams(track)):
            path = src if mode in ('same', 'fast') else _music_upload_file(fl.get('upload'))
            progress.step('dernier tour', 0.55)
            pcm = music.prepare(music.decode(path, MUSIC_FAST if mode == 'fast' else 1.0, normalize), fade)
            name = req.get('fl_name') if mode == 'file' else req.get('main_name')
            s = _music_store(track, 'fl', pcm, name or 'morceau importé', {'mode': mode})
            report.append(f'dernier tour : {s:.0f} s' + (f' (+{round((MUSIC_FAST - 1) * 100)} %)' if mode == 'fast' else ''))
    finally:
        shutil.rmtree(_music_upload_dir(), ignore_errors=True)
    if not report:
        raise ValueError('aucun morceau choisi')
    return {'report': report, **music_info(track)}


def music_clear(track, kinds):
    """Retire les musiques importees de ces types ; -> fichiers retires."""
    removed, st = [], music_settings(track)
    for lg, k in music_streams(track):
        p = music_path(track, lg)
        if k in kinds and os.path.exists(p):
            os.remove(p)
            removed.append(os.path.basename(p))
    for k in kinds:
        st.pop(k, None)
    _music_write_settings(track, st)
    return removed


def music_reset(req):
    n = music_clear(req['track'], [k for k in (req.get('kinds') or MUSIC_KINDS) if k in MUSIC_KINDS])
    return {'removed': n, **music_info(req['track'])}


# -- temps des reliques et des fantomes du contre-la-montre (race_times.py) -----------------------
# Reglages dans out/editor/<piste>_times.json : {'relic': {palier: [4 valeurs]}, 'ghosts': {'unlock': s, 'times': [4]}}
# (seulement ce qui differe du jeu). Appliques a l'installation : zoneinfo de la piste et GhostData (partage par toutes
# les pistes : il recoit les reglages de toutes les pistes de ce dossier), enregistrements .igb du dossier ghosts du jeu
# (copie d'origine gardee a cote : <fichier>.ctrmod).
GHOST_BACKUP = '.ctrmod'


def times_path(track):
    return os.path.join(OUT_DIR, f'{track}_times.json')


def times_settings(track):
    p = times_path(track)
    try:
        return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {}
    except ValueError:
        return {}


def ghost_dir():
    return os.path.join(os.path.dirname(ARCHIVES), 'ghosts')


def _times_source(track):
    """Piste dont le zoneinfo d'origine sert (piste creee : celle d'ou elle vient)."""
    for t in (custom_category.read_state(ARCHIVES) or {}).get('tracks', []):
        if t['id'].lower() == track.lower():
            return t['source']
    return track


def _relic_original(track):
    try:
        return race_times.read_relic(pak_tool.read_latest(ARCHIVES, race_times.zoneinfo_logical(_times_source(track)),
                                                          race_times.zoneinfo_pak())[0])
    except KeyError:
        return {}


def _ghost_data_original():
    return pak_tool.read_latest(ARCHIVES, race_times.GHOST_DATA, race_times.GHOST_PAK)[0]


def _ghost_original_time(f):
    p = os.path.join(ghost_dir(), f)
    for q in (p + GHOST_BACKUP, p):
        if os.path.exists(q):
            return race_times.igb_time(open(q, 'rb').read(4096))
    return race_times.name_time(f)


def times_info(track):
    st = times_settings(track)
    orig = _relic_original(track)
    relic = {k: (st.get('relic') or {}).get(k) or v for k, v in orig.items()}
    g = race_times.read_ghosts(_ghost_data_original(), track)
    ghosts = None
    if g:
        want = (st.get('ghosts') or {}).get('times') or []
        rows = []
        for i, x in enumerate(g['ghosts']):
            o = _ghost_original_time(x['file'])
            rows.append({'driver': x['driver'], 'file': x['file'], 'original': round(o, 3) if o else None,
                         'time': want[i] if i < len(want) and want[i] is not None else (round(o, 3) if o else None),
                         'found': os.path.exists(os.path.join(ghost_dir(), x['file']))})
        ghosts = {'unlock_original': g['unlock'], 'unlock': (st.get('ghosts') or {}).get('unlock') or g['unlock'], 'ghosts': rows}
    return {'relic': relic, 'relic_original': orig, 'ghosts': ghosts, 'custom': bool(st)}


def times_apply(req):
    track = req['track']
    info = times_info(track)
    st = {}
    relic = {}
    for tier, vals in (req.get('relic') or {}).items():
        if tier in race_times.TIERS and vals:
            vals = [round(race_times._clean(v), 3) for v in vals]
            if vals != [round(v, 3) for v in info['relic_original'].get(tier, [])]:
                relic[tier] = vals
    if relic:
        if not info['relic_original']:
            raise RuntimeError('temps des reliques introuvables pour cette piste')
        st['relic'] = relic
    g, gi = req.get('ghosts') or {}, info['ghosts']
    if g and gi:
        out = {}
        if g.get('unlock') is not None and round(race_times._clean(g['unlock']), 3) != gi['unlock_original']:
            out['unlock'] = round(float(g['unlock']), 3)
        times = []
        for row, t in zip(gi['ghosts'], g.get('times') or []):
            t = None if t is None else round(race_times._clean(t), 3)
            times.append(t if t is not None and row['original'] is not None and abs(t - row['original']) > 0.0005 else None)
        if any(t is not None for t in times):
            out['times'] = times
        if out:
            st['ghosts'] = out
    if st:
        json.dump(st, open(times_path(track), 'w', encoding='utf-8'), indent=1)
    elif os.path.exists(times_path(track)):
        os.remove(times_path(track))
    return {**times_info(track), 'report': [('temps modifiés' if st else 'temps du jeu')]}


def times_reset(req):
    if os.path.exists(times_path(req['track'])):
        os.remove(times_path(req['track']))
    return times_info(req['track'])


def _all_ghost_settings():
    """{piste: reglages des fantomes} de toutes les pistes de ce dossier de travail."""
    out = {}
    for f in os.listdir(OUT_DIR) if os.path.isdir(OUT_DIR) else []:
        if f.endswith('_times.json'):
            tr = f[:-len('_times.json')]
            g = times_settings(tr).get('ghosts')
            if g:
                out[tr.lower()] = g
    return out


def times_install_files(track):
    """{nom logique: octets d'origine} a poser dans les archives (zoneinfo, GhostData) ; modifies par _apply_times."""
    st, out = times_settings(track), {}
    if st.get('relic') and _times_source(track) == track:      # piste creee : zoneinfo fait par custom_category
        try:
            out[race_times.zoneinfo_logical(track)] = pak_tool.read_latest(
                ARCHIVES, race_times.zoneinfo_logical(track), race_times.zoneinfo_pak())[0]
        except KeyError:
            pass
    if st.get('ghosts'):
        out[race_times.GHOST_DATA] = _ghost_data_original()
    return out


def _apply_times(reps):
    """Fichiers a ecrire dans une archive : zoneinfo des pistes aux reliques modifiees et GhostData recoivent les
    temps enregistres (pour toutes les pistes : un fichier garde d'une autre piste est refait a l'identique)."""
    out = dict(reps)
    for lg in list(out):
        low = lg.lower()
        if low.endswith('_zoneinfo.igz'):
            tr = low.rsplit('/', 1)[-1][:-len('_zoneinfo.igz')]
            relic = next((times_settings(f[:-len('_times.json')]).get('relic') for f in os.listdir(OUT_DIR)
                          if f.lower() == f'{tr}_times.json'), None) if os.path.isdir(OUT_DIR) else None
            if relic:
                out[lg] = race_times.write_relic(out[lg], relic)
        elif low == race_times.GHOST_DATA.lower():
            # toujours depuis l'original : un reglage retire revient au temps du jeu
            out[lg] = race_times.write_ghosts(_ghost_data_original(), _all_ghost_settings())
    return out


def apply_ghost_files(track, on=True):
    """Enregistrements .igb des fantomes de la piste : temps reglé (on) ou remis d'origine. -> textes du rapport."""
    g = race_times.read_ghosts(_ghost_data_original(), track)
    if not g:
        return []
    want = ((times_settings(track).get('ghosts') or {}).get('times') or []) if on else []
    done = []
    for i, x in enumerate(g['ghosts']):
        p = os.path.join(ghost_dir(), x['file'])
        bak = p + GHOST_BACKUP
        t = want[i] if i < len(want) else None
        if t is not None:
            if not os.path.exists(p):
                continue
            if not os.path.exists(bak):
                shutil.copy2(p, bak)
            open(p, 'wb').write(race_times.igb_with_time(open(bak, 'rb').read(), t))
            done.append(f'fantôme {x["driver"]} : {t:.2f} s')
        elif os.path.exists(bak):
            os.replace(bak, p)
            done.append(f'fantôme {x["driver"]} remis d\'origine')
    return done


def music_export(track):
    """Musiques importees pour un pack de maps : {type: .snd} (le premier fichier de chaque type)."""
    out = {}
    for lg, k in music_streams(track):
        if k not in out and os.path.exists(music_path(track, lg)):
            out[k] = open(music_path(track, lg), 'rb').read()
    return out


def music_import(track, kinds, names):
    """Musiques d'un pack posees sur les fichiers de la piste cible (sans reencodage) ; -> types poses."""
    st, done = music_settings(track), []
    for lg, k in music_streams(track):
        if k in kinds:
            os.makedirs(os.path.dirname(music_path(track, lg)), exist_ok=True)
            open(music_path(track, lg), 'wb').write(music.rebuild_for(_music_original(track, lg), kinds[k]))
            st[k] = {'name': (names.get(k) or {}).get('name') or 'morceau importé'}
            done.append(k)
    if (names.get('fl') or {}).get('mode') == 'continue':
        st['fl'] = {'mode': 'continue'}
    _music_write_settings(track, st)
    return sorted(set(done))


def snapshot_saved(track, label):
    """Copie des fichiers enregistres AVANT une operation qui les modifie (absents notes comme tels)."""
    root = history_dir(track)
    os.makedirs(root, exist_ok=True)
    n = max([int(d) for d in os.listdir(root) if d.isdigit()] + [0]) + 1
    snap = os.path.join(root, f'{n:06d}')
    prev = os.path.join(root, f'{n - 1:06d}')
    prev_t = os.path.getmtime(os.path.join(prev, 'snapshot.json')) if os.path.exists(os.path.join(prev, 'snapshot.json')) else 0
    os.makedirs(os.path.join(snap, 'models'))
    present = {}
    for name, p in _tracked_files(track):
        present[name] = os.path.exists(p)
        if present[name]:
            # modele importe inchange depuis la copie precedente : lien vers elle (les copies ne sont jamais
            # modifiees) au lieu de recopier des dizaines de Mo a chaque enregistrement
            old = os.path.join(prev, name)
            if name.startswith(('models/', 'music_')) and os.path.exists(old) and os.path.getmtime(p) < prev_t \
                    and os.path.getsize(old) == os.path.getsize(p):
                try:
                    os.link(old, os.path.join(snap, name))
                    continue
                except OSError:
                    pass
            shutil.copyfile(p, os.path.join(snap, name))
    json.dump({'label': label, 'files': present}, open(os.path.join(snap, 'snapshot.json'), 'w'), indent=1)
    for old in sorted(d for d in os.listdir(root) if d.isdigit())[:-HISTORY_KEEP]:
        shutil.rmtree(os.path.join(root, old), ignore_errors=True)


def history_list(track):
    root = history_dir(track)
    if not os.path.isdir(root):
        return []
    return [json.load(open(os.path.join(root, d, 'snapshot.json')))['label']
            for d in sorted(x for x in os.listdir(root) if x.isdigit())]


def with_history(track, label, fn):
    """Copie des fichiers enregistres, puis l'operation ; si elle echoue, les fichiers sont remis comme avant
    (rien de a moitie ecrit) et la copie est consommee."""
    progress.step('copie pour « Annuler »')
    snapshot_saved(track, label)
    try:
        return fn()
    except Exception:
        undo_save(track)
        raise


def undo_save(track):
    """Restaure les fichiers enregistres d'avant la derniere operation (puis oublie cette copie)."""
    root = history_dir(track)
    snaps = sorted(d for d in os.listdir(root) if d.isdigit()) if os.path.isdir(root) else []
    if not snaps:
        raise RuntimeError('aucun enregistrement a annuler')
    snap = os.path.join(root, snaps[-1])
    meta = json.load(open(os.path.join(snap, 'snapshot.json')))
    current = dict(_tracked_files(track))
    for name, was in meta['files'].items():
        p = current.get(name) or (os.path.join(OUT_DIR, 'models', name[len('models/'):]) if name.startswith('models/')
                                  else os.path.join(OUT_DIR, name))
        if was:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            shutil.copyfile(os.path.join(snap, name), p)
        elif os.path.exists(p) and not name.startswith('models/'):
            os.remove(p)                       # fichier qui n'existait pas encore (les modeles restent sur le disque)
    shutil.rmtree(snap, ignore_errors=True)
    _visual_cache.clear()
    _model_cache.clear()
    _preview_cache.clear()
    return {'undone': meta['label'], 'remaining': len(snaps) - 1}


# -- modeles importes -------------------------------------------------------------------------
CUSTOM_DIR = 'Levels/Octane/Custom'


def custom_model_path(logical):
    return ci_path(os.path.join(OUT_DIR, 'models'), os.path.basename(logical))


def custom_models(track):
    """{chemin logique: infos} des modeles importes pour la piste."""
    p = os.path.join(OUT_DIR, f'{track}_custom_models.json')
    return json.load(open(p)) if os.path.exists(p) else {}


def save_custom_models(track, reg):
    os.makedirs(OUT_DIR, exist_ok=True)
    json.dump(reg, open(os.path.join(OUT_DIR, f'{track}_custom_models.json'), 'w'), indent=1)


# -- murs invisibles : collision seule ---------------------------------------------------------
# Un mur invisible est un modele importe comme les autres (objet de decor deplacable, copiable, supprimable), dont le
# .igz installe n'est qu'un triangle d'un millimetre (rien a l'ecran) ; sa forme est dans <modele>.wall.json et
# c'est elle qui donne la collision (object_world_array) et l'affichage dans l'editeur. Registre : 'invisible': True.
WALL_SURFACE = 4               # « Sol (défaut) » : surface des murs de Crash Cove, Coco Park, Turbo Track


def wall_mesh_path(logical):
    return custom_model_path(logical)[:-4] + '.wall.json'


def wall_mesh(track, logical):
    """(sommets [[x, y, z]], triangles [[a, b, c]]) en repere local d'un modele mur invisible, sinon None."""
    if not (custom_models(track).get(logical) or {}).get('invisible'):
        return None
    d = json.load(open(wall_mesh_path(logical)))
    return d['pos'], d['tris']


def model_or_wall_mesh(track, logical):
    """(positions a plat, indices) comme decor.model_mesh : celles du mur si le modele est un mur invisible."""
    w = wall_mesh(track, logical)
    if w is None:
        return model_mesh(model_bytes(track, logical))
    return [c for p in w[0] for c in p], [i for t in w[1] for i in t]


def _forget_model(logical):
    for cache in (_visual_cache, _model_cache, _preview_cache):
        cache.pop(logical, None)


def write_wall_model(track, reg, name, pos, tris, **info):
    """Modele mur invisible `name` (sommets locaux, triangles) : .igz point + .wall.json + registre (reg, a
    enregistrer par l'appelant). -> chemin logique."""
    logical = f'models/{CUSTOM_DIR}/{name}.igz'
    os.makedirs(os.path.join(OUT_DIR, 'models'), exist_ok=True)
    dot = [(0.0, 0.0, -20.0), (0.04, 0.0, -20.0), (0.0, 0.04, -20.0)]   # 1 mm, sous le sol : jamais visible
    p, n, u, t = complete_mesh(dot, None, None, [(0, 1, 2)])
    open(custom_model_path(logical), 'wb').write(
        build_model(read_game_file(track, TEMPLATE), p, n, u, t, [(0, 1, 2)], f'{CUSTOM_DIR}/{name}', None))
    json.dump({'pos': [[round(float(c), 3) for c in q] for q in pos], 'tris': [[int(i) for i in x] for x in tris]},
              open(wall_mesh_path(logical), 'w'))
    _forget_model(logical)
    reg[logical] = {'name': name, 'vertices': len(pos), 'triangles': len(tris), 'material': 'gabarit',
                    'invisible': True, **info}
    return logical


def free_model_name(track, want, taken=None):
    """Nom de modele importe libre (registre, fichiers deja sur le disque)."""
    taken = taken if taken is not None else {os.path.basename(k).lower() for k in custom_models(track)}
    name, n = want, 1
    while f'{name}.igz'.lower() in taken or os.path.exists(custom_model_path(f'{name}.igz')):
        n += 1
        name = f'{want}_{n}'
    taken.add(f'{name}.igz'.lower())
    return name


def place_custom_objects(track, art, items):
    """Objets de decor des modeles importes : items = [(nom, chemin logique, position monde, euler, echelle,
    surface)] copies de l'objet modele du fichier ; liens memorises. -> ids des objets (fichier reecrit)."""
    df = DecorFile(base_file(track, art)[0])
    tmpl = template_object(track, art)
    if tmpl is None:
        raise ValueError(f'{os.path.basename(art)} : aucun objet modèle à copier dans ce fichier')
    used, specs = set(df.names.values()), []
    for name, _, pos, euler, scale, _ in items:
        obj_name, k = name, 1
        while obj_name in used:
            k += 1
            obj_name = f'{name}_{k}'
        used.add(obj_name)
        specs.append((tmpl, obj_name, [float(v) for v in pos], [float(v) for v in euler], [float(v) for v in scale]))
    created = df.duplicate_many(specs)
    links = load_links(track)
    for new_id, (_, logical, _, _, _, surface) in zip(created, items):
        df.set_model(new_id, 'models:\\' + CUSTOM_DIR.replace('/', '\\') + f'\\{os.path.basename(logical)[:-4]}.igb')
        links.setdefault(art, {})[str(new_id)] = {'custom': logical, 'surface': surface}
    save_links(track, links)
    idmap = write_art(track, art, df)
    return [idmap[i] for i in created]


def _wall_objects(track, kind=None):
    """[(fichier _Art, objet, lien)] des murs invisibles du decor enregistre (d'un type : 'auto', 'manual', 'obj')."""
    reg = custom_models(track)
    return [(art, o, lk) for art, o, lk in _imported_objects(track)
            if (reg.get(lk['custom']) or {}).get('invisible')
            and (kind is None or (reg.get(lk['custom']) or {}).get('wall', 'obj') == kind)]


def remove_wall_objects(track, kind):
    """Retire les murs invisibles d'un type (objets + modeles). -> nombre d'objets retires."""
    found = _wall_objects(track, kind)
    by_art = defaultdict(list)
    for art, o, _ in found:
        by_art[art].append(o['id'])
    for art, ids in by_art.items():
        df = DecorFile(base_file(track, art)[0])
        df.delete_many(ids)
        write_art(track, art, df)
    reg = custom_models(track)
    used = {lk['custom'] for _, _, lk in _imported_objects(track)}
    for logical in [k for k, v in reg.items() if v.get('invisible') and v.get('wall', 'obj') == kind and k not in used]:
        for p in (custom_model_path(logical), wall_mesh_path(logical)):
            if os.path.exists(p):
                os.remove(p)
        del reg[logical]
        _forget_model(logical)
    save_custom_models(track, reg)
    return len(found)


def walls_auto(req):
    """Murs invisibles le long des bords de la route : req = {track, margin (m), height (m), piece (m),
    sides 'both' | 'left' | 'right', offroad (bool)}. Les murs automatiques precedents sont remplaces ; les murs
    ajoutes a la main ou importes restent (et comptent comme des murs existants)."""
    track = req['track']
    margin, height = float(req.get('margin', 3)) * 39.37, float(req.get('height', 10)) * 39.37
    piece = max(10.0, float(req.get('piece', 50))) * 39.37
    report = []
    progress.step('anciens murs automatiques', 0.0)
    n_old = remove_wall_objects(track, 'auto')
    # sol mesure = collision a jour du decor enregistre, sans les anciens murs automatiques (rien a refaire si elle
    # l'est deja) ; une collision enregistree en retard sur le decor faisait voir du vide partout
    with progress.span(0.02, 0.3):
        sync_collision(track)
    if n_old:
        report.append(f'{n_old} ancien(s) mur(s) automatique(s) remplacé(s)')
    progress.step('bords de la route', 0.3)
    loop, _ = race_path_points(track)
    if len(loop) < 4:
        raise ValueError('pas de parcours : crée d\'abord le parcours (mode Course)')
    pieces = walls.generate(ground_for(track), loop, road_ground(track), margin=margin, piece=piece,
                            sides=req.get('sides', 'both'), offroad=bool(req.get('offroad')))
    if not pieces:
        report.append('aucun bord à fermer (pas de vide au bord de la route'
                      + ('' if req.get('offroad') else ' ; « hors route » non coché') + ')')
        return {'report': report, 'ids': [], 'file': main_art(track)}
    progress.step('murs', 0.55)
    reg = custom_models(track)
    taken = {os.path.basename(k).lower() for k in reg}
    batch = f"murs invisibles automatiques — {time.strftime('%d/%m %H:%M')}"
    items = []
    for k, pc in enumerate(pieces):
        P = np.asarray(pc['points'], np.float64)
        pivot = [float((P[:, 0].min() + P[:, 0].max()) / 2), float((P[:, 1].min() + P[:, 1].max()) / 2), float(P[:, 2].min())]
        pos, tris = walls.ribbon((P - pivot).tolist(), height)
        name = free_model_name(track, f'MurInvisible_{k + 1:03d}', taken)
        logical = write_wall_model(track, reg, name, pos, tris, wall='auto', **{'import': batch})
        items.append((name, logical, pivot, [0.0, 0.0, 0.0], [1.0, 1.0, 1.0], WALL_SURFACE))
    save_custom_models(track, reg)
    art = main_art(track)
    ids = place_custom_objects(track, art, items)
    length = sum(float(np.linalg.norm(np.diff(np.asarray(pc['points'])[:, :2], axis=0), axis=1).sum()) for pc in pieces)
    n_void = sum(pc['reason'] == 'void' for pc in pieces)
    report.append(f'{len(pieces)} mur(s) invisible(s) : {length / 39.37:.0f} m, hauteur {height / 39.37:.0f} m, à '
                  f'{margin / 39.37:.1f} m du bord ({n_void} au bord d\'un vide, {len(pieces) - n_void} hors route)')
    with progress.span(0.6, 1.0):
        report.append(defer_collision(track))
    return {'report': report, 'ids': ids, 'file': art}


JOIN_DEFAULT = 120                                      # m : bouts de murs de zone relies (poteaux de barriere 40-110 m)


def walls_zone(req):
    """Murs invisibles le long des bords des objets du decor choisis : req = {track, objects: [{file, id}],
    margin (m), height (m), piece (m), offroad (bool), join (m : bouts relies, 0 = non)}. Jamais dans la bande de la route (si le parcours existe).
    Les murs d'une precedente generation sur exactement les memes objets sont remplaces."""
    track = req['track']
    margin, height = float(req.get('margin', 1)) * 39.37, float(req.get('height', 10)) * 39.37
    piece = max(10.0, float(req.get('piece', 50))) * 39.37
    reg = custom_models(track)
    chosen, names = [], []
    for ref in req.get('objects') or []:
        o = next((x for x in DecorFile(base_file(track, ref['file'])[0]).objects() if x['id'] == int(ref['id'])), None)
        if o is None:
            raise ValueError(f"objet introuvable (id {ref['id']}) : enregistre le décor puis recommence")
        if (reg.get(model_logical_path(o['model'])) or {}).get('invisible'):
            continue                                    # les murs invisibles choisis avec le reste sont ignores
        chosen.append(o)
        names.append(f"{ref['file']}|{o['name']}")
    if not chosen:
        raise ValueError('choisis d\'abord un ou plusieurs objets du décor (pas des murs invisibles)')
    key = '\n'.join(sorted(names))
    report = []
    progress.step('anciens murs de cette zone', 0.0)
    old = [(art, o) for art, o, lk in _wall_objects(track, 'zone') if (reg.get(lk['custom']) or {}).get('zone') == key]
    if old:
        by_art = defaultdict(list)
        for art, o in old:
            by_art[art].append(o['id'])
        for art, ids in by_art.items():
            df = DecorFile(base_file(track, art)[0])
            df.delete_many(ids)
            write_art(track, art, df)
        report.append(f'{len(old)} mur(s) de la génération précédente sur ces objets remplacé(s)')
    with progress.span(0.02, 0.3):
        sync_collision(track)                           # sol a jour, sans les murs remplaces
    progress.step('bords des objets choisis', 0.3)
    ground = ground_for(track)
    loop, _ = race_path_points(track)
    corridor = walls.Corridor(ground, loop, road_ground(track)) if len(loop) >= 4 else None
    tris = np.concatenate([object_world_array(track, o) for o in chosen])
    pieces = walls.zone(ground, tris, corridor, margin=margin, piece=piece, offroad=bool(req.get('offroad')), height=height,
                        join=max(0.0, float(req.get('join', JOIN_DEFAULT))) * 39.37)
    if corridor is None:
        report.append('pas encore de parcours : la route n\'a pas pu être évitée')
    if not pieces:
        report.append('aucun bord à fermer sur ces objets (pas de vide au bord'
                      + ('' if req.get('offroad') else ' ; « vers le sol non choisi » non coché') + ', ou bords sur la route)')
        return {'report': report, 'ids': [], 'file': main_art(track)}
    progress.step('murs', 0.6)
    taken = {os.path.basename(k).lower() for k in reg}
    batch = f"murs invisibles autour de {chosen[0]['name']}{f' (+{len(chosen) - 1})' if len(chosen) > 1 else ''} — {time.strftime('%d/%m %H:%M')}"
    items = []
    for k, pc in enumerate(pieces):
        P = np.asarray(pc['points'], np.float64)
        pivot = [float((P[:, 0].min() + P[:, 0].max()) / 2), float((P[:, 1].min() + P[:, 1].max()) / 2), float(P[:, 2].min())]
        pos, tris_ = walls.ribbon((P - pivot).tolist(), height)
        name = free_model_name(track, f'MurZone_{k + 1:03d}', taken)
        logical = write_wall_model(track, reg, name, pos, tris_, wall='zone', zone=key, **{'import': batch})
        items.append((name, logical, pivot, [0.0, 0.0, 0.0], [1.0, 1.0, 1.0], WALL_SURFACE))
    save_custom_models(track, reg)
    art = main_art(track)
    ids = place_custom_objects(track, art, items)
    length = sum(float(np.linalg.norm(np.diff(np.asarray(pc['points'])[:, :2], axis=0), axis=1).sum()) for pc in pieces)
    n_void = sum(pc['reason'] == 'void' for pc in pieces)
    report.append(f'{len(pieces)} mur(s) invisible(s) autour de {len(chosen)} objet(s) : {length / 39.37:.0f} m, hauteur '
                  f'{height / 39.37:.0f} m ({n_void} au bord d\'un vide, {len(pieces) - n_void} vers un autre sol)')
    with progress.span(0.65, 1.0):
        report.append(defer_collision(track))
    return {'report': report, 'ids': ids, 'file': art}


def wall_add(req):
    """Un mur invisible droit : req = {track, pos [x, y, z sol], yaw (rad), length (m), height (m)}."""
    track = req['track']
    length, height = float(req.get('length', 20)) * 39.37, float(req.get('height', 10)) * 39.37
    pos = [float(v) for v in req.get('pos') or [0, 0, 0]]
    if pos[2] < KILL_Z + 1000:
        pos[2] = 0.0
    reg = custom_models(track)
    name = free_model_name(track, 'MurInvisible_main')
    p, t = walls.straight(length, height)
    logical = write_wall_model(track, reg, name, p, t, wall='manual', **{'import': f"mur invisible — {time.strftime('%d/%m %H:%M')}"})
    save_custom_models(track, reg)
    art = main_art(track)
    ids = place_custom_objects(track, art, [(name, logical, pos, [0.0, 0.0, float(req.get('yaw') or 0.0)],
                                             [1.0, 1.0, 1.0], WALL_SURFACE)])
    return {'ids': ids, 'file': art, 'report': [f'{name} : {length / 39.37:.0f} × {height / 39.37:.0f} m', defer_collision(track)]}


def set_invisible(req, sync=True):
    """Modele importe <-> mur invisible : req = {track, model (chemin du decor ou logique), invisible (bool)}.
    Tous les objets de ce modele changent. Rendu invisible : le .igz visible est garde a cote (<nom>.visible.igz)
    pour le retour ; un mur cree invisible redevient visible avec la texture du gabarit (UV projetees)."""
    track = req['track']
    logical = model_logical_path(req['model']) if not req['model'].startswith('models/') else req['model']
    reg = custom_models(track)
    info = reg.get(logical)
    if info is None:
        raise ValueError('seulement pour les modèles importés')
    p = custom_model_path(logical)
    keep = p[:-4] + '.visible.igz'
    name = os.path.basename(logical)[:-4]
    if req.get('invisible'):
        if info.get('invisible'):
            return {'report': [f'{name} est déjà un mur invisible']}
        pos, idx = model_mesh(open(p, 'rb').read())
        P = [pos[i:i + 3] for i in range(0, len(pos), 3)]
        T = [idx[i:i + 3] for i in range(0, len(idx) // 3 * 3, 3)]
        shutil.copyfile(p, keep)
        material = info.get('material')
        new = write_wall_model(track, reg, name, P, T, wall=info.get('wall', 'obj'), visible_material=material,
                               **{k: v for k, v in info.items() if k in ('import', 'obj_object', 'obj_material')})
        assert new == logical
        # sans collision, un mur invisible ne sert a rien : collision par defaut des murs
        links = load_links(track)
        for art_links in links.values():
            for lk in art_links.values():
                if isinstance(lk, dict) and lk.get('custom') == logical and lk.get('surface') == 'none':
                    lk['surface'] = WALL_SURFACE
        save_links(track, links)
        msg = f'{name} : mur invisible (collision seule, rien n\'est affiché en jeu)'
    else:
        if not info.get('invisible'):
            return {'report': [f'{name} est déjà visible']}
        if os.path.exists(keep):
            shutil.copyfile(keep, p)
        else:
            pos, tris = wall_mesh(track, logical)
            catalog = {m['id']: m for m in material_catalog(track)}
            m = catalog.get(info.get('visible_material'))
            q, n, u, t = complete_mesh([tuple(v) for v in pos], None, None, [tuple(x) for x in tris])
            open(p, 'wb').write(build_model(read_game_file(track, TEMPLATE), q, n, u, t, [tuple(x) for x in tris],
                                            f'{CUSTOM_DIR}/{name}', (m['name'], m['ns'], m['dep']) if m else None))
        info.pop('invisible', None)
        info['material'] = info.pop('visible_material', None) or info.get('material') or 'gabarit'
        msg = f'{name} : de nouveau visible en jeu'
    _forget_model(logical)
    save_custom_models(track, reg)
    return {'report': [msg, defer_collision(track)] if sync else [msg]}


def model_bytes(track, logical):
    """Modele : importe (out/editor/models) sinon archives."""
    p = custom_model_path(logical)
    if os.path.exists(p) and logical.startswith(f'models/{CUSTOM_DIR}/'):
        return open(p, 'rb').read()
    return read_game_file(track, logical)


def read_game_file(track, logical, prefer=()):
    """Fichier du jeu : archives communes / de la piste, sinon celle d'une autre piste (objets de la bibliotheque)."""
    try:
        return pak_tool.read_latest(ARCHIVES, logical, track_pak(track))[0]
    except KeyError:
        pak = library.find_pak(ARCHIVES, logical, prefer)
        if pak is None:
            raise
        return pak_tool.read_latest(ARCHIVES, logical, pak)[0]


_material_cache = {}


def material_catalog(track):
    """Materiaux utilisables pour un modele importe : ceux des draw calls des modeles du manifeste de la piste
    qui ont exactement le format de sommet du gabarit, et dont le fichier materialinstances est aussi liste
    (donc deja charge par le jeu). Les materiaux propres a la piste d'abord."""
    if track not in _material_cache:
        tp = track_pak(track)
        rows = pkg_manifest.entries(pak_tool.read_latest(ARCHIVES, pkg_manifest.manifest_logical(track), tp)[0])
        listed = {p.rsplit('/', 1)[-1] for t, p in rows if t == 'material_instances'}
        ref = model_materials(read_game_file(track, TEMPLATE))[0][4]
        found = {}
        for t, p in rows:
            if t != 'model' or not p.endswith('.igz'):
                continue
            try:
                mats = model_materials(pak_tool.read_latest(ARCHIVES, p, tp)[0])
            except Exception:  # noqa: BLE001 - modele absent ou illisible : ignore
                continue
            for _, name, ns, dep, sig, _ in mats:
                if sig == ref and dep and ns.lower() + '.igz' in listed:
                    found.setdefault(f'{name}|{ns}', {'id': f'{name}|{ns}', 'name': name, 'ns': ns, 'dep': dep,
                                                      'model': p.rsplit('/', 1)[-1][:-4]})
        prefix = track.split('_')[0].lower()
        for m in found.values():
            m['label'] = f"{m['name']} · {m['model']}"
        _material_cache[track] = sorted(found.values(), key=lambda m: (not m['ns'].lower().startswith(prefix),
                                                                         m['model'], m['name']))
    return custom_material_entries(track) + _material_cache[track]


# -- textures importees (image -> texture BC1 + materiau clone de la roche du gabarit) ----------
TEX_TEMPLATE_COLOR = 'textures/ColorMap,textures@!levels!Octane!T111_Crash_Cove!T111_rockgroundside!T111_rockgroundside_C`tga,111.igz'
TEX_TEMPLATE_NORMAL = 'textures/NormalMap,textures@!levels!Octane!T111_Crash_Cove!T111_rockgroundside!T111_rockgroundside_N`tga,111.igz'
MAT_TEMPLATE = 'materialinstances/octane/t111_crash_cove/t111_props_materials,t111_rockgroundside_b,00020.igz'
FLAT_NORMAL_NS = 'NormalMap,textures@!custom!flat_N`png,111'
# images avec transparence : texture BC3 1024 + mipmaps, materiau des feuilles d'arbre de Crash Cove (identique a la
# roche, sauf CAlphaClipBundle._enable = vrai, seuil 0,5, et l'echantillonnage)
TEX_TEMPLATE_ALPHA = 'textures/colormap,textures@!levels!crash1!jungle!c1_dirt01_c`tga,111.igz'
# « Alleger la map » : textures 512 x 512 (4 fois moins de memoire), gabarits du jeu de cette taille (BC1 / BC3)
TEX_TEMPLATES_512 = {False: 'textures/ColorMap,textures@!levels!Crash1!village!C1_WoodSolid01_C`tga,111.igz',
                     True: 'textures/ColorMap,textures@!levels!Crash1!village!C1_WoodSolid02_C`tga,111.igz'}
TEXTURE_SIZES = (1024, 512)
MAT_TEMPLATE_ALPHA = 'materialinstances/Levels/Crash1/L101_NSanityBeach_materials,T111_VinesLeaf01,0000000002.igz'


def custom_textures_path(track):
    return os.path.join(OUT_DIR, f'{track}_custom_textures.json')


def custom_textures(track):
    p = custom_textures_path(track)
    return json.load(open(p)) if os.path.exists(p) else {}


def custom_file_path(logical):
    """Fichiers de texture / materiau importes : out/editor/textures/<nom de fichier>."""
    return ci_path(os.path.join(OUT_DIR, 'textures'), os.path.basename(logical))


def custom_material_entries(track):
    """Entrees du catalogue pour les textures importees."""
    out = []
    for name, info in custom_textures(track).items():
        out.append({'id': info['material_id'], 'name': info['material_name'], 'ns': info['ns'], 'dep': info['dep'],
                    'model': f'image {name}', 'label': f'Image : {name}', 'custom_texture': name})
    return out


def import_texture(req):
    """req = {track, name, image (data URL ou base64 d'un PNG/JPG...)}. Cree la texture couleur (BC1 1024^2),
    la carte de normales plate (partagee) et un materiau « Standard » clone de la roche du gabarit."""
    import base64
    return create_texture(req['track'], req.get('name'), base64.b64decode(req['image'].split(',', 1)[-1]))


def create_texture(track, name, image, source=None, alpha=None, size=1024):
    """Image (octets PNG/JPG...) -> texture + materiau importes (voir import_texture). source : fichier d'origine
    (chemin, taille, date) ; une image deja importee depuis le meme fichier est reutilisee. alpha : transparence
    (decoupe) forcee, sinon detectee (image_has_alpha). size : 1024 ou 512 (alleger)."""
    reg = custom_textures(track)
    alpha = texture_build.image_has_alpha(image) if alpha is None else bool(alpha)
    size = int(size or 1024)
    if source:
        hit = next((n for n, i in reg.items() if i.get('source') == source), None)
        if hit and bool(reg[hit].get('alpha')) == alpha and reg[hit].get('size', 1024) == size:
            return {'name': hit, 'id': reg[hit]['material_id'], 'label': f'Image : {hit}', 'reused': True}
        if hit:                       # autre transparence / taille : refaite sur place (memes noms)
            _write_texture_files(track, hit, image, alpha, size)
            reg[hit].update(alpha=alpha, size=size)
            json.dump(reg, open(custom_textures_path(track), 'w'), indent=1)
            return {'name': hit, 'id': reg[hit]['material_id'], 'label': f'Image : {hit}', 'reused': True, 'upgraded': True}
    name = _clean_name(name, 'Texture')
    base, n = name, 1
    while name in reg:
        n += 1
        name = f'{base}_{n}'
    files, mat_name, mat_ns, mat_dep = _write_texture_files(track, name, image, alpha, size)
    reg[name] = {'material_id': f'{mat_name}|{mat_ns}', 'material_name': mat_name, 'ns': mat_ns, 'dep': mat_dep,
                 'files': files, 'alpha': alpha, 'size': size}
    if source:
        reg[name]['source'] = source
    os.makedirs(OUT_DIR, exist_ok=True)
    json.dump(reg, open(custom_textures_path(track), 'w'), indent=1)
    return {'name': name, 'id': reg[name]['material_id'], 'label': f'Image : {name}'}


def _write_texture_files(track, name, image, alpha, size=1024):
    """Fichiers d'une image importee : texture couleur (BC1 opaque, ou BC3 + mipmaps si l'image a de la
    transparence ; size x size), normales plates partagees, materiau clone (roche ; feuilles a decoupe alpha si
    transparence, renomme comme la roche : les modeles qui l'utilisent n'ont pas a changer).
    -> (fichiers, nom du materiau, espace, dependance)."""
    tp = track_pak(track)
    color_ns = f'ColorMap,textures@!custom!{name}_C`png,111'
    color_logical, normal_logical = f'textures/{color_ns}.igz', f'textures/{FLAT_NORMAL_NS}.igz'
    mat_ns = f'Custom_materials,{name},1'
    mat_logical, mat_dep = f'materialinstances/Custom/{mat_ns}.igz', f'materials:/Custom/{mat_ns}.igz'
    os.makedirs(os.path.join(OUT_DIR, 'textures'), exist_ok=True)
    tmpl_mat = read_game_file(track, MAT_TEMPLATE_ALPHA if alpha else MAT_TEMPLATE)
    if int(size) == 512:
        tex_tmpl = _logical_case(track, TEX_TEMPLATES_512[bool(alpha)])
    else:
        tex_tmpl = _logical_case(track, TEX_TEMPLATE_ALPHA) if alpha else TEX_TEMPLATE_COLOR
    old = {ns.split(',')[0]: ns for n_, ns in IgzFile(tmpl_mat).ext_names if n_ == 'image'}
    open(custom_file_path(color_logical), 'wb').write(texture_build.build_color_texture(
        read_game_file(track, tex_tmpl), image, f'_{name}_C'))
    if not os.path.exists(custom_file_path(normal_logical)):
        open(custom_file_path(normal_logical), 'wb').write(texture_build.build_flat_normal(
            read_game_file(track, TEX_TEMPLATE_NORMAL)))
    mat_name, mat = _texture_material(track, color_ns, alpha)
    if (custom_textures(track).get(name) or {}).get('glow'):   # refaite (transparence, taille) : reste lumineuse
        mat = texture_build.set_emissive(mat, True, color_ns)
    open(custom_file_path(mat_logical), 'wb').write(mat)
    for cache in (_texture_png_cache, _preview_cache):
        cache.clear()
    return ({'texture': [color_logical, normal_logical], 'material_instances': [mat_logical]}, mat_name, mat_ns, mat_dep)


def _texture_material(track, color_ns, alpha):
    """Materiau d'une image importee : roche du gabarit (feuilles a decoupe alpha si transparence) visant la
    texture couleur color_ns et les normales plates. -> (nom du materiau, octets)."""
    tmpl_mat = read_game_file(track, MAT_TEMPLATE_ALPHA if alpha else MAT_TEMPLATE)
    old = {ns.split(',')[0]: ns for n_, ns in IgzFile(tmpl_mat).ext_names if n_ == 'image'}
    mat_name = model_materials(read_game_file(track, TEMPLATE))[0][1]       # 'rockGroundSide'
    mat = texture_build.retarget_material(tmpl_mat, {old['ColorMap']: color_ns, old['NormalMap']: FLAT_NORMAL_NS})
    if alpha:                                          # meme nom que le materiau roche (handle des modeles)
        from igz import fnv1a_lower
        z = IgzFile(mat)
        entries = z._name_entries()
        entries[0] = (mat_name, fnv1a_lower(mat_name))
        z._write_names(entries)
        mat = z.to_bytes()
    return mat_name, mat


def alpha_texture_list(track):
    """Textures importees depuis un fichier image : [{name, file, alpha (actuel), detected (decoupe detectee)}]."""
    out = []
    for name, info in custom_textures(track).items():
        src = info.get('source') or []
        if not src or not isinstance(src[0], str) or not os.path.isfile(src[0]):
            continue
        out.append({'name': name, 'file': os.path.basename(src[0]), 'alpha': bool(info.get('alpha')),
                    'detected': texture_build.image_has_alpha(open(src[0], 'rb').read())})
    return {'textures': sorted(out, key=lambda t: (not t['detected'], t['name'].lower()))}


def set_alpha_textures(track, wanted):
    """Transparence (decoupe) activee / desactivee pour des textures importees : refaites sur place, memes noms
    (aucun modele a re-importer). wanted = {nom: bool}. -> rapport."""
    reg = custom_textures(track)
    on, off = [], []
    for name, want in (wanted or {}).items():
        info = reg.get(name)
        src = (info or {}).get('source') or []
        if not info or bool(info.get('alpha')) == bool(want) or not src or not os.path.isfile(src[0]):
            continue
        _write_texture_files(track, name, open(src[0], 'rb').read(), bool(want), info.get('size', 1024))
        info['alpha'] = bool(want)
        (on if want else off).append(name)
    if on or off:
        json.dump(reg, open(custom_textures_path(track), 'w'), indent=1)
    return {'report': [f'transparence activée sur {len(on)} texture(s), retirée sur {len(off)}'
                       + (f' ({", ".join((on + off)[:10])}{"…" if len(on + off) > 10 else ""})' if on or off else '')]}


# Types de sol (valeur des triangles de collision) : position dans la liste CCollisionMaterialHandleList de
# LooseData/CollisionMaterials.igz + 3 (0 = non defini). Verifie sur les pistes du jeu : Crash Cove 38 = route en
# sable, 13 = pont en bois, 16 = mer (reapparition), 22 = plaques turbo ; Blizzard Bluff 8 = neige, 10 = glace.
# « palette » = present dans la palette de materiaux de la collision de Crash Cove (sur) ; les autres sont a tester.
# Ralentissement : CCollisionMaterialSurfaceInfo._speedMultiplier (Grass 0,4, DirtSlowSlower 0,34 ; Dirt et SandWet
# 1,0 : verifie en jeu, ils ne ralentissent pas) ; affiche dans le menu d'apres le fichier du jeu (surface_params).
SURFACES = [
    (38, 'Sable', True), (40, 'Sable mouillé', True), (4, 'Sol (défaut)', True),
    (5, 'Herbe', True), (53, 'Terre lente', False), (6, 'Roche', True), (13, 'Bois', True),
    (11, 'Eau peu profonde', True), (12, 'Eau profonde', True), (39, 'Verre', True),
    # 22 « Turbo » retire du menu (2026-11-10) : sans effet en jeu (l'accélération vient du script des plaques)
    (16, 'Réapparition (on y tombe)', True), (7, 'Terre', False), (46, 'Asphalte', False), (29, 'Sable sombre', False),
    (8, 'Neige', False), (10, 'Glace', False), (18, 'Boue', False), (9, 'Métal', False),
    # « AlwaysFloor » (_alwaysActAsFloor) : une paroi raide compte comme du sol, pas comme un mur (tuyaux de Sewer
    # Speedway, Deep Sea Driving, Hyper Spaceway : jusqu'a ~90 deg). Jamais a l'envers dans le jeu : boucle non validee.
    # Menu allege a la demande de l'utilisateur : seul le metal (42) est propose ; 41 roche, 43 eau, 50 neige, 35 bois
    # mouille sont les autres parois roulables du jeu.
    (42, 'Driving wall', False)]
_surface_params = {}
SURFACE_OBSERVED = {5: {'speed': 0.4}}   # constate en jeu, absent de la fiche (herbe : ralentissement du hors-piste)


def surface_params():
    """{valeur: {'speed', 'traction'}} lus dans LooseData/CollisionMaterials.igz (materiau -> fiche de surface)."""
    if not _surface_params:
        z = IgzFile(pak_tool.read_latest(ARCHIVES, 'LooseData/CollisionMaterials.igz', 'permanent.pak')[0])
        roots = {n: o for n, o in z.root_objects() if n}
        hl = next(o for o, t in z.objects.items() if t == 'CCollisionMaterialHandleList')
        items = z.dump_object(hl)['@items']
        names = [str(it.get('@handle')).split('::')[-1] if isinstance(it, dict) else None for it in items]
        # valeur = rang dans la liste + decalage, cale sur Sand = 38 (valide en jeu) : la lecture de la liste peut
        # compter ou non une entree nulle en tete (un decalage fixe a fait afficher les fiches du sol voisin)
        off = 38 - names.index('Sand') if 'Sand' in names else 4
        for idx, item in enumerate(items):
            o = roots.get(names[idx]) if names[idx] else None
            if o is None or z.objects.get(o) != 'CCollisionMaterial':
                continue
            m = z.dump_object(o)
            si = m.get('_surfaceInfo')
            sn = si['@handle'].split('::')[-1] if isinstance(si, dict) and '@handle' in si else None
            s = z.dump_object(roots[sn]) if sn in roots else {}
            if s:
                # adherence : traction de la fiche, ou frottement du materiau (glace 0,05 contre 0,5 partout ailleurs)
                fr = m.get('_dynamicFriction')
                grip = min(v for v in (s.get('_traction'), fr / 0.5 if isinstance(fr, (int, float)) else None, 1.0)
                           if isinstance(v, (int, float)))
                _surface_params[idx + off] = {'speed': s.get('_speedMultiplier'), 'traction': round(grip, 3),
                                              'floor': bool((s.get('_surfaceFlags') or 0) & 0x800)}   # _alwaysActAsFloor
        for v, p in SURFACE_OBSERVED.items():
            if v in _surface_params and (_surface_params[v].get('speed') or 1.0) >= 0.99:
                _surface_params[v] = {**_surface_params[v], **p}
    return _surface_params


# -- types de sol a vitesse / glissade propres (collision_materials) ---------------------------------------------
# Registre commun a toutes les pistes (le fichier du jeu est commun) : [{base, speed, slide}], valeur de surface =
# 1re valeur libre du jeu + rang. Une entree n'est jamais retiree (une piste installee peut encore s'en servir).
def custom_surfaces_path():
    return os.path.join(OUT_DIR, 'custom_surfaces.json')


def custom_surfaces():
    p = custom_surfaces_path()
    return json.load(open(p)) if os.path.exists(p) else []


_first_custom = []


def first_custom_surface():
    if not _first_custom:
        _first_custom.append(collision_materials.first_value(
            pak_tool.read_latest(ARCHIVES, collision_materials.LOGICAL, collision_materials.PAK)[0]))
    return _first_custom[0]


def surface_defaults(value):
    """{'speed', 'slide'} d'un type de sol du jeu (vitesse constatee en jeu pour l'herbe)."""
    p = surface_params().get(int(value)) or {}
    b = collision_materials.base_params(pak_tool.read_latest(ARCHIVES, collision_materials.LOGICAL,
                                                             collision_materials.PAK)[0], int(value)) or {'speed': 1.0, 'slide': 0.0}
    return {'speed': round(float(p.get('speed') or b['speed']), 3), 'slide': b['slide']}


def clean_phys(base, phys):
    """Reglages propres d'un objet, ou None s'ils sont ceux du type de sol (rien a ajouter)."""
    if not isinstance(phys, dict) or base in ('auto', 'none', None):
        return phys if isinstance(phys, dict) and base == 'auto' else None
    d = surface_defaults(base)
    sp = round(max(0.05, min(3.0, float(phys.get('speed', d['speed'])))), 3)
    sl = round(max(0.0, min(1.0, float(phys.get('slide', d['slide'])))), 3)
    return None if abs(sp - d['speed']) < 1e-3 and abs(sl - d['slide']) < 1e-3 else {'speed': sp, 'slide': sl}


def custom_surface_value(base, phys):
    """Valeur de surface a ecrire dans la collision : celle du type de sol, ou celle du type ajoute pour ses
    reglages propres (ajoute au registre si nouveau)."""
    phys = clean_phys(int(base), phys)
    if not phys:
        return int(base)
    reg = custom_surfaces()
    want = {'base': int(base), 'speed': phys['speed'], 'slide': phys['slide']}
    for k, c in enumerate(reg):
        if c == want:
            return first_custom_surface() + k
    reg.append(want)
    os.makedirs(OUT_DIR, exist_ok=True)
    json.dump(reg, open(custom_surfaces_path(), 'w'), indent=1)
    return first_custom_surface() + len(reg) - 1


def _apply_custom_surfaces(reps):
    """CollisionMaterials ecrit dans une archive : depuis l'original, avec TOUS les types ajoutes (fichier commun)."""
    out = dict(reps)
    for lg in list(out):
        if lg.lower() == collision_materials.LOGICAL.lower() and custom_surfaces():
            orig = pak_tool.read_latest(ARCHIVES, collision_materials.LOGICAL, collision_materials.PAK)[0]
            out[lg] = collision_materials.build(orig, custom_surfaces())
    return out


def set_surface(req, sync=True):
    """Type de sol des objets importes : req = {track, objects: [{file, id}], surface: 'auto' | 'none' | valeur,
    phys: {speed, slide} | None (vitesse / glissade propres ; absent : reglages gardes)}.
    Memorise dans les liens du decor, puis collision recalculee (sync=False : par l'enregistrement du decor)."""
    track, surf = req['track'], req.get('surface')
    if surf not in ('auto', 'none'):
        surf = int(surf)
        if surf not in {s for s, _, _ in SURFACES}:
            raise ValueError(f'type de sol inconnu : {surf}')
    links, n = load_links(track), 0
    for ref in req.get('objects') or []:
        lk = links.get(ref['file'], {}).get(str(ref['id']))
        if isinstance(lk, dict) and 'custom' in lk:
            lk['surface'] = surf
            if 'phys' in req:                              # reglages propres choisis (ou remis a ceux du type)
                ph = clean_phys(surf, req.get('phys'))
                if ph:
                    lk['phys'] = ph
                else:
                    lk.pop('phys', None)
            elif surf == 'none':
                lk.pop('phys', None)
            n += 1
    if not n:
        raise ValueError('aucun modèle importé dans la sélection (le sol des objets d\'origine ne se change pas ici)')
    save_links(track, links)
    label = {'auto': 'comme le sol dessous', 'none': 'sans collision'}.get(surf) or next(l for s, l, _ in SURFACES if s == surf)
    if not sync:
        return {'report': [f'{n} objet(s) : {label}'], 'surface': surf}
    with progress.span(0.05, 1.0):
        rep = defer_collision(track)
    return {'report': [f'{n} objet(s) : {label}', rep], 'surface': surf}


def set_object_alpha(req):
    """Transparence (decoupe) de la texture d'un modele importe : req = {track, model, alpha}."""
    track = req['track']
    logical = req['model'] if req['model'].startswith('models/') else model_logical_path(req['model'])
    mat = (custom_models(track).get(logical) or {}).get('material')
    name = next((n for n, i in custom_textures(track).items() if i['material_id'] == mat), None)
    if name is None:
        raise ValueError('ce modèle n\'utilise pas une image importée (texture du jeu : transparence non modifiable)')
    return set_alpha_textures(track, {name: bool(req.get('alpha'))})


def set_object_glow(req):
    """Texture lumineuse (emission, comme les lampes du jeu) d'un modele importe : req = {track, model, glow}. Le
    materiau de l'image importee est refait sur place : tous les modeles qui utilisent cette image brillent."""
    track = req['track']
    logical = req['model'] if req['model'].startswith('models/') else model_logical_path(req['model'])
    mat = (custom_models(track).get(logical) or {}).get('material')
    reg = custom_textures(track)
    name = next((n for n, i in reg.items() if i['material_id'] == mat), None)
    if name is None:
        raise ValueError('ce modèle n\'utilise pas une image importée (texture du jeu : non modifiable)')
    info, on = reg[name], bool(req.get('glow'))
    mat_logical = info['files']['material_instances'][0]
    color_ns = info['files']['texture'][0][len('textures/'):-len('.igz')]
    p = custom_file_path(mat_logical)
    if os.path.exists(p) and os.path.getsize(p):
        data = open(p, 'rb').read()                    # lu AVANT d'ouvrir en ecriture (qui vide le fichier)
    else:                                              # absent ou vide (ancienne erreur) : refait comme a l'import
        data = _texture_material(track, color_ns, bool(info.get('alpha')))[1]
    data = texture_build.set_emissive(data, on, color_ns)
    open(p, 'wb').write(data)
    if on:
        info['glow'] = True
    else:
        info.pop('glow', None)
    json.dump(reg, open(custom_textures_path(track), 'w'), indent=1)
    users = sum(1 for i in custom_models(track).values() if i.get('material') == mat)
    return {'report': [f'image « {name} » ' + ('lumineuse' if on else 'non lumineuse')
                       + f' ({users} modèle(s) l\'utilisent)'], 'texture': name}


def set_custom_material(req):
    """Change la texture (materiau) d'un modele importe : req = {track, model ('models:\\...igb' ou chemin
    logique), material (id du catalogue)}. Toutes les copies de ce modele changent (meme fichier)."""
    track = req['track']
    logical = req['model'] if req['model'].startswith('models/') else model_logical_path(req['model'])
    if not logical.startswith(f'models/{CUSTOM_DIR}/') or not os.path.exists(custom_model_path(logical)):
        raise ValueError('seuls les modeles importes peuvent changer de texture')
    m = next((m for m in material_catalog(track) if m['id'] == req['material']), None)
    if m is None:
        raise ValueError(f"materiau inconnu : {req['material']}")
    z = IgzFile(open(custom_model_path(logical), 'rb').read())
    set_material(z, m['name'], m['ns'], m['dep'])
    open(custom_model_path(logical), 'wb').write(z.to_bytes())
    _model_cache.pop(logical, None)
    _preview_cache.pop(logical, None)
    reg = custom_models(track)
    if logical in reg:
        reg[logical]['material'] = m['id']
        save_custom_models(track, reg)
    return {'model': logical, 'material': m['id'], 'label': m['label']}


# -- edition de forme d'un objet du decor (2026-11-06) : points deplaces, texture par face ------------------------
# L'objet modifie recoit un NOUVEAU modele importe, a plusieurs textures (model_build.build_model_multi : un draw call
# par texture), au format de sommet du gabarit. Objets du jeu compris : l'objet d'origine est remplace par une copie
# importee (sa collision suit alors la nouvelle forme, surface « comme le sol dessous »).
def model_parts(track, file_name):
    """Textures (draw calls) d'un modele, dans l'ordre des groupes de l'apercu : [{material (id du catalogue ou
    nom|espace), label, compatible (format de sommet du gabarit : reutilisable tel quel)}]."""
    logical = model_logical_path(file_name)
    data = model_bytes(track, logical)
    ref = model_materials(read_game_file(track, TEMPLATE))[0][4]
    catalog = material_catalog(track)
    by = {(m['name'], m['ns']): m for m in catalog}
    out = []
    for _, name, ns, dep, sig, _ in model_materials(data):
        m = by.get((name, ns))
        out.append({'material': m['id'] if m else f'{name}|{ns}', 'label': m['label'] if m else name,
                    'compatible': sig == ref and bool(dep), 'name': name, 'ns': ns, 'dep': dep})
    return {'model': logical, 'parts': out}


def _part_material(track, mid, originals):
    """(nom, espace, dependance) d'un id de texture : catalogue, sinon texture d'origine compatible du modele."""
    m = next((m for m in material_catalog(track) if m['id'] == mid), None)
    if m:
        return m['name'], m['ns'], m['dep']
    o = next((p for p in originals if p['material'] == mid and p['compatible']), None)
    if o:
        return o['name'], o['ns'], o['dep']
    return None                                              # texture du gabarit (roche de Crash Cove)


def mesh_save(req):
    """req = {track, file (_Art), id, scope 'one' | 'all', parts: [{material, positions [x,y,z...], uvs [u,v...] |
    None, indices [...]}]} (positions locales au modele, pouces). Nouveau modele importe ; l'objet (scope 'one') ou
    tous les objets du meme modele (scope 'all') le recoivent. -> {report, ids, file, model}."""
    track, art, oid = req['track'], req['file'], int(req['id'])
    df0 = DecorFile(base_file(track, art)[0])
    obj = next((o for o in df0.objects() if o['id'] == oid), None)
    if obj is None:
        raise ValueError('objet introuvable : enregistre le décor puis recommence')
    old_logical = model_logical_path(obj['model'])
    originals = model_parts(track, obj['model'])['parts']
    template = read_game_file(track, TEMPLATE)
    parts, n_v, n_t, mats = [], 0, 0, []
    for p in req.get('parts') or []:
        P = [tuple(map(float, p['positions'][i:i + 3])) for i in range(0, len(p['positions']), 3)]
        T = [tuple(map(int, p['indices'][i:i + 3])) for i in range(0, len(p['indices']) // 3 * 3, 3)]
        if not T:
            continue
        # UV de l'apercu = valeurs stockees dans le modele (v vers le bas) ; build_model attend la convention OBJ
        # (il ecrit 1 - v) : v retourne ici, sinon la texture d'origine ressortait a l'envers
        U = [(float(p['uvs'][i]), 1.0 - float(p['uvs'][i + 1])) for i in range(0, len(p['uvs']) - 1, 2)] if p.get('uvs') else None
        if U is not None and len(U) != len(P):
            U = None
        # sommets de cette partie seulement (bornes propres : model_mesh ecarte deux draw calls de memes bornes et
        # meme nombre d'indices, pris pour des niveaux de detail)
        used = sorted({i for t in T for i in t})
        remap = {v: k for k, v in enumerate(used)}
        P = [P[i] for i in used]
        U = [U[i] for i in used] if U is not None else None
        T = [tuple(remap[i] for i in t) for t in T]
        q, n, u, t = complete_mesh(P, None, U, T)
        mat = _part_material(track, p.get('material'), originals)
        parts.append({'pos': q, 'nrm': n, 'uvs': u, 'tan': t, 'tris': T,
                      'material': mat or (lambda m: (m[1], m[2], m[3]))(model_materials(template)[0])})
        mats.append(p.get('material') if mat else 'gabarit')
        n_v += len(q)
        n_t += len(T)
    if not parts:
        raise ValueError('forme vide')
    reg = custom_models(track)
    base = _clean_name(os.path.basename(old_logical)[:-4].replace('_Forme', ''))[:30] + '_Forme'
    name, k = base, 1
    while os.path.exists(custom_model_path(f'{name}.igz')) or f'models/{CUSTOM_DIR}/{name}.igz' in reg:
        k += 1
        name = f'{base}{k}'
    logical = f'models/{CUSTOM_DIR}/{name}.igz'
    os.makedirs(os.path.join(OUT_DIR, 'models'), exist_ok=True)
    open(custom_model_path(logical), 'wb').write(build_model_multi(template, parts, f'{CUSTOM_DIR}/{name}'))
    _forget_model(logical)
    reg[logical] = {'name': name, 'vertices': n_v, 'triangles': n_t, 'material': mats[0], 'parts': mats,
                    'edited_from': old_logical}
    save_custom_models(track, reg)
    # objets a remplacer : celui-ci, ou tous ceux du meme modele (tous les fichiers de decor)
    igb = 'models:\\' + CUSTOM_DIR.replace('/', '\\') + f'\\{name}.igb'
    every = req.get('scope') == 'all'
    arts = art_files(track) if every else [art]
    ids, n_obj = [], 0
    for a in arts:
        links = load_links(track)                         # relu : write_art remappe les liens a chaque fichier
        df = df0 if a == art else DecorFile(base_file(track, a)[0])
        targets = [o for o in df.objects() if model_logical_path(o['model']).lower() == old_logical.lower()
                   and (every or o['id'] == oid)]
        if not targets:
            continue
        tmpl = template_object(track, a)
        if tmpl is None:
            raise ValueError(f'{os.path.basename(a)} : pas d\'objet modèle pour la copie')
        old_links = links.get(a, {})
        keep = [{k2: v for k2, v in (old_links.get(str(o['id'])) or {}).items() if k2 not in ('custom', 'library')}
                for o in targets]
        df.delete_many([o['id'] for o in targets])
        specs = [(tmpl, o['name'], o['pos'], o['euler'], o['scale']) for o in targets]
        created = df.duplicate_many(specs)
        for nid, kp in zip(created, keep):
            df.set_model(nid, igb)
            links.setdefault(a, {})[str(nid)] = {'surface': req.get('surface') or 'auto', **kp, 'custom': logical}
        for o in targets:
            old_links.pop(str(o['id']), None)
        save_links(track, links)
        idmap = write_art(track, a, df)
        if a == art:
            ids = [idmap.get(i, i) for i in created]
        n_obj += len(targets)
    report = [f'{name} : {len(parts)} texture(s), {n_v} sommets, {n_t} triangles ; {n_obj} objet(s) remplacé(s)']
    with progress.span(0.5, 1.0):
        report.append(defer_collision(track))
    return {'report': report, 'ids': ids, 'file': art, 'model': logical}


# -- colorisation d'un objet du decor (2026-11-10) -----------------------------------------------------------------
# Le jeu n'a pas de couleur par objet : la couleur vient de la texture. Chaque texture choisie est relue, teintee et
# importee comme une image (create_texture) ; l'objet est ensuite reconstruit en modele importe multi-textures
# (mesh_save, comme l'edition de forme), UV d'origine gardees.
TINT_MODES = ('tint', 'paint')


def _parse_color(c):
    c = str(c or '').lstrip('#')
    if not re.fullmatch(r'[0-9a-fA-F]{6}', c):
        raise ValueError(f'couleur invalide : {c}')
    return c.lower()


def tint_image(rgba, color, strength=1.0, mode='tint'):
    """rgba (H, W, 4) uint8 -> teinte. tint : la luminosite de la texture (recentree autour du gris moyen) garde
    les details, la couleur remplace la teinte (melange « lumiere douce » : gris moyen = couleur choisie) ;
    paint : couleur unie. strength 0..1 : melange avec l'original. Alpha inchange."""
    import numpy as np
    a = rgba.astype(np.float32) / 255.0
    rgb, alpha = a[..., :3], a[..., 3:4]
    c = np.array([int(color[i:i + 2], 16) for i in (0, 2, 4)], np.float32) / 255.0
    if mode == 'paint':
        out = np.broadcast_to(c, rgb.shape)
    else:
        lum = rgb @ np.array([0.299, 0.587, 0.114], np.float32)
        seen = alpha[..., 0] > 0.5
        mean = float(lum[seen].mean()) if seen.any() else float(lum.mean())
        l = np.clip(lum + (0.5 - mean), 0.0, 1.0)[..., None]       # contraste garde, gris moyen = couleur
        out = np.where(l < 0.5, 2.0 * l * c, 1.0 - 2.0 * (1.0 - l) * (1.0 - c))
    s = float(np.clip(strength, 0.0, 1.0))
    res = rgb * (1.0 - s) + out * s
    return (np.concatenate([res, alpha], -1) * 255.0 + 0.5).clip(0, 255).astype(np.uint8)


def _texture_rgba(track, ns, max_size):
    from PIL import Image
    if not ns:                                   # partie sans texture connue : gris moyen
        import numpy as np
        return np.full((64, 64, 4), (128, 128, 128, 255), np.uint8)
    import numpy as np
    return np.array(Image.open(io.BytesIO(texture_png(track, ns, max_size))).convert('RGBA'))


def tint_preview(track, ns, color, strength, mode):
    """Apercu (PNG <= 256 px) d'une texture teintee : meme calcul que l'enregistrement."""
    from PIL import Image
    img = tint_image(_texture_rgba(track, ns, 256), _parse_color(color), float(strength), mode)
    buf = io.BytesIO()
    Image.fromarray(img, 'RGBA').save(buf, 'PNG', compress_level=1)
    return buf.getvalue()


def recolor(req):
    """req = {track, file, id, scope, color '#rrggbb', strength 0..1, mode 'tint' | 'paint', parts: [{material,
    ns (texture couleur d'origine ou None), tint (bool), positions, uvs, indices}]}. Parties tint : texture teintee
    importee (reutilisee si deja faite avec les memes reglages) ; autres : texture d'origine. -> comme mesh_save."""
    from PIL import Image
    track = req['track']
    color, mode = _parse_color(req.get('color')), req.get('mode') or 'tint'
    if mode not in TINT_MODES:
        raise ValueError(f'mode inconnu : {mode}')
    strength = float(req.get('strength', 1.0))
    parts, made = [], 0
    for p in req.get('parts') or []:
        p = dict(p)
        # partie gardee mais au format de sommet incompatible : mesh_save la remplacerait par la roche du gabarit ->
        # copie de sa texture (teinte a 0 %)
        keep = not p.get('tint') and p.get('compatible') is False and p.get('ns')
        if p.get('tint') or keep:
            ns, s = p.get('ns'), 0.0 if keep else strength
            src = ['teinte', ns or '', color if s else '', round(s, 2), mode if s else '']
            rgba = _texture_rgba(track, ns, 1024)
            img = tint_image(rgba, color, s, mode)
            buf = io.BytesIO()
            Image.fromarray(img, 'RGBA').save(buf, 'PNG')
            # 'ColorMap,textures@!levels!Crash1!village!C1_WoodSolid02_C`tga,111' -> 'C1_WoodSolid02_C'
            mid = ns.split(',')[1] if ns and ns.count(',') >= 2 else (ns or 'uni')
            stem = _clean_name(mid.rsplit('!', 1)[-1].split('`')[0], 'Texture')[:24]
            size = 512 if max(rgba.shape[:2]) <= 512 else 1024
            r = create_texture(track, f'{stem}_{color}' if s else f'{stem}_copie', buf.getvalue(), source=src, size=size)
            p['material'] = r['id']
            made += 0 if r.get('reused') else 1
        parts.append(p)
    if not any(q.get('tint') for q in parts):
        raise ValueError('aucune partie à coloriser')
    # objet du jeu sans collision (palmier, feuillage traverses par les karts) : la copie colorisee reste sans
    # collision (mesh_save donnerait « comme le sol dessous »). Objets importes : leur reglage est garde (liens).
    surface = None
    try:
        col = decor_collision_preview(track, req['file'], int(req['id']))
        if not col.get('tris') and not col.get('own_instances') and 'modele importe' not in col.get('note', ''):
            surface = 'none'
    except Exception:
        pass
    with progress.span(0.0, 1.0):
        out = mesh_save({**req, 'parts': parts, 'surface': surface})
    if surface == 'none':
        out['report'].insert(0, "sans collision, comme l'objet d'origine")
    out['report'].insert(0, f'couleur #{color} ({"teinte" if mode == "tint" else "unie"}, {round(strength * 100)} %) : '
                            f'{made} texture(s) créée(s)')
    return out


def set_double_sided(req):
    """Modele importe visible des deux cotes en jeu (2026-11-06) : le jeu n'affiche que la face avant des triangles
    (panneau, banderole vus de dos : invisibles). req = {track, model, on}. on : chaque triangle double d'un triangle
    retourne (sommets copies, normales opposees), meme texture ; l'original est garde (<modele>.single.igz) et remis
    a off. Toutes les copies du modele changent."""
    track = req['track']
    logical = req['model'] if req['model'].startswith('models/') else model_logical_path(req['model'])
    p = custom_model_path(logical)
    if not logical.startswith(f'models/{CUSTOM_DIR}/') or not os.path.exists(p):
        raise ValueError('seulement pour les modèles importés')
    reg = custom_models(track)
    info = reg.setdefault(logical, {'name': os.path.basename(logical)[:-4]})
    keep = p[:-4] + '.single.igz'
    name = os.path.basename(logical)[:-4]
    if not req.get('on'):
        if os.path.exists(keep):
            shutil.copyfile(keep, p)
        info.pop('double', None)
        msg = f'{name} : visible d\'un seul côté (comme le modèle d\'origine)'
    else:
        if info.get('double'):
            return {'report': [f'{name} est déjà visible des deux côtés'], 'double': True}
        data = open(p, 'rb').read()
        shutil.copyfile(p, keep)
        pv = preview.model_preview(data, lambda lg: preview_read(track, lg))
        mats = model_materials(data)
        P, U, I = np.asarray(pv['positions'], float), np.asarray(pv['uvs'], float), np.asarray(pv['indices'], int)
        template = read_game_file(track, TEMPLATE)
        parts = []
        for k, (start, count, _) in enumerate(pv['groups']):
            tris = I[start:start + count].reshape(-1, 3)
            used = np.unique(tris)
            remap = {int(v): j for j, v in enumerate(used)}
            pos = [tuple(P[v]) for v in used]
            uvs = [(float(U[v][0]), 1.0 - float(U[v][1])) for v in used]       # convention OBJ (build_model : 1 - v)
            front = [tuple(remap[int(v)] for v in t) for t in tris]
            n = len(pos)
            back = [(a + n, c + n, b + n) for a, b, c in front]                  # copies retournees
            q, nrm, u, t = complete_mesh(pos + pos, None, uvs + uvs, front + back)
            m = mats[k] if k < len(mats) else mats[0]
            parts.append({'pos': q, 'nrm': nrm, 'uvs': u, 'tan': t, 'tris': front + back,
                          'material': (m[1], m[2], m[3]) if m[3] else (lambda x: (x[1], x[2], x[3]))(model_materials(template)[0])})
        open(p, 'wb').write(build_model_multi(template, parts, f'{CUSTOM_DIR}/{name}'))
        info['double'] = True
        msg = f'{name} : visible des deux côtés en jeu ({sum(len(x["tris"]) for x in parts)} triangles)'
    _forget_model(logical)
    save_custom_models(track, reg)
    return {'report': [msg], 'double': bool(info.get('double'))}


def _clean_name(s, default='Modele'):
    return re.sub(r'[^A-Za-z0-9_]', '_', s or '').strip('_')[:40] or default


def import_model(req):
    """Importe un OBJ (un modele ou une scene complete) dans le decor.

    req = {track, name, obj (texte), scale, up, file (fichier _Art),
           placement : 'view' (le centre-bas de la scene au point vise, pos [x,y,z] pouces) | 'absolute'
                       (coordonnees de l'OBJ = coordonnees du jeu),
           materials : {materiau OBJ (usemtl, '' si aucun) : {'material': id du catalogue | null, 'surface': 'auto' | int | 'none'}},
           material / surface : valeurs par defaut pour les materiaux OBJ non listes}
    Un modele .igz + un objet de decor par couple (objet OBJ, materiau OBJ), decoupe au-dela de 65 535 sommets.
    Chaque objet de decor a son origine au centre-bas de son morceau (deplacable seul ensuite)."""
    track = req['track']
    catalog = {m['id']: m for m in material_catalog(track)}
    progress.step('découpage du modèle', 0.0)
    groups = [g for g in parse_obj_groups(req['obj'], float(req.get('scale', 39.37)), req.get('up', 'y')) if g['tris']]
    if not groups:
        raise ValueError('aucune face dans l\'OBJ')
    mapping = req.get('materials') or {}
    default = {'material': req.get('material'), 'surface': req.get('surface', 'auto')}

    def choice(mtl):
        c = dict(default, **(mapping.get(mtl) or {}))
        if c.get('material') and c['material'] not in catalog:
            raise ValueError(f"materiau inconnu : {c['material']}")
        return c
    # placement : decalage applique a toute la scene ; reference = la route si elle est connue (anchor_material),
    # sinon toute la scene (dont le decor de fond, qui peut descendre bien plus bas que la route)
    anchor = [g for g in groups if req.get('anchor_material') and g['material'] == req['anchor_material']]
    allp = [p for g in (anchor or groups) for p in g['pos']]
    lo = [min(p[k] for p in allp) for k in range(3)]
    hi = [max(p[k] for p in allp) for k in range(3)]
    if req.get('placement') == 'absolute':
        shift = [0.0, 0.0, 0.0]
    else:
        target = list(req.get('pos') or [(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])
        if target[2] < KILL_Z + 1000:                     # vue visant sous le plancher de chute (-1000) : remontee
            target[2] = 0.0
        shift = [target[0] - (lo[0] + hi[0]) / 2, target[1] - (lo[1] + hi[1]) / 2, target[2] - lo[2]]
    base = _clean_name(req.get('name'))
    batch = f"{base} — {time.strftime('%d/%m %H:%M')}"     # lot d'import (« Nouvelle map » : retirer un import entier)
    taken = {os.path.basename(k).lower() for k in custom_models(track)}

    def free_name(want):
        name, n = want, 1
        while f'{name}.igz'.lower() in taken or os.path.exists(custom_model_path(f'{name}.igz')):
            n += 1
            name = f'{want}_{n}'
        taken.add(f'{name}.igz'.lower())
        return name
    template = read_game_file(track, TEMPLATE)
    os.makedirs(os.path.join(OUT_DIR, 'models'), exist_ok=True)
    art = req.get('file') or main_art(track)
    df = DecorFile(base_file(track, art)[0])
    # objet modele pris dans le fichier d'ORIGINE (apres « Nouvelle map », le fichier enregistre peut n'avoir plus
    # aucun objet ; ses donnees y restent aux memes adresses, write_art reconstruisant depuis l'original)
    tmpl = {'id': template_object(track, art)}
    if tmpl['id'] is None:
        raise ValueError(f'{os.path.basename(art)} : aucun objet modèle à copier dans ce fichier')
    reg, links = custom_models(track), load_links(track)
    specs, pending, used_names, n_verts, n_tris = [], [], set(df.names.values()), 0, 0
    for g in progress.items(groups, 'modèle {i} / {n}', 0.05, 0.55):
        if len(groups) == 1:
            want = base
        else:
            parts = [g['object'], g['material'] if sum(x['object'] == g['object'] for x in groups) > 1 else '']
            want = '_'.join(_clean_name(s, '') for s in [base] + parts if _clean_name(s, ''))[:36]
            if g['part'] or any(x is not g and (x['object'], x['material']) == (g['object'], g['material']) for x in groups):
                want += f'_p{g["part"] + 1}'
        name = free_name(want)
        logical = f'models/{CUSTOM_DIR}/{name}.igz'
        c = choice(g['material'])
        m = catalog.get(c.get('material'))
        # UV projetees calculees en coordonnees de scene (continues d'un morceau a l'autre), puis origine locale
        pos, nrm, uvs, tan = complete_mesh(g['pos'], g['nrm'], g['uvs'], g['tris'])
        glo = [min(p[k] for p in pos) for k in range(3)]
        ghi = [max(p[k] for p in pos) for k in range(3)]
        pivot = [(glo[0] + ghi[0]) / 2, (glo[1] + ghi[1]) / 2, glo[2]]
        local = [(p[0] - pivot[0], p[1] - pivot[1], p[2] - pivot[2]) for p in pos]
        if c.get('surface') == 'invisible':             # mur invisible : collision seule
            write_wall_model(track, reg, name, local, g['tris'], wall='obj', obj_object=g['object'],
                             obj_material=g['material'], **{'import': batch})
            c = dict(c, surface=WALL_SURFACE)
        else:
            data = build_model(template, local, nrm, uvs, tan, g['tris'], f'{CUSTOM_DIR}/{name}',
                               (m['name'], m['ns'], m['dep']) if m else None)
            open(custom_model_path(logical), 'wb').write(data)
            _forget_model(logical)
            reg[logical] = {'name': name, 'vertices': len(pos), 'triangles': len(g['tris']),
                            'material': c.get('material') or 'gabarit', 'obj_object': g['object'], 'obj_material': g['material'],
                            'import': batch}
        obj_name, k = name, 1
        while obj_name in used_names:
            k += 1
            obj_name = f'{name}_{k}'
        used_names.add(obj_name)
        world = [pivot[k] + shift[k] for k in range(3)]
        specs.append((tmpl['id'], obj_name, world, [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]))
        pending.append((name, logical, c.get('surface', 'auto')))
        n_verts += len(pos)
        n_tris += len(g['tris'])
    progress.step('écriture du décor', 0.58)
    created = df.duplicate_many(specs)
    for new_id, (name, logical, surface) in zip(created, pending):
        df.set_model(new_id, 'models:\\' + CUSTOM_DIR.replace('/', '\\') + f'\\{name}.igb')
        links.setdefault(art, {})[str(new_id)] = {'custom': logical, 'surface': surface}
    save_custom_models(track, reg)
    save_links(track, links)
    idmap = write_art(track, art, df)
    created = [idmap[i] for i in created]
    with progress.span(0.65, 1.0):
        report = [f'{len(created)} modele(s) : {n_verts} sommets, {n_tris} triangles', defer_collision(track)]
    zmin, kz = lo[2] + shift[2], world_killz(track)
    if zmin < kz + 200:
        report.append(f'ATTENTION : le modele descend a z = {zmin:.0f}, sous ou pres du plancher de chute du monde '
                      f'({kz:.0f}) : un kart qui y roule est considere comme tombe. Remonte-le (ou refais « Chutes et '
                      f'reapparitions » une fois le parcours cree).')
    return {'id': created[0], 'ids': created, 'file': art, 'report': report}


# -- bibliotheque d'objets du jeu (modeles des autres pistes) -------------------------------------
_library_cache = []


def library_catalog():
    if not _library_cache:
        _library_cache.extend(library.catalog(ARCHIVES))
    return _library_cache


def library_files(track, model, pak):
    """[(type, chemin, archive ou None si deja disponible en course)] des fichiers du modele."""
    read = lambda lg: read_game_file(track, lg, (pak,))
    out = []
    for typ, lg in library.dependencies(read, model):
        if library.available(ARCHIVES, lg, track_pak(track)):
            out.append((typ, lg, None))
        else:
            src = library.find_pak(ARCHIVES, lg, (pak,))
            if src is None:
                raise KeyError(f'fichier introuvable dans les archives : {lg}')
            out.append((typ, lg, src))
    return out


def place_library_many(track, items, tag):
    """Pose plusieurs objets de la bibliotheque en UNE ecriture du decor et UN recalcul de la collision (semis de
    l'onglet Creation). items = [{model, pak, pos [x, y, z], yaw, scale}]. Les objets marques `tag` (liens) d'un semis
    precedent sont d'abord supprimes ; les autres objets de la bibliotheque (poses a la main) ne bougent pas."""
    art = main_art(track)
    df = DecorFile(base_file(track, art)[0])
    links = load_links(track)
    fl = links.setdefault(art, {})
    old = [oid for oid, lk in fl.items() if isinstance(lk, dict) and lk.get('tag') == tag]
    present = set(df.names)
    df.delete_many([int(oid) for oid in old if int(oid) in present])
    for oid in old:
        fl.pop(oid, None)
    for model, pak in {(it['model'], it['pak']) for it in items}:
        library_files(track, model, pak)                    # erreur ici si un fichier manque : rien n'est ecrit
    specs, used, tmpl = [], set(df.names.values()), template_object(track, art)
    for it in items:
        base = os.path.basename(it['model'])[:-4]
        name, k = base, 1
        while name in used:
            k += 1
            name = f'{base}_{k}'
        used.add(name)
        s = max(0.05, float(it.get('scale') or 1.0))
        rx, ry = it.get('rot') or (0.0, 0.0)                # inclinaison selon la pente du sol (track_creator.prop_seat)
        specs.append((tmpl, name, [float(v) for v in it['pos']], [float(rx), float(ry), float(it.get('yaw') or 0.0)], [s, s, s]))
    ids = df.duplicate_many(specs) if specs else []
    for nid, it, sp in zip(ids, items, specs):
        df.set_model(nid, library.file_name(it['model']))
        # collision grossiere (forme generale, COARSE_DIV) : 500 objets semes = plus d'un million de triangles en
        # pleine definition, la collision ne pouvait plus etre encodee (plus de 65 535 sommets partages)
        fl[str(nid)] = {'custom': it['model'], 'library': it['pak'], 'tag': tag, 'coarse': True,
                        'surface': 'none' if NO_COLLISION_HINT.search(sp[1]) else 'auto'}
    save_links(track, links)
    write_art(track, art, df)
    with progress.span(0.5, 1.0):
        rep = defer_collision(track)
    return {'placed': len(ids), 'removed': len(old), 'report': rep}


def place_library(req):
    """Place un objet de la bibliotheque : req = {track, model (chemin logique), pak, pos [x,y,z], yaw (radians),
    scale (uniforme, defaut 1), file (fichier _Art, defaut Art_Core)}. Entite = copie de l'objet minimal du fichier d'origine (comme un modele
    importe) avec le modele de l'autre piste ; collision = son maillage (« sans collision » pour le feuillage)."""
    track, model, pak = req['track'], req['model'], req['pak']
    if not model.lower().startswith('models/') or not pak.endswith('.pak'):
        raise ValueError('modèle de la bibliothèque invalide')
    progress.step('dépendances du modèle', 0.0)
    files = library_files(track, model, pak)             # erreur ici si un fichier manque : rien n'est ecrit
    art = req.get('file') or main_art(track)
    df = DecorFile(base_file(track, art)[0])
    tmpl = {'id': template_object(track, art)}
    name = os.path.basename(model)[:-4]
    used, obj_name, k = set(df.names.values()), name, 1
    while obj_name in used:
        k += 1
        obj_name = f'{name}_{k}'
    pos = [float(v) for v in req.get('pos') or [0, 0, 0]]
    if pos[2] < KILL_Z + 1000:
        pos[2] = 0.0
    progress.step('écriture du décor', 0.1)
    s = max(0.05, float(req.get('scale') or 1.0))
    new_id = df.duplicate_many([(tmpl['id'], obj_name, pos, [0.0, 0.0, float(req.get('yaw') or 0.0)], [s, s, s])])[0]
    df.set_model(new_id, library.file_name(model))
    surface = 'none' if NO_COLLISION_HINT.search(name) else 'auto'
    links = load_links(track)
    links.setdefault(art, {})[str(new_id)] = {'custom': model, 'surface': surface, 'library': pak}
    save_links(track, links)
    new_id = write_art(track, art, df)[new_id]
    with progress.span(0.2, 1.0):
        rep = defer_collision(track)
    n_copy = sum(1 for *_, src in files if src)
    return {'id': new_id, 'file': art, 'report': [
        f"{obj_name} (de {library.nice(pak)}) : {len(files)} fichier(s), {n_copy} à copier dans l'archive de la piste à "
        f"l'installation" + (' ; sans collision (feuillage)' if surface == 'none' else ''), rep]}


def library_install_entries(track):
    """Objets de la bibliotheque utilises par le decor enregistre : (entrees du manifeste, {chemin: archive source}
    des fichiers a copier)."""
    links = load_links(track)
    wanted = {}
    for art in art_files(track):
        objs = {str(o['id']): o for o in DecorFile(base_file(track, art)[0]).objects()}
        for oid, lk in links.get(art, {}).items():
            if isinstance(lk, dict) and lk.get('library') and oid in objs:
                wanted[model_logical_path(objs[oid]['model']).lower()] = (lk['custom'], lk['library'])
    entries, copies = [], {}
    for model, pak in wanted.values():
        for typ, lg, src in library_files(track, model, pak):
            if (typ, lg) not in entries:
                entries.append((typ, lg))
            if src:
                copies[_archive_case(src, lg)] = src
    return entries, copies


# -- dessin au sol des boosters -----------------------------------------------------------------
BOOST_VISUAL_PREFIX = 'BoostPad_Visual_'
BOOST_MASK_TEX = 'textures/colormap,textures@!levels!octane!global!oct_turbo_pad_ec`tga,111.igz'
BOOST_VISUAL_LIFT = 3.0        # po au-dessus du point du booster (pas de scintillement avec la route)
BOOST_MODEL_VERSION = 2        # change -> le modele « BoostPad » deja cree est reconstruit (2 : sens des chevrons)


# couleurs des plaques : (haut des chevrons, bas des chevrons, fond) ; orange = BoostPad, bleu = BoostPadSuper
BOOST_PALETTE = {'orange': ((255, 230, 40), (255, 110, 40), (18, 28, 70)),
                 'bleu': ((150, 240, 255), (40, 150, 255), (8, 16, 48)),
                 'vert': ((200, 255, 90), (40, 200, 60), (10, 36, 20)),
                 'violet': ((235, 160, 255), (150, 60, 255), (28, 10, 52)),
                 'rouge': ((255, 140, 110), (230, 30, 30), (50, 10, 14)),
                 'rose': ((255, 190, 230), (255, 70, 170), (52, 12, 40))}


def boost_base(color):
    """Nom du modele de plaque d'une couleur (orange et bleu : noms d'origine, plaques deja creees)."""
    return {'orange': 'BoostPad', 'bleu': 'BoostPadSuper'}.get(color, f'BoostPad_{color}')


def boost_pad_png(track, super_=False):
    """Image de la plaque : chevrons du masque d'emission du jeu (oct_turbo_pad_ec, canal vert), degrade de la
    couleur choisie (BOOST_PALETTE ; super_ = True : bleu, False : orange, ou nom de couleur) sur fond sombre, bord
    clair ; pointe vers le bas de l'image (= sens de course apres le placage UV)."""
    from PIL import Image
    rgba, _ = preview.decode_texture(read_game_file(track, BOOST_MASK_TEX), 512)
    m = rgba[:, :, 1].astype(np.float32) / 255.0
    h, w = m.shape
    t = np.linspace(0, 1, h)[:, None]
    color = super_ if isinstance(super_, str) else ('bleu' if super_ else 'orange')
    top, bot, bgc = (np.array(v, np.float32) for v in BOOST_PALETTE.get(color, BOOST_PALETTE['orange']))
    hot = top * (1 - t[..., None]) + bot * t[..., None]
    bg = bgc
    img = bg * (1 - m[..., None]) + hot * m[..., None]
    img[:, :6] = img[:, -6:] = (250, 250, 250)                                   # bords lateraux
    buf = io.BytesIO()
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(buf, 'PNG')
    return buf.getvalue()


def ensure_boost_model(track, super_=False):
    """Modele importe « BoostPad » (super_ : « BoostPadSuper », plaque bleue) : plaque de 100 x 100 po (X = sens de
    course), texture generee. Cree une fois. super_ : True / False ou nom de couleur (BOOST_PALETTE)."""
    color = super_ if isinstance(super_, str) else ('bleu' if super_ else 'orange')
    base = boost_base(color)
    logical = f'models/{CUSTOM_DIR}/{base}.igz'
    reg = custom_models(track)
    if logical in reg and os.path.exists(custom_model_path(logical)) and reg[logical].get('version') == BOOST_MODEL_VERSION:
        return logical
    tex = create_texture(track, base, boost_pad_png(track, color), source=[base.lower(), 1])
    m = next(x for x in custom_material_entries(track) if x['id'] == tex['id'])
    pos = [(-50.0, -50.0, 0.0), (50.0, -50.0, 0.0), (50.0, 50.0, 0.0), (-50.0, 50.0, 0.0)]
    tris = [(0, 1, 2), (0, 2, 3)]
    # +X (avant) -> bas de l'image, ou pointent les chevrons ; build_model ecrit 1 - v (convention OBJ) : v inverse ici
    # (version 1 : chevrons vers l'arriere en jeu)
    uvs = [((p[1] + 50) / 100, (50 - p[0]) / 100) for p in pos]
    pos, nrm, uvs, tan = complete_mesh(pos, [(0.0, 0.0, 1.0)] * 4, uvs, tris)
    data = build_model(read_game_file(track, TEMPLATE), pos, nrm, uvs, tan, tris,
                       f'{CUSTOM_DIR}/{base}', (m['name'], m['ns'], m['dep']))
    os.makedirs(os.path.join(OUT_DIR, 'models'), exist_ok=True)
    open(custom_model_path(logical), 'wb').write(data)
    for cache in (_model_cache, _preview_cache, _visual_cache):
        cache.pop(logical, None)
    reg[logical] = {'name': base, 'vertices': 4, 'triangles': 2, 'material': tex['id'],
                    'obj_object': base, 'obj_material': base, 'version': BOOST_MODEL_VERSION}
    save_custom_models(track, reg)
    return logical


def sync_boost_visuals(track, boosts):
    """Un objet de decor « BoostPad_Visual_NNN » (sans collision) par booster : position, inclinaison et cap, taille =
    celles de sa zone (profondeur x largeur) ; plaque bleue pour un super turbo. Les anciens sont remplaces."""
    art = main_art(track)
    df = DecorFile(base_file(track, art)[0])
    olds = [o for o in df.objects() if (o['name'] or '').startswith(BOOST_VISUAL_PREFIX)]
    old = [o['id'] for o in olds]
    if not old and not boosts:
        return 'aucun booster'
    col = lambda b: b.get('color') if b.get('color') in BOOST_COLORS else ('bleu' if b.get('super') else 'orange')
    for s in {col(b) for b in boosts}:
        ensure_boost_model(track, s)                   # (re)construit le modele si sa version a change
    ground = ground_for(track)
    zs = [(lambda t: t if t is not None else b['pos'][2])(ground.top(b['pos'][0], b['pos'][1], b['pos'][2])) for b in boosts]
    euler = lambda b: [float(v) for v in (b.get('tilt') or [0.0, 0.0])] + [float(b.get('yaw') or 0.0)]
    want = [([b['pos'][0], b['pos'][1], z + BOOST_VISUAL_LIFT], euler(b), [b['dims'][0] / 100.0, b['dims'][1] / 100.0],
             col(b)) for b, z in zip(boosts, zs)]
    have = [(o['pos'], o['euler'], o['scale'][:2], boost_color_of_model(o['model'])) for o in sorted(olds, key=lambda o: o['name'])]
    if len(have) == len(want) and all(h[3] == w[3] and max(abs(a - b) for a, b in zip(h[0] + h[1] + h[2], w[0] + w[1] + w[2])) < 0.05
                                      for h, w in zip(have, want)):
        return None                                    # deja a jour
    df.delete_many(old)
    links = load_links(track)
    if boosts:
        tmpl = {'id': template_object(track, art)}
        # plaque sur la surface la plus haute sous le booster (la route), pas sur un niveau enfoui dessous (sable
        # 1 m sous la route de Mario Circuit 3 : la plaque y etait invisible)
        specs = [(tmpl['id'], f'{BOOST_VISUAL_PREFIX}{k:03d}', pos, e, scale + [1.0])
                 for k, (pos, e, scale, _) in enumerate(want, 1)]
        for nid, (*_, color) in zip(df.duplicate_many(specs), want):
            df.set_model(nid, 'models:\\' + CUSTOM_DIR.replace('/', '\\') + f'\\{boost_base(color)}.igb')
            links.setdefault(art, {})[str(nid)] = {'custom': ensure_boost_model(track, color), 'surface': 'none'}
        save_links(track, links)
    write_art(track, art, df)
    return f'dessin au sol : {len(boosts)} plaque(s)'


# -- import d'un dossier complet (OBJ + MTL + textures) -----------------------------------------
PROJECT_DIR = os.path.dirname(os.path.dirname(HERE))
IMAGE_EXT = ('.png', '.jpg', '.jpeg', '.tga', '.bmp', '.dds', '.tif', '.tiff', '.webp')
# decor non roulable : sans collision par defaut (feuillage, fleurs, lampes...) ; modifiable dans la fenetre
NO_COLLISION_HINT = re.compile(r'leaf|flower|plant|bush|tree|nature|kusa|mist|light|lamp|star(?!t)|cloud|sky|water|effect|confetti|^ef_'
                               r'|no_?col', re.I)        # « NoCollision_* » : nom donne par l'auteur de la map


def _folder(req):
    folder = os.path.abspath(os.path.join(PROJECT_DIR, req.get('folder') or 'map'))
    if not os.path.isdir(folder):
        raise ValueError(f'dossier introuvable : {folder}')
    return folder


def _find_file(folder, name):
    """Fichier du dossier (chemin relatif ou seulement le nom de fichier ; chaque element du chemin insensible a la
    casse, aussi sous Linux : « Textures\\Herbe.PNG » d'un .mtl Windows trouve textures/herbe.png)."""
    if not name:
        return None
    name = name.replace('\\', '/')

    # chemin donne, sinon le nom seul dans le dossier
    for cand in (name, os.path.basename(name)):
        
        # chemin absolu : tel quel (sinon le nom seul, essai suivant)
        if os.path.isabs(cand):
            if os.path.isfile(cand):
                return cand
            continue
        p = folder

        # element par element : nom exact, sinon le meme a la casse pres
        for part in cand.split('/'):
            if part in ('', '.'):
                continue
            q = os.path.join(p, part)
            if not os.path.exists(q):
                try:
                    q = os.path.join(p, next(f for f in os.listdir(p) if f.lower() == part.lower()))
                except (OSError, StopIteration):
                    break
            p = q
        else:
            # tout le chemin trouve
            if os.path.isfile(p):
                return p
    return None


def _folder_materials(folder, text):
    summ = obj_summary(text)
    mtl = {}
    for lib in summ['mtllibs']:
        p = _find_file(folder, lib)
        if p:
            mtl.update(parse_mtl(open(p, encoding='utf-8', errors='replace').read()))
    if not summ['mtllibs']:                              # sans mtllib : tous les .mtl du dossier
        for f in os.listdir(folder):
            if f.lower().endswith('.mtl'):
                mtl.update(parse_mtl(open(os.path.join(folder, f), encoding='utf-8', errors='replace').read()))
    return summ, mtl


MODEL_EXT = ('.obj', '.dae')
_dae_cache = {}


def _load_source(folder, name):
    """(texte OBJ, materiaux {nom: {'texture', 'color'}}, resume, axe vertical propose) d'un .obj (+ .mtl) ou
    d'un .dae (converti par dae_import ; resultat garde en cache tant que le fichier ne change pas)."""
    path = os.path.join(folder, name)
    if name.lower().endswith('.dae'):
        import dae_import
        st = os.stat(path)
        key = (path, st.st_size, st.st_mtime_ns)
        if key not in _dae_cache:
            if len(_dae_cache) >= 8:                   # plusieurs .dae importes ensemble : gardes tous
                _dae_cache.pop(next(iter(_dae_cache)))
            _dae_cache[key] = dae_import.dae_to_obj(path)
        text, mtl, up = _dae_cache[key]
        return text, mtl, obj_summary(text), up
    text = open(path, encoding='utf-8', errors='replace').read()
    summ, mtl = _folder_materials(folder, text)
    return text, mtl, summ, 'y'


def _obj_objects(text):
    """[(objet `o`/`g`, triangles)] d'un OBJ, dans l'ordre du fichier (objets sans face ignores)."""
    counts, obj = {}, ''
    for line in text.splitlines():
        if line.startswith(('o ', 'g ')):
            obj = line[2:].strip()
        elif line.startswith('f '):
            counts[obj] = counts.get(obj, 0) + len(line.split()) - 3
    return list(counts.items())


# axe vertical d'un fichier -> celui de la scene fusionnee (y : (x, -z, y) dans le jeu ; z : tel quel)
_UP_CONVERT = {('z', 'y'): lambda x, y, z: (x, z, -y), ('y', 'z'): lambda x, y, z: (x, -z, y)}


def _filter_obj(text, keep, base, rename_obj=None, rename_mtl=None, conv=None):
    """OBJ reduit aux faces des objets gardes (keep(objet)), sommets / UV / normales inutiles retires, indices a
    partir de base = (sommets, UV, normales) deja ecrits ; objets / materiaux renommes, axe vertical converti.
    -> (texte, nombres ecrits (sommets, UV, normales))."""
    src, faces, obj, mtl = ([], [], []), [], '', ''
    for line in text.splitlines():
        p = line.split()
        if not p:
            continue
        k = {'v': 0, 'vt': 1, 'vn': 2}.get(p[0])
        if k is not None:
            src[k].append(p[1:4] if k != 1 else p[1:3])
        elif p[0] in ('o', 'g'):
            obj = ' '.join(p[1:])
        elif p[0] == 'usemtl':
            mtl = ' '.join(p[1:])
        elif p[0] == 'f' and keep(obj):
            cs = []
            for c in p[1:]:
                idx = (c.split('/') + ['', ''])[:3]
                cs.append(tuple((int(s) - 1 if int(s) > 0 else len(src[j]) + int(s)) if s else None for j, s in enumerate(idx)))
            faces.append((obj, mtl, cs))
    remap = ({}, {}, {})
    for _, _, cs in faces:
        for c in cs:
            for j in range(3):
                if c[j] is not None and c[j] not in remap[j]:
                    remap[j][c[j]] = len(remap[j])
    out = []
    for j, tag in enumerate(('v', 'vt', 'vn')):
        for i in remap[j]:                             # ordre d'apparition dans les faces
            vals = src[j][i]
            if conv and j != 1:
                vals = ['%.6f' % c for c in conv(*map(float, vals))]
            out.append(f'{tag} {" ".join(vals)}')
    cur = None
    for obj, mtl, cs in faces:
        if (obj, mtl) != cur:
            out.append(f'o {rename_obj(obj) if rename_obj else obj}')
            out.append(f'usemtl {(rename_mtl or {}).get(mtl, mtl)}')
            cur = (obj, mtl)
        out.append('f ' + ' '.join('/'.join('' if c[j] is None else str(base[j] + remap[j][c[j]] + 1) for j in range(3)).rstrip('/')
                                   for c in cs))
    return '\n'.join(out) + '\n', tuple(len(r) for r in remap)


def _load_sources(folder, names, objects=None):
    """Un ou plusieurs .obj / .dae du dossier fusionnes en une scene : (texte OBJ, materiaux, resume, axe vertical,
    elements [{file, name, triangles}] de ces fichiers). objects = None (tout) ou ['fichier|objet', ...] a garder.
    Plusieurs fichiers : objets prefixes du nom du fichier, materiaux homonymes differents renommes, axe vertical du
    premier fichier (les autres convertis) ; memes echelle et placement pour tous (ils restent alignes)."""
    names = list(dict.fromkeys(names))
    if objects is not None and not objects:
        raise ValueError('aucun élément choisi')
    keep_set = None if objects is None else set(objects)
    srcs = [(name,) + _load_source(folder, name) for name in names]
    if len(srcs) == 1 and keep_set is None:            # un fichier entier : tel quel
        name, text, mtl, summ, up = srcs[0]
        return text, mtl, summ, up, [{'file': name, 'name': o, 'triangles': n} for o, n in _obj_objects(text)]
    up0, multi = srcs[0][4], len(srcs) > 1
    parts, mtl_all, elements, base = [], {}, [], (0, 0, 0)
    for name, text, mtl, _, up in srcs:
        stem = _clean_name(os.path.splitext(name)[0])
        elements += [{'file': name, 'name': o, 'triangles': n} for o, n in _obj_objects(text)]
        ren = {}
        for m, info in mtl.items():
            new = m if m not in mtl_all or mtl_all[m] == info else f'{m}__{stem}'
            ren[m], mtl_all[new] = new, info
        keep = (lambda o: True) if keep_set is None else (lambda o, name=name: f'{name}|{o}' in keep_set)
        part, n = _filter_obj(text, keep, base, (lambda o, s=stem: f'{s}_{o}') if multi else None, ren,
                              _UP_CONVERT.get((up, up0)))
        parts.append(part)
        base = tuple(b + k for b, k in zip(base, n))
    text = ''.join(parts)
    summ = obj_summary(text)
    if not summ['triangles']:
        raise ValueError('aucun triangle dans les éléments choisis')
    return text, mtl_all, summ, up0, elements


def _chosen_files(req, objs):
    """Fichiers choisis : req['files'] (plusieurs), sinon req['obj'], sinon le premier du dossier."""
    files = [f for f in (req.get('files') or ([req['obj']] if req.get('obj') else [])) if f in objs]
    return files or objs[:1]


ROAD_WIDTH_TARGET = 30.0       # m : largeur de route visee (Crash Cove : ~48 m au plus large, routes CTR 20-40 m)


def _nice(raw):
    p = 10 ** math.floor(math.log10(raw))
    return min((p * m for m in (1, 2, 5, 10)), key=lambda v: abs(math.log(v / raw)))


def _suggest_scale(bounds, up):
    """Metres par unite pour que le plus grand cote horizontal fasse ~500 m (valeur ronde 1-2-5)."""
    if not bounds:
        return 1.0
    e = [bounds[1][k] - bounds[0][k] for k in range(3)]
    side = max(e[0], e[1] if up == 'z' else e[2]) or 1.0
    return _nice(500.0 / side)


def _road_scale(text, up):
    """Echelle d'apres la ROUTE : surface des materiaux « road » la plus grande (si elle couvre une part notable de
    la scene), largeur mediane mesuree sur son squelette (vue de dessus) -> ROAD_WIDTH_TARGET. Les maps contiennent
    souvent un decor de fond tres lointain (nuages, montagnes) : l'emprise totale ne dit rien de la taille de la
    route (Mario Circuit 3 : fichier de 82 000 unites, route de 4 200). -> (echelle, materiau, largeur brute) | None."""
    key = (hash(text), up)                              # analyse puis import : meme fichier, calcul fait une fois
    if key not in _road_scale_cache:
        _road_scale_cache.clear()
        _road_scale_cache[key] = _road_scale_calc(text, up)
    return _road_scale_cache[key]


_road_scale_cache = {}


def _road_scale_calc(text, up):
    import route_gen
    groups = [g for g in parse_obj_groups(text, 1.0, up) if re.search(r'road', g['material'] or '', re.I)]
    by_mat = defaultdict(list)
    for g in groups:
        P = g['pos']
        by_mat[g['material']] += [(P[a], P[b], P[c]) for a, b, c in g['tris']]
    best = None
    for m, tris in by_mat.items():
        if len(tris) < 200:
            continue
        T = np.array(tris)
        ext = T[:, :, :2].max((0, 1)) - T[:, :, :2].min((0, 1))
        cell = max(float(ext.max()) / 300, 1e-6)
        road = route_gen.largest_component(route_gen.close_holes(route_gen.rasterize(tris, cell)[0], 1))
        area = float(road.sum()) * cell * cell
        sk = route_gen.thin(road)
        width = 2 * float(np.median(route_gen.depth(road)[sk])) * cell if sk.any() else 0.0
        # une route : bien plus longue que large (pas un panneau, une ligne de depart...)
        if width > 0 and float(ext.max()) >= 8 * width and (best is None or area > best[0]):
            best = (area, m, width)
    if best is None:
        return None
    _, m, width = best
    return _nice(ROAD_WIDTH_TARGET / width), m, width


def folder_scan(req):
    """req = {folder (relatif au projet ou absolu), files (facultatif : un ou plusieurs .obj / .dae ; ancien : obj),
    objects (facultatif : ['fichier|objet'] a garder)} -> fichiers .obj / .dae du dossier, elements (objets) des
    fichiers choisis et, pour la selection, ses materiaux : texture trouvee, triangles, collision proposee ;
    taille brute, echelle et axe proposes."""
    folder = _folder(req)
    objs = sorted(f for f in os.listdir(folder) if f.lower().endswith(MODEL_EXT))
    if not objs:
        raise ValueError(f'aucun fichier .obj ou .dae dans {folder}')
    files = _chosen_files(req, objs)
    obj = ', '.join(files)
    progress.step(f'lecture de {obj}', 0.02)
    text, mtl, summ, up, elements = _load_sources(folder, files, req.get('objects'))
    progress.step('taille des matériaux', 0.3)
    # decor de fond (montagnes, nuages, sol a perte de vue : bien plus grand que la route) : sans collision par
    # defaut — ses triangles de plusieurs km faisaient exploser la collision (4 millions de morceaux, non encodable)
    # (un grand sol PLAT garde sa collision : sinon les karts tombent en sortant de la route)
    ext = obj_material_extents(text, up)
    roads = [e[0] for m, e in ext.items() if re.search(r'road', m, re.I) and summ['triangles'].get(m, 0) >= 200]
    ref = max(roads) if roads else float(np.median([e[0] for e in ext.values()] or [1.0])) * 2
    mats = []
    for name, n in progress.items(sorted(summ['triangles'].items(), key=lambda kv: -kv[1]),
                                  'transparence des textures {i} / {n}', 0.4, 0.75):
        info = mtl.get(name, {})
        tex = _find_file(folder, info.get('texture'))
        horiz, height = ext.get(name, (0.0, 0.0))
        background = horiz > 3 * ref and height > 0.03 * horiz
        mats.append({'name': name, 'triangles': n, 'texture': os.path.basename(tex) if tex else None,
                     'texture_missing': info.get('texture') if info.get('texture') and not tex else None,
                     'color': info.get('color'), 'background': background,
                     'collision': not NO_COLLISION_HINT.search(name) and not background,
                     'alpha': bool(tex) and texture_build.image_has_alpha(open(tex, 'rb').read())})
    images = sum(1 for f in os.listdir(folder) if f.lower().endswith(IMAGE_EXT))
    progress.step('largeur de la route (échelle proposée)', 0.75)
    return {'folder': folder, 'objs': objs, 'obj': obj, 'files': files, 'elements': elements,
            'objects': req.get('objects'), 'materials': mats, 'vertices': summ['vertices'],
            'triangles': sum(summ['triangles'].values()), 'bounds': summ['bounds'], 'images': images,
            'up': up, **_scale_info(text, summ['bounds'], up)}


def _scale_info(text, bounds, up):
    rs = _road_scale(text, up)
    if rs:
        scale, mat, width = rs
        return {'scale': scale, 'road_width_raw': width, 'road_material': mat,
                'scale_reason': f"d'après la route ({mat})"}
    return {'scale': _suggest_scale(bounds, up),
            'scale_reason': "d'après la taille de la scène (~500 m de côté ; pas de matériau « road » assez grand)"}


ROAD_WIDTH_OK = (8.0, 80.0)    # m : largeur de route acceptee a l'import (une route CTR : 20 a 40 m)


def _check_import_scale(text, req):
    """Refuse une echelle qui donne une route absurde (sauf req['force']) : a l'echelle 1 au lieu de 0,1, map3
    faisait 4 km (montagnes de 70 km) et la creation du parcours, la collision et l'enregistrement n'en finissaient
    plus."""
    rs = None if req.get('force') else _road_scale(text, req.get('up', 'y'))
    if not rs:
        return
    proposed, mat, width = rs
    w = width * float(req.get('scale', 39.37)) / 39.37
    if not ROAD_WIDTH_OK[0] <= w <= ROAD_WIDTH_OK[1]:
        raise ValueError(f'echelle douteuse : la route ({mat}) ferait {w:.0f} m de large (une route CTR : 20 a 40 m). '
                         f'Echelle proposee : {proposed} m par unite.')


def import_folder(req):
    """Import d'un dossier en une fois : req = {track, folder, files (un ou plusieurs .obj / .dae ; ancien : obj),
    objects (facultatif : ['fichier|objet'] a garder), scale, up, placement, pos, file,
    materials: {materiau OBJ: {'collision': bool, 'surface': 'auto' | int}}}. Chaque materiau recoit sa texture
    (map_Kd du .mtl, convertie ; a defaut une couleur unie Kd), puis la scene est importee (un modele par objet /
    materiau) avec ces textures et la collision choisie."""
    from PIL import Image
    track = req['track']
    folder = _folder(req)
    wanted = req.get('files') or ([req['obj']] if req.get('obj') else [])
    if not wanted or any(not os.path.isfile(os.path.join(folder, f)) or not f.lower().endswith(MODEL_EXT) for f in wanted):
        raise ValueError('fichier .obj / .dae introuvable dans le dossier')
    obj = wanted[0] if len(wanted) == 1 else os.path.basename(os.path.normpath(folder)) + '.obj'
    progress.step(f'lecture de {", ".join(wanted)}', 0.01)
    text, mtl, summ, _, _ = _load_sources(folder, wanted, req.get('objects'))
    _check_import_scale(text, req)
    choice = req.get('materials') or {}
    mapping, made, reused, plain = {}, 0, 0, 0
    # taille des textures : 'auto' = 512 pour celles qui ne servent qu'au decor de fond, sinon 1024 ; ou 512 / 1024
    want_size = str(req.get('texture_size') or 'auto')
    users = defaultdict(list)
    for name in summ['triangles']:
        users[_find_file(folder, mtl.get(name, {}).get('texture'))].append(name)
    tex_size = lambda tex: (int(want_size) if want_size in ('512', '1024') else
                            512 if all((choice.get(m) or {}).get('background') for m in users[tex]) else 1024)
    with progress.span(0.05, 0.35):
        for name in progress.items(summ['triangles'], 'texture {i} / {n}'):
            if (choice.get(name) or {}).get('surface') == 'invisible':    # mur invisible : pas de texture
                mapping[name] = {'material': None, 'surface': 'invisible'}
                continue
            info = mtl.get(name, {})
            tex = _find_file(folder, info.get('texture'))
            if tex:
                st = os.stat(tex)
                r = create_texture(track, os.path.splitext(os.path.basename(tex))[0], open(tex, 'rb').read(),
                                   source=[os.path.abspath(tex), st.st_size, int(st.st_mtime)],
                                   alpha=(choice.get(name) or {}).get('alpha'), size=tex_size(tex))
            else:                                            # pas d'image : couleur unie du materiau (Kd)
                col = tuple(int(max(0, min(1, c)) * 255) for c in (info.get('color') or (0.6, 0.6, 0.6)))
                buf = io.BytesIO()
                Image.new('RGB', (8, 8), col).save(buf, 'PNG')
                r = create_texture(track, f'{_clean_name(name, "Couleur")}_couleur', buf.getvalue(),
                                   source=['couleur'] + list(col))
                plain += 1
            reused += bool(r.get('reused'))
            made += not r.get('reused')
            c = choice.get(name) or {}
            collide = c.get('collision', not NO_COLLISION_HINT.search(name))
            mapping[name] = {'material': r['id'], 'surface': c.get('surface', 'auto') if collide else 'none'}
    with progress.span(0.35, 1.0):
        res = import_model({'track': track, 'name': os.path.splitext(obj)[0], 'obj': text,
                            'scale': req.get('scale', 39.37), 'up': req.get('up', 'y'),
                            'placement': req.get('placement', 'view'), 'pos': req.get('pos'), 'file': req.get('file'),
                            'materials': mapping, 'anchor_material': req.get('road_material')})
    res['report'].insert(0, f'{len(mapping)} materiau(x) : {made} texture(s) creee(s), {reused} reutilisee(s)'
                            + (f', {plain} en couleur unie (image absente)' if plain else '')
                            + f' ; collision sur {sum(m["surface"] != "none" for m in mapping.values())}')
    return res


def _tri_area2(t):
    """Carre du double de l'aire d'un triangle (pouces^4)."""
    a, b, c = t
    u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    v = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    return n[0] ** 2 + n[1] ** 2 + n[2] ** 2


LINK_TOLERANCE = 12.0          # pouces : un triangle du sol « appartient » a un objet si ses 3 sommets en sont si proches
_visual_cache = {}


def object_world_array(track, obj):
    """Triangles monde (pouces) du modele visuel d'un objet, a sa transformation (obj) : tableau (n, 3, 3).
    Mur invisible : son maillage de collision (le modele du jeu n'est qu'un point)."""
    logical = model_logical_path(obj['model'])
    if logical not in _visual_cache:
        pos, idx = model_or_wall_mesh(track, logical)
        _visual_cache[logical] = (np.asarray(pos, np.float64).reshape(-1, 3),
                                  np.asarray(idx[:len(idx) // 3 * 3], np.int64).reshape(-1, 3))
    V, F = _visual_cache[logical]
    M = np.asarray(object_matrix(obj['pos'], obj['euler'], obj['scale']), np.float64)
    return (V @ M[:3, :3].T + M[:3, 3])[F]


def object_world_tris(track, obj):
    """Triangles monde (pouces) du modele visuel d'un objet : [((x, y, z) * 3)]."""
    return [tuple(map(tuple, t)) for t in object_world_array(track, obj).tolist()]


def instance_matches(cf, originals):
    """{indice d'instance: (fichier, objet d'origine)} : instance placee exactement comme l'objet."""
    out = {}
    for inst in cf.instances():
        cand = [(math.dist(o['pos'], inst['pos']), art, o) for art, o in originals
                if abs(o['pos'][0] - inst['pos'][0]) < 1 and abs(o['pos'][1] - inst['pos'][1]) < 1]
        cand = [c for c in cand if c[0] < 0.5 and all(abs(a - b) < 1e-3 for a, b in zip(c[2]['scale'], inst['scale']))]
        if cand:
            _, art, orig = min(cand, key=lambda c: c[0])
            out[inst['index']] = (art, orig)
    return out


def linked_ground(ge, track, obj, own_instances):
    """Primitives des maillages de sol qui appartiennent a l'objet (hors instances propres de l'objet) :
      1) graines = primitives dont les 3 sommets sont a moins de LINK_TOLERANCE du modele visuel ;
      2) propagation aux voisines (sommet commun) de la surface majoritaire des graines (ex. bois), dans
         l'emprise du modele (+40 po autour, +120 po dessous) : recupere les parties de collision qui ne
         collent pas exactement au visuel (tablier ~1 m plus bas, poutres) sans prendre le terrain.
    Valide sur Bridge04 : 139 graines -> 408 primitives, plus aucun bois restant sous l'ancien emplacement."""
    tris = object_world_tris(track, obj)
    seeds = [s for s in ge.select_near_mesh(tris, LINK_TOLERANCE) if ge.meshes[s[0]]['instance'] not in own_instances]
    if not seeds:
        return []
    major = collections.Counter(ge.meshes[mi]['mesh'].prims[pi].value for mi, pi in seeds).most_common(1)[0][0]
    pts = [v for t in tris for v in t]
    lo = [min(p[k] for p in pts) for k in range(3)]
    hi = [max(p[k] for p in pts) for k in range(3)]
    box = ([lo[0] - 40, lo[1] - 40, lo[2] - 120], [hi[0] + 40, hi[1] + 40, hi[2] + 40])
    grown = ge.grow_connected([s for s in seeds if ge.meshes[s[0]]['mesh'].prims[s[1]].value == major], box)
    return sorted(set(grown) | set(seeds))


MAX_COLLISION_EDGE = 4000.0    # ~100 m : le sol du jeu n'a aucun triangle de plus de ~300 m
KILL_Z = -1000.0               # CWorldEntityData._killz de Crash Cove : en dessous, le kart est « tombe »


SUBDIV_MAX = 8                 # au plus 8 x 8 = 64 morceaux par triangle (decor de fond de plusieurs km : explosion)


def subdivide_tri(t, max_edge=MAX_COLLISION_EDGE):
    """Triangle decoupe en n^2 triangles (n = arete max / max_edge, arrondi au-dessus, au plus SUBDIV_MAX), meme
    orientation. Des triangles de plusieurs km (modele importe tres agrandi) ne collisionnent pas en jeu ; au-dela de
    SUBDIV_MAX le triangle est hors de toute route (decor de fond : 292 triangles d'herbe sur 52 km donnaient 2
    millions de morceaux et la collision ne pouvait plus etre encodee)."""
    a, b, c = (np.array(p, np.float64) for p in t)
    n = min(SUBDIV_MAX, int(math.ceil(max(np.linalg.norm(b - a), np.linalg.norm(c - b), np.linalg.norm(a - c)) / max_edge)))
    if n <= 1:
        return [t]
    P = lambda i, j: tuple(a + (b - a) * (i / n) + (c - a) * (j / n))
    out = []
    for i in range(n):
        for j in range(n - i):
            out.append((P(i, j), P(i + 1, j), P(i, j + 1)))
            if i + j < n - 1:
                out.append((P(i + 1, j), P(i + 1, j + 1), P(i, j + 1)))
    return out


def _extent(T):
    """(plus grand cote horizontal, hauteur) d'un tableau de triangles (n, 3, 3)."""
    d = T.reshape(-1, 3).max(0) - T.reshape(-1, 3).min(0)
    return float(max(d[0], d[1])), float(d[2])


def _background_objects(track, objs):
    """Noms des objets importes de decor de fond (montagnes, nuages) : plus de 3x plus etendus que la route et
    hauts (> 3 % de leur etendue). Un grand sol plat (herbe autour du circuit) n'en fait pas partie.
    objs : [(nom, triangles monde (n, 3, 3))]."""
    ext = {name: _extent(T) for name, T in objs if len(T)}
    roads = [ext[n][0] for n in ext if re.search(r'road', n, re.I)]
    if not roads:
        return set()
    ref = max(roads)
    return {n for n, (h, v) in ext.items() if h > 3 * ref and v > 0.03 * h}


# -- allegement ---------------------------------------------------------------------------------
def light_path(track):
    return os.path.join(OUT_DIR, f'{track}_light.json')


def light_settings(track):
    """Reglages « Alleger la map » : collision_cell (po, 0 = collision exacte) des murs et decors importes."""
    p = light_path(track)
    return {'collision_cell': 0, 'texture_max': 0, 'decor_reach': 100, **(json.load(open(p)) if os.path.exists(p) else {})}


def _imported_objects(track):
    """[(fichier _Art, objet, lien {custom, surface})] des objets de decor issus de modeles importes."""
    links, out = load_links(track), []
    for art in art_files(track):
        for o in DecorFile(base_file(track, art)[0]).objects():
            lk = links.get(art, {}).get(str(o['id']))
            if isinstance(lk, dict) and 'custom' in lk:
                out.append((art, o, lk))
    return out


def light_info(track):
    """Etat pour « Alleger la map » : reglage de collision, triangles de collision des modeles importes (exacts /
    simplifies), textures importees utilisees (taille, fond), modeles importes inutilises (fichiers a nettoyer)."""
    objs = _imported_objects(track)
    reg, tex = custom_models(track), custom_textures(track)
    arrays = {o['name']: object_world_array(track, o) for _, o, lk in objs}
    background = _background_objects(track, list(arrays.items()))
    coll = [(o['name'], arrays[o['name']]) for _, o, lk in objs
            if lk.get('surface', 'auto') != 'none' and not (lk.get('surface', 'auto') == 'auto' and o['name'] in background)]
    walls = [(n, T) for n, T in coll if not is_flat(n, T)]
    n_total = sum(len(T) for _, T in coll)
    simplified = {str(c): n_total - sum(len(T) - len(simplify_tris(T, c)) for _, T in walls) for c in (20, 40)}
    used_models = {lk['custom'] for _, _, lk in objs}
    by_mat = {i['material_id']: n for n, i in tex.items()}
    tex_users = defaultdict(list)                   # texture -> objets qui l'utilisent
    for _, o, lk in objs:
        t = by_mat.get((reg.get(lk['custom']) or {}).get('material'))
        if t:
            tex_users[t].append(o['name'])
    textures = []
    for name, users in sorted(tex_users.items()):
        info = tex[name]
        src = (info.get('source') or [None])[0]
        textures.append({'name': name, 'size': info.get('size', 1024), 'alpha': bool(info.get('alpha')),
                         'background': all(u in background for u in users), 'objects': len(users),
                         'resizable': bool(src) and isinstance(src, str) and os.path.isfile(src)})
    unused = [k for k in reg if k not in used_models and os.path.exists(custom_model_path(k))]
    return {'collision_cell': light_settings(track)['collision_cell'], 'collision': {'0': n_total, **simplified},
            'texture_max': int(light_settings(track).get('texture_max') or 0),
            'decor_reach': light_settings(track).get('decor_reach', 100),
            'walls': len(walls), 'textures': textures,
            'unused_models': len(unused), 'unused_mb': round(sum(os.path.getsize(custom_model_path(k)) for k in unused) / 2 ** 20, 1)}


def apply_light(req):
    """req = {track, collision_cell (0 | 20 | 40 po), sizes: {texture: 512 | 1024}, cleanup: bool} : reglages
    enregistres, textures refaites sur place a la taille voulue, modeles importes inutilises retires (fichiers et
    registre : la copie « Annuler » les garde), collision recalculee."""
    track, report = req['track'], []
    os.makedirs(OUT_DIR, exist_ok=True)
    cell = int(req.get('collision_cell') or 0)
    st = light_settings(track)
    st['collision_cell'] = cell
    # reduction de la map (2026-11-07) : taille max des textures a l'installation (0 = auto, sous PAK_BUDGET),
    # collision du decor retiree au-dela de decor_reach m de la piste (0 = jamais)
    if 'texture_max' in req:
        st['texture_max'] = int(req['texture_max'] or 0) if int(req['texture_max'] or 0) in (0, 512, 1024) else 0
    if 'decor_reach' in req:
        st['decor_reach'] = max(0, min(1000, int(req['decor_reach'] or 0)))
    json.dump(st, open(light_path(track), 'w'))
    reg = custom_textures(track)
    changed = []
    for name, size in progress.items((req.get('sizes') or {}).items(), 'texture {i} / {n}', 0.0, 0.5):
        info = reg.get(name)
        src = (info or {}).get('source') or []
        if not info or int(size) not in TEXTURE_SIZES or info.get('size', 1024) == int(size) \
                or not src or not isinstance(src[0], str) or not os.path.isfile(src[0]):
            continue
        _write_texture_files(track, name, open(src[0], 'rb').read(), bool(info.get('alpha')), int(size))
        info['size'] = int(size)
        changed.append(f'{name} ({size})')
    if changed:
        json.dump(reg, open(custom_textures_path(track), 'w'), indent=1)
        report.append(f'{len(changed)} texture(s) refaite(s) : ' + ', '.join(changed[:8]) + (' …' if len(changed) > 8 else ''))
    if req.get('cleanup'):
        progress.step('nettoyage des modèles inutilisés', 0.5)
        used = {lk['custom'] for _, _, lk in _imported_objects(track)}
        models = custom_models(track)
        gone = [k for k in models if k not in used]
        for k in gone:
            if os.path.exists(custom_model_path(k)):
                os.remove(custom_model_path(k))
            del models[k]
            for cache in (_model_cache, _preview_cache, _visual_cache):
                cache.pop(k, None)
        if gone:
            save_custom_models(track, models)
            report.append(f'{len(gone)} modèle(s) importé(s) inutilisé(s) retiré(s)')
    with progress.span(0.55, 1.0):
        report.append(defer_collision(track))
    return {'report': report}


def is_flat(name, T):
    """Surface de roulage (route, terre, herbe, ligne de depart) : nom « road » ou au moins 85 % de la surface
    horizontale (pente < 25 deg) ; sa collision n'est jamais simplifiee (bosses sous les roues). (L'etendue ne suffit
    pas : des murs de blocs repartis sur tout le circuit font 800 m de large pour 9 m de haut.)"""
    if re.search(r'road', name, re.I):
        return True
    n = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
    area = np.linalg.norm(n, axis=1)
    if not area.sum():
        return True
    return float(area[np.abs(n[:, 2]) > 0.9 * area].sum() / area.sum()) >= 0.85


def simplify_tris(T, cell):
    """Collision simplifiee par regroupement des sommets sur une grille de cell pouces (sommet = moyenne de sa
    cellule), triangles devenus degeneres ou en double retires. Les murs de briques / blocs perdent leurs details
    (relief des briques, chanfreins) mais gardent leur forme a cell / 2 pres."""
    V = T.reshape(-1, 3)
    uk, inv = np.unique(np.floor(V / cell).astype(np.int64), axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    rep = np.zeros((len(uk), 3))
    np.add.at(rep, inv, V)
    rep /= np.bincount(inv, minlength=len(uk))[:, None]
    F = inv.reshape(-1, 3)
    F = F[(F[:, 0] != F[:, 1]) & (F[:, 1] != F[:, 2]) & (F[:, 0] != F[:, 2])]
    _, first = np.unique(np.sort(F, axis=1), axis=0, return_index=True)
    P = rep[F[np.sort(first)]]
    return P[np.linalg.norm(np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]), axis=1) > 1e-2]


def subdivide_array(T, max_edge=MAX_COLLISION_EDGE):
    """subdivide_tri sur un tableau (n, 3, 3) : seuls les triangles trop grands passent par le decoupage."""
    edges = np.linalg.norm(T - T[:, [1, 2, 0]], axis=2).max(1)
    big = edges > max_edge
    if not big.any():
        return T
    parts = [np.asarray(subdivide_tri(t), np.float64) for t in T[big]]
    return np.concatenate([T[~big]] + parts)


COARSE_DIV, COARSE_MIN, COARSE_MAX = 6.0, 0.5 * 39.37, 6 * 39.37   # collision des objets semes (pouces)
# 2026-11-07 : T901 plantait au chargement (journal shadPS4 : « OOM ... GlobalChunk », collision de 20 Mo,
# 1 125 896 triangles ; les pistes du jeu : moins de 0,5 Mo). Les objets de decor loin de la piste n'ont plus de
# collision (aucun kart ne les touche) et tout le decor (pas seulement les objets semes) est simplifie comme eux.
DECOR_COLLISION_REACH = 100 * 39.37      # po : objet dont la boite est plus loin que ca de tout trace de course
COLLISION_BUDGET = 300_000               # au-dela : avertissement (collision lourde, risque de manque de memoire)
# feuillage en surface « auto » : sans collision (un type de sol choisi a la main la garde)
FOLIAGE_RE = re.compile(r'foliage|grass|vine|fern|flower|bush|leaf|leaves|ivy|weed|reed', re.I)


def race_point_grid(track, cell=100 * 39.37):
    """Points des traces de course (splines de position et d'IA, tous les ~2 m), ranges par cases (x, y) de `cell` po :
    {(i, j): tableau (n, 2)}. None si la piste n'a pas de trace lisible (alors rien n'est retire)."""
    try:
        splines = load_track(track)['splines']
    except Exception:  # noqa: BLE001
        return None
    pts = []
    for s in splines:
        P = np.asarray([p[:2] for p in s.get('control_points') or []], np.float64)
        if len(P) < 2:
            continue
        for a, b in zip(P[:-1], P[1:]):
            n = max(1, int(np.linalg.norm(b - a) // 80))
            pts.append(a + (b - a) * (np.arange(n)[:, None] / n))
        pts.append(P[-1:])
    if not pts:
        return None
    P = np.concatenate(pts)
    grid = defaultdict(list)
    for (i, j), p in zip(np.floor(P / cell).astype(np.int64).tolist(), P):
        grid[(i, j)].append(p)
    return {'cell': cell, 'cells': {k: np.asarray(v) for k, v in grid.items()}}


def far_from_race(G, T, reach=DECOR_COLLISION_REACH):
    """La boite (x, y) des triangles T est-elle a plus de `reach` po de tout point des traces ?"""
    if G is None or not len(T):
        return False
    V = T.reshape(-1, 3)
    lo, hi = V[:, :2].min(0), V[:, :2].max(0)
    c = G['cell']
    i0, j0 = np.floor((lo - reach) / c).astype(int)
    i1, j1 = np.floor((hi + reach) / c).astype(int)
    for i in range(i0, i1 + 1):
        for j in range(j0, j1 + 1):
            P = G['cells'].get((i, j))
            if P is None:
                continue
            d = np.hypot(np.maximum(0, np.maximum(lo[0] - P[:, 0], P[:, 0] - hi[0])),
                         np.maximum(0, np.maximum(lo[1] - P[:, 1], P[:, 1] - hi[1])))
            if d.min() <= reach:
                return False
    return True


def add_custom_collision(ge, track, customs, mesh_index=None):
    """Collision des modeles importes (leur maillage, par surface) ajoutee au sol ; retourne (nb de triangles,
    noms des decors de fond ignores, nb de triangles avant simplification). Les grands triangles sont decoupes
    (MAX_COLLISION_EDGE). Les decors de fond en surface « auto » n'ont pas de collision (montagnes de 70 km : des
    centaines de milliers de triangles, la collision ne pouvait plus etre encodee et l'editeur devenait tres lent).
    « Alleger la map » : murs et decors (pas les surfaces de roulage) simplifies (light_settings)."""
    cell = float(light_settings(track).get('collision_cell') or 0)
    by_surface = defaultdict(list)
    objs = []
    for art, info, cur in progress.items(customs, 'collision : modèle importé {i} / {n}', 0.0, 0.4):
        if info.get('surface', 'auto') == 'none':                               # feuillage...
            continue
        T = object_world_array(track, cur)
        T = T[np.linalg.norm(np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]), axis=1) > 1e-2]   # sans degeneres
        # sol, route, murs de la Creation (« Createur_... ») : surfaces de roulage, jamais allegees ni retirees ;
        # tout autre objet (semis, bibliotheque, decor auto, modele importe) : collision grossiere
        model_name = os.path.basename(str(cur.get('model') or ''))
        creator_ground = model_name.startswith('Createur_')
        if not creator_ground and info.get('surface', 'auto') == 'auto' and FOLIAGE_RE.search(model_name):
            continue                                     # herbes, lianes, buissons : les karts passent au travers
        coarse = not creator_ground
        objs.append((cur['name'], info.get('surface', 'auto'), coarse, T, info.get('phys'), creator_ground))
    skipped = _background_objects(track, [(o[0], o[3]) for o in objs if o[1] == 'auto'])
    reach = float(light_settings(track).get('decor_reach', 100) or 0) * 39.37    # m -> po ; 0 : jamais retiree
    G = race_point_grid(track) if reach > 0 else None
    far = 0
    n_before = n_after = 0
    for name, surf, coarse, T, phys, keep in progress.items(objs, 'collision : découpage {i} / {n}', 0.4, 1.0):
        if name in skipped or not len(T):
            continue
        if not keep and far_from_race(G, T, reach):             # loin de la piste : aucun kart ne le touche
            far += 1
            n_before += len(T)
            continue
        n_before += len(T)
        c = cell
        if coarse:                                       # objet seme : grille a 1/COARSE_DIV de sa taille
            ext = float((T.reshape(-1, 3).max(0) - T.reshape(-1, 3).min(0)).max())
            c = max(c, min(COARSE_MAX, max(COARSE_MIN, ext / COARSE_DIV)))
        if c > 0 and not is_flat(name, T):
            T = simplify_tris(T, c)
        n_after += len(T)
        if not len(T):
            continue
        T = subdivide_array(T)
        if surf == 'auto':
            P = T.reshape(-1, 3)
            surf = ge.surface_under(P.min(0).tolist(), P.max(0).tolist())
        by_surface[custom_surface_value(int(surf), phys)].append(T)     # vitesse / glissade propres : type ajoute

    n_custom = 0
    for surf, parts in by_surface.items():
        T = np.concatenate(parts)
        ge.add_world_prims(T, surf, mesh_index)
        n_custom += len(T)
    return n_custom, sorted(skipped), (n_before, n_after, far, n_custom)


def _skipped_note(skipped, counts=(0, 0)):
    n_before, n_after, far, total = (tuple(counts) + (0, 0))[:4]
    return ((f' ; sans collision (decor de fond) : {", ".join(skipped[:6])}' + (' ...' if len(skipped) > 6 else '')
             if skipped else '')
            + (f' ; {far} objet(s) loin de la piste sans collision' if far else '')
            + (f' ; collision allegee : {n_before} -> {n_after} triangles' if n_after < n_before else '')
            + (f' ; ATTENTION collision lourde ({total} triangles, au-dela de {COLLISION_BUDGET} : le jeu peut manquer de '
               f'memoire au chargement) : retire des objets proches de la piste ou passe-les « Sans collision »'
               if total > COLLISION_BUDGET else ''))


# -- nouvelle map : retrait de l'ancien sol / de l'ancien decor ----------------------------------
def newmap_path(track):
    return os.path.join(OUT_DIR, f'{track}_newmap.json')


def newmap_settings(track):
    """{'strip_ground': bool, 'strip_art': [fichiers _Art dont tous les objets d'origine sont retires]}."""
    p = newmap_path(track)
    return json.load(open(p)) if os.path.exists(p) else {}


_owner_cache = {}


def collision_owners(track):
    """{instance du compound: (fichier _Art, nom de l'entite)} : le jeu n'active une instance de la collision
    statique que si l'entite qui la porte (composant CStaticCollisionComponentData) est chargee.
    StaticCollision_<piste>.igz : table de hachage cle u64 (fnv1a(nom du fichier _Art) << 32 | hash du nom de
    l'entite, celui de la liste des noms racine) -> instance u16."""
    if track not in _owner_cache:
        sc = IgzFile(pak_tool.read_latest(ARCHIVES, f'maps/Octane/{track}/StaticCollision_{track}.igz',
                                          track_pak(track))[0])
        tbl = next(o for o, t in sc.objects.items() if t == 'CStaticCollisionHashInstanceIdHashTable')
        vd, kd, cap = sc.deref(tbl + 0x18), sc.deref(tbl + 0x28), sc.u32(tbl + 0x20) // 8
        keys = {}
        for i in range(cap):
            k = sc.u64(kd + i * 8)
            if k != 0xFAFAFAFAFAFAFAFA:
                lo = sc._loc(vd + i * 2)
                keys[k] = struct.unpack_from('<H', *lo)[0]
        out = {}
        for art in art_files(track):
            fh = pak_tool.fnv1a_lower(os.path.basename(art)[:-4])
            z = IgzFile(pak_tool.read_latest(ARCHIVES, art, track_pak(track))[0])
            cnt, _, data = z.list_info(z.names_offset)
            for i, (name, _) in enumerate(z.root_objects()[:cnt]):
                inst = keys.get(fh << 32 | z.u32(data + i * 16 + 8))
                if inst is not None and name:
                    out[inst] = (art, name)
        _owner_cache[track] = out
    return _owner_cache[track]


def ground_owner(track):
    """(fichier _Art, nom) de l'entite qui porte le maillage de sol principal (le plus grand, celui qui recoit les
    triangles des modeles importes) : Crash Cove = Art_Core / RaceTrack_Collision (instance 29)."""
    pf = Packfile(pak_tool.read_latest(ARCHIVES, collision_file(track), track_pak(track))[0])
    comp = next(o for o, c in pf.objects.items() if c == 'hknpStaticCompoundShape')
    io_, n = pf.array(comp + 0x60)
    best, size = None, -1
    for i in range(n):
        shape = pf.ptr(io_ + i * 128 + 0x50)
        if pf.objects.get(shape) == 'hknpCompressedMeshShape':
            np_ = pf.array(pf.ptr(shape + 0x58) + 0x60)[1]
            if np_ > size:
                best, size = i, np_
    return collision_owners(track).get(best)


def collision_custom_only(track, hk, customs, copies, orphan):
    """Collision = SEULEMENT les modeles importes : toutes les primitives du sol d'origine retirees, toutes les
    instances du compound desactivees sauf celle du maillage qui recoit les triangles importes."""
    ge = GroundEditor(hk)
    target = max(range(len(ge.meshes)), key=lambda i: len(ge.meshes[i]['mesh'].prims))
    n_orig = 0
    for mi, m in enumerate(ge.meshes):
        ge.delete([(mi, pi) for pi in range(len(m['mesh'].prims))])
        n_orig += len(m['mesh'].prims)
    with progress.span(0.05, 0.4):
        n_custom, skipped, counts = add_custom_collision(ge, track, customs, target)
    keep = ge.meshes[target]['instance']
    n_inst = ge.instance_count()
    # diagnostic (newmap.json : "disable_instances": false) : instances laissees actives, seuls les maillages vides
    disable = newmap_settings(track).get('disable_instances', True)
    for i in range(n_inst):
        if i != keep and disable:
            ge.disable_instance(i)
    with progress.span(0.4, 1.0, 'encodage de la collision'):
        out = ge.to_bytes()
    p = saved_path(collision_file(track))
    open(p, 'wb').write(out)
    return (f'collision « nouvelle map » : {n_orig} primitive(s) du sol d\'origine retirees, '
            f'{n_inst - 1 if disable else 0} instance(s) desactivee(s), {n_custom} triangle(s) des modeles importes'
            + (f' ; {len(copies) + orphan} copie(s) d\'objets d\'origine sans collision' if copies or orphan else '')
            + _skipped_note(skipped, counts))


# Collision differee (2026-11-10) : recalculer la collision apres chaque modification (ajout, couleur, type de sol...)
# prenait ~2 min sur une grande map (T907). Les modifications marquent seulement la collision « en retard » ; elle est
# recalculee une fois, a « Enregistrer », et de toute facon avant tout ce qui la lit (installation, verification,
# parcours, export, poids).
DEFERRED_NOTE = 'collision : recalculée au prochain « Enregistrer »'


def _collision_stale_path(track):
    return os.path.join(OUT_DIR, f'{track}_collision_stale')


def defer_collision(track):
    """Marque la collision a recalculer (au prochain enregistrement). -> note pour le rapport."""
    os.makedirs(OUT_DIR, exist_ok=True)
    open(_collision_stale_path(track), 'w').write('1')
    return DEFERRED_NOTE


def collision_pending(track):
    return os.path.exists(_collision_stale_path(track))


def ensure_collision(track):
    """Collision a jour avant de la lire : recalculee seulement si une modification l'a laissee en retard."""
    return sync_collision(track) if collision_pending(track) else None


def _collision_done(track):
    try:
        os.remove(_collision_stale_path(track))
    except OSError:
        pass


def sync_collision(track):
    """Reconstruit la collision a partir de l'original pour suivre le decor enregistre :
      * triangles du sol qui collent au modele d'un objet deplace -> meme deplacement ; objet supprime -> retires ;
      * instance propre d'un objet (marqueur, pilier...) -> nouvelle transformation / desactivee.
    Les copies d'objets n'ont pas encore de collision."""
    logical = collision_file(track)
    progress.step('collision : lecture du décor', 0.0)
    hk, _ = pak_tool.read_latest(ARCHIVES, logical, track_pak(track))
    originals, current = [], {}
    for art in art_files(track):
        od, _ = pak_tool.read_latest(ARCHIVES, art, track_pak(track))
        originals += [(art, o) for o in DecorFile(od).objects()]
        cd, _ = base_file(track, art)
        current[art] = {o['id']: o for o in DecorFile(cd).objects()}
    changed = []                                     # (fichier, original, courant ou None)
    for art, o in originals:
        cur = current[art].get(o['id'])
        if cur is None or any(abs(a - b) > 1e-4 for a, b in zip(cur['pos'] + cur['euler'] + cur['scale'],
                                                                o['pos'] + o['euler'] + o['scale'])):
            changed.append((art, o, cur))
    # copies (objets absents des fichiers d'origine) -> objet d'origine via les liens memorises
    links = load_links(track)
    orig_by_id = {(art, o['id']): o for art, o in originals}
    copies, customs, orphan = [], [], 0
    for art, objs in current.items():
        for oid, cur in objs.items():
            if (art, oid) in orig_by_id:
                continue
            src = links.get(art, {}).get(str(oid))
            if isinstance(src, dict) and 'custom' in src:
                customs.append((art, src, cur))                  # objet importe : collision = son modele
            elif src is not None and (art, int(src)) in orig_by_id:
                copies.append((art, orig_by_id[(art, int(src))], cur))
            else:
                orphan += 1
    nm = newmap_settings(track)
    stripped = set(nm.get('strip_art') or [])
    if stripped:
        # objets d'origine retires en bloc (nouvelle map) : leur sol lie n'est pas recherche un par un (milliers
        # d'objets) ; il disparait avec « retirer l'ancien sol »
        changed = [c for c in changed if c[0] not in stripped]
    # meme decor que lors du dernier calcul (ex. seule une plaque de booster ou un objet sans collision a bouge) et
    # fichier de collision intact : rien a refaire (~20 s sur une map importee de 200 000 triangles)
    key = _collision_key(track, nm, changed, copies, customs, orphan)
    memo = _collision_memo(track)
    if memo.get('key') == key and memo.get('out') == _saved_md5(saved_path(logical)):
        _collision_done(track)
        return memo['report'] + ' (inchangee)'
    if nm.get('strip_ground'):
        report = collision_custom_only(track, hk, customs, copies, orphan)
    else:
        report = _sync_ground(track, logical, hk, originals, changed, copies, customs, orphan)
    json.dump({'key': key, 'out': _saved_md5(saved_path(logical)), 'report': report}, open(_collision_memo_path(track), 'w'))
    _collision_done(track)
    return report


COLLISION_CODE_VERSION = 3     # change -> collision recalculee meme si le decor n'a pas change (3 : decor loin retire)


def _collision_memo_path(track):
    return os.path.join(OUT_DIR, f'{track}_collision_memo.json')


def _collision_memo(track):
    try:
        return json.load(open(_collision_memo_path(track)))
    except (OSError, ValueError):
        return {}


def _saved_md5(p):
    import hashlib
    return hashlib.md5(open(p, 'rb').read()).hexdigest() if os.path.exists(p) else None


def _collision_key(track, nm, changed, copies, customs, orphan):
    """Empreinte de tout ce dont depend la collision calculee."""
    import hashlib
    pose = lambda o: None if o is None else [o.get('model'), [round(v, 4) for v in o['pos'] + o['euler'] + o['scale']]]
    data = {'v': COLLISION_CODE_VERSION, 'newmap': nm, 'light': light_settings(track), 'orphan': orphan,
            'changed': [[a, o['id'], pose(c)] for a, o, c in changed],
            'copies': [[a, o['id'], pose(c)] for a, o, c in copies],
            'customs': [[a, s, c['name'], pose(c)] for a, s, c in customs]}
    return hashlib.md5(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def _sync_ground(track, logical, hk, originals, changed, copies, customs, orphan):
    """Sol d'origine garde : triangles lies aux objets deplaces / supprimes / copies, modeles importes ajoutes."""
    matches = instance_matches(CollisionFile(hk), originals)
    own = defaultdict(set)
    for i, (art, o) in matches.items():
        own[(art, o['id'])].add(i)
    ge = GroundEditor(hk)
    # 1) selections calculees sur le sol d'origine, puis copies (depuis l'etat d'origine), deplacements, suppressions
    sels = {}
    for art, o, _ in changed + copies:
        if (art, o['id']) not in sels:
            sels[(art, o['id'])] = linked_ground(ge, track, o, own[(art, o['id'])])
    snap = ge.snapshot({s for v in sels.values() for s in v})
    to_mat = lambda x: object_matrix(x['pos'], x['euler'], x['scale'])
    n_copied = 0
    for art, o, cur in copies:
        delta = mat_mul(to_mat(cur), mat_inv_rigid_scale(to_mat(o)))
        ge.copy(sels[(art, o['id'])], delta, source=snap)
        n_copied += len(sels[(art, o['id'])])
    with progress.span(0.1, 0.4):
        n_custom, skipped, counts = add_custom_collision(ge, track, customs)
    taken, n_moved_tris, n_deleted_tris = set(), 0, 0
    for art, o, cur in changed:
        sel = [s for s in sels[(art, o['id'])] if s not in taken]
        taken.update(sel)
        if cur is None:
            ge.delete(sel)
            n_deleted_tris += len(sel)
        else:
            ge.transform(sel, mat_mul(to_mat(cur), mat_inv_rigid_scale(to_mat(o))))
            n_moved_tris += len(sel)
    # 2) instances propres : deplacees / desactivees / ajoutees pour les copies (arbre du compound reconstruit)
    moved = disabled = added = 0
    changed_ids = {(art, o['id']): cur for art, o, cur in changed}
    for i, (art, o) in matches.items():
        if (art, o['id']) in changed_ids:
            cur = changed_ids[(art, o['id'])]
            if cur is None:
                ge.disable_instance(i)
                disabled += 1
            else:
                ge.set_instance(i, cur['pos'], cur['euler'], cur['scale'])
                moved += 1
    for art, o, cur in copies:
        for i in sorted(own[(art, o['id'])]):
            ge.add_instance(i, cur['pos'], cur['euler'], cur['scale'])
            added += 1
    with progress.span(0.4, 1.0, 'encodage de la collision'):
        out = ge.to_bytes()
    p = saved_path(logical)
    if out != hk:
        open(p, 'wb').write(out)
    elif os.path.exists(p):
        os.remove(p)
    return (f'collision : {n_moved_tris} primitive(s) du sol deplacee(s), {n_deleted_tris} retiree(s), '
            f'{n_copied} copiee(s), {n_custom} triangle(s) de modeles importes ; '
            f'instances : {moved} deplacee(s), {disabled} desactivee(s), {added} ajoutee(s)'
            + (f' ; {orphan} copie(s) sans source connue (pas de collision)' if orphan else '')
            + _skipped_note(skipped, counts))


def decor_collision_preview(track, logical, obj_id):
    """Collision liee a un objet (repere local de l'objet, pouces) : pour l'apercu dans l'editeur."""
    od, _ = pak_tool.read_latest(ARCHIVES, logical, track_pak(track))
    orig_objs = {x['id']: x for x in DecorFile(od).objects()}
    o = orig_objs.get(obj_id)
    if o is None:                                     # copie enregistree : objet source via les liens
        src = load_links(track).get(logical, {}).get(str(obj_id))
        if isinstance(src, dict) and 'custom' in src:  # objet importe : sa collision est son propre modele
            if src.get('surface') == 'none':
                return {'tris': [], 'note': 'modele importe sans collision'}
            pos, idx = model_or_wall_mesh(track, src['custom'])
            return {'tris': [round(c, 2) for i in idx for c in pos[i * 3:i * 3 + 3]],
                    'note': f"{'mur invisible' if wall_mesh(track, src['custom']) else 'modele importe'} : "
                            f'{len(idx) // 3} triangle(s) de collision (surface '
                            f'{src.get("surface", "auto")})'}
        o = orig_objs.get(int(src)) if src is not None else None
    if o is None:
        return {'tris': [], 'note': 'copie sans source connue (enregistree avant le suivi des copies) : pas de collision'}
    hk, _ = pak_tool.read_latest(ARCHIVES, collision_file(track), track_pak(track))
    ge = GroundEditor(hk)
    originals = [(art, x) for art in art_files(track)
                 for x in DecorFile(pak_tool.read_latest(ARCHIVES, art, track_pak(track))[0]).objects()]
    matches = instance_matches(CollisionFile(hk), originals)
    own = {i for i, (art, x) in matches.items() if art == logical and x['id'] == o['id']}
    inv = mat_inv_rigid_scale(object_matrix(o['pos'], o['euler'], o['scale']))
    tris = []
    for mi, pi in linked_ground(ge, track, o, own):
        m = ge.meshes[mi]
        for tri in m['mesh'].prims[pi].triangles():
            tris += [round(c, 2) for v in tri for c in apply(inv, apply(m['to_world'], v))]
    return {'tris': tris, 'own_instances': sorted(own),
            'note': f'{len(tris) // 9} triangle(s) du sol lies, {len(own)} instance(s) propre(s)'}


_extra_maps_cache = {}


def extra_decor_files(track):
    """Fichiers de carte du manifeste, hors _Art, qui placent des modeles (ex. _Lighting : geometrie lointaine)."""
    if track not in _extra_maps_cache:
        tp, arts, out = track_pak(track), {a.lower() for a in art_files(track)}, []
        rows = pkg_manifest.entries(pak_tool.read_latest(ARCHIVES, pkg_manifest.manifest_logical(track), tp)[0])
        for t, p in rows:
            if not p.startswith('maps/') or p in arts:
                continue
            try:
                data, _ = pak_tool.read_latest(ARCHIVES, p, tp)
                if DecorFile(data).objects():
                    out.append(p)
            except Exception:  # noqa: BLE001 - fichier absent ou sans entites : ignore
                continue
        _extra_maps_cache[track] = out
    return _extra_maps_cache[track]


def export_obj(req):
    """Reference Blender : req = {track, collision: bool, splines: bool, decor: 'none'|'boxes'|'full',
    files: [fichiers _Art] (defaut : tous), extra: bool (autres fichiers de carte avec des modeles, defaut oui),
    up: 'y'|'z'}. Ecrit out/blender/<Piste>_reference.obj + .mtl au fil de l'eau (versions enregistrees de la
    collision et du decor si elles existent) et retourne les chemins + statistiques."""
    track = req['track']
    up = 'z' if req.get('up') == 'z' else 'y'
    out_dir = os.path.join(os.path.dirname(OUT_DIR), 'blender')
    os.makedirs(out_dir, exist_ok=True)
    base = f'{track}_reference'
    obj_path, mtl_path = os.path.join(out_dir, f'{base}.obj'), os.path.join(out_dir, f'{base}.mtl')
    with open(obj_path, 'w', newline='\n') as f:
        f.write(f'# Reference {track} pour Blender : metres, {up.upper()} vers le haut '
                f'(importer avec « Up : {up.upper()} », comme l\'axe vertical {up.upper()} de l\'import de l\'editeur)\n')
        w = obj_export.ObjWriter(f, f'{base}.mtl', up)
        _export_layers(track, req, w)
    with open(mtl_path, 'w', newline='\n') as f:
        f.write(w.mtl_text())
    return {'obj': obj_path, 'mtl': mtl_path, 'size': os.path.getsize(obj_path), **w.stats}


def _export_layers(track, req, w):
    if req.get('collision', True):
        ensure_collision(track)
        ge = GroundEditor(base_file(track, collision_file(track))[0])
        by_surface = defaultdict(list)
        for mi, m in enumerate(ge.meshes):
            for p in m['mesh'].prims:
                by_surface[p.value] += [tuple(apply(m['to_world'], v) for v in t) for t in p.triangles()]
        for value in sorted(by_surface):
            w.add_mesh(f'Collision_surface_{value}', f'Collision_{value}', obj_export.surface_color(value), by_surface[value])
    if req.get('splines', True):
        for s in load_track(track)['splines']:
            ai = 'ai' in (s.get('kind') or s['name']).lower()
            w.add_polyline(f"Spline_{s['name']}", 'Spline_IA' if ai else 'Spline_course',
                           (1.0, 0.55, 0.1) if ai else (0.1, 0.8, 1.0), s['control_points'])
    mode = req.get('decor', 'full')
    if mode == 'none':
        return
    files = list(req['files'] if req.get('files') is not None else art_files(track))
    mesh_cache = {}
    if req.get('extra', True):
        files += [p for p in extra_decor_files(track) if p not in files]
    for art in files:
        label = os.path.basename(art)[len(track) + 1:-4] or os.path.basename(art)[:-4]
        data = base_file(track, art)[0] if art in art_files(track) else pak_tool.read_latest(ARCHIVES, art, track_pak(track))[0]
        for o in DecorFile(data).objects():
            logical = model_logical_path(o['model'])
            if logical not in mesh_cache:
                try:
                    mesh_cache[logical] = model_mesh(model_bytes(track, logical))
                except Exception:  # noqa: BLE001 - modele illisible : ignore
                    mesh_cache[logical] = ([], [])
            pos, idx = mesh_cache[logical]
            if not pos:
                continue
            name = f"Decor_{label}_{o['name'] or o['id']}"
            M = object_matrix(o['pos'], o['euler'], o['scale'])
            if mode == 'full' or logical.startswith(f'models/{CUSTOM_DIR}/'):   # modeles importes : toujours complets
                w.add_indexed(name, 'Decor', (0.6, 0.6, 0.6), [apply(M, pos[k:k + 3]) for k in range(0, len(pos), 3)], idx)
            else:
                lo = [min(pos[k::3]) for k in range(3)]
                hi = [max(pos[k::3]) for k in range(3)]
                w.add_mesh(name, 'Decor_boite', (0.6, 0.6, 0.6),
                           [tuple(apply(M, v) for v in t) for t in obj_export.box_tris(lo, hi)])


# -- mini-carte ---------------------------------------------------------------------------------
def minimap_texture_logical(track):
    """Texture de la mini-carte de course (manifeste : ...!ui!octane!minimaps!..._race_...), casse de l'archive."""
    rows = pkg_manifest.entries(pak_tool.read_latest(ARCHIVES, pkg_manifest.manifest_logical(track), track_pak(track))[0])
    p = next(p for t, p in rows if t == 'texture' and 'minimaps' in p and '_race_' in p)
    return _logical_case(track, p)


def race_chain(tr):
    """[(transition, spline de position qui la suit)] dans l'ordre de course depuis la ligne d'arrivee."""
    by = {s['name']: s for s in tr['splines'] if s['kind'] == 'position_paths'}
    t = next((x for x in tr['transitions'] if x['increment_lap']), None)
    out, seen = [], set()
    while t and t['name'] not in seen:
        seen.add(t['name'])
        nxt = [n for n in t['next_position'] if n in by]
        if not nxt:
            break
        out.append((t, by[nxt[0]]))
        # transition de passage (de la spline vers elle-meme, Coco Park Spline_Transition_002) : pas une section
        cands = [x for x in tr['transitions'] if nxt[0] in x['previous_position'] and x['name'] not in seen]
        cands.sort(key=lambda x: bool(set(x['next_position']) & set(x['previous_position'])))
        t = cands[0] if cands else None
    return out


def race_path_points(track):
    """Trace de course enregistre : splines de position dans l'ordre depuis la ligne d'arrivee, raccordees."""
    tr = load_track(track)
    out = [s['control_points'] for _, s in race_chain(tr)]
    if not out:
        out = [s['control_points'] for s in tr['splines'] if s['kind'] == 'position_paths']
    path = powerup.chain_paths(out)
    return [list(p) for p in ai_gen.catmull_rom(path, 300.0)], tr


# -- nom et images de la piste dans les menus ---------------------------------------------------
MENU_ARCHIVE_PREFIXES = ('juicedomain', 'chunkinfos', 'update', 'loadingscreen', 'permanent')


def menu_logicals(track):
    """Fichiers du nom (par langue) et des images de menu de la piste : {cle: chemin logique}."""
    import menu_assets
    out = {f'name_{lg}': menu_assets.name_file(track, lg) for lg in menu_assets.LANGS}
    out.update({f'image_{k}': menu_image_logical(track, k) for k in menu_assets.IMAGES})
    return out


_menu_image_cache = {}


def menu_image_logical(track, key):
    """Texture d'interface de la piste : son nom n'est pas toujours celui de la piste (Roo's Tubes « roostube »,
    N. Gin Labs « nginlab », Oxide Station « oxydestation » pour le fond mais « oxidestation » pour la vignette) :
    nom le plus proche parmi les textures de ce type des archives de menu ; sinon le nom deduit de la piste."""
    import difflib
    import menu_assets
    if key in menu_assets.OWN_IMAGES and menu_image_source(track):
        return menu_assets.own_image_file(track, key)            # piste creee : ses textures (custom_category)
    if (track, key) not in _menu_image_cache:
        want = menu_assets.image_file(track, key)
        _menu_archives_index()
        prefix = want.lower().rsplit(menu_assets.slug(track), 1)[0]
        best, score = want, 0.0
        for keys in _menu_arc_cache.values():
            for k in keys:
                if not k.startswith(prefix):
                    continue
                suffix = k[len(prefix):].split('`', 1)[0]
                if suffix.startswith('pattern'):
                    continue                                  # motifs de fond, pas l'image d'une piste
                r = difflib.SequenceMatcher(None, suffix, menu_assets.slug(track)).ratio()
                if r > score:
                    best, score = k, r
        _menu_image_cache[(track, key)] = best if score >= 0.8 else want
    return _menu_image_cache[(track, key)]


_menu_arc_cache = {}


def _menu_archives_index():
    """{archive: noms} des archives de menu ET de toutes les pistes (l'index n'etait construit qu'avec l'archive
    de la premiere piste ouverte : les images d'une autre piste, rangees dans son archive, n'etaient jamais trouvees)."""
    if not _menu_arc_cache:
        tracks = {p.lower() for p in library.track_paks(ARCHIVES)}
        for p in sorted(os.listdir(ARCHIVES)):
            low = p.lower()
            if low.endswith('.pak') and low != pak_tool.LAYER_ARCHIVE and (low.startswith(MENU_ARCHIVE_PREFIXES) or low in tracks):
                try:
                    _menu_arc_cache[p] = pak_tool.cached_archive(os.path.join(ARCHIVES, p))[1].keys()
                except Exception:  # noqa: BLE001 - archive illisible : ignoree
                    continue


def menu_archives(track, logical):
    """Archives qui contiennent ce fichier (toutes sont patchees a l'installation) : [chemins], la plus
    prioritaire d'abord (update2, update, puis les autres)."""
    if _own_menu_image(track, logical):
        return [os.path.join(ARCHIVES, custom_category.ARCHIVE)]    # mise dans update2 a chaque reecriture
    _menu_archives_index()
    order = lambda p: (p not in pak_tool.UPDATE_ARCHIVES, pak_tool.UPDATE_ARCHIVES.index(p) if p in pak_tool.UPDATE_ARCHIVES else 0, p)
    return [os.path.join(ARCHIVES, p) for p in sorted(_menu_arc_cache, key=order) if logical.lower() in _menu_arc_cache[p]]


def _own_menu_image(track, logical):
    """Cle ('background' / 'icon') si logical est une image a elle d'une piste creee, sinon None."""
    if not menu_image_source(track):
        return None
    return next((k for k in menu_assets.OWN_IMAGES if menu_assets.own_image_file(track, k).lower() == logical.lower()), None)


def _menu_original(track, logical):
    """(octets d'origine, nom logique avec la casse de l'archive) ou (None, None). Image a elle d'une piste creee :
    l'origine est l'image du jeu de sa source (copiee telle quelle dans update2 tant qu'elle n'est pas modifiee)."""
    k = _own_menu_image(track, logical)
    if k:
        src = menu_image_source(track)
        data, _ = _menu_original(src, menu_image_logical(src, k))
        return (data, menu_assets.own_image_file(track, k)) if data is not None else (None, None)
    arcs = menu_archives(track, logical)
    if not arcs:
        return None, None
    base = next((a for a in arcs if os.path.basename(a) not in pak_tool.UPDATE_ARCHIVES), arcs[0])
    try:
        data, _ = pak_tool.read_latest(ARCHIVES, logical, os.path.basename(base))
    except KeyError:                     # piste creee (track_clone) : son nom n'existe que dans l'update2 installe
        data, _ = pak_tool.read_latest(ARCHIVES, logical, os.path.basename(base), original=False)
    return data, _archive_case(os.path.basename(arcs[0]), logical)


def menu_image_source(track):
    """Piste dont une piste CREEE (onglet Menu) affiche les images de menu : sa source enregistree a la copie
    (custom_category, 'source' : Crash Cove), sinon None. Le zoneinfo copie garde LevelIcon_CrashCove etc."""
    for t in (custom_category.read_state(ARCHIVES) or {}).get('tracks', []):
        if t['id'] == track:
            return t.get('images_from') or t.get('source') or NEW_TRACK_SOURCE
    return None


def own_race_icon_files(track):
    """Piste creee : l'icone de la piste en course (<Piste>_Minimap_materials::<Piste>_Icon, visee par le zoneInfo)
    utilise la vignette du menu de la source ; elle vise ici la vignette a elle (update2, custom_category), comme les
    pistes ajoutees par les mises a jour (Hyper Spaceway : sa vignette dans son manifeste).
    Mini-carte : meme principe. L'image refaite par l'editeur part sous un nom PROPRE a la piste
    (« ..._minimaps_race_t901custommap ») au lieu de celui de la source (« ..._crashcove ») : deux pistes creees jouees
    a la suite avaient le meme fichier avec deux contenus (le jeu garde un nom = un contenu).
    -> ({nom logique: octets} pour l'archive de la piste, entrees du manifeste, {nom logique d'origine a ne PAS
    remplacer})."""
    if not menu_image_source(track):
        return {}, [], set()
    logical = f'materialinstances/ui/{track.lower()}_minimap_materials.igz'
    try:
        z = IgzFile(pak_tool.read_latest(ARCHIVES, logical, track_pak(track))[0])
    except KeyError:
        return {}, [], set()
    fo = next(o for o, (n, _) in z.fields_of('igGraphicsTexture').items() if n == '_imageHandle')
    files, entries, drop = {}, [], set()
    try:
        mm_logical = minimap_texture_logical(track)
    except StopIteration:
        mm_logical = None
    mm_saved = saved_path(mm_logical) if mm_logical else None
    for o, t in list(z.objects.items()):
        h = z.named_handle(z.u32(o + fo)) if t == 'igGraphicsTexture' else None
        if not h:
            continue
        if '_raceselect_ico_' in h[1]:
            tex = menu_assets.own_texture_name(h[1], track)
            entries.append(('texture', menu_assets.own_image_file(track, 'icon')))
        elif '!minimaps!octane_ui_minimaps_race_' in h[1].lower() and mm_saved and os.path.exists(mm_saved):
            tex = menu_assets.own_texture_name(h[1], track)
            own = f'textures/{tex}.igz'
            files[own] = open(mm_saved, 'rb').read()
            entries.append(('texture', own))
            drop.add(mm_logical.lower())
        else:
            continue
        struct.pack_into('<I', *z._loc(o + fo), 0x80000000 | z.ext_index(h[0], tex))
        z.add_tdep([(tex, 'textures:/' + tex + '.igz')])
    if not entries:
        return {}, [], set()
    files[_archive_case(track_pak(track), logical)] = z.to_bytes()
    return files, entries, drop


def menu_info(track):
    """Noms actuels (enregistres ou d'origine) par langue et apercus des images de menu."""
    import base64
    import menu_assets
    from PIL import Image
    files = menu_logicals(track)
    names, images = {}, {}
    for lg, label in menu_assets.LANGS.items():
        orig, logical = _menu_original(track, files[f'name_{lg}'])
        if orig is None:
            continue
        p = saved_path(logical)
        names[lg] = {'label': label, 'original': menu_assets.read_name(orig),
                     'name': menu_assets.read_name(open(p, 'rb').read() if os.path.exists(p) else orig)}
    for k, (label, _) in menu_assets.IMAGES.items():
        # piste creee : fond et vignette a elle (copies installees par custom_category) ; embleme de l'intro et
        # trace = ceux de sa source, partages (lecture seule ici : les modifier changerait aussi Crash Cove)
        source = menu_image_source(track) if k not in menu_assets.OWN_IMAGES else None
        orig, logical = _menu_original(track, files[f'image_{k}']) if not source else \
            _menu_original(source, menu_image_logical(source, k))
        if orig is None:
            continue
        p = saved_path(logical)
        data = open(p, 'rb').read() if os.path.exists(p) else orig
        rgba, _ = preview.decode_texture(data, 512)
        info = texture_build.texture_info(orig)
        buf = io.BytesIO()
        Image.fromarray(rgba[::-1]).save(buf, 'PNG')         # textures d'interface stockees de bas en haut (apply_menu)
        images[k] = {'label': label, 'size': [info['width'], info['height']], 'custom': os.path.exists(p),
                     'shared': source,
                     'preview': 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()}
    v = menu_video(track)
    return {'names': names, 'images': images, 'slug': menu_assets.slug(track), 'image_source': menu_image_source(track),
            'hide_video': hide_menu_video(track),
            'video': os.path.basename(v) if os.path.exists(v) or os.path.exists(v + VIDEO_OFF) else None}


def apply_menu(req):
    """req = {track, names: {langue: nom | null (origine)}, images: {cle: data URL | 'generate' (trace) | null
    (origine)}} : fichiers enregistres (installes dans toutes les archives qui les contiennent)."""
    import base64
    import menu_assets
    track, report = req['track'], []
    files = menu_logicals(track)
    if req.get('hide_video') is not None:
        st = menu_settings(track)
        if bool(st.get('hide_video')) != bool(req['hide_video']):
            st['hide_video'] = bool(req['hide_video'])
            os.makedirs(OUT_DIR, exist_ok=True)
            json.dump(st, open(menu_settings_path(track), 'w'))
            report.append('vidéo du menu : ' + ('mise de côté à l\'installation' if st['hide_video'] else 'gardée'))
    for lg, name in (req.get('names') or {}).items():
        orig, logical = _menu_original(track, files.get(f'name_{lg}', ''))
        if orig is None:
            continue
        p = saved_path(logical)
        if not name or name == menu_assets.read_name(orig):
            if os.path.exists(p):
                os.remove(p)
                report.append(f'nom ({lg}) : origine')
            continue
        open(p, 'wb').write(menu_assets.write_name(orig, name.strip()))
        report.append(f'nom ({lg}) : « {name.strip()} »')
    for k, val in progress.items((req.get('images') or {}).items(), 'image {i} / {n}', 0.1, 1.0):
        orig, logical = _menu_original(track, files.get(f'image_{k}', ''))
        if orig is None:
            continue
        p = saved_path(logical)
        if val is None:
            if os.path.exists(p):
                os.remove(p)
                report.append(f'{menu_assets.IMAGES[k][0]} : origine')
            continue
        info = texture_build.texture_info(orig)
        w, h = info['width'], info['height']
        if val == 'generate':
            path, _ = race_path_points(track)
            src = json.load(open(road_source_path(track))) if os.path.exists(road_source_path(track)) else \
                {'objects': imported_road_objects(track)}
            tris = road_tris(track, src) if src.get('objects') else None
            rgba = menu_assets.outline(w, path, tris)
        else:
            rgba = menu_assets.fit_image(base64.b64decode(val.split(',', 1)[-1]), w, h, cover=(k == 'background'))
        # textures d'interface stockees de bas en haut (verifie en jeu : ecrite de haut en bas, l'image etait a l'envers)
        open(p, 'wb').write(texture_build.build_bc3_image(orig, np.ascontiguousarray(rgba[::-1])))
        report.append(f'{menu_assets.IMAGES[k][0]} : ' + ('tracé généré' if val == 'generate' else 'image remplacée'))
    return {'report': report or ['aucun changement']}


VIDEO_OFF = '.ctrmod-off'      # video du menu mise de cote (renommee a cote d'elle, remise a la desinstallation)


def menu_settings_path(track):
    return os.path.join(OUT_DIR, f'{track}_menu.json')


def menu_settings(track):
    p = menu_settings_path(track)
    return json.load(open(p)) if os.path.exists(p) else {}


def menu_video(track):
    """Video Bink 2 du fond de l'ecran de choix de course (hors archives) : archives/octane_ui_race_select_<piste>.bk2."""
    return os.path.join(ARCHIVES, 'octane_ui_race_select_' + re.sub(r'^T\d+_', '', track).lower() + '.bk2')


def hide_menu_video(track):
    """La video du menu est mise de cote quand le fond de l'ecran de choix est personnalise (valide en jeu : sinon
    elle joue par-dessus l'image et la cache)."""
    return os.path.exists(saved_path(menu_logicals(track)['image_background']))


def set_menu_video(track, hidden):
    """Video du menu mise de cote (hidden) ou remise a sa place. -> texte ou None si rien n'a change."""
    v = menu_video(track)
    off = v + VIDEO_OFF
    if hidden and os.path.exists(v):
        if os.path.exists(off):             # deux copies (jeu reinstalle ?) : on ne supprime rien
            return f'ATTENTION : {os.path.basename(v)} et sa copie mise de côté existent toutes les deux : vidéo laissée'
        os.replace(v, off)
        return f'vidéo du menu mise de côté ({os.path.basename(v)})'
    if not hidden and os.path.exists(off):
        os.replace(off, v)
        return f'vidéo du menu remise ({os.path.basename(v)})'
    return None


def menu_saved(track):
    """[(nom logique avec casse, chemin enregistre)] des fichiers de menu modifies."""
    out = []
    for logical in menu_logicals(track).values():
        _, cased = _menu_original(track, logical)
        if cased and os.path.exists(saved_path(cased)):
            out.append((cased, saved_path(cased)))
    return out


# -- chutes et reapparitions automatiques -------------------------------------------------------
RESPAWN_AUTO = 'Respawn_waypoint_auto'
FALL_AUTO = 'Respawn_Trigger_auto'
FALL_TEMPLATE = 'Respawn_Trigger_Bridge'
DESIGN_ENTITY_TYPES = ('CPlayerStartEntity', 'CEntity', 'CGameEntity', 'igEntity')


def world_killz(track, original=False):
    """Plancher du monde (CWorldEntityData._killz) de la version enregistree (original : celle du jeu)."""
    logical = start_finish.main_map_file(track)
    data = pak_tool.read_latest(ARCHIVES, logical, track_pak(track))[0] if original else base_file(track, logical)[0]
    z = IgzFile(data)
    w = next((o for o, t in z.objects.items() if t == 'CWorldEntityData'), None)
    return struct.unpack_from('<f', *z._loc(w + 0x40))[0] if w is not None else KILL_Z


def scene_points(req):
    """Entites de la scene que l'editeur de course ne charge pas, pour « Changer l'echelle de la map » :
    req = {track, names (points de reapparition des splines de position)} -> {poses: {nom: {pos, yaw}} (points,
    zones de chute auto ; _Design ou _RaceSystem), killz}. Pas les cameras <nom>_camera : ce ne sont pas des
    entites, leur « position » +0x20 ecrasait le pointeur de leur nom (plantage en quittant la course)."""
    track = req['track']
    names = set(req.get('names') or [])
    poses = {}
    for logical in (race_file(track), start_finish.design_file(track)):
        try:
            data = base_file(track, logical)[0]
        except KeyError:
            continue
        roots = [n for n, _ in IgzFile(data).root_objects() if n]
        want = [n for n in roots if n in names or (n.startswith(FALL_AUTO) and n[len(FALL_AUTO):].isdigit())]
        poses.update(start_finish.read_entity_poses(data, want))
    return {'poses': poses, 'killz': world_killz(track)}


def set_world_killz(track, killz):
    """Plancher du monde (CWorldEntityData._killz) de la version enregistree."""
    logical = start_finish.main_map_file(track)
    z = IgzFile(base_file(track, logical)[0])
    w = next(o for o, t in z.objects.items() if t == 'CWorldEntityData')
    struct.pack_into('<f', *z._loc(w + _field(z, 'CWorldEntityData', '_killz')), float(killz))
    open(saved_path(logical), 'wb').write(z.to_bytes())


def _component(z, ent, type_name):
    """Composant d'une entite (table de composants de ses donnees) ou None."""
    data = z.deref(ent + 0x40)
    table = z.deref(data + 0x10) if data is not None else None
    for _, v in (z.hash_items(table) if table is not None else []):
        off = int(v['@ref'], 16) if isinstance(v, dict) and '@ref' in v else None
        if off is not None and z.objects.get(off) == type_name:
            return off
    return None


def _field(z, type_name, name):
    return next(o for o, (n, _) in z.fields_of(type_name).items() if n == name)


def _respawns_off_gaps(points, P, starts, end, ground, lift=50.0, reach_m=20):
    """Point de reapparition au-dessus d'une coupure plus etroite que l'ecart des points du trace (les deux voisins
    ont du sol : non marque « air ») : decale le long du trace, d'abord vers l'avant, jusqu'a avoir du sol juste
    dessous (T901 Boo Lake : Respawn_waypoint_auto038 entre deux morceaux de route, « sans sol dessous »)."""
    import falls
    S = falls.arc(P)

    def grounded(pos):
        h = ground.top(pos[0], pos[1], pos[2] + 300)
        return h is not None and pos[2] - h <= AIR + lift

    out = []
    for sec, pos, yaw, s in points:
        if not grounded(pos):
            for d in [k * sign for k in range(1, reach_m + 1) for sign in (1, -1)]:
                s2 = min(max(s + d * 39.37, starts[0]), end)
                pos2, yaw2 = falls.pose_at(P, S, s2, lift)
                if grounded(pos2):
                    sec = max(k for k in range(len(starts)) if starts[k] <= s2)
                    pos, yaw, s = pos2, yaw2, s2
                    break
        out.append((sec, pos, yaw, s))
    return sorted(out, key=lambda o: o[3])


def _falls_donor():
    """(IgzFile, {nom: objet}) du _Design d'origine de Crash Cove : modeles d'un point de reapparition et d'une zone de chute
    pour les pistes qui n'en ont pas dans leur _Design (memes objets que sur les pistes creees, valides en jeu)."""
    z = IgzFile(pak_tool.read_latest(ARCHIVES, start_finish.design_file(NEW_TRACK_SOURCE), track_pak(NEW_TRACK_SOURCE))[0])
    return z, {n: o for n, o in z.root_objects() if n}


def auto_falls(req):
    """Chutes et reapparitions d'apres le parcours ENREGISTRE : req = {track, spacing (m), killz (bool),
    zones (bool)}.
      * points de reapparition tous les ~spacing m, poses sur la route dans le sens de la course, rattaches a la
        section ou ils sont (les points d'origine sont repris, d'autres clones au besoin, jamais supprimes) ;
      * plancher du monde 30 m sous le point le plus bas du parcours (chute = reapparition rapide) ;
      * zones de chute (clones de Respawn_Trigger_Bridge) la ou il n'y a pas de sol a cote de la route, qui
        renvoient aux 3 points precedents. Les zones auto d'un calcul precedent sont reutilisees ou ecartees."""
    import falls
    track, report = req['track'], []
    tr = load_track(track)
    chain = race_chain(tr)
    if len(chain) < 1:
        raise ValueError('pas de parcours enregistre (ligne d\'arrivee reliee aux splines de position)')
    progress.step('tracé et sol', 0.05)
    path, _ = race_path_points(track)
    P = np.asarray(path, np.float64)
    ground = ground_for(track)
    air = np.zeros(len(P), bool)                       # au-dessus d'un trou (saut franchi par le parcours)
    for i in range(len(P)):                            # trace pose sur la route (dessus), sauf au-dessus des trous
        h = ground.top(P[i, 0], P[i, 1], P[i, 2] + 300)
        air[i] = h is None or P[i, 2] - h > AIR
        if not air[i] and abs(h - P[i, 2]) < 600:
            P[i, 2] = h
    starts, end = falls.section_starts(P, [t['position'] for t, _ in chain])
    # 1) plancher du monde
    killz = world_killz(track)
    if req.get('killz', True):
        killz = falls.killz_for(P)
        logical = start_finish.main_map_file(track)
        z = IgzFile(base_file(track, logical)[0])
        w = next(o for o, t in z.objects.items() if t == 'CWorldEntityData')
        struct.pack_into('<f', *z._loc(w + _field(z, 'CWorldEntityData', '_killz')), killz)
        open(saved_path(logical), 'wb').write(z.to_bytes())
        report.append(f'plancher de chute : z = {killz:.0f} (30 m sous le point le plus bas du parcours)')
    # 2) points de reapparition
    progress.step('points de réapparition', 0.2)
    design = start_finish.design_file(track)
    dz = IgzFile(base_file(track, design)[0])
    roots = {n: o for n, o in dz.root_objects() if n}
    orig = []
    for _, s in chain:
        orig += [str(r).split('::')[-1] for r in (s.get('respawn_points') or []) if str(r).split('::')[-1] not in orig]
    is_auto = lambda n: n.startswith(RESPAWN_AUTO) and n[len(RESPAWN_AUTO):].isdigit()
    autos = sorted(n for n in roots if is_auto(n))
    base = [n for n in orig if n in roots and not is_auto(n)]          # points d'origine : toujours utilises
    pool = base + autos
    donor = None
    if not pool:                                        # points ranges dans le _RaceSystem (Sewer Speedway, Slide Coliseum...)
        donor = _falls_donor()
        src = next(n for n, o in donor[1].items() if donor[0].objects.get(o) == 'CPlayerStartEntity' and f'{n}_camera' not in donor[1])
        dz.import_entity(donor[0], donor[1][src], f'{RESPAWN_AUTO}001')
        roots = {n: o for n, o in dz.root_objects() if n}
        autos, pool = [f'{RESPAWN_AUTO}001'], [f'{RESPAWN_AUTO}001']
    points = falls.respawn_layout(P, starts, end, float(req.get('spacing', 50)) * 39.37, minimum=len(base), air=air)
    points = _respawns_off_gaps(points, P, starts, end, ground)
    template = next((n for n in pool if f'{n}_camera' not in roots), pool[0])
    zones = falls.find_fall_zones(P, ground, road_ground(track), killz=killz) if req.get('zones', True) else []
    zautos = sorted(n for n in roots if n.startswith(FALL_AUTO) and n[len(FALL_AUTO):].isdigit())
    if zones and FALL_TEMPLATE not in roots and not zautos:   # piste sans modele de zone : celui de Crash Cove
        donor = donor or _falls_donor()
        dz.import_entity(donor[0], donor[1][FALL_TEMPLATE], f'{FALL_AUTO}001')
        roots = {n: o for n, o in dz.root_objects() if n}
        zautos = [f'{FALL_AUTO}001']
    zone_model = FALL_TEMPLATE if FALL_TEMPLATE in roots else (zautos[0] if zautos else None)
    # clones manquants (une seule passe : proprietes calculees une fois, liste racine reecrite une fois)
    need_p = max(0, len(points) - len(pool))
    need_z = max(0, len(zones) - len(zautos))
    if need_p or need_z:
        progress.step(f'création de {need_p + need_z} entité(s)', 0.4)
        owned = dz.owned_by(DESIGN_ENTITY_TYPES)
        names = {o: n for n, o in dz.root_objects()}
        pairs, k = [], len(autos)
        for _ in range(need_p):
            k += 1
            name = f'{RESPAWN_AUTO}{k:03d}'
            _, p = dz.clone_owned(roots[template], name, owned[roots[template]], names)
            pairs += p
            pool.append(name)
        k = len(zautos)
        for _ in range(need_z):
            k += 1
            name = f'{FALL_AUTO}{k:03d}'
            _, p = dz.clone_owned(roots[zone_model], name, owned[roots[zone_model]], names)
            pairs += p
            zautos.append(name)
        dz.add_roots(pairs)
        roots = {n: o for n, o in dz.root_objects() if n}
    used = pool[:len(points)]
    for name, (sec, pos, yaw, _) in zip(used, points):
        _set_pose(dz, roots[name], pos, yaw)
    for j, name in enumerate(pool[len(points):]):      # points auto en trop (calcul precedent) : plus listes, poses
        _, pos, yaw, _ = points[j % len(points)]       # sur un point utilise (jamais un endroit ou l'on tomberait)
        _set_pose(dz, roots[name], pos, yaw)
    # 3) zones de chute
    ns = f'{track}_Design'
    # liste = points de reapparition SEULS, comme Respawn_Trigger_Bridge de Crash Cove (version de la mise a jour) :
    # un « EntityTags::PlayerStart » en tete (ancienne version) faisait planter le jeu des qu'un kart entrait dans la
    # zone (T901 Boo Lake : tomber a cote de la route = plantage, joueur et IA)
    for name, zone in zip(zautos, zones):
        ent = roots[name]
        struct.pack_into('<3f', *dz._loc(ent + 0x20), *zone['center'])
        box = _component(dz, ent, 'CTriggerVolumeBoxComponentData')
        dz.set_field(box, '_dimensions', zone['dims'])
        rt = _component(dz, ent, 'CRespawnTriggerComponentData')
        lst = dz.deref(rt + _field(dz, 'CRespawnTriggerComponentData', '_respawnPoints'))
        dz.set_handle_list(lst, [(used[i], ns) for i in falls.before(points, zone['s'])])
    for name in zautos[len(zones):]:
        p = list(dz.vec3(roots[name] + 0x20))
        struct.pack_into('<3f', *dz._loc(roots[name] + 0x20), p[0], p[1], FAR_BELOW)
    progress.step('écriture', 0.85)
    safe_compact(track, design, dz)
    dz.save(saved_path(design))
    # 4) listes de reapparition des sections (RaceSystem)
    ed = RaceSystemEditor(base_file(track, race_file(track))[0], track)
    for k, (_, s) in enumerate(chain):
        comp = ed.component(ed.by_name[s['name']], 'CRaceTrackSplineComponentData')
        lst = ed.igz.deref(comp + _field(ed.igz, 'CRaceTrackSplineComponentData', '_respawnPoints'))
        ed.igz.set_handle_list(lst, [(n, ns) for n, p in zip(used, points) if p[0] == k])
    safe_compact(track, race_file(track), ed.igz)
    ed.igz.save(saved_path(race_file(track)))
    lap = (end - starts[0]) / 39.37
    report.append(f'{len(points)} points de réapparition sur {lap:.0f} m (un tous les {lap / len(points):.0f} m'
                  f'{", " + str(need_p) + " ajoutés" if need_p else ""})')
    report.append(f'{len(zones)} zone(s) de chute' + (' : aucun trou ni vide à côté de la route' if not zones else
                  ' : ' + ', '.join(f"{z['dims'][0] / 39.37:.0f} × {z['dims'][1] / 39.37:.0f} m" for z in zones[:6])))
    return {'report': report, 'zones': zones, 'points': [p[1] for p in points], 'killz': killz}


def _set_pose(z, ent, pos, yaw):
    struct.pack_into('<3f', *z._loc(ent + 0x20), *[float(c) for c in pos])
    tr = z.deref(ent + 0x30)
    if tr is not None:
        if yaw is not None:
            struct.pack_into('<f', *z._loc(tr + 0x68), float(yaw))
        struct.pack_into('<I', *z._loc(tr + 0x7C), 1)


_minimap_orient_cache = {}


def minimap_orientation(track):
    """(op, sure) : sens d'affichage de l'image de mini-carte de la piste, retrouve sur son image et son trace
    d'origine (minimap.choose_orientation). Crash Cove (reference) : normal."""
    if track not in _minimap_orient_cache:
        if minimap_crash_cove_family(track):
            # Crash Cove et ses copies (pistes creees) : image lue retournee haut / bas en jeu (comme les images du menu ;
            # verifie sur la T111 de l'utilisateur, corrigee a la main par « Miroir vertical » sur chaque piste). Trace
            # ovale presque symetrique : la detection hesitait (retournee 0,53 / normale 0,47) et retombait sur normal
            _minimap_orient_cache[track] = ((0, True), True)
        else:
            tp = track_pak(track)
            try:
                rgba, _ = preview.decode_texture(pak_tool.read_latest(ARCHIVES, minimap_texture_logical(track), tp)[0], 1024)
                rs = RaceSystem(pak_tool.read_latest(ARCHIVES, race_file(track), tp)[0], file_ns=race_ns(track)).decode()
                pts = np.vstack([np.array(ai_gen.catmull_rom(p['control_points'], 300))[:, :2] for p in rs['position_paths']])
                op, sure, _ = minimap.choose_orientation(rgba, pts)
            except Exception:  # noqa: BLE001 - donnees d'origine illisibles : sens de Crash Cove
                traceback.print_exc()
                op, sure = (0, False), False
            _minimap_orient_cache[track] = (tuple(op), sure)
    return _minimap_orient_cache[track]


MINIMAP_MIRROR_VERSION = 2     # 2 : Crash Cove et ses copies retournees par defaut (avant : « Miroir vertical » a la main)
MINIMAP_META_VERSION = 3       # 3 : trace plus grand, comme les images du jeu (minimap.CONTENT)


def minimap_crash_cove_family(track):
    """Piste dont la mini-carte est celle de Crash Cove (Crash Cove, pistes creees : texture ..._race_crashcove)."""
    try:
        return 'race_crashcove' in minimap_texture_logical(track).lower()
    except StopIteration:
        return False


def minimap_meta(track):
    """Reglage memorise de la mini-carte ({} si jamais generee). Ancienne version sur Crash Cove / pistes creees : le
    miroir vertical a la main valait le retournement desormais par defaut -> miroir vertical retire."""
    p = os.path.join(OUT_DIR, f'{track}_minimap.json')
    meta = json.load(open(p)) if os.path.exists(p) else {}
    if meta and meta.get('v', 1) < MINIMAP_MIRROR_VERSION and minimap_crash_cove_family(track):
        meta['mirror_v'] = False
    return meta


def minimap_outdated(track):
    """Mini-carte generee par une ancienne version (trace trop petit ; Crash Cove / piste creee : image a l'envers en
    jeu sans le miroir vertical a la main) : a refaire, reglages du dessin gardes."""
    p = os.path.join(OUT_DIR, f'{track}_minimap.json')
    return os.path.exists(p) and json.load(open(p)).get('v', 1) < MINIMAP_META_VERSION


def generate_minimap(track, move=None, flip=None):
    """Mini-carte refaite d'apres le parcours ENREGISTRE (route importee si connue, sinon trace epais) : image +
    coins du script, toujours depuis les fichiers d'origine. move = [du, dv] : reglage fin du dessin (px, cumule et
    memorise dans <Piste>_minimap.json) ; flip = 'h' / 'v' : inverse le miroir horizontal / vertical du dessin
    (memorise aussi). -> rapport + apercu PNG (data URL) + reglage."""
    import base64
    from PIL import Image
    meta_p = os.path.join(OUT_DIR, f'{track}_minimap.json')
    meta = minimap_meta(track)
    nudge = list(meta.get('nudge', minimap.NUDGE_DEFAULT))
    mirror = [bool(meta.get('mirror_h')), bool(meta.get('mirror_v'))]
    if move:
        nudge = [nudge[0] + int(move[0]), nudge[1] + int(move[1])]
    if flip in ('h', 'v'):
        mirror['hv'.index(flip)] = not mirror['hv'.index(flip)]
    path, tr = race_path_points(track)
    if len(path) < 10:
        raise ValueError('pas de parcours enregistre (cree le parcours et enregistre d\'abord)')
    fin = next((t for t in tr['transitions'] if t['increment_lap']), None)
    src = json.load(open(road_source_path(track))) if os.path.exists(road_source_path(track)) else \
        {'objects': imported_road_objects(track)}
    progress.step('lecture de la route', 0.1)
    try:
        tris = road_tris(track, src) if src.get('objects') else None
    except ValueError:                                    # objet de route supprime depuis : dessin d'apres le trace
        traceback.print_exc()
        tris = None
    progress.step('orientation de la mini-carte', 0.3)
    orient, sure = minimap_orientation(track)
    progress.step('dessin et encodage de l\'image', 0.4)
    mm, tex_logical = minimap.minimap_file(track), minimap_texture_logical(track)
    setup, tex, rgba, corners = minimap.build(
        pak_tool.read_latest(ARCHIVES, mm, track_pak(track))[0],
        pak_tool.read_latest(ARCHIVES, tex_logical, track_pak(track))[0],
        path, tris, (fin['position'], fin['yaw'] or 0.0) if fin else None, 1000.0, nudge, orient, tuple(mirror))
    os.makedirs(OUT_DIR, exist_ok=True)
    open(saved_path(mm), 'wb').write(setup)
    open(saved_path(tex_logical), 'wb').write(tex)
    json.dump({'path_key': minimap_path_key(track), 'nudge': nudge, 'mirror_h': mirror[0], 'mirror_v': mirror[1],
               'v': MINIMAP_META_VERSION}, open(meta_p, 'w'))
    buf = io.BytesIO()
    Image.fromarray(rgba).save(buf, 'PNG')
    stored_png = None
    if corners.get('stored') is not None:                 # miroir : image telle qu'enregistree (le jeu la relit retournee)
        sb = io.BytesIO()
        Image.fromarray(corners['stored']).save(sb, 'PNG')
        stored_png = 'data:image/png;base64,' + base64.b64encode(sb.getvalue()).decode()
    return {'stored_preview': stored_png,
            'report': [f"mini-carte : {'route importée' if tris is not None else 'tracé'} dessinée, coins "
                       f"({corners['top_left'][0]:.0f}, {corners['top_left'][1]:.0f}) / "
                       f"({corners['bottom_right'][0]:.0f}, {corners['bottom_right'][1]:.0f}), réglage du dessin "
                       f"{nudge[0]:+d} / {nudge[1]:+d} px"
                       + ('' if orient == (0, False) else f", image rangée dans le sens d'affichage de la piste "
                          f"({'retournée' if orient == (0, True) else f'orientation {orient}'})")
                       + ('' if sure else " ; ATTENTION : sens d'affichage de cette piste incertain, à vérifier en jeu")
                       + (f", miroir {' et '.join(n for n, m in zip(('horizontal', 'vertical'), mirror) if m)}"
                          if any(mirror) else '')],
            'preview': 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode(), 'nudge': nudge,
            'mirror': mirror}


def minimap_path_key(track):
    """Empreinte du parcours enregistre (splines de position, a 10 po pres) : la mini-carte est-elle a jour ?"""
    import hashlib
    path, _ = race_path_points(track)
    return hashlib.md5(json.dumps([[round(c / 10) for c in p[:2]] for p in path]).encode()).hexdigest()


def minimap_saved_key(track):
    p = os.path.join(OUT_DIR, f'{track}_minimap.json')
    return json.load(open(p)).get('path_key') if os.path.exists(p) else None


def minimap_logicals(track):
    try:
        return [minimap.minimap_file(track), minimap_texture_logical(track)]
    except StopIteration:
        return [minimap.minimap_file(track)]


# -- verification avant installation ------------------------------------------------------------
# -- corrections en un clic (fenetre « Verifier ») -------------------------------------------------
# Chaque controle peut porter une correction : 'fix' (automatique, sur la version ENREGISTREE, dans l'historique :
# « Annuler » la defait) ou 'ui' (ouvre l'outil a utiliser dans l'editeur). Ordre de « Tout corriger » : les fichiers
# dont dependent les suivants d'abord (la mini-carte, dessinee d'apres le parcours, en dernier).
FIX_ORDER = ['occlusion', 'sky', 'splines', 'transitions', 'grid', 'crates', 'boosters', 'falls', 'minimap', 'flyby', 'texmax']
# -- hauteur des splines (parcours et IA) au-dessus de la route ----------------------------------------
# Mesure sur la courbe suivie (Catmull-Rom entre les points), par rapport a la route memorisee (« Creer le parcours »)
# sinon au sol. Splines generees : position sur la route (0), IA 2 m au-dessus. Jeu d'origine : creux jusqu'a -3,7 m,
# sauts / chutes jusqu'a 47 m (Sewer Speedway) -> les splines restees comme dans le jeu ne sont pas controlees.
SPLINE_UNDER = -100.0       # plus de 2,5 m sous la surface : sous la route
SPLINE_HIGH = 400.0         # plus de 10 m au-dessus (ou rien dessous) : en l'air
SPLINE_JUMP_END = 6000.0    # en l'air jusqu'au bout de la spline : saut qui passe une transition s'il fait < 150 m
SPLINE_LIFT = {'position_paths': 0.0, 'ai_paths': 80.0}
LIP_DIST = 400.0            # ~10 m : sous la route a moins de 10 m d'un vide (le long de la courbe) = bord d'une chute


def _surface_under(road, ground, p):
    """Niveau de la route sous p : le plus haut qui ne depasse pas p de plus de 150 po, sinon le plus proche (spline
    enfouie sous la route). Hors de la route memorisee (ou sans elle) : sol sous p seulement — un rocher ou un
    plafond au-dessus n'est pas « la route » (Crash Cove : surplomb 12 m au-dessus du trace). None : rien dessous."""
    hs = road.heights(p[0], p[1]) if road is not None else []
    if hs:
        below = [h for h in hs if h <= p[2] + 150]
        return below[0] if below else min(hs, key=lambda h: abs(h - p[2]))
    return ground.top(p[0], p[1], p[2], above=150) if ground is not None else None


def spline_height_issues(cp, road, ground):
    """Troncons de la courbe sous la route / en l'air hors saut. -> {'under': [(i0, i1, m)], 'air': [(i0, i1, m)],
    'P', 'seg', 'surf', 'd'} ; un troncon en l'air entre deux points poses (saut de A a B) est accepte, de meme
    qu'un court saut qui continue sur la section voisine."""
    P, seg = ai_gen.curve_uniform(cp, 16)
    P = np.asarray(P, np.float64)
    surf = [_surface_under(road, ground, p) for p in P]
    d = [None if h is None else float(p[2] - h) for p, h in zip(P, surf)]
    L = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(P[:, :2], axis=0), axis=1))])
    n, out = len(P), {'under': [], 'air': [], 'P': P, 'seg': seg, 'surf': surf, 'd': d}

    def runs(flag):
        k = 0
        while k < n:
            if not flag(k):
                k += 1
                continue
            j = k
            while j + 1 < n and flag(j + 1):
                j += 1
            yield k, j
            k = j + 1
    # sous la route : mesurable seulement sur la route memorisee (le sol d'origine a des creux que les splines du jeu
    # traversent de 3 a 4 m, et un plafond au-dessus n'est pas la route)
    on_road = [road is not None and bool(road.heights(p[0], p[1])) for p in P]
    for i0, i1 in runs(lambda k: on_road[k] and d[k] is not None and d[k] < SPLINE_UNDER):
        # bord d'une chute (route qui s'arrete juste apres / avant : rien dessous) : la courbe entre le point sur la
        # route du haut et celui de la reception plonge un peu avant le bord (T901 Boo Lake : chute de 27 m, courbe
        # 6 m sous le bout de la route du haut) ; le kart suit la route et tombe au bord, comme un saut
        if any(not on_road[k] for k in range(n) if L[i0] - LIP_DIST <= L[k] <= L[i1] + LIP_DIST):
            continue
        out['under'].append((i0, i1, -min(d[i0:i1 + 1]) / 39.37))
    for i0, i1 in runs(lambda k: d[k] is None or d[k] > SPLINE_HIGH):
        start, end = i0 == 0, i1 == n - 1
        if not start and not end:
            continue                                       # saut : pose avant (A) et apres (B)
        if start != end and L[i1] - L[i0] < SPLINE_JUMP_END:
            continue                                       # saut a cheval sur une transition
        top = max((x for x in d[i0:i1 + 1] if x is not None), default=None)
        out['air'].append((i0, i1, top / 39.37 if top is not None else None))
    return out


def _zone_dist(P, t):
    """Distance (vue de dessus, po) des points P au bord de la zone de la transition t (boite : profondeur
    dimensions[0] dans le sens du cap, largeur dimensions[1]) ; 0 si un point est dedans."""
    yaw, dims = t.get('yaw') or 0.0, t.get('dimensions') or [0.0, 0.0, 0.0]
    d = np.asarray(P, np.float64)[:, :2] - np.asarray(t['position'][:2], np.float64)
    along = np.abs(d @ [math.cos(yaw), math.sin(yaw)]) - dims[0] / 2
    side = np.abs(d @ [-math.sin(yaw), math.cos(yaw)]) - dims[1] / 2
    return float(np.min(np.hypot(np.maximum(along, 0), np.maximum(side, 0))))


def _used_splines(tr):
    """Noms des splines que la course utilise : citees par une transition ou un embranchement en place (pas ecarte
    sous la carte), ou de depart. Les restes de l'ancien trace (Cortex Castle AI_Spline_01..05, cites seulement par
    des embranchements ecartes) n'en font pas partie."""
    used = set(tr.get('starting_splines') or [])
    for t in tr['transitions']:
        if t['position'][2] > FAR_BELOW + 1:
            for k in ('previous_ai', 'next_ai', 'previous_position', 'next_position'):
                used |= set(t.get(k) or [])
    for f in tr.get('forks') or []:
        if f['position'][2] > FAR_BELOW + 1:
            used |= {str(h).split('::')[-1] for h in f.get('ai_paths') or []}
            if f.get('position_path'):
                used.add(str(f['position_path']).split('::')[-1])
    return used


def _edited_splines(track, tr):
    """Splines utilisees par la course et differentes de celles du jeu d'origine (nom absent ou points changes)."""
    try:
        orig = RaceSystem(pak_tool.read_latest(ARCHIVES, race_file(track), track_pak(track))[0],
                          file_ns=race_ns(track)).decode()
    except KeyError:
        return list(tr['splines'])
    o = {s['name']: s['control_points'] for s in orig['position_paths'] + orig['ai_paths']}
    same = lambda a, b: b is not None and len(a) == len(b) and np.allclose(np.asarray(a, float), np.asarray(b, float), atol=1.0)
    used = _used_splines(tr)
    return [s for s in tr['splines'] if s['name'] in used and not same(s['control_points'], o.get(s['name']))]


def fix_spline_heights(track):
    """Points des splines modifiees sous la route ou en l'air (hors saut) remis a la hauteur habituelle de la spline
    au-dessus de la route (mediane de ses points bien poses ; generees : 0 / 2 m). Sauts gardes."""
    tr = load_track(track)
    road, ground = road_ground(track), ground_for(track)
    out, moved = {}, 0
    for s in _edited_splines(track, tr):
        cp = s['control_points']
        if len(cp) < 2:
            continue
        r = spline_height_issues(cp, road, ground)
        bad = set()
        for i0, i1, _ in r['under'] + r['air']:
            bad |= set(range(i0, i1 + 1))
        if not bad:
            continue
        good = [x for k, x in enumerate(r['d']) if x is not None and k not in bad]
        lift = float(np.clip(np.median(good), 0, 250)) if good else SPLINE_LIFT.get(s['kind'], 0.0)
        pts = [list(p) for p in cp]
        blind = []                                         # sans rien dessous (trou de la route) : voisins
        for i, p in enumerate(pts):
            k = min(i * 16, len(r['P']) - 1)               # echantillon de la courbe sur ce point de controle
            if not any(j in bad for j in range(max(0, k - 8), min(len(r['P']), k + 9))):
                continue
            h = _surface_under(road, ground, p)
            if h is None:
                blind.append(i)
            elif abs(p[2] - (h + lift)) > 1:
                p[2] = h + lift
                moved += 1
        known = [i for i in range(len(pts)) if i not in blind]
        for i in blind:                                    # hauteur interpolee entre les points voisins
            a = max((j for j in known if j < i), default=None)
            b = min((j for j in known if j > i), default=None)
            if a is None and b is None:
                continue
            z = pts[a][2] if b is None else pts[b][2] if a is None else \
                pts[a][2] + (pts[b][2] - pts[a][2]) * (i - a) / (b - a)
            if abs(pts[i][2] - z) > 1:
                pts[i][2] = z
                moved += 1
        out[s['name']] = pts
    if not out:
        return 'splines : toutes à bonne hauteur'
    save_track({'track': track, 'splines': out, 'transitions': {}})
    return f'splines posées sur la route : {moved} point(s) sur {len(out)} spline(s)'


FIX_LABELS = {'occlusion': 'Retirer les zones d\'occultation', 'sky': 'Appliquer un ciel',
              'transitions': 'Replacer sur le parcours',
              'grid': 'Replacer la grille derrière la ligne', 'crates': 'Tout poser au sol',
              'boosters': 'Refaire les plaques des boosters', 'falls': 'Refaire chutes et réapparitions',
              'minimap': 'Générer la mini-carte', 'splines': 'Poser les splines sur la route',
              'flyby': 'Générer le survol', 'texmax': 'Textures en 1024 maximum'}
UI_LABELS = {'mkroute': 'Recréer le parcours…', 'regenall': 'Régénérer les splines IA…', 'dambiance': 'Choisir un ciel…',
             'dlight': 'Alléger la map…'}


def fix_grid(track):
    """Grille + repere de depart replaces derriere la ligne d'arrivee actuelle avec la disposition du jeu d'origine,
    poses a 60 po du sol (comme « Replacer la grille derriere cette ligne »)."""
    tr = load_track(track)
    o = original_start(track)
    fin = next((t for t in tr['transitions'] if t['increment_lap']), None)
    if not o or not fin:
        raise ValueError('grille ou ligne d\'arrivee introuvable')
    f0, dyaw = o['finish'], (fin['yaw'] or 0.0) - (o['finish']['yaw'] or 0.0)
    c, s = math.cos(dyaw), math.sin(dyaw)
    tf = lambda p: [fin['position'][0] + c * (p[0] - f0['position'][0]) - s * (p[1] - f0['position'][1]),
                    fin['position'][1] + s * (p[0] - f0['position'][0]) + c * (p[1] - f0['position'][1]),
                    fin['position'][2] + p[2] - f0['position'][2]]
    g = ground_for(track)
    grid, lifts = [], []
    for slot in o['grid']:
        p = tf(slot['pos'])
        top = g.top(p[0], p[1], p[2] + 800)
        if top is not None:
            lifts.append(top + 60 - p[2])
            p[2] = top + 60
        grid.append({'name': slot['name'], 'pos': p, 'yaw': slot['yaw'] + dyaw})
    req = {'track': track, 'splines': {}, 'transitions': {}, 'start_grid': grid}
    if o.get('ps'):
        p = tf(o['ps']['pos'])
        p[2] += float(np.mean(lifts)) if lifts else 0.0
        req['player_start'] = {'pos': p, 'yaw': o['ps']['yaw'] + dyaw}
    save_track(req)
    return f'grille de départ : {len(grid)} places replacées derrière la ligne'


def fix_transitions(track):
    """Transitions loin de leur spline de position suivante (> 38 m) ou tournees a l'envers : ramenees au point le
    plus proche de cette spline, cap = sens de la spline (hauteur : celle de la zone au-dessus du trace)."""
    tr = load_track(track)
    splines = {s['name']: s for s in tr['splines']}
    moved, out = [], {}
    for t in tr['transitions']:
        nxt = [n for n in t['next_position'] if n in splines]
        if not nxt:
            continue
        P = np.array(ai_gen.curve_uniform(splines[nxt[0]]['control_points'], 16)[0])
        d = np.linalg.norm(P[:, :2] - np.asarray(t['position'][:2]), axis=1)
        k = int(d.argmin())
        tan = P[min(k + 1, len(P) - 1), :2] - P[max(k - 1, 0), :2]
        head = math.atan2(tan[1], tan[0])
        if d[k] <= 1500 and math.cos(head - (t['yaw'] or 0.0)) >= 0:
            continue
        lift = t['position'][2] - float(P[k, 2])           # hauteur de la zone au-dessus du trace, gardee
        out[t['name']] = {'position': [float(P[k, 0]), float(P[k, 1]), float(P[k, 2]) + (lift if 0 < lift < 2000 else 660.0)],
                          'yaw': head, 'dimensions': t['dimensions']}
        moved.append(t['name'].replace('RaceSystem_SplineTransition_', 'transition ').replace('Splines_Transition_', 'transition '))
    if not out:
        return 'transitions : rien à replacer'
    save_track({'track': track, 'splines': {}, 'transitions': out})
    return f'{", ".join(moved)} : replacée(s) sur le parcours'


def fix_crates(track):
    """Caisses (et TNT / Nitro / fruits) posees sur le sol ; inclinees comme la pente a l'enregistrement."""
    tr = load_track(track)
    g, n = ground_for(track), 0
    crates = []
    for c in tr['crates']:
        c = dict(c)
        if c['kind'] != 'boost':
            top = g.top(c['pos'][0], c['pos'][1], c['pos'][2])
            if top is not None:
                z = top + powerup.lift_of(c['kind'])
                n += abs(z - c['pos'][2]) > 1
                c['pos'] = [c['pos'][0], c['pos'][1], z]
        crates.append(c)
    save_track({'track': track, 'splines': {}, 'transitions': {}, 'crates': crates})
    return f'caisses : {n} reposée(s) sur le sol'


def fix_boosters(track):
    """Plaques au sol refaites d'apres les boosters (comme un enregistrement en mode Course)."""
    save_track({'track': track, 'splines': {}, 'transitions': {}, 'crates': load_track(track)['crates']})
    return 'plaques des boosters refaites'


def fix_sky(track):
    """Ciel (re)ecrit dans l'eclairage de la piste : celui deja choisi, sinon celui de Crash Cove."""
    p = ambiance_path(track)
    cur = json.load(open(p)) if os.path.exists(p) else {}
    key = cur.get('sky') or 'T111_Crash_Cove'
    set_ambiance({'track': track, 'preset': cur.get('preset', 'day'), 'values': cur.get('values') or {}, 'sky': key})
    label = next((s['label'] for s in sky_catalog() if s['key'] == key), key)
    return f'ciel et éclairage de {label} écrits (modifiable : Ambiance › Ciel)'


def fix_texmax(track):
    """Reglage « Alleger la map » : textures en 1024 maximum a l'installation (512 si c'etait deja 1024)."""
    st = light_settings(track)
    st['texture_max'] = 512 if int(st.get('texture_max') or 0) == 1024 else 1024
    json.dump(st, open(light_path(track), 'w'))
    return f"textures en {st['texture_max']} maximum à l'installation (modifiable : Alléger la map)"


def fix_occlusion(track):
    nm = newmap_settings(track)
    apply_newmap({'track': track, 'strip_ground': nm.get('strip_ground'), 'strip_art': nm.get('strip_art'),
                  'move_away': list(dict.fromkeys((nm.get('move_away') or []) + ['occlusion'])), 'remove': []})
    return 'zones d\'occultation de l\'ancienne piste retirées'


FIXES = {'splines': fix_spline_heights, 'transitions': fix_transitions, 'grid': fix_grid, 'crates': fix_crates, 'boosters': fix_boosters, 'sky': fix_sky, 'occlusion': fix_occlusion,
         'falls': lambda t: '; '.join(auto_falls({'track': t}).get('report') or ['chutes et réapparitions refaites']),
         'minimap': lambda t: generate_minimap(t)['report'][0], 'flyby': fix_flyby, 'texmax': fix_texmax}


def apply_fixes(req):
    """req = {track, fixes: [ids]} : corrections appliquees dans l'ordre FIX_ORDER. -> {report, failed}."""
    track = req['track']
    todo = [f for f in FIX_ORDER if f in set(req.get('fixes') or [])]
    report, failed = [], []
    for k, f in enumerate(todo):
        with progress.span(k / len(todo), (k + 1) / len(todo), FIX_LABELS[f]):
            try:
                report.append(FIXES[f](track))
            except Exception as e:  # noqa: BLE001 - les autres corrections continuent
                traceback.print_exc()
                failed.append(f'{FIX_LABELS[f]} : {e}')
    return {'report': report, 'failed': failed}


def preinstall_check(track):
    """Controles de ce qui sera installe (versions enregistrees) : [{'level': 'erreur' | 'attention' | 'ok',
    'topic', 'text'}]. Les erreurs empechent une course normale (depart a l'envers, IA perdues...) ; les
    avertissements meritent un coup d'oeil. Reprend les pieges rencontres : ligne d'arrivee deplacee / retournee
    apres la creation du parcours, noeuds des splines IA, objets poses sur un sol enfoui, route sous le plancher."""
    out = []

    def add(level, topic, text, fix=None, ui=None):
        c = {'level': level, 'topic': topic, 'text': text}
        if fix:                                        # correction automatique (apply_fixes)
            c['fix'], c['fix_label'] = fix, FIX_LABELS[fix]
        elif ui:                                       # outil de l'editeur a ouvrir
            c['ui'], c['fix_label'] = ui, UI_LABELS[ui]
        out.append(c)
    ensure_collision(track)                            # modifications en attente : collision a jour avant les controles
    tr = load_track(track)
    splines = {s['name']: s for s in tr['splines']}
    pos = {n: s for n, s in splines.items() if s['kind'] == 'position_paths'}
    ai = {n: s for n, s in splines.items() if s['kind'] == 'ai_paths'}
    dense = {n: np.array(ai_gen.curve_uniform(s['control_points'], 16)[0]) for n, s in splines.items()}
    progress.step('lecture du sol', 0.1)
    ground = ground_for(track)
    road = road_ground(track)
    progress.step('contrôles', 0.4)

    def nearest(P, xy):
        d = np.linalg.norm(P[:, :2] - np.asarray(xy[:2]), axis=1)
        k = int(d.argmin())
        t = P[min(k + 1, len(P) - 1), :2] - P[max(k - 1, 0), :2]
        return float(d[k]), math.atan2(t[1], t[0])
    # 1) depart et transitions
    fin = [t for t in tr['transitions'] if t['increment_lap']]
    if not fin:
        add('erreur', 'Départ', 'aucune ligne d\'arrivée (transition « changement de tour »)')
    bad_t = []
    for t in tr['transitions']:
        label = 'ligne d\'arrivée' if t['increment_lap'] else t['name'].replace('RaceSystem_SplineTransition_', 'transition ')
        if not t['increment_lap'] and t['position'][2] <= FAR_BELOW + 1:   # ecartee sous la carte (raccourci retire)
            continue
        nxt = [n for n in t['next_position'] if n in dense]
        if not nxt:
            bad_t.append((f'{label} : aucune spline de position suivante', None))
            continue
        dist, head = nearest(dense[nxt[0]], t['position'])
        if dist > 1500:
            bad_t.append((f'{label} : à {dist / 39.37:.0f} m de sa spline de position', 'transitions'))
        elif math.cos(head - (t['yaw'] or 0.0)) < 0:
            bad_t.append((f'{label} : tournée dans le sens inverse du parcours', 'transitions'))
        # distance au bord de la zone (pas a son centre : sur une route tres large, la voie exterieure passe a 38 m
        # du centre tout en traversant la zone, Crash Cove)
        far_ai = [n for n in t['next_ai'] if n in dense and _zone_dist(dense[n], t) > 1000]
        if far_ai and dist <= 1500:                    # zone a sa place mais IA loin : il faut refaire le parcours
            bad_t.append((f'{label} : {len(far_ai)} spline(s) IA suivante(s) loin de la zone', None))
        if not t['next_ai']:
            bad_t.append((f'{label} : aucune spline IA suivante (les IA s\'y arrêtent)', None))
    for b, fix in bad_t:
        if fix:
            add('erreur', 'Départ et transitions', b, fix=fix)
        else:
            add('erreur', 'Départ et transitions', b + ' → « Recréer le parcours depuis cette ligne » (ligne d\'arrivée '
                                                       'sélectionnée)', ui='mkroute')
    if fin and not bad_t:
        add('ok', 'Départ et transitions', f"{len(tr['transitions'])} transitions sur le parcours et dans le bon sens")
    # grille
    if fin and tr.get('start_grid'):
        f0 = fin[0]
        nxt = [n for n in f0['next_position'] if n in dense]
        g = tr['start_grid']
        c = np.mean([s['pos'] for s in g], axis=0)
        dist = float(np.linalg.norm(c[:2] - np.array(f0['position'][:2])))
        head = nearest(dense[nxt[0]], c)[1] if nxt else f0['yaw'] or 0.0
        wrong = sum(math.cos(s['yaw'] - head) < 0 for s in g)
        if wrong:
            add('erreur', 'Grille de départ', f'{wrong} place(s) sur {len(g)} tournée(s) à contresens du parcours', fix='grid')
        elif dist > 3000:
            add('attention', 'Grille de départ', f'à {dist / 39.37:.0f} m de la ligne d\'arrivée → « Replacer la grille derrière cette ligne »', fix='grid')
        else:
            add('ok', 'Grille de départ', f'{len(g)} places derrière la ligne, dans le sens de la course')
    # 2) splines IA
    knots = [n for n, s in ai.items() if ai_gen.self_crossings(s['control_points']) > 0]
    longs = [n for n, s in ai.items()
             if len(s['control_points']) > 1 and np.linalg.norm(np.diff(np.array(s['control_points'])[:, :2], axis=0), axis=1).max() > 6000]
    if knots:
        add('attention', 'Splines IA', f'nœud(s) sur {", ".join(knots)} → « Régénérer toutes les splines IA » ou corriger à la main', ui='regenall')
    if longs:
        add('attention', 'Splines IA', f'segment(s) de plus de 150 m (risque de traverser un mur) : {", ".join(longs)}', ui='regenall')
    missing = [s for s in tr.get('starting_splines') or [] if s not in ai]
    if missing:
        add('attention', 'Splines IA', f'splines de départ absentes : {", ".join(sorted(set(missing)))} (remplacées à l\'enregistrement)')
    if road is not None and ai:
        off = tot = 0
        for n, s in ai.items():
            for p in dense[n][::4]:
                tot += 1
                off += road.at(p[0], p[1], p[2] - 80, window=1500.0) is None
        if off / max(tot, 1) > 0.05:
            add('attention', 'Splines IA', f'{100 * off / tot:.0f} % des trajets IA hors de la route', ui='regenall')
    if ai and not knots and not longs:
        add('ok', 'Splines IA', f'{len(ai)} splines, sans nœud ni long segment')
    # hauteur des splines modifiees : un peu au-dessus de la route, ou en l'air seulement pendant un saut (A -> B)
    progress.step('hauteur des splines', 0.5)
    edited = _edited_splines(track, tr)
    under, air = [], []
    for s in edited:
        if len(s['control_points']) < 2:
            continue
        r = spline_height_issues(s['control_points'], road, ground)
        kind = 'parcours' if s['kind'] == 'position_paths' else 'IA'
        if r['under']:
            under.append(f"{s['name']} ({kind}, jusqu'à {max(x[2] for x in r['under']):.0f} m dessous)")
        if r['air']:
            top = [x[2] for x in r['air'] if x[2] is not None]
            air.append(f"{s['name']} ({kind}, " + (f'{max(top):.0f} m au-dessus' if top else 'sans sol dessous') + ')')
    if under:
        add('erreur', 'Hauteur des splines', f'{len(under)} spline(s) sous la route (plus de 2,5 m) : '
                                              f'{", ".join(under[:4])}{" …" if len(under) > 4 else ""}', fix='splines')
    if air:
        void = ' — sans sol dessous : branche restée sur l\'ancien tracé ? (à déplacer sur ta route ou à retirer des ' \
               'transitions)' if any('sans sol' in a for a in air) else ''
        add('attention', 'Hauteur des splines', f'{len(air)} spline(s) en l\'air hors d\'un saut (plus de 10 m, sans '
                                                f'retomber) : {", ".join(air[:4])}{" …" if len(air) > 4 else ""}{void}', fix='splines')
    if not under and not air:
        add('ok', 'Hauteur des splines', f'{len(edited)} spline(s) modifiée(s) au-dessus de la route (en l\'air '
                                         f'seulement pendant les sauts)' if edited else 'splines du jeu d\'origine')
    # 3) sol, hauteur
    kz = world_killz(track)
    low = min((float(np.min(np.asarray(s['control_points'])[:, 2])) for s in pos.values()), default=None)
    if road is not None and len(road.t):
        zr = float(np.median(road.t[:, :, 2]))
        if zr < kz:
            add('erreur', 'Route', f'la route est à z = {zr:.0f}, sous le plancher de chute ({kz:.0f}) : les karts y sont « tombés »')
        else:
            add('ok', 'Route', f'au-dessus du plancher de chute (z ≈ {zr:.0f})')
    if low is not None and low - 40 < kz:          # jeu d'origine : 3,8 m de marge seulement (Tiny Arena)
        add('erreur', 'Chutes', f'le parcours descend à z = {low:.0f}, à moins d\'1 m du plancher de chute ({kz:.0f}) : '
                                f'refais « Chutes et réapparitions » (la map a bougé ?)', fix='falls')
    # reapparitions (points des splines de position)
    rnames = sorted({str(r).split('::')[-1] for s in pos.values() for r in (s.get('respawn_points') or [])})
    if rnames:
        poses = start_finish.read_entity_poses(base_file(track, start_finish.design_file(track))[0], rnames)
        if len(poses) < len(rnames):                  # rangees dans le _RaceSystem (Sewer Speedway, Slide Coliseum...)
            poses.update(start_finish.read_entity_poses(base_file(track, race_file(track))[0],
                                                        [n for n in rnames if n not in poses]))
        lost = [n for n, p in poses.items() if p['pos'][2] > FAR_BELOW / 2 and not ground.heights(p['pos'][0], p['pos'][1])]
        if lost:
            add('attention', 'Réapparitions', f'{len(lost)} point(s) sans sol dessous : {", ".join(lost[:5])}', fix='falls')
        else:
            add('ok', 'Réapparitions', f'{len(poses)} point(s) au-dessus du sol')
    # 4) caisses et boosters
    crates = tr.get('crates') or []
    box = [c for c in crates if c['kind'] != 'boost']
    buried, floating = [], []
    for c in box:
        top = ground.top(c['pos'][0], c['pos'][1], c['pos'][2])
        if top is None:
            continue
        dz = c['pos'][2] - top - (powerup.lift_of(c['kind']) - powerup.LIFT)      # fruit : origine en son centre
        if dz < -10:
            buried.append(c['name'])
        elif dz > 150:
            floating.append(c['name'])
    if buried:
        add('erreur', 'Caisses', f'{len(buried)} caisse(s) enfoncée(s) dans le sol → « Tout poser au sol »', fix='crates')
    if floating:
        add('attention', 'Caisses', f'{len(floating)} caisse(s) en l\'air (plus de 4 m) → « Tout poser au sol » si ce n\'est pas voulu', fix='crates')
    if box and not buried and not floating:
        add('ok', 'Caisses', f'{len(box)} caisse(s) posées sur le sol')
    boosts = [c for c in crates if c['kind'] == 'boost']
    if boosts:
        art = main_art(track)
        vis = [o for o in DecorFile(base_file(track, art)[0]).objects()
               if (o['model'] or '').lower().endswith(('\\boostpad.igb', '\\boostpadsuper.igb'))]
        if len(vis) != len(boosts):
            add('attention', 'Boosters', f'{len(boosts)} booster(s) mais {len(vis)} plaque(s) au sol → enregistre en mode Course', fix='boosters')
        else:
            add('ok', 'Boosters', f'{len(boosts)} booster(s) avec leur plaque')
    # 5) fichiers
    used = set()
    for art in art_files(track):
        used |= {model_logical_path(o['model']) for o in DecorFile(base_file(track, art)[0]).objects()}
    lost_models = [m for m in used if m.startswith(f'models/{CUSTOM_DIR}/') and not os.path.exists(custom_model_path(m))]
    if lost_models:
        add('erreur', 'Fichiers', f'{len(lost_models)} modèle(s) importé(s) introuvable(s) : {", ".join(os.path.basename(m) for m in lost_models[:5])}')
    low = []
    for art in art_files(track):
        for o in DecorFile(base_file(track, art)[0]).objects():
            if o['model'] and model_logical_path(o['model']).startswith(f'models/{CUSTOM_DIR}/') and o['pos'][2] < KILL_Z - 2000:
                low.append(o['name'])
    if low:
        add('attention', 'Décor', f'{len(low)} objet(s) importé(s) bien sous le plancher de chute : {", ".join(low[:4])}')
    try:
        lib_entries, lib_copies = library_install_entries(track)
        if lib_entries:
            n_models = sum(t == 'model' for t, _ in lib_entries)
            add('ok', 'Bibliothèque', f'{n_models} modèle(s) d\'autres pistes : {len(lib_entries)} fichier(s) déclaré(s), '
                                      f'{len(lib_copies)} copié(s) dans l\'archive de la piste')
    except Exception as e:  # noqa: BLE001 - fichier manquant
        add('erreur', 'Bibliothèque', f'objet d\'une autre piste incomplet : {e}')
    nm = newmap_settings(track)
    if nm.get('strip_art') and move_away_files(track).get('occlusion') and 'occlusion' not in (nm.get('move_away') or []):
        add('attention', 'Occultation', 'les zones d\'occultation de l\'ancienne piste masquent des morceaux de ta map selon '
                                        'la caméra → mode Décor › Nouvelle map › cocher « Zones d\'occultation »', fix='occlusion')
    # ciel : piste sans ciel (fond = decor retire par « Nouvelle map ») -> trainees en jeu
    try:
        sky = ambiance_sky(track)
        own = _sky_name(IgzFile(pak_tool.read_latest(ARCHIVES, lighting_file(track), track_pak(track))[0]))
        written = _sky_name(IgzFile(base_file(track, lighting_file(track))[0])) if sky else None
        if sky and written != sky['name']:
            add('attention', 'Ciel', f"le ciel de {sky['label']} est choisi mais pas écrit dans l'éclairage de la piste "
                                     f"({os.path.basename(lighting_file(track))})", fix='sky')
        elif sky:
            n = len(sky_install_files(track)[1])
            add('ok', 'Ciel', f"ciel de {sky['label']}" + (f' ({n} fichier(s) copié(s) dans l\'archive de la piste)' if n else ''))
        elif not own and newmap_settings(track).get('strip_art'):
            add('attention', 'Ciel', 'cette piste n\'a pas de ciel (son fond était un décor, retiré par « Nouvelle map ») : '
                                     'grosses traînées en jeu → mode Décor › Ambiance › Ciel', fix='sky')
    except Exception as e:  # noqa: BLE001
        add('erreur', 'Ciel', f'ciel incomplet : {e}')
    # mini-carte : toujours celle de l'ancienne piste alors que le parcours a ete refait ?
    new_course = os.path.exists(road_source_path(track)) or newmap_settings(track).get('strip_art')
    mm = saved_path(minimap.minimap_file(track))
    if new_course and not os.path.exists(mm):
        add('attention', 'Mini-carte', 'c\'est encore celle de la piste d\'origine → « Générer la mini-carte » (mode Course)', fix='minimap')
    elif os.path.exists(mm) and minimap_path_key(track) != minimap_saved_key(track):
        add('attention', 'Mini-carte', 'le parcours a changé depuis sa génération → « Générer la mini-carte » à nouveau', fix='minimap')
    elif os.path.exists(mm):
        add('ok', 'Mini-carte', 'dessinée d\'après le parcours')
    # survol d'introduction : cameras refaites pour cette map ?
    shots = tr.get('flyby') or []
    if shots:
        done = sum(s['custom'] for s in shots)
        far = flyby_far_from_grid(track, tr)
        if not done and (new_course or far):
            add('attention', 'Survol d\'introduction', f'caméras d\'origine ({len(shots)} plans) : elles filment l\'ancienne '
                                                       'piste → « Générer depuis le parcours » (mode Course › Survol)', fix='flyby')
        elif far:
            add('attention', 'Survol d\'introduction', f'le survol finit à {far:.0f} m de la grille : le parcours ou la grille '
                                                       'ont bougé depuis → à refaire', fix='flyby')
        elif done < len(shots) and new_course:
            add('attention', 'Survol d\'introduction', f'{len(shots) - done} plan(s) sur {len(shots)} encore d\'origine : ils '
                                                       'filment l\'ancienne piste', fix='flyby')
        elif done:
            add('ok', 'Survol d\'introduction', f'{done} plan(s) sur {len(shots)} refait(s), fin près de la grille')
        else:
            add('ok', 'Survol d\'introduction', 'caméras d\'origine, sur la piste d\'origine')
    # memoire du jeu (2026-11-07) : le jeu charge toute l'archive de la piste ; T901 a 741 Mo plantait (« OOM »)
    progress.step('poids de la map en jeu', 0.8)
    try:
        w = map_weight(track)
        limit = f"plafond {w['budget']} Mo, le jeu charge toute l'archive au chargement"
        if w['after'] > w['budget']:
            add('erreur', 'Mémoire du jeu', f"archive de la piste : {w['after']} Mo même après réduction des textures ({limit}) : "
                                            'le jeu plantera au chargement → retire du décor ou réduis les textures',
                **({'fix': 'texmax'} if w['texture_max'] != 512 else {'ui': 'dlight'}))
        elif w['textures']:
            add('attention', 'Mémoire du jeu', f"archive de {w['before']} Mo : {w['textures']} texture(s) seront réduites de moitié "
                                               f"à l'installation pour passer à {w['after']} Mo ({limit})", ui='dlight')
        else:
            add('ok', 'Mémoire du jeu', f"archive de la piste : {w['after']} Mo ({limit})")
        if w['collision'] and w['collision'] > w['collision_budget']:
            add('attention', 'Mémoire du jeu', f"collision lourde : {w['collision']} triangles (au-delà de {w['collision_budget']}) "
                                               '→ décor loin de la piste sans collision, ou collision simplifiée', ui='dlight')
    except Exception as e:  # noqa: BLE001
        add('attention', 'Mémoire du jeu', f'poids non mesuré : {e}')
    return {'checks': out, 'errors': sum(c['level'] == 'erreur' for c in out),
            'warnings': sum(c['level'] == 'attention' for c in out)}


def _archive_case(pak, logical):
    """Nom logique avec la casse de l'archive pak (le manifeste et EXTRAS sont en minuscules)."""
    arc, index, _ = pak_tool.cached_archive(os.path.join(ARCHIVES, pak))
    e = index.get(logical.lower())
    return e.logical_name if e else logical


def _scripted_missing(track, logical, data):
    """Fichier _Art enregistre auquel il manque des entites animees / scriptees (CGameEntity, CEntity) de l'original."""
    z = IgzFile(data)
    orig = IgzFile(pak_tool.read_latest(ARCHIVES, logical, track_pak(track))[0])
    want = {n for n, o in orig.root_objects() if orig.objects.get(o) in ('CGameEntity', 'CEntity')}
    return bool(want - {n for n, _ in z.root_objects()})


def install_plan(track):
    """{archive: {fichier: octets}} de tout ce que la piste installe (fichiers enregistres, ajouts, manifeste,
    menu). Rien n'est ecrit (sauf la collision, recalculee si une modification l'a laissee en retard)."""
    ensure_collision(track)
    per_archive = defaultdict(dict)
    migrate_boosters(track)
    moved = set(moved_away_logicals(track))
    stripped = set(newmap_settings(track).get('strip_art') or [])
    if minimap_outdated(track):
        try:
            generate_minimap(track)                     # ancienne mini-carte de Crash Cove / piste creee : a l'endroit
        except Exception:  # noqa: BLE001 - parcours absent : l'ancienne image reste
            traceback.print_exc()
    for logical in (race_file(track), ttr_file(track), collision_file(track), start_finish.design_file(track),
                    start_finish.main_map_file(track), powerup.powerup_file(track)) + tuple(art_files(track)) \
            + tuple(dict.fromkeys(moved_away_logicals(track) + [lighting_file(track)])) + tuple(minimap_logicals(track)):
        p = saved_path(logical)
        if not os.path.exists(p):
            continue
        data = open(p, 'rb').read()
        if logical == race_file(track):                 # fichiers enregistres avant le nettoyage de save_track
            z = IgzFile(data)
            if drop_orphan_points(track, z):
                safe_compact(track, logical, z)
                data = z.to_bytes()
        if logical in (race_file(track), start_finish.design_file(track)):
            # cameras <nom>_camera abimees par une ancienne version (« Changer l'echelle », « Deplacer toute la
            # map ») : pointeur de nom ecrase -> plantage du jeu en quittant la course
            try:
                data = start_finish.repair_cameras(data, pak_tool.read_latest(ARCHIVES, logical, track_pak(track))[0])[0]
            except KeyError:
                pass
        if logical in moved:
            data = sink_leftover_crates(logical, data)
        if logical in stripped and _scripted_missing(track, logical, data):
            # « Nouvelle map » d'une ancienne version : entites animees supprimees (plantage au chargement de la
            # piste suivante) -> fichier refait (elles reviennent, descendues sous la carte)
            write_art(track, logical, DecorFile(data))
            data = open(p, 'rb').read()
        for arc in pak_tool.archives_with(ARCHIVES, logical, track_pak(track)):
            per_archive[arc][logical] = data
    # modeles importes : NOUVEAUX fichiers, ajoutes a l'archive de la piste (seulement s'ils sont utilises)
    used = set()
    for art in art_files(track):
        used |= {model_logical_path(o['model']) for o in DecorFile(base_file(track, art)[0]).objects()}
    new_models = []
    for logical in custom_models(track):
        if logical in used and os.path.exists(custom_model_path(logical)):
            per_archive[os.path.join(ARCHIVES, track_pak(track))][logical] = open(custom_model_path(logical), 'rb').read()
            new_models.append(logical)
    # textures importees utilisees par ces modeles : texture(s) + materiau, nouveaux fichiers eux aussi
    entries = [('model', m) for m in new_models]
    reg, tex = custom_models(track), {i['material_id']: i for i in custom_textures(track).values()}
    # TOUTES les parties d'un modele multi-textures (edition de forme, colorisation), pas seulement la premiere :
    # une texture de partie absente bloquait le chargement de la piste sans fin (T907, 2026-11-10)
    wanted = {mid for m in new_models for mid in (reg[m].get('parts') or []) + [reg[m].get('material')]}
    for info in wanted & set(tex):
        for kind, logicals in tex[info]['files'].items():
            for logical in logicals:
                per_archive[os.path.join(ARCHIVES, track_pak(track))][logical] = open(custom_file_path(logical), 'rb').read()
                entries.insert(0, (kind, logical))
    # objets de la bibliotheque : modele, materiaux, textures declares ; ceux des archives d'autres pistes copies
    progress.step('objets de la bibliothèque', 0.02)
    lib_entries, lib_copies = library_install_entries(track)
    entries += [e for e in lib_entries if e not in entries]
    for logical, src_pak in lib_copies.items():
        per_archive[os.path.join(ARCHIVES, track_pak(track))][logical] = pak_tool.read_latest(ARCHIVES, logical, src_pak)[0]
    # ciel d'une autre piste (Ambiance) : modele « sky_model », materiau, textures
    sky_entries, sky_copies = sky_install_files(track)
    entries += [e for e in sky_entries if e not in entries]
    for logical, src_pak in sky_copies.items():
        per_archive[os.path.join(ARCHIVES, track_pak(track))][logical] = pak_tool.read_latest(ARCHIVES, logical, src_pak)[0]
    # boosters : script des plaques turbo (deja dans update.pak) a declarer dans le manifeste de la piste
    pu = saved_path(crate_file(track)) if crates_supported(track) else None
    kinds = {c['kind'] for c in powerup.read_crates(open(pu, 'rb').read(), crates_in_design(track))} \
        if pu and os.path.exists(pu) else set()
    if 'boost' in kinds or design_boosts(track):
        entries.append(('vsc', powerup.BOOST_SCRIPT))
    # TNT / Nitro / fruits : scripts, modeles et materiaux a declarer ; fichiers absents des archives communes copies
    for kind in sorted(kinds & set(powerup.EXTRAS)):
        ex = powerup.EXTRAS[kind]
        for e in ex['manifest']:
            if e not in entries:
                entries.append(e)
        for logical, src_pak in ex['copy']:
            data, _ = pak_tool.read_latest(ARCHIVES, logical, src_pak)
            per_archive[os.path.join(ARCHIVES, track_pak(track))][_archive_case(src_pak, logical)] = data
    # teleporteurs : script et effet de Hyper Spaceway (copies s'ils ne sont que dans son archive)
    tp_entries, tp_copies = teleport_install_files(track)
    entries += [e for e in tp_entries if e not in entries]
    for logical, src_pak in tp_copies.items():
        per_archive[os.path.join(ARCHIVES, track_pak(track))][logical] = pak_tool.read_latest(ARCHIVES, logical, src_pak)[0]
    # survol d'introduction : cameras reecrites, dans les archives de survol de la piste
    for arc, files in flyby_install_files(track).items():
        per_archive[arc].update(files)
    # piste creee : son icone en course vise sa vignette a elle, sa mini-carte part sous un nom a elle (le fichier au
    # nom de la source garde son contenu d'origine)
    ri_files, ri_entries, ri_drop = own_race_icon_files(track)
    for arc in per_archive:
        for lg in [x for x in per_archive[arc] if x.lower() in ri_drop]:
            del per_archive[arc][lg]
    per_archive[os.path.join(ARCHIVES, track_pak(track))].update(ri_files)
    entries += [e for e in ri_entries if e not in entries]
    # musique importee : memes noms que les originaux, dans les archives qui les contiennent
    for logical, data in music_install_files(track).items():
        for arc in pak_tool.archives_with(ARCHIVES, logical, track_pak(track)):
            per_archive[arc][logical] = data
    if music_continues(track):                          # dernier tour sans changement de morceau : la carte enregistree ne change pas
        logical, data, script = music_continue_files(track)
        for arc in pak_tool.archives_with(ARCHIVES, logical, track_pak(track)):
            per_archive[arc][logical] = data
        per_archive[os.path.join(ARCHIVES, track_pak(track))][music.CONTINUE_SCRIPT] = script
        entries.append(('vsc', music.CONTINUE_SCRIPT))
    # ...et declares dans le manifeste de streaming, sinon le jeu ne les charge pas (invisibles)
    if entries:
        man = pkg_manifest.manifest_logical(track)
        data, _ = pak_tool.read_latest(ARCHIVES, man, track_pak(track))
        data, _ = pkg_manifest.add_entries(data, entries)
        for arc in pak_tool.archives_with(ARCHIVES, man, track_pak(track)):
            per_archive[arc][man] = data
    # nom et images de menu : dans toutes les archives qui les contiennent (chunkinfos, juicedomain_*, piste...)
    for logical, p in menu_saved(track):
        data = open(p, 'rb').read()
        for arc in menu_archives(track, logical):
            per_archive[arc][logical] = data
    # temps des reliques / des fantomes : fichiers d'origine, temps poses a l'ecriture (_apply_times)
    for logical, data in times_install_files(track).items():
        pak = race_times.GHOST_PAK if logical == race_times.GHOST_DATA else race_times.zoneinfo_pak()
        for arc in pak_tool.archives_with(ARCHIVES, logical, pak):
            per_archive[arc].setdefault(logical, data)
    # types de sol a vitesse / glissade propres : CollisionMaterials (commun a tout le jeu) avec les types ajoutes
    if custom_surfaces():
        orig = pak_tool.read_latest(ARCHIVES, collision_materials.LOGICAL, collision_materials.PAK)[0]
        for arc in pak_tool.archives_with(ARCHIVES, collision_materials.LOGICAL, collision_materials.PAK):
            per_archive[arc].setdefault(collision_materials.LOGICAL, orig)
    _fix_refcounts(per_archive)
    return per_archive


MAX_AI_PER_TRANSITION = 6                               # voies par section (jeu : 5, 8 au plus sur Dingo Canyon)


def _max_ai_lanes(data, track):
    ed = RaceSystemEditor(data, track)
    return max((len(v) for t in ed.transitions() for k, v in ed.transition_paths(t).items() if k in ('previous_ai', 'next_ai')), default=0)


def slim_ai_lanes(per_archive, track):
    """Copie installee : pas plus de MAX_AI_PER_TRANSITION voies IA par section (ou le maximum d'origine de la piste). T114 avec
    12 voies par section (68 voies, 768 liens ; jeu : 300 au plus) : « OOM MP_LEVEL » en fin de chargement (2026-11-09) ; ni le
    nombre de points ni la taille du fichier n'y changeaient rien, 34 voies passent. Fichiers enregistres inchanges, splines
    de depart gardees, chaque section garde au moins une voie. -> lignes du rapport."""
    rl, tl = race_file(track), ttr_file(track)
    races, ttrs = [r for r in per_archive.values() if rl in r], [r for r in per_archive.values() if tl in r]
    if not races or not ttrs:
        return []
    try:
        limit = max(MAX_AI_PER_TRANSITION, _max_ai_lanes(pak_tool.read_latest(ARCHIVES, rl, track_pak(track))[0], track))
    except KeyError:
        limit = MAX_AI_PER_TRANSITION
    ed, ttr = RaceSystemEditor(races[0][rl], track), TTRStatsEditor(ttrs[0][tl])
    lists = {(t, k): list(ed.transition_paths(t)[k]) for t in ed.transitions() for k in ('previous_ai', 'next_ai')}
    keep, dropped, stuck = set(ttr.starting_splines()), [], set()
    while True:
        over = [kv for kv in lists.items() if len(kv[1]) > limit and kv[0] not in stuck]
        if not over:
            break
        key, cur = max(over, key=lambda kv: len(kv[1]))
        cand = [n for n in cur if n not in keep and all(len(v) > 1 for v in lists.values() if n in v)]
        if not cand:
            stuck.add(key)
            continue
        name = cand[(len(dropped) * 2 + 1) % len(cand)]             # une sur deux : voies restantes reparties sur la largeur
        dropped.append(name)
        for v in lists.values():
            if name in v:
                v.remove(name)
    if not dropped:
        return []
    for name in dropped:
        ed.remove_ai_spline(name)
        ttr.remove_spline_stats(name)
    safe_compact(track, tl, ttr.igz)
    safe_compact(track, rl, ed.igz)
    race, stats = ed.igz.to_bytes(), ttr.to_bytes()
    for r in races:
        r[rl] = race
    for r in ttrs:
        r[tl] = stats
    _fix_refcounts(per_archive)
    return [f'{len(dropped)} trajectoire(s) IA en moins dans le jeu ({limit} voies par section au plus : au-delà, le jeu manque de mémoire ; '
            'tes trajectoires restent dans l\'éditeur)']


def _fix_refcounts(per_archive):
    """Fichiers de carte a installer : compteurs de references rendus exacts (igz.IgzFile.fix_refcounts), pour ceux enregistres
    avant le correctif du 2026-11-08 (qui ne sont pas reecrits tant qu'on ne les modifie pas)."""
    for reps in per_archive.values():
        for lg, data in list(reps.items()):
            if lg.lower().startswith('maps/') and lg.lower().endswith('.igz'):
                try:
                    z = IgzFile(data)
                    if z.fix_refcounts():
                        reps[lg] = z.to_bytes()
                except Exception:  # noqa: BLE001 - fichier non IGZ standard : laisse tel quel
                    traceback.print_exc()

# Plusieurs pistes installees : des archives sont PARTAGEES (update / update2, chunkinfos pour les noms,
# juicedomain_* pour les images de menu). Une archive est toujours remise a l'origine avant une installation : sans
# precaution, installer Roo's Tubes effacait de ces archives ce que Crash Cove y avait mis (piste et nom d'origine
# revenus). Une archive partagee reecrite garde donc tout ce qui y est installe, sauf les fichiers de la piste
# (re)installee ; les archives propres a la piste (la sienne, ses survols) sont entierement refaites. Les fichiers
# gardes sont relus dans l'archive telle qu'installee : l'editeur et l'installateur (CTR Track Installer, autre dossier
# de travail) ne s'effacent pas l'un l'autre.
# Registre commun (a cote des archives) : pistes installees, par qui, et leurs fichiers par archive.
APP_NAME = 'editor'                                     # 'installer' pour CTR Track Installer
REGISTRY = 'ctr_installed_tracks.json'


def installed_path():
    return os.path.join(OUT_DIR, 'installed_tracks.json')


def registry_path():
    return os.path.join(ARCHIVES, REGISTRY)


def read_registry():
    """{piste: {by, date, archives: {archive: [fichiers]}, ...}} (title, pack : installateur)."""
    try:
        return json.load(open(registry_path(), encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _write_registry(reg):
    if reg:
        json.dump(reg, open(registry_path(), 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    elif os.path.exists(registry_path()):
        os.remove(registry_path())


def set_registry_info(track, **info):
    """Informations en plus sur une piste installee (installateur : titre de la map, pack d'origine)."""
    reg = read_registry()
    if track in reg:
        reg[track].update(info)
        _write_registry(reg)


def installed_tracks():
    """Pistes installees : registre commun, liste de ce dossier de travail (avant le registre), et celles dont
    l'archive propre porte une installation."""
    p = installed_path()
    out = set(json.load(open(p))) if os.path.exists(p) else set()
    out |= set(read_registry())
    out |= {t for t in list_tracks() if os.path.exists(pak_tool.backup_path(os.path.join(ARCHIVES, track_pak(t))))}
    return out


def _set_installed(track, on, per_archive=None):
    cur = set(json.load(open(installed_path()))) if os.path.exists(installed_path()) else set()
    cur = (cur | {track}) if on else (cur - {track})
    os.makedirs(OUT_DIR, exist_ok=True)
    json.dump(sorted(cur), open(installed_path(), 'w'))
    reg = read_registry()
    if on:
        old = reg.get(track, {})
        reg[track] = {**{k: v for k, v in old.items() if k not in ('archives', 'by', 'date')},
                      'by': APP_NAME, 'date': time.strftime('%Y-%m-%d %H:%M'),
                      'archives': {os.path.basename(a): sorted(f) for a, f in (per_archive or {}).items() if f}}
    else:
        reg.pop(track, None)
    _write_registry(reg)


def own_archives(track):
    """Archives propres a la piste (personne d'autre n'y installe) : la sienne et ses survols."""
    return {os.path.join(ARCHIVES, track_pak(track))} | \
        {os.path.join(ARCHIVES, n) for n in flyby.flyby_paks(os.listdir(ARCHIVES), track)}


def _others_for(archives, track, report, plan=None):
    """{archive: {fichier: octets}} a garder dans ces archives quand `track` y est (re)installee ou retiree : tout ce
    qui y est installe sauf ses fichiers (registre + plan d'installation) et ceux du menu (refaits a part)."""
    if plan is None:
        try:
            plan = install_plan(track)
        except Exception:  # noqa: BLE001 - rien d'enregistre : ses fichiers sont ceux du registre
            plan = {}
    mine_reg = read_registry().get(track, {}).get('archives', {})
    # menu refait par custom_category.extra_files, sauf les images propres modifiees des pistes creees (gardees,
    # comme custom_category._apply)
    edited = {menu_assets.own_image_file(t['id'], k).lower() for t in (custom_category.read_state(ARCHIVES) or {}).get('tracks', [])
              for k in menu_assets.OWN_IMAGES}
    menu = {k.lower() for k in custom_category._ours(ARCHIVES)} - edited
    own = {os.path.normcase(a) for a in own_archives(track)}
    out = defaultdict(dict)
    for arc in archives:
        if os.path.normcase(arc) in own:
            continue
        mine = {n.lower() for n in mine_reg.get(os.path.basename(arc), [])} | {n.lower() for n in plan.get(arc, {})}
        keep = {n: d for n, d in custom_category._installed_files(arc).items() if n.lower() not in mine | menu}
        if keep:
            out[arc] = keep
            report.append(f'{os.path.basename(arc)} : {len(keep)} fichier(s) d\'autres pistes gardé(s)')
    return out


def _rewrite(arc, reps):
    # categorie « Custom » du menu (custom_category.py), si elle est active : gardee a chaque reecriture d'update2
    reps = _apply_custom_surfaces(_apply_times({**custom_category.extra_files(ARCHIVES, arc), **reps}))
    custom_category.store(arc, reps)                    # update / update2 : ajouts et menu dans update3.pak


FALL_CLEAR = 10 * 39.37            # po : une zone de chute qui touchait la course est redescendue 10 m sous elle
KART_H = 3 * 39.37                 # po : hauteur du kart (une zone a moins de ca au-dessus de la route le touche)


def check_race_zones(track):
    """Verification avant installation (2026-11-06) : le kart ne doit rien toucher qui le fasse reapparaitre sur la
    course (trace des splines de position + places de la grille) :
      * zones de chute (boites du _Design) qui contiennent un point de la course -> redescendues FALL_CLEAR sous le
        point le plus bas de la course dans leur emprise (enregistre) ;
      * surfaces « Reapparition » (16) de modeles importes au niveau de la route (de 1 m dessous a KART_H dessus) ->
        signalees. -> lignes du rapport."""
    report = []
    try:
        path, tr = race_path_points(track)
    except Exception:  # noqa: BLE001 - pas de parcours : rien a verifier
        return report
    pts = [list(p) for p in path] + [list(g['pos']) for g in (tr.get('start_grid') or [])]
    if not pts:
        return report
    P = np.asarray(pts, np.float64)
    ground = ground_for(track)
    for i in range(len(P)):                              # trace pose sur la route
        h = ground.top(P[i, 0], P[i, 1], P[i, 2] + 300)
        if h is not None and abs(h - P[i, 2]) < 600:
            P[i, 2] = h
    moved = []
    import falls
    road = road_ground(track)                            # route seule (bords des virages inclines, pas seulement le milieu)
    for z in read_fall_zones(track):
        c, d = np.asarray(z['pos']), np.asarray(z['dims']) / 2
        inside = (np.abs(P[:, 0] - c[0]) <= d[0]) & (np.abs(P[:, 1] - c[1]) <= d[1]) & \
                 (P[:, 2] + KART_H >= c[2] - d[2]) & (P[:, 2] - 39.37 <= c[2] + d[2])
        top = c[2] + d[2]
        if inside.any():
            foot = (np.abs(P[:, 0] - c[0]) <= d[0]) & (np.abs(P[:, 1] - c[1]) <= d[1])
            top = float(P[foot, 2].min()) - FALL_CLEAR
        top = falls.road_clear_top(c[:2] - d[:2], c[:2] + d[:2], top, 2 * d[2], road)
        if top < c[2] + d[2] - 1:
            moved.append({'name': z['name'], 'pos': [c[0], c[1], round(top - d[2], 1)], 'dims': z['dims']})
    if moved:
        write_fall_zones(track, moved)
        report.append(f'{len(moved)} zone(s) de chute sur la course redescendue(s) sous la route : '
                      + ', '.join(m['name'] for m in moved[:5]) + (' …' if len(moved) > 5 else ''))
    # surfaces « Reapparition » au niveau de la route
    hits = defaultdict(int)
    for art, o, lk in _imported_objects(track):
        if str(lk.get('surface')) != '16':
            continue
        try:
            T = object_world_array(track, o)
        except Exception:  # noqa: BLE001 - modele introuvable : rien a verifier
            continue
        lo, hi = T.reshape(-1, 3).min(0), T.reshape(-1, 3).max(0)
        near = P[(P[:, 0] >= lo[0]) & (P[:, 0] <= hi[0]) & (P[:, 1] >= lo[1]) & (P[:, 1] <= hi[1])]
        for x, y, zr in near[::2]:
            a, b, cc = T[:, 0], T[:, 1], T[:, 2]
            den = (b[:, 1] - cc[:, 1]) * (a[:, 0] - cc[:, 0]) + (cc[:, 0] - b[:, 0]) * (a[:, 1] - cc[:, 1])
            ok = np.abs(den) > 1e-9
            sd = np.where(ok, den, 1)
            w0 = np.where(ok, ((b[:, 1] - cc[:, 1]) * (x - cc[:, 0]) + (cc[:, 0] - b[:, 0]) * (y - cc[:, 1])) / sd, -1)
            w1 = np.where(ok, ((cc[:, 1] - a[:, 1]) * (x - cc[:, 0]) + (a[:, 0] - cc[:, 0]) * (y - cc[:, 1])) / sd, -1)
            w2 = 1 - w0 - w1
            m = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
            zz = (w0 * a[:, 2] + w1 * b[:, 2] + w2 * cc[:, 2])[m]
            if ((zz > zr - 39.37) & (zz < zr + KART_H)).any():
                hits[o['name']] += 1
    for name, n in hits.items():
        report.append(f'ATTENTION : {name} (type de sol « Réapparition ») touche la course en {n} endroit(s) : '
                      f'le kart y réapparaît — change son type de sol ou déplace-le')
    return report


# 2026-11-07 : T901 plantait au chargement (journal de shadPS4 : « OOM [1]{76,GlobalChunk} » puis 0xc0000005). Le jeu
# charge TOUTE l'archive de la piste en memoire (843 Mo reserves = 741 Mo de t901_custom_map.pak + 80 Mo d'effets
# communs), fichiers inutilises compris (textures d'origine de la piste copiee). Versions de T901 qui se chargeaient :
# archive de 602 a 648 Mo. Au-dela de PAK_BUDGET (contenu de l'archive, une fois installee), les plus grosses textures
# (ajoutees ou d'origine) perdent leur 1er niveau de detail (2048 -> 1024, puis 1024 -> 512 s'il le faut).
PAK_BUDGET = 560 * 2**20


def shrink_textures(per_archive, track, budget=PAK_BUDGET, max_side=None, stats=None):
    """Archive de la piste ramenee sous `budget` octets de contenu : textures les plus grosses d'abord, moitie de cote
    (texture_build.drop_top_level) ; les textures d'origine reduites sont ajoutees aux fichiers installes. max_side
    (reglage « Alleger la map ») : toutes les textures plus grandes sont d'abord ramenees a ce cote. stats (dict) :
    rempli avec before / after / textures. -> rapport."""
    import texture_build
    if max_side is None:
        max_side = int(light_settings(track).get('texture_max') or 0)
    arc = next((a for a in per_archive if os.path.basename(a).lower() == track_pak(track).lower()),
               os.path.join(ARCHIVES, track_pak(track)))
    reps = per_archive.setdefault(arc, {})
    view = pak_tool.original_archive(arc)
    if view:
        src, index, lock = view
    else:
        src, index, lock = pak_tool.cached_archive(arc)
    mine = {k.lower() for k in reps}
    total = sum(len(v) for v in reps.values()) + sum(e.size for k, e in index.items() if k not in mine)
    before, n = total, 0
    is_tex = lambda k: k.lower().startswith('textures/') and k.lower().endswith('.igz')

    def candidates():
        return sorted([(len(v), k, None) for k, v in reps.items() if is_tex(k)] +
                      [(e.size, e.logical_name, e) for k, e in index.items() if k not in mine and is_tex(k)],
                      key=lambda c: -c[0])

    def halve(size, k, e, floor):
        nonlocal total, n
        try:
            if e is not None:
                with lock:
                    data = src.read(e)
            else:
                data = reps[k]
            if texture_build.texture_info(data)['width'] < floor:
                return False
            new = texture_build.drop_top_level(data)
        except Exception:  # noqa: BLE001 - texture illisible : laissee telle quelle
            return False
        if not new:
            return False
        total -= size - len(new)
        reps[k] = new
        mine.add(k.lower())
        n += 1
        return True
    if max_side:                                     # reglage : plus aucune texture au-dessus de max_side
        for _ in range(3):
            if not [c for c in candidates() if halve(*c, max_side * 2)]:
                break
    for floor in (2048, 1024):                       # plafond : d'abord les 2048, ensuite seulement les 1024
        for c in candidates():
            if total <= budget:
                break
            halve(*c, floor)
        if total <= budget:
            break
    if stats is not None:
        stats.update(before=before, after=total, textures=n)
    if not n:
        return []
    return [f'{n} texture(s) réduite(s) de moitié (archive de la piste : {before // 2**20} -> {total // 2**20} Mo, '
            f'plafond {budget // 2**20} Mo : le jeu charge toute l\'archive, au-delà il manque de mémoire)'
            + ('' if total <= budget else ' ; ATTENTION toujours au-dessus du plafond : retire du décor')]


def map_weight(track):
    """Poids de la map une fois installee : {before, after (Mo, contenu de l'archive de la piste avant / apres
    reduction des textures), textures (reduites), budget (Mo), collision (triangles du fichier enregistre)}."""
    progress.step('poids de la map : fichiers à installer', 0.0)
    stats = {}
    shrink_textures(install_plan(track), track, stats=stats)
    coll = None
    try:
        p = saved_path(collision_file(track))      # install_plan l'a remise a jour si besoin
        if os.path.exists(p):
            pf = Packfile(open(p, 'rb').read())
            comp = next(o for o, c in pf.objects.items() if c == 'hknpStaticCompoundShape')
            io_, k = pf.array(comp + 0x60)
            coll = 0
            for i in range(k):
                shape = pf.ptr(io_ + i * 128 + 0x50)
                if pf.objects.get(shape) == 'hknpCompressedMeshShape':
                    coll += pf.array(pf.ptr(shape + 0x58) + 0x60)[1]
    except Exception:  # noqa: BLE001
        coll = None
    return {'before': round(stats.get('before', 0) / 2**20), 'after': round(stats.get('after', 0) / 2**20),
            'textures': stats.get('textures', 0), 'budget': PAK_BUDGET // 2**20, 'collision': coll,
            'collision_budget': COLLISION_BUDGET, 'texture_max': int(light_settings(track).get('texture_max') or 0),
            'decor_reach': light_settings(track).get('decor_reach', 100)}

def install_track(track):
    progress.step('vérification de la course', 0.0)
    try:
        checked = check_race_zones(track)
    except Exception as e:  # noqa: BLE001 - la verification ne doit pas empecher l'installation
        traceback.print_exc()
        checked = [f'vérification de la course impossible : {e}']
    progress.step('préparation des fichiers', 0.0)
    per_archive = install_plan(track)
    if not per_archive:
        raise RuntimeError('rien a installer : enregistrer d\'abord')
    # diagnostic : « install_skip » (motifs, ctr_editor_config.json) = fichiers NON installes (ceux du jeu restent)
    skip = [re.compile(p, re.I) for p in (load_config().get('install_skip') or [])]
    skipped = []
    for arc in list(per_archive):
        for lg in [x for x in per_archive[arc] if any(r.search(x) for r in skip)]:
            del per_archive[arc][lg]
            skipped.append(lg)
    kept = checked + ([f'DIAGNOSTIC : {len(skipped)} fichier(s) non installé(s) ({", ".join(sorted({os.path.basename(s) for s in skipped})[:6])})']
                      if skipped else [])
    # diagnostic : « install_override » {motif: fichier} = version de test installee a la place
    for pat, src in (load_config().get('install_override') or {}).items():
        for arc in per_archive:
            for lg in [x for x in per_archive[arc] if re.search(pat, x, re.I)]:
                per_archive[arc][lg] = open(src, 'rb').read()
                kept.append(f'DIAGNOSTIC : {os.path.basename(lg)} remplacé par {os.path.basename(src)}')
    kept += slim_ai_lanes(per_archive, track)
    kept += shrink_textures(per_archive, track)
    progress.step('autres pistes installées', 0.03)
    # archives de menu modifiees par une installation precedente et plus concernees : remises a l'origine (avec les
    # fichiers des autres pistes qui s'y trouvaient)
    # (idem pour les archives de survol quand les plans d'origine sont revenus)
    stale = [a for a in menu_track_archives(track) + [os.path.join(ARCHIVES, n) for n in flyby.flyby_paks(os.listdir(ARCHIVES), track)]
             if a not in per_archive and (os.path.exists(pak_tool.backup_path(a)) or custom_category.layer_has(a))]
    others = _others_for(list(per_archive) + stale, track, kept, plan=per_archive)
    for arc in stale:
        _rewrite(arc, others.get(arc, {}))
    video = set_menu_video(track, hide_menu_video(track))
    done, files = [], set()
    for k, (arc, reps) in enumerate(per_archive.items()):
        progress.step(f'archive {k + 1} / {len(per_archive)} : {os.path.basename(arc)} ({len(reps)} fichiers)',
                      0.05 + 0.95 * k / len(per_archive))
        _rewrite(arc, {**others.get(arc, {}), **reps})          # la piste installee l'emporte sur un meme fichier
        done.append(os.path.basename(arc))
        files.update(os.path.basename(k) for k in reps)
    _set_installed(track, True, per_archive)
    if video:
        files.add(video)
    try:                                                # enregistrements des fantomes (dossier ghosts du jeu)
        kept += apply_ghost_files(track, True)
    except OSError as e:
        kept.append(f'ATTENTION : fantômes non modifiés ({e})')
    return {'installed_in': done, 'files': sorted(files), 'kept': kept}


def _ask_shadps4():
    """Fenetre de choix de shadPS4.exe (Windows : tkinter ; ailleurs : zenity)."""
    if sys.platform.startswith('linux') and shutil.which('zenity'):
        r = subprocess.run(['zenity', '--file-selection', '--title', 'shadPS4 (exécutable de l\'émulateur)'],
                           capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    try:
        return filedialog.askopenfilename(parent=root, title='shadPS4.exe (exécutable de l\'émulateur)',
                                          filetypes=[('shadPS4', 'shadPS4*.exe *shadps4*'), ('*', '*')]) or None
    finally:
        root.destroy()


def test_in_game(req):
    """POST /api/test_in_game : piste installee (comme « Installer »), ecran titre -> course unique sur la piste,
    shadPS4 lance ; choix perso / kart valide automatiquement ; jeu normal remis a la fermeture de shadPS4."""
    track = req['track']
    if quick_test.emulator_running():
        raise RuntimeError('shadPS4 est ouvert : ferme-le avant de tester')
    exe = quick_test.find_shadps4(load_config().get('shadps4'))
    if not exe or req.get('choose_exe'):
        exe = _ask_shadps4()
        if not exe:
            return {'ok': False, 'cancelled': True}
        save_config(shadps4=os.path.normpath(exe))
    report = []
    if req.get('install', True):
        try:
            r = install_track(track)
            report.append(f'piste installée ({len(r["files"])} fichiers)')
        except RuntimeError as e:
            if 'rien a installer' not in str(e):
                raise
            report.append('rien d\'enregistré : piste du jeu telle quelle')
    progress.step('écran titre de test', 0.98)
    _release_archives()
    report += quick_test.install(ARCHIVES, track)
    clear_caches()

    def restore():
        with WRITE_LOCK:
            try:
                _release_archives()
                quick_test.uninstall(ARCHIVES)
                clear_caches()
                quick_test._status('idle', 'jeu normal remis (écran titre et intros)')
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                quick_test._status('error', f'jeu normal NON remis : {e!r}')

    quick_test.launch(exe, os.path.dirname(ARCHIVES), track, on_exit=restore, auto_ready=req.get('auto_ready', True))
    return {'ok': True, 'exe': exe, 'report': report}


def creator_path(track):
    return os.path.join(OUT_DIR, f'{track}_creator.json')


def creator_info(track):
    """GET /api/creator : trace du paveur enregistre ({points, closed, ground_z, kit}) et kits disponibles."""
    saved = json.load(open(creator_path(track))) if os.path.exists(creator_path(track)) else None
    return {'saved': saved, 'kits': {k: v['label'] for k, v in track_creator.KITS.items()}, 'order': list(track_creator.KITS),
            'materials': {k: [{'label': m[4], 'color': m[5], 'png': m[1]} for m in v['materials']] for k, v in track_creator.KITS.items()},
            'kitinfo': {k: {'road_repeat': v['road_repeat'], 'ground_repeat': v['ground_repeat']} for k, v in track_creator.KITS.items()},
            'props': {k: {pk: {'label': p['label'], 'spacing': p['spacing'], 'scale': p['scale'], 'n': len(p['models']),
                               'dims': kit_prop_dims(k).get(pk, []), 'clear': track_creator.PROP_CLEAR,
                               'foot': track_creator.foot_share({**p, 'rock': pk in track_creator.ROCK_KINDS}),
                               'big': bool(p.get('big')), 'big_min': track_creator.BIG_MIN,
                               'level': track_creator.PROP_LEVEL, 'deck': track_creator.DECK,
                               'names': [os.path.basename(m)[:-4] for m in p['models']],
                               'hide': track_creator.hidden_models(k, pk),
                               'role': track_creator.prop_role(pk, p.get('big')),
                               'tilt': track_creator.PROP_ROLES[track_creator.prop_role(pk, p.get('big'))][0],
                               'seat': track_creator.PROP_ROLES[track_creator.prop_role(pk, p.get('big'))][1]}
                          for pk, p in (v.get('props') or {}).items()} for k, v in track_creator.KITS.items()}}


def create_build(req):
    """POST /api/create_build : piste generee depuis le trace du paveur. req = {track, points: [[x, y, z, largeur]]
    (pouces), closed, ground_z (pouces), kit, terrain: {x0, y0, cell, n, h, paint} | null}. Map videe (« Nouvelle map »
    complete, creation precedente retiree), route + terrain raccorde importes (collision par matiere) ;
    -> {report, road: [{file, id}], guide, exact, start, yaw, killz}
    pour « Créer le parcours » (page)."""
    track = req['track']
    pts = req.get('points') or []
    if len(pts) < 8:
        raise ValueError('tracé trop court : roule un peu plus avec le paveur')
    kit = req.get('kit') or 'sable'
    if kit not in track_creator.KITS:
        raise ValueError(f'thème inconnu : {kit}')
    ground_z = float(req.get('ground_z') or 0.0)
    progress.step('géométrie de la piste', 0.0)
    terrain = req.get('terrain')
    barriers = req.get('barriers') or 'curves'
    obj, mtl, info = track_creator.build(pts, bool(req.get('closed')), ground_z, kit, terrain, barriers)
    folder = os.path.join(OUT_DIR, 'creator', track)
    os.makedirs(folder, exist_ok=True)
    texs = track_creator.kit_textures(lambda lg, pak: pak_tool.read_latest(ARCHIVES, lg, pak)[0], kit, used=info['materials'])
    if info['mixes']:
        progress.step('fondus entre peintures', 0.02)
        texs.update(track_creator.mix_textures(texs, info['mixes']))
    for name, data in texs.items():
        p = os.path.join(folder, name)
        if not os.path.exists(p) or open(p, 'rb').read() != data:
            open(p, 'wb').write(data)
    open(os.path.join(folder, track_creator.OBJ_NAME), 'w', encoding='utf-8').write(obj)
    open(os.path.join(folder, track_creator.MTL_NAME), 'w', encoding='utf-8').write(mtl)
    json.dump({'points': pts, 'closed': bool(req.get('closed')), 'ground_z': ground_z, 'kit': kit, 'terrain': terrain,
               'barriers': barriers, 'props': req.get('props') or []},
              open(creator_path(track), 'w'))
    # map vide : tout le decor et le sol d'origine retires, creation precedente supprimee ; wipe (« Repartir de
    # zéro ») : aussi tous les ajouts faits dans Edition (imports, objets de la bibliotheque, copies)
    progress.step('nouvelle map (vider la piste)', 0.05)
    prefix = 'imp:' + os.path.splitext(track_creator.OBJ_NAME)[0] + ' —'
    with progress.span(0.05, 0.3):
        apply_newmap({'track': track, 'strip_ground': True, 'strip_art': art_files(track),
                      'move_away': [k for k, _, _ in MOVE_AWAY_GROUPS],
                      'remove': [g['key'] for g in added_groups(track) if req.get('wipe') or g['key'].startswith(prefix)]})
    surf = {m: {'collision': s is not None, 'surface': s if s is not None else 'none'}
            for m, s in {**track_creator.surfaces(kit), **info['mix_surfaces']}.items()}
    with progress.span(0.3, 0.85):
        res = import_folder({'track': track, 'folder': folder, 'files': [track_creator.OBJ_NAME], 'scale': 39.37,
                             'up': 'z', 'placement': 'absolute', 'materials': surf, 'road_material': 'Road',
                             'texture_size': '1024', 'force': True})
    # decor seme (onglet Creation, mode Decor) : objets du jeu poses sur le sol genere, semis precedent remplace
    items, dropped = track_creator.props_items(kit, req.get('props'), info.pop('_ground'), kit_prop_dims)
    with progress.span(0.85, 1.0, 'décor semé'):
        sown = place_library_many(track, items, 'creator')
    road = [{'file': o['file'], 'id': o['id']} for o in route_objects(track)['objects']
            if 'CreatorRoad' in (o['name'] or '')]               # nom prefixe du lot : « Createur_CreatorRoad »
    if not road:
        raise ValueError('route générée introuvable dans le décor après l\'import')
    return {'report': [f"piste de {info['length']:.0f} m, terrain {info['ground_tiles']} carreau(x) : {', '.join(info['materials'])}"
                      + (f", {len(info['mixes'])} fondu(s) de peinture" if info['mixes'] else '')
                      + (f", {info['trimmed_pct']} % de la carte retirés (loin de la route)" if info.get('trimmed_pct') else '')
                      + (f", {info['bridges']} pont(s)" if info['bridges'] else '')
                      + (f", {info['jumps']} saut(s)" if info['jumps'] else '')
                      + (f", barrières {info['walls_m']} m" if info['walls_m'] else '')
                      + (f", {sown['placed']} objet(s) de décor" if sown['placed'] else '')
                      + (f" ({dropped} trop près de la route ou au-dessus d'un saut, écarté(s))" if dropped else '')]
                      + res.get('report', []),
            'road': road, 'guide': info['guide'], 'exact': info['exact'], 'start': info['start'], 'yaw': info['yaw'],
            # plancher de chute 30 m sous le point le plus bas (celui enregistre peut venir d'une ancienne map plus haute :
            # T905 a z 9512 au-dessus d'un sol a 6812 -> les karts « tombaient » des le depart)
            'killz': info['min_z'] - 30 * 39.37}


# paveuse de l'onglet Creation : kart de l'equipe Crash (carrosserie : acteur ; roues : modeles de personnalisation,
# centrees sur le moyeu, essieu selon x)
CREATOR_KART_PAKS = ('kartteamcrash.pak', 'kartcustomization_wheels_kartteamcrash.pak')
CREATOR_KART = {'body': 'actors/Karts/KartTeamCrash/KartTeamCrash_Lod3.igz',
                'wheel_l': 'models/Karts/wheels/KartTeamCrash_Wheel_L_Lod1.igz',
                'wheel_r': 'models/Karts/wheels/KartTeamCrash_Wheel_R_Lod1.igz'}
_kart_cache = {}


def _kart_read(lg):
    for pak in CREATOR_KART_PAKS:
        try:
            return pak_tool.read_latest(ARCHIVES, lg, pak)[0]
        except KeyError:
            continue
    raise KeyError(lg)


def kart_preview(part='body'):
    """GET /api/kart?part=body|wheel_l|wheel_r : kart de l'equipe Crash (echelle 1:1, avant = +x) au format de
    model_preview_binary."""
    if part not in _kart_cache:
        pv = preview.model_preview(_kart_read(CREATOR_KART[part]), _kart_read)
        texs = sorted({g[2] for g in pv['groups'] if g[2]})
        head = struct.pack('<III', len(pv['positions']), len(pv['indices']), len(pv['groups']))
        groups = b''.join(struct.pack('<III', s, n, texs.index(t) + 1 if t else 0) for s, n, t in pv['groups'])
        js = json.dumps([{'ns': ns, 'decal': decal} for ns, decal in texs]).encode()
        _kart_cache[part] = (head + pv['positions'].astype('<f4').tobytes() + pv['uvs'].astype('<f4').tobytes()
                                + pv['indices'].astype('<u4').tobytes() + groups + struct.pack('<I', len(js)) + js)
    return _kart_cache[part]


def kart_texture(ns):
    """GET /api/kart_texture : texture du kart (PNG)."""
    from PIL import Image
    if ns not in _kart_cache:
        rgba, _ = preview.decode_texture(_kart_read(f'textures/{ns}.igz'), 512)
        buf = io.BytesIO()
        Image.fromarray(rgba, 'RGBA').save(buf, 'PNG')
        _kart_cache[ns] = buf.getvalue()
    return _kart_cache[ns]


_kit_model_cache = {}


def _kit_read(lg, pak):
    """Fichier d'un objet du kit : son archive, sinon la piste qui le contient (bibliotheque)."""
    try:
        return pak_tool.read_latest(ARCHIVES, lg, pak)[0]
    except KeyError:
        src = library.find_pak(ARCHIVES, lg, (pak,))
        if src is None:
            raise
        return pak_tool.read_latest(ARCHIVES, lg, src)[0]


def _kit_model(kit, kind, m):
    d = track_creator.KITS[kit]['props'][kind]
    model = d['models'][int(m) % len(d['models'])]
    if model not in _kit_model_cache:
        _kit_model_cache[model] = preview.model_preview(_kit_read(model, d['pak']), lambda lg: _kit_read(lg, d['pak']))
    return _kit_model_cache[model]


def kit_prop_dims(kit):
    """{type: [{r (rayon d'emprise depuis l'origine), zmin, zmax} en metres, par modele]} des objets du kit. Dimensions
    gardees sur le disque : lire tous les modeles du jeu a l'ouverture de la Creation prenait une trentaine de secondes."""
    out, cache = {}, _kit_dims_cache()
    before = len(cache)
    for kind, d in (track_creator.KITS[kit].get('props') or {}).items():
        out[kind] = []
        for m, model in enumerate(d['models']):
            if model not in cache:
                try:
                    P = np.nan_to_num(np.asarray(_kit_model(kit, kind, m)['positions'], np.float64)).reshape(-1, 3) / 39.37
                    cache[model] = {'r': round(float(np.hypot(P[:, 0], P[:, 1]).max()), 2),
                                    'zmin': round(float(P[:, 2].min()), 2), 'zmax': round(float(P[:, 2].max()), 2)}
                except Exception:  # noqa: BLE001 - modele illisible : emprise par defaut (non gardee)
                    traceback.print_exc()
                    out[kind].append({'r': 3.0, 'zmin': 0.0, 'zmax': 5.0})
                    continue
            out[kind].append(cache[model])
    if len(cache) != before:
        os.makedirs(OUT_DIR, exist_ok=True)
        json.dump(cache, open(os.path.join(OUT_DIR, 'kit_dims_cache.json'), 'w'))
    return out


_kit_dims = {}


def _kit_dims_cache():
    """{modele: dimensions}, relu du disque une fois par dossier de sortie."""
    if OUT_DIR not in _kit_dims:
        try:
            _kit_dims[OUT_DIR] = json.load(open(os.path.join(OUT_DIR, 'kit_dims_cache.json')))
        except (OSError, ValueError):
            _kit_dims[OUT_DIR] = {}
    return _kit_dims[OUT_DIR]


# reglage « Qualite » de l'onglet Creation -> allegement des objets de l'apercu : part des triangles visee, plancher,
# plafond, grilles essayees (finesse par etendue de l'objet), perte de silhouette toleree, dernier passage sans UV
LITE_LEVELS = {1: dict(share=1 / 2, low=800, high=6000, res=(128, 96, 64, 48, 32), lost=0.05, uv=8, merge=False),   # auto, moyenne
               2: dict(share=1 / 6, low=150, high=1200, res=(64, 48, 32, 24, 16, 12, 8), lost=0.2, uv=2, merge=True)}   # basse


def lite_model(pv, lod=1):
    """Copie allegee d'un objet pour l'apercu de l'onglet Creation SEULEMENT (la piste generee garde le vrai modele) :
    sommets proches fusionnes sur une grille, materiau par materiau, sans melanger des zones de texture differentes.
    Une piste de 3 879 objets en affichait 43 millions de triangles. lod 0 : modele d'origine (qualite maximale)."""
    if lod not in LITE_LEVELS:
        return pv
    L = LITE_LEVELS[lod]
    P, U, I = [np.nan_to_num(np.asarray(pv[k])) if k != 'indices' else np.asarray(pv[k]) for k in ('positions', 'uvs', 'indices')]
    n0 = len(I) // 3
    target = int(np.clip(n0 * L['share'], L['low'], L['high']))
    if n0 <= target or not len(P):
        return pv
    ext0 = np.maximum(P.max(0) - P.min(0), 1e-3)
    size = float(ext0.max()) or 1.0
    best = None
    # dernier passage (objets encore tres lourds, souvent de nombreux morceaux de texture) : zones de texture melangees
    for res, split_uv in [(r, True) for r in L['res']] + ([(L['res'][-2], False)] if L['merge'] else []):
        cell = size / res
        pos, uvs, idx, groups, base = [], [], [], [], 0
        for st, n, t in pv['groups']:
            tri = I[st:st + n]
            if not len(tri):
                continue
            used, inv = np.unique(tri, return_inverse=True)
            cols = [np.floor(P[used] / cell)] + ([np.round(np.clip(U[used], -1e6, 1e6) * L['uv'])] if split_uv else [])
            key = np.column_stack(cols).astype(np.int64)
            _, rep = np.unique(key, axis=0, return_inverse=True)
            rep = rep.ravel()
            cnt = np.bincount(rep).astype(np.float64)[:, None]
            gp = np.stack([np.bincount(rep, P[used][:, k]) for k in range(3)], 1) / cnt
            gu = np.stack([np.bincount(rep, U[used][:, k]) for k in range(2)], 1) / cnt
            t3 = rep[inv.ravel()].reshape(-1, 3)
            t3 = t3[(t3[:, 0] != t3[:, 1]) & (t3[:, 1] != t3[:, 2]) & (t3[:, 0] != t3[:, 2])]
            if not len(t3):                                  # materiau trop petit pour cette grille : garde tel quel
                t3 = rep[inv.ravel()].reshape(-1, 3)[:1]
            groups.append((sum(len(a) for a in idx), t3.size, t))
            pos.append(gp); uvs.append(gu); idx.append((t3 + base).ravel()); base += len(gp)
        tris = sum(len(a) for a in idx) // 3
        cand = {'positions': np.concatenate(pos).astype(np.float32), 'uvs': np.concatenate(uvs).astype(np.float32),
                'indices': np.concatenate(idx).astype(np.uint32), 'groups': groups}
        kept = cand['positions'][np.unique(cand['indices'])]
        if (1 - (kept.max(0) - kept.min(0)) / ext0).max() > L['lost']:
            break                                            # silhouette trop entamee (cloture, objet fin) : niveau d'avant
        if L['merge'] and split_uv and res == L['res'][-1] and tris <= 2 * target:
            best = cand
            break
        best = cand
        if tris <= target:
            break
    return best if best is not None and len(best['indices']) // 3 < n0 else pv


def kit_model_binary(kit, kind, m, lod=1):
    """GET /api/kit_model : objet du kit au format de model_preview_binary (apercu de l'onglet Creation), allege selon
    lod (voir LITE_LEVELS)."""
    d = track_creator.KITS[kit]['props'][kind]
    model = d['models'][int(m) % len(d['models'])]
    key = ('lite', model, lod)
    if key not in _kit_model_cache:
        _kit_model_cache[key] = lite_model(_kit_model(kit, kind, m), lod)
    pv = _kit_model_cache[key]
    texs = sorted({g[2] for g in pv['groups'] if g[2]})
    head = struct.pack('<III', len(pv['positions']), len(pv['indices']), len(pv['groups']))
    groups = b''.join(struct.pack('<III', st, n, texs.index(t) + 1 if t else 0) for st, n, t in pv['groups'])
    js = json.dumps([{'ns': ns, 'decal': decal} for ns, decal in texs]).encode()
    return (head + pv['positions'].astype('<f4').tobytes() + pv['uvs'].astype('<f4').tobytes()
            + pv['indices'].astype('<u4').tobytes() + groups + struct.pack('<I', len(js)) + js)


_creator_tex = {}


def creator_texture(kit, fname):
    """GET /api/creator_texture : texture du theme (route, matieres du sol) decodee comme a la generation (512)."""
    if kit not in _creator_tex:
        _creator_tex[kit] =track_creator.kit_textures(lambda lg, pak: pak_tool.read_latest(ARCHIVES, lg, pak)[0], kit, 512)
    return _creator_tex[kit][fname]


def kit_texture(kit, kind, ns):
    """GET /api/kit_texture : texture d'un objet du kit (PNG 256)."""
    from PIL import Image
    key = ('tex', ns)
    if key not in _kit_model_cache:
        rgba, _ = preview.decode_texture(_kit_read(f'textures/{ns}.igz', track_creator.KITS[kit]['props'][kind]['pak']), 256)
        buf = io.BytesIO()
        Image.fromarray(rgba, 'RGBA').save(buf, 'PNG')
        _kit_model_cache[key] = buf.getvalue()
    return _kit_model_cache[key]


def test_status():
    return dict(quick_test.STATUS)


def restore_game_all():
    """Retour au jeu d'origine (game_restore.py) : tout ce qui a ete installe ou cree est retire ; la liste locale
    des pistes installees est videe. -> {report}."""
    import game_restore
    if quick_test.emulator_running():
        raise RuntimeError('shadPS4 est ouvert : ferme-le avant de restaurer le jeu')
    remember_created_tracks()                           # nom et categorie : l'etat du menu va etre supprime
    _release_archives()
    report = game_restore.restore_game(ARCHIVES, progress=lambda f, t: progress.step(t, f))
    if os.path.exists(installed_path()):
        os.remove(installed_path())
    clear_caches()
    return {'report': report}


def restore_game_plan():
    """Ce que « Tout le jeu » retirerait (lecture seule, game_restore.restore_plan)."""
    import game_restore
    return game_restore.restore_plan(ARCHIVES, settings().get('lang') or 'fr')


def menu_track_archives(track):
    """Archives hors piste / mises a jour qui contiennent le nom ou les images de menu de la piste."""
    base = {os.path.join(ARCHIVES, n) for n in pak_tool.UPDATE_ARCHIVES + (track_pak(track),)}
    return sorted({a for lg in menu_logicals(track).values() for a in menu_archives(track, lg)} - base)


def uninstall_track(track):
    """Archives de la piste remises a l'origine ; les archives partagees gardent les fichiers des autres pistes
    installees (reinstalles aussitot). Piste pas installee : rien n'est touche ({not_installed: True})."""
    if track not in installed_tracks():
        return {'restored': [], 'kept': [], 'not_installed': True}
    done, kept = [], []
    arcs = [os.path.join(ARCHIVES, n) for n in pak_tool.UPDATE_ARCHIVES + (track_pak(track),)] + menu_track_archives(track) \
        + [os.path.join(ARCHIVES, n) for n in flyby.flyby_paks(os.listdir(ARCHIVES), track)]
    arcs = [a for a in arcs if os.path.exists(pak_tool.backup_path(a)) or custom_category.layer_has(a)]
    others = _others_for(arcs, track, kept)                 # avant de l'oublier : ses fichiers sont dans le registre
    _set_installed(track, False)
    for arc in arcs:
        _rewrite(arc, others.get(arc, {}))
        done.append(os.path.basename(arc))
    if set_menu_video(track, False):
        done.append(os.path.basename(menu_video(track)))
    try:
        done += apply_ghost_files(track, False)
    except OSError as e:
        kept.append(f'ATTENTION : fantômes non remis ({e})')
    return {'restored': done, 'kept': kept}


# -- onglet « Menu » : categories du menu du jeu et nouvelles pistes (custom_category.py, track_clone.py) ----------
NEW_TRACK_SOURCE = 'T111_Crash_Cove'


def _zone_display(zone, lang, created):
    """Nom affiche d'une zone : piste creee -> son nom ; piste du jeu -> son .lng (version installee)."""
    t = created.get(zone.lower())
    if t:
        return t.get('display') or t['id']
    tid = zone.lower().rsplit('/', 1)[-1]
    logical = f'maps/octane/{tid}/{tid}_zoneinfo_{lang}.lng'
    for pak in pak_tool.UPDATE_ARCHIVES + ('chunkinfos.pak', tid + '.pak'):
        p = os.path.join(ARCHIVES, pak)
        if not os.path.exists(p):
            continue
        a, idx, lock = pak_tool.cached_archive(p)
        e = idx.get(logical)
        if e is not None:
            with lock:
                return menu_assets.read_name(a.read(e))
    return tid


def menu_layout_info():
    """GET /api/menu_layout : {groups: [{id, key, title, game_title, levels: [{zone, name, track}]}], tracks}."""
    st = custom_category.read_state(ARCHIVES) or {}
    lang = custom_category.UI_LANG.get(settings().get('lang') or 'en', 'en')
    titles = custom_category.game_titles(ARCHIVES, lang)
    created = {track_clone.zone_name(t['id']): t for t in st.get('tracks', [])}
    groups = []
    for g in custom_category.current_layout(ARCHIVES, st):
        groups.append({'id': g.get('id'), 'key': g.get('key'), 'title': g.get('title'),
                       'game_title': titles.get(g['id']) if g.get('id') else None,
                       'levels': [{'zone': lv, 'name': _zone_display(lv, lang, created),
                                   'track': created[lv.lower()]['id'] if lv.lower() in created else None}
                                  for lv in g['levels']]})
    return {'groups': groups, 'tracks': st.get('tracks', []), 'source': NEW_TRACK_SOURCE}


def _release_archives():
    """Ferme les archives ouvertes par le serveur (Windows refuse de remplacer / supprimer un fichier ouvert)."""
    with pak_tool._cache_lock:
        for hit in pak_tool._cache.values():
            hit[1].f.close()
    for hit in pak_tool._orig_cache.values():
        hit[1].f.close()
    clear_caches()


def menu_layout_save(req):
    progress.step('menu du jeu (update2.pak)', 0.1)
    _release_archives()
    custom_category.set_layout(ARCHIVES, req['groups'])
    clear_caches()
    return menu_layout_info()


def free_track_number():
    """Numero de piste creee (T9NN) libre dans le jeu ET sans sauvegarde dans l'editeur : apres un retour au jeu d'origine,
    les numeros sont de nouveau libres dans le jeu mais les fichiers de l'ancienne piste restent, et menu_track_create
    les effacerait (reset_track). Les c_T9NN_* (plans de survol laisses par une piste supprimee) ne comptent pas."""
    paks = {f.lower() for f in os.listdir(ARCHIVES)}
    saved = [f.lower() for f in os.listdir(OUT_DIR)] if os.path.isdir(OUT_DIR) else []
    for n in range(1, 100):
        low = track_clone.new_id(NEW_TRACK_SOURCE, n).lower()
        if low + '.pak' not in paks and not any(f.startswith((low + '_', low + '.', 'staticcollision_' + low)) for f in saved):
            return n
    raise RuntimeError('plus aucun numéro de piste libre (T901 à T999)')


def menu_track_create(req):
    """Nouvelle piste : copie de Crash Cove (d'origine) renommee, rangee dans le groupe choisi, puis videe comme
    « Nouvelle map » (sol, decor, decor anime, effets, lumieres, sons, occultation) et installee : prete pour
    l'import d'une map."""
    if quick_test.emulator_running():
        raise RuntimeError('shadPS4 est ouvert : ferme-le avant de créer une piste')
    name = (req.get('name') or '').strip() or 'Custom Track'
    with progress.span(0.0, 0.6, 'copie de Crash Cove (≈ 360 Mo)'):
        new, written, _ = track_clone.create(ARCHIVES, NEW_TRACK_SOURCE, n=free_track_number(), display=name,
                                             progress=lambda f: progress.step(None, f))
    with progress.span(0.6, 0.75, 'enregistrement dans le menu du jeu'):
        _release_archives()
        custom_category.add_track(ARCHIVES, new, NEW_TRACK_SOURCE, name, written, req.get('group'))
        clear_caches()
    report = [f'{new} : {", ".join(written)}']
    if req.get('blank', True):
        reset_track(new, 'all')                         # restes d'une ancienne piste de meme numero
        with progress.span(0.75, 0.9, 'map vierge (nouvelle map)'):
            r = with_history(new, 'nouvelle map', lambda: apply_newmap(
                {'track': new, 'strip_ground': True, 'strip_art': art_files(new),
                 'move_away': [g[0] for g in MOVE_AWAY_GROUPS]}))
        report += [x for x in r.get('report', []) if x]
        with progress.span(0.9, 1.0, 'installation dans le jeu'):
            install_track(new)
    return {'track': new, 'report': report, 'menu': menu_layout_info(), 'tracks': list_tracks()}


def retired_path():
    return os.path.join(OUT_DIR, 'retired_tracks.json')


def read_retired():
    try:
        return json.load(open(retired_path(), encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def remember_created_tracks():
    """Avant un retour au jeu d'origine : nom, source et categorie des pistes creees, qui ne sont pas dans leurs sauvegardes."""
    st = custom_category.read_state(ARCHIVES) or {}
    info = read_retired()
    for t in st.get('tracks', []):
        zone = track_clone.zone_name(t['id'])
        g = next((g for g in st.get('layout') or [] if zone in {lv.lower() for lv in g['levels']}), None)
        info[t['id']] = {'display': t.get('display'), 'source': t.get('source'),
                         'group': {'key': g.get('key'), 'title': g.get('title'), 'added': not g.get('id')} if g else None}
    if info:
        os.makedirs(OUT_DIR, exist_ok=True)
        json.dump(info, open(retired_path(), 'w', encoding='utf-8'), indent=1, ensure_ascii=False)


def retired_tracks():
    """Pistes creees absentes du jeu dont les sauvegardes sont completes. Le fichier _newmap.json distingue une piste retiree
    d'une piste supprimee : la suppression l'efface (reset_track) et ne laisse que quelques reglages."""
    if not os.path.isdir(OUT_DIR):
        return []
    paks, info, out = {f.lower() for f in os.listdir(ARCHIVES)}, read_retired(), []
    for f in sorted(os.listdir(OUT_DIR)):
        m = re.match(r'^(T9\d\d_[A-Za-z_]+?)_newmap\.json$', f)
        if m and m.group(1).lower() + '.pak' not in paks:
            e = info.get(m.group(1), {})
            out.append({'id': m.group(1), 'display': e.get('display') or 'Custom Track', 'group': e.get('group')})
    return out


def _group_named(title):
    """Cle de la categorie de ce titre, creee (vide) si elle n'existe plus."""
    st = custom_category.read_state(ARCHIVES) or {}
    layout = custom_category.current_layout(ARCHIVES, st)
    g = next((g for g in layout if g.get('title') == title), None)
    if g:
        return g['key']
    key = custom_category.new_key(layout)
    st['layout'] = layout + [{'id': None, 'key': key, 'title': title, 'levels': []}]
    st.pop('levels', None)
    custom_category._write_state(ARCHIVES, st)
    return key


def retired_restore(req):
    """Remet dans le jeu une piste retiree : archives refaites depuis Crash Cove d'origine sous le MEME numero, enregistrement,
    puis installation de ses sauvegardes (intactes : ni reset_track ni « nouvelle map » ici)."""
    if quick_test.emulator_running():
        raise RuntimeError('shadPS4 est ouvert : ferme-le avant de remettre une piste')
    track = req['track']
    if track not in {t['id'] for t in retired_tracks()}:
        raise ValueError(f'{track} : pas une piste retirée du jeu')
    name = (req.get('name') or '').strip() or 'Custom Track'
    source = read_retired().get(track, {}).get('source') or NEW_TRACK_SOURCE
    with progress.span(0.0, 0.6, 'copie de Crash Cove (≈ 360 Mo)'):
        new, written, _ = track_clone.create(ARCHIVES, source, n=int(track[2:4]), display=name,
                                             progress=lambda f: progress.step(None, f))
    if new != track:
        raise RuntimeError(f'{new} créée au lieu de {track}')
    with progress.span(0.6, 0.7, 'enregistrement dans le menu du jeu'):
        _release_archives()
        group = _group_named(req['new_group']) if req.get('new_group') else req.get('group')
        custom_category.add_track(ARCHIVES, new, source, name, written, group)
        clear_caches()
    with progress.span(0.7, 1.0, 'installation de tes sauvegardes'):
        r = install_track(new)
    info = read_retired()
    if info.pop(track, None) is not None:
        json.dump(info, open(retired_path(), 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    return {'track': new, 'kept': r['kept'], 'menu': menu_layout_info(), 'tracks': list_tracks()}


def menu_track_delete(req):
    """Supprime une piste CREEE (jamais une piste du jeu) : archives .pak, enregistrement, sauvegardes de l'editeur."""
    track = req['track']
    st = custom_category.read_state(ARCHIVES) or {}
    if track not in {t['id'] for t in st.get('tracks', [])}:
        raise ValueError(f'{track} : pas une piste créée par l\'éditeur')
    removed = reset_track(track, 'all')['removed']           # lit encore l'archive de la piste : avant de l'effacer
    _release_archives()
    _set_installed(track, False)
    custom_category.remove_track(ARCHIVES, track, delete_paks=True)
    clear_caches()
    return {'removed': removed, 'menu': menu_layout_info(), 'tracks': list_tracks()}


def reset_track(track, what='all'):
    removed = []
    groups = {'race': (race_file(track), ttr_file(track), start_finish.design_file(track), start_finish.main_map_file(track),
                       powerup.powerup_file(track)) + tuple(minimap_logicals(track)) + tuple(menu_logicals(track).values()),
              'decor': tuple(art_files(track)) + (collision_file(track),) + tuple(moved_away_logicals(track))}
    targets = groups['race'] + groups['decor'] if what == 'all' else groups[what]
    if what in ('all', 'decor') and os.path.exists(links_path(track)):
        os.remove(links_path(track))
        removed.append(os.path.basename(links_path(track)))
    if what in ('all', 'decor') and os.path.exists(newmap_path(track)):
        os.remove(newmap_path(track))
        removed.append(os.path.basename(newmap_path(track)))
    if what in ('all', 'decor') and os.path.exists(lights_path(track)):
        os.remove(lights_path(track))
        removed.append(os.path.basename(lights_path(track)))
    if what in ('all', 'decor'):
        # modeles communs a plusieurs pistes (BoostPad) : gardes, les autres pistes les utilisent encore
        shared = set()
        for f in os.listdir(OUT_DIR):
            if f.endswith('_custom_models.json') and f != f'{track}_custom_models.json':
                shared |= set(json.load(open(os.path.join(OUT_DIR, f), encoding='utf-8')))
        for logical in custom_models(track):
            if logical not in shared and os.path.exists(custom_model_path(logical)):
                os.remove(custom_model_path(logical))
                removed.append(os.path.basename(logical))
        reg = os.path.join(OUT_DIR, f'{track}_custom_models.json')
        if os.path.exists(reg):
            os.remove(reg)
    for logical in targets:
        p = saved_path(logical)
        if os.path.exists(p):
            os.remove(p)
            removed.append(os.path.basename(p))
    if what == 'all':
        removed += music_clear(track, MUSIC_KINDS)
    return {'removed': removed}


class Handler(BaseHTTPRequestHandler):
    # HTTP/1.1 + connexion persistante : sous Windows, fermer la socket juste apres une grosse reponse
    # provoquait un RST cote client (reponses > ~1,5 Mo tronquees dans le navigateur).
    protocol_version = 'HTTP/1.1'

    def _send(self, code, body, ctype='application/json'):
        b = body if isinstance(body, bytes) else json.dumps(body).encode()
        gz = 'gzip' in (self.headers.get('Accept-Encoding') or '') and len(b) > 4096
        if gz:
            b = gzip.compress(b, 5)
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        if gz:
            self.send_header('Content-Encoding', 'gzip')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        try:
            if u.path in ('/', '/index.html'):
                # reglages (langue) fournis avant i18n.js, qui traduit la page des son chargement
                html = open(os.path.join(HERE, 'index.html'), 'rb').read()
                pre = f'<script>window.CTR_SETTINGS = {json.dumps({**settings(), "app_version": updater.VERSION})};</script>\n'.encode()
                self._send(200, html.replace(b'<script src="/i18n.js"></script>', pre + b'<script src="/i18n.js"></script>', 1),
                           'text/html; charset=utf-8')
            elif u.path == '/i18n.js':                    # traductions de l'interface
                self._send(200, open(os.path.join(HERE, 'i18n.js'), 'rb').read(), 'text/javascript; charset=utf-8')
            elif u.path.startswith('/vendor/'):              # three.js local (hors ligne)
                vendor = os.path.join(HERE, 'vendor')
                p = os.path.normpath(os.path.join(vendor, u.path[len('/vendor/'):]))
                if p.startswith(vendor + os.sep) and p.endswith('.js') and os.path.isfile(p):
                    self._send(200, open(p, 'rb').read(), 'text/javascript; charset=utf-8')
                else:
                    self._send(404, {'error': 'introuvable'})
            elif u.path == '/api/progress':
                self._send(200, progress.get())
            elif u.path == '/api/update_status':              # nouvelle version sur GitHub ? (une fois par lancement)
                self._send(200, updater.public_status(force='force' in parse_qs(u.query)))
            elif u.path == '/api/archives':
                self._send(200, archives_info())
            elif u.path == '/api/pack_tracks':                # pistes exportables en pack de maps
                self._send(200, {'tracks': mappack.exportable_tracks(), 'all': list_tracks()})
            elif u.path == '/api/octr_tracks':                # pistes exportables en mod pour le portage PC
                self._send(200, octr_export.tracks_info())
            elif u.path == '/api/pack_download':              # pack exporte (dossier exports du projet seulement)
                p = mappack.export_file(parse_qs(u.query).get('name', [''])[0])
                if p is None:
                    self._send(404, {'error': 'introuvable'})
                else:
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/zip')
                    self.send_header('Content-Disposition', f'attachment; filename="{os.path.basename(p)}"')
                    self.send_header('Content-Length', str(os.path.getsize(p)))
                    self.end_headers()
                    with open(p, 'rb') as f:
                        shutil.copyfileobj(f, self.wfile)
            elif u.path == '/api/tracks':
                self._send(200, list_tracks())
            elif u.path == '/api/menu_layout':                # onglet Menu : categories et pistes creees
                self._send(200, menu_layout_info())
            elif u.path == '/api/track':
                self._send(200, load_track(parse_qs(u.query)['name'][0]))
            elif u.path == '/api/collision':                 # sol gris seul (relu apres un enregistrement)
                self._send(200, load_collision(parse_qs(u.query)['track'][0]))
            elif u.path == '/api/decor':
                self._send(200, load_decor(parse_qs(u.query)['name'][0]))
            elif u.path == '/api/decor_collision':
                q = parse_qs(u.query)
                self._send(200, decor_collision_preview(q['track'][0], q['file'][0], int(q['id'][0])))
            elif u.path == '/api/model_parts':               # edition de forme : textures du modele
                q = parse_qs(u.query)
                self._send(200, model_parts(q['track'][0], q['file'][0]))
            elif u.path == '/api/materials':
                self._send(200, material_catalog(parse_qs(u.query)['track'][0]))
            elif u.path == '/api/model_preview':
                q = parse_qs(u.query)
                self._send(200, model_preview_binary(q['track'][0], q['file'][0]), 'application/octet-stream')
            elif u.path == '/api/texture':
                q = parse_qs(u.query)
                self._send(200, texture_png(q['track'][0], q['ns'][0]), 'image/png')
            elif u.path == '/api/tint_preview':              # colorisation : apercu d'une texture teintee
                q = parse_qs(u.query)
                self._send(200, tint_preview(q['track'][0], q.get('ns', [''])[0], q['color'][0],
                                             float(q.get('strength', ['1'])[0]), q.get('mode', ['tint'])[0]), 'image/png')
            elif u.path == '/api/model':
                q = parse_qs(u.query)
                self._send(200, model_binary(q['track'][0], q['file'][0]), 'application/octet-stream')
            elif u.path == '/api/library':
                self._send(200, library_catalog())
            elif u.path == '/api/route_objects':
                self._send(200, route_objects(parse_qs(u.query)['track'][0]))
            elif u.path == '/api/test_status':               # « Tester en jeu » : etape en cours
                self._send(200, test_status())
            elif u.path == '/api/creator':                   # onglet Creation : trace du paveur enregistre
                self._send(200, creator_info(parse_qs(u.query)['track'][0]))
            elif u.path == '/api/kart':                      # onglet Creation : kart du jeu (paveuse)
                self._send(200, kart_preview(parse_qs(u.query).get('part', ['body'])[0]), 'application/octet-stream')
            elif u.path == '/api/kit_model':                 # onglet Creation : objet a semer (apercu)
                q = parse_qs(u.query)
                self._send(200, kit_model_binary(q['kit'][0], q['type'][0], q.get('m', ['0'])[0], int(q.get('lod', ['1'])[0])), 'application/octet-stream')
            elif u.path == '/api/creator_texture':
                q = parse_qs(u.query)
                self._send(200, creator_texture(q['kit'][0], q['f'][0]), 'image/png')
            elif u.path == '/api/kit_texture':
                q = parse_qs(u.query)
                self._send(200, kit_texture(q['kit'][0], q['type'][0], q['ns'][0]), 'image/png')
            elif u.path == '/api/kart_texture':
                self._send(200, kart_texture(parse_qs(u.query)['ns'][0]), 'image/png')
            elif u.path == '/creator.js':                    # onglet Creation : paveur (module de la page)
                self._send(200, open(os.path.join(HERE, 'creator.js'), 'rb').read(), 'text/javascript; charset=utf-8')
            elif u.path == '/api/route_start':               # depart propose : objet Start / Finish, sinon damier
                self._send(200, route_start_guess(parse_qs(u.query)['track'][0]))
            elif u.path == '/api/music':                      # musique de la piste : etat
                self._send(200, music_info(parse_qs(u.query)['track'][0]))
            elif u.path == '/api/times':                      # temps des reliques et des fantomes
                self._send(200, times_info(parse_qs(u.query)['track'][0]))
            elif u.path == '/api/music_audio':                # ecoute : flux joue en course, en MP3
                q = parse_qs(u.query)
                self._send(200, music_audio(q['track'][0], q['kind'][0]), 'audio/mpeg')
            elif u.path == '/api/old_route_moves':            # vider la scene : entites de l'ancien trace sous la carte
                d, r = old_route_moves(parse_qs(u.query)['track'][0])
                self._send(200, {'design_moves': d, 'race_moves': r})
            else:
                self._send(404, {'error': 'introuvable'})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self._send(500, {'error': repr(e)})

    PROGRESS_LABELS = {'/api/update_download': 'Mise à jour', '/api/update_apply': 'Mise à jour', '/api/octr_export': 'Export pour le PC (OCTR)', '/api/pack_export': 'Export des maps', '/api/pack_import': 'Import des maps',
                       '/api/save': 'Enregistrement de la course', '/api/install': 'Installation dans le jeu',
                       '/api/test_in_game': 'Tester en jeu', '/api/create_build': 'Création de la piste',
                       '/api/uninstall': 'Désinstallation', '/api/restore_all': 'Retour au jeu d\'origine', '/api/reset': "Retour à l'original",
                       '/api/decor_save': 'Enregistrement du décor', '/api/import_model': 'Import du modèle',
                       '/api/set_custom_material': 'Texture du modèle', '/api/import_texture': "Import de l'image",
                       '/api/newmap': 'Nouvelle map', '/api/undo_save': 'Annulation',
                       '/api/gen_ai_splines': 'Génération des splines IA', '/api/route_layout': 'Création du parcours',
                       '/api/crates_auto': 'Placement des caisses', '/api/check': 'Vérification avant installation',
                       '/api/alpha_textures': 'Analyse des textures', '/api/set_alpha_textures': 'Transparence des textures',
                       '/api/minimap': 'Mini-carte', '/api/folder_scan': 'Analyse du dossier',
                       '/api/import_folder': 'Import du dossier', '/api/export_obj': 'Export OBJ',
                       '/api/light_info': 'Analyse du poids de la map', '/api/map_weight': 'Poids de la map en jeu', '/api/apply_light': 'Allègement de la map',
                       '/api/auto_falls': 'Chutes et réapparitions', '/api/menu_info': 'Lecture du nom et des images',
                       '/api/apply_menu': 'Nom et images de la piste', '/api/set_surface': 'Type de sol', '/api/mesh_save': 'Forme de l\'objet', '/api/recolor': 'Couleur de l\'objet',
                       '/api/object_alpha': 'Transparence de la texture', '/api/surfaces': 'Types de sol',
                       '/api/ambiance_info': "Lecture de l'éclairage", '/api/set_ambiance': 'Ambiance',
                       '/api/place_library': "Ajout d'un objet de la bibliothèque", '/api/fix': 'Corrections',
                       '/api/walls_auto': 'Murs invisibles', '/api/wall_add': 'Mur invisible',
                       '/api/walls_zone': 'Murs invisibles autour de la sélection',
                       '/api/set_invisible': 'Mur invisible', '/api/menu_layout_save': 'Menu du jeu',
                       '/api/menu_track_create': 'Nouvelle piste',
                       '/api/menu_track_delete': 'Suppression de la piste',
                       '/api/retired_restore': 'Remise de la piste dans le jeu',
                       '/api/music_apply': 'Import de la musique'}

    def do_POST(self):
        try:
            if urlparse(self.path).path == '/api/pack_upload':      # pack de maps (.zip) : octets bruts
                from urllib.parse import unquote
                data = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                name = unquote(parse_qs(urlparse(self.path).query).get('name', ['pack.zip'])[0])
                self._send(200, mappack.save_upload(data, name))
                return
            if urlparse(self.path).path == '/api/music_upload':     # musique a importer : octets bruts
                from urllib.parse import unquote
                data = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                q = parse_qs(urlparse(self.path).query)
                self._send(200, music_upload(data, unquote(q.get('name', ['musique'])[0]), bool(q.get('keep'))))
                return
            req = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
            routes = {'/api/save': lambda: with_history(req['track'], 'course', lambda: save_track(req)),
                      '/api/music_apply': lambda: with_history(req['track'], 'musique de la piste', lambda: music_apply(req)),
                      '/api/music_reset': lambda: with_history(req['track'], 'musique d\'origine', lambda: music_reset(req)),
                      '/api/pick_ffmpeg': lambda: pick_ffmpeg(req),
                      '/api/times_apply': lambda: with_history(req['track'], 'temps des reliques et des fantômes',
                                                               lambda: times_apply(req)),
                      '/api/times_reset': lambda: with_history(req['track'], 'temps du jeu', lambda: times_reset(req)),
                      '/api/install': lambda: install_track(req['track']),
                      '/api/test_in_game': lambda: test_in_game(req),
                      '/api/create_build': lambda: with_history(req['track'], 'création de la piste (paveur)',
                                                                lambda: create_build(req)),
                      '/api/uninstall': lambda: uninstall_track(req['track']),
                      '/api/restore_plan': restore_game_plan,
                      '/api/restore_all': restore_game_all,
                      '/api/retired_tracks': lambda: {'tracks': retired_tracks()},
                      '/api/retired_restore': lambda: retired_restore(req),
                      '/api/reset': lambda: with_history(req['track'], f"repartir de l'original ({req.get('what', 'all')})",
                                                         lambda: reset_track(req['track'], req.get('what', 'all'))),
                      '/api/decor_save': lambda: with_history(req['track'], 'decor', lambda: save_decor(req)),
                      '/api/import_model': lambda: with_history(req['track'], f"import {req.get('name') or ''}",
                                                                lambda: import_model(req)),
                      '/api/set_custom_material': lambda: with_history(req['track'], 'texture d\'un modele importe',
                                                                       lambda: set_custom_material(req)),
                      '/api/import_texture': lambda: with_history(req['track'], f"image {req.get('name') or ''}",
                                                                  lambda: import_texture(req)),
                      '/api/newmap': lambda: with_history(req['track'], 'nouvelle map', lambda: apply_newmap(req)),
                      '/api/undo_save': lambda: undo_save(req['track']),
                      '/api/history': lambda: {'labels': history_list(req['track'])},
                      '/api/gen_ai_splines': lambda: gen_ai_splines(req),
                      '/api/route_layout': lambda: route_layout(req),
                      '/api/crates_auto': lambda: crates_auto(req),
                      '/api/check': lambda: preinstall_check(req['track']),
                      '/api/alpha_textures': lambda: alpha_texture_list(req['track']),
                      '/api/set_alpha_textures': lambda: with_history(req['track'], 'transparence des textures',
                                                                      lambda: set_alpha_textures(req['track'], req.get('wanted'))),
                      '/api/minimap': lambda: (generate_minimap(req['track'], req.get('move'), req.get('flip'))
                                               if req.get('move') or req.get('flip')        # reglage fin / miroir : sans historique
                                                 else with_history(req['track'], 'mini-carte', lambda: generate_minimap(req['track']))),
                      '/api/folder_scan': lambda: folder_scan(req),
                      '/api/light_info': lambda: light_info(req['track']),
                      '/api/map_weight': lambda: map_weight(req['track']),
                      '/api/ambiance_info': lambda: ambiance_info(req['track']),
                      '/api/set_ambiance': lambda: with_history(req['track'], 'ambiance', lambda: set_ambiance(req)),
                      '/api/surfaces': lambda: {'surfaces': [{'value': s, 'label': l, 'safe': ok, **surface_params().get(s, {}),
                                                              'defaults': surface_defaults(s)} for s, l, ok in SURFACES]},
                      '/api/set_surface': lambda: with_history(req['track'], 'type de sol', lambda: set_surface(req)),
                      '/api/object_alpha': lambda: with_history(req['track'], 'transparence', lambda: set_object_alpha(req)),
                      '/api/mesh_save': lambda: with_history(req['track'], 'forme d\'un objet', lambda: mesh_save(req)),
                      '/api/recolor': lambda: with_history(req['track'], 'couleur d\'un objet', lambda: recolor(req)),
                      '/api/double_sided': lambda: with_history(req['track'], 'faces des deux côtés', lambda: set_double_sided(req)),
                      '/api/object_glow': lambda: with_history(req['track'], 'texture lumineuse', lambda: set_object_glow(req)),
                      '/api/menu_info': lambda: menu_info(req['track']),
                      '/api/apply_menu': lambda: with_history(req['track'], 'nom et images de menu', lambda: apply_menu(req)),
                      '/api/auto_falls': lambda: with_history(req['track'], 'chutes et réapparitions', lambda: auto_falls(req)),
                      '/api/apply_light': lambda: with_history(req['track'], 'alléger la map', lambda: apply_light(req)),
                      '/api/import_folder': lambda: with_history(req['track'], f"import du dossier {req.get('folder') or 'map'}",
                                                                 lambda: import_folder(req)),
                      '/api/export_obj': lambda: export_obj(req),
                      '/api/scene_points': lambda: scene_points(req),
                      '/api/archives': lambda: choose_archives(req),
                      '/api/pick_folder': lambda: pick_folder(req),
                      '/api/flyby_auto': lambda: flyby_auto(req),
                      '/api/pack_export': lambda: mappack.export_pack(req),
                      '/api/update_download': lambda: updater.download(),
                      '/api/update_apply': lambda: update_apply(),
                      '/api/octr_export': lambda: octr_export.build(req),
                      '/api/pack_import': lambda: mappack.import_pack(req),
                      '/api/fix': lambda: with_history(req['track'], 'corrections : ' + ', '.join(req.get('fixes') or []),
                                                       lambda: apply_fixes(req)),
                      '/api/place_library': lambda: with_history(req['track'], f"bibliothèque : {os.path.basename(req.get('model') or '')[:-4]}",
                                                                 lambda: place_library(req)),
                      '/api/walls_auto': lambda: with_history(req['track'], 'murs invisibles automatiques', lambda: walls_auto(req)),
                      '/api/wall_add': lambda: with_history(req['track'], 'mur invisible', lambda: wall_add(req)),
                      '/api/walls_zone': lambda: with_history(req['track'], 'murs invisibles autour de la sélection',
                                                              lambda: walls_zone(req)),
                      '/api/set_invisible': lambda: with_history(req['track'], 'mur invisible' if req.get('invisible') else 'mur visible',
                                                                 lambda: set_invisible(req)),
                      '/api/menu_layout_save': lambda: menu_layout_save(req),
                      '/api/menu_track_create': lambda: menu_track_create(req),
                      '/api/menu_track_delete': lambda: menu_track_delete(req)}
            if self.path == '/api/settings':                 # rapide, sans verrou ni barre de progression
                self._send(200, set_settings(req))
            elif self.path in routes:
                # une seule operation d'ecriture a la fois : une installation lancee pendant un enregistrement
                # (recalcul de la collision ~5 s) partait sans le .hkx pas encore ecrit
                with WRITE_LOCK:
                    progress.begin(self.PROGRESS_LABELS.get(self.path, 'Opération'))
                    try:
                        result = routes[self.path]()
                    finally:
                        progress.end()
                self._send(200, result)
            else:
                self._send(404, {'error': 'introuvable'})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self._send(500, {'error': repr(e)})

    def log_message(self, fmt, *args):
        sys.stderr.write('%s\n' % (fmt % args))


def configure(archives=None, out_dir=None, project_dir=None, config=None):
    """Dossiers utilises (application .exe : archives choisies par l'utilisateur, sauvegardes et dossiers de maps a
    cote de l'exe ; sinon ceux du projet). A appeler avant de servir."""
    global ARCHIVES, OUT_DIR, PROJECT_DIR, CONFIG
    if archives:
        ARCHIVES = archives
    if out_dir:
        OUT_DIR = out_dir
    if project_dir:
        PROJECT_DIR = project_dir
    if config:
        CONFIG = config


# --- dossier des archives du jeu : choix depuis l'editeur (navigateur ou application), pris en compte aussitot ---
CONFIG = os.path.join(os.path.dirname(os.path.dirname(HERE)), 'ctr_editor_config.json')


def valid_archives(path):
    """Dossier « archives » du jeu (CUSA13795) : update.pak et au moins une archive de piste."""
    try:
        names = {n.lower() for n in os.listdir(path)}
    except (OSError, TypeError):
        return False
    return 'update.pak' in names and any(n.startswith('t1') and n.endswith('.pak') for n in names)


def load_config():
    try:
        return json.load(open(CONFIG, encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def clear_caches():
    """Oublie tout ce qui a ete lu dans les archives (caches du module et archives ouvertes de pak_tool)."""
    for name, v in list(globals().items()):
        if name.startswith('_') and (name.endswith('_cache') or name in ('_aggressive_ok', '_surface_params')) \
                and isinstance(v, (dict, list)):
            v.clear()
    with pak_tool._cache_lock:
        pak_tool._cache.clear()
    pak_tool._orig_cache.clear()


def save_config(**values):
    json.dump(dict(load_config(), **values), open(CONFIG, 'w', encoding='utf-8'), indent=1)


def set_archives(path):
    global ARCHIVES
    path = os.path.normpath(path)
    if not valid_archives(path):
        raise ValueError(f'{path} ne contient pas les archives du jeu (update.pak, t111_crash_cove.pak…). '
                         'Choisis le dossier « archives » du jeu installé pour shadPS4.')
    if os.path.normcase(path) != os.path.normcase(ARCHIVES):
        ARCHIVES = path
        clear_caches()
    save_config(archives=path)
    return path


FOLDER_DIALOG = None           # (titre, dossier initial) -> chemin ou None : fenetre de l'application (app.py, Linux)


def _ask_folder_tk(title, initial):
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    try:
        return filedialog.askdirectory(parent=root, mustexist=True, title=title, initialdir=initial)
    finally:
        root.destroy()


def _ask_folder_linux(title, initial):
    """zenity (GNOME...) ou kdialog (KDE). None si aucun des deux ; '' si annule."""
    kde = 'KDE' in os.environ.get('XDG_CURRENT_DESKTOP', '').upper()
    tools = ('kdialog', 'zenity') if kde else ('zenity', 'kdialog')
    tool = next((t for t in tools if shutil.which(t)), None)
    if not tool:
        return None
    if tool == 'zenity':
        cmd = ['zenity', '--file-selection', '--directory', '--title', title]
        cmd += ['--filename', os.path.join(initial, '')] if initial else []
    else:
        cmd = ['kdialog', '--title', title, '--getexistingdirectory', initial or os.path.expanduser('~')]
    env = dict(os.environ)
    if getattr(sys, 'frozen', False):                 # PyInstaller : bibliotheques du systeme pour l'outil, pas les notres
        orig = env.pop('LD_LIBRARY_PATH_ORIG', None)
        env.pop('LD_LIBRARY_PATH', None)
        if orig:
            env['LD_LIBRARY_PATH'] = orig

    # bloque jusqu'au choix
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)

    # chemin sur stdout ; code 1 = annule
    return r.stdout.strip() if r.returncode == 0 else ''


def ask_folder(title, initial=None):
    """Fenetre de choix de dossier, ouverte par le serveur (meme PC) au premier plan : celle de l'application si
    elle en fournit une, sinon zenity / kdialog sous Linux (tkinter souvent absent), sinon tkinter."""
    initial = initial if initial and os.path.isdir(initial) else None

    # None = pas de fenetre disponible, '' = annule
    path = None
    if FOLDER_DIALOG:
        
        path = FOLDER_DIALOG(title, initial)
    elif sys.platform.startswith('linux'):
        # 2. zenity / kdialog
        path = _ask_folder_linux(title, initial)
    if path is None and not FOLDER_DIALOG:
        # 3. tkinter
        try:
            path = _ask_folder_tk(title, initial)
        except ImportError:
            raise RuntimeError('aucune fenêtre de choix de dossier disponible : installer zenity (ou python3-tk), '
                               'ou lancer le serveur avec --archives "<dossier archives du jeu>"')
    return os.path.normpath(path) if path else None


def ask_archives_folder():
    return ask_folder('Dossier « archives » de Crash Team Racing Nitro-Fueled (CUSA13795)', ARCHIVES)


def pick_folder(req):
    """POST /api/pick_folder : dossier a importer (OBJ / DAE + textures) ; relatif au projet s'il y est."""
    initial = req.get('initial') or ''
    if initial and not os.path.isabs(initial):
        initial = os.path.join(PROJECT_DIR, initial)
    path = ask_folder('Dossier de la map à importer (OBJ ou DAE + textures)', initial if os.path.isdir(initial) else PROJECT_DIR)
    if not path:
        return {'ok': False}
    rel = os.path.relpath(path, PROJECT_DIR) if os.path.splitdrive(path)[0].lower() == os.path.splitdrive(PROJECT_DIR)[0].lower() else path
    return {'ok': True, 'folder': rel if not rel.startswith('..') else path}


# reglages de l'interface gardes par le serveur (le stockage du navigateur depend du port : perdu par l'application)
SETTINGS_KEYS = ('lang',)


def settings():
    return {k: v for k, v in load_config().items() if k in SETTINGS_KEYS}


def set_settings(req):
    save_config(**{k: req[k] for k in SETTINGS_KEYS if isinstance(req.get(k), str)})
    return settings()


def archives_info():
    return {'path': ARCHIVES, 'valid': valid_archives(ARCHIVES)}


def choose_archives(req):
    """POST /api/archives : {path} donne, sinon fenetre de choix. Annule => {ok: False, cancelled: True}."""
    path = req.get('path') or ask_archives_folder()
    if not path:
        return {'ok': False, 'cancelled': True, **archives_info()}
    return {'ok': True, 'path': set_archives(path), 'valid': True}


def update_apply():
    """Lance la nouvelle version (elle attend la fin de celle-ci), puis ferme l'application."""
    r = updater.start_apply()
    threading.Timer(0.4, lambda: APP_QUIT() if APP_QUIT else os._exit(0)).start()
    threading.Timer(10.0, lambda: os._exit(0)).start()   # fenetre bloquee : la mise a jour attend cette fin
    return r


def serve(port=8765, host='127.0.0.1'):
    """Serveur pret (pas encore demarre) : httpd.serve_forever() dans un fil, httpd.shutdown() pour arreter."""
    ThreadingHTTPServer.request_queue_size = 128      # le client charge des dizaines de modeles a la fois
    return ThreadingHTTPServer((host, port), Handler)


def main(argv):
    port = int(argv[argv.index('--port') + 1]) if '--port' in argv else 8765
    if '--archives' in argv:
        configure(archives=argv[argv.index('--archives') + 1])
    elif valid_archives(load_config().get('archives')):    # dossier choisi depuis l'editeur
        configure(archives=load_config()['archives'])
    print(f'editeur CTR : http://localhost:{port}  (archives : {ARCHIVES})', flush=True)
    serve(port).serve_forever()


if __name__ == '__main__':
    main(sys.argv)
