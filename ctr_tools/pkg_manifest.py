"""Manifeste de streaming d'une piste (packages/generated/maps/.../<Piste>_pkg.igz).

Un igStreamingChunkInfo dont le vecteur `_required` liste des paires (type, chemin) : le jeu ne charge
que les fichiers listés. Un modèle ajouté à l'archive mais absent d'ici n'est jamais chargé (invisible),
alors que la collision, elle, vient du .hkx de la piste déjà chargé.
"""
import struct
from igz import IgzFile

ENTRY = 16          # (chaine type u64, chaine chemin u64)


def manifest_logical(track):
    return f'packages/generated/maps/Octane/{track}/{track}_pkg.igz'


def _chunk(z):
    off = next(o for o, t in z.objects.items() if t == 'igStreamingChunkInfo')
    return off + 40       # champ _required (igVector : compte u64, memref {taille|flags, ptr})


def entries(data):
    z = IgzFile(data)
    vec = _chunk(z)
    count, base = z.u32(vec), z.deref(vec + 0x10)
    return [(z.string(z.u64(base + i * ENTRY)), z.string(z.u64(base + i * ENTRY + 8))) for i in range(count)]


def add_entries(data, new):
    """Ajoute les paires (type, chemin) absentes ; chacune après la dernière entrée de même type.

    Retourne (octets, liste des paires réellement ajoutées). Les chemins sont mis en minuscules comme ceux du jeu.
    """
    z = IgzFile(data)
    vec = _chunk(z)
    rows = entries(data)
    have = {p for _, p in rows}
    added = []
    for typ, path in new:
        path = path.lower()
        if path in have:
            continue
        last = max((i for i, (t, _) in enumerate(rows) if t == typ), default=len(rows) - 1)
        rows.insert(last + 1, (typ, path))
        have.add(path)
        added.append((typ, path))
    if not added:
        return data, []
    count, old = z.u32(vec), z.deref(vec + 0x10)
    for i in range(count * 2):
        z._mark('RSTT', old + i * 8, False)
    base = z.alloc(len(rows) * ENTRY, 16)
    for i, (typ, path) in enumerate(rows):
        z.set_string_ref(base + i * ENTRY, typ)
        z.set_string_ref(base + i * ENTRY + 8, path)
    struct.pack_into('<I', *z._loc(vec), len(rows))
    flags = z.u32(vec + 0x0C)
    struct.pack_into('<II', *z._loc(vec + 0x08), len(rows) * ENTRY, flags)
    z.set_ptr(vec + 0x10, base)
    return z.to_bytes(), added
