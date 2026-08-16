/* Wally 3D — maquette d'avatar pour l'overlay.
 *
 * MAQUETTE : ce fichier ne remplace RIEN. L'avatar en production reste
 * `avatar/wally.webm`, servi par `overlay.html`. On juge d'abord sur pièces.
 *
 * ── La méthode, et pourquoi celle-là ──────────────────────────────────────
 *
 * Wally n'est PAS une goutte : c'est un feu, avec des langues charnues qui
 * montent, se courbent et retombent. Trois méthodes ont été essayées avant
 * celle-ci, et chacune a échoué pour une raison STRUCTURELLE, pas de réglage :
 *
 *  1. Profil de révolution (`LatheGeometry`) → une goutte. Une silhouette
 *     convexe reste une goutte quoi qu'on l'effile.
 *  2. Une boule + des langues en maillages séparés qui s'y enfoncent → les deux
 *     s'INTERSECTENT au lieu de fusionner : « perruque sur citrouille ».
 *  3. Une icosphère déplacée par un champ radial R(direction) → un rayon parti
 *     du centre ne peut décrire qu'un CÔNE, jamais un doigt : « cristal ».
 *
 * Ce qui est en place : des MÉTABALLES fondues par marching cubes. Le corps est
 * une grosse boule, chaque langue une CHAÎNE de boules décroissantes le long
 * d'une courbe. Le champ de potentiel s'additionne, donc l'union est lisse et
 * continue par nature — il n'y a aucune jonction à cacher, et une chaîne de
 * boules décrit un doigt courbé, ce qu'aucune des trois méthodes ne savait
 * faire.
 *
 * Le rendu est LISSE et non facetté : le low poly était une contrainte qu'on
 * s'était donnée au départ, pas une exigence, et les flammes 3D visées sont
 * douces. `MarchingCubes` sort ses normales du gradient du champ, donc le lissé
 * ne coûte rien de plus.
 *
 * Tout est en chiffres — longueur des langues, largeur, courbure, teinte — donc
 * tout se branchera un jour sur les cinq émotions.
 */
import * as THREE from "/static/vendor/three.module.min.js";
import { MarchingCubes } from "/static/vendor/MarchingCubes.js";

/* ------------------------------------------------------------------ palette */

/* Rampe de température. L'orange de Wally (#FE7249, relevé sur `wally.webm`)
   est placé au niveau du VISAGE : c'est là qu'on reconnaît le personnage, le
   reste du dégradé n'est que du feu autour. */
const RAMPE = [
  [0.00, 0xa8280f],
  [0.16, 0xd53d1c],
  [0.32, 0xfe7249],
  [0.50, 0xff8a33],
  [0.66, 0xffa528],
  [0.83, 0xffc040],
  [1.00, 0xffe479],
];
/* Bornes verticales du dégradé, dans le repère du maillage (qui va de −1 à 1). */
const COL_BAS = -0.92;
const COL_HAUT = 0.94;

/* Rampe précalculée. Les couleurs sont réécrites à chaque image — la forme
   bouge, le dégradé doit rester accroché à la hauteur RÉELLE — et une table
   d'indices coûte une multiplication là où `Color.lerp` coûterait deux
   conversions d'espace colorimétrique par sommet. */
const PALIERS = 96;
const LUT = new Float32Array(PALIERS * 3);
{
  const a = new THREE.Color(), b = new THREE.Color(), c = new THREE.Color();
  for (let i = 0; i < PALIERS; i++) {
    const t = i / (PALIERS - 1);
    let k = 1;
    while (k < RAMPE.length - 1 && t > RAMPE[k][0]) k++;
    const [t0, c0] = RAMPE[k - 1], [t1, c1] = RAMPE[k];
    a.setHex(c0);
    b.setHex(c1);
    c.copy(a).lerp(b, (t - t0) / (t1 - t0));
    LUT[i * 3] = c.r;
    LUT[i * 3 + 1] = c.g;
    LUT[i * 3 + 2] = c.b;
  }
}

