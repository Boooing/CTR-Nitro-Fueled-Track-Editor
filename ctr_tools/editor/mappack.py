"""Packs de maps (.zip) : exporter une ou plusieurs pistes modifiees, les reimporter (et installer) sur la piste de son
choix — sur ce PC ou chez quelqu'un d'autre qui a son propre jeu.

AUCUN fichier du jeu dans le zip : seulement ce que l'utilisateur a fait, sous des formes neutres.
  pack.json                      liste des maps
  <dossier>/map.json             description : decor, parcours, objets, reglages, noms, survol...
  <dossier>/models/<nom>.obj     maillage de chaque modele importe (coordonnees du jeu : pouces, Z en haut, origine =
                                 pivot de l'objet ; positions, normales, UV relus sans perte du .igz construit)
  <dossier>/textures/<nom>.<ext> image de chaque texture importee (fichier source s'il existe encore, sinon la
                                 texture du jeu construite, decodee)
  <dossier>/menu/<cle>.png       images de menu personnalisees
Les objets du jeu (bibliotheque, copies du decor d'origine) ne sont designes que par leur nom de fichier et
l'archive ou les trouver : ils viennent du jeu de celui qui importe.

Import sur une piste cible (rejoue l'edition avec les fonctions de l'editeur, sur ses fichiers d'origine) :
  1. piste cible remise a l'origine (copie pour « Annuler ») ; 2. « Nouvelle map » ; 3. textures et modeles
  reconstruits (gabarits du jeu), objets places, collision ; 4. ambiance, allegement ; 5. parcours : meme nombre
  de sections -> copie exacte (splines IA comprises), sinon boucle redecoupee comme « Creer le parcours » et splines
  IA a regenerer par la page ; 6. caisses, boosters, teleporteurs, grille, reapparitions, mini-carte, survol, nom
  et images de menu."""
import base64
import io
import json
import math
import os
import re
import struct
import time
import zipfile

import numpy as np

FORMAT = 'ctr-track-editor-pack'
VERSION = 1


_server = None


def bind(module):
    """Module du serveur en cours d'execution (server.py le donne a son import : lance en script, c'est __main__,
    et « import server » en chargerait une seconde copie sans dossier des archives ni des sauvegardes)."""
    global _server
    _server = module


def _S():
    if _server is None:
        import server                                  # utilise hors du serveur (scripts de test)
        return server
    return _server


def _slug(s):
    return re.sub(r'[^A-Za-z0-9_-]+', '_', s or '').strip('_')[:40] or 'map'


# -- maillage d'un modele construit par l'editeur ------------------------------------------------------
def read_mesh(data):
    """(positions, normales, uvs, triangles) d'un modele importe (.igz de build_model : sommets de 40 octets
    position 3f, normale 3f, UV half2 (v stocke 1 - v), tangente 3f ; indices u16). Autres formats : positions et
    UV seulement (normales recalculees a l'import)."""
    import preview
    from igz import IgzFile
    z = IgzFile(data)
    pos, nrm, uvs, tris = [], [], [], []
    for o, t in sorted(z.objects.items()):
        if t != 'igModelDrawCallData':
            continue
        vb = z.deref(z.deref(o + 0x48) + 0x20)
        ib = z.deref(z.deref(o + 0x50) + 0x20)
        fmt = z.deref(vb + 0x30)
        nv, ni = z.u32(vb + 0x0C), z.u32(ib + 0x0C)
        vdata, _ = z.memory_ref(vb + 0x20)
        idata, _ = z.memory_ref(ib + 0x20)
        if z.u32(fmt + 0x0C) != 40 or vdata is None or idata is None:
            mesh = preview.model_preview(data, lambda lg: b'')
            P, U, I = mesh['positions'].tolist(), mesh['uvs'].tolist(), mesh['indices'].tolist()
            return P, None, [[u, 1.0 - v] for u, v in U], [I[i:i + 3] for i in range(0, len(I), 3)]
        base = len(pos)
        vb_, vo = z._loc(vdata)
        for i in range(nv):
            p = struct.unpack_from('<3f3fee', vb_, vo + i * 40)
            pos.append(list(p[0:3]))
            nrm.append(list(p[3:6]))
            uvs.append([float(p[6]), 1.0 - float(p[7])])
        ib_, io_ = z._loc(idata)
        idx = struct.unpack_from(f'<{ni}H', ib_, io_)
        tris += [[base + idx[k], base + idx[k + 1], base + idx[k + 2]] for k in range(0, ni - 2, 3)]
    return pos, nrm, uvs, tris


def mesh_to_obj(name, pos, nrm, uvs, tris):
    out = [f'# CTR Track Editor pack : {name} — coordonnees du jeu (pouces, Z vers le haut), origine = pivot de l\'objet',
           f'o {name}']
    out += [f'v {p[0]:.4f} {p[1]:.4f} {p[2]:.4f}' for p in pos]
    out += [f'vt {u:.6f} {v:.6f}' for u, v in uvs]
    if nrm:
        out += [f'vn {n[0]:.5f} {n[1]:.5f} {n[2]:.5f}' for n in nrm]
        out += [f'f {a + 1}/{a + 1}/{a + 1} {b + 1}/{b + 1}/{b + 1} {c + 1}/{c + 1}/{c + 1}' for a, b, c in tris]
    else:
        out += [f'f {a + 1}/{a + 1} {b + 1}/{b + 1} {c + 1}/{c + 1}' for a, b, c in tris]
    return '\n'.join(out) + '\n'


