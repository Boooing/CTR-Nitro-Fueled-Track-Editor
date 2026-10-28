# CTR Track Editor

**A track editor for Crash Team Racing Nitro-Fueled (PS4, v1.21 — CUSA13795), played on the [shadPS4](https://github.com/shadps4-emu/shadPS4) emulator.**

Import your own map (OBJ / COLLADA), turn it into a playable race in a few clicks, and install it in place of an existing track — with AI opponents, item crates, boosters, respawns, a minimap, menu images and even teleporters.

Discord : https://discord.gg/m3Zv6sXEgU


> 🇫🇷 Version française plus bas.

---

## What's new V0.2

### Invisible walls (Decor mode)
- **Three ways to make one**:
  - **From an OBJ**: set its type to *Invisible wall*. It keeps its collision and nothing is drawn in game.
  - **Generated along the road**: walls where the road edge drops into the void, or optionally where it meets grass or other ground.
  - **By hand**: “Add a wall at the centre of the view”.
- **Walls around a selection**: pick one or several parts of the map in the 3D view (also from the right-click menu). Walls follow their edges and are never placed on the race route.
- **Walls join up**: gaps along an edge are closed, and nearby wall ends are linked along the object itself. A fence becomes one wall from post to post, curves included. The new *Join walls closer than* setting (120 m by default) controls this.
- **Never in front of a jump**: no wall is placed on a road end at the edge of a gap, even when the landing is much lower.
- Walls are shown in translucent purple in the editor and can be hidden. They travel with map packs.

### Create the route
- **Jumps**: the race line now crosses a gap through the middle of the road, not via the nearest corner. AI lanes keep their spread over the void instead of squeezing into one point.
- **Solid objects on the road**: the race line and the AI lanes now go around rocks and pillars sitting on the road. Ramps, turbo pads, bridges and tunnels are not treated as obstacles.
- **More robust**:
  - Giant background scenery picked by mistake is ignored.
  - A road cut by gaps of more than 40 m is retried with gaps up to 80 m.
  - A kill floor left by an older route no longer blocks the new one.

### Intro cameras
- **Intro flyover**: the cutscene cameras played before the race. You can regenerate them from your route, frame a shot from the current 3D view, or use a fixed shot on the grid, then preview them in the editor.

### Map packs (.zip import / export)
- **Export** one or several tracks into a single **.zip with no game file inside**: models, images, route, objects, settings, menu name and images, flyover and invisible walls.
- **Import** a pack: choose which maps to install and **in place of which track**, then install them in one click. The AI splines are kept even if the target track has a different number of sections.

### Decor
- **Move the whole map up or down** (Decor › Finishing): every object moves in Z, and collision and booster pads follow.
- **Ground types**: the right-click menu shows each ground's slowdown and grip again (dirt, grass, ice…).

---

## Features

### Build a track from your own map
- **Import a folder** — `.obj` + `.mtl` or `.dae` (COLLADA) with its textures: one model per material, textures converted for the game (BC1 / BC3, mipmaps), per-material collision, alpha cut-out for foliage, automatic scale suggestion from the road width.
- **New map** — removes the original track (ground, decor, effects, animated objects, occlusion) while keeping the game logic; everything you imported stays.
- **Create the route from the road** — the race line is computed from the road geometry: sections, checkpoints, finish line, start grid, respawn points and every AI spline. Handles overpasses (a road crossing itself) and **jumps over gaps**. Pick the road pieces in a list or directly in the 3D view. **Choose the number of sections** (transitions): they are added or removed for you.
- **Spline height check** — “Check” flags route / AI splines buried under the road or floating in the air outside a jump (a jump from A to B is fine), with a one-click fix.
- **Add / remove transitions** — cut a section in two at any point (new transition + new position spline), or delete a transition (the two sections merge, their AI splines are rebuilt); respawn points and forks follow.
- **Lighten the map** — mesh simplification for collision and 512 px textures for background scenery.

### Race (Course mode)
- **AI splines** — edit, duplicate, delete, or regenerate them all from the road width (lanes, randomness, wall clearance), automatically joined at every checkpoint.
- **Checkpoints / finish line** — move, rotate and resize the trigger zones; link panel for previous / next splines.
- **Start grid** — 8 slots, snapped to the ground behind the finish line.
- **Item crates** — `?` crates and Wumpa crates, placed by hand or automatically along the route, tilted to match the slope.
- **TNT, Nitro, Wumpa fruit, boosters** — objects transplanted from other tracks (turbo pads come with their ground decal).
- **Falls & respawns** — respawn points every N metres along the road (never above a gap), fall zones, world kill floor.
- **Teleporters** — the Spyro Circuit "mirror" mechanism: any checkpoint can become a portal that sends karts to an arrival point you place.
- **Minimap** — generated from the route, correctly oriented.
- **Track name and menu images** — name in every language, background / thumbnail / emblem images.
- **Virtual tour** — drive the racing line at kart height in the editor.
- **Intro flyover** — the cutscene cameras played before the race: regenerate them from your route, set them from the current 3D view, or use a fixed shot on the grid; preview in the editor.

### Decor (Décor mode)
- Move / rotate / scale / duplicate / delete scenery; **collision follows** (Havok compressed-mesh encoder rebuilt from scratch).
- **Object library** — ~2,800 models from all 47 tracks and arenas, placed with their materials and textures (files copied automatically when needed).
- **Textures** — swap a material, or use any external image as a texture.
- **Ground types** — grass, dirt, ice, snow… with the real speed and grip values read from the game; collision on / off per object.
- **Sky & ambience** — copy the sky, lighting and fog of another track.
- **Export to Blender** — collision, splines and full decor as OBJ.

### Share your maps
- **Map packs (.zip)** — export one or several of your tracks into a single zip **without any game file** (OBJ models, your images, route, objects, settings, menu name and images, flyover). Anyone who owns the game imports it from the editor, picks which maps to install and **in place of which track**, and can install them straight into the game. When the target track has a different number of sections, transitions are added or removed so the pack's AI splines are copied as is.

### Safety
- **Pre-install check** with **one-click fixes** (sky, finish line, grid, AI, crates, minimap…).
- **Undo / redo** — every edit, plus a save history on disk.
- **Install / restore** — the game archives are patched in place with a backup; several modded tracks can be installed at the same time; "Restore archives" puts the original game back.
- Interface in **English, French, Spanish, Italian and German**.

---

## Requirements
- Your **own legally dumped copy** of CTR Nitro-Fueled for PS4 (CUSA13795, update 1.21) running on shadPS4. No game file is included in this repository.
- Windows 10/11 (`.exe`) or Linux x86_64 / aarch64 (`.AppImage`). For the source version: Python 3.11+.

## Quick start (Windows app)
1. Run `CTR Track Editor.exe`.
2. On first launch, choose the game's **`archives`** folder from 1.21 Update (it contains `update.pak` and the track archives such as `t111_crash_cove.pak`). The choice is remembered.
3. Follow the 6-step guide on the left: *Remove the old track → Import your map → Create the route → Place objects → Check → Install*.
4. Close shadPS4 before installing, then start a race on the track you replaced.

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
Most tests take the game's `archives` folder (they read real game files, nothing is modified); a few take a
file or an extracted folder (see the `Usage` line at the top of each test):
```bash
python ctr_tools/test_library.py "<game archives folder>"
python ctr_tools/pak_tool.py extract "<game archives folder>/t111_crash_cove.pak" extracted/t111_crash_cove
python ctr_tools/test_roundtrip.py extracted          # every .igz re-written byte for byte
```

## Project layout
| Path | Content |
|---|---|
| `ctr_tools/editor/` | `server.py` (local HTTP API), `index.html` (three.js editor), `i18n.js` (translations), `app.py` (Windows app), `build_exe.py` |
| `ctr_tools/igz.py` | Reader / writer for Alchemy `.igz` files (fixups, handles, deep clone, cross-file entity import, compaction) |
| `ctr_tools/pak_tool.py` | `.pak` archives (IGA v13, LZMA): extract, patch in place, backups |
| `ctr_tools/havok*.py`, `cms_codec.py`, `collision*.py` | Havok collision: compressed-mesh decoder / encoder, compound instances |
| `ctr_tools/route_gen.py`, `ai_gen.py`, `falls.py` | Race line from the road, AI lanes, respawns |
| `ctr_tools/model_build.py`, `texture_build.py`, `dae_import.py` | Model, material and PS4 texture (tiling, BC1/BC3) generation |
| `ctr_tools/powerup.py`, `teleport.py`, `minimap.py`, `menu_assets.py`, `library.py` | Crates and objects, teleporters, minimap, menus, object library |
| `ctr_tools/schema/ctr_meta.json` | Class schema (names, sizes, fields) extracted from the game executable by `extract_meta.py` |
| `ctr_tools/README.md` | Detailed technical notes (French): file formats, what was validated in game, pitfalls |

## Disclaimer
Fan-made, non-commercial modding tool. Not affiliated with or endorsed by Activision, Beenox or Sony. Crash Team Racing and all related assets are the property of their respective owners. Use only with a copy of the game you own.

Third-party: [three.js](https://threejs.org) (MIT, `ctr_tools/editor/vendor/three/LICENSE`), [pywebview](https://pywebview.flowrl.com), NumPy, Pillow, PyInstaller.

---

## 🇫🇷 Version française

**Éditeur de pistes pour Crash Team Racing Nitro-Fueled (PS4 v1.21, CUSA13795) sur l'émulateur shadPS4.**

Importe ta propre map (OBJ / COLLADA), transforme-la en course jouable en quelques clics et installe-la à la place d'une piste du jeu : IA, caisses, boosters, réapparitions, mini-carte, images de menu et même téléporteurs.

**Nouveautés**
- **Murs invisibles** (mode Décor) :
  - **Trois façons d'en créer** : un OBJ dont tu choisis le type *Mur invisible* (collision seule, rien à l'écran en jeu), une génération automatique le long des bords de la route, ou un ajout à la main.
  - **Autour d'une sélection** : choisis des parties de la map dans la vue 3D, ou passe par le clic droit. Les murs ne sont jamais posés sur le parcours.
  - **Murs reliés** : les trous le long d'un bord sont fermés, et les bouts proches sont reliés en suivant l'objet (une barrière devient un seul mur de poteau en poteau, virages compris). Le réglage est « Relier les murs », à 120 m par défaut.
  - **Jamais devant un saut**.
  - Les murs voyagent avec les packs de maps.
- **Créer le parcours** :
  - **Sauts** : le tracé franchit un trou par le milieu de la route, plus par un coin. Les voies IA restent écartées au-dessus du vide.
  - **Obstacles** : le tracé et les IA **contournent les rochers et piliers posés sur la route**. Les tremplins, plaques turbo, ponts et tunnels ne gênent pas.
  - **Plus robuste** : le décor de fond géant sélectionné par erreur est ignoré, une route coupée par des trous de plus de 40 m est réessayée jusqu'à 80 m, et un ancien plancher de chute ne bloque plus.
- **Caméras de début de map** : le survol d'introduction (cinématique d'avant-course) est régénéré d'après ton parcours, cadré depuis la vue 3D, ou remplacé par un plan fixe sur la grille, avec un aperçu dans l'éditeur.
- **Import / export en .zip (packs de maps)** :
  - **Export** : une ou plusieurs pistes dans un seul .zip **sans aucun fichier du jeu** (modèles, images, parcours, objets, réglages, nom et images de menu, survol, murs invisibles).
  - **Import** : tu choisis les maps et la piste qu'elles remplacent, puis tu installes en un clic. Les IA sont gardées même si la piste cible n'a pas le même nombre de sections.
