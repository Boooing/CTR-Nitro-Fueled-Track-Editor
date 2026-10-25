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
import sys
import threading
import time
import traceback
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import pak_tool  # noqa: E402
import ai_gen  # noqa: E402
import numpy as np  # noqa: E402
import obj_export  # noqa: E402
import library  # noqa: E402
import pkg_manifest  # noqa: E402
import powerup  # noqa: E402
import progress  # noqa: E402
import minimap  # noqa: E402
import preview  # noqa: E402
import route_gen  # noqa: E402
import start_finish  # noqa: E402
import teleport  # noqa: E402
import texture_build  # noqa: E402
from collision import decode_compressed_mesh, transform  # noqa: E402
from collision_edit import CollisionFile  # noqa: E402
from collision_region import GroundEditor, apply, mat_inv_rigid_scale, mat_mul, object_matrix  # noqa: E402
from decor import ENTITY_TYPES, DecorFile, model_logical_path, model_mesh  # noqa: E402
from igz import IgzFile  # noqa: E402
from model_build import (TEMPLATE, build_model, complete_mesh, model_materials, obj_extents, obj_material_extents,  # noqa: E402
                         obj_summary, parse_mtl,
                         parse_obj_groups, set_material)
from havok import Packfile  # noqa: E402
from race_entities import RaceSystemEditor, TTRStatsEditor  # noqa: E402
from race_system import RaceSystem  # noqa: E402

ARCHIVES = ''                  # dossier « archives » du jeu : --archives, sinon ctr_editor_config.json, sinon demande par la page
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(HERE)), 'out', 'editor')
HAVOK_TO_GAME = 39.37          # metres -> pouces
LIST_KEYS = ('previous_ai', 'next_ai', 'previous_position', 'next_position')
WRITE_LOCK = threading.Lock()


def track_pak(track):
    return track.lower() + '.pak'


def race_file(track):
    return f'maps/Octane/{track}/{track}_RaceSystem.igz'


def ttr_file(track):
    return f'ttrStats/{track}_TTRStats.igz'


def collision_file(track):
    return f'models/maps/Octane/{track}/StaticCollision_{track}.hkx'


def saved_path(logical):
    return os.path.join(OUT_DIR, os.path.basename(logical))


def list_tracks():
    out = []
    for f in sorted(os.listdir(ARCHIVES)):
        m = re.match(r'^(t\d{3}_[a-z_]+)\.pak$', f)
        if m and 'flyby' not in f:
            arc = pak_tool.IgaArchive(os.path.join(ARCHIVES, f))
            names = [e.logical_name for e in arc.entries if e.logical_name.endswith('_RaceSystem.igz')]
            arc.f.close()
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
    return col


def load_track(track):
    data, src = base_file(track, race_file(track))
    rs = RaceSystem(data, file_ns=f'{track}_RaceSystem').decode()
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
        crates = powerup.read_crates(base_file(track, powerup.powerup_file(track))[0])
    except KeyError:
        crates = []
    return {'track': track, 'source': src, 'saved': src.startswith(OUT_DIR), 'splines': splines,
            'transitions': transitions, 'forks': rs['fork_checkers'], 'player_starts': rs['player_starts'],
            'starting_splines': starting, 'start_grid': grid, 'player_start': player_start, 'crates': crates,
            'teleporters': teleporters_of(track, ed), 'original_start': original_start(track),
            'collision': load_collision(track)}


# -- teleporteurs (mecanisme de Spyro Circuit, voir teleport.py) ---------------------------------
def teleporters_of(track, ed):
    """{transition: {'arrival': entite du _Design, 'pos', 'yaw'}} des transitions teleporteurs."""
    tps = teleport.read_teleporters(ed.igz, {n: o for n, o in ed.by_name.items()
                                             if ed.igz.objects.get(o) in DESIGN_ENTITY_TYPES})
    if not tps:
        return {}
    try:
        dz = IgzFile(base_file(track, start_finish.design_file(track))[0])
    except KeyError:
        dz = None
    roots = {n: o for n, o in dz.root_objects() if n} if dz else {}
    out = {}
    for tname, arrival in tps.items():
        ent = roots.get(arrival)
        pos, yaw = None, 0.0
        if ent is not None:
            pos = [round(v, 2) for v in dz.vec3(ent + 0x20)]
            tr = dz.deref(ent + 0x30)
            yaw = round(struct.unpack_from('<f', *dz._loc(tr + 0x68))[0], 5) if tr is not None else 0.0
        out[tname] = {'arrival': arrival, 'pos': pos, 'yaw': yaw}
    return out


def apply_teleporters(track, ed, want, rs_data):
    """Teleporteurs voulus : want = {transition: {'pos': [x, y, z], 'yaw'}} (les autres redeviennent ordinaires).
    Arrivees = entites du _Design clonees d'un point de reapparition (ecrit tout de suite) ; RaceSystem modifie
    dans ed (ecrit par save_track). Retourne les lignes du rapport."""
    report = []
    ents = {n: o for n, o in ed.by_name.items() if ed.igz.objects.get(o) in DESIGN_ENTITY_TYPES}
    current = teleport.read_teleporters(ed.igz, ents)
    for tname in current:
        if tname not in want and teleport.clear_teleporter(ed.igz, ents[tname]):
            report.append(f'{tname} : plus un téléporteur')
    want = {t: w for t, w in want.items() if t in ents and w.get('pos')}
    if not want:
        return report
    # arrivees dans le _Design : entite sans composant, comme Destination_01 de Spyro Circuit
    design = start_finish.design_file(track)
    dz = IgzFile(base_file(track, design)[0])
    roots = {n: o for n, o in dz.root_objects() if n}
    missing = [t for t in want if teleport.dest_name(t) not in roots]
    if missing:
        rs = RaceSystem(rs_data, file_ns=f'{track}_RaceSystem').decode()
        respawns = [str(r).split('::')[-1] for s in rs['position_paths'] for r in (s.get('respawn_points') or [])]
        cands = [n for n in respawns if n in roots]
        template = next((n for n in cands if f'{n}_camera' not in roots), cands[0] if cands else None)
        if template is None:
            raise ValueError('aucun point de réapparition dans le _Design (modèle de l\'arrivée du téléporteur)')
        owned = dz.owned_by(DESIGN_ENTITY_TYPES)
        names = {o: n for n, o in dz.root_objects()}
        pairs = []
        for t in missing:
            pairs += dz.clone_owned(roots[template], teleport.dest_name(t), owned[roots[template]], names)[1]
        dz.add_roots(pairs)
        roots = {n: o for n, o in dz.root_objects() if n}
    for t, w in want.items():
        _set_pose(dz, roots[teleport.dest_name(t)], [float(c) for c in w['pos']], float(w.get('yaw') or 0.0))
    safe_compact(track, design, dz)
    dz.save(saved_path(design))
    # RaceSystem : drapeau, script de teleportation, handle vers l'arrivee
    src = teleport.donor(lambda lg, pak: pak_tool.read_latest(ARCHIVES, lg, pak)[0])
    for t, w in want.items():
        teleport.set_teleporter(ed.igz, ents[t], t, teleport.dest_name(t), f'{track}_Design', src)
        report.append(f'{t} : téléporteur vers ({", ".join(str(round(c)) for c in w["pos"])})')
    return report


def teleport_install_files(track):
    """(entrees du manifeste, {chemin: archive source} a copier) si la piste enregistree a des teleporteurs."""
    p = saved_path(race_file(track))
    if not os.path.exists(p):
        return [], {}
    ed = RaceSystemEditor(open(p, 'rb').read(), track)
    if not teleport.read_teleporters(ed.igz, {n: o for n, o in ed.by_name.items()
                                              if ed.igz.objects.get(o) in DESIGN_ENTITY_TYPES}):
        return [], {}
    copies = {}
    for _, lg in teleport.FILES:
        if not library.available(ARCHIVES, lg, track_pak(track)):
            src = library.find_pak(ARCHIVES, lg, (teleport.DONOR[0],))
            if src is None:
                raise KeyError(f'fichier du téléporteur introuvable dans les archives : {lg}')
            copies[_archive_case(src, lg)] = src
    return list(teleport.FILES), copies


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
        fin = next(t for t in RaceSystem(read(race_file(track)), file_ns=f'{track}_RaceSystem').decode()['transitions']
                   if t['increment_lap'])
        pos, yaw, _ = start_finish.transition_pose(ed, fin['name'])
        ps = start_finish.read_player_start(read(start_finish.main_map_file(track)))
    except (KeyError, StopIteration):
        return None
    return {'grid': grid, 'ps': ps, 'finish': {'position': pos, 'yaw': yaw}} if grid else None


