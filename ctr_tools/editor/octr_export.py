"""Export de pistes en un mod pour le portage PC « CTR-NitroFueled-PC » (OCTR, lanceur > Mods) - 2026-11-06.

Un mod OCTR est un .zip : mod.json (schemaVersion 2), octr-mod.required (« OCTR Mod Package 2 »), README.txt et
archives/*.pak COMPLETES, au format natif du jeu (IGA). Le jeu charge update.pak, update2.pak, update3.pak... jusqu'au
premier absent, chacun l'emportant sur les precedents : l'enregistrement des pistes va dans un update3.pak (comme le
mod d'exemple Coconut Mall : t922_coconut_mall_wii.pak + update3.pak).

Un mod peut porter plusieurs pistes : deux mods qui livrent chacun un update3.pak complet sont en conflit et le
lanceur ne fusionne pas les enregistrements de pistes, donc des pistes jouables ensemble partent dans un meme mod, avec
un seul update3.pak et un groupe du menu nomme a l'export. Chaque piste :
  * piste creee (T9xx) : son archive et ses survols complets, avec les fichiers de l'editeur ;
  * 'new' (piste du jeu) : une NOUVELLE piste T9xx (rien du jeu remplace) : copie renommee (track_clone) ;
  * 'replace' (piste du jeu) : la piste remplacee. Son archive (et ses survols) complete, sans enregistrement.
Fichiers que l'installation met dans update/update2/permanent/chunkinfos... -> update3.pak.
Rien n'est ecrit dans le dossier du jeu : les archives sont fabriquees a partir des originaux (lecture seule) et des
fichiers calcules par le plan d'installation de l'editeur.
"""
import hashlib
import io
import json
import os
import re
import shutil
import threading
import time
import zipfile

import pak_tool
import track_clone

_server = None
MARKER, MARKER_CONTENT = 'octr-mod.required', b'OCTR Mod Package 2\n'
UPDATE3 = 'update3.pak'
# priorite des archives du jeu quand un meme fichier est installe dans plusieurs (la plus haute en dernier)
_PRIORITY = ('permanent.pak', 'update.pak', 'update2.pak')
NAME_MAX = 40                     # comme l'onglet Menu de l'editeur (nom de piste, titre de categorie)


def bind(module):
    global _server
    _server = module


def _S():
    if _server is None:
        raise RuntimeError('octr_export : serveur non lie')
    return _server


# -- fichiers en memoire, presentes comme des entrees d'archive (track_clone / write_archive) -----------------------
class _Mem:
    def __init__(self, data):
        self.data = data
        self.f = io.BytesIO(data)
        self.sector = 0x800

    def read(self, e):
        return self.data


def _mem(logical, data, full=None):
    e = pak_tool.Entry(0, full or pak_tool.FULL_PREFIX + logical, logical, 0, 0, len(data), pak_tool.TYPE_NONE,
                       0x0FFFFFFF, 0)
    return (_Mem(data), e, threading.Lock())


def _plan(track):
    """{chemin d'archive: {nom logique: octets}} de l'installation, avec les retouches faites a l'ecriture (temps,
    types de sol ajoutes) ; le menu des pistes creees n'y est pas (extra_files : etat du jeu, pas cette piste)."""
    S = _S()
    try:                                                  # comme l'installation : zones de chute hors de la course
        checked = S.check_race_zones(track)
    except Exception as e:  # noqa: BLE001 - la verification ne doit pas empecher l'export
        checked = [f'vérification de la course impossible : {e}']
    plan = S.install_plan(track)
    # meme plafond de memoire qu'a l'installation (2026-11-07 : T901 exportee a 843 Mo plantait aussi dans OCTR,
    # « OOM [1]{76,GlobalChunk} » : le jeu charge toute l'archive de la piste) ; textures d'origine reduites ajoutees
    _LAST_SHRINK[track] = checked + S.slim_ai_lanes(plan, track) + S.shrink_textures(plan, track)
    return {arc: S._apply_custom_surfaces(S._apply_times(dict(reps))) for arc, reps in plan.items() if reps}


_LAST_SHRINK = {}                                         # piste -> rapport de reduction des textures (build)


