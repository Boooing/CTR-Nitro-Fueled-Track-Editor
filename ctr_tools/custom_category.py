"""Menu de selection des pistes : categories (renommer, creer, ranger les pistes) et pistes creees par track_clone.

Le menu (ui/Octane_LevelSelect_Proto.igz, update2.pak) range les pistes de course en groupes :
CGuiListItemPopulatorOctaneLevelSelect._levelData = liste de 7 CGuiOctaneLevelSelectDataList (N. Sanity Beach,
Gemstone Valley, Lost Ruins, Glacier Park, Citadel City, CNK, bonus), chacune = CGuiOctaneLevelSelectData
(_levelName = nom de zone « octane/t111_crash_cove/t111_crash_cove ») + titre _categoryName. Les titres du jeu
viennent des fichiers de langue (Octane_LevelSelect_Proto_<langue>.lng : igLocalizedStringData dont le handle vise
l'objet racine du groupe) ; un groupe ajoute n'y figure pas : son titre est ecrit directement dans le champ (valide
en jeu). Renommer un groupe du jeu = changer sa chaine dans les 4 .lng.

Disposition (etat <archives>/ctr_custom_category.json, cle 'layout') : [{id: nom racine d'un groupe du jeu ou None,
key: identifiant stable, title: titre (None = celui du jeu), levels: [zones]}] dans l'ordre du menu ; un groupe
vide n'est pas mis dans le menu. Pistes creees : cle 'tracks' [{id, source, display, paks}]. Installe dans update2.pak
en gardant les fichiers deja installes ; l'editeur (server._rewrite) le reprend a chaque reecriture de update2.pak.
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # lance avec « python -I »
import pak_tool  # noqa: E402
from igz import IgzFile  # noqa: E402

PROTO = 'ui/Octane_LevelSelect_Proto.igz'
ARCHIVE = 'update2.pak'
PREFIX = 'LevelList_listItemPopulator_levelData'
TITLE = 'Custom'
DEFAULT_LEVELS = ['octane/t111_crash_cove/t111_crash_cove']
GUI_DATA = 'loosedata/guisystemdata.igz'                     # liste globale des pistes de course du jeu
RACE_LISTS = 'GuiSystemData_raceAreaLevelDataList'
LNG_LANGS = ('en', 'fr', 'mx', 'pt')
UI_LANG = {'fr': 'fr', 'en': 'en', 'es': 'mx', 'it': 'en', 'de': 'en', 'pt': 'pt'}   # langue editeur -> .lng


def proto_lng(lang):
    return f'ui/Octane_LevelSelect_Proto_{lang}.lng'


def state_path(archives):
    return os.path.join(archives, 'ctr_custom_category.json')


def read_state(archives):
    p = state_path(archives)
    return json.load(open(p)) if os.path.exists(p) else None


def _slug(level):
    return ''.join(w.capitalize() for w in level.rsplit('/', 1)[-1].split('_')[1:]) or 'Level'


def _detached_clone(z, model_list):
    """Copie d'un groupe sans ses items (le clone pointe sur ceux du modele : set_list les « libererait »)."""
    new = z.clone_object(model_list)
    struct.pack_into('<II', *z._loc(new + 0x0C), 0, 0)
    struct.pack_into('<I', *z._loc(new + 0x18), 0)
    z.set_ptr(new + 0x20, None)
    return new


def _level_items(z, roots):
    """{zone minuscule: item} des pistes du menu d'origine."""
    out = {}
    for lst in z.object_list(roots[PREFIX]):
        for it in z.object_list(lst):
            out.setdefault(z.dump_object(it)['_levelName'].lower(), it)
    return out


def original_layout(data):
    """Disposition du menu d'origine."""
    z = IgzFile(data)
    names = {o: n for n, o in z.root_objects()}
    return [{'id': names[lst], 'key': names[lst], 'title': None,
             'levels': [z.dump_object(it)['_levelName'] for it in z.object_list(lst)]}
            for lst in z.object_list(dict(z.root_objects())[PREFIX])]


