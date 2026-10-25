"""Bibliotheque d'objets du jeu : modeles de decor des autres pistes, places dans la piste modifiee.

Catalogue = modeles listes (type 'model') dans les manifestes de streaming des pistes et arenes
(packages/generated/maps/Octane/<P>/<P>_pkg.igz), sans les morceaux de terrain / collision / ombres.
Un objet place = une entite de decor dont CModelComponentData._fileName pointe le modele (comme un modele importe).

Dependances d'un modele (table TDEP) : 'materials:/X' -> materialinstances/X ; un materiau : 'textures:/X' ->
textures/X ('shaders:/...' : communs, deja charges). Pour que le jeu les charge, chaque fichier doit :
  * etre liste dans le manifeste de la piste modifiee (sinon invisible, comme le Nitro) ;
  * se trouver dans une archive montee pendant la course : update2 / update / permanent, ou l'archive de la piste
    (sinon il est copie depuis l'archive d'origine).
"""
import os
import re

import pak_tool
import pkg_manifest
from igz import IgzFile
from model_build import tdep_entries

TRACK_PAK = re.compile(r'^[ta]\d{3}_[a-z0-9_]+\.pak$')
COMMON_ARCHIVES = pak_tool.UPDATE_ARCHIVES + ('permanent.pak',)
# objets de decor seulement (pas les personnages / karts animes, ni les modeles de test)
INCLUDE = re.compile(r'^models/(levels|props)/', re.I)
# morceaux de piste (terrain, sections de route, paysage lointain, ombres, collision) : pas des objets a poser
EXCLUDE = re.compile(r'terrain|section|vista|shadow|collision|navmesh|_lod\d|proxy|occluder|blocker|skybox|skydome'
                     r'|^models/effects/|^models/vfx/|^models/levelassets/basic/|_ground\d*$|_road\d*$', re.I)
DEPS = {'materials': ('material_instances', 'materialinstances/'), 'textures': ('texture', 'textures/'),
        'models': ('model', 'models/')}


def track_paks(archives):
    """Archives des pistes et arenes (sans survols ni cinematiques)."""
    return sorted(f for f in os.listdir(archives) if TRACK_PAK.match(f) and 'flyby' not in f and 'outro' not in f)


def nice(pak):
    """'t134_dingo_canyon.pak' -> 'Dingo Canyon'."""
    return ' '.join(w.capitalize() for w in pak[:-4].split('_')[1:])


def group_of(logical):
    """Dossier lisible : 'models/levels/crash3/desert/x.igz' -> 'Crash3 / Desert',
    '.../octane/t134_dingo_canyon/...' -> 'Dingo Canyon'."""
    parts = logical.lower().split('/')[1:-1]
    if parts and parts[0] == 'levels':
        parts = parts[1:]
    if parts and parts[0] == 'octane' and len(parts) > 1:
        parts = parts[1:]
    out = []
    for p in parts:
        if re.match(r'^[ta]\d{3}_', p):
            out.append(nice(p + '.pak'))
        elif not p.endswith(('_assets', '_asset')):
            out.append(p.capitalize())
    return ' / '.join(dict.fromkeys(out)) or 'Divers'


def _home(logical, paks):
    """Archive de la piste nommee dans le chemin du modele ('.../T134_Dingo_Canyon/...'), sinon None."""
    for seg in logical.lower().split('/'):
        if seg + '.pak' in paks:
            return seg + '.pak'
    return None


def catalog(archives):
    """[{'model': chemin logique (casse de l'archive), 'pak': archive source, 'track': piste d'origine,
    'name', 'group'}], un par modele. Source : la piste nommee dans le chemin si elle l'utilise, sinon la
    premiere piste qui le liste."""
    users, found = {}, {}
    paks = track_paks(archives)
    for pak in paks:
        arc, idx, _ = pak_tool.cached_archive(os.path.join(archives, pak))
        man = pkg_manifest.manifest_logical(pak[:-4])
        if man.lower() not in idx:
            continue
        rows = pkg_manifest.entries(pak_tool.read_latest(archives, man, pak)[0])
        for typ, p in rows:
            if typ != 'model' or not p.endswith('.igz') or not INCLUDE.match(p) or EXCLUDE.search(p) \
                    or EXCLUDE.search(os.path.basename(p)[:-4]):
                continue
            users.setdefault(p, []).append(pak)
            if p not in found and p in idx:
                found[p] = idx[p].logical_name
    out = []
    for p, lst in users.items():
        logical = found.get(p) or _common_case(archives, p)
        if logical is None:
            continue                                     # modele introuvable : ignore
        home = _home(p, set(lst))
        pak = home or lst[0]
        out.append({'model': logical, 'pak': pak, 'track': nice(pak), 'name': os.path.basename(logical)[:-4],
                    'group': group_of(logical)})
    out.sort(key=lambda m: (m['group'].lower(), m['name'].lower()))
    return out


def _common_case(archives, p):
    for n in COMMON_ARCHIVES:
        path = os.path.join(archives, n)
        if os.path.exists(path):
            e = pak_tool.cached_archive(path)[1].get(p.lower())
            if e:
                return e.logical_name
    return None


def file_name(logical):
    """'models/Levels/X/Y.igz' -> 'models:\\Levels\\X\\Y.igb' (CModelComponentData._fileName)."""
    rel = logical.split('/', 1)[1]
    return 'models:\\' + os.path.splitext(rel)[0].replace('/', '\\') + '.igb'


def dependencies(read, model):
    """Fichiers necessaires au modele, lui compris : [(type de manifeste, chemin logique)], dans l'ordre
    textures, materiaux, modele. read(chemin logique) -> octets (KeyError si absent)."""
    out, todo, done = [], [('model', model)], set()
    while todo:
        typ, lg = todo.pop()
        if lg.lower() in done:
            continue
        done.add(lg.lower())
        out.append((typ, lg))
        if typ == 'texture':
            continue
        for _, dep in tdep_entries(IgzFile(read(lg))):
            scheme, _, rest = dep.partition(':/')
            if scheme in DEPS:
                t, prefix = DEPS[scheme]
                todo.append((t, prefix + rest))
    order = {'texture': 0, 'material_instances': 1, 'model': 2}
    return sorted(out, key=lambda e: order[e[0]])


def available(archives, logical, track_pak):
    """Le fichier est-il dans une archive montee pendant la course de la piste (version d'origine) ?"""
    for n in COMMON_ARCHIVES:
        p = os.path.join(archives, n)
        if os.path.exists(p) and logical.lower() in pak_tool.cached_archive(p)[1]:
            return True
    p = os.path.join(archives, track_pak)
    view = pak_tool.original_archive(p)
    idx = view[1] if view else pak_tool.cached_archive(p)[1]
    return logical.lower() in idx


def find_pak(archives, logical, prefer=()):
    """Archive de piste qui contient le fichier (les archives preferees d'abord), sinon None."""
    for pak in list(prefer) + track_paks(archives):
        p = os.path.join(archives, pak)
        if os.path.exists(p) and logical.lower() in pak_tool.cached_archive(p)[1]:
            return pak
    return None
