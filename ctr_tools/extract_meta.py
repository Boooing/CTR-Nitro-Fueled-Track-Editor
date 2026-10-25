"""Extrait le schema des classes Alchemy (nom, taille, parent, champs) depuis l'eboot.bin decrypte.

Usage : python extract_meta.py <eboot.bin> <sortie.json>

Mecanisme (CTR Nitro-Fueled 1.21) :
  * Chaque classe s'enregistre via REGISTER_CLASS(rdi=&meta_global, rdx=parent_getter, r8=nom, r9d=taille,
    pile: callback_champs ...). parent_getter fait `lea rdi, [&meta_parent]` puis appelle l'enregistrement.
  * Le callback de champs cree N metafields depuis une table de fonctions de creation (`lea rsi, [types]`,
    `mov ecx, N`), puis appelle SET_FIELDS(rdi=meta, rsi=noms[], rdx=stockage[], rcx=offsets_u16[], r8d=base).
  * Chaque fonction de creation fait `lea r14, [&meta_du_metafield]` : on retrouve ainsi le type du champ.
Les adresses des deux fonctions sont trouvees par signature dans le code, sinon par defaut celles de la 1.21.
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pylib'))
import capstone  # noqa: E402
import numpy as np  # noqa: E402

REGISTER_CLASS = 0x15083E0
SET_FIELDS = 0x1507980
ENSURE_REGISTERED = 0x14B22A0


def load_self(path):
    d = open(path, 'rb').read()
    seg_count = struct.unpack_from('<H', d, 0x18)[0]
    segs = [struct.unpack_from('<QQQQ', d, 0x20 + i * 0x20) for i in range(seg_count)]
    eo = 0x20 + seg_count * 0x20
    phoff, = struct.unpack_from('<Q', d, eo + 0x20)
    phnum, = struct.unpack_from('<H', d, eo + 0x38)
    phdrs = [struct.unpack_from('<IIQQQQQQ', d, eo + phoff + i * 0x38) for i in range(phnum)]
    blk = {(fl >> 20) & 0xfff: off for fl, off, c, s in segs if fl & 0x800}
    regions = []
    for i, (pt, pf, off, va, pa, fsz, msz, al) in enumerate(phdrs):
        if pt in (1, 0x61000010) and i in blk:
            regions.append((va, d[blk[i]:blk[i] + fsz]))
    # relative relocations (pointers in data tables are only visible through them)
    dl_i = next(i for i, p in enumerate(phdrs) if p[0] == 0x61000000)
    dl = d[blk[dl_i]:blk[dl_i] + phdrs[dl_i][5]]
    dyn_p = next(p for p in phdrs if p[0] == 2)
    dyn = dl[dyn_p[2] - phdrs[dl_i][2]: dyn_p[2] - phdrs[dl_i][2] + dyn_p[5]]
    tags = {}
    for i in range(0, len(dyn), 16):
        t, v = struct.unpack_from('<qQ', dyn, i)
        tags.setdefault(t, v)
    rel = {}
    for i in range(0, tags[0x61000031], 24):
        off, info, add = struct.unpack_from('<QQq', dl, tags[0x6100002f] + i)
        if info & 0xffffffff == 8:
            rel[off] = add
    return regions, rel


class Image:
    def __init__(self, path):
        self.regions, self.rel = load_self(path)
        self.code = self.regions[0][1]
        self.md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        self.md.detail = True

    def read(self, va, n):
        for rva, b in self.regions:
            if rva <= va < rva + len(b):
                return b[va - rva:va - rva + n]
        return None

    def cstr(self, va):
        b = self.read(va, 256)
        return b.split(b'\0')[0].decode('latin1') if b else None

    def ptr(self, va):
        if va in self.rel:
            return self.rel[va]
        b = self.read(va, 8)
        return struct.unpack('<Q', b)[0] if b else None

    def callers(self, target, with_jmp=False):
        arr = np.frombuffer(self.code, dtype=np.uint8)
        cand = np.nonzero((arr == 0xE8) | ((arr == 0xE9) if with_jmp else False))[0]
        cand = cand[cand + 5 <= len(self.code)]
        b = arr.astype(np.int64)
        disp = b[cand + 1] | (b[cand + 2] << 8) | (b[cand + 3] << 16) | (b[cand + 4] << 24)
        disp = np.where(disp >= 2 ** 31, disp - 2 ** 32, disp)
        return [int(x) for x in cand[cand + 5 + disp == target]]

    def insns(self, start, end):
        return list(self.md.disasm(self.code[start:end], start))

    def regs_before(self, call_va, window=0x80):
        """Track simple register loads (lea rip / mov imm / mov reg,reg) linearly up to call_va."""
        for back in (window, window - 3, window - 1, window - 2, window - 5, window - 7):
            ins = self.insns(call_va - back, call_va + 5)
            if ins and ins[-1].address == call_va:
                break
        else:
            return {}
        regs = {}
        for i in ins[:-1]:
            ops = i.operands
            if i.mnemonic == 'lea' and len(ops) == 2 and ops[1].type == capstone.x86.X86_OP_MEM \
                    and ops[1].mem.base == capstone.x86.X86_REG_RIP:
                regs[i.reg_name(ops[0].reg)] = ('addr', i.address + i.size + ops[1].mem.disp)
            elif i.mnemonic == 'mov' and len(ops) == 2 and ops[0].type == capstone.x86.X86_OP_REG \
                    and ops[1].type == capstone.x86.X86_OP_IMM:
                regs[i.reg_name(ops[0].reg)] = ('imm', ops[1].imm)
            elif i.mnemonic == 'mov' and len(ops) == 2 and ops[0].type == capstone.x86.X86_OP_REG \
                    and ops[1].type == capstone.x86.X86_OP_MEM and ops[1].mem.base == capstone.x86.X86_REG_RIP:
                regs[i.reg_name(ops[0].reg)] = ('load', i.address + i.size + ops[1].mem.disp)
            elif i.mnemonic == 'mov' and len(ops) == 2 and ops[0].type == capstone.x86.X86_OP_REG \
                    and ops[1].type == capstone.x86.X86_OP_REG:
                src = i.reg_name(ops[1].reg)
                if src in regs:
                    regs[i.reg_name(ops[0].reg)] = regs[src]
        return regs

    def ensured_meta(self, fn, limit=0x60):
        """Meta global passed in rdi to the first ENSURE_REGISTERED call inside a creator function."""
        for i in self.insns(fn, fn + limit):
            if i.mnemonic == 'call' and i.operands[0].type == capstone.x86.X86_OP_IMM \
                    and i.operands[0].imm == ENSURE_REGISTERED:
                return reg_val(self.regs_before(i.address, window=i.address - fn), 'rdi')
            if i.mnemonic in ('ret', 'jmp'):
                break
        return None

    def first_lea(self, fn, reg=None, limit=0x40):
        for i in self.insns(fn, fn + limit):
            ops = i.operands
            if i.mnemonic == 'lea' and ops[1].type == capstone.x86.X86_OP_MEM \
                    and ops[1].mem.base == capstone.x86.X86_REG_RIP \
                    and (reg is None or i.reg_name(ops[0].reg) == reg):
                return i.address + i.size + ops[1].mem.disp
            if i.mnemonic == 'ret':
                break
        return None


def reg_val(regs, *names):
    for n in names:
        if n in regs and regs[n][0] in ('addr', 'imm'):
            return regs[n][1]
    return None


def field_refs(img, fn, end):
    """Index du champ -> meta global du type reference (ObjectRef, listes, enums...).

    Motif : `mov r15, [r12 + r14*8 + 8*k]` (k-ieme nouveau champ), `lea rdi, [G]` + ENSURE_REGISTERED,
    puis un appel de configuration du champ avec rdi = r15 et rdx = meta(G).
    """
    refs = {}
    field_regs = {}        # registre -> index du champ qu'il contient
    last_meta = None       # dernier `lea rdi, [G]`
    ensured = None         # meta global du dernier ENSURE_REGISTERED
    rdi_src = None         # registre copie dans rdi avant le prochain call
    for i in img.insns(fn, end + 5):
        ops = i.operands
        reg0 = i.reg_name(ops[0].reg) if ops and ops[0].type == capstone.x86.X86_OP_REG else None
        if i.mnemonic == 'mov' and reg0 and len(ops) == 2 and ops[1].type == capstone.x86.X86_OP_MEM \
                and ops[1].mem.index != 0 and ops[1].mem.scale == 8:
            field_regs[reg0] = ops[1].mem.disp // 8
        elif i.mnemonic == 'lea' and reg0 == 'rdi' and ops[1].mem.base == capstone.x86.X86_REG_RIP:
            last_meta = i.address + i.size + ops[1].mem.disp
            rdi_src = None
        elif i.mnemonic == 'mov' and reg0 == 'rdi' and ops[1].type == capstone.x86.X86_OP_REG:
            rdi_src = i.reg_name(ops[1].reg)
        elif i.mnemonic == 'call' and ops[0].type == capstone.x86.X86_OP_IMM:
            if ops[0].imm == ENSURE_REGISTERED:
                ensured = last_meta
            elif ensured is not None and rdi_src in field_regs:
                refs.setdefault(field_regs[rdi_src], ensured)
                ensured = None
            rdi_src = None
    return refs


def main(eboot, out):
    img = Image(eboot)
    classes = {}          # meta_global -> info
    for call in img.callers(REGISTER_CLASS):
        r = img.regs_before(call)
        glob = reg_val(r, 'rdi')
        name_va = reg_val(r, 'r8')
        if glob is None or name_va is None:
            continue
        classes[glob] = {
            'name': img.cstr(name_va),
            'size': reg_val(r, 'r9d', 'r9'),
            # rcx = &pointeur vers le meta global du parent (REGISTER_CLASS fait `mov rsi, [rcx]`)
            'parent_global': reg_val(r, 'rcx'),
            'field_fn': reg_val(r, 'r11'),
            'register_call': call,
        }
    print(f'{len(classes)} classes enregistrees')

    # field callbacks
    set_calls = {}
    for call in img.callers(SET_FIELDS, with_jmp=True):   # souvent appele en queue (jmp)
        # find enclosing function start (push rbp; mov rbp, rsp)
        fn = img.code.rfind(b'\x55\x48\x89\xe5', 0, call)
        set_calls.setdefault(fn, []).append(call)

    nfields = 0
    for glob, c in classes.items():
        c['fields'] = []
        fn = c['field_fn']
        if not fn or fn not in set_calls:
            continue
        call = set_calls[fn][0]
        r = img.regs_before(call, window=min(0x60, call - fn))
        names_tab, offs_tab = reg_val(r, 'rsi'), reg_val(r, 'rcx')
        # types table + count : first `lea rsi,[x]` / `mov ecx,n` pair in the callback
        types_tab, count = None, None
        for i in img.insns(fn, call):
            ops = i.operands
            if i.mnemonic == 'lea' and len(ops) == 2 and ops[1].type == capstone.x86.X86_OP_MEM \
                    and ops[1].mem.base == capstone.x86.X86_REG_RIP and i.reg_name(ops[0].reg) == 'rsi' \
                    and types_tab is None:
                types_tab = i.address + i.size + ops[1].mem.disp
            if i.mnemonic == 'mov' and len(ops) == 2 and ops[0].type == capstone.x86.X86_OP_REG \
                    and i.reg_name(ops[0].reg) == 'ecx' and ops[1].type == capstone.x86.X86_OP_IMM and count is None:
                count = ops[1].imm
            if types_tab is not None and count is not None:
                break
        if not (names_tab and offs_tab and types_tab and count):
            c['field_error'] = 'pattern'
            continue
        refs = field_refs(img, fn, call)
        for k in range(count):
            nm = img.ptr(names_tab + k * 8)
            off = struct.unpack('<H', img.read(offs_tab + k * 2, 2))[0]
            tfn = img.ptr(types_tab + k * 8)
            tglob = img.ensured_meta(tfn) if tfn else None
            c['fields'].append({'name': img.cstr(nm) if nm else None, 'offset': off,
                                'type_global': tglob, 'ref_global': refs.get(k)})
            nfields += 1
    print(f'{nfields} champs')

    by_glob = {g: c['name'] for g, c in classes.items()}
    result = {}
    for g, c in classes.items():
        result[c['name']] = {
            'size': c['size'],
            'parent': by_glob.get(c['parent_global']),
            'fields': [dict({'name': f['name'], 'offset': f['offset'],
                             'type': by_glob.get(f['type_global'], hex(f['type_global'] or 0))},
                            **({'ref': by_glob[f['ref_global']]}
                               if by_glob.get(f.get('ref_global')) not in (None, 'igDotNetMetaObject') else {}))
                       for f in c['fields']],
        }
        if 'field_error' in c:
            result[c['name']]['field_error'] = c['field_error']
    with open(out, 'w') as f:
        json.dump(result, f, indent=1, sort_keys=True)
    errs = sum(1 for c in classes.values() if 'field_error' in c)
    print(f'ecrit {out} ({errs} callbacks non reconnus)')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
