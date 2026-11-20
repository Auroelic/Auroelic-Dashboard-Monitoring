(() => {
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const P = {
  sliders: '<path d="M21 4h-7M10 4H3M21 12h-9M8 12H3M21 20h-5M12 20H3M14 2v4M8 10v4M16 18v4"/>',
  cpu: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M15 2v2M15 20v2M2 15h2M2 9h2M20 15h2M20 9h2M9 2v2M9 20v2"/>',
  mem: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5M3 12a9 3 0 0 0 18 0"/>',
  disk: '<path d="M22 12H2M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11zM6 16h.01M10 16h.01"/>',
  net: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
  down: '<path d="M12 5v14M19 12l-7 7-7-7"/>', up: '<path d="M12 19V5M5 12l7-7 7 7"/>'
};
const ic = n => `<svg class="i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">${P[n]}</svg>`;
document.querySelectorAll('[data-i]').forEach(e => e.insertAdjacentHTML('afterbegin', ic(e.dataset.i)));

const U = ['B','KB','MB','GB','TB','PB'];
const bytes = (n, d = 1) => { n = Math.max(0, n || 0); let i = 0; while (n >= 1024 && i < 5) { n /= 1024; i++; } return (i ? n.toFixed(d) : Math.round(n)) + ' ' + U[i]; };
const rate = n => bytes(n) + '/s';
const dur = s => { s = Math.floor(s); const d = Math.floor(s/86400), h = Math.floor(s%86400/3600), m = Math.floor(s%3600/60);
  return [d && d + ' d', (d || h) && h + ' h', m + ' min'].filter(Boolean).join(' '); };
const clock = (t, sec) => new Date(t*1000).toLocaleTimeString('en-US', {hour:'2-digit', minute:'2-digit', ...(sec ? {second:'2-digit'} : {})});
const stamp = t => new Date(t*1000).toLocaleString('en-US', {day:'numeric', month:'short', hour:'2-digit', minute:'2-digit'});

const S = {range:'5m', points:[], snap:null, sys:null, th:null, alerts:[], ws:null, retry:0};
const tok = () => sessionStorage.getItem('auroelic_token') || '';
async function api(path, opt = {}) {
  const r = await fetch(path, {...opt, headers: {'Content-Type':'application/json', 'Authorization':'Bearer ' + tok(), ...(opt.headers || {})}});
  if (r.status === 401) { openSettings('A token is required to access this server.'); throw new Error('401'); }
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(Array.isArray(body.detail) ? body.detail.map(d => d.msg).join('; ') : body.detail || r.statusText);
  return body;
}

const lv = (p, m) => !S.th ? 'ok' : p >= S.th[m+'_crit'] ? 'crit' : p >= S.th[m+'_warn'] ? 'warn' : 'ok';
function renderStrip(s) {
  const cell = (m, icon, label, p, sub) => `<div class="m ${lv(p, m)}"><div class="ml">${ic(icon)}<span>${label}</span></div>
    <div class="mv">${p.toFixed(1)}<small>%</small></div><div class="meter"><i style="width:${Math.min(100,p)}%"></i></div><div class="ms">${sub}</div></div>`;
  const load = s.cpu.load ? ` | load ${s.cpu.load.join(' ')}` : '';
  $('#strip').innerHTML =
    cell('cpu', 'cpu', 'CPU', s.cpu.percent, `${s.cpu.cores_logical} core${load}`) +
    cell('mem', 'mem', 'Memory', s.mem.percent, `${bytes(s.mem.used)} of ${bytes(s.mem.total)}`) +
    cell('disk', 'disk', 'Disk', s.disk.percent, `${bytes(s.disk.used)} used, ${bytes(s.disk.free)} free`) +
    `<div class="m"><div class="ml">${ic('net')}<span>Network</span></div>
      <div class="nr"><span>${ic('down')}Download</span>${rate(s.net.rx_rate)}</div><div class="nr"><span>${ic('up')}Upload</span>${rate(s.net.tx_rate)}</div>
      <div class="ms">Total ${bytes(s.net.rx_total)} in, ${bytes(s.net.tx_total)} out</div></div>`;
}
function renderInfo(s) {
  const y = S.sys; if (!y) return;
  const rows = [['Hostname', y.hostname], ['Operating system', y.os], ['Kernel', y.kernel], ['IP address', y.ip],
    ['Uptime', s ? dur(s.uptime.seconds) : '-'], ['Last boot', stamp(y.boot_time)],
    ['Processor', y.cpu_model], ['Core count', `${y.cores_physical} physical, ${y.cores_logical} logical`],
    ['Architecture', y.arch], ['Total RAM', bytes(y.ram_total)]];
  $('#info').innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join('');
}
function renderDisks(s) {
  $('#disks').innerHTML = '<tr><th>Mount</th><th>Device</th><th>Type</th><th class="n">Capacity</th><th class="n">Used</th><th class="n">Free</th><th class="n">Usage</th></tr>' +
    s.disk.partitions.map(p => `<tr><td>${esc(p.mountpoint)}</td><td>${esc(p.device)}</td><td>${esc(p.fstype)}</td><td class="n">${bytes(p.total)}</td><td class="n">${bytes(p.used)}</td><td class="n">${bytes(p.free)}</td><td class="n">${p.percent.toFixed(1)}%</td></tr>`).join('');
}
function renderAlerts() {
  const el = $('#alerts');
  if (!S.alerts.length) { el.innerHTML = '<li class="none">No alerts yet. Alerts appear when CPU, memory, or disk exceeds a threshold.</li>'; return; }
  el.innerHTML = S.alerts.map(a => `<li class="${a.resolved_ts ? 'done' : a.severity}"><span class="sv"></span>
    <b>${esc(a.message)}</b><small>${a.severity === 'critical' ? 'Critical' : 'Warning'} | ${stamp(a.ts)} | ${a.resolved_ts ? 'resolved ' + clock(a.resolved_ts) : 'active'}</small>
    <small>${esc(a.cause || '')}</small></li>`).join('');
}

function draw(el, keys, o = {}) {
  const w = el.clientWidth || 300, h = 150, pl = 66, pr = 8, pt = 8, pb = 20, pts = S.points;
  if (pts.length < 2) { el.innerHTML = '<div class="empty">Collecting data</div>'; return; }
  const t0 = pts[0].t, t1 = pts[pts.length-1].t;
  const max = o.max ?? Math.max(1, ...pts.flatMap(p => keys.map(k => p[k.k] || 0))) * 1.15;
  const x = t => pl + (t - t0) / (t1 - t0 || 1) * (w - pl - pr), y = v => pt + (1 - Math.min(v, max) / max) * (h - pt - pb);
  let g = '';
  for (let i = 0; i <= 4; i++) { const v = max * i / 4, yy = y(v);
    g += `<line x1="${pl}" x2="${w-pr}" y1="${yy}" y2="${yy}" stroke="#272333"/><text x="${pl-6}" y="${yy+4}" text-anchor="end" fill="#8f88a3" font-size="11">${o.fmt(v)}</text>`; }
  const thr = o.th && S.th ? `<line x1="${pl}" x2="${w-pr}" y1="${y(S.th[o.th+'_warn'])}" y2="${y(S.th[o.th+'_warn'])}" stroke="#d9b36a" stroke-dasharray="4 4" opacity=".6"/>` : '';
  const lines = keys.map(k => `<path d="M${pts.map(p => x(p.t).toFixed(1) + ',' + y(p[k.k] || 0).toFixed(1)).join('L')}" fill="none" stroke="var(${k.c})" stroke-width="1.6" stroke-linejoin="round"/>`).join('');
  const sec = S.range === '5m';
  el.innerHTML = `<svg width="${w}" height="${h}" role="img">${g}${thr}${lines}
    <text x="${pl}" y="${h-4}" fill="#8f88a3" font-size="11">${clock(t0, sec)}</text><text x="${w-pr}" y="${h-4}" text-anchor="end" fill="#8f88a3" font-size="11">${clock(t1, sec)}</text></svg>`;
}
const pct = v => Math.round(v) + '%';
function charts() {
  draw($('#c-cpu'), [{k:'cpu', c:'--c1'}], {max:100, fmt:pct, th:'cpu'});
  draw($('#c-mem'), [{k:'mem', c:'--c2'}], {max:100, fmt:pct, th:'mem'});
  draw($('#c-net'), [{k:'rx', c:'--c3'}, {k:'tx', c:'--c4'}], {fmt:v => bytes(v, 0) + '/s'});
  draw($('#c-all'), [{k:'cpu', c:'--c1'}, {k:'mem', c:'--c2'}, {k:'disk', c:'--c5'}], {max:100, fmt:pct});
}

function setStatus(s) {
  const e = $('#status'), names = {online:'Online', warning:'Warning', critical:'Critical'};
  e.className = 'pill ' + (s || ''); e.querySelector('b').textContent = names[s] || 'Waiting for data';
}
function setConn(state) {
  const e = $('#conn'), m = {ok:['online', 'Monitoring connected'], retry:['warning', 'Reconnecting'], auth:['critical', 'Token required'], stale:['warning', 'Data delayed']}[state];
  e.className = 'pill quiet ' + m[0]; e.querySelector('b').textContent = m[1];
}
function onSnap(s) {
  S.snap = s; S.lastRx = Date.now();
  setStatus(s.status); setConn('ok');
  $('#updated').textContent = 'Last updated: ' + clock(s.ts, true);
  renderStrip(s); renderInfo(s); renderDisks(s);
  if (S.range === '5m') {
    S.points.push({t:s.ts, cpu:s.cpu.percent, mem:s.mem.percent, disk:s.disk.percent, rx:s.net.rx_rate, tx:s.net.tx_rate});
    while (S.points.length && S.points[0].t < s.ts - 300) S.points.shift();
    charts();
  }
}
async function loadHistory() { S.points = (await api('/api/history?range=' + S.range)).points; charts(); }
async function loadAlerts() { S.alerts = (await api('/api/alerts?limit=20')).alerts; renderAlerts(); }
async function init() {
  try {
    [S.sys, S.th] = await Promise.all([api('/api/system'), api('/api/settings')]);
    renderInfo(S.snap); await Promise.all([loadHistory(), loadAlerts()]);
  } catch (e) { console.error('Auroelic init:', e); }
}
function connect() {
  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws?token=${encodeURIComponent(tok())}`);
  S.ws = ws;
  ws.onopen = () => { S.retry = 0; };
  ws.onmessage = e => { const m = JSON.parse(e.data); if (m.type === 'snapshot') onSnap(m.data); else if (m.type === 'alert') loadAlerts().catch(() => {}); };
  ws.onclose = ev => { if (ev.code === 4401) { setConn('auth'); openSettings('A token is required to access this server.'); } else setConn('retry');
    setTimeout(connect, Math.min(10000, 1000 * 2 ** S.retry++)); };
}

const dlg = $('#dlg'), F = ['cpu_warn','cpu_crit','mem_warn','mem_crit','disk_warn','disk_crit'];
function openSettings(msg) {
  F.forEach(k => { if (S.th) $('#' + k).value = S.th[k]; });
  $('#token').value = tok(); $('#err').textContent = msg || '';
  if (!dlg.open) dlg.showModal();
}
$('#openSettings').onclick = () => openSettings();
$('#cancel').onclick = () => dlg.close();
$('#form').onsubmit = async ev => {
  ev.preventDefault();
  sessionStorage.setItem('auroelic_token', $('#token').value.trim());
  try {
    const body = Object.fromEntries(F.map(k => [k, Number($('#' + k).value)]));
    S.th = await api('/api/settings', {method:'PUT', body:JSON.stringify(body)});
    dlg.close(); await init(); if (S.ws.readyState > 1) connect(); if (S.snap) renderStrip(S.snap);
  } catch (e) { if (e.message !== '401') $('#err').textContent = e.message; }
};
$('#range').onclick = async e => {
  const b = e.target.closest('button'); if (!b) return;
  S.range = b.dataset.r; document.querySelectorAll('#range button').forEach(x => x.classList.toggle('on', x === b));
  try { await loadHistory(); } catch (_) {}
};
setInterval(() => { if (S.range !== '5m') loadHistory().catch(() => {}); }, 30000);
setInterval(() => { if (S.ws && S.ws.readyState === 1) S.ws.send('ping'); }, 25000);
setInterval(() => { if (S.snap && Date.now() - S.lastRx > (S.snap.interval * 3 + 2) * 1000) setConn('stale'); }, 1000);
let raf; window.addEventListener('resize', () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(charts); });
init(); connect();
})();
