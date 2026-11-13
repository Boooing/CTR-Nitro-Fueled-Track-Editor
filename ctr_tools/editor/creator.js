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
const KICK_H = 3 * IN, KICK_LEN = 22 * IN;  // tremplin avant un saut (track_creator : KICK_H, KICK_LEN)
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
const BLEND_DEF = 0.75, SCULPT_FULL = 3 * IN;   // largeur du talus par m de denivele ; relief sculpte qui garde sa hauteur pres de la route
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
const TOOLS = [['raise', '⬆ Monter'], ['lower', '⬇ Creuser'], ['flatten', '▬ Aplanir'], ['smooth', '〰 Lisser'],
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
  let kartLoad = null;
  function loadKart() {
    return kartLoad ||= (async () => {
      try {
        const [bodyPart, wheelL, wheelR] = await Promise.all([kartPart('body', 0xffffff), kartPart('wheel_l', 0xffffff), kartPart('wheel_r', 0xffffff)]);
        const proto = { wheel_l: wheelL, wheel_r: wheelR };
        kart.add(bodyPart); body.visible = false;
        for (const [part, x, y] of WHEELS) {
          const w = proto[part].clone(); w.position.set(x, y, 18.3); w.rotation.z = Math.PI / 2;   // essieu (x) -> y
          kart.add(w);
        }
      } catch (e) { kartLoad = null; }
    })();
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
  // tunnels (track_creator._roof_mask) : relief garde au-dessus de la route comme un plafond, dessine des deux cotes
  const roofMesh = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.DoubleSide }));
  roofMesh.visible = false; group.add(roofMesh);
  // ponts de terre (outil Relief « Relier deux sommets ») et trait d'apercu entre le 1er sommet et la souris

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
    #creatorPanel .crsub{display:grid;grid-template-columns:1fr 1fr;margin-top:8px}
    #creatorPanel .crsub button{border-radius:0;padding:7px 4px}
    #creatorPanel .crsub button:first-child{border-radius:8px 0 0 8px}
    #creatorPanel .crsub button:last-child{border-radius:0 8px 8px 0}
    #creatorPanel .crrow2{display:grid;grid-template-columns:1fr 118px;gap:5px 6px;align-items:center;font-size:12px}
    #creatorPanel .crrow2 select{width:100%}
    #creatorPanel .crchips{display:flex;flex-wrap:wrap;gap:4px}
    #creatorPanel .crchips button{font-size:12px;padding:3px 7px}
    #creatorPanel .crcard label{font-size:12px}`;
  document.head.appendChild(css);
  panel.innerHTML = `<div style="font-weight:600;font-size:14px;margin-bottom:6px">🛣 Création de piste</div>
    <details id="crsetup" class="crcard" style="margin-top:0" open><summary>⚙ Réglages de la piste</summary>
    <div style="${row}">
      <span>Thème</span><select id="crkit" style="width:100%"></select>
      <span>Terrain</span><select id="crsize" style="width:100%" title="Taille du carré de base">${T_SIZES.map(s => `<option value="${s}">${sizeLabel(s)} km × ${sizeLabel(s)} km</option>`).join('')}</select>
      <span>Barrières</span><select id="crbar" style="width:100%"><option value="curves">Extérieur des virages serrés</option><option value="all">Les deux bords, partout</option><option value="none">Aucune</option></select>
      <span>Qualité</span><select id="crq" style="width:100%" title="Résolution de la vue et détail des objets pendant la création. Auto : la résolution baisse toute seule si la carte graphique peine, remonte si elle a de la marge. Maximale : objets d'origine. Basse : objets très simplifiés, pour les petits PC. Aucun effet sur la piste générée."><option value="auto">Auto</option><option value="0">Maximale</option><option value="2">Moyenne</option><option value="3">Basse</option></select>
    </div></details>
    ${H('Outil')}
    <div style="display:grid;grid-template-columns:repeat(6,1fr);gap:4px"><button id="crmroute" style="grid-column:span 2">🛣 Route</button><button id="crmedges" style="grid-column:span 2">↔ Bords</button><button id="crmbridge" style="grid-column:span 2" title="Faire passer une route au-dessus d'une autre là où elles se croisent">🌉 Pont</button><button id="crmterrain" style="grid-column:span 2">⛰ Relief</button><button id="crmpaint" style="grid-column:span 2">🎨 Peinture</button><button id="crmprops" style="grid-column:span 2">🌴 Décor</button></div>
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
      <div class="note" style="margin:8px 0 0">Conduis le paveur : la route se pose derrière lui. Ferme la boucle en revenant dans le cercle vert.</div>
      <div class="crcard"><h4>Tracé</h4>
      <label style="display:block;margin-bottom:6px">Largeur : <b id="crw"></b> m<input id="crwidth" type="range" min="${W_MIN / IN}" max="${W_MAX / IN}" value="${W_DEF / IN}" style="width:100%"></label>
      <button id="crstartpick" style="width:100%" title="Clique ensuite sur le terrain : le kart s'y place et la route partira de là. Le départ de la course suit à la génération.">📍 Placer le kart (point de départ)</button>
      </div>
      <div class="crcard"><h4>Virages relevés</h4>
      <label style="display:block;margin-bottom:2px" title="Le kart et la route penchent progressivement vers cet angle en roulant (30° sur 40 m). L'angle reste jusqu'à ce que tu le changes. Touches T et G.">Inclinaison : <b id="crrollv">à plat</b>
        <input id="crroll" type="range" min="-30" max="30" step="1" value="0" style="width:100%"></label>
      <button id="crrollflat" style="width:100%">↔ Remettre à plat</button>
      </div>
      <div class="crcard"><h4>Talus</h4>
      <label style="display:flex;gap:6px;align-items:center;margin-bottom:4px" title="Avec : le terrain monte jusqu'à la route. Sans : le sol reste à sa hauteur et la route passe au-dessus, comme un pont. Change en roulant : seule la route posée ensuite suit ce réglage. Touche B."><input type="checkbox" id="crtalus" checked> Talus sous la route (B)</label>
      <button id="crtalusall" style="width:100%;margin-bottom:6px" title="Applique le réglage ci-dessus à toute la route déjà posée">Appliquer à toute la route</button>
      <label style="display:block" title="Largeur du talus de chaque côté, pour 10 m de dénivelé entre la route et le sol. Plus petit : talus plus raide, qui prend moins de place. S'applique à toute la piste.">Largeur du talus : <b id="crblendv"></b><input id="crblend" type="range" min="0.25" max="1.5" step="0.25" value="${BLEND_DEF}" style="width:100%"></label>
      </div>
      <details class="crhelp"><summary>⌨ Commandes du paveur</summary>
      <div style="display:grid;grid-template-columns:auto 1fr;gap:2px 8px;font-size:12px;color:var(--muted);margin-top:4px">
        <span>↑ Z W</span><span>avancer (pose la route)</span><span>↓ S</span><span>reculer (efface)</span>
        <span>← Q A · → D</span><span>tourner</span><span>R · F</span><span>monter · descendre</span>
        <span>T · G</span><span>incliner à gauche · à droite</span><span>B</span><span>talus sous la route (oui · non)</span>
        <span>+ · −</span><span>largeur</span><span>Entrée</span><span>fermer la boucle</span>
        <span>Maj</span><span>plus vite</span><span>C</span><span>caméra libre / poursuite</span>
        <span>Espace</span><span>saut (maintenir : trou dans la route)</span></div></details>
      <button id="crreset" class="danger" style="width:100%;margin-top:4px">🗑 Supprimer toute la route</button>
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
        <div class="note" style="font-size:11px;margin:8px 0 0">Construit un décor d'après le thème, les peintures et les pentes, avec de gros objets en fond de carte. Tes objets et ton relief faits à la main sont gardés.</div>
        <div class="crcard"><h4>Style</h4>
          <div class="crchips"><button data-aipreset="balanced">⚖ Équilibré</button><button data-aipreset="nature">🌳 Nature</button><button data-aipreset="clear">👁 Dégagé</button><button data-aipreset="wild">🌲 Sauvage</button><button data-aipreset="built">🏘 Aménagé</button></div>
        </div>
        <div class="crcard"><h4>Quantité</h4>
          <div class="crrow2">
            <span>Densité :</span><select id="craidens"><option value="0">Légère</option><option value="1" selected>Normale</option><option value="2">Dense</option></select>
            ${[['craiveg', '🌳 Végétation', 'Arbres, buissons, herbes et fleurs'], ['crairock', '🗻 Rochers', 'Rochers, cristaux, fossiles'], ['craibuilt', '🏠 Objets et bâtiments', 'Statues, piliers, machines, maisons, huttes'], ['crairoad', '🚧 Bord de route', 'Panneaux, lampes, barrières, pneus : surtout à l\'extérieur des virages']]
              .map(([id, l, tip]) => `<span title="${tip}">${l}</span><select id="${id}" title="${tip}"><option value="0">Aucun</option><option value="1">Peu</option><option value="2" selected>Normal</option><option value="3">Beaucoup</option></select>`).join('')}
          </div>
        </div>
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
        <div class="note" style="font-size:11px;margin:8px 0 0">Objets de tous les thèmes, posés sur le sol à la génération, jamais sur la route. Clic gauche maintenu : pinceau, clic droit : tourner la vue.</div>
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
              <div class="crrow2" style="margin-bottom:6px">
                <span title="Rotation autour de la verticale">Rotation Z (°)</span><input id="crpeyaw" type="number" step="5" style="width:100%" title="Rotation autour de la verticale">
                <span title="Inclinaison autour de l'axe X (rouge), en plus de la pente du sol">Inclinaison X (°)</span><input id="crperx" type="number" step="5" min="-180" max="180" style="width:100%" title="Inclinaison autour de l'axe X (rouge), en plus de la pente du sol">
                <span title="Inclinaison autour de l'axe Y (vert), en plus de la pente du sol">Inclinaison Y (°)</span><input id="crpery" type="number" step="5" min="-180" max="180" style="width:100%" title="Inclinaison autour de l'axe Y (vert), en plus de la pente du sol">
                <span>Taille (×)</span><input id="crpes" type="number" step="0.05" min="0.05" max="20" style="width:100%">
                <span title="Décalage au-dessus (ou au-dessous) du sol. 0 : posé sur le sol, il suit le relief.">Hauteur (m)</span><input id="crpedz" type="number" step="0.5" style="width:100%" title="Décalage au-dessus (ou au-dessous) du sol. 0 : posé sur le sol, il suit le relief.">
              </div>
              <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px"><button id="crpeground" title="Hauteur remise à 0 : l'objet suit de nouveau le sol">⤓ Au sol</button><button id="crpedup" title="Copie posée à côté (Ctrl+D)">⧉ Dupliquer</button><button id="crpedel" class="danger" title="Suppr">🗑 Supprimer</button></div>
              <div id="crpewarn" class="note" style="font-size:11px;margin-top:4px;color:var(--err)" hidden></div>
              <div class="note" style="font-size:11px;margin-top:4px">W déplacer · E tourner · R taille · Suppr · Échap : désélectionner</div>
            </div>
          </div>
        </div>
        <div class="crcard"><h4>3. Ou le long de la route</h4>
          <label style="display:block;margin-bottom:4px;font-size:12px">Jusqu'à <b id="crpfarv"></b> m du bord<input id="crpfar" type="range" min="10" max="200" value="60" style="width:100%"></label>
          <button id="crpauto" style="width:100%">🌴 Semer le long de la route</button>
          <div class="note" style="font-size:11px;margin:4px 0 0">Gros objets (⛰) : seulement en fond de map, derrière les autres. Au pinceau, tu peux les poser plus près.</div>
        </div>
      </div>
      <div class="crcard"><h4>Objets semés</h4>
        <div id="crpstat" class="note" style="margin-bottom:6px"></div>
        <button id="crpclear" class="danger" style="width:100%">🗑 Supprimer tous les objets</button>
      </div>
    </div>
    <div id="crbrushhome"><div id="crbrush" class="crcard" hidden>
      <label style="display:block;margin-bottom:4px">Taille du pinceau : <b id="crr"></b> m<input id="crradius" type="range" min="6" max="150" value="30" style="width:100%"></label>
      <label style="display:block;margin-bottom:6px">Force : <b id="crs"></b><input id="crstrength" type="range" min="5" max="100" value="50" style="width:100%"></label>
      <label id="crspeedrow" style="display:block;margin-bottom:6px" title="Multiplie la vitesse à laquelle le sol monte, se creuse, s'aplanit ou se lisse">Vitesse : <b id="crspeedv">x1</b><input id="crspeed" type="range" min="1" max="10" step="1" value="1" style="width:100%"></label>
    </div></div>
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
  S.waters = []; S.waterSel = -1;                    // eau des trous (outil du Relief, renderWater)
  const propGroup = new THREE.Group(); group.add(propGroup);
  // vrais modeles du jeu (comme dans le Decor), a la bonne taille ; repere gris de la taille reelle pendant le chargement
  const propModels = {}, markerMat = new THREE.MeshLambertMaterial({ color: 0x8a8580, transparent: true, opacity: 0.6 });
  const markerGeo = new THREE.CylinderGeometry(1, 1, 1, 10); markerGeo.rotateX(Math.PI / 2); markerGeo.translate(0, 0, 0.5);
  const dimOf = p => kindOf(p)?.dims?.[p.m % (kindOf(p)?.n || 1)] || { r: 3, zmin: 0, zmax: 5 };
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
  function roadUnder(p) {
    const G = roadIndex(), a = Math.floor(p.x / G.size), b = Math.floor(p.y / G.size);
    let top = null;
    for (let u = a - 1; u <= a + 1; u++) for (let v = b - 1; v <= b + 1; v++) {
      for (const q of G.cells.get(u * 100003 + v) || []) if (Math.hypot(p.x - q[0], p.y - q[1]) < q[3] / 2 && (top === null || q[2] > top)) top = q[2];
    }
    return top;
  }
  function seatOf(p) {
    let st = seats.get(p);
    if (st) return st;
    if (p.road) {                                            // sur la route : a plat sur son revetement (track_creator idem)
      const rz = roadUnder(p);
      if (rz !== null) { st = { low: rz + 6 - 0.3 * IN, rx: 0, ry: 0, off: null, deg: 0, onRoad: true }; seats.set(p, st); return st; }
    }
    const k = kindOf(p), d = dimOf(p), size = d.r * IN * p.s, rt = Math.max(IN, 0.7 * size), z0 = shownAt(p.x, p.y);
    let gx = 0, gy = 0;
    for (const [c, s] of RING) { const z = shownAt(p.x + rt * c, p.y + rt * s); gx += z * c; gy += z * s; }
    gx /= 4 * rt; gy /= 4 * rt;
    const g = Math.hypot(gx, gy), lim = Math.tan((k?.tilt ?? 0) * Math.PI / 180);
    // pente : la plus forte autour du pied (a 1 m et sur l'emprise). Le plan moyen seul l'adoucissait sous les gros
    // objets : il en restait sur des falaises (2026-11-11)
    let steep = g;
    for (const r of [IN, rt]) for (const [c, s] of RING) steep = Math.max(steep, Math.abs(shownAt(p.x + r * c, p.y + r * s) - z0) / r);
    const deg = Math.atan(steep) * 180 / Math.PI;
    if (g > lim) { const f = g ? lim / g : 0; gx *= f; gy *= f; }
    const rf = (k?.seat ?? 0.3) * size;
    let low = z0;
    for (const f of [0.5, 1]) for (const [c, s] of RING) {
      const dx = f * rf * c, dy = f * rf * s;
      low = Math.min(low, shownAt(p.x + dx, p.y + dy) - gx * dx - gy * dy);
    }
    // enfoncement : hauteur du sol au-dessus de la base de l'objet sous son corps (cote du haut d'une pente)
    let bury = 0;
    const rb = 0.45 * size;
    for (const f of [0.5, 1]) for (const [c, s] of RING) {
      const dx = f * rb * c, dy = f * rb * s;
      bury = Math.max(bury, shownAt(p.x + dx, p.y + dy) - (low + gx * dx + gy * dy));
    }
    const n = Math.hypot(gx, gy, 1), nx = -gx / n, ny = -gy / n, cy = Math.cos(p.yaw), sy = Math.sin(p.yaw);
    st = { low: low - 0.3 * IN, rx: -Math.asin(-sy * nx + cy * ny), ry: Math.atan2(cy * nx + sy * ny, 1 / n), off: null, deg,
           bury: bury + 0.3 * IN, h: (d.zmax - d.zmin) * IN * p.s };
    seats.set(p, st);
    return st;
  }
  const propLow = p => seatOf(p).low;
  // pose de l'origine : par la base (rochers : par l'origine, faits pour etre a moitie enterres)
  // p.dz : decalage en hauteur donne a la main (outil Modifier, pouces), 0 = pose sur le sol
  const propZ = p => propLow(p) + (p.dz || 0) - (p.t === 'rock' ? 0 : dimOf(p).zmin * IN * p.s);
  // route touchee (track_creator.prop_conflict) : au niveau de la route, seul le pied compte ; une route plus haute
  // (pont, rampe) ne doit croiser aucune partie de l'objet tant que le dessous de son tablier est sous son sommet
  function propConflict(p) {
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
        if (q[2] < base + level ? !onRoad && hd < foot : q[2] - deck < top + IN && hd < full) return true;
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
  function renderProps() {
    let off = 0;
    const buckets = new Map(), lod = propLod();
    for (const p of S.props) {
      // la route a change depuis le semis (pont, rampe) : objet ecarte a la generation, donc pas montre
      if (!kindOf(p)) { off++; continue; }                // famille inconnue : ignoree aussi a la generation
      const st = seatOf(p);
      st.off ??= propConflict(p) || !inTerrain(p) || (!st.onRoad && (st.deg > STEEP_MAX || inRoof(p)));
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
    const p = { k: c.k, t: c.t, m: c.m, x, y, yaw: +(Math.random() * 2 * Math.PI).toFixed(3), s: c.s ?? +(a + Math.random() * (b - a)).toFixed(2) };
    if (manual && roadUnder(p) !== null) p.road = 1;
    if (!seatOf(p).onRoad && seatOf(p).deg > STEEP_MAX) return false;     // falaise : rien n'y tient
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
  const AI_DENSITY = { 0: [900, 500, 0.6], 1: [450, 1000, 1], 2: [250, 1800, 1.4] };      // m2 par objet, maximum, gros objets
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
  function aiRelief(amp, rnd, D) {
    const T = S.terrain, n = T.n, c = T.cell, noise = aiNoise(rnd);
    T.aih ??= new Float32Array(n * n);
    const near = Math.max(30, amp * 1.2) * IN, wide = near + Math.max(60, amp * 3) * IN, rim = 220 * IN;
    for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) {
      const v = j * n + i, x = i * c, y = j * c, m = sstep(near, wide, D[v]);
      if (!m) continue;
      const edge = Math.min(i, j, n - 1 - i, n - 1 - j) * c, up = sstep(rim, 0, edge);
      const hill = noise(x, y, 320 * IN) * 1.5 * (1 - up) + up * (0.9 + 0.5 * noise(x, y, 180 * IN));
      const next = Math.max(T_LO, Math.min(T_HI, T.h[v] + amp * IN * hill * m));
      T.aih[v] = next - T.h[v]; T.h[v] = next;
    }
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
      const out = [];
      for (const [id, d] of shuffle(list).slice(0, own ? 3 : 2)) {
        const [k, t] = id.split('|');
        const ms = shuffle(usable(d, role)).slice(0, own ? 4 : 3);
        if (ms.length) out.push({ k, t, d, ms, far: k !== mk && k !== kit });
      }
      pals.set(key, out);
      return out;
    };
    // grille d'occupation (bien plus rapide que S.props.some pour des milliers d'essais)
    const GS = 64 * IN, grid = new Map(), bigs = [];
    const add = p => { if (kindOf(p)?.big) { bigs.push(p); return; } const key = Math.floor(p.x / GS) * 100003 + Math.floor(p.y / GS); (grid.get(key) || grid.set(key, []).get(key)).push(p); };
    S.props.forEach(add);
    const body = o => 0.5 * dimOf(o).r * IN * o.s;
    function put(c, m, x, y) {
      const k = c.d, [a, b] = k.scale;
      const p = { k: c.k, t: c.t, m, x, y, yaw: +(rnd() * 2 * Math.PI).toFixed(3), s: +(a + rnd() * (b - a)).toFixed(2), ai: 1 };
      if (!inTerrain(p) || seatOf(p).deg > STEEP_MAX || buriedTooMuch(p) || propConflict(p)) return false;
      const sp = k.spacing * IN, bp = body(p);
      const clash = q => { const gap = !!k.big !== !!kindOf(q)?.big ? 0 : Math.max(sp, (kindOf(q)?.spacing || 3) * IN) * 0.8;
        return Math.hypot(q.x - x, q.y - y) < Math.max(gap, bp + body(q)); };
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
      const w = sh * level(role), a = w ? avail(role) : 0;
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
                  dz: -Math.round((0.3 + rnd() * 1.2) * 10) / 10 * IN, type: types[Math.floor(rnd() * types.length)], ai: 1 };
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
  function inAiWater(x, y) {                                    // objet dans une eau du decor automatique
    const T = S.terrain, n = T.n, v = Math.round((y - T.y0) / T.cell) * n + Math.round((x - T.x0) / T.cell);
    return S.waters.some(w => w.ai && waterBasin(w)?.region[v]);
  }
  function aiDecor() {
    if (S.points.length < 8) { status('Trace d\'abord une route : le décor se construit autour d\'elle', 'err'); return; }
    const seed = (Date.now() ^ (Math.random() * 2 ** 31)) >>> 0;
    let s = seed;                                                 // mulberry32
    const rnd = () => { s = (s + 0x6D2B79F5) | 0; let t = Math.imul(s ^ (s >>> 15), 1 | s); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
    S.props = S.props.filter(p => !p.ai);
    S.waters = S.waters.filter(w => !w.ai); if (S.waterSel >= S.waters.length) S.waterSel = -1;
    aiClearRelief();
    const amp = +$('craiamp').value;
    if (amp > 0) aiRelief(amp, rnd, roadDistance());
    refreshTerrainMesh(); rebuild();
    const nw = aiWaters(rnd, roadDistance());                   // points d'eau dans les creux (parfois)
    const o = aiOptions();
    const { count: c, missing, borrowed } = aiPlace(rnd, o);
    if (nw) S.props = S.props.filter(p => !p.ai || !inAiWater(p.x, p.y));     // rien de pose dans l'eau
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
        k.hide?.includes(m) ? '' : tileHtml(kk, nm, m, kitNames ? kitNames[kk.split('|')[0]] : ''))).join('')}</div>`;
  const shownCount = k => (k.names || []).length - (k.hide || []).length;   // famille dont tout est masque : pas de titre vide
  // par style : un bloc repliable par theme (le theme courant en premier, ouvert) ; par type : un bloc par genre
  // d'objet (familles de tous les themes, nom du theme en titre) ; vignettes chargees a l'ouverture du bloc
  function renderPropList() {
    const grid = $('crpgrid'), cur = $('crkit').value, names = S.info?.kits || {};
    const kits = [cur, ...(S.info?.order || Object.keys(names)).filter(k => k !== cur)];
    if ($('crpsort').value === 'type') {
      const groups = [...PROP_TYPES.map(([l]) => l), '📦 Autres objets', '⛰ Gros objets (fond de map)'];
      const fams = kits.flatMap(kit => Object.entries(propKinds).filter(([kk, k]) => kk.startsWith(kit + '|') && shownCount(k)));
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
        kick[i] = Math.max(kick[i], KICK_H * (1 - (j * STEP / (2 * IN) - 1) / (KICK_LEN / (2 * IN))));
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
      const reach = T.cell + Math.max(BLEND_MIN, slope * (Math.abs(P[k][2] - S.groundZ) + Math.abs(P[k][5]) + hMax + 2 * IN));
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
        const dz = Math.max(Math.abs(h0[v] - zlo), Math.abs(h0[v] - zhi)), lim = T.cell + Math.max(BLEND_MIN, slope * free * dz);
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
        const bl = Math.max(BLEND_MIN, Math.abs(rz - h0[v]) * slope * free);
        if (d >= T.cell + bl) continue;
        if (last[v] >= 0 && k - last[v] > 3) { if (runV[v] < acc[v]) acc[v] = runV[v]; runD[v] = Infinity; }   // autre passage
        let val = rz;
        if (d > T.cell) { const tt = (d - T.cell) / bl, s = tt * tt * (3 - 2 * tt); val = rz * (1 - s) + h0[v] * s; }
        if (d < runD[v] || (d === runD[v] && val < runV[v])) { runD[v] = d; runV[v] = val; }
        last[v] = k;
      }
    }
    // S.raw : sol raccorde ; S.shown (affiche) en est une copie ou les ponts de terre sont fusionnes (refreshTerrainMesh)
    const out = S.raw?.length === N ? S.raw : new Float32Array(N);
    for (let j = J0; j <= J1; j++) for (let i = I0, v = j * n + I0; i <= I1; i++, v++) {
      const a = runD[v] < Infinity ? Math.min(acc[v], runV[v]) : acc[v];
      out[v] = a < Infinity && !T.dig?.[v] ? a : h0[v];                // creuse sous la route : relief garde
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
    const old = terrainFaces, tp = T.paint, fade = S.fade ?? FADE_DEF;
    if (old.paint?.length === tp.length && old.last === last && old.fade === fade && old.used.map(c => c <= last ? sigOne(c) : sigOf(c, old.mixes)).join() === old.sig && terrainGeo.index?.count === cells * 6) {
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
      const a = j * n + i, b = a + 1, c = a + n + 1, d = a + n; let o = w[best[q]];
      ix[o++] = a; ix[o++] = b; ix[o++] = c; ix[o++] = a; ix[o++] = c; ix[o++] = d; w[best[q]] = o;
    }
    idx.needsUpdate = true;
    terrainGeo.clearGroups();
    used.forEach((m, g) => terrainGeo.addGroup(start[m], count[m] * 6, g));
    terrainMesh.material = used.map(m => { const key = sigOf(m, mixes), mix = m > last ? mixes[m - last - 1] : null, mt = matOf(mix ? mix[0] : m), mb = mix && matOf(mix[1]);
      if (!terrainMats.has(key)) terrainMats.set(key, mix && mt.png && mb.png ? mixMaterial(key, mt, mb, mix[2]) : new THREE.MeshBasicMaterial({ vertexColors: true,
        side: THREE.DoubleSide,                               // dessous des ponts de terre (refreshRoof) avec la meme matiere
        ...(mt.png ? { map: kitTexture(mt.png, mt.kit) } : { color: new THREE.Color(...mt.color) }) }));
      return terrainMats.get(key); });
    terrainFaces = { paint: tp.slice(), last, used, mixes, fade, sig: used.map(c => sigOf(c, mixes)).join(),
                     best, mats: new Map(used.map((m, g) => [m, terrainMesh.material[g]])) };
  }
  // ---- tunnels (2026-11-11 ; meme calcul que track_creator._roof_mask) : la ou le relief marque (pinceau Deplacer sur
  // le cote, ou Creuser sous la route) passe a plus de ROOF_CLEAR au-dessus de la route, il reste au-dessus comme un
  // plafond et la route passe dessous. Sans marque, une tranchee profonde reste une tranchee. ----
  const ROOF_CLEAR = 8 * IN, ROOF_EDGE = 0.3 * IN, ROOF_REACH = 60 * IN, ROOF_THICK = 6 * IN, ROOF_KEEP = 12 * IN, ROOF_KEEP_R = 40 * IN;
  let roofRoad = { src: null };
  function roofRoadZ() {                                      // dessus de la route sous chaque sommet (NaN hors route)
    const T = S.terrain, n = T.n, c = T.cell, E = S.eff || effPoints(), key = `${T.x0}|${T.y0}|${c}|${n}`;
    if (roofRoad.src === E && roofRoad.key === key) return roofRoad.rz;
    const rz = new Float32Array(n * n).fill(NaN);
    for (const q of E) {
      if (q[4]) continue;
      const r = q[3] / 2, z = q[2] + 6;
      const i0 = Math.max(0, Math.floor((q[0] - r - T.x0) / c)), i1 = Math.min(n - 1, Math.ceil((q[0] + r - T.x0) / c));
      const j0 = Math.max(0, Math.floor((q[1] - r - T.y0) / c)), j1 = Math.min(n - 1, Math.ceil((q[1] + r - T.y0) / c));
      for (let j = j0; j <= j1; j++) for (let i = i0; i <= i1; i++) {
        const v = j * n + i;
        if (Math.hypot(T.x0 + i * c - q[0], T.y0 + j * c - q[1]) < r && !(rz[v] >= z)) rz[v] = z;
      }
    }
    roofRoad = { src: E, key, rz };
    return rz;
  }
  function roofMask() {                                       // sommets du plafond (Uint8Array) ou null
    const T = S.terrain; if (!T?.dig || !T.dig.some(v => v)) return null;
    const n = T.n, N = n * n, H = S.raw; if (!H || H.length !== N) return null;
    const rz = roofRoadZ(), h0 = v => S.groundZ + T.h[v], low = v => h0(v) - H[v];
    const roof = new Uint8Array(N), ref = new Float32Array(N);
    let front = [];
    for (let v = 0; v < N; v++) if (T.dig[v] && rz[v] === rz[v] && h0(v) - rz[v] >= ROOF_CLEAR) { roof[v] = 1; ref[v] = rz[v]; front.push(v); }
    if (!front.length) return null;
    const ok = (w, r) => !roof[w] && low(w) > ROOF_EDGE && h0(w) >= r + ROOF_CLEAR / 2 && (rz[w] !== rz[w] || h0(w) - rz[w] >= ROOF_CLEAR);
    for (let d = 1, maxD = Math.ceil(ROOF_REACH / T.cell); d <= maxD && front.length; d++) {
      const next = [];
      for (const v of front) {
        const i = v % n, j = (v - i) / n;
        for (const w of [i > 0 ? v - 1 : -1, i < n - 1 ? v + 1 : -1, j > 0 ? v - n : -1, j < n - 1 ? v + n : -1])
          if (w >= 0 && ok(w, ref[v])) { roof[w] = 1; ref[w] = ref[v]; next.push(w); }
      }
      front = next;
    }
    roof.ref = ref;                                           // dessus de la route couverte, par sommet (volume du tunnel)
    // partie au-dessus de la route (sommets de la route et leurs 4 voisins) : dalle avec le vide dessous ; le reste
    // (flancs des buttes reliees) est plein jusqu'au sol (track_creator : span)
    const onRoad = v => rz[v] === rz[v];
    roof.span = new Uint8Array(N);
    for (let v = 0; v < N; v++) if (roof[v]) {
      const i = v % n, j = (v - i) / n;
      roof.span[v] = onRoad(v) || (i > 0 && onRoad(v - 1)) || (i < n - 1 && onRoad(v + 1)) || (j > 0 && onRoad(v - n)) || (j < n - 1 && onRoad(v + n)) ? 1 : 0;
    }
    // au-dessus de la route, seule la partie haute de la bande reste (ROOF_KEEP sous son sommet local) : ses bords en pente
    // pendaient en voiles jusque pres de la route (track_creator idem)
    const k = Math.round(ROOF_KEEP_R / T.cell), drop = [];
    for (let v = 0; v < N; v++) if (roof.span[v]) {
      const i = v % n, j = (v - i) / n;
      let peak = -Infinity;
      for (let b = Math.max(0, j - k); b <= Math.min(n - 1, j + k); b++) for (let a = Math.max(0, i - k); a <= Math.min(n - 1, i + k); a++)
        if (roof.span[b * n + a]) peak = Math.max(peak, h0(b * n + a));
      if (h0(v) < Math.max(ref[v] + ROOF_CLEAR + ROOF_THICK, peak - ROOF_KEEP)) drop.push(v);
    }
    for (const v of drop) roof[v] = roof.span[v] = 0;
    return roof;
  }
  // objet seme sur l'emprise d'un plafond : ni dessus ni dans le tunnel (ecarte a la generation aussi)
  const inRoof = p => { const T = S.terrain, R = S.roof; if (!R || !T) return false;
    const i = Math.round((p.x - T.x0) / T.cell), j = Math.round((p.y - T.y0) / T.cell);
    return i >= 0 && j >= 0 && i < T.n && j < T.n && !!R[j * T.n + i]; };
  function refreshRoof() {
    const R = roofMask(), had = !!S.roof;
    S.roof = R;
    if (had !== !!R) clearSeats();
    roofMesh.geometry.dispose(); roofMesh.geometry = new THREE.BufferGeometry();
    if (!R) { roofMesh.visible = false; return; }
    // FUSIONNE AU RELIEF, meme calcul que la generation (track_creator, « tunnels ») : les flancs des buttes reliees sont
    // le relief lui-meme (S.shown, refreshTerrainMesh) ; seule la partie au-dessus de la route est dessinee ici, son dessus
    // dans le prolongement du relief (meme hauteur, meme ombrage, memes peintures case par case), dessous = dalle de
    // ROOF_THICK (jamais a moins de ROOF_CLEAR de la route) qui rejoint le dessus des buttes a ses bouts
    const T = S.terrain, n = T.n, c = T.cell, H = S.shown, rep = (S.kitInfo?.ground_repeat || 12) * IN;
    // dessus : relief du pont ; hors du pont, le sol affiche (bloc ou butte que la bande rejoint)
    const top = v => R[v] ? S.groundZ + T.h[v] : H[v];
    // case du pont : un coin au moins au-dessus de la route, les autres dans le pont OU sur du relief haut que la bande
    // touche (pas abaisse par le raccord, au moins ROOF_CLEAR au-dessus de la route) : la bande s'y soude sans trou
    const cellOk = new Uint8Array((n - 1) * (n - 1));
    for (let j = 0; j < n - 1; j++) for (let i = 0; i < n - 1; i++) {
      const a = j * n + i, q = [a, a + 1, a + n, a + n + 1];
      if (!q.some(v => R.span[v])) continue;
      const ref = Math.max(...q.filter(v => R.span[v]).map(v => R.ref[v]));
      cellOk[j * (n - 1) + i] = q.every(v => R[v] || (S.groundZ + T.h[v] - S.raw[v] <= ROOF_EDGE && H[v] >= ref + ROOF_CLEAR)) ? 1 : 0;
    }
    const isCell = (i, j) => i >= 0 && j >= 0 && i < n - 1 && j < n - 1 && cellOk[j * (n - 1) + i] === 1;
    const bot = v => R.span[v] ? Math.min(top(v) - 0.5 * IN, Math.max(top(v) - ROOF_THICK, H[v], R.ref[v] + ROOF_CLEAR)) : top(v);
    // ombrage du relief (refreshTerrainMesh) d'apres la surface vue de dessus : pont compris
    const surf = top, in2 = 1 / (2 * c);
    const shade = v => {
      const i = v % n, j = (v - i) / n, a = i > 0 ? v - 1 : v, b = i < n - 1 ? v + 1 : v, d0 = j > 0 ? v - n : v, d1 = j < n - 1 ? v + n : v;
      const nx = -(surf(b) - surf(a)) * in2, ny = -(surf(d1) - surf(d0)) * in2, dot = (nx * 0.45 + ny * -0.35 + 0.82) / Math.sqrt(nx * nx + ny * ny + 1);
      return Math.min(1, 0.55 + 0.5 * Math.max(0, dot));
    };
    const best = terrainFaces.best, groups = new Map(), bz = new Map();
    const B = v => { if (!bz.has(v)) bz.set(v, bot(v)); return bz.get(v); };
    let out = null;
    const P = (v, z, s) => { const x = T.x0 + (v % n) * c, y = T.y0 + Math.floor(v / n) * c; out.pos.push(x, y, z); out.uv.push(x / rep, y / rep); out.col.push(s, s, s); };
    const tri = (a, za, b, zb, d, zd, s) => { P(a, za, s ?? shade(a)); P(b, zb, s ?? shade(b)); P(d, zd, s ?? shade(d)); };
    for (let j = 0; j < n - 1; j++) for (let i = 0; i < n - 1; i++) {
      if (!isCell(i, j)) continue;
      const code = best?.[j * (n - 1) + i] ?? 0;
      out = groups.get(code) || groups.set(code, { pos: [], uv: [], col: [] }).get(code);
      const a = j * n + i, q = [a, a + 1, a + n + 1, a + n], t = v => top(v) - 2;           // -2 : comme le relief
      tri(q[0], t(q[0]), q[1], t(q[1]), q[2], t(q[2])); tri(q[0], t(q[0]), q[2], t(q[2]), q[3], t(q[3]));       // dessus
      tri(q[0], B(q[0]), q[2], B(q[2]), q[1], B(q[1]), 0.45); tri(q[0], B(q[0]), q[3], B(q[3]), q[2], B(q[2]), 0.45);   // dessous
      for (const [di, dj, p, r] of [[0, -1, q[0], q[1]], [1, 0, q[1], q[2]], [0, 1, q[2], q[3]], [-1, 0, q[3], q[0]]]) {
        if (isCell(i + di, j + dj) || !(R.span[p] || R.span[r])) continue;      // paroi (pas entre deux sommets de butte)
        tri(p, t(p), r, t(r), r, B(r), 0.6); tri(p, t(p), r, B(r), p, B(p), 0.6);
      }
    }
    const pos = [], uv = [], col = [], mats = [];
    for (const [code, g] of groups) {
      roofMesh.geometry.addGroup(pos.length / 3, g.pos.length / 3, mats.length);
      mats.push(terrainFaces.mats?.get(code) || terrainMesh.material[0] || roofMesh.userData.mat0);
      for (const x of g.pos) pos.push(x);
      for (const x of g.uv) uv.push(x);
      for (const x of g.col) col.push(x);
    }
    roofMesh.geometry.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    roofMesh.geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
    roofMesh.geometry.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
    roofMesh.material = mats;
    roofMesh.visible = pos.length > 0;
  }
  // box : zone modifiee (monde), le reste du maillage ne bouge pas ; sans box : tout le terrain
  function refreshTerrainMesh(box = null) {
    clearSeats(box);                                          // objets de la zone : a reposer sur le sol
    const T = S.terrain, n = T.n, N = n * n, cell = T.cell;
    let rg = box && S.shown?.length === N && terrainGeo.attributes.position?.count === N ? gridRange(box) : null;
    if (box && !rg && S.shown?.length === N && terrainGeo.attributes.position?.count === N) { refreshTerrainFaces(); return; }   // hors du terrain
    conform(rg);
    // pont de terre fusionne au relief (track_creator idem) : sous la partie au-dessus de la route, sol au niveau de la
    // route (vide jusqu'a la dalle) ; flancs des buttes reliees rendus au relief (un seul bloc avec la bande)
    S.shown.set(S.raw);
    const under = roofMask(), mods = new Set();
    if (under) for (let v = 0; v < N; v++) if (under[v]) {
      S.shown[v] = under.span[v] ? Math.min(S.raw[v], under.ref[v] - 16) : S.groundZ + T.h[v];   // ref : dessus de la route
      mods.add(v);
    }
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
    renderWater(); syncWaterLevel(); saveDraft();
    const inf = S.waterInfo[S.waterSel];
    status(`Trou rempli : ${Math.round(inf.area)} m², ${(inf.depth / IN).toFixed(1).replace('.', ',')} m au plus profond` +
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
    const T = S.terrain, p = S.mouse; if (!T || !p) return;
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
  // ponts de terre : liste creuse [sommet, hauteur, ...] et epaisseur (upt)
  const packTerrain = T => T && { x0: T.x0, y0: T.y0, cell: T.cell, n: T.n, h: Array.from(T.h, v => Math.round(v)), paint: Array.from(T.paint),
                                  ...(T.dig?.some(v => v) ? { dig: Array.from(T.dig) } : {}) };
  // relief du decor automatique (pouces, entiers 16 bits en base64) : 2,7 caracteres par sommet, pour le retirer apres reouverture
  const packI16 = a => { const u = new Uint8Array(Int16Array.from(a, v => Math.round(v)).buffer); let s = '';
    for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode.apply(null, u.subarray(i, i + 0x8000)); return btoa(s); };
  const unpackI16 = (b, n) => { const s = atob(b), u = new Uint8Array(s.length); for (let i = 0; i < s.length; i++) u[i] = s.charCodeAt(i);
    return u.length === n * 2 ? Float32Array.from(new Int16Array(u.buffer)) : undefined; };
  const packFull = T => T && { ...packTerrain(T), size: T.size, full: true, blend: S.blendSlope ?? BLEND_DEF, fade: S.fade ?? FADE_DEF,       // carre de base complet genere
                               ...(T.aih?.some(v => v) ? { aih: packI16(T.aih) } : {}) };
  // brouillon ecrit au plus une fois par seconde (700 Ko a chaque point pose par le paveur), et a la fermeture
  let draftTimer = 0;
  const saveDraft = () => { draftTimer ||= setTimeout(writeDraft, 1000); histSchedule(); };
  addEventListener('pagehide', () => { if (draftTimer) writeDraft(); });
  const writeDraft = () => { clearTimeout(draftTimer); draftTimer = 0; try { localStorage.setItem(draftKey(), JSON.stringify({ at: Date.now(), points: S.points, closed: S.closed, ground_z: S.groundZ, start: S.points.length <= 1 ? S.start : undefined, width: S.width, barriers: $('crbar').value, props: S.props, waters: S.waters, kit: $('crkit').value, sel: [...S.sel], far: +$('crpfar').value,
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
                                    kit: $('crkit').value, sel: [...S.sel], far: $('crpfar').value, props: S.props, waters: S.waters,
                                    t: T && [T.x0, T.y0, T.cell, T.n, T.size] }),
             h: T?.h.slice(), paint: T?.paint.slice(), dig: T?.dig?.slice(), aih: T?.aih?.slice() };
  }
  const sameArr = (a, b) => a === b || (a && b && a.length === b.length && a.every((v, i) => v === b[i]));
  const histSame = (a, b) => a.meta === b.meta && sameArr(a.h, b.h) && sameArr(a.paint, b.paint) && sameArr(a.dig, b.dig);
  function histButtons() {
    $('crundo').disabled = histAt <= 0; $('crredo').disabled = histAt >= hist.length - 1;
    // fleches de la barre du haut : meme etat ($ ne cherche que dans le panneau de droite)
    document.getElementById('undo').disabled = histAt <= 0; document.getElementById('redo').disabled = histAt >= hist.length - 1;
  }
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
    // objet selectionne (outil Modifier) : retrouve dans l'etat remis par sa place dans la liste
    const si = S.propSelP ? S.props.indexOf(S.propSelP) : -1;
    S.points = m.points; S.closed = m.closed; S.props = m.props; S.sel = new Set(m.sel);
    S.propSelP = si >= 0 && S.props[si] ? S.props[si] : null;
    if (!S.propSelP) selectProp(null);
    S.waters = m.waters || []; if (S.waterSel >= S.waters.length) S.waterSel = -1;
    $('crbar').value = m.barriers; $('crpfar').value = m.far; $('crpfarv').textContent = m.far;
    if (m.t) {
      S.terrain = { x0: m.t[0], y0: m.t[1], cell: m.t[2], n: m.t[3], size: m.t[4], h: s.h.slice(), paint: s.paint.slice(),
                    dig: s.dig ? s.dig.slice() : new Uint8Array(m.t[3] * m.t[3]), aih: s.aih?.slice() };
      $('crsize').value = String(m.t[4]);
    }
    if ($('crkit').value !== m.kit) { $('crkit').value = m.kit; applyKit(); } else syncSel();
    setWidth(m.width); placeFromPoints(); S.back = 0;          // pente du bout de route reprise (placeFromPoints)
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
  $('craigo').onclick = aiDecor;
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
  function placeFromPoints() {
    const p = S.points[S.points.length - 1];
    S.pos = new THREE.Vector3(p[0], p[1], p[2]); S.roll = rollOf(p); setRollTarget(S.roll); setTalus(!p[9]);
    if (S.points.length > 1) { const q = S.points[S.points.length - 2]; S.yaw = Math.atan2(p[1] - q[1], p[0] - q[0]); }
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
    return Math.max(-SLOPE_MAX, Math.min(SLOPE_MAX, (b[2] - a[2]) / run));
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
    showRoadStat();
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
      const m = T.cell + Math.max(wl, wr) + Math.max(BLEND_MIN, (S.blendSlope ?? BLEND_DEF) * (Math.abs(q[2] - S.groundZ) + Math.abs(hl) + Math.abs(hr) + (S.hMax || 0) + 2 * IN)) + 4 * IN;
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
    if (!S.active) return;
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
           : m === 'bridge' ? 'Pont : clique sur la route là où elle croise une autre route (clic droit : tourner la vue)'
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
  view.addEventListener('pointerdown', e => {
    if (!S.active || S.mode === 'route' || e.button !== 0 || e.target !== canvas) return;
    if (S.mode === 'edges') { edgePointerDown(e); return; }
    if (S.mode === 'bridge') { bridgePointerDown(e); return; }
    if (S.mode === 'props' && S.propTab === 'man' && S.propEdit) { propPointerDown(e); return; }
    if (S.mode === 'terrain' && S.tool === 'water' && (S.waterMode || 'fill') === 'fill') { waterPointerDown(e); return; }
    if (noBrush()) return;
    const p = pick(e); if (!p) return;
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
    const p = pick(e);
    brush.visible = !!p;
    if (p) { S.mouse = p; brush.position.set(p.x, p.y, p.z + 20); brush.scale.set(S.radius, S.radius, 1); }
    if (S.brushing) { e.preventDefault(); e.stopImmediatePropagation(); }
  }, true);
  const endBrush = e => {
    if (!S.brushing) return;
    S.brushing = false; orbit.enabled = true;
    if (S.mode === 'terrain' && S.tool === 'water') { waterStrokeEnd(); e?.stopImmediatePropagation?.(); return; }   // relief inchange
    // fin du trait : la zone peinte seulement ; talus et objets suivent le relief (rien de tout ca pour la peinture et le decor)
    if (S.mode === 'terrain') { refreshTerrainMesh(S.strokeBox); rebuild(); renderProps(); }
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
    ptc.addEventListener('objectChange', propDrag);
  }
  S.propSelP = null; S.propEdit = false;
  function setPropGizmo(m) {
    if (!ptc) return;
    ptc.setMode(m);
    ptc.showX = ptc.showY = ptc.showZ = true;                          // tourner : 3 axes (2026-11-12 ; avant : verticale seule)
    panel.querySelectorAll('[data-ptm]').forEach(b => b.classList.toggle('primary', b.dataset.ptm === m));
  }
  function selectProp(p) {
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
    w.hidden = !off;
    if (off) w.textContent = st.deg > STEEP_MAX ? 'Sur une pente trop forte : il ne sera pas posé.'
      : !inTerrain(p) ? 'Hors du terrain : il ne sera pas posé.' : 'Il touche la route (ou un pont) : il ne sera pas posé. Pose-le sur la route ou plus loin.';
  }
  // l'objet a change : pose recalculee (sol, route dessous), objet « a la main », vue
  function propChanged(p) {
    delete p.ai;
    if (roadUnder(p) !== null) p.road = 1; else delete p.road;
    seats.delete(p); renderProps();
  }
  function propDragStart() { const p = S.propSelP; if (p) S.propDrag = { z: propZ(p), dz: p.dz || 0, s: p.s }; }
  function propDrag() {
    const p = S.propSelP, b = S.propDrag; if (!p || !b) return;
    const m = ptc.getMode();
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
      p.s = +Math.max(0.05, Math.min(20, b.s * f)).toFixed(2); sc.setScalar(p.s);
    }
    propChanged(p);
  }
  function propDragEnd() { S.propDrag = null; syncPropSel(); saveDraft(); }
  function propTyped() {
    const p = S.propSelP; if (!p) return;
    const yaw = +$('crpeyaw').value, s = +$('crpes').value, dz = +$('crpedz').value;
    if (Number.isFinite(yaw)) p.yaw = +(yaw * Math.PI / 180).toFixed(3);
    for (const k of ['rx', 'ry']) {
      const v = +$('crpe' + k).value;
      if (Number.isFinite(v)) { const a = +(Math.max(-180, Math.min(180, v)) * Math.PI / 180).toFixed(3); if (a) p[k] = a; else delete p[k]; }
    }
    if (Number.isFinite(s) && s > 0) p.s = +Math.max(0.05, Math.min(20, s)).toFixed(2);
    if (Number.isFinite(dz)) { p.dz = Math.round(dz * IN); if (!p.dz) delete p.dz; }
    propChanged(p); syncPropSel(); saveDraft();
  }
  function propDelete() {
    const p = S.propSelP; if (!p) return;
    S.props = S.props.filter(q => q !== p); selectProp(null); renderProps(); saveDraft(); status('Objet supprimé (Ctrl+Z pour annuler)');
  }
  function propDuplicate() {
    const p = S.propSelP; if (!p) return;
    const step = Math.max(2 * IN, 1.2 * dimOf(p).r * IN * p.s), q = { ...p, x: Math.round(p.x + step * Math.cos(p.yaw)), y: Math.round(p.y + step * Math.sin(p.yaw)) };
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
    if (!p) { selectProp(null); return; }                     // a cote : la vue tourne
    selectProp(p);
    e.preventDefault(); e.stopImmediatePropagation();
  }
  addEventListener('keydown', e => {
    if (!S.active || !S.propSelP || S.mode !== 'props' || typing(e) || e.altKey) return;
    const k = e.key.toLowerCase();
    if (e.ctrlKey || e.metaKey) { if (k !== 'd') return; propDuplicate(); }
    else if (k === 'w' || k === 'z') setPropGizmo('translate');
    else if (k === 'e') setPropGizmo('rotate');
    else if (k === 'r') setPropGizmo('scale');
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
                                                                  waterBasin, renderWater, waterPointerDown, placeFromPoints, slopeOfEnd, selectEdge, edgeZone, edgeSmooth, setEdgeZone };
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
  $('crpeground').onclick = () => { const p = S.propSelP; if (!p) return; delete p.dz; propChanged(p); syncPropSel(); saveDraft(); };
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
  $('crgo').onclick = async () => {
    // ou generer : piste selectionnee ou nouvelle piste (nom, categorie), choix explicite avant tout le reste
    const target = await chooseTarget();
    if (!target) return;
    // repartir de zero : aussi les ajouts faits dans Edition (imports, bibliotheque, copies) et toute la scene de
    // course ; sinon ils restent avec la piste generee. Nouvelle piste : rien a garder (caisses de Crash Cove retirees)
    let wipe = true;
    if (!target.isNew) {
      const c = await choose('Générer la piste ? Le sol et le décor d\'origine sont retirés, la création précédente est remplacée, '
        + 'puis le parcours et les IA sont créés et enregistrés (≈ 1 à 3 min).\n\nSupprimer aussi la map en cours dans Édition pour '
        + 'repartir de zéro ? Tes imports, objets de la bibliothèque et copies, ainsi que la scène de course (caisses, boosters, '
        + 'zones de chute, téléporteurs, embranchements).', ['🧹 Repartir de zéro', 'Garder la map en cours']);
      if (c < 0) return;
      wipe = c === 0;
    }
    // beaucoup de carte loin de la route : le jeu la charge pour rien. Retrait a la generation seulement, le brouillon reste complet
    let trim = false;
    const far = farFromRoad();
    if (far && far.share >= FAR_TRIM_SHARE) {
      const t = await choose(`${Math.round(far.share * 100)} % de la carte est à plus de ${FAR_TRIM_M} m de la route : personne n'y roule, mais le jeu doit la charger.\n\n`
        + `La retirer de la piste générée ? Le relief, la peinture et les ${far.props} objet(s) qui s'y trouvent n'y seront pas. Ton brouillon reste complet : tu pourras regénérer sans retrait.`,
        ['✂ Retirer cette partie', 'Tout garder']);
      if (t < 0) return;
      trim = t === 0;
    }
    $('crgo').disabled = true;
    try {
      const dest = target.isNew ? await createTarget(target) : getTrack();
      status('Génération de la piste…');
      const r = await api('/api/create_build', { track: dest, points: S.points, closed: S.closed, ground_z: S.groundZ,
                                                  kit: $('crkit').value, barriers: $('crbar').value, props: S.props, waters: S.waters,
                                                  terrain: { ...packFull(S.terrain), ...(trim ? { trim_m: FAR_TRIM_M } : {}) }, wipe });
      await onGenerate({ ...r, wipe, track: dest });
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
    await loadKart();
    const st = getStart();
    S.start = { pos: st.pos, yaw: st.yaw }; S.groundZ = st.groundZ;
    far.position.set(st.pos[0], st.pos[1], S.groundZ - 60);
    let info = { saved: null, kits: { sable: 'Plage de sable (Crash Cove)' } };
    try { info = await (await fetch('/api/creator?track=' + encodeURIComponent(getTrack()))).json(); } catch (e) { /* sans importance */ }
    $('crkit').innerHTML = (info.order || Object.keys(info.kits)).map(k => [k, info.kits[k]]).map(([k, l]) => `<option value="${k}">${l}</option>`).join('');
    let draft = null;
    try { draft = JSON.parse(localStorage.getItem(draftKey()) || 'null'); } catch (e) { /* sans importance */ }
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
      S.groundZ = Number.isFinite(src.ground_z) && Math.abs(src.ground_z - fromTrace) < 20 * IN ? src.ground_z : fromTrace;
      far.position.z = S.groundZ - 60;
    } else if (Number.isFinite(src?.ground_z)) { S.groundZ = src.ground_z; far.position.z = S.groundZ - 60; }
    $('crsize').value = String(S.terrain.size);
    $('crbar').value = src?.barriers || 'curves';
    setBlend(Number.isFinite(src?.terrain?.blend) ? src.terrain.blend : BLEND_DEF);
    setFade(Number.isFinite(src?.terrain?.fade) ? src.terrain.fade : FADE_DEF);
    S.info = info;
    if (src?.kit && info.kits[src.kit]) $('crkit').value = src.kit;
    // anciens brouillons : objets et choix sans theme = theme du brouillon
    const k0 = src?.kit && info.kits[src.kit] ? src.kit : 'sable';
    S.sel = new Set((Array.isArray(src?.sel) ? src.sel : []).map(s => s.split('|').length === 2 ? k0 + '|' + s : s));
    $('crpfar').value = String(src?.far || 60); $('crpfarv').textContent = $('crpfar').value;
    applyKit();
    S.props = (Array.isArray(src?.props) ? src.props : []).map(p => p.k ? p : { ...p, k: k0 });
    S.waters = Array.isArray(src?.waters) ? src.waters.filter(w => (Number.isFinite(w?.x) && Number.isFinite(w?.y)) || (w?.paint && Array.isArray(w.v) && Number.isFinite(w.level))) : [];
    for (const w of S.waters) if (!w.paint && [0.3, 1].some(d => Math.abs((w.dz ?? WATER_DZ) + d * IN) < 0.01)) w.dz = WATER_DZ;   // anciens defauts 30 cm / 1 m -> 5 m
    S.waterSel = -1;
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
    group.visible = true; panel.hidden = false; S.active = true; S.last = 0;
    setTool(S.tool); setPaint(S.paint); setMode('route');
    rebuild(); renderProps(); histReset();
    status('Création : conduis le paveur (↑ avancer, ← → tourner, R / F monter / descendre) — onglet Terrain pour sculpter le sol');
  }
  function close() {
    if (!S.active) return;
    if (draftTimer) writeDraft();
    ctx.setRenderScale?.(1);                                 // l'editeur garde sa pleine resolution
    if (S.savedNear) { camera.near = S.savedNear; camera.updateProjectionMatrix(); }
    selectProp(null);                                        // poignees de l'outil Modifier detachees (sinon actives dans l'editeur)
    S.active = false; S.keys.clear(); S.brushing = false; panel.hidden = true; group.visible = false; orbit.enabled = true;    restoreButtons();
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
  // « Enregistrer » dans la Creation : brouillon du navigateur + copie sur le serveur (autre navigateur, autre PC)
  async function saveNow() {
    writeDraft();
    try {
      const d = localStorage.getItem(draftKey());
      if (d) await api('/api/creator_draft', { track: getTrack(), draft: JSON.parse(d) });
      return true;
    } catch (e) { return false; }
  }
  return { open, close, tick, rehide, undo, redo, saveNow, get active() { return S.active; } };
}
