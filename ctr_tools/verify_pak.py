"""Compare deux archives .pak fichier par fichier (contenu decompresse).

Usage : python verify_pak.py <origine.pak> <modifie.pak>
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pak_tool import IgaArchive  # noqa: E402


def main(a_path, b_path):
    a, b = IgaArchive(a_path), IgaArchive(b_path)
    assert len(a.entries) == len(b.entries), 'nombre de fichiers different'
    changed = 0
    for ea, eb in zip(a.entries, b.entries):
        assert ea.logical_name == eb.logical_name and ea.name_hash == eb.name_hash
        da, db = a.read(ea), b.read(eb)
        if da != db:
            changed += 1
            diffs = [i for i in range(min(len(da), len(db))) if da[i] != db[i]]
            print(f'modifie : {eb.logical_name} ({len(da)} -> {len(db)} octets, type {ea.ctype} -> {eb.ctype}, '
                  f'{len(diffs)} octet(s) differents aux offsets {[hex(i) for i in diffs[:8]]})')
    print(f'{len(a.entries)} fichiers compares, {changed} modifie(s), {len(a.entries) - changed} identiques')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
