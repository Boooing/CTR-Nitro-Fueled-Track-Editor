"""Construit l'application « CTR Track Editor » dans CTR/exe a la racine du projet :
CTR Track Editor.exe + _internal (Python, bibliotheques, editeur, three.js, schema IGZ), sans console.
Autre dossier : python ctr_tools/editor/build_exe.py <dossier de sortie>

    python ctr_tools/editor/build_exe.py

Outils dans un environnement a part (.build_venv a la racine du projet), cree au besoin :
    python -m venv .build_venv
    set PIP_USE_FEATURE=truststore        (certificats de Windows : un antivirus qui filtre le HTTPS bloquait pip)
    .build_venv\\Scripts\\python -m pip install pyinstaller pywebview numpy pillow
Fichiers embarques : index.html, i18n.js, vendor/three (editeur hors ligne), schema/ctr_meta.json (format IGZ).
Icone : crash-team-racing-nitro-fueled_j4g2.jpg (racine du projet) s'il existe, fond blanc rendu transparent ;
sinon drapeau a damier dessine.
Sauvegardes : out/editor a cote de l'exe, ou dans un dossier parent qui en a deja (voir app.py).
Le contenu du dossier de sortie autre que l'exe et _internal (ctr_editor_config.json...) est conserve.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
ROOT = os.path.dirname(TOOLS)
VENV_PY = os.path.join(ROOT, '.build_venv', 'Scripts', 'python.exe')
BUILD = os.path.join(ROOT, '.build')
NAME = 'CTR Track Editor'
APP_DIR = os.path.join(ROOT, 'CTR', 'exe')
ICON_SRC = os.path.join(ROOT, 'crash-team-racing-nitro-fueled_j4g2.jpg')


def make_icon(path):
    """Icone depuis le logo du jeu : fond blanc transparent (remplissage depuis les bords), cadre carre serre.
    Sans l'image (depot GitHub : pas d'image du jeu) : drapeau a damier sur une pastille orange."""
    from PIL import Image, ImageDraw
    if not os.path.exists(ICON_SRC):
        s = 256
        img = Image.new('RGBA', (s, s), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((8, 8, s - 8, s - 8), radius=56, fill=(232, 89, 12, 255))
        d.rectangle((70, 52, 82, 210), fill=(255, 255, 255, 255))
        for i in range(6):
            for j in range(4):
                col = (255, 255, 255, 255) if (i + j) % 2 == 0 else (27, 31, 42, 255)
                d.rectangle((82 + i * 22, 52 + j * 22, 104 + i * 22, 74 + j * 22), fill=col)
        img.save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        return
    img = Image.open(ICON_SRC).convert('RGBA')
    w, h = img.size
    for xy in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1), (w // 2, 0), (w // 2, h - 1), (0, h // 2), (w - 1, h // 2)]:
        if img.getpixel(xy)[3]:
            ImageDraw.floodfill(img, xy, (255, 255, 255, 0), thresh=40)
    box = img.getbbox()
    side = max(box[2] - box[0], box[3] - box[1])
    sq = Image.new('RGBA', (side, side), (0, 0, 0, 0))
    sq.paste(img.crop(box), ((side - (box[2] - box[0])) // 2, (side - (box[3] - box[1])) // 2))
    sq.resize((256, 256), Image.LANCZOS).save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                                                           (128, 128), (256, 256)])


def main():
    global APP_DIR
    if len(sys.argv) > 1:
        APP_DIR = os.path.abspath(sys.argv[1])
    py = VENV_PY if os.path.exists(VENV_PY) else sys.executable
    os.makedirs(BUILD, exist_ok=True)
    icon = os.path.join(BUILD, 'ctr_editor.ico')
    make_icon(icon)
    dist = os.path.join(BUILD, 'dist')
    sep = os.pathsep
    cmd = [py, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--windowed', '--name', NAME,
           '--icon', icon, '--distpath', dist, '--workpath', os.path.join(BUILD, 'work'), '--specpath', BUILD,
           '--paths', TOOLS, '--paths', HERE,
           '--add-data', f'{os.path.join(TOOLS, "schema")}{sep}schema',
           '--add-data', f'{os.path.join(HERE, "index.html")}{sep}.',
           '--add-data', f'{os.path.join(HERE, "i18n.js")}{sep}.',
           '--add-data', f'{os.path.join(HERE, "vendor")}{sep}vendor',
           '--hidden-import', 'server', '--collect-submodules', 'webview',
           os.path.join(HERE, 'app.py')]
    print(' '.join(f'"{c}"' if ' ' in c else c for c in cmd), flush=True)
    subprocess.check_call(cmd, cwd=ROOT)
    built = os.path.join(dist, NAME)
    os.makedirs(APP_DIR, exist_ok=True)
    internal = os.path.join(APP_DIR, '_internal')
    if os.path.isdir(internal):                        # ancienne version des bibliotheques (genere par ce script)
        shutil.rmtree(internal)
    shutil.copytree(os.path.join(built, '_internal'), internal)
    shutil.copy2(os.path.join(built, NAME + '.exe'), os.path.join(APP_DIR, NAME + '.exe'))
    size = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(APP_DIR) for f in fs)
    print(f'\n{os.path.join(APP_DIR, NAME + ".exe")} (dossier : {size / 2 ** 20:.0f} Mo)')


if __name__ == '__main__':
    main()
