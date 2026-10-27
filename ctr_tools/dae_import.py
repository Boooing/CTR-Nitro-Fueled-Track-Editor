"""Lecture d'un fichier COLLADA (.dae) -> texte OBJ + materiaux (meme format que parse_mtl), pour l'import.

Gere : <geometry>/<mesh> en <triangles>, <polylist> ou <polygons> (eventail), instances directes
(<instance_geometry>) ou skinnees (<instance_controller> : bind_shape_matrix appliquee, pose de repos ; les exports
de cartes (Switch Toolbox...) n'ont qu'un os identite), noeuds imbriques (<matrix>, <translate>, <rotate>, <scale>),
<instance_node>, unite (<unit meter>) ; materiaux -> effet -> texture diffuse (sampler -> surface -> image, ou
image directe) ou couleur diffuse. Coordonnees laissees dans le repere du fichier (axe vertical : <up_axis>, Y par
defaut), l'import convertit ensuite comme pour un OBJ.
"""
import math
import os
import re
import xml.etree.ElementTree as ET
from urllib.parse import unquote

import numpy as np


def _strip(root):
    """Retire l'espace de noms des balises (COLLADA 1.4 / 1.5)."""
    for el in root.iter():
        if isinstance(el.tag, str) and el.tag.startswith('{'):
            el.tag = el.tag.split('}', 1)[1]
    return root


def _floats(text):
    return np.array(text.split(), np.float64) if text and text.strip() else np.zeros(0)


def _ints(text):
    return np.array(text.split(), np.int64) if text and text.strip() else np.zeros(0, np.int64)


