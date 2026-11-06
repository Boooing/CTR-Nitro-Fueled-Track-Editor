"""Mini-carte : taille comparee a l'ancienne zone et aux images du jeu, sans rien ecrire (minimap.build en memoire).
La correspondance monde -> image doit suivre les coins : les pastilles restent sur le trace.
python test_minimap_size.py [dossier archives] -> planches PNG dans [dossier de sortie]."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, 'editor')]
import numpy as np  # noqa: E402
import minimap  # noqa: E402
import pak_tool  # noqa: E402
import server  # noqa: E402

server.ARCHIVES = sys.argv[1] if len(sys.argv) > 1 else os.environ.get('CTR_TEST_ARCHIVES') or sys.exit('usage : test_minimap_size.py <dossier archives> [dossier de sortie]')
OUT = sys.argv[2] if len(sys.argv) > 2 else None
OLD = (476, 64, 794, 734)
fails = []


def check(cond, text):
    print(('ok   ' if cond else 'ECHEC') + ' ' + text)
    if not cond:
        fails.append(text)


def bbox(a):
    ys, xs = np.nonzero(a[:, :, 3] > 128)
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def build(track, content):
    new = minimap.CONTENT
    minimap.CONTENT = content
    try:
        path, tr = server.race_path_points(track)
        fin = next((t for t in tr['transitions'] if t['increment_lap']), None)
        src = {'objects': server.imported_road_objects(track)}
        import json
        rp = server.road_source_path(track)
        if os.path.exists(rp):
            src = json.load(open(rp))
        try:
            tris = server.road_tris(track, src) if src.get('objects') else None
        except ValueError:                            # comme generate_minimap : objet de route supprime -> trace
            tris = None
        meta = server.minimap_meta(track)
        tl = server.minimap_texture_logical(track)
        rd = lambda lg: pak_tool.read_latest(server.ARCHIVES, lg, server.track_pak(track))[0]
        return minimap.build(rd(minimap.minimap_file(track)), rd(tl), path, tris, (fin['position'], fin['yaw'] or 0.0) if fin else None,
                             1000.0, meta.get('nudge', minimap.NUDGE_DEFAULT), server.minimap_orientation(track)[0],
                             (bool(meta.get('mirror_h')), bool(meta.get('mirror_v'))))[1:], path, tris
    finally:
        minimap.CONTENT = new


def corners_follow():
    """Quelle que soit la zone : un point du monde tombe au meme pixel par les coins (pastilles) et par le dessin."""
    pts = np.array([[1000.0, -3000.0], [52000.0, 41000.0], [20000.0, 9000.0]])
    k, cw, cp = minimap.layout(pts)
    tl = minimap.transform_corner(minimap.REFERENCE['top_left'], k, cw, cp)
    br = minimap.transform_corner(minimap.REFERENCE['bottom_right'], k, cw, cp)
    q0, q1 = minimap.REFERENCE['top_left'], minimap.REFERENCE['bottom_right']
    for p in pts:
        tx = (p[0] - tl[0]) / (br[0] - tl[0])
        ty = (p[1] - tl[1]) / (br[1] - tl[1])
        crash = (q0[0] + tx * (q1[0] - q0[0]), q0[1] + ty * (q1[1] - q0[1]))
        u, v = minimap.A * crash[0] + minimap.BU, -minimap.A * crash[1] + minimap.BV
        d = np.subtract((u, v), minimap.to_px(p, k, cw, cp))
        check(np.abs(d).max() < 1e-3, f'pastille sur le dessin, ecart {np.abs(d).max():.5f} px')


def main():
    corners_follow()
    from PIL import Image
    for track in ('T111_Crash_Cove', 'T112_Roos_Tubes', 'T121_Slide_Coliseum', 'T901_Custom_Map'):
        (_, old, _), _, _ = build(track, OLD)
        (_, new, _), path, tris = build(track, minimap.CONTENT)
        bo, bn = bbox(old), bbox(new)
        so, sn = max(bo[2] - bo[0], bo[3] - bo[1]), max(bn[2] - bn[0], bn[3] - bn[1])
        print(f'{track} : ancien {bo} -> nouveau {bn}, x{sn / so:.2f}')
        check(sn > so * 1.3, f'{track} : plus grand')
        check(bn[0] >= 0 and bn[1] >= 0 and bn[2] <= 799 and bn[3] <= 799, f'{track} : tient dans l\'image')
        check(new[:, :, 3].sum() > old[:, :, 3].sum(), f'{track} : plus de surface dessinee')
        if OUT:
            os.makedirs(OUT, exist_ok=True)
            sheet = Image.new('RGBA', (1620, 800), (40, 60, 90, 255))
            sheet.paste(Image.fromarray(old), (0, 0), Image.fromarray(old))
            sheet.paste(Image.fromarray(new), (820, 0), Image.fromarray(new))
            sheet.resize((810, 400)).convert('RGB').save(os.path.join(OUT, f'{track}.png'))
    print('\n' + ('TOUT EST BON' if not fails else f'{len(fails)} ECHEC(S) : ' + ' | '.join(fails)))
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