def set_points(ed, name, pts):
    cur = ed.points(name)
    while len(cur) > len(pts):
        ed.remove_point(name, len(cur) - 1)
        cur = ed.points(name)
    while len(cur) < len(pts):
        ed.insert_point(name, len(cur), pts[len(cur)])
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
    return hashlib.md5(base_file(track, collision_file(track))[0]).hexdigest()


def ground_for(track):
    """Sol (collision enregistree, decor importe compris), en cache tant qu'il ne change pas."""
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
    if src.get('objects'):                               # ids -> noms (les ids changent a chaque reecriture du decor)
        named = []
        for ref in src['objects']:
            df = DecorFile(base_file(track, ref['file'])[0])
            if int(ref['id']) not in df.names:
                raise ValueError(f"objet {ref['id']} introuvable (enregistre le decor d'abord)")
            named.append({'file': ref['file'], 'name': df.names[int(ref['id'])]})
        src = {'objects': named}
    progress.step('lecture de la route', 0.02)
    tris = road_tris(track, src)
    if not len(tris):
        raise ValueError('aucun triangle de route')
    bad = None
    try:
        route_gen.check_extent(tris)                      # avant de lire le sol (long sur une map geante)
    except ValueError as e:
        if 'geante' in str(e):
            raise
        bad = e                                           # objet minuscule selectionne : route importee essayee
    progress.step('lecture du sol', 0.05)
    ground = ground_for(track)
    kz = world_killz(track)
    if float(np.median(tris[:, :, 2])) < kz:
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
    try:
        if bad:
            raise bad
        with progress.span(0.15, 0.9):
            loop = route_gen.road_loop(tris, start[:2], heading, ground=ground, start_z=z0, max_gap=max_gap)
    except ValueError as e:
        # selection qui n'est pas la route (ex. « START_LINE2 », le decor de la ligne de depart, ou les surfaces du
        # sol d'une map importee) : essai avec la route importee (materiau « road »)
        found = None
        for cand in _road_candidates(track, src):
            try:
                ctris = road_tris(track, cand)
                route_gen.check_extent(ctris)
                with progress.span(0.15, 0.9, f"essai avec {cand['objects'][0]['name']}"):
                    found = (cand, ctris, route_gen.road_loop(ctris, start[:2], heading, ground=ground, start_z=z0,
                                                                          max_gap=max_gap))
                break
            except ValueError:
                continue
        if not found:
            raise ValueError(f'{e} — la selection ne forme pas un circuit ferme : en mode Decor, selectionne la ROUTE '
                             f'importee (objet dont le nom contient « Road »), pas la ligne de depart ou le decor') from None
        what = ', '.join(o['name'] for o in src.get('objects', [])) or 'les surfaces du sol'
        src, tris, loop = found
        note = f"{what} ne forme pas un circuit ferme : route utilisee a la place : {src['objects'][0]['name']}"
    progress.step('sections et réapparitions', 0.9)
    lay = route_gen.layout(loop, max(1, int(req.get('sections', 4))))
    respawns = {}
    for k, names in enumerate(req.get('respawns') or []):
        if k < len(lay['section_paths']) and names:
            poses = route_gen.spread_on_path(lay['section_paths'][k], len(names))
            respawns.update(zip(names, _respawns_on_ground(poses, lay['section_paths'][k], ground)))
    # a ecarter : zones de reapparition / succes du _Design, embranchements du RaceSystem (lies a l'ancien trace)
    dz = base_file(track, start_finish.design_file(track))[0]
    zd = IgzFile(dz)
    trig = [n for n, o in zd.root_objects() if zd.objects.get(o) in ('CEntity', 'CGameEntity', 'igEntity')]
    design_moves = {n: {'pos': p['pos'][:2] + [FAR_BELOW], 'yaw': p['yaw']}
                    for n, p in start_finish.read_entity_poses(dz, trig).items()}
    rs = RaceSystem(base_file(track, race_file(track))[0], file_ns=f'{track}_RaceSystem').decode()
    race_moves = {f['name']: f['position'][:2] + [FAR_BELOW] for f in rs['fork_checkers']}
    if src.get('objects'):                               # route memorisee : sert aussi aux splines IA
        os.makedirs(OUT_DIR, exist_ok=True)
        json.dump(src, open(road_source_path(track), 'w'), indent=1)
    return {'loop': loop['points'], 'length': round(loop['length']), 'sections': lay['sections'], 'note': note,
            'transitions': lay['transitions'], 'respawns': respawns, 'design_moves': design_moves,
            'race_moves': race_moves, 'jumps': loop.get('jumps', 0)}


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
        rs0 = RaceSystem(base_file(track, race_file(track))[0], file_ns=f'{track}_RaceSystem').decode()
        cnt = collections.Counter()
        for pos in rs0['position_paths']:
            for p in ai_gen.catmull_rom(pos['control_points'], 300):
                q = ground.at(p[0], p[1], p[2])
                if q:
                    cnt[q[1]] += 1
        surfaces = [s for s, n in cnt.items() if n >= 5]
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
            if info and re.search(r'road', info.get('obj_material') or '', re.I) and lk.get('surface') != 'none':
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
            road = bool(re.search(r'road', (info.get('obj_material') or '') + ' ' + (o['name'] or ''), re.I))
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


def crates_tilt_outdated(track, data):
    """Caisses enregistrees dont l'inclinaison ne suit pas (ou plus) la pente : une sauvegarde sans changement de
    caisse les corrige aussi."""
    orig = pak_tool.read_latest(ARCHIVES, powerup.powerup_file(track), track_pak(track))[0]
    return powerup.tilt_outdated(data, _crate_height_at(track), orig)


def write_crates_file(track, want):
    """Fichier _Power_Up reconstruit depuis l'original (caisses, boosters, TNT / Nitro / fruits), caisses inclinees
    comme la pente du sol. -> (IgzFile, rapport)."""
    read = lambda p, pak: pak_tool.read_latest(ARCHIVES, p, pak)[0]
    donor = powerup.boost_donor(read) if any(c['kind'] == 'boost' for c in want) else None
    extras = {k: powerup.extra_donor(k, read) for k in {c['kind'] for c in want} if k in powerup.EXTRAS}
    z, msg, _ = powerup.write_crates(read(powerup.powerup_file(track), track_pak(track)), want, donor, extras,
                                     _crate_height_at(track))
    return z, msg


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

    # splines remplacees par des splines generees : les remplacantes prennent leur place dans les embranchements
    for old, news in req.get('replaced', {}).items():
        news = [n for n in news if n in ed.by_name]
        for fcomp in ed.forks().values():
            lst = ed.igz.deref(fcomp + 0x18)                       # _aiPaths
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
    # teleporteurs deja enregistres sans les evenements de zone (version precedente de l'editeur) : repares
    tp_ents = {n: o for n, o in ed.by_name.items() if ed.igz.objects.get(o) in DESIGN_ENTITY_TYPES}
    for tname in teleport.read_teleporters(ed.igz, tp_ents):
        if teleport.set_trigger_events(ed.igz, tp_ents[tname], True):
            report.append(f'{tname} : zone du téléporteur réparée (entrée des karts transmise au script)')

    # entites du RaceSystem deplacees (embranchements ecartes par « Creer le parcours »)
    for name, pos in (req.get('race_entity_positions') or {}).items():
        if name in ed.by_name:
            struct.pack_into('<3f', *ed.igz._loc(ed.by_name[name] + 0x20), *[float(c) for c in pos])
            report.append(f'{name} deplace')

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
    if (req.get('start_grid') and not in_race) or req.get('design_poses'):
        data = base_file(track, logical)[0]
        out = data
        if req.get('start_grid') and not in_race:
            cur = {s['name']: s for s in start_finish.read_grid(data)}
            want = {s['name']: s for s in req['start_grid'] if s['name'] in cur}
            if any(abs(a - b) > 1e-3 for n, s in want.items() for a, b in zip(s['pos'] + [s['yaw']], cur[n]['pos'] + [cur[n]['yaw']])):
                out = start_finish.write_grid(out, want)
                report.append(f'grille de depart : {len(want)} places')
        if req.get('design_poses'):
            out = start_finish.write_entity_poses(out, req['design_poses'])
            report.append(f"_Design : {len(req['design_poses'])} entite(s) placee(s) (reapparitions, zones)")
        if out is not data:
            open(saved_path(logical), 'wb').write(out)
    if req.get('player_start'):
        logical = start_finish.main_map_file(track)
        data = base_file(track, logical)[0]
        cur, ps = start_finish.read_player_start(data), req['player_start']
        if cur and any(abs(a - b) > 1e-3 for a, b in zip(ps['pos'] + [ps['yaw']], cur['pos'] + [cur['yaw']])):
            open(saved_path(logical), 'wb').write(start_finish.write_player_start(data, ps['pos'], ps['yaw']))
            report.append('repere de depart deplace')

    # caisses d'objets : fichier reconstruit depuis l'original (positions, ajouts, suppressions)
    progress.step('caisses et boosters', 0.4)
    if req.get('crates') is not None:
        logical = powerup.powerup_file(track)
        cur = powerup.read_crates(base_file(track, logical)[0])
        want = []
        for c in req['crates']:
            w = {'name': c.get('name'), 'kind': c['kind'], 'pos': [round(float(v), 2) for v in c['pos']]}
            if c['kind'] == 'boost':
                w['yaw'] = round(float(c.get('yaw') or 0.0), 5)
                w['dims'] = [round(float(v), 1) for v in (c.get('dims') or powerup.BOOST_DIMS)]
            want.append(w)
        named = lambda c: c['kind'] in ('question', 'fruit')             # copies d'origine : le nom compte
        key = lambda lst: [(c['name'] if named(c) else None, c['kind'], c['pos'], c.get('yaw'), c.get('dims'))
                           for c in lst]
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
    gain = safe_compact(track, race_file(track), ed.igz) + safe_compact(track, ttr_file(track), ttr.igz)
    if gain > 4096:
        report.append(f'fichiers compactes : {gain // 1024} Ko de blocs abandonnes retires')
    ed.igz.save(saved_path(race_file(track)))
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