def build_proto(data, layout):
    """Proto d'origine -> menu de la disposition : groupes du jeu reutilises (dans le nouvel ordre), groupes ajoutes
    clones de Gemstone Valley, items du jeu deplaces tels quels, items des pistes ajoutees clones de Mystery Caves."""
    z = IgzFile(data)
    roots = dict(z.root_objects())
    items = _level_items(z, roots)
    model_list, model_item = roots[PREFIX + '_GemstoneValley'], roots[PREFIX + '_MysteryCaves']
    groups, pairs, k = [], [], 0
    for g in layout:
        if not g['levels']:
            continue                                     # groupe vide : pas dans le menu
        if g.get('id') in roots:
            lst = roots[g['id']]
        else:
            k += 1
            lst = _detached_clone(z, model_list)
            pairs.append((lst, f'{PREFIX}_Custom{k}'))
        its = []
        for level in g['levels']:
            it = items.get(level.lower())
            if it is None:
                it = items[level.lower()] = z.clone_object(model_item)
                z.set_string_ref(z.find_field(it, '_levelName')[0], level)
                pairs.append((it, f'{PREFIX}_Custom{k}_{_slug(level)}'))
            its.append(it)
        z.set_list(lst, its)
        if g.get('id') not in roots:
            # chaines IGZ ecrites octet pour octet (latin-1), le jeu les lit en UTF-8 : sinon « Été » s'affiche mal
            z.set_string_ref(z.find_field(lst, '_categoryName')[0], (g.get('title') or TITLE).encode('utf-8').decode('latin1'))
        groups.append(lst)
    z.set_list(roots[PREFIX], groups)
    if pairs:
        z.add_roots(pairs)
    z.compact()
    return z.to_bytes()


def categories(data):
    """[(titre, [niveaux])] des groupes de course du menu (controle)."""
    z = IgzFile(data)
    groups = dict(z.root_objects())[PREFIX]
    out = []
    for lst in z.object_list(groups):
        d = z.dump_object(lst)
        out.append((d.get('_categoryName'), [z.dump_object(it)['_levelName'] for it in z.object_list(lst)]))
    return out


# -- titres (.lng du menu) -------------------------------------------------------------------------------------
def _title_entries(z):
    """{nom racine du groupe: offset du champ _string}."""
    so = next(fo for fo, (n, _) in z.fields_of('igLocalizedStringData').items() if n == '_string')
    ho = next(fo for fo, (n, _) in z.fields_of('igLocalizedStringData').items() if n == '_object')
    out = {}
    for o, t in z.objects.items():
        if t == 'igLocalizedStringData' and z.is_handle(o + ho):
            out[z.handle(o + ho).split('::', 1)[-1]] = o + so
    return out


def game_titles(archives, lang='fr'):
    """{nom racine: titre du jeu} dans la langue (en, fr, mx, pt)."""
    z = IgzFile(pak_tool.read_latest(archives, proto_lng(lang))[0])
    return {n: z.string(z.u32(off)).encode('latin1').decode('utf-8', 'replace') for n, off in _title_entries(z).items()}


def write_titles(data, titles):
    z = IgzFile(data)
    ent = _title_entries(z)
    for n, title in titles.items():
        if n in ent:
            z.set_string_ref(ent[n], title.encode('utf-8').decode('latin1'))
    return z.to_bytes()


# -- liste globale des pistes de course (guisystemdata) --------------------------------------------------------
def add_race_levels(data, levels):
    """guisystemdata d'origine -> avec nos zones dans la liste globale des pistes de course (dernier groupe, comme
    les pistes du Grand Prix T501-T508 ajoutees par le jeu)."""
    z = IgzFile(data)
    roots = dict(z.root_objects())
    names = {o: n for n, o in roots.items()}
    group = z.object_list(roots[RACE_LISTS])[-1]
    items = z.object_list(group)
    have = {z.dump_object(it)['_levelName'].lower() for it in items}
    pairs = []
    for level in levels:
        if level.lower() in have:
            continue
        it = z.clone_object(items[0])
        z.set_string_ref(z.find_field(it, '_levelName')[0], level)
        pairs.append((it, f'{names[group]}_{len(items) + len(pairs)}'))
    if not pairs:
        return data
    z.set_list(group, items + [p[0] for p in pairs])
    z.add_roots(pairs)
    z.compact()
    return z.to_bytes()


