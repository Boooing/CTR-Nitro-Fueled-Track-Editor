"""Createur de pistes (onglet « Création » de l'editeur) : trace du paveur + terrain -> scene OBJ prete a importer.

Le paveur enregistre la ligne centrale (x, y, z, largeur ; pouces, repere du jeu, z vers le haut) ; l'onglet Terrain
une grille de relief (hauteurs relatives au sol de depart) et une matiere par sommet. On en tire :
  * CreatorRoad : ruban de route (texture de piste de la piste de base, repetee le long de la route) ;
  * CreatorGround<carreau>_<matiere> : terrain autour du trace, raccorde a la route (aplani sous elle, puis pente
    douce jusqu'au relief sculpte), en carreaux de 200 m et par matiere (texture et type de sol propres).
L'OBJ est ecrit en metres, z vers le haut, coordonnees du jeu (import « absolute », echelle 39.37).
"""
import io
import math
from collections import defaultdict

import numpy as np

from track_creator_extra import EXTRA as _EXTRA, HIDDEN as HIDDEN_MODELS, LABELS as _EXTRA_LABELS

INCH = 39.37
STEP = 2.0                       # m : pas de la ligne centrale lissee
OBJ_NAME, MTL_NAME = 'Createur.obj', 'Createur.mtl'      # nom du lot d'import : « Createur — date »
ROAD_LIFT = 0.05                 # m : route au-dessus du sol (evite le scintillement avec le sol)
UNDER_ROAD = 0.25                # m : terrain aplani juste sous la route
BLEND_SLOPE = 1.5                # raccord route -> relief : 1,5 m a l'horizontale par metre de denivele
BLEND_MIN = 6.0                  # m : raccord minimal
SCULPT_FULL = 3.0                # m : sol sculpte d'au moins cette hauteur : il garde sa hauteur jusqu'a BLEND_MIN de la route
Z_SMOOTH = 6.0                   # m : ecart-type du lissage de la hauteur de route (crete / creux trop secs)
GROUND_MARGIN = 150.0            # m autour du trace
GROUND_CELL = 10.0               # m : maille du sol quand rien n'est sculpte
GROUND_TILE = 200.0              # m : un objet de sol par carreau
KICK_LEN, KICK_H = 22.0, 3.0     # m : tremplin avant un saut (longueur, hauteur gagnee) ; avant le 2026-11-05 : 14 / 1,6
HOLE_MARGIN = 3.0                # m : trou du terrain sous un saut, au-dela du bord de route
WALL_H, WALL_T, WALL_GAP = 2.2, 0.6, 0.3   # m : barrieres (hauteur, epaisseur, ecart au bord de route)
CURVE_R = 90.0                   # m : virage (rayon plus petit) -> barriere a l'exterieur en mode « virages »
CURVE_EXTEND = 10                # echantillons : barriere prolongee avant / apres le virage
START_CELL, START_ROWS, START_LIFT = 1.5, 2, 0.03   # damier du depart : case (m), rangees, hauteur au-dessus de la route

# kits : textures de la piste de base (fichiers du jeu), longueur couverte par une repetition (m), matieres du
# terrain dans l'ordre des indices de peinture (nom OBJ, image, texture du jeu, surface de collision, libelle, couleur
# d'apercu) — la 1re = sol par defaut ; une image « rock.png » sert aussi aux barrieres et aux tabliers de pont.
# Surfaces : 38 sable, 40 sable mouille, 5 herbe (ralentit x0,4), 7 terre, 4 sol par defaut, 46 asphalte.
_T111 = 'textures/ColorMap,textures@!levels!Octane!T111_Crash_Cove!'
_T131 = 'textures/ColorMap,textures@!levels!Octane!T131_Coco_Park!'
_T132 = 'textures/ColorMap,textures@!levels!Octane!T132_Tiger_Temple!'
_T134 = 'textures/ColorMap,textures@!levels!Octane!T134_Dingo_Canyon!'
_T141 = 'textures/ColorMap,textures@!levels!Octane!T141_Blizzard_Bluff!'
_T143 = 'textures/ColorMap,textures@!levels!Octane!T143_Polar_Pass!'
_C1J = 'textures/ColorMap,textures@!levels!Crash1!jungle!'
_C3D = 'textures/ColorMap,textures@!levels!Crash3!Desert!'


def _m(folder, *names):
    """Chemins de modeles de la bibliotheque : models/Levels/<dossier>/<nom>.igz."""
    return [f'models/Levels/{folder}/{n}.igz' for n in names]

KITS = {
    'sable': {
        'label': 'Plage de sable (Crash Cove)',
        'road': _T111 + 'T111_Sand_Dry01!CrashCove_SandTrack_C`tga,111.igz',
        'materials': [('Sand', 'sand.png', _T111 + 'T111_Sand_Dry01!CrashCove_Sand01_D`tga,111.igz', 38, 'Sable', (0.85, 0.71, 0.49)),
                      ('WetSand', 'wetsand.png', _T111 + 'T111_Sand_Wet01!CrashCove_Sand02_D`tga,111.igz', 40, 'Sable mouillé', (0.62, 0.50, 0.34)),
                      ('Grass', 'grass.png', _T111 + 'T111_Grass!T111_GrassTile01_C`tga,111.igz', 5, 'Herbe (ralentit)', (0.42, 0.60, 0.24)),
                      ('Rock', 'rock.png', _T111 + 'T111_rockgroundside!T111_rockgroundside_C`tga,111.igz', 4, 'Roche', (0.52, 0.50, 0.47))],
        'road_repeat': 14.0, 'ground_repeat': 12.0,
        'road_surface': 38,                                   # sable (collision du jeu)
        'pak': 't111_crash_cove.pak',
        # objets du jeu a semer (onglet Creation, mode Decor) : modeles de la bibliotheque par famille, echelle aleatoire
        'props': {
            'palm': {'label': '🌴 Palmiers', 'pak': 't111_crash_cove.pak', 'scale': (0.85, 1.25), 'spacing': 9.0,
                     'models': _m('Crash1/jungle', 'C1_PalmTree01S', 'C1_PalmTree03')},
            'rock': {'label': '🪨 Rochers', 'pak': 't111_crash_cove.pak', 'scale': (0.5, 1.0), 'spacing': 12.0,
                     'models': _m('Octane/T111_Crash_Cove', 'T111_RockModul01', 'T111_RockModul02', 'T111_RockModul03', 'T111_RockModul04',
                                  'T111_RockModul01_Tape01', 'T111_RockModul01_Tape02', 'T111_RockModul01_Twist01',
                                  'T111_RockModul01_Twist02', 'T111_RockModul03_Taper01', 'T111_RockModul03_Taper02',
                                  'T111_RockModul04_Grass', 'T111_RockGroundSide_b', 'T111_RockGroundSide_c',
                                  'T111_RockGroundSide_d', 'T111_RockGroundSide_g')},
            'pillar': {'label': '🗿 Piliers de roche', 'pak': 't111_crash_cove.pak', 'scale': (0.8, 1.2), 'spacing': 20.0,
                       'models': _m('Crash3/Sea', 'C3_Sea_RockPillar01', 'C3_Sea_RockPillar05', 'C3_Sea_RockPillar06')},
            'grass': {'label': '🌿 Herbes et fleurs', 'pak': 't111_crash_cove.pak', 'scale': (0.8, 1.4), 'spacing': 3.0,
                      'models': _m('Octane/T111_Crash_Cove', 'T111_HighResGrass_01', 'T111_HighResGrass_02', 'T111_RedCoveFlower')
                      + _m('Crash1/jungle', 'C1_HighResGrass_02')},
            'beach': {'label': '⚓ Objets de plage', 'pak': 't111_crash_cove.pak', 'scale': (1.0, 1.0), 'spacing': 6.0,
                      'models': _m('Octane/T111_Crash_Cove', 'T111_CrashTire', 'T111_WoodPost', 'T111_WoodPostLong', 'T111_PostRope',
                                   'T111_WoodArrow', 'T111_WoodArrow02')
                      + _m('Crash3/JetSki', 'Rowboat') + _m('Octane/T111_Crash_Cove', 'starfish01')},
            'coral': {'label': '🪸 Coraux', 'pak': 't111_crash_cove.pak', 'scale': (0.8, 1.3), 'spacing': 5.0,
                      'models': _m('Crash3/Sea', 'C3_Sea_CoralFan01', 'C3_Sea_CoralFan02', 'C3_Sea_CoralFan04',
                                   'C3_Sea_CoralLeather02', 'C3_Sea_CoralLeather03', 'C3_Sea_CoralSpotted02', 'C3_Sea_Kelp03')},
            'big': {'label': '⛰ Grandes falaises (fond)', 'pak': 't221_meteor_gorge.pak', 'scale': (0.6, 1.0), 'spacing': 45.0, 'big': True,
                    'models': _m('Octane/T221_Meteor_Gorge', 'T221_Cliff_02', 'T221_Cliff_03')},
        },
    },    'parc': {
        'label': 'Parc fleuri (Coco Park)',
        'road': 'textures/ColorMap,textures@!levels!Octane!T121_Slide_Coliseum!T121_Asphalt01_C`tga,111.igz',
        'materials': [('ParkGrass', 'parkgrass.png', _T131 + 'T131_GroundGrass_C`tga,111.igz', 5, 'Pelouse (ralentit)', (0.38, 0.62, 0.25)),
                      ('Flowers', 'flowers.png', _T131 + 'T131_PetalGround_01_C`tga,111.igz', 5, 'Fleurs (ralentit)', (0.70, 0.55, 0.62)),
                      ('Dirt', 'dirt.png', 'textures/ColorMap,textures@!levels!Crash3!Medieval!C3_DirtRocky01_C`tga,111.igz', 7, 'Terre', (0.55, 0.42, 0.30)),
                      ('ParkRock', 'rock.png', _T131 + 'T131_WallRock_01_C`tga,111.igz', 4, 'Roche', (0.55, 0.53, 0.50))],
        'road_repeat': 16.0, 'ground_repeat': 10.0,
        'road_surface': 46,                                   # asphalte
        'pak': 't131_coco_park.pak',
        'props': {
            'tree': {'label': '🌳 Arbres', 'pak': 't131_coco_park.pak', 'scale': (0.8, 1.2), 'spacing': 14.0,
                     'models': _m('Octane/T131_Coco_Park', 'T131_Tree_01', 'T131_BigTree_01', 'T131_TreeTrunk_01')},
            'flower': {'label': '🌸 Fleurs', 'pak': 't131_coco_park.pak', 'scale': (0.8, 1.3), 'spacing': 4.0,
                       'models': _m('Octane/T131_Coco_Park', 'T131_FlowerClump01', 'T131_FlowerClumpPink01', 'T31_FlowerClumpYellow01',
                                    'T131_FlowerBucket', 'T131_FlowerSet3', 'T131_Petals_01', 'T131_Petals_02')
                       + _m('Crash3/Medieval', 'C3_FlowerClump01', 'C3_FlowerClump02')},
            'giant': {'label': '🌼 Fleurs géantes', 'pak': 't131_coco_park.pak', 'scale': (0.6, 1.0), 'spacing': 25.0,
                      'models': _m('Octane/T131_Coco_Park', 'T131_FlowerDaisy01', 'T131_FlowerDaisy02', 'T131_BigFlowerOpen',
                                   'T131_BigFlowerClosed')},
            'bush': {'label': '🌿 Buissons et champignons', 'pak': 't131_coco_park.pak', 'scale': (0.9, 1.2), 'spacing': 6.0,
                     'models': _m('Octane/T131_Coco_Park', 'T131_Castle_Bushes_01') + _m('Octane/A115_Skull_Rock', 'T131_Foliage01')
                     + _m('Crash1/jungle', 'C1_MushroomSmall01', 'C1_MushroomSmall02')},
            'rock': {'label': '🪨 Rochers', 'pak': 't131_coco_park.pak', 'scale': (0.8, 1.3), 'spacing': 10.0,
                     'models': _m('Octane/T131_Coco_Park', 'T131_WallRockSmall_01', 'T131_WallRockSmall_02', 'T131_WallRockSmall_03',
                                  'T131_WallRockSmall_04', 'T131_WallRockMoss_01', 'T131_WallRock_01')},
            'house': {'label': '🏠 Maisons et tentes', 'pak': 't131_coco_park.pak', 'scale': (1.0, 1.0), 'spacing': 30.0,
                      'models': _m('Octane/T131_Coco_Park', 'T131_House01', 'T131_House02', 'T131_Tent_01', 'T131_Tent_02', 'T131_Tent_03',
                                   'T131_Tent_04') + _m('Crash3/Medieval', 'C3_CarnivalTent01')},
            'statue': {'label': '🗽 Statues de Coco', 'pak': 't131_coco_park.pak', 'scale': (1.0, 1.0), 'spacing': 40.0,
                       'models': _m('Octane/T131_Coco_Park', 'T131_Coco_statue1', 'T131_Coco_statue3', 'T131_Coco_Statue_02_DF',
                                    'T131_BaseStatue_01')},
        },
    },
    'jungle': {
        'label': 'Temple de la jungle (Tiger Temple)',
        'road': _T132 + 'T132_Mud02_C`tga,111.igz',
        'materials': [('JungleGrass', 'junglegrass.png', _C1J + 'C1_GrassTile01_C`tga,111.igz', 5, 'Herbe (ralentit)', (0.36, 0.52, 0.22)),
                      ('Moss', 'moss.png', _C1J + 'C1_Moss03_C`tga,111.igz', 5, 'Mousse (ralentit)', (0.30, 0.45, 0.22)),
                      ('Mud', 'mud.png', _T132 + 'T132_Mud01_C`tga,111.igz', 7, 'Boue', (0.45, 0.34, 0.22)),
                      ('TempleRock', 'rock.png', _T132 + 'T132_BrickStone01_C`tga,111.igz', 4, 'Pierre du temple', (0.55, 0.52, 0.45))],
        'road_repeat': 14.0, 'ground_repeat': 10.0,
        'road_surface': 7,                                    # terre
        'pak': 't132_tiger_temple.pak',
        'props': {
            'plant': {'label': '🌿 Herbes et champignons', 'pak': 't132_tiger_temple.pak', 'scale': (0.8, 1.3), 'spacing': 4.0,
                      'models': _m('Crash1/jungle', 'C1_HighResGrass_03', 'C1_MushroomBig01')},
            'pillar': {'label': '🏛 Piliers aux lianes', 'pak': 't132_tiger_temple.pak', 'scale': (0.8, 1.1), 'spacing': 18.0,
                       'models': _m('Octane/T132_Tiger_Temple', 'T132_Tiger_Temple_Pillar_Vines_01', 'T132_Tiger_Temple_Pillar_Vines_02',
                                    'T132_Tiger_Temple_Pillar_Vines_03', 'T132_Tiger_Temple_Pillar_Vines_04',
                                    'T132_Tiger_Temple_Pillar_Vines_05')},
            'statue': {'label': '🐯 Statues et ruines', 'pak': 't132_tiger_temple.pak', 'scale': (1.0, 1.0), 'spacing': 25.0,
                       'models': _m('Octane/T132_Tiger_Temple', 'T132_GoldenStatue_01', 'T132_Totem01', 'T132_Tiger_Temple_Cube')
                       + _m('Crash1/village', 'C1_Papu_Throne')},
            'big': {'label': '⛰ Falaises et visage de pierre (fond)', 'pak': 't132_tiger_temple.pak', 'scale': (0.7, 1.1), 'spacing': 35.0,
                    'big': True, 'models': _m('Octane/T133_Papus_Pyramid/Papus_Pyramid_Assets', 'Papus_Pyramid_cliff02')
                    + _m('Octane/T132_Tiger_Temple', 'T132_Tiger_Temple_StoneFace')},
        },
    },
    'neige': {
        'label': 'Montagne enneigée (Blizzard Bluff)',
        'road': _T143 + 'T143_SnowPath_C`tga,111.igz',
        'materials': [('Snow', 'snow.png', _T141 + 'T134_SnowClean_01_C`png,111.igz', 8, 'Neige', (0.92, 0.94, 0.97)),
                      ('SnowGrunge', 'snowgrunge.png', _T141 + 'T134_SnowGrunge_01_C`tga,111.igz', 8, 'Neige tassée', (0.78, 0.80, 0.84)),
                      ('Ice', 'ice.png', _T141 + 'T141_Start_Ice_02_C`tga,111.igz', 10, 'Glace (glisse)', (0.62, 0.78, 0.90)),
                      ('SnowRock', 'rock.png', _T141 + 'T141_Cliff_01_C`tga,111.igz', 4, 'Roche', (0.50, 0.52, 0.56))],
        'road_repeat': 14.0, 'ground_repeat': 12.0,
        'road_surface': 8,                                    # neige
        'pak': 't141_blizzard_bluff.pak',
        'props': {
            'pine': {'label': '🌲 Sapins', 'pak': 't141_blizzard_bluff.pak', 'scale': (0.8, 1.3), 'spacing': 10.0,
                     'models': _m('Crash2/Snow', 'C2_Pine_Tree03')},
            'rock': {'label': '🪨 Rochers et glace', 'pak': 't141_blizzard_bluff.pak', 'scale': (0.7, 1.2), 'spacing': 12.0,
                     'models': _m('Octane/T141_Blizzard_Bluff', 'T141_SmallRock_01', 'T141_SmallRock_02', 'T141_SmallRock_03',
                                  'T141_CliffSmall_01', 'T141_CliffSmall_02', 'T141_CliffSmall_03_snow', 'T141_CliffSmall_04_snow',
                                  )},
            'snow': {'label': '❄ Tas de neige', 'pak': 't141_blizzard_bluff.pak', 'scale': (0.8, 1.3), 'spacing': 8.0,
                     'models': _m('Octane/T141_Blizzard_Bluff', 'T141_SnowPile', 'T141_Snowpile02', 'T141_SnowBlocks01',
                                  'T141_SnowBlocks02')},
            'house': {'label': '🏠 Chalets', 'pak': 't141_blizzard_bluff.pak', 'scale': (1.0, 1.0), 'spacing': 30.0,
                      'models': _m('Octane/T141_Blizzard_Bluff', 'T141_HouseA', 'T141_HouseB', 'T141_HouseC', 'T141_Campsite01')},
            'deco': {'label': '⛷ Objets de station', 'pak': 't141_blizzard_bluff.pak', 'scale': (1.0, 1.0), 'spacing': 8.0,
                     'models': _m('Octane/T141_Blizzard_Bluff', 'T141_Lamppost', 'T141_FlagPost_01', 'T141_FlagPost_02',
                                  'T141_SkiProps_01', 'T141_SkiProps_02', 'T141_Ski_Sign_01', 'T141_Ski_Sign_04', 'T141_AlpineHorn', 'T141_SnowShoes_01', 'T141_TotemBear_01',
                                  'T141_SingingFish')},
            'fence': {'label': '🚧 Barrières', 'pak': 't141_blizzard_bluff.pak', 'scale': (1.0, 1.0), 'spacing': 8.0,
                      'models': _m('Octane/T141_Blizzard_Bluff', 'T141_WoodenFence_01', 'T141_WoodenFence_02', 'T141_WoodenFence_03',
                                   'T141_FiletFence_01', 'T141_FiletFence_02')},
            'big': {'label': '⛰ Falaises et bloc de glace (fond)', 'pak': 't141_blizzard_bluff.pak', 'scale': (0.6, 1.0), 'spacing': 40.0,
                    'big': True, 'models': _m('Octane/T141_Blizzard_Bluff', 'T141_Cliff_02', 'T141_Cliff_03', 'T141_Cliff_04',
                                              'T141_Cliff_Mushroom_01', 'T141_Cliff_Mushroom_03', 'T141_IceBlock_01')},
        },
    },
    'canyon': {
        'label': 'Canyon du désert (Dingo Canyon)',
        'road': _T134 + 'T134_Asphalt01_C`tga,111.igz',
        'materials': [('DesertSand', 'desertsand.png', _T134 + 'T134_Sand_01_C`tga,111.igz', 38, 'Sable', (0.82, 0.62, 0.40)),
                      ('SandRocky', 'sandrocky.png', _T134 + 'T134_SandRocky_01_C`tga,111.igz', 38, 'Sable caillouteux', (0.72, 0.52, 0.36)),
                      ('DesertDirt', 'desertdirt.png', _C3D + 'C3_DesertDirt01_C`tga,111.igz', 7, 'Terre', (0.60, 0.42, 0.28)),
                      ('CanyonRock', 'rock.png', _T134 + 'T134_Cliff_01_C`tga,111.igz', 4, 'Roche', (0.62, 0.40, 0.28))],
        'road_repeat': 16.0, 'ground_repeat': 12.0,
        'road_surface': 46,                                   # asphalte
        'pak': 't134_dingo_canyon.pak',
        'props': {
            'cactus': {'label': '🌵 Cactus', 'pak': 't134_dingo_canyon.pak', 'scale': (0.8, 1.4), 'spacing': 7.0,
                       'models': _m('Crash3/Desert', 'C3_Cactus01')},
            'rock': {'label': '🪨 Rochers', 'pak': 't134_dingo_canyon.pak', 'scale': (0.6, 1.1), 'spacing': 14.0,
                     'models': _m('Octane/T134_Dingo_Canyon', 'T134_CliffSmall_01', 'T134_CliffSmall_02', 'T134_CliffSmall_03',
                                  'T134_CliffSmall_04', 'T134_CliffMedium_01')},
            'sign': {'label': '🪧 Panneaux', 'pak': 't134_dingo_canyon.pak', 'scale': (1.0, 1.0), 'spacing': 10.0,
                     'models': _m('Crash3/L308_HogRide', 'ArmadilloSign', 'JumpSign')
                     + _m('Octane/T134_Dingo_Canyon', 'T134_Flammable_sign', 'T134_DingoAd_01', 'T134_DingoAd_02',
                          'T134_Woodpost')
                     + _m('Crash3/Desert', 'C3_BillboardCortex_02', 'C3_BillboardRace_01')},
            'building': {'label': '🏭 Bâtiments', 'pak': 't134_dingo_canyon.pak', 'scale': (1.0, 1.0), 'spacing': 35.0,
                         'models': _m('Crash3/Desert', 'C3_Diner_01')
                         + _m('Octane/T134_Dingo_Canyon', 'T134_Gas_silo')},
            'big': {'label': '⛰ Falaises, château d\'eau, grand panneau (fond)', 'pak': 't134_dingo_canyon.pak', 'scale': (0.5, 0.9),
                    'spacing': 40.0, 'big': True,
                    'models': _m('Octane/T134_Dingo_Canyon', 'T134_Cliff_02', 'T134_Cliff_03', 'T134_Dingo_billboard',
                                 'T134_Wood_Structure02', 'T134_WaterTower') + _m('Crash2/Global', 'C2_BonusTree05')},
        },
    },
}

