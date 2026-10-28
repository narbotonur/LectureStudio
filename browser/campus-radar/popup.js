const $ = id => document.getElementById(id);
async function refresh() {
  const {courses = [], token = '', status = 'No course watched yet.'} = await chrome.storage.local.get(['courses','token','status']);
  $('token').value = token;
  $('courses').replaceChildren(...courses.map(c => { const li = document.createElement('li'); li.textContent = c; return li; }));
  $('status').textContent = status;
  const alarm = await chrome.alarms.get('campus');
  $('next').textContent = courses.length && alarm
    ? 'Next scheduled check: ' + new Date(alarm.scheduledTime).toLocaleString() + '. Chrome can delay checks.'
    : courses.length ? 'Automatic check is not scheduled. Choose Watch this course again.' : 'Automatic checks stopped.';
}
$('watch').addEventListener('click', async () => {
  const token = $('token').value.trim();
  if (!/^[A-Za-z0-9_-]{43}$/.test(token)) { $('status').textContent = 'Enable browser receiver in Lecture Studio and paste its pairing code.'; return; }
  const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  const p = CampusCore.pathInfo(tab?.url || '');
  if (!p) { $('status').textContent = 'Open a NU WeBWorK course tab first.'; return; }
  const {courses = []} = await chrome.storage.local.get('courses');
  if (!courses.includes(p.course)) courses.push(p.course);
  await chrome.storage.local.set({courses, token, status: 'Watching enabled. Checking…'});
  await chrome.runtime.sendMessage({type: 'sync'});
  await chrome.runtime.sendMessage({type: 'poll'});
  refresh();
});
$('check').addEventListener('click', async () => { await chrome.runtime.sendMessage({type: 'poll'}); refresh(); });
$('stop').addEventListener('click', async () => {
  await chrome.storage.local.set({courses: [], status: 'Watching stopped.'});
  await chrome.storage.local.remove('token');
  await chrome.runtime.sendMessage({type: 'sync'});
  refresh();
});
refresh();
