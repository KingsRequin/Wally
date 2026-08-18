/* Les réglages : l'interrupteur, l'adresse, le jeton.
 *
 * Le bouton ne se contente pas d'enregistrer : il ESSAIE la connexion et dit ce
 * qui revient. Un jeton mal collé, une adresse fautive — sans cet essai, Azraël
 * refermerait la fenêtre en croyant que c'est branché, et personne ne
 * découvrirait le contraire avant le live.
 */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const etat = $("etat");

  chrome.storage.local.get(["url", "jeton", "actif"], (r) => {
    $("url").value = r.url || "https://heywally.fr";
    $("jeton").value = r.jeton || "";
    $("actif").checked = r.actif === true;
  });

  // L'interrupteur prend effet TOUT DE SUITE, sans passer par Enregistrer :
  // c'est un geste de confidentialité, il ne se met pas en attente.
  $("actif").addEventListener("change", () => {
    chrome.storage.local.set({ actif: $("actif").checked });
    dire($("actif").checked ? "Partage activé." : "Partage coupé — rien ne sort.");
  });

  $("enregistrer").addEventListener("click", async () => {
    const url = $("url").value.trim().replace(/\/+$/, "");
    const jeton = $("jeton").value.trim();
    chrome.storage.local.set({ url, jeton, actif: $("actif").checked });

    if (!url || !jeton) { dire("Il manque l'adresse ou le jeton."); return; }
    dire("Essai en cours…");
    try {
      const r = await fetch(url + "/api/music/beat", {
        method: "POST",
        headers: { "Content-Type": "application/json",
                   "Authorization": "Bearer " + jeton },
        // Un essai n'envoie AUCUN titre : il vérifie la porte, rien d'autre.
        body: JSON.stringify({ actif: false }),
      });
      if (r.status === 401) dire("Jeton refusé — vérifie qu'il est complet.");
      else if (r.status === 503) dire("Le bot n'a pas de jeton configuré de son côté.");
      else if (r.ok) dire("C'est branché ✓");
      else dire("Le bot a répondu " + r.status + ".");
    } catch (e) {
      dire("Bot injoignable à cette adresse.");
    }
  });

  function dire(texte) { etat.textContent = texte; }
})();
