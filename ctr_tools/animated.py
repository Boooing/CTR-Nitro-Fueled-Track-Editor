"""Objets animes du jeu (acteurs a skin : animaux, bannieres, hologrammes, ballons...) copies d'une piste a une autre.

Un objet anime est une CGameEntity dont le CGameEntityData donne un skin d'acteur (_skinName, ex.
'Octane\\Levels\\Global\\Props\\Penguin') ; l'animation est jouee par un script (CVscComponentData -> EXNM drapeau 0
'<script>Data' / '<script>') ou par un CAnimateEntityComponentData (nom d'animation en boucle). Le fichier qui la
contient declare dans sa table TDEP :
  * le skin : '<build>actors:/<skin>.igz' (+ '.hkx') et '<build>data:/anims/<skin>.hka', sous le nom court du skin ;
  * chaque script : 'vsc:/...igz' sous le nom du script.
Copier l'objet = IgzFile.import_entity dans un fichier de la piste + ces entrees TDEP + les fichiers declares au
manifeste de streaming de la piste (sinon le jeu ne les charge pas) + copie dans l'archive de la piste de ceux qui ne
sont pas dans une archive commune.

Seuls les objets AUTONOMES sont proposes : aucun handle (RHND) vers une autre entite (spline de trajet, point de
depart, entite a attacher...), qui n'existerait pas dans la piste de destination.
"""
import os
import re

import library
import pak_tool
from igz import IgzFile
from model_build import tdep_entries

ENTITY_TYPES = ('CGameEntity',)
# schema de la TDEP -> (prefixe du chemin logique, type au manifeste) ; None : fichier commun, deja charge
SCHEMES = {
    'actors': ('actors/', None),
    'anims': ('anims/', 'havokanimdb'),
    'vsc': ('vsc/', 'vsc'),
    'vfx': ('vfx/', 'effect'),
    'sounds': ('sounds/', 'sound_bank'),
    'materials': ('materialinstances/', 'material_instances'),
    'textures': ('textures/', 'texture'),
    'models': ('models/', 'model'),
}
COMMON = re.compile(r'^(shaders|data:/loosedata|data:/LooseData)', re.I)


def skin_of(z, ent):
    """_skinName de l'entite (ou None)."""
    data = z.deref(ent + 0x40)
    if data is None or z.objects.get(data) != 'CGameEntityData':
        return None
    return z.dump_object(data).get('_skinName') or None


def _spans(z, ent):
    objs, mem = z.reachable(ent)
    out = {o: z.size_of(z.objects[o]) for o in objs}
    for m, s in mem.items():
        out[m] = max(int(s), 8)
    return out


def links(z, ent):
    """Scripts (noms d'EXNM drapeau 0 vises) et handles vers d'autres entites (EXNM drapeau 1 / EXID) de l'entite."""
    flag0, flag1, exid = z._exnm_flagged(0), z._exnm_flagged(1), z.exid_pairs()
    scripts, handles = set(), set()
    for a, size in _spans(z, ent).items():
        for p in z._marks_in('RNEX', a, size):
            v = z.u64(p) & 0x7FFFFFFFFFFFFFFF
            if v < len(flag0):
                scripts.add(flag0[v][1])
        for p in z._marks_in('RHND', a, size):
            v = z.u32(p)
            handles.add(flag1[v & 0x7FFFFFFF] if v & 0x80000000 else ('EXID', exid[v] if v < len(exid) else v))
    return sorted(scripts), sorted(handles, key=str)


def entity_tdep(z, ent):
    """Entrees TDEP du fichier necessaires a l'entite : celles du skin (nom court) et des scripts qu'elle vise."""
    skin = skin_of(z, ent)
    short = skin.replace('\\', '/').split('/')[-1].lower() if skin else None
    scripts, _ = links(z, ent)
    want = {s.lower() for s in scripts} | ({short} if short else set())
    return [(n, p) for n, p in tdep_entries(z) if n.lower() in want]


def _logical(dep):
    """'<build>actors:/X/Y.igz' -> ('actors/X/Y.igz', schema) ; 'data:/anims/..' -> anims ; None si commun."""
    dep = dep.replace('<build>', '')
    if COMMON.match(dep):
        return None, None
    scheme, _, rest = dep.partition(':/')
    if scheme == 'data' and rest.lower().startswith('anims/'):
        return rest, 'anims'
    if scheme not in SCHEMES:
        return None, None
    return SCHEMES[scheme][0] + rest, scheme


def _manifest_type(logical, scheme):
    low = logical.lower()
    if scheme == 'actors':
        return 'havokrigidbody' if low.endswith('.hkx') else 'actorskin'
    if scheme == 'models' and low.endswith('.hkx'):
        return 'havokrigidbody'
    if scheme == 'sounds' and not low.startswith('sounds/banks/'):
        return 'sound_sample'
    return SCHEMES[scheme][1]


