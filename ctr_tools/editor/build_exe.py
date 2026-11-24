"""Construit l'application « CTR Track Editor » dans CTR/exe a la racine du projet :
CTR Track Editor.exe + _internal (Python, bibliotheques, editeur, three.js, schema IGZ), sans console.
Autre dossier : python ctr_tools/editor/build_exe.py <dossier de sortie>

    python ctr_tools/editor/build_exe.py

Outils dans un environnement a part (.build_venv a la racine du projet), cree au besoin :
    python -m venv .build_venv
    set PIP_USE_FEATURE=truststore        (certificats de Windows : un antivirus qui filtre le HTTPS bloquait pip)
    .build_venv\\Scripts\\python -m pip install pyinstaller PySide6-Essentials PySide6-WebEngine numpy pillow
Fenetre : Qt WebEngine (Chromium embarque, plus besoin d'Edge WebView2 sur le PC).
Fichiers embarques : index.html, i18n.js, creator.js, clay.js, vendor/three (editeur hors ligne), schema/ctr_meta.json (format IGZ).
Icone : crash-team-racing-nitro-fueled_j4g2.jpg (racine du projet) s'il existe, fond blanc rendu transparent ;
sinon drapeau a damier dessine.
Sauvegardes : out/editor a cote de l'exe, ou dans un dossier parent qui en a deja (voir app.py).
Le contenu du dossier de sortie autre que l'exe et _internal (ctr_editor_config.json...) est conserve.

Moins de faux positifs d'antivirus (2026-11-23) :
  - fiche de version Windows (produit, version, description : Proprietes > Details de l'exe) ;
  - --noupx : jamais de compression UPX (souvent signalee), meme si upx est installe ;
  - lanceur PyInstaller recompile sur ce PC (empreinte propre, pas celle partagee avec des malwares) :
        python ctr_tools/editor/build_exe.py --bootloader
    reinstalle PyInstaller depuis ses sources dans .build_venv en compilant le lanceur (outils C++ de Visual Studio
    Build Tools necessaires), sans construire l'exe. A refaire seulement apres une mise a jour de PyInstaller.
    Le script affiche a chaque construction si le lanceur est celui d'origine ou recompile.
"""
import hashlib
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
# icone : logo de l'editeur choisi par l'utilisateur (2026-11-14, PNG a fond transparent) a la racine du projet ;
# sinon l'ancien logo du jeu (fond blanc rendu transparent par make_icon) ; sinon drapeau a damier dessine
ICON_SRC = next((p for p in (os.path.join(ROOT, 'ctrnfte_logo.png'), os.path.join(ROOT, 'crash-team-racing-nitro-fueled_j4g2.jpg'))
                 if os.path.exists(p)), os.path.join(ROOT, 'ctrnfte_logo.png'))


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


# Qt embarque par PyInstaller mais inutile a la fenetre (QML, 3D, graphiques, multimedia, styles...) ; Qt WebEngine
# lui-meme a besoin de Quick, Qml, QmlModels, QmlMeta, QmlWorkerScript, QuickWidgets, Positioning, WebChannel, Network
PRUNE_DIRS = ['qml']
PRUNE_DLL = ('Qt63D', 'Qt6Charts', 'Qt6DataVisualization', 'Qt6Graphs', 'Qt6Labs', 'Qt6Location', 'Qt6Multimedia',
             'Qt6Quick3D', 'Qt6QuickControls2', 'Qt6QuickDialogs2', 'Qt6QuickEffects', 'Qt6QuickLayouts',
             'Qt6QuickNativeStyle', 'Qt6QuickParticles', 'Qt6QuickShapes', 'Qt6QuickTest', 'Qt6QuickTimeline',
             'Qt6QuickVectorImage', 'Qt6RemoteObjects', 'Qt6Scxml', 'Qt6Sensors', 'Qt6SerialPort', 'Qt6ShaderTools',
             'Qt6SpatialAudio', 'Qt6Sql', 'Qt6StateMachine', 'Qt6Test', 'Qt6TextToSpeech', 'Qt6VirtualKeyboard',
             'Qt6WebView', 'Qt6WebEngineQuick', 'Qt6WebChannelQuick', 'Qt6PositioningQuick', 'Qt6QmlLocalStorage',
             'Qt6QmlXmlListModel', 'Qt6QmlDesignSupport', 'Qt6QmlNetwork', 'Qt6QmlCore')
KEEP_LOCALES = ('en-US', 'fr', 'es', 'it', 'de')                 # langues de l'editeur


def prune_qt(internal):
    """Retire de _internal/PySide6 ce que la fenetre n'utilise pas (≈ 600 -> 400 Mo)."""
    qt = os.path.join(internal, 'PySide6')
    if not os.path.isdir(qt):
        return
    for d in PRUNE_DIRS:
        shutil.rmtree(os.path.join(qt, d), ignore_errors=True)
    for f in os.listdir(qt):
        if f.endswith('.dll') and f.startswith(PRUNE_DLL):
            os.remove(os.path.join(qt, f))
    dbg = os.path.join(qt, 'resources', 'qtwebengine_devtools_resources.debug.pak')
    if os.path.exists(dbg):
        os.remove(dbg)
    loc = os.path.join(qt, 'translations', 'qtwebengine_locales')
    if os.path.isdir(loc):
        for f in os.listdir(loc):
            if os.path.splitext(f)[0] not in KEEP_LOCALES:
                os.remove(os.path.join(loc, f))


# empreinte du lanceur sans console livre par pip (PyInstaller 6.22.3) : lanceur d'origine, pas recompile
STOCK_RUNW = {'2291f269c3a3804fde1079462239e09a8b32fffbeeaa8f628a531faf5be77d41'}


