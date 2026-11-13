"""Animations Havok du jeu (.hka : packfile hk_2014.1.0-r1, pointeurs 64 bits, petit-boutiste), pour l'apercu des
objets animes de l'editeur. (havok.py = lecteur des collisions .hkx : autre module, ne pas confondre.)

Packfile : en-tete (64 o) + 16 o de bourrage, puis 3 en-tetes de section (__classnames__, __types__, __data__) de
64 o : (debut absolu, correctifs locaux, globaux, virtuels, exports, imports, fin) relatifs au debut de la section.
  * correctifs locaux (src, dst) : pointeur a src -> dst (meme section) ;
  * globaux (src, section, dst) : pointeur vers un objet ;
  * virtuels (src, section des noms, decalage) : objet de classe <nom> a src.
Objets lus (disposition 64 bits, 2014) :
  hkaAnimationContainer +16 skeletons, +32 animations, +48 bindings (hkArray : ptr 8, taille 4, capacite 4)
  hkaSkeleton +16 name, +24 parentIndices (int16), +40 bones (hkaBone 16 o : nom, verrou), +56 referencePose (48 o)
  hkaAnimationBinding +16 originalSkeletonName, +24 animation, +32 transformTrackToBoneIndices (int16)
  hkaAnimation +16 type, +20 duration, +24 numberOfTransformTracks, +28 numberOfFloatTracks
  hkaSplineCompressedAnimation +56 numFrames, +60 numBlocks, +64 maxFramesPerBlock, +68 maskAndQuantizationSize,
    +72 blockDuration, +76 blockInverseDuration, +80 frameDuration, +88 blockOffsets, +104 floatBlockOffsets,
    +120 transformOffsets, +136 floatOffsets, +152 data (uint8)
"""
import math
import struct

import numpy as np


class AnimPackfile:
    def __init__(self, data):
        self.d = data
        m0, m1, _, self.version = struct.unpack_from('<IIii', data, 0)
        if (m0, m1) != (0x57E0E057, 0x10C0C010):
            raise ValueError('pas un fichier Havok')
        nsec = struct.unpack_from('<i', data, 20)[0]
        pad = struct.unpack_from('<h', data, 62)[0]
        off = 64 + max(0, pad)
        self.sections = []
        for _ in range(nsec):
            name = data[off:off + 20].split(b'\0')[0].decode()
            vals = struct.unpack_from('<7i', data, off + 20)
            self.sections.append((name, vals))
            off += 64 if self.version >= 11 else 48
        names = dict((n, v) for n, v in self.sections)
        cn = names['__classnames__']
        self.cn_base = cn[0]
        dv = names['__data__']
        self.base = dv[0]
        b, loc, glo, vir, exp = dv[0], dv[1], dv[2], dv[3], dv[4]
        self.ptr = {}                                  # adresse (relative a __data__) -> cible
        # tables completees par du bourrage (-1) jusqu'a un multiple de 16 : pas toujours un nombre entier d'entrees
        for i in range(loc, glo - 7, 8):
            s, t = struct.unpack_from('<ii', data, b + i)
            if s != -1:
                self.ptr[s] = t
        for i in range(glo, vir - 11, 12):
            s, _, t = struct.unpack_from('<iii', data, b + i)
            if s != -1:
                self.ptr[s] = t
        self.objects = {}                              # adresse -> classe
        for i in range(vir, exp - 11, 12):
            s, _, c = struct.unpack_from('<iii', data, b + i)
            if s != -1:
                self.objects[s] = self._cstr(self.cn_base + c)

    def _cstr(self, a):
        return self.d[a:self.d.index(b'\0', a)].decode('latin1')

    def u8(self, a): return self.d[self.base + a]
    def i16(self, a): return struct.unpack_from('<h', self.d, self.base + a)[0]
    def i32(self, a): return struct.unpack_from('<i', self.d, self.base + a)[0]
    def u32(self, a): return struct.unpack_from('<I', self.d, self.base + a)[0]
    def f32(self, a): return struct.unpack_from('<f', self.d, self.base + a)[0]
    def deref(self, a): return self.ptr.get(a)

    def string(self, a):
        t = self.deref(a)
        return None if t is None else self._cstr(self.base + t)

    def array(self, a):
        """hkArray a l'adresse a -> (adresse des elements ou None, taille)."""
        return self.deref(a), self.i32(a + 8)

    def of_class(self, name):
        return [a for a, c in self.objects.items() if c == name]


