"""Boosters dans le _Design (contre-la-montre) et controle du survol. Rien n'est ecrit dans les archives : dossier de
sortie temporaire. python test_boost_design.py [dossier archives]"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, 'editor')]
import numpy as np  # noqa: E402
import server  # noqa: E402
import pak_tool  # noqa: E402
import pkg_manifest  # noqa: E402
import powerup  # noqa: E402
import start_finish  # noqa: E402
from igz import IgzFile  # noqa: E402

server.ARCHIVES = sys.argv[1] if len(sys.argv) > 1 else os.environ.get('CTR_TEST_ARCHIVES') or sys.exit('usage : test_boost_design.py <dossier archives d''une COPIE du jeu>')
server.OUT_DIR = tempfile.mkdtemp(prefix='boost_')
fails = []


def check(cond, text):
    print(('ok   ' if cond else 'ECHEC') + ' ' + text)
    if not cond:
        fails.append(text)


def reset():
    shutil.rmtree(server.OUT_DIR, ignore_errors=True)
    os.makedirs(server.OUT_DIR)
    server.clear_caches()


def boost(x, y, z=0.0):
    return {'kind': 'boost', 'pos': [x, y, z], 'yaw': 0.5, 'dims': [800.0, 1000.0, 1000.0]}


def save_crates(track, want):
    logical = server.crate_file(track)
    z, _ = server.write_crates_file(track, want)
    server.safe_compact(track, logical, z)
    z.save(server.saved_path(logical))


def roots(data):
    return {n for n, _ in IgzFile(data).root_objects() if n}


def powerup_case(track):
    reset()
    design, pu = start_finish.design_file(track), powerup.powerup_file(track)
    orig_design = pak_tool.read_latest(server.ARCHIVES, design, server.track_pak(track))[0]
    crates = server.read_track_crates(track)
    n_crates = len(crates)
    save_crates(track, crates + [boost(100, 200), boost(300, 400)])
    pu_saved = open(server.saved_path(pu), 'rb').read()
    de_saved = open(server.saved_path(design), 'rb').read()
    check(not [c for c in powerup.read_crates(pu_saved) if c['kind'] == 'boost'], f'{track} : aucun booster dans le _Power_Up')
    got = powerup.read_crates(de_saved, True)
    check(sum(c['kind'] == 'boost' for c in got) == 2, f'{track} : 2 boosters dans le _Design')
    check(roots(orig_design) <= roots(de_saved), f'{track} : entites du _Design gardees')
    tr = server.read_track_crates(track)
    check(len(tr) == n_crates + 2, f'{track} : lecture caisses + boosters ({len(tr)})')
    b = [c for c in tr if c['kind'] == 'boost']
    check(b[0]['pos'][:2] == [100, 200] and b[0]['dims'] == [800.0, 1000.0, 1000.0] and abs(b[0]['yaw'] - 0.5) < 1e-4,
          f'{track} : position, cap et taille relus')
    check(start_finish.read_grid(de_saved) == start_finish.read_grid(orig_design), f'{track} : grille inchangee')
    # enregistrements repetes : la taille ne grossit pas
    size = len(de_saved)
    for _ in range(3):
        save_crates(track, server.read_track_crates(track))
    size2 = os.path.getsize(server.saved_path(design))
    check(size2 <= size + 4096, f'{track} : taille stable apres 3 enregistrements ({size} -> {size2})')
    check(sum(c['kind'] == 'boost' for c in server.read_track_crates(track)) == 2, f'{track} : toujours 2 boosters')
    entries = server.install_plan(track)
    man = pkg_manifest.manifest_logical(track)
    arc = next(a for a in entries if man in entries[a])
    rows = pkg_manifest.entries(entries[arc][man])
    check(('vsc', powerup.BOOST_SCRIPT) in rows, f'{track} : script des boosters au manifeste')
    want = {a for a in pak_tool.archives_with(server.ARCHIVES, design, server.track_pak(track))}
    check(want <= {a for a in entries if design in entries[a]}, f'{track} : _Design installe dans {len(want)} archive(s)')
    # retrait
    save_crates(track, [c for c in server.read_track_crates(track) if c['kind'] != 'boost'])
    check(not [c for c in server.read_track_crates(track) if c['kind'] == 'boost'], f'{track} : boosters retires')
    check(roots(open(server.saved_path(design), 'rb').read()) == roots(orig_design), f'{track} : _Design revenu a ses entites')


def legacy_case(track):
    """Piste enregistree par une version precedente : boosters dans le _Power_Up."""
    reset()
    read = lambda p, pak: pak_tool.read_latest(server.ARCHIVES, p, pak)[0]
    pu = powerup.powerup_file(track)
    crates = powerup.read_crates(read(pu, server.track_pak(track)))
    z, _, _ = powerup.write_crates(read(pu, server.track_pak(track)), crates + [boost(1, 2), boost(3, 4), boost(5, 6)],
                                   powerup.boost_donor(read), None, server._crate_height_at(track))
    z.save(server.saved_path(pu))
    check(len([c for c in server.read_track_crates(track) if c['kind'] == 'boost']) == 3, f'{track} ancien : 3 boosters lus')
    server.install_plan(track)
    check(not [c for c in powerup.read_crates(open(server.saved_path(pu), 'rb').read()) if c['kind'] == 'boost'],
          f'{track} ancien : _Power_Up vide de boosters apres installation')
    d = powerup.read_crates(open(server.saved_path(start_finish.design_file(track)), 'rb').read(), True)
    check(sum(c['kind'] == 'boost' for c in d) == 3, f'{track} ancien : 3 boosters passes dans le _Design')
    check(len(server.read_track_crates(track)) == len(crates) + 3, f'{track} ancien : aucun doublon')
    check(not server.migrate_boosters(track), f'{track} ancien : migration faite une seule fois')


def native_case(track):
    """Piste du jeu qui a deja des boosters dans son _Design : ils restent."""
    reset()
    design = start_finish.design_file(track)
    orig = pak_tool.read_latest(server.ARCHIVES, design, server.track_pak(track))[0]
    check(not [n for n in roots(orig) if n.startswith(powerup.BOOST_OWN)], f'{track} : prefixe libre dans le jeu')
    check(not [c for c in server.read_track_crates(track) if c['kind'] == 'boost'], f'{track} : boosters du jeu non repris')
    native = powerup.read_crates(orig, True)
    save_crates(track, server.read_track_crates(track) + [boost(10, 20)])
    saved = open(server.saved_path(design), 'rb').read()
    check(roots(orig) <= roots(saved), f'{track} : boosters du jeu gardes')
    check(sum(c['kind'] == 'boost' for c in server.read_track_crates(track)) == 1, f'{track} : 1 booster ajoute')
    after = {c['name']: c for c in powerup.read_crates(saved, True)}
    check(all(after.get(c['name']) == c for c in native), f'{track} : boosters du jeu a la meme place')
    save_crates(track, [c for c in server.read_track_crates(track) if c['kind'] != 'boost'])
    check(roots(open(server.saved_path(design), 'rb').read()) == roots(orig), f'{track} : retrait sans toucher au jeu')


def flyby_case(track):
    reset()
    lv = lambda: [c for c in server.preinstall_check(track)['checks'] if c['topic'].startswith('Survol')]
    c = lv()
    check(len(c) == 1 and c[0]['level'] == 'ok', f"{track} piste d'origine : {c[0]['text'] if c else '?'}")
    shots = server.flyby_shots(track)
    # nouvelle map : parcours refait, cameras d'origine
    open(server.road_source_path(track), 'w').write('{}')
    c = lv()
    check(c[0]['level'] == 'attention' and c[0].get('fix') == 'flyby', f"{track} nouvelle map : {c[0]['text']}")
    msg = server.fix_flyby(track)
    print('     ', msg)
    c = lv()
    check(c[0]['level'] == 'ok', f"{track} apres correction : {c[0]['text']}")
    # un plan remis d'origine
    models = server.load_flyby(track)
    models.pop(shots[0]['key'])
    server.apply_flyby(track, models)
    c = lv()
    check(c[0]['level'] == 'attention', f"{track} plan manquant : {c[0]['text']}")
    # survol fixe : la fin reste pres de la grille
    server.apply_flyby(track, server.flyby_auto({'track': track, 'mode': 'fixed'})['models'])
    check(lv()[0]['level'] == 'ok', f'{track} plan fixe accepte')
    # survol qui ne finit plus sur la grille
    models = server.load_flyby(track)
    for k, s in zip(models, shots):
        m = models[k]
        m['end']['pos'] = [v + 20000 for v in m['end']['pos']]
    server.apply_flyby(track, models)
    c = lv()
    check(c[0]['level'] == 'attention' and 'grille' in c[0]['text'], f"{track} perime : {c[0]['text']}")
    server.fix_flyby(track)
    check(lv()[0]['level'] == 'ok', f'{track} perime corrige')


if __name__ == '__main__':
    powerup_case('T111_Crash_Cove')
    legacy_case('T111_Crash_Cove')
    for t in ('T113_Mystery_Caves', 'T114_Sewer_Speedway', 'T134_Dingo_Canyon', 'T143_Polar_Pass', 'T151_NGin_Labs',
              'T152_Cortex_Castle', 'T154_Oxide_Station', 'T213_Tiny_Temple', 'T221_Meteor_Gorge', 'T222_Barin_Ruins',
              'T231_Out_of_Time', 'T232_Clockwork_Wumpa', 'T255_Hyper_Spaceway'):
        native_case(t)
    flyby_case('T111_Crash_Cove')
    shutil.rmtree(server.OUT_DIR, ignore_errors=True)
    print('\n' + ('TOUT EST BON' if not fails else f'{len(fails)} ECHEC(S) : ' + ' | '.join(fails)))
    sys.exit(1 if fails else 0)
