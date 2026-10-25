"""Test : ajout + remplacement de fichiers dans une COPIE d'archive, lecture, vue d'origine, desinstallation.

Usage : python test_pak_add.py <archive.pak> <dossier temporaire>
"""
import hashlib
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pak_tool  # noqa: E402


def check(cond, msg):
    print(('OK   ' if cond else 'ECHEC') + ' ' + msg)
    if not cond:
        raise SystemExit(1)


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 22), b''):
            h.update(b)
    return h.hexdigest()


def main(src, tmp):
    os.makedirs(tmp, exist_ok=True)
    dst = os.path.join(tmp, os.path.basename(src))
    shutil.copyfile(src, dst)
    h0 = sha(dst)
    a0 = pak_tool.IgaArchive(dst)
    orig = {e.logical_name: a0.read(e) for e in a0.entries}
    a0.f.close()
    victim = next(n for n in orig if n.endswith('_RaceSystem.igz'))
    new_names = ['models/Levels/Octane/Custom/MonModele.igz', 'models/Levels/Octane/Custom/Autre.igz']
    files = {victim: b'REMPLACE' * 100, new_names[0]: b'NOUVEAU1' * 300, new_names[1]: b'NOUVEAU2' * 7}
    pak_tool.install(dst, files)
    a = pak_tool.IgaArchive(dst)
    got = {e.logical_name: e for e in a.entries}
    check(len(a.entries) == len(orig) + 2, f'{len(a.entries)} fichiers apres ajout ({len(orig)} + 2)')
    same = sum(1 for n, d in orig.items() if n != victim and a.read(got[n]) == d)
    check(same == len(orig) - 1, f'{same}/{len(orig) - 1} fichiers d\'origine intacts')
    check(a.read(got[victim]) == files[victim], 'fichier remplace lu correctement')
    check(all(a.read(got[n]) == files[n] for n in new_names), 'nouveaux fichiers lus correctement')
    hashes = [e.name_hash for e in a.entries]
    check(hashes == sorted(hashes), 'table triee par hash')
    check(all(e.name_hash == pak_tool.fnv1a_lower(e.logical_name) for e in a.entries), 'hash = FNV-1a du nom logique')
    check(all(abs(i - h // a.hash_div) <= a.hash_slop for i, h in enumerate(hashes)),
          f'recherche : chaque indice a moins de {a.hash_slop} de hash // {a.hash_div:#x}')
    a.f.close()
    # vue d'origine
    view = pak_tool.original_archive(dst)
    check(view is not None and len(view[0].entries) == len(orig), 'vue d\'origine : TOC d\'avant le mod')
    check(view[0].read(view[1][victim.lower()]) == orig[victim], 'vue d\'origine : contenu d\'origine du fichier remplace')
    check(new_names[0].lower() not in view[1], 'vue d\'origine : le fichier ajoute n\'y est pas')
    view[0].f.close()
    pak_tool.uninstall(dst)
    check(sha(dst) == h0, 'desinstallation : SHA-256 identique a l\'original')
    os.remove(dst)
    print('tous les tests passent')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