def race_levels(data):
    """[niveaux] de la liste globale des pistes de course (controle)."""
    z = IgzFile(data)
    groups = dict(z.root_objects())[RACE_LISTS]
    return [z.dump_object(it)['_levelName'] for g in z.object_list(groups) for it in z.object_list(g)]


# -- disposition -----------------------------------------------------------------------------------------------
def _original(archives):
    return original_layout(pak_tool.read_latest(archives, PROTO)[0])     # version d'origine, meme si update2 est modde


def current_layout(archives, st=None):
    """Disposition en vigueur : celle de l'etat, sinon celle du jeu (+ groupe « Custom » de l'ancien etat). Une
    piste creee absente de tous les groupes est ajoutee au dernier groupe ajoute (ou a un nouveau « Custom »)."""
    import track_clone
    st = st if st is not None else (read_state(archives) or {})
    if st.get('layout'):
        layout = [dict(g, levels=list(g['levels'])) for g in st['layout']]
    else:
        layout = _original(archives)
        legacy = st.get('levels', []) + [track_clone.zone_name(t['id']) for t in st.get('tracks', [])]
        if legacy:
            layout.append({'id': None, 'key': 'custom1', 'title': TITLE, 'levels': legacy})
    placed = {lv.lower() for g in layout for lv in g['levels']}
    for t in st.get('tracks', []):
        zone = track_clone.zone_name(t['id'])
        if zone not in placed:
            g = next((g for g in reversed(layout) if not g.get('id')), None)
            if g is None:
                g = {'id': None, 'key': new_key(layout), 'title': TITLE, 'levels': []}
                layout.append(g)
            g['levels'].append(zone)
            placed.add(zone)
    return layout


def new_key(layout):
    keys = {g.get('key') for g in layout}
    return next(f'custom{i}' for i in range(1, 1000) if f'custom{i}' not in keys)


def _is_original(archives, layout):
    return [(g.get('id'), g.get('title'), [lv.lower() for lv in g['levels']]) for g in layout] == \
        [(g['id'], None, [lv.lower() for lv in g['levels']]) for g in _original(archives)]


def extra_files(archives, arc):
    """Fichiers a ajouter a une reecriture de l'archive `arc` (vide si le menu est celui du jeu et qu'aucune piste
    n'est creee) : menu, titres renommes, et pour les pistes creees (track_clone.py) leur zoneInfo, leurs .lng, le
    chunkInfos qui les declare et la liste globale des pistes de course."""
    st = read_state(archives)
    if not st or os.path.basename(arc).lower() != ARCHIVE:
        return {}
    return registration_for_state(archives, st)


def registration_for_state(archives, st):
    """Fichiers d'enregistrement (menu, titres, chunkInfos, liste des pistes de course, zoneInfo, .lng, images du
    menu) d'un etat {tracks, layout} donne ; extra_files avec l'etat du jeu, l'export OCTR avec une seule piste."""
    import track_clone
    tracks = st.get('tracks', [])
    layout = current_layout(archives, st)
    out = {}
    if not _is_original(archives, layout):
        out[PROTO] = build_proto(pak_tool.read_latest(archives, PROTO)[0], layout)
    titles = {g['id']: g['title'] for g in layout if g.get('id') and g.get('title')}
    if titles:
        for lang in LNG_LANGS:
            out[proto_lng(lang)] = write_titles(pak_tool.read_latest(archives, proto_lng(lang))[0], titles)
    if tracks:
        out[track_clone.CHUNKINFOS] = track_clone.register_chunkinfos(archives, [t['id'] for t in tracks])
        gui, _ = pak_tool.read_latest(archives, GUI_DATA)
        out[GUI_DATA] = add_race_levels(gui, [track_clone.zone_name(t['id']) for t in tracks])
        for t in tracks:
            out.update(track_clone.registration_files(archives, t['source'], t['id'], t.get('display')))
        zis = {k: v for k, v in out.items() if k.endswith('_zoneinfo.igz')}
        out.update(own_menu_files(archives, tracks, zis))
        out.update(zis)
    return out


