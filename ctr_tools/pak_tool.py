"""Crash Team Racing Nitro-Fueled - outil d'archives .pak (Alchemy IGA v13).

Usage :
    python pak_tool.py info    <archive.pak>
    python pak_tool.py list    <archive.pak> [filtre]
    python pak_tool.py extract <archive.pak> <dossier_sortie> [filtre]
    python pak_tool.py replace <archive.pak> <sortie.pak> <nom/logique.igz>=<fichier> [...]
    python pak_tool.py install   <archive.pak> <nom/logique.igz>=<fichier> [...]   (en place, reversible)
    python pak_tool.py uninstall <archive.pak>                                     (restaure l'original exact)

Format (deduit de t111_crash_cove.pak) :
    0x00  'IGA\\x1A', version (13)
    0x08  taille de la TOC, nombre de fichiers, taille de secteur (0x800)
    0x14  diviseur / slop de recherche par hash
    0x1C  nombre de blocs large (u32) / medium (u16) / small (u8)
    0x28  offset (u64) et taille (u32) de la table des noms, flags
    0x38  hashes des noms (u32, tries), puis une entree de 16 octets par fichier :
          offset u40 | ordinal u24 | taille decompressee u32 | type << 28 | index de bloc
    puis les tables de blocs large / medium / small.

Les fichiers sont decoupes en blocs de 0x8000 octets. Chaque fichier occupe nb_blocs + 1 entrees
dans une table de blocs (la derniere marque la fin) : bit haut = bloc compresse,
bits restants = offset en secteurs depuis le debut du fichier. La table small (u8) sert quand le
fichier tient en 0x7F secteurs, sinon la medium (u16), sinon la large (u32).
Type 2 = LZMA (u32 taille compressee, 5 octets de proprietes, flux brut), type 0xF = non compresse.
"""
import fnmatch
import json
import lzma
import os
import re
import shutil
import struct
import threading
import sys
from dataclasses import dataclass

BLOCK_SIZE = 0x8000
TYPE_LZMA = 2
TYPE_NONE = 0xF


@dataclass
class Entry:
    index: int
    name: str
    logical_name: str
    offset: int
    ordinal: int
    size: int
    ctype: int
    block_index: int
    name_hash: int


