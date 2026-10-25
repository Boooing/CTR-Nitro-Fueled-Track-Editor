"""Lecture des fichiers .igz Alchemy (version 10, PS4 64 bits) de CTR Nitro-Fueled.

Structure :
  0x00  magic 0x015A4749 ('\\x01ZGI'), version (10), hash de type, ?
  0x18  sections : {offset u32, taille u32, alignement u32, ?} ; section 0 = fixups, suivantes = donnees
  fixups : blocs {magic[4], count u32, taille u32, debut des donnees u32}
    TSTR chaines (alignees sur 2)        TMET noms des types        MTSZ tailles des types
    EXNM references externes nommees     RVTB/RSTT/ROFS/RPID/RHND listes d'offsets compressees
    ROOT offset de la liste racine       ONAM offset de la liste des noms des objets racine
  Listes compressees : nibbles (poids faible d'abord), 3 bits de valeur + bit de continuation,
  offset = precedent + valeur * 4.
  Pointeurs 64 bits : section = v >> 27 (0 = premiere section de donnees), offset = v & 0x7FFFFFF.
"""
import bisect
import collections
import json
import os
import struct

MAGIC = 0x49475A01   # octets 01 5A 47 49
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'schema', 'ctr_meta.json')

# Classes du coeur moteur dont les champs ne sont pas declares par le meme mecanisme.
CORE_FIELDS = {
    'igDataList': [('_count', 0x0C, 'igIntMetaField'), ('_capacity', 0x10, 'igIntMetaField'),
                   ('_data', 0x18, 'igMemoryRefMetaField')],
    'igEntity': [('_bolt', 0x10, 'igObjectRefMetaField'), ('_components', 0x18, 'igObjectRefMetaField'),
                 ('_parentSpacePosition', 0x20, 'igVec3fMetaField'), ('_transform', 0x30, 'igObjectRefMetaField'),
                 ('_bitfield', 0x38, 'igUnsignedIntMetaField'), ('_entityData', 0x40, 'igObjectRefMetaField')],
    # noms deduits du nommage des objets (<spline>_data, _floatTracks...) ; _length/_flags d'apres les valeurs
    'igSpline2': [('_data', 0x10, 'igObjectRefMetaField'), ('_floatTracks', 0x48, 'igObjectRefMetaField'),
                  ('_vec3fTracks', 0x50, 'igObjectRefMetaField'), ('_rotationTracks', 0x58, 'igObjectRefMetaField'),
                  ('_events', 0x60, 'igObjectRefMetaField'), ('_length', 0x68, 'igFloatMetaField'),
                  ('_flags', 0x6C, 'igUnsignedIntMetaField')],
    'igHashTable': [('_values', 0x10, 'igMemoryRefMetaField'), ('_keys', 0x20, 'igMemoryRefMetaField'),
                    ('_hashItemCount', 0x30, 'igIntMetaField'), ('_autoRehash', 0x34, 'igBoolMetaField'),
                    ('_loadFactor', 0x38, 'igFloatMetaField')],
}

_schema_cache = None


def load_schema():
    global _schema_cache
    if _schema_cache is None:
        _schema_cache = json.load(open(SCHEMA_PATH)) if os.path.exists(SCHEMA_PATH) else {}
    return _schema_cache


def unpack_offsets(count, data):
    out, prev, pos, hi = [], 0, 0, False

    def nib():
        nonlocal pos, hi
        if not hi:
            hi = True
            return data[pos] & 0xF
        hi = False
        pos += 1
        return data[pos - 1] >> 4

    for _ in range(count):
        c = nib()
        val, sh = c & 7, 3
        while c & 8:
            c = nib()
            val |= (c & 7) << sh
            sh += 3
        prev += val * 4
        out.append(prev)
    return out


def pack_offsets(offsets):
    """Inverse de unpack_offsets (offsets tries, multiples de 4)."""
    nibbles, prev = [], 0
    for o in sorted(offsets):
        val = (o - prev) // 4
        prev = o
        while True:
            n = val & 7
            val >>= 3
            nibbles.append(n | (8 if val else 0))
            if not val:
                break
    if len(nibbles) & 1:
        nibbles.append(0)
    return bytes(nibbles[i] | (nibbles[i + 1] << 4) for i in range(0, len(nibbles), 2))


def encode_strings(strings):
    """Bloc de chaines TSTR/TMET : chaque chaine terminee par 0 et alignee sur 2."""
    out = bytearray()
    for s in strings:
        out += s.encode('latin1') + b'\0'
        if len(out) & 1:
            out += b'\0'
    return bytes(out)


def fnv1a_lower(s):
    h = 0x811C9DC5
    for c in s.lower().encode('latin1'):
        h = ((h ^ c) * 0x01000193) & 0xFFFFFFFF
    return h


COMPRESSED_FIXUPS = ('RVTB', 'RSTT', 'ROFS', 'RPID', 'RHND', 'RNEX', 'REXT', 'RSTR')
# ordre des sections de fixups dans les fichiers du jeu (une section absente peut etre creee : ensure_fixup)
FIXUP_ORDER = ('TDEP', 'TSTR', 'TMET', 'MTSZ', 'EXID', 'EXNM', 'RVTB', 'RSTT', 'ROFS', 'RPID', 'RHND', 'RNEX',
               'REXT', 'RSTR', 'ROOT', 'ONAM')
# paires de u32 : donnees le plus souvent alignees sur 8 dans la section (bourrage avant), ~130 exceptions dans les
# fichiers du jeu (le jeu lit le champ « debut ») : le bourrage d'origine est garde, calcule seulement pour une
# section creee
PAIR_FIXUPS = ('EXID', 'EXNM')