def load_decor(track):
    files = []
    reg = custom_models(track)
    labels = {m['id']: m['label'] for m in material_catalog(track)} if reg else {}
    links = load_links(track)
    alpha = {i['material_id']: bool(i.get('alpha')) for i in custom_textures(track).values()}
    for logical in art_files(track):
        data, src = base_file(track, logical)
        objs = DecorFile(data).objects()
        for o in objs:                                   # modeles importes : texture, surface, transparence
            info = reg.get(model_logical_path(o['model']))
            lk = links.get(logical, {}).get(str(o['id']))
            if info:
                o['custom_material'] = labels.get(info.get('material'), 'roche du gabarit')
                o['surface'] = lk.get('surface', 'auto') if isinstance(lk, dict) else 'auto'
                o['alpha'] = alpha.get(info.get('material'))
            elif isinstance(lk, dict) and lk.get('library'):  # objet de la bibliotheque : piste d'origine, surface
                o['library'] = library.nice(lk['library'])
                o['surface'] = lk.get('surface', 'auto')
        files.append({'file': logical, 'label': os.path.basename(logical)[len(track) + 1:-4],
                      'source': os.path.basename(src), 'saved': src.startswith(OUT_DIR), 'objects': objs})
    groups = move_away_files(track)
    return {'track': track, 'files': files, 'newmap': newmap_settings(track),
            'added': added_groups(track, {f['file']: f['objects'] for f in files}),
            'move_away_groups': [{'key': k, 'label': l, 'files': [os.path.basename(p)[len(track) + 1:-4] for p in groups.get(k, [])]}
                                 for k, l, _ in MOVE_AWAY_GROUPS if groups.get(k)]}


