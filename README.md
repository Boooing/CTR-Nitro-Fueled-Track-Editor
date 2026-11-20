# CTR Track Editor

**A track editor for Crash Team Racing Nitro-Fueled (PS4, v1.21, CUSA13795), for the [shadPS4](https://github.com/shadps4-emu/shadPS4) emulator and the OCTR PC port.**

Import your own map (OBJ / COLLADA) or **build one from scratch in the editor**, turn it into a playable race in a few clicks, and add it to the game as a **brand new track** or in place of an existing one, with AI opponents, item crates, boosters, respawns, a minimap, menu images, your own music, lights and even teleporters.

> 🇫🇷 Version française plus bas.
>
> This folder holds the editor only. **CTR Track Installer**, the separate app for players, is not part of it.

---

## What's new in v0.7.5

### Smaller history, same undo
- **The save history (`out/editor/history`) is now stored compactly**: each file content is kept once, compressed, and every step only points to it. Undo, *Go back to this step* and *Remove a step* work as before. On a real set of 31 tracks: **11.3 GB shown / 3.9 GB on disk → 0.77 GB**.
- On first launch after the update, the editor **offers to compress the old history** and shows how much space you get back (only when it is worth it). Old steps stay readable until then, and the conversion is safe if the app is closed in the middle.

### New tools
- **📏 Measure** (left bar, key M): two clicks in the 3D view → distance, horizontal gap, height and slope.
- **Arrange** (several scenery objects selected): *Align*, *Spread evenly*, *Same height*, *Along the road* (same side, same gap, heading relative to the road).
- **📷 Postcard** (Track menu): 6 previews (current view, aerial view framed inside the map, 4 views beside the road like the intro cameras, **↻ Regenerate** for new ones), 1080p / 1440p / 4K, without the editor's markers; one PNG per ticked view in `captures`.
- **Track name and images**: a **📷 Postcard…** button next to each image turns a view of your track into the menu image, at the right size.
- **Live memory gauge** in the status bar (🧠 %), updated as you edit; a click opens *Lighten the map*.

### Check, before installing
- **Check** now also looks at: checkpoints (the lap closes, no checkpoint left unreachable), teleporters (arrival far away, after the next checkpoint, or with no ground), fall zones crossed by the route where the kart drives, crates above the void, and edited AI splines that run into a wall.

### In the 3D view
- **Sky and weather** shown in the editor: the track's sky (or the one picked in Ambiance) and the chosen weather (rain, storm with lightning, snow, blizzard, leaves, fireflies, pollen) around the camera.
- **Display menu tidied up** into folding sections (Track, Scenery and ground, Sky and mood, Performance). New box **Sand ground under the track** (off by default) to hide the large sand plane of the base.
- **Fall, camera and gravity zones can be rotated** (button, *Heading (°)* field, gizmo, key E).

### Fixes
- Created tracks (Custom Track slots) could not be renamed in *Track name and images*: the name field is back (one name for all languages).
- The **Box** select tool of the left bar did nothing on crates and was not shown as active.
- Many texts were still in French in the other languages (gravity buttons, history, tools): full translation pass.
- Postcards no longer show the base's crates, Wumpa fruit, boosters or sand ground.

## What was new in v0.7

### One map, one tab
- **Create and Edit are now a single tab, *Create / Edit*.** The left tool bar holds the **Base** tools (Route, Edges, Bridge, Relief, Paint, Scenery, 🎲 Random) and then the **Edit** tools (Scene, Move, Rotate, Size, Box, Tour, Refresh). You work on one map at a time, whatever the tool.
- **⚙ Generate the track** is a button of the top bar, usable from anywhere. An orange dot shows when the base has changed since the last generation. When only the scenery has changed, it offers **⚡ Apply the scenery** (a few seconds instead of a full generation).
- The base is shown in the Edit view **without generating**: ground, road, water and scenery as they are. Its objects can be picked, moved, rotated, resized, dropped to the ground (G), hidden (H) and box-selected with the Edit tools.
- **Nothing done in Edit is lost when you generate again**: moved, rotated, resized, copied or deleted scenery, **colour, glow texture and reshaped objects**, library objects, imports, crates and boosters are kept and put back on the new ground. Changes that were not saved yet are saved automatically just before the generation starts.
- **Undo / redo (Ctrl+Z / Ctrl+Y) shared** by the base tools and the Edit tools.
- **File › 🆕 New map…** (name and category): an empty track made from a light template, opened on the Route tool.
- **Finishing** page (name and images, minimap, flyover, ambience and weather, road markings, music, times) and **Game** page (Save, Generate, Check, Install, Test, sharing, game settings), lighter menus, a single inspector on the right and status chips (*Not saved*, *To generate*...) in the bottom bar.
- Check, Install, Test and Tour are only offered on a generated map, with the reason shown otherwise. An imported map without a base goes straight to *Create the route* instead of *Generate*.

### Base tools (former Create tab)
- **🎲 Random track** is a tool of its own (bottom of the Base group, also *File › Random track…*): new layouts (angular, hairpins, blocks), hills in the background, optional **crates and boosters** placed along the route, and a number of checkpoints that follows the track length.
- Scenery sorted again from the game's 2,826 models (no more stones mixed with trees, more variety). New family **⤴ Ramps and jumps** in the Scenery tool and in the *By object type* view.
- Scenery › *Modify*: **select several objects** (Shift / Ctrl + click), move or rotate them together, **duplicate them (Ctrl+D)**: the copies become the selection and can be moved right away.
- An object **placed by hand** stays even if it touches the road or stands on a slope (a notice tells you); only objects outside the terrain are left out.
- Sowing under a bridge puts the objects on the ground, not on the road above. Automatic scenery no longer drops objects in the water.
- The *Ramp* piece no longer builds kilometre-long ramps. After erasing road, the paver takes back the angle of the road behind it.
- Earth bridges and tunnels made automatically over deep trenches have been removed.

### Race
- **📍 Add a checkpoint between two** (Add › Race): click two checkpoints that follow each other, a new one is placed halfway between them.
- **🌀 Teleporter checkpoint** (Add): same two clicks, the new checkpoint becomes a teleporter; its arrival is placed before the next checkpoint and can be moved.
- **🪐 Gravity zones** (Add › *Gravity zone at the centre of the view*): low or high gravity inside a box, like Oxide Station.
- **AI lanes**: tighter generation, with a *Width used by the lanes (%)* setting (70 % by default). New tools in Add › Race:
  - **〰 Rework AI lanes**: pull them towards the race line, smooth them, space their points evenly, for all sections or one, with a live preview; *Soft drag* moves the neighbouring points along when you drag one.
  - **✏ Draw AI lanes (top view)**: one section at a time, click a lane and redraw it with the mouse, draw new ones, delete one or **all the lanes of the section**.
  - **🧹 Remove AI lanes far from the route** (lanes left over from an old layout); *Regenerate all AI lanes* removes them too.
- Automatic crate placement with *Replace* also removes the crates planned by the random track.
- Curbs in banked turns sit at the height of the road edge.

### Scenery and objects
- **Animated objects**: they play their animation in game (objects started by a delay script included) and keep the rotation set in the editor. The animation also plays **in the editor's 3D view**, with the path of objects that travel. *Speed ×* setting per object, own category in *Scene objects*, and a new **Check › Animated objects** line (frozen, too slow, floating objects).
- Library models made of several parts are placed at their real height (they no longer float in game).
- Scenery object: **All identical objects** block (same size, same rotation, drop all to the ground, colourise all).
- **✨ Glow texture** on the game's own objects.
- Object library: **⤴ Ramps, jumps and half-pipes** category.
- **Check** shows the estimated game memory load; *Lighten the map* lists the rare models (1 or 2 copies) to remove first.

### Faster saving and generation
Same files as before, produced faster:
- **Collision encoding rewritten and spread over the processor's cores** (up to 8): 21 s → 4.7 s on a 4 km track, 67 s → 18 s on a very big map. A save that doesn't change the collision reuses the previous result.
- **Track generation** no longer rebuilds the collision twice (two passes of about 20 s each removed on a big map).
- **Create the route and generate the AI lanes**: about 3.5 times faster (30.6 s → 8.4 s on a 4 km track, 7 sections).
- Install: weather effects 3.9 s → 1.2 s. Map import: textures encoded in parallel (8 images: 3.8 s → 1.8 s). Opening the models of a big map: 3.8 s → 0.8 s (preview cache).

### Smoother editor (graphics card)
- Identical objects drawn in one go: Crash Cove 5,529 → 916 draw calls per frame (29 → 8.5 ms).
- Animated objects computed by the graphics card.
- Lighter on modest PCs: the view slows down when nothing moves, the resolution lowers itself when frames get slow, the editor recovers by itself when the display is lost, and Display › *Low-end PC mode* lowers it further. No more flickering of the Edit tools on some graphics cards.

### Linux
- Music import from the AppImage: FFmpeg runs with the system's libraries, is also looked for next to the `.AppImage` file, and the Music window shows the install command for your distribution.

### Fixes
- Edit changes (moved object, crate...) lost when clicking *Generate the track*.
- Old crates of a random track staying on the track after placing new ones, or coming back at every generation.
- Crates buried in a sloped road on random tracks.
- Grey collision of the previous map left on screen after switching map.
- Empty right panel after going back and forth between Scenery and Move; animated objects disappearing in the base tools.
- Objects too dark in the editor with a night ambience.

## What was new in v0.6.5

### Create tab
- **🎲 Random track from a code** (Track settings › *Random track (code)…*): pick the theme, the length (1.8 / 2.6 / 3.4 / 4.2 km), the difficulty and which pieces to use, and the editor builds the whole track: layout (shapes inspired by the game's own tracks, figure-eights with a bridge), spirals, chicanes, bumps, jumps, banked turns, canyons and embankments, terrain paint, automatic scenery, water and road markings. The terrain size is picked automatically. **The same code always gives the same track**, so codes can be shared. Everything can be edited afterwards, then *Generate the track* as usual.
- **🧩 Special pieces** (Route › *Pieces* tab): banked turn (angle, radius, banking), spiral (turns, radius, gap between loops), chicane / slalom, jump, bumps, ramp, straight. Added at the end of the road in one click, with a yellow preview (red with the reason when it can't fit). The inner edge of banked pieces stays level with the road and the outer edge rises gently.
- **🖌 Road markings** (Route › *Settings*): edge lines, dashed center line, red and white curbs inside tight turns. Painted on the road without collision.
- The Route column is sorted into 3 tabs (*Driving*, *Pieces*, *Settings*), with a separator under the tool buttons.
- Bigger, curved jump ramp (5 m over 30 m).
- Automatic scenery: more varied, objects no longer overlap, ponds at least 5 m below their edge.
- Trimming the far terrain: smooth edge, bands of ground kept towards far objects and water.
- Barriers now touch the road (no more gap).

### Edit tab
- **🌦 Weather** (Ambience › *Weather*): rain, thunderstorm (Tiger Temple), snow, blizzard (Blizzard Bluff), falling leaves, pollen (Coco Park), fireflies (Mystery Caves), in 3 densities. The game's own effects are placed along the saved route at install.
- **🖌 Road markings on any map** (Map finishing › *Road markings…*): road width measured on the collision, or a fixed width when the road and its shoulders have the same ground.
- *Falls and respawns*: no more fall zones under bridges or a raised road.

### Track / category tab
- **🏁 1 or 2 lap races**: adds 1 and 2 to the lap choice of the race settings (also offered in the OCTR export, offline only). Not compatible with an OCTR mod that ships its own `update3.pak` (Nurburgring…).

### Fixes
- Switching map with the Create tab open: Create kept the old map's draft and the Edit view then stayed empty / grey, even after *Refresh*.
- Reversing on a spiral or another piece put the kart under the road.
- The Linux 0.6 AppImage was missing the Create tab (`creator.js`).
- Automatic scenery could take minutes when the map had water.

## What was new in v0.6

### Create tab
- **Water**: Relief › *💧 Fill with water*, click at the bottom of a dug hole and it fills up to its lowest edge. Adjustable level (0 to 20 m below the edge) and 5 water types (clear, lagoon, swamp, dark, mud). Shallow water (under 1.5 m): you drive on the bottom; deeper: you fall and respawn on the road.
- **Automatic scenery adds ponds** now and then: 1 to 3 water spots in hollows of the terrain, never on the road; they are regenerated or removed with the automatic scenery.
- **Edit scenery placed in Create**: Scenery › By hand › *✋ Modify*: click an object to move it, **rotate it on all 3 axes**, resize it, raise or lower it, duplicate or delete it.
- **Bridge tool** (*🌉 Bridge*): click where two roads cross, the clicked road rises above the other.
- **Edges tool**: *〰 Smooth between the ends* evens out width and raise between the two ends of the selected zone; − / + buttons (and keys) to shrink or enlarge the zone, white markers at its ends.
- **Paver**: after reversing, the road picks up the slope and banking of the road behind it again (no more bump).
- *Delete the whole road* also removes the embankments the old road had made in the ground.
- Water is drawn opaque in the 3D view (painted grass under it no longer turns it green).

### Edit tab
- **Animated objects** (Add › *🎞 Animated object…*): animals, characters, banners, balloons, sails… from other tracks, with an **animated preview**. They are copied into your track when it's installed. Click them in the 3D view to move them, **rotate them on 3 axes** and resize them.
- The 3D previews of the object libraries can be **rotated and zoomed with the mouse** (double-click: back to the start view).
- "Place at the centre of the view" now aims at what is really at the centre of the screen.
- Map packs: created tracks are listed with their number and menu name (no more rows of "Custom Map").
- Pack export keeps the boosters' tilt and settings (re-export older packs).

### Game and install
- **Game in one or two folders**: a single 1.21 folder, or the base game with its update next to it (`-UPDATE` / `-patch`).
- **Sky check** before installing and before *Test in game* (the sky model, its materials and textures must be declared and present).
- *Test in game*: shadPS4 is started with a clean environment (fixes the error "entry point ?convertVolume@QAudio… not found" on some PCs).
- **Linux**: the AppImage is built automatically on GitHub and attached to each release, and the Linux editor now updates itself too. The Linux build script now includes the Create tab.

### Fixes
- Animated objects that stayed invisible in game (some come disabled from their own track, e.g. the Zams of Hyper Spaceway).
- Infinite loading after removing a camera zone (an experimental feature since removed from the menus).

### Good to know
- No sky and textures smearing across the screen, on **Intel Arc** graphics: that's the emulator, not the editor (it happens on the game's own tracks too). The OCTR PC port works.

## What was new in v0.5

### Automatic updates
- The editor checks GitHub at launch and offers the new version; it replaces itself and restarts. Your saves, settings and FFmpeg stay in place. **v0.4 has no updater: install v0.5 by hand once.**

### A clearer editor
- New look: line icons, a vertical tool bar on the 3D view, mouse hints in the status bar, tabs in work order (Create, Edit, Track / category).
- **Scene objects** panel (replaces Search): every object of the map by category (scenery by model, invisible walls, lights, crates, boosters, fall zones), with 3D thumbnails, select, show / hide and details.
- The right-hand inspector is laid out in blocks (Position, Tool, Actions...) for scenery, crates, boosters, splines, grid, finish line, lights.
- **Colorize an object** (Edit › select › *Colorize…*, or right-click): tint that keeps the texture's details, or flat paint, with intensity and live preview; parts of the object and "all identical objects" can be chosen.
- **Faster editing on big maps**: adding objects, colouring, changing a ground type... no longer rebuilds the whole collision each time (about 2 minutes on a big map). It is rebuilt once, on **Save** (orange dot on the button), and always before installing or checking.

### Create tab
- New panel in blocks, Scenery in two tabs (*Automatic* / *By hand*).
- **Smarter automatic scenery**: styles (balanced, nature, clear, wild, built), amount per family, objects borrowed from other themes when the ground has no matching object, corners kept clear.
- Bigger height range (road from -200 m to +300 m), road banking up to 30°, slopes with or without embankment per section, embankment width, smooth blending between ground paints, tilted objects that sit on the slope, "Place the kart" to choose the start.
- Parts of the map far from the road can be trimmed at generation (lighter map).
- "Generate the track" now offers a **new track** by default, so nobody overwrites Crash Cove by mistake.

### Race
- **Rotatable crates**, automatic crate rows centred on the race line.
- **Reverse the race direction** (or one spline).
- Better route detection on stacked roads (spirals, 3 levels) and jumps up to 80 m; AI lanes that keep their width where road pieces overlap.
- Falls and respawns work on tracks whose respawn points are in the RaceSystem (Star Circuit, Slide Coliseum, Turbo Track...).
- More game tracks can be edited (Thunder Struck, Out of Time, Electron Avenue and the tracks whose race line is in the _Design).

### Game and install
- **Restore the game's archives**: this track or the whole game; **put back a track** removed by a full restore.
- Big maps: track archive capped to what the game can load (textures reduced if needed), "Game memory" line in **Check**, lighter collision for far scenery.
- The ground type **Turbo** is removed (it had no effect in game; use boosters).

### Fixes
- Infinite loading when an object with several textures had a custom texture on a part other than the first one (e.g. a colourised rock).
- Crash when leaving a track after a race (object reference counts), crash after loading with too many AI lanes (copies installed with 6 lanes per section at most), "Test in game" crash after the title-screen patch.
- Fall zones that triggered on the low edge of banked corners.
- Save error after re-creating many AI lanes on a big track; missing sky on copied tracks; "unexpected title-screen script" on another PC.

---

## Requirements
- Your **own legally dumped copy** of CTR Nitro-Fueled for PS4 (CUSA13795, update 1.21), on shadPS4 or the OCTR PC port. No game file is included in this repository.
- Windows 10/11 (`.exe`) or Linux x86_64 / aarch64. For the source version: Python 3.11+.
- **FFmpeg, only to import music** (see below).

## FFmpeg (only for importing music)
[FFmpeg](https://ffmpeg.org/download.html) is **not included** in this repository (too large for GitHub) and is only needed to **import** a song. Everything else works without it, including playing tracks and packs that already contain music.

The editor looks for it in this order: the path you gave it, next to the `.exe` (Linux: next to the `.AppImage` file), then your system `PATH`. If it isn't found, **Track › Track music** tells you and asks where it is: browse to its folder or paste the path (its `bin` subfolder is checked too). It must support MP3 encoding (`libmp3lame`), as the usual full builds do. Your choice is remembered.

- Windows: `winget install Gyan.FFmpeg`, or unzip a build from the FFmpeg site.
- Linux: `sudo apt install ffmpeg` (or your distribution's package).

## Quick start (Windows app)
1. Run `CTR Track Editor.exe`.
2. On first launch, choose the game's **`archives`** folder from the 1.21 update (it contains `update.pak` and the track archives such as `t111_crash_cove.pak`). The choice is remembered.
3. Build a track with the **Base** tools of the left bar (or *File › Random track…*) and click **⚙ Generate the track**, or bring your own map: *File › Import*, then *Create the route*. Place objects, **Check**, **Install in the game**.
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
| `ctr_tools/editor/` | `server.py` (local HTTP API), `index.html` (three.js editor), `i18n.js` (translations), `creator.js` (Base tools), `octr_export.py` (OCTR mods), `mappack.py` (map packs), `app.py` (desktop app), `build_exe.py`, `build_appimage.py` |
| `ctr_tools/igz.py` | Reader / writer for Alchemy `.igz` files (fixups, handles, deep clone, cross-file entity import, compaction) |
| `ctr_tools/pak_tool.py`, `game_restore.py` | `.pak` archives (IGA v13, LZMA): extract, patch in place, backups, full restore |
| `ctr_tools/track_clone.py`, `custom_category.py` | New tracks (renamed copy, hashes rebuilt) and the game's race menu |
| `ctr_tools/havok*.py`, `cms_codec.py`, `collision*.py` | Havok collision: compressed-mesh decoder / encoder, compound instances; `havok_anim.py` decodes skeletal animations (animated object preview) |
| `ctr_tools/animated.py` | Animated objects: catalog of the game's animated actors, copy into a track with their scripts, skins and animations |
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

### Nouveautés de la v0.7.5

- **Historique plus léger, mêmes annulations** : l'historique des enregistrements (`out/editor/history`) est rangé de façon compacte (chaque contenu gardé une seule fois, compressé ; chaque étape y renvoie). Annuler, *Revenir à cette étape* et *Retirer une étape* marchent comme avant. Sur 31 pistes réelles : **11,3 Go affichés / 3,9 Go sur le disque → 0,77 Go**. Au premier lancement après la mise à jour, l'éditeur **propose de compresser l'ancien historique** en montrant la place gagnée ; l'ancien format reste lisible d'ici là, et la conversion ne perd rien si l'appli est fermée en cours.
- **Nouveaux outils** : **📏 Mesure** (barre de gauche, touche M : distance, écart horizontal, hauteur, pente) ; **Disposer** pour plusieurs objets du décor (*Aligner*, *Répartir*, *Même hauteur*, *Le long de la route*) ; **📷 Carte postale** (menu Piste : 6 aperçus — vue actuelle, vue aérienne cadrée dans la map, 4 vues au bord de la route comme les caméras d'intro, **↻ Régénérer** — en 1080p / 1440p / 4K, sans les repères de l'éditeur, une image par vue cochée dans `captures`) ; bouton **📷 Carte postale…** à côté de chaque image dans *Nom et images* pour en faire l'image du menu ; **jauge mémoire en direct** (🧠 %) dans la barre d'état.
- **Vérifier** contrôle aussi : checkpoints (le tour se referme, aucun checkpoint inatteignable), téléporteurs (arrivée trop loin, après le checkpoint suivant ou sans sol), zones de chute traversées par le parcours là où le kart roule, caisses au-dessus du vide, splines IA modifiées qui touchent un mur.
- **Vue 3D** : **ciel et météo** affichés dans l'éditeur (ciel de la piste ou celui d'Ambiance ; pluie, orage avec éclairs, neige, tempête, feuilles, lucioles, pollen). **Menu Affichage rangé** en rubriques repliables (Piste, Décor et sol, Ciel et ambiance, Performances) ; nouvelle case **Sol sable sous la piste** (décochée de base). **Zones de chute, de caméra et de gravité orientables** (bouton, champ *Cap (°)*, poignée, touche E).
- **Corrections** : nom des pistes créées impossible à changer dans *Nom et images* (champ unique pour toutes les langues) ; outil **Cadre** de la barre de gauche sans effet sur les caisses et pas allumé ; textes restés en français dans les autres langues (boutons de gravité, historique, outils) ; caisses, fruits Wumpa, boosters et sol sable de la base visibles sur les cartes postales.

### Nouveautés de la v0.7

- **Une map, un onglet** : Création et Édition ne font plus qu'un onglet, *Création / Édition*. Barre de gauche : outils de **Base** (Route, Bords, Pont, Relief, Peinture, Décor, 🎲 Aléatoire) puis outils d'**Édition** (Scène, Déplacer, Tourner, Taille, Cadre, Visite, Actualiser).
- **⚙ Générer la piste** est un bouton de la barre du haut, utilisable partout ; pastille orange quand la base a changé ; **⚡ Appliquer le décor** quand seul le décor a changé (quelques secondes). La base est visible dans l'Édition **sans générer**, et ses objets se manipulent avec les outils de l'Édition (déplacer, tourner, taille, cadre, poser au sol G, cacher H).
- **Rien de ce qui est fait dans l'Édition n'est perdu en regénérant** : décor déplacé, tourné, agrandi, copié ou supprimé, **couleur, texture lumineuse et forme modifiée**, objets de la bibliothèque, imports, caisses et boosters sont gardés et reposés sur le nouveau sol. Les modifications pas encore enregistrées le sont automatiquement juste avant la génération. **Ctrl+Z / Ctrl+Y communs** aux outils de base et d'Édition.
- **Fichier › 🆕 Nouvelle map…** (nom et catégorie) : piste vide faite depuis un modèle léger. Pages **Habillage** (nom et images, mini-carte, survol, ambiance et météo, marquage, musique, temps) et **Jeu** (Enregistrer, Générer, Vérifier, Installer, Tester, partager, réglages), menus allégés, inspecteur unique à droite, pastilles d'état en bas. Vérifier / Installer / Tester / Visite seulement sur une map générée ; une map importée sans base va directement à *Créer le parcours*.
- **Outils de base** : **🎲 Piste aléatoire** devenue un outil (nouveaux tracés : anguleux, épingles, blocs ; collines au loin ; **caisses et boosters** en option ; nombre de points de passage selon la longueur). Décor reclassé à partir des 2 826 modèles du jeu, nouvelle famille **⤴ Rampes et tremplins**. Décor › *Modifier* : **sélection de plusieurs objets** (Maj / Ctrl + clic), déplacer ou tourner ensemble, **dupliquer (Ctrl+D)** avec les copies sélectionnées. **Un objet placé à la main reste posé** même s'il touche la route ou une pente. Semer sous un pont pose au sol ; plus d'objets du décor automatique dans l'eau ; pièce *Rampe* corrigée (rampes géantes) ; le paveur reprend l'angle de la route après un effacement ; ponts de terre et tunnels automatiques retirés.
- **Course** : **📍 Ajouter un checkpoint entre deux** (Ajouter › Parcours : clic sur deux checkpoints qui se suivent) et **🌀 Checkpoint téléporteur** (Ajouter) ; **🪐 zones de gravité** (comme Oxide Station). **Voies IA** plus resserrées (réglage *Largeur occupée par les voies*, 70 % par défaut) et nouveaux outils : **〰 Retoucher les splines IA** (resserrer, lisser, espacer, déplacement doux), **✏ Dessiner les splines IA (vue du dessus)** par section (redessiner, ajouter, supprimer une voie ou **toutes celles de la section**), **🧹 Retirer les splines IA éloignées du parcours**. Le placement automatique des caisses avec *Remplacer* retire aussi celles prévues par la piste aléatoire. Vibreurs des virages relevés à la hauteur du bord.
- **Décor et objets** : **objets animés** animés en jeu (scripts à retardement compris) avec la rotation de l'éditeur ; animation visible **dans la vue 3D de l'éditeur** avec le trajet des objets qui se déplacent ; réglage *Vitesse ×* ; catégorie dans *Objets de la scène* ; ligne **Vérifier › Objets animés**. Modèles en plusieurs pièces posés à leur vraie hauteur (plus d'objets en l'air). Bloc **Tous les mêmes objets** (même taille, même rotation, tous au sol, tous colorisés). **✨ Texture lumineuse** sur les objets du jeu. Catégorie **⤴ Rampes, tremplins et half-pipes** dans la bibliothèque. Charge mémoire estimée dans **Vérifier**, modèles rares dans *Alléger la map*.
- **Enregistrement et génération plus rapides** (mêmes fichiers qu'avant, faits plus vite) :
  - **encodage de la collision réécrit et réparti sur les cœurs du processeur** (jusqu'à 8) : 21 s → 4,7 s sur une piste de 4 km, 67 s → 18 s sur une très grande map ; un enregistrement qui ne change pas la collision reprend le calcul précédent ;
  - **génération de la piste** sans double recalcul de la collision (deux passes d'environ 20 s en moins sur une grande map) ;
  - **création du parcours et des voies IA** environ 3,5 fois plus rapide (30,6 s → 8,4 s sur une piste de 4 km, 7 sections) ;
  - installation : météo 3,9 s → 1,2 s ; import de map : textures encodées en parallèle (8 images : 3,8 s → 1,8 s) ; ouverture des modèles d'une grande map : 3,8 s → 0,8 s.
- **Éditeur plus fluide** (carte graphique) : objets identiques dessinés en une fois (Crash Cove : 5 529 → 916 appels de dessin, 29 → 8,5 ms par image) ; objets animés calculés par la carte graphique ; PC modestes : vue ralentie quand rien ne bouge, résolution qui baisse seule si les images ralentissent, reprise automatique si l'affichage est perdu, case *Mode PC modeste* ; plus de scintillement des outils d'Édition sur certaines cartes graphiques.
- **Linux** : import de musique depuis l'AppImage (FFmpeg lancé avec les bibliothèques du système, cherché aussi à côté du fichier `.AppImage`, commande d'installation de ta distribution affichée).
- **Corrections** : modifications de l'Édition (objet déplacé, caisse...) perdues en cliquant *Générer la piste* ; anciennes caisses d'une piste aléatoire qui restaient ou revenaient à chaque génération ; caisses enfoncées dans une route en pente (piste aléatoire) ; collision grise de la map précédente après un changement de map ; panneau de droite vide après des allers-retours Décor / Déplacer ; objets animés qui disparaissaient dans les outils de base ; objets trop sombres dans l'éditeur avec une ambiance de nuit.

### Nouveautés de la v0.6.5

- **🎲 Piste aléatoire à partir d'un code** (Réglages de la piste › *Piste aléatoire (code)…*) : choisis le thème, la longueur (1,8 / 2,6 / 3,4 / 4,2 km), la difficulté et les pièces, l'éditeur crée toute la piste : tracé (formes inspirées des pistes du jeu, huits avec pont), spirales, chicanes, bosses, sauts, virages relevés, canyons et remblais, peinture du sol, décor automatique, eau et marquage. La taille du terrain est choisie toute seule. **Le même code redonne toujours la même piste** : les codes se partagent. Tout se retouche ensuite, puis *Générer la piste* comme d'habitude.
- **🧩 Pièces spéciales** (Route › onglet *Pièces*) : virage relevé (angle, rayon, inclinaison), spirale (tours, rayon, écart entre les boucles), chicane / slalom, saut, bosses, rampe, ligne droite. Ajoutées au bout de la route en un clic, avec aperçu jaune (rouge, avec la raison, si elles ne passent pas). Le bord intérieur des pièces inclinées reste à hauteur de route, l'extérieur monte en douceur.
- **🖌 Marquage au sol** (Route › *Réglages*) : lignes de bord, ligne centrale en tirets, vibreurs rouges et blancs à l'intérieur des virages serrés ; peint sur la route, sans collision.
- Colonne Route rangée en 3 onglets (*Conduite*, *Pièces*, *Réglages*), séparateur sous les boutons d'outils. Tremplin des sauts plus grand et courbe (5 m sur 30 m). Décor automatique plus varié, sans objets qui se rentrent dedans, eau au moins 5 m sous le bord. Découpe du terrain lointain au bord lisse, avec des bandes de sol vers les objets et l'eau éloignés. Barrières collées à la route.
- **🌦 Météo** (Ambiance › *Météo*) : pluie, orage (Tiger Temple), neige, tempête de neige (Blizzard Bluff), feuilles qui tombent, pollen (Coco Park), lucioles (Mystery Caves), 3 densités ; effets du jeu posés le long du parcours enregistré à l'installation.
- **🖌 Marquage au sol sur n'importe quelle map** (Finitions de la map › *Marquage au sol…*) : largeur de route mesurée sur la collision, ou largeur fixe quand la route et ses bas-côtés ont le même sol. *Chutes et réapparitions* : plus de zones de chute sous les ponts ou une route en hauteur.
- **🏁 Courses de 1 ou 2 tours** (onglet Piste / catégorie) : ajoute 1 et 2 au choix des tours des réglages de course (aussi proposé à l'export OCTR, hors ligne seulement). Incompatible avec un mod OCTR qui a son propre `update3.pak` (Nurburgring…).
- **Corrections** : changement de map avec l'onglet Création ouvert (la Création gardait le brouillon de l'ancienne map, puis la vue Édition restait vide / grise, même après *Actualiser*) ; kart sous la route en reculant sur une spirale ou une autre pièce ; onglet Création absent de l'AppImage Linux 0.6 ; décor automatique qui pouvait durer plusieurs minutes avec de l'eau.

### Nouveautés de la v0.6
- **Eau** : Relief › *💧 Remplir d'eau*, clic au fond d'un trou creusé et il se remplit jusqu'à son bord le plus bas ; niveau réglable (0 à 20 m sous le bord), 5 types d'eau (claire, lagon, marais, sombre, boue). Moins de 1,5 m : on roule au fond ; plus profond : on tombe et on réapparaît sur la route.
- **Le décor automatique ajoute parfois des points d'eau** : 1 à 3 dans des creux du relief, jamais sur la route ; refaits ou retirés avec le décor automatique.
- **Modifier le décor posé dans la Création** : Décor › À la main › *✋ Modifier* : déplacer, **tourner sur les 3 axes**, changer la taille et la hauteur, dupliquer, supprimer.
- **Outil Pont** (*🌉 Pont*) : clic sur un croisement, la route cliquée passe au-dessus de l'autre.
- **Outil Bords** : *〰 Lisser entre les extrémités* égalise largeur et relevé entre les deux bouts de la zone ; boutons − / + (et touches) pour réduire ou agrandir la zone, repères blancs à ses extrémités.
- **Paveur** : après un recul, la route reprend la pente et l'inclinaison de la route d'avant (plus de bosse). *Supprimer toute la route* efface aussi les talus de l'ancienne route. Eau affichée opaque dans la vue 3D.
- **Objets animés** (Ajouter › *🎞 Objet animé…*) : animaux, personnages, bannières, ballons, voiles… des autres pistes, avec **aperçu animé**, copiés dans ta piste à l'installation ; sélectionnables dans la vue 3D (déplacer, **tourner sur 3 axes**, taille).
- **Aperçus 3D** des bibliothèques d'objets : tourner et zoomer à la souris (double-clic : vue de départ). « Placer au centre de la vue » vise vraiment le centre de l'écran.
- **Packs de maps** : pistes créées affichées avec leur numéro et leur nom de menu (fini les lignes « Custom Map ») ; l'export garde l'inclinaison et les réglages des boosters (ré-exporte les anciens packs).
- **Jeu et installation** : jeu en **un ou deux dossiers** (1.21 complet, ou base + mise à jour à côté, `-UPDATE` / `-patch`) ; **contrôle du ciel** avant l'installation et avant *Tester en jeu* ; *Tester en jeu* lance shadPS4 avec un environnement propre (corrige « point d'entrée ?convertVolume@QAudio… introuvable » sur certains PC).
- **Linux** : l'AppImage est construite automatiquement sur GitHub et jointe à chaque release, et l'éditeur Linux se met maintenant à jour tout seul ; l'onglet Création est inclus dans la version Linux.
- **Corrections** : objets animés invisibles en jeu (certains sont désactivés dans leur piste d'origine, comme les Zam d'Hyper Spaceway) ; chargement sans fin après la suppression d'une zone caméra (fonction expérimentale retirée depuis des menus).
- **Bon à savoir** : pas de ciel et des textures qui laissent des traînées sur une carte graphique **Intel Arc** : c'est l'émulateur, pas l'éditeur (pareil sur les pistes d'origine). Le portage PC OCTR fonctionne.

### Nouveautés de la v0.5
- **Mise à jour automatique** : au lancement, l'éditeur propose la nouvelle version publiée sur GitHub, se remplace et redémarre ; sauvegardes, réglages et FFmpeg restent en place. **La v0.4 n'a pas ce mécanisme : installe la v0.5 à la main une fois.**
- **Éditeur plus clair** : icônes au trait, barre d'outils verticale sur la vue 3D, rappels souris dans la barre d'état, onglets dans l'ordre du travail ; panneau **Objets de la scène** (remplace Rechercher) avec tous les objets de la map par catégorie, vignettes 3D, sélection, cacher / afficher et infos ; inspecteur de droite rangé en blocs.
- **Coloriser un objet** (bouton *Coloriser…* de la fiche ou clic droit) : teinte qui garde les détails de la texture ou peinture unie, intensité, aperçu en direct, choix des parties et « tous les objets identiques ».
- **Édition plus rapide sur les grandes maps** : ajouter, coloriser, changer un type de sol... ne recalcule plus toute la collision (environ 2 min sur une grande map) ; elle est refaite une fois à **Enregistrer** (pastille orange), et toujours avant l'installation et la vérification.
- **Onglet Création** : panneau en blocs, Décor en deux onglets (*Automatique* / *À la main*) ; **décor automatique plus intelligent** (styles, quantités par famille, objets empruntés à d'autres thèmes quand le sol n'en a pas, virages dégagés) ; hauteur de route de -200 à +300 m, inclinaison jusqu'à 30°, talus par morceau et largeur réglable, fondu entre peintures du sol, objets posés selon la pente, « Placer le kart » ; retrait des zones loin de la route ; « Générer la piste » propose une **nouvelle piste** par défaut.
- **Course** : caisses orientables, rangées automatiques centrées sur la ligne de course ; **inverser le sens de la course** ; parcours sur routes superposées (spirale) et sauts jusqu'à 80 m, voies IA qui gardent leur largeur ; chutes et réapparitions sur les pistes dont les points sont dans le RaceSystem ; nouvelles pistes du jeu modifiables (Thunder Struck, Out of Time, Electron Avenue...).
- **Jeu et installation** : **restaurer les archives du jeu** (cette piste ou tout le jeu) et **remettre une piste retirée** ; archive des grandes maps plafonnée à ce que le jeu charge, ligne « Mémoire du jeu » dans **Vérifier** ; type de sol **Turbo** retiré (sans effet en jeu : utilise les boosters).
- **Corrections** : chargement sans fin quand une partie autre que la première d'un objet multi-textures avait une texture importée (roche colorisée) ; plantages en quittant une piste, avec trop de voies IA, et après « Tester en jeu » ; zones de chute sur le bord bas des virages inclinés ; erreur d'enregistrement après beaucoup de voies IA ; ciel manquant sur les pistes copiées.

### FFmpeg (seulement pour importer une musique)
[FFmpeg](https://ffmpeg.org/download.html) **n'est pas inclus** dans ce dépôt (trop gros pour GitHub). Tout le reste marche sans lui, y compris jouer des pistes et des packs qui ont déjà leur musique.

L'éditeur le cherche ici, dans l'ordre : le chemin que tu lui as donné, à côté du `.exe` (Linux : à côté du fichier `.AppImage`), puis le `PATH` du système. S'il ne le trouve pas, **Piste › Musique de la piste** te le dit et te demande où il est : parcours jusqu'à son dossier ou colle le chemin (son sous-dossier `bin` est aussi regardé). Il doit savoir encoder en MP3 (`libmp3lame`), comme les versions complètes habituelles. Ton choix est retenu.

- Windows : `winget install Gyan.FFmpeg`, ou décompresse une version du site de FFmpeg.
- Linux : `sudo apt install ffmpeg` (ou le paquet de ta distribution).

### Démarrage
Lance `CTR Track Editor.exe`, choisis le dossier `archives` du jeu, puis construis ta piste avec les outils de **Base** de la barre de gauche (ou *Fichier › Piste aléatoire…*) et clique **⚙ Générer la piste**, ou importe ta map (**Fichier › Importer**) et crée le parcours. Depuis les sources : `pip install -r requirements.txt` puis `python ctr_tools/editor/server.py` (http://localhost:8765), ou `python ctr_tools/editor/app.py` pour la fenêtre.

Outil de fan, non commercial, sans lien avec Activision, Beenox ou Sony. Aucun fichier du jeu n'est inclus : il faut ta propre copie du jeu. Un mod OCTR contient, lui, des archives de piste complètes : ne le partage qu'avec des joueurs qui ont le jeu.
