"""Test : nom et images de la piste dans les menus (menu_assets.py + server.apply_menu).

Usage : python test_menu.py <dossier archives>
"""
import base64
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'editor'))
import menu_assets  # noqa: E402
import preview  # noqa: E402
import texture_build  # noqa: E402

T = 'T111_Crash_Cove'


def check(cond, msg):
    print(('OK   ' if cond else 'ECHEC') + ' ' + msg)
    if not cond:
        raise SystemExit(1)


def main(archives):
    import server
    from PIL import Image
    server.ARCHIVES = archives
    with tempfile.TemporaryDirectory() as d:
        server.OUT_DIR = d
        info = server.menu_info(T)
        check(info['names']['fr']['original'] == 'Crique Crash' and info['names']['pt']['original'] == 'Baía do Crash',
              f"noms d'origine : {', '.join(n['original'] for n in info['names'].values())} (accents en UTF-8)")
        check(set(info['images']) == set(menu_assets.IMAGES), f"{len(info['images'])} images de menu trouvees")
        buf = io.BytesIO()
        Image.new('RGB', (800, 600), (200, 30, 30)).save(buf, 'PNG')
        url = 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()
        server.apply_menu({'track': T, 'names': {'fr': 'Circuit Mario 3 – Château', 'en': 'Mario Circuit 3'},
                           'images': {'background': url, 'icon': url}})
        info2 = server.menu_info(T)
        check(info2['names']['fr']['name'] == 'Circuit Mario 3 – Château' and info2['names']['mx']['name'] == 'Cala Crash',
              f"nom relu : {info2['names']['fr']['name']} (les autres langues gardent le leur)")
        saved = dict(server.menu_saved(T))
        lng = next(p for l, p in saved.items() if l.endswith('_fr.lng'))
        check('Château'.encode('utf-8') in open(lng, 'rb').read(), 'ecrit en UTF-8 comme le jeu')
        bg = next(p for l, p in saved.items() if 'raceselect_bg_' in l)
        data = open(bg, 'rb').read()
        ti = texture_build.texture_info(data)
        rgba, _ = preview.decode_texture(data, 2048)
        check((ti['width'], ti['height'], ti['levels']) == (1288, 1080, 1) and abs(int(rgba[540, 644, 0]) - 200) < 12,
              f"fond : {ti['width']} x {ti['height']}, rempli par l'image")
        # sens : textures d'interface stockees de bas en haut (verifie en jeu) ; haut rouge / bas bleu
        im = Image.new('RGB', (1288, 1080), (220, 20, 20))
        im.paste((20, 20, 220), (0, 540, 1288, 1080))
        b2 = io.BytesIO()
        im.save(b2, 'PNG')
        server.apply_menu({'track': T, 'images': {'background': 'data:image/png;base64,' + base64.b64encode(b2.getvalue()).decode()}})
        raw, _ = preview.decode_texture(open(bg, 'rb').read(), 2048)
        check(raw[10, 644, 2] > 150 and raw[1070, 644, 0] > 150,
              'stockee de bas en haut (1re ligne du fichier = bas de l\'image, comme le fond d\'origine)')
        check(len(server.menu_archives(T, next(l for l in saved if 'raceselect_bg_' in l))) == 2,
              'fond installe dans juicedomain_startscreen et juicedomain_onlinemenus')
        server.apply_menu({'track': T, 'names': {'fr': None}, 'images': {'icon': None}})
        info3 = server.menu_info(T)
        check(info3['names']['fr']['name'] == 'Crique Crash' and not info3['images']['icon']['custom'], 'retour a l\'origine')
    print('tous les tests passent')


if __name__ == '__main__':
    main(sys.argv[1])
