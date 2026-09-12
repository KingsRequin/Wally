# Les `Notes` de la base Notion « 🃏 Cartes du Purgatoire », sauvegardées avant
# suppression de la colonne, le 2026-09-12.
#
# ⚖️ L'owner : « les notes servent à rien concrètement, on s'en fout d'avoir
# l'historique des modifs ». Il a raison sur l'historique : git le fait déjà, et
# mieux — chaque commit porte son changement daté. Ce qui vaut d'être relu ici
# n'est PAS l'historique : c'est l'ORIGINE de chaque ref (le verbatim du chat, qui
# l'a dite et quand), qui est le critère d'entrée d'une carte dans une saison et
# que git n'a nulle part ; et les CONSÉQUENCES encore ouvertes, qui parlent du
# futur et pas du passé.
#
# 🚨 Ne pas rouvrir ce fichier pour opposer une règle à l'owner : ce qui fait foi
# est la base Notion, puis les YAML. Ceci est une archive.

## 10 pizzas géantes

Ligne créée le 2026-09-11 : la carte existait dans le design des tactiques mais n'avait aucune ligne en base. TACTIQUE · coût à définir : rend 4 PV à tous tes héros.

Règle gardée au tri du 2026-09-11 par l'owner. Illustration : la pizza de game-icons semée dix fois dans la fenêtre, tailles et angles tirés d'une graine fixe.

⚠️ Le coût est à 0 comme toutes les tactiques depuis le tri — à calibrer. Un soin de zone de 4 PV est la carte la plus large du lot soin ; elle mérite probablement le haut du barème.

## Aim assist = aimbot

⚖️ RÉÉCRITE LE 2026-09-12 avec l'owner, et elle CHANGE DE SOUS-TYPE : PASSIF (était ACTION). Coût NON CALIBRÉ.

EFFET : tant qu'elle est en jeu, les héros adverses ne peuvent plus esquiver — leurs chances d'esquive tombent à zéro.

🆕 PREMIER CONTRE À L'ESQUIVE DU JEU. Jusqu'ici aucune carte ne répondait à une stat défensive aléatoire : on pouvait en donner, jamais en retirer.

⚖️ ELLE PEUT NE SERVIR À RIEN, ET C'EST VOULU — arbitrage de l'owner du 2026-09-12 : « c'est fait pour. L'intérêt du jeu c'est de composer son deck : soit on prend le risque de pas contrer l'esquive, soit on ne prend pas le risque mais du coup on a une carte qui peut ne servir à rien. » Ne PLUS signaler comme un défaut qu'une carte dépende du deck d'en face : c'est le pari de construction, et c'est la décision intéressante que le jeu demande au joueur.

⚖️ POURQUOI PASSIF : arbitrage de l'owner du 2026-09-12 — « les passifs se déclenchent tout seuls, les actions c'est le joueur qui les déclenche ». L'annulation s'applique d'elle-même tant que la carte est là. ⚠️ Le cadre de la carte passe au crème PASSIF.

❓ NON TRANCHÉ : pose face visible (donc destructible) ou non. Le camion de Raiky et Mozambique sont tous deux face visible ; celle-ci n'a pas été dite. À régler une fois pour tous les passifs, pas carte par carte.

Origine : le meme The Office « they're the same picture », signé Taki.