/* ------------------------------------------------------------------- champ */

/* `MarchingCubes` attend ses boules en coordonnées 0..1 et rend un maillage
   dans −1..1. Tout le modèle est donc écrit en 0..1, `y` vers le haut. */

/* Le champ d'une boule vaut `force / d² − SOUSTRAIT`, et la surface est là où
   la somme atteint ISOLATION. D'où, pour une boule seule :
   rayon de surface = √(force / (ISOLATION + SOUSTRAIT)).
   On raisonne donc en RAYONS (ce qui se voit) et `force()` fait la conversion —
   régler une « force » à l'aveugle serait ingérable. */
/* `SOUSTRAIT` règle la PORTÉE de fusion : une boule influence le champ jusqu'à
   rayon × √((ISOLATION + SOUSTRAIT) / SOUSTRAIT). À 15, la portée valait 2,5
   rayons et toutes les langues se soudaient en un seul bloc ; à 45 elle tombe à
   1,7, assez pour fondre les jonctions sans effacer les creux. C'est LE réglage
   qui décide si l'on voit un feu ou une patate. */
const ISOLATION = 80;
const SOUSTRAIT = 45;
const force = (rayon) => rayon * rayon * (ISOLATION + SOUSTRAIT);

/* Le corps. Deux boules plutôt qu'une : une seule donne une bille, deux
   décalées donnent une masse d'œuf, plus lourde du bas. */
const CORPS = [
  { x: 0.5, y: 0.230, z: 0.5, rayon: 0.225 },
  { x: 0.5, y: 0.345, z: 0.5, rayon: 0.190 },
];

/* Les langues. `rb`/`yb` = où la chaîne commence (DANS le corps : une langue
   qui démarre à la surface montre sa première boule et se lit comme une corne),
   `rt`/`yt` = où elle finit. `cambrure` la fait bomber latéralement — sans elle
   la chaîne est un segment, donc une pique. `boules` : plus il y en a, plus la
   langue est lisse ; moins il y en a, plus elle est bosselée.
   Hauteurs et largeurs délibérément inégales : un feu régulier lit « couronne ». */
const LANGUES = [
  { az: -0.35, rb: 0.050, yb: 0.38, rt: 0.17, yt: 0.96, cambrure:  0.060, r0: 0.092, r1: 0.014, boules: 13, pulse: 0.62, phase: 0.0 },
  { az:  0.85, rb: 0.090, yb: 0.36, rt: 0.26, yt: 0.84, cambrure: -0.050, r0: 0.080, r1: 0.013, boules: 11, pulse: 0.83, phase: 1.7 },
  { az: -1.60, rb: 0.120, yb: 0.34, rt: 0.31, yt: 0.80, cambrure:  0.045, r0: 0.072, r1: 0.012, boules: 10, pulse: 0.71, phase: 3.1 },
  { az:  2.20, rb: 0.120, yb: 0.32, rt: 0.29, yt: 0.76, cambrure: -0.038, r0: 0.064, r1: 0.011, boules: 9, pulse: 0.94, phase: 4.4 },
  { az:  3.00, rb: 0.060, yb: 0.38, rt: 0.19, yt: 0.90, cambrure:  0.040, r0: 0.076, r1: 0.013, boules: 12, pulse: 0.55, phase: 5.2 },
  { az:  0.32, rb: 0.045, yb: 0.42, rt: 0.14, yt: 0.79, cambrure: -0.035, r0: 0.060, r1: 0.011, boules: 10, pulse: 1.07, phase: 2.4 },
];

/* Les boules du corps ne bougent pas : leur liste est figée une fois pour
   toutes et sert aussi à poser le visage. */
const BOULES_CORPS = CORPS.map((b) => ({ ...b, f: force(b.rayon) }));

