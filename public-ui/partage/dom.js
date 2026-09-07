// public-ui/partage/dom.js — la fabrique de DOM, partagée
//
// `public-ui/partage/` est le SEUL dossier importé par les deux surfaces du
// front : le site public (`/`) et l'overlay OBS (`/static/`). L'overlay ne peut
// pas importer `app.js` — il tirerait Lenis, le routeur d'historique, les flux
// SSE du site et son décor parallax pour avoir une seule fonction.
//
// `h()` reste réexporté par `app.js` : six pages l'importent depuis là, et
// aucune n'a à bouger parce que l'overlay a besoin de la même chose.

// Les pages construisent leur arbre avec `h()` : jamais d'innerHTML, jamais de
// chaîne HTML interpolée. Un titre d'image ou un pseudo peut contenir du code
// (vécu : un nom de fichier de son exécutait un `onclick` interpolé).
export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
      else if (k === 'style') el.style.cssText = v;
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
      else if (k.startsWith('data-') || k === 'role' || k.startsWith('aria-')) el.setAttribute(k, v);
      else el[k] = v;
    }
  }
  kids.flat().forEach((k) => {
    if (k === null || k === undefined || k === false) return;
    el.appendChild(typeof k === 'string' || typeof k === 'number' ? document.createTextNode(String(k)) : k);
  });
  return el;
}
