/* Pure parsing helpers; dates must carry an explicit UTC offset. */
(function (root) {
  const HOST = 'https://webwork-new.nu.edu.kz';
  function pathInfo(value) {
    let u;
    try { u = new URL(value, HOST); } catch { return null; }
    if (u.origin !== HOST || u.username || u.password) return null;
    const m = u.pathname.match(/^\/webwork2\/([A-Za-z0-9_-]{1,80})(?:\/([A-Za-z0-9_-]{1,100}))?\/?$/);
    if (!m) return null;
    if (m[2] && /^(grades|logout|options|hardcopy|instructor|gateway_quiz|feedback)$/i.test(m[2])) return null;
    return {course: m[1], set: m[2] || null, url: HOST + '/webwork2/' + m[1] + (m[2] ? '/' + m[2] : '')};
  }
  function parseDate(text) {
    const m = text.match(/\b(January|February|March|April|May|June|July|August|September|October|November|December) (\d{1,2}), (\d{4}), (\d{1,2}):(\d{2}):(\d{2}) (AM|PM) ([+-])(\d{2})(?::(\d{2}))?\b/);
    if (!m) return null;
    const months = ['January','February','March','April','May','June','July','August','September','October','November','December'];
    const month = months.indexOf(m[1]) + 1, day = +m[2], year = +m[3], hour = +m[4];
    if (hour < 1 || hour > 12 || +m[5] > 59 || +m[6] > 59 || +m[9] > 14 || +(m[10] || 0) > 59 || (+m[9] === 14 && +(m[10] || 0))) return null;
    const d = new Date(Date.UTC(year, month - 1, day));
    if (d.getUTCFullYear() !== year || d.getUTCMonth() !== month - 1 || d.getUTCDate() !== day) return null;
    const pad = x => String(x).padStart(2, '0');
    return `${year}-${pad(month)}-${pad(day)}T${pad(hour % 12 + (m[7] === 'PM' ? 12 : 0))}:${m[5]}:${m[6]}${m[8]}${m[9]}:${m[10] || '00'}`;
  }
  function itemFromCard(course, href, title, text) {
    const p = pathInfo(href);
    if (!p || p.course !== course || !p.set || !title.trim() || text.length > 4000) return null;
    const due = text.match(/\bDue\s+([^]*?)(?=\s+Download\b|$)/);
    const closing = text.match(/\bSet closes on\s+([^]*?)(?=\s+Download\b|$)/);
    const rawDue = due ? due[0].trim().slice(0, 1500) : '';
    const rawClose = closing ? closing[0].trim().slice(0, 1500) : '';
    return {external_id: p.set, title: title.trim().slice(0, 300), course,
      due_at: due ? parseDate(rawDue) : null, raw_due_text: rawDue,
      closes_at: closing ? parseDate(rawClose) : null, raw_close_text: rawClose,
      source_url: p.url,
      status: /Answers available for review|\bClosed\b/i.test(text) ? 'closed' : /\bOpen\./.test(text) ? 'open' : 'unknown'};
  }
  function cardText(element) {
    const chunks = [];
    function walk(node) {
      if (node.nodeType === 3) chunks.push(node.nodeValue);
      else if (!['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(node.nodeName)) {
        for (const child of node.childNodes || []) walk(child);
      }
    }
    walk(element);
    return chunks.join(' ').replace(/\s+/g, ' ').trim();
  }
  const api = {HOST, pathInfo, parseDate, itemFromCard, cardText};
  root.CampusCore = api;
  if (typeof module !== 'undefined') module.exports = api;
})(globalThis);