def write_version_file(path):
    """Fiche de version Windows de l'exe (un exe sans aucune info parait plus suspect aux antivirus)."""
    import re
    src = open(os.path.join(HERE, 'updater.py'), encoding='utf-8').read()
    ver = re.search(r"^VERSION = '([^']+)'", src, re.M).group(1)
    repo = re.search(r"^REPO = '([^']+)'", src, re.M).group(1)
    nums = [int(x) for x in ver.split('.') if x.isdigit()][:4]
    nums += [0] * (4 - len(nums))
    t = tuple(nums)
    v = ver
    txt = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
                    date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040C04B0', [
      StringStruct('CompanyName', 'CTR Nitro-Fueled Track Editor (open source)'),
      StringStruct('FileDescription', 'CTR Nitro-Fueled Track Editor'),
      StringStruct('FileVersion', '{v}'),
      StringStruct('InternalName', 'CTR Track Editor'),
      StringStruct('LegalCopyright', 'Open source - github.com/{repo}'),
      StringStruct('OriginalFilename', '{NAME}.exe'),
      StringStruct('ProductName', 'CTR Nitro-Fueled Track Editor'),
      StringStruct('ProductVersion', '{v}')])]),
    VarFileInfo([VarStruct('Translation', [0x040C, 1200])])
  ]
)
"""
    open(path, 'w', encoding='utf-8').write(txt)


def bootloader_state(py):
    """'recompile' / 'origine' / '?' selon l'empreinte de runw.exe dans l'environnement de construction."""
    out = subprocess.run([py, '-c', 'import PyInstaller, os; print(os.path.dirname(PyInstaller.__file__))'],
                         capture_output=True, text=True).stdout.strip()
    f = os.path.join(out, 'bootloader', 'Windows-64bit-intel', 'runw.exe')
    if not os.path.exists(f):
        return '?'
    h = hashlib.sha256(open(f, 'rb').read()).hexdigest()
    return 'origine' if h in STOCK_RUNW else 'recompile'


def rebuild_bootloader(py):
    """Reinstalle PyInstaller (meme version) depuis ses sources en compilant le lanceur sur ce PC."""
    ver = subprocess.run([py, '-c', 'import PyInstaller; print(PyInstaller.__version__)'],
                         capture_output=True, text=True).stdout.strip()
    env = dict(os.environ, PYINSTALLER_COMPILE_BOOTLOADER='1', PIP_USE_FEATURE='truststore')
    subprocess.check_call([py, '-m', 'pip', 'install', '--force-reinstall', '--no-deps', '--no-cache-dir',
                           '--no-binary', 'pyinstaller', f'pyinstaller=={ver}'], env=env)
    print('lanceur PyInstaller :', bootloader_state(py))


def main():
    global APP_DIR
    if '--bootloader' in sys.argv:
        rebuild_bootloader(VENV_PY if os.path.exists(VENV_PY) else sys.executable)
        return
    if len(sys.argv) > 1:
        APP_DIR = os.path.abspath(sys.argv[1])
    py = VENV_PY if os.path.exists(VENV_PY) else sys.executable
    os.makedirs(BUILD, exist_ok=True)
    icon = os.path.join(BUILD, 'ctr_editor.ico')
    make_icon(icon)
    vfile = os.path.join(BUILD, 'version_info.txt')
    write_version_file(vfile)
    print('lanceur PyInstaller :', bootloader_state(py), '(python build_exe.py --bootloader pour le recompiler)')
    dist = os.path.join(BUILD, 'dist')
    sep = os.pathsep
    cmd = [py, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--windowed', '--name', NAME,
           '--icon', icon, '--version-file', vfile, '--noupx', '--distpath', dist, '--workpath', os.path.join(BUILD, 'work'), '--specpath', BUILD,
           '--paths', TOOLS, '--paths', HERE,
           '--add-data', f'{os.path.join(TOOLS, "schema")}{sep}schema',
           '--add-data', f'{os.path.join(HERE, "index.html")}{sep}.',
           '--add-data', f'{os.path.join(HERE, "i18n.js")}{sep}.',
           '--add-data', f'{os.path.join(HERE, "creator.js")}{sep}.',
           '--add-data', f'{os.path.join(HERE, "clay.js")}{sep}.',          # sol en pate a modeler (2026-11-24)
           '--add-data', f'{os.path.join(HERE, "vendor")}{sep}vendor',
           '--hidden-import', 'server', '--hidden-import', 'updater', '--hidden-import', 'PySide6.QtWebEngineWidgets',
           '--exclude-module', 'webview',
           os.path.join(HERE, 'app.py')]
    print(' '.join(f'"{c}"' if ' ' in c else c for c in cmd), flush=True)
    subprocess.check_call(cmd, cwd=ROOT)
    built = os.path.join(dist, NAME)
    os.makedirs(APP_DIR, exist_ok=True)
    internal = os.path.join(APP_DIR, '_internal')
    if os.path.isdir(internal):                        # ancienne version des bibliotheques (genere par ce script)
        shutil.rmtree(internal)
    shutil.copytree(os.path.join(built, '_internal'), internal)
    prune_qt(internal)
    shutil.copy2(os.path.join(built, NAME + '.exe'), os.path.join(APP_DIR, NAME + '.exe'))
    size = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(APP_DIR) for f in fs)
    print(f'\n{os.path.join(APP_DIR, NAME + ".exe")} (dossier : {size / 2 ** 20:.0f} Mo)')


if __name__ == '__main__':
    main()