# themes tires des autres pistes du jeu (textures et modeles verifies : decodes / charges ; objets centres sur
# leur origine seulement), dans l'ordre des pistes
KITS.update({
    'egouts': {
        'label': 'Égouts (Sewer Speedway)',
        'road': 'textures/ColorMap,textures@!levels!Octane!T114_Sewer_Speedway!T114_Concrete_C`tga,111.igz',
        'materials': [
            ('SewerCement', 'sewercement.png', 'textures/ColorMap,textures@!levels!Crash2!Sewer!SEW_Cement01_C`tga,111.igz', 4, 'Ciment', (0.36, 0.34, 0.32)),
            ('SewerWet', 'sewerwet.png', 'textures/ColorMap,textures@!levels!Octane!T114_Sewer_Speedway!T114_StoneWater_C`tga,111.igz', 4, 'Pierre mouillée', (0.45, 0.52, 0.55)),
            ('SewerGrid', 'sewergrid.png', 'textures/ColorMap,textures@!levels!Octane!T114_Sewer_Speedway!T114_Grid_C`tga,111.igz', 4, 'Grille métallique', (0.3, 0.26, 0.21)),
            ('SewerBrick', 'rock.png', 'textures/ColorMap,textures@!levels!Octane!T114_Sewer_Speedway!T114_Stone_brick_02_C`tga,111.igz', 4, 'Briques', (0.41, 0.42, 0.42)),
        ],
        'road_repeat': 14.0, 'ground_repeat': 12.0, 'road_surface': 46,
        'pak': 't114_sewer_speedway.pak',
        'props': {
            'pipe': {'label': '🛢 Tuyaux et vannes', 'pak': 't114_sewer_speedway.pak', 'scale': (0.9, 1.2), 'spacing': 10.0,
                    'models': ['models/Levels/Crash1/factory/C1_Factory_Pipe01.igz', 'models/Levels/Crash2/L221_PistonItAway/PIST_Pipes01.igz', 'models/Levels/Octane/T114_Sewer_Speedway/T114_Pipe01.igz', 'models/Levels/Octane/T114_Sewer_Speedway/T114_Pipe_bracket.igz', 'models/Levels/Octane/T114_Sewer_Speedway/T114_Pipe_gasket.igz', 'models/Levels/Octane/T114_Sewer_Speedway/T114_Valve.igz', 'models/Levels/Octane/T151_NGin_Labs/NGin_Labs_Assets/NGin_Labs_pipe_01_gray.igz', 'models/Levels/Octane/T151_NGin_Labs/NGin_Labs_Assets/NGin_Labs_pipe_set_01.igz']},
            'barrel': {'label': '🛢 Barils et boîtiers', 'pak': 't114_sewer_speedway.pak', 'scale': (0.9, 1.2), 'spacing': 7.0,
                    'models': ['models/Levels/Crash1/factory/Barrel_02.igz', 'models/Levels/Crash1/factory/C1_Factory_Hatch01.igz', 'models/Levels/Octane/T114_Sewer_Speedway/T114_Electrical_box.igz']},
            'fan': {'label': '⚙ Ventilateurs et engrenages', 'pak': 't114_sewer_speedway.pak', 'scale': (0.8, 1.1), 'spacing': 15.0,
                    'models': ['models/Levels/Octane/T114_Sewer_Speedway/T114_Fanblade_static.igz', 'models/Levels/Octane/T151_NGin_Labs/NGin_Labs_Assets/NGin_Labs_Silo_fan.igz']},
            'beam': {'label': '🏗 Poutres', 'pak': 't114_sewer_speedway.pak', 'scale': (0.9, 1.1), 'spacing': 14.0,
                    'models': ['models/Levels/Octane/T114_Sewer_Speedway/T114_Beam_Support.igz']},
        },
    },
    'grottes': {
        'label': 'Grottes mystérieuses (Mystery Caves)',
        'road': 'textures/ColorMap,textures@!levels!Octane!T113_Mystery_Caves!T113_Cave_Ground!T113_Mud02_C`tga,111.igz',
        'materials': [
            ('CaveSand', 'cavesand.png', 'textures/ColorMap,textures@!levels!Octane!T113_Mystery_Caves!T113_Cave_Ground!T113_Sand_01a_C`tga,111.igz', 38, 'Sable', (0.43, 0.37, 0.32)),
            ('CaveSandDark', 'cavesanddark.png', 'textures/ColorMap,textures@!levels!Octane!T113_Mystery_Caves!T113_Cave_Ground!T113_Sand_02_C`tga,111.igz', 38, 'Sable sombre', (0.44, 0.34, 0.24)),
            ('CaveMoss', 'cavemoss.png', 'textures/ColorMap,textures@!levels!Crash1!jungle!C1_Moss03_C`tga,111.igz', 5, 'Mousse (ralentit)', (0.14, 0.32, 0.13)),
            ('CaveRock', 'rock.png', 'textures/ColorMap,textures@!levels!Octane!T113_Mystery_Caves!T113_Cave_Rockwall!T113_Cave_Rockwall_01_C`tga,111.igz', 4, 'Roche', (0.34, 0.34, 0.34)),
        ],
        'road_repeat': 14.0, 'ground_repeat': 12.0, 'road_surface': 7,
        'pak': 't113_mystery_caves.pak',
        'props': {
            'crystal': {'label': '💎 Cristaux', 'pak': 't113_mystery_caves.pak', 'scale': (0.8, 1.3), 'spacing': 12.0,
                    'models': ['models/Levels/Octane/T113_Mystery_Caves/T113_Mystery_Caves_assets/T113_Mystery_Caves_Crystal_01.igz', 'models/Levels/Octane/T113_Mystery_Caves/T113_Mystery_Caves_assets/T113_Mystery_Caves_Crystal_02.igz', 'models/Levels/Octane/T113_Mystery_Caves/T113_Mystery_Caves_assets/T113_Mystery_Caves_Crystal_03.igz', 'models/Levels/Octane/T113_Mystery_Caves/T113_Mystery_Caves_assets/T113_Mystery_Caves_Crystal_Group_01.igz', 'models/Levels/Octane/T113_Mystery_Caves/T113_Mystery_Caves_assets/T113_Mystery_Caves_Crystal_Group_02.igz', 'models/Levels/Octane/T113_Mystery_Caves/T113_Mystery_Caves_assets/T113_Mystery_Caves_Crystal_Group_03.igz', 'models/Levels/Octane/T113_Mystery_Caves/T113_Mystery_Caves_assets/T113_Rope_Crystal02.igz', 'models/Levels/Octane/T113_Mystery_Caves/T113_Mystery_Caves_assets/T113_Rope_Crystal03.igz']},
            'fossil': {'label': '🦴 Fossiles', 'pak': 't113_mystery_caves.pak', 'scale': (0.9, 1.1), 'spacing': 18.0,
                    'models': ['models/Levels/Crash3/Prehistoric/C3_DinoFossil_Skull_A.igz', 'models/Levels/Crash3/Prehistoric/C3_DinoFossil_Skull_B.igz', 'models/Levels/Crash3/Prehistoric/C3_DinoFossil_Spine_A.igz']},
            'plant': {'label': '🌿 Plantes', 'pak': 't113_mystery_caves.pak', 'scale': (0.8, 1.3), 'spacing': 6.0,
                    'models': ['models/Levels/Crash1/L103_TheGreatGate/VinesIvy01.igz', 'models/Levels/Crash1/L110_TheLostCity/L110_grassClump01.igz', 'models/Levels/Crash1/jungle/C1_Bush03.igz', 'models/Levels/Octane/A115_Skull_Rock/A115_Foliage.igz']},
            'rock': {'label': '🪨 Rochers', 'pak': 't113_mystery_caves.pak', 'scale': (0.6, 1.1), 'spacing': 12.0,
                    'models': ['models/Levels/Crash3/L301_ToadVillage/L103_ModBoulder03.igz', 'models/Levels/Octane/T112_Roos_Tubes/T112_Roos_Tube_Assets/T112_Rock_01.igz', 'models/Levels/Octane/T113_Mystery_Caves/T113_Mystery_Caves_assets/Mystery_Caves_Rock01.igz', 'models/Levels/Octane/T113_Mystery_Caves/T113_Mystery_Caves_assets/Mystery_Caves_Rock02.igz', 'models/Levels/Octane/T113_Mystery_Caves/T113_Mystery_Caves_assets/Mystery_Caves_Rock03.igz', 'models/Levels/Octane/T113_Mystery_Caves/T113_Mystery_Caves_assets/Mystery_Caves_Rock04.igz', 'models/Levels/Octane/T113_Mystery_Caves/T113_Mystery_Caves_assets/Mystery_Caves_Rock05.igz', 'models/Levels/Octane/T113_Mystery_Caves/T113_Mystery_Caves_assets/Mystery_Caves_Rocks06.igz']},
            'pillar': {'label': '🏛 Piliers et ruines', 'pak': 't113_mystery_caves.pak', 'scale': (0.9, 1.1), 'spacing': 22.0,
                    'models': ['models/Levels/Crash1/L111_TempleRuins/L111_BlockStone01.igz', 'models/Levels/Crash1/L111_TempleRuins/L111_TempleStonepillar01.igz', 'models/Levels/Crash1/temple/C1_Pillar_Grin.igz', 'models/Levels/Octane/T113_Mystery_Caves/T113_Mystery_Caves_assets/T113_TempleStonepillar03.igz']},
        },
    },
    'tubes': {
        'label': "Tubes sous-marins (Roo's Tubes)",
        'road': 'textures/ColorMap,textures@!levels!Octane!T112_Roos_Tube!T112_Metal_Plates!T112_Metal_Plate_Ground_01_C`tga,111.igz',
        'materials': [
            ('SeaSand', 'seasand.png', 'textures/ColorMap,textures@!levels!Crash3!Sea!C3_Sea_SandUnderwater01_D`tga,111.igz', 38, 'Sable marin', (0.57, 0.45, 0.38)),
            ('SeaMoss', 'seamoss.png', 'textures/ColorMap,textures@!levels!Octane!T112_Roos_Tube!T112_Sea_RockMoss01_C`tga,111.igz', 4, 'Roche moussue', (0.36, 0.47, 0.49)),
            ('SeaPlates', 'seaplates.png', 'textures/ColorMap,textures@!levels!Octane!T112_Roos_Tube!T112_Metal_Plates!T112_Metal_Plate_Ground_01_Wet_C`tga,111.igz', 4, 'Plaques mouillées', (0.28, 0.28, 0.27)),
            ('SeaRock', 'rock.png', 'textures/ColorMap,textures@!levels!Octane!T112_Roos_Tube!T112_Rockwall!T112_Rockwall_01_C`png,111.igz', 4, 'Roche', (0.28, 0.28, 0.28)),
        ],
        'road_repeat': 14.0, 'ground_repeat': 12.0, 'road_surface': 4,
        'pak': 't112_roos_tubes.pak',
        'props': {
            'coral': {'label': '🪸 Coraux', 'pak': 't112_roos_tubes.pak', 'scale': (0.8, 1.3), 'spacing': 5.0,
                    'models': ['models/Levels/Crash3/Sea/C3_Sea_CoralFan01.igz', 'models/Levels/Crash3/Sea/C3_Sea_CoralFan02.igz', 'models/Levels/Crash3/Sea/C3_Sea_CoralLeather01.igz', 'models/Levels/Crash3/Sea/C3_Sea_CoralLeather02.igz', 'models/Levels/Crash3/Sea/C3_Sea_CoralLeather03.igz', 'models/Levels/Crash3/Sea/C3_Sea_CoralPiece02.igz', 'models/Levels/Crash3/Sea/C3_Sea_CoralSpotted01.igz']},
            'kelp': {'label': '🌿 Algues', 'pak': 't112_roos_tubes.pak', 'scale': (0.8, 1.4), 'spacing': 4.0,
                    'models': ['models/Levels/Crash3/Sea/C3_Sea_Grass01.igz', 'models/Levels/Crash3/Sea/C3_Sea_Kelp01.igz', 'models/Levels/Crash3/Sea/C3_Sea_Kelp02.igz', 'models/Levels/Crash3/Sea/C3_Sea_Kelp03.igz', 'models/Levels/Crash3/Sea/C3_Sea_Kelp04.igz', 'models/Levels/Octane/T112_Roos_Tubes/T112_Roos_Tube_Assets/Sea_Grass_Blue.igz', 'models/Levels/Octane/T112_Roos_Tubes/T112_Roos_Tube_Assets/Sea_Grass_Purple.igz', 'models/Levels/Octane/T112_Roos_Tubes/T112_Roos_Tube_Assets/T112_grassClump01.igz']},
            'rock': {'label': '🪨 Rochers', 'pak': 't112_roos_tubes.pak', 'scale': (0.6, 1.1), 'spacing': 12.0,
                    'models': ['models/Levels/Octane/T112_Roos_Tubes/T112_Roos_Tube_Assets/T112_Rock_01.igz', 'models/Levels/Octane/T112_Roos_Tubes/T112_Roos_Tube_Assets/T112_Rock_02.igz', 'models/Levels/Octane/T112_Roos_Tubes/T112_Roos_Tube_Assets/T112_Rock_03.igz', 'models/Levels/Octane/T112_Roos_Tubes/T112_Roos_Tube_Assets/T112_Rock_04.igz', 'models/Levels/Octane/T112_Roos_Tubes/T112_Roos_Tube_Assets/T112_Rock_05.igz']},
            'bones': {'label': '🦴 Os et étoiles de mer', 'pak': 't112_roos_tubes.pak', 'scale': (0.9, 1.1), 'spacing': 15.0,
                    'models': ['models/Levels/Octane/H110_Nsanity_Beach/H110_starfish02.igz', 'models/Levels/Octane/T111_Crash_Cove/starfish01.igz', 'models/Levels/Octane/T112_Roos_Tubes/T112_Roos_Tube_Assets/T112_Roos_Tube_Starfish.igz', 'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_Bones_01.igz', 'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_Bones_02.igz', 'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_Bones_04.igz', 'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_Bones_05.igz']},
            'big': {'label': '⛰ Piliers de roche (fond)', 'pak': 't112_roos_tubes.pak', 'scale': (0.7, 1.0), 'spacing': 35.0, 'big': True,
                    'models': ['models/Levels/Crash3/Sea/C3_Sea_RockPillar01.igz', 'models/Levels/Crash3/Sea/C3_Sea_RockPillar02.igz', 'models/Levels/Crash3/Sea/C3_Sea_RockPillar03.igz', 'models/Levels/Crash3/Sea/C3_Sea_RockPillar04.igz', 'models/Levels/Crash3/Sea/C3_Sea_RockPillar06.igz', 'models/Levels/Crash3/Sea/C3_Sea_RockPillar07.igz']},
        },
    },
    'stade': {
        'label': 'Circuit automobile (Turbo Track)',
        'road': 'textures/ColorMap,textures@!levels!Octane!T121_Slide_Coliseum!T121_Asphalt01_C`tga,111.igz',
        'materials': [
            ('Lawn', 'lawn.png', 'textures/ColorMap,textures@!levels!Octane!T111_Crash_Cove!T111_Grass!T111_GrassTile01_C`tga,111.igz', 5, 'Pelouse (ralentit)', (0.24, 0.36, 0.17)),
            ('Asphalt', 'asphalt.png', 'textures/ColorMap,textures@!levels!Octane!T121_Slide_Coliseum!T121_Asphalt02_C`tga,111.igz', 46, 'Asphalte', (0.22, 0.23, 0.24)),
            ('TrackDirt', 'trackdirt.png', 'textures/ColorMap,textures@!levels!Crash3!Medieval!C3_DirtRocky01_C`tga,111.igz', 7, 'Terre', (0.44, 0.34, 0.22)),
            ('Concrete', 'rock.png', 'textures/ColorMap,textures@!levels!Octane!T121_Slide_Coliseum!T121_ConcreteBlock01_C`tga,111.igz', 4, 'Béton', (0.41, 0.42, 0.44)),
        ],
        'road_repeat': 14.0, 'ground_repeat': 12.0, 'road_surface': 46,
        'pak': 't122_turbo_track.pak',
        'props': {
            'tire': {'label': '🛞 Pneus et bottes de foin', 'pak': 't122_turbo_track.pak', 'scale': (1.0, 1.0), 'spacing': 6.0,
                    'models': ['models/Levels/Octane/T121_Slide_Coliseum/T121_Wheel_Tire.igz', 'models/Levels/Octane/T122_Turbo_Track/T122_Haystack_01.igz', 'models/Levels/Octane/T122_Turbo_Track/T122_Haystack_02.igz', 'models/Levels/Octane/T122_Turbo_Track/T122_Wheel_Tire.igz']},
            'statue': {'label': '🏆 Statues et trophées', 'pak': 't122_turbo_track.pak', 'scale': (1.0, 1.0), 'spacing': 30.0,
                    'models': ['models/Levels/Octane/T122_Turbo_Track/T122_Statue_BaseKart.igz', 'models/Levels/Octane/T122_Turbo_Track/T122_Statue_KartCrikey.igz', 'models/Levels/Octane/T122_Turbo_Track/T122_Statue_KartOxide_01.igz', 'models/Levels/Octane/T122_Turbo_Track/T122_Statue_KartTeamCrash.igz', 'models/Levels/Octane/T122_Turbo_Track/T122_Trophy_01.igz']},
            'kart': {'label': '🏎 Karts exposés', 'pak': 't122_turbo_track.pak', 'scale': (1.0, 1.0), 'spacing': 18.0,
                    'models': ['models/Levels/Octane/T122_Turbo_Track/T122_KartDeadinator.igz', 'models/Levels/Octane/T122_Turbo_Track/T122_KartDoomBuggy.igz', 'models/Levels/Octane/T122_Turbo_Track/T122_KartSpeed.igz', 'models/Levels/Octane/T122_Turbo_Track/T122_KartTrikee.igz']},
            'big': {'label': '🏢 Immeubles (fond)', 'pak': 't122_turbo_track.pak', 'scale': (0.8, 1.0), 'spacing': 45.0, 'big': True,
                    'models': ['models/Levels/Octane/T242_Android_Alley/T242_AA_Building_A.igz', 'models/Levels/Octane/T242_Android_Alley/T242_AA_Building_B.igz', 'models/Levels/Octane/T242_Android_Alley/T242_AA_Building_C.igz', 'models/Levels/Octane/T242_Android_Alley/T242_AA_Building_D.igz']},
        },
    },
    'pyramide': {
        'label': "Pyramide de Papu (Papu's Pyramid)",
        'road': 'textures/ColorMap,textures@!levels!Crash1!jungle!C1_Dirt_Path01_C`tga,111.igz',
        'materials': [
            ('PapuGrass', 'papugrass.png', 'textures/ColorMap,textures@!levels!Crash1!jungle!C1_GrassTile01_C`tga,111.igz', 5, 'Herbe (ralentit)', (0.31, 0.43, 0.18)),
            ('Forest', 'forest.png', 'textures/ColorMap,textures@!levels!Crash1!jungle!C1_ForestFloor01_C`tga,111.igz', 7, 'Sol de forêt', (0.22, 0.39, 0.25)),
            ('PapuSand', 'papusand.png', 'textures/ColorMap,textures@!levels!Crash1!jungle!C1_SandWavy_C`tga,111.igz', 38, 'Sable', (0.6, 0.58, 0.44)),
            ('PapuStone', 'rock.png', 'textures/ColorMap,textures@!levels!Crash1!temple!templeStone_Base_Papus_C`tga,111.igz', 4, 'Pierre du temple', (0.5, 0.45, 0.31)),
        ],
        'road_repeat': 14.0, 'ground_repeat': 12.0, 'road_surface': 7,
        'pak': 't133_papus_pyramid.pak',
        'props': {
            'palm': {'label': '🌴 Palmiers', 'pak': 't133_papus_pyramid.pak', 'scale': (0.85, 1.2), 'spacing': 10.0,
                    'models': ['models/Levels/Crash1/jungle/C1_PalmCluster01.igz', 'models/Levels/Crash1/jungle/C1_PalmCluster02_vista.igz', 'models/Levels/Crash1/jungle/C1_PalmTree01.igz', 'models/Levels/Crash1/jungle/C1_PalmTree01_Exotic.igz', 'models/Levels/Crash1/jungle/C1_PalmTree02.igz', 'models/Levels/Crash1/jungle/C1_PalmTree02_Exotic.igz', 'models/Levels/Crash1/jungle/C1_PalmTree03.igz', 'models/Levels/Crash1/jungle/C1_PalmTree03_Exotic.igz']},
            'plant': {'label': '🌺 Plantes et fleurs', 'pak': 't133_papus_pyramid.pak', 'scale': (0.8, 1.3), 'spacing': 4.0,
                    'models': ['models/Levels/Crash1/jungle/C1_Bush01.igz', 'models/Levels/Crash1/jungle/C1_FlowerClump01.igz', 'models/Levels/Crash1/jungle/C1_FlowerClump02.igz', 'models/Levels/Crash1/jungle/C1_FlowerClumpRed01.igz', 'models/Levels/Crash1/jungle/C1_FlowerClumpYellow01.igz', 'models/Levels/Crash1/jungle/C1_HighResGrass_02.igz', 'models/Levels/Crash1/jungle/C1_MushroomSmall02.igz', 'models/Levels/Octane/A115_Skull_Rock/A115_Foliage.igz']},
            'statue': {'label': '🗿 Piliers, torches et trône', 'pak': 't133_papus_pyramid.pak', 'scale': (0.9, 1.1), 'spacing': 22.0,
                    'models': ['models/Levels/Crash1/temple/C1_Pillar_Angry.igz', 'models/Levels/Crash1/temple/C1_Pillar_Grin.igz', 'models/Levels/Crash1/temple/ZiggTorch.igz', 'models/Levels/Crash1/village/C1_Papu_Throne.igz', 'models/Levels/Crash1/village/C1_TikiTorch.igz', 'models/Levels/Crash2/Temple/Ruin_BigHead_02.igz', 'models/Levels/Crash2/Temple/Ruin_Bighead_03.igz', 'models/Levels/Octane/T133_Papus_Pyramid/Papus_Pyramid_Assets/Brazier.igz']},
            'hut': {'label': '🛖 Huttes et boucliers', 'pak': 't133_papus_pyramid.pak', 'scale': (1.0, 1.0), 'spacing': 20.0,
                    'models': ['models/Levels/Crash1/L107_HogWild/L107_Hut01.igz', 'models/Levels/Crash1/L111_TempleRuins/Papus_Pyramid_cauldron.igz', 'models/Levels/Octane/T133_Papus_Pyramid/Papus_Pyramid_Assets/Papus_Pyramid_shield_a.igz', 'models/Levels/Octane/T133_Papus_Pyramid/Papus_Pyramid_Assets/Papus_Pyramid_shield_b.igz', 'models/Levels/Octane/T133_Papus_Pyramid/Papus_Pyramid_Assets/Papus_Pyramid_shield_c.igz', 'models/Levels/Octane/T133_Papus_Pyramid/Papus_Pyramid_Assets/Papus_Pyramid_shield_d.igz']},
            'big': {'label': '⛰ Falaise et pyramide (fond)', 'pak': 't133_papus_pyramid.pak', 'scale': (0.7, 1.0), 'spacing': 45.0, 'big': True,
                    'models': ['models/Levels/Octane/T133_Papus_Pyramid/Papus_Pyramid_Assets/Papus_Pyramid_Ziggurat01.igz', 'models/Levels/Octane/T133_Papus_Pyramid/Papus_Pyramid_Assets/Papus_Pyramid_cliff01.igz']},
        },
    },
    'mines': {
        'label': 'Mines du dragon (Dragon Mines)',
        'road': 'textures/ColorMap,textures@!levels!Octane!T142_Dragon_Mines!T142_Sand!T142_Mud_Track_05_C`tga,111.igz',
        'materials': [
            ('MineSand', 'minesand.png', 'textures/ColorMap,textures@!levels!Octane!T142_Dragon_Mines!T142_Sand!T142_Ground_Sand_01_C`tga,111.igz', 38, 'Sable de mine', (0.51, 0.45, 0.36)),
            ('MineSand2', 'minesand2.png', 'textures/ColorMap,textures@!levels!Octane!T142_Dragon_Mines!T142_Sand!T142_Ground_Sand_02_C`tga,111.igz', 38, 'Sable gris', (0.49, 0.41, 0.33)),
            ('Rubble', 'rubble.png', 'textures/ColorMap,textures@!levels!Crash1!jungle!C1_Rubble01_mines_C`tga,111.igz', 7, 'Éboulis', (0.28, 0.28, 0.31)),
            ('MineRock', 'rock.png', 'textures/ColorMap,textures@!levels!Crash1!cave!C1_CaveRockwall_C`tga,111.igz', 4, 'Roche', (0.57, 0.44, 0.4)),
        ],
        'road_repeat': 14.0, 'ground_repeat': 12.0, 'road_surface': 7,
        'pak': 't142_dragon_mines.pak',
        'props': {
            'cart': {'label': '⛏ Wagonnets, barils et outils', 'pak': 't142_dragon_mines.pak', 'scale': (1.0, 1.0), 'spacing': 10.0,
                    'models': ['models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/T142_Dragon_Mines_Barrel.igz', 'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/T142_Dragon_Mines_Minecart_coal.igz', 'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/T142_Dragon_Mines_Minecart_empty.igz', 'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/T142_Dragon_Mines_Minecart_props.igz', 'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/T142_Dragon_Mines_Pickaxe_01.igz', 'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/T142_Dragon_Mines_Spade_01.igz', 'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/T142_Dragon_Mines_Treausre_chest.igz']},
            'wood': {'label': '🪵 Poteaux, clôtures et lanternes', 'pak': 't142_dragon_mines.pak', 'scale': (1.0, 1.0), 'spacing': 8.0,
                    'models': ['models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/Dragon_Mines_lantern.igz', 'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/Dragon_Mines_wood_fence_01.igz', 'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/Dragon_Mines_wood_post_01.igz', 'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/Dragon_Mines_wood_post_long_01.igz', 'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/Dragon_Mines_wood_post_support_01.igz']},
            'gems': {'label': '💎 Trésors', 'pak': 't142_dragon_mines.pak', 'scale': (0.9, 1.2), 'spacing': 10.0,
                    'models': ['models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/Dragon_Mines_Treasures_Ankh_Gold.igz', 'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/Dragon_Mines_Treasures_Ankh_Platnium.igz', 'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/Dragon_Mines_Treasures_Ankh_Sapphire.igz', 'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/Dragon_Mines_Treasures_BlueGem.igz', 'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/Dragon_Mines_Treasures_GoldKey.igz', 'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/Dragon_Mines_Treasures_GreenGem.igz', 'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/Dragon_Mines_Treasures_OrangeGem.igz', 'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/Dragon_Mines_Treasures_PowerGem.igz']},
            'rock': {'label': '🪨 Rochers', 'pak': 't142_dragon_mines.pak', 'scale': (0.7, 1.2), 'spacing': 12.0,
                    'models': ['models/Levels/Crash1/L101_NSanityBeach/C1_RubbleRocks01.igz', 'models/Levels/Crash1/jungle/C1_Rock01.igz', 'models/Levels/Crash1/jungle/C1_Rocks06.igz']},
        },
    },
    'labo': {
        'label': 'Laboratoire (N. Gin Labs)',
        'road': 'textures/ColorMap,textures@!levels!Octane!T151_NGin_Labs!T151_Metal_Plate_Ground!T151_Metal_Plate_Ground_01_C`tga,111.igz',
        'materials': [
            ('LabFloor', 'labfloor.png', 'textures/ColorMap,textures@!levels!Crash1!factory!C1_Factory_Floor01_C`tga,111.igz', 4, "Sol d'usine", (0.55, 0.5, 0.43)),
            ('LabGrid', 'labgrid.png', 'textures/ColorMap,textures@!levels!Crash2!Sewer!SEW_MetalFloor_01_C`tga,111.igz', 4, 'Plancher métallique', (0.45, 0.46, 0.47)),
            ('LabDirt', 'labdirt.png', 'textures/ColorMap,textures@!levels!Crash1!factory!C1_Factory_Dirt01_C`tga,111.igz', 7, 'Terre', (0.24, 0.24, 0.24)),
            ('LabMetal', 'rock.png', 'textures/ColorMap,textures@!levels!Crash1!factory!C1_MetalPanel_01_C`tga,111.igz', 4, 'Métal', (0.67, 0.32, 0.28)),
        ],
        'road_repeat': 14.0, 'ground_repeat': 12.0, 'road_surface': 4,
        'pak': 't151_ngin_labs.pak',
        'props': {
            'tesla': {'label': '⚡ Bobines et réacteurs', 'pak': 't151_ngin_labs.pak', 'scale': (0.9, 1.1), 'spacing': 22.0,
                    'models': ['models/Levels/Octane/T151_NGin_Labs/NGin_Labs_Assets/NGin_Labs_TeslaCoil03.igz', 'models/Levels/Octane/T151_NGin_Labs/NGin_Labs_Assets/NGin_Labs_TeslaCoil09.igz', 'models/Levels/Octane/T151_NGin_Labs/NGin_Labs_Assets/NGin_Labs_teslacoil_02_goo.igz']},
            'pipe': {'label': '🛢 Tuyaux', 'pak': 't151_ngin_labs.pak', 'scale': (0.9, 1.1), 'spacing': 10.0,
                    'models': ['models/Levels/Crash1/factory/C1_Factory_Pipe01.igz', 'models/Levels/Crash1/factory/C1_Factory_Pipe01_NGinLabs.igz', 'models/Levels/Crash2/L221_PistonItAway/PIST_Pipes01.igz', 'models/Levels/Crash2/L221_PistonItAway/PIST_Pipes03.igz', 'models/Levels/Crash2/L221_PistonItAway/PIST_Pipes03Cold.igz', 'models/Levels/Crash2/L221_PistonItAway/PIST_Pipes03Hot.igz', 'models/Levels/Octane/T151_NGin_Labs/NGin_Labs_Assets/NGin_Labs_pipe_01.igz', 'models/Levels/Octane/T151_NGin_Labs/NGin_Labs_Assets/NGin_Labs_pipe_goo.igz']},
            'machine': {'label': '🤖 Machines', 'pak': 't151_ngin_labs.pak', 'scale': (1.0, 1.0), 'spacing': 18.0,
                    'models': ['models/Levels/Crash1/L118_GeneratorRoom/C1_GeneratorTank01.igz', 'models/Levels/Crash1/L118_GeneratorRoom/C1_GeneratorTank03.igz', 'models/Levels/Crash1/L118_GeneratorRoom/NGin_Labs_generator_01.igz', 'models/Levels/Crash1/L118_GeneratorRoom/NGin_Labs_generator_02.igz', 'models/Levels/Crash1/L118_GeneratorRoom/NGin_Labs_generator_03.igz', 'models/Levels/Crash1/castle/C1_Castle_Computer01.igz', 'models/Levels/Crash1/castle/C1_Castle_Computer02.igz', 'models/Levels/Crash1/factory/Barrel_02.igz']},
            'fence': {'label': '🚧 Grilles et flèches', 'pak': 't151_ngin_labs.pak', 'scale': (1.0, 1.0), 'spacing': 10.0,
                    'models': ['models/Levels/Octane/T151_NGin_Labs/NGin_Labs_Assets/NGin_Labs_direction_arrows.igz', 'models/Levels/Octane/T151_NGin_Labs/NGin_Labs_Assets/NGin_Labs_security_fence.igz']},
        },
    },
    'chateau': {
        'label': 'Château de Cortex (Cortex Castle)',
        'road': 'textures/ColorMap,textures@!levels!Octane!T152_Cortex_Castle!T152_RockFloor01_C`tga,111.igz',
        'materials': [
            ('CastleGrass', 'castlegrass.png', 'textures/ColorMap,textures@!levels!Crash3!Medieval!C3_GrassTile02_C`tga,111.igz', 5, 'Herbe (ralentit)', (0.39, 0.33, 0.08)),
            ('CastlePath', 'castlepath.png', 'textures/ColorMap,textures@!levels!Crash3!Medieval!C3_MedievalPath01_C`tga,111.igz', 7, 'Chemin', (0.45, 0.43, 0.31)),
            ('CastleWet', 'castlewet.png', 'textures/ColorMap,textures@!levels!Octane!T152_Cortex_Castle!T152_RockFloor01_Wet_C`tga,111.igz', 4, 'Dalles mouillées', (0.33, 0.35, 0.34)),
            ('CastleStone', 'rock.png', 'textures/ColorMap,textures@!levels!Octane!T152_Cortex_Castle!T152_Stone_Brick01_C`tga,111.igz', 4, 'Pierre', (0.37, 0.38, 0.37)),
        ],
        'road_repeat': 14.0, 'ground_repeat': 12.0, 'road_surface': 4,
        'pak': 't152_cortex_castle.pak',
        'props': {
            'torch': {'label': '🔥 Torches et chandelles', 'pak': 't152_cortex_castle.pak', 'scale': (1.0, 1.0), 'spacing': 12.0,
                    'models': ['models/Levels/Crash1/castle/C1_Castle_Candle.igz', 'models/Levels/Crash1/castle/C1_Castle_ColumnCandle.igz', 'models/Levels/Octane/T152_Cortex_Castle/T152_Cortex_Castle_Torch.igz']},
            'statue': {'label': '🗿 Statues et gargouilles', 'pak': 't152_cortex_castle.pak', 'scale': (1.0, 1.0), 'spacing': 30.0,
                    'models': ['models/Levels/Crash1/castle/C1_Castle_Gargoyle.igz', 'models/Levels/Crash1/castle/T152_Castle_Gargoyle.igz', 'models/Levels/Octane/T152_Cortex_Castle/T152_CortexStatue_Left.igz', 'models/Levels/Octane/T152_Cortex_Castle/T152_CortexStatue_Neutral.igz', 'models/Levels/Octane/T152_Cortex_Castle/T152_CortexStatue_Right.igz', 'models/Levels/Octane/T152_Cortex_Castle/T152_Cortex_Head.igz']},
            'column': {'label': '🏛 Colonnes et tours', 'pak': 't152_cortex_castle.pak', 'scale': (0.9, 1.1), 'spacing': 25.0,
                    'models': ['models/Levels/Crash1/castle/C1_Castle_ColumnArch.igz', 'models/Levels/Crash1/castle/C1_Castle_ColumnRibs.igz', 'models/Levels/Octane/T152_Cortex_Castle/T152_ChainPillar.igz', 'models/Levels/Octane/T152_Cortex_Castle/T152_RedTower.igz']},
            'spike': {'label': '🚧 Grilles et pics', 'pak': 't152_cortex_castle.pak', 'scale': (1.0, 1.0), 'spacing': 10.0,
                    'models': ['models/Levels/Octane/T152_Cortex_Castle/Cortex_Castle_Assets/Cortex_Castle_cathedral_spiked_fence.igz', 'models/Levels/Octane/T152_Cortex_Castle/Cortex_Castle_Assets/Cortex_Castle_metal_spike_01.igz', 'models/Levels/Octane/T152_Cortex_Castle/T152_Cortex_Castle_Cage.igz', 'models/Levels/Octane/T152_Cortex_Castle/T152_Spikes.igz']},
            'rock': {'label': '🪨 Rochers et fleurs', 'pak': 't152_cortex_castle.pak', 'scale': (0.8, 1.2), 'spacing': 6.0,
                    'models': ['models/Levels/Crash1/jungle/C1_FlowerClump02.igz', 'models/Levels/Crash1/jungle/C1_GrassBend01.igz', 'models/Levels/Crash1/jungle/C1_Rock05.igz', 'models/Levels/Crash1/jungle/C1_Rocks06.igz']},
        },
    },
    'ciel': {
        'label': 'Îles volantes (Hot Air Skyway)',
        'road': 'textures/ColorMap,textures@!levels!Octane!T153_Hot_Air_Skyway!T153_GroundTexture_C`tga,111.igz',
        'materials': [
            ('SkyGrass', 'skygrass.png', 'textures/ColorMap,textures@!levels!Crash3!Asia!C3_Asia_Grass01_C`tga,111.igz', 5, 'Herbe (ralentit)', (0.29, 0.36, 0.14)),
            ('SkyGrass2', 'skygrass2.png', 'textures/ColorMap,textures@!levels!Crash3!Asia!C3_Asia_Grass02_C`tga,111.igz', 5, 'Herbe claire (ralentit)', (0.18, 0.34, 0.13)),
            ('SkyPlanks', 'skyplanks.png', 'textures/ColorMap,textures@!levels!Crash1!factory!C1_woodPlankFloor_C`tga,111.igz', 13, 'Planches', (0.3, 0.2, 0.17)),
            ('SkyBrick', 'rock.png', 'textures/ColorMap,textures@!levels!Octane!T153_Hot_Air_Skyway!T153_BrickSide_C`tif,111.igz', 4, 'Briques', (0.79, 0.63, 0.45)),
        ],
        'road_repeat': 14.0, 'ground_repeat': 12.0, 'road_surface': 4,
        'pak': 't153_hot_air_skyway.pak',
        'props': {
            'card': {'label': '🃏 Cartes et loterie', 'pak': 't153_hot_air_skyway.pak', 'scale': (1.0, 1.0), 'spacing': 15.0,
                    'models': ['models/Levels/Octane/T153_Hot_Air_Skyway/T153_Card_01.igz', 'models/Levels/Octane/T153_Hot_Air_Skyway/T153_Card_02.igz', 'models/Levels/Octane/T153_Hot_Air_Skyway/T153_Card_03.igz', 'models/Levels/Octane/T153_Hot_Air_Skyway/T153_Card_04.igz', 'models/Levels/Octane/T153_Hot_Air_Skyway/T_153_Lottery_Tokens_Pack.igz']},
            'big': {'label': '🗼 Tours et plateformes (fond)', 'pak': 't153_hot_air_skyway.pak', 'scale': (0.7, 1.0), 'spacing': 50.0, 'big': True,
                    'models': ['models/Levels/Octane/T153_Hot_Air_Skyway/T153_FlyingPlatform_01.igz', 'models/Levels/Octane/T153_Hot_Air_Skyway/T153_Hotel_Helipad.igz', 'models/Levels/Octane/T153_Hot_Air_Skyway/T153_Tower_01.igz']},
        },
    },
    'espace': {
        'label': 'Station spatiale (Hyper Spaceway)',
        'road': 'textures/ColorMap,textures@!levels!Octane!T255_Hyper_Spaceway!T255_Road_01_C`tga,111.igz',
        'materials': [
            ('MoonSand', 'moonsand.png', 'textures/ColorMap,textures@!levels!Octane!T255_Hyper_Spaceway!T255_Ground_01_Sand_C`tga,111.igz', 38, 'Sable lunaire', (0.61, 0.4, 0.25)),
            ('Pebbles', 'pebbles.png', 'textures/ColorMap,textures@!levels!Octane!T255_Hyper_Spaceway!T255_Ground_01_Pebbles_C`tga,111.igz', 7, 'Cailloux', (0.34, 0.28, 0.23)),
            ('MoonSand3', 'moonsand3.png', 'textures/ColorMap,textures@!levels!Octane!T255_Hyper_Spaceway!T255_Ground_03_Sand_C`tga,111.igz', 38, 'Sable gris', (0.36, 0.28, 0.23)),
            ('SpaceConcrete', 'rock.png', 'textures/ColorMap,textures@!levels!Octane!T255_Hyper_Spaceway!T255_Concrete_02_C`tga,111.igz', 4, 'Béton', (0.37, 0.41, 0.32)),
        ],
        'road_repeat': 14.0, 'ground_repeat': 12.0, 'road_surface': 46,
        'pak': 't255_hyper_spaceway.pak',
        'props': {
            'crystal': {'label': '💎 Cristaux et astéroïdes', 'pak': 't255_hyper_spaceway.pak', 'scale': (0.7, 1.2), 'spacing': 14.0,
                    'models': ['models/Levels/Octane/T255_Hyper_Spaceway/T255_Crystal_02.igz', 'models/Levels/Octane/T255_Hyper_Spaceway/T255_Crystal_03.igz', 'models/Levels/Octane/T255_Hyper_Spaceway/T255_asteroide.igz']},
            'tech': {'label': '🖥 Écrans et panneaux', 'pak': 't255_hyper_spaceway.pak', 'scale': (1.0, 1.0), 'spacing': 12.0,
                    'models': ['models/Levels/Octane/T255_Hyper_Spaceway/T255_Fence_01.igz', 'models/Levels/Octane/T255_Hyper_Spaceway/T255_Keyboard_01.igz', 'models/Levels/Octane/T255_Hyper_Spaceway/T255_Keyboard_02.igz', 'models/Levels/Octane/T255_Hyper_Spaceway/T255_Screen_01.igz', 'models/Levels/Octane/T255_Hyper_Spaceway/T255_Screen_02.igz']},
            'pipe': {'label': '🛢 Tuyaux et arches', 'pak': 't255_hyper_spaceway.pak', 'scale': (1.0, 1.0), 'spacing': 20.0,
                    'models': ['models/Levels/Octane/T255_Hyper_Spaceway/T255_Hyper_Spaceway_Archway.igz', 'models/Levels/Octane/T255_Hyper_Spaceway/T255_Hyper_Spaceway_Joint.igz', 'models/Levels/Octane/T255_Hyper_Spaceway/T255_Hyper_Spaceway_Pipe_02.igz', 'models/Levels/Octane/T255_Hyper_Spaceway/T255_Hyper_Spaceway_Wire_Joint.igz']},
            'big': {'label': '🗼 Tours (fond)', 'pak': 't255_hyper_spaceway.pak', 'scale': (0.6, 1.0), 'spacing': 60.0, 'big': True,
                    'models': ['models/Levels/Octane/T255_Hyper_Spaceway/T255_Goliath_01.igz', 'models/Levels/Octane/T255_Hyper_Spaceway/T255_Main_Tower.igz']},
        },
    },
    'volcan': {
        'label': 'Île volcanique (Inferno Island)',
        'road': 'textures/ColorMap,textures@!levels!Octane!T211_Inferno_Island!T211_SandTrack_C`tga,111.igz',
        'materials': [
            ('VolcSand', 'volcsand.png', 'textures/ColorMap,textures@!levels!Octane!T211_Inferno_Island!T211_Sand01_D`tga,111.igz', 38, 'Sable', (0.39, 0.29, 0.26)),
            ('LavaDry', 'lavadry.png', 'textures/ColorMap,textures@!levels!Octane!T211_Inferno_Island!Ground_Rocks!T211_GroundLavaDry02_C`tga,111.igz', 7, 'Lave séchée', (0.25, 0.22, 0.22)),
            ('VolcGrass', 'volcgrass.png', 'textures/ColorMap,textures@!levels!Octane!T111_Crash_Cove!T111_Grass!T111_GrassTile01_C`tga,111.igz', 5, 'Herbe (ralentit)', (0.24, 0.36, 0.17)),
            ('VolcRock', 'rock.png', 'textures/ColorMap,textures@!levels!Octane!T211_Inferno_Island!Ground_Rocks!T211_GroundRocks01_C`tga,111.igz', 4, 'Roche volcanique', (0.27, 0.24, 0.24)),
        ],
        'road_repeat': 14.0, 'ground_repeat': 12.0, 'road_surface': 38,
        'pak': 't211_inferno_island.pak',
        'props': {
            'palm': {'label': '🌴 Palmiers', 'pak': 't211_inferno_island.pak', 'scale': (0.85, 1.2), 'spacing': 10.0,
                    'models': ['models/Levels/Octane/T211_Inferno_Island/Polish/T211_Cove_Tree_01.igz', 'models/Levels/Octane/T211_Inferno_Island/Polish/T211_Palm_Tree_01.igz']},
            'plant': {'label': '🌿 Plantes étranges', 'pak': 't211_inferno_island.pak', 'scale': (0.8, 1.3), 'spacing': 5.0,
                    'models': ['models/Levels/Crash1/jungle/C1_Bush03.igz', 'models/Levels/Octane/T211_Inferno_Island/Polish/Alien_Plant_01.igz', 'models/Levels/Octane/T211_Inferno_Island/Polish/T211_Alien_Bush_02.igz', 'models/Levels/Octane/T211_Inferno_Island/Polish/T211_Alien_Fern_01.igz', 'models/Levels/Octane/T211_Inferno_Island/Polish/T211_Alien_Plant_03.igz', 'models/Levels/Octane/T211_Inferno_Island/Polish/T211_Alien_Vines_01.igz', 'models/Levels/Octane/T211_Inferno_Island/Polish/T211_Alien_Vines_02.igz', 'models/Levels/Octane/T211_Inferno_Island/Polish/T211_Alien_Vines_03.igz']},
            'tiki': {'label': '🗿 Tikis et statues', 'pak': 't211_inferno_island.pak', 'scale': (1.0, 1.0), 'spacing': 25.0,
                    'models': ['models/Levels/Octane/T211_Inferno_Island/T211_Inferno_Mask_02.igz', 'models/Levels/Octane/T211_Inferno_Island/T211_Inferno_UkaUkas.igz', 'models/Levels/Octane/T211_Inferno_Island/T211_MonkeyStatue_02.igz']},
            'rock': {'label': '🪨 Rochers', 'pak': 't211_inferno_island.pak', 'scale': (0.6, 1.1), 'spacing': 12.0,
                    'models': ['models/Levels/Octane/T211_Inferno_Island/Polish/T211_Rock_Modul_V2.igz', 'models/Levels/Octane/T211_Inferno_Island/T211_Inferno_RockA.igz', 'models/Levels/Octane/T211_Inferno_Island/T211_Inferno_RockB.igz', 'models/Levels/Octane/T211_Inferno_Island/T211_Inferno_RockC.igz', 'models/Levels/Octane/T211_Inferno_Island/T211_Inferno_RockD.igz', 'models/Levels/Octane/T211_Inferno_Island/T211_Inferno_RockE.igz', 'models/Levels/Octane/T211_Inferno_Island/T211_Inferno_RockF.igz', 'models/Levels/Octane/T211_Inferno_Island/T211_RockModul01.igz']},
            'hut': {'label': '🛖 Huttes et épaves', 'pak': 't211_inferno_island.pak', 'scale': (1.0, 1.0), 'spacing': 30.0,
                    'models': ['models/Levels/Crash1/L107_HogWild/L107_Hut02.igz', 'models/Levels/Octane/T211_Inferno_Island/Destroyed_Boat_01.igz', 'models/Levels/Octane/T211_Inferno_Island/Polish/T211_Hut_Simple.igz']},
        },
    },
    'ruines': {
        'label': 'Ruines glacées (Barin Ruins)',
        'road': 'textures/ColorMap,textures@!levels!Octane!T222_Barin_Ruins!T222_Stone_Path01_C`tga,111.igz',
        'materials': [
            ('RuinStone', 'ruinstone.png', 'textures/ColorMap,textures@!levels!Octane!T222_Barin_Ruins!T222_StoneSolid_C`tga,111.igz', 4, 'Pierre', (0.47, 0.43, 0.3)),
            ('RuinIce', 'ruinice.png', 'textures/ColorMap,textures@!levels!Octane!T222_Barin_Ruins!T222_IceTrack_C`tga,111.igz', 10, 'Glace (glisse)', (0.67, 0.69, 0.75)),
            ('RuinSnow', 'ruinsnow.png', 'textures/ColorMap,textures@!levels!Crash2!Snow!C2_Snow01_C`tga,111.igz', 8, 'Neige', (0.57, 0.61, 0.62)),
            ('RuinRock', 'rock.png', 'textures/ColorMap,textures@!levels!Octane!T222_Barin_Ruins!T222_Rockwall_01_C`tga,111.igz', 4, 'Roche', (0.25, 0.26, 0.26)),
        ],
        'road_repeat': 14.0, 'ground_repeat': 12.0, 'road_surface': 4,
        'pak': 't222_barin_ruins.pak',
        'props': {
            'pillar': {'label': '🏛 Piliers', 'pak': 't222_barin_ruins.pak', 'scale': (0.9, 1.1), 'spacing': 22.0,
                    'models': ['models/Levels/Octane/T222_Barin_Ruins/T222_Statue_pillarA_topA.igz', 'models/Levels/Octane/T222_Barin_Ruins/T222_Statue_pillarA_topB.igz']},
            'snow': {'label': '❄ Tas de neige', 'pak': 't222_barin_ruins.pak', 'scale': (0.8, 1.3), 'spacing': 8.0,
                    'models': ['models/Levels/Octane/T222_Barin_Ruins/T222_SnowPileA.igz', 'models/Levels/Octane/T222_Barin_Ruins/T222_SnowPileB.igz', 'models/Levels/Octane/T222_Barin_Ruins/T222_SnowPileC.igz']},
            'rock': {'label': '🪨 Rochers', 'pak': 't222_barin_ruins.pak', 'scale': (0.6, 1.1), 'spacing': 14.0,
                    'models': ['models/Levels/Octane/T222_Barin_Ruins/TEMP_Boulder.igz']},
        },
    },
    'abysses': {
        'label': 'Fonds marins (Deep Sea Driving)',
        'road': 'textures/ColorMap,textures@!levels!Octane!T223_Deep_Sea_Driving!T223_Sand_01_C`tga,111.igz',
        'materials': [
            ('DeepSandRock', 'deepsandrock.png', 'textures/ColorMap,textures@!levels!Octane!T223_Deep_Sea_Driving!T223_SandRocky_01_C`tga,111.igz', 38, 'Sable rocheux', (0.27, 0.26, 0.27)),
            ('DeepSand', 'deepsand.png', 'textures/ColorMap,textures@!levels!Crash3!Sea!C3_Sea_SandUnderwater01_D`tga,111.igz', 38, 'Sable marin', (0.57, 0.45, 0.38)),
            ('DeepMoss', 'deepmoss.png', 'textures/ColorMap,textures@!levels!Crash3!Sea!C3_Sea_RockMoss01_C`tga,111.igz', 4, 'Roche moussue', (0.22, 0.33, 0.35)),
            ('DeepRock', 'rock.png', 'textures/ColorMap,textures@!levels!Octane!T223_Deep_Sea_Driving!T223_Rockwall_02_test_C`png,111.igz', 4, 'Roche', (0.14, 0.2, 0.16)),
        ],
        'road_repeat': 14.0, 'ground_repeat': 12.0, 'road_surface': 38,
        'pak': 't223_deep_sea_driving.pak',
        'props': {
            'coral': {'label': '🪸 Coraux et coquillages', 'pak': 't223_deep_sea_driving.pak', 'scale': (0.8, 1.3), 'spacing': 6.0,
                    'models': ['models/Levels/Crash3/Sea/C3_Sea_CoralPiece01.igz', 'models/Levels/Crash3/Sea/C3_Sea_CoralPiece02.igz', 'models/Levels/Crash3/Sea/C3_Sea_CoralPiece03.igz', 'models/Levels/Crash3/Sea/C3_Sea_RedCoral01.igz', 'models/Levels/Octane/T112_Roos_Tubes/T112_Roos_Tube_Assets/T112_Roos_Tube_Brain_Coral_01.igz', 'models/Levels/Octane/T112_Roos_Tubes/T112_Roos_Tube_Assets/T112_Roos_Tube_Brain_Coral_02.igz', 'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_Brain_Coral_01.igz', 'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_Brain_Coral_02.igz']},
            'kelp': {'label': '🌿 Algues', 'pak': 't223_deep_sea_driving.pak', 'scale': (0.8, 1.4), 'spacing': 4.0,
                    'models': ['models/Levels/Crash3/Sea/C3_Sea_Kelp01.igz', 'models/Levels/Crash3/Sea/C3_Sea_Kelp02.igz', 'models/Levels/Crash3/Sea/C3_Sea_Kelp03.igz', 'models/Levels/Crash3/Sea/C3_Sea_Kelp04.igz', 'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_Sea_Grass02.igz', 'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_Sea_Grass_01.igz', 'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_Sea_Grass_02.igz', 'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_Sea_Grass_03.igz']},
            'machine': {'label': '⚙ Machines et scaphandre', 'pak': 't223_deep_sea_driving.pak', 'scale': (1.0, 1.0), 'spacing': 18.0,
                    'models': ['models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_Furnace.igz', 'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_Gear.igz', 'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_PressureMeter.igz', 'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_Scaphandre.igz', 'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_Valve.igz']},
            'mushroom': {'label': '🍄 Champignons', 'pak': 't223_deep_sea_driving.pak', 'scale': (0.8, 1.2), 'spacing': 10.0,
                    'models': ['models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_Mushroom.igz', 'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_Mushroom_Green_Intro_Cavern.igz', 'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_Mushroom_Ground.igz', 'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_Mushroom_Intro_Cavern.igz']},
            'rock': {'label': '🪨 Rochers', 'pak': 't223_deep_sea_driving.pak', 'scale': (0.6, 1.1), 'spacing': 14.0,
                    'models': ['models/Levels/Crash3/Sea/C3_Sea_RockPillar01.igz', 'models/Levels/Crash3/Sea/C3_Sea_Stalagmite01.igz', 'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_cave_rock_02.igz', 'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_cave_rock_03.igz', 'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_cave_rock_04.igz', 'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_cave_rock_07.igz', 'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_cave_rock_08.igz', 'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_cave_rock_09.igz']},
        },
    },
    'temps': {
        'label': 'Pays des horloges (Out of Time)',
        'road': 'textures/ColorMap,textures@!levels!Octane!T231_Out_of_Time!T231_Asphalt_01_C`tga,111.igz',
        'materials': [
            ('TimeSand', 'timesand.png', 'textures/ColorMap,textures@!levels!Octane!T231_Out_of_Time!T231_Sand_01_C`tga,111.igz', 38, 'Sable', (0.46, 0.33, 0.35)),
            ('TimeSandFlat', 'timesandflat.png', 'textures/ColorMap,textures@!levels!Octane!T231_Out_of_Time!T231_SandFlat_01_C`tga,111.igz', 38, 'Sable plat', (0.62, 0.56, 0.42)),
            ('TimePlanks', 'timeplanks.png', 'textures/ColorMap,textures@!levels!Octane!T231_Out_of_Time!T231_woodPlankFloor_C`tga,111.igz', 13, 'Planches', (0.44, 0.33, 0.27)),
            ('TimeCliff', 'rock.png', 'textures/ColorMap,textures@!levels!Octane!T231_Out_of_Time!T231_Cliff_01_C`tga,111.igz', 4, 'Roche', (0.66, 0.43, 0.36)),
        ],
        'road_repeat': 14.0, 'ground_repeat': 12.0, 'road_surface': 46,
        'pak': 't231_out_of_time.pak',
        'props': {
            'gears': {'label': '⚙ Engrenages et horloges', 'pak': 't231_out_of_time.pak', 'scale': (0.8, 1.1), 'spacing': 25.0,
                    'models': ['models/Levels/Octane/T231_Out_of_Time/T231_ClockGears_01/T231_ClockGears_01.igz', 'models/Levels/Octane/T231_Out_of_Time/T231_Clock_01.igz', 'models/Levels/Octane/T231_Out_of_Time/T231_Gears_01.igz']},
            'plant': {'label': '🍄 Plantes et champignons', 'pak': 't231_out_of_time.pak', 'scale': (0.8, 1.3), 'spacing': 6.0,
                    'models': ['models/Levels/Octane/T231_Out_of_Time/T231_Roots_01.igz', 'models/Levels/Octane/T231_Out_of_Time/T231_Roots_02.igz', 'models/Levels/Octane/T231_Out_of_Time/T231_Shroom_01.igz', 'models/Levels/Octane/T231_Out_of_Time/T231_Shroom_02.igz', 'models/Levels/Octane/T231_Out_of_Time/T231_Shroom_03.igz']},
            'deco': {'label': '🏮 Lanternes, clôtures, moulins', 'pak': 't231_out_of_time.pak', 'scale': (1.0, 1.0), 'spacing': 14.0,
                    'models': ['models/Levels/Octane/T231_Out_of_Time/T231_Fence_01.igz', 'models/Levels/Octane/T231_Out_of_Time/T231_Lantern_01.igz', 'models/Levels/Octane/T231_Out_of_Time/T231_Lantern_02.igz', 'models/Levels/Octane/T231_Out_of_Time/T231_MetalFenceBroken_01.igz', 'models/Levels/Octane/T231_Out_of_Time/T231_Windmill_01.igz']},
            'big': {'label': '⛰ Falaises (fond)', 'pak': 't231_out_of_time.pak', 'scale': (0.7, 1.0), 'spacing': 45.0, 'big': True,
                    'models': ['models/Levels/Octane/T231_Out_of_Time/T231_CliffMedium_01.igz', 'models/Levels/Octane/T231_Out_of_Time/T231_Cliff_05.igz', 'models/Levels/Octane/T231_Out_of_Time/T_231_Cliff_02.igz']},
        },
    },
    'horloge': {
        'label': 'Tour enneigée (Clockwork Wumpa)',
        'road': 'textures/ColorMap,textures@!levels!Octane!T152_Cortex_Castle!T152_RockFloor01_C`tga,111.igz',
        'materials': [
            ('ClockSnow', 'clocksnow.png', 'textures/ColorMap,textures@!levels!Octane!T232_Clockwork_Wumpa!T232_Snow_02_C`tga,111.igz', 8, 'Neige', (0.55, 0.57, 0.65)),
            ('ClockSnow2', 'clocksnow2.png', 'textures/ColorMap,textures@!levels!Octane!T143_Polar_Pass!T143_Snow_01_C`tga,111.igz', 8, 'Neige poudreuse', (0.73, 0.76, 0.78)),
            ('ClockPlanks', 'clockplanks.png', 'textures/ColorMap,textures@!levels!Crash1!factory!C1_woodPlankFloor_C`tga,111.igz', 13, 'Planches', (0.3, 0.2, 0.17)),
            ('ClockBrick', 'rock.png', 'textures/ColorMap,textures@!levels!Octane!T232_Clockwork_Wumpa!T232_StoneBrick_01_Snow_C`tga,111.igz', 4, 'Pierre enneigée', (0.43, 0.42, 0.4)),
        ],
        'road_repeat': 14.0, 'ground_repeat': 12.0, 'road_surface': 4,
        'pak': 't232_clockwork_wumpa.pak',
        'props': {
            'barrel': {'label': '🍎 Barils, pommes et wagonnets', 'pak': 't232_clockwork_wumpa.pak', 'scale': (1.0, 1.0), 'spacing': 10.0,
                    'models': ['models/Levels/Octane/T232_Clockwork_Wumpa/T232_Barrel_01.igz', 'models/Levels/Octane/T232_Clockwork_Wumpa/T232_Clockwork_Wumpa_Barrel_01.igz', 'models/Levels/Octane/T232_Clockwork_Wumpa/T232_Container_002.igz', 'models/Levels/Octane/T232_Clockwork_Wumpa/T232_JuiceContainer_01.igz', 'models/Levels/Octane/T232_Clockwork_Wumpa/T232_MiningCart_01.igz']},
            'deco': {'label': '🏮 Lanternes, braseros, gargouilles', 'pak': 't232_clockwork_wumpa.pak', 'scale': (1.0, 1.0), 'spacing': 14.0,
                    'models': ['models/Levels/Octane/T232_Clockwork_Wumpa/T232_Brazero_01.igz', 'models/Levels/Octane/T232_Clockwork_Wumpa/T232_Gargoyle_02.igz', 'models/Levels/Octane/T232_Clockwork_Wumpa/T232_Lantern_01.igz', 'models/Levels/Octane/T232_Clockwork_Wumpa/T232_Tablette_01.igz', 'models/Levels/Octane/T232_Clockwork_Wumpa/T232_Tablette_02.igz']},
            'gear': {'label': '⚙ Engrenages et tuyaux', 'pak': 't232_clockwork_wumpa.pak', 'scale': (0.9, 1.1), 'spacing': 20.0,
                    'models': ['models/Levels/Octane/T232_Clockwork_Wumpa/T232_Gear_01.igz', 'models/Levels/Octane/T232_Clockwork_Wumpa/T232_Gear_01_RoadGPE.igz', 'models/Levels/Octane/T232_Clockwork_Wumpa/T232_Pipes_02.igz']},
            'snow': {'label': '❄ Congères', 'pak': 't232_clockwork_wumpa.pak', 'scale': (0.8, 1.3), 'spacing': 10.0,
                    'models': ['models/Levels/Octane/T232_Clockwork_Wumpa/T232_Snowmound_01.igz', 'models/Levels/Octane/T232_Clockwork_Wumpa/T232_Snowmound_02.igz', 'models/Levels/Octane/T232_Clockwork_Wumpa/T232_Snowmound_03.igz', 'models/Levels/Octane/T232_Clockwork_Wumpa/T232_Snowmound_04.igz', 'models/Levels/Octane/T232_Clockwork_Wumpa/T232_Snowmound_05.igz']},
            'big': {'label': '🗼 Tours (fond)', 'pak': 't232_clockwork_wumpa.pak', 'scale': (0.7, 1.0), 'spacing': 50.0, 'big': True,
                    'models': ['models/Levels/Octane/T232_Clockwork_Wumpa/T232_TowerBell_Arch_01.igz', 'models/Levels/Octane/T232_Clockwork_Wumpa/T_232_Tower_1.igz']},
        },
    },
    'orage': {
        'label': "Tour de l'orage (Thunder Struck)",
        'road': 'textures/ColorMap,textures@!levels!Octane!T233_Thunder_Struck!T233_Floor_D`png,111.igz',
        'materials': [
            ('StormWet', 'stormwet.png', 'textures/ColorMap,textures@!levels!Octane!T233_Thunder_Struck!T233_Floor_Wet_D`png,111.igz', 4, 'Sol mouillé', (0.28, 0.2, 0.13)),
            ('StormWood', 'stormwood.png', 'textures/ColorMap,textures@!levels!Octane!T233_Thunder_Struck!T233_Wood_Tile_02_D`tga,111.igz', 13, 'Bois', (0.38, 0.24, 0.16)),
            ('StormPlatform', 'stormplatform.png', 'textures/ColorMap,textures@!levels!Octane!T233_Thunder_Struck!T233_RockPlatform_D`tga,111.igz', 4, 'Dalle de roche', (0.34, 0.36, 0.37)),
            ('StormCliff', 'rock.png', 'textures/ColorMap,textures@!levels!Octane!T233_Thunder_Struck!T233_Cliff_03_D`tga,111.igz', 4, 'Roche', (0.31, 0.3, 0.29)),
        ],
        'road_repeat': 14.0, 'ground_repeat': 12.0, 'road_surface': 4,
        'pak': 't233_thunder_struck.pak',
        'props': {
            'tesla': {'label': '⚡ Bobines et lampes', 'pak': 't233_thunder_struck.pak', 'scale': (1.0, 1.0), 'spacing': 18.0,
                    'models': ['models/Levels/Octane/T233_Thunder_Struck/T233_Building_TopCoil.igz']},
            'gear': {'label': '⚙ Engrenages et horloges', 'pak': 't233_thunder_struck.pak', 'scale': (0.9, 1.1), 'spacing': 25.0,
                    'models': ['models/Levels/Octane/T233_Thunder_Struck/T233_GearTower_01.igz']},
            'vine': {'label': '🌿 Lianes et souches', 'pak': 't233_thunder_struck.pak', 'scale': (0.8, 1.2), 'spacing': 8.0,
                    'models': ['models/Levels/Octane/T233_Thunder_Struck/T233_Thunder_BarkEnd_Cap.igz', 'models/Levels/Octane/T233_Thunder_Struck/T233_Thunder_BarkEnd_Stump.igz']},
            'rock': {'label': '🪨 Rochers', 'pak': 't233_thunder_struck.pak', 'scale': (0.6, 1.1), 'spacing': 12.0,
                    'models': ['models/Levels/Crash1/jungle/C1_Rock01.igz', 'models/Levels/Octane/T233_Thunder_Struck/T233_RockPlatform.igz']},
            'big': {'label': '⛰ Falaises (fond)', 'pak': 't233_thunder_struck.pak', 'scale': (0.7, 1.0), 'spacing': 50.0, 'big': True,
                    'models': ['models/Levels/Octane/T233_Thunder_Struck/T233_108_Cliff.igz', 'models/Levels/Octane/T233_Thunder_Struck/T233_Cliff_004.igz']},
        },
    },
    'usine': {
        'label': 'Chaîne de montage (Assembly Lane)',
        'road': 'textures/ColorMap,textures@!levels!Octane!T241_Assembly_Line!T241_Assembly_Lane_Metal_plates_02_C`tga,111.igz',
        'materials': [
            ('FactoryFloor', 'factoryfloor.png', 'textures/ColorMap,textures@!levels!Crash1!factory!C1_Factory_Floor01_C`tga,111.igz', 4, "Sol d'usine", (0.55, 0.5, 0.43)),
            ('FactoryMud', 'factorymud.png', 'textures/ColorMap,textures@!levels!Octane!T144_Tiny_Arena!T144_Mud01_C`tga,111.igz', 7, 'Boue', (0.35, 0.27, 0.19)),
            ('FactoryDirt', 'factorydirt.png', 'textures/ColorMap,textures@!levels!Octane!T241_Assembly_Line!T241_dirtTile_Mound_C`tga,111.igz', 7, 'Terre', (0.36, 0.26, 0.17)),
            ('FactoryPanel', 'rock.png', 'textures/ColorMap,textures@!levels!Octane!T241_Assembly_Line!T241_Assembly_Lane_Metal_Panel_Grey_C`tga,111.igz', 4, 'Métal', (0.49, 0.46, 0.43)),
        ],
        'road_repeat': 14.0, 'ground_repeat': 12.0, 'road_surface': 4,
        'pak': 't241_assembly_lane.pak',
        'props': {
            'drum': {'label': '🛢 Fûts et vannes', 'pak': 't241_assembly_lane.pak', 'scale': (1.0, 1.0), 'spacing': 10.0,
                    'models': ['models/Levels/Crash1/L118_GeneratorRoom/C1_GeneratorTank03.igz', 'models/Levels/Octane/T241_Assembly_Lane/T241_Assembly_Lane_Steel_Mill_Bucket_3.igz', 'models/Levels/Octane/T241_Assembly_Lane/T241_Assembly_Lane_Valve.igz', 'models/Levels/Octane/T241_Assembly_Lane/T241_Assembly_Lane_Valve_Sphere.igz']},
            'machine': {'label': '🤖 Machines et écrans', 'pak': 't241_assembly_lane.pak', 'scale': (1.0, 1.0), 'spacing': 18.0,
                    'models': ['models/Levels/Crash1/L126_TheLab/theLab_panel1.igz', 'models/Levels/Crash1/castle/C1_Castle_Computer01.igz', 'models/Levels/Crash1/castle/C1_Castle_Computer02.igz', 'models/Levels/Octane/T241_Assembly_Lane/T241_Assembly_Lane_TV.igz', 'models/Levels/Octane/T241_Assembly_Lane/T241_Assembly_Lane_Xray.igz']},
            'pipe': {'label': '🛢 Tuyaux', 'pak': 't241_assembly_lane.pak', 'scale': (1.0, 1.0), 'spacing': 14.0,
                    'models': ['models/Levels/Octane/T241_Assembly_Lane/T241_Assembly_Lane_PipeSet_Post_01.igz', 'models/Levels/Octane/T241_Assembly_Lane/T241_Assembly_Lane_PipeSet_S_01.igz', 'models/Levels/Octane/T241_Assembly_Lane/T241_Assembly_Lane_Pipe_Curve.igz']},
            'magnet': {'label': '🧲 Aimants et pilons', 'pak': 't241_assembly_lane.pak', 'scale': (1.0, 1.0), 'spacing': 25.0,
                    'models': ['models/Levels/Octane/T241_Assembly_Lane/T241_Assembly_Lane_Magnet_Stomper.igz']},
        },
    },
    'futur': {
        'label': 'Ville du futur (Electron Avenue)',
        'road': 'textures/ColorMap,textures@!levels!Octane!T243_Electron_Avenue!T243_Electron_Avenue_Hexsphalt_Road_C`tga,111.igz',
        'materials': [
            ('FutureTiles', 'futuretiles.png', 'textures/ColorMap,textures@!levels!Octane!T243_Electron_Avenue!tiles_C`tga,111.igz', 4, 'Dalles', (0.74, 0.74, 0.74)),
            ('FutureMetal', 'futuremetal.png', 'textures/ColorMap,textures@!levels!Octane!T243_Electron_Avenue!T243_EA_RoadMetal_C`tga,111.igz', 4, 'Métal', (0.27, 0.24, 0.29)),
            ('FuturePath', 'futurepath.png', 'textures/ColorMap,textures@!levels!Crash3!Future!C3_Future_Path01_C`tga,111.igz', 4, 'Allée', (0.53, 0.57, 0.57)),
            ('FuturePanel', 'rock.png', 'textures/ColorMap,textures@!levels!Octane!T242_Android_Alley!T242_MetalPanel_01_D`tga,111.igz', 4, 'Panneaux', (0.2, 0.22, 0.21)),
        ],
        'road_repeat': 14.0, 'ground_repeat': 12.0, 'road_surface': 46,
        'pak': 't243_electron_avenue.pak',
        'props': {
            'big': {'label': '🏢 Immeubles (fond)', 'pak': 't243_electron_avenue.pak', 'scale': (0.7, 1.0), 'spacing': 60.0, 'big': True,
                    'models': ['models/Levels/Octane/T243_Electron_Avenue/EA_Building_CenterTower.igz', 'models/Levels/Octane/T243_Electron_Avenue/ElectronAve_building001_a.igz', 'models/Levels/Octane/T243_Electron_Avenue/ElectronAve_building002_a.igz', 'models/Levels/Octane/T243_Electron_Avenue/ElectronAve_building003_a.igz', 'models/Levels/Octane/T243_Electron_Avenue/ElectronAve_building004_a.igz', 'models/Levels/Octane/T243_Electron_Avenue/ElectronAve_building005_a.igz', 'models/Levels/Octane/T243_Electron_Avenue/ElectronAve_building006_a.igz']},
        },
    },
    'banquise': {
        'label': 'Banquise viking (Polar Pass)',
        'road': 'textures/ColorMap,textures@!levels!Octane!T143_Polar_Pass!T143_TrackSnow_01_C`png,111.igz',
        'materials': [
            ('PolarSnow', 'polarsnow.png', 'textures/ColorMap,textures@!levels!Octane!T143_Polar_Pass!T143_FrozenSnow_01_C`tga,111.igz', 8, 'Neige gelée', (0.4, 0.5, 0.59)),
            ('PolarLumpy', 'polarlumpy.png', 'textures/ColorMap,textures@!levels!Crash2!Snow!C2_Snow_Lumpy01_C`tga,111.igz', 8, 'Neige bosselée', (0.84, 0.89, 0.92)),
            ('PolarIce', 'polarice.png', 'textures/ColorMap,textures@!levels!Crash2!Snow!C2_Ice_Wall01_C`tga,111.igz', 10, 'Glace (glisse)', (0.43, 0.71, 0.85)),
            ('PolarCliff', 'rock.png', 'textures/ColorMap,textures@!levels!Octane!T143_Polar_Pass!T143_Cliff_Mid_01_C`tga,111.igz', 4, 'Roche', (0.52, 0.53, 0.55)),
        ],
        'road_repeat': 14.0, 'ground_repeat': 12.0, 'road_surface': 8,
        'pak': 't143_polar_pass.pak',
        'props': {
            'pine': {'label': '🌲 Arbres', 'pak': 't143_polar_pass.pak', 'scale': (0.8, 1.3), 'spacing': 10.0,
                    'models': ['models/Levels/Crash2/Snow/C2_Dead_Tree01.igz', 'models/Levels/Crash2/Snow/C2_Pine_Tree01.igz', 'models/Levels/Crash2/Snow/T143_Birch_Tree01.igz']},
            'house': {'label': '🏠 Maisons vikings', 'pak': 't143_polar_pass.pak', 'scale': (1.0, 1.0), 'spacing': 30.0,
                    'models': ['models/Levels/Octane/T143_Polar_Pass/T143_Hut.igz']},
            'statue': {'label': '🗿 Statues et bonhommes de neige', 'pak': 't143_polar_pass.pak', 'scale': (1.0, 1.0), 'spacing': 25.0,
                    'models': ['models/Levels/Octane/T143_Polar_Pass/T143_Snowman.igz', 'models/Levels/Octane/T143_Polar_Pass/T143_Totem_Statue.igz', 'models/Levels/Octane/T143_Polar_Pass/T143_Totem_Statue02.igz', 'models/Levels/Octane/T143_Polar_Pass/T143_VikingHead.igz', 'models/Levels/Octane/T143_Polar_Pass/T143_WalrusStatue.igz']},
            'crystal': {'label': '💎 Cristaux', 'pak': 't143_polar_pass.pak', 'scale': (0.8, 1.2), 'spacing': 12.0,
                    'models': ['models/Levels/Crash1/cave/T143_Crystal_Blue01.igz', 'models/Levels/Crash2/Snow/Crystal_Blue01.igz', 'models/Levels/Crash2/Snow/T143_Crystal_blue02.igz']},
            'deco': {'label': '⚓ Barques, tonneaux, filets', 'pak': 't143_polar_pass.pak', 'scale': (1.0, 1.0), 'spacing': 12.0,
                    'models': ['models/Levels/Octane/T143_Polar_Pass/T143_Barrel.igz', 'models/Levels/Octane/T143_Polar_Pass/T143_Boat01.igz', 'models/Levels/Octane/T143_Polar_Pass/T143_Fishnet01.igz', 'models/Levels/Octane/T143_Polar_Pass/T143_Snowpile.igz', 'models/Levels/Octane/T143_Polar_Pass/T143_Weathercock.igz']},
            'big': {'label': '⛰ Falaises et montagne (fond)', 'pak': 't143_polar_pass.pak', 'scale': (0.6, 1.0), 'spacing': 50.0, 'big': True,
                    'models': ['models/Levels/Crash1/jungle/T143_Mountain01.igz', 'models/Levels/Octane/T143_Polar_Pass/T143_Polar_Pass_CliffLarge_01.igz']},
        },
    },
    'gorge': {
        'label': 'Gorge du météore (Meteor Gorge)',
        'road': 'textures/ColorMap,textures@!levels!Octane!T221_Meteor_Gorge!T221_Stone_Path01_C`tga,111.igz',
        'materials': [
            ('GorgeMud', 'gorgemud.png', 'textures/ColorMap,textures@!levels!Octane!T221_Meteor_Gorge!T221_Mud02_C`tga,111.igz', 7, 'Boue', (0.11, 0.09, 0.13)),
            ('GorgeSnow', 'gorgesnow.png', 'textures/ColorMap,textures@!levels!Crash2!Snow!C2_Snow01_C`tga,111.igz', 8, 'Neige', (0.57, 0.61, 0.62)),
            ('GorgeDirt', 'gorgedirt.png', 'textures/ColorMap,textures@!levels!Crash1!cave!C1_dirttile01_C`tga,111.igz', 7, 'Terre', (0.43, 0.34, 0.2)),
            ('GorgeCliff', 'rock.png', 'textures/ColorMap,textures@!levels!Octane!T221_Meteor_Gorge!T221_Cliff_01_C`tga,111.igz', 4, 'Roche', (0.33, 0.33, 0.37)),
        ],
        'road_repeat': 14.0, 'ground_repeat': 12.0, 'road_surface': 4,
        'pak': 't221_meteor_gorge.pak',
        'props': {
            'lantern': {'label': '🏮 Lanternes', 'pak': 't221_meteor_gorge.pak', 'scale': (1.0, 1.0), 'spacing': 15.0,
                    'models': ['models/Levels/Octane/T221_Meteor_Gorge/T221_Meteor_Gorge_lantern.igz']},
            'statue': {'label': '🐟 Statues de poisson', 'pak': 't221_meteor_gorge.pak', 'scale': (0.9, 1.1), 'spacing': 30.0,
                    'models': ['models/Levels/Octane/T221_Meteor_Gorge/T221_Meteor_Gorge_fish_statue.igz', 'models/Levels/Octane/T221_Meteor_Gorge/T221_Meteor_Gorge_small_fish_statue.igz']},
            'pipe': {'label': '🛢 Tuyaux de lave', 'pak': 't221_meteor_gorge.pak', 'scale': (1.0, 1.0), 'spacing': 14.0,
                    'models': ['models/Levels/Octane/T221_Meteor_Gorge/T221_Meteor_Gorge_Pipe_Coupler_01.igz', 'models/Levels/Octane/T221_Meteor_Gorge/T221_Meteor_Gorge_Pipe_Lava_elbow_01.igz', 'models/Levels/Octane/T221_Meteor_Gorge/T221_Meteor_Gorge_Pipe_detail_01.igz', 'models/Levels/Octane/T221_Meteor_Gorge/T221_Meteor_Gorge_Pipe_elbow_01.igz', 'models/Levels/Octane/T221_Meteor_Gorge/T221_Meteor_Gorge_valve_wheel_01.igz']},
            'snow': {'label': '❄ Glaçons et congères', 'pak': 't221_meteor_gorge.pak', 'scale': (0.8, 1.2), 'spacing': 10.0,
                    'models': ['models/Levels/Octane/T141_Blizzard_Bluff/T141_SnowPile.igz', 'models/Levels/Octane/T221_Meteor_Gorge/T221_Meteor_Gorge_IcicleA.igz', 'models/Levels/Octane/T221_Meteor_Gorge/T221_Meteor_Gorge_IcicleB.igz', 'models/Levels/Octane/T221_Meteor_Gorge/T221_Meteor_Gorge_IcicleC.igz', 'models/Levels/Octane/T221_Meteor_Gorge/T221_Meteor_Gorge_snowdrift_01.igz']},
            'big': {'label': '⛰ Falaises et bâtiments miniers (fond)', 'pak': 't221_meteor_gorge.pak', 'scale': (0.7, 1.0), 'spacing': 45.0, 'big': True,
                    'models': ['models/Levels/Octane/T221_Meteor_Gorge/T221_CliffMedium_01.igz', 'models/Levels/Octane/T221_Meteor_Gorge/T221_Cliff_02.igz', 'models/Levels/Octane/T221_Meteor_Gorge/T221_MG_MineBldg_mod_A.igz', 'models/Levels/Octane/T221_Meteor_Gorge/T221_MG_MineBldg_mod_B.igz', 'models/Levels/Octane/T221_Meteor_Gorge/T221_MG_MineBldg_mod_D.igz']},
        },
    },
    'boogie': {
        'label': 'Forêt tropicale (Jungle Boogie)',
        'road': 'textures/ColorMap,textures@!levels!Octane!T212_Jungle_Boogie!T212_tracks_C`tga,111.igz',
        'materials': [
            ('BoogieDirt', 'boogiedirt.png', 'textures/ColorMap,textures@!levels!Octane!T212_Jungle_Boogie!T_SH_dirtTile_C`tga,111.igz', 7, 'Terre', (0.56, 0.38, 0.24)),
            ('BoogieMoss', 'boogiemoss.png', 'textures/ColorMap,textures@!levels!Crash1!jungle!C1_Moss03_C`tga,111.igz', 5, 'Mousse (ralentit)', (0.14, 0.32, 0.13)),
            ('BoogieStone', 'boogiestone.png', 'textures/ColorMap,textures@!levels!Octane!T212_Jungle_Boogie!T212_Ground_Stone_C`tga,111.igz', 4, 'Pierre', (0.59, 0.47, 0.36)),
            ('BoogieRock', 'rock.png', 'textures/ColorMap,textures@!levels!Octane!T212_Jungle_Boogie!T212_BackRock_C`tga,111.igz', 4, 'Roche', (0.54, 0.56, 0.54)),
        ],
        'road_repeat': 14.0, 'ground_repeat': 12.0, 'road_surface': 7,
        'pak': 't212_jungle_boogie.pak',
        'props': {
            'tree': {'label': '🌳 Arbres', 'pak': 't212_jungle_boogie.pak', 'scale': (0.85, 1.2), 'spacing': 12.0,
                    'models': ['models/Levels/Octane/T211_Inferno_Island/Polish/T211_Palm_Tree_01.igz', 'models/Levels/Octane/T212_Jungle_Boogie/T212_Jungle_Boogie_Tree_01.igz']},
            'plant': {'label': '🌿 Plantes', 'pak': 't212_jungle_boogie.pak', 'scale': (0.8, 1.3), 'spacing': 5.0,
                    'models': ['models/Levels/Octane/A115_Skull_Rock/A115_Foliage_02.igz', 'models/Levels/Octane/A115_Skull_Rock/A115_Foliage_03_fern01.igz', 'models/Levels/Octane/A115_Skull_Rock/A115_Foliage_03_fern03.igz', 'models/Levels/Octane/T111_Crash_Cove/T111_HighResGrass_02.igz', 'models/Levels/Octane/T211_Inferno_Island/Polish/Alien_Plant_01.igz', 'models/Levels/Octane/T211_Inferno_Island/Polish/T211_Alien_Bush_02.igz', 'models/Levels/Octane/T211_Inferno_Island/Polish/T211_Alien_Fern_01.igz', 'models/Levels/Octane/T211_Inferno_Island/Polish/T211_Alien_Plant_03.igz']},
            'hut': {'label': '🛖 Huttes, masques et poteries', 'pak': 't212_jungle_boogie.pak', 'scale': (1.0, 1.0), 'spacing': 18.0,
                    'models': ['models/Levels/Octane/T212_Jungle_Boogie/T212_Jungle_Boogie_Hut.igz', 'models/Levels/Octane/T212_Jungle_Boogie/T212_Jungle_Boogie_Post.igz']},
            'pillar': {'label': '🏛 Piliers et pierres', 'pak': 't212_jungle_boogie.pak', 'scale': (0.9, 1.1), 'spacing': 25.0,
                    'models': ['models/Levels/Octane/T212_Jungle_Boogie/T212_Boogie_Rock_Stack_1.igz', 'models/Levels/Octane/T212_Jungle_Boogie/T212_Boogie_Rock_Stack_2.igz', 'models/Levels/Octane/T212_Jungle_Boogie/T212_Boogie_Rock_Stack_3.igz', 'models/Levels/Octane/T212_Jungle_Boogie/T212_Boogie_Rock_Stack_4.igz', 'models/Levels/Octane/T212_Jungle_Boogie/T212_Jungle_Boogie_Pyramid_01.igz']},
        },
    },
})


