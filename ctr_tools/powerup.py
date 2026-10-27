"""Caisses d'objets (fichier <Piste>_Power_Up.igz) : lecture, reecriture, placement automatique le long du trace.

Fichier (Crash Cove) : 21 CGameEntity racine « crate_question_NNN » (caisses « ? ») et « crate_fruit_N » (caisses de
fruits Wumpa). Chaque caisse = position (+0x20), igEntityTransform, igComponentList propres ; les donnees
(CGameEntityData : composants caisse, declencheur, reapparition...) sont PARTAGEES par toutes les caisses d'un type
(« PowerUpCrate_entityData_gen » / « WumpaFruitCrate_entityData_gen »). Position = au sol (boite 30 x 30 x 30 po
posee dessus). Une caisse ajoutee = copie d'une caisse d'origine du meme type ; le fichier est toujours reconstruit
depuis l'original (comme le decor : pas de blocs abandonnes qui s'accumulent).
"""
import collections
import math
import struct

import numpy as np

import ai_gen
from decor import ENTITY_TYPES, DecorFile

KINDS = {'question': 'PowerUpCrate_entityData_gen', 'fruit': 'WumpaFruitCrate_entityData_gen'}
PREFIX = {'question': 'crate_question_', 'fruit': 'crate_fruit_'}
LIFT = 5.0          # hauteur au-dessus du sol (caisses d'origine : 0 a 16 po)
# fruit pose : son origine est au centre du fruit (Turbo Track : 40 a 46 po au-dessus du sol ; a 5 po il etait a
# moitie dans le sol)
LIFTS = {'wumpa': 42.0}


def lift_of(kind):
    return LIFTS.get(kind, LIFT)


# Caisse sur une pente : inclinee pour reposer a plat sur le sol (sinon un coin s'enfonce ; une copie gardait meme
# l'inclinaison de la caisse d'origine copiee : Roo's Tubes, caisses de travers et enfoncees). Le jeu code une caisse
# inclinee par son Euler (+0x60, R = Rz Ry Rx) et 2 indicateurs de plus au champ +0x38 (Crash Cove : 0x1011081 a plat,
# 0x1013881 inclinee).
TILT_FLAGS = 0x2800
TILT_REACH = 40.0          # po : hauteur du sol mesuree a cette distance de part et d'autre (caisse : 30 po)
TILT_MAX = math.radians(35)  # au-dela : mur ou bord de route sous la mesure, caisse laissee a plat


def tilt_euler(height_at, x, y, z):
    """Euler [rx, ry, 0] qui aligne le haut de la caisse sur la normale du sol en (x, y) ; height_at(x, y, z) ->
    hauteur du sol ou None. [0, 0, 0] si le sol n'est pas mesurable ou trop raide (mur, bord)."""
    r = TILT_REACH
    hx = [height_at(x + d, y, z) for d in (-r, r)]
    hy = [height_at(x, y + d, z) for d in (-r, r)]
    if None in hx or None in hy:
        return [0.0, 0.0, 0.0]
    gx, gy = (hx[1] - hx[0]) / (2 * r), (hy[1] - hy[0]) / (2 * r)
    L = (gx * gx + gy * gy + 1.0) ** 0.5
    rx, ry = float(np.arcsin(gy / L)), float(np.arctan(-gx))
    if max(abs(rx), abs(ry)) > TILT_MAX or math.degrees(math.acos(1.0 / L)) < TILT_MIN_DEG:
        return [0.0, 0.0, 0.0]
    return [rx, ry, 0.0]


TILT_MIN_DEG = 3.0         # pente plus faible : caisse laissee a plat (Crash Cove laisse a plat jusqu'a ~5 deg)
# calcul compare aux caisses inclinees d'origine (sol d'origine) : ecart median 1,5 deg, max 2,8 (Roo's Tubes, 15 caisses)


