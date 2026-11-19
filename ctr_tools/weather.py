"""Meteo et particules d'ambiance (2026-11-13) : effets d'autres pistes du jeu poses le long du trace.

Dans le jeu, la pluie, la neige, les feuilles qui tombent... sont des entites igEntity a un seul composant
CStaticVfxComponentData (_effect : handle EXID vers un effet 'vfx:/CTR/levels/<effet>.igz', _startSpawned,
_spawnPerCamera). Elles sont posees le long du trace a une hauteur propre a chaque effet (releve sur les pistes
d'origine, scratchpad weather_rel.py) :
  * Tiger Temple : pluie « screen volume » (une par camera) a hauteur de route tous les ~13 m du trace, gouttes
    « sub_a » a hauteur de route a ~20 m du centre, effet d'ecran « sub_b » une fois ;
  * Blizzard Bluff : neige legere +10 m (espacement ~70 m), grosse neige +70 m (~110 m), neige soufflee au sol (~55 m) ;
  * Coco Park : feuilles roses +39 m au-dessus de la route (emetteur agrandi x7 dans sa transformation, gardee) ;
  * Mystery Caves / Jungle Boogie / Coco Park : lucioles, pollen pres du sol.
Copier = IgzFile.import_entity de l'entite d'origine (transformation et echelle gardees, position remplacee), TDEP
de l'effet ajoutee, fichiers de l'effet (sous-effets, textures) declares au manifeste et copies dans l'archive de la
piste s'ils ne sont pas dans une archive commune (animated.install_files, recursif).
"""
import math
import os
import re

import numpy as np

import animated
import pak_tool
from igz import IgzFile
from model_build import tdep_entries

IN = 39.37
PREFIX = 'EdWx_'
# couche : (archive, fichier de carte, effet, espacement (m), hauteur au-dessus de la route (m), ecart lateral (m,
# alterne gauche / droite), nombre maxi ; espacement 0 = une seule fois, au depart)
TIGER = ('t132_tiger_temple.pak', 'maps/Octane/T132_Tiger_Temple/T132_Tiger_Temple_VFX_Core.igz')
BLIZZ = ('t141_blizzard_bluff.pak', 'maps/Octane/T141_Blizzard_Bluff/T141_Blizzard_Bluff_VFX.igz')
COCO = ('t131_coco_park.pak', 'maps/Octane/T131_Coco_Park/T131_Coco_Park_VFX_Core.igz')
COCO_F = ('t131_coco_park.pak', 'maps/Octane/T131_Coco_Park/T131_Coco_Park_VFX_Forever.igz')
CAVES = ('t113_mystery_caves.pak', 'maps/Octane/T113_Mystery_Caves/T113_Mystery_Caves_VFX_core.igz')
RAIN = [(*TIGER, 'ctr_t132_weather_rain_screen_volume', 30, 0.0, 0, 120),
        (*TIGER, 'ctr_t132_weather_rain_screen_volume_sub_a', 30, 0.0, 15, 120),
        (*TIGER, 'ctr_t132_weather_rain_screen_volume_sub_b', 0, 0.0, 0, 1)]
SNOW = [(*BLIZZ, 'ctr_t141_light_snow', 60, 10.0, 0, 80),
        (*BLIZZ, 'ctr_t141_falling_snow', 110, 70.0, 0, 40)]
PRESETS = {
    'rain':     {'label': 'Pluie', 'layers': RAIN},
    'storm':    {'label': 'Orage', 'layers': RAIN + [(*TIGER, 'ctr_t132_weather_lightning_screen_volume', 0, 0.0, 0, 1)]},
    'snow':     {'label': 'Neige', 'layers': SNOW},
    'blizzard': {'label': 'Tempête de neige', 'layers': SNOW + [(*BLIZZ, 'ctr_t141_snow_blowing', 50, 0.0, 0, 80)]},
    'leaves':   {'label': 'Feuilles qui tombent', 'layers': [(*COCO, 'ctr_t131_fallingleaves_pink', 70, 39.0, 0, 60)]},
    'fireflies': {'label': 'Lucioles', 'layers': [(*CAVES, 'ctr_t113_fireflies', 60, 2.0, 10, 60)]},
    'pollen':   {'label': 'Pollen', 'layers': [(*COCO_F, 'ctr_t131_ambient_pollen', 100, 0.0, 0, 40)]},
}
DENSITY = {'low': 1.6, 'normal': 1.0, 'high': 0.7}          # multiplicateur de l'espacement
MAX_TOTAL = 260                                               # entites ajoutees au plus (memoire du jeu)


def donor_entity(z, effect):
    """(entite, (nom, chemin) de la TDEP) de la 1re entite du fichier qui joue l'effet, ou (None, None)."""
    td = {pak_tool.fnv1a_lower(n): (n, p) for n, p in tdep_entries(z) if p.lower().startswith('vfx:')}
    exid = z.exid_pairs()
    ents = dict(z.root_objects())
    for name, o in z.root_objects():
        if z.objects.get(o) != 'CStaticVfxComponentData' or not name:
            continue
        h = (z.dump_object(o).get('_effect') or {}).get('@handle', '')
        try:
            pair = td.get(exid[int(h.split('#')[1], 16)][0])
        except (IndexError, ValueError):
            continue
        if not pair or pair[0].lower() != effect.lower():
            continue
        ent = ents.get(name.split('_entityData')[0])
        if ent is not None:
            return ent, pair
    return None, None