/* Tampon des boules de langues, réécrit à chaque image. Un tableau réutilisé
   plutôt qu'un `map()` par image : la boucle tourne 60 fois par seconde. */
const BOULES_LANGUES = [];
for (const l of LANGUES) {
  for (let i = 0; i < l.boules; i++) BOULES_LANGUES.push({ x: 0, y: 0, z: 0, f: 0 });
}

/** Replace toutes les boules de langues pour l'instant `t`. */
function pousser(t) {
  let n = 0;
  for (const l of LANGUES) {
    /* Deux sinus non harmoniques : une seule fréquence donnerait un battement
       régulier, donc une boucle qu'on repère au bout de trois secondes. */
    const vie = 1
      + 0.13 * Math.sin(t * l.pulse * 2.4 + l.phase)
      + 0.06 * Math.sin(t * l.pulse * 5.1 + l.phase * 2.3);
    /* L'ondulation REMONTE la langue : la phase décroît avec `v`, donc la vague
       voyage vers la pointe. Avec un plus elle descendrait — et un feu qui
       coule vers le bas se remarque immédiatement, sans savoir dire pourquoi. */
    const sin = Math.sin(l.az), cos = Math.cos(l.az);

    for (let i = 0; i < l.boules; i++) {
      const v = i / (l.boules - 1);
      /* Le rayon s'écarte de l'axe en accélérant : la langue part droite et ne
         se couche qu'en fin de course, ce qui lui donne son crochet. */
      const r = l.rb + (l.rt - l.rb) * Math.pow(v, 1.7);
      const y = l.yb + (l.yt - l.yb) * v * vie;
      /* Cambrure fixe + ondulation vivante, toutes deux tangentielles. */
      const tang = l.cambrure * Math.sin(Math.PI * v)
        + 0.035 * v * v * Math.sin(t * 2.4 - v * 3.6 + l.phase);

      const b = BOULES_LANGUES[n++];
      b.x = 0.5 + sin * r + cos * tang;
      b.y = y;
      b.z = 0.5 + cos * r - sin * tang;
      /* La racine carrée sur (1 − v) fait tenir la largeur sur les deux tiers de
         la course avant de l'effiler d'un coup. Une décroissance en `v` — même
         adoucie — amincissait la langue dès le départ : on obtenait une antenne
         au lieu d'une flamme. C'est cette rupture, et pas la finesse de la
         pointe, qui donne le coup de fouet. */
      b.f = force(l.r1 + (l.r0 - l.r1) * Math.sqrt(1 - v));
    }
  }
}

/** Valeur du champ en un point, pour les boules données. Sert à POSER le visage
 *  sur la vraie surface : la deviner reviendrait à la voir dériver au premier
 *  réglage de rayon. */
function champ(x, y, z, boules) {
  let s = 0;
  for (let i = 0; i < boules.length; i++) {
    const b = boules[i];
    const dx = x - b.x, dy = y - b.y, dz = z - b.z;
    const val = b.f / (0.000001 + dx * dx + dy * dy + dz * dz) - SOUSTRAIT;
    if (val > 0) s += val;
  }
  return s;
}

/* Surface de référence pour poser le visage : le corps ET les langues figées à
   l'instant 0. Le corps seul ne suffit pas — les langues gonflent la surface
   autour d'elles, et un œil placé sur le corps nu se retrouve SOUS la peau.
   Figée, et non recalculée : sinon le sourcil bondirait à chaque battement. */
const BOULES_REPOS = [];
function figerLeRepos() {
  pousser(0);
  BOULES_REPOS.length = 0;
  BOULES_REPOS.push(...BOULES_CORPS, ...BOULES_LANGUES.map((b) => ({ ...b })));
}

/** Distance du centre du corps à sa surface, dans une direction unitaire.
 *  Dichotomie : le champ décroît en 1/d², il n'y a pas de forme fermée. */
