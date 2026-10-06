import test from 'node:test';
import assert from 'node:assert/strict';
import worker, {tick} from '../scheduler/worker.mjs';

const env = {DISPATCH_ENABLED:'true', GITHUB_ACTIONS_TOKEN:'test-secret'};
const now = Date.parse('2026-10-06T15:00:00Z');
const stale = {is_demo:false, models:[]};
const json = value => new Response(JSON.stringify(value));

test('disabled timer and missing token never make network calls', async () => {
  const network = () => {throw new Error('Unexpected network call');};
  assert.equal(await tick({},network), 'disabled');
  await assert.rejects(tick({DISPATCH_ENABLED:'true'},network),/not configured/);
});
test('fresh full-model data skips dispatch; a partial run does not', async () => {
  const models = Array.from({length:17}, () => ({latest:{checked_at:new Date(now-60000).toISOString()}}));
  assert.equal(await tick(env, async () => json({is_demo:false,models}),now),'fresh');
  let calls = 0;
  assert.equal(await tick(env,async () => ++calls===1 ? json({is_demo:false,models:models.slice(0,1)}) : json({workflow_runs:[{status:'queued'}]}),now),'running');
  assert.equal(calls,2);
});
test('stale data dispatches exactly once to the fixed repository without sending token to Pages', async () => {
  const calls = [];
  const outcome = await tick(env,async (url,options) => {
    calls.push({url,options});
    if(calls.length===1) return json(stale);
    if(calls.length===2) return json({workflow_runs:[{status:'completed'}]});
    return new Response(null,{status:204});
  },now);
  assert.equal(outcome,'dispatched');
  assert.equal(calls.length,3);
  assert.equal(calls[0].options.headers.Authorization,undefined);
  assert.match(calls[2].url,/^https:\/\/api\.github\.com\/repos\/tonywang1201\/anyrouter-healthcheck\/actions\/workflows\/monitor\.yml\/dispatches$/);
  assert.equal(calls[2].options.body,'{"ref":"main"}');
  assert.equal(calls[2].options.redirect,'error');
});
test('active runs prevent duplicate dispatch and API errors fail without exposing response bodies', async () => {
  assert.equal(await tick(env,async url => url.includes('github.io') ? json(stale) : json({workflow_runs:[{status:'in_progress'}]}),now),'running');
  await assert.rejects(tick(env,async url => url.includes('github.io') ? json(stale) : new Response('private-error',{status:401}),now),/^Error: Scheduler cannot read workflow runs \(HTTP 401\)$/);
});
test('public HTTP requests cannot trigger a workflow', async () => {
  assert.equal(worker.fetch().status,404);
});