def route_samples(paths, every, side=0.0, start_at=0.0):
    """Points tous les `every` po le long des splines de position (listes de points [x, y, z] deja lisses), sans
    doublon la ou elles se chevauchent (transitions) ; side : ecart lateral alterne (po). -> [[x, y, z]]."""
    out = []
    k = 0
    for P in paths:
        P = np.asarray(P, float)
        if len(P) < 2:
            continue
        seg = np.hypot(*(P[1:, :2] - P[:-1, :2]).T)
        s = np.concatenate([[0.0], np.cumsum(seg)])
        t = start_at
        while t <= s[-1]:
            i = min(len(seg) - 1, int(np.searchsorted(s, t, 'right') - 1))
            u = (t - s[i]) / (seg[i] or 1)
            p = P[i] + (P[i + 1] - P[i]) * u
            if side:
                tx, ty = (P[i + 1, :2] - P[i, :2]) / (seg[i] or 1)
                sgn = 1 if k % 2 == 0 else -1
                p = p + np.array([-ty, tx, 0.0]) * side * sgn
            if all(math.hypot(p[0] - q[0], p[1] - q[1]) > every * 0.6 for q in out[-400:]):
                out.append([float(p[0]), float(p[1]), float(p[2])])
                k += 1
            t += every
    return out


def plan(preset, density, paths):
    """[(couche, [positions en po])] de la meteo choisie sur ce trace."""
    if preset not in PRESETS:
        return []
    mult = DENSITY.get(density, 1.0)
    out = []
    for layer in PRESETS[preset]['layers']:
        pak, logical, effect, every, dz, side, cap = layer
        if not every:
            P = next((p for p in paths if len(p)), None)
            pos = [[float(P[0][0]), float(P[0][1]), float(P[0][2]) + dz * IN]] if P is not None else []
        else:
            step = every * mult * IN
            pos = route_samples(paths, step, side * IN)
            while len(pos) > cap:                         # trace tres long : espacement agrandi
                step *= len(pos) / cap * 1.02
                pos = route_samples(paths, step, side * IN)
            pos = [[x, y, z + dz * IN] for x, y, z in pos]
        out.append((layer, pos))
    total = sum(len(p) for _, p in out)
    if total > MAX_TOTAL:                                 # coupe proportionnelle (une fois au depart garde)
        f = MAX_TOTAL / total
        out = [(l, p if len(p) <= 1 else p[::max(1, round(1 / f))]) for l, p in out]
    return out


def _set_position(z, ent, pos):
    import struct
    struct.pack_into('<3f', *z._loc(ent + 0x20), *[float(v) for v in pos])
    struct.pack_into('<I', *z._loc(ent + 0x38), z.u32(ent + 0x38) | 1)          # entite active au depart
    tr = z.deref(ent + 0x30)
    if tr is not None:
        struct.pack_into('<I', *z._loc(tr + 0x7C), 1)                           # _isDirty


def inject(z, preset, density, paths, read, archives, track_pak):
    """Copie la meteo dans le fichier z (IgzFile). read(chemin logique, archive) -> octets.
    -> (entrees du manifeste, {fichier a copier: archive source}, rapport, nombre d'entites)."""
    entries, copies, report, n = [], {}, [], 0
    donors = {}
    for (pak, logical, effect, *_), pos in plan(preset, density, paths):
        if not pos:
            continue
        if (pak, logical) not in donors:
            try:
                donors[(pak, logical)] = IgzFile(read(logical, pak))
            except KeyError:
                donors[(pak, logical)] = None
        src = donors[(pak, logical)]
        ent, pair = donor_entity(src, effect) if src else (None, None)
        if ent is None:
            report.append(f'effet introuvable : {effect} ({pak})')
            continue
        old = dict((o, nm) for nm, o in src.root_objects()).get(ent)
        with z.defer_roots():                       # une reecriture de la liste racine pour tout l'effet
            for p in pos:
                new = z.import_entity(src, ent, f'{PREFIX}{n:04d}', old_name=old)
                _set_position(z, new, p)
                n += 1
        z.add_tdep([pair])
        e, c, missing = animated.install_files(archives, [pair], track_pak, pak)
        entries += [x for x in e if x not in entries]
        copies.update(c)
        if missing:
            report.append(f'{effect} : fichier(s) introuvable(s) {missing[:3]}')
    # chaque ajout reecrit la liste racine et la table des noms (4 000 objets sur un _Art) : les anciennes, abandonnees,
    # faisaient passer le fichier de 0,7 a 19 Mo (pluie) -> retirees
    if n:
        z.compact()
    return entries, copies, report, n
