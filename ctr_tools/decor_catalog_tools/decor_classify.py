"""Nouveau catalogue du decor de la Creation (lecture seule sur le jeu ; ecrit ctr_tools/track_creator_catalog.py seulement
avec --write). Classement par MOTS du nom (pas de sous-chaine : Spine n'est pas un sapin, Rocket pas un rocher), mot
principal prioritaire, taille reelle (gros objets = fond), textures (ni grises ni unies), poids. Garde TOUS les modeles
deja proposes (les objets deja semes doivent rester valides) et ajoute ceux des pistes de chaque theme."""
import os, sys, re, json
from collections import defaultdict, Counter
ROOT = r'C:\Users\Boooing\Desktop\Nouveau dossier'
sys.path.insert(0, os.path.join(ROOT, 'ctr_tools'))
import track_creator as tc
HERE = os.path.dirname(os.path.abspath(__file__))
SURVEY = json.load(open(os.path.join(HERE, 'decor_survey.json'), encoding='utf-8'))
S = {k.lower(): v for k, v in SURVEY.items()}
import pak_tool, library  # noqa: E402
_cfg = json.load(open(os.path.join(ROOT, 'ctr_editor_config.json'), encoding='utf-8'))
_A = pak_tool.set_layout(_cfg['archives'])['archives']
SURVEY_CASE = {m['model'].lower(): m['model'] for m in library.catalog(_A)}   # nom avec la casse de l'archive