def obj_to_mesh(text):
    """Relit un OBJ ecrit par mesh_to_obj (un indice par sommet)."""
    pos, nrm, uvs, tris = [], [], [], []
    for line in text.splitlines():
        if line.startswith('v '):
            pos.append([float(x) for x in line.split()[1:4]])
        elif line.startswith('vn '):
            nrm.append([float(x) for x in line.split()[1:4]])
        elif line.startswith('vt '):
            uvs.append([float(x) for x in line.split()[1:3]])
        elif line.startswith('f '):
            tris.append([int(t.split('/')[0]) - 1 for t in line.split()[1:4]])
    return pos, (nrm if len(nrm) == len(pos) else None), (uvs if len(uvs) == len(pos) else None), tris


# -- export ---------------------------------------------------------------------------------------------
def exportable_tracks():
    """Pistes qui ont des modifications enregistrees : [{track, title, objects, race}]."""
    S = _S()
    out = []
    for t in S.list_tracks():
        if not os.path.exists(S.saved_path(S.race_file(t))) and not S.custom_models(t) and not os.path.exists(S.newmap_path(t)):
            continue
        out.append({'track': t, 'title': _title(t), 'models': len(S.custom_models(t)),
                    'race': os.path.exists(S.saved_path(S.race_file(t)))})
    return out


def _title(track):
    S = _S()
    try:
        names = S.menu_info(track)['names']
        for lg in ('fr', 'en'):
            n = names.get(lg)
            if n and n['name'] != n['original']:
                return n['name']
        n = names.get('en') or names.get('fr')
        if n:
            return n['name']
    except Exception:  # noqa: BLE001
        pass
    return track


