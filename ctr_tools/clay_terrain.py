"""Sol en pâte à modeler (essai 2026-11-24, copie ctr_tools_clay) : export pour le jeu.

L'éditeur (editor/clay.js) garde le sol comme un volume : champ F = z - (sol du relief) + D, D = retouches (Étirer,
outils en volume, ponts de terre, tunnels) par blocs de 16³ points tous les 4 m (entiers 16 bits = pouces / 4, base64).

Export MIXTE (poids du jeu) : le relief habituel partout, et la pâte seulement là où elle diffère du relief (retouches
+ 16 m de marge). Les cases du relief de ces zones sont retirées ; la pâte y est maillée (surface nets, 4 m, grille
alignée sur celle du relief). Couture exacte : au bord de la zone, les sommets de la pâte sont posés SUR les arêtes du
relief, à sa hauteur (interpolée le long de l'arête, comme le maillage du relief) : pas de fente.
Textures : le jeu n'a pas la projection triplanaire de l'éditeur -> projection par triangle (dessus x, y ; côté x, z
ou y, z), sommets doublés au besoin."""
import base64

import numpy as np

VOX = 4.0                     # m : voxel des retouches dans l'éditeur (clay.js V = 4 * IN pouces)
CH = 16                       # points par bloc et par axe
INCH = 39.37
MARGIN_CELLS = 2              # cases du relief (8 m) autour des retouches : la pâte rejoint le relief à plat
D_MIN = 0.1                   # m : retouche plus petite que ça = rien


def decode(clay):
    """{(cx, cy, cz): tableau [z, y, x] (m)} depuis terrain['clay'] du brouillon."""
    out = {}
    if not clay or clay.get('voxel') is None or abs(clay['voxel'] / INCH - VOX) > 1e-3 or clay.get('ch') != CH:
        return out
    for k, b in (clay.get('chunks') or {}).items():
        a = np.frombuffer(base64.b64decode(b), '<i2')
        if a.size != CH ** 3:
            continue
        cx, cy, cz = (int(v) for v in k.split(','))
        arr = a.astype(np.float32).reshape(CH, CH, CH) * 4.0 / INCH
        if np.abs(arr).max() >= D_MIN:
            out[(cx, cy, cz)] = arr
    return out


def _dense(chunks):
    """Retouches en un tableau dense [z, y, x] (m) + indice du premier point (ix0, iy0, iz0)."""
    ks = np.array(list(chunks))
    lo, hi = ks.min(0), ks.max(0)
    shape = ((hi[2] - lo[2] + 1) * CH, (hi[1] - lo[1] + 1) * CH, (hi[0] - lo[0] + 1) * CH)
    D = np.zeros(shape, np.float32)
    for (cx, cy, cz), a in chunks.items():
        z, y, x = (cz - lo[2]) * CH, (cy - lo[1]) * CH, (cx - lo[0]) * CH
        D[z:z + CH, y:y + CH, x:x + CH] = a
    return D, (lo[0] * CH, lo[1] * CH, lo[2] * CH)


def _trilinear(D, o, X, Y, Z):
    """Retouche interpolée aux points (m) ; hors du tableau : 0."""
    gx, gy, gz = X / VOX - o[0], Y / VOX - o[1], Z / VOX - o[2]
    ix, iy, iz = np.floor(gx).astype(np.int64), np.floor(gy).astype(np.int64), np.floor(gz).astype(np.int64)
    u, v, w = gx - ix, gy - iy, gz - iz
    nz, ny, nx = D.shape
    out = np.zeros(np.broadcast(X, Y, Z).shape, np.float32)
    for c in range(8):
        a, b, e = c & 1, (c >> 1) & 1, c >> 2
        jx, jy, jz = ix + a, iy + b, iz + e
        ok = (jx >= 0) & (jx < nx) & (jy >= 0) & (jy < ny) & (jz >= 0) & (jz < nz)
        val = np.where(ok, D[np.clip(jz, 0, nz - 1), np.clip(jy, 0, ny - 1), np.clip(jx, 0, nx - 1)], 0.0)
        out += val * (u if a else 1 - u) * (v if b else 1 - v) * (w if e else 1 - w)
    return out


