"""Formes de piste pour la piste aleatoire de la Creation (creator.js RND_GAME_SHAPES), tirees des pistes du jeu.

Lit le trace de course ORIGINAL de chaque piste du jeu (splines de position, comme la mini-carte), vu de dessus :
48 points regulierement espaces, centres, taille 1 (plus grande dimension), et le nombre d'endroits ou la piste se
croise elle-meme (0 ou 1 gardes par la piste aleatoire : 1 croisement = pont, comme la forme en 8). Ecrit la liste
dans creator.js (entre RND_GAME_SHAPES:BEGIN / END). Les sauvegardes de l'editeur sont ignorees (dossier de sortie
temporaire). Lecture seule du jeu.

python ctr_tools/editor/make_rnd_shapes.py [dossier archives]
"""
import json
import math
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE)]
import server  # noqa: E402

N = 48


def resample(path, n):
    pts = [(float(p[0]), float(p[1])) for p in path]
    if math.dist(pts[0], pts[-1]) > 1e-6:
        pts.append(pts[0])
    seg = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    total = sum(seg)
    out, acc, k = [], 0.0, 0
    for i in range(n):
        want = total * i / n
        while k < len(seg) - 1 and acc + seg[k] < want:
            acc += seg[k]
            k += 1
        u = (want - acc) / seg[k] if seg[k] else 0.0
        a, b = pts[k], pts[k + 1]
        out.append((a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u))
    return out, total


def crossings(pts):
    """Croisements du polygone ferme (segments non voisins qui se coupent)."""
    n, c = len(pts), 0
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        for j in range(i + 2, n):
            if (j + 1) % n == i:
                continue
            c2, d = pts[j], pts[(j + 1) % n]
            if cross(a, b, c2) * cross(a, b, d) < 0 and cross(c2, d, a) * cross(c2, d, b) < 0:
                c += 1
    return c


def race_outline(track):
    """Trace de course sans aller-retour : les splines de position se chevauchent (~90 m) aux transitions -> chaque
    section coupee au point le plus proche du debut de la suivante (comme la visite virtuelle, index.html)."""
    tr = server.load_track(track)
    secs = [[(float(p[0]), float(p[1])) for p in s['control_points']] for _, s in server.race_chain(tr)]
    if not secs:
        secs = [[(float(p[0]), float(p[1])) for p in s['control_points']] for s in tr['splines'] if s['kind'] == 'position_paths']
    out = []
    for i, sec in enumerate(secs):
        if len(secs) > 1 and len(sec) > 2:
            nxt = secs[(i + 1) % len(secs)][0]
            cut = min(range(1, len(sec)), key=lambda k: math.dist(sec[k], nxt))
            sec = sec[:cut + 1]
        out += sec
    return out


def main(argv):
    archives = argv[1] if len(argv) > 1 else server.load_config().get('archives')
    server.configure(archives=archives, out_dir=tempfile.mkdtemp(prefix='rndshapes_'))
    shapes = []
    for track in server.list_tracks():
        if not track[1:2].isdigit() or track.startswith('T9'):
            continue
        try:
            path = race_outline(track)
        except Exception as e:  # noqa: BLE001
            print(f'{track} : illisible ({e})')
            continue
        if len(path) < 20:
            print(f'{track} : pas de trace de course')
            continue
        pts, total = resample(path, N)
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        size = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
        norm = [[round((x - cx) / size, 4), round((y - cy) / size, 4)] for x, y in pts]
        c = crossings(norm)
        shapes.append({'track': track, 'cross': c, 'len_m': round(total / 39.37), 'pts': norm})
        print(f'{track} : {round(total / 39.37)} m, {c} croisement(s)')
    # dans creator.js, entre les reperes (pas de fichier de plus a servir ni a empaqueter dans l'exe / l'AppImage)
    keep = [s for s in shapes if s['cross'] <= 1]
    rows = ',\n'.join("    { t: '%s', c: %d, p: [%s] }" % (s['track'].split('_', 1)[1].replace('_', ' '), s['cross'],
                                                        ','.join('%.3f' % v for p in s['pts'] for v in p)) for s in keep)
    block = ('  // RND_GAME_SHAPES:BEGIN (ecrit par editor/make_rnd_shapes.py : traces des pistes du jeu vus de dessus, 48 points,\n'
             '  // taille 1, c = croisements de la piste avec elle-meme ; ne pas modifier a la main)\n'
             '  const RND_GAME_SHAPES = [\n' + rows + '\n  ];\n  // RND_GAME_SHAPES:END')
    cj = os.path.join(HERE, 'creator.js')
    src = open(cj, encoding='utf-8').read()
    a, b = src.find('  // RND_GAME_SHAPES:BEGIN'), src.find('// RND_GAME_SHAPES:END')
    if a < 0 or b < 0:
        raise SystemExit('reperes RND_GAME_SHAPES absents de creator.js')
    src = src[:a] + block + src[b + len('// RND_GAME_SHAPES:END'):]
    open(cj, 'w', encoding='utf-8', newline='\n').write(src)
    print(f'{len(keep)} formes (0 ou 1 croisement) sur {len(shapes)} -> creator.js')


if __name__ == '__main__':
    main(sys.argv)