def _level_select(z):
    """(offset de COctaneLevelSelectData, [(offset du handle, nom du materiau, espace)]) du zoneInfo."""
    off = next(o for o, t in z.objects.items() if t == 'COctaneLevelSelectData')
    out = []
    for fo, (n, ft) in sorted(z.fields_of('COctaneLevelSelectData').items()):
        if ft == 'igHandleMetaField':
            h = z.named_handle(z.u32(off + fo))
            if h:
                out.append((off + fo, h[0], h[1]))
    return off, out


def _read_texture(archives, logical, source):
    """Texture d'origine de la source (version du jeu, jamais celle modifiee par l'editeur)."""
    import menu_assets
    for pak in (None,) + menu_assets.MENU_TEXTURE_PAKS + (source.lower() + '.pak',):
        try:
            return pak_tool.read_latest(archives, logical, pak)[0]
        except (KeyError, FileNotFoundError):
            continue
    raise KeyError(logical)


def own_menu_files(archives, tracks, zoneinfos):
    """Fond et vignette propres aux pistes creees (menu_assets) : {nom logique: octets} pour update2 (materiaux,
    paquets des domaines du menu, textures copiees de la source) ; zoneinfos {piste: octets} modifies en place
    (handles vers les nouveaux materiaux, video du menu absente -> l'image de fond s'affiche)."""
    import menu_assets
    import pkg_manifest
    import track_clone
    from model_build import tdep_entries
    mats =IgzFile(pak_tool.read_latest(archives, menu_assets.MENU_MATERIALS)[0])
    roots = {n: o for n, o in mats.root_objects() if n}
    names = {o: n for n, o in roots.items()}
    owned = mats.owned_by(('igGraphicsMaterial',))
    tex_field = next(fo for fo, (n, _) in mats.fields_of('igGraphicsTexture').items() if n == '_imageHandle')
    deps = dict(tdep_entries(mats))
    out, textures = {}, []
    for t in tracks:
        zl = track_clone.zoneinfo_logical(t['id'])
        zi = IgzFile(zoneinfos[zl])
        _, handles = _level_select(zi)
        for hoff, mat, ns in handles:
            new = mat.split('_', 1)[0] + '_' + t['id']                 # LevelIcon_CrashCove -> LevelIcon_T901_Custom_Map
            if mat in roots and new not in roots:
                clone, pairs = mats.clone_owned(roots[mat], new, owned[roots[mat]], names)
                mats.add_roots(pairs)
                roots[new] = clone
                shared = mats.reachable(roots[mat])[0]
                for o in mats.reachable(clone)[0]:
                    if mats.objects[o] != 'igGraphicsTexture' or o in shared:
                        continue                                       # texture partagee : non clonee, gardee
                    h = mats.named_handle(mats.u32(o + tex_field))
                    if not h:
                        continue
                    tex = menu_assets.own_texture_name(h[1], t['id'])
                    struct.pack_into('<I', *mats._loc(o + tex_field), 0x80000000 | mats.ext_index(h[0], tex))
                    mats.add_tdep([(tex, 'textures:/' + tex + '.igz')])
                    textures.append((deps.get(h[1], 'textures:/' + h[1] + '.igz'), tex, t['source']))
            struct.pack_into('<I', *zi._loc(hoff), 0x80000000 | zi.ext_index(new, ns))
        zo = next(o for o, ty in zi.objects.items() if ty == 'CZoneInfo')
        mo = next(fo for fo, (n, _) in zi.fields_of('CZoneInfo').items() if n == '_previewMovie')
        zi.set_string_ref(zo + mo, 'octane_ui_race_select_' + t['id'].lower())
        zoneinfos[zl] = zi.to_bytes()
    if not textures:
        return out
    out[menu_assets.MENU_MATERIALS] = mats.to_bytes()
    entries = []
    for src_path, tex, source in textures:
        logical = 'textures/' + tex + '.igz'
        out[logical] = _read_texture(archives, src_path.replace(':/', '/', 1), source)   # « textures:/x » -> « textures/x »
        entries.append(('texture', logical))
    for pkg in menu_assets.MENU_PKGS:
        out[pkg] = pkg_manifest.add_entries(pak_tool.read_latest(archives, pkg)[0], entries)[0]
    return out


