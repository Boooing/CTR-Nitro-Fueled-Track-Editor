"""Musique de piste : fichiers .snd du jeu (sound_streams/wavs/Music/mus_*.snd).

Format : conteneur FMOD FSB5 version 1, un seul son, codec 11 (MPEG), 48 kHz, en general 10 canaux = 5 flux MP3 stereo
CBR 128 kb/s entrelaces trame par trame (384 o par trame, sans bourrage). En course, le jeu ne fait entendre que le
flux 0 (essai en jeu sur Crash Cove : les voix des flux 1 a 4 jamais entendues) ; la musique importee va donc sur le
flux 0, les autres flux restent presents et silencieux. Le jeu accepte une duree differente de l'originale : la banque
MUS ne reference le fichier que par son nom.

Boucle sans blanc : un MP3 decode est decale (LAME + decodeur : 1105 echantillons) et chaque trame depend de la
precedente. L'audio est donc encode en boucle (fin du morceau recopiee avant le debut), les 2 premieres trames sont
retirees et le reservoir de bits est coupe : la derniere trame enchaine sur la premiere comme a l'interieur du morceau.

Encodage et decodage : ffmpeg (a cote de l'exe, sinon dans le PATH), avec libmp3lame.
"""
import os
import shutil
import struct
import subprocess
import sys

import numpy as np

from igz import IgzFile
import track_clone

CODEC_MPEG = 11
FRAME_SAMPLES = 1152
FRAME_BYTES = 384                # 128 kb/s a 48 kHz
RATE = 48000
DELAY = 1105                     # decalage LAME + decodeur (echantillons)
SKIP_FRAMES = 2                  # trames retirees au debut (elles ne portent que la recopie de la fin du morceau)
MIN_SECONDS, MAX_SECONDS = 10, 20 * 60
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


# Musique continue au dernier tour : le changement de morceau est decide par un script commun a toutes les pistes
# (vsc/common/Race/common_Race_Music_Manager.igz) : son reglage FINAL_LAP_SETTINGS joue le jingle (_stinger1) et bascule
# du flux normal au flux du dernier tour (_flipStreams). La piste recoit sa copie, sous un nom de meme longueur, ou ce
# reglage ne bascule plus ; sa carte et son manifeste la designent. Modifier la carte seule ne suffit pas : son
# _combatStream vise le morceau du dernier tour ; le mettre egal a _traversalStream empeche la musique de demarrer, le
# vider donne le silence au dernier tour.
MANAGER = 'common_Race_Music_Manager'
CONTINUE = 'common_Race_Music_Continu'
MANAGER_SCRIPT = f'vsc/common/Race/{MANAGER}.igz'
CONTINUE_SCRIPT = f'vsc/common/Race/{CONTINUE}.igz'
FINAL_LAP_SETTINGS = 'Game_Sound_Music_Settings_id_qw2pev6x_metaField_default'


def _continue_rename(script, *others):
    ren = track_clone.Renamer(MANAGER, CONTINUE)
    tokens = {MANAGER, MANAGER + 'Data'}
    for d in (script,) + others:
        tokens |= {s for s in IgzFile(d).strings if ren.rx.search(s.encode('latin1'))}
    return ren, tokens, track_clone._hash_table(tokens, ren)


def continue_script(script):
    """Copie du script de musique : le dernier tour joue son jingle mais ne bascule plus sur l'autre flux."""
    ren, tokens, table = _continue_rename(script)
    new, _ = track_clone.transform_igz(script, ren, table, tokens)
    new, _ = track_clone.rehash_tables(new, script)
    z = IgzFile(new)
    settings = next((o for n, o in z.root_objects() if n == FINAL_LAP_SETTINGS), None)
    if settings is None or z.objects.get(settings) != 'CGameSoundMusicSettings':
        raise ValueError('script de musique inattendu : dernier tour introuvable')
    off = settings + next(f for f, (n, _) in z.fields_of('CGameSoundMusicSettings').items() if n == '_flipStreams')
    buf, p = z._loc(off)
    if buf[p] != 1:
        raise ValueError('script de musique inattendu : pas de bascule au dernier tour')
    buf[p] = 0
    return z.to_bytes()