(Ancienne version, écartée au tri du 2026-09-11 : « copie l'Attaque de ton héros le plus fort sur un autre des tiens ce tour, dans la limite de +5 ».)

## Amitié

⚖️ RÉÉCRITE ET RENOMMÉE LE 2026-09-12 avec l'owner. ACTION · coût NON CALIBRÉ.

TITRE : AMITIÉ (était « Push par 3 teams »). SOUS-TITRE : « Pouvoir de l'amitié ! »
EFFET : augmente l'Attaque d'UN SEUL héros du poseur, et l'Aura de TOUS.

⚠️ ORTHOGRAPHE CORRIGÉE À LA SAISIE : l'owner a écrit « Amitier » / « amitier ». Écrit « Amitié » sur la carte — même précédent que « steak haché » contre « streak hacher » : le nom d'une carte est ce que les joueurs liront, et le titre est en gros à l'écran. À remettre tel quel si la faute était voulue.

🚨 LA CARTE N'A PLUS RIEN À VOIR AVEC SON VISUEL. L'illustration est toujours le meme de la vache hébétée (carte-push-3-teams.png), qui illustrait « se faire push par 3 teams ». Le titre, le sous-titre et l'effet parlent maintenant d'amitié et d'Aura partagée. Le pochoir est à refaire, ou le lien est à écrire.

❓ SA CATÉGORIE EST À TRANCHER, comme celle de « Flatline ». Elle est rangée en SOIN (bandeau vert) depuis la planche du design, mais son effet est de l'AURA et de l'Attaque — aucun soin. Laissée en SOIN en attendant : le design fait foi tant qu'on ne le contredit pas exprès.

🎁 ELLE COMBLE LA FAMILLE LA PLUS PAUVRE DU JEU. « Aura et coopération » n'avait presque rien ; celle-ci donne de l'Aura à TOUTE la ligne, ce qu'aucune autre ne fait à ce jour à part « Apéro chez Zeddo ».

(Ancienne version, écartée au tri du 2026-09-11 : « tu choisis lequel de tes héros encaisse TOUTES les attaques adverses ce tour ». Origine : le meme de la vache hébétée.)

## Apéro chez Zeddo

Demandée par l'owner le 2026-09-04.

## Azraël

Le streamer, seul Archange du serveur. Budget 20 = 12 + 8 (Archange).

🚨 2026-09-10 — SON ULTIME EST RÉÉCRIT, sur arbitrage de l'owner : « rework l'ult d'azra : quand il utilise son ult il peut utiliser celui d'un personnage au choix sur le plateau, ce qui fait qu'à chaque activation il peut changer ».

Nouveau F07 Rework — Ultime, à la résolution : désigne un héros SUR LE PLATEAU, allié ou adverse ; Azraël déclenche L'ULTIME DE CE HÉROS à sa place. Le choix se refait à chaque activation.

L'ancien Rework AFFAIBLISSAIT une cible (« son Ultime coûte +3, tous ses nombres baissent de 2 ») ; celui-ci EMPRUNTE. La ref au rework de Fuse survit — un rework change ce qu'un personnage sait faire — mais elle vise désormais Azraël lui-même, pas sa victime. Répercuté dans tcg/cartes.yaml et dans le catalogue des Réflexes (F07).

Quatre cas que le moteur doit trancher : (1) Azraël paie SON coût d'Ultime (10), jamais celui du héros copié ; (2) il emprunte l'EFFET, pas les nombres du porteur — un Ultime qui lit l'Attaque lit celle d'Azraël, sinon l'entrée devient proportionnelle donc cassée ; (3) il peut copier l'Ultime d'un ALLIÉ, et c'est voulu — c'est ce qui le rend intéressant en coop contre Wally ; (4) aucun état ne persiste sur la cible.

Prix 6 inchangé : plancher 5 pour ce qui touche à une mécanique signature (ici l'Ultime), × 1,25 parce qu'il peut emprunter à l'adversaire → 6,25 → 6. 🎁 Le plafond que le barème exige est STRUCTUREL : aucune entrée du catalogue ne dépasse 6, donc ce que F07 peut emprunter est borné par le catalogue lui-même. Il tombe le jour où une entrée à 7 est ajoutée — seule chose à surveiller ici.

⚠️ 2026-09-10 — SES CHIFFRES RESTENT À REFAIRE. Les 5/10/5 et le coût 10 posés le 2026-09-07 sortaient de la formule (z-scores sur 65 personnes). L'owner a retiré la mémoire de la fabrication : les stats s'écrivent à la MAIN, seule contrainte Attaque + PV + Aura = 20. Seul son COÛT (10) est à reposer — mais 10 reste défendable : c'est le coût maximum pour l'Ultime le plus flexible du jeu.

ILLUSTRATION — décrite par Azraël lui-même le 2026-09-06 : skin prestige, explosion dans le dos, colorimétrie orange / noir / blanc avec touches de gold.

⚠️ Faction à poser à la main par l'owner, toujours vide.

## Azraël met ta perk !

Pack 2 du 2026-09-10, demandée par l'owner.

EFFET : À ÉCRIRE (hasard pur).

Origine : le meme rangé de la mouette qui inspire (Inhaling Seagull) puis hurle « azrael met ta perk !!!! ».

⚖️ 2026-09-12 — L'OWNER AVAIT RAISON DEPUIS LE DÉBUT. Il l'avait demandée comme « un pourcentage de chance d'oublier d'attaquer », et j'avais opposé l'arbitrage « le hasard est tiré et affiché avant la pose » pour l'accrocher au Tirage. Cet arbitrage est MORT : hasard PUR, pourcentage porté par la carte, résolu au moment de l'effet. L'ancien effet « état OUBLIE, il n'attaque pas si le Tirage ≤ 3 » est supprimé, et l'état Oublie est à redéfinir comme un simple pourcentage.

🎁 Ne nomme personne au sens du consentement — Azraël est l'owner.

## Belle bite

Idée de l'owner, versée de sa page le 2026-09-12, verbatim : « belle bite [passif] : ajoute de l'aura ». PASSIF · coût à définir.

⚠️ Ni la valeur d'Aura, ni la cible (un héros allié ? tous ?), ni la durée ne sont écrites — à trancher par l'owner. Le coût vient APRÈS la puissance (règle owner du 2026-09-12).

🎁 Tombe dans « Aura et coopération », la famille la moins fournie du paquet — 5 cartes contre 15 en Attaque.

🎁 Ne nomme personne — hors du point dur du consentement.

## Bloodshade.Hyjal

Retenue au tri de l'owner du 2026-09-10. Stats à écrire à la MAIN — Attaque + PV + Aura = 12 + bonus de rareté.

## ClakerNoJutsu

Retenue au tri de l'owner du 2026-09-10. Stats à écrire à la MAIN — Attaque + PV + Aura = 12 + bonus de rareté.

⚠️ 2026-09-10 : « Iron d'aile » (discord:1172453915825016852) est la MÊME personne — confirmé par l'owner. Sa ligne passe en doublon fusionné. Les deux comptes ne sont PAS liés en base.

⚠️ Sa carte est déjà dans tcg/cartes.yaml (8 · 5/4/3) et rareté « Âme » posée par défaut : ces chiffres viennent de l'ancien modèle Voix/Aura/Piquant, à revoir. Faction laissée vide — ni le grade Twitch ni le rôle Discord ne sont lisibles aujourd'hui (scopes absents).

## Codage à la Requin

⚖️ RÉÉCRITE LE 2026-09-12 avec l'owner. ACTION · coût NON CALIBRÉ.

EFFET : reste sur le plateau et se relance à chaque tour, elle ne se défausse JAMAIS. Elle a 50 % de blesser un héros adverse ; sinon c'est un des héros du poseur, TIRÉ AU HASARD, qui prend la MOITIÉ de ces dégâts.

⚠️ LE RATÉ COÛTE LA MOITIÉ, PAS LE TOUT. Verbatim de l'owner, correction de sa propre formulation : « la carte a genre 50 % de chance d'infliger 10 de dégâts à l'ennemi ; si ça rate, le joueur prend 5 de dégâts (pas 10, c'est my bad) sur un héros au hasard. »

⚠️ SEUL LE TAUX EST CALIBRÉ (50 %, écrit en stat). Les dégâts ne le sont pas — et il faudra décider si la moitié s'arrondit au supérieur ou à l'inférieur sur un nombre impair. Le totem tranche déjà « arrondie au supérieur » de son côté : à dire une seule fois pour tout le jeu, pas carte par carte.

🆕 DEUXIÈME CARTE RÉUTILISABLE, après « Le camion de Raiky », et la même forme : elle reste en jeu, le joueur la relance, et le prix est un risque pour son propre camp. ⚠️ Différence à tenir : le camion AGGRAVE son risque à chaque usage et ne redescend jamais, celle-ci reste à 50 % pour toujours. Si les deux finissent équivalentes à la calibration, le camion n'a plus de raison d'exister.

🎁 « Ça compile ou ça casse » est rendu littéralement : on relance la compilation autant qu'on veut, et une fois sur deux ça pète à la figure.

⚠️ Hasard PUR. L'ancien effet à trois paliers de Tirage (≥ 5 / ≤ 2 / sinon) est mort avec le Tirage. L'entrée de catalogue « I03 Ça compile ou ça casse » disparaît avec.

## De l'air

« Tu manges quoi à midi ? — De l'air 😅 ». Demandée par l'owner le 2026-09-04.

## Fitoum

AJOUTÉE au tri du 2026-09-10 — demandée par l'owner dans sa liste perso. « Une personne pas vraiment de la commu d'Azraël, mais il est très drôle » (owner). Stats à écrire à la MAIN — Attaque + PV + Aura = 12 + bonus de rareté.

⏸️ À fournir par l'owner : son pseudo Discord/Twitch s'il en a un, et de quoi écrire la carte (personnage, ultime, texte d'ambiance). Wally ne le connaît pas — 4 occurrences dans tous les logs, toujours comme interjection lancée par d'autres (mks_zedd, Rhao).

## Flatline

⚖️ RÉÉCRITE LE 2026-09-12 avec l'owner. PASSIF · coût NON CALIBRÉ.

TITRE : Flatline. SOUS-TITRE : « vous avez vu mon skin de flatline ? »
EFFET : ajoute de l'Aura à un héros au hasard.

⚠️ ELLE A PERDU LE NOM D'AZRAËL. « La Flatline d'Azraël » devient « Flatline », et la ref passe dans le sous-titre sous forme de réplique. Une entrée de moins qui nomme une personne.

❓ SA CATÉGORIE EST À TRANCHER. Elle est rangée en ATTAQUE (bandeau rouge) depuis la planche du design, mais son effet est maintenant de l'AURA (bandeau baie). Le bandeau dit la catégorie, et un joueur qui lit « attaque » sur une carte qui donne de l'aura est induit en erreur — c'est exactement ce que les deux dimensions type/catégorie servent à éviter. Laissée en ATTAQUE en attendant l'arbitrage : le design fait foi tant qu'on ne l'a pas contredit exprès.

⚠️ Le héros est TIRÉ AU HASARD, le joueur ne le choisit pas — même parti pris que « Le cluster ». Hasard PUR, aucun dé.

Origine : « c'est LE flatline » · « tu croises plus de hemlock que de flatline, ce jeu est si cruel ».

(Ancienne version, écartée au tri du 2026-09-11 : « +4 d'Attaque à un héros allié, pour toute la partie ».)

## Iron d'aile

Fusionnée dans « ClakerNoJutsu » — confirmé par l'owner le 2026-09-10 : c'est la même personne. Ligne gardée pour la trace, une seule carte existe. Comptes : discord:1172453915825016852 (58 faits) + twitch:526656325 (513). ⚠️ Non liés en base — même raison que Taki : lier sans déplacer les faits en rendrait la majorité invisibles.

## KassandreYunikon

Retenue au tri de l'owner du 2026-09-10. Stats à écrire à la MAIN — Attaque + PV + Aura = 12 + bonus de rareté.

## KingsRequin

Retenue au tri de l'owner du 2026-09-10. Stats à écrire à la MAIN — Attaque + PV + Aura = 12 + bonus de rareté. L'owner de ce dépôt — distinct d'Azraël, tranché le 2026-09-04. A aussi une carte-objet « Codage à la Requin ».

## L'anti-cheat

Pack 4, 2026-09-10. Seule ref retenue du pack.

Origine : le meme rangé Homer/Marge — Homer en sous-vêtements exhibe « ANTI CHEAT D'APEX VUE DE LA PLÈBE », Marge répond « ANTI CHEAT VUE DES CHEATEUR ». Le gag est le CONTRASTE : redoutable vu d'en bas, ridicule vu d'en haut.

✅ Très bien partagée : 40 personnes distinctes, 98 occurrences sur cheat/triche. C'est le meilleur score du pack 4, et le 2e de toutes les refs relevées après « les PP du samedi » (42).

🎁 Ne nomme personne — hors du point dur du consentement.

🎁 Un second meme rangé porte la même ref : Simpsons, Moe « APEX » jette le sac « CHEATERS » dehors et le retrouve derrière lui. Deux memes indépendants sur le même sujet = la ref est solide, mais c'est UNE carte, pas deux.

⚠️ Le gag est un contraste entre deux points de vue : un effet qui vaut beaucoup pour l'un et rien pour l'autre. À écrire par l'owner.

## La manette

⚖️ RÉÉCRITE LE 2026-09-12 avec l'owner. PASSIF · coût NON CALIBRÉ.

EFFET : tant qu'elle est en jeu, TES héros ont une chance d'infliger un coup critique.

🚨 RÈGLE D'ÉQUILIBRAGE POSÉE PAR L'OWNER LE 2026-09-12 : « Mozambique devrait donner plus de chance de critique que la manette, c'est comme ça qu'on balance. » Le taux de CETTE carte est donc le PLANCHER : strictement inférieur à celui de « Mozambique here! », qui donne le même critique mais aux DEUX camps. Les deux se calibrent ensemble, jamais séparément — si les taux finissent égaux, l'une des deux ne sert plus à rien.

⚠️ Dépersonnalisée au tri du 2026-09-10 : « Claker joue à la manette » est retiré. C'est un OBJET, plus une ref à quelqu'un.

⚖️ L'ancien effet « si le Tirage du tour ≥ 4, tes héros frappent DEUX FOIS » est mort avec le Tirage (2026-09-12). Le critique reste l'idée d'origine — c'était déjà « I01 Critique » — mais il est maintenant un pourcentage PUR porté par la carte, sans seuil ni dé.

🎁 Ne nomme personne.

## La statue de Mirage

Pack de l'owner du 2026-09-10, réécrite le 2026-09-11. PASSIF À REGROUPER · 1 d'énergie : une fois les TROIS réunies et regroupées, tes cartes de soin ne coûtent plus rien.

✅ LE DÉFAUT « ELLE GONFLE LE DECK DE 12 À 15 » EST FERMÉ. Arbitrage de l'owner du 2026-09-11 : une seule carte est comptée dans le deck, elle verse ses deux sœurs au moment d'être jouée, chaque sœur récupérée occupe un emplacement de passif, et les trois se regroupent en une seule à l'arrivée de la troisième. Le deck reste à 12.

Mécanique du REGROUPEMENT définie une fois au §4 de 2026-09-05-tcg-tactiques-saison-1.md — partagée avec « Le Rhum », pas réinventée ici.

Origine : la statue de Mirage. 🎁 Croise « Le mode diva » — Kassandre exige déjà une statue pour son entrée royale.

Prix : le soin gratuit pour le RESTE DE LA PARTIE (la carte regroupée est un passif permanent) ≈ 9 points, × 0,5 pour une condition très longue → 4,5 → 2, ramené à 1 parce que deux des trois emplacements de passif sont immobilisés pendant toute la collecte. Seul endroit du barème où un coût d'OCCUPATION entre dans le prix — justifié, le Regroupement étant la seule mécanique qui fait payer en emplacements plutôt qu'en énergie.

⚠️ Même point de calibration que le Rhum : pari sur la durée de la partie.

## Le Rhum

Pack de l'owner du 2026-09-10, réécrite le 2026-09-11, sous-titre posé le 2026-09-12.

TITRE : RHUM. SOUS-TITRE : « Un petit cadeau de Zeddo » (owner, 2026-09-12).
EFFET : PASSIF À REGROUPER · chaque Rhum en jeu fait perdre 1 PV tous les 5 tours à son porteur. Les TROIS regroupées donnent 50 % d'esquive. Les trois valeurs sont en stats, réglables sans toucher au texte.

✅ LE « SI 3 RÉUNIS » EST RÉTABLI. Je l'avais déclaré injouable (2 emplacements de passif, deck de 12) et écrit la carte sans lui. Arbitrage de l'owner du 2026-09-11 : une seule carte comptée dans le deck, elle verse ses deux sœurs au moment d'être jouée, chaque sœur récupérée occupe un emplacement, et les trois se regroupent IMMÉDIATEMENT à l'arrivée de la troisième — c'est ce qui évite d'avoir besoin d'un 3e emplacement.

🎁 CARTE LA PLUS FIDÈLE DU PAQUET, et c'est la mécanique qui l'a rendue telle : un seul Rhum ne fait que du mal à son porteur, il en faut trois pour que ça serve, et ce qui sert c'est d'être difficile à toucher.

🆕 Le sous-titre lui donne un DONNEUR sans la renommer : « Un petit cadeau de Zeddo ». Zeddo a déjà « Apéro chez Zeddo » — deux entrées, mais celle-ci ne le met que dans le sous-titre.

⚠️ SEULE SOURCE D'ESQUIVE DU JEU avec « Tenma » (sous condition). Elle est donc la cible directe de « Aim assist = aimbot », qui met toutes les esquives adverses à zéro : les trois se calibrent ensemble.

⚠️ Premier point de calibration, avant le prix : une carte à regrouper est un PARI SUR LA DURÉE DE LA PARTIE. Si les parties de test sont courtes, elle ne se complète jamais.

Origine : « le rhum là » · « ya du rhum ? »

## Le baril de Caustique

Pack de l'owner du 2026-09-10. TACTIQUE, SE JOUE FACE CACHÉE · 2 d'énergie : 1 dégât à TOUS les héros — les tiens compris — au début de chacun des 3 prochains tours.

Origine : Caustique.

Prix : ~3 dégâts par camp sur 3 tours, mais SYMÉTRIQUES — pas de × 1,25, il frappe aussi les siens → 4 → plafond(4/3) = 2 d'énergie.

🆕 UNE DES TROIS CARTES QUI FONT REVENIR L'ANONYME — et c'est elle qui a servi à trancher ses deux questions ouvertes, le 2026-09-11 :

✅ PV = SON COÛT EN ÉNERGIE, donc 2 ici. Valeur DÉRIVÉE (« donner à la carte face cachée le même nombre de PV que l'énergie qu'elle coûte », owner) : rien à calibrer, toute carte cachée future en hérite. 🚨 MAIS LES PV NE SONT PAS AFFICHÉS — sinon ils disent le coût, et le coût est le plus gros indice sur ce que contient une carte cachée. Cachés, on frappe sans savoir si le coup suffit.

✅ DÉTRUITE : révélée puis défaussée, SON EFFET NE PART PAS. L'attaquant a frappé du carton au lieu d'un héros — les deux camps perdent quelque chose. L'autre option se referme sur elle-même : si l'effet partait en mourant, attaquer serait toujours un mauvais coup, donc personne ne le ferait, donc la face cachée redeviendrait gratuite.

🎁 SON GAG SURVIT QUAND MÊME, SANS EXCEPTION À ÉCRIRE. Son effet démarre au début du tour suivant : elle est cachée pendant EXACTEMENT UN tour adverse. C'est la fenêtre pour la désamorcer ; ratée, elle se révèle en explosant toute seule. Le baril finit toujours par partir, on a juste eu une chance de couper le fil.

🎁 Ne nomme personne.

## Le baril de soins

Pack de l'owner du 2026-09-10. PASSIF · coût non calibré : tant qu'il est en jeu, TOUT baril posé soigne au lieu de blesser — y compris ceux de l'adversaire, s'il en a mis dans son deck et le joue.

Origine : le baril d'Apex, l'autre usage.

🎁 PREMIÈRE CARTE DU JEU QUI MODIFIE UNE AUTRE CARTE plutôt que des héros. Elle ouvre une couche de contre-jeu que le paquet n'avait pas.

⚖️ ELLE PEUT NE SERVIR À RIEN SI PERSONNE NE JOUE DE BARIL, ET CE N'EST PAS UN DÉFAUT — arbitrage de l'owner du 2026-09-12 : « c'est fait pour. L'intérêt du jeu c'est de composer son deck : soit on prend le risque, soit on ne le prend pas mais du coup on a une carte qui peut ne servir à rien. » (La note précédente le comptait comme un défaut à corriger, avec « Michel-Velux » et « Quoi → FEUR ». C'était faux.)

## Le camion de Raiky

⚖️ RÉÉCRITE LE 2026-09-12 avec l'owner. ACTION · coût NON CALIBRÉ (squelette sans stats, on chiffre quand toutes les cartes sont écrites).

EFFET : reste sur le plateau, FACE VISIBLE, et se relance à chaque tour. Elle blesse un héros adverse, puis un des tiens en ligne, TIRÉ AU HASARD, encaisse le contrecoup. Le risque et le contrecoup montent à chaque utilisation et NE REDESCENDENT JAMAIS de la partie.

⚠️ ELLE RESTE UNE ACTION, pas un passif, malgré la pose sur le plateau. Arbitrage de l'owner du 2026-09-12 : « les passifs se déclenchent tout seuls, les actions c'est le joueur qui les déclenche ». Une carte posée qu'on relance soi-même est une ACTION.

⚠️ FACE VISIBLE OBLIGATOIRE, et ce n'est pas le défaut : depuis le 2026-09-12 toute action peut se poser face cachée. Celle-ci ne le peut pas — ses compteurs (risque, dégâts du contrecoup) sont écrits sur la carte et doivent être lus par les deux joueurs.

⚠️ Le hasard est PUR, résolu au moment de l'usage. Aucun Tirage, aucun dé.

Origine : son pseudo ENTIER — « Raiky le fusible de camion ». Le compteur qui ne redescend jamais EST le fusible.

⚠️ Nomme Raiky, qui a déjà « Raiky dans l'anneau » ET une carte-héros. Trois entrées pour une personne — point dur du consentement.

(Ancienne version, écartée au tri du 2026-09-11 : « 4 dégâts à un héros adverse », l'étalon sans clause du paquet. Le paquet n'a donc plus de carte-étalon simple — à surveiller.)

## Le care package

Pack de l'owner du 2026-09-10. TACTIQUE · 2 d'énergie : pioche 3 cartes, garde-en 1, remets les autres AU-DESSUS de ta pioche.

Origine : le ravitaillement d'Apex.

Prix : +1 carte nette (2 points) plus la sélection sur trois (≈ 2 points de qualité) → 4 → plafond(4/3) = 2 d'énergie.

Remettre les deux autres AU-DESSUS et non dessous est ce qui la garde honnête : on sait ce qui arrive, l'adversaire aussi.

🎁 Ne nomme personne.

## Le clavier-souris

⚖️ RÉÉCRITE LE 2026-09-12 avec l'owner. PASSIF · coût NON CALIBRÉ.

EFFET : tant qu'elle est en jeu, les héros du poseur ont 20 % de chance d'esquiver une attaque. Le taux est en stat, réglable sans toucher au texte.

🚨 ÉCHELLE D'ESQUIVE DU JEU, posée par l'owner le 2026-09-12 : « elle donne genre 10 ou 20 % d'esquive, moins que le rhum du coup. » L'ordre à tenir, et à ne jamais casser en calibrant une carte isolément :
· LE CLAVIER-SOURIS — 20 %, sans condition, tout de suite. Le plancher.
· LE RHUM — 50 %, mais seulement une fois les TROIS réunies, et chaque porteur perd des PV en attendant.
· TENMA — « fortement accru », mais seulement quand il ne reste qu'UN héros. Le plus fort taux paie la condition la plus dure.
La règle générale qui s'en dégage : plus la condition est dure, plus le taux monte. Une carte sans condition reste au plancher.

⚠️ Les trois sont éteintes d'un coup par « Aim assist = aimbot », qui met toutes les esquives adverses à zéro. Les quatre cartes se calibrent ensemble.

⚠️ 10 OU 20 % N'EST PAS TRANCHÉ — l'owner a donné une fourchette. 20 % est posé comme valeur de départ, pas comme décision.

⚠️ Dépersonnalisée au tri du 2026-09-10 : « oyoloyoo n'a jamais joué à la manette » est retiré. C'est un OBJET, plus une ref à quelqu'un.

⚖️ L'ancien effet « si le Tirage ≥ 3, tes héros ignorent les dégâts de zone » est mort avec le Tirage (2026-09-12). L'esquive reste l'idée d'origine — c'était déjà « I02 Esquive » — mais c'est maintenant un pourcentage PUR, sans seuil ni dé.

🎁 PENDANT EXACT DE « La manette » : deux objets dépersonnalisés, l'un donne du critique à son camp, l'autre de l'esquive. À garder symétriques.

## Le cluster

⚖️ RÉÉCRITE LE 2026-09-12 avec l'owner. ACTION · coût NON CALIBRÉ (squelette sans stats).

EFFET : tu ne choisis AUCUNE cible. Elle frappe un héros adverse tiré au hasard, puis rebondit sur un autre, tiré au hasard lui aussi, et ainsi de suite en faisant moins de dégâts à chaque rebond. Elle s'arrête au premier rebond raté.

⚠️ LE HASARD EST COMPLET, et c'est la demande explicite de l'owner : « au hasard complet, on ne choisit pas le héros ». La PREMIÈRE cible est tirée elle aussi — pas seulement les rebonds. Aucune étape de la carte ne laisse une décision au joueur.

⚠️ Hasard PUR résolu au moment de l'effet, aucun dé, aucun Tirage.

⚠️ À CALIBRER : la chaîne de rebonds n'a pas de borne écrite. C'est le piège « aucun multiplicateur sans plafond » — une suite de rebonds heureux peut valoir plusieurs fois le prix payé. Le garde-fou naturel est la décroissance des dégâts à chaque rebond, à vérifier en partie de test.

Origine : la grenade à fragmentation d'Apex. 6 personnes.

(Ancienne version, écartée au tri du 2026-09-11 : « 4 dégâts répartis au hasard entre les héros adverses, jamais plus de 2 sur le même ».)

🎁 Ne nomme personne.

## Le drone de Crypto

Pack de l'owner du 2026-09-10. TACTIQUE · 2 d'énergie : regarde la main de l'adversaire jusqu'à la fin du tour.

✅ Origine : Crypto. 25 personnes, 121 occurrences — LA RÉF LA MIEUX PARTAGÉE DU PACK.

Prix : de l'information pure, elle ne retire rien — 4 points, pas de × 1,25 → plafond(4/3) = 2 d'énergie.

🚨 EN COOP, CETTE CARTE VISE WALLY — et c'est la vue censurée en face. Wally connaît sa main ; s'il doit la montrer, c'est le MOTEUR qui la rend, pas le modèle. L'état public envoyé au juge et la main révélée aux joueurs sont deux choses distinctes, et les confondre se lit comme de la triche dans un sens ou dans l'autre.

⚠️ Combo à surveiller : enchaîné avant « Le shop de Loba », il transforme un vol au hasard en vol au choix. Seul combo à deux cartes du paquet.

🎁 Ne nomme personne.

## Le leurre

Pack de l'owner du 2026-09-10. TACTIQUE · 2 d'énergie : double un de tes héros en jeu ; une seule des deux copies est vraie. Attaquer la fausse la détruit et COÛTE LE TOUR de l'attaquant.

Origine : le leurre de Mirage. 5 personnes au chat.

Prix : annule une attaque (≈ 4 points) × 1,25 parce qu'il fait perdre son tour à l'adversaire → 5 → plafond(5/3) = 2 d'énergie.

⚠️ Repose sur de l'INFORMATION CACHÉE EN JEU, même famille que les cartes face cachée. Le moteur doit pouvoir dire lequel est vrai sans jamais le montrer, ET l'écrire au journal d'événements — sinon un leurre deviné devient indiscernable d'un bug.

## Le meme de la commu

Demandée par l'owner le 2026-09-04. ⚠️ 2026-09-10 : elle n'a JAMAIS reçu d'effet ni de prix — elle ne figure dans aucune des 17 tactiques de la saison 1. Elle existe donc en titre seulement. À écrire ou à retirer, mais pas à laisser dans cet état : une ligne sans effet ne se voit pas manquer.

## Le scan de Seer

Pack de l'owner du 2026-09-10. TACTIQUE · 3 d'énergie : désactive TOUS les passifs adverses pendant 2 tours.

Origine : le drone qui scanne. 14 personnes sur « scan », 25 sur « crypto ».

Prix : neutraliser jusqu'à 2 passifs pendant 2 tours ≈ 6 points × 1,25 → 7,5 → plafond(7,5/3) = 3 d'énergie.

🚨 C'EST UN CONTRE DIRECT AUX 12 PASSIFS DU PAQUET, DONT 5 ARRIVÉS LE MÊME JOUR. Une carte anti-passif dans un paquet qui vient de doubler ses passifs se calibre EN MÊME TEMPS QU'EUX, jamais après : si elle est trop bonne, elle tue « Le totem », « Lifeline », « Le Rhum » et « La Flatline » d'un seul coup.

🎁 Ne nomme personne.

## Le shop de Loba

Pack de l'owner du 2026-09-10. TACTIQUE · 2 d'énergie : prends UNE CARTE AU HASARD dans la main de l'adversaire.

Origine : Loba. 19 personnes, 40 occurrences.

Prix : +1 carte pour toi (2) et −1 pour lui (2) × 1,25 → 5 → plafond(5/3) = 2 d'énergie.

⚠️ AU HASARD, PAS AU CHOIX — l'owner a précisé « main adverse face cachée » et il a raison. Choisir dans une main révélée vaudrait le double, et enchaîné après un « drone de Crypto » ça devient un combo à deux cartes qui prend la meilleure carte d'en face pour 4 d'énergie. Seul combo à deux cartes du paquet : à surveiller en calibration.

🎁 Ne nomme personne.

## Le steak haché de Meliodas

⚖️ VALIDÉE TELLE QUELLE LE 2026-09-12 par l'owner. ACTION · coût NON CALIBRÉ.

EFFET : désigne un héros adverse — ce tour, il ne reçoit ni Aura ni soin de son camp. Seul dans son assiette.

✅ LA REF S'ENTRETIENT TOUTE SEULE, et c'est le meilleur signe qu'elle est solide : la victime elle-même la relance. « eh oh je suis pas sourd hein, laissez-moi tranquille avec ce foutu steak haché » (meliodas987_, 01/09) · « le plus rien dire en question: talk about melio's steak haché for the past week » (02/09) · « le steack haché avait faim » (Malef__) · « c'est pour avoir un menu à base de steak haché » (kassandreyunikon). 5 personnes, du 28/08 au 02/09. Une ref qu'on continue de servir à quelqu'un qui demande qu'on arrête est exactement le critère : tout le monde rit sans qu'on explique.

🎁 LE GAG EST UN GAG D'ISOLEMENT, et l'effet le dit littéralement — couper un héros de l'Aura et des soins des siens. C'est le seul de son lot qui ne parle pas d'Apex.

⚠️ Écrite « steak haché », PAS « streak hacher » : la ligne d'origine portait l'orthographe de la saisie. Le nom d'une carte est ce que les joueurs liront.

⚠️ Elle nomme Meliodas, qui a déjà « Séance de révision » et une carte-héros — trois entrées, sans dette depuis l'arbitrage du 2026-09-11 : une carte est une ref, pas un portrait.

## Le stim d'Octane

Pack de l'owner du 2026-09-10. TACTIQUE · 1 d'énergie : un héros allié perd 2 PV et gagne +4 d'Attaque ce tour.

Origine : Octane. 18 personnes, 36 occurrences.

Prix : +4 d'Attaque le tour (4 points) moins un malus SUBI de 2 PV (× 0,5 → −1) → 3 → plafond(3/3) = 1 d'énergie.

Même forme que « Un piercing de petitpoissonnn » : on se fait mal pour aller plus vite, et c'est exactement ce que fait le personnage.

🎁 Ne nomme personne.

## Le totem

Pack de l'owner du 2026-09-10. PASSIF · 3 d'énergie : une fois, un de tes héros MORTS revient en ligne avec la moitié de ses PV, arrondie au supérieur.

Origine : le totem de Revenant (Apex). 3 personnes au chat seulement (dovaest ×3), mais la ref se passe d'explication pour qui joue Apex.

Prix : un héros à mi-PV vaut plus qu'un gros soin → 9, usage unique déjà compris dans le chiffre → plafond(9/3) = 3 d'énergie, ET un des deux emplacements de passif.

🆕 INTRODUIT LA RÉANIMATION — première fois qu'un héros mort revient. Ce n'est pas un effet de plus : ça change la condition de victoire, qui repose sur les héros qui tombent.

🚨 À CALIBRER EN PREMIER DU LOT : si réanimer est rentable, plus personne ne joue autre chose en passif.

## Le tunnel de Rina

Réécrite le 2026-09-11, sous-titre posé le 2026-09-12.

TITRE : TUNNEL. SOUS-TITRE : « Encore une histoire de Rina... » (owner, 2026-09-12).
EFFET : ACTION · pose l'état TUNNEL sur un héros adverse — il ne peut plus attaquer que celui du poseur, 2 tours. La durée est en stat.

🆕 SEUL EFFET DU JEU QUI REDIRIGE au lieu d'empêcher. Tous les autres contrôles sont des interdictions ; celui-ci force une cible, ce qui est jouable des DEUX côtés.
⚠️ Corollaire à surveiller : TUNNEL PEUT PROTÉGER. Le poser sur le plus gros héros adverse avec un héros-mur à soi le détourne de ses cartes fragiles pendant deux tours. Usage défensif que le gag ne laissait pas prévoir, et peut-être meilleur que l'offensif.

✅ L'HOMONYMIE EST TRANCHéE (2026-09-11) : la carte POSE l'état, elle n'EST pas l'état. L'owner : « les états ne sont pas des cartes. » Il n'y a qu'un seul objet nommé Tunnel dans le jeu.

🎁 Le sous-titre déplace la ref du titre vers la réplique, et le gag y gagne : ce n'est plus « le tunnel DE Rina », c'est la lassitude de celui qui écoute. « Encore une histoire de Rina... » dit exactement ce que fait l'effet — tu ne peux plus parler à personne d'autre.

🎁 Le son existe déjà : data/sons/commande/rina.mp3, migré de PhantomBot.

Origine : « tout ça pour esquiver son tunel » · « tunel numero 2......... » · le GIF Tenor dédié. Fusionnée avec « Blabla Rina », même gag, une seule carte.

## Les PP du samedi

Seconde passe du 2026-09-10. TACTIQUE · 2 d'énergie : +4 d'énergie, mais l'adversaire en gagne 2.

Origine : le rituel des parties personnalisées du samedi. ✅ LA REF LA PLUS PARTAGÉE du lot — 42 personnes distinctes, 149 occurrences. Un topic Apex lui est consacré.

L'adversaire y gagne aussi : c'est le gag, une PP réunit tout le monde, pas seulement toi.

## Lifeline

Pack 2 du 2026-09-10, demandée par l'owner. PASSIF · 3 d'énergie : RÉGÉNÉRATION — +2 PV à un héros allié au début de chacun de tes tours, tant que le passif est en jeu.

Origine : la médic d'Apex. Triple ref déjà présente dans la commu — la STATUE DE LIFELINE que Kassandre exige pour son entrée royale (carte « Le mode diva »), et le meme UNO draw 25 où Raiky préfère piocher 25 cartes plutôt que de jouer autre chose que Lifeline.

⚠️ Un passif occupe 1 des 2 emplacements du joueur : c'est ce qui empêche la régénération d'être toujours meilleure qu'un soin ponctuel. Prix 9 = ~2 PV sur la durée d'une partie → 3 d'énergie, la carte la plus chère du paquet après La Chute.

🎁 Ne nomme personne.

## Lyly

⚖️ RENOMMÉE LE 2026-09-12 par l'owner : « Lili » devient « LYLY ». C'est l'orthographe du vrai nom du chat — le nom d'une carte est ce que les joueurs liront, et ici il désigne un animal réel.

La clé du catalogue suit (lili → lyly) : rien ne la référençait ailleurs, et une clé qui ne dit plus le nom de sa carte finit par désigner autre chose dans la tête de celui qui la lit. « Pika, Spiro et Lili » devient « Pika, Spiro et Lyly ».

PASSIF · catégorie AURA · effet À ÉCRIRE.

⚠️ Les quatre cartes de chats (Pika, Spiro, Lyly, et les trois ensemble) partagent le MÊME pochoir carte-chat.png, et « les trois ensemble » le répète en ARC. Aucune n'a d'effet écrit à ce jour, et elles forment visiblement un ensemble à écrire D'UN COUP : trois passifs d'aura indépendants plus une carte de regroupement n'ont de sens que les uns par rapport aux autres.

## Mets-le dans du riz

⚖️ RÉÉCRITE LE 2026-09-12 avec l'owner. ACTION · coût NON CALIBRÉ.

EFFET : soigne un héros du poseur — mais seulement à la FIN DU TOUR SUIVANT. Si l'adversaire l'achève d'ici là, LE SOIN EST PERDU AVEC LA CARTE.

🎁 LE DÉLAI N'EST PAS UN ÉQUILIBRAGE, C'EST LE GAG : le riz met la nuit à faire effet.

⚖️ LA PERTE EST LE PRINCIPE, pas un cas limite — verbatim de l'owner, 2026-09-12 : « justement, c'est là le principe : si le héros meurt avant d'être soigné, alors la carte est perdue. » C'est écrit SUR la carte et pas seulement ici : un joueur doit savoir ce qu'il risque avant de la poser.

⚠️ L'owner a déplacé le déclenchement : la version d'avant soignait « au DÉBUT de ton prochain tour », celle-ci à la FIN du tour suivant. La fenêtre où la cible est achevable est plus longue d'un tour entier.

⚠️ PREMIER EFFET DIFFÉRÉ DU JEU. Le moteur devra tenir une file d'effets en attente. La question « que devient un effet dont la cible est morte ? » est tranchée ICI et vaut comme précédent : l'effet est PERDU, il ne se reporte sur personne.

Origine : « mets ton casque dans du riz » (rrina_t) · « mets du riz dans ton casque » (lilio___) · « t'as essayé de mettre ton arc star dans du riz avant de la jeter ? »

🎁 Ne nomme personne sur la carte.

## Mozambique here!

⚖️ RÉÉCRITE LE 2026-09-12 avec l'owner, et elle CHANGE DE SOUS-TYPE : PASSIF (était ACTION). Coût NON CALIBRÉ.

EFFET : reste sur le plateau, FACE VISIBLE, et peut donc être détruite. Tant qu'elle y est, TOUT LE MONDE est en RAGE — les héros du poseur comme ceux d'en face : chacun a une chance d'infliger un coup critique.

🚨 RÈGLE D'ÉQUILIBRAGE POSÉE PAR L'OWNER LE 2026-09-12 : « Mozambique devrait donner plus de chance de critique que la manette, c'est comme ça qu'on balance. » Le taux de RAGE doit donc être STRICTEMENT SUPÉRIEUR à celui de « La manette », qui donne le même critique mais à son camp SEUL. Le sur-taux est ce qu'on paie pour armer aussi l'adversaire — sans lui, Mozambique serait une manette en pire et personne ne la jouerait.

🆕 PREMIER BUFF NOMMÉ PARTAGÉ PAR LES DEUX CAMPS. « RAGE » entre au vocabulaire du jeu ici. À définir une seule fois quand les règles seront reprises, pas dans chaque carte qui s'en servira.

⚖️ POURQUOI PASSIF : arbitrage de l'owner du 2026-09-12 — « les passifs se déclenchent tout seuls, les actions c'est le joueur qui les déclenche ». ⚠️ Le cadre de la carte passe au crème PASSIF.

⚠️ FACE VISIBLE, donc DESTRUCTIBLE. Il faudra dire une fois, et pas carte par carte, ce que « détruire une carte posée » coûte à l'attaquant.

⚠️ Hasard PUR résolu au moment du coup, aucun dé, aucun Tirage.

🎁 SYMÉTRIQUE, et le gag y est : le Mozambique est la pire arme d'Apex, celle qu'on ramasse en désespoir de cause. La carte ne donne d'avantage à personne — elle rend juste la table plus violente pour tout le monde.

Origine : le meme « redis-le encore une fois » — la pire arme d'Apex, devenue culte.

(Ancienne version, écartée au tri du 2026-09-11 : « un héros allié n'inflige plus que 1 dégât ce tour, mais il frappe TOUS les héros adverses ».)

## Méliodas

Retenue au tri de l'owner du 2026-09-10. Stats à écrire à la MAIN — Attaque + PV + Aura = 12 + bonus de rareté. A aussi une carte-moment « Séance de révision avec Meliodas » (debuff). ⚠️ Déjà dans tcg/cartes.yaml, mais tout à INDÉFINI / 0.

## OriganireTV

Retenue au tri de l'owner du 2026-09-10. Stats à écrire à la MAIN — Attaque + PV + Aura = 12 + bonus de rareté. Les trois comptes (twitch:702529105, discord:586611760082059287, twitch:541477747) sont la même personne, confirmé par l'owner le 2026-09-04. ⚠️ Non liés en base.

## POV le chevreuil

Pack 2 du 2026-09-10, demandée par l'owner. ACTION · coût non calibré : pose STUN sur un héros adverse — il n'attaque pas ce tour, sans condition. Figé dans les phares.

Origine : le meme rangé « POV LE CHEVREUIL » / « QUAND IL A VU LA VOITURE » — chevreuil surpris, oreilles levées, yeux écarquillés, forêt nocturne.

⚠️ STUN EST DÉTERMINISTE, et c'est voulu : un effet certain se calibre plus simplement qu'un effet aléatoire, et le jeu en a besoin d'au moins un. Ne pas lui ajouter de pourcentage « pour faire pareil » que les autres.

🎁 Ne nomme personne — hors du point dur du consentement.

## Pika

Pack 3, 2026-09-10. Un des trois chats d'Azraël — idée de l'owner du 2026-08-31 : « une carte unique chacun, plus une carte avec les trois réunis ».

🎁 Pika a déjà son meme rangé : « Pika, calme devant le stream, regard fixe au-dessus de l'eau et des montagnes — T'ES TRANQUILLE EN TRAIN DE… ». C'est le seul des trois qui en a un.

🎁 Ne nomme aucune personne — hors du point dur du consentement. Visée : la famille Aura et coopération, la seule qui n'a rien reçu depuis le début.

## Pika, Spiro et Lili

Pack 3, 2026-09-10. Les TROIS chats d'Azraël réunis — idée de l'owner du 2026-08-31 : une carte chacun, PLUS celle-ci.

Visée naturelle : la famille Aura et coopération. Une carte « les trois ensemble » appelle un effet qui récompense d'avoir les trois autres, ce que le paquet n'a pas encore.

⚠️ Si elle exige les trois cartes individuelles en jeu, elle est injouable la plupart du temps — 3 cartes sur un deck de 12, dont 2 passifs limités à 2 emplacements. À vérifier avant d'écrire l'effet.

## Quoi → FEUR

Seconde passe du 2026-09-10, vocabulaire corrigé le 2026-09-12.

ACTION · coût non calibré : annule la prochaine ACTION jouée par l'adversaire ce tour.

⚖️ LE MOT « TACTIQUE » EST RETIRÉ DE LA CARTE (2026-09-12). Le sous-type se dit ACTION, c'est ce que porte le bandeau du bas — une carte qui en nommait un autre dans sa propre règle envoyait le joueur chercher une catégorie qui n'existe plus à l'écran. C'était la DERNIÈRE occurrence du mot dans tout le catalogue.

Origine : le meme rangé du bouton rouge — « QUAND QUELQU'UN DIT QUOI ET QU'IL Y A REQUIN », main qui claque le bouton « FEUR ». 3 personnes, 13 occurrences.

🎁 SEULE CARTE DU JEU SANS POCHOIR : le mot FEUR prend la place de l'illustration, en Archivo Black à la taille d'une icône. Une carte dont la vanne EST un mot ne gagne rien à un pictogramme — elle n'a pas d'objet à dessiner, elle a une réplique.

🚨 À SURVEILLER À LA CALIBRATION : annuler une carte pour pas cher est la meilleure affaire de la liste quand l'adversaire joue cher. Une annulation bon marché aplatit tout un paquet d'un coup.

⚖️ En revanche « et une carte morte quand il ne joue rien » n'est PLUS compté comme un défaut — arbitrage de l'owner du 2026-09-12 : une carte qui dépend du deck d'en face est un PARI DE CONSTRUCTION.

## Raciste

⚖️ RÉÉCRITE LE 2026-09-12 avec l'owner. ACTION · coût NON CALIBRÉ.

EFFET : un héros du poseur se spécialise — il gagne beaucoup d'Attaque, mais ne peut plus changer de cible : il tape le même héros adverse jusqu'à ce qu'il tombe.

🚨 SON ANCIEN EFFET REPOSAIT SUR LES FACTIONS, QUI N'EXISTENT PAS. L'owner, 2026-09-12 : « y a pas de faction dans le jeu. » L'ancienne version était « −3 d'Attaque à tous les héros adverses qui partagent la même faction » — une règle écrite sur une dimension que rien n'a jamais portée. ⚠️ Le champ « Faction » de cette base est vide sur 63 fiches et vaut « aucune » sur 9 : AUCUNE carte n'en a jamais eu. C'est un champ à supprimer de la base.

🎁 LE GAG EST MIEUX RENDU QU'AVANT. « Raciste » dans la commu, c'est jouer toujours les mêmes persos ou la même arme — le mot ne veut PAS dire autre chose ici. La nouvelle version fait exactement ça : on se spécialise, on tape plus fort, et on ne sait plus faire autre chose. L'ancienne punissait l'adversaire d'être monochrome ; celle-ci fait porter le travers à SON PROPRE camp, ce qui est plus juste et moins lisible de travers.

⚠️ SEUL TITRE DU PAQUET LISIBLE DE TRAVERS HORS CONTEXTE. Le sous-titre répète aujourd'hui le titre et ne désamorce rien — c'est la seule surface où la carte peut dire ce qu'elle veut dire. À écrire.

🎁 Ne nomme personne.

## Raiky dans l'anneau

Seconde passe du 2026-09-10. TACTIQUE · 2 d'énergie : un héros de ta RÉSERVE entre en ligne immédiatement, mais perd 2 PV.

Origine : le meme rangé « Let Me In » (Eric Andre hurlant à la grille) — texte : RAIKY QUAND ELLE EST DANS L'ANNEAU. Hors zone, elle veut rentrer.

⚠️ AUCUNE trace au chat : cette carte tient uniquement sur l'existence du meme. C'est une preuve d'un AUTRE ordre — quelqu'un l'a fabriqué et rangé — et elle vaut, mais elle ne se mesure pas de la même façon.

⚠️ Nomme Raiky, retenue côté héros : entre dans le point dur du consentement.

## Raiky le fusible de camion

Retenue au tri de l'owner du 2026-09-10. Stats à écrire à la MAIN — Attaque + PV + Aura = 12 + bonus de rareté. Même personne que « raiky0801 », confirmé par l'owner le 2026-09-04. ⚠️ Non liés en base.

## Rendez-vous au véto

⚖️ RÉÉCRITE LE 2026-09-12 avec l'owner, et elle CHANGE DE CAMP. ACTION · coût NON CALIBRÉ.

EFFET : un héros du poseur quitte la ligne pour un tour — il ne peut ni agir ni être touché — et revient complètement soigné.

🚨 ELLE N'EST PLUS OFFENSIVE. L'ancienne version faisait passer son tour à un héros ADVERSE (état Scroll + perte d'Aura), et c'était la carte la plus brutale du jeu. Celle-ci ne touche que le camp du poseur : on retire un héros du danger et on le récupère intact. ⚠️ L'état SCROLL n'a donc PLUS AUCUNE CARTE qui le pose — il est à retirer du vocabulaire, ou une autre carte doit le reprendre.

🆕 PREMIER EFFET DE RETRAIT TEMPORAIRE. Le jeu savait empêcher d'agir (Stun), rediriger (Tunnel), soigner. Il ne savait pas SORTIR un héros de la table et le ramener. ⚠️ Le moteur devra dire ce que devient un effet en cours sur un héros absent — un soin différé (le riz), un état posé sur lui : suspendus, ou perdus comme le riz ? À trancher une fois.

🎁 LE GAG EST PLUS FIDÈLE QUE L'ANCIEN. Un rendez-vous chez le véto, ça n'empêche pas l'adversaire de jouer — ça te fait disparaître toi. Le stream saute, on revient après.

🎁 Elle relie deux cartes sans qu'on l'ait cherché : le véto en question, c'est celui de SPIRO, qui a sa propre carte au catalogue.

Origine, vérifiée et datée dans les logs : « rendez vous veto en urgence demain matin » · « gros ulcère de la cornée » · « rendez vous veto pour un contrôle pour l'œil de Spiro à 10h, si c'est rapide je lance vers 10h30, sinon pas de matinale ».

## Requin qui tente d'expliquer

Seconde passe du 2026-09-10. TACTIQUE · 2 d'énergie : les tactiques de l'adversaire coûtent +1 d'énergie ce tour.

Origine : le meme rangé « format calculs confus, homme perplexe noyé sous des formules — REQUIN QUI TENTE DE NOUS EXPLIQUER POURQUOI… ». 17 personnes distinctes sur les marqueurs d'incompréhension.

L'effet est fidèle : personne ne comprend, donc tout coûte plus cher.

## Soin

Demandée par l'owner le 2026-09-04. ⚠️ 2026-09-10 : « Soin » est un TYPE d'effet, pas une ref — et il est désormais couvert par deux cartes qui, elles, viennent de quelque part : « Mets-le dans du riz » (2 énergie, 6 PV différés) et « 10 pizzas géantes » (3 énergie, 4 PV à tous). Sans effet propre ni origine, cette ligne fait doublon. À retirer, sauf si l'owner lui voit un gag.

## Spiro

Pack 3, 2026-09-10. Un des trois chats d'Azraël — idée de l'owner du 2026-08-31.

⚠️ Aucune trace en base ni dans les logs : contrairement à Pika, Spiro n'a ni meme ni mention. Sa carte est à écrire entièrement par l'owner (personnage, effet), Wally ne le connaît pas.

## Séance de révision avec Meliodas

Debuff, demandée par l'owner le 2026-09-04.

## Taki_Gano

Retenue au tri de l'owner du 2026-09-10. Stats à écrire à la MAIN — Attaque + PV + Aura = 12 + bonus de rareté. Même personne que « Ɇ |TaKi », confirmé par l'owner le 2026-09-04. ⚠️ Les deux comptes ne sont PAS liés en base.

## Tenma 

⚖️ RÉÉCRITE LE 2026-09-12 avec l'owner. PASSIF · coût NON CALIBRÉ.

EFFET : tant qu'il ne reste qu'UN SEUL héros en ligne à son poseur, la chance d'esquive de ce héros est fortement accrue.

🎁 LE GAG EST DANS LA CONDITION. Le meme d'origine est « TENMA A 10HP : moi qui pensais pouvoir gagner mon 1v1 » : la carte ne sert à rien tant que tout va bien, et devient redoutable exactement au moment où on croyait avoir gagné.

🆕 PREMIÈRE CARTE À RÉCOMPENSER LE FAIT D'ÊTRE EN TRAIN DE PERDRE. Toutes les autres améliorent une position ; celle-ci ne s'allume qu'en dernier recours. ⚠️ À surveiller à la calibration : un effet qui ne s'allume qu'en fin de partie est soit inutile, soit ce qui décide toutes les fins de partie. Il n'y a pas d'entre-deux.

⚠️ INTERACTION DIRECTE avec « Aim assist = aimbot », qui met TOUTES les esquives adverses à zéro : Aim assist éteint Tenma complètement. C'est du contre-jeu voulu, pas un conflit — mais les deux se calibrent ensemble.

⚠️ Hasard PUR, aucun dé, aucun Tirage.

Origine : 2 memes rangés — « TENMA A 10HP : moi qui pensais pouvoir gagner mon 1v1 ».

(Ancienne version, écartée au tri du 2026-09-11 : « le premier de tes héros qui tomberait à 0 PV survit à 1 PV et gagne +5 d'Attaque ce tour ».)

## Traite

Idée de l'owner, versée de sa page le 2026-09-12, verbatim : « traite ,: enlève des PV à un allié pour les transformer en attaque ». Coût à définir.

⚠️ LE NOM EST À CONFIRMER : « traite » se lit « la traite » (on tire sur l'allié comme sur une vache), « traître » (on le sacrifie) ou « traité ». Le gag et l'illustration diffèrent selon la lecture.

⚠️ Sous-type non tagué (l'owner a tagué « belle bite » [passif], pas celle-ci). Rangée en tactique par défaut ; si l'effet doit durer, c'est un passif.

⚠️ Ni le nombre de PV retirés ni le taux de conversion ne sont écrits. Le barème veut 1 PV ≈ 1 point et un malus SUBI × 0,5 : une conversion 1:1 est rentable par construction.

🎁 Même forme que « Le stim d'Octane » et « Un piercing de petitpoissonnn » — mais elle frappe un AUTRE héros que le bénéficiaire, ce qu'aucune carte du paquet ne fait encore.

## Typical Octane

Pack de l'owner du 2026-09-10. TACTIQUE, SE JOUE FACE CACHÉE · 2 d'énergie : la prochaine fois que l'adversaire pioche, C'EST TOI QUI PRENDS LA CARTE.

Origine : le meme « typical octane » — le mec qui part avec ce qui n'est pas à lui.

Prix : +1 carte (2) et −1 pour l'adversaire (2) × 1,25 → 5 → plafond(5/3) = 2 d'énergie. Même prix que « Le shop de Loba » pour un effet voisin, et c'est cohérent : l'un prend dans la main, l'autre dans la pioche.

🆕 TROISIÈME CARTE QUI FAIT REVENIR L'ANONYME. Règles arrêtées le 2026-09-11 : 2 PV (= son coût), NON AFFICHÉS ; détruite, elle est révélée et défaussée sans déclencher.

⚠️ CONTRAIREMENT AU BARIL DE CAUSTIQUE, ELLE N'A AUCUNE FENÊTRE GARANTIE : le baril part forcément au tour suivant, elle attend que l'adversaire pioche — ce qui peut ne jamais venir avant qu'on la descende. C'est la plus fragile des trois, et c'est cohérent : elle vole, elle se cache vraiment.

🎁 Ne nomme personne.

## Un montage de Malef

Demandée par l'owner le 2026-09-04. GARDÉE au tri du 2026-09-10, alors même que la carte-personne de Malef ne l'est pas : le gag survit à la personne (§4.1 — ces cartes n'ont personne derrière et ne tirent rien de la mémoire).

## Un piercing de petitpoissonnn

Demandée par l'owner le 2026-09-10. TACTIQUE · 1 d'énergie : +3 d'Aura à un héros allié pour la partie, ET il perd 1 PV.

Origine, 1 personne — mais un running gag qu'elle répète : « j'ai craqué j'ai un nouveau piercing azra » · « siiii comme ça j'ai un nombre pair de piercing » · « rekin m'a convaincu d'aller me faire le nostril ».

Prix : +3 d'Aura permanent = 3 points, moins un malus SUBI de 1 PV (× 0,5 → −0,5) → 3 arrondi → 1 d'énergie. On souffre un peu pour être beau : c'est le gag, et c'est la seule carte d'Aura qui se paie en PV plutôt qu'en énergie.

⚠️ petitpoissonnn est aussi retenue côté héros : cette carte la nomme, elle entre donc dans le point dur du consentement.

## Wally

AJOUTÉE au tri du 2026-09-10 — la ligne manquait, alors que la carte EXISTE déjà dans tcg/cartes.yaml (clé « wally », commit a90028ca).

C'est le BOSS : toute la commu s'unit contre lui (idée de l'owner, 2026-08-31). Sa carte n'est pas gagnable.

État dans tcg/cartes.yaml : légende WALLY · ARCHANGE, classe ARCHANGE, visuels 2D + 3D posés (parallaxe 1.2, holographique). Mais ultime, description, ambiance, coût, atk, pv et aura sont tous à INDÉFINI / 0.

🎁 Son Ultime est déjà écrit dans la maquette du plateau : TRICHE — « Ses PV ne suivent aucune règle : il peut en regagner sans prévenir. » C'est la forme voulue : une règle ANNONCÉE, jamais un mensonge du moteur. La maquette lui donne 120 PV (84 restants en partie).

⚠️ Son budget de BOSS n'est pas celui d'un héros de deck : les 120 PV de la maquette débordent largement le 12 + rareté. À poser comme une valeur à part, pas comme une entorse au barème.

## Zoe_Chmamour

AJOUTÉE au tri du 2026-09-10 — demandée par l'owner sous « ZOÉ » dans sa liste perso. Alias « zowée ». Stats à écrire à la MAIN — Attaque + PV + Aura = 12 + bonus de rareté. ⚠️ Les deux comptes ne sont PAS liés en base.

## dovaest

Retenue au tri de l'owner du 2026-09-10. Stats à écrire à la MAIN — Attaque + PV + Aura = 12 + bonus de rareté.

## elhya__

🕯️ Elhya est décédée. Carte HOMMAGE, hors du jeu pour le moment — elle y entrera plus tard, quand l'owner le décidera. Ne pas l'inclure dans les tirages, les lootbox ni les decks.

## lilio___

Retenue au tri de l'owner du 2026-09-10. Stats à écrire à la MAIN — Attaque + PV + Aura = 12 + bonus de rareté. A aussi une carte-moment « Le jingle de Lilio ». 🎁 Le jingle existe déjà : data/sons/commande/ (migré de PhantomBot).

## lilith220501

Retenue au tri de l'owner du 2026-09-10. Stats à écrire à la MAIN — Attaque + PV + Aura = 12 + bonus de rareté. ⚠️ Sa carte est déjà dans tcg/cartes.yaml (7 · 6/6/5) : ces chiffres viennent de l'ancien modèle, à revoir.

## petitpoissonnn

Retenue au tri de l'owner du 2026-09-10. Stats à écrire à la MAIN — Attaque + PV + Aura = 12 + bonus de rareté.

## rhae___

CHEF des modérateurs — « Azra et Rhae sont de grosses cartes » (owner, 2026-08-31). Carte unique, rareté Ange. ⚠️ Sa carte est déjà dans tcg/cartes.yaml (6 · 8/5/4) : ces chiffres viennent de l'ancien modèle Voix/Aura/Piquant, à revoir. Stats à écrire à la MAIN — Attaque + PV + Aura = 12 + bonus de rareté.

## zeddo el plubelo

Retenue au tri de l'owner du 2026-09-10. Stats à écrire à la MAIN — Attaque + PV + Aura = 12 + bonus de rareté. A aussi une carte-objet « Apéro chez Zeddo ».

## « C'est mon kill » / « NOTRE kill »

Pack 3, 2026-09-10. Origine : le meme rangé Bugs Bunny communiste (faucille et marteau) — « MOI EN WILDCARD : C'EST MON KILL / AZRAEL : NOTRE KILL ».

Visée : Aura et coopération. Le gag est un effet de PARTAGE — ce qui est à un est à tous — et c'est exactement la forme qui manque au paquet (11 cartes en Attaque contre 4 en Aura).

⚠️ Nomme Azraël : entre dans le point dur du consentement.

## « Viens en vocal »

🆕 PACK 3, 2026-09-10 — PREMIÈRE CARTE DU DECK DE WALLY. L'owner : « c'est une carte spéciale, une carte du deck de Wally (il aura son propre deck). Une fois jouée ça lance une boîte de dialogue, un des joueurs doit parler avec Wally et le convaincre d'un truc, à voir encore quoi. »

Origine : rhae qui prévient Azraël que Wally l'attend en vocal.

C'est la première carte du jeu qui APPELLE LE LLM EN PLEINE PARTIE. Elle solde le manque nommé au §6 des tactiques (« les tactiques de Wally ne sont pas écrites »). Cinq points durs, dont deux structurants :

🚨 1. REPRODUCTIBILITÉ. L'arbitrage du 2026-09-09 a choisi un moteur HÉURISTIQUE À GRAINE contre un LLM, précisément parce qu'on ne peut pas équilibrer un jeu contre un adversaire non déterministe (10 000 parties en une nuit à graine fixée). Une conversation ne se rejoue pas. → À TRANCHER : en calibration, la conversation doit être remplacée par un verdict tiré à un taux fixe. Sinon cette carte rend la calibration impossible pour tout le paquet.

🚨 2. PROMPT INJECTION. « Convaincre Wally », c'est littéralement demander à un joueur de manipuler un LLM — et le gagnant sera celui qui sait le faire, pas celui qui joue bien. La brique existe : wrap_untrusted() (bot/core/untrusted.py) borne le contenu externe et rappelle que c'est de la DONNÉE, jamais une instruction. Le texte du joueur doit y passer.

3. LE TEMPS. Une conversation bloque toute la table. Limite nécessaire : nombre de messages ou chrono.

4. VUE CENSURÉE. En coop Wally est l'adversaire, il connaît sa main. Le juge doit recevoir l'ÉTAT PUBLIC, jamais l'état complet — sinon il vend sa propre main ou commente ce que le joueur ne peut pas voir, ce qui se lit comme de la triche (§9.3).

5. CLOISONNEMENT. Rien de cet échange ne repasse par fact_extractor ni par la consolidation nocturne (§4.2). Une vanne de partie ne doit pas devenir un fait mémorisé sur quelqu'un.

⏸️ RESTE À DÉFINIR PAR L'OWNER : de quoi le joueur doit convaincre Wally, et ce qu'il gagne ou perd.

## Ʀ |TaKi

Fusionnée dans « Taki_Gano » — confirmé par l'owner le 2026-09-04 : c'est la même personne. Ligne gardée pour la trace, une seule carte existe. Comptes : discord:528237220327325720 (38 faits) + twitch:191311228 (165).
