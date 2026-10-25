"""Reecriture de packfiles Havok (hk_2014.1) : remplacement de tableaux et ajout de blocs.

Principe « ajout en fin » : les nouveaux blocs sont ajoutes a la fin des donnees de la section __data__,
les pointeurs (fixups locaux src -> dst) sont rediriges ; les anciens blocs restent, non references.
Les tables de fixups (locales 8 o, globales 12 o, virtuelles 12 o, remplies de 0xFF jusqu'a 16 o) sont
reconstruites, puis les offsets de la section dans l'en-tete. Sans modification, to_bytes() == original.
"""
import struct

from havok import Packfile


class PackfileWriter:
    def __init__(self, raw):
        self.raw = bytes(raw)
        self.pf = Packfile(self.raw)
        self.sec_index = next(i for i, s in enumerate(self.pf.sections) if s['name'] == '__data__')
        s = self.pf.sections[self.sec_index]
        self.sec = s
        start = s['start']
        self.data = bytearray(self.raw[start:start + s['local']])

        def table(begin, end, size, fmt):
            out = []
            for o in range(begin, end - size + 1, size):
                e = struct.unpack_from(fmt, self.raw, start + o)
                if e[0] != -1:
                    out.append(list(e))
            return out
        self.local = table(s['local'], s['global'], 8, '<ii')
        self.global_ = table(s['global'], s['virtual'], 12, '<iii')
        self.virtual = table(s['virtual'], s['exports'], 12, '<iii')
        self.tail = self.raw[start + s['exports']:start + s['end']]          # exports + imports (bruts)
        self.tail_split = s['imports'] - s['exports']
        self._local_index = {e[0]: n for n, e in enumerate(self.local)}

    # -- edition ------------------------------------------------------------------------------
    def append(self, blob, align=16):
        self.data += b'\0' * (-len(self.data) % align)
        off = len(self.data)
        self.data += blob
        return off

    def write(self, off, blob):
        self.data[off:off + len(blob)] = blob

    def set_pointer(self, src, dst):
        """Pointeur local a src -> dst (None : pointeur nul)."""
        if dst is None:
            if src in self._local_index:
                self.local[self._local_index[src]][1] = -1      # entree neutralisee
            struct.pack_into('<Q', self.data, src, 0)
            return
        if src in self._local_index:
            self.local[self._local_index[src]][1] = dst
        else:
            self._local_index[src] = len(self.local)
            self.local.append([src, dst])

    def set_array(self, field, blob, count, align=16):
        """hkArray a `field` : nouvelles donnees (ajoutees en fin), taille et capacite (drapeau 0x80000000)."""
        if count:
            self.set_pointer(field, self.append(blob, align))
        else:
            self.set_pointer(field, None)
        struct.pack_into('<iI', self.data, field + 8, count, (count | 0x80000000) if count else 0x80000000)

    # -- serialisation -----------------------------------------------------------------------
    def to_bytes(self):
        def pad16(b):
            return b + b'\xff' * (-len(b) % 16)
        data = bytes(self.data) + b'\0' * (-len(self.data) % 16)
        loc = pad16(b''.join(struct.pack('<ii', s, d) for s, d in self.local if d != -1))
        glo = pad16(b''.join(struct.pack('<iii', *e) for e in self.global_))
        vir = pad16(b''.join(struct.pack('<iii', *e) for e in self.virtual))
        body = data + loc + glo + vir + self.tail
        out = bytearray(self.raw[:self.sec['start']])
        o_local = len(data)
        o_global = o_local + len(loc)
        o_virtual = o_global + len(glo)
        o_exports = o_virtual + len(vir)
        o_imports = o_exports + self.tail_split
        o_end = o_exports + len(self.tail)
        hdr = 0x40 + (0x10 if self.pf.version >= 11 else 0)
        sec_size = 0x40 if self.pf.version >= 11 else 0x30
        struct.pack_into('<6I', out, hdr + self.sec_index * sec_size + 0x18,
                         o_local, o_global, o_virtual, o_exports, o_imports, o_end)
        return bytes(out) + body
