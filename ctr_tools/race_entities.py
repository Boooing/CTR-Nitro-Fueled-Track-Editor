"""Ajout d'entites de course completes : nouvelle spline IA (+ stats TTR) branchee aux transitions.

    from race_entities import RaceSystemEditor, TTRStatsEditor
    rs = RaceSystemEditor(octets_racesystem, 'T111_Crash_Cove')
    rs.add_ai_spline('AI_Spline_20', template='AI_Spline_03', points=[[x, y, z], ...])
    rs.set_transition_ai_paths('RaceSystem_SplineTransition_01', next=['AI_Spline_20'])
    ttr = TTRStatsEditor(octets_ttrstats)
    ttr.add_spline_stats('AI_Spline_20', template='AI_Spline_03')
    ttr.set_starting_splines(['AI_Spline_20'] * 5)

Une transition reference ses splines par handle 'T111_Crash_Cove_RaceSystem::AI_Spline_NN' (EXNM).
CRaceTrackSplineComponentData de transition : +0x10/+0x18 splines de position precedentes/suivantes,
+0x20/+0x28 splines IA precedentes/suivantes (CEntityHandleList).
TTRStats : CRaceTrackSplineStats / CRaceTrackSplineSegmentStats identifies par _splineHash = FNV-1a 32 bits
du nom (sensible a la casse) ; CStartingSplineInfo = splines IA possibles au depart.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spline_edit import SplineEditor  # noqa: E402

TRANSITION = 'CRaceTrackSplineTransitionComponentData'
FIELDS = {'previous_position': 0x10, 'next_position': 0x18, 'previous_ai': 0x20, 'next_ai': 0x28}


def fnv1a(s):
    h = 0x811C9DC5
    for c in s.encode('latin1'):
        h = ((h ^ c) * 0x01000193) & 0xFFFFFFFF
    return h


class RaceSystemEditor(SplineEditor):
    def __init__(self, data, track):
        super().__init__(data)
        self.track = track
        self.ns = f'{track}_RaceSystem'

    def transitions(self):
        out = {}
        for name, o in self.by_name.items():
            if self.igz.objects.get(o) in ('CEntity', 'igEntity'):
                comp = self.component(o, TRANSITION)
                if comp is not None:
                    out[name] = comp
        return out

    def transition_paths(self, name):
        comp = self.transitions()[name]
        return {k: [n for n, _ in self.igz.handle_list(self.igz.deref(comp + off))] for k, off in FIELDS.items()}

    def set_transition_paths(self, name, **lists):
        """set_transition_paths('...', next_ai=[noms], previous_ai=[...], ...) : remplace les listes donnees."""
        comp = self.transitions()[name]
        for key, names in lists.items():
            lst = self.igz.deref(comp + FIELDS[key])
            self.igz.set_handle_list(lst, [(n, self.ns) for n in names])

    def add_ai_spline(self, new_name, template, points=None, wire=True):
        """Clone l'entite `template` sous `new_name`, avec ses points (monde) eventuellement remplaces.

        wire=True : la nouvelle spline est ajoutee a cote du modele dans toutes les transitions qui le citent.
        """
        if new_name in self.by_name:
            raise ValueError(f'{new_name} existe deja')
        self.igz.deep_clone_entity(self.by_name[template], new_name)
        self._names()
        if points is not None:
            cur = self.points(new_name)
            while len(cur) > len(points):
                self.remove_point(new_name, len(cur) - 1)
                cur = self.points(new_name)
            while len(cur) < len(points):
                self.insert_point(new_name, len(cur), points[len(cur)])
                cur = self.points(new_name)
            for i, p in enumerate(points):
                self.move_point(new_name, i, p)
        if wire:
            for tname in self.transitions():
                paths = self.transition_paths(tname)
                for key in ('previous_ai', 'next_ai'):
                    if template in paths[key] and new_name not in paths[key]:
                        self.set_transition_paths(tname, **{key: paths[key] + [new_name]})
        return self.by_name[new_name]


    def forks(self):
        out = {}
        for name, o in self.by_name.items():
            if self.igz.objects.get(o) in ('CEntity', 'igEntity'):
                comp = self.component(o, 'CRaceTrackForkCheckerComponentData')
                if comp is not None:
                    out[name] = comp
        return out

    def remove_ai_spline(self, name):
        """Supprime une spline IA : retiree des transitions/embranchements et de la liste racine."""
        ent = self.by_name[name]
        for tname in self.transitions():
            paths = self.transition_paths(tname)
            for key in ('previous_ai', 'next_ai'):
                if name in paths[key]:
                    self.set_transition_paths(tname, **{key: [n for n in paths[key] if n != name]})
        for fcomp in self.forks().values():
            lst = self.igz.deref(fcomp + 0x18)                      # _aiPaths
            cur = self.igz.handle_list(lst)
            if any(h and h[0] == name for h in cur):
                self.igz.set_handle_list(lst, [h for h in cur if h and h[0] != name])
        others = set()
        for n, o in self.by_name.items():
            if o != ent and self.igz.objects.get(o) in ('CEntity', 'igEntity'):
                others |= self.igz.reachable(o)[0]
        mine = self.igz.reachable(ent)[0]
        self.igz.remove_roots([o for o in mine if o not in others])
        self._names()


class TTRStatsEditor:
    def __init__(self, data):
        from igz import IgzFile
        self.igz = IgzFile(data)

    def _objs(self, type_name):
        return [o for o, t in self.igz.objects.items() if t == type_name]

    def spline_stats(self, name):
        h = fnv1a(name)
        return ([o for o in self._objs('CRaceTrackSplineStats') if self.igz.u32(o + 0x0C) == h],
                sorted((o for o in self._objs('CRaceTrackSplineSegmentStats') if self.igz.u32(o + 0x0C) == h),
                       key=lambda o: self.igz.u32(o + 0x10)))

    def add_spline_stats(self, new_name, template, segments=None):
        """Duplique les stats de `template` (spline + segments) pour `new_name`.

        segments : nombre de segments de la nouvelle spline (nb de points - 1) ; par defaut celui du modele.
        Les stats apprises (compteurs, vitesses) sont celles du modele : le jeu les remet a jour en course.
        """
        sp, segs = self.spline_stats(template)
        if not sp:
            raise KeyError(f'pas de stats pour {template}')
        h = fnv1a(new_name)
        n = 0
        for o in sp:
            c = self.igz.clone_object(o)
            struct.pack_into('<I', *self.igz._loc(c + 0x0C), h)
            self.igz.set_string_ref(c + 0x10, new_name)
            self.igz.add_root(c, f'CRaceTrackSplineStats_{new_name}')
        want = segments if segments is not None else len(segs)
        for i in range(want):
            src = segs[min(i, len(segs) - 1)]
            c = self.igz.clone_object(src)
            struct.pack_into('<Ii', *self.igz._loc(c + 0x0C), h, i)
            self.igz.add_root(c, f'CRaceTrackSplineSegmentStats_{new_name}_{i}')
            n += 1
        return n

    def resize_segments(self, name, n):
        """Ajuste le nombre de segments de stats d'une spline (apres ajout/suppression de points)."""
        sp, segs = self.spline_stats(name)
        if not segs:
            return
        h = fnv1a(name)
        for i in range(len(segs), n):
            c = self.igz.clone_object(segs[-1])
            struct.pack_into('<Ii', *self.igz._loc(c + 0x0C), h, i)
            self.igz.add_root(c, f'CRaceTrackSplineSegmentStats_{name}_{i}')
        extra = segs[n:]
        if extra:
            self.igz.remove_roots(extra)
            for o in extra:
                struct.pack_into('<I', *self.igz._loc(o + 0x0C), 0)

    def remove_spline_stats(self, name):
        sp, segs = self.spline_stats(name)
        self.igz.remove_roots(sp + segs)
        # objets retires de la racine : on les rend aussi introuvables par hash
        for o in sp + segs:
            struct.pack_into('<I', *self.igz._loc(o + 0x0C), 0)

    def starting_splines(self):
        return [self.igz.string(self.igz.u32(o + 0x10)) for o in self._objs('CStartingSplineInfo')]

    def set_starting_splines(self, names):
        objs = self._objs('CStartingSplineInfo')
        if len(names) != len(objs):
            raise ValueError(f'{len(objs)} emplacements de depart, {len(names)} noms fournis')
        for o, nm in zip(objs, names):
            struct.pack_into('<I', *self.igz._loc(o + 0x0C), fnv1a(nm))
            self.igz.set_string_ref(o + 0x10, nm)

    def to_bytes(self):
        return self.igz.to_bytes()