# ---- mots -> categorie (le 1er mot reconnu en partant de la FIN du nom l'emporte, sauf mots forts) ----
WORDS = {
    'palm': 'palm', 'palms': 'palm',
    'pine': 'pine', 'pines': 'pine', 'birch': 'pine', 'fir': 'pine', 'spruce': 'pine',
    'tree': 'tree', 'trees': 'tree', 'trunk': 'tree', 'canopy': 'tree', 'oak': 'tree', 'willow': 'tree', 'baobab': 'tree', 'bonustree': 'tree',
    'cactus': 'cactus', 'cacti': 'cactus',
    'mushroom': 'mushroom', 'mushrooms': 'mushroom', 'shroom': 'mushroom', 'fungi': 'mushroom', 'fungus': 'mushroom',
    'flower': 'flower', 'flowers': 'flower', 'petal': 'flower', 'petals': 'flower', 'daisy': 'flower', 'tulip': 'flower', 'bloom': 'flower',
    'flowerclump': 'flower', 'flowerbucket': 'flower', 'flowerset': 'flower',
    'bush': 'bush', 'bushes': 'bush', 'shrub': 'bush', 'foliage': 'bush', 'fern': 'bush', 'ferns': 'bush', 'hedge': 'bush',
    'plant': 'bush', 'plants': 'bush', 'leaves': 'bush', 'leaf': 'bush',
    'vine': 'vine', 'vines': 'vine', 'ivy': 'vine', 'liana': 'vine', 'roots': 'vine', 'root': 'vine', 'stump': 'vine', 'bark': 'vine',
    'grass': 'grass', 'grasses': 'grass', 'reed': 'grass', 'reeds': 'grass', 'weed': 'grass', 'weeds': 'grass',
    'kelp': 'kelp', 'seaweed': 'kelp', 'algae': 'kelp',
    'coral': 'coral', 'corals': 'coral', 'anemone': 'coral', 'sponge': 'coral', 'coralfan': 'coral', 'coralleather': 'coral',
    'coralspotted': 'coral', 'coralpiece': 'coral', 'redcoral': 'coral', 'purplecoral': 'coral',
    'starfish': 'bones', 'shell': 'bones', 'shells': 'bones', 'bone': 'bones', 'bones': 'bones', 'skeleton': 'bones',
    'vertebrae': 'bones', 'fishbone': 'bones', 'rib': 'bones', 'ribs': 'bones', 'fossil': 'bones', 'spine': 'bones',
    'crystal': 'crystal', 'crystals': 'crystal', 'gem': 'crystal', 'gems': 'crystal', 'treasures': 'crystal', 'treasure': 'crystal',
    'rock': 'rock', 'rocks': 'rock', 'stone': 'rock', 'stones': 'rock', 'boulder': 'rock', 'boulders': 'rock', 'pebble': 'rock',
    'rubble': 'rock', 'rubblerocks': 'rock', 'rockmodul': 'rock', 'modboulder': 'rock', 'iceblock': 'rock', 'asteroide': 'rock', 'asteroid': 'rock',
    'cliff': 'cliff', 'cliffs': 'cliff', 'mountain': 'cliff', 'rockwall': 'cliff', 'mesa': 'cliff', 'cliffsmall': 'rock', 'cliffmedium': 'cliff',
    'clifflarge': 'cliff', 'cliffmodule': 'cliff',
    'pillar': 'pillar', 'pillars': 'pillar', 'column': 'pillar', 'columns': 'pillar', 'totem': 'pillar', 'obelisk': 'pillar',
    'stalagmite': 'pillar', 'stalagtite': 'pillar', 'stalactite': 'pillar', 'spire': 'pillar', 'rockpillar': 'pillar',
    'statue': 'statue', 'statues': 'statue', 'idol': 'statue', 'bighead': 'statue', 'gargoyle': 'statue', 'tiki': 'statue', 'mask': 'statue',
    'sphinx': 'statue', 'bust': 'statue', 'skull': 'statue', 'trophy': 'statue', 'snowman': 'statue', 'head': 'statue', 'throne': 'statue',
    'house': 'house', 'houses': 'house', 'hut': 'house', 'tent': 'house', 'cabin': 'house', 'chalet': 'house', 'igloo': 'house',
    'shack': 'house', 'building': 'house', 'buildings': 'house', 'campsite': 'house', 'diner': 'house', 'silo': 'house', 'windmill': 'house',
    'tower': 'house', 'church': 'house',
    'fence': 'fence', 'fences': 'fence', 'barrier': 'fence', 'railing': 'fence', 'post': 'fence', 'woodpost': 'fence', 'plank': 'fence',
    'planks': 'fence', 'spikes': 'fence', 'spike': 'fence', 'cage': 'fence', 'fencepost': 'fence', 'wood': 'fence',
    'sign': 'sign', 'signs': 'sign', 'billboard': 'sign', 'arrow': 'sign', 'arrows': 'sign', 'flagpost': 'sign', 'flag': 'sign', 'ad': 'sign',
    'lamp': 'lamp', 'lamppost': 'lamp', 'light': 'lamp', 'lights': 'lamp', 'lantern': 'lamp', 'torch': 'lamp', 'brazier': 'lamp',
    'brazero': 'lamp', 'candle': 'lamp', 'spotlight': 'lamp', 'torchere': 'lamp', 'lightbulb': 'lamp',
    'pipe': 'pipe', 'pipes': 'pipe', 'valve': 'pipe', 'gasket': 'pipe', 'bracket': 'pipe', 'coupler': 'pipe', 'elbow': 'pipe', 'pipeset': 'pipe',
    'machine': 'machine', 'machineset': 'machine', 'generator': 'machine', 'computer': 'machine', 'tesla': 'machine', 'teslacoil': 'machine',
    'coil': 'machine', 'reactor': 'machine', 'fan': 'machine', 'fanblade': 'machine', 'gear': 'machine', 'gears': 'machine', 'screen': 'machine',
    'keyboard': 'machine', 'pump': 'machine', 'furnace': 'machine', 'magnet': 'machine', 'meter': 'machine', 'tv': 'machine', 'xray': 'machine',
    'rocket': 'machine', 'clock': 'machine', 'stomper': 'machine', 'panel': 'machine', 'scaphandre': 'machine',
    'barrel': 'barrel', 'barrels': 'barrel', 'crate': 'barrel', 'box': 'barrel', 'chest': 'barrel', 'container': 'barrel', 'cart': 'barrel',
    'minecart': 'barrel', 'miningcart': 'barrel', 'wagon': 'barrel', 'drum': 'barrel', 'bucket': 'barrel', 'cauldron': 'barrel', 'goobarrel': 'barrel',
    'snow': 'snow', 'snowpile': 'snow', 'snowmound': 'snow', 'snowdrift': 'snow', 'snowblocks': 'snow', 'icicle': 'snow', 'snowgo': 'snow',
    'tire': 'tire', 'tires': 'tire', 'wheel': 'tire', 'haystack': 'tire',
    'boat': 'beach', 'rowboat': 'beach', 'woodboat': 'beach', 'oar': 'beach', 'mast': 'beach', 'anchor': 'beach', 'boathead': 'beach',
    'kart': 'kart',
}
# mots « forts » : l'emportent ou qu'ils soient dans le nom (le support : un pilier aux lianes est un pilier)
STRONG = ('coral', 'crystal', 'cactus', 'palm', 'pine', 'mushroom', 'cliff', 'rock', 'pillar', 'statue', 'house', 'kart', 'pipe', 'machine')
# mots qui ne decrivent pas l'objet (lieux, numeros, styles)
SKIP = {'t', 'c', 'a', 'b', 'd', 'e', 'f', 'g', 'l', 'r', 's', 'x', 'nx', 'df', 'v', 'mod', 'set', 'small', 'big', 'large', 'medium', 'tall',
        'short', 'low', 'high', 'res', 'new', 'old', 'red', 'blue', 'green', 'pink', 'purple', 'yellow', 'orange', 'gold', 'icy', 'ice', 'static',
        'snowy', 'moss', 'mossy', 'broken', 'destroyed', 'detail', 'main', 'top', 'base', 'left', 'right', 'center', 'mid', 'end', 'cap',
        'crash', 'cove', 'jungle', 'sea', 'desert', 'cave', 'caves', 'mystery', 'inferno', 'island', 'polar', 'pass', 'labs', 'lab', 'ngin',
        'cortex', 'dragon', 'mines', 'roos', 'tube', 'tubes', 'deep', 'driving', 'meteor', 'gorge', 'papus', 'pyramid', 'tiger', 'coco', 'park',
        'blizzard', 'bluff', 'dingo', 'canyon', 'sewer', 'speedway', 'electron', 'avenue', 'android', 'alley', 'assembly', 'lane', 'thunder',
        'struck', 'clockwork', 'wumpa', 'out', 'of', 'time', 'hyper', 'spaceway', 'oxide', 'station', 'barin', 'ruins', 'jungle', 'boogie',
        'tiny', 'slide', 'coliseum', 'turbo', 'track', 'hot', 'air', 'skyway', 'n', 'gin', 'prehistoric', 'future', 'asia', 'medieval',
        'polish', 'newplants', 'assets', 'exotic', 'vista', 'ff', 'mg', 'aa', 'ea', 'gpe', 'roadgpe', 'nsanity', 'beach', 'village', 'factory',
        'global', 'speedtrees', 'alien', 'castle', 'goo', 'gray', 'cold', 'hot', 'empty', 'moving', 'props', 'grin', 'angry', 'kong', 'koala'}
