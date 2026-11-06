"""update3.pak avec tres peu de fichiers (jeu d'origine, nouvelle categorie : le menu seul). Rien n'est ecrit dans le jeu :
dossier temporaire, l'archive du jeu ne sert que de modele d'en-tete.
python test_update3_small.py <dossier archives>"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import custom_category as cc  # noqa: E402
import pak_tool  # noqa: E402
import track_clone  # noqa: E402

A = sys.argv[1] if len(sys.argv) > 1 else os.environ.get('CTR_TEST_ARCHIVES') or sys.exit('usage : test_update3_small.py <dossier archives>')
tmp = tempfile.mkdtemp(prefix='u3_')
try:
    u2 = os.path.join(tmp, 'update2.pak')
    track_clone.write_archive(u2, [('a/base.igz', pak_tool.FULL_PREFIX + 'a/base.igz', 0, ('data', b'base'))], os.path.join(A, 'update2.pak'))
    pak_tool.invalidate_cache(u2)
    assert pak_tool.cached_archive(u2)[0].hash_div <= 0xFFFFFFFF
    assert pak_tool.read_latest(tmp, 'a/base.igz')[0] == b'base'
    print('ok archive a 1 fichier')
    for n in (1, 2, 3):
        files = {f'ui/f{k}.igz': bytes([65 + k]) * (100 + k) for k in range(n)}
        cc._layer_write(tmp, 'update2.pak', files)
        assert set(cc.layer_files(tmp)) == set(files)
        for k, d in files.items():
            got, where = pak_tool.read_latest(tmp, k, original=False)
            assert got == d and os.path.basename(where) == 'update3.pak', k
        a = pak_tool.IgaArchive(cc.layer_path(tmp))
        assert a.hash_div <= 0xFFFFFFFF and len(a.entries) == n
        a.f.close()
        pak_tool.invalidate_cache(cc.layer_path(tmp))
        print(f'ok update3 a {n} fichier(s), diviseur {hex((1 << 32) // n)} borne')
    assert not os.path.exists(cc.layer_path(tmp) + '.tmp')
    cc._layer_write(tmp, 'update2.pak', {})
    assert not os.path.exists(cc.layer_path(tmp)) and not cc._layer_index(tmp)
    print('ok vide : update3 supprime')
finally:
    pak_tool.invalidate_cache()
    shutil.rmtree(tmp, ignore_errors=True)
print('TOUT EST BON')
