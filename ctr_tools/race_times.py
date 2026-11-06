"""Temps des reliques et des fantomes du contre-la-montre d'une piste.

  * reliques : maps/octane/<p>/<p>_zoneinfo.igz (update2 / chunkinfos) — CZoneInfo._sapphireTimes / _goldTimes /
    _platinumTimes -> CDifficultySpecificFloat (_easyValue, _mediumValue, _hardValue, _nightmareValue), en secondes.
    (Les champs simples _sapphireTime 240 / _goldTime 180 / _platinumTime 120 sont les memes sur toutes les pistes :
    valeurs par defaut, non touchees.)
  * fantomes (N. Tropy, N. Oxide, Beenox, developpeur) : looseData/GhostData.igz (update2 / permanent) —
    CChallengeGhostData par piste (_levelName, _unlockChallengeGhostsTime = temps a battre pour les faire apparaitre,
    _ghosts -> CChallengeGhostHeaderData : _driverName, _time (999 partout), _ghostFile « data:\\Ghosts\\<...>.igb »).
    Le vrai temps d'un fantome est dans son enregistrement : <jeu>/ghosts/<...>.igb, flottant 19 octets apres le texte
    « ghost_time » (verifie sur les 163 fichiers du jeu). Le fantome rejoue toujours son enregistrement (trajet et
    vitesse de la piste d'origine) : seul le temps annonce / a battre change.
"""
import os
import re
import struct

from igz import IgzFile

TIERS = ('sapphire', 'gold', 'platinum')
DIFFS = ('_easyValue', '_mediumValue', '_hardValue', '_nightmareValue')
GHOST_DATA = 'looseData/GhostData.igz'
GHOST_PAK = 'permanent.pak'
GHOST_KEY = b'ghost_time\x00'
GHOST_TIME_AT = 19                                  # depuis le debut de « ghost_time »
MIN_T, MAX_T = 5.0, 3599.0


def zoneinfo_logical(track):
    return f'maps/octane/{track.lower()}/{track.lower()}_zoneinfo.igz'


def zoneinfo_pak():
    return 'chunkinfos.pak'


def _zone(z):
    return next(o for o, t in z.objects.items() if t == 'CZoneInfo')


def _tier_objects(z):
    zone = _zone(z)
    d = z.dump_object(zone)
    out = {}
    for tier in TIERS:
        ref = d.get(f'_{tier}Times')
        if isinstance(ref, dict) and '@ref' in ref:
            out[tier] = int(ref['@ref'], 16)
    return out


def read_relic(data):
    """{'sapphire': [facile, moyen, difficile, cauchemar], 'gold': [...], 'platinum': [...]} (secondes)."""
    z = IgzFile(data)
    out = {}
    for tier, o in _tier_objects(z).items():
        d = z.dump_object(o)
        out[tier] = [round(float(d[k]), 3) for k in DIFFS]
    return out


def _clean(v):
    v = float(v)
    if not MIN_T <= v <= MAX_T:
        raise ValueError(f'temps hors limites : {v} s ({MIN_T:g} a {MAX_T:g} s)')
    return v


def write_relic(data, relic):
    """Temps des reliques remplaces (seulement les paliers donnes ; listes de 4 valeurs)."""
    if not relic:
        return data
    z = IgzFile(data)
    objs = _tier_objects(z)
    for tier, vals in relic.items():
        if tier not in objs or vals is None:
            continue
        if len(vals) != 4:
            raise ValueError(f'{tier} : 4 valeurs attendues')
        for k, v in zip(DIFFS, vals):
            z.set_field(objs[tier], k, _clean(v))
    return z.to_bytes()


# -- fantomes -------------------------------------------------------------------------------
def _level_key(name):
    return (name or '').replace('\\', '/').rsplit('/', 1)[-1].lower()


def _challenges(z):
    """{piste en minuscules: (offset CChallengeGhostData, [offsets CChallengeGhostHeaderData])}."""
    out = {}
    for o, t in z.objects.items():
        if t != 'CChallengeGhostData':
            continue
        d = z.dump_object(o)
        ghosts = []
        ref = d.get('_ghosts')
        if isinstance(ref, dict) and '@ref' in ref:
            ghosts = [int(i['@ref'], 16) for i in z.dump_object(int(ref['@ref'], 16)).get('@items', []) if i]
        out.setdefault(_level_key(d.get('_levelName')), (o, ghosts))
    return out


def ghost_file_name(path):
    return (path or '').replace('\\', '/').rsplit('/', 1)[-1]


def igb_time(b):
    k = b.find(GHOST_KEY)
    if k < 0 or k > 4096:
        return None
    return struct.unpack_from('<f', b, k + GHOST_TIME_AT)[0]


def igb_with_time(b, t):
    k = b.find(GHOST_KEY)
    if k < 0 or k > 4096:
        raise ValueError('enregistrement de fantome sans « ghost_time »')
    out = bytearray(b)
    struct.pack_into('<f', out, k + GHOST_TIME_AT, _clean(t))
    return bytes(out)


def name_time(fname):
    m = re.search(r'-([\d.]+)-\.igb$', fname or '')
    return float(m.group(1)) if m else None


def read_ghosts(data, track, ghost_dir=None):
    """{'unlock': s, 'ghosts': [{'driver', 'file', 'time'}]} de la piste, ou None si elle n'a pas de fantomes.
    time = temps de l'enregistrement (fichier dans ghost_dir s'il existe, sinon celui du nom du fichier)."""
    z = IgzFile(data)
    c = _challenges(z).get(track.lower())
    if not c:
        return None
    o, ghosts = c
    out = {'unlock': round(float(z.dump_object(o)['_unlockChallengeGhostsTime']), 3), 'ghosts': []}
    for g in ghosts:
        d = z.dump_object(g)
        f = ghost_file_name(d.get('_ghostFile'))
        t = None
        if ghost_dir and f and os.path.exists(os.path.join(ghost_dir, f)):
            t = igb_time(open(os.path.join(ghost_dir, f), 'rb').read(4096))
        if t is None:
            t = name_time(f)
        out['ghosts'].append({'driver': d.get('_driverName') or '', 'file': f, 'time': round(float(t), 3) if t else None})
    return out


def write_ghosts(data, settings):
    """settings {piste: {'unlock': s, 'times': [s ou None, ...]}} : temps de deblocage + _time des fantomes."""
    z = IgzFile(data)
    ch = _challenges(z)
    changed = False
    for track, st in settings.items():
        c = ch.get(track.lower())
        if not c or not st:
            continue
        o, ghosts = c
        if st.get('unlock') is not None:
            z.set_field(o, '_unlockChallengeGhostsTime', _clean(st['unlock']))
            changed = True
        for g, t in zip(ghosts, st.get('times') or []):
            if t is not None:
                z.set_field(g, '_time', _clean(t))
                changed = True
    return z.to_bytes() if changed else data
