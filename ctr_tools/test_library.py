"""Bibliotheque d'objets : catalogue, dependances d'un modele, fichiers a copier pour Crash Cove.

Usage : python test_library.py <dossier archives du jeu>
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import library  # noqa: E402
import pak_tool  # noqa: E402


def main(A):
    cat = library.catalog(A)
    assert len(cat) > 1500, len(cat)
    assert all(library.INCLUDE.match(m['model']) for m in cat)
    assert not any(library.EXCLUDE.search(m['model']) for m in cat)
    by_name = {m['name'].lower(): m for m in cat}
    # modele range sous sa piste : source = l'archive de cette piste
    sign = next(m for m in cat if m['model'].lower().startswith('models/levels/octane/t133_papus_pyramid/'))
    assert sign['pak'] == 't133_papus_pyramid.pak' and sign['track'] == 'Papus Pyramid', sign
    cactus = by_name['c3_cactus_01']
    assert library.file_name(cactus['model']) == 'models:\\Levels\\Crash3\\Desert\\C3_Cactus_01.igb'
    read = lambda lg: pak_tool.read_latest(A, lg, cactus['pak'])[0]
    deps = library.dependencies(read, cactus['model'])
    kinds = [t for t, _ in deps]
    assert kinds[-1] == 'model' and 'material_instances' in kinds and kinds.count('texture') >= 2, deps
    assert kinds == sorted(kinds, key=['texture', 'material_instances', 'model'].index)
    missing = [lg for _, lg in deps if not library.available(A, lg, 't111_crash_cove.pak')]
    assert cactus['model'] in missing                    # modele du desert : absent des archives de Crash Cove
    assert all(library.find_pak(A, lg, (cactus['pak'],)) for lg in missing)
    # palmier deja utilise par Crash Cove : rien a copier
    palm = by_name['c1_palmtree01']
    deps = library.dependencies(lambda lg: pak_tool.read_latest(A, lg, palm['pak'])[0], palm['model'])
    assert all(library.available(A, lg, 't111_crash_cove.pak') for _, lg in deps), deps
    assert library.group_of('models/Levels/Octane/T134_Dingo_Canyon/x.igz') == 'Dingo Canyon'
    assert library.group_of('models/Levels/Crash3/Desert/x.igz') == 'Crash3 / Desert'
    print(f'ok : {len(cat)} objets ; cactus : {len(missing)} fichier(s) a copier')


if __name__ == '__main__':
    main(sys.argv[1])
