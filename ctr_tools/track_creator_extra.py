"""Objets ajoutes a la Creation (bibliotheque du jeu) et objets masques de la liste. Fichier genere : les modeles sont
choisis sur leurs textures (ni uniformes ni sans couleur) et leur poids. AJOUTES EN FIN de famille : les objets deja semes
gardent leur numero de modele ; un objet masque reste au catalogue pour la meme raison (et s'il est deja pose, il le reste)."""

LABELS = {
    "barrel": "🛢 Barils",
    "beach": "⚓ Objets de plage",
    "big": "⛰ Gros objets (fond)",
    "bones": "🦴 Os et étoiles de mer",
    "building": "🏭 Bâtiments",
    "bush": "🌿 Buissons",
    "cactus": "🌵 Cactus",
    "cart": "⛏ Wagonnets et outils",
    "column": "🏛 Colonnes et tours",
    "coral": "🪸 Coraux",
    "crystal": "💎 Cristaux",
    "drum": "🛢 Fûts et vannes",
    "fan": "⚙ Ventilateurs",
    "fence": "🚧 Barrières",
    "flower": "🌸 Fleurs",
    "fossil": "🦴 Fossiles",
    "gear": "⚙ Engrenages",
    "grass": "🌿 Herbes",
    "house": "🏠 Maisons",
    "hut": "🛖 Huttes",
    "kelp": "🌿 Algues",
    "lamp": "💡 Lampes",
    "lantern": "🏮 Lanternes",
    "machine": "🤖 Machines",
    "mushroom": "🍄 Champignons",
    "palm": "🌴 Palmiers",
    "pillar": "🏛 Piliers",
    "pine": "🌲 Sapins",
    "pipe": "🛢 Tuyaux",
    "plant": "🌿 Plantes",
    "rock": "🪨 Rochers",
    "sign": "🪧 Panneaux",
    "snow": "❄ Neige et glaçons",
    "speaker": "🔊 Haut-parleurs",
    "spike": "🚧 Grilles et pics",
    "statue": "🗿 Statues",
    "tech": "🖥 Écrans et panneaux",
    "tesla": "⚡ Bobines",
    "tiki": "🗿 Tikis",
    "tire": "🛞 Pneus et bottes de foin",
    "torch": "🔥 Torches et chandelles",
    "tree": "🌳 Arbres",
    "vine": "🌿 Lianes et souches",
    "wood": "🪵 Poteaux et clôtures"
}

