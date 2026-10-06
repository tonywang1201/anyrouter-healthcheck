// Optional Cloudflare timer. AnyRouter credentials remain in GitHub Secrets.
const WORKFLOW = 'https://api.github.com/repos/tonywang1201/anyrouter-healthcheck/actions/workflows/monitor.yml';
const STATUS = 'https://tonywang1201.github.io/anyrouter-healthcheck/data/status.json';
const ACTIVE = new Set(['queued', 'in_progress', 'waiting', 'pending', 'requested']);
const FRESH_MS = 12 * 60 * 1000;

async function request(fetcher, url, options = {}) {
  try {
    return await fetcher(url, {...options, redirect:'error', signal:AbortSignal.timeout(12000)});
  } catch {
    throw new Error('Scheduler network request failed');
  }
}

export async function tick(env, fetcher = fetch, now = Date.now()) {
  if (env.DISPATCH_ENABLED !== 'true') return 'disabled';
  if (!env.GITHUB_ACTIONS_TOKEN?.trim()) throw new Error('Scheduler token is not configured');
  const response = await request(fetcher, STATUS, {headers:{'Cache-Control':'no-cache'}});
  if (response.ok) {
    let status;
    try { status = await response.json(); } catch { status = null; }
    if (status?.is_demo === false && status.models?.length === 17 && status.models.every(model => {
      const checked = Date.parse(model.latest?.checked_at);
      return Number.isFinite(checked) && now >= checked && now - checked < FRESH_MS;
    })) return 'fresh';
  }
  const headers = {'Accept':'application/vnd.github+json',
    'Authorization':`Bearer ${env.GITHUB_ACTIONS_TOKEN}`,
    'X-GitHub-Api-Version':'2026-03-10', 'User-Agent':'anyrouter-healthcheck-scheduler'};
  const runs = await request(fetcher, `${WORKFLOW}/runs?per_page=2`, {headers});
  if (!runs.ok) throw new Error(`Scheduler cannot read workflow runs (HTTP ${runs.status})`);
  let recent;
  try { recent = await runs.json(); } catch { throw new Error('Scheduler received invalid workflow metadata'); }
  if (!Array.isArray(recent.workflow_runs)) throw new Error('Scheduler received invalid workflow metadata');
  if (recent.workflow_runs.some(run => ACTIVE.has(run.status))) return 'running';
  const dispatched = await request(fetcher, `${WORKFLOW}/dispatches`, {
    method:'POST', headers:{...headers,'Content-Type':'application/json'}, body:JSON.stringify({ref:'main'})
  });
  if (![200,204].includes(dispatched.status)) {
    throw new Error(`Scheduler dispatch failed (HTTP ${dispatched.status})`);
  }
  return 'dispatched';
}

export default {
  async scheduled(_event, env) {
    // Log only a fixed outcome, never request headers, secrets or response bodies.
    console.log(`Monitor timer: ${await tick(env)}`);
  },
  fetch() { return new Response('Not found', {status:404}); }
};
