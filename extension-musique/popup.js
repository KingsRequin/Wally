/* Les réglages : l'interrupteur, l'adresse, le jeton.
 *
 * Le bouton ne se contente pas d'enregistrer : il ESSAIE la connexion et dit ce
 * qui revient. Un jeton mal collé, une adresse fautive — sans cet essai, Azraël
 * refermerait la fenêtre en croyant que c'est branché, et personne ne
 * découvrirait le contraire avant le live.
 */
(() => {
  "use strict";

  const MARQUE = "wally-musique";
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

  // ── Ce que fait vraiment l'onglet ouvert derrière cette fenêtre ───────────
  //
  // Le bouton « Enregistrer » appelle le bot DEPUIS l'extension, qui y a droit
  // sans rien demander. Le battement, lui, part de la page YouTube. Les deux
  // chemins sont distincts, et le premier peut réussir pendant que le second
  // n'existe pas : un onglet ouvert avant l'installation n'a pas reçu le
  // script et se taira jusqu'à son rechargement. C'est exactement ce qui s'est
  // produit au premier essai en réel, sans qu'aucune trace ne le dise, ni ici
  // ni côté bot.
  function interrogerOnglet() {
    const zone = $("onglet");
    chrome.tabs.query({ active: true, currentWindow: true }, (onglets) => {
      const onglet = onglets && onglets[0];
      if (!onglet) return;
      chrome.tabs.sendMessage(onglet.id, { marque: MARQUE, type: "diagnostic" },
        (rep) => {
          if (chrome.runtime.lastError || !rep) {
            zone.textContent = "⚠️ Cet onglet n'envoie rien. S'il est sur "
              + "YouTube, recharge la page (F5) : l'extension ne s'installe "
              + "pas dans les onglets déjà ouverts.";
            return;
          }
          if (!rep.actif) { zone.textContent = "Partage éteint : rien ne part de cet onglet."; return; }
          if (rep.dernierOk) {
            const secondes = Math.round((Date.now() - rep.dernierOk) / 1000);
            zone.textContent = "✓ Cet onglet parle à Wally (dernier envoi il y a "
              + secondes + " s)" + (rep.titre ? " — " + rep.titre : "") + ".";
          } else {
            zone.textContent = "⚠️ Cet onglet essaie mais n'y arrive pas : "
              + (rep.erreur || "aucun envoi encore abouti") + ".";
          }
        });
    });
  }
  interrogerOnglet();
})();
