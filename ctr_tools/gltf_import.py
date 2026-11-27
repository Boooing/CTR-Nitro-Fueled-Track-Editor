"""Lecture d'un fichier glTF 2.0 (.glb binaire, ou .gltf JSON + .bin) -> texte OBJ + materiaux (meme format que
parse_mtl / dae_import), pour l'import d'une map depuis un dossier. Lecture maison avec numpy (pas de bibliotheque).

Gere : scene (scene par defaut, sinon la premiere, sinon tous les noeuds racines), noeuds imbriques (matrix, ou
translation / rotation / scale), maillages en triangles (mode 4), bandes (5) et eventails (6), avec ou sans indices,
accesseurs normalises (UV en octets / mots), accesseurs epars ; materiaux -> texture de couleur de base
(pbrMetallicRoughness.baseColorTexture, sinon KHR_materials_pbrSpecularGlossiness.diffuseTexture) ou couleur
(baseColorFactor) ; alphaMode (OPAQUE : transparence de l'image ignoree ; MASK / BLEND : gardee).
Textures integrees (bufferView du .glb, ou data: URI) extraites dans un dossier temporaire ; textures externes
(uri relative) laissees au dossier de la map. glTF est en metres, axe vertical Y : l'import convertit ensuite comme
pour un OBJ / DAE Y-up. Non gere : maillages compresses (Draco, meshopt), textures KTX2 : erreur claire.
"""
import base64
import hashlib
import json
import os
import re
import struct
import tempfile
from urllib.parse import unquote

import numpy as np

GLB_MAGIC = b'glTF'
CHUNK_JSON, CHUNK_BIN = 0x4E4F534A, 0x004E4942
COMPONENT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
NCOMP = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT2': 4, 'MAT3': 9, 'MAT4': 16}
NORM_DIV = {np.int8: 127.0, np.uint8: 255.0, np.int16: 32767.0, np.uint16: 65535.0, np.uint32: 4294967295.0}
MIME_EXT = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp', 'image/bmp': '.bmp'}
UNSUPPORTED = {'KHR_draco_mesh_compression': 'Draco', 'EXT_meshopt_compression': 'meshopt',
               'KHR_meshopt_compression': 'meshopt'}
TEXTURE_DIR = os.path.join(tempfile.gettempdir(), 'ctr_gltf_textures')


def _clean(name, default):
    s = re.sub(r'[^A-Za-z0-9_.-]+', '_', name or '').strip('_.')
    return s or default


def _data_uri(uri):
    head, _, data = uri.partition(',')
    return base64.b64decode(data) if ';base64' in head else unquote(data).encode('latin-1')


