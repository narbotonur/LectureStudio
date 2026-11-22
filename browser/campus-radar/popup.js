const $ = id => document.getElementById(id);
let busy = false;

function action(text, serve) {
  const button = document.createElement('button');
  button.textContent = text;
  button.addEventListener('click', () => run(serve));
  return button;
}

async function run(serve) {
  if (busy) return;
  busy = true;
  let feedback = '';
  try { feedback = await serve(); }
  catch { feedback = 'Could not update monitoring. Reopen the popup and try again.'; }
  finally {
    busy = false;
    await refresh();
    if (feedback) $('status').textContent = feedback;
  }
}

async function check(course) {
  const reply = await chrome.runtime.sendMessage({type: 'poll', course});
  if (!reply?.ok) return 'A check is already running or could not start. Try again shortly.';
}

async function toggle(course) {
  const {pausedCourses = []} = await chrome.storage.local.get('pausedCourses');
  const paused = pausedCourses.includes(course);
  await chrome.storage.local.set({
    pausedCourses: paused ? pausedCourses.filter(item => item !== course) : [...pausedCourses, course]
  });
  await chrome.runtime.sendMessage({type: 'sync'});
  return paused ? 'Automatic checks resumed.' : 'Automatic checks paused for this course.';
}

async function remove(course) {
  const {courses = [], pausedCourses = [], courseStatus = {}} = await chrome.storage.local.get(['courses','pausedCourses','courseStatus']);
  delete courseStatus[course];
  await chrome.storage.local.set({courses: courses.filter(item => item !== course),
    pausedCourses: pausedCourses.filter(item => item !== course), courseStatus});
  await chrome.runtime.sendMessage({type: 'sync'});
  return 'Course removed from monitoring.';
}

async function refresh() {
  const {courses = [], pausedCourses = [], courseStatus = {}, token = '', status = 'No course watched yet.'} =
    await chrome.storage.local.get(['courses','pausedCourses','courseStatus','token','status']);
  $('token').value = token;
  $('courses').replaceChildren(...courses.map(course => {
    const row = document.createElement('li');
    const title = document.createElement('strong');
    const paused = pausedCourses.includes(course);
    title.textContent = course + (paused ? ' · Paused' : ' · Watching');
    const last = document.createElement('div');
    last.textContent = courseStatus[course] || 'No recent check saved.';
    row.append(title, last, action(paused ? 'Resume' : 'Pause', () => toggle(course)),
      action('Check this course', () => check(course)), action('Remove', () => remove(course)));
    return row;
  }));
  $('status').textContent = status;
  const alarm = await chrome.alarms.get('campus');
  const active = courses.some(course => !pausedCourses.includes(course));
  $('next').textContent = active && alarm
    ? 'Next scheduled check: ' + new Date(alarm.scheduledTime).toLocaleString() + '. Chrome can delay checks.'
    : active ? 'Automatic check is not scheduled. Choose Watch this course again.' : 'Automatic checks paused or stopped.';
}
$('watch').addEventListener('click', () => run(async () => {
  const token = $('token').value.trim();
  if (!/^[A-Za-z0-9_-]{43}$/.test(token)) return 'Enable browser receiver in Lecture Studio and paste its pairing code.';
  const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  const p = CampusCore.pathInfo(tab?.url || '');
  if (!p) return 'Open a NU WeBWorK course tab first.';
  const {courses = [], pausedCourses = []} = await chrome.storage.local.get(['courses','pausedCourses']);
  if (!courses.includes(p.course)) courses.push(p.course);
  await chrome.storage.local.set({courses, token, pausedCourses: pausedCourses.filter(item => item !== p.course), status: 'Watching enabled. Checking…'});
  await chrome.runtime.sendMessage({type: 'sync'});
  return check(p.course);
}));
$('check').addEventListener('click', () => run(() => check()));
$('stop').addEventListener('click', () => run(async () => {
  await chrome.storage.local.set({courses: [], pausedCourses: [], courseStatus: {}, status: 'Watching stopped.'});
  await chrome.storage.local.remove('token');
  await chrome.runtime.sendMessage({type: 'sync'});
}));
refresh();
