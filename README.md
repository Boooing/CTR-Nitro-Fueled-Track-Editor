# CTR Track Editor

**A track editor for Crash Team Racing Nitro-Fueled (PS4, v1.21, CUSA13795), for the [shadPS4](https://github.com/shadps4-emu/shadPS4) emulator and the OCTR PC port.**

Import your own map (OBJ / COLLADA) or **build one from scratch in the editor**, turn it into a playable race in a few clicks, and add it to the game as a **brand new track** or in place of an existing one, with AI opponents, item crates, boosters, respawns, a minimap, menu images, your own music, lights and even teleporters.

> 🇫🇷 Version française plus bas.
>
> This folder holds the editor only. **CTR Track Installer**, the separate app for players, is not part of it.

---

## What's new in v0.6


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
- **Animated objects** (Add › *🎞 Animated object…*): animals, characters, banners, balloons, sails… from other tracks, with an **animated preview**. They are copied into your track when it's installed. Click them in the 3D view to move them, **rotate them on 3 axes** and resize them. Tried in game. 
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

Items marked work in the editor and pass their offline tests, but nobody has confirmed them in a race yet.

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
- Bigger height range (road from -200 m to +300 m), road banking up to 30°, slopes with or without embankment per section, embankment width, smooth blending between ground paints, tilted objects that sit on the slope, "Place the kart" to choose the start. *(partly tried in game)*
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

### Nouveautés de la v0.6
Les points marqués *(pas encore essayé en jeu)* marchent dans l'éditeur et passent leurs tests hors jeu, sans confirmation en course pour l'instant.

- **Eau** : Relief › *💧 Remplir d'eau*, clic au fond d'un trou creusé et il se remplit jusqu'à son bord le plus bas ; niveau réglable (0 à 20 m sous le bord), 5 types d'eau (claire, lagon, marais, sombre, boue). Moins de 1,5 m : on roule au fond ; plus profond : on tombe et on réapparaît sur la route. *(pas encore essayé en jeu)*
- **Le décor automatique ajoute parfois des points d'eau** : 1 à 3 dans des creux du relief, jamais sur la route ; refaits ou retirés avec le décor automatique. *(pas encore essayé en jeu)*
- **Modifier le décor posé dans la Création** : Décor › À la main › *✋ Modifier* : déplacer, **tourner sur les 3 axes**, changer la taille et la hauteur, dupliquer, supprimer. *(rotation 3 axes pas encore essayée en jeu)*
- **Outil Pont** (*🌉 Pont*) : clic sur un croisement, la route cliquée passe au-dessus de l'autre. *(pas encore essayé en jeu)*
- **Outil Bords** : *〰 Lisser entre les extrémités* égalise largeur et relevé entre les deux bouts de la zone ; boutons − / + (et touches) pour réduire ou agrandir la zone, repères blancs à ses extrémités.
- **Paveur** : après un recul, la route reprend la pente et l'inclinaison de la route d'avant (plus de bosse). *Supprimer toute la route* efface aussi les talus de l'ancienne route. Eau affichée opaque dans la vue 3D.
- **Objets animés** (Ajouter › *🎞 Objet animé…*) : animaux, personnages, bannières, ballons, voiles… des autres pistes, avec **aperçu animé**, copiés dans ta piste à l'installation ; sélectionnables dans la vue 3D (déplacer, **tourner sur 3 axes**, taille). Essayé en jeu. *(rotation 3 axes pas encore essayée en jeu)*
- **Aperçus 3D** des bibliothèques d'objets : tourner et zoomer à la souris (double-clic : vue de départ). « Placer au centre de la vue » vise vraiment le centre de l'écran.
- **Packs de maps** : pistes créées affichées avec leur numéro et leur nom de menu (fini les lignes « Custom Map ») ; l'export garde l'inclinaison et les réglages des boosters (ré-exporte les anciens packs).
- **Jeu et installation** : jeu en **un ou deux dossiers** (1.21 complet, ou base + mise à jour à côté, `-UPDATE` / `-patch`) ; **contrôle du ciel** avant l'installation et avant *Tester en jeu* ; *Tester en jeu* lance shadPS4 avec un environnement propre (corrige « point d'entrée ?convertVolume@QAudio… introuvable » sur certains PC).
- **Linux** : l'AppImage est construite automatiquement sur GitHub et jointe à chaque release, et l'éditeur Linux se met maintenant à jour tout seul ; l'onglet Création est inclus dans la version Linux.
- **Corrections** : objets animés invisibles en jeu (certains sont désactivés dans leur piste d'origine, comme les Zam d'Hyper Spaceway) ; chargement sans fin après la suppression d'une zone caméra (fonction expérimentale retirée depuis des menus).
- **Bon à savoir** : pas de ciel et des textures qui laissent des traînées sur une carte graphique **Intel Arc** : c'est l'émulateur, pas l'éditeur (pareil sur les pistes d'origine). Le portage PC OCTR fonctionne.

