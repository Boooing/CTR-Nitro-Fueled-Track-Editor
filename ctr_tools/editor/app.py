"""Editeur de pistes CTR en application de bureau (Windows .exe ou Linux .AppImage, PyInstaller) : le serveur tourne
dans l'application et l'editeur s'ouvre dans sa propre fenetre Qt WebEngine (PySide6, Chromium embarque : ne depend
plus d'Edge WebView2, absent ou casse sur certains PC). Sans PySide6 : pywebview (WebView2...), puis le navigateur.

Dossiers :
  * l'application et ses bibliotheques : dossier CTR/exe (exe + _internal) ou le fichier .AppImage,
    ctr_editor_config.json (dossier des archives, langue) a cote ;
  * donnees : out/editor (sauvegardes), dossiers de maps a importer (map, map2...), out/ctr_editor.log (journal),
    a cote de l'exe / de l'AppImage, ou dans un dossier parent (2 niveaux) qui a deja des sauvegardes (racine du
    projet) ; Linux, dossier non modifiable : ~/.local/share/ctr-track-editor ;
  * archives du jeu : celles memorisees dans ctr_editor_config.json, sinon la page les demande a l'ouverture ;
    dans l'editeur (guide, menu « ⋯ ») : changer de dossier, pris en compte aussitot (server.choose_archives).
three.js est servi localement (editor/vendor) : l'editeur marche hors ligne.
Sans fenetre possible : l'editeur s'ouvre dans le navigateur, une petite fenetre permet de le fermer.
Fenetre Qt : F12 = outils de developpement ; profil persistant dans out/qt_profile (brouillons de la Creation...) ;
vue 3D sur la carte graphique (liste noire de Chromium ignoree).

Construction : python ctr_tools/editor/build_exe.py (Windows), .build_venv/bin/python ctr_tools/editor/build_appimage.py (Linux)
"""
import os
import socket
import sys
import threading
import traceback

FROZEN = getattr(sys, 'frozen', False)
LINUX = sys.platform.startswith('linux')
HERE = os.path.dirname(os.path.abspath(__file__))


def _app_dir():
    """Dossier de l'application. AppImage : l'exe est dans une image montee en lecture seule (/tmp/.mount_...), on
    prend le dossier du fichier .AppImage ; Linux, dossier non modifiable (/opt...) : ~/.local/share."""

    # chemin du fichier .AppImage, donne par son lanceur
    if os.environ.get('APPIMAGE'):
        d = os.path.dirname(os.path.abspath(os.environ['APPIMAGE']))
    else:
         # exe PyInstaller, sinon racine du projet (sources)
        d = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.dirname(HERE))
    if os.name != 'nt' and not os.access(d, os.W_OK):
        # config et sauvegardes impossibles a cote : dossier utilisateur
        d = os.path.join(os.environ.get('XDG_DATA_HOME') or os.path.expanduser('~/.local/share'), 'ctr-track-editor')
        os.makedirs(d, exist_ok=True)
    return d


APP_DIR = _app_dir()
if FROZEN and LINUX:
    # AppImage : son bac a sable Chromium exige des espaces de noms utilisateur souvent bloques (Ubuntu 24.04,
    # AppArmor) ; la page affichee est uniquement celle du serveur local.
    os.environ.setdefault('PYWEBVIEW_GUI', 'qt')
    os.environ.setdefault('QTWEBENGINE_DISABLE_SANDBOX', '1')
# Chromium de Qt : vue 3D sur la carte graphique, meme si elle est sur sa liste noire (vieux pilotes) ; WebGL
# logiciel (SwiftShader) seulement si la carte ne peut vraiment pas servir, au lieu d'une vue 3D vide
_flags = ['--ignore-gpu-blocklist', '--enable-gpu-rasterization', '--enable-unsafe-swiftshader']
os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = ' '.join([os.environ.get('QTWEBENGINE_CHROMIUM_FLAGS', '')] + _flags).strip()


def _data_dir():
    """Dossier des donnees (out/editor, maps a importer) : celui de l'exe, sinon le premier dossier parent (2 niveaux)
    qui a deja des sauvegardes (exe range dans CTR/exe a la racine du projet)."""
    up1 = os.path.dirname(APP_DIR)
    for d in (APP_DIR, up1, os.path.dirname(up1)):
        if os.path.isdir(os.path.join(d, 'out', 'editor')):
            return d
    return APP_DIR


BASE = _data_dir()
CONFIG = os.path.join(APP_DIR, 'ctr_editor_config.json')
TITLE = 'CTR Track Editor'


def _log_to_file():
    """Sans console (exe fenetre), sys.stdout / sys.stderr valent None : journal dans out/ctr_editor.log."""
    os.makedirs(os.path.join(BASE, 'out'), exist_ok=True)
    f = open(os.path.join(BASE, 'out', 'ctr_editor.log'), 'a', encoding='utf-8', buffering=1)
    sys.stdout = sys.stderr = f