def tilt_outdated(data, height_at, orig_data, tol=0.02, crates_only=False):
    """Caisses « ? » / fruits dont l'inclinaison enregistree ne suit pas la pente du sol (fichier ecrit avant ce calcul,
    ou sol modifie) : -> nombre. Les caisses d'origine restees a leur place gardent l'inclinaison du jeu : ignorees."""
    df = DecorFile(data)
    z = df.igz
    by_name = {n: o for o, n in df.names.items()}
    untouched = {(c['name'], tuple(c['pos'])) for c in read_crates(orig_data, crates_only)}
    n = 0
    for c in read_crates(data, crates_only):
        if (c['name'], tuple(c['pos'])) in untouched:
            continue
        o = by_name.get(c['name'])
        tr = z.deref(o + 0x30) if c['kind'] in KINDS and o is not None else None
        if tr is None:
            continue
        cur = struct.unpack_from('<3f', *z._loc(tr + 0x60))
        want = tilt_euler(height_at, *c['pos'])
        n += any(abs(a - b) > tol for a, b in zip(cur, want))
    return n


def _set_tilt(df, ent, pos, euler, flags):
    """Position + inclinaison d'une caisse ; indicateurs +0x38 = ceux du modele, + TILT_FLAGS si inclinee."""
    df.set_transform(ent, [float(v) for v in pos], euler)
    z = df.igz
    struct.pack_into('<I', *z._loc(ent + 0x38), flags | (TILT_FLAGS if any(abs(v) > 1e-6 for v in euler) else 0))

# Boosters (plaques turbo) : entite d'une autre piste copiee dans ce fichier (IgzFile.import_entity) — zone de
# declenchement (CTriggerVolumeBoxComponentData, dimensions profondeur / largeur / hauteur) + script
# « Scripts.Graph.common_TurboPadData » (vsc/common/race/common_turbopad.igz, deja dans update.pak : il faut
# seulement le lister dans le manifeste de la piste) ; donnees de boost, sons (banques communes) et vibration
# (permanent.pak) sont generiques. Le dessin au sol est un objet de decor separe (voir server).
BOOST_DONOR = ('T114_Sewer_Speedway', 'GPI_SpeedBoostZone006')
BOOST_PREFIX = 'TurboPad_'
BOOST_TDEP = [('common_TurboPad', 'vsc:/common/Race/common_TurboPad.igz'),
              ('ctr_pwrup_turboboost_rumble', 'vfx:/CTR/share/ctr_pwrup_turboboost_rumble.igz')]
BOOST_SCRIPT = 'vsc/common/race/common_turbopad.igz'
BOOST_DIMS = [800.0, 1000.0, 1000.0]   # profondeur (sens de course), largeur, hauteur (po) ; Sewer : 1000 x 3000 x 1000


# Autres objets du jeu, copies comme les boosters (entite complete d'un autre fichier, IgzFile.import_entity) :
#   * TNT / Nitro = caisses explosives posees du mode « cristaux » des arenes (CSpawnedExplosiveCrateComponentData :
#     explosent au contact, ralentissent, compte a rebours si on saute dessus) ; script, effets et modele TNT dans
#     permanent.pak ; modele Nitro dans update2.pak + un materiau present seulement dans l'archive de Rocky Road
#     (copie dans la piste a l'installation) ;
#   * fruit Wumpa pose au sol (Turbo Track : caisse « collectable » contenu 2, une unite, sans reapparition).
# donor = (archive, fichier, entite) ; tdep = dependances ajoutees au _Power_Up ; manifest = fichiers a declarer dans
# le manifeste de la piste ; copy = fichiers a copier dans l'archive de la piste (absents des archives communes).
_EXPLOSIVE_TDEP = [('CollisionMaterials', 'data:/LooseData/CollisionMaterials.igz'),
                   ('common_ExplosiveCrate', 'vsc:/common/PowerUp/common_ExplosiveCrate.igz')] + [
    (n, f'vfx:/CTR/share/{n}.igz') for n in (
        'ctr_crate_attach', 'ctr_crate_destroy', 'ctr_crate_destroy_kart', 'ctr_pwrup_explosive_crate_impact',
        'ctr_pwrup_explosive_crate_impact_juiced', 'ctr_pwrup_explosive_crates', 'ctr_pwrup_explosive_crates_juiced',
        'ctr_pwrup_explosive_crates_white_flash')]