def model_binary(track, file_name):
    """Maillage d'un modele : u32 nb sommets, u32 nb indices, float32[3n], uint32[m]."""
    logical = model_logical_path(file_name)
    if logical not in _model_cache:
        try:
            pos, idx = model_mesh(model_bytes(track, logical))
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
MOVE_AWAY_KEEP = re.compile(r'crate|power_?up', re.I)   # generateur de caisses (fichier _VFX de Crash Cove) : reste


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
    if not moved and not amb and not sky:
        if os.path.exists(path):
            os.remove(path)
            return f'{os.path.basename(logical)} : remis a sa place'
        return None
    z = IgzFile(pak_tool.read_latest(ARCHIVES, logical, track_pak(track))[0])
    msg = []
    if moved:
        n = 0
        for name, o in z.root_objects():
            t = z.objects.get(o) or ''
            if t in OCCLUSION_TYPES:                   # position : champ _position du declencheur, +0x68 de la boite
                off = z.find_field(o, '_position')[0] if t == 'COcclusionTrigger' else o + 0x68
                x, y, zz = z.vec3(off)
                struct.pack_into('<3f', *z._loc(off), x, y, zz + MOVE_AWAY_DZ)
                n += 1
            elif t.endswith('Entity') and not MOVE_AWAY_KEEP.search(name or ''):
                x, y, zz = z.vec3(o + 0x20)
                struct.pack_into('<3f', *z._loc(o + 0x20), x, y, zz + MOVE_AWAY_DZ)
                n += 1
        msg.append(f'{n} entite(s) descendue(s) sous la carte')
    if sky:                                            # d'abord l'atmosphere de la piste source, puis l'ambiance
        msg.append(f"ciel et éclairage de {sky['label']} ({apply_sky(z, sky)} réglages)")
    if amb:
        msg.append(f'ambiance : {apply_ambiance(z, amb)} reglage(s)')
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
    """(entrees du manifeste, {fichier: archive source} a copier) du ciel choisi, ou ([], {})."""
    sky = ambiance_sky(track)
    if not sky:
        return [], {}
    entries, copies = [], {}
    sd = sky_source(sky).dump_object(next(o for o, t in sky_source(sky).objects.items() if t == 'CWorldVisualData'))
    probes = [('texture', _probe_logical(sd[f])) for f in ('_environmentMap', '_specularEnvironmentMap') if sd.get(f)]
    deps = library.dependencies(lambda lg: read_game_file(track, lg, (sky['pak'],)), sky['model'])
    for typ, lg in list(dict.fromkeys(probes)) + deps:
        entries.append(('sky_model' if lg == sky['model'] else typ, lg))
        if not library.available(ARCHIVES, lg, track_pak(track)):
            src = library.find_pak(ARCHIVES, lg, (sky['pak'],))
            if src is None:
                raise KeyError(f'fichier du ciel introuvable : {lg}')
            copies[_archive_case(src, lg)] = src
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
    report.append(sync_collision(track))
    return {'report': report, 'settings': s, 'remaining': remaining_elements(track)}


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
    holders = []
    if logical in (newmap_settings(track).get('strip_art') or []):
        # nouvelle map : tous les objets d'origine retires, SAUF l'entite qui active le maillage de sol ou vont les
        # triangles des modeles importes (sans elle le jeu ne charge pas ce maillage : on passe au travers)
        owner = ground_owner(track)
        keep = {i for i, o in oobjs.items() if owner and (logical, o['name']) == owner}
        cids = (cids - set(oobjs)) | keep
        cur = [o for o in cur if o['id'] not in oobjs or o['id'] in keep] + \
              [oobjs[i] for i in keep if i not in {o['id'] for o in cur}]
        # entites sans modele qui en regroupent d'autres (prefabriques : Roo's Tubes « C3_Sea_KelpBunch01 » ->
        # igPrefabComponentData -> liste d'entites) : retirees aussi, sinon leurs enfants restaient atteignables
        holders = [r for r in orig.roots if z.objects.get(r) in ENTITY_TYPES and r not in oobjs]
    elif restore_originals:                            # fin du mode « nouvelle map » : les objets d'origine reviennent
        cur = cur + [o for i, o in oobjs.items() if i not in cids]
        cids |= set(oobjs)
    orig.delete_many([i for i in oobjs if i not in cids] + holders)
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
    deleted: [id]}}}. Les ids sont ceux de la version chargee (sauvee ou originale)."""
    track, report = req['track'], []
    os.makedirs(OUT_DIR, exist_ok=True)
    for logical, ed in progress.items(req.get('files', {}).items(), 'écriture du décor ({i} / {n})', 0.0, 0.25):
        if logical not in art_files(track):
            raise ValueError(f'{logical} n\'est pas un fichier de decor de {track}')
        data, _ = base_file(track, logical)
        df = DecorFile(data)
        names = {o['id']: o['name'] for o in df.objects()}
        links = load_links(track)
        file_links = links.setdefault(logical, {})
        for sid, m in ed.get('moves', {}).items():
            df.set_transform(int(sid), m.get('pos'), m.get('euler'), m.get('scale'))
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
    with progress.span(0.25, 0.95):
        report.append(sync_collision(track))
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
                  if (o['model'] or '').lower().endswith('\\boostpad.igb')), key=lambda o: o['name'])
    logical = powerup.powerup_file(track)
    cur = powerup.read_crates(base_file(track, logical)[0])
    old = [c for c in cur if c['kind'] == 'boost']
    if not vis and not old:
        return None
    new = []
    for k, v in enumerate(vis):
        h = old[k]['dims'][2] if k < len(old) else powerup.BOOST_DIMS[2]
        new.append({'kind': 'boost', 'pos': [round(v['pos'][0], 2), round(v['pos'][1], 2), round(v['pos'][2] - BOOST_VISUAL_LIFT, 2)],
                    'yaw': round(v['euler'][2], 5), 'dims': [round(abs(v['scale'][0]) * 100, 1), round(abs(v['scale'][1]) * 100, 1), h]})
    same = len(new) == len(old) and all(
        max(abs(a - b) for a, b in zip(n['pos'] + [n['yaw']] + n['dims'], o['pos'] + [o['yaw']] + o['dims'])) < 1.0
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
    out = [(os.path.basename(n), saved_path(n)) for n in names]
    out += [(os.path.basename(links_path(track)), links_path(track)),
            (f'{track}_custom_models.json', os.path.join(OUT_DIR, f'{track}_custom_models.json')),
            (f'{track}_custom_textures.json', custom_textures_path(track)),
            (f'{track}_newmap.json', newmap_path(track)), (f'{track}_road.json', road_source_path(track)),
            (f'{track}_minimap.json', os.path.join(OUT_DIR, f'{track}_minimap.json')),
            (f'{track}_light.json', light_path(track)),
            (f'{track}_menu.json', menu_settings_path(track)),
            (f'{track}_ambiance.json', ambiance_path(track))]
    out += [('models/' + os.path.basename(k), custom_model_path(k)) for k in custom_models(track)]
    return out


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
            if name.startswith('models/') and os.path.exists(old) and os.path.getmtime(p) < prev_t \
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
    return os.path.join(OUT_DIR, 'models', os.path.basename(logical))


def custom_models(track):
    """{chemin logique: infos} des modeles importes pour la piste."""
    p = os.path.join(OUT_DIR, f'{track}_custom_models.json')
    return json.load(open(p)) if os.path.exists(p) else {}


def save_custom_models(track, reg):
    os.makedirs(OUT_DIR, exist_ok=True)
    json.dump(reg, open(os.path.join(OUT_DIR, f'{track}_custom_models.json'), 'w'), indent=1)


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
    return os.path.join(OUT_DIR, 'textures', os.path.basename(logical))


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
    mat_name = model_materials(read_game_file(track, TEMPLATE))[0][1]       # 'rockGroundSide'
    mat = texture_build.retarget_material(tmpl_mat, {old['ColorMap']: color_ns, old['NormalMap']: FLAT_NORMAL_NS})
    if alpha:                                          # meme nom que le materiau roche (handle des modeles)
        from igz import fnv1a_lower
        z = IgzFile(mat)
        entries = z._name_entries()
        entries[0] = (mat_name, fnv1a_lower(mat_name))
        z._write_names(entries)
        mat = z.to_bytes()
    open(custom_file_path(mat_logical), 'wb').write(mat)
    for cache in (_texture_png_cache, _preview_cache):
        cache.clear()
    return ({'texture': [color_logical, normal_logical], 'material_instances': [mat_logical]}, mat_name, mat_ns, mat_dep)


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
    (38, 'Sable (route de Crash Cove)', True), (40, 'Sable mouillé', True), (4, 'Sol (défaut)', True),
    (5, 'Herbe', True), (53, 'Terre lente', False), (6, 'Roche', True), (13, 'Bois', True),
    (11, 'Eau peu profonde', True), (12, 'Eau profonde', True), (39, 'Verre', True), (22, 'Turbo (accélère)', True),
    (16, 'Réapparition (on y tombe)', True), (7, 'Terre', False), (46, 'Asphalte', False), (29, 'Sable sombre', False),
    (8, 'Neige', False), (10, 'Glace', False), (18, 'Boue', False), (9, 'Métal', False)]
_surface_params = {}


def surface_params():
    """{valeur: {'speed', 'traction'}} lus dans LooseData/CollisionMaterials.igz (materiau -> fiche de surface)."""
    if not _surface_params:
        z = IgzFile(pak_tool.read_latest(ARCHIVES, 'LooseData/CollisionMaterials.igz', 'permanent.pak')[0])
        roots = {n: o for n, o in z.root_objects() if n}
        hl = next(o for o, t in z.objects.items() if t == 'CCollisionMaterialHandleList')
        for idx, item in enumerate(z.dump_object(hl)['@items']):
            o = roots.get(str(item.get('@handle')).split('::')[-1]) if isinstance(item, dict) else None
            if o is None or z.objects.get(o) != 'CCollisionMaterial':
                continue
            si = z.dump_object(o).get('_surfaceInfo')
            sn = si['@handle'].split('::')[-1] if isinstance(si, dict) and '@handle' in si else None
            s = z.dump_object(roots[sn]) if sn in roots else {}
            if s:
                _surface_params[idx + 3] = {'speed': s.get('_speedMultiplier'), 'traction': s.get('_traction')}
    return _surface_params


def set_surface(req):
    """Type de sol des objets importes : req = {track, objects: [{file, id}], surface: 'auto' | 'none' | valeur}.
    Memorise dans les liens du decor, puis collision recalculee."""
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
            n += 1
    if not n:
        raise ValueError('aucun modèle importé dans la sélection (le sol des objets d\'origine ne se change pas ici)')
    save_links(track, links)
    label = {'auto': 'comme le sol dessous', 'none': 'sans collision'}.get(surf) or next(l for s, l, _ in SURFACES if s == surf)
    with progress.span(0.05, 1.0):
        rep = sync_collision(track)
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
        data = build_model(template, local, nrm, uvs, tan, g['tris'], f'{CUSTOM_DIR}/{name}',
                           (m['name'], m['ns'], m['dep']) if m else None)
        open(custom_model_path(logical), 'wb').write(data)
        _visual_cache.pop(logical, None)
        _model_cache.pop(logical, None)
        _preview_cache.pop(logical, None)
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
        report = [f'{len(created)} modele(s) : {n_verts} sommets, {n_tris} triangles', sync_collision(track)]
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
        rep = sync_collision(track)
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


def boost_pad_png(track):
    """Image de la plaque : chevrons du masque d'emission du jeu (oct_turbo_pad_ec, canal vert), jaune -> orange sur
    fond bleu nuit, bord clair ; pointe vers le bas de l'image (= sens de course apres le placage UV)."""
    from PIL import Image
    rgba, _ = preview.decode_texture(read_game_file(track, BOOST_MASK_TEX), 512)
    m = rgba[:, :, 1].astype(np.float32) / 255.0
    h, w = m.shape
    t = np.linspace(0, 1, h)[:, None]
    hot = np.stack([255 + 0 * t, 230 - 120 * t, 40 + 0 * t], -1)               # jaune en haut, orange en bas
    bg = np.array([18, 28, 70], np.float32)
    img = bg * (1 - m[..., None]) + hot * m[..., None]
    img[:, :6] = img[:, -6:] = (250, 250, 250)                                   # bords lateraux
    buf = io.BytesIO()
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(buf, 'PNG')
    return buf.getvalue()


