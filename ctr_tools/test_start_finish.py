"""Test : grille de depart (_Design), repere PlayerStartAll et zone de la ligne d'arrivee (RaceSystem).

Usage : python test_start_finish.py <dossier archives>
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'editor'))
import server  # noqa: E402

T = 'T111_Crash_Cove'


def check(cond, msg):
    print(('OK   ' if cond else 'ECHEC') + ' ' + msg)
    if not cond:
        raise SystemExit(1)


def main(archives):
    server.ARCHIVES = archives
    with tempfile.TemporaryDirectory() as d:
        server.OUT_DIR = d
        t = server.load_track(T)
        grid, ps = t['start_grid'], t['player_start']
        finish = [x for x in t['transitions'] if x['increment_lap']]
        check(len(grid) == 8 and [g['name'] for g in grid][0] == 'Starting_Waypoint_1st', 'grille : 8 places dans l\'ordre')
        check(ps is not None and len(finish) == 1 and finish[0]['dimensions'], 'repere de depart + une ligne d\'arrivee avec sa zone')
        dx = 500.0
        trans = {x['name']: {k: x[k] for k in ('increment_lap', 'previous_ai', 'next_ai', 'previous_position',
                                               'next_position', 'position', 'yaw', 'dimensions')} for x in t['transitions']}
        f = trans[finish[0]['name']]
        f['position'] = [f['position'][0] + dx] + f['position'][1:]
        f['yaw'] += 0.1
        f['dimensions'] = [600.0] + f['dimensions'][1:]
        r = server.save_track({'track': T, 'deleted': [], 'new_splines': [], 'starting_splines': t['starting_splines'],
                               'splines': {s['name']: s['control_points'] for s in t['splines']}, 'transitions': trans,
                               'start_grid': [dict(g, pos=[g['pos'][0] + dx] + g['pos'][1:]) for g in grid],
                               'player_start': dict(ps, pos=[ps['pos'][0] + dx] + ps['pos'][1:])})
        check(len(r['report']) == 3, 'enregistrement : zone, grille et repere signales')
        t2 = server.load_track(T)
        f2 = next(x for x in t2['transitions'] if x['name'] == finish[0]['name'])
        check(abs(f2['position'][0] - finish[0]['position'][0] - dx) < 1e-2 and abs(f2['yaw'] - finish[0]['yaw'] - 0.1) < 1e-4
              and f2['dimensions'][0] == 600.0 and f2['increment_lap'], 'zone de changement de tour deplacee, tournee, redimensionnee')
        check(all(abs(a['pos'][0] - b['pos'][0] - dx) < 1e-2 and abs(a['yaw'] - b['yaw']) < 1e-5
                  for a, b in zip(t2['start_grid'], grid)), 'grille relue : 8 places deplacees, caps inchanges')
        check(abs(t2['player_start']['pos'][0] - ps['pos'][0] - dx) < 1e-2, 'repere PlayerStartAll deplace')
        check(sorted(os.listdir(d)) == sorted([f'{T}.igz', f'{T}_Design.igz', f'{T}_RaceSystem.igz', f'{T}_TTRStats.igz']),
              'fichiers enregistres : principal, _Design, RaceSystem, TTRStats')
    # Sewer Speedway : grille « StartingPosition_001.. » dans le _RaceSystem (8 pistes sont ainsi)
    with tempfile.TemporaryDirectory() as d:
        server.OUT_DIR = d
        T2 = 'T114_Sewer_Speedway'
        check(server.grid_file(T2) == server.race_file(T2), 'Sewer Speedway : grille dans le _RaceSystem')
        g = server.load_track(T2)['start_grid']
        server.save_track({'track': T2, 'splines': {}, 'transitions': {},
                           'start_grid': [dict(s, pos=[s['pos'][0] + 100] + s['pos'][1:]) for s in g]})
        g2 = server.load_track(T2)['start_grid']
        check(len(g) == 8 and all(abs(a['pos'][0] - b['pos'][0] - 100) < 1e-2 for a, b in zip(g2, g))
              and not os.path.exists(server.saved_path(server.start_finish.design_file(T2))),
              'grille du _RaceSystem deplacee et relue, _Design non touche')
    print('tous les tests passent')


if __name__ == '__main__':
    main(sys.argv[1])
