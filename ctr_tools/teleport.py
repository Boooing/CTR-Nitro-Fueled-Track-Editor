"""Teleporteurs : mecanisme de Spyro Circuit (T503) et Hyper Spaceway (T255).

Une transition de spline du RaceSystem devient un teleporteur :
  * CRaceTrackSplineTransitionComponentData._isTeleporter = vrai (le classement accepte le saut) ;
  * un 3e composant dans la table de composants de ses donnees : le script « common_teleport_entity »
    (vsc/common/Octane/T255_Hyper_Spaceway/common_teleport_entity.igz, CTeleportNodes::teleportEntity2), cle
    « instance_Scripts.Graph.common_teleport_entityData ». Memoire de ses parametres : +0x10 handle de l'entite
    d'arrivee, +0x18 = 1 (Hyper Spaceway : 0 sur le seul teleporteur sans effet), +0x20 handle de l'effet joue sur
    le pilote (ctr_t255_portal_driver_warp, EXID) ;
  * l'arrivee = une entite sans composant du _Design (Spyro : Destination_01, comme un point de reapparition),
    designee depuis le RaceSystem par un handle nomme (EXNM drapeau 1, espace « <Piste>_Design ») — comme les
    points de reapparition, valide en jeu.
Le kart qui entre dans la zone de la transition est deplace sur l'arrivee. Sur Spyro Circuit, l'arrivee est dans la
section suivante (la spline de position suivante relie le portail a l'arrivee), juste avant la transition suivante.

Table de composants (igComponentDataTable) : table de hachage a sondage lineaire, capacite = 2 x nombre de
composants, place = FNV-1a (cle en minuscules) % capacite (verifie sur 216 tables du jeu, 529 cles).
Donneur du composant : Teleporter_04 du _Design de Hyper Spaceway (archive de piste directement lisible ; Spyro
Circuit est dans une archive imbriquee dans update2.pak)."""
import struct

from igz import IgzFile, fnv1a_lower

DONOR = ('t255_hyper_spaceway.pak', 'maps/Octane/T255_Hyper_Spaceway/T255_Hyper_Spaceway_Design.igz', 'Teleporter_04')
KEY = 'instance_Scripts.Graph.common_teleport_entityData'
TRANSITION_KEY = 'instance_CRaceTrackSplineTransitionComponentData'
TRIGGER_KEY = 'instance_CTriggerVolumeBoxComponentData'
# zone de declenchement : les teleporteurs du jeu (Spyro, Hyper Spaceway) envoient l'entree d'un kart a l'entite
# (le script ne recoit rien sinon) ; les transitions ordinaires de Crash Cove ont ces deux champs a faux. Premier
# essai en jeu sans eux : aucune teleportation.
TRIGGER_EVENTS = ('_sendEventsToEntity', '_triggerCausesTouch')
DEST_PREFIX = 'Teleport_Arrival_'
P_DEST, P_FLAG, P_VFX = 0x10, 0x18, 0x20
TDEP = [('common_teleport_entity', 'vsc:/common/Octane/T255_Hyper_Spaceway/common_teleport_entity.igz'),
        ('ctr_t255_portal_driver_warp', 'vfx:/CTR/levels/ctr_t255_portal_driver_warp.igz')]
# fichiers a declarer dans le manifeste de la piste (et a copier s'ils ne sont que dans l'archive de Hyper Spaceway)
FILES = [('vsc', 'vsc/common/octane/t255_hyper_spaceway/common_teleport_entity.igz'),
         ('effect', 'vfx/ctr/levels/ctr_t255_portal_driver_warp.igz'),
         ('model', 'models/vfx/ctr/t255_portal.igz'),
         ('material_instances', 'materialinstances/vfx/ctr/fx_mat_t255_portal_materials,t255_portal,20.igz'),
         ('texture', 'textures/colormap,textures@!vfx!ctr!fxt_t255_portal`tga,111.igz'),
         ('texture', 'textures/colormap,textures@!default_c`png,111.igz'),
         ('texture', 'textures/colormap,textures@!vfx!dirt!fxt_basicshardsdebrissheet`tga,111.igz')]


def dest_name(transition):
    return DEST_PREFIX + transition


def table_of(z, ent):
    data = z.deref(ent + 0x40)
    return z.deref(data + 0x10) if data is not None else None