_NITRO_MAT = 'materialinstances/levels/crash1/c1_factory_materials,octane_nitrocrate,8000000000000.igz'
EXTRAS = {
    'tnt': {'label': 'TNT', 'prefix': 'TNT_',
            'donor': ('a234_desert_storm.pak', 'maps/Octane/A234_Desert_Storm/A234_Desert_Storm_Race_Crystal.igz',
                      'SpawnedExplosiveCrate_fclaveau'),
            'tdep': _EXPLOSIVE_TDEP + [('TNTCrate', '<build>actors:/Octane/Levels/Crates/TNTCrate.hkx'),
                                       ('TNTCrate', '<build>actors:/Octane/Levels/Crates/TNTCrate.igz'),
                                       ('TNTCrate', '<build>data:/anims/Octane/Levels/Crates/TNTCrate.hka')],
            'manifest': [('vsc', 'vsc/common/powerup/common_explosivecrate.igz')], 'copy': []},
    'nitro': {'label': 'Nitro', 'prefix': 'Nitro_',
              'donor': ('a145_rocky_road.pak', 'maps/Octane/A145_Rocky_Road/A145_Rocky_Road_Race_Crystal.igz',
                        'SpawnedNitroCrate_01'),
              'tdep': _EXPLOSIVE_TDEP + [('Octane_NitroCrate', '<build>models:/Levels/Octane/Global/Crates/Octane_NitroCrate.hkx'),
                                         ('Octane_NitroCrate', '<build>models:/Levels/Octane/Global/Crates/Octane_NitroCrate.igz')],
              'manifest': [('vsc', 'vsc/common/powerup/common_explosivecrate.igz'),
                           ('material_instances', 'materialinstances/crash_crates_materials,octane_nitrocrate,00000420.igz'),
                           ('material_instances', _NITRO_MAT),
                           ('model', 'models/levels/octane/global/crates/octane_nitrocrate.igz')],
              'copy': [(_NITRO_MAT, 'a145_rocky_road.pak')]},
    'wumpa': {'label': 'fruit Wumpa', 'prefix': 'Wumpa_',
              'donor': ('t122_turbo_track.pak', 'maps/Octane/T122_Turbo_Track/T122_Turbo_Track_Design.igz', 'fruit_1'),
              'tdep': [('box', '<build>models:/LevelAssets/Basic/box.hkx'), ('box', '<build>models:/LevelAssets/Basic/box.igz'),
                       ('CollisionMaterials', 'data:/LooseData/CollisionMaterials.igz'),
                       ('common_WumpaFruit_Behavior', 'vsc:/common/common_WumpaFruit_Behavior.igz'),
                       ('ctr_hidden_wumpa_crate_glow', 'vfx:/CTR/share/ctr_hidden_wumpa_crate_glow.igz')],
              'manifest': [('vsc', 'vsc/common/common_wumpafruit_behavior.igz'),
                           ('effect', 'vfx/ctr/share/ctr_hidden_wumpa_crate_glow.igz')], 'copy': []},
}


def powerup_file(track):
    return f'maps/Octane/{track}/{track}_Power_Up.igz'


def extra_donor(kind, read):
    """(IgzFile, entite) modele d'un objet d'EXTRAS. read(chemin logique, archive) -> octets."""
    from igz import IgzFile
    pak, logical, name = EXTRAS[kind]['donor']
    z = IgzFile(read(logical, pak))
    return z, next(o for n, o in z.root_objects() if n == name)


def extra_kind(name):
    return next((k for k, e in EXTRAS.items() if (name or '').startswith(e['prefix'])), None)


def boost_donor(read):
    """(IgzFile, entite) de la plaque turbo modele. read(chemin logique, archive de piste) -> octets."""
    from igz import IgzFile
    t, name = BOOST_DONOR
    z = IgzFile(read(f'maps/Octane/{t}/{t}_Design.igz', t.lower() + '.pak'))
    return z, next(o for n, o in z.root_objects() if n == name)


