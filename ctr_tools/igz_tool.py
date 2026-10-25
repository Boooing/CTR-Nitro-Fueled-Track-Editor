"""Outil en ligne de commande pour les fichiers .igz.

Usage :
    python igz_tool.py info  <fichier.igz>
    python igz_tool.py dump  <fichier.igz> [sortie.json]
    python igz_tool.py roots <fichier.igz>
"""
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from igz import IgzFile  # noqa: E402


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 1
    cmd, path = argv[1], argv[2]
    igz = IgzFile(path)
    if cmd == 'info':
        print(f'IGZ v{igz.version}, {len(igz.sections) - 1} section(s) de donnees, {len(igz.objects)} objets')
        print('fixups :', ', '.join(f'{k}({v[0]})' for k, v in igz.fixups.items()))
        for t, c in collections.Counter(igz.objects.values()).most_common():
            print(f'  {c:5}  {t}')
        if igz.ext_names:
            print(f'{len(igz.ext_names)} references externes, ex. :', [f'{ns}::{n}' for n, ns in igz.ext_names[:5]])
    elif cmd == 'roots':
        for name, off in igz.root_objects():
            print(f'{off:#08x}  {igz.objects.get(off, "?"):45}  {name}')
    elif cmd == 'dump':
        out = argv[3] if len(argv) > 3 else path + '.json'
        with open(out, 'w') as f:
            json.dump(igz.dump(), f, indent=1)
        print(f'ecrit {out}')
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
