"""Nouvelle piste sans en ecraser une : copie RENOMMEE d'une piste du jeu, enregistree comme une zone de plus.

Ce que le jeu utilise (releve sur les pistes du Grand Prix T501-T508, ajoutees par simples donnees) :
  * archives/<zone>.pak : la piste ; ouverte par son nom (aucune liste de .pak dans les donnees) ;
    chunks.igx (racine du jeu) liste tous les fichiers « installes », dont ces archives ;
  * maps/octane/<zone>/<zone>_zoneinfo.igz (CZoneInfo, _name = « octane/<zone>/<zone> ») et ses .lng,
    declares dans packages/generated/maps/chunkInfos_pkg.igz (igx_file / lang_file) ;
  * le menu (ui/Octane_LevelSelect_Proto.igz) : voir custom_category.py.

Renommage : l'identifiant (« T111_Crash_Cove ») est remplace partout par un identifiant de MEME longueur
(« T901_Custom_Map ») — chemins des fichiers, textes des fichiers (mise en page intacte) — et les hachages
FNV-1a des noms touches sont recalcules : EXID (handles par hachage vers un autre fichier), listes de noms,
cles de StaticCollision (hachage du nom des fichiers _Art). Les banques de sons (LVL_/MUS_<id>_bank...) gardent
leur nom : ce sont les memes fichiers, lus tels quels.
"""
import json
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # lance avec « python -I »
import pak_tool  # noqa: E402
from igz import fnv1a_lower  # noqa: E402

LANGS = ('en', 'fr', 'mx', 'pt')
CHUNKINFOS = 'packages/generated/maps/chunkInfos_pkg.igz'
CHUNKS_IGX = 'chunks.igx'
SOUND_CTX = (b'lvl_', b'mus_')            # « LVL_T111_Crash_Cove_bank », « mus_t111_crash_cove_lp » : sons gardes
NAME_POOL = 'Custom_Map_Track_Copy_Zone_Extra_Long_Name'


def fnv1a(s):
    h = 0x811C9DC5
    for c in s.encode('latin1'):
        h = ((h ^ c) * 0x01000193) & 0xFFFFFFFF
    return h


def new_id(src, n):
    """Identifiant de meme longueur que la source : T9NN_Custom_Map... (lettres seulement apres le numero, comme
    les pistes du jeu : l'editeur reconnait les archives t\\d{3}_[a-z_]+)."""
    head = f'T9{n:02d}_'
    s = (head + NAME_POOL)[:len(src)]
    if len(s) < len(src) or len(src) < len(head) + 1:
        raise ValueError(f'identifiant source trop court : {src}')
    return s[:-1] + 'x' if s.endswith('_') else s


def zone_name(track_id):
    t = track_id.lower()
    return f'octane/{t}/{t}'


def zoneinfo_logical(track_id):
    return f'maps/octane/{track_id.lower()}/{track_id.lower()}_zoneinfo.igz'


def lng_logical(track_id, lang):
    return f'maps/Octane/{track_id}/{track_id}_zoneInfo_{lang}.lng'


class Renamer:
    def __init__(self, src, new):
        if len(src) != len(new):
            raise ValueError('identifiants de longueurs differentes')
        self.src, self.new = src, new
        self.rx = re.compile(re.escape(src).encode(), re.I)

    def _case(self, old):
        o = old.decode('latin1')
        if o == self.src:
            return self.new
        if o == o.lower():
            return self.new.lower()
        if o == o.upper():
            return self.new.upper()
        return ''.join(n.upper() if c.isupper() else n.lower() for c, n in zip(o, self.new))

    def text(self, data):
        """Octets avec l'identifiant remplace (hors contextes de sons) ; (octets, nombre de remplacements)."""
        out, n = None, 0
        for m in self.rx.finditer(data):
            s = m.start()
            if data[max(0, s - 4):s].lower() in SOUND_CTX:
                continue
            if out is None:
                out = bytearray(data)
            out[s:m.end()] = self._case(m.group()).encode('latin1')
            n += 1
        return (bytes(out) if out is not None else data), n

    def name(self, s):
        return self.text(s.encode('latin1'))[0].decode('latin1')


