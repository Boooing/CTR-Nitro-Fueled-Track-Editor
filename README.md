# CTR Track Editor & CTR Track Installer

**Two tools for Crash Team Racing Nitro-Fueled (PS4, v1.21, CUSA13795), played on the [shadPS4](https://github.com/shadps4-emu/shadPS4) emulator, in one repository and sharing the same engine (`ctr_tools`).**

| Tool | For | Source |
|---|---|---|
| **CTR Track Editor** | Map makers | `ctr_tools/editor/` (this page) |
| **CTR Track Installer** | Players | [`CTR Track Installer/`](CTR%20Track%20Installer) |

Import your own map (OBJ / COLLADA), turn it into a playable race in a few clicks, and add it to the game as a **brand new track** or in place of an existing one, with AI opponents, item crates, boosters, respawns, a minimap, menu images, lights and even teleporters.

Players who just want to install map packs can use **CTR Track Installer**, a small separate app (its own download; its source is the `CTR Track Installer` folder of this repository).

> 🇫🇷 Version française plus bas.

---

## What's new in v0.3

### New tracks and game menu
- **Create new tracks without replacing existing ones.** They are added to your own category in the game's track select, with their own name, background, thumbnail and in-race icon.
- **Track / category tab**: create, rename, move and delete categories and tracks (the game's ones too), or restore the original menu.

### CTR Track Installer (new)
- Standalone app for players: install one or several map packs (.zip exported by the editor) without using the editor.
- For each map, choose: new category, existing category, or replace a track.
- Automatic backup and **Restore the original game**, which lists everything that will be removed before doing it.
- Installed tracks are kept in a shared registry next to the game archives, so installing from the editor or from the installer no longer undoes the other tracks.

### Interface
- Reworked interface: menu bar (File, Edit, Add, Track, Help), Selection panel on the right, resizable panels, toolbar on the 3D view, status bar with history and shortcuts.
- Free camera: zoom towards the cursor, fly with right-click + WASD (ZQSD on AZERTY), A / E down / up, Shift to go faster.
- Camera / Objects toggle: choose whether the arrow keys move the view or the selection.
- Refresh 3D view button.

### Create the route
- **Top-down preview** after the route is generated. Draw on it to fix the route: an open stroke replaces the part between its two ends, a closed stroke replaces the whole lap. Then regenerate from the drawing.
- **Automatic start line**: an object named Start / Finish, otherwise a checkerboard on the ground, otherwise the current finish line. A "View" button shows it in the 3D view.
- **Number of sections**: transitions are added or removed and all AI lines are regenerated.
- More reliable route: holes with nothing below are kept and avoided, roads cut by a ramp are handled, and a thin seam between two road pieces no longer creates a shortcut.

### Decor
- **Lights** (presets, intensity up to 1000) that light the map in game, previewed in the 3D view.
- **Glowing textures** (right-click › Glowing texture).
- **Rescale the whole map** and **move the whole map**: route, zones, crates, boosters, grid, flyover and lights follow.
- **Import a folder of several OBJ / DAE files** and choose which objects to import (different up axes are aligned).
- The collision preview updates by itself after each change.

### Race
- **Editable fall zones**: move, resize, delete; generated in 40 m pieces.
- Respawn points shown in the 3D view.
- "Spline height" check in Check.

### Minimap and intro
- Minimap **mirror buttons** (horizontal / vertical) when it shows up flipped in game.
- Crash Cove and created tracks: the minimap is now stored the right way up by default (no more manual vertical
  mirror); older minimaps are redone automatically at install.
- Intro flyover: camera pitch fixed (shots were looking at the sky).

### Fixes
- Crash when quitting a race from the pause menu on modified maps.
- Crash when a kart fell next to the road (automatic fall zones).
- Crash when loading a track after removing its teleporter.
- Karts falling through the road right after the start on some imported maps.
- Fallback mode on PCs without WebView2 no longer freezes when choosing the game folder.
- Crash at the start of loading ANY track after playing a created track ("New map" deleted the animated boat sails
  and flags of Crash Cove; they are now moved under the map). Tracks and .zip packs made with an older version are
  repaired automatically at install.
- Created tracks: textures shared with Crash Cove were missing in the copy.
- Installer: maps of an opened .zip could stay invisible after scrolling the empty list.

---

## Features

### Build a track from your own map
- **Import a folder**: `.obj` + `.mtl` or `.dae` (COLLADA) with textures, one or several files at once. One model per material, textures converted for the game (BC1 / BC3, mipmaps), per-material collision, alpha cut-out for foliage, scale suggested from the road width. You choose which objects to import.
- **New map**: removes the original track (ground, decor, effects, animated objects, occlusion) while keeping the game logic; everything you imported stays.
- **Create the route from the road**: the race line is computed from the road geometry: sections, checkpoints, finish line, start grid, respawn points and every AI spline. Handles overpasses (a road crossing itself) and **jumps over gaps** (up to 40 m by default), and goes around rocks and pillars on the road. Pick the road pieces in a list or directly in the 3D view, choose the number of sections, check the result from above and **redraw it with the mouse** if needed. The start line is detected from a Start / Finish object or a checkerboard.
- **Add / remove transitions**: cut a section in two at any point, or delete a transition (the two sections merge and their AI splines are rebuilt); respawn points and forks follow.
- **Move / rescale the whole map** in one click, everything follows (route, zones, crates, grid, flyover, lights).
- **Lighten the map**: mesh simplification for collision and 512 px textures for background scenery.

### Race (Race mode)
- **AI splines**: edit, duplicate, delete, or regenerate them all from the road width (lanes, randomness, wall clearance), joined at every checkpoint.
- **Checkpoints / finish line**: move, rotate and resize the trigger zones; link panel for previous / next splines.
- **Start grid**: 8 slots, snapped to the ground behind the finish line.
- **Item crates**: `?` crates and Wumpa crates, placed by hand or automatically along the route, tilted to match the slope.
- **TNT, Nitro, Wumpa fruit, boosters**: objects transplanted from other tracks (turbo pads come with their ground decal).
- **Falls & respawns**: respawn points every N metres along the road (never above a gap), fall zones you can edit by hand, world kill floor.
- **Teleporters**: the Spyro Circuit "mirror" mechanism; any checkpoint can become a portal that sends karts to an arrival point you place.
- **Minimap**: generated from the route, with mirror buttons if the game reads it flipped.
- **Intro flyover**: the cutscene cameras played before the race; regenerate them from your route, set them from the current 3D view, or use a fixed shot on the grid; preview in the editor.
- **Virtual tour**: drive the racing line at kart height in the editor.

### Decor (Decor mode)
- Move / rotate / scale / duplicate / delete scenery; **collision follows** (Havok compressed-mesh encoder rebuilt from scratch).
- **Object library**: ~2,800 models from all 47 tracks and arenas, placed with their materials and textures (files copied automatically when needed).
- **Textures**: swap a material, use any external image, or make it glow.
- **Ground types**: grass, dirt, ice, snow… with the real speed and grip values read from the game; collision on / off per object.
- **Invisible walls**: from an OBJ, generated along the road edges or around a selection (joined post to post, never in front of a jump), or added by hand.
- **Lights**: point lights from presets, lighting the map in game.
- **Sky & ambience**: day / evening / night, sky, lighting and fog of another track.
- **Export to Blender**: collision, splines and full decor as OBJ.

### Tracks and game menu
- **New tracks**: added next to the game's tracks, in your own category, without replacing anything.
- **Track / category tab**: create, rename, reorder and delete categories and tracks, rename the game's categories, restore the original menu.
- **Track name and menu images**: name in every language, background / thumbnail / in-race icon.

### Share your maps
- **Map packs (.zip)**: export one or several of your tracks into a single zip **without any game file** (OBJ models, your images, route, objects, settings, menu name and images, flyover, invisible walls, lights). Others install it from the editor or with **CTR Track Installer**, as a new track or in place of a track of their choice. When the target track has a different number of sections, transitions are added or removed so the pack's AI splines are copied as is.

### Safety
- **Pre-install check** with **one-click fixes** (sky, finish line, grid, AI, crates, minimap, spline heights…).
- **Undo / redo**: every edit, plus a save history on disk.
- **Install / restore**: the game archives are patched in place with a backup; several modded tracks can be installed at the same time; the original game can be restored at any time.
- Interface in **English, French, Spanish, Italian and German**.

---

## CTR Track Installer

A separate app for players (own download; source in the [`CTR Track Installer`](CTR%20Track%20Installer) folder, which uses the `ctr_tools` engine of this repository). It installs map packs exported by the editor, organises the race menu and restores the original game, using the same engine as the editor. The list of installed tracks (`ctr_installed_tracks.json`, next to the game archives) is shared: the editor and the installer can be used on the same game without undoing each other's tracks.

---

## Requirements
- Your **own legally dumped copy** of CTR Nitro-Fueled for PS4 (CUSA13795, update 1.21) running on shadPS4. No game file is included in this repository.
- Windows 10/11 (`.exe`) or Linux x86_64 / aarch64. For the source version: Python 3.11+.

## Quick start (Windows app)
1. Run `CTR Track Editor.exe`.
2. On first launch, choose the game's **`archives`** folder from the 1.21 update (it contains `update.pak` and the track archives such as `t111_crash_cove.pak`). The choice is remembered.
3. Open **Edit › Guide: create your track in 6 steps** and follow it: *Remove the old track → Import your map → Create the route → Place objects → Check → Install*.
4. Close shadPS4 before installing, then start a race on your track.

Your saves are stored in `out/editor` next to the executable.

## Run from source
```bash
pip install -r requirements.txt
python ctr_tools/editor/server.py            # then open http://localhost:8765
python ctr_tools/editor/server.py --archives "<game archives folder>" --port 8765
```
Desktop window (pywebview): `python ctr_tools/editor/app.py`.

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
| `ctr_tools/editor/` | `server.py` (local HTTP API), `index.html` (three.js editor), `i18n.js` (translations, shared with the installer), `mappack.py` (map packs), `app.py` (desktop app), `build_exe.py`, `build_appimage.py` |
| `ctr_tools/igz.py` | Reader / writer for Alchemy `.igz` files (fixups, handles, deep clone, cross-file entity import, compaction) |
| `ctr_tools/pak_tool.py`, `game_restore.py` | `.pak` archives (IGA v13, LZMA): extract, patch in place, backups, full restore |
| `ctr_tools/track_clone.py`, `custom_category.py` | New tracks (renamed copy, hashes rebuilt) and the game's race menu |
| `ctr_tools/havok*.py`, `cms_codec.py`, `collision*.py` | Havok collision: compressed-mesh decoder / encoder, compound instances |
| `ctr_tools/route_gen.py`, `ai_gen.py`, `falls.py`, `start_finish.py` | Race line from the road, AI lanes, respawns and fall zones, finish line and grid |
| `ctr_tools/model_build.py`, `texture_build.py`, `dae_import.py` | Model, material and PS4 texture (tiling, BC1/BC3, glow) generation |
| `ctr_tools/powerup.py`, `teleport.py`, `minimap.py`, `menu_assets.py`, `library.py`, `lights.py`, `walls.py`, `flyby.py` | Crates and objects, teleporters, minimap, menus, object library, lights, invisible walls, intro flyover |
| `ctr_tools/schema/ctr_meta.json` | Class schema (names, sizes, fields) extracted from the game executable by `extract_meta.py` |
| `ctr_tools/README.md` | Detailed technical notes (French): file formats, what was validated in game, pitfalls |
| `CTR Track Installer/` | The installer app: `src/ctr_track_installer.py` (Tkinter), `build.py`, its own README |

## Disclaimer
Fan-made, non-commercial modding tool. Not affiliated with or endorsed by Activision, Beenox or Sony. Crash Team Racing and all related assets are the property of their respective owners. Use only with a copy of the game you own.

Third-party: [three.js](https://threejs.org) (MIT, `ctr_tools/editor/vendor/three/LICENSE`), [pywebview](https://pywebview.flowrl.com), NumPy, Pillow, PyInstaller.

---

## 🇫🇷 Version française

**Éditeur de pistes pour Crash Team Racing Nitro-Fueled (PS4 v1.21, CUSA13795) sur l'émulateur shadPS4.**

Importe ta propre map (OBJ / COLLADA), transforme-la en course jouable en quelques clics et ajoute-la au jeu comme **nouvelle piste** ou à la place d'une piste existante : IA, caisses, boosters, réapparitions, mini-carte, images de menu, lumières et même téléporteurs.

Deux outils dans ce dépôt, avec le même moteur (`ctr_tools`) : **CTR Track Editor** (créer des maps) et **CTR Track Installer** (dossier [`CTR Track Installer`](CTR%20Track%20Installer) : pour les joueurs qui veulent juste installer des packs de maps ; téléchargement à part).

### Nouveautés de la v0.3
- **Nouvelles pistes sans en remplacer** : elles arrivent dans ta propre catégorie du menu du jeu, avec nom, fond, vignette et icône en course. Onglet **Piste / catégorie** pour créer, renommer, déplacer et supprimer catégories et pistes (y compris celles du jeu), ou revenir au menu d'origine.
- **CTR Track Installer** : installe un ou plusieurs packs .zip sans l'éditeur. Pour chaque map : nouvelle catégorie, catégorie existante ou remplacer une piste. Sauvegarde automatique et **Remettre le jeu d'origine** (avec la liste de ce qui sera supprimé). Registre commun avec l'éditeur : installer une piste ne défait plus les autres.
- **Nouvelle interface** : barre de menus (Fichier, Édition, Ajouter, Piste, Aide), panneau Sélection à droite, panneaux redimensionnables, barre d'outils sur la vue 3D, barre d'état. Caméra libre (zoom vers le curseur, vol clic droit + ZQSD), bouton Caméra / Objets, bouton Actualiser la vue.
- **Créer le parcours** : vue de dessus après la génération, **dessin à la souris** pour corriger un morceau ou tout le tour ; **ligne de départ détectée** (objet Start / Finish, sinon damier au sol) ; nombre de sections au choix ; tracé plus fiable (trous sans rien dessous contournés, route coupée par une rampe, plus de raccourci par une fente entre deux morceaux).
- **Décor** : **lumières** qui éclairent la map en jeu (aperçu dans la vue 3D), **textures lumineuses**, **changer l'échelle / déplacer toute la map** (tout suit), **import d'un dossier de plusieurs OBJ / DAE** avec choix des objets, sol de collision mis à jour tout seul.
- **Course** : **zones de chute modifiables** (déplacer, redimensionner, supprimer, morceaux de 40 m), points de réapparition affichés, contrôle « Hauteur des splines ».
- **Mini-carte** : boutons miroir ; Crash Cove et pistes créées dans le bon sens par défaut (plus de miroir vertical à la main, anciennes mini-cartes refaites à l'installation). **Survol d'introduction** : inclinaison des caméras corrigée.
- **Corrections** : plantage en quittant une course depuis la pause, plantage quand un kart tombait à côté de la route, plantage au chargement après avoir retiré un téléporteur, karts qui traversaient la route au départ, mode secours sans WebView2, **plantage au chargement de n'importe quelle piste après une piste créée** (« Nouvelle map » supprimait les voiles et drapeaux animés des bateaux de Crash Cove : ils sont désormais descendus sous la carte ; pistes et packs .zip d'une ancienne version réparés à l'installation), textures partagées avec Crash Cove manquantes dans les pistes créées, maps d'un .zip invisibles dans l'installateur après un coup de molette.

### Fonctionnalités
- **Ta map** : import d'un dossier OBJ / DAE + textures (un ou plusieurs fichiers, choix des objets, collision et transparence par matériau, échelle proposée), « Nouvelle map » qui retire l'ancienne piste, déplacer / changer l'échelle de toute la map, allègement.
- **Parcours automatique** depuis la forme de la route : sections, ligne d'arrivée, grille, réapparitions, toutes les splines IA ; routes qui se croisent, **sauts au-dessus des trous**, obstacles contournés ; vue de dessus et correction au dessin ; départ détecté ; nombre de sections au choix ; transitions ajoutées / supprimées.
- **Course** : splines IA (édition, génération), zones de transition, grille de départ, caisses `?` et fruits (posées selon la pente), TNT, Nitro, fruits Wumpa, boosters, chutes et réapparitions, zones de chute modifiables, **téléporteurs** (le miroir de Spyro Circuit), mini-carte, survol d'introduction, visite virtuelle.
- **Décor** : déplacer / tourner / dupliquer avec la collision qui suit, **bibliothèque de ~2 800 objets** des 47 pistes, textures (images externes, textures lumineuses), **types de sol** avec vitesse et adhérence réelles, murs invisibles, lumières, ambiance jour / soir / nuit et ciel d'une autre piste, export Blender.
- **Pistes et menu** : nouvelles pistes dans ta catégorie, onglet Piste / catégorie, nom et images de menu.
- **Partage** : **packs de maps (.zip)** sans aucun fichier du jeu, à installer depuis l'éditeur ou avec **CTR Track Installer**.
- **Sécurité** : vérification avant installation et **corrections en un clic**, annuler / rétablir, installation réversible, plusieurs pistes installées en même temps, retour au jeu d'origine.
- Interface en **français, anglais, espagnol, italien et allemand**.

### Démarrage
Lance `CTR Track Editor.exe`, choisis le dossier `archives` du jeu, puis ouvre **Édition › Guide : créer ta piste en 6 étapes**. Depuis les sources : `pip install -r requirements.txt` puis `python ctr_tools/editor/server.py` (http://localhost:8765). L'installateur pour les joueurs (**CTR Track Installer**) est un téléchargement à part ; ses sources sont dans le dossier `CTR Track Installer` de ce dépôt (`python "CTR Track Installer/src/ctr_track_installer.py"`).

Outil de fan, non commercial, sans lien avec Activision, Beenox ou Sony. Aucun fichier du jeu n'est inclus : il faut ta propre copie du jeu.