# (theme, famille, modeles)
EXTRA = [
    ('abysses', 'big', [
        'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_Bones_03.igz',
        'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_Coral_sponge_01.igz',
        'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_Coral_sponge_02.igz',
        'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_Magma_Sphere_Pipe.igz',
    ]),
    ('abysses', 'coral', [
        'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_CoralFan03.igz',
        'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_CoralFan04.igz',
        'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_CoralSpotted01.igz',
        'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_CoralSpotted02.igz',
        'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_Coral_red.igz',
        'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_Coralleather_02.igz',
        'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_Coralleather_03.igz',
    ]),
    ('abysses', 'fossil', [
        'models/Levels/Octane/T112_Roos_Tubes/T112_Skull/T112_Roos_Tube_Skeleton_Parts_Bone.igz',
        'models/Levels/Octane/T112_Roos_Tubes/T112_Skull/T112_Roos_Tube_Skeleton_Parts_vertebrae.igz',
    ]),
    ('abysses', 'gear', [
        'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_Gear02.igz',
    ]),
    ('abysses', 'grass', [
        'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_grassClump01.igz',
        'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_grassEdgeA.igz',
        'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_grassEdgeB.igz',
    ]),
    ('abysses', 'lamp', [
        'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_Ceiling_Light.igz',
    ]),
    ('banquise', 'big', [
        'models/Levels/Octane/T143_Polar_Pass/T143_Viking_house01.igz',
        'models/Levels/Octane/T143_Polar_Pass/T143_Viking_house01_red.igz',
        'models/Levels/Octane/T143_Polar_Pass/T143_Viking_house02_orange.igz',
        'models/Levels/Octane/T143_Polar_Pass/T143_Viking_house03.igz',
        'models/Levels/Octane/T143_Polar_Pass/T143_Viking_house03_blue.igz',
        'models/Levels/Octane/T143_Polar_Pass/T143_Viking_house03_orange.igz',
        'models/Levels/Octane/T143_Polar_Pass/T143_Viking_house04_blue.igz',
        'models/Levels/Octane/T143_Polar_Pass/T143_Viking_house06_blue.igz',
    ]),
    ('banquise', 'house', [
        'models/Levels/Octane/T143_Polar_Pass/T143_Viking_house04_ext.igz',
        'models/Levels/Octane/T143_Polar_Pass/T143_Viking_house04_ext_green.igz',
    ]),
    ('banquise', 'pipe', [
        'models/Levels/Octane/T221_Meteor_Gorge/pipe_01.igz',
    ]),
    ('banquise', 'rock', [
        'models/Levels/Crash2/Snow/C2_Snow_Rock01.igz',
    ]),
    ('banquise', 'snow', [
        'models/Levels/Crash2/L202_SnowGo/C2_SnowGo_Cliff05.igz',
        'models/Levels/Crash2/L202_SnowGo/C2_SnowGo_CliffArch01RIcy.igz',
        'models/Levels/Crash2/L206_SnowBiz/C2_SnowBiz_CliffSideIsland02.igz',
        'models/Levels/Octane/A224_Frozen_Frenzy/A224_Frozen_Frenzy_Snow_Top.igz',
        'models/Levels/Octane/A224_Frozen_Frenzy/T224_FF_snow_chunk_decorator_A.igz',
        'models/Levels/Octane/A224_Frozen_Frenzy/T224_FF_snow_chunks_group_A.igz',
        'models/Levels/Octane/A224_Frozen_Frenzy/T224_FF_snow_pile_decorator_A.igz',
        'models/Levels/Octane/A224_Frozen_Frenzy/T224_FF_snow_pile_decorator_B.igz',
    ]),
    ('banquise', 'torch', [
        'models/Levels/Octane/A224_Frozen_Frenzy/A224_FF_Torchere.igz',
    ]),
    ('boogie', 'grass', [
        'models/Levels/Octane/T213_Tiny_Temple/T213_GrassBorder01.igz',
        'models/Levels/Octane/T213_Tiny_Temple/T213_GrassClump02.igz',
    ]),
    ('boogie', 'hut', [
        'models/Levels/Octane/T212_Jungle_Boogie/T212_Jungle_Boogie_Hut_Branch_01.igz',
    ]),
    ('boogie', 'lantern', [
        'models/Levels/Octane/T213_Tiny_Temple/T213_Lantern_A.igz',
    ]),
    ('boogie', 'pillar', [
        'models/Levels/Octane/T213_Tiny_Temple/T213_Tiny_Temple_SmallPillar.igz',
    ]),
    ('boogie', 'plant', [
        'models/Levels/Octane/T213_Tiny_Temple/T213_Leaves01.igz',
    ]),
    ('boogie', 'statue', [
        'models/Levels/Octane/T213_Tiny_Temple/T213_StatueGladiator.igz',
        'models/Levels/Octane/T213_Tiny_Temple/T213_Statue_Tiny_A.igz',
        'models/Levels/Octane/T213_Tiny_Temple/T213_Statue_Tiny_A_Long.igz',
        'models/Levels/Octane/T213_Tiny_Temple/T213_Statue_Tiny_B.igz',
    ]),
    ('boogie', 'tree', [
        'models/Levels/Octane/T212_Jungle_Boogie/T212_Jungle_Boogie_Tree_4.igz',
        'models/Levels/Octane/T212_Jungle_Boogie/T212_Jungle_Boogie_Tree_7.igz',
        'models/Levels/Octane/T212_Jungle_Boogie/T212_Jungle_Boogie_Tree_Branch_01.igz',
        'models/Levels/Octane/T212_Jungle_Boogie/T212_Jungle_Boogie_Tree_Branch_02.igz',
        'models/Levels/Octane/T212_Jungle_Boogie/T212_Jungle_Boogie_Tree_Canopy_5.igz',
        'models/Levels/Octane/T212_Jungle_Boogie/T212_Jungle_Boogie_Tree_Canopy_6.igz',
        'models/Levels/Octane/T212_Jungle_Boogie/T212_Jungle_Boogie_Tree_Main.igz',
        'models/Levels/Octane/T213_Tiny_Temple/T213_Tree01.igz',
    ]),
    ('boogie', 'vine', [
        'models/Levels/Octane/T212_Jungle_Boogie/T212_Boogie_Vine_01.igz',
    ]),
    ('canyon', 'big', [
        'models/Levels/Octane/T144_Tiny_Arena/T144_Tiny_Arena_RaceBuilding01.igz',
    ]),
    ('canyon', 'grass', [
        'models/Levels/Crash3/Desert/C3_DesertGrass01.igz',
        'models/Levels/Crash3/Medieval/C3_GrassBend02.igz',
    ]),
    ('canyon', 'machine', [
        'models/Levels/Crash3/Desert/C3_petrol_pump.igz',
    ]),
    ('canyon', 'rock', [
        'models/Levels/Crash3/Desert/C3_DesertBoulder02.igz',
        'models/Levels/Crash3/Desert/C3_DesertBoulder04.igz',
    ]),
    ('canyon', 'sign', [
        'models/Levels/Crash3/Desert/C3_Sign_DinerNeon_02.igz',
        'models/Levels/Crash3/Desert/C3_Sign_GasNeon_02.igz',
        'models/Levels/Octane/T134_Dingo_Canyon/T134_NoEntry_sign.igz',
    ]),
    ('canyon', 'statue', [
        'models/Levels/Octane/A234_Desert_Storm/A234_Desert_Storm_Gargoyle.igz',
    ]),
    ('canyon', 'wood', [
    ]),
    ('chateau', 'big', [
        'models/Levels/Octane/T152_Cortex_Castle/Cortex_Castle_Optimization/T152_Cortex_Castle_InnerCourt_SecondCorridor_Shell.igz',
        'models/Levels/Octane/T152_Cortex_Castle/T152_Cortex_Castle_InnerCourt_FirstCorridor_Shell.igz',
        'models/Levels/Octane/T152_Cortex_Castle/T152_Cortex_Castle_Prison_Shell.igz',
        'models/Levels/Octane/T152_Cortex_Castle/T152_Cortex_Castle_StainedGlass_Shell.igz',
    ]),
    ('chateau', 'column', [
        'models/Levels/Crash1/castle/C1_B04_ColumnSpikesSquare.igz',
    ]),
    ('chateau', 'fence', [
        'models/Levels/Octane/T152_Cortex_Castle/Cortex_Castle_Roof_Spike_Fence.igz',
    ]),
    ('ciel', 'big', [
        'models/Levels/Octane/T153_Hot_Air_Skyway/T153_LotteryMachine_01.igz',
    ]),
    ('ciel', 'lamp', [
        'models/Levels/Octane/T153_Hot_Air_Skyway/T153_Spotlight_01.igz',
    ]),
    ('egouts', 'fan', [
        'models/Levels/Octane/T114_Sewer_Speedway/T114_Fanblade_fast.igz',
        'models/Levels/Octane/T114_Sewer_Speedway/T114_Fanblade_med.igz',
        'models/Levels/Octane/T114_Sewer_Speedway/T114_Fanblade_slow.igz',
    ]),
    ('egouts', 'lamp', [
        'models/Levels/Octane/T114_Sewer_Speedway/T144_Flood_Light.igz',
    ]),
    ('egouts', 'pipe', [
        'models/Levels/Crash1/factory/C1_CortexPowerPipe_01.igz',
        'models/Levels/Crash1/factory/C1_CortexPowerPipe_02.igz',
        'models/Levels/Octane/T114_Sewer_Speedway/T114_Sewer_Speedway_SmallPipes_Set01.igz',
        'models/Levels/Octane/T114_Sewer_Speedway/T114_Sewer_Speedway_SmallPipes_Set03.igz',
    ]),
    ('espace', 'barrel', [
        'models/Levels/Octane/T154_Oxide_Station/T154_Oxide_Station_GooBarrel.igz',
    ]),
    ('espace', 'big', [
        'models/Levels/Octane/T255_Hyper_Spaceway/T255_Crystal_01.igz',
        'models/Levels/Octane/T255_Hyper_Spaceway/T255_Hyper_Spaceway_Big_Pipe_Exterior.igz',
    ]),
    ('espace', 'lamp', [
        'models/Levels/Octane/T255_Hyper_Spaceway/T255_Hyper_Spaceway_Small_Light_Arch.igz',
        'models/Levels/Octane/T255_Hyper_Spaceway/T255_Hyper_Spaceway_Small_Light_Interior.igz',
        'models/Levels/Octane/T255_Hyper_Spaceway/T255_Sneaky_LightBulb.igz',
    ]),
    ('espace', 'sign', [
        'models/Levels/Octane/T255_Hyper_Spaceway/T255_CTR_Sign.igz',
    ]),
    ('futur', 'big', [
        'models/Levels/Octane/T242_Android_Alley/T242_Exhaust_Pipe.igz',
    ]),
    ('futur', 'cart', [
        'models/Levels/Octane/T242_Android_Alley/wagon.igz',
    ]),
    ('futur', 'column', [
        'models/Levels/Octane/T243_Electron_Avenue/ea_building_centerTower_gear.igz',
    ]),
    ('futur', 'pipe', [
        'models/Levels/Octane/T242_Android_Alley/T242_AA_Entrance_Halfpipe.igz',
        'models/Levels/Octane/T242_Android_Alley/T242_AA_Entrance_HalfpipeB.igz',
        'models/Levels/Octane/T242_Android_Alley/T242_Long_curved_pipe_trim.igz',
    ]),
    ('futur', 'sign', [
        'models/Levels/Octane/T242_Android_Alley/T242_AA_SignA.igz',
    ]),
    ('gorge', 'beach', [
        'models/Levels/Octane/T221_Meteor_Gorge/T221_MG_MineBldg_Crusher_shell.igz',
    ]),
    ('gorge', 'big', [
        'models/Levels/Octane/T221_Meteor_Gorge/T221_Meteor_Gorge_CrabTank_static.igz',
    ]),
    ('gorge', 'lantern', [
        'models/Levels/Octane/T221_Meteor_Gorge/T221_Meteor_Gorge_lantern_base.igz',
    ]),
    ('gorge', 'pipe', [
        'models/Levels/Octane/T221_Meteor_Gorge/T221_Meteor_Gorge_Pipe_Coupler_02.igz',
        'models/Levels/Octane/T221_Meteor_Gorge/T221_Meteor_Gorge_Pipe_detail_02.igz',
        'models/Levels/Octane/T221_Meteor_Gorge/T221_Meteor_Gorge_Pipe_elbow_02.igz',
        'models/Levels/Octane/T221_Meteor_Gorge/T221_Meteor_Gorge_Pipe_elbow_04.igz',
        'models/Levels/Octane/T221_Meteor_Gorge/T221_Meteor_Gorge_Pipe_socket_01.igz',
        'models/Levels/Octane/T221_Meteor_Gorge/T221_Meteor_Gorge_Pipe_socket_02.igz',
    ]),
    ('grottes', 'big', [
        'models/Levels/Octane/T113_Mystery_Caves/T113_Mystery_Caves_assets/T113_Mystery_Caves_FossilRibs.igz',
        'models/Levels/Octane/T113_Mystery_Caves/T113_Mystery_Caves_assets/T113_Mystery_Caves_FossilSkull_Jaw.igz',
        'models/Levels/Octane/T113_Mystery_Caves/T113_Mystery_Caves_assets/T113_Mystery_Caves_FossilSpine.igz',
    ]),
    ('grottes', 'column', [
        'models/Levels/Octane/T113_Mystery_Caves/T113_Mystery_Caves_assets/T113_Mystery_Caves_NBrioBonus_ColumnWide.igz',
    ]),
    ('grottes', 'fossil', [
        'models/Levels/Octane/T112_Roos_Tubes/T112_Skull/T112_Roos_Tube_Skeleton_Parts_Tail.igz',
    ]),
    ('grottes', 'grass', [
        'models/Levels/Crash1/L110_TheLostCity/L110_grassClumpLeft.igz',
        'models/Levels/Crash1/L110_TheLostCity/L110_grassCornerLeft.igz',
        'models/Levels/Crash1/L110_TheLostCity/L110_grassEdgeA.igz',
        'models/Levels/Crash1/L110_TheLostCity/L110_grassEdgeB.igz',
    ]),
    ('grottes', 'pillar', [
        'models/Levels/Crash1/L111_TempleRuins/L111_TempleStonepillar02.igz',
        'models/Levels/Crash1/L111_TempleRuins/L111_TempleStonepillar03.igz',
    ]),
    ('grottes', 'rock', [
        'models/Levels/Octane/T113_Mystery_Caves/T113_Mystery_Caves_assets/T113_Rocks_Border_05.igz',
    ]),
    ('grottes', 'torch', [
    ]),
    ('grottes', 'vine', [
        'models/Levels/Crash3/L304_BoneYard/Prehistoric_Vine01.igz',
    ]),
    ('grottes', 'wood', [
        'models/Levels/Octane/T113_Mystery_Caves/T113_Mystery_Caves_assets/t113_Wood_Post.igz',
    ]),
    ('horloge', 'cart', [
        'models/Levels/Octane/T232_Clockwork_Wumpa/Miningcart_03.igz',
        'models/Levels/Octane/T232_Clockwork_Wumpa/T232_MiningCart_02.igz',
    ]),
    ('horloge', 'gear', [
        'models/Levels/Octane/T232_Clockwork_Wumpa/T232_Gear_03.igz',
    ]),
    ('horloge', 'pipe', [
        'models/Levels/Octane/T232_Clockwork_Wumpa/T232_Pipes_01_Joint.igz',
        'models/Levels/Octane/T232_Clockwork_Wumpa/T232_Pipes_03B.igz',
        'models/Levels/Octane/T232_Clockwork_Wumpa/T232_Pipes_03C.igz',
        'models/Levels/Octane/T232_Clockwork_Wumpa/T232_Pipes_03D_Corner.igz',
        'models/Levels/Octane/T232_Clockwork_Wumpa/T232_Pipes_04.igz',
    ]),
    ('jungle', 'crystal', [
        'models/Levels/Crash1/cave/C1_Cave_Crystals.igz',
    ]),
    ('jungle', 'flower', [
        'models/Levels/Octane/T211_Inferno_Island/Polish/T211_Small_Flower_01.igz',
    ]),
    ('jungle', 'grass', [
        'models/Levels/Crash1/jungle/C1_GrassBend02.igz',
        'models/Levels/Crash1/jungle/C1_GrassPatch01.igz',
    ]),
    ('jungle', 'hut', [
        'models/Levels/Crash1/L107_HogWild/L107_Hut03.igz',
    ]),
    ('jungle', 'pillar', [
        'models/Levels/Crash1/temple/Crash_ZigguratPillar.igz',
        'models/Levels/Octane/A214_Temple_Turmoil/T212_Jungle_Boogie_FencePillar.igz',
    ]),
    ('jungle', 'rock', [
        'models/Levels/Crash1/jungle/C1_Rock02.igz',
        'models/Levels/Crash1/jungle/C1_Rock03.igz',
    ]),
    ('jungle', 'tree', [
        'models/Levels/Crash1/jungle/C1_TreeLeafCanopy01.igz',
        'models/Levels/Crash1/jungle/C1_TreeLeaves_XL.igz',
        'models/Levels/Crash1/jungle/TreeTrunkRoots01.igz',
    ]),
    ('jungle', 'vine', [
        'models/Levels/Crash1/L103_TheGreatGate/VinesIvy02.igz',
        'models/Levels/Octane/T132_Tiger_Temple/T132_Tiger_Temple_Climbing_Vines_01.igz',
        'models/Levels/Octane/T132_Tiger_Temple/T132_Tiger_Temple_Climbing_Vines_02.igz',
    ]),
    ('labo', 'big', [
        'models/Levels/Octane/T151_NGin_Labs/NGin_Labs_Assets/NGin_Labs_ceiling_lights.igz',
        'models/Levels/Octane/T151_NGin_Labs/NGin_Labs_Assets/NGin_Labs_panels_curve.igz',
        'models/Levels/Octane/T151_NGin_Labs/NGin_Labs_Assets/NGin_Labs_panels_nolight.igz',
        'models/Levels/Octane/T151_NGin_Labs/NGin_Labs_Assets/NGin_Labs_pipe_02.igz',
        'models/Levels/Octane/T151_NGin_Labs/NGin_Labs_Assets/NGin_Labs_pipe_03.igz',
        'models/Levels/Octane/T151_NGin_Labs/NGin_Labs_Assets/NGin_Labs_pipe_03_orange.igz',
        'models/Levels/Octane/T151_NGin_Labs/NGin_Labs_Assets/NGin_Labs_pipe_goo_small.igz',
        'models/Levels/Octane/T151_NGin_Labs/NGin_Labs_Assets/Ngin_Labs_Logo.igz',
    ]),
    ('labo', 'building', [
        'models/Levels/Octane/T151_NGin_Labs/NGin_Labs_Assets/NGin_Labs_factory_beam_horizontal_02.igz',
        'models/Levels/Octane/T151_NGin_Labs/NGin_Labs_Assets/NGin_Labs_factory_beam_horizontal_03.igz',
        'models/Levels/Octane/T151_NGin_Labs/NGin_Labs_Assets/NGin_Labs_factory_beam_square_support_01.igz',
        'models/Levels/Octane/T151_NGin_Labs/NGin_Labs_Assets/NGin_Labs_factory_beam_vertical_02.igz',
        'models/Levels/Octane/T151_NGin_Labs/NGin_Labs_Assets/NGin_Labs_factory_beam_vertical_side_02.igz',
        'models/Levels/Octane/T151_NGin_Labs/NGin_Labs_Assets/NGin_Labs_factory_beam_vertical_side_03.igz',
        'models/Levels/Octane/T151_NGin_Labs/NGin_Labs_Assets/NGin_Labs_factory_frame_01.igz',
        'models/Levels/Octane/T151_NGin_Labs/NGin_Labs_Assets/NGin_Labs_factory_frame_02.igz',
    ]),
    ('labo', 'fan', [
        'models/Levels/Octane/T151_NGin_Labs/NGin_Labs_Assets/NGin_Labs_fan.igz',
    ]),
    ('labo', 'lamp', [
        'models/Levels/Octane/A193_Lab_Basement/A193_Lab_Basement_CeilingLights.igz',
    ]),
    ('labo', 'machine', [
        'models/Levels/Crash1/L126_TheLab/theLab_machineTube.igz',
        'models/Levels/Crash1/factory/C1_CastleMachineryGenerator02.igz',
    ]),
    ('labo', 'pipe', [
        'models/Levels/Crash1/L126_TheLab/theLab_PipeCorner.igz',
        'models/Levels/Crash1/factory/C1_CortexPowerPipe_03.igz',
        'models/Levels/Crash2/L221_PistonItAway/PIST_SlimePipe.igz',
        'models/Levels/Octane/T151_NGin_Labs/NGin_Labs_Assets/NGin_Labs_pipe_goo_ceiling.igz',
        'models/Levels/Octane/T151_NGin_Labs/NGin_Labs_Assets/NGin_Labs_pipe_set_08.igz',
        'models/Levels/Octane/T151_NGin_Labs/NGin_Labs_Assets/NGin_Labs_pipe_set_11.igz',
    ]),
    ('labo', 'rock', [
        'models/Levels/Octane/T151_NGin_Labs/T151_NGin_Labs_Rocket.igz',
    ]),
    ('labo', 'tesla', [
        'models/Levels/Octane/T151_NGin_Labs/NGin_Labs_Assets/NGin_Labs_TeslaCoil04_goo.igz',
        'models/Levels/Octane/T151_NGin_Labs/NGin_Labs_Assets/NGin_Labs_Teslacoil_03_goo.igz',
        'models/Levels/Octane/T151_NGin_Labs/NGin_Labs_Assets/NGin_Labs_teslacoil_05_goo.igz',
    ]),
    ('mines', 'big', [
        'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/T142_Dragon_Mines_Fence_1.igz',
        'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/T142_Dragon_Mines_Fence_4.igz',
        'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/T142_Dragon_Mines_House_Balcony_4.igz',
        'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/T142_Dragon_Mines_House_Balcony_7.igz',
        'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/T142_Dragon_Mines_Suspended_Barrels.igz',
        'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/T142_Dragon_Mines_Suspended_Planks.igz',
    ]),
    ('mines', 'cart', [
        'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/T142_Dragon_Mines_Minecart_moving_gold.igz',
    ]),
    ('mines', 'gear', [
        'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/Dragon_Mines_gear_01.igz',
        'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/Dragon_Mines_gear_02.igz',
        'models/Levels/Octane/T142_Dragon_Mines/T142_Gear_01.igz',
    ]),
    ('mines', 'lamp', [
    ]),
    ('mines', 'rock', [
        'models/Levels/Crash1/L101_NSanityBeach/C1_RubbleRocks02.igz',
    ]),
    ('mines', 'sign', [
        'models/Levels/Crash1/L112_RoadToNowhere/L112_Sign01.igz',
    ]),
    ('mines', 'wood', [
        'models/Levels/Crash1/L112_RoadToNowhere/L112_WoodPlank01.igz',
        'models/Levels/Crash1/L112_RoadToNowhere/L112_WoodPlank02.igz',
        'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/Dragon_Mines_wood_plank_long_01.igz',
        'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/Dragon_Mines_wood_plank_medium_01.igz',
        'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/Dragon_Mines_wood_plank_small_01.igz',
        'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/Dragon_Mines_wood_post_small_01.igz',
        'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/Dragon_Mines_wood_post_small_02.igz',
        'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/Dragon_Mines_wood_post_support_02.igz',
    ]),
    ('neige', 'beach', [
        'models/Levels/Octane/T141_Blizzard_Bluff/T141_Blizzard_Bluff_ChairLift_01.igz',
    ]),
    ('neige', 'big', [
        'models/Levels/Octane/T141_Blizzard_Bluff/T141_SupportingPole_SkiStation.igz',
    ]),
    ('neige', 'bones', [
        'models/Levels/Octane/A192_The_North_Bowl/A192_The_North_Bowl_Assets/A192_The_North_Bowl_Fishbone.igz',
    ]),
    ('neige', 'fence', [
        'models/Levels/Octane/T141_Blizzard_Bluff/T141_FiletFencePost_01.igz',
        'models/Levels/Octane/T141_Blizzard_Bluff/T141_WoodenFencePost_01.igz',
    ]),
    ('neige', 'hut', [
        'models/Levels/Octane/T141_Blizzard_Bluff/T141_Window_Shutter.igz',
    ]),
    ('neige', 'mushroom', [
        'models/Levels/Octane/T141_Blizzard_Bluff/T141_Cliff_Mushroom_Top_01.igz',
    ]),
    ('neige', 'rock', [
        'models/Levels/Crash2/Snow/C2_Snow_Rock03.igz',
        'models/Levels/Crash2/Snow/C2_Snow_Rock04.igz',
    ]),
    ('neige', 'sign', [
        'models/Levels/Crash3/L308_HogRide/CurveSign.igz',
        'models/Levels/Octane/T141_Blizzard_Bluff/T141_Ski_Sign_03.igz',
    ]),
    ('neige', 'snow', [
        'models/Levels/Crash2/L202_SnowGo/C2_SnowGo_Cliff03.igz',
        'models/Levels/Crash2/L202_SnowGo/C2_SnowGo_Cliff09.igz',
        'models/Levels/Crash2/L202_SnowGo/C2_SnowGo_Cliff09R.igz',
        'models/Levels/Crash2/L202_SnowGo/C2_SnowGo_CliffFrame01_Ice.igz',
        'models/Levels/Crash2/L202_SnowGo/T143_SnowGo_CliffArch01RIcy.igz',
        'models/Levels/Crash2/Snow/C2_Icicle01.igz',
        'models/Levels/Crash2/Snow/C2_Icicle02.igz',
        'models/Levels/Octane/T141_Blizzard_Bluff/T141_SnowMachine_Support.igz',
    ]),
    ('neige', 'statue', [
        'models/Levels/Octane/T141_Blizzard_Bluff/T141_Blizzard_Bluff_Statue_01.igz',
    ]),
    ('neige', 'torch', [
        'models/Levels/Crash1/village/GameEnts/Village_Hazard_FireBrazier.igz',
    ]),
    ('neige', 'wood', [
        'models/Levels/Crash2/Snow/C2_Destructible_Plank.igz',
    ]),
    ('orage', 'big', [
        'models/Levels/Octane/T233_Thunder_Struck/T233_Vine_RockA.igz',
        'models/Levels/Octane/T233_Thunder_Struck/T233_Vine_RockB.igz',
    ]),
    ('orage', 'building', [
        'models/Levels/Octane/T233_Thunder_Struck/T233_Building_Plates.igz',
        'models/Levels/Octane/T233_Thunder_Struck/T233_Building_TopPart.igz',
    ]),
    ('orage', 'pillar', [
        'models/Levels/Octane/T233_Thunder_Struck/T233_Building_PillarA.igz',
        'models/Levels/Octane/T233_Thunder_Struck/T233_Building_PillarA_Parts.igz',
        'models/Levels/Octane/T233_Thunder_Struck/T233_Building_PillarB.igz',
        'models/Levels/Octane/T233_Thunder_Struck/T233_Building_PillarB_Parts.igz',
        'models/Levels/Octane/T233_Thunder_Struck/T233_Building_PillarC.igz',
        'models/Levels/Octane/T233_Thunder_Struck/T233_Building_PillarD.igz',
        'models/Levels/Octane/T233_Thunder_Struck/T233_Building_TopPillar.igz',
    ]),
    ('parc', 'big', [
        'models/Levels/Octane/A115_Skull_Rock/A115_Foliage_05_vine.igz',
        'models/Levels/Octane/T131_Coco_Park/T131_StackLeavesRed_01.igz',
    ]),
    ('parc', 'flower', [
        'models/Levels/Octane/T131_Coco_Park/T131_BigFlowerLeaves_B_01.igz',
        'models/Levels/Octane/T131_Coco_Park/T131_BigFlowerLeaves_C_01.igz',
        'models/Levels/Octane/T131_Coco_Park/T131_BigFlowerLeaves_D_01.igz',
        'models/Levels/Octane/T131_Coco_Park/T131_BigFlowerLeaves_E_01.igz',
        'models/Levels/Octane/T131_Coco_Park/T131_BigFlowerLeaves_F_01.igz',
        'models/Levels/Octane/T131_Coco_Park/T131_PetalsAlone_01.igz',
    ]),
    ('parc', 'vine', [
        'models/Levels/Octane/T131_Coco_Park/T131_VinesLeafFull04.igz',
        'models/Levels/Octane/T131_Coco_Park/T131_VinesLeafFull06.igz',
    ]),
    ('pyramide', 'grass', [
        'models/Levels/Octane/T133_Papus_Pyramid/Papus_Pyramid_Assets/T133_Grass_Edge_01.igz',
        'models/Levels/Octane/T133_Papus_Pyramid/Papus_Pyramid_Assets/T133_HighResGrass_01.igz',
        'models/Levels/Octane/T133_Papus_Pyramid/Papus_Pyramid_Assets/T133_HighResGrass_02.igz',
    ]),
    ('pyramide', 'pillar', [
        'models/Levels/Octane/T133_Papus_Pyramid/Papus_Pyramid_Assets/Papus_Pyramid_pillar_01.igz',
        'models/Levels/Octane/T133_Papus_Pyramid/Papus_Pyramid_Assets/Papus_Pyramid_pillar_02.igz',
    ]),
    ('pyramide', 'pipe', [
        'models/Levels/Crash2/Temple/Papus_Pyramid_Pipe.igz',
    ]),
    ('pyramide', 'plant', [
        'models/Levels/Octane/T133_Papus_Pyramid/Papus_Pyramid_Assets/Papus_Pyramid_plant_glasses.igz',
    ]),
    ('pyramide', 'rock', [
        'models/Levels/Crash1/L104_Boulders/boulderHollow.igz',
        'models/Levels/Crash1/jungle/C1_Rock04.igz',
    ]),
    ('pyramide', 'sign', [
        'models/Levels/Octane/T133_Papus_Pyramid/Papus_Pyramid_Assets/T133_Papus_Pyramid_Direction_Sign.igz',
    ]),
    ('pyramide', 'vine', [
        'models/Levels/Crash1/temple/VineLeftL.igz',
        'models/Levels/Crash1/temple/VineMidA.igz',
        'models/Levels/Crash1/temple/VineMidC.igz',
        'models/Levels/Crash1/temple/VinesPillar.igz',
    ]),
    ('ruines', 'beach', [
        'models/Levels/Octane/T222_Barin_Ruins/T222_CaveShellA.igz',
    ]),
    ('ruines', 'big', [
        'models/Levels/Octane/T222_Barin_Ruins/T222_Stone_Block_03_detail.igz',
    ]),
    ('ruines', 'snow', [
        'models/Levels/Octane/T222_Barin_Ruins/T222_Stalagtite_D_snow.igz',
    ]),
    ('sable', 'beach', [
        'models/Levels/Crash1/jungle/C1_jungle_boathead.igz',
        'models/Levels/Crash1/jungle/C1_jungle_woodboat.igz',
        'models/Levels/Crash3/JetSki/Lab_Oar_Boat_GenX.igz',
    ]),
    ('sable', 'big', [
    ]),
    ('sable', 'bush', [
        'models/Levels/Crash1/jungle/C1_Bush04.igz',
        'models/Levels/Crash3/Asia/C3_Asia_Bush02.igz',
        'models/Levels/Octane/A115_Skull_Rock/A115_Foliage_04_plant02.igz',
    ]),
    ('sable', 'coral', [
        'models/Levels/Crash3/Sea/C3_Sea_CoralFan03.igz',
    ]),
    ('sable', 'flower', [
        'models/Levels/Crash1/jungle/C1_FlowerClumpPurple01.igz',
    ]),
    ('sable', 'grass', [
        'models/Levels/Crash1/jungle/C1_GrassPatch02.igz',
        'models/Levels/Crash1/jungle/C1_GrassPatch03.igz',
        'models/Levels/Crash3/Medieval/C3_GrassBend01.igz',
        'models/Levels/Octane/T111_Crash_Cove/T111_HighResGrass_01_low.igz',
        'models/Levels/Octane/T111_Crash_Cove/T111_HighResGrass_02_low.igz',
        'models/Levels/Octane/T111_Crash_Cove/T111_HighResGrass_03.igz',
        'models/Levels/Octane/T111_Crash_Cove/T111_HighResGrass_03_low.igz',
    ]),
    ('sable', 'hut', [
    ]),
    ('sable', 'pillar', [
        'models/Levels/Crash1/village/C1_Papu_Pillar.igz',
        'models/Levels/Octane/A115_Skull_Rock/A115_C1_Papu_Pillar.igz',
    ]),
    ('sable', 'rock', [
        'models/Levels/Octane/T111_Crash_Cove/T111_RockModulSmall01.igz',
    ]),
    ('sable', 'statue', [
        'models/Levels/Crash1/L107_HogWild/L107_VillageIdol01.igz',
        'models/Levels/Octane/H110_Nsanity_Beach/H110_CrashStatue.igz',
    ]),
    ('sable', 'tree', [
        'models/Levels/Crash1/jungle/C1_TreeLeaves_L.igz',
        'models/Levels/Crash1/jungle/C1_TreeLeaves_M.igz',
        'models/Levels/Octane/T111_Crash_Cove/Cove_TreeLeaves_M.igz',
        'models/Levels/Octane/T111_Crash_Cove/Cove_TreeLeaves_S.igz',
        'models/Levels/Octane/T111_Crash_Cove/Cove_TreeLeaves_XL.igz',
    ]),
    ('sable', 'vine', [
        'models/Levels/Crash3/L304_BoneYard/Prehistoric_Vine02.igz',
        'models/Levels/Octane/T111_Crash_Cove/T111_Vines03.igz',
        'models/Levels/Octane/T111_Crash_Cove/T111_Vines04.igz',
        'models/Levels/Octane/T111_Crash_Cove/T111_VinesLeaf01.igz',
        'models/Levels/Octane/T111_Crash_Cove/T111_VinesLeaf02.igz',
        'models/Levels/Octane/T111_Crash_Cove/T111_VinesLeafFull01.igz',
        'models/Levels/Octane/T111_Crash_Cove/T111_VinesLeafFull02.igz',
    ]),
    ('sable', 'wood', [
        'models/Levels/Octane/T111_Crash_Cove/T111_CTR_Logo.igz',
        'models/Levels/Octane/T111_Crash_Cove/T111_PlankJump.igz',
    ]),
    ('stade', 'big', [
        'models/Levels/Crash3/Future/C3_Future_Building03.igz',
        'models/Levels/Crash3/Future/C3_Future_Building07.igz',
        'models/Levels/Octane/T121_Slide_Coliseum/T121_Slide_Coliseum_Light.igz',
        'models/Levels/Octane/T121_Slide_Coliseum/T121_Slide_Coliseum_Speakers/Model/T121_Slide_Coliseum_SpeakersA_02.igz',
        'models/Levels/Octane/T121_Slide_Coliseum/T121_Slide_Coliseum_Speakers/Model/T121_Slide_Coliseum_SpeakersB_02.igz',
        'models/Levels/Octane/T121_Slide_Coliseum/T121_Slide_Coliseum_Speakers/Model/T121_Slide_Coliseum_SpeakersC_02.igz',
    ]),
    ('stade', 'bush', [
        'models/Levels/Octane/T152_Cortex_Castle/T152_Cortex_Castle_Bushes_01.igz',
    ]),
    ('stade', 'grass', [
        'models/Levels/Crash3/Medieval/C3_GrassPatch01.igz',
        'models/Levels/Crash3/Medieval/C3_GrassPatch02.igz',
    ]),
    ('stade', 'lamp', [
    ]),
    ('stade', 'sign', [
    ]),
    ('temps', 'gear', [
        'models/Levels/Octane/T231_Out_of_Time/T231_GearsClockCenter_01.igz',
        'models/Levels/Octane/T231_Out_of_Time/T231_Gears_03.igz',
        'models/Levels/Octane/T231_Out_of_Time/T231_Gears_04.igz',
    ]),
    ('temps', 'wood', [
        'models/Levels/Octane/T231_Out_of_Time/T231_WoodenPlank_01.igz',
    ]),
    ('tubes', 'big', [
        'models/Levels/Octane/T112_Roos_Tubes/T112_Rib_Cage/T112_Rib_Cage_01/T112_Rib_Cage_01.igz',
        'models/Levels/Octane/T112_Roos_Tubes/T112_Roos_Tube_Assets/T112_Roos_Tube_Sunken_Boat_Main_Mast.igz',
        'models/Levels/Octane/T112_Roos_Tubes/T112_Roos_Tube_Pipes_02.igz',
        'models/Levels/Octane/T112_Roos_Tubes/T112_Roos_Tubes_Pipes_03.igz',
    ]),
    ('tubes', 'bush', [
        'models/Levels/SpeedTrees/Shrub_Pink_01.igz',
    ]),
    ('tubes', 'coral', [
        'models/Levels/Crash3/Sea/C3_Sea_PurpleCoral01.igz',
        'models/Levels/Octane/T112_Roos_Tubes/T112_Roos_Tube_Assets/T112_Roos_Tube_Sea_CoralFan01_red.igz',
        'models/Levels/Octane/T112_Roos_Tubes/T112_Roos_Tube_Assets/T112_Roos_Tube_Sea_CoralFan03_red.igz',
        'models/Levels/Octane/T112_Roos_Tubes/T112_Roos_Tube_Assets/T112_Roos_Tube_Sea_CoralFan04_red.igz',
        'models/Levels/Octane/T112_Roos_Tubes/T112_Roos_Tube_Assets/T112_Roos_Tube_Table_Coral_01.igz',
        'models/Levels/Octane/T112_Roos_Tubes/T112_Roos_Tube_Assets/T112_Roos_Tube_Table_Coral_02.igz',
        'models/Levels/Octane/T112_Roos_Tubes/T112_Roos_Tube_Assets/T112_Roos_Tube_Tube_Anemone_01.igz',
        'models/Levels/Octane/T112_Roos_Tubes/T112_Roos_Tube_Assets/T112_Roos_Tube_anemone_big_01.igz',
    ]),
    ('tubes', 'fossil', [
        'models/Levels/Octane/T112_Roos_Tubes/T112_Skull/T112_rOOS_Tube_Skull.igz',
    ]),
    ('tubes', 'grass', [
        'models/Levels/Octane/T112_Roos_Tubes/T112_Roos_Tube_Assets/T112_grassCornerLeft.igz',
        'models/Levels/Octane/T112_Roos_Tubes/T112_Roos_Tube_Assets/T112_grassEdgeA.igz',
        'models/Levels/Octane/T112_Roos_Tubes/T112_Roos_Tube_Assets/T112_grassEdgeB.igz',
    ]),
    ('tubes', 'lamp', [
        'models/Levels/Octane/T112_Roos_Tubes/T112_Roos_Tube_Assets/T112_Roos_Tube_Orange_Lights.igz',
        'models/Levels/Octane/T112_Roos_Tubes/T112_Roos_Tube_Assets/T112_Roos_Tube_Purple_Lights.igz',
    ]),
    ('tubes', 'mushroom', [
        'models/Levels/Octane/T112_Roos_Tubes/T112_Mushrooms/T112_Mushroom_01/T112_Roos_Tube_Mushroom.igz',
    ]),
    ('tubes', 'pine', [
        'models/Levels/Octane/T112_Roos_Tubes/T112_Roos_Tube_Spine_Bone.igz',
    ]),
    ('tubes', 'pipe', [
        'models/Levels/Octane/T112_Roos_Tubes/T112_Roos_Tube_Assets/T112_Roos_Tube_Pipe_Fastener.igz',
        'models/Levels/Octane/T112_Roos_Tubes/T112_Roos_Tube_Assets/T112_Roos_Tube_Valve_Red.igz',
        'models/Levels/Octane/T112_Roos_Tubes/T112_Roos_Tube_Assets/T112_Roos_Tube_Valve_Yellow.igz',
    ]),
    ('usine', 'big', [
        'models/Levels/Octane/T241_Assembly_Lane/T241_Assembly_Lane_BuildingSet.igz',
        'models/Levels/Octane/T241_Assembly_Lane/T241_Assembly_Lane_MachineSet_03.igz',
        'models/Levels/Octane/T241_Assembly_Lane/T241_Assembly_Lane_MachineSet_08.igz',
        'models/Levels/Octane/T241_Assembly_Lane/T241_Assembly_Lane_MachineSet_11_no_vents.igz',
        'models/Levels/Octane/T241_Assembly_Lane/T241_Assembly_Lane_Middle_Pipe.igz',
        'models/Levels/Octane/T241_Assembly_Lane/T241_Assembly_Lane_PipeSet_Support_02.igz',
        'models/Levels/Octane/T241_Assembly_Lane/T241_Assembly_Lane_PipeSet_entrance_01.igz',
        'models/Levels/Octane/T241_Assembly_Lane/T241_Assembly_Lane_Pipe_Room_2.igz',
    ]),
    ('usine', 'building', [
        'models/Levels/Octane/T241_Assembly_Lane/T241_Assembly_Lane_Building_Vents01.igz',
        'models/Levels/Octane/T241_Assembly_Lane/T241_Assembly_Lane_Main_Building_Exterior_Tank.igz',
    ]),
    ('usine', 'lamp', [
    ]),
    ('usine', 'pipe', [
        'models/Levels/Octane/T241_Assembly_Lane/T241_Assembly_Lane_PipeSet_Hatch_01.igz',
        'models/Levels/Octane/T241_Assembly_Lane/T241_Assembly_Lane_PipeSet_Post_03.igz',
        'models/Levels/Octane/T241_Assembly_Lane/T241_Assembly_Lane_PipeSet_S_02.igz',
        'models/Levels/Octane/T241_Assembly_Lane/T241_Assembly_Lane_Pipe_Bracket.igz',
        'models/Levels/Octane/T241_Assembly_Lane/T241_Assembly_Lane_Pipe_Cuff.igz',
        'models/Levels/Octane/T241_Assembly_Lane/T241_Assembly_Lane_Pipe_Hole.igz',
    ]),
    ('volcan', 'big', [
        'models/Levels/Octane/T211_Inferno_Island/Polish/T211_OxideShip_reactor.igz',
        'models/Levels/Octane/T211_Inferno_Island/T211_Inferno_DestroyedHut_01.igz',
        'models/Levels/Octane/T211_Inferno_Island/T211_Inferno_TikiGorillaTongueA.igz',
        'models/Levels/Octane/T211_Inferno_Island/T211_RockModul01_Tape01.igz',
        'models/Levels/Octane/T211_Inferno_Island/T211_RockModul01_Tape02.igz',
        'models/Levels/Octane/T211_Inferno_Island/T211_RockModul01_Twist01.igz',
        'models/Levels/Octane/T211_Inferno_Island/T211_RockModul01_Twist02.igz',
        'models/Levels/Octane/T211_Inferno_Island/T211_RockModul02.igz',
    ]),
    ('volcan', 'flower', [
        'models/Levels/Octane/T211_Inferno_Island/Polish/T211_Small_Flower_02.igz',
    ]),
    ('volcan', 'grass', [
        'models/Levels/Octane/T211_Inferno_Island/T211_RockModul04_Grass.igz',
    ]),
    ('volcan', 'mushroom', [
        'models/Levels/Octane/T211_Inferno_Island/T211_NewPlants/T211_MushroomSmall03_Purple.igz',
    ]),
    ('volcan', 'palm', [
        'models/Levels/Octane/T211_Inferno_Island/Polish/T211_Palm_Tree_Trunk.igz',
    ]),
    ('volcan', 'rock', [
        'models/Levels/Octane/T211_Inferno_Island/T211_RockModul03.igz',
        'models/Levels/Octane/T211_Inferno_Island/T211_RockModul03_Taper02.igz',
    ]),
    ('volcan', 'tree', [
        'models/Levels/Octane/T211_Inferno_Island/Polish/T211_Inferno_Stump_RoundPlanks.igz',
    ]),
    ('volcan', 'vine', [
        'models/Levels/Octane/T211_Inferno_Island/Polish/T211_Alien_Vines_05.igz',
        'models/Levels/Octane/T211_Inferno_Island/Polish/T211_Alien_Vines_06.igz',
        'models/Levels/Octane/T211_Inferno_Island/T211_NewPlants/T211_Vines01.igz',
        'models/Levels/Octane/T211_Inferno_Island/T211_NewPlants/T211_VinesLeafFull03.igz',
    ]),
]