class IgaArchive:
    def __init__(self, path, fileobj=None):
        self.path = path
        self.f = fileobj or open(path, 'rb')
        hdr = self.f.read(0x38)
        (magic, self.version, toc_size, n, self.sector, self.hash_div, self.hash_slop,
         nl, nm, ns, name_off, name_size, self.flags) = struct.unpack('<4sIIIIIIIIIQII', hdr)
        if magic != b'IGA\x1a':
            raise ValueError(f'{path}: pas une archive IGA')
        if self.version != 13:
            print(f'attention : version IGA {self.version} non testee', file=sys.stderr)
        self.f.seek(0)
        toc = self.f.read(0x38 + toc_size)
        hashes = struct.unpack_from(f'<{n}I', toc, 0x38)
        eo = 0x38 + n * 4
        bo = eo + n * 16
        self.large = struct.unpack_from(f'<{nl}I', toc, bo)
        bo += nl * 4
        self.medium = struct.unpack_from(f'<{nm}H', toc, bo)
        bo += nm * 2
        self.small = toc[bo:bo + ns]

        self.f.seek(name_off)
        names = self.f.read(name_size)
        name_offs = struct.unpack_from(f'<{n}I', names, 0)

        def cstr(o):
            return names[o:names.index(b'\0', o)].decode('utf-8', 'replace')

        self.entries = []
        for i in range(n):
            a, b, size, blk = struct.unpack_from('<IIII', toc, eo + i * 16)
            full = cstr(name_offs[i])
            logical = cstr(name_offs[i] + len(full.encode()) + 1)
            self.entries.append(Entry(i, full, logical or full, a | ((b & 0xff) << 32), b >> 8,
                                      size, blk >> 28, blk & 0x0fffffff, hashes[i]))

    def block_table(self, e):
        """Return (entries, mask, compressed_flag) for the table this file uses."""
        sectors = (e.size + self.sector - 1) // self.sector
        if sectors <= 0x7f:
            return self.small, 0x7f, 0x80
        if sectors <= 0x7fff:
            return self.medium, 0x7fff, 0x8000
        return self.large, 0x7fffffff, 0x80000000

    def read(self, e):
        if e.ctype == TYPE_NONE:
            self.f.seek(e.offset)
            return self.f.read(e.size)
        if e.ctype != TYPE_LZMA:
            raise NotImplementedError(f'{e.logical_name}: compression de type {e.ctype} inconnue')
        table, mask, cflag = self.block_table(e)
        nblocks = (e.size + BLOCK_SIZE - 1) // BLOCK_SIZE
        out = bytearray()
        for k in range(nblocks):
            ent = table[e.block_index + k]
            nxt = table[e.block_index + k + 1] & mask
            start = e.offset + (ent & mask) * self.sector
            want = min(BLOCK_SIZE, e.size - k * BLOCK_SIZE)
            self.f.seek(start)
            if ent & cflag:
                raw = self.f.read((nxt - (ent & mask)) * self.sector)
                csize = struct.unpack_from('<I', raw)[0]
                flt = lzma._decode_filter_properties(lzma.FILTER_LZMA1, raw[4:9])
                dec = lzma.LZMADecompressor(lzma.FORMAT_RAW, filters=[flt])
                blk = dec.decompress(raw[9:9 + csize], max_length=want)
            else:
                blk = self.f.read(want)
            if len(blk) != want:
                raise IOError(f'{e.logical_name}: bloc {k} = {len(blk)} octets, attendu {want}')
            out += blk
        return bytes(out)


def replace_files(src, dst, replacements):
    """Copie src vers dst en remplacant des fichiers.

    replacements : {nom logique: octets}. Chaque nouveau fichier est ajoute en fin d'archive, non compresse
    (type 0xF, comme les fichiers deja stockes ainsi), aligne sur un secteur ; son entree de TOC est
    reecrite (offset, taille, bloc). Les hashes, l'ordre et la table des noms ne changent pas.
    """
    shutil.copyfile(src, dst)
    _append_replace(dst, replacements)


def _append_replace(path, replacements):
    """Ajoute les fichiers en fin d'archive et reecrit leurs entrees. Retourne {index: entree d'origine}."""
    invalidate_cache(path)
    arc = IgaArchive(path)
    by_name = {e.logical_name.lower(): e for e in arc.entries}
    n, sector = len(arc.entries), arc.sector
    arc.f.close()
    originals = {}
    with open(path, 'r+b') as f:
        for name, data in replacements.items():
            e = by_name.get(name.lower())
            if e is None:
                raise KeyError(f'{name} absent de {path}')
            toc = 0x38 + n * 4 + e.index * 16
            f.seek(toc)
            originals[e.index] = f.read(16)
            f.seek(0, os.SEEK_END)
            pos = f.tell()
            pos += -pos % sector
            f.write(b'\0' * (pos - f.tell()))
            f.write(data)
            f.write(b'\0' * (-f.tell() % sector))
            if pos >> 40:
                raise ValueError('archive trop grande')
            entry = struct.pack('<IIII', pos & 0xFFFFFFFF, ((pos >> 32) & 0xFF) | (e.ordinal << 8),
                                len(data), (TYPE_NONE << 28) | 0x0FFFFFFF)
            f.seek(toc)
            f.write(entry)
    return originals


UPDATE_ARCHIVES = ('update2.pak', 'update.pak')   # versions les plus recentes en premier


_cache = {}                     # chemin -> (empreinte, IgaArchive, {nom minuscule: entree}, verrou)
_cache_lock = threading.Lock()