# ---- objets ajoutes le 2026-11-05 (bibliotheque du jeu : modeles 3D, pas de plans 2D) ----
# AJOUTES EN FIN de famille : les objets deja semes gardent leur numero de modele
def _add(kit, kind, models, **fam):
    """Ajoute des modeles a la famille kind du theme kit (creee avec fam si absente)."""
    props = KITS[kit].setdefault('props', {})
    if kind not in props:
        props[kind] = {'pak': KITS[kit]['pak'], 'scale': (1.0, 1.0), 'spacing': 10.0, 'models': [], **fam}
    have = {m.lower() for m in props[kind]['models']}
    props[kind]['models'] += [m for m in models if m.lower() not in have]


_BIG = dict(scale=(0.7, 1.0), spacing=45.0, big=True)
# palmiers (Crash 1, Skull Rock) et grands palmiers d'Inferno Island (35 a 52 m)
_add('sable', 'palm', _m('Crash1/jungle', 'C1_PalmTreeShort01', 'C1_PalmTreeShort02', 'C1_PalmTreeTall01', 'C1_PalmCluster02',
                         'A115_PalmTree'))
_add('sable', 'bush', _m('SpeedTrees', 'Shrub_Palm_02', 'Shrub_Palm_03'), label='🌿 Buissons de palmes', scale=(0.8, 1.2), spacing=8.0)
_add('volcan', 'palm', _m('Octane/T211_Inferno_Island/Polish', *[f'T211_Palm_Tree_0{i}' for i in range(2, 9)]))
_add('volcan', 'bush', _m('Octane/T211_Inferno_Island/T211_NewPlants', 'T211_Bush01', 'T211_Bush02', 'T211_Bush03',
                          'T211_FernPink_A', 'FernAlien_01') + _m('Octane/T211_Inferno_Island/Polish', 'T211_Alien_Fern_02'),
     label='🌿 Buissons et fougères', scale=(0.8, 1.2), spacing=7.0)
