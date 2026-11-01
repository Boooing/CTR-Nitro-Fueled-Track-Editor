"""Lumieres ponctuelles ajoutees a une map (lampadaires, torches, fenetres...) : entites du fichier _Lighting principal.

Modele : « Light_Boat » du _Lighting de Crash Cove (igEntity -> igEntityData -> igComponentDataTable ->
CPointLightComponentData), copie (import_entity) pour chaque lumiere. Position = igEntity._parentSpacePosition (+0x20,
pouces) ; composant : _color vec4 (+0x10), _intensity (+0x20), _radius (+0x24, pouces). Toutes les lumieres
ponctuelles du jeu (1918, 31 pistes) ont _lightBakeType 0 : eclairage en temps reel.

Reglages types (PRESETS) releves dans les pistes du jeu (valeurs les plus frequentes de chaque famille).
"""
import struct

DONOR_TRACK = 'T111_Crash_Cove'
DONOR_FILE = 'maps/Octane/T111_Crash_Cove/T111_Crash_Cove_Lighting.igz'
DONOR_ENTITY = 'Light_Boat'
PREFIX = 'PointLight_ctrmod'

# cle : (libelle, couleur RVB, intensite, rayon en pouces, piste d'origine)
PRESETS = {
    # intensite 100 (Oxide Station : 10) : demande de l'utilisateur, 10 trop faible sur une map de nuit (T901)
    'street': ('Lampadaire (jaune)', [1.0, 0.9, 0.24], 100.0, 1237.0, 'Oxide Station, PointLight_YellowBorder'),
    'warm': ('Lampe chaude', [1.0, 0.9, 0.74], 1.8, 2000.0, 'Crash Cove, Light_Boat'),
    'window': ('Fenêtre éclairée', [1.0, 0.76, 0.0], 12.38, 2200.0, 'Tiny Temple, PointLight_Windows'),
    'torch': ('Torche', [1.0, 0.58, 0.16], 3.0, 1900.0, 'Cortex Castle, TorchLight'),
    'candle': ('Bougie', [1.0, 0.54, 0.0], 5.0, 2000.0, 'Cortex Castle, CandleLight'),
    'fire': ('Feu / brasero', [1.0, 0.54, 0.22], 3.5, 1350.0, 'Tiger Temple, FireLight'),
    'lava': ('Lave', [1.0, 0.21, 0.05], 5.0, 6000.0, 'Inferno Island, PointLight_Fire'),
    'pub': ('Enseigne (grande portée)', [1.0, 0.83, 0.32], 6.0, 12000.0, 'Turbo Track, Pointlight_pub'),
    'green': ('Néon vert', [0.43, 1.0, 0.6], 5.0, 2268.0, 'Mystery Caves, PointLight_Gem'),
    'nitro': ('Vert nitro', [0.2, 1.0, 0.3], 6.0, 1500.0, 'Hyper Spaceway, PointLight_GreenNitro'),
    'cyan': ('Cyan électrique', [0.35, 0.7, 1.0], 4.0, 3000.0, 'Thunder Struck, Light_Cyan'),
}


MAX_INTENSITY = 1000.0      # 100 bloquait les lampadaires deja a 100 (preset) : plus fort impossible


def clean(lights):
    """Liste de lumieres valides [{pos, color, intensity, radius}] (valeurs bornees)."""
    out = []
    for l in lights or []:
        try:
            pos = [float(v) for v in l['pos'][:3]]
            col = [min(max(float(v), 0.0), 1.0) for v in (l.get('color') or [1, 1, 1])[:3]]
            out.append({'pos': pos, 'color': col, 'intensity': min(max(float(l.get('intensity', 5)), 0.0), MAX_INTENSITY),
                        'radius': min(max(float(l.get('radius', 1500)), 50.0), 50000.0),
                        **({'preset': l['preset']} if l.get('preset') in PRESETS else {})})
        except (KeyError, TypeError, ValueError, IndexError):
            continue
    return out


def add_lights(z, donor, lights):
    """Ajoute les lumieres dans le fichier z (IgzFile du _Lighting) ; donor = IgzFile du _Lighting de Crash Cove.
    -> nombre de lumieres ajoutees."""
    ent = dict((n, o) for n, o in donor.root_objects() if n)[DONOR_ENTITY]
    for i, l in enumerate(lights):
        new = z.import_entity(donor, ent, f'{PREFIX}{i:03d}', old_name=DONOR_ENTITY)
        struct.pack_into('<3f', *z._loc(new + 0x20), *l['pos'])
        comp = next(o for o in z.reachable(new)[0] if z.objects[o] == 'CPointLightComponentData')
        struct.pack_into('<4f', *z._loc(comp + 0x10), *l['color'], 1.0)
        struct.pack_into('<2f', *z._loc(comp + 0x20), l['intensity'], l['radius'])
    return len(lights)