# -- update3.pak : fichiers AJOUTES et menu (2026-11-06) ---------------------------------------------------------
# Le jeu charge update.pak, update2.pak, update3.pak... jusqu'au premier absent, chacun l'emportant sur les precedents.
# Un fichier ajoute a update2.pak decale la position des autres (table triee) : les formats d'ecran du lanceur OCTR
# (21:9, 32:9) retrouvent leurs fichiers d'interface par position et contenu d'origine et refusaient de demarrer avec
# un mod (T901 : 8 fichiers ajoutes -> 57 fichiers attendus deplaces). update / update2 ne recoivent donc plus que des
# REMPLACEMENTS hors menu ; les fichiers ajoutes et le menu (dont ui/Octane_LevelSelect_Proto, controle par son
# contenu) vont dans update3.pak, que l'editeur tient a jour. Le reste de l'editeur voit toujours ces fichiers « dans
# update2 » (_installed_files) : index ctr_update3.json = {nom logique: archive d'origine}. OCTR remplace update3.pak
# par le sien (onglet Graphismes) : les pistes creees n'y apparaissent que par leur mod, menu et enregistrement
# restant coherents entre eux (tous dans update3).
LAYER = pak_tool.LAYER_ARCHIVE
LAYER_INDEX = 'ctr_update3.json'
LAYERED = tuple(a.lower() for a in pak_tool.UPDATE_ARCHIVES)


def layer_path(archives):
    return os.path.join(archives, LAYER)


def _layer_index(archives):
    p = os.path.join(archives, LAYER_INDEX)
    try:
        return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {}
    except ValueError:
        return {}


def _menu_names():
    import menu_assets
    import track_clone
    return {n.lower() for n in (PROTO, track_clone.CHUNKINFOS, GUI_DATA, menu_assets.MENU_MATERIALS, *menu_assets.MENU_PKGS)} | \
        {proto_lng(g).lower() for g in LNG_LANGS}


def layer_files(archives, origin=None):
    """{nom logique: octets} installes dans update3.pak (ceux venus de l'archive `origin`, ou tous)."""
    idx = _layer_index(archives)
    names = {n for n, o in idx.items() if origin is None or o.lower() == origin.lower()}
    path = pak_tool.real(layer_path(archives))
    if not names or not os.path.exists(path):
        return {}
    a = pak_tool.IgaArchive(path)
    try:
        by = {e.logical_name.lower(): e for e in a.entries}
        return {n: a.read(by[n.lower()]) for n in names if n.lower() in by}
    finally:
        a.f.close()


