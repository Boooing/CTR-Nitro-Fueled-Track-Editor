"""Construit l'application Linux « CTR Track Editor » dans CTR/appimage a la racine du projet :
CTR_Track_Editor-<arch>.AppImage (un seul fichier : Python, bibliotheques, Qt WebEngine, editeur, three.js, schema IGZ).
Autre dossier : .build_venv/bin/python ctr_tools/editor/build_appimage.py <dossier de sortie>

    .build_venv/bin/python ctr_tools/editor/build_appimage.py

Outils dans un environnement a part (.build_venv a la racine du projet), cree au besoin :
    python3 -m venv .build_venv
    .build_venv/bin/python -m pip install pyinstaller pywebview qtpy PyQt6 PyQt6-WebEngine numpy pillow
Fenetre : pywebview avec Qt WebEngine (embarque, rien a installer chez l'utilisateur) ; un seul jeu de liaisons Qt
(PyQt6) est embarque, les autres (PyQt5, PySide) sont exclus.
appimagetool : celui du PATH, ou $APPIMAGETOOL, sinon telecharge dans .build (github.com/AppImage/appimagetool).
Sans FUSE (conteneur Docker...) : appimagetool lance en mode extraction (APPIMAGE_EXTRACT_AND_RUN).
Compatibilite : l'AppImage utilise la glibc du systeme, elle marche sur les distributions dont la glibc est au moins
celle de la machine de construction ; construire sur la plus ancienne visee (ex. Ubuntu 22.04 en x86_64 ; en aarch64,
les roues PyQt6 demandent une glibc plus recente : Ubuntu 24.04). Qt WebEngine doit se charger sur la machine de
construction (bibliotheques du systeme : APT_HINT ci-dessous, embarquees ensuite) : verifie avant de construire.
Icone et fichiers embarques : comme build_exe.py (make_icon).
Sauvegardes : out/editor a cote du fichier .AppImage, ou dans un dossier parent qui en a deja (voir app.py).
Le contenu du dossier de sortie autre que l'AppImage (ctr_editor_config.json, out...) est conserve.
"""
import os
import platform
import shutil
import stat
import subprocess
import sys
import urllib.request

from build_exe import BUILD, HERE, NAME, ROOT, TOOLS, make_icon

VENV_PY = os.path.join(ROOT, '.build_venv', 'bin', 'python')
APP_DIR = os.path.join(ROOT, 'CTR', 'appimage')
SLUG = 'ctr-track-editor'                      # nom de l'exe, du .desktop et de l'icone (sans espaces)
ARCH = {'x86_64': 'x86_64', 'amd64': 'x86_64', 'aarch64': 'aarch64', 'arm64': 'aarch64'}.get(platform.machine().lower(),
                                                                                         platform.machine())
TOOL_URL = f'https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-{ARCH}.AppImage'
# moteurs de fenetre de pywebview inutiles sous Linux (et GTK : PyGObject depend des bibliotheques du systeme)
EXCLUDE = ['webview.platforms.winforms', 'webview.platforms.edgechromium', 'webview.platforms.mshtml',
           'webview.platforms.cef', 'webview.platforms.cocoa', 'webview.platforms.android', 'webview.platforms.gtk',
           'gi', 'PyQt5', 'PySide2', 'PySide6']

# bibliotheques du systeme qu'il faut pour charger Qt WebEngine (PyQt6 6.11) lors de la construction (puis embarquees)
APT_HINT = ('sudo apt install libglib2.0-0 libgl1 libegl1 libfontconfig1 libxkbcommon-x11-0 libxcb-cursor0 '
            'libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0 '
            'libxcb-xinerama0 libnss3 libxfixes3 libxcomposite1 libxdamage1 libxrandr2 libxtst6 libxkbfile1 libasound2 '
            'liblcms2-2 libwebpdemux2 libwebpmux3 libopus0 libsnappy1v5 libminizip1')

APPRUN = f"""#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/{SLUG}/{SLUG}" "$@"
"""

DESKTOP = f"""[Desktop Entry]
Type=Application
Name={NAME}
Comment=Track editor for Crash Team Racing Nitro-Fueled
Exec={SLUG}
Icon={SLUG}
Terminal=false
Categories=Game;
"""


