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
const IN = 39.37;
const STEP = 4 * IN;                 // un point enregistre tous les 4 m
const SPEED = 35 * IN;               // vitesse du paveur (po/s), Maj : x2
const R_MIN = 30 * IN;               // rayon de virage minimal a plat (karts et IA doivent suivre)
const R_SLOPE = 1.2;                 // en pente : rayon minimal x (1 + R_SLOPE * pente / pente max) (montee + virage serre = kart bloque)
const SLOPE_MAX = 0.28;              // pente maximale (28 %)
const SLOPE_RATE = SLOPE_MAX / (40 * IN);   // variation de pente par pouce parcouru : 0 -> 28 % sur 40 m
const H_MAX = 80 * IN;               // hauteur maximale au-dessus du sol de depart
const W_MIN = 40 * IN, W_MAX = 120 * IN, W_DEF = 65 * IN;
const CLOSE_DIST = 35 * IN, CLOSE_MIN_LEN = 250 * IN;
// terrain : grille carree centree sur le depart
const T_CELL = 8 * IN;               // maille du terrain (8 m) ; cote au choix (carre de base), 1,6 km par defaut
const T_SIZES = [1200, 1600, 2000, 2400, 2800, 3200];  // m
const SINK_UNDER_ROAD = 0.25 * IN, BLEND_MIN = 6 * IN, BLEND_SLOPE = 1.5;   // raccord route -> terrain (track_creator)
const T_LO = -40 * IN, T_HI = 100 * IN;
let MATERIALS = [                     // ordre = indice de peinture (matieres du kit, track_creator.KITS ; remplacees a l'ouverture)
  { key: 'sand', label: 'Sable', color: [0.85, 0.71, 0.49] },
  { key: 'wetsand', label: 'Sable mouillé', color: [0.62, 0.50, 0.34] },
  { key: 'grass', label: 'Herbe (ralentit)', color: [0.42, 0.60, 0.24] },
  { key: 'rock', label: 'Roche', color: [0.52, 0.50, 0.47] }];