def _trigger(df, ent):
    """Composant zone de declenchement d'une plaque (via la table de composants de ses donnees)."""
    z = df.igz
    table = z.deref(z.deref(ent + 0x40) + 0x10)
    for _, v in z.hash_items(table):
        o = int(v['@ref'], 16) if isinstance(v, dict) and '@ref' in v else None
        if o is not None and z.objects.get(o) == 'CTriggerVolumeBoxComponentData':
            return o
    return None


CONTENT_KINDS = {0: 'question', 1: 'fruit'}       # CCollectibleCrateComponentData._content


def _content_kind(df, ent):
    """Type d'une caisse d'apres son contenu, quand ses donnees ne portent pas le nom de Crash Cove (Roo's Tubes :
    donnees propres a chaque caisse « crate_question_005_entityData »). Caisse triple (Barin Ruins) : a part."""
    z = df.igz
    if 'triple' in (df.names.get(ent) or '').lower():
        return None
    data = z.deref(ent + 0x40)
    table = z.deref(data + 0x10) if data is not None else None
    for _, v in (z.hash_items(table) if table is not None else []):
        o = int(v['@ref'], 16) if isinstance(v, dict) and '@ref' in v else None
        if o is not None and z.objects.get(o) == 'CCollectibleCrateComponentData':
            return CONTENT_KINDS.get(z.dump_object(o).get('_content'))
    return None


def is_crate(kind):
    """Objet gere comme une caisse : caisses « ? » / fruits, boosters, TNT / Nitro / fruit Wumpa poses."""
    return kind in ('question', 'fruit', 'boost') or kind in EXTRAS


def read_crates(data, crates_only=False):
    """[{'name', 'kind' ('question' | 'fruit' | 'boost' | autre nom de donnees), 'pos'} (+ 'yaw', 'dims' pour
    les boosters)] dans l'ordre du fichier. crates_only : seulement les caisses (fichier _Design de Coco Park,
    Turbo Track, Blizzard Bluff, ou elles cotoient la grille, les reapparitions, les succes...)."""
    out = _read_entities(data)
    return [c for c in out if is_crate(c['kind'])] if crates_only else out


def _read_entities(data):
    df = DecorFile(data)
    z = df.igz
    kind_of = {o: k for k, n in KINDS.items() for o, nm in df.names.items() if nm == n}
    out = []
    for o in sorted(df.roots):
        if z.objects.get(o) not in ENTITY_TYPES:
            continue
        ed = z.deref(o + 0x40)
        name = df.names.get(o) or ''
        kind = kind_of.get(ed) or _content_kind(df, o) or df.names.get(ed) or '?'
        c = {'name': name, 'kind': kind, 'pos': [round(v, 2) for v in z.vec3(o + 0x20)]}
        if extra_kind(name):
            c['kind'] = extra_kind(name)
        if name.startswith(BOOST_PREFIX):
            tr, trig = z.deref(o + 0x30), _trigger(df, o)
            c['kind'] = 'boost'
            c['yaw'] = round(struct.unpack_from('<3f', *z._loc(tr + 0x60))[2], 5) if tr is not None else 0.0
            c['dims'] = [round(v, 1) for v in z.vec3(z.find_field(trig, '_dimensions')[0])] if trig else list(BOOST_DIMS)
        out.append(c)
    return out


