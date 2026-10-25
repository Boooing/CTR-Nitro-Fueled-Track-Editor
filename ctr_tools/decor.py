"""Decor d'une piste : objets places par les fichiers maps/Octane/<Piste>/<Piste>_Art*.igz.

Chaque objet est une entite (igEntity) dont la table de composants contient un CModelComponentData
(_fileName = 'models:\\...\\X.igb' -> archive 'models/.../X.igz').
  igEntity +0x20 position (vec3), +0x30 -> igEntityTransform, +0x40 -> donnees -> table de composants
  igEntityTransform +0x60 Euler XYZ (radians, applique R = Rz * Ry * Rx), +0x6C echelle globale,
                    +0x70 echelle xyz (echelle finale = globale * xyz)
Les entites sans igEntityTransform ne peuvent qu'etre deplacees.

    df = DecorFile(octets_du_fichier_art)
    df.objects()                              # [{id, name, model, pos, euler, scale, has_transform}]
    df.set_transform(id, pos=[...], euler=[...], scale=[...])
    new_id = df.duplicate(id, 'MonPalmier', pos=[...])
    df.delete(id)
    df.to_bytes()

Modeles : model_mesh(octets_igz) -> (positions float32, indices uint32) de tous les draw calls,
doublons retires (meme nombre de triangles et meme boite englobante = passe d'ombre / variante).
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from igz import IgzFile  # noqa: E402

ENTITY_TYPES = ('igEntity', 'CEntity', 'CGameEntity')


class DecorFile:
    def __init__(self, data):
        self.igz = IgzFile(data)
        self._refresh()

    def _refresh(self):
        self.names = {o: n for n, o in self.igz.root_objects()}
        self.roots = set(self.names)

    def _model_of(self, ent):
        z = self.igz
        data = z.deref(ent + 0x40)
        table = z.deref(data + 0x10) if data is not None else None
        for _, v in (z.hash_items(table) if table is not None else []):
            off = int(v['@ref'], 16) if isinstance(v, dict) and '@ref' in v else None
            if off is not None and z.objects.get(off) == 'CModelComponentData':
                return z.dump_object(off).get('_fileName')
        return None

    def objects(self):
        z, out = self.igz, []
        for o in sorted(self.roots):
            if z.objects.get(o) not in ENTITY_TYPES:
                continue
            model = self._model_of(o)
            if not model:
                continue
            tr = z.deref(o + 0x30)
            if tr is not None:
                euler = list(struct.unpack_from('<3f', *z._loc(tr + 0x60)))
                s = z.f32(tr + 0x6C)
                scale = [c * s for c in struct.unpack_from('<3f', *z._loc(tr + 0x70))]
            else:
                euler, scale = [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]
            out.append({'id': o, 'name': self.names.get(o), 'model': model, 'pos': z.vec3(o + 0x20),
                        'euler': euler, 'scale': scale, 'has_transform': tr is not None})
        return out

    def set_transform(self, ent, pos=None, euler=None, scale=None):
        z = self.igz
        if pos is not None:
            struct.pack_into('<3f', *z._loc(ent + 0x20), *pos)
        tr = z.deref(ent + 0x30)
        if tr is None:
            if euler is not None or scale is not None:
                raise ValueError('cet objet n\'a pas de transformation : seule la position est modifiable')
            return
        if euler is not None:
            struct.pack_into('<3f', *z._loc(tr + 0x60), *euler)
        if scale is not None:
            s = z.f32(tr + 0x6C) or 1.0
            struct.pack_into('<3f', *z._loc(tr + 0x70), *[c / s for c in scale])
        struct.pack_into('<I', *z._loc(tr + 0x7C), 1)          # _isDirty

    def set_model(self, ent, file_name):
        """Change le fichier modele d'un objet (CModelComponentData._fileName, +0x10).
        Les composants modele ne sont jamais partages entre entites (verifie sur Crash Cove)."""
        z = self.igz
        table = z.deref(z.deref(ent + 0x40) + 0x10)
        for _, v in z.hash_items(table):
            off = int(v['@ref'], 16) if isinstance(v, dict) and '@ref' in v else None
            if off is not None and z.objects.get(off) == 'CModelComponentData':
                z.set_string_ref(off + 0x10, file_name)
                return
        raise KeyError('objet sans composant modele')

    def duplicate(self, ent, new_name, pos=None, euler=None, scale=None):
        new = self.igz.deep_clone_entity(ent, new_name, entity_types=ENTITY_TYPES)
        self._refresh()
        self.set_transform(new, pos, euler, scale)
        return new

    def duplicate_many(self, specs):
        """specs = [(source, nom, pos, euler|None, echelle|None)] -> nouveaux ids.

        Propriete des objets calculee une fois et liste racine reecrite une seule fois (pas de blocs abandonnes
        a chaque copie). Les sources doivent exister avant l'appel."""
        z = self.igz
        owned = z.owned_by(ENTITY_TYPES)
        names = dict(self.names)
        new_ids, pairs = [], []
        for src, name, *_ in specs:
            new, p = z.clone_owned(src, name, owned[src], names)
            new_ids.append(new)
            pairs += p
        z.add_roots(pairs)
        self._refresh()
        for (_, _, pos, euler, scale), new in zip(specs, new_ids):
            self.set_transform(new, pos, euler, scale)
        return new_ids

    def delete(self, ent):
        """Retire l'objet (et ce qui lui est propre) de la liste racine : il n'est plus cree par le jeu."""
        self.delete_many([ent])

    def delete_many(self, ents):
        ents = set(ents)
        if not ents:
            return
        z = self.igz
        others, mine = set(), set()
        for o in self.roots:
            if z.objects.get(o) in ENTITY_TYPES:
                (mine if o in ents else others).update(z.reachable(o)[0])
        z.remove_roots([o for o in mine if o not in others])
        self._refresh()

    def unique_name(self, base):
        used = set(self.names.values())
        k = 1
        while f'{base}_copie{k:02d}' in used:
            k += 1
        return f'{base}_copie{k:02d}'

    def to_bytes(self):
        return self.igz.to_bytes()