// peintures de TOUS les themes, apres celles du theme : indice MATERIALS.length + rang (track_creator.paint_materials)
let EXTRA_MATS = [];
// dig : sous une route en hauteur, le sol n'est plus colle a la route (relief garde, route en pont) ; fill : l'inverse
const TOOLS = [['raise', '⬆ Monter'], ['lower', '⬇ Creuser'], ['flatten', '▬ Aplanir'], ['smooth', '〰 Lisser'],
               ['dig', '⛏ Creuser sous la route'], ['fill', '↺ Reboucher sous la route']];

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
  const { THREE, scene, camera, orbit, view, renderer, api, status, ask, choose, getTrack, getStart, onGenerate } = ctx;
  const group = new THREE.Group(); group.visible = false; scene.add(group);
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
    const buf = await (await fetch('/api/kart?part=' + part)).arrayBuffer(), dv = new DataView(buf);
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
  (async () => {
    try {
      kart.add(await kartPart('body', 0xffffff)); body.visible = false;
      const proto = { wheel_l: await kartPart('wheel_l', 0xffffff), wheel_r: await kartPart('wheel_r', 0xffffff) };
      for (const [part, x, y] of WHEELS) {
        const w = proto[part].clone(); w.position.set(x, y, 18.3); w.rotation.z = Math.PI / 2;   // essieu (x) -> y
        kart.add(w);
      }
    } catch (e) { /* boite jaune gardee */ }
  })();
  const roadMat = new THREE.MeshBasicMaterial({ color: 0xffffff, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 });
  const bankMat = new THREE.MeshLambertMaterial({ color: 0x8c8378, side: THREE.DoubleSide });          // tabliers de pont
  const lineMat = new THREE.LineBasicMaterial({ color: 0x5a3510 });
  const edgeMat = new THREE.LineBasicMaterial({ color: 0xfff2d0 });
  const road = new THREE.Mesh(new THREE.BufferGeometry(), roadMat);
  const banks = new THREE.Mesh(new THREE.BufferGeometry(), bankMat);              // talus d'aperçu jusqu'au terrain
  const edgeL = new THREE.Line(new THREE.BufferGeometry(), edgeMat), edgeR = new THREE.Line(new THREE.BufferGeometry(), edgeMat);
  const center = new THREE.Line(new THREE.BufferGeometry(), lineMat);
  const startMark = new THREE.Mesh(new THREE.CylinderGeometry(1, 1, 10, 40, 1, true),
                                   new THREE.MeshBasicMaterial({ color: 0x33dd66, transparent: true, opacity: 0.25, side: THREE.DoubleSide }));
  startMark.rotation.x = Math.PI / 2;
  // damier du depart (track_creator : 2 rangees de cases de 1,5 m en travers de la route) ; texture 2 x 2 cases
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
  group.add(far, terrainMesh, road, banks, edgeL, edgeR, center, startMark, startLine, paver, brush);

  // panneau
  const panel = document.createElement('div');
  panel.id = 'creatorPanel'; panel.hidden = true;
  panel.style.cssText = 'position:absolute;left:12px;top:96px;max-height:calc(100% - 108px);overflow:auto;z-index:5;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px;width:300px;max-width:calc(100% - 24px);box-shadow:0 8px 24px #000a;font-size:13px';
  // ordre : reglages de la piste, outils du mode, son contenu, suppression (en bas) ; etat + Generer colles en bas
  const H = t => `<div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin:10px 0 4px">${t}</div>`;
  const row = 'display:grid;grid-template-columns:72px 1fr;gap:4px 6px;align-items:center;font-size:12px';
  const sizeLabel = s => (s / 1000).toLocaleString('fr', { minimumFractionDigits: 1 });
  panel.innerHTML = `<div style="font-weight:600;font-size:14px;margin-bottom:6px">🛣 Création de piste</div>
    <div style="${row}">
      <span>Thème</span><select id="crkit" style="width:100%"></select>
      <span>Terrain</span><select id="crsize" style="width:100%" title="Taille du carré de base">${T_SIZES.map(s => `<option value="${s}">${sizeLabel(s)} km × ${sizeLabel(s)} km</option>`).join('')}</select>
      <span>Barrières</span><select id="crbar" style="width:100%"><option value="curves">Extérieur des virages serrés</option><option value="all">Les deux bords, partout</option><option value="none">Aucune</option></select>
    </div>
    ${H('Outil')}
    <div style="display:grid;grid-template-columns:repeat(6,1fr);gap:4px"><button id="crmroute" style="grid-column:span 3">🛣 Route</button><button id="crmedges" style="grid-column:span 3">↔ Bords</button><button id="crmterrain" style="grid-column:span 2">⛰ Relief</button><button id="crmpaint" style="grid-column:span 2">🎨 Peinture</button><button id="crmprops" style="grid-column:span 2">🌴 Décor</button></div>
    <div id="credges" hidden>
      <div class="note" style="margin:8px 0 6px">Clic sur un bord de la route : une poignée apparaît. Flèche rouge (vers l'extérieur) : élargir ou amincir ce côté. Flèche bleue (vers le haut) : relever ou abaisser le bord (virage relevé). Les points voisins suivent en douceur, le terrain dessous se raccorde. Clic droit : tourner la vue.</div>
      <label style="display:block;margin-bottom:6px">Étendue : <b id="credgerv">30</b> m<input id="credger" type="range" min="5" max="150" value="30" style="width:100%"></label>
      <div id="credgeinfo" class="note" style="margin-bottom:4px">Clique sur un bord de la route.</div>
      <div id="credgeset" style="${row};margin-bottom:6px;display:none">
        <span>Largeur (m)</span><input id="credgew" type="number" step="0.5" min="5" max="60" title="Distance de ce bord au tracé du paveur">
        <span>Relevé (m)</span><input id="credgeh" type="number" step="0.5" min="-10" max="15" title="Hauteur du bord par rapport au tracé : positif = relevé">
        <span></span><button id="credgereset">↺ Ce passage à plat</button>
      </div>
      <button id="credgeall" class="danger" style="width:100%;margin-top:4px">🗑 Tous les bords à plat (largeur symétrique)</button>
    </div>
    <div id="crroute">
      <div class="note" style="margin:8px 0 6px">Conduis le paveur : la route se pose derrière lui. Ferme la boucle en revenant dans le cercle vert.</div>
      <label style="display:block;margin-bottom:6px">Largeur : <b id="crw"></b> m<input id="crwidth" type="range" min="${W_MIN / IN}" max="${W_MAX / IN}" value="${W_DEF / IN}" style="width:100%"></label>
      <details style="margin-bottom:6px"><summary style="cursor:pointer;font-size:12px">⌨ Commandes du paveur</summary>
      <div style="display:grid;grid-template-columns:auto 1fr;gap:2px 8px;font-size:12px;color:var(--muted);margin-top:4px">
        <span>↑ Z W</span><span>avancer (pose la route)</span><span>↓ S</span><span>reculer (efface)</span>
        <span>← Q A · → D</span><span>tourner</span><span>R · F</span><span>monter · descendre</span>
        <span>+ · −</span><span>largeur</span><span>Entrée</span><span>fermer la boucle</span>
        <span>Maj</span><span>plus vite</span><span>C</span><span>caméra libre / poursuite</span>
        <span>Espace</span><span>saut (maintenir : trou dans la route)</span></div></details>
      <button id="crreset" class="danger" style="width:100%;margin-top:4px">🗑 Supprimer toute la route</button>
    </div>
    <div id="crterrain" hidden>
      <div class="note" style="margin:8px 0 6px">Clic gauche maintenu sur le sol : sculpter. Clic droit : tourner la vue, molette : zoom, clic milieu : déplacer. Sous la route, le terrain est raccordé à la route à la génération.</div>
      <div class="note" style="margin:0 0 6px">⛏ Creuser sous la route : sous une route en hauteur, le sol n'est plus collé à elle (place pour du décor, la route devient un pont). ↺ Reboucher : le sol se raccorde de nouveau.</div>
      <div id="crtools" style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:6px">${TOOLS.map(([k, l]) => `<button data-tool="${k}">${l}</button>`).join('')}</div>
    </div>
    <div id="crpaint" hidden>
      <div class="note" style="margin:8px 0 6px">Clic gauche maintenu sur le sol : peindre (le relief ne change pas). Clic droit : tourner la vue, molette : zoom, clic milieu : déplacer.</div>
      <div style="font-size:12px;margin-bottom:4px">Peinture : <b id="crmatcur"></b></div>
      <div id="crmats" style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:6px"></div>
      <details style="margin-bottom:6px"><summary style="cursor:pointer;font-size:12px">🎨 Autres peintures (sols de tous les thèmes)</summary>
        <div id="crmatsx" style="max-height:260px;overflow:auto;border:1px solid var(--line);border-radius:6px;padding:2px 6px;margin-top:4px"></div></details>
    </div>
    <div id="crprops" hidden>
      <div class="note" style="margin:8px 0 6px">Objets de tous les thèmes, posés sur le sol à la génération, jamais sur la route. Clic gauche maintenu : pinceau, clic droit : tourner la vue.</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;margin-bottom:6px"><button id="crpsow">🌱 Semer</button><button id="crperase">🧽 Effacer</button></div>
    </div>
    <div id="crbrush" hidden>
      <label style="display:block;margin-bottom:4px">Taille du pinceau : <b id="crr"></b> m<input id="crradius" type="range" min="6" max="150" value="30" style="width:100%"></label>
      <label style="display:block;margin-bottom:6px">Force : <b id="crs"></b><input id="crstrength" type="range" min="5" max="100" value="50" style="width:100%"></label>
    </div>
    <div id="crpmore" hidden>
      <div style="display:flex;align-items:center;gap:6px;margin:10px 0 4px">
        <span style="flex:1;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)">Objets à semer · <span id="crpsel" style="text-transform:none"></span></span>
        <select id="crpsort" title="Classement de la liste" style="font-size:11px"><option value="style">Par style</option><option value="type">Par type d'objet</option></select>
      </div>
      <button id="crpnone" hidden style="width:100%;margin-bottom:4px;font-size:12px">✖ Désélectionner tout</button>
      <div id="crpgrid" style="max-height:320px;overflow:auto;border:1px solid var(--line);border-radius:6px;padding:2px 6px"></div>
      ${H('Le long de la route')}
      <label style="display:block;margin-bottom:4px;font-size:12px">Jusqu'à <b id="crpfarv"></b> m du bord<input id="crpfar" type="range" min="10" max="200" value="60" style="width:100%"></label>
      <button id="crpauto" style="width:100%">🌴 Semer le long de la route</button>
      <div class="note" style="font-size:11px;margin:4px 0">Gros objets (⛰) : seulement en fond de map, derrière les autres. Au pinceau, tu peux les poser plus près.</div>
      ${H('Objets semés')}
      <div id="crpstat" class="note" style="margin-bottom:6px"></div>
      <button id="crpclear" class="danger" style="width:100%">🗑 Supprimer tous les objets</button>
    </div>
    <button id="crtreset" class="danger" style="width:100%;margin-top:6px" hidden>🗑 Tout supprimer</button>
    <div style="position:sticky;bottom:-40px;z-index:1;background:var(--panel);border-top:1px solid var(--line);margin:10px 0 -40px;padding:6px 0 40px">
      <div id="crstat" style="margin-bottom:6px;font-size:12px"></div>
      <div style="display:flex;gap:6px"><button id="crundo" title="Annuler (Ctrl+Z)" disabled>↶</button>
        <button id="crredo" title="Rétablir (Ctrl+Y)" disabled>↷</button><button id="crclose">⭕ Fermer la boucle</button>
        <button id="crgo" class="go" style="flex:1">⚙ Générer la piste</button></div></div>`;
  // panneau dans la barre de droite (a la place de « Sélection ») quand l'editeur la fournit, sinon sur la vue
  const host = ctx.details || view;
  if (ctx.details) panel.style.cssText = 'font-size:13px;padding:2px 0';
  host.appendChild(panel);
  const $ = id => panel.querySelector('#' + id);

  // ---- decor seme (mode Decor) : objets du kit (pose a la generation), reperes simples dans l'apercu ----
  // familles d'objets de TOUS les themes (un objet d'un theme se seme sur n'importe quel autre)
  let propKinds = {};                 // {'theme|type': {label, spacing (m), scale [min, max], n (modeles), dims, names}}
  const kindOf = p => propKinds[p.k + '|' + p.t];
  S.props = []; S.propErase = false; S.propAcc = 0; S.propsDirty = false; S.lastProps = 0;
  const propGroup = new THREE.Group(); group.add(propGroup);
  // vrais modeles du jeu (comme dans le Decor), a la bonne taille ; repere gris de la taille reelle pendant le chargement
  const propModels = {}, markerMat = new THREE.MeshLambertMaterial({ color: 0x8a8580, transparent: true, opacity: 0.6 });
  const markerGeo = new THREE.CylinderGeometry(1, 1, 1, 10); markerGeo.rotateX(Math.PI / 2); markerGeo.translate(0, 0, 0.5);
  const dimOf = p => kindOf(p)?.dims?.[p.m % (kindOf(p)?.n || 1)] || { r: 3, zmin: 0, zmax: 5 };
  // modele d'un objet : promesse resolue quand la geometrie ET ses textures sont chargees (vignettes) ; .value des que
  // la geometrie est la (apercu de la scene)
  function propModelP(kit, t, m) {
    const key = `${kit}|${t}|${m}`;
    return (propModels[key] ??= (() => {
      const entry = { value: null };
      entry.promise = (async () => {
        const buf = await (await fetch(`/api/kit_model?kit=${kit}&type=${t}&m=${m}`)).arrayBuffer(), dv = new DataView(buf);
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
          let done; loads.push(new Promise(r => { done = r; setTimeout(r, 4000); }));
          const tex = texLoader.load(`/api/kit_texture?kit=${kit}&type=${t}&ns=${encodeURIComponent(tx.ns)}`, done, undefined, done);
          tex.flipY = false; tex.colorSpace = THREE.SRGBColorSpace; tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
          return new THREE.MeshLambertMaterial({ map: tex, alphaTest: 0.5, side: THREE.DoubleSide });
        })];
        entry.value = { g, mats }; S.propsDirty = true;
        await Promise.all(loads);
        return entry.value;
      })().catch(() => null);
      return entry;
    })());
  }
  const propModel = (k, t, m) => propModelP(k, t, m).value;
  const footOf = p => (kindOf(p)?.foot ?? 0.3) * dimOf(p).r * IN * p.s;     // emprise du pied (tronc, base)
  // bas de l'objet (comme la generation) : point le plus bas sous son pied - 30 cm
  function propLow(p) {
    const r = footOf(p);
    let z = shownAt(p.x, p.y);
    for (const f of [0.5, 1]) for (let k = 0; k < 8; k++) {
      const a = k * Math.PI / 4; z = Math.min(z, shownAt(p.x + f * r * Math.cos(a), p.y + f * r * Math.sin(a)));
    }
    return z - 0.3 * IN;
  }
  // pose de l'origine : par la base (rochers : par l'origine, faits pour etre a moitie enterres)
  const propZ = p => propLow(p) - (p.t === 'rock' ? 0 : dimOf(p).zmin * IN * p.s);
  // route touchee (track_creator.prop_conflict) : au niveau de la route, seul le pied compte ; une route plus haute
  // (pont, rampe) ne doit croiser aucune partie de l'objet tant que le dessous de son tablier est sous son sommet
  function propConflict(p) {
    const k = kindOf(p), d = dimOf(p), base = propLow(p), top = base + (d.zmax - d.zmin) * IN * p.s;
    const clear = (k?.clear ?? 1) * IN, foot = footOf(p) + clear, full = 0.9 * d.r * IN * p.s + clear;
    const level = (k?.level ?? 1.5) * IN, deck = (k?.deck ?? 1.2) * IN;
    return (S.eff || S.points).some(q => {
      const hd = Math.hypot(p.x - q[0], p.y - q[1]) - q[3] / 2;
      return q[2] < base + level ? hd < foot : q[2] - deck < top + IN && hd < full;
    });
  }
  // dans le carre de base (hors du terrain : ecarte a la generation)
  const inTerrain = p => { const T = S.terrain; if (!T) return true;
    const m = 0.5 * dimOf(p).r * IN * p.s, e = (T.n - 1) * T.cell;
    return p.x - m > T.x0 && p.y - m > T.y0 && p.x + m < T.x0 + e && p.y + m < T.y0 + e; };
  function renderProps() {
    propGroup.clear();
    let off = 0;
    for (const p of S.props) {
      // la route a change depuis le semis (pont, rampe) : objet ecarte a la generation, donc pas montre
      if (!kindOf(p) || propConflict(p) || !inTerrain(p)) { off++; continue; }   // famille inconnue : ignoree aussi a la generation
      const mdl = propModel(p.k, p.t, p.m % (kindOf(p)?.n || 1)), d = dimOf(p);
      let o;
      if (mdl) { o = new THREE.Mesh(mdl.g, mdl.mats); o.scale.setScalar(p.s); }
      else { o = new THREE.Mesh(markerGeo, markerMat); o.scale.set(d.r * IN * p.s * 0.6, d.r * IN * p.s * 0.6, (d.zmax - d.zmin) * IN * p.s); }
      o.rotation.z = p.yaw; o.position.set(p.x, p.y, propZ(p) + (mdl ? 0 : d.zmin * IN * p.s));
      propGroup.add(o);
    }
    $('crpstat').textContent = `${S.props.length - off} objet(s) semé(s)` +
      (off ? ` · ${off} masqué(s) : ils touchent la route (pont, rampe) ou sortent du terrain, ils ne seront pas posés` : '');
  }
  // objets choisis dans la liste (« theme|type|modele ») : le pinceau et le semis le long de la route y piochent
  S.sel = new Set();
  const selKind = key => propKinds[key.split('|').slice(0, 2).join('|')];
  // big : true = gros objets seulement, false = les autres, undefined = tous
  const pickSel = big => { const a = [...S.sel].filter(s => selKind(s) && (big === undefined || !!selKind(s).big === big));
                           if (!a.length) return null;
                           const [k, t, m] = a[Math.floor(Math.random() * a.length)].split('|'); return { k, t, m: +m }; };
  // c : objet deja choisi ({k, t, m, s?}), sinon tire dans la selection
  function tryProp(x, y, c = pickSel()) {
    if (!c) return false;
    const k = kindOf(c), [a, b] = k.scale;
    const p = { k: c.k, t: c.t, m: c.m, x, y, yaw: +(Math.random() * 2 * Math.PI).toFixed(3), s: c.s ?? +(a + Math.random() * (b - a)).toFixed(2) };
    if (propConflict(p) || !inTerrain(p)) return false;
    const sp = k.spacing * IN;
    // pas de chevauchement : corps des deux objets (moitie de leur emprise) + espacement de leur famille
    const body = o => 0.5 * dimOf(o).r * IN * o.s;
    // (gros objet d'un cote : seulement leurs corps, sinon un rocher geant interdirait toute herbe a 30 m a la ronde)
    const gap = q => k.big !== kindOf(q)?.big ? 0 : Math.max(sp, (kindOf(q)?.spacing || 3) * IN) * 0.8;
    if (S.props.some(q => Math.hypot(q.x - x, q.y - y) < Math.max(gap(q), body(p) + body(q)))) return false;
    S.props.push(p);
    return true;
  }
  function sowAlongRoad() {
    if (!pickSel()) { status('Choisis d\'abord un ou plusieurs objets dans la liste', 'err'); return; }
    let n = 0, nb = 0;
    const far = +$('crpfar').value, small = !!pickSel(false), big = !!pickSel(true);
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
    renderProps(); saveDraft();
    status(`${n + nb} objet(s) semé(s) le long de la route` + (nb ? ` dont ${nb} gros objet(s) en fond de map` : ''), 'ok');
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
      const mdl = await propModelP(k, t, m).promise;
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
    ['🪧 Objets et décorations', ['beach', 'deco', 'sign', 'fence', 'wood', 'torch', 'lamp', 'lantern', 'spike', 'tire', 'kart', 'card', 'speaker']]];
  const typeOf = (t, k) => k.big ? '⛰ Gros objets (fond de map)' : (PROP_TYPES.find(([, ts]) => ts.includes(t))?.[0] || '📦 Autres objets');
  // classement par type : une seule categorie par famille, tous themes confondus (tous les palmiers ensemble...)
  const TYPE_ALIAS = { gears: 'gear' };
  const TYPE_LABELS = {
    palm: '🌴 Palmiers', tree: '🌳 Arbres', pine: '🌲 Sapins', plant: '🌿 Plantes', grass: '🌿 Herbes', flower: '🌸 Fleurs',
    giant: '🌼 Fleurs géantes', bush: '🌿 Buissons', kelp: '🌿 Algues', coral: '🪸 Coraux', cactus: '🌵 Cactus',
    mushroom: '🍄 Champignons', vine: '🌿 Lianes et souches', rock: '🪨 Rochers', crystal: '💎 Cristaux', gems: '💎 Trésors',
    snow: '❄ Neige et glaçons', pillar: '🏛 Piliers', statue: '🗿 Statues', column: '🏛 Colonnes et tours', tiki: '🗿 Tikis',
    fossil: '🦴 Fossiles', bones: '🦴 Os et étoiles de mer', house: '🏠 Maisons', hut: '🛖 Huttes', building: '🏭 Bâtiments',
    pipe: '🛢 Tuyaux', barrel: '🛢 Barils', fan: '⚙ Ventilateurs', beam: '🏗 Poutres', machine: '🤖 Machines',
    tesla: '⚡ Bobines', drum: '🛢 Fûts et vannes', magnet: '🧲 Aimants et pilons', gear: '⚙ Engrenages',
    cart: '⛏ Wagonnets et outils', tech: '🖥 Écrans et panneaux', beach: '⚓ Objets de plage', deco: '🏮 Décorations',
    sign: '🪧 Panneaux', fence: '🚧 Barrières', wood: '🪵 Poteaux et clôtures', torch: '🔥 Torches et chandelles',
    lamp: '💡 Lampes', lantern: '🏮 Lanternes', spike: '🚧 Grilles et pics', tire: '🛞 Pneus et bottes de foin',
    kart: '🏎 Karts exposés', card: '🃏 Cartes et loterie', speaker: '🔊 Haut-parleurs', big: '⛰ Gros objets (fond de map)' };
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
        tileHtml(kk, nm, m, kitNames ? kitNames[kk.split('|')[0]] : ''))).join('')}</div>`;
  // par style : un bloc repliable par theme (le theme courant en premier, ouvert) ; par type : un bloc par genre
  // d'objet (familles de tous les themes, nom du theme en titre) ; vignettes chargees a l'ouverture du bloc
  function renderPropList() {
    const grid = $('crpgrid'), cur = $('crkit').value, names = S.info?.kits || {};
    const kits = [cur, ...(S.info?.order || Object.keys(names)).filter(k => k !== cur)];
    if ($('crpsort').value === 'type') {
      const groups = [...PROP_TYPES.map(([l]) => l), '📦 Autres objets', '⛰ Gros objets (fond de map)'];
      const fams = kits.flatMap(kit => Object.entries(propKinds).filter(([kk]) => kk.startsWith(kit + '|')));
      grid.innerHTML = groups.map(g => [g, fams.filter(([kk, k]) => typeOf(kk.split('|')[1], k) === g)]).filter(([, f]) => f.length)
        .map(([g, f], i) => {
          // meme famille dans tous les themes : une seule categorie (theme du modele en infobulle)
          const byType = new Map();
          for (const fam of f) { const t = typeKey(fam[0].split('|')[1]); if (!byType.has(t)) byType.set(t, []); byType.get(t).push(fam); }
          return `<details${i ? '' : ' open'}><summary style="cursor:pointer;font-weight:600;margin:6px 0 2px">${g}
          <span style="font-weight:400;color:var(--muted)">(${f.reduce((a, [, k]) => a + (k.names || []).length, 0)})</span></summary>${
          [...byType].map(([t, tf]) => famHtml(tf, TYPE_LABELS[t] || tf[0][1].label, names)).join('')}</details>`;
        }).join('');
    } else
      grid.innerHTML = kits.map(kit => `<details data-kit="${kit}"${kit === cur ? ' open' : ''}><summary style="cursor:pointer;font-weight:600;margin:6px 0 2px">${names[kit] || kit}</summary>${
        Object.entries(propKinds).filter(([kk]) => kk.startsWith(kit + '|')).map(([kk, k]) => famHtml([[kk, k]], k.label)).join('')}</details>`).join('');
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
      const keys = b.dataset.all.split(',').flatMap(kk => (propKinds[kk]?.names || []).map((_, m) => `${kk}|${m}`));
      const all = keys.every(k => S.sel.has(k));
      keys.forEach(k => all ? S.sel.delete(k) : S.sel.add(k)); syncSel(); saveDraft();
    });
    syncSel();
  }
  function syncSel() {
    panel.querySelectorAll('.crptile').forEach(b => b.classList.toggle('primary', S.sel.has(b.dataset.key)));
    const n = [...S.sel].filter(selKind).length;
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
  const shownAt = (x, y) => S.shown && S.shown.length === S.terrain.n ** 2 ? sample(S.shown, x, y) : heightAt(x, y);
  // raccord (track_creator._conform) : sous la route + une maille aplani juste sous elle, puis pente douce jusqu'au
  // relief ; chaque passage de la route compte a part (suite de points proches) et le sol suit le passage le plus BAS
  // (sous un croisement : la route du dessus devient un pont). Sous un saut, le sol se raccorde aussi (pas de route).
  // bords edites (outil Bords) : p[5..8] = demi-largeur gauche, droite, relevement du bord gauche, droit (pouces).
  // Route reelle (track_creator.centerline) : [x, y, z, largeur, saut, devers, Lx, Ly] (L : normale gauche),
  // centre decale vers le cote elargi, devers = bord gauche au-dessus du centre (le droit autant en dessous)
  const edgesOf = p => [p[5] ?? p[3] / 2, p[6] ?? p[3] / 2, p[7] ?? 0, p[8] ?? 0];
  function effPoints() {
    const P = S.points, n = P.length;
    return S.eff = P.map((p, i) => {
      const a = P[i > 0 ? i - 1 : S.closed ? n - 1 : 0], b = P[i < n - 1 ? i + 1 : S.closed ? 0 : n - 1];
      let tx = b[0] - a[0], ty = b[1] - a[1]; const l = Math.hypot(tx, ty) || 1; tx /= l; ty /= l;
      const [wl, wr, hl, hr] = edgesOf(p), sh = (wl - wr) / 2;
      return [p[0] - ty * sh, p[1] + tx * sh, p[2] + (hl + hr) / 2, wl + wr, p[4] || 0, (hl - hr) / 2, -ty, tx];
    });
  }
  function conform() {
    const T = S.terrain, n = T.n, N = n * n, P = effPoints(), [EL, ER] = realEdges(P), below = SINK_UNDER_ROAD + 6;
    const h0 = new Float32Array(N); for (let v = 0; v < N; v++) h0[v] = S.groundZ + T.h[v];
    const acc = new Float32Array(N).fill(Infinity), runD = new Float32Array(N).fill(Infinity), runV = new Float32Array(N);
    const last = new Int32Array(N).fill(-99);
    let hMax = 0; for (let v = 0; v < N; v++) hMax = Math.max(hMax, Math.abs(T.h[v]));
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
      const reach = T.cell + Math.max(BLEND_MIN, BLEND_SLOPE * (Math.abs(P[k][2] - S.groundZ) + Math.abs(P[k][5]) + hMax + 2 * IN));
      const x0 = Math.min(l0[0], l1[0], r0[0], r1[0]) - reach, x1 = Math.max(l0[0], l1[0], r0[0], r1[0]) + reach;
      const y0 = Math.min(l0[1], l1[1], r0[1], r1[1]) - reach, y1 = Math.max(l0[1], l1[1], r0[1], r1[1]) + reach;
      const i0 = Math.max(0, Math.floor((x0 - T.x0) / T.cell)), i1 = Math.min(n - 1, Math.ceil((x1 - T.x0) / T.cell));
      const j0 = Math.max(0, Math.floor((y0 - T.y0) / T.cell)), j1 = Math.min(n - 1, Math.ceil((y1 - T.y0) / T.cell));
      for (let j = j0; j <= j1; j++) for (let i = i0; i <= i1; i++) {
        const v = j * n + i, x = T.x0 + i * T.cell, y = T.y0 + j * T.cell;
        // sous la route : sa surface reelle ; a cote : le bord le plus proche
        const surf = inTri(x, y, l0, l1, r1) ?? inTri(x, y, l0, r1, r0);
        let d = 0, rz = surf;
        if (surf === null) {
          const ea = toEdge(x, y, l0, l1), eb = toEdge(x, y, r0, r1), e = ea[0] <= eb[0] ? ea : eb;
          d = e[0]; rz = e[1];
        }
        rz -= below;
        const bl = Math.max(BLEND_MIN, Math.abs(rz - h0[v]) * BLEND_SLOPE);
        if (d >= T.cell + bl) continue;
        if (last[v] >= 0 && k - last[v] > 3) { if (runV[v] < acc[v]) acc[v] = runV[v]; runD[v] = Infinity; }   // autre passage
        let val = rz;
        if (d > T.cell) { const tt = (d - T.cell) / bl, s = tt * tt * (3 - 2 * tt); val = rz * (1 - s) + h0[v] * s; }
        if (d < runD[v] || (d === runD[v] && val < runV[v])) { runD[v] = d; runV[v] = val; }
        last[v] = k;
      }
    }
    const out = new Float32Array(N);
    for (let v = 0; v < N; v++) {
      const a = runD[v] < Infinity ? Math.min(acc[v], runV[v]) : acc[v];
      out[v] = a < Infinity && !T.dig?.[v] ? a : h0[v];                // creuse sous la route : relief garde
    }
    clearRoad(out, EL, ER, P);
    S.shown = out;
    // plan de fond : toujours sous le sol (sinon il apparait dans les creux, en aplat beige)
    let low = S.groundZ; for (let v = 0; v < N; v++) if (out[v] < low) low = out[v];
    far.position.z = low - 60;
  }
  // track_creator._clear_road : la grille (8 m) ne suit pas une route dont la hauteur change vite (virage releve) ; la
  // ou sa surface passerait au-dessus de la route, les sommets de la case sont abaisses juste ce qu'il faut
  function clearRoad(H, EL, ER, P) {
    const T = S.terrain, n = T.n, c = T.cell, step = 2 * IN, clear = 0.25 * IN, xs = [], ys = [], zs = [];
    const count = S.closed ? P.length : P.length - 1;
    for (let k = 0; k < count; k++) {
      const k1 = (k + 1) % P.length;
      if (P[k][4] || P[k1][4]) continue;
      const l0 = EL[k], l1 = EL[k1], r0 = ER[k], r1 = ER[k1];
      const nu = Math.max(1, Math.floor(Math.max(Math.hypot(l0[0] - r0[0], l0[1] - r0[1]), Math.hypot(l1[0] - r1[0], l1[1] - r1[1])) / step));
      const nv = Math.max(1, Math.floor(Math.max(Math.hypot(l1[0] - l0[0], l1[1] - l0[1]), Math.hypot(r1[0] - r0[0], r1[1] - r0[1])) / step));
      for (let iv = 0; iv <= nv; iv++) for (let iu = 0; iu <= nu; iu++) {
        const v = iv / nv, u = iu / nu;                      // u : 0 bord droit, 1 bord gauche
        for (const [q, arr] of [[0, xs], [1, ys], [2, zs]]) {
          const rr = r0[q] + (r1[q] - r0[q]) * v, ll = l0[q] + (l1[q] - l0[q]) * v;
          arr.push(rr + (ll - rr) * u);
        }
      }
    }
    const low = new Float32Array(H.length);
    for (let pass = 0; pass < 8; pass++) {
      let bad = false;
      low.fill(0);
      for (let q = 0; q < xs.length; q++) {
        const fx = (xs[q] - T.x0) / c, fy = (ys[q] - T.y0) / c;
        if (fx < 0 || fy < 0 || fx > n - 1 || fy > n - 1) continue;
        const i = Math.min(n - 2, Math.floor(fx)), j = Math.min(n - 2, Math.floor(fy)), u = fx - i, w = fy - j;
        const A = j * n + i, B = A + 1, C = A + n + 1, D = A + n;
        const z = u >= w ? H[A] + u * (H[B] - H[A]) + w * (H[C] - H[B]) : H[A] + u * (H[C] - H[D]) + w * (H[D] - H[A]);
        const over = z - (zs[q] - clear);
        if (over <= 0.04) continue;
        bad = true;
        for (const V of [A, B, C, D]) if (over > low[V]) low[V] = over;
      }
      if (!bad) return;
      for (let v = 0; v < H.length; v++) H[v] -= low[v];
    }
  }
  // sauts : seule la route s'arrete, le sol reste (comme track_creator.build) -> aucune case retiree
  function holeCells() {
    const T = S.terrain, n = T.n, holes = new Uint8Array((n - 1) * (n - 1));
    for (const p of []) {
      if (!p[4]) continue;
      const reach = p[3] / 2 + 3 * IN, ci = (p[0] - T.x0) / T.cell - 0.5, cj = (p[1] - T.y0) / T.cell - 0.5, rc = reach / T.cell;
      for (let j = Math.max(0, Math.floor(cj - rc)); j <= Math.min(n - 2, Math.ceil(cj + rc)); j++)
        for (let i = Math.max(0, Math.floor(ci - rc)); i <= Math.min(n - 2, Math.ceil(ci + rc)); i++)
          if (Math.hypot(T.x0 + (i + 0.5) * T.cell - p[0], T.y0 + (j + 0.5) * T.cell - p[1]) <= reach) holes[j * (n - 1) + i] = 1;
    }
    return holes;
  }
  function refreshTerrainMesh() {
    const T = S.terrain, n = T.n, N = n * n;
    conform();
    if (!terrainGeo.attributes.position || terrainGeo.attributes.position.count !== N) {     // nouvelle taille
      terrainGeo.dispose(); terrainGeo = new THREE.BufferGeometry(); terrainMesh.geometry = terrainGeo;
      terrainGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(N * 3), 3));
      terrainGeo.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(N * 2), 2));
      terrainGeo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(N * 3), 3));
    }
    const pos = terrainGeo.attributes.position, uv = terrainGeo.attributes.uv, col = terrainGeo.attributes.color;
    const rep = (S.kitInfo?.ground_repeat || 12) * IN;
    for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) {
      const v = j * n + i, x = T.x0 + i * T.cell, y = T.y0 + j * T.cell;
      pos.setXYZ(v, x, y, S.shown[v] - 2); uv.setXY(v, x / rep, y / rep);
    }
    pos.needsUpdate = uv.needsUpdate = true;
    // faces par matiere (la plus presente aux 4 coins, comme la generation), sans les trous des sauts
    // (egalite : la plus petite peinture, comme track_creator.build)
    const holes = holeCells(), per = new Map(), cnt = new Map(), last = MATERIALS.length + EXTRA_MATS.length - 1;
    for (let j = 0; j < n - 1; j++) for (let i = 0; i < n - 1; i++) {
      if (holes[j * (n - 1) + i]) continue;
      const a = j * n + i, b = a + 1, c = a + n + 1, d = a + n;
      cnt.clear(); let best = 0, bc = 0;
      for (const v of [a, b, c, d]) {
        const m = Math.min(T.paint[v], last), k = (cnt.get(m) || 0) + 1;
        cnt.set(m, k); if (k > bc || (k === bc && m < best)) { bc = k; best = m; }
      }
      if (!per.has(best)) per.set(best, []);
      per.get(best).push(a, b, c, a, c, d);
    }
    const used = [...per.keys()].sort((x, y) => x - y);
    terrainGeo.setIndex([].concat(...used.map(m => per.get(m)))); terrainGeo.clearGroups();
    let o = 0; used.forEach((m, g) => { terrainGeo.addGroup(o, per.get(m).length, g); o += per.get(m).length; });
    terrainMesh.material = used.map(m => { const mt = matOf(m);
      return new THREE.MeshBasicMaterial({ vertexColors: true,
        ...(mt.png ? { map: kitTexture(mt.png, mt.kit) } : { color: new THREE.Color(...mt.color) }) }); });
    terrainGeo.computeVertexNormals();
    // ombrage fixe (soleil en biais) dans la couleur des sommets, multipliee par la texture
    const nrm = terrainGeo.attributes.normal, L = [0.45, -0.35, 0.82];
    for (let v = 0; v < N; v++) {
      const s = 0.55 + 0.5 * Math.max(0, nrm.getX(v) * L[0] + nrm.getY(v) * L[1] + nrm.getZ(v) * L[2]);
      col.setXYZ(v, Math.min(1, s), Math.min(1, s), Math.min(1, s));
    }
    col.needsUpdate = true;
    terrainGeo.computeBoundingSphere(); terrainGeo.computeBoundingBox();
  }
  // nouvelle taille du carre de base : relief et peinture reechantillonnes (centre garde)
  function resizeTerrain(size) {
    const old = S.terrain, T = newTerrain(S.start, size);
    if (old) for (let j = 0; j < T.n; j++) for (let i = 0; i < T.n; i++) {
      const x = T.x0 + i * T.cell, y = T.y0 + j * T.cell, v = j * T.n + i;
      const fi = Math.round((x - old.x0) / old.cell), fj = Math.round((y - old.y0) / old.cell);
      if (fi < 0 || fj < 0 || fi >= old.n || fj >= old.n) continue;
      S.terrain = old; T.h[v] = sample(old.h, x, y); T.paint[v] = old.paint[fj * old.n + fi]; T.dig[v] = old.dig?.[fj * old.n + fi] || 0;
    }
    S.terrain = T;
  }  function applyBrush(dt) {
    const T = S.terrain, p = S.mouse; if (!T || !p) return;
    if (S.mode === 'props') {                                 // semer / effacer des objets
      if (S.propErase) {
        const n = S.props.length; S.props = S.props.filter(q => Math.hypot(q.x - p.x, q.y - p.y) > S.radius);
        S.propsDirty ||= n !== S.props.length; return;
      }
      S.propAcc += dt * (2 + 10 * S.strength);
      while (S.propAcc >= 1) {
        S.propAcc -= 1;
        const a = Math.random() * 2 * Math.PI, r = S.radius * Math.sqrt(Math.random());
        if (tryProp(p.x + r * Math.cos(a), p.y + r * Math.sin(a))) S.propsDirty = true;
      }
      return;
    }
    const r = S.radius, ci = (p.x - T.x0) / T.cell, cj = (p.y - T.y0) / T.cell, rc = r / T.cell;
    const i0 = Math.max(0, Math.floor(ci - rc)), i1 = Math.min(T.n - 1, Math.ceil(ci + rc));
    const j0 = Math.max(0, Math.floor(cj - rc)), j1 = Math.min(T.n - 1, Math.ceil(cj + rc));
    const rate = 8 * IN * S.strength * dt * 2;
    const old = S.tool === 'smooth' ? T.h.slice() : null;
    for (let j = j0; j <= j1; j++) for (let i = i0; i <= i1; i++) {
      const d = Math.hypot(i - ci, j - cj) / rc; if (d >= 1) continue;
      const f = (1 - d * d) ** 2, k = tIndex(i, j);
      if (S.mode === 'paint') { if (f > 0.25) T.paint[k] = S.paint; continue; }
      if (S.tool === 'raise') T.h[k] += rate * f;
      else if (S.tool === 'lower') T.h[k] -= rate * f;
      else if (S.tool === 'dig') { T.h[k] -= rate * f; if (f > 0.05) T.dig[k] = 1; }   // relief garde sous la route
      else if (S.tool === 'fill') { if (f > 0.05) T.dig[k] = 0; continue; }          // de nouveau raccorde a la route
      else if (S.tool === 'flatten') T.h[k] += (S.flatZ - T.h[k]) * Math.min(1, dt * 6 * S.strength * f);
      else if (S.tool === 'smooth' && i > 0 && j > 0 && i < T.n - 1 && j < T.n - 1) {
        const avg = (old[k - 1] + old[k + 1] + old[k - T.n] + old[k + T.n]) / 4;
        T.h[k] += (avg - T.h[k]) * Math.min(1, dt * 8 * S.strength * f);
      }
      T.h[k] = Math.max(T_LO, Math.min(T_HI, T.h[k]));
    }
    S.dirtyT = true;
  }
  // point du terrain sous la souris : rayon contre le maillage (aperçu)
  const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
  function pick(e) {
    const b = renderer.domElement.getBoundingClientRect();
    ndc.set(((e.clientX - b.left) / b.width) * 2 - 1, -((e.clientY - b.top) / b.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    const hit = ray.intersectObject(terrainMesh, false)[0];
    return hit ? hit.point : null;
  }

  const draftKey = () => 'ctr_creator_' + getTrack();
  const packTerrain = T => T && { x0: T.x0, y0: T.y0, cell: T.cell, n: T.n, h: Array.from(T.h, v => Math.round(v)), paint: Array.from(T.paint),
                                  ...(T.dig?.some(v => v) ? { dig: Array.from(T.dig) } : {}) };
  const packFull = T => T && { ...packTerrain(T), size: T.size, full: true };       // carre de base complet genere
  const saveDraft = () => { writeDraft(); histSchedule(); };
  const writeDraft = () => { try { localStorage.setItem(draftKey(), JSON.stringify({ points: S.points, closed: S.closed, width: S.width, barriers: $('crbar').value, props: S.props, kit: $('crkit').value, sel: [...S.sel], far: +$('crpfar').value,
                                                                                   terrain: packFull(S.terrain) })); } catch (e) { /* sans importance */ } };
  const closeR = () => Math.max(CLOSE_DIST, S.width * 0.8);

  // ---- annuler / retablir : instantane du brouillon (trace, bords, objets, relief, peinture, reglages) pris un
  // instant apres chaque modification enregistree (saveDraft) ; un trait de pinceau, un glisser ou un trajet du
  // paveur = une etape ----
  const HIST_MAX = 60;
  let hist = [], histAt = -1, histTimer = 0;
  function histSnap() {
    const T = S.terrain;
    return { meta: JSON.stringify({ points: S.points, closed: S.closed, width: S.width, barriers: $('crbar').value,
                                    kit: $('crkit').value, sel: [...S.sel], far: $('crpfar').value, props: S.props,
                                    t: T && [T.x0, T.y0, T.cell, T.n, T.size] }),
             h: T?.h.slice(), paint: T?.paint.slice(), dig: T?.dig?.slice() };
  }
  const sameArr = (a, b) => a === b || (a && b && a.length === b.length && a.every((v, i) => v === b[i]));
  const histSame = (a, b) => a.meta === b.meta && sameArr(a.h, b.h) && sameArr(a.paint, b.paint) && sameArr(a.dig, b.dig);
  function histButtons() { $('crundo').disabled = histAt <= 0; $('crredo').disabled = histAt >= hist.length - 1; }
  function histReset() { clearTimeout(histTimer); histTimer = 0; hist = [histSnap()]; histAt = 0; histButtons(); }
  function histSchedule() { clearTimeout(histTimer); histTimer = setTimeout(histCommit, 350); }
  function histCommit() {
    clearTimeout(histTimer); histTimer = 0;
    if (!S.active || histAt < 0) return;
    if (S.brushing || S.keys.size || tc?.dragging) { histSchedule(); return; }   // geste en cours : etape a la fin
    const s = histSnap();
    if (histSame(s, hist[histAt])) return;
    hist.length = histAt + 1; hist.push(s);
    if (hist.length > HIST_MAX) hist.shift();
    histAt = hist.length - 1; histButtons();
  }
  function histRestore(s) {
    const m = JSON.parse(s.meta);
    S.points = m.points; S.closed = m.closed; S.props = m.props; S.sel = new Set(m.sel);
    $('crbar').value = m.barriers; $('crpfar').value = m.far; $('crpfarv').textContent = m.far;
    if (m.t) {
      S.terrain = { x0: m.t[0], y0: m.t[1], cell: m.t[2], n: m.t[3], size: m.t[4], h: s.h.slice(), paint: s.paint.slice(),
                    dig: s.dig ? s.dig.slice() : new Uint8Array(m.t[3] * m.t[3]) };
      $('crsize').value = String(m.t[4]);
    }
    if ($('crkit').value !== m.kit) { $('crkit').value = m.kit; applyKit(); } else syncSel();
    setWidth(m.width); placeFromPoints(); S.slope = 0; S.back = 0;
    if (S.edgeSel && S.edgeSel.i >= S.points.length) selectEdge(null);
    S.terrainDirty = S.dirtyT = false;
    refreshTerrainMesh(); rebuild(); renderProps(); if (S.edgeSel) placeEdge();
    writeDraft(); histButtons();
  }
  function undo() {
    if (tc?.dragging || S.brushing) return;
    if (histTimer) histCommit();                              // modification toute fraiche : d'abord en faire une etape
    if (histAt <= 0) { status('Rien à annuler'); return; }
    histRestore(hist[--histAt]); status('Annulé');
  }
  function redo() {
    if (tc?.dragging || S.brushing || histAt >= hist.length - 1) return;
    histRestore(hist[++histAt]); status('Rétabli');
  }

  function resetPaver() {
    const st = S.start, z = heightAt(st.pos[0], st.pos[1]);
    S.points = [[st.pos[0], st.pos[1], z, S.width]];
    S.closed = false; S.pos = new THREE.Vector3(st.pos[0], st.pos[1], z); S.yaw = st.yaw; S.slope = 0; S.back = 0;
  }
  function placeFromPoints() {
    const p = S.points[S.points.length - 1];
    S.pos = new THREE.Vector3(p[0], p[1], p[2]);
    if (S.points.length > 1) { const q = S.points[S.points.length - 2]; S.yaw = Math.atan2(p[1] - q[1], p[0] - q[0]); }
    else S.yaw = S.start.yaw;
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
      line.geometry.dispose(); line.geometry = new THREE.BufferGeometry();
      line.geometry.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
    }
    center.geometry.dispose(); center.geometry = new THREE.BufferGeometry();
    center.geometry.setAttribute('position', new THREE.Float32BufferAttribute(cl, 3));
    // damier du depart, en travers de la route au 1er point (comme la generation)
    startLine.visible = n > 1 && !P[0][4];
    if (startLine.visible) {
      const [l, rr] = [rv[0], rv[1]], [tx, ty] = tg[0], d = 1.5 * IN;
      const q = (p, k) => [p[0] + tx * d * k, p[1] + ty * d * k, p[2] + 4];
      const w = Math.hypot(l[0] - rr[0], l[1] - rr[1]) / (3 * IN);
      const A = q(rr, -1), B = q(rr, 1), Cq = q(l, 1), D = q(l, -1);
      startLine.geometry.dispose(); startLine.geometry = new THREE.BufferGeometry();
      startLine.geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array([...A, ...B, ...Cq, ...A, ...Cq, ...D]), 3));
      startLine.geometry.setAttribute('uv', new THREE.BufferAttribute(new Float32Array([0, 0, 0, 1, w, 1, 0, 0, w, 1, w, 0]), 2));
    }
    const r = closeR(); startMark.scale.set(r, 30, r);           // cylindre couche : x, z = rayon, y = hauteur
    if (S.points.length) startMark.position.set(S.points[0][0], S.points[0][1], S.points[0][2] + 5);
    const len = length() / IN;
    $('crstat').innerHTML = `Longueur : <b>${Math.round(len)} m</b> · ${S.points.length} points · ` +
      (S.closed ? '<b style="color:var(--ok)">boucle fermée</b>' : nearStart() ? '<b style="color:var(--ok)">Entrée : fermer la boucle</b>' : 'boucle ouverte');
    $('crgo').disabled = !S.closed;
    $('crclose').disabled = S.closed || !nearStart();
  }
  // croisement : nouveau point sur un morceau plus ancien a la meme hauteur (pas de pont possible)
  function crossing(p) {
    if (Math.hypot(p[0] - S.points[0][0], p[1] - S.points[0][1]) < closeR() * 1.5) return false;   // retour au depart
    for (let i = 0; i < S.points.length - 8; i++) {
      const q = S.points[i];
      if (Math.hypot(p[0] - q[0], p[1] - q[1]) < (p[3] + q[3]) / 2 && Math.abs(p[2] - q[2]) < 7 * IN) return true;
    }
    return false;
  }

  function tick(t) {
    if (!S.active) return;
    const dt = Math.min(0.1, (t - (S.last || t)) / 1000); S.last = t;
    if (S.propsDirty && t - S.lastProps > 100) { renderProps(); S.propsDirty = false; S.lastProps = t; }
    // terrain raccorde recalcule au plus 4 fois par seconde pendant que le paveur pose la route
    if (S.terrainDirty && t - (S.lastTerrain || 0) > 250) { refreshTerrainMesh(); rebuild(); renderProps(); S.terrainDirty = false; S.lastTerrain = t; }
    // manette : valeurs des actions ; « tap » = appui de ce cadre (bouton qui vient d'etre enfonce)
    const pad = firstPad(), P = {}, was = S.padWas || {};
    for (const [k] of PAD_ACTIONS) P[k] = padValue(pad, S.padMap[k]);
    const tap = k => P[k] > 0.5 && !(was[k] > 0.5);
    S.padWas = P;
    if (tap('undo')) undo();
    if (tap('redo')) redo();
    if (S.mode !== 'route') {
      if (S.brushing) applyBrush(dt);
      if (S.dirtyT && t - S.lastNormals > 120) { refreshTerrainMesh(); rebuild(); S.dirtyT = false; S.lastNormals = t; }
      if (S.propsDirty && t - S.lastProps > 100) { renderProps(); S.propsDirty = false; S.lastProps = t; }
      return;
    }
    const k = S.keys;
    let fwd = (k.has('ArrowUp') || k.has('KeyW') || k.has('KeyZ')) ? 1 : 0;
    let rev = (k.has('ArrowDown') || k.has('KeyS')) ? 1 : 0;
    let steer = ((k.has('ArrowLeft') || k.has('KeyA') || k.has('KeyQ')) ? 1 : 0) - ((k.has('ArrowRight') || k.has('KeyD')) ? 1 : 0);
    let climb = (k.has('KeyR') ? 1 : 0) - (k.has('KeyF') ? 1 : 0);
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
      S.pos.x += Math.cos(S.yaw) * d; S.pos.y += Math.sin(S.yaw) * d;
      // jamais sous le terrain (sinon la route serait enterree) ni trop haut
      const floor = heightAt(S.pos.x, S.pos.y);
      S.pos.z = Math.max(floor, Math.min(S.groundZ + H_MAX, S.pos.z + S.slope * d));
      if (S.pos.z <= floor && S.slope < 0) S.slope = 0;
      const last = S.points[S.points.length - 1];
      if (Math.hypot(S.pos.x - last[0], S.pos.y - last[1]) >= STEP) {
        const p = [S.pos.x, S.pos.y, S.pos.z, S.width, jumping ? 1 : 0];
        if (crossing(p) && t - S.warned > 3000) { S.warned = t; status('Croisement à la même hauteur : monte (R) ou descends (F) pour faire un pont', 'err'); }
        S.points.push(p); changed = true;
      }
    } else if (rev > 0 && S.points.length > 1) {
      S.closed = false;
      S.back += speed * rev * dt;
      while (S.back >= STEP && S.points.length > 1) { S.points.pop(); S.back -= STEP; changed = true; }
      placeFromPoints(); S.slope = 0;
    } else if (steer && !S.closed && S.points.length === 1) {
      S.yaw += steer * dt * 1.5; S.start = { ...S.start, yaw: S.yaw };    // orienter le depart sur place
    }
    paver.position.copy(S.pos); paver.rotation.set(0, -Math.atan(S.slope), S.yaw);
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
  function setMode(m) {
    const was = S.mode;
    S.mode = m; S.brushing = false;
    $('crroute').hidden = m !== 'route'; $('crterrain').hidden = m !== 'terrain'; $('crpaint').hidden = m !== 'paint';
    $('crprops').hidden = $('crpmore').hidden = m !== 'props'; $('crtreset').hidden = m === 'props' || m === 'route' || m === 'edges';
    $('crtreset').textContent = m === 'paint' ? '🗑 Effacer toute la peinture' : '🗑 Remettre tout le relief à plat';
    $('crbrush').hidden = m === 'route' || m === 'edges'; $('credges').hidden = m !== 'edges';
    if (m !== 'edges') selectEdge(null);
    for (const [id, k] of [['crmroute', 'route'], ['crmedges', 'edges'], ['crmterrain', 'terrain'], ['crmpaint', 'paint'], ['crmprops', 'props']]) $(id).classList.toggle('primary', m === k);
    paver.visible = m === 'route'; brush.visible = false;
    S.chase = m === 'route'; orbit.enabled = !S.chase;
    // pinceaux : clic gauche = pinceau, clic droit = tourner la vue, clic milieu = deplacer (molette : zoom)
    if (m !== 'route' && !S.savedButtons) {
      S.savedButtons = { ...orbit.mouseButtons };
      orbit.mouseButtons = { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.PAN, RIGHT: THREE.MOUSE.ROTATE };
    } else if (m === 'route') restoreButtons();
    if (m !== 'route' && was === 'route') {
      // vue de haut, en biais, centree sur le paveur
      orbit.target.copy(S.pos); camera.position.set(S.pos.x - 120 * IN, S.pos.y - 160 * IN, S.pos.z + 220 * IN);
      camera.up.set(0, 0, 1); camera.lookAt(S.pos); orbit.update();
      status(m === 'edges' ? 'Bords : clique sur un bord de la route, puis tire la flèche rouge (largeur) ou bleue (relevé)'
           : m === 'props' ? 'Décor : clic gauche maintenu pour semer ou effacer des objets (clic droit : tourner la vue)'
           : m === 'paint' ? 'Peinture : clic gauche maintenu pour peindre le sol (clic droit : tourner la vue)'
                           : 'Relief : clic gauche maintenu pour sculpter (clic droit : tourner la vue)');
    }
  }
  function restoreButtons() {
    if (S.savedButtons) { orbit.mouseButtons = S.savedButtons; S.savedButtons = null; }
  }
  function setTool(k) {
    S.tool = k;
    panel.querySelectorAll('[data-tool]').forEach(b => b.classList.toggle('primary', b.dataset.tool === k));
  }
  function setPaint(i) {
    S.paint = i;
    panel.querySelectorAll('[data-mat]').forEach(b => b.classList.toggle('primary', +b.dataset.mat === i));
    const m = matOf(i), names = S.info?.kits || {};
    $('crmatcur').textContent = m.label + (i >= MATERIALS.length ? ` · ${names[m.kit] || m.kit}` : '');
  }

  const DRIVE = new Set(['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'KeyW', 'KeyZ', 'KeyS', 'KeyA', 'KeyQ', 'KeyD',
                         'KeyR', 'KeyF', 'ShiftLeft', 'ShiftRight', 'Space']);
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
  view.addEventListener('pointerdown', e => {
    if (!S.active || S.mode === 'route' || e.button !== 0 || e.target !== canvas) return;
    if (S.mode === 'edges') { edgePointerDown(e); return; }
    const p = pick(e); if (!p) return;
    S.mouse = p; S.brushing = true; S.flatZ = heightAt(p.x, p.y) - S.groundZ;
    orbit.enabled = false; canvas.setPointerCapture?.(e.pointerId);
    e.preventDefault(); e.stopImmediatePropagation();
  }, true);
  view.addEventListener('pointermove', e => {
    if (!S.active || S.mode === 'route' || S.mode === 'edges' || (e.target !== canvas && !S.brushing)) return;
    const p = pick(e);
    brush.visible = !!p;
    if (p) { S.mouse = p; brush.position.set(p.x, p.y, p.z + 20); brush.scale.set(S.radius, S.radius, 1); }
    if (S.brushing) { e.preventDefault(); e.stopImmediatePropagation(); }
  }, true);
  const endBrush = e => {
    if (!S.brushing) return;
    S.brushing = false; orbit.enabled = true; refreshTerrainMesh(); rebuild(); renderProps(); saveDraft();   // talus et objets suivent le relief
    e?.stopImmediatePropagation?.();
  };
  view.addEventListener('pointerup', endBrush, true);
  view.addEventListener('click', e => { if (S.active && S.mode !== 'route' && e.target === canvas) { e.preventDefault(); e.stopImmediatePropagation(); } }, true);
  canvas.addEventListener('pointerleave', () => { brush.visible = false; });

  // ---- outil Bords : clic sur un bord de la route -> poignee (gizmo) ; fleche rouge (vers l'exterieur) : elargir /
  // amincir ce cote, fleche bleue (vers le haut) : relever / abaisser le bord (virage releve). Les points voisins
  // suivent sur l'etendue choisie (fondu en cosinus) ; le terrain dessous se raccorde (conform) ----
  const EDGE_W = [5 * IN, 60 * IN], EDGE_H = [-10 * IN, 15 * IN];     // demi-largeur : jusqu'a 120 m de route
  const edgeHandle = new THREE.Mesh(new THREE.SphereGeometry(1.5 * IN, 16, 12),
                                    new THREE.MeshBasicMaterial({ color: 0xffcc33, depthTest: false }));
  edgeHandle.renderOrder = 20; edgeHandle.visible = false; group.add(edgeHandle);
  const edgeLine = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: 0xffcc33, depthTest: false }));
  edgeLine.renderOrder = 19; edgeLine.visible = false; group.add(edgeLine);
  const tc = ctx.TransformControls ? new ctx.TransformControls(camera, canvas) : null;
  if (tc) {
    tc.setSpace('local'); tc.showY = false; group.add(tc.getHelper ? tc.getHelper() : tc);
    tc.addEventListener('dragging-changed', e => { orbit.enabled = !e.value; e.value ? edgeDragStart() : edgeDragEnd(); });
    tc.addEventListener('objectChange', edgeDrag);
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
    const [wl, wr, hl, hr] = edgesOf(S.points[sel.i]);
    $('credgeinfo').innerHTML = `Bord <b>${sd > 0 ? 'gauche' : 'droit'}</b> (sens de la course)`;
    $('credgew').value = ((sd > 0 ? wl : wr) / IN).toFixed(1); $('credgeh').value = ((sd > 0 ? hl : hr) / IN).toFixed(1);
    $('credgeset').style.display = 'grid';
  }
  function selectEdge(sel) {
    S.edgeSel = sel;
    if (!sel) { tc?.detach(); edgeHandle.visible = edgeLine.visible = false; $('credgeset').style.display = 'none';
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
    if (all) S.points.forEach(p => { if (p.length > 5) { p[3] = p[5] + p[6]; p.length = 5; } });
    else applyEdges(base, (v, w) => { const h = (v[0] + v[1]) / 2; return [v[0] + (h - v[0]) * w, v[1] + (h - v[1]) * w, v[2] * (1 - w), v[3] * (1 - w)]; });
    refreshTerrainMesh(); rebuild(); renderProps(); saveDraft(); placeEdge();
  }

  $('crmroute').onclick = () => setMode('route');
  $('crmterrain').onclick = () => setMode('terrain');
  $('crmpaint').onclick = () => setMode('paint');
  $('crmprops').onclick = () => setMode('props');
  $('crmedges').onclick = () => setMode('edges');
  $('credger').oninput = e => { $('credgerv').textContent = e.target.value; placeEdge(); };
  $('credgew').onchange = $('credgeh').onchange = edgeTyped;
  $('credgereset').onclick = () => edgeReset(false);
  $('credgeall').onclick = async () => { if (await ask('Remettre tous les bords à plat, avec la même largeur des deux côtés ?')) edgeReset(true); };
  $('crpsow').onclick = () => { S.propErase = false; $('crpsow').classList.add('primary'); $('crperase').classList.remove('primary'); };
  $('crperase').onclick = () => { S.propErase = true; $('crperase').classList.add('primary'); $('crpsow').classList.remove('primary'); };
  $('crpauto').onclick = sowAlongRoad;
  $('crpfar').oninput = e => { $('crpfarv').textContent = e.target.value; };
  $('crpfar').onchange = saveDraft;
  $('crpclear').onclick = async () => { if (S.props.length && !(await ask('Retirer tous les objets semés ?'))) return; S.props = []; renderProps(); saveDraft(); };
  panel.querySelectorAll('[data-tool]').forEach(b => b.onclick = () => setTool(b.dataset.tool));

  $('crradius').oninput = e => { S.radius = +e.target.value * IN; $('crr').textContent = e.target.value; };
  $('crstrength').oninput = e => { S.strength = +e.target.value / 100; $('crs').textContent = e.target.value + ' %'; };
  $('crtreset').onclick = async () => {                       // Relief : tout a plat ; Peinture : tout dans la 1re matiere
    const relief = S.mode === 'terrain';
    if (!(await ask(relief ? 'Remettre tout le relief à plat (la peinture reste) ?' : 'Effacer toute la peinture (le relief reste) ?'))) return;
    if (relief) { S.terrain.h.fill(0); S.terrain.dig?.fill(0); } else S.terrain.paint.fill(0);
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
  $('crreset').onclick = async () => {
    if (S.points.length > 1 && !(await ask('Supprimer tout le tracé et recommencer au départ ?'))) return;
    resetPaver(); rebuild(); renderProps(); saveDraft();
  };
  $('crgo').onclick = async () => {
    // repartir de zero : aussi les ajouts faits dans Edition (imports, bibliotheque, copies) et toute la scene de
    // course ; sinon ils restent avec la piste generee
    const c = await choose('Générer la piste ? Le sol et le décor d\'origine sont retirés, la création précédente est remplacée, '
      + 'puis le parcours et les IA sont créés et enregistrés (≈ 1 à 3 min).\n\nSupprimer aussi la map en cours dans Édition pour '
      + 'repartir de zéro ? Tes imports, objets de la bibliothèque et copies, ainsi que la scène de course (caisses, boosters, '
      + 'zones de chute, téléporteurs, embranchements).', ['🧹 Repartir de zéro', 'Garder la map en cours']);
    if (c < 0) return;
    const wipe = c === 0;
    $('crgo').disabled = true;
    try {
      status('Génération de la piste…');
      const r = await api('/api/create_build', { track: getTrack(), points: S.points, closed: S.closed, ground_z: S.groundZ,
                                                  kit: $('crkit').value, barriers: $('crbar').value, props: S.props,
                                                  terrain: packFull(S.terrain), wipe });
      await onGenerate({ ...r, wipe });
    } catch (e) { status('Erreur : ' + e.message, 'err'); }
    finally { rebuild(); }
  };

  // une seule ouverture a la fois : le serveur repond en quelques secondes ; une 2e ouverture memorisait la vue deja
  // masquee, que la fermeture remettait ensuite (apercu toujours affiche, splines cachees)
  async function open() {
    if (S.active || S.opening) return;
    S.opening = true;
    try { await openNow(); } finally { S.opening = false; }
  }
  async function openNow() {
    const st = getStart();
    S.start = { pos: st.pos, yaw: st.yaw }; S.groundZ = st.groundZ;
    far.position.set(st.pos[0], st.pos[1], S.groundZ - 60);
    let info = { saved: null, kits: { sable: 'Plage de sable (Crash Cove)' } };
    try { info = await (await fetch('/api/creator?track=' + encodeURIComponent(getTrack()))).json(); } catch (e) { /* sans importance */ }
    $('crkit').innerHTML = (info.order || Object.keys(info.kits)).map(k => [k, info.kits[k]]).map(([k, l]) => `<option value="${k}">${l}</option>`).join('');
    let draft = null;
    try { draft = JSON.parse(localStorage.getItem(draftKey()) || 'null'); } catch (e) { /* sans importance */ }
    const src = draft?.points?.length > 1 ? draft : info.saved;
    if (src?.points?.length > 1) S.start = { pos: [src.points[0][0], src.points[0][1]],
                                             yaw: Math.atan2(src.points[1][1] - src.points[0][1], src.points[1][0] - src.points[0][0]) };
    const t = src?.terrain;
    if (t?.n > 2 && t.h?.length === t.n * t.n)
      S.terrain = { x0: t.x0, y0: t.y0, cell: t.cell || T_CELL, n: t.n, size: t.size || Math.round((t.n - 1) * (t.cell || T_CELL) / IN),
                    h: Float32Array.from(t.h), paint: Uint8Array.from(t.paint),
                    dig: t.dig?.length === t.n * t.n ? Uint8Array.from(t.dig) : new Uint8Array(t.n * t.n) };
    else S.terrain = newTerrain(S.start, 1600);
    // taille retiree de la liste (0,8 km) : terrain reechantillonne a la plus proche proposee
    if (!T_SIZES.includes(S.terrain.size))
      resizeTerrain(T_SIZES.reduce((a, b) => Math.abs(b - S.terrain.size) < Math.abs(a - S.terrain.size) ? b : a));
    $('crsize').value = String(S.terrain.size);
    $('crbar').value = src?.barriers || 'curves';
    S.info = info;
    if (src?.kit && info.kits[src.kit]) $('crkit').value = src.kit;
    // anciens brouillons : objets et choix sans theme = theme du brouillon
    const k0 = src?.kit && info.kits[src.kit] ? src.kit : 'sable';
    S.sel = new Set((Array.isArray(src?.sel) ? src.sel : []).map(s => s.split('|').length === 2 ? k0 + '|' + s : s));
    $('crpfar').value = String(src?.far || 60); $('crpfarv').textContent = $('crpfar').value;
    applyKit();
    S.props = (Array.isArray(src?.props) ? src.props : []).map(p => p.k ? p : { ...p, k: k0 });
    if (src?.points?.length > 1) {
      S.points = src.points; S.closed = !!src.closed; setWidth(src.width || src.points[src.points.length - 1][3] || W_DEF);
      placeFromPoints();
    } else { setWidth(W_DEF); resetPaver(); }
    refreshTerrainMesh();
    $('crr').textContent = Math.round(S.radius / IN); $('crs').textContent = Math.round(S.strength * 100) + ' %';
    S.savedVis = scene.children.map(c => [c, c.visible]);
    scene.children.forEach(c => { if (c !== group && !c.isLight) c.visible = false; });
    // barre de droite : seul le panneau de creation (titre et selection de l'editeur masques)
    if (ctx.details) S.hostVis = [...ctx.details.children].filter(c => c !== panel).map(c => { const h = c.hidden; c.hidden = true; return [c, h]; });
    group.visible = true; panel.hidden = false; S.active = true; S.last = 0;
    setTool(S.tool); setPaint(S.paint); setMode('route');
    rebuild(); renderProps(); histReset();
    status('Création : conduis le paveur (↑ avancer, ← → tourner, R / F monter / descendre) — onglet Terrain pour sculpter le sol');
  }
  function close() {
    if (!S.active) return;
    S.active = false; S.keys.clear(); S.brushing = false; panel.hidden = true; group.visible = false; orbit.enabled = true;
    restoreButtons();
    for (const [c, h] of S.hostVis || []) c.hidden = h;
    S.hostVis = null;
    for (const [c, v] of S.savedVis || []) c.visible = v;
    S.savedVis = null;
  }
  // scene de l'editeur relue pendant la Creation (« Actualiser la vue ») : elle se remontrait (points de reapparition,
  // splines...) -> de nouveau masquee ; son etat d'affichage relu est celui remis a la fermeture
  function rehide() {
    if (!S.active) return;
    const saved = new Map(S.savedVis || []);
    scene.children.forEach(c => { if (c === group || c.isLight) return; saved.set(c, c.visible); c.visible = false; });
    S.savedVis = [...saved];
  }
  return { open, close, tick, rehide, get active() { return S.active; } };
}