def ensure_boost_model(track):
    """Modele importe « BoostPad » : plaque de 100 x 100 po (X = sens de course), texture generee. Cree une fois."""
    logical = f'models/{CUSTOM_DIR}/BoostPad.igz'
    reg = custom_models(track)
    if logical in reg and os.path.exists(custom_model_path(logical)) and reg[logical].get('version') == BOOST_MODEL_VERSION:
        return logical
    tex = create_texture(track, 'BoostPad', boost_pad_png(track), source=['boostpad', 1])
    m = next(x for x in custom_material_entries(track) if x['id'] == tex['id'])
    pos = [(-50.0, -50.0, 0.0), (50.0, -50.0, 0.0), (50.0, 50.0, 0.0), (-50.0, 50.0, 0.0)]
    tris = [(0, 1, 2), (0, 2, 3)]
    # +X (avant) -> bas de l'image, ou pointent les chevrons ; build_model ecrit 1 - v (convention OBJ) : v inverse ici
    # (version 1 : chevrons vers l'arriere en jeu)
    uvs = [((p[1] + 50) / 100, (50 - p[0]) / 100) for p in pos]
    pos, nrm, uvs, tan = complete_mesh(pos, [(0.0, 0.0, 1.0)] * 4, uvs, tris)
    data = build_model(read_game_file(track, TEMPLATE), pos, nrm, uvs, tan, tris,
                       f'{CUSTOM_DIR}/BoostPad', (m['name'], m['ns'], m['dep']))
    os.makedirs(os.path.join(OUT_DIR, 'models'), exist_ok=True)
    open(custom_model_path(logical), 'wb').write(data)
    for cache in (_model_cache, _preview_cache, _visual_cache):
        cache.pop(logical, None)
    reg[logical] = {'name': 'BoostPad', 'vertices': 4, 'triangles': 2, 'material': tex['id'],
                    'obj_object': 'BoostPad', 'obj_material': 'BoostPad', 'version': BOOST_MODEL_VERSION}
    save_custom_models(track, reg)
    return logical


def sync_boost_visuals(track, boosts):
    """Un objet de decor « BoostPad_Visual_NNN » (sans collision) par booster : position, cap, taille = celles de
    sa zone (profondeur x largeur). Les anciens sont remplaces."""
    art = main_art(track)
    df = DecorFile(base_file(track, art)[0])
    olds = [o for o in df.objects() if (o['name'] or '').startswith(BOOST_VISUAL_PREFIX)]
    old = [o['id'] for o in olds]
    if not old and not boosts:
        return 'aucun booster'
    if boosts:
        ensure_boost_model(track)                      # (re)construit le modele si sa version a change
    ground = ground_for(track)
    zs = [(lambda t: t if t is not None else b['pos'][2])(ground.top(b['pos'][0], b['pos'][1], b['pos'][2])) for b in boosts]
    want = [([b['pos'][0], b['pos'][1], z + BOOST_VISUAL_LIFT], float(b.get('yaw') or 0.0), [b['dims'][0] / 100.0, b['dims'][1] / 100.0])
            for b, z in zip(boosts, zs)]
    have = [(o['pos'], o['euler'][2], o['scale'][:2]) for o in sorted(olds, key=lambda o: o['name'])]
    if len(have) == len(want) and all(max(abs(a - b) for a, b in zip(h[0] + [h[1]] + h[2], w[0] + [w[1]] + w[2])) < 0.05
                                      for h, w in zip(have, want)):
        return None                                    # deja a jour
    df.delete_many(old)
    links = load_links(track)
    if boosts:
        logical = ensure_boost_model(track)
        tmpl = {'id': template_object(track, art)}
        # plaque sur la surface la plus haute sous le booster (la route), pas sur un niveau enfoui dessous (sable
        # 1 m sous la route de Mario Circuit 3 : la plaque y etait invisible)
        specs = [(tmpl['id'], f'{BOOST_VISUAL_PREFIX}{k:03d}', pos, [0.0, 0.0, yaw], scale + [1.0])
                 for k, (pos, yaw, scale) in enumerate(want, 1)]
        for nid in df.duplicate_many(specs):
            df.set_model(nid, 'models:\\' + CUSTOM_DIR.replace('/', '\\') + '\\BoostPad.igb')
            links.setdefault(art, {})[str(nid)] = {'custom': logical, 'surface': 'none'}
        save_links(track, links)
    write_art(track, art, df)
    return f'dessin au sol : {len(boosts)} plaque(s)'


# -- import d'un dossier complet (OBJ + MTL + textures) -----------------------------------------
PROJECT_DIR = os.path.dirname(os.path.dirname(HERE))
IMAGE_EXT = ('.png', '.jpg', '.jpeg', '.tga', '.bmp', '.dds', '.tif', '.tiff', '.webp')
# decor non roulable : sans collision par defaut (feuillage, fleurs, lampes...) ; modifiable dans la fenetre
NO_COLLISION_HINT = re.compile(r'leaf|flower|plant|bush|tree|nature|kusa|mist|light|lamp|star(?!t)|cloud|sky|water|effect|confetti|^ef_',
                               re.I)


def _folder(req):
    folder = os.path.abspath(os.path.join(PROJECT_DIR, req.get('folder') or 'map'))
    if not os.path.isdir(folder):
        raise ValueError(f'dossier introuvable : {folder}')
    return folder