# -- fichiers IGZ : zones de correctifs (fixups) -------------------------------------------------------------
def _fixups(data):
    """{magic: (debut du corps, fin)} des correctifs d'un IGZ (section 0, comme IgzFile), plus '@data' : debut des
    sections de donnees."""
    out = {}
    secs = []
    for i in range(32):
        off, size = struct.unpack_from('<II', data, 0x18 + i * 16)
        if off == 0 and size == 0:
            break
        secs.append((off, size))
    fo, fs = secs[0]
    p = fo
    while p < fo + fs:
        m, cnt, size, start = struct.unpack_from('<4sIII', data, p)
        out[m.decode('latin1')] = (p + start, p + size)
        if size == 0:
            break
        p += size
    out['@data'] = (min((o for o, s in secs[1:]), default=fo + fs), len(data))
    return out


def _strings(data, fx):
    if 'TSTR' not in fx:
        return []
    a, b = fx['TSTR']
    return [s.decode('latin1') for s in data[a:b].split(b'\0') if s]


def _patch_u32(buf, a, b, table):
    """Remplace dans buf[a:b] les u32 alignes (sur 4 depuis a) presents dans table ; retourne le nombre."""
    n = 0
    for i in range(a, b - 3, 4):
        v = struct.unpack_from('<I', buf, i)[0]
        if v in table:
            struct.pack_into('<I', buf, i, table[v])
            n += 1
    return n


def _hash_table(tokens, ren):
    t = {}
    for s in tokens:
        r = ren.name(s)
        if r == s:
            continue
        for f in (fnv1a_lower, fnv1a):
            if f(s) != f(r):
                t[f(s)] = f(r)
    return t


def transform_igz(data, ren, global_hashes, local_extra):
    """IGZ renomme : textes, EXID (hachages globaux), puis hachages des noms propres au fichier (listes de noms,
    tables, cles de collision). Retourne (octets, stats)."""
    data2, nt = ren.text(data)
    buf = bytearray(data2)
    fx = _fixups(data)
    st = {'text': nt, 'exid': 0, 'local': 0}
    if 'EXID' in fx:
        st['exid'] = _patch_u32(buf, *fx['EXID'], global_hashes)
    if nt:
        own = [s for s in _strings(data, fx) if ren.rx.search(s.encode('latin1'))]
        local = _hash_table(set(own) | set(local_extra), ren)
        start = fx['@data'][0]                                    # sections de donnees (pas les correctifs)
        st['local'] = _patch_u32(buf, start - start % 4, len(buf), local)
    return bytes(buf), st


# -- tables de hachage : cles renommees = cases a refaire --------------------------------------------------------
_M64 = 0xFFFFFFFFFFFFFFFF
_EMPTY_KEYS = {0xFAFAFAFAFAFAFAFA, 0xFAFAFAFA, 0, _M64, 0xFFFFFFFF}


def wang_hash(k):
    """Hachage des cles entieres 64 bits des igHashTable (verifie sur StaticCollision : 77/77 cles a leur place)."""
    k = (~k + (k << 18)) & _M64
    k ^= k >> 31
    k = (k * 21) & _M64
    k ^= k >> 11
    k = (k + (k << 6)) & _M64
    k ^= k >> 22
    return k & 0xFFFFFFFF


_KEY_HASHES = (lambda k: fnv1a_lower(k) if isinstance(k, str) else None,
               lambda k: wang_hash(k) if isinstance(k, int) else None)


