"""Lecture seule : couleur moyenne / saturation / contraste des textures de chaque modele releve (decor_survey.json)."""
import os, sys, json, colorsys, time
import numpy as np
ROOT = r'C:\Users\Boooing\Desktop\Nouveau dossier'
sys.path.insert(0, os.path.join(ROOT, 'ctr_tools', 'editor')); sys.path.insert(0, os.path.join(ROOT, 'ctr_tools'))
import pak_tool, library, preview
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'decor_survey.json')
cfg = json.load(open(os.path.join(ROOT, 'ctr_editor_config.json'), encoding='utf-8'))
A = pak_tool.set_layout(cfg['archives'])['archives']
data = json.load(open(OUT, encoding='utf-8'))
cache = {}


def read_any(lg, paks):
    for pk in list(paks) + list(library.COMMON_ARCHIVES):
        try:
            return pak_tool.read_latest(A, lg, pk)[0]
        except KeyError:
            continue
    src = library.find_pak(A, lg)
    return pak_tool.read_latest(A, lg, src)[0] if src else None


t0 = time.time()
for p, rec in data.items():
    out = []
    for t in (rec.get('tex') or [])[:3]:
        name = t[0] if isinstance(t, (list, tuple)) else t
        lg = 'textures/' + name + '.igz'
        if lg not in cache:
            try:
                td = read_any(lg, rec['users'])
                rgba, alpha = preview.decode_texture(td, 32)
                rgb = rgba[..., :3].reshape(-1, 3) / 255.0
                m = rgb.mean(0)
                cache[lg] = {'mean': [round(float(x), 3) for x in m], 'sat': round(colorsys.rgb_to_hsv(*m)[1], 3),
                             'std': round(float(rgb.std(0).mean()), 3), 'alpha': alpha, 'tbytes': len(td)}
            except Exception as e:  # noqa: BLE001
                cache[lg] = {'err': str(e)[:60]}
        out.append(cache[lg])
    rec['tstats'] = out
json.dump(data, open(OUT, 'w', encoding='utf-8'))
ok = sum(1 for r in data.values() if r['tstats'] and 'mean' in r['tstats'][0])
print('textures', len(cache), 'modeles avec stats', ok, round(time.time() - t0), 's')
