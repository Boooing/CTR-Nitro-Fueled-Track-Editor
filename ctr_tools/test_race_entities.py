"""Tests hors jeu : ajout d'une spline IA complete + stats TTR (Crash Cove, versions update2 d'origine).

Usage : python test_race_entities.py <dossier archives>
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pak_tool  # noqa: E402
from igz import IgzFile  # noqa: E402
from race_entities import RaceSystemEditor, TTRStatsEditor, fnv1a  # noqa: E402
from race_system import RaceSystem  # noqa: E402

TRACK = 'T111_Crash_Cove'


def check(cond, msg):
    print(('OK   ' if cond else 'ECHEC') + ' ' + msg)
    if not cond:
        raise SystemExit(1)


def main(archives):
    rs_data, _ = pak_tool.read_latest(archives, f'maps/Octane/{TRACK}/{TRACK}_RaceSystem.igz', 't111_crash_cove.pak')
    ttr_data, _ = pak_tool.read_latest(archives, f'ttrStats/{TRACK}_TTRStats.igz', 't111_crash_cove.pak')
    rs = RaceSystemEditor(rs_data, TRACK)
    base = rs.points('AI_Spline_03')
    pts = [list(p) for p in base]
    pts[2] = [pts[2][0] + 300, pts[2][1], pts[2][2]]
    n_obj = len(rs.igz.objects)
    rs.add_ai_spline('AI_Spline_20', template='AI_Spline_03', points=pts)
    out = rs.igz.to_bytes()
    check(IgzFile(out).to_bytes() == out, 'RaceSystem modifie : relecture/reecriture stable')

    re = RaceSystemEditor(out, TRACK)
    check('AI_Spline_20' in re.entities_with_spline(), 'AI_Spline_20 est une entite spline nommee')
    check(re.points('AI_Spline_20') == pts, 'ses points sont ceux demandes')
    check(re.points('AI_Spline_03') == base, 'le modele AI_Spline_03 est intact')
    check(len(re.igz.objects) == n_obj + 24, f'{len(re.igz.objects) - n_obj} objets ajoutes (28 du graphe - 4 partages)')
    t1 = re.transition_paths('RaceSystem_SplineTransition_01')
    t2 = re.transition_paths('RaceSystem_SplineTransition_02')
    check(t1['next_ai'][-1] == 'AI_Spline_20' and len(t1['next_ai']) == 6, f'transition 01 -> IA suivantes {t1["next_ai"]}')
    check(t2['previous_ai'][-1] == 'AI_Spline_20', f'transition 02 <- IA precedentes {t2["previous_ai"]}')
    # partage : l'archetype commun n'est pas duplique
    shared = [o for o, t in re.igz.objects.items() if t == 'CRaceTrackSplineComponentData']
    check(len(shared) == 6, f'archetypes CRaceTrackSplineComponentData non dupliques ({len(shared)})')
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, f'{TRACK}_RaceSystem.igz')
        open(p, 'wb').write(out)
        r = RaceSystem(p).decode()
        names = [s['name'] for s in r['ai_paths']]
        check('AI_Spline_20' in names and len(names) == 22, f'race_system voit {len(names)} splines IA')
        t = next(t for t in r['transitions'] if t['name'] == 'RaceSystem_SplineTransition_01')
        check('AI_Spline_20' in t['next_ai_paths'], 'handle T111_Crash_Cove_RaceSystem::AI_Spline_20 resolu')

    ttr = TTRStatsEditor(ttr_data)
    sp, segs = ttr.spline_stats('AI_Spline_03')
    n = ttr.add_spline_stats('AI_Spline_20', template='AI_Spline_03', segments=len(pts) - 1)
    ttr.set_starting_splines(['AI_Spline_20'] * 5)
    tout = ttr.to_bytes()
    t2_ = TTRStatsEditor(tout)
    s2, g2 = t2_.spline_stats('AI_Spline_20')
    check(len(s2) == 1 and len(g2) == len(pts) - 1, f'stats TTR : 1 spline + {len(g2)} segments (modele : {len(segs)})')
    check([t2_.igz.u32(o + 0x10) for o in g2] == list(range(len(pts) - 1)), 'segments indexes 0..n-1')
    check(t2_.starting_splines() == ['AI_Spline_20'] * 5, 'splines de depart remplacees')
    check(all(t2_.igz.u32(o + 0x0C) == fnv1a('AI_Spline_20') for o in t2_._objs('CStartingSplineInfo')), 'hash de depart corrects')
    check(IgzFile(tout).to_bytes() == tout, 'TTRStats modifie : relecture/reecriture stable')
    print('tous les tests passent')


if __name__ == '__main__':
    main(sys.argv[1])
