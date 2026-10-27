# ctr_tools — outils de modding pistes pour CTR Nitro-Fueled (PS4, v1.21)

Python 3.11. Capstone (désassembleur, `pip install capstone`, ou copie locale dans `pylib/`) : seulement pour
`extract_meta.py`.

| Script | Rôle |
|---|---|
| `pak_tool.py` | Archives `.pak` (Alchemy IGA v13, blocs LZMA) : `info`, `list`, `extract` |
| `extract_meta.py` | Extrait de l'`eboot.bin` le schéma des 8960 classes (nom, taille, parent, champs, offsets, types) → `schema/ctr_meta.json` |
| `igz.py` / `igz_tool.py` | Lecture des `.igz` (v10) : `info`, `roots`, `dump` (JSON de tous les objets, champs nommés via le schéma) |
| `race_system.py` | Décode `<piste>_RaceSystem.igz` → `<piste>.race.json` + `<piste>.splines.obj` (Blender) |

```bash
python ctr_tools/pak_tool.py extract "<archives du jeu>/t111_crash_cove.pak" extracted/t111_crash_cove
python ctr_tools/race_system.py extracted/t111_crash_cove/maps/Octane/T111_Crash_Cove/T111_Crash_Cove_RaceSystem.igz out
```

## Ce que contient une piste (dossier `maps/Octane/<Piste>/`)

- `_RaceSystem.igz` : splines de **position** (progression, classement, respawn), splines **IA**
  (`_pathDifficulty`, `_isShortcut`, `_isHazardous`), **transitions** entre sections
  (`_incrementLap` = ligne d'arrivée, `_isTeleporter`), **embranchements** (`ForkChecker` : quelles splines IA
  prendre selon la section), listes de **départs** (`CPlayerStartEntityHandleList` → entités du fichier `_Design`).
- `_Design*.igz` : gameplay (waypoints de respawn/départ, caisses, boosts...).
- `StaticCollision_<Piste>.igz` + `models/maps/.../StaticCollision_<Piste>.hkx` : collision Havok 2014.1
  (`hknpCompressedMeshShape`, packfile binaire).
- `_Art_*.igz`, `_Lighting*.igz`, `_VFX*.igz`, `_Audio*.igz`, `_Minimap.igz` : décor, éclairage, effets, son, minimap.

## Format IGZ (résumé)

