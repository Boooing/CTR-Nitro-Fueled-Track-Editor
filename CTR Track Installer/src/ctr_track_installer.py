"""CTR Track Installer : installe des packs de maps (.zip exportes par CTR Track Editor) dans Crash Team Racing
Nitro-Fueled (version PS4 1.21 pour shadPS4), range les pistes du menu du jeu (categories) et remet le jeu d'origine.

Pour les joueurs qui ne veulent pas de l'editeur : meme moteur (ctr_tools : server.py, mappack.py, game_restore.py),
sans l'interface web ni la vue 3D. Dossier de travail et reglages a cote de l'application (data/) ; le registre des
pistes installees est commun avec l'editeur (a cote des archives du jeu) : les deux ne s'effacent pas.

    python "CTR Track Installer/src/ctr_track_installer.py"
"""
import base64
import io
import json
import locale
import os
import re
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

APP = 'CTR Track Installer'
FROZEN = getattr(sys, 'frozen', False)
if FROZEN:                                             # PyInstaller : moteur et donnees dans _internal
    BUNDLE = sys._MEIPASS
    BASE = os.path.dirname(sys.executable)
else:
    HERE = os.path.dirname(os.path.abspath(__file__))
    # moteur : ctr_tools dans le dossier de l'installateur (depot seul), sinon a cote (projet complet)
    TOOLS = os.path.join(os.path.dirname(HERE), 'ctr_tools')
    if not os.path.isdir(TOOLS):
        TOOLS = os.path.join(os.path.dirname(os.path.dirname(HERE)), 'ctr_tools')
    sys.path[:0] = [TOOLS, os.path.join(TOOLS, 'editor')]
    BUNDLE = os.path.join(TOOLS, 'editor')
    BASE = os.path.dirname(HERE)
DATA = os.path.join(BASE, 'data')
CONFIG = os.path.join(DATA, 'ctr_installer_config.json')

import game_restore  # noqa: E402
import progress  # noqa: E402
import server  # noqa: E402

server.APP_NAME = 'installer'
server.configure(out_dir=os.path.join(DATA, 'work'), config=CONFIG)
mappack = server.mappack


# ---- traductions : dictionnaire de l'editeur (editor/i18n.js), cles = textes francais ------------------------
LANGS = ['fr', 'en', 'es', 'it', 'de']
LANG_NAMES = {'fr': 'Français', 'en': 'English', 'es': 'Español', 'it': 'Italiano', 'de': 'Deutsch'}


def _load_i18n():
    out = {}
    try:
        src = open(os.path.join(BUNDLE, 'i18n.js'), encoding='utf-8').read()
    except OSError:
        return out
    for m in re.finditer(r'^\s*("(?:[^"\\]|\\.)*")\s*:\s*(\[.*\]),?\s*$', src, re.M):
        try:
            out[json.loads(m.group(1))] = json.loads(m.group(2))
        except ValueError:
            continue
    return out


I18N = _load_i18n()
LANG = 'fr'


def T(text, /, **kw):
    """Texte traduit (cle = texte francais), {nom} remplaces apres traduction (n'importe quel nom : {s}, {t}...)."""
    if LANG != 'fr':
        tr = I18N.get(text)
        if tr and len(tr) >= LANGS.index(LANG):
            text = tr[LANGS.index(LANG) - 1]
    return text.format(**kw) if kw else text


