"""Edition de zones du maillage de collision (sol compresse) : selection, deplacement, suppression.

    reg = GroundEditor(octets_hkx)
    prims = reg.select_box(lo, hi)                    # coordonnees du jeu (pouces)
    prims = reg.select_near_mesh(triangles_monde, tol)  # triangles du sol qui « collent » a un modele
    reg.transform(prims, matrice_4x4_monde)           # applique une transformation (pouces)
    reg.delete(prims)
    octets = reg.to_bytes()                           # re-encode les maillages modifies + compound

Les maillages modifies sont re-encodes (cms_codec : aller-retour exact a 0,3 mm, valide en jeu) ;
l'arbre du compound est neutralise et son domaine agrandi (collision_edit).
"""
import collections
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cms_codec import Prim, encode_mesh, read_mesh, write_mesh  # noqa: E402
from collision_edit import CollisionFile  # noqa: E402
from havok import Packfile  # noqa: E402
from havok_writer import PackfileWriter  # noqa: E402

G = 39.37          # pouces par metre


def mat_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def mat_inv_rigid_scale(m):
    """Inverse d'une matrice 4x4 rotation * echelle + translation (generale 3x3)."""
    a = [row[:3] for row in m[:3]]
    det = (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1]) - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
           + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))
    inv = [[(a[(j + 1) % 3][(i + 1) % 3] * a[(j + 2) % 3][(i + 2) % 3] - a[(j + 1) % 3][(i + 2) % 3] * a[(j + 2) % 3][(i + 1) % 3]) / det
            for j in range(3)] for i in range(3)]
    t = [-sum(inv[i][k] * m[k][3] for k in range(3)) for i in range(3)]
    return [inv[0] + [t[0]], inv[1] + [t[1]], inv[2] + [t[2]], [0, 0, 0, 1]]


def apply(m, p):
    return tuple(m[i][0] * p[0] + m[i][1] * p[1] + m[i][2] * p[2] + m[i][3] for i in range(3))


def object_matrix(pos, euler, scale):
    """Matrice monde (pouces) d'un objet de decor : T * Rz*Ry*Rx * S."""
    cx, sx, cy, sy, cz, sz = (math.cos(euler[0]), math.sin(euler[0]), math.cos(euler[1]), math.sin(euler[1]),
                              math.cos(euler[2]), math.sin(euler[2]))
    R = [[cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx],
         [sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx],
         [-sy, cy * sx, cy * cx]]
    return [[R[i][0] * scale[0], R[i][1] * scale[1], R[i][2] * scale[2], pos[i]] for i in range(3)] + [[0, 0, 0, 1]]


def _pt_tri_dist(p, a, b, c):
    """Distance point-triangle (Ericson, Real-Time Collision Detection 5.1.5)."""
    sub = lambda u, v: (u[0] - v[0], u[1] - v[1], u[2] - v[2])
    dot = lambda u, v: u[0] * v[0] + u[1] * v[1] + u[2] * v[2]
    ab, ac, ap = sub(b, a), sub(c, a), sub(p, a)
    d1, d2 = dot(ab, ap), dot(ac, ap)
    if d1 <= 0 and d2 <= 0:
        return math.dist(p, a)
    bp = sub(p, b)
    d3, d4 = dot(ab, bp), dot(ac, bp)
    if d3 >= 0 and d4 <= d3:
        return math.dist(p, b)
    vc = d1 * d4 - d3 * d2
    if vc <= 0 and d1 >= 0 and d3 <= 0:
        t = d1 / (d1 - d3)
        return math.dist(p, (a[0] + ab[0] * t, a[1] + ab[1] * t, a[2] + ab[2] * t))
    cp = sub(p, c)
    d5, d6 = dot(ab, cp), dot(ac, cp)
    if d6 >= 0 and d5 <= d6:
        return math.dist(p, c)
    vb = d5 * d2 - d1 * d6
    if vb <= 0 and d2 >= 0 and d6 <= 0:
        t = d2 / (d2 - d6)
        return math.dist(p, (a[0] + ac[0] * t, a[1] + ac[1] * t, a[2] + ac[2] * t))
    va = d3 * d6 - d5 * d4
    if va <= 0 and (d4 - d3) >= 0 and (d5 - d6) >= 0:
        t = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        return math.dist(p, (b[0] + (c[0] - b[0]) * t, b[1] + (c[1] - b[1]) * t, b[2] + (c[2] - b[2]) * t))
    den = 1.0 / (va + vb + vc)
    v, w = vb * den, vc * den
    return math.dist(p, (a[0] + ab[0] * v + ac[0] * w, a[1] + ab[1] * v + ac[1] * w, a[2] + ab[2] * v + ac[2] * w))