def skeleton(pf, a):
    """{'name', 'bones': [noms], 'parents': [int], 'pose': [[tx, ty, tz, qx, qy, qz, qw, sx, sy, sz]]}"""
    pa, pn = pf.array(a + 24)
    ba, bn = pf.array(a + 40)
    ra, rn = pf.array(a + 56)
    parents = [pf.i16(pa + 2 * i) for i in range(pn)] if pa is not None else []
    bones = [pf.string(ba + 16 * i) for i in range(bn)] if ba is not None else []
    pose = []
    for i in range(rn):
        o = ra + 48 * i
        t = struct.unpack_from('<3f', pf.d, pf.base + o)
        q = struct.unpack_from('<4f', pf.d, pf.base + o + 16)
        s = struct.unpack_from('<3f', pf.d, pf.base + o + 32)
        pose.append(list(t) + list(q) + list(s))
    return {'name': pf.string(a + 16), 'bones': bones, 'parents': parents, 'pose': pose}


# hkaAnimation (hkReferencedObject = 12 o ici) : +12 type, +16 duree, +20 pistes de transformation, +24 pistes flottantes,
# +40 annotationTracks (hkaAnnotationTrack 24 o : nom de l'os, annotations)
ROT_SIZE = {0: 4, 1: 5, 2: 6, 3: 3, 4: 2, 5: 16}            # POLAR32, THREECOMP40, THREECOMP48, THREECOMP24, STRAIGHT16, UNCOMPRESSED
ROT_ALIGN = {0: 4, 1: 1, 2: 2, 3: 1, 4: 2, 5: 4}


def _q40(b):
    v = int.from_bytes(b, 'little')
    mask, half = (1 << 12) - 1, ((1 << 12) - 1) >> 1
    f = (1.0 / math.sqrt(2.0)) / half
    c = [((v >> (12 * i)) & mask) - half for i in range(3)]
    c = [x * f for x in c]
    shift, neg = (v >> 36) & 3, (v >> 38) & 1
    w = math.sqrt(max(0.0, 1.0 - sum(x * x for x in c)))
    if neg:
        w = -w
    q = c[:]
    q.insert(shift, w)
    return q


def _q48(b):
    x, y, z = struct.unpack('<3H', b)
    half = 0x3FFF
    f = (1.0 / math.sqrt(2.0)) / half
    shift = ((y >> 14) & 2) | ((x >> 15) & 1)
    neg = (z >> 15) & 1
    c = [((v & 0x7FFF) - half) * f for v in (x, y, z)]
    w = math.sqrt(max(0.0, 1.0 - sum(v * v for v in c)))
    if neg:
        w = -w
    q = c[:]
    q.insert(shift, w)
    return q


def _q32(b):
    v = struct.unpack('<I', b)[0]
    # POLAR32 (rare) : non gere -> identite
    return [0.0, 0.0, 0.0, 1.0]


def _quat(b, kind):
    if kind == 1:
        return _q40(b)
    if kind == 2:
        return _q48(b)
    if kind == 5:
        return list(struct.unpack('<4f', b))
    if kind == 3:
        return _q40(b + b'\0\0')                               # approximation (rare)
    return _q32(b[:4]) if kind == 0 else [0.0, 0.0, 0.0, 1.0]


class _Reader:
    def __init__(self, data, pos=0):
        self.d, self.p = data, pos

    def align(self, n):
        self.p = (self.p + n - 1) // n * n

    def u8(self):
        v = self.d[self.p]
        self.p += 1
        return v

    def u16(self):
        v = struct.unpack_from('<H', self.d, self.p)[0]
        self.p += 2
        return v

    def f32(self):
        v = struct.unpack_from('<f', self.d, self.p)[0]
        self.p += 4
        return v

    def take(self, n):
        v = self.d[self.p:self.p + n]
        self.p += n
        return v


def _span(n, p, u, knots):
    """Intervalle de noeuds (algorithme de de Boor) : n = nb de points de controle - 1."""
    if u >= knots[n + 1]:
        return n
    low, high = p, n + 1
    mid = (low + high) // 2
    while u < knots[mid] or u >= knots[mid + 1]:
        if u < knots[mid]:
            high = mid
        else:
            low = mid
        mid = (low + high) // 2
    return mid