const CENTRE = [0.5, 0.30, 0.5];
function surfaceCorps(dx, dy, dz) {
  let bas = 0.0, haut = 0.6;
  for (let i = 0; i < 24; i++) {
    const m = (bas + haut) / 2;
    if (champ(CENTRE[0] + dx * m, CENTRE[1] + dy * m, CENTRE[2] + dz * m, BOULES_REPOS) > ISOLATION) {
      bas = m;
    } else {
      haut = m;
    }
  }
  return (bas + haut) / 2;
}

/* ------------------------------------------------------------------- visage */

/* Un noir chaud plutôt qu'un noir pur : sous une lumière rasante, le noir pur
   s'aplatit et les yeux se décollent du visage. */
const TRAIT = 0x2a0f06;

/* Le visage, en directions (azimut, élévation) : le champ ne sait répondre qu'à
   une direction. Élévations négatives = sous l'équateur du corps. */
const AZ_OEIL = 0.36;
const EL_OEIL = 0.02;
const EL_SOURCIL = 0.44;
const EL_BOUCHE = -0.44;

/* Le maillage sortant de `MarchingCubes` va de −1 à 1 quand le modèle est écrit
   en 0..1 : tout ce qui est posé dessus doit donc être exprimé au DOUBLE. */
const ECHELLE = 2;

const _p = new THREE.Vector3();

/** Pose un élément SUR la surface du corps, tourné vers l'extérieur. */
function poser(obj, azimut, elevation, avance = 0) {
  const ce = Math.cos(elevation);
  const dx = Math.sin(azimut) * ce, dy = Math.sin(elevation), dz = Math.cos(azimut) * ce;
  const r = surfaceCorps(dx, dy, dz) + avance;
  _p.set(
    (CENTRE[0] + dx * r) * ECHELLE - 1,
    (CENTRE[1] + dy * r) * ECHELLE - 1,
    (CENTRE[2] + dz * r) * ECHELLE - 1,
  );
  obj.position.copy(_p);
  /* `lookAt` oriente le +z de l'objet vers la cible ; les traits du visage sont
     dessinés face à +z. On vise donc loin DEVANT, le long de la normale. */
  obj.lookAt(_p.x + dx, _p.y + dy, _p.z + dz);
}

/* Tailles exprimées par rapport au rayon du corps (~0.42 après fusion des deux
   boules, en unités de maillage) : ainsi le visage garde ses proportions si on
   regrossit le corps. */
const R_CORPS = 0.52;

function creerOeil() {
  const oeil = new THREE.Group();
  const globe = new THREE.Mesh(
    new THREE.SphereGeometry(R_CORPS * 0.20, 14, 10),
    new THREE.MeshStandardMaterial({ color: TRAIT, roughness: 0.32 }),
  );
  globe.scale.y = 1.12;
  oeil.add(globe);
  /* Reflet en `MeshBasicMaterial` : il doit rester blanc franc quelle que soit
     l'orientation. Une lumière le ferait griser dès que Wally se détourne. */
  const reflet = new THREE.Mesh(
    new THREE.SphereGeometry(R_CORPS * 0.056, 10, 8),
    new THREE.MeshBasicMaterial({ color: 0xffffff }),
  );
  reflet.position.set(-R_CORPS * 0.060, R_CORPS * 0.068, R_CORPS * 0.13);
  oeil.add(reflet);
  return oeil;
}

