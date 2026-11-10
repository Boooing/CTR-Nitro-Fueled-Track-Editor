"""Tous les objets de la Creation : chaque fichier dont ils dependent doit etre trouve (sinon la generation s'arrete sur
« fichier introuvable dans les archives »). Rien n'est ecrit. python test_creator_kits.py <dossier archives>"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'editor'))
import pak_tool  # noqa: E402
import server as S  # noqa: E402
import track_creator as tc  # noqa: E402

A = sys.argv[1] if len(sys.argv) > 1 else os.environ.get('CTR_TEST_ARCHIVES') or sys.exit('usage : test_creator_kits.py <dossier archives>')
S.ARCHIVES = A
T = next(t for t in S.list_tracks())
pairs = {(m, p['pak']) for k in tc.KITS.values() for p in (k.get('props') or {}).values() for m in p['models']}
missing = []
for model, pak in sorted(pairs):
    try:
        S.library_files(T, model, pak)
    except KeyError as e:
        missing.append((model, str(e)))
assert not missing, missing[:10]
pak_tool.invalidate_cache()
print(f'ok {len(pairs)} objets : toutes les dependances trouvees')
print('TOUT EST BON')