def _node_matrix(node):
    M = np.eye(4)
    for el in node:
        t = el.tag
        if t == 'matrix':
            M = M @ _floats(el.text).reshape(4, 4)
        elif t == 'translate':
            T = np.eye(4)
            T[:3, 3] = _floats(el.text)[:3]
            M = M @ T
        elif t == 'scale':
            M = M @ np.diag(list(_floats(el.text)[:3]) + [1.0])
        elif t == 'rotate':
            x, y, z, a = _floats(el.text)[:4]
            n = math.sqrt(x * x + y * y + z * z) or 1.0
            x, y, z, a = x / n, y / n, z / n, math.radians(a)
            c, s, C = math.cos(a), math.sin(a), 1 - math.cos(a)
            R = np.eye(4)
            R[:3, :3] = [[c + x * x * C, x * y * C - z * s, x * z * C + y * s],
                         [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
                         [z * x * C - y * s, z * y * C + x * s, c + z * z * C]]
            M = M @ R
    return M


class Dae:
    def __init__(self, path):
        self.path = path
        self.root = _strip(ET.parse(path).getroot())
        self.ids = {el.get('id'): el for el in self.root.iter() if el.get('id')}
        unit = self.root.find('asset/unit')
        self.meter = float(unit.get('meter', 1)) if unit is not None else 1.0
        up = self.root.find('asset/up_axis')
        self.up = (up.text or 'Y_UP').strip().upper() if up is not None else 'Y_UP'

    def ref(self, url):
        return self.ids.get((url or '').lstrip('#'))

    # -- materiaux ---------------------------------------------------------------------------------
    def image_file(self, image_id):
        img = self.ids.get(image_id)
        if img is None or img.tag != 'image':
            return None
        f = img.find('.//init_from')
        if f is None:
            return None
        ref = f.find('ref')                                  # COLLADA 1.5 : <init_from><ref>...</ref>
        txt = (ref.text if ref is not None else f.text) or ''
        txt = txt.strip()
        if txt.startswith('file://'):                        # URI : file:///C:/x.png (Windows), file:///home/x.png
            txt = unquote(txt[len('file://'):])
            if re.match(r'^/[A-Za-z]:', txt):
                txt = txt[1:]
        return txt or None

    def material_info(self, mat_id):
        """{'texture': fichier ou None, 'color': (r, g, b) ou None} d'un materiau."""
        mat = self.ids.get(mat_id)
        eff = self.ref(mat.find('instance_effect').get('url')) if mat is not None and mat.find('instance_effect') is not None else None
        out = {'texture': None, 'color': None}
        if eff is None:
            return out
        params = {p.get('sid'): p for p in eff.iter('newparam')}
        diffuse = next(eff.iter('diffuse'), None)
        tex = diffuse.find('texture') if diffuse is not None else None
        if tex is None:
            tex = next(eff.iter('texture'), None)
        if tex is not None:
            key = tex.get('texture')
            for _ in range(4):                                # sampler -> surface -> image
                p = params.get(key)
                if p is None:
                    break
                src = p.find('.//source')
                init = p.find('.//init_from')
                inst = p.find('.//instance_image')            # COLLADA 1.5
                if src is not None:
                    key = src.text.strip()
                elif inst is not None:
                    key = inst.get('url', '').lstrip('#')
                    break
                elif init is not None:
                    key = init.text.strip()
                    break
                else:
                    break
            out['texture'] = self.image_file(key)
        col = diffuse.find('color') if diffuse is not None else None
        if col is not None:
            out['color'] = tuple(_floats(col.text)[:3])
        return out

    # -- geometrie ---------------------------------------------------------------------------------
    def _source(self, url):
        src = self.ref(url)
        if src is None:
            return None
        if src.tag == 'vertices':                             # <vertices> -> son entree POSITION
            inp = next((i for i in src.findall('input') if i.get('semantic') == 'POSITION'), None)
            return self._source(inp.get('source')) if inp is not None else None
        arr = src.find('float_array')
        acc = src.find('technique_common/accessor')
        stride = int(acc.get('stride', 1)) if acc is not None else 1
        data = _floats(arr.text)
        return data[:len(data) // stride * stride].reshape(-1, stride)

    def mesh_parts(self, geom):
        """[(symbole de materiau, positions (n, 3), normales (n, 3) | None, uv (n, 2) | None)] par primitive,
        sommets deroules (3 par triangle)."""
        mesh = geom.find('mesh')
        out = []
        if mesh is None:
            return out
        for prim in mesh:
            if prim.tag not in ('triangles', 'polylist', 'polygons'):
                continue
            inputs = prim.findall('input')
            stride = max(int(i.get('offset', 0)) for i in inputs) + 1
            sem = {}
            for i in inputs:
                s = i.get('semantic')
                if s == 'TEXCOORD':
                    sets = sem.setdefault('TEXCOORD', {})
                    sets[int(i.get('set', 0))] = i
                elif s not in sem:
                    sem[s] = i
            if prim.tag == 'polygons':                        # un <p> par polygone
                polys = [_ints(p.text).reshape(-1, stride) for p in prim.findall('p')]
            else:
                idx = _ints(prim.findtext('p')).reshape(-1, stride)
                if prim.tag == 'triangles':
                    polys = None
                    tri_idx = idx
                else:
                    counts = _ints(prim.findtext('vcount'))
                    starts = np.concatenate([[0], np.cumsum(counts)[:-1]])
                    polys = [idx[s:s + c] for s, c in zip(starts, counts)]
            if polys is not None:                             # eventails -> triangles
                rows = []
                for pl in polys:
                    for k in range(1, len(pl) - 1):
                        rows += [pl[0], pl[k], pl[k + 1]]
                tri_idx = np.array(rows, np.int64).reshape(-1, stride) if rows else np.zeros((0, stride), np.int64)

            def column(inp, width):
                if inp is None:
                    return None
                data = self._source(inp.get('source'))
                if data is None or not len(data):
                    return None
                return data[tri_idx[:, int(inp.get('offset', 0))], :width]
            vin = sem.get('VERTEX')
            pos = column(vin, 3)
            if pos is None:
                continue
            nrm = column(sem.get('NORMAL'), 3)
            sets = sem.get('TEXCOORD') or {}
            uv = column(sets[min(sets)], 2) if sets else None
            # normales / UV declares dans <vertices> (certains exports)
            vtx = self.ref(vin.get('source'))
            if vtx is not None and vtx.tag == 'vertices':
                extra = {i.get('semantic'): i for i in vtx.findall('input')}
                pidx = tri_idx[:, int(vin.get('offset', 0))]
                if nrm is None and 'NORMAL' in extra:
                    nrm = self._source(extra['NORMAL'].get('source'))[pidx, :3]
                if uv is None and 'TEXCOORD' in extra:
                    uv = self._source(extra['TEXCOORD'].get('source'))[pidx, :2]
            out.append((prim.get('material') or '', pos, nrm, uv))
        return out

    def instances(self):
        """[(nom, geometrie, matrice monde 4x4, {symbole: id du materiau})] de la scene visuelle."""
        scene = self.root.find('scene/instance_visual_scene')
        vs = self.ref(scene.get('url')) if scene is not None else self.root.find('library_visual_scenes/visual_scene')
        out = []

        def bindings(inst):
            return {m.get('symbol'): m.get('target', '').lstrip('#') for m in inst.iter('instance_material')}

        def walk(node, M, depth=0):
            if depth > 64:
                return
            W = M @ _node_matrix(node)
            name = node.get('name') or node.get('id') or 'objet'
            for inst in node.findall('instance_geometry'):
                g = self.ref(inst.get('url'))
                if g is not None:
                    out.append((name, g, W, bindings(inst)))
            for inst in node.findall('instance_controller'):
                ctrl = self.ref(inst.get('url'))
                skin = ctrl.find('skin') if ctrl is not None else None
                if skin is None:
                    continue
                g = self.ref(skin.get('source'))
                bsm = skin.findtext('bind_shape_matrix')
                B = _floats(bsm).reshape(4, 4) if bsm else np.eye(4)
                if g is not None:
                    out.append((name, g, W @ B, bindings(inst)))
            for inst in node.findall('instance_node'):
                n = self.ref(inst.get('url'))
                if n is not None:
                    walk(n, W, depth + 1)
            for child in node.findall('node'):
                walk(child, W, depth + 1)
        if vs is not None:
            for n in vs.findall('node'):
                walk(n, np.eye(4))
        return out


def dae_to_obj(path):
    """(texte OBJ, {nom de materiau: {'texture', 'color'}}, axe vertical 'y' | 'z'). Une entree `o` par instance,
    `usemtl` = nom du materiau COLLADA ; positions en unites du fichier x <unit meter> (donc en metres)."""
    dae = Dae(path)
    lines, mats, names = [], {}, {}
    nv = nt = nn = 0
    for name, geom, M, bind in dae.instances():
        Nm = np.linalg.inv(M[:3, :3]).T
        for symbol, pos, nrm, uv in dae.mesh_parts(geom):
            mat_id = bind.get(symbol, symbol)
            mat_el = dae.ids.get(mat_id)
            mname = (mat_el.get('name') if mat_el is not None else None) or mat_id or 'sans_materiau'
            if mname not in mats:
                mats[mname] = dae.material_info(mat_id)
            P = (pos @ M[:3, :3].T + M[:3, 3]) * dae.meter
            has_uv, has_n = uv is not None, nrm is not None
            cols = [P]
            if has_n:
                N = nrm @ Nm.T
                N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
                cols.append(N)
            if has_uv:
                cols.append(uv)
            # sommets deroules (3 par triangle) -> sommets uniques (position + normale + UV identiques)
            K = np.round(np.hstack(cols), 6)
            U, inv = np.unique(K, axis=0, return_inverse=True)
            inv = inv.reshape(-1)
            n = len(U)
            lines.append(f'o {name}\nusemtl {mname}\n')
            lines.append(''.join(f'v {x:.6f} {y:.6f} {z:.6f}\n' for x, y, z in U[:, :3]))
            if has_n:
                lines.append(''.join(f'vn {x:.5f} {y:.5f} {z:.5f}\n' for x, y, z in U[:, 3:6]))
            if has_uv:
                lines.append(''.join(f'vt {u:.6f} {v:.6f}\n' for u, v in U[:, -2:]))
            face = []
            for k in range(0, len(inv) - 2, 3):
                c = []
                for j in range(3):
                    i = int(inv[k + j]) + 1
                    vi, ti, ni = nv + i, (nt + i if has_uv else ''), (nn + i if has_n else '')
                    c.append(f'{vi}/{ti}/{ni}' if has_n else (f'{vi}/{ti}' if has_uv else f'{vi}'))
                face.append('f ' + ' '.join(c) + '\n')
            lines.append(''.join(face))
            nv += n
            nt += n if has_uv else 0
            nn += n if has_n else 0
            names[name] = names.get(name, 0) + 1
    up = 'z' if dae.up == 'Z_UP' else 'y'
    return ''.join(lines), mats, up
