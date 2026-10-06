import test from 'node:test';
import assert from 'node:assert/strict';
import {currentStatus,sampleRate,timelineSlots,latencySegments,formatTime} from '../web/status.mjs';

const now=Date.parse('2026-10-06T12:00:00Z');
const check=(minutes,status='success')=>({checked_at:new Date(now-minutes*60000).toISOString(),status,latency_ms:100});

test('a successful result becomes unknown after 30 minutes, including an open tab',()=>{
  assert.equal(currentStatus(check(30),now,30),'success');
  assert.equal(currentStatus(check(31),now,30),'unknown');
  assert.equal(currentStatus(null,now,30),'unknown');
  assert.equal(currentStatus({checked_at:'invalid',status:'success'},now,30),'unknown');
  assert.equal(currentStatus(check(-10),now,30),'unknown');
});
test('sample rate excludes unknown, never assumes missed calls succeeded',()=>{
  assert.equal(sampleRate([check(0),check(15,'account_restricted'),check(30,'unknown')]),50);
  assert.equal(sampleRate([]),null);
});
test('timeline explicitly leaves missing 15-minute samples gray',()=>{
  const slots=timelineSlots([check(30),check(0,'failure')],now,15,1);
  assert.deepEqual(slots.map(slot=>slot.status),['unknown','success','unknown','failure']);
});
test('timeline keeps the most recent rerun without moving missing slots',()=>{
  const latest=check(1,'account_restricted');
  const slots=timelineSlots([latest,check(5)],now,15,1);
  assert.equal(slots.at(-2).check,latest);
  assert.equal(slots.at(-1).status,'unknown');
});
test('latency curves break across missing, failed, or unknown samples',()=>{
  const segments=latencySegments([check(0),check(15),check(30,'failure'),check(45),check(90)],15);
  assert.deepEqual(segments.map(segment=>segment.length),[1,1,2]);
});
test('all visible timestamps use Hong Kong time',()=>{
  assert.match(formatTime('2026-10-06T12:00:00Z',true),/20:00:00/);
});