### Nouveautés de la v0.5
Les points marqués *(pas encore essayé en jeu)* marchent dans l'éditeur et passent leurs tests hors jeu, sans confirmation en course pour l'instant.

- **Mise à jour automatique** : au lancement, l'éditeur propose la nouvelle version publiée sur GitHub, se remplace et redémarre ; sauvegardes, réglages et FFmpeg restent en place. **La v0.4 n'a pas ce mécanisme : installe la v0.5 à la main une fois.**
- **Éditeur plus clair** : icônes au trait, barre d'outils verticale sur la vue 3D, rappels souris dans la barre d'état, onglets dans l'ordre du travail ; panneau **Objets de la scène** (remplace Rechercher) avec tous les objets de la map par catégorie, vignettes 3D, sélection, cacher / afficher et infos ; inspecteur de droite rangé en blocs.
- **Coloriser un objet** (bouton *Coloriser…* de la fiche ou clic droit) : teinte qui garde les détails de la texture ou peinture unie, intensité, aperçu en direct, choix des parties et « tous les objets identiques ». *(pas encore essayé en jeu)*
- **Édition plus rapide sur les grandes maps** : ajouter, coloriser, changer un type de sol... ne recalcule plus toute la collision (environ 2 min sur une grande map) ; elle est refaite une fois à **Enregistrer** (pastille orange), et toujours avant l'installation et la vérification.
- **Onglet Création** : panneau en blocs, Décor en deux onglets (*Automatique* / *À la main*) ; **décor automatique plus intelligent** (styles, quantités par famille, objets empruntés à d'autres thèmes quand le sol n'en a pas, virages dégagés) *(pas encore essayé en jeu)* ; hauteur de route de -200 à +300 m, inclinaison jusqu'à 30°, talus par morceau et largeur réglable, fondu entre peintures du sol, objets posés selon la pente, « Placer le kart » ; retrait des zones loin de la route ; « Générer la piste » propose une **nouvelle piste** par défaut.
- **Course** : caisses orientables, rangées automatiques centrées sur la ligne de course ; **inverser le sens de la course** *(pas encore essayé en jeu)* ; parcours sur routes superposées (spirale) et sauts jusqu'à 80 m, voies IA qui gardent leur largeur *(pas encore essayé en jeu)* ; chutes et réapparitions sur les pistes dont les points sont dans le RaceSystem ; nouvelles pistes du jeu modifiables (Thunder Struck, Out of Time, Electron Avenue...).
- **Jeu et installation** : **restaurer les archives du jeu** (cette piste ou tout le jeu) et **remettre une piste retirée** ; archive des grandes maps plafonnée à ce que le jeu charge, ligne « Mémoire du jeu » dans **Vérifier** ; type de sol **Turbo** retiré (sans effet en jeu : utilise les boosters).
- **Corrections** : chargement sans fin quand une partie autre que la première d'un objet multi-textures avait une texture importée (roche colorisée) ; plantages en quittant une piste, avec trop de voies IA, et après « Tester en jeu » ; zones de chute sur le bord bas des virages inclinés ; erreur d'enregistrement après beaucoup de voies IA ; ciel manquant sur les pistes copiées.

### FFmpeg (seulement pour importer une musique)
[FFmpeg](https://ffmpeg.org/download.html) **n'est pas inclus** dans ce dépôt (trop gros pour GitHub). Tout le reste marche sans lui, y compris jouer des pistes et des packs qui ont déjà leur musique.

L'éditeur le cherche ici, dans l'ordre : le chemin que tu lui as donné, à côté du `.exe`, puis le `PATH` du système. S'il ne le trouve pas, **Piste › Musique de la piste** te le dit et te demande où il est : parcours jusqu'à son dossier ou colle le chemin (son sous-dossier `bin` est aussi regardé). Il doit savoir encoder en MP3 (`libmp3lame`), comme les versions complètes habituelles. Ton choix est retenu.

- Windows : `winget install Gyan.FFmpeg`, ou décompresse une version du site de FFmpeg.
- Linux : `sudo apt install ffmpeg` (ou le paquet de ta distribution).

### Démarrage
Lance `CTR Track Editor.exe`, choisis le dossier `archives` du jeu, puis construis ta piste dans l'onglet **Création**, ou importe ta map (**Fichier › Importer ta map**) et crée le parcours. Depuis les sources : `pip install -r requirements.txt` puis `python ctr_tools/editor/server.py` (http://localhost:8765), ou `python ctr_tools/editor/app.py` pour la fenêtre.

Outil de fan, non commercial, sans lien avec Activision, Beenox ou Sony. Aucun fichier du jeu n'est inclus : il faut ta propre copie du jeu. Un mod OCTR contient, lui, des archives de piste complètes : ne le partage qu'avec des joueurs qui ont le jeu.