def _loop_from_lap(path, finish):
    """Boucle d'un tour (depart sur la ligne d'arrivee, ~300 po entre points) depuis le trace enregistre (splines
    de position raccordees, qui depassent la ligne de part et d'autre)."""
    P = np.asarray(path, float)
    f = np.asarray(finish[:2], float)
    d = np.linalg.norm(P[:, :2] - f, axis=1)
    n = len(P)
    i0 = int(np.argmin(d[: max(1, n // 3)]))                       # pres du debut
    i1 = n // 2 + int(np.argmin(d[n // 2:]))                      # pres de la fin (meme ligne, un tour plus loin)
    return P[i0:i1].tolist() if i1 - i0 > 10 else P.tolist()


def export_track(track, zf, folder):
    """Ecrit <folder>/... de la piste dans le zip ; -> (entree de pack.json, lignes du rapport)."""
    S = _S()
    from decor import DecorFile, model_logical_path
    import preview
    from PIL import Image
    report = []
    mp = {'source_track': track, 'title': _title(track), 'created': time.strftime('%Y-%m-%d %H:%M')}

    # -- decor : objets importes, objets de la bibliotheque, copies et modifications du decor d'origine
    links, reg, texreg = S.load_links(track), S.custom_models(track), S.custom_textures(track)
    newmap = S.newmap_settings(track)
    mp['newmap'] = {'strip_ground': bool(newmap.get('strip_ground')), 'strip_art': bool(newmap.get('strip_art')),
                    'move_away': list(newmap.get('move_away') or [])}
    objects, originals, used_models = [], {}, set()
    for art in S.art_files(track):
        df = DecorFile(S.base_file(track, art)[0])
        orig_ids = S.original_ids(track, art)
        orig = {o['id']: o for o in DecorFile(S.pak_tool.read_latest(S.ARCHIVES, art, S.track_pak(track))[0]).objects()}
        same = lambda a, b: all(abs(x - y) < 1e-3 for k in ('pos', 'euler', 'scale') for x, y in zip(a[k], b[k]))
        present = set()
        for o in df.objects():
            if (o['name'] or '').startswith(S.BOOST_VISUAL_PREFIX):
                continue                                   # dessin des boosters : refait avec les boosters
            lk = links.get(art, {}).get(str(o['id']))
            entry = {'name': o['name'], 'pos': o['pos'], 'euler': o['euler'], 'scale': o['scale']}
            if isinstance(lk, dict) and 'custom' in lk and not lk.get('library'):
                entry.update(kind='model', model=lk['custom'], surface=lk.get('surface', 'auto'))
                used_models.add(lk['custom'])
            elif isinstance(lk, dict) and lk.get('library'):
                entry.update(kind='library', model=lk['custom'], pak=lk['library'], surface=lk.get('surface', 'auto'))
            elif o['id'] not in orig_ids:                  # copie d'un objet d'origine : modele du jeu de cette piste
                entry.update(kind='library', model=model_logical_path(o['model']), pak=S.track_pak(track),
                             surface='auto')
            else:
                present.add(o['id'])
                if o['id'] in orig and not same(o, orig[o['id']]):       # objet d'origine deplace
                    originals.setdefault(art, {'moves': {}, 'deleted': []})['moves'][str(o['id'])] = \
                        {'pos': o['pos'], 'euler': o['euler'], 'scale': o['scale']}
                continue
            objects.append(entry)
        if art not in (newmap.get('strip_art') or []):
            gone = sorted(orig_ids - present)
            if gone:
                originals.setdefault(art, {'moves': {}, 'deleted': []})['deleted'] = gone
    mp['objects'] = objects
    mp['originals'] = originals                            # rejoue seulement sur la meme piste (memes objets)

    # modeles importes : maillage en OBJ ; materiau = image importee, materiau du jeu (nom) ou gabarit
    mp['models'], textures = {}, {}
    for logical in sorted(used_models):
        p = S.custom_model_path(logical)
        if not os.path.exists(p):
            report.append(f'modèle manquant, ignoré : {os.path.basename(logical)}')
            continue
        name = os.path.basename(logical)[:-4]
        wall = S.wall_mesh(track, logical)
        if wall:                                           # mur invisible : sa forme de collision
            pos, tris = wall
            zf.writestr(f'{folder}/models/{name}.obj', mesh_to_obj(name, pos, None, [(0.0, 0.0)] * len(pos), tris))
            mp['models'][logical] = {'obj': f'models/{name}.obj', 'invisible': (reg.get(logical) or {}).get('wall', 'obj')}
            continue
        pos, nrm, uvs, tris = read_mesh(open(p, 'rb').read())
        zf.writestr(f'{folder}/models/{name}.obj', mesh_to_obj(name, pos, nrm, uvs, tris))
        mat = (reg.get(logical) or {}).get('material') or 'gabarit'
        tex = next((n for n, i in texreg.items() if i['material_id'] == mat), None)
        info = {'obj': f'models/{name}.obj'}
        if tex:
            info['texture'] = tex
            textures[tex] = texreg[tex]
        elif mat != 'gabarit':
            info['game_material'] = mat
        mp['models'][logical] = info
    mp['textures'] = {}
    for name, info in textures.items():
        src = info.get('source') or []
        if src and isinstance(src[0], str) and os.path.isfile(src[0]):
            ext = os.path.splitext(src[0])[1].lower() or '.png'
            zf.write(src[0], f'{folder}/textures/{name}{ext}')
            path = f'textures/{name}{ext}'
        else:                                              # source disparue : texture construite, decodee
            rgba, _ = preview.decode_texture(open(S.custom_file_path(info['files']['texture'][0]), 'rb').read(), 4096)
            buf = io.BytesIO()
            Image.fromarray(rgba).save(buf, 'PNG')
            zf.writestr(f'{folder}/textures/{name}.png', buf.getvalue())
            path = f'textures/{name}.png'
        mp['textures'][name] = {'file': path, 'alpha': bool(info.get('alpha')), 'size': info.get('size', 1024)}

    # -- parcours (par index : sections dans l'ordre de course depuis la ligne d'arrivee)
    tr = S.load_track(track)
    chain = S.race_chain(tr)
    race = None
    if chain:
        names = [t['name'] for t, _ in chain]
        ai = [s for s in tr['splines'] if s['kind'] == 'ai_paths']
        ai_out = []
        for s in ai:
            starts = [k for k, (t, _) in enumerate(chain) if s['name'] in (t.get('next_ai') or [])]
            ends = [k for k, (t, _) in enumerate(chain) if s['name'] in (t.get('previous_ai') or [])]
            if starts or ends:
                ai_out.append({'name': s['name'], 'points': s['control_points'], 'starts': starts, 'ends': ends,
                               'shortcut': bool(s.get('shortcut'))})
        idx = {a['name']: i for i, a in enumerate(ai_out)}
        path, _ = S.race_path_points(track)
        fin = chain[0][0]
        race = {
            'sections': [s['control_points'] for _, s in chain],
            'transitions': [{'position': t['position'], 'yaw': t.get('yaw') or 0.0, 'dimensions': t.get('dimensions'),
                             'increment_lap': bool(t.get('increment_lap'))} for t, _ in chain],
            'ai': ai_out,
            'starting': [idx.get(n) for n in tr.get('starting_splines') or []],
            'loop': _loop_from_lap(path, fin['position']),
            'grid': [{'pos': g['pos'], 'yaw': g['yaw']} for g in tr.get('start_grid') or []],
            'player_start': {'pos': tr['player_start']['pos'], 'yaw': tr['player_start']['yaw']} if tr.get('player_start') else None,
            'crates': [{k: c[k] for k in ('kind', 'pos', 'yaw', 'dims') if k in c} for c in tr.get('crates') or []],
            'teleporters': {str(names.index(n)): {'pos': tp['pos'], 'yaw': tp['yaw']}
                            for n, tp in (tr.get('teleporters') or {}).items() if n in names and tp.get('pos')},
        }
    mp['race'] = race
    road = json.load(open(S.road_source_path(track))) if os.path.exists(S.road_source_path(track)) else {}
    mp['road'] = [o['name'] for o in road.get('objects') or []]

    # -- reglages
    amb = json.load(open(S.ambiance_path(track))) if os.path.exists(S.ambiance_path(track)) else None
    mp['ambiance'] = amb
    mp['own_sky'] = bool(S._sky_name(S.IgzFile(S.pak_tool.read_latest(S.ARCHIVES, S.lighting_file(track), S.track_pak(track))[0])))
    mp['light'] = S.light_settings(track)
    mm = os.path.join(S.OUT_DIR, f'{track}_minimap.json')
    mp['minimap'] = {'nudge': (json.load(open(mm)).get('nudge') if os.path.exists(mm) else None)}
    # survol : plans modifies, reperes par type (complet / court), rang et plan final
    shots = S.flyby_info(track)
    mp['flyby'] = []
    for short in (False, True):
        mine = [s for s in shots if ('short' in s['pak'].lower()) == short]
        mp['flyby'] += [{'short': short, 'index': i, 'final': s['final'], 'model': s['model']}
                        for i, s in enumerate(mine) if s['custom']]
    fly = mp['flyby']
    # nom et images de menu (personnalises seulement)
    menu = {'names': {}, 'images': {}, 'hide_video': bool(S.menu_settings(track).get('hide_video'))}
    try:
        info = S.menu_info(track)
        menu['names'] = {lg: n['name'] for lg, n in info['names'].items() if n['name'] != n['original']}
        files = S.menu_logicals(track)
        for k in info['images']:
            orig, logical = S._menu_original(track, files[f'image_{k}'])
            p = S.saved_path(logical)
            if orig is None or not os.path.exists(p):
                continue
            rgba, _ = preview.decode_texture(open(p, 'rb').read(), 4096)
            buf = io.BytesIO()
            Image.fromarray(np.ascontiguousarray(rgba[::-1])).save(buf, 'PNG')   # stockees de bas en haut
            zf.writestr(f'{folder}/menu/{k}.png', buf.getvalue())
            menu['images'][k] = f'menu/{k}.png'
    except Exception as e:  # noqa: BLE001
        report.append(f'menu non exporté ({e})')
    mp['menu'] = menu
    zf.writestr(f'{folder}/map.json', json.dumps(mp, indent=1, ensure_ascii=False))
    report.append(f"{mp['title']} ({track}) : {len(objects)} objet(s), {len(mp['models'])} modèle(s), "
                  f"{len(mp['textures'])} texture(s)" + (f", {len(chain)} section(s)" if chain else ', sans parcours')
                  + (f', survol {len(fly)} plan(s)' if fly else ''))
    return {'id': folder, 'title': mp['title'], 'source_track': track, 'folder': folder,
            'objects': len(objects), 'race': bool(chain)}, report


def export_pack(req):
    """req = {tracks: [...], folder (dossier de destination, relatif au projet ou absolu), name} -> {path, report}."""
    S = _S()
    tracks = [t for t in req.get('tracks') or [] if t in S.list_tracks()]
    if not tracks:
        raise ValueError('aucune piste choisie')
    folder = req.get('folder') or os.path.join(S.PROJECT_DIR, 'exports')
    if not os.path.isabs(folder):
        folder = os.path.join(S.PROJECT_DIR, folder)
    os.makedirs(folder, exist_ok=True)
    titles = [_slug(_title(t)) for t in tracks]
    name = _slug(req.get('name')) if req.get('name') else 'CTR_maps_' + '_'.join(titles)[:60]
    path = os.path.join(folder, f'{name}_{time.strftime("%Y%m%d_%H%M")}.zip')
    report, maps = [], []
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for k, t in enumerate(tracks):
            S.progress.step(f'export de {t}', k / len(tracks))
            m, rep = export_track(t, zf, f'{k + 1:02d}_{titles[k]}')
            maps.append(m)
            report += rep
        zf.writestr('pack.json', json.dumps({'format': FORMAT, 'version': VERSION, 'created': time.strftime('%Y-%m-%d %H:%M'),
                                             'maps': maps}, indent=1, ensure_ascii=False))
        zf.writestr('LISEZMOI.txt', 'Pack de maps pour CTR Track Editor (Crash Team Racing Nitro-Fueled, PS4 1.21).\n'
                    'Ne contient aucun fichier du jeu : uniquement les creations de l\'auteur (modeles OBJ, images, reglages).\n'
                    'Importer : editeur > menu ⋯ > Importer un pack de maps (.zip).\n')
    return {'path': path, 'size': os.path.getsize(path), 'maps': maps, 'report': report}


def export_file(name):
    """Chemin d'un pack du dossier exports du projet (nom de fichier .zip seul), ou None."""
    S = _S()
    name = os.path.basename(name or '')
    p = os.path.join(S.PROJECT_DIR, 'exports', name)
    return p if name.lower().endswith('.zip') and os.path.isfile(p) else None


# -- import ---------------------------------------------------------------------------------------------
def packs_dir():
    return os.path.join(_S().OUT_DIR, 'packs')


def save_upload(data, filename):
    """Zip recu de la page -> out/editor/packs/<nom>.zip ; -> pack_info."""
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise ValueError('ce fichier n\'est pas un .zip')
    os.makedirs(packs_dir(), exist_ok=True)
    name = _slug(os.path.splitext(os.path.basename(filename or 'pack'))[0]) + '.zip'
    open(os.path.join(packs_dir(), name), 'wb').write(data)
    return pack_info(name)


def _open(pack):
    p = os.path.join(packs_dir(), os.path.basename(pack))
    zf = zipfile.ZipFile(p)
    meta = json.loads(zf.read('pack.json'))
    if meta.get('format') != FORMAT:
        raise ValueError('ce zip n\'est pas un pack de maps de CTR Track Editor')
    if int(meta.get('version', 0)) > VERSION:
        raise ValueError('pack créé par une version plus récente de l\'éditeur : mets l\'éditeur à jour')
    return zf, meta


def pack_info(pack):
    zf, meta = _open(pack)
    maps = []
    for m in meta['maps']:
        mp = json.loads(zf.read(f"{m['folder']}/map.json"))
        img = next((f"{m['folder']}/{mp['menu']['images'][k]}" for k in ('background', 'icon', 'emblem')
                    if k in (mp.get('menu') or {}).get('images', {})), None)
        maps.append({**m, 'names': mp.get('menu', {}).get('names', {}),
                     'preview': ('data:image/png;base64,' + base64.b64encode(zf.read(img)).decode()) if img else None,
                     'sections': len((mp.get('race') or {}).get('sections') or []), 'models': len(mp.get('models') or {})})
    return {'pack': os.path.basename(zf.filename), 'created': meta.get('created'), 'maps': maps}


def _data_url(zf, path):
    return 'data:image/png;base64,' + base64.b64encode(zf.read(path)).decode()


def _clean_target(track):
    """Piste cible remise a l'origine : fichiers enregistres et reglages de l'editeur."""
    S = _S()
    S.reset_track(track, 'all')
    S.apply_flyby(track, {})
    for p in (S.ambiance_path(track), S.light_path(track), S.road_source_path(track), S.menu_settings_path(track),
              os.path.join(S.OUT_DIR, f'{track}_minimap.json'), S.custom_textures_path(track)):
        if os.path.exists(p):
            os.remove(p)
    S.clear_caches()


def _unique_texture_name(track, want):
    """Nom libre pour une image importee : ni dans le registre de la piste, ni deja ecrit par une autre piste
    (fichiers communs out/editor/textures)."""
    S = _S()
    reg = S.custom_textures(track)
    base = S._clean_name(want, 'Texture')
    name, n = base, 1
    while name in reg or os.path.exists(S.custom_file_path(f'textures/ColorMap,textures@!custom!{name}_C`png,111.igz')):
        n += 1
        name = f'{base}_{n}'
    return name


def _place_decor(track, zf, folder, mp, report):
    """Textures, modeles et objets du pack dans le decor de la piste cible (fichier _Art principal)."""
    S = _S()
    from decor import DecorFile
    from model_build import build_model, complete_mesh
    import library
    # textures
    tex_mat = {}
    for name, t in (mp.get('textures') or {}).items():
        new = _unique_texture_name(track, name)
        r = S.create_texture(track, new, zf.read(f"{folder}/{t['file']}"), alpha=t.get('alpha'), size=t.get('size', 1024))
        info = S.custom_textures(track)[r['name']]
        tex_mat[name] = (info['material_name'], info['ns'], info['dep'], info['material_id'])
    catalog = {m['id']: m for m in S.material_catalog(track)}
    # modeles
    template = S.read_game_file(track, S.TEMPLATE)
    os.makedirs(os.path.join(S.OUT_DIR, 'models'), exist_ok=True)
    reg = S.custom_models(track)
    taken = {os.path.basename(k).lower() for k in reg}
    model_map, missing_mat = {}, set()
    for logical, info in S.progress.items(list((mp.get('models') or {}).items()), 'modèle {i} / {n}', 0.15, 0.55):
        want, name, n = os.path.basename(logical)[:-4], os.path.basename(logical)[:-4], 1
        while f'{name}.igz'.lower() in taken or os.path.exists(S.custom_model_path(f'{name}.igz')):
            n += 1
            name = f'{want}_{n}'
        taken.add(f'{name}.igz'.lower())
        pos, nrm, uvs, tris = obj_to_mesh(zf.read(f"{folder}/{info['obj']}").decode('utf-8'))
        if info.get('invisible'):                          # mur invisible
            model_map[logical] = S.write_wall_model(track, reg, name, pos, tris, wall=info['invisible'],
                                                    **{'import': f"pack {mp.get('title')} — {time.strftime('%d/%m %H:%M')}"})
            continue
        pos, nrm, uvs, tan = complete_mesh(pos, nrm, uvs, tris)
        if info.get('texture') in tex_mat:
            m = tex_mat[info['texture']]
            material, mat_id = m[:3], m[3]
        elif info.get('game_material') in catalog:
            m = catalog[info['game_material']]
            material, mat_id = (m['name'], m['ns'], m['dep']), m['id']
        else:
            if info.get('game_material'):
                missing_mat.add(info['game_material'].split('|')[-1])
            material, mat_id = None, 'gabarit'
        new_logical = f'models/{S.CUSTOM_DIR}/{name}.igz'
        open(S.custom_model_path(new_logical), 'wb').write(
            build_model(template, pos, nrm, uvs, tan, tris, f'{S.CUSTOM_DIR}/{name}', material))
        reg[new_logical] = {'name': name, 'vertices': len(pos), 'triangles': len(tris), 'material': mat_id,
                            'import': f"pack {mp.get('title')} — {time.strftime('%d/%m %H:%M')}"}
        model_map[logical] = new_logical
    S.save_custom_models(track, reg)
    if missing_mat:
        report.append(f'{len(missing_mat)} matériau(x) du jeu absents de cette piste : texture du gabarit '
                      f'({", ".join(sorted(missing_mat)[:4])}{"…" if len(missing_mat) > 4 else ""})')
    # objets
    art = S.main_art(track)
    df = DecorFile(S.base_file(track, art)[0])
    tmpl = S.template_object(track, art)
    if tmpl is None:
        raise ValueError(f'{os.path.basename(art)} : aucun objet modèle à copier')
    used = set(df.names.values())
    specs, pending, names = [], [], {}
    for o in mp.get('objects') or []:
        if o['kind'] == 'model' and o['model'] not in model_map:
            continue
        name, k = o['name'] or 'Objet', 1
        while name in used:
            k += 1
            name = f"{o['name']}_{k}"
        used.add(name)
        names[o['name']] = name
        specs.append((tmpl, name, [float(v) for v in o['pos']], [float(v) for v in o['euler']], [float(v) for v in o['scale']]))
        pending.append(o)
    S.progress.step('écriture du décor', 0.6)
    created = df.duplicate_many(specs)
    links = S.load_links(track)
    lib_missing = 0
    for new_id, o in zip(created, pending):
        if o['kind'] == 'model':
            logical = model_map[o['model']]
            df.set_model(new_id, 'models:\\' + S.CUSTOM_DIR.replace('/', '\\') + '\\' + os.path.basename(logical)[:-4] + '.igb')
            links.setdefault(art, {})[str(new_id)] = {'custom': logical, 'surface': o.get('surface', 'auto')}
        else:
            if library.find_pak(S.ARCHIVES, o['model'], (o['pak'],)) is None:
                lib_missing += 1
            df.set_model(new_id, library.file_name(o['model']))
            links.setdefault(art, {})[str(new_id)] = {'custom': o['model'], 'surface': o.get('surface', 'auto'),
                                                      'library': o['pak']}
    S.save_links(track, links)
    S.write_art(track, art, df)
    if lib_missing:
        report.append(f'{lib_missing} objet(s) du jeu introuvables dans tes archives (gardés, mais invisibles)')
    if mp.get('road'):
        json.dump({'objects': [{'file': art, 'name': names.get(n, n)} for n in mp['road']]},
                  open(S.road_source_path(track), 'w'), indent=1)
    report.append(f'décor : {len(created)} objet(s), {len(model_map)} modèle(s), {len(tex_mat)} texture(s)')
    return names


def _chain_from(tr, start):
    """[(transition, spline de position suivante)] dans l'ordre de course depuis la transition `start` (comme
    server.race_chain, qui part de la premiere ligne d'arrivee)."""
    by = {s['name']: s for s in tr['splines'] if s['kind'] == 'position_paths'}
    out, seen, t = [], set(), start
    while t and t['name'] not in seen:
        seen.add(t['name'])
        nxt = [n for n in t.get('next_position') or [] if n in by]
        if not nxt:
            break
        out.append((t, by[nxt[0]]))
        # transition suivante pas encore vue ; celles qui reviennent sur la meme spline en dernier (Coco Park :
        # Spline_Transition_002 de 201_OLD vers 201_OLD, la vraie suite est Spline_Transition_003 vers 301_OLD)
        cands = [x for x in tr['transitions'] if nxt[0] in (x.get('previous_position') or []) and x['name'] not in seen]
        cands.sort(key=lambda x: bool(set(x.get('next_position') or []) & set(x.get('previous_position') or [])))
        t = cands[0] if cands else None
    return out


def _race_request(track, mp, report):
    """Requete d'enregistrement du parcours (comme la page) pour la piste cible ; -> (req, splines IA a regenerer)."""
    S = _S()
    import route_gen
    race = mp['race']
    tgt = S.load_track(track)
    chain = S.race_chain(tgt)
    if not chain:
        raise ValueError(f'{track} : pas de ligne d\'arrivée reliée aux splines de position')
    nt, ns = len(chain), len(race['sections'])
    req = {'track': track, 'splines': {}, 'transitions': {}, 'new_splines': [], 'deleted': []}
    if nt != ns:
        # cible ramenee au nombre de sections du pack (transitions ajoutees / retirees) : copie exacte des IA
        plan = S.plan_sections(tgt, ns)
        if plan:
            req.update(plan)
            chain = S.race_chain(tgt)
            report.append(f'sections : {nt} sur {track}, {ns} dans le pack — '
                          f"{len(plan['new_transitions'])} transition(s) ajoutée(s), {len(plan['deleted_transitions'])} retirée(s)")
            nt = len(chain)
            for t in tgt['transitions']:                   # listes de position recablees, IA des transitions ajoutees
                e = req['transitions'].setdefault(t['name'], {})
                e.update(previous_position=t['previous_position'], next_position=t['next_position'])
                if t['name'] in {x['name'] for x in plan['new_transitions']}:
                    e.update(previous_ai=t['previous_ai'], next_ai=t['next_ai'], increment_lap=False)
    tnames = [t['name'] for t, _ in chain]
    dims = [t['dimensions'] for t in race['transitions'] if t.get('dimensions')]
    hw = float(np.median([d[1] for d in dims])) / 2 - 800 if dims else 1500.0
    loop = {'points': race['loop'], 'half_widths': [max(600.0, hw)] * len(race['loop'])}
    # autres traces complets de la piste (Slide Coliseum : deux tours de 5 et 7 sections, chacun sa ligne
    # d'arrivee) : chacun redecoupe sur le parcours du pack ; leurs splines IA sont alors regenerees (page)
    others = []
    for t0 in tgt['transitions']:
        if t0.get('increment_lap') and t0['name'] not in tnames:
            others.append(_chain_from(tgt, t0))
    regen_ai = nt != ns or any(others)
    if nt == ns:
        sections, trans = race['sections'], race['transitions']
    else:                                                  # autre nombre de sections : boucle redecoupee
        lay = route_gen.layout(loop, nt)
        sections, trans = lay['sections'], lay['transitions']
        report.append(f'parcours : {ns} sections dans le pack, {nt} sur {track} : tracé redécoupé, splines IA à régénérer')
    for ch in others:
        if not ch:
            continue
        lay = route_gen.layout(loop, len(ch))
        for k, (t, s) in enumerate(ch):
            req['splines'][s['name']] = lay['sections'][k]
            tt = lay['transitions'][k]
            req['transitions'].setdefault(t['name'], {}).update(
                position=tt['position'], yaw=tt.get('yaw') or 0.0, dimensions=tt.get('dimensions') or t.get('dimensions'))
        report.append(f'autre tracé de {track} ({len(ch)} sections, depuis {ch[0][0]["name"]}) posé sur le parcours')
    for k, ((t, s), pts) in enumerate(zip(chain, sections)):
        req['splines'][s['name']] = pts
        tt = trans[k]
        req['transitions'].setdefault(t['name'], {}).update(
            position=tt['position'], yaw=tt.get('yaw') or 0.0, dimensions=tt.get('dimensions') or t.get('dimensions'))
    # embranchements (autres splines de position entre deux transitions du tour, Slide Coliseum : 12 pour 5
    # sections) : sur le trace de la section principale, sinon ils restaient sur l'ancienne piste (IA hors route)
    chain_pos = {s['name'] for _, s in chain}
    pos_names = {s['name'] for s in tgt['splines'] if s['kind'] == 'position_paths'}
    branches = 0
    for t in tgt['transitions']:
        if t['name'] not in tnames:
            continue
        k = tnames.index(t['name'])
        for n in t.get('next_position') or []:
            if n in pos_names and n not in chain_pos and n not in req['splines']:
                req['splines'][n] = sections[k]
                branches += 1
    if branches:
        report.append(f'{branches} embranchement(s) de {track} posé(s) sur le tracé')
    # transitions restees hors des traces : de passage (Coco Park Spline_Transition_002, de 201_OLD vers 201_OLD) au
    # milieu de leur spline de position, deja posee ; raccourcis de l'ancien trace (Sewer Speedway
    # SplineTransition_Shortcut) ecartes sous la carte comme les embranchements
    for t in tgt['transitions']:
        prev = [n for n in t.get('previous_position') or [] if n in req['splines']]
        if 'position' in req['transitions'].get(t['name'], {}):
            continue
        if not set(t.get('previous_position') or []) & set(t.get('next_position') or []):
            p = t.get('position') or [0.0, 0.0, 0.0]
            req['transitions'].setdefault(t['name'], {}).update(position=[p[0], p[1], S.FAR_BELOW])
            continue
        if not prev:
            continue
        pts = req['splines'][prev[0]]
        i = len(pts) // 2
        a, b = pts[max(i - 1, 0)], pts[min(i + 1, len(pts) - 1)]
        req['transitions'].setdefault(t['name'], {}).update(
            position=[pts[i][0], pts[i][1], pts[i][2] + 660.0], yaw=math.atan2(b[1] - a[1], b[0] - a[0]), dimensions=t.get('dimensions'))
    if not regen_ai:                                       # splines IA du pack, reliees aux memes transitions
        old_ai = [s['name'] for s in tgt['splines'] if s['kind'] == 'ai_paths']
        if not old_ai:
            raise ValueError(f'{track} : aucune spline IA modèle')
        taken = {s['name'] for s in tgt['splines']}
        new_names = []
        for i, a in enumerate(race['ai']):
            n, k = f'AI_Pack_{i + 1:03d}', 1
            while n in taken:
                k += 1
                n = f'AI_Pack_{i + 1:03d}_{k}'
            taken.add(n)
            new_names.append(n)
            req['splines'][n] = a['points']
            req['new_splines'].append({'name': n, 'template': old_ai[0]})
        req['deleted'] = req['deleted'] + old_ai
        for k, name in enumerate(tnames):
            req['transitions'][name]['next_ai'] = [new_names[i] for i, a in enumerate(race['ai']) if k in a['starts']]
            req['transitions'][name]['previous_ai'] = [new_names[i] for i, a in enumerate(race['ai']) if k in a['ends']]
        slots = len(tgt.get('starting_splines') or [])
        start = [new_names[i] for i in race.get('starting') or [] if i is not None and i < len(new_names)]
        if slots and start:
            req['starting_splines'] = [start[i % len(start)] for i in range(slots)]
    # grille, repere de depart, entites de l'ancien trace ecartees
    grid = tgt.get('start_grid') or []
    if grid and race.get('grid'):
        req['start_grid'] = [dict(g, pos=race['grid'][i % len(race['grid'])]['pos'], yaw=race['grid'][i % len(race['grid'])]['yaw'])
                             for i, g in enumerate(grid)]
    if tgt.get('player_start') and race.get('player_start'):
        req['player_start'] = race['player_start']
    req['design_poses'], req['race_entity_positions'] = S.old_route_moves(track)
    # caisses / boosters / TNT... (types que la piste cible sait copier)
    import powerup
    if not S.crates_supported(track):
        if race.get('crates'):
            report.append(f"{len(race['crates'])} caisse(s) / booster(s) non posés : fichier des caisses de {track} introuvable")
    else:
        orig = S.pak_tool.read_latest(S.ARCHIVES, S.crate_file(track), S.track_pak(track))[0]
        kinds = {c['kind'] for c in powerup.read_crates(orig, S.crates_in_design(track))}
        kinds |= {'boost'} | set(powerup.EXTRAS)
        crates = [dict(c, name=None) for c in race.get('crates') or [] if c['kind'] in kinds]
        if len(crates) < len(race.get('crates') or []):
            report.append(f"{len(race['crates']) - len(crates)} caisse(s) d'un type absent de {track} : ignorées")
        req['crates'] = crates
    # teleporteurs : meme transition (index), sinon la plus proche de celle du pack
    tps = {}
    for k, tp in (race.get('teleporters') or {}).items():
        k = int(k)
        if not regen_ai:
            tps[tnames[k]] = tp
        else:
            src = np.asarray(race['transitions'][k]['position'][:2])
            j = int(np.argmin([np.linalg.norm(np.asarray(t['position'][:2]) - src) for t in trans]))
            if j != 0:
                tps[tnames[j]] = tp
    if tps:
        req['teleporters'] = tps
    return req, regen_ai


def _flyby_models(track, mp):
    """Plans du pack sur ceux de la piste cible (survol complet / court, meme rang ; plan final -> plan final) ;
    plans sans equivalent : proposes d'apres le parcours."""
    S = _S()
    src = mp.get('flyby') or []
    if not src:
        return None
    shots = S.flyby_shots(track)
    try:
        auto = S.flyby_auto({'track': track, 'mode': 'auto'})['models']
    except ValueError:
        auto = {}
    out = {}
    for short in (False, True):
        mine = [s for s in shots if ('short' in s['pak'].lower()) == short]
        theirs = [f for f in src if f['short'] == short]
        for i, s in enumerate(mine):
            if s['final']:
                m = next((f['model'] for f in theirs if f['final']), None)
            else:
                m = next((f['model'] for f in theirs if not f['final'] and f['index'] == i), None)
            m = m or auto.get(s['key'])
            if m:
                out[s['key']] = m
    return out


def import_map(zf, folder, track, report):
    """Rejoue une map du pack sur la piste `track` ; -> True si les splines IA sont a regenerer (page)."""
    S = _S()
    mp = json.loads(zf.read(f'{folder}/map.json'))
    S.progress.step('remise à l\'origine de la piste', 0.0)
    _clean_target(track)
    # 1. « Nouvelle map »
    nm = mp.get('newmap') or {}
    if nm.get('strip_ground') or nm.get('strip_art') or nm.get('move_away'):
        S.progress.step('nouvelle map', 0.05)
        S.apply_newmap({'track': track, 'strip_ground': nm.get('strip_ground'),
                        'strip_art': S.art_files(track) if nm.get('strip_art') else [], 'move_away': nm.get('move_away') or []})
    # 2. decor d'origine modifie (meme piste seulement : memes objets)
    if mp.get('originals') and track == mp.get('source_track'):
        files = {art: {'moves': ed['moves'], 'duplicates': [], 'deleted': ed.get('deleted') or []}
                 for art, ed in mp['originals'].items() if art in S.art_files(track)}
        if files:
            S.save_decor({'track': track, 'files': files})
    elif mp.get('originals') and not nm.get('strip_art'):
        report.append('décor d\'origine modifié de la piste source : pas repris sur une autre piste')
    # 3. textures, modeles, objets, collision
    with S.progress.span(0.1, 0.62):
        _place_decor(track, zf, folder, mp, report)
    S.progress.step('collision', 0.62)
    report.append(S.sync_collision(track))
    # 4. ambiance et allegement
    amb = mp.get('ambiance')
    if amb is None and mp.get('own_sky') and track != mp.get('source_track'):
        amb = {'preset': 'day', 'values': {}, 'sky': mp['source_track']}
    if amb:
        S.set_ambiance({'track': track, 'preset': amb.get('preset', 'day'), 'values': amb.get('values') or {},
                        'sky': amb.get('sky') or ''})
    light = mp.get('light') or {}
    if int(light.get('collision_cell') or 0):
        S.apply_light({'track': track, 'collision_cell': light['collision_cell']})
    # 5. parcours, caisses, teleporteurs, grille
    regen_ai = False
    if mp.get('race'):
        S.progress.step('parcours', 0.7)
        req, regen_ai = _race_request(track, mp, report)
        saved = S.save_track(req)['report']
        report += [l for l in saved[:-3] if str(l).startswith('caisses')] + saved[-3:]
        S.progress.step('chutes et réapparitions', 0.8)
        try:
            report += S.auto_falls({'track': track, 'spacing': 50, 'killz': True, 'zones': True})['report']
        except ValueError as e:
            report.append(f'réapparitions : {e}')
        S.progress.step('mini-carte', 0.86)
        try:
            S.generate_minimap(track)
            nudge = (mp.get('minimap') or {}).get('nudge')
            if nudge and any(nudge):
                S.generate_minimap(track, move=nudge)
        except Exception as e:  # noqa: BLE001
            report.append(f'mini-carte : {e}')
        fly = _flyby_models(track, mp)
        if fly:
            report += S.apply_flyby(track, fly)
    # 6. nom et images de menu
    menu = mp.get('menu') or {}
    if menu.get('names') or menu.get('images') or menu.get('hide_video'):
        S.progress.step('nom et images', 0.92)
        S.apply_menu({'track': track, 'names': menu.get('names') or {}, 'hide_video': menu.get('hide_video'),
                      'images': {k: _data_url(zf, f'{folder}/{p}') for k, p in (menu.get('images') or {}).items()}})
    return regen_ai


def import_pack(req):
    """req = {pack, maps: [{id (dossier), target}]} -> {results: [{target, title, report, regen_ai}]}."""
    S = _S()
    zf, meta = _open(req['pack'])
    by_id = {m['folder']: m for m in meta['maps']}
    jobs = [(m['id'], m['target']) for m in req.get('maps') or [] if m.get('id') in by_id]
    targets = [t for _, t in jobs]
    if len(set(targets)) != len(targets):
        raise ValueError('deux maps vers la même piste : choisis une piste différente pour chacune')
    tracks = set(S.list_tracks())
    results = []
    for k, (folder, target) in enumerate(jobs):
        if target not in tracks:
            raise ValueError(f'piste inconnue : {target}')
        title = by_id[folder]['title']
        report = []
        with S.progress.span(k / len(jobs), (k + 1) / len(jobs), f'{title} → {target}'):
            regen = S.with_history(target, f'import du pack : {title}', lambda: import_map(zf, folder, target, report))
        results.append({'target': target, 'title': title, 'report': report, 'regen_ai': regen})
    return {'results': results}