function creerVisage() {
  const visage = new THREE.Group();
  const matTrait = new THREE.MeshStandardMaterial({ color: TRAIT, roughness: 0.4 });

  const oeilG = creerOeil(), oeilD = creerOeil();
  poser(oeilG, -AZ_OEIL, EL_OEIL, -0.02);
  poser(oeilD, AZ_OEIL, EL_OEIL, -0.02);

  /* Sourcils en arc, pas en barre : le dessin d'origine les a courbés, et une
     boîte droite donnait deux accents circonflexes flottants. L'arc part de +x,
     donc `π/2 − arc/2` le recentre vers le haut. */
  const ARC = 1.15;
  const geomSourcil = new THREE.TorusGeometry(R_CORPS * 0.30, R_CORPS * 0.058, 6, 12, ARC);
  const sourcilG = new THREE.Mesh(geomSourcil, matTrait);
  const sourcilD = new THREE.Mesh(geomSourcil, matTrait);
  /* Avance POSITIVE : sur une surface convexe, les extrémités d'un arc
     s'enfoncent bien plus que son milieu. À fleur de peau, le sourcil
     disparaît par les bouts. */
  poser(sourcilG, -AZ_OEIL, EL_SOURCIL, 0.05);
  poser(sourcilD, AZ_OEIL, EL_SOURCIL, 0.05);
  /* `rotateZ` APRÈS `lookAt`, dans le repère local : `rotation.z = …` écraserait
     l'orientation que `poser` vient d'établir. Extrémités extérieures relevées,
     l'air ouvert et neutre du dessin actuel — c'est ce seul angle qui, plus
     tard, portera l'essentiel de l'émotion. */
  sourcilG.rotateZ(Math.PI / 2 - ARC / 2 + 0.16);
  sourcilD.rotateZ(Math.PI / 2 - ARC / 2 - 0.16);

  /* Demi-tore ouvert vers le haut = sourire. Le demi-tour parce qu'un arc de
     tore part de +x et couvre le demi-cercle SUPÉRIEUR — soit une moue. */
  const bouche = new THREE.Mesh(
    new THREE.TorusGeometry(R_CORPS * 0.26, R_CORPS * 0.052, 8, 18, Math.PI),
    matTrait,
  );
  poser(bouche, 0, EL_BOUCHE, 0.01);
  bouche.rotateZ(Math.PI);

  visage.add(oeilG, oeilD, sourcilG, sourcilD, bouche);
  return { visage, yeux: [oeilG, oeilD] };
}

/* ------------------------------------------------------------------ braises */

/* Étincelles détachées. Elles montent, s'éteignent, repartent : c'est le seul
   élément qui dit que le feu PRODUIT quelque chose au lieu de juste bouger.
   Hors métaballes exprès — fondues dans le champ, elles feraient des bourgeons
   collés à la flamme au lieu de s'en détacher. */
const BRAISES = [
  { x:  0.50, z:  0.14, y: 0.30, portee: 0.55, duree: 2.6, decalage: 0.0, taille: 0.055 },
  { x: -0.56, z:  0.06, y: 0.10, portee: 0.65, duree: 3.3, decalage: 1.4, taille: 0.042 },
  { x:  0.22, z: -0.24, y: 0.55, portee: 0.45, duree: 2.9, decalage: 2.2, taille: 0.034 },
];

function creerBraise(taille) {
  /* Un tétraèdre étiré : quatre facettes, une pointe franche. À cette taille,
     rien de plus détaillé ne serait lisible. */
  const geom = new THREE.TetrahedronGeometry(taille, 0);
  geom.scale(0.8, 2.1, 0.8);
  const mat = new THREE.MeshStandardMaterial({
    color: 0xffd463,
    emissive: 0xff9a2e,
    emissiveIntensity: 0.7,
    roughness: 0.5,
    flatShading: true,
    transparent: true,
  });
  return new THREE.Mesh(geom, mat);
}

/* ---------------------------------------------------------------- éclairage */