# ---- utilitaires ---------------------------------------------------------------------------------------
def load_config():
    try:
        return json.load(open(CONFIG, encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def save_config(**values):
    os.makedirs(DATA, exist_ok=True)
    json.dump(dict(load_config(), **values), open(CONFIG, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)


def shadps4_running():
    """shadPS4 ouvert : il garde les archives ouvertes (Windows refuse de les modifier, Linux les lit a moitie)."""
    try:
        if os.name == 'nt':
            out = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'], capture_output=True, text=True,
                                 creationflags=0x08000000).stdout.lower()
        else:
            out = subprocess.run(['ps', '-A', '-o', 'comm='], capture_output=True, text=True).stdout.lower()
        return 'shadps4' in out
    except OSError:
        return False


def zone_of(track):
    return f'octane/{track.lower()}/{track.lower()}'


class Busy(Exception):
    pass


# ---- application -------------------------------------------------------------------------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        global LANG
        cfg = load_config()
        sys_lang = (locale.getlocale()[0] or 'en')[:2].lower()
        LANG = cfg.get('lang') if cfg.get('lang') in LANGS else (sys_lang if sys_lang in LANGS else 'en')
        self.title(APP)
        self.geometry('1060x720')
        self.minsize(860, 560)
        try:
            ttk.Style(self).theme_use('vista' if os.name == 'nt' else 'clam')
        except tk.TclError:
            pass
        self.busy = False
        self.packs = []                                  # packs ouverts (pack_info de mappack)
        self.map_rows = []
        self.layout = []                                 # groupes du menu (copie modifiable)
        self.layout_dirty = False
        self._thumbs = []
        archives = cfg.get('archives')
        if archives and server.valid_archives(archives):
            server.ARCHIVES = os.path.normpath(archives)
        self.build()
        self.after(200, self.start)

    def report_callback_exception(self, exc, val, tb):
        """Erreur dans l'interface : montree (l'application n'a pas de console) et gardee dans data/erreurs.log."""
        import traceback
        text = ''.join(traceback.format_exception(exc, val, tb))
        try:
            os.makedirs(DATA, exist_ok=True)
            open(os.path.join(DATA, 'erreurs.log'), 'a', encoding='utf-8').write(text + '\n')
        except OSError:
            pass
        self.status(T('Erreur : {e}', e=val))
        messagebox.showerror(APP, f'{val}\n\n{text[-1500:]}')

    # -- squelette -------------------------------------------------------------------------------------------
    def build(self):
        for w in self.winfo_children():
            w.destroy()
        top = ttk.Frame(self, padding=(10, 8))
        top.pack(fill='x')
        ttk.Label(top, text='🏁 ' + APP, font=('TkDefaultFont', 13, 'bold')).pack(side='left')
        ttk.Label(top, text='   ' + T('Dossier du jeu :')).pack(side='left')
        self.game_lbl = ttk.Label(top, text=server.ARCHIVES or T('(non choisi)'), foreground='#666')
        self.game_lbl.pack(side='left', padx=(4, 6))
        ttk.Button(top, text=T('📁 Choisir…'), command=self.choose_game).pack(side='left')
        self.lang_var = tk.StringVar(value=LANG_NAMES[LANG])
        lang = ttk.Combobox(top, textvariable=self.lang_var, values=[LANG_NAMES[l] for l in LANGS], width=10, state='readonly')
        lang.pack(side='right')
        lang.bind('<<ComboboxSelected>>', lambda e: self.set_lang())
        ttk.Label(top, text='🌐').pack(side='right', padx=4)

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill='both', expand=True, padx=10)
        self.tab_install = ttk.Frame(self.nb, padding=10)
        self.tab_menu = ttk.Frame(self.nb, padding=10)
        self.tab_backup = ttk.Frame(self.nb, padding=10)
        self.nb.add(self.tab_install, text=T('📦 Installer des maps'))
        self.nb.add(self.tab_menu, text=T('🗂 Piste / catégorie'))
        self.nb.add(self.tab_backup, text=T('🛟 Sauvegarde'))
        self.nb.bind('<<NotebookTabChanged>>', lambda e: self.on_tab())

        bot = ttk.Frame(self, padding=(10, 6))
        bot.pack(fill='x')
        self.prog = ttk.Progressbar(bot, length=220, maximum=1000)
        self.prog.pack(side='right')
        self.status_var = tk.StringVar(value='')
        ttk.Label(bot, textvariable=self.status_var, anchor='w').pack(side='left', fill='x', expand=True)
        self.build_install()
        self.build_menu()
        self.build_backup()

    def set_lang(self):
        global LANG
        LANG = next(k for k, v in LANG_NAMES.items() if v == self.lang_var.get())
        save_config(lang=LANG)
        tab = self.nb.index(self.nb.select())
        self.build()
        self.nb.select(tab)
        if self.packs:
            self.show_pack()

    def status(self, text, frac=None):
        self.status_var.set(text)
        if frac is not None:
            self.prog['value'] = int(frac * 1000)

    def start(self):
        if not server.valid_archives(server.ARCHIVES):
            messagebox.showinfo(APP, T('Choisis le dossier « archives » du jeu installé pour shadPS4 '
                                       '(il contient update.pak et t111_crash_cove.pak).'))
            self.choose_game()
        else:
            self.status(T('Prêt.'))
            self.on_tab()

    def choose_game(self):
        d = filedialog.askdirectory(title=T('Dossier « archives » du jeu'), initialdir=server.ARCHIVES or os.path.expanduser('~'))
        if not d:
            return
        try:
            server.set_archives(d)
        except ValueError as e:
            messagebox.showerror(APP, str(e))
            return
        self.game_lbl.config(text=server.ARCHIVES)
        self.status(T('Dossier du jeu : {p}', p=server.ARCHIVES))
        self.on_tab()

    def on_tab(self):
        if not server.valid_archives(server.ARCHIVES) or self.busy:
            return
        tab = self.nb.index(self.nb.select())
        if tab == 1:
            self.load_menu()
        elif tab == 2:
            self.load_backup()
        elif tab == 0 and self.packs:
            self.refresh_targets()

    # -- operations longues : fil a part, barre de progression lue dans le moteur -------------------------------------
    def run(self, label, fn, done=None, game=True):
        if self.busy:
            return
        if not server.valid_archives(server.ARCHIVES):
            messagebox.showwarning(APP, T('Choisis d\'abord le dossier du jeu.'))
            return
        if game and shadps4_running() and not messagebox.askyesno(APP, T('shadPS4 semble ouvert : ferme-le avant de modifier '
                                                                     'le jeu (il garde les archives ouvertes). Continuer quand même ?')):
            return
        self.busy = True
        self.config(cursor='watch')
        result = {}

        def work():
            progress.begin(label)
            try:
                with server.WRITE_LOCK:
                    result['value'] = fn()
            except Exception as e:  # noqa: BLE001 - montre a l'utilisateur
                result['error'] = e
            finally:
                progress.end()

        th = threading.Thread(target=work, daemon=True)
        th.start()

        def poll():
            p = progress.get()
            if th.is_alive():
                if p.get('active'):
                    self.status(f"{label} — {p.get('step') or ''} ({p.get('elapsed', 0):.0f} s)", p.get('frac', 0))
                self.after(300, poll)
                return
            self.busy = False
            self.config(cursor='')
            self.prog['value'] = 0
            if 'error' in result:
                self.status(T('Erreur : {e}', e=result['error']))
                messagebox.showerror(APP, f"{label}\n\n{result['error']}")
            elif done:
                done(result.get('value'))
        self.after(300, poll)

    # ======== onglet « Installer des maps » =====================================================================
    def build_install(self):
        f = self.tab_install
        head = ttk.Frame(f)
        head.pack(fill='x')
        ttk.Button(head, text=T('📂 Ouvrir des packs de maps (.zip)…'), command=self.open_pack).pack(side='left')
        self.clear_btn = ttk.Button(head, text=T('✖ Vider la liste'), command=self.clear_packs, state='disabled')
        self.clear_btn.pack(side='left', padx=(6, 0))
        self.pack_lbl = ttk.Label(head, text=T('Aucun pack ouvert.'), foreground='#666')
        self.pack_lbl.pack(side='left', padx=10)
        self.install_btn = ttk.Button(head, text=T('🎮 Installer dans le jeu'), command=self.install_maps, state='disabled')
        self.install_btn.pack(side='right')
        ttk.Label(f, text=T('Pour chaque map : nouvelle catégorie, nouvelle map dans une catégorie existante, ou remplacer une map '
                            'du jeu. Une nouvelle map est une copie vierge de Crash Cove ; les pistes du jeu ne changent pas.'),
                  foreground='#555', wraplength=980, justify='left').pack(fill='x', pady=(8, 6))
        canvas = self.maps_canvas = tk.Canvas(f, highlightthickness=0)
        sb = ttk.Scrollbar(f, orient='vertical', command=canvas.yview)
        self.maps_box = ttk.Frame(canvas)
        self.maps_box.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=self.maps_box, anchor='nw')
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

        def wheel(e):
            # liste plus courte que la fenetre (ou vide) : pas de defilement, sinon la vue partait sous la liste et
            # les maps ouvertes ensuite restaient invisibles
            if self.maps_box.winfo_reqheight() > canvas.winfo_height():
                canvas.yview_scroll(int(-e.delta / 120), 'units')
        canvas.bind_all('<MouseWheel>', wheel)

    def open_pack(self):
        paths = filedialog.askopenfilenames(title=T('Packs de maps (.zip) — plusieurs possibles'), filetypes=[('Pack .zip', '*.zip')])
        if not paths:
            return

        def load():
            packs, bad = [], []
            for p in paths:
                try:
                    packs.append(mappack.save_upload(open(p, 'rb').read(), os.path.basename(p)))
                except Exception as e:  # noqa: BLE001 - zip illisible : signale, les autres sont gardes
                    bad.append(f'{os.path.basename(p)} : {e}')
            return packs, bad, server.menu_layout_info(), server.list_tracks()
        self.run(T('Lecture des packs'), load, self.pack_loaded, game=False)

    def pack_loaded(self, v):
        packs, bad, self.menu_cache, self.tracks = v
        # meme pack rouvert : remplace l'ancien ; les packs deja ouverts restent
        self.packs = [p for p in self.packs if p['pack'] not in {q['pack'] for q in packs}] + packs
        self.show_pack()
        self.status(T('{p} pack(s), {n} map(s).', p=len(self.packs), n=sum(len(p['maps']) for p in self.packs)))
        if bad:
            messagebox.showwarning(APP, T('Packs non lus :') + '\n\n' + '\n'.join(bad))

    def clear_packs(self):
        self.packs = []
        self.show_pack()

    def _targets(self):
        """(categories [(cle, nom)], pistes [(id, nom)]) pour les choix."""
        menu = self.menu_cache
        cats = [(g['key'], g.get('title') or g.get('game_title') or g['key']) for g in menu['groups']]
        names = {lv['track'] or lv['zone']: lv['name'] for g in menu['groups'] for lv in g['levels']}
        tracks = [(t, f"{names.get(t) or names.get(zone_of(t)) or t}  ({t})") for t in self.tracks]
        return cats, tracks

    def refresh_targets(self):
        def load():
            return server.menu_layout_info(), server.list_tracks()

        def done(v):
            self.menu_cache, self.tracks = v
            self.show_pack()
        self.run(T('Lecture du menu du jeu'), load, done, game=False)

    def show_pack(self):
        for w in self.maps_box.winfo_children():
            w.destroy()
        self._thumbs, self.map_rows = [], []
        n = sum(len(p['maps']) for p in self.packs)
        self.pack_lbl.config(text=T('{p} pack(s) ouvert(s) — {n} map(s)', p=len(self.packs), n=n) if self.packs else T('Aucun pack ouvert.'))
        self.clear_btn.config(state='normal' if self.packs else 'disabled')
        if not self.packs:
            self.install_btn.config(state='disabled')
            return
        cats, tracks = self._targets()
        for info, m in [(p, m) for p in self.packs for m in p['maps']]:
            row = ttk.LabelFrame(self.maps_box, text=f"{m['title']}   ({info['pack']})", padding=8)
            row.pack(fill='x', pady=4, padx=2)
            img = None
            if m.get('preview'):
                try:
                    from PIL import Image, ImageTk
                    im = Image.open(io.BytesIO(base64.b64decode(m['preview'].split(',', 1)[1])))
                    im.thumbnail((200, 112))
                    img = ImageTk.PhotoImage(im)
                    self._thumbs.append(img)
                except Exception:  # noqa: BLE001 - apercu facultatif
                    img = None
            ttk.Label(row, image=img, text='' if img else T('(pas d\'image)'), width=0 if img else 18).grid(row=0, column=0, rowspan=4, sticky='nw', padx=(0, 12))
            use = tk.BooleanVar(value=True)
            ttk.Checkbutton(row, text=T('Installer cette map'), variable=use).grid(row=0, column=1, sticky='w')
            ttk.Label(row, text=T('Créée sur {t} · {s} section(s) · {k} modèle(s) importé(s)',
                                  t=m.get('source_track', '?'), s=m.get('sections', 0), k=m.get('models', 0)),
                      foreground='#666').grid(row=0, column=2, columnspan=3, sticky='w', padx=6)
            how = tk.StringVar(value='newcat')
            newcat = tk.StringVar(value=info['pack'].rsplit('.', 1)[0].replace('_', ' '))
            cat = tk.StringVar(value=cats[-1][1] if cats else '')
            rep = tk.StringVar(value=next((n for t, n in tracks if t.lower() == str(m.get('source_track', '')).lower()), tracks[0][1] if tracks else ''))
            ttk.Radiobutton(row, text=T('Nouvelle map dans une nouvelle catégorie :'), variable=how, value='newcat').grid(row=1, column=1, sticky='w')
            ttk.Entry(row, textvariable=newcat, width=34).grid(row=1, column=2, sticky='w', padx=6)
            ttk.Radiobutton(row, text=T('Nouvelle map dans la catégorie :'), variable=how, value='cat').grid(row=2, column=1, sticky='w')
            ttk.Combobox(row, textvariable=cat, values=[n for _, n in cats], width=32, state='readonly').grid(row=2, column=2, sticky='w', padx=6)
            ttk.Radiobutton(row, text=T('Remplacer la map :'), variable=how, value='replace').grid(row=3, column=1, sticky='w')
            ttk.Combobox(row, textvariable=rep, values=[n for _, n in tracks], width=44, state='readonly').grid(row=3, column=2, columnspan=3, sticky='w', padx=6)
            self.map_rows.append({'map': m, 'pack': info['pack'], 'use': use, 'how': how, 'newcat': newcat, 'cat': cat, 'rep': rep})
        self.install_btn.config(state='normal' if self.map_rows else 'disabled')
        self.maps_box.update_idletasks()
        self.maps_canvas.configure(scrollregion=(0, 0, self.maps_box.winfo_reqwidth(), self.maps_box.winfo_reqheight()))
        self.maps_canvas.yview_moveto(0)

    def install_maps(self):
        cats, tracks = self._targets()
        jobs = []
        for r in self.map_rows:
            if not r['use'].get():
                continue
            how = r['how'].get()
            job = {'map': r['map'], 'pack': r['pack'], 'how': how}
            if how == 'newcat':
                job['category'] = r['newcat'].get().strip() or 'Custom'
            elif how == 'cat':
                job['key'] = next((k for k, n in cats if n == r['cat'].get()), None)
                if not job['key']:
                    messagebox.showwarning(APP, T('Choisis une catégorie pour « {m} ».', m=r['map']['title']))
                    return
            else:
                job['target'] = next((t for t, n in tracks if n == r['rep'].get()), None)
                if not job['target']:
                    messagebox.showwarning(APP, T('Choisis la map à remplacer pour « {m} ».', m=r['map']['title']))
                    return
            jobs.append(job)
        if not jobs:
            return
        targets = [j['target'] for j in jobs if j['how'] == 'replace']
        if len(set(targets)) != len(targets):
            messagebox.showwarning(APP, T('Deux maps remplacent la même piste : choisis une piste différente pour chacune.'))
            return
        lines = []
        for j in jobs:
            what = {'newcat': T('nouvelle catégorie « {c} »', c=j.get('category')),
                    'cat': T('catégorie « {c} »', c=next((n for k, n in cats if k == j.get('key')), '')),
                    'replace': T('remplace {t}', t=j.get('target'))}[j['how']]
            lines.append(f"• {j['map']['title']} → {what}")
        if not messagebox.askyesno(APP, T('Installer dans le jeu ?') + '\n\n' + '\n'.join(lines) + '\n\n' +
                                   T('Compte 1 à 5 minutes par map. Ferme shadPS4 avant.')):
            return

        def work():
            results = []
            created_cats = {}
            for k, j in enumerate(jobs):
                m = j['map']
                with progress.span(k / len(jobs), (k + 1) / len(jobs), m['title']):
                    if j['how'] in ('newcat', 'cat'):
                        key = j.get('key')
                        if j['how'] == 'newcat':
                            key = created_cats.get(j['category'])
                            if not key:
                                info = server.menu_layout_info()
                                groups = [{'id': g['id'], 'key': g['key'], 'title': g['title'],
                                           'levels': [lv['zone'] for lv in g['levels']]} for g in info['groups']]
                                key = server.custom_category.new_key(groups)
                                groups.append({'id': None, 'key': key, 'title': j['category'], 'levels': []})
                                with progress.span(0.0, 0.05, T('nouvelle catégorie')):
                                    server.menu_layout_save({'groups': groups})
                                created_cats[j['category']] = key
                        with progress.span(0.05, 0.4, T('nouvelle piste (copie de Crash Cove)')):
                            target = server.menu_track_create({'name': m['title'], 'group': key, 'blank': True})['track']
                    else:
                        target = j['target']
                    with progress.span(0.4, 0.85, T('import de la map')):
                        res = mappack.import_pack({'pack': j['pack'], 'maps': [{'id': m['folder'], 'target': target}]})['results'][0]
                    with progress.span(0.85, 1.0, T('installation dans le jeu')):
                        server.install_track(target)
                    server.set_registry_info(target, title=m['title'], pack=j['pack'])
                    results.append({'title': m['title'], 'target': target, 'report': res['report'], 'regen_ai': res['regen_ai']})
            return results

        def done(results):
            msg = []
            for r in results:
                msg.append(T('✔ {m} installée sur {t}', m=r['title'], t=r['target']))
                if r['regen_ai']:
                    msg.append('   ' + T('⚠ les IA de cette piste sont à régénérer dans l\'éditeur (piste à plusieurs tracés)'))
            self.status(T('{n} map(s) installée(s).', n=len(results)))
            messagebox.showinfo(APP, '\n'.join(msg) + '\n\n' + T('Lance le jeu : les maps sont dans le menu des courses.'))
            self.refresh_targets()
        self.run(T('Installation des maps'), work, done)

    # ======== onglet « Piste / catégorie » =======================================================================
    def build_menu(self):
        f = self.tab_menu
        ttk.Label(f, text=T('Catégories du menu des courses et leurs pistes. Les changements sont installés dans le jeu '
                            'avec « Enregistrer le menu ».'), foreground='#555', wraplength=980, justify='left').pack(fill='x')
        body = ttk.Frame(f)
        body.pack(fill='both', expand=True, pady=8)
        # boutons places d'abord (a droite) : la liste prend le reste sans les ecraser
        side = ttk.Frame(body, padding=(10, 0))
        side.pack(side='right', fill='y')
        self.tree = ttk.Treeview(body, columns=('info',), show='tree headings', selectmode='browse')
        self.tree.heading('#0', text=T('Catégorie / piste'))
        self.tree.heading('info', text='')
        self.tree.column('#0', width=380, minwidth=200, stretch=True)
        self.tree.column('info', width=200, minwidth=120, stretch=False)
        sb = ttk.Scrollbar(body, orient='vertical', command=self.tree.yview)
        sb.pack(side='right', fill='y')
        self.tree.pack(side='left', fill='both', expand=True)
        self.tree.configure(yscrollcommand=sb.set)
        for text, cmd in ((T('➕ Nouvelle catégorie…'), self.cat_new), (T('✏ Renommer la catégorie…'), self.cat_rename),
                          (T('🗑 Supprimer la catégorie (vide)'), self.cat_delete), (None, None),
                          (T('⬆ Monter'), lambda: self.move(-1)), (T('⬇ Descendre'), lambda: self.move(1)),
                          (T('↪ Déplacer la piste vers…'), self.track_move), (None, None),
                          (T('🆕 Nouvelle piste vierge…'), self.track_new), (T('🗑 Supprimer la piste créée…'), self.track_delete),
                          (None, None), (T('💾 Enregistrer le menu'), self.menu_save), (T('↺ Annuler les changements'), self.load_menu)):
            if text is None:
                ttk.Separator(side).pack(fill='x', pady=6)
            else:
                ttk.Button(side, text=text, command=cmd).pack(fill='x', pady=2)

    def load_menu(self):
        def done(info):
            self.layout = [{'id': g['id'], 'key': g['key'], 'title': g['title'], 'game_title': g['game_title'],
                            'levels': [dict(lv) for lv in g['levels']]} for g in info['groups']]
            self.layout_dirty = False
            self.render_menu()
            self.status(T('Menu du jeu lu.'))
        self.run(T('Lecture du menu du jeu'), server.menu_layout_info, done, game=False)

    def render_menu(self, select=None):
        self.tree.delete(*self.tree.get_children())
        for gi, g in enumerate(self.layout):
            name = g['title'] or g['game_title'] or g['key']
            info = T('catégorie du jeu') + (T(' (renommée)') if g['id'] and g['title'] else '') if g['id'] else T('catégorie ajoutée')
            gid = self.tree.insert('', 'end', iid=f'g{gi}', text=f'📁 {name}', values=(f"{info} · {len(g['levels'])}",), open=True)
            for li, lv in enumerate(g['levels']):
                self.tree.insert(gid, 'end', iid=f'g{gi}l{li}', text=('🆕 ' if lv['track'] else '🏁 ') + lv['name'],
                                 values=(T('piste créée') if lv['track'] else T('piste du jeu'),))
        if select and self.tree.exists(select):
            self.tree.selection_set(select)
            self.tree.see(select)
        self.status(T('Menu modifié : « Enregistrer le menu » pour l\'installer.') if self.layout_dirty else '')

    def _sel(self):
        s = self.tree.selection()
        if not s:
            return None, None
        m = re.match(r'^g(\d+)(?:l(\d+))?$', s[0])
        return int(m.group(1)), (int(m.group(2)) if m.group(2) else None)

    def _changed(self, select=None):
        self.layout_dirty = True
        self.render_menu(select)

    def cat_new(self):
        name = simpledialog.askstring(APP, T('Nom de la nouvelle catégorie :'), parent=self)
        if name and name.strip():
            self.layout.append({'id': None, 'key': server.custom_category.new_key(self.layout), 'title': name.strip(),
                                'game_title': None, 'levels': []})
            self._changed(f'g{len(self.layout) - 1}')

    def cat_rename(self):
        gi, li = self._sel()
        if gi is None or li is not None:
            messagebox.showinfo(APP, T('Sélectionne une catégorie.'))
            return
        g = self.layout[gi]
        name = simpledialog.askstring(APP, T('Nouveau nom (vide : nom du jeu) :'), initialvalue=g['title'] or g['game_title'] or '', parent=self)
        if name is None:
            return
        g['title'] = name.strip() or (None if g['id'] else 'Custom')
        self._changed(f'g{gi}')

    def cat_delete(self):
        gi, li = self._sel()
        if gi is None or li is not None:
            messagebox.showinfo(APP, T('Sélectionne une catégorie.'))
            return
        g = self.layout[gi]
        if g['id'] or g['levels']:
            messagebox.showinfo(APP, T('Seule une catégorie ajoutée et vide peut être supprimée (déplace d\'abord ses pistes).'))
            return
        del self.layout[gi]
        self._changed()

    def move(self, d):
        gi, li = self._sel()
        if gi is None:
            return
        if li is None:
            j = gi + d
            if 0 <= j < len(self.layout):
                self.layout[gi], self.layout[j] = self.layout[j], self.layout[gi]
                self._changed(f'g{j}')
            return
        lv = self.layout[gi]['levels']
        j = li + d
        if 0 <= j < len(lv):
            lv[li], lv[j] = lv[j], lv[li]
            self._changed(f'g{gi}l{j}')

    def track_move(self):
        gi, li = self._sel()
        if li is None:
            messagebox.showinfo(APP, T('Sélectionne une piste.'))
            return
        names = [g['title'] or g['game_title'] or g['key'] for g in self.layout]
        dlg = tk.Toplevel(self)
        dlg.title(APP)
        dlg.transient(self)
        ttk.Label(dlg, text=T('Déplacer « {t} » vers :', t=self.layout[gi]['levels'][li]['name']), padding=10).pack()
        var = tk.StringVar(value=names[gi])
        ttk.Combobox(dlg, textvariable=var, values=names, state='readonly', width=40).pack(padx=10)

        def ok():
            j = names.index(var.get())
            lv = self.layout[gi]['levels'].pop(li)
            self.layout[j]['levels'].append(lv)
            dlg.destroy()
            self._changed(f"g{j}l{len(self.layout[j]['levels']) - 1}")
        ttk.Button(dlg, text='OK', command=ok).pack(pady=10)
        dlg.grab_set()

    def menu_save(self):
        groups = [{'id': g['id'], 'key': g['key'], 'title': g['title'], 'levels': [lv['zone'] for lv in g['levels']]}
                  for g in self.layout]

        def done(info):
            self.status(T('Menu installé dans le jeu.'))
            self.load_menu()
        self.run(T('Installation du menu'), lambda: server.menu_layout_save({'groups': groups}), done)

    def track_new(self):
        if self.layout_dirty and not messagebox.askyesno(APP, T('Le menu modifié n\'est pas enregistré : il sera relu. Continuer ?')):
            return
        gi, _ = self._sel()
        key = self.layout[gi]['key'] if gi is not None else None
        name = simpledialog.askstring(APP, T('Nom de la nouvelle piste (copie vierge de Crash Cove, prête pour une map) :'),
                                      initialvalue='Custom Track', parent=self)
        if not name:
            return
        self.run(T('Nouvelle piste'), lambda: server.menu_track_create({'name': name.strip(), 'group': key, 'blank': True}),
                 lambda r: (self.status(T('Piste créée : {t}', t=r['track'])), self.load_menu()))

    def track_delete(self):
        gi, li = self._sel()
        lv = self.layout[gi]['levels'][li] if li is not None else None
        if not lv or not lv['track']:
            messagebox.showinfo(APP, T('Sélectionne une piste créée (🆕) : les pistes du jeu ne peuvent pas être supprimées.'))
            return
        if not messagebox.askyesno(APP, T('Supprimer définitivement la piste « {t} » ({id}) et ses archives ?', t=lv['name'], id=lv['track'])):
            return
        self.run(T('Suppression de la piste'), lambda: server.menu_track_delete({'track': lv['track']}),
                 lambda r: (self.status(T('Piste supprimée.')), self.load_menu()))

    # ======== onglet « Sauvegarde » ==============================================================================
    def build_backup(self):
        f = self.tab_backup
        ttk.Label(f, text=T('Chaque archive modifiée garde une sauvegarde de son état d\'origine (à côté d\'elle, .ctrmod) : '
                            'une map peut être désinstallée, et tout le jeu remis d\'origine.'),
                  foreground='#555', wraplength=980, justify='left').pack(fill='x')
        body = ttk.Frame(f)
        body.pack(fill='both', expand=True, pady=8)
        # boutons places d'abord (a droite) : la liste prend le reste sans les ecraser
        side = ttk.Frame(body, padding=(10, 0))
        side.pack(side='right', fill='y')
        ttk.Button(side, text=T('↩ Désinstaller la map'), command=self.uninstall_one).pack(fill='x', pady=2)
        ttk.Button(side, text=T('↻ Actualiser'), command=self.load_backup).pack(fill='x', pady=2)
        ttk.Separator(side).pack(fill='x', pady=10)
        ttk.Button(side, text=T('⚠ Remettre le jeu d\'origine…'), command=self.restore_all).pack(fill='x', pady=2)
        self.btree = ttk.Treeview(body, columns=('by', 'date'), show='tree headings', selectmode='browse')
        self.btree.heading('#0', text=T('Map installée'))
        self.btree.heading('by', text=T('Installée par'))
        self.btree.heading('date', text=T('Date'))
        self.btree.column('#0', width=360, minwidth=200, stretch=True)
        self.btree.column('by', width=160, minwidth=100, stretch=False)
        self.btree.column('date', width=130, minwidth=100, stretch=False)
        self.btree.pack(side='left', fill='both', expand=True)

    def load_backup(self):
        def load():
            return game_restore.restore_plan(server.ARCHIVES, LANG), server.read_registry()

        def done(v):
            plan, reg = v
            self.backup_plan = plan
            self.btree.delete(*self.btree.get_children())
            for it in plan['installed']:
                e = reg.get(it['track'], {})
                by = {'installer': APP, 'editor': 'CTR Track Editor'}.get(e.get('by'), T('éditeur (ancien)'))
                self.btree.insert('', 'end', iid=it['track'], text=f"{e.get('title') or it['track']}  ({it['track']})",
                                  values=(by, e.get('date') or ''))
            self.status(T('{n} map(s) installée(s), {a} archive(s) modifiée(s).', n=len(plan['installed']), a=len(plan['archives'])))
        self.run(T('Lecture des sauvegardes'), load, done, game=False)

    def uninstall_one(self):
        s = self.btree.selection()
        if not s:
            messagebox.showinfo(APP, T('Sélectionne une map installée.'))
            return
        t = s[0]
        if not messagebox.askyesno(APP, T('Désinstaller {t} ? Ses archives reviennent à l\'origine ; les autres maps restent.', t=t)):
            return
        self.run(T('Désinstallation'), lambda: server.uninstall_track(next(x for x in server.list_tracks() if x.lower() == t.lower())),
                 lambda r: self.load_backup())

    def restore_all(self):
        def done(plan):
            if plan['nothing']:
                messagebox.showinfo(APP, T('Le jeu est déjà d\'origine : rien à remettre.'))
                return
            self.confirm_restore(plan)
        self.run(T('Analyse'), lambda: game_restore.restore_plan(server.ARCHIVES, LANG), done, game=False)

    def confirm_restore(self, plan):
        dlg = tk.Toplevel(self)
        dlg.title(T('Remettre le jeu d\'origine'))
        dlg.transient(self)
        dlg.geometry('640x560')
        ttk.Label(dlg, text=T('⚠ Tout ce qui a été installé ou créé sera supprimé. Ce n\'est pas annulable.'),
                  font=('TkDefaultFont', 11, 'bold'), foreground='#b00', padding=10, wraplength=600).pack(fill='x')
        txt = tk.Text(dlg, wrap='word', height=20)
        txt.pack(fill='both', expand=True, padx=10)

        def section(title, items):
            if items:
                txt.insert('end', title + '\n', 'h')
                for i in items:
                    txt.insert('end', '   • ' + i + '\n')
                txt.insert('end', '\n')
        txt.tag_configure('h', font=('TkDefaultFont', 10, 'bold'))
        section(T('Pistes créées supprimées (avec leurs archives) :'), [f"{c['display']} ({c['id']})" for c in plan['created']])
        section(T('Catégories remises comme dans le jeu :'), [c['title'] for c in plan['categories']])
        section(T('Maps installées retirées :'), [f"{i['title'] or i['track']} ({i['track']})" for i in plan['installed']])
        section(T('Archives remises d\'origine :'), plan['archives'])
        section(T('Vidéos du menu remises :'), plan['videos'])
        if plan['chunks']:
            section(T('Liste des fichiers du jeu :'), ['chunks.igx'])
        section(T('⚠ Problèmes (non touchés) :'), plan['problems'])
        txt.insert('end', T('Pour retrouver une map ensuite, il faudra réimporter son pack .zip : garde tes packs. '
                            'Ferme shadPS4 avant de continuer.'))
        txt.config(state='disabled')
        bar = ttk.Frame(dlg, padding=10)
        bar.pack(fill='x')

        def go():
            dlg.destroy()
            self.run(T('Retour au jeu d\'origine'), server.restore_game_all,
                     lambda r: (messagebox.showinfo(APP, '\n'.join(r['report'][-12:])), self.load_backup()))
        ttk.Button(bar, text=T('Annuler'), command=dlg.destroy).pack(side='right', padx=4)
        ttk.Button(bar, text=T('Tout supprimer et remettre le jeu d\'origine'), command=go).pack(side='right')
        dlg.grab_set()


def main():
    os.makedirs(DATA, exist_ok=True)
    App().mainloop()


if __name__ == '__main__':
    main()