# vignette grise ou vide : texture sans couleur ni detail dans l'apercu (la texture semble ne pas charger)
HIDDEN = {
    'models/Levels/Crash1/L126_TheLab/theLab_panel1.igz',
    'models/Levels/Crash1/cave/T143_Crystal_Blue01.igz',
    'models/Levels/Crash1/jungle/C1_Bush01.igz',
    'models/Levels/Crash1/jungle/C1_Bush02.igz',
    'models/Levels/Crash1/jungle/C1_Bush03.igz',
    'models/Levels/Crash2/Global/C2_BonusTree05.igz',
    'models/Levels/Crash2/Snow/C2_Dead_Tree01.igz',
    'models/Levels/Crash2/Snow/C2_Pine_Tree03.igz',
    'models/Levels/Crash2/Snow/Crystal_Blue01.igz',
    'models/Levels/Crash2/Snow/T143_Birch_Tree01.igz',
    'models/Levels/Crash2/Snow/T143_Birch_Tree02.igz',
    'models/Levels/Crash2/Snow/T143_Crystal_blue02.igz',
    'models/Levels/Crash3/Future/C3_Future_Tower04.igz',
    'models/Levels/Crash3/Future/C3_Future_Tower05.igz',
    'models/Levels/Crash3/L308_HogRide/ArmadilloSign.igz',
    'models/Levels/Crash3/Medieval/C3_CarnivalTent01.igz',
    'models/Levels/Octane/A115_Skull_Rock/A115_Foliage_02.igz',
    'models/Levels/Octane/A115_Skull_Rock/A115_Foliage_03_fern01.igz',
    'models/Levels/Octane/A115_Skull_Rock/A115_Foliage_03_fern02.igz',
    'models/Levels/Octane/A115_Skull_Rock/A115_Foliage_03_fern03.igz',
    'models/Levels/Octane/T114_Sewer_Speedway/T114_Pipe01.igz',
    'models/Levels/Octane/T114_Sewer_Speedway/T114_Valve.igz',
    'models/Levels/Octane/T122_Turbo_Track/T122_Haystack_02.igz',
    'models/Levels/Octane/T122_Turbo_Track/T122_KartDeadinator.igz',
    'models/Levels/Octane/T122_Turbo_Track/T122_KartDoomBuggy.igz',
    'models/Levels/Octane/T122_Turbo_Track/T122_KartSpeed.igz',
    'models/Levels/Octane/T122_Turbo_Track/T122_KartTrikee.igz',
    'models/Levels/Octane/T131_Coco_Park/T131_FlowerDaisy01.igz',
    'models/Levels/Octane/T131_Coco_Park/T131_FlowerDaisy02.igz',
    'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/Dragon_Mines_Treasures_Ankh_Gold.igz',
    'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/Dragon_Mines_Treasures_Ankh_Platnium.igz',
    'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/Dragon_Mines_Treasures_Ankh_Sapphire.igz',
    'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/Dragon_Mines_Treasures_BlueGem.igz',
    'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/Dragon_Mines_Treasures_GreenGem.igz',
    'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/Dragon_Mines_Treasures_OrangeGem.igz',
    'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/Dragon_Mines_lantern.igz',
    'models/Levels/Octane/T142_Dragon_Mines/Dragon_Mines_Assets/T142_Dragon_Mines_Minecart_empty.igz',
    'models/Levels/Octane/T143_Polar_Pass/T143_Hut.igz',
    'models/Levels/Octane/T151_NGin_Labs/NGin_Labs_Assets/NGin_Labs_pipe_01_gray.igz',
    'models/Levels/Octane/T152_Cortex_Castle/Cortex_Castle_Assets/Cortex_Castle_metal_spike_01.igz',
    'models/Levels/Octane/T152_Cortex_Castle/T152_Cortex_Castle_Cage.igz',
    'models/Levels/Octane/T211_Inferno_Island/T211_Inferno_TikiGorillaC.igz',
    'models/Levels/Octane/T211_Inferno_Island/T211_NewPlants/FernAlien_01.igz',
    'models/Levels/Octane/T211_Inferno_Island/T211_NewPlants/T211_Bush01.igz',
    'models/Levels/Octane/T211_Inferno_Island/T211_NewPlants/T211_Bush02.igz',
    'models/Levels/Octane/T211_Inferno_Island/T211_NewPlants/T211_Bush03.igz',
    'models/Levels/Octane/T211_Inferno_Island/T211_NewPlants/T211_FernPink_A.igz',
    'models/Levels/Octane/T221_Meteor_Gorge/T221_Cliff_02.igz',
    'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_Mushroom_Intro_Cavern.igz',
    'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_Sea_Grass_01.igz',
    'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_Sea_Grass_02.igz',
    'models/Levels/Octane/T223_Deep_Sea_Driving/T223_Deep_Sea_Driving_Assets/T223_Deep_Sea_Driving_Sea_Grass_03.igz',
    'models/Levels/Octane/T231_Out_of_Time/T231_Fence_01.igz',
    'models/Levels/Octane/T231_Out_of_Time/T231_Lantern_01.igz',
    'models/Levels/Octane/T231_Out_of_Time/T231_Lantern_02.igz',
    'models/Levels/Octane/T231_Out_of_Time/T231_MetalFenceBroken_01.igz',
    'models/Levels/Octane/T232_Clockwork_Wumpa/T232_Lantern_01.igz',
    'models/Levels/Octane/T233_Thunder_Struck/T233_Building_TopCoil.igz',
    'models/Levels/Octane/T241_Assembly_Lane/T241_Assembly_Lane_PipeSet_Post_01.igz',
    'models/Levels/Octane/T241_Assembly_Lane/T241_Assembly_Lane_TV.igz',
    'models/Levels/Octane/T241_Assembly_Lane/T241_Assembly_Lane_Valve_Sphere.igz',
    'models/Levels/Octane/T242_Android_Alley/T242_AA_Building_A.igz',
    'models/Levels/Octane/T242_Android_Alley/T242_AA_Building_B.igz',
    'models/Levels/Octane/T242_Android_Alley/T242_AA_Building_C.igz',
    'models/Levels/Octane/T243_Electron_Avenue/ElectronAve_building001_a.igz',
    'models/Levels/Octane/T243_Electron_Avenue/ElectronAve_building002_a.igz',
    'models/Levels/Octane/T243_Electron_Avenue/ElectronAve_building003_a.igz',
    'models/Levels/Octane/T243_Electron_Avenue/ElectronAve_building004_a.igz',
    'models/Levels/Octane/T243_Electron_Avenue/ElectronAve_building005_a.igz',
    'models/Levels/Octane/T243_Electron_Avenue/ElectronAve_building006_a.igz',
    'models/Levels/SpeedTrees/Shrub_Palm_02.igz',
    'models/Levels/SpeedTrees/Shrub_Palm_03.igz',
}
