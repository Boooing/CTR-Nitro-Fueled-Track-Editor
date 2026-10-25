"""Export OBJ de reference pour Blender (collision du sol, decor, splines).

Conventions inverses de model_build.parse_obj (up='y', scale=39.37) : un point du jeu (X, Y, Z) en pouces,
Z vers le haut, devient (X / 39.37, Z / 39.37, -Y / 39.37) en metres, Y vers le haut (Blender par defaut).
C'est une rotation (determinant +1) : l'ordre des sommets des faces est conserve. Une scene modelisee autour de
cette reference et importee avec le placement « coordonnees absolues » tombe donc au meme endroit en jeu.
Le fichier est ecrit au fil de l'eau (le decor complet d'une piste depasse 5 millions de triangles).
"""
import colorsys

SCALE = 39.37


def to_blender(p, scale=SCALE, up='y'):
    """Point du jeu -> OBJ. up='y' : Y vers le haut (Blender par defaut) ; up='z' : Z vers le haut (a importer
    avec « Up : Z » dans Blender, et l'axe vertical Z dans l'import de l'editeur)."""
    if up == 'z':
        return (p[0] / scale, p[1] / scale, p[2] / scale)
    return (p[0] / scale, p[2] / scale, -p[1] / scale)


class ObjWriter:
    def __init__(self, f, mtl_name=None, up='y'):
        """f : fichier texte ouvert en ecriture."""
        self.f, self.up = f, up
        if mtl_name:
            f.write(f'mtllib {mtl_name}\n')
        self.n = 0                      # sommets ecrits (indices OBJ globaux, a partir de 1)
        self.materials = {}             # nom -> couleur (r, g, b)
        self.stats = {'objects': 0, 'triangles': 0, 'lines': 0}

    def _head(self, name, material, color):
        self.materials.setdefault(material, color)
        self.f.write(f'o {name}\nusemtl {material}\n')
        self.stats['objects'] += 1

    def add_mesh(self, name, material, color, tris, digits=6):
        """tris : [(p0, p1, p2)] en coordonnees du jeu (pouces). Sommets partages au sein de l'objet."""
        if not tris:
            return
        index, verts, faces = {}, [], []
        for t in tris:
            f = []
            for p in t:
                b = tuple(round(c, digits) for c in to_blender(p, up=self.up))
                if b not in index:
                    verts.append(b)
                    index[b] = self.n + len(verts)
                f.append(index[b])
            if len(set(f)) == 3:                       # triangles degeneres ignores
                faces.append(f)
        self._write(name, material, color, verts, faces, digits)

    def add_indexed(self, name, material, color, verts, idx, digits=4):
        """Maillage indexe : verts en coordonnees du jeu, idx = indices de triangles (liste plate)."""
        if not idx:
            return
        b = self.n + 1
        faces = [(idx[i] + b, idx[i + 1] + b, idx[i + 2] + b) for i in range(0, len(idx) - 2, 3)
                 if idx[i] != idx[i + 1] and idx[i + 1] != idx[i + 2] and idx[i] != idx[i + 2]]
        self._write(name, material, color, [to_blender(v, up=self.up) for v in verts], faces, digits)

    def _write(self, name, material, color, verts_obj, faces, digits):
        if not faces:
            return
        self._head(name, material, color)
        fmt = f'v %.{digits}f %.{digits}f %.{digits}f\n'
        self.f.write(''.join(fmt % tuple(v) for v in verts_obj))
        self.f.write(''.join('f %d %d %d\n' % tuple(f) for f in faces))
        self.n += len(verts_obj)
        self.stats['triangles'] += len(faces)

    def add_polyline(self, name, material, color, pts):
        """Polyligne (aretes `l`) : importee dans Blender comme un objet fait d'aretes."""
        if len(pts) < 2:
            return
        self._head(name, material, color)
        self.f.write(''.join('v %.6f %.6f %.6f\n' % to_blender(p, up=self.up) for p in pts))
        self.f.write('l ' + ' '.join(str(self.n + i + 1) for i in range(len(pts))) + '\n')
        self.n += len(pts)
        self.stats['lines'] += 1

    def mtl_text(self):
        out = []
        for name, (r, g, b) in self.materials.items():
            out += [f'newmtl {name}', f'Kd {r:.3f} {g:.3f} {b:.3f}', 'Ka 0 0 0', 'Ks 0 0 0', 'd 1', '']
        return '\n'.join(out)


def box_tris(lo, hi):
    """12 triangles d'une boite (faces vers l'exterieur, Z vers le haut)."""
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    c = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    return [t for a, b, cc, d in quads for t in ((c[a], c[b], c[cc]), (c[a], c[cc], c[d]))]


def surface_color(value):
    """Couleur stable par surface de collision (teinte derivee du numero)."""
    r, g, b = colorsys.hsv_to_rgb((value * 0.618034) % 1.0, 0.55, 0.85)
    return (r, g, b)
