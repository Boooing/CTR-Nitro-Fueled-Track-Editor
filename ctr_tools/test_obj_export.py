"""Test : export OBJ de reference (collision + splines + decor en boites) -> relecture par l'import de l'editeur.

Les triangles de collision relus (metres, Y haut -> pouces, Z haut) doivent etre ceux du jeu, dans le meme ordre.
Usage : python test_obj_export.py <dossier archives>
"""
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'editor'))
import server  # noqa: E402
from collision_region import GroundEditor, apply  # noqa: E402
from model_build import parse_obj_groups  # noqa: E402
from obj_export import box_tris  # noqa: E402

T = 'T111_Crash_Cove'


def check(cond, msg):
    print(('OK   ' if cond else 'ECHEC') + ' ' + msg)
    if not cond:
        raise SystemExit(1)


def main(archives):
    server.ARCHIVES = archives
    with tempfile.TemporaryDirectory() as d:
        server.OUT_DIR = os.path.join(d, 'editor')          # fichiers d'origine (rien d'enregistre)
        art_core = [a for a in server.art_files(T) if a.endswith('_Art_Core.igz')]
        r = server.export_obj({'track': T, 'collision': True, 'splines': True, 'decor': 'boxes', 'files': art_core, 'extra': False})
        text = open(r['obj']).read()
        check(os.path.exists(r['mtl']) and text.count('\nl ') == r['lines'] > 0, f"{r['lines']} splines en aretes, .mtl ecrit")
        groups = {g['object']: g for g in parse_obj_groups(text, max_verts=None)}
        ge = GroundEditor(server.base_file(T, server.collision_file(T))[0])
        by_surface = {}
        for m in ge.meshes:
            for p in m['mesh'].prims:
                by_surface.setdefault(p.value, []).extend(tuple(apply(m['to_world'], v) for v in t) for t in p.triangles())
        worst, n, counts_ok = 0.0, 0, True
        for value, tris in by_surface.items():
            g = groups[f'Collision_surface_{value}']
            orig = [t for t in tris if len({tuple(round(c * 1e6 / 39.37) for c in v) for v in t}) == 3]
            back = [tuple(g['pos'][i] for i in t) for t in g['tris']]
            counts_ok &= len(back) == len(orig)
            for a, b in zip(orig, back):
                worst = max(worst, max(math.dist(p, q) for p, q in zip(a, b)))
            n += len(back)
        check(counts_ok, f'{len(by_surface)} surfaces : autant de triangles relus qu\'exportes')
        check(worst < 1e-3, f'{n} triangles de collision relus a l\'identique (ecart max {worst:.2e} po, meme ordre de sommets)')
        rz = server.export_obj({'track': T, 'collision': True, 'splines': False, 'decor': 'none', 'up': 'z'})
        gz = {g['object']: g for g in parse_obj_groups(open(rz['obj']).read(), up='z', max_verts=None)}
        check(all(math.dist(a, b) < 1e-3 for k in gz for a, b in zip(gz[k]['pos'], groups[k]['pos'])),
              'axe Z : relu avec l\'axe vertical Z, memes positions qu\'en Y')
        decor = [g for k, g in groups.items() if k.startswith('Decor_')]
        check(decor and all(len(g['tris']) == len(box_tris([0] * 3, [1] * 3)) for g in decor),
              f'{len(decor)} objets du decor en boites de 12 triangles')
        # decor complet d'Art_Core : autant de triangles que les modeles places (hors triangles degeneres)
        rf = server.export_obj({'track': T, 'collision': False, 'splines': False, 'decor': 'full', 'files': art_core, 'extra': False})
        nv = nf = maxi = 0
        with open(rf['obj']) as f:
            for line in f:
                if line.startswith('v '):
                    nv += 1
                elif line.startswith('f '):
                    nf += 1
                    maxi = max(maxi, *map(int, line.split()[1:]))
        check(nf == rf['triangles'] > 1_000_000 and maxi <= nv,
              f"decor complet Art_Core : {rf['objects']} objets, {nf} triangles, indices valides")
    print('tous les tests passent')


if __name__ == '__main__':
    main(sys.argv[1])
