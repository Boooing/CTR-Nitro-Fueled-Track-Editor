"""Collision d'une piste longue : plus de 65 535 sommets communs a plusieurs sections (limite du format pour les sommets
partages). Encode -> ecrit dans la collision de Crash Cove -> relu : tout est garde, arbres valides, ecart mesure. La route
(maille fine) doit garder ses sommets partages. Rien n'est ecrit dans le jeu.
python test_cms_long.py <dossier archives> [maillage.pkl]"""
import collections
import math
import os
import pickle
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pak_tool  # noqa: E402
from cms_codec import Mesh, Prim, encode_mesh, read_mesh, write_mesh  # noqa: E402
from havok import Packfile  # noqa: E402
from havok_writer import PackfileWriter  # noqa: E402
from test_cms_codec import HKX, TRACK, ground_shape, tree_check  # noqa: E402

ROAD, GROUND = 4, 38


def synthetic():
    """Sol de 600 x 600 cases de 8 m, doux, et une route de 2 km en bandes de 4 m juste au-dessus."""
    h = lambda x, y: 30 * math.sin(x / 300) * math.cos(y / 250)
    prims, c = [], 8.0
    for j in range(600):
        for i in range(600):
            q = [(i * c, j * c), ((i + 1) * c, j * c), ((i + 1) * c, (j + 1) * c), (i * c, (j + 1) * c)]
            p = [(x, y, h(x, y)) for x, y in q]
            prims += [Prim([p[0], p[1], p[2]], GROUND), Prim([p[0], p[2], p[3]], GROUND)]
    for k in range(500):
        for s in range(8):
            q = [(100 + k * 4.0, 2000 + s * 4.0), (104 + k * 4.0, 2000 + s * 4.0), (104 + k * 4.0, 2004 + s * 4.0), (100 + k * 4.0, 2004 + s * 4.0)]
            p = [(x, y, h(x, y) + 0.5) for x, y in q]
            prims += [Prim([p[0], p[1], p[2]], ROAD), Prim([p[0], p[2], p[3]], ROAD)]
    return Mesh(prims=prims)


def main(archives, pkl=None):
    mesh = pickle.load(open(pkl, 'rb')) if pkl else synthetic()
    t = time.time()
    enc = encode_mesh(mesh)
    print(f"{len(mesh.prims)} primitives -> {len(enc['sections'])} sections, {len(enc['shared']) // 8} partages, "
          f"{len(enc['packed']) // 4} compresses, cle max {enc['max_key']} ({enc['bits_per_key']} bits), {time.time() - t:.0f} s")
    assert len(enc['shared']) // 8 == 0xFFFF, 'la limite doit etre atteinte, sinon ce test ne prouve rien'
    assert enc['packed'], 'des sommets doivent etre compresses'
    hk = pak_tool.read_latest(archives, HKX, TRACK.lower() + '.pak')[0]
    w = PackfileWriter(hk)
    write_mesh(w, ground_shape(Packfile(hk)), enc)
    out = w.to_bytes()
    pf = Packfile(out)
    back = read_mesh(pf, ground_shape(pf))
    assert len(back.prims) == len(mesh.prims), (len(back.prims), len(mesh.prims))
    print(f'relu : {len(back.prims)} primitives, fichier {len(out) // 1024} Ko')
    (ok, bad), leaf_ok, nsec = tree_check(pf, ground_shape(pf))
    assert bad == 0 and ok == nsec and leaf_ok == nsec, (ok, bad, leaf_ok, nsec)
    print(f'arbre du haut : {ok}/{nsec} sections contenues, feuilles {leaf_ok}/{nsec}')
    vals = collections.Counter(p.value for p in mesh.prims)
    assert collections.Counter(p.value for p in back.prims) == vals, 'surfaces modifiees'
    # ecart : chaque sommet relu contre le sommet d'origine le plus proche ; une fissure vaut au pire 2 x cet ecart
    grid = {}
    for p in mesh.prims:
        for v in p.verts:
            grid.setdefault((int(v[0] // 2), int(v[1] // 2)), set()).add(v)
    worst = collections.defaultdict(float)
    errs = collections.defaultdict(list)
    for p in back.prims:
        for v in p.verts:
            cx, cy = int(v[0] // 2), int(v[1] // 2)
            d = min(math.dist(v, o) for a in (-1, 0, 1) for b in (-1, 0, 1) for o in grid.get((cx + a, cy + b), ()))
            worst[p.value] = max(worst[p.value], d)
            errs[p.value].append(d)
    for s in sorted(worst, key=lambda s: -vals[s]):
        e = sorted(errs[s])
        print(f'surface {s} : {vals[s]} primitives, ecart median {e[len(e) // 2] * 100:.2f} cm, 99 % {e[int(len(e) * .99)] * 100:.2f} cm, max {worst[s] * 100:.2f} cm')
    assert max(worst.values()) < 0.25, f'ecart trop grand : {max(worst.values())} m'
    if not pkl:
        assert worst[ROAD] < 0.02, f'la route doit rester precise : {worst[ROAD] * 100:.2f} cm'
        # sous la limite : encodage inchange, tout en sommets partages
        small = encode_mesh(Mesh(prims=mesh.prims[:2000]))
        assert not small['packed'], 'petit maillage : aucun sommet compresse attendu'
    print('TOUT EST BON')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else os.environ.get('CTR_TEST_ARCHIVES') or sys.exit('usage : test_cms_long.py <dossier archives> [maillage.pkl]'),
         sys.argv[2] if len(sys.argv) > 2 else None)