- **Décor** :
  - **Déplacer toute la map en hauteur** (Décor › Finitions) : la collision et les plaques de booster suivent.
  - Le clic droit réaffiche le **ralentissement et l'adhérence** de chaque sol.

**Fonctionnalités**
- **Ta map** : import d'un dossier OBJ / DAE + textures (collision et transparence par matériau, échelle proposée), « Nouvelle map » qui retire l'ancienne piste, allègement de la map.
- **Parcours automatique** depuis la forme de la route : sections, ligne d'arrivée, grille, réapparitions, toutes les splines IA ; routes qui se croisent et **sauts au-dessus des trous** ; choix des morceaux de route dans la vue 3D ; **nombre de sections au choix**.
- **Contrôle de hauteur des splines** : « Vérifier » signale les splines de parcours / IA enfoncées sous la route ou en l'air hors d'un saut (un saut de A à B est accepté), avec correction en un clic.
- **Transitions ajoutées / supprimées** : couper une section en deux à n'importe quel point, ou supprimer une transition (les deux sections fusionnent, leurs IA sont refaites) ; réapparitions et embranchements suivent.
- **Course** : splines IA (édition, génération), zones de transition, grille de départ, caisses `?` et fruits (posées selon la pente), TNT, Nitro, fruits Wumpa, boosters, chutes et réapparitions, **téléporteurs** (le miroir de Spyro Circuit), mini-carte, nom et images de menu, visite virtuelle, **survol
  d'introduction** (caméras de la cinématique d'avant-course régénérées d'après ton parcours ou cadrées à la main).
- **Décor** : déplacer / tourner / dupliquer avec la collision qui suit, **bibliothèque de ~2 800 objets** des 47 pistes, textures (y compris images externes), **types de sol** avec vitesse et adhérence réelles, ciel et ambiance d'une autre piste, export Blender.
- **Partage** : **packs de maps (.zip)** sans aucun fichier du jeu, à réimporter et installer en un clic à la place de
  la piste de son choix (si la piste cible n'a pas le même nombre de sections, des transitions sont ajoutées / retirées : les IA du pack sont copiées telles quelles).
- **Sécurité** : vérification avant installation et **corrections en un clic**, annuler / rétablir, installation réversible (sauvegarde des archives), plusieurs pistes installées en même temps.
- Interface en **français, anglais, espagnol, italien et allemand**.

**Démarrage** : lance `CTR Track Editor.exe`, choisis le dossier `archives` du jeu, puis suis le guide en 6 étapes. Depuis les sources : `pip install -r requirements.txt` puis `python ctr_tools/editor/server.py` (http://localhost:8765).

Outil de fan, non commercial, sans lien avec Activision, Beenox ou Sony. Aucun fichier du jeu n'est inclus : il faut ta propre copie du jeu.