def write_crates(orig_data, crates, donor=None, extras=None, height_at=None, crates_only=False, keep_tilt=None):
    """Fichier reconstruit depuis l'original (crates_only : depuis le _Design enregistre, seules ses caisses sont
    concernees, ses autres entites restent telles quelles) : crates = [{'name' (caisse d'origine gardee, ou nouvelle / absente),
    'kind', 'pos'} | {'kind': 'boost', 'pos', 'yaw', 'dims'} | {'kind': 'tnt' | 'nitro' | 'wumpa', 'pos'}]. Caisses
    d'origine absentes de la liste : retirees. donor : boost_donor(...) (s'il y a des boosters) ; extras :
    {type: extra_donor(...)} pour les objets d'EXTRAS. height_at(x, y, z) -> hauteur du sol : les caisses posees
    ou deplacees (et TNT / Nitro) sont inclinees comme la pente (tilt_euler), sinon a plat. keep_tilt : {(nom, pos)}
    des caisses du jeu jamais deplacees ; les autres caisses gardees sont re-inclinees (base deja enregistree).
    Retourne (IgzFile, rapport, ids ajoutes)."""
    euler_at = (lambda p: tilt_euler(height_at, *[float(v) for v in p])) if height_at else (lambda p: [0.0, 0.0, 0.0])
    boosts = [c for c in crates if c['kind'] == 'boost']
    others = [c for c in crates if c['kind'] in EXTRAS]
    crates = [c for c in crates if c['kind'] != 'boost' and c['kind'] not in EXTRAS]
    df = DecorFile(orig_data)
    z = df.igz
    by_name = {n: o for o, n in df.names.items() if z.objects.get(o) in ENTITY_TYPES}
    orig = {c['name']: c for c in read_crates(orig_data, crates_only)}
    # modele de copie par type : une caisse d'origine de ce type, avec le champ de bits le plus courant
    bits = collections.defaultdict(collections.Counter)
    for n, c in orig.items():
        bits[c['kind']][z.u32(by_name[n] + 0x38)] += 1
    template = {}
    for n, c in orig.items():
        if c['kind'] not in template and z.u32(by_name[n] + 0x38) == bits[c['kind']].most_common(1)[0][0]:
            template[c['kind']] = by_name[n]
    used = set(orig)
    kept, added = {}, []
    for c in crates:
        if c.get('name') in orig and c['name'] not in kept:
            kept[c['name']] = c
        else:
            if c['kind'] not in template:
                raise ValueError(f"type de caisse inconnu : {c['kind']}")
            k = 1
            while f"{PREFIX[c['kind']]}{k:03d}" in used:
                k += 1
            name = f"{PREFIX[c['kind']]}{k:03d}"
            used.add(name)
            added.append((name, c))
    # copies : inclinaison de LEUR sol (le modele copie garde sinon celle de sa pente d'origine : Roo's Tubes)
    eulers = [euler_at(c['pos']) for _, c in added]
    new_ids = df.duplicate_many([(template[c['kind']], name, [float(v) for v in c['pos']], e, None)
                                 for (name, c), e in zip(added, eulers)])
    tilted = 0
    for nid, (_, c), e in zip(new_ids, added, eulers):
        _set_tilt(df, nid, c['pos'], e, z.u32(template[c['kind']] + 0x38))
        tilted += any(e)
    moved = 0
    for name, c in kept.items():
        is_moved = any(abs(a - b) > 1e-3 for a, b in zip(c['pos'], orig[name]['pos']))
        if not is_moved and keep_tilt is not None and height_at and (name, tuple(orig[name]['pos'])) not in keep_tilt:
            # deja posee / deplacee lors d'une sauvegarde precedente : inclinaison suivant le sol actuel
            e = euler_at(c['pos'])
            _set_tilt(df, by_name[name], c['pos'], e, z.u32(template[orig[name]['kind']] + 0x38))
            tilted += any(e)
        if is_moved:
            # deplacee : inclinaison du sol a sa nouvelle place (Crash Cove crate_question_001, 19 deg a l'origine,
            # remise a plat ailleurs : un coin rentrait dans le sol)
            e = euler_at(c['pos'])
            _set_tilt(df, by_name[name], c['pos'], e, z.u32(template[orig[name]['kind']] + 0x38))
            tilted += any(e)
            moved += 1
    gone = [by_name[n] for n in orig if n not in kept]
    df.delete_many(gone)
    report = f'caisses : {len(kept) + len(added)} ({len(added)} ajoutee(s), {moved} deplacee(s), {len(gone)} retiree(s))'
    if tilted:
        report += f', {tilted} inclinee(s) selon la pente'
    if boosts:
        if donor is None:
            raise ValueError('plaque turbo modele manquante')
        src, src_ent = donor
        for k, b in enumerate(boosts, 1):
            ent = z.import_entity(src, src_ent, f'{BOOST_PREFIX}{k:03d}')
            df._refresh()
            df.set_transform(ent, [float(v) for v in b['pos']], [0.0, 0.0, float(b.get('yaw', 0.0))])
            trig = _trigger(df, ent)
            dims = [max(50.0, float(v)) for v in (b.get('dims') or BOOST_DIMS)]
            struct.pack_into('<3f', *z._loc(z.find_field(trig, '_dimensions')[0]), *dims)
        z.add_tdep(BOOST_TDEP)
        report += f', {len(boosts)} booster(s)'
    counts = collections.Counter()
    for c in others:
        kind = c['kind']
        if not extras or kind not in extras:
            raise ValueError(f'objet modele manquant : {kind}')
        src, src_ent = extras[kind]
        counts[kind] += 1
        ent = z.import_entity(src, src_ent, f"{EXTRAS[kind]['prefix']}{counts[kind]:03d}")
        df._refresh()
        pos = [float(v) for v in c['pos']]
        if z.deref(ent + 0x30) is not None:                     # avec transformation (TNT, Nitro) : pente du sol
            _set_tilt(df, ent, pos, euler_at(pos), z.u32(ent + 0x38))
        else:                                                   # fruit : position seule
            struct.pack_into('<3f', *z._loc(ent + 0x20), *pos)
    for kind in counts:
        z.add_tdep(EXTRAS[kind]['tdep'])
    if counts:
        report += ', ' + ', '.join(f"{n} {EXTRAS[k]['label']}" for k, n in counts.items())
    return df.igz, report, new_ids