def _bilinear(xs, ys, H, X, Y):
    fx = np.clip((X - xs[0]) / (xs[1] - xs[0]), 0, len(xs) - 1.000001)
    fy = np.clip((Y - ys[0]) / (ys[1] - ys[0]), 0, len(ys) - 1.000001)
    i, j = np.minimum(fx.astype(np.int64), len(xs) - 2), np.minimum(fy.astype(np.int64), len(ys) - 2)
    u, v = fx - i, fy - j
    return (H[j, i] * (1 - u) + H[j, i + 1] * u) * (1 - v) + (H[j + 1, i] * (1 - u) + H[j + 1, i + 1] * u) * v


def _dilate(m, r):
    out = m.copy()
    for _ in range(r):
        o = out.copy()
        o[1:, :] |= out[:-1, :]; o[:-1, :] |= out[1:, :]; o[:, 1:] |= out[:, :-1]; o[:, :-1] |= out[:, 1:]
        o[1:, 1:] |= out[:-1, :-1]; o[:-1, :-1] |= out[1:, 1:]; o[1:, :-1] |= out[:-1, 1:]; o[:-1, 1:] |= out[1:, :-1]
        out = o
    return out


TILE = 48                     # cases de voxels par carreau de calcul (192 m) : memoire bornee quelle que soit la carte

EDGES = [(0, 1), (2, 3), (4, 5), (6, 7), (0, 2), (1, 3), (4, 6), (5, 7), (0, 4), (1, 5), (2, 6), (3, 7)]
CORNER = [(a, b, d) for a in (0, 1) for b in (0, 1) for d in (0, 1)]        # (dz, dy, dx), indice = 4 dz + 2 dy + dx


