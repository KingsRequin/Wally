/* Wally low poly 3D — maquette d'avatar pour l'overlay.
 *
 * MAQUETTE : ce fichier ne remplace RIEN. L'avatar en production reste
 * `avatar/wally.webm`, servi par `overlay.html`. On juge d'abord sur pièces.
 *
 * Le parti pris : aucune géométrie importée, aucun asset payant, aucun outil
 * de modélisation. La silhouette de Wally est une goutte de révolution, donc
 * elle s'écrit — un profil de 14 points passé à `LatheGeometry`. Ce qui se
 * décrit en chiffres se règle, s'anime et se branche plus tard sur les cinq
 * émotions ; un maillage cuit par un générateur d'images, non.
 *
 * Facettes assumées : `flatShading` sur 12 segments. Le low poly est un style,
 * pas un manque de budget — c'est aussi ce qui permet d'onduler le maillage
 * vertex par vertex à chaque image sans y penser (182 sommets).
 */
import * as THREE from "/static/vendor/three.module.min.js";

/* Profil de la goutte, en [hauteur, rayon]. Le ventre est dans le tiers bas
   (y ≈ 0.85), la pointe s'effile sur toute la moitié haute : c'est ce rapport,
   pas le nombre de points, qui fait lire « flamme » plutôt que « ballon ».
   Les rayons ne tombent jamais à 0 — un lathe fermé sur un rayon nul produit
   des triangles dégénérés, donc des normales nulles, donc des taches noires. */
const PROFIL = [
  [0.00, 0.020], [0.05, 0.400], [0.15, 0.660], [0.30, 0.830],
  [0.50, 0.925], [0.72, 0.950], [0.95, 0.930], [1.20, 0.870],
  [1.48, 0.775], [1.78, 0.600], [2.10, 0.440], [2.42, 0.290],
  [2.70, 0.165], [2.92, 0.070], [3.05, 0.012],
];
const HAUTEUR = 3.05;
const SEGMENTS = 12;

/* Relevé sur la vidéo actuelle (`wally.webm`, image 0) : #FE7249. */
const ORANGE = 0xfe7249;
/* Un noir chaud plutôt qu'un noir pur : sous une lumière rasante, le noir pur
   s'aplatit et les yeux se décollent du visage. */
const TRAIT = 0x1a0d09;

/** Rayon du corps à une hauteur donnée, par interpolation du profil.
 *  Sert à POSER le visage sur la surface au lieu de le faire flotter devant. */
function rayonAuY(y) {
  if (y <= PROFIL[0][0]) return PROFIL[0][1];
  for (let i = 1; i < PROFIL.length; i++) {
    const [y0, r0] = PROFIL[i - 1], [y1, r1] = PROFIL[i];
    if (y <= y1) return r0 + (r1 - r0) * ((y - y0) / (y1 - y0));
  }
  return PROFIL[PROFIL.length - 1][1];
}

/* La flamme penche : décalage horizontal croissant avec la hauteur. L'exposant
   garde la base d'aplomb — une courbure linéaire ferait glisser tout le corps
   au lieu de coucher la seule pointe. */
const PENCHE = -0.42;
const pencheAuY = (y) => PENCHE * Math.pow(Math.max(0, y) / HAUTEUR, 2.4);

/** Pose un élément du visage SUR la surface du corps, orienté vers l'extérieur.
 *  `angle` est la rotation autour de l'axe vertical (0 = plein face). */
function poser(obj, angle, y, avance = 0) {
  const r = rayonAuY(y) + avance;
  obj.position.set(pencheAuY(y) + Math.sin(angle) * r, y, Math.cos(angle) * r);
  obj.rotation.y = angle;
}