def _bspline(u, p, knots, ctrl):
    """Point d'une B-spline de degre p (ctrl : tableau [n + 1, k])."""
    n = len(ctrl) - 1
    s = _span(n, p, u, knots)
    N = [0.0] * (p + 1)
    N[0] = 1.0
    left, right = [0.0] * (p + 1), [0.0] * (p + 1)
    for j in range(1, p + 1):
        left[j] = u - knots[s + 1 - j]
        right[j] = knots[s + j] - u
        saved = 0.0
        for r in range(j):
            den = right[r + 1] + left[j - r]
            t = N[r] / den if den else 0.0
            N[r] = saved + right[r + 1] * t
            saved = left[j - r] * t
        N[j] = saved
    out = np.zeros(len(ctrl[0]))
    for i in range(p + 1):
        out += N[i] * np.asarray(ctrl[s - p + i])
    return out


def _vector_track(r, flags, quant, default):
    """Piste position / echelle d'un bloc -> fonction(frame locale) -> [x, y, z]."""
    spline = any(flags & (0x10 << i) for i in range(3))
    if spline:
        n_items = r.u16()
        degree = r.u8()
        knots = list(r.take(n_items + degree + 2))
        r.align(4)
        mins, maxs, static = [0.0] * 3, [0.0] * 3, list(default)
        for i in range(3):
            if flags & (0x10 << i):
                mins[i], maxs[i] = r.f32(), r.f32()
            elif flags & (1 << i):
                static[i] = r.f32()
        ctrl = []
        for _ in range(n_items + 1):
            row = list(static)
            for i in range(3):
                if flags & (0x10 << i):
                    q = r.u8() / 255.0 if quant == 0 else r.u16() / 65535.0
                    row[i] = mins[i] + (maxs[i] - mins[i]) * q
            ctrl.append(row)
        r.align(4)
        return lambda t: _bspline(t, degree, knots, ctrl)
    static = list(default)
    for i in range(3):
        if flags & (1 << i):
            static[i] = r.f32()
    return lambda t: np.asarray(static)


def _rotation_track(r, flags, quant):
    size, al = ROT_SIZE[quant], ROT_ALIGN[quant]
    if flags & 0xF0:
        n_items = r.u16()
        degree = r.u8()
        knots = list(r.take(n_items + degree + 2))
        r.align(al)
        ctrl = [_quat(r.take(size), quant) for _ in range(n_items + 1)]
        # meme hemisphere d'un point au suivant (interpolation lineaire des composantes)
        for i in range(1, len(ctrl)):
            if np.dot(ctrl[i], ctrl[i - 1]) < 0:
                ctrl[i] = [-c for c in ctrl[i]]
        r.align(4)

        def f(t):
            q = _bspline(t, degree, knots, ctrl)
            return q / (np.linalg.norm(q) or 1.0)
        return f
    if flags & 0x0F:
        r.align(al)
        q = np.asarray(_quat(r.take(size), quant))
        r.align(4)
        return lambda t: q
    return lambda t: np.array([0.0, 0.0, 0.0, 1.0])


def spline_animation(pf, a):
    """Animation compressee -> {'frames', 'fps', 'tracks' (noms d'os), 'data' : float32 [frames, pistes, 10]
    (tx ty tz qx qy qz qw sx sy sz)}."""
    n_tracks = pf.i32(a + 20)
    num_frames, num_blocks, max_fpb = pf.i32(a + 56), pf.i32(a + 60), pf.i32(a + 64)
    mqs = pf.i32(a + 68)
    frame_dur = pf.f32(a + 80)
    boa, bon = pf.array(a + 88)
    block_offs = [pf.u32(boa + 4 * i) for i in range(bon)]
    da, dn = pf.array(a + 152)
    data = pf.d[pf.base + da:pf.base + da + dn]
    ata, atn = pf.array(a + 40)
    names = [pf.string(ata + 24 * i) for i in range(atn)] if ata is not None else [None] * n_tracks
    out = np.zeros((num_frames, n_tracks, 10), np.float32)
    end = 0
    for b in range(num_blocks):
        r = _Reader(data, block_offs[b])
        masks = [tuple(r.take(4)) for _ in range(n_tracks)]
        r.p = block_offs[b] + mqs
        r.align(4)
        fns = []
        for qt, pt, rt, st in masks:
            pos = _vector_track(r, pt, qt & 3, (0.0, 0.0, 0.0))
            rot = _rotation_track(r, rt, (qt >> 2) & 0xF)
            scl = _vector_track(r, st, (qt >> 6) & 3, (1.0, 1.0, 1.0))
            fns.append((pos, rot, scl))
        end = r.p
        f0 = b * (max_fpb - 1)
        f1 = min(num_frames, f0 + max_fpb)
        for f in range(f0, f1):
            t = float(f - f0)
            for k, (pos, rot, scl) in enumerate(fns):
                out[f, k, 0:3] = pos(t)
                out[f, k, 3:7] = rot(t)
                out[f, k, 7:10] = scl(t)
    return {'frames': num_frames, 'fps': (1.0 / frame_dur) if frame_dur else 30.0, 'tracks': names, 'data': out,
            'read_end': end, 'size': dn}


