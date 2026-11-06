"""Recherche de ffmpeg (music.ffmpeg_in, check_ffmpeg, find_ffmpeg), sans le jeu."""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import music  # noqa: E402


def test_folder_lookup():
    d = tempfile.mkdtemp()
    try:
        assert music.ffmpeg_in(d) is None
        assert music.ffmpeg_in('') is None
        os.makedirs(os.path.join(d, 'bin'))
        exe = os.path.join(d, 'bin', 'ffmpeg.exe')
        open(exe, 'wb').close()
        assert music.ffmpeg_in(d) == exe                      # archive ffmpeg pour Windows : dans bin
        assert music.ffmpeg_in(f'"{d}"') == exe               # chemin colle avec ses guillemets
        assert music.ffmpeg_in(exe) == exe                    # le programme lui-meme
        other = os.path.join(d, 'autre.exe')
        open(other, 'wb').close()
        assert music.ffmpeg_in(other) is None
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_user_choice_first():
    d = tempfile.mkdtemp()
    old = music.FFMPEG_PATH
    try:
        exe = os.path.join(d, 'ffmpeg.exe')
        open(exe, 'wb').close()
        music.FFMPEG_PATH = exe
        assert music.find_ffmpeg() == exe
        music.FFMPEG_PATH = os.path.join(d, 'disparu.exe')     # fichier retire depuis : recherche normale
        assert music.find_ffmpeg() != music.FFMPEG_PATH
    finally:
        music.FFMPEG_PATH = old
        shutil.rmtree(d, ignore_errors=True)


def test_check_refuses_bad_program():
    d = tempfile.mkdtemp()
    try:
        bad = os.path.join(d, 'ffmpeg.exe')
        open(bad, 'wb').write(b'pas un programme')
        try:
            music.check_ffmpeg(bad)
            raise AssertionError('programme invalide accepte')
        except ValueError:
            pass
    finally:
        shutil.rmtree(d, ignore_errors=True)
    real = shutil.which('ffmpeg')
    if real:
        assert music.check_ffmpeg(real) == real


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
