"""Tests de music.py (ffmpeg requis) : structure FSB5, boucle sans blanc, flux silencieux, relecture.
    python ctr_tools/test_music.py
"""
import os
import struct
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import music  # noqa: E402


def fake_original(channels=10, name=b'mus_test_lp', big_header=False):
    """En-tete FSB5 de meme forme que ceux du jeu, avec une trame par flux."""
    frame = bytes.fromhex('fffb9464') + bytes(music.FRAME_BYTES - 4)
    n = channels // 2
    chunks = struct.pack('<IB', 1 << 25 | 1 << 1, channels)
    if big_header:                                       # bloc supplementaire (certains originaux en ont)
        chunks = struct.pack('<IB', 1 << 25 | 1 << 1 | 1, channels) + struct.pack('<I', 6 << 25 | 64 << 1) + bytes(64)
    table = struct.pack('<I', 4) + name + b'\0'
    table += b'\0' * (-(60 + 8 + len(chunks) + len(table)) % 32)
    head = b'FSB5' + struct.pack('<6I', 1, 1, 8 + len(chunks), len(table), n * music.FRAME_BYTES, music.CODEC_MPEG) + bytes(32)
    sample = 0x13 | music.FRAME_SAMPLES << 34
    return head + struct.pack('<Q', sample) + chunks + table + frame * n


def decode_mp3(mp3):
    r = subprocess.run([music.find_ffmpeg(), '-v', 'error', '-f', 'mp3', '-i', '-', '-ac', '2', '-ar', str(music.RATE), '-f', 'f32le', '-'],
                       input=mp3, capture_output=True, check=True)
    return np.frombuffer(r.stdout, '<f4').reshape(-1, 2)


def test_header():
    o = fake_original()
    i = music.read_header(o)
    assert (i['channels'], i['streams'], i['samples'], i['data_start']) == (10, 5, 1152, len(o) - 5 * music.FRAME_BYTES)
    assert music.read_header(fake_original(big_header=True))['streams'] == 5
    assert music._sound_name(o) == b'mus_test_lp'


def periodic(seconds=12):
    """Signal parfaitement periodique sur sa longueur : toute rupture a la reprise se mesure."""
    n = seconds * music.RATE // music.FRAME_SAMPLES * music.FRAME_SAMPLES
    t = np.arange(n) / n * 2 * np.pi
    left = 0.3 * np.sin(t * 2200) + 0.2 * np.sin(t * 3301)
    return np.stack([left, 0.3 * np.sin(t * 1650)], 1).astype('f4')


def test_build_and_loop():
    x = periodic()
    frames = len(x) // music.FRAME_SAMPLES
    snd = music.build(fake_original(), x)
    i = music.read_header(snd)
    assert i['samples'] == len(x) and i['streams'] == 5
    assert (i['data_start'] + i['data_size']) == len(snd) and i['data_size'] == 5 * frames * music.FRAME_BYTES
    assert music._sound_name(snd) == b'mus_test_lp'
    fr = music.split_frames(snd)
    assert [len(s) for s in fr] == [frames] * 5
    assert fr[1] == fr[2] == fr[3] == fr[4]
    assert np.abs(decode_mp3(b''.join(fr[1]))).max() < 1e-3         # silence
    # trois tours decodes bout a bout : le 2e tour doit raccorder au signal, y compris autour de la reprise
    y = decode_mp3(b''.join(fr[0]) * 3)
    n = len(x)
    start = n - 4000                                     # a cheval sur la 1re reprise
    seg = y[start:start + 8000, 0]
    ref = np.tile(x[:, 0], 3)
    err = {d: float(np.sqrt(np.mean((seg - ref[start - d:start - d + 8000]) ** 2))) for d in range(-1500, 1500)}
    best = min(err, key=err.get)
    rms = float(np.sqrt(np.mean(seg ** 2)))
    print(f'decalage du decodeur {best} echantillons, erreur {err[best]:.4f} pour un niveau {rms:.3f}')
    assert err[best] < 0.1 * rms, 'la reprise de boucle ne raccorde pas'
    # plus petit niveau glissant autour de la reprise : un blanc ferait chuter l'enveloppe
    env = np.sqrt(np.convolve(seg ** 2, np.ones(240) / 240, 'valid'))
    print(f'enveloppe a la reprise : min {env.min():.3f}, max {env.max():.3f}')
    assert env.min() > 0.3 * rms, 'blanc a la reprise de boucle'


def test_fade_and_limits():
    x = music.prepare(np.ones((48000 * 12 + 77, 2), 'f4') * 0.5)
    assert len(x) % music.FRAME_SAMPLES == 0 and abs(x[-1, 0]) < 1e-3 and abs(x[0, 0]) < 1e-3
    for bad in (np.zeros((48000, 2), 'f4'),):
        try:
            music.prepare(bad)
        except ValueError:
            continue
        raise AssertionError('morceau trop court accepte')


def test_rebuild():
    snd = music.build(fake_original(), periodic())
    other = music.rebuild_for(fake_original(name=b'mus_autre_lp'), snd)
    assert music._sound_name(other) == b'mus_autre_lp' and music.split_frames(other)[0] == music.split_frames(snd)[0]
    two = music.rebuild_for(fake_original(channels=2, name=b'x'), snd)
    assert music.read_header(two)['streams'] == 1


if __name__ == '__main__':
    for f in (test_header, test_build_and_loop, test_fade_and_limits, test_rebuild):
        f()
        print('ok', f.__name__)
