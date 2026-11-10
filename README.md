# CTR Track Editor

**A track editor for Crash Team Racing Nitro-Fueled (PS4, v1.21, CUSA13795), for the [shadPS4](https://github.com/shadps4-emu/shadPS4) emulator and the OCTR PC port.**

Import your own map (OBJ / COLLADA) or **build one from scratch in the editor**, turn it into a playable race in a few clicks, and add it to the game as a **brand new track** or in place of an existing one, with AI opponents, item crates, boosters, respawns, a minimap, menu images, your own music, lights and even teleporters.

> 🇫🇷 Version française plus bas.
>
> This folder holds the editor only. **CTR Track Installer**, the separate app for players, is not part of it.

---
## What's new in v0.5


### Automatic updates
- The editor checks GitHub at launch and offers the new version; it replaces itself and restarts. Your saves, settings and FFmpeg stay in place. v0.4 has no updater: install v0.5 by hand once.

### A clearer editor
- New look: line icons, a vertical tool bar on the 3D view, mouse hints in the status bar, tabs in work order (Create, Edit, Track / category).
- Scene objects panel (replaces Search): every object of the map by category (scenery by model, invisible walls, lights, crates, boosters, fall zones), with 3D thumbnails, select, show / hide and details.
- The right-hand inspector is laid out in blocks (Position, Tool, Actions...) for scenery, crates, boosters, splines, grid, finish line, lights.
- Colorize an object (Edit › select › *Colorize…*, or right-click): tint that keeps the texture's details, or flat paint, with intensity and live preview; parts of the object and "all identical objects" can be chosen. *(not tried in game yet)*
- Faster editing on big maps: adding objects, colouring, changing a ground type... no longer rebuilds the whole collision each time (about 2 minutes on a big map). It is rebuilt once, on Save (orange dot on the button), and always before installing or checking.

### Create tab
- New panel in blocks, Scenery in two tabs (*Automatic* / *By hand*).
- Smarter automatic scenery: styles (balanced, nature, clear, wild, built), amount per family, objects borrowed from other themes when the ground has no matching object, corners kept clear. *(not tried in game yet)*
- Bigger height range (road from -200 m to +300 m), road banking up to 30°, slopes with or without embankment per section, embankment width, smooth blending between ground paints, tilted objects that sit on the slope, "Place the kart" to choose the start. *(partly tried in game)*
- Parts of the map far from the road can be trimmed at generation (lighter map).
- "Generate the track" now offers a new track by default, so nobody overwrites Crash Cove by mistake.

### Race
- Rotatable crates, automatic crate rows centred on the race line.
- Reverse the race direction (or one spline). *(not tried in game yet)*
- Better route detection on stacked roads (spirals, 3 levels) and jumps up to 80 m; AI lanes that keep their width where road pieces overlap. *(not tried in game yet)*
- Falls and respawns work on tracks whose respawn points are in the RaceSystem (Star Circuit, Slide Coliseum, Turbo Track...). *(not tried in game yet)*
- More game tracks can be edited (Thunder Struck, Out of Time, Electron Avenue and the tracks whose race line is in the _Design).

### Game and install
- Restore the game's archives: this track or the whole game; put back a track removed by a full restore.
- Big maps: track archive capped to what the game can load (textures reduced if needed), "Game memory" line in Check, lighter collision for far scenery.
- The ground type Turbo is removed (it had no effect in game; use boosters).

### Fixes
- Infinite loading when an object with several textures had a custom texture on a part other than the first one (e.g. a colourised rock).
- Crash when leaving a track after a race (object reference counts), crash after loading with too many AI lanes (copies installed with 6 lanes per section at most), "Test in game" crash after the title-screen patch.
- Fall zones that triggered on the low edge of banked corners.
- Save error after re-creating many AI lanes on a big track; missing sky on copied tracks; "unexpected title-screen script" on another PC.

---

## What's new in v0.4

Items marked *(not tried in game yet)* work in the editor and pass their offline tests, but nobody has confirmed them in a race yet.

### Create tab: build a track without any 3D software
- **Drive to lay the road**: a paver kart in the 3D view (keyboard or gamepad, with configurable buttons), road width 40 to 120 m, undo / redo.
- **Terrain**: raise, dig, flatten, smooth, paint. The ground follows the road, and bridges are made where the road crosses itself.
- **26 themes** taken from the game's tracks, each with its road, ground materials and objects. Objects from every theme can be mixed, with 3D thumbnails and a brush or "along the road" placement.
- **Barriers** and start checkerboard. Generate, and the route, AI, grid and respawns are created for you.
- *(not tried in game yet)* Jumps with the larger ramp, the "dig under the road" tool, 4 m road strips, and the 47 extra 3D objects.

### Your own music
- **Import a song** per track (MP3, WAV, FLAC, OGG, M4A...): seamless loop, level matching.
- **Final lap**: keep the same music with no change (the jingle still plays), same song a bit faster, another song, or the original.
- Packs carry the music with the track. **Requires FFmpeg** (see below). Tried in game on Crash Cove.

### OCTR PC port
- **File › Export for PC (OCTR)**: one mod (.zip) holding one or several tracks, with the name of each track and of their menu category. Works in OCTR, including 21:9.

### Boosters and ground
- **Super boosters**, **boosters that follow the slope**, and boosters that work in **time trial**.
- Boost settings: colour, power, reserve *(confirmed working overall; the power and duration effects were not checked separately)*.
- **Custom ground types** with their own speed and grip. A slow ground was tried in game; slip was not confirmed.

### Editing
- **Test in game**: one button installs the track and starts a race on it in shadPS4.
- **Single Edit tab** (scenery and race together), selection filter All / Track / Scenery, rectangle selection (B), hide / show objects (H).
- **Edit an object's shape and textures** (right-click), including models with several textures.
- *(not tried in game yet)* **Visible from both sides** (right-click), for flat signs seen from behind.
- *(not tried in game yet)* **Relic and ghost times** (Track › Relic and ghost times).
- **Bigger minimap**, sized like the game's own.

### Check before installing
- The check now reports **intro flyover cameras** not redone for a new map, and race zones that would respawn the kart: fall zones on the route are lowered, Respawn surfaces at road level are reported.

### Window and install
- **Qt window**: no more Edge WebView2 needed on your PC.
- Files added by an install now go to `update3.pak`, so `update.pak` and `update2.pak` keep their file positions (needed by OCTR's 21:9 and 32:9 layouts).

### Fixes
- "Collision too detailed" error when scattering many objects.
- Generation error when another track was already installed.
- Road and scenery display after generating a track.

---

---

## Requirements
- Your **own legally dumped copy** of CTR Nitro-Fueled for PS4 (CUSA13795, update 1.21), on shadPS4 or the OCTR PC port. No game file is included in this repository.
- Windows 10/11 (`.exe`) or Linux x86_64 / aarch64. For the source version: Python 3.11+.
- **FFmpeg, only to import music** (see below).

## FFmpeg (only for importing music)
[FFmpeg](https://ffmpeg.org/download.html) is **not included** in this repository (too large for GitHub) and is only needed to **import** a song. Everything else works without it, including playing tracks and packs that already contain music.

The editor looks for it in this order: the path you gave it, next to the `.exe`, then your system `PATH`. If it isn't found, **Track › Track music** tells you and asks where it is: browse to its folder or paste the path (its `bin` subfolder is checked too). It must support MP3 encoding (`libmp3lame`), as the usual full builds do. Your choice is remembered.

- Windows: `winget install Gyan.FFmpeg`, or unzip a build from the FFmpeg site.
- Linux: `sudo apt install ffmpeg` (or your distribution's package).

## Quick start (Windows app)
1. Run `CTR Track Editor.exe`.
2. On first launch, choose the game's **`archives`** folder from the 1.21 update (it contains `update.pak` and the track archives such as `t111_crash_cove.pak`). The choice is remembered.
3. Build a track in the **Create** tab, or bring your own map: *File › Import your map*, then *Track › Create the route*, place objects, **Check**, **Install in the game**.
4. Close shadPS4 before installing, then start a race on your track.

Your saves are stored in `out/editor` next to the executable.

## Run from source
```bash
pip install -r requirements.txt
python ctr_tools/editor/server.py            # then open http://localhost:8765
python ctr_tools/editor/server.py --archives "<game archives folder>" --port 8765
```
Desktop window (Qt WebEngine): `python ctr_tools/editor/app.py`.

### Build the Windows app
```bash
python ctr_tools/editor/build_exe.py [output folder]
```
PyInstaller one-folder build: `CTR Track Editor.exe` + `_internal/` (Python, libraries, editor page, three.js, IGZ schema). Works offline.

### Build the Linux AppImage
```bash
python3 -m venv .build_venv
.build_venv/bin/python -m pip install pyinstaller pywebview qtpy PyQt6 PyQt6-WebEngine numpy pillow
.build_venv/bin/python ctr_tools/editor/build_appimage.py [output folder]
```
Single-file `CTR_Track_Editor-<arch>.AppImage` with an embedded Qt WebEngine window. Build on the oldest distribution you want to support (e.g. Ubuntu 22.04). Saves and settings are stored next to the `.AppImage` (or in `~/.local/share/ctr-track-editor` if that folder is read-only).

### Tests
Most tests take the game's `archives` folder (they read real game files, nothing is modified); a few take a file or an extracted folder (see the `Usage` line at the top of each test):
```bash
python ctr_tools/test_library.py "<game archives folder>"
python ctr_tools/pak_tool.py extract "<game archives folder>/t111_crash_cove.pak" extracted/t111_crash_cove
python ctr_tools/test_roundtrip.py extracted          # every .igz re-written byte for byte
```

## Project layout
| Path | Content |
|---|---|
| `ctr_tools/editor/` | `server.py` (local HTTP API), `index.html` (three.js editor), `i18n.js` (translations), `creator.js` (Create tab), `octr_export.py` (OCTR mods), `mappack.py` (map packs), `app.py` (desktop app), `build_exe.py`, `build_appimage.py` |
| `ctr_tools/igz.py` | Reader / writer for Alchemy `.igz` files (fixups, handles, deep clone, cross-file entity import, compaction) |
| `ctr_tools/pak_tool.py`, `game_restore.py` | `.pak` archives (IGA v13, LZMA): extract, patch in place, backups, full restore |
| `ctr_tools/track_clone.py`, `custom_category.py` | New tracks (renamed copy, hashes rebuilt) and the game's race menu |
| `ctr_tools/havok*.py`, `cms_codec.py`, `collision*.py` | Havok collision: compressed-mesh decoder / encoder, compound instances |
| `ctr_tools/route_gen.py`, `ai_gen.py`, `falls.py`, `start_finish.py` | Race line from the road, AI lanes, respawns and fall zones, finish line and grid |
| `ctr_tools/model_build.py`, `texture_build.py`, `dae_import.py` | Model, material and PS4 texture (tiling, BC1/BC3, glow) generation |
| `ctr_tools/powerup.py`, `teleport.py`, `minimap.py`, `menu_assets.py`, `library.py`, `lights.py`, `walls.py`, `flyby.py` | Crates and objects, teleporters, minimap, menus, object library, lights, invisible walls, intro flyover |
| `ctr_tools/track_creator.py`, `music.py`, `collision_materials.py`, `race_times.py`, `quick_test.py` | Create tab, music import, custom ground types, relic and ghost times, Test in game |
| `ctr_tools/schema/ctr_meta.json` | Class schema (names, sizes, fields) extracted from the game executable by `extract_meta.py` |
| `ctr_tools/README.md` | Detailed technical notes (French): file formats, what was validated in game, pitfalls |

## Disclaimer
Fan-made, non-commercial modding tool. Not affiliated with or endorsed by Activision, Beenox or Sony. Crash Team Racing and all related assets are the property of their respective owners. Use only with a copy of the game you own.

Third-party: [three.js](https://threejs.org) (MIT, `ctr_tools/editor/vendor/three/LICENSE`), [Qt / PySide6](https://www.qt.io/qt-for-python) (LGPL), NumPy, Pillow, PyInstaller. [FFmpeg](https://ffmpeg.org) is not distributed here.

---

## 🇫🇷 Version française

**Éditeur de pistes pour Crash Team Racing Nitro-Fueled (PS4 v1.21, CUSA13795), pour l'émulateur shadPS4 et le portage PC OCTR.**

Importe ta map (OBJ / COLLADA) ou **construis-la de zéro dans l'éditeur**, transforme-la en course jouable en quelques clics et ajoute-la au jeu comme **nouvelle piste** ou à la place d'une piste existante : IA, caisses, boosters, réapparitions, mini-carte, images de menu, ta propre musique, lumières et même téléporteurs.

Ce dossier contient l'éditeur seul. **CTR Track Installer**, l'appli à part pour les joueurs, n'en fait pas partie.

### Nouveautés de la v0.4
Les points marqués *(pas encore essayé en jeu)* marchent dans l'éditeur et passent leurs tests hors jeu, sans confirmation en course pour l'instant.

- **Onglet Création** : pose la route en conduisant une paveuse (clavier ou manette, boutons configurables), largeur 40 à 120 m, annuler / rétablir ; relief et peinture du sol, ponts automatiques, barrières, damier de départ ; **26 thèmes** tirés des pistes du jeu, objets de tous les thèmes avec vignettes 3D, au pinceau ou le long de la route. *(pas encore essayé en jeu : sauts avec le grand tremplin, « Creuser sous la route », route en bandes de 4 m, les 47 objets 3D ajoutés.)*
- **Ta musique** : un morceau par piste (MP3, WAV, FLAC, OGG, M4A...), boucle sans blanc, niveau sonore du jeu. Dernier tour au choix : même musique sans changement (le jingle reste), même morceau plus rapide, autre morceau, ou l'original. Les packs emportent la musique. **Il faut FFmpeg** (voir plus bas). Essayé en jeu sur Crash Cove.
- **Portage PC OCTR** : Fichier › Exporter pour le PC (OCTR) : un seul mod (.zip) avec une ou plusieurs pistes, le nom de chacune et celui de leur catégorie. Fonctionne dans OCTR, 21:9 compris.
- **Boosters et sol** : **super turbos**, boosters **inclinés selon la pente**, boosters actifs en **contre-la-montre** ; réglages de couleur, puissance et réserve (effet de la puissance et de la durée pas vérifié à part) ; **types de sol** à vitesse et adhérence propres (sol lent essayé en jeu, glissade pas confirmée).
- **Édition** : **Tester en jeu** en un bouton, onglet **Édition** unique (décor et course), filtre Tout / Piste / Décor, sélection rectangle (B), cacher / réafficher (H), **forme et textures d'un objet** (clic droit, modèles à plusieurs textures compris), **mini-carte plus grande**. *(pas encore essayé en jeu : « Visible des deux côtés », temps des reliques et des fantômes.)*
- **Vérifier** signale aussi les **caméras de survol** pas refaites et les zones qui feraient réapparaître le kart sur la course.
- **Fenêtre Qt** : plus besoin d'Edge WebView2. Les fichiers ajoutés à l'installation vont dans `update3.pak`, pour garder les positions d'`update.pak` et `update2.pak` (nécessaire au 21:9 et au 32:9 d'OCTR).

### FFmpeg (seulement pour importer une musique)
[FFmpeg](https://ffmpeg.org/download.html) **n'est pas inclus** dans ce dépôt (trop gros pour GitHub). Tout le reste marche sans lui, y compris jouer des pistes et des packs qui ont déjà leur musique.

L'éditeur le cherche ici, dans l'ordre : le chemin que tu lui as donné, à côté du `.exe`, puis le `PATH` du système. S'il ne le trouve pas, **Piste › Musique de la piste** te le dit et te demande où il est : parcours jusqu'à son dossier ou colle le chemin (son sous-dossier `bin` est aussi regardé). Il doit savoir encoder en MP3 (`libmp3lame`), comme les versions complètes habituelles. Ton choix est retenu.

- Windows : `winget install Gyan.FFmpeg`, ou décompresse une version du site de FFmpeg.
- Linux : `sudo apt install ffmpeg` (ou le paquet de ta distribution).

### Démarrage
Lance `CTR Track Editor.exe`, choisis le dossier `archives` du jeu, puis construis ta piste dans l'onglet **Création**, ou importe ta map (**Fichier › Importer ta map**) et crée le parcours. Depuis les sources : `pip install -r requirements.txt` puis `python ctr_tools/editor/server.py` (http://localhost:8765), ou `python ctr_tools/editor/app.py` pour la fenêtre.

Outil de fan, non commercial, sans lien avec Activision, Beenox ou Sony. Aucun fichier du jeu n'est inclus : il faut ta propre copie du jeu. Un mod OCTR contient, lui, des archives de piste complètes : ne le partage qu'avec des joueurs qui ont le jeu.
