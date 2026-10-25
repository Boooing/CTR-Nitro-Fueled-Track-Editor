"""Test : caisses d'objets (lecture, reecriture depuis l'original, placement automatique sur le trace).

Usage : python test_powerup.py <dossier archives>
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pak_tool  # noqa: E402
import powerup  # noqa: E402
from ai_gen import GroundQuery  # noqa: E402
from race_system import RaceSystem  # noqa: E402

T = 'T111_Crash_Cove'


def check(cond, msg):
    print(('OK   ' if cond else 'ECHEC') + ' ' + msg)
    if not cond:
        raise SystemExit(1)


def race_path(rs):
    """Splines de position dans l'ordre de course depuis la ligne d'arrivee."""
    by = {p['name']: p for p in rs['position_paths']}
    ts = rs['transitions']
    t = next(x for x in ts if x['increment_lap'])
    out, seen = [], set()
    while t and t['name'] not in seen:
        seen.add(t['name'])
        nxt = [n.split('::')[-1] for n in t.get('next_position_paths') or []]
        if not nxt or nxt[0] not in by:
            break
        out.append(by[nxt[0]]['control_points'])
        t = next((x for x in ts if nxt[0] in [n.split('::')[-1] for n in x.get('previous_position_paths') or []]), None)
    return powerup.chain_paths(out)


def main(archives):
    pak = T.lower() + '.pak'
    data = pak_tool.read_latest(archives, powerup.powerup_file(T), pak)[0]
    crates = powerup.read_crates(data)
    kinds = [c['kind'] for c in crates]
    check(kinds.count('question') == 18 and kinds.count('fruit') == 3, f'{len(crates)} caisses : 18 « ? » + 3 fruits')
    ground = GroundQuery.from_hkx(pak_tool.read_latest(archives, f'models/maps/Octane/{T}/StaticCollision_{T}.hkx', pak)[0])
    # au sol (0 a 16 po au-dessus) ; 2 caisses de fruits sont en l'air (sur un saut)
    dz = [c['pos'][2] - g[0] for c in crates for g in [ground.at(c['pos'][0], c['pos'][1], c['pos'][2], 60)] if g]
    check(len(dz) == 19 and all(-1 <= d <= 20 for d in dz), f'{len(dz)} caisses posees au sol (ecart {min(dz):.0f} a {max(dz):.0f} po)')
    # reecriture : une gardee deplacee, une retiree, deux ajoutees
    want = [dict(c) for c in crates[1:]]
    want[0]['pos'] = [want[0]['pos'][0] + 100, want[0]['pos'][1], want[0]['pos'][2]]
    want += [{'kind': 'question', 'pos': [0.0, 0.0, 500.0]}, {'kind': 'fruit', 'pos': [10.0, 0.0, 500.0]}]
    z, rep, new = powerup.write_crates(data, want)
    back = powerup.read_crates(z.to_bytes())
    names = [c['name'] for c in back]
    check(len(back) == 22 and crates[0]['name'] not in names and 'crate_question_019' in names and 'crate_fruit_001' in names,
          f'reecriture : {rep}')
    moved = next(c for c in back if c['name'] == want[0]['name'])
    check(abs(moved['pos'][0] - want[0]['pos'][0]) < 0.01, 'position ecrite')
    check(next(c for c in back if c['name'] == 'crate_question_019')['kind'] == 'question', 'copie du bon type')
    # caisse inclinee d'origine (pente de Crash Cove) deplacee : remise a plat comme les autres
    import struct
    from decor import DecorFile
    tilted = [dict(c) for c in crates]
    tilted[3]['pos'] = [0.0, 100.0, 500.0]                     # crate_question_001
    z2, _, _ = powerup.write_crates(data, tilted)
    df = DecorFile(z2.to_bytes())
    ent = next(o for o, n in df.names.items() if n == 'crate_question_001')
    ref = next(o for o, n in df.names.items() if n == 'crate_question_005')
    pitch = struct.unpack_from('<3f', *df.igz._loc(df.igz.deref(ent + 0x30) + 0x60))
    check(crates[3]['name'] == 'crate_question_001' and pitch == (0.0, 0.0, 0.0)
          and df.igz.u32(ent + 0x38) == df.igz.u32(ref + 0x38), 'caisse inclinee deplacee : remise a plat')
    # boosters : plaque turbo de Sewer Speedway copiee dans ce fichier (types, chaines, handles EXID / EXNM, RNEX)
    from igz import IgzFile
    from model_build import tdep_entries
    donor = powerup.boost_donor(lambda p, pak: pak_tool.read_latest(archives, p, pak)[0])
    z3, rep3, _ = powerup.write_crates(data, crates + [{'kind': 'boost', 'pos': [1.0, 2.0, 3.0], 'yaw': 0.5, 'dims': [600, 900, 1000]}], donor)
    raw = z3.to_bytes()
    b = [c for c in powerup.read_crates(raw) if c['kind'] == 'boost']
    check(len(b) == 1 and b[0]['pos'] == [1.0, 2.0, 3.0] and b[0]['yaw'] == 0.5 and b[0]['dims'] == [600.0, 900.0, 1000.0],
          f'booster ecrit et relu : {rep3}')
    zz = IgzFile(raw)
    vsc = next(o for n, o in zz.root_objects() if n == 'TurboPad_001_entityData_componentData_CommonTurboPad')
    src = donor[0]
    sv = next(o for n, o in src.root_objects() if n.endswith('GPI_SpeedBoostZone006_entityData_componentData_CommonTurboPad'))
    hs = lambda f, m: [f.exid_pairs()[f.u32(m + k)] for k in range(0, 0x48, 8) if f.is_handle(m + k)]
    check(hs(zz, zz.deref(vsc + 0x10)) == hs(src, src.deref(sv + 0x10)) and len(hs(zz, zz.deref(vsc + 0x10))) == 8,
          '8 references (donnees de boost, sons, vibration) identiques a l\'original')
    check(zz._exnm_flagged(0)[zz.u64(vsc + 0x18)] == ('common_KartBoostData', 'common_TurboPad'), 'script relie (RNEX)')
    check(set(powerup.BOOST_TDEP) <= set(tdep_entries(zz)), 'dependances : script + vibration')
    # placement automatique sur le trace de Crash Cove
    rs = RaceSystem(pak_tool.read_latest(archives, f'maps/Octane/{T}/{T}_RaceSystem.igz', pak)[0],
                    file_ns=f'{T}_RaceSystem').decode()
    path = race_path(rs)
    out, rep = powerup.auto_rows(ground, path, rows=5, per_row=4, fruit=3)
    q = [c for c in out if c['kind'] == 'question']
    check(len(q) >= 16 and sum(c['kind'] == 'fruit' for c in out) >= 2, f'automatique : {len(out)} caisses — {rep}')
    on_ground = sum(1 for c in out if abs(c['pos'][2] - powerup.LIFT - ground.at(c['pos'][0], c['pos'][1], c['pos'][2])[0]) < 1)
    check(on_ground == len(out), 'toutes posees sur le sol')
    # autres objets du jeu : TNT / Nitro (arenes, mode cristaux) et fruit Wumpa pose (Turbo Track)
    read = lambda p, pk: pak_tool.read_latest(archives, p, pk)[0]
    extras = {k: powerup.extra_donor(k, read) for k in powerup.EXTRAS}
    more = [{'kind': 'tnt', 'pos': [10.0, 20.0, 30.0]}, {'kind': 'nitro', 'pos': [40.0, 50.0, 60.0]},
            {'kind': 'wumpa', 'pos': [70.0, 80.0, 90.0]}, {'kind': 'wumpa', 'pos': [100.0, 80.0, 90.0]}]
    z4, rep4, _ = powerup.write_crates(data, crates + more, None, extras)
    raw4 = z4.to_bytes()
    got = [(c['kind'], c['pos']) for c in powerup.read_crates(raw4) if c['kind'] in powerup.EXTRAS]
    check(got == [(c['kind'], c['pos']) for c in more], f'TNT, Nitro et fruits ecrits et relus : {rep4}')
    deps = set(tdep_entries(IgzFile(raw4)))
    check(all(set(e['tdep']) <= deps for e in powerup.EXTRAS.values()), 'dependances des trois objets ajoutees')
    out2, rep2 = powerup.auto_rows(ground, path, rows=4, per_row=4, tnt=2, nitro=2, wumpa_lines=2, wumpa_per_line=5)
    n = {k: sum(c['kind'] == k for c in out2) for k in ('tnt', 'nitro', 'wumpa')}
    check(n == {'tnt': 2, 'nitro': 2, 'wumpa': 10}, f'automatique : {n} — {rep2}')
    up = [c['pos'][2] - ground.top(c['pos'][0], c['pos'][1], c['pos'][2]) for c in out2 if c['kind'] == 'wumpa']
    check(all(abs(u - 42) < 1 for u in up), 'fruits poses a 42 po du sol (origine au centre du fruit, comme a Turbo Track)')
    # pente : sol z = 0,2 x + 0,1 y -> caisses ajoutee et deplacee inclinees (haut = normale du sol), indicateurs
    import math
    import struct
    from decor import DecorFile
    slope = lambda x, y, z: 0.2 * x + 0.1 * y
    want = [dict(c) for c in crates]
    want[0]['pos'] = [want[0]['pos'][0] + 50, want[0]['pos'][1], want[0]['pos'][2]]
    want += [{'kind': 'question', 'pos': [0.0, 0.0, 0.0]}]
    z5, rep5, _ = powerup.write_crates(data, want, height_at=slope)
    df5 = DecorFile(z5.to_bytes())
    ok = []
    for name in (want[0]['name'], 'crate_question_019'):
        o = next(o for o, n in df5.names.items() if n == name)
        a, b, _ = struct.unpack_from('<3f', *df5.igz._loc(df5.igz.deref(o + 0x30) + 0x60))
        upv = (math.cos(a) * math.sin(b), -math.sin(a), math.cos(a) * math.cos(b))
        n = (-0.2, -0.1, 1.0)
        cos = sum(u * v for u, v in zip(upv, n)) / math.sqrt(sum(v * v for v in n))
        ok.append(cos > 0.9999 and df5.igz.u32(o + 0x38) & powerup.TILT_FLAGS == powerup.TILT_FLAGS)
    check(all(ok) and 'inclinee' in rep5, f'pente : caisses inclinees comme le sol ({rep5})')
    flat = lambda x, y, z: 0.01 * x                                 # < 3 deg : a plat
    z6, rep6, _ = powerup.write_crates(data, want, height_at=flat)
    check('inclinee' not in rep6, 'pente faible : caisses laissees a plat')
    print('tous les tests passent')


if __name__ == '__main__':
    main(sys.argv[1])