def _hash_tables(z):
    """[(objet, taille des cles, cles, taille des valeurs, valeurs)] des igHashTable."""
    out = []
    for o, t in z.objects.items():
        if 'igHashTable' in z._chain(t):
            ks, kd = z.u32(o + 0x20) & 0x07FFFFFF, z.deref(o + 0x28)
            vs, vd = z.u32(o + 0x10) & 0x07FFFFFF, z.deref(o + 0x18)
            if kd is not None and vd is not None and ks:
                out.append((o, ks, kd, vs, vd))
    return out


def _table_keys(z, kd, cap, stride):
    out = []
    for i in range(cap):
        a = kd + i * stride
        if stride == 8 and z.is_str(a):
            out.append((i, z.string(z.u32(a))))
        else:
            v = z.u64(a) if stride == 8 else z.u32(a)
            if v not in _EMPTY_KEYS:
                out.append((i, v))
    return out


def _placed(cap, keys, h):
    """Toutes les cles a leur case (h(cle) % cap puis cases suivantes occupees) ?"""
    occ = {i for i, _ in keys}
    for i, k in keys:
        v = h(k)
        if v is None:
            return False
        j = v % cap
        while j != i and j in occ:
            j = (j + 1) % cap
        if j != i:
            return False
    return True


def rehash_tables(new, orig):
    """IGZ renomme (meme mise en page que orig) avec ses tables de hachage remises en ordre : une cle renommee
    (chaine, ou cle de StaticCollision = hachage d'un nom) change de case ; le jeu ne la trouvait plus (piste sans
    collision). Seules les tables bien rangees dans l'original et derangees dans la copie sont refaites."""
    from igz import IgzFile
    z0 = IgzFile(orig)
    tabs = _hash_tables(z0)
    if not tabs:
        return new, 0
    z1 = IgzFile(new)
    fixed = 0
    for o, ks, kd, vs, vd in tabs:
        for stride in (8, 4):
            cap = ks // stride
            k0 = _table_keys(z0, kd, cap, stride)
            h = next((f for f in _KEY_HASHES if k0 and _placed(cap, k0, f)), None)
            if h:
                break
        else:
            continue
        k1 = _table_keys(z1, kd, cap, stride)
        if _placed(cap, k1, h):
            continue
        vstride = vs // cap
        kinds = list(z1.offset_sets)

        def take(a, n):
            return bytes(z1._loc(a)[0][z1._loc(a)[1]:z1._loc(a)[1] + n]), \
                [(kd_, r) for kd_ in kinds for r in range(n) if a + r in z1.offset_sets[kd_]]

        def put(a, n, raw, marks):
            buf, p = z1._loc(a)
            buf[p:p + n] = raw
            for kd_ in kinds:
                for r in range(n):
                    z1._mark(kd_, a + r, False)
            for kd_, r in marks:
                z1._mark(kd_, a + r, True)

        used = {i for i, _ in k1}
        empty = next(i for i in range(cap) if i not in used)
        blank = (take(kd + empty * stride, stride), take(vd + empty * vstride, vstride))
        items = [(k, take(kd + i * stride, stride), take(vd + i * vstride, vstride)) for i, k in k1]
        for i in range(cap):
            put(kd + i * stride, stride, *blank[0])
            put(vd + i * vstride, vstride, *blank[1])
        taken = set()
        for k, kb, vb in items:
            j = h(k) % cap
            while j in taken:
                j = (j + 1) % cap
            taken.add(j)
            put(kd + j * stride, stride, *kb)
            put(vd + j * vstride, vstride, *vb)
        fixed += 1
    return (z1.to_bytes(), fixed) if fixed else (new, 0)


# -- lecture des sources ---------------------------------------------------------------------------------------
def _view(path):
    v = pak_tool.original_archive(path)
    if v:
        return v
    return pak_tool.cached_archive(path)


