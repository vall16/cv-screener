export function renderMarkdown(md: string): string {
  const esc = (s: string) =>
    s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  const lines = esc(md).split('\n');
  const out: string[] = [];
  let inList = false;
  let para: string[] = [];

  const flushPara = () => {
    if (para.length) {
      out.push(`<p>${para.join(' ')}</p>`);
      para = [];
    }
  };
  const closeList = () => {
    if (inList) {
      out.push('</ul>');
      inList = false;
    }
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    const t = line.trim();
    let m: RegExpExecArray | null;

    if ((m = /^```/.exec(t))) {
      flushPara();
      closeList();
      continue;
    }
    if ((m = /^### (.*)$/.exec(t))) {
      flushPara();
      closeList();
      out.push(`<h3>${m[1]}</h3>`);
    } else if ((m = /^## (.*)$/.exec(t))) {
      flushPara();
      closeList();
      out.push(`<h2>${m[1]}</h2>`);
    } else if ((m = /^# (.*)$/.exec(t))) {
      flushPara();
      closeList();
      out.push(`<h1>${m[1]}</h1>`);
    } else if ((m = /^[-*] (.*)$/.exec(t))) {
      flushPara();
      if (!inList) {
        out.push('<ul>');
        inList = true;
      }
      out.push(`<li>${m[1]}</li>`);
    } else if (t === '') {
      flushPara();
      closeList();
    } else {
      closeList();
      para.push(t);
    }
  }
  flushPara();
  closeList();

  return out
    .join('\n')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
}