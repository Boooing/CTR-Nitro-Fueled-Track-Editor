"""Verifie que IgzFile(f).to_bytes() reproduit chaque .igz a l'octet pres.

Usage : python test_roundtrip.py <dossier>
"""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from igz import IgzFile  # noqa: E402


def first_diff(a, b):
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return min(len(a), len(b))


def main(root):
    stats, fails = collections.Counter(), []
    for dp, _, fn in os.walk(root):
        for f in fn:
            if not f.endswith('.igz'):
                continue
            p = os.path.join(dp, f)
            raw = open(p, 'rb').read()
            try:
                out = IgzFile(raw).to_bytes()
            except Exception as e:  # noqa: BLE001
                stats['erreur'] += 1
                fails.append((p, repr(e)))
                continue
            if out == raw:
                stats['identique'] += 1
            else:
                stats['different'] += 1
                fails.append((p, f'diff @ {first_diff(raw, out):#x}, taille {len(raw)} -> {len(out)}'))
    print(dict(stats))
    for p, why in fails[:15]:
        print(' ', os.path.relpath(p, root), why)
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