def cached_archive(path):
    """Archive ouverte et indexee, reutilisee tant que le fichier ne change pas (taille / date)."""
    st = os.stat(path)
    stamp = (st.st_size, st.st_mtime_ns)
    with _cache_lock:
        hit = _cache.get(path)
        if hit and hit[0] == stamp:
            return hit[1], hit[2], hit[3]
        if hit:
            hit[1].f.close()
        arc = IgaArchive(path)
        index = {e.logical_name.lower(): e for e in arc.entries}
        _cache[path] = (stamp, arc, index, threading.Lock())
        return arc, index, _cache[path][3]


def invalidate_cache(path=None):
    with _cache_lock:
        for p in ([path] if path else list(_cache)):
            hit = _cache.pop(p, None)
            if hit:
                hit[1].f.close()


def archives_with(archives_dir, logical_name, track_pak=None):
    """Archives contenant le fichier, de la plus prioritaire (mise a jour) a la moins prioritaire."""
    names = list(UPDATE_ARCHIVES) + ([track_pak] if track_pak else [])
    out = []
    for n in names:
        p = os.path.join(archives_dir, n)
        if os.path.exists(p) and logical_name.lower() in cached_archive(p)[1]:
            out.append(p)
    return out


class _OverlayFile:
    """Fichier dont les premiers octets viennent d'une sauvegarde (en-tete + TOC d'origine)."""

    def __init__(self, path, head):
        self.f, self.head, self.pos = open(path, 'rb'), head, 0

    def seek(self, pos, whence=0):
        self.pos = pos if whence == 0 else (self.pos + pos if whence == 1 else os.path.getsize(self.f.name) + pos)
        return self.pos

    def tell(self):
        return self.pos

    def read(self, n=-1):
        out = b''
        if self.pos < len(self.head):
            out = self.head[self.pos:self.pos + n] if n >= 0 else self.head[self.pos:]
            self.pos += len(out)
            n = n - len(out) if n >= 0 else n
            if n == 0:
                return out
        self.f.seek(self.pos)
        rest = self.f.read(n)
        self.pos += len(rest)
        return out + rest

    def close(self):
        self.f.close()


_orig_cache = {}


def original_archive(path):
    """(archive, index, verrou) de l'archive TELLE QU'AVANT le mod installe (sauvegarde v2), sinon None."""
    info = _backup_info(path)
    if not info or info.get('version') != 2:
        return None
    stamp = (os.path.getsize(path), os.path.getmtime(path))
    hit = _orig_cache.get(path)
    if hit and hit[0] == stamp:
        return hit[1:]
    if hit:
        hit[1].f.close()
    head = open(toc_backup_path(path), 'rb').read()
    arc = IgaArchive(path, _OverlayFile(path, head))
    index = {e.logical_name.lower(): e for e in arc.entries}
    _orig_cache[path] = (stamp, arc, index, threading.Lock())
    return arc, index, _orig_cache[path][3]


def read_latest(archives_dir, logical_name, track_pak=None, original=True):
    """Contenu de la version la plus recente d'un fichier (update2 > update > archive de la piste).

    original=True : si un mod est installe sur l'archive, lit la version d'origine (sauvegarde) ; un fichier
    ajoute par le mod n'existe donc pas dans cette vue.
    """
    names = list(UPDATE_ARCHIVES) + ([track_pak] if track_pak else [])
    for n in names:
        p = os.path.join(archives_dir, n)
        if not os.path.exists(p):
            continue
        view = original_archive(p) if original else None
        arc, index, lock = view if view else cached_archive(p)
        e = index.get(logical_name.lower())
        if e is None:
            continue
        info = _backup_info(p) if original and not view else None
        if info and info.get('version', 1) == 1:              # ancienne sauvegarde : entrees seulement
            saved = info['entries'].get(str(e.index))
            if saved:
                a, b, size, blk = struct.unpack('<IIII', bytes.fromhex(saved))
                e = Entry(e.index, e.name, e.logical_name, a | ((b & 0xff) << 32), b >> 8, size,
                          blk >> 28, blk & 0x0FFFFFFF, e.name_hash)
        with lock:                                   # le fichier ouvert est partage entre threads
            data = arc.read(e)
        return data, p
    raise KeyError(logical_name)