Section 0 = fixups (`TSTR` chaînes, `TMET`/`MTSZ` types et tailles, `EXNM` références externes `fichier::objet`,
`RVTB`/`RSTT`/`ROFS`/`RHND` listes compressées d'offsets des vtables/chaînes/pointeurs/handles, `ROOT`, `ONAM`).
Listes compressées : nibbles (poids faible d'abord), 3 bits + bit de continuation, offset += valeur × 4.
Coordonnées : Z vertical ; point de spline monde = position de l'entité + `_position` du point ; splines ouvertes,
Catmull-Rom (longueur recalculée = `igSpline2._length` à 0,1 % près).

## Écriture

- `IgzFile.set_field(obj, champ, valeur)` modifie un scalaire en place ; `to_bytes()`/`save()` reconstruit le
  fichier (fixups ré-encodés). Aller-retour vérifié à l'octet près sur les 992 `.igz` de Crash Cove (`test_roundtrip.py`).
- `pak_tool.py replace` (copie) ou `install`/`uninstall` (en place, réversible : SHA-256 identique après
  désinstallation). Le fichier remplacé est ajouté non compressé en fin d'archive ; seule son entrée de TOC change.
- **Attention** : les `update*.pak` contiennent des versions plus récentes de nombreux fichiers
  (ex. `T111_Crash_Cove_RaceSystem.igz` est dans `update2.pak`) : il faut patcher chaque archive qui contient le fichier.
- `mod_test_finish_line.py install|uninstall <archives>` : mod de test (ligne d'arrivée déplacée au milieu de Crash Cove).

## Édition structurelle IGZ

`IgzFile` : `alloc`, `new_object`, `clone_object`, `set_ptr`, `set_list`, `list_insert`/`list_remove`,
`add_root` (liste racine + nom, hash FNV-1a 32 bits du nom en minuscules), `add_string`, `type_index`.
`spline_edit.SplineEditor` : `points`, `move_point`, `insert_point`, `remove_point`, `set_increment_lap`
(recalcule `_length`). Tests : `test_spline_edit.py`.

## Collision et géométrie

- `havok.py` : packfiles Havok 2014.1 (sections, fixups locaux/globaux/virtuels, hkArray). Pas de réflexion
  dans les fichiers : dispositions des classes déduites des données (voir `collision.py`).
- `collision.py <StaticCollision_X.hkx> <sortie.obj>` : maillages compressés hknp + polytopes + sphères.
  **Unités du jeu = pouces** (Havok en mètres × 39,37) : validé, 281/282 points de spline posés sur le sol.
- `level_geometry.py <dossier extrait> <Piste> <sortie.obj>` : décor placé par `_Art*.igz`
  (position + Euler Rz·Ry·Rx + échelle). Inclut tous les LOD et variantes 2P/4P : très lourd (5 M triangles).

## Éditeur

```bash
python ctr_tools/editor/server.py
```
Dossier « archives » du jeu : `--archives "<dossier>"`, sinon celui mémorisé dans `ctr_editor_config.json`, sinon
la page le demande à l'ouverture (aucun chemin écrit dans le code). Ce fichier garde aussi la langue (anglais par
défaut ; `window.CTR_SETTINGS` injecté dans la page, `POST /api/settings`), car le stockage du navigateur dépend du
port. « Importer un dossier » : bouton « 📁 Parcourir… » (`POST /api/pick_folder`, fenêtre de choix ouverte par le
serveur : celle de l'application sous Linux, sinon `zenity` / `kdialog`, sinon tkinter). « Créer le parcours » : « 🖱 Choisir les routes dans le Décor » (sélection dans la vue 3D, puis retour au
dialogue avec ces morceaux cochés).
Ouvrir http://localhost:8765 : vue 3D (collision + splines + transitions), sélection/déplacement/ajout/suppression
de points, **duplication / suppression de splines IA** (nouvelle spline = copie décalée de 300 po, ajoutée aux
mêmes transitions que son modèle, stats TTR créées), **panneau de liens** par transition (IA/position précédentes
et suivantes, `incrementLap`), splines de départ éditables (5 emplacements `CStartingSplineInfo` de TTRStats,
« Tous = spline sélectionnée », « Appliquer à la ligne d'arrivée »).
**Testé en jeu** : les splines de départ seules ne changent PAS le tour 1 ; la grille est juste avant la ligne
d'arrivée et les IA prennent aussitôt une des « IA suivantes » de la transition `incrementLap`. Pour le tour 1, il
faut donc mettre la spline dans ces IA suivantes (ce que fait « Appliquer à la ligne d'arrivée », qui l'ajoute aussi
en entrée de la transition suivante) ; config validée : départs + IA suivantes de la ligne = nouvelle spline.
« Enregistrer » écrit `RaceSystem` + `TTRStats` dans `out/editor/` (base des sauvegardes suivantes),
« Installer dans le jeu » patche chaque archive qui contient ces fichiers (réversible), « Restaurer les archives »,
« Repartir de l'original » (oublie les sauvegardes). **Validé en jeu** : spline IA dupliquée, déplacée et seule
liée après la ligne d'arrivée → suivie par les IA à partir du tour 2. Une spline supprimée sort de la liste racine et de toutes
les listes de liens ; ses objets restent dans le fichier sans être référencés.
L'éditeur part toujours de la version d'origine la plus récente (update2 > update > piste), même si un mod est installé.

### Application Windows (`CTR/exe/CTR Track Editor.exe`)

Dossier `CTR/exe` (par défaut ; autre dossier : argument de `build_exe.py`) : `CTR Track Editor.exe` + `_internal`
(Python, bibliothèques, éditeur, three.js, schéma IGZ), sans Python à installer. Le serveur tourne dans
l'application et l'éditeur s'ouvre dans sa propre fenêtre (pywebview, moteur Edge WebView2 de Windows). Lanceur :
`editor/app.py`. Icône : `crash-team-racing-nitro-fueled_j4g2.jpg` à la racine du projet (fond blanc rendu
transparent), sinon un drapeau à damier dessiné (dépôt GitHub sans image du jeu).
* Données (`out/editor`, maps à importer, journal `out/ctr_editor.log`) : à côté de l'exe, ou dans le premier
  dossier parent (2 niveaux) qui a déjà des sauvegardes → la racine du projet, comme avant.
* Archives du jeu : celles mémorisées dans `ctr_editor_config.json` à côté de l'exe, sinon demandées par la page à
  l'ouverture. Dans l'éditeur (application **et**
  navigateur) : ligne « 🎮 Dossier du jeu » en tête du guide et menu « ⋯ › 📁 Dossier des archives du jeu… ».
  `POST /api/archives` (sans `path` : fenêtre de choix ouverte par le serveur) vérifie le dossier, oublie tous les
  caches (`clear_caches`), mémorise le choix et la page se recharge. Le serveur seul relit
  `ctr_editor_config.json` à la racine du projet quand `--archives` n'est pas donné.
* Hors ligne : three.js 0.160.0 est servi localement (`editor/vendor/three`, route `/vendor/`).
* Port 8765, ou un port libre s'il est pris.
* Reconstruire après une modification du code :
  ```bash
  .build_venv\Scripts\python ctr_tools\editor\build_exe.py
  ```
  (environnement `.build_venv` : pyinstaller, pywebview, numpy, pillow ; `PIP_USE_FEATURE=truststore` si pip
  échoue sur les certificats). Piège : pywebview expose à la page tout attribut public d'un objet `js_api`
  (une fenêtre en attribut public = parcours récursif sans fin, fenêtre figée) ; l'application n'en utilise plus.

### Application Linux (`CTR/appimage/CTR_Track_Editor-<arch>.AppImage`)

Même lanceur (`editor/app.py`), construit par `build_appimage.py` (sous Linux) : dossier PyInstaller dans une AppImage
(un seul fichier). Fenêtre : pywebview + Qt WebEngine (PyQt6) embarqué ; les autres moteurs de pywebview et les autres
liaisons Qt sont exclus. Bac à sable Chromium désactivé (`QTWEBENGINE_DISABLE_SANDBOX`, bloqué par AppArmor sur
Ubuntu 24.04) : la page affichée est celle du serveur local.
* Données et `ctr_editor_config.json` : à côté du fichier `.AppImage` (l'application elle-même est montée en lecture
  seule), ou dans un dossier parent qui a déjà des sauvegardes ; dossier non modifiable : `~/.local/share/ctr-track-editor`.
* Fichiers enregistrés (`out/editor`) et fichiers des maps importées : noms cherchés sans tenir compte de la casse
  (`server.ci_path`, `_find_file`), comme sous Windows (le manifeste donne des noms en minuscules, les `.mtl` exportés
  sous Windows des chemins `Textures\Herbe.PNG`).
* Construire :
  ```bash
  python3 -m venv .build_venv
  .build_venv/bin/python -m pip install pyinstaller pywebview qtpy PyQt6 PyQt6-WebEngine numpy pillow
  .build_venv/bin/python ctr_tools/editor/build_appimage.py
  ```
  `appimagetool` : PATH, `$APPIMAGETOOL`, sinon téléchargé dans `.build`. La glibc de la machine de construction est
  la plus ancienne acceptée : construire sur une distribution ancienne (Ubuntu 22.04).

### Packs de maps (.zip, `editor/mappack.py`)

Menu « ⋯ » : **📦 Exporter des maps (.zip)** (pistes modifiées au choix, dossier `exports` du projet par défaut,
lien « ⬇ Télécharger » dans le navigateur) et **📦 Importer un pack de maps (.zip)** (pour chaque map : l'importer ou
non, et à la place de quelle piste ; option « installer dans le jeu après l'import »).
Le zip ne contient **aucun fichier du jeu** : `pack.json` (liste), par map `map.json` (décor, parcours, objets,
réglages, noms, survol…), `models/*.obj` (maillage de chaque modèle importé relu sans perte du `.igz` : positions,
normales, UV ; coordonnées du jeu, origine = pivot de l'objet), `textures/*` (image source si elle existe encore,
sinon la texture décodée), `menu/*.png`. Objets du jeu (bibliothèque, copies du décor d'origine) : nom de fichier +
archive seulement. Import (rejoué avec les fonctions de l'éditeur sur les fichiers d'origine de la piste cible,
une copie pour « Annuler ») : piste cible remise à l'origine → « Nouvelle map » → textures, modèles (gabarits du
jeu de l'importateur), objets, collision → ambiance (ciel de la piste source s'il en avait un) et allègement →
parcours : même nombre de sections = copie exacte (splines IA, liens des transitions, splines de départ) ; sinon
boucle du tour redécoupée (`route_gen.layout`, comme « Créer le parcours ») et splines IA régénérées par la page
→ caisses / boosters / TNT…, téléporteurs (même transition, sinon la plus proche), grille et repère de départ,
anciennes entités écartées (`old_route_moves`), chutes et réapparitions, mini-carte, survol (même rang ; plan final
→ plan final ; sinon proposé), nom et images de menu. Décor d'origine modifié : rejoué seulement sur la même piste.
Vérifié sur une copie : Crash Cove → Crash Cove / Roo's Tubes / Mystery Caves (copie exacte, 4 sections) et → Sewer
Speedway (6 sections : redécoupé, IA régénérées dans la page) ; zip de 6 Mo (22 OBJ, 11 PNG, 2 JSON).
Corrigé au passage : embranchement sans liste d'IA (Sewer Speedway) — `handle_list(None)` = liste vide ; arrivée de
téléporteur sur une piste sans point de réapparition dans le `_Design` (Roo's Tubes) : repère importé de Crash Cove.
Autres tracés de la piste (`_chain_from`) : une transition de passage qui revient sur sa propre spline (Coco Park
`Spline_Transition_002`, de `201_OLD` vers `201_OLD`) est sautée pour suivre la vraie suite, puis posée au milieu de
sa spline ; après la régénération, la page lui donne les IA de sa section (précédentes = suivantes, comme le jeu).
Coco Park, Turbo Track, Blizzard Bluff : caisses / boosters écrits dans le `_Design` (voir « Caisses d'objets »).
**Non validé en jeu.**

Nombre de sections différent (depuis le 2026-10-27) : la cible est d'abord ramenée au nombre du pack
(`server.plan_sections` : coupe la section la plus longue / retire en partant de la fin du tour), puis copie exacte
des IA du pack. Ex. Crash Cove 6 sections → Roo's Tubes (4) : 2 transitions ajoutées, « Vérifier » OK ; pack 4 →
Sewer Speedway (6) : 2 retirées, `SplineTransition_Shortcut` (raccourci de l'ancien tracé) écartée sous la carte.

### Sections : transitions ajoutées / supprimées

Section = spline de position entre deux transitions (`CRaceTrackSplineComponentData` : `_respawnPoints` = points de
réapparition de la section ; `_start` / `_end` inutilisés ; aucune stat TTR pour les splines de position).
- **Ajout** (fiche de la transition « ✂ Ajouter une transition dans la section suivante », ou point d'une spline de
  position « ✂ Nouvelle transition ici ») : la section est coupée (un point de chevauchement de chaque côté), la seconde
  moitié = nouvelle spline de position (`new_position_splines`, copie `add_ai_spline` sans stats), nouvelle transition
  = copie d'une transition ordinaire du jeu (`new_transitions`, `RaceSystemEditor.add_entity_copy` ; copie d'un
  téléporteur rendue ordinaire). IA de la section inchangées : la nouvelle transition est « de passage »
  (IA précédentes = suivantes, comme Coco Park `Spline_Transition_002`) — validé par le jeu d'origine.
- **Suppression** (« 🗑 Supprimer cette transition », pas la ligne d'arrivée ni une transition à plusieurs splines de
  position) : sections fusionnées (`joinPaths` : reprise après le point le plus proche), spline suivante supprimée,
  transition retirée (`deleted_transitions`, `remove_entity`). Les IA qui la traversaient sont refaites sur toute leur
  portée (`regenSpan` : de leur vraie transition de départ à leur vraie arrivée, à travers les transitions de passage).
- **Serveur** (`save_track`) : `section_merges` = sections touchées ; leurs points de réapparition sont répartis sur la
  plus proche (positions du `_Design`, ou celles replacées dans la même sauvegarde ; points hors `_Design` — Sewer
  Speedway, `RespawnPoint` du `_RaceSystem` — gardent leur section ou suivent la fusion) ; embranchements dont le
  `_positionPath` est une section touchée rattachés à la plus proche.
- **Créer le parcours** : champ « Sections » ; si le nombre change, `setSectionCount` puis toutes les IA régénérées.
- `race_chain` / `raceChain` sautent les transitions de passage (de la spline vers elle-même).
Testé sur copie (Crash Cove : +1, −1, puis « Créer le parcours » à 6 sections : « Vérifier » sans erreur) ; **non
validé en jeu**.

### Contrôle « Hauteur des splines » (Vérifier)

Splines de parcours et IA **utilisées par la course** (citées par une transition / un embranchement en place, ou de
départ) et **modifiées** (différentes du jeu d'origine : les pistes du jeu ont des creux jusqu'à −3,7 m et des sauts
jusqu'à 47 m, Sewer Speedway). Mesure sur la courbe suivie (`curve_uniform`), par rapport à la route mémorisée
(« Créer le parcours ») sinon au sol sous la spline (jamais un plafond / surplomb au-dessus). Splines générées :
parcours sur la route (0 m), IA à +2 m.
- **Erreur** : plus de 2,5 m sous la route (seulement là où la route mémorisée est connue).
- **Attention** : plus de 10 m au-dessus (ou rien dessous) sans retomber. Accepté : saut posé avant (A) et après (B)
  dans la spline, ou court saut (< 150 m) à cheval sur une transition. « Sans sol dessous » : souvent une branche
  restée sur l'ancien tracé (Mystery Caves de l'utilisateur : `Race_Position_Spline_split_02` + IA, encore reliées).
- **Correction** « Poser les splines sur la route » (`fix_spline_heights`) : points de contrôle autour des tronçons
  fautifs remis à la hauteur habituelle de la spline (médiane de ses points bien posés, sinon 0 / 2 m) ; point sans
  rien dessous (trou de la route) : interpolé entre ses voisins. Sauts gardés.
Testé : pistes d'origine sans alerte ; copies des maps de l'utilisateur (5 pistes) sans fausse alerte ; sabotage
(IA −6 m, parcours +20 m) détecté puis corrigé.

### Banc d'essai « Créer le parcours » sur les 21 pistes d'origine (2026-10-27)

Sur copie, chaque piste : parcours et IA recréés depuis les surfaces de route (« Créer le parcours », surfaces vides),
enregistrés, « Vérifier », puis contrôle avancé hors éditeur (tour comparé au tracé du jeu : longueur, écart, sens,
morceaux non parcourus, hauteur sur la route, IA sur les surfaces de route) et image vue de dessus. Corrigé :
- **Réapparitions rangées dans le `_RaceSystem`** (Sewer, Slide, Turbo, Papu, Dingo, Dragon, Cortex) : l'enregistrement
  plantait (`KeyError entite introuvable`) — `save_track` les écrit maintenant dans le `_RaceSystem`, « Vérifier » les lit.
- **Surfaces de route auto** : une surface croisée brièvement (pont, bande de bois, booster) compte dès 2 points
  (échantillons tous les 100 po) ; avant (5 points tous les 300 po) la route était coupée et la boucle trouvée faisait
  600 m au lieu de 3,7 km (Mystery Caves), 169 m (Inferno Island).
- **Morceaux de route reliés** (`route_gen.join_pieces`, `join_cuts`) : coupures courtes aux bords irréguliers que
  `bridge_gaps` ne voyait pas (bouts du squelette pas face à face) ; `join_cuts` refuse s'il y a un mur entre les deux.
- **Branches de l'ancien tracé** (`detachOldBranches` dans la page) : 2e spline de position d'une section (Mystery Caves
  `split_02`, raccourcis de Sewer / Turbo / Slide…) détachée des transitions du tour, ses transitions propres écartées
  sous la carte ; IA régénérées sur le tour seulement (`regenerateAllAi` options `only` / `share`).
- **Hauteur du tracé** : niveau de route le plus proche du point précédent (pas le plus haut : voûte des tuyaux de
  Sewer Speedway), repris à n'importe quelle hauteur après une chute de plus de 10 m (Android Alley : tracé resté 40 m
  trop haut) ; trou franchi sous une butte d'une autre surface : posé dessus (`_lift_onto_ground`, Crash Cove).
- **Courbe sous les bosses** : entre deux points de contrôle espacés (~60 m), la courbe passait jusqu'à 6 m sous le
  sommet d'une bosse ; `ai_gen.fit_controls` resserre aussi là où elle s'enfonce de plus de 1,5 m (ou monte de plus
  de 5 m) — parcours et voies IA.
- **Boucle la plus longue** (`_longest_cycle`) en plus du choix glouton : un raccourci / une route intérieure est plus
  court que le vrai tour (Turbo Track 2,3 → 3,3 km sur 3,8 km).
- Contrôle « Chutes » : erreur à moins d'1 m du plancher (avant : 10 m ; le jeu lui-même n'a que 3,8 m sur Tiny
  Arena). « Départ et transitions » : IA suivante mesurée au bord de la zone, pas à son centre (voie extérieure d'une
  plage de 70 m à 38 m du centre, Crash Cove).
Limites restantes (tracé à faire à la main ou en choisissant les morceaux de route) : circuits à étages superposés
vue de dessus (Cortex Castle), aller-retour sur la même route séparé par un muret (Tiger Temple), très grands sauts
(Dingo Canyon, > 40 m : monter « Franchir les trous »), Polar Pass (grands carrefours) ; splines rangées hors du
`_RaceSystem` (N. Gin Labs, Hot Air Skyway, Oxide Station) : non gérées par l'éditeur.

### « Créer le parcours » : décor géant, route trouée, plancher (2026-10-27)

Map Sneak a Peak importée sur Crash Cove (utilisateur) : « route géante : 4227 m ». La sélection contenait le décor de
fond `NoCollision_background_t_` (un clic sur la map en mode Décor touche ce maillage qui englobe tout). Corrigé :
- objet de plus de 3 km dans la sélection : écarté avec une note (erreur claire s'il ne reste que lui) ; source
  géante ou vide (surfaces du sol, tracé d'origine loin de la map) : route mémorisée / importée essayée ;
- boucle trouvée bien plus petite que la route choisie (route coupée par des trous > 40 m : petite boucle d'une
  place, 333 m sur 1,6 km) : second essai en franchissant jusqu'à 80 m, gardé s'il est nettement plus long
  (5,2 km) ; sinon note « coche les morceaux qui bouchent les trous » ;
- plancher de chute : seul celui du jeu (ou plus bas) borne la route ; celui posé par « Chutes et réapparitions »
  d'un ancien parcours (9512, au-dessus de la nouvelle route) ne bloque plus, une note demande de le refaire ;
- matériaux nommés `NoCollision*` : sans collision par défaut à l'import.
**Déplacer toute la map en hauteur** (Décor › Finitions) : tous les objets du décor décalés en Z comme un déplacement à
la main (Ctrl+Z, Enregistrer : collision et plaques de booster suivent, sol gris relu) ; le parcours ne suit pas.

### Sauts et obstacles : parcours et splines IA (2026-10-27)

Crash Cove de l'utilisateur. Problèmes et corrections :
- **Parcours décalé au-dessus d'un trou** : le pont dessiné dans l'image de la route (`join_pieces`, `bridge_gaps`,
  `join_cuts`) était un trait entre les deux pixels / bouts de squelette les plus proches, c'est-à-dire un coin
  quand les bouts de route sont en biais. Le tracé passait par le coin. Maintenant, le pont est l'enveloppe convexe
  des bords qui se font face (`_face_bridge`, `_end_bridge`), et le tracé passe au milieu (test « trous en biais »).
- **Splines IA resserrées au-dessus du vide** : aucun sol pour mesurer la largeur. Les points au-dessus d'un trou
  (`air`) et jusqu'à ~15 m du bord (largeur faussée par le bout coupé) reprennent les largeurs et les bornes de part
  et d'autre (`_fill_air`). La hauteur au-dessus du trou est celle du tracé.
- **Parcours et IA à travers les objets solides** : un rocher posé sur la route (la route continue dessous) ne se
  voyait pas. `ai_gen.Obstacles` reconnaît deux cas :
  - une face raide (pente > ~60°) traversée à hauteur de kart (60 po) ;
  - l'intérieur d'un objet : un dessus au-dessus de la route, et une face raide touchée dans les 4 directions à moins
    de 25 m.

  Les tremplins, plaques turbo, ponts et tunnels ne comptent pas. `avoid_bounds` choisit un seul côté libre par
  passage le long d'un obstacle (choisi point par point, il alternait et la voie traversait tout droit), puis
  resserre les bornes, que la pente 0,35 érode. Cela vaut pour les voies IA et la ligne centrale
  (`route_gen._avoid_obstacles`, note « tracé écarté d'objets solides »). `fit_controls(avoid=)` resserre les points
  de contrôle là où la courbe touche un obstacle (`Obstacles.crosses`).
- **Murs de zone devant un saut** : un bord tourné vers le sens de la course, avec la route choisie qui reprend en
  face à moins de 80 m (jusqu'à 80 m plus haut ou plus bas : réception 43 m sous le tremplin), est un bord de saut
  (`walls._jump_edge`) et ne reçoit jamais de mur.

Vérifié sur une copie (parcours 5,1 km, 11 points écartés de 2 rochers ; IA sans traversée de rocher ; aucun mur sur
le tracé ni sur les IA). Reste : une voie frôle le coin d'un bloc sur la lèvre d'une réception. Rien n'est validé en
jeu.

### Murs invisibles (`walls.py`, mode Décor — non validé en jeu)

Collision seule, rien à l'écran en jeu. Un mur invisible est un **modèle importé ordinaire** (objet de décor :
déplacer, tourner, échelle X = longueur / Z = hauteur, dupliquer, supprimer, annuler, packs de maps) dont le `.igz`
installé n'est qu'un triangle d'1 mm sous le sol ; sa forme est dans `out/editor/models/<nom>.wall.json` (registre
`'invisible': True`, `'wall': 'auto' | 'manual' | 'obj'`). `object_world_array` / aperçu / collision liée lisent cette
forme (`model_or_wall_mesh`), donc la collision suit l'objet comme pour tout import. Surface 4 (« Sol », celle des murs
de Crash Cove, Coco Park, Turbo Track).
- **Depuis un OBJ** : à l'import (colonne « Mur invis. » d'« Importer un dossier » — cochée d'office pour un matériau
  nommé `invisible` / `nodraw` / `clip` —, choix « mur invisible » dans « Importer un modèle OBJ »), ou après coup par
  clic droit « Mur invisible » (le `.igz` visible est gardé en `<nom>.visible.igz` pour « Rendre visible en jeu »).
- **Générés** (« Générer le long de la route… ») : le long des deux bords de la ligne de course enregistrée
  (`race_path_points`), bord mesuré comme les voies IA (route seule si connue). Au-delà du bord : mur ou talus déjà là
  (segment à 1,5 m de haut qui touche la collision, ou sol plus haut) → rien ; plus de sol au niveau de la route →
  mur ; herbe / sable au même niveau → mur seulement avec « hors route ». Jamais sur une autre partie de la route, à
  l'intérieur d'un virage plus serré que le décalage, ni où la route connue n'est pas sous le tracé (passage sous un
  pont d'un autre objet). Morceaux de 50 m (réglable), 10 m de haut, à 3 m du bord ; les murs générés précédemment
  sont remplacés (la collision est d'abord recalculée sans eux), les murs à la main / importés restent.
- **Autour d'une sélection** (« Murs autour de la sélection… », aussi au clic droit ; `walls.zone`, type `'zone'`) :
  parties de la map cliquées dans la vue 3D (Maj+clic). Bords = arêtes du dessus (triangles tournés vers le haut)
  qui n'appartiennent qu'à un triangle, sommets fusionnés à 2 po ; rien vers un autre objet choisi au même niveau
  (raccord), vers un mur / talus existant, ni dans la bande de la route (`walls.Corridor` : largeur mesurée de chaque
  côté du tracé, et un mur dont la hauteur croise l'espace d'un kart sur la route dessous ou dessus est refusé) ;
  mur à 1 m vers l'extérieur ; « vers un autre sol au même niveau » en option. Relancer sur les mêmes objets remplace
  ces murs (registre `'zone'` = liste des objets). Le test « sur la route » est fait tout le long de chaque bord (tous
  les ~4 m) : le bout coupé d'une route au bord d'un saut est un seul long bord en travers, dont le milieu tombait
  hors de la bande (mesurée plus étroite au bout) → mur en travers de la route (Crash Cove de l'utilisateur, corrigé
  le 2026-10-27).
- **Relier les murs** (« Relier les murs distants de moins de », 120 m par défaut, 0 = non ; `walls._join`) :
  1. trous du contour (mur ou talus déjà là, autre sol) d'au plus cette longueur entre deux murs : fermés en suivant
     le bord ; 2. bouts de murs restants reliés, plus courts raccords d'abord, chaque bout une fois : le long des objets
     choisis s'ils le permettent (`_mesh_router` : arêtes des faces non horizontales + bords du dessus, recoupées tous
     les 100 po, sauts d'au plus 250 po entre morceaux sans sommet commun ; hors de la bande de la route rétrécie de
     120 po), sinon coin là où les deux murs prolongés se croisent, sinon tout droit (jamais sur la route ni par-dessus
     les objets choisis, pas de demi-tour). Les petites boucles (dessus d'un poteau, ≤ 5 m) servent de points de
     passage. Cas d'origine : `SneakAPeak_Wall_Barrier` = 69 morceaux (2 bandeaux de panneaux verticaux + poteaux de
     8 sommets, 40 à 110 m d'écart) → seuls les dessus des poteaux donnaient des murs de 6 m isolés.
- **À la main** : « Ajouter un mur au centre de la vue » (20 m, face à la caméra).
Testé sur copie (Roo's Tubes importée de l'utilisateur, Crash Cove d'origine, pack exporté puis importé sur une autre
piste) et `test_walls.py`. À vérifier en jeu : un modèle d'1 mm n'affiche rien, les karts butent sur la feuille
(une seule épaisseur, les deux côtés).

### Types de sol : valeur de collision

`server.surface_params` : valeur = rang dans la `CCollisionMaterialHandleList` de `LooseData/CollisionMaterials.igz`
+ décalage **calé sur Sand = 38** (la liste lue n'a plus d'entrée nulle en tête : l'ancien « + 3 » affichait la fiche
du sol voisin, d'où ralentissement / adhérence 1,0 partout dans le menu du clic droit). Adhérence affichée = min(
`_traction` de la fiche, `_dynamicFriction` du matériau / 0,5) (glace : frottement 0,05). Herbe (5) : ×0,4 constaté
en jeu, absent de la fiche (`SURFACE_OBSERVED`).

### Survol d'introduction (`flyby.py`)

Archives propres à chaque piste `<piste>_*flyby*.pak` (Crash Cove : `t111_crash_cove_newflyby.pak` = 4 plans de
3 à 4 s, `…_newflyby_short02.pak` = 1 plan de 6 s ; le dernier plan de chaque survol finit sur la grille). Caméra
d'un plan : `cutscene/…/cameras/c_<…>_shotN.igz` — `CCutsceneCamera` (pose de départ, rotation en degrés) +
`CCameraKeyframeAnimation` : une clé tous les 1/30 s, `_positions` (coordonnées de la piste), `_rotations`
(roulis, tangage, cap en radians ; tangage négatif = regard vers le bas), `_fovs`. Vérifié : les clés recalculées
depuis les poses de début / fin d'un plan d'origine retrouvent exactement son orientation.
Éditeur (mode Course, section « 🎬 Survol d'introduction ») : un plan = pose de début et de fin (caméra + point
regardé), déplaçables dans la vue 3D ou « Prendre la vue actuelle » ; « Générer depuis le parcours » (travellings le
long de la route, plan final qui descend vers la grille), « Plan fixe sur la grille » (le survol ne montre plus
l'ancienne piste), lecture ▶ dans la vue 3D. Enregistrement : `<piste>_flyby.json` + caméras réécrites en place
(mêmes clés, même minutage) ; installées dans les archives de survol (sauvegardées / restaurées comme les autres).
**Validé en jeu (2026-10-26).**

### Téléporteurs (mécanisme de Spyro Circuit)

Analyse de Spyro Circuit (T503, archive `archives/T503_September_Spyro.pak` imbriquée dans `update2.pak`) et de Hyper
Spaceway (T255) : le « miroir » est une transition de spline dont le composant `CRaceTrackSplineTransitionComponentData`
a `_isTeleporter = true` et qui porte un 3e composant, le script `common_teleport_entity`
(`vsc/common/Octane/T255_Hyper_Spaceway/…`, `CTeleportNodes::teleportEntity2`). Paramètres (mémoire du script) :
+0x10 handle de l'entité d'arrivée (Spyro : `Destination_01..03` du `_Design`, entités sans composant), +0x18 = 1,
+0x20 effet joué sur le pilote (`ctr_t255_portal_driver_warp`, EXID). Le portail visible de Spyro est une image
pré-calculée de l'arrivée (textures `fxt_t503_portal1..3`). La spline de position suivante relie le portail à
l'arrivée, juste avant la transition suivante.

Éditeur (mode Course) : zone de transition → « 🌀 Faire de cette zone un téléporteur » → anneau violet (arrivée,
flèche = sens) déplaçable / orientable ; « Poser sur la route ». À l'enregistrement (`teleport.py`,
`apply_teleporters`) : arrivée `Teleport_Arrival_<transition>` clonée d'un point de réapparition dans le `_Design`,
composant script importé de `Teleporter_04` (Hyper Spaceway, archive lisible directement), table de composants
réécrite, et la zone de déclenchement transmet l'entrée des karts à l'entité (`_sendEventsToEntity` et
`_triggerCausesTouch` à vrai, comme les téléporteurs du jeu ; à faux sur les transitions ordinaires de Crash Cove —
1er essai en jeu sans eux : aucune téléportation ; chaque enregistrement répare un téléporteur qui ne les a pas).
À l'installation : script + effet copiés dans l'archive de la piste (seulement dans celle de Hyper Spaceway),
modèle / matériau / textures de l'effet déclarés au manifeste. **Validé en jeu (2026-10-25).**

Découvertes utiles au passage :
* `igComponentDataTable` = table de hachage à sondage linéaire, capacité 2 × n, case = FNV-1a(clé en minuscules)
  % capacité (vérifié sur 216 tables / 529 clés) → `teleport.write_table` ajoute ou retire un composant.
* Handles nommés (bit 31) = **rang parmi les entrées EXNM drapeau 1**, pas l'index dans toute la liste (fichiers du
  jeu : la plus grande valeur est toujours < nombre d'entrées drapeau 1). `ext_index`, `handle`, `handle_list`
  suivent cette règle (elles ne différaient que dans un fichier où une entrée drapeau 0 en précède une drapeau 1).
* Sections de fixups absentes (RaceSystem de Crash Cove : ni TDEP, ni EXID, ni RNEX) : `ensure_fixup` les crée dans
  l'ordre du jeu, nombre de sections à l'en-tête +0x10. Bourrage avant EXID / EXNM : gardé tel quel (le jeu a ~130
  exceptions à la règle « alignement sur 8 »), calculé seulement pour une section créée.
* Mémoire des paramètres d'un script (`CVscComponentData._dynamicFieldMemory`) : le champ de taille ne la donne pas ;
  `reachable` l'étend jusqu'à l'objet suivant (sinon le compactage complet coupait les paramètres d'un script greffé).

## Validé en jeu (shadPS4)

- Ligne d'arrivée déplacée (`_incrementLap` transition 01 → 03) : le tour change à mi-parcours.
- Splines IA (`mod_test_ai_slalom.py`) : un slalom de ±15 m n'a **aucun effet** visible ; à ±38 m les IA
  se jettent d'une paroi à l'autre puis se bloquent quand les points sont dans le mur. Les IA suivent donc les
  splines, mais avec une tolérance latérale d'environ 15–20 m (cf. `ttrStats/<Piste>_TTRStats.igz`,
  `_longestOffset2` ≈ 785² po² par segment). Pour modifier une trajectoire IA : sortir de cette marge,
  garder les points au-dessus de la route (vérifier le sol avec la collision).
- `ttrStats/<Piste>_TTRStats.igz` contient des statistiques **par segment** de chaque spline IA
  (`_segmentIndex`, vitesses, offsets) : en ajoutant/supprimant des points, il faudra probablement les régénérer.

## Nouvelles entités

- `IgzFile.deep_clone_entity(entité, nouveau_nom)` : duplique une entité et ses objets/blocs mémoire exclusifs
  (les objets partagés entre entités — archétypes, bolts — restent référencés), re-câble les pointeurs, nomme
  les copies. `ext_index` / `set_handle_list` / `handle_list` : handles externes (`Fichier::Objet`, EXNM).
- `race_entities.py` : `RaceSystemEditor.add_ai_spline` (clone + branchement aux transitions),
  `set_transition_paths` ; `TTRStatsEditor.add_spline_stats`, `set_starting_splines`
  (`_splineHash` = FNV-1a 32 bits du nom, sensible à la casse). Tests : `test_race_entities.py`.
- `mod_test_new_ai_spline.py install|uninstall` : nouvelle spline `AI_Spline_20` seule utilisée au départ.
  **Validé en jeu** : les IA suivent la nouvelle entité (slalom après le départ).
  TTRStats existe dans `update2.pak`, `update.pak` et l'archive de la piste : les trois sont patchées.

## Mode Décor (éditeur)

Sélecteur **Course / Décor** en haut. En mode Décor : les ~4800 objets des fichiers `_Art*` (versions les plus
récentes, update2 compris) avec leurs vrais maillages (121 modèles, chargés en binaire), un fichier = une couleur,
cases pour masquer un fichier, recherche par nom/modèle, sélection au clic, poignées déplacer / tourner / échelle
(W / E / R) et champs numériques, **Dupliquer** (Inser) et **Supprimer** (Suppr). « Enregistrer » écrit les
fichiers `_Art*` modifiés dans `out/editor/` ; « Installer dans le jeu » installe **tout** ce qui est enregistré
(course + décor). Module : `decor.py` (tests : `test_decor.py`).
Placement : igEntity +0x20 position ; igEntityTransform +0x60 Euler (R = Rz·Ry·Rx, ordre three.js 'ZYX'),
+0x6C échelle globale, +0x70 échelle xyz. Une suppression retire l'objet de la liste racine.
**Testé en jeu** : déplacer un objet déplace son visuel, mais PAS sa collision (figée dans `StaticCollision_*.hkx`).

### Collision qui suit le décor (`collision_edit.py`) — LIMITÉ
**Testé en jeu** : le `.hkx` est bien lu (désactiver l'instance du sol fait passer le kart à travers), mais
déplacer l'instance d'un objet ne suffit pas : pour beaucoup d'objets (ex. `Bridge04`), l'instance n'est qu'un
**marqueur** minuscule (12 triangles, 17 cm) et la surface réelle est **fusionnée dans le grand maillage du sol**
(instance 29). La synchronisation ci-dessous ne vaut donc que pour les objets dont l'instance porte la vraie forme
(piliers en polytopes, sphères…). Déplacer le reste demande de réécrire le maillage compressé du sol.
Chaque objet de décor avec collision = une instance du `hknpStaticCompoundShape` à la même transformation
(77/77 sur Crash Cove). À chaque « Enregistrer » du décor, le serveur reconstruit la collision depuis l'original :
instance d'un objet déplacé → nouvelle transformation ; objet supprimé → instance réduite à l'échelle 1e-4 ;
puis l'arbre de boîtes du compound est neutralisé et son domaine agrandi. Fichier : `out/editor/StaticCollision_*.hkx`,
installé avec le reste. Les **copies** d'objets n'ont pas encore de collision (il faudrait ajouter des instances).
Tests : `test_collision_edit.py`.

## Maillage de collision : encodeur et zones

- `havok_writer.py` : réécriture de packfile par ajout en fin de `__data__` + fixups reconstruits
  (les 10 `.hkx` de Crash Cove et les 3 versions du sol réécrits à l'identique).
- `cms_codec.py` : `read_mesh` (primitives, surface, drapeaux) / `encode_mesh` / `write_mesh`. Encodage : découpe
  spatiale en sections (≤ 120 primitives, ≤ 250 sommets), **tous les sommets « partagés »** (21/21/22 bits, ~0,4 mm),
  arbres du haut (5 o) et de section (4 o), data runs, `quadIsFlat` / `triangleIsInterior`, clés.
  Aller-retour du sol : 14 634 triangles à 0,3 mm, surfaces et drapeaux identiques (`test_cms_codec.py`).
  **Validé en jeu** : le sol ré-encodé se comporte normalement.
- `collision_region.py` (`GroundEditor`) : sélection par boîte ou par proximité d'un modèle, déplacement,
  suppression, ré-encodage + neutralisation de l'arbre du compound.
- Éditeur (mode Décor) : un objet déplacé/supprimé entraîne les triangles du sol qui lui appartiennent + son
  instance propre ; aperçu en rouge à la sélection (`/api/decor_collision`). Les copies n'ont pas encore de collision.
  Sélection : graines = 3 sommets à moins de 12 po du modèle, puis **propagation** aux voisines de même surface
  (ex. bois) dans l'emprise du modèle. 1er essai en jeu sans propagation : seul le niveau des rambardes suivait,
  le tablier de collision (~1 m sous le visuel par endroits) restait en place ; avec propagation, Bridge04 :
  139 → 402 primitives, même empilement de couches au nouvel emplacement.
  **Validé en jeu** : Bridge04 déplacé de ~49 m → on roule sur les planches au nouvel endroit, plus rien à l'ancien.
- **Copies avec collision** : à l'enregistrement, chaque copie est liée à son objet d'origine
  (`out/editor/<Piste>_decor_links.json`, une copie de copie remonte à l'original). La synchro copie les
  primitives de sol liées à la source (depuis leur état d'origine) à la position de la copie et ajoute une
  instance de compound pour chaque instance propre de la source. L'arbre du compound est **reconstruit**
  (nœuds 6 o : bornes, hiData bit 7 = interne, loData u16 ; enfant droit i + 2·valeur) au lieu d'être neutralisé.
  Tests : `test_collision_copy.py`. **Validé en jeu** (pont dupliqué : on roule sur la copie).
- Le serveur sérialise les écritures (verrou) : une installation lancée pendant un enregistrement (recalcul de
  la collision ~5 s) partait sans le `.hkx`. Le message d'installation indique « collision incluse / SANS collision ».

## Import de modèles (étape 3)

- **Ajout de fichiers dans un `.pak`** (`pak_tool.install`) : nom indexé par **FNV-1a 32 bits du nom logique en
  minuscules** ; ~1 400 o libres après la TOC (20 o par fichier, soit ~70 fichiers ajoutés) ; au-delà (map complète :
  ~230 fichiers), les fichiers stockés juste après la TOC sont déplacés en fin d'archive (`_plan_toc_space` ; sur
  Crash Cove : le manifeste `_pkg.igz`) et la sauvegarde couvre leur ancienne place (vérifié : originaux relus à
  l'identique, restauration au bit près) ; TOC reconstruite (triée par hash,
  diviseur = 2³²/n, marge recalculée), table des noms réécrite en fin d'archive. Sauvegarde v2 = tout l'en-tête
  (`.ctrmod.toc`) → désinstallation à l'identique ; la « vue d'origine » d'une archive modifiée se lit à travers
  cette sauvegarde (`original_archive`). Tests : `test_pak_add.py`.
- **`model_build.py`** : `parse_obj` (axes Blender Y-haut → Z-haut, mètres → pouces), `complete_mesh` (normales,
  UV projetées, tangentes), `build_model` : clone du gabarit `T111_RockGroundSide_b` (1 draw call, sommets 40 o,
  texture de roche), sommets/indices/boîtes/compteurs/noms remplacés. Triangles anti-horaires (vérifié 82/82).
  Tests : `test_model_build.py`.
- **Éditeur** : bouton « Importer un modèle OBJ… » (mode Décor) → modèle `models/Levels/Octane/Custom/<nom>.igz`
  (stocké dans `out/editor/models/`), objet de décor placé au centre de la vue, collision = le modèle, ajoutée au sol
  (surface du sol dessous par défaut). Installé comme **nouveau fichier** dans l'archive de la piste.
  Un nom déjà pris reçoit un suffixe (`MonModele_2`…) au lieu d'écraser le modèle existant.
  **Choix de la texture** : liste (`/api/materials`) des matériaux des modèles du manifeste dont le draw call a
  exactement le format de sommet du gabarit et dont le `materialinstances` est listé (136 pour Crash Cove, ceux de la
  piste d'abord). `model_build.set_material` change le handle EXNM du draw call (+0x40), la dépendance TDEP
  (`materials:/…igz`) et la table `CMaterialHandleTableInfo` (clé « bibliothèque.matériau » → « espace.matériau »,
  case = FNV-1a(clé minuscule) % capacité, vérifié sur les modèles du jeu). **TDEP** = chaînes (espace, chemin)
  terminées par \0 + **une chaîne vide de fin** + alignement sur 4 (`encode_tdep`, règle vérifiée sur 141 modèles) :
  sans ce terminateur (cas où la longueur tombe pile sur un multiple de 4), chargement infini de la piste
  (corrigé et validé en jeu : scène de 6 objets multi-matériaux, textures + collision).
  Exemple : `out/Rampe.obj` (rampe 8 × 4 m, 2 m de haut).
  **Scènes (map complète en un import)** : `parse_obj_groups` → un modèle + un objet de décor par couple
  (objet `o`/`g`, matériau `usemtl`), découpé au-delà de 65 535 sommets (`_p1`, `_p2`…). Dans la fenêtre, chaque
  matériau Blender reçoit une texture du jeu (correspondance automatique par nom, suffixe `.001` ignoré, mémorisée
  dans le navigateur) et une surface de collision (`auto`, 38, 13, 16 ou **aucune**). Placement : centre-bas de la
  scène au point visé, ou **coordonnées absolues** (coordonnées Blender = coordonnées du jeu après conversion).
  Chaque objet a son origine au centre-bas de son morceau. Un seul recalcul de collision (triangles dégénérés
  ignorés, ajout groupé par surface ; encodeur ~4× plus rapide : ~6 s pour 29 000 triangles).
  Exemple : `out/Scene.obj` (plateforme `rockGroundSide`, rampe `WoodPost`, 4 poteaux `PostRope`).
- **Annuler / Rétablir** (boutons ↶ ↷, Ctrl+Z / Ctrl+Y) : instantané de l'état non enregistré après chaque
  modification (`markDirty`, un glisser du gizmo = une étape) ; décor = `dEdits` (les copies ont un `uid`), course =
  splines + transitions + départs. Pile vide → « Annuler le dernier enregistrement » : avant chaque enregistrement,
  import, changement de texture ou « Repartir de l'original », le serveur copie les fichiers enregistrés de la piste
  dans `out/editor/history/<Piste>/` (20 niveaux, `with_history`, `/api/undo_save`) ; une opération qui échoue est
  aussi annulée automatiquement.
- **Texture d'un modèle importé** (panneau de l'objet sélectionné) : un matériau du catalogue
  (`/api/set_custom_material`, toutes les copies du modèle changent) ou une **image externe** PNG/JPG
  (`texture_build.py`, `/api/import_texture`) : texture BC1 1024² (clone de la couleur de la roche du gabarit,
  mipmaps recalculés, encodeur BC1 numpy ~0,3 s), carte de normales plate partagée (BC5 constant), matériau
  « Standard » clone de la roche (`retarget_material` : poignées EXNM + TDEP), nommés
  `textures/ColorMap,textures@!custom!<Nom>_C`png,111.igz` et `materialinstances/Custom/Custom_materials,<Nom>,1.igz`.
  Installés et déclarés dans le manifeste (types `texture`, `material_instances`) avec les modèles qui les utilisent.
  Format PS4 vérifié : blocs 4×4 en tuiles de 8×8 blocs, ordre de Morton (x0 y0 x1 y1 x2 y2), chaque niveau complété
  à 8×8 blocs ; format par référence externe (833431f8 BC1, cf76b9f0 BC3, 6a1e087d BC5). Tests : `test_texture_build.py`.
  **Validé en jeu** : l'image externe s'affiche correctement (bon sens).
- **Départ et ligne d'arrivée** (`start_finish.py`, mode Course) : **grille** = 8 `CWaypoint`
  « Starting_Waypoint_1st..8th » de `maps/Octane/<P>/<P>_Design.igz` (`_position` monde, `_rotation` Z = cap, avant
  du kart = +X local) ; **repère** `PlayerStartAll` (CPlayerStartEntity de `maps/Octane/<P>/<P>.igz`, +0x20 position,
  transformation +0x68 cap) qui suit la grille déplacée en bloc ; **changement de tour** = transition à `_incrementLap`
  dont la zone est le `CTriggerVolumeBoxComponentData` de l'entité (`_dimensions` profondeur / largeur / hauteur,
  centrée sur la position, tournée du cap de l'entité, transformation +0x68). Éditeur : karts numérotés (sélection
  d'une place ou de toute la grille), zones en boîtes (verte = changement de tour, une seule à la fois), déplacer
  (W) / tourner le cap (E) / dimensions, « Replacer la grille derrière cette ligne » (même disposition qu'à
  l'origine). Les deux nouveaux fichiers sont installés, réinitialisables et dans l'historique. Tests :
  `test_start_finish.py`. **Validé en jeu** (ligne déplacée de ~250 m) : départ, changement de tour et classement OK ;
  les IA tournaient en rond à l'ancienne ligne → bouton « Raccorder les splines IA à cette zone » : les splines IA
  « précédentes » de la transition sont prolongées (tracé de la « suivante » la plus proche, décalage de voie réduit
  progressivement) jusqu'à +1500 po après la ligne, les « suivantes » repartent de −1500 po (chevauchement comme dans
  le jeu) ; cas inverse (ligne reculée) : précédentes coupées, suivantes prolongées au début. Annulable (Ctrl+Z).
- **Génération automatique des splines IA** (`ai_gen.py`, `/api/gen_ai_splines`, bouton « Générer les splines IA de
  cette section… » sur un point de spline) : depuis une spline de référence (position ou IA), la largeur de route est
  mesurée sur la collision enregistrée (pas de 40 po vers chaque côté jusqu'à un changement de surface — surfaces
  majoritaires sous la référence + celle sous le tracé —, une marche > 80 po ou le vide ; lissée sur ~50 m). N voies
  réparties sur la largeur moins une marge, variation latérale douce et aléatoire (3 sinusoïdes, graine), posées à
  80 po du sol, points tous les ~2500 po (calibré sur le jeu : ~2700 po, ~84 po). Section = transitions de début /
  fin de la référence ; option remplacer les splines IA de la section (sauf raccourcis/sauts et branches
  d'embranchement), câblage dans les transitions, raccord automatique aux deux bouts ; les remplacées cèdent leur
  place dans les embranchements (`replaced`, côté serveur). Annulable (Ctrl+Z). Tests : `test_ai_gen.py`.
  Validé en jeu (une section). **« Régénérer toutes les splines IA… »** (panneau sans sélection, mode Course) : toutes
  les sections d'un coup (une par spline de position, voies = nombre actuel ou fixe), option « sans exception » :
  raccourcis, sauts et branches d'embranchement refaits en une voie sur leur propre tracé (`keep_air` : hauteur
  d'origine gardée au-dessus du sol), même place dans transitions / embranchements / départs ; puis toutes les
  transitions raccordées ; une seule étape d'annulation. Crash Cove : 21 → 21 splines, embranchements et splines de
  départ du tour 1 mis à jour (vérifié en rejouant l'enregistrement sur une copie). Validé en jeu (tour complet).
  **Éloignement des murs** : la courbe lissée entre deux points de contrôle (~2500 po) coupait l'intérieur des
  virages. Désormais (1) chaque point de la voie voulue garde au moins `CLEARANCE` = 120 po (~3 m) de route libre
  côté extérieur, sinon il est ramené vers le tracé par pas de 40 po ; (2) `fit_controls` ajoute des points de
  contrôle tant que la courbe Catmull-Rom uniforme s'écarte de plus de 150 po de la voie. Mesure sur la courbe
  suivie (`offroad_ratio`, vue de dessus) : sections 01 / 02 de 2,0 % / 0,8 % hors route à 0 % ; reste 1,7 % en 04
  sur une surface plate voisine (herbe), pas un mur — les splines du jeu font 0,7 %. Plus de points dans les virages.
- **Créer le parcours depuis la route** (`route_gen.py`, `/api/route_layout`, bouton du mode Course) : sans aucune
  spline existante, la route (objets sélectionnés en mode Décor = route importée, ou surfaces du sol) est rasterisée
  vue de dessus (60 po/pixel), trous bouchés, obstacles au milieu de la route (trous < 25 % de l'intérieur du
  circuit) comblés, squelette Zhang-Suen, impasses ébarbées (bout de ligne = un seul groupe de voisins), parcours en
  profondeur depuis la ligne d'arrivée dans son sens (branche alignée et large, retour au carrefour sur impasse),
  lissé, hauteur suivie en continuité (pas de passerelle au-dessus). Crash Cove : boucle de 2314 m à 4 m
  (médiane) du tracé du jeu. Puis : N sections égales = splines de position (chevauchement 2000 po), transitions
  au début de chaque section (cap = tangente, largeur = route + 800 po, ligne d'arrivée : 1000 po de profondeur,
  660 po au-dessus du sol), grille recalée, points de réapparition du `_Design` répartis par section, zones de
  réapparition / succès du `_Design` et embranchements écartés sous la carte (−100000), toutes les splines IA
  générées (raccourcis / sauts de l'ancien tracé retirés). Une étape d'annulation. Tests : `test_route_gen.py`.
  Non validé en jeu. L'ancien sol et l'ancien décor restent (leur retrait est une étape à venir).
- **Nouvelle map** = PREMIÈRE étape du guide (avant l'import ; section « 🧹 Nouvelle map » en tête du mode Décor).
  Section « Tes ajouts » (`added_groups`, champ `added` de `/api/decor`, `remove` de `/api/newmap`) : objets ajoutés
  au décor enregistré (ids absents du fichier d'origine), par lot d'import (champ `import` du registre des modèles
  importés, « nom — jj/mm hh:mm » ; anciens imports : nom retrouvé devant l'objet OBJ + suffixe « (n°6) »), par
  modèle de la bibliothèque, et « copies d'objets d'origine » ; plaques de booster exclues. Cochés : supprimés
  (définitif, « ↶ Annuler » pour revenir). « Tout cocher » vide toute la map. Map vide (sol retiré, aucun import)
  testée : collision encodée sans triangle, import suivant normal.
  Toutes les pistes (corrigé après l'erreur StopIteration sur Roo's Tubes) : le fichier qui reçoit les ajouts est
  `main_art` = celui de l'entité du sol de collision (Crash Cove Art_Core, Roo's Tubes Art_Level_Core, Coco Park
  Art…), l'objet copié `template_object` = l'objet transformable au moins de composants (Crash Cove : inchangé,
  « banner »), cherché seulement s'il y a des ajouts. Vider un fichier retire aussi les entités sans modèle qui
  regroupent des objets (préfabriqués : algues de Roo's Tubes), sinon leurs enfants restaient. Restes hors décor
  reconnus au nom (`design_*`, `crowd`, `spider` ; `vfx*` ; `lighting*` ; `audio*`, fichiers sans entité
  ignorés), générateur de caisses (`crate|powerup`) jamais déplacé. Gabarits de Crash Cove (modèle, matériau,
  textures) lus aussi depuis d'autres archives (`read_game_file`).
- **Nouvelle map** (détails ; bouton « Nouvelle map… » du mode Décor, `/api/newmap`, réglages `out/editor/<Piste>_newmap.json`) :
  « retirer l'ancien sol » = la collision ne contient plus que les modèles importés (`collision_custom_only` : toutes
  les primitives d'origine supprimées, ~9800 sur Crash Cove, toutes les instances du compound désactivées sauf celle
  du maillage qui reçoit les triangles importés) ; « retirer les objets d'origine » par fichier `_Art` (`write_art`
  ne garde que les objets importés et les copies). Décocher remet l'origine (`restore_originals`). Enregistré
  aussitôt, dans l'historique (Annuler). Restent (listés après application) : éclairage + géométrie lointaine
  (`_Lighting`), caisses d'objets (`_Power_Up`), reliques, jetons, objets animés, sons localisés, effets, mini-carte,
  ciel et eau. Tests : `test_newmap.py`. Premier essai en jeu : on traversait les modèles importés — c'étaient
  des boîtes agrandies ×25 à ×40 (triangles de 2,5 à 5 km ; le sol du jeu : 307 m au plus). La collision des
  modèles importés est désormais découpée en triangles de 100 m au plus (`subdivide_tri`, `MAX_COLLISION_EDGE`),
  le visuel ne change pas. (Vérification ensuite : la collision réellement installée lors de ce test contenait encore
  le sol d'origine — test non concluant.) Import après « Nouvelle map » : l'objet modèle est pris dans le fichier
  d'origine (le fichier enregistré peut n'avoir plus aucun objet → `StopIteration`). Fenêtre d'import : millimètres,
  échelle libre (m par unité) et taille obtenue affichée ; avertissement si le modèle descend près de `_killz`
  (−1000, `CWorldEntityData`). Essai avec `circuit.obj` (anneau Rhino) à 0,075 m/unité : boucle de 300 m.
  **Cause réelle du « on passe au travers »** : le jeu n'active une instance du compound que si l'entité `_Art` qui
  la porte (composant `CStaticCollisionComponentData`) est chargée. Table `StaticCollision_<Piste>.igz`
  (`CStaticCollisionHashInstanceIdHashTable`, 2 × capacité : clés u64, valeurs u16) : clé = fnv1a(nom du fichier
  `_Art` sans extension) << 32 | hash du nom de l'entité (celui de la liste des noms racine, +8 de chaque entrée de
  16 o) → instance. Sur Crash Cove le maillage de sol 29 (où vont les triangles importés) = `RaceTrack_Collision`
  d'Art_Core (modèle `T111_Crash_Cove_Collision.igb`) ; « Nouvelle map » la supprimait. `collision_owners` /
  `ground_owner` la retrouvent et `write_art` la garde toujours. **Validé en jeu** (2026-10-19) : les karts roulent
  sur `circuit.obj` importé, ancien sol et ancien décor retirés ; avec « Créer le parcours depuis la route » : changement
  de tour, classement, réapparition après une chute et IA (trajectoires perfectibles) fonctionnent sur un tour complet.
- **Import d'un dossier** (mode Décor, « Importer un dossier… » ; `/api/folder_scan`, `/api/import_folder`) : OBJ +
  MTL + images d'un dossier (relatif au projet, `map` par défaut). Chaque matériau `usemtl` reçoit sa propre texture
  (`map_Kd` du .mtl, nom de fichier insensible à la casse, convertie par `create_texture` ; couleur unie `Kd` si
  l'image manque ; une image déjà importée depuis le même fichier est réutilisée), puis `import_model` (un modèle par
  objet / matériau). Collision choisie par matériau : feuillage, fleurs, lampes, eau… décochés par défaut
  (`NO_COLLISION_HINT`). Essai avec `map/Mario Circuit.obj` (80 matériaux, 123 000 triangles) : 39 s, 65 textures
  (~51 Mo), 74 600 triangles de collision. Collision de plus de 65 535 sommets : seuls les sommets communs à
  plusieurs sections restent « partagés », les autres sont compressés par section (11/11/10 bits, comme le sol
  d'origine ; écart < 2 cm à l'horizontale et < 9 cm en hauteur sur une grille de 150 000 triangles). La transparence
  n'est pas gérée (BC1). **Validé en jeu** (2026-10-20, Mario Circuit : affichage, textures, collision) ; il a fallu
  agrandir la TOC de l'archive (voir « Ajout de fichiers dans un .pak »).
  **COLLADA (.dae)** : `dae_import.py` convertit le fichier en texte OBJ + matériaux (même chemin ensuite) :
  `<triangles>` / `<polylist>` / `<polygons>`, `<instance_geometry>` et `<instance_controller>` (skin :
  `bind_shape_matrix`, pose de repos — les exports de cartes Switch Toolbox ont un seul os identité), nœuds
  imbriqués (matrix / translate / rotate / scale), `<unit meter>`, `<up_axis>` (Y par défaut) ; texture = diffuse de
  l'effet (sampler → surface → image) ; premier jeu d'UV ; sommets fusionnés (position + normale + UV). Essai
  `map2/Cnsw_12.dae` : 180 000 triangles, 26 matériaux, conversion 1,6 s, import 40 s. La fenêtre propose l'axe du
  fichier et une échelle ronde donnant ~500 m de côté (`_suggest_scale` : 1 pour Mario Circuit, 0,02 ici).
  **Échelle d'après la route** (`_road_scale`, prioritaire) : l'emprise totale trompe (Mario Circuit 3 : nuages et
  montagnes de fond sur 82 000 unités, route de 4 200 → import à 0,005 = route de 1 m, à z = −9 539, « Créer le
  parcours » échouait). On prend la plus grande surface dont le matériau contient « road » (≥ 200 triangles, bien plus
  longue que large), on mesure sa largeur médiane (squelette de la vue de dessus) et on vise 30 m
  (`ROAD_WIDTH_TARGET`) : map2 0,1 (28 m ; importée à 0,02 = 5,6 m), map3 0,1 (22 m), Mario Circuit 5 (route de
  ~5 m à l'échelle 1). La fenêtre affiche la largeur obtenue (rouge hors 15–60 m). Placement « vue » : c'est la route
  qui est posée au point visé (`anchor_material`), et un point visé sous le plancher de chute est remonté à z = 0.
  « Créer le parcours » explique désormais une route minuscule ou sous le plancher de chute.
  **Largeur des voies IA sur une map importée** : toute la collision importée a la même surface (38) → route,
  herbe, bordures basses et montagnes comptaient comme route (map3 : largeur vue 203 m, voies à 82 % hors route,
  boucles hors map). Les voies sont désormais mesurées sur la géométrie de la route seule (`road_ground`) : objets
  utilisés par « Créer le parcours » (mémorisés par nom dans `<Piste>_road.json`), sinon les modèles importés dont le
  matériau contient « road » (`imported_road_objects`). map3 : 25 m, 0,2 % hors route, 0 nœud.
  **IA qui partent de travers au départ** : la ligne d'arrivée (et la grille) avait été déplacée sur le vrai départ
  de la map APRÈS « Créer le parcours » : les splines de position / IA partaient toujours de l'ancien endroit (à
  ~150-380 m), les IA fonçaient vers le début de leur spline. L'éditeur signale maintenant une transition éloignée de
  plus de 38 m des splines qu'elle relie (`transitionOffTrack` : au chargement, à l'enregistrement, dans le panneau de
  la zone) avec le bouton « Recréer le parcours depuis cette ligne… ». Règle : placer la ligne d'arrivée PUIS créer
  le parcours. Même avertissement si une zone est **tournée à l'envers** du parcours (map3 : ligne + grille
  retournées de 180° après la création → « mauvais sens » en jeu en roulant dans le sens de la grille).
  **Niveau enfoui sous la route** : Mario Circuit 3 a un sol de sable 1,1 m sous la route ; le tracé suivait le sol
  le plus proche de la ligne d'arrivée (placée à sable + 660) → tracé, zones, caisses (à moitié enfoncées) et booster
  sur le sable. Le tracé prend maintenant la hauteur sur les triangles de route eux-mêmes (`road_loop`, zmap) et le
  placement automatique des caisses la surface la plus haute (`GroundQuery.top`).
  **Raccord aux transitions dans une épingle** : le raccord repérait « avant / après la ligne » par la distance au
  plan de la zone ; dans une épingle la route recoupe ce plan → prolongations de 260 m en ligne droite à travers les
  murs (map3, transition 03). `joinAiSplinesToTransition` mesure désormais tout le long des splines (abscisse
  curviligne : projection de la zone sur la fin des précédentes / le début des suivantes, coupe et prolongation à
  ±M = 1 500 po). map3 régénérée : 0 nœud, segment max 69 m (au lieu de 260).
- **Corrections après essais sur 2 maps importées (2026-10-20)** :
  - *Nœuds des splines IA* : (1) raccord aux transitions qui prenait des points de la spline suivante situés
    ailleurs sur le tour (saut de 230 m) et laissait des points quasi superposés → suite contiguë depuis le point le
    plus proche, points à moins de 5 m fusionnés ; (2) génération : décalage latéral lissé, borné de chaque côté et à
    pente limitée (`_slope_envelope`), plafonné à 60 % du rayon à l'intérieur des virages (au-delà la voie décalée
    boucle) ; (3) `fit_controls` : écart ≈ moitié du rayon de virage (13 m à `spacing`), variation progressive,
    segments voisins dans un rapport ≤ 1,8. Contrôle : `ai_gen.self_crossings` (test : 48 voies très aléatoires,
    0 nœud), et l'éditeur signale les splines nouées après « Régénérer toutes les splines IA ».
  - *Caisse tordue* : `crate_question_001` (19°) et `crate_fruit_1` (9°) sont inclinées pour leur pente d'origine
    (euler +0x64, 2 bits de plus en +0x38) ; déplacées, elles sont remises à plat comme les copies.
  - *Restes de l'ancienne map* (« Nouvelle map », cases « Restes hors décor ») : bateaux / voiles / animaux
    (`_Design_Excl_4p`, `_Design_Exclude_4p`), effets (`_VFX_Core`, `_VFX_PS4_*`), lumières, zones d'ambiance et
    ombres des falaises (`_Lighting*`) : toutes les entités du fichier descendues de 100 000 po (`write_moved_away`),
    rien n'est supprimé (le `_Design` y fait référence). Le ciel (cube de nuages) et l'eau restent.
- **Transparence des textures importées** (découpe alpha : feuillages, herbes, fleurs, grillages) : le matériau des
  feuilles de Crash Cove (`L101_NSanityBeach_materials,T111_VinesLeaf01`) est identique à celui de la roche sauf
  `CAlphaClipBundle._enable` = vrai (seuil 0,5) et l'échantillonnage. Image avec découpe → texture **BC3 1024 + 9
  mipmaps** (gabarit `c1_dirt01_c`, `build_color_texture` gère BC1 et BC3 ; couleur étendue sous les zones
  transparentes, `_bleed_alpha`) + matériau des feuilles **renommé `rockGroundSide`** (même handle que la roche :
  conversion sur place sans ré-importer les modèles). Détection (`image_has_alpha`) : plus de 0,2 % de pixels
  transparents et alpha presque tout-ou-rien (moins de 25 % de valeurs intermédiaires ; un alpha progressif = brillance
  ou masque des textures de jeux, pas de trous dans les routes). Import de dossier : colonne « Transp. » (détectée,
  modifiable) ; mode Décor : « Transparence des textures… » (convertit / reconvertit les textures déjà importées,
  annulable). Mario Circuit : 15 textures détectées (feuilles, herbes, fleurs, grille de départ, grillages, textes) ;
  map3 (export Switch) : aucune image n'a de transparence.
- **Alléger la map** (mode Décor, « Alléger la map… » ; `light_info` / `apply_light`, réglage `<Piste>_light.json`) :
  - collision des murs et décors importés simplifiée par regroupement des sommets sur une grille (`simplify_tris`,
    cellule 20 po : sommets déplacés de ~20 cm, 45 cm au pire ; 40 po : ~35 cm, 1 m au pire). Les surfaces de
    roulage (nom « road » ou ≥ 85 % de surface horizontale, `is_flat`) ne sont jamais simplifiées. map3 : 180 k →
    110 k / 96 k triangles ;
  - textures importées en **512 × 512** (gabarits du jeu `C1_WoodSolid01_C` BC1 / `C1_WoodSolid02_C` BC3, 8 niveaux :
    174 Ko au lieu de 684 Ko), refaites sur place depuis l'image d'origine. Import de dossier : « Taille des
    textures » (auto = 512 pour les textures qui ne servent qu'au décor de fond) ;
  - modèles importés inutilisés (imports retirés du décor) supprimés : la copie « Annuler » les garde.
- **Ambiance jour / soir / nuit** (mode Décor, « 🌅 Ambiance… » ; `ambiance_info` / `set_ambiance`, réglage
  `<Piste>_ambiance.json`) : éclairage = `CWorldVisualDataGroup` « worldVisualData_defaultGroup » de
  `<Piste>_Lighting.igz` (117 réglages : soleil couleur vec4 / intensité / angles, ciel, nuages, brouillard,
  étalonnage exposition / saturation / contraste / teinte, `_toonFade`…). Les boîtes locales (`CVisualDataGroup`)
  ne remplacent que les champs dont « …State » est vrai : ceux-là reçoivent aussi la valeur. Préréglages calés sur
  les pistes du jeu (soir ≈ Dingo Canyon / Out of Time, nuit ≈ Roo's Tubes / Slide Coliseum). Le fichier est
  reconstruit depuis l'original avec, s'il y a lieu, les entités descendues par « Nouvelle map »
  (`rebuild_map_file`). Le ciel (image) ne change pas. Validé en jeu.
- **Plusieurs pistes installées** : `update.pak`, `update2.pak`, `chunkinfos.pak`, `juicedomain_*` sont partagées. Une
  archive est remise à l'origine avant chaque installation : installer Roo's Tubes effaçait ce que Crash Cove y avait
  mis (piste et nom d'origine revenus). `install_plan(piste)` = fichiers de la piste ; `install_track` /
  `uninstall_track` réécrivent chaque archive avec aussi les fichiers des autres pistes installées
  (`installed_tracks` : liste `out/editor/installed_tracks.json` + pistes dont l'archive propre porte une
  installation). Validé en jeu (Crash Cove + Roo's Tubes ensemble). Vidéo du menu mise de côté automatiquement quand le fond est personnalisé (validé en jeu ; la case
  « Essai » a disparu).
- **Ciel** (Ambiance › Ciel) : `CWorldVisualData._farSkyModelName4` du `_Lighting` (« Octane\T111_Skybox ») + modèle
  `sky_model` du manifeste. Roo's Tubes n'en a pas (fond = décor `t112_roos_tube_vista`) : après « Nouvelle map »,
  plus rien derrière la map → grosses traînées en jeu. Choix du ciel d'une autre piste (15 pistes en ont) : nom écrit
  dans le `_Lighting` reconstruit, modèle + matériau + textures déclarés (copiés si absents des archives montées) à
  l'installation (`sky_install_files`) ; « Vérifier » signale une piste vidée sans ciel. 1er essai en jeu : nom seul
  = ciel invisible, piste sombre, traînées (Roo's Tubes : `_skyGradientEnabled` faux, `_skyFade` 1, éclairage de
  grotte, reflets sous-marins). `apply_sky` reprend donc toute l'atmosphère de la piste source : dégradé, sondes de
  reflets (`_environmentMap*`, ajoutées au manifeste / copiées), `_environmentMap1` retiré, et les 222 réglages sans
  pointeur du `CWorldVisualDataGroup` (dont les courbes de 84 o : dégradé du ciel, couleur d'ambiance) ; l'ambiance
  s'applique ensuite. Validé en jeu (Roo's Tubes). Fichier d'éclairage principal = celui du manifeste qui contient
  `CWorldVisualData` (`lighting_file`) : Mystery Caves utilise `_Lighting_New` (son `_Lighting` est vide : le ciel y
  était écrit pour rien). « Vérifier » signale un ciel choisi mais pas écrit (correction en un clic) ; « Nouvelle map »
  sur une piste sans ciel ajoute d'office celui de Crash Cove.
- **Créer le parcours : plusieurs morceaux et sauts** : la fenêtre liste les objets importés (`route_objects` : la
  route d'abord, taille, recherche ; pré-cochés : sélection du mode Décor, sinon route mémorisée) ; tous les morceaux
  cochés forment la route. « Franchir les trous jusqu'à X m » (`route_gen.bridge_gaps`, défaut 40 m) : deux bouts de
  route qui se font face (tremplin / réception, ±35°) et dont le segment traverse un vide sont reliés avant de garder
  le plus grand morceau ; au-dessus du trou le tracé est droit, hauteur interpolée (`air`). Les splines IA du
  parcours gardent cette hauteur (`keep_air`), et aucun point de réapparition n'est posé au-dessus d'un trou
  (`_respawns_on_ground`, `falls.respawn_layout(air=…)` : déplacé à la réception). Tests : stade synthétique avec un
  trou de 15 / 25 / 30 / 40 m ; Roo's Tubes inchangé (3 202 m, aucun faux saut). Validé en jeu.
- **Corrections en un clic** (fenêtre « Vérifier » ; `apply_fixes`, `/api/fix`) : chaque contrôle en défaut porte un
  bouton 🔧. Automatiques, sur la version enregistrée, une seule entrée d'historique (« ↶ Annuler ») : zones
  d'occultation, ciel de Crash Cove, transitions loin de leur spline / à l'envers (`fix_transitions` : point le plus
  proche de la spline de position suivante, cap de la spline), grille (`fix_grid` : disposition d'origine derrière la
  ligne, places à 60 po du sol), caisses au sol (`fix_crates`), plaques des boosters, chutes et réapparitions,
  mini-carte (dans cet ordre, `FIX_ORDER`). Avec un choix à faire : ouvre l'outil (recréer le parcours, régénérer les
  splines IA). « Tout corriger » enchaîne les automatiques, puis la vérification est refaite dans la même fenêtre.
- **Caisses sur une pente** (`powerup.tilt_euler`, `write_crates(..., height_at)`) : à l'enregistrement, chaque caisse
  posée ou déplacée (et TNT / Nitro) est inclinée comme le sol (hauteurs à ±40 po ; Euler +0x60 sans cap, indicateurs
  `TILT_FLAGS` 0x2800 au champ +0x38 comme les caisses inclinées du jeu) ; à plat sous 3° ou au-delà de 35° (mur).
  Calcul vérifié sur les caisses inclinées d'origine : écart médian 1,5°. Avant, une copie gardait l'inclinaison de la
  caisse modèle (Roo's Tubes : toutes inclinées) → de travers et enfoncée. Validé en jeu.
- **Mini-carte, autres pistes** : chaque piste a sa propre orientation d'image et ses propres coins / taille
  (Roo's Tubes : image retournée, 380 × 420) ; l'éditeur transformait SES coins avec la correspondance mesurée sur
  Crash Cove → mini-carte à l'envers. `minimap.REFERENCE` : toutes les pistes reçoivent le réglage de Crash Cove
  (rotation 0, taille 300 × 300, coins, repères) transformé pour le nouveau tracé. Crash Cove : fichier identique.
  Ça ne suffisait pas (essai en jeu : pastilles juste, image retournée de haut en bas) : le jeu n'AFFICHE pas l'image
  de la même façon selon la piste (même en-tête de texture, mêmes réglages). `minimap.choose_orientation` retrouve le
  sens d'affichage sur l'image et le tracé d'origine (8 orientations, recouvrement intersection/union du tracé dessiné
  à la largeur de la route) ; retenu seulement s'il est net (Roo's Tubes : retourné 0,58 contre 0,31), sinon sens de
  Crash Cove + avertissement (Coco Park, Hot Air Skyway, Oxide Station). L'image est rangée avec l'orientation inverse.
- **Occultation** (Nouvelle map › « Zones d'occultation ») : fichiers `*occlusion*` = `COcclusionTrigger` (position,
  taille) qui, une fois traversés, masquent tout ce qui est dans leurs `COcclusionBox` (centre en +0x68). Roo's Tubes :
  route et sol importés disparaissaient selon la caméra. Déclencheurs et boîtes descendus sous la carte comme les
  autres restes ; « Vérifier » prévient si la map est vidée sans ce groupe. Validé en jeu (Roo's Tubes).
- **Images de menu, autres pistes** : nom de texture trouvé par ressemblance (`menu_image_logical` : Roo's Tubes
  « roostube », N. Gin Labs « nginlab », Oxide Station « oxydestation »/« oxidestation ») ; l'index des archives
  couvre toutes les pistes (il n'avait que celle de la 1re piste ouverte). Roo's Tubes : fond et vignette seulement.
- **Grille de départ sur toutes les pistes** : 8 `CWaypoint` aux noms variables (`start_finish.GRID_RE` :
  `Starting_Waypoint_1st`, `AIWaypoint001`, `AI_Waypoint_001`, `StartingPosition_01`, `Grid_Start_Waypoint_001`,
  `StartingWaypoint001`… les 8 plus petits numéros). Dans le `_Design` (13 pistes) ou dans le `_RaceSystem`
  (Sewer Speedway, Slide Coliseum, Turbo Track, Dingo Canyon, N. Gin Labs, Cortex Castle, Barin Ruins, Android Alley :
  `server.grid_file`, écrite dans le RaceSystem en cours d'édition). « Replacer la grille derrière la ligne » part de
  la disposition du jeu d'origine (`original_start`) et pose les places à 60 po du sol. Caisses : type lu dans
  `CCollectibleCrateComponentData._content` (0 « ? », 1 fruits) quand les données ne sont pas partagées (Roo's Tubes).
- **Route qui passe sur elle-même** (pont au-dessus de la route, circuit en 8 ; Roo's Tubes importé) : vu de dessus le
  squelette a un croisement en X. Ancien parcours : branche la plus large d'abord et pixels jamais repassés → coupait
  au plus court (2,1 km au lieu de 3,2 km). `route_gen.walk_graph` : graphe des tronçons entre carrefours
  (`skeleton_graph`, carrefours proches fusionnés, doublons d'un même tronçon éliminés), à chaque carrefour le
  tronçon non emprunté le plus dans l'axe (tangente sur 10 px) puis le plus large ; un carrefour peut être traversé
  plusieurs fois, un tronçon une seule. Sans carrefour : ancien parcours. Hauteur : continuité déjà en place (sur le
  pont au 1er passage, dessous au 2e). Test synthétique « 8 avec pont » dans `test_route_gen.py`.
- **Bibliothèque d'objets du jeu** (mode Décor, « 📚 Objets du jeu » ; `library.py`, `/api/library`,
  `/api/place_library`) : catalogue = modèles `models/levels/` et `models/props/` listés dans les manifestes des 47
  pistes et arènes (~2 800, sans terrain / sections / ombres / collision). Recherche, filtre par piste / dossier,
  aperçu 3D texturé avec la taille, rotation, échelle, « poser le bas sur le sol ». Placement = copie de l'objet
  minimal du fichier `_Art_Core` d'origine avec `_fileName` du modèle de l'autre piste (comme un modèle importé),
  enregistré aussitôt (historique) ; lien `{custom, surface, library: archive}` → collision = son maillage
  (« sans collision » d'office pour feuillage / arbres, modifiable au clic droit). Dépendances : TDEP du modèle
  `materials:/` → `materialinstances/`, TDEP du matériau `textures:/` → `textures/`. À l'installation, tous sont
  déclarés dans le manifeste de la piste ; ceux absents de update2 / update / permanent / l'archive de la piste
  (version d'origine) y sont copiés depuis l'archive de l'autre piste. « Vérifier » les compte. Validé en jeu.
- **Visite virtuelle** (« 🎥 Visite virtuelle » dans Parcours et dans Affichage du mode Décor ; éditeur seulement) :
  la caméra suit les splines de position dans l'ordre de course (`raceChain`), à 2 m au-dessus du sol de collision,
  regard 18 m devant, 25 m/s × vitesse (×0,5 à ×4). Les sections se chevauchent : chacune est coupée au point le
  plus proche du début de la suivante (le tour mesuré est donc plus court que la somme des sections). Barre :
  lecture / pause (Espace), vitesse (↑ ↓), position (curseur, ← → = 20 m), décor / collision / repères affichés ;
  glisser la souris = tourner la tête ; Échap = quitter (caméra et affichage remis comme avant). Signale en direct
  les endroits sans sol sous la ligne (rien, ou sol à plus de 4 m sous la spline) et leur nombre en sortant.
- **Présentation et langues** : barre du haut = onglets Décor / Course, piste, ↶ ↷, puis 💾 Enregistrer, ✔ Vérifier,
  🎮 Installer ; menu « ⋯ » : langue, vue filaire, guide, aide, restaurer les archives, repartir de l'original ;
  barre d'état sous la barre. Panneau latéral : guide « Créer ta piste en 6 étapes » (chaque étape ouvre l'outil
  dans le bon mode), sélection, sections repliables (Parcours, Objets, Boosters, Avancé ; Importer, Préparer,
  Affichage, Rechercher, Avancé). Tous les identifiants d'éléments d'avant sont gardés (le code n'a pas changé).
  Langues : `editor/i18n.js` (servi par `/i18n.js`) traduit à l'affichage (le français reste la langue du code) :
  dictionnaire exact + débuts de messages connus, `MutationObserver` pour les fenêtres créées ensuite, texte
  d'origine mémorisé par nœud (changement de langue sans recharger). Langue mémorisée dans le navigateur
  (`ctr_lang`). Les rapports détaillés du serveur restent en français.
- **Types de sol et menu clic droit** (mode Décor) : valeur d'un triangle de collision = position dans
  `CCollisionMaterialHandleList` de `LooseData/CollisionMaterials.igz` **+ 3** (0 = non défini ; vérifié : Crash Cove
  38 = Sand (route), 13 = Wood (pont), 16 = Respawn (mer), 22 = SpeedBoost (plaques), 4 Default, 5 Grass, 6 Rock,
  11/12 eau, 40 SandWet ; Blizzard Bluff 8 = Snow, 10 = Ice). La collision de Crash Cove a aussi une palette de noms
  (`hknpShapeMaterialStringPalette` : Wood, Default, Sand, Grass, SandWet, WaterDeep, Respawn, WaterDeepSlow,
  SpeedBoost, Rock, Glass, WaterShallow) : les sols hors palette (Terre 7, Asphalte 46, Neige, Glace, Boue, Métal)
  sont marqués « à tester ». `SURFACES`, `/api/set_surface` (liens du décor + collision recalculée),
  `/api/object_alpha`. Clic droit sur un objet : type de sol, collision on/off, texture, image externe,
  transparence, W/E/R, centrer, même modèle, dupliquer, supprimer.
- **Nom et images de la piste dans les menus** (mode Course, « Nom et images de la piste… » ; `menu_assets.py`,
  `menu_info` / `apply_menu`, `test_menu.py`), sans renommer de fichier :
  - nom : `maps/Octane/<P>/<P>_zoneInfo_<en|fr|mx|pt>.lng` (seulement dans `chunkinfos.pak`) = IGZ de 3
    `igLocalizedStringData` : 1er = nom affiché (« Crique Crash »), 2e = indice, 3e = zone. Chaînes en **UTF-8**
    (« Baía do Crash ») alors qu'`IgzFile` les traite en latin-1 → conversion dans `read_name` / `write_name` ;
  - images (textures d'interface BC3 à un niveau, `build_bc3_image`, lignes de haut en bas ; l'aperçu
    `preview.decode_texture` les rend à l'envers) : fond du choix de course `octane_ui_raceselect_bg_<slug>`
    1288 × 1080 (juicedomain_startscreen + onlinemenus), vignette `..._ico_<slug>` 100 × 100 (juicedomain_permanent +
    piste), emblème d'intro `ui_octane_raceintro_icons_<slug>` 164 × 164 (3 juicedomain_race*), tracé du menu
    `..._minimap_<slug>` 600 × 600 = silhouette blanche pleine de la route (générée depuis le parcours) ;
    `<slug>` = nom sans préfixe ni « _ » en minuscules (crashcove) ;
  - installés dans toutes les archives qui les contiennent (`menu_archives`), restaurées par la désinstallation ;
    install / désinstall vérifiés sur des copies de `chunkinfos.pak` et `juicedomain_startscreen.pak` ;
  - le fond animé de l'écran de choix est une vidéo Bink 2 hors archives (`archives/octane_ui_race_select_<piste>.bk2`,
    15 Mo) : non générée (encodeur Bink 2 propriétaire).
- **TNT, Nitro et fruits Wumpa posés** (mode Course, panneau des caisses + placement automatique ; `powerup.EXTRAS`) :
  aucune piste ne pose de TNT / Nitro (armes) ; les modèles viennent du mode « cristaux » des arènes —
  `SpawnedExplosiveCrate_fclaveau` (Desert Storm, TNT) et `SpawnedNitroCrate_01` (Rocky Road) :
  `CSpawnedExplosiveCrateComponentData` (explose au contact, ralentit à 85 %, compte à rebours si on saute dessus) —
  et le fruit posé de Turbo Track (`fruit_1` : `CCollectibleCrateComponentData` contenu 2, une unité, sans
  réapparition). Copiés dans `_Power_Up.igz` comme les boosters (`import_entity`, préfixes `TNT_` / `Nitro_` /
  `Wumpa_`), dépendances TDEP ajoutées. À l'installation : script `common_ExplosiveCrate` (permanent / update),
  modèle `Octane_NitroCrate` + 2 matériaux (update2 ; `C1_Factory_materials,Octane_NitroCrate` n'existe que dans
  `a145_rocky_road.pak` → copié dans l'archive de la piste), script `common_WumpaFruit_Behavior` (update2) déclarés
  dans le manifeste. Non validé en jeu.
- **Chutes et réapparitions** (mode Course, « Chutes et réapparitions… » ; `falls.py`, `auto_falls`, `test_falls.py`),
  d'après le parcours enregistré :
  - points de réapparition (`CPlayerStartEntity` « Respawn_waypointNNN » du `_Design`) tous les ~N m au centre de la
    route, cap dans le sens de la course, rattachés à leur section (`CRaceTrackSplineComponentData._respawnPoints`
    du RaceSystem) ; les 22 d'origine toujours repris, clones `Respawn_waypoint_autoNNN` au besoin (réutilisés aux
    calculs suivants ; ceux en trop sont retirés des listes et posés sur un point utilisé) ;
  - plancher du monde (`CWorldEntityData._killz`, fichier principal, +0x40) 30 m sous le point le plus bas du
    parcours (map3 à z ≈ 7 900 : on tombait 225 m jusqu'à −1 000). Les contrôles (import, création du parcours,
    vérification) lisent le plancher enregistré ;
  - zones de chute : à côté de la route (du bord jusqu'à 40 m), pas de sol à moins de 6 m sous la route → boîte
    (clone de `Respawn_Trigger_Bridge` : `CTriggerVolumeBoxComponentData._dimensions` = tailles complètes, centrée ;
    `CRespawnTriggerComponentData._respawnPoints` = tag `EntityTags::PlayerStart` puis les 3 points précédents),
    sommet 4 m sous la route, 20 m de profondeur ; jamais sur un autre morceau du parcours. map3 : aucune (herbe
    partout) ; Crash Cove d'origine : 23 (eau, falaises). Non validé en jeu.
- **Vitesse de l'éditeur** : collision recalculée seulement si ce dont elle dépend a changé (empreinte + md5 du
  fichier dans `<Piste>_collision_memo.json` : enregistrement du décor 0,3 s au lieu de ~20 s) ; triangles des
  modèles en numpy ; copies « Annuler » : modèles inchangés liés (`os.link`) à la copie précédente ; barre de
  progression (`progress.py`, `GET /api/progress`) ; échelle d'import absurde refusée (route hors 8–80 m) et route
  géante (> 3 km) refusée avant tout calcul.
- **Mini-carte** (mode Course, « Générer la mini-carte » ; `minimap.py`, `/api/minimap`) : `<Piste>_Minimap.igz` =
  entité « Minimap » dont le script (`common_Octane_Minimap`) envoie à l'interface un
  `CGuiEventRacingMinimapSetup` depuis sa mémoire dynamique : +0x00 `_rotationAngle`, +0x04 `_textureSize` (300 ×
  300 sur Crash Cove), +0x0C `_topLeft`, +0x14 `_bottomRight` (vec2), +0x20 matériau, +0x30 sens des pilotes ;
  plus deux repères `MinimapTopLeft` / `MinimapBottomRight`. Image : texture d'interface BC3 800 × 800 à un niveau
  (`texture_build.build_bc3_image`, nouvel encodeur `bc3_encode`). Correspondance monde → image **mesurée** sur
  Crash Cove (tracé calé sur l'image d'origine à 97 %, sans rotation) : u = 0,01491 x + 630,8, v = −0,01491 y + 414,4 ;
  les coins d'origine y tombent à la même échelle → image affine en fonction des coins : coins et repères sont
  transformés par la similitude qui amène le nouveau tracé dans la zone dessinée d'origine (px 476–794 × 64–734),
  l'image est dessinée avec la correspondance composée (route importée vue de dessus, liseré, damier sur la ligne).
  Toujours depuis les fichiers d'origine ; empreinte du tracé mémorisée (`<Piste>_minimap.json`) : la vérification
  avant installation signale une mini-carte absente ou plus à jour. Les autres pistes ont des images tournées et des
  paramètres différents : la correspondance n'est mesurée que pour Crash Cove. **Validé en jeu** (2026-10-21) : les
  pastilles suivent le tracé, à peine trop haut → dessin remonté de 4 px par défaut (`NUDGE_DEFAULT`, dessin seul,
  les coins ne bougent pas) et flèches de réglage fin (2 px, mémorisé dans `<Piste>_minimap.json`, sans historique).
- **Vérification avant installation** (bouton « Vérifier », et automatiquement avant « Installer dans le jeu » ;
  `/api/check`, `preinstall_check`) sur les versions enregistrées : ligne d'arrivée présente ; chaque transition à
  moins de 38 m de sa spline de position suivante et dans son sens, avec des IA suivantes proches ; grille dans le
  sens de la course et près de la ligne ; splines IA sans nœud ni segment de plus de 150 m, splines de départ
  existantes, trajets sur la route (si elle est connue) ; route au-dessus du plancher de chute ; réapparitions avec
  un sol dessous ; caisses ni enfoncées ni à plus de 4 m en l'air ; une plaque par booster ; modèles importés
  présents ; objets importés pas bien sous le plancher. Erreurs en rouge (« Installer quand même »), avertissements,
  et l'action à faire pour chaque problème.
- **Taille des zones de transition à la souris** : zone sélectionnée → « Taille (R) » : poignées du gizmo en repère
  local (rouge = profondeur, vert = largeur, bleu = hauteur, cube central = tout), dimensions mises à jour en direct
  (minimum 100 po), boîte reconstruite à la fin du glisser, Ctrl+Z annule. Les champs numériques restent.
- **Boosters (plaques turbo)** (mode Course, panneau « Boosters » ; `powerup.py`, même fichier `_Power_Up.igz`) :
  dans le jeu, une plaque turbo est une `CGameEntity` du `_Design` de certaines pistes (Sewer Speedway, N. Gin Labs,
  Oxide Station…) : `CTriggerVolumeBoxComponentData` (dimensions profondeur / largeur / hauteur) +
  `CVscComponentData` « Scripts.Graph.common_TurboPadData » dont la mémoire dynamique porte 8 handles EXID
  (`common_TurboPad::TurboPad_KartBoostData` / `SuperTurboPad_…`, vibration `ctr_pwrup_turboboost_rumble` dans
  permanent.pak, 4 sons des banques communes) et `_meta` (RNEX) = `common_TurboPad::common_KartBoostData`. Le script
  `vsc/common/race/common_turbopad.igz` est déjà dans update.pak : il suffit de le déclarer au manifeste (fait à
  l'installation) et d'ajouter 2 TDEP. **Copie inter-fichiers** `IgzFile.import_entity` : objets + blocs mémoire
  propres à l'entité (taille réelle d'un bloc = jusqu'au bloc suivant), remappage RVTB (types ajoutés avec la taille
  du fichier source), ROFS, RSTT, RHND (bit 31 = EXNM drapeau 1, sinon EXID, entrées ajoutées), RNEX (rang parmi
  les entrées EXNM à drapeau 0 — EXNM contient deux listes mêlées), RPID tel quel ; racines renommées. Modèle :
  `GPI_SpeedBoostZone006` de Sewer Speedway. Dessin au sol : modèle importé « BoostPad » (plaque 100 × 100 po,
  texture générée à partir du masque de chevrons `oct_turbo_pad_ec` du jeu), un objet de décor `BoostPad_Visual_NNN`
  sans collision par booster (`sync_boost_visuals`). Éditeur : « + Booster » (au centre de la vue, posé au sol,
  orienté sur la spline de position la plus proche), W / E / R (poignées de taille), « Aligner sur la course »,
  Inser / Suppr. Tests : `test_powerup.py` (copie identique champ par champ, 8 références, script, TDEP).
  **Validé en jeu** (2026-10-21) : le turbo fonctionne. La plaque était invisible : posée sur un niveau de collision
  enfoui 1,1 m sous la route (sable de Mario Circuit 3) ; plaque et pose au sol de l'éditeur prennent désormais la
  surface la plus haute qui ne dépasse pas le point visé de plus de 300 po (`GroundQuery.top`, `groundZ`), et
  chaque enregistrement replace une plaque qui n'est plus à jour. Plaque visible en jeu ensuite, mais chevrons
  vers l'arrière : `build_model` écrit `1 − v` (convention OBJ), le placage UV de la plaque est maintenant inversé
  en conséquence (`BOOST_MODEL_VERSION` = 2 : modèle reconstruit au prochain enregistrement). Le turbo agit dans les
  deux sens : le script du jeu (`common_turbopad`) ne teste pas la direction du kart. **Synchronisation dans les
  deux sens** : enregistrer en mode Course replace les plaques (`sync_boost_visuals`) ; enregistrer en mode Décor
  met à jour les boosters d'après leurs plaques (`boosts_from_decor` : déplacer, tourner, redimensionner, dupliquer,
  supprimer une plaque = idem pour son booster ; hauteur de zone gardée) et l'éditeur recharge la course.
- **Caisses d'objets** (mode Course, panneau « Caisses d'objets » ; `powerup.py`, fichier `<Piste>_Power_Up.igz`,
  déjà dans le manifeste) : 21 `CGameEntity` sur Crash Cove, « crate_question_NNN » (caisses « ? ») et
  « crate_fruit_N » ; position à +0x20 (au sol, 0 à 16 po au-dessus), transformation et liste de composants propres,
  données partagées par type (`PowerUpCrate_entityData_gen` / `WumpaFruitCrate_entityData_gen`). Ajout = copie d'une
  caisse d'origine du même type ; le fichier est reconstruit depuis l'original à chaque enregistrement
  (`write_crates`). Éditeur : clic pour sélectionner, W déplacer, Inser dupliquer, Suppr, type, « Poser au sol »
  (collision affichée) ; « Placement automatique… » (`/api/crates_auto`, `auto_rows`) = rangées en travers de la
  route le long des splines de position depuis la ligne d'arrivée (`chain_paths` retire leurs chevauchements), écart
  réduit si la route est étroite, caisses de fruits isolées en option. Tests : `test_powerup.py`. **Validé en jeu**
  (2026-10-20) : caisses placées et ajoutées visibles et fonctionnelles sur le circuit importé.
  **Caisses dans le `_Design`** (Coco Park, Turbo Track, Blizzard Bluff : `_Power_Up` vide, un seul objet sans
  table de noms) : `server.crate_file` choisit le fichier des caisses (le `_Power_Up` s'il a des noms, sinon le
  `_Design` s'il porte des caisses « ? » / fruits). Dans le `_Design`, `read_crates(..., crates_only=True)` ne garde
  que caisses / boosters / TNT / Nitro / fruits, et `write_crates(..., crates_only=True, keep_tilt=...)` repart du
  fichier **enregistré** (pas de l'original) : grille, réapparitions, arrivées de téléporteur et autres entités
  restent intactes ; les caisses déjà posées sont ré-inclinées selon le sol actuel. Boosters et extras y sont
  importés comme dans le `_Power_Up` (manifeste : script turbopad). Testé sur copie (import de pack + caisse
  déplacée + booster ajouté sur les 3 pistes, contrôle avant installation sans erreur) ; **non validé en jeu**.
- **Compactage des fichiers IGZ** (`IgzFile.compact`, `server.safe_compact` à l'enregistrement de RaceSystem et
  TTRStats) : les réécritures (listes racine, tables de noms, listes de poignées) abandonnaient l'ancien bloc à chaque
  appel ; après une régénération complète, TTRStats 37 Ko → 2,4 Mo, RaceSystem 103 Ko → 1,7 Mo. Les blocs
  abandonnés sont notés (`_free`) et retirés s'ils ne sont ni atteignables ni visés par un pointeur vivant ;
  pointeurs (ROFS) et racines (ROOT, ONAM) renumérotés, alignement modulo 16 conservé. Mode complet (tout le non
  atteignable, pour les déchets des versions précédentes) seulement si l'original du fichier en ressort identique
  (vrai pour Crash Cove ; faux pour Cortex Castle / N. Gin Labs RaceSystem, qui ont 48-64 octets non atteignables).
  Pas pour les fichiers `_Art` (l'id d'un objet est son adresse). 1200 fichiers d'origine inchangés. Tests :
  `test_compact.py`.
- **Textures dans l'éditeur** (`preview.py`, `/api/model_preview`, `/api/texture`, case « Afficher les textures du
  jeu ») : chaque modèle est envoyé avec ses UV (half2, 1er jeu) et un groupe par draw call ; la texture « ColorMap »
  du matériau de chaque draw call (matériau trouvé par son nom dans le fichier `materialinstances`, qui peut en
  contenir plusieurs) est décodée en PNG RGBA (BC1 avec transparence 1 bit, BC3 avec alpha) au niveau de mipmap
  ≤ 256 px, cache disque `out/editor/cache/textures/`. Crash Cove : 122 modèles, 243/244 parties texturées,
  76 textures (~4 s la première fois). Décals (effet GBufferDecal : sable, piste, herbe) en fondu par-dessus le sol,
  le reste avec transparence par seuil (feuillage). La collision grise est reculée et masquable en mode Décor.
  Approximations : texture couleur seule (pas de normales ni d'éclairage du jeu), shaders mélangés = 1re texture.
  Tests : `test_preview.py`.
- **Export pour Blender** (`obj_export.py`, bouton « Exporter pour Blender… », `/api/export_obj`) :
  `out/blender/<Piste>_reference.obj` + `.mtl`, dans les conventions inverses de l'import (mètres, Y haut :
  (X, Y, Z)_jeu → (X, Z, −Y) / 39,37, rotation donc ordre des sommets conservé). Contenu : collision du sol (un objet
  et une couleur par surface), splines en arêtes (course en bleu, IA en orange), décor : complet (défaut : les 6
  fichiers `_Art` + les autres fichiers de carte qui placent des modèles, ex. `_Lighting` ; Crash Cove ≈ 4 870 objets,
  5,2 M triangles, 290 Mo en ~15 s, écrit au fil de l'eau, sommets du décor à 0,1 mm), aucun, ou boîtes
  englobantes. Non exportés : entités animées (`_Animation`) et objets de gameplay (caisses, bonus, reliques). **Axe vertical** au choix (`up` : Y = Blender par défaut, ou Z) : il doit être le même que « Up » dans
  l'importeur OBJ de Blender (réglage mémorisé par Blender), sinon la piste apparaît debout.
  Versions enregistrées utilisées. Crash Cove (collision + splines + boîtes Art_Core) : 1,2 Mo en ~1 s.
  Une scène modélisée autour et importée en « coordonnées de l'OBJ » tombe au même endroit. Tests : `test_obj_export.py`
  (19 034 triangles de collision relus à 3·10⁻⁵ po près).
- **Fichiers de décor compacts** (`server.write_art`) : chaque enregistrement / import reconstruit le `_Art*.igz`
  depuis l'original (suppressions, transformations, puis toutes les copies en un passage `duplicate_many` + une
  seule réécriture de la liste racine `add_roots`). Avant, chaque `add_root` abandonnait l'ancienne liste racine et
  la table des noms (~24 o × ~3 000 racines, 5 à 7 fois par objet) : 6 objets importés = Art_Core 0,72 → 3,7 Mo,
  et chargement infini en jeu (budget mémoire probable). Les ids des objets ajoutés changent : liens remappés.
- **Sélection multiple** (mode Décor) : Maj+clic ajoute/retire, Échap désélectionne, « Sélectionner les N
  résultats » dans la recherche ; le groupe se déplace / tourne autour de son centre, se duplique, se supprime.
  Après un import, tous les objets importés sont sélectionnés.
- **Manifeste de streaming** (`pkg_manifest.py`) : `packages/generated/maps/Octane/<Piste>/<Piste>_pkg.igz` =
  `igStreamingChunkInfo._required`, vecteur de paires (type, chemin en minuscules) ; **le jeu ne charge que les
  fichiers listés** (un modèle ajouté sans entrée est invisible, alors que sa collision marche). L'installation y
  ajoute une entrée `model` par modèle importé utilisé. Tests : `test_pkg_manifest.py`.

## Reste à faire
Tester en jeu ; nouvelles entités (checkpoints, transitions, splines entières) ; écriture de la collision Havok
(nouvelle géométrie) ; import de modèles ; LOD/variantes pour alléger la géométrie.
