"""Construit CTR Track Installer (PyInstaller, dossier « onedir », sans console) pour le systeme en cours :
    Windows : CTR Track Installer/Windows/CTR Track Installer.exe + _internal
    Linux   : CTR Track Installer/Linux/CTR Track Installer + _internal
(PyInstaller ne compile pas pour un autre systeme : lancer ce script sous Linux pour la version Linux.)

    python "CTR Track Installer/build.py"

Outils : Windows : environnement .build_venv a la racine du projet s'il existe (celui de l'editeur), sinon le Python
qui lance le script ; Linux : le Python qui lance le script. Paquets : pyinstaller numpy pillow (requirements.txt) ;
Linux : Tk en plus (Debian / Ubuntu : sudo apt install python3-tk ; Fedora : sudo dnf install python3-tkinter).
Embarques : moteur (ctr_tools : server.py, mappack.py, game_restore.py... ), schema IGZ (ctr_tools/schema),
traductions (ctr_tools/editor/i18n.js). Le dossier data/ (reglages, dossier de travail) a cote de l'application est
conserve d'une construction a l'autre.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# moteur : ctr_tools dans ce dossier (depot de l'installateur seul), sinon a cote (projet complet avec l'editeur)
ROOT = HERE if os.path.isdir(os.path.join(HERE, 'ctr_tools')) else os.path.dirname(HERE)
TOOLS = os.path.join(ROOT, 'ctr_tools')
EDITOR = os.path.join(TOOLS, 'editor')
NAME = 'CTR Track Installer'
WINDOWS = os.name == 'nt'
OUT = os.path.join(HERE, 'Windows' if WINDOWS else 'Linux')
BUILD = os.path.join(HERE, '.build', 'windows' if WINDOWS else 'linux')
VENV_PY = os.path.join(ROOT, '.build_venv', 'Scripts', 'python.exe')


def make_icon(path):
    """Icone de l'editeur (logo du jeu dans le projet complet) ; seul : drapeau a damier sur une pastille orange."""
    try:
        sys.path.insert(0, EDITOR)
        import build_exe
        build_exe.make_icon(path)
        return
    except ImportError:
        pass
    from PIL import Image, ImageDraw
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


def main():
    py = VENV_PY if WINDOWS and os.path.exists(VENV_PY) else sys.executable
    os.makedirs(BUILD, exist_ok=True)
    sep = os.pathsep
    cmd = [py, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--windowed', '--name', NAME,
           '--distpath', os.path.join(BUILD, 'dist'), '--workpath', os.path.join(BUILD, 'work'), '--specpath', BUILD,
           '--paths', TOOLS, '--paths', EDITOR,
           '--add-data', f'{os.path.join(TOOLS, "schema")}{sep}schema',
           '--add-data', f'{os.path.join(EDITOR, "i18n.js")}{sep}.',
           '--hidden-import', 'server', '--hidden-import', 'mappack', '--hidden-import', 'game_restore',
           '--hidden-import', 'PIL.ImageTk']
    if WINDOWS:
        icon = os.path.join(BUILD, 'ctr_installer.ico')
        make_icon(icon)
        cmd += ['--icon', icon]
    cmd.append(os.path.join(HERE, 'src', 'ctr_track_installer.py'))
    print(' '.join(f'"{c}"' if ' ' in c else c for c in cmd), flush=True)
    subprocess.check_call(cmd, cwd=ROOT)
    built = os.path.join(BUILD, 'dist', NAME)
    os.makedirs(OUT, exist_ok=True)
    internal = os.path.join(OUT, '_internal')
    if os.path.isdir(internal):                          # bibliotheques de la version precedente
        shutil.rmtree(internal)
    shutil.copytree(os.path.join(built, '_internal'), internal)
    exe = NAME + ('.exe' if WINDOWS else '')
    shutil.copy2(os.path.join(built, exe), os.path.join(OUT, exe))
    size = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(OUT) for f in fs)
    print(f'\n{os.path.join(OUT, exe)} (dossier : {size / 2 ** 20:.0f} Mo)')


if __name__ == '__main__':
    main()