def continue_map(data, script):
    """Carte de la piste : le script de musique est remplace par sa copie."""
    if MANAGER.encode() not in data:
        raise ValueError('cette piste n\'utilise pas le script de musique habituel')
    ren, tokens, table = _continue_rename(script, data)
    new, _ = track_clone.transform_igz(data, ren, table, tokens)
    return track_clone.rehash_tables(new, data)[0]


FFMPEG_PATH = None                  # chemin choisi par l'utilisateur (reglage 'ffmpeg' de l'editeur), prioritaire


def ffmpeg_in(folder):
    """ffmpeg du dossier donne, ou de son sous-dossier bin (archives ffmpeg pour Windows) ; un chemin vers l'exe lui-meme
    est accepte. None si absent."""
    folder = (folder or '').strip().strip('"')
    if os.path.isfile(folder):
        return folder if os.path.basename(folder).lower() in ('ffmpeg', 'ffmpeg.exe') else None
    for d in (folder, os.path.join(folder, 'bin')):
        for name in ('ffmpeg.exe', 'ffmpeg'):
            p = os.path.join(d, name)
            if folder and os.path.isfile(p):
                return p
    return None


def check_ffmpeg(exe):
    """Le programme se lance et sait encoder en MP3 (libmp3lame, seul encodeur utilise) ; ValueError sinon."""
    try:
        r = subprocess.run([exe, '-hide_banner', '-encoders'], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        raise ValueError(f'ffmpeg ne se lance pas : {e}') from e
    if r.returncode != 0:
        raise ValueError(f'ffmpeg ne se lance pas (code {r.returncode})')
    if b'libmp3lame' not in r.stdout:
        raise ValueError('cette version de ffmpeg ne sait pas encoder en MP3 (libmp3lame absent)')
    return exe


def find_ffmpeg():
    """Choisi par l'utilisateur, sinon a cote de l'exe, sinon dans le PATH de l'ordinateur ; None si introuvable."""
    if FFMPEG_PATH and os.path.isfile(FFMPEG_PATH):
        return FFMPEG_PATH
    here = [os.path.dirname(sys.executable)] if getattr(sys, 'frozen', False) else []
    for d in here + [getattr(sys, '_MEIPASS', '')]:
        for name in ('ffmpeg.exe', 'ffmpeg'):
            p = os.path.join(d, name) if d else ''
            if p and os.path.isfile(p):
                return p
    return shutil.which('ffmpeg')


def _ffmpeg():
    exe = find_ffmpeg()
    if not exe:
        raise RuntimeError('ffmpeg introuvable : indique où il se trouve dans Piste › Musique de la piste (ou installe-le) pour importer une musique')
    return exe


def read_header(data):
    """-> {channels, streams, samples, seconds, data_start, data_size}. Refuse ce qui n'est pas du MPEG."""
    if data[:4] != b'FSB5':
        raise ValueError('ce fichier de musique n\'est pas au format FSB5')
    ver, count, sh, nm, size, mode = struct.unpack_from('<6I', data, 4)
    if ver != 1 or count != 1 or mode != CODEC_MPEG:
        raise ValueError(f'musique non prise en charge (version {ver}, {count} son(s), codec {mode})')
    v = struct.unpack_from('<Q', data, 60)[0]
    ch = {0: 1, 1: 2, 2: 6, 3: 8}[(v >> 5) & 3]
    o, more = 68, v & 1
    while more:                                          # blocs optionnels : type 1 = nombre de canaux
        c = struct.unpack_from('<I', data, o)[0]
        more, length, typ = c & 1, (c >> 1) & 0xFFFFFF, c >> 25
        if typ == 1:
            ch = data[o + 4]
        o += 4 + length
    if ch % 2:
        raise ValueError(f'musique non prise en charge ({ch} canaux)')
    start = 60 + sh + nm
    return {'channels': ch, 'streams': ch // 2, 'samples': v >> 34, 'seconds': (v >> 34) / RATE,
            'data_start': start, 'data_size': size}


def _sound_name(data):
    """Nom du son dans la table de noms de l'original."""
    sh, nm = struct.unpack_from('<2I', data, 12)
    table = data[60 + sh:60 + sh + nm]
    off = struct.unpack_from('<I', table, 0)[0] if len(table) >= 4 else 0
    return table[off:].split(b'\0', 1)[0] if off < len(table) else b'music'


def wrap(original, frames):
    """Conteneur FSB5 : en-tete deduit de l'original (nom, reglages) ; frames = liste de flux (listes de trames),
    autant que l'original. L'en-tete est refait : certains originaux ont des blocs lies a leur contenu."""
    info = read_header(original)
    if len(frames) != info['streams'] or len({len(s) for s in frames}) != 1:
        raise ValueError('flux de musique incoherents')
    n = len(frames[0])
    body = b''.join(s[k] for k in range(n) for s in frames)
    name = _sound_name(original)
    sample_hdr_tail = struct.pack('<IB', 1 << 25 | 1 << 1, info['channels'])
    table = struct.pack('<I', 4) + name + b'\0'
    table += b'\0' * (-(60 + 8 + len(sample_hdr_tail) + len(table)) % 32)
    head = bytearray(original[:60])
    struct.pack_into('<6I', head, 4, 1, 1, 8 + len(sample_hdr_tail), len(table), len(body), CODEC_MPEG)
    low = struct.unpack_from('<Q', original, 60)[0] & 0x1E                 # indice de frequence d'origine
    sample = low | 1 | (n * FRAME_SAMPLES) << 34                           # bloc suivant : canaux ; donnees a l'offset 0
    return bytes(head) + struct.pack('<Q', sample) + sample_hdr_tail + table + body


def split_frames(data):
    """Trames de chaque flux d'un .snd."""
    info = read_header(data)
    s, o, end, out = info['streams'], info['data_start'], info['data_start'] + info['data_size'], []
    while o + 4 <= end:
        if data[o] != 0xFF or data[o + 1] & 0xE0 != 0xE0:
            raise ValueError(f'trame MPEG invalide à l\'octet {o}')
        size = _frame_size(data, o)
        out.append(data[o:o + size])
        o += size
    return [out[i::s] for i in range(s)]


BITRATES = {1: 32, 2: 40, 3: 48, 4: 56, 5: 64, 6: 80, 7: 96, 8: 112, 9: 128, 10: 160, 11: 192, 12: 224, 13: 256, 14: 320}


def _frame_size(d, o):
    br = BITRATES.get(d[o + 2] >> 4)
    if not br or (d[o + 2] >> 2) & 3 != 1:
        raise ValueError(f'trame MPEG inattendue à l\'octet {o}')
    return 144000 * br // RATE + ((d[o + 2] >> 1) & 1)


def stream_mp3(data, index=0):
    """Flux en fichier MP3 (ecoute dans la page, verification)."""
    return b''.join(split_frames(data)[index])


def decode(path, tempo=1.0, normalize=True):
    """Fichier audio quelconque -> PCM flottant stereo 48 kHz (n, 2)."""
    filters = []
    if abs(tempo - 1) > 1e-3:
        filters.append(f'atempo={tempo:.3f}')
    if normalize:                                        # niveau proche de la musique d'origine
        filters.append('loudnorm=I=-16:TP=-1.5:LRA=11')
    filters.append(f'aresample={RATE}')
    r = subprocess.run([_ffmpeg(), '-v', 'error', '-nostdin', '-i', path, '-vn', '-af', ','.join(filters), '-ac', '2', '-ar', str(RATE),
                        '-f', 'f32le', '-'], capture_output=True, creationflags=FLAGS)
    if r.returncode or not r.stdout:
        msg = r.stderr.decode('utf-8', 'replace').strip().splitlines()
        raise ValueError('fichier audio illisible' + (f' ({msg[-1][:160]})' if msg else ''))
    return np.frombuffer(r.stdout, '<f4').reshape(-1, 2).copy()


def _encode(pcm):
    """PCM flottant -> trames MP3 CBR 128 kb/s, sans etiquette ni reservoir de bits."""
    raw = (np.clip(pcm, -1, 1) * 32767).astype('<i2').tobytes()
    r = subprocess.run([_ffmpeg(), '-v', 'error', '-nostdin', '-f', 's16le', '-ar', str(RATE), '-ac', '2', '-i', '-', '-c:a', 'libmp3lame',
                        '-b:a', '128k', '-abr', '0', '-joint_stereo', '1', '-reservoir', '0', '-write_xing', '0', '-id3v2_version', '0',
                        '-f', 'mp3', '-'], input=raw, capture_output=True, creationflags=FLAGS)
    if r.returncode:
        raise RuntimeError('encodage MP3 impossible : ' + r.stderr.decode('utf-8', 'replace')[-200:])
    d, o, out = r.stdout, 0, []
    while o + 4 <= len(d):
        if d[o] != 0xFF or d[o + 1] & 0xE0 != 0xE0:
            raise RuntimeError(f'encodage MP3 : trame invalide à l\'octet {o}')
        size = _frame_size(d, o)
        if size != FRAME_BYTES:
            raise RuntimeError(f'encodage MP3 : trame de {size} octets')
        out.append(d[o:o + size])
        o += size
    return out


def prepare(pcm, fade=2.0):
    """Longueur = nombre entier de trames ; fondu de fin (morceau qui n'est pas une boucle) et attaque de 10 ms."""
    n = len(pcm) // FRAME_SAMPLES * FRAME_SAMPLES
    if n < MIN_SECONDS * RATE:
        raise ValueError(f'morceau trop court ({n / RATE:.0f} s, {MIN_SECONDS} s au moins)')
    if n > MAX_SECONDS * RATE:
        raise ValueError(f'morceau trop long ({n / RATE / 60:.0f} min, {MAX_SECONDS // 60} min au plus)')
    x = pcm[:n].copy()
    if fade > 0:
        k = int(fade * RATE)
        x[-k:] *= np.linspace(1, 0, k)[:, None]
        a = int(0.01 * RATE)
        x[:a] *= np.linspace(0, 1, a)[:, None]
    return x


def encode_loop(x):
    """PCM de longueur multiple de 1152 -> trames (autant que len(x) / 1152) qui bouclent sans blanc."""
    frames = len(x) // FRAME_SAMPLES
    lead = SKIP_FRAMES * FRAME_SAMPLES - DELAY           # la trame 2 decodee commence exactement au debut du morceau
    looped = np.concatenate([x[-lead:], x, x[:FRAME_SAMPLES * 2]])
    out = _encode(looped)
    if len(out) < frames + SKIP_FRAMES:
        raise RuntimeError(f'encodage MP3 : {len(out)} trames pour {frames + SKIP_FRAMES} attendues')
    return out[SKIP_FRAMES:SKIP_FRAMES + frames]


def build(original, pcm):
    """.snd : pcm prepare sur le flux 0, silence sur les autres (structure de l'original gardee)."""
    info = read_header(original)
    main = encode_loop(pcm)
    silent = _encode(np.zeros((FRAME_SAMPLES * (len(main) + 4), 2), 'f4'))[:len(main)] if info['streams'] > 1 else []
    if info['streams'] > 1 and len(silent) != len(main):
        raise RuntimeError('encodage du silence incomplet')
    return wrap(original, [main] + [silent] * (info['streams'] - 1))


def rebuild_for(original, snd):
    """Musique deja encodee (pack de maps) posee sur l'en-tete d'une autre piste ; flux en trop retires, manquants
    remplaces par le silence du dernier flux."""
    frames = split_frames(snd)
    want = read_header(original)['streams']
    return wrap(original, (frames + [frames[-1]] * want)[:want])