def _layer_write(archives, origin, files):
    """update3.pak : fichiers venus de `origin` remplaces par `files` ; ceux des autres archives gardes."""
    import track_clone
    path, idx = pak_tool.real(layer_path(archives)), _layer_index(archives)     # jeu en deux dossiers : la ou le jeu le lit
    if os.path.exists(path) and not idx:
        if not files:
            return
        raise RuntimeError(f'{LAYER} existe deja et ne vient pas de l\'editeur (un mod ?) : retire-le avant d\'installer')
    cur = layer_files(archives)
    want = {n: d for n, d in cur.items() if idx.get(n, '').lower() != origin.lower()}
    owner = {n: idx[n] for n in want}
    for n, d in files.items():
        for old in [k for k in want if k.lower() == n.lower()]:
            del want[old]
            owner.pop(old, None)
        want[n], owner[n] = d, origin
    if want == cur and owner == idx:
        return
    pak_tool.invalidate_cache(path)
    ip = os.path.join(archives, LAYER_INDEX)
    if not want:
        for p in (path, ip):
            if os.path.exists(p):
                os.remove(p)
        return
    template = os.path.join(archives, pak_tool.UPDATE_ARCHIVES[0])
    full = {}
    view = pak_tool.original_archive(template) or pak_tool.cached_archive(template)
    for n in want:
        e = view[1].get(n.lower())
        full[n] = e.name if e is not None else pak_tool.FULL_PREFIX + n
    rows = [(n, full[n], i, ('data', d)) for i, (n, d) in enumerate(sorted(want.items(), key=lambda kv: kv[0].lower()))]
    tmp = path + '.tmp'
    try:
        track_clone.write_archive(tmp, rows, template)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    json.dump(owner, open(ip, 'w', encoding='utf-8'), indent=1)
    pak_tool.invalidate_cache(path)


def layer_has(arc):
    """L'archive a-t-elle des fichiers installes dans update3.pak ?"""
    return bool({o for o in _layer_index(os.path.dirname(arc)).values() if o.lower() == os.path.basename(arc).lower()})


def store(arc, files):
    """Installe `files` dans l'archive `arc` (remise a l'origine d'abord) ; update / update2 : fichiers ajoutes et
    menu dans update3.pak (voir plus haut)."""
    archives, base = os.path.dirname(arc), os.path.basename(arc).lower()
    stay = dict(files)
    if base in LAYERED:
        view = pak_tool.original_archive(arc) or pak_tool.cached_archive(arc)
        menu = _menu_names()
        moved = {n: d for n, d in files.items() if n.lower() in menu or n.lower() not in view[1]}
        stay = {n: d for n, d in files.items() if n not in moved}
        _layer_write(archives, base, moved)
    pak_tool.invalidate_cache(arc)
    if os.path.exists(pak_tool.backup_path(arc)):
        pak_tool.uninstall(arc)
    if stay:
        pak_tool.install(arc, stay)
    pak_tool.invalidate_cache(arc)


def _installed_files(arc):
    """Fichiers deja installes dans l'archive (contenu actuel, update3.pak compris pour update / update2), sans le
    menu."""
    out = {}
    info = pak_tool._backup_info(arc)
    if info:
        a = pak_tool.IgaArchive(pak_tool.real(arc))
        idx = {e.logical_name.lower(): e for e in a.entries}
        out = {n: a.read(idx[n.lower()]) for n in info['files'] if n.lower() != PROTO.lower()}
        a.f.close()
    if os.path.basename(arc).lower() in LAYERED:
        out.update({n: d for n, d in layer_files(os.path.dirname(arc), os.path.basename(arc)).items()
                    if n.lower() != PROTO.lower()})
    return out


def _rewrite(arc, files):
    store(arc, files)


def _write_state(archives, st):
    if not st.get('tracks') and not st.get('levels') and (not st.get('layout') or _is_original(archives, st['layout'])):
        if os.path.exists(state_path(archives)):
            os.remove(state_path(archives))                 # menu du jeu, rien de cree : plus d'etat
        return
    json.dump(st, open(state_path(archives), 'w'), indent=1)


