"""« Tester en jeu » : le jeu demarre directement sur une course unique de la piste choisie.

Script de l'ecran titre (vsc/Octane_StartScreen/Octane_StartScreen_Manager.igz, version update2) : au demarrage,
getGameMode -> switch (0 / hors table -> menu « Press Start », 1 / 16 -> menu principal, 8 = Arcade au retour d'une
course -> getArcadeMenuToOpen). Au lancement le jeu est deja en mode 8 avec le menu Arcade « principal » (6) ou
« aucun » (0) : ces cas, et toutes les branches du switch sauf 8, sont detournes vers :
    applyPreviousRaceSettings -> setNextGameMode(8 Arcade) -> setNextRaceMode(1 course unique) -> piste
    -> getNextRaceMode -> setNextMap(piste) + choix du personnage / kart -> course
(un loadMap2 direct donnait un kart sans pilote ni camera : le pilote n'est charge que par l'ecran de
personnalisation). launch() lance shadPS4 et valide ce choix (touche croix) des que le journal montre le pilote charge,
puis remet le jeu normal a la fermeture de l'emulateur.

Usage :
    python quick_test.py patch <Octane_StartScreen_Manager.igz> <sortie.igz> <T901_Custom_Map>
    python quick_test.py install <archives> <T901_Custom_Map>
    python quick_test.py uninstall <archives>
"""
import configparser
import glob
import os
import struct
import subprocess
import sys
import threading
import time

import pak_tool
from igz import IgzFile

MANAGER = 'vsc/Octane_StartScreen/Octane_StartScreen_Manager.igz'
INTRO_VIDEOS = ('octane_intro_logo_atvi.bk2', 'openinglogo.bk2', 'ctr_game_intro.bk2')
VIDEO_OFF = '.ctrmod-off'
GAME_MODE_ARCADE = 8
RACE_MODE_SINGLE = 1


def map_path(track):
    """'T901_Custom_Map' -> 'Octane/T901_Custom_Map/T901_Custom_Map' (chemin des zoneInfo)."""
    return f'Octane/{track}/{track}'