def source_files(archives, src):
    """{nom logique: (archive, entree)} des fichiers de la piste : son archive, plus les fichiers des mises a jour
    qui la remplacent ou qui portent son identifiant (versions d'origine, jamais celles de l'editeur)."""
    rx = re.compile(re.escape(src), re.I)
    pak = os.path.join(archives, src.lower() + '.pak')
    a, idx, lock = _view(pak)
    out = {e.logical_name: (a, e, lock) for e in idx.values()}
    lower = {n.lower(): n for n in out}
    for up in reversed(pak_tool.UPDATE_ARCHIVES):               # update puis update2 (le plus recent l'emporte)
        p = os.path.join(archives, up)
        if not pak_tool.exists(p):
            continue
        ua, uidx, ulock = _view(p)
        for n, e in uidx.items():
            if n in lower or (rx.search(n) and not n.endswith('.pak') and '_zoneinfo' not in n):
                out[lower.get(n, e.logical_name)] = (ua, e, ulock)
                lower[n] = lower.get(n, e.logical_name)
    return out


def flyby_paks(archives, src):
    s = src.lower()
    return sorted(f for f in pak_tool.listdir(archives) if f.lower().startswith(s + '_') and 'flyby' in f.lower()
                  and f.lower().endswith('.pak'))


def _read(ae):
    a, e, lock = ae
    with lock:
        return a.read(e)


# -- ecriture d'une archive IGA neuve --------------------------------------------------------------------------
def _raw_span(a, e, lock):
    """(octets bruts du fichier tels que stockes, blocs relatifs) pour une copie sans recompression."""
    with lock:
        if e.ctype == pak_tool.TYPE_NONE:
            a.f.seek(e.offset)
            return a.f.read(e.size), None
        table, mask, cflag = a.block_table(e)
        nb = (e.size + pak_tool.BLOCK_SIZE - 1) // pak_tool.BLOCK_SIZE
        blocks = list(table[e.block_index:e.block_index + nb + 1])
        end = (blocks[-1] & mask) * a.sector
        a.f.seek(e.offset)
        return a.f.read(end), blocks


