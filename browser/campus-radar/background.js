importScripts('core.js');
const ENDPOINT = 'http://127.0.0.1:8768';
let running = false;
async function captureTab(tab, course) {
  let timer;
  try {
    return await Promise.race([
      chrome.tabs.sendMessage(tab.id, {type: 'capture', course}),
      new Promise((_, reject) => { timer = setTimeout(() => reject(Error('Course tab did not respond')), 20000); })
    ]);
  } finally { clearTimeout(timer); }
}
async function post(path, body, token) {
  const current = await chrome.storage.local.get(['courses','token']);
  if (current.token !== token || !(current.courses || []).includes(body.source?.name || body.source_id?.slice(3))) return false;
  const response = await fetch(ENDPOINT + path, {method: 'POST',
    headers: {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token},
    body: JSON.stringify(body), signal: AbortSignal.timeout(10000)});
  if (!response.ok) throw Error('Local receiver rejected the capture. Check pairing.');
  return true;
}
async function poll() {
  if (running) return;
  running = true;
  try {
    const {courses = [], token = ''} = await chrome.storage.local.get(['courses','token']);
    if (!courses.length || !token) return;
    const tabs = await chrome.tabs.query({url: CampusCore.HOST + '/webwork2/*'});
    for (const course of courses) {
      const candidates = tabs.filter(t => CampusCore.pathInfo(t.url)?.course === course)
        .sort((a, b) => Number(b.active) - Number(a.active));
      let snapshot;
      let captureError = 'Course adapter is not loaded. Reload the signed-in course tab.';
      try {
        // Reloading an unpacked extension invalidates existing content scripts.
        // Try another already-open tab if the first is stale; never open tabs or log in.
        for (const tab of candidates) {
          try {
            const result = await captureTab(tab, course);
            if (result?.snapshot) { snapshot = result.snapshot; break; }
            if (typeof result?.error === 'string' && result.error.startsWith('Capture unavailable at ')) captureError = result.error.slice(0, 200);
          } catch {}
        }
        if (!snapshot) throw Error();
      } catch {
        try { await post('/failure', {source_id: 'ww.' + course,
          checked_at: new Date().toISOString(), reason: captureError}, token); } catch {}
        await chrome.storage.local.set({status: 'Check unavailable. ' + captureError});
        continue;
      }
      try {
        if (!await post('/capture', snapshot, token)) continue;
        await chrome.storage.local.set({status: snapshot.complete ? 'Captured at ' + new Date().toLocaleString() : 'Partial capture: review coverage in Lecture Studio.'});
      } catch {
        await chrome.storage.local.set({status: 'Lecture Studio receiver unavailable or pairing rejected. No successful delivery.'});
      }
    }
  } finally { running = false; }
}
async function syncAlarm() {
  const {courses = []} = await chrome.storage.local.get('courses');
  if (courses.length) {
    if (!await chrome.alarms.get('campus')) await chrome.alarms.create('campus', {periodInMinutes: 5});
  } else await chrome.alarms.clear('campus');
}
chrome.alarms.onAlarm.addListener(a => { if (a.name === 'campus') poll(); });
chrome.runtime.onStartup.addListener(syncAlarm);
chrome.runtime.onInstalled.addListener(syncAlarm);
chrome.runtime.onMessage.addListener((m, sender, reply) => {
  if (sender.id !== chrome.runtime.id || sender.url !== chrome.runtime.getURL('popup.html')) return;
  if (m.type === 'poll') { poll().then(() => reply({ok: true}), () => reply({ok: false})); return true; }
  if (m.type === 'sync') { syncAlarm().then(() => reply({ok: true})); return true; }
});
chrome.storage.local.setAccessLevel({accessLevel: 'TRUSTED_CONTEXTS'});
syncAlarm();
