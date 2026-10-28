const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const core = require('../core.js');

async function worker({tabs = [], snapshots = {}, stopDuringCapture = false, postOK = true, alarmExists = true} = {}) {
  const state = {courses: ['TEST_101'], token: 'test-token'}, posts = [], attempts = [], alarms = [];
  const chrome = {
    storage: {local: {get: async () => ({...state}), set: async values => Object.assign(state, values), setAccessLevel: async () => {}}},
    tabs: {query: async () => tabs, sendMessage: async id => {
      attempts.push(id);
      if (stopDuringCapture) state.courses = [];
      if (!snapshots[id]) throw Error('No receiving content script');
      return {snapshot: snapshots[id]};
    }},
    alarms: {get: async () => alarmExists ? {} : undefined,
      create: async (name, settings) => alarms.push({name, settings}),
      clear: async () => {}, onAlarm: {addListener: () => {}}},
    runtime: {id: 'own', getURL: p => 'chrome-extension://own/' + p,
      onInstalled: {addListener: () => {}}, onStartup: {addListener: () => {}}, onMessage: {addListener: () => {}}}
  };
  const context = {chrome, importScripts: () => {}, CampusCore: core, AbortSignal, setTimeout, clearTimeout,
    fetch: async (url, options) => { posts.push({url, body: JSON.parse(options.body)}); return {ok: postOK}; }};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../background.js'), 'utf8'), context);
  await vm.runInContext('poll()', context);
  return {state, posts, attempts, alarms};
}
const capture = {source: {name: 'TEST_101'}, complete: true};
const tab = (id, active) => ({id, active, url: core.HOST + '/webwork2/TEST_101'});
test('prefers active course tab and falls back past stale extension contexts', async () => {
  const result = await worker({tabs: [tab(1, false), tab(2, true), tab(3, false)], snapshots: {3: capture}});
  assert.deepEqual(result.attempts, [2, 1, 3]);
  assert.equal(result.posts.length, 1);
  assert.ok(result.posts[0].url.endsWith('/capture'));
  assert.match(result.state.status, /Captured/);
});
test('no tab reports failure rather than clean success; lost receiver is visible', async () => {
  let result = await worker();
  assert.ok(result.posts[0].url.endsWith('/failure'));
  assert.match(result.state.status, /unavailable/);
  result = await worker({tabs: [tab(1, true)], snapshots: {1: capture}, postOK: false});
  assert.match(result.state.status, /No successful delivery/);
});
test('stop while capture is in flight prevents sending coursework', async () => {
  const result = await worker({tabs: [tab(1, true)], snapshots: {1: capture}, stopDuringCapture: true});
  assert.equal(result.posts.length, 0);
  assert.doesNotMatch(result.state.status || '', /Captured/);
});
test('worker restores a missing five-minute alarm without resetting an existing one', async () => {
  const missing = await worker({alarmExists: false});
  assert.ok(missing.alarms.length > 0);
  assert.equal(missing.alarms[0].name, 'campus');
  assert.equal(missing.alarms[0].settings.periodInMinutes, 5);
  assert.equal((await worker()).alarms.length, 0);
});