def backup_path(archive):
    return archive + '.ctrmod.json'


def toc_backup_path(archive):
    return archive + '.ctrmod.toc'


def _backup_info(archive):
    bk = backup_path(archive)
    return json.load(open(bk)) if os.path.exists(bk) else None


def fnv1a_lower(s):
    h = 0x811C9DC5
    for c in s.lower().encode('latin1'):
        h = ((h ^ c) * 0x01000193) & 0xFFFFFFFF
    return h


FULL_PREFIX = 'temporary/octane/data/ps4/output/'


def install(archive, files):
    """Installe des fichiers (remplaces OU ajoutes) en place, de facon reversible (voir uninstall).

    Sauvegarde : tout l'en-tete jusqu'aux premieres donnees (TOC d'origine) + taille d'origine. Les nouvelles
    donnees sont ajoutees en fin d'archive, non compressees ; la TOC est reconstruite (triee par hash
    FNV-1a du nom logique en minuscules, diviseur et marge de recherche recalcules) et la table des noms
    reecrite en fin de fichier."""
    bk = backup_path(archive)
    if os.path.exists(bk):
        raise RuntimeError(f'un mod est deja installe sur {archive} : lancer uninstall d\'abord')
    invalidate_cache(archive)
    arc = IgaArchive(archive)
    limit, moved = _plan_toc_space(arc, files)
    arc.f.seek(0)
    head = arc.f.read(limit)            # en-tete + TOC + donnees des fichiers deplaces (recouvertes par la TOC)
    size = os.path.getsize(archive)
    arc.f.close()
    open(toc_backup_path(archive), 'wb').write(head)                       # sauvegarde AVANT modification
    with open(bk, 'w') as f:
        json.dump({'version': 2, 'original_size': size, 'files': sorted(files),
                   'moved': sorted(e.logical_name for e in moved)}, f, indent=1)
    _rebuild_with_files(archive, files, limit, moved)


def _plan_toc_space(arc, files):
    """Place de la TOC : elle s'etend jusqu'aux premieres donnees. Si les fichiers ajoutes (20 o d'entree chacun)
    ne tiennent pas, les fichiers stockes juste apres la TOC sont deplaces en fin d'archive (leurs blocs sont
    adresses depuis le debut du fichier : ils restent valides). Retourne (nouvelle limite, entrees a deplacer)."""
    by_name = {e.logical_name.lower() for e in arc.entries}
    n_new = len(arc.entries) + sum(1 for n in files if n.lower() not in by_name)
    toc_size = struct.unpack('<I', _read_at(arc.f, 8, 4))[0]
    need = 0x38 + n_new * 20 + (toc_size - len(arc.entries) * 20)
    starts = sorted({e.offset for e in arc.entries})
    limit = next((s for s in starts if s >= need), None)
    if limit is None:
        raise RuntimeError(f'plus de place dans la TOC de {arc.path}')
    return limit, [e for e in arc.entries if e.offset < limit]


def _read_at(f, pos, n):
    f.seek(pos)
    return f.read(n)


