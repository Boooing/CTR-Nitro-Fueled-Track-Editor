# CTR Track Editor

**A track editor for Crash Team Racing Nitro-Fueled (PS4, v1.21 — CUSA13795), played on the [shadPS4](https://github.com/shadps4-emu/shadPS4) emulator and CTR Nitro Fueled PC Port [CTR-NitroFueled-PC](ttps://github.com/GetLostIn/CTR-NitroFueled-PC) .**

Import your own map (OBJ / COLLADA), turn it into a playable race in a few clicks, and install it in place of an existing track — with AI opponents, item crates, boosters, respawns, a minimap, menu images and even teleporters.

> 🇫🇷 Version française plus bas.

---

## Features

### Build a track from your own map
- **Import a folder** — `.obj` + `.mtl` or `.dae` (COLLADA) with its textures: one model per material, textures converted for the game (BC1 / BC3, mipmaps), per-material collision, alpha cut-out for foliage, automatic scale suggestion from the road width.
- **New map** — removes the original track (ground, decor, effects, animated objects, occlusion) while keeping the game logic; everything you imported stays.
- **Create the route from the road** — the race line is computed from the road geometry: sections, checkpoints, finish line, start grid, respawn points and every AI spline. Handles overpasses (a road crossing itself) and **jumps over gaps**. Pick the road pieces in a list or directly in the 3D view.
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

### Decor (Décor mode)
- Move / rotate / scale / duplicate / delete scenery; **collision follows** (Havok compressed-mesh encoder rebuilt from scratch).
- **Object library** — ~2,800 models from all 47 tracks and arenas, placed with their materials and textures (files copied automatically when needed).
- **Textures** — swap a material, or use any external image as a texture.
- **Ground types** — grass, dirt, ice, snow… with the real speed and grip values read from the game; collision on / off per object.
- **Sky & ambience** — copy the sky, lighting and fog of another track.
- **Export to Blender** — collision, splines and full decor as OBJ.

### Safety
- **Pre-install check** with **one-click fixes** (sky, finish line, grid, AI, crates, minimap…).
- **Undo / redo** — every edit, plus a save history on disk.
- **Install / restore** — the game archives are patched in place with a backup; several modded tracks can be installed at the same time; "Restore archives" puts the original game back.
- Interface in **English, French, Spanish, Italian and German**.

---

## Requirements
- Your **own legally dumped copy** of CTR Nitro-Fueled for PS4 (CUSA13795, update 1.21) running on shadPS4 or CTR-NitroFueled-PC. No game file is included in this repository.
- Windows 10/11. For the source version: Python 3.11+.

## Quick start (Windows app)
1. Run `CTR Track Editor.exe`.
2. On first launch, choose the game's **`archives`** folder from 1.21 Update (it contains `update.pak` and the track archives such as `t111_crash_cove.pak`). The choice is remembered.
3. Follow the 6-step guide on the left: *Remove the old track → Import your map → Create the route → Place objects → Check → Install*.
4. Close shadPS4 or CTR-NitroFueled-PC before installing, then start a race on the track you replaced.

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

**Éditeur de pistes pour Crash Team Racing Nitro-Fueled (PS4 v1.21, CUSA13795) sur l'émulateur shadPS4 et sur le portage PC [CTR-NitroFueled-PC](https://github.com/GetLostIn/CTR-NitroFueled-PC) .**

Importe ta propre map (OBJ / COLLADA), transforme-la en course jouable en quelques clics et installe-la à la place d'une piste du jeu : IA, caisses, boosters, réapparitions, mini-carte, images de menu et même téléporteurs.

**Fonctionnalités**
- **Ta map** : import d'un dossier OBJ / DAE + textures (collision et transparence par matériau, échelle proposée), « Nouvelle map » qui retire l'ancienne piste, allègement de la map.
- **Parcours automatique** depuis la forme de la route : sections, ligne d'arrivée, grille, réapparitions, toutes les splines IA ; routes qui se croisent et **sauts au-dessus des trous** ; choix des morceaux de route dans la vue 3D.
- **Course** : splines IA (édition, génération), zones de transition, grille de départ, caisses `?` et fruits (posées selon la pente), TNT, Nitro, fruits Wumpa, boosters, chutes et réapparitions, **téléporteurs** (le miroir de Spyro Circuit), mini-carte, nom et images de menu, visite virtuelle.
- **Décor** : déplacer / tourner / dupliquer avec la collision qui suit, **bibliothèque de ~2 800 objets** des 47 pistes, textures (y compris images externes), **types de sol** avec vitesse et adhérence réelles, ciel et ambiance d'une autre piste, export Blender.
- **Sécurité** : vérification avant installation et **corrections en un clic**, annuler / rétablir, installation réversible (sauvegarde des archives), plusieurs pistes installées en même temps.
- Interface en **français, anglais, espagnol, italien et allemand**.

**Démarrage** : lance `CTR Track Editor.exe`, choisis le dossier `archives` du jeu, puis suis le guide en 6 étapes. Depuis les sources : `pip install -r requirements.txt` puis `python ctr_tools/editor/server.py` (http://localhost:8765).

Outil de fan, non commercial, sans lien avec Activision, Beenox ou Sony. Aucun fichier du jeu n'est inclus : il faut ta propre copie du jeu.
