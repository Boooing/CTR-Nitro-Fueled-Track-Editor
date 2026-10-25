"""Test : « nouvelle map » (ancien sol et ancien decor retires, modeles importes gardes, retour a l'origine).

Usage : python test_newmap.py <dossier archives>
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'editor'))
import server  # noqa: E402
from collision_region import GroundEditor  # noqa: E402
from decor import DecorFile  # noqa: E402
from test_model_build import RAMP_OBJ  # noqa: E402

T = 'T111_Crash_Cove'


def check(cond, msg):
    print(('OK   ' if cond else 'ECHEC') + ' ' + msg)
    if not cond:
        raise SystemExit(1)


def _png():
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (64, 64), (120, 120, 120)).save(buf, 'PNG')
    return buf.getvalue()


def main(archives):
    server.ARCHIVES = archives
    with tempfile.TemporaryDirectory() as d:
        server.OUT_DIR = d
        server.import_model({'track': T, 'name': 'Route', 'obj': RAMP_OBJ, 'pos': [0, 0, 0], 'surface': 38})
        arts = server.art_files(T)
        counts0 = {a: len(DecorFile(server.base_file(T, a)[0]).objects()) for a in arts}
        owners = server.collision_owners(T)
        check(len(owners) == 77 and server.ground_owner(T) == (arts[0], 'RaceTrack_Collision'),
              f'77 instances de collision -> entites ; sol principal = {server.ground_owner(T)[1]}')
        r = server.apply_newmap({'track': T, 'strip_ground': True, 'strip_art': arts})
        left = {a: [o['name'] for o in DecorFile(open(server.saved_path(a), 'rb').read()).objects()] for a in arts}
        names = sorted(n for v in left.values() for n in v)
        check(len(names) == 2 and 'RaceTrack_Collision' in names,
              f'decor : {sum(counts0.values())} -> {names} (la route importee + l\'entite qui active la collision du sol)')
        ge = GroundEditor(open(server.saved_path(server.collision_file(T)), 'rb').read())
        prims = sorted(((len(m['mesh'].prims), m['instance']) for m in ge.meshes), reverse=True)
        check(prims[0][0] == 8 and all(n == 1 for n, _ in prims[1:]),
              f'collision : la rampe seule (8 triangles) ; {len(prims) - 1} maillages d\'origine vides')
        check(any('nouvelle map' in l for l in r['report']) and r['remaining'], f"{len(r['remaining'])} elements restants listes")
        # triangles geants (modele tres agrandi) : decoupes pour la collision (sinon on passe au travers en jeu)
        big = ((0.0, 0.0, 0.0), (120000.0, 0.0, 0.0), (0.0, 90000.0, 0.0))
        parts = server.subdivide_tri(big)
        edge = max(max(abs(q[i][k] - q[i - 1][k]) for k in range(2)) for q in parts for i in range(3))
        n = min(server.SUBDIV_MAX, -(-150000 // int(server.MAX_COLLISION_EDGE)))   # hypotenuse 3,8 km, plafonne
        check(len(parts) == n * n, f'triangle de 3,8 km -> {len(parts)} triangles (decoupage plafonne a {server.SUBDIV_MAX} x {server.SUBDIV_MAX})')
        small = server.subdivide_tri(((0.0, 0.0, 0.0), (12000.0, 0.0, 0.0), (0.0, 9000.0, 0.0)))
        edge = max(max(abs(q[i][k] - q[i - 1][k]) for k in range(2)) for q in small for i in range(3))
        check(edge <= server.MAX_COLLISION_EDGE, f'triangle de 380 m -> {len(small)} triangles de moins de 100 m')
        # allegement : mur detaille (grille de 40 x 10 petits carres) simplifie, sol plat jamais simplifie
        import numpy as np
        g = np.array([[[x, 0, z], [x + 10, 0, z], [x, 0, z + 10]] for x in range(0, 400, 10) for z in range(0, 100, 10)], float)
        wall = np.concatenate([g, g + [0, 0.3, 0]])
        light = server.simplify_tris(wall, 40)
        check(len(light) < len(wall) / 4 and not server.is_flat('Mur', wall) and server.is_flat('Herbe', g[:, :, [0, 2, 1]]),
              f'collision allegee : mur de {len(wall)} triangles -> {len(light)} ; un sol plat est reconnu (pas simplifie)')
        tex = server.create_texture(T, 'Gris', _png(), size=512)
        from texture_build import texture_info
        info = texture_info(open(server.custom_file_path(server.custom_textures(T)[tex['name']]['files']['texture'][0]), 'rb').read())
        check((info['width'], info['levels']) == (512, 8), f"texture en 512 : {info['width']} x {info['height']}, {info['levels']} niveaux")
        # restes hors decor (bateaux, effets, lumieres) : entites descendues sous la carte, puis remises
        from igz import IgzFile
        keys = [g[0] for g in server.MOVE_AWAY_GROUPS]
        server.apply_newmap({'track': T, 'strip_ground': True, 'strip_art': arts, 'move_away': keys})
        moved = server.moved_away_logicals(T)
        z = IgzFile(open(server.saved_path(moved[0]), 'rb').read())
        zs = [z.vec3(o + 0x20)[2] for _, o in z.root_objects() if (z.objects.get(o) or '').endswith('Entity')]
        # Crash Cove : 2 design + 4 vfx + 3 lighting + 3 audio + 2 occultation (design_include_switch vide : ignore)
        check(len(moved) == 14 and max(zs) < -90000, f'{len(moved)} fichiers (bateaux, effets, lumieres, sons, occultation) descendus sous la carte')
        occ = [m for m in moved if 'occlusion' in m.lower()]
        zo = IgzFile(open(server.saved_path(occ[0]), 'rb').read())
        check(len(occ) == 2 and all(zo.vec3(o + 0x68)[2] < -50000 for _, o in zo.root_objects() if zo.objects.get(o) == 'COcclusionBox'),
              'zones d\'occultation descendues')
        vfx = next(m for m in moved if m.lower().endswith('_vfx.igz'))
        zv = IgzFile(open(server.saved_path(vfx), 'rb').read())
        pos = {n: zv.vec3(o + 0x20)[2] for n, o in zv.root_objects() if (zv.objects.get(o) or '').endswith('Entity')}
        check(pos['Crate_Spawner'] > -90000 and pos['VFX_WaterSplash_Shark'] < -90000, 'generateur de caisses laisse en place')
        check(all(any(os.path.basename(m) == n for n, _ in server._tracked_files(T)) for m in moved), 'suivis par l\'historique')
        r2 = server.apply_newmap({'track': T, 'strip_ground': False, 'strip_art': []})
        check(not server.moved_away_logicals(T), 'decoches : remis a leur place')
        back = {a: len(DecorFile(open(server.saved_path(a), 'rb').read()).objects()) for a in arts}
        check(all(back[a] == counts0[a] for a in arts), 'retour : tous les objets d\'origine reviennent')
        ge2 = GroundEditor(open(server.saved_path(server.collision_file(T)), 'rb').read())
        check(sum(len(m['mesh'].prims) for m in ge2.meshes) > 9000, 'retour : sol d\'origine + rampe dans la collision')
    print('tous les tests passent')


if __name__ == '__main__':
    main(sys.argv[1])