def install_files(archives, tdep, track_pak, donor_pak):
    """Fichiers a declarer et a copier pour des entrees TDEP (recursif : skin -> materiaux -> textures, script ->
    effets, sons...). -> (entrees du manifeste [(type, chemin)], copies {chemin logique: archive source},
    introuvables [chemin])."""
    entries, copies, missing, seen = [], {}, [], set()
    todo = [_logical(p) for _, p in tdep]
    while todo:
        logical, scheme = todo.pop()
        if not logical or logical.lower() in seen:
            continue
        seen.add(logical.lower())
        typ = _manifest_type(logical, scheme)
        src = None
        if not library.available(archives, logical, track_pak):
            src = library.find_pak(archives, logical, (donor_pak,))
            if src is None:
                missing.append(logical)
                continue
            copies[logical] = src
        if typ:
            entries.append((typ, logical))
        if scheme in ('textures', 'anims') or logical.lower().endswith(('.hkx', '.hka')):
            continue
        try:
            data = pak_tool.read_latest(archives, logical, src or track_pak)[0]
            deps = tdep_entries(IgzFile(data))
        except Exception:  # noqa: BLE001 - fichier sans TDEP lisible : rien de plus a suivre
            continue
        todo += [_logical(p) for _, p in deps]
    # ordre du jeu : textures, materiaux, puis le reste
    rank = {'texture': 0, 'material_instances': 1}
    entries.sort(key=lambda e: rank.get(e[0], 2))
    # .hkx d'acteur cite par la TDEP mais absent du jeu (la plupart des skins) : rien a charger
    missing = [m for m in missing if not m.lower().endswith('.hkx')]
    return entries, copies, missing


PREFIX = 'EdAnim_'      # entites copiees par l'editeur (nom + numero)
# composants admis : animation, script, sons et effets d'ambiance, mouvement sur place (balancement, rotation : un
# mouvement sur une spline a un handle et n'est pas propose). Le reste (caisses, declencheurs, reapparition,
# physique...) a un role dans la course : objet ecarte du catalogue
SAFE = {'CVscComponentData', 'CAnimateEntityComponentData', 'CAmbientAudioComponentData', 'CLoopingVfxComponentData',
        'CSoundBankListComponentData', 'CMovementControllerComponentData', 'CModelComponentData', 'CStaticComponentData'}
CUSTOM_PAK = re.compile(r'^t9\d\d_', re.I)          # pistes creees par l'editeur : copies de pistes du jeu


def components(z, ent):
    data = z.deref(ent + 0x40)
    table = z.deref(data + 0x10) if data is not None else None
    out = []
    for _, v in (z.hash_items(table) if table is not None else []):
        off = int(v['@ref'], 16) if isinstance(v, dict) and '@ref' in v else None
        if off is not None and z.objects.get(off):
            out.append(z.objects[off])
    return out


DESIGNERS = re.compile(r'\b(dmorin|mmercier|tmichel|fclaveau|flaliberte|marichard|mmercier)\b', re.I)


def anim_hints(z, ent):
    """Chaines des parametres de l'entite (script, CAnimateEntityComponentData) : noms d'animation joues en jeu."""
    out = []
    for a, size in _spans(z, ent).items():
        for p in z._marks_in('RSTT', a, size):
            try:
                s = z.string(z.u32(p))
            except Exception:  # noqa: BLE001 - chaine illisible
                continue
            if s and not s.startswith('instance_') and s not in out and len(s) < 80:
                out.append(s)
    return out


def nice_name(entity, skin=''):
    """'Cheering_Penguin_04' -> 'Cheering Penguin' ; noms d'auteur (dmorin...), 'CGameEntity', 'T213 ' et noms
    techniques retires ; sinon le nom du skin."""
    n = entity or ''
    if 'entityData' in n or n.startswith('CGameEntity'):
        n = ''
    n = DESIGNERS.sub('', n.replace('_', ' '))
    n = re.sub(r'^[TA]\d{3}\s+', '', n)
    n = re.sub(r'[\s\d]+$', '', n)
    n = re.sub(r'\s+', ' ', n).strip()
    if not n:
        n = re.sub(r'\s+', ' ', re.sub(r'^[TA]\d{3}\s+', '', skin.replace('_', ' '))).strip()
    return n[:1].upper() + n[1:]


def scan(archives, step=None):
    """Catalogue des objets animes autonomes du jeu : [{id, pak, file, entity, name, skin, actor, scripts, track}], un
    par (skin, scripts, nom). step(fraction, texte) : avancement."""
    out, seen = [], set()
    paks = [p for p in library.track_paks(archives) if not CUSTOM_PAK.match(p)]
    for k, pak in enumerate(paks):
        if step:
            step(k / max(1, len(paks)), library.nice(pak))
        idx = pak_tool.cached_archive(os.path.join(archives, pak))[1]
        for key, e in sorted(idx.items()):
            if not key.startswith('maps/') or not key.endswith('.igz'):
                continue
            try:
                z = IgzFile(pak_tool.read_latest(archives, e.logical_name, pak)[0])
            except Exception:  # noqa: BLE001 - fichier illisible : ignore
                continue
            for name, o in z.root_objects():
                if not name or z.objects.get(o) not in ENTITY_TYPES:
                    continue
                skin = skin_of(z, o)
                if not skin:
                    continue
                if not set(components(z, o)) <= SAFE:
                    continue
                scripts, handles = links(z, o)
                if handles:
                    continue
                label = nice_name(name, skin.replace('\\', '/').split('/')[-1])
                sig = (skin.lower(), tuple(s.lower() for s in scripts), label.lower())
                if sig in seen:
                    continue
                seen.add(sig)
                out.append({'id': f'{pak}|{e.logical_name}|{name}', 'pak': pak, 'file': e.logical_name, 'entity': name,
                            'name': label, 'skin': skin.replace('\\', '/').split('/')[-1], 'scripts': scripts,
                            'actor': 'actors/' + skin.replace('\\', '/') + '.igz', 'track': library.nice(pak),
                            'hints': anim_hints(z, o)})
    out.sort(key=lambda r: (r['skin'].lower(), r['name'].lower()))
    return out