LABELS = {
    'palm': '🌴 Palmiers', 'tree': '🌳 Arbres', 'pine': '🌲 Sapins', 'cactus': '🌵 Cactus', 'bush': '🌿 Buissons et plantes',
    'grass': '🌾 Herbes', 'flower': '🌸 Fleurs', 'mushroom': '🍄 Champignons', 'vine': '🍂 Lianes, racines et souches',
    'kelp': '🌊 Algues', 'coral': '🪸 Coraux', 'bones': '🐚 Os, coquillages et étoiles de mer', 'crystal': '💎 Cristaux et trésors',
    'rock': '🪨 Rochers', 'pillar': '🏛 Piliers et colonnes', 'statue': '🗿 Statues', 'house': '🏠 Maisons et bâtiments',
    'fence': '🚧 Clôtures, poteaux et planches', 'sign': '🪧 Panneaux et drapeaux', 'lamp': '💡 Lampes, lanternes et torches',
    'pipe': '🛢 Tuyaux et vannes', 'machine': '⚙ Machines et engrenages', 'barrel': '📦 Barils, caisses et wagonnets',
    'snow': '❄ Neige et glaçons', 'tire': '🛞 Pneus et bottes de foin', 'beach': '⚓ Barques et épaves', 'kart': '🏎 Karts exposés',
    'prop': '🧩 Objets divers', 'big': '⛰ Falaises et gros objets (fond)'}
