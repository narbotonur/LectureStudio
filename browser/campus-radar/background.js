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
async function post(path, body, token, manual) {
  const current = await chrome.storage.local.get(['courses', 'pausedCourses', 'token']);
  const course = body.source?.name || body.source_id?.slice(3);
  if (current.token !== token || !(current.courses || []).includes(course)
      || (!manual && (current.pausedCourses || []).includes(course))) return false;
  const response = await fetch(ENDPOINT + path, {method: 'POST',
    headers: {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token},
    body: JSON.stringify(body), signal: AbortSignal.timeout(10000)});
  if (!response.ok) throw Error('Local receiver rejected the capture. Check pairing.');
  return true;
}
async function report(course, status) {
  const {courses = [], courseStatus = {}} = await chrome.storage.local.get(['courses', 'courseStatus']);
  if (courses.includes(course)) await chrome.storage.local.set({
    status, courseStatus: {...courseStatus, [course]: status}
  });
}
async function poll(selected = null) {
  if (running) return false;
  running = true;
  try {
    const {courses = [], pausedCourses = [], token = ''} = await chrome.storage.local.get(['courses', 'pausedCourses', 'token']);
    const waiting = courses.filter(course => selected ? selected === course : !pausedCourses.includes(course));
    if (!waiting.length || !token) return true;
    const tabs = await chrome.tabs.query({url: CampusCore.HOST + '/webwork2/*'});
    for (const course of waiting) {
      const current = await chrome.storage.local.get(['courses', 'pausedCourses', 'token']);
      if (current.token !== token || !(current.courses || []).includes(course)
          || (!selected && (current.pausedCourses || []).includes(course))) continue;
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
          checked_at: new Date().toISOString(), reason: captureError}, token, Boolean(selected)); } catch {}
        await report(course, 'Check unavailable. ' + captureError);
        continue;
      }
      try {
        if (!await post('/capture', snapshot, token, Boolean(selected))) continue;
        await report(course, snapshot.complete ? 'Captured at ' + new Date().toLocaleString() : 'Partial capture: review coverage in Lecture Studio.');
      } catch {
        await report(course, 'Lecture Studio receiver unavailable or pairing rejected. No successful delivery.');
      }
    }
    return true;
  } finally { running = false; }
}
async function syncAlarm() {
  const {courses = [], pausedCourses = []} = await chrome.storage.local.get(['courses', 'pausedCourses']);
  if (courses.some(course => !pausedCourses.includes(course))) {
    if (!await chrome.alarms.get('campus')) await chrome.alarms.create('campus', {periodInMinutes: 5});
  } else await chrome.alarms.clear('campus');
}
chrome.alarms.onAlarm.addListener(a => { if (a.name === 'campus') poll(); });
chrome.runtime.onStartup.addListener(syncAlarm);
chrome.runtime.onInstalled.addListener(syncAlarm);
chrome.runtime.onMessage.addListener((m, sender, reply) => {
  if (sender.id !== chrome.runtime.id || sender.url !== chrome.runtime.getURL('popup.html')) return;
  if (m.type === 'poll') {
    poll(typeof m.course === 'string' ? m.course : null).then(ok => reply({ok}), () => reply({ok: false}));
    return true;
  }
  if (m.type === 'sync') { syncAlarm().then(() => reply({ok: true})); return true; }
});
chrome.storage.local.setAccessLevel({accessLevel: 'TRUSTED_CONTEXTS'});
syncAlarm();
