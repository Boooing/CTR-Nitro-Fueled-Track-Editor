"""Lecture des packfiles binaires Havok (hk_2014.1.0-r1, 64 bits little endian) de CTR Nitro-Fueled.

En-tete (0x40 + 0x10 en version 11) : magic 57E0E057 10C0C010, userTag, version (11),
layout (taille pointeur 8, LE, ...), nombre de sections, section/offset du contenu, version texte.
Sections (0x40 chacune) : nom[19], debut absolu, puis offsets relatifs des fixups locaux / globaux /
virtuels, exports, imports, fin.
  fixups locaux   (src, dst)              : pointeur a src -> donnees+dst (meme section)
  fixups globaux  (src, section, dst)     : pointeur vers une autre section
  fixups virtuels (src, section, nom)     : objet a src, classe nommee dans __classnames__
"""
import struct


class Packfile:
    def __init__(self, path_or_bytes):
        b = open(path_or_bytes, 'rb').read() if isinstance(path_or_bytes, str) else path_or_bytes
        self.raw = b
        m0, m1, self.user_tag, self.version = struct.unpack_from('<IIII', b, 0)
        if (m0, m1) != (0x57E0E057, 0x10C0C010):
            raise ValueError('pas un packfile Havok')
        self.layout = b[0x10:0x14]
        nsec, self.contents_sec, self.contents_off, self.contents_cn_sec, self.contents_cn_off = \
            struct.unpack_from('<iiiii', b, 0x14)
        self.contents_version = b[0x28:0x38].split(b'\0')[0].decode()
        hdr = 0x40 + (0x10 if self.version >= 11 else 0)
        sec_size = 0x40 if self.version >= 11 else 0x30
        self.sections = []
        for i in range(nsec):
            o = hdr + i * sec_size
            name = b[o:o + 19].split(b'\0')[0].decode()
            start, loc, glob, virt, exp, imp, end = struct.unpack_from('<7I', b, o + 0x14)
            self.sections.append({'name': name, 'start': start, 'local': loc, 'global': glob,
                                  'virtual': virt, 'exports': exp, 'imports': imp, 'end': end})
        self.classnames = {}
        cn = self.section('__classnames__')
        p, end = cn['start'], cn['start'] + cn['local']
        while p + 5 < end:
            sig, tag = struct.unpack_from('<IB', b, p)
            if sig == 0xFFFFFFFF:
                break
            e = b.index(b'\0', p + 5)
            self.classnames[p + 5 - cn['start']] = b[p + 5:e].decode()
            p = e + 1
        d = self.section('__data__')
        self.data_start = d['start']
        self.data = b[d['start']:d['start'] + d['local']]
        self.local = {}
        for i in range(d['local'], d['global'] - 7, 8):
            src, dst = struct.unpack_from('<ii', b, d['start'] + i)
            if src != -1:
                self.local[src] = dst
        self.global_ = {}
        for i in range(d['global'], d['virtual'] - 11, 12):
            src, sec, dst = struct.unpack_from('<iii', b, d['start'] + i)
            if src != -1:
                self.global_[src] = (sec, dst)
        self.objects = {}
        for i in range(d['virtual'], d['exports'] - 11, 12):
            src, sec, nm = struct.unpack_from('<iii', b, d['start'] + i)
            if src != -1:
                self.objects[src] = self.classnames.get(nm, f'?{nm:#x}')

    def section(self, name):
        return next(s for s in self.sections if s['name'] == name)

    # -- lecture -------------------------------------------------------------------------
    def ptr(self, off):
        """Cible (dans __data__) du pointeur stocke a off, ou None."""
        if off in self.local:
            return self.local[off]
        if off in self.global_:
            sec, dst = self.global_[off]
            if self.sections[sec]['name'] == '__data__':
                return dst
        return None

    def u8(self, o):
        return self.data[o]

    def u16(self, o):
        return struct.unpack_from('<H', self.data, o)[0]

    def u32(self, o):
        return struct.unpack_from('<I', self.data, o)[0]

    def i32(self, o):
        return struct.unpack_from('<i', self.data, o)[0]

    def u64(self, o):
        return struct.unpack_from('<Q', self.data, o)[0]

    def f32(self, o):
        return struct.unpack_from('<f', self.data, o)[0]

    def floats(self, o, n):
        return list(struct.unpack_from(f'<{n}f', self.data, o))

    def array(self, o):
        """hkArray {T* data; int size; int capacityAndFlags} -> (offset des donnees, taille)."""
        return self.ptr(o), self.i32(o + 8)

    def cstr(self, o):
        t = self.ptr(o)
        if t is None:
            return None
        return self.data[t:self.data.index(b'\0', t)].decode('latin1')

    def arrays(self):
        """Tous les hkArray plausibles : pointeur fixe + taille >0 + capacite avec drapeau 0x80000000."""
        out = []
        for src, dst in sorted(self.local.items()):
            if src + 16 > len(self.data):
                continue
            size, cap = struct.unpack_from('<iI', self.data, src + 8)
            if size > 0 and cap & 0x80000000 and (cap & 0x3FFFFFFF) == size:
                out.append((src, dst, size))
        return out