def _find_file(folder, name):
    """Fichier du dossier (nom insensible a la casse ; chemin relatif ou seulement le nom de fichier)."""
    if not name:
        return None
    name = name.replace('\\', '/')
    for cand in (name, os.path.basename(name)):
        p = os.path.join(folder, cand)
        if os.path.isfile(p):
            return p
        low = cand.lower()
        for f in os.listdir(os.path.dirname(p) if os.path.isdir(os.path.dirname(p)) else folder):
            if f.lower() == os.path.basename(low):
                return os.path.join(os.path.dirname(p) if os.path.isdir(os.path.dirname(p)) else folder, f)
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
            _dae_cache.clear()
            _dae_cache[key] = dae_import.dae_to_obj(path)
        text, mtl, up = _dae_cache[key]
        return text, mtl, obj_summary(text), up
    text = open(path, encoding='utf-8', errors='replace').read()
    summ, mtl = _folder_materials(folder, text)
    return text, mtl, summ, 'y'


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
    """req = {folder (relatif au projet ou absolu), obj (facultatif)} -> fichiers .obj / .dae du dossier et, pour
    celui choisi, ses materiaux : texture trouvee, triangles, collision proposee ; taille brute, echelle et axe
    proposes."""
    folder = _folder(req)
    objs = sorted(f for f in os.listdir(folder) if f.lower().endswith(MODEL_EXT))
    if not objs:
        raise ValueError(f'aucun fichier .obj ou .dae dans {folder}')
    obj = req.get('obj') if req.get('obj') in objs else objs[0]
    progress.step(f'lecture de {obj}', 0.02)
    text, mtl, summ, up = _load_source(folder, obj)
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
    return {'folder': folder, 'objs': objs, 'obj': obj, 'materials': mats, 'vertices': summ['vertices'],
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
    """Import d'un dossier en une fois : req = {track, folder, obj, scale, up, placement, pos, file,
    materials: {materiau OBJ: {'collision': bool, 'surface': 'auto' | int}}}. Chaque materiau recoit sa texture
    (map_Kd du .mtl, convertie ; a defaut une couleur unie Kd), puis l'OBJ est importe (un modele par objet /
    materiau) avec ces textures et la collision choisie."""
    from PIL import Image
    track = req['track']
    folder = _folder(req)
    obj = req.get('obj')
    if not obj or not os.path.isfile(os.path.join(folder, obj)) or not obj.lower().endswith(MODEL_EXT):
        raise ValueError('fichier .obj / .dae introuvable dans le dossier')
    progress.step(f'lecture de {obj}', 0.01)
    text, mtl, summ, _ = _load_source(folder, obj)
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
    """Triangles monde (pouces) du modele visuel d'un objet, a sa transformation (obj) : tableau (n, 3, 3)."""
    logical = model_logical_path(obj['model'])
    if logical not in _visual_cache:
        pos, idx = model_mesh(model_bytes(track, logical))
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
    return {'collision_cell': 0, **(json.load(open(p)) if os.path.exists(p) else {})}


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
        report.append(sync_collision(track))
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
        objs.append((cur['name'], info.get('surface', 'auto'), T))
    skipped = _background_objects(track, [(n, T) for n, s, T in objs if s == 'auto'])
    n_before = n_after = 0
    for name, surf, T in progress.items(objs, 'collision : découpage {i} / {n}', 0.4, 1.0):
        if name in skipped or not len(T):
            continue
        n_before += len(T)
        if cell > 0 and not is_flat(name, T):
            T = simplify_tris(T, cell)
        n_after += len(T)
        if not len(T):
            continue
        T = subdivide_array(T)
        if surf == 'auto':
            P = T.reshape(-1, 3)
            surf = ge.surface_under(P.min(0).tolist(), P.max(0).tolist())
        by_surface[int(surf)].append(T)
    n_custom = 0
    for surf, parts in by_surface.items():
        T = np.concatenate(parts)
        ge.add_world_prims(T, surf, mesh_index)
        n_custom += len(T)
    return n_custom, sorted(skipped), (n_before, n_after)


def _skipped_note(skipped, counts=(0, 0)):
    n_before, n_after = counts
    return ((f' ; sans collision (decor de fond) : {", ".join(skipped[:6])}' + (' ...' if len(skipped) > 6 else '')
             if skipped else '')
            + (f' ; collision allegee : {n_before} -> {n_after} triangles' if n_after < n_before else ''))


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
        return memo['report'] + ' (inchangee)'
    if nm.get('strip_ground'):
        report = collision_custom_only(track, hk, customs, copies, orphan)
    else:
        report = _sync_ground(track, logical, hk, originals, changed, copies, customs, orphan)
    json.dump({'key': key, 'out': _saved_md5(saved_path(logical)), 'report': report}, open(_collision_memo_path(track), 'w'))
    return report


COLLISION_CODE_VERSION = 2     # change -> collision recalculee meme si le decor n'a pas change


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
            pos, idx = model_mesh(model_bytes(track, src['custom']))
            return {'tris': [round(c, 2) for i in idx for c in pos[i * 3:i * 3 + 3]],
                    'note': f'modele importe : {len(idx) // 3} triangle(s) de collision (surface '
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
        t = next((x for x in tr['transitions'] if nxt[0] in x['previous_position']), None)
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
            if low.endswith('.pak') and (low.startswith(MENU_ARCHIVE_PREFIXES) or low in tracks):
                try:
                    _menu_arc_cache[p] = pak_tool.cached_archive(os.path.join(ARCHIVES, p))[1].keys()
                except Exception:  # noqa: BLE001 - archive illisible : ignoree
                    continue


def menu_archives(track, logical):
    """Archives qui contiennent ce fichier (toutes sont patchees a l'installation) : [chemins], la plus
    prioritaire d'abord (update2, update, puis les autres)."""
    _menu_archives_index()
    order = lambda p: (p not in pak_tool.UPDATE_ARCHIVES, pak_tool.UPDATE_ARCHIVES.index(p) if p in pak_tool.UPDATE_ARCHIVES else 0, p)
    return [os.path.join(ARCHIVES, p) for p in sorted(_menu_arc_cache, key=order) if logical.lower() in _menu_arc_cache[p]]


def _menu_original(track, logical):
    """(octets d'origine, nom logique avec la casse de l'archive) ou (None, None)."""
    arcs = menu_archives(track, logical)
    if not arcs:
        return None, None
    base = next((a for a in arcs if os.path.basename(a) not in pak_tool.UPDATE_ARCHIVES), arcs[0])
    data, _ = pak_tool.read_latest(ARCHIVES, logical, os.path.basename(base))
    return data, _archive_case(os.path.basename(arcs[0]), logical)


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
        orig, logical = _menu_original(track, files[f'image_{k}'])
        if orig is None:
            continue
        p = saved_path(logical)
        data = open(p, 'rb').read() if os.path.exists(p) else orig
        rgba, _ = preview.decode_texture(data, 512)
        info = texture_build.texture_info(orig)
        buf = io.BytesIO()
        Image.fromarray(rgba[::-1]).save(buf, 'PNG')         # textures d'interface stockees de bas en haut (apply_menu)
        images[k] = {'label': label, 'size': [info['width'], info['height']], 'custom': os.path.exists(p),
                     'preview': 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()}
    v = menu_video(track)
    return {'names': names, 'images': images, 'slug': menu_assets.slug(track),
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


def world_killz(track):
    """Plancher du monde (CWorldEntityData._killz) de la version enregistree."""
    z = IgzFile(base_file(track, start_finish.main_map_file(track))[0])
    w = next((o for o, t in z.objects.items() if t == 'CWorldEntityData'), None)
    return struct.unpack_from('<f', *z._loc(w + 0x40))[0] if w is not None else KILL_Z


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
    if not pool:
        raise ValueError('aucun point de reapparition dans le _Design')
    points = falls.respawn_layout(P, starts, end, float(req.get('spacing', 50)) * 39.37, minimum=len(base), air=air)
    template = next((n for n in pool if f'{n}_camera' not in roots), pool[0])
    zones = falls.find_fall_zones(P, ground, road_ground(track), killz=killz) if req.get('zones', True) else []
    zautos = sorted(n for n in roots if n.startswith(FALL_AUTO) and n[len(FALL_AUTO):].isdigit())
    if zones and FALL_TEMPLATE not in roots:
        raise ValueError(f'{FALL_TEMPLATE} introuvable dans le _Design (modele des zones de chute)')
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
            _, p = dz.clone_owned(roots[FALL_TEMPLATE], name, owned[roots[FALL_TEMPLATE]], names)
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
    tag = next(((n, s) for n, s in dz.ext_names if s == 'EntityTags' and n == 'PlayerStart'), ('PlayerStart', 'EntityTags'))
    for name, zone in zip(zautos, zones):
        ent = roots[name]
        struct.pack_into('<3f', *dz._loc(ent + 0x20), *zone['center'])
        box = _component(dz, ent, 'CTriggerVolumeBoxComponentData')
        dz.set_field(box, '_dimensions', zone['dims'])
        rt = _component(dz, ent, 'CRespawnTriggerComponentData')
        lst = dz.deref(rt + _field(dz, 'CRespawnTriggerComponentData', '_respawnPoints'))
        dz.set_handle_list(lst, [tag] + [(used[i], ns) for i in falls.before(points, zone['s'])])
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
        if track == 'T111_Crash_Cove':
            _minimap_orient_cache[track] = ((0, False), True)
        else:
            tp = track_pak(track)
            try:
                rgba, _ = preview.decode_texture(pak_tool.read_latest(ARCHIVES, minimap_texture_logical(track), tp)[0], 1024)
                rs = RaceSystem(pak_tool.read_latest(ARCHIVES, race_file(track), tp)[0], file_ns=f'{track}_RaceSystem').decode()
                pts = np.vstack([np.array(ai_gen.catmull_rom(p['control_points'], 300))[:, :2] for p in rs['position_paths']])
                op, sure, _ = minimap.choose_orientation(rgba, pts)
            except Exception:  # noqa: BLE001 - donnees d'origine illisibles : sens de Crash Cove
                traceback.print_exc()
                op, sure = (0, False), False
            _minimap_orient_cache[track] = (tuple(op), sure)
    return _minimap_orient_cache[track]


def generate_minimap(track, move=None):
    """Mini-carte refaite d'apres le parcours ENREGISTRE (route importee si connue, sinon trace epais) : image +
    coins du script, toujours depuis les fichiers d'origine. move = [du, dv] : reglage fin du dessin (px, cumule et
    memorise dans <Piste>_minimap.json). -> rapport + apercu PNG (data URL) + reglage."""
    import base64
    from PIL import Image
    meta_p = os.path.join(OUT_DIR, f'{track}_minimap.json')
    meta = json.load(open(meta_p)) if os.path.exists(meta_p) else {}
    nudge = list(meta.get('nudge', minimap.NUDGE_DEFAULT))
    if move:
        nudge = [nudge[0] + int(move[0]), nudge[1] + int(move[1])]
    path, tr = race_path_points(track)
    if len(path) < 10:
        raise ValueError('pas de parcours enregistre (cree le parcours et enregistre d\'abord)')
    fin = next((t for t in tr['transitions'] if t['increment_lap']), None)
    src = json.load(open(road_source_path(track))) if os.path.exists(road_source_path(track)) else \
        {'objects': imported_road_objects(track)}
    progress.step('lecture de la route', 0.1)
    tris = road_tris(track, src) if src.get('objects') else None
    progress.step('orientation de la mini-carte', 0.3)
    orient, sure = minimap_orientation(track)
    progress.step('dessin et encodage de l\'image', 0.4)
    mm, tex_logical = minimap.minimap_file(track), minimap_texture_logical(track)
    setup, tex, rgba, corners = minimap.build(
        pak_tool.read_latest(ARCHIVES, mm, track_pak(track))[0],
        pak_tool.read_latest(ARCHIVES, tex_logical, track_pak(track))[0],
        path, tris, (fin['position'], fin['yaw'] or 0.0) if fin else None, 1000.0, nudge, orient)
    os.makedirs(OUT_DIR, exist_ok=True)
    open(saved_path(mm), 'wb').write(setup)
    open(saved_path(tex_logical), 'wb').write(tex)
    json.dump({'path_key': minimap_path_key(track), 'nudge': nudge}, open(meta_p, 'w'))
    buf = io.BytesIO()
    Image.fromarray(rgba).save(buf, 'PNG')
    return {'report': [f"mini-carte : {'route importée' if tris is not None else 'tracé'} dessinée, coins "
                       f"({corners['top_left'][0]:.0f}, {corners['top_left'][1]:.0f}) / "
                       f"({corners['bottom_right'][0]:.0f}, {corners['bottom_right'][1]:.0f}), réglage du dessin "
                       f"{nudge[0]:+d} / {nudge[1]:+d} px"
                       + ('' if orient == (0, False) else f", image rangée dans le sens d'affichage de la piste "
                          f"({'retournée' if orient == (0, True) else f'orientation {orient}'})")
                       + ('' if sure else " ; ATTENTION : sens d'affichage de cette piste incertain, à vérifier en jeu")],
            'preview': 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode(), 'nudge': nudge}


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
FIX_ORDER = ['occlusion', 'sky', 'transitions', 'grid', 'crates', 'boosters', 'falls', 'minimap']
FIX_LABELS = {'occlusion': 'Retirer les zones d\'occultation', 'sky': 'Appliquer un ciel',
              'transitions': 'Replacer sur le parcours',
              'grid': 'Replacer la grille derrière la ligne', 'crates': 'Tout poser au sol',
              'boosters': 'Refaire les plaques des boosters', 'falls': 'Refaire chutes et réapparitions',
              'minimap': 'Générer la mini-carte'}
UI_LABELS = {'mkroute': 'Recréer le parcours…', 'regenall': 'Régénérer les splines IA…', 'dambiance': 'Choisir un ciel…'}


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


def fix_occlusion(track):
    nm = newmap_settings(track)
    apply_newmap({'track': track, 'strip_ground': nm.get('strip_ground'), 'strip_art': nm.get('strip_art'),
                  'move_away': list(dict.fromkeys((nm.get('move_away') or []) + ['occlusion'])), 'remove': []})
    return 'zones d\'occultation de l\'ancienne piste retirées'


FIXES = {'transitions': fix_transitions, 'grid': fix_grid, 'crates': fix_crates, 'boosters': fix_boosters, 'sky': fix_sky, 'occlusion': fix_occlusion,
         'falls': lambda t: '; '.join(auto_falls({'track': t}).get('report') or ['chutes et réapparitions refaites']),
         'minimap': lambda t: generate_minimap(t)['report'][0]}


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
        nxt = [n for n in t['next_position'] if n in dense]
        if not nxt:
            bad_t.append((f'{label} : aucune spline de position suivante', None))
            continue
        dist, head = nearest(dense[nxt[0]], t['position'])
        if dist > 1500:
            bad_t.append((f'{label} : à {dist / 39.37:.0f} m de sa spline de position', 'transitions'))
        elif math.cos(head - (t['yaw'] or 0.0)) < 0:
            bad_t.append((f'{label} : tournée dans le sens inverse du parcours', 'transitions'))
        far_ai = [n for n in t['next_ai'] if n in dense and nearest(dense[n], t['position'])[0] > 1500]
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
    # 3) sol, hauteur
    kz = world_killz(track)
    low = min((float(np.min(np.asarray(s['control_points'])[:, 2])) for s in pos.values()), default=None)
    if road is not None and len(road.t):
        zr = float(np.median(road.t[:, :, 2]))
        if zr < kz:
            add('erreur', 'Route', f'la route est à z = {zr:.0f}, sous le plancher de chute ({kz:.0f}) : les karts y sont « tombés »')
        else:
            add('ok', 'Route', f'au-dessus du plancher de chute (z ≈ {zr:.0f})')
    if low is not None and low - 400 < kz:
        add('erreur', 'Chutes', f'le parcours descend à z = {low:.0f}, à moins de 10 m du plancher de chute ({kz:.0f}) : '
                                f'refais « Chutes et réapparitions » (la map a bougé ?)', fix='falls')
    # reapparitions (points des splines de position)
    rnames = sorted({str(r).split('::')[-1] for s in pos.values() for r in (s.get('respawn_points') or [])})
    if rnames:
        poses = start_finish.read_entity_poses(base_file(track, start_finish.design_file(track))[0], rnames)
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
        vis = [o for o in DecorFile(base_file(track, art)[0]).objects() if (o['model'] or '').lower().endswith('\\boostpad.igb')]
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
    return {'checks': out, 'errors': sum(c['level'] == 'erreur' for c in out),
            'warnings': sum(c['level'] == 'attention' for c in out)}


def _archive_case(pak, logical):
    """Nom logique avec la casse de l'archive pak (le manifeste et EXTRAS sont en minuscules)."""
    arc, index, _ = pak_tool.cached_archive(os.path.join(ARCHIVES, pak))
    e = index.get(logical.lower())
    return e.logical_name if e else logical


def install_plan(track):
    """{archive: {fichier: octets}} de tout ce que la piste installe (fichiers enregistres, ajouts, manifeste,
    menu). Rien n'est ecrit."""
    per_archive = defaultdict(dict)
    for logical in (race_file(track), ttr_file(track), collision_file(track), start_finish.design_file(track),
                    start_finish.main_map_file(track), powerup.powerup_file(track)) + tuple(art_files(track)) \
            + tuple(dict.fromkeys(moved_away_logicals(track) + [lighting_file(track)])) + tuple(minimap_logicals(track)):
        p = saved_path(logical)
        if not os.path.exists(p):
            continue
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
    for info in {reg[m].get('material') for m in new_models} & set(tex):
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
    pu = saved_path(powerup.powerup_file(track))
    kinds = {c['kind'] for c in powerup.read_crates(open(pu, 'rb').read())} if os.path.exists(pu) else set()
    if 'boost' in kinds:
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
    return per_archive


# Plusieurs pistes installees : des archives sont PARTAGEES (update / update2, chunkinfos pour les noms,
# juicedomain_* pour les images de menu). Une archive est toujours remise a l'origine avant une installation : sans
# precaution, installer Roo's Tubes effacait de ces archives ce que Crash Cove y avait mis (piste et nom d'origine
# revenus). Chaque archive reecrite recoit donc aussi les fichiers des autres pistes installees.
def installed_path():
    return os.path.join(OUT_DIR, 'installed_tracks.json')


def installed_tracks():
    """Pistes installees : celles memorisees, plus celles dont l'archive propre porte une installation (avant
    l'existence de cette liste)."""
    p = installed_path()
    out = set(json.load(open(p))) if os.path.exists(p) else set()
    out |= {t for t in list_tracks() if os.path.exists(pak_tool.backup_path(os.path.join(ARCHIVES, track_pak(t))))}
    return out


def _set_installed(track, on):
    cur = set(json.load(open(installed_path()))) if os.path.exists(installed_path()) else set()
    cur = (cur | {track}) if on else (cur - {track})
    os.makedirs(OUT_DIR, exist_ok=True)
    json.dump(sorted(cur), open(installed_path(), 'w'))


def _others_for(archives, track, report):
    """{archive: {fichier: octets}} des AUTRES pistes installees, pour ces archives."""
    out = defaultdict(dict)
    for t in sorted(installed_tracks() - {track}):
        try:
            plan = install_plan(t)
        except Exception as e:  # noqa: BLE001 - piste illisible : signalee, l'installation continue
            report.append(f'{t} : fichiers non repris ({e})')
            continue
        for arc in archives:
            if plan.get(arc):
                out[arc].update(plan[arc])
                report.append(f'{os.path.basename(arc)} : {len(plan[arc])} fichier(s) de {t} gardé(s)')
    return out


def _rewrite(arc, reps):
    if os.path.exists(pak_tool.backup_path(arc)):
        pak_tool.uninstall(arc)
    if reps:
        pak_tool.install(arc, reps)


def install_track(track):
    progress.step('préparation des fichiers', 0.0)
    per_archive = install_plan(track)
    if not per_archive:
        raise RuntimeError('rien a installer : enregistrer d\'abord')
    kept = []
    progress.step('autres pistes installées', 0.03)
    # archives de menu modifiees par une installation precedente et plus concernees : remises a l'origine (avec les
    # fichiers des autres pistes qui s'y trouvaient)
    stale = [a for a in menu_track_archives(track) if a not in per_archive and os.path.exists(pak_tool.backup_path(a))]
    others = _others_for(list(per_archive) + stale, track, kept)
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
    _set_installed(track, True)
    if video:
        files.add(video)
    return {'installed_in': done, 'files': sorted(files), 'kept': kept}


def menu_track_archives(track):
    """Archives hors piste / mises a jour qui contiennent le nom ou les images de menu de la piste."""
    base = {os.path.join(ARCHIVES, n) for n in pak_tool.UPDATE_ARCHIVES + (track_pak(track),)}
    return sorted({a for lg in menu_logicals(track).values() for a in menu_archives(track, lg)} - base)


def uninstall_track(track):
    """Archives de la piste remises a l'origine ; les archives partagees gardent les fichiers des autres pistes
    installees (reinstalles aussitot)."""
    done, kept = [], []
    arcs = [os.path.join(ARCHIVES, n) for n in pak_tool.UPDATE_ARCHIVES + (track_pak(track),)] + menu_track_archives(track)
    arcs = [a for a in arcs if os.path.exists(pak_tool.backup_path(a))]
    _set_installed(track, False)
    others = _others_for(arcs, track, kept)
    for arc in arcs:
        _rewrite(arc, others.get(arc, {}))
        done.append(os.path.basename(arc))
    if set_menu_video(track, False):
        done.append(os.path.basename(menu_video(track)))
    return {'restored': done, 'kept': kept}


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
    if what in ('all', 'decor'):
        for logical in custom_models(track):
            if os.path.exists(custom_model_path(logical)):
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
                pre = f'<script>window.CTR_SETTINGS = {json.dumps(settings())};</script>\n'.encode()
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
            elif u.path == '/api/archives':
                self._send(200, archives_info())
            elif u.path == '/api/tracks':
                self._send(200, list_tracks())
            elif u.path == '/api/track':
                self._send(200, load_track(parse_qs(u.query)['name'][0]))
            elif u.path == '/api/decor':
                self._send(200, load_decor(parse_qs(u.query)['name'][0]))
            elif u.path == '/api/decor_collision':
                q = parse_qs(u.query)
                self._send(200, decor_collision_preview(q['track'][0], q['file'][0], int(q['id'][0])))
            elif u.path == '/api/materials':
                self._send(200, material_catalog(parse_qs(u.query)['track'][0]))
            elif u.path == '/api/model_preview':
                q = parse_qs(u.query)
                self._send(200, model_preview_binary(q['track'][0], q['file'][0]), 'application/octet-stream')
            elif u.path == '/api/texture':
                q = parse_qs(u.query)
                self._send(200, texture_png(q['track'][0], q['ns'][0]), 'image/png')
            elif u.path == '/api/model':
                q = parse_qs(u.query)
                self._send(200, model_binary(q['track'][0], q['file'][0]), 'application/octet-stream')
            elif u.path == '/api/library':
                self._send(200, library_catalog())
            elif u.path == '/api/route_objects':
                self._send(200, route_objects(parse_qs(u.query)['track'][0]))
            else:
                self._send(404, {'error': 'introuvable'})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self._send(500, {'error': repr(e)})

    PROGRESS_LABELS = {'/api/save': 'Enregistrement de la course', '/api/install': 'Installation dans le jeu',
                       '/api/uninstall': 'Désinstallation', '/api/reset': "Retour à l'original",
                       '/api/decor_save': 'Enregistrement du décor', '/api/import_model': 'Import du modèle',
                       '/api/set_custom_material': 'Texture du modèle', '/api/import_texture': "Import de l'image",
                       '/api/newmap': 'Nouvelle map', '/api/undo_save': 'Annulation',
                       '/api/gen_ai_splines': 'Génération des splines IA', '/api/route_layout': 'Création du parcours',
                       '/api/crates_auto': 'Placement des caisses', '/api/check': 'Vérification avant installation',
                       '/api/alpha_textures': 'Analyse des textures', '/api/set_alpha_textures': 'Transparence des textures',
                       '/api/minimap': 'Mini-carte', '/api/folder_scan': 'Analyse du dossier',
                       '/api/import_folder': 'Import du dossier', '/api/export_obj': 'Export OBJ',
                       '/api/light_info': 'Analyse du poids de la map', '/api/apply_light': 'Allègement de la map',
                       '/api/auto_falls': 'Chutes et réapparitions', '/api/menu_info': 'Lecture du nom et des images',
                       '/api/apply_menu': 'Nom et images de la piste', '/api/set_surface': 'Type de sol',
                       '/api/object_alpha': 'Transparence de la texture', '/api/surfaces': 'Types de sol',
                       '/api/ambiance_info': "Lecture de l'éclairage", '/api/set_ambiance': 'Ambiance',
                       '/api/place_library': "Ajout d'un objet de la bibliothèque", '/api/fix': 'Corrections'}

    def do_POST(self):
        try:
            req = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
            routes = {'/api/save': lambda: with_history(req['track'], 'course', lambda: save_track(req)),
                      '/api/install': lambda: install_track(req['track']),
                      '/api/uninstall': lambda: uninstall_track(req['track']),
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
                      '/api/minimap': lambda: (generate_minimap(req['track'], req['move']) if req.get('move')        # reglage fin : sans historique
                                                 else with_history(req['track'], 'mini-carte', lambda: generate_minimap(req['track']))),
                      '/api/folder_scan': lambda: folder_scan(req),
                      '/api/light_info': lambda: light_info(req['track']),
                      '/api/ambiance_info': lambda: ambiance_info(req['track']),
                      '/api/set_ambiance': lambda: with_history(req['track'], 'ambiance', lambda: set_ambiance(req)),
                      '/api/surfaces': lambda: {'surfaces': [{'value': s, 'label': l, 'safe': ok, **surface_params().get(s, {})}
                                                             for s, l, ok in SURFACES]},
                      '/api/set_surface': lambda: with_history(req['track'], 'type de sol', lambda: set_surface(req)),
                      '/api/object_alpha': lambda: with_history(req['track'], 'transparence', lambda: set_object_alpha(req)),
                      '/api/menu_info': lambda: menu_info(req['track']),
                      '/api/apply_menu': lambda: with_history(req['track'], 'nom et images de menu', lambda: apply_menu(req)),
                      '/api/auto_falls': lambda: with_history(req['track'], 'chutes et réapparitions', lambda: auto_falls(req)),
                      '/api/apply_light': lambda: with_history(req['track'], 'alléger la map', lambda: apply_light(req)),
                      '/api/import_folder': lambda: with_history(req['track'], f"import du dossier {req.get('folder') or 'map'}",
                                                                 lambda: import_folder(req)),
                      '/api/export_obj': lambda: export_obj(req),
                      '/api/archives': lambda: choose_archives(req),
                      '/api/pick_folder': lambda: pick_folder(req),
                      '/api/fix': lambda: with_history(req['track'], 'corrections : ' + ', '.join(req.get('fixes') or []),
                                                       lambda: apply_fixes(req)),
                      '/api/place_library': lambda: with_history(req['track'], f"bibliothèque : {os.path.basename(req.get('model') or '')[:-4]}",
                                                                 lambda: place_library(req))}
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


def ask_folder(title, initial=None):
    """Fenetre Windows de choix de dossier, ouverte par le serveur (meme PC) au premier plan."""
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    try:
        path = filedialog.askdirectory(parent=root, mustexist=True, title=title,
                                       initialdir=initial if initial and os.path.isdir(initial) else None)
    finally:
        root.destroy()
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
