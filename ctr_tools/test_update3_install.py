"""Installation / desinstallation reelles de l'editeur (server.install_track / uninstall_track) sur la COPIE DE TEST,
avec une copie du dossier d'editeur de test : update2 ne recoit aucun fichier ajoute, update3 garde l'enregistrement
des pistes creees, les formats 21:9 / 32:9 / 16:10 du lanceur OCTR restent acceptes.
python test_update3_install.py <dossier d'editeur de test> [piste] [dossier archives de la copie]"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, 'editor')]
import custom_category  # noqa: E402
import pak_tool  # noqa: E402
import server  # noqa: E402
import test_update3_layer as layer  # noqa: E402

SRC = sys.argv[1]
TRACK = sys.argv[2] if len(sys.argv) > 2 else 'T111_Crash_Cove'
A = sys.argv[3] if len(sys.argv) > 3 else os.environ.get('CTR_TEST_ARCHIVES') or sys.exit('usage : test_update3_install.py <dossier d''editeur de test> [piste] <dossier archives d''une COPIE du jeu>')
layer.A = A                       # le module lit sys.argv[1] a l'import : ici c'est le dossier d'editeur
fails = layer.fails
check = layer.check


def state():
    u2 = os.path.join(A, 'update2.pak')
    view = pak_tool.original_archive(u2)
    n_cur = len(pak_tool.cached_archive(u2)[0].entries)
    return n_cur, (len(view[0].entries) if view else n_cur), {k.lower() for k in custom_category._layer_index(A)}


def main():
    tmp = tempfile.mkdtemp(prefix='edit_')
    out = os.path.join(tmp, 'out')
    shutil.copytree(SRC, out, ignore=shutil.ignore_patterns('history', 'cache', 'creator'))
    server.ARCHIVES, server.OUT_DIR = A, out
    server.clear_caches()
    created = [t['id'] for t in (custom_category.read_state(A) or {}).get('tracks', [])]
    _, _, lay0 = state()
    r = server.install_track(TRACK)
    print('   installee dans :', r['installed_in'])
    pak_tool.invalidate_cache()
    n, n0, lay = state()
    check(n == n0, f'update2 : aucun fichier ajoute ({n} / {n0})')
    check(lay0 <= lay, 'update3 : enregistrement des pistes creees garde')
    plan = server.install_plan(TRACK)
    for arc, reps in plan.items():
        if os.path.basename(arc).lower() in custom_category.LAYERED:
            inst = {k.lower() for k in custom_category._installed_files(arc)}
            check({k.lower() for k in reps} <= inst, f'{os.path.basename(arc)} : {len(reps)} fichier(s) de {TRACK} installes (update3 compris)')
    res = layer.layouts_ok('apres installation')
    check(all(v is None for v in res.values()), 'formats acceptes apres installation')
    server.uninstall_track(TRACK)
    pak_tool.invalidate_cache()
    n, n0, lay = state()
    check(n == n0, 'desinstallation : update2 sans ajout')
    zones = {server.track_clone.zoneinfo_logical(t) for t in created}
    check(zones <= lay, f'desinstallation : pistes creees toujours enregistrees ({len(zones)})')
    res = layer.layouts_ok('apres desinstallation')
    check(all(v is None for v in res.values()), 'formats acceptes apres desinstallation')
    shutil.rmtree(tmp, ignore_errors=True)
    print('\n' + ('TOUT EST BON' if not fails else f'{len(fails)} ECHEC(S) : ' + ' | '.join(fails)))
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