def patch_manager(data, track, customize=True):
    z = IgzFile(data)
    by_name = {n: o for n, o in z.root_objects() if n}
    switch = by_name['Switch_id_kz3ps9lk']                       # getGameMode -> menu a ouvrir
    action1 = by_name['Octane_Game_Manager_id_t13jig1z']         # appel a 1 accesseur enum (getNextRaceMode)
    action0 = by_name['Music_id_les4un4g']                       # appel sans accesseur (resumeCurrentMusic)
    const_enum = by_name['E_Octane_Arcade_Menus_id_w96a1l35_Accessor']
    assign = by_name['Set_id_mkkj0clk']                          # « Octane_StartScreen_Menu » -> nom du menu
    track_field = by_name['String_id_lm5sg651_Accessor']         # piste lue par loadMap2 (methode enhdmr9h)
    fade_load = by_name['Fade_Out_id_6oa5vo55']                  # fondu puis loadMap2(piste)
    # getNextRaceMode -> course unique : setNextMap(piste) + choix du personnage (charge le pilote ; sans lui,
    # loadMap2 direct donne un kart sans pilote ni camera)
    to_customization = by_name['Octane_Game_Manager_id_t13jig1z']

    def enum_value(v):
        acc = z.clone_object(const_enum)
        z.set_field(acc, '_value', v)
        return acc

    def int_value(v):
        acc = z.clone_object(const_enum)                         # meme taille / meme mise en page que ConstInt
        struct.pack_into('<Q', *z._loc(acc), z.type_index('igVscConstIntAccessor'))
        z.objects[acc] = 'igVscConstIntAccessor'
        z.set_field(acc, '_value', v)
        return acc

    def call(fn, arg=None):
        node = z.clone_object(action1 if arg is not None else action0)
        struct.pack_into('<I', *z._loc(node + 0x38), z._exnm_add(fn, 'metafunction', 0))
        if arg is not None:
            arr = z.alloc(8, 16)
            z.set_ptr(arr, arg)
            z.set_ptr(node + 0x20, arr)
        z.set_ptr(node + 0x28, None)
        z.set_ptr(node + 0x30, None)
        return node

    def chain(*nodes):
        for a, b in zip(nodes, nodes[1:]):
            z.set_ptr(a + 0x28, b)
        return nodes[0]

    # comme le menu : reglages de la derniere course (pilote, kart...), mode, 1 joueur local
    prev = call('CRaceUtilityNodes::applyPreviousRaceSettings_VSC')
    set_game = call('CGameUtilityNodes::setNextGameMode_VSC', enum_value(GAME_MODE_ARCADE))
    set_race = call('CRaceModeNodes::setNextRaceMode_VSC', enum_value(RACE_MODE_SINGLE))
    set_count = call('CGameUtilityNodes::setNextLocalPlayerCount_VSC', int_value(1))
    apply_count = call('CGameUtilityNodes::applyLocalPlayerCount_VSC')
    path = z.clone_object(z.deref(assign + 0x10))
    z.set_string_ref(z.find_field(path, '_value')[0], map_path(track))
    set_path = z.clone_object(assign)
    z.set_ptr(set_path + 0x10, path)
    z.set_ptr(set_path + 0x18, track_field)
    z.set_ptr(set_path + 0x20, to_customization if customize else fade_load)
    # set_count / apply_count : pilote recharge en pleine course -> manque de memoire (OOM HeroData) et plantage
    start = chain(prev, set_game, set_race, set_path)

    # case du mode 0 (premier lancement) dans la table du switch : cles u32, valeurs pointeurs
    table = z.deref(switch + 0x18)
    vsize, values = z.u32(table + 0x10), z.deref(table + 0x18)
    keys = z.deref(table + 0x28)
    main_menu = by_name['Set_id_ed17qijz']                       # « Octane_MainMenu »
    slots = [i for i in range(vsize // 8) if z.deref(values + i * 8) in (assign, main_menu)]
    if not slots:
        raise ValueError('script de l\'ecran titre inattendu')
    for i in slots:                                              # tout sauf le retour d'une course Arcade (8)
        z.set_ptr(values + i * 8, start)
    if z.deref(switch + 0x20) == assign:                         # mode hors table (eGM_Invalid != 0 ?) : idem
        z.set_ptr(switch + 0x20, start)
    # mode Arcade des le lancement (constate en jeu) : getArcadeMenuToOpen -> 6 menu principal / 0 aucun / 5 -> ecran
    # titre ou menu principal ; apres une course il vaut piste / personnage / mode (1-4) : inchange, pas de boucle
    arcade = by_name['Switch_id_hmptn8li']
    boot_menus = {by_name['Set_id_mfqfgbmk'], by_name['Set_id_uxf8fydt']}
    table = z.deref(arcade + 0x18)
    vsize, values = z.u32(table + 0x10), z.deref(table + 0x18)
    for i in range(vsize // 8):
        if z.deref(values + i * 8) in boot_menus:
            z.set_ptr(values + i * 8, start)
    # isInAdhocMode vrai (cas de shadPS4) : disableAdhoc -> menu « Press Start », sans passer par getGameMode
    adhoc_off = by_name.get('Adhoc_id_fhv7osom')
    if adhoc_off is not None and z.deref(adhoc_off + 0x28) == by_name.get('Set_id_glngoxc1'):
        z.set_ptr(adhoc_off + 0x28, start)
    z.add_roots([(prev, 'CtrTest_PreviousSettings'), (set_game, 'CtrTest_SetGameMode'),
                 (set_race, 'CtrTest_SetRaceMode'), (set_count, 'CtrTest_SetPlayerCount'),
                 (apply_count, 'CtrTest_ApplyPlayerCount'), (set_path, 'CtrTest_SetTrack')])
    return z.to_bytes()


def set_intro_videos(archives, hidden):
    """Videos d'introduction mises de cote (<video>.ctrmod-off, remises par game_restore) ou remises."""
    report = []
    for v in INTRO_VIDEOS:
        # jeu en deux dossiers : la video que le jeu lit (mise a jour, sinon jeu de base), mise de cote a cote d'elle
        if hidden:
            on = pak_tool.real(os.path.join(archives, v))
            off = on + VIDEO_OFF
        else:
            off = pak_tool.real(os.path.join(archives, v + VIDEO_OFF))
            on = off[:-len(VIDEO_OFF)]
        src, dst = (on, off) if hidden else (off, on)
        if os.path.exists(src) and not os.path.exists(dst):
            os.replace(src, dst)
            report.append(f'{v} : {"mise de côté" if hidden else "remise"}')
    return report


PATCH_MARK = b'CtrTest_SetTrack'  # nom ajoute par patch_manager


def _saved_manager(archives):
    return os.path.join(archives, os.path.basename(MANAGER) + '.ctrmod-orig')


def original_manager(archives):
    """Script d'ecran titre d'origine, meme si le patch est encore en place : essai precedent jamais remis (editeur ferme,
    plantage) sur un update2 SANS sauvegarde de TOC (les ajouts vont dans update3 ; « script de l'ecran titre
    inattendu », et la remise a l'etat normal reecrivait le script patche). Copie gardee par install, sinon version d'update."""
    data, _ = pak_tool.read_latest(archives, MANAGER)
    if PATCH_MARK not in data:
        return data
    p = _saved_manager(archives)
    if os.path.exists(p):
        return open(p, 'rb').read()
    upd = os.path.join(archives, 'update.pak')
    if pak_tool.exists(upd):
        arc, idx, lock = pak_tool.cached_archive(upd)
        e = idx.get(MANAGER.lower())
        if e is not None:
            with lock:
                data = arc.read(e)
            if PATCH_MARK not in data:
                return data
    raise ValueError('script de l\'écran titre d\'origine introuvable : vérifie les fichiers du jeu')


def _test_backup(archives):
    """Sauvegarde propre a « Tester en jeu » quand update2 n'a pas celle de l'editeur (.ctrmod.json) : sans elle, chaque
    essai ajoutait l'ecran titre modifie puis l'original en fin d'update2 (+60 ko par essai, jamais retires : l'update2
    de l'autre PC avait grossi de 125 ko). Chemin du fichier que le jeu lit (jeu en deux dossiers : la mise a jour)."""
    return pak_tool.real(os.path.join(archives, 'update2.pak')) + '.ctrtest'


def install(archives, track):
    """Ecran titre -> course unique sur `track` + intros sautees. Le fichier remplace est ajoute en fin d'update2 ;
    si update2 n'a pas de sauvegarde de l'editeur, son en-tete (TOC) et sa taille sont gardes avant : uninstall le
    remet a l'identique. Sinon la sauvegarde de l'editeur couvre deja ces ajouts."""
    data = original_manager(archives)
    p = _saved_manager(archives)
    if not os.path.exists(p):
        with open(p, 'wb') as f:
            f.write(data)
    u2 = os.path.join(archives, 'update2.pak')
    bk = _test_backup(archives)
    if not os.path.exists(pak_tool.backup_path(u2)) and not os.path.exists(bk):
        real = pak_tool.real(u2)
        a = pak_tool.IgaArchive(real)
        head_len = min(e.offset for e in a.entries)          # en-tete + TOC : la seule zone reecrite en place
        a.f.seek(0)
        head = a.f.read(head_len)
        a.f.close()
        with open(bk, 'wb') as f:
            f.write(struct.pack('<Q', os.path.getsize(real)) + head)
    pak_tool._append_replace(u2, {MANAGER: patch_manager(data, track)})
    return [f'écran titre : course unique sur {track}'] + set_intro_videos(archives, True)


def uninstall(archives):
    """Ecran titre d'origine + videos d'introduction remises (update2 a l'identique si la sauvegarde d'essai existe)."""
    data = original_manager(archives)
    u2 = os.path.join(archives, 'update2.pak')
    bk = _test_backup(archives)
    if os.path.exists(bk) and not os.path.exists(pak_tool.backup_path(u2)):
        raw = open(bk, 'rb').read()
        size, head = struct.unpack('<Q', raw[:8])[0], raw[8:]
        real = pak_tool.real(u2)
        pak_tool.invalidate_cache(u2)
        pak_tool._orig_cache.pop(real, None)
        with open(real, 'r+b') as f:
            f.seek(0)
            f.write(head)
            f.truncate(size)
        pak_tool.invalidate_cache(u2)
        os.remove(bk)
        # update2 deja bloque avant l'essai (ecran titre d'un ancien essai jamais remis) : l'original par-dessus
        if PATCH_MARK in pak_tool.read_latest(archives, MANAGER, original=False)[0]:
            pak_tool._append_replace(u2, {MANAGER: data})
    elif pak_tool.read_latest(archives, MANAGER, original=False)[0] != data:
        pak_tool._append_replace(u2, {MANAGER: data})
    if os.path.exists(bk):                                   # sauvegarde de l'editeur arrivee entre-temps : caduque
        os.remove(bk)
    p = _saved_manager(archives)
    if os.path.exists(p):
        os.remove(p)
    return ['écran titre d\'origine'] + set_intro_videos(archives, False)


# --- shadPS4 : lancement, validation automatique du choix du personnage, retour au jeu normal ---------------------
CROSS_KEY = 0x4E                  # « n » : croix au clavier dans la configuration par defaut de shadPS4
READY_MARK = 'forPlayID:0'        # journal : pilote du joueur charge -> ecran de personnalisation pret
FIRST_PRESS, PRESS_EVERY, MAX_PRESSES = 0.8, 1.0, 15     # s apres READY_MARK, s entre deux appuis, appuis au plus
STATUS = {'state': 'idle', 'text': ''}


def _status(state, text):
    STATUS.update(state=state, text=text, time=time.time())


def find_shadps4(configured=None):
    """shadPS4.exe : reglage, sinon version choisie dans le lanceur Qt (qt_ui.ini), sinon la plus recente."""
    if configured and os.path.isfile(configured):
        return configured
    root = os.path.join(os.environ.get('APPDATA', ''), 'shadPS4QtLauncher')
    ini = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        ini.read(os.path.join(root, 'qt_ui.ini'), encoding='utf-8')
        sel = ini.get('version_manager', 'versionSelected', fallback='').strip('"')
        if sel and os.path.isfile(sel):
            return os.path.normpath(sel)
    except (configparser.Error, OSError):
        pass
    found = sorted(glob.glob(os.path.join(root, 'versions', '*', 'shadPS4*.exe')), key=os.path.getmtime)
    return found[-1] if found else None


def emulator_running():
    if sys.platform != 'win32':
        return subprocess.run(['pgrep', '-f', 'shadps4'], capture_output=True).returncode == 0
    out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq shadPS4.exe', '/NH'], capture_output=True, text=True,
                         creationflags=0x08000000).stdout
    return 'shadps4.exe' in out.lower()


def log_path(exe):
    """Journal de shadPS4 : dossier « user » a cote de l'exe (version portable), sinon %APPDATA%\\shadPS4."""
    portable = os.path.join(os.path.dirname(exe), 'user', 'log', 'shad_log.txt')
    if os.path.isdir(os.path.dirname(portable)):
        return portable
    return os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'shadPS4', 'log', 'shad_log.txt')


class _Log:
    """Lecture au fil de l'eau du journal (recree a chaque lancement)."""

    def __init__(self, path, since):
        self.path, self.since, self.pos, self.text = path, since, 0, ''

    def read(self):
        try:
            if os.path.getmtime(self.path) < self.since:
                return ''
            size = os.path.getsize(self.path)
            if size < self.pos:
                self.pos, self.text = 0, ''
            with open(self.path, 'rb') as f:
                f.seek(self.pos)
                new = f.read().decode('utf-8', 'replace')
            self.pos += len(new.encode('utf-8'))
            self.text += new
            return new
        except OSError:
            return ''


def _emulator_pids():
    out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq shadPS4.exe', '/FO', 'CSV', '/NH'], capture_output=True,
                         text=True, creationflags=0x08000000).stdout
    return {int(l.split('","')[1]) for l in out.splitlines() if l.lower().startswith('"shadps4.exe"')}