def free_port(preferred=8765):
    for port in (preferred, 0):
        with socket.socket() as s:
            try:
                s.bind(('127.0.0.1', port))
                return s.getsockname()[1]
            except OSError:
                continue
    return 0


def _webview_folder(window, initial):
    """
    Choix de dossier dans la fenetre de l'editeur (appele depuis un fil du serveur : pywebview le transmet a la
    boucle de la fenetre et attend la reponse).
    """
    import webview
    kind = getattr(getattr(webview, 'FileDialog', None), 'FOLDER', None) or webview.FOLDER_DIALOG  # 6.x / 5.x
    r = window.create_file_dialog(kind, directory=initial or '')

    # liste des dossiers choisis ; None si annule
    return r[0] if r else ''


def _qt_window(url):
    """
    Fenetre Qt WebEngine. Leve ImportError sans PySide6 (WebEngine) : main passe alors a pywebview.
    Choix de dossier, telechargements et liens externes sont geres ici ; les <input type=file> par Qt lui-meme.
    """
    from PySide6.QtCore import QObject, Qt, QUrl, Signal, QCoreApplication, QFileInfo
    from PySide6.QtGui import QDesktopServices, QIcon, QKeySequence, QShortcut
    from PySide6.QtWidgets import QApplication, QFileDialog, QFileIconProvider, QMainWindow
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
    import server

    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName(TITLE)

    # profil persistant : localStorage (brouillons de la Creation, reglages de la page) garde d'une session a l'autre
    profile = QWebEngineProfile('ctr-editor', app)
    store = os.path.join(BASE, 'out', 'qt_profile')
    profile.setPersistentStoragePath(store)
    profile.setCachePath(os.path.join(store, 'cache'))
    profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)    # editeur servi en local : toujours les derniers fichiers
    host = QUrl(url).host()

    class Page(QWebEnginePage):
        def acceptNavigationRequest(self, u, kind, main):
            # liens vers internet (aide, depot GitHub...) : navigateur du systeme ; la fenetre reste sur l'editeur
            if u.host() not in (host, 'localhost') and u.scheme() in ('http', 'https'):
                QDesktopServices.openUrl(u)
                return False
            return super().acceptNavigationRequest(u, kind, main)

        def createWindow(self, _type):                 # target=_blank / window.open : meme regle (page jetable)
            return Page(profile, self)

    win = QMainWindow()
    win.setWindowTitle(TITLE)
    if FROZEN:
        win.setWindowIcon(QFileIconProvider().icon(QFileInfo(sys.executable)))
    view = QWebEngineView(win)
    page = Page(profile, view)
    view.setPage(page)
    s, A = page.settings(), QWebEngineSettings.WebAttribute
    for a in (A.WebGLEnabled, A.Accelerated2dCanvasEnabled, A.LocalStorageEnabled, A.JavascriptCanAccessClipboard,
              A.JavascriptCanPaste):
        s.setAttribute(a, True)
    win.setCentralWidget(view)
    win.resize(1440, 900)
    win.setMinimumSize(900, 600)

    # choix de dossier demande par le serveur (autre fil) : execute dans le fil de la fenetre, le serveur attend
    class Dialogs(QObject):
        ask = Signal(str, str, object)
        quit = Signal()

        def __init__(self):
            super().__init__()
            self.ask.connect(self._ask, Qt.ConnectionType.QueuedConnection)
            self.quit.connect(self._quit, Qt.ConnectionType.QueuedConnection)
            self.on_quit = None

        def _quit(self):
            if self.on_quit:
                self.on_quit()

        def _ask(self, title, initial, box):
            try:
                box['path'] = QFileDialog.getExistingDirectory(win, title, initial)
            finally:
                box['done'].set()

    dialogs = Dialogs()

    def folder(title, initial):
        box = {'path': '', 'done': threading.Event()}
        dialogs.ask.emit(title, initial or '', box)
        box['done'].wait()
        return box['path']
    server.FOLDER_DIALOG = folder

    # telechargements (pack exporte...) : enregistrer sous
    def download(d):
        path, _ = QFileDialog.getSaveFileName(win, 'Enregistrer', os.path.join(d.downloadDirectory(), d.downloadFileName()))
        if not path:
            d.cancel()
            return
        d.setDownloadDirectory(os.path.dirname(path))
        d.setDownloadFileName(os.path.basename(path))
        d.accept()
    profile.downloadRequested.connect(download)

    # F12 : outils de developpement dans une fenetre a part
    tools = {}

    def devtools():
        if 'w' not in tools:
            w = QWebEngineView()
            w.setWindowTitle(TITLE + ' — DevTools')
            w.resize(1100, 700)
            page.setDevToolsPage(w.page())
            tools['w'] = w
        tools['w'].show()
        tools['w'].raise_()
    QShortcut(QKeySequence('F12'), win, devtools)

    # fermeture : la page peut demander confirmation (modifications non enregistrees, beforeunload)
    closing = {'ok': False}

    def close_ok():
        closing['ok'] = True
        win.close()
    page.windowCloseRequested.connect(close_ok)
    dialogs.on_quit = close_ok                         # mise a jour : fermeture demandee par le serveur (autre fil)
    server.APP_QUIT = dialogs.quit.emit
    base_close = win.closeEvent

    def close_event(e):
        if closing['ok']:
            tools.get('w') and tools['w'].close()
            base_close(e)
            return
        e.ignore()
        page.triggerAction(QWebEnginePage.WebAction.RequestClose)
    win.closeEvent = close_event

    view.load(QUrl(url))
    win.show()
    app.exec()
    server.FOLDER_DIALOG = None
    server.APP_QUIT = None