def _complete_pak(arc_path, reps, out_path):
    """Archive complete : fichiers d'origine recopies tels quels, ceux de reps remplaces ou ajoutes."""
    a, idx, lock = track_clone._view(arc_path)
    lower = {k.lower(): k for k in reps}
    files, done = [], set()
    nxt = max((e.ordinal for e in idx.values() if e.ordinal < 0xFFFFFF), default=-1) + 1
    for n, e in sorted(idx.items(), key=lambda kv: kv[1].index):
        if n in lower:
            files.append((e.logical_name, e.name, e.ordinal, ('data', reps[lower[n]])))
            done.add(n)
        else:
            files.append((e.logical_name, e.name, e.ordinal, ('raw', a, e, lock)))
    for k, v in sorted(reps.items()):
        if k.lower() not in done:
            files.append((k, pak_tool.FULL_PREFIX + k, nxt, ('data', v)))
            nxt += 1
    track_clone.write_archive(out_path, files, arc_path)
    return len(files)


def _update3(merged, out_path, template):
    """update3.pak neuf avec les fichiers donnes ({minuscules: (nom logique, octets, nom complet)})."""
    files = [(k, full, i, ('data', d)) for i, (k, d, full) in enumerate(sorted(merged.values(), key=lambda f: f[0].lower()))]
    track_clone.write_archive(out_path, files, template)
    return len(files)


def _full_name(arc_path, logical):
    try:
        _, idx, _ = track_clone._view(arc_path)
        e = idx.get(logical.lower())
        if e is not None:
            return e.name
    except (OSError, ValueError):
        pass
    return pak_tool.FULL_PREFIX + logical


def _merge_common(plan, skip):
    """Fichiers des archives communes (pas celles de la piste) : la plus prioritaire l'emporte.
    -> {minuscules: (nom logique, octets, nom complet)}."""
    rank = lambda arc: (_PRIORITY.index(os.path.basename(arc).lower()) if os.path.basename(arc).lower() in _PRIORITY else -1)
    out = {}
    for arc in sorted(plan, key=rank):
        if os.path.normcase(arc) in skip:
            continue
        for k, v in plan[arc].items():
            out[k.lower()] = (k, v, _full_name(arc, k))
    return out


def _slug(s):
    return re.sub(r'[^a-z0-9-]+', '-', s.lower()).strip('-')[:80] or 'ctr-track'


def _free_id(archives, src, used=()):
    """Numero T9xx libre : ni dans le jeu, ni deja pris dans ce mod (le numero seul : T901_Custom_Ma et T901_Custom_Map
    seraient deux pistes de meme numero)."""
    import custom_category
    taken = {f.lower().split('_')[0] for f in os.listdir(archives) if f.lower().endswith('.pak')}
    taken |= {t['id'].lower().split('_')[0] for t in (custom_category.read_state(archives) or {}).get('tracks', [])}
    taken |= {u.lower().split('_')[0] for u in used}
    for k in range(1, 100):
        new = track_clone.new_id(src, k)
        if new.lower().split('_')[0] not in taken:
            return new
    raise RuntimeError('plus de numero de piste libre (T901 a T999)')


def tracks_info():
    """GET /api/octr_tracks : pistes exportables [{track, name, created, group}] (group : son groupe ajoute au menu)."""
    S = _S()
    import custom_category
    import mappack
    st = custom_category.read_state(S.ARCHIVES) or {}
    created = {t['id']: t for t in st.get('tracks', [])}
    layout = custom_category.current_layout(S.ARCHIVES, st)
    rows = {t['track']: t['title'] for t in mappack.exportable_tracks()}
    for t in created.values():
        rows.setdefault(t['id'], t.get('display') or t['id'])
    out = []
    for track, title in rows.items():
        zone = track_clone.zone_name(track)
        g = next((g for g in layout if zone in [v.lower() for v in g['levels']]), None)
        c = created.get(track)
        out.append({'track': track, 'name': (c or {}).get('display') or title, 'created': bool(c),
                    'group': g.get('title') if g and not g.get('id') else None})
    return {'tracks': out}


