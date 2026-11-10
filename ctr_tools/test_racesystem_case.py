"""Parcours ranges autrement que dans <piste>_RaceSystem.igz : T233 « _Racesystem », T231 et T243 « _Race_System », T212, T213,
T221, T223, T232, T241 et T255 dans le _Design (meme fichier pour le parcours, la grille, les caisses...), positions dans le
_Design (T153, T243), splines portees par des CGameEntity (T151, T212). Liste, decodage et enregistrement.
Rien n'est ecrit dans le jeu : l'enregistrement va dans un dossier temporaire.
python test_racesystem_case.py <dossier archives>"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'editor'))
import pak_tool  # noqa: E402
import race_entities  # noqa: E402
import server as S  # noqa: E402
import start_finish  # noqa: E402
from igz import IgzFile  # noqa: E402
from race_entities import RaceSystemEditor  # noqa: E402
from race_system import RaceSystem  # noqa: E402

A = sys.argv[1] if len(sys.argv) > 1 else os.environ.get('CTR_TEST_ARCHIVES') or sys.exit('usage : test_racesystem_case.py <dossier archives>')
S.ARCHIVES = A
tmp = tempfile.mkdtemp(prefix='rs_')
S.OUT_DIR = tmp

#        piste                     espace de noms du fichier
CASES = {'T233_Thunder_Struck': '_Racesystem', 'T231_Out_of_Time': '_Race_System', 'T243_Electron_Avenue': '_Race_System',
         'T153_Hot_Air_Skyway': '_RaceSystem', 'T151_NGin_Labs': '_RaceSystem', 'T111_Crash_Cove': '_RaceSystem',
         'T212_Jungle_Boogie': '_Design', 'T213_Tiny_Temple': '_Design', 'T221_Meteor_Gorge': '_Design',
         'T223_Deep_Sea_Driving': '_Design', 'T232_Clockwork_Wumpa': '_Design', 'T241_Assembly_Lane': '_Design',
         'T255_Hyper_Spaceway': '_Design'}


def links(data, T):
    """Les liens des transitions tels qu'ecrits dans le fichier : {transition: {liste: [(nom, fichier)]}}."""
    ed = RaceSystemEditor(data, T)
    return {name: {k: ed.igz.handle_list(ed.igz.deref(comp + off)) for k, off in race_entities.FIELDS.items()}
            for name, comp in ed.transitions().items()}


