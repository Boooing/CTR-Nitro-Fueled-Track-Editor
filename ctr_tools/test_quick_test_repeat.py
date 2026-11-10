"""« Tester en jeu » : essais repetes sans remise a l'etat normal, sur un update2 sans sauvegarde de TOC. Archives
temporaires ; les fichiers du jeu ne servent que de modele et de contenu. python test_quick_test_repeat.py <dossier archives>"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pak_tool  # noqa: E402
import quick_test as q  # noqa: E402
import track_clone  # noqa: E402

A = sys.argv[1] if len(sys.argv) > 1 else os.environ.get('CTR_TEST_ARCHIVES') or sys.exit('usage : test_quick_test_repeat.py <dossier archives>')
real = pak_tool.read_latest(A, q.MANAGER)[0]
a, idx, lock = pak_tool.cached_archive(os.path.join(A, 'update.pak'))
with lock:
    old = a.read(idx[q.MANAGER.lower()])
assert q.PATCH_MARK not in real and q.PATCH_MARK not in old
tmp = tempfile.mkdtemp(prefix='qt_')
make = lambda n, d: track_clone.write_archive(os.path.join(tmp, n), [(q.MANAGER, pak_tool.FULL_PREFIX + q.MANAGER, 0, ('data', d)), ('a/b.igz', pak_tool.FULL_PREFIX + 'a/b.igz', 1, ('data', b'x'))], os.path.join(A, n))
cur = lambda: (pak_tool.invalidate_cache(), pak_tool.read_latest(tmp, q.MANAGER, original=False)[0])[1]
try:
    make('update2.pak', real)
    make('update.pak', old)
    assert not os.path.exists(os.path.join(tmp, 'update2.pak.ctrmod.toc'))
    # 1) sequence normale, identique a l'origine a la fin
    q.install(tmp, 'T901_Custom_Map')
    assert q.PATCH_MARK in cur() and q.map_path('T901_Custom_Map').encode() in cur()
    q.uninstall(tmp)
    assert cur() == real and not os.path.exists(q._saved_manager(tmp))
    print('ok essai puis retour : script d\'origine a l\'identique')
    # 2) essai jamais remis (l'erreur signalee) puis autre piste : plus d'erreur, seule la nouvelle piste
    q.install(tmp, 'T901_Custom_Map')
    q.install(tmp, 'T902_Custom_Map')
    assert q.map_path('T902_Custom_Map').encode() in cur() and q.map_path('T901_Custom_Map').encode() not in cur()
    q.uninstall(tmp)
    assert cur() == real
    print('ok deux essais sans retour : piste a jour, script d\'origine a la fin')
    # 3) PC deja bloque par l'ancienne version : script patche, aucune copie -> secours d'update.pak
    pak_tool.invalidate_cache()
    pak_tool._append_replace(os.path.join(tmp, 'update2.pak'), {q.MANAGER: q.patch_manager(real, 'T901_Custom_Map')})
    pak_tool.invalidate_cache()
    q.install(tmp, 'T902_Custom_Map')
    assert q.map_path('T902_Custom_Map').encode() in cur()
    q.uninstall(tmp)
    assert q.PATCH_MARK not in cur() and cur() == old
    print('ok PC deja bloque : essai possible, retour au jeu normal')
finally:
    pak_tool.invalidate_cache()
    shutil.rmtree(tmp, ignore_errors=True)
print('TOUT EST BON')