# -- placement automatique ----------------------------------------------------------------------
def chain_paths(paths):
    """Splines de position successives -> un seul trace. Elles se chevauchent (~100 m de part et d'autre de chaque
    transition) : la suivante reprend apres le point le plus proche de la fin de la precedente, vers l'avant."""
    out = [list(p) for p in paths[0]] if paths else []
    for q in paths[1:]:
        if not out:
            out = [list(p) for p in q]
            continue
        end = np.asarray(out[-1][:2])
        Q = np.asarray(q, np.float64)
        k = int(np.argmin(np.linalg.norm(Q[:, :2] - end, axis=1)))
        if k + 1 < len(Q) and np.dot(Q[k, :2] - end, Q[k + 1, :2] - Q[k, :2]) <= 0:
            k += 1
        out += [list(p) for p in q[k:]]
    return out


def _resample(points, step):
    P = np.asarray(points, np.float64)
    seg = np.linalg.norm(np.diff(P[:, :2], axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])
    t = np.arange(0, s[-1], step)
    return np.stack([np.interp(t, s, P[:, k]) for k in range(3)], 1), s[-1]


def auto_rows(ground, path, rows=4, per_row=4, spacing=575.0, skip=0.12, margin=150.0, fruit=0, closed=True,
              tnt=0, nitro=0, wumpa_lines=0, wumpa_per_line=5, wumpa_gap=120.0):
    """Rangees de caisses « ? » en travers de la route le long de `path` (trace de course dans l'ordre, depuis la
    ligne d'arrivee), reparties sur le tour en laissant libre le debut (`skip` : part du tour apres la ligne, ou est
    la grille) ; ecart `spacing` entre caisses (575 po sur Crash Cove), reduit si la route est plus etroite.
    fruit : caisses de fruits isolees entre les rangees. tnt / nitro : caisses explosives posees sur la route, a
    gauche ou a droite de la trajectoire, decalees des rangees ; wumpa_lines : lignes de wumpa_per_line fruits dans le
    sens de la course (ecart wumpa_gap po). Retourne ([{'kind', 'pos'}], rapport)."""
    pts = ai_gen.catmull_rom(path, 100.0) if len(path) > 2 else path
    P, length = _resample(pts, 100.0)
    if length < 1000:
        raise ValueError('trace trop court')
    road = set(ai_gen.road_surfaces(ground, P[::5]))

    def frame(s):
        i = min(int(s / 100.0), len(P) - 2)
        a, b = P[max(i - 3, 0)], P[min(i + 3, len(P) - 1)]
        t = np.array([b[0] - a[0], b[1] - a[1]])
        t /= np.linalg.norm(t) or 1.0
        return P[i], np.array([-t[1], t[0]])

    def place(p, n, off, lift=LIFT):
        # surface la plus haute sous le trace (la route), pas le niveau le plus proche : un sol enfoui sous la route
        # (sable de Mario Circuit 3, 1,1 m dessous) enfoncait les caisses de moitie
        x, y = p[0] + n[0] * off, p[1] + n[1] * off
        z = ground.top(x, y, p[2]) if hasattr(ground, 'top') else None
        if z is None:
            g = ground.at(x, y, p[2])
            z = g[0] if g else None
        return [round(x, 1), round(y, 1), round(z + lift, 1)] if z is not None else None

    out, narrow, missing = [], 0, 0
    span = length * (1 - skip - (0.04 if closed else 0.0))
    marks = [length * skip + span * (k + 0.5) / max(rows, 1) for k in range(rows)]
    for s in marks:
        p, n = frame(s)
        left = ai_gen.road_width(ground, p, n, p[2], road)
        right = ai_gen.road_width(ground, p, -n, p[2], road)
        center = (left - right) / 2
        usable = max(0.0, left + right - 2 * margin)
        gap = spacing if per_row < 2 else min(spacing, usable / (per_row - 1))
        if per_row > 1 and gap < spacing - 1:
            narrow += 1
        for i in range(per_row):
            q = place(p, n, center + (i - (per_row - 1) / 2) * gap)
            if q:
                out.append({'kind': 'question', 'pos': q})
            else:
                missing += 1
    for k in range(fruit):                                     # entre deux rangees, alternativement a gauche / droite
        s = length * skip + span * (k + 1) / (fruit + 1)
        p, n = frame(s)
        left = ai_gen.road_width(ground, p, n, p[2], road)
        right = ai_gen.road_width(ground, p, -n, p[2], road)
        q = place(p, n, (left - right) / 2 + (1 if k % 2 else -1) * (left + right) / 4)
        if q:
            out.append({'kind': 'fruit', 'pos': q})
        else:
            missing += 1
    # caisses explosives : entre les rangees (au tiers), alternativement a gauche / a droite du milieu de la route
    bombs = ['tnt'] * tnt + ['nitro'] * nitro
    bombs = [bombs[i] for i in sorted(range(len(bombs)), key=lambda i: (i % max(tnt, nitro, 1), i))]   # melange
    for k, kind in enumerate(bombs):
        s = length * skip + span * (k + 0.33) / max(len(bombs), 1)
        p, n = frame(s)
        left = ai_gen.road_width(ground, p, n, p[2], road)
        right = ai_gen.road_width(ground, p, -n, p[2], road)
        q = place(p, n, (left - right) / 2 + (1 if k % 2 else -1) * (left + right) / 5)
        if q:
            out.append({'kind': kind, 'pos': q})
        else:
            missing += 1
    # lignes de fruits : au milieu entre deux rangees (aux deux tiers), sur un cote de la trajectoire
    for k in range(wumpa_lines):
        s0 = length * skip + span * (k + 0.66) / max(wumpa_lines, 1)
        for j in range(wumpa_per_line):
            p, n = frame(min(length - 1, s0 + j * wumpa_gap))
            left = ai_gen.road_width(ground, p, n, p[2], road)
            right = ai_gen.road_width(ground, p, -n, p[2], road)
            q = place(p, n, (left - right) / 2 + (-1 if k % 2 else 1) * (left + right) / 6, lift_of('wumpa'))
            if q:
                out.append({'kind': 'wumpa', 'pos': q})
            else:
                missing += 1
    rep = f'{rows} rangee(s) de {per_row} sur {round(length / 39.37)} m'
    if bombs:
        rep += f', {tnt} TNT et {nitro} Nitro'
    if wumpa_lines:
        rep += f', {wumpa_lines} ligne(s) de {wumpa_per_line} fruits'
    if narrow:
        rep += f', {narrow} rangee(s) resserree(s) (route etroite)'
    if missing:
        rep += f', {missing} caisse(s) sans sol dessous (non placees)'
    return out, rep