def _add_track(item, work, used, frac):
    """Archives d'une piste dans work/archives. -> (fichiers communs {minuscules: ...}, noms d'archives, rapport, piste a
    enregistrer {id, source, display, paks} ou None si elle remplace une piste du jeu)."""
    S = _S()
    import custom_category
    archives = S.ARCHIVES
    track, mode, display = item['track'], item['mode'], item['name']
    S.progress.step(f'plan d\'installation : {display}', frac(0))
    plan = _plan(track)
    created = {t['id'].lower(): t for t in (custom_category.read_state(archives) or {}).get('tracks', [])}
    is_created = track.lower() in created
    if not plan and not is_created:
        raise RuntimeError(f'{track} : rien a exporter, enregistre la piste d\'abord')
    own = {os.path.normcase(a) for a in S.own_archives(track)}
    paks, report = [], list(_LAST_SHRINK.pop(track, []))
    if mode == 'replace' or is_created:
        # archive de la piste toujours ; survols seulement s'ils ont ete modifies (piste creee : aussi, ils ne sont
        # dans le jeu de personne d'autre)
        main = os.path.normcase(os.path.join(archives, S.track_pak(track)))
        changed = {os.path.normcase(p) for p in plan}
        arcs = [a for a in sorted(own) if os.path.exists(a) and (a == main or a in changed or is_created)]
        for k, arc in enumerate(arcs):
            S.progress.step(f'archive {os.path.basename(arc)}', frac(0.1 + 0.9 * k / max(1, len(arcs))))
            reps = next((r for p, r in plan.items() if os.path.normcase(p) == arc), {})
            name = os.path.basename(arc).lower()
            n = _complete_pak(arc, reps, os.path.join(work, 'archives', name))
            paks.append(name)
            report.append(f'{name} : {n} fichiers, dont {len(reps)} de l\'éditeur')
        common = _merge_common(plan, own)
        reg = dict(created[track.lower()], display=display) if is_created else None
        return common, paks, report, reg
    # nouvelle piste : copie renommee de la piste avec les fichiers de l'editeur
    src = track
    new_id = _free_id(archives, src, used)
    used.add(new_id)
    rx = re.compile(re.escape(src), re.I)
    extra = track_clone.source_files(archives, src)
    lower = {k.lower(): k for k in extra}
    routed = set()
    for arc, reps in plan.items():
        for k, v in reps.items():
            mine = os.path.normcase(arc) in own and not os.path.basename(arc).lower().startswith(src.lower() + '_')
            if mine or k.lower() in lower or rx.search(k):
                if '_zoneinfo' in k.lower():
                    continue                              # zoneInfo de la nouvelle piste : enregistrement
                extra[lower.get(k.lower(), k)] = _mem(k, v)
                routed.add((arc, k))
    main = new_id.lower() + '.pak'
    st = track_clone.clone_pak(archives, src, new_id, src.lower() + '.pak', os.path.join(work, 'archives', main),
                               extra=extra, progress=lambda f: S.progress.step(f'copie renommée : {display}', frac(0.1 + 0.8 * f)))
    paks.append(main)
    report.append(f'{main} : {st["files"]} fichiers ({st["renamed"]} renommés)')
    ren = track_clone.Renamer(src, new_id)
    # survols, avec ceux de l'editeur ; cinematique de fin de boss (T112, T133, T142, T153), listee au manifeste
    outro = sorted(f for f in os.listdir(archives) if f.lower().startswith(src.lower() + '_') and f.lower().endswith('_outro.pak'))
    for fp in track_clone.flyby_paks(archives, src) + outro:
        fpath = os.path.join(archives, fp)
        a, idx, lock = track_clone._view(fpath)
        fx = {e.logical_name: (a, e, lock) for e in idx.values()}
        for k, v in next((r for p, r in plan.items() if os.path.normcase(p) == os.path.normcase(fpath)), {}).items():
            fx[k] = _mem(k, v)
        out = ren.name(fp).lower()
        track_clone.clone_pak(archives, src, new_id, fp, os.path.join(work, 'archives', out), extra=fx)
        paks.append(out)
    # communs (types de sol ajoutes, fantomes, scripts...) : ceux qui ne sont pas partis dans la copie
    rest = {arc: {k: v for k, v in reps.items() if (arc, k) not in routed and '_zoneinfo' not in k.lower()}
            for arc, reps in plan.items()}
    return _merge_common(rest, own), paks, report, {'id': new_id, 'source': src, 'display': display, 'paks': list(paks),
                                                    'relic_of': src}


def _registration(regs, category):
    """Fichiers d'enregistrement de toutes les pistes du mod, dans un groupe du menu ajoute a celui du jeu.
    -> {minuscules: (nom logique, octets, nom complet)}."""
    S = _S()
    import custom_category
    import race_times
    archives = S.ARCHIVES
    layout = custom_category._original(archives) + [
        {'id': None, 'key': 'custom1', 'title': category, 'levels': [track_clone.zone_name(t['id']) for t in regs]}]
    tracks = [{k: v for k, v in t.items() if k != 'relic_of'} for t in regs]
    reg = custom_category.registration_for_state(archives, {'tracks': tracks, 'layout': layout})
    reg = S._apply_times(reg)
    for t in regs:                                    # copie d'une piste du jeu : temps des reliques de la piste source
        relic = (S.times_settings(t['relic_of']) or {}).get('relic') if t.get('relic_of') else None
        zl = track_clone.zoneinfo_logical(t['id'])
        if relic and zl in reg:
            reg[zl] = race_times.write_relic(reg[zl], relic)
    return {k.lower(): (k, v, _full_name(os.path.join(archives, 'update2.pak'), k)) for k, v in reg.items()}


