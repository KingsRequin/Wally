/* Wally 3D — maquette d'avatar pour l'overlay.
 *
 * MAQUETTE : ce fichier ne remplace RIEN. L'avatar en production reste
 * `avatar/wally.webm`, servi par `overlay.html`. On juge d'abord sur pièces.
 *
 * ── La méthode, et pourquoi celle-là ──────────────────────────────────────
 *
 * Wally est un feu : des langues charnues qui montent, se courbent, s'effilent.
 * Quatre méthodes à MAILLAGE ont été essayées, et chacune a échoué pour une
 * raison structurelle — pas un réglage :
 *
 *  1. Profil de révolution (`LatheGeometry`) → une goutte. Une silhouette
 *     convexe reste une goutte quoi qu'on l'effile.
 *  2. Boule + langues en maillages séparés qui s'y enfoncent → les deux
 *     s'INTERSECTENT au lieu de fusionner : « perruque sur citrouille ».
 *  3. Icosphère déplacée par un champ radial R(direction) → un rayon parti du
 *     centre ne décrit qu'un CÔNE, jamais un doigt : « cristal ».
 *  4. Métaballes polygonisées (marching cubes) → l'union est enfin continue,
 *     mais un champ de métaballes ARRONDIT tout : aucune pointe nette. Et la
 *     surface est reconstruite sur une grille, donc les extrémités fines
 *     partent en bouillie dès que le détail passe sous le pas de la grille.
 *
 * Ici : PLUS DE MAILLAGE DU TOUT. La flamme est une fonction de distance
 * signée (SDF), tracée au rayon dans le fragment shader. Conséquences directes
 * sur les deux défauts qui restaient :
 *
 *  - une langue est une courbe de Bézier balayée par une section qui s'effile
 *    jusqu'à un VRAI point : la finesse est celle du pixel, plus celle d'une
 *    maille. Plus de bouillie, plus de rectangles ;
 *  - ombres douces, occlusion ambiante et translucidité se lisent directement
 *    dans le champ de distance. C'est ce qui sépare un rendu de studio d'un
 *    rendu « jeu de navigateur », et ici ça ne coûte qu'un rayon de plus.
 *
 * Tout est en chiffres — courbe, largeur, effilement, teinte — donc tout se
 * branchera un jour sur les cinq émotions.
 *
 * Références de technique : Inigo Quilez, « Raymarching Distance Fields » et
 * « Soft shadows in raymarched SDFs » (iquilezles.org). Les primitives
 * `sdRoundCone` / `sdEllipsoid` viennent de sa liste, elles sont exactes.
 */
import * as THREE from "/static/vendor/three.module.min.js";

