import {LABELS,REASONS,currentStatus,timelineSlots,latencySegments,windowStats,formatTime,percent,duration} from './status.mjs';

const $ = id => document.getElementById(id);
let manifest, selectedModel, selectedHours = 24, provider = 'all', query = '', requestVersion = 0;
const cache = new Map();
let recentChecks = [];
let recentLoaded = false;
let detailChecks = [];

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}
function badge(status) {
  const node = element('span', `badge ${status}`);
  node.append(element('i'), document.createTextNode(LABELS[status] || LABELS.unknown));
  return node;
}
function statusOf(model) { return currentStatus(model.latest, Date.now(), manifest.stale_after_minutes); }
function nowForHistory() { return Date.now(); }
function detailStats(model,checks) {
  const stats=windowStats(checks,Date.now(),selectedHours,manifest.interval_minutes,model.started_at);
  $('detail-rate').textContent=percent(stats.success_rate);
  $('detail-coverage').textContent=percent(stats.coverage);
  $('detail-p50').textContent=duration(stats.p50_ms);
  $('detail-p95').textContent=duration(stats.p95_ms);
}

async function json(url) {
  const response = await fetch(new URL(url, location.href), {cache:'no-store'});
  if (!response.ok) throw new Error('Data unavailable');
  return response.json();
}
async function checksFor(hours) {
  const since = new Date(Date.now() - hours * 3600000).toISOString().slice(0,10);
  const files = manifest.history.filter(entry => entry.date >= since);
  const collected = [];
  // Keep downloads bounded, and reuse already loaded daily files between windows.
  for (let start=0; start<files.length; start+=4) {
    const batch = await Promise.all(files.slice(start,start+4).map(async entry => {
      if (!cache.has(entry.url)) cache.set(entry.url, json(entry.url).catch(error => { cache.delete(entry.url); throw error; }));
      return (await cache.get(entry.url)).checks;
    }));
    for (const checks of batch) collected.push(...checks);
  }
  return collected.filter(check => Date.parse(check.checked_at) >= Date.now()-hours*3600000 && Date.parse(check.checked_at) <= Date.now());
}

function renderSummary() {
  const counts = {success:0,failure:0,account_restricted:0,unknown:0};
  for (const model of manifest.models) counts[statusOf(model)]++;
  for (const [status,count] of Object.entries(counts)) $(`count-${status}`).textContent = count;
  $('model-total').textContent = `/ ${manifest.models.length} 个模型`;
  $('last-run').textContent = manifest.last_run_at ? formatTime(manifest.last_run_at,true) : '等待首次检测';
  $('schedule-label').textContent = `每 ${manifest.interval_minutes} 分钟检测`;
  $('stale-label').textContent = `超过 ${manifest.stale_after_minutes} 分钟未收到新记录`;
  $('probe-location').textContent = manifest.probe_location;
  $('demo-banner').hidden = !manifest.is_demo;
  document.querySelector('.th-note').textContent=`每格 ${manifest.interval_minutes} 分钟`;
  document.title = manifest.title;
}
function renderModels() {
  const models = manifest.models.filter(model => (provider === 'all' || model.provider === provider) && model.id.toLowerCase().includes(query));
  $('visible-count').textContent = models.length;
  const fragment = document.createDocumentFragment();
  for (const model of models) {
    const tr = element('tr', 'model-row' + (selectedModel === model.id ? ' selected' : ''));
    const modelCell = element('td');
    const button = element('button','model-button');
    button.type = 'button';
    button.setAttribute('aria-label', `查看 ${model.id} 历史`);
    button.addEventListener('click', () => selectModel(model.id));
    const name = element('span','model-name');
    const symbol = model.provider === 'Anthropic' ? '✳' : model.provider === 'Google' ? '✦' : '◎';
    name.append(element('span', `provider-icon ${model.provider.toLowerCase()}`, symbol),element('span',null,model.id));
    button.append(name,element('span','model-time',model.latest ? `${formatTime(model.latest.checked_at)} · ${model.protocol}` : '等待首次检测'));
    modelCell.append(button);
    const statusCell = element('td'); statusCell.append(badge(statusOf(model)));
    statusCell.title = statusOf(model) === 'unknown' && model.latest ? '最近记录已过期，不能代表当前状态' : REASONS[model.latest?.reason] || '尚未检测';
    const historyCell = element('td');
    const timeline = element('div','timeline');
    const slots = timelineSlots(recentChecks.filter(check => check.model === model.id),nowForHistory(),manifest.interval_minutes);
    timeline.style.gridTemplateColumns = `repeat(${slots.length},1fr)`;
    for (const slot of slots) {
      const cell = element('span',slot.status);
      cell.title = `${formatTime(new Date(slot.time).toISOString())} · ${slot.check ? LABELS[slot.status]+' · '+duration(slot.check.latency_ms) : '未采样'}`;
      timeline.append(cell);
    }
    const labels = element('div','timeline-labels'); labels.append(element('span',null,'24 小时前'),element('span',null,'现在'));
    historyCell.append(timeline,labels);
    const stats=recentLoaded ? windowStats(recentChecks.filter(check=>check.model===model.id),Date.now(),24,manifest.interval_minutes,model.started_at) : model.stats['24'];
    const rateCell = element('td','metric',percent(stats.success_rate));
    rateCell.append(element('small',null,`${stats.attempts} 次调用`));
    const latencyCell = element('td','latency latency-cell',duration(model.latest?.latency_ms));
    const detailCell = element('td');
    const detailButton = element('button','detail-button','↗'); detailButton.setAttribute('aria-label',`打开 ${model.id} 图表`); detailButton.addEventListener('click',()=>selectModel(model.id)); detailCell.append(detailButton);
    tr.append(modelCell,statusCell,historyCell,rateCell,latencyCell,detailCell); fragment.append(tr);
  }
  if (!models.length) { const tr = element('tr');const cell=element('td','empty-state','没有匹配的模型');cell.colSpan=6;tr.append(cell);fragment.append(tr); }
  $('models-body').replaceChildren(fragment);
}

