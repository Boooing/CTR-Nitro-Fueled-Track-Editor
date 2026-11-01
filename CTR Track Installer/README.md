# CTR Track Installer

**Install custom tracks into Crash Team Racing Nitro-Fueled (PS4, v1.21, CUSA13795), played on the [shadPS4](https://github.com/shadps4-emu/shadPS4) emulator, without using the editor.**

It installs map packs (`.zip` files exported by **CTR Track Editor**), organises the game's race menu, and can put the game back to its original state at any time.

> 🇫🇷 Version française plus bas.

---

## Features
- **Install one or several map packs at once.** For each map, choose:
  - a **new track in a new category** (you type the category name),
  - a **new track in an existing category**,
  - or **replace a track** (a game track or a track created earlier).

  A new track is added next to the game's tracks: nothing is replaced.
- **Track / category tab**: create, rename, reorder and delete categories; move tracks between categories, create a blank track, delete a created track. *Save menu* installs the new menu.
- **Backup tab**: list of installed maps (by the installer or the editor), uninstall a map, and **Restore the original game**. It first shows everything that will be removed (installed maps, created tracks, categories), then asks for confirmation.
- Interface in **English, French, Spanish, Italian and German**.

## Usage
1. Close shadPS4.
2. Run `CTR Track Installer` and choose the game's **`archives`** folder from the 1.21 update (it contains `update.pak` and `t111_crash_cove.pak`). The choice is remembered.
3. **Install maps** tab: add one or several `.zip` packs, choose where each map goes, then click **Install**. Count 1 to 5 minutes per map.
4. Start shadPS4 and pick your track in the race menu.

## Backups
Each modified archive keeps its original header and size next to it (`<archive>.ctrmod.json` and `.ctrmod.toc`), so there is no copy of the 9 GB of archives. `chunks.igx.ctrmod` (game root) and the menu videos set aside (`.bk2.ctrmod-off`) are restored as well. If the game was reinstalled or updated in the meantime, the affected archives are reported and left untouched.

The list of installed tracks (`ctr_installed_tracks.json`, next to the archives) is shared with CTR Track Editor: both apps can be used on the same game without undoing each other's tracks.

Settings and the working folder are in `data/` next to the app. Keep it: reinstalls use it.

## Requirements
- Your **own legally dumped copy** of CTR Nitro-Fueled for PS4 (CUSA13795, update 1.21) running on shadPS4. No game file is included.
- Windows 10/11 or Linux x86_64. To run from source: Python 3.10+.

## Run from source
This folder is part of the CTR Track Editor repository: the engine is the `ctr_tools` folder at the repository root (shared with the editor).
```bash
pip install -r requirements.txt
python src/ctr_track_installer.py
```
Linux: Tk is required (`sudo apt install python3-tk` on Debian / Ubuntu, `sudo dnf install python3-tkinter` on Fedora).

## Build the app
```bash
pip install -r requirements.txt
python build.py
```
- **Windows**: `Windows/CTR Track Installer.exe` (+ `_internal`).
- **Linux**: `Linux/CTR Track Installer` (+ `_internal`). Build it **on Linux**: PyInstaller only builds for the system it runs on.

## Project layout
| Path | Content |
|---|---|
| `src/ctr_track_installer.py` | The app (Tkinter) |
| `build.py` | Windows / Linux build (PyInstaller, one folder) |
| `../ctr_tools/` | Engine shared with CTR Track Editor (repository root): `editor/server.py` (install, menu, registry), `editor/mappack.py` (map packs), `game_restore.py` (restore), `track_clone.py` and `custom_category.py` (new tracks, race menu), `pak_tool.py` (game archives), `igz.py` (game files) and the modules they use |
| `../ctr_tools/editor/i18n.js` | Translations (same dictionary as the editor) |
| `../ctr_tools/schema/ctr_meta.json` | Class schema of the game files |

## Disclaimer
Fan-made, non-commercial modding tool. Not affiliated with or endorsed by Activision, Beenox or Sony. Crash Team Racing and all related assets are the property of their respective owners. Use only with a copy of the game you own.

Third-party: NumPy, Pillow, PyInstaller.

---

## 🇫🇷 Version française

**Installe des pistes perso dans Crash Team Racing Nitro-Fueled (PS4 v1.21, CUSA13795) sur l'émulateur shadPS4, sans passer par l'éditeur.**

Il installe les packs de maps (`.zip` exportés par **CTR Track Editor**), range le menu des courses du jeu et peut remettre le jeu d'origine à tout moment.

### Fonctionnalités
- **Installe un ou plusieurs packs à la fois.** Pour chaque map, au choix :
  - **nouvelle piste dans une nouvelle catégorie** (nom à saisir),
  - **nouvelle piste dans une catégorie existante**,
  - ou **remplacer une piste** (du jeu ou déjà créée).

  Une nouvelle piste s'ajoute à côté de celles du jeu : rien n'est remplacé.
- **Onglet Piste / catégorie** : créer, renommer, ordonner et supprimer des catégories ; déplacer des pistes, créer une piste vierge, supprimer une piste créée. *Enregistrer le menu* l'installe.
- **Onglet Sauvegarde** : maps installées (par l'installateur ou l'éditeur), désinstaller une map, **Remettre le jeu d'origine** (affiche d'abord tout ce qui sera supprimé, puis demande confirmation).
- Interface en **français, anglais, espagnol, italien et allemand**.

### Utilisation
1. Ferme shadPS4.
2. Lance `CTR Track Installer` et choisis le dossier **`archives`** du jeu (mise à jour 1.21 : il contient `update.pak` et `t111_crash_cove.pak`). Le choix est mémorisé.
3. Onglet **Installer des maps** : ajoute un ou plusieurs `.zip`, choisis où va chaque map, puis **Installer**. Compte 1 à 5 minutes par map.
4. Lance shadPS4 et choisis ta piste dans le menu des courses.

### Sauvegardes
Chaque archive modifiée garde à côté d'elle son en-tête et sa taille d'origine (`<archive>.ctrmod.json` et `.ctrmod.toc`) : pas de copie des 9 Go d'archives. `chunks.igx.ctrmod` (racine du jeu) et les vidéos du menu mises de côté (`.bk2.ctrmod-off`) sont remis aussi. Si le jeu a été réinstallé ou mis à jour entre-temps, les archives concernées sont signalées et laissées telles quelles.

Le registre des pistes installées (`ctr_installed_tracks.json`, à côté des archives) est commun avec CTR Track Editor : les deux applications peuvent servir sur le même jeu sans s'effacer.

Réglages et dossier de travail : `data/` à côté de l'application (à garder, les réinstallations s'en servent).

### Depuis les sources
Le moteur est le dossier `ctr_tools` à la racine du dépôt (commun avec l'éditeur). `pip install -r requirements.txt` puis `python src/ctr_track_installer.py`. Construire l'application : `python build.py` (Windows → `Windows/`, Linux → `Linux/`, à construire sous Linux ; Tk requis : `python3-tk` / `python3-tkinter`).

Outil de fan, non commercial, sans lien avec Activision, Beenox ou Sony. Aucun fichier du jeu n'est inclus : il faut ta propre copie du jeu.