def table_items(z, table):
    """[(cle, composant)] de la table."""
    return [(k, int(v['@ref'], 16)) for k, v in z.hash_items(table) if isinstance(v, dict) and '@ref' in v]


def write_table(z, table, items):
    """Reecrit la table : nouveaux blocs cles / valeurs (capacite 2 x n, places par hachage), anciens abandonnes."""
    cap = max(2, 2 * len(items))
    slots = [None] * cap
    for key, comp in items:
        i = fnv1a_lower(key) % cap
        while slots[i] is not None:
            i = (i + 1) % cap
        slots[i] = (key, comp)
    for field, stride_kind in (('_keys', 'RSTT'), ('_values', 'ROFS')):
        off = z.find_field(table, field)[0]
        old, old_size = z.memory_ref(off)
        if old is not None:
            for i in range(old_size // 8):
                z._mark(stride_kind, old + i * 8, False)
            z._free(old, old_size)
        new = z.alloc(cap * 8, 16)
        for i, s in enumerate(slots):
            if s is None:
                continue
            if field == '_keys':
                z.set_string_ref(new + i * 8, s[0])
            else:
                z.set_ptr(new + i * 8, s[1])
        head = z.u32(off)
        struct.pack_into('<I', *z._loc(off), (head & ~0x07FFFFFF & 0xFFFFFFFF) | (cap * 8))
        z.set_ptr(off + 8, new)
    struct.pack_into('<i', *z._loc(z.find_field(table, '_hashItemCount')[0]), len(items))


def donor(read):
    """(IgzFile, composant script) du teleporteur modele. read(chemin logique, archive) -> octets."""
    pak, logical, name = DONOR
    z = IgzFile(read(logical, pak))
    ent = next(o for n, o in z.root_objects() if n == name)
    return z, dict(table_items(z, table_of(z, ent)))[KEY]


def _params(z, comp):
    """Debut de la memoire des parametres du script (donnees dynamiques du CVscComponentData)."""
    return int(z.dump_object(comp)['_dynamicFieldMemory']['@mem'], 16)


def read_teleporters(z, entities):
    """{transition: nom de l'entite d'arrivee (ou None)} des transitions teleporteurs. entities = {nom: entite}."""
    out = {}
    for name, ent in entities.items():
        table = table_of(z, ent)
        comp = dict(table_items(z, table)).get(KEY) if table is not None else None
        if comp is None:
            continue
        h = z.named_handle(z.u32(_params(z, comp) + P_DEST))
        out[name] = h[0] if h else None
    return out


def set_teleporter(z, ent, name, arrival, design_ns, src):
    """Fait de la transition `name` (entite ent) un teleporteur vers l'entite `arrival` du _Design (espace
    design_ns). src = donor(...). Composant deja present : seule l'arrivee change."""
    table = table_of(z, ent)
    items = table_items(z, table)
    comp = dict(items).get(KEY)
    if comp is None:
        dz, dcomp = src
        comp = z.import_entity(dz, dcomp, name, old_name=DONOR[2])
        write_table(z, table, items + [(KEY, comp)])
    mem = _params(z, comp)
    struct.pack_into('<Q', *z._loc(mem + P_DEST), 0x80000000 | z.ext_index(arrival, design_ns))
    tcomp = dict(items)[TRANSITION_KEY]
    z.set_field(tcomp, '_isTeleporter', True)
    set_trigger_events(z, ent, True)
    z.add_tdep(TDEP)


def set_trigger_events(z, ent, on):
    """Evenements de la zone de declenchement transmis a l'entite (indispensables au script) ou non."""
    trig = dict(table_items(z, table_of(z, ent))).get(TRIGGER_KEY)
    if trig is None:
        return False
    changed = False
    for f in TRIGGER_EVENTS:
        if z.dump_object(trig).get(f) != on:
            z.set_field(trig, f, on)
            changed = True
    return changed


def clear_teleporter(z, ent):
    """Transition ordinaire de nouveau : composant script retire de la table (et de la liste racine)."""
    table = table_of(z, ent)
    items = table_items(z, table)
    comp = dict(items).get(KEY)
    if comp is None:
        return False
    write_table(z, table, [(k, c) for k, c in items if k != KEY])
    z.remove_roots([comp])
    z.set_field(dict(items)[TRANSITION_KEY], '_isTeleporter', False)
    set_trigger_events(z, ent, False)
    return True
