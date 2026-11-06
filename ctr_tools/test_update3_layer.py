"""update3.pak de l'editeur (custom_category.store) sur la COPIE DE TEST du jeu (ecrit dans ses archives).
Verifie : update2 ne recoit plus de fichier ajoute ni le menu ; les formats 21:9 et 32:9 du lanceur OCTR retrouvent
leurs fichiers (leur vrai controle, sorties dans un dossier temporaire) ; le 16:10 trouve sa jauge ; l'editeur voit
toujours ces fichiers « dans update2 » ; retrait et remise.
python test_update3_layer.py [dossier archives de la copie]"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = os.path.join(os.path.dirname(HERE), 'CTR-NitroFueled-PC-portable', 'scripts')
sys.path[:0] = [HERE, PORT]
import custom_category  # noqa: E402
import pak_tool  # noqa: E402
import track_clone  # noqa: E402

A = sys.argv[1] if len(sys.argv) > 1 else os.environ.get('CTR_TEST_ARCHIVES') or sys.exit('usage : test_update3_layer.py <dossier archives d''une COPIE du jeu>')
fails = []


def check(cond, text):
    print(('ok   ' if cond else 'ECHEC') + ' ' + text)
    if not cond:
        fails.append(text)


def layouts_ok(tag):
    """Vrai controle du lanceur (widescreen.archive_patches, aspect_hud.prepare) : -> {format: None | erreur}."""
    import aspect_hud
    import widescreen as ws
    game, out = os.path.dirname(A), tempfile.mkdtemp(prefix='ws_')
    res = {}
    try:
        for lay, size in (('21x9', '3440x1440'), ('32x9', '5120x1440')):
            s = {'aspect_ratio': lay, 'widescreen_layout': lay, 'aspect_output': size, 'widescreen_output': size, 'render_res': '1080'}
            folder = ws.DATA / f'ultrawide-{lay}'
            c = ws.selection(s)
            _, flat = ws.fmt.resolve(ws.fmt.validate_folder(folder), dict(s, output_res=c[1], render_res=c[2]))
            shaders = [o for o in flat['operations'] if o['kind'].startswith('shader_')]
            assets = [o for o in flat['operations'] if o['kind'] == 'archive_asset']
            try:
                ws.archive_patches(game, out, folder, assets, {}, text_factor=shaders[0]['factor'])
                res[lay] = None
            except (OSError, ValueError, KeyError) as e:
                res[lay] = str(e)
        try:
            res['16x10'] = None if aspect_hud.prepare(game, out, {}) else 'aucune archive'
        except (OSError, ValueError) as e:
            res['16x10'] = str(e)
    finally:
        shutil.rmtree(out, ignore_errors=True)
    print(f'   [{tag}] formats : {res}')
    return res


def main():
    st = custom_category.read_state(A)
    check(bool(st and st.get('tracks')), f"copie avec pistes creees : {[t['id'] for t in (st or {}).get('tracks', [])]}")
    u2 = os.path.join(A, 'update2.pak')
    before = layouts_ok('avant')
    custom_category._apply(A)                         # reecrit update2 comme une installation : migration
    pak_tool.invalidate_cache()
    lay = custom_category._layer_index(A)
    check(os.path.exists(custom_category.layer_path(A)) and lay, f'update3.pak de l\'editeur : {len(lay)} fichier(s)')
    zones = [track_clone.zoneinfo_logical(t['id']) for t in st['tracks']]
    check(all(z in {k.lower() for k in lay} for z in zones), 'zoneInfo des pistes creees dans update3')
    check(custom_category.PROTO in lay, 'menu dans update3')
    view = pak_tool.original_archive(u2)
    cur = pak_tool.cached_archive(u2)
    if view is None:
        check(not os.path.exists(pak_tool.backup_path(u2)), 'update2 : plus rien d\'installe, remis a l\'origine')
    else:
        check(len(cur[0].entries) == len(view[0].entries), f'update2 : autant de fichiers qu\'a l\'origine ({len(cur[0].entries)} / {len(view[0].entries)})')
    info = pak_tool._backup_info(u2) or {'files': []}
    check(not {n.lower() for n in info['files']} & custom_category._menu_names(), 'update2 : plus de fichier du menu')
    inst = custom_category._installed_files(u2)
    check(all(z in {k.lower() for k in inst} for z in zones), 'l\'editeur voit toujours les fichiers « dans update2 »')
    data, p = pak_tool.read_latest(A, zones[0], original=False)
    check(os.path.basename(p) == 'update3.pak', f'lecture de la version installee : {os.path.basename(p)}')
    check(not os.path.basename(pak_tool.read_latest(A, custom_category.PROTO)[1]) == 'update3.pak', 'vue d\'origine : jamais update3')
    after = layouts_ok('apres')
    check(all(v is None for v in after.values()), f'21:9, 32:9 et 16:10 acceptes : {after}')
    # retrait du menu puis remise
    saved = json.load(open(custom_category.state_path(A), encoding='utf-8'))
    custom_category.uninstall(A)
    check(not os.path.exists(custom_category.layer_path(A)) and not custom_category._layer_index(A), 'retrait : update3.pak supprime')
    json.dump(saved, open(custom_category.state_path(A), 'w'), indent=1)
    track_clone.chunks_igx_set(os.path.dirname(A), [p for t in saved['tracks'] for p in t['paks']])
    custom_category._apply(A)
    check(custom_category.PROTO in custom_category._layer_index(A), 'remise : menu de nouveau dans update3')
    # un update3.pak qui n'est pas a nous n'est jamais ecrase
    tmp = tempfile.mkdtemp(prefix='l3_')
    Path(tmp, 'update3.pak').write_bytes(b'mod')
    try:
        custom_category._layer_write(tmp, 'update2.pak', {'a.igz': b'x'})
        check(False, 'update3.pak etranger refuse')
    except RuntimeError:
        check(True, 'update3.pak etranger refuse')
    shutil.rmtree(tmp, ignore_errors=True)
    print('   avant la migration (pour memoire) :', before)
    print('\n' + ('TOUT EST BON' if not fails else f'{len(fails)} ECHEC(S) : ' + ' | '.join(fails)))
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
