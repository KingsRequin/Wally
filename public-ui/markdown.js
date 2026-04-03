// public-ui/markdown.js — Parseur Markdown Discord → DOM partagé
// Supports: # h1-3, -# small heading, **gras**, *italique*, _italique_,
//           ~~barré~~, `code`, > blockquote

export function parseInline(text, container) {
  const INLINE = /(\*\*(.+?)\*\*|\*(.+?)\*|_(.+?)_|~~(.+?)~~|`(.+?)`)/gs;
  let last = 0;
  const tokens = [];
  for (const m of text.matchAll(INLINE)) {
    if (m.index > last) tokens.push({ type: 'text', val: text.slice(last, m.index) });
    if      (m[2] !== undefined) tokens.push({ type: 'strong', val: m[2] });
    else if (m[3] !== undefined) tokens.push({ type: 'em',     val: m[3] });
    else if (m[4] !== undefined) tokens.push({ type: 'em',     val: m[4] });
    else if (m[5] !== undefined) tokens.push({ type: 'del',    val: m[5] });
    else if (m[6] !== undefined) tokens.push({ type: 'code',   val: m[6] });
    last = m.index + m[0].length;
  }
  if (last < text.length) tokens.push({ type: 'text', val: text.slice(last) });

  for (const tok of tokens) {
    if (tok.type === 'text') {
      container.appendChild(document.createTextNode(tok.val));
    } else if (tok.type === 'strong') {
      const el = document.createElement('strong'); el.textContent = tok.val; container.appendChild(el);
    } else if (tok.type === 'em') {
      const el = document.createElement('em'); el.textContent = tok.val; container.appendChild(el);
    } else if (tok.type === 'del') {
      const el = document.createElement('s'); el.textContent = tok.val; container.appendChild(el);
    } else if (tok.type === 'code') {
      const el = document.createElement('code'); el.className = 'md-code'; el.textContent = tok.val; container.appendChild(el);
    }
  }
}

export function renderMarkdown(text, container) {
  const HEADING      = /^(#{1,3})\s+(.+)$/;
  const SMALL_HEADING = /^-#\s+(.+)$/;
  const BLOCKQUOTE   = /^>\s?(.*)/;

  const blocks = text.split(/\n{2,}/);
  for (const block of blocks) {
    if (!block.trim()) continue;
    const lines = block.split('\n');
    const firstLine = lines[0];
    const smMatch = firstLine.match(SMALL_HEADING);
    const hMatch  = firstLine.match(HEADING);

    if (smMatch) {
      const el = document.createElement('div');
      el.className = 'md-small-heading';
      parseInline(smMatch[1], el);
      container.appendChild(el);
      if (lines.length > 1) {
        const p = document.createElement('p');
        lines.slice(1).forEach((line, i) => {
          parseInline(line, p);
          if (i < lines.length - 2) p.appendChild(document.createElement('br'));
        });
        container.appendChild(p);
      }
    } else if (hMatch) {
      const level = Math.min(hMatch[1].length + 2, 6); // h3-h5
      const el = document.createElement('h' + level);
      el.className = 'md-heading';
      parseInline(hMatch[2], el);
      container.appendChild(el);
      if (lines.length > 1) {
        const p = document.createElement('p');
        lines.slice(1).forEach((line, i) => {
          parseInline(line, p);
          if (i < lines.length - 2) p.appendChild(document.createElement('br'));
        });
        container.appendChild(p);
      }
    } else if (lines.every(l => BLOCKQUOTE.test(l))) {
      const bq = document.createElement('blockquote');
      bq.className = 'md-blockquote';
      lines.forEach((line, i) => {
        const m = line.match(BLOCKQUOTE);
        parseInline(m ? m[1] : line, bq);
        if (i < lines.length - 1) bq.appendChild(document.createElement('br'));
      });
      container.appendChild(bq);
    } else {
      const p = document.createElement('p');
      lines.forEach((line, i) => {
        parseInline(line, p);
        if (i < lines.length - 1) p.appendChild(document.createElement('br'));
      });
      container.appendChild(p);
    }
  }
}
