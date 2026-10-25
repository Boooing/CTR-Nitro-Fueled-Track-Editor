"""Edition des splines d'un fichier _RaceSystem.igz (ou de tout igz contenant des CSplineComponentData).

    from spline_edit import SplineEditor
    ed = SplineEditor('..._RaceSystem.igz')
    ed.points('AI_Spline_01')                       # positions monde
    ed.move_point('AI_Spline_01', 3, [x, y, z])
    ed.insert_point('AI_Spline_01', 6, [x, y, z])   # nouveau point avant l'index 6
    ed.remove_point('AI_Spline_01', 2)
    ed.save('sortie.igz')

Les positions sont en coordonnees monde (entite + point). `_length` de la spline est recalcule
(Catmull-Rom, meme methode que celle verifiee a 0,1 % pres sur les fichiers du jeu).
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from igz import IgzFile  # noqa: E402

SPLINE_SUFFIX = '_entityData_componentData_Spline'


def catmull_rom_length(pts, n=32):
    if len(pts) < 2:
        return 0.0
    ext = [pts[0]] + pts + [pts[-1]]
    total, prev = 0.0, pts[0]
    for s in range(len(pts) - 1):
        p0, p1, p2, p3 = ext[s], ext[s + 1], ext[s + 2], ext[s + 3]
        for k in range(1, n + 1):
            t = k / n
            t2, t3 = t * t, t * t * t
            q = [0.5 * (2 * p1[i] + (-p0[i] + p2[i]) * t + (2 * p0[i] - 5 * p1[i] + 4 * p2[i] - p3[i]) * t2
                        + (-p0[i] + 3 * p1[i] - 3 * p2[i] + p3[i]) * t3) for i in range(3)]
            total += sum((q[i] - prev[i]) ** 2 for i in range(3)) ** 0.5
            prev = q
    return total


class SplineEditor:
    def __init__(self, path_or_bytes):
        self.igz = IgzFile(path_or_bytes)
        self._names()

    def _names(self):
        self.by_name = {n: o for n, o in self.igz.root_objects() if n}

    # -- acces ---------------------------------------------------------------------------
    def component(self, ent, type_name):
        """Composant d'un type donne : entite +0x40 -> donnees +0x10 -> table de composants."""
        data = self.igz.deref(ent + 0x40)
        table = self.igz.deref(data + 0x10) if data is not None else None
        for _, v in (self.igz.hash_items(table) if table is not None else []):
            off = int(v['@ref'], 16) if isinstance(v, dict) and '@ref' in v else None
            if off is not None and self.igz.objects.get(off) == type_name:
                return off
        return None

    def _spline_component(self, ent):
        return self.component(ent, 'CSplineComponentData')

    def set_increment_lap(self, entity, value):
        comp = self.component(self.by_name[entity], 'CRaceTrackSplineTransitionComponentData')
        if comp is None:
            raise KeyError(f'{entity} n\'est pas une transition')
        self.igz.set_field(comp, '_incrementLap', bool(value))

    def entities_with_spline(self):
        return sorted(n for n, o in self.by_name.items()
                      if self.igz.objects.get(o) in ('CEntity', 'igEntity') and self._spline_component(o) is not None)

    def _parts(self, entity):
        ent = self.by_name[entity]
        origin = self.igz.vec3(ent + 0x20)            # igEntity._parentSpacePosition
        comp = self._spline_component(ent)
        if comp is None:
            raise KeyError(f'{entity} n\'a pas de composant spline')
        spline = self.igz.deref(comp + 0x10)          # CSplineComponentData._spline
        cps = self.igz.deref(spline + 0x10)           # igSpline2._data
        return origin, spline, cps

    def points(self, entity):
        origin, _, cps = self._parts(entity)
        out = []
        for cp in self.igz.object_list(cps):
            p = self.igz.vec3(cp + 0x0C)              # igSplineControlPoint2._position
            out.append([origin[i] + p[i] for i in range(3)])
        return out

    # -- edition -------------------------------------------------------------------------
    def _local(self, entity, world):
        origin, _, _ = self._parts(entity)
        return [world[i] - origin[i] for i in range(3)]

    def move_point(self, entity, index, world):
        _, _, cps = self._parts(entity)
        cp = self.igz.object_list(cps)[index]
        self.igz.set_field(cp, '_position', self._local(entity, world))
        self._update_length(entity)

    def insert_point(self, entity, index, world, name=None):
        """Insere un point (clone du voisin : memes tangentes/drapeaux) avant `index`."""
        _, _, cps = self._parts(entity)
        items = self.igz.object_list(cps)
        template = items[min(index, len(items) - 1)]
        cp = self.igz.clone_object(template)
        self.igz.set_field(cp, '_position', self._local(entity, world))
        self.igz.list_insert(cps, index, cp)
        if name is None:
            base = entity + SPLINE_SUFFIX + '_spline_data_'
            k = len(items)
            while f'{base}{k}' in self.by_name:
                k += 1
            name = f'{base}{k}'
        self.igz.add_root(cp, name)
        self._names()
        self._update_length(entity)
        return cp

    def remove_point(self, entity, index):
        """Retire le point de la spline (l'objet reste dans le fichier mais n'est plus reference)."""
        _, _, cps = self._parts(entity)
        if len(self.igz.object_list(cps)) <= 2:
            raise ValueError('une spline doit garder au moins 2 points')
        self.igz.list_remove(cps, index)
        self._update_length(entity)

    def _update_length(self, entity):
        _, spline, _ = self._parts(entity)
        struct.pack_into('<f', *self.igz._loc(spline + 0x68), catmull_rom_length(self.points(entity)))

    def length(self, entity):
        _, spline, _ = self._parts(entity)
        return self.igz.f32(spline + 0x68)

    def save(self, path):
        self.igz.save(path)

    def to_bytes(self):
        return self.igz.to_bytes()