def appimagetool():
    """Commande appimagetool : $APPIMAGETOOL, le PATH, sinon telechargee une fois dans .build."""
    tool = os.environ.get('APPIMAGETOOL') or shutil.which('appimagetool') or shutil.which(f'appimagetool-{ARCH}.AppImage')
    if tool:
        return tool
    tool = os.path.join(BUILD, f'appimagetool-{ARCH}.AppImage')
    if not os.path.exists(tool):
        print(f'telechargement de {TOOL_URL}', flush=True)
        urllib.request.urlretrieve(TOOL_URL, tool + '.part')
        os.replace(tool + '.part', tool)
    os.chmod(tool, os.stat(tool).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return tool


def main():
    global APP_DIR
    if not sys.platform.startswith('linux'):
        sys.exit("l'AppImage se construit sous Linux (Windows : build_exe.py)")
    if len(sys.argv) > 1:
        APP_DIR = os.path.abspath(sys.argv[1])
    py = VENV_PY if os.path.exists(VENV_PY) else sys.executable

    # 1. verification : Qt WebEngine doit se charger ici, sinon les hooks PyInstaller sautent les modules Qt
    # (plugins, QtWebEngineProcess) sans erreur et l'AppImage n'ouvre pas de fenetre
    r = subprocess.run([py, '-c', 'from PyQt6 import QtWebEngineWidgets'], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f'{r.stderr.strip()}\n\nPyQt6 / Qt WebEngine ne se charge pas avec {py} : installer les paquets de la '
                 f'docstring (pip) et les bibliotheques du systeme qui manquent, ex. Ubuntu / Debian :\n  {APT_HINT}')
    # 2. icone PNG (meme dessin que l'.ico de Windows)
    os.makedirs(BUILD, exist_ok=True)
    icon = os.path.join(BUILD, SLUG + '.png')
    make_icon(icon)

    # 3. PyInstaller : dossier executable (Python + bibliotheques + fichiers de l'editeur), moteur Qt seulement
    dist = os.path.join(BUILD, 'dist-linux')
    sep = os.pathsep
    cmd = [py, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--name', SLUG,
           '--distpath', dist, '--workpath', os.path.join(BUILD, 'work-linux'), '--specpath', BUILD,
           '--paths', TOOLS, '--paths', HERE,
           '--add-data', f'{os.path.join(TOOLS, "schema")}{sep}schema',
           '--add-data', f'{os.path.join(HERE, "index.html")}{sep}.',
           '--add-data', f'{os.path.join(HERE, "i18n.js")}{sep}.',
           '--add-data', f'{os.path.join(HERE, "vendor")}{sep}vendor',
           '--hidden-import', 'server', '--collect-submodules', 'webview', '--hidden-import', 'webview.platforms.qt']
    for m in EXCLUDE:
        cmd += ['--exclude-module', m]
    cmd.append(os.path.join(HERE, 'app.py'))
    print(' '.join(f'"{c}"' if ' ' in c else c for c in cmd), flush=True)
    subprocess.check_call(cmd, cwd=ROOT)

    # 4. AppDir : AppRun -> usr/lib/<slug>/<slug> (dossier PyInstaller), .desktop et icone a la racine
    appdir = os.path.join(BUILD, f'{SLUG}.AppDir')
    if os.path.isdir(appdir):                          # genere par ce script
        shutil.rmtree(appdir)
    shutil.copytree(os.path.join(dist, SLUG), os.path.join(appdir, 'usr', 'lib', SLUG), symlinks=True)
    for name, text in (('AppRun', APPRUN), (SLUG + '.desktop', DESKTOP)):
        with open(os.path.join(appdir, name), 'w', newline='\n') as f:
            f.write(text)
    os.chmod(os.path.join(appdir, 'AppRun'), 0o755)
    shutil.copy2(icon, os.path.join(appdir, SLUG + '.png'))
    shutil.copy2(icon, os.path.join(appdir, '.DirIcon'))
    icons = os.path.join(appdir, 'usr', 'share', 'icons', 'hicolor', '256x256', 'apps')
    os.makedirs(icons)

    # icone du menu (integration au bureau)
    shutil.copy2(icon, os.path.join(icons, SLUG + '.png'))

    # 5. appimagetool : AppDir -> un seul fichier .AppImage (image squashfs + lanceur)
    os.makedirs(APP_DIR, exist_ok=True)
    out = os.path.join(APP_DIR, f'{NAME.replace(" ", "_")}-{ARCH}.AppImage')
    env = dict(os.environ, ARCH=ARCH)

    # conteneur : appimagetool est lui-meme une AppImage
    if not os.path.exists('/dev/fuse'):
        env['APPIMAGE_EXTRACT_AND_RUN'] = '1'
    tool = appimagetool()
    print(f'{tool} {appdir} {out}', flush=True)
    subprocess.check_call([tool, '--no-appstream', appdir, out], env=env)
    print(f'\n{out} ({os.path.getsize(out) / 2 ** 20:.0f} Mo)')


if __name__ == '__main__':
    main()