def _apply_names(merged, regs):
    """Nom choisi a l'export : en dernier, un .lng enregistre par l'editeur ne doit pas le remplacer."""
    import menu_assets
    for t in regs:
        for lang in track_clone.LANGS:
            key = track_clone.lng_logical(t['id'], lang).lower()
            if key in merged and t.get('display'):
                k, d, full = merged[key]
                merged[key] = (k, menu_assets.write_name(d, t['display']), full)


def _clone_images(merged, regs):
    """Copie d'une piste du jeu : le menu de la copie vise SES images (fond, vignette : ..._t902custommap), copiees de
    la piste source d'origine. Une image modifiee dans l'editeur (enregistree sous le nom de la source,
    ..._crashcove) devient la sienne, et la piste source du jeu garde son image d'origine."""
    S = _S()
    import menu_assets
    for t in regs:
        src = t.get('relic_of')
        if not src:
            continue
        for key in menu_assets.OWN_IMAGES:
            logical = S.menu_image_logical(src, key)
            p = S.saved_path(logical)
            if not os.path.exists(p):
                continue
            own = menu_assets.own_image_file(t['id'], key)
            k, _, full = merged.get(own.lower(), (own, None, pak_tool.FULL_PREFIX + own))
            merged[own.lower()] = (k, open(p, 'rb').read(), full)
            merged.pop(logical.lower(), None)


def _items(req):
    """Pistes demandees, sans doublon. req = {tracks: [{track, mode, name}]} ou, pour une seule, {track, mode, name}."""
    S = _S()
    raw = req.get('tracks') or ([{'track': req['track'], 'mode': req.get('mode'), 'name': req.get('name')}] if req.get('track') else [])
    if not raw:
        raise ValueError('aucune piste choisie')
    known = set(S.list_tracks())
    out, seen = [], set()
    for r in raw:
        track = r['track']
        if track not in known:
            raise ValueError(f'piste inconnue : {track}')
        if track.lower() in seen:
            continue
        seen.add(track.lower())
        mode = r.get('mode') or 'new'
        if mode not in ('replace', 'new'):
            raise ValueError('mode inconnu')
        name = (r.get('name') or '').strip() or track.split('_', 1)[1].replace('_', ' ')
        if len(name) > NAME_MAX:
            raise ValueError(f'nom trop long ({NAME_MAX} caractères au plus) : {name}')
        out.append({'track': track, 'mode': mode, 'name': name})
    return out