_add('volcan', 'big', _m('Octane/T211_Inferno_Island', 'T211_Inferno_TikiGorillaA', 'T211_Inferno_TikiGorillaC')
     + _m('Octane/T211_Inferno_Island/Polish', 'T211_Alien_Bush_05'), label='⛰ Gorilles tiki et buisson géant (fond)', **_BIG)
# grands arbres de la jungle (Crash 1 et 2), buissons
_add('boogie', 'tree', _m('Crash1/jungle', 'C1_CanopyTree01', 'C1_CanopyTree02', 'C1_CanopyTree02B') + _m('Crash2/Global', 'C2_BonusTree01'))
_add('boogie', 'bush', _m('Octane/T213_Tiny_Temple', 'T213_Bush01') + _m('Crash1/jungle', 'C1_Bush02')
     + _m('Octane/A115_Skull_Rock', 'A115_Foliage_04_plant', 'A115_Foliage_03_fern02'),
     label='🌿 Buissons et fougères', scale=(0.8, 1.2), spacing=8.0)
_add('boogie', 'big', _m('Octane/T113_Mystery_Caves/T113_Mystery_Caves_assets', 'T113_Mystery_Cave_Tree'),
     label='⛰ Arbre géant (fond)', **_BIG)
_add('parc', 'big', _m('Octane/T131_Coco_Park', 'T131_TreeTrunk_01_NX', 'T131_BigFlowerLeaves_A_01'),
     label='⛰ Tronc et feuilles géants (fond)', **_BIG)
