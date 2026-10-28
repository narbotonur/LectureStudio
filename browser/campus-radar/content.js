/* Runs in an isolated world on NU WeBWorK only. Never reads login fields. */
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (message.type !== 'capture' || sender.id !== chrome.runtime.id) return;
  let stage = 'course tab';
  (async () => {
    const here = CampusCore.pathInfo(location.href);
    if (!here || here.course !== message.course) throw Error('Wrong course tab');
    const url = CampusCore.HOST + '/webwork2/' + here.course;
    stage = 'course request';
    const response = await fetch(url, {credentials: 'same-origin', redirect: 'error', signal: AbortSignal.timeout(15000)});
    if (!response.ok || !response.headers.get('content-type')?.includes('text/html')) throw Error('Course page unavailable');
    const html = await response.text();
    if (html.length > 2_000_000) throw Error('Course page too large');
    stage = 'course structure';
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const heading = doc.querySelector('#page-title');
    // WeBWorK 2.20 creates section headings in JavaScript. The server HTML
    // already contains the course-specific assignment list and display labels.
    const container = doc.querySelector('#set-list-container');
    const display = doc.querySelector('#show-by-date-btn');
    if (!heading || heading.textContent.trim() !== here.course ||
        !container || display?.getAttribute('data-open-title') !== 'Open Assignments' ||
        doc.querySelector('input[type=password]')) throw Error('Sign in or unsupported course page');
    const items = new Map();
    stage = 'assignment cards';
    let complete = true;
    for (const anchor of container.querySelectorAll('li[data-set-type] a[href]')) {
      const href = new URL(anchor.getAttribute('href'), url + '/').href;
      const p = CampusCore.pathInfo(href);
      if (!p?.set || p.course !== here.course) continue;
      const card = anchor.closest('li');
      const text = CampusCore.cardText(card);
      if (!/\bRegular Assignment\b/.test(text)) {
        if (/\bOpen\.|\bDue\s|Answers available for review/.test(text)) complete = false;
        continue;
      }
      const item = CampusCore.itemFromCard(here.course, href, anchor.textContent, text);
      if (!item) { complete = false; continue; }
      const previous = items.get(item.external_id);
      if (previous && JSON.stringify(previous) !== JSON.stringify(item)) complete = false;
      items.set(item.external_id, item);
      if (item.status === 'unknown' || (item.raw_due_text && !item.due_at) || (item.status === 'open' && !item.due_at)) complete = false;
    }
    // An empty list is never treated as a successful check of this adapter.
    if (!items.size || items.size > 500) throw Error('No supported assignment cards; coverage unknown');
    return {source: {source_id: 'ww.' + here.course, kind: 'webwork', name: here.course,
      url, scope: 'course'}, checked_at: new Date().toISOString(), complete, items: [...items.values()]};
  })().then(snapshot => reply({snapshot}), () => reply({error: 'Capture unavailable at ' + stage + '. Check sign-in and reload the course tab.'}));
  return true;
});