def build(req):
    """req = {tracks: [{track, mode 'replace' | 'new', name}], category (groupe du menu), mod_name, author, version,
    description} -> {path, report}. Le .zip est ecrit dans <projet>/exports/octr."""
    S = _S()
    archives = S.ARCHIVES
    items = _items(req)
    category = (req.get('category') or '').strip() or 'Custom'
    if len(category) > NAME_MAX:
        raise ValueError(f'nom de catégorie trop long ({NAME_MAX} caractères au plus)')
    display = (req.get('mod_name') or '').strip() or (items[0]['name'] if len(items) == 1 else category)
    version = req.get('version') or '1.0.0'
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('version au format 1.0.0')
    mod_id = _slug(f'ctr-editor-{display}')
    work = os.path.join(S.OUT_DIR, 'octr_build', mod_id)
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(os.path.join(work, 'archives'))
    report, pak_names, regs, common, clash, used = [], [], [], {}, [], set()
    for n, item in enumerate(items):
        frac = lambda f, n=n: 0.02 + 0.68 * (n + f) / len(items)
        files, paks, rep, reg = _add_track(item, work, used, frac)
        pak_names += paks
        report += rep
        if reg:
            regs.append(reg)
        for k, v in files.items():                    # meme fichier commun, contenus differents : la derniere l'emporte
            if k in common and common[k][1] != v[1]:
                clash.append(v[0])
            common[k] = v
    # comme a l'installation : les fichiers de l'editeur (images de menu, zoneInfo...) passent apres l'enregistrement
    S.progress.step('enregistrement', 0.7)
    merged = _registration(regs, category) if regs else {}
    merged.update(common)
    _apply_names(merged, regs)
    _clone_images(merged, regs)
    if regs:
        report.append(f'{len(regs)} piste(s) dans le groupe du menu « {category} » : '
                      + ', '.join(f"{t['display']} ({t['id']})" for t in regs))
    if clash:
        report.append(f'attention, {len(clash)} fichier(s) communs différents entre ces pistes (la dernière l\'emporte) : '
                      + ', '.join(sorted(set(clash))[:5]))
    S.progress.step('update3.pak', 0.75)
    if merged:
        n = _update3(merged, os.path.join(work, 'archives', UPDATE3), os.path.join(archives, 'update2.pak'))
        pak_names.append(UPDATE3)
        report.append(f'{UPDATE3} : {n} fichiers (enregistrement, fichiers communs)')
    # lisez-moi, manifeste, marqueur
    lines = [f"Nouvelle piste {t['id']} « {t['display']} » : groupe « {category} » du choix des pistes.\n" for t in regs]
    lines += [f"Remplace la piste {i['track']}.\n" for i in items if i['mode'] == 'replace' and i['track'] not in {t['id'] for t in regs}]
    readme = (f'{display} {version} - pour Crash Team Racing Nitro-Fueled (USA 1.21), fait avec CTR Track Editor.\n\n'
              f'INSTALLATION\nLanceur OCTR > Mods > Add files, choisir ce .zip, activer « {display} », redemarrer le jeu.\n'
              + ''.join(lines)
              + f'\nCONFLITS\nCe mod contient un {UPDATE3} complet : desactiver les autres mods qui en livrent un (pistes, menus).\n'
              f'\nARCHIVES\n' + ''.join(f'  archives/{p}\n' for p in pak_names))
    open(os.path.join(work, 'README.txt'), 'w', encoding='utf-8', newline='\n').write(readme)
    open(os.path.join(work, MARKER), 'wb').write(MARKER_CONTENT)
    files = []
    for root, _, names in os.walk(work):
        for f in sorted(names):
            p = os.path.join(root, f)
            rel = os.path.relpath(p, work).replace('\\', '/')
            h = hashlib.sha256()
            with open(p, 'rb') as fh:
                for blk in iter(lambda: fh.read(1 << 20), b''):
                    h.update(blk)
            files.append({'file': rel, 'sha256': h.hexdigest(), 'bytes': os.path.getsize(p)})
    desc = (req.get('description') or '').strip() or (
        ' ; '.join(l.strip() for l in lines) + ' Fait avec CTR Track Editor. Contient un update3.pak complet '
        '(conflit avec les autres mods qui en livrent un).')
    manifest = {'schemaVersion': 2, 'id': mod_id, 'name': display, 'version': version,
                'author': (req.get('author') or '').strip() or 'CTR Track Editor', 'description': desc,
                'requiresCapabilities': [], 'files': sorted(files, key=lambda f: f['file']), 'conflicts': [],
                # 'offline-only' bloque le lancement tant que le mode en ligne est actif (online=1 par defaut dans le
                # lanceur) ; le mod d'exemple Coconut Mall declare aussi 'allowed'
                'compatibility': {'online': 'allowed'}, 'operations': []}
    open(os.path.join(work, 'mod.json'), 'w', encoding='utf-8', newline='\n').write(json.dumps(manifest, indent=2, ensure_ascii=False))
    S.progress.step('fichier .zip', 0.85)
    out_dir = os.path.join(S.PROJECT_DIR, 'exports', 'octr')
    os.makedirs(out_dir, exist_ok=True)
    file_stem = f'{_slug(display)}-{version}'          # l'identifiant du mod garde son prefixe, pas le nom du fichier
    out = os.path.join(out_dir, f'{file_stem}.zip')
    if os.path.exists(out):
        out = os.path.join(out_dir, f'{file_stem}-{time.strftime("%Y%m%d-%H%M%S")}.zip')
    with zipfile.ZipFile(out, 'x', allowZip64=True) as z:
        for root, _, names in os.walk(work):
            for f in sorted(names):
                p = os.path.join(root, f)
                rel = os.path.relpath(p, work).replace('\\', '/')
                z.write(p, rel, compress_type=zipfile.ZIP_STORED if f.lower().endswith('.pak') else zipfile.ZIP_DEFLATED)
    shutil.rmtree(work, ignore_errors=True)
    size = os.path.getsize(out)
    report.append(f'{os.path.basename(out)} : {size / 2 ** 20:.0f} Mo')
    return {'path': out, 'name': os.path.basename(out), 'id': mod_id, 'track_ids': [t['id'] for t in regs], 'report': report}