function eclairer(scene) {
  /* Le dégradé étant déjà dans les sommets, la lumière n'a plus à colorer quoi
     que ce soit : elle ne sert qu'à donner le volume. D'où une ambiance forte
     et des projecteurs modérés — l'inverse écraserait la rampe vers le blanc. */
  scene.add(new THREE.HemisphereLight(0xfff0e0, 0x3a1508, 1.5));

  const cle = new THREE.DirectionalLight(0xffffff, 1.25);
  cle.position.set(2.5, 3.2, 4.5);
  scene.add(cle);

  /* Contre-jour chaud : c'est lui qui détache Wally d'un fond de jeu clair —
     sans liseré, un overlay disparaît dès que la scène derrière est lumineuse. */
  const contre = new THREE.DirectionalLight(0xffb070, 0.9);
  contre.position.set(-3.0, 1.4, -2.6);
  scene.add(contre);

  const bouche = new THREE.DirectionalLight(0x86a6ff, 0.3);
  bouche.position.set(-2.2, -1.0, 1.8);
  scene.add(bouche);
}

/* ------------------------------------------------------------------ montage */

/* Résolution de la grille. Elle fixe la finesse de la surface — trop bas, les
   pointes deviennent des moignons ; trop haut, le coût est CUBIQUE et la
   polygonisation JS mange l'image. 48 tient les 60 fps même en rendu logiciel. */
const RESOLUTION = 48;

/**
 * Monte Wally dans un canvas et lance sa boucle d'animation.
 * Retourne `{ redimensionner, arreter }`.
 */