function creerCorps() {
  const points = PROFIL.map(([y, r]) => new THREE.Vector2(r, y));
  const geom = new THREE.LatheGeometry(points, SEGMENTS);

  /* La penche et l'asymétrie sont cuites dans la géométrie : l'ondulation
     animée s'ajoutera par-dessus, à partir de cette copie de référence. */
  const pos = geom.attributes.position;
  for (let i = 0; i < pos.count; i++) {
    const x = pos.getX(i), y = pos.getY(i), z = pos.getZ(i);
    /* Une révolution parfaite se lit « goutte d'eau ». Trois lobes légers,
       d'autant plus marqués qu'on monte, suffisent à rendre la masse
       irrégulière — donc vivante. */
    const gonfle = 1 + 0.075 * Math.sin(3 * Math.atan2(z, x) + 0.6) * (y / HAUTEUR);
    pos.setXYZ(i, x * gonfle + pencheAuY(y), y, z * gonfle);
  }
  geom.computeVertexNormals();

  const mat = new THREE.MeshStandardMaterial({
    color: ORANGE,
    flatShading: true,
    roughness: 0.62,
    metalness: 0.0,
    /* Une flamme émet. Très peu — juste de quoi empêcher la face à l'ombre de
       virer au brun sale. */
    emissive: ORANGE,
    emissiveIntensity: 0.14,
  });
  return new THREE.Mesh(geom, mat);
}

function creerOeil() {
  const oeil = new THREE.Group();
  const globe = new THREE.Mesh(
    new THREE.SphereGeometry(0.170, 14, 10),
    new THREE.MeshStandardMaterial({ color: TRAIT, roughness: 0.32 }),
  );
  oeil.add(globe);
  /* Reflet en `MeshBasicMaterial` : il doit rester blanc franc quelle que soit
     l'orientation. Une lumière le ferait griser dès que Wally se détourne. */
  const reflet = new THREE.Mesh(
    new THREE.SphereGeometry(0.048, 10, 8),
    new THREE.MeshBasicMaterial({ color: 0xffffff }),
  );
  reflet.position.set(-0.052, 0.058, 0.112);
  oeil.add(reflet);
  return oeil;
}

function creerVisage() {
  const visage = new THREE.Group();
  const matTrait = new THREE.MeshStandardMaterial({ color: TRAIT, roughness: 0.4 });

  const oeilG = creerOeil(), oeilD = creerOeil();
  poser(oeilG, -0.33, 1.05, -0.03);
  poser(oeilD, 0.33, 1.05, -0.03);

  /* Sourcils en arc, pas en barre : le dessin d'origine les a courbés, et une
     boîte droite donnait deux accents circonflexes flottants. L'arc part de +x,
     donc `π/2 − arc/2` le recentre vers le haut. */
  const ARC = 1.15;
  const geomSourcil = new THREE.TorusGeometry(0.26, 0.050, 6, 12, ARC);
  const sourcilG = new THREE.Mesh(geomSourcil, matTrait);
  const sourcilD = new THREE.Mesh(geomSourcil, matTrait);
  poser(sourcilG, -0.33, 1.28, -0.02);
  poser(sourcilD, 0.33, 1.28, -0.02);
  /* Extrémités extérieures relevées : l'air ouvert et neutre du dessin actuel.
     C'est ce seul angle qui, plus tard, portera l'essentiel de l'émotion. */
  sourcilG.rotation.z = Math.PI / 2 - ARC / 2 + 0.16;
  sourcilD.rotation.z = Math.PI / 2 - ARC / 2 - 0.16;

  /* Demi-tore ouvert vers le haut = sourire. `rotation.z = π` parce qu'un arc
     de tore part de +x et couvre le demi-cercle SUPÉRIEUR — soit une moue. */
  const bouche = new THREE.Mesh(
    new THREE.TorusGeometry(0.235, 0.046, 8, 18, Math.PI),
    matTrait,
  );
  poser(bouche, 0, 0.68, 0.03);
  bouche.rotation.z = Math.PI;

  visage.add(oeilG, oeilD, sourcilG, sourcilD, bouche);
  return { visage, yeux: [oeilG, oeilD] };
}

/** Petite braise détachée, en haut à droite — reprise du dessin d'origine.
 *  Elle doit rester nettement SÉPARÉE de la pointe : collée, elle se lit comme
 *  une excroissance ratée du maillage plutôt que comme une étincelle. */
const BRAISE_POS = [0.62, 2.50, 0.05];
function creerBraise(matCorps) {
  const points = PROFIL.map(([y, r]) => new THREE.Vector2(r * 0.20, y * 0.20));
  const braise = new THREE.Mesh(new THREE.LatheGeometry(points, 8), matCorps);
  braise.position.set(...BRAISE_POS);
  return braise;
}

