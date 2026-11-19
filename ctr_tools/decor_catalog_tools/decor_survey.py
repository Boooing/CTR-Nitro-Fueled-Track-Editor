"""Lecture seule (jeu) : releve de tous les modeles de decor du jeu pour reclasser le decor de la Creation.
Par modele : pistes qui le listent, dimensions (m), triangles, textures (couleur moyenne, saturation, contraste), poids des
fichiers. Resultat : decor_survey.json (repris si interrompu)."""
import os, sys, json, time, colorsys
import numpy as np
ROOT = r'C:\Users\Boooing\Desktop\Nouveau dossier'
sys.path.insert(0, os.path.join(ROOT, 'ctr_tools', 'editor')); sys.path.insert(0, os.path.join(ROOT, 'ctr_tools'))
import pak_tool, pkg_manifest, library, preview
from igz import IgzFile
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'decor_survey.json')
cfg = json.load(open(os.path.join(ROOT, 'ctr_editor_config.json'), encoding='utf-8'))
A = pak_tool.set_layout(cfg['archives'])['archives']
data = json.load(open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {}
# pistes qui listent chaque modele
users = {}
for pak in library.track_paks(A):
    if pak.startswith('t9'):
        continue                                           # pistes creees par l'editeur : copies de Crash Cove
    arc, idx, _ = pak_tool.cached_archive(os.path.join(A, pak))
    man = pkg_manifest.manifest_logical(pak[:-4])
    if man.lower() not in idx:
        continue
    for typ, p in pkg_manifest.entries(pak_tool.read_latest(A, man, pak)[0]):
        if typ == 'model' and p.endswith('.igz') and library.INCLUDE.match(p) and not library.EXCLUDE.search(p):
            users.setdefault(p, []).append(pak)
print(len(users), 'modeles', flush=True)
t0, n = time.time(), 0


def read_any(lg, paks):
    for pk in paks:
        try:
            return pak_tool.read_latest(A, lg, pk)[0]
        except KeyError:
            continue
    src = library.find_pak(A, lg)
    return pak_tool.read_latest(A, lg, src)[0] if src else None


for p, lst in sorted(users.items()):
    if p in data:
        continue
    rec = {'users': lst}
    try:
        d = read_any(p, lst)
        if d is None:
            raise KeyError('introuvable')
        rec['bytes'] = len(d)
        pv = preview.model_preview(d, lambda lg: read_any(lg, lst))
        P = np.nan_to_num(np.asarray(pv['positions'], np.float64)).reshape(-1, 3) / 39.37
        rec['tris'] = int(len(pv['indices']) // 3)
        if len(P):
            rec['r'] = round(float(np.hypot(P[:, 0], P[:, 1]).max()), 2)
            rec['zmin'], rec['zmax'] = round(float(P[:, 2].min()), 2), round(float(P[:, 2].max()), 2)
            rec['wx'], rec['wy'] = round(float(np.ptp(P[:, 0])), 2), round(float(np.ptp(P[:, 1])), 2)
        tex = []
        for _, _, t in pv['groups']:
            if t and t not in tex:
                tex.append(t)
        rec['tex'] = tex[:6]
        stats = []
        for t in tex[:3]:
            try:
                td = read_any(t, lst)
                img = preview.decode_texture(td, 32)
                a = np.asarray(img[0] if isinstance(img, tuple) else img, np.float64)
                if a.ndim == 3 and a.shape[-1] >= 3:
                    rgb = a[..., :3].reshape(-1, 3) / 255.0
                    m = rgb.mean(0)
                    stats.append({'mean': [round(x, 3) for x in m], 'sat': round(colorsys.rgb_to_hsv(*m)[1], 3),
                                  'std': round(float(rgb.std(0).mean()), 3), 'tbytes': len(td)})
            except Exception as e:  # noqa: BLE001
                stats.append({'err': str(e)[:60]})
        rec['tstats'] = stats
    except Exception as e:  # noqa: BLE001
        rec['err'] = repr(e)[:120]
    data[p] = rec
    n += 1
    if n % 100 == 0:
        json.dump(data, open(OUT, 'w', encoding='utf-8'))
        print(n, 'faits', round(time.time() - t0), 's', flush=True)
json.dump(data, open(OUT, 'w', encoding='utf-8'))
print('fini', len(data), round(time.time() - t0), 's')
