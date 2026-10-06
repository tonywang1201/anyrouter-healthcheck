export const LABELS = {success:'可用', failure:'失败', account_restricted:'账号受限', unknown:'未知'};
export const REASONS = {ok:'有效回复',invalid_api_key:'密钥无效',permission_denied:'权限不足',quota_exceeded:'额度不足',rate_limited:'请求限流',endpoint_or_model_not_found:'接口或模型不存在',invalid_request:'请求参数不兼容',upstream_error:'服务端错误',access_denied:'访问被拒绝 / WAF',http_error:'HTTP 错误',timeout:'请求超时',network_error:'网络错误',invalid_json:'非 JSON 回复',invalid_response:'回复结构异常',empty_response:'空回复',incomplete_response:'生成未完成 / token 上限',response_too_large:'回复超过大小限制',monitor_error:'检测器错误',monitor_not_configured:'未配置检测密钥'};
export function currentStatus(latest, now, staleMinutes) {
  if (!latest || !Number.isFinite(Date.parse(latest.checked_at))) return 'unknown';
  const age = now - Date.parse(latest.checked_at);
  return age < -60000 || age > staleMinutes * 60000 ? 'unknown' : latest.status;
}
export function sampleRate(checks) {
  const completed = checks.filter(c => c.status !== 'unknown');
  return completed.length ? completed.filter(c => c.status === 'success').length / completed.length * 100 : null;
}
export function windowStats(checks, now, hours, intervalMinutes, startedAt) {
  const since=now-hours*3600000;
  const completed=checks.filter(check=>check.status!=='unknown'&&Date.parse(check.checked_at)>=since&&Date.parse(check.checked_at)<=now);
  const latencies=completed.filter(check=>check.status==='success'&&check.latency_ms!=null).map(check=>check.latency_ms).sort((a,b)=>a-b);
  const interval=intervalMinutes*60000;
  const start=startedAt ? Math.max(since,Date.parse(startedAt)) : now;
  const expected=startedAt ? Math.max(0,Math.floor(now/interval)-Math.floor(start/interval)+1) : 0;
  const slots=new Set(completed.map(check=>Math.floor(Date.parse(check.checked_at)/interval)));
  return {attempts:completed.length,success_rate:sampleRate(completed),coverage:expected?Math.min(1,slots.size/expected)*100:null,
    p50_ms:latencies.length?latencies[Math.floor((latencies.length-1)/2)]:null,
    p95_ms:latencies.length?latencies[Math.max(0,Math.ceil(latencies.length*.95)-1)]:null};
}
export function timelineSlots(checks, now, intervalMinutes, hours = 24) {
  const interval = intervalMinutes * 60000;
  const lastSlot = Math.floor(now / interval);
  const count = Math.ceil(hours * 60 / intervalMinutes);
  const buckets = Array.from({length:count}, (_, i) => ({time:(lastSlot - count + 1 + i) * interval, status:'unknown', check:null}));
  for (const check of checks) {
    const instant = Date.parse(check.checked_at);
    if (instant > now) continue;
    const index = Math.floor(instant / interval) - (lastSlot - count + 1);
    if (index >= 0 && index < buckets.length && (!buckets[index].check || instant >= Date.parse(buckets[index].check.checked_at))) {
      buckets[index].status = check.status;
      buckets[index].check = check;
    }
  }
  return buckets;
}
export function latencySegments(checks, intervalMinutes) {
  const sorted = [...checks].sort((a,b) => Date.parse(a.checked_at)-Date.parse(b.checked_at));
  const segments = [];
  let segment = [];
  for (const check of sorted) {
    const previous = segment.at(-1);
    if (check.status !== 'success' || check.latency_ms == null) {
      if (segment.length) segments.push(segment);
      segment = [];
      continue;
    }
    if (previous && Date.parse(check.checked_at)-Date.parse(previous.checked_at) > intervalMinutes * 60000 * 1.8) {
      segments.push(segment);
      segment = [];
    }
    segment.push(check);
  }
  if (segment.length) segments.push(segment);
  return segments;
}
export function formatTime(value, full = false) {
  if (!value) return '尚无记录';
  return new Intl.DateTimeFormat('zh-CN', {timeZone:'Asia/Hong_Kong', month:'2-digit',day:'2-digit', hour:'2-digit',minute:'2-digit', ...(full ? {year:'numeric',second:'2-digit'} : {}),hourCycle:'h23'}).format(new Date(value));
}
export function percent(value) { return value == null ? '—' : value.toFixed(1) + '%'; }
export function duration(value) { return value == null ? '—' : (value / 1000).toFixed(2) + ' s'; }