# (echelle, espacement m) par categorie
FAM = {'palm': ((0.85, 1.2), 10.0), 'tree': ((0.85, 1.2), 13.0), 'pine': ((0.85, 1.2), 10.0), 'cactus': ((0.8, 1.2), 8.0),
       'bush': ((0.8, 1.2), 7.0), 'grass': ((0.8, 1.4), 3.0), 'flower': ((0.8, 1.3), 4.0), 'mushroom': ((0.8, 1.3), 5.0),
       'vine': ((0.8, 1.2), 6.0), 'kelp': ((0.8, 1.3), 4.0), 'coral': ((0.8, 1.3), 5.0), 'bones': ((0.8, 1.2), 6.0),
       'crystal': ((0.8, 1.2), 8.0), 'rock': ((0.6, 1.1), 11.0), 'pillar': ((0.8, 1.1), 18.0), 'statue': ((1.0, 1.0), 25.0),
       'house': ((1.0, 1.0), 30.0), 'fence': ((1.0, 1.0), 6.0), 'sign': ((1.0, 1.0), 14.0), 'lamp': ((1.0, 1.0), 14.0),
       'pipe': ((1.0, 1.0), 10.0), 'machine': ((1.0, 1.0), 15.0), 'barrel': ((0.9, 1.1), 7.0), 'snow': ((0.8, 1.2), 7.0),
       'tire': ((1.0, 1.0), 6.0), 'beach': ((1.0, 1.0), 12.0), 'kart': ((1.0, 1.0), 25.0), 'prop': ((1.0, 1.0), 12.0),
       'big': ((0.7, 1.0), 45.0)}
# pistes d'origine de chaque theme (en plus de KITS[kit]['pak'])
HOME = {'stade': ['t121_slide_coliseum.pak'], 'espace': ['t154_oxide_station.pak'], 'futur': ['t242_android_alley.pak'],
        'boogie': ['t213_tiny_temple.pak'], 'sable': ['a115_skull_rock.pak', 'h110_nsanity_beach.pak'],
        'neige': ['a192_the_north_bowl.pak'], 'banquise': ['a224_frozen_frenzy.pak'], 'labo': ['a193_lab_basement.pak'],
        'canyon': ['a234_desert_storm.pak'], 'parc': ['t144_tiny_arena.pak']}
BAD_NAME = re.compile(r'decal|_lod|lowpoly|proxy|shadow|collision|occlud|interior|corridor|floor|ceiling|roof|ground|terrain|road|ramp'
                      r'|jump|track|curb|banner|logo|start|finish|checkpoint|portal|tunnel|bridge|stairs|stair|door|window|shutter'
                      r'|platform|helipad|section|piece_|_part|parts|sky|water|wave|lava|plane|card|cloud|smoke|fx|vfx|_anim|boss|test|temp_'
                      r'|crate_basic|beenox|timecrate|nitrocrate|capture_flag|^item_|ruins_web', re.I)


def words(name):
    n = re.sub(r'([a-z])([A-Z])', r'\1_\2', name)
    n = re.sub(r'([A-Za-z])(\d)', r'\1_\2', n)
    toks = [t.lower() for t in re.split(r'[_\W\d]+', n) if t]
    # mots colles (« flowerclump », « rockmodul ») : le mot entier puis ses morceaux
    whole = [t.lower() for t in re.split(r'[_\W]+', re.sub(r'\d+', '_', name)) if t]
    return toks, whole