def _rebuild_with_files(archive, files, limit=None, moved=()):
    arc = IgaArchive(archive)
    sector = arc.sector
    first_data = limit or min(e.offset for e in arc.entries)
    # fichiers deplaces : etendue brute (jusqu'au debut du fichier suivant), lue avant toute ecriture
    starts = sorted({e.offset for e in arc.entries})
    relocate = {}
    for e in moved:
        if e.logical_name.lower() in {n.lower() for n in files}:
            continue                                       # remplace : ses nouvelles donnees sont ajoutees de toute facon
        end = next(s for s in starts if s > e.offset)
        relocate[e.index] = _read_at(arc.f, e.offset, end - e.offset)
    arc.f.seek(0)
    hdr = bytearray(arc.f.read(0x38))
    n_old = len(arc.entries)
    arc.f.seek(0x38)
    toc = arc.f.read(struct.unpack_from('<I', hdr, 8)[0])
    blocks = toc[n_old * 20:]                                  # tables de blocs (inchangees)
    arc.f.close()
    by_name = {e.logical_name.lower(): e for e in arc.entries}
    rows = []                                                  # (hash, entree 16 o, nom complet, nom logique)
    max_ord = max((e.ordinal for e in arc.entries if e.ordinal < 0xFFFFFF), default=0)   # 0xFFFFFF = sentinelle
    with open(archive, 'r+b') as f:
        placed = {}
        for name, data in files.items():
            f.seek(0, os.SEEK_END)
            pos = f.tell()
            pos += -pos % sector
            f.write(b'\0' * (pos - f.tell()))
            f.write(data)
            f.write(b'\0' * (-f.tell() % sector))
            placed[name.lower()] = (pos, len(data))
        new_offset = {}
        for idx, blob in relocate.items():                      # meme contenu brut, plus loin
            f.seek(0, os.SEEK_END)
            pos = f.tell()
            pos += -pos % sector
            f.write(b'\0' * (pos - f.tell()))
            f.write(blob)
            new_offset[idx] = pos
        for e in arc.entries:
            off = new_offset.get(e.index, e.offset)
            raw = struct.pack('<IIII', off & 0xFFFFFFFF, ((off >> 32) & 0xFF) | (e.ordinal << 8), e.size,
                              (e.ctype << 28) | (e.block_index & 0x0FFFFFFF))
            if e.logical_name.lower() in placed:
                pos, ln = placed[e.logical_name.lower()]
                raw = struct.pack('<IIII', pos & 0xFFFFFFFF, ((pos >> 32) & 0xFF) | (e.ordinal << 8), ln,
                                  (TYPE_NONE << 28) | 0x0FFFFFFF)
            rows.append((e.name_hash, raw, e.name, e.logical_name))
        for name in files:
            if name.lower() in by_name:
                continue
            max_ord += 1
            pos, ln = placed[name.lower()]
            raw = struct.pack('<IIII', pos & 0xFFFFFFFF, ((pos >> 32) & 0xFF) | (max_ord << 8), ln,
                              (TYPE_NONE << 28) | 0x0FFFFFFF)
            rows.append((fnv1a_lower(name), raw, FULL_PREFIX + name, name))
        rows.sort(key=lambda r: r[0])
        n = len(rows)
        new_toc = b''.join(struct.pack('<I', r[0]) for r in rows) + b''.join(r[1] for r in rows) + blocks
        if 0x38 + len(new_toc) > first_data:
            raise RuntimeError(f'plus de place dans la TOC de {archive} ({0x38 + len(new_toc)} > {first_data})')
        # table des noms : offsets u32 puis « nom complet \0 nom logique \0 » (alignes sur 2 comme l'original ?)
        strings, offs = bytearray(), []
        for r in rows:
            offs.append(n * 4 + len(strings))
            strings += r[2].encode('latin1') + b'\0' + r[3].encode('latin1') + b'\0'
        names_blob = struct.pack(f'<{n}I', *offs) + bytes(strings)
        f.seek(0, os.SEEK_END)
        name_off = f.tell()
        name_off += -name_off % 16
        f.write(b'\0' * (name_off - f.tell()))
        f.write(names_blob)
        # recherche par hash : indice ~ hash // diviseur, a +/- marge pres
        div = max(1, (1 << 32) // n)
        slop = max(abs(i - r[0] // div) for i, r in enumerate(rows)) + 1
        struct.pack_into('<II', hdr, 0x08, len(new_toc), n)
        struct.pack_into('<II', hdr, 0x14, div, slop)
        struct.pack_into('<QI', hdr, 0x28, name_off, len(names_blob))
        f.seek(0)
        f.write(bytes(hdr))
        f.write(new_toc)
        f.write(b'\0' * (first_data - 0x38 - len(new_toc)))
    invalidate_cache(archive)


def uninstall(archive):
    invalidate_cache(archive)
    _orig_cache.pop(archive, None)
    bk = backup_path(archive)
    info = json.load(open(bk))
    if info.get('version') == 2:
        head = open(toc_backup_path(archive), 'rb').read()
        with open(archive, 'r+b') as f:
            f.seek(0)
            f.write(head)
            f.truncate(info['original_size'])
        os.remove(toc_backup_path(archive))
    else:                                                       # ancienne sauvegarde : entrees seulement
        arc = IgaArchive(archive)
        n = len(arc.entries)
        arc.f.close()
        with open(archive, 'r+b') as f:
            for idx, raw in info['entries'].items():
                f.seek(0x38 + n * 4 + int(idx) * 16)
                f.write(bytes.fromhex(raw))
            f.truncate(info['original_size'])
    os.remove(bk)


def match(e, pattern):
    if not pattern:
        return True
    pattern = pattern.lower()
    name = e.logical_name.lower()
    return fnmatch.fnmatch(name, pattern) or pattern in name


def safe_path(name):
    name = name.replace('\\', '/').lstrip('/')
    parts = [re.sub(r'[<>:"|?*]', '_', p) for p in name.split('/') if p not in ('', '.', '..')]
    return os.path.join(*parts)


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 1
    cmd, path = argv[1], argv[2]
    if cmd == 'replace':
        reps = {}
        for spec in argv[4:]:
            name, _, src = spec.partition('=')
            reps[name] = open(src, 'rb').read()
        replace_files(path, argv[3], reps)
        print(f'{len(reps)} fichier(s) remplace(s) -> {argv[3]}')
        return 0
    if cmd == 'install':
        reps = {}
        for spec in argv[3:]:
            name, _, src = spec.partition('=')
            reps[name] = open(src, 'rb').read()
        install(path, reps)
        print(f'{len(reps)} fichier(s) installe(s) dans {path} (sauvegarde : {backup_path(path)})')
        return 0
    if cmd == 'uninstall':
        uninstall(path)
        print(f'{path} restaure')
        return 0
    arc = IgaArchive(path)
    if cmd == 'info':
        sizes = sum(e.size for e in arc.entries)
        print(f'{path}\n  IGA v{arc.version}, {len(arc.entries)} fichiers, {sizes / 1e6:.1f} Mo decompresses')
        ext = {}
        for e in arc.entries:
            x = os.path.splitext(e.logical_name)[1].lower()
            ext[x] = ext.get(x, 0) + 1
        for x, c in sorted(ext.items(), key=lambda kv: -kv[1]):
            print(f'  {x or "(sans)":10} {c}')
    elif cmd == 'list':
        pattern = argv[3] if len(argv) > 3 else None
        for e in sorted(arc.entries, key=lambda e: e.logical_name.lower()):
            if match(e, pattern):
                print(f'{e.size:>10}  {"lzma" if e.ctype == TYPE_LZMA else "raw ":4}  {e.logical_name}')
    elif cmd == 'extract':
        out_dir = argv[3]
        pattern = argv[4] if len(argv) > 4 else None
        count = 0
        for e in arc.entries:
            if not match(e, pattern):
                continue
            dst = os.path.join(out_dir, safe_path(e.logical_name))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, 'wb') as o:
                o.write(arc.read(e))
            count += 1
        print(f'{count} fichiers extraits dans {out_dir}')
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