def model_logical_path(file_name):
    """'models:\\Levels\\X.igb' -> 'models/Levels/X.igz' (nom dans les archives)."""
    rel = file_name.replace('\\', '/').split(':', 1)[-1].lstrip('/')
    return 'models/' + os.path.splitext(rel)[0] + '.igz'


def model_mesh(data):
    """(positions [x,y,z,...], indices [...]) de tous les draw calls d'un modele, doublons retires."""
    z = IgzFile(data)
    positions, indices, seen = [], [], set()
    for o, t in z.objects.items():
        if t != 'igModelDrawCallData':
            continue
        gvb, gib = z.deref(o + 0x48), z.deref(o + 0x50)
        vb = z.deref(gvb + 0x20) if gvb is not None else None
        ib = z.deref(gib + 0x20) if gib is not None else None
        if vb is None or ib is None:
            continue
        ni = z.u32(ib + 0x0C)
        key = (ni, tuple(round(c, 1) for c in struct.unpack_from('<6f', *z._loc(o + 0x20))))
        if key in seen:
            continue
        seen.add(key)
        nv = z.u32(vb + 0x0C)
        vdata, _ = z.memory_ref(vb + 0x20)
        fmt = z.deref(vb + 0x30)
        idata, _ = z.memory_ref(ib + 0x20)
        if vdata is None or fmt is None or idata is None:
            continue
        stride = z.u32(fmt + 0x0C)
        pos_off = 0
        el, el_size = z.memory_ref(fmt + 0x10)
        if el is not None:
            eb, eo = z._loc(el)
            for i in range(el_size // 12):
                e = eb[eo + i * 12:eo + i * 12 + 12]
                if e[4] == 0 and e[0] == 2:
                    pos_off = struct.unpack_from('<H', e, 8)[0]
                    break
        vbuf, vo = z._loc(vdata)
        base = len(positions) // 3
        for i in range(nv):
            positions += struct.unpack_from('<3f', vbuf, vo + i * stride + pos_off)
        ibuf, io = z._loc(idata)
        indices += [base + i for i in struct.unpack_from(f'<{ni}H', ibuf, io)]
    return positions, indices
