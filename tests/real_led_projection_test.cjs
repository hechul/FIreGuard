'use strict';
const assert = require('node:assert/strict');
const {project, coordinates} = require('../static/js/real_led_projection.js');
const {sections} = require('../static/js/prototype_map.js');
const coords = coordinates(sections);
assert.equal(coords.length, 162);
// S2 is bottom-to-top and S3 right-to-left despite drawing order.
assert(coords[4].y > coords[35].y);
assert(coords[36].x > coords[65].x);
const h = {operationMode:'real', ledStatus:'active', ledCommandAck:true,
 ledMappingVersion:'led162-usb163-shift20-da2de217fd',
 ledLogicalIndices:[0,20,61], ledIndices:[0,21,62],
 fireLedLogicalIndices:[61,80], fireLedIndices:[62,81]};
const cloud = {enabled:true,hasTelemetry:true,stale:false,routeSource:'pi',hardware:h};
const result = project(cloud,sections);
assert.match(result.label,/추정.*발광 미확인/);
assert.deepEqual(result.points.map(p=>[p.index,p.color]),[[0,'route'],[20,'route'],[61,'fire'],[80,'fire']]);
assert.equal(project({...cloud,stale:true},sections),null);
assert.equal(project({...cloud,routeSource:'server_preview'},sections),null);
assert.equal(project({...cloud,hardware:{...h,ledCommandAck:false}},sections),null);
assert.equal(project({...cloud,hardware:{...h,ledStatus:'off'}},sections),null);
assert.equal(project({...cloud,hardware:{...h,operationMode:'simulation'}},sections),null);
assert.equal(project({...cloud,hardware:{...h,ledMappingVersion:'unknown'}},sections),null);
assert.equal(project({...cloud,hardware:{...h,ledIndices:[0,20,62]}},sections),null);
assert.equal(project({...cloud,hardware:{...h,ledLogicalIndices:[999],ledIndices:[1000]}},sections),null);
assert.equal(project(cloud,sections.slice(0,-1)),null);
console.log('PASS: projected LED commands require fresh REAL acknowledgement and known mapping');
