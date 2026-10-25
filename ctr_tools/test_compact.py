"""Test : IgzFile.compact (blocs abandonnes par les reecritures retires, contenu identique).

Usage : python test_compact.py <dossier archives>
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pak_tool  # noqa: E402
from igz import IgzFile  # noqa: E402
from race_entities import RaceSystemEditor, TTRStatsEditor  # noqa: E402

T, TP = 'T111_Crash_Cove', 't111_crash_cove.pak'


def check(cond, msg):
    print(('OK   ' if cond else 'ECHEC') + ' ' + msg)
    if not cond:
        raise SystemExit(1)


def sem(z):
    """Contenu sans les adresses (qui changent forcement)."""
    return sorted((n, re.sub(r'0x[0-9a-f]+', '#', str(z.dump_object(o)))) for n, o in z.root_objects())


def main(archives):
    ttr = pak_tool.read_latest(archives, f'ttrStats/{T}_TTRStats.igz', TP)[0]
    race = pak_tool.read_latest(archives, f'maps/Octane/{T}/{T}_RaceSystem.igz', TP)[0]
    for name, d in (('TTRStats', ttr), ('RaceSystem', race)):
        z = IgzFile(d)
        check(z.compact() == 0 and z.compact(aggressive=True) == 0 and z.to_bytes() == d, f'{name} d\'origine : identique')
    t = TTRStatsEditor(ttr)
    for i in range(20):
        t.add_spline_stats(f'AI_Spline_9{i:02d}', template='AI_Spline_01', segments=12)
    t.remove_spline_stats('AI_Spline_03')
    before = IgzFile(t.igz.to_bytes())
    gain = t.igz.compact()
    after = IgzFile(t.igz.to_bytes())
    check(gain > 1_000_000 and len(after.raw) < 150_000, f'TTRStats apres 20 ajouts : {len(before.raw)} -> {len(after.raw)} octets')
    check(sem(before) == sem(after), 'TTRStats : meme contenu apres compactage')
    r = RaceSystemEditor(race, T)
    r.add_ai_spline('AI_Spline_77', template='AI_Spline_01')
    r.remove_ai_spline('AI_Spline_02')
    n01 = len(r.points('AI_Spline_01'))             # (apres compact(), les adresses de `r` sont perimees)
    before = IgzFile(r.igz.to_bytes())
    r.igz.compact()
    after = IgzFile(r.igz.to_bytes())
    check(sem(before) == sem(after) and len(after.raw) < len(before.raw), f'RaceSystem : {len(before.raw)} -> {len(after.raw)}, meme contenu')
    r2 = RaceSystemEditor(after.raw, T)
    check(len(r2.points('AI_Spline_77')) == n01 and 'AI_Spline_02' not in r2.by_name,
          'RaceSystem compacte relu : nouvelle spline presente, supprimee absente')
    print('tous les tests passent')


if __name__ == '__main__':
    main(sys.argv[1])
