/* Panneaux Apex de l'overlay.
 *
 * Fichier séparé à dessein : `overlay.js` fait déjà près de mille lignes, et
 * ces sept panneaux forment un bloc qu'on lit d'un tenant.
 *
 * Il s'enregistre dans `window.APEX_BUILDERS`, qu'`overlay.js` fusionne dans sa
 * table BUILDERS. Il DOIT donc être chargé AVANT lui — dans l'autre ordre, la
 * fusion lit `undefined` sans que rien ne le signale (même famille de piège que
 * la TDZ de buildSections).
 *
 * Aucune valeur n'est calculée ici : le serveur envoie des chiffres déjà justes.
 * Le navigateur ne fait que les mettre en forme.
 */
(() => {
  "use strict";

  const el = (tag, className) => {
    const n = document.createElement(tag);
    if (className) n.className = className;
    return n;
  };

  const nombre = (v) => Number(v || 0).toLocaleString("fr-FR");

  /** Une carte au format `.stats`, dont le style existe déjà. */
  const carte = (titre) => {
    const box = el("div", "stats apex");
    if (titre) {
      const who = el("div", "who");
      who.textContent = String(titre);
      box.appendChild(who);
    }
    return box;
  };

  /** Une ligne « libellé / valeur », alignée comme celles de `stats`. */
  const ligne = (box, libelle, valeur, i) => {
    const row = el("div", "line");
    row.style.setProperty("--i", String(i));
    const k = el("span", "k");
    const v = el("span", "v");
    k.textContent = String(libelle);
    v.textContent = String(valeur);
    row.append(k, v);
    box.appendChild(row);
    return row;
  };

  /** « 5190 » → « 1:26:30 ». */
  const duree = (secondes) => {
    const s = Math.max(0, Math.floor(secondes));
    const h = Math.floor(s / 3600);
    const m = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
    const r = String(s % 60).padStart(2, "0");
    return h ? `${h}:${m}:${r}` : `${m}:${r}`;
  };

  /* Décompte vivant. Le timer s'arrête tout seul dès que l'élément quitte le
   * DOM : un widget chasse l'autre, et un intervalle orphelin tournerait pour
   * l'éternité dans une source OBS qu'on ne recharge jamais. */
  const decompte = (node, secondes) => {
    let restant = secondes;
    node.textContent = duree(restant);
    const id = setInterval(() => {
      if (!node.isConnected) { clearInterval(id); return; }
      restant -= 1;
      if (restant <= 0) { clearInterval(id); node.textContent = "—"; return; }
      node.textContent = duree(restant);
    }, 1000);
  };

  window.APEX_BUILDERS = {
    apex_rank(p) {
      const box = carte(p.player);
      const tete = el("div", "apex-rank-head");
      if (p.img) {
        const img = el("img", "apex-rank-img");
        img.src = String(p.img);
        img.alt = "";
        tete.appendChild(img);
      }
      const nom = el("div", "apex-rank-name");
      nom.textContent = p.div ? `${p.rank_name} ${p.div}` : String(p.rank_name || "");
      tete.appendChild(nom);
      box.appendChild(tete);
      ligne(box, "RP", nombre(p.score), 0);
      if (p.top_percent !== null && p.top_percent !== undefined) {
        ligne(box, "Ladder", `top ${p.top_percent} %`, 1);
      }
      if (p.ladder_pos) ligne(box, "Position", `${nombre(p.ladder_pos)}ᵉ`, 2);
      return box;
    },

    apex_status(p) {
      const box = carte(p.player);
      if (p.avatar) {
        const img = el("img", "apex-avatar");
        img.src = String(p.avatar);
        img.alt = "";
        box.appendChild(img);
      }
      const etat = el("div", p.in_game ? "apex-state live" : "apex-state");
      etat.textContent = p.in_game ? "En partie" : String(p.state || "Hors ligne");
      box.appendChild(etat);
      let i = 0;
      if (p.legend) ligne(box, "Légende", String(p.legend), i++);
      if (p.skin) ligne(box, "Skin", String(p.skin), i++);
      ligne(box, "Niveau", nombre(p.level), i++);
      if (p.banned) ligne(box, "⚠️", "banni", i++);
      return box;
    },

    apex_stats(p) {
      const box = carte(p.player);
      (p.rows || []).forEach((row, i) => {
        const l = ligne(box, row.label, nombre(row.value), i);
        if (row.top_percent !== null && row.top_percent !== undefined) {
          const rang = el("span", "apex-world");
          rang.textContent = `top ${row.top_percent} %`;
          l.appendChild(rang);
        }
      });
      return box;
    },

    apex_map(p) {
      const box = carte("Rotation");
      (p.modes || []).forEach((mode, i) => {
        const l = ligne(box, mode.name, mode.map, i);
        if (mode.remaining_s > 0) {
          const t = el("span", "apex-timer");
          decompte(t, mode.remaining_s);
          l.appendChild(t);
        }
      });
      return box;
    },

    apex_craft(p) {
      const box = carte("Replicator");
      (p.bundles || []).forEach((b, i) => ligne(box, b.type, b.items.join(", "), i));
      return box;
    },

    apex_predator(p) {
      const box = carte("Seuil Predator");
      (p.rows || []).forEach((r, i) => ligne(box, r.platform, `${nombre(r.rp)} RP`, i));
      return box;
    },

    apex_servers(p) {
      const box = carte("Serveurs");
      (p.rows || []).forEach((r, i) => {
        const l = ligne(box, r.name, r.status, i);
        l.classList.add(r.up ? "apex-up" : "apex-down");
      });
      return box;
    },
  };
})();