function svg(tag, attributes={}, text) {
  const node = document.createElementNS('http://www.w3.org/2000/svg',tag);
  for (const [key,value] of Object.entries(attributes)) node.setAttribute(key,String(value));
  if (text != null) node.textContent = text;
  return node;
}
function renderChart(checks) {
  if (!checks.length) { $('chart').replaceChildren(element('div','empty-state','此时间范围内暂无检测记录'));return; }
  const width=1050,height=250,left=48,right=18,top=18,bottom=32;
  const now=Date.now(),since=now-selectedHours*3600000;
  const maxLatency=Math.max(1000,...checks.map(check=>check.latency_ms || 0));
  const upper=Math.ceil(maxLatency/1000)*1000;
  const x=value=>left+(Date.parse(value)-since)/(now-since)*(width-left-right);
  const y=value=>height-bottom-value/upper*(height-top-bottom);
  const graph=svg('svg',{viewBox:`0 0 ${width} ${height}`,role:'img','aria-label':`${selectedModel} 过去 ${selectedHours} 小时的请求耗时；曲线断开处代表缺失或失败记录`});
  for(let index=0;index<=4;index++) {
    const value=upper*index/4,yy=y(value);
    graph.append(svg('line',{x1:left,x2:width-right,y1:yy,y2:yy,class:'grid'}),svg('text',{x:left-8,y:yy+3,'text-anchor':'end'},(value/1000).toFixed(1)+'s'));
  }
  for(let index=0;index<=4;index++) {
    const value=since+(now-since)*index/4;
    graph.append(svg('text',{x:left+(width-left-right)*index/4,y:height-7,'text-anchor':index===0?'start':index===4?'end':'middle'},formatTime(new Date(value).toISOString())));
  }
  for(const segment of latencySegments(checks,manifest.interval_minutes)) {
    graph.append(svg('path',{class:'series',d:segment.map((check,index)=>`${index?'L':'M'}${x(check.checked_at).toFixed(1)},${y(check.latency_ms).toFixed(1)}`).join(' ')}));
  }
  for(const check of checks) {
    if(check.latency_ms == null) continue;
    const point=svg('circle',{cx:x(check.checked_at).toFixed(1),cy:y(check.latency_ms).toFixed(1),r:checks.length>400?1.8:3,class:`point ${check.status}`});
    point.append(svg('title',{},`${formatTime(check.checked_at,true)} · ${LABELS[check.status]} · ${duration(check.latency_ms)} · ${REASONS[check.reason] || check.reason}`));graph.append(point);
  }
  $('chart').replaceChildren(graph);
}
async function renderDetail() {
  const version=++requestVersion;
  const model=manifest.models.find(model=>model.id===selectedModel);
  if(!model) return;
  $('detail-panel').hidden=false;
  $('detail-title').textContent=model.id;
  $('detail-subtitle').textContent=`${model.provider} · ${model.protocol} · ${model.latest ? REASONS[model.latest.reason] : '等待首次检测'}`;
  const stats=model.stats[String(selectedHours)];
  $('detail-rate').textContent=percent(stats.success_rate);
  $('detail-coverage').textContent=percent(stats.coverage);
  $('detail-p50').textContent=duration(stats.p50_ms);
  $('detail-p95').textContent=duration(stats.p95_ms);
  $('chart').replaceChildren(element('div','empty-state','正在读取历史记录…'));
  $('recent-body').replaceChildren();
  try {
    const checks=(await checksFor(selectedHours)).filter(check=>check.model===selectedModel).sort((a,b)=>Date.parse(a.checked_at)-Date.parse(b.checked_at));
    if(version!==requestVersion) return;
    detailChecks=checks;
    detailStats(model,checks);
    renderChart(checks);
    const rows=document.createDocumentFragment();
    for(const check of [...checks].reverse().slice(0,10)) {
      const tr=element('tr'); const result=element('td'); result.append(badge(check.status));
      tr.append(element('td',null,formatTime(check.checked_at,true)),result,element('td',null,duration(check.latency_ms)),element('td',null,check.http_status || '—'),element('td',null,REASONS[check.reason] || '未知'),element('td',null,`${check.usage.input_tokens ?? '—'} / ${check.usage.output_tokens ?? '—'}`)); rows.append(tr);
    }
    if(!checks.length) { const tr=element('tr'),cell=element('td','empty-state','暂无记录');cell.colSpan=6;tr.append(cell);rows.append(tr); }
    $('recent-body').replaceChildren(rows);
  } catch {
    if(version===requestVersion) $('chart').replaceChildren(element('div','empty-state','历史数据暂时无法读取，请刷新重试。'));
  }
}
function selectModel(id,scroll=true) {
  selectedModel=id;renderModels();renderDetail();
  if(scroll) $('detail-panel').scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
}
async function load() {
  $('refresh').disabled=true;
  try {
    const fresh=await json('./data/status.json');
    if(fresh.schema_version!==1 || !Array.isArray(fresh.models)) throw new Error('Unknown schema');
    manifest=fresh;cache.clear();recentLoaded=false;renderSummary();renderModels();
    $('load-error').hidden=true;
    try {recentChecks=await checksFor(24);recentLoaded=true;renderModels();} catch {recentChecks=[];renderModels();$('load-error').textContent='当前状态已加载，历史文件暂时无法读取；灰色记录不代表故障。';$('load-error').hidden=false;}
    if(!selectedModel) selectedModel=manifest.models[0]?.id;
    if(selectedModel) await renderDetail();
  } catch {
    $('load-error').textContent='状态数据暂时无法读取，请稍后刷新。已有结果仍会按检测时间过期。';$('load-error').hidden=false;
    if(!manifest) {const row=element('tr'),cell=element('td','empty-state','无法读取状态数据');cell.colSpan=6;row.append(cell);$('models-body').replaceChildren(row);}
  } finally {$('refresh').disabled=false;}
}
$('refresh').addEventListener('click',load);
$('search').addEventListener('input',event=>{query=event.target.value.trim().toLowerCase();if(manifest)renderModels();});
$('provider-filters').addEventListener('click',event=>{
  const button=event.target.closest('button[data-provider]');if(!button)return;provider=button.dataset.provider;
  for(const candidate of $('provider-filters').querySelectorAll('button')) {const active=candidate===button;candidate.classList.toggle('active',active);candidate.setAttribute('aria-pressed',active);}
  if(manifest)renderModels();
});
$('window-filters').addEventListener('click',event=>{
  const button=event.target.closest('button[data-hours]');if(!button)return;selectedHours=Number(button.dataset.hours);
  for(const candidate of $('window-filters').querySelectorAll('button')) {const active=candidate===button;candidate.classList.toggle('active',active);candidate.setAttribute('aria-pressed',active);}
  if(manifest)renderDetail();
});
// Re-evaluate freshness even if a tab stays open during missed workflow runs.
setInterval(()=>{if(manifest){renderSummary();renderModels();const model=manifest.models.find(m=>m.id===selectedModel);if(model&&detailChecks.length)detailStats(model,detailChecks);}},30000);
setInterval(()=>{if(!document.hidden)load();},300000);
load();
