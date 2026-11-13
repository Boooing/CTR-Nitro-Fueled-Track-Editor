"""Retour au jeu d'origine : tout ce que l'editeur ou l'installateur ont mis dans le dossier du jeu est retire.

  plan = restore_plan(archives)     ce qui sera perdu / remis (pour prevenir l'utilisateur), problemes detectes
  report = restore_game(archives)   le fait

Retire / remet :
  - archives modifiees (<archive>.ctrmod.json + .ctrmod.toc, voir pak_tool.install) : en-tete d'origine remis,
    fichier ramene a sa taille d'origine ;
  - pistes creees (custom_category, track_clone) : leurs archives t9xx_*.pak (et survols) supprimees ;
  - menu du jeu (categories ajoutees / renommees) : etat ctr_custom_category.json supprime (update2 deja remis) ;
  - chunks.igx (racine du jeu) : copie d'origine chunks.igx.ctrmod remise ;
  - videos du menu mises de cote (<video>.bk2.ctrmod-off) : remises ;
  - registre commun des pistes installees (ctr_installed_tracks.json).
Une archive plus petite que sa taille d'origine (jeu reinstalle ou mis a jour depuis l'installation) n'est pas
touchee : ses sauvegardes ne correspondent plus, elle est signalee."""
import json
import os
import re

import custom_category
import pak_tool
import track_clone

REGISTRY = 'ctr_installed_tracks.json'
VIDEO_OFF = '.ctrmod-off'