const FRAGMENT = /* glsl */ `
precision highp float;

uniform vec2  uTaille;
uniform float uTemps;

/* « Assez loin pour ne jamais gagner un min ». Toute la scène tient dans une
   dizaine d'unités, donc 10 000 suffisent — et surtout, PAS 1e9 : ce genre de
   constante ne survit qu'en haute précision, et si un pilote retombe en
   précision moyenne (maximum ≈ 65 000) elle devient l'infini, puis un NaN à la
   première soustraction. C'est un classique du clignotement sur GPU intégré. */
const float LOIN = 1.0e4;

/* ─────────────────────────────────────────────────── primitives exactes ── */

float smin(float a, float b, float k) {
  float h = clamp(0.5 + 0.5 * (b - a) / k, 0.0, 1.0);
  return mix(b, a, h) - k * h * (1.0 - h);
}

float sdEllipsoide(vec3 p, vec3 r) {
  float k0 = length(p / r);
  /* 🚨 Au CENTRE exact de l'ellipsoïde, k0 et k1 valent zéro : la formule rend
     0/0, donc NaN. Le cas n'est pas théorique — traversee() sonde le champ à
     l'INTÉRIEUR du corps, et un de ses points peut tomber sur un centre (celui
     d'un œil, notamment, qui est petit). Le NaN remonte ensuite par les min et
     les smin et noircit le pixel. */
  float k1 = max(length(p / (r * r)), 1e-7);
  return k0 * (k0 - 1.0) / k1;
}

float sdCapsule(vec3 p, vec3 a, vec3 b, float r) {
  vec3 pa = p - a, ba = b - a;
  float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
  return length(pa - ba * h) - r;
}

/* Cône à bouts ronds. C'est LA primitive de la flamme : en passant r2 = 0, il
   se termine sur un point exact — ce qu'aucun maillage ni métaballe ne sait
   faire. Formulation exacte d'Inigo Quilez. */
float sdConeRond(vec3 p, vec3 a, vec3 b, float r1, float r2) {
  vec3 ba = b - a;
  float l2 = max(dot(ba, ba), 1e-6);
  float rr = r1 - r2;
  float a2 = l2 - rr * rr;

  /* 🚨 Cône DÉGÉNÉRÉ : quand l'écart des rayons dépasse la longueur, une boule
     avale l'autre et a2 passe sous zéro — sqrt() rend alors NaN. Le NaN
     contamine tout le champ par les min/smin, la comparaison de la marche
     devient imprévisible, et l'image ENTIÈRE vire au noir opaque.
     Constaté en prod à t ≈ 3,4 s : le cycle de vie raccourcissait une langue
     sous son propre rayon de base. Un cas de bord de trois images sur cent,
     mais total quand il arrive. Ici la forme est exactement une boule, donc on
     la renvoie telle quelle plutôt que de rafistoler la racine. */
  if (a2 <= 0.0) return length(p - (rr > 0.0 ? a : b)) - max(r1, r2);

  float il2 = 1.0 / l2;
  vec3 pa = p - a;
  float y = dot(pa, ba);
  float z = y - l2;
  vec3 xv = pa * l2 - ba * y;
  float x2 = dot(xv, xv);
  float y2 = y * y * l2;
  float z2 = z * z * l2;
  float k = sign(rr) * rr * rr * x2;
  if (sign(z) * a2 * z2 > k) return sqrt(x2 + z2) * il2 - r2;
  if (sign(y) * a2 * y2 < k) return sqrt(x2 + y2) * il2 - r1;
  return (sqrt(x2 * a2 * il2) + y * rr) * il2 - r1;
}

vec3 bezier(vec3 a, vec3 b, vec3 c, float t) {
  float u = 1.0 - t;
  return u * u * a + 2.0 * u * t * b + t * t * c;
}

/* ────────────────────────────────────────────────────────── la flamme ── */

/* Une langue de feu.
 *
 * 🚨 Deux erreurs font une PIEUVRE plutôt qu'un feu, et il a fallu les deux
 * pour s'en sortir : une langue qui s'ÉCARTE de l'axe en montant est un
 * tentacule (une flamme monte), et une langue à section RONDE est un tentacule
 * même droite (une vraie langue est une lame, large de face et mince de
 * profil). D'où le repère tourné puis aplati, et une trajectoire qui reste à
 * distance constante de l'axe.
 *
 * az place la langue autour de l'axe — donc aussi en PROFONDEUR. C'est leur
 * chevauchement, et non leur écartement, qui donne son volume au feu. */
float langue(vec3 p, float az, vec3 B, vec3 M, vec3 T, float r0, float aplat,
             float phase, float vitesse, float periode, float decalage) {
  float c = cos(-az), s = sin(-az);
  vec3 q = vec3(c * p.x - s * p.z, p.y, s * p.x + c * p.z);

  /* 🚨 LA VIE DE LA LANGUE. Sans ce cycle, une langue ne fait que se balancer :
     elle garde la même longueur pour toujours et le feu se lit comme un objet
     qui vibre. Une vraie langue NAÎT, s'allonge, tient, puis se rétracte et
     cède la place. C'est ce cycle — et non l'agitation de la pointe — qui fait
     qu'on lit « feu ».
     Le facteur de vie multiplie AUSSI la montée : au raccord du cycle (u → 1)
     la vie vaut 0, donc rien ne saute quand le compteur repasse à zéro. */
  float u = fract(uTemps / periode + decalage);
  float vie = smoothstep(0.0, 0.20, u) * (1.0 - smoothstep(0.60, 1.0, u));
  /* Le plancher n'est pas décoratif : sous ~0,55 la langue devient plus courte
     que son propre rayon de base, et ses segments dégénèrent. On garde donc de
     la marge en plus du garde-fou de sdConeRond — une ceinture ET des
     bretelles, parce que le symptôme est une image entièrement noire. */
  float allonge = 0.55 + 0.45 * vie;

  /* Le milieu balance, la pointe fouette deux fois plus, et les deux sinus ne
     sont pas harmoniques — une seule fréquence donnerait un battement qu'on
     repère au bout de trois secondes. */
  float sw  = sin(uTemps * vitesse + phase);
  float sw2 = sin(uTemps * vitesse * 1.63 + phase * 1.7);
  vec3 m = mix(B, M, allonge) + vec3(0.055 * sw, 0.020 * sw2, 0.0);
  vec3 t = mix(B, T, allonge)
         + vec3(0.130 * sw2, 0.075 * sw + 0.13 * u * vie, 0.0);

  /* Borne : la langue tient dans cette capsule, donc la distance à la capsule
     MINORE la distance à la langue — c'est ce qui rend le raccourci licite
     pour le tracé de rayon. Sans lui, les quatre cônes seraient évalués pour
     chaque pixel du cadre, même vide. */
  /* 🚨 Le seuil doit dépasser le rayon de fusion (smin) le plus large, sinon le
     raccourci renvoie une distance MINORÉE juste assez près pour peser dans le
     smin : le corps se met à bomber là où la borne s'active, avec une arête
     franche au seuil. Vu à l'écran, en travers de la joue. */
  float db = sdCapsule(q, B, t, r0 + 0.16);
  if (db > 0.30) return db;

  /* Lame : on écrase la PROFONDEUR autour du plan de la langue, pas la
     trajectoire — sinon la courbe se déplacerait avec l'aplatissement. */
  q.z = B.z + (q.z - B.z) / aplat;

  vec3 p0 = B;
  float d = LOIN;
  for (int i = 1; i <= 4; i++) {
    float u = float(i) * 0.25;
    vec3 p1 = bezier(B, m, t, u);
    /* Onde qui REMONTE la langue : la phase décroît avec u, donc une crête
       part de la base et file vers la pointe. Avec un plus elle descendrait —
       un feu qui coule vers le bas se remarque tout de suite, même sans savoir
       dire pourquoi. C'est ce terme qui donne le mouvement d'ascension ; le
       balancement ci-dessus ne fait que remuer la langue en bloc. */
    p1.x += 0.050 * u * sin(uTemps * 3.6 - u * 6.0 + phase);
    /* Le rayon tombe à ZÉRO au dernier point : la pointe est un point, pas une
       calotte. L'exposant < 1 fait tenir la matière sur les deux tiers de la
       course avant de s'effiler d'un coup — c'est cette rupture, et non la
       finesse de la pointe, qui donne le coup de fouet. */
    float ra = r0 * pow(1.0 - (u - 0.25), 0.62);
    float rb = r0 * pow(1.0 - u, 0.62);
    d = min(d, sdConeRond(q, p0, p1, ra, rb));
    p0 = p1;
  }
  return d * aplat;
}

/* Un morceau de flamme qui se détache.
 *
 * Il NAÎT à l'intérieur du feu, monte en ralentissant, rétrécit, et s'éteint.
 * La séparation n'est pas jouée : elle arrive toute seule, parce que le fondu
 * (smin) qui le rattache au corps cesse d'agir dès qu'il s'en éloigne. C'est
 * ce qui manque le plus à une flamme qui ne fait que s'agiter — sans rien qui
 * s'en échappe, elle reste un objet, jamais une combustion.
 *
 * Disparaître demande de RETIRER la primitive : un cône dont les deux rayons
 * tombent à zéro dégénère en segment, et un segment se dessine encore — un
 * cheveu qui reste à l'écran. D'où la sortie franche sous un rayon sub-pixel. */
float detache(vec3 p, vec3 base, float derive, float montee, float r0,
              float periode, float decalage) {
  float u = fract(uTemps / periode + decalage);
  float r = r0 * (1.0 - u) * smoothstep(0.0, 0.16, u);
  if (r < 0.006) return LOIN;

  vec3 c = base + vec3(derive * u + 0.04 * sin(uTemps * 1.9 + decalage * 11.0),
                       montee * pow(u, 0.72), 0.0);
  /* Une goutte pointue vers le haut, comme la flamme dont elle vient. */
  return sdConeRond(p, c, c + vec3(0.0, r * 3.0, 0.0), r, 0.0);
}

/* Matériaux : 1 = feu, 2 = trait du visage, 3 = reflet de l'œil. */
vec2 plusProche(vec2 a, vec2 b) { return a.x < b.x ? a : b; }

/* Le corps : deux ellipsoïdes fondus, plus lourd du bas. Une seule sphère se
   lit « tête » ; deux masses décalées donnent un œuf qui se referme vers le
   haut, d'où les langues sortent en prolongement au lieu d'y être plantées. */
float corps(vec3 p) {
  float bas  = sdEllipsoide(p - vec3(0.0, -0.40, 0.0), vec3(0.62, 0.56, 0.60));
  float haut = sdEllipsoide(p - vec3(0.0,  0.02, 0.0), vec3(0.50, 0.46, 0.48));
  return smin(bas, haut, 0.26);
}

float feu(vec3 p) {
  /* Flux ascendant. Une déformation du REPÈRE, dont la phase décroît avec la
     hauteur : tout ce qui est décrit ensuite se met à défiler vers le haut, y
     compris la masse du corps. C'est le mouvement de fond ; sans lui, seules
     les pointes remuent et le feu a l'air posé.
     Elle démarre au-dessus du visage — un front qui ondule n'est pas une
     flamme, c'est un défaut. */
  float k = smoothstep(0.05, 0.75, p.y);
  vec3 w = p;
  w.x += 0.034 * k * sin(p.y * 4.0 - uTemps * 3.1);
  w.z += 0.024 * k * cos(p.y * 3.4 - uTemps * 2.5);

  float d = corps(w);

  /* Cinq langues, délibérément inégales en hauteur, en largeur et en cadence,
     et surtout aux cycles de vie DÉPHASÉS : si elles poussaient ensemble, le
     feu entier respirerait comme un poumon. Le smin les fait naître DU corps —
     un min les y collerait avec une arête visible. */
  d = smin(d, langue(w,  0.10, vec3(0.0, -0.05, 0.12), vec3(0.05, 0.48, 0.12), vec3(-0.07, 1.06, 0.12), 0.225, 0.40, 0.0, 1.30, 3.30, 0.00), 0.15);
  d = smin(d, langue(w, -1.00, vec3(0.0, -0.15, 0.36), vec3(0.09, 0.30, 0.36), vec3( 0.17, 0.80, 0.36), 0.190, 0.38, 1.7, 1.62, 2.60, 0.37), 0.13);
  d = smin(d, langue(w,  1.25, vec3(0.0, -0.15, 0.36), vec3(-0.08, 0.27, 0.36), vec3(-0.16, 0.70, 0.36), 0.175, 0.38, 3.1, 1.44, 2.90, 0.71), 0.13);
  d = smin(d, langue(w,  2.60, vec3(0.0, -0.08, 0.20), vec3(0.07, 0.40, 0.20), vec3( 0.14, 0.92, 0.20), 0.185, 0.38, 5.2, 1.18, 3.70, 0.19), 0.13);
  d = smin(d, langue(w, -2.15, vec3(0.0, -0.20, 0.34), vec3(-0.07, 0.18, 0.34), vec3(-0.13, 0.55, 0.34), 0.155, 0.36, 4.4, 1.86, 2.30, 0.55), 0.12);

  /* Les morceaux qui s'échappent. Sur le repère NON déformé : ils ont quitté
     le flux, ils ne doivent plus le suivre. */
  d = smin(d, detache(p, vec3( 0.06, 0.62, 0.10), -0.10, 0.62, 0.085, 2.70, 0.00), 0.06);
  d = smin(d, detache(p, vec3(-0.20, 0.46, 0.22),  0.13, 0.78, 0.062, 3.40, 0.42), 0.05);
  d = smin(d, detache(p, vec3( 0.24, 0.38, 0.14),  0.09, 0.55, 0.048, 2.20, 0.78), 0.05);
  return d;
}

/* Le visage. En union FRANCHE (min) et non fondue : un trait qui se fond
   dans la joue n'est plus un trait. */
vec2 visage(vec3 p) {
  /* Borne du visage : huit primitives pour une zone qui n'occupe qu'un coin du
     volume. Les évaluer partout revenait à payer le visage sur chaque pas de
     chaque rayon. La distance à la sphère englobante MINORE la vraie, donc le
     raccourci reste licite pour la marche ; le matériau renvoyé n'a aucune
     importance ici, on est encore à plus de 6 cm de toute surface. */
  float db = length(p - vec3(0.0, -0.16, 0.40)) - 0.55;
  if (db > 0.06) return vec2(db, 1.0);

  vec3 ps = vec3(abs(p.x), p.y, p.z);          // symétrie : un œil pour deux

  /* 🚨 Les profondeurs (z) suivent la surface RÉELLE du corps, qui recule
     fortement quand on monte et quand on s'écarte du milieu. Posées à une
     profondeur unique, les extrémités des sourcils et les coins de la bouche
     passent SOUS la peau et disparaissent — c'est ce qui les avait effacés. */
  float oeil = sdEllipsoide(ps - vec3(0.235, -0.11, 0.440), vec3(0.125, 0.142, 0.125));
  vec2 d = vec2(oeil, 2.0);

  /* Reflet en blanc pur, décalé vers le haut à l'intérieur du globe : c'est lui
     qui fait qu'un œil REGARDE au lieu d'être un trou. */
  float reflet = length(ps - vec3(0.195, -0.052, 0.535)) - 0.038;
  d = plusProche(d, vec2(reflet, 3.0));

  /* Sourcil : deux capsules en chevron, extrémité extérieure relevée. C'est ce
     seul angle qui, plus tard, portera l'essentiel de l'émotion. */
  float s1 = sdCapsule(ps, vec3(0.115, 0.135, 0.425), vec3(0.265, 0.165, 0.378), 0.035);
  float s2 = sdCapsule(ps, vec3(0.265, 0.165, 0.378), vec3(0.400, 0.130, 0.278), 0.032);
  d = plusProche(d, vec2(min(s1, s2), 2.0));

  /* Bouche : trois capsules qui dessinent un sourire. Un tore serait plus
     élégant mais s'enfoncerait par les bouts sur une surface bombée. */
  float b1 = sdCapsule(p, vec3(-0.185, -0.395, 0.545), vec3(-0.075, -0.465, 0.570), 0.033);
  float b2 = sdCapsule(p, vec3(-0.075, -0.465, 0.570), vec3( 0.075, -0.465, 0.570), 0.033);
  float b3 = sdCapsule(p, vec3( 0.075, -0.465, 0.570), vec3( 0.185, -0.395, 0.545), 0.033);
  d = plusProche(d, vec2(min(min(b1, b2), b3), 2.0));

  return d;
}

vec2 carte(vec3 p) {
  return plusProche(vec2(feu(p), 1.0), visage(p));
}

vec3 normale(vec3 p) {
  /* Gradient par tétraèdre : quatre évaluations au lieu des six d'une
     différence centrée sur les trois axes. */
  const vec2 e = vec2(1.0, -1.0) * 0.0018;
  vec3 g = e.xyy * carte(p + e.xyy).x + e.yyx * carte(p + e.yyx).x
         + e.yxy * carte(p + e.yxy).x + e.xxx * carte(p + e.xxx).x;
  /* 🚨 normalize(vec3(0)) rend NaN. Le gradient s'annule là où le champ est
     plat — au point de rencontre exact de deux formes fondues, ou dans une
     zone que la borne d'optimisation d'une langue rend constante. Un seul
     pixel suffit à faire une étincelle noire qui saute d'une image à l'autre. */
  float l = length(g);
  return l > 1e-8 ? g / l : vec3(0.0, 1.0, 0.0);
}

/* Ombre douce en une seule marche : la pénombre se déduit de la distance au
   plus proche obstacle rencontrée en chemin. C'est l'astuce qui donne des
   ombres de studio pour le prix d'un rayon. */
float ombre(vec3 p, vec3 l) {
  float res = 1.0;
  float t = 0.03;
  /* 12 pas, et sur le champ du FEU SEUL — pas du visage. Ce sont les langues
     qui portent l'ombre utile ; les yeux et les sourcils, déjà noirs, n'en
     projettent aucune qu'on distingue. Ombre, occlusion, traversée et normale
     coûtent chacune une évaluation complète du champ PAR PIXEL TOUCHÉ : c'est
     là que part le budget, pas dans la marche principale. */
  for (int i = 0; i < 12; i++) {
    float h = feu(p + l * t);
    res = min(res, 10.0 * h / t);
    t += clamp(h, 0.02, 0.20);
    if (res < 0.005 || t > 2.5) break;
  }
  return clamp(res, 0.0, 1.0);
}

/* Occlusion ambiante : on compare la distance réelle à la distance parcourue
   le long de la normale. Dans un creux, la surface reste proche — donc sombre.
   C'est ce qui creuse les interstices entre les langues. */
float occlusion(vec3 p, vec3 n) {
  float occ = 0.0, poids = 1.0;
  for (int i = 0; i < 4; i++) {
    float h = 0.02 + 0.13 * float(i);
    occ += (h - carte(p + n * h).x) * poids;
    poids *= 0.72;
  }
  return clamp(1.0 - 2.2 * occ, 0.0, 1.0);
}

/* Translucidité : on sonde le champ SOUS la surface, dans la direction de la
   lumière. Là où la matière est mince — les pointes — la lumière traverse et
   la flamme s'allume par l'intérieur. Sans ça, une flamme n'est qu'un objet
   orange ; c'est ce terme qui la rend incandescente. */
float traversee(vec3 p, vec3 n, vec3 l) {
  float acc = 0.0;
  for (int i = 1; i <= 3; i++) {
    float h = 0.075 * float(i);
    acc += max(0.0, -feu(p - n * 0.01 + l * h));
  }
  return clamp(1.0 - acc * 4.2, 0.0, 1.0);
}

/* Rampe de température, en LINÉAIRE (la conversion sRGB se fait en sortie).
   L'orange de Wally (#FE7249, relevé sur wally.webm) tombe au niveau du
   VISAGE : c'est là qu'on reconnaît le personnage, le reste n'est que du feu
   autour. */
vec3 couleurFeu(float y) {
  float t = clamp((y + 1.05) / 2.50, 0.0, 1.0);
  vec3 c = mix(vec3(0.29, 0.014, 0.003), vec3(0.59, 0.042, 0.007), smoothstep(0.00, 0.18, t));
  c = mix(c, vec3(0.99, 0.166, 0.066), smoothstep(0.16, 0.38, t));
  c = mix(c, vec3(1.00, 0.263, 0.033), smoothstep(0.45, 0.62, t));
  c = mix(c, vec3(1.00, 0.381, 0.019), smoothstep(0.62, 0.74, t));
  c = mix(c, vec3(1.00, 0.545, 0.050), smoothstep(0.76, 0.88, t));
  c = mix(c, vec3(1.00, 0.744, 0.191), smoothstep(0.90, 1.00, t));
  return c;
}

/* ACES, version compacte de Krzysztof Narkowicz. Sans tone mapping, tout ce
   qui dépasse 1 est écrêté à plat et les zones éclairées virent au blanc mat —
   la signature la plus reconnaissable d'un rendu bâclé. */
vec3 aces(vec3 x) {
  return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0);
}

void main() {
  /* Ceinture ET bretelles : le filtre côté JavaScript empêche déjà d'envoyer
     une taille nulle, mais le shader ne doit JAMAIS pouvoir diviser par zéro —
     un uniforme non encore écrit vaut zéro à la première image. */
  vec2 taille = max(uTaille, vec2(1.0));
  vec2 uv = (gl_FragCoord.xy - 0.5 * taille) / taille.y;

  vec3 ro = vec3(0.0, 0.10, 3.55);
  vec3 rd = normalize(vec3(uv * 0.62, -1.0));

  /* Sphère englobante : la flamme tient dedans, donc un rayon qui la manque
     n'a rien à marcher. Sur un avatar détouré, c'est la majorité du cadre. */
  const vec3 centre = vec3(0.0, 0.10, 0.0);
  const float RAYON = 1.55;
  vec3 oc = ro - centre;
  float b = dot(oc, rd);
  float disc = b * b - (dot(oc, oc) - RAYON * RAYON);
  if (disc < 0.0) { gl_FragColor = vec4(0.0); return; }
  float racine = sqrt(disc);

  float t = max(-b - racine, 0.0);
  float tMax = -b + racine;

  /* L'anticrénelage vient de la DENSITÉ de pixels, pas d'un calcul de
     couverture : le canevas est rendu plus grand que sa taille d'affichage et
     réduit par le navigateur. La densité est ajustée en continu selon les
     images par seconde mesurées — voir la boucle côté JavaScript. */
  float mat = 0.0;
  for (int i = 0; i < 52; i++) {
    vec3 p = ro + rd * t;
    vec2 h = carte(p);
    if (h.x < 0.0009) { mat = h.y; break; }
    /* Pas volontairement raccourci : la déformation du repère qui fait monter
       le flux rend la distance légèrement SURESTIMÉE par endroits, et un pas
       trop long traverserait la surface — on verrait des trous scintillants
       dans la flamme. 15 % de marge coûtent moins qu'un artefact. */
    t += h.x * 0.85;
    if (t > tMax) break;
  }

  if (mat < 0.5) { gl_FragColor = vec4(0.0); return; }

  vec3 p = ro + rd * t;
  vec3 n = normale(p);

  vec3 lum = normalize(vec3(0.55, 0.85, 0.62));
  float diff = max(dot(n, lum), 0.0);
  /* Une surface qui TOURNE LE DOS à la lumière est déjà noire : y lancer un
     rayon d'ombre, c'est payer douze évaluations du champ pour multiplier zéro
     par un. Sur une silhouette convexe, ça retire la moitié des pixels. */
  float sh = diff > 0.0 ? ombre(p + n * 0.012, lum) : 1.0;
  float ao = occlusion(p, n);

  /* Ciel chaud / sol sombre. Un dégradé selon la normale remplace une carte
     d'environnement : la lumière arrive de partout, ce qui suffit à sortir du
     rendu « deux projecteurs » qui trahit le temps réel bâclé. */
  vec3 ciel = mix(vec3(0.10, 0.045, 0.035), vec3(0.62, 0.50, 0.42), 0.5 + 0.5 * n.y);

  vec3 albedo;
  vec3 emis = vec3(0.0);
  float rugosite;

  if (mat > 2.5) {
    albedo = vec3(0.95);                 // reflet de l'œil
    rugosite = 0.10;
    emis = vec3(0.35);
  } else if (mat > 1.5) {
    albedo = vec3(0.020, 0.008, 0.004);  // trait, un noir CHAUD
    rugosite = 0.24;
  } else {
    albedo = couleurFeu(p.y);
    rugosite = 0.40;
    /* 🚨 La flamme s'allume là où elle est MINCE — les pointes — pas là où elle
       est épaisse. traversee() vaut 1 quand la lumière passe, donc l'émission
       suit sa valeur ; la prendre à l'envers allumait tout le ventre et lavait
       la couleur en un jaune plat. */
    /* La translucidité ne se voit que sur la moitié haute, là où la matière
       est mince. En bas, le ventre est opaque : on économise trois évaluations
       du champ plutôt que de calculer un résultat qui vaudra zéro. Le fondu
       évite la ligne de démarcation qu'un simple seuil laisserait. */
    float chaud = smoothstep(-0.05, 0.30, p.y);
    float trav = chaud > 0.004 ? traversee(p, n, lum) * chaud : 0.0;
    emis = couleurFeu(p.y + 0.35) * (0.05 + 0.34 * trav);
  }

  /* 🚨 Exposition volontairement basse. Un orange saturé (rouge ≈ 1, vert ≈ 0.17)
     multiplié par plus de 1 sature d'abord le ROUGE : le vert et le bleu
     continuent alors seuls de monter, et la teinte glisse vers le saumon pâle.
     Le délavage d'un rendu trop éclairé n'est pas une affaire de goût, c'est
     cette asymétrie-là. */
  vec3 col = albedo * (ciel * ao * 0.55 + vec3(1.0, 0.93, 0.82) * diff * sh * 0.88);

  vec3 hv = normalize(lum - rd);
  float spec = pow(max(dot(n, hv), 0.0), mix(90.0, 14.0, rugosite));
  col += vec3(1.0, 0.95, 0.88) * spec * sh * (1.0 - rugosite) * 0.40;

  /* Liseré de Fresnel : c'est lui qui détache Wally d'un fond de jeu clair.
     Sans lui, un overlay disparaît dès que la scène derrière est lumineuse. */
  float fre = pow(1.0 - max(dot(n, -rd), 0.0), 3.5);
  col += vec3(1.0, 0.52, 0.20) * fre * 0.30 * ao;

  col += emis;

  col = aces(col);
  col = pow(col, vec3(1.0 / 2.2));

  /* Filet de sortie. Si une valeur non finie a malgré tout traversé, on sort
     TRANSPARENT et non noir : sur un overlay, un trou invisible passe inaperçu
     là où un rectangle noir se voit de toute la chaîne. Le test s'écrit en
     « pas ≥ 0 » parce qu'une comparaison avec un NaN est toujours fausse. */
  if (!(col.r >= 0.0) || !(col.g >= 0.0) || !(col.b >= 0.0)) {
    gl_FragColor = vec4(0.0);
    return;
  }
  gl_FragColor = vec4(col, 1.0);
}
`;

