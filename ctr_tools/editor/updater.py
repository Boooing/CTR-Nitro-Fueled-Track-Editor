"""Mise a jour de l'application depuis GitHub (Windows, application empaquetee).

Au lancement, la page demande /api/update_status : le fichier `version` du depot donne le numero le plus recent. S'il est
plus grand que VERSION et que la derniere release GitHub porte bien ce numero, la page propose la mise a jour.
Installation, sur accord de l'utilisateur :
  1. le .zip de la release est telecharge et decompresse dans <application>/_update/new (taille et empreinte verifiees) ;
  2. un script Windows (APPLY_SCRIPT), lance par la version installee, attend sa fermeture, remplace « CTR Track Editor.exe »
     et « _internal » (avec retour en arriere si la copie echoue), relance l'application et efface _update.
Seuls l'exe et _internal changent : ctr_editor_config.json, out/ (sauvegardes), ffmpeg.exe... restent en place.
Sans internet ou en cas d'erreur de verification : rien ne se passe, l'editeur fonctionne normalement.

Pour publier une version : changer VERSION ici, construire (build_exe.py), publier la release GitHub avec le .zip (exe + _internal
a la racine, numero dans le tag), et seulement ensuite changer le fichier `version` du depot.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile

import progress

VERSION = '0.5'
REPO = 'Boooing/CTR-Nitro-Fueled-Track-Editor'
VERSION_URL = f'https://raw.githubusercontent.com/{REPO}/refs/heads/main/version'
RELEASE_URL = f'https://api.github.com/repos/{REPO}/releases/latest'
EXE_NAME = 'CTR Track Editor.exe'
INTERNAL = '_internal'
UPDATE_DIR = '_update'
USER_AGENT = 'ctr-track-editor'
CHECK_TIMEOUT = 8
NOTES_MAX = 6000

APP_DIR = None                  # dossier de l'application empaquetee (app.py) ; None : lance depuis les sources
_status = None
_status_lock = threading.Lock()
_ready = None                   # dossier de la version telechargee, prete a installer


def _get(url, timeout=CHECK_TIMEOUT):
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Cache-Control': 'no-cache'})
    return urllib.request.urlopen(req, timeout=timeout)


def parse_version(text):
    """'0.4' -> (0, 4) ; None si ce n'est pas un numero de version."""
    text = (text or '').strip()
    return tuple(int(p) for p in text.split('.')) if re.fullmatch(r'\d+(\.\d+)*', text) else None


def is_newer(remote, local):
    """remote plus recent que local (0.10 > 0.9 ; 0.4 = 0.4.0)."""
    a, b = parse_version(remote), parse_version(local)
    if a is None or b is None:
        return False
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def _pick_asset(release):
    """Le .zip Windows de la release (le premier .zip qui n'est pas pour Linux)."""
    zips = [a for a in release.get('assets') or [] if str(a.get('name', '')).lower().endswith('.zip')]
    return next((a for a in zips if 'linux' not in a['name'].lower()), None)


def can_install():
    return bool(APP_DIR) and sys.platform == 'win32'


def check():
    """Etat de la mise a jour (reseau). Toute erreur (hors ligne, GitHub indisponible...) = pas de mise a jour."""
    out = {'current': VERSION, 'available': False, 'can_install': can_install()}
    try:
        latest = _get(VERSION_URL).read(64).decode('ascii', 'replace').strip()
        out['latest'] = latest
        if not is_newer(latest, VERSION):
            return out
        rel = json.loads(_get(RELEASE_URL).read())
        tag = str(rel.get('tag_name') or '')
        if not re.search(r'(?<![\d.])' + re.escape(latest) + r'(?![\d.])', tag):
            return out                                 # numero change avant la publication de la release : pas encore
        asset = _pick_asset(rel)
        if asset is None:
            return out
        out.update(available=True, tag=tag, name=rel.get('name') or tag, notes=(rel.get('body') or '')[:NOTES_MAX],
                   page=rel.get('html_url') or '', size=int(asset.get('size') or 0),
                   asset_url=asset.get('browser_download_url'), digest=asset.get('digest') or '')
    except Exception as e:  # noqa: BLE001 - hors ligne : l'editeur continue sans rien dire
        print(f'mise a jour : verification impossible ({e!r})', flush=True)
    return out


def status(force=False):
    """check() une fois par lancement ; force : nouvelle verification (menu Aide)."""
    global _status
    with _status_lock:
        if _status is None or force:
            _status = check()
        return _status