def _read_json(p):
    try:
        return json.load(open(p, encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _game_titles(archives, lang):
    try:
        return custom_category.game_titles(archives, lang)
    except Exception:  # noqa: BLE001 - noms du jeu facultatifs (affichage)
        return {}


def restore_plan(archives, lang='fr'):
    """-> {created: [{id, display, paks}], categories: [{title, added}], installed: [{track, by, title}],
           archives: [noms des archives modifiees], videos: [videos remises], chunks: bool,
           problems: [archives dont la sauvegarde ne correspond plus], nothing: bool}."""
    st = custom_category.read_state(archives) or {}
    created = [{'id': t['id'], 'display': t.get('display') or t['id'], 'paks': list(t.get('paks') or [])}
               for t in st.get('tracks', [])]
    created_paks = {p.lower() for t in created for p in t['paks']}
    cats = []
    if st.get('layout'):
        titles = _game_titles(archives, custom_category.UI_LANG.get(lang, 'en'))
        for g in st['layout']:
            if not g.get('id'):
                cats.append({'title': g.get('title') or custom_category.TITLE, 'added': True})
            elif g.get('title'):
                cats.append({'title': f"{titles.get(g['id'], g['id'])} → {g['title']}", 'added': False})
    reg = _read_json(os.path.join(archives, REGISTRY)) or {}
    installed = [{'track': t, 'by': e.get('by'), 'title': e.get('title')} for t, e in sorted(reg.items())]
    # installees avant le registre : archive propre de la piste sauvegardee (t111_crash_cove.pak.ctrmod.json)
    known = {t.lower() for t in reg} | {t['id'].lower() for t in created}
    for f in pak_tool.listdir(archives):              # jeu en deux dossiers : mise a jour comprise
        m = re.match(r'^(t\d{3}_[a-z0-9_]+)\.pak\.ctrmod\.json$', f, re.I)
        if m and 'flyby' not in f.lower() and m.group(1).lower() not in known:
            installed.append({'track': m.group(1), 'by': None, 'title': None})
    mods, problems = [], []
    for f in pak_tool.listdir(archives):
        if not f.endswith('.ctrmod.json'):
            continue
        arc = os.path.join(archives, f[:-len('.ctrmod.json')])
        name = os.path.basename(arc)
        if name.lower() in created_paks:
            continue                                      # supprimee avec sa piste
        info = _read_json(pak_tool.backup_path(arc)) or {}
        if not pak_tool.exists(arc):
            problems.append(f'{name} : archive absente (sauvegarde orpheline)')
        elif info.get('version') == 2 and not os.path.exists(pak_tool.toc_backup_path(arc)):
            problems.append(f'{name} : sauvegarde incomplète (.ctrmod.toc absent)')
        elif os.path.getsize(pak_tool.real(arc)) < int(info.get('original_size') or 0):
            problems.append(f'{name} : plus petite qu\'à l\'installation (jeu réinstallé ou mis à jour ?) — non touchée')
        else:
            mods.append(name)
    videos = sorted(f[:-len(VIDEO_OFF)] for f in pak_tool.listdir(archives) if f.endswith('.bk2' + VIDEO_OFF))
    chunks = os.path.exists(pak_tool.real(os.path.join(os.path.dirname(archives), track_clone.CHUNKS_IGX)) + '.ctrmod')
    # update3.pak de l'editeur (fichiers ajoutes et menu, custom_category) : supprime ; un update3.pak sans index
    # n'est pas a nous (mod) et reste
    layer = os.path.exists(os.path.join(archives, custom_category.LAYER_INDEX))
    if layer:
        mods.append(custom_category.LAYER)
    return {'created': created, 'categories': cats, 'installed': installed, 'archives': mods, 'videos': videos,
            'chunks': chunks, 'problems': problems, 'layer': layer,
            'nothing': not (created or cats or installed or mods or videos or chunks or st)}


def _close_archives():
    """Archives ouvertes par pak_tool fermees (Windows refuse de supprimer / tronquer un fichier ouvert)."""
    pak_tool.invalidate_cache()
    for hit in list(pak_tool._orig_cache.values()):
        hit[1].f.close()
    pak_tool._orig_cache.clear()


def restore_game(archives, progress=None):
    """Remet le jeu d'origine (voir le module). progress(fraction, texte) facultatif. -> rapport [lignes]."""
    step = progress or (lambda f, t: None)
    plan = restore_plan(archives)
    report = []
    _close_archives()
    # 0. ecran titre de « Tester en jeu » encore en place (essai jamais remis) : la sauvegarde de TOC d'update2, s'il y en
    # a une, ne suffit pas toujours (les ajouts vont dans update3, update2 peut ne pas en avoir)
    import quick_test
    if quick_test.PATCH_MARK in pak_tool.read_latest(archives, quick_test.MANAGER, original=False)[0]:
        quick_test.uninstall(archives)
        report.append('écran titre d\'origine remis')
        plan = restore_plan(archives)
    _close_archives()                                     # la lecture ci-dessus a ouvert update3.pak : Windows refuserait de le supprimer
    # 1. pistes creees : archives supprimees (avec leurs sauvegardes)
    step(0.0, 'pistes créées')
    for t in plan['created']:
        for p in t['paks']:
            path = os.path.join(archives, p)
            for f in (path, pak_tool.backup_path(path), pak_tool.toc_backup_path(path)):
                if os.path.exists(f):
                    os.remove(f)
        report.append(f"piste créée supprimée : {t['display']} ({t['id']})")
    # 2. archives modifiees : en-tete et taille d'origine
    n = len(plan['archives'])
    for k, name in enumerate(plan['archives']):
        step(0.1 + 0.75 * k / max(1, n), f'archive {k + 1} / {n} : {name}')
        if name == custom_category.LAYER:
            for f in (pak_tool.real(custom_category.layer_path(archives)), os.path.join(archives, custom_category.LAYER_INDEX)):
                if os.path.exists(f):
                    os.remove(f)
            report.append(f'{name} de l\'éditeur supprimé')
            continue
        pak_tool.uninstall(os.path.join(archives, name))
        report.append(f'archive remise d\'origine : {name}')
    # 3. menu du jeu, chunks.igx, videos, registre
    step(0.9, 'menu du jeu')
    st_path = custom_category.state_path(archives)
    if os.path.exists(st_path):
        os.remove(st_path)
        report.append('menu du jeu : catégories d\'origine')
    game_dir = os.path.dirname(archives)
    ch = pak_tool.real(os.path.join(game_dir, track_clone.CHUNKS_IGX))
    if os.path.exists(ch + '.ctrmod'):
        os.replace(ch + '.ctrmod', ch)
        report.append('chunks.igx d\'origine remis')
    for v in plan['videos']:
        src = pak_tool.real(os.path.join(archives, v + VIDEO_OFF))
        dst = os.path.join(os.path.dirname(src), v)
        if os.path.exists(dst):
            report.append(f'vidéo {v} : déjà présente, copie mise de côté laissée')
            continue
        os.replace(src, dst)
        report.append(f'vidéo du menu remise : {v}')
    reg = os.path.join(archives, REGISTRY)
    if os.path.exists(reg):
        os.remove(reg)
    report += [f'NON RESTAURÉ — {p}' for p in plan['problems']]
    _close_archives()
    step(1.0, 'terminé')
    return report
