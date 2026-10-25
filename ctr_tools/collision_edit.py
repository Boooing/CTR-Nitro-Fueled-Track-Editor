"""Edition en place de la collision statique Havok (StaticCollision_<Piste>.hkx) : instances du compound.

Chaque objet de decor qui a une collision correspond a UNE instance du hknpStaticCompoundShape, placee avec
la meme transformation (verifie sur Crash Cove : 77/77 instances, ecart < 0,03 po). Deplacer la collision d'un
objet = reecrire la transformation de son instance :
  instance (128 o) : +0x00 colonnes de rotation (3 x vec4, w = drapeaux conserves), +0x30 translation (m),
                     +0x40 echelle (vec4), +0x50 forme*
Le compound accelere les requetes avec un arbre de boites (hknpStaticCompoundShapeData +0x10 noeuds de 6 o,
+0x20/+0x30 domaine). Noeud : 3 octets de bornes (quartet haut = retrait du min, bas = retrait du max, en
q^2/226 de l'etendue du parent), puis hiData (bit 7 = noeud interne) et loData ; enfant droit = i + 2*valeur.
Apres une modification on « neutralise » l'arbre (bornes a 0 : chaque boite = le domaine) et on agrandit le
domaine pour couvrir toutes les instances : correct, juste un peu moins rapide (77 instances).
Un objet supprime : son instance est reduite a une echelle quasi nulle.
"""
import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collision import decode_polytope as polytope_vertices  # noqa: E402
from havok import Packfile  # noqa: E402

GAME_PER_METER = 39.37
DELETED_SCALE = 1e-4


def euler_columns(rx, ry, rz):
    """Colonnes de R = Rz * Ry * Rx."""
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    R = [[cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx],
         [sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx],
         [-sy, cy * sx, cy * cx]]
    return [[R[0][k], R[1][k], R[2][k]] for k in range(3)]


class CollisionFile:
    def __init__(self, data):
        self.buf = bytearray(data)
        self.pf = Packfile(bytes(data))
        pf = self.pf
        self.compound = next(o for o, c in pf.objects.items() if c == 'hknpStaticCompoundShape')
        self.tree = next(o for o, c in pf.objects.items() if c == 'hknpStaticCompoundShapeData')
        self.inst_off, self.count = pf.array(self.compound + 0x60)
        self.changed = False

    # -- lecture / ecriture ------------------------------------------------------------------
    def _write(self, off, fmt, *vals):
        """Ecrit dans la copie modifiable (self.pf reste la lecture d'origine : formes, tableaux)."""
        struct.pack_into(fmt, self.buf, self.pf.data_start + off, *vals)
        self.changed = True

    def _floats(self, off, n):
        return list(struct.unpack_from(f'<{n}f', self.buf, self.pf.data_start + off))

    def instances(self):
        out = []
        for i in range(self.count):
            b = self.inst_off + i * 128
            m = self._floats(b, 16)
            out.append({'index': i, 'kind': self.pf.objects.get(self.pf.ptr(b + 0x50)),
                        'pos': [c * GAME_PER_METER for c in m[12:15]], 'scale': self._floats(b + 0x40, 3)})
        return out

    def find(self, pos, tolerance=0.5):
        """Index de l'instance placee a pos (pouces), ou None."""
        best = None
        for inst in self.instances():
            d = math.dist(inst['pos'], pos)
            if d <= tolerance and (best is None or d < best[0]):
                best = (d, inst['index'])
        return best[1] if best else None

    def set_instance(self, i, pos, euler, scale):
        """Place l'instance i : pos en pouces, euler (radians, R = Rz*Ry*Rx), echelle xyz."""
        b = self.inst_off + i * 128
        cols = euler_columns(*euler)
        for k in range(3):
            self._write(b + k * 16, '<3f', *cols[k])          # w (drapeaux) conserve
        self._write(b + 0x30, '<3f', *[c / GAME_PER_METER for c in pos])
        self._write(b + 0x40, '<3f', *scale)

    def disable_instance(self, i):
        b = self.inst_off + i * 128
        self._write(b + 0x40, '<3f', DELETED_SCALE, DELETED_SCALE, DELETED_SCALE)

    # -- arbre / domaine -----------------------------------------------------------------------
    def _shape_radius(self, shape):
        """Rayon englobant (m) d'une forme autour de l'origine de l'instance."""
        pf, kind = self.pf, self.pf.objects.get(shape)
        if kind == 'hknpCompressedMeshShape':
            d = pf.ptr(shape + 0x58)
            lo, hi = pf.floats(d + 0x20, 3), pf.floats(d + 0x30, 3)
            return max(math.dist([0, 0, 0], [x, y, z]) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2]))
        if kind == 'hknpConvexPolytopeShape':
            pts = polytope_vertices(pf, shape)
            return max(math.dist([0, 0, 0], p) for p in pts) + pf.f32(shape + 0x14)
        if kind == 'hknpSphereShape':
            return pf.f32(shape + 0x14)
        return 10.0

    def neutralize_tree(self):
        """Toutes les boites = le domaine, et le domaine (+ l'AABB du compound) couvre toutes les instances."""
        pf = self.pf
        no, nn = pf.array(self.tree + 0x10)
        for k in range(nn):
            self._write(no + k * 6, '<3B', 0, 0, 0)
        lo, hi = self._floats(self.tree + 0x20, 3), self._floats(self.tree + 0x30, 3)
        for i in range(self.count):
            b = self.inst_off + i * 128
            c = self._floats(b + 0x30, 3)
            r = self._shape_radius(pf.ptr(b + 0x50)) * max(abs(s) for s in self._floats(b + 0x40, 3))
            for k in range(3):
                lo[k] = min(lo[k], c[k] - r)
                hi[k] = max(hi[k], c[k] + r)
        for base in (self.tree + 0x20, self.compound + 0x80):
            self._write(base, '<3f', *lo)
            self._write(base + 0x10, '<3f', *hi)

    def to_bytes(self):
        return bytes(self.buf)