def public_status(force=False):
    """Etat pour la page (sans l'adresse de telechargement)."""
    return {k: v for k, v in status(force).items() if k not in ('asset_url', 'digest')}


def _update_root(app_dir):
    return os.path.join(app_dir, UPDATE_DIR)


def _download(url, dest, size, digest):
    """Telecharge url dans dest ; verifie la taille annoncee et, si GitHub la donne, l'empreinte SHA-256."""
    h, done = hashlib.sha256(), 0
    with _get(url, timeout=60) as r, open(dest, 'wb') as f:
        total = size or int(r.headers.get('Content-Length') or 0)
        while True:
            blk = r.read(1 << 20)
            if not blk:
                break
            f.write(blk)
            h.update(blk)
            done += len(blk)
            if total:
                progress.step(f'téléchargement : {done // 2**20} / {total // 2**20} Mo', 0.75 * done / total)
    if size and done != size:
        raise RuntimeError(f'téléchargement incomplet ({done} octets sur {size})')
    m = re.fullmatch(r'sha256:([0-9a-fA-F]{64})', digest or '')
    if m and h.hexdigest().lower() != m.group(1).lower():
        raise RuntimeError('fichier téléchargé corrompu (empreinte différente de celle de GitHub)')


def _safe_name(name):
    return '..' not in name.replace('\\', '/').split('/') and not os.path.isabs(name) and ':' not in name


def extract_release(archive, new_dir, step=None):
    """Extrait l'exe et _internal du .zip dans new_dir (ils peuvent etre dans un sous-dossier du .zip) ; controles CRC a
    l'extraction. -> nombre de fichiers."""
    with zipfile.ZipFile(archive) as z:
        infos = z.infolist()
        exe = [i.filename for i in infos if i.filename.replace('\\', '/').rsplit('/', 1)[-1] == EXE_NAME
               and f'/{INTERNAL}/' not in '/' + i.filename.replace('\\', '/')]
        if len(exe) != 1:
            raise RuntimeError(f'archive inattendue : « {EXE_NAME} » introuvable')
        root = exe[0].replace('\\', '/')[:-len(EXE_NAME)]
        inner = root + INTERNAL + '/'
        files = [i for i in infos if not i.is_dir() and i.filename.replace('\\', '/').startswith(inner)]
        if not files:
            raise RuntimeError(f'archive inattendue : dossier « {INTERNAL} » introuvable')
        if not all(_safe_name(i.filename) for i in files):
            raise RuntimeError('archive refusée : chemin de fichier invalide')
        need = sum(i.file_size for i in files)
        if shutil.disk_usage(os.path.dirname(new_dir)).free < 2 * need + (1 << 28):
            raise RuntimeError(f'pas assez de place sur le disque ({2 * need // 2**20} Mo nécessaires)')
        shutil.rmtree(new_dir, ignore_errors=True)
        os.makedirs(new_dir)
        for k, i in enumerate(files):
            rel = i.filename.replace('\\', '/')[len(root):]
            dst = os.path.join(new_dir, *rel.split('/'))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with z.open(i) as src, open(dst, 'wb') as out:
                shutil.copyfileobj(src, out, 1 << 20)
            if step and k % 20 == 0:
                step(k / len(files))
        with z.open(exe[0]) as src, open(os.path.join(new_dir, EXE_NAME), 'wb') as out:
            shutil.copyfileobj(src, out, 1 << 20)
    return len(files) + 1


def download():
    """Etape 1 : version telechargee et decompressee dans _update/new. -> {ready, latest}."""
    global _ready
    st = status()
    if not st.get('available') or not can_install():
        raise RuntimeError('aucune mise à jour à installer')
    root = _update_root(APP_DIR)
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(root, exist_ok=True)
    archive = os.path.join(root, 'release.zip')
    progress.step('téléchargement', 0.0)
    _download(st['asset_url'], archive, st.get('size') or 0, st.get('digest') or '')
    progress.step('décompression', 0.75)
    new_dir = os.path.join(root, 'new')
    extract_release(archive, new_dir, lambda f: progress.step('décompression', 0.75 + 0.24 * f))
    os.remove(archive)
    _ready = new_dir
    return {'ready': True, 'latest': st['latest']}


