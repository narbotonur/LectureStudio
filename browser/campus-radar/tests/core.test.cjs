const {test} = require('node:test');
const assert = require('node:assert/strict');
const {pathInfo, parseDate, itemFromCard, cardText} = require('../core.js');

test('canonical links drop session and user parameters; other hosts and actions excluded', () => {
  assert.equal(pathInfo('/webwork2/TEST_101/HW_6?effectiveUser=private&key=private').url,
    'https://webwork-new.nu.edu.kz/webwork2/TEST_101/HW_6');
  for (const url of ['https://attacker.example/webwork2/TEST/HW', '/webwork2/TEST/grades',
    '/webwork2/TEST/logout', '/webwork2/TEST/HW/problem/1', 'javascript:alert(1)']) assert.equal(pathInfo(url), null);
});
test('explicit offset, noon, midnight, calendar validation and no guessing', () => {
  assert.equal(parseDate('Due November 1, 2026, 11:59:00 PM +05.'), '2026-11-01T23:59:00+05:00');
  assert.equal(parseDate('March 1, 2026, 12:00:00 AM -04:30'), '2026-03-01T00:00:00-04:30');
  assert.equal(parseDate('March 1, 2026, 12:00:00 PM +00'), '2026-03-01T12:00:00+00:00');
  for (const text of ['11/01/26', 'tomorrow', 'November 1, 2026, 11:59:00 PM',
    'February 30, 2026, 11:59:00 PM +05', 'March 1, 2026, 13:00:00 AM +05',
    'March 1, 2026, 1:00:00 AM +15']) assert.equal(parseDate(text), null);
});
test('due and closing are independent, closed never means completed', () => {
  const link = '/webwork2/TEST_101/HW_6?effectiveUser=private';
  const item = itemFromCard('TEST_101', link, 'HW 6',
    'Regular Assignment HW 6 Open. Due November 1, 2026, 11:59:00 PM +05. Download');
  assert.equal(item.due_at, '2026-11-01T23:59:00+05:00');
  assert.equal(item.raw_due_text, 'Due November 1, 2026, 11:59:00 PM +05.');
  assert.equal(item.closes_at, null);
  assert.equal(item.status, 'open');
  const close = itemFromCard('TEST_101', link, 'HW 6', 'Set closes on November 1, 2026, 11:59:00 PM +05.');
  assert.equal(close.due_at, null);
  assert.equal(close.closes_at, '2026-11-01T23:59:00+05:00');
  assert.equal(itemFromCard('TEST_101', link, 'HW 6', 'Answers available for review.').status, 'closed');
  assert.equal(itemFromCard('OTHER', link, 'HW 6', 'Open.'), null);
});
test('adjacent HTML nodes retain word boundaries without relying on layout', () => {
  const element = {nodeType: 1, nodeName: 'LI', childNodes: [
    {nodeType: 1, nodeName: 'SPAN', childNodes: [{nodeType: 3, nodeValue: 'Regular Assignment'}]},
    {nodeType: 1, nodeName: 'A', childNodes: [{nodeType: 3, nodeValue: 'HW 6'}]},
    {nodeType: 3, nodeValue: 'Open. Due November 1, 2026, 11:59:00 PM +05.'},
    {nodeType: 1, nodeName: 'SCRIPT', childNodes: [{nodeType: 3, nodeValue: 'do not collect'}]},
    {nodeType: 1, nodeName: 'A', childNodes: [{nodeType: 3, nodeValue: 'Download'}]}]};
  const text = cardText(element);
  assert.equal(text, 'Regular Assignment HW 6 Open. Due November 1, 2026, 11:59:00 PM +05. Download');
  assert.equal(itemFromCard('TEST_101', '/webwork2/TEST_101/HW_6', 'HW 6', text).status, 'open');
});
