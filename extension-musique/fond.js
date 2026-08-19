/* La pastille sur l'icône : « une version corrigée existe ».
 *
 * Pourquoi un fichier de plus pour ça : `chrome.action` n'est joignable ni
 * depuis la page YouTube ni depuis le monde de la page. Seul ce service worker
 * peut poser la pastille, et il ne fait que ça.
 *
 * Elle existe parce que la fenêtre de réglages ne suffit pas : une fois que ça
 * marche, Azraël n'a plus aucune raison de l'ouvrir — l'avertissement y
 * dormirait des semaines. Sur l'icône, il se voit sans rien ouvrir.
 *
 * Le service worker s'endort au bout de quelques secondes d'inactivité et la
 * pastille, elle, reste : c'est une propriété de l'icône, pas de ce script. Le
 * battement la repose de toute façon toutes les deux secondes.
 */
"use strict";

const MARQUE = "wally-musique";

chrome.runtime.onMessage.addListener((msg) => {
  if (!msg || msg.marque !== MARQUE || msg.type !== "maj") return;
  // Un point, pas un compte : il n'y a jamais qu'une mise à jour en retard, et
  // un « 1 » se lirait comme un message non lu.
  chrome.action.setBadgeText({ text: msg.disponible ? "●" : "" });
  if (msg.disponible) {
    chrome.action.setBadgeBackgroundColor({ color: "#f59e0b" });
    chrome.action.setTitle({
      title: "Wally — musique du live : une mise à jour existe",
    });
  } else {
    chrome.action.setTitle({ title: "Wally — musique du live" });
  }
});