const VERTEX = /* glsl */ `
void main() { gl_Position = vec4(position.xy, 0.0, 1.0); }
`;

/**
 * Monte Wally dans un canvas et lance sa boucle d'animation.
 * Retourne `{ redimensionner, mesures, arreter }`.
 */
export function creerWally(canvas, surPanne) {
  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: false });
  renderer.setClearAlpha(0);

  /* 🚨 Le tracé de rayon coûte au PIXEL, et au carré de la densité : passer de
     1 à 2 quadruple le travail. C'était le premier poste de dépense, et une
     densité fixe est un pari sur la machine — or l'overlay tourne chez le
     streamer, à côté d'un jeu qui prend déjà le GPU.
     Elle s'ajuste donc toute seule, entre 0,6 et la densité de l'écran, d'après
     les images par seconde RÉELLEMENT mesurées : nette sur une machine qui
     suit, dégradée plutôt que saccadée sur une machine chargée. */
  const RATIO_MIN = 0.6;
  const ratioMax = Math.min(window.devicePixelRatio || 1, 2);
  let ratio = ratioMax;
  let largeurCSS = 0, hauteurCSS = 0;

  function appliquerTaille() {
    if (!(largeurCSS > 0) || !(hauteurCSS > 0)) return;
    renderer.setPixelRatio(ratio);
    renderer.setSize(largeurCSS, hauteurCSS, false);
    uniforms.uTaille.value.set(largeurCSS * ratio, hauteurCSS * ratio);
  }

  const scene = new THREE.Scene();
  /* Aucune caméra 3D : la caméra vit dans le shader (origine + direction du
     rayon). Celle-ci ne sert qu'à couvrir l'écran d'un rectangle. */
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);

  const uniforms = {
    uTaille: { value: new THREE.Vector2(1, 1) },
    uTemps: { value: 0 },
  };
  const materiau = new THREE.ShaderMaterial({
    vertexShader: VERTEX,
    fragmentShader: FRAGMENT,
    uniforms,
    transparent: true,
    depthTest: false,
    depthWrite: false,
  });
  scene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), materiau));

  /* `performance.now()` plutôt que `THREE.Clock`, déprécié en r185. Une horloge
     de trois lignes ne mérite pas une dépendance de plus. */
  const depart = performance.now();
  let anim = 0;
  let coutImage = 0;
  let precedente = 0;
  /* Compté et AFFICHÉ, pas seulement corrigé : le défaut ne se reproduit pas
     sur la machine de développement. Si le clignotement persiste malgré le
     filtre, ce compteur dira si la cause est bien là — ou s'il faut chercher
     ailleurs. Un correctif qu'on ne peut pas confirmer n'est qu'une hypothèse. */
  let mesuresNulles = 0;
  let imagesDepuisReglage = 0;

  /* 🚨 Un contexte WebGL peut être perdu à tout moment sans que rien ne lève :
     pilote qui redémarre, veille, mémoire vidéo réclamée par le jeu. Le canevas
     reste alors là, FIGÉ OU NOIR — et un trou noir en plein live est pire que
     pas d'avatar du tout. `preventDefault()` autorise une restauration, mais on
     ne l'attend pas : on prévient tout de suite pour retomber sur la vidéo.
     Le cas est réel, il s'est présenté pendant la mise au point. */
  canvas.addEventListener("webglcontextlost", (e) => {
    e.preventDefault();
    cancelAnimationFrame(anim);
    if (surPanne) surPanne("contexte WebGL perdu");
  });

  function boucle() {
    anim = requestAnimationFrame(boucle);
    const maintenant = performance.now();
    uniforms.uTemps.value = (maintenant - depart) / 1000;
    renderer.render(scene, camera);

    /* 🚨 On mesure l'INTERVALLE entre deux images, pas la durée de l'appel de
       rendu. Le tracé de rayon se fait entièrement sur le GPU : `render()`
       ne fait qu'empiler des commandes et revient en quelques microsecondes —
       le chronométrer affichait « 0,0 ms », un chiffre rassurant et faux.
       L'intervalle, lui, inclut l'attente de la présentation, donc le dessin.
       La première image est écartée : elle porte la compilation du shader. */
    if (precedente > 0) {
      const dt = maintenant - precedente;
      coutImage = coutImage > 0 ? coutImage * 0.9 + dt * 0.1 : dt;
    }
    precedente = maintenant;

    /* Ajustement de la densité, une fois toutes les 45 images : assez rare pour
       que la moyenne glissante ait le temps de se refaire entre deux décisions,
       sinon la densité oscille au lieu de converger. Les deux seuils sont
       volontairement écartés (22 ms ≈ 45 im/s, 11 ms ≈ 90 im/s) — une bande
       morte entre eux, sans quoi on monte et redescend à chaque mesure. */
    if (++imagesDepuisReglage >= 45 && coutImage > 0) {
      imagesDepuisReglage = 0;
      let vise = ratio;
      if (coutImage > 22 && ratio > RATIO_MIN) vise = Math.max(RATIO_MIN, ratio * 0.8);
      else if (coutImage < 11 && ratio < ratioMax) vise = Math.min(ratioMax, ratio * 1.15);
      if (vise !== ratio) {
        ratio = vise;
        appliquerTaille();
        /* La mesure repart de zéro : garder l'ancienne moyenne ferait juger la
           nouvelle densité sur le coût de l'ancienne. */
        coutImage = 0;
        precedente = 0;
      }
    }
  }

  function redimensionner(largeur, hauteur) {
    /* 🚨 Un ResizeObserver se déclenche AUSSI avec une taille nulle : onglet
       masqué, élément en display:none, source redimensionnée dans OBS. Sans ce
       filtre, uTaille tombe à zéro, la division qui donne la direction du rayon
       produit des NaN — et un NaN ment sur la comparaison d'arrêt de la marche.
       Selon le pilote, elle répond « touché », le shader ombre du vide, et
       clamp(NaN) sort NOIR OPAQUE sur tout le cadre. C'est l'explication du
       clignotement : une image sur deux part d'une mesure vide. */
    if (!(largeur > 0) || !(hauteur > 0)) { mesuresNulles++; return; }
    largeurCSS = largeur;
    hauteurCSS = hauteur;
    appliquerTaille();
  }

  boucle();
  return {
    redimensionner,
    /** Intervalle moyen entre deux images, en millisecondes — donc le coût
     *  réel, dessin compris. 16,7 ms = 60 images par seconde. `densite` est la
     *  densité de pixels retenue par l'ajustement automatique, `nulles` compte
     *  les redimensionnements à taille vide interceptés. */
    mesures: () => ({ ms: coutImage, densite: ratio, nulles: mesuresNulles }),
    arreter() {
      cancelAnimationFrame(anim);
      materiau.dispose();
      renderer.dispose();
    },
  };
}