def _press_cross(pid):
    """Croix envoyee a la fenetre du jeu, SEULEMENT si elle est au premier plan (jamais a une autre application)."""
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.windll.user32
    pids = {pid} | _emulator_pids()
    wins = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        p = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value in pids and u32.IsWindowVisible(hwnd):
            wins.append(hwnd)
        return True

    u32.EnumWindows(each, 0)
    if not wins:
        return False
    fg = u32.GetForegroundWindow()
    if fg not in wins:
        u32.keybd_event(0x12, 0, 0, 0)            # Alt : autorise le passage au premier plan
        u32.keybd_event(0x12, 0, 2, 0)
        u32.SetForegroundWindow(wins[0])
        time.sleep(0.3)
        if u32.GetForegroundWindow() not in wins:
            return False
    scan = u32.MapVirtualKeyW(CROSS_KEY, 0)
    u32.keybd_event(CROSS_KEY, scan, 0, 0)
    time.sleep(0.12)
    u32.keybd_event(CROSS_KEY, scan, 2, 0)
    return True


def clean_env():
    """Environnement de l'emulateur sans les reglages de l'exe de l'editeur (2026-11-12). L'exe (PyInstaller + PySide6)
    pointe QT_PLUGIN_PATH, PATH... vers SON Qt (_internal) : shadPS4, qui a son propre Qt, y chargeait des morceaux
    d'une autre version (« point d'entree ?convertVolume@QAudio@@... introuvable » sur un autre PC)."""
    env = dict(os.environ)
    bundle = getattr(sys, '_MEIPASS', None)
    for k in list(env):
        if k.upper().startswith(('QT_', 'QTWEBENGINE', 'QML', 'PYTHON', '_PYI', '_MEI')):
            del env[k]
    if bundle:
        root = os.path.normcase(os.path.abspath(bundle))
        keep = [p for p in env.get('PATH', '').split(os.pathsep)
                if p and not os.path.normcase(os.path.abspath(p)).startswith(root)]
        env['PATH'] = os.pathsep.join(keep)
    return env


