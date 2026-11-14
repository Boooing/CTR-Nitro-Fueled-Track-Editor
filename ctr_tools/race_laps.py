"""Choix du nombre de tours du menu « Reglages de course » (2026-11-14).

ui/octane_mainmenu_racesetting.igz : CGuiBehaviorRaceLapSelector, champ a +0x1C0 (absent du schema) -> igIntList des
tours proposes, [3, 5, 7] dans le jeu. Le mod Nurburgring (CTRNFModding, nurburgring-track-0111.zip) la remplace par
[1, 2, 3, 5, 7] : meme fichier, liste agrandie (nouveau bloc en fin de section, l'ancien laisse en place). Reglage
commun a TOUTES les pistes (rien par piste dans le jeu). Le fichier va dans update3.pak avec le menu (custom_category).
"""
import struct
import sys

import igz

RACESETTING = 'ui/octane_mainmenu_racesetting.igz'
GAME_LAPS = [3, 5, 7]
SHORT_LAPS = [1, 2, 3, 5, 7]
SELECTOR = 'CGuiBehaviorRaceLapSelector'
LIST_FIELD = 0x1C0


def _lap_list(z):
    sel = next(o for o, t in z.objects.items() if t == SELECTOR)
    lst = z.deref(sel + LIST_FIELD)
    if lst is None or z.objects.get(lst) != 'igIntList':
        raise ValueError('liste des tours introuvable dans ' + RACESETTING)
    return lst


def read_laps(data):
    z = igz.IgzFile(data)
    count, _, at = z.list_info(_lap_list(z))
    return list(struct.unpack_from(f'<{count}i', *z._loc(at))) if at is not None else []


def set_laps(data, laps):
    """Fichier d'origine -> meme fichier avec ces choix de tours (entiers de 1 a 99, dans l'ordre du menu)."""
    laps = [int(v) for v in laps]
    if not laps or any(not 1 <= v <= 99 for v in laps):
        raise ValueError('tours : entre 1 et 99')
    z = igz.IgzFile(data)
    lst = _lap_list(z)
    new = z.alloc(4 * len(laps), 16)
    struct.pack_into(f'<{len(laps)}i', *z._loc(new), *laps)
    struct.pack_into('<II', *z._loc(lst + 0x0C), len(laps), len(laps))
    flags = z.u32(lst + 0x1C)
    struct.pack_into('<II', *z._loc(lst + 0x18), 4 * len(laps), flags)
    z.set_ptr(lst + 0x20, new)
    return z.to_bytes()


if __name__ == '__main__':
    src = open(sys.argv[1], 'rb').read()
    print('tours :', read_laps(src))
    if len(sys.argv) > 2:
        open(sys.argv[2], 'wb').write(set_laps(src, SHORT_LAPS))