class GroundEditor:
    def __init__(self, hkx):
        self.raw = bytes(hkx)
        pf = self.pf = Packfile(self.raw)
        comp = next(o for o, c in pf.objects.items() if c == 'hknpStaticCompoundShape')
        io, n = pf.array(comp + 0x60)
        self.meshes = []            # {'instance', 'shape', 'to_world' (pouces), 'mesh', 'dirty'}
        for i in range(n):
            b = io + i * 128
            shape = pf.ptr(b + 0x50)
            if pf.objects.get(shape) != 'hknpCompressedMeshShape':
                continue
            m = pf.floats(b, 16)
            sc = pf.floats(b + 0x40, 3)
            # colonne-majeur (colonnes de rotation, translation en m) -> pouces
            to_world = [[m[0 + r] * sc[0] * G, m[4 + r] * sc[1] * G, m[8 + r] * sc[2] * G, m[12 + r] * G] for r in range(3)]
            to_world.append([0, 0, 0, 1])
            self.meshes.append({'instance': i, 'shape': shape, 'to_world': to_world,
                                'mesh': read_mesh(pf, shape), 'dirty': False})

    def prims_world(self):
        """[(indice maillage, indice primitive, sommets monde)]"""
        for mi, m in enumerate(self.meshes):
            for pi, p in enumerate(m['mesh'].prims):
                yield mi, pi, [apply(m['to_world'], v) for v in p.verts]

    def select_box(self, lo, hi):
        return [(mi, pi) for mi, pi, vs in self.prims_world()
                if all(all(lo[k] <= v[k] <= hi[k] for k in range(3)) for v in vs)]

    def select_near_mesh(self, tris, tol=4.0, cell=200.0):
        """Primitives dont TOUS les sommets sont a moins de tol (pouces) de la surface donnee (triangles monde)."""
        grid = collections.defaultdict(list)
        for t in tris:
            lo = [min(v[k] for v in t) - tol for k in range(3)]
            hi = [max(v[k] for v in t) + tol for k in range(3)]
            for gx in range(int(lo[0] // cell), int(hi[0] // cell) + 1):
                for gy in range(int(lo[1] // cell), int(hi[1] // cell) + 1):
                    for gz in range(int(lo[2] // cell), int(hi[2] // cell) + 1):
                        grid[(gx, gy, gz)].append(t)

        def near(p):
            for t in grid.get((int(p[0] // cell), int(p[1] // cell), int(p[2] // cell)), ()):
                if _pt_tri_dist(p, *t) <= tol:
                    return True
            return False
        return [(mi, pi) for mi, pi, vs in self.prims_world() if all(near(v) for v in vs)]

    def grow_connected(self, seeds, box=None, same_surface=True, eps=0.01):
        """Etend une selection aux primitives voisines (sommet commun, a eps m pres dans le repere du maillage)
        de meme surface que la graine qui les atteint, sans sortir de box (lo, hi en pouces) si donnee."""
        sel = set(seeds)
        index = collections.defaultdict(list)          # (maillage, sommet arrondi) -> primitives
        key = lambda v: (round(v[0] / eps), round(v[1] / eps), round(v[2] / eps))
        for mi, m in enumerate(self.meshes):
            for pi, p in enumerate(m['mesh'].prims):
                for v in p.verts:
                    index[(mi, key(v))].append(pi)

        def inside(mi, pi):
            if box is None:
                return True
            w = [apply(self.meshes[mi]['to_world'], v) for v in self.meshes[mi]['mesh'].prims[pi].verts]
            return all(all(box[0][k] <= v[k] <= box[1][k] for k in range(3)) for v in w)
        stack = list(sel)
        while stack:
            mi, pi = stack.pop()
            p = self.meshes[mi]['mesh'].prims[pi]
            for v in p.verts:
                for qi in index[(mi, key(v))]:
                    if (mi, qi) in sel:
                        continue
                    q = self.meshes[mi]['mesh'].prims[qi]
                    if same_surface and q.value != p.value:
                        continue
                    if inside(mi, qi):
                        sel.add((mi, qi))
                        stack.append((mi, qi))
        return sorted(sel)

    def transform(self, sel, world_matrix):
        """Applique une transformation monde (4x4, pouces) aux primitives selectionnees."""
        for mi, pi in sel:
            m = self.meshes[mi]
            to_local = mat_inv_rigid_scale(m['to_world'])
            full = mat_mul(to_local, mat_mul(world_matrix, m['to_world']))
            p = m['mesh'].prims[pi]
            p.verts = [apply(full, v) for v in p.verts]
            m['dirty'] = True

    def delete(self, sel):
        """Suppression differee (appliquee a l'ecriture) : les indices restent valables jusque-la."""
        for mi, pi in sel:
            self.meshes[mi].setdefault('deleted', set()).add(pi)
            self.meshes[mi]['dirty'] = True

    def copy(self, sel, world_matrix, source=None):
        """Ajoute des copies transformees des primitives selectionnees (dans le meme maillage).

        source : {(mi, pi): sommets locaux} pour copier depuis un etat anterieur (ex. avant deplacement)."""
        for mi, pi in sel:
            m = self.meshes[mi]
            to_local = mat_inv_rigid_scale(m['to_world'])
            full = mat_mul(to_local, mat_mul(world_matrix, m['to_world']))
            p = m['mesh'].prims[pi]
            verts = source[(mi, pi)] if source else p.verts
            m['mesh'].prims.append(Prim([apply(full, v) for v in verts], p.value, p.flat, p.interior))
            m['dirty'] = True

    def add_world_prims(self, tris_world, value, mesh_index=None):
        """Ajoute des triangles (monde, pouces) au maillage de sol principal (le plus grand) avec la surface value."""
        mi = mesh_index if mesh_index is not None else max(range(len(self.meshes)), key=lambda i: len(self.meshes[i]['mesh'].prims))
        m = self.meshes[mi]
        L = np.asarray(mat_inv_rigid_scale(m['to_world']), np.float64)
        T = np.asarray(tris_world, np.float64).reshape(-1, 3, 3)
        for t in (T @ L[:3, :3].T + L[:3, 3]).tolist():
            m['mesh'].prims.append(Prim([tuple(v) for v in t], value))
        m['dirty'] = True
        return mi

    def surface_under(self, lo, hi, default=38):
        """Surface la plus frequente des primitives du sol sous une emprise (boite monde, pouces)."""
        vals = collections.Counter()
        cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
        rad = max(hi[0] - lo[0], hi[1] - lo[1]) / 2 + 200
        for mi, pi, vs in self.prims_world():
            px = sum(v[0] for v in vs) / len(vs)
            py = sum(v[1] for v in vs) / len(vs)
            if abs(px - cx) <= rad and abs(py - cy) <= rad and min(v[2] for v in vs) <= hi[2] + 200:
                vals[self.meshes[mi]['mesh'].prims[pi].value] += 1
        return vals.most_common(1)[0][0] if vals else default

    def snapshot(self, sel):
        return {(mi, pi): list(self.meshes[mi]['mesh'].prims[pi].verts) for mi, pi in sel}

    # -- instances du compound -------------------------------------------------------------------
    def _instances(self):
        if not hasattr(self, 'inst_edits'):
            self.inst_edits = {}        # indice -> ('set', pos, euler, scale) | ('off',)
            self.inst_added = []        # (indice source, pos, euler, scale)
        return self

    def set_instance(self, i, pos, euler, scale):
        self._instances().inst_edits[i] = ('set', pos, euler, scale)

    def instance_count(self):
        """Nombre d'instances du compound (maillages et autres formes)."""
        comp = next(o for o, c in self.pf.objects.items() if c == 'hknpStaticCompoundShape')
        return self.pf.array(comp + 0x60)[1]

    def disable_instance(self, i):
        self._instances().inst_edits[i] = ('off',)

    def add_instance(self, src, pos, euler, scale):
        """Nouvelle instance : meme forme que l'instance src, placee a (pos, euler, scale) (pouces / radians)."""
        self._instances().inst_added.append((src, pos, euler, scale))

    def to_bytes(self):
        self._instances()
        if not any(m['dirty'] for m in self.meshes) and not self.inst_edits and not self.inst_added:
            return self.raw
        w = PackfileWriter(self.raw)
        for m in self.meshes:
            if m['dirty']:
                dele = m.get('deleted', set())
                m['mesh'].prims = [p for i, p in enumerate(m['mesh'].prims) if i not in dele]
                m['deleted'] = set()
                if not m['mesh'].prims:      # maillage vide : on garde un triangle minuscule (structure valide)
                    m['mesh'].prims = [Prim([(0, 0, -1e4), (1e-3, 0, -1e4), (0, 1e-3, -1e4)], 0)]
                write_mesh(w, m['shape'], encode_mesh(m['mesh']))
        write_compound(w, self)
        return w.to_bytes()


# ---------------------------------------------------------------------------------------------
from collision_edit import DELETED_SCALE, euler_columns  # noqa: E402
from cms_codec import _build_tree  # noqa: E402
from collision import decode_polytope  # noqa: E402
import struct  # noqa: E402


def _shape_local_aabb(pf, shape, ge):
    """Boite locale (m) d'une forme : maillage (sommets, a jour si edite), polytope, sphere."""
    kind = pf.objects.get(shape)
    if kind == 'hknpCompressedMeshShape':
        m = next((x for x in ge.meshes if x['shape'] == shape), None)
        pts = [v for p in m['mesh'].prims for v in p.verts] if m else []
        r = m['mesh'].radius if m else 0.01
    elif kind == 'hknpConvexPolytopeShape':
        pts, r = decode_polytope(pf, shape), pf.f32(shape + 0x14)
    elif kind == 'hknpSphereShape':
        rad = pf.f32(shape + 0x14)
        pts, r = [(-rad, -rad, -rad), (rad, rad, rad)], 0.0
    else:
        pts, r = [(-1, -1, -1), (1, 1, 1)], 0.0
    if not pts:
        pts = [(0, 0, 0)]
    lo = [min(p[k] for p in pts) - r for k in range(3)]
    hi = [max(p[k] for p in pts) + r for k in range(3)]
    return lo, hi


def write_compound(w, ge):
    """Reecrit les instances du hknpStaticCompoundShape (transformations, ajouts) et RECONSTRUIT son arbre.

    Arbre (hknpStaticCompoundShapeData +0x10, noeuds 6 o) : 3 octets de bornes, hiData (bit 7 = interne),
    loData u16 ; valeur 23 bits = feuille : instance / interne : enfant droit a i + 2*valeur."""
    pf = ge.pf
    comp = next(o for o, c in pf.objects.items() if c == 'hknpStaticCompoundShape')
    tree = next(o for o, c in pf.objects.items() if c == 'hknpStaticCompoundShapeData')
    io, n = pf.array(comp + 0x60)
    entries = [bytearray(w.data[io + i * 128:io + i * 128 + 128]) for i in range(n)]
    shapes = [pf.ptr(io + i * 128 + 0x50) for i in range(n)]

    def place(e, pos, euler, scale):
        cols = euler_columns(*euler)
        for k in range(3):
            struct.pack_into('<3f', e, k * 16, *cols[k])
        struct.pack_into('<3f', e, 0x30, *[c / G for c in pos])
        struct.pack_into('<3f', e, 0x40, *scale)
    for i, ed in ge.inst_edits.items():
        if ed[0] == 'off':
            struct.pack_into('<3f', entries[i], 0x40, DELETED_SCALE, DELETED_SCALE, DELETED_SCALE)
        else:
            place(entries[i], *ed[1:])
    for src, pos, euler, scale in ge.inst_added:
        e = bytearray(entries[src])
        place(e, pos, euler, scale)
        entries.append(e)
        shapes.append(shapes[src])
    count = len(entries)
    if count != n:
        w.set_array(comp + 0x60, b''.join(bytes(e) for e in entries), count)
        base = w.local[w._local_index[comp + 0x60]][1]
        for i, s in enumerate(shapes):
            w.set_pointer(base + i * 128 + 0x50, s)
    else:
        for i, e in enumerate(entries):
            w.write(io + i * 128, bytes(e))
    # boites monde (m) de chaque instance
    boxes = []
    for i, e in enumerate(entries):
        m = struct.unpack_from('<16f', e, 0)
        sc = struct.unpack_from('<3f', e, 0x40)
        lo, hi = _shape_local_aabb(pf, shapes[i], ge)
        corners = [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
        wc = [[m[0 + r] * sc[0] * c[0] + m[4 + r] * sc[1] * c[1] + m[8 + r] * sc[2] * c[2] + m[12 + r] for r in range(3)]
              for c in corners]
        boxes.append(([min(p[k] for p in wc) for k in range(3)], [max(p[k] for p in wc) for k in range(3)]))
    dlo = [min(b[0][k] for b in boxes) - 0.01 for k in range(3)]
    dhi = [max(b[1][k] for b in boxes) + 0.01 for k in range(3)]
    nodes, _ = _build_tree(list(range(count)), lambda i: boxes[i], (dlo, dhi), 6,
                           lambda i: bytes([(i >> 16) & 0x7F, i & 0xFF, (i >> 8) & 0xFF]),
                           lambda nl: bytes([0x80 | ((nl >> 16) & 0x7F), nl & 0xFF, (nl >> 8) & 0xFF]))
    w.set_array(tree + 0x10, nodes, len(nodes) // 6)
    for base in (tree + 0x20, comp + 0x80):
        wlo = struct.unpack_from('<f', w.data, base + 12)[0]
        whi = struct.unpack_from('<f', w.data, base + 28)[0]
        w.write(base, struct.pack('<4f', *dlo, wlo))
        w.write(base + 0x10, struct.pack('<4f', *dhi, whi))
    w.write(comp + 0x12, bytes([max(1, (count - 1).bit_length())]))