function eclairer(scene) {
  /* Ciel chaud / sol sombre : la lumière d'ambiance colore déjà la silhouette,
     ce qui évite d'avoir à poser un troisième projecteur pour déboucher. */
  scene.add(new THREE.HemisphereLight(0xffe6d5, 0x2a1210, 1.7));

  const cle = new THREE.DirectionalLight(0xffffff, 2.6);
  cle.position.set(2.5, 3.5, 4.0);
  scene.add(cle);

  /* Contre-jour chaud : c'est lui qui détache Wally d'un fond de jeu clair —
     sans liseré, un overlay disparaît dès que la scène derrière est lumineuse. */
  const contre = new THREE.DirectionalLight(0xffb070, 2.0);
  contre.position.set(-3.0, 1.5, -2.5);
  scene.add(contre);

  const bouche = new THREE.DirectionalLight(0x86a6ff, 0.6);
  bouche.position.set(-2.2, -1.0, 1.8);
  scene.add(bouche);
}

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
  camera.position.set(0, 1.50, 7.0);
  camera.lookAt(0, 1.45, 0);
  eclairer(scene);

  const wally = new THREE.Group();
  const corps = creerCorps();
  const { visage, yeux } = creerVisage();
  /* Le visage est enfant du CORPS, pas du groupe : il suit ainsi la respiration
     (le squash & stretch), sinon il s'enfonce dans la surface à chaque cycle. */
  corps.add(visage);
  /* La braise est sœur du corps, pas sa fille : elle flotte librement et ne doit
     pas hériter de la respiration. */
  const braise = creerBraise(corps.material);
  wally.add(corps, braise);
  scene.add(wally);

  /* Référence figée des sommets : l'ondulation repart d'elle à chaque image.
     Cumuler la déformation sur la géométrie vivante la ferait dériver. */
  const base = corps.geometry.attributes.position.array.slice();

  /* `performance.now()` plutôt que `THREE.Clock`, déprécié en r185. Une horloge
     de trois lignes ne mérite pas une dépendance de plus. */
  const depart = performance.now();
  let prochainClignement = 2.0;
  let debutClignement = -1;
  let anim = 0;

  function onduler(t) {
    const pos = corps.geometry.attributes.position;
    for (let i = 0; i < pos.count; i++) {
      const x = base[i * 3], y = base[i * 3 + 1], z = base[i * 3 + 2];
      /* L'amplitude suit la hauteur à la puissance 2.6 : la base reste plantée
         au sol et seule la pointe vit. Une ondulation uniforme donnerait une
         gélatine, pas une flamme. */
      const k = Math.pow(Math.max(0, y) / HAUTEUR, 2.6);
      pos.setXYZ(
        i,
        x + Math.sin(t * 1.9 + y * 1.5) * 0.13 * k,
        y,
        z + Math.cos(t * 1.4 + y * 1.1) * 0.07 * k,
      );
    }
    pos.needsUpdate = true;
    corps.geometry.computeVertexNormals();
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

  function boucle() {
    anim = requestAnimationFrame(boucle);
    const t = (performance.now() - depart) / 1000;

    onduler(t);
    cligner(t);

    /* Respiration : le volume se conserve à peu près (ce qui monte se resserre),
       sinon Wally « gonfle » au lieu de respirer. */
    const souffle = Math.sin(t * 1.5);
    corps.scale.set(1 - souffle * 0.022, 1 + souffle * 0.035, 1 - souffle * 0.022);

    wally.position.y = Math.sin(t * 1.5) * 0.04;
    wally.rotation.z = Math.sin(t * 0.85) * 0.022;

    braise.position.y = BRAISE_POS[1] + Math.sin(t * 2.3 + 1.1) * 0.10;
    braise.position.x = BRAISE_POS[0] + Math.sin(t * 1.7) * 0.05;
    braise.rotation.z = Math.sin(t * 1.9) * 0.25;

    renderer.render(scene, camera);
  }

  function redimensionner(largeur, hauteur) {
    renderer.setSize(largeur, hauteur, false);
    camera.aspect = largeur / hauteur;
    camera.updateProjectionMatrix();
  }

  boucle();
  return {
    redimensionner,
    arreter() {
      cancelAnimationFrame(anim);
      renderer.dispose();
    },
  };
}
