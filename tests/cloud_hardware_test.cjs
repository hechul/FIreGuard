'use strict';
const assert = require('node:assert/strict');
const {describe} = require('../static/js/cloud_hardware.js');
assert.equal(describe(null), null);
const noAck = describe({ledStatus: 'disconnected', ledCommandAck: false,
  plannedLedLogicalIndices: [61], plannedFireLogicalIndices: [56],
  ledIndices: [62], ledLogicalIndices: [61]});
assert.match(noAck.planned, /경로 62 \(1개\).*화재 57 \(1개\)/);
assert.match(noAck.applied, /확인된 LED 명령 없음/);
assert.doesNotMatch(noAck.applied, /전송 슬롯/);
assert.match(noAck.note, /N28과 N35.*62번/);
const ack = describe({ledStatus: 'active', ledCommandAck: true,
  plannedLedLogicalIndices: [61], plannedFireLogicalIndices: [],
  ledLogicalIndices: [61], fireLedLogicalIndices: [], ledIndices: [62], fireLedIndices: []});
assert.match(ack.status, /OK.*발광은 별도 미확인/);
assert.match(ack.applied, /경로 62 \(1개\).*Arduino 전송 슬롯.*경로 62 \(1개\)/);
const unknown = describe({ledStatus: 'preview', ledCommandAck: false});
assert.match(unknown.planned, /미보고/);
assert.match(unknown.applied, /실제 점등 여부 미확인/);
const many = describe({plannedLedLogicalIndices: Array.from({length: 40}, (_, i) => i)});
assert.match(many.planned, /외 10개 \(40개\)/);
console.log('cloud hardware display tests passed');
