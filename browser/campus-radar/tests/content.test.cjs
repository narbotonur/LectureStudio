const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const core = require('../core.js');

async function capture({cards = [], password = false, serverStructure = true, heading = 'TEST_101', status = 200} = {}) {
  let listener;
  const anchors = cards.map(card => ({getAttribute: () => card.href,
    textContent: card.title, closest: () => ({nodeType: 1, nodeName: 'LI', childNodes: [{nodeType: 3, nodeValue: card.text}]})}));
  const doc = {querySelector: s => {
    if (s === '#page-title') return {textContent: heading};
    if (s === '#set-list-container') return serverStructure ? {querySelectorAll: () => anchors} : null;
    if (s === '#show-by-date-btn') return serverStructure ? {getAttribute: () => 'Open Assignments'} : null;
    return password ? {} : null;
  }};
  const context = {CampusCore: core, location: {href: core.HOST + '/webwork2/TEST_101/HW_1'},
    chrome: {runtime: {id: 'own-extension', onMessage: {addListener: fn => { listener = fn; }}}},
    DOMParser: class {parseFromString() { return doc; }}, AbortSignal, URL,
    fetch: async (url, opts) => {
      assert.equal(url, core.HOST + '/webwork2/TEST_101');
      assert.equal(opts.credentials, 'same-origin');
      assert.equal(opts.redirect, 'error');
      return {ok: status === 200, headers: {get: () => 'text/html'}, text: async () => '<synthetic course>'};
    }};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../content.js'), 'utf8'), context);
  return new Promise(resolve => listener({type: 'capture', course: 'TEST_101'}, {id: 'own-extension'}, resolve));
}
const card = {href: '/webwork2/TEST_101/HW_1?effectiveUser=private', title: 'HW 1',
  text: 'Regular Assignment HW 1 Open. Due November 1, 2026, 11:59:00 PM +05. Download'};

test('course acquisition excludes sidebar duplicates and user query parameters', async () => {
  const result = await capture({cards: [{...card, text: 'HW 1'}, card]});
  assert.equal(result.snapshot.complete, true);
  assert.equal(result.snapshot.items.length, 1);
  assert.equal(result.snapshot.source.source_id, 'ww.TEST_101');
  assert.equal(result.snapshot.items[0].due_at, '2026-11-01T23:59:00+05:00');
  assert.ok(!JSON.stringify(result.snapshot).includes('private'));
});
test('login, missing index evidence, empty capture, HTTP failures never become empty success', async () => {
  for (const opts of [{password: true, cards: [card]}, {serverStructure: false, cards: [card]},
    {cards: []}, {heading: 'Login', cards: [card]}, {status: 403, cards: [card]}]) {
    const result = await capture(opts);
    assert.ok(result.error);
    assert.equal(result.snapshot, undefined);
  }
});
test('server assignment container works without client-generated section headings', async () => {
  const result = await capture({cards: [{...card, href: 'HW_1?effectiveUser=private'}]});
  assert.equal(result.snapshot.complete, true);
  assert.equal(result.snapshot.items[0].source_url, core.HOST + '/webwork2/TEST_101/HW_1');
});
test('unsupported due dates and other assignment types yield partial coverage', async () => {
  let result = await capture({cards: [{...card, text: 'Regular Assignment HW 1 Open. Due tomorrow. Download'}]});
  assert.equal(result.snapshot.complete, false);
  assert.equal(result.snapshot.items[0].due_at, null);
  assert.equal(result.snapshot.items[0].raw_due_text, 'Due tomorrow.');
  result = await capture({cards: [card, {...card, href: '/webwork2/TEST_101/QUIZ', text: 'Gateway Assignment Quiz Open.'}]});
  assert.equal(result.snapshot.complete, false);
});