def category(name):
    toks, whole = words(name)
    # mots entiers d'abord (« CliffSmall » = petit rocher, « CoralFan » = corail), puis les morceaux
    for group in ([WORDS[t] for t in whole if t in WORDS and t not in SKIP], [WORDS[t] for t in toks if t in WORDS and t not in SKIP]):
        if not group:
            continue
        for s in STRONG:
            if s in group:
                return s
        return group[-1]                                   # mot principal : le dernier reconnu (« Snow_Rock » -> rock)
    return None


def size_of(rec):
    h = (rec.get('zmax', 0) or 0) - (rec.get('zmin', 0) or 0)
    return max(h, 2 * (rec.get('r') or 0)), h


BUILT = ('house', 'pillar', 'statue', 'machine', 'pipe', 'prop', 'beach', 'bones', 'fence', 'barrel', 'sign', 'lamp', 'kart')


def is_big(rec, cat, was_big):
    """Fond de carte : ce qui y etait deja, les falaises, et les objets construits enormes (vegetation et rochers restent
    dans leur famille, meme grands : palmiers d'Inferno, gros rochers de Crash Cove)."""
    span, h = size_of(rec)
    return was_big or (cat == 'cliff' and span > 25) or (cat in BUILT and (span > 45 or h > 30))


def looks_ok(rec):
    st = [t for t in rec.get('tstats') or [] if 'mean' in t]
    if not st:
        return False
    if all(t['std'] < 0.025 and t['sat'] < 0.08 for t in st):
        return False                                       # gris uni : vignette vide
    if all(max(t['mean']) < 0.06 for t in st):
        return False                                       # noir
    span, h = size_of(rec)
    if span < 0.35:
        return False                                       # minuscule
    if (rec.get('tris') or 0) > 40000:
        return False
    return True


# ---- ancien catalogue (a garder : objets deja semes) ----
LEGACY = {k: {f: list(d['models']) for f, d in (v.get('props') or {}).items()} for k, v in tc.KITS.items()}
HIDDEN = {m.lower() for m in tc.HIDDEN_MODELS}
new = {}
report = []
for kit, kv in tc.KITS.items():
    paks = {kv['pak']} | set(HOME.get(kit, []))
    old = [m for f in LEGACY[kit].values() for m in f]
    cands = list(dict.fromkeys(old))
    oldset = {m.lower() for m in old}
    for p, rec in S.items():
        if p in oldset or not (set(rec['users']) & paks):
            continue
        nm = os.path.basename(p)[:-4]
        if BAD_NAME.search(nm) or not looks_ok(rec):
            continue
        if p in SURVEY_CASE:
            cands.append(SURVEY_CASE[p])
    fams = defaultdict(list)
    for m in cands:
        nm = os.path.basename(m)[:-4]
        rec = S.get(m.lower(), {})
        cat = category(nm)
        oldfam = next((f for f, L in LEGACY[kit].items() if m in L), None)
        was_big = bool(oldfam and tc.KITS[kit]['props'][oldfam].get('big'))
        if cat is None:
            if m.lower() not in oldset:
                continue                                   # nouveau sans mot reconnu : ecarte
            cat = 'prop'
        # objet deja propose : reste au fond seulement s'il y etait (sa taille est mesuree depuis son origine, parfois
        # decalee : maisons vikings, totems) ; nouveau : d'apres sa taille
        movable = cat in ('house', 'statue', 'beach', 'barrel', 'fence', 'lamp', 'sign', 'pine', 'tree', 'palm') and size_of(rec or {})[0] <= 45
        if (was_big and not movable) if m.lower() in oldset else is_big(rec or {}, cat, False):
            cat = 'big'
        elif cat == 'cliff':
            cat = 'rock'
        fams[cat].append(m)
    # famille faite seulement de 1 ou 2 nouveaux objets : bruit (objet isole d'une autre piste), retiree
    for cat in [c for c, L in fams.items() if len(L) < 3 and not any(m.lower() in oldset for m in L)]:
        del fams[cat]
    # taille des familles : anciens modeles d'abord, puis nouveaux (3 variantes au plus par nom de base), 24 au plus
    out = {}
    for cat, L in fams.items():
        keep, base_n = [], Counter()
        for m in L:
            b = re.sub(r'[_\d]+[a-z]?$', '', os.path.basename(m)[:-4].lower())
            if m.lower() in oldset:
                keep.append(m); base_n[b] += 1
        for m in L:
            if m.lower() in oldset:
                continue
            b = re.sub(r'[_\d]+[a-z]?$', '', os.path.basename(m)[:-4].lower())
            if base_n[b] >= 3 or len(keep) >= 24:
                continue
            keep.append(m); base_n[b] += 1
        out[cat] = keep
    new[kit] = out
    n_old, n_new = len(set(old)), sum(len(v) for v in out.values())
    report.append(f'## {kit} : {n_old} -> {n_new} modeles, {len(LEGACY[kit])} -> {len(out)} familles')
    for cat in sorted(out, key=lambda c: list(LABELS).index(c)):
        L = out[cat]
        report.append(f'  [{cat}] {LABELS[cat]} ({len(L)}) : ' + ', '.join(('' if m.lower() in oldset else '+') + os.path.basename(m)[:-4] for m in L))
