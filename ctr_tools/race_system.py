"""Decode le fichier <piste>_RaceSystem.igz : splines IA, splines de position (progression / tours),
transitions (ligne d'arrivee, enchainement des sections), embranchements, points de depart.

Usage : python race_system.py <..._RaceSystem.igz> [dossier_sortie]
Sorties : <nom>.race.json (resume) et <nom>.splines.obj (polylignes, a importer dans Blender).

Verifie sur Crash Cove :
  * position monde d'un point = _parentSpacePosition de l'entite + _position du point (Z = vertical) ;
  * splines ouvertes, points `_smooth` interpoles en Catmull-Rom : la longueur obtenue colle a 0,1 %
    pres a igSpline2._length. Le sens de `_flags` (0x100 partout) reste inconnu.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from igz import IgzFile  # noqa: E402

SAMPLES_PER_SEGMENT = 8


def catmull_rom(points, closed, n=SAMPLES_PER_SEGMENT):
    if len(points) < 2:
        return points
    pts = points + points[:3] if closed else [points[0]] + points + [points[-1]]
    segs = len(points) if closed else len(points) - 1
    out = []
    for s in range(segs):
        p0, p1, p2, p3 = (pts[s], pts[s + 1], pts[s + 2], pts[s + 3]) if not closed else \
            (pts[s - 1] if s else points[-1], pts[s], pts[s + 1], pts[s + 2])
        for k in range(n):
            t = k / n
            t2, t3 = t * t, t * t * t
            out.append([0.5 * ((2 * p1[i]) + (-p0[i] + p2[i]) * t + (2 * p0[i] - 5 * p1[i] + 4 * p2[i] - p3[i]) * t2
                               + (-p0[i] + 3 * p1[i] - 3 * p2[i] + p3[i]) * t3) for i in range(3)])
    out.append(points[0] if closed else points[-1])
    return out


class RaceSystem:
    def __init__(self, path, file_ns=None):
        """path : chemin ou octets ; file_ns : nom du fichier sans extension (espace de noms des handles)."""
        self.igz = IgzFile(path)
        self.file_ns = file_ns or os.path.splitext(os.path.basename(path))[0]
        self.names = {o: n for n, o in self.igz.root_objects()}
        self.by_name = {n: o for o, n in self.names.items() if n}
        # entites de la liste racine seulement (une entite supprimee reste dans le fichier, hors racine)
        self.entities = [o for _, o in self.igz.root_objects() if self.igz.objects.get(o) == 'CEntity']

    # -- helpers ---------------------------------------------------------------------------
    def obj(self, off):
        return self.igz.dump_object(off) if off is not None else None

    def ref(self, v):
        return int(v['@ref'], 16) if isinstance(v, dict) and '@ref' in v else None

    def handle_name(self, h):
        """'Ns::Name' -> 'Name' si la reference est locale a ce fichier."""
        if not isinstance(h, dict) or '@handle' not in h:
            return None
        ns, _, name = h['@handle'].partition('::')
        return name if ns == self.file_ns else h['@handle']

    def handle_list(self, v):
        off = self.ref(v)
        if off is None:
            return []
        return [self.handle_name(x) for x in self.obj(off).get('@items', [])]

    def components(self, ent):
        e = self.obj(ent)
        data = self.obj(self.ref(e.get('_entityData')))
        table = self.obj(self.ref(data.get('_componentData'))) if data else None
        comps = {}
        for key, val in (table or {}).get('@items', {}).items():
            off = self.ref(val)
            if off is not None:
                comps[self.igz.objects[off]] = self.obj(off)
        return e, comps

    def spline_points(self, spline_comp, origin):
        spl = self.obj(self.ref(spline_comp.get('_spline')))
        if not spl:
            return [], False, 0
        cps = self.obj(self.ref(spl.get('_data')))
        pts = []
        for item in cps.get('@items', []):
            cp = self.obj(self.ref(item))
            pts.append([round(origin[i] + cp['_position'][i], 3) for i in range(3)])
        return pts, spl.get('_flags'), spl.get('_length')

    # -- decode ----------------------------------------------------------------------------
    def decode(self):
        res = {'track': self.file_ns.replace('_RaceSystem', ''), 'ai_paths': [], 'position_paths': [],
               'transitions': [], 'fork_checkers': [], 'trigger_volumes': [], 'other_entities': []}
        for ent in self.entities:
            name = self.names.get(ent, f'entity@{ent:#x}')
            e, comps = self.components(ent)
            origin = e['_parentSpacePosition']
            rts = comps.get('CRaceTrackSplineComponentData')
            spline = comps.get('CSplineComponentData')
            if spline is not None:
                pts, flags, length = self.spline_points(spline, origin)
                entry = {'name': name, 'origin': origin, 'spline_flags': flags, 'length': length,
                         'control_points': pts}
                if rts:
                    entry.update({'difficulty': rts.get('_pathDifficulty'), 'shortcut': rts.get('_isShortcut'),
                                  'hazardous': rts.get('_isHazardous'),
                                  'start': self.handle_name(rts.get('_start')), 'end': self.handle_name(rts.get('_end')),
                                  'respawn_points': self.handle_list(rts.get('_respawnPoints'))})
                res['ai_paths'].append(entry)   # reclasse plus bas d'apres les transitions
                continue
            tr = comps.get('CRaceTrackSplineTransitionComponentData')
            if tr:
                res['transitions'].append({
                    'name': name, 'position': origin,
                    'increment_lap': tr.get('_incrementLap'), 'teleporter': tr.get('_isTeleporter'),
                    'previous_position_paths': self.handle_list(tr.get('_previousPositionPaths')),
                    'next_position_paths': self.handle_list(tr.get('_nextPositionPaths')),
                    'previous_ai_paths': self.handle_list(tr.get('_previousAIPaths')),
                    'next_ai_paths': self.handle_list(tr.get('_nextAIPaths')),
                    'trigger': self.trigger(comps)})
                continue
            fk = comps.get('CRaceTrackForkCheckerComponentData')
            if fk:
                res['fork_checkers'].append({
                    'name': name, 'position': origin,
                    'position_path': self.handle_name(fk.get('_positionPath')),
                    'ai_paths': self.handle_list(fk.get('_aiPaths')), 'trigger': self.trigger(comps)})
                continue
            if 'CTriggerVolumeBoxComponentData' in comps:
                res['trigger_volumes'].append({'name': name, 'position': origin, 'trigger': self.trigger(comps)})
                continue
            res['other_entities'].append({'name': name, 'position': origin, 'components': sorted(comps)})
        # une spline est "de position" (progression/classement) si une transition ou un embranchement la cite
        pos_names = {n for t in res['transitions'] for n in t['previous_position_paths'] + t['next_position_paths']}
        pos_names |= {f['position_path'] for f in res['fork_checkers']}
        res['position_paths'] = [s for s in res['ai_paths'] if s['name'] in pos_names]
        res['ai_paths'] = [s for s in res['ai_paths'] if s['name'] not in pos_names]
        # points de depart : listes CPlayerStartEntityHandleList (references au fichier _Design)
        res['player_starts'] = {
            self.names.get(o, f'@{o:#x}'): self.handle_list({'@ref': f'{o:#x}'})
            for o, t in self.igz.objects.items() if t == 'CPlayerStartEntityHandleList'}
        return res

    def trigger(self, comps):
        tv = comps.get('CTriggerVolumeBoxComponentData')
        if not tv:
            return None
        return {'offset': tv.get('_offset'), 'rotation': tv.get('_rotation'), 'dimensions': tv.get('_dimensions'),
                'convex_radius': tv.get('_convexRadius')}


def write_obj(res, path):
    lines, v = [f'# splines de {res["track"]} (unites du jeu, coordonnees brutes)'], 0
    for kind in ('position_paths', 'ai_paths'):
        for sp in res[kind]:
            pts = catmull_rom(sp['control_points'], False)
            if len(pts) < 2:
                continue
            lines.append(f'o {kind[:-6]}_{sp["name"]}')
            lines += [f'v {p[0]:.3f} {p[1]:.3f} {p[2]:.3f}' for p in pts]
            lines.append('l ' + ' '.join(str(v + i + 1) for i in range(len(pts))))
            v += len(pts)
    for kind in ('transitions', 'fork_checkers', 'trigger_volumes'):
        for t in res[kind]:
            p = t['position']
            lines.append(f'o {kind[:-1]}_{t["name"]}')
            lines.append(f'v {p[0]:.3f} {p[1]:.3f} {p[2]:.3f}')
            lines.append(f'p {v + 1}')
            v += 1
    with open(path, 'w') as f:
        f.write('\n'.join(lines) + '\n')


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    rs = RaceSystem(argv[1])
    res = rs.decode()
    out_dir = argv[2] if len(argv) > 2 else os.path.dirname(argv[1])
    base = os.path.join(out_dir, res['track'])
    with open(base + '.race.json', 'w') as f:
        json.dump(res, f, indent=1)
    write_obj(res, base + '.splines.obj')
    print(f'piste {res["track"]}')
    print(f'  {len(res["position_paths"])} splines de position, {len(res["ai_paths"])} splines IA, '
          f'{len(res["transitions"])} transitions, {len(res["fork_checkers"])} embranchements, '
          f'{len(res["trigger_volumes"])} volumes, {len(res["other_entities"])} autres entites')
    for t in res['transitions']:
        tag = ' <- LIGNE D\'ARRIVEE (incrementLap)' if t['increment_lap'] else ''
        print(f'  {t["name"]}: {t["previous_position_paths"]} -> {t["next_position_paths"]}{tag}')
    print(f'ecrit {base}.race.json et {base}.splines.obj')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