def clay_patch(clay, xs, ys, H):
    """-> None (rien d'étiré) ou dict : hide [ny-1, nx-1] (cases du relief remplacées), verts (N, 3) m,
    tris (M, 3) indices, cells (M, 2) case du relief (a, b) de chaque triangle (matière)."""
    chunks = decode(clay)
    if not chunks or len(xs) < 3 or len(ys) < 3:
        return None
    D, o = _dense(chunks)
    cell = float(xs[1] - xs[0])
    h = cell / 2                                             # voxels de l'export : 2 par case du relief (4 m)
    nxv, nyv = 2 * (len(xs) - 1) + 1, 2 * (len(ys) - 1) + 1
    PX, PY = xs[0] + np.arange(nxv) * h, ys[0] + np.arange(nyv) * h
    # zone : colonnes (4 m) ou la retouche depasse D_MIN, en cases du relief, + marge
    big = np.abs(D) >= D_MIN
    ey, ex = np.nonzero(big.any(0))
    if not len(ex):
        return None
    wx, wy = (ex + o[0]) * VOX, (ey + o[1]) * VOX
    ca = np.clip(((wx - xs[0]) // cell).astype(np.int64), 0, len(xs) - 2)
    cb = np.clip(((wy - ys[0]) // cell).astype(np.int64), 0, len(ys) - 2)
    region = np.zeros((len(ys) - 1, len(xs) - 1), bool)
    region[cb, ca] = True
    region = _dilate(region, MARGIN_CELLS)
    # cases de voxels : 1 dans la zone, 2 anneau juste dehors (sommets poses sur le bord), 0 dehors
    colR = np.repeat(np.repeat(region, 2, 0), 2, 1).astype(np.int8)
    colR[_dilate(colR == 1, 1) & (colR == 0)] = 2
    R1 = colR == 1
    zcol = np.nonzero(big.any((1, 2)))[0]                    # etendue en z des retouches (grille de l'editeur)
    dz0, dz1 = (zcol.min() + o[2]) * VOX, (zcol.max() + o[2]) * VOX
    jj, ii = np.nonzero(colR)
    VS, TS, CS = [], [], []
    nv = 0
    for tb in range(jj.min(), jj.max() + 1, TILE):
        for ta in range(ii.min(), ii.max() + 1, TILE):
            if not colR[tb:tb + TILE, ta:ta + TILE].any():
                continue
            # points [ta-1, ta+TILE+1] : une case de plus autour (aretes du bord du carreau)
            i0, i1 = max(0, ta - 1), min(nxv - 1, ta + TILE + 1)
            j0, j1 = max(0, tb - 1), min(nyv - 1, tb + TILE + 1)
            Hb = _bilinear(xs, ys, H, PX[None, i0:i1 + 1], PY[j0:j1 + 1, None])
            zlo, zhi = min(float(Hb.min()), dz0) - 2 * h, max(float(Hb.max()), dz1) + 2 * h
            PZ = zlo + np.arange(int(np.ceil((zhi - zlo) / h)) + 1) * h
            X, Y, Z = PX[None, None, i0:i1 + 1], PY[None, j0:j1 + 1, None], PZ[:, None, None]
            F = ((Z - Hb[None]) + _trilinear(D, o, X, Y, Z)).astype(np.float32)   # [k, j, i]
            v, t, cl = _mesh(F, PX, PY, PZ, i0, j0, colR, R1, xs, ys, H, h, ta, tb, nxv, nyv)
            if len(t):
                VS.append(v); TS.append(t + nv); CS.append(cl); nv += len(v)
    if not TS:
        return None
    V, T = np.concatenate(VS), np.concatenate(TS)
    cen = V[T].mean(1)
    ca = np.clip(((cen[:, 0] - xs[0]) // cell).astype(np.int64), 0, len(xs) - 2)
    cb = np.clip(((cen[:, 1] - ys[0]) // cell).astype(np.int64), 0, len(ys) - 2)
    return {'hide': region, 'verts': V, 'tris': T, 'cells': np.stack([ca, cb], 1), 'D': D, 'o': o}


def _mesh(F, PX, PY, PZ, i0, j0, colR, R1, xs, ys, H, h, ta, tb, nxv, nyv):
    """Surface nets d'un carreau. -> (sommets (n, 3), triangles (m, 3), rien)"""
    nz, ny, nx = F.shape
    c = [F[a:nz - 1 + a, b:ny - 1 + b, d:nx - 1 + d] for (a, b, d) in CORNER]
    sgn = [ci < 0 for ci in c]
    anyS, allS = np.zeros_like(sgn[0]), np.ones_like(sgn[0])
    for s_ in sgn:
        anyS |= s_
        allS &= s_
    cross = anyS & ~allS & (colR[j0:j0 + ny - 1, i0:i0 + nx - 1] > 0)[None]
    acc = np.zeros(cross.shape + (3,), np.float32)
    cnt = np.zeros(cross.shape, np.float32)
    for p, q in EDGES:
        e = (sgn[p] != sgn[q]) & cross
        den = c[p] - c[q]
        t = np.where(e, c[p] / np.where(den == 0, 1, den), 0)
        for ax in range(3):
            acc[..., ax] += np.where(e, CORNER[p][ax] + (CORNER[q][ax] - CORNER[p][ax]) * t, 0)
        cnt += e
    ks, js, is_ = np.nonzero(cross)
    if not len(ks):
        return np.zeros((0, 3)), np.zeros((0, 3), np.int64), None
    off = acc[ks, js, is_] / cnt[ks, js, is_, None]
    gi, gj = i0 + is_, j0 + js                               # case de voxels (indices globaux)
    vx, vy, vz = PX[gi] + off[:, 2] * h, PY[gj] + off[:, 1] * h, PZ[ks] + off[:, 0] * h
    # anneau : sommet pose sur le bord de la zone (ligne de la grille du relief), a la hauteur du relief
    rr = colR[gj, gi] == 2
    if rr.any():
        def inR(j, i):
            ok = (j >= 0) & (j < R1.shape[0]) & (i >= 0) & (i < R1.shape[1])
            return ok & R1[np.clip(j, 0, R1.shape[0] - 1), np.clip(i, 0, R1.shape[1] - 1)]
        rj, ri = gj[rr], gi[rr]
        lf, rt, dn, up = inR(rj, ri - 1), inR(rj, ri + 1), inR(rj - 1, ri), inR(rj + 1, ri)
        sx = np.where(rt, PX[np.minimum(ri + 1, nxv - 1)], np.where(lf, PX[ri], vx[rr]))
        sy = np.where(up, PY[np.minimum(rj + 1, nyv - 1)], np.where(dn, PY[rj], vy[rr]))
        diag = ~(lf | rt | dn | up)                          # coin : la case de la zone est en diagonale
        for dj, di in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
            m = diag & inR(rj + dj, ri + di)
            sx = np.where(m, PX[np.clip(ri + (di > 0), 0, nxv - 1)], sx)
            sy = np.where(m, PY[np.clip(rj + (dj > 0), 0, nyv - 1)], sy)
        vx[rr], vy[rr] = sx, sy
        vz[rr] = _bilinear(xs, ys, H, sx, sy)
    vid = -np.ones(cross.shape, np.int64)
    vid[ks, js, is_] = np.arange(len(ks))
    quads = []
    for ax in range(3):                                      # 0 : x, 1 : y, 2 : z
        if ax == 0:
            a0, a1 = F[:, :, :-1], F[:, :, 1:]
        elif ax == 1:
            a0, a1 = F[:, :-1, :], F[:, 1:, :]
        else:
            a0, a1 = F[:-1, :, :], F[1:, :, :]
        kk, jy, ix = np.nonzero((a0 < 0) != (a1 < 0))
        own = (i0 + ix >= ta) & (i0 + ix < ta + TILE) & (j0 + jy >= tb) & (j0 + jy < tb + TILE)   # arete de ce carreau
        kk, jy, ix = kk[own], jy[own], ix[own]
        solid0 = a0[kk, jy, ix] < 0
        if ax == 0:
            cs = [(kk - 1, jy - 1, ix), (kk - 1, jy, ix), (kk, jy, ix), (kk, jy - 1, ix)]
        elif ax == 1:
            cs = [(kk - 1, jy, ix - 1), (kk, jy, ix - 1), (kk, jy, ix), (kk - 1, jy, ix)]
        else:
            cs = [(kk, jy - 1, ix - 1), (kk, jy - 1, ix), (kk, jy, ix), (kk, jy, ix - 1)]
        ok = np.ones(len(kk), bool)
        inzone = np.zeros(len(kk), bool)
        ids = []
        for (a, b, d) in cs:
            inside = (a >= 0) & (a < cross.shape[0]) & (b >= 0) & (b < cross.shape[1]) & (d >= 0) & (d < cross.shape[2])
            v = np.where(inside, vid[np.clip(a, 0, cross.shape[0] - 1), np.clip(b, 0, cross.shape[1] - 1), np.clip(d, 0, cross.shape[2] - 1)], -1)
            ok &= v >= 0
            ids.append(v)
            inzone |= R1[np.clip(j0 + b, 0, R1.shape[0] - 1), np.clip(i0 + d, 0, R1.shape[1] - 1)]
        ok &= inzone                                         # tout dans l'anneau : plat, sur le bord -> rien
        q = np.stack(ids, 1)[ok]
        flip = ~solid0[ok]
        q[flip] = q[flip][:, ::-1]
        quads.append(q)
    Q = np.concatenate(quads)
    V = np.stack([vx, vy, vz], 1)
    d02 = np.linalg.norm(V[Q[:, 0]] - V[Q[:, 2]], axis=1)
    d13 = np.linalg.norm(V[Q[:, 1]] - V[Q[:, 3]], axis=1)
    A = np.where((d02 <= d13)[:, None], Q[:, [0, 1, 2]], Q[:, [0, 1, 3]])
    B = np.where((d02 <= d13)[:, None], Q[:, [0, 2, 3]], Q[:, [1, 2, 3]])
    T = np.concatenate([A, B])
    area = np.linalg.norm(np.cross(V[T[:, 1]] - V[T[:, 0]], V[T[:, 2]] - V[T[:, 0]]), axis=1)
    return V, T[area > 1e-6], None


def field(patch, xs, ys, H, x, y, z):
    """Champ (m) au point (m) : négatif dans la matière. Un seul point : calcul direct en Python (numpy coûte trop cher
    pour un point, 2026-11-24 : pose des objets 5 fois plus rapide)."""
    x0, dx, y0, dy = float(xs[0]), float(xs[1] - xs[0]), float(ys[0]), float(ys[1] - ys[0])
    fx = min(max((x - x0) / dx, 0.0), len(xs) - 1.000001)
    fy = min(max((y - y0) / dy, 0.0), len(ys) - 1.000001)
    i, j = min(int(fx), len(xs) - 2), min(int(fy), len(ys) - 2)
    u, v = fx - i, fy - j
    h = (H[j, i] * (1 - u) + H[j, i + 1] * u) * (1 - v) + (H[j + 1, i] * (1 - u) + H[j + 1, i + 1] * u) * v
    Dd, o = patch['D'], patch['o']
    gx, gy, gz = x / VOX - o[0], y / VOX - o[1], z / VOX - o[2]
    ix, iy, iz = int(np.floor(gx)), int(np.floor(gy)), int(np.floor(gz))
    a, b, c = gx - ix, gy - iy, gz - iz
    nz, ny, nx = Dd.shape
    d = 0.0
    if -1 <= ix < nx and -1 <= iy < ny and -1 <= iz < nz:
        for k in (0, 1):
            zk = iz + k
            if not 0 <= zk < nz:
                continue
            wk = c if k else 1 - c
            for jj in (0, 1):
                yj = iy + jj
                if not 0 <= yj < ny:
                    continue
                wj = b if jj else 1 - b
                for ii in (0, 1):
                    xi = ix + ii
                    if 0 <= xi < nx:
                        d += float(Dd[zk, yj, xi]) * wk * wj * (a if ii else 1 - a)
    return float(z - h + d)


def surface_z(patch, xs, ys, H, x, y, hint):
    """Surface (air au-dessus, matière dessous) à la verticale de (x, y) m, la plus proche de la hauteur hint (m) :
    d'abord en descendant de hint + 6 m, sinon (hint dans la matière) juste au-dessus. -> z (m) ou None."""
    f = lambda z: field(patch, xs, ys, H, x, y, z)
    def refine(za, zb):                                      # za dans l'air, zb dans la matière
        for _ in range(12):
            m = (za + zb) / 2
            if f(m) > 0:
                za = m
            else:
                zb = m
        return (za + zb) / 2
    za = hint + 6.0
    fa = f(za)
    z = za - 1.0
    while z >= hint - 40.0:
        fz = f(z)
        if fa > 0 >= fz:
            return refine(za, z)
        za, fa, z = z, fz, z - 1.0
    if f(hint) < 0:
        z = hint
        while z <= hint + 40.0:
            if f(z + 1.0) > 0:
                return refine(z + 1.0, z)
            z += 1.0
    return None


def edited_at(patch, x, y):
    """Retouche d'au moins D_MIN a moins d'une maille (4 m) de (x, y) m ? (chemin rapide : ailleurs, le relief suffit)."""
    am = patch.get('amax')
    if am is None:
        am = patch['amax'] = np.abs(patch['D']).max(0)
    gx, gy = int(np.floor(x / VOX)) - patch['o'][0], int(np.floor(y / VOX)) - patch['o'][1]
    j0, j1, i0, i1 = max(0, gy - 1), min(am.shape[0], gy + 3), max(0, gx - 1), min(am.shape[1], gx + 3)
    return j1 > j0 and i1 > i0 and bool((am[j0:j1, i0:i1] >= D_MIN).any())


def covered(patch, xs, ys, H, x, y, z):
    """Matière au-dessus du point (dans les 80 m) : sous une voûte, dans un tunnel ou une cave."""
    h = z + 2.0
    while h <= z + 80.0:
        if field(patch, xs, ys, H, x, y, h) < 0:
            return True
        h += 2.0
    return False


def top_z(patch, xs, ys, H, x, y):
    """Surface la plus haute à la verticale de (x, y) m (dessus de la colline d'un tunnel, d'une arche)."""
    z = float(_bilinear(xs, ys, H, np.array([x]), np.array([y]))[0]) + 120.0
    while z > -1e4:
        if field(patch, xs, ys, H, x, y, z) < 0:
            return surface_z(patch, xs, ys, H, x, y, z + 1.0)
        z -= 2.0
    return None


def emit(ob, patch, names_of_cell, rep, prefix='CreatorClay'):
    """Triangles de la pâte dans l'OBJ, un objet par matière ; UV par triangle (dessus ou côté). -> matières utilisées."""
    V, T, cells = patch['verts'], patch['tris'], patch['cells']
    n = np.cross(V[T[:, 1]] - V[T[:, 0]], V[T[:, 2]] - V[T[:, 0]])
    an = np.abs(n)
    proj = np.where(an[:, 2] >= 0.6 * an.max(1), 0, np.where(an[:, 0] > an[:, 1], 1, 2))   # 0 dessus, 1 cote y-z, 2 cote x-z
    mats = np.array([names_of_cell(int(a), int(b)) for a, b in cells])
    used = set()
    for m in np.unique(mats):
        sel = np.nonzero(mats == m)[0]
        ob.obj(f'{prefix}_{m}', m)
        used.add(m)
        vid = {}
        for t in sel:
            pr = int(proj[t])
            ids = []
            for v in T[t]:
                key = (int(v), pr)
                if key not in vid:
                    x, y, z = V[v]
                    uv = (x / rep, y / rep) if pr == 0 else (y / rep, z / rep) if pr == 1 else (x / rep, z / rep)
                    vid[key] = ob.vert((float(x), float(y), float(z)), uv)
                ids.append(vid[key])
            ob.poly(ids)
    return used