class IgzFile:
    def __init__(self, path_or_bytes):
        b = open(path_or_bytes, 'rb').read() if isinstance(path_or_bytes, str) else path_or_bytes
        self.raw = b
        magic, self.version, self.type_hash = struct.unpack_from('<III', b, 0)
        if magic != MAGIC:
            raise ValueError('pas un fichier IGZ')
        self.sections = []
        self.section_meta = []        # (alignement, champ inconnu) pour la reecriture
        for i in range(32):
            off, size, align, unk = struct.unpack_from('<IIII', b, 0x18 + i * 16)
            if off == 0 and size == 0:
                break
            self.sections.append((off, size))
            self.section_meta.append((align, unk))
        self.fixups = {}
        self.fixup_layout = []        # (magic, octets entre l'en-tete et les donnees) dans l'ordre du fichier
        fo, fs = self.sections[0]
        p = fo
        while p < fo + fs:
            m, cnt, size, start = struct.unpack_from('<4sIII', b, p)
            self.fixups[m.decode('latin1')] = (cnt, b[p + start:p + size])
            self.fixup_layout.append((m.decode('latin1'), b[p + 16:p + start]))
            if size == 0:
                break
            p += size
        self.data = [bytearray(b[o:o + s]) for o, s in self.sections[1:]]
        self.strings = self._strings('TSTR')
        self.types = self._strings('TMET')
        cnt, body = self.fixups.get('MTSZ', (0, b''))
        self.type_sizes = list(struct.unpack_from(f'<{cnt}I', body))
        cnt, body = self.fixups.get('EXNM', (0, b''))
        self._exnm_raw = list(struct.iter_unpack('<II', body[:cnt * 8]))   # reecrites telles quelles
        self.ext_names = [(self.string(a), self.string(c & 0x7FFFFFFF)) for a, c in self._exnm_raw]
        # offset sets (all relative to data section 0 in practice; keep (sec, off) keys)
        self.offset_sets = {}
        for k in ('RVTB', 'RSTT', 'ROFS', 'RPID', 'RHND', 'RNEX', 'REXT', 'RSTR'):
            if k in self.fixups:
                self.offset_sets[k] = set(unpack_offsets(*self.fixups[k]))
        self.objects = {}
        for off in sorted(self.offset_sets.get('RVTB', ())):
            t = struct.unpack_from('<Q', *self._loc(off))[0]
            self.objects[off] = self.types[t]
        root_cnt, root = self.fixups.get('ROOT', (0, b''))
        self.root_offset = struct.unpack_from('<I', root)[0] if root_cnt else None
        onam_cnt, onam = self.fixups.get('ONAM', (0, b''))
        self.names_offset = struct.unpack_from('<I', onam)[0] if onam_cnt else None

    # -- ecriture -------------------------------------------------------------------------
    def find_field(self, obj_off, field_name):
        """(offset absolu, type) d'un champ d'objet, via le schema."""
        for fo, (name, ftype) in self.fields_of(self.objects[obj_off]).items():
            if name == field_name:
                return obj_off + fo, ftype
        raise KeyError(f'{self.objects[obj_off]} n\'a pas de champ {field_name}')

    def set_field(self, obj_off, field_name, value):
        """Modifie un champ scalaire en place (meme taille : la mise en page ne change pas)."""
        off, ftype = self.find_field(obj_off, field_name)
        if off in self.offset_sets.get('ROFS', ()) or off in self.offset_sets.get('RSTT', ()) \
                or off in self.offset_sets.get('RHND', ()):
            raise ValueError(f'{field_name} est un pointeur/chaine/handle : utiliser les fixups')
        if ftype == 'igVec3fMetaField':
            struct.pack_into('<3f', *self._loc(off), *value)
        elif ftype == 'igFloatMetaField':
            struct.pack_into('<f', *self._loc(off), value)
        elif ftype == 'igBoolMetaField':
            self._set_byte(off, 1 if value else 0)
        elif ftype in ('igIntMetaField', 'igEnumMetaField'):
            struct.pack_into('<i', *self._loc(off), value)
        elif ftype == 'igUnsignedIntMetaField':
            struct.pack_into('<I', *self._loc(off), value)
        else:
            raise NotImplementedError(f'ecriture du type {ftype}')

    # -- edition structurelle ------------------------------------------------------------
    def alloc(self, size, align=16, sec=0):
        """Reserve `size` octets a zero en fin de section ; retourne l'offset encode."""
        buf = self.data[sec]
        buf.extend(b'\0' * (-len(buf) % align))
        off = len(buf)
        buf.extend(b'\0' * size)
        return (sec << 27) | off

    def add_string(self, s):
        if s in self.strings:
            return self.strings.index(s)
        self.strings.append(s)
        return len(self.strings) - 1

    def type_index(self, type_name):
        """Index TMET du type, en l'ajoutant (taille issue du schema) s'il est absent."""
        if type_name not in self.types:
            size = load_schema().get(type_name, {}).get('size')
            if size is None:
                raise KeyError(f'type {type_name} inconnu du schema')
            self.types.append(type_name)
            self.type_sizes.append(size)
        return self.types.index(type_name)

    def ensure_fixup(self, magic):
        """Cree une section de fixups absente (vide), a sa place dans l'ordre du jeu. Ex. : RaceSystem de Crash Cove
        sans TDEP / EXID / RNEX, necessaires pour y greffer un script (teleporteur)."""
        if magic in self.fixups:
            return
        self.fixups[magic] = (0, b'')
        rank = FIXUP_ORDER.index(magic)
        at = next((i for i, (m, _) in enumerate(self.fixup_layout)
                   if m in FIXUP_ORDER and FIXUP_ORDER.index(m) > rank), len(self.fixup_layout))
        self.fixup_layout.insert(at, (magic, None))      # bourrage calcule a l'ecriture
        if magic in COMPRESSED_FIXUPS:
            self.offset_sets.setdefault(magic, set())

    def _mark(self, kind, off, on=True):
        if on and kind not in self.fixups:
            self.ensure_fixup(kind)
        s = self.offset_sets.setdefault(kind, set())
        (s.add if on else s.discard)(off)
        self._sorted_cache = None

    def set_ptr(self, off, target):
        """Ecrit un pointeur (offset encode) ou None, et tient ROFS a jour."""
        struct.pack_into('<Q', *self._loc(off), target or 0)
        self._mark('ROFS', off, target is not None)

    def set_string_ref(self, off, s):
        struct.pack_into('<Q', *self._loc(off), self.add_string(s) if s is not None else 0)
        self._mark('RSTT', off, s is not None)

    def new_object(self, type_name):
        """Objet vierge : index de type + refcount a 1 (comme les objets du jeu)."""
        size = self.size_of(type_name)
        off = self.alloc(size, 16)
        struct.pack_into('<QI', *self._loc(off), self.type_index(type_name), 1)
        self._mark('RVTB', off)
        self.objects[off] = type_name
        return off

    def clone_object(self, src):
        """Copie superficielle : memes octets, memes pointeurs/chaines/handles (fixups recopies)."""
        t = self.objects[src]
        size = self.size_of(t)
        off = self.alloc(size, 16)
        sbuf, so = self._loc(src)
        dbuf, do = self._loc(off)
        dbuf[do:do + size] = sbuf[so:so + size]
        for kind, s in self.offset_sets.items():
            for rel in [o - src for o in self._marks_in(kind, src, size)]:
                s.add(off + rel)
        self._sorted_cache = None
        self.objects[off] = t
        return off

    def set_list(self, list_off, items, stride=8):
        """Remplace le contenu d'un igDataList de pointeurs (items = offsets d'objets ou None).

        L'ancien bloc memoire est abandonne (reste dans le fichier, plus reference) ; un nouveau bloc est alloue.
        """
        count, old_size, old_data = self.list_info(list_off)
        if old_data is not None:
            for i in range(count):
                self._mark('ROFS', old_data + i * stride, False)
            self._free(old_data, old_size)
        new_data = self.alloc(max(len(items), 1) * stride, 16) if items else None
        for i, it in enumerate(items):
            self.set_ptr(new_data + i * stride, it)
        struct.pack_into('<II', *self._loc(list_off + 0x0C), len(items), len(items))
        flags = self.u32(list_off + 0x1C)
        struct.pack_into('<II', *self._loc(list_off + 0x18), len(items) * stride, flags)
        self.set_ptr(list_off + 0x20, new_data)

    def list_insert(self, list_off, index, obj):
        items = self.object_list(list_off)
        items.insert(index, obj)
        self.set_list(list_off, items)

    def list_remove(self, list_off, index):
        items = self.object_list(list_off)
        removed = items.pop(index)
        self.set_list(list_off, items)
        return removed

    def _name_entries(self):
        count, _, data = self.list_info(self.names_offset)
        entries = []
        for i in range(count):
            a = data + i * 16
            entries.append((self.string(self.u32(a)) if self.is_str(a) else None, self.u32(a + 8)))
            self._mark('RSTT', a, False)
        return entries

    def add_root(self, obj, name):
        """Ajoute l'objet a la liste racine et lui donne un nom (igNameList : chaine + hash FNV-1a minuscule)."""
        self.add_roots([(obj, name)])

    def add_roots(self, pairs):
        """Ajoute [(objet, nom)] a la liste racine en UNE reecriture : chaque reecriture abandonne l'ancienne liste
        et l'ancienne table des noms dans le fichier (~24 o par racine), d'ou l'interet de grouper."""
        if not pairs:
            return
        roots = self.object_list(self.root_offset)
        self.set_list(self.root_offset, roots + [o for o, _ in pairs])
        entries = self._name_entries()
        entries += [(n, fnv1a_lower(n)) for _, n in pairs]
        self._write_names(entries)

    def remove_roots(self, objs):
        """Retire des objets de la liste racine (et leurs noms). Ils restent dans le fichier, non references."""
        objs = set(objs)
        roots = self.object_list(self.root_offset)
        keep = [i for i, o in enumerate(roots) if o not in objs]
        entries = self._name_entries()
        self.set_list(self.root_offset, [roots[i] for i in keep])
        self._write_names([entries[i] for i in keep if i < len(entries)])

    def _write_names(self, entries):
        _, old_size, old_data = self.list_info(self.names_offset)
        self._free(old_data, old_size)
        new = self.alloc(len(entries) * 16, 16)
        for i, (s, h) in enumerate(entries):
            if s is not None:
                self.set_string_ref(new + i * 16, s)
            struct.pack_into('<I', *self._loc(new + i * 16 + 8), h)
        n = len(entries)
        struct.pack_into('<II', *self._loc(self.names_offset + 0x0C), n, n)
        flags = self.u32(self.names_offset + 0x1C)
        struct.pack_into('<II', *self._loc(self.names_offset + 0x18), n * 16, flags)
        self.set_ptr(self.names_offset + 0x20, new)

    # -- references externes (handles) -----------------------------------------------------
    def ext_index(self, name, namespace):
        """Valeur (sans le bit 31) d'un handle nomme vers 'namespace::name', ajoute s'il est absent : RANG parmi
        les entrees EXNM drapeau 1, pas l'index dans toute la liste (fichiers du jeu : la plus grande valeur est
        toujours inferieure au nombre d'entrees drapeau 1 ; les deux ne different que si une entree drapeau 0 —
        reference RNEX — precede, ex. apres la greffe d'un script)."""
        return self._exnm_add(name, namespace, 1)

    def set_handle_list(self, list_off, handles):
        """Remplace un igDataList de handles par [(nom, espace de noms)] (elements de 8 octets)."""
        count, old_size, old = self.list_info(list_off)
        if old is not None:
            for i in range(count):
                self._mark('RHND', old + i * 8, False)
            self._free(old, old_size)
        new = self.alloc(max(len(handles), 1) * 8, 16) if handles else None
        for i, (name, ns) in enumerate(handles):
            struct.pack_into('<Q', *self._loc(new + i * 8), 0x80000000 | self.ext_index(name, ns))
            self._mark('RHND', new + i * 8)
        struct.pack_into('<II', *self._loc(list_off + 0x0C), len(handles), len(handles))
        flags = self.u32(list_off + 0x1C)
        struct.pack_into('<II', *self._loc(list_off + 0x18), len(handles) * 8, flags)
        self.set_ptr(list_off + 0x20, new)

    def named_handle(self, v):
        """(nom, espace) d'une valeur de handle nomme (bit 31 + rang parmi les entrees EXNM drapeau 1) ou None."""
        if not v & 0x80000000:
            return None
        f1 = self._exnm_flagged(1)
        return f1[v & 0x7FFFFFFF] if (v & 0x7FFFFFFF) < len(f1) else None

    def handle_list(self, list_off):
        count, _, data = self.list_info(list_off)
        return [self.named_handle(self.u32(data + i * 8)) for i in range(count)]

    # -- clonage profond ---------------------------------------------------------------------
    def _sorted(self, kind):
        cache = getattr(self, '_sorted_cache', None)
        if cache is None:
            cache = self._sorted_cache = {}
        if kind not in cache:
            cache[kind] = sorted(self.offset_sets.get(kind, ()))
        return cache[kind]

    def _marks_in(self, kind, start, size):
        lst = self._sorted(kind)
        return lst[bisect.bisect_left(lst, start):bisect.bisect_left(lst, start + size)]

    def _pointers_in(self, start, size):
        return self._marks_in('ROFS', start, size)

    def reachable(self, root):
        """(objets, {debut bloc memoire: taille}) atteignables depuis root via les pointeurs.
        Parametres d'un script (CVscComponentData._dynamicFieldMemory) : le champ de taille ne la donne pas (2 pour
        les 0x30 octets du teleporteur) ; bloc etendu jusqu'a l'objet suivant (comme import_entity), sinon le
        compactage complet coupait les parametres d'un script greffe."""
        objs, mem, stack = set(), {}, [('o', root)]
        starts = None
        while stack:
            kind, o = stack.pop()
            if kind == 'o':
                if o in objs:
                    continue
                objs.add(o)
                span = (o, self.size_of(self.objects[o]))
            else:
                span = (o, mem[o])
            vsc = kind == 'o' and self.objects[o] == 'CVscComponentData'
            for p in self._pointers_in(*span):
                t = self.deref(p)
                if t is None:
                    continue
                if t in self.objects:
                    stack.append(('o', t))
                elif t not in mem:
                    size = self.u32(p - 8) & 0x07FFFFFF   # igMemoryRef / igDataList : taille juste avant
                    if vsc:
                        if starts is None:
                            starts = sorted(self.objects)
                        i = bisect.bisect_right(starts, t)
                        nxt = starts[i] if i < len(starts) and starts[i] >> 27 == t >> 27 else t + 0x100
                        size = max(size, min(nxt - t, 0x1000))
                    mem[t] = size
                    stack.append(('m', t))
        return objs, mem

    def deep_clone_entity(self, entity, new_name, entity_types=('CEntity', 'igEntity')):
        """Duplique une entite et tout ce qui lui est propre (objets/memoire non partages avec d'autres entites).

        Les objets partages (archetypes, bolts...) restent references tels quels. Les noms des objets clones
        sont derives en remplacant le nom de l'entite d'origine par new_name. Retourne l'offset de la copie.
        """
        names = {o: n for n, o in self.root_objects()}
        new, pairs = self.clone_owned(entity, new_name, self.owned_by(entity_types)[entity], names)
        self.add_roots(pairs)
        return new

    def owned_by(self, entity_types):
        """{entite: (objets, {bloc: taille})} propres a chaque entite : atteignables depuis elle seule."""
        ents = [o for o, t in self.objects.items() if t in entity_types]
        reach = {e: self.reachable(e) for e in ents}
        co, cm = collections.Counter(), collections.Counter()
        for ro, rm in reach.values():
            co.update(ro)
            cm.update(rm.keys())          # (update(dict) additionnerait les tailles)
        return {e: ([o for o in ro if co[o] == 1], {m: s for m, s in rm.items() if cm[m] == 1})
                for e, (ro, rm) in reach.items()}

    def clone_owned(self, entity, new_name, owned, names):
        """Clone (objets, blocs) propres a une entite ; retourne (copie, [(objet, nom)] racines a ajouter)."""
        old_name = names.get(entity)
        clone_o, clone_m = sorted(owned[0]), owned[1]
        omap, mmap = {}, {}
        for o in clone_o:
            omap[o] = self.clone_object(o)
        for m, s in sorted(clone_m.items()):
            new = self.alloc(max(s, 1), 16)
            sb, so = self._loc(m)
            db, do = self._loc(new)
            db[do:do + s] = sb[so:so + s]
            for kind, st in self.offset_sets.items():
                for rel in [x - m for x in self._marks_in(kind, m, s)]:
                    st.add(new + rel)
            self._sorted_cache = None
            mmap[m] = new
        # re-cablage des pointeurs dans toutes les copies
        spans = [(n, self.size_of(self.objects[n])) for n in omap.values()] + \
                [(n, clone_m[m]) for m, n in mmap.items()]
        for start, size in spans:
            for p in self._pointers_in(start, size):
                t = self.deref(p)
                if t in omap:
                    self.set_ptr(p, omap[t])
                elif t in mmap:
                    self.set_ptr(p, mmap[t])
        pairs = []
        for o, n in omap.items():
            nm = names.get(o)
            if nm and old_name and nm.startswith(old_name):
                pairs.append((n, new_name + nm[len(old_name):]))
            elif o == entity:
                pairs.append((n, new_name))
        return omap[entity], pairs

    # -- references externes : deux listes melees dans EXNM, plus EXID ------------------------------------
    # EXNM : entrees (nom, espace) avec un drapeau (bit 31 de l'espace) ; drapeau 1 = handles nommes (valeur
    # 0x80000000 | rang parmi les entrees drapeau 1), drapeau 0 = references d'objets RNEX (rang parmi les entrees
    # drapeau 0 ; ex. CVscComponentData._meta -> « common_TurboPad::common_KartBoostData »).
    # EXID : paires (hash du nom, hash de l'espace), handles RHND sans le bit 31 = rang dans EXID (sons, effets...).
    def _exnm_flagged(self, flag):
        return [(self.string(a), self.string(c & 0x7FFFFFFF)) for a, c in self._exnm_raw if (c >> 31) == flag]

    def _exnm_add(self, name, ns, flag):
        lst = self._exnm_flagged(flag)
        if (name, ns) in lst:
            return lst.index((name, ns))
        self._exnm_raw.append((self.add_string(name), self.add_string(ns) | (0x80000000 if flag else 0)))
        self.ext_names.append((name, ns))
        return len(lst)

    def exid_pairs(self):
        cnt, body = self.fixups.get('EXID', (0, b''))
        return [struct.unpack_from('<II', body, i * 8) for i in range(cnt)]

    def exid_index(self, pair):
        pairs = self.exid_pairs()
        if tuple(pair) in pairs:
            return pairs.index(tuple(pair))
        self.ensure_fixup('EXID')
        pairs.append(tuple(pair))
        self.fixups['EXID'] = (len(pairs), b''.join(struct.pack('<II', *p) for p in pairs))
        return len(pairs) - 1

    def import_entity(self, src, entity, new_name, old_name=None):
        """Copie dans CE fichier une entite d'un AUTRE fichier IGZ et tout ce qui lui est propre (objets, blocs
        memoire), en remappant : types (RVTB, tailles du fichier source), pointeurs (ROFS, dans la copie),
        chaines (RSTT), handles (RHND : EXNM drapeau 1 ou EXID), references RNEX (EXNM drapeau 0), RPID tel quel.
        Les objets nommes (racines) sont ajoutes a la liste racine, le nom de l'entite remplace par new_name.
        Retourne l'offset de l'entite copiee."""
        objs, mem = src.reachable(entity)
        # taille reelle des blocs memoire : jusqu'au debut du bloc / objet suivant du fichier source (le champ de
        # taille d'un igRawRef ne la donne pas : memoire dynamique des scripts)
        starts = sorted(set(src.objects) | set(src.reachable(src.root_offset)[1]))
        spans = {}
        for o in objs:
            spans[o] = src.size_of(src.objects[o])
        for m, s in mem.items():
            nxt = next((x for x in starts if x > m), m + max(int(s), 8))
            spans[m] = max(int(s), min(nxt - m, 0x10000))
        omap = {}
        for a in sorted(spans):
            size = spans[a]
            new = self.alloc(max(size, 1), 16)
            sb, so = src._loc(a)
            db, do = self._loc(new)
            db[do:do + size] = sb[so:so + size]
            omap[a] = new
            if a in objs:
                t = src.objects[a]
                if t not in self.types:
                    self.types.append(t)
                    self.type_sizes.append(src.type_sizes[src.types.index(t)])
                self.objects[new] = t
        flag1, flag0, exid = src._exnm_flagged(1), src._exnm_flagged(0), src.exid_pairs()
        for a, size in spans.items():
            base = omap[a]
            for kind in ('RVTB', 'ROFS', 'RSTT', 'RHND', 'RNEX', 'RPID'):
                for p in src._marks_in(kind, a, size):
                    q = base + (p - a)
                    if kind == 'RVTB':
                        struct.pack_into('<Q', *self._loc(q), self.types.index(src.types[src.u64(p) & 0xFFFFFFFF]))
                    elif kind == 'ROFS':
                        tgt = src.deref(p)
                        if tgt not in omap:
                            raise ValueError(f'pointeur hors de l\'entite ({p:#x} -> {tgt}) : copie impossible')
                        self.set_ptr(q, omap[tgt])
                        continue
                    elif kind == 'RSTT':
                        struct.pack_into('<Q', *self._loc(q), self.add_string(src.string(src.u32(p))))
                    elif kind == 'RHND':
                        v = src.u32(p)
                        if v & 0x80000000:
                            nv = 0x80000000 | self._exnm_add(*flag1[v & 0x7FFFFFFF], 1)
                        else:
                            nv = self.exid_index(exid[v])
                        struct.pack_into('<Q', *self._loc(q), nv)
                    elif kind == 'RNEX':
                        struct.pack_into('<Q', *self._loc(q), self._exnm_add(*flag0[src.u64(p)], 0))
                    self._mark(kind, q)
        self._sorted_cache = None
        names = {o: n for n, o in src.root_objects()}
        old = old_name or names.get(entity)
        pairs = [(omap[o], new_name + n[len(old):] if old and n.startswith(old) else n)
                 for o, n in names.items() if o in omap and n]
        self.add_roots(sorted(pairs, key=lambda p: p[0]))
        return omap[entity]

    def add_tdep(self, pairs):
        """Ajoute des dependances de fichiers (nom, chemin) absentes au TDEP ; liste triee comme le jeu (nom puis
        chemin, sans casse), terminateur vide + alignement (encode_tdep)."""
        from model_build import encode_tdep, tdep_entries
        cur = tdep_entries(self)
        new = sorted(set(cur) | set(map(tuple, pairs)), key=lambda p: (p[0].lower(), p[1].lower()))
        if new != cur:
            self.ensure_fixup('TDEP')
            self.fixups['TDEP'] = (len(new), encode_tdep(new))

    def _free(self, off, size):
        """Note un bloc abandonne par une reecriture (ancienne liste, ancienne table de noms) : compact() le
        retirera s'il n'est plus utilise."""
        if off is not None and size:
            self.__dict__.setdefault('_freed', []).append((off, int(size)))

    def compact(self, aggressive=False):
        """Retire de la 1re section de donnees les blocs abandonnes par nos reecritures (`_free`) qui ne sont plus
        atteignables depuis les racines ni vises par un pointeur. aggressive=True : retire tout ce qui n'est pas
        atteignable (fichiers deja gonfles par des versions precedentes) — a reserver aux types de fichiers verifies
        (certains fichiers du jeu ont des donnees utiles non atteignables). Les zones gardees conservent leur
        alignement modulo 16. Pointeurs (ROFS) et racines sont renumerotes. Retourne le nombre d'octets retires."""
        old = self.data[0]
        starts = [o for o in (self.root_offset, self.names_offset) if o is not None]
        objs, mem = set(), {}
        for s in starts:
            o, m = self.reachable(s)
            objs |= o
            mem.update(m)
        live = []
        for a, b in sorted([(o, o + self.size_of(self.objects[o])) for o in objs if o >> 27 == 0]
                           + [(m, m + max(int(s), 0)) for m, s in mem.items() if m >> 27 == 0]):
            if live and a <= live[-1][1]:
                live[-1][1] = max(live[-1][1], b)
            else:
                live.append([a, b])
        # zones visees par un pointeur VIVANT (les dechets se designent entre eux : ca ne compte pas)
        lstarts = [a for a, _ in live]

        def is_live(p):
            i = bisect.bisect_right(lstarts, p) - 1
            return i >= 0 and p < live[i][1]
        targets = sorted(self.u64(p) & ~3 for p in self.offset_sets.get('ROFS', ())
                         if p >> 27 == 0 and is_live(p) and self.u64(p) and (self.u64(p) >> 27) == 0)
        # candidats a retirer : trous entre zones vivantes (agressif) ou blocs liberes, prives des zones vivantes
        if aggressive:
            cand, prev = [], 0
            for a, b in live:
                if a > prev:
                    cand.append((prev, a))
                prev = max(prev, b)
            if prev < len(old):
                cand.append((prev, len(old)))
        else:
            cand = []
            for a, b in sorted((o, o + s) for o, s in getattr(self, '_freed', []) if o >> 27 == 0):
                pieces = [(a, b)]
                for la, lb in live:
                    pieces = [q for pa, pb in pieces for q in ((pa, min(pb, la)), (max(pa, lb), pb)) if q[1] > q[0]]
                cand += pieces
        removals = []
        for a, b in sorted(set(cand)):
            if removals and a < removals[-1][1]:
                a = removals[-1][1]
            i = bisect.bisect_left(targets, a)
            if i < len(targets) and targets[i] < b:
                continue                                   # une zone visee par un pointeur : on la garde
            r = ((b - a) // 16) * 16
            if r:
                removals.append((a, a + r))
        # une zone non vivante mais GARDEE (mode normal : seuls les blocs liberes partent) peut encore viser un bloc
        # libere (RaceSystem de Roo's Tubes : 0x2ae8 -> 0xc700) : ce bloc est garde aussi, jusqu'a stabilite
        ptrs = [(p, self.u64(p) & ~3) for p in self.offset_sets.get('ROFS', ())
                if p >> 27 == 0 and self.u64(p) and (self.u64(p) >> 27) == 0]
        while removals:
            rs = [a for a, _ in removals]
            inside = lambda x: (lambda i: i >= 0 and x < removals[i][1])(bisect.bisect_right(rs, x) - 1)
            hit = {bisect.bisect_right(rs, v) - 1 for p, v in ptrs if not inside(p) and inside(v)}
            if not hit:
                break
            removals = [r for i, r in enumerate(removals) if i not in hit]
        self.__dict__['_freed'] = []
        if not removals:
            return 0
        rstarts = [a for a, _ in removals]
        cum = [0]
        for a, b in removals:
            cum.append(cum[-1] + (b - a))

        def remap(off):
            if off >> 27 or off > len(old):                # autre section, ou valeur qui n'est pas une adresse
                return off
            i = bisect.bisect_right(rstarts, off) - 1
            if i >= 0 and off < removals[i][1]:
                return None
            return off - cum[i + 1]
        buf, prev = bytearray(), 0
        for a, b in removals:
            buf += old[prev:a]
            prev = b
        buf += old[prev:]
        self.data[0] = buf
        for kind, st in self.offset_sets.items():
            self.offset_sets[kind] = {r for r in (remap(o) for o in st) if r is not None}
        for p in self.offset_sets.get('ROFS', ()):
            v = self.u64(p)
            if v and (v >> 27) == 0:
                nv = remap(v)
                if nv is None:
                    raise ValueError(f'pointeur vers une zone retiree ({p:#x} -> {v:#x})')
                struct.pack_into('<Q', *self._loc(p), nv)
        self.objects = {remap(o): t for o, t in self.objects.items() if remap(o) is not None}
        for attr, magic in (('root_offset', 'ROOT'), ('names_offset', 'ONAM')):
            cur = getattr(self, attr)
            if cur is not None:
                setattr(self, attr, remap(cur))
                cnt, body = self.fixups[magic]
                self.fixups[magic] = (cnt, struct.pack('<I', remap(cur)) + body[4:])
        self._sorted_cache = None
        return len(old) - len(buf)

    def to_bytes(self):
        """Reconstruit le fichier : fixups (listes compressees re-encodees) + sections de donnees."""
        fix = bytearray()
        for magic, gap in self.fixup_layout:
            cnt, body = self.fixups[magic]
            if magic == 'TSTR':
                cnt, body = len(self.strings), encode_strings(self.strings)
            elif magic == 'TMET':
                cnt, body = len(self.types), encode_strings(self.types)
            elif magic == 'MTSZ':
                cnt, body = len(self.type_sizes), struct.pack(f'<{len(self.type_sizes)}I', *self.type_sizes)
            elif magic == 'EXNM':
                cnt = len(self.ext_names)
                raw = self._exnm_raw + [(self.strings.index(n), self.strings.index(ns) | 0x80000000)
                                        for n, ns in self.ext_names[len(self._exnm_raw):]]
                body = b''.join(struct.pack('<II', a, c) for a, c in raw)
            elif magic in COMPRESSED_FIXUPS:
                offs = sorted(self.offset_sets[magic])
                cnt, body = len(offs), pack_offsets(offs)
            if gap is None:                              # section creee par ensure_fixup : bourrage le plus courant
                gap = b'\0' * (-(len(fix) + 16) % 8 if magic in PAIR_FIXUPS else 0)
            start = 16 + len(gap)
            size = start + len(body)
            size += -size & 3
            fix += struct.pack('<4sIII', magic.encode('latin1'), cnt, size, start) + gap + body
            fix += b'\0' * (size - start - len(body))
        blobs = [bytes(fix)] + [bytes(d) for d in self.data]
        out = bytearray(self.raw[:self.sections[0][0]])   # en-tete d'origine (contient d'autres champs apres la table)
        struct.pack_into('<I', out, 0x10, len(self.fixup_layout))       # nombre de sections de fixups
        pos = self.sections[0][0]
        layout = []
        for i, blob in enumerate(blobs):
            align = self.section_meta[i][0]     # alignement en memoire ; dans le fichier les sections se suivent
            layout.append((pos, len(blob)))
            struct.pack_into('<IIII', out, 0x18 + i * 16, pos, len(blob), align, self.section_meta[i][1])
            pos += len(blob)
        for (p, _), blob in zip(layout, blobs):
            out += b'\0' * (p - len(out)) + blob
        return bytes(out)

    def save(self, path):
        with open(path, 'wb') as f:
            f.write(self.to_bytes())

    # -- helpers ---------------------------------------------------------------------------
    def _strings(self, key):
        cnt, body = self.fixups.get(key, (0, b''))
        out, o = [], 0
        for _ in range(cnt):
            e = body.index(b'\0', o)
            out.append(body[o:e].decode('latin1'))
            o = e + 1
            if o & 1:
                o += 1
        return out

    def string(self, i):
        return self.strings[i] if 0 <= i < len(self.strings) else None

    # Tous les offsets (fixups, pointeurs, cles d'objets) sont encodes : section << 27 | offset local.
    def _loc(self, off):
        return self.data[off >> 27], off & 0x7FFFFFF

    def _byte(self, off):
        buf, o = self._loc(off)
        return buf[o]

    def _set_byte(self, off, v):
        buf, o = self._loc(off)
        buf[o] = v

    def u32(self, off):
        return struct.unpack_from('<I', *self._loc(off))[0]

    def u64(self, off):
        return struct.unpack_from('<Q', *self._loc(off))[0]

    def f32(self, off):
        return struct.unpack_from('<f', *self._loc(off))[0]

    def vec3(self, off):
        return list(struct.unpack_from('<3f', *self._loc(off)))

    @staticmethod
    def ptr_target(v):
        return v >> 27, v & 0x7FFFFFF

    def is_ptr(self, off):
        return off in self.offset_sets.get('ROFS', ())

    def is_str(self, off):
        return off in self.offset_sets.get('RSTT', ())

    def is_handle(self, off):
        return off in self.offset_sets.get('RHND', ())

    def deref(self, off):
        """Return target offset of the pointer stored at off, or None."""
        if not self.is_ptr(off):
            return None
        v = self.u64(off)
        return v if (v >> 27) < len(self.data) else None   # meme encodage que les offsets

    def handle(self, off):
        v = self.u32(off)
        h = self.named_handle(v)
        if h:
            return f'{h[1]}::{h[0]}'
        return f'handle#{v:#x}'

    def list_info(self, off):
        """igDataList : (count, memory size, data offset)."""
        count = self.u32(off + 0x0C)
        size = self.u32(off + 0x18)
        return count, size, self.deref(off + 0x20)

    def object_list(self, off):
        count, _, data = self.list_info(off)
        if data is None:
            return []
        return [self.deref(data + i * 8) for i in range(count)]

    def root_objects(self):
        """[(name, offset)] des objets racine."""
        objs = self.object_list(self.root_offset) if self.root_offset is not None else []
        names = []
        if self.names_offset is not None:
            count, _, data = self.list_info(self.names_offset)
            names = [self.string(self.u32(data + i * 16)) if self.is_str(data + i * 16) else None
                     for i in range(count)]
        return [(names[i] if i < len(names) else None, o) for i, o in enumerate(objs)]

    # -- schema ------------------------------------------------------------------------------
    def fields_of(self, type_name):
        schema = load_schema()
        chain, n = [], type_name
        while n:
            chain.append(n)
            n = schema.get(n, {}).get('parent')
        fields = {}
        for c in reversed(chain):
            for name, off, t in CORE_FIELDS.get(c, []):
                fields[off] = (name, t)
            for f in schema.get(c, {}).get('fields', []):
                if f['offset'] == 0 and f['name'] != '_vtable':
                    continue      # proprietes sans stockage
                if f['type'] in ('igBitFieldMetaField',):
                    continue      # bitfields : stockage partage, on garde le champ porteur
                fields.setdefault(f['offset'], (f['name'], f['type']))
        return dict(sorted(fields.items()))

    def size_of(self, type_name):
        if type_name in self.types:
            return self.type_sizes[self.types.index(type_name)]
        return load_schema().get(type_name, {}).get('size', 0x10)

    def memory_ref(self, off):
        """igMemoryRef {u32 taille, u32 drapeaux, pointeur} -> (offset des donnees ou None, taille)."""
        return self.deref(off + 8), self.u32(off) & 0x07FFFFFF

    def read_value(self, off, ftype, size_hint):
        if ftype == 'igMemoryRefMetaField' and not self.is_ptr(off):
            data, size = self.memory_ref(off)
            return {'@mem': f'{data:#x}', 'size': size} if data is not None else None
        if self.is_ptr(off):
            tgt = self.deref(off)
            if tgt is None:
                return None
            return {'@ref': f'{tgt:#x}'} if tgt in self.objects else {'@mem': f'{tgt:#x}'}
        if self.is_str(off):
            return self.string(self.u32(off))
        if self.is_handle(off):
            return {'@handle': self.handle(off)}
        if ftype == 'igVec3fMetaField':
            return [round(x, 4) for x in self.vec3(off)]
        if ftype in ('igFloatMetaField',):
            return round(self.f32(off), 6)
        if ftype in ('igBoolMetaField',):
            return bool(self._byte(off))
        if ftype in ('igObjectRefMetaField', 'igMemoryRefMetaField', 'igStringMetaField', 'igHandleMetaField'):
            return None
        if ftype in ('igUnsignedShortMetaField', 'igShortMetaField'):
            return struct.unpack_from('<H' if 'Unsigned' in ftype else '<h', *self._loc(off))[0]
        if ftype in ('igUnsignedCharMetaField', 'igCharMetaField'):
            return self._byte(off)
        if size_hint >= 4:
            v = self.u32(off)
            if ftype in ('igIntMetaField', 'igEnumMetaField', 'igUnsignedIntMetaField', 'igLongMetaField'):
                return v if 'Unsigned' in ftype or v < 0x80000000 else v - 0x100000000
            return guess_scalar(v)
        return self._byte(off)

    def dump_object(self, off):
        t = self.objects[off]
        size = self.size_of(t)
        fields = self.fields_of(t)
        out = {'@off': f'{off:#x}', '@type': t}
        offs = sorted(o for o in fields if o < size)
        covered = set()
        for i, fo in enumerate(offs):
            nxt = offs[i + 1] if i + 1 < len(offs) else size
            name, ft = fields[fo]
            out[name] = self.read_value(off + fo, ft, nxt - fo)
            span = 12 if ft == 'igVec3fMetaField' else max(1, min(nxt - fo, 8 if self.is_ptr(off + fo) else nxt - fo))
            covered.update(range(fo, fo + span))
        # bytes not described by the schema (core classes) : decode by fixup / heuristic
        o = 8
        while o + 4 <= size:
            if o not in covered and self.u32(off + o) or self.is_ptr(off + o) and o not in covered:
                if o not in covered:
                    out[f'_{o:#x}'] = self.read_value(off + o, None, 8 if self.is_ptr(off + o) else 4)
                    if self.is_ptr(off + o):
                        o += 8
                        continue
            o += 4
        chain = self._chain(t)
        if 'igDataList' in chain:
            out['@items'] = self.list_items(off, t)
        elif 'igHashTable' in chain:
            out['@items'] = {k: v for k, v in self.hash_items(off)}
        return out

    def hash_items(self, off):
        """igHashTable : [(cle, valeur)] des cases occupees (valeurs = memoire a +0x10, cles a +0x20)."""
        vsize, vdata = self.u32(off + 0x10), self.deref(off + 0x18)
        ksize, kdata = self.u32(off + 0x20), self.deref(off + 0x28)
        if vdata is None or kdata is None:
            return []
        n = min(vsize, ksize) // 8
        items = []
        for i in range(n):
            ka, va = kdata + i * 8, vdata + i * 8
            if self.is_str(ka):
                key = self.string(self.u32(ka))
            elif self.u64(ka) in (0, 0xFFFFFFFFFFFFFFFF):
                continue
            else:
                key = f'{self.u64(ka):#x}'
            tgt = self.deref(va)
            items.append((key, {'@ref': f'{tgt:#x}'} if tgt in self.objects else
                          ({'@mem': f'{tgt:#x}'} if tgt is not None else self.u64(va))))
        return items

    def _chain(self, t):
        schema, n, c = load_schema(), t, []
        while n:
            c.append(n)
            n = schema.get(n, {}).get('parent')
        return c

    def list_items(self, off, t):
        count, size, data = self.list_info(off)
        if data is None or count == 0:
            return []
        stride = size // count if count else 0
        items = []
        for i in range(count):
            a = data + i * stride
            if stride == 8 and self.is_ptr(a):
                tgt = self.deref(a)
                items.append({'@ref': f'{tgt:#x}'} if tgt in self.objects else {'@mem': f'{tgt:#x}'})
            elif stride >= 4 and self.is_str(a):
                items.append(self.string(self.u32(a)))
            elif stride >= 4 and self.is_handle(a):
                items.append({'@handle': self.handle(a)})
            elif stride == 12:
                items.append([round(x, 4) for x in self.vec3(a)])
            else:
                items.append([guess_scalar(self.u32(a + k)) for k in range(0, stride, 4)])
        return items

    def dump(self):
        names = {o: n for n, o in self.root_objects()}
        objs = []
        for off in self.objects:
            d = self.dump_object(off)
            if off in names and names[off]:
                d['@name'] = names[off]
            objs.append(d)
        return {
            'version': self.version,
            'types': [{'name': n, 'size': s} for n, s in zip(self.types, self.type_sizes)],
            'external': [f'{ns}::{n}' for n, ns in self.ext_names],
            'objects': objs,
        }


def guess_scalar(v):
    """Heuristique pour les octets non decrits : flottant plausible sinon entier."""
    if v == 0:
        return 0
    f = struct.unpack('<f', struct.pack('<I', v))[0]
    e = (v >> 23) & 0xFF
    if 0x60 < e < 0x9F:
        return round(f, 5)
    return v if v < 0x80000000 else v - 0x100000000