def _popen_clean(cmd, cwd):
    """Popen hors du dossier de DLL de l'exe : le chargeur PyInstaller appelle SetDllDirectoryW(_internal), que les
    processus fils heritent ; remis a zero le temps du lancement."""
    if os.name == 'nt' and getattr(sys, 'frozen', False):
        import ctypes
        k32 = ctypes.windll.kernel32
        buf = ctypes.create_unicode_buffer(32768)
        old = buf.value if k32.GetDllDirectoryW(32768, buf) else ''
        k32.SetDllDirectoryW(None)
        try:
            return subprocess.Popen(cmd, cwd=cwd, env=clean_env())
        finally:
            if old:
                k32.SetDllDirectoryW(old)
    return subprocess.Popen(cmd, cwd=cwd, env=clean_env())


def launch(exe, game_root, track, on_exit=None, auto_ready=True, timeout=180):
    """Lance shadPS4 sur le jeu ; fil de suivi : validation du choix perso / kart, puis on_exit() a la fermeture."""
    since = time.time() - 2
    proc = _popen_clean([exe, '-g', os.path.join(game_root, 'eboot.bin')], os.path.dirname(exe))
    log = _Log(log_path(exe), since)
    load_marks = (f"load {map_path(track)}".lower(), f"'{map_path(track).lower()}'")
    _status('starting', 'shadPS4 lancé, démarrage du jeu…')

    def watch():
        nonlocal auto_ready
        try:
            ready_at, presses, loaded, t0 = None, 0, False, time.time()
            while proc.poll() is None or emulator_running():       # le jeu peut tourner dans un 2e processus
                log.read()
                low = log.text.lower()
                if not loaded and any(m in low for m in load_marks):
                    loaded = True
                    _status('race', f'course lancée sur {track}')
                elif not loaded and auto_ready and sys.platform == 'win32':
                    if ready_at is None and READY_MARK.lower() in low:
                        ready_at = time.time() + FIRST_PRESS
                        _status('ready', 'choix du personnage : validation automatique…')
                    if ready_at and time.time() >= ready_at:
                        if _press_cross(proc.pid):
                            presses += 1
                        ready_at = time.time() + PRESS_EVERY
                    if presses >= MAX_PRESSES or time.time() - t0 > timeout:
                        auto_ready = False
                        _status('ready', 'validation automatique arrêtée : valide le choix à la manette')
                time.sleep(0.2)
            _status('closing', 'shadPS4 fermé : remise du jeu normal…')
        finally:
            if on_exit:
                on_exit()

    threading.Thread(target=watch, daemon=True).start()
    return proc


def main(argv):
    if len(argv) == 5 and argv[1] == 'patch':
        out = patch_manager(open(argv[2], 'rb').read(), argv[4])
        open(argv[3], 'wb').write(out)
        print(f'ecrit {argv[3]} ({len(out)} o)')
        return 0
    if len(argv) == 4 and argv[1] == 'install':
        print('\n'.join(install(argv[2], argv[3])))
        return 0
    if len(argv) == 3 and argv[1] == 'uninstall':
        print('\n'.join(uninstall(argv[2])))
        return 0
    print(__doc__)
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