def write_archive(path, files, template):
    """files : [(nom logique, nom complet, ordinal, ('data', octets) | ('raw', archive, entree, verrou))].
    Les fichiers « raw » sont recopies tels quels (compresses ou non) avec leurs blocs ; les autres non compresses."""
    tpl = pak_tool.IgaArchive(pak_tool.real(template))
    sector, flags, version = tpl.sector, tpl.flags, tpl.version
    tpl.f.close()
    tables = {'small': [], 'medium': [], 'large': []}
    rows = []
    n = len(files)
    # place de la TOC estimee large : en-tete + entrees + tables de blocs (calculees au premier passage)
    staged = []
    for logical, full, ordinal, src in files:
        if src[0] == 'raw':
            raw, blocks = _raw_span(*src[1:])
            e = src[2]
            staged.append((logical, full, ordinal, raw, e.size, e.ctype, blocks))
        else:
            staged.append((logical, full, ordinal, src[1], len(src[1]), pak_tool.TYPE_NONE, None))
    for logical, full, ordinal, raw, size, ctype, blocks in staged:
        if blocks is not None:
            sectors = (size + sector - 1) // sector
            kind = 'small' if sectors <= 0x7f else ('medium' if sectors <= 0x7fff else 'large')
            tables[kind] += blocks
    toc_size = n * 20 + len(tables['large']) * 4 + len(tables['medium']) * 2 + len(tables['small'])
    first = 0x38 + toc_size
    first += -first % sector
    for t in tables.values():
        t.clear()
    with open(path, 'wb') as f:
        f.write(b'\0' * first)
        for logical, full, ordinal, raw, size, ctype, blocks in staged:
            pos = f.tell()
            pos += -pos % sector
            f.write(b'\0' * (pos - f.tell()))
            f.write(raw)
            if blocks is None:
                blk = 0x0FFFFFFF
            else:
                sectors = (size + sector - 1) // sector
                kind = 'small' if sectors <= 0x7f else ('medium' if sectors <= 0x7fff else 'large')
                blk = len(tables[kind])
                tables[kind] += blocks
            if pos >> 40:
                raise ValueError('archive trop grande')
            ent = struct.pack('<IIII', pos & 0xFFFFFFFF, ((pos >> 32) & 0xFF) | (ordinal << 8), size,
                              (ctype << 28) | (blk & 0x0FFFFFFF))
            rows.append((fnv1a_lower(logical), ent, full, logical))
        f.write(b'\0' * (-f.tell() % sector))
        rows.sort(key=lambda r: r[0])
        strings, offs = bytearray(), []
        for r in rows:
            offs.append(n * 4 + len(strings))
            strings += r[2].encode('latin1') + b'\0' + r[3].encode('latin1') + b'\0'
        names_blob = struct.pack(f'<{n}I', *offs) + bytes(strings)
        name_off = f.tell()
        name_off += -name_off % 16
        f.write(b'\0' * (name_off - f.tell()))
        f.write(names_blob)
        div = min(0xFFFFFFFF, max(1, (1 << 32) // n))   # un seul fichier : 2^32 ne tient pas dans l'en-tete (u32)
        slop = max(abs(i - r[0] // div) for i, r in enumerate(rows)) + 1
        toc = (b''.join(struct.pack('<I', r[0]) for r in rows) + b''.join(r[1] for r in rows)
               + struct.pack(f'<{len(tables["large"])}I', *tables['large'])
               + struct.pack(f'<{len(tables["medium"])}H', *tables['medium'])
               + bytes(tables['small']))
        assert 0x38 + len(toc) <= first
        hdr = struct.pack('<4sIIIIIIIIIQII', b'IGA\x1a', version, len(toc), n, sector, div, slop,
                          len(tables['large']), len(tables['medium']), len(tables['small']),
                          name_off, len(names_blob), flags)
        f.seek(0)
        f.write(hdr)
        f.write(toc)


# -- clonage ----------------------------------------------------------------------------------------------------
def _is_igz(name, data):
    return name.lower().endswith(('.igz', '.lng')) and data[:4] in (b'\x01ZGI', b'IGZ\x01')


def _ordinals(archives, pak_name, names):
    """{nom: ordinal} : celui de l'archive de la piste, les fichiers venus des mises a jour a la suite (leur ordinal
    d'update2 depasse le nombre de fichiers et en double d'autres : le jeu plantait au chargement). Comme les
    archives du jeu : 0..n-1 sans doublon, 0xFFFFFF (sentinelle) garde."""
    a, idx, lock = _view(os.path.join(archives, pak_name))
    base = {n: e.ordinal for n, e in idx.items()}
    nxt = max((o for o in base.values() if o < 0xFFFFFF), default=-1) + 1
    out = {}
    for n in sorted(names):
        o = base.get(n.lower())
        if o is None:
            o, nxt = nxt, nxt + 1
        out[n] = o
    used = [o for o in out.values() if o < 0xFFFFFF]
    if len(used) != len(set(used)):
        raise RuntimeError(f'{pak_name} : ordinaux en double')
    return out


def clone_pak(archives, src, new, pak_name, out_path, extra=None, progress=None):
    """Ecrit la copie renommee d'une archive de piste. Retourne des statistiques."""
    ren = Renamer(src, new)
    if extra is None:
        srcs = {}
        a, idx, lock = _view(os.path.join(archives, pak_name))
        for e in idx.values():
            srcs[e.logical_name] = (a, e, lock)
    else:
        srcs = extra
    names = list(srcs)
    # jetons globaux (EXID) : textes de tous les IGZ qui portent l'identifiant + noms des fichiers renommes
    tokens = set()
    for n in names:
        b = os.path.basename(n).rsplit('.', 1)[0]
        if ren.rx.search(b.encode('latin1')):
            tokens |= {b, b.lower()}
    texts = {}
    for n in names:
        a, e, lock = srcs[n]
        if not n.lower().endswith(('.igz', '.lng')):
            continue
        d = _read(srcs[n])
        if ren.rx.search(d):
            texts[n] = d
            fx = _fixups(d)
            tokens |= {s for s in _strings(d, fx) if ren.rx.search(s.encode('latin1'))}
    gh = _hash_table(tokens, ren)
    # cles de StaticCollision : hachage du nom des fichiers de la carte (_Art...) ; liste courte expres (chaque
    # valeur cherchee dans tout le fichier : peu de valeurs = pas de fausse correspondance)
    local_extra = sorted({os.path.basename(n).rsplit('.', 1)[0] for n in names if n.lower().startswith('maps/')
                          and ren.rx.search(n.encode('latin1'))})
    ords = _ordinals(archives, pak_name, names)
    files, st = [], {'files': 0, 'renamed': 0, 'rewritten': 0, 'text': 0, 'exid': 0, 'local': 0, 'tables': 0,
                     'shared': 0, 'kept_originals': 0}
    # Fichiers PARTAGES : nom sans l'identifiant mais contenu qui le cite (bibliotheque de materiaux
    # l101_nsanitybeach_materials -> texture « levels!Octane!T111_Crash_Cove!T111_Grass... », effets de cascade...).
    # Gardes TELS QUELS : un meme nom doit avoir le meme contenu dans toutes les pistes (le jeu reprend la version deja
    # chargee : T902 puis T901 = plantage au debut du 2e chargement, liste chainee corrompue). Les fichiers renommes
    # qu'ils citent (par texte ou par hachage EXID) restent AUSSI sous leur nom d'origine.
    rev = {}
    for tkn in tokens:
        for f in (fnv1a_lower, fnv1a):
            rev.setdefault(f(tkn), tkn.lower())
    cited_text, cited_tokens = [], set()
    for k, n in enumerate(sorted(names)):
        a, e, lock = srcs[n]
        if progress and k % 50 == 0:
            progress(k / len(names))
        new_n = ren.name(n)
        full = ren.name(e.name if e.name.lower().endswith(n.lower()) else pak_tool.FULL_PREFIX + n)
        st['files'] += 1
        st['renamed'] += new_n != n
        d = texts.get(n)
        exids = []
        if n.lower().endswith(('.igz', '.lng')):
            dd = d if d is not None else _read(srcs[n])
            fx = _fixups(dd)
            if 'EXID' in fx:
                exids = struct.unpack_from(f'<{(fx["EXID"][1] - fx["EXID"][0]) // 4}I', dd, fx['EXID'][0])
            if d is None and any(v in gh for v in exids):
                d = dd
        if d is not None and new_n == n and _is_igz(n, d):
            st['shared'] += 1                                      # partage : copie brute, references notees
            cited_text.append(d.lower())
            cited_tokens |= {rev[v] for v in exids if v in rev}
            files.append((new_n, full, ords[n], ('raw', a, e, lock)))
            continue
        if d is not None and _is_igz(n, d):
            nd, s = transform_igz(d, ren, gh, local_extra)
            for key in ('text', 'exid', 'local'):
                st[key] += s[key]
            if nd != d and n.lower().endswith('.igz'):
                nd, nt = rehash_tables(nd, d)
                st['tables'] += nt
            if nd != d:
                st['rewritten'] += 1
                files.append((new_n, full, ords[n], ('data', nd)))
                continue
        files.append((new_n, full, ords[n], ('raw', a, e, lock)))
    # fichiers renommes cites par un fichier partage : aussi sous leur nom d'origine (contenu d'origine) ; ce qu'ils
    # citent a leur tour aussi (t111_level_materials garde -> ses textures « levels!Octane!T111_Crash_Cove!... »)
    nxt = max((o for o in ords.values() if o < 0xFFFFFF), default=-1) + 1
    kept = set()
    while True:
        new_kept = []
        for n in sorted(names):
            if n in kept or ren.name(n) == n:
                continue
            key = os.path.basename(n).rsplit('.', 1)[0].lower()
            kb = key.encode('latin1')
            whole = (kb + b'\0', kb + b'.igz', kb + b'::')    # nom complet (pas un morceau d'un nom plus long)
            if key in cited_tokens or any(w in t for t in cited_text for w in whole):
                new_kept.append(n)
        if not new_kept:
            break
        cited_text = []
        for n in new_kept:
            kept.add(n)
            a, e, lock = srcs[n]
            full = e.name if e.name.lower().endswith(n.lower()) else pak_tool.FULL_PREFIX + n
            files.append((n, full, nxt, ('raw', a, e, lock)))
            nxt += 1
            st['kept_originals'] += 1
            if n.lower().endswith('.igz'):
                cited_text.append(_read(srcs[n]).lower())
    write_archive(out_path, files, os.path.join(archives, pak_name if extra is None else src.lower() + '.pak'))
    return st


def _read_any(archives, logical, paks):
    for p in paks:
        path = os.path.join(archives, p)
        if not pak_tool.exists(path):
            continue
        a, idx, lock = _view(path)
        e = idx.get(logical.lower())
        if e is not None:
            with lock:
                return a.read(e)
    raise KeyError(logical)


def registration_files(archives, src, new, display=None):
    """{nom logique: octets} a ajouter a update2.pak pour la zone : zoneInfo + .lng (le chunkInfos est fait par
    register_chunkinfos, pour toutes les pistes a la fois)."""
    import menu_assets
    ren = Renamer(src, new)
    out = {}
    zi = _read_any(archives, zoneinfo_logical(src), pak_tool.UPDATE_ARCHIVES + (src.lower() + '.pak',))
    zi2, _ = transform_igz(zi, ren, {}, [src, src.lower()])
    out[zoneinfo_logical(new)], _ = rehash_tables(zi2, zi)
    for lang in LANGS:
        try:
            d = _read_any(archives, lng_logical(src, lang),
                          pak_tool.UPDATE_ARCHIVES + ('chunkinfos.pak', src.lower() + '.pak'))
        except KeyError:
            continue
        d, _ = transform_igz(d, ren, {}, [src, src.lower()])
        if display:
            d = menu_assets.write_name(d, display)
        out[lng_logical(new, lang)] = d
    return out


def register_chunkinfos(archives, track_ids):
    import pkg_manifest
    data = _read_any(archives, CHUNKINFOS, pak_tool.UPDATE_ARCHIVES)
    entries = []
    for t in track_ids:
        entries += [('lang_file', lng_logical(t, lang).lower()) for lang in LANGS]
        entries.append(('igx_file', zoneinfo_logical(t)))
    data, _ = pkg_manifest.add_entries(data, entries)
    return data


def chunks_igx_set(game_dir, pak_files):
    """Ajoute / retire nos archives dans chunks.igx (liste des fichiers installes, 1er groupe). Sauvegarde
    chunks.igx.ctrmod a la premiere modification. pak_files : noms des archives a y avoir (les autres « t9.. »
    ajoutees par nous sont retirees)."""
    p = pak_tool.real(os.path.join(game_dir, CHUNKS_IGX))     # jeu en deux dossiers : celui de la mise a jour
    if not os.path.exists(p):
        return False
    txt = open(p, encoding='utf-8', newline='').read()
    if not os.path.exists(p + '.ctrmod'):
        open(p + '.ctrmod', 'w', encoding='utf-8', newline='').write(txt)
    orig = open(p + '.ctrmod', encoding='utf-8', newline='').read()
    m = re.search(r'(<object refname="igStringRefList" type="igStringRefList" count=")(\d+)(">\n)', orig)
    if not m:
        raise RuntimeError('chunks.igx : liste des fichiers introuvable')
    lines = ''.join(f'\t\t<listitem value="archives/{f.lower()}" />\n' for f in pak_files)
    new = orig[:m.start()] + m.group(1) + str(int(m.group(2)) + len(pak_files)) + m.group(3) + lines + orig[m.end():]
    if not pak_files:
        new = orig
    if new != txt:
        open(p, 'w', encoding='utf-8', newline='').write(new)
    return True


def create(archives, src, n=None, display=None, out_dir=None, progress=None, overwrite=False):
    """Cree la piste (archives .pak renommees) ; retourne (identifiant, [archives ecrites], stats).
    out_dir : dossier de sortie (essai) ; par defaut le dossier des archives du jeu (nouveaux fichiers seulement).
    overwrite : refait les archives d'une piste deja creee par nous (numero n)."""
    out_dir = out_dir or archives
    taken = {f.lower() for f in pak_tool.listdir(archives)} | {f.lower() for f in pak_tool.listdir(out_dir)}
    if n is None:
        n = next(k for k in range(1, 100) if new_id(src, k).lower() + '.pak' not in taken)
    new = new_id(src, n)
    if new.lower() + '.pak' in taken and not overwrite:
        raise RuntimeError(f'{new} existe deja')
    ren = Renamer(src, new)
    written, stats = [], {}
    jobs = [(new.lower() + '.pak', src.lower() + '.pak', source_files(archives, src))]
    jobs += [(ren.name(fp).lower(), fp, None) for fp in flyby_paks(archives, src)]
    for dst, pak, extra in jobs:
        out = os.path.join(out_dir, dst)
        for f in (pak_tool.backup_path(out), pak_tool.toc_backup_path(out)):
            if overwrite and os.path.exists(f):
                os.remove(f)                     # installation de l'editeur sur l'ancienne copie : caduque
        stats[dst] = clone_pak(archives, src, new, pak, out + '.tmp', extra=extra,
                               progress=progress if extra is not None else None)
        try:
            os.replace(out + '.tmp', out)
        except PermissionError:
            raise RuntimeError(f'{dst} est ouverte par un autre programme (editeur sur le port 8765, jeu) : '
                               'ferme-le puis relance la commande') from None
        written.append(dst)
    return new, written, stats


def main(argv):
    if len(argv) < 3 or argv[0] not in ('create', 'build', 'rebuild'):
        print('usage : track_clone.py create <dossier archives> <piste source, ex. T111_Crash_Cove> ["Nom affiche"]\n'
              '        track_clone.py rebuild <dossier archives> <piste creee, ex. T901_Custom_Map>  (la refaire)\n'
              '        track_clone.py build  <dossier archives> <piste source> <dossier de sortie>  (essai)')
        return 1
    import custom_category
    archives, src = argv[1], argv[2]
    if argv[0] == 'rebuild':
        t = next((t for t in (custom_category.read_state(archives) or {}).get('tracks', [])
                  if t['id'].lower() == src.lower()), None)
        if t is None:
            print(f'{src} : piste creee introuvable ({custom_category.state_path(archives)})')
            return 1
        new, written, stats = create(archives, t['source'], int(t['id'][2:4]), t.get('display'), overwrite=True)
        custom_category.add_track(archives, new, t['source'], t.get('display'), written)
        print(f'{new} refaite : {", ".join(written)} ; enregistrement mis a jour (update2.pak, chunks.igx).')
        return 0
    if argv[0] == 'build':
        new, written, stats = create(archives, src, out_dir=argv[3])
        reg = registration_files(archives, src, new, 'Custom Track')
        for k, v in reg.items():
            p = os.path.join(argv[3], k.replace('/', '_'))
            open(p, 'wb').write(v)
        print(new, json.dumps(stats, indent=1))
        return 0
    display = argv[3] if len(argv) > 3 else 'Custom Track'
    new, written, stats = create(archives, src, display=display)
    print(f'{new} : {", ".join(written)} ecrites dans {archives}')
    custom_category.add_track(archives, new, src, display, written)
    print('Zone enregistree (update2.pak, chunks.igx) et ajoutee a la categorie « Custom ».')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