# Script de remplacement (Windows) : lance par la version installee, il attend sa fermeture puis remplace l'exe et _internal.
# Il ne depend pas de la version telechargee (une release sans ce mecanisme s'installe aussi). Parametres : variables
# d'environnement (chemins avec accents sans probleme). En cas d'erreur : ancienne version remise. Texte ASCII seulement.
APPLY_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
$app = $env:CTR_UPD_APP; $new = $env:CTR_UPD_NEW; $exeName = $env:CTR_UPD_EXE; $oldPid = [int]$env:CTR_UPD_PID
$internal = '_internal'
$root = Join-Path $app '_update'
$log = Join-Path $app 'ctr_update.log'
function Say($t) { Add-Content -LiteralPath $log -Encoding UTF8 -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ' + $t) }
function Retry([scriptblock]$f) {
    for ($k = 0; ; $k++) { try { & $f; return } catch { if ($k -ge 20) { throw }; Start-Sleep -Milliseconds 500 } }
}
$p = Get-Process -Id $oldPid -ErrorAction SilentlyContinue
if ($p -and -not $p.WaitForExit(60000)) { Say 'ancienne version toujours ouverte : mise a jour abandonnee'; exit 1 }
$curExe = Join-Path $app $exeName; $curInt = Join-Path $app $internal
$backup = Join-Path $root 'old'; $oldExe = Join-Path $backup $exeName; $oldInt = Join-Path $backup $internal
$moved = @()
try {
    if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Recurse -Force }
    New-Item -ItemType Directory -Path $backup | Out-Null
    Retry { Move-Item -LiteralPath $curInt -Destination $oldInt }
    $moved += ,@($oldInt, $curInt)
    Retry { Move-Item -LiteralPath $curExe -Destination $oldExe }
    $moved += ,@($oldExe, $curExe)
    if (-not (Test-Path -LiteralPath (Join-Path $new $internal))) { throw 'version telechargee incomplete' }
    Copy-Item -LiteralPath (Join-Path $new $internal) -Destination $curInt -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $new $exeName) -Destination $curExe -Force
    Say 'mise a jour installee'
} catch {
    Say ('echec, version precedente remise : ' + $_)
    [array]::Reverse($moved)
    foreach ($m in $moved) {
        if (Test-Path -LiteralPath $m[1]) { Remove-Item -LiteralPath $m[1] -Recurse -Force }
        Retry { Move-Item -LiteralPath $m[0] -Destination $m[1] }
    }
}
try { Start-Process -FilePath $curExe -WorkingDirectory $app } catch { Say ('relancement impossible : ' + $_) }
for ($k = 0; $k -lt 12 -and (Test-Path -LiteralPath $root); $k++) {
    try { Remove-Item -LiteralPath $root -Recurse -Force } catch { Start-Sleep -Seconds 5 }
}
Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
'''


def _child_env():
    """Autre application PyInstaller lancee depuis celle-ci : pas ses variables internes (bibliotheques, drapeaux Qt)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith('_PYI') and k != 'QTWEBENGINE_CHROMIUM_FLAGS'}
    env['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    return env


def spawn_apply(pid, app_dir, new_dir):
    """Lance le script de remplacement, detache : il attend la fin du processus pid. -> le processus du script."""
    fd, script = tempfile.mkstemp(prefix='ctr_update_', suffix='.ps1')
    with os.fdopen(fd, 'w', encoding='ascii', newline='\r\n') as f:
        f.write(APPLY_SCRIPT)
    env = _child_env()
    env.update(CTR_UPD_APP=app_dir, CTR_UPD_NEW=new_dir, CTR_UPD_EXE=EXE_NAME, CTR_UPD_PID=str(pid))
    return subprocess.Popen(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', script],
                            cwd=tempfile.gettempdir(), env=env, close_fds=True,
                            creationflags=0x08000000 | 0x00000200)   # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP


def start_apply():
    """Etape 2 : lance le remplacement, qui commencera des que cette application sera fermee."""
    if not _ready or not os.path.isfile(os.path.join(_ready, EXE_NAME)):
        raise RuntimeError('la mise à jour n\'a pas été téléchargée')
    spawn_apply(os.getpid(), APP_DIR, _ready)
    return {'restarting': True}


def cleanup(app_dir):
    """Au lancement : fichiers temporaires d'une mise a jour terminee (la version qui les a installes finit de se fermer)."""
    root = _update_root(app_dir)
    if not os.path.isdir(root):
        return

    def run():
        for _ in range(12):
            shutil.rmtree(root, ignore_errors=True)
            if not os.path.isdir(root):
                return
            time.sleep(5)
    threading.Thread(target=run, daemon=True).start()