try:
    listed = S.list_tracks()
    assert not [t for t in listed if t.lower().endswith('_outro')], listed
    for T, spelled in CASES.items():
        assert T in listed, T
        logical = S.race_file(T)
        in_design = spelled == '_Design'
        assert in_design == (logical == start_finish.design_file(T)), logical
        data = pak_tool.read_latest(A, logical, S.track_pak(T))[0]
        assert RaceSystemEditor(data, T).ns == T + spelled, (T, RaceSystemEditor(data, T).ns)

        # decodage : tout ce que les transitions citent dans ce fichier existe, splines de depart comprises
        tr = S.load_track(T)
        names = {s['name'] for s in tr['splines']}
        cited = {x for t in tr['transitions'] for k in ('next_ai', 'previous_ai') for x in t[k]}
        assert cited <= names, (T, sorted(cited - names)[:6])
        ai = {s['name'] for s in tr['splines'] if s['kind'] == 'ai_paths'}
        assert ai, T
        assert set(tr['starting_splines']) <= ai | names, (T, tr['starting_splines'])
        assert 'GPI_Magnet_spline' not in names

        # enregistrement sans changement : memes liens, meme fichier cible
        before = links(data, T)
        S.save_track({'track': T, 'transitions': {t['name']: {k: t[k] for k in S.LIST_KEYS} for t in tr['transitions']}})
        assert links(open(S.saved_path(logical), 'rb').read(), T) == before, T

        # enregistrement avec tout a la fois : rien ne doit ecraser le reste (le _Design est ecrit par plusieurs etapes)
        moved = next(s for s in tr['splines'] if s['kind'] == 'ai_paths')
        pts = [[p[0] + 500.0, p[1], p[2]] for p in moved['control_points']]
        req = {'track': T, 'splines': {moved['name']: pts},
               'transitions': {t['name']: {k: t[k] for k in S.LIST_KEYS} for t in tr['transitions']}}
        design_roots = dict(IgzFile(S.base_file(T, start_finish.design_file(T))[0]).root_objects())
        respawns = [str(r).split('::')[-1] for s in tr['splines'] for r in (s.get('respawn_points') or [])]
        pose_name = next((n for n in respawns if n in design_roots), None)
        if pose_name:
            req['design_poses'] = {pose_name: {'pos': [111.0, 222.0, 333.0], 'yaw': 0.5}}
        crates = [dict(c) for c in tr['crates']]
        crate = next((c for c in crates if c['kind'] == 'question'), None)
        if crate:
            crate['pos'] = [crate['pos'][0] + 300.0, crate['pos'][1], crate['pos'][2]]
            req['crates'] = crates
        if tr['fall_zones']:
            z = tr['fall_zones'][0]
            req['fall_zones'] = [{'name': z['name'], 'pos': [z['pos'][0] + 77.0, z['pos'][1], z['pos'][2]], 'dims': z['dims']}]
        tp = next((t for t in tr['transitions'] if not t['increment_lap'] and not t.get('teleporter')), None)
        if tp and in_design:
            req['teleporters'] = dict(tr['teleporters'], **{tp['name']: {'pos': [10.0, 20.0, 30.0], 'yaw': 0.0}})
        S.save_track(req)

        saved = open(S.saved_path(logical), 'rb').read()
        again = S.load_track(T)
        got = next(s for s in again['splines'] if s['name'] == moved['name'])['control_points']
        assert all(abs(a[0] - b[0]) < 0.01 for a, b in zip(got, pts)), (T, 'spline perdue')
        checks = ['spline']
        if pose_name:
            p = start_finish.read_entity_poses(S.base_file(T, start_finish.design_file(T))[0], [pose_name])[pose_name]
            assert [round(c) for c in p['pos']] == [111, 222, 333], (T, 'point de reapparition perdu', p)
            checks.append('reapparition')
        if crate:
            hit = [c for c in again['crates'] if c['name'] == crate['name']]
            assert hit and abs(hit[0]['pos'][0] - crate['pos'][0]) < 0.5, (T, 'caisse perdue')
            checks.append('caisse')
        if tr['fall_zones']:
            hit = [z2 for z2 in again['fall_zones'] if z2['name'] == z['name']]
            assert hit and abs(hit[0]['pos'][0] - z['pos'][0] - 77.0) < 0.5, (T, 'zone de chute perdue')
            checks.append('zone')
        if 'teleporters' in req:
            assert set(req['teleporters']) <= set(again['teleporters']), (T, 'teleporteur perdu')
            assert S.teleport.dest_name(tp['name']) in dict(IgzFile(saved).root_objects()), (T, 'arrivee perdue')
            checks.append('teleporteur')
        spaces = {ns for t in links(saved, T).values() for lst in t.values() for h in lst if h for ns in [h[1]]}
        assert T + spelled in spaces and all(ns in (T + spelled, f'{T}_Design') for ns in spaces), (T, spaces)
        print(f"ok {T} ({spelled}) : {len(ai)} IA, {len(names) - len(ai)} position, {len(tr['transitions'])} transitions, garde : {', '.join(checks)}")
        pak_tool.invalidate_cache()

    # portail hors transition (Teleporter_02 de T255) : zone et arrivee modifiables, Teleporter_01 (meme arrivee) intact
    T, P = 'T255_Hyper_Spaceway', 'Teleporter_02'
    for name in os.listdir(tmp):
        if os.path.isfile(os.path.join(tmp, name)):
            os.remove(os.path.join(tmp, name))
    pak_tool.invalidate_cache()
    tr = S.load_track(T)
    assert list(tr['portals']) == [P] and P not in tr['teleporters'] and 'Teleporter_01' in tr['teleporters'], tr['portals']
    assert not any(t['name'] == P for t in tr['transitions'])
    for other in S.list_tracks():                                # le seul du jeu
        if other != T:
            assert not S.load_track(other)['portals'], other
    p0, t01 = tr['portals'][P], tr['teleporters']['Teleporter_01']
    assert p0['arrival']['name'] == t01['arrival'] == 'Teleport_Destination_02'
    # sans changement : rien n'est ecrit pour le portail
    assert not [r for r in S.save_track({'track': T, 'portals': {P: p0}})['report'] if P in r]
    # zone seule : l'arrivee reste partagee
    want = {'position': [p0['position'][0] + 100.0, p0['position'][1], p0['position'][2]], 'yaw': 0.7,
            'dimensions': [6000.0, 1200.0, 1500.0], 'arrival': p0['arrival']}
    S.save_track({'track': T, 'portals': {P: want}})
    p1 = S.load_track(T)['portals'][P]
    assert abs(p1['position'][0] - want['position'][0]) < 0.01 and abs(p1['yaw'] - 0.7) < 1e-3 and p1['dimensions'] == want['dimensions'], p1
    assert p1['arrival']['name'] == 'Teleport_Destination_02', p1['arrival']
    # arrivee deplacee : entite propre, Teleporter_01 ne bouge pas, liens du parcours intacts
    design = start_finish.design_file(T)
    links0 = links(open(S.saved_path(design), 'rb').read(), T)
    S.save_track({'track': T, 'portals': {P: dict(p1, arrival={'pos': [1000.0, 2000.0, 3000.0], 'yaw': 1.0})}})
    tr2 = S.load_track(T)
    a = tr2['portals'][P]['arrival']
    assert a['name'] == S.teleport.dest_name(P) and [round(c) for c in a['pos']] == [1000, 2000, 3000] and abs(a['yaw'] - 1.0) < 1e-3, a
    assert tr2['teleporters']['Teleporter_01'] == t01, tr2['teleporters']['Teleporter_01']
    assert links(open(S.saved_path(design), 'rb').read(), T) == links0
    # les transitions teleporteurs et le portail ne se genent pas
    S.save_track({'track': T, 'teleporters': tr2['teleporters']})
    assert S.load_track(T)['portals'][P]['arrival']['name'] == S.teleport.dest_name(P)
    # supprime : ecarte sous la carte, plus liste, jamais retire du fichier
    S.save_track({'track': T, 'portals': {P: dict(tr2['portals'][P], deleted=True)}})
    assert not S.load_track(T)['portals']
    assert P in dict(IgzFile(open(S.saved_path(design), 'rb').read()).root_objects())
    print('ok portail : zone, arrivee propre, Teleporter_01 intact, suppression')
finally:
    pak_tool.invalidate_cache()
    shutil.rmtree(tmp, ignore_errors=True)
print('TOUT EST BON')