def _ours(archives, st=None):
    """Noms des fichiers que ce module a pu mettre dans update2."""
    import track_clone
    st = st if st is not None else (read_state(archives) or {})
    import menu_assets
    out = {PROTO, track_clone.CHUNKINFOS, GUI_DATA, menu_assets.MENU_MATERIALS, *menu_assets.MENU_PKGS} | \
        {proto_lng(g) for g in LNG_LANGS}
    for t in st.get('tracks', []):
        out |= {track_clone.zoneinfo_logical(t['id'])} | {track_clone.lng_logical(t['id'], g) for g in track_clone.LANGS}
        out |= {menu_assets.own_image_file(t['id'], k) for k in menu_assets.OWN_IMAGES} | \
            {menu_assets.own_image_file(t['id'], 'background').replace('_bg_', '_bg_pattern_')}
    return out


def _apply(archives, old_ours=()):
    """Reecrit update2.pak : fichiers deja installes (pistes de l'editeur) + fichiers du menu / des pistes creees."""
    arc = os.path.join(archives, ARCHIVE)
    import menu_assets
    ours = {k.lower() for k in set(_ours(archives)) | set(old_ours)}
    installed = _installed_files(arc)
    keep = {n: d for n, d in installed.items() if n.lower() not in ours}
    # images des pistes creees modifiees par l'editeur (installees a la place des copies) : gardees
    own = {menu_assets.own_image_file(t['id'], k).lower() for t in (read_state(archives) or {}).get('tracks', [])
           for k in menu_assets.OWN_IMAGES}
    edited = {n: d for n, d in installed.items() if n.lower() in own}
    _rewrite(arc, {**keep, **extra_files(archives, arc), **edited})
    return keep


def set_layout(archives, layout):
    """Nouvelle disposition (groupes du jeu par id, groupes ajoutes id None) ; chaque piste du jeu et chaque piste
    creee doit y etre au plus une fois. Installe aussitot."""
    import track_clone
    orig = _original(archives)
    if not layout:
        layout = orig                                      # menu d'origine (pistes creees : groupe « Custom »)
    ids = {g['id'] for g in orig}
    known = {lv.lower() for g in orig for lv in g['levels']}
    st = read_state(archives) or {}
    known |= {track_clone.zone_name(t['id']) for t in st.get('tracks', [])}
    clean, seen = [], set()
    for g in layout:
        gid = g.get('id') if g.get('id') in ids else None
        title = (g.get('title') or '').strip() or None
        levels = []
        for lv in g.get('levels') or []:
            if lv.lower() in known and lv.lower() not in seen:
                levels.append(lv)
                seen.add(lv.lower())
        clean.append({'id': gid, 'key': g.get('key') or gid or new_key(clean), 'title': title if gid or title else TITLE,
                      'levels': levels})
    missing = [g['id'] for g in orig if g['id'] not in {c['id'] for c in clean}]
    clean += [{'id': i, 'key': i, 'title': None, 'levels': []} for i in missing]   # groupes du jeu jamais supprimes
    old = _ours(archives, st)
    st['layout'] = clean
    st.pop('levels', None)
    _write_state(archives, st)
    _apply(archives, old)
    return current_layout(archives)


def add_track(archives, track_id, source, display, paks, group_key=None):
    """Enregistre une piste creee par track_clone (archives deja ecrites) : etat, chunks.igx, update2. group_key :
    groupe ou la ranger (sinon le dernier groupe ajoute, cree au besoin)."""
    import track_clone
    st = read_state(archives) or {}
    if not st.get('layout') and st.get('levels') == DEFAULT_LEVELS:
        st['levels'] = []                                  # entree d'essai (Crash Cove) remplacee par la piste
    layout = current_layout(archives, st)
    zone = track_clone.zone_name(track_id)
    for g in layout:
        g['levels'] = [lv for lv in g['levels'] if lv.lower() != zone]
    target = next((g for g in layout if group_key and g.get('key') == group_key), None)
    if target is not None:
        target['levels'].append(zone)
    st['tracks'] = [t for t in st.get('tracks', []) if t['id'] != track_id] + \
        [{'id': track_id, 'source': source, 'display': display, 'paks': paks,
          'images_from': source}]                          # images du menu : celles de la source (zoneinfo copie)
    st['layout'] = layout
    st.pop('levels', None)
    st['layout'] = current_layout(archives, st)            # pas de groupe choisi : dernier groupe ajoute
    old = _ours(archives, st)
    _write_state(archives, st)
    track_clone.chunks_igx_set(os.path.dirname(archives), [p for t in st['tracks'] for p in t['paks']])
    return _apply(archives, old)


