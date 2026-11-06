"""Types de sol a reglages propres (2026-11-06) : un type de sol du jeu (neige, herbe, sable...) garde son son et ses
effets, mais avec une vitesse et une glissade choisies.

Les reglages d'un type de sol sont globaux (LooseData/CollisionMaterials.igz, liste CCollisionMaterialHandleList :
valeur de surface d'un triangle de collision = rang dans la liste + decalage, cale sur Sand = 38). On n'y change rien
d'existant : chaque combinaison (type de base, vitesse, glissade) devient un NOUVEAU materiau, copie du materiau de base
et de sa fiche de surface (CCollisionMaterialSurfaceInfo), ajoute en fin de liste -> nouvelle valeur de surface.

  * vitesse  -> fiche._speedMultiplier (1 = normal ; herbe lente du jeu 0,34 / 0,49, boue 0,5) ;
  * glissade -> 0 = adherence du sol de base, 1 = glace : frottement du materiau (_dynamicFriction / _staticFriction,
    0,5 -> 0,05 comme Ice), fiche._slipperyFactorAcceleration (0 -> 650 comme IceSurface) et drapeaux de surface de la
    glace (0x22) au-dela de la moitie.
NON VALIDE EN JEU (le ralentissement de l'herbe du jeu ne vient pas de cette fiche : constate 0,4 en jeu, fiche 1,0).
"""
import struct

from igz import IgzFile

LOGICAL = 'LooseData/CollisionMaterials.igz'
PAK = 'permanent.pak'
PREFIX = 'CTRMod_Surface'
ICE_FRICTION, BASE_FRICTION = 0.05, 0.5
ICE_SLIP_ACC = 650.0
ICE_FLAGS = 0x22


def _list(z):
    roots = {n: o for n, o in z.root_objects() if n}
    hl = next(o for o, t in z.objects.items() if t == 'CCollisionMaterialHandleList')
    items = z.dump_object(hl)['@items']
    names = [str(it.get('@handle')).split('::')[-1] if isinstance(it, dict) else None for it in items]
    off = 38 - names.index('Sand') if 'Sand' in names else 4
    return roots, hl, names, off


def first_value(data):
    """Valeur de surface du 1er type ajoute (apres ceux du jeu)."""
    z = IgzFile(data)
    _, _, names, off = _list(z)
    return len(names) + off


def base_params(data, value):
    """{'speed', 'slide'} d'un type de sol du jeu (valeur de surface) ; None s'il n'a pas de materiau."""
    z = IgzFile(data)
    roots, _, names, off = _list(z)
    i = value - off
    if not 0 <= i < len(names) or roots.get(names[i]) is None:
        return None
    m = z.dump_object(roots[names[i]])
    si = m.get('_surfaceInfo')
    sn = si['@handle'].split('::')[-1] if isinstance(si, dict) and '@handle' in si else None
    s = z.dump_object(roots[sn]) if sn in roots else {}
    fr = m.get('_dynamicFriction') if isinstance(m.get('_dynamicFriction'), (int, float)) else BASE_FRICTION
    slide = max(0.0, min(1.0, (BASE_FRICTION - fr) / (BASE_FRICTION - ICE_FRICTION)))
    return {'speed': float(s.get('_speedMultiplier') or 1.0), 'slide': round(slide, 3)}


def build(data, customs):
    """CollisionMaterials.igz avec les types ajoutes : customs = [{'base': valeur, 'speed', 'slide'}] dans l'ordre
    (valeur du k-ieme = first_value + k). -> octets."""
    z = IgzFile(data)
    src = IgzFile(data)                                   # modele des copies (offsets d'origine)
    roots, hl, names, off = _list(z)
    sroots = {n: o for n, o in src.root_objects() if n}
    count, _, old = z.list_info(hl)
    raw = [z.u64(old + i * 8) for i in range(count)]
    marked = [z.is_handle(old + i * 8) for i in range(count)]
    ns = None
    new_names = []
    for k, c in enumerate(customs):
        i = int(c['base']) - off
        if not 0 <= i < len(names) or sroots.get(names[i]) is None:
            raise ValueError(f'type de sol de base inconnu : {c["base"]}')
        mat_src = sroots[names[i]]
        md = src.dump_object(mat_src)
        h = src.named_handle(src.u32(src.find_field(mat_src, '_surfaceInfo')[0]))
        if h is None or h[0] not in sroots:
            raise ValueError(f'fiche de surface introuvable pour {names[i]}')
        sinfo_name, ns = h
        mname, sname = f'{PREFIX}{k:02d}', f'{PREFIX}{k:02d}_surfaceInfo'
        so = z.import_entity(src, sroots[sinfo_name], sname)
        mo = z.import_entity(src, mat_src, mname)
        slide = max(0.0, min(1.0, float(c.get('slide', 0.0))))
        speed = max(0.05, min(3.0, float(c.get('speed', 1.0))))
        z.set_field(so, '_speedMultiplier', speed)
        base_fr = md.get('_dynamicFriction') if isinstance(md.get('_dynamicFriction'), (int, float)) else BASE_FRICTION
        fr = base_fr + (ICE_FRICTION - base_fr) * slide
        z.set_field(mo, '_dynamicFriction', fr)
        z.set_field(mo, '_staticFriction', fr)
        z.set_field(so, '_slipperyFactorAcceleration', ICE_SLIP_ACC * slide)
        if slide >= 0.5:
            fo, _ = z.find_field(so, '_surfaceFlags')            # entier 16 bits (set_field ne l'ecrit pas)
            struct.pack_into('<H', *z._loc(fo), z.u32(fo) & 0xFFFF | ICE_FLAGS)
        # nom du materiau (chaine) et fiche : celles de la copie
        z.set_string_ref(z.find_field(mo, '_name')[0], mname)
        fo = z.find_field(mo, '_surfaceInfo')[0]
        struct.pack_into('<Q', *z._loc(fo), 0x80000000 | z.ext_index(sname, ns))
        new_names.append(mname)
    if not new_names:
        return bytes(data)
    # liste des materiaux : anciennes entrees telles quelles (valeurs brutes), puis les nouvelles
    new = z.alloc((count + len(new_names)) * 8, 16)
    for i in range(count):
        struct.pack_into('<Q', *z._loc(new + i * 8), raw[i])
        if marked[i]:
            z._mark('RHND', new + i * 8)
    for j, n in enumerate(new_names):
        p = new + (count + j) * 8
        struct.pack_into('<Q', *z._loc(p), 0x80000000 | z.ext_index(n, ns))
        z._mark('RHND', p)
    for i in range(count):
        z._mark('RHND', old + i * 8, False)
    total = count + len(new_names)
    struct.pack_into('<II', *z._loc(hl + 0x0C), total, total)
    flags = z.u32(hl + 0x1C)
    struct.pack_into('<II', *z._loc(hl + 0x18), total * 8, flags)
    z.set_ptr(hl + 0x20, new)
    return z.to_bytes()


def read_customs(data):
    """[(valeur, nom, speed, slide)] des types ajoutes presents dans un fichier (verification)."""
    z = IgzFile(data)
    roots, _, names, off = _list(z)
    out = []
    for i, n in enumerate(names):
        if n and n.startswith(PREFIX):
            m = z.dump_object(roots[n])
            sn = z.named_handle(z.u32(z.find_field(roots[n], '_surfaceInfo')[0]))
            s = z.dump_object(roots[sn[0]]) if sn and sn[0] in roots else {}
            out.append((i + off, n, s.get('_speedMultiplier'), m.get('_dynamicFriction'), s.get('_slipperyFactorAcceleration')))
    return out
