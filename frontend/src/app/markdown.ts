export function renderMarkdown(md: string): string {
  const esc = (s: string) =>
    s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  const lines = esc(md).split('\n');
  const out: string[] = [];
  let inList = false;
  let para: string[] = [];
  let inTable = false;
  let tableRows: string[][] = [];
  let tableHeaderDone = false;

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
  const flushTable = () => {
    if (!inTable) return;
    inTable = false;
    tableHeaderDone = false;
    if (tableRows.length === 0) return;
    const [header, ...body] = tableRows;
    let html = '<div class="md-table-wrap"><table class="md-table"><thead><tr>';
    for (const cell of header) html += `<th>${cell}</th>`;
    html += '</tr></thead><tbody>';
    for (const row of body) {
      html += '<tr>';
      for (const cell of row) html += `<td>${cell}</td>`;
      html += '</tr>';
    }
    html += '</tbody></table></div>';
    out.push(html);
    tableRows = [];
  };

  const parseTableRow = (line: string): string[] => {
    // Split by |, remove first and last empty elements
    const parts = line.split('|').map(c => c.trim());
    // Remove leading/trailing empty strings from split
    if (parts[0] === '') parts.shift();
    if (parts[parts.length - 1] === '') parts.pop();
    return parts;
  };

  const isSeparatorRow = (line: string): boolean => {
    // Matches |---|---| or | --- | --- |
    return /^\|?[\s:-]+\|/.test(line) && /^[\s|:-]+$/.test(line);
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    const t = line.trim();
    let m: RegExpExecArray | null;

    // Table detection
    if (t.startsWith('|') && t.endsWith('|')) {
      if (isSeparatorRow(t)) {
        // Separator row: mark header done, skip
        tableHeaderDone = true;
        continue;
      }
      flushPara();
      closeList();
      if (!inTable) {
        inTable = true;
        tableRows = [];
      }
      tableRows.push(parseTableRow(t));
      continue;
    } else if (inTable) {
      flushTable();
    }

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
  flushTable();

  return out
    .join('\n')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
}