def rename_track(archives, track_id, display):
    st = read_state(archives) or {}
    for t in st.get('tracks', []):
        if t['id'] == track_id:
            t['display'] = display
    _write_state(archives, st)
    return _apply(archives)


def remove_track(archives, track_id, delete_paks=False):
    import track_clone
    st = read_state(archives) or {}
    old = [t for t in st.get('tracks', []) if t['id'] == track_id]
    old_ours = _ours(archives, st)
    zone = track_clone.zone_name(track_id)
    if st.get('layout'):
        for g in st['layout']:
            g['levels'] = [lv for lv in g['levels'] if lv.lower() != zone]
    st['tracks'] = [t for t in st.get('tracks', []) if t['id'] != track_id]
    _write_state(archives, st)
    track_clone.chunks_igx_set(os.path.dirname(archives), [p for t in st['tracks'] for p in t['paks']])
    keep = _apply(archives, old_ours)
    if delete_paks:
        for t in old:
            for p in t['paks']:
                path = os.path.join(archives, p)
                for f in (path, pak_tool.backup_path(path), pak_tool.toc_backup_path(path)):
                    if os.path.exists(f):
                        os.remove(f)
    return keep


def install(archives, levels=None):
    """Essai historique : groupe « Custom » avec ces pistes du jeu (Crash Cove par defaut)."""
    st = read_state(archives) or {}
    layout = [g for g in current_layout(archives, st) if g.get('id')]
    layout.append({'id': None, 'key': 'custom1', 'title': TITLE, 'levels': levels or DEFAULT_LEVELS})
    st['layout'] = layout
    old = _ours(archives, st)
    _write_state(archives, st)
    return _apply(archives, old)


def uninstall(archives):
    """Menu du jeu remis et enregistrement des pistes creees retire (leurs archives .pak restent sur le disque)."""
    import track_clone
    arc = os.path.join(archives, ARCHIVE)
    ours = {k.lower() for k in _ours(archives)}
    keep = {n: d for n, d in _installed_files(arc).items() if n.lower() not in ours}
    if os.path.exists(state_path(archives)):
        os.remove(state_path(archives))
    track_clone.chunks_igx_set(os.path.dirname(archives), [])
    _rewrite(arc, keep)
    return keep


def build(archives, levels=None):
    """Proto avec un groupe « Custom » (essai, sans rien installer)."""
    layout = _original(archives) + [{'id': None, 'key': 'custom1', 'title': TITLE, 'levels': levels or DEFAULT_LEVELS}]
    return build_proto(pak_tool.read_latest(archives, PROTO)[0], layout)


def main(argv):
    if len(argv) < 2 or argv[0] not in ('install', 'uninstall', 'build'):
        print('usage : custom_category.py install|uninstall <dossier archives> [niveau ...]\n'
              '        custom_category.py build <dossier archives> <fichier de sortie> [niveau ...]')
        return 1
    cmd, archives = argv[0], argv[1]
    if cmd == 'build':
        data = build(archives, argv[3:] or None)
        open(argv[2], 'wb').write(data)
        for title, levels in categories(data):
            print(f'  {title or "(titre du jeu)"} : {len(levels)} piste(s)')
        return 0
    if cmd == 'install':
        keep = install(archives, argv[2:] or None)
        print(f'Categorie « {TITLE} » installee dans {ARCHIVE} ({len(keep)} fichier(s) deja installe(s) gardes).')
    else:
        keep = uninstall(archives)
        print(f'Menu du jeu remis ({len(keep)} fichier(s) installe(s) gardes).')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