def _browser_fallback(url):
    """Editeur dans le navigateur ; petite fenetre tkinter pour le fermer, sinon (tkinter absent) Ctrl+C."""
    import webbrowser
    if FROZEN and LINUX:                                # navigateur du systeme : pas nos bibliotheques (PyInstaller)
        orig = os.environ.pop('LD_LIBRARY_PATH_ORIG', None)
        os.environ.pop('LD_LIBRARY_PATH', None)
        if orig:
            os.environ['LD_LIBRARY_PATH'] = orig
    try:
        import tkinter as tk
    except ImportError:
        webbrowser.open(url)
        print(f"L'éditeur est ouvert dans le navigateur : {url} (Ctrl+C pour le fermer)", flush=True)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            return
    root = tk.Tk()
    root.title(TITLE)
    tk.Label(root, text=f"L'éditeur est ouvert dans ton navigateur :\n{url}", padx=20, pady=12).pack()
    tk.Button(root, text="Fermer l'éditeur", command=root.destroy, padx=12).pack(pady=(0, 12))
    _tk_folder_dialog(root)
    webbrowser.open(url)
    root.mainloop()
    import server
    server.FOLDER_DIALOG = None


def _tk_folder_dialog(root):
    """Choix de dossier ouvert par la petite fenetre (fil principal). Le serveur le demandait depuis son fil avec un
    second tkinter : deux Tk dans deux fils se bloquent, la page attendait sans fin (PC sans WebView2)."""
    import queue
    from tkinter import filedialog
    import server
    asks = queue.Queue()

    def ask(title, initial):
        if LINUX:                                       # zenity / kdialog d'abord, comme avant (processus a part)
            path = server._ask_folder_linux(title, initial)
            if path is not None:
                return path
        done, out = threading.Event(), []
        asks.put((title, initial, done, out))
        done.wait()
        return out[0] if out else None

    def poll():
        try:
            while True:
                title, initial, done, out = asks.get_nowait()
                root.attributes('-topmost', True)
                root.lift()
                try:
                    out.append(filedialog.askdirectory(parent=root, mustexist=True, title=title, initialdir=initial) or '')
                finally:
                    root.attributes('-topmost', False)
                    done.set()
        except queue.Empty:
            pass
        root.after(100, poll)
    server.FOLDER_DIALOG = ask
    root.after(100, poll)


def main():
    sys.path.insert(0, HERE)
    sys.path.insert(0, os.path.dirname(HERE))
    if FROZEN:
        _log_to_file()
    import server
    import updater
    global TITLE
    TITLE = f'CTRNFTE {updater.VERSION}'
    if FROZEN:                                         # mise a jour possible seulement pour l'application empaquetee
        updater.APP_DIR = APP_DIR
        updater.cleanup(APP_DIR)
    # dossier des archives : memorise, sinon demande par la page a l'ouverture (/api/archives, comme le menu ⋯)
    server.configure(out_dir=os.path.join(BASE, 'out', 'editor'), project_dir=BASE, config=CONFIG)
    archives = server.load_config().get('archives')
    if server.valid_archives(archives):
        server.configure(archives=archives)
    port = free_port()
    httpd = server.serve(port)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{port}/'
    print(f'{TITLE} : {url} (archives : {server.ARCHIVES or "a choisir"}, sauvegardes : {server.OUT_DIR})', flush=True)
    if '--server-only' in sys.argv:                    # tests : serveur seul, sans fenetre
        threading.Event().wait()
    try:
        _qt_window(url)
    except ImportError:                                 # pas de Qt WebEngine : pywebview, puis navigateur
        traceback.print_exc()
        _pywebview_or_browser(url)
    except Exception:
        traceback.print_exc()
        server.FOLDER_DIALOG = None
        _browser_fallback(url)
    httpd.shutdown()
    httpd.server_close()
    return 0


def _pywebview_or_browser(url):
    import server
    try:
        import webview
        window = webview.create_window(TITLE, url, width=1440, height=900, min_size=(900, 600), text_select=True)
        if os.name != 'nt':                             # Linux : fenetre de dossier de pywebview (tkinter souvent absent)
            server.FOLDER_DIALOG = lambda title, initial: _webview_folder(window, initial)
        webview.start()
    except Exception:                                   # pas de pywebview / WebView2 : navigateur + petite fenetre
        traceback.print_exc()
        server.FOLDER_DIALOG = None
        _browser_fallback(url)


if __name__ == '__main__':
    sys.exit(main())
