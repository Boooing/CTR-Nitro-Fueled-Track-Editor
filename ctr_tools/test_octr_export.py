"""Export OCTR a plusieurs pistes : T901 + T902 de la copie de test, noms et categorie choisis. Rien n'est ecrit dans
les archives : sorties dans un dossier temporaire (out/editor vide : pistes creees sans modification, plus une image de
menu enregistree pour verifier qu'elle l'emporte sur l'enregistrement).
python test_octr_export.py [dossier archives] [validateur package_mod.py]"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, 'editor')]
import custom_category  # noqa: E402
import menu_assets  # noqa: E402
import octr_export  # noqa: E402
import pak_tool  # noqa: E402
import pkg_manifest  # noqa: E402
import server  # noqa: E402
import track_clone  # noqa: E402

A = sys.argv[1] if len(sys.argv) > 1 else os.environ.get('CTR_TEST_ARCHIVES') or sys.exit('usage : test_octr_export.py <dossier archives d''une COPIE du jeu, avec T901 et T902 creees> [package_mod.py]')
VALID = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(HERE), 'CTR-NitroFueled-PC-portable', 'scripts', 'package_mod.py')
T1, T2 = 'T901_Custom_Map', 'T902_Custom_Map'
fails = []


def check(cond, text):
    print(('ok   ' if cond else 'ECHEC') + ' ' + text)
    if not cond:
        fails.append(text)


def tree_hash(root):
    h = hashlib.sha256()
    for f in sorted(os.listdir(root)):
        p = os.path.join(root, f)
        if os.path.isfile(p):
            s = os.stat(p)
            h.update(f'{f}{s.st_size}{s.st_mtime_ns}'.encode())
    return h.hexdigest()


def main():
    tmp = tempfile.mkdtemp(prefix='octr_')
    server.ARCHIVES, server.OUT_DIR, server.PROJECT_DIR = A, os.path.join(tmp, 'out'), tmp
    os.makedirs(server.OUT_DIR)
    server.clear_caches()
    before = tree_hash(A)
    info = {t['track']: t for t in octr_export.tracks_info()['tracks']}
    check(T1 in info and T2 in info and info[T1]['created'], 'les deux pistes creees sont proposees')
    check(info[T1]['group'] == 'Mario Kart 8', f"groupe actuel propose : {info[T1]['group']}")
    r = octr_export.build({'tracks': [{'track': T1, 'name': 'Circuit Lune'}, {'track': T2, 'name': 'Volcan Été'}, {'track': T1, 'name': 'doublon'}],
                           'category': 'Ma Coupe d\'Été', 'mod_name': 'Mon Pack', 'version': '1.2.3'})
    print('\n'.join('      ' + l for l in r['report']))
    check(r['track_ids'] == [T1, T2], 'deux pistes enregistrees, doublon ignore')
    check(r['name'] == 'mon-pack-1.2.3.zip', f"nom du fichier sans prefixe : {r['name']}")
    check(r['id'] == 'ctr-editor-mon-pack', f"identifiant du mod garde : {r['id']}")
    x = os.path.join(tmp, 'x')
    with zipfile.ZipFile(r['path']) as z:
        z.extractall(x)
    man = json.load(open(os.path.join(x, 'mod.json'), encoding='utf-8'))
    check(man['name'] == 'Mon Pack' and man['version'] == '1.2.3' and man['compatibility']['online'] == 'allowed', 'manifeste du mod')
    paks = sorted(os.listdir(os.path.join(x, 'archives')))
    check([p for p in paks if p == 'update3.pak'] and all(any(p.startswith(t.lower()) for p in paks) for t in (T1, T2)), f'archives : {paks}')
    a, idx, _ = pak_tool.cached_archive(os.path.join(x, 'archives', 'update3.pak'))
    low = [e.logical_name.lower() for e in a.entries]
    check(len(low) == len(set(low)), 'update3 : pas de fichier en double (casse comprise)')
    read = lambda n: a.read(idx[n.lower()])
    cats = custom_category.categories(read(custom_category.PROTO))
    want = [track_clone.zone_name(T1), track_clone.zone_name(T2)]
    title = cats[-1][0].encode('latin1').decode('utf-8')          # le jeu lit de l'UTF-8
    check(title == 'Ma Coupe d\'Été' and [v.lower() for v in cats[-1][1]] == want, f'menu : dernier groupe {title} {cats[-1][1]}')
    check(sum(1 for c in cats if any(v.lower() in want for v in c[1])) == 1, 'pistes dans une seule categorie')
    races = {v.lower() for v in custom_category.race_levels(read(custom_category.GUI_DATA))}
    check(set(want) <= races, 'liste des pistes de course : les deux')
    chunks = {p.lower() for _, p in pkg_manifest.entries(read(track_clone.CHUNKINFOS))}
    check(all(track_clone.zoneinfo_logical(t) in chunks for t in (T1, T2)), 'chunkInfos : les deux')
    for t, n in ((T1, 'Circuit Lune'), (T2, 'Volcan Été')):
        for lang in track_clone.LANGS:
            key = track_clone.lng_logical(t, lang).lower()
            if key in idx:
                got = menu_assets.read_name(a.read(idx[key]))
                check(got == n, f'{t} {lang} : nom {got}')
                break
    with zipfile.ZipFile(r['path']) as z:
        check(z.testzip() is None, 'zip lisible')
    a.f.close()
    v = subprocess.run([sys.executable, VALID, x, '--validate'], capture_output=True, text=True)
    check(v.returncode == 0, 'validateur OCTR : ' + (v.stdout or v.stderr).strip()[:200])
    # une seule piste, sans nom de mod
    s = octr_export.build({'track': T1, 'name': 'Seule', 'category': 'Solo'})
    check(s['id'] == 'ctr-editor-seule', f"une seule piste : {s['id']}")
    # copie d'une piste du jeu dont l'image de fond a ete changee : la copie l'affiche, la piste du jeu garde la sienne
    src = 'T111_Crash_Cove'
    bg = server.menu_image_logical(src, 'background')
    mine = server._menu_original('T113_Mystery_Caves', server.menu_image_logical('T113_Mystery_Caves', 'background'))[0]
    open(server.saved_path(bg), 'wb').write(mine)
    c = octr_export.build({'tracks': [{'track': src, 'mode': 'new', 'name': 'Copie'}], 'category': 'Copies'})
    new = c['track_ids'][0]
    y = os.path.join(tmp, 'y')
    with zipfile.ZipFile(c['path']) as z:
        z.extractall(y, [n for n in z.namelist() if n.endswith('update3.pak')])
    b, ib, _ = pak_tool.cached_archive(os.path.join(y, 'archives', 'update3.pak'))
    own = menu_assets.own_image_file(new, 'background').lower()
    check(own in ib and b.read(ib[own]) == mine, f'{new} : son fond est l\'image choisie')
    check(bg.lower() not in ib, 'Crash Cove garde son image d\'origine')
    b.f.close()
    pak_tool.invalidate_cache(os.path.join(y, 'archives', 'update3.pak'))
    for bad, msg in (({'tracks': []}, 'aucune piste'), ({'tracks': [{'track': 'T999_Nope'}]}, 'piste inconnue'),
                     ({'tracks': [{'track': T1, 'name': 'x' * 41}]}, 'nom trop long'), ({'tracks': [{'track': T1, 'mode': 'autre'}]}, 'mode inconnu')):
        try:
            octr_export.build(bad)
            check(False, f'refus attendu : {msg}')
        except ValueError:
            check(True, f'refuse : {msg}')
    check(tree_hash(A) == before, 'dossier du jeu inchange')
    pak_tool.invalidate_cache(os.path.join(x, 'archives', 'update3.pak'))
    shutil.rmtree(tmp, ignore_errors=True)
    print('\n' + ('TOUT EST BON' if not fails else f'{len(fails)} ECHEC(S) : ' + ' | '.join(fails)))
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