def set_pose(z, ent, pos, yaw=0.0, scale=1.0, rx=0.0, ry=0.0):
    """Position (+0x20), rotation (igEntityTransform +0x60 Euler x, y, z en radians, R = Rz*Ry*Rx comme le decor ;
    yaw = z) et echelle (+0x6C echelle globale, +0x70 xyz) d'une entite copiee."""
    import struct
    struct.pack_into('<3f', *z._loc(ent + 0x20), *[float(v) for v in pos])
    # CGameEntity._bitfield (+0x38) bit 0 = entite active au depart. A 0 sur des entites que leur piste cache (zam_02 a
    # zam_05 de Hyper Spaceway, monkey_test de Tiger Temple...) : copiees telles quelles, invisibles en jeu (2026-11-12)
    struct.pack_into('<I', *z._loc(ent + 0x38), z.u32(ent + 0x38) | 1)
    tr = z.deref(ent + 0x30)
    if tr is None:
        return
    struct.pack_into('<3f', *z._loc(tr + 0x60), float(rx), float(ry), float(yaw))
    g = z.f32(tr + 0x6C) or 1.0
    struct.pack_into('<3f', *z._loc(tr + 0x70), *([float(scale) / g] * 3))
    struct.pack_into('<I', *z._loc(tr + 0x7C), 1)                       # _isDirty


def reuse_scripts(tdep, declared):
    """Scripts deja declares par la piste sous un autre chemin (piste creee : 'vsc/common/Octane/T111_Crash_Cove/X.igz'
    devient '.../T901_Custom_Map/X.igz' a la copie) : la TDEP vise le leur. Declarer aussi celui de la piste source
    charge deux fois le meme type de script -> plantage au chargement (2026-11-12).
    declared = {nom de fichier en minuscules: chemin logique}. -> (tdep corrigee, entrees a suivre pour l'installation)."""
    out, follow = [], []
    for n, p in tdep:
        logical, scheme = _logical(p)
        base = os.path.basename(logical).lower() if logical else None
        if scheme == 'vsc' and base in declared and declared[base].lower() != logical.lower():
            out.append((n, 'vsc:/' + declared[base][len('vsc/'):]))
            continue
        out.append((n, p))
        follow.append((n, p))
    return out, follow


def inject(z, items, read, archives, track_pak, declared=None):
    """Copie les objets animes items = [{pak, file, entity, pos, yaw, scale}] dans le fichier z (IgzFile).
    read(chemin logique, archive) -> octets. declared : scripts deja declares par la piste (reuse_scripts).
    -> (entrees du manifeste, {fichier a copier: archive source}, rapport)."""
    donors, entries, copies, report = {}, [], {}, []
    declared = declared or {}
    for i, it in enumerate(items):
        key = (it['pak'], it['file'])
        if key not in donors:
            try:
                donors[key] = IgzFile(read(it['file'], it['pak']))
            except KeyError:
                donors[key] = None
        src = donors[key]
        ent = dict(src.root_objects()).get(it['entity']) if src else None
        if ent is None:
            report.append(f"objet animé introuvable : {it['entity']} ({it['pak']})")
            continue
        new = z.import_entity(src, ent, f'{PREFIX}{i:03d}', old_name=it['entity'])
        set_pose(z, new, it['pos'], it.get('yaw', 0.0), it.get('scale', 1.0), it.get('rx', 0.0), it.get('ry', 0.0))
        tdep, follow = reuse_scripts(entity_tdep(src, ent), declared)
        z.add_tdep(tdep)
        e, c, missing = install_files(archives, follow, track_pak, it['pak'])
        # scripts suivis (dependances comprises) : declares sous le chemin de la source ; un de meme nom deja declare
        # par la piste sous un autre chemin est garde a la place
        e = [x for x in e if not (x[0] == 'vsc' and os.path.basename(x[1]).lower() in declared
                                  and declared[os.path.basename(x[1]).lower()].lower() != x[1].lower())]
        entries += [x for x in e if x not in entries]
        copies.update(c)
        if missing:
            report.append(f"{it['entity']} : fichier(s) introuvable(s) {missing[:3]}")
    return entries, copies, report