export function creerWally(canvas) {
  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  renderer.setClearAlpha(0);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

  const scene = new THREE.Scene();
  /* Cadrage serré, comme l'avatar actuel : dans un slot de 200 px sur l'overlay,
     tout l'air laissé autour est du personnage en moins. */
  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100);
  camera.position.set(0, 0.02, 4.3);
  camera.lookAt(0, 0.0, 0);
  eclairer(scene);

  const matFeu = new THREE.MeshStandardMaterial({
    vertexColors: true,
    /* Rendu LISSE, pas facetté : les références visées sont des flammes 3D
       douces et satinées. Le low poly était une contrainte qu'on s'était
       imposée, pas une demande — et `MarchingCubes` calcule déjà des normales
       interpolées, donc c'est gratuit. */
    roughness: 0.42,
    metalness: 0.0,
    /* Une flamme émet. Très peu — juste de quoi empêcher la face à l'ombre de
       virer au brun sale. */
    emissive: 0xff6a2a,
    emissiveIntensity: 0.15,
  });

  /* `enableColors` sert seulement à faire EXISTER l'attribut de couleur : les
     teintes par boule de la classe se somment sans être normalisées et virent
     au blanc là où deux boules se recouvrent. On les réécrit nous-mêmes par la
     hauteur, après chaque polygonisation. */
  const feu = new MarchingCubes(RESOLUTION, matFeu, false, true, 40000);
  feu.isolation = ISOLATION;

  /* Le champ doit être dans son état de repos AVANT de poser le visage : sans
     ça, `poser()` interrogerait des langues de longueur nulle et les yeux
     s'enfonceraient dans le corps dès la première image. */
  figerLeRepos();
  const { visage, yeux } = creerVisage();
  /* Le visage est enfant du FEU : il suit ainsi la respiration, sinon il
     s'enfonce dans la surface à chaque cycle. */
  feu.add(visage);

  const wally = new THREE.Group();
  const braises = BRAISES.map((b) => creerBraise(b.taille));
  wally.add(feu, ...braises);
  scene.add(wally);

  /* `performance.now()` plutôt que `THREE.Clock`, déprécié en r185. Une horloge
     de trois lignes ne mérite pas une dépendance de plus. */
  const depart = performance.now();
  let prochainClignement = 2.0;
  let debutClignement = -1;
  let anim = 0;

  /* Aucun `computeVertexNormals()` : `MarchingCubes` sort déjà ses normales, et
     mieux que nous — il les prend dans le GRADIENT du champ, donc lisses par
     construction, là où un calcul par facette ne verrait que la maille. */

  function sculpter(t) {
    pousser(t);
    feu.reset();
    for (const b of BOULES_CORPS) feu.addBall(b.x, b.y, b.z, b.f, SOUSTRAIT);
    for (const b of BOULES_LANGUES) feu.addBall(b.x, b.y, b.z, b.f, SOUSTRAIT);
    feu.update();

    /* Le dégradé est accroché à la hauteur RÉELLE, pas à une boule : une langue
       qui pousse doit voir sa pointe virer au jaune en montant. */
    const pos = feu.geometry.attributes.position.array;
    const col = feu.geometry.attributes.color.array;
    const echelle = (PALIERS - 1) / (COL_HAUT - COL_BAS);
    for (let i = 0; i < feu.count; i++) {
      let k = Math.round((pos[i * 3 + 1] - COL_BAS) * echelle);
      k = k < 0 ? 0 : k > PALIERS - 1 ? PALIERS - 1 : k;
      col[i * 3] = LUT[k * 3];
      col[i * 3 + 1] = LUT[k * 3 + 1];
      col[i * 3 + 2] = LUT[k * 3 + 2];
    }
    feu.geometry.attributes.color.needsUpdate = true;
  }

  function animerBraises(t) {
    braises.forEach((braise, i) => {
      const b = BRAISES[i];
      const p = ((t + b.decalage) % b.duree) / b.duree;
      braise.position.set(b.x + Math.sin(t * 1.9 + i) * 0.05, b.y + b.portee * p, b.z);
      /* Naître et mourir en fondu : une étincelle qui apparaît d'un coup se lit
         comme un défaut d'affichage. */
      braise.material.opacity = Math.sin(p * Math.PI);
      braise.scale.setScalar(1 - 0.35 * p);
      braise.rotation.z = Math.sin(t * 2.2 + i) * 0.30;
    });
  }

  function cligner(t) {
    if (debutClignement < 0 && t >= prochainClignement) debutClignement = t;
    if (debutClignement < 0) return;

    const DUREE = 0.15;
    const p = (t - debutClignement) / DUREE;
    if (p >= 1) {
      debutClignement = -1;
      /* Intervalle irrégulier : un clignement métronomique se remarque
         immédiatement et trahit la boucle. */
      prochainClignement = t + 2.4 + Math.random() * 3.6;
      yeux.forEach((o) => (o.scale.y = 1));
      return;
    }
    const fermeture = Math.sin(p * Math.PI);
    yeux.forEach((o) => (o.scale.y = 1 - 0.92 * fermeture));
  }

  /* Coût réel d'une image, en moyenne glissante. La polygonisation tourne en JS
     sur le fil principal : c'est le seul chiffre qui dise si l'avatar tiendra
     dans OBS à côté d'un jeu. Mesuré, pas supposé. */
  let coutImage = 0;

  function boucle() {
    anim = requestAnimationFrame(boucle);
    const t = (performance.now() - depart) / 1000;
    const avant = performance.now();

    sculpter(t);
    animerBraises(t);
    cligner(t);

    /* Respiration : le volume se conserve à peu près (ce qui monte se resserre),
       sinon Wally « gonfle » au lieu de respirer. */
    const souffle = Math.sin(t * 1.5);
    feu.scale.set(1 - souffle * 0.018, 1 + souffle * 0.028, 1 - souffle * 0.018);

    wally.position.y = Math.sin(t * 1.5) * 0.02;
    wally.rotation.z = Math.sin(t * 0.85) * 0.018;

    renderer.render(scene, camera);
    coutImage = coutImage * 0.9 + (performance.now() - avant) * 0.1;
  }

  function redimensionner(largeur, hauteur) {
    renderer.setSize(largeur, hauteur, false);
    camera.aspect = largeur / hauteur;
    camera.updateProjectionMatrix();
  }

  boucle();
  return {
    redimensionner,
    /** Coût d'une image en millisecondes, et nombre de triangles rendus. */
    mesures: () => ({ ms: coutImage, triangles: Math.round(feu.count / 3) }),
    arreter() {
      cancelAnimationFrame(anim);
      renderer.dispose();
    },
  };
}
