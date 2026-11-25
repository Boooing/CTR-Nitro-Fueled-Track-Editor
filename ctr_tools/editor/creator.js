// ---- onglet « Création » : un paveur qu'on conduit dans la vue 3D trace la piste (facon ModNation Racers) --------
// Mode Route — clavier : ↑/Z/W avancer (pose la route), ↓/S reculer (efface), ←/Q/A et →/D tourner, R monter,
// F descendre, + / - largeur, Entrée fermer la boucle, Maj plus vite, C camera libre / poursuite. Manette : touches au
// choix (Fichier › Manette, PAD_ACTIONS) ; par defaut gachette droite avancer, gauche reculer, stick gauche tourner,
// stick droit monter / descendre, A saut, X plus vite, LB / RB largeur, Y fermer, B camera, croix ← → annuler / retablir.
// Mode Terrain — pinceaux a la souris (clic gauche maintenu) sur une grille de relief : monter, creuser, aplanir,
// lisser, peindre le sol (sable, sable mouille, herbe, roche).
// Le trace (points tous les 4 m : x, y, z, largeur en pouces, repere du jeu z vers le haut) et le terrain (hauteurs
// relatives au sol de depart, matieres) sont envoyes au serveur (/api/create_build) qui genere route, terrain raccorde
// a la route et sol ; la page cree ensuite le parcours (onGenerate).
import { createClay } from '/clay.js';
const IN = 39.37;
const STEP = 4 * IN;                 // un point enregistre tous les 4 m
const SPEED = 35 * IN;               // vitesse du paveur (po/s), Maj : x2
const R_MIN = 30 * IN;               // rayon de virage minimal a plat (karts et IA doivent suivre)
const R_SLOPE = 1.2;                 // en pente : rayon minimal x (1 + R_SLOPE * pente / pente max) (montee + virage serre = kart bloque)
const SLOPE_MAX = 0.28;              // pente maximale (28 %)
const SLOPE_RATE = SLOPE_MAX / (40 * IN);   // variation de pente par pouce parcouru : 0 -> 28 % sur 40 m
const KICK_H = 5 * IN, KICK_LEN = 30 * IN;  // tremplin avant un saut, courbe (track_creator : KICK_H, KICK_LEN ; 3 / 22 droit avant le 2026-11-14)
const H_MAX = 300 * IN;              // hauteur maximale au-dessus du sol de depart
const H_MIN = 200 * IN;              // profondeur maximale sous le sol de depart (le terrain se creuse autour de la route)
const ROLL_MAX = 30 * Math.PI / 180; // inclinaison maximale de la route sur le cote
const ROLL_RATE = ROLL_MAX / (40 * IN);    // variation par pouce parcouru : 0 -> 30 degres sur 40 m
const W_MIN = 40 * IN, W_MAX = 120 * IN, W_DEF = 65 * IN;
const CLOSE_DIST = 35 * IN, CLOSE_MIN_LEN = 250 * IN;
// terrain : grille carree centree sur le depart
const T_CELL = 8 * IN;               // maille du terrain (8 m) ; cote au choix (carre de base), 1,6 km par defaut
const T_SIZES = [1200, 1600, 2000, 2400, 2800, 3200];  // m (3,6 et 4 km retires le 2026-11-08 : trop grands pour le jeu)
const FAR_TRIM_M = 400, FAR_TRIM_SHARE = 0.25;          // generation : retrait propose si au moins ce quart de la carte est a plus de 400 m de la route
const SINK_UNDER_ROAD = 0.25 * IN, BLEND_MIN = 6 * IN;   // raccord route -> terrain (track_creator)
const CAT_VERSION = 2;                 // catalogue du decor (track_creator.CATALOG_VERSION) : objets semes marques c = 2
const BLEND_DEF = 0.75, SCULPT_FULL = 3 * IN;   // largeur du talus par m de denivele ; relief sculpte qui garde sa hauteur pres de la route
// largeur du raccord route -> relief (pouces) pour un denivele dz (track_creator._blend_width idem, 2026-11-16 : sur un
// relief sculpte le raccord tombait a BLEND_MIN pour une maille de 8 m -> saccades / dents de scie au bord de la route)
const SCULPT_KEEP = 0.5, RAMP_CELLS = 2.5, RAMP_DZ = 4 * IN;
const blendWidth = (dz, free, slope, cell) => Math.max(BLEND_MIN, Math.min(1, dz / RAMP_DZ) * RAMP_CELLS * cell,
                                                       dz * slope * (SCULPT_KEEP + (1 - SCULPT_KEEP) * free));
const FADE_DEF = 4, MIX_MAX = 24;               // fondu entre peintures (track_creator : FADE_DEF, MIX_MAX)
const T_LO = -200 * IN, T_HI = 300 * IN;    // relief : memes limites que la route (H_MIN, H_MAX)
let MATERIALS = [                     // ordre = indice de peinture (matieres du kit, track_creator.KITS ; remplacees a l'ouverture)
  { key: 'sand', label: 'Sable', color: [0.85, 0.71, 0.49] },
  { key: 'wetsand', label: 'Sable mouillé', color: [0.62, 0.50, 0.34] },
  { key: 'grass', label: 'Herbe (ralentit)', color: [0.42, 0.60, 0.24] },
  { key: 'rock', label: 'Roche', color: [0.52, 0.50, 0.47] }];
// peintures de TOUS les themes, apres celles du theme : indice MATERIALS.length + rang (track_creator.paint_materials)
let EXTRA_MATS = [];
// dig : sous une route en hauteur, le sol n'est plus colle a la route (relief garde, route en pont) ; fill : l'inverse
const TOOLS = [['stretch', '✋ Étirer'], ['raise', '⬆ Monter'], ['lower', '⬇ Creuser'], ['flatten', '▬ Aplanir'], ['smooth', '〰 Lisser'],
               ['dig', '⛏ Creuser sous la route'], ['fill', '↺ Reboucher sous la route'], ['water', '💧 Remplir d\'eau']];

// ---- manette : chaque action lit une entree, bouton (b) ou demi-axe (a + sens s), valeur 0..1. Touches au choix,
// gardees dans le navigateur (localStorage) ; numeros = disposition standard (Xbox : 0 A, 1 B, 2 X, 3 Y, 4 LB,
// 5 RB, 6 LT, 7 RT, 8 Back, 9 Start, 10 / 11 clic des sticks, 12-15 croix haut / bas / gauche / droite) ----
export const PAD_ACTIONS = [
  ['forward', 'Avancer (pose la route)', { b: 7 }], ['reverse', 'Reculer (efface)', { b: 6 }],
  ['left', 'Tourner à gauche', { a: 0, s: -1 }], ['right', 'Tourner à droite', { a: 0, s: 1 }],
  ['up', 'Monter', { a: 3, s: -1 }], ['down', 'Descendre', { a: 3, s: 1 }],
  ['jump', 'Saut (trou dans la route)', { b: 0 }], ['fast', 'Plus vite', { b: 2 }],
  ['wider', 'Élargir la route', { b: 5 }], ['narrower', 'Rétrécir la route', { b: 4 }],
  ['close', 'Fermer la boucle', { b: 3 }], ['camera', 'Caméra libre / poursuite', { b: 1 }],
  ['bankLeft', 'Incliner la route à gauche', { b: 12 }], ['bankRight', 'Incliner la route à droite', { b: 13 }],
  ['undo', '↶ Annuler', { b: 14 }], ['redo', '↷ Rétablir', { b: 15 }]];
const PAD_KEY = 'ctr_pad_map', PAD_DEAD = 0.2;
export function loadPadMap() {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(PAD_KEY) || '{}') || {}; } catch (e) { /* sans importance */ }
  return Object.fromEntries(PAD_ACTIONS.map(([k, , d]) => [k, k in saved ? saved[k] : d]));
}
export function savePadMap(m) { try { localStorage.setItem(PAD_KEY, JSON.stringify(m)); } catch (e) { /* sans importance */ } }
export const padDefaults = () => Object.fromEntries(PAD_ACTIONS.map(([k, , d]) => [k, d]));
// peripherique utilise : celui choisi dans Fichier › Manette (garde par son nom), sinon une vraie manette
// (disposition « standard ») avant tout autre peripherique vu comme manette (casque audio, volant...)
const PAD_DEV_KEY = 'ctr_pad_device';
export const listPads = () => [...(navigator.getGamepads?.() || [])].filter(p => p && p.connected);
export function padDevice() { try { return localStorage.getItem(PAD_DEV_KEY) || ''; } catch (e) { return ''; } }
export function setPadDevice(id) { try { id ? localStorage.setItem(PAD_DEV_KEY, id) : localStorage.removeItem(PAD_DEV_KEY); } catch (e) { /* sans importance */ } }
export function firstPad() {
  const pads = listPads(), want = padDevice();
  return (want && pads.find(p => p.id === want)) || pads.find(p => p.mapping === 'standard') || pads[0] || null;
}
export function padValue(pad, b) {
  if (!pad || !b) return 0;
  if (b.b != null) return pad.buttons[b.b]?.value || (pad.buttons[b.b]?.pressed ? 1 : 0);
  const v = (pad.axes[b.a] || 0) * b.s;
  return v > PAD_DEAD ? (v - PAD_DEAD) / (1 - PAD_DEAD) : 0;
}
export const padLabel = b => !b ? '—' : b.b != null
  ? ({ 0: 'A', 1: 'B', 2: 'X', 3: 'Y', 4: 'LB', 5: 'RB', 6: 'LT', 7: 'RT', 8: 'Back', 9: 'Start', 10: 'L3', 11: 'R3',
       12: 'Croix ↑', 13: 'Croix ↓', 14: 'Croix ←', 15: 'Croix →' }[b.b] ?? `Bouton ${b.b}`)
  : ({ 0: 'Stick G', 1: 'Stick G', 2: 'Stick D', 3: 'Stick D' }[b.a] ?? `Axe ${b.a}`) + ' ' +
    (b.a % 2 ? (b.s < 0 ? '↑' : '↓') : (b.s < 0 ? '←' : '→'));

export function initCreator(ctx) {
  const { THREE, scene, camera, orbit, view, renderer, api, status, ask, choose, getTrack, getStart, onGenerate, chooseTarget, createTarget } = ctx;
  const group = new THREE.Group(); group.visible = false; scene.add(group);
  // caisses et boosters prevus par la piste aleatoire (S.items) : apercu, poses a « Generer la piste »
  const itemGroup = new THREE.Group(); group.add(itemGroup);
  // reperes grossis (comme ceux de l'Edition) pour etre vus de loin : caisse « ? » jaune, caisse de fruits verte, fruit orange
  const crateTex = (bg, txt) => { const cv = document.createElement('canvas'); cv.width = cv.height = 64; const g = cv.getContext('2d');
    g.fillStyle = bg; g.fillRect(0, 0, 64, 64); g.strokeStyle = '#5a3a10'; g.lineWidth = 6; g.strokeRect(3, 3, 58, 58);
    g.fillStyle = '#fff'; g.font = 'bold 42px sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(txt, 32, 35);
    const t = new THREE.CanvasTexture(cv); t.colorSpace = THREE.SRGBColorSpace; return new THREE.MeshBasicMaterial({ map: t }); };
  const ITEM_LOOK = {
    question: [new THREE.BoxGeometry(150, 150, 150), crateTex('#f0a020', '?'), 75],
    fruit: [new THREE.BoxGeometry(150, 150, 150), crateTex('#3aa84a', 'W'), 75],
    wumpa: [new THREE.SphereGeometry(45, 12, 10), new THREE.MeshBasicMaterial({ color: 0xff6a1a }), 50] };
  // booster : comme dans l'Edition (zone en boite orange translucide + aretes, plaque pleine, fleche) ; une plaque seule,
  // orange pale a plat, se perdait sur le sable (retour utilisateur 2026-11-16 « je ne vois pas les boosters »)
  const BOOST_MAT = new THREE.MeshBasicMaterial({ color: 0xff6a00, side: THREE.DoubleSide });
  const BOOST_ZONE = new THREE.MeshBasicMaterial({ color: 0xff7a1a, transparent: true, opacity: 0.28, depthWrite: false });
  const BOOST_EDGE = new THREE.LineBasicMaterial({ color: 0xffe27a });
  const ARROW_MAT = new THREE.MeshBasicMaterial({ color: 0xffffff, side: THREE.DoubleSide, depthWrite: false });
  // caisses et boosters reposes sur la route telle qu'elle est affichee (effPoints : tremplins, bords releves, relief et
  // decor du tirage appliques). 2026-11-16 : leur hauteur venait du trace AVANT ces retouches -> plaques des boosters 2 a 5 m
  // SOUS la route, invisibles. Point de route le plus proche en plan ET en hauteur (ponts : pas la route du dessus) ;
  // hauteur au decalage lateral (bord releve) ; inclinaison : pente sur ~16 m et pente laterale (comme « Poser au sol »)
  function seatItems(it) {
    const E = S.points.length > 1 ? effPoints() : null, n = E?.length || 0;
    if (!n) return;
    const near = p => { let k = -1, best = Infinity;
      for (let i = 0; i < n; i++) { const q = E[i], d = Math.hypot(q[0] - p[0], q[1] - p[1]);
        if (d > q[3] / 2 + 10 * IN) continue;
        const c = d + 3 * Math.abs(q[2] - p[2]); if (c < best) { best = c; k = i; } }
      return k; };
    const at = i => E[((i % n) + n) % n];
    const zOf = (q, x, y) => { const off = (x - q[0]) * q[6] + (y - q[1]) * q[7];
      return q[2] + q[5] * Math.max(-1, Math.min(1, off / (q[3] / 2))); };
    for (const o of [...(it.boosts || []), ...(it.crates || [])]) {
      const k = near(o.pos);
      if (k < 0) continue;
      const q = E[k];
      o.pos = [o.pos[0], o.pos[1], zOf(q, o.pos[0], o.pos[1])];
      if (o.kind === 'wumpa') continue;
      // pente : meme decalage lateral, 2 points avant / apres
      const off = (o.pos[0] - q[0]) * q[6] + (o.pos[1] - q[1]) * q[7], a = at(k - 2), b = at(k + 2);
      const za = a[2] + a[5] * Math.max(-1, Math.min(1, off / (a[3] / 2))), zb = b[2] + b[5] * Math.max(-1, Math.min(1, off / (b[3] / 2)));
      const d = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
      // pente dans le sens de l'objet (yaw) et laterale (bord releve), projetees sur ses axes
      const tx = (b[0] - a[0]) / d, ty = (b[1] - a[1]) / d, sAlong = (zb - za) / d, sLeft = q[5] / (q[3] / 2);
      const c = Math.cos(o.yaw || 0), s = Math.sin(o.yaw || 0);
      // gradient du sol (monde) = sAlong * t + sLeft * gauche(t) ; sur les axes de l'objet : avant (c, s), gauche (-s, c)
      const gx = sAlong * tx - sLeft * ty, gy = sAlong * ty + sLeft * tx;
      const fwd = gx * c + gy * s, left = -gx * s + gy * c, L = Math.hypot(fwd, left, 1);
      const rx = Math.asin(Math.max(-1, Math.min(1, left / L))), ry = Math.atan2(-fwd / L, 1 / L);
      o.tilt = Math.max(Math.abs(rx), Math.abs(ry)) > 35 * Math.PI / 180 ? [0, 0] : [+rx.toFixed(4), +ry.toFixed(4)];
    }
  }
  function renderItems() {
    itemGroup.clear();
    const it = S.items;
    if (!it || it.v !== 2) return;
    seatItems(it);
    for (const c of it.crates || []) {
      const [geo, mat, lift] = ITEM_LOOK[c.kind] || ITEM_LOOK.question, m = new THREE.Mesh(geo, mat);
      // inclinee comme la route (meme convention que le jeu : R = Rz Ry Rx -> ordre 'ZYX' de three.js)
      const [rx, ry] = c.tilt || [0, 0];
      m.position.set(c.pos[0], c.pos[1], c.pos[2] + 8 + lift); m.rotation.set(rx, ry, c.yaw || 0, 'ZYX'); itemGroup.add(m);
    }
    for (const b of it.boosts || []) {
      // plaque et fleche dans un repere incline comme la route (« Poser au sol »)
      const [rx, ry] = b.tilt || [0, 0], box = new THREE.Group();
      box.position.set(b.pos[0], b.pos[1], b.pos[2]); box.rotation.set(rx, ry, b.yaw, 'ZYX');
      const pad = new THREE.Mesh(new THREE.PlaneGeometry(b.dims[0], b.dims[1]), BOOST_MAT);
      pad.position.z = 14; pad.renderOrder = 2; box.add(pad);
      const s = new THREE.Shape(); s.moveTo(b.dims[0] * 0.35, 0); s.lineTo(-b.dims[0] * 0.25, b.dims[1] * 0.25); s.lineTo(-b.dims[0] * 0.25, -b.dims[1] * 0.25);
      const arrow = new THREE.Mesh(new THREE.ShapeGeometry(s), ARROW_MAT);    // fleche : sens du turbo
      arrow.position.z = 16; arrow.renderOrder = 3; box.add(arrow);
      const zg = new THREE.BoxGeometry(b.dims[0], b.dims[1], b.dims[2]), zone = new THREE.Mesh(zg, BOOST_ZONE);
      zone.position.z = b.dims[2] / 2; zone.renderOrder = 4; box.add(zone);
      const edges = new THREE.LineSegments(new THREE.EdgesGeometry(zg), BOOST_EDGE); edges.position.z = b.dims[2] / 2; box.add(edges);
      itemGroup.add(box);
    }
  }
  const S = { active: false, mode: 'route', points: [], closed: false, pos: null, yaw: 0, slope: 0, width: W_DEF, groundZ: 0,
              keys: new Set(), back: 0, chase: true, start: null, last: 0, warned: 0, savedVis: null,
              tool: 'raise', radius: 30 * IN, strength: 0.5, paint: 2, brushing: false, flatZ: null, mouse: null,
              terrain: null, dirtyT: false, lastNormals: 0, padMap: loadPadMap(), padWas: null };
  addEventListener('ctr-pad-map', () => { S.padMap = loadPadMap(); });      // touches changees (Fichier › Manette)

  // terrain (aperçu fidele : relief raccorde a la route comme a la generation, vraies textures du theme par matiere,
  // ombrage calcule a la main dans la couleur des sommets), paveur, route
  let terrainGeo = new THREE.BufferGeometry();
  const terrainMesh = new THREE.Mesh(terrainGeo, [new THREE.MeshBasicMaterial({ color: 0xc9a46f, vertexColors: true })]);
  // textures du theme (meme decodage que la generation) : route, matieres du sol
  const kitTex = {};
  function kitTexture(png, kit = $('crkit').value) {      // kit : theme d'une peinture d'un autre theme
    const key = kit + '|' + png;
    return kitTex[key] ??= (() => { const t = texLoader.load(`/api/creator_texture?kit=${kit}&f=${png}`);
      t.colorSpace = THREE.SRGBColorSpace; t.wrapS = t.wrapT = THREE.RepeatWrapping; t.anisotropy = 8; return t; })();
  }
  const far = new THREE.Mesh(new THREE.PlaneGeometry(8000 * IN, 8000 * IN), new THREE.MeshBasicMaterial({ color: 0xc9a46f }));
  // paveuse : kart du jeu a l'echelle 1:1 (charge depuis le serveur ; boite jaune en attendant) + racle a l'arriere,
  // de la largeur de la route
  const paver = new THREE.Group(); paver.rotation.order = 'ZYX';
  const KART_SCALE = 2;                                       // kart a l'echelle x2 (bien visible sur une route de 55 m)
  const kart = new THREE.Group(); kart.scale.setScalar(KART_SCALE); paver.add(kart);
  const body = new THREE.Mesh(new THREE.BoxGeometry(4 * IN, 2.4 * IN, 1.4 * IN), new THREE.MeshBasicMaterial({ color: 0x3a3d42 }));
  body.position.z = 0.7 * IN; kart.add(body);
  // racle (finisseur) : poutre a bandes de danger de la largeur de la route, flasques, dents, bras d'attelage
  const hazardTex = (() => {
    const c = document.createElement('canvas'); c.width = 128; c.height = 32;
    const x = c.getContext('2d'); x.fillStyle = '#f2b705'; x.fillRect(0, 0, 128, 32); x.fillStyle = '#1b1b1b';
    for (let i = -32; i < 160; i += 32) { x.beginPath(); x.moveTo(i, 32); x.lineTo(i + 16, 32); x.lineTo(i + 32, 0); x.lineTo(i + 16, 0); x.fill(); }
    const t = new THREE.CanvasTexture(c); t.wrapS = THREE.RepeatWrapping; t.colorSpace = THREE.SRGBColorSpace; return t;
  })();
  const steelMat = new THREE.MeshLambertMaterial({ color: 0x4a4e55 }), beamMat = new THREE.MeshLambertMaterial({ map: hazardTex });
  const screed = new THREE.Group(); screed.position.set(-7.6 * IN, 0, 0); paver.add(screed);
  function buildScreed(w) {
    screed.clear();
    // faces avant / arriere (+-x, le long de la largeur) a bandes de danger ; dessus, bouts, dessous en acier
    const beam = new THREE.Mesh(new THREE.BoxGeometry(1.4 * IN, w, 0.9 * IN), [beamMat, beamMat, steelMat, steelMat, steelMat, steelMat]);
    hazardTex.repeat.set(w / (3 * IN), 1); beam.position.z = 0.75 * IN;
    screed.add(beam);
    const plate = new THREE.BoxGeometry(2.2 * IN, 0.25 * IN, 1.5 * IN);
    for (const s of [1, -1]) { const p = new THREE.Mesh(plate, steelMat); p.position.set(0.2 * IN, s * (w / 2 + 0.12 * IN), 0.75 * IN); screed.add(p); }
    const tooth = new THREE.BoxGeometry(0.5 * IN, 0.35 * IN, 0.45 * IN), n = Math.max(2, Math.floor(w / (1.6 * IN)));
    for (let i = 0; i < n; i++) { const t = new THREE.Mesh(tooth, steelMat); t.position.set(-0.4 * IN, -w / 2 + (i + 0.5) * w / n, 0.15 * IN); screed.add(t); }
    for (const s of [1, -1]) {                                // bras du kart (arriere, ~ -2,7 m x2) a la poutre
      const arm = new THREE.Mesh(new THREE.BoxGeometry(2.6 * IN, 0.35 * IN, 0.35 * IN), steelMat);
      arm.position.set(1.9 * IN, s * 1.6 * IN, 1.1 * IN); arm.rotation.z = -s * 0.25; screed.add(arm);
    }
  }
  // pieces du kart (format de model_preview_binary) ; tint : la texture du kart est surtout blanche / grise, la
  // couleur d'equipe etant appliquee en jeu par une palette -> teinte orange de Crash a la place
  const texLoader = new THREE.TextureLoader();
  async function kartPart(part, tint) {
    const res = await fetch('/api/kart?part=' + part);
    if (!res.ok) throw new Error(`kart ${part} : ${res.status}`);
    const buf = await res.arrayBuffer(), dv = new DataView(buf);
    const nv = dv.getUint32(0, true), ni = dv.getUint32(4, true), ng = dv.getUint32(8, true);
    let o = 12;
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(buf, o, nv * 3), 3)); o += nv * 12;
    g.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(buf, o, nv * 2), 2)); o += nv * 8;
    g.setIndex(new THREE.BufferAttribute(new Uint32Array(buf, o, ni), 1)); o += ni * 4;
    for (let i = 0; i < ng; i++, o += 12) g.addGroup(dv.getUint32(o, true), dv.getUint32(o + 4, true), dv.getUint32(o + 8, true));
    const texs = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, o + 4, dv.getUint32(o, true))));
    g.computeVertexNormals();
    // livree « voiture de course » : gris fonce, bande blanche au centre du dessus (couleur par sommet, multipliee
    // par la texture du jeu, presque blanche : la couleur d'equipe est une palette en jeu)
    const livery = part === 'body';
    if (livery) {
      const pos = g.attributes.position, col = new Float32Array(pos.count * 3);
      for (let i = 0; i < pos.count; i++) {
        const stripe = Math.abs(pos.getY(i)) < 9 && pos.getZ(i) > 22;
        col.set(stripe ? [0.95, 0.95, 0.95] : [0.2, 0.21, 0.23], i * 3);
      }
      g.setAttribute('color', new THREE.BufferAttribute(col, 3));
    }
    const mats = [new THREE.MeshLambertMaterial({ color: tint, vertexColors: livery }), ...texs.map(t => {
      const tex = texLoader.load('/api/kart_texture?ns=' + encodeURIComponent(t.ns));
      tex.flipY = false; tex.colorSpace = THREE.SRGBColorSpace; tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
      return new THREE.MeshLambertMaterial({ map: tex, color: tint, vertexColors: livery, side: THREE.DoubleSide });
    })];
    return new THREE.Mesh(g, mats);
  }
  // moyeux (pouces) lus dans le squelette du kart (matrices de pose inverses, os *_02_*WheelE)
  const WHEELS = [['wheel_l', 49.1, 51.6], ['wheel_r', 49.1, -51.6], ['wheel_l', -53.0, 51.7], ['wheel_r', -53.0, -51.7]];
  // charge a l'ouverture de la Creation, pas au demarrage de la page : au premier lancement le dossier du jeu n'est pas
  // encore choisi. Echec (dossier absent...) : boite gardee, nouvel essai a la prochaine ouverture
  // carrosserie et roues (une fois ; echec : nouvel essai a la prochaine demande) : paveuse et visite (kartModel)
  let kartParts = null;
  const loadKartParts = () => kartParts ||= Promise.all([kartPart('body', 0xffffff), kartPart('wheel_l', 0xffffff), kartPart('wheel_r', 0xffffff)])
    .catch(e => { kartParts = null; throw e; });
  let kartLoad = null;
  function loadKart() {
    return kartLoad ||= (async () => {
      try {
        const [bodyPart, wheelL, wheelR] = await loadKartParts();
        const proto = { wheel_l: wheelL, wheel_r: wheelR };
        kart.add(bodyPart); body.visible = false;
        for (const [part, x, y] of WHEELS) {
          const w = proto[part].clone(); w.position.set(x, y, 18.3); w.rotation.z = Math.PI / 2;   // essieu (x) -> y
          kart.add(w);
        }
      } catch (e) { kartLoad = null; }
    })();
  }
  // kart du jeu pour la visite virtuelle (2026-11-23) : nouvelle copie (meme livree que la paveuse), echelle 1:1 ;
  // userData.wheels = [{ pivot (braquage, rotation.z), spin (rotation.y = essieu), r }] ; null si le jeu est introuvable
  async function kartModel() {
    let parts;
    try { parts = await loadKartParts(); } catch (e) { return null; }
    const [bodyPart, wheelL, wheelR] = parts, proto = { wheel_l: wheelL, wheel_r: wheelR };
    const g = new THREE.Group(), wheels = [];
    g.add(bodyPart.clone());
    for (const [part, x, y] of WHEELS) {
      const pivot = new THREE.Group(); pivot.position.set(x, y, 18.3); g.add(pivot);
      const spin = new THREE.Group(); pivot.add(spin);
      const w = proto[part].clone(); w.rotation.z = Math.PI / 2; spin.add(w);   // essieu (x) -> y
      wheels.push({ pivot, spin, r: 18.3, front: x > 0 });
    }
    g.traverse(o => { if (o.isMesh) o.raycast = () => {}; });
    g.userData.wheels = wheels;
    return g;
  }
  const roadMat = new THREE.MeshBasicMaterial({ color: 0xffffff, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 });
  const bankMat = new THREE.MeshLambertMaterial({ color: 0x8c8378, side: THREE.DoubleSide });          // tabliers de pont
  // bords et axe de la route : fondus avec la distance (200 m -> 600 m). Plus fins qu'un pixel au loin, ils clignotaient
  // quand la camera bouge : 60 % du scintillement mesure en vue de haut ; aucun antialiasing ne les stabilise
  const fadeFar = mat => {
    mat.transparent = true; mat.depthWrite = false;
    mat.onBeforeCompile = sh => {
      sh.vertexShader = 'varying float vCrDepth;\n' + sh.vertexShader.replace('#include <project_vertex>', '#include <project_vertex>\n vCrDepth = -mvPosition.z;');
      sh.fragmentShader = 'varying float vCrDepth;\n' + sh.fragmentShader.replace('#include <dithering_fragment>',
        `#include <dithering_fragment>\n gl_FragColor.a *= 1.0 - smoothstep(${(200 * IN).toFixed(1)}, ${(600 * IN).toFixed(1)}, vCrDepth);`);
    };
    return mat;
  };
  const lineMat = fadeFar(new THREE.LineBasicMaterial({ color: 0x5a3510 }));
  const edgeMat = fadeFar(new THREE.MeshBasicMaterial({ color: 0xfff2d0, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -4, polygonOffsetUnits: -4 }));
  const road = new THREE.Mesh(new THREE.BufferGeometry(), roadMat);
  const banks = new THREE.Mesh(new THREE.BufferGeometry(), bankMat);              // talus d'aperçu jusqu'au terrain
  // bords : ruban de 25 cm, pas une ligne d'un pixel (blanche sur le sol, elle faisait 60 % du scintillement mesure en
  // deplacant la camera : l'antialiasing lisse un ruban fin, pas une ligne)
  const edgeL = new THREE.Mesh(new THREE.BufferGeometry(), edgeMat), edgeR = new THREE.Mesh(new THREE.BufferGeometry(), edgeMat);
  const center = new THREE.Line(new THREE.BufferGeometry(), lineMat);
  const startMark = new THREE.Mesh(new THREE.CylinderGeometry(1, 1, 10, 40, 1, true),
                                   new THREE.MeshBasicMaterial({ color: 0x33dd66, transparent: true, opacity: 0.25, side: THREE.DoubleSide }));
  startMark.rotation.x = Math.PI / 2;
  // damier du depart (track_creator START_CELL : 2 rangees de cases de 3 m en travers de la route) ; texture 2 x 2 cases
  const START_CELL_M = 3;
  const checkerTex = (() => {
    const c = document.createElement('canvas'); c.width = c.height = 64;
    const g = c.getContext('2d');
    for (let i = 0; i < 2; i++) for (let j = 0; j < 2; j++) { g.fillStyle = (i + j) % 2 ? '#f3f3f3' : '#121212'; g.fillRect(i * 32, j * 32, 32, 32); }
    const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.magFilter = THREE.NearestFilter; t.colorSpace = THREE.SRGBColorSpace;
    return t;
  })();
  const startLine = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial({ map: checkerTex, side: THREE.DoubleSide,
    polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 }));
  const brush =new THREE.Mesh(new THREE.RingGeometry(0.92, 1, 48), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.8, side: THREE.DoubleSide, depthTest: false }));
  brush.visible = false;
  // sol en pate a modeler (essai 2026-11-24) : le relief habituel a l'ecran, la pate seulement la ou elle est retouchee
  // (ses cases du relief cachees : clay.hiddenMask) - avant, tout le sol en pate : 770 000 triangles, editeur lent
  const clay = createClay({ THREE, IN, terrain: () => S.terrain,
    ground: (x, y) => S.terrain && S.shown?.length === S.terrain.n ** 2 ? sample(S.shown, x, y) : S.groundZ,
    faces: () => terrainFaces, repeat: () => (S.kitInfo?.ground_repeat || 12) * IN,
    material: m => terrainFaces?.mats?.get(m) || terrainMesh.material[0],
    onRegion: () => S.terrain && refreshTerrainFaces(), pickGround: r => pickRay(r), roadMap: () => clayRoadMap() });
  // chaussee pour la pate (2026-11-24 : pas de pate a moins de 15 m au-dessus de la route) : colonnes de la grille de 4 m
  // sous la route (largeur locale + 1 m de chaque cote) -> hauteurs de la chaussee ; refaite quand la route change
  let roadMapC = { sig: null, ver: 0, map: new Map() };
  function clayRoadMap() {
    const P = S.points; if (!P?.length || !S.terrain || S.shown?.length !== S.terrain.n ** 2) return roadMapC;
    let h = P.length;
    for (const q of P) h = (h * 31 + q[0] * 0.37 + q[1] * 0.61 + q[2] * 0.83 + (q[3] || 0) * 0.11 + (q[4] ? 7 : 0)) % 1e9;
    const sig = h + '|' + (S.closed ? 1 : 0) + '|' + S.width;
    if (sig === roadMapC.sig) return roadMapC;
    const V = 4 * IN, map = new Map(), E = effPoints(), n = E.length, ck = (ix, iy) => (ix + 1e5) * 3e5 + (iy + 1e5);
    for (let k = 0; k < n; k++) {
      const a = E[k], b = E[(k + 1) % n]; if (!S.closed && k === n - 1) break;
      const dx = b[0] - a[0], dy = b[1] - a[1], L = Math.hypot(dx, dy) || 1, nx = -dy / L, ny = dx / L;
      for (let t = 0; t < 1; t += 0.25) {
        const x0 = a[0] + dx * t, y0 = a[1] + dy * t, z0 = a[2] + (b[2] - a[2]) * t, hw = ((a[3] || S.width) + ((b[3] || S.width) - (a[3] || S.width)) * t) / 2 + 1 * IN;
        for (let o = -hw; o <= hw; o += V / 2) {
          const x = x0 + nx * o, y = y0 + ny * o;
          for (const ix of [Math.floor(x / V), Math.ceil(x / V)]) for (const iy of [Math.floor(y / V), Math.ceil(y / V)]) {
            if (Math.hypot(ix * V - x0, iy * V - y0) > hw + V / 2) continue;
            // chaussee AU POINT de la grille (sol affiche : devers compris) ; pont / saut (sol loin dessous) : l'axe
            const sh = sample(S.shown, ix * V, iy * V), zr = sh > z0 - 4 * IN ? sh : z0;
            const key = ck(ix, iy), zs = map.get(key);
            if (!zs) map.set(key, [zr]);
            else { const j = zs.findIndex(z => Math.abs(z - zr) < 6 * IN); if (j < 0) zs.push(zr); else zs[j] = Math.min(zs[j], zr); }
          }
        }
      }
    }
    roadMapC = { sig, ver: roadMapC.ver + 1, map };
    return roadMapC;
  }
  group.add(far, terrainMesh, clay.group, road, banks, edgeL, edgeR, center, startMark, startLine, paver, brush);
  // (ancien maillage des ponts de terre / tunnels, supprimes le 2026-11-16 : garde vide et cache)
  const roofMesh = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.DoubleSide }));
  roofMesh.visible = false; group.add(roofMesh);

  // panneau
  const panel = document.createElement('div');
  panel.id = 'creatorPanel'; panel.hidden = true;
  panel.style.cssText = 'position:absolute;left:12px;top:96px;max-height:calc(100% - 108px);overflow:auto;z-index:5;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px;width:300px;max-width:calc(100% - 24px);box-shadow:0 8px 24px #000a;font-size:13px';
  // ordre : reglages de la piste, outils du mode, son contenu, suppression (en bas) ; etat + Generer colles en bas
  const H = t => `<div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin:10px 0 4px">${t}</div>`;
  const row = 'display:grid;grid-template-columns:72px 1fr;gap:4px 6px;align-items:center;font-size:12px';
  const sizeLabel = s => (s / 1000).toLocaleString('fr', { minimumFractionDigits: 1 });
  // mise en page : blocs titres (.crcard), aide repliable (.crhelp), sous-onglets (.crsub)
  const css = document.createElement('style');
  css.textContent = `#creatorPanel .crcard{border:1px solid var(--line);border-radius:8px;padding:8px;margin-top:8px;background:var(--panel2)}
    #creatorPanel .crcard>h4,#creatorPanel .crcard>summary{margin:0 0 6px;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
    #creatorPanel details.crcard>summary{cursor:pointer;margin:0}
    #creatorPanel details.crcard[open]>summary{margin-bottom:6px}
    #creatorPanel details.crhelp{margin:8px 0 6px;font-size:12px}
    #creatorPanel details.crhelp>summary{cursor:pointer;color:var(--muted)}
    #creatorPanel details.crhelp>.note{margin-top:4px}
    #creatorPanel .crsub{display:grid;grid-auto-flow:column;grid-auto-columns:1fr;margin-top:8px}
    #creatorPanel .crsub button{border-radius:0;padding:7px 4px}
    #creatorPanel .crsub button:first-child{border-radius:8px 0 0 8px}
    #creatorPanel .crsub button:last-child{border-radius:0 8px 8px 0}
    #creatorPanel .crrow2{display:grid;grid-template-columns:1fr 118px;gap:5px 6px;align-items:center;font-size:12px}
    #creatorPanel .crrow2 select{width:100%}
    #creatorPanel .crchips{display:flex;flex-wrap:wrap;gap:4px}
    #creatorPanel .crchips button{font-size:12px;padding:3px 7px}
    #creatorPanel .crcard label{font-size:12px}
    #creatorPanel .crsep{height:2px;margin:12px -2px 4px;border-radius:1px;background:var(--muted);opacity:.55}`;
  document.head.appendChild(css);
  // titre : l'en-tete unique de l'inspecteur (« Outil de base · Route », index.html syncInspector, 2026-11-15)
  // « Piste aléatoire » : outil de la barre de gauche (index.html #railrandom, 2026-11-17) ; ancien bouton du panneau garde masque
  panel.innerHTML = `<div hidden>
      <button id="crrandom" title="Piste complète créée d'après un code (tracé, relief, décor…) : le même code redonne la même piste">🎲 Piste aléatoire…</button></div>
    <!-- outils : dans la barre de gauche de l'editeur depuis l'onglet unique (2026-11-14, B5) ; rangee gardee masquee -->
    <div id="crmodes" hidden>${H('Outil')}
    <div style="display:grid;grid-template-columns:repeat(6,1fr);gap:4px"><button id="crmroute" style="grid-column:span 2">🛣 Route</button><button id="crmedges" style="grid-column:span 2">↔ Bords</button><button id="crmbridge" style="grid-column:span 2" title="Faire passer une route au-dessus d'une autre là où elles se croisent">🌉 Pont</button><button id="crmterrain" style="grid-column:span 2">⛰ Relief</button><button id="crmpaint" style="grid-column:span 2">🎨 Peinture</button><button id="crmprops" style="grid-column:span 2">🌴 Décor</button></div></div>
    <!-- (separateur sous l'en-tete retire le 2026-11-18, demande utilisateur : l'en-tete de l'inspecteur a deja sa ligne) -->
    <div id="credges" hidden>
      <details class="crhelp"><summary>ℹ Comment faire</summary><div class="note">Clic sur un bord de la route : une poignée apparaît. Flèche rouge (vers l'extérieur) : élargir ou amincir ce côté. Flèche bleue (vers le haut) : relever ou abaisser le bord (virage relevé). Les points voisins suivent en douceur, le terrain dessous se raccorde. Clic droit : tourner la vue.</div></details>
      <div style="margin-bottom:6px">Zone sélectionnée : <b id="credgerv">30</b> m de part et d'autre
        <div style="display:flex;gap:4px;align-items:center;margin-top:2px">
          <button id="credgerminus" title="Réduire la zone ( - )" style="min-width:30px">−</button>
          <input id="credger" type="range" min="5" max="150" value="30" style="flex:1;min-width:0" title="Étendue de la zone autour du point cliqué (trait jaune ; extrémités : points blancs)">
          <button id="credgerplus" title="Agrandir la zone ( + )" style="min-width:30px">+</button></div></div>
      <div id="credgeinfo" class="note" style="margin-bottom:4px">Clique sur un bord de la route.</div>
      <div id="credgeset" style="${row};margin-bottom:6px;display:none">
        <span>Largeur (m)</span><input id="credgew" type="number" step="0.5" min="5" max="60" title="Distance de ce bord au tracé du paveur">
        <span>Relevé (m)</span><input id="credgeh" type="number" step="0.5" min="-10" max="15" title="Hauteur du bord par rapport au tracé : positif = relevé">
        <span></span><button id="credgereset">↺ Ce passage à plat</button>
        <span></span><button id="credgesmooth" title="Largeur et relevé de ce bord en ligne droite entre les deux extrémités de la zone (points blancs) : bosses et creux entre les deux effacés">〰 Lisser entre les extrémités</button>
      </div>
      <button id="credgeall" class="danger" style="width:100%;margin-top:4px">🗑 Tous les bords à plat (largeur symétrique)</button>
    </div>
    <div id="crbridge" hidden>
      <details class="crhelp"><summary>ℹ Comment faire</summary><div class="note">Clique sur la route là où elle croise une autre route. La route cliquée monte au-dessus de l'autre en pente douce, sans talus : le sol reste dessous et l'autre route passe sous le pont. Ctrl+Z pour annuler.</div></details>
      <div class="crcard"><h4>Pont</h4>
      <label style="display:block;margin-bottom:6px" title="Espace libre entre l'autre route et le dessous du pont">Hauteur sous le pont : <b id="crbrhv">8</b> m<input id="crbrh" type="range" min="5" max="30" value="8" style="width:100%"></label>
      <label style="display:block;margin-bottom:6px" title="Longueur de chaque rampe, avant et après le pont. Plus long : pente plus douce">Longueur des rampes : <b id="crbrlv">80</b> m<input id="crbrl" type="range" min="30" max="200" step="10" value="80" style="width:100%"></label>
      <div id="crbrinfo" class="note" style="margin-bottom:6px">Clique sur un croisement de la route.</div>
      <button id="crbrgo" class="primary" style="width:100%;margin-bottom:4px" disabled>🌉 Faire passer cette route au-dessus</button>
      <button id="crbrswap" style="width:100%" disabled title="C'est l'autre route qui monte au-dessus">⇅ L'autre route passe dessus</button>
      </div>
    </div>
    <div id="crroute">
      <!-- 2026-11-13 : trois onglets (l'utilisateur trouvait la colonne Route trop chargee) -->
      <div class="crsub" style="margin-top:8px"><button id="crrtdrive">🚗 Conduite</button><button id="crrtpieces">🧩 Pièces</button><button id="crrtset">⚙ Réglages</button></div>
      <div id="crrpdrive">
      <details class="crhelp" style="margin-top:0"><summary>ℹ Comment faire</summary><div class="note">Conduis le paveur : la route se pose derrière lui. Ferme la boucle en revenant dans le cercle vert.</div></details>
      <div class="crcard">
      <label style="display:block;margin-bottom:6px">Largeur : <b id="crw"></b> m<input id="crwidth" type="range" min="${W_MIN / IN}" max="${W_MAX / IN}" value="${W_DEF / IN}" style="width:100%"></label>
      <label style="display:block;margin-bottom:2px" title="Le kart et la route penchent progressivement vers cet angle en roulant (30° sur 40 m). L'angle reste jusqu'à ce que tu le changes. Touches T et G.">Inclinaison : <b id="crrollv">à plat</b>
        <div style="display:flex;gap:4px;align-items:center"><input id="crroll" type="range" min="-30" max="30" step="1" value="0" style="flex:1;min-width:0">
        <button id="crrollflat" title="Remettre à plat">↔</button></div></label>
      <label style="display:flex;gap:6px;align-items:center;margin:6px 0 0" title="Avec : le terrain monte jusqu'à la route. Sans : le sol reste à sa hauteur et la route passe au-dessus, comme un pont. Change en roulant : seule la route posée ensuite suit ce réglage. Touche B."><input type="checkbox" id="crtalus" checked> Talus sous la route (B)</label>
      </div>
      <button id="crstartpick" style="width:100%;margin-top:6px" title="Clique ensuite sur le terrain : le kart s'y place et la route partira de là. Le départ de la course suit à la génération.">📍 Placer le kart (point de départ)</button>
      </div>
      <div id="crrppieces" hidden>
      <details class="crhelp" style="margin-top:0"><summary>ℹ Comment faire</summary><div class="note">Ajoutée au bout de la route, devant le kart (aperçu jaune). Ctrl+Z pour annuler.</div></details>
      <div id="crpiecegrid" style="display:grid;grid-template-columns:1fr 1fr;gap:4px;margin-bottom:6px">
        <button data-piece="banked">↪ Virage relevé</button><button data-piece="spiral">🌀 Spirale</button>
        <button data-piece="slalom">〰 Chicane / slalom</button><button data-piece="jump">🛫 Saut</button>
        <button data-piece="bumps">⛰ Bosses</button><button data-piece="ramp">⟋ Rampe</button>
        <button data-piece="straight">➖ Ligne droite</button><button data-piece="hairpin" title="Demi-tour serré : la route repart dans l'autre sens">↩ Épingle</button>
        <button data-piece="plunge" title="Descente raide puis remontée, comme des montagnes russes">🎢 Plongeon</button><button data-piece="overpass" title="Virage de 270° qui monte et repasse au-dessus de la route en pont ; la route repart à angle droit">➰ Boucle par-dessus</button></div>
      <div class="crcard">
      <div id="crpdirrow" style="display:flex;gap:4px;margin-bottom:6px">
        <button id="crpleft" style="flex:1">← Gauche</button><button id="crpright" style="flex:1">Droite →</button></div>
      <div id="crpvertrow" style="display:flex;gap:4px;margin-bottom:6px">
        <button id="crpup" style="flex:1">⬆ Monte</button><button id="crpdown" style="flex:1">⬇ Descend</button></div>
      <label id="crpalab" style="display:block;margin-bottom:4px"><span id="crpaname"></span> : <b id="crpav"></b><input id="crpa" type="range" style="width:100%"></label>
      <label id="crpblab" style="display:block;margin-bottom:4px"><span id="crpbname"></span> : <b id="crpbv"></b><input id="crpb" type="range" style="width:100%"></label>
      <label id="crpclab" style="display:block;margin-bottom:4px"><span id="crpcname"></span> : <b id="crpcv"></b><input id="crpc" type="range" style="width:100%"></label>
      <div id="crpinfo" class="note" style="font-size:12px;margin:2px 0 6px"></div>
      <button id="crpgo" class="primary" style="width:100%">🧩 Poser la pièce</button>
      </div>
      </div>
      <div id="crrpset" hidden>
      <div class="crcard"><h4>🖌 Marquage au sol</h4>
      <div class="note" style="font-size:12px;margin-bottom:4px">Peint sur la route à la génération (on roule dessus sans le sentir).</div>
      <label style="display:flex;gap:6px;align-items:center"><input type="checkbox" data-mark="edges"> Lignes de bord</label>
      <label style="display:flex;gap:6px;align-items:center"><input type="checkbox" data-mark="center"> Ligne centrale en tirets</label>
      <label style="display:flex;gap:6px;align-items:center" title="Bandes rouges et blanches à l'intérieur des virages serrés"><input type="checkbox" data-mark="curbs"> Vibreurs dans les virages</label>
      </div>
      <!-- panneaux de virage : RETIRES du menu le 2026-11-13 a la demande de l'utilisateur (code garde, plus utilise) -->
      <select id="crsign" hidden><option value=""></option></select>
      <div class="crcard"><h4>Talus</h4>
      <button id="crtalusall" style="width:100%;margin-bottom:6px" title="Applique le réglage « Talus sous la route » (onglet Conduite) à toute la route déjà posée">Appliquer le talus à toute la route</button>
      <label style="display:block" title="Largeur du talus de chaque côté, pour 10 m de dénivelé entre la route et le sol. Plus petit : talus plus raide, qui prend moins de place. S'applique à toute la piste.">Largeur du talus : <b id="crblendv"></b><input id="crblend" type="range" min="0.25" max="1.5" step="0.25" value="${BLEND_DEF}" style="width:100%"></label>
      </div>
      <!-- 2026-11-14 : suppressions a part, sous un separateur (moins de risque de clic par erreur) -->
      <div class="crsep" style="margin-top:16px"></div>
      <button id="crreset" class="danger" style="width:100%;margin-top:8px">🗑 Supprimer toute la route</button>
      </div>
      <details class="crhelp"><summary>⌨ Commandes du paveur</summary>
      <div style="display:grid;grid-template-columns:auto 1fr;gap:2px 8px;font-size:12px;color:var(--muted);margin-top:4px">
        <span>↑ Z W</span><span>avancer (pose la route)</span><span>↓ S</span><span>reculer (efface)</span>
        <span>← Q A · → D</span><span>tourner</span><span>R · F</span><span>monter · descendre</span>
        <span>T · G</span><span>incliner à gauche · à droite</span><span>B</span><span>talus sous la route (oui · non)</span>
        <span>+ · −</span><span>largeur</span><span>Entrée</span><span>fermer la boucle</span>
        <span>Maj</span><span>plus vite</span><span>C</span><span>caméra libre / poursuite</span>
        <span>Espace</span><span>saut (maintenir : trou dans la route)</span></div></details>
    </div>
    <div id="crterrain" hidden>
      <details class="crhelp"><summary>ℹ Comment faire</summary>
      <div class="note">Clic gauche maintenu sur le sol : sculpter. Clic droit : tourner la vue, molette : zoom, clic milieu : déplacer. Sous la route, le terrain est raccordé à la route à la génération.</div>
      <div class="note">⛏ Creuser sous la route : sous une route en hauteur, le sol n'est plus collé à elle (place pour du décor, la route devient un pont). ↺ Reboucher : le sol se raccorde de nouveau.</div></details>
      <div class="crcard"><h4>Outil de relief</h4>
      <div id="crtools" style="display:flex;flex-wrap:wrap;gap:4px">${TOOLS.map(([k, l]) => `<button data-tool="${k}">${l}</button>`).join('')}</div></div>
      <div id="crwatercard" class="crcard" hidden><h4>💧 Eau</h4>
        <div id="crwhelp" class="note" style="font-size:12px;margin-bottom:6px"></div>
        <label style="display:flex;gap:6px;align-items:center;margin-bottom:6px" title="Couleur de l'eau, pour l'eau sélectionnée et les nouvelles">Type
          <select id="crwtype" style="flex:1"></select></label>
        <label id="crwhrow" style="display:none;margin-bottom:6px" title="Hauteur de la nouvelle eau peinte au-dessus du sol cliqué au début du trait">Hauteur de l'eau peinte : <b id="crwhv">1</b> m au-dessus du sol<input id="crwh" type="range" min="0" max="20" step="0.5" value="1" style="width:100%"></label>
        <div id="crwlist" style="margin-bottom:6px"></div>
        <label id="crwlevelrow" style="display:none;margin-bottom:6px" title="Hauteur de l'eau par rapport au bord le plus bas du trou">Niveau : <b id="crwlv"></b> m sous le bord<input id="crwlevel" type="range" min="-20" max="0" step="0.1" value="-5" style="width:100%"></label>
        <label id="crwplevelrow" style="display:none;margin-bottom:6px" title="Niveau de l'eau peinte, par rapport au sol cliqué au début du trait">Niveau : <b id="crwplv"></b> m au-dessus du sol de départ<input id="crwplevel" type="range" min="-5" max="30" step="0.5" value="1" style="width:100%"></label>
        <div class="note" style="font-size:12px;margin-bottom:6px">Moins de 1,5 m d'eau : on roule au fond. Plus profond : on tombe et on réapparaît sur la route. Clique dans une eau pour la sélectionner.</div>
        <button id="crwclear" class="danger" style="width:100%">🗑 Retirer toute l'eau</button>
      </div>
    </div>
    <div id="crpaint" hidden>
      <details class="crhelp"><summary>ℹ Comment faire</summary>
      <div class="note">Clic gauche maintenu sur le sol : peindre (le relief ne change pas). Clic droit : tourner la vue, molette : zoom, clic milieu : déplacer.</div></details>
      <div class="crcard"><h4>Peinture : <b id="crmatcur" style="text-transform:none;color:var(--text)"></b></h4>
      <div id="crmats" style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:6px"></div>
      <details><summary style="cursor:pointer;font-size:12px">🎨 Autres peintures (sols de tous les thèmes)</summary>
        <div id="crmatsx" style="max-height:260px;overflow:auto;border:1px solid var(--line);border-radius:6px;padding:2px 6px;margin-top:4px"></div></details>
      </div>
      <div class="crcard"><label style="display:block" title="Largeur de la transition entre deux peintures qui se touchent. S'applique à toute la piste.">Fondu entre peintures : <select id="crfade"><option value="0">Aucun (net)</option><option value="2">Court (8 m)</option><option value="4">Moyen (24 m)</option><option value="6">Large (40 m)</option></select></label></div>
    </div>
    <div id="crprops" hidden>
      <div class="crsub"><button id="crptauto">🤖 Automatique</button><button id="crptman">🖌 À la main</button></div>
      <div id="crpaneauto">
        <details class="crhelp"><summary>ℹ Comment faire</summary><div class="note">Construit un décor d'après le thème, les peintures et les pentes, avec de gros objets en fond de carte. Tes objets et ton relief faits à la main sont gardés.</div></details>
        <div class="crcard"><h4>Style</h4>
          <div class="crchips"><button data-aipreset="balanced">⚖ Équilibré</button><button data-aipreset="nature">🌳 Nature</button><button data-aipreset="clear">👁 Dégagé</button><button data-aipreset="wild">🌲 Sauvage</button><button data-aipreset="built">🏘 Aménagé</button></div>
        </div>
        <details class="crcard"><summary>Quantité</summary>
          <div class="crrow2">
            <span>Densité :</span><select id="craidens"><option value="0">Légère</option><option value="1" selected>Normale</option><option value="2">Dense</option></select>
            ${[['craiveg', '🌳 Végétation', 'Arbres, buissons, herbes et fleurs'], ['crairock', '🗻 Rochers', 'Rochers, cristaux, fossiles'], ['craibuilt', '🏠 Objets et bâtiments', 'Statues, piliers, machines, maisons, huttes'], ['crairoad', '🚧 Bord de route', 'Panneaux, lampes, barrières, pneus : surtout à l\'extérieur des virages']]
              .map(([id, l, tip]) => `<span title="${tip}">${l}</span><select id="${id}" title="${tip}"><option value="0">Aucun</option><option value="1">Peu</option><option value="2" selected>Normal</option><option value="3">Beaucoup</option></select>`).join('')}
          </div>
        </details>
        <details id="craiadv" class="crcard"><summary>Réglages avancés</summary>
          <label style="display:block;margin-bottom:4px" title="Bande laissée vide de chaque côté de la route (les panneaux et lampes du bord de route restent). Plus grand : piste plus lisible, moins chargée.">Bande dégagée au bord : <b id="craiclearv">4</b> m<input id="craiclear" type="range" min="0" max="30" step="1" value="4" style="width:100%"></label>
          <label style="display:block;margin-bottom:4px" title="Distance jusqu'où le décor s'étend de chaque côté de la route. Plus petit : décor concentré près de la piste.">Étendue : jusqu'à <b id="craireachv">230</b> m de la route<input id="craireach" type="range" min="80" max="300" step="10" value="230" style="width:100%"></label>
          <div class="crrow2" style="margin-bottom:6px">
            <span title="Dispersée : objets répartis partout. En bosquets : groupes serrés séparés par des clairières.">Répartition</span><select id="craicluster"><option value="0">Dispersée</option><option value="1" selected>Naturelle</option><option value="2">En bosquets</option></select>
            <span title="Quand le thème n'a pas d'objet pour un sol (pas d'arbres aux Égouts, pas d'herbes sur les Îles volantes), où en prendre.">Objets d'autres thèmes</span><select id="craiborrow" title="Quand le thème n'a pas d'objet pour un sol (pas d'arbres aux Égouts, pas d'herbes sur les Îles volantes), où en prendre."><option value="0">Jamais</option><option value="1" selected>Thèmes proches</option><option value="2">Tous les thèmes adaptés au sol</option></select>
          </div>
          <label style="display:block;margin-bottom:4px" title="Hauteur des collines et creux que le décor automatique peut modeler autour de la route. 0 : il ne touche pas au relief.">Relief : <b id="craiampv">25</b> m<input id="craiamp" type="range" min="0" max="80" step="5" value="25" style="width:100%"></label>
          <label style="display:block;margin-bottom:4px"><input id="craibig" type="checkbox" checked> Gros décors en fond de carte</label>
          <label style="display:block" title="Rien de haut (arbre, rocher, bâtiment) à moins de 30 m à l'intérieur d'un virage ni autour de la ligne de départ : on voit toujours la suite de la route."><input id="craisight" type="checkbox" checked> Virages et départ dégagés</label>
        </details>
        <button id="craigo" class="primary" style="width:100%;margin-top:8px">🤖 Créer le décor</button>
        <button id="crairm" hidden style="width:100%;margin-top:4px;font-size:12px">🧹 Retirer le décor automatique</button>
        <div id="crairep" class="note" data-noi18n hidden style="font-size:11px;margin-top:6px"></div>
      </div>
      <div id="crpaneman" hidden>
        <details class="crhelp"><summary>ℹ Comment faire</summary><div class="note">Objets de tous les thèmes, posés sur le sol à la génération, jamais sur la route. Clic gauche maintenu : pinceau, clic droit : tourner la vue.</div></details>
        <div class="crcard">
          <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px">
            <span style="flex:1;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)">1. Objets à semer · <span id="crpsel" style="text-transform:none"></span></span>
            <select id="crpsort" title="Classement de la liste" style="font-size:11px"><option value="style">Par style</option><option value="type">Par type d'objet</option></select>
          </div>
          <button id="crpnone" hidden style="width:100%;margin-bottom:4px;font-size:12px">✖ Désélectionner tout</button>
          <div id="crpgrid" style="max-height:300px;overflow:auto;border:1px solid var(--line);border-radius:6px;padding:2px 6px;background:var(--panel)"></div>
        </div>
        <div class="crcard"><h4>2. Au pinceau</h4>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px;margin-bottom:6px"><button id="crpsow">🌱 Semer</button><button id="crperase">🧽 Effacer</button><button id="crpedit" title="Clic sur un objet : le déplacer, le tourner ou changer sa taille">✋ Modifier</button></div>
          <div id="crbrushslot"></div>
          <div id="crpeditbox" hidden>
            <div id="crpeinfo" class="note" style="font-size:12px">Clique sur un objet (posé à la main ou par le décor automatique) pour le modifier.</div>
            <div id="crpeset" style="display:none">
              <div class="crchips" style="margin:6px 0"><button data-ptm="translate" title="W">✥ Déplacer</button><button data-ptm="rotate" title="E">⟳ Tourner</button><button data-ptm="scale" title="R">⤢ Taille</button></div>
              <div class="crrow2" id="crpefields" style="margin-bottom:6px">
                <span title="Rotation autour de la verticale">Rotation Z (°)</span><input id="crpeyaw" type="number" step="5" style="width:100%" title="Rotation autour de la verticale">
                <span title="Inclinaison autour de l'axe X (rouge), en plus de la pente du sol">Inclinaison X (°)</span><input id="crperx" type="number" step="5" min="-180" max="180" style="width:100%" title="Inclinaison autour de l'axe X (rouge), en plus de la pente du sol">
                <span title="Inclinaison autour de l'axe Y (vert), en plus de la pente du sol">Inclinaison Y (°)</span><input id="crpery" type="number" step="5" min="-180" max="180" style="width:100%" title="Inclinaison autour de l'axe Y (vert), en plus de la pente du sol">
                <span>Taille (×)</span><input id="crpes" type="number" step="0.05" min="0.05" max="100" style="width:100%">
                <span title="Décalage au-dessus (ou au-dessous) du sol. 0 : posé sur le sol, il suit le relief.">Hauteur (m)</span><input id="crpedz" type="number" step="0.5" style="width:100%" title="Décalage au-dessus (ou au-dessous) du sol. 0 : posé sur le sol, il suit le relief.">
              </div>
              <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px"><button id="crpeground" title="Hauteur remise à 0 : l'objet suit de nouveau le sol">⤓ Au sol</button><button id="crpedup" title="Copie posée à côté (Ctrl+D) ; plusieurs objets sélectionnés : tous copiés, les copies deviennent la sélection">⧉ Dupliquer</button><button id="crpedel" class="danger" title="Suppr">🗑 Supprimer</button></div>
              <div id="crpewarn" class="note" style="font-size:11px;margin-top:4px;color:var(--err)" hidden></div>
              <div class="note" style="font-size:11px;margin-top:4px">Maj+clic ou Ctrl+clic : plusieurs objets · W déplacer · E tourner · R taille · Ctrl+D dupliquer · Suppr · Échap : désélectionner</div>
            </div>
          </div>
        </div>
        <div class="crcard"><h4>3. Ou le long de la route</h4>
          <label style="display:block;margin-bottom:4px;font-size:12px">Jusqu'à <b id="crpfarv"></b> m du bord<input id="crpfar" type="range" min="10" max="200" value="60" style="width:100%"></label>
          <button id="crpauto" style="width:100%">🌴 Semer le long de la route</button>
          <div class="note" style="font-size:11px;margin:4px 0 0">Gros objets (⛰) : seulement en fond de map, derrière les autres. Au pinceau, tu peux les poser plus près.</div>
        </div>
      </div>
      <div class="crsep" style="margin-top:16px"></div>
      <div id="crpstat" class="note" style="margin:8px 0 6px"></div>
      <button id="crpclear" class="danger" style="width:100%">🗑 Supprimer tous les objets</button>
    </div>
    <div id="crbrushhome"><div id="crbrush" class="crcard" hidden>
      <label style="display:block;margin-bottom:4px">Taille du pinceau : <b id="crr"></b> m<input id="crradius" type="range" min="6" max="150" value="30" style="width:100%"></label>
      <label style="display:block;margin-bottom:6px">Force : <b id="crs"></b><input id="crstrength" type="range" min="5" max="100" value="50" style="width:100%"></label>
      <label id="crspeedrow" style="display:block;margin-bottom:6px" title="Multiplie la vitesse à laquelle le sol monte, se creuse, s'aplanit ou se lisse">Vitesse : <b id="crspeedv">x1</b><input id="crspeed" type="range" min="1" max="10" step="1" value="1" style="width:100%"></label>
    </div></div>
    <button id="crtreset" class="danger" style="width:100%;margin-top:16px" hidden>🗑 Tout supprimer</button>
    <div style="position:sticky;bottom:0;z-index:1;background:var(--panel);border-top:1px solid var(--line);margin:10px 0 0;padding:6px 0 8px">
      <div id="crstat" style="margin-bottom:6px;font-size:12px"></div>
      <div style="display:flex;gap:6px"><button id="crundo" title="Annuler (Ctrl+Z)" disabled>↶</button>
        <button id="crredo" title="Rétablir (Ctrl+Y)" disabled>↷</button><button id="crclose">⭕ Fermer la boucle</button>
        <button id="crgo" class="go" style="flex:1;display:none">⚙ Générer la piste</button></div></div>`;
  // crgo masque : « Générer la piste » est un bouton de la barre du haut de l'editeur (2026-11-14), qui appelle generate()
  // panneau dans la barre de droite (a la place de « Sélection ») quand l'editeur la fournit, sinon sur la vue
  const host = ctx.details || view;
  if (ctx.details) panel.style.cssText = 'font-size:13px;padding:2px 0';
  host.appendChild(panel);
  // 2026-11-14, demande utilisateur (« panneau de droite trop bordelique ») : reglages de la piste (theme, terrain,
  // barrieres, qualite) dans une barre en haut de la vue 3D, a la place de la barre de l'Edition (masquee en Creation)
  const topbar = document.createElement('div');
  topbar.id = 'crtopbar'; topbar.hidden = true;
  const tcss = document.createElement('style');
  tcss.textContent = `#crtopbar{position:fixed;top:calc(var(--top,44px) + 8px);left:calc(var(--side,0px) + 8px);right:calc(var(--details,0px) + 8px);z-index:3;
      display:flex;flex-wrap:wrap;gap:6px;align-items:center;pointer-events:none;font-size:12.5px}
    #crtopbar[hidden]{display:none}
    #crtopbar>label{pointer-events:auto;display:flex;align-items:center;gap:6px;background:#1d2026e6;border:1px solid var(--line);border-radius:8px;padding:3px 4px 3px 9px;color:var(--muted)}
    #crtopbar select{padding:3px 6px;font-size:12.5px;max-width:230px}`;
  document.head.appendChild(tcss);
  topbar.innerHTML = `<label><span>Thème</span><select id="crkit"></select></label>
    <label title="Taille du carré de base"><span>Terrain</span><select id="crsize">${T_SIZES.map(s => `<option value="${s}">${sizeLabel(s)} × ${sizeLabel(s)} km</option>`).join('')}</select></label>
    <label><span>Barrières</span><select id="crbar"><option value="curves">Extérieur des virages serrés</option><option value="all">Les deux bords, partout</option><option value="none">Aucune</option></select></label>
    <label title="Affiche aussi ce que tu as ajouté dans Édition (objets, imports, copies, caisses, boosters). Ils sont à leur place actuelle : à la génération, ils sont reposés sur le nouveau sol."><input type="checkbox" id="crghost" checked><span>Ajouts d'Édition</span></label>
    <label title="Résolution de la vue et détail des objets pendant la création. Auto : la résolution baisse toute seule si la carte graphique peine, remonte si elle a de la marge. Maximale : objets d'origine. Basse : objets très simplifiés, pour les petits PC. Aucun effet sur la piste générée."><span>Qualité</span><select id="crq"><option value="auto">Auto</option><option value="0">Maximale</option><option value="2">Moyenne</option><option value="3">Basse</option></select></label>`;
  document.body.appendChild(topbar);
  const $ = id => panel.querySelector('#' + id) || topbar.querySelector('#' + id);

  // ---- decor seme (mode Decor) : objets du kit (pose a la generation), reperes simples dans l'apercu ----
  // familles d'objets de TOUS les themes (un objet d'un theme se seme sur n'importe quel autre)
  let propKinds = {};                 // {'theme|type': {label, spacing (m), scale [min, max], n (modeles), dims, names}}
  const kindOf = p => propKinds[p.k + '|' + p.t];
  S.props = []; S.propErase = false; S.propAcc = 0; S.propsDirty = false; S.lastProps = 0;
  S.waters = []; S.waterSel = -1;                    // eau des trous (outil du Relief, renderWater)
  const propGroup = new THREE.Group(); group.add(propGroup);
  // vrais modeles du jeu (comme dans le Decor), a la bonne taille ; repere gris de la taille reelle pendant le chargement
  const propModels = {}, markerMat = new THREE.MeshLambertMaterial({ color: 0x8a8580, transparent: true, opacity: 0.6 });
  const markerGeo = new THREE.CylinderGeometry(1, 1, 1, 10); markerGeo.rotateX(Math.PI / 2); markerGeo.translate(0, 0, 0.5);
  const dimOf = p => kindOf(p)?.dims?.[p.m % (kindOf(p)?.n || 1)] || { r: 3, zmin: 0, zmax: 5 };
  const rad = o => dimOf(o).r * IN * o.s;                      // rayon d'emprise
  // part des deux rayons a respecter entre deux objets (2026-11-14, retour utilisateur « objets qui se rentrent
  // dedans » : 0,5 pour tous avant, deux gros objets s'enfoncaient a mi-corps) : objets solides (batiments, objets,
  // rochers, gros decors) jamais l'un dans l'autre ; arbres : feuillages qui se touchent un peu ; buissons un peu
  // plus ; herbes et fleurs : au pied des autres. Decor automatique et pinceau
  const roleOf = o => kindOf(o)?.big ? 'big' : kindOf(o)?.role || 'prop';
  const SOFT = { cover: 0.35, shrub: 0.6, tree: 0.75 };
  const apart = (a, b) => Math.min(SOFT[roleOf(a)] ?? 1, SOFT[roleOf(b)] ?? 1);
  // modele d'un objet : promesse resolue quand la geometrie ET ses textures sont chargees (vignettes) ; .value des que
  // la geometrie est la (apercu de la scene)
  // lod : detail de l'apercu, d'apres le reglage Qualite (0 modele d'origine, 1 reduction douce, 2 forte) ; la piste generee
  // garde toujours les vrais modeles
  const propLod = () => Q.lost ? 2 : ({ 0: 0, 3: 2 }[$('crq').value] ?? 1);
  function propModelP(kit, t, m, lod = propLod()) {
    const key = `${kit}|${t}|${m}|${lod}`;
    return (propModels[key] ??= (() => {
      const entry = { value: null };
      Q.loading++;
      entry.promise = (async () => {
        const buf =await (await fetch(`/api/kit_model?kit=${kit}&type=${t}&m=${m}&lod=${lod}`)).arrayBuffer(), dv = new DataView(buf);
        const nv = dv.getUint32(0, true), ni = dv.getUint32(4, true), ng = dv.getUint32(8, true);
        let o = 12;
        const g = new THREE.BufferGeometry();
        g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(buf, o, nv * 3), 3)); o += nv * 12;
        g.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(buf, o, nv * 2), 2)); o += nv * 8;
        g.setIndex(new THREE.BufferAttribute(new Uint32Array(buf, o, ni), 1)); o += ni * 4;
        for (let i = 0; i < ng; i++, o += 12) g.addGroup(dv.getUint32(o, true), dv.getUint32(o + 4, true), dv.getUint32(o + 8, true));
        const texs = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, o + 4, dv.getUint32(o, true))));
        g.computeVertexNormals(); g.computeBoundingSphere();
        const loads = [];
        const mats = [markerMat, ...texs.map(tx => {
          // attente longue : serveur occupe (centaines de vignettes), une vignette sans sa texture restait grise pour de bon
          let done; loads.push(new Promise(r => { done = r; setTimeout(r, 60000); }));
          const tex = texLoader.load(`/api/kit_texture?kit=${kit}&type=${t}&ns=${encodeURIComponent(tx.ns)}`, done, undefined, done);
          tex.flipY = false; tex.colorSpace = THREE.SRGBColorSpace; tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
          return new THREE.MeshLambertMaterial({ map: tex, alphaTest: 0.5, side: THREE.DoubleSide });
        })];
        await Promise.all(loads);
        // montre seulement avec ses textures : sans elles, l'objet s'affichait noir puis changeait d'un coup
        entry.value = { g, mats }; S.propsDirty = true;
        return entry.value;
      })().catch(() => null).finally(() => { Q.loading--; });
      return entry;
    })());
  }
  const propModel = (k, t, m) => propModelP(k, t, m).value;
  const footOf = p => (kindOf(p)?.foot ?? 0.3) * dimOf(p).r * IN * p.s;     // emprise du pied (tronc, base)
  // pose sur le sol (comme track_creator.prop_seat) : plan moyen sous l'objet, incline au plus de ce que permet sa famille, puis
  // bas au point le plus bas de l'emprise par rapport a ce plan - 30 cm. Gardee d'un calcul a l'autre : seuls les objets
  // de la zone modifiee sont recalcules (clearSeats)
  let seats = new WeakMap(), roadSeen = 0;
  const clearSeats = box => {
    if (!box) { seats = new WeakMap(); return; }
    for (const p of S.props) if (p.x >= box.x0 - 200 * IN && p.x <= box.x1 + 200 * IN && p.y >= box.y0 - 200 * IN && p.y <= box.y1 + 200 * IN) seats.delete(p);
  };
  const RING = Array.from({ length: 8 }, (_, k) => [Math.cos(k * Math.PI / 4), Math.sin(k * Math.PI / 4)]);
  // 2026-11-11 : aucun objet sur une pente de plus de 80 degres (pinceau, le long de la route, automatique ; ceux deja
  // semes y sont masques et ecartes a la generation, track_creator.STEEP_MAX)
  const STEEP_MAX = 80;
  // decor automatique : objet refuse si le sol monte sur son corps de plus de max(60 cm, 15 % de sa hauteur) au-dessus
  // de sa base (enfonce dans la montee). Rochers (faits pour etre a moitie enterres) et herbes : non concernes
  const buriedTooMuch = p => { const st = seatOf(p); if (st.onRoad || p.t === 'rock' || kindOf(p)?.rock) return false;
                               return st.bury > Math.max(0.6 * IN, 0.15 * st.h); };
  // objet pose a la main SUR la route (p.road = 1, pinceau seulement) : passage le plus haut sous lui, ou null
  // 2026-11-18 (« semer pose les objets sur la route du dessus plutot que le sol ») : la route la plus PROCHE DU SOL a cet
  // endroit, plus la plus haute ; une route a plus de ROAD_NEAR_GROUND au-dessus du sol (pont, spirale) ne compte pas :
  // l'objet va sur le sol dessous (propConflict ecarte ceux qui toucheraient le tablier)
  const ROAD_NEAR_GROUND = 4 * IN;
  function roadUnder(p) {
    const G = roadIndex(), a = Math.floor(p.x / G.size), b = Math.floor(p.y / G.size), z0 = shownAt(p.x, p.y);
    let best = null, bd = Infinity;
    for (let u = a - 1; u <= a + 1; u++) for (let v = b - 1; v <= b + 1; v++) {
      for (const q of G.cells.get(u * 100003 + v) || []) {
        if (Math.hypot(p.x - q[0], p.y - q[1]) >= q[3] / 2) continue;
        const d = Math.abs(q[2] - z0);
        if (d < bd) { bd = d; best = q[2]; }
      }
    }
    return best !== null && best - z0 <= ROAD_NEAR_GROUND ? best : null;
  }
  function seatOf(p) {
    let st = seats.get(p);
    if (st) return st;
    if (p.road) {                                            // sur la route : a plat sur son revetement (track_creator idem)
      const rz = roadUnder(p);
      if (rz !== null) { st = { low: rz + 6 - 0.3 * IN, rx: 0, ry: 0, off: null, deg: 0, onRoad: true }; seats.set(p, st); return st; }
    }
    // sol : la pate la ou elle a ete etiree (arche, voute, fond de cave : surface la plus proche de la hauteur de pose p.cz)
    // (centre : recherche complete, une fois ; points autour : surface la plus proche de la hauteur du centre, 2026-11-24 vitesse)
    const zc = clay.edited && clay.columnEdited(p.x, p.y) ? clayGround(p.x, p.y, p.cz) : null;
    const gAt = zc === null ? clay.edited ? (x, y) => clayGround(x, y, p.cz) : shownAt
      : (x, y) => x === p.x && y === p.y ? zc : clay.columnEdited(x, y) ? clay.surfaceZ(x, y, zc) ?? shownAt(x, y) : shownAt(x, y);
    const k = kindOf(p), d = dimOf(p), size = d.r * IN * p.s, rt = Math.max(IN, 0.7 * size), z0 = gAt(p.x, p.y);
    let gx = 0, gy = 0;
    for (const [c, s] of RING) { const z = gAt(p.x + rt * c, p.y + rt * s); gx += z * c; gy += z * s; }
    gx /= 4 * rt; gy /= 4 * rt;
    const g = Math.hypot(gx, gy), lim = Math.tan((k?.tilt ?? 0) * Math.PI / 180);
    // pente : la plus forte autour du pied (a 1 m et sur l'emprise). Le plan moyen seul l'adoucissait sous les gros
    // objets : il en restait sur des falaises (2026-11-11)
    let steep = g;
    for (const r of [IN, rt]) for (const [c, s] of RING) steep = Math.max(steep, Math.abs(gAt(p.x + r * c, p.y + r * s) - z0) / r);
    const deg = Math.atan(steep) * 180 / Math.PI;
    if (g > lim) { const f = g ? lim / g : 0; gx *= f; gy *= f; }
    const rf = (k?.seat ?? 0.3) * size;
    let low = z0;
    for (const f of [0.5, 1]) for (const [c, s] of RING) {
      const dx = f * rf * c, dy = f * rf * s;
      low = Math.min(low, gAt(p.x + dx, p.y + dy) - gx * dx - gy * dy);
    }
    // enfoncement : hauteur du sol au-dessus de la base de l'objet sous son corps (cote du haut d'une pente)
    let bury = 0;
    const rb = 0.45 * size;
    for (const f of [0.5, 1]) for (const [c, s] of RING) {
      const dx = f * rb * c, dy = f * rb * s;
      bury = Math.max(bury, gAt(p.x + dx, p.y + dy) - (low + gx * dx + gy * dy));
    }
    const n = Math.hypot(gx, gy, 1), nx = -gx / n, ny = -gy / n, cy = Math.cos(p.yaw), sy = Math.sin(p.yaw);
    st = { low: low - 0.3 * IN, rx: -Math.asin(-sy * nx + cy * ny), ry: Math.atan2(cy * nx + sy * ny, 1 / n), off: null, deg,
           bury: bury + 0.3 * IN, h: (d.zmax - d.zmin) * IN * p.s };
    seats.set(p, st);
    return st;
  }
  // sol de la pate le plus proche de la hauteur de pose (sans : du sol du relief : une arche tiree plus tard au-dessus
  // d'un objet ne l'emporte pas)
  // objet sans hauteur de pose qui tomberait sous de la matiere (dans un tunnel, sous une voute : « des objets entre les
  // deux couches du tunnel », 2026-11-24) : sur la surface du dessus
  const clayGround = (x, y, hint) => {
    const g = shownAt(x, y);
    if (!clay.columnEdited(x, y)) return g;
    const z = clay.surfaceZ(x, y, hint ?? g) ?? g;
    return hint == null && clay.covered(x, y, z) ? clay.surfaceZ(x, y, null) ?? z : z;
  };
  const propLow = p => seatOf(p).low;
  // pose de l'origine : par la base (rochers : par l'origine, faits pour etre a moitie enterres)
  // p.dz : decalage en hauteur donne a la main (outil Modifier, pouces), 0 = pose sur le sol
  const propZ = p => propLow(p) + (p.dz || 0) - (p.t === 'rock' ? 0 : dimOf(p).zmin * IN * p.s);
  // route touchee (track_creator.prop_conflict) : au niveau de la route, seul le pied compte ; une route plus haute
  // (pont, rampe) ne doit croiser aucune partie de l'objet tant que le dessous de son tablier est sous son sommet
  // noUnder (decor automatique, 2026-11-13 : sapins sous la spirale qui traversaient la route du dessus en jeu) : rien
  // sous un pont, quelle que soit la hauteur libre
  function propConflict(p, noUnder = false) {
    const k = kindOf(p), d = dimOf(p), base = propLow(p) + (p.dz || 0), top = base + (d.zmax - d.zmin) * IN * p.s;
    const clear = (k?.clear ?? 1) * IN, foot = footOf(p) + clear, full = 0.9 * d.r * IN * p.s + clear;
    const level = (k?.level ?? 1.5) * IN, deck = (k?.deck ?? 1.2) * IN;
    // seuls les points de route proches sont testes (3 879 objets x 1 789 points : 190 ms a chaque fin de trait)
    const G = roadIndex(), reach = Math.max(foot, full) + G.half;
    const a0 = Math.floor((p.x - reach) / G.size), a1 = Math.floor((p.x + reach) / G.size);
    const b0 = Math.floor((p.y - reach) / G.size), b1 = Math.floor((p.y + reach) / G.size);
    const onRoad = !!p.road;                                 // pose a la main sur la route : seul un pont au-dessus gene
    for (let a = a0; a <= a1; a++) for (let b = b0; b <= b1; b++) {
      const cell = G.cells.get(a * 100003 + b); if (!cell) continue;
      for (const q of cell) {
        const hd = Math.hypot(p.x - q[0], p.y - q[1]) - q[3] / 2;
        if (q[2] < base + level ? !onRoad && hd < foot : (noUnder || q[2] - deck < top + IN) && hd < full) return true;
      }
    }
    return false;
  }
  // points de la route ranges par cases de 100 m, refaits quand le trace change (effPoints donne un nouveau tableau)
  let roadIdx = { src: null };
  function roadIndex() {
    const pts = S.eff || S.points;
    if (roadIdx.src === pts && roadIdx.n === pts.length) return roadIdx;
    if (pts.length < roadSeen) clearSeats();                 // route raccourcie : des objets masques redeviennent possibles
    roadSeen = pts.length;
    const size = 100 * IN, cells = new Map(); let half = 0;
    for (const q of pts) {
      const key = Math.floor(q[0] / size) * 100003 + Math.floor(q[1] / size);
      let c = cells.get(key); if (!c) cells.set(key, c = []);
      c.push(q); if (q[3] / 2 > half) half = q[3] / 2;
    }
    return roadIdx = { src: pts, n: pts.length, size, cells, half };
  }
  // dans le carre de base (hors du terrain : ecarte a la generation)
  const inTerrain = p => { const T = S.terrain; if (!T) return true;
    const m = 0.5 * dimOf(p).r * IN * p.s, e = (T.n - 1) * T.cell;
    return p.x - m > T.x0 && p.y - m > T.y0 && p.x + m < T.x0 + e && p.y + m < T.y0 + e; };
  let propStat = '';
  // objets groupes par modele et par zone de 800 m (InstancedMesh) : quelques centaines d'appels de dessin au lieu d'un
  // par objet, et une zone hors de la vue n'est pas dessinee
  const propDummy = new THREE.Object3D(), PROP_ZONE = 800 * IN;
  propDummy.rotation.order = 'ZYX';
  const Q = { level: 0, sum: 0, n: 0, from: 0, down: 0, up: -1e9, wait: 60000, cull: 0, bad: 0, loading: 0, lost: false };   // qualite de la vue (voir setQuality)
  const propMeshes = new Map();                           // zone + modele -> InstancedMesh gardee d'un calcul a l'autre
  // objets de la base caches dans l'editeur (Edition : H, Maj+H ; 2026-11-16) : seulement l'affichage, pour la session
  const propHidden = new Set();
  function renderProps() {
    let off = 0;
    const buckets = new Map(), lod = propLod();
    for (const p of S.props) {
      if (propHidden.has(p)) continue;                    // cache dans l'editeur (H) : genere quand meme
      // la route a change depuis le semis (pont, rampe) : objet ecarte a la generation, donc pas montre
      if (!kindOf(p)) { off++; continue; }                // famille inconnue : ignoree aussi a la generation
      const st = seatOf(p);
      // objet place a la main (p.ed : deplace, tourne, duplique) : pose meme s'il touche la route ou sur une pente
      // (2026-11-19 ; track_creator.props_items le garde aussi) ; seul le hors-terrain l'ecarte
      st.off ??= p.ed ? !inTerrain(p) : propConflict(p) || !inTerrain(p) || (!st.onRoad && (st.deg > STEEP_MAX || inRoof(p)));
      if (st.off) { off++; continue; }
      const m = p.m % (kindOf(p)?.n || 1), mdl = propModel(p.k, p.t, m), d = dimOf(p), o = propDummy;
      if (mdl) o.scale.setScalar(p.s);
      else o.scale.set(d.r * IN * p.s * 0.6, d.r * IN * p.s * 0.6, (d.zmax - d.zmin) * IN * p.s);
      o.rotation.set(st.rx + (p.rx || 0), st.ry + (p.ry || 0), p.yaw); o.position.set(p.x, p.y, propZ(p) + (mdl ? 0 : d.zmin * IN * p.s));
      o.updateMatrix();
      const key = `${Math.floor(p.x / PROP_ZONE)},${Math.floor(p.y / PROP_ZONE)}|${mdl ? `${p.k}|${p.t}|${m}|${lod}` : ''}`;
      let b = buckets.get(key);
      if (!b) buckets.set(key, b = { g: mdl ? mdl.g : markerGeo, mats: mdl ? mdl.mats : markerMat, list: [], props: [], maxR: 0 });
      b.list.push(...o.matrix.elements); b.props.push(p);    // instance -> objet (clic de l'outil Modifier)
      b.maxR = Math.max(b.maxR, mdl ? (mdl.g.boundingSphere?.radius || 100) * p.s : Math.max(d.r * IN * p.s, (d.zmax - d.zmin) * IN * p.s));
    }
    // seules les zones qui ont change repartent a la carte graphique : tout refaire a chaque objet pose, plusieurs fois par
    // seconde, saturait les petites cartes graphiques
    for (const [key, im] of propMeshes) if (!buckets.has(key)) { propGroup.remove(im); im.dispose(); propMeshes.delete(key); }
    for (const [key, b] of buckets) {
      const n = b.list.length / 16;
      let im = propMeshes.get(key), changed = false;
      if (!im || n > im.instanceMatrix.count) {
        if (im) { propGroup.remove(im); im.dispose(); }
        im = new THREE.InstancedMesh(b.g, b.mats, Math.ceil(n * 1.3) + 4);
        propMeshes.set(key, im); propGroup.add(im); changed = true;
      }
      const a = im.instanceMatrix.array;
      if (!changed && im.count === n) { for (let i = 0; i < b.list.length; i++) if (a[i] !== Math.fround(b.list[i])) { changed = true; break; } }
      else changed = true;
      if (changed) { a.set(b.list); im.count = n; im.instanceMatrix.needsUpdate = true; im.computeBoundingSphere(); }
      im.userData.maxR = b.maxR; im.userData.props = b.props;
    }
    if (S.propSelP) syncPropSel();
    if (S.propMany?.length > 1) drawMany();
    Q.cull = 0;                                           // masquage des petits objets (qualite basse) refait aussitot
    syncAi();
    const stat = `${S.props.length - off} objet(s) semé(s)` +
      (off ? ` · ${off} masqué(s) : ils touchent la route (pont, rampe) ou sortent du terrain, ils ne seront pas posés` : '');
    if (stat !== propStat) { propStat = stat; $('crpstat').textContent = stat; }   // reecrit seulement s'il change (voir showRoadStat)
  }
  // objets choisis dans la liste (« theme|type|modele ») : le pinceau et le semis le long de la route y piochent
  S.sel = new Set();
  const selKind = key => propKinds[key.split('|').slice(0, 2).join('|')];
  // big : true = gros objets seulement, false = les autres, undefined = tous
  const hiddenSel = s => selKind(s)?.hide?.includes(+s.split('|')[2]);   // masque de la liste : plus seme
  const pickSel = big => { const a = [...S.sel].filter(s => selKind(s) && !hiddenSel(s) && (big === undefined || !!selKind(s).big === big));
                           if (!a.length) return null;
                           const [k, t, m] = a[Math.floor(Math.random() * a.length)].split('|'); return { k, t, m: +m }; };
  // c : objet deja choisi ({k, t, m, s?}), sinon tire dans la selection
  // manual : pinceau (l'objet peut etre pose sur la route : p.road) ; le semis le long de la route ne le fait pas
  function tryProp(x, y, c = pickSel(), manual = false) {
    if (!c) return false;
    const k = kindOf(c), [a, b] = k.scale;
    const p = { k: c.k, t: c.t, m: c.m, x, y, yaw: +(Math.random() * 2 * Math.PI).toFixed(3), s: c.s ?? +(a + Math.random() * (b - a)).toFixed(2), c: CAT_VERSION };
    if (S.mode === 'props' && S.mouse && clay.columnEdited(x, y)) p.cz = Math.round(S.mouse.z);   // pose sur la pate visee (arche, cave)
    if (manual && roadUnder(p) !== null) p.road = 1;
    if (!seatOf(p).onRoad && seatOf(p).deg > STEEP_MAX) return false;     // falaise : rien n'y tient
    if (propConflict(p) || !inTerrain(p)) return false;
    const sp = k.spacing * IN;
    // pas de chevauchement : emprises des deux objets (part selon leur genre, apart) + espacement de leur famille
    // (gros objet d'un cote : seulement leurs emprises, sinon un rocher geant interdirait toute herbe a 30 m a la ronde)
    const gap = q => k.big !== kindOf(q)?.big ? 0 : Math.max(sp, (kindOf(q)?.spacing || 3) * IN) * 0.8;
    if (S.props.some(q => Math.hypot(q.x - x, q.y - y) < Math.max(gap(q), (rad(p) + rad(q)) * apart(p, q)))) return false;
    S.props.push(p);
    return true;
  }
  function sowAlongRoad() {
    if (!pickSel()) { status('Choisis d\'abord un ou plusieurs objets dans la liste', 'err'); return; }
    let n = 0, nb = 0;
    const far = +$('crpfar').value, small = !!pickSel(false), big = !!pickSel(true), old = new Set(S.props);
    for (let i = 0; i < S.points.length; i += 6) {           // tous les ~24 m, des deux cotes
      const a = S.points[i], b = S.points[Math.min(S.points.length - 1, i + 1)];
      let tx = b[0] - a[0], ty = b[1] - a[1]; const l = Math.hypot(tx, ty) || 1; tx /= l; ty /= l;
      const at = (off, along, side, c) => tryProp(a[0] - ty * off * side + tx * along, a[1] + tx * off * side + ty * along, c);
      // toute la bande, du bord jusqu'a la distance choisie (l'espacement des objets regle la densite)
      const tries = Math.max(2, Math.ceil(far / 10));
      if (small) for (const side of [1, -1]) for (let k = 0; k < tries; k++)
        if (at(a[3] / 2 + (3 + Math.random() * far) * IN, (Math.random() - 0.5) * 24 * IN, side, pickSel(false))) n++;
      // gros objets : seulement en fond de map, derriere la bande (au moins big_min du bord), leur bord le plus proche
      // de la route a cette distance
      if (big) for (const side of [1, -1]) {
        const c = pickSel(true), k = kindOf(c), [s0, s1] = k.scale;
        c.s = +(s0 + Math.random() * (s1 - s0)).toFixed(2);
        const r = 0.5 * dimOf(c).r * c.s;
        if (at(a[3] / 2 + (Math.max(k.big_min ?? 60, far) + r + Math.random() * 60) * IN, (Math.random() - 0.5) * 24 * IN, side, c)) nb++;
      }
    }
    const wetOut = dropPropsInWater(p => old.has(p));             // semis : rien dans l'eau non plus (2026-11-14)
    n = Math.max(0, n - wetOut);
    renderProps(); saveDraft();
    status(`${n + nb} objet(s) semé(s) le long de la route` + (nb ? ` dont ${nb} gros objet(s) en fond de map` : ''), 'ok');
  }
  // ---- decor automatique : regles, sans service exterieur. Lit le theme, les peintures, les pentes et la route ; modele le
  // relief autour de la route et remplit par couches, du fond vers le bord. Objets marques ai, relief garde a part (T.aih) :
  // regenerer remplace seulement ce qu'il avait pose, pas les objets ni le relief faits a la main ----
  const AI_AFF = { // chance qu'une famille pousse sur un type de sol
    veg: { cover: 1, shrub: 0.8, tree: 1, rock: 0.3, prop: 0.35, house: 0.5, road: 1, big: 1 },
    dirt: { cover: 0.5, shrub: 0.5, tree: 0.7, rock: 0.5, prop: 0.5, house: 0.7, road: 1, big: 1 },
    sand: { cover: 0.35, shrub: 0.3, tree: 0.6, rock: 0.6, prop: 0.4, house: 0.5, road: 1, big: 1 },
    rock: { cover: 0.12, shrub: 0.12, tree: 0.2, rock: 1, prop: 0.5, house: 0.25, road: 1, big: 1 },
    snow: { cover: 0.4, shrub: 0.3, tree: 0.8, rock: 0.6, prop: 0.35, house: 0.5, road: 1, big: 1 },
    built: { cover: 0.05, shrub: 0.1, tree: 0.1, rock: 0.15, prop: 1, house: 0.6, road: 1, big: 1 } };
  // role : part du total, distance au bord de la route (m), pente maxi, clairiere (seuil du bruit : plus haut = plus groupe)
  const AI_LAYERS = [['house', 0.02, 25, 170, 0.3, -1], ['prop', 0.05, 10, 110, 0.5, -1], ['tree', 0.28, 8, 210, 0.6, -0.05],
                     ['rock', 0.14, 5, 230, 1.2, -1], ['shrub', 0.1, 4, 130, 0.7, -0.1], ['cover', 0.36, 2, 95, 0.9, -0.3]];
  // m2 par objet, maximum, gros objets ; 3 : piste aleatoire (2026-11-13, « pas assez fourni ») : bien plus d'objets
  const AI_DENSITY = { 0: [900, 500, 0.6], 1: [450, 1000, 1], 2: [250, 1800, 1.4], 3: [170, 3200, 1.6] };
  // reglages par categorie (Aucun, Peu, Normal, Beaucoup) : multiplie la part des roles de la categorie
  const AI_LEVEL = [0, 0.5, 1, 1.8];
  const AI_GROUP = { tree: 'veg', shrub: 'veg', cover: 'veg', rock: 'rock', prop: 'built', house: 'built', road: 'road' };
  const AI_TALL = new Set(['tree', 'house', 'rock', 'prop']);        // cachent la suite de la route s'ils sont trop pres
  const AI_ROLE_LABEL = { tree: 'arbres', shrub: 'buissons', cover: 'herbes et fleurs', rock: 'rochers', prop: 'objets',
                          house: 'bâtiments', road: 'bord de route', big: 'gros décors' };
  // themes proches : quand le theme du sol n'a pas d'objet d'un role (pas d'arbre aux Egouts, pas d'herbe sur les Iles
  // volantes), le decor automatique pioche d'abord dans sa famille de themes
  const AI_KIN = [['sable', 'volcan', 'pyramide', 'boogie', 'jungle'], ['parc', 'ciel', 'chateau', 'stade'],
                  ['neige', 'banquise', 'ruines', 'gorge', 'horloge'], ['tubes', 'abysses'], ['canyon', 'mines', 'grottes', 'temps'],
                  ['egouts', 'labo', 'usine', 'futur', 'espace', 'orage']];
  // puis, si l'option le permet, dans les themes faits pour ce type de sol
  const AI_DONORS = { veg: ['parc', 'boogie', 'jungle', 'pyramide', 'sable', 'volcan'], dirt: ['boogie', 'parc', 'jungle', 'canyon', 'pyramide'],
                      snow: ['neige', 'banquise', 'ruines', 'gorge', 'horloge'], sand: ['sable', 'canyon', 'pyramide', 'volcan'],
                      rock: ['canyon', 'grottes', 'mines', 'volcan', 'neige'], built: ['labo', 'usine', 'egouts', 'futur', 'espace', 'stade'] };
  const matClass = v => {
    const m = matOf(v), l = (m.label || '').toLowerCase(), s = `${m.png} ${l}`.toLowerCase();
    // le nom affiche d'abord : « Béton », « Métal » ou « Briques » ont une image nommee rock.png
    return /m[eé]tal|panneau|usine|grille|b[eé]ton|asphalt|dalle|plaque|planche|ciment|brique|bois|plancher/.test(l) ? 'built'
      : /grass|herbe|moss|mousse|forest|for[eê]t|lawn|pelouse|flower|fleur|jungle|park/.test(s) ? 'veg'
      : /snow|neige|ice|glace|polar/.test(s) ? 'snow'
      : /rock|roche|stone|pierre|cliff|falaise|rubble|pebble|gravat|caillou|[eé]boulis|lav/.test(s) ? 'rock'
      : /metal|panel|floor|grid|concrete|tile|plate|plank|cement|wood/.test(s) ? 'built'
      : /dirt|terre|mud|boue|path|chemin|all[eé]e/.test(s) ? 'dirt' : 'sand';
  };
  const aiNoise = rnd => {
    const P = Array.from({ length: 256 }, () => rnd() * 2 - 1);
    const at = (i, j) => P[((i * 73 + j * 179) ^ (i * j * 31)) & 255];
    const one = (x, y) => { const i = Math.floor(x), j = Math.floor(y), u = x - i, v = y - j, a = u * u * (3 - 2 * u), b = v * v * (3 - 2 * v);
      return (at(i, j) * (1 - a) + at(i + 1, j) * a) * (1 - b) + (at(i, j + 1) * (1 - a) + at(i + 1, j + 1) * a) * b; };
    return (x, y, period) => one(x / period, y / period) * 0.65 + one(x / period * 2.1 + 17, y / period * 2.1 + 5) * 0.35;
  };
  const sstep = (a, b, x) => { const t = Math.max(0, Math.min(1, (x - a) / (b - a))); return t * t * (3 - 2 * t); };
  // distance (pouces) de chaque sommet au bord de la route : passes de chanfrein sur la grille
  function roadDistance() {
    const T = S.terrain, n = T.n, c = T.cell, D = new Float32Array(n * n).fill(1e9), c2 = c * Math.SQRT2;
    for (const q of S.eff || S.points) {
      const i0 = Math.round((q[0] - T.x0) / c), j0 = Math.round((q[1] - T.y0) / c);
      for (let j = Math.max(0, j0 - 1); j <= Math.min(n - 1, j0 + 1); j++) for (let i = Math.max(0, i0 - 1); i <= Math.min(n - 1, i0 + 1); i++) {
        const d = Math.hypot(T.x0 + i * c - q[0], T.y0 + j * c - q[1]) - q[3] / 2;
        if (d < D[j * n + i]) D[j * n + i] = d;
      }
    }
    for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) {
      const v = j * n + i;
      if (i) D[v] = Math.min(D[v], D[v - 1] + c);
      if (j) { D[v] = Math.min(D[v], D[v - n] + c); if (i) D[v] = Math.min(D[v], D[v - n - 1] + c2); if (i < n - 1) D[v] = Math.min(D[v], D[v - n + 1] + c2); }
    }
    for (let j = n - 1; j >= 0; j--) for (let i = n - 1; i >= 0; i--) {
      const v = j * n + i;
      if (i < n - 1) D[v] = Math.min(D[v], D[v + 1] + c);
      if (j < n - 1) { D[v] = Math.min(D[v], D[v + n] + c); if (i < n - 1) D[v] = Math.min(D[v], D[v + n + 1] + c2); if (i) D[v] = Math.min(D[v], D[v + n - 1] + c2); }
    }
    return D;
  }
  function aiClearRelief() {
    const T = S.terrain;
    if (T.aih) { for (let v = 0; v < T.h.length; v++) T.h[v] -= T.aih[v]; T.aih.fill(0); }
  }
  // collines et creux, nuls pres de la route et plus marques vers le bord de la carte
  // far (m, piste aleatoire, 2026-11-16) : collines de fond en plus, montant de ~200 m a ~350 m de la route (rendu
  // « fini » : la carte se ferme sur des hauteurs au lieu d'une plaine)
  function aiRelief(amp, rnd, D, far = 0) {
    const T = S.terrain, n = T.n, c = T.cell, noise = aiNoise(rnd);
    T.aih ??= new Float32Array(n * n);
    const near = Math.max(30, amp * 1.2) * IN, wide = near + Math.max(60, amp * 3) * IN, rim = 220 * IN;
    for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) {
      const v = j * n + i, x = i * c, y = j * c, m = sstep(near, wide, D[v]);
      if (!m) continue;
      const edge = Math.min(i, j, n - 1 - i, n - 1 - j) * c, up = sstep(rim, 0, edge);
      const hill = noise(x, y, 320 * IN) * 1.5 * (1 - up) + up * (0.9 + 0.5 * noise(x, y, 180 * IN));
      const back = far ? far * IN * sstep(200 * IN, 350 * IN, D[v]) * (0.7 + 0.45 * noise(x + 9e5, y, 230 * IN)) : 0;
      const next = Math.max(T_LO, Math.min(T_HI, T.h[v] + amp * IN * hill * m + back));
      T.aih[v] = next - T.h[v]; T.h[v] = next;
    }
  }
  // ---- ponts de terre et tunnels de la piste aleatoire (2026-11-24, sol en pate) : arches epaisses au-dessus d'un creux,
  // pieds plantes dans le sol ; tunnels creuses de part en part dans une colline. Loin de la route, tirage a part.
  // -> noms des pieces posees
  const V_CLAY = 4 * IN;                                       // voxel de la pate (clay.js)
  function clayFeatures(c) {
    const T = S.terrain, n = T.n, cell = T.cell, Dd = roadDistance(), r = mulberry((c.seed ^ 0x51ED270B) >>> 0), out = [];
    const g = (x, y) => sample(S.shown, x, y), dRoad = (x, y) => {
      const i = Math.max(0, Math.min(n - 1, Math.round((x - T.x0) / cell))), j = Math.max(0, Math.min(n - 1, Math.round((y - T.y0) / cell)));
      return Dd[j * n + i];
    };
    const inside = (x, y, m) => x > T.x0 + m && y > T.y0 + m && x < T.x0 + (n - 1) * cell - m && y < T.y0 + (n - 1) * cell - m;
    const longer = c.len === 'L' || c.len === 'X' ? 1 : 0;
    // 2026-11-24 (« la route doit passer dans les caves et sous les ponts ») : tunnels et arches SUR la route d'abord ;
    // hors de la route, une arche ou un tunnel de decor de temps en temps
    // « une arche c'est trop court, il faut des vrais tunnels » (2026-11-24) : plus d'arches sur la route, des tunnels longs
    // 2026-11-24 (retour utilisateur « trop de tunnels au-dessus du sol, trop peu en souterrain, reduis leur nombre ») :
    // un tunnel en surface une fois sur deux (+1 en difficile), les souterrains d'abord (tranchee 2a')
    const nRoadTun = (r() < 0.5 ? 1 : 0) + (c.diff === 'D' ? 1 : 0), nRoadArch = 0;
    const nArch = r() < 0.4 ? 1 : 0, nTun = r() < 0.25 ? 1 : 0;
    const used = [];                                            // pieces deja posees : pas l'une sur l'autre
    S.clayFeat = [];                                            // ou elles sont (essais, cadrage)
    const free = (x, y, rad) => used.every(u => Math.hypot(u[0] - x, u[1] - y) > u[2] + rad);
    // ---- sur la route : portion presque droite, au niveau du sol (ni pont ni remblai), sans saut, loin du depart et de
    // tout autre passage de la route (la colline d'un tunnel ne doit en recouvrir aucun)
    const P = S.points, N = P.length, W = S.width;
    const hd = i => { const a = P[(i - 1 + N) % N], b = P[(i + 1) % N]; return Math.atan2(b[1] - a[1], b[0] - a[0]); };
    const wrapA = a => Math.atan2(Math.sin(a), Math.cos(a));
    function roadSpot(m, clear) {                               // m : demi-longueur (points) ; clear : ecart aux autres passages
      for (let tries = 0; tries < 250; tries++) {
        const i = 60 + Math.floor(r() * Math.max(1, N - 120)), h0 = hd(i);
        let ok = true;
        for (let k = -m - 4; k <= m + 4 && ok; k++) {
          const q = P[(i + k + N) % N];
          // le tunnel suit la route : virages (126 degres au plus sur le troncon) et pentes admis ; pas de saut, pas en l'air
          if (q[4] || Math.abs(wrapA(hd((i + k + N) % N) - h0)) > 2.2 || Math.abs(g(q[0], q[1]) - q[2]) > 15 * IN || !inside(q[0], q[1], 40 * IN)) ok = false;
        }
        if (!ok || !free(P[i][0], P[i][1], clear)) continue;
        const seg = [];                                         // le troncon (un point sur 4) : les autres passages s'en tiennent loin
        for (let k = -m; k <= m; k += 4) seg.push(P[(i + k + N) % N]);
        for (let j = 0; j < N && ok; j++) {
          const dj = Math.min(Math.abs(j - i), N - Math.abs(j - i));
          if (dj > m + 25 && seg.some(q => Math.hypot(P[j][0] - q[0], P[j][1] - q[1]) < clear)) ok = false;
        }
        if (ok) return i;
      }
      return -1;
    }
    const nrm = k => { const a = hd((k + N) % N); return [-Math.sin(a), Math.cos(a)]; };
    // tunnels : colline de pate par-dessus la route puis creusee le long de la route (5 tubes cote a cote : voute large
    // et plate, assez pour toute la largeur), creusee un peu plus loin que la colline aux deux bouts
    // galerie le long de la route (indices i + from .. i + to) : 5 tubes creuses cote a cote (voute large et plate), puis
    // le sol refait juste sous la chaussee (2026-11-24, retour en jeu : « trous dans les murs sous les tunnels » : le
    // creusement descendait sous la route, la chaussee flottait au-dessus d'un vide visible depuis les bords)
    // f : fraction de la largeur LOCALE de la route (p[3] : elle varie d'un point a l'autre, jusqu'a 1,6 fois S.width ;
    // 2026-11-24 : avec la largeur moyenne, parois et bosses entre les tubes mordaient sur la chaussee elargie)
    // low : hauteur prise au plus bas de l'axe et de la chaussee affichee a cet endroit (devers : le bord bas d'un virage
    // releve est 2 a 3 m sous l'axe ; le sol refait sous la route depassait de 1 m sur ce bord, 2026-11-24)
    const line = (i, from, to, f, dz, rad, low = false) => { const pts = [];
      for (let q = from; q <= to; q += 2) { const p = P[(i + q + N) % N], [nx, ny] = nrm(i + q), off = f * (p[3] || W), x = p[0] + nx * off, y = p[1] + ny * off;
        pts.push({ x, y, z: (low ? Math.min(p[2], g(x, y)) : p[2]) + dz, r: rad }); }
      return pts; };
    const wMax = (i, from, to) => { let w = W; for (let q = from; q <= to; q++) w = Math.max(w, P[(i + q + N) % N][3] || W); return w; };
    const offs = [-0.4, -0.2, 0, 0.2, 0.4];                     // toute la largeur de la route au niveau de la chaussee
    function gallery(i, from, to, rIn) {
      const wm = wMax(i, from, to); rIn = Math.max(rIn, wm * 0.35);
      // creusee plus large que la chaussee (+/-0,48 ; 0,4 avant : pied des parois 1 a 1,5 m sur le bord de la route)
      for (const f of [-0.48, -0.24, 0, 0.24, 0.48]) clay.tube(line(i, from, to, f, rIn * 0.9, rIn), true);
      const rf = wm * 0.3;                                        // sol : sommet 1,5 m sous la chaussee (raccord arrondi compris)
      // raccord serre (4 m au lieu de 6) : l'union douce gonfle le sol de K/4 entre les tubes, jusqu'a la chaussee
      for (const f of offs) clay.tube(line(i, from, to, f, -rf - 1.5 * IN, rf, true), false, V_CLAY);
    }
    for (let k = 0; k < nRoadTun; k++) {
      // parois epaisses (15 a 22 m ; 6 a 12 m avant : trop minces pour la grille de 4 m, trous en jeu)
      const rIn = Math.max(14 * IN, W * 0.35), thick = (15 + r() * 7) * IN, L0 = (100 + r() * 120) * IN;
      // place pour la colline (les autres passages de la route restent dehors) ; sinon un tunnel plus court, 80 m au moins
      let m = 0, i = -1;
      // galerie creusee au-dela des bouts arrondis de la colline (rayon rIn + thick + raccord) : sinon la colline debordait
      // sur la route a la sortie (2026-11-24, capture utilisateur)
      const ext = Math.ceil((rIn + thick + 1.5 * V_CLAY) / STEP) + 4;
      for (const L of [L0, L0 * 0.7, 80 * IN]) { m = Math.round(L / 2 / STEP); i = roadSpot(m + ext, 0.9 * W + rIn + thick + 5 * IN); if (i >= 0) break; }
      if (i < 0) break;
      const rT = Math.max(rIn, wMax(i, -m - ext, m + ext) * 0.35);    // voute a la largeur locale : parois toujours epaisses
      for (const f of offs) clay.tube(line(i, -m, m, f, rT * 0.9, rT + thick), false, 3 * V_CLAY);   // la colline
      gallery(i, -m - ext, m + ext, rIn);
      used.push([P[i][0], P[i][1], m * STEP + W / 2 + rIn + thick]); out.push('tunnel');
      S.clayFeat.push({ kind: 'roadTunnel', i, x: P[i][0], y: P[i][1], z: P[i][2] });
    }
    // tunnels souterrains (2026-11-24) : la route descend dans une tranchee profonde (piste aleatoire, S.deepCutsQ) ; la
    // pate remet le terrain naturel au-dessus de la partie la plus basse, puis la galerie est creusee dessous
    for (const dc of S.deepCutsQ || []) {
      const rIn = Math.max(14 * IN, wMax(dc.s, -dc.ramp, dc.len + dc.ramp) * 0.35), need = 1.9 * rIn + 12 * IN;
      // toit : le terrain naturel, releve au besoin au-dessus de la voute sur la partie basse de la tranchee (tertre qui
      // se fond dans le relief) ; tunnel sur la partie ou la route est au plus 4 m au-dessus de son point le plus bas
      let zLow = Infinity;
      for (let k = 0; k <= dc.len; k++) zLow = Math.min(zLow, P[(dc.s + k + N) % N][2]);
      const roofZ = (x, y) => Math.max(heightAt(x, y), zLow + need);
      let a = -1, b = -1;
      for (let k = -dc.ramp; k <= dc.len + dc.ramp; k++) {
        const p = P[(dc.s + k + N) % N];
        if (p[2] <= zLow + 4 * IN || heightAt(p[0], p[1]) - p[2] >= need) { if (a < 0) a = k; b = k; }
      }
      if (a < 0 || b - a < 12) continue;
      const i = (dc.s + a + N) % N, len = b - a, path = [];
      for (let q = -6; q <= len + 6; q++) { const p = P[(i + q + N) % N]; path.push({ x: p[0], y: p[1] }); }
      // les AUTRES passages de la route (pas cette tranchee ni ses rampes) restent degages : pas de remblai a moins de
      // W/2 + 8 m, fondu sur 40 m (2026-11-24, capture utilisateur : terre sur la route a cote d'un tunnel souterrain)
      const reach = W / 2 + 160 * IN, guard = [];
      let bx0 = Infinity, by0 = Infinity, bx1 = -Infinity, by1 = -Infinity;
      for (const q of path) { bx0 = Math.min(bx0, q.x); by0 = Math.min(by0, q.y); bx1 = Math.max(bx1, q.x); by1 = Math.max(by1, q.y); }
      for (let k = 0; k < N; k++) {
        const d = ((k - i) % N + N) % N;
        if (d <= len + dc.ramp + 40 || d >= N - dc.ramp - 40) continue;
        const q = P[k]; if (q[0] > bx0 - reach && q[0] < bx1 + reach && q[1] > by0 - reach && q[1] < by1 + reach) guard.push(q);
      }
      const r0 = W / 2 + 8 * IN, r1 = 40 * IN;
      const roofG = (x, y) => {
        // pres d'une autre route : sol AFFICHE (route en deblai comprise), pas le terrain naturel qui reboucherait le deblai
        const t = roofZ(x, y); if (!guard.length) return t;
        const base = g(x, y); if (t <= base) return t;
        let d = Infinity; for (const q of guard) { const e = Math.hypot(q[0] - x, q[1] - y); if (e < d) d = e; }
        const u = Math.max(0, Math.min(1, (d - r0) / r1));
        return base + (t - base) * u * u * (3 - 2 * u);
      };
      clay.fillTo(path, W / 2 + 110 * IN, roofG, 50 * IN);
      gallery(i, -8, len + 8, rIn);
      // rampes de cette tranchee recouvertes par le remblai (virage pres de l'entree) : galerie prolongee jusqu'au bout
      const covered = k => { const p = P[(i + k + N) % N], [nx, ny] = nrm(i + k);
        return [-0.45, 0, 0.45].some(f => [3, 6].some(h => clay.field(p[0] + nx * W * f, p[1] + ny * W * f, p[2] + h * IN) < 0)); };
      let e0 = -8, e1 = len + 8;
      for (let k = -9; k >= -8 - dc.ramp - 30; k--) if (covered(k)) e0 = k - 4;
      for (let k = len + 9; k <= len + 8 + dc.ramp + 30; k++) if (covered(k)) e1 = k + 4;
      if (e0 < -8) gallery(i, e0, -8, rIn);
      if (e1 > len + 8) gallery(i, len + 8, e1, rIn);
      used.push([P[i][0], P[i][1], len * STEP]); out.push('tunnel souterrain');
      S.clayFeat.push({ kind: 'deepTunnel', i, len, x: P[i][0], y: P[i][1], z: P[i][2] });
    }
    // arches : en travers de la route, pieds sur les bas-cotes, passage d'au moins 8 m au-dessus de la chaussee
    for (let k = 0; k < nRoadArch; k++) {
      const rad = (7 + r() * 5) * IN, i = roadSpot(6, W / 2 + 40 * IN); if (i < 0) break;
      const p = P[i], [nx, ny] = nrm(i), K = 1.5 * V_CLAY;       // K : raccord arrondi de la pate (clay.tube)
      let half = W / 2 + rad * 1.35 + K + 4 * IN, apex = p[2] + Math.max(16 * IN, 0.3 * W) + rad, pts = [];
      for (let pass = 0; pass < 8; pass++) {
        const ax = p[0] - nx * half, ay = p[1] - ny * half, bx = p[0] + nx * half, by = p[1] + ny * half, ga = g(ax, ay), gb = g(bx, by);
        pts = [];
        for (let q = 0; q <= 16; q++) {
          const t = q / 16, base = ga + (gb - ga) * t - 1.5 * rad;
          pts.push({ s: -half + 2 * half * t, x: ax + (bx - ax) * t, y: ay + (by - ay) * t, z: base + (apex - base) * Math.sin(Math.PI * t) ** 0.6,
                     r: rad * (1.35 - 0.45 * Math.sin(Math.PI * t)) });
        }
        // coupe de la route (largeur + 3 m de chaque cote, de 1 a 8 m au-dessus) : hors de l'arche et de son raccord
        let worst = Infinity;
        for (let sl = -W / 2 - 3 * IN; sl <= W / 2 + 3 * IN; sl += 4 * IN) for (const hz of [1, 4, 8]) {
          const z = p[2] + hz * IN;
          for (let k2 = 1; k2 < pts.length; k2++) {
            const A = pts[k2 - 1], B = pts[k2], us = B.s - A.s, uz = B.z - A.z, L2 = us * us + uz * uz || 1;
            const t = Math.max(0, Math.min(1, ((sl - A.s) * us + (z - A.z) * uz) / L2));
            worst = Math.min(worst, Math.hypot(sl - A.s - us * t, z - A.z - uz * t) - (A.r + (B.r - A.r) * t) - K);
          }
        }
        if (worst >= 0) break;
        apex += -worst * 1.2 + 2 * IN; half += 4 * IN;         // trop bas ou pieds trop pres : plus haute, plus large
      }
      clay.tube(pts, false); used.push([p[0], p[1], half]); out.push('pont de terre');
      S.clayFeat.push({ kind: 'roadArch', i, x: p[0], y: p[1], z: apex, th: Math.atan2(ny, nx) });
    }
    // arches : au-dessus d'un creux (sol du milieu plus bas que les pieds), portee 50 a 110 m, sommet 14 a 30 m au-dessus
    for (let k = 0, tries = 0; k < nArch && tries < 400; tries++) {
      const span = (50 + r() * 60) * IN, th = r() * Math.PI, rad = (6 + r() * 5) * IN;
      const cx = T.x0 + r() * (n - 1) * cell, cy = T.y0 + r() * (n - 1) * cell;
      const ax = cx - Math.cos(th) * span / 2, ay = cy - Math.sin(th) * span / 2, bx = cx + Math.cos(th) * span / 2, by = cy + Math.sin(th) * span / 2;
      if (!inside(ax, ay, 60 * IN) || !inside(bx, by, 60 * IN) || !free(cx, cy, span / 2 + rad)) continue;
      let ok = true, low = Infinity;
      for (let t = 0; t <= 1 && ok; t += 0.1) {
        const x = ax + (bx - ax) * t, y = ay + (by - ay) * t;
        if (dRoad(x, y) < 45 * IN + rad) ok = false;
        if (t > 0.2 && t < 0.8) low = Math.min(low, g(x, y));
      }
      const ga = g(ax, ay), gb = g(bx, by);
      if (!ok || Math.min(ga, gb) - low < (tries < 250 ? 8 : 2) * IN) continue;   // un vrai creux sous l'arche (d'abord)
      const apex = Math.max(ga, gb) + (14 + r() * 16) * IN, pts = [];
      for (let q = 0; q <= 16; q++) {
        const t = q / 16, x = ax + (bx - ax) * t, y = ay + (by - ay) * t, base = ga + (gb - ga) * t - 1.5 * rad;
        pts.push({ x, y, z: base + (apex - base) * Math.sin(Math.PI * t) ** 0.8, r: rad * (1.35 - 0.45 * Math.sin(Math.PI * t)) });
      }
      clay.tube(pts, false); used.push([cx, cy, span / 2 + rad]); out.push('pont de terre'); k++;
      S.clayFeat.push({ kind: 'arch', x: cx, y: cy, z: apex, th });
    }
    // tunnels : dans une colline (au moins 22 m au-dessus de son pied), de part en part
    for (let k = 0, tries = 0; k < nTun && tries < 600; tries++) {
      const cx = T.x0 + r() * (n - 1) * cell, cy = T.y0 + r() * (n - 1) * cell, top = g(cx, cy);
      if (!inside(cx, cy, 120 * IN) || dRoad(cx, cy) < 80 * IN || !free(cx, cy, 60 * IN)) continue;
      const th = r() * Math.PI, ux = Math.cos(th), uy = Math.sin(th), rad = (7 + r() * 5) * IN;
      // bouts : la ou le sol redescend au pied de la colline, des deux cotes (au plus 160 m)
      const foot = [];
      for (const sd of [1, -1]) {
        let d = 10 * IN, f = null;
        for (; d < 160 * IN; d += 4 * IN) { const z = g(cx + ux * d * sd, cy + uy * d * sd); if (top - z > 22 * IN) { f = { d, z }; break; } }
        foot.push(f);
      }
      if (!foot[0] || !foot[1]) continue;
      const ax = cx + ux * (foot[0].d + rad), ay = cy + uy * (foot[0].d + rad), bx = cx - ux * (foot[1].d + rad), by = cy - uy * (foot[1].d + rad);
      if (dRoad(ax, ay) < 40 * IN || dRoad(bx, by) < 40 * IN || !inside(ax, ay, 30 * IN) || !inside(bx, by, 30 * IN)) continue;
      const za = foot[0].z + rad * 0.55, zb = foot[1].z + rad * 0.55, pts = [];
      if (top - Math.max(za, zb) < rad * 1.6) continue;          // assez de matiere au-dessus de la voute
      for (let q = 0; q <= 12; q++) { const t = q / 12; pts.push({ x: ax + (bx - ax) * t, y: ay + (by - ay) * t, z: za + (zb - za) * t, r: rad }); }
      clay.tube(pts, true); used.push([cx, cy, Math.max(foot[0].d, foot[1].d)]); out.push('tunnel'); k++;
      S.clayFeat.push({ kind: 'tunnel', x: ax, y: ay, z: za, th, bx, by });
    }
    if (out.length) { clearSeats(); renderProps(); }
    return out;
  }
  // o : { density 0-2, veg / rock / built / road 0-3 (AI_LEVEL), clear (m sans rien au bord), reach (m), cluster 0-2,
  //       borrow 0 theme seul / 1 themes proches / 2 tous les themes adaptes au sol, big, sight (virages degages) }
  function aiPlace(rnd, o) {
    const T = S.terrain, D = roadDistance(), noise = aiNoise(rnd), [per, cap, bigK] = AI_DENSITY[o.density];
    const kit = $('crkit').value, R = S.eff || S.points;
    let len = 0;
    for (let i = 1; i < R.length; i++) len += Math.hypot(R[i][0] - R[i - 1][0], R[i][1] - R[i - 1][1]);
    const mLen = len / IN, target = Math.min(cap, mLen * 400 / per);
    // palette du tirage : quelques familles et modeles par sol et par role, pour un ensemble coherent (et different a chaque fois)
    const shuffle = a => { for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };
    const pals = new Map(), borrowed = new Set();
    const usable = (d, role) => Array.from({ length: d.n }, (_, i) => i).filter(i => !d.hide?.includes(i) && d.dims?.[i] && (role === 'big' || d.dims[i].r < 45));
    const fams = (kk, role) => Object.entries(propKinds).filter(([id, d]) => id.startsWith(kk + '|') && d.role === role && usable(d, role).length);
    const kin = k => AI_KIN.find(g => g.includes(k))?.filter(x => x !== k) || [];
    // ou chercher : theme du sol, theme de la piste, puis (selon le reglage) themes proches, puis themes faits pour ce sol.
    // Le premier niveau qui a des objets gagne : un theme complet ne recoit jamais d'objets d'ailleurs
    const palette = (mat, role) => {
      const key = `${mat}|${role}`;
      if (pals.has(key)) return pals.get(key);
      const mk = matOf(mat).kit || kit;
      const tiers = [[mk], [kit]];
      if (o.borrow >= 1) tiers.push(shuffle([...new Set([...kin(mk), ...kin(kit)])]));
      if (o.borrow >= 2) tiers.push(AI_DONORS[matClass(mat)] || []);
      let list = [], own = true;
      for (let t = 0; t < tiers.length && !list.length; t++) {
        own = t < 2;
        // emprunt : un seul theme a la fois (le premier qui a ce role), pour garder un ensemble coherent
        for (const kk of tiers[t]) { list = fams(kk, role); if (list.length) break; }
      }
      // variete (piste aleatoire, 2026-11-13 : decor « trop repetitif ») : aussi les familles des themes proches, et plus
      // de familles / modeles tires pour chaque role
      if (o.variety && own) list = list.concat(shuffle([...new Set([...kin(mk), ...kin(kit)])]).flatMap(kk => fams(kk, role)));
      const out = [];
      for (const [id, d] of shuffle(list).slice(0, own ? (o.variety ? 6 : 3) : 2)) {
        const [k, t] = id.split('|');
        const ms = shuffle(usable(d, role)).slice(0, own ? (o.variety ? 7 : 4) : 3);
        if (ms.length) out.push({ k, t, d, ms, far: k !== mk && k !== kit });
      }
      pals.set(key, out);
      return out;
    };
    // grille d'occupation (bien plus rapide que S.props.some pour des milliers d'essais)
    const GS = 64 * IN, grid = new Map(), bigs = [];
    const add = p => { if (kindOf(p)?.big) { bigs.push(p); return; } const key = Math.floor(p.x / GS) * 100003 + Math.floor(p.y / GS); (grid.get(key) || grid.set(key, []).get(key)).push(p); };
    S.props.forEach(add);
    function put(c, m, x, y) {
      const k = c.d, [a, b] = k.scale;
      const p = { k: c.k, t: c.t, m, x, y, yaw: +(rnd() * 2 * Math.PI).toFixed(3), s: +(a + rnd() * (b - a)).toFixed(2), ai: 1, c: CAT_VERSION };
      if (!inTerrain(p) || seatOf(p).deg > STEEP_MAX || buriedTooMuch(p) || propConflict(p, true)) return false;
      const sp = k.spacing * IN, bp = rad(p);
      const clash = q => { const gap = !!k.big !== !!kindOf(q)?.big ? 0 : Math.max(sp, (kindOf(q)?.spacing || 3) * IN) * 0.8;
        return Math.hypot(q.x - x, q.y - y) < Math.max(gap, (bp + rad(q)) * apart(p, q)); };
      if (bigs.some(clash)) return false;
      const reach = Math.ceil((60 * IN + bp) / GS), ga = Math.floor(x / GS), gb = Math.floor(y / GS);
      for (let u = ga - reach; u <= ga + reach; u++) for (let w = gb - reach; w <= gb + reach; w++) { const cell = grid.get(u * 100003 + w); if (cell?.some(clash)) return false; }
      S.props.push(p); add(p);
      if (c.far) borrowed.add(c.k);
      return true;
    }
    const slopeAt = (x, y) => { const e = 4 * IN; return Math.hypot(shownAt(x + e, y) - shownAt(x - e, y), shownAt(x, y + e) - shownAt(x, y - e)) / (2 * e); };
    const paintAt = (x, y) => { const i = Math.round((x - T.x0) / T.cell), j = Math.round((y - T.y0) / T.cell);
      return i < 0 || j < 0 || i >= T.n || j >= T.n ? -1 : Math.min(T.paint[j * T.n + i], MATERIALS.length + EXTRA_MATS.length - 1); };
    // point a cote de la route : [x, y, indice du point de route, virage (rad sur ~60 m, > 0 : ce cote est a l'interieur)]
    const beside = (off, side) => { const i = Math.floor(rnd() * (R.length - 1)), a = R[i], b = R[i + 1], l = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
      const p = R[Math.max(0, i - 8)], q = R[Math.min(R.length - 1, i + 8)];
      let turn = Math.atan2(q[1] - a[1], q[0] - a[0]) - Math.atan2(a[1] - p[1], a[0] - p[0]);
      turn = Math.atan2(Math.sin(turn), Math.cos(turn));
      return [a[0] - (b[1] - a[1]) / l * (a[3] / 2 + off) * side, a[1] + (b[0] - a[0]) / l * (a[3] / 2 + off) * side, i, turn * side]; };
    const count = {}, missing = [];
    // sols autour de la route (echantillon) : sert a savoir quels roles ont vraiment des objets ici
    const mats = new Map();
    for (let k = 0; k < 400; k++) { const [x, y] = beside(rnd() * o.reach * IN, rnd() < 0.5 ? 1 : -1), m = paintAt(x, y); if (m >= 0) mats.set(m, (mats.get(m) || 0) + 1); }
    const matN = [...mats.values()].reduce((a, b) => a + b, 0) || 1;
    // part du terrain ou ce role peut pousser : a des objets pour ce sol ET le sol lui convient
    const avail = role => [...mats].reduce((a, [m, n]) => a + (palette(m, role).length ? n / matN * (AI_AFF[matClass(m)][role] ?? 0.3) : 0), 0);
    const level = role => AI_LEVEL[o[AI_GROUP[role]] ?? 2];
    // parts : un role sans objet ne laisse pas la carte vide, les autres prennent une partie de sa place (x1,5 au plus,
    // pour ne pas noyer une piste d'Egouts sous les tuyaux)
    let asked = 0, served = 0;
    const share = {};
    for (const [role, sh] of AI_LAYERS) {
      // petits decors (herbes, fleurs, buissons) plus nombreux si demande (piste aleatoire : o.small)
      const w = sh * level(role) * (o.small && (role === 'cover' || role === 'shrub') ? o.small : 1), a = w ? avail(role) : 0;
      asked += w; share[role] = a > 0.02 ? w : 0;
      if (w && a <= 0.02) missing.push(role); else served += w;
    }
    const boost = served ? Math.min(1.5, asked / served) : 0;
    const spread = o.reach / 230, groves = [-2, 0, 0.2][o.cluster];
    // fond de carte : gros objets, derriere tout le reste
    if (o.big) {
      const want = Math.max(8, Math.min(60, Math.round(mLen / 120 * bigK)));
      for (let tr = 0, got = 0; tr < want * 25 && got < want; tr++) {
        const [x, y] = beside((110 + rnd() * 420) * IN, rnd() < 0.5 ? 1 : -1), mat = paintAt(x, y);
        if (mat < 0 || D[Math.round((y - T.y0) / T.cell) * T.n + Math.round((x - T.x0) / T.cell)] < 90 * IN) continue;
        const pal = palette(mat, 'big'); if (!pal.length) continue;
        const c = pal[Math.floor(rnd() * pal.length)];
        if (put(c, c.ms[Math.floor(rnd() * c.ms.length)], x, y)) { got++; count.big = got; }
      }
    }
    // bord de route : panneaux, lampes, barrieres, plus nombreux dans les virages (a l'exterieur : ils les annoncent)
    const roadK = level('road') * (o.density + 1) / 2;
    for (let i = 8; roadK && i < R.length - 8; i += 4) {
      const a = R[i - 8], c0 = R[i], b = R[i + 8];
      let turn = Math.atan2(b[1] - c0[1], b[0] - c0[0]) - Math.atan2(c0[1] - a[1], c0[0] - a[0]);
      turn = Math.atan2(Math.sin(turn), Math.cos(turn));
      const sharp = Math.abs(turn) > 0.35;
      if (rnd() > (sharp ? 0.3 : 0.05) * roadK) continue;
      const l = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1, side = sharp ? (turn > 0 ? -1 : 1) : rnd() < 0.5 ? 1 : -1, off = c0[3] / 2 + (2 + rnd() * 5) * IN;
      const x = c0[0] - (b[1] - a[1]) / l * off * side, y = c0[1] + (b[0] - a[0]) / l * off * side, mat = paintAt(x, y);
      if (mat < 0) continue;
      const pal = palette(mat, 'road'); if (!pal.length) continue;
      const c = pal[Math.floor(rnd() * pal.length)];
      if (put(c, c.ms[Math.floor(rnd() * c.ms.length)], x, y)) count.road = (count.road || 0) + 1;
    }
    // couches : du plus massif au plus petit, l'herbe remplit ce qui reste
    for (const [role, , d0, d1, maxSlope, glade] of AI_LAYERS) {
      const want = Math.round(target * share[role] * boost);
      const near = Math.max(d0, o.clear), far = Math.max(near + 15, d1 * spread), tall = AI_TALL.has(role);
      for (let tr = 0, got = 0; tr < want * 14 && got < want; tr++) {
        const off = near + (far - near) * rnd() * rnd(), [x, y, i, inner] = beside(off * IN, rnd() < 0.5 ? 1 : -1), mat = paintAt(x, y);
        if (mat < 0) continue;
        // visibilite : rien de haut a l'interieur d'un virage (il cacherait la sortie) ni au ras de la grille de depart
        if (tall && o.sight && off < 30 && (inner > 0.3 || i < 12 || i > R.length - 12)) continue;
        if (glade > -1 && noise(x, y, 140 * IN) < glade + groves) continue;          // clairieres entre les bosquets
        const sl = slopeAt(x, y);
        if (sl > maxSlope) continue;
        // sur une pente raide, un rocher va partout ; ailleurs, selon le sol
        if (!(role === 'rock' && sl > 0.45) && rnd() > (AI_AFF[matClass(mat)][role] ?? 0.3)) continue;
        const pal = palette(mat, role); if (!pal.length) continue;
        const c = pal[Math.floor(rnd() * pal.length)];
        if (put(c, c.ms[Math.floor(rnd() * c.ms.length)], x, y)) { got++; count[role] = got; }
      }
    }
    return { count, missing, borrowed: [...borrowed] };
  }
  // points d'eau du decor automatique (2026-11-13) : parfois (2 fois sur 3) 1 a 3 creux du relief, n'importe ou (aussi
  // au bord de la route) mais jamais sur la route (1 m de marge), remplis presque a ras bord (eau marquee ai : repartent
  // avec le decor automatique). -> nombre d'eaux posees
  function aiWaters(rnd, D) {
    const T = S.terrain; if (!T || !S.shown) return 0;
    if (rnd() < 1 / 3) return 0;
    const want = 1 + Math.floor(rnd() * 3), n = T.n, types = ['clear', 'clear', 'lagoon', 'swamp'];
    const taken = new Uint8Array(n * n);
    for (const w of S.waters) { const b = waterBasin(w); if (b) b.region.forEach((r, v) => { if (r) taken[v] = 1; }); }
    let got = 0;
    for (let tr = 0; tr < 400 && got < want; tr++) {
      const i = 2 + Math.floor(rnd() * (n - 4)), j = 2 + Math.floor(rnd() * (n - 4)), v = j * n + i;
      if (D[v] < 2 * IN || taken[v]) continue;
      const w = { x: Math.round(T.x0 + i * T.cell), y: Math.round(T.y0 + j * T.cell),
                  // niveau au moins 5 m sous le bord du creux (2026-11-14, demande utilisateur ; 0,3 a 1,5 m avant)
                  dz: -Math.round((5 + rnd() * 1.5) * 10) / 10 * IN, type: types[Math.floor(rnd() * types.length)], ai: 1 };
      const b = waterBasin(w);
      if (!b || b.count < 25 || b.count > 6000 || b.level - b.bottom < 1 * IN) continue;
      let ok = true;
      for (let u = 0; u < b.region.length && ok; u++) if (b.region[u] && (taken[u] || D[u] < 1 * IN)) ok = false;
      if (!ok || roadInWater(b)) continue;
      b.region.forEach((r, u) => { if (r) taken[u] = 1; });
      S.waters.push(w); got++;
    }
    return got;
  }
  // objets poses dans l'eau retires (2026-11-14, retour utilisateur « le decor genere pose parfois des objets dans
  // l'eau ») : TOUTES les eaux (decor auto, remplies, peintes ; avant : celles du decor auto seulement) et toute
  // l'emprise du pied de l'objet + une demi-case de marge (avant : le seul sommet le plus proche du centre : objets de
  // la rive a moitie dans l'eau gardes). keep(p) vrai : objet non concerne (deja la avant). -> nombre retire
  function dropPropsInWater(keep) {
    const T = S.terrain; if (!T || !S.waters.length) return 0;
    const n = T.n, wet = new Uint8Array(n * n);
    let any = false;
    for (const w of S.waters) { const b = waterBasin(w); if (b) b.region.forEach((r, v) => { if (r) { wet[v] = 1; any = true; } }); }
    if (!any) return 0;
    const before = S.props.length;
    S.props = S.props.filter(p => {
      if (keep(p) || p.road || p.ed) return true;         // pose a la main : laisse ou il est
      const R = footOf(p) + 0.5 * T.cell, ci = (p.x - T.x0) / T.cell, cj = (p.y - T.y0) / T.cell, k = R / T.cell;
      for (let j = Math.max(0, Math.floor(cj - k)); j <= Math.min(n - 1, Math.ceil(cj + k)); j++)
        for (let i = Math.max(0, Math.floor(ci - k)); i <= Math.min(n - 1, Math.ceil(ci + k)); i++)
          if (wet[j * n + i] && Math.hypot(i - ci, j - cj) * T.cell <= R) return false;
      return true;
    });
    return before - S.props.length;
  }
  function inAiWater(x, y) {                                    // objet dans une eau du decor automatique
    const T = S.terrain, n = T.n, v = Math.round((y - T.y0) / T.cell) * n + Math.round((x - T.x0) / T.cell);
    return S.waters.some(w => w.ai && waterBasin(w)?.region[v]);
  }
  function aiDecor(seedIn, extra) {
    if (S.points.length < 8) { status('Trace d\'abord une route : le décor se construit autour d\'elle', 'err'); return; }
    // graine imposee : piste aleatoire a partir d'un code (meme code = meme decor) ; clic sur le bouton : au hasard
    const seed = Number.isFinite(seedIn) ? seedIn >>> 0 : (Date.now() ^ (Math.random() * 2 ** 31)) >>> 0;
    let s = seed;                                                 // mulberry32
    const rnd = () => { s = (s + 0x6D2B79F5) | 0; let t = Math.imul(s ^ (s >>> 15), 1 | s); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
    S.props = S.props.filter(p => !p.ai);
    S.waters = S.waters.filter(w => !w.ai); if (S.waterSel >= S.waters.length) S.waterSel = -1;
    aiClearRelief();
    const amp = +$('craiamp').value;
    if (amp > 0 || extra?.farHills) aiRelief(amp, rnd, roadDistance(), extra?.farHills || 0);
    refreshTerrainMesh(); rebuild();
    const nw = aiWaters(rnd, roadDistance());                   // points d'eau dans les creux (parfois)
    const o = { ...aiOptions(), ...(extra || {}) };                // extra : reglages imposes (piste aleatoire)
    const { count: c, missing, borrowed } = aiPlace(rnd, o);
    // rien de pose dans l'eau. Zones d'eau calculees UNE fois (2026-11-14 : inAiWater par objet refaisait le remplissage
    // de chaque eau pour chacun des ~4000 objets -> plusieurs minutes, navigateur bloque sur 0LD-IW7ENN-1R)
    dropPropsInWater(p => !p.ai);
    renderWater(); syncWaterLevel();
    renderProps(); saveDraft(); aiSaveOptions();
    const n = Object.values(c).reduce((a, b) => a + b, 0), names = S.info?.kits || {};
    // bilan sous le bouton : ce qui a ete pose, ce qui vient d'un autre theme, ce qui manque (et comment l'obtenir)
    // (texte compose : traduit ici morceau par morceau, le bloc est marque data-noi18n)
    const tt = s => window.CTR_I18N?.t(s) ?? s;
    const parts = ['tree', 'shrub', 'cover', 'rock', 'prop', 'house', 'road', 'big'].filter(r => c[r]).map(r => `${c[r]} ${tt(AI_ROLE_LABEL[r])}`);
    let rep = `<b>${n} ${tt('objet(s)')}</b>` + (parts.length ? ' : ' + parts.join(', ') : '');
    if (nw) rep += `<br>💧 ${nw} ${tt('point(s) d\'eau dans les creux')}`;
    if (borrowed.length) rep += `<br>↪ ${tt('Empruntés à :')} ${borrowed.map(k => tt(names[k] || k).replace(/ \(.*/, '')).join(', ')}`;
    if (missing.length) rep += `<br>⚠ ${tt('Rien de disponible pour :')} ${missing.map(r => tt(AI_ROLE_LABEL[r])).join(', ')}`
      + (o.borrow < 2 ? ' — ' + tt('passe « Objets d\'autres thèmes » sur « Tous les thèmes adaptés au sol »') : '');
    $('crairep').innerHTML = rep; $('crairep').hidden = false;
    status(`Décor automatique : ${n} objet(s)` + (c.big ? `, dont ${c.big} gros en fond de carte` : '') + (amp ? `, relief jusqu'à ${amp} m` : '')
           + (nw ? `, ${nw} point(s) d'eau` : ''), n ? 'ok' : 'err');
  }
  function aiRemove() {
    S.props = S.props.filter(p => !p.ai); aiClearRelief();
    S.waters = S.waters.filter(w => !w.ai); if (S.waterSel >= S.waters.length) S.waterSel = -1;
    refreshTerrainMesh(); rebuild(); renderWater(); syncWaterLevel(); renderProps(); saveDraft();
    $('crairep').hidden = true;
    status('Décor automatique retiré : tes objets et ton relief restent', 'ok');
  }
  // reglages du decor automatique : gardes d'une piste a l'autre (preference de l'utilisateur, pas donnee de la piste)
  const AI_KEY = 'ctr_creator_ai', AI_FIELDS = ['craidens', 'craiveg', 'crairock', 'craibuilt', 'crairoad', 'craiclear', 'craireach', 'craicluster', 'craiborrow', 'craiamp'];
  const aiOptions = () => ({ density: +$('craidens').value, veg: +$('craiveg').value, rock: +$('crairock').value, built: +$('craibuilt').value,
    road: +$('crairoad').value, clear: +$('craiclear').value, reach: +$('craireach').value, cluster: +$('craicluster').value,
    borrow: +$('craiborrow').value, big: $('craibig').checked, sight: $('craisight').checked });
  const aiShowValues = () => { $('craiampv').textContent = $('craiamp').value; $('craiclearv').textContent = $('craiclear').value; $('craireachv').textContent = $('craireach').value; };
  function aiSaveOptions() {
    try { localStorage.setItem(AI_KEY, JSON.stringify({ ...Object.fromEntries(AI_FIELDS.map(id => [id, $(id).value])), craibig: $('craibig').checked, craisight: $('craisight').checked })); } catch (e) { /* sans importance */ }
  }
  function aiLoadOptions() {
    try {
      const v = JSON.parse(localStorage.getItem(AI_KEY) || '{}');
      for (const id of AI_FIELDS) if (v[id] != null) $(id).value = v[id];
      for (const id of ['craibig', 'craisight']) if (v[id] != null) $(id).checked = !!v[id];
    } catch (e) { /* sans importance */ }
    aiShowValues();
  }
  // styles tout faits : remplissent les reglages (qu'on peut retoucher ensuite)
  const AI_PRESETS = { balanced: [1, 2, 2, 2, 2, 4, 230, 1], nature: [1, 3, 2, 1, 1, 6, 230, 1], clear: [0, 2, 1, 1, 2, 15, 160, 1], wild: [2, 3, 3, 0, 0, 4, 280, 2], built: [1, 1, 1, 3, 3, 8, 200, 0] };
  function aiPreset(name) {
    const v = AI_PRESETS[name]; if (!v) return;
    ['craidens', 'craiveg', 'crairock', 'craibuilt', 'crairoad', 'craiclear', 'craireach', 'craicluster'].forEach((id, i) => { $(id).value = v[i]; });
    aiShowValues(); aiSaveOptions();
  }
  function syncAi() {
    const has = S.props.some(p => p.ai) || S.terrain?.aih?.some(v => v) || S.waters.some(w => w.ai);
    $('craigo').textContent = has ? '🎲 Régénérer un autre décor' : '🤖 Créer le décor';
    $('crairm').hidden = !has;
  }
  // liste deroulante des objets du theme : vignette 3D de chaque modele, clic = choisir / retirer
  const thumbR = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  thumbR.setSize(64, 64); thumbR.setPixelRatio(1);
  const thumbScene = new THREE.Scene(), thumbCam = new THREE.PerspectiveCamera(32, 1, 1, 1e7);
  thumbCam.up.set(0, 0, 1);
  thumbScene.add(new THREE.HemisphereLight(0xffffff, 0x666655, 2.4));
  const thumbSun = new THREE.DirectionalLight(0xffffff, 1.6); thumbSun.position.set(1, -1, 2); thumbScene.add(thumbSun);
  let thumbQueue = Promise.resolve();
  function thumb(k, t, m, img) {
    thumbQueue = thumbQueue.then(async () => {
      const mdl = await propModelP(k, t, m, 1).promise;      // vignettes : toujours le meme detail
      if (!mdl || !img.isConnected) return;
      const mesh = new THREE.Mesh(mdl.g, mdl.mats), bs = mdl.g.boundingSphere;
      thumbScene.add(mesh);
      const dir = new THREE.Vector3(1, -1.4, 0.9).normalize();
      thumbCam.position.copy(bs.center).addScaledVector(dir, bs.radius * 3.3); thumbCam.lookAt(bs.center);
      thumbCam.near = bs.radius * 0.5; thumbCam.far = bs.radius * 10; thumbCam.updateProjectionMatrix();
      thumbR.render(thumbScene, thumbCam);
      img.src = thumbR.domElement.toDataURL();
      thumbScene.remove(mesh);
    });
  }
  // classement « par type » : familles d'objets regroupees par genre, tous themes confondus (cle de famille du kit)
  const PROP_TYPES = [
    ['🌳 Arbres et palmiers', ['palm', 'tree', 'pine']],
    ['🌿 Plantes, fleurs et algues', ['plant', 'grass', 'flower', 'giant', 'bush', 'kelp', 'coral', 'cactus', 'mushroom', 'vine']],
    ['🪨 Rochers, cristaux et neige', ['rock', 'crystal', 'gems', 'snow']],
    ['🗿 Piliers, statues et ruines', ['pillar', 'statue', 'column', 'tiki', 'fossil', 'bones']],
    ['🏠 Bâtiments et huttes', ['house', 'hut', 'building']],
    ['⚙ Machines et industrie', ['pipe', 'barrel', 'fan', 'beam', 'machine', 'tesla', 'drum', 'magnet', 'gear', 'gears', 'cart', 'tech']],
    ['🪧 Objets et décorations', ['beach', 'deco', 'sign', 'fence', 'wood', 'torch', 'lamp', 'lantern', 'spike', 'tire', 'kart', 'card', 'speaker']],
    ['⤴ Rampes et tremplins', ['ramp']]];                  // 2026-11-18 : memes 5 rampes dans tous les themes
  const typeOf = (t, k) => k.big ? '⛰ Gros objets (fond de map)' : (PROP_TYPES.find(([, ts]) => ts.includes(t))?.[0] || '📦 Autres objets');
  // classement par type : une seule categorie par famille, tous themes confondus (tous les palmiers ensemble...)
  const TYPE_ALIAS = { gears: 'gear' };
  // (libelles du catalogue reclasse du 2026-11-17 : track_creator_catalog.FAMILIES ; anciennes cles gardees)
  const TYPE_LABELS = {
    palm: '🌴 Palmiers', tree: '🌳 Arbres', pine: '🌲 Sapins', plant: '🌿 Plantes', grass: '🌾 Herbes', flower: '🌸 Fleurs',
    giant: '🌼 Fleurs géantes', bush: '🌿 Buissons et plantes', kelp: '🌊 Algues', coral: '🪸 Coraux', cactus: '🌵 Cactus',
    mushroom: '🍄 Champignons', vine: '🍂 Lianes, racines et souches', rock: '🪨 Rochers', crystal: '💎 Cristaux et trésors', gems: '💎 Trésors',
    snow: '❄ Neige et glaçons', pillar: '🏛 Piliers et colonnes', statue: '🗿 Statues', column: '🏛 Colonnes et tours', tiki: '🗿 Tikis',
    fossil: '🦴 Fossiles', bones: '🐚 Os, coquillages et étoiles de mer', house: '🏠 Maisons et bâtiments', hut: '🛖 Huttes', building: '🏭 Bâtiments',
    pipe: '🛢 Tuyaux et vannes', barrel: '📦 Barils, caisses et wagonnets', fan: '⚙ Ventilateurs', beam: '🏗 Poutres', machine: '⚙ Machines et engrenages',
    tesla: '⚡ Bobines', drum: '🛢 Fûts et vannes', magnet: '🧲 Aimants et pilons', gear: '⚙ Engrenages',
    cart: '⛏ Wagonnets et outils', tech: '🖥 Écrans et panneaux', beach: '⚓ Barques et épaves', deco: '🏮 Décorations',
    sign: '🪧 Panneaux et drapeaux', fence: '🚧 Clôtures, poteaux et planches', wood: '🪵 Poteaux et clôtures', torch: '🔥 Torches et chandelles',
    lamp: '💡 Lampes, lanternes et torches', lantern: '🏮 Lanternes', spike: '🚧 Grilles et pics', tire: '🛞 Pneus et bottes de foin',
    kart: '🏎 Karts exposés', card: '🃏 Cartes et loterie', speaker: '🔊 Haut-parleurs', prop: '🧩 Objets divers',
    ramp: '⤴ Rampes et tremplins',
    big: '⛰ Falaises et gros objets (fond)' };
  const typeKey = t => TYPE_ALIAS[t] || t;
  const SORT_KEY = 'ctr_creator_sort';
  try { $('crpsort').value = localStorage.getItem(SORT_KEY) || 'style'; } catch (e) { /* sans importance */ }
  // une categorie : titre, bouton « tout », vignettes de une ou plusieurs familles (fams : [[cle 'theme|type', famille]])
  const tileHtml = (kk, nm, m, tip) =>
    `<button class="crptile" data-key="${kk}|${m}" title="${nm}${tip ? ' · ' + tip : ''}" style="width:68px;padding:2px;display:flex;flex-direction:column;align-items:center">
          <img width="64" height="64" style="background:#0002;border-radius:4px"><span style="font-size:9px;max-width:64px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${nm.replace(/^(T\d+_|C\d_|Octane_)/, '')}</span></button>`;
  const famHtml = (fams, title, kitNames) => `<div class="crpcat"><b>${title}</b>
        <button data-all="${fams.map(([kk]) => kk).join(',')}" style="padding:0 6px;font-size:11px">tout</button></div>
      <div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:6px">${fams.flatMap(([kk, k]) => (k.names || []).map((nm, m) =>
        k.hide?.includes(m) ? '' : tileHtml(kk, nm, m, kitNames ? kitNames[kk.split('|')[0]] : ''))).join('')}</div>`;
  const shownCount = k => (k.names || []).length - (k.hide || []).length;   // famille dont tout est masque : pas de titre vide
  // par style : un bloc repliable par theme (le theme courant en premier, ouvert) ; par type : un bloc par genre
  // d'objet (familles de tous les themes, nom du theme en titre) ; vignettes chargees a l'ouverture du bloc
  function renderPropList() {
    const grid = $('crpgrid'), cur = $('crkit').value, names = S.info?.kits || {};
    const kits = [cur, ...(S.info?.order || Object.keys(names)).filter(k => k !== cur)];
    if ($('crpsort').value === 'type') {
      const groups = [...PROP_TYPES.map(([l]) => l), '📦 Autres objets', '⛰ Gros objets (fond de map)'];
      // rampes : la meme famille dans chaque theme -> seulement celle du theme courant (sinon 26 fois chaque rampe)
      const fams = kits.flatMap(kit => Object.entries(propKinds).filter(([kk, k]) => kk.startsWith(kit + '|') && shownCount(k)
        && (kk.split('|')[1] !== 'ramp' || kit === cur)));
      grid.innerHTML = groups.map(g => [g, fams.filter(([kk, k]) => typeOf(kk.split('|')[1], k) === g)]).filter(([, f]) => f.length)
        .map(([g, f], i) => {
          // meme famille dans tous les themes : une seule categorie (theme du modele en infobulle)
          const byType = new Map();
          for (const fam of f) { const t = typeKey(fam[0].split('|')[1]); if (!byType.has(t)) byType.set(t, []); byType.get(t).push(fam); }
          return `<details${i ? '' : ' open'}><summary style="cursor:pointer;font-weight:600;margin:6px 0 2px">${g}
          <span style="font-weight:400;color:var(--muted)">(${f.reduce((a, [, k]) => a + shownCount(k), 0)})</span></summary>${
          [...byType].map(([t, tf]) => famHtml(tf, TYPE_LABELS[t] || tf[0][1].label, names)).join('')}</details>`;
        }).join('');
    } else
      grid.innerHTML = kits.map(kit => `<details data-kit="${kit}"${kit === cur ? ' open' : ''}><summary style="cursor:pointer;font-weight:600;margin:6px 0 2px">${names[kit] || kit}</summary>${
        Object.entries(propKinds).filter(([kk, k]) => kk.startsWith(kit + '|') && shownCount(k)).map(([kk, k]) => famHtml([[kk, k]], k.label)).join('')}</details>`).join('');
    const fill = d => d.querySelectorAll('.crptile').forEach(b => {
      if (b.dataset.done) return;
      b.dataset.done = '1';
      const [k, t, m] = b.dataset.key.split('|');
      thumb(k, t, +m, b.querySelector('img'));
    });
    grid.querySelectorAll('details').forEach(d => { if (d.open) fill(d); d.ontoggle = () => d.open && fill(d); });
    grid.querySelectorAll('.crptile').forEach(b => {
      b.onclick = () => { S.sel.has(b.dataset.key) ? S.sel.delete(b.dataset.key) : S.sel.add(b.dataset.key); syncSel(); saveDraft(); };
    });
    grid.querySelectorAll('[data-all]').forEach(b => b.onclick = () => {
      const keys = b.dataset.all.split(',').flatMap(kk => (propKinds[kk]?.names || []).map((_, m) => `${kk}|${m}`)).filter(k => !hiddenSel(k));
      const all = keys.every(k => S.sel.has(k));
      keys.forEach(k => all ? S.sel.delete(k) : S.sel.add(k)); syncSel(); saveDraft();
    });
    syncSel();
  }
  function syncSel() {
    panel.querySelectorAll('.crptile').forEach(b => b.classList.toggle('primary', S.sel.has(b.dataset.key)));
    const n = [...S.sel].filter(s => selKind(s) && !hiddenSel(s)).length;
    $('crpsel').textContent = `${n} choisi(s)`;
    $('crpnone').hidden = n < 2;
  }
  $('crpsort').onchange = () => { try { localStorage.setItem(SORT_KEY, $('crpsort').value); } catch (e) { /* sans importance */ } renderPropList(); };
  $('crpnone').onclick = () => { S.sel.clear(); syncSel(); saveDraft(); };
  // peinture d'indice v : du theme courant, ou d'un autre theme ({label, color, png, kit})
  const matOf = v => v < MATERIALS.length ? { ...MATERIALS[v], kit: $('crkit').value }
    : EXTRA_MATS[v - MATERIALS.length] || { ...MATERIALS[0], kit: $('crkit').value };
  // theme : matieres a peindre (celles du theme en tete, puis celles des autres themes) et objets a semer
  function applyKit() {
    const kit = $('crkit').value, info = S.info || {}, names = info.kits || {};
    if (info.materials?.[kit]) MATERIALS = info.materials[kit];
    EXTRA_MATS = (info.order || []).flatMap(k => (info.materials?.[k] || []).map(m => ({ ...m, kit: k })));
    const sw = m => `border-left:14px solid rgb(${m.color.map(c => Math.round(c * 255)).join(',')})`;
    $('crmats').innerHTML = MATERIALS.map((m, i) => `<button data-mat="${i}" style="${sw(m)}">${m.label}</button>`).join('');
    $('crmatsx').innerHTML = (info.order || []).filter(k => k !== kit).map(k => `<div class="crpcat"><b>${names[k] || k}</b></div>
      <div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:6px">${EXTRA_MATS.map((m, g) => [m, g]).filter(([m]) => m.kit === k)
        .map(([m, g]) => `<button data-mat="${MATERIALS.length + g}" style="${sw(m)};font-size:11px">${m.label}</button>`).join('')}</div>`).join('');
    panel.querySelectorAll('[data-mat]').forEach(b => b.onclick = () => setPaint(+b.dataset.mat));
    setPaint(S.paint < MATERIALS.length + EXTRA_MATS.length ? S.paint : 0);
    propKinds = {};
    for (const [k, kinds] of Object.entries(info.props || {})) for (const [t, d] of Object.entries(kinds)) propKinds[k + '|' + t] = d;
    if (![...S.sel].some(selKind)) {                                   // rien de choisi : 1re famille du theme
      const t0 = Object.keys(propKinds).find(kk => kk.startsWith(kit + '|'));
      if (t0) (propKinds[t0].names || []).forEach((_, m) => S.sel.add(`${t0}|${m}`));
    }
    renderPropList();
    S.kitInfo = info.kitinfo?.[kit] || null;
    if (S.terrain && S.points.length) { refreshTerrainMesh(); rebuild(); }
  }
  // ---- terrain : hauteurs (pouces, relatives au sol de depart) et matieres par sommet d'une grille carree centree
  // sur le depart (cote au choix). shown = hauteurs AFFICHEES : relief raccorde a la route comme a la generation ----
  const newTerrain = (st, size = 1600) => {
    const n = Math.round(size / 8) + 1;
    return { x0: st.pos[0] - (n - 1) / 2 * T_CELL, y0: st.pos[1] - (n - 1) / 2 * T_CELL, cell: T_CELL, n, size,
             h: new Float32Array(n * n), paint: new Uint8Array(n * n), dig: new Uint8Array(n * n) };
  };
  const tIndex = (i, j) => j * S.terrain.n + i;
  function sample(arr, x, y) {               // valeur interpolee d'une grille du terrain (pouces)
    const T = S.terrain, n = T.n, fx = (x - T.x0) / T.cell, fy = (y - T.y0) / T.cell;
    const i = Math.max(0, Math.min(n - 2, Math.floor(fx))), j = Math.max(0, Math.min(n - 2, Math.floor(fy)));
    const u = Math.max(0, Math.min(1, fx - i)), v = Math.max(0, Math.min(1, fy - j)), k = j * n + i;
    return (arr[k] * (1 - u) + arr[k + 1] * u) * (1 - v) + (arr[k + n] * (1 - u) + arr[k + n + 1] * u) * v;
  }
  // relief sculpte (sans raccord) : plancher du paveur
  const heightAt = (x, y) => S.terrain ? S.groundZ + sample(S.terrain.h, x, y) : S.groundZ;
  // sol tel qu'il sera genere (raccorde a la route) : pose des objets, tabliers de pont
  // (sur les MEMES triangles que le maillage, comme track_creator._mesh_height : l'interpolation bilineaire s'en ecartait de
  // plusieurs metres sur les talus, les objets flottaient ou s'enterraient dans l'apercu)
  function meshAt(H, x, y) {
    const T = S.terrain, n = T.n, fx = (x - T.x0) / T.cell, fy = (y - T.y0) / T.cell;
    const i = Math.max(0, Math.min(n - 2, Math.floor(fx))), j = Math.max(0, Math.min(n - 2, Math.floor(fy)));
    const u = Math.max(0, Math.min(1, fx - i)), v = Math.max(0, Math.min(1, fy - j)), k = j * n + i;
    const a = H[k], b = H[k + 1], c = H[k + n + 1], d = H[k + n];
    return u >= v ? a + u * (b - a) + v * (c - b) : a + u * (c - d) + v * (d - a);
  }
  const shownAt = (x, y) => S.shown && S.shown.length === S.terrain.n ** 2 ? meshAt(S.shown, x, y) : heightAt(x, y);
  // raccord (track_creator._conform) : sous la route + une maille aplani juste sous elle, puis pente douce jusqu'au
  // relief ; chaque passage de la route compte a part (suite de points proches) et le sol suit le passage le plus BAS
  // (sous un croisement : la route du dessus devient un pont). Sous un saut, le sol se raccorde aussi (pas de route).
  // bords edites (outil Bords) : p[5..8] = demi-largeur gauche, droite, relevement du bord gauche, droit (pouces).
  // Route reelle (track_creator.centerline) : [x, y, z, largeur, saut, devers, Lx, Ly, sans talus] (L : normale gauche),
  // centre decale vers le cote elargi, devers = bord gauche au-dessus du centre (le droit autant en dessous)
  const edgesOf = p => [p[5] ?? p[3] / 2, p[6] ?? p[3] / 2, p[7] ?? 0, p[8] ?? 0];
  // point sans talus : le sol ne monte pas vers la route (p[9] ; les colonnes 5 a 8 existent alors)
  function setNoTalus(p, on) {
    if (on) { const e = edgesOf(p); while (p.length < 5) p.push(0); p[5] = e[0]; p[6] = e[1]; p[7] = e[2]; p[8] = e[3]; p[9] = 1; }
    else if (p.length > 9) p[9] = 0;
  }
  function effPoints() {
    const P = S.points, n = P.length;
    // tremplin (track_creator.centerline) : la route se releve avant chaque saut, comme a la generation
    const kick = new Float64Array(n);
    for (let s0 = 0; s0 < n; s0++) {
      const prev = s0 ? s0 - 1 : S.closed ? n - 1 : -1;
      if (!P[s0][4] || prev < 0 || P[prev][4]) continue;
      for (let j = 1; j * STEP <= KICK_LEN; j++) {
        const i = s0 - j >= 0 ? s0 - j : S.closed ? s0 - j + n : -1;
        if (i < 0 || P[i][4]) break;
        kick[i] = Math.max(kick[i], KICK_H * Math.max(0, 1 - (j * STEP / (2 * IN) - 1) / (KICK_LEN / (2 * IN))) ** 2);   // courbe
      }
    }
    return S.eff = P.map((p, i) => {
      const a = P[i > 0 ? i - 1 : S.closed ? n - 1 : 0], b = P[i < n - 1 ? i + 1 : S.closed ? 0 : n - 1];
      let tx = b[0] - a[0], ty = b[1] - a[1]; const l = Math.hypot(tx, ty) || 1; tx /= l; ty /= l;
      const [wl, wr, hl, hr] = edgesOf(p), sh = (wl - wr) / 2;
      return [p[0] - ty * sh, p[1] + tx * sh, p[2] + kick[i] + (hl + hr) / 2, wl + wr, p[4] || 0, (hl - hr) / 2, -ty, tx, p[9] ? 1 : 0];
    });
  }
  // rg = {i0, i1, j0, j1} (sommets de la grille) : seule cette zone est recalculee (pinceau, paveur), le reste de S.shown
  // ne change pas ; le resultat d'un sommet ne depend que de son relief et des segments de route a sa portee
  let cBuf = null;                                       // tableaux de travail, reutilises d'un calcul a l'autre
  function conform(rg = null) {
    const T = S.terrain, n = T.n, N = n * n, below = SINK_UNDER_ROAD + 6;
    // pendant un trait de pinceau, la route ne change pas : ses bords (longs a calculer sur 11 km) sont gardes
    const road = S.brushing && S.strokeRoad ? S.strokeRoad : (() => { const p = effPoints(); return [p, ...realEdges(p)]; })();
    S.strokeRoad = S.brushing ? road : null;
    const [P, EL, ER] = road;
    if (!cBuf || cBuf.N !== N) cBuf = { N, h0: new Float32Array(N), acc: new Float32Array(N), runD: new Float32Array(N), runV: new Float32Array(N),
                                        last: new Int32Array(N), low: new Float32Array(N) };
    const { h0, acc, runD, runV, last } = cBuf;
    if (S.raw?.length !== N) rg = null;
    const I0 = rg ? rg.i0 : 0, I1 = rg ? rg.i1 : n - 1, J0 = rg ? rg.j0 : 0, J1 = rg ? rg.j1 : n - 1;
    for (let j = J0; j <= J1; j++) for (let i = I0, v = j * n + I0; i <= I1; i++, v++) {
      h0[v] = S.groundZ + T.h[v]; acc[v] = runD[v] = Infinity; last[v] = -99;
    }
    let hMax = 0; for (let v = 0; v < N; v++) { const a = Math.abs(T.h[v]); if (a > hMax) hMax = a; }
    S.hMax = hMax;
    // distance et hauteur au segment de bord a-b ; point dans le triangle a-b-c : hauteur de la surface, sinon null
    const toEdge = (x, y, a, b) => {
      const dx = b[0] - a[0], dy = b[1] - a[1], t = Math.max(0, Math.min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / (dx * dx + dy * dy || 1)));
      return [Math.hypot(x - a[0] - dx * t, y - a[1] - dy * t), a[2] + (b[2] - a[2]) * t];
    };
    const inTri = (x, y, a, b, c) => {
      const den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1]);
      if (Math.abs(den) < 1e-6) return null;
      const u = ((b[1] - c[1]) * (x - c[0]) + (c[0] - b[0]) * (y - c[1])) / den, w = ((c[1] - a[1]) * (x - c[0]) + (a[0] - c[0]) * (y - c[1])) / den;
      return u >= 0 && w >= 0 && u + w <= 1 ? u * a[2] + w * b[2] + (1 - u - w) * c[2] : null;
    };
    const count = S.closed ? P.length : P.length - 1;
    for (let k = 0; k < count; k++) {
      const k1 = (k + 1) % P.length;                    // sauts compris : le sol suit la route, seule la route s'arrete
      const l0 = EL[k], l1 = EL[k1], r0 = ER[k], r1 = ER[k1];
      const slope = S.blendSlope ?? BLEND_DEF;
      const reach = T.cell + blendWidth(Math.abs(P[k][2] - S.groundZ) + Math.abs(P[k][5]) + hMax + 2 * IN, 1, slope, T.cell);
      const x0 = Math.min(l0[0], l1[0], r0[0], r1[0]) - reach, x1 = Math.max(l0[0], l1[0], r0[0], r1[0]) + reach;
      const y0 = Math.min(l0[1], l1[1], r0[1], r1[1]) - reach, y1 = Math.max(l0[1], l1[1], r0[1], r1[1]) + reach;
      const i0 = Math.max(I0, Math.floor((x0 - T.x0) / T.cell)), i1 = Math.min(I1, Math.ceil((x1 - T.x0) / T.cell));
      const j0 = Math.max(J0, Math.floor((y0 - T.y0) / T.cell)), j1 = Math.min(J1, Math.ceil((y1 - T.y0) / T.cell));
      const ex0 = x0 + reach, ex1 = x1 - reach, ey0 = y0 + reach, ey1 = y1 - reach;      // boite du segment
      const zlo = Math.min(l0[2], l1[2], r0[2], r1[2]) - below, zhi = Math.max(l0[2], l1[2], r0[2], r1[2]) - below;
      for (let j = j0; j <= j1; j++) for (let i = i0; i <= i1; i++) {
        const v = j * n + i, x = T.x0 + i * T.cell, y = T.y0 + j * T.cell;
        // hors de portee pour CE sommet (la portee ci-dessus vaut pour le plus haut du terrain) : rien de plus a calculer
        const gapX = x < ex0 ? ex0 - x : x > ex1 ? x - ex1 : 0, gapY = y < ey0 ? ey0 - y : y > ey1 ? y - ey1 : 0;
        const free = 1 - Math.min(1, Math.abs(T.h[v]) / SCULPT_FULL);   // relief sculpte : raccord resserre (track_creator._conform)
        const dz = Math.max(Math.abs(h0[v] - zlo), Math.abs(h0[v] - zhi)), lim = T.cell + blendWidth(dz, free, slope, T.cell);
        if (gapX * gapX + gapY * gapY > lim * lim) continue;
        // sous la route : sa surface reelle ; a cote : le bord le plus proche
        const surf = inTri(x, y, l0, l1, r1) ?? inTri(x, y, l0, r1, r0);
        let d = 0, rz = surf;
        if (surf === null) {
          const ea = toEdge(x, y, l0, l1), eb = toEdge(x, y, r0, r1), e = ea[0] <= eb[0] ? ea : eb;
          d = e[0]; rz = e[1];
        }
        rz -= below;
        if (P[k][8] && rz > h0[v]) continue;                 // sans talus : le sol reste dessous (la tranchee, elle, reste)
        const bl = blendWidth(Math.abs(rz - h0[v]), free, slope, T.cell);
        if (d >= T.cell + bl) continue;
        if (last[v] >= 0 && k - last[v] > 3) { if (runV[v] < acc[v]) acc[v] = runV[v]; runD[v] = Infinity; }   // autre passage
        let val = rz;
        if (d > T.cell) { const tt = (d - T.cell) / bl, s = tt * tt * (3 - 2 * tt); val = rz * (1 - s) + h0[v] * s; }
        if (d < runD[v] || (d === runD[v] && val < runV[v])) { runD[v] = d; runV[v] = val; }
        last[v] = k;
      }
    }
    // S.raw : sol raccorde ; S.shown (affiche) en est une copie (refreshTerrainMesh)
    const out = S.raw?.length === N ? S.raw : new Float32Array(N);
    for (let j = J0; j <= J1; j++) for (let i = I0, v = j * n + I0; i <= I1; i++, v++) {
      const a = runD[v] < Infinity ? Math.min(acc[v], runV[v]) : acc[v];
      // creuse sous la route : relief garde seulement s'il est PLUS BAS que le raccord (route en pont) ; plus haut, raccord
      // normal (2026-11-16 : sinon une butte montee au bord devenait un pont de terre au-dessus de la route)
      out[v] = a < Infinity ? (T.dig?.[v] ? Math.min(a, h0[v]) : a) : h0[v];
    }
    clearRoad(out, EL, ER, P, rg);
    S.raw = out;
    if (S.shown?.length !== N || S.shown === out) S.shown = Float32Array.from(out);
    // hauteurs extremes (recherche sous la souris, boite englobante) ; plan de fond : toujours sous le sol (sinon il
    // apparait dans les creux, en aplat beige)
    let low = rg ? S.shownLow : S.groundZ, high = rg ? S.shownHigh : S.groundZ;
    const R = rg ? { i0: Math.max(0, I0 - 1), i1: Math.min(n - 1, I1 + 1), j0: Math.max(0, J0 - 1), j1: Math.min(n - 1, J1 + 1) } : { i0: 0, i1: n - 1, j0: 0, j1: n - 1 };
    for (let j = R.j0; j <= R.j1; j++) for (let i = R.i0, v = j * n + i; i <= R.i1; i++, v++) { const z = out[v]; if (z < low) low = z; if (z > high) high = z; }
    S.shownLow = low; S.shownHigh = high;
    // sous la route aussi : descendue hors du terrain, elle passait sous le plan beige et devenait invisible
    let farZ = low; for (const q of P) if (q[2] < farZ) farZ = q[2];
    far.position.z = farZ - 60;
  }
  // track_creator._clear_road : la grille (8 m) ne suit pas une route dont la hauteur change vite (virage releve) ; la
  // ou sa surface passerait au-dessus de la route, les sommets de la case sont abaisses juste ce qu'il faut
  function clearRoad(H, EL, ER, P, rg = null) {
    const T = S.terrain, n = T.n, c = T.cell, step = 2 * IN, clear = 0.25 * IN, xs = [], ys = [], zs = [];
    const count = S.closed ? P.length : P.length - 1;
    // zone recalculee + une maille : seuls les points de route au-dessus de ses cases comptent
    const I0 = rg ? Math.max(0, rg.i0 - 1) : 0, I1 = rg ? Math.min(n - 1, rg.i1 + 1) : n - 1, J0 = rg ? Math.max(0, rg.j0 - 1) : 0, J1 = rg ? Math.min(n - 1, rg.j1 + 1) : n - 1;
    const bx0 = T.x0 + I0 * c, bx1 = T.x0 + I1 * c, by0 = T.y0 + J0 * c, by1 = T.y0 + J1 * c;
    for (let k = 0; k < count; k++) {
      const k1 = (k + 1) % P.length;
      if (P[k][4] || P[k1][4]) continue;
      const l0 = EL[k], l1 = EL[k1], r0 = ER[k], r1 = ER[k1];
      if (rg && (Math.max(l0[0], l1[0], r0[0], r1[0]) < bx0 || Math.min(l0[0], l1[0], r0[0], r1[0]) > bx1 ||
                 Math.max(l0[1], l1[1], r0[1], r1[1]) < by0 || Math.min(l0[1], l1[1], r0[1], r1[1]) > by1)) continue;
      const nu = Math.max(1, Math.floor(Math.max(Math.hypot(l0[0] - r0[0], l0[1] - r0[1]), Math.hypot(l1[0] - r1[0], l1[1] - r1[1])) / step));
      const nv = Math.max(1, Math.floor(Math.max(Math.hypot(l1[0] - l0[0], l1[1] - l0[1]), Math.hypot(r1[0] - r0[0], r1[1] - r0[1])) / step));
      for (let iv = 0; iv <= nv; iv++) for (let iu = 0; iu <= nu; iu++) {
        const v = iv / nv, u = iu / nu;                      // u : 0 bord droit, 1 bord gauche
        const rx = r0[0] + (r1[0] - r0[0]) * v, lx = l0[0] + (l1[0] - l0[0]) * v, ry = r0[1] + (r1[1] - r0[1]) * v, ly = l0[1] + (l1[1] - l0[1]) * v;
        const rz = r0[2] + (r1[2] - r0[2]) * v, lz = l0[2] + (l1[2] - l0[2]) * v;
        xs.push(rx + (lx - rx) * u); ys.push(ry + (ly - ry) * u); zs.push(rz + (lz - rz) * u);
      }
    }
    const low = cBuf.low;
    for (let pass = 0; pass < 8; pass++) {
      let bad = false;
      for (let j = J0; j <= J1; j++) low.fill(0, j * n + I0, j * n + I1 + 1);
      for (let q = 0; q < xs.length; q++) {
        const fx = (xs[q] - T.x0) / c, fy = (ys[q] - T.y0) / c;
        if (fx < I0 || fy < J0 || fx > I1 || fy > J1) continue;
        const i = Math.min(I1 - 1, Math.floor(fx)), j = Math.min(J1 - 1, Math.floor(fy)), u = fx - i, w = fy - j;
        const A = j * n + i, B = A + 1, C = A + n + 1, D = A + n;
        const z = u >= w ? H[A] + u * (H[B] - H[A]) + w * (H[C] - H[B]) : H[A] + u * (H[C] - H[D]) + w * (H[D] - H[A]);
        const over = z - (zs[q] - clear);
        if (over <= 0.04) continue;
        bad = true;
        for (const V of [A, B, C, D]) if (over > low[V]) low[V] = over;
      }
      if (!bad) return;
      for (let j = J0; j <= J1; j++) for (let v = j * n + I0, e = j * n + I1; v <= e; v++) H[v] -= low[v];
    }
  }
  // boite du monde -> sommets de la grille ; null si elle ne touche pas le terrain
  function gridRange(box) {
    const T = S.terrain, n = T.n;
    const i0 = Math.max(0, Math.floor((box.x0 - T.x0) / T.cell)), i1 = Math.min(n - 1, Math.ceil((box.x1 - T.x0) / T.cell));
    const j0 = Math.max(0, Math.floor((box.y0 - T.y0) / T.cell)), j1 = Math.min(n - 1, Math.ceil((box.y1 - T.y0) / T.cell));
    return i0 > i1 || j0 > j1 ? null : { i0, i1, j0, j1 };
  }
  const growBox = (b, x0, y0, x1, y1) => b ? { x0: Math.min(b.x0, x0), y0: Math.min(b.y0, y0), x1: Math.max(b.x1, x1), y1: Math.max(b.y1, y1) } : { x0, y0, x1, y1 };
  // faces par matiere (la plus presente aux 4 coins, comme la generation ; egalite : la plus petite peinture, comme
  // track_creator.build), refaites seulement si la peinture ou le theme ont change. Sauts : seule la route s'arrete, le
  // sol reste -> aucune case retiree
  const terrainMats = new Map();
  let terrainFaces = { paint: null, sig: '' };
  // bruit carrele uniforme entre 0 et 1, des fondus entre peintures (track_creator._mix_noise, dessin proche)
  let mixNoise = null;
  function getMixNoise() {
    if (mixNoise) return mixNoise;
    const N = 512, f = new Float32Array(N * N);
    for (const [g, amp] of [[6, 1], [12, 0.6], [24, 0.35], [48, 0.2]]) {
      const r = new Float32Array(g * g), rnd = (s => () => (s = (s * 16807) % 2147483647) / 2147483647)(7 + g);
      for (let k = 0; k < g * g; k++) r[k] = rnd();
      for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
        const fx = x / N * g, fy = y / N * g, x0 = fx | 0, y0 = fy | 0, x1 = (x0 + 1) % g, y1 = (y0 + 1) % g;
        const u = fx - x0, v = fy - y0, a = u * u * (3 - 2 * u), b = v * v * (3 - 2 * v);
        f[y * N + x] += amp * ((r[y0 * g + x0] * (1 - a) + r[y0 * g + x1] * a) * (1 - b) + (r[y1 * g + x0] * (1 - a) + r[y1 * g + x1] * a) * b);
      }
    }
    const order = Uint32Array.from(f.keys()).sort((p, q) => f[p] - f[q]);
    mixNoise = new Float32Array(N * N);
    order.forEach((id, k) => { mixNoise[id] = k / (N * N - 1); });
    return mixNoise;
  }
  // texture d'un fondu : composee une fois les 2 images chargees (la 1re s'affiche en attendant)
  const mixTex = new Map();
  function mixMaterial(key, A, B, level) {
    const mat = new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.DoubleSide, map: kitTexture(A.png, A.kit) });
    const url = m => `/api/creator_texture?kit=${m.kit}&f=${m.png}`;
    const img = m => new Promise((ok, ko) => { const e = new Image(); e.onload = () => ok(e); e.onerror = ko; e.src = url(m); });
    (mixTex.get(key) || mixTex.set(key, Promise.all([img(A), img(B)]).then(([a, b]) => {
      const N = 512, cv = document.createElement('canvas'); cv.width = cv.height = N;
      const g = cv.getContext('2d', { willReadFrequently: true });
      g.drawImage(a, 0, 0, N, N); const da = g.getImageData(0, 0, N, N);
      g.drawImage(b, 0, 0, N, N); const db = g.getImageData(0, 0, N, N).data, d = da.data, noise = getMixNoise(), w = level / 4;
      for (let v = 0; v < N * N; v++) {
        const k = Math.max(0, Math.min(1, (w - noise[v]) / 0.8 + 0.5));
        for (let c = 0; c < 3; c++) d[v * 4 + c] += (db[v * 4 + c] - d[v * 4 + c]) * k;
      }
      g.putImageData(da, 0, 0);
      const t = new THREE.CanvasTexture(cv);
      t.colorSpace = THREE.SRGBColorSpace; t.wrapS = t.wrapT = THREE.RepeatWrapping; t.anisotropy = 8;
      return t;
    })).get(key)).then(t => { mat.map = t; mat.needsUpdate = true; }, () => {});
    return mat;
  }
  function refreshTerrainFaces() {
    const T = S.terrain, n = T.n, cells = (n - 1) * (n - 1), last = MATERIALS.length + EXTRA_MATS.length - 1;
    const sigOne = m => { const mt = matOf(m); return `${m}|${mt.png || ''}|${mt.kit || ''}|${mt.color || ''}`; };
    const sigOf = (c, mx) => c <= last ? sigOne(c) : `mix|${sigOne(mx[c - last - 1][0])}|${sigOne(mx[c - last - 1][1])}|${mx[c - last - 1][2]}`;
    const old = terrainFaces, tp = T.paint, fade = S.fade ?? FADE_DEF, hid = clay.hiddenMask(), hv = clay.regionVersion;
    if (old.paint?.length === tp.length && old.last === last && old.fade === fade && old.hv === hv && old.used.map(c => c <= last ? sigOne(c) : sigOf(c, old.mixes)).join() === old.sig && terrainGeo.index?.count === cells * 6) {
      let same = true;
      for (let v = 0; v < tp.length; v++) if (tp[v] !== old.paint[v]) { same = false; break; }
      if (same) return;
    }
    const best = new Uint16Array(cells), P4 = [0, 0, 0, 0];
    let mixes = [];
    if (fade < 2) {
      for (let j = 0, q = 0; j < n - 1; j++) for (let i = 0; i < n - 1; i++, q++) {
        const a = j * n + i;
        P4[0] = tp[a]; P4[1] = tp[a + 1]; P4[2] = tp[a + n + 1]; P4[3] = tp[a + n];
        let b = 0, bc = 0;
        for (let u = 0; u < 4; u++) {
          const m = P4[u] < last ? P4[u] : last;
          let k = 0; for (let w = 0; w <= u; w++) if ((P4[w] < last ? P4[w] : last) === m) k++;
          if (k > bc || (k === bc && m < b)) { bc = k; b = m; }
        }
        best[q] = b;
      }
    } else {
      // meme calcul que track_creator._cell_materials : les 2 peintures les plus presentes de la fenetre -> 25, 50 ou 75 %
      const r = (fade - 2) >> 1, hist = new Uint32Array(last + 1), tally = new Map(), seen = [];
      for (let j = 0, q = 0; j < n - 1; j++) {
        const j0 = Math.max(0, j - r), j1 = Math.min(n - 1, j + 1 + r);
        for (let i = 0; i < n - 1; i++, q++) {
          const i0 = Math.max(0, i - r), i1 = Math.min(n - 1, i + 1 + r);
          const m0 = Math.min(tp[j0 * n + i0], last);
          let uni = true;
          for (let y = j0; y <= j1 && uni; y++) for (let v = y * n + i0, e = y * n + i1; v <= e; v++) if (Math.min(tp[v], last) !== m0) { uni = false; break; }
          if (uni) { best[q] = m0; continue; }
          seen.length = 0;
          for (let y = j0; y <= j1; y++) for (let v = y * n + i0, e = y * n + i1; v <= e; v++) { const m = Math.min(tp[v], last); if (!hist[m]++) seen.push(m); }
          let p = -1, q2 = -1;
          for (const m of seen) {
            if (p < 0 || hist[m] > hist[p] || (hist[m] === hist[p] && m < p)) { q2 = p; p = m; }
            else if (q2 < 0 || hist[m] > hist[q2] || (hist[m] === hist[q2] && m < q2)) q2 = m;
          }
          const level = Math.floor(hist[q2] / (hist[p] + hist[q2]) * 4 + 0.5);
          for (const m of seen) hist[m] = 0;
          if (!level) { best[q] = p; continue; }
          const key = p < q2 ? [p, q2, level] : [q2, p, 4 - level], ks = key.join();
          (tally.get(ks) || tally.set(ks, { key, cells: [] }).get(ks)).cells.push(q);
        }
      }
      const sorted = [...tally.values()].sort((a, b) => b.cells.length - a.cells.length
        || a.key[0] - b.key[0] || a.key[1] - b.key[1] || a.key[2] - b.key[2]);
      sorted.forEach((t, k) => {
        const code = k < MIX_MAX ? last + 1 + k : t.key[2] > 2 ? t.key[1] : t.key[0];
        if (k < MIX_MAX) mixes.push(t.key);
        for (const c of t.cells) best[c] = code;
      });
    }
    const total = last + 1 + mixes.length, count = new Uint32Array(total);
    for (let q = 0; q < cells; q++) count[best[q]]++;
    const used = [], start = new Uint32Array(total);
    for (let m = 0, o = 0; m < total; m++) if (count[m]) { used.push(m); start[m] = o; o += count[m] * 6; }
    // meme tampon d'une fois sur l'autre (un nouveau a chaque calcul : 2 Mo de plus pour la carte graphique, 8 fois par seconde)
    let idx = terrainGeo.index;
    if (idx?.count !== cells * 6) { idx = new THREE.BufferAttribute(new Uint32Array(cells * 6), 1); terrainGeo.setIndex(idx); }
    const ix = idx.array, w = start.slice();
    for (let j = 0, q = 0; j < n - 1; j++) for (let i = 0; i < n - 1; i++, q++) {
      if (hid && hid[q]) continue;                            // case de la zone de pate : dessinee par la pate
      const a = j * n + i, b = a + 1, c = a + n + 1, d = a + n; let o = w[best[q]];
      ix[o++] = a; ix[o++] = b; ix[o++] = c; ix[o++] = a; ix[o++] = c; ix[o++] = d; w[best[q]] = o;
    }
    idx.needsUpdate = true;
    terrainGeo.clearGroups();
    used.forEach((m, g) => terrainGeo.addGroup(start[m], w[m] - start[m], g));
    terrainMesh.material = used.map(m => { const key = sigOf(m, mixes), mix = m > last ? mixes[m - last - 1] : null, mt = matOf(mix ? mix[0] : m), mb = mix && matOf(mix[1]);
      if (!terrainMats.has(key)) terrainMats.set(key, mix && mt.png && mb.png ? mixMaterial(key, mt, mb, mix[2]) : new THREE.MeshBasicMaterial({ vertexColors: true,
        side: THREE.DoubleSide,
        ...(mt.png ? { map: kitTexture(mt.png, mt.kit) } : { color: new THREE.Color(...mt.color) }) }));
      return terrainMats.get(key); });
    terrainFaces = { paint: tp.slice(), last, used, mixes, fade, hv, sig: used.map(c => sigOf(c, mixes)).join(),
                     best, mats: new Map(used.map((m, g) => [m, terrainMesh.material[g]])) };
  }
  // ---- ponts de terre / tunnels (relief garde au-dessus de la route) : SUPPRIMES le 2026-11-16 a la demande de
  // l'utilisateur (track_creator idem). Restent ces deux appels vides pour l'apercu et le semis d'objets ----
  function roofMask() { return null; }
  const inRoof = () => false;
  function refreshRoof() { S.roof = null; roofMesh.visible = false; }
  // box : zone modifiee (monde), le reste du maillage ne bouge pas ; sans box : tout le terrain
  function refreshTerrainMesh(box = null) {
    clearSeats(box);                                          // objets de la zone : a reposer sur le sol
    const T = S.terrain, n = T.n, N = n * n, cell = T.cell;
    let rg = box && S.shown?.length === N && terrainGeo.attributes.position?.count === N ? gridRange(box) : null;
    if (box && !rg && S.shown?.length === N && terrainGeo.attributes.position?.count === N) { refreshTerrainFaces(); return; }   // hors du terrain
    conform(rg);
    S.shown.set(S.raw);
    const mods = new Set();
    if (rg) for (const v of [...mods, ...(S.mods || [])]) {   // modifie hors de la zone recalculee : tout renvoyer
      const i = v % n, j = (v - i) / n;
      if (i < rg.i0 || i > rg.i1 || j < rg.j0 || j > rg.j1) { rg = null; break; }
    }
    S.mods = mods;
    const fresh = !terrainGeo.attributes.position || terrainGeo.attributes.position.count !== N;
    if (fresh) {                                              // nouvelle taille
      terrainGeo.dispose(); terrainGeo = new THREE.BufferGeometry(); terrainMesh.geometry = terrainGeo;
      terrainGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(N * 3), 3));
      terrainGeo.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(N * 2), 2));
      terrainGeo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(N * 3), 3));
    }
    const pos = terrainGeo.attributes.position, uv = terrainGeo.attributes.uv, col = terrainGeo.attributes.color;
    const P = pos.array, C = col.array, H = S.shown, rep = (S.kitInfo?.ground_repeat || 12) * IN;
    // x, y et uv : seulement si la grille ou la repetition de la texture ont change
    const gridKey = `${T.x0}|${T.y0}|${cell}|${n}|${rep}`;
    if (fresh || terrainGeo.userData.gridKey !== gridKey) {
      const U = uv.array;
      for (let j = 0, v = 0; j < n; j++) for (let i = 0; i < n; i++, v++) {
        const x = T.x0 + i * cell, y = T.y0 + j * cell;
        P[v * 3] = x; P[v * 3 + 1] = y; U[v * 2] = x / rep; U[v * 2 + 1] = y / rep;
      }
      uv.needsUpdate = true; terrainGeo.userData.gridKey = gridKey; rg = null;
    }
    const R = rg || { i0: 0, i1: n - 1, j0: 0, j1: n - 1 };
    // conform peut aussi abaisser une maille autour de la zone (clearRoad) ; ombrage : un sommet de plus, ses voisins comptent
    const zi0 = Math.max(0, R.i0 - 1), zi1 = Math.min(n - 1, R.i1 + 1), zj0 = Math.max(0, R.j0 - 1), zj1 = Math.min(n - 1, R.j1 + 1);
    const si0 = Math.max(0, R.i0 - 2), si1 = Math.min(n - 1, R.i1 + 2), sj0 = Math.max(0, R.j0 - 2), sj1 = Math.min(n - 1, R.j1 + 2);
    for (let j = zj0; j <= zj1; j++) for (let i = zi0, v = j * n + zi0; i <= zi1; i++, v++) P[v * 3 + 2] = H[v] - 2;
    // ombrage fixe (soleil en biais) dans la couleur des sommets, multipliee par la texture ; normale d'apres les voisins
    const Lx = 0.45, Ly = -0.35, Lz = 0.82, in2 = 1 / (2 * cell);
    for (let j = sj0; j <= sj1; j++) for (let i = si0, v = j * n + si0; i <= si1; i++, v++) {
      const a = i > 0 ? v - 1 : v, b = i < n - 1 ? v + 1 : v, c = j > 0 ? v - n : v, d = j < n - 1 ? v + n : v;
      const nx = -(H[b] - H[a]) * (i > 0 && i < n - 1 ? in2 : 2 * in2), ny = -(H[d] - H[c]) * (j > 0 && j < n - 1 ? in2 : 2 * in2);
      const dot = (nx * Lx + ny * Ly + Lz) / Math.sqrt(nx * nx + ny * ny + 1);
      const s = Math.min(1, 0.55 + 0.5 * (dot > 0 ? dot : 0));
      C[v * 3] = C[v * 3 + 1] = C[v * 3 + 2] = s;
    }
    pos.clearUpdateRanges(); col.clearUpdateRanges();
    if (rg) {                                                 // envoi a la carte graphique : les lignes touchees seulement
      pos.addUpdateRange(zj0 * n * 3, (zj1 - zj0 + 1) * n * 3);
      col.addUpdateRange(sj0 * n * 3, (sj1 - sj0 + 1) * n * 3);
    }
    pos.needsUpdate = col.needsUpdate = true;
    refreshTerrainFaces();
    clay.refresh(box);
    refreshRoof();
    scheduleWater();                                          // eau des trous : niveau et forme d'apres le nouveau sol
    // boite englobante d'apres les hauteurs extremes, sans reparcourir les sommets
    const e = (n - 1) * cell, bb = terrainGeo.boundingBox ||= new THREE.Box3(), bs = terrainGeo.boundingSphere ||= new THREE.Sphere();
    bb.min.set(T.x0, T.y0, S.shownLow - 2); bb.max.set(T.x0 + e, T.y0 + e, S.shownHigh - 2);
    bb.getCenter(bs.center); bs.radius = bb.min.distanceTo(bb.max) / 2;
  }
  // ---- eau (2026-11-12) : outil du Relief « Remplir d'eau ». Un clic dans un creux le remplit jusqu'a son bord le plus
  // bas (la ou l'eau deborderait), + un decalage reglable (dz, pouces ; par defaut 30 cm sous le bord). S.waters =
  // [{x, y, dz}] : seul le point clique est garde, forme et niveau recalcules d'apres le sol (track_creator.water_basins
  // idem a la generation). Moins de WATER_DEEP d'eau : on roule au fond ; plus : zone de chute (reapparition) ----
  // WATER_DZ : nouvelle eau sous le bord (5 m, reglable jusqu'a 20 m ; 30 cm puis 1 m avant, le 2026-11-12 ;
  // track_creator.WATER_DZ idem). Trou moins profond : eau a mi-profondeur (newWaterAt)
  const WATER_DEEP = 1.5 * IN, WATER_DZ = -5.0 * IN;
  // types d'eau (couleur ; track_creator.WATER_TYPES, meme ordre et memes couleurs)
  const WATER_TYPES = { clear: ['Eau claire', 0x2f7fd0], lagoon: ['Lagon', 0x22b5b5], swamp: ['Marais', 0x55702f],
                        dark: ['Eau sombre', 0x1d3a58], mud: ['Boue', 0x6b5034] };
  const waterType = w => WATER_TYPES[w?.type] ? w.type : 'clear';
  // eau peinte au pinceau (S.waters : {paint: 1, base, level, v: [sommets], type}) : sous l'eau = sommets peints dont
  // le sol est sous le niveau (le relief plus haut fait la rive)
  function paintBasin(w) {
    const T = S.terrain, H = S.shown; if (!T || !H || H.length !== T.n ** 2) return null;
    const region = new Uint8Array(T.n ** 2), L = w.level;
    let count = 0, deep = 0, bottom = Infinity;
    for (const v of w._set || w.v || []) if (v >= 0 && v < H.length && H[v] < L) {
      region[v] = 1; count++; bottom = Math.min(bottom, H[v]); if (L - H[v] > WATER_DEEP) deep++;
    }
    return { level: L, spill: L, region, count, deep, bottom, paint: true };
  }
  function scheduleWater() { clearTimeout(S.waterTimer); S.waterTimer = setTimeout(() => renderWater(), 250); }
  // tas binaire minimal (hauteur, sommet)
  function minHeap() {
    const h = [], k = [];
    const up = i => { while (i > 0) { const p = (i - 1) >> 1; if (h[p] <= h[i]) break; [h[p], h[i]] = [h[i], h[p]]; [k[p], k[i]] = [k[i], k[p]]; i = p; } };
    const down = i => { for (;;) { const l = 2 * i + 1, r = l + 1; let m = i;
      if (l < h.length && h[l] < h[m]) m = l; if (r < h.length && h[r] < h[m]) m = r;
      if (m === i) return; [h[m], h[i]] = [h[i], h[m]]; [k[m], k[i]] = [k[i], k[m]]; i = m; } };
    return { get size() { return h.length; },
      push(p, v) { h.push(p); k.push(v); up(h.length - 1); },
      pop() { const p = h[0], v = k[0], lp = h.pop(), lv = k.pop(); if (h.length) { h[0] = lp; k[0] = lv; down(0); } return [p, v]; } };
  }
  // bassin d'un point d'eau sur le sol affiche : {level, spill, region (sommets), count, deep, bottom, seed} ou null
  function waterBasin(w) {
    if (w.paint) return paintBasin(w);
    const T = S.terrain, H = S.shown; if (!T || !H || H.length !== T.n ** 2) return null;
    const n = T.n;
    let i = Math.round((w.x - T.x0) / T.cell), j = Math.round((w.y - T.y0) / T.cell);
    if (i < 1 || j < 1 || i >= n - 1 || j >= n - 1) return null;
    let seed = j * n + i;
    for (let guard = 0; guard < 4 * n; guard++) {           // point clique sur la pente du creux : on descend au fond
      let best = seed;
      for (const u of [seed - 1, seed + 1, seed - n, seed + n]) if (H[u] < H[best]) best = u;
      if (best === seed) break;
      seed = best; const bi = seed % n, bj = (seed - bi) / n;
      if (bi < 1 || bj < 1 || bi >= n - 1 || bj >= n - 1) return null;
    }
    // inondation par le bas (2026-11-12 : jusqu'au VRAI bord) : l'eau monte et remplit aussi les petits creux de la pente
    // (avant : arret au premier petit creux, eau au fond d'un grand trou) ; elle deborde la ou elle atteint le bord du
    // terrain ou la route posee au sol. Niveau = point le plus bas du bord (track_creator.water_basin idem)
    const seen = new Uint8Array(n * n), heap = minHeap();
    let level = H[seed], spill = null;
    heap.push(H[seed], seed); seen[seed] = 1;
    while (heap.size) {
      const [h, v] = heap.pop();
      if (h > level) level = h;
      const vi = v % n, vj = (v - vi) / n;
      if (vi === 0 || vj === 0 || vi === n - 1 || vj === n - 1) { spill = level; break; }
      const rz = roadUnder({ x: T.x0 + vi * T.cell, y: T.y0 + vj * T.cell });
      if (rz !== null && rz < h + 2 * IN) { spill = level; break; }      // route au sol (pas un pont au-dessus)
      for (const u of [v - 1, v + 1, v - n, v + n]) if (!seen[u]) { seen[u] = 1; heap.push(H[u], u); }
    }
    spill ??= level;
    const L = spill + (w.dz ?? WATER_DZ), region = new Uint8Array(n * n);
    let count = 0, deep = 0, bottom = Infinity;
    if (H[seed] < L) {
      const st = [seed]; region[seed] = 1;
      while (st.length) {
        const v = st.pop(); count++; bottom = Math.min(bottom, H[v]); if (L - H[v] > WATER_DEEP) deep++;
        const vi = v % n, vj = (v - vi) / n;
        for (const [u, ok] of [[v - 1, vi > 0], [v + 1, vi < n - 1], [v - n, vj > 0], [v + n, vj < n - 1]])
          if (ok && !region[u] && H[u] < L) { region[u] = 1; st.push(u); }
      }
    }
    return { level: L, spill, region, count, deep, bottom, seed };
  }
  // sommets deja sous une eau (sauf l'eau skip) : pas d'eau sur de l'eau (2026-11-12)
  function waterOccupied(skip) {
    const T = S.terrain, occ = new Uint8Array(T.n ** 2);
    for (const w of S.waters) if (w !== skip) { const b = waterBasin(w); if (b) for (let v = 0; v < occ.length; v++) if (b.region[v]) occ[v] = 1; }
    return occ;
  }
  // route dans l'eau (passage sous le niveau) : nombre de points
  function roadInWater(b) {
    const T = S.terrain, n = T.n; let k = 0;
    for (const q of effPoints()) {
      const i = Math.round((q[0] - T.x0) / T.cell), j = Math.round((q[1] - T.y0) / T.cell);
      if (i >= 0 && j >= 0 && i < n && j < n && b.region[j * n + i] && q[2] < b.level) k++;
    }
    return k;
  }
  function renderWater() {
    S.waterGroup ??= (() => { const g = new THREE.Group(); group.add(g); return g; })();
    S.waterMats ??= {};
    const wmat = (type, sel) => S.waterMats[type + (sel ? '+' : '')] ??= (() => {
      const c = new THREE.Color(WATER_TYPES[type][1]); if (sel) c.lerp(new THREE.Color(0xffffff), 0.35);
      // opaque (2026-11-12) comme en jeu (image d'eau sans transparence) : le sol peint dessous ne teinte plus l'eau
      return new THREE.MeshLambertMaterial({ color: c, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1 });
    })();
    const wg = S.waterGroup;
    S.waterHoverCache = null;                                // creux libres / occupes a recalculer
    for (const m of wg.children) m.geometry.dispose();
    wg.clear();
    S.waterInfo = [];
    const T = S.terrain; if (!T) return;
    const n = T.n, cell = T.cell;
    S.waters.forEach((w, k) => {
      const b = waterBasin(w);
      S.waterInfo.push(b && b.count ? { level: b.level, spill: b.spill, count: b.count, deep: b.deep, depth: b.level - b.bottom,
                                        road: roadInWater(b), area: b.count * (cell / IN) ** 2 } : null);
      if (!b || !b.count) return;
      // cases dont un coin est sous l'eau : surface plane au niveau (le relief plus haut la cache sur la rive)
      const pos = [];
      for (let j = 0; j < n - 1; j++) for (let i = 0; i < n - 1; i++) {
        const v = j * n + i, R = b.region, q = [R[v], R[v + 1], R[v + n + 1], R[v + n]], k4 = q[0] + q[1] + q[2] + q[3];
        if (!k4) continue;
        const x0 = T.x0 + i * cell, y0 = T.y0 + j * cell, x1 = x0 + cell, y1 = y0 + cell, z = b.level - 2;
        const C = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
        // eau peinte : bord en biais (case a 3 coins = triangle, moins de 3 : rien) ; trou : case entiere (la rive cache le bord)
        if (!w.paint || k4 === 4) pos.push(x0, y0, z, x1, y0, z, x1, y1, z, x0, y0, z, x1, y1, z, x0, y1, z);
        else if (k4 === 3) for (let c = 0; c < 4; c++) if (q[c]) pos.push(C[c][0], C[c][1], z);
      }
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); g.computeVertexNormals();
      const m = new THREE.Mesh(g, wmat(waterType(w), k === S.waterSel));
      m.renderOrder = 5; wg.add(m);
    });
    renderWaterList();
  }
  function renderWaterList() {
    const box = $('crwlist'); if (!box) return;
    const f1 = v => (v / IN).toFixed(1).replace('.', ',');
    box.innerHTML = S.waters.length ? S.waters.map((w, k) => {
      const inf = S.waterInfo?.[k];
      const txt = (w.paint ? '🖌 ' : '') + WATER_TYPES[waterType(w)][0] + ' · ' + (!inf ? '<span style="color:var(--err)">' + (w.paint ? 'aucune zone peinte sous le niveau' : 'pas de creux ici (le niveau est sous le sol)') + '</span>'
        : `${Math.round(inf.area)} m², ${f1(inf.depth)} m au plus profond · ${inf.deep ? '<b>profond</b> : on tombe' : 'peu profond : on roule au fond'}`
          + (inf.road ? ' · <span style="color:var(--err)">⚠ la route passe dans l\'eau</span>' : ''));
      return `<div data-w="${k}" style="display:flex;gap:4px;align-items:center;padding:3px 4px;border-radius:4px;cursor:pointer;${k === S.waterSel ? 'background:#56b8ff22' : ''}">
        <span style="flex:1;font-size:12px">💧 ${k + 1} · ${txt}</span><button data-wdel="${k}" title="Retirer cette eau">🗑</button></div>`;
    }).join('') : '<div class="note" style="font-size:12px">Aucune eau. Clique au fond d\'un trou creusé pour le remplir.</div>';
    box.querySelectorAll('[data-w]').forEach(r => r.onclick = e => {
      if (e.target.dataset.wdel != null) { S.waters.splice(+e.target.dataset.wdel, 1); S.waterSel = -1; renderWater(); syncWaterLevel(); saveDraft(); return; }
      S.waterSel = +r.dataset.w; renderWater(); syncWaterLevel();
    });
  }
  function syncWaterLevel() {
    const w = S.waters[S.waterSel];
    $('crwlevelrow').style.display = w && !w.paint ? 'block' : 'none';
    $('crwplevelrow').style.display = w?.paint ? 'block' : 'none';
    if (w && !w.paint) { $('crwlevel').value = ((w.dz ?? WATER_DZ) / IN).toFixed(1); $('crwlv').textContent = (-(w.dz ?? WATER_DZ) / IN).toFixed(1).replace('.', ','); }
    if (w?.paint) { const h = (w.level - w.base) / IN; $('crwplevel').value = h.toFixed(1); $('crwplv').textContent = h.toFixed(1).replace('.', ','); }
    $('crwtype').value = w ? waterType(w) : (S.waterType || 'clear');
  }
  // mode de l'outil Eau : fill (remplir un trou, clic), paint / erase (pinceau)
  function setWaterMode(m) {
    m = 'fill';                                             // Peindre / Effacer retires (2026-11-12, demande utilisateur)
    S.waterMode = m;
    panel.querySelectorAll('[data-wm]').forEach(b => b.classList.toggle('primary', b.dataset.wm === m));
    $('crwhrow').style.display = m === 'paint' ? 'block' : 'none';
    $('crwhelp').textContent = m === 'fill' ? 'Clique au fond d\'un trou creusé : il se remplit jusqu\'à un peu sous son bord.'
      : m === 'paint' ? 'Peins le lac ou la rivière au pinceau. Le niveau est pris au début du trait (sol cliqué + hauteur ci-dessous) ; là où le sol est plus haut, c\'est la rive. Repeindre depuis une eau peinte sélectionnée l\'agrandit.'
      : 'Passe le pinceau sur de l\'eau peinte pour l\'effacer.';
    if (S.mode === 'terrain' && S.tool === 'water') $('crbrush').hidden = m === 'fill';
  }
  // pinceau de l'eau : debut du trait (eau peinte a agrandir ou nouvelle, au niveau du sol clique + hauteur)
  function waterStrokeStart(p) {
    if (S.waterMode !== 'paint') return;
    const T = S.terrain, i = Math.round((p.x - T.x0) / T.cell), j = Math.round((p.y - T.y0) / T.cell), v = j * T.n + i;
    // trait commence dans une eau peinte : elle s'agrandit (meme niveau) ; sinon nouvelle eau
    let w = S.waters.find(x => x.paint && (x.v.includes(v) || waterBasin(x)?.region[v]));
    if (w) S.waterSel = S.waters.indexOf(w);
    else if (waterOccupied(null)[v]) { status('Il y a déjà de l\'eau ici : sélectionne-la pour changer son niveau ou son type', 'err'); S.waterBlock = null; return; }
    else {
      const base = Math.round(p.z);
      w = { paint: 1, base, level: base + Math.round((+$('crwh').value) * IN), v: [], type: S.waterType || 'clear' };
      S.waters.push(w); S.waterSel = S.waters.length - 1;
    }
    w._set = new Set(w.v);
    S.waterBlock = waterOccupied(w);                        // le pinceau ne peint pas sur les autres eaux
    syncWaterLevel();
  }
  function waterBrush(p) {
    const T = S.terrain, n = T.n, c = T.cell, r = S.radius;
    const ci = (p.x - T.x0) / c, cj = (p.y - T.y0) / c, rc = r / c;
    const i0 = Math.max(0, Math.floor(ci - rc)), i1 = Math.min(n - 1, Math.ceil(ci + rc));
    const j0 = Math.max(0, Math.floor(cj - rc)), j1 = Math.min(n - 1, Math.ceil(cj + rc));
    const w = S.waters[S.waterSel];
    for (let j = j0; j <= j1; j++) for (let i = i0; i <= i1; i++) {
      if (Math.hypot(i - ci, j - cj) / rc >= 1) continue;
      const v = j * n + i;
      if (S.waterMode === 'paint' && w?._set) { if (!S.waterBlock?.[v]) w._set.add(v); }
      else if (S.waterMode === 'erase') for (const x of S.waters) if (x.paint) { x._set ??= new Set(x.v); x._set.delete(v); }
    }
    const now = performance.now();
    if (!S.waterDrawAt || now - S.waterDrawAt > 120) { S.waterDrawAt = now; renderWater(); }
  }
  function waterStrokeEnd() {
    S.waterBlock = null;
    for (const w of S.waters) if (w._set) { w.v = [...w._set].sort((a, b) => a - b); delete w._set; }
    const before = S.waters.length;
    S.waters = S.waters.filter(w => !w.paint || w.v.length);
    if (S.waters.length !== before) S.waterSel = -1;
    const gone = dropPropsInWater(p => !p.ai);                // decor automatique dans l'eau peinte : retire
    if (gone) { renderProps(); status(`${gone} objet(s) du décor automatique retiré(s) de l'eau`, 'ok'); }
    renderWater(); syncWaterLevel(); saveDraft();
  }
  // nouvelle eau au point p : WATER_DZ sous le bord ; trou moins profond que ca : eau a mi-profondeur.
  // -> {w, b, taken (indice d'une eau deja dans ce creux, sinon -1)} ou null (pas de creux)
  function newWaterAt(p) {
    const w = { x: Math.round(p.x), y: Math.round(p.y), dz: WATER_DZ, type: S.waterType || 'clear' };
    let b = waterBasin(w);
    if (!b || !b.count) {
      const b0 = waterBasin({ ...w, dz: 0 });
      if (!b0 || !b0.count || b0.spill - b0.bottom < 0.4 * IN) return null;
      w.dz = -Math.round((b0.spill - b0.bottom) / 2 / IN * 10) / 10 * IN;
      b = waterBasin(w); if (!b || !b.count) return null;
    }
    let taken = -1;
    for (let k = 0; k < S.waters.length && taken < 0; k++) {
      const o = waterBasin(S.waters[k]);
      if (o && o.region.some((r, v) => r && b.region[v])) taken = k;
    }
    return { w, b, taken };
  }
  // survol avec l'outil Eau : curseur goutte sur un creux ou l'on peut mettre de l'eau (resultat garde par fond du creux)
  const DROP_CURSOR = `url("data:image/svg+xml,${encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><path d="M12 2C12 2 5 10.5 5 15a7 7 0 0 0 14 0C19 10.5 12 2 12 2z" fill="#3a9be8" stroke="#fff" stroke-width="1.6"/><ellipse cx="9.5" cy="15" rx="1.6" ry="2.6" fill="#fff" opacity=".7"/></svg>')}") 12 22, pointer`;
  function waterHover(e) {
    const now = performance.now();
    if (S.waterHoverAt && now - S.waterHoverAt < 90) return;
    S.waterHoverAt = now;
    const p = pick(e), T = S.terrain, H = S.shown;
    let ok = false;
    if (p && T && H) {
      const n = T.n; let i = Math.round((p.x - T.x0) / T.cell), j = Math.round((p.y - T.y0) / T.cell);
      if (i >= 1 && j >= 1 && i < n - 1 && j < n - 1) {
        let seed = j * n + i;
        for (let g = 0; g < 4 * n; g++) {                    // meme descente que waterBasin : fond du creux
          let best = seed; for (const u of [seed - 1, seed + 1, seed - n, seed + n]) if (H[u] < H[best]) best = u;
          if (best === seed) break; seed = best;
        }
        S.waterHoverCache ??= new Map();
        if (!S.waterHoverCache.has(seed)) { const r = newWaterAt(p); S.waterHoverCache.set(seed, !!r && r.taken < 0); }
        ok = S.waterHoverCache.get(seed);
      }
    }
    canvas.style.cursor = ok ? DROP_CURSOR : '';
    S.waterCursor = ok;
  }
  function waterPointerDown(e) {
    const p = pick(e); if (!p) return;
    e.preventDefault(); e.stopImmediatePropagation();
    // clic dans une eau existante : la selectionne
    const T = S.terrain, n = T.n, i = Math.round((p.x - T.x0) / T.cell), j = Math.round((p.y - T.y0) / T.cell);
    for (let k = 0; k < S.waters.length; k++) {
      const b = waterBasin(S.waters[k]);
      if (b?.region[j * n + i]) { S.waterSel = k; renderWater(); syncWaterLevel(); status(`Eau ${k + 1} sélectionnée : règle son niveau ou retire-la`); return; }
    }
    const r = newWaterAt(p);
    if (!r) { status('Pas de creux ici : clique au fond d\'un trou creusé (outil ⬇ Creuser)', 'err'); return; }
    // le creux touche une eau existante (meme trou clique sur sa pente, ou lac peint dedans) : pas de 2e eau
    if (r.taken >= 0) {
      S.waterSel = r.taken; renderWater(); syncWaterLevel();
      status(`Il y a déjà de l'eau dans ce creux (eau ${r.taken + 1}, sélectionnée) : règle son niveau ou retire-la`, 'err'); return;
    }
    const w = r.w;
    S.waters.push(w); S.waterSel = S.waters.length - 1;
    // objets du decor automatique qui se retrouvent dans cette eau : retires (ceux poses a la main restent)
    const gone = dropPropsInWater(p => !p.ai);
    if (gone) renderProps();
    renderWater(); syncWaterLevel(); saveDraft();
    const inf = S.waterInfo[S.waterSel];
    status((gone ? `${gone} objet(s) du décor automatique retiré(s) de l'eau · ` : '') +
           `Trou rempli : ${Math.round(inf.area)} m², ${(inf.depth / IN).toFixed(1).replace('.', ',')} m au plus profond` +
           (inf.deep ? ' (profond : on y tombe, réapparition sur la route)' : ' (peu profond : on roule au fond)') +
           (inf.road ? ' — ⚠ la route passe dans l\'eau : baisse le niveau' : ''), inf.road ? 'err' : 'ok');
  }
  // nouvelle taille du carre de base : relief et peinture reechantillonnes (centre garde)
  function resizeTerrain(size) {
    // centre garde : le kart peut etre ailleurs qu'au milieu du terrain
    const old = S.terrain, T = newTerrain(old ? { pos: [old.x0 + (old.n - 1) * old.cell / 2, old.y0 + (old.n - 1) * old.cell / 2] } : S.start, size);
    if (old) for (let j = 0; j < T.n; j++) for (let i = 0; i < T.n; i++) {
      const x = T.x0 + i * T.cell, y = T.y0 + j * T.cell, v = j * T.n + i;
      const fi = Math.round((x - old.x0) / old.cell), fj = Math.round((y - old.y0) / old.cell);
      if (fi < 0 || fj < 0 || fi >= old.n || fj >= old.n) continue;
      S.terrain = old; T.h[v] = sample(old.h, x, y); T.paint[v] = old.paint[fj * old.n + fi]; T.dig[v] = old.dig?.[fj * old.n + fi] || 0;
      if (old.aih) (T.aih ??= new Float32Array(T.n * T.n))[v] = sample(old.aih, x, y);
    }
    S.terrain = T;
  }  function applyBrush(dt) {
    const T = S.terrain, p = S.mouse; if (!T || !p || S.grab) return;   // Etirer : gere a la souris (clay.stretch)
    if (S.vol) {                                              // Monter / Creuser / Aplanir / Lisser sur de la matiere en volume
      const sp = S.brushSpeed || 1;
      const amt = S.tool === 'raise' || S.tool === 'lower' ? 8 * IN * S.strength * dt * 2 * sp
        : S.tool === 'smooth' ? dt * 8 * S.strength * sp : dt * 6 * S.strength * sp;
      const bx = clay.sculpt(S.tool, S.vol.p, S.radius, amt, S.vol.plane);
      if (bx) S.vol.box = growBox(S.vol.box, bx.x0, bx.y0, bx.x1, bx.y1);
      return;
    }
    if (S.mode === 'terrain' && S.tool === 'water') { waterBrush(p); return; }   // eau peinte / effacee (relief inchange)
    if (S.mode === 'props') {                                 // semer / effacer des objets
      if (S.propErase) {
        const n = S.props.length; S.props = S.props.filter(q => Math.hypot(q.x - p.x, q.y - p.y) > S.radius);
        S.propsDirty ||= n !== S.props.length; return;
      }
      S.propAcc += dt * (2 + 10 * S.strength);
      while (S.propAcc >= 1) {
        S.propAcc -= 1;
        const a = Math.random() * 2 * Math.PI, r = S.radius * Math.sqrt(Math.random());
        if (tryProp(p.x + r * Math.cos(a), p.y + r * Math.sin(a), pickSel(), true)) S.propsDirty = true;
      }
      return;
    }
    const r = S.radius, ci = (p.x - T.x0) / T.cell, cj = (p.y - T.y0) / T.cell, rc = r / T.cell;
    const i0 = Math.max(0, Math.floor(ci - rc)), i1 = Math.min(T.n - 1, Math.ceil(ci + rc));
    const j0 = Math.max(0, Math.floor(cj - rc)), j1 = Math.min(T.n - 1, Math.ceil(cj + rc));
    const speed = S.brushSpeed || 1, rate = 8 * IN * S.strength * dt * 2 * speed;
    const old = S.tool === 'smooth' ? T.h.slice() : null;
    for (let j = j0; j <= j1; j++) for (let i = i0; i <= i1; i++) {
      const d = Math.hypot(i - ci, j - cj) / rc; if (d >= 1) continue;
      const f = (1 - d * d) ** 2, k = tIndex(i, j);
      if (S.mode === 'paint') { if (f > 0.25) T.paint[k] = S.paint; continue; }
      if (S.tool === 'raise') T.h[k] += rate * f;
      else if (S.tool === 'lower') T.h[k] -= rate * f;
      else if (S.tool === 'dig') { T.h[k] -= rate * f; if (f > 0.05) T.dig[k] = 1; }   // relief garde sous la route
      else if (S.tool === 'fill') { if (f > 0.05) T.dig[k] = 0; continue; }          // de nouveau raccorde a la route
      else if (S.tool === 'flatten') T.h[k] += (S.flatZ - T.h[k]) * Math.min(1, dt * 6 * S.strength * f * speed);
      else if (S.tool === 'smooth' && i > 0 && j > 0 && i < T.n - 1 && j < T.n - 1) {
        const avg = (old[k - 1] + old[k + 1] + old[k - T.n] + old[k + T.n]) / 4;
        T.h[k] += (avg - T.h[k]) * Math.min(1, dt * 8 * S.strength * f * speed);
      }
      T.h[k] = Math.max(T_LO, Math.min(T_HI, T.h[k]));
    }
    S.dirtyT = true; S.dirtyBox = growBox(S.dirtyBox, p.x - r, p.y - r, p.x + r, p.y + r);
    S.strokeBox = growBox(S.strokeBox, p.x - r, p.y - r, p.x + r, p.y + r);
  }
  // point du terrain sous la souris : le rayon avance sur la grille jusqu'a passer sous le sol (le maillage entier :
  // 320 000 triangles testes, 15 ms a chaque mouvement de souris). Vu de dessous : rien, comme les faces du maillage
  const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
  function pick(e) {
    const b = renderer.domElement.getBoundingClientRect();
    ndc.set(((e.clientX - b.left) / b.width) * 2 - 1, -((e.clientY - b.top) / b.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    return pickRay(ray.ray);
  }
  function pickRay(r) {
    const T = S.terrain; if (!T || S.shown?.length !== T.n ** 2) return null;
    // marge en hauteur : sur un sol plat, le rayon doit partir au-dessus du sol, pas exactement dessus (sinon rien n'est touche)
    const o = r.origin, d = r.direction, e = (T.n - 1) * T.cell, lo = [T.x0, T.y0, S.shownLow - 52], hi = [T.x0 + e, T.y0 + e, S.shownHigh + 48];
    let t0 = 0, t1 = Infinity;
    for (const [q, a, c] of [[0, o.x, d.x], [1, o.y, d.y], [2, o.z, d.z]]) {
      if (Math.abs(c) < 1e-9) { if (a < lo[q] || a > hi[q]) return null; continue; }
      const u = (lo[q] - a) / c, v = (hi[q] - a) / c;
      t0 = Math.max(t0, Math.min(u, v)); t1 = Math.min(t1, Math.max(u, v));
    }
    if (t0 > t1) return null;
    const over = t => o.z + d.z * t - (sample(S.shown, o.x + d.x * t, o.y + d.y * t) - 2);
    const hl = Math.hypot(d.x, d.y), dt = hl > 1e-6 ? T.cell / 2 / hl : t1 - t0 || 1;
    let a = t0, fa = over(a);
    for (let t = t0 + dt; ; t += dt) {
      const c = Math.min(t, t1), fc = over(c);
      if (fa > 0 && fc <= 0) {                               // on vient de traverser le sol : point precis par dichotomie
        let x = a, y = c;
        for (let k = 0; k < 14; k++) { const m = (x + y) / 2; if (over(m) > 0) x = m; else y = m; }
        return new THREE.Vector3(o.x + d.x * y, o.y + d.y * y, o.z + d.z * y);
      }
      if (c >= t1) return null;
      a = c; fa = fc;
    }
  }

  const draftKey = () => 'ctr_creator_' + getTrack();
  const GHOST_KEY = 'ctr_creator_ghost';
  const packTerrain = T => T && { x0: T.x0, y0: T.y0, cell: T.cell, n: T.n, h: Array.from(T.h, v => Math.round(v)), paint: Array.from(T.paint),
                                  ...(T.dig?.some(v => v) ? { dig: Array.from(T.dig) } : {}) };
  // relief du decor automatique (pouces, entiers 16 bits en base64) : 2,7 caracteres par sommet, pour le retirer apres reouverture
  const packI16 = a => { const u = new Uint8Array(Int16Array.from(a, v => Math.round(v)).buffer); let s = '';
    for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode.apply(null, u.subarray(i, i + 0x8000)); return btoa(s); };
  const unpackI16 = (b, n) => { const s = atob(b), u = new Uint8Array(s.length); for (let i = 0; i < s.length; i++) u[i] = s.charCodeAt(i);
    return u.length === n * 2 ? Float32Array.from(new Int16Array(u.buffer)) : undefined; };
  const packFull = T => T && { ...packTerrain(T), size: T.size, full: true, blend: S.blendSlope ?? BLEND_DEF, fade: S.fade ?? FADE_DEF,       // carre de base complet genere
                               ...(clay.edited ? { clay: clay.pack() } : {}),
                               ...(T.aih?.some(v => v) ? { aih: packI16(T.aih) } : {}) };
  // brouillon ecrit au plus une fois par seconde (700 Ko a chaque point pose par le paveur), et a la fermeture
  let draftTimer = 0;
  // toute modification : la base n'est plus celle de la derniere generation (point sur « Générer la piste », apercu dans l'Edition)
  const saveDraft = () => { S.genDirty = true; S.editN = (S.editN || 0) + 1; draftTimer ||= setTimeout(writeDraft, 1000); histSchedule(); };
  addEventListener('pagehide', () => { if (draftTimer) writeDraft(); });
  // brouillon trop gros pour le navigateur (piste aleatoire ~2 Mo, plusieurs pistes : ~5 Mo de place) : l'ecriture echouait
  // sans rien dire et la reouverture reprenait l'ancienne base (2026-11-14) -> copie sur le serveur (plus recente : prise
  // a l'ouverture), message une fois
  let serverDraftTimer = 0;
  const writeDraft = () => {
    clearTimeout(draftTimer); draftTimer = 0;
    const d = draftData();
    try { localStorage.setItem(draftKey(), JSON.stringify(d)); return; } catch (e) { /* place du navigateur pleine */ }
    serverDraft(d);
  };
  // copie du brouillon sur le serveur (navigateur plein ; « Vider la map » : suivie par l'historique des pistes)
  const postDraft = (track, d) => fetch('/api/creator_draft', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ track, draft: d }) });
  const serverDraft = d => {
    const track = getTrack();
    clearTimeout(serverDraftTimer);
    serverDraftTimer = setTimeout(() => {
      postDraft(track, d).catch(() => status('⚠ Brouillon de la base non enregistré (navigateur plein, serveur injoignable) : « Enregistrer » avant de fermer', 'err'));
    }, 300);
    if (!S.draftWarned) { S.draftWarned = true; status('Brouillon de la base trop gros pour le navigateur : il est gardé sur le serveur à la place'); }
  };
  const draftData = () => {
    const d = { at: Date.now(), cat: CAT_VERSION, points: S.points, closed: S.closed, ground_z: S.groundZ, start: S.points.length <= 1 ? S.start : undefined, width: S.width, barriers: $('crbar').value, marks: S.marks, signs: S.signs, rnd: S.rndCode || undefined, look: S.rndLook || undefined, fresh: S.rndFresh || undefined, items: S.items || undefined, props: S.props, waters: S.waters, kit: $('crkit').value, sel: [...S.sel], far: +$('crpfar').value,
                terrain: packFull(S.terrain) };
    return d;
  };
  const closeR = () => Math.max(CLOSE_DIST, S.width * 0.8);

  // ---- annuler / retablir : instantane du brouillon (trace, bords, objets, relief, peinture, reglages) pris un
  // instant apres chaque modification enregistree (saveDraft) ; un trait de pinceau, un glisser ou un trajet du
  // paveur = une etape ----
  const HIST_MAX = 60;
  let hist = [], histAt = -1, histTimer = 0;
  function histSnap() {
    const T = S.terrain;
    return { meta: JSON.stringify({ points: S.points, closed: S.closed, width: S.width, barriers: $('crbar').value, marks: S.marks, signs: S.signs,
                                    kit: $('crkit').value, sel: [...S.sel], far: $('crpfar').value, props: S.props, waters: S.waters,
                                    t: T && [T.x0, T.y0, T.cell, T.n, T.size] }),
             h: T?.h.slice(), paint: T?.paint.slice(), dig: T?.dig?.slice(), aih: T?.aih?.slice(), clay: clay.snapshot() };
  }
  const sameArr = (a, b) => a === b || (a && b && a.length === b.length && a.every((v, i) => v === b[i]));
  const histSame = (a, b) => a.meta === b.meta && sameArr(a.h, b.h) && sameArr(a.paint, b.paint) && sameArr(a.dig, b.dig) && a.clay?.v === b.clay?.v;
  function histButtons() {
    $('crundo').disabled = histAt <= 0; $('crredo').disabled = histAt >= hist.length - 1;
    // fleches de la barre du haut : meme etat ($ ne cherche que dans le panneau de droite) ; Creation fermee : ce sont
    // celles de l'Edition (elle y melange ses etapes et celles faites ici sur les objets de la base)
    if (S.active) { document.getElementById('undo').disabled = histAt <= 0; document.getElementById('redo').disabled = histAt >= hist.length - 1; }
  }
  // historique de la base de la piste chargee : garde d'une ouverture a l'autre, et rempli aussi quand la Creation est
  // fermee (objets de la base retouches depuis l'Edition, 2026-11-17 : avant, Ctrl+Z ne pouvait pas les defaire)
  function histReset() { clearTimeout(histTimer); histTimer = 0; hist = [{ ...histSnap(), at: 0 }]; histAt = 0; S.histTrack = S.loadedTrack; histButtons(); }
  function histSchedule() { clearTimeout(histTimer); histTimer = setTimeout(histCommit, 350); }
  function histCommit() {
    clearTimeout(histTimer); histTimer = 0;
    if (histAt < 0 || S.histTrack !== S.loadedTrack) return;
    if (S.brushing || S.keys.size || tc?.dragging) { histSchedule(); return; }   // geste en cours : etape a la fin
    const s = histSnap();
    if (histSame(s, hist[histAt])) return;
    // Creation fermee : seules les retouches faites a la main sur les objets de la base (ext*) font une etape ; le reste
    // (report des retouches a l'enregistrement, generation) devient le nouvel etat de depart, sans etape a annuler
    if (!S.active && !S.extPending) { s.at = hist[histAt].at; hist[histAt] = s; return; }
    S.extPending = false;
    s.at = Date.now();                                       // heure de l'etape : Ctrl+Z de l'Edition defait la plus recente des deux piles
    hist.length = histAt + 1; hist.push(s);
    if (hist.length > HIST_MAX) hist.shift();
    histAt = hist.length - 1; histButtons();
    ctx.onBaseEdit?.();
  }
  // pour la pile commune de l'Edition : heure de l'etape a annuler / a retablir (-1 : aucune)
  function histTimes() {
    if (histTimer) histCommit();
    if (S.histTrack !== S.loadedTrack || histAt < 0) return { undo: -1, redo: -1 };
    return { undo: histAt > 0 ? hist[histAt].at || 0 : -1, redo: histAt < hist.length - 1 ? hist[histAt + 1].at || 0 : -1 };
  }
  function histRestore(s) {
    const m = JSON.parse(s.meta);
    // objet selectionne (outil Modifier) : retrouve dans l'etat remis par sa place dans la liste
    const si = S.propSelP ? S.props.indexOf(S.propSelP) : -1;
    S.points = m.points; S.closed = m.closed; S.props = m.props; S.sel = new Set(m.sel);
    S.propSelP = si >= 0 && S.props[si] ? S.props[si] : null;
    if (!S.propSelP) selectProp(null);
    S.waters = m.waters || []; if (S.waterSel >= S.waters.length) S.waterSel = -1;
    $('crbar').value = m.barriers; $('crpfar').value = m.far; $('crpfarv').textContent = m.far;
    setMarks(m.marks); setSigns(m.signs);
    if (m.t) {
      S.terrain = { x0: m.t[0], y0: m.t[1], cell: m.t[2], n: m.t[3], size: m.t[4], h: s.h.slice(), paint: s.paint.slice(),
                    dig: s.dig ? s.dig.slice() : new Uint8Array(m.t[3] * m.t[3]), aih: s.aih?.slice() };
      $('crsize').value = String(m.t[4]);
    }
    if ($('crkit').value !== m.kit) { $('crkit').value = m.kit; applyKit(); } else syncSel();
    setWidth(m.width); placeFromPoints(); S.back = 0;          // pente du bout de route reprise (placeFromPoints)
    if (S.edgeSel && S.edgeSel.i >= S.points.length) selectEdge(null);
    S.terrainDirty = S.dirtyT = false;
    clay.setSnap(s.clay);
    refreshTerrainMesh(); rebuild(); renderProps(); if (S.edgeSel) placeEdge();
    writeDraft(); histButtons();
  }
  function undo() {
    if (tc?.dragging || S.brushing) return;
    if (histTimer) histCommit();                              // modification toute fraiche : d'abord en faire une etape
    if (histAt <= 0) { status('Rien à annuler'); return; }
    histRestore(hist[--histAt]); genAgain(); status('Annulé');
  }
  function redo() {
    if (tc?.dragging || S.brushing || histAt >= hist.length - 1) return;
    histRestore(hist[++histAt]); genAgain(); status('Rétabli');
  }
  // base revenue (Annuler / Retablir) a l'etat de la derniere generation : plus « à générer » (2026-11-17 : l'indicateur
  // restait leve apres avoir annule la seule retouche faite depuis la generation)
  function genMark() { if (histTimer) histCommit(); S.genSnap = histSnap(); }
  function genAgain() { if (S.genSnap) S.genDirty = !histSame(hist[histAt], S.genSnap); }

  function resetPaver() {
    const st = S.start, z = heightAt(st.pos[0], st.pos[1]);
    S.points = [[st.pos[0], st.pos[1], z, S.width]];
    S.closed = false; S.pos = new THREE.Vector3(st.pos[0], st.pos[1], z); S.yaw = st.yaw; S.slope = 0; S.back = 0; S.roll = 0;
    setRollTarget(0);
  }
  // inclinaison voulue (radians, positive : a gauche) : curseur a gauche = pencher a gauche. Le kart la rejoint en roulant
  function setRollTarget(a) {
    S.rollTarget = Math.max(-ROLL_MAX, Math.min(ROLL_MAX, a));
    const deg = Math.round(S.rollTarget * 180 / Math.PI);
    if (+$('crroll').value !== -deg) $('crroll').value = -deg;
    const txt = deg ? `${deg > 0 ? '←' : '→'} ${Math.abs(deg)}°` : 'à plat';
    if ($('crrollv').textContent !== txt) $('crrollv').textContent = txt;
  }
  $('crroll').oninput = e => setRollTarget(-e.target.value * Math.PI / 180);
  $('crrollflat').onclick = () => setRollTarget(0);
  const setBlend = v => {
    S.blendSlope = v; $('crblend').value = v;
    $('crblendv').textContent = `${(v * 10).toLocaleString('fr')} m / 10 m`;
  };
  $('crblend').oninput = e => setBlend(+e.target.value);
  $('crblend').onchange = () => { refreshTerrainMesh(); rebuild(); renderProps(); saveDraft(); };   // au relachement : tout le terrain
  $('craigo').onclick = () => aiDecor();
  $('crairm').onclick = aiRemove;
  for (const id of ['craiamp', 'craiclear', 'craireach']) $(id).oninput = aiShowValues;
  // un reglage retouche a la main : plus aucun style tout fait n'est allume
  const aiMarkPreset = name => { for (const b of panel.querySelectorAll('[data-aipreset]')) b.classList.toggle('primary', b.dataset.aipreset === name); };
  for (const id of [...AI_FIELDS, 'craibig', 'craisight']) $(id).onchange = () => { if (id !== 'craiamp' && id !== 'craiborrow' && id !== 'craibig' && id !== 'craisight') aiMarkPreset(null); aiSaveOptions(); };
  for (const b of panel.querySelectorAll('[data-aipreset]')) b.onclick = () => { aiPreset(b.dataset.aipreset); aiMarkPreset(b.dataset.aipreset); };
  $('crptauto').onclick = () => setPropTab('auto');
  $('crptman').onclick = () => setPropTab('man');
  S.propTab = (() => { try { return localStorage.getItem('ctr_creator_proptab'); } catch (e) { return null; } })() === 'man' ? 'man' : 'auto';
  aiLoadOptions();
  const setFade = v => { S.fade = v; $('crfade').value = v; };
  $('crfade').onchange = e => { setFade(+e.target.value); refreshTerrainFaces(); saveDraft(); };
  const setTalus = on => { S.noTalus = !on; $('crtalus').checked = on; };
  $('crtalus').onchange = e => setTalus(e.target.checked);
  $('crtalusall').onclick = () => {
    S.points.forEach(p => setNoTalus(p, S.noTalus));
    refreshTerrainMesh(); rebuild(); renderProps(); saveDraft();
    status(S.noTalus ? 'Toute la route : sans talus' : 'Toute la route : avec talus', 'ok');
  };
  // inclinaison d'un point du trace (bord gauche plus bas si positive), d'apres le relevement de ses bords
  const rollOf = p => { const [wl, wr, hl, hr] = edgesOf(p); return Math.asin(Math.max(-1, Math.min(1, (hr - hl) / (wl + wr || 1)))); };
  // hauteur reelle du centre de la route (effPoints) : un bord releve d'un seul cote (pieces speciales : bord interieur a
  // hauteur, exterieur releve) remonte le centre de la moitie. Sans elle, en reculant sur une spirale le kart passait sous
  // la route (2026-11-13). Le paveur repart de la : ses points (bords symetriques) gardent le centre continu
  const effZ = p => p[2] + ((p[7] ?? 0) + (p[8] ?? 0)) / 2;
  function placeFromPoints() {
    const p = S.points[S.points.length - 1];
    S.pos = new THREE.Vector3(p[0], p[1], effZ(p)); S.roll = rollOf(p); setRollTarget(S.roll); setTalus(!p[9]);
    if (S.points.length > 1) {
      const q = S.points[S.points.length - 2];
      S.yaw = Math.atan2(p[1] - q[1], p[0] - q[0]);
      // cap du kart au dernier point (2026-11-18, « le kart ne reprend plus le meme angle si on efface ») : dans un virage,
      // la corde du dernier pas est en retard d'un demi-pas sur le cap qu'avait le kart -> on prolonge le virage des deux
      // derniers pas (meme courbure), sauf saut ou cassure (> 30 deg entre deux pas : raccord, piece posee)
      if (S.points.length > 2) {
        const o = S.points[S.points.length - 3];
        let d = S.yaw - Math.atan2(q[1] - o[1], q[0] - o[0]);
        d = Math.atan2(Math.sin(d), Math.cos(d));
        if (Math.abs(d) < Math.PI / 6 && !p[4] && !q[4]) S.yaw += d / 2;
      }
    }
    else S.yaw = S.start.yaw;
    S.slope = slopeOfEnd();
  }
  // pente du bout de la route (2026-11-12) : apres un recul, le paveur repart dans la continuite (montee / descente
  // gardee) au lieu de repartir a plat, ce qui faisait une bosse. Moyenne sur ~12 m (points de 4 m), bornee comme au volant
  function slopeOfEnd() {
    const n = S.points.length; if (n < 2) return 0;
    const a = S.points[Math.max(0, n - 4)], b = S.points[n - 1];
    let run = 0;
    for (let i = Math.max(1, n - 3); i < n; i++) run += Math.hypot(S.points[i][0] - S.points[i - 1][0], S.points[i][1] - S.points[i - 1][1]);
    if (run < 1 || a[4] || b[4]) return 0;                   // saut (trou) au bout : pas de pente a reprendre
    return Math.max(-SLOPE_MAX, Math.min(SLOPE_MAX, (effZ(b) - effZ(a)) / run));
  }
  const length = () => S.points.reduce((a, p, i) => i ? a + Math.hypot(p[0] - S.points[i - 1][0], p[1] - S.points[i - 1][1]) : 0, 0);
  const nearStart = () => S.points.length > 2 && length() > CLOSE_MIN_LEN &&
    Math.hypot(S.pos.x - S.points[0][0], S.pos.y - S.points[0][1]) < closeR();

  // bord de route sans repli (track_creator._unfold) : chaque boucle (le bord se recoupe a moins de 40 points) ramenee
  // a son croisement, puis un point qui recule par rapport a la tangente reste colle au dernier point valide
  function unfold(E, tg) {
    E = E.map(e => e.slice());
    const n = E.length;
    for (let i = 0; i < n - 2; i++) {
      const a = E[i], b = E[i + 1], r0 = b[0] - a[0], r1 = b[1] - a[1];
      for (let j = Math.min(n - 2, i + 40); j > i + 1; j--) {
        const c = E[j], d = E[j + 1], s0 = d[0] - c[0], s1 = d[1] - c[1], den = r0 * s1 - r1 * s0;
        if (Math.abs(den) < 1e-9) continue;
        const t = ((c[0] - a[0]) * s1 - (c[1] - a[1]) * s0) / den, u = ((c[0] - a[0]) * r1 - (c[1] - a[1]) * r0) / den;
        if (t > 0 && t < 1 && u > 0 && u < 1) {
          const x = a[0] + t * r0, y = a[1] + t * r1;
          for (let k = i + 1; k <= j; k++) { E[k][0] = x; E[k][1] = y; }
          i = j; break;
        }
      }
    }
    let last = 0;
    for (let i = 1; i < n; i++) {
      if ((E[i][0] - E[last][0]) * tg[i][0] + (E[i][1] - E[last][1]) * tg[i][1] <= 2) continue;
      for (let k = last + 1; k < i; k++) {                   // points ecartes : repartis sur le segment (position et hauteur)
        const w = (k - last) / (i - last);
        for (const c of [0, 1, 2]) E[k][c] = E[last][c] + (E[i][c] - E[last][c]) * w;
      }
      last = i;
    }
    for (let k = last + 1; k < n; k++) E[k] = E[last].slice();
    return E;
  }
  // bords reels de la route (memes valeurs que rebuild) : [gauche, droit], listes de [x, y, z] ; fermee : sans doublon
  function realEdges(P) {
    const n = P.length, L = [], R = [], tg = [];
    for (let i = 0; i < n; i++) {
      const a = P[i > 0 ? i - 1 : S.closed ? n - 1 : 0], b = P[i < n - 1 ? i + 1 : S.closed ? 0 : n - 1];
      let tx = b[0] - a[0], ty = b[1] - a[1]; const l = Math.hypot(tx, ty) || 1; tx /= l; ty /= l;
      const h = P[i][3] / 2, z = P[i][2] + 6, bank = P[i][5];
      L.push([P[i][0] - ty * h, P[i][1] + tx * h, z + bank]); R.push([P[i][0] + ty * h, P[i][1] - tx * h, z - bank]); tg.push([tx, ty]);
    }
    return [unfold(L, tg), unfold(R, tg)];
  }
  // ruban de route (vraie texture du theme) ; talus = terrain raccorde (refreshTerrainMesh) ; tablier de pont la ou la
  // route passe a plus de 2,5 m au-dessus du sol affiche (comme la generation)
  function rebuild() {
    const E0 = effPoints(), P = S.closed ? [...E0, E0[0]] : E0;     // route reelle (bords edites)
    const n = P.length, rv = [], ruv = [], cl = [], el = [], er = [], deck = [], tg = [];
    const rrep = (S.kitInfo?.road_repeat || 14) * IN;
    let s = 0;
    for (let i = 0; i < n; i++) {
      const a = P[Math.max(0, i - 1)], b = P[Math.min(n - 1, i + 1)];
      let tx = b[0] - a[0], ty = b[1] - a[1]; const l = Math.hypot(tx, ty) || 1; tx /= l; ty /= l;
      const [x, y, z, w] = P[i], h = w / 2, lz = z + 6, bank = P[i][5];
      if (i) s += Math.hypot(x - P[i - 1][0], y - P[i - 1][1]);
      rv.push([x - ty * h, y + tx * h, lz + bank], [x + ty * h, y - tx * h, lz - bank]); ruv.push(s / rrep); tg.push([tx, ty]);
      deck.push(!P[i][4] && z - shownAt(x, y) > 2.5 * IN);
      cl.push(x, y, lz + 10);
    }
    // bords sans repli dans les virages plus serres que la demi-largeur (track_creator._unfold)
    for (const side of [0, 1]) {
      const E = unfold(rv.filter((_, k) => k % 2 === side), tg);
      E.forEach((e, i) => { rv[2 * i + side] = e; (side ? er : el).push(e[0], e[1], e[2] + 12); });
    }
    const pos = [], uv = [], bpos = [];
    for (let i = 0; i + 1 < n; i++) {
      if (P[i][4] || P[i + 1][4]) continue;                  // saut : pas de route
      const [l0, r0, l1, r1] = [rv[2 * i], rv[2 * i + 1], rv[2 * i + 2], rv[2 * i + 3]];
      pos.push(...l0, ...l1, ...r1, ...l0, ...r1, ...r0);
      uv.push(0, ruv[i], 0, ruv[i + 1], 1, ruv[i + 1], 0, ruv[i], 1, ruv[i + 1], 1, ruv[i]);
      if (deck[i] || deck[i + 1]) for (const [e0, e1] of [[l0, l1], [r0, r1]]) {      // flancs du tablier (1,2 m)
        const d0 = [e0[0], e0[1], e0[2] - 1.2 * IN], d1 = [e1[0], e1[1], e1[2] - 1.2 * IN];
        bpos.push(...e0, ...e1, ...d1, ...e0, ...d1, ...d0);
      } else for (const [e0, e1] of [[l0, l1], [r0, r1]]) {  // jupe (track_creator) : bord qui surplombe le sol
        const g0 = shownAt(e0[0], e0[1]), g1 = shownAt(e1[0], e1[1]);
        if (Math.max(e0[2] - g0, e1[2] - g1) <= 0.6 * IN) continue;
        const d0 = [e0[0], e0[1], g0 - 20], d1 = [e1[0], e1[1], g1 - 20];
        bpos.push(...e0, ...e1, ...d1, ...e0, ...d1, ...d0);
      }
    }
    roadMat.map = kitTexture('road.png'); roadMat.needsUpdate = true;
    road.geometry.dispose(); road.geometry = new THREE.BufferGeometry();
    road.geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(pos), 3));
    road.geometry.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(uv), 2));
    banks.geometry.dispose(); banks.geometry = new THREE.BufferGeometry();
    banks.geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(bpos), 3));
    banks.geometry.computeVertexNormals();
    for (const [line, pts] of [[edgeL, el], [edgeR, er]]) {
      const m = pts.length / 3, hw = 5, v = new Float32Array(m * 6), ix = new Uint32Array(Math.max(0, m - 1) * 6);
      for (let i = 0; i < m; i++) {                          // perpendiculaire au bord, a plat
        const a = Math.max(0, i - 1) * 3, b = Math.min(m - 1, i + 1) * 3;
        let tx = pts[b] - pts[a], ty = pts[b + 1] - pts[a + 1]; const l = Math.hypot(tx, ty) || 1; tx /= l; ty /= l;
        v.set([pts[i * 3] - ty * hw, pts[i * 3 + 1] + tx * hw, pts[i * 3 + 2], pts[i * 3] + ty * hw, pts[i * 3 + 1] - tx * hw, pts[i * 3 + 2]], i * 6);
        if (i + 1 < m) ix.set([2 * i, 2 * i + 1, 2 * i + 3, 2 * i, 2 * i + 3, 2 * i + 2], i * 6);
      }
      line.geometry.dispose(); line.geometry = new THREE.BufferGeometry();
      line.geometry.setAttribute('position', new THREE.BufferAttribute(v, 3));
      line.geometry.setIndex(new THREE.BufferAttribute(ix, 1));
    }
    center.geometry.dispose(); center.geometry = new THREE.BufferGeometry();
    center.geometry.setAttribute('position', new THREE.Float32BufferAttribute(cl, 3));
    // damier du depart, en travers de la route au 1er point (comme la generation)
    startLine.visible = n > 1 && !P[0][4];
    if (startLine.visible) {
      const [l, rr] = [rv[0], rv[1]], [tx, ty] = tg[0], d = START_CELL_M * IN;           // demi-bande : 2 rangees
      // pente de la route au depart (2026-11-24 : le damier restait horizontal, en l'air ou enterre dans une pente)
      const pa = P[S.closed ? n - 1 : 0], pb = P[1], sz = (pb[2] - pa[2]) / (Math.hypot(pb[0] - pa[0], pb[1] - pa[1]) || 1);
      const q = (p, k) => [p[0] + tx * d * k, p[1] + ty * d * k, p[2] + sz * d * k + 4];
      const w = Math.hypot(l[0] - rr[0], l[1] - rr[1]) / (2 * START_CELL_M * IN);       // repetitions (2 cases)
      const A = q(rr, -1), B = q(rr, 1), Cq = q(l, 1), D = q(l, -1);
      startLine.geometry.dispose(); startLine.geometry = new THREE.BufferGeometry();
      startLine.geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array([...A, ...B, ...Cq, ...A, ...Cq, ...D]), 3));
      startLine.geometry.setAttribute('uv', new THREE.BufferAttribute(new Float32Array([0, 0, 0, 1, w, 1, 0, 0, w, 1, w, 0]), 2));
    }
    const r = closeR(); startMark.scale.set(r, 30, r);           // cylindre couche : x, z = rayon, y = hauteur
    if (S.points.length) startMark.position.set(S.points[0][0], S.points[0][1], S.points[0][2] + 5);
    marksGeometry(P, rv, tg);
    showRoadStat();
  }

  // ---- marquage au sol (2026-11-13) : apercu de track_creator._markings (memes regles, memes distances) ----
  // 'arrows' (fleches peintes avant les virages) RETIRE le 2026-11-13 (« pas pertinent ») : plus proposees ni dessinees
  const MARK_KEYS = ['edges', 'center', 'curbs'];
  const MK = { lift: 5, edgeIn: 0.6 * IN, edgeW: 0.4 * IN, centerW: 0.3 * IN, dash: 3 * IN, period: 9 * IN,
               curbW: 1.5 * IN, curbRep: 3 * IN, curveR: 90 * IN, arrowAt: [45 * IN, 25 * IN] };
  const ARROW_SHAPE = [[[-7, -0.7], [0.7, -0.7], [0.7, 0.7], [-7, 0.7]], [[-0.7, 0.7], [0.7, 0.7], [0.7, 4], [-0.7, 4]],
                       [[-2.4, 4], [2.4, 4], [0, 7.5]]];
  const curbTex = (() => {
    const c = document.createElement('canvas'); c.width = 4; c.height = 2;
    const g = c.getContext('2d'); g.fillStyle = '#c81e1e'; g.fillRect(0, 0, 4, 1); g.fillStyle = '#ececE4'; g.fillRect(0, 1, 4, 1);
    const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.magFilter = THREE.NearestFilter; t.colorSpace = THREE.SRGBColorSpace;
    return t;
  })();
  const markOpts = { side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -3, polygonOffsetUnits: -3 };
  const markWhite = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial({ color: 0xececE4, ...markOpts }));
  const markCurb = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial({ map: curbTex, ...markOpts }));
  group.add(markWhite, markCurb);
  S.marks = {};
  function setMarks(m) {
    S.marks = Object.fromEntries(MARK_KEYS.map(k => [k, !!(m && m[k])]));
    for (const c of panel.querySelectorAll('[data-mark]')) c.checked = S.marks[c.dataset.mark];
  }
  for (const c of panel.querySelectorAll('[data-mark]')) c.onchange = () => {
    S.marks = { ...S.marks, [c.dataset.mark]: c.checked }; rebuild(); saveDraft();
  };
  // panneaux de virage : apercu en panneaux orange (les vrais modeles du jeu sont poses a la generation)
  const signMesh = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial({ color: 0xffe600, side: THREE.DoubleSide }));
  group.add(signMesh);
  S.signs = {};
  function setSigns(v) {
    S.signs = { style: '' };                  // option retiree (2026-11-13) : un brouillon qui en avait n'en pose plus
    $('crsign').value = S.signs.style;
  }
  $('crsign').onchange = () => { setSigns({ style: $('crsign').value }); rebuild(); saveDraft(); };
  function marksGeometry(P, rv, tg) {
    const n = P.length, M = S.marks || {}, wpos = [], cpos = [], cuv = [], spos = [];
    if ((!MARK_KEYS.some(k => M[k]) && !S.signs?.style) || n < 3) {
      for (const m of [markWhite, markCurb, signMesh]) { m.geometry.dispose(); m.geometry = new THREE.BufferGeometry(); }
      return;
    }
    const L = i => rv[2 * i], R = i => rv[2 * i + 1];
    const W = i => Math.hypot(L(i)[0] - R(i)[0], L(i)[1] - R(i)[1]) || 1;
    const Q = (i, q) => [R(i)[0] + (L(i)[0] - R(i)[0]) * q, R(i)[1] + (L(i)[1] - R(i)[1]) * q, R(i)[2] + (L(i)[2] - R(i)[2]) * q + MK.lift];
    const s = [0]; for (let i = 1; i < n; i++) s.push(s[i - 1] + Math.hypot(P[i][0] - P[i - 1][0], P[i][1] - P[i - 1][1]));
    const jump = i => P[i][4];
    const fq = d => i => Math.min(0.5, d / W(i));
    const strip = (out, uv, ok, q0, q1, rep) => {
      for (let k = 0; k + 1 < n; k++) {
        if (jump(k) || jump(k + 1) || !ok(k)) continue;
        const a = Q(k, q0(k)), b = Q(k + 1, q0(k + 1)), c = Q(k + 1, q1(k + 1)), d = Q(k, q1(k));
        out.push(...a, ...b, ...c, ...a, ...c, ...d);
        if (uv) { const va = s[k] / rep, vb = s[k + 1] / rep; uv.push(0, va, 0, vb, 1, vb, 0, va, 1, vb, 1, va); }
      }
    };
    if (M.edges) {
      const a = fq(MK.edgeIn), b = fq(MK.edgeIn + MK.edgeW);
      strip(wpos, null, () => true, a, b); strip(wpos, null, () => true, i => 1 - b(i), i => 1 - a(i));
    }
    if (M.center) { const h = fq(MK.centerW / 2); strip(wpos, null, k => s[k] % MK.period < MK.dash, i => 0.5 - h(i), i => 0.5 + h(i)); }
    // virages serres (meme mesure que la generation : angle entre les tangentes de part et d'autre)
    const radius = [], sign = [];
    for (let i = 0; i < n; i++) {
      const a = tg[Math.max(0, i - 1)], b = tg[Math.min(n - 1, i + 1)];
      const turn = Math.atan2(a[0] * b[1] - a[1] * b[0], a[0] * b[0] + a[1] * b[1]);
      const len = (i > 0 ? s[i] - s[i - 1] : 0) + (i + 1 < n ? s[i + 1] - s[i] : 0);
      radius.push(len / Math.max(Math.abs(turn), 1e-6)); sign.push(Math.sign(turn));
    }
    const tight = radius.map(r => r < MK.curveR);
    if (M.arrows) {
      const seg = s[n - 1] / Math.max(1, n - 1);
      for (let i0 = 1; i0 < n; i0++) {
        if (!tight[i0] || tight[i0 - 1]) continue;
        const side = sign[i0] || 1;
        for (const dist of MK.arrowAt) {
          const k = i0 - Math.round(dist / seg);
          if (k < 0 || jump(k) || tight[k]) continue;
          for (const poly of ARROW_SHAPE) {
            let vs = poly.map(([u, w]) => {
              const fi = Math.max(0, Math.min(n - 1.001, k + u * IN / seg)), ia = Math.floor(fi), t = fi - ia;
              const q = Math.max(0, Math.min(1, 0.5 + side * w * IN / W(ia)));
              const A = Q(ia, q), B = Q(Math.min(n - 1, ia + 1), q);
              return A.map((v, j) => v * (1 - t) + B[j] * t);
            });
            if (side < 0) vs = vs.reverse();
            wpos.push(...vs[0], ...vs[1], ...vs[2]);
            if (vs.length === 4) wpos.push(...vs[0], ...vs[2], ...vs[3]);
          }
        }
      }
    }
    if (M.curbs) {
      const ext = 3, inside = { 1: new Array(n).fill(false), [-1]: new Array(n).fill(false) };
      for (let i = 0; i < n; i++) if (tight[i] && sign[i]) for (let e = -ext; e <= ext; e++) { const j = i + e; if (j >= 0 && j < n) inside[sign[i]][j] = true; }
      const a = fq(MK.curbW);
      strip(cpos, cuv, k => inside[-1][k] && inside[-1][k + 1], () => 0, a, MK.curbRep);
      strip(cpos, cuv, k => inside[1][k] && inside[1][k + 1], i => 1 - a(i), () => 1, MK.curbRep);
    }
    if (S.signs?.style) {   // meme regle que track_creator._sign_turns / sign_spots (2026-11-13 : bien moins de panneaux)
      const off = 2.5 * IN, seg = s[n - 1] / Math.max(1, n - 1), space = 35 * IN, minGap = 30 * IN;
      const ok = i => radius[i] < MK.curveR && radius[i] > 5 * IN && sign[i];
      const runs = [];
      for (let i = 0; i < n;) {
        if (!ok(i)) { i++; continue; }
        const a = i, side = sign[i];
        while (i < n && ok(i) && sign[i] === side) i++;
        const last = runs[runs.length - 1];
        if (last && last[2] === side && s[a] - s[last[1]] <= 10 * IN) last[1] = i - 1; else runs.push([a, i - 1, side]);
      }
      const placed = [];
      for (const [a, b, side] of runs) {
        let ang = 0, rmin = Infinity;
        for (let k = a; k <= b; k++) { ang += seg / radius[k]; rmin = Math.min(rmin, radius[k]); }
        if (ang < 35 * Math.PI / 180 || rmin >= 60 * IN) continue;
        const cnt = Math.max(1, Math.min(3, Math.floor((s[b] - s[a] + seg) / space) + 1)), mid = (a + b) / 2;
        const ks = [];
        for (let j = 0; j < cnt; j++) ks.push(Math.min(b, Math.max(a, Math.round(mid + (j - (cnt - 1) / 2) * space / seg))));
        for (const k of ks) {
          if (jump(k) || placed.some(([x, y]) => Math.hypot(P[k][0] - x, P[k][1] - y) < minGap)) continue;
          placed.push([P[k][0], P[k][1]]);
          const e = side > 0 ? R(k) : L(k), [tx, ty] = tg[k], ox = side > 0 ? ty : -ty, oy = side > 0 ? -tx : tx;
          const x = e[0] + ox * off, y = e[1] + oy * off, z = e[2], hw = 3 * IN, h0 = 1.5 * IN, h1 = 5.5 * IN;
          const ax = -ty * hw, ay = tx * hw;          // panneau en travers de la route, face aux karts
          spos.push(x - ax, y - ay, z + h0, x + ax, y + ay, z + h0, x + ax, y + ay, z + h1,
                    x - ax, y - ay, z + h0, x + ax, y + ay, z + h1, x - ax, y - ay, z + h1);
        }
      }
    }
    signMesh.geometry.dispose(); signMesh.geometry = new THREE.BufferGeometry();
    signMesh.geometry.setAttribute('position', new THREE.Float32BufferAttribute(spos, 3));
    markWhite.geometry.dispose(); markWhite.geometry = new THREE.BufferGeometry();
    markWhite.geometry.setAttribute('position', new THREE.Float32BufferAttribute(wpos, 3));
    markCurb.geometry.dispose(); markCurb.geometry = new THREE.BufferGeometry();
    markCurb.geometry.setAttribute('position', new THREE.Float32BufferAttribute(cpos, 3));
    markCurb.geometry.setAttribute('uv', new THREE.Float32BufferAttribute(cuv, 2));
  }
  // ligne d'etat : au plus 4 fois par seconde et seulement si elle change. Reecrite a chaque point, elle faisait repeindre
  // la couche des barres (menu, colonne de droite) : elles clignotaient pendant que le paveur roule
  let statShown = '', statAt = 0, statTimer = 0;
  function showRoadStat() {
    const now = performance.now();
    if (now - statAt < 250) { statTimer ||= setTimeout(() => { statTimer = 0; showRoadStat(); }, 250); return; }
    statAt = now;
    const len = length() / IN, near = nearStart();
    const deg = Math.round(Math.abs(S.roll || 0) * 180 / Math.PI);
    const html = `Longueur : <b>${Math.round(len)} m</b> · ${S.points.length} points · ` + (deg ? `inclinaison <b>${deg}° ${S.roll > 0 ? '←' : '→'}</b> · ` : '') +
      (S.closed ? '<b style="color:var(--ok)">boucle fermée</b>' : near ? '<b style="color:var(--ok)">Entrée : fermer la boucle</b>' : 'boucle ouverte');
    if (html !== statShown) { statShown = html; $('crstat').innerHTML = html; }
    if ($('crgo').disabled !== !S.closed) $('crgo').disabled = !S.closed;
    const noClose = S.closed || !near;
    if ($('crclose').disabled !== noClose) $('crclose').disabled = noClose;
  }
  // croisement : nouveau point sur un morceau plus ancien a la meme hauteur (pas de pont possible)
  function crossing(p) {
    if (Math.hypot(p[0] - S.points[0][0], p[1] - S.points[0][1]) < closeR() * 1.5) return false;   // retour au depart
    // morceau tout juste pose exclu : 8 points (32 m) + 1,5 largeur de route. Avec 8 points seulement, une route de plus de
    // 32 m de large se « croisait » elle-meme, meme en ligne droite
    const recent = 8 + Math.ceil(1.5 * p[3] / STEP);
    for (let i = 0; i < S.points.length - recent; i++) {
      const q = S.points[i];
      if (Math.hypot(p[0] - q[0], p[1] - q[1]) < (p[3] + q[3]) / 2 && Math.abs(p[2] - q[2]) < 7 * IN) return true;
    }
    return false;
  }

  // zone du terrain touchee par un point pose ou retire : portee du raccord (conform) autour de ce point et des 45
  // precedents, dont les bords reels peuvent changer (unfold regarde 40 points en avant)
  function growPave(p) {
    const T = S.terrain, P = S.points; if (!T) return;
    for (let k = Math.max(0, P.length - 46); k <= P.length; k++) {
      const q = k < P.length ? P[k] : p, [wl, wr, hl, hr] = edgesOf(q);
      const m = T.cell + Math.max(wl, wr) + blendWidth(Math.abs(q[2] - S.groundZ) + Math.abs(hl) + Math.abs(hr) + (S.hMax || 0) + 2 * IN, 1, S.blendSlope ?? BLEND_DEF, T.cell) + 4 * IN;
      S.paveBox = growBox(S.paveBox, q[0] - m, q[1] - m, q[0] + m, q[1] + m);
    }
  }
  // qualite de la vue : la peinture des pixels pese le plus sur une petite carte graphique. Auto : sous ~35 images/s la
  // resolution baisse par paliers, et remonte s'il y a de la marge (attente doublee si elle redescend aussitot : pas de
  // va-et-vient) ; aux derniers paliers, les objets trop petits a l'ecran sont aussi masques (aperçu seulement)
  // 2026-11-07 : plus aucune zone masquee/remontree selon la distance (Q_HIDE_PX a 0) : une zone entiere de decor qui
  // apparait et disparait en bougeant la camera se voyait comme un clignotement ; la vue Edition n'en a pas
  const Q_SCALE = [1, 0.8, 0.65, 0.5], Q_HIDE_PX = [0, 0, 0, 0], Q_KEY = 'ctr_creator_quality';
  const qMode = () => $('crq').value;
  function setQuality(level) {
    Q.level = level; ctx.setRenderScale?.(Q_SCALE[level]);
    $('crq').options[0].textContent = qMode() === 'auto' && level ? `Auto (${Math.round(Q_SCALE[level] * 100)} %)` : 'Auto';
    if (Q_HIDE_PX[level] === 0) for (const m of propGroup.children) m.visible = true;
  }
  function cullSmallProps() {
    const px = Q_HIDE_PX[Q.level]; if (!px) return;
    const k = view.clientHeight * Q_SCALE[Q.level] / (2 * Math.tan(camera.fov * Math.PI / 360));
    for (const m of propGroup.children) {                 // zone entiere : d'apres son objet le plus proche et le plus grand
      const bs = m.boundingSphere, dist = Math.max(1, bs.center.distanceTo(camera.position) - bs.radius);
      // marge : une zone a la limite apparaissait et disparaissait sans arret
      m.visible = m.userData.maxR * k >= px * dist * (m.visible ? 0.8 : 1.25);
    }
  }
  function updateQuality(t, ms) {
    if (t - Q.cull > 250) { Q.cull = t; cullSmallProps(); }
    // 2026-11-07 : Auto ne change PLUS la resolution (la vue Edition, qui ne la change jamais, ne clignote pas ; chaque
    // changement recree la zone de dessin = ecran qui clignote sur les petits PC) ; Auto = objets alleges seulement.
    // Moyenne / Basse (choisies a la main) gardent leur resolution fixe.
    return;
    // onglet masque, objets en chargement, pose en cours : ces images lentes ne disent rien de la carte graphique. Sinon, la
    // resolution de toute la vue changeait a chaque objet pose : c'est ce qui se voyait comme un clignotement de l'ecran
    if (!(ms > 0) || ms > 250 || Q.loading > 0 || S.brushing || S.propsDirty) { Q.sum = Q.n = 0; Q.from = t; Q.bad = 0; return; }
    Q.sum += ms; Q.n++;
    if (t - Q.from < 1000) return;
    const avg = Q.sum / Q.n; Q.sum = Q.n = 0; Q.from = t;
    Q.bad = avg > 28 ? Q.bad + 1 : 0;
    if (Q.bad >= 3 && Q.level < Q_SCALE.length - 1 && t - Q.down > 1500) {          // 3 secondes de suite
      if (t - Q.up < 6000) Q.wait = Math.min(300000, Q.wait * 2);
      Q.bad = 0; Q.down = t; setQuality(Q.level + 1);
    } else if (avg < 15 && Q.level > 0 && t - Q.down > Q.wait) { Q.up = t; Q.down = t; setQuality(Q.level - 1); }
  }
  // carte graphique debordee (ecran noir un instant, tout le navigateur peut clignoter) : apercu au plus leger jusqu'au prochain
  // rechargement de la page. La piste generee n'est pas concernee
  ctx.renderer?.domElement.addEventListener('webglcontextlost', e => {
    e.preventDefault();
    if (S.active) status('La carte graphique a saturé : aperçu allégé. Essaie Qualité : Basse si cela revient', 'err');
  });
  ctx.renderer?.domElement.addEventListener('webglcontextrestored', () => {
    Q.lost = true;
    if (S.active) S.propsDirty = true;          // objets allégés (propLod) ; la résolution ne change plus d'elle-même
  });
  function tick(t) {
    if (!S.active) {
      // apercu de la base dans l'Edition : modeles du decor arrives depuis (reperes provisoires -> vrais objets)
      if (group.visible && propGroup.visible && S.propsDirty && t - (S.lastProps || 0) > 300) { renderProps(); S.propsDirty = false; S.lastProps = t; }
      return;
    }
    updateQuality(t, t - (S.last || t));
    const dt = Math.min(0.1, (t - (S.last || t)) / 1000); S.last = t;
    const propGap = S.props.length > 500 ? 500 : 100;        // beaucoup d'objets : ils suivent moins souvent
    if (S.propsDirty && t - S.lastProps > propGap) { renderProps(); S.propsDirty = false; S.lastProps = t; }
    // terrain raccorde recalcule au plus 8 fois par seconde pendant que le paveur pose la route
    if (S.terrainDirty && t - (S.lastTerrain || 0) > 120) { refreshTerrainMesh(S.paveFull ? null : S.paveBox); rebuild(); S.propsDirty = true; S.terrainDirty = S.paveFull = false; S.paveBox = null; S.lastTerrain = t; }
    // manette : valeurs des actions ; « tap » = appui de ce cadre (bouton qui vient d'etre enfonce)
    const pad = firstPad(), P = {}, was = S.padWas || {};
    for (const [k] of PAD_ACTIONS) P[k] = padValue(pad, S.padMap[k]);
    const tap = k => P[k] > 0.5 && !(was[k] > 0.5);
    S.padWas = P;
    if (tap('undo')) undo();
    if (tap('redo')) redo();
    if (S.mode !== 'route') {
      if (S.brushing) applyBrush(dt);
      // peinture : toute la liste des faces repart a la carte graphique, moins souvent que le relief (lignes touchees seulement)
      // talus de la route et objets : a la fin du trait (endBrush)
      if (S.dirtyT && t - S.lastNormals > (S.mode === 'paint' ? 150 : 50)) { refreshTerrainMesh(S.dirtyBox); S.dirtyBox = null; S.dirtyT = false; S.lastNormals = t; }
      if (S.propsDirty && t - S.lastProps > propGap) { renderProps(); S.propsDirty = false; S.lastProps = t; }
      return;
    }
    if (t - (S.ghostAt || 0) > 120) { S.ghostAt = t; updateGhost(); }   // apercu de la piece speciale devant le kart
    if (S.pickStart) return;                                 // placement du kart en cours : il ne roule pas
    const k = S.keys;
    let fwd = (k.has('ArrowUp') || k.has('KeyW') || k.has('KeyZ')) ? 1 : 0;
    let rev = (k.has('ArrowDown') || k.has('KeyS')) ? 1 : 0;
    let steer = ((k.has('ArrowLeft') || k.has('KeyA') || k.has('KeyQ')) ? 1 : 0) - ((k.has('ArrowRight') || k.has('KeyD')) ? 1 : 0);
    let climb = (k.has('KeyR') ? 1 : 0) - (k.has('KeyF') ? 1 : 0);
    let bank = (k.has('KeyT') ? 1 : 0) - (k.has('KeyG') ? 1 : 0);   // T : incliner a gauche, G : a droite
    if (pad) {
      bank = bank || P.bankLeft - P.bankRight;
    }
    if (bank) setRollTarget((S.rollTarget || 0) + bank * dt * 25 * Math.PI / 180);   // 25 degres par seconde, meme a l'arret
    if (pad) {
      fwd = Math.max(fwd, P.forward); rev = Math.max(rev, P.reverse);
      steer = steer || P.left - P.right; climb = climb || P.up - P.down;
      if (P.wider > 0.5) setWidth(S.width + 10 * IN * dt);
      if (P.narrower > 0.5) setWidth(S.width - 10 * IN * dt);
      if (tap('close') && !S.closed) closeLoop();
      if (tap('camera')) toggleChase();
    }
    if (rev > fwd) fwd = 0; else rev = 0;                    // les deux a la fois : la plus enfoncee
    const speed = SPEED * (k.has('ShiftLeft') || k.has('ShiftRight') || P.fast > 0.5 ? 2 : 1);
    const jumping = k.has('Space') || P.jump > 0.5;                          // saut : trou dans la route
    let changed = false;
    if (fwd > 0 && !S.closed) {
      const d = speed * fwd * dt;
      S.yaw += steer * d / (R_MIN * (1 + R_SLOPE * Math.abs(S.slope) / SLOPE_MAX));
      const target = climb * SLOPE_MAX;
      S.slope += Math.max(-SLOPE_RATE * d, Math.min(SLOPE_RATE * d, target - S.slope));
      // inclinaison progressive vers l'angle choisi
      const dr = (S.rollTarget || 0) - (S.roll || 0);
      if (dr) { S.roll = (S.roll || 0) + Math.sign(dr) * Math.min(Math.abs(dr), ROLL_RATE * d); showRoadStat(); }
      S.pos.x += Math.cos(S.yaw) * d; S.pos.y += Math.sin(S.yaw) * d;
      // ni trop haut ni trop profond : sous le sol, le terrain se creuse autour de la route (conform)
      const floor = S.groundZ - H_MIN;
      S.pos.z = Math.max(floor, Math.min(S.groundZ + H_MAX, S.pos.z + S.slope * d));
      if (S.pos.z <= floor && S.slope < 0) S.slope = 0;
      const last = S.points[S.points.length - 1];
      if (Math.hypot(S.pos.x - last[0], S.pos.y - last[1]) >= STEP) {
        const p = [S.pos.x, S.pos.y, S.pos.z, S.width, jumping ? 1 : 0];
        if (Math.abs(S.roll || 0) > 1e-3) {                  // route inclinee : bords releves / abaisses (comme l'outil Bords)
          const w2 = S.width / 2, dz = Math.round(w2 * Math.sin(S.roll));
          p.push(w2, w2, -dz, dz);
        }
        if (S.noTalus) setNoTalus(p, true);
        if (crossing(p) && t - S.warned > 3000) { S.warned = t; status('Croisement à la même hauteur : monte (R) ou descends (F) pour faire un pont', 'err'); }
        S.points.push(p); changed = true; growPave(p);
      }
    } else if (rev > 0 && S.points.length > 1) {
      if (S.closed) S.paveFull = true;                       // le segment de fermeture disparait : tout le terrain
      S.closed = false;
      S.back += speed * rev * dt;
      while (S.back >= STEP && S.points.length > 1) { growPave(S.points[S.points.length - 1]); S.points.pop(); S.back -= STEP; changed = true; }
      placeFromPoints();                                     // pente du bout de route reprise (plus de bosse)
    } else if (steer && !S.closed && S.points.length === 1) {
      S.yaw += steer * dt * 1.5; S.start = { ...S.start, yaw: S.yaw };    // orienter le depart sur place
    }
    paver.position.copy(S.pos); paver.rotation.set(-(S.roll || 0), -Math.atan(S.slope), S.yaw);
    showHeight();
    if (changed) { rebuild(); S.terrainDirty = true; saveDraft(); }
    if (S.chase) {
      const back = new THREE.Vector3(Math.cos(S.yaw), Math.sin(S.yaw), 0);
      // assez loin pour voir toute la largeur de la route et ce qui arrive
      const want = S.pos.clone().addScaledVector(back, -Math.max(45 * IN, S.width * 1.1)); want.z += Math.max(22 * IN, S.width * 0.55);
      camera.position.lerp(want, Math.min(1, dt * 4));
      const look = S.pos.clone().addScaledVector(back, 25 * IN);
      camera.up.set(0, 0, 1); camera.lookAt(look); orbit.target.copy(look);
    }
  }

  // ---- pieces speciales (2026-11-13) : un morceau de route calcule d'un coup au bout du trace, avec les memes regles
  // que le paveur (rayon mini selon la pente, pente <= 28 %, inclinaison <= 30 deg, vitesses de variation). Points
  // ordinaires du paveur : la generation, les sauts (tremplin) et les outils Bords / Pont s'y appliquent sans rien de plus
  const PIECES = {          // [nom du reglage, min, max, pas, defaut, unite]
    banked:   { a: ['Angle', 45, 180, 15, 90, '°'], b: ['Rayon', 35, 150, 5, 55, ' m'], c: ['Inclinaison', 5, 30, 1, 15, '°'], dir: 1 },
    spiral:   { a: ['Tours', 1, 3, 0.5, 1, ''], b: ['Rayon', 40, 120, 5, 50, ' m'], c: ['Écart entre les boucles', 10, 40, 1, 16, ' m'], dir: 1, vert: 1 },
    slalom:   { a: ['Virages', 2, 8, 1, 3, ''], b: ['Rayon', 35, 120, 5, 45, ' m'], dir: 1 },
    jump:     { a: ['Longueur du trou', 8, 40, 2, 16, ' m'], b: ['Atterrissage plus bas de', 0, 12, 1, 2, ' m'] },
    bumps:    { a: ['Bosses', 1, 8, 1, 3, ''], b: ['Hauteur', 1, 4, 0.5, 2, ' m'] },
    ramp:     { a: ['Dénivelé', 5, 80, 5, 20, ' m'], b: ['Pente', 5, 28, 1, 15, ' %'], vert: 1 },
    straight: { a: ['Longueur', 20, 300, 10, 60, ' m'] },
    // 2026-11-23 : epingle (demi-tour), plongeon (creux en U), boucle qui repasse au-dessus de sa propre entree
    hairpin:  { a: ['Rayon', 35, 100, 5, 45, ' m'], b: ['Inclinaison', 0, 20, 1, 10, '°'], dir: 1 },
    plunge:   { a: ['Profondeur', 4, 40, 1, 12, ' m'], b: ['Pente', 8, 28, 1, 22, ' %'], c: ['Fond plat', 0, 40, 2, 8, ' m'] },
    overpass: { a: ['Rayon', 40, 120, 5, 60, ' m'], b: ['Hauteur au-dessus de la route', 8, 20, 1, 10, ' m'], dir: 1 },
  };
  const BANK_EDGE_SLOPE = 0.15;         // virage releve : pente maxi du bord exterieur qui monte (entree / sortie douces)
  const PIECE_KEY = 'ctr_creator_piece';
  const piece = { kind: 'banked', dir: 1, up: 1, v: {} };
  try { Object.assign(piece, JSON.parse(localStorage.getItem(PIECE_KEY)) || {}); } catch (e) { /* sans importance */ }
  if (!PIECES[piece.kind]) piece.kind = 'banked';
  const pieceVal = (k, which) => { const c = PIECES[k][which]; const v = piece.v[k]?.[which]; return c ? (v ?? c[4]) : 0; };
  const rMinAt = s => R_MIN * (1 + R_SLOPE * Math.abs(s) / SLOPE_MAX);
  // montees par pas (somme = H) : pente 0 -> pic (SLOPE_RATE), palier, pic -> 0 ; pic abaisse si H est trop petit
  function rampProfile(H, p0) {
    const pk = Math.min(p0, Math.sqrt(H * SLOPE_RATE));
    const Lr = pk / SLOPE_RATE, Lf = Math.max(0, (H - pk * pk / SLOPE_RATE) / pk), L = 2 * Lr + Lf;
    const n = Math.max(2, Math.ceil(L / STEP));
    const slopeAt = x => x < Lr ? pk * x / Lr : x < Lr + Lf ? pk : Math.max(0, pk * (L - x) / Lr);
    const dz = Array.from({ length: n }, (_, i) => slopeAt((i + 0.5) * L / n));
    const sum = dz.reduce((a, v) => a + v, 0) || 1;
    return dz.map(v => v * H / sum);
  }
  // pas de 4 m : {k : courbure (1/po, positive a gauche), slope : pente visee | dz : montee imposee, roll : inclinaison visee, jump}
  function pieceSteps() {
    const k = piece.kind, A = pieceVal(k, 'a'), B = pieceVal(k, 'b'), Cv = pieceVal(k, 'c'), side = piece.dir, st = [], deg = Math.PI / 180;
    const steps = len => Math.max(1, Math.round(len / STEP));
    const straight = (len, e = {}) => { for (let i = steps(len); i > 0; i--) st.push({ k: 0, slope: 0, roll: 0, ...e }); };
    const arc = (ang, R, sgn, e = {}) => { const n = Math.max(2, Math.round(ang * R / STEP)); for (let i = 0; i < n; i++) st.push({ k: sgn * ang / (n * STEP), slope: 0, roll: 0, ...e }); };
    const rollIn = r => Math.ceil(Math.abs(r) / ROLL_RATE / STEP) * STEP;      // longueur pour atteindre cette inclinaison
    if (k === 'banked') {
      // 2026-11-13 (retour utilisateur : entree trop brusque, fosse du cote interieur) : le bord INTERIEUR reste a hauteur
      // de route, seul l'exterieur monte (piecePoints) ; inclinaison en courbe douce (smoothstep) sur une longueur telle que
      // le bord exterieur ne monte pas a plus de 15 %, prise en partie dans le debut du virage (30 % de l'arc au plus)
      const R = B * IN, roll = side * Cv * deg, ang = A * deg, arcLen = ang * R;
      const raise = S.width * Math.sin(Cv * deg), Lr = Math.max(30 * IN, raise / BANK_EDGE_SLOPE);
      const lead = Math.max(0, Lr - 0.3 * arcLen);
      straight(lead); arc(ang, R, side); straight(lead);
      const total = st.length * STEP, r0 = S.roll || 0, sm = u => { u = Math.max(0, Math.min(1, u)); return u * u * (3 - 2 * u); };
      st.forEach((e, i) => {
        const s = (i + 1) * STEP;
        e.rollAbs = s < total / 2 ? r0 + (roll - r0) * sm(s / Lr) : roll * sm((total - s) / Lr);
      });
    } else if (k === 'spiral') {
      const s = piece.up * Math.min(SLOPE_MAX, Cv * IN / (2 * Math.PI * B * IN));
      const R = Math.max(B * IN, rMinAt(s) * 1.02), roll = side * 12 * deg;
      straight(Math.max(12 * IN, Math.abs(s) / SLOPE_RATE), { slope: s, roll }); arc(A * 2 * Math.PI, R, side, { slope: s, roll });
      straight(Math.max(24 * IN, Math.abs(s) / SLOPE_RATE + 8 * IN));
    } else if (k === 'slalom') {
      const h = 30 * deg, R = B * IN;                         // demi-virages aux bouts : la route repart dans la meme direction
      for (let i = 0; i < A; i++) {
        const sgn = (i % 2 ? -1 : 1) * side, ang = i === 0 || i === A - 1 ? h : 2 * h;
        arc(ang, R, sgn, { roll: sgn * 8 * deg });
      }
      straight(rollIn(8 * deg));
    } else if (k === 'jump') {
      const n = steps(A * IN);
      straight(30 * IN);
      for (let i = 0; i < n; i++) st.push({ k: 0, dz: -B * IN / n, roll: 0, jump: 1 });
      straight(30 * IN);
    } else if (k === 'bumps') {
      const H = B * IN, L = Math.max(40 * IN, Math.PI * H / 0.24), m = steps(L);
      const f = s => H * (1 - Math.cos(2 * Math.PI * s / m)) / 2;
      for (let b = 0; b < A; b++) for (let i = 0; i < m; i++) st.push({ k: 0, dz: f(i + 1) - f(i), roll: 0 });
      straight(8 * IN);
    } else if (k === 'ramp') {                                // pente qui monte doucement, palier, puis se remet a plat
      // 2026-11-18 (« rampes enormement longues, en rouge ») : l'ancien calcul pas a pas depassait parfois la hauteur,
      // repartait vers le haut et ne s'arretait qu'au bout de 4 000 pas (16 km : 614 reglages sur 832). Profil direct :
      // pente 0 -> pic (SLOPE_RATE), palier, pic -> 0 ; pic abaisse si le denivele est trop petit pour la pente choisie ;
      // hauteur totale recalee exactement
      for (const v of rampProfile(A * IN, B / 100)) st.push({ k: 0, dz: piece.up * v, roll: 0 });
      straight(8 * IN);
    } else if (k === 'hairpin') {                             // demi-tour : courte entree, 180 deg, sortie (inclinaison lissee)
      straight(10 * IN);
      arc(Math.PI, A * IN, side, { roll: side * B * deg });
      straight(Math.max(16 * IN, rollIn(B * deg)));
    } else if (k === 'plunge') {                              // creux en U : descente, fond plat, remontee (meme profil)
      const prof = rampProfile(A * IN, B / 100);
      straight(8 * IN);
      for (const v of prof) st.push({ k: 0, dz: -v, roll: 0 });
      if (Cv > 0) straight(Cv * IN, { dz: 0 });
      for (const v of prof.slice().reverse()) st.push({ k: 0, dz: v, roll: 0 });
      straight(8 * IN);
    } else if (k === 'overpass') {
      // boucle a 270 deg : entree droite (plus longue que le rayon), le virage monte de B m, la sortie repasse au-dessus de
      // l'entree a angle droit (sans talus : la route du dessous reste degagee), puis continue en hauteur
      const R = A * IN, H = B * IN, W = S.width, roll = side * 8 * deg;
      const lead = R + W / 2 + 20 * IN, toCross = R, past = W / 2 + 30 * IN;
      const climbLen = 1.5 * Math.PI * R + Math.max(8 * IN, toCross - W / 2 - 12 * IN);
      const nArc = Math.max(2, Math.round(1.5 * Math.PI * R / STEP)), nClimb = Math.round(climbLen / STEP);
      const prof = rampProfile(H, Math.min(SLOPE_MAX, 2 * H / climbLen));
      const dzAt = i => { const j = Math.round(i * prof.length / nClimb); return j < prof.length ? prof[j] * prof.length / nClimb : 0; };
      straight(lead, { dz: 0 });
      let i = 0;
      for (let a = 0; a < nArc; a++, i++) st.push({ k: side * 1.5 * Math.PI / (nArc * STEP), dz: dzAt(i), roll, noTalus: a > nArc * 0.6 });
      for (let e = steps(toCross + past); e > 0; e--, i++) st.push({ k: 0, dz: dzAt(i), roll: 0, noTalus: 1 });
      const sum = st.reduce((a, x) => a + (x.dz || 0), 0), fix = H / (sum || 1);   // hauteur exacte
      for (const x of st) if (x.dz) x.dz *= fix;
    } else straight(A * IN);
    return st;
  }
  // points de la piece depuis le bout de la route ; err : raison du refus (rien n'est pose)
  function piecePoints() {
    const T = S.terrain, last = S.points[S.points.length - 1], pts = [];
    let x = last[0], y = last[1], yaw = S.yaw, slope = slopeOfEnd(), roll = S.roll || 0, err = '';
    // depart : le bord interieur de la piece rejoint celui du bout de route, son centre (remonte de la moitie du bord
    // releve) aussi, que ce bout vienne du paveur (bords symetriques) ou d'une piece
    let z = effZ(last) - S.width * Math.sin(Math.abs(roll)) / 2;
    const lo = S.groundZ - H_MIN, hi = S.groundZ + H_MAX;
    const m = S.width / 2 + 2 * (T?.cell || T_CELL);
    const steps = pieceSteps();
    if (piece.kind === 'hairpin' && 2 * pieceVal('hairpin', 'a') * IN < S.width + 6 * IN)
      err = `Épingle trop serrée pour une route de ${Math.round(S.width / IN)} m : rayon d'au moins ${Math.ceil((S.width / IN + 6) / 2)} m`;
    if (piece.kind === 'overpass' && pieceVal('overpass', 'a') * IN < S.width * 0.75)
      err = `Boucle trop serrée pour une route de ${Math.round(S.width / IN)} m : rayon d'au moins ${Math.ceil(S.width / IN * 0.75)} m`;
    // inclinaison des pieces sans profil impose (spirale, chicane...) : 2026-11-13, retour utilisateur « entree trop
    // raide, gros decalages entre les cotes » -> on raisonne sur la HAUTEUR du bord releve (largeur x sin inclinaison) :
    // elle ne varie pas de plus de 15 % de pente (passe avant puis arriere : rampes symetriques, retour a plat au bout),
    // puis lissage sur 7 pas (pas de cassure en haut ni en bas des rampes)
    if (!steps.some(e => e.rollAbs !== undefined)) {
      const n = steps.length, W = S.width, d = BANK_EDGE_SLOPE * STEP, u0 = W * Math.sin(roll);
      const u = steps.map(e => W * Math.sin(e.roll || 0));
      let prev = u0;
      for (let i = 0; i < n; i++) { u[i] = Math.max(prev - d, Math.min(prev + d, u[i])); prev = u[i]; }
      u[n - 1] = 0;                                         // a plat au bout (APRES la passe avant, qui le relevait)
      for (let i = n - 2; i >= 0; i--) u[i] = Math.max(u[i + 1] - d, Math.min(u[i + 1] + d, u[i]));
      steps.forEach((e, i) => {
        let s = 0;
        for (let j = i - 3; j <= i + 3; j++) s += j < 0 ? u0 : j >= n ? 0 : u[j];
        e.rollAbs = Math.asin(Math.max(-1, Math.min(1, s / 7 / W)));
      });
    }
    for (const e of steps) {
      yaw += e.k * STEP / 2; x += Math.cos(yaw) * STEP; y += Math.sin(yaw) * STEP; yaw += e.k * STEP / 2;
      if (e.dz !== undefined) { z += e.dz; slope = e.jump ? 0 : e.dz / STEP; }
      else { slope += Math.max(-SLOPE_RATE * STEP, Math.min(SLOPE_RATE * STEP, e.slope - slope)); z += slope * STEP; }
      if (e.rollAbs !== undefined) roll = e.rollAbs;
      else roll += Math.max(-ROLL_RATE * STEP, Math.min(ROLL_RATE * STEP, e.roll - roll));
      if (!err && Math.abs(e.k) > 1 / rMinAt(slope) + 1e-9) err = 'Virage trop serré pour cette pente : agrandis le rayon';
      if (!err && (z < lo || z > hi)) err = z > hi ? `Trop haut : la route ne peut pas dépasser ${H_MAX / IN} m au-dessus du sol de départ` : `Trop bas : la route ne peut pas descendre à plus de ${H_MIN / IN} m sous le sol de départ`;
      if (!err && T && (x < T.x0 + m || y < T.y0 + m || x > T.x0 + (T.n - 1) * T.cell - m || y > T.y0 + (T.n - 1) * T.cell - m)) err = 'La pièce sort du terrain : tourne le kart ou choisis-en une plus petite';
      const p = [x, y, z, S.width, e.jump ? 1 : 0];
      // inclinaison des pieces : bord interieur a hauteur de route, bord exterieur releve (pas de fosse a l'interieur)
      if (Math.abs(roll) > 1e-3) {
        const w2 = S.width / 2, up = Math.round(S.width * Math.sin(Math.abs(roll)));
        p.push(w2, w2, roll > 0 ? 0 : up, roll > 0 ? up : 0);
      }
      if (S.noTalus || e.noTalus) setNoTalus(p, true);
      pts.push(p);
    }
    return { pts, err };
  }
  const ghostMat = new THREE.LineBasicMaterial({ color: 0xffd400, depthTest: false, transparent: true });
  const ghost = new THREE.Line(new THREE.BufferGeometry(), ghostMat);
  ghost.renderOrder = 21; ghost.visible = false; group.add(ghost);
  let ghostKey = '';
  function updateGhost(force) {
    const show = S.active && S.mode === 'route' && S.routeTab === 'pieces' && !S.closed && !S.pickStart && S.points.length > 0;
    ghost.visible = show; if (!show) { ghostKey = ''; return; }
    const last = S.points[S.points.length - 1];
    const key = [S.points.length, last[0], last[1], last[2], S.yaw.toFixed(3), S.width, JSON.stringify(piece)].join('|');
    if (!force && key === ghostKey) return;
    ghostKey = key;
    const r = piecePoints(), v = [last[0], last[1], last[2] + 2 * IN];
    for (const p of r.pts) v.push(p[0], p[1], p[2] + 2 * IN);
    ghost.geometry.dispose(); ghost.geometry = new THREE.BufferGeometry();
    ghost.geometry.setAttribute('position', new THREE.Float32BufferAttribute(v, 3));
    ghostMat.color.set(r.err ? 0xff4040 : 0xffd400);
    const len = r.pts.length * STEP / IN, dh = r.pts.length ? (r.pts[r.pts.length - 1][2] - last[2]) / IN : 0;
    $('crpinfo').textContent = r.err || `≈ ${Math.round(len)} m de route${Math.abs(dh) >= 0.5 ? ` · ${dh > 0 ? '+' : ''}${Math.round(dh)} m de hauteur` : ''}`;
    $('crpinfo').style.color = r.err ? 'var(--err, #e55)' : '';
    $('crpgo').disabled = !!r.err;
  }
  function pieceUI() {
    const c = PIECES[piece.kind];
    for (const b of panel.querySelectorAll('[data-piece]')) b.classList.toggle('primary', b.dataset.piece === piece.kind);
    for (const w of ['a', 'b', 'c']) {
      const lab = $('crp' + w + 'lab'), inp = $('crp' + w), d = c[w];
      lab.style.display = d ? 'block' : 'none'; if (!d) continue;
      inp.min = d[1]; inp.max = d[2]; inp.step = d[3]; inp.value = pieceVal(piece.kind, w);
      $('crp' + w + 'name').textContent = d[0];
      $('crp' + w + 'v').textContent = `${(+inp.value).toLocaleString('fr')}${d[5]}`;
    }
    $('crpdirrow').style.display = c.dir ? 'flex' : 'none';
    $('crpvertrow').style.display = c.vert ? 'flex' : 'none';
    $('crpleft').classList.toggle('primary', piece.dir > 0); $('crpright').classList.toggle('primary', piece.dir < 0);
    $('crpup').classList.toggle('primary', piece.up > 0); $('crpdown').classList.toggle('primary', piece.up < 0);
    try { localStorage.setItem(PIECE_KEY, JSON.stringify(piece)); } catch (e) { /* sans importance */ }
    updateGhost(true);
  }
  function placePiece() {
    if (S.closed) { status('La boucle est fermée : recule (↓) pour rouvrir la route avant d\'ajouter une pièce', 'err'); return; }
    const r = piecePoints();
    if (r.err) { status(r.err, 'err'); return; }
    if (histTimer) histCommit();                              // modification toute fraiche : etape a part
    const n0 = S.points.length;
    for (const p of r.pts) {
      if (crossing(p)) { S.points.length = n0; status('La pièce croise la route à la même hauteur : monte ou descends avant (R / F), ou fais un pont', 'err'); return; }
      S.points.push(p);
    }
    S.paveFull = true; S.terrainDirty = true; S.back = 0;
    placeFromPoints(); rebuild(); saveDraft(); updateGhost(true);
    status(`Pièce posée : ${Math.round(r.pts.length * STEP / IN)} m de route`, 'ok');
  }
  for (const b of panel.querySelectorAll('[data-piece]')) b.onclick = () => { piece.kind = b.dataset.piece; pieceUI(); };
  // onglets de la colonne Route : Conduite / Pieces / Reglages (memorise) ; l'apercu jaune seulement sur l'onglet Pieces
  const ROUTE_TAB_KEY = 'ctr_creator_routetab';
  function setRouteTab(t) {
    S.routeTab = ['drive', 'pieces', 'set'].includes(t) ? t : 'drive';
    try { localStorage.setItem(ROUTE_TAB_KEY, S.routeTab); } catch (e) { /* sans importance */ }
    for (const [k, b, p] of [['drive', 'crrtdrive', 'crrpdrive'], ['pieces', 'crrtpieces', 'crrppieces'], ['set', 'crrtset', 'crrpset']]) {
      $(b).classList.toggle('primary', S.routeTab === k); $(p).hidden = S.routeTab !== k;
    }
    updateGhost(true);
  }
  $('crrtdrive').onclick = () => setRouteTab('drive');
  $('crrtpieces').onclick = () => setRouteTab('pieces');
  $('crrtset').onclick = () => setRouteTab('set');
  for (const w of ['a', 'b', 'c']) $('crp' + w).oninput = e => { (piece.v[piece.kind] ??= {})[w] = +e.target.value; pieceUI(); };
  $('crpleft').onclick = () => { piece.dir = 1; pieceUI(); };
  $('crpright').onclick = () => { piece.dir = -1; pieceUI(); };
  $('crpup').onclick = () => { piece.up = 1; pieceUI(); };
  $('crpdown').onclick = () => { piece.up = -1; pieceUI(); };
  $('crpgo').onclick = placePiece;
  $('crrandom').onclick = () => openRandomDialog();
  pieceUI();
  setRouteTab((() => { try { return localStorage.getItem(ROUTE_TAB_KEY); } catch (e) { return null; } })());

  // ---- piste aleatoire a partir d'un code (2026-11-13) ----------------------------------------------------------------
  // code « <theme><longueur><difficulte>-<graine> » (ex. 3MN-K7Q2ZP) : theme = rang dans la liste des themes (les
  // nouveaux sont ajoutes a la FIN, les codes restent valables), C / M / L = courte / moyenne / longue, F / N / D =
  // facile / normale / difficile, graine en base 36. Meme code = meme piste (trace, relief, peinture, decor, eau).
  // m : longueur visee (2026-11-13 : plus longues qu'au debut, 1,3 / 1,9 / 2,6 km ; X = tres longue)
  const RND_LEN = { C: 1800, M: 2600, L: 3400, X: 4200 };
  // RND_GAME_SHAPES:BEGIN (ecrit par editor/make_rnd_shapes.py : traces des pistes du jeu vus de dessus, 48 points,
  // taille 1, c = croisements de la piste avec elle-meme ; ne pas modifier a la main)
  const RND_GAME_SHAPES = [
    { t: 'Crash Cove', c: 0, p: [0.170,-0.060,0.174,-0.005,0.183,0.049,0.193,0.103,0.200,0.157,0.199,0.212,0.194,0.267,0.190,0.322,0.189,0.377,0.219,0.405,0.195,0.442,0.151,0.474,0.102,0.498,0.047,0.500,-0.003,0.482,-0.029,0.436,-0.051,0.401,-0.094,0.368,-0.149,0.367,-0.198,0.345,-0.217,0.300,-0.222,0.245,-0.240,0.220,-0.229,0.166,-0.222,0.112,-0.221,0.057,-0.221,0.002,-0.222,-0.053,-0.223,-0.108,-0.218,-0.162,-0.200,-0.213,-0.175,-0.262,-0.150,-0.311,-0.130,-0.362,-0.105,-0.410,-0.065,-0.448,-0.017,-0.473,0.033,-0.495,0.088,-0.500,0.141,-0.495,0.191,-0.473,0.221,-0.428,0.239,-0.378,0.240,-0.323,0.235,-0.269,0.218,-0.217,0.199,-0.165,0.181,-0.113] },
    { t: 'Roos Tubes', c: 1, p: [-0.034,-0.440,-0.023,-0.384,-0.021,-0.326,-0.022,-0.269,-0.022,-0.211,-0.012,-0.155,0.021,-0.108,0.059,-0.066,0.097,-0.023,0.125,0.027,0.141,0.083,0.138,0.140,0.112,0.190,0.082,0.239,0.054,0.290,0.035,0.344,0.033,0.401,0.061,0.450,0.104,0.486,0.159,0.500,0.214,0.485,0.257,0.448,0.281,0.397,0.280,0.340,0.256,0.288,0.221,0.242,0.180,0.201,0.139,0.161,0.098,0.120,0.059,0.079,0.018,0.038,-0.030,0.009,-0.084,0.013,-0.133,0.043,-0.188,0.053,-0.240,0.028,-0.267,-0.021,-0.277,-0.077,-0.280,-0.135,-0.281,-0.193,-0.280,-0.250,-0.279,-0.308,-0.275,-0.365,-0.258,-0.420,-0.228,-0.468,-0.184,-0.500,-0.128,-0.499,-0.075,-0.480] },
    { t: 'Mystery Caves', c: 0, p: [-0.060,-0.500,-0.026,-0.450,0.008,-0.401,0.042,-0.351,0.077,-0.301,0.120,-0.259,0.173,-0.232,0.233,-0.223,0.293,-0.221,0.349,-0.203,0.372,-0.150,0.350,-0.095,0.306,-0.053,0.262,-0.013,0.205,0.006,0.145,0.010,0.086,0.023,0.036,0.056,-0.007,0.098,-0.022,0.155,-0.031,0.214,-0.066,0.261,-0.106,0.306,-0.141,0.355,-0.154,0.414,-0.175,0.468,-0.228,0.496,-0.285,0.500,-0.335,0.469,-0.362,0.416,-0.372,0.357,-0.364,0.298,-0.327,0.252,-0.282,0.212,-0.242,0.167,-0.230,0.109,-0.233,0.049,-0.271,0.005,-0.312,-0.039,-0.334,-0.094,-0.333,-0.153,-0.312,-0.209,-0.270,-0.252,-0.230,-0.296,-0.209,-0.351,-0.195,-0.410,-0.169,-0.463,-0.120,-0.496] },
    { t: 'Sewer Speedway', c: 0, p: [-0.034,-0.498,-0.107,-0.497,-0.173,-0.467,-0.231,-0.424,-0.281,-0.370,-0.312,-0.307,-0.291,-0.246,-0.241,-0.193,-0.204,-0.132,-0.178,-0.064,-0.135,-0.005,-0.080,0.044,-0.033,0.097,-0.028,0.169,-0.055,0.236,-0.124,0.248,-0.197,0.257,-0.266,0.280,-0.291,0.342,-0.289,0.414,-0.241,0.464,-0.183,0.490,-0.110,0.493,-0.037,0.496,0.036,0.499,0.109,0.500,0.165,0.460,0.184,0.389,0.188,0.316,0.208,0.247,0.255,0.193,0.292,0.159,0.312,0.118,0.287,0.053,0.235,0.003,0.167,-0.013,0.099,-0.030,0.044,-0.078,0.009,-0.141,0.020,-0.207,0.079,-0.250,0.137,-0.294,0.192,-0.343,0.215,-0.407,0.176,-0.462,0.114,-0.494,0.041,-0.500,-0.032,-0.499] },
    { t: 'Slide Coliseum', c: 0, p: [0.099,0.468,0.001,0.469,-0.097,0.470,-0.135,0.398,-0.066,0.328,-0.033,0.240,-0.101,0.176,-0.189,0.209,-0.265,0.270,-0.358,0.263,-0.388,0.178,-0.340,0.093,-0.280,0.017,-0.271,-0.077,-0.340,-0.145,-0.432,-0.171,-0.500,-0.230,-0.454,-0.303,-0.357,-0.313,-0.286,-0.373,-0.276,-0.470,-0.202,-0.454,-0.160,-0.376,-0.075,-0.329,0.014,-0.290,0.059,-0.208,0.009,-0.130,-0.084,-0.098,-0.108,-0.016,-0.031,0.017,0.035,-0.041,0.099,-0.116,0.184,-0.161,0.281,-0.162,0.372,-0.126,0.445,-0.061,0.500,0.018,0.500,0.116,0.446,0.179,0.351,0.166,0.332,0.074,0.270,0.013,0.174,0.024,0.110,0.097,0.098,0.191,0.162,0.264,0.190,0.353,0.184,0.450] },
    { t: 'Turbo Track', c: 0, p: [0.153,-0.295,0.228,-0.230,0.302,-0.163,0.375,-0.095,0.441,-0.021,0.484,0.067,0.489,0.165,0.484,0.265,0.463,0.362,0.378,0.406,0.280,0.422,0.181,0.429,0.083,0.446,-0.012,0.476,-0.110,0.492,-0.209,0.500,-0.309,0.496,-0.403,0.470,-0.471,0.407,-0.488,0.310,-0.487,0.211,-0.489,0.111,-0.485,0.012,-0.418,-0.052,-0.322,-0.058,-0.248,0.005,-0.202,0.093,-0.188,0.192,-0.180,0.219,-0.152,0.301,-0.132,0.213,-0.118,0.179,-0.062,0.141,-0.046,0.235,-0.042,0.276,0.023,0.287,0.022,0.188,0.032,0.089,0.039,-0.010,0.026,-0.108,-0.024,-0.193,-0.091,-0.267,-0.155,-0.343,-0.185,-0.436,-0.128,-0.500,-0.036,-0.493,0.051,-0.448,0.123,-0.378] },
    { t: 'Coco Park', c: 0, p: [0.234,-0.048,0.234,0.007,0.234,0.062,0.234,0.116,0.234,0.171,0.231,0.226,0.217,0.278,0.177,0.314,0.125,0.331,0.073,0.347,0.023,0.370,-0.020,0.403,-0.057,0.443,-0.098,0.479,-0.148,0.500,-0.200,0.484,-0.229,0.440,-0.233,0.386,-0.234,0.331,-0.231,0.296,-0.222,0.242,-0.202,0.191,-0.172,0.145,-0.139,0.102,-0.109,0.056,-0.097,0.004,-0.107,-0.050,-0.136,-0.096,-0.170,-0.139,-0.200,-0.185,-0.220,-0.236,-0.230,-0.289,-0.234,-0.344,-0.233,-0.399,-0.223,-0.452,-0.187,-0.492,-0.133,-0.500,-0.085,-0.479,-0.049,-0.438,-0.017,-0.394,0.020,-0.353,0.064,-0.320,0.113,-0.296,0.163,-0.276,0.205,-0.241,0.228,-0.193,0.233,-0.139,0.234,-0.084] },
    { t: 'Tiger Temple', c: 0, p: [-0.158,0.126,-0.216,0.130,-0.269,0.153,-0.308,0.196,-0.344,0.241,-0.397,0.260,-0.455,0.255,-0.490,0.220,-0.497,0.165,-0.500,0.107,-0.500,0.048,-0.494,-0.010,-0.461,-0.053,-0.404,-0.061,-0.349,-0.047,-0.312,-0.002,-0.274,0.042,-0.229,0.079,-0.171,0.085,-0.113,0.085,-0.054,0.084,0.004,0.084,0.062,0.084,0.120,0.082,0.174,0.062,0.210,0.017,0.238,-0.034,0.257,-0.089,0.263,-0.147,0.281,-0.202,0.323,-0.240,0.377,-0.260,0.433,-0.247,0.476,-0.212,0.500,-0.161,0.498,-0.104,0.469,-0.054,0.434,-0.007,0.397,0.038,0.355,0.078,0.307,0.110,0.250,0.123,0.192,0.125,0.134,0.125,0.075,0.126,0.017,0.125,-0.041,0.125,-0.100,0.125] },
    { t: 'Dingo Canyon', c: 0, p: [0.021,0.486,0.083,0.498,0.146,0.500,0.209,0.498,0.272,0.493,0.329,0.469,0.369,0.423,0.378,0.361,0.344,0.309,0.290,0.279,0.228,0.269,0.165,0.263,0.139,0.209,0.123,0.148,0.113,0.085,0.109,0.022,0.109,-0.041,0.112,-0.104,0.108,-0.166,0.078,-0.220,0.046,-0.274,0.028,-0.334,0.018,-0.396,0.006,-0.458,-0.035,-0.500,-0.098,-0.495,-0.158,-0.477,-0.220,-0.487,-0.279,-0.492,-0.311,-0.442,-0.329,-0.381,-0.351,-0.322,-0.373,-0.263,-0.378,-0.203,-0.359,-0.143,-0.329,-0.088,-0.293,-0.036,-0.274,-0.042,-0.281,0.021,-0.298,0.082,-0.305,0.144,-0.286,0.204,-0.253,0.257,-0.213,0.306,-0.174,0.355,-0.129,0.399,-0.079,0.438,-0.027,0.474] },
    { t: 'Blizzard Bluff', c: 0, p: [0.280,0.207,0.273,0.279,0.265,0.351,0.257,0.424,0.207,0.470,0.146,0.500,0.085,0.461,0.046,0.402,0.016,0.336,-0.023,0.275,-0.086,0.244,-0.144,0.284,-0.199,0.332,-0.254,0.379,-0.310,0.393,-0.367,0.349,-0.408,0.289,-0.421,0.243,-0.405,0.174,-0.354,0.122,-0.310,0.065,-0.285,-0.003,-0.279,-0.075,-0.282,-0.147,-0.304,-0.217,-0.323,-0.287,-0.311,-0.352,-0.266,-0.409,-0.200,-0.413,-0.135,-0.382,-0.074,-0.342,-0.014,-0.301,0.057,-0.298,0.114,-0.341,0.166,-0.392,0.218,-0.443,0.270,-0.494,0.339,-0.500,0.397,-0.464,0.421,-0.404,0.407,-0.333,0.368,-0.272,0.327,-0.212,0.291,-0.149,0.289,-0.077,0.304,-0.006,0.312,0.065,0.293,0.135] },
    { t: 'Dragon Mines', c: 1, p: [-0.057,-0.388,-0.057,-0.309,-0.055,-0.229,-0.061,-0.149,-0.070,-0.070,-0.078,0.009,-0.043,0.078,0.035,0.084,0.109,0.059,0.168,0.005,0.237,-0.028,0.314,-0.009,0.382,0.031,0.450,0.073,0.472,0.124,0.460,0.192,0.406,0.249,0.386,0.325,0.364,0.402,0.310,0.457,0.233,0.468,0.161,0.434,0.092,0.395,0.032,0.343,-0.035,0.302,-0.110,0.285,-0.175,0.331,-0.237,0.381,-0.286,0.441,-0.258,0.500,-0.193,0.467,-0.218,0.401,-0.284,0.355,-0.329,0.293,-0.343,0.215,-0.348,0.136,-0.349,0.056,-0.371,-0.020,-0.407,-0.091,-0.435,-0.139,-0.472,-0.209,-0.462,-0.286,-0.402,-0.335,-0.337,-0.381,-0.282,-0.438,-0.220,-0.486,-0.143,-0.500,-0.074,-0.464] },
    { t: 'Cortex Castle', c: 1, p: [-0.239,-0.159,-0.239,-0.053,-0.288,0.012,-0.394,0.013,-0.442,0.079,-0.442,0.186,-0.443,0.292,-0.418,0.380,-0.318,0.397,-0.293,0.496,-0.200,0.500,-0.182,0.397,-0.076,0.391,-0.068,0.286,-0.068,0.179,0.010,0.147,0.116,0.140,0.135,0.042,0.136,-0.064,0.186,-0.125,0.273,-0.148,0.228,-0.233,0.204,-0.329,0.204,-0.435,0.262,-0.500,0.368,-0.500,0.410,-0.418,0.440,-0.323,0.436,-0.229,0.411,-0.134,0.443,-0.035,0.388,0.044,0.288,0.018,0.242,0.092,0.242,0.199,0.240,0.305,0.235,0.411,0.132,0.420,0.038,0.400,0.034,0.293,0.034,0.187,0.035,0.080,0.036,-0.026,0.035,-0.133,0.035,-0.239,-0.053,-0.261,-0.159,-0.261,-0.237,-0.228] },
    { t: 'Inferno Island', c: 0, p: [0.109,-0.399,0.136,-0.343,0.163,-0.288,0.197,-0.238,0.233,-0.189,0.260,-0.134,0.287,-0.079,0.286,-0.021,0.259,0.033,0.226,0.084,0.202,0.140,0.193,0.158,0.182,0.195,0.179,0.256,0.176,0.317,0.176,0.378,0.166,0.437,0.125,0.481,0.068,0.500,0.007,0.496,-0.049,0.472,-0.099,0.438,-0.158,0.423,-0.216,0.403,-0.265,0.368,-0.287,0.313,-0.284,0.255,-0.258,0.200,-0.228,0.147,-0.194,0.096,-0.167,0.041,-0.148,-0.017,-0.148,-0.077,-0.155,-0.106,-0.179,-0.163,-0.203,-0.219,-0.227,-0.275,-0.244,-0.334,-0.239,-0.390,-0.207,-0.442,-0.149,-0.460,-0.090,-0.477,-0.031,-0.493,0.029,-0.500,0.076,-0.473,0.101,-0.417,0.125,-0.361,0.134,-0.342] },
    { t: 'Jungle Boogie', c: 1, p: [-0.003,0.110,0.019,0.051,0.026,-0.011,0.029,-0.074,0.033,-0.137,0.042,-0.198,0.064,-0.257,0.091,-0.314,0.108,-0.374,0.107,-0.434,0.061,-0.477,0.001,-0.496,-0.057,-0.500,-0.113,-0.470,-0.154,-0.424,-0.188,-0.370,-0.219,-0.316,-0.252,-0.262,-0.276,-0.205,-0.284,-0.143,-0.247,-0.098,-0.201,-0.055,-0.163,-0.004,-0.120,0.041,-0.140,0.096,-0.170,0.152,-0.197,0.209,-0.210,0.270,-0.192,0.328,-0.142,0.348,-0.113,0.293,-0.057,0.281,0.006,0.277,0.069,0.277,0.131,0.275,0.194,0.281,0.249,0.308,0.282,0.359,0.284,0.421,0.250,0.473,0.194,0.500,0.134,0.483,0.104,0.458,0.075,0.403,0.049,0.345,0.022,0.288,-0.001,0.230,-0.017,0.169] },
    { t: 'Tiny Temple', c: 0, p: [-0.107,0.330,-0.144,0.277,-0.189,0.231,-0.251,0.219,-0.305,0.220,-0.369,0.224,-0.422,0.199,-0.433,0.137,-0.405,0.081,-0.358,0.036,-0.305,0.001,-0.241,-0.005,-0.177,-0.004,-0.119,-0.030,-0.071,-0.072,-0.036,-0.124,-0.035,-0.189,-0.033,-0.253,-0.026,-0.317,0.002,-0.374,0.046,-0.420,0.096,-0.448,0.144,-0.490,0.207,-0.500,0.271,-0.490,0.334,-0.476,0.392,-0.449,0.433,-0.403,0.427,-0.341,0.415,-0.278,0.420,-0.214,0.431,-0.151,0.409,-0.092,0.362,-0.048,0.324,0.001,0.320,0.065,0.316,0.103,0.299,0.165,0.257,0.213,0.205,0.249,0.156,0.291,0.145,0.352,0.148,0.416,0.112,0.466,0.057,0.500,0.001,0.490,-0.039,0.439,-0.073,0.384] },
    { t: 'Meteor Gorge', c: 0, p: [-0.061,-0.308,0.024,-0.313,0.102,-0.347,0.168,-0.400,0.199,-0.478,0.254,-0.500,0.336,-0.496,0.411,-0.463,0.447,-0.389,0.449,-0.303,0.448,-0.218,0.446,-0.133,0.446,-0.047,0.447,0.038,0.448,0.123,0.452,0.209,0.449,0.294,0.412,0.367,0.339,0.409,0.268,0.454,0.199,0.500,0.116,0.492,0.048,0.441,-0.024,0.415,-0.095,0.408,-0.178,0.390,-0.240,0.333,-0.252,0.251,-0.203,0.186,-0.123,0.157,-0.043,0.129,0.029,0.084,0.052,0.005,0.009,-0.066,-0.038,-0.093,-0.121,-0.092,-0.181,-0.034,-0.225,0.039,-0.295,0.083,-0.378,0.075,-0.443,0.022,-0.452,-0.061,-0.420,-0.140,-0.377,-0.214,-0.332,-0.286,-0.286,-0.357,-0.211,-0.388,-0.135,-0.351] },
    { t: 'Barin Ruins', c: 1, p: [-0.028,0.343,0.036,0.367,0.099,0.391,0.147,0.362,0.182,0.304,0.243,0.279,0.307,0.257,0.363,0.219,0.415,0.181,0.478,0.199,0.500,0.260,0.476,0.320,0.419,0.357,0.352,0.357,0.301,0.312,0.278,0.249,0.263,0.183,0.233,0.124,0.177,0.086,0.119,0.050,0.061,0.014,0.038,-0.001,0.010,-0.016,-0.049,-0.050,-0.100,-0.094,-0.132,-0.152,-0.105,-0.211,-0.070,-0.269,-0.073,-0.335,-0.118,-0.385,-0.184,-0.391,-0.231,-0.353,-0.267,-0.295,-0.293,-0.232,-0.319,-0.173,-0.343,-0.110,-0.372,-0.048,-0.418,-0.000,-0.477,0.035,-0.500,0.097,-0.479,0.157,-0.420,0.189,-0.357,0.215,-0.295,0.244,-0.260,0.298,-0.225,0.352,-0.159,0.371,-0.094,0.355] },
    { t: 'Deep Sea Driving', c: 1, p: [0.210,0.499,0.117,0.471,0.023,0.451,-0.072,0.444,-0.156,0.491,-0.247,0.490,-0.275,0.401,-0.273,0.305,-0.272,0.269,-0.238,0.181,-0.205,0.090,-0.162,0.009,-0.074,-0.031,0.006,-0.060,0.017,-0.150,-0.055,-0.207,-0.152,-0.208,-0.248,-0.202,-0.341,-0.223,-0.402,-0.295,-0.411,-0.391,-0.356,-0.466,-0.266,-0.496,-0.170,-0.500,-0.091,-0.446,-0.027,-0.375,0.042,-0.309,0.132,-0.322,0.182,-0.403,0.239,-0.442,0.327,-0.425,0.340,-0.333,0.308,-0.241,0.283,-0.148,0.255,-0.055,0.262,0.037,0.350,0.064,0.411,0.004,0.392,-0.084,0.306,-0.112,0.235,-0.051,0.237,0.045,0.297,0.115,0.386,0.150,0.409,0.238,0.387,0.332,0.357,0.424,0.303,0.500] },
    { t: 'Out of Time', c: 1, p: [0.289,0.232,0.259,0.128,0.245,0.024,0.282,-0.078,0.274,-0.066,0.318,-0.165,0.319,-0.267,0.228,-0.291,0.145,-0.220,0.045,-0.186,-0.051,-0.226,-0.004,-0.301,0.098,-0.326,0.062,-0.409,-0.044,-0.422,-0.141,-0.374,-0.177,-0.272,-0.202,-0.167,-0.220,-0.061,-0.281,0.028,-0.347,0.114,-0.423,0.192,-0.500,0.267,-0.477,0.350,-0.392,0.310,-0.348,0.212,-0.284,0.125,-0.218,0.038,-0.144,-0.041,-0.045,-0.059,0.019,0.011,-0.027,0.102,-0.105,0.177,-0.163,0.269,-0.172,0.375,-0.091,0.422,0.002,0.381,0.015,0.276,0.051,0.176,0.149,0.157,0.245,0.118,0.274,0.016,0.362,-0.022,0.425,0.056,0.464,0.157,0.500,0.258,0.441,0.340,0.344,0.325] },
    { t: 'Clockwork Wumpa', c: 1, p: [-0.245,0.215,-0.246,0.315,-0.247,0.414,-0.214,0.490,-0.115,0.493,-0.029,0.450,0.061,0.425,0.134,0.492,0.232,0.500,0.278,0.434,0.278,0.335,0.291,0.240,0.348,0.160,0.316,0.071,0.277,-0.016,0.219,-0.071,0.119,-0.068,0.020,-0.072,-0.005,-0.161,-0.072,-0.205,-0.148,-0.145,-0.247,-0.146,-0.346,-0.150,-0.377,-0.221,-0.325,-0.282,-0.255,-0.353,-0.160,-0.370,-0.081,-0.371,0.010,-0.373,0.108,-0.380,0.138,-0.467,0.217,-0.500,0.316,-0.496,0.375,-0.442,0.377,-0.343,0.344,-0.259,0.246,-0.254,0.148,-0.247,0.128,-0.157,0.128,-0.057,0.127,0.042,0.127,0.142,0.126,0.241,0.089,0.315,-0.010,0.320,-0.109,0.316,-0.131,0.232,-0.178,0.169] },
    { t: 'Assembly Lane', c: 1, p: [0.500,-0.119,0.498,-0.005,0.486,0.108,0.439,0.210,0.340,0.259,0.242,0.261,0.143,0.210,0.193,0.119,0.296,0.070,0.377,-0.008,0.360,-0.115,0.254,-0.142,0.145,-0.116,0.124,-0.005,0.040,0.034,0.018,-0.067,-0.016,-0.174,-0.043,-0.281,-0.046,-0.395,-0.120,-0.467,-0.231,-0.468,-0.343,-0.459,-0.412,-0.376,-0.361,-0.298,-0.337,-0.199,-0.334,-0.085,-0.332,0.029,-0.347,0.128,-0.421,0.171,-0.425,0.259,-0.500,0.321,-0.500,0.434,-0.418,0.468,-0.305,0.461,-0.294,0.355,-0.292,0.241,-0.202,0.206,-0.088,0.206,0.026,0.200,0.114,0.140,0.123,0.028,0.120,-0.086,0.083,-0.191,0.096,-0.297,0.197,-0.341,0.310,-0.339,0.421,-0.313,0.492,-0.232] },
    { t: 'Hyper Spaceway', c: 0, p: [-0.030,0.153,-0.031,0.047,-0.042,-0.058,-0.042,-0.164,-0.042,-0.269,-0.037,-0.375,-0.031,-0.403,0.052,-0.431,0.158,-0.435,0.263,-0.439,0.361,-0.427,0.421,-0.340,0.481,-0.253,0.500,-0.150,0.476,-0.049,0.382,-0.008,0.335,0.062,0.420,0.060,0.440,0.152,0.423,0.257,0.406,0.353,0.390,0.358,0.285,0.378,0.181,0.397,0.077,0.417,-0.026,0.436,-0.131,0.456,-0.216,0.430,-0.285,0.357,-0.280,0.265,-0.338,0.199,-0.391,0.107,-0.437,0.013,-0.456,-0.090,-0.500,-0.187,-0.456,-0.281,-0.394,-0.366,-0.327,-0.448,-0.250,-0.456,-0.227,-0.367,-0.239,-0.262,-0.252,-0.157,-0.211,-0.061,-0.165,0.035,-0.119,0.130,-0.073,0.225,-0.031,0.185,-0.031,0.140] }
  ];
  // RND_GAME_SHAPES:END
  const RND_DIFF = {
    F: { amp: 0.22, harm: 3, hill: 4, bank: 8, jumps: 0, width: 70 },
    N: { amp: 0.32, harm: 4, hill: 10, bank: 13, jumps: 1, width: 60 },
    D: { amp: 0.42, harm: 5, hill: 20, bank: 18, jumps: 2, width: 50 },
  };
  const mulberry = seed => {
    let s = seed >>> 0;
    return () => { s = (s + 0x6D2B79F5) | 0; let t = Math.imul(s ^ (s >>> 15), 1 | s); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  };
  // pieces choisies (2026-11-14) : bits chicanes 1, bosses 2, spirales 4, sauts 8, virages releves 16. Par defaut celles
  // de la difficulte (code sans suffixe, comme avant : les anciens codes redonnent la meme piste) ; sinon suffixe
  // « -<masque base 32> » (ex. 3MN-K7Q2ZP-B)
  const RND_PIECES = [['chic', 1, 'Chicanes'], ['bump', 2, 'Bosses'], ['spiral', 4, 'Spirales'], ['jump', 8, 'Sauts'], ['bank', 16, 'Virages relevés'],
                      ['cut', 32, 'Canyons et remblais'], ['plunge', 64, 'Plongeons'], ['hairpin', 128, 'Épingles'],
                      ['earth', 256, 'Ponts de terre et tunnels']];
  const RND_MASK_DEF = { F: 51, N: 63, D: 63 };            // facile : virages releves aussi (2026-11-14 ; 35 avant)
  // plongeons et epingles (2026-11-23) : coches de base sur les NOUVEAUX codes (suffixe de masque) ; un code sans suffixe
  // redonne la meme piste qu'avant (sans eux)
  const RND_NEW = 64 | 128 | 256, rndDefMask = d => RND_MASK_DEF[d] | RND_NEW;
  // second theme (2026-11-20) : suffixe « +<theme base 36> » (ex. 1MN-QOIMRM+5) ; sans suffixe : un seul theme (anciens codes)
  const rndCode = (kitIdx, len, diff, seed, mask, kit2) =>
    `${kitIdx.toString(36).toUpperCase()}${len}${diff}-${(seed >>> 0).toString(36).toUpperCase().padStart(6, '0').slice(-6)}`
    + (mask !== undefined && mask !== RND_MASK_DEF[diff] ? '-' + mask.toString(32).toUpperCase() : '')
    + (Number.isInteger(kit2) && kit2 !== kitIdx ? '+' + kit2.toString(36).toUpperCase() : '');
  function parseRndCode(code) {
    const m = /^\s*([0-9A-Z])([CMLX])([FND])-([0-9A-Z]{1,6})(?:-([0-9A-V]{1,2}))?(?:\+([0-9A-Z]))?\s*$/i.exec(code || '');
    if (!m) return null;
    const c = { kit: parseInt(m[1], 36), len: m[2].toUpperCase(), diff: m[3].toUpperCase(), seed: parseInt(m[4], 36) >>> 0 };
    if (m[5]) { const k = parseInt(m[5], 32); if (k !== RND_MASK_DEF[c.diff]) c.mask = k; }
    if (m[6]) { const k2 = parseInt(m[6], 36); if (k2 !== c.kit) c.kit2 = k2; }
    return c;
  }
  // aire signee d'un trace ferme (> 0 : sens trigonometrique)
  const loopArea = P => P.reduce((a, p, i) => { const q = P[(i + 1) % P.length]; return a + p[0] * q[1] - q[0] * p[1]; }, 0);
  // rayon (pouces) du cercle passant par a, b, c (Infinity : alignes)
  const circR = (a, b, c) => {
    const ab = Math.hypot(b[0] - a[0], b[1] - a[1]), bc = Math.hypot(c[0] - b[0], c[1] - b[1]), ca = Math.hypot(a[0] - c[0], a[1] - c[1]);
    const cr = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
    return Math.abs(cr) < 1e-9 ? Infinity : ab * bc * ca / (2 * Math.abs(cr));
  };
  // barre de progression de la piste aleatoire (2026-11-14) : meme fenetre que l'ouverture de la Creation (#crload),
  // titre change le temps de la creation ; pct null = fin
  async function rndProgress(pct, msg) {
    const g = id => document.getElementById(id);                  // hors du panneau (index.html)
    const box = g('crload'), fill = g('crloadfill'), title = box?.querySelector('.t');
    if (!box) return;
    if (pct == null) {
      fill.style.width = '100%';
      await new Promise(r => setTimeout(r, 200));
      box.classList.remove('on'); fill.style.width = '0';
      if (title.dataset.rnd) { title.textContent = title.dataset.rnd; delete title.dataset.rnd; }
      return;
    }
    if (!title.dataset.rnd) { title.dataset.rnd = title.textContent; title.textContent = 'Création de la piste aléatoire…'; }
    box.classList.add('on'); g('crloadmsg').textContent = msg; fill.style.width = pct + '%';
    await new Promise(r => requestAnimationFrame(() => setTimeout(r, 30)));   // laisse la barre s'afficher
  }
  async function randomTrack(c, opts = {}, step = async () => {}) {
    await step(5, 'Tracé de la route…');
    const rnd = mulberry(c.seed ^ 0x9E3779B9), D = RND_DIFF[c.diff], kits = [...$('crkit').options].map(o => o.value);
    const kit = kits[c.kit % kits.length], W = D.width * IN, T0 = S.terrain;
    const cx = T0.x0 + (T0.n - 1) * T0.cell / 2, cy = T0.y0 + (T0.n - 1) * T0.cell / 2;
    // 1. trace : courbe polaire r(t) > 0 (jamais de croisement), quelques ondulations au hasard, ellipse, rotation ;
    // ondulations reduites jusqu'a ce que le virage le plus serre passe (rayon mini du paveur, largeur de route)
    // deux passages de la route qui se touchent (2026-11-13, retour utilisateur 3LD-1A2B3C : « la route passe sur une
    // autre ») : points eloignes le long du trace (> 3 largeurs) a moins d'une largeur + 10 m ; H donne : accepte si
    // l'un passe au moins RND_CLEAR au-dessus de l'autre (pont)
    const RND_CLEAR = 9 * IN;
    function overlaps(A, H) {
      const N = A.length, far = Math.ceil(3 * W / STEP), lim = W + 10 * IN;
      for (let i = 0; i < N; i++) for (let j = i + far; j < N; j++) {
        if (N - (j - i) < far) break;
        if (Math.hypot(A[i][0] - A[j][0], A[i][1] - A[j][1]) < lim && (!H || Math.abs(H[i] - H[j]) < RND_CLEAR)) return true;
      }
      return false;
    }
    // forme du trace (2026-11-14, retour utilisateur « toujours un cercle vu de dessus ») : forme tiree au hasard (libre,
    // allongee, haricot, triangle, carre, goutte), quelques points de passage irreguliers autour du centre (jamais de
    // croisement : un rayon par direction), lisses en courbe (Catmull-Rom fermee). Trop marquee (virage trop serre ou
    // deux bouts qui se touchent) : adoucie peu a peu vers un cercle (s)
    // + « huit » (2026-11-14, demande utilisateur) : la route se croise une fois, un passage monte sur un pont au-dessus de
    // l'autre (crossProfile) ; s'il ne passe pas (virage trop serre, passages trop proches), forme libre a la place
    // + « jeu » (2026-11-14, demande utilisateur « inspire-toi des mini-cartes du jeu ») : trace d'une piste du jeu vu
    // de dessus (RND_GAME_SHAPES), miroir et rotation au hasard, un peu d'irregularite ; croisee une fois : pont comme le
    // huit ; virage trop serre : lissee peu a peu ; impossible : forme libre
    // + « anguleuse » et « épingles » (2026-11-16, retour utilisateur « manque de virages secs a plus de 90 degres,
    // souvent un rond ou un ovale ») : polygone irregulier (5 a 9 sommets, dont 1 a 3 rentrants pour « épingles ») dont
    // chaque coin est arrondi au rayon juste suffisant (lignes droites + virages serres), au lieu d'une courbe lisse
    // + « bloc » (voir blocPoly) : forme la plus frequente ; formes presque rondes (libre, goutte, triangle, carre...) rares
    const SHAPES = [['bloc', 0.6], ['jeu', 0.2], ['huit', 0.07], ['épingles', 0.08], ['anguleuse', 0.03], ['haricot', 0.02]];
    let pick = rnd(), shape = SHAPES[0][0];
    for (const [nm, w] of SHAPES) { if (pick < w) { shape = nm; break; } pick -= w; }
    if (opts.shape) shape = opts.shape;                            // essais (?crtest) seulement
    const tpl0 = RND_GAME_SHAPES[Math.min(RND_GAME_SHAPES.length - 1, Math.floor(rnd() * RND_GAME_SHAPES.length))], mirror = rnd() < 0.5 ? -1 : 1;
    const gameTpl = (opts.tpl && RND_GAME_SHAPES.find(s => s.t === opts.tpl)) || tpl0;   // opts.tpl : essais seulement
    if (opts.tpl) shape = 'jeu';
    let crossing = shape === 'huit' || (shape === 'jeu' && gameTpl.c === 1);
    const th0 = rnd() * 2 * Math.PI;
    const ex = shape === 'allongée' ? 1.6 + rnd() * 0.6 : 0.85 + rnd() * 0.35;
    const nz = (shape === 'libre' ? 0.38 : 0.14) * D.amp / 0.32;     // irregularite (plus en difficile)
    const crossRise = (13 + rnd() * 5) * IN;                        // huit : hauteur du pont au croisement
    const wrap = a => Math.atan2(Math.sin(a), Math.cos(a));
    let poly, K, ctrl, corner = false, rf = 1;
    // « bloc » (2026-11-16, retour utilisateur « toujours une base de rond vu de dessus, ennuyeux a jouer ») : les
    // autres formes tournent toutes autour d'un centre (presque convexes). Ici un amas de cases pousse au hasard sur une
    // grille (bras de preference : L, U, S, T, os, zigzag ; ni trou, ni cases qui ne se touchent que par un coin), son
    // contour devient le polygone, coins arrondis comme « anguleuse ». Taille des cases choisie pour que deux bords de
    // route restent a plus d'une largeur l'un de l'autre et que deux coins de suite (demi-tour) passent
    const blocPoly = () => {
      const needB = Math.max(R_MIN * 1.3, W * 0.7), cmin = Math.max(2.3 * needB, 2 * W);
      const Lw = RND_LEN[c.len] * IN;
      // perimetre d'un amas « en arbre » de M cases = 2M + 2 cotes ; M au plus ce que la taille mini permet
      const Mmax = Math.max(4, Math.floor((Lw / cmin - 2) / 2));
      for (let att = 0; att < 30; att++) {
        const M = Math.max(4, Mmax - Math.floor(rnd() * Math.min(3, Mmax - 3)) - Math.floor(att / 6));
        const on = new Set(['0,0']), has = (x, y) => on.has(x + ',' + y);
        const pinch = (x, y) => {                                   // 2x2 avec seulement deux cases en diagonale
          for (const [dx, dy] of [[0, 0], [-1, 0], [0, -1], [-1, -1]]) {
            const q = [[x + dx, y + dy], [x + dx + 1, y + dy], [x + dx, y + dy + 1], [x + dx + 1, y + dy + 1]]
              .map(([u, v]) => (u === x && v === y) || has(u, v));
            if ((q[0] && q[3] && !q[1] && !q[2]) || (q[1] && q[2] && !q[0] && !q[3])) return true;
          }
          return false;
        };
        const holes = () => {                                       // case vide enfermee ?
          let x0 = 1e9, x1 = -1e9, y0 = 1e9, y1 = -1e9;
          for (const s of on) { const [x, y] = s.split(',').map(Number); x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
          const seen = new Set([(x0 - 1) + ',' + (y0 - 1)]), st = [[x0 - 1, y0 - 1]];
          while (st.length) { const [x, y] = st.pop();
            for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) { const u = x + dx, v = y + dy, k = u + ',' + v;
              if (u < x0 - 1 || u > x1 + 1 || v < y0 - 1 || v > y1 + 1 || seen.has(k) || on.has(k)) continue; seen.add(k); st.push([u, v]); } }
          return seen.size + on.size < (x1 - x0 + 3) * (y1 - y0 + 3);
        };
        for (let g = 0; on.size < M && g < 400; g++) {
          const fr = new Map();                                    // cases voisines libres, ponderees : bras (1 voisin) d'abord
          for (const s of on) { const [x, y] = s.split(',').map(Number);
            for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) { const u = x + dx, v = y + dy, k = u + ',' + v;
              if (on.has(k) || fr.has(k)) continue;
              const nb = [[1, 0], [-1, 0], [0, 1], [0, -1]].filter(([a, b]) => has(u + a, v + b)).length;
              // bras qui s'eloignent du depart : formes plus ouvertes (plus de parties rentrantes)
              fr.set(k, nb === 1 ? 3 * (1 + 0.5 * Math.hypot(u, v)) : nb === 2 ? 0.15 : 0.02); } }
          let tot = 0; for (const w of fr.values()) tot += w;
          let pk = rnd() * tot, cell = null;
          for (const [k, w] of fr) { if (pk < w) { cell = k; break; } pk -= w; }
          if (!cell) break;
          const [x, y] = cell.split(',').map(Number);
          if (pinch(x, y)) continue;
          on.add(cell); if (holes()) on.delete(cell);
        }
        if (on.size < M) continue;
        // contour (sens trigo, interieur a gauche) : un seul cycle (ni trou ni pincement)
        const next = new Map();
        for (const s of on) { const [x, y] = s.split(',').map(Number);
          if (!has(x, y - 1)) next.set(x + ',' + y, [x + 1, y]);
          if (!has(x + 1, y)) next.set((x + 1) + ',' + y, [x + 1, y + 1]);
          if (!has(x, y + 1)) next.set((x + 1) + ',' + (y + 1), [x, y + 1]);
          if (!has(x - 1, y)) next.set(x + ',' + (y + 1), [x, y]); }
        const first = next.keys().next().value.split(',').map(Number), loop = [first];
        for (let p = next.get(first.join(',')); p && (p[0] !== first[0] || p[1] !== first[1]) && loop.length <= next.size; p = next.get(p.join(','))) loop.push(p);
        if (loop.length !== next.size) continue;
        const vs = loop.filter((p, i) => { const a = loop[(i - 1 + loop.length) % loop.length], b = loop[(i + 1) % loop.length];
          return (p[0] - a[0]) * (b[1] - p[1]) - (p[1] - a[1]) * (b[0] - p[0]) !== 0; });   // coins seulement
        if (vs.length < 6) continue;                                // rectangle (amas en ligne) : pas de partie rentrante
        // irregularite : etirement 0,8-1,25 et sommets bouges de +-0,12 case (les angles ne sont plus tous droits)
        const sx = 0.8 + rnd() * 0.45, sy = 1 / sx;
        let mx = 0, my = 0; for (const [x, y] of vs) { mx += x / vs.length; my += y / vs.length; }
        const pts = vs.map(([x, y]) => [(x - mx + (rnd() - 0.5) * 0.24) * sx, (y - my + (rnd() - 0.5) * 0.24) * sy]);
        let Lp = 0; for (let i = 0; i < pts.length; i++) Lp += Math.hypot(pts[(i + 1) % pts.length][0] - pts[i][0], pts[(i + 1) % pts.length][1] - pts[i][1]);
        if (Lw / Lp * Math.min(sx, sy) * 0.85 < cmin * 0.95) continue; // cases trop petites a cette longueur : moins de cases
        return pts;
      }
      return null;
    };
    const makeCtrl = () => {
      poly = { triangle: 3, 'carré': 4 }[shape] || 0;
      if (shape === 'bloc') {
        const pts = blocPoly();
        if (pts) { corner = true; K = pts.length; ctrl = pts.map(xy => ({ xy })); rf = 1 + rnd() * 0.3; return; }
        shape = 'épingles';                                         // amas impossible (piste tres courte) : epingles
      }
      corner = shape === 'anguleuse' || shape === 'épingles';
      if (corner) {                                                 // sommets du polygone (coins arrondis plus loin)
        // peu de sommets (4 a 7) : virages de 60 a 140 degres ; epingles : 6 a 9 sommets dont des rentrants profonds
        const ep = shape === 'épingles';
        const oneNotch = !ep && rnd() < 0.6;                        // anguleuse : 4-5 sommets, ou 5-6 dont 1 rentrant
        K = ep ? 6 + Math.floor(rnd() * 4) : (oneNotch ? 5 : 4) + Math.floor(rnd() * 2);
        const notch = new Set();
        if (ep || oneNotch) {                                  // sommets rentrants, jamais voisins (anguleuse : parfois 1)
          const nn = ep ? 1 + Math.floor(rnd() * Math.min(3, Math.floor(K / 2) - 1)) : 1;
          for (let t = 0; t < 20 && notch.size < nn; t++) { const k = Math.floor(rnd() * K);
            if (!notch.has(k) && !notch.has((k + 1) % K) && !notch.has((k - 1 + K) % K)) notch.add(k); }
        }
        ctrl = [];
        for (let k = 0; k < K; k++) {
          const th = th0 + 2 * Math.PI * (k + (rnd() - 0.5) * 0.6) / K;
          ctrl.push({ th, r: notch.has(k) ? (ep ? 0.12 + rnd() * 0.2 : 0.3 + rnd() * 0.2) : 0.65 + rnd() * 0.55 });
        }
        // rayon des coins : 1 a 1,4 x le minimum (un virage de 90 degres tient en 65 a 95 m ; elargi si ca ne passe pas)
        rf = 1 + rnd() * 0.4;
        return;
      }
      K = poly ? poly * 3 : shape === 'jeu' ? gameTpl.p.length / 2 : shape === 'huit' ? 16 : shape === 'libre' ? 7 + Math.floor(rnd() * 5) : 9 + Math.floor(rnd() * 4);
      const form = th => poly ? Math.cos(Math.PI / poly) / Math.cos(((((th - th0) % (2 * Math.PI / poly)) + 2 * Math.PI / poly) % (2 * Math.PI / poly)) - Math.PI / poly)
        : shape === 'haricot' ? 1 - 0.5 * Math.exp(-(wrap(th - th0) ** 2) / 0.25)
        : shape === 'goutte' ? 1 + 0.45 * Math.cos(th - th0) : 1;
      ctrl = [];
      // huit : largeur / longueur des boucles 0,55 a 0,8 (croisement a 57-77 degres ; plus larges, leurs bouts se
      // resserrent : rayon mini 33 m a 1,6 contre 85 m a 0,7 sur 1,8 km)
      const B = 0.55 + rnd() * 0.25;
      for (let k = 0; k < K; k++) {
        if (shape === 'jeu') {                                      // piste du jeu : point k, miroir, irregularite legere
          const j = 1 + (rnd() * 2 - 1) * nz * 0.25;
          ctrl.push({ xy: [gameTpl.p[2 * k] * mirror * 2 * j, gameTpl.p[2 * k + 1] * 2 * j] });
          continue;
        }
        if (shape === 'huit') {                                     // lemniscate de Gerono : x = sin t, y = sin t cos t
          const t = 2 * Math.PI * k / K, j = 1 + (rnd() * 2 - 1) * nz * 0.5;
          ctrl.push({ xy: [Math.sin(t) * j, Math.sin(t) * Math.cos(t) * B * j] });
          continue;
        }
        const th = th0 + 2 * Math.PI * (k + (poly ? 0 : (rnd() - 0.5) * 0.5)) / K;
        ctrl.push({ th, r: form(th) * (1 + (rnd() * 2 - 1) * nz) });
      }
    };
    makeCtrl();
    const rot = rnd() * 2 * Math.PI, need = Math.max(R_MIN * 1.3, W * 0.7);
    // huit : croisement = deux points eloignes le long du trace (plus d'un quart du tour) les plus proches ; profil du
    // pont (passage i) : palier sur 1,6 x (largeur + 10 m) de chaque cote, rampes a 9 % en moyenne
    const crossFlat = Math.ceil(1.6 * (W + 10 * IN) / STEP), crossRamp = Math.ceil(crossRise / 0.09 / STEP);
    function crossProfile(A) {
      const N = A.length, q = Math.floor(N / 4);
      let bi = -1, bj = -1, bd = Infinity;
      for (let i = 0; i < N; i++) for (let j = i + q; j < N; j++) {
        if (N - (j - i) < q) break;
        const d = Math.hypot(A[i][0] - A[j][0], A[i][1] - A[j][1]); if (d < bd) { bd = d; bi = i; bj = j; }
      }
      const prof = new Float64Array(N);
      for (let k = 0; k < N; k++) {
        const d = Math.min(Math.abs(k - bi), N - Math.abs(k - bi));
        prof[k] = d <= crossFlat ? crossRise : d < crossFlat + crossRamp ? crossRise * (1 - sstep(0, 1, (d - crossFlat) / crossRamp)) : 0;
      }
      return { i: bi, j: bj, prof };
    }
    let amp = 1, P = [];
    for (let tr = 0; tr < 40; tr++) {
      // impossible ici : « bloc » a la place (2026-11-16 ; « libre » avant, qui finissait souvent ronde)
      if ((shape === 'huit' || shape === 'jeu') && tr === 16) { shape = 'bloc'; crossing = false; makeCtrl(); amp = 1; }
      const ext = 1 + (ex - 1) * amp;
      const cp = ctrl.map(({ th, r, xy }) => {
        let x, y;
        if (xy) { x = xy[0]; y = xy[1]; }
        else { const rr = 1 + (r - 1) * amp; x = rr * Math.cos(th) * ext; y = rr * Math.sin(th) / ext; }
        return [x * Math.cos(rot) - y * Math.sin(rot), x * Math.sin(rot) + y * Math.cos(rot)]; });
      const raw = [];
      if (corner) {                                                // polygone : droites + coins arrondis (rayon rf x need)
        let Lp = 0; for (let k = 0; k < K; k++) Lp += Math.hypot(cp[(k + 1) % K][0] - cp[k][0], cp[(k + 1) % K][1] - cp[k][1]);
        const r0 = rf * need / (RND_LEN[c.len] * IN / Lp);       // rayon voulu, en unites du polygone (echelle approchee)
        const arcs = cp.map((v, k) => {
          const a = cp[(k - 1 + K) % K], b = cp[(k + 1) % K];
          const l1 = Math.hypot(v[0] - a[0], v[1] - a[1]), l2 = Math.hypot(b[0] - v[0], b[1] - v[1]);
          const d1 = [(v[0] - a[0]) / l1, (v[1] - a[1]) / l1], d2 = [(b[0] - v[0]) / l2, (b[1] - v[1]) / l2];
          const phi = Math.atan2(d1[0] * d2[1] - d1[1] * d2[0], d1[0] * d2[0] + d1[1] * d2[1]), ta = Math.tan(Math.abs(phi) / 2);
          const t = Math.min(r0 * ta, 0.45 * Math.min(l1, l2)), r = ta > 1e-6 ? t / ta : 0, sg = Math.sign(phi) || 1;
          const E = [v[0] - d1[0] * t, v[1] - d1[1] * t], Cc = [E[0] - d1[1] * r * sg, E[1] + d1[0] * r * sg];
          return { E, X: [v[0] + d2[0] * t, v[1] + d2[1] * t], C: Cc, r, phi, a0: Math.atan2(E[1] - Cc[1], E[0] - Cc[0]) };
        });
        const ds = Lp / 3000;
        for (let k = 0; k < K; k++) {
          const A = arcs[k], B = arcs[(k + 1) % K];
          const na = Math.max(1, Math.ceil(Math.abs(A.phi) * A.r / ds));
          for (let q = 0; q < na; q++) { const ph = A.a0 + A.phi * q / na; raw.push([A.C[0] + A.r * Math.cos(ph), A.C[1] + A.r * Math.sin(ph)]); }
          const ls = Math.hypot(B.E[0] - A.X[0], B.E[1] - A.X[1]), nl = Math.max(1, Math.ceil(ls / ds));
          for (let q = 0; q < nl; q++) raw.push([A.X[0] + (B.E[0] - A.X[0]) * q / nl, A.X[1] + (B.E[1] - A.X[1]) * q / nl]);
        }
      } else {
        const N = 2048, per = N / K;
        for (let i = 0; i < N; i++) {                              // Catmull-Rom fermee par les points de passage
          const f = i / per, s0 = Math.floor(f), u = f - s0;
          const p0 = cp[(s0 - 1 + K) % K], p1 = cp[s0 % K], p2 = cp[(s0 + 1) % K], p3 = cp[(s0 + 2) % K];
          const cr = (a, b, c2, d) => 0.5 * (2 * b + (-a + c2) * u + (2 * a - 5 * b + 4 * c2 - d) * u * u + (-a + 3 * b - 3 * c2 + d) * u * u * u);
          raw.push([cr(p0[0], p1[0], p2[0], p3[0]), cr(p0[1], p1[1], p2[1], p3[1])]);
        }
      }
      const N = raw.length;
      let L = 0;
      for (let i = 0; i < N; i++) L += Math.hypot(raw[(i + 1) % N][0] - raw[i][0], raw[(i + 1) % N][1] - raw[i][1]);
      const k = RND_LEN[c.len] * IN / L;
      // points tous les STEP le long de la courbe (boucle fermee)
      P = []; let acc = 0, want = 0;
      for (let i = 0; i < N; i++) {
        const a = raw[i], b = raw[(i + 1) % N], d = Math.hypot(b[0] - a[0], b[1] - a[1]) * k;
        while (want <= acc + d && P.length < 4000) { const u = (want - acc) / d; P.push([(a[0] + (b[0] - a[0]) * u) * k, (a[1] + (b[1] - a[1]) * u) * k]); want += STEP; }
        acc += d;
      }
      if (Math.hypot(P[P.length - 1][0] - P[0][0], P[P.length - 1][1] - P[0][1]) < STEP * 0.6) P.pop();
      let rmin = Infinity;
      for (let i = 0; i < P.length; i++) rmin = Math.min(rmin, circR(P[(i - 2 + P.length) % P.length], P[i], P[(i + 2) % P.length]));
      // ni virage trop serre, ni deux bouts qui se touchent (huit : sauf au croisement, ou un passage est sur le pont)
      if (rmin >= need && !overlaps(P, crossing ? crossProfile(P).prof : null)) break;
      if (shape === 'huit') { for (const c2 of ctrl) { c2.xy[1] *= 0.94; } continue; }  // boucles plus fines (bouts moins serres)
      if (shape === 'bloc') {                                      // amas : coins un peu plus larges, sinon un autre amas
        if (tr >= 24) { shape = 'épingles'; makeCtrl(); amp = 1; } else if (tr % 3 === 2) makeCtrl(); else rf *= 1.08;
        continue;
      }
      if (corner) { rf *= 1.12; amp *= 0.9; continue; }          // coins plus larges, polygone un peu plus regulier
      if (shape === 'jeu') {                                       // piste du jeu : lissee un peu plus (virages moins serres)
        // 2026-11-16 : seulement autour des virages trop serres (avant : tout le trace, la forme finissait en rond) ;
        // deux bouts trop proches (aucun virage en cause) : tout le trace comme avant
        const old = ctrl.map(c2 => c2.xy.slice()), rr = P.map((p, i) => circR(P[(i - 2 + P.length) % P.length], p, P[(i + 2) % P.length]));
        const kw = RND_LEN[c.len] * IN / L, bad = new Uint8Array(K);
        cp.forEach((q, k2) => {
          let bi = 0, bd = Infinity;
          for (let i = 0; i < P.length; i += 2) { const d = Math.hypot(P[i][0] - q[0] * kw, P[i][1] - q[1] * kw); if (d < bd) { bd = d; bi = i; } }
          for (let d = -12; d <= 12; d++) if (rr[(bi + d + P.length) % P.length] < need) { bad[k2] = 1; break; }
        });
        const anyBad = bad.some(Boolean);
        ctrl.forEach((c2, k2) => {
          if (anyBad && !bad[k2] && !bad[(k2 + 1) % K] && !bad[(k2 - 1 + K) % K]) return;
          const a = old[(k2 - 1 + K) % K], b = old[(k2 + 1) % K];
          c2.xy = [0.5 * old[k2][0] + 0.25 * (a[0] + b[0]), 0.5 * old[k2][1] + 0.25 * (a[1] + b[1])]; });
        continue;
      }
      amp *= 0.85;
    }
    // ondulations (2026-11-14, retour utilisateur « trop de lignes droites, manque de virages ») : la route serpente de
    // part et d'autre du trace (2 ou 3 vagues de 180 a 450 m, nombre entier sur le tour), amplitude selon la difficulte
    // (12 / 22 / 32 m), reduite si un virage devient trop serre ou si deux passages se rapprochent. Tirage a part
    if (!opts.noWiggle) {                                          // opts.noWiggle : essais (?crtest) seulement
      const wr = mulberry((c.seed ^ 0xC0FFEE) >>> 0), Lp = P.length * STEP;
      const waves = Array.from({ length: 2 + Math.floor(wr() * 2) }, () => {
        const lam = Lp / Math.max(2, Math.round(Lp / ((180 + wr() * 270) * IN)));
        return { lam, a: 0.5 + wr() * 0.5, ph: wr() * 2 * Math.PI };
      });
      // 2026-11-14, retour utilisateur « manque encore beaucoup de virages » : une vague courte de plus (120 a 220 m) et
      // amplitude 12 / 22 / 32 m -> 20 / 32 / 42 m (toujours reduite si un virage devient trop serre)
      const wr2 = mulberry((c.seed ^ 0xB3E7D) >>> 0);
      waves.push({ lam: Lp / Math.max(2, Math.round(Lp / ((120 + wr2() * 100) * IN))), a: 0.35 + wr2() * 0.3, ph: wr2() * 2 * Math.PI });
      const sum = waves.reduce((s, w) => s + w.a, 0);
      const A0 = { F: 20, N: 32, D: 42 }[c.diff] * IN;
      // portions droites gardees (2 a 4 de 250 m, la ou le trace est deja droit) : sauts, chicanes, spirales s'y posent
      const m0 = P.length, env = new Float64Array(m0).fill(1), Rb = P.map((p, i) => circR(P[(i - 5 + m0) % m0], p, P[(i + 5) % m0]));
      const SL = Math.round(250 * IN / STEP), RAMPW = 15, nKeep = 2 + (c.len === 'L' || c.len === 'X' ? 1 : 0) + (c.diff === 'D' ? 1 : 0);
      const cands = [];
      for (let i = 0; i < m0; i++) { let ok = true; for (let k = 0; k < SL && ok; k++) if (Rb[(i + k) % m0] < 300 * IN) ok = false; if (ok) cands.push(i); }
      const kept = [];
      for (let t = 0; t < 40 && kept.length < nKeep && cands.length; t++) {
        const i0 = cands[Math.floor(wr() * cands.length)];
        if (kept.some(k => Math.min(Math.abs(k - i0), m0 - Math.abs(k - i0)) < SL + 2 * RAMPW + 20)) continue;
        kept.push(i0);
        for (let k = -RAMPW; k < SL + RAMPW; k++) {
          const w = k < 0 ? sstep(0, 1, -k / RAMPW) : k >= SL ? sstep(0, 1, (k - SL + 1) / RAMPW) : 0;
          env[(i0 + k + m0) % m0] = Math.min(env[(i0 + k + m0) % m0], w);
        }
      }
      for (let A = A0; A >= 4 * IN; A *= 0.75) {
        const m = P.length, raw = P.map((p, i) => {
          const a = P[(i - 1 + m) % m], b = P[(i + 1) % m], l = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
          const o = env[i] * A / sum * waves.reduce((s, w) => s + w.a * Math.sin(2 * Math.PI * i * STEP / w.lam + w.ph), 0);
          return [p[0] - (b[1] - a[1]) / l * o, p[1] + (b[0] - a[0]) / l * o];
        });
        // points tous les STEP le long de la nouvelle courbe
        const Q2 = []; let acc = 0, want = 0;
        for (let i = 0; i < m; i++) {
          const a = raw[i], b = raw[(i + 1) % m], d = Math.hypot(b[0] - a[0], b[1] - a[1]);
          while (want <= acc + d && Q2.length < 4000) { const u = (want - acc) / (d || 1); Q2.push([a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u]); want += STEP; }
          acc += d;
        }
        if (Math.hypot(Q2[Q2.length - 1][0] - Q2[0][0], Q2[Q2.length - 1][1] - Q2[0][1]) < STEP * 0.6) Q2.pop();
        let rmin = Infinity;
        for (let i = 0; i < Q2.length; i++) rmin = Math.min(rmin, circR(Q2[(i - 2 + Q2.length) % Q2.length], Q2[i], Q2[(i + 2) % Q2.length]));
        if (rmin >= need && !overlaps(Q2, crossing ? crossProfile(Q2).prof : null)) { P = Q2; break; }
      }
    }
    const shapeUsed = shape === 'huit' ? 'en 8' : shape === 'jeu' ? `inspirée de ${gameTpl.t}` : amp > 0.5 ? shape : amp > 0.2 ? shape + ' (adoucie)' : 'ronde';
    if (opts.traceOnly) return { P, shape: shapeUsed, amp, rf, K, base: shape };     // essais (?crtest) : trace seul, rien n'est modifie
    if (rnd() < 0.5) P.reverse();                                // sens de la course au hasard
    let n = P.length;
    const cross = crossing ? crossProfile(P) : null;
    await step(20, 'Pièces de route : chicanes, bosses, spirales…');
    // 2. PIECES SPECIALES dans le trace (2026-11-13, demande utilisateur) : chicanes, series de bosses, spirales ; nombre
    // selon la difficulte et la longueur. Chaque piece prend une ligne droite libre (marquee « occupee » ensuite)
    const longer = c.len === 'L' || c.len === 'X' ? 1 : 0;
    const want = { F: { chic: 1, bump: 1, spiral: 0 },
                   N: { chic: 1 + longer, bump: 1 + longer, spiral: rnd() < 0.6 ? 1 : 0 },
                   D: { chic: 2 + longer, bump: 2, spiral: 1 + longer } }[c.diff];
    // pieces choisies dans la fenetre (masque) : cochee = au moins une, decochee = aucune
    let nJumps = D.jumps, bankDeg = D.bank;
    if (c.mask !== undefined) {
      const on = b => (c.mask & b) !== 0;
      want.chic = on(1) ? Math.max(1, want.chic) : 0;
      want.bump = on(2) ? Math.max(1, want.bump) : 0;
      want.spiral = on(4) ? Math.max(1, want.spiral) : 0;
      nJumps = on(8) ? Math.max(1, D.jumps) : 0;
      bankDeg = on(16) ? D.bank || 10 : 0;
    }
    const radOf = A => A.map((p, i) => circR(A[(i - 2 + A.length) % A.length], p, A[(i + 2) % A.length]));
    const shuffled = a => { a = a.slice(); for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };
    let busy = new Uint8Array(n);
    if (cross) {                                                   // croisement du huit : aucune autre piece, pas le depart
      for (let k = -(crossFlat + crossRamp + 5); k <= crossFlat + crossRamp + 5; k++) busy[(cross.i + k + n) % n] = 1;
      for (let k = -(crossFlat + 8); k <= crossFlat + 8; k++) busy[(cross.j + k + n) % n] = 1;
    }
    // debuts de suites de `len` points de rayon > 220 m, sans piece
    const freeRuns = len => { const r = radOf(P), out = [];
      for (let i = 0; i + len < P.length; i++) { let ok = true; for (let k = 0; k < len && ok; k++) if (r[i + k] < 220 * IN || busy[i + k]) ok = false; if (ok) out.push(i); }
      return out; };
    const pieces = [];
    // 2a. chicanes : decalage lateral en S (deux virages opposes) sur ~150 m, amplitude 10 a 18 m
    // pieces choisies a la main (masque) : plusieurs essais, chicane plus longue et plus douce (la forme d'origine, 150 m
    // et 10 a 18 m de decalage, etait presque toujours trop serree pour la largeur de route). Sans masque : comme avant
    // (memes pistes pour les anciens codes)
    const chicTries = c.mask !== undefined ? 12 : 1;
    for (let j = 0, tries = 0; j < want.chic && tries < want.chic * chicTries; tries++) {
      if (chicTries === 1) j++;
      const soft = chicTries > 1, L = soft ? [64, 54, 46][tries % 3] : 38, runs = freeRuns(L + 10); if (!runs.length) { if (soft && tries % 3 < 2) continue; break; }
      const i0 = runs[Math.floor(rnd() * runs.length)] + 5, A = (soft ? 6 + rnd() * 6 : 10 + rnd() * 8) * IN * (rnd() < 0.5 ? 1 : -1), old = P.map(p => p.slice());
      for (let k = 0; k <= L; k++) {
        const i = i0 + k, t = k / L, a = old[i - 1], b = old[i + 1];
        const nx = -(b[1] - a[1]), ny = b[0] - a[0], l = Math.hypot(nx, ny) || 1, off = A * Math.sin(2 * Math.PI * t) * Math.sin(Math.PI * t);
        P[i] = [old[i][0] + nx / l * off, old[i][1] + ny / l * off];
      }
      const r = radOf(P); let rmin = Infinity;
      for (let k = i0 - 3; k <= i0 + L + 3; k++) rmin = Math.min(rmin, r[(k + n) % n]);
      if (rmin < need) { P = old; continue; }                     // virage trop serre : chicane abandonnee
      for (let k = i0 - 5; k <= i0 + L + 5; k++) busy[(k + n) % n] = 1;
      pieces.push('chicane');
      if (soft) j++;
    }
    // 2d. epingles (2026-11-23, masque 128) : sur une longue ligne droite, la route sort sur le cote (quart de tour), file
    // tout droit, fait demi-tour (epingle), revient et reprend sa direction (quart de tour) : aller-retour qui garde le
    // tour ferme. Tirage a part ; du cote exterieur d'abord, loin du reste du trace
    if (c.mask !== undefined && (c.mask & 128)) {
      const hr2 = mulberry((c.seed ^ 0x3C6EF372) >>> 0);
      const count = 1 + (c.diff === 'D' || longer ? 1 : 0);
      const area0 = loopArea(P);
      for (let j = 0, tries = 0; j < count && tries < 12; tries++) {
        const Rh = Math.max(W / 2 + 8 * IN, need), r1 = Math.max(need, 40 * IN), Lo = (tries < 6 ? 50 + hr2() * 70 : 30 + hr2() * 30) * IN;
        const Dlen = 2 * r1 + 2 * Rh, nD = Math.round(Dlen / STEP);
        // portion presque droite (rayon > 150 m) a peine plus longue que la piece ; le raccord au bout est verifie ensuite
        const rr1 = radOf(P), runs = [];
        for (let i = 12; i + nD + 30 < n; i++) { let ok = true; for (let k = 0; k < nD + 8 && ok; k++) if (busy[i + k] || rr1[i + k] < 150 * IN) ok = false; if (ok) runs.push(i); }
        if (!runs.length) break;
        let done = false;
        for (const r0 of shuffled(runs).slice(0, 20)) {
          const i0 = r0 + 4, i1 = i0 + nD, a = P[i0 - 1], b = P[i0 + 1];
          const th0 = Math.atan2(b[1] - a[1], b[0] - a[0]);
          for (const sd of area0 > 0 ? [-1, 1] : [1, -1]) {
            const segs = [[Math.PI / 2 * r1, sd / r1], [Lo, 0], [Math.PI * Rh, -sd / Rh], [Lo, 0], [Math.PI / 2 * r1, sd / r1]];
            let x = P[i0][0], y = P[i0][1], th = th0;
            const gen = [];
            for (const [len, k] of segs) for (let m = Math.max(1, Math.round(len / STEP)), q2 = 0; q2 < m; q2++) {
              const dl = len / m; th += k * dl / 2; x += Math.cos(th) * dl; y += Math.sin(th) * dl; th += k * dl / 2; gen.push([x, y]);
            }
            const end = gen.pop();
            if (Math.hypot(end[0] - P[i1][0], end[1] - P[i1][1]) > 10 * IN) continue;   // ligne pas assez droite
            let ok = true;
            for (const p of gen) {
              for (let i = 0; i < n && ok; i++) {
                if (i >= i0 - 45 && i <= i1 + 45) continue;
                if (Math.hypot(P[i][0] - p[0], P[i][1] - p[1]) < W + 30 * IN) ok = false;
              }
              if (!ok) break;
            }
            if (!ok) continue;
            const P2 = [...P.slice(0, i0 + 1), ...gen, ...P.slice(i1)];
            const r2 = radOf(P2); let rmin = Infinity;
            for (let k = i0 - 3; k < i0 + gen.length + 4; k++) rmin = Math.min(rmin, r2[(k + P2.length) % P2.length]);
            if (rmin < need * 0.98 || overlaps(P2, null)) continue;
            const nb = new Uint8Array(P2.length);
            nb.set(busy.slice(0, i0 + 1), 0); nb.set(busy.slice(i1), i0 + 1 + gen.length);
            nb.fill(1, Math.max(0, i0 - 8), Math.min(P2.length, i0 + gen.length + 9));
            P = P2; busy = nb; n = P.length; done = true; pieces.push('épingle');
            break;
          }
          if (done) break;
        }
        if (done) j++;
      }
    }
    // 3. hauteurs : ondulations douces sur le tour (fermees), pente <= 60 % du maximum et compatible avec les virages
    let s = [0];
    for (let i = 1; i < n; i++) s.push(s[i - 1] + Math.hypot(P[i][0] - P[i - 1][0], P[i][1] - P[i - 1][1]));
    let Ltot = s[n - 1] + Math.hypot(P[0][0] - P[n - 1][0], P[0][1] - P[n - 1][1]);
    for (let k = 0; k < 6; k++) rnd();                             // (anciens tirages des ondulations : suite inchangee)
    let rad = radOf(P), h;
    // 2026-11-14, retour utilisateur « manque beaucoup de montees / descentes » : l'ancien relief (3 ondulations sur le
    // tour) etait reduit PARTOUT des qu'un seul virage serre genait (2,6 km : 40 a 60 m de montee au total). Maintenant
    // la pente se tire troncon par troncon (montee, palier, descente de 80 a 280 m, 5 a 16 % selon la difficulte, la
    // hauteur ramenee vers 0 au-dela de +- Hlim), limitee LA ou un virage l'exige (rayon mini en pente du paveur), lissee
    // (pente qui change sur ~40 m), puis corrigee pour que le tour se referme. Tirage a part
    { const hr = mulberry((c.seed ^ 0x7E11A5) >>> 0);
      // 2026-11-16, retour utilisateur « montees et descentes superieures a l'actuel » : pentes et hauteur maxi relevees
      // (normale 7-14 % / +-45 m -> 14-21 % / +-85 m), pente maxi 60 -> 75 % du paveur, troncons plus longs, moins de plats
      const G = { F: [0.08, 0.14, 50], N: [0.14, 0.21, 85], D: [0.16, 0.21, 110] }[c.diff], Hlim = G[2] * IN;
      // pente maxi par point : 75 % du maxi du paveur, et compatible avec le virage le plus serre a +- 20 m
      const gmax = new Float64Array(n);
      for (let i = 0; i < n; i++) {
        let r = Infinity; for (let k = -5; k <= 5; k++) r = Math.min(r, rad[(i + k + n) % n]);
        gmax[i] = Math.max(0, Math.min(0.75 * SLOPE_MAX, Number.isFinite(r) ? 0.9 * (r / R_MIN - 1) / R_SLOPE * SLOPE_MAX : 1));
      }
      let g = new Float64Array(n), z = 0;
      for (let i = 0; i < n;) {
        const len = Math.round((110 + hr() * 260) * IN / STEP), mag = G[0] + hr() * (G[1] - G[0]);
        // plus on est haut (ou bas), plus on a de chances de revenir ; un troncon sur 10 a plat
        const up = hr() < 0.5 - 0.45 * Math.max(-1, Math.min(1, z / Hlim));
        const gs = hr() < 0.1 ? 0 : up ? mag : -mag;
        for (let k = 0; k < len && i < n; k++, i++) { g[i] = gs; z += gs * STEP; }
      }
      const gRaw = opts.reliefOnly ? g.slice() : null;
      const clip = () => { for (let i = 0; i < n; i++) g[i] = Math.max(-gmax[i], Math.min(gmax[i], g[i])); };
      const smooth = () => { const W2 = 5, o = new Float64Array(n);
        for (let i = 0; i < n; i++) { let t = 0; for (let k = -W2; k <= W2; k++) t += g[(i + k + n) % n]; o[i] = t / (2 * W2 + 1); }
        g = o; };
      for (let it = 0; it < 12; it++) {
        clip(); smooth(); smooth(); clip();
        // fermeture : le reste de denivele reparti la ou la pente a de la marge
        const res = g.reduce((a, v) => a + v, 0); if (Math.abs(res * STEP) < 0.2 * IN) break;
        const room = Array.from(g, (v, i) => Math.max(0, res > 0 ? gmax[i] + v : gmax[i] - v)), tot = room.reduce((a, v) => a + v, 0) || 1;
        for (let i = 0; i < n; i++) g[i] -= res * room[i] / tot;
      }
      const res = g.reduce((a, v) => a + v, 0) / n; for (let i = 0; i < n; i++) g[i] -= res;   // reste minime
      h = new Array(n); h[0] = 0;
      for (let i = 1; i < n; i++) h[i] = h[i - 1] + g[i - 1] * STEP;
      const mid = (Math.max(...h) + Math.min(...h)) / 2; h = h.map(v => v - mid);
      if (opts.reliefOnly) return { h, g0: opts.reliefOnly === 2 ? gRaw : null };   // essais (?crtest) seulement
    }
    if (cross) {                                                   // pont du huit, au moins 12 m au-dessus de l'autre passage
      // 2026-11-16 : palier a hauteur fixe (top), rampes allongees jusqu'a ~9 % de moyenne. Avant : la hauteur manquante
      // s'ajoutait aux rampes d'origine (62 % de pente mesures avec le relief plus fort)
      const far = Math.ceil(3 * W / STEP), lim = W + 10 * IN, dI = k => Math.min(Math.abs(k - cross.i), n - Math.abs(k - cross.i));
      let hLow = -Infinity;
      for (let a = 0; a < n; a++) if (dI(a) <= crossFlat) for (let b = 0; b < n; b++) {
        const di = Math.min(Math.abs(a - b), n - Math.abs(a - b));
        if (di > far && Math.hypot(P[a][0] - P[b][0], P[a][1] - P[b][1]) < lim) hLow = Math.max(hLow, h[b]);
      }
      const top = Math.max(h[cross.i] + crossRise, hLow + 12 * IN), maxR = Math.floor(n / 4) - crossFlat - 10, h0 = h.slice();
      for (const sd of [1, -1]) {
        let Lr = crossRamp;
        for (let t = 0; t < 6; t++) Lr = Math.min(maxR, Math.max(crossRamp, Math.ceil(Math.abs(top - h0[(cross.i + sd * (crossFlat + Lr) + 2 * n) % n]) / 0.09 / STEP)));
        // pente reelle de la rampe (relief dessous compris) : rampe encore allongee tant qu'elle depasse 75 % du maxi
        const rampMax = L2 => { let m = 0, prev = top;
          for (let d = crossFlat + 1; d <= crossFlat + L2 + 1; d++) { const k = (cross.i + sd * d + 2 * n) % n, w = sstep(0, 1, (d - crossFlat) / L2), v = top * (1 - w) + h0[k] * w;
            m = Math.max(m, Math.abs(v - prev)); prev = v; } return m / STEP; };
        for (let t = 0; t < 12 && Lr < maxR && rampMax(Lr) > 0.75 * SLOPE_MAX; t++) Lr = Math.min(maxR, Math.ceil(Lr * 1.25));
        for (let d = 0; d <= crossFlat + Lr; d++) {
          const k = (cross.i + sd * d + 2 * n) % n, w = d <= crossFlat ? 0 : sstep(0, 1, (d - crossFlat) / Lr);
          h[k] = top * (1 - w) + h0[k] * w;
          if (d > crossFlat + crossRamp) busy[k] = 1;              // rampe allongee : pas de piece dessus
        }
      }
    }
    const gentle = (i0, len, lim) => { for (let k = 0; k < len; k++) { const i = (i0 + k) % h.length;
      if (Math.abs(h[(i + 1) % h.length] - h[i]) > lim * STEP) return false; } return true; };
    // pas de portion assez plate : la route est ramenee a une pente reguliere sous la piece (raccords sur 50 m), si les
    // pentes et virages restent compatibles ; h modifie, true si reussi
    const level = (i0, len, lim) => {
      const N = h.length, R2 = radOf(P), F = 12, h0 = h[(i0 % N)], h1 = h[(i0 + len) % N], h2 = h.slice();
      for (let k = -F; k <= len + F; k++) {
        const i = (i0 + k + N) % N, t = Math.max(0, Math.min(1, k / len)), w = k < 0 ? sstep(0, 1, (k + F) / F) : k > len ? sstep(0, 1, (len + F - k) / F) : 1;
        h2[i] = h[i] * (1 - w) + (h0 + (h1 - h0) * t) * w;
      }
      for (let k = -F - 1; k <= len + F + 1; k++) {
        const i = (i0 + k + N) % N, sl = Math.abs(h2[(i + 1) % N] - h2[i]) / STEP;
        if (sl > 0.75 * SLOPE_MAX || (Number.isFinite(R2[i]) && R2[i] < rMinAt(sl))) return false;
        if (k >= 0 && k < len && sl > lim) return false;
      }
      h = h2; return true;
    };
    // 2a'. tranchee profonde pour un tunnel souterrain (2026-11-24, masque 256 ; avant les autres pieces : il lui faut ~1 km) : route a 24-36 m sous le sol, rampes a 13 %
    // en moyenne ; recouverte ensuite par la pate (clayFeatures). Tirage a part
    S.deepCuts = [];
    if (c.mask !== undefined && (c.mask & 256)) {
      const rd = mulberry((c.seed ^ 0x2C1B3C6D) >>> 0), want = 1 + (c.diff !== 'F' && longer ? 1 : 0);
      const r01 = u => { const a = 0.25, v = 1 / (1 - a); return u <= 0 ? 0 : u >= 1 ? 1 : u < a ? v * u * u / (2 * a)
        : u > 1 - a ? 1 - v * (1 - u) * (1 - u) / (2 * a) : v * (u - a / 2); };
      for (let j = 0, tries = 0; j < want && tries < 60; tries++) {
        const depth = -(24 + rd() * 12) * IN, ramp = Math.ceil((Math.abs(depth) + 3 * IN) / 0.13 / STEP);   // 24-36 m : plus souvent de la place
        const flat = Math.round((tries < 30 ? 90 + rd() * 110 : 70 + rd() * 40) * IN / STEP), len = 2 * ramp + flat;
        if (len + 20 >= n) break;
        const starts = [];
        { let run = 0;
          for (let i = 0; i < 2 * n; i++) { run = busy[i % n] ? 0 : run + 1; if (i >= n && run >= len + 10) starts.push((i - len - 4 + n) % n); } }
        if (!starts.length) break;
        const i0 = starts[Math.floor(rd() * starts.length)], h2 = h.slice();
        for (let k = 0; k <= len; k++) {
          const w = k < ramp ? r01(k / ramp) : k <= ramp + flat ? 1 : r01((len - k) / ramp), i = (i0 + k) % n;
          h2[i] = h[i] * (1 - w) + depth * w;
        }
        let ok = true;
        for (let k = -1; k <= len + 1 && ok; k++) {
          const i = (i0 + k + n) % n, sl = Math.abs(h2[(i + 1) % n] - h2[i]) / STEP;
          if (sl > 0.65 * SLOPE_MAX || (Number.isFinite(rad[i]) && rad[i] < rMinAt(sl))) ok = false;
        }
        if (!ok || overlaps(P, h2)) continue;
        h = h2;
        for (let k = -5; k < len + 5; k++) busy[(i0 + k + n) % n] = 1;
        S.deepCuts.push({ i0, ramp, flat }); j++;
      }
    }
    // 2b. bosses : 2 ou 3 bosses de 1,5 a 3 m (pente <= 22 %) sur une ligne droite
    for (let j = 0; j < want.bump; j++) {
      // la bosse s'ajoute a la pente de la route (2026-11-14) : route a 10 % au plus, bosse a 16 % au plus (22 avant)
      const Hb = (1.5 + rnd() * 1.5) * IN, m = Math.round(Math.max(40 * IN, Math.PI * Hb / 0.16) / STEP), nb = 2 + Math.floor(rnd() * 2);
      let runs = freeRuns(m * nb + 10).filter(r0 => gentle(r0, m * nb + 10, 0.1));
      if (!runs.length) { const r0 = shuffled(freeRuns(m * nb + 34).map(r => r + 12)).slice(0, 12).find(r => level(r, m * nb + 10, 0.1)); if (r0 !== undefined) runs = [r0]; }
      if (!runs.length) break;
      const i0 = runs[Math.floor(rnd() * runs.length)] + 5;
      for (let k = 0; k < m * nb; k++) h[(i0 + k) % n] += Hb * (1 - Math.cos(2 * Math.PI * (k % m) / m)) / 2;
      for (let k = i0 - 5; k < i0 + m * nb + 5; k++) busy[(k + n) % n] = 1;
      pieces.push('bosses');
    }
    // 2b'. plongeons (2026-11-23, masque 64) : creux en U de 6 a 15 m (pente 12 a 18 %, moins si la route est deja en
    // pente), fond plat de 0 a 16 m. Tirage a part
    if (c.mask !== undefined && (c.mask & 64)) {
      const hp = mulberry((c.seed ^ 0x6A09E667) >>> 0);
      const count = 1 + (c.diff === 'D' ? 1 : 0) + longer, rr0 = radOf(P);
      for (let j = 0, tries = 0; j < count && tries < count * 8; tries++) {
        // creux AJOUTE au relief (qui monte et descend souvent a 14-21 %) : sa pente est reduite a la marge laissee par la
        // pente de la route a cet endroit (pente + creux <= 75 % du maxi du paveur) ; pas pose si la marge est < 8 %
        const depth0 = (6 + hp() * (c.diff === 'F' ? 5 : 9)) * IN, p0 = 0.12 + hp() * 0.06, flat = Math.round(hp() * 4);
        const cap = 0.75 * SLOPE_MAX, len0 = 2 * rampProfile(depth0, p0).length + flat;
        const okR = rMinAt(cap) * 1.05, cand = [];
        for (let i = 12; i + len0 + 22 < n; i++) {
          let ok = true, msl = 0;
          for (let k = 0; k < len0 + 10 && ok; k++) {
            if (busy[i + k] || rr0[i + k] < okR) ok = false;
            else msl = Math.max(msl, Math.abs(h[(i + k + 1) % n] - h[i + k]) / STEP);
          }
          if (ok && cap - msl >= 0.08) cand.push([i, cap - msl]);
        }
        if (!cand.length) continue;
        const [r0, room] = cand[Math.floor(hp() * cand.length)];
        const pUse = Math.min(p0, room - 0.01), depth = depth0 * pUse / p0, prof = rampProfile(depth, pUse);
        const len = 2 * prof.length + flat, i0 = r0 + 5;
        let d = 0;
        for (let k = 0; k < len; k++) {
          d += k < prof.length ? -prof[k] : k < prof.length + flat ? 0 : prof[len - 1 - k];
          h[(i0 + k) % n] += d;
        }
        for (let k = i0 - 5; k < i0 + len + 5; k++) busy[(k + n) % n] = 1;
        pieces.push('plongeon'); j++;
      }
    }
    // 2c. spirales : boucle complete qui monte de 16 a 22 m et repasse au-dessus de son entree (pont), puis la route
    // redescend a 10 %. Posee du cote ou elle a de la place (exterieur d'abord), loin du reste du trace
    const area = loopArea(P);
    // 2026-11-14, retour utilisateur « spirales trop serrees, peu de vision en arrivant dessous » : rayon 45 m -> ~80 m
    // (65 m si la place manque ; route de 50 a 70 m de large), 22 a 28 m de hauteur libre sous le pont (16 a 22 avant)
    const RC_TRY = [Math.max(80 * IN, W * 1.6), Math.max(65 * IN, W * 1.3)];
    for (let j = 0; j < want.spiral; j++) {
      const rise = (22 + rnd() * 6) * IN, Ld = rise / 0.10, nd = Math.ceil(Ld / STEP);
      let done = false;
      for (const Rc of RC_TRY) {
      const m = Math.max(24, Math.round(2 * Math.PI * Rc / STEP));
      // la sortie garde sa hauteur tant qu'elle passe au-dessus de la boucle (sinon elle la longeait a 5 m au-dessus et
      // son talus recouvrait la route du dessous), au plus ce palier
      const hold = Math.ceil(Math.sqrt((Rc + W + 10 * IN) ** 2 - Rc ** 2) / STEP) + 2;
      // entree droite sur 120 m ; la redescente qui suit peut tourner, mais sans autre piece
      // redescente a ~15 % au plus ajoutee a la pente : portion presque plate d'abord, sinon route ramenee a plat
      const runs0 = freeRuns(30).filter(r0 => r0 > 12 && r0 + hold + nd + 42 < n && !busy.slice(r0, r0 + hold + nd + 30).some(Boolean));
      const flat0 = runs0.filter(r0 => gentle(r0, hold + nd + 30, 0.12)), runs = flat0.length ? flat0 : runs0;
      for (const r0 of shuffled(runs).slice(0, 15)) {
        const hSave = h;
        if (!flat0.length && !level(r0, hold + nd + 30, 0.12)) continue;
        const kk = r0 + 15, a = P[kk - 1], b = P[kk + 1], l = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1, tx = (b[0] - a[0]) / l, ty = (b[1] - a[1]) / l;
        for (const sd of area > 0 ? [-1, 1] : [1, -1]) {           // +1 : centre a gauche (boucle trigo : exterieur = droite)
          const C = [P[kk][0] - ty * sd * Rc, P[kk][1] + tx * sd * Rc];
          const ph0 = Math.atan2(P[kk][1] - C[1], P[kk][0] - C[0]), circ = [];
          for (let q = 1; q < m; q++) { const ph = ph0 + sd * 2 * Math.PI * q / m; circ.push([C[0] + Rc * Math.cos(ph), C[1] + Rc * Math.sin(ph)]); }
          let ok = true;
          for (const p of circ) {
            for (let i = 0; i < n && ok; i++) {
              const di = Math.min(Math.abs(i - kk), n - Math.abs(i - kk));
              if (di > 45 && Math.hypot(P[i][0] - p[0], P[i][1] - p[1]) < W + 30 * IN) ok = false;
            }
            if (!ok) break;
          }
          if (!ok) continue;
          const hk = h[kk];
          const P2 = [...P.slice(0, kk + 1), ...circ, ...P.slice(kk + 1)];
          // sortie : EXACTEMENT au sommet de la boucle (hk + rise) pendant le palier, puis rejoint le relief. Avant
          // (2026-11-14, retour utilisateur T915 « conflit entre la route et la barriere ») elle suivait la pente du
          // relief + rise : relief en descente sous la sortie -> sortie qui redescendait pendant que la boucle montait,
          // 12 m seulement au-dessus de la route d'en dessous, bord et barriere poses dessus
          const h2 = [...h.slice(0, kk + 1), ...circ.map((_, q) => hk + rise * (q + 1) / m),
               ...h.slice(kk + 1).map((v, i) => { const w = sstep(0, 1, (i + 1 - hold) / nd); return (hk + rise) * (1 - w) + v * w; })];
          let steep = false;                                      // redescente trop raide (relief qui descend aussi)
          for (let q = kk + m; q < kk + m + hold + nd + 2 && q + 1 < h2.length && !steep; q++)
            if (Math.abs(h2[q + 1] - h2[q]) > 0.75 * SLOPE_MAX * STEP) steep = true;
          if (steep || overlaps(P2, h2)) continue;                // pas assez haut au-dessus d'un autre passage
          P = P2; h = h2;
          for (const d of S.deepCuts || []) if (d.i0 > kk) d.i0 += circ.length;   // tranchee profonde apres la boucle : decalee
          const nb = new Uint8Array(P.length), e = kk + hold + nd + 5;
          nb.set(busy.slice(0, kk + 1), 0); nb.fill(1, kk - 15, e + m); nb.set(busy.slice(e), e + m - 1);
          busy = nb; n = P.length; done = true; pieces.push('spirale');
          break;
        }
        if (done) break;
        h = hSave;                                                 // route ramenee a plat pour rien : remise
      }
      if (done) break;
      }
    }
    s = [0];
    for (let i = 1; i < n; i++) s.push(s[i - 1] + Math.hypot(P[i][0] - P[i - 1][0], P[i][1] - P[i - 1][1]));
    Ltot = s[n - 1] + Math.hypot(P[0][0] - P[n - 1][0], P[0][1] - P[n - 1][1]);
    rad = radOf(P);
    // 2e. canyons et remblais (2026-11-14, demande utilisateur) : troncons de 100 a 350 m ou la route descend de 15 a 40 m
    // sous le sol (le terrain se creuse autour : canyon) ou monte de 12 a 35 m (talus dessous : remblai ; au-dessus de
    // 18 m, une fois sur deux SANS talus : route en l'air, comme un pont). Hauteur par rapport au SOL (le relief de base
    // de la piste ne l'ecrase plus), rampes a 10 % en moyenne. Nombre au hasard (0 a 4, parfois aucun), tirage a part (le
    // reste de la piste ne change pas), jamais sur une piece, pente et virages compatibles, sans approcher un autre passage
    const air = new Uint8Array(n);
    if (c.mask === undefined || (c.mask & 32)) {
      const rr = mulberry((c.seed ^ 0x5A17C0DE) >>> 0);
      // 85 % des pistes en ont (1 a 4 selon longueur et difficulte), les autres aucune
      const count = rr() < 0.85 ? 1 + Math.floor(rr() * (2 + longer + (c.diff === 'D' ? 1 : 0))) : 0;
      // rampe a pente reguliere (montee de la pente sur le premier quart, descente sur le dernier) : pente maxi 4/3 de
      // la moyenne (12 % -> 16 %), plus courte qu'une courbe en S (1,5 x)
      const ramp01 = u => { const a = 0.25, v = 1 / (1 - a); return u <= 0 ? 0 : u >= 1 ? 1 : u < a ? v * u * u / (2 * a)
        : u > 1 - a ? 1 - v * (1 - u) * (1 - u) / (2 * a) : v * (u - a / 2); };
      for (let j = 0, tries = 0; j < count && tries < count * 25; tries++) {
        const canyon = rr() < 0.5, depth = (canyon ? -(15 + rr() * 25) : 12 + rr() * 23) * IN;
        const inAir = !canyon && depth > 18 * IN && rr() < 0.5;
        const ramp = Math.ceil((Math.abs(depth) + 3 * IN) / 0.12 / STEP), flat = Math.round((100 + rr() * 250) * IN / STEP), len = 2 * ramp + flat;
        if (len + 20 >= n) continue;
        // emplacement tire parmi ceux qui sont libres sur toute la longueur (+ 5 points de chaque cote) : au hasard sur
        // tout le tour, presque tous tombaient sur une autre piece
        const starts = [];
        { let run = 0;
          for (let i = 0; i < 2 * n; i++) { run = busy[i % n] ? 0 : run + 1; if (i >= n && run >= len + 10) starts.push((i - len - 4 + n) % n); } }
        if (!starts.length) continue;
        const i0 = starts[Math.floor(rr() * starts.length)];
        let ok = true;
        const h2 = h.slice(), lift = [];
        for (let k = 0; k <= len; k++) {
          const w = k < ramp ? ramp01(k / ramp) : k <= ramp + flat ? 1 : ramp01((len - k) / ramp), i = (i0 + k) % n;
          h2[i] = h[i] * (1 - w) + depth * w;
          if (inAir && h2[i] > 6 * IN) lift.push(i);
        }
        for (let k = -1; k <= len + 1 && ok; k++) {
          const i = (i0 + k + n) % n, sl = Math.abs(h2[(i + 1) % n] - h2[i]) / STEP;
          if (sl > 0.65 * SLOPE_MAX || (Number.isFinite(rad[i]) && rad[i] < rMinAt(sl))) ok = false;
        }
        if (!ok || overlaps(P, h2)) continue;
        h = h2;
        for (let k = -5; k < len + 5; k++) busy[(i0 + k + n) % n] = 1;
        for (const i of lift) air[i] = 1;
        pieces.push(canyon ? 'canyon' : inAir ? 'route en l\'air' : 'remblai'); j++;
      }
    }
    // 2d. terrain : 2 km au moins, sinon la taille qui contient la piste avec 450 m de marge (2,4 / 2,8 / 3,2 km) ;
    // trace centre sur le terrain actuel
    let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    for (const [x, y] of P) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
    const span = Math.max(x1 - x0, y1 - y0) / IN;
    const size = T_SIZES.find(v => v >= Math.max(2000, span + 900)) || T_SIZES[T_SIZES.length - 1];
    const mx = (x0 + x1) / 2, my = (y0 + y1) / 2;
    for (const p of P) { p[0] += cx - mx; p[1] += cy - my; }
    // 4. depart sur la portion la plus droite (moyenne des courbures sur 80 m), jamais sur une piece
    const curv = rad.map(r => (Number.isFinite(r) ? 1 / r : 0));
    let best = 0, bestV = Infinity;
    for (let i = 0; i < n; i++) { let v = 0; for (let k = -10; k <= 10; k++) v += curv[(i + k + n) % n] + busy[(i + k + n) % n]; if (v < bestV) { bestV = v; best = i; } }
    const ord = i => (i + best) % n;
    S.deepCutsQ = S.deepCuts.map(d => ({ s: (d.i0 + d.ramp - best + n) % n, len: d.flat, ramp: d.ramp }));   // indices de la route finale
    const Q = Array.from({ length: n }, (_, i) => P[ord(i)]), H = Array.from({ length: n }, (_, i) => h[ord(i)]);
    const R = Array.from({ length: n }, (_, i) => rad[ord(i)]), B = Array.from({ length: n }, (_, i) => busy[ord(i)]);
    // cote du virage (+ a gauche) : produit vectoriel des deux troncons
    const side = Q.map((p, i) => { const a = Q[(i - 1 + n) % n], b = Q[(i + 1) % n];
      return Math.sign((p[0] - a[0]) * (b[1] - p[1]) - (p[1] - a[1]) * (b[0] - p[0])); });
    // 4b. largeur variable (2026-11-14, demande utilisateur « changements de taille de route en 50 et 90 m ») : troncons
    // de 150 a 400 m, largeur tiree entre 50 et 90 m, passage de l'une a l'autre sur ~60 m. Limitee dans les virages
    // serres (rayon >= 0,7 x largeur, comme le trace) et pres d'un autre passage (centres >= demi-largeurs + 10 m : chaque
    // largeur <= distance - 10 m). Depart (60 m de chaque cote) a la largeur de la difficulte. Tirage a part
    const wd = new Float64Array(n).fill(W);
    { const wr3 = mulberry((c.seed ^ 0x51DE5) >>> 0), cap = new Float64Array(n), far = Math.ceil(3 * 90 * IN / STEP);
      for (let i = 0; i < n; i++) {
        let r = Infinity; for (let k = -6; k <= 6; k++) r = Math.min(r, R[(i + k + n) % n]);
        let d = Infinity;
        for (let j = 0; j < n; j++) { const di = Math.min(Math.abs(i - j), n - Math.abs(i - j)); if (di > far) d = Math.min(d, Math.hypot(Q[i][0] - Q[j][0], Q[i][1] - Q[j][1])); }
        cap[i] = Math.min(r / 0.7, d - 10 * IN);
      }
      const tw = new Float64Array(n);
      for (let i = 0; i < n;) { const len = Math.round((150 + wr3() * 250) * IN / STEP), v = (50 + wr3() * 40) * IN;
        for (let k = 0; k < len && i < n; k++, i++) tw[i] = v; }
      for (let k = -15; k <= 15; k++) tw[(k + n) % n] = W;
      let w = Array.from(tw, (v, i) => Math.min(v, cap[i]));
      for (let pass = 0; pass < 3; pass++) {                      // lissage (~60 m), puis limites a nouveau
        const o = w.map((_, i) => { let t = 0; for (let k = -7; k <= 7; k++) t += w[(i + k + n) % n]; return t / 15; });
        w = o.map((v, i) => Math.min(v, cap[i]));
      }
      for (let i = 0; i < n; i++) wd[i] = Math.round(Math.max(Math.min(50 * IN, W), w[i]));
      for (let k = -15; k <= 15; k++) wd[(k + n) % n] = W; }
    // 5. virages releves (normale / difficile) : bord interieur a hauteur, bord exterieur releve, montee limitee a 15 %
    // 2026-11-14, retour utilisateur « manque de virages releves » : releve des 230 m de rayon (150 avant), complet a
    // 120 m (50 avant) ; angles 8 / 13 / 18 degres (0 / 10 / 16 avant)
    const u = Q.map((_, i) => bankDeg && R[i] < 230 * IN ? side[i] * wd[i] * Math.sin(bankDeg * Math.PI / 180 * Math.min(1, (230 * IN - R[i]) / (110 * IN))) : 0);
    const dmax = BANK_EDGE_SLOPE * STEP;
    for (let pass = 0; pass < 2; pass++) {
      for (let i = 0; i < 2 * n; i++) { const a = u[(i - 1 + n) % n], k = i % n; u[k] = Math.max(a - dmax, Math.min(a + dmax, u[k])); }
      for (let i = 2 * n; i > 0; i--) { const a = u[(i + 1) % n], k = i % n; u[k] = Math.max(a - dmax, Math.min(a + dmax, u[k])); }
    }
    const us = u.map((_, i) => { let t = 0; for (let k = -3; k <= 3; k++) t += u[(i + k + n) % n]; return t / 7; });
    // 6. sauts (normale / difficile) : sur les lignes droites (rayon > 250 m sur 100 m), loin du depart, trou de 16 m
    const gap = new Uint8Array(n);
    const straight = i => { for (let k = -12; k <= 12; k++) if (R[(i + k + n) % n] < 250 * IN || Math.abs(us[(i + k + n) % n]) > 1 || B[(i + k + n) % n]) return false; return true; };
    const spots = [];
    for (let i = 60; i < n - 60; i++) if (straight(i)) spots.push(i);
    for (let j = 0; j < nJumps && spots.length; j++) {
      const k = spots[Math.floor(rnd() * spots.length)];
      for (let g = 0; g < 4; g++) gap[k + g] = 1;
      for (let t = spots.length - 1; t >= 0; t--) if (Math.abs(spots[t] - k) < 60) spots.splice(t, 1);   // sauts espaces
    }
    // 7. brouillon : theme, terrain, route, peinture, decor
    await step(40, 'Terrain et route…');
    $('crkit').value = kit; applyKit();
    S.terrain = newTerrain({ pos: [cx, cy] }, size); $('crsize').value = String(size);
    clay.unpack(null);                                           // pate : plus de retouches de l'ancienne base
    S.props = []; S.waters = []; S.waterSel = -1;
    setWidth(W);
    S.points = Q.map((p, i) => {
      const q = [p[0], p[1], S.groundZ + H[i], wd[i], gap[i]];
      const up = Math.round(Math.abs(us[i]));
      if (up > 0) q.push(wd[i] / 2, wd[i] / 2, us[i] > 0 ? 0 : up, us[i] > 0 ? up : 0);
      return q;
    });
    // passage au-dessus d'un autre (spirale) : pont, sans talus (le sol suit la route du dessous), 20 m de marge
    { const far = Math.ceil(3 * W / STEP), top = new Uint8Array(n);
      for (let i = 0; i < n; i++) for (let j = i + far; j < n; j++) {
        if (n - (j - i) < far) break;
        if (Math.hypot(Q[i][0] - Q[j][0], Q[i][1] - Q[j][1]) < (wd[i] + wd[j]) / 2 + 20 * IN) top[H[i] > H[j] ? i : j] = 1;
      }
      for (let i = 0; i < n; i++) if (top[i]) for (let k = -3; k <= 3; k++) setNoTalus(S.points[(i + k + n) % n], true);
      for (let i = 0; i < n; i++) if (air[ord(i)]) setNoTalus(S.points[i], true); }      // routes en l'air (2e)
    S.closed = true; S.back = 0;
    // 6b. caisses et boosters (2026-11-16, demande utilisateur) : poses dans l'Edition a la generation (onGenerate) ; ici
    // seulement leurs emplacements. Booster avant chaque saut (avant le tremplin, centre, large) et en sortie de virage serre
    // sur les lignes droites (decale d'un cote, alterne). Les rangees de caisses (placement automatique de l'Edition)
    // evitent les sauts et les boosters. Tirage a part : le trace du code ne change pas
    S.items = null;
    if (opts.items) {
      const br = mulberry((c.seed ^ 0xB0057) >>> 0), at = i => (i + n) % n;
      const yawAt = i => Math.atan2(Q[at(i + 2)][1] - Q[at(i - 2)][1], Q[at(i + 2)][0] - Q[at(i - 2)][0]);
      // point a `off` po a gauche du trace (negatif : a droite), a la hauteur de la route (bord releve compris : bord gauche
      // releve de hl, droit de hr, comme placeFromPoints)
      const pos = (i, off) => { const a = yawAt(i), q = S.points[at(i)], t = Math.max(-1, Math.min(1, off / (wd[at(i)] / 2)));
        const hl = q[7] || 0, hr = q[8] || 0;
        return [Q[at(i)][0] - Math.sin(a) * off, Q[at(i)][1] + Math.cos(a) * off, S.groundZ + H[at(i)] + (hl * (1 + t) + hr * (1 - t)) / 2]; };
      // inclinaison [rx, ry] qui pose a plat sur la route (comme « Poser au sol » de l'Edition, groundTilt : R = Rz Ry Rx) :
      // pente dans le sens de la course (sur 16 m) et pente laterale (bord releve), 35 degres au plus
      const tiltAt = (i, off) => {
        const d = Math.hypot(Q[at(i + 2)][0] - Q[at(i - 2)][0], Q[at(i + 2)][1] - Q[at(i - 2)][1]) || 1;
        const s = (pos(i + 2, off)[2] - pos(i - 2, off)[2]) / d, h = Math.min(150, wd[at(i)] / 4);
        const g = (pos(i, off + h)[2] - pos(i, off - h)[2]) / (2 * h), L = Math.hypot(s, g, 1);
        const rx = Math.asin(Math.max(-1, Math.min(1, g / L))), ry = Math.atan2(-s / L, 1 / L);
        return Math.max(Math.abs(rx), Math.abs(ry)) > 35 * Math.PI / 180 ? [0, 0] : [+rx.toFixed(4), +ry.toFixed(4)]; };
      const boosts = [], avoid = [];
      const jumps = [...gap.keys()].filter(i => gap[i] && !gap[at(i - 1)]);
      for (const g of jumps) {
        avoid.push([...Q[at(g + 2)].slice(0, 2), 55 * IN]);
        const i = g - 14;                                           // ~55 m avant le trou : avant le tremplin (30 m)
        boosts.push({ i: at(i), pos: pos(i, 0), yaw: yawAt(i), tilt: tiltAt(i, 0), dims: [800, Math.round(Math.min(45 * IN, wd[at(i)] * 0.6)), 1000], jump: 1 });
      }
      // lignes droites en sortie de virage : 80 m devant sans virage serre, sans piece, sans saut, peu releve
      const want = { F: 2, N: 3, D: 3 }[c.diff] + { C: 0, M: 0, L: 1, X: 2 }[c.len];
      // 2 passes : rayon >= 140 m sur ~70 m devant, puis >= 90 m (traces sinueux : « bloc », ondulations). Pieces
      // acceptees (canyon, remblai droits ; spirales et chicanes ont un rayon plus petit), bord releve de 6 % au plus
      const okAt = (i, rmin) => { if (i < 0.1 * n || i > 0.92 * n) return false;
        for (let k = -2; k <= 16; k++) { const j = at(i + k); if (R[j] < rmin || Math.abs(us[j]) > 0.06 * wd[j]) return false; }
        for (let k = -6; k <= 30; k++) if (gap[at(i + k)]) return false;
        return true; };
      const exitOf = i => { let r = Infinity; for (let k = -20; k <= -3; k++) r = Math.min(r, R[at(i + k)]); return r < 110 * IN; };
      const minGap = Math.max(30, Math.floor(n / (want + 2)));
      let side = br() < 0.5 ? 1 : -1;
      for (const rmin of [140 * IN, 90 * IN]) {
        let cand = [];
        for (let i = 0; i < n; i++) if (okAt(i, rmin)) cand.push(i);
        for (let k = cand.length - 1; k > 0; k--) { const j = Math.floor(br() * (k + 1)); [cand[k], cand[j]] = [cand[j], cand[k]]; }
        cand = cand.filter(i => exitOf(i)).concat(cand.filter(i => !exitOf(i)));    // sorties de virage d'abord
        for (const i of cand) {
          if (boosts.filter(b => !b.jump).length >= want) break;
          if (boosts.some(b => Math.min(Math.abs(b.i - i), n - Math.abs(b.i - i)) < minGap)) continue;
          const off = side * wd[i] * (0.12 + br() * 0.13); side = -side;
          boosts.push({ i, pos: pos(i, off), yaw: yawAt(i), tilt: tiltAt(i, off), dims: [800, 1000, 1000] });
        }
      }
      for (const b of boosts) avoid.push([b.pos[0], b.pos[1], 30 * IN]);
      // caisses (2026-11-16, 2e retour : « les caisses par rangees (bonus ?) », caisses de fruits gardees, ni TNT ni Nitro) :
      // calculees ici (apercu = resultat) comme le placement automatique de l'Edition : rangees de 4 caisses « ? » en
      // travers de la route (14,6 m d'ecart, resserre si la route est etroite), reparties sur le tour apres la grille ;
      // caisses de fruits entre les rangees ; lignes de 5 fruits Wumpa. Hors des sauts et des boosters
      const crates = [], SP = 14.6 * IN, PER = 4;
      const free = (i, reach) => avoid.every(([x, y, r]) => Math.hypot(Q[at(i)][0] - x, Q[at(i)][1] - y) > r + reach);
      const clearIdx = (i, reach) => { for (let d = 0; d < 40; d++) for (const j of d ? [i + d, i - d] : [i]) if (j > 0.1 * n && j < 0.97 * n && free(j, reach)) return j; return -1; };
      const span = (lo, hi, k, m) => Math.round(n * (lo + (hi - lo) * (k + 0.5) / m));
      // nombre de rangees selon la longueur reelle de la route (2026-11-16) : une tous les 740 m environ (550 puis 630
      // jugees trop nombreuses sur les grandes maps, -15 % le 2026-11-16), 3 au moins, 11 au plus
      // -> 1,8 km : 3 ; 2,6 km : 4 ; 3,4 km : 5 ; 4,2 km : 6 ; 5,5 km : 7
      const L = Math.max(3, Math.min(11, Math.round(Ltot / IN / 740)));
      for (let k = 0; k < L; k++) {
        const g = Math.max(SP * 0.45, Math.min(SP, (wd[span(0.12, 0.96, k, L)] - 2 * 4 * IN) / (PER - 1)));
        const i = clearIdx(span(0.12, 0.96, k, L), g * (PER - 1) / 2);
        if (i < 0) continue;
        for (let j = 0; j < PER; j++) crates.push({ kind: 'question', pos: pos(i, (j - (PER - 1) / 2) * g), yaw: yawAt(i), tilt: tiltAt(i, (j - (PER - 1) / 2) * g) });
        avoid.push([Q[at(i)][0], Q[at(i)][1], g * (PER - 1) / 2 + 6 * IN]);
      }
      for (let k = 0; k < 2; k++) {                                   // caisses de fruits, a gauche puis a droite
        const i = clearIdx(Math.round(n * (0.12 + 0.84 * (k + 1) / 3)), SP * 0.5);
        const off = (k ? -1 : 1) * Math.min(SP, wd[i] / 2 - 4 * IN) * 0.5;
        if (i >= 0) crates.push({ kind: 'fruit', pos: pos(i, off), yaw: yawAt(i), tilt: tiltAt(i, off) });
      }
      const WL = { F: 2, N: 3, D: 4 }[c.diff];                          // lignes de 5 fruits (4 m d'ecart)
      for (let k = 0; k < WL; k++) {
        let i = Math.round(n * (0.12 + 0.84 * (k + 0.66) / WL)), tries = 0;
        while (tries++ < 40 && ![0, 1, 2, 3, 4].every(j => free(i + j, SP * 0.33))) i++;
        if (tries > 40) continue;
        const off = (k % 2 ? -1 : 1) * Math.min(SP, wd[at(i)] / 2 - 4 * IN) * 0.33;
        for (let j = 0; j < 5; j++) crates.push({ kind: 'wumpa', pos: pos(i + j, off) });
      }
      for (const b of boosts) delete b.i;
      S.items = { v: 2, boosts, crates };
    }
    renderItems();
    S.start = { pos: [Q[0][0], Q[0][1]], yaw: Math.atan2(Q[1][1] - Q[0][1], Q[1][0] - Q[0][0]) };
    $('crbar').value = c.diff === 'F' ? 'all' : 'curves';
    setMarks(opts.marks ? { edges: true, curbs: true, center: false } : {});
    placeFromPoints(); refreshTerrainMesh(); rebuild();
    // peinture : taches des autres sols du theme loin de la route
    await step(60, 'Peinture du sol…');
    const T = S.terrain, Dd = roadDistance(), noise = aiNoise(rnd), nm = Math.min(4, MATERIALS.length);
    if (nm > 1) for (let j = 0; j < T.n; j++) for (let i = 0; i < T.n; i++) {
      const v = j * T.n + i; if (Dd[v] < 15 * IN) continue;
      const val = noise(i * T.cell, j * T.cell, 260 * IN);
      if (val > 0.45) T.paint[v] = 1; else if (val < -0.55 && nm > 2) T.paint[v] = 2;
    }
    // second theme (2026-11-20, demande utilisateur « deux themes sur une meme piste ») : une partie du tour (40 a 60 %)
    // peinte avec les sols du 2e theme, transitions melangees sur ~150 m. Le decor automatique prend les objets du theme
    // du sol (aiPlace) : arbres, rochers... suivent. Route, barrieres, ciel : ceux du 1er theme. Tirage a part
    const kit2 = Number.isInteger(c.kit2) ? kits[c.kit2 % kits.length] : null;
    const base2 = kit2 && kit2 !== kit ? EXTRA_MATS.findIndex(e => e.kit === kit2) : -1;
    let theme2 = null;
    if (base2 >= 0) {
      const r2 = mulberry((c.seed ^ 0x2D7E3A) >>> 0), n2 = EXTRA_MATS.filter(e => e.kit === kit2).length;
      const idx = m => MATERIALS.length + base2 + Math.min(m, n2 - 1);
      const R = S.points, N = R.length, u0 = 0.2 + r2() * 0.3, span = 0.4 + r2() * 0.2, blend = 150 * IN;
      let tot = 0; const acc = [0];
      for (let k = 1; k < N; k++) { tot += Math.hypot(R[k][0] - R[k - 1][0], R[k][1] - R[k - 1][1]); acc.push(tot); }
      tot += Math.hypot(R[0][0] - R[N - 1][0], R[0][1] - R[N - 1][1]);
      const a0 = u0 * tot, a1 = (u0 + span) * tot, smp = [];
      for (let k = 0; k < N; k += 3) smp.push(k);
      const n3 = aiNoise(r2);
      // poids du 2e theme selon la distance (le long du tour) aux deux limites : 0 dehors, 1 dedans
      const w2 = s => { const inside = s >= a0 && s < a1, d = Math.min(Math.abs(s - a0), Math.abs(s - a1), Math.abs(s + tot - a1), Math.abs(s - tot - a0));
        return inside ? 0.5 + 0.5 * Math.min(1, d / blend) : 0.5 - 0.5 * Math.min(1, d / blend); };
      for (let j = 0; j < T.n; j++) for (let i = 0; i < T.n; i++) {
        const x = T.x0 + i * T.cell, y = T.y0 + j * T.cell, v = j * T.n + i;
        let best = Infinity, bk = 0;
        for (const k of smp) { const d = (R[k][0] - x) ** 2 + (R[k][1] - y) ** 2; if (d < best) { best = d; bk = k; } }
        if (w2(acc[bk]) + 0.35 * n3(x, y, 90 * IN) <= 0.5) continue;
        if (Dd[v] < 15 * IN) { T.paint[v] = idx(0); continue; }
        const val = noise(i * T.cell, j * T.cell, 260 * IN);
        T.paint[v] = val > 0.45 ? idx(1) : val < -0.55 && n2 > 2 ? idx(2) : idx(0);
      }
      theme2 = kit2;
    }
    if (opts.decor) {                                              // relief, objets et eau : decor automatique a graine fixe
      await step(70, 'Relief, décor et eau (quelques secondes)…');
      const keep = Object.fromEntries([...AI_FIELDS, 'craibig', 'craisight'].map(id => [id, $(id).type === 'checkbox' ? $(id).checked : $(id).value]));
      aiPreset(['balanced', 'nature', 'wild', 'clear'][Math.floor(rnd() * 4)]);
      $('craiamp').value = String({ F: 25, N: 48, D: 75 }[c.diff]);      // 2026-11-24 : x1,5 a x1,7 (15 / 30 / 50 avant)
      // decor fourni et varie : densite maxi, petits decors x2,2, familles des themes proches, gros decors de fond
      aiDecor((c.seed * 2654435761) >>> 0, { density: 3, small: 2.2, variety: true, big: true, borrow: Math.max(1, +$('craiborrow').value),
                                                    farHills: { F: 80, N: 100, D: 125 }[c.diff] });   // 55 / 65 / 75 avant
      for (const [id, v] of Object.entries(keep)) { if ($(id).type === 'checkbox') $(id).checked = v; else $(id).value = v; }
      aiSaveOptions(); aiShowValues();
    } else { refreshTerrainMesh(); rebuild(); renderProps(); renderWater(); }
    if (c.mask !== undefined && (c.mask & 256)) {
      await step(90, 'Ponts de terre et tunnels…'); pieces.push(...clayFeatures(c));
      const fb = clay.dropFloating(); if (fb) { clearSeats(fb); renderProps(); }      // restes de pate detaches (creusements)
    }
    S.rndCode = rndCode(c.kit, c.len, c.diff, c.seed, c.mask, c.kit2);
    // ciel, heure et meteo (2026-11-20, demande utilisateur) : tires d'apres le code, poses a « Générer la piste »
    S.rndLook = opts.look ? rndLook(c, kit, opts.skies || []) : null;
    // ajouts d'Edition (objets, imports, copies, caisses, boosters, lumières, objets animés) : places pour l'ancienne piste, retires a la generation
    // (2026-11-20 : « les objets de la map de base se retrouvent sur la nouvelle map »)
    S.rndFresh = !!opts.fresh;
    renderItems();                                                 // caisses / boosters reposes sur la route finale
    saveDraft();
    return { shape: shapeUsed, length: Math.round(Ltot / IN), jumps: nJumps ? [...gap].filter((g, i) => g && !gap[(i - 1 + n) % n]).length : 0, size, pieces,
             look: S.rndLook, theme2 };
  }
  // meteo possible selon le theme ('' = aucune ; plusieurs fois = plus probable). Lieux fermes (egouts, tubes, fonds
  // marins, mines, labo, usine, espace) : aucune
  const RND_WEATHER = {
    neige: ['snow', 'snow', 'blizzard', ''], ruines: ['snow', 'blizzard', ''], horloge: ['snow', 'snow', ''], banquise: ['snow', 'blizzard', 'blizzard', ''],
    jungle: ['rain', 'storm', 'fireflies', 'leaves', ''], boogie: ['rain', 'rain', 'storm', 'fireflies', ''], parc: ['leaves', 'leaves', 'pollen', 'rain', ''],
    sable: ['', '', 'rain', 'storm', 'pollen'], canyon: ['', '', 'pollen'], pyramide: ['', 'pollen', 'fireflies'], gorge: ['', '', 'storm'],
    volcan: ['', 'storm'], orage: ['storm', 'storm', 'rain'], chateau: ['rain', 'storm', ''], ciel: ['', 'pollen', 'leaves'],
    stade: ['', '', 'rain'], futur: ['', 'rain', 'storm'], temps: ['', 'leaves'], grottes: ['fireflies', ''],
  };
  // ciel : la moitie du temps celui de la piste du theme, sinon un autre au hasard ; heure : jour 60 %, soir 25 %, nuit 15 %
  function rndLook(c, kit, skies) {
    const r = mulberry((c.seed ^ 0x5C7E11) >>> 0), pick = a => a[Math.floor(r() * a.length) % a.length];
    const list = skies.slice().sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
    const home = ($('crkit').querySelector(`option[value="${kit}"]`)?.textContent || '').match(/\(([^)]*)\)\s*$/)?.[1]?.toLowerCase() || '';
    const own = list.find(s => (s.label || '').toLowerCase() === home);
    const t = r(), other = list.length ? pick(list) : null;
    const sky = (t < 0.5 && own) ? own : other || own;
    const h = r(), preset = h < 0.6 ? 'day' : h < 0.85 ? 'evening' : 'night';
    const weather = pick(RND_WEATHER[kit] || ['']), d = r();
    return { sky: sky?.key || '', skyLabel: sky?.label || '', preset, weather, density: d < 0.25 ? 'low' : d < 0.8 ? 'normal' : 'high' };
  }
  function openRandomDialog() {
    if (S.opening) return;
    const kits = [...$('crkit').options].map(o => [o.value, o.textContent]);
    // theme : celui des Reglages de la piste (2026-11-14 : le code gardait le theme de la derniere piste creee quand on
    // l'avait change dans les Reglages)
    const kitNow = Math.max(0, kits.findIndex(([k]) => k === $('crkit').value));
    const cur = { ...(parseRndCode(S.rndCode) || { len: 'M', diff: 'N', seed: (Math.random() * 36 ** 6) >>> 0 }), kit: kitNow };
    // fenetre refaite le 2026-11-17 (« bouton mal fait, repense-le ») : choix visuels d'abord (theme en tuiles, longueur et
    // difficulte en boutons, pieces et options en pastilles), le code en bas (copier / coller / nouveau tirage)
    const ov = document.createElement('div');
    ov.style.cssText = 'position:fixed;inset:0;background:#0009;z-index:30;display:flex;align-items:center;justify-content:center;padding:16px';
    const info = S.info || {};
    const rgb = c => `rgb(${(c || [0.5, 0.5, 0.5]).map(v => Math.round(v * 255)).join(',')})`;
    const tile = ([k, l], i) => { const m = info.materials?.[k] || [];
      const short = (window.CTR_I18N?.t(l) || l).replace(/\s*\(.*\)\s*$/, '');   // nom traduit, sans la piste du jeu entre parentheses
      return `<button class="rdtile" data-i="${i}" title="${l}" style="background:linear-gradient(135deg,${rgb(m[0]?.color)} 0 55%,${rgb(m[m.length - 1]?.color)} 55%)"><span data-noi18n>${short}</span></button>`; };
    const seg = (id, items) => `<div class="rdseg" id="${id}">${items.map(([v, l, s]) => `<button data-v="${v}">${l}${s ? `<small>${s}</small>` : ''}</button>`).join('')}</div>`;
    const chip = (cls, data, l, title = '') => `<button class="rdchip ${cls}" ${data}${title ? ` title="${title}"` : ''}>${l}</button>`;
    ov.innerHTML = `<style>
      #rdbox{max-width:560px;width:100%;max-height:calc(100vh - 32px);overflow:auto;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}
      #rdbox h4{margin:12px 0 6px;font-size:12px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.04em}
      #rdbox .rdtiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(96px,1fr));gap:6px;max-height:190px;overflow:auto;padding:2px}
      #rdbox .rdtile{position:relative;height:52px;border-radius:7px;border:2px solid transparent;padding:0;overflow:hidden;cursor:pointer}
      #rdbox .rdtile span{position:absolute;inset:auto 0 0 0;padding:3px 5px;font-size:11px;line-height:1.15;background:#000a;color:#fff;text-align:left}
      #rdbox .rdtile.on{border-color:var(--accent,#f5a623);box-shadow:0 0 0 2px #0008 inset}
      #rdbox .rdseg{display:grid;grid-auto-flow:column;grid-auto-columns:1fr;gap:0}
      #rdbox .rdseg button{border-radius:0;padding:6px 4px;line-height:1.2}
      #rdbox .rdseg button small{display:block;font-size:10px;color:var(--muted)}
      #rdbox .rdseg button:first-child{border-radius:7px 0 0 7px}#rdbox .rdseg button:last-child{border-radius:0 7px 7px 0}
      #rdbox .rdseg button.on,#rdbox .rdchip.on{background:var(--accent,#f5a623);color:#111;border-color:transparent}
      #rdbox .rdseg button.on small{color:#333}
      #rdbox .rdchips{display:flex;flex-wrap:wrap;gap:5px}
      #rdbox .rdchip{border-radius:999px;padding:4px 10px;font-size:12px}
      #rdbox .rdcode{display:flex;gap:6px;align-items:center;background:#0003;border:1px solid var(--line);border-radius:8px;padding:6px 8px;margin-top:12px}
      #rdbox .rdcode input{flex:1;min-width:0;background:transparent;border:0;color:var(--text);font-family:monospace;font-size:16px;letter-spacing:1px}
    </style>
    <div id="rdbox">
      <div style="display:flex;align-items:center;gap:8px"><b style="font-size:15px">🎲 Piste aléatoire</b></div>
      <div class="note" style="font-size:12px;margin-top:4px">Tout est créé d'après le code : tracé, relief, peinture, décor, eau. Le même code redonne toujours la même piste : partage-le !</div>
      <h4>Thème</h4><div class="rdtiles">${kits.map(tile).join('')}</div>
      <h4>Deuxième thème <span style="text-transform:none;font-weight:400">— sur une partie du tour (sol et décor)</span></h4>
      <div style="display:flex;gap:6px;align-items:center"><select id="rdkit2" style="flex:1;background:#1d2026;color:var(--text);border:1px solid var(--line);border-radius:4px;padding:4px 6px">
        <option value="">Aucun (un seul thème)</option>${kits.map(([k, l], i) => `<option value="${i}">${l}</option>`).join('')}</select>
        <button id="rdkit2r" title="Deuxième thème au hasard">🎲</button></div>
      <div style="display:grid;grid-template-columns:3fr 2fr;gap:10px">
        <div><h4>Longueur</h4>${seg('rdlen', [['C', 'Courte', '≈ 1,8 km'], ['M', 'Moyenne', '≈ 2,6 km'], ['L', 'Longue', '≈ 3,4 km'], ['X', 'Très longue', '≈ 4,2 km']])}</div>
        <div><h4>Difficulté</h4>${seg('rddiff', [['F', 'Facile'], ['N', 'Normale'], ['D', 'Difficile']])}</div></div>
      <h4>Pièces de route</h4>
      <div class="rdchips">${RND_PIECES.map(([, b, l]) => chip('rdpc', `data-b="${b}"`, l)).join('')}</div>
      <div class="note" style="font-size:11px;margin-top:3px">Cochée : au moins une sur la piste (si la place le permet). Décochée : aucune.</div>
      <h4>Avec</h4>
      <div class="rdchips">${chip('rdopt on', 'data-o="decor"', 'Relief, décor et eau automatiques')}${chip('rdopt on', 'data-o="marks"', 'Marquage au sol')}${chip('rdopt on', 'data-o="items"', 'Caisses et boosters',
        'Visibles tout de suite dans l\'aperçu, posés à « Générer la piste » : rangées de caisses « ? », caisses de fruits, lignes de fruits Wumpa, et boosters avant les sauts et en sortie de virage. Rien n\'est posé si la piste a déjà des caisses ou des boosters.')}${chip('rdopt on', 'data-o="look"', '🌦 Ciel et météo',
        'Ciel (celui du thème ou d\'une autre piste), heure (jour, soir, nuit) et météo selon le thème (pluie, neige, orage, feuilles, lucioles…), tirés d\'après le code. Posés à « Générer la piste » ; modifiables ensuite dans Habillage › Ambiance.')}${chip('rdopt on', 'data-o="fresh"', '🧹 Retirer l\'ancienne scène',
        'Tout ce qui était posé sur l\'ancienne piste (décor, objets, imports, copies, caisses, boosters, lumières, objets animés, groupes) disparaît de l\'aperçu et est retiré à « Générer la piste » (« ↶ Annuler » pour revenir). Décoché : tes ajouts d\'Édition sont gardés et reposés sur le nouveau sol.')}</div>
      <div class="rdcode"><span style="font-size:12px;color:var(--muted)">Code</span><input id="rdcode" type="text" maxlength="16" spellcheck="false">
        <button id="rdnew" title="Nouveau code au hasard">🎲 Autre</button><button id="rdcopy" title="Copier le code (pour le partager)">Copier</button></div>
      <div id="rdbad" style="color:var(--err,#e55);font-size:12px;margin-top:4px" hidden>Code invalide (exemple : 3MN-K7Q2ZP)</div>
      <div style="display:flex;align-items:center;gap:8px;margin-top:14px">
        <span class="note" style="font-size:11px;flex:1">Remplace la route et le terrain actuels (Ctrl+Z pour revenir).</span>
        <button id="rdno">Annuler</button><button id="rdyes" class="primary">🎲 Créer la piste</button></div></div>`;
    document.body.appendChild(ov);
    const q = s => ov.querySelector(s);
    const boxes = [...ov.querySelectorAll('.rdpc')];
    const showPieces = c => { const m = c.mask ?? RND_MASK_DEF[c.diff]; boxes.forEach(b => b.classList.toggle('on', (m & +b.dataset.b) !== 0)); };
    const show = c => { q('#rdcode').value = rndCode(c.kit, c.len, c.diff, c.seed, c.mask, c.kit2);
                        ov.querySelectorAll('.rdtile').forEach(t => t.classList.toggle('on', +t.dataset.i === c.kit % kits.length));
                        ov.querySelectorAll('#rdlen button').forEach(b => b.classList.toggle('on', b.dataset.v === c.len));
                        ov.querySelectorAll('#rddiff button').forEach(b => b.classList.toggle('on', b.dataset.v === c.diff));
                        q('#rdkit2').value = Number.isInteger(c.kit2) && c.kit2 % kits.length !== c.kit % kits.length ? String(c.kit2 % kits.length) : '';
                        q('#rdbad').hidden = true; showPieces(c); };
    let c = { ...cur, kit: cur.kit % kits.length };
    show(c);
    q('.rdtile.on')?.scrollIntoView({ block: 'nearest' });
    ov.querySelectorAll('.rdtile').forEach(t => t.onclick = () => { c = { ...c, kit: +t.dataset.i }; if (c.kit2 === c.kit) c = { ...c, kit2: undefined }; show(c); });
    q('#rdkit2').onchange = () => { const v = q('#rdkit2').value; c = { ...c, kit2: v === '' || +v === c.kit ? undefined : +v }; show(c); };
    q('#rdkit2r').onclick = () => { let k; do { k = Math.floor(Math.random() * kits.length); } while (k === c.kit % kits.length && kits.length > 1); c = { ...c, kit2: k }; show(c); };
    ov.querySelectorAll('#rdlen button').forEach(b => b.onclick = () => { c = { ...c, len: b.dataset.v }; show(c); });
    ov.querySelectorAll('#rddiff button').forEach(b => b.onclick = () => { c = { ...c, diff: b.dataset.v, mask: rndDefMask(b.dataset.v) }; show(c); });
    // pieces : masque garde seulement s'il differe de celui de la difficulte (code court sinon)
    boxes.forEach(b => b.onclick = () => {
      b.classList.toggle('on');
      const m = boxes.reduce((a, x) => a | (x.classList.contains('on') ? +x.dataset.b : 0), 0);
      c = { ...c, mask: m === RND_MASK_DEF[c.diff] ? undefined : m }; show(c);
    });
    ov.querySelectorAll('.rdopt').forEach(b => b.onclick = () => b.classList.toggle('on'));
    q('#rdnew').onclick = () => { c = { ...c, seed: (Math.random() * 36 ** 6) >>> 0, mask: c.mask ?? rndDefMask(c.diff) }; show(c); };
    q('#rdcopy').onclick = async () => { try { await navigator.clipboard.writeText(q('#rdcode').value); status('Code copié : ' + q('#rdcode').value, 'ok'); }
                                         catch (e) { q('#rdcode').select(); status('Sélectionne le code puis Ctrl+C pour le copier'); } };
    q('#rdcode').oninput = () => { const p = parseRndCode(q('#rdcode').value); q('#rdbad').hidden = !!p;
      if (p) { c = { ...p, kit: p.kit % kits.length }; const v = q('#rdcode').value; show(c); q('#rdcode').value = v; } };
    q('#rdno').onclick = () => ov.remove();
    ov.addEventListener('keydown', e => { if (e.key === 'Escape') ov.remove(); });
    q('#rdyes').onclick = async () => {
      const p = parseRndCode(q('#rdcode').value);
      if (!p) { q('#rdbad').hidden = false; return; }
      const on = k => !!q(`.rdopt[data-o="${k}"]`)?.classList.contains('on');
      const opts = { decor: on('decor'), marks: on('marks'), items: on('items'), look: on('look'), fresh: on('fresh') };
      ov.remove();
      if (opts.look) {                                             // ciels disponibles (pistes du jeu qui en ont un)
        try { opts.skies = (await api('/api/ambiance_info', { track: getTrack() })).skies || []; } catch (e) { opts.skies = []; }
      }
      if (histTimer) histCommit();
      let r;
      S.opening = true;                                            // pas de seconde creation pendant celle-ci
      try { r = await randomTrack({ ...p, kit: p.kit % kits.length, kit2: Number.isInteger(p.kit2) ? p.kit2 % kits.length : undefined }, opts, rndProgress); }
      catch (e) { status('Erreur : ' + e.message, 'err'); return; }
      finally { S.opening = false; await rndProgress(null); }
      const pc = ['spirale', 'chicane', 'bosses', 'plongeon', 'épingle', 'canyon', 'remblai', 'route en l\'air', 'pont de terre', 'tunnel', 'tunnel souterrain'].map(k => [k, r.pieces.filter(x => x === k).length]).filter(([, v]) => v).map(([k, v]) => `${v} ${k}`);
      if (opts.fresh) ctx.showEdition?.(false);                    // ajouts d'Edition de l'ancienne piste : plus montres
      const lk = r.look, WX = { rain: 'pluie', storm: 'orage', snow: 'neige', blizzard: 'tempête de neige', leaves: 'feuilles', fireflies: 'lucioles', pollen: 'pollen' };
      const look = lk ? ` — ${{ day: 'jour', evening: 'soir', night: 'nuit' }[lk.preset]}${lk.skyLabel ? `, ciel de ${lk.skyLabel}` : ''}, `
        + (lk.weather ? `météo : ${WX[lk.weather] || lk.weather}` : 'sans météo') : '';
      const t2 = r.theme2 ? `, 2e thème : ${(kits.find(([k]) => k === r.theme2)?.[1] || r.theme2).replace(/\s*\(.*\)\s*$/, '')}` : '';
      status(`Piste ${S.rndCode} : ${r.length} m, forme ${r.shape}${t2}` + (r.jumps ? `, ${r.jumps} saut(s)` : '') + (pc.length ? `, ${pc.join(', ')}` : '')
             + ` — terrain ${sizeLabel(r.size)} km${look}. Retouche-la puis « Générer la piste »`, 'ok');
    };
  }

  function setWidth(w) {
    S.width = Math.max(W_MIN, Math.min(W_MAX, w));
    buildScreed(S.width);                                    // racle de la largeur de la route
    $('crwidth').value = String(Math.round(S.width / IN)); $('crw').textContent = Math.round(S.width / IN);
  }
  function closeLoop() {
    if (!nearStart()) { status('Reviens dans le cercle vert du départ pour fermer la boucle', 'err'); return; }
    // fin du trace passee devant le depart (sur le debut de la route) : retiree, sinon le raccord ferait un aller-retour
    const [a, b] = S.points, dx = b[0] - a[0], dy = b[1] - a[1], l = Math.hypot(dx, dy) || 1;
    const ahead = p => ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l;
    while (S.points.length > 3) {
      const p = S.points[S.points.length - 1];
      if (Math.hypot(p[0] - a[0], p[1] - a[1]) < closeR() && ahead(p) > -STEP) S.points.pop(); else break;
    }
    placeFromPoints();
    S.closed = true; rebuild(); saveDraft();
    status('Boucle fermée : « Générer la piste » construit la route, le sol, le parcours et les IA', 'ok');
  }

  function toggleChase() {
    S.chase = !S.chase; orbit.enabled = !S.chase;
    status(S.chase ? 'Caméra de poursuite' : 'Caméra libre (C : revenir à la poursuite)');
  }
  // sous le kart, dans la vue 3D : inclinaison en cours et hauteur par rapport au sol sous lui (relief sculpte, sans le
  // raccord a la route, qui suit justement le kart). Etiquette de la scene, redessinee seulement si le texte change
  const hudCanvas = document.createElement('canvas'); hudCanvas.width = 256; hudCanvas.height = 48;
  const hudTex = new THREE.CanvasTexture(hudCanvas); hudTex.colorSpace = THREE.SRGBColorSpace;
  const hud = new THREE.Sprite(new THREE.SpriteMaterial({ map: hudTex, depthTest: false, sizeAttenuation: false, transparent: true }));
  hud.scale.set(0.2, 0.0375, 1); hud.center.set(0.5, 1.5); hud.renderOrder = 30; hud.raycast = () => {};
  paver.add(hud);
  let hudText = null;
  function showHeight() {
    const m = Math.round((S.pos.z - heightAt(S.pos.x, S.pos.y)) / IN), deg = Math.round(Math.abs(S.roll || 0) * 180 / Math.PI);
    const atLimit = S.pos.z >= S.groundZ + H_MAX - IN || S.pos.z <= S.groundZ - H_MIN + IN;
    const text = `∠ ${deg ? (S.roll > 0 ? '← ' : '→ ') : ''}${deg}°    ↕ ${m > 0 ? '+' : m < 0 ? '−' : ''}${Math.abs(m)} m`;
    if (text + atLimit === hudText) return;
    hudText = text + atLimit;
    const g = hudCanvas.getContext('2d'), w = hudCanvas.width, h = hudCanvas.height;
    g.clearRect(0, 0, w, h);
    g.fillStyle = 'rgba(0,0,0,.65)'; g.beginPath(); g.roundRect(2, 2, w - 4, h - 4, 12); g.fill();
    g.fillStyle = atLimit ? '#ff6b6b' : '#fff'; g.font = '600 26px system-ui,sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
    g.fillText(text, w / 2, h / 2 + 1);
    hudTex.needsUpdate = true;
  }
  // mode Decor : onglet « Automatique » (reglages + bouton, pas de pinceau) ou « À la main » (liste d'objets + pinceau)
  const noBrush = () => (S.mode === 'props' && (S.propTab !== 'man' || S.propEdit)) || (S.mode === 'terrain' && S.tool === 'water' && (S.waterMode || 'fill') === 'fill');
  function setPropTab(t) {
    S.propTab = t === 'man' ? 'man' : 'auto';
    try { localStorage.setItem('ctr_creator_proptab', S.propTab); } catch (e) { /* sans importance */ }
    $('crptauto').classList.toggle('primary', S.propTab === 'auto'); $('crptman').classList.toggle('primary', S.propTab === 'man');
    $('crpaneauto').hidden = S.propTab !== 'auto'; $('crpaneman').hidden = S.propTab !== 'man';
    if (S.propTab === 'auto') { S.brushing = false; brush.visible = false; selectProp(null); }
  }
  function setMode(m) {
    const was = S.mode;
    if (S.pickStart) { S.pickStart = false; $('crstartpick').classList.remove('primary'); }
    S.mode = m; S.brushing = false;
    $('crroute').hidden = m !== 'route'; $('crterrain').hidden = m !== 'terrain'; $('crpaint').hidden = m !== 'paint';
    $('crprops').hidden = m !== 'props'; $('crtreset').hidden = m === 'props' || m === 'route' || m === 'edges' || m === 'bridge';
    $('crtreset').textContent = m === 'paint' ? '🗑 Effacer toute la peinture' : '🗑 Remettre tout le relief à plat';
    // reglages du pinceau : dans le bloc « Au pinceau » en mode Decor, sous l'outil sinon
    const slot = m === 'props' ? $('crbrushslot') : $('crbrushhome'), box = $('crbrush');
    if (box.parentNode !== slot) slot.appendChild(box);
    box.classList.toggle('crcard', m !== 'props');
    if (m === 'props') setPropTab(S.propTab);
    $('crbrush').hidden = m === 'route' || m === 'edges' || m === 'bridge' || (m === 'terrain' && S.tool === 'water' && (S.waterMode || 'fill') === 'fill');
    $('credges').hidden = m !== 'edges';
    $('crbridge').hidden = m !== 'bridge';
    $('crspeedrow').style.display = m === 'terrain' ? 'block' : 'none';   // (l'attribut hidden ne suffit pas : display en ligne)
    if (m !== 'edges') selectEdge(null);
    if (m !== 'bridge') selectBridge(null);
    if (m !== 'props') selectProp(null);
    for (const [id, k] of [['crmroute', 'route'], ['crmedges', 'edges'], ['crmbridge', 'bridge'], ['crmterrain', 'terrain'], ['crmpaint', 'paint'], ['crmprops', 'props']]) $(id).classList.toggle('primary', m === k);
    paver.visible = m === 'route'; brush.visible = false;
    S.chase = m === 'route'; orbit.enabled = !S.chase;
    updateGhost(true);
    // pinceaux : clic gauche = pinceau, clic droit = tourner la vue, clic milieu = deplacer (molette : zoom)
    if (m !== 'route' && !S.savedButtons) {
      S.savedButtons = { ...orbit.mouseButtons };
      orbit.mouseButtons = { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.PAN, RIGHT: THREE.MOUSE.ROTATE };
    } else if (m === 'route') restoreButtons();
    if (m !== 'route' && was === 'route') {
      // vue de haut, en biais, centree sur le paveur
      orbit.target.copy(S.pos); camera.position.set(S.pos.x - 120 * IN, S.pos.y - 160 * IN, S.pos.z + 220 * IN);
      camera.up.set(0, 0, 1); camera.lookAt(S.pos); orbit.update();
    }
    // message de l'outil a CHAQUE changement (2026-11-15 : il n'etait mis qu'en quittant Route, et restait sur « Bords… »
    // en passant a Pont, Relief, Peinture ou Decor)
    if (m !== was) status(m === 'route' ? 'Route : conduis le paveur (↑ avancer, ← → tourner, R / F monter / descendre, Entrée : fermer la boucle)'
           : m === 'edges' ? 'Bords : clique sur un bord de la route, puis tire la flèche rouge (largeur) ou bleue (relevé)'
           : m === 'bridge' ? 'Pont : clique sur la route là où elle croise une autre route (clic droit : tourner la vue)'
           : m === 'props' ? 'Décor : clic gauche maintenu pour semer ou effacer des objets (clic droit : tourner la vue)'
           : m === 'paint' ? 'Peinture : clic gauche maintenu pour peindre le sol (clic droit : tourner la vue)'
                           : 'Relief : clic gauche maintenu pour sculpter (clic droit : tourner la vue)');
  }
  function restoreButtons() {
    if (S.savedButtons) { orbit.mouseButtons = S.savedButtons; S.savedButtons = null; }
  }
  function setTool(k) {
    S.tool = k;
    panel.querySelectorAll('[data-tool]').forEach(b => b.classList.toggle('primary', b.dataset.tool === k));
    // eau : un clic, pas de pinceau
    $('crwatercard').hidden = k !== 'water';
    if (S.mode === 'terrain') $('crbrush').hidden = k === 'water' && (S.waterMode || 'fill') === 'fill';
    if (k === 'water') { brush.visible = false; setWaterMode(S.waterMode || 'fill'); renderWater(); syncWaterLevel(); }
  }
  function setPaint(i) {
    S.paint = i;
    panel.querySelectorAll('[data-mat]').forEach(b => b.classList.toggle('primary', +b.dataset.mat === i));
    const m = matOf(i), names = S.info?.kits || {};
    $('crmatcur').textContent = m.label + (i >= MATERIALS.length ? ` · ${names[m.kit] || m.kit}` : '');
  }

  const DRIVE = new Set(['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'KeyW', 'KeyZ', 'KeyS', 'KeyA', 'KeyQ', 'KeyD',
                         'KeyR', 'KeyF', 'KeyT', 'KeyG', 'ShiftLeft', 'ShiftRight', 'Space']);
  addEventListener('keydown', e => {
    if (!S.active || S.mode !== 'route' || e.code !== 'KeyB' || e.repeat || typing(e) || e.ctrlKey || e.metaKey) return;
    setTalus(S.noTalus);                                     // bascule
    status(S.noTalus ? 'Route suivante : sans talus (pont)' : 'Route suivante : avec talus');
    e.preventDefault(); e.stopImmediatePropagation();
  }, true);
  const typing = e => /^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName) && e.target.type !== 'range';
  addEventListener('keydown', e => {
    if (!S.active || S.mode !== 'route' || typing(e) || e.ctrlKey || e.metaKey) return;
    if (DRIVE.has(e.code)) S.keys.add(e.code);
    else if (e.key === '+' || e.code === 'NumpadAdd' || e.key === '=') setWidth(S.width + IN);
    else if (e.key === '-' || e.code === 'NumpadSubtract') setWidth(S.width - IN);
    else if (e.key === 'Enter') closeLoop();
    else if (e.code === 'KeyC') toggleChase();
    else return;
    e.preventDefault(); e.stopImmediatePropagation();
  }, true);
  // Ctrl+Z / Ctrl+Y (ou Ctrl+Maj+Z) : historique de la creation, pas celui de l'editeur
  addEventListener('keydown', e => {
    if (!S.active || typing(e) || !(e.ctrlKey || e.metaKey) || e.altKey) return;
    const k = e.key.toLowerCase();
    if (k === 'z' && !e.shiftKey) undo();
    else if (k === 'y' || (k === 'z' && e.shiftKey)) redo();
    else return;
    e.preventDefault(); e.stopImmediatePropagation();
  }, true);
  addEventListener('keyup', e => { S.keys.delete(e.code); }, true);
  addEventListener('blur', () => { S.keys.clear(); S.brushing = false; });

  // pinceaux du terrain : clic gauche sur la vue, ecoute en capture sur le conteneur (avant l'editeur et la camera :
  // rien n'est selectionne ni tourne pendant ce temps)
  const canvas = renderer.domElement;
  const VOL_TOOLS = new Set(['raise', 'lower', 'flatten', 'smooth']);
  function clayAt(e) {                                      // point de la pate sous la souris (arches et voutes comprises)
    const b = canvas.getBoundingClientRect();
    ndc.set(((e.clientX - b.left) / b.width) * 2 - 1, -((e.clientY - b.top) / b.height) * 2 + 1); ray.setFromCamera(ndc, camera);
    return clay.pick(ray.ray)?.point || null;
  }
  view.addEventListener('pointerdown', e => {
    if (!S.active || S.mode === 'route' || e.button !== 0 || e.target !== canvas) return;
    if (S.mode === 'edges') { edgePointerDown(e); return; }
    if (S.mode === 'bridge') { bridgePointerDown(e); return; }
    if (S.mode === 'props' && S.propTab === 'man' && S.propEdit) { propPointerDown(e); return; }
    if (S.mode === 'terrain' && S.tool === 'water' && (S.waterMode || 'fill') === 'fill') { waterPointerDown(e); return; }
    if (noBrush()) return;
    if (S.mode === 'terrain' && S.tool === 'stretch') {     // Etirer : la pate attrapee suit la souris
      const b = renderer.domElement.getBoundingClientRect();
      ndc.set(((e.clientX - b.left) / b.width) * 2 - 1, -((e.clientY - b.top) / b.height) * 2 + 1); ray.setFromCamera(ndc, camera);
      const h = clay.pick(ray.ray); if (!h) return;
      // a l'horizontale seulement (2026-11-24, demande utilisateur) : plan horizontal a la hauteur du point attrape
      S.grab = { a0: h.point.clone(), plane: new THREE.Plane().setFromNormalAndCoplanarPoint(new THREE.Vector3(0, 0, 1), h.point), box: null };
      clay.beginStretch(h.point, S.radius / 2);             // morceau attrape : boule de la moitie du pinceau
      S.brushing = true; orbit.enabled = false; canvas.setPointerCapture?.(e.pointerId);
      e.preventDefault(); e.stopImmediatePropagation(); return;
    }
    if (S.mode === 'terrain' && VOL_TOOLS.has(S.tool)) {    // sur une arche, une voute, une paroi etiree : en volume
      const h = clayAt(e);
      if (h && clay.isVolume(h.x, h.y, h.z)) {
        S.vol = { p: h, plane: { p: h.clone(), n: clay.normalAt(h.x, h.y, h.z) } };
        S.mouse = h; S.brushing = true; orbit.enabled = false; canvas.setPointerCapture?.(e.pointerId);
        e.preventDefault(); e.stopImmediatePropagation(); return;
      }
    }
    const p = S.mode === 'props' && clay.edited ? clayAt(e) || pick(e) : pick(e); if (!p) return;
    S.mouse = p; S.brushing = true; S.strokeRoad = null; S.flatZ = heightAt(p.x, p.y) - S.groundZ;
    if (S.mode === 'terrain' && S.tool === 'water') waterStrokeStart(p);      // eau peinte : niveau pris ici
    orbit.enabled = false; canvas.setPointerCapture?.(e.pointerId);
    e.preventDefault(); e.stopImmediatePropagation();
  }, true);
  view.addEventListener('pointermove', e => {
    if (!S.active || S.mode === 'route' || S.mode === 'edges' || S.mode === 'bridge' || (e.target !== canvas && !S.brushing)) return;
    if (S.mode === 'terrain' && S.tool === 'water' && !S.brushing) { brush.visible = false; waterHover(e); return; }
    if (S.waterCursor) { canvas.style.cursor = ''; S.waterCursor = false; }
    if (noBrush()) { brush.visible = false; return; }
    if (S.mode === 'terrain' && S.tool === 'stretch') {
      const b = renderer.domElement.getBoundingClientRect();
      ndc.set(((e.clientX - b.left) / b.width) * 2 - 1, -((e.clientY - b.top) / b.height) * 2 + 1); ray.setFromCamera(ndc, camera);
      if (S.brushing && S.grab) {                           // la matiere attrapee suit la souris, a l'horizontale
        const tgt = ray.ray.intersectPlane(S.grab.plane, new THREE.Vector3());
        if (tgt) {
          const d = tgt.clone().sub(S.grab.a0); d.z = 0;          // jamais vers le haut ni vers le bas
          const bx = clay.dragStretch(d);
          if (bx) S.grab.box = growBox(S.grab.box, bx.x0, bx.y0, bx.x1, bx.y1);
          brush.position.copy(tgt);
        }
        brush.visible = true; brush.scale.set(S.radius / 2, S.radius / 2, 1);
        e.preventDefault(); e.stopImmediatePropagation(); return;
      }
      const h = clay.pick(ray.ray);
      brush.visible = !!h;
      if (h) { brush.position.set(h.point.x, h.point.y, h.point.z + 20); brush.scale.set(S.radius, S.radius, 1); }
      return;
    }
    if (S.vol || (S.mode === 'terrain' && VOL_TOOLS.has(S.tool) && !S.brushing)) {   // le pinceau suit la surface de la pate
      const h = clayAt(e);
      if (h && S.vol) { S.vol.p = h; S.mouse = h; }
      brush.visible = !!h;
      if (h) { brush.position.set(h.x, h.y, h.z + 20); brush.scale.set(S.radius, S.radius, 1); if (!S.vol) S.mouse = h; }
      if (S.brushing) { e.preventDefault(); e.stopImmediatePropagation(); }
      return;
    }
    const p = S.mode === 'props' && clay.edited ? clayAt(e) || pick(e) : pick(e);
    brush.visible = !!p;
    if (p) { S.mouse = p; brush.position.set(p.x, p.y, p.z + 20); brush.scale.set(S.radius, S.radius, 1); }
    if (S.brushing) { e.preventDefault(); e.stopImmediatePropagation(); }
  }, true);
  const endBrush = e => {
    if (!S.brushing) return;
    S.brushing = false; orbit.enabled = true;
    if (S.mode === 'terrain' && S.tool === 'water') { waterStrokeEnd(); e?.stopImmediatePropagation?.(); return; }   // relief inchange
    let clayBox = S.grab?.box || S.vol?.box;                 // Etirer / outils en volume : objets de la zone reposes sur la pate
    if (S.grab || S.vol) {
      if (S.grab) clay.endStretch();
      S.grab = S.vol = null;
      const fb = clay.dropFloating();                       // morceaux de pate qui ne tiennent plus a rien : retires
      if (fb) clayBox = clayBox ? growBox(clayBox, fb.x0, fb.y0, fb.x1, fb.y1) : fb;
      if (clayBox) { clearSeats(clayBox); renderProps(); }
      saveDraft(); e?.stopImmediatePropagation?.(); return;
    }   // Etirer : brouillon + etape d'annulation
    // fin du trait : la zone peinte seulement ; talus et objets suivent le relief (rien de tout ca pour la peinture et le decor)
    if (S.mode === 'terrain') {
      refreshTerrainMesh(S.strokeBox);
      // sol du relief creuse sous un pied de pate : morceau detache retire (2026-11-24)
      const fb = clay.edited ? clay.dropFloating() : null; if (fb) clearSeats(fb);
      rebuild(); renderProps();
    }
    else if (S.mode === 'paint') refreshTerrainMesh(S.strokeBox);
    else renderProps();
    S.strokeBox = S.dirtyBox = null; S.dirtyT = false; saveDraft();
    e?.stopImmediatePropagation?.();
  };
  view.addEventListener('pointerup', endBrush, true);
  view.addEventListener('click', e => { if (S.active && S.mode !== 'route' && e.target === canvas) { e.preventDefault(); e.stopImmediatePropagation(); } }, true);
  canvas.addEventListener('pointerleave', () => { brush.visible = false; if (S.waterCursor) { canvas.style.cursor = ''; S.waterCursor = false; } });

  // ---- outil Bords : clic sur un bord de la route -> poignee (gizmo) ; fleche rouge (vers l'exterieur) : elargir /
  // amincir ce cote, fleche bleue (vers le haut) : relever / abaisser le bord (virage releve). Les points voisins
  // suivent sur l'etendue choisie (fondu en cosinus) ; le terrain dessous se raccorde (conform) ----
  const EDGE_W = [5 * IN, 60 * IN], EDGE_H = [-10 * IN, 15 * IN];     // demi-largeur : jusqu'a 120 m de route
  const edgeHandle = new THREE.Mesh(new THREE.SphereGeometry(1.5 * IN, 16, 12),
                                    new THREE.MeshBasicMaterial({ color: 0xffcc33, depthTest: false }));
  edgeHandle.renderOrder = 20; edgeHandle.visible = false; group.add(edgeHandle);
  const edgeLine = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: 0xffcc33, depthTest: false }));
  edgeLine.renderOrder = 19; edgeLine.visible = false; group.add(edgeLine);
  // extremites de la zone selectionnee (2026-11-12) : reperes blancs, bornes de « Lisser »
  const edgeEnds = [0, 1].map(() => {
    const m = new THREE.Mesh(new THREE.SphereGeometry(1.1 * IN, 14, 10), new THREE.MeshBasicMaterial({ color: 0xffffff, depthTest: false }));
    m.renderOrder = 20; m.visible = false; group.add(m); return m;
  });
  const tc = ctx.TransformControls ? new ctx.TransformControls(camera, canvas) : null;
  if (tc) {
    tc.setSpace('local'); tc.showY = false; group.add(tc.getHelper ? tc.getHelper() : tc);
    tc.addEventListener('dragging-changed', e => { orbit.enabled = !e.value; e.value ? edgeDragStart() : edgeDragEnd(); });
    tc.addEventListener('objectChange', edgeDrag);
  }

  // ---- mode Decor, outil « Modifier » (2026-11-12) : clic sur un objet seme -> boite jaune + poignees (deplacer en x / y
  // / hauteur, tourner autour de la verticale, taille uniforme). L'objet reste pose sur le sol (seatOf) ; la hauteur
  // tiree devient un decalage p.dz. Un objet du decor automatique modifie devient un objet « a la main » (p.ai retire :
  // « Retirer le décor automatique » ou un nouveau decor automatique le gardent) ----
  const selHold = new THREE.Object3D(), selBox = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(1, 1, 1)),
    new THREE.LineBasicMaterial({ color: 0xffcc33, depthTest: false }));
  selHold.rotation.order = 'ZYX'; selBox.renderOrder = 20; selHold.add(selBox); selHold.visible = false; group.add(selHold);
  const propProxy = new THREE.Object3D(); group.add(propProxy);
  propProxy.rotation.order = 'ZYX';                                    // ordre du jeu (inclinaisons X / Y puis cap Z)
  const ptc = ctx.TransformControls ? new ctx.TransformControls(camera, canvas) : null;
  if (ptc) {
    ptc.setSpace('local'); group.add(ptc.getHelper ? ptc.getHelper() : ptc);
    ptc.addEventListener('dragging-changed', e => { orbit.enabled = !e.value; e.value ? propDragStart() : propDragEnd(); });
    ptc.addEventListener('objectChange', () => propDrag());
  }
  S.propSelP = null; S.propEdit = false;
  function setPropGizmo(m) {
    if (!ptc) return;
    ptc.setMode(m);
    ptc.showX = ptc.showY = ptc.showZ = true;                          // tourner : 3 axes (2026-11-12 ; avant : verticale seule)
    panel.querySelectorAll('[data-ptm]').forEach(b => b.classList.toggle('primary', b.dataset.ptm === m));
  }
  function selectProp(p) {
    S.propMany = []; manyBoxes?.clear(); manyStart = null;
    if ($('crpefields')) $('crpefields').style.display = '';
    const scb = panel.querySelector('[data-ptm="scale"]'); if (scb) scb.disabled = false;
    S.propSelP = p || null;
    if (!p) { ptc?.detach(); selHold.visible = false; $('crpeset').style.display = 'none';
              $('crpeinfo').textContent = 'Clique sur un objet (posé à la main ou par le décor automatique) pour le modifier.'; return; }
    $('crpeset').style.display = 'block';
    syncPropSel(); ptc?.attach(propProxy); setPropGizmo(ptc?.getMode() || 'translate');
  }
  function syncPropSel() {
    const p = S.propSelP; if (!p) return;
    if (!S.props.includes(p)) { selectProp(null); return; }
    const st = seatOf(p), d = dimOf(p), mdl = propModel(p.k, p.t, p.m % (kindOf(p)?.n || 1));
    selHold.position.set(p.x, p.y, propZ(p)); selHold.rotation.set(st.rx + (p.rx || 0), st.ry + (p.ry || 0), p.yaw); selHold.scale.setScalar(p.s);
    if (mdl) { const g = mdl.g; g.boundingBox || g.computeBoundingBox(); const bb = g.boundingBox;
               bb.getCenter(selBox.position); bb.getSize(selBox.scale); }
    else { selBox.position.set(0, 0, (d.zmin + d.zmax) / 2 * IN); selBox.scale.set(1.4 * d.r * IN, 1.4 * d.r * IN, Math.max(IN, (d.zmax - d.zmin) * IN)); }
    selBox.scale.max(new THREE.Vector3(IN / 2, IN / 2, IN / 2));
    const off = !!st.off;
    selBox.material.color.setHex(off ? 0xff5050 : 0xffcc33); selHold.visible = true;
    if (!ptc?.dragging) { propProxy.position.set(p.x, p.y, propZ(p)); propProxy.rotation.set(p.rx || 0, p.ry || 0, p.yaw); propProxy.scale.setScalar(p.s); }
    const k = kindOf(p), name = k?.names?.[p.m % (k?.n || 1)] || p.t;
    $('crpeinfo').innerHTML = `<b>${name}</b> · ${k?.label || p.t}${p.ai ? ' · décor automatique' : ''}`;
    const put = (id, v) => { const el = $(id); if (document.activeElement !== el) el.value = v; };
    put('crpeyaw', Math.round((((p.yaw * 180 / Math.PI) % 360) + 360) % 360));
    put('crperx', Math.round((p.rx || 0) * 180 / Math.PI)); put('crpery', Math.round((p.ry || 0) * 180 / Math.PI)); put('crpes', +p.s.toFixed(2)); put('crpedz', +((p.dz || 0) / IN).toFixed(1));
    const w = $('crpewarn');
    const touch = !off && p.ed && propConflict(p);          // place a la main contre la route : pose quand meme
    w.hidden = !off && !touch;
    if (touch) w.textContent = 'Il touche la route (ou un pont) : posé quand même, car placé à la main. Vérifie qu’il ne gêne pas les karts.';
    else if (off) w.textContent = st.deg > STEEP_MAX ? 'Sur une pente trop forte : il ne sera pas posé.'
      : !inTerrain(p) ? 'Hors du terrain : il ne sera pas posé.' : 'Il touche la route (ou un pont) : il ne sera pas posé. Pose-le sur la route ou plus loin.';
  }
  // l'objet a change : pose recalculee (sol, route dessous), objet « a la main », vue
  function propChanged(p) {
    delete p.ai; p.ed = 1;                                   // place a la main : toujours pose (voir renderProps)
    if (roadUnder(p) !== null) p.road = 1; else delete p.road;
    seats.delete(p); renderProps();
  }
  function propDragStart() {
    if (manyActive()) { manyBegin(); return; }
    const p = S.propSelP; if (p) S.propDrag = { z: propZ(p), dz: p.dz || 0, s: p.s };
  }
  // mode : celui des poignees de la Creation, ou celles de l'Edition (objet de la base manipule depuis l'Edition, extDrag)
  function propDrag(m = ptc?.getMode()) {
    if (manyActive()) { manyDrag(); return; }
    const p = S.propSelP, b = S.propDrag; if (!p || !b) return;
    if (m === 'translate') {
      p.x = Math.round(propProxy.position.x); p.y = Math.round(propProxy.position.y);
      p.dz = Math.round(b.dz + propProxy.position.z - b.z); if (Math.abs(p.dz) < 1) delete p.dz;
    } else if (m === 'rotate') {                              // 3 axes (2026-11-12) : inclinaisons X / Y en plus de la pente du sol
      const r = propProxy.rotation;
      p.yaw = +r.z.toFixed(3);
      for (const [k, v] of [['rx', r.x], ['ry', r.y]]) { const a = +v.toFixed(3); if (Math.abs(a) < 1e-3) delete p[k]; else p[k] = a; }
    }
    else {
      // taille uniforme : l'axe tire le plus donne le facteur
      const sc = propProxy.scale, f = [sc.x, sc.y, sc.z].reduce((a, v) => Math.abs(v / b.s - 1) > Math.abs(a - 1) ? v / b.s : a, 1);
      p.s = +Math.max(0.05, Math.min(100, b.s * f)).toFixed(2); sc.setScalar(p.s);
    }
    propChanged(p);
  }
  function propDragEnd() {
    if (manyActive()) { manyStart = null; drawMany(); saveDraft(); return; }
    S.propDrag = null; syncPropSel(); saveDraft();
  }
  // ---- plusieurs objets dans Modifier (2026-11-18, demande utilisateur) : Maj / Ctrl+clic, poignee sur le groupe
  // (deplacer, tourner autour du centre), Dupliquer : les copies deviennent la selection, a deplacer tout de suite ----
  S.propMany = [];
  var manyBoxes = new THREE.Group(); group.add(manyBoxes);      // var : selectProp peut servir avant cette ligne
  var propPivot = new THREE.Object3D(); group.add(propPivot);
  var manyStart = null;
  function manyActive() { return S.propMany?.length > 1; }
  function boxFor(p) {                                       // boite jaune d'un objet (meme calcul que syncPropSel)
    const st = seatOf(p), d = dimOf(p), mdl = propModel(p.k, p.t, p.m % (kindOf(p)?.n || 1));
    const h = new THREE.Object3D(), b = new THREE.LineSegments(selBox.geometry, selBox.material);
    h.rotation.order = 'ZYX'; b.renderOrder = 20; h.add(b);
    h.position.set(p.x, p.y, propZ(p)); h.rotation.set(st.rx + (p.rx || 0), st.ry + (p.ry || 0), p.yaw); h.scale.setScalar(p.s);
    if (mdl) { const g = mdl.g; g.boundingBox || g.computeBoundingBox(); g.boundingBox.getCenter(b.position); g.boundingBox.getSize(b.scale); }
    else { b.position.set(0, 0, (d.zmin + d.zmax) / 2 * IN); b.scale.set(1.4 * d.r * IN, 1.4 * d.r * IN, Math.max(IN, (d.zmax - d.zmin) * IN)); }
    b.scale.max(new THREE.Vector3(IN / 2, IN / 2, IN / 2));
    return h;
  }
  function drawMany() {
    S.propMany = S.propMany.filter(p => S.props.includes(p));
    manyBoxes.clear();
    for (const p of S.propMany.slice(0, 400)) manyBoxes.add(boxFor(p));
    $('crpeinfo').innerHTML = `<b>${S.propMany.length} objets sélectionnés</b> · Maj+clic pour en ajouter / retirer`;
  }
  function selectMany(list) {
    list = [...new Set(list)].filter(p => S.props.includes(p));
    if (list.length < 2) { selectProp(list[0] || null); return; }
    S.propSelP = null; S.propDrag = null; selHold.visible = false;
    S.propMany = list; manyStart = null;
    const c = new THREE.Vector3();
    for (const p of list) c.add(new THREE.Vector3(p.x, p.y, propZ(p)));
    propPivot.position.copy(c.divideScalar(list.length)); propPivot.rotation.set(0, 0, 0); propPivot.scale.set(1, 1, 1);
    propPivot.updateMatrixWorld();
    $('crpeset').style.display = 'block'; $('crpefields').style.display = 'none'; $('crpewarn').hidden = true;
    panel.querySelector('[data-ptm="scale"]').disabled = true;
    ptc?.attach(propPivot);
    setPropGizmo(ptc?.getMode() === 'rotate' ? 'rotate' : 'translate');
    drawMany();
  }
  function manyBegin() {
    propPivot.updateMatrixWorld();
    manyStart = { M0: propPivot.matrixWorld.clone().invert(),
                  items: S.propMany.map(p => ({ p, x: p.x, y: p.y, z: propZ(p), dz: p.dz || 0, yaw: p.yaw })) };
  }
  const _mv = new THREE.Vector3(), _mq = new THREE.Quaternion(), _me = new THREE.Euler(0, 0, 0, 'ZYX');
  function manyDrag() {
    if (!manyStart) manyBegin();
    propPivot.updateMatrixWorld();
    const D = propPivot.matrixWorld.clone().multiply(manyStart.M0);
    _mq.setFromRotationMatrix(D); _me.setFromQuaternion(_mq, 'ZYX');
    for (const b of manyStart.items) {
      _mv.set(b.x, b.y, b.z).applyMatrix4(D);
      b.p.x = Math.round(_mv.x); b.p.y = Math.round(_mv.y);
      b.p.dz = Math.round(b.dz + _mv.z - b.z); if (Math.abs(b.p.dz) < 1) delete b.p.dz;
      b.p.yaw = +(b.yaw + _me.z).toFixed(3);
      delete b.p.ai; b.p.ed = 1;
      if (roadUnder(b.p) !== null) b.p.road = 1; else delete b.p.road;
      seats.delete(b.p);
    }
    renderProps();
  }
  function propTyped() {
    const p = S.propSelP; if (!p) return;
    const yaw = +$('crpeyaw').value, s = +$('crpes').value, dz = +$('crpedz').value;
    if (Number.isFinite(yaw)) p.yaw = +(yaw * Math.PI / 180).toFixed(3);
    for (const k of ['rx', 'ry']) {
      const v = +$('crpe' + k).value;
      if (Number.isFinite(v)) { const a = +(Math.max(-180, Math.min(180, v)) * Math.PI / 180).toFixed(3); if (a) p[k] = a; else delete p[k]; }
    }
    if (Number.isFinite(s) && s > 0) p.s = +Math.max(0.05, Math.min(100, s)).toFixed(2);
    if (Number.isFinite(dz)) { p.dz = Math.round(dz * IN); if (!p.dz) delete p.dz; }
    propChanged(p); syncPropSel(); saveDraft();
  }
  function propDelete() {
    if (manyActive()) {
      const gone = new Set(S.propMany), n = gone.size;
      S.props = S.props.filter(q => !gone.has(q)); selectProp(null); renderProps(); saveDraft();
      status(`${n} objets supprimés (Ctrl+Z pour annuler)`); return;
    }
    const p = S.propSelP; if (!p) return;
    S.props = S.props.filter(q => q !== p); selectProp(null); renderProps(); saveDraft(); status('Objet supprimé (Ctrl+Z pour annuler)');
  }
  function propDuplicate() {
    if (manyActive()) {
      // tout le groupe, decale d'un bloc (la plus grande emprise) : les copies deviennent la selection
      const step = Math.max(4 * IN, ...S.propMany.map(p => 1.2 * dimOf(p).r * IN * p.s));
      const copies = S.propMany.map(p => { const q = { ...p, x: Math.round(p.x + step), y: p.y }; delete q.u; return q; });
      for (const q of copies) { S.props.push(q); propChanged(q); }
      selectMany(copies); saveDraft();
      status(`${copies.length} objets dupliqués : les copies sont sélectionnées, déplace-les avec la poignée`); return;
    }
    const p = S.propSelP; if (!p) return;
    const step = Math.max(2 * IN, 1.2 * dimOf(p).r * IN * p.s), q = { ...p, x: Math.round(p.x + step * Math.cos(p.yaw)), y: Math.round(p.y + step * Math.sin(p.yaw)) };
    delete q.u;                                              // nouvel objet de la recette (comme extDuplicate)
    S.props.push(q); propChanged(q); selectProp(q); saveDraft(); status('Objet dupliqué : la copie est sélectionnée');
  }
  // clic : objet sous la souris (instance touchee), sinon le plus proche du point du sol clique
  function propPointerDown(e) {
    if (ptc?.axis) return;                                     // sur une poignee : le gizmo s'en occupe
    const b = canvas.getBoundingClientRect();
    ndc.set(((e.clientX - b.left) / b.width) * 2 - 1, -((e.clientY - b.top) / b.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    let p = null;
    for (const h of ray.intersectObject(propGroup, true)) {
      const L = h.object.userData.props;
      if (h.object.visible && L && h.instanceId != null && L[h.instanceId]) { p = L[h.instanceId]; break; }
    }
    if (!p) {
      const g = pick(e);
      if (g) { let bd = Infinity;
        for (const q of S.props) { const d = Math.hypot(q.x - g.x, q.y - g.y); if (d < Math.max(2 * IN, 0.6 * dimOf(q).r * IN * q.s) && d < bd) { bd = d; p = q; } } }
    }
    const add = e.shiftKey || e.ctrlKey || e.metaKey;
    if (!p) { if (!add) selectProp(null); return; }           // a cote : la vue tourne
    if (add) {                                                // Maj / Ctrl+clic : ajoute ou retire de la selection
      const cur = manyActive() ? [...S.propMany] : S.propSelP ? [S.propSelP] : [];
      const i = cur.indexOf(p); if (i >= 0) cur.splice(i, 1); else cur.push(p);
      selectMany(cur);
    } else selectProp(p);
    e.preventDefault(); e.stopImmediatePropagation();
  }
  addEventListener('keydown', e => {
    if (!S.active || !(S.propSelP || manyActive()) || S.mode !== 'props' || typing(e) || e.altKey) return;
    const k = e.key.toLowerCase();
    if (e.ctrlKey || e.metaKey) { if (k !== 'd') return; propDuplicate(); }
    else if (k === 'w' || k === 'z') setPropGizmo('translate');
    else if (k === 'e') setPropGizmo('rotate');
    else if (k === 'r') { if (!manyActive()) setPropGizmo('scale'); }
    else if (e.key === 'Delete') propDelete();
    else if (e.key === 'Escape') selectProp(null);
    else return;
    e.preventDefault(); e.stopImmediatePropagation();
  }, true);
  function setPropTool(t) {
    S.propErase = t === 'erase'; S.propEdit = t === 'edit';
    for (const [id, k] of [['crpsow', 'sow'], ['crperase', 'erase'], ['crpedit', 'edit']]) $(id).classList.toggle('primary', t === k);
    $('crbrushslot').hidden = S.propEdit; $('crpeditbox').hidden = !S.propEdit;
    if (S.propEdit) { S.brushing = false; brush.visible = false; status('Modifier : clique sur un objet du décor (clic droit : tourner la vue)'); }
    else selectProp(null);
  }
  const clampv = (v, [a, b]) => Math.max(a, Math.min(b, v));
  // distance le long du trace entre deux points bruts (boucle : par le plus court)
  function arcDists(i) {
    const P = S.points, n = P.length, cum = [0];
    for (let k = 1; k < n; k++) cum.push(cum[k - 1] + Math.hypot(P[k][0] - P[k - 1][0], P[k][1] - P[k - 1][1]));
    const tot = cum[n - 1] + (S.closed ? Math.hypot(P[0][0] - P[n - 1][0], P[0][1] - P[n - 1][1]) : 0);
    return cum.map(c => { const d = Math.abs(c - cum[i]); return S.closed ? Math.min(d, tot - d) : d; });
  }
  const edgeReach = () => +$('credger').value * IN;
  // points de la zone autour de i, dans l'ordre du trace (de l'extremite arriere a l'extremite avant ; boucle : par-dessus
  // la fermeture). Meme critere que les poids (distance le long du trace < etendue)
  function edgeZone(i) {
    const n = S.points.length, arc = arcDists(i), R = edgeReach(), step = k => S.closed ? (k + n) % n : k;
    let a = i, b = i;
    for (let g = 0; g < n; g++) { const k = step(a - 1); if (k < 0 || k === b || arc[k] >= R) break; a = k; }
    for (let g = 0; g < n; g++) { const k = step(b + 1); if (k >= n || k === a || arc[k] >= R) break; b = k; }
    const out = [a];
    for (let k = a; k !== b; ) { k = step(k + 1); out.push(k); }
    return out;
  }
  function setEdgeZone(m) {                                   // − / + : zone reduite / agrandie de 5 m
    const r = $('credger'), v = Math.max(+r.min, Math.min(+r.max, +r.value + m));
    r.value = v; $('credgerv').textContent = v; placeEdge();
  }
  // « Lisser » (2026-11-12) : largeur et releve du bord choisi en ligne droite (selon la distance le long du trace) entre
  // les deux extremites de la zone ; l'autre bord ne change pas
  function edgeSmooth() {
    const sel = S.edgeSel; if (!sel) return;
    const Z = edgeZone(sel.i);
    if (Z.length < 3) { status('Zone trop courte : agrandis-la (+) pour lisser', 'err'); return; }
    const k0 = sel.side > 0 ? 0 : 1, base = S.points.map(edgesOf), P = S.points;
    const s = [0];
    for (let j = 1; j < Z.length; j++) s.push(s[j - 1] + Math.hypot(P[Z[j]][0] - P[Z[j - 1]][0], P[Z[j]][1] - P[Z[j - 1]][1]));
    const A = base[Z[0]], B = base[Z[Z.length - 1]], tot = s[s.length - 1] || 1;
    for (let j = 1; j < Z.length - 1; j++) {
      const t = s[j] / tot, v = base[Z[j]].slice(), p = P[Z[j]];
      v[k0] = clampv(A[k0] + (B[k0] - A[k0]) * t, EDGE_W); v[k0 + 2] = clampv(A[k0 + 2] + (B[k0 + 2] - A[k0 + 2]) * t, EDGE_H);
      while (p.length < 5) p.push(p.length === 3 ? S.width : 0);
      p[5] = Math.round(v[0]); p[6] = Math.round(v[1]); p[7] = Math.round(v[2]); p[8] = Math.round(v[3]);
      p[3] = p[5] + p[6];
    }
    refreshTerrainMesh(); rebuild(); renderProps(); saveDraft(); placeEdge();
    status(`Bord ${sel.side > 0 ? 'gauche' : 'droit'} lissé sur ${Math.round(tot / IN)} m, entre les deux points blancs`, 'ok');
  }
  const weights = i => arcDists(i).map(d => d < edgeReach() ? 0.5 * (1 + Math.cos(Math.PI * d / edgeReach())) : 0);
  // poignee et trait sur le bord selectionne (gauche : side = 1, droit : -1)
  function placeEdge() {
    const sel = S.edgeSel; if (!sel) return;
    const E = effPoints(), q = E[sel.i], sd = sel.side, h = q[3] / 2;
    const ox = q[6] * sd, oy = q[7] * sd;
    edgeHandle.position.set(q[0] + ox * h, q[1] + oy * h, q[2] + 6 + sd * q[5]);
    edgeHandle.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(
      new THREE.Vector3(ox, oy, 0), new THREE.Vector3(-oy, ox, 0), new THREE.Vector3(0, 0, 1)));
    edgeHandle.visible = true;
    const w = weights(sel.i), pts = [];
    E.forEach((p, k) => { if (w[k] > 0) pts.push(p[0] + p[6] * sd * p[3] / 2, p[1] + p[7] * sd * p[3] / 2, p[2] + 30 + sd * p[5]); });
    edgeLine.geometry.dispose(); edgeLine.geometry = new THREE.BufferGeometry();
    edgeLine.geometry.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3)); edgeLine.visible = true;
    const Z = edgeZone(sel.i);
    [Z[0], Z[Z.length - 1]].forEach((k, j) => { const p = E[k];
      edgeEnds[j].position.set(p[0] + p[6] * sd * p[3] / 2, p[1] + p[7] * sd * p[3] / 2, p[2] + 30 + sd * p[5]); edgeEnds[j].visible = true; });
    const [wl, wr, hl, hr] = edgesOf(S.points[sel.i]);
    $('credgeinfo').innerHTML = `Bord <b>${sd > 0 ? 'gauche' : 'droit'}</b> (sens de la course)`;
    $('credgew').value = ((sd > 0 ? wl : wr) / IN).toFixed(1); $('credgeh').value = ((sd > 0 ? hl : hr) / IN).toFixed(1);
    $('credgeset').style.display = 'grid';
  }
  function selectEdge(sel) {
    S.edgeSel = sel;
    if (!sel) { tc?.detach(); edgeHandle.visible = edgeLine.visible = edgeEnds[0].visible = edgeEnds[1].visible = false; $('credgeset').style.display = 'none';
                $('credgeinfo').textContent = 'Clique sur un bord de la route.'; return; }
    placeEdge(); tc?.attach(edgeHandle);
  }
  function edgePointerDown(e) {
    if (tc?.axis) return;                                     // sur la poignee : le gizmo s'en occupe
    const b = canvas.getBoundingClientRect();
    ndc.set(((e.clientX - b.left) / b.width) * 2 - 1, -((e.clientY - b.top) / b.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    const hit = ray.intersectObject(road, false)[0];
    if (!hit) return;                                         // a cote de la route : la vue tourne
    const E = effPoints(); let best = 0, bd = Infinity;
    E.forEach((q, k) => { const d = Math.hypot(q[0] - hit.point.x, q[1] - hit.point.y); if (d < bd) { bd = d; best = k; } });
    const q = E[best], lat = (hit.point.x - q[0]) * q[6] + (hit.point.y - q[1]) * q[7];
    selectEdge({ i: best, side: lat >= 0 ? 1 : -1 });
    e.preventDefault(); e.stopImmediatePropagation();
  }
  // modifie les bords autour du point choisi : f(valeurs d'origine [wl, wr, hl, hr], poids) -> nouvelles valeurs
  function applyEdges(base, f) {
    const w = weights(S.edgeSel.i);
    S.points.forEach((p, k) => {
      if (!w[k] && !p[5]) return;
      const v = w[k] ? f(base[k], w[k]) : base[k];
      v[0] = clampv(v[0], EDGE_W); v[1] = clampv(v[1], EDGE_W); v[2] = clampv(v[2], EDGE_H); v[3] = clampv(v[3], EDGE_H);
      while (p.length < 5) p.push(p.length === 3 ? S.width : 0);
      p[5] = Math.round(v[0]); p[6] = Math.round(v[1]); p[7] = Math.round(v[2]); p[8] = Math.round(v[3]);
      p[3] = p[5] + p[6];
    });
    S.terrainDirty = true;
  }
  function edgeDragStart() { S.edgeBase = S.points.map(edgesOf); S.edgeFrom = edgeHandle.position.clone(); }
  function edgeDrag() {
    if (!S.edgeBase || !S.edgeSel) return;
    const sd = S.edgeSel.side, q = S.eff[S.edgeSel.i];
    const d = edgeHandle.position.clone().sub(S.edgeFrom);
    const dw = d.x * q[6] * sd + d.y * q[7] * sd, dh = d.z;
    const k0 = sd > 0 ? 0 : 1;
    applyEdges(S.edgeBase, (v, w) => { v = v.slice(); v[k0] += dw * w; v[k0 + 2] += dh * w; return v; });
  }
  function edgeDragEnd() {
    S.edgeBase = null; refreshTerrainMesh(); rebuild(); renderProps(); saveDraft(); placeEdge();
  }
  // valeurs tapees : le point choisi prend la valeur, les voisins suivent en fondu
  function edgeTyped() {
    const sel = S.edgeSel; if (!sel) return;
    const base = S.points.map(edgesOf), k0 = sel.side > 0 ? 0 : 1, cur = base[sel.i];
    const dw = +$('credgew').value * IN - cur[k0], dh = +$('credgeh').value * IN - cur[k0 + 2];
    applyEdges(base, (v, w) => { v = v.slice(); v[k0] += dw * w; v[k0 + 2] += dh * w; return v; });
    refreshTerrainMesh(); rebuild(); renderProps(); saveDraft(); placeEdge();
  }
  // remise d'origine (largeur du paveur, a plat) : autour du point choisi, ou partout
  function edgeReset(all) {
    const base = S.points.map(edgesOf);
    if (all) S.points.forEach(p => { if (p.length > 5) { p[3] = p[5] + p[6]; const nt = p[9]; p.length = 5; setNoTalus(p, nt); } });
    else applyEdges(base, (v, w) => { const h = (v[0] + v[1]) / 2; return [v[0] + (h - v[0]) * w, v[1] + (h - v[1]) * w, v[2] * (1 - w), v[3] * (1 - w)]; });
    refreshTerrainMesh(); rebuild(); renderProps(); saveDraft(); placeEdge();
  }

  // ---- outil Pont (2026-11-11) : clic sur un croisement -> la route cliquee monte au-dessus de l'autre, rampes en
  // cosinus de part et d'autre, sans talus sur le tablier (le sol suit alors le passage du dessous, conform). La
  // generation fait le reste comme pour un pont pose en conduisant (flancs du tablier a plus de 2,5 m du sol) ----
  const bridgeLine = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: 0x5ad1ff, depthTest: false }));
  bridgeLine.renderOrder = 19; bridgeLine.visible = false; group.add(bridgeLine);
  const bridgeMark = new THREE.Mesh(new THREE.SphereGeometry(2 * IN, 16, 12), new THREE.MeshBasicMaterial({ color: 0x5ad1ff, depthTest: false }));
  bridgeMark.renderOrder = 20; bridgeMark.visible = false; group.add(bridgeMark);
  // autre passage de la route au point i : point a moins d'une demi-largeur cumulee, loin le long du trace. -> indice ou -1
  function crossingAt(i) {
    const P = S.points, p = P[i], arc = arcDists(i), minArc = 2 * Math.max(p[3], 20 * IN) + 40 * IN;
    let best = -1, bd = Infinity;
    P.forEach((q, k) => {
      if (arc[k] < minArc) return;
      const d = Math.hypot(q[0] - p[0], q[1] - p[1]);
      if (d < (p[3] + q[3]) / 2 && d < bd) { bd = d; best = k; }
    });
    return best;
  }
  // la route au point i passe au-dessus de celle au point j : {dz, w (poids par point), target, error}
  function bridgePlan(i, j) {
    const P = S.points, n = P.length, H = +$('crbrh').value * IN;
    const dir = k => { const a = P[Math.max(0, k - 1)], b = P[Math.min(n - 1, k + 1)], l = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
                       return [(b[0] - a[0]) / l, (b[1] - a[1]) / l]; };
    const [ax, ay] = dir(i), [bx, by] = dir(j), sin = Math.abs(ax * by - ay * bx);
    // tablier plat au-dessus de toute la largeur de l'autre route (croisement en biais : plus long), + 8 m de marge
    const flat = P[j][3] / 2 / Math.max(0.35, sin) + 8 * IN;
    const di = arcDists(i), dj = arcDists(j);
    // rampes : jamais jusqu'au passage du dessous (il garde sa hauteur)
    const room = di[j] - 2 * flat - 10 * IN;
    if (room < 20 * IN) return { error: 'Les deux passages sont trop proches le long de la route pour y mettre des rampes', w: di.map(() => 0), dz: 0 };
    const ramp = Math.min(+$('crbrl').value * IN, room);
    // dessus de l'autre route sous le tablier (bords releves compris)
    let top = -Infinity;
    P.forEach((q, k) => { if (dj[k] < flat + P[j][3]) { const e = edgesOf(q); top = Math.max(top, q[2] + Math.max(Math.abs(e[2]), Math.abs(e[3]))); } });
    const want = top + H + 1.2 * IN;                     // + epaisseur du tablier
    const target = Math.min(S.groundZ + H_MAX, want);
    const w = di.map(d => d <= flat ? 1 : d < flat + ramp ? 0.5 * (1 + Math.cos(Math.PI * (d - flat) / ramp)) : 0);
    return { dz: target - P[i][2], w, target, ramp, short: ramp < +$('crbrl').value * IN, capped: target < want };
  }
  function selectBridge(sel) {
    S.bridgeSel = sel;
    if (!sel) {
      bridgeLine.visible = bridgeMark.visible = false; $('crbrgo').disabled = $('crbrswap').disabled = true;
      $('crbrinfo').textContent = 'Clique sur un croisement de la route.'; return;
    }
    showBridge();
  }
  function showBridge() {
    const sel = S.bridgeSel; if (!sel) return;
    const E = effPoints(), plan = bridgePlan(sel.i, sel.j), up = Math.max(0, plan.dz), pts = [];
    E.forEach((q, k) => { if (plan.w[k] > 0) pts.push(q[0], q[1], q[2] + 40 + up * plan.w[k]); });
    bridgeLine.geometry.dispose(); bridgeLine.geometry = new THREE.BufferGeometry();
    bridgeLine.geometry.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3)); bridgeLine.visible = pts.length > 3;
    bridgeMark.position.set(E[sel.i][0], E[sel.i][1], E[sel.i][2] + 40 + up); bridgeMark.visible = true;
    $('crbrinfo').innerHTML = plan.error ? `<span style="color:var(--err)">${plan.error}</span>`
      : (up > 0 ? `La route monte de <b>${(up / IN).toFixed(1)} m</b> (ligne bleue), rampes de ${Math.round(plan.ramp / IN)} m`
                : 'Cette route passe déjà assez haut : seul le talus sous le pont est retiré.')
        + (plan.short ? ' · rampes raccourcies (l\'autre passage est proche)' : '')
        // pente la plus forte d'une rampe en cosinus : dz * pi / (2 * rampe)
        + (!plan.error && up * Math.PI / (2 * plan.ramp) > 0.25
           ? ` · <span style="color:var(--err)">rampes très raides (${Math.round(Math.atan(up * Math.PI / (2 * plan.ramp)) * 180 / Math.PI)}°) : allonge-les</span>` : '')
        + (plan.capped ? ' · <span style="color:var(--err)">hauteur limitée (300 m au-dessus du départ)</span>' : '');
    $('crbrgo').disabled = !!plan.error; $('crbrswap').disabled = false;
  }
  function bridgePointerDown(e) {
    const b = canvas.getBoundingClientRect();
    ndc.set(((e.clientX - b.left) / b.width) * 2 - 1, -((e.clientY - b.top) / b.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    const hit = ray.intersectObject(road, false)[0];
    if (!hit) return;                                         // a cote de la route : la vue tourne
    // point le plus proche (hauteur comprise : sur un pont deja la, celui du dessus)
    const E = effPoints(); let best = 0, bd = Infinity;
    E.forEach((q, k) => { const d = Math.hypot(q[0] - hit.point.x, q[1] - hit.point.y, 2 * (q[2] + 6 - hit.point.z)); if (d < bd) { bd = d; best = k; } });
    const j = crossingAt(best);
    e.preventDefault(); e.stopImmediatePropagation();
    if (j < 0) { selectBridge(null); status('Pas d\'autre route à cet endroit : clique là où deux routes se croisent', 'err'); return; }
    selectBridge({ i: best, j });
  }
  function makeBridge() {
    const sel = S.bridgeSel; if (!sel) return;
    const plan = bridgePlan(sel.i, sel.j); if (plan.error) { status(plan.error, 'err'); return; }
    const up = Math.max(0, plan.dz);
    S.points.forEach((p, k) => {
      if (!plan.w[k]) return;
      p[2] += up * plan.w[k];
      if (plan.w[k] > 0.5) setNoTalus(p, true);              // tablier et haut des rampes : le sol reste dessous
    });
    S.terrainDirty = true; placeFromPoints(); refreshTerrainMesh(); rebuild(); renderProps(); saveDraft();
    status(up > 0 ? `Pont : la route monte de ${(up / IN).toFixed(1)} m au-dessus de l'autre (Ctrl+Z pour annuler)` : 'Pont : talus retiré sous le passage du dessus', 'ok');
    showBridge();
  }
  // essais automatiques seulement (adresse avec ?crtest) : fonctions de la Creation accessibles depuis la console
  if (/[?&]crtest\b/.test(location.search)) window.__crtest = { S, setMode, crossingAt, bridgePlan, selectBridge, makeBridge, tryProp, seatOf, roadUnder, undo, effPoints, applyBrush, pick, setTool, roofMask, roofMesh,
                                                                  refreshTerrainMesh, camera, orbit, saveDraft, ptc, propProxy, selectProp, propZ,
                                                                  waterBasin, renderWater, waterPointerDown, placeFromPoints, slopeOfEnd, selectEdge, edgeZone, edgeSmooth, setEdgeZone,
                                                                  randomTrack, parseRndCode, roadDistance, rndProgress, rndCode,
                                                                  kindOf, dimOf, rad, roleOf, apart, piecePoints, piece, startMark, group, clay, refreshTerrainMesh, sample };
  $('crmbridge').onclick = () => setMode('bridge');
  $('crbrh').oninput = e => { $('crbrhv').textContent = e.target.value; showBridge(); };
  $('crbrl').oninput = e => { $('crbrlv').textContent = e.target.value; showBridge(); };
  $('crbrgo').onclick = makeBridge;
  $('crbrswap').onclick = () => { const s = S.bridgeSel; if (s) selectBridge({ i: s.j, j: s.i }); };

  $('crmroute').onclick = () => setMode('route');
  $('crmterrain').onclick = () => setMode('terrain');
  $('crmpaint').onclick = () => setMode('paint');
  $('crmprops').onclick = () => setMode('props');
  $('crmedges').onclick = () => setMode('edges');
  $('credger').oninput = e => { $('credgerv').textContent = e.target.value; placeEdge(); };
  $('credgew').onchange = $('credgeh').onchange = edgeTyped;
  $('credgereset').onclick = () => edgeReset(false);
  $('credgesmooth').onclick = edgeSmooth;
  $('credgerminus').onclick = () => setEdgeZone(-5);
  $('credgerplus').onclick = () => setEdgeZone(5);
  addEventListener('keydown', e => {                          // - / + au clavier : zone reduite / agrandie
    if (!S.active || S.mode !== 'edges' || !S.edgeSel || typing(e) || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === '+' || e.code === 'NumpadAdd') setEdgeZone(5);
    else if (e.key === '-' || e.code === 'NumpadSubtract') setEdgeZone(-5);
    else return;
    e.preventDefault(); e.stopImmediatePropagation();
  }, true);
  $('credgeall').onclick = async () => { if (await ask('Remettre tous les bords à plat, avec la même largeur des deux côtés ?')) edgeReset(true); };
  $('crpsow').onclick = () => setPropTool('sow');
  $('crperase').onclick = () => setPropTool('erase');
  $('crpedit').onclick = () => setPropTool('edit');
  $('crwlevel').oninput = e => {
    const w = S.waters[S.waterSel]; if (!w) return;
    w.dz = Math.round(+e.target.value * IN); $('crwlv').textContent = (-+e.target.value).toFixed(1).replace('.', ',');
    scheduleWater();
  };
  $('crwlevel').onchange = saveDraft;
  $('crwplevel').oninput = e => {
    const w = S.waters[S.waterSel]; if (!w?.paint) return;
    w.level = w.base + Math.round(+e.target.value * IN); $('crwplv').textContent = (+e.target.value).toFixed(1).replace('.', ',');
    scheduleWater();
  };
  $('crwplevel').onchange = saveDraft;
  $('crwh').oninput = e => { $('crwhv').textContent = (+e.target.value).toFixed(1).replace('.', ','); };
  $('crwtype').innerHTML = Object.entries(WATER_TYPES).map(([k, [l]]) => `<option value="${k}">${l}</option>`).join('');
  $('crwtype').onchange = e => {
    S.waterType = e.target.value;
    const w = S.waters[S.waterSel]; if (w) { w.type = e.target.value; renderWater(); saveDraft(); }
  };
  panel.querySelectorAll('[data-wm]').forEach(b => b.onclick = () => setWaterMode(b.dataset.wm));
  $('crwclear').onclick = async () => {
    if (!S.waters.length || !(await ask('Retirer toute l\'eau des trous ?'))) return;
    S.waters = []; S.waterSel = -1; renderWater(); syncWaterLevel(); saveDraft();
  };
  panel.querySelectorAll('[data-ptm]').forEach(b => b.onclick = () => setPropGizmo(b.dataset.ptm));
  $('crpeyaw').onchange = $('crperx').onchange = $('crpery').onchange = $('crpes').onchange = $('crpedz').onchange = propTyped;
  $('crpeground').onclick = () => {
    if (manyActive()) { for (const p of S.propMany) { delete p.dz; propChanged(p); } selectMany([...S.propMany]); saveDraft(); return; }
    const p = S.propSelP; if (!p) return; delete p.dz; propChanged(p); syncPropSel(); saveDraft();
  };
  $('crpedup').onclick = propDuplicate;
  $('crpedel').onclick = propDelete;
  $('crpauto').onclick = sowAlongRoad;
  $('crpfar').oninput = e => { $('crpfarv').textContent = e.target.value; };
  $('crpfar').onchange = saveDraft;
  $('crpclear').onclick = async () => { if (S.props.length && !(await ask('Retirer tous les objets semés ?'))) return; S.props = []; renderProps(); saveDraft(); };
  panel.querySelectorAll('[data-tool]').forEach(b => b.onclick = () => setTool(b.dataset.tool));

  $('crradius').oninput = e => { S.radius = +e.target.value * IN; $('crr').textContent = e.target.value; };
  $('crstrength').oninput = e => { S.strength = +e.target.value / 100; $('crs').textContent = e.target.value + ' %'; };
  $('crspeed').oninput = e => { S.brushSpeed = +e.target.value; $('crspeedv').textContent = 'x' + e.target.value; };
  $('crtreset').onclick = async () => {                       // Relief : tout a plat ; Peinture : tout dans la 1re matiere
    const relief = S.mode === 'terrain';
    if (!(await ask(relief ? 'Remettre tout le relief à plat (la peinture reste) ?' : 'Effacer toute la peinture (le relief reste) ?'))) return;
    if (relief) { S.terrain.h.fill(0); S.terrain.dig?.fill(0); S.terrain.aih?.fill(0); } else S.terrain.paint.fill(0);
    refreshTerrainMesh(); rebuild(); renderProps(); saveDraft();
  };
  $('crwidth').oninput = e => setWidth(+e.target.value * IN);
  $('crbar').onchange = saveDraft;
  $('crsize').onchange = () => { resizeTerrain(+$('crsize').value); refreshTerrainMesh(); rebuild(); renderProps(); saveDraft(); };
  $('crkit').onchange = () => {
    applyKit(); renderProps(); saveDraft();                              // les objets semes gardent leur theme
  };
  $('crclose').onclick = closeLoop;
  $('crundo').onclick = undo; $('crredo').onclick = redo;
  // placer le kart : vue de haut, clic sur le terrain = nouveau point de depart. La route en part, donc elle repart de
  // zero, mais seulement au clic (Echap ou le bouton annulent sans rien perdre)
  function startPick(on) {
    S.pickStart = on;
    $('crstartpick').classList.toggle('primary', on);
    brush.visible = false;
    S.chase = !on && S.mode === 'route'; orbit.enabled = !S.chase;
    if (on) {
      orbit.target.copy(S.pos); camera.position.set(S.pos.x - 120 * IN, S.pos.y - 160 * IN, S.pos.z + 260 * IN);
      camera.up.set(0, 0, 1); camera.lookAt(S.pos); orbit.update();
      status('Clique sur le terrain pour y placer le kart (Échap : annuler ; clic droit : tourner la vue, molette : zoom)');
    }
  }
  $('crstartpick').onclick = async () => {
    if (S.pickStart) { startPick(false); return; }
    if (S.points.length > 1 && !(await ask('La route part du kart : le déplacer efface le tracé actuel, une fois le nouvel endroit cliqué. Continuer ?'))) return;
    startPick(true);
  };
  view.addEventListener('pointerdown', e => {
    if (!S.active || !S.pickStart || e.button !== 0 || e.target !== canvas) return;
    e.preventDefault(); e.stopImmediatePropagation();
    const p = pick(e);
    if (!p) { status('Clique sur le terrain', 'err'); return; }
    S.start = { pos: [p.x, p.y], yaw: S.yaw };
    startPick(false);
    resetPaver(); refreshTerrainMesh(); rebuild(); renderProps(); saveDraft();
    status('Kart placé : ← → pour l\'orienter, ↑ pour poser la route', 'ok');
  }, true);
  view.addEventListener('pointermove', e => {
    if (!S.active || !S.pickStart || e.target !== canvas) return;
    const p = pick(e);
    brush.visible = !!p;
    if (p) { brush.position.set(p.x, p.y, p.z + 20); brush.scale.set(S.width / 2, S.width / 2, 1); }
  });
  addEventListener('keydown', e => { if (S.active && S.pickStart && e.key === 'Escape') { startPick(false); e.stopImmediatePropagation(); } }, true);
  $('crreset').onclick = async () => {
    const T = S.terrain, hasRoad = S.points.length > 1;
    const hasRest = S.props.length > 0 || T.h.some(v => v !== 0) || T.paint.some(v => v !== 0) || !!T.dig?.some(v => v !== 0) || !!T.aih?.some(v => v !== 0);
    let all = false;
    if (hasRest) {                                            // relief, peinture ou objets : choisir ce qui part avec la route
      const c = await choose('Que veux-tu supprimer ?\n\nRecommencer depuis le départ efface le tracé. Tu peux aussi effacer le relief, la peinture et les objets posés.',
                             ['Juste la route', 'Tout (route, relief, peinture, objets)']);
      if (c < 0) return;
      all = c === 1;
    } else if (hasRoad && !(await ask('Supprimer tout le tracé et recommencer au départ ?'))) return;
    if (all) {
      S.props = []; T.h.fill(0); T.paint.fill(0); T.dig?.fill(0); T.aih?.fill(0);
      S.points = S.points.slice(0, 1);                        // sol recalcule sans l'ancienne route, avant de reposer le kart dessus
      refreshTerrainMesh();
    }
    resetPaver();
    // sol recalcule dans tous les cas (2026-11-12) : talus, remblais et creusements suivaient l'ancienne route (route en
    // montee / descente) ; sans ce calcul ils restaient affiches apres « Juste la route » / sans relief peint
    refreshTerrainMesh();
    rebuild(); renderProps(); saveDraft();
  };
  // « Vider la map » de l'Edition (2026-11-20, retour utilisateur « tout coche, les objets sont toujours la ») : la base
  // (route, relief, peinture, eau, decor seme, caisses de la piste aleatoire) remise a zero. Sur une creation, l'Edition
  // l'affiche par-dessus la map tant qu'elle n'est pas generee : vider la map seule ne la touchait pas. Brouillon suivi
  // par l'historique des pistes (« ↶ Annuler » le remet)
  // avant « Vider la map » : base actuelle copiee sur le serveur, pour que l'etape de l'historique la contienne
  async function saveBaseToServer() {
    if (S.loadedTrack !== getTrack()) return;
    if (draftTimer) writeDraft();
    await postDraft(getTrack(), draftData());
  }
  // fichiers remis par l'historique (« ↶ Annuler ») : base relue a la prochaine occasion (apercu, outils de base)
  function forget() { if (!S.active && !S.opening) S.loadedTrack = null; }
  async function clearBase() {
    if (S.loadedTrack !== getTrack()) await loadQuiet();
    if (S.loadedTrack !== getTrack()) return false;
    const T = S.terrain;
    S.props = []; S.waters = []; S.waterSel = -1; S.items = null; S.rndCode = ''; S.rndLook = null; S.rndFresh = false;
    T.h.fill(0); T.paint.fill(0); T.dig?.fill(0); T.aih?.fill(0);
    S.points = S.points.slice(0, 1);
    resetPaver(); refreshTerrainMesh(); rebuild(); renderProps(); renderWater(); renderItems();
    histReset(); clearTimeout(draftTimer); draftTimer = 0;
    // brouillon vide gardé sur le SERVEUR seulement (copie du navigateur retiree) : « ↶ Annuler » remet celui d'avant
    // (copie envoyee par saveBaseToServer avant le vidage), relu ensuite (forget)
    try { await postDraft(getTrack(), draftData()); } catch (e) { /* le navigateur garde alors la base videe */ }
    try { localStorage.removeItem(draftKey()); } catch (e) { /* sans importance */ }
    S.hasBase = false; S.generated = false; S.genDirty = false; S.editN = 0;   // plus de base ni de generation (recette retiree par le serveur)
    if (!S.active) group.visible = false;
    return true;
  }
  // part de la carte a plus de FAR_TRIM_M de la route (echantillonnee) et objets semes concernes
  function farFromRoad() {
    const T = S.terrain, E = effPoints();
    if (!T || E.length < 2) return null;
    const pts = E.filter((_, k) => k % 2 === 0), r2 = (FAR_TRIM_M * IN) ** 2;
    const isFar = (x, y) => { for (const q of pts) if ((q[0] - x) ** 2 + (q[1] - y) ** 2 <= r2) return false; return true; };
    const step = Math.max(1, Math.floor(T.n / 120));
    let nf = 0, nt = 0;
    for (let j = 0; j < T.n; j += step) for (let i = 0; i < T.n; i += step) { nt++; if (isFar(T.x0 + i * T.cell, T.y0 + j * T.cell)) nf++; }
    return { share: nf / nt, props: S.props.filter(p => isFar(p.x, p.y)).length };
  }
  // « Appliquer le décor » (B4, 2026-11-14) : seul le decor seme a change depuis la derniere generation de cette piste ->
  // objets reposes en quelques secondes sur le sol deja genere, au lieu de tout regenerer. true : traite (ou annule)
  const buildReq = (track, extra = {}) => ({ track, points: S.points, closed: S.closed, ground_z: S.groundZ, kit: $('crkit').value,
                                              barriers: $('crbar').value, marks: S.marks, signs: S.signs, props: S.props, waters: S.waters,
                                              terrain: packFull(S.terrain), ...extra });
  async function fastApply() {
    let r;
    try { r = await api('/api/creator_props_apply', buildReq(getTrack(), { props: [], dry: true })); } catch (e) { return false; }
    if (!r?.ok) return false;
    const c = await choose('Depuis la dernière génération de cette piste, seul le décor a changé.\n\nL\'appliquer tout de suite '
      + '(quelques secondes) ? Le sol, la route et l\'eau ne bougent pas.', ['⚡ Appliquer le décor', 'Tout regénérer']);
    if (c === 1) return false;
    if (c < 0) return true;
    $('crgo').disabled = true;
    try {
      // modifications de l'Edition pas encore enregistrees (objets deplaces, parcours, caisses...) : enregistrees
      // d'abord, sinon la piste relue apres l'application les effacait (2026-11-19)
      if (ctx.beforeGenerate && !(await ctx.beforeGenerate())) return true;
      const sent = S.props.slice();
      status('Décor de la Création appliqué à la piste…');
      const a = await api('/api/creator_props_apply', buildReq(getTrack(), { props: sent }));
      if (!a.ok) { status(`Décor non appliqué : ${a.reason}. Utilise « Tout regénérer ».`, 'err'); return true; }
      (a.uids || []).forEach((u, i) => { if (u && sent[i]) sent[i].u = u; });
      writeDraft();
      S.genDirty = false; genMark();
      await ctx.onPropsApplied?.(a);
      status(a.report.filter(Boolean).join(' · '), 'ok');
    } catch (e) { status('Erreur : ' + e.message, 'err'); }
    finally { $('crgo').disabled = false; }
    return true;
  }
  $('crgo').onclick = async () => {
    if (await fastApply()) return;
    // ou generer : piste selectionnee ou nouvelle piste (nom, categorie), choix explicite avant tout le reste
    const target = await chooseTarget();
    if (!target) return;
    // ajouts faits dans Edition (imports, bibliotheque, copies, caisses, boosters) toujours gardes et reposes sur le
    // nouveau sol (server creator_reseat, 2026-11-14 : plus de choix « Repartir de zéro / Garder »). Pour tout retirer :
    // Edition > Nouvelle map. Nouvelle piste : rien a garder (caisses de Crash Cove retirees)
    // piste aleatoire (case « Retirer mes ajouts d'Édition », cochee de base) : ils etaient places pour l'ancienne piste
    const wipe = !!target.isNew || !!S.rndFresh;
    if (!target.isNew && !(await ask('Générer la piste ? Le sol et le décor d\'origine sont retirés, la création précédente est remplacée, '
        + 'puis le parcours et les IA sont créés et enregistrés (≈ 1 à 3 min).\n\n' + (S.rndFresh
          ? 'Piste aléatoire : tes ajouts faits dans Édition (objets, imports, copies, caisses, boosters, lumières, objets animés) sont retirés, ils étaient placés '
            + 'pour l\'ancienne piste (« ↶ Annuler » pour revenir).'
          : 'Tes ajouts faits dans Édition (objets, imports, copies, caisses, boosters) sont gardés et reposés sur le nouveau sol.')))) return;
    // beaucoup de carte loin de la route : le jeu la charge pour rien. Retrait a la generation seulement, le brouillon reste complet
    let trim = false;
    const far = farFromRoad();
    if (far && far.share >= FAR_TRIM_SHARE) {
      const t = await choose(`${Math.round(far.share * 100)} % de la carte est à plus de ${FAR_TRIM_M} m de la route : personne n'y roule, mais le jeu doit la charger.\n\n`
        + `La retirer de la piste générée ? Le relief et la peinture n'y seront pas, mais la découpe contourne les ${far.props} objet(s) et l'eau qui s'y trouvent : le sol reste sous eux. Ton brouillon reste complet : tu pourras regénérer sans retrait.`,
        ['✂ Retirer cette partie', 'Tout garder']);
      if (t < 0) return;
      trim = t === 0;
    }
    $('crgo').disabled = true;
    try {
      // modifications de l'Edition pas encore enregistrees : enregistrees avant (sinon perdues, 2026-11-19).
      // Nouvelle piste : elles concernent l'ancienne, enregistrees aussi (rien n'est jete sans le dire)
      if (ctx.beforeGenerate && !(await ctx.beforeGenerate())) return;
      const dest = target.isNew ? await createTarget(target) : getTrack();
      status('Génération de la piste…');
      const sent = S.props.slice();
      const r = await api('/api/create_build', buildReq(dest, { props: sent, wipe,
                                                               terrain: { ...packFull(S.terrain), ...(trim ? { trim_m: FAR_TRIM_M } : {}) } }));
      // identifiant de chaque objet du decor : ses retouches dans Edition reviennent dans ce brouillon (applyPatch)
      (r.uids || []).forEach((u, i) => { if (u && sent[i]) sent[i].u = u; });
      const look = S.rndLook;                                    // ciel / meteo de la piste aleatoire : poses une seule fois
      S.rndLook = null; S.rndFresh = false;
      writeDraft();
      S.genDirty = false; genMark();
      await onGenerate({ ...r, wipe, look, track: dest, items: S.items });
    } catch (e) { status('Erreur : ' + e.message, 'err'); }
    finally { rebuild(); }
  };

  // pipeline (2026-11-21, map complete d'une traite) : generation de la base en cours, sans question (cible = piste
  // selectionnee, rien retire au loin, pas de « décor seul ? »), nohist : sans copie pour « Annuler ». Ne touche pas a la vue :
  // la suite (parcours, IA, caisses, chutes) est faite par la page (index.html runPipeline)
  async function generateNow(opt = {}) {
    if (S.loadedTrack !== getTrack()) throw new Error('base non chargée');
    if (!S.closed || S.points.length < 8) throw new Error('route non fermée');
    const wipe = opt.wipe ?? !!S.rndFresh;
    const sent = S.props.slice();
    const r = await api('/api/create_build', buildReq(getTrack(), { props: sent, wipe, nohist: !!opt.nohist, terrain: packFull(S.terrain) }));
    (r.uids || []).forEach((u, i) => { if (u && sent[i]) sent[i].u = u; });
    const look = S.rndLook;
    S.rndLook = null; S.rndFresh = false;
    writeDraft();
    S.genDirty = false; genMark();
    return { ...r, wipe, look, track: getTrack(), items: S.items };
  }

  // une seule ouverture a la fois : le serveur repond en quelques secondes ; une 2e ouverture memorisait la vue deja
  // masquee, que la fermeture remettait ensuite (apercu toujours affiche, splines cachees)
  async function open() {
    // chargement en arriere-plan en cours (loadQuiet) : attendu, puis ouverture (avant : ouverture ignoree)
    while (S.opening && S.loadP) { try { await S.loadP; } catch (e) { /* sans importance */ } }
    if (S.active || S.opening) return;
    S.opening = true;
    try { await openNow(); } finally { S.opening = false; }
  }
  // donnees de la base de la piste (brouillon, sinon derniere generation) -> S et maillages de l'apercu ; sans rien afficher :
  // aussi appele a l'ouverture d'une piste (loadQuiet), pour l'apercu de la base dans l'Edition (2026-11-14)
  async function loadBase() {
    S.loadedTrack = null;
    // piste figee au debut (2026-11-15) : son nom etait relu apres les attentes ; un changement de piste pendant le
    // chargement etiquetait la base de l'ANCIENNE piste avec le nom de la nouvelle -> outils de base ouverts sur une base
    // vide (ou celle d'une autre piste), jamais rechargee
    const trk = getTrack();
    if (S.baseTrack !== trk) { S.editN = 0; S.baseTrack = trk; }   // modifications comptees par piste
    await loadKart();
    const st = getStart();
    S.start = { pos: st.pos, yaw: st.yaw }; S.groundZ = st.groundZ;
    far.position.set(st.pos[0], st.pos[1], S.groundZ - 60);
    let info = { saved: null, kits: { sable: 'Plage de sable (Crash Cove)' } };
    try { info = await (await fetch('/api/creator?track=' + encodeURIComponent(trk))).json(); } catch (e) { /* sans importance */ }
    $('crkit').innerHTML = (info.order || Object.keys(info.kits)).map(k => [k, info.kits[k]]).map(([k, l]) => `<option value="${k}">${l}</option>`).join('');
    let draft = null;
    try { draft = JSON.parse(localStorage.getItem('ctr_creator_' + trk) || 'null'); } catch (e) { /* sans importance */ }
    // copie du brouillon sur le serveur (« Enregistrer ») : prise si ce navigateur n'en a pas, ou une plus ancienne
    if (info.draft?.points && (!draft || (info.draft.at || 0) > (draft.at || 0))) draft = info.draft;
    // brouillon sans route mais avec son kart (place ou route supprimee) : il l'emporte sur la derniere piste generee
    const src = draft?.points?.length > 1 || draft?.start?.pos ? draft : info.saved;
    if (src?.points?.length > 1) S.start = { pos: [src.points[0][0], src.points[0][1]],
                                             yaw: Math.atan2(src.points[1][1] - src.points[0][1], src.points[1][0] - src.points[0][0]) };
    else if (src?.start?.pos) S.start = src.start;
    const t = src?.terrain;
    if (t?.n > 2 && t.h?.length === t.n * t.n)
      S.terrain = { x0: t.x0, y0: t.y0, cell: t.cell || T_CELL, n: t.n, size: t.size || Math.round((t.n - 1) * (t.cell || T_CELL) / IN),
                    h: Float32Array.from(t.h), paint: Uint8Array.from(t.paint),
                    dig: t.dig?.length === t.n * t.n ? Uint8Array.from(t.dig) : new Uint8Array(t.n * t.n),
                    aih: t.aih ? unpackI16(t.aih, t.n) : undefined };
    else S.terrain = newTerrain(S.start, 1600);
    // taille retiree de la liste (0,8 km) : terrain reechantillonne a la plus proche proposee. Brouillon deja en 3,6 / 4 km :
    // garde tel quel (le reduire couperait sa route), sa taille reste proposee pour lui seul
    const big = S.terrain.size > T_SIZES[T_SIZES.length - 1];
    if (big && ![...$('crsize').options].some(o => +o.value === S.terrain.size))
      $('crsize').add(new Option(`${sizeLabel(S.terrain.size)} km × ${sizeLabel(S.terrain.size)} km`, String(S.terrain.size)));
    if (!big && !T_SIZES.includes(S.terrain.size))
      resizeTerrain(T_SIZES.reduce((a, b) => Math.abs(b - S.terrain.size) < Math.abs(a - S.terrain.size) ? b : a));
    // sol du trace repris : la grille de la scene peut etre ailleurs (jeu restaure, piste regeneree) et le terrain se
    // retrouvait loin au-dessus de la route (T901 : sol a 174 m, route de 28 a 108 m, au fond d'un canyon). Le 1er point
    // est pose sur le terrain : valeur enregistree si elle colle a ce point (20 m pres, relief sculpte), sinon deduite
    if (src?.points?.length > 1) {
      const p0 = src.points[0], fromTrace = p0[2] - sample(S.terrain.h, p0[0], p0[1]);
      // valeur enregistree jugee sur TOUTE la route (mediane), pas sur son 1er point : piste aleatoire T915 (2026-11-14), depart
      // sur un remblai 34 m au-dessus du relief -> sol remonte de 34 m a chaque reouverture, puis a la generation
      const offs = src.points.filter((_, k) => k % 4 === 0).map(p => p[2] - sample(S.terrain.h, p[0], p[1])).sort((a, b) => a - b);
      const med = offs[offs.length >> 1];
      S.groundZ = Number.isFinite(src.ground_z) && Math.abs(src.ground_z - med) < 40 * IN ? src.ground_z : fromTrace;
      // meme route que la derniere generation : sa hauteur de base fait foi (brouillon deja decale par l'ancienne regle)
      const g = info.saved, same = (a, b) => a && b && a.length === b.length && [0, 1, a.length >> 1, a.length - 1].every(k => String(a[k]) === String(b[k]));
      if (Number.isFinite(g?.ground_z) && same(g.points, src.points)) S.groundZ = g.ground_z;
      far.position.z = S.groundZ - 60;
    } else if (Number.isFinite(src?.ground_z)) { S.groundZ = src.ground_z; far.position.z = S.groundZ - 60; }
    $('crsize').value = String(S.terrain.size);
    $('crbar').value = src?.barriers || 'curves';
    setMarks(src?.marks); setSigns(src?.signs);
    S.rndCode = typeof src?.rnd === 'string' ? src.rnd : '';      // code de la piste aleatoire (propose a la reouverture)
    S.rndLook = src?.look && typeof src.look === 'object' ? src.look : null;   // ciel / meteo tires, poses a la generation
    S.rndFresh = !!src?.fresh;                                     // ajouts d'Edition a retirer a la generation
    S.items = src?.items && Array.isArray(src.items.boosts) ? src.items : null;   // caisses / boosters a poser (piste aleatoire)
    setBlend(Number.isFinite(src?.terrain?.blend) ? src.terrain.blend : BLEND_DEF);
    setFade(Number.isFinite(src?.terrain?.fade) ? src.terrain.fade : FADE_DEF);
    S.info = info;
    if (src?.kit && info.kits[src.kit]) $('crkit').value = src.kit;
    // anciens brouillons : objets et choix sans theme = theme du brouillon
    const k0 = src?.kit && info.kits[src.kit] ? src.kit : 'sable';
    S.sel = new Set((Array.isArray(src?.sel) ? src.sel : []).map(s => s.split('|').length === 2 ? k0 + '|' + s : s)
      // choix du pinceau d'avant le reclassement du decor (2026-11-17) : meme modele dans sa nouvelle famille
      .map(s => { if (src?.cat === CAT_VERSION) return s; const [k, t, m] = s.split('|'), lst = info.remap?.[k]?.[t];
                  const r = lst?.length ? lst[(+m || 0) % lst.length] : null; return r ? `${k}|${r[0]}|${r[1]}` : s; }));
    $('crpfar').value = String(src?.far || 60); $('crpfarv').textContent = $('crpfar').value;
    applyKit();
    S.props = (Array.isArray(src?.props) ? src.props : []).map(p => migrateProp(p.k ? p : { ...p, k: k0 }, info));
    S.waters = Array.isArray(src?.waters) ? src.waters.filter(w => (Number.isFinite(w?.x) && Number.isFinite(w?.y)) || (w?.paint && Array.isArray(w.v) && Number.isFinite(w.level))) : [];
    for (const w of S.waters) if (!w.paint && [0.3, 1].some(d => Math.abs((w.dz ?? WATER_DZ) + d * IN) < 0.01)) w.dz = WATER_DZ;   // anciens defauts 30 cm / 1 m -> 5 m
    S.waterSel = -1;
    clay.unpack(src?.terrain?.clay);                         // retouches de la pate (essai)
    if (src?.points?.length > 1) {
      S.points = src.points; S.closed = !!src.closed; setWidth(src.width || src.points[src.points.length - 1][3] || W_DEF);
      placeFromPoints();
    } else { setWidth(W_DEF); resetPaver(); }
    refreshTerrainMesh();
    renderItems();                                           // apres la route : caisses / boosters reposes dessus
    // base de cette piste chargee (apercu dans l'Edition, « Générer la piste » depuis l'Edition) ; differe-t-elle de la
    // derniere generation ? (verification du serveur ; une modification faite entre-temps l'emporte). hasBase : une route
    // existe (sinon pas d'apercu : piste du jeu jamais creee, nouvelle map vide)
    S.loadedTrack = trk;                                   // piste changee entre-temps : rechargee (loadQuiet / openNow)
    histReset();                                           // historique de la base : repart de cette piste
    S.genSnap = null;                                      // etat de la derniere generation (genAgain) : inconnu ici
    S.hasBase = (src?.points?.length > 1) || (info.saved?.points?.length > 1);
    S.generated = info.saved?.points?.length > 1;              // une generation existe (sinon : map importee possible)
    const n0 = S.editN || 0;
    S.genDirty = !(info.saved?.points?.length > 1);
    if (!S.genDirty) (async () => {
      let dirty = true;
      try {
        const r = await api('/api/creator_props_apply', buildReq(trk, { props: [], dry: true }));
        dirty = !r?.ok || JSON.stringify(S.props) !== JSON.stringify((info.saved.props || []).map(p => p.k ? p : { ...p, k: info.saved.kit || 'sable' }));
      } catch (e) { /* inconnu : signale comme a generer */ }
      if ((S.editN || 0) === n0) { S.genDirty = dirty; if (!dirty) S.genSnap = histSnap(); }
      ctx.onBaseState?.();
    })();
    return info;
  }
  // objet seme avant le reclassement du decor (2026-11-17) : famille et numero de l'ancien catalogue -> meme modele dans le
  // nouveau (table du serveur, track_creator.remap_table) ; marque c = version du catalogue (deja converti : inchange)
  function migrateProp(p, info) {
    const v = info?.cat || CAT_VERSION;
    if (!p || p.c === v) return p;
    const lst = info?.remap?.[p.k]?.[p.t], r = lst?.length ? lst[(+p.m || 0) % lst.length] : null;
    return r ? { ...p, t: r[0], m: r[1], c: v } : { ...p, c: v };
  }
  async function openNow() {
    // base deja en memoire pour cette piste (chargee en arriere-plan, ou Creation deja ouverte) : gardee telle quelle, pas
    // relue du brouillon (une ecriture ratee faisait revenir l'ancienne base, 2026-11-14)
    if (S.loadedTrack !== getTrack()) await loadBase();
    $('crr').textContent = Math.round(S.radius / IN); $('crs').textContent = Math.round(S.strength * 100) + ' %';
    S.savedVis = scene.children.filter(c => !c.userData.keepInCreator).map(c => [c, c.visible]);
    // tout l'editeur masque, sauf la meteo (2026-11-24 : « pourquoi la meteo n'est pas affichee dans les outils de base »)
    scene.children.forEach(c => { if (c !== group && !c.isLight && !c.userData.keepInCreator) c.visible = false; });
    // ajouts faits dans Edition (objets, caisses, boosters) visibles aussi ici (case « Ajouts d'Édition », retenue)
    try { $('crghost').checked = localStorage.getItem(GHOST_KEY) !== '0'; } catch (e) { /* sans importance */ }
    $('crghost').onchange = () => {
      try { localStorage.setItem(GHOST_KEY, $('crghost').checked ? '1' : '0'); } catch (e) { /* sans importance */ }
      ctx.showEdition?.($('crghost').checked);
    };
    ctx.showEdition?.($('crghost').checked && !S.rndFresh);         // piste aleatoire : ajouts d'Edition retires a la generation
    // barre de droite : seul le panneau de creation (titre et selection de l'editeur masques)
    // (l'en-tete unique de l'inspecteur reste : il affiche l'outil de base en cours)
    // 2026-11-18 (« panneau de droite vide » apres des allers-retours Decor / Deplacer) : un element deja cache PAR LA
    // CREATION (dataset.crHidden) garde son etat d'origine (visible) au lieu d'etre note « cache » et remis cache a la fermeture
    if (ctx.details) S.hostVis = [...ctx.details.children].filter(c => c !== panel && c.id !== 'inshd').map(c => {
      const h = c.dataset.crHidden ? c.dataset.crHidden === 'h' : c.hidden;
      c.dataset.crHidden = h ? 'h' : 'v'; c.hidden = true; return [c, h];
    });
    // profondeur plus precise : dans la Creation, rien n'est regarde a moins de 2,5 m (scintillement au loin : -70 %)
    S.savedNear = camera.near; camera.near = 100; camera.updateProjectionMatrix();
    try { $('crq').value = localStorage.getItem(Q_KEY) || 'auto'; } catch (e) { /* sans importance */ }
    if (!$('crq').value) $('crq').value = 'auto';
    Q.sum = Q.n = 0; Q.from = 0; Q.wait = 60000; Q.bad = 0;
    setQuality(qMode() === 'auto' ? 0 : +qMode());
    $('crq').onchange = () => {
      try { localStorage.setItem(Q_KEY, qMode()); } catch (e) { /* sans importance */ }
      Q.sum = Q.n = 0; setQuality(qMode() === 'auto' ? 0 : +qMode());
      S.propsDirty = true;                                   // detail des objets : suit le reglage
    };
    groundParts(true); if (S.waterGroup) S.waterGroup.visible = true;      // cases d'Affichage de l'Edition sans effet ici
    group.visible = true; propGroup.visible = true; panel.hidden = false; topbar.hidden = false; S.active = true; S.last = 0;
    startMark.visible = true; delete startMark.userData.pvHidden;   // cache par l'apercu de l'Edition
    setTool(S.tool); setPaint(S.paint); setMode('route');
    rebuild(); renderProps();
    if (S.histTrack !== S.loadedTrack) histReset(); else histButtons();   // etapes faites depuis l'Edition gardees
    status('Création : conduis le paveur (↑ avancer, ← → tourner, R / F monter / descendre) — onglet Terrain pour sculpter le sol');
  }
  // ouverture d'une piste dans l'editeur : base chargee sans ouvrir la Creation (apercu dans l'Edition si elle n'est pas generee)
  async function loadQuiet() {
    if (S.active || S.opening || S.loadedTrack === getTrack()) return;
    S.opening = true;
    S.loadP = (async () => { await loadBase(); rebuild(); renderProps(); if (!S.active) group.visible = false; })();
    try { await S.loadP; }
    catch (e) { console.warn('base non chargee', e); }
    finally { S.opening = false; S.loadP = null; }
    if (!S.active && S.loadedTrack !== getTrack()) return loadQuiet();     // piste changee pendant le chargement
  }
  // apercu de la base dans l'Edition, Creation fermee (2026-11-14) : sol, route, decor seme et eau de la Creation, sans paveur
  // ni poignees ; meshes de sol pour poser les caisses / objets dessus (index.html groundZ)
  // withProps : decor seme de l'apercu aussi (sinon celui de la piste generee, selectionnable, s'affiche a sa place)
  function preview(on, withProps = true) {
    if (S.active) return;
    group.visible = !!on && S.loadedTrack === getTrack();
    const pv = S.pv || {};                                    // cases d'Affichage de l'Edition (previewParts)
    propGroup.visible = !!withProps && pv.props !== false;
    if (S.waterGroup) S.waterGroup.visible = pv.water !== false;
    groundParts(pv.ground !== false);
    // cercle vert du depart (« fermer la boucle ») : repere des outils de base seulement (2026-11-23 : il restait affiche
    // dans l'Edition)
    for (const o of [paver, brush, ghost, edgeHandle, edgeLine, bridgeLine, bridgeMark, selHold, startMark]) o.visible = false;
  }
  // Edition : objet du decor de l'apercu sous le rayon (plus proche que maxDist) -> son rang dans S.props, sinon -1
  function previewPropAt(r, maxDist = Infinity) {
    if (!group.visible || !propGroup.visible) return -1;
    for (const h of r.intersectObject(propGroup, true)) {
      if (h.distance > maxDist) break;
      const L = h.object.userData.props;
      if (h.object.visible && L && h.instanceId != null && L[h.instanceId]) return S.props.indexOf(L[h.instanceId]);
    }
    return -1;
  }
  // objet du decor de la base manipule avec les outils de l'EDITION (2026-11-14) : boite jaune + proxy sur lequel l'Edition
  // accroche ses poignees ; memes regles que l'outil Modifier (pose au sol, decalage de hauteur, objet « a la main »)
  function extSelect(i) {
    const p = S.props[i]; if (!p) return null;
    S.propSelP = p; S.propDrag = null; syncPropSel();
    propProxy.position.set(p.x, p.y, propZ(p)); propProxy.rotation.set(p.rx || 0, p.ry || 0, p.yaw); propProxy.scale.setScalar(p.s);
    return propProxy;
  }
  function extDeselect() { S.propSelP = null; S.propDrag = null; selHold.visible = false; }
  // retouche d'un objet de la base faite depuis l'Edition : etape d'annulation (histCommit) et l'Edition prevenue (sa pile
  // d'annulation melange ses etapes et celles-ci, dans l'ordre)
  function extEdited() { if (!S.active) S.extPending = true; }
  function extInfo() {
    const p = S.propSelP; if (!p) return null;
    const k = kindOf(p);
    return { name: k?.names?.[p.m % (k?.n || 1)] || p.t, label: k?.label || p.t, x: p.x, y: p.y, z: propZ(p), yaw: p.yaw, s: p.s,
             off: !!seatOf(p).off, index: S.props.indexOf(p) };
  }
  function extDelete() {
    const p = S.propSelP; if (!p) return;
    S.props.splice(S.props.indexOf(p), 1); extDeselect(); renderProps(); saveDraft(); extEdited();
  }
  function extDuplicate() {
    const p = S.propSelP; if (!p) return -1;
    const step = Math.max(2 * IN, 1.2 * dimOf(p).r * IN * p.s);
    const q = { ...p, x: Math.round(p.x + step * Math.cos(p.yaw)), y: Math.round(p.y + step * Math.sin(p.yaw)) };
    delete q.u;                                              // nouvel objet de la recette
    S.props.push(q); propChanged(q); saveDraft(); extEdited();
    return S.props.length - 1;
  }
  // valeurs tapees dans l'Edition : position (pouces), cap (radians), taille
  function extSet(v) {
    const p = S.propSelP; if (!p) return;
    if (Number.isFinite(v.x)) p.x = Math.round(v.x);
    if (Number.isFinite(v.y)) p.y = Math.round(v.y);
    if (Number.isFinite(v.yaw)) p.yaw = +v.yaw.toFixed(3);
    if (Number.isFinite(v.s)) p.s = +Math.max(0.05, Math.min(100, v.s)).toFixed(2);
    propChanged(p); syncPropSel(); saveDraft(); extEdited();
    propProxy.position.set(p.x, p.y, propZ(p)); propProxy.rotation.set(p.rx || 0, p.ry || 0, p.yaw); propProxy.scale.setScalar(p.s);
  }
  // plusieurs objets de la base (outil Cadre de l'Edition, 2026-11-14) : test(x, y, z) -> dans le cadre ; geste applique par
  // une matrice (pivot de l'Edition) depuis la pose de depart ; deplacer / tourner autour du centre / supprimer
  function propsInRect(test) {
    if (!group.visible || !propGroup.visible) return [];
    const out = [];
    S.props.forEach((p, i) => { if (kindOf(p) && !propHidden.has(p) && !seatOf(p).off && test(p.x, p.y, propZ(p))) out.push(i); });
    return out;
  }
  // H / Maj+H de l'Edition sur les objets de la base : caches / tous reaffiches (rien ne change a la generation)
  function extHide(indices) {
    let n = 0;
    for (const i of indices) { const p = S.props[i]; if (p && !propHidden.has(p)) { propHidden.add(p); n++; } }
    if (n) { extDeselect(); S.multi = null; renderProps(); }
    return n;
  }
  function extUnhideAll() {
    for (const p of [...propHidden]) if (!S.props.includes(p)) propHidden.delete(p);
    const n = propHidden.size;
    if (n) { propHidden.clear(); renderProps(); }
    return n;
  }
  function extMultiStart(indices) {
    S.multi = indices.map(i => S.props[i]).filter(Boolean).map(p => ({ p, x: p.x, y: p.y, z: propZ(p), dz: p.dz || 0, yaw: p.yaw }));
    selHold.visible = false; S.propSelP = null;
    return S.multi.length;
  }
  const _v = new THREE.Vector3(), _q = new THREE.Quaternion(), _e = new THREE.Euler(0, 0, 0, 'ZYX');
  function extMultiApply(D) {
    if (!S.multi?.length) return;
    _q.setFromRotationMatrix(D); _e.setFromQuaternion(_q, 'ZYX');
    for (const b of S.multi) {
      _v.set(b.x, b.y, b.z).applyMatrix4(D);
      b.p.x = Math.round(_v.x); b.p.y = Math.round(_v.y);
      b.p.dz = Math.round(b.dz + _v.z - b.z); if (Math.abs(b.p.dz) < 1) delete b.p.dz;
      b.p.yaw = +(b.yaw + _e.z).toFixed(3);
      delete b.p.ai; b.p.ed = 1;
      if (roadUnder(b.p) !== null) b.p.road = 1; else delete b.p.road;
      seats.delete(b.p);
    }
    renderProps();
  }
  function extMultiEnd() { if (S.multi?.length) { saveDraft(); extEdited(); } }
  function extMultiMarks() { return (S.multi || []).map(b => ({ x: b.p.x, y: b.p.y, z: propZ(b.p), r: Math.max(IN, dimOf(b.p).r * IN * b.p.s * 0.8) })); }
  function extMultiDelete() {
    const set = new Set((S.multi || []).map(b => b.p)); if (!set.size) return 0;
    S.props = S.props.filter(p => !set.has(p)); S.multi = null; renderProps(); saveDraft(); extEdited();
    return set.size;
  }
  function extMultiClear() { S.multi = null; }
  // « Poser au sol » (Edition) : objet(s) de la base remis sur le sol (decalage de hauteur retire)
  function extDrop() {
    const list = S.multi?.length ? S.multi.map(b => b.p) : S.propSelP ? [S.propSelP] : [];
    for (const p of list) { delete p.dz; delete p.ai; seats.delete(p); }
    if (!list.length) return 0;
    renderProps(); if (S.propSelP) syncPropSel(); saveDraft(); extEdited();
    if (S.propSelP) { const p = S.propSelP; propProxy.position.set(p.x, p.y, propZ(p)); }
    return list.length;
  }
  // Creation ouverte (brouillon relu : meme ordre des objets) : outil Decor > Modifier sur cet objet
  function editProp(i) {
    const p = S.props[i]; if (!p || !S.active) return;
    setMode('props'); setPropTab('man'); setPropTool('edit'); selectProp(p);
  }
  // sol, route et bords de l'apercu masques / remis (etat d'avant garde : voutes, marquage desactive restent caches)
  function groundParts(show) {
    for (const o of [terrainMesh, clay.group, road, banks, edgeL, edgeR, center, startMark, startLine, roofMesh, markWhite, markCurb]) {
      if (!o) continue;
      if (!show && o.visible) { o.visible = false; o.userData.pvHidden = true; }
      else if (show && o.userData.pvHidden) { o.visible = true; delete o.userData.pvHidden; }
    }
  }
  function previewParts(o) { S.pv = { ...(S.pv || {}), ...o }; }
  // liste de l'onglet Scene (Edition) : objets du decor de la base montres (rang, nom du modele, famille, position)
  function sceneList() {
    const out = [];
    S.props.forEach((p, i) => {
      const k = kindOf(p); if (!k || seatOf(p).off || propHidden.has(p)) return;
      out.push({ i, name: k.names?.[p.m % (k.n || 1)] || p.t, label: k.label || p.t, x: p.x, y: p.y, z: propZ(p) });
    });
    return out;
  }
  // une base existe : chargee avec une route, ou commencee pendant la session (route, relief, decor : toute modification)
  const baseExists = () => !!S.hasBase || S.points?.length > 1 || (S.editN || 0) > 0;
  const surfaces = () => [terrainMesh, road, clay.group];      // pate : sol des parties retouchees (relief cache dessous)
  function close() {
    if (!S.active) return;
    if (draftTimer) writeDraft();
    ctx.setRenderScale?.(1);                                 // l'editeur garde sa pleine resolution
    if (S.savedNear) { camera.near = S.savedNear; camera.updateProjectionMatrix(); }
    selectProp(null);                                        // poignees de l'outil Modifier detachees (sinon actives dans l'editeur)
    S.active = false; S.keys.clear(); S.brushing = false; panel.hidden = true; topbar.hidden = true; group.visible = false; orbit.enabled = true;    restoreButtons();
    for (const [c, h] of S.hostVis || []) { c.hidden = h; delete c.dataset.crHidden; }
    // filet : tout element encore marque comme cache par la Creation est remis dans son etat d'origine
    for (const c of ctx.details ? ctx.details.children : []) if (c.dataset.crHidden) { c.hidden = c.dataset.crHidden === 'h'; delete c.dataset.crHidden; }
    S.hostVis = null;
    ctx.showEdition?.(null);                                 // objets du decor : affichage d'avant la Creation
    for (const [c, v] of S.savedVis || []) c.visible = v;
    S.savedVis = null;
  }
  // scene de l'editeur relue pendant la Creation (« Actualiser la vue ») : elle se remontrait (points de reapparition,
  // splines...) -> de nouveau masquee ; son etat d'affichage relu est celui remis a la fermeture
  function rehide() {
    if (!S.active) return;
    const saved = new Map(S.savedVis || []);
    // objets deja caches par open() : leur etat d'origine est garde (2026-11-13 : il etait remplace par « cache » ->
    // en revenant dans Edition apres un changement de map, le decor restait invisible, seul le sol gris de collision
    // s'affichait, meme apres « Actualiser ») ; seuls les objets apparus depuis sont notes
    scene.children.forEach(c => { if (c === group || c.isLight || c.userData.keepInCreator) return; if (!saved.has(c)) saved.set(c, c.visible); c.visible = false; });
    S.savedVis = [...saved];
    ctx.showEdition?.(null);                                 // decor relu : objets neufs, ajouts d'Edition remontres
    ctx.showEdition?.($('crghost').checked);
  }
  // « Enregistrer » dans la Creation : brouillon du navigateur + copie sur le serveur (autre navigateur, autre PC)
  async function saveNow() {
    writeDraft();
    try {
      const d = localStorage.getItem(draftKey());
      if (d) await api('/api/creator_draft', { track: getTrack(), draft: JSON.parse(d) });
      return true;
    } catch (e) { return false; }
  }
  // retouches faites dans Edition sur le decor genere (deplacer, tourner, taille, copier, supprimer) : reportees dans le
  // brouillon du navigateur, la prochaine generation les garde (meme calcul que server.py patch_props)
  function applyPatch(patch) {
    if (!patch?.length) return;
    const fix = props => {
      props = props.slice();
      for (const op of patch) {
        if (op.add) { props.push(op.add); continue; }
        const u = op.del || op.set?.u, i = props.findIndex(p => p?.u === u);
        if (i < 0) continue;                                  // retire depuis dans la Creation : sa suppression l'emporte
        if (op.del) props.splice(i, 1); else props[i] = { ...op.set };
      }
      return props;
    };
    if (S.active) { S.props = fix(S.props); S.propsDirty = true; writeDraft(); return; }
    try {
      const d = JSON.parse(localStorage.getItem(draftKey()) || 'null');
      if (d && Array.isArray(d.props)) { d.props = fix(d.props); d.at = Date.now(); localStorage.setItem(draftKey(), JSON.stringify(d)); }
    } catch (e) { /* sans importance */ }
    if (S.props) S.props = fix(S.props);
  }
  // caisses / boosters prevus par la piste aleatoire retires de la base (2026-11-19 : ils restaient dans l'apercu apres
  // le placement automatique de l'Edition, et revenaient a chaque generation tant que l'Edition n'avait plus de caisse).
  // kind : 'crates' | 'boosts' | 'all' (poses dans l'Edition a la generation : plus rien a poser ensuite)
  function dropItems(kind = 'all') {
    if (S.loadedTrack !== getTrack() || !S.items) return false;
    if (kind === 'all') S.items = null;
    else if (S.items[kind]?.length) S.items = { ...S.items, [kind]: [] };
    else return false;
    renderItems(); writeDraft();
    return true;
  }
  return { itemGroup, manyBoxes, farPlane: far, kartModel, open, close, tick, rehide, undo, redo, saveNow, applyPatch, preview, dropItems, surfaces, loadQuiet, previewPropAt, editProp,
           extSelect, extDeselect, extInfo, extDelete, extDuplicate, extSet,
           get generated() { return S.loadedTrack === getTrack() && !!S.generated; },
           get hasRoute() { return S.loadedTrack === getTrack() && S.points?.length > 1; },
           get lengthM() { return S.loadedTrack === getTrack() && S.points?.length > 1 ? Math.round(length() / IN) : 0; },
           clearBase, saveBaseToServer, forget, generateNow, randomBase: (c, o) => randomTrack(c, o), parseCode: c => parseRndCode(c), previewParts, sceneList, propsInRect, extDrop, extHide, extUnhideAll, get hiddenBase() { return propHidden.size; }, extMultiStart, extMultiApply, extMultiEnd, extMultiMarks, extMultiDelete, extMultiClear,
           extDragStart: () => propDragStart(), extDrag: m => propDrag(m), extDragEnd: () => { propDragEnd(); extEdited(); }, histTimes, openRandom: () => openRandomDialog(),
           get hasBase() { return S.loadedTrack === getTrack() && baseExists(); },
           // largeur de la route de la base (pouces, mediane des points ; 0 sans base) : cadrage des cartes postales
           get roadWidth() { if (S.loadedTrack !== getTrack() || !S.points?.length) return 0; const w = S.points.map(p => p[3] || S.width).sort((x, y) => x - y); return w[w.length >> 1]; },
           // piste aleatoire pas encore generee dont les ajouts d'Edition et la scene de course seront retires (rndFresh)
           get pendingFresh() { return S.loadedTrack === getTrack() && !!S.rndFresh; },
           generate: () => { if (!$('crgo').disabled) $('crgo').onclick(); },
           get busy() { return $('crgo').disabled; },
           get loaded() { return S.loadedTrack === getTrack(); },
           get genDirty() { return S.loadedTrack === getTrack() && baseExists() && !!S.genDirty; },
           get active() { return S.active; } };
}
