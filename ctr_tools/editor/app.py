"""Editeur de pistes CTR en application Windows (.exe, PyInstaller) : le serveur tourne dans l'application et
l'editeur s'ouvre dans sa propre fenetre (pywebview, moteur Edge WebView2 de Windows).

Dossiers :
  * l'application et ses bibliotheques : dossier CTR/exe (exe + _internal), ctr_editor_config.json (dossier des
    archives, langue) ;
  * donnees : out/editor (sauvegardes), dossiers de maps a importer (map, map2...), out/ctr_editor.log (journal),
    a cote de l'exe, ou dans un dossier parent (2 niveaux) qui a deja des sauvegardes (racine du projet) ;
  * archives du jeu : celles memorisees dans ctr_editor_config.json, sinon la page les demande a l'ouverture ;
    dans l'editeur (guide, menu « ⋯ ») : changer de dossier, pris en compte aussitot (server.choose_archives).
three.js est servi localement (editor/vendor) : l'editeur marche hors ligne.
Sans pywebview (ou WebView2 absent) : l'editeur s'ouvre dans le navigateur, une petite fenetre permet de le fermer.

Construction : python ctr_tools/editor/build_exe.py
"""
import os
import socket
import sys
import threading
import traceback

FROZEN = getattr(sys, 'frozen', False)
HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.dirname(HERE))


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


def main():
    if FROZEN:
        _log_to_file()
    sys.path.insert(0, HERE)
    sys.path.insert(0, os.path.dirname(HERE))
    import server
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
        import webview
        webview.create_window(TITLE, url, width=1440, height=900, min_size=(900, 600), text_select=True)
        webview.start()
    except Exception:                                   # pas de pywebview / WebView2 : navigateur + petite fenetre
        traceback.print_exc()
        import tkinter as tk
        import webbrowser
        webbrowser.open(url)
        root = tk.Tk()
        root.title(TITLE)
        tk.Label(root, text=f"L'éditeur est ouvert dans ton navigateur :\n{url}", padx=20, pady=12).pack()
        tk.Button(root, text="Fermer l'éditeur", command=root.destroy, padx=12).pack(pady=(0, 12))
        root.mainloop()
    httpd.shutdown()
    httpd.server_close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
