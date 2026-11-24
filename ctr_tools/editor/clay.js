// ---- sol en pâte à modeler (essai 2026-11-24, copie ctr_tools_clay) -------------------------------------------------
// Tout le sol de la Création est un VOLUME : un champ F(x, y, z) (pouces), négatif dans la matière, positif dans l'air.
//   F = base + D
//   base = z - (sol du relief affiché)     -> les outils actuels (Monter, Creuser, Lisser, Peinture, raccord à la route)
//                                             continuent de modeler la base
//   D    = retouches en volume (outil Étirer), par blocs de CH³ points, seulement là où on a étiré
// Surface affichée : « surface nets » sur une grille de V (4 m), un sommet par case placé à la moyenne des passages de
// la surface sur ses arêtes, lissé, normales d'après le champ (éclairage doux, pas de facettes). Les blocs partagent
// leurs points de bord : aucune couture. Deux morceaux de matière qui se touchent n'en font qu'un (même champ).
// Étirer : la matière sous le curseur suit la souris avec un fondu (F(x) <- F(x - d·w(x))), comme une pâte qu'on tire.
export function createClay(o) {
  const { THREE, IN } = o;
  const V = 4 * IN, CH = 16, CW = V * CH;                   // voxel 4 m, bloc de 16 voxels (64 m)
  const group = new THREE.Group(); group.name = 'clay';  const meshes = new Map();                                 // cle du bloc -> Mesh
  const D = new Map();                                      // cle du bloc -> Float32Array(CH³) retouches aux points du bloc
  let version = 0;
  // cles numeriques (2026-11-24, vitesse : une cle texte construite a chaque lecture du champ coutait la moitie du temps)
  const key = (a, b, c) => ((a + 2048) * 4096 + (b + 2048)) * 4096 + (c + 2048);
  const unkey = k => [Math.floor(k / 16777216) - 2048, Math.floor(k / 4096) % 4096 - 2048, k % 4096 - 2048];
  const fl = Math.floor;
  let epoch = 0;                                            // change a chaque modification de D (caches ci-dessous)
  const setD = (k, a) => { D.set(k, a); epoch++; };
  const clearD = () => { D.clear(); epoch++; };

  // ---- champ -------------------------------------------------------------------------------------------------------
  const T = () => o.terrain();
  const groundAt = (x, y) => o.ground(x, y);               // sol du relief affiché (pouces, absolu)
  let lastK = NaN, lastA = null, lastE = -1;               // dernier bloc lu (les lectures voisines tombent souvent dedans)
  function dAt(ix, iy, iz) {                                // retouche au point de grille (ix, iy, iz)
    if (!D.size) return 0;
    const cx = fl(ix / CH), cy = fl(iy / CH), cz = fl(iz / CH), k = key(cx, cy, cz);
    if (k !== lastK || lastE !== epoch) { lastK = k; lastE = epoch; lastA = D.get(k) || null; }
    if (!lastA) return 0;
    return lastA[((iz - cz * CH) * CH + (iy - cy * CH)) * CH + (ix - cx * CH)];
  }
  function dSample(x, y, z) {                               // retouche interpolée en un point quelconque
    const gx = x / V, gy = y / V, gz = z / V, ix = fl(gx), iy = fl(gy), iz = fl(gz), u = gx - ix, v = gy - iy, w = gz - iz;
    let s = 0;
    for (let c = 0; c < 8; c++) {
      const a = c & 1, b = (c >> 1) & 1, e = c >> 2, val = dAt(ix + a, iy + b, iz + e);
      if (val) s += val * (a ? u : 1 - u) * (b ? v : 1 - v) * (e ? w : 1 - w);
    }
    return s;
  }
  const field = (x, y, z) => z - groundAt(x, y) + dSample(x, y, z);

  // ---- maillage d'un bloc (surface nets) ---------------------------------------------------------------------------
  const NP = CH + 2;                                        // points -1..CH du bloc
  const pf = new Float32Array(NP * NP * NP), colH = new Float32Array(NP * NP);
  const cellV = new Int32Array((CH + 1) ** 3), cellP = new Float32Array((CH + 1) ** 3 * 3), cellN = new Float32Array((CH + 1) ** 3 * 3);
  const EDGES = [[0, 1], [2, 3], [4, 5], [6, 7], [0, 2], [1, 3], [4, 6], [5, 7], [0, 4], [1, 5], [2, 6], [3, 7]];
  const CORNER = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1], [1, 1, 1]];
  const Lx = 0.45, Ly = -0.35, Lz = 0.82, Ln = Math.hypot(Lx, Ly, Lz);

  // ---- zone de pate (2026-11-24, vitesse : tout le sol en pate = 770 000 triangles, 1 400 morceaux a l'ecran) ----------
  // Comme l'export du jeu (clay_terrain.py) : le relief habituel partout ; la pate seulement dans les cases du relief
  // ou elle a ete retouchee (au moins 10 cm), + 2 cases de marge. Grille de la pate alignee sur celle du relief (2 voxels
  // par case) ; anneau de voxels juste dehors : sommets poses SUR l'arete du relief, a sa hauteur (couture sans fente).
  const MARGIN = 2;
  let regE = -1, regVersion = 0, regDirty = null, region = null, colR = null, regN = 0, AX = 0, AY = 0, NCV = 0;
  function computeRegion() {
    const Tt = T(); if (!Tt) return false;
    const n = Tt.n, nc = n - 1;
    if (regE === epoch && regN === n && AX === Tt.x0 && AY === Tt.y0) return false;
    const r = new Uint8Array(nc * nc), cm = columns();
    for (const ck of cm.keys()) {
      const ix = Math.floor(ck / 3e5) - 1e5, iy = ck - (ix + 1e5) * 3e5 - 1e5;
      for (const [dx, dy] of [[0, 0], [V, 0], [0, V], [V, V]]) {
        const a = fl((ix * V + dx - Tt.x0) / Tt.cell), b = fl((iy * V + dy - Tt.y0) / Tt.cell);
        if (a >= 0 && b >= 0 && a < nc && b < nc) r[b * nc + a] = 1;
      }
    }
    let cur = r;                                             // marge : 2 cases (8 voisins)
    for (let it = 0; it < MARGIN; it++) {
      const o2 = cur.slice();
      for (let b = 0; b < nc; b++) for (let a = 0; a < nc; a++) if (cur[b * nc + a])
        for (let v = -1; v <= 1; v++) for (let u = -1; u <= 1; u++) { const aa = a + u, bb = b + v; if (aa >= 0 && bb >= 0 && aa < nc && bb < nc) o2[bb * nc + aa] = 1; }
      cur = o2;
    }
    const NV = 2 * nc, cr = new Uint8Array(NV * NV);
    for (let q = 0; q < NV; q++) for (let p = 0; p < NV; p++) if (cur[(q >> 1) * nc + (p >> 1)]) cr[q * NV + p] = 1;
    for (let q = 0; q < NV; q++) for (let p = 0; p < NV; p++) if (cr[q * NV + p] === 1)
      for (let v = -1; v <= 1; v++) for (let u = -1; u <= 1; u++) { const pp = p + u, qq = q + v; if (pp >= 0 && qq >= 0 && pp < NV && qq < NV && !cr[qq * NV + pp]) cr[qq * NV + pp] = 2; }
    const changed = !region || region.length !== cur.length || cur.some((v, i) => v !== region[i]);
    // voxels dont la classe a change (zone, anneau, dehors) : leurs blocs deja la doivent etre remailles aussi, meme loin
    // de la retouche (sinon : cases du relief cachees sans pate dessus, trous ; 2026-11-24, capture utilisateur)
    regDirty = null;
    if (changed) {
      if (!colR || colR.length !== cr.length) regDirty = 'all';
      else {
        let p0 = Infinity, q0 = Infinity, p1 = -Infinity, q1 = -Infinity;
        for (let q = 0; q < NV; q++) for (let p = 0; p < NV; p++) if (cr[q * NV + p] !== colR[q * NV + p]) {
          if (p < p0) p0 = p; if (p > p1) p1 = p; if (q < q0) q0 = q; if (q > q1) q1 = q; }
        if (p0 <= p1) regDirty = { x0: Tt.x0 + (p0 - 1) * V, y0: Tt.y0 + (q0 - 1) * V, x1: Tt.x0 + (p1 + 2) * V, y1: Tt.y0 + (q1 + 2) * V };
      }
    }
    region = cur; colR = cr; regN = n; AX = Tt.x0; AY = Tt.y0; NCV = NV; regE = epoch;
    if (changed) regVersion++;
    return changed;
  }
  function inRegion(x, y) {
    computeRegion(); if (!region) return false;
    const Tt = T(), nc = regN - 1, a = fl((x - AX) / Tt.cell), b = fl((y - AY) / Tt.cell);
    return a >= 0 && b >= 0 && a < nc && b < nc && region[b * nc + a] === 1;
  }
  const colAt = (p, q) => p >= 0 && q >= 0 && p < NCV && q < NCV ? colR[q * NCV + p] : 0;

  function buildChunk(cx, cy, cz) {
    if (!colR) return null;
    const bx = cx * CH, by = cy * CH, bz = cz * CH;          // indices (voxels alignes sur le relief ; z : monde)
    let any = false;
    for (let j = -1; j < CH && !any; j++) for (let i = -1; i < CH; i++) if (colAt(bx + i, by + j)) { any = true; break; }
    if (!any) return null;
    // sol du relief par colonne (points -1..CH), puis champ aux points
    for (let j = 0; j < NP; j++) for (let i = 0; i < NP; i++) colH[j * NP + i] = groundAt(AX + (bx + i - 1) * V, AY + (by + j - 1) * V);
    let neg = false, pos = false;
    for (let k = 0, q = 0; k < NP; k++) {
      const z = (bz + k - 1) * V;
      for (let j = 0; j < NP; j++) for (let i = 0; i < NP; i++, q++) {
        const x = AX + (bx + i - 1) * V, y = AY + (by + j - 1) * V;
        const f = z - colH[j * NP + i] + dSample(x, y, z);
        pf[q] = f; if (f < 0) neg = true; else pos = true;
      }
    }
    if (!neg || !pos) return null;                          // pas de surface dans ce bloc
    const P = (i, j, k) => pf[((k + 1) * NP + (j + 1)) * NP + (i + 1)];   // i, j, k : -1..CH
    const NC = CH + 1, cid = (i, j, k) => ((k + 1) * NC + (j + 1)) * NC + (i + 1);
    cellV.fill(-1);
    let nv = 0;
    const cv = new Float32Array(8);
    for (let k = -1; k < CH; k++) for (let j = -1; j < CH; j++) for (let i = -1; i < CH; i++) {
      const cls = colAt(bx + i, by + j); if (!cls) continue;   // hors de la zone : le relief
      let m = 0;
      for (let c = 0; c < 8; c++) { cv[c] = P(i + CORNER[c][0], j + CORNER[c][1], k + CORNER[c][2]); if (cv[c] < 0) m |= 1 << c; }
      if (m === 0 || m === 255) continue;
      let sx = 0, sy = 0, sz = 0, cnt = 0;
      for (const [a, b] of EDGES) {
        if ((cv[a] < 0) === (cv[b] < 0)) continue;
        const t = cv[a] / (cv[a] - cv[b]);
        sx += CORNER[a][0] + (CORNER[b][0] - CORNER[a][0]) * t;
        sy += CORNER[a][1] + (CORNER[b][1] - CORNER[a][1]) * t;
        sz += CORNER[a][2] + (CORNER[b][2] - CORNER[a][2]) * t; cnt++;
      }
      const q = cid(i, j, k);
      cellV[q] = nv++;
      let px = AX + (bx + i + sx / cnt) * V, py = AY + (by + j + sy / cnt) * V, pz = (bz + k + sz / cnt) * V;
      if (cls === 2) {                                       // anneau : sur l'arete du relief, a sa hauteur
        const p0 = bx + i, q0 = by + j;
        const L = colAt(p0 - 1, q0) === 1, R = colAt(p0 + 1, q0) === 1, Dn = colAt(p0, q0 - 1) === 1, Up = colAt(p0, q0 + 1) === 1;
        if (R) px = AX + (p0 + 1) * V; else if (L) px = AX + p0 * V;
        if (Up) py = AY + (q0 + 1) * V; else if (Dn) py = AY + q0 * V;
        if (!(L || R || Dn || Up)) for (const [dj, di] of [[-1, -1], [-1, 1], [1, -1], [1, 1]]) if (colAt(p0 + di, q0 + dj) === 1) {
          px = AX + (p0 + (di > 0 ? 1 : 0)) * V; py = AY + (q0 + (dj > 0 ? 1 : 0)) * V; break;
        }
        pz = groundAt(px, py);
      }
      cellP[q * 3] = px; cellP[q * 3 + 1] = py; cellP[q * 3 + 2] = pz;
      let gx = (cv[1] - cv[0]) + (cv[3] - cv[2]) + (cv[5] - cv[4]) + (cv[7] - cv[6]);
      let gy = (cv[2] - cv[0]) + (cv[3] - cv[1]) + (cv[6] - cv[4]) + (cv[7] - cv[5]);
      let gz = (cv[4] - cv[0]) + (cv[5] - cv[1]) + (cv[6] - cv[2]) + (cv[7] - cv[3]);
      const gl = Math.hypot(gx, gy, gz) || 1;
      cellN[q * 3] = gx / gl; cellN[q * 3 + 1] = gy / gl; cellN[q * 3 + 2] = gz / gl;
    }
    if (!nv) return null;
    const tris = [];
    for (let k = 0; k < CH; k++) for (let j = 0; j < CH; j++) for (let i = 0; i < CH; i++) {
      const f0 = P(i, j, k);
      for (let ax = 0; ax < 3; ax++) {
        const f1 = ax === 0 ? P(i + 1, j, k) : ax === 1 ? P(i, j + 1, k) : P(i, j, k + 1);
        if ((f0 < 0) === (f1 < 0)) continue;
        let c0, c1, c2, c3, cols;
        if (ax === 0) { c0 = cid(i, j - 1, k - 1); c1 = cid(i, j, k - 1); c2 = cid(i, j, k); c3 = cid(i, j - 1, k); cols = [[i, j - 1], [i, j]]; }
        else if (ax === 1) { c0 = cid(i - 1, j, k - 1); c1 = cid(i - 1, j, k); c2 = cid(i, j, k); c3 = cid(i, j, k - 1); cols = [[i - 1, j], [i, j]]; }
        else { c0 = cid(i - 1, j - 1, k); c1 = cid(i, j - 1, k); c2 = cid(i, j, k); c3 = cid(i - 1, j, k); cols = [[i - 1, j - 1], [i, j - 1], [i, j], [i - 1, j]]; }
        if (cellV[c0] < 0 || cellV[c1] < 0 || cellV[c2] < 0 || cellV[c3] < 0) continue;
        if (!cols.some(([a, b]) => colAt(bx + a, by + b) === 1)) continue;   // tout dans l'anneau : plat, sur le bord
        if (f0 < 0) tris.push(c0, c1, c2, c0, c2, c3); else tris.push(c0, c2, c1, c0, c3, c2);
      }
    }
    if (!tris.length) return null;
    return { tris };
  }

  // ---- texture « triplanaire » : chaque pixel melange les projections de dessus et de cote selon l'orientation du sol
  // (pas de rupture d'un triangle a l'autre, parois et voutes sans texture etiree). Une copie par matiere du relief.
  const triMats = new Map();
  function triplanar(base) {
    if (!base?.map || !base.isMeshBasicMaterial) return base;   // couleur unie : telle quelle
    let m = triMats.get(base);
    if (m) return m;
    m = base.clone(); m.userData.clayOf = base;
    // texture toujours celle de la matiere du relief (fondus : image melangee posee plus tard)
    Object.defineProperty(m, 'map', { get: () => base.map, set() {}, configurable: true });
    const rep = { value: o.repeat() };
    m.onBeforeCompile = sh => {
      sh.uniforms.uClayRep = rep;
      sh.vertexShader = sh.vertexShader.replace('#include <common>', '#include <common>\nvarying vec3 vClayP;\nvarying vec3 vClayN;')
        .replace('#include <begin_vertex>', '#include <begin_vertex>\nvClayP = (modelMatrix * vec4(position, 1.0)).xyz;\nvClayN = normalize(mat3(modelMatrix) * normal);');
      sh.fragmentShader = sh.fragmentShader.replace('#include <common>', '#include <common>\nvarying vec3 vClayP;\nvarying vec3 vClayN;\nuniform float uClayRep;')
        .replace('#include <map_fragment>', `
          vec3 cw = pow(abs(normalize(vClayN)), vec3(4.0)); cw /= (cw.x + cw.y + cw.z);
          vec4 tx = texture2D(map, vClayP.yz / uClayRep), ty = texture2D(map, vClayP.xz / uClayRep), tz = texture2D(map, vClayP.xy / uClayRep);
          diffuseColor *= tx * cw.x + ty * cw.y + tz * cw.z;`);
    };
    m.customProgramCacheKey = () => 'clay-triplanar';
    triMats.set(base, m);
    return m;
  }

  // ---- matieres et triangles -> geometrie (sommets partages, triangles ranges par matiere) --------------------------
  function geometryOf(r) {
    const faces = o.faces(), Tt = T(), rep = o.repeat();
    const byMat = new Map();                                // code de matiere -> liste de triangles (indices de cases)
    for (let t = 0; t < r.tris.length; t += 3) {
      const a = r.tris[t], b = r.tris[t + 1], c = r.tris[t + 2];
      const x = (cellP[a * 3] + cellP[b * 3] + cellP[c * 3]) / 3, y = (cellP[a * 3 + 1] + cellP[b * 3 + 1] + cellP[c * 3 + 1]) / 3;
      let m = 0;
      if (faces?.best && Tt) {
        const n = Tt.n, i = Math.max(0, Math.min(n - 2, fl((x - Tt.x0) / Tt.cell))), j = Math.max(0, Math.min(n - 2, fl((y - Tt.y0) / Tt.cell)));
        m = faces.best[j * (n - 1) + i];
      }
      (byMat.get(m) || byMat.set(m, []).get(m)).push(a, b, c);
    }
    // sommets : les cases utilisees, renumerotees
    const remap = new Map(), ids = [];
    for (const q of r.tris) if (!remap.has(q)) { remap.set(q, ids.length); ids.push(q); }
    const nvx = ids.length, pos = new Float32Array(nvx * 3), nrm = new Float32Array(nvx * 3), uv = new Float32Array(nvx * 2), col = new Float32Array(nvx * 3);
    ids.forEach((q, v) => {
      const x = cellP[q * 3], y = cellP[q * 3 + 1], z = cellP[q * 3 + 2], nx = cellN[q * 3], ny = cellN[q * 3 + 1], nz = cellN[q * 3 + 2];
      pos[v * 3] = x; pos[v * 3 + 1] = y; pos[v * 3 + 2] = z - 2;
      nrm[v * 3] = nx; nrm[v * 3 + 1] = ny; nrm[v * 3 + 2] = nz;
      uv[v * 2] = x / rep; uv[v * 2 + 1] = y / rep;          // matieres sans projection triplanaire : dessus
      const d = (nx * Lx + ny * Ly + nz * Lz) / Ln;          // soleil en biais (meme ombrage que le relief), voutes un peu plus sombres
      col[v * 3] = col[v * 3 + 1] = col[v * 3 + 2] = Math.min(1, 0.5 + 0.5 * (d > 0 ? d : 0) - (nz < -0.3 ? 0.08 : 0));
    });
    const index = new Uint32Array(r.tris.length), g = new THREE.BufferGeometry(), mats = [];
    let start = 0;
    for (const [m, list] of byMat) {
      for (let t = 0; t < list.length; t++) index[start + t] = remap.get(list[t]);
      g.addGroup(start, list.length, mats.length);
      mats.push(triplanar(o.material(m)));
      start += list.length;
    }
    g.setIndex(new THREE.BufferAttribute(index, 1));
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('normal', new THREE.BufferAttribute(nrm, 3));
    g.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
    g.setAttribute('color', new THREE.BufferAttribute(col, 3));
    g.computeBoundingBox(); g.computeBoundingSphere();
    return { g, mats };
  }
  function remesh(cx, cy, cz) {
    const k = key(cx, cy, cz), old = meshes.get(k);
    const r = buildChunk(cx, cy, cz);
    if (!r) { if (old) { group.remove(old); old.geometry.dispose(); meshes.delete(k); } return; }
    const { g, mats } = geometryOf(r);
    if (old) { old.geometry.dispose(); old.geometry = g; old.material = mats; return; }
    const m = new THREE.Mesh(g, mats); m.userData.clay = k; m.matrixAutoUpdate = false;
    meshes.set(k, m); group.add(m);
  }

  // ---- blocs a mailler : ceux de la zone de pate (colonnes de blocs alignees sur le relief) ----------------------------
  function chunkCols(box) {                                 // colonnes de blocs (cx, cy) de la zone, dans la boite (monde)
    if (!colR) return [];
    const out = [], nb = Math.ceil(NCV / CH);
    for (let cy = 0; cy < nb; cy++) for (let cx = 0; cx < nb; cx++) {
      const x0 = AX + (cx * CH - 1) * V, y0 = AY + (cy * CH - 1) * V, x1 = AX + (cx * CH + CH + 1) * V, y1 = AY + (cy * CH + CH + 1) * V;
      if (box && (x1 < box.x0 || x0 > box.x1 || y1 < box.y0 || y0 > box.y1)) continue;
      let any = false;
      for (let j = -1; j <= CH && !any; j++) for (let i = -1; i <= CH; i++) if (colAt(cx * CH + i, cy * CH + j)) { any = true; break; }
      if (any) out.push([cx, cy]);
    }
    return out;
  }
  function dropColumn(cx, cy) {
    for (const [k, m] of meshes) { const [a, b] = unkey(k); if (a === cx && b === cy) { group.remove(m); m.geometry.dispose(); meshes.delete(k); } }
  }
  function refreshColumn(cx, cy) {
    let lo = Infinity, hi = -Infinity;                      // sol du relief sur la colonne (bords compris)
    for (let j = -1; j <= CH + 1; j += 2) for (let i = -1; i <= CH + 1; i += 2) {
      const h = groundAt(AX + (cx * CH + i) * V, AY + (cy * CH + j) * V); if (h < lo) lo = h; if (h > hi) hi = h;
    }
    const want = new Set();
    for (let cz = fl((lo - 2 * V) / CW); cz <= fl((hi + 2 * V) / CW); cz++) want.add(cz);
    const x0 = AX + (cx * CH - 1) * V, x1 = AX + (cx * CH + CH + 1) * V, y0 = AY + (cy * CH - 1) * V, y1 = AY + (cy * CH + CH + 1) * V;
    for (const k of D.keys()) {                             // blocs retouches qui recouvrent la colonne : leur hauteur aussi
      const [a, b, c] = unkey(k);
      if ((a + 1) * CW >= x0 && a * CW <= x1 && (b + 1) * CW >= y0 && b * CW <= y1) for (let z = c - 1; z <= c + 1; z++) want.add(z);
    }
    for (const [k, m] of meshes) {
      const [a, b, c] = unkey(k);
      if (a === cx && b === cy && !want.has(c)) { group.remove(m); m.geometry.dispose(); meshes.delete(k); }
    }
    for (const cz of want) remesh(cx, cy, cz);
  }
  // box : {x0, y0, x1, y1} monde (zone modifiee), sans : tout. Zone de pate recalculee si les retouches ont change :
  // colonnes entrees ou sorties remaillees, et le relief prevenu (ses cases cachees changent : o.onRegion)
  // ---- route degagee : jamais de pate de la chaussee jusqu'a 15 m au-dessus (2026-11-24, demande utilisateur : « la
  // pate ne doit pas pouvoir se trouver a moins de 15 m au-dessus de la route »). o.roadMap() -> { ver, map : colonne de
  // la grille (ckey) -> hauteurs de chaussee (une par passage) }. Champ porte a au moins (z - route) dans la tranche :
  // surface juste a la hauteur de la chaussee, air au-dessus, la matiere sous la route ne bouge pas
  const ROAD_CLEAR = 15 * IN;
  let roadVer = null;
  function clampRoad(box) {
    const rm = o.roadMap?.(); if (!rm || !rm.map.size) return false;
    let changed = false;
    const doCol = (ck, zs) => {
      const ix = Math.floor(ck / 3e5) - 1e5, iy = ck - (ix + 1e5) * 3e5 - 1e5;
      if (box && (ix * V < box.x0 - V || ix * V > box.x1 + V || iy * V < box.y0 - V || iy * V > box.y1 + V)) return;
      const g = groundAt(ix * V, iy * V);
      for (const zr of zs) for (let iz = fl(zr / V); iz <= Math.ceil((zr + ROAD_CLEAR) / V); iz++) {
        const z = iz * V, need = (z - zr) - (z - g), cx = fl(ix / CH), cy = fl(iy / CH), cz = fl(iz / CH), kk = key(cx, cy, cz);
        let arr = D.get(kk); const q = ((iz - cz * CH) * CH + (iy - cy * CH)) * CH + (ix - cx * CH);
        const cur = arr ? arr[q] : 0;
        if (cur >= need - 0.5) continue;
        if (!arr) { arr = new Float32Array(CH ** 3); setD(kk, arr); }
        arr[q] = need; changed = true;
      }
    };
    if (box) {                                              // colonnes de la boite seulement
      for (let iy = fl(box.y0 / V) - 1; iy <= Math.ceil(box.y1 / V) + 1; iy++) for (let ix = fl(box.x0 / V) - 1; ix <= Math.ceil(box.x1 / V) + 1; ix++) {
        const ck = ckey(ix, iy), zs = rm.map.get(ck); if (zs) doCol(ck, zs);
      }
    } else for (const [ck, zs] of rm.map) doCol(ck, zs);
    if (changed) { version++; epoch++; }
    return changed;
  }
  function refresh(box) {
    const rv = o.roadMap?.()?.ver;                          // route modifiee : toute la pate sur la nouvelle route degagee
    if (rv !== roadVer) { roadVer = rv; if (D.size && clampRoad(null)) box = null; }
    const before = new Set(chunkCols(null).map(([a, b]) => a + ',' + b));
    const changed = computeRegion();
    const now = chunkCols(null), nowSet = new Set(now.map(([a, b]) => a + ',' + b));
    if (!box) { for (const [, m] of meshes) { group.remove(m); m.geometry.dispose(); } meshes.clear(); }
    for (const c of before) if (!nowSet.has(c)) { const [a, b] = c.split(',').map(Number); dropColumn(a, b); }
    const pad = box && { x0: box.x0 - 2 * V, y0: box.y0 - 2 * V, x1: box.x1 + 2 * V, y1: box.y1 + 2 * V };
    const todo = new Set((box ? chunkCols(pad) : now).map(([a, b]) => a + ',' + b));
    if (changed) for (const c of nowSet) if (!before.has(c)) todo.add(c);
    if (changed && regDirty) for (const [a, b] of regDirty === 'all' ? now : chunkCols(regDirty)) todo.add(a + ',' + b);
    for (const c of todo) { const [a, b] = c.split(',').map(Number); refreshColumn(a, b); }
    if (changed) o.onRegion?.();
  }

  // ---- Etirer : comme une pate qu'on tire. Au debut du geste, le morceau attrape (la matiere dans une boule de rayon R
  // autour du point) est pris tel quel ; il suit la souris et laisse derriere lui une langue de matiere continue (union
  // douce avec ce qui est deja la). Le morceau est toujours relu dans l'etat du DEBUT du geste : rien ne s'use en route,
  // meme sur un long trajet. Au contact d'une autre matiere, le champ ne fait qu'un : les deux parties fusionnent.
  let grab = null;                                          // { a0, R, D0 (retouches au debut), t (deplacement deja fait) }
  function beginStretch(a0, R) {
    grab = { a0: { x: a0.x, y: a0.y, z: a0.z }, R, D0: new Map([...D].map(([k, a]) => [k, a.slice()])), t: { x: 0, y: 0, z: 0 } };
  }
  function d0At(ix, iy, iz) {                               // retouches telles qu'au debut du geste
    const a = grab.D0.get(key(fl(ix / CH), fl(iy / CH), fl(iz / CH)));
    if (!a) return 0;
    return a[((iz - fl(iz / CH) * CH) * CH + (iy - fl(iy / CH) * CH)) * CH + (ix - fl(ix / CH) * CH)];
  }
  function field0(x, y, z) {                                // champ au debut du geste
    const gx = x / V, gy = y / V, gz = z / V, ix = fl(gx), iy = fl(gy), iz = fl(gz), u = gx - ix, v = gy - iy, w = gz - iz;
    let s = 0;
    for (let c = 0; c < 8; c++) {
      const a = c & 1, b = (c >> 1) & 1, e = c >> 2, val = d0At(ix + a, iy + b, iz + e);
      if (val) s += val * (a ? u : 1 - u) * (b ? v : 1 - v) * (e ? w : 1 - w);
    }
    return z - groundAt(x, y) + s;
  }
  // morceau attrape (dans l'etat du debut), deplace de t : matiere du debut ET dans la boule ; bord de boule adouci
  const blob = (x, y, z, t) => {
    const px = x - t.x, py = y - t.y, pz = z - t.z, g = grab;
    return Math.max(field0(px, py, pz), Math.hypot(px - g.a0.x, py - g.a0.y, pz - g.a0.z) - g.R);
  };
  const smin = (a, b, k) => { const h = Math.max(k - Math.abs(a - b), 0) / k; return Math.min(a, b) - h * h * k / 4; };
  // t : deplacement total depuis le point attrape (monde) -> boite modifiee
  function dragStretch(t) {
    if (!grab) return null;
    const p = grab.t, L = Math.hypot(t.x - p.x, t.y - p.y, t.z - p.z); if (L < 1) return null;
    const n = Math.max(1, Math.ceil(L / (V / 2))), ts = [];
    for (let k = 1; k <= n; k++) ts.push({ x: p.x + (t.x - p.x) * k / n, y: p.y + (t.y - p.y) * k / n, z: p.z + (t.z - p.z) * k / n });
    const a = grab.a0, ext = grab.R + 2 * V;
    const xs = ts.map(q => a.x + q.x).concat(a.x + p.x), ys = ts.map(q => a.y + q.y).concat(a.y + p.y), zs = ts.map(q => a.z + q.z).concat(a.z + p.z);
    const ix0 = fl((Math.min(...xs) - ext) / V), ix1 = Math.ceil((Math.max(...xs) + ext) / V);
    const iy0 = fl((Math.min(...ys) - ext) / V), iy1 = Math.ceil((Math.max(...ys) + ext) / V);
    const iz0 = fl((Math.min(...zs) - ext) / V), iz1 = Math.ceil((Math.max(...zs) + ext) / V);
    const out = [], K = 1.5 * V;                             // union douce sur ~6 m : raccord arrondi, comme de la pate
    for (let iz = iz0; iz <= iz1; iz++) for (let iy = iy0; iy <= iy1; iy++) for (let ix = ix0; ix <= ix1; ix++) {
      const x = ix * V, y = iy * V, z = iz * V;
      let b = Infinity;
      for (const q of ts) {                                 // plus proche passage du morceau le long du trajet
        const dx = x - a.x - q.x, dy = y - a.y - q.y, dz = z - a.z - q.z;
        if (dx * dx + dy * dy + dz * dz > (grab.R + K) ** 2) continue;
        const v = blob(x, y, z, q); if (v < b) b = v;
      }
      if (b === Infinity || b > K) continue;
      const cur = field(x, y, z);
      if (b >= cur + K) continue;
      out.push(ix, iy, iz, smin(cur, b, K) - (z - groundAt(x, y)));
    }
    for (let k = 0; k < out.length; k += 4) {               // ecrit apres lecture
      const ix = out[k], iy = out[k + 1], iz = out[k + 2], val = out[k + 3];
      const cx = fl(ix / CH), cy = fl(iy / CH), cz = fl(iz / CH), kk = key(cx, cy, cz);
      let arr = D.get(kk);
      if (!arr) { if (Math.abs(val) < 1) continue; arr = new Float32Array(CH ** 3); setD(kk, arr); }
      arr[((iz - cz * CH) * CH + (iy - cy * CH)) * CH + (ix - cx * CH)] = val;
    }
    grab.t = { x: t.x, y: t.y, z: t.z };
    if (!out.length) return null;
    version++; epoch++;                                    // caches (zone de pate, colonnes) a recalculer
    const bx = { x0: (ix0 - 1) * V, y0: (iy0 - 1) * V, x1: (ix1 + 1) * V, y1: (iy1 + 1) * V };
    clampRoad(bx);
    refresh(bx);
    return bx;
  }
  function endStretch() { grab = null; }

  // ---- Monter / Creuser / Aplanir / Lisser EN VOLUME (2026-11-24 : sans effet sur la partie etiree, ils ne touchaient que
  // le relief 2D). La matiere avance ou recule le long de sa normale, dans une boule de rayon R autour du point touche.
  // tool : 'raise' | 'lower' | 'smooth' | 'flatten' ; amt : epaisseur (pouces, raise / lower) ou force 0..1 (smooth /
  // flatten) ; plane : {p, n} plan d'Aplanir (pris au debut du trait). -> boite modifiee
  function normalAt(x, y, z) {                              // normale sortante d'apres le champ
    const e = V / 2, gx = field(x + e, y, z) - field(x - e, y, z), gy = field(x, y + e, z) - field(x, y - e, z), gz = field(x, y, z + e) - field(x, y, z - e);
    const l = Math.hypot(gx, gy, gz) || 1;
    return { x: gx / l, y: gy / l, z: gz / l };
  }
  // point touche sur de la matiere en volume (retouchee, ou loin du sol du relief : arche, voute, paroi etiree) ?
  const isVolume = (x, y, z) => Math.abs(dSample(x, y, z)) > V / 2 || Math.abs(z - groundAt(x, y)) > V;
  function sculpt(tool, p, R, amt, plane) {
    const ix0 = fl((p.x - R) / V), ix1 = Math.ceil((p.x + R) / V), iy0 = fl((p.y - R) / V), iy1 = Math.ceil((p.y + R) / V);
    const iz0 = fl((p.z - R) / V), iz1 = Math.ceil((p.z + R) / V);
    const out = [], band = 3 * V;
    const fAt = (ix, iy, iz) => iz * V - groundAt(ix * V, iy * V) + dAt(ix, iy, iz);
    for (let iz = iz0; iz <= iz1; iz++) for (let iy = iy0; iy <= iy1; iy++) for (let ix = ix0; ix <= ix1; ix++) {
      const x = ix * V, y = iy * V, z = iz * V, r = Math.hypot(x - p.x, y - p.y, z - p.z) / R;
      if (r >= 1) continue;
      const w = (1 - r * r) ** 2, f = fAt(ix, iy, iz);
      if (Math.abs(f) > band + amt) continue;               // loin de la surface : rien a faire (la cave reste vide)
      let nf = f;
      if (tool === 'raise') nf = f - amt * w;
      else if (tool === 'lower') nf = f + amt * w;
      else if (tool === 'smooth') {
        const avg = (fAt(ix - 1, iy, iz) + fAt(ix + 1, iy, iz) + fAt(ix, iy - 1, iz) + fAt(ix, iy + 1, iz) + fAt(ix, iy, iz - 1) + fAt(ix, iy, iz + 1)) / 6;
        nf = f + (avg - f) * Math.min(1, amt * w);
      } else if (tool === 'flatten' && plane) {
        const tgt = (x - plane.p.x) * plane.n.x + (y - plane.p.y) * plane.n.y + (z - plane.p.z) * plane.n.z;
        nf = f + (tgt - f) * Math.min(1, amt * w);
      }
      if (nf !== f) out.push(ix, iy, iz, nf - (z - groundAt(x, y)));
    }
    if (!out.length) return null;
    for (let k = 0; k < out.length; k += 4) {
      const ix = out[k], iy = out[k + 1], iz = out[k + 2], val = out[k + 3];
      const cx = fl(ix / CH), cy = fl(iy / CH), cz = fl(iz / CH), kk = key(cx, cy, cz);
      let arr = D.get(kk);
      if (!arr) { if (Math.abs(val) < 1) continue; arr = new Float32Array(CH ** 3); setD(kk, arr); }
      arr[((iz - cz * CH) * CH + (iy - cy * CH)) * CH + (ix - cx * CH)] = val;
    }
    version++; epoch++;                                    // caches (zone de pate, colonnes) a recalculer
    const bx = { x0: (ix0 - 1) * V, y0: (iy0 - 1) * V, x1: (ix1 + 1) * V, y1: (iy1 + 1) * V };
    clampRoad(bx);
    refresh(bx);
    return bx;
  }

  // ---- tube de matiere (pont de terre) ou tube vide (tunnel, cave) le long d'une ligne : piste aleatoire ----------------
  // pts : [{x, y, z, r}] (rayon par point, interpole) ; carve : creuse au lieu d'ajouter ; raccord doux sur K. -> boite
  function tube(pts, carve = false, K = 1.5 * V) {
    let x0 = Infinity, y0 = Infinity, z0 = Infinity, x1 = -Infinity, y1 = -Infinity, z1 = -Infinity;
    for (const p of pts) { x0 = Math.min(x0, p.x - p.r); y0 = Math.min(y0, p.y - p.r); z0 = Math.min(z0, p.z - p.r);
                           x1 = Math.max(x1, p.x + p.r); y1 = Math.max(y1, p.y + p.r); z1 = Math.max(z1, p.z + p.r); }
    const ix0 = fl((x0 - K) / V), ix1 = Math.ceil((x1 + K) / V), iy0 = fl((y0 - K) / V), iy1 = Math.ceil((y1 + K) / V);
    const iz0 = fl((z0 - K) / V), iz1 = Math.ceil((z1 + K) / V);
    const out = [];
    // distance signee au tube, segment par segment sur sa seule boite (2026-11-24, vitesse : avant, chaque point de la
    // boite entiere etait compare a tous les segments)
    const nx = ix1 - ix0 + 1, ny = iy1 - iy0 + 1, nz = iz1 - iz0 + 1, dist = new Float32Array(nx * ny * nz).fill(Infinity);
    for (let k = 1; k < pts.length; k++) {
      const a = pts[k - 1], b = pts[k], ux = b.x - a.x, uy = b.y - a.y, uz = b.z - a.z, L2 = ux * ux + uy * uy + uz * uz || 1;
      const rr = Math.max(a.r, b.r) + K;
      const jx0 = Math.max(ix0, fl((Math.min(a.x, b.x) - rr) / V)), jx1 = Math.min(ix1, Math.ceil((Math.max(a.x, b.x) + rr) / V));
      const jy0 = Math.max(iy0, fl((Math.min(a.y, b.y) - rr) / V)), jy1 = Math.min(iy1, Math.ceil((Math.max(a.y, b.y) + rr) / V));
      const jz0 = Math.max(iz0, fl((Math.min(a.z, b.z) - rr) / V)), jz1 = Math.min(iz1, Math.ceil((Math.max(a.z, b.z) + rr) / V));
      for (let iz = jz0; iz <= jz1; iz++) for (let iy = jy0; iy <= jy1; iy++) for (let ix = jx0; ix <= jx1; ix++) {
        const x = ix * V, y = iy * V, z = iz * V;
        const t = Math.max(0, Math.min(1, ((x - a.x) * ux + (y - a.y) * uy + (z - a.z) * uz) / L2));
        const v = Math.hypot(x - a.x - ux * t, y - a.y - uy * t, z - a.z - uz * t) - (a.r + (b.r - a.r) * t);
        const q = ((iz - iz0) * ny + (iy - iy0)) * nx + (ix - ix0);
        if (v < dist[q]) dist[q] = v;
      }
    }
    for (let iz = iz0; iz <= iz1; iz++) for (let iy = iy0; iy <= iy1; iy++) for (let ix = ix0; ix <= ix1; ix++) {
      const d = dist[((iz - iz0) * ny + (iy - iy0)) * nx + (ix - ix0)];
      if (d > K) continue;
      const x = ix * V, y = iy * V, z = iz * V;
      const cur = field(x, y, z);
      const nf = carve ? -smin(-cur, d, K) : smin(cur, d, K);
      if (Math.abs(nf - cur) < 1) continue;
      out.push(ix, iy, iz, nf - (z - groundAt(x, y)));
    }
    if (!out.length) return null;
    for (let k = 0; k < out.length; k += 4) {
      const ix = out[k], iy = out[k + 1], iz = out[k + 2], val = out[k + 3];
      const cx = fl(ix / CH), cy = fl(iy / CH), cz = fl(iz / CH), kk = key(cx, cy, cz);
      let arr = D.get(kk);
      if (!arr) { arr = new Float32Array(CH ** 3); setD(kk, arr); }
      arr[((iz - cz * CH) * CH + (iy - cy * CH)) * CH + (ix - cx * CH)] = val;
    }
    version++; epoch++;                                    // caches (zone de pate, colonnes) a recalculer
    const bx = { x0: (ix0 - 1) * V, y0: (iy0 - 1) * V, x1: (ix1 + 1) * V, y1: (iy1 + 1) * V };
    clampRoad(bx);
    refresh(bx);
    return bx;
  }

  // ---- remblai : la matiere remonte jusqu'a top(x, y) (terrain naturel) le long d'un trace 2D (tunnel souterrain : le
  // toit de la tranchee de la route est remis). path : [{x, y}] ; half : demi-largeur ; ends : fondu aux deux bouts
  // (entrees du tunnel). -> boite
  function fillTo(path, half, top, ends) {
    const segs = [], cum = [0];
    for (let k = 1; k < path.length; k++) cum.push(cum[k - 1] + Math.hypot(path[k].x - path[k - 1].x, path[k].y - path[k - 1].y));
    const L = cum[cum.length - 1], K = 2 * V;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const p of path) { x0 = Math.min(x0, p.x); y0 = Math.min(y0, p.y); x1 = Math.max(x1, p.x); y1 = Math.max(y1, p.y); }
    const ix0 = fl((x0 - half) / V), ix1 = Math.ceil((x1 + half) / V), iy0 = fl((y0 - half) / V), iy1 = Math.ceil((y1 + half) / V);
    const ss = (a, b, x) => { const t = Math.max(0, Math.min(1, (x - a) / (b - a))); return t * t * (3 - 2 * t); };
    const out = [];
    let iz0 = Infinity, iz1 = -Infinity;
    // distance au trace et abscisse du point le plus proche, segment par segment sur sa seule boite (vitesse)
    const nx = ix1 - ix0 + 1, ny = iy1 - iy0 + 1, dd = new Float32Array(nx * ny).fill(Infinity), sv = new Float32Array(nx * ny);
    for (let k = 1; k < path.length; k++) {
      const a = path[k - 1], b = path[k], ux = b.x - a.x, uy = b.y - a.y, l2 = ux * ux + uy * uy || 1;
      const jx0 = Math.max(ix0, fl((Math.min(a.x, b.x) - half) / V)), jx1 = Math.min(ix1, Math.ceil((Math.max(a.x, b.x) + half) / V));
      const jy0 = Math.max(iy0, fl((Math.min(a.y, b.y) - half) / V)), jy1 = Math.min(iy1, Math.ceil((Math.max(a.y, b.y) + half) / V));
      for (let iy = jy0; iy <= jy1; iy++) for (let ix = jx0; ix <= jx1; ix++) {
        const x = ix * V, y = iy * V, t = Math.max(0, Math.min(1, ((x - a.x) * ux + (y - a.y) * uy) / l2)), e = Math.hypot(x - a.x - ux * t, y - a.y - uy * t);
        const q = (iy - iy0) * nx + (ix - ix0);
        if (e < dd[q]) { dd[q] = e; sv[q] = cum[k - 1] + (cum[k] - cum[k - 1]) * t; }
      }
    }
    for (let iy = iy0; iy <= iy1; iy++) for (let ix = ix0; ix <= ix1; ix++) {
      const x = ix * V, y = iy * V, q = (iy - iy0) * nx + (ix - ix0), d = dd[q], s = sv[q];
      if (d === Infinity) continue;
      const w = ss(half, half - 3 * K, d) * ss(0, ends, s) * ss(L, L - ends, s);
      if (w <= 0) continue;
      const g = groundAt(x, y), zt = g + (top(x, y) - g) * w;
      if (zt <= g + 0.1 * IN) continue;
      const a0 = fl((g - V) / V), a1 = Math.ceil((zt + V) / V);
      for (let iz = a0; iz <= a1; iz++) {
        const z = iz * V, cur = field(x, y, z), nf = Math.min(cur, z - zt);
        if (nf < cur - 1) { out.push(ix, iy, iz, nf - (z - g)); iz0 = Math.min(iz0, iz); iz1 = Math.max(iz1, iz); }
      }
    }
    if (!out.length) return null;
    for (let k = 0; k < out.length; k += 4) {
      const ix = out[k], iy = out[k + 1], iz = out[k + 2], val = out[k + 3];
      const cx = fl(ix / CH), cy = fl(iy / CH), cz = fl(iz / CH), kk = key(cx, cy, cz);
      let arr = D.get(kk);
      if (!arr) { arr = new Float32Array(CH ** 3); setD(kk, arr); }
      arr[((iz - cz * CH) * CH + (iy - cy * CH)) * CH + (ix - cx * CH)] = val;
    }
    version++; epoch++;                                    // caches (zone de pate, colonnes) a recalculer
    const bx = { x0: (ix0 - 1) * V, y0: (iy0 - 1) * V, x1: (ix1 + 1) * V, y1: (iy1 + 1) * V };
    clampRoad(bx);
    refresh(bx);
    return bx;
  }

  // ---- sol pour le decor (2026-11-24 : les objets ne se posaient que sur le relief 2D) ---------------------------------
  // colonnes de la grille (4 m) vraiment retouchees (au moins 10 cm) : plus forte retouche et haut de la matiere retouchee
  const D_MIN = 4;                                          // pouces
  const ckey = (ix, iy) => (ix + 1e5) * 3e5 + (iy + 1e5);
  let colE = -1, colMap = new Map();
  // ---- matiere detachee : apres un creusement, un morceau de pate qui ne tient plus a rien (ni au sol, ni au relief
  // autour) est retire (2026-11-24, demande utilisateur : « supprime automatiquement tout ce qui n'est plus relie a la
  // base »). Parcours des points pleins de la grille (26 voisins : un contact en biais compte comme relie) depuis le
  // dessous du sol des colonnes retouchees et depuis les colonnes non retouchees autour. -> boite modifiee ou null
  function dropFloating() {
    if (!D.size) return null;
    const cm = columns(); if (!cm.size) return null;
    const cols = new Map();
    const dec = ck => { const ix = Math.floor(ck / 3e5) - 1e5; return [ix, ck - (ix + 1e5) * 3e5 - 1e5]; };
    const add = (ix, iy, edited, top) => {
      const k = ckey(ix, iy); let c = cols.get(k);
      if (!c) { const g = groundAt(ix * V, iy * V); c = { ix, iy, g, z0: fl(g / V) - 2, z1: Math.ceil(g / V) + 2, edited: false }; cols.set(k, c); }
      if (edited) { c.edited = true; c.z1 = Math.max(c.z1, Math.ceil(top / V) + 2); }
      return c;
    };
    for (const [ck, e] of cm) { const [ix, iy] = dec(ck); add(ix, iy, true, e.top); }
    for (const c of [...cols.values()]) for (let v = -1; v <= 1; v++) for (let u = -1; u <= 1; u++) if (u || v) add(c.ix + u, c.iy + v, false, 0);
    let total = 0; for (const c of cols.values()) { c.o = total; total += c.z1 - c.z0 + 1; }
    const st = new Uint8Array(total), q = new Int32Array(total);
    const list = [...cols.values()];
    let qn = 0;
    for (let ci = 0; ci < list.length; ci++) {
      const c = list[ci]; c.i = ci;
      for (let iz = c.z0; iz <= c.z1; iz++) {
        if (iz * V - c.g + dAt(c.ix, c.iy, iz) >= 0) continue;     // air
        const id = c.o + iz - c.z0; st[id] = 1;
        if (!c.edited || iz === c.z0) { st[id] = 2; q[qn++] = id; }  // relie a la base : sous le sol, ou relief non retouche
      }
    }
    const colOf = new Int32Array(total); for (const c of list) colOf.fill(c.i, c.o, c.o + c.z1 - c.z0 + 1);
    for (let h = 0; h < qn; h++) {
      const id = q[h], c = list[colOf[id]], iz = c.z0 + id - c.o;
      for (let v = -1; v <= 1; v++) for (let u = -1; u <= 1; u++) {
        const n = (u || v) ? cols.get(ckey(c.ix + u, c.iy + v)) : c; if (!n) continue;
        for (let w = -1; w <= 1; w++) {
          const z = iz + w; if (z < n.z0 || z > n.z1) continue;
          const j = n.o + z - n.z0; if (st[j] === 1) { st[j] = 2; q[qn++] = j; }
        }
      }
    }
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity, cnt = 0;
    for (const c of list) for (let iz = c.z0; iz <= c.z1; iz++) {
      if (st[c.o + iz - c.z0] !== 1) continue;
      const val = V / 4 - (iz * V - c.g);                   // devient de l'air (juste au-dessus de la surface)
      const cx = fl(c.ix / CH), cy = fl(c.iy / CH), cz = fl(iz / CH), kk = key(cx, cy, cz);
      let arr = D.get(kk); if (!arr) { arr = new Float32Array(CH ** 3); setD(kk, arr); }
      arr[((iz - cz * CH) * CH + (c.iy - cy * CH)) * CH + (c.ix - cx * CH)] = val;
      cnt++; x0 = Math.min(x0, c.ix * V); x1 = Math.max(x1, c.ix * V); y0 = Math.min(y0, c.iy * V); y1 = Math.max(y1, c.iy * V);
    }
    if (!cnt) return null;
    version++; epoch++;
    const bx = { x0: x0 - V, y0: y0 - V, x1: x1 + V, y1: y1 + V, removed: cnt };
    clampRoad(bx);
    refresh(bx);
    return bx;
  }

  function columns() {
    if (colE === epoch) return colMap;
    colMap = new Map();
    for (const [k, a] of D) {
      const [cx, cy, cz] = unkey(k);
      for (let ly = 0; ly < CH; ly++) for (let lx = 0; lx < CH; lx++) {
        let m = 0, top = -Infinity;
        for (let lz = 0; lz < CH; lz++) { const v = Math.abs(a[(lz * CH + ly) * CH + lx]); if (v > m) m = v; if (v >= D_MIN) top = (cz * CH + lz) * V; }
        if (m < D_MIN) continue;
        const ck = ckey(cx * CH + lx, cy * CH + ly), e = colMap.get(ck);
        if (!e) colMap.set(ck, { m, top }); else { if (m > e.m) e.m = m; if (top > e.top) e.top = top; }
      }
    }
    colE = epoch;
    return colMap;
  }
  function columnEdited(x, y) {                             // retouche a moins d'une maille (4 m) de (x, y) ?
    if (!D.size) return false;
    const cm = columns(), gx = fl(x / V), gy = fl(y / V);
    for (let j = gy - 1; j <= gy + 2; j++) for (let i = gx - 1; i <= gx + 2; i++) if (cm.has(ckey(i, j))) return true;
    return false;
  }
  // surface (air au-dessus, matiere dessous) a la verticale de (x, y), la plus proche de la hauteur hint (pouces) ;
  // hint absent : la plus haute. -> z, ou null
  function surfaceZ(x, y, hint) {
    const step = V / 2, refine = (za, zb) => { for (let k = 0; k < 8; k++) { const m = (za + zb) / 2; if (field(x, y, m) > 0) za = m; else zb = m; } return (za + zb) / 2; };
    let top = groundAt(x, y) + 2 * V;
    const cm = columns(), gx = fl(x / V), gy = fl(y / V);
    for (let j = gy; j <= gy + 1; j++) for (let i = gx; i <= gx + 1; i++) { const e = cm.get(ckey(i, j)); if (e && e.top + 2 * V > top) top = e.top + 2 * V; }
    const hi = hint == null ? top : Math.min(top, hint + 6 * IN), lo = (hint == null ? groundAt(x, y) : hint) - 40 * IN;
    let za = hi, fa = field(x, y, za);
    for (let z = hi - step; z >= lo; z -= step) {           // en descendant : premier passage de l'air a la matiere
      const f = field(x, y, z);
      if (fa > 0 && f <= 0) return refine(za, z);
      za = z; fa = f;
    }
    if (hint != null && field(x, y, hint) < 0)              // dans la matiere : surface juste au-dessus
      for (let z = hint; z <= hint + 40 * IN; z += step) if (field(x, y, z + step) > 0) return refine(z + step, z);
    return null;
  }

  // matiere au-dessus du point (dans les 80 m) : sous une voute, dans un tunnel ou une cave
  function covered(x, y, z) {
    for (let h = z + 2 * IN; h <= z + 80 * IN; h += V / 2) if (field(x, y, h) < 0) return true;
    return false;
  }

  // ---- point de la pate sous un rayon ------------------------------------------------------------------------------
  const rc = new THREE.Raycaster();
  function pick(ray) {
    rc.ray.copy(ray); rc.far = Infinity;
    const h = rc.intersectObjects([...meshes.values()], false)[0];
    // relief hors de la zone de pate (dedans, la pate le recouvre) : le plus proche des deux
    const g = o.pickGround?.(ray);
    if (g && !inRegion(g.x, g.y) && (!h || ray.origin.distanceTo(g) < h.distance)) return { point: g.clone(), normal: new THREE.Vector3(0, 0, 1) };
    return h ? { point: h.point.clone(), normal: h.face?.normal.clone() } : null;
  }

  // ---- annuler / brouillon -----------------------------------------------------------------------------------------
  const snapshot = () => ({ v: version, d: new Map([...D].map(([k, a]) => [k, a.slice()])) });
  function restore(s) {
    clearD(); for (const [k, a] of s?.d || []) D.set(k, a.slice()); epoch++;
    version = s?.v ?? version + 1;
    refresh();
  }
  function setSnap(s) {                                     // Ctrl+Z : retouches remises (le remaillage suit avec le relief)
    clearD(); for (const [k, a] of s?.d || []) D.set(k, a.slice()); epoch++;
    version = s?.v ?? version + 1;
  }
  function pack() {                                         // retouches en entiers 16 bits (pouces / 4) en base64
    if (!D.size) return null;
    const chunks = {};
    for (const [k, a] of D) {
      if (!a.some(v => Math.abs(v) >= 1)) continue;
      const u = new Uint8Array(Int16Array.from(a, v => Math.max(-32767, Math.min(32767, Math.round(v / 4)))).buffer);
      let s = ''; for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode.apply(null, u.subarray(i, i + 0x8000));
      chunks[unkey(k).join(',')] = btoa(s);
    }
    return { v: 1, voxel: V, ch: CH, chunks };
  }
  function unpack(p) {
    clearD(); version++;
    if (!p || p.voxel !== V || p.ch !== CH) return;
    for (const [k, b] of Object.entries(p.chunks || {})) {
      const s = atob(b), u = new Uint8Array(s.length); for (let i = 0; i < s.length; i++) u[i] = s.charCodeAt(i);
      if (u.length !== CH ** 3 * 2) continue;
      D.set(key(...k.split(',').map(Number)), Float32Array.from(new Int16Array(u.buffer), v => v * 4));
    }
  }
  function clear() { clearD(); version++; refresh(); }

  return { group, refresh, hiddenMask: () => (computeRegion(), region), get regionVersion() { computeRegion(); return regVersion; }, beginStretch, dragStretch, endStretch, sculpt, dropFloating, tube, fillTo, normalAt, isVolume, columnEdited, surfaceZ, covered, pick, snapshot, restore, setSnap, pack, unpack, clear, field,
           get version() { return version; }, get edited() { return D.size > 0; }, get meshCount() { return meshes.size; },
           get triCount() { let n = 0; for (const m of meshes.values()) n += m.geometry.index.count / 3; return n; } };
}