_add('canyon', 'cactus', _m('Crash3/Desert', 'C3_Cactus_01', 'C3_Cactus_02', 'C3_Cactus_03', 'C3_Cactus_04', 'C3_Cactus_05'))
_add('neige', 'pine', _m('Crash2/Snow', 'C2_Pine_Tree02', 'T143_Birch_Tree02'))
# gros objets de fond (falaises, arbre de glace, tours...)
_add('banquise', 'big', _m('Octane/T143_Polar_Pass', 'T143_IceTree_01', 'T143_Polar_Pass_CliffLarge_01_Ice',
                           'T143_Polar_Pass_CliffLarge_02', 'T143_Polar_Pass_CliffModuleG_01', 'T143_Polar_Pass_CliffModuleI_01'))
_add('gorge', 'big', _m('Octane/T221_Meteor_Gorge', 'T221_Cliff_04'))
_add('temps', 'big', _m('Octane/T231_Out_of_Time', 'T_231_Cliff_03', 'T_231_Cliff_04'))
_add('orage', 'big', _m('Octane/T233_Thunder_Struck', 'T233_Cliff_05'))
_add('futur', 'big', _m('Crash3/Future', 'C3_Future_Tower04', 'C3_Future_Tower05'))
_add('mines', 'big', _m('Octane/T142_Dragon_Mines', 'T142_Dragon_Mines_Pillar_01', 'T142_Dragon_Mines_Pillar_02'),
     label='⛰ Piliers de la mine (fond)', **_BIG)
_add('tubes', 'big', _m('Crash3/Sea', 'C3_Sea_RockWall02'))
_add('jungle', 'big', _m('Octane/T132_Tiger_Temple', 'T132_Tiger_Temple_JungleCliffWall'))
_add('pyramide', 'big', _m('Octane/T133_Papus_Pyramid/Papus_Pyramid_Assets', 'Papus_Pyramid_cliff04', 'Papus_Pyramid_cliff08'))
# objets d'autres maps (2026-11-07) : toujours ajoutes en dernier, voir track_creator_extra.py
for _kit, _kind, _models in _EXTRA:
    _add(_kit, _kind, _models, **(dict(label=_EXTRA_LABELS['big'], **_BIG) if _kind == 'big' else
                                  dict(label=_EXTRA_LABELS.get(_kind, _kind), scale=(0.8, 1.2), spacing=10.0)))


def hidden_models(kit, kind):
    """Numeros des modeles de la famille masques de la liste (vignette grise ou vide)."""
    return [m for m, model in enumerate(KITS[kit]['props'][kind]['models']) if model in HIDDEN_MODELS]


def _catmull(P, closed, step):
    """Ligne (n, k) -> points espaces d'environ `step` (colonne 0..2 = position) par Catmull-Rom, puis
    reechantillonnage a pas constant (largeur et hauteur interpolees avec)."""
    P = np.asarray(P, np.float64)
    n = len(P)
    if n < 2:
        return P
    seg = n if closed else n - 1
    out = []
    for i in range(seg):
        p0 = P[(i - 1) % n] if closed or i > 0 else P[0]
        p1, p2 = P[i], P[(i + 1) % n]
        p3 = P[(i + 2) % n] if closed or i + 2 < n else P[-1]
        d = np.linalg.norm(p2[:3] - p1[:3])
        k = max(1, int(math.ceil(d / (step / 2))))
        for t in np.arange(k) / k:
            t2, t3 = t * t, t * t * t
            out.append(0.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3))
    if not closed:
        out.append(P[-1])
    Q = np.asarray(out)
    # pas constant le long de la courbe
    ds = np.linalg.norm(np.diff(np.vstack([Q, Q[:1]]) if closed else Q, axis=0)[:, :2], axis=1)
    s = np.concatenate([[0], np.cumsum(ds)])
    total = s[-1]
    if closed:
        Q = np.vstack([Q, Q[:1]])
    m = max(3, int(round(total / step)))
    t = np.linspace(0, total, m, endpoint=not closed)
    R = np.stack([np.interp(t, s, Q[:, j]) for j in range(Q.shape[1])], 1)
    return R


def _smooth(v, sigma, closed):
    """Lissage gaussien d'une colonne echantillonnee tous les STEP m (boucle : circulaire)."""
    k = int(math.ceil(3 * sigma / STEP))
    if k < 1 or len(v) < 3:
        return v
    w = np.exp(-0.5 * (np.arange(-k, k + 1) * STEP / sigma) ** 2)
    w /= w.sum()
    pad = np.concatenate([v[-k:], v, v[:k]]) if closed else np.concatenate([np.full(k, v[0]), v, np.full(k, v[-1])])
    return np.convolve(pad, w, mode='valid')


def _edge_cols(p):
    """Point du paveur -> [x, y, z, largeur, saut, demi-largeur gauche, droite, relevement du bord gauche, droit, sans talus]
    (bords edites dans l'onglet Creation ; par defaut route symetrique et a plat, avec talus)."""
    p = list(p) + [14.0 * INCH, 0.0][len(p) - 3:] if len(p) < 5 else list(p)
    w = p[3]
    d = [w / 2, w / 2, 0.0, 0.0]
    return p[:5] + [float(v) if v is not None else d[k] for k, v in enumerate((p[5:9] + [None] * 4)[:4])] \
        + [1.0 if len(p) > 9 and p[9] else 0.0]


def centerline(points_in, closed):
    """Points du paveur (pouces, [x, y, z, largeur, saut, (demi-largeur gauche, droite, relevement gauche, droit)])
    -> ligne lissee (metres, colonnes x, y, z, largeur, saut, devers, sans talus) : centre et largeur reels de la route
    (bords edites), devers = hauteur du bord gauche au-dessus du centre (le droit est autant en dessous)."""
    P = np.asarray([_edge_cols(p) for p in points_in], np.float64)
    P[:, :4] /= INCH                                          # colonne 4 : saut (0 / 1), sans unite
    P[:, 5:9] /= INCH                                         # colonne 9 : sans talus (0 / 1), sans unite
    if closed and len(P) > 2 and np.linalg.norm(P[0, :2] - P[-1, :2]) < 0.5:
        P = P[:-1]
    C = _catmull(P, closed, STEP)
    C[:, 4] = (C[:, 4] > 0.5).astype(np.float64)
    C[:, 2] = _smooth(C[:, 2], Z_SMOOTH, closed)            # hauteur : pas de crete ni de creux brusque
    # tremplin : la route se releve de KICK_H sur les KICK_LEN m avant chaque saut
    gap = C[:, 4] > 0.5
    starts = np.nonzero(gap & ~np.roll(gap, 1))[0] if closed else np.nonzero(gap & ~np.concatenate([[False], gap[:-1]]))[0]
    n = len(C)
    for s0 in starts:
        for k in range(1, int(KICK_LEN / STEP) + 1):
            i = (s0 - k) % n if closed else s0 - k
            if i < 0 or gap[i]:
                break
            C[i, 2] += KICK_H * (1 - (k - 1) / (KICK_LEN / STEP))
    # bords edites : le centre se decale vers le cote elargi, le devers vient de la difference de relevement
    _, L = _frames(C, closed)
    wl, wr, hl, hr = C[:, 5], C[:, 6], C[:, 7], C[:, 8]
    out = np.column_stack([C[:, :6], C[:, 9] > 0.5])
    out[:, :2] += L * ((wl - wr) / 2)[:, None]
    out[:, 2] += (hl + hr) / 2
    out[:, 3] = wl + wr
    out[:, 5] = (hl - hr) / 2
    return out


def _frames(C, closed):
    """Tangentes horizontales et normales laterales (gauche) de la ligne C."""
    nxt = np.roll(C[:, :2], -1, 0) if closed else np.vstack([C[1:, :2], 2 * C[-1:, :2] - C[-2:-1, :2]])
    prv = np.roll(C[:, :2], 1, 0) if closed else np.vstack([2 * C[:1, :2] - C[1:2, :2], C[:-1, :2]])
    T = nxt - prv
    T /= np.maximum(np.linalg.norm(T, axis=1, keepdims=True), 1e-9)
    L = np.stack([-T[:, 1], T[:, 0]], 1)
    return T, L


UNFOLD_WIN = 40                  # echantillons : longueur maximale d'un repli du bord de route recherche

def _unfold(edge, T):
    """Bord de route sans repli : dans un virage plus serre que la demi-largeur, le bord interieur reviendrait en
    arriere et la route se repasserait dessus (bout de route qui depasse dans l'herbe). Un point de bord qui recule
    par rapport a la tangente est ecarte : ces points sont repartis en ligne droite, position et hauteur, entre les deux
    points valides qui les encadrent (ni pincement vertical ni falaise dans un virage releve). D'abord, chaque boucle (le
    bord se recoupe a moins de UNFOLD_WIN echantillons) est ramenee a son point de croisement."""
    out = edge.copy()
    P = out[:, :2]
    Z = out[:, 2]
    n = len(P)
    i = 0
    while i < n - 2:
        a, b = P[i], P[i + 1]
        hit = None
        for j in range(min(n - 2, i + UNFOLD_WIN), i + 1, -1):          # croisement le plus loin : toute la boucle
            c, d = P[j], P[j + 1]
            r, s = b - a, d - c
            den = r[0] * s[1] - r[1] * s[0]
            if abs(den) < 1e-12:
                continue
            t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / den
            u = ((c[0] - a[0]) * r[1] - (c[1] - a[1]) * r[0]) / den
            if 0 < t < 1 and 0 < u < 1:
                hit = (j, a + t * r, Z[i] + t * (Z[i + 1] - Z[i]))
                break
        if hit:
            j, x, z = hit
            P[i + 1:j + 1] = x
            Z[i + 1:j + 1] = z
            i = j
        i += 1
    last = 0
    for i in range(1, len(out)):
        if np.dot(out[i, :2] - out[last, :2], T[i]) > 0.05:
            if i - last > 1:                                 # points ecartes : repartis sur le segment (position et hauteur)
                w = (np.arange(last + 1, i) - last)[:, None] / (i - last)
                out[last + 1:i] = out[last] + (out[i] - out[last]) * w
            last = i
    out[last + 1:] = out[last]                               # fin de trace ouvert : rien apres pour raccorder
    return out