class Gltf:
    def __init__(self, path):
        self.path = path
        self.folder = os.path.dirname(os.path.abspath(path))
        raw = open(path, 'rb').read()
        self.bin = None
        if raw[:4] == GLB_MAGIC:
            ver, total = struct.unpack_from('<II', raw, 4)
            if ver != 2:
                raise ValueError(f'{os.path.basename(path)} : glTF binaire version {ver} (seule la version 2 est lue)')
            off, js = 12, None
            while off + 8 <= min(total, len(raw)):
                ln, typ = struct.unpack_from('<II', raw, off)
                chunk = raw[off + 8:off + 8 + ln]
                if typ == CHUNK_JSON and js is None:
                    js = json.loads(chunk.decode('utf-8'))
                elif typ == CHUNK_BIN and self.bin is None:
                    self.bin = chunk
                off += 8 + ln + (-ln % 4)
            if js is None:
                raise ValueError(f'{os.path.basename(path)} : pas de bloc JSON (fichier .glb abime ?)')
            self.js = js
        else:
            self.js = json.loads(raw.decode('utf-8-sig'))
        ver = str((self.js.get('asset') or {}).get('version', '2.0'))
        if not ver.startswith('2'):
            raise ValueError(f'{os.path.basename(path)} : glTF version {ver} (seule la version 2 est lue)')
        used = set(self.js.get('extensionsRequired') or []) | set(self.js.get('extensionsUsed') or [])
        bad = sorted({UNSUPPORTED[e] for e in used if e in UNSUPPORTED})
        if bad and any(e in UNSUPPORTED for e in (self.js.get('extensionsRequired') or [])):
            raise ValueError(f'{os.path.basename(path)} : maillage compressé ({", ".join(bad)}) non pris en charge ; '
                             f'réexporte-le sans compression (Blender : décocher « Compression »)')
        self._buffers = {}

    def _list(self, key):
        return self.js.get(key) or []

    # -- donnees binaires ------------------------------------------------------------------------
    def buffer(self, i):
        if i not in self._buffers:
            b = self._list('buffers')[i]
            uri = b.get('uri')
            if uri is None:                                   # buffer 0 du .glb : bloc BIN
                if self.bin is None:
                    raise ValueError('buffer sans données (bloc BIN absent)')
                data = self.bin
            elif uri.startswith('data:'):
                data = _data_uri(uri)
            else:
                p = os.path.join(self.folder, unquote(uri))
                if not os.path.isfile(p):
                    raise ValueError(f'fichier de données {unquote(uri)} introuvable à côté de {os.path.basename(self.path)}')
                data = open(p, 'rb').read()
            self._buffers[i] = data
        return self._buffers[i]

    def view_bytes(self, vi):
        v = self._list('bufferViews')[vi]
        off = v.get('byteOffset', 0)
        return self.buffer(v['buffer'])[off:off + v['byteLength']], v.get('byteStride')

    def accessor(self, ai):
        """Tableau (count, n) en float64 (valeurs normalisees ramenees a 0-1 / -1-1) ou entiers (indices)."""
        a = self._list('accessors')[ai]
        dt = COMPONENT[a['componentType']]
        n, count = NCOMP[a['type']], a['count']
        item = np.dtype(dt).itemsize
        if 'bufferView' in a:
            data, stride = self.view_bytes(a['bufferView'])
            off = a.get('byteOffset', 0)
            stride = stride or n * item
            if stride == n * item:
                arr = np.frombuffer(data, dt, count * n, off).reshape(count, n)
            else:                                             # sommets entrelaces
                rows = np.frombuffer(data, np.uint8, (count - 1) * stride + n * item, off) if count else np.zeros(0, np.uint8)
                idx = (np.arange(count)[:, None] * stride + np.arange(n * item)[None, :])
                arr = rows[idx].copy().view(dt).reshape(count, n)
            arr = arr.copy()
        else:
            arr = np.zeros((count, n), dt)
        sp = a.get('sparse')
        if sp:                                                # valeurs remplacees a certains indices
            ii, iv = sp['indices'], sp['values']
            d, _ = self.view_bytes(ii['bufferView'])
            where = np.frombuffer(d, COMPONENT[ii['componentType']], sp['count'], ii.get('byteOffset', 0)).astype(np.int64)
            d, _ = self.view_bytes(iv['bufferView'])
            arr[where] = np.frombuffer(d, dt, sp['count'] * n, iv.get('byteOffset', 0)).reshape(-1, n)
        if dt == np.float32:
            return arr.astype(np.float64)
        if a.get('normalized'):
            return np.maximum(arr.astype(np.float64) / NORM_DIV[dt], -1.0)
        return arr.astype(np.int64) if a['type'] == 'SCALAR' else arr.astype(np.float64)

    # -- materiaux -------------------------------------------------------------------------------
    def image_file(self, ti):
        """Chemin de l'image d'une texture : fichier externe (relatif au dossier de la map, tel quel), sinon image
        integree extraite dans TEXTURE_DIR (nom stable : la meme image n'est pas reencodee a chaque import)."""
        tex = self._list('textures')[ti] if ti is not None and ti < len(self._list('textures')) else None
        if tex is None:
            return None
        ext = tex.get('extensions') or {}
        src = tex.get('source')
        for k in ('EXT_texture_webp', 'MSFT_texture_dds'):     # variante proposee (la source peut manquer)
            if src is None and k in ext:
                src = ext[k].get('source')
        if src is None:
            return None
        img = self._list('images')[src]
        uri = img.get('uri')
        if uri and not uri.startswith('data:'):
            return unquote(uri)                              # texture externe : cherchee dans le dossier
        if uri:
            data, mime = _data_uri(uri), uri[5:].split(';')[0].split(',')[0]
        elif 'bufferView' in img:
            data, mime = self.view_bytes(img['bufferView'])[0], img.get('mimeType', '')
        else:
            return None
        if mime == 'image/ktx2':
            return None
        h = hashlib.sha1(data).hexdigest()[:10]
        name = _clean(os.path.splitext(img.get('name') or '')[0], f'texture{src}')[:40]
        ext = MIME_EXT.get(mime) or ('.png' if data[:4] == b'\x89PNG' else '.jpg')
        os.makedirs(TEXTURE_DIR, exist_ok=True)
        p = os.path.join(TEXTURE_DIR, f'{name}_{h}{ext}')
        if not os.path.isfile(p) or os.path.getsize(p) != len(data):
            with open(p, 'wb') as f:
                f.write(bytes(data))
        return p

    def material_info(self, mi):
        out = {'texture': None, 'color': None}
        if mi is None:
            return out
        m = self._list('materials')[mi]
        pbr = m.get('pbrMetallicRoughness') or {}
        sg = (m.get('extensions') or {}).get('KHR_materials_pbrSpecularGlossiness') or {}
        t = pbr.get('baseColorTexture') or sg.get('diffuseTexture')
        if t is not None:
            out['texture'] = self.image_file(t.get('index'))
            if t.get('texCoord', 0):
                out['texcoord'] = t['texCoord']
        col = pbr.get('baseColorFactor') or sg.get('diffuseFactor')
        if col:
            out['color'] = tuple(float(c) for c in col[:3])
        mode = m.get('alphaMode', 'OPAQUE')
        if out['texture']:
            out['alpha'] = None if mode in ('MASK', 'BLEND') else False   # None : d'apres l'image
        return out

    # -- scene -----------------------------------------------------------------------------------
    @staticmethod
    def node_matrix(n):
        if 'matrix' in n:
            return np.array(n['matrix'], np.float64).reshape(4, 4).T      # colonnes d'abord
        T, R, S = np.eye(4), np.eye(4), np.eye(4)
        T[:3, 3] = n.get('translation', (0, 0, 0))
        x, y, z, w = n.get('rotation', (0, 0, 0, 1))
        q = np.array([x, y, z, w], np.float64)
        q /= np.linalg.norm(q) or 1.0
        x, y, z, w = q
        R[:3, :3] = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
        S[:3, :3] = np.diag(n.get('scale', (1, 1, 1)))
        return T @ R @ S

    def instances(self):
        """[(nom, indice du maillage, matrice monde 4x4)] de la scene."""
        nodes = self._list('nodes')
        scenes = self._list('scenes')
        if scenes:
            roots = scenes[self.js.get('scene', 0) if self.js.get('scene', 0) < len(scenes) else 0].get('nodes') or []
        else:                                                # pas de scene : noeuds qui ne sont l'enfant de personne
            kids = {c for n in nodes for c in n.get('children') or []}
            roots = [i for i in range(len(nodes)) if i not in kids]
        out = []

        def walk(i, M, depth=0):
            if depth > 64 or i >= len(nodes):
                return
            n = nodes[i]
            W = M @ self.node_matrix(n)
            if n.get('mesh') is not None:
                mesh = self._list('meshes')[n['mesh']]
                out.append((n.get('name') or mesh.get('name') or f'objet{i}', n['mesh'], W))
            for c in n.get('children') or []:
                walk(c, W, depth + 1)
        for r in roots:
            walk(r, np.eye(4))
        return out

    def primitives(self, mi):
        """[(indice de materiau | None, positions, normales | None, {jeu: uv}, triangles (m, 3))] d'un maillage."""
        out = []
        for p in self._list('meshes')[mi].get('primitives') or []:
            if any(e in UNSUPPORTED for e in (p.get('extensions') or {})):
                raise ValueError(f'{os.path.basename(self.path)} : maillage compressé non pris en charge ; '
                                 f'réexporte-le sans compression')
            mode = p.get('mode', 4)
            at = p.get('attributes') or {}
            if mode not in (4, 5, 6) or 'POSITION' not in at:
                continue
            pos = self.accessor(at['POSITION'])[:, :3]
            nrm = self.accessor(at['NORMAL'])[:, :3] if 'NORMAL' in at else None
            uvs = {int(k.split('_')[1]): self.accessor(v)[:, :2] for k, v in at.items() if k.startswith('TEXCOORD_')}
            idx = self.accessor(p['indices']).reshape(-1).astype(np.int64) if 'indices' in p else np.arange(len(pos))
            if mode == 4:
                tris = idx[:len(idx) // 3 * 3].reshape(-1, 3)
            elif mode == 5:                                   # bande : un triangle sur deux retourne
                k = np.arange(max(len(idx) - 2, 0))
                a, b, c = idx[k], idx[k + 1], idx[k + 2]
                odd = k % 2 == 1
                tris = np.stack([a, np.where(odd, c, b), np.where(odd, b, c)], 1)
            else:                                             # eventail
                k = np.arange(1, max(len(idx) - 1, 1))
                tris = np.stack([np.full(len(k), idx[0]), idx[k], idx[k + 1]], 1) if len(idx) >= 3 else np.zeros((0, 3), np.int64)
            tris = tris[(tris[:, 0] != tris[:, 1]) & (tris[:, 1] != tris[:, 2]) & (tris[:, 0] != tris[:, 2])]
            if len(tris):
                out.append((p.get('material'), pos, nrm, uvs, tris))
        return out


def _gltf_parts(path):
    """Morceaux du fichier : ([(objet, materiau, positions (n, 3), normales | None, uv | None, triangles (m, 3) sur ces
    n sommets)], {nom de materiau: {'texture', 'color', 'alpha'}}). Positions dans le repere du fichier (Y en haut,
    metres), noeuds appliques ; seulement les sommets servis par les faces ; V des UV retourne (glTF : origine en haut a
    gauche, OBJ : en bas a gauche)."""
    g = Gltf(path)
    parts, mats, mat_name = [], {}, {}

    def name_of(mi):
        if mi not in mat_name:
            info = g.material_info(mi)
            base = 'sans_materiau' if mi is None else \
                re.sub(r'\s+', '_', (g._list('materials')[mi].get('name') or '').strip()) or f'materiau{mi}'
            name, k = base, 2
            while name in mats and mats[name] != info:       # homonymes differents : renommes
                name, k = f'{base}_{k}', k + 1
            mats[name], mat_name[mi] = info, name
        return mat_name[mi]
    for oname, mi, M in g.instances():
        oname = re.sub(r'\s+', '_', oname.strip()) or 'objet'
        Nm = np.linalg.inv(M[:3, :3]).T if abs(np.linalg.det(M[:3, :3])) > 1e-20 else M[:3, :3]
        flip = np.linalg.det(M[:3, :3]) < 0                  # echelle negative : faces retournees
        for mat, pos, nrm, uvs, tris in g.primitives(mi):
            mname = name_of(mat)
            uv = uvs.get(mats[mname].get('texcoord', 0), uvs.get(0))
            P = pos @ M[:3, :3].T + M[:3, 3]
            used = np.unique(tris)                            # sommets servis par les faces seulement
            remap = np.full(len(P), -1, np.int64)
            remap[used] = np.arange(len(used))
            T = remap[tris]
            if flip:
                T = T[:, [0, 2, 1]]
            N = None
            if nrm is not None:
                N = nrm[used] @ Nm.T
                N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
            UV = None
            if uv is not None:
                UV = np.stack([uv[used, 0], 1.0 - uv[used, 1]], 1)
            parts.append((oname, mname, P[used], N, UV, T))
    for info in mats.values():
        info.pop('texcoord', None)
    return parts, mats


def gltf_to_obj(path):
    """(texte OBJ, {nom de materiau: {'texture', 'color', 'alpha'}}, axe vertical 'y'). Une entree `o` par noeud
    (objet), `usemtl` = nom du materiau glTF ; positions en metres (unite de glTF)."""
    parts, mats = _gltf_parts(path)
    lines = []
    nv = nt = nn = 0
    for oname, mname, P, N, UV, T in parts:
        lines.append(f'o {oname}\nusemtl {mname}\n')
        lines.append(''.join(f'v {x:.6f} {y:.6f} {z:.6f}\n' for x, y, z in P))
        has_n, has_uv = N is not None, UV is not None
        if has_n:
            lines.append(''.join(f'vn {x:.5f} {y:.5f} {z:.5f}\n' for x, y, z in N))
        if has_uv:
            lines.append(''.join(f'vt {u:.6f} {v:.6f}\n' for u, v in UV))
        T = T + 1
        if has_n and has_uv:
            fmt = lambda i: f'{nv + i}/{nt + i}/{nn + i}'
        elif has_n:
            fmt = lambda i: f'{nv + i}//{nn + i}'
        elif has_uv:
            fmt = lambda i: f'{nv + i}/{nt + i}'
        else:
            fmt = lambda i: f'{nv + i}'
        lines.append(''.join(f'f {fmt(a)} {fmt(b)} {fmt(c)}\n' for a, b, c in T.tolist()))
        n = len(P)
        nv += n
        nt += n if has_uv else 0
        nn += n if has_n else 0
    if not nv:
        raise ValueError(f'{os.path.basename(path)} : aucun maillage en triangles dans la scène')
    return ''.join(lines), mats, 'y'


def gltf_to_arrays(path):
    """Comme gltf_to_obj, mais directement en tableaux (format de model_build.parse_obj_arrays), sans passer par le
    texte OBJ (2026-11-27 : MoltenMile, 2,4 M triangles : 11 s d'ecriture + 11 s de relecture evitees). Fichier sans
    maillage (lumieres, emetteurs vides) : tableaux vides. -> (tableaux, materiaux, 'y')."""
    parts, mats = _gltf_parts(path)
    groups, gidx = [], {}
    Vs, VTs, VNs, Cs, gids = [], [], [], [], []
    nv = nt = nn = 0
    for oname, mname, P, N, UV, T in parts:
        g = gidx.setdefault((oname, mname), len(groups))
        if g == len(groups):
            groups.append((oname, mname))
        n = len(P)
        C = np.full((len(T), 3, 3), -1, np.int64)
        C[:, :, 0] = T + nv
        if UV is not None:
            C[:, :, 1] = T + nt
            VTs.append(UV)
            nt += n
        if N is not None:
            C[:, :, 2] = T + nn
            VNs.append(N)
            nn += n
        Vs.append(P)
        nv += n
        Cs.append(C)
        gids.append(np.full(len(T), g, np.int32))
    cat = lambda L, w: np.concatenate(L).astype(np.float64) if L else np.zeros((0, w))
    A = {'V': cat(Vs, 3), 'VT': cat(VTs, 2), 'VN': cat(VNs, 3),
         'C': np.concatenate(Cs) if Cs else np.zeros((0, 3, 3), np.int64),
         'gid': np.concatenate(gids) if gids else np.zeros(0, np.int32), 'groups': groups, 'mtllibs': []}
    return A, mats, 'y'