open(os.path.join(HERE, 'decor_new.txt'), 'w', encoding='utf-8').write('\n'.join(report))
json.dump({'legacy': LEGACY, 'new': new}, open(os.path.join(HERE, 'decor_new.json'), 'w', encoding='utf-8'))
print('\n'.join(r for r in report if r.startswith('##')))

# ---- ecriture du catalogue (--write) ----
if '--write' in sys.argv:
    order = list(LABELS)
    pr = lambda o: json.dumps(o, ensure_ascii=False)
    L = ['"""Decor de la Creation par theme : familles d\'objets du jeu (FICHIER GENERE le 2026-11-17 par decor_classify.py du',
         'scratchpad, a partir d\'un releve de tous les modeles du jeu : mots du nom, taille reelle, textures).',
         'Classement par MOTS du nom (Spine n\'est pas un sapin, Rocket pas un rocher), mot principal prioritaire (un pilier aux',
         'lianes est un pilier), falaises et objets construits enormes au fond. LEGACY = ancien catalogue (familles et numeros',
         'des objets deja semes) : track_creator.migrate_prop convertit ces objets (marque c = 2)."""',
         '', 'CATALOG_VERSION = 2', '', '# famille -> (libelle, echelle, espacement m)']
    L.append('FAMILIES = {')
    for c in order:
        (a, b), sp = FAM[c]
        L.append(f'    {pr(c)}: ({pr(LABELS[c])}, ({a}, {b}), {sp}),')
    L.append('}')
    L.append('')
    L.append('# theme -> [(famille, [modeles])], dans l\'ordre de la liste')
    L.append('CATALOG = {')
    for kit, fams in new.items():
        L.append(f'    {pr(kit)}: [')
        for c in sorted(fams, key=order.index):
            L.append(f'        ({pr(c)}, [')
            L += [f'            {pr(m)},' for m in fams[c]]
            L.append('        ]),')
        L.append('    ],')
    L.append('}')
    L.append('')
    L.append('# ancien catalogue (avant le 2026-11-17) : theme -> famille -> modeles (numero = rang)')
    L.append('LEGACY = {')
    for kit, fams in LEGACY.items():
        L.append(f'    {pr(kit)}: {{')
        for f, ms in fams.items():
            L.append(f'        {pr(f)}: [')
            L += [f'            {pr(m)},' for m in ms]
            L.append('        ],')
        L.append('    },')
    L.append('}')
    open(os.path.join(ROOT, 'ctr_tools', 'track_creator_catalog.py'), 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    print('ecrit track_creator_catalog.py')