class _Obj:
    def __init__(self):
        self.v, self.vt, self.f = [], [], []

    def obj(self, name, mtl):
        self.f.append(f'o {name}\nusemtl {mtl}')

    def vert(self, p, uv):
        self.v.append(p)
        self.vt.append(uv)
        return len(self.v)

    def quad(self, a, b, c, d):        # a b c d dans le sens trigonometrique vu de dessus (normale vers le haut)
        self.f.append(f'f {a}/{a} {b}/{b} {c}/{c}')
        self.f.append(f'f {a}/{a} {c}/{c} {d}/{d}')

    def text(self, mtllib):
        out = io.StringIO()
        out.write(f'# CTR Track Editor - createur de pistes\nmtllib {mtllib}\n')
        for p in self.v:
            out.write(f'v {p[0]:.4f} {p[1]:.4f} {p[2]:.4f}\n')
        for t in self.vt:
            out.write(f'vt {t[0]:.5f} {t[1]:.5f}\n')
        out.write('\n'.join(self.f) + '\n')
        return out.getvalue()


def _terrain_grid(terrain, C, gz):
    """Grille du terrain (metres) limitee au trace + marge et aux zones sculptees / peintes :
    (xs, ys, H (ny, nx) hauteurs absolues, M (ny, nx) matieres)."""
    if terrain:
        n, cell = int(terrain['n']), terrain['cell'] / INCH
        x0, y0 = terrain['x0'] / INCH, terrain['y0'] / INCH
        h = np.asarray(terrain['h'], np.float64).reshape(n, n) / INCH        # [j, i]
        paint = np.asarray(terrain['paint'], np.int64).reshape(n, n)
    else:                                                    # rien de sculpte : sol plat de sable
        cell = GROUND_CELL
        lo = np.floor((C[:, :2].min(0) - GROUND_MARGIN) / cell) * cell
        n = int(np.ceil((C[:, :2].max(0) + GROUND_MARGIN - lo).max() / cell)) + 1
        x0, y0 = lo
        h, paint = np.zeros((n, n)), np.zeros((n, n), np.int64)
    if terrain and terrain.get('full'):                    # carre de base choisi dans l'editeur : genere en entier
        return x0 + np.arange(n) * cell, y0 + np.arange(n) * cell, gz + h, paint, cell
    # emprise : trace + marge, plus tout ce qui a ete sculpte ou peint
    lo, hi = C[:, :2].min(0) - GROUND_MARGIN, C[:, :2].max(0) + GROUND_MARGIN
    edited = np.argwhere((np.abs(h) > 1e-3) | (paint > 0))
    if len(edited):
        lo = np.minimum(lo, [x0 + edited[:, 1].min() * cell - cell, y0 + edited[:, 0].min() * cell - cell])
        hi = np.maximum(hi, [x0 + edited[:, 1].max() * cell + cell, y0 + edited[:, 0].max() * cell + cell])
    i0, j0 = max(0, int((lo[0] - x0) // cell)), max(0, int((lo[1] - y0) // cell))
    i1, j1 = min(n - 1, int(math.ceil((hi[0] - x0) / cell))), min(n - 1, int(math.ceil((hi[1] - y0) / cell)))
    xs, ys = x0 + np.arange(i0, i1 + 1) * cell, y0 + np.arange(j0, j1 + 1) * cell
    return xs, ys, gz + h[j0:j1 + 1, i0:i1 + 1], paint[j0:j1 + 1, i0:i1 + 1], cell


WINDOW, STRIDE = 30, 15          # morceaux de route (echantillons de STEP m) qui se chevauchent : 60 m tous les 30 m
BRIDGE_MIN = 2.5                 # m : route a plus de ca au-dessus du terrain = tablier de pont visible
SKIRT_MIN = 0.6                  # m : bord de route a plus de ca au-dessus du sol = flanc de roche jusqu'au sol
DECK = 1.2                       # m : epaisseur du tablier


ROOF_CLEAR = 8.0                 # m : relief a plus de ca au-dessus de la route = plafond (la route passe dessous)
ROOF_EDGE = 0.3                  # m : le plafond s'etend tant que le raccord a abaisse le sol de plus de ca
ROOF_REACH = 60.0                # m : ... et au plus a ca de la route qu'il couvre (pas le long des tranchees)
ROOF_THICK = 6.0                 # m : epaisseur de la dalle de terre qui relie les hauteurs au-dessus de la route
ROOF_KEEP, ROOF_KEEP_R = 12.0, 40.0   # m : au-dessus de la route, bande gardee jusqu'a ca sous le sommet a moins de ROOF_KEEP_R


def _roof_mask(xs, ys, H0, H, C, dig):
    """Tunnel (2026-11-11) : relief passe par-dessus la route avec le pinceau « Deplacer sur le cote » ou « Creuser sous
    la route » (masque dig ; sans lui, une tranchee profonde deviendrait un tunnel). Le raccord (_conform) abaisse le sol
    jusqu'a la route ; la ou, SUR la route marquee, le relief (H0) est au moins ROOF_CLEAR au-dessus de la route, il est
    garde au-dessus comme un plafond, etendu aux sommets voisins que le raccord a abaisses (parois du tunnel), a
    ROOF_REACH au plus et toujours a ROOF_CLEAR / 2 au moins au-dessus de la route couverte. creator.js roofMask idem.
    -> (masque (ny, nx) des sommets du plafond, ref (dessus de la route couverte), masque de la route) ou None."""
    low = H0 - H
    if dig is None or len(xs) < 2 or not (low >= ROOF_CLEAR).any():
        return None
    cell = xs[1] - xs[0]
    road = np.zeros(H.shape, bool)
    rz = np.full(H.shape, -np.inf)                       # dessus de la route (la plus haute) sous chaque sommet
    for x, y, z, w in C[:, :4]:
        r = w / 2
        a0, a1 = max(0, int((x - r - xs[0]) // cell)), min(len(xs) - 1, int((x + r - xs[0]) // cell) + 1)
        b0, b1 = max(0, int((y - r - ys[0]) // cell)), min(len(ys) - 1, int((y + r - ys[0]) // cell) + 1)
        if a1 < a0 or b1 < b0:
            continue
        X, Y = np.meshgrid(xs[a0:a1 + 1], ys[b0:b1 + 1])
        inside = np.hypot(X - x, Y - y) < r
        road[b0:b1 + 1, a0:a1 + 1] |= inside
        sub = rz[b0:b1 + 1, a0:a1 + 1]
        sub[inside] = np.maximum(sub[inside], z + ROAD_LIFT)
    free = H0 - rz                                       # hauteur libre mesuree depuis la ROUTE
    roof = road & (free >= ROOF_CLEAR) & dig
    if not roof.any():
        return None
    allowed = (low > ROOF_EDGE) & (~road | (free >= ROOF_CLEAR))

    def grow(m):                                         # maximum des 4 voisins (et de soi)
        g = m.copy()
        g[1:, :] = np.maximum(g[1:, :], m[:-1, :])
        g[:-1, :] = np.maximum(g[:-1, :], m[1:, :])
        g[:, 1:] = np.maximum(g[:, 1:], m[:, :-1])
        g[:, :-1] = np.maximum(g[:, :-1], m[:, 1:])
        return g
    ref = np.where(roof, rz, -np.inf)
    for _ in range(int(math.ceil(ROOF_REACH / cell))):
        r2 = grow(ref)
        d = roof | (grow(roof.astype(np.int8)).astype(bool) & allowed & (H0 >= r2 + ROOF_CLEAR / 2))
        if (d == roof).all():
            break
        ref = np.where(d & ~roof, r2, ref)
        roof = d
    return roof, ref, road


def _dig_mask(terrain, xs, ys):
    """Sommets « creuses sous la route » (outil Creuser de la Creation, terrain['dig'] 0 / 1 sur la grille complete),
    sur la grille coupee (xs, ys) ; None si rien de creuse."""
    if not terrain or not terrain.get('dig'):
        return None
    n, cell = int(terrain['n']), terrain['cell'] / INCH
    D = np.asarray(terrain['dig'], np.uint8).reshape(n, n) > 0
    if not D.any():
        return None
    i0 = int(round((xs[0] - terrain['x0'] / INCH) / cell))
    j0 = int(round((ys[0] - terrain['y0'] / INCH) / cell))
    return D[j0:j0 + len(ys), i0:i0 + len(xs)]


def _conform(xs, ys, H, C, closed, left, right, dig=None, slope=BLEND_SLOPE, sculpt=None):
    """Terrain raccorde a la route : juste sous sa surface reelle (left, right : ses bords, pinces dans les virages serres,
    releves dans les virages inclines), aplani une maille au-dela du bord a la hauteur de ce bord, puis pente douce jusqu'au
    relief (enterre la route quand le relief est plus haut : tranchee ; la soutient quand il est plus bas : remblai).
    Chaque passage de la route est traite a part (morceaux de WINDOW echantillons, seul celui qui contient la
    projection du point compte) et le terrain suit le passage le PLUS BAS : la ou la route repasse au-dessus d'elle-
    meme, le sol reste au niveau de la route du dessous et celle du dessus devient un pont.
    slope : largeur du talus par metre de denivele (reglage de l'editeur). sculpt : relief sculpte (m, memes dimensions que H) :
    la ou il y en a, le raccord se resserre, sinon il ecrasait le relief pose pres de la route."""
    X, Y = np.meshgrid(xs, ys)
    P = np.stack([X.ravel(), Y.ravel()], 1)
    h0 = H.ravel().copy()
    # part du raccord en pente : 1 sur le sol d'origine, 0 sur un relief sculpte d'au moins SCULPT_FULL m
    free = 1.0 - np.clip(np.abs(sculpt.ravel()) / SCULPT_FULL, 0.0, 1.0) if sculpt is not None else np.ones(len(h0))
    out = np.full(len(P), np.inf)
    n = len(C)
    cell = xs[1] - xs[0] if len(xs) > 1 else GROUND_CELL
    below = UNDER_ROAD + ROAD_LIFT                           # les bords portent deja ROAD_LIFT
    starts = range(0, n, STRIDE) if closed else range(0, max(1, n - WINDOW + STRIDE), STRIDE)
    sub = np.linspace(0, 1, 4, endpoint=False)[:, None]
    for st in starts:
        idx = (np.arange(st, st + WINDOW) % n) if closed else np.arange(st, min(n, st + WINDOW))
        if len(idx) < 3:
            continue
        seg = C[idx]
        lo_edge = 0 if (not closed and st == 0) else 2                     # projection hors du morceau : ignore
        hi_edge = len(idx) - 1 if (not closed and idx[-1] == n - 1) else len(idx) - 3
        # portee du raccord d'apres l'ecart de hauteur de CHAQUE sommet. Une portee fixe coupait le talus : falaise de 283 m a
        # cote d'une route a +300 m, absente de l'apercu
        e_z = np.concatenate([left[idx, 2], right[idx, 2]])
        gap_z = np.maximum(np.abs(h0 - e_z.min()), np.abs(h0 - e_z.max())) + below
        reach = seg[:, 3].max() / 2 + cell + np.maximum(BLEND_MIN, gap_z * slope * free) + STEP
        out_x = np.maximum(np.maximum(seg[:, 0].min() - P[:, 0], P[:, 0] - seg[:, 0].max()), 0.0)
        out_y = np.maximum(np.maximum(seg[:, 1].min() - P[:, 1], P[:, 1] - seg[:, 1].max()), 0.0)
        sel = np.nonzero(out_x * out_x + out_y * out_y < reach * reach)[0]
        if not len(sel):
            continue
        Q = P[sel]
        d = np.linalg.norm(Q[:, None, :] - seg[None, :, :2], axis=2)
        k = d.argmin(1)
        # sous un saut aussi : le sol suit la hauteur de la route (seule la route s'arrete, demande du 2026-11-05)
        ok = (k >= lo_edge) & (k <= hi_edge)
        # bords reels du morceau, points rapproches
        pairs = list(zip(idx[:-1], idx[1:]))
        if not pairs:
            continue
        a, b = np.array(pairs).T
        E = np.concatenate([e[a][:, None, :] + (e[b] - e[a])[:, None, :] * sub for e in (left, right)]).reshape(-1, 3)
        de = np.linalg.norm(Q[:, None, :] - E[None, :, :2], axis=2)
        near = de.argmin(1)
        dist, rz = de[np.arange(len(near)), near], E[near, 2]
        # sous la route : hauteur de sa surface (memes triangles que son maillage)
        inside = np.zeros(len(Q), bool)
        for t0, t1, t2 in ((right[a], right[b], left[b]), (right[a], left[b], left[a])):
            for A, B, D in zip(t0, t1, t2):
                lo, hi = np.minimum(np.minimum(A[:2], B[:2]), D[:2]), np.maximum(np.maximum(A[:2], B[:2]), D[:2])
                m = np.nonzero((Q[:, 0] >= lo[0]) & (Q[:, 0] <= hi[0]) & (Q[:, 1] >= lo[1]) & (Q[:, 1] <= hi[1]))[0]
                if not len(m):
                    continue
                den = (B[1] - D[1]) * (A[0] - D[0]) + (D[0] - B[0]) * (A[1] - D[1])
                if abs(den) < 1e-9:
                    continue
                w0 = ((B[1] - D[1]) * (Q[m, 0] - D[0]) + (D[0] - B[0]) * (Q[m, 1] - D[1])) / den
                w1 = ((D[1] - A[1]) * (Q[m, 0] - D[0]) + (A[0] - D[0]) * (Q[m, 1] - D[1])) / den
                w2 = 1 - w0 - w1
                hit = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
                z = w0 * A[2] + w1 * B[2] + w2 * D[2]
                u = m[hit]
                first = ~inside[u]
                rz[u] = np.where(first, z[hit], np.minimum(rz[u], z[hit]))
                inside[u] = True
        dist = np.where(inside, 0.0, dist)
        rz = rz - below
        blend = np.maximum(BLEND_MIN, np.abs(rz - h0[sel]) * slope * free[sel])
        ok &= dist <= cell + blend
        # sans talus : le sol ne monte pas vers la route (pont) ; sous le relief, la tranchee reste necessaire
        flag = np.repeat(C[a, 6] > 0.5, len(sub))
        ok &= ~(np.concatenate([flag, flag])[near] & (rz > h0[sel]))
        t = np.clip((dist - cell) / blend, 0.0, 1.0)
        s = t * t * (3 - 2 * t)
        v = np.where(dist <= cell, rz, rz * (1 - s) + h0[sel] * s)
        cur = out[sel[ok]]
        out[sel[ok]] = np.minimum(cur, v[ok])
    out = np.where(np.isfinite(out), out, h0)
    if dig is not None and dig.shape == H.shape:         # creuse sous la route : relief sculpte garde (route en pont)
        out = np.where(dig.ravel(), h0, out)
    return out.reshape(H.shape)


ROAD_CLEAR = 0.25                # m : le terrain reste au moins a cette distance sous la surface de la route
CLEAR_STEP = 1.0                 # m : pas des points de controle sur la route
CLEAR_PASSES = 8


ROAD_STRIP = 4.0                 # m : largeur maximale d'une bande de triangles de la route


def road_strips(C):
    """Nombre de bandes de la route dans sa largeur (le meme sur tout le trace)."""
    return max(1, int(math.ceil(float(C[:, 3].max()) / ROAD_STRIP)))


def _road_samples(left, right, rows, gap, ns=1):
    """Points de la surface de la route (x, y, z), tous les CLEAR_STEP m environ, sauts exclus (ns : bandes, voir
    build)."""
    out = []
    for k in range(len(rows) - 1):
        i, j = rows[k], rows[k + 1]
        if gap[i] or gap[j]:
            continue
        for q in range(ns):
            f0, f1 = q / ns, (q + 1) / ns
            b0, a0 = right[i] + (left[i] - right[i]) * f0, right[i] + (left[i] - right[i]) * f1
            b1, a1 = right[j] + (left[j] - right[j]) * f0, right[j] + (left[j] - right[j]) * f1
            na = max(1, int(max(np.linalg.norm((a0 - b0)[:2]), np.linalg.norm((a1 - b1)[:2])) / CLEAR_STEP))
            nb = max(1, int(max(np.linalg.norm((a1 - a0)[:2]), np.linalg.norm((b1 - b0)[:2])) / CLEAR_STEP))
            for v in np.linspace(0, 1, nb + 1):
                for u in np.linspace(0, 1, na + 1):
                    # memes triangles que le quad de la bande (r0, r1, l1, l0)
                    if u <= v:
                        p = b0 + (b1 - b0) * v + (a1 - b1) * u
                    else:
                        p = b0 + (a0 - b0) * u + (a1 - a0) * v
                    out.append(p)
    return np.asarray(out) if out else np.zeros((0, 3))


def _mesh_heights(xs, ys, H, S):
    """Cases et hauteurs du terrain aux points S, sur les memes triangles que le maillage (voir _mesh_height)."""
    fx, fy = (S[:, 0] - xs[0]) / (xs[1] - xs[0]), (S[:, 1] - ys[0]) / (ys[1] - ys[0])
    i, j = np.clip(fx.astype(np.int64), 0, len(xs) - 2), np.clip(fy.astype(np.int64), 0, len(ys) - 2)
    u, v = np.clip(fx - i, 0, 1), np.clip(fy - j, 0, 1)
    a, b, c, d = H[j, i], H[j, i + 1], H[j + 1, i + 1], H[j + 1, i]
    return i, j, u, v, np.where(u >= v, a + u * (b - a) + v * (c - b), a + u * (c - d) + v * (d - a))


def _clear_road(xs, ys, H, left, right, rows, gap, ns=1):
    """La grille du terrain (8 m) ne suit pas une route dont la hauteur change vite (virage releve) : entre deux sommets
    sa surface passerait au-dessus de la route. Partout ou c'est le cas, les sommets de la case sont abaisses juste ce
    qu'il faut. -> (terrain, nombre de points de route qui etaient recouverts)."""
    S = _road_samples(left, right, rows, gap, ns)
    inside = (S[:, 0] >= xs[0]) & (S[:, 0] <= xs[-1]) & (S[:, 1] >= ys[0]) & (S[:, 1] <= ys[-1])
    S = S[inside]
    H = H.copy()
    first = 0
    for p in range(CLEAR_PASSES):
        if not len(S):
            break
        i, j, u, v, z = _mesh_heights(xs, ys, H, S)
        over = z - (S[:, 2] - ROAD_CLEAR)
        bad = over > 1e-3
        if p == 0:
            first = int(np.count_nonzero(bad))
        if not bad.any():
            break
        low = np.zeros_like(H)                               # abaissement voulu par sommet : le plus grand demande
        for jj, ii in ((j, i), (j, i + 1), (j + 1, i + 1), (j + 1, i)):
            np.maximum.at(low, (jj[bad], ii[bad]), over[bad])
        H -= low
    return H, first


def _height(xs, ys, H, x, y):
    """Hauteur du terrain (grille) au point (x, y), interpolee."""
    fx = np.clip((x - xs[0]) / (xs[1] - xs[0]), 0, len(xs) - 1.001)
    fy = np.clip((y - ys[0]) / (ys[1] - ys[0]), 0, len(ys) - 1.001)
    i, j = int(fx), int(fy)
    u, v = fx - i, fy - j
    return (H[j, i] * (1 - u) + H[j, i + 1] * u) * (1 - v) + (H[j + 1, i] * (1 - u) + H[j + 1, i + 1] * u) * v


WALL_SURFACE = 4                 # « Sol (defaut) » : surface des murs de Crash Cove


def _far_cells(xs, ys, C, reach):
    """Cases du terrain dont le centre est a plus de `reach` m de la route (booleens (ny, nx)) : ni sol ni collision, objets
    semes dessus ecartes (prop_seat)."""
    cx, cy = (xs[:-1] + xs[1:]) / 2, (ys[:-1] + ys[1:]) / 2
    P = C[::2, :2]
    far = np.ones((len(cy), len(cx)), bool)
    for j, y in enumerate(cy):
        near = P[np.abs(P[:, 1] - y) <= reach]
        if len(near):
            far[j] = ((cx[:, None] - near[:, 0][None, :]) ** 2 + (y - near[:, 1][None, :]) ** 2).min(1) > reach * reach
    return far


def _hole_cells(xs, ys, C):
    """Cases du terrain retirees sous les sauts (bord de route + HOLE_MARGIN) : un kart qui rate le saut tombe
    jusqu'au plancher de chute et reapparait."""
    G = C[C[:, 4] > 0.5]
    cx, cy = (xs[:-1] + xs[1:]) / 2, (ys[:-1] + ys[1:]) / 2
    X, Y = np.meshgrid(cx, cy)
    P = np.stack([X.ravel(), Y.ravel()], 1)
    d = np.full(len(P), np.inf)
    reach = np.full(len(P), 0.0)
    for a in range(0, len(G), 256):
        D = np.linalg.norm(P[:, None, :] - G[None, a:a + 256, :2], axis=2)
        k = D.argmin(1)
        better = D[np.arange(len(k)), k] < d
        d = np.where(better, D[np.arange(len(k)), k], d)
        reach = np.where(better, G[a + k, 3] / 2 + HOLE_MARGIN, reach)
    return (d <= reach).reshape(X.shape)


def _barriers(ob, C, L, left, right, rows, gap, closed, mode):
    """Barrieres (WALL_H m de haut, WALL_T d'epaisseur, a WALL_GAP du bord), collision « mur ». 'curves' : cote
    exterieur des virages de rayon < CURVE_R, prolongees de CURVE_EXTEND echantillons. -> nb d'echantillons murés."""
    if mode not in ('curves', 'all'):
        return 0
    n = len(C)
    T = np.stack([L[:, 1], -L[:, 0]], 1)                     # tangente (L = gauche)
    turn = np.arctan2(np.cross(np.roll(T, 1, 0), np.roll(T, -1, 0)), (np.roll(T, 1, 0) * np.roll(T, -1, 0)).sum(1))
    if not closed:
        turn[0] = turn[-1] = 0.0
    radius = 2 * STEP / np.maximum(np.abs(turn), 1e-6)
    want = {+1: np.zeros(n, bool), -1: np.zeros(n, bool)}   # +1 : bord gauche, -1 : bord droit
    if mode == 'all':
        want[1][:] = want[-1][:] = True
    else:
        for side in (1, -1):
            # virage a gauche (turn > 0) : exterieur = bord droit
            core = (radius < CURVE_R) & (np.sign(turn) == -side)
            idx = np.nonzero(core)[0]
            for e in range(-CURVE_EXTEND, CURVE_EXTEND + 1):
                j = (idx + e) % n if closed else np.clip(idx + e, 0, n - 1)
                want[side][j] = True
    for side in (1, -1):
        want[side] &= ~gap
    count = 0
    if not (want[1].any() or want[-1].any()):
        return 0
    ob.obj('CreatorWall', 'Wall')
    for side, edge in ((1, left), (-1, right)):
        w = want[side]
        for k in range(len(rows) - 1):
            i, j = rows[k], rows[k + 1]
            if not (w[i] and w[j]):
                continue
            count += 1
            o_i, o_j = side * L[i] * WALL_GAP, side * L[j] * WALL_GAP
            t_i, t_j = side * L[i] * (WALL_GAP + WALL_T), side * L[j] * (WALL_GAP + WALL_T)
            a0 = np.array([edge[i, 0] + o_i[0], edge[i, 1] + o_i[1], edge[i, 2]])
            a1 = np.array([edge[j, 0] + o_j[0], edge[j, 1] + o_j[1], edge[j, 2]])
            b0 = np.array([edge[i, 0] + t_i[0], edge[i, 1] + t_i[1], edge[i, 2]])
            b1 = np.array([edge[j, 0] + t_j[0], edge[j, 1] + t_j[1], edge[j, 2]])
            up = np.array([0, 0, WALL_H])
            v = lambda p, u, w_: ob.vert(p, (u, w_))
            # face cote route, dessus, face exterieure
            faces = [(a0, a1, a1 + up, a0 + up), (a0 + up, a1 + up, b1 + up, b0 + up), (b1, b0, b0 + up, b1 + up)]
            for q in faces:                                      # deux sens : visible de partout (pas de face cachee)
                for qq in (q, q[::-1]):
                    ob.quad(v(qq[0], 0, 0), v(qq[1], 1, 0), v(qq[2], 1, 0.2), v(qq[3], 0, 0.2))
    return count


WATER_DEEP = 1.5        # m : plus d'eau que ca -> zone de chute (reapparition) ; moins : on roule au fond
WATER_DZ = -5.0         # m (0,3 puis 1 avant, le 2026-11-12 ; creator.js idem) : niveau par defaut sous le bord le plus bas du creux
WATER_REPEAT = 24.0     # m : repetition de la texture d'eau
WATER_FALL_TILE = 40.0  # m : zones de chute de l'eau profonde, en carreaux (reapparition proche de l'endroit de la chute)
# types d'eau (2026-11-12 ; creator.js WATER_TYPES) : couleur de base (r, g, b) et ecart des ondulations. Matiere « Water »
# pour l'eau claire (anciens brouillons), « Water_<type> » sinon ; image water.png / water_<type>.png
WATER_TYPES = {'clear': ((0.10, 0.42, 0.62), (0.10, 0.16, 0.20)), 'lagoon': ((0.08, 0.55, 0.58), (0.10, 0.18, 0.14)),
               'swamp': ((0.22, 0.30, 0.13), (0.08, 0.10, 0.05)), 'dark': ((0.06, 0.16, 0.27), (0.05, 0.08, 0.12)),
               'mud': ((0.36, 0.26, 0.16), (0.08, 0.06, 0.04))}


def water_kind(w):
    return w.get('type') if isinstance(w, dict) and w.get('type') in WATER_TYPES else 'clear'


def water_material(kind):
    return 'Water' if kind == 'clear' else f'Water_{kind}'


def water_png(kind):
    return 'water.png' if kind == 'clear' else f'water_{kind}.png'


def paint_mask(terrain, xs, ys, verts):
    """Sommets peints (indices sur la grille complete du terrain) -> masque sur la grille coupee (xs, ys)."""
    n, cell = int(terrain['n']), terrain['cell'] / INCH
    i0 = int(round((xs[0] - terrain['x0'] / INCH) / cell))
    j0 = int(round((ys[0] - terrain['y0'] / INCH) / cell))
    mask = np.zeros((len(ys), len(xs)), bool)
    for v in verts or []:
        v = int(v)
        j, i = v // n - j0, v % n - i0
        if 0 <= j < len(ys) and 0 <= i < len(xs):
            mask[j, i] = True
    return mask


def water_basin(xs, ys, H, x, y, dz, road_z=None):
    """Creux du sol au point (x, y) (metres) rempli jusqu'a son bord le plus bas + dz (m) : (niveau, masque des sommets
    sous l'eau [ny, nx]) ou None. Meme calcul que creator.js waterBasin : descente au fond, inondation par le bas (les
    petits creux de la pente sont remplis aussi, 2026-11-12) jusqu'au bord du terrain ou a la route posee au sol
    (road_z : dessus de la route sous chaque sommet, -inf sans route), puis sommets relies sous le niveau."""
    import heapq
    ny, nx = H.shape
    a = int(np.argmin(np.abs(xs - x)))
    b = int(np.argmin(np.abs(ys - y)))
    if not (0 < a < nx - 1 and 0 < b < ny - 1):
        return None
    for _ in range(4 * max(nx, ny)):                     # point sur la pente : on descend au fond
        best = (b, a)
        for nb, na in ((b, a - 1), (b, a + 1), (b - 1, a), (b + 1, a)):
            if H[nb, na] < H[best]:
                best = (nb, na)
        if best == (b, a):
            break
        b, a = best
        if not (0 < a < nx - 1 and 0 < b < ny - 1):
            return None
    seen = np.zeros(H.shape, bool)
    level, spill = float(H[b, a]), None
    heap = [(level, b, a)]
    seen[b, a] = True
    while heap:
        h, vb, va = heapq.heappop(heap)
        level = max(level, h)
        if va in (0, nx - 1) or vb in (0, ny - 1):
            spill = level
            break
        if road_z is not None and -np.inf < road_z[vb, va] < h + 2.0:   # route au sol (pas un pont au-dessus)
            spill = level
            break
        for nb, na in ((vb, va - 1), (vb, va + 1), (vb - 1, va), (vb + 1, va)):
            if not seen[nb, na]:
                seen[nb, na] = True
                heapq.heappush(heap, (float(H[nb, na]), nb, na))
    L = (level if spill is None else spill) + dz
    if H[b, a] >= L:
        return None
    mask = np.zeros(H.shape, bool)
    mask[b, a] = True
    stack = [(b, a)]
    while stack:
        vb, va = stack.pop()
        for nb, na in ((vb, va - 1), (vb, va + 1), (vb - 1, va), (vb + 1, va)):
            if 0 <= nb < ny and 0 <= na < nx and not mask[nb, na] and H[nb, na] < L:
                mask[nb, na] = True
                stack.append((nb, na))
    return L, mask


def water_texture(size=512, kind='clear'):
    """Image d'eau (PNG) du type kind (WATER_TYPES) : ondulations douces, reflets, raccord sur les bords."""
    from PIL import Image
    import io
    u = np.linspace(0, 2 * np.pi, size, endpoint=False)
    X, Y = np.meshgrid(u, u)
    w = (np.sin(3 * X + 2 * Y) + 0.9 * np.sin(5 * Y - 4 * X + 1.3) + 0.8 * np.sin(2 * X - 6 * Y + 0.7)
         + 0.5 * np.sin(9 * X + 7 * Y + 0.4) + 0.45 * np.sin(11 * Y - 8 * X + 2.6) + 0.3 * np.sin(17 * X + 3 * Y + 1.1))
    w = (w - w.min()) / (w.max() - w.min())
    (r0, g0, b0), (dr, dg, db) = WATER_TYPES.get(kind, WATER_TYPES['clear'])
    r = r0 + dr * w
    g = g0 + dg * w
    bl = b0 + db * w
    hi = np.clip((w - 0.9) * 3, 0, 1) * (0.4 if kind == 'mud' else 1.0)   # reflets
    rgb = np.stack([r + 0.5 * hi, g + 0.4 * hi, bl + 0.3 * hi], -1)
    buf = io.BytesIO()
    Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8), 'RGB').save(buf, 'PNG')
    return buf.getvalue()


def _road_top(xs, ys, C):
    """Dessus de la route (la plus haute) sous chaque sommet de la grille (metres), -inf hors de la route."""
    cell = xs[1] - xs[0]
    rz = np.full((len(ys), len(xs)), -np.inf)
    for x, y, z, w in C[:, :4]:
        r = w / 2
        a0, a1 = max(0, int((x - r - xs[0]) // cell)), min(len(xs) - 1, int((x + r - xs[0]) // cell) + 1)
        b0, b1 = max(0, int((y - r - ys[0]) // cell)), min(len(ys) - 1, int((y + r - ys[0]) // cell) + 1)
        if a1 < a0 or b1 < b0:
            continue
        X, Y = np.meshgrid(xs[a0:a1 + 1], ys[b0:b1 + 1])
        inside = np.hypot(X - x, Y - y) < r
        sub = rz[b0:b1 + 1, a0:a1 + 1]
        sub[inside] = np.maximum(sub[inside], z + ROAD_LIFT)
    return rz


def _water(ob, xs, ys, H, waters, hole, terrain=None, C=None):
    """Surfaces d'eau (objets CreatorWaterNN, matiere du type d'eau, sans collision) et zones de chute de l'eau profonde.
    waters = [{x, y, dz, type}] (creux remplis) ou [{paint: 1, level, v: [sommets], type}] (eau peinte au pinceau,
    niveau absolu en pouces ; sous l'eau = sommets peints dont le sol est plus bas). -> (nb d'eaux, zones [{'center',
    'dims'} pouces], rapport, types utilises)."""
    count, zones, report, kinds = 0, [], [], set()
    nyc, nxc = len(ys) - 1, len(xs) - 1
    road_z = _road_top(xs, ys, C) if C is not None and len(xs) > 1 and any(not w.get('paint') for w in waters or []) else None
    for k, w in enumerate(waters or []):
        r = None
        try:
            if w.get('paint'):
                if terrain:
                    L = float(w['level']) / INCH
                    mask = paint_mask(terrain, xs, ys, w.get('v')) & (H < L)
                    r = (L, mask) if mask.any() else None
            else:
                r = water_basin(xs, ys, H, float(w['x']) / INCH, float(w['y']) / INCH, float(w.get('dz', WATER_DZ * INCH)) / INCH, road_z)
        except (KeyError, TypeError, ValueError):
            r = None
        if r is None:
            report.append(f'eau {k + 1} : ' + ('aucune zone peinte sous son niveau' if w.get('paint') else 'plus de creux à cet endroit'))
            continue
        L, mask = r
        cell = mask[:-1, :-1] | mask[1:, :-1] | mask[:-1, 1:] | mask[1:, 1:]
        cells = [(a, b) for b, a in np.argwhere(cell) if not hole[b, a]]
        # eau peinte : bord en biais (case a 3 coins = triangle, moins de 3 : rien ; creator.js idem)
        tris = []
        if w.get('paint'):
            full, tris = [], []
            for a, b in cells:
                q = [(a, b), (a + 1, b), (a + 1, b + 1), (a, b + 1)]
                inside = [mask[qb, qa] for qa, qb in q]
                if all(inside):
                    full.append((a, b))
                elif sum(inside) == 3:
                    tris.append([c for c, ok in zip(q, inside) if ok])
            cells = full
        if not cells and not tris:
            continue
        count += 1
        kind = water_kind(w)
        kinds.add(kind)
        ob.obj(f'CreatorWater{count:02d}', water_material(kind))
        vid = {}

        def v(a, b):
            if (a, b) not in vid:
                vid[(a, b)] = ob.vert((xs[a], ys[b], L), (xs[a] / WATER_REPEAT, ys[b] / WATER_REPEAT))
            return vid[(a, b)]
        for a, b in cells:
            ob.quad(v(a, b), v(a + 1, b), v(a + 1, b + 1), v(a, b + 1))
        for c3 in tris:                                  # coins dans le sens trigonometrique (ordre de la case)
            ob.f.append('f ' + ' '.join(f'{i}/{i}' for i in (v(*c) for c in c3)))
        # eau profonde : boites de chute de WATER_FALL_TILE m, dessus 1 m sous la surface, jusqu'au fond
        deep = mask & ((L - H) > WATER_DEEP)
        if deep.any():
            step = max(1, int(round(WATER_FALL_TILE / float(xs[1] - xs[0]))))
            for b0 in range(0, len(ys), step):
                for a0 in range(0, len(xs), step):
                    sub = deep[b0:b0 + step, a0:a0 + step]
                    if not sub.any():
                        continue
                    jj, ii = np.nonzero(sub)
                    half = float(xs[1] - xs[0]) / 2
                    x0, x1 = xs[a0 + ii.min()] - half, xs[a0 + ii.max()] + half
                    y0, y1 = ys[b0 + jj.min()] - half, ys[b0 + jj.max()] + half
                    top = L - 1.0
                    bot = float(H[b0:b0 + step, a0:a0 + step][sub].min()) - 1.0
                    zones.append({'center': [(x0 + x1) / 2 * INCH, (y0 + y1) / 2 * INCH, (top + bot) / 2 * INCH],
                                  'dims': [(x1 - x0) * INCH, (y1 - y0) * INCH, max(2.0, top - bot) * INCH]})
    return count, zones, report, kinds


def build(points_in, closed, ground_z, kit='sable', terrain=None, barriers='curves', waters=None):
    """-> (texte OBJ, texte MTL, infos {length, guide, exact (pouces), start, yaw, ground_tiles, min_z (pouces), ...}).
    barriers : 'none' | 'curves' (exterieur des virages serres) | 'all' (les deux bords partout, sauf sauts)."""
    K = KITS[kit]
    C = centerline(points_in, closed)
    if len(C) < 4:
        raise ValueError('tracé trop court')
    gz = ground_z / INCH
    xs, ys, H, M, cell = _terrain_grid(terrain, C, gz)
    T, L = _frames(C, closed)
    half = C[:, 3:4] / 2
    road_z = C[:, 2] + ROAD_LIFT
    left = _unfold(np.hstack([C[:, :2] + L * half, (road_z + C[:, 5])[:, None]]), T)      # devers : bords releves
    right = _unfold(np.hstack([C[:, :2] - L * half, (road_z - C[:, 5])[:, None]]), T)
    ds = np.linalg.norm(np.diff(C[:, :2], axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(ds)])
    if closed:
        s = np.append(s, s[-1] + np.linalg.norm(C[0, :2] - C[-1, :2]))
    ob = _Obj()
    rows = list(range(len(C))) + ([0] if closed else [])

    # route, en bandes de ROAD_STRIP m dans la largeur : un seul quad sur toute la largeur se pliait en diagonale dans
    # les virages en pente (rangees non paralleles) -> petites vagues qui faisaient sautiller le kart
    ob.obj('CreatorRoad', 'Road')
    ns = road_strips(C)
    ids = []
    for k, i in enumerate(rows):
        v = s[k] / K['road_repeat']
        ids.append([ob.vert(right[i] + (left[i] - right[i]) * (q / ns), (1.0 - q / ns, v)) for q in range(ns + 1)])
    gap = C[:, 4] > 0.5
    for k in range(len(ids) - 1):
        if gap[rows[k]] or gap[rows[k + 1]]:                  # saut : pas de route (trou)
            continue
        for q in range(ns):                                   # de droite (q = 0) a gauche
            ob.quad(ids[k][q], ids[k + 1][q], ids[k + 1][q + 1], ids[k][q + 1])

    # ligne de depart : damier au sol en travers de la route au depart (START_ROWS rangees de cases de START_CELL m),
    # juste au-dessus de la route, sans collision (on roule sur la route dessous)
    if not gap[0]:
        ob.obj('CreatorStartLine', 'StartLine')
        t3 = np.array([T[0, 0], T[0, 1], 0.0]) * (START_ROWS * START_CELL / 2)
        lift = np.array([0.0, 0.0, START_LIFT])
        w = float(np.linalg.norm(left[0, :2] - right[0, :2])) / (2 * START_CELL)      # repetitions (2 cases) en largeur
        v = START_ROWS / 2
        ob.quad(ob.vert(right[0] - t3 + lift, (0.0, 0.0)), ob.vert(right[0] + t3 + lift, (0.0, v)),
                ob.vert(left[0] + t3 + lift, (w, v)), ob.vert(left[0] - t3 + lift, (w, 0.0)))

    # terrain raccorde a la route, en carreaux de GROUND_TILE m et par matiere (matiere d'une case : la plus presente
    # a ses 4 coins)
    H0 = H.copy()                                        # relief (avant raccord) : plafond des tunnels
    dig = _dig_mask(terrain, xs, ys)
    H = _conform(xs, ys, H, C, closed, left, right, dig,
                 float((terrain or {}).get('blend') or BLEND_SLOPE), H - gz)
    H, _ = _clear_road(xs, ys, H, left, right, rows, gap, ns)
    RM = _roof_mask(xs, ys, H0, H, C, dig)
    roof = RM[0] if RM is not None else None
    span = None
    if roof is not None:
        # partie du pont de terre au-dessus de la route (sommets de la route et leurs 4 voisins) : DALLE avec le vide
        # dessous, sol au niveau de la route. Ailleurs (flancs des buttes reliees) : relief plein jusqu'au sol, sinon il
        # pendait en rideaux fins. creator.js refreshTerrainMesh / refreshRoof idem
        rd = RM[2]
        near = rd.copy()
        near[1:, :] |= rd[:-1, :]
        near[:-1, :] |= rd[1:, :]
        near[:, 1:] |= rd[:, :-1]
        near[:, :-1] |= rd[:, 1:]
        span = roof & near
        # au-dessus de la route, seule la partie haute de la bande reste (ROOF_KEEP sous son sommet local) : ses bords en
        # pente (flancs etires par le pinceau) pendaient en voiles jusque pres de la route. creator.js roofMask idem
        k = int(round(ROOF_KEEP_R / cell))
        drop = []
        for b, a in np.argwhere(span):
            win = span[max(0, b - k):b + k + 1, max(0, a - k):a + k + 1]
            peak = H0[max(0, b - k):b + k + 1, max(0, a - k):a + k + 1][win].max()
            if H0[b, a] < max(RM[1][b, a] + ROOF_CLEAR + ROOF_THICK, peak - ROOF_KEEP):
                drop.append((b, a))
        for b, a in drop:
            roof[b, a] = span[b, a] = False
        H = np.where(span, np.minimum(H, RM[1] - ROAD_LIFT - 0.25), H)
        # flancs des buttes reliees : rendus au relief, la bande et les buttes ne font qu'un bloc (2026-11-11)
        H = np.where(roof & ~span, H0, H)
    # sauts : seule la route s'arrete, le sol dessous reste (demande du 2026-11-05 ; avant : _hole_cells, trou jusqu'au
    # plancher de chute)
    hole = np.zeros((len(ys) - 1, len(xs) - 1), bool)
    trim = float((terrain or {}).get('trim_m') or 0)
    if trim > 0:                                         # carte loin de la route retiree (demande a la generation)
        hole = _far_cells(xs, ys, C, trim)
    MATS = paint_materials(kit)
    M = np.clip(M, 0, len(MATS) - 1)
    MIX0 = len(MATS)
    CM, mixes = _cell_materials(M, MIX0, (terrain or {}).get('fade', FADE_DEF))
    NAMES = [m[0] for m in MATS] + [_mix_name(*x) for x in mixes]
    per = max(1, int(round(GROUND_TILE / cell)))
    rep = K['ground_repeat']
    used = set()
    tile = 0
    for ta in range(0, len(xs) - 1, per):
        for tb in range(0, len(ys) - 1, per):
            ia, ib = ta, min(ta + per, len(xs) - 1)
            ja, jb = tb, min(tb + per, len(ys) - 1)
            if ib <= ia or jb <= ja:
                continue
            tile += 1
            for m in np.unique(CM[ja:jb, ia:ib]):         # matieres presentes dans le carreau seulement (100+ peintures)
                m = int(m)
                name = NAMES[m]
                cells = [(a, b) for b in range(ja, jb) for a in range(ia, ib) if CM[b, a] == m and not hole[b, a]]
                if not cells:
                    continue
                used.add(m)
                ob.obj(f'CreatorGround{tile:02d}_{name}', name)
                vid = {}

                def v(a, b):
                    if (a, b) not in vid:
                        vid[(a, b)] = ob.vert((xs[a], ys[b], H[b, a]), (xs[a] / rep, ys[b] / rep))
                    return vid[(a, b)]
                for a, b in cells:
                    ob.quad(v(a, b), v(a + 1, b), v(a + 1, b + 1), v(a, b + 1))

    # eau des creux (outil du Relief « Remplir d'eau », 2026-11-12) : surface plane au niveau, sans collision
    n_water, water_falls, water_rep, water_kinds = _water(ob, xs, ys, H, waters, hole, terrain, C)

    # ponts : la ou la route passe nettement au-dessus du terrain (au-dessus d'elle-meme), tablier en roche
    # (flancs de DECK m sous les bords et dessous) ; la collision n'est que la route
    g = np.array([_height(xs, ys, H, x, y) for x, y in C[:, :2]])
    high = ((road_z - g) > BRIDGE_MIN) & ~gap
    n_bridges = 0
    ring = rows if closed else list(range(len(C)))
    # jupe : bord de route qui surplombe le sol (virage releve, grille du terrain trop large pour le suivre) : flanc de
    # roche jusqu'au sol, pas de vide visible sous la route
    skirts = []
    for k in range(len(ring) - 1):
        i, j = ring[k], ring[k + 1]
        if gap[i] or gap[j] or high[i] or high[j]:
            continue
        for e0, e1 in ((left[i], left[j]), (right[j], right[i])):
            g0, g1 = _mesh_height(xs, ys, H, e0[0], e0[1]), _mesh_height(xs, ys, H, e1[0], e1[1])
            if max(e0[2] - g0, e1[2] - g1) > SKIRT_MIN:
                skirts.append((e0, e1, g0 - 0.5, g1 - 0.5))
    if high.any() or skirts:
        ob.obj('CreatorBridge', 'Bridge')
        for e0, e1, g0, g1 in skirts:
            b0, b1 = np.array([e0[0], e0[1], g0]), np.array([e1[0], e1[1], g1])
            ob.quad(ob.vert(b0, (0, 0)), ob.vert(b1, (1, 0)), ob.vert(e1, (1, 0.1)), ob.vert(e0, (0, 0.1)))
    if high.any():
        for k in range(len(ring) - 1):
            i, j = ring[k], ring[k + 1]
            if not (high[i] or high[j]):
                continue
            n_bridges += high[j] and not high[i]
            for e0, e1 in ((left[i], left[j]), (right[j], right[i])):        # flancs, face vers l'exterieur
                b0, b1 = e0 - [0, 0, DECK], e1 - [0, 0, DECK]
                ob.quad(ob.vert(b0, (0, 0)), ob.vert(b1, (1, 0)), ob.vert(e1, (1, 0.1)), ob.vert(e0, (0, 0.1)))
            bl0, bl1 = left[i] - [0, 0, DECK], left[j] - [0, 0, DECK]
            br0, br1 = right[i] - [0, 0, DECK], right[j] - [0, 0, DECK]
            ob.quad(ob.vert(bl0, (0, 0)), ob.vert(bl1, (1, 0)), ob.vert(br1, (1, 1)), ob.vert(br0, (0, 1)))   # dessous
        n_bridges = max(n_bridges, 1)

    # tunnels : terre gardee au-dessus de la route, en VOLUME FERME (2026-11-11 ; creator.js refreshRoof idem) :
    #   dessus = relief (H0) ; dessous = dalle de ROOF_THICK m (jamais a moins de ROOF_CLEAR au-dessus de la route), qui
    #   rejoint le sol la ou il remonte (buttes reliees) ; vide dessous jusqu'a la route ;
    #   parois sur tout le tour (aux entrees : facade, l'entree reste ouverte). Le jeu n'affiche que la face avant :
    #   dessus vers le haut, dessous vers le bas, parois dans les deux sens. Matiere du sol de la case.
    n_roof = 0
    if roof is not None:
        _, rref, rroad = RM
        nyc, nxc = len(ys) - 1, len(xs) - 1
        # cases du pont : 4 coins dans le plafond, un au moins au-dessus de la route (le reste = flancs, rendus au relief :
        # un seul bloc avec les buttes ; dessus de la bande dans le prolongement du sol)
        # ... un coin au-dessus de la route, les autres dans le pont OU sur du relief haut que la bande touche (pas abaisse
        # par le raccord, ROOF_CLEAR au moins au-dessus de la route) : la bande s'y soude sans trou (creator.js idem)
        rc_ = np.zeros((nyc, nxc), bool)
        for b, a in np.argwhere((span[:-1, :-1] | span[1:, :-1] | span[:-1, 1:] | span[1:, 1:]) & ~hole):
            q = ((b, a), (b, a + 1), (b + 1, a), (b + 1, a + 1))
            ref = max(rref[v] for v in q if span[v])
            rc_[b, a] = all(roof[v] or (H0[v] - H[v] <= ROOF_EDGE and H[v] >= ref + ROOF_CLEAR) for v in q)
        top_z = lambda a, b: H0[b, a] if roof[b, a] else H[b, a]

        def bot_z(a, b):
            # au-dessus de la route : DALLE de ROOF_THICK m sous le relief, jamais a moins de ROOF_CLEAR de la route
            # (l'utilisateur, 2026-11-11 : « je ne veux pas que ca descende jusqu'a la route, juste rejoindre deux parties
            # hautes ») ; sur les buttes, le dessous rejoint leur dessus (fusion)
            if not span[b, a]:
                return top_z(a, b)
            return min(H0[b, a] - 0.5, max(H0[b, a] - ROOF_THICK, H[b, a], rref[b, a] + ROOF_CLEAR))
        rcells = defaultdict(list)
        for b in range(nyc):
            for a in range(nxc):
                if rc_[b, a]:
                    rcells[int(CM[b, a])].append((a, b))
        for m, cells in rcells.items():
            used.add(m)
            ob.obj(f'CreatorRoof{m:02d}_{NAMES[m]}', NAMES[m])
            vt, vb = {}, {}

            def rv(a, b, d, f):
                if (a, b) not in d:
                    d[(a, b)] = ob.vert((xs[a], ys[b], f(a, b)), (xs[a] / rep, ys[b] / rep))
                return d[(a, b)]
            for a, b in cells:
                ob.quad(rv(a, b, vt, top_z), rv(a + 1, b, vt, top_z), rv(a + 1, b + 1, vt, top_z), rv(a, b + 1, vt, top_z))
                ob.quad(rv(a, b, vb, bot_z), rv(a, b + 1, vb, bot_z), rv(a + 1, b + 1, vb, bot_z), rv(a + 1, b, vb, bot_z))
                for da, db, (pa, pb), (qa, qb) in ((0, -1, (a, b), (a + 1, b)), (1, 0, (a + 1, b), (a + 1, b + 1)),
                                                    (0, 1, (a + 1, b + 1), (a, b + 1)), (-1, 0, (a, b + 1), (a, b))):
                    na, nb = a + da, b + db
                    if (0 <= na < nxc and 0 <= nb < nyc and rc_[nb, na]) or not (span[pb, pa] or span[qb, qa]):
                        continue                                 # pas de paroi entre deux sommets de butte (relief)
                    sl = float(np.hypot(xs[qa] - xs[pa], ys[qb] - ys[pb]))
                    w = (ob.vert((xs[pa], ys[pb], top_z(pa, pb)), (0, top_z(pa, pb) / rep)),
                         ob.vert((xs[qa], ys[qb], top_z(qa, qb)), (sl / rep, top_z(qa, qb) / rep)),
                         ob.vert((xs[qa], ys[qb], bot_z(qa, qb)), (sl / rep, bot_z(qa, qb) / rep)),
                         ob.vert((xs[pa], ys[pb], bot_z(pa, pb)), (0, bot_z(pa, pb) / rep)))
                    ob.quad(*w)
                    ob.quad(*w[::-1])
                n_roof += 1

    n_walls = _barriers(ob, C, L, left, right, rows, gap, closed, barriers)
    # fondus : images composees apres coup (mix_textures), leurs deux peintures doivent etre decodees
    mix_used = [x for i, x in enumerate(mixes) if MIX0 + i in used]
    base_used = {m for m in used if m < MIX0} | {m for x in mix_used for m in x[:2]}
    mtl ='newmtl Road\nKd 0.8 0.7 0.5\nmap_Kd road.png\n\n' + \
        ('newmtl StartLine\nKd 1 1 1\nmap_Kd checker.png\n\n' if not gap[0] else '') + ('newmtl Bridge\nKd 0.5 0.5 0.5\nmap_Kd rock.png\n\n' if n_bridges or skirts else '') + \
        ('newmtl Wall\nKd 0.5 0.5 0.5\nmap_Kd rock.png\n\n' if n_walls else '') + \
        ''.join(f'newmtl {water_material(k)}\nKd 0.2 0.5 0.75\nmap_Kd {water_png(k)}\n\n' for k in sorted(water_kinds)) + ''.join(
        f'newmtl {name}\nKd 0.8 0.7 0.5\nmap_Kd {png}\n\n' for m, (name, png, *_) in enumerate(MATS) if m in used) + ''.join(
        f'newmtl {_mix_name(*x)}\nKd 0.8 0.7 0.5\nmap_Kd {_mix_name(*x)}.png\n\n' for x in mix_used)
    yaw = math.atan2(T[0, 1], T[0, 0])
    guide = (C[::2, :2] * INCH).round(1).tolist()
    exact = np.hstack([C[:, :2], road_z[:, None], C[:, 3:4]]) * INCH      # route (surface), largeur
    exact = np.hstack([exact, gap[:, None].astype(np.float64)])            # + saut (en l'air)
    info = {'length': float(s[-1]), 'guide': guide, 'exact': exact.round(1).tolist(), 'start': (C[0, :3] * INCH).tolist(),
            'trimmed_pct': round(100 * float(hole.mean())) if trim > 0 else 0,
            'yaw': yaw, 'ground_tiles': tile, 'materials': [MATS[m][0] for m in sorted(base_used)],
            'mixes': [(_mix_name(*x), MATS[x[0]][1], MATS[x[1]][1], x[2]) for x in mix_used],
            # surface de collision d'un fondu : celle de la peinture dominante
            'mix_surfaces': {_mix_name(*x): MATS[x[1] if x[2] > 2 else x[0]][3] for x in mix_used},
            'bridges': int(n_bridges), 'tunnel_cells': int(n_roof), 'jumps': int(np.count_nonzero(gap & ~np.roll(gap, 1))), 'walls_m': round(n_walls * STEP),
            'min_z': float(min(H.min(), road_z.min())) * INCH,
            'waters': int(n_water), 'water_falls': water_falls, 'water_report': water_rep, 'water_kinds': sorted(water_kinds),
            '_ground': (xs, ys, H, hole, C, roof)}                     # sol genere (metres) : hauteur des objets semes
    return ob.text(MTL_NAME), mtl, info


PROP_SINK = 0.3                  # m : objet enfonce sous le point le plus bas de son emprise (base jamais visible)
PROP_CLEAR = 1.0                 # m : ecart minimal entre le pied d'un objet et le bord de la route
FOOT_SHARE, ROCK_FOOT = 0.3, 0.6  # part du rayon d'emprise occupee par le pied (tronc, base) ; rochers : plus massifs
BIG_FOOT = 0.9                   # gros objets (falaises, tours) : toute leur emprise compte, meme au niveau de la route
PROP_LEVEL = 1.5                 # m : route a moins de ca au-dessus de la base d'un objet = au niveau de son pied
ROCK_KINDS = ('rock',)           # poses par leur origine (faits pour etre a moitie enterres), les autres par leur base
BIG_MIN = 60.0                   # m : semis automatique le long de la route : gros objets au moins a ca du bord (fond)

def _mesh_height(xs, ys, H, mx, my):
    """Hauteur du sol (metres) sur les MEMES triangles que le maillage genere (case (a, b) : triangles a-b-c et
    a-c-d) ; l'interpolation bilineaire s'en ecartait de plusieurs metres sur les talus raides."""
    fx = (mx - xs[0]) / (xs[1] - xs[0])
    fy = (my - ys[0]) / (ys[1] - ys[0])
    i = int(min(max(fx, 0), len(xs) - 2))
    j = int(min(max(fy, 0), len(ys) - 2))
    u, v = min(max(fx - i, 0.0), 1.0), min(max(fy - j, 0.0), 1.0)
    a, b, c, d = H[j, i], H[j, i + 1], H[j + 1, i + 1], H[j + 1, i]
    return a + u * (b - a) + v * (c - b) if u >= v else a + u * (c - d) + v * (d - a)


def ground_height(ground, x, y):
    """Hauteur (pouces) du sol genere sous (x, y) en pouces ; None au-dessus d'un trou (saut) ou hors du terrain."""
    xs, ys, H, hole = ground[:4]
    mx, my = x / INCH, y / INCH
    if not (xs[0] <= mx <= xs[-1] and ys[0] <= my <= ys[-1]):
        return None
    a = min(len(xs) - 2, int((mx - xs[0]) // (xs[1] - xs[0])))
    b = min(len(ys) - 2, int((my - ys[0]) // (ys[1] - ys[0])))
    if hole[b, a]:
        return None
    return float(_mesh_height(xs, ys, H, mx, my)) * INCH


def foot_share(kind):
    """Part du rayon d'emprise qui compte au niveau de la route (pied) pour une famille d'objets."""
    return BIG_FOOT if kind.get('big') else ROCK_FOOT if kind.get('rock') else FOOT_SHARE


def prop_conflict(r, zmin, zmax, s, base, mx, my, C, foot_share=FOOT_SHARE):
    """L'objet (rayon d'emprise r, hauteurs zmin..zmax du modele, echelle s, pose a base m ; position mx, my m) touche-
    t-il la route ? Au niveau de la route (moins de PROP_LEVEL au-dessus de sa base) : seul le pied compte (tronc,
    base : foot_share x rayon) a PROP_CLEAR du bord ; une route plus haute (pont, rampe, route en hauteur) ne doit
    croiser aucune partie de l'objet (emprise complete) tant que le dessous de son tablier est sous son sommet."""
    hd = np.hypot(C[:, 0] - mx, C[:, 1] - my) - C[:, 3] / 2
    top = base + (zmax - zmin) * s
    foot = foot_share * r * s + PROP_CLEAR
    level = C[:, 2] < base + PROP_LEVEL                      # route au niveau du pied (ou plus bas)
    above = ~level & (C[:, 2] - DECK < top + 1.0)            # route plus haute, mais sous le sommet de l'objet
    return bool(((hd < foot) & level).any() or ((hd < r * s * 0.9 + PROP_CLEAR) & above).any())


# role d'une famille d'objets : (inclinaison max selon la pente en degres, part du rayon d'emprise qui doit reposer sur le sol).
# Herbes et rochers epousent le sol ; un arbre ou un mur reste presque droit et s'enfonce du cote du haut.
PROP_ROLES = {'cover': (30.0, 0.6), 'shrub': (15.0, 0.4), 'tree': (5.0, 0.2), 'rock': (30.0, 0.6), 'road': (6.0, 0.4),
              'prop': (12.0, 0.5), 'house': (8.0, 0.7), 'big': (3.0, 0.9)}
ROLE_OF = {**dict.fromkeys(('grass', 'flower', 'plant', 'kelp', 'coral', 'mushroom', 'beach', 'snow', 'bones', 'vine'), 'cover'),
           'bush': 'shrub', **dict.fromkeys(('palm', 'tree', 'pine', 'cactus', 'giant'), 'tree'),
           **dict.fromkeys(('rock', 'crystal', 'gems', 'fossil'), 'rock'),
           **dict.fromkeys(('house', 'hut', 'building'), 'house'),
           **dict.fromkeys(('sign', 'fence', 'lamp', 'lantern', 'torch', 'tire'), 'road')}


def prop_role(kind_name, big=False):
    """Role d'une famille (voir PROP_ROLES) ; tout le reste (statues, machines, tuyaux...) : 'prop'."""
    return 'big' if big else ROLE_OF.get(kind_name, 'prop')


def prop_seat(ground, x, y, yaw, r, s, role):
    """Pose sur le sol genere de l'objet en (x, y) pouces, de rayon r m et d'echelle s -> (bas du modele en m, rx, ry), ou None
    au-dessus d'un trou. Plan moyen du sol sous l'objet, incline au plus de ce que permet le role ; le bas descend ensuite
    jusqu'au point le plus bas de l'emprise par rapport a ce plan (rien ne flotte). Meme calcul que seatOf (creator.js)."""
    tilt, seat = PROP_ROLES[role]
    ang = [i * math.pi / 4 for i in range(8)]
    rt = max(INCH, 0.7 * r * s * INCH)
    around = [ground_height(ground, x + rt * math.cos(a), y + rt * math.sin(a)) for a in ang]
    z0 = ground_height(ground, x, y)
    if z0 is None or sum(z is None for z in around) > 2:
        return None
    around = [z0 if z is None else z for z in around]
    gx = sum(z * math.cos(a) for z, a in zip(around, ang)) / (4 * rt)
    gy = sum(z * math.sin(a) for z, a in zip(around, ang)) / (4 * rt)
    g, lim = math.hypot(gx, gy), math.tan(math.radians(tilt))
    if g > lim:
        gx, gy = gx * lim / g, gy * lim / g
    rf = seat * r * s * INCH
    low = z0
    for f in (0.5, 1.0):
        for a in ang:
            dx, dy = f * rf * math.cos(a), f * rf * math.sin(a)
            z = ground_height(ground, x + dx, y + dy)
            if z is not None:
                low = min(low, z - gx * dx - gy * dy)
    n = math.sqrt(gx * gx + gy * gy + 1)
    nx, ny = -gx / n, -gy / n
    c, sn = math.cos(yaw), math.sin(yaw)
    lx, ly = c * nx + sn * ny, -sn * nx + c * ny                   # normale dans le repere de l'objet tourne
    return low / INCH - PROP_SINK, -math.asin(max(-1.0, min(1.0, ly))), math.atan2(lx, 1 / n)


STEEP_MAX = 80.0     # degres : aucun objet seme au-dela (creator.js STEEP_MAX, meme mesure)


def prop_steep(ground, x, y, r, s):
    """Pente la plus forte du sol genere autour du pied (a 1 m et sur l'emprise), en degres (creator.js seatOf)."""
    z0 = ground_height(ground, x, y)
    if z0 is None:
        return 0.0
    rt = max(INCH, 0.7 * r * s * INCH)
    steep = 0.0
    for rr in (INCH, rt):
        for i in range(8):
            a = i * math.pi / 4
            z = ground_height(ground, x + rr * math.cos(a), y + rr * math.sin(a))
            if z is not None:
                steep = max(steep, abs(z - z0) / rr)
    return math.degrees(math.atan(steep))


def props_items(kit, props, ground, dims):
    """Objets semes du brouillon [{t, m, x, y, yaw, s}] -> items de place_library_many, poses sur le sol genere (prop_seat) par
    leur base (sauf rochers : par leur origine) ; ecartes si l'objet touche la route (prop_conflict) ou un trou de saut.
    Chaque objet peut venir d'un autre theme (p['k'], sinon kit).
    dims(theme) -> {type: [{'r', 'zmin', 'zmax'} (metres) par modele]}. -> (items, nb ecartes)."""
    C = ground[4]
    roof = ground[5] if len(ground) > 5 else None
    xs, ys = ground[0], ground[1]

    def under_roof(x, y):
        if roof is None or xs is None or len(xs) < 2:
            return False
        a = int(round((x / INCH - xs[0]) / (xs[1] - xs[0])))
        b = int(round((y / INCH - ys[0]) / (ys[1] - ys[0])))
        return 0 <= b < roof.shape[0] and 0 <= a < roof.shape[1] and bool(roof[b, a])
    out, dropped = [], 0
    for p in props or []:
        if not p.get('road') and under_roof(p['x'], p['y']):
            dropped += 1
            continue
        k = p.get('k') or kit
        d = (KITS.get(k, {}).get('props') or {}).get(p.get('t'))
        if not d:
            continue
        m = int(p.get('m', 0)) % len(d['models'])
        dm = (dims(k).get(p['t']) or [{}] * len(d['models']))[m]
        s = float(p.get('s', 1.0))
        r, zmin, zmax = float(dm.get('r', 2.0)), float(dm.get('zmin', 0.0)), float(dm.get('zmax', 5.0))
        rock = p['t'] in ROCK_KINDS
        fs = foot_share({**d, 'rock': rock})
        yaw = float(p.get('yaw', 0.0))
        mx, my = p['x'] / INCH, p['y'] / INCH
        # pose a la main SUR la route (p['road'], 2026-11-11) : a plat sur le passage le plus haut sous l'objet ; seule
        # une route plus haute (pont) peut alors l'ecarter. Plus sur la route (trace modifie) : pose normale.
        on = (np.hypot(C[:, 0] - mx, C[:, 1] - my) < C[:, 3] / 2) if p.get('road') else None
        if on is not None and on.any():
            low = float(C[on, 2].max()) + ROAD_LIFT - PROP_SINK
            rx = ry = 0.0
            Cc = C[C[:, 2] >= low + PROP_LEVEL]
        else:
            if prop_steep(ground, p['x'], p['y'], r, s) > STEEP_MAX:     # falaise (objet seme avant la limite)
                dropped += 1
                continue
            seated = prop_seat(ground, p['x'], p['y'], yaw, r, s, prop_role(p['t'], d.get('big')))
            if seated is None:                                       # au-dessus d'un trou de saut
                dropped += 1
                continue
            low, rx, ry = seated                                     # m : bas de l'objet
            Cc = C
        # decalage en hauteur donne a la main (outil Modifier de la Creation, pouces)
        low += float(p.get('dz') or 0.0) / INCH
        if len(Cc) and prop_conflict(r, zmin, zmax, s, low, mx, my, Cc, fs):
            dropped += 1
            continue
        z = (low - (0.0 if rock else zmin * s)) * INCH
        # inclinaison donnee a la main (outil Modifier, 2026-11-12 ; radians) en plus de celle de la pente du sol
        rx += float(p.get('rx') or 0.0)
        ry += float(p.get('ry') or 0.0)
        out.append({'model': d['models'][m], 'pak': d['pak'], 'pos': [p['x'], p['y'], z],
                    'yaw': yaw, 'rot': [rx, ry], 'scale': s})
    return out, dropped

FADE_DEF = 4        # fondu entre peintures : cote (sommets) de la fenetre autour d'une case. 0 : net ; 2 / 4 / 6 : 8 / 24 / 40 m
MIX_MAX = 24        # images de fondu au plus par piste (les plus etendues) ; au-dela, la case prend sa peinture dominante


def _mix_name(lo, hi, level):
    return f'Mix{lo}_{hi}_{level}'


def _cell_materials(M, mix0, fade=FADE_DEF):
    """Peinture de chaque case -> (CM, mixes). Sans fondu : la plus presente a ses 4 coins. Avec : les 2 plus presentes dans la
    fenetre donnent un melange a 25, 50 ou 75 %, code dans CM a partir de mix0 ; mixes = [(peinture lo, peinture hi, quarts de
    hi)]. Le jeu n'a pas d'alpha progressif au sol : chaque melange est une vraie image (mix_textures), mappee comme le sol,
    donc sans couture. Meme calcul que refreshTerrainFaces (creator.js)."""
    fade = int(fade or 0)
    if fade < 2:
        corners = np.stack([M[:-1, :-1], M[:-1, 1:], M[1:, :-1], M[1:, 1:]])          # (4, cases y, cases x)
        present = np.unique(M)
        return present[np.stack([(corners == m).sum(0) for m in present]).argmax(0)], []
    r = (fade - 2) // 2
    win = np.lib.stride_tricks.sliding_window_view(np.pad(M, r, mode='edge'), (fade, fade))
    CM = win[:, :, 0, 0].copy()
    tally = {}
    for b, a in np.argwhere(win.min((2, 3)) != win.max((2, 3))):
        vals, cnt = np.unique(M[max(0, b - r):b + 2 + r, max(0, a - r):a + 2 + r], return_counts=True)
        top = np.argsort(-cnt, kind='stable')[:2]                                     # egalite : la plus petite peinture
        p, q = int(vals[top[0]]), int(vals[top[1]])
        level = int(np.floor(cnt[top[1]] / (cnt[top[0]] + cnt[top[1]]) * 4 + 0.5))
        if not level:
            CM[b, a] = p
            continue
        key = (p, q, level) if p < q else (q, p, 4 - level)
        tally.setdefault(key, []).append((b, a))
    mixes = sorted(tally, key=lambda k: (-len(tally[k]), k))[:MIX_MAX]
    code = {k: mix0 + i for i, k in enumerate(mixes)}
    for k, cells in tally.items():
        c = code.get(k, k[1] if k[2] > 2 else k[0])
        for b, a in cells:
            CM[b, a] = c
    return CM, mixes


_mix_noises = {}


def _mix_noise(size):
    """Bruit carrele uniforme entre 0 et 1 (FFT : il se raccorde sur les bords comme la texture du sol)."""
    if size not in _mix_noises:
        f = np.fft.fftfreq(size) * size
        R = np.hypot(*np.meshgrid(f, f))
        N = np.fft.ifft2(np.fft.fft2(np.random.RandomState(7).standard_normal((size, size))) / (1 + (R / 5.0) ** 2)).real
        rank = np.empty(N.size)
        rank[np.argsort(N, axis=None)] = np.linspace(0, 1, N.size)
        _mix_noises[size] = rank.reshape(N.shape)
    return _mix_noises[size]


def mix_textures(textures, mixes):
    """Images de fondu : {'MixL_H_n.png': octets}. textures : {image: octets PNG} ; mixes : info['mixes']. Decoupe irreguliere et
    douce : 3 niveaux empiles passent de l'un a l'autre sans marche visible sur la grille de 8 m."""
    from PIL import Image
    out, cache = {}, {}

    def load(png, size=None):
        key = (png, size)
        if key not in cache:
            im = Image.open(io.BytesIO(textures[png])).convert('RGB')
            cache[key] = np.asarray(im.resize((size, size), Image.BILINEAR) if size and im.size != (size, size) else im, np.float32)
        return cache[key]
    for name, lo, hi, level in mixes:
        A = load(lo, 1024)
        k = np.clip((level / 4 - _mix_noise(A.shape[0])) / 0.8 + 0.5, 0, 1)[..., None]
        buf = io.BytesIO()
        Image.fromarray((A * (1 - k) + load(hi, A.shape[0]) * k + 0.5).astype(np.uint8)).save(buf, 'PNG')
        out[name + '.png'] = buf.getvalue()
    return out


def paint_materials(kit='sable'):
    """Matieres a peindre, par indice de peinture : 0..3 = celles du theme ; 4 + rang = celles de TOUS les themes dans
    l'ordre de KITS (un sol d'un autre theme se peint sur n'importe lequel ; nom OBJ et image prefixes de son theme).
    -> [(nom OBJ, image, texture du jeu, surface, libelle, couleur, theme)]. Nouveaux themes : a la FIN de KITS (les
    indices des terrains deja peints restent justes)."""
    own = [tuple(m) + (kit,) for m in KITS[kit]['materials']]
    return own + [(f'{k}_{m[0]}', f'{k}_{m[1]}', m[2], m[3], m[4], m[5], k) for k in KITS for m in KITS[k]['materials']]


def surfaces(kit='sable'):
    """{materiau OBJ: surface de collision du jeu (None : sans collision, tablier des ponts)}."""
    return {'Road': KITS[kit]['road_surface'], 'Bridge': None, 'StartLine': None, 'Wall': WALL_SURFACE,
            **{m[0]: m[3] for m in paint_materials(kit)}}


def kit_textures(read, kit='sable', size=1024, used=None):
    """{'road.png': octets, 'sand.png': octets, ...} decodes des textures du jeu ; read(nom logique, archive) -> octets.
    used : noms OBJ des peintures d'autres themes a fournir aussi (celles du theme : toujours)."""
    from PIL import Image
    import preview
    K = KITS[kit]
    out = {}
    extra = [(m[2], m[1], KITS[m[6]]['pak']) for m in paint_materials(kit)[len(K['materials']):] if m[0] in (used or ())]
    for logical, fname, pak in [(K['road'], 'road.png', K['pak'])] + [(tex, png, K['pak']) for _, png, tex, *_ in K['materials']] + extra:
        rgba, _ = preview.decode_texture(read(logical, pak), max_size=size)
        buf = io.BytesIO()
        Image.fromarray(np.asarray(rgba)[..., :3].astype(np.uint8)).save(buf, 'PNG')
        out[fname] = buf.getvalue()
    # damier du depart (2 x 2 cases par repetition), dessine ici : aucun fichier du jeu
    cell = np.indices((2, 2)).sum(0) % 2
    img = (np.kron(cell, np.ones((64, 64)))[..., None].repeat(3, 2) * 225 + 18).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, 'PNG')
    out['checker.png'] = buf.getvalue()
    return out