def animations(data):
    """{nom: animation} des animations d'un fichier (noms : table « animTable » dans l'ordre des liaisons)."""
    pf = AnimPackfile(data)
    table = None
    for a in pf.of_class('hkaSkeleton'):
        sk = skeleton(pf, a)
        if sk['name'] == 'animTable':
            table = sk['bones']
    c = pf.of_class('hkaAnimationContainer')[0]
    ba, bn = pf.array(c + 48)
    out = {}
    for i in range(bn):
        bind = pf.deref(ba + 8 * i)
        anim = pf.deref(bind + 24)
        name = table[i] if table and i < len(table) else f'anim{i}'
        if pf.objects.get(anim) == 'hkaSplineCompressedAnimation':
            out[name] = (pf, anim, bind)
    return out


INCH = 39.37        # animations Havok en metres, skins du jeu en pouces


def _qs_matrix(t, q, s):
    """hkQsTransform -> matrice 4x4 (convention vecteur-ligne : v' = v M, translation sur la derniere ligne)."""
    x, y, z, w = q
    R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w)],
                  [2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w)],
                  [2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y)]])
    M = np.eye(4)
    M[:3, :3] = np.diag(s) @ R
    M[3, :3] = t
    return M


def skin_skeleton(z):
    """Squelette d'un skin d'acteur (IgzFile) : {'names', 'parents', 'blend' (index de matrice ou -1), 'inv' [n_blend, 4, 4]}."""
    sk = next(o for o, t in z.objects.items() if t == 'igSkeleton2')
    d = z.dump_object(sk)
    lst = d['_boneList']['@ref']
    items = z.dump_object(int(lst, 16)).get('@items') or []
    bones = [z.dump_object(int(it['@ref'], 16)) for it in items]
    mem = d['_inverseJointArray']
    mb, mo = z._loc(int(mem['@mem'], 16))
    inv = np.frombuffer(bytes(mb[mo:mo + mem['size']]), np.float32).reshape(-1, 4, 4).astype(np.float64)
    return {'names': [b['_name'] for b in bones], 'parents': [b['_parentIndex'] for b in bones],
            'blend': [b['_blendMatrixIndex'] for b in bones], 'inv': inv}


def skin_matrices(skel, anim):
    """Matrices de deformation par image : float32 [images, n_blend, 4, 4] (liaison inverse x os anime).
    anim : spline_animation(...) ou None (pose de liaison : identites)."""
    names, parents, blend, inv = skel['names'], skel['parents'], skel['blend'], skel['inv']
    n = len(names)
    bind_world = [np.linalg.inv(inv[b]) if b >= 0 else np.eye(4) for b in blend]
    bind_local = []
    for i in range(n):
        p = parents[i]
        bind_local.append(bind_world[i] @ np.linalg.inv(bind_world[p]) if p >= 0 else bind_world[i])
    track = {nm: k for k, nm in enumerate(anim['tracks'])} if anim else {}
    frames = anim['frames'] if anim else 1
    out = np.zeros((frames, len(inv), 4, 4), np.float32)
    for f in range(frames):
        world = [None] * n
        for i in range(n):
            k = track.get(names[i])
            if k is not None:
                v = anim['data'][f, k]
                local = _qs_matrix(v[0:3] * INCH, v[3:7], v[7:10])
            else:
                local = bind_local[i]
            p = parents[i]
            world[i] = local @ world[p] if p >= 0 else local
        for i in range(n):
            if blend[i] >= 0:
                out[f, blend[i]] = inv[blend[i]] @ world[i]
    return out


def summary(data):
    pf = AnimPackfile(data)
    out = {'version': pf.version, 'classes': {}}
    for c in pf.objects.values():
        out['classes'][c] = out['classes'].get(c, 0) + 1
    return pf, out
