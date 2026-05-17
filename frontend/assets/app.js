const PANEL_PARTIALS = [
  ['dashboard', 'panels/dashboard.html'],
  ['simulator', 'panels/simulator.html'],
  ['calendar', 'panels/calendar.html'],
  ['adapt', 'panels/adapt.html'],
  ['help', 'panels/help.html'],
];
let PANEL_LOAD_PROMISE = null;
function loadPanelPartials() {
  if (PANEL_LOAD_PROMISE) return PANEL_LOAD_PROMISE;
  PANEL_LOAD_PROMISE = Promise.all(PANEL_PARTIALS.map(async ([id, src]) => {
    const host = document.querySelector(`[data-panel-placeholder="${id}"]`);
    if (!host) return;
    const response = await fetch(src);
    if (!response.ok) throw new Error(`Panel yüklenemedi: ${src}`);
    host.outerHTML = await response.text();
  }));
  return PANEL_LOAD_PROMISE;
}
loadPanelPartials().catch(error => console.error(error));

let HAS_REGISTERED = false;
let APP_STATE = { firstName: 'Demo', lastName: 'User', facilityName: 'Bilinmeyen Tesis', role: 'Misafir', email: '' };
const API_BASE = 'http://127.0.0.1:8001';
const today = new Date();
let calendarYear = today.getFullYear();
let calendarMonth = today.getMonth();
let SELECTED_CALENDAR_DATE = null;
let WEATHER_POINTS = [];
let TRAFFIC_POINTS = [];

// AUTH
function switchAuthTab(t) {
  document.getElementById('login-form').classList.toggle('hidden', t !== 'login');
  document.getElementById('register-form').classList.toggle('hidden', t !== 'register');
  document.getElementById('tab-login').classList.toggle('active', t === 'login');
  document.getElementById('tab-register').classList.toggle('active', t === 'register');
  document.getElementById('tab-login').classList.toggle('text-slate-400', t !== 'login');
  document.getElementById('tab-register').classList.toggle('text-slate-400', t !== 'register');
}
function toggleRegisterBtn() {
  const c = document.getElementById('contract-check').checked, b = document.getElementById('register-btn');
  b.disabled = !c; b.style.opacity = c ? '1' : '0.4'; b.style.cursor = c ? 'pointer' : 'not-allowed';
}
function attemptLogin() {
  if (!HAS_REGISTERED) {
    const err = document.getElementById('login-error');
    err.classList.remove('hidden');
    setTimeout(() => {
      err.classList.add('hidden');
      switchAuthTab('register');
    }, 2500);
    return;
  }
  enterApp();
}
function registerAndEnterApp() {
  const fac = document.getElementById('reg-facility');
  if (!fac || !fac.value.trim()) {
    alert("Lütfen Tesis / Şirket Adı alanını doldurun.");
    return;
  }
  HAS_REGISTERED = true;
  enterApp();
}
function collectOnboardingState() {
  const firstName = document.getElementById('reg-first-name')?.value.trim() || APP_STATE.firstName;
  const lastName = document.getElementById('reg-last-name')?.value.trim() || APP_STATE.lastName;
  const facilityName = document.getElementById('reg-facility')?.value.trim() || APP_STATE.facilityName;
  const role = document.getElementById('reg-role')?.value || APP_STATE.role;
  const email = document.getElementById('reg-email')?.value.trim() || APP_STATE.email;
  APP_STATE = { firstName, lastName, facilityName, role, email, mode: 'demo' };
}
function applyOnboardingState() {
  const initials = (APP_STATE.firstName[0] || 'D') + (APP_STATE.lastName[0] || 'K');
  const el = document.getElementById('user-initials');
  if (el) el.textContent = initials.toUpperCase();
  const facilEl = document.getElementById('sidebar-facility-name');
  if (facilEl) facilEl.textContent = APP_STATE.facilityName;
  const roleEl = document.getElementById('sidebar-user-role');
  if (roleEl) roleEl.textContent = APP_STATE.role;
  const pageSub = document.getElementById('page-sub');
  if (pageSub) pageSub.textContent = `${APP_STATE.facilityName} · 21 MW · Ankara`;
  const adaptName = document.getElementById('adapt-name');
  if (adaptName && !adaptName.value.trim()) adaptName.value = APP_STATE.facilityName;
  updateAdaptCode();
}
async function enterApp() {
  collectOnboardingState();
  try {
    await loadPanelPartials();
  } catch (error) {
    console.error(error);
    alert('Panel dosyaları yüklenemedi. Frontend\'i http://127.0.0.1:3000 üzerinden açtığınızdan emin olun.');
    return;
  }
  const as = document.getElementById('auth-screen');
  as.style.opacity = '0'; as.style.transition = 'opacity .5s';
  setTimeout(() => { as.classList.add('hidden'); document.getElementById('app').classList.remove('hidden'); applyOnboardingState(); initApp(); }, 500);
}
function logout() {
  document.getElementById('app').classList.add('hidden');
  const as = document.getElementById('auth-screen'); as.classList.remove('hidden'); as.style.opacity = '1';
}

// INIT
function initApp() {
  removeLegacySidebarStatus();
  updateClock(); setInterval(updateClock, 1000);
  resetDashboardToWaitingState();
  renderCalendar(); renderCalEventsList();
}
function resetDashboardToWaitingState() {
  clearComputedOutputs('Koşul bekleniyor');
  HAS_SCENARIO_RESULT = false;
  LAST_OPTIMIZED_SCENARIO = null;
  ['chart-area', 'chart-current', 'chart-optimum', 'chart-forecast'].forEach(id => document.getElementById(id)?.setAttribute('d', ''));
  clearCurrentTrendMarker();
  document.getElementById('chart-x-labels')?.replaceChildren();
  setDemoStatus('demo-data-source', 'Koşul bekleniyor');
  setDemoStatus('demo-backend-status', 'Henüz çağrılmadı');
  setDemoStatus('demo-physics-status', '-');
  setDemoStatus('demo-calendar-status', '-');
}
function clearComputedOutputs(reason = 'Koşul bekleniyor') {
  const values = {
    'd-current-pue': '--', 'd-target-pue': '--', 'd-savings': '--', 'd-carbon': '--', 'd-temp': '--', 'd-load': '--', 'd-inlet': '--', 'd-co2': '--',
    'r-chiller-from': '--', 'r-chiller-to': '--', 'r-fan-from': '--', 'r-fan-to': '--', 'r-cooling-from': '--', 'r-cooling-to': '--', 'r-free-from': '--', 'r-free-to': '--',
    'sim-pue': '--', 'sim-inlet': '--', 'sim-fan': '--', 'sim-save': '--', 'sim-cop': '--'
  };
  Object.entries(values).forEach(([id, value]) => { const el = document.getElementById(id); if (el) el.textContent = value; });
  const load = document.getElementById('d-it-load'); if (load) load.innerHTML = '--<span class="text-lg">MW</span>';
  const aiChip = document.getElementById('ai-status-chip');
  if (aiChip) { aiChip.textContent = 'Koşul Bekliyor'; aiChip.className = 'ml-auto chip bg-blue-500/10 text-blue-300 border border-blue-500/20'; }
  LAST_SAVINGS_CONTEXT = null;
  updateSavingsRing(null);
  const carbonNote = document.getElementById('carbon-note'); if (carbonNote) carbonNote.textContent = 'Optimizasyon sonrası aylık azaltım';
  const summary = document.getElementById('trend-summary'); if (summary) summary.textContent = 'Optimizasyon sonrası bu koşula ait trend görünür';
  const simStatus = document.getElementById('sim-opt-status');
  if (simStatus) simStatus.textContent = reason === 'Koşul bekleniyor' ? 'Jüri bu butonla seçili sıcaklık, yük ve saat değerlerini backend model hattına gönderebilir.' : 'Koşul değişti. Yeni değerler için tekrar optimize edin.';
}
function removeLegacySidebarStatus() {
  const nav = document.querySelector('nav');
  if (!nav) return;
  const children = [...nav.children];
  const start = children.findIndex(el => el.textContent.includes('Durum'));
  if (start >= 0) children.slice(start, start + 3).forEach(el => el.remove());
}
function updateClock() {
  const el = document.getElementById('top-clock');
  if (el) el.textContent = new Date().toLocaleTimeString('tr-TR', { hour12: false });
}
function toggleDemoFlow() {
  const body = document.getElementById('demo-flow-body');
  const icon = document.getElementById('demo-flow-icon');
  const summary = document.getElementById('demo-flow-summary');
  if (!body) return;
  const opening = body.classList.contains('hidden');
  body.classList.toggle('hidden', !opening);
  if (icon) icon.style.transform = opening ? 'rotate(180deg)' : 'rotate(0deg)';
  if (summary) summary.textContent = opening ? 'Açık · backend durum kartları görüntüleniyor.' : 'Kapalı · backend akış durumlarını görmek için açın.';
}

// PAGE NAV
const pageTitles = {
  dashboard: ['Dashboard — Gerçek Zamanlı İzleme', ''],
  simulator: ['Simülatör — Senaryo Testi', 'Optuna · Fizik Doğrulama · Preset Senaryolar'],
  calendar: ['Kritik Trafik Takvimi', 'Ay/Yıl gezinme · Dosya yükleme · Simülatöre aktarım'],
  adapt: ['Domain Adaptation', 'XGBoost Warm Start · Müşteri Verisi · Yerel İşlem'],
  help: ['Yardım Merkezi', 'SSS · Kullanım Kılavuzu · Demo Akışı'],
};
function showPage(id, navEl) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => { n.classList.remove('active'); n.classList.add('text-slate-500'); });
  document.getElementById('page-' + id).classList.add('active');
  navEl.classList.add('active'); navEl.classList.remove('text-slate-500');
  const [title, sub] = pageTitles[id] || ['', ''];
  document.getElementById('page-title').textContent = title;
  document.getElementById('page-sub').textContent = id === 'dashboard' ? `${APP_STATE.facilityName} · 21 MW · Ankara` : sub;
}

// CHART
let trendScale = '24h';
let lastTrendState = { curPUE: 1.55, tgtPUE: 1.24, temp: 22, load: 67 };
let HAS_SCENARIO_RESULT = false;
let LAST_OPTIMIZED_SCENARIO = null;
let IS_RUNNING_OPTIMIZE = false;
let LAST_SAVINGS_CONTEXT = null;
function setTrendScale(scale) {
  trendScale = scale;
  document.querySelectorAll('.trend-scale-btn').forEach(btn => { btn.classList.remove('bg-white/10', 'text-slate-200'); btn.classList.add('text-slate-500'); });
  const active = document.getElementById('scale-' + scale);
  if (active) { active.classList.add('bg-white/10', 'text-slate-200'); active.classList.remove('text-slate-500'); }
  if (HAS_SCENARIO_RESULT) renderChart(lastTrendState.curPUE, lastTrendState.tgtPUE, lastTrendState);
  else {
    ['chart-area', 'chart-current', 'chart-optimum', 'chart-forecast'].forEach(id => document.getElementById(id)?.setAttribute('d', ''));
    clearCurrentTrendMarker();
    document.getElementById('chart-x-labels')?.replaceChildren();
    const summary = document.getElementById('trend-summary');
    if (summary) summary.textContent = 'Optimizasyon sonrası bu koşula ait trend görünür';
  }
}
function updateTrendVisibility() {
  ['current', 'optimum', 'forecast'].forEach(id => {
    const path = document.getElementById('chart-' + id);
    const checkbox = document.getElementById('series-' + id);
    if (path && checkbox) path.style.display = checkbox.checked ? '' : 'none';
  });
  const currentOn = document.getElementById('series-current')?.checked;
  const optimumOn = document.getElementById('series-optimum')?.checked;
  const forecastOn = document.getElementById('series-forecast')?.checked;
  const area = document.getElementById('chart-area');
  if (area) area.style.display = currentOn && optimumOn ? '' : 'none';
  const summary = document.getElementById('trend-summary');
  if (summary) summary.textContent = `${trendScale === '24h' ? '24 saatlik' : '7 günlük'} geçmiş trend · ${[currentOn ? 'Mevcut' : null, optimumOn ? 'Optimal' : null, forecastOn ? 'İleri Tahmin' : null].filter(Boolean).join(' / ')}`;
}
function renderChart(curPUE, tgtPUE, context = {}) {
  const W = 560, H = 120, x0 = 18;
  const temp = Number(context.temp ?? parseFloat(document.getElementById('d-temp')?.textContent) ?? 22);
  const load = Number(context.load ?? parseFloat(document.getElementById('d-load')?.textContent) ?? 67);
  const hour = Number(context.hour ?? new Date().getHours());
  lastTrendState = { curPUE, tgtPUE, temp, load, hour };
  const N = trendScale === '24h' ? 24 : 7;
  const labels = trendScale === '24h' ? ['00', '06', '12', '18', '24'] : ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz'];
  const markerIndex = trendScale === '24h'
    ? Math.max(0, Math.min(N - 1, Math.round(hour)))
    : Math.max(0, Math.min(N - 1, (new Date().getDay() + 6) % 7));
  const toX = i => x0 + (i / (N - 1)) * (W - x0 - 8);
  const workloadFactor = (load - 60) / 100;
  const tempFactor = Math.max(0, temp - 18) / 100;
  const pts = [];
  const offsets = [];
  for (let i = 0; i < N; i++) {
    const dayShape = trendScale === '24h' ? (i >= 9 && i <= 18 ? 0.014 : i >= 19 && i <= 22 ? 0.007 : -0.01) : ([0.004, 0.007, 0.009, 0.008, 0.011, 0.003, -0.006][i] || 0);
    const wave = Math.sin(i * (trendScale === '24h' ? 0.55 : 1.15)) * 0.005;
    const stress = workloadFactor * 0.018 + tempFactor * 0.025;
    offsets.push(dayShape + wave + stress);
  }
  const anchor = offsets[markerIndex] || 0;
  for (let i = 0; i < N; i++) {
    const relative = offsets[i] - anchor;
    const current = curPUE + relative;
    const optimum = tgtPUE + (relative * 0.45);
    const forecast = tgtPUE + (Math.max(0, i - markerIndex) * (trendScale === '24h' ? 0.0025 : 0.006)) + (tempFactor * 0.01);
    pts.push({ current, optimum, forecast });
  }
  const history = pts.slice(0, markerIndex + 1);
  const forecastPts = pts.slice(markerIndex).map((p, i) => ({ forecast: p.forecast, index: i + markerIndex }));
  const forecastOn = document.getElementById('series-forecast')?.checked;
  const scaleValues = [
    ...history.flatMap(p => [p.current, p.optimum]),
    ...(forecastOn ? forecastPts.map(p => p.forecast) : [])
  ].filter(Number.isFinite);
  const minVal = Math.min(...scaleValues), maxVal = Math.max(...scaleValues);
  const range = Math.max(0.018, maxVal - minVal);
  const pad = Math.max(0.008, range * 0.25);
  const pMin = Math.max(1.0, minVal - pad), pMax = maxVal + pad;
  const toY = v => 15 + (1 - (v - pMin) / (pMax - pMin)) * (H - 30);
  const pathForHistory = key => history.map((p, i) => `${i === 0 ? 'M' : 'L'}${toX(i)},${toY(p[key])}`).join('');
  const pathForForecast = () => forecastPts.map((p, i) => `${i === 0 ? 'M' : 'L'}${toX(p.index)},${toY(p.forecast)}`).join('');
  const cur = pathForHistory('current'), opt = pathForHistory('optimum'), forecast = pathForForecast();
  let area = '';
  if (history.length > 1) {
    area = opt + ` L${toX(markerIndex)},${toY(history[history.length - 1].current)}`;
    for (let i = history.length - 2; i >= 0; i--)area += ` L${toX(i)},${toY(history[i].current)}`;
    area += ' Z';
  }
  document.getElementById('chart-area')?.setAttribute('d', area);
  document.getElementById('chart-current')?.setAttribute('d', cur);
  document.getElementById('chart-optimum')?.setAttribute('d', opt);
  document.getElementById('chart-forecast')?.setAttribute('d', forecast);
  const title = document.getElementById('trend-title');
  if (title) title.textContent = trendScale === '24h' ? '24 Saatlik PUE Trendi' : '7 Günlük PUE Trendi';
  renderTrendLabels(labels, toX, H);
  renderCurrentTrendMarker(toX(markerIndex), toY(pts[markerIndex].current), toY(pts[markerIndex].optimum), trendScale === '24h' ? `${String(markerIndex).padStart(2, '0')}:00` : 'Seçilen koşul');
  updateTrendVisibility();
}
function renderChartFromTwin(points) {
  if (!Array.isArray(points) || !points.length) return;
  const W = 560, H = 120, x0 = 18, N = points.length;
  const toX = i => x0 + (i / (N - 1)) * (W - x0 - 8);
  const scaleValues = points.flatMap(p => [Number(p.current_pue), Number(p.optimal_pue), Number(p.forecast_pue)]).filter(Number.isFinite);
  const minVal = Math.min(...scaleValues), maxVal = Math.max(...scaleValues);
  const range = Math.max(0.04, maxVal - minVal), pad = Math.max(0.025, range * 0.35);
  const pMin = Math.max(1.0, minVal - pad), pMax = maxVal + pad;
  const toY = v => 15 + (1 - (v - pMin) / (pMax - pMin)) * (H - 30);
  const pathFor = key => points.map((p, i) => `${i === 0 ? 'M' : 'L'}${toX(i)},${toY(Number(p[key]))}`).join('');
  const cur = pathFor('current_pue'), opt = pathFor('optimal_pue'), forecast = pathFor('forecast_pue');
  let area = opt + ` L${toX(N - 1)},${toY(Number(points[N - 1].current_pue))}`;
  for (let i = N - 2; i >= 0; i--)area += ` L${toX(i)},${toY(Number(points[i].current_pue))}`; area += ' Z';
  document.getElementById('chart-area')?.setAttribute('d', area);
  document.getElementById('chart-current')?.setAttribute('d', cur);
  document.getElementById('chart-optimum')?.setAttribute('d', opt);
  document.getElementById('chart-forecast')?.setAttribute('d', forecast);
  const title = document.getElementById('trend-title');
  if (title) title.textContent = trendScale === '24h' ? '24 Saatlik PUE Trendi' : '7 Günlük PUE Trendi';
  const labels = points.map(p => p.label);
  renderTrendLabels(labels, i => toX(i), H);
  const last = points[N - 1];
  renderCurrentTrendMarker(toX(N - 1), toY(Number(last.current_pue)), toY(Number(last.optimal_pue)), last.label || 'Şimdi');
  updateTrendVisibility();
}
function clearCurrentTrendMarker() {
  const group = document.getElementById('chart-now-marker');
  if (group) group.innerHTML = '';
}
function renderCurrentTrendMarker(x, currentY, optimumY, label) {
  const group = document.getElementById('chart-now-marker');
  if (!group) return;
  group.innerHTML = '';
  const ns = 'http://www.w3.org/2000/svg';
  const make = (tag, attrs) => { const el = document.createElementNS(ns, tag); Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v)); return el; };
  group.appendChild(make('line', { x1: x, y1: 12, x2: x, y2: 111, stroke: 'rgba(148,163,184,0.35)', 'stroke-width': '1', 'stroke-dasharray': '3 4' }));
  group.appendChild(make('circle', { cx: x, cy: currentY, r: 4.2, fill: '#f59e0b', stroke: '#0f172a', 'stroke-width': '1.5' }));
  group.appendChild(make('circle', { cx: x, cy: optimumY, r: 4.2, fill: '#2dd4bf', stroke: '#0f172a', 'stroke-width': '1.5' }));
  const tag = make('text', { x: Math.max(24, Math.min(505, x + 7)), y: 18, 'font-size': '8', fill: 'rgba(226,232,240,0.78)', 'font-family': 'Inter, sans-serif' });
  tag.textContent = `Seçilen koşul · ${label}`;
  group.appendChild(tag);
}
function renderTrendLabels(labels, toX, H) {
  const group = document.getElementById('chart-x-labels');
  if (!group) return;
  group.innerHTML = '';
  labels.forEach((label, index) => {
    const step = labels.length > 7 ? 1 : (trendScale === '24h' ? 23 / (labels.length - 1) : 1);
    const x = toX(index * step);
    const t = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    t.setAttribute('x', x); t.setAttribute('y', H + 6); t.setAttribute('font-size', '8'); t.setAttribute('fill', 'rgba(255,255,255,0.28)'); t.setAttribute('font-family', 'Consolas'); t.textContent = label;
    group.appendChild(t);
  });
}

// RACK
function renderRackMatrix(id, pue) {
  const el = document.getElementById(id); if (!el) return; el.innerHTML = '';
  for (let i = 0; i < 32; i++) {
    const r = Math.random(); let bg;
    if (pue > 1.7 && r < 0.12) bg = 'rgba(239,68,68,0.55)';
    else if (pue > 1.5 && r < 0.28) bg = 'rgba(245,158,11,0.45)';
    else bg = 'rgba(34,197,94,0.35)';
    const d = document.createElement('div');
    d.className = 'rack-cell'; d.style.cssText = `height:16px;background:${bg}`;
    el.appendChild(d);
  }
}

// NEMOTRON
let streamIv;
function startNemotronStream(reportText) {
  if (!reportText) {
    reportText = "Bugün Ankara'da dış ortam sıcaklığı 22°C ile mevsim normallerinde seyrediyor. Bu koşullar altında serbest soğutma (free cooling) devreye alınması mümkündür ve Chiller-1 yükü %78'den %62'ye düşürülebilir.\n\nAI optimizasyon motoru 150 farklı chiller-fan kombinasyonunu değerlendirdi. Mevcut PUE 1.55'ten 1.24'e indirilerek aylık 287.000 TL tasarruf sağlanabilir. Yıllık projeksiyon 3.4 milyon TL düzeyindedir.\n\nÖnerilen tüm ayarlar ASHRAE TC 9.9 standartlarıyla doğrulanmış, sunucu giriş sıcaklığı 21°C ile güvenli eşiğin (27°C) altında kalmaktadır. Uygulama için tesis müdürü onayı önerilir.";
  }
  const el = document.getElementById('report-text'), cur = document.getElementById('report-cursor');
  if (!el || !cur) return; el.innerHTML = ''; el.appendChild(cur);
  let i = 0; clearInterval(streamIv);
  streamIv = setInterval(() => {
    if (i < reportText.length) {
      const c = reportText[i++];
      if (c === '\n') { el.insertBefore(document.createElement('br'), cur); if (reportText[i] === '\n') { el.insertBefore(document.createElement('br'), cur); i++; } }
      else el.insertBefore(document.createTextNode(c), cur);
    } else clearInterval(streamIv);
  }, 20);
}

// OPTIMIZE
async function runOptimize() {
  const activeSimulator = document.getElementById('page-simulator')?.classList.contains('active');
  if (!activeSimulator && !HAS_SCENARIO_RESULT) {
    setDemoStatus('demo-data-source', 'Önce simülatörde koşul seçin', 'warn');
    setDemoStatus('demo-backend-status', 'Çağrı yapılmadı', 'neutral');
    setDemoStatus('demo-physics-status', 'Koşul yok', 'warn');
    startNemotronStream('Önce Simülatör panelinde sıcaklık, yük ve saat koşulunu seçip "Bu Koşula Göre Optimize Et" butonunu çalıştırın. Sonuçlar dashboard üzerinde görünecek.');
    return;
  }
  const btn = document.getElementById(activeSimulator ? 'sim-opt-btn' : 'opt-btn'),
    txt = document.getElementById(activeSimulator ? 'sim-opt-btn-txt' : 'opt-btn-txt'),
    pbar = document.getElementById(activeSimulator ? 'sim-opt-pbar' : 'opt-pbar'),
    fill = document.getElementById(activeSimulator ? 'sim-opt-fill' : 'opt-fill'),
    preview = document.getElementById('demo-payload-preview');
  const simStatus = document.getElementById('sim-opt-status');
  IS_RUNNING_OPTIMIZE = true;
  if (btn) btn.disabled = true;
  if (txt) txt.textContent = 'Senaryo okunuyor...';
  if (simStatus) simStatus.textContent = 'Seçili simülatör koşulları okunuyor...';
  if (pbar) pbar.classList.remove('hidden');
  if (fill) fill.style.width = '8%';
  setDemoStatus('demo-data-source', 'Manuel/preset senaryo okunuyor');
  setDemoStatus('demo-backend-status', 'Backend kontrol ediliyor');
  setDemoStatus('demo-physics-status', 'Optuna bekleniyor');
  setDemoStatus('demo-calendar-status', 'Takvim bekleniyor');
  if (preview) { preview.classList.remove('hidden'); preview.textContent = 'Optimizasyon akışı başladı...'; }

  try {
    const [importantDatesText, healthResponse] = await Promise.all([
      fetch('sample-data/important-dates.csv').then(r => r.text()),
      fetch(`${API_BASE}/health`)
    ]);
    if (!healthResponse.ok) throw new Error('health failed');
    const health = await healthResponse.json();
    setDemoStatus('demo-backend-status', health.status === 'ok' ? 'Bağlandı' : 'Uyarı', 'ok');
    if (fill) fill.style.width = '20%';

    const scenario = buildManualOptimizationScenario();
    setDemoStatus('demo-data-source', `${scenario.sourceLabel} · yük %${scenario.workload.toFixed(0)} · ${scenario.ambient.toFixed(1)}°C`, scenario.workload ? 'ok' : 'warn');
    if (simStatus) simStatus.textContent = `Backend'e gönderilecek koşul: ${scenario.ambient.toFixed(1)}°C, %${scenario.workload.toFixed(0)} yük, ${String(scenario.hour).padStart(2, '0')}:00.`;

    if (txt) txt.textContent = 'Takvim parse ediliyor...';
    const calendarResponse = await fetch(`${API_BASE}/api/calendar/parse`, { method: 'POST', headers: { 'Content-Type': 'text/csv' }, body: importantDatesText });
    if (calendarResponse.ok) {
      const calendarData = await calendarResponse.json();
      setDemoStatus('demo-calendar-status', `${calendarData.accepted_count} olay`, calendarData.accepted_count ? 'ok' : 'warn');
      if (Array.isArray(calendarData.events) && calendarData.events.length) {
        CALENDAR_EVENTS = calendarData.events.map(normalizeCalendarEvent);
        jumpToFirstEvent();
        renderCalendar();
        renderCalEventsList();
      }
    }
    if (fill) fill.style.width = '35%';

    const optimizePayload = {
      server_workload_pct: scenario.workload,
      ambient_temp_c: scenario.ambient,
      hour: scenario.hour,
      month: scenario.month,
      it_capacity_mw: scenario.itCapacityMw,
      n_trials: 60
    };
    if (preview) preview.textContent = 'Backend /api/twin-optimize payload:\n' + JSON.stringify(optimizePayload, null, 2);
    if (txt) txt.textContent = 'Backend Optuna çalışıyor...';
    const optimizeResponse = await fetch(`${API_BASE}/api/twin-optimize`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(optimizePayload) });
    if (!optimizeResponse.ok) throw new Error('twin optimize failed');
    const optimization = await optimizeResponse.json();
    const selectedRank = optimization.decision?.selected_candidate_rank;
    const selected = optimization.candidates.find(c => c.rank === selectedRank) || optimization.candidates[0];
    if (!selected) throw new Error('candidate missing');
    const savingsMetrics = calculateSavingsMetrics(optimization.current, selected);
    if (fill) fill.style.width = '72%';

    updateDashboardFromOptimization(optimization.current, selected, scenario);
    HAS_SCENARIO_RESULT = true;
    LAST_OPTIMIZED_SCENARIO = scenario;
    if (simStatus) simStatus.textContent = `Optimizasyon tamamlandı: PUE ${optimization.current.pue.toFixed(2)} -> ${selected.pue.toFixed(2)}, önerilen setpoint ${selected.chiller_setpoint_c.toFixed(1)}°C ve fan %${selected.fan_speed_pct.toFixed(0)}.`;
    setDemoStatus('demo-physics-status', `PUE ${optimization.current.pue.toFixed(2)} -> ${selected.pue.toFixed(2)}`, selected.pue < optimization.current.pue ? 'ok' : 'warn');

    const reportPayload = {
      scenario_name: `${APP_STATE.facilityName} pik yük optimizasyonu`,
      current_pue: optimization.current.pue,
      optimum_pue: selected.pue,
      ambient_temp_c: scenario.ambient,
      server_workload_pct: scenario.workload,
      inlet_temp_c: selected.inlet_temp_c,
      current_chiller_pct: scenario.chillerPct,
      optimized_chiller_pct: selected.chiller_setpoint_c,
      current_fan_pct: optimization.current.fan_speed_pct,
      optimized_fan_pct: selected.fan_speed_pct,
      monthly_savings_tl: savingsMetrics.monthlySavingsTl,
      co2_savings_ton_month: Math.round((selected.co2_tons_year || 0) / 12 * 10) / 10,
      physics_status: selected.safety_ok ? 'ok' : 'warning',
      physics_notes: [selected.ashrae_status, `Risk: ${selected.risk_level}`, optimization.policy?.reason_tr || optimization.policy_used?.reason_tr || ''],
      recommended_actions: [
        `Chiller setpoint ${selected.chiller_setpoint_c}°C`,
        `Fan hızı %${selected.fan_speed_pct}`,
        selected.validation?.approved ? 'Fizik doğrulama güvenli' : 'Operatör onayı ile incele'
      ],
      use_mock: false
    };
    if (preview) preview.textContent = 'Backend /api/twin-optimize sonucu:\n' + JSON.stringify({ scenario, optimizePayload, selected, decision: optimization.decision }, null, 2) + '\n\nBackend /api/report payload:\n' + JSON.stringify(reportPayload, null, 2);
    if (txt) txt.textContent = 'LLM raporu üretiliyor...';
    const badge = document.getElementById('llm-mode-badge');
    if (badge) badge.textContent = 'LLM: Çalışıyor';
    const reportResponse = await fetch(`${API_BASE}/api/report`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(reportPayload) });
    if (!reportResponse.ok) throw new Error('report failed');
    const reportData = await reportResponse.json();
    if (badge) badge.textContent = `LLM: ${reportData.provider}`;
    startNemotronStream(reportData.report);
    if (fill) fill.style.width = '100%';
  } catch (error) {
    setDemoStatus('demo-backend-status', 'Akış hatası', 'bad');
    setDemoStatus('demo-physics-status', error.message, 'warn');
    if (simStatus) simStatus.textContent = `Optimizasyon çalışmadı: ${error.message}. Backend 8001 portunda açık olmalı.`;
    if (preview) preview.textContent = `Optimizasyon çalışmadı: ${error.message}\n\nBackend 8001 ve frontend 3000 portunda çalışıyor olmalı.`;
    startNemotronStream("Optimizasyon akışı tamamlanamadı. Backend servisinin 8001 portunda çalıştığını ve .env içinde NVIDIA_API_KEY veya OPENROUTER_API_KEY bulunduğunu kontrol edin. API anahtarı yoksa backend fallback metin üretir; Optuna ve fizik motoru yine çalışır.");
  } finally {
    IS_RUNNING_OPTIMIZE = false;
    setTimeout(() => { if (btn) btn.disabled = false; if (txt) txt.textContent = activeSimulator ? 'Bu Koşula Göre Optimize Et' : 'Optimize Et'; if (pbar) pbar.classList.add('hidden'); if (fill) fill.style.width = '0%'; }, 500);
  }
}

function setDemoStatus(id, text, kind = 'neutral') {
  const el = document.getElementById(id); if (!el) return;
  el.textContent = text;
  el.className = 'text-sm font-semibold ' + (kind === 'ok' ? 'text-green-400' : kind === 'warn' ? 'text-amber-400' : kind === 'bad' ? 'text-red-400' : 'text-slate-300');
  const summary = document.getElementById('demo-flow-summary');
  if (summary && id === 'demo-backend-status' && document.getElementById('demo-flow-body')?.classList.contains('hidden')) {
    summary.textContent = `Kapalı · backend: ${text}`;
  }
}
function inferMonthFromAmbient(temp) {
  if (temp <= 5) return 1;
  if (temp >= 30) return 7;
  if (temp >= 24) return 8;
  if (temp >= 15) return 4;
  return 10;
}
function buildManualOptimizationScenario() {
  const simActive = document.getElementById('page-simulator')?.classList.contains('active');
  if (simActive) {
    const temp = +document.getElementById('sl-temp').value;
    const load = +document.getElementById('sl-load').value;
    const hour = +document.getElementById('sl-hour').value;
    const chiller = +document.getElementById('sl-chiller').value;
    const fan = +document.getElementById('sl-fan').value;
    return {
      sourceLabel: 'Simülatör manuel senaryo',
      workload: load,
      ambient: temp,
      inlet: parseFloat(document.getElementById('sim-inlet').textContent) || 21,
      chillerPct: chiller,
      fanPct: fan,
      hour,
      month: inferMonthFromAmbient(temp),
      itCapacityMw: 21
    };
  }
  const now = new Date();
  return {
    sourceLabel: 'Dashboard anlık parametreler',
    workload: parseFloat(document.getElementById('d-load').textContent) || 67,
    ambient: parseFloat(document.getElementById('d-temp').textContent) || 22,
    inlet: parseFloat(document.getElementById('d-inlet').textContent) || 21,
    chillerPct: 78,
    fanPct: parseFloat(document.getElementById('r-fan-from').textContent.replace(/[^\\d.]/g, '')) || 85,
    hour: now.getHours(),
    month: now.getMonth() + 1,
    itCapacityMw: 21
  };
}
function pctToChillerSetpoint(chillerPct) {
  return Math.max(6, Math.min(16, 16 - (chillerPct / 100) * 10));
}
function getEnergyPrice() {
  const raw = String(document.getElementById('energy-price')?.value || '').replace(',', '.');
  const value = Number(raw);
  return Number.isFinite(value) && value > 0 ? value : 3.2;
}
function calculateSavingsMetrics(current, selected) {
  const price = getEnergyPrice();
  const currentKw = Number(current.total_power_kw) || ((Number(current.pue) || 0) * (Number(current.it_power_kw) || 0));
  const selectedKw = Number(selected.total_power_kw) || ((Number(selected.pue) || 0) * (Number(selected.it_power_kw) || Number(current.it_power_kw) || 0));
  if ((!currentKw || !selectedKw) && Number.isFinite(Number(selected.monthly_savings_tl))) {
    const baseSavings = Number(selected.monthly_savings_tl);
    const monthlySavingsTl = baseSavings * (price / 3.2);
    const baseMonthlyCost = (Number(current.hourly_cost_tl) || 0) * 720;
    const currentMonthlyCost = baseMonthlyCost * (price / 3.2);
    const savingsRate = baseMonthlyCost > 0 ? (baseSavings / baseMonthlyCost) * 100 : 0;
    return { price, currentKw: 0, selectedKw: 0, savedKw: 0, currentMonthlyCost, monthlySavingsTl, savingsRate };
  }
  const savedKw = Math.max(0, currentKw - selectedKw);
  const currentMonthlyCost = currentKw * 720 * price;
  const monthlySavingsTl = savedKw * 720 * price;
  const savingsRate = currentMonthlyCost > 0 ? (monthlySavingsTl / currentMonthlyCost) * 100 : 0;
  return { price, currentKw, selectedKw, savedKw, currentMonthlyCost, monthlySavingsTl, savingsRate };
}
function calculateCarbonMetrics(current, selected, scenario = {}) {
  const scenarioItKw = (Number(scenario.workload) || 0) / 100 * (Number(scenario.itCapacityMw) || 21) * 1000;
  const itKw = Number(current.it_power_kw) || scenarioItKw;
  const currentKw = Number(current.total_power_kw) || ((Number(current.hourly_cost_tl) || 0) / 3.2) || ((Number(current.pue) || 0) * itKw);
  const selectedKw = Number(selected.total_power_kw) || ((Number(selected.pue) || 0) * itKw);
  const currentMonthlyTon = (Number(current.co2_kg_per_hour) || currentKw * 0.45) * 720 / 1000;
  const selectedMonthlyTon = (Number(selected.co2_kg_per_hour) || selectedKw * 0.45) * 720 / 1000;
  const monthlyReductionTon = Number.isFinite(Number(selected.co2_tons_year))
    ? Number(selected.co2_tons_year) / 12
    : Math.max(0, currentMonthlyTon - selectedMonthlyTon);
  return { currentMonthlyTon, selectedMonthlyTon, monthlyReductionTon };
}
function updateCarbonMetric(metrics) {
  const value = document.getElementById('d-carbon');
  const note = document.getElementById('carbon-note');
  if (!metrics) {
    if (value) value.textContent = '--';
    if (note) note.textContent = 'Optimizasyon sonrası aylık azaltım';
    return;
  }
  if (value) value.textContent = metrics.selectedMonthlyTon.toFixed(1) + ' t';
  if (note) note.textContent = `Mevcut ${metrics.currentMonthlyTon.toFixed(1)} t/ay · azaltım ${metrics.monthlyReductionTon.toFixed(1)} t/ay`;
}
function updateSavingsRing(metrics) {
  const ring = document.getElementById('savings-ring'), rate = document.getElementById('savings-rate'), note = document.getElementById('savings-note');
  if (!metrics) {
    if (ring) ring.style.setProperty('--pct', '0%');
    if (rate) rate.textContent = '--';
    if (note) note.textContent = 'Optimizasyon sonrası oran görünür';
    return;
  }
  const pct = Math.max(0, Math.min(100, metrics.savingsRate));
  if (ring) ring.style.setProperty('--pct', pct.toFixed(1) + '%');
  if (rate) rate.textContent = pct.toFixed(1) + '%';
  if (note) note.textContent = `Aylık enerji giderinden tasarruf · ${metrics.price.toFixed(2)} TL/kWh`;
}
function updateSavingsWithEnergyPrice() {
  if (!LAST_SAVINGS_CONTEXT) return;
  const metrics = calculateSavingsMetrics(LAST_SAVINGS_CONTEXT.current, LAST_SAVINGS_CONTEXT.selected);
  document.getElementById('d-savings').textContent = (metrics.monthlySavingsTl / 1000).toFixed(0) + 'K ₺';
  const simPage = document.getElementById('page-simulator');
  if (simPage?.classList.contains('active')) document.getElementById('sim-save').textContent = (metrics.monthlySavingsTl / 1000).toFixed(0) + 'K ₺';
  updateSavingsRing(metrics);
}
function updateDashboardFromOptimization(current, selected, scenario) {
  HAS_SCENARIO_RESULT = true;
  LAST_OPTIMIZED_SCENARIO = scenario;
  LAST_SAVINGS_CONTEXT = { current, selected };
  const savingsMetrics = calculateSavingsMetrics(current, selected);
  const carbonMetrics = calculateCarbonMetrics(current, selected, scenario);
  const aiChip = document.getElementById('ai-status-chip');
  if (aiChip) { aiChip.textContent = '✓ Doğrulandı'; aiChip.className = 'ml-auto chip bg-green-500/10 text-green-400 border border-green-500/20'; }
  const dashBtnTxt = document.getElementById('opt-btn-txt'); if (dashBtnTxt) dashBtnTxt.textContent = 'Optimize Et';
  document.getElementById('d-current-pue').textContent = current.pue.toFixed(2);
  document.getElementById('d-target-pue').textContent = selected.pue.toFixed(2);
  document.getElementById('d-it-load').innerHTML = (scenario.workload / 100 * scenario.itCapacityMw).toFixed(1) + '<span class="text-lg">MW</span>';
  document.getElementById('d-savings').textContent = (savingsMetrics.monthlySavingsTl / 1000).toFixed(0) + 'K ₺';
  document.getElementById('d-temp').textContent = scenario.ambient.toFixed(1) + '°C';
  document.getElementById('d-load').textContent = scenario.workload.toFixed(0) + '%';
  document.getElementById('d-inlet').textContent = selected.inlet_temp_c.toFixed(1) + '°C';
  document.getElementById('d-co2').textContent = carbonMetrics.monthlyReductionTon.toFixed(1) + 't';
  document.getElementById('r-chiller-from').textContent = current.chiller_setpoint_c.toFixed(1) + '°C';
  document.getElementById('r-chiller-to').textContent = selected.chiller_setpoint_c.toFixed(1) + '°C';
  document.getElementById('r-fan-from').textContent = '%' + current.fan_speed_pct.toFixed(0);
  document.getElementById('r-fan-to').textContent = '%' + selected.fan_speed_pct.toFixed(0);
  document.getElementById('r-cooling-from').textContent = ((current.chiller_power_kw || 0) / 1000).toFixed(1) + ' MW';
  document.getElementById('r-cooling-to').textContent = ((selected.chiller_power_kw || 0) / 1000).toFixed(1) + ' MW';
  document.getElementById('r-free-from').textContent = current.free_cooling_active ? 'AKTİF' : 'KAPALI';
  document.getElementById('r-free-to').textContent = selected.free_cooling_active ? 'AKTİF' : 'KAPALI';
  updateAnomalyPanel(selected);
  const simPage = document.getElementById('page-simulator');
  if (simPage?.classList.contains('active')) {
    document.getElementById('sim-pue').textContent = selected.pue.toFixed(2);
    document.getElementById('sim-pue').className = 'mono text-lg font-bold ' + (selected.pue > 1.5 ? 'text-amber-400' : 'text-green-400');
    document.getElementById('sim-inlet').textContent = selected.inlet_temp_c.toFixed(1) + '°C';
    document.getElementById('sim-save').textContent = (savingsMetrics.monthlySavingsTl / 1000).toFixed(0) + 'K ₺';
    document.getElementById('sim-cop').textContent = String(selected.cop_real ?? '-');
  }
  updateSavingsRing(savingsMetrics);
  updateCarbonMetric(carbonMetrics);
  renderChart(current.pue, selected.pue, { temp: scenario.ambient, load: scenario.workload, hour: scenario.hour });
}

function updateAnomalyPanel(selected) {
  const count = document.getElementById('anomaly-count'), list = document.getElementById('anomaly-list');
  if (!count || !list) return;
  const warnings = [];
  if (!selected.safety_ok || selected.ashrae_status === 'VIOLATION') warnings.push({ level: 'bad', title: 'ASHRAE sıcaklık riski', detail: `Inlet ${selected.inlet_temp_c}°C · ${selected.ashrae_status}` });
  else if (selected.risk_level === 'medium' || selected.risk_level === 'high') warnings.push({ level: 'warn', title: 'Termal risk izleme', detail: `Risk ${selected.risk_level} · Inlet ${selected.inlet_temp_c}°C` });
  if ((selected.cop_real || 7) < 2.2) warnings.push({ level: 'warn', title: 'COP verim uyarısı', detail: `COP ${selected.cop_real}` });
  if (!warnings.length) {
    count.textContent = 'Risk Yok'; count.className = 'chip bg-green-500/10 text-green-400 border border-green-500/20';
    list.innerHTML = '<div class="flex items-start gap-2 p-2 rounded-lg bg-green-500/5 border border-green-500/15"><i class="fas fa-check-circle text-green-400 text-xs mt-0.5"></i><div><p class="text-xs font-medium text-green-300">Bu koşul güvenli</p><p class="text-xs text-slate-600">Digital twin ASHRAE ve COP limitlerinde kritik uyarı üretmedi.</p></div></div>';
    return;
  }
  count.textContent = warnings.length + ' Uyarı'; count.className = 'anomaly-badge chip bg-red-500/10 text-red-400 border border-red-500/20';
  list.innerHTML = warnings.map(item => `<div class="flex items-start gap-2 p-2 rounded-lg ${item.level === 'bad' ? 'bg-red-500/5 border-red-500/15' : 'bg-amber-500/5 border-amber-500/15'} border"><i class="fas ${item.level === 'bad' ? 'fa-exclamation-triangle text-red-400' : 'fa-exclamation-circle text-amber-400'} text-xs mt-0.5"></i><div><p class="text-xs font-medium ${item.level === 'bad' ? 'text-red-300' : 'text-amber-300'}">${item.title}</p><p class="text-xs text-slate-600">${item.detail}</p></div></div>`).join('');
}

function updateDashboardFromTwin(data) {
  const current = data.current, optimal = data.optimal;
  if (!current || !optimal) return;
  document.getElementById('d-current-pue').textContent = Number(data.current_pue).toFixed(2);
  document.getElementById('d-target-pue').textContent = Number(data.optimal_pue).toFixed(2);
  document.getElementById('d-it-load').innerHTML = Number(data.it_load_mw).toFixed(1) + '<span class="text-lg">MW</span>';
  document.getElementById('d-savings').textContent = (Number(data.monthly_savings_tl) / 1000).toFixed(0) + 'K ₺';
  document.getElementById('d-temp').textContent = Number(data.ambient_temp_c).toFixed(1) + '°C';
  document.getElementById('d-load').textContent = Number(data.server_workload_pct).toFixed(0) + '%';
  document.getElementById('d-inlet').textContent = Number(optimal.inlet_temp_c).toFixed(1) + '°C';
  document.getElementById('d-co2').textContent = Number(data.co2_savings_ton_month).toFixed(1) + 't';
  updateCarbonMetric(calculateCarbonMetrics(current, { ...optimal, co2_tons_year: Number(data.co2_savings_ton_month) * 12 }));
  document.getElementById('r-chiller-from').textContent = Number(current.chiller_setpoint_c).toFixed(1) + '°C';
  document.getElementById('r-chiller-to').textContent = Number(optimal.chiller_setpoint_c).toFixed(1) + '°C';
  document.getElementById('r-fan-from').textContent = '%' + Number(current.fan_speed_pct).toFixed(0);
  document.getElementById('r-fan-to').textContent = '%' + Number(optimal.fan_speed_pct).toFixed(0);
  lastTrendState = { curPUE: data.current_pue, tgtPUE: data.optimal_pue, temp: data.ambient_temp_c, load: data.server_workload_pct, hour: new Date(data.timestamp || Date.now()).getHours() };
}
function renderRackMatrixFromTwin(id, values) {
  const el = document.getElementById(id); if (!el || !Array.isArray(values)) return;
  el.innerHTML = '';
  values.forEach(value => {
    let bg = 'rgba(34,197,94,0.35)';
    if (value >= 0.78) bg = 'rgba(239,68,68,0.55)';
    else if (value >= 0.55) bg = 'rgba(245,158,11,0.45)';
    const d = document.createElement('div');
    d.className = 'rack-cell'; d.style.cssText = `height:16px;background:${bg}`;
    el.appendChild(d);
  });
}
async function loadTwinMetrics() {
  try {
    const response = await fetch(`${API_BASE}/api/live-metrics`);
    if (!response.ok) throw new Error('live metrics failed');
    const data = await response.json();
    updateDashboardFromTwin(data);
    setDemoStatus('demo-data-source', 'Digital twin canlı metrik', 'ok');
    setDemoStatus('demo-backend-status', 'Bağlandı', 'ok');
    setDemoStatus('demo-physics-status', `PUE ${Number(data.current_pue).toFixed(2)} -> ${Number(data.optimal_pue).toFixed(2)}`, 'ok');
    fetchBackendReport();
  } catch (error) {
    setDemoStatus('demo-backend-status', 'Digital twin kapalı', 'warn');
    fetchBackendReport();
  }
}
async function loadTwinTrend() {
  try {
    const response = await fetch(`${API_BASE}/api/pue-trend?scale=${trendScale}`);
    if (!response.ok) throw new Error('trend failed');
    const data = await response.json();
    renderChartFromTwin(data.points);
    const summary = document.getElementById('trend-summary');
    if (summary) summary.textContent = `${trendScale === '24h' ? '24 saatlik' : '7 günlük'} digital twin görünümü · fizik motoru`;
  } catch (error) {
    renderChart(lastTrendState.curPUE, lastTrendState.tgtPUE, lastTrendState);
  }
}

async function fetchBackendReport() {
  const currentPue = parseFloat(document.getElementById('d-current-pue').textContent) || 1.55;
  const optimumPue = parseFloat(document.getElementById('d-target-pue').textContent) || 1.24;
  const ambientTemp = parseFloat(document.getElementById('d-temp').textContent) || 22;
  const workload = parseFloat(document.getElementById('d-load').textContent) || 67;
  const inlet = parseFloat(document.getElementById('d-inlet').textContent) || 21;
  const savingsText = document.getElementById('d-savings').textContent;
  const savings = savingsText.includes('K') ? parseFloat(savingsText) * 1000 : parseFloat(savingsText.replace(/\\./g, '').replace(/[^\\d]/g, '')) || 287000;
  const payload = {
    scenario_name: `${APP_STATE.facilityName} demo senaryosu`,
    current_pue: currentPue,
    optimum_pue: optimumPue,
    ambient_temp_c: ambientTemp,
    server_workload_pct: workload,
    inlet_temp_c: inlet,
    current_chiller_pct: parseFloat(document.getElementById('r-chiller-from').textContent.replace(/[^\\d.]/g, '')) || 78,
    optimized_chiller_pct: parseFloat(document.getElementById('r-chiller-to').textContent.replace(/[^\\d.]/g, '')) || 62,
    current_fan_pct: parseFloat(document.getElementById('r-fan-from').textContent.replace(/[^\\d.]/g, '')) || 85,
    optimized_fan_pct: parseFloat(document.getElementById('r-fan-to').textContent.replace(/[^\\d.]/g, '')) || 58,
    monthly_savings_tl: savings,
    co2_savings_ton_month: parseFloat(document.getElementById('d-co2').textContent) || 18.4,
    physics_status: inlet <= 27 ? 'ok' : 'warning',
    physics_notes: [inlet <= 27 ? 'ASHRAE inlet limiti altında' : 'ASHRAE inlet limiti uyarısı'],
    use_mock: true
  };
  try {
    const response = await fetch(`${API_BASE}/api/report`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    if (!response.ok) throw new Error('report failed');
    const data = await response.json();
    startNemotronStream(data.report);
  } catch (error) {
    startNemotronStream("Backend'e ulaşılamadı. Backend'i 8001 portunda çalıştırınca bu panel /api/report çıktısını gösterecek.\\n\\nKomut: uvicorn main:app --reload --port 8001");
  }
}

// SIMULATOR
const PRESETS = [
  { temp: 35, load: 85, hour: 14, chiller: 78, fan: 85, curPUE: 1.74, tgtPUE: 1.31, save: 412000 },
  { temp: -2, load: 45, hour: 3, chiller: 50, fan: 45, curPUE: 1.42, tgtPUE: 1.19, save: 145000 },
  { temp: 18, load: 60, hour: 11, chiller: 62, fan: 58, curPUE: 1.53, tgtPUE: 1.25, save: 287000 },
  { temp: 28, load: 95, hour: 16, chiller: 95, fan: 95, curPUE: 1.81, tgtPUE: 1.38, save: 521000 },
];
function loadPreset(idx, el) {
  document.querySelectorAll('.preset-btn').forEach(b => { b.classList.remove('border-blue-500/40'); b.classList.add('border-white/10'); });
  el.classList.remove('border-white/10'); el.classList.add('border-blue-500/40');
  const p = PRESETS[idx];
  ['temp', 'load', 'hour', 'chiller', 'fan'].forEach(k => {
    const slider = document.getElementById('sl-' + k);
    if (slider) slider.value = p[k];
  });
  updateSim();
}
function updateDashboard(p) {
  document.getElementById('d-current-pue').textContent = p.curPUE.toFixed(2);
  document.getElementById('d-target-pue').textContent = p.tgtPUE.toFixed(2);
  document.getElementById('d-it-load').innerHTML = (p.load / 100 * 21).toFixed(1) + '<span class="text-lg">MW</span>';
  document.getElementById('d-savings').textContent = (p.save / 1000).toFixed(0) + 'K ₺';
  document.getElementById('d-temp').textContent = p.temp + '°C';
  document.getElementById('d-load').textContent = p.load + '%';
  document.getElementById('d-inlet').textContent = Math.round(14 + p.temp * 0.3 + p.load * 0.05) + '°C';
  document.getElementById('r-chiller-from').textContent = pctToChillerSetpoint(p.chiller).toFixed(1) + '°C';
  document.getElementById('r-fan-from').textContent = '%' + p.fan;
  document.getElementById('r-chiller-to').textContent = Math.min(16, pctToChillerSetpoint(p.chiller) + 2).toFixed(1) + '°C';
  document.getElementById('r-fan-to').textContent = '%' + Math.round(p.fan * 0.7);
  renderChart(p.curPUE, p.tgtPUE, p);
}
function updateSim() {
  const temp = +document.getElementById('sl-temp').value, load = +document.getElementById('sl-load').value,
    hour = +document.getElementById('sl-hour').value, chiller = +document.getElementById('sl-chiller').value,
    fan = +document.getElementById('sl-fan').value;
  document.getElementById('sl-temp-val').textContent = temp + '°C';
  document.getElementById('sl-load-val').textContent = load + '%';
  document.getElementById('sl-hour-val').textContent = hour.toString().padStart(2, '0') + ':00';
  document.getElementById('sl-chiller-val').textContent = chiller + '%';
  document.getElementById('sl-fan-val').textContent = fan + '%';
  if (!IS_RUNNING_OPTIMIZE) {
    HAS_SCENARIO_RESULT = false;
    clearComputedOutputs('Koşul değişti');
    ['chart-area', 'chart-current', 'chart-optimum', 'chart-forecast'].forEach(id => document.getElementById(id)?.setAttribute('d', ''));
    document.getElementById('chart-x-labels')?.replaceChildren();
    setDemoStatus('demo-data-source', 'Yeni koşul seçildi');
    setDemoStatus('demo-backend-status', 'Henüz çağrılmadı');
    setDemoStatus('demo-physics-status', 'Optimize bekleniyor');
    return;
  }
  const pue = +(1.1 + (load / 100) * 0.55 + Math.max(0, (temp - 10) / 100) * 0.38 - (chiller / 100 * 0.12) - (fan / 100 * 0.08) + Math.random() * 0.02).toFixed(2);
  const clamped = Math.min(Math.max(pue, 1.15), 1.95);
  const inlet = Math.round(14 + temp * 0.3 + load * 0.05 - chiller * 0.07);
  const save = Math.max(0, Math.round((clamped - 1.2) * 21000 * 0.5 * 24 * 30 * 1.5));
  const fanPow = +(21 * (load / 100) * 0.12 * Math.pow(fan / 100, 3)).toFixed(2);
  const cop = Math.max(1.5, (3.5 - temp * 0.03 - load * 0.01)).toFixed(1);
  document.getElementById('sim-pue').textContent = clamped.toFixed(2);
  document.getElementById('sim-pue').className = 'mono text-lg font-bold ' + (clamped > 1.5 ? 'text-amber-400' : 'text-green-400');
  document.getElementById('sim-inlet').textContent = inlet + '°C';
  document.getElementById('sim-fan').textContent = fanPow + ' MW';
  document.getElementById('sim-save').textContent = (save / 1000).toFixed(0) + 'K ₺';
  document.getElementById('sim-cop').textContent = cop;
  const ok = inlet <= 27;
  document.getElementById('physics-ok').classList.toggle('hidden', !ok);
  document.getElementById('physics-warn').classList.toggle('hidden', ok);
}

// CALENDAR
let CALENDAR_EVENTS = [
  { id: 1, name: 'KPSS Sonuçları', date: '2026-06-08', load: 88, severity: 'critical', desc: 'Sınav sonuç açıklaması' },
  { id: 2, name: 'Vergi Beyan Son Gün', date: '2026-06-25', load: 72, severity: 'critical', desc: 'SGK ve gelir vergisi' },
  { id: 3, name: 'Aybaşı SGK', date: '2026-06-01', load: 65, severity: 'normal', desc: 'Aylık rutin pik' },
  { id: 4, name: 'YKS Tercihleri', date: '2026-06-18', load: 79, severity: 'critical', desc: 'Üniversite tercih dönemi' },
];
function renderCalendar() {
  const grid = document.getElementById('cal-grid'); if (!grid) return; grid.innerHTML = '';
  const criticalDays = {};
  CALENDAR_EVENTS.forEach(ev => {
    const day = parseInt(ev.date.split('-')[2]), month = parseInt(ev.date.split('-')[1]);
    if (month === 6) criticalDays[day] = ev.severity;
  });
  for (let day = 1; day <= 30; day++) {
    const d = document.createElement('div'), sev = criticalDays[day];
    d.className = 'cal-day rounded-lg py-2 px-1 text-center ' + (sev === 'critical' ? 'critical' : sev === 'normal' ? 'normal' : 'empty');
    d.style.minHeight = '44px';
    d.innerHTML = `<p class="text-xs font-semibold ${sev === 'critical' ? 'text-red-300' : sev === 'normal' ? 'text-amber-300' : 'text-slate-600'}">${day}</p>`
      + (sev ? `<div class="w-1.5 h-1.5 rounded-full mx-auto mt-0.5 ${sev === 'critical' ? 'bg-red-400' : 'bg-amber-400'}"></div>` : '');
    grid.appendChild(d);
  }
  const cc = CALENDAR_EVENTS.filter(e => e.severity === 'critical').length;
  const el = document.getElementById('cal-count'); if (el) el.textContent = cc + ' Kritik Gün';
}
function renderCalEventsList() {
  const el = document.getElementById('cal-events-list'); if (!el) return; el.innerHTML = '';
  CALENDAR_EVENTS.forEach((ev, i) => {
    const d = ev.date.split('-'), dateStr = `${d[2]}.${d[1]}.${d[0]}`;
    const div = document.createElement('div');
    div.className = `flex items-center justify-between p-2 rounded-lg border ${ev.severity === 'critical' ? 'bg-red-500/5 border-red-500/15' : 'bg-amber-500/5 border-amber-500/15'}`;
    div.innerHTML = `<div class="flex items-center gap-2"><span class="${ev.severity === 'critical' ? 'text-red-400' : 'text-amber-400'} text-xs"><i class="fas fa-circle"></i></span><div><p class="text-xs font-medium ${ev.severity === 'critical' ? 'text-red-300' : 'text-amber-300'}">${ev.name}</p><p class="text-xs text-slate-600 mono">${dateStr} · %${ev.load} yük</p></div></div><button onclick="removeCalEvent(${i})" class="text-slate-700 hover:text-red-400 text-xs"><i class="fas fa-times"></i></button>`;
    el.appendChild(div);
  });
}
function addCalendarEvent() {
  const name = document.getElementById('ev-name').value.trim(), date = document.getElementById('ev-date').value,
    load = parseInt(document.getElementById('ev-load').value) || 70,
    severity = document.getElementById('ev-severity').value, desc = document.getElementById('ev-desc').value.trim();
  if (!name || !date) { alert('Etkinlik adı ve tarih zorunludur.'); return; }
  CALENDAR_EVENTS.push({ id: Date.now(), name, date, load, severity, desc });
  const d = parseDate(date);
  if (d) { calendarYear = d.getFullYear(); calendarMonth = d.getMonth(); SELECTED_CALENDAR_DATE = date; }
  renderCalendar(); renderCalEventsList();
  const s = document.getElementById('cal-success'); s.classList.remove('hidden'); setTimeout(() => s.classList.add('hidden'), 3000);
  document.getElementById('ev-name').value = ''; document.getElementById('ev-load').value = ''; document.getElementById('ev-desc').value = '';
}
function removeCalEvent(idx) { CALENDAR_EVENTS.splice(idx, 1); renderCalendar(); renderCalEventsList(); }

// Calendar integration overrides
function normalizeCalendarEvent(ev, index = 0) {
  const level = ev.level || ((ev.load || 0) >= 90 ? 'high' : (ev.load || 0) >= 70 ? 'med' : 'low');
  return { ...ev, id: ev.id || index + 1, severity: ev.severity || (level === 'high' ? 'critical' : 'normal'), level, temp: ev.temp ?? defaultTempForDate(ev.date), cooling: ev.cooling || 'Standart proaktif izleme' };
}
CALENDAR_EVENTS = CALENDAR_EVENTS.map(normalizeCalendarEvent);
function updateCalendarControls(monthStart) {
  const monthSelect = document.getElementById('calendar-month-select');
  const yearInput = document.getElementById('calendar-year-input');
  const title = document.getElementById('cal-title');
  const subtitle = document.getElementById('cal-subtitle');
  if (monthSelect) monthSelect.value = String(calendarMonth);
  if (yearInput) yearInput.value = String(calendarYear);
  const label = monthStart.toLocaleDateString('tr-TR', { month: 'long', year: 'numeric' });
  if (title) title.textContent = 'Kritik Trafik Takvimi — ' + label;
  if (subtitle) subtitle.textContent = 'Ay ve yıl seçerek kritik günleri gezebilirsiniz.';
}
function changeCalendarMonth(delta) {
  const next = new Date(calendarYear, calendarMonth + delta, 1);
  calendarYear = next.getFullYear();
  calendarMonth = next.getMonth();
  SELECTED_CALENDAR_DATE = null;
  renderCalendar();
}
function setCalendarMonthYear() {
  const month = Number(document.getElementById('calendar-month-select')?.value);
  const year = Number(document.getElementById('calendar-year-input')?.value);
  if (Number.isFinite(month) && month >= 0 && month <= 11) calendarMonth = month;
  if (Number.isFinite(year) && year >= 2020 && year <= 2035) calendarYear = year;
  SELECTED_CALENDAR_DATE = null;
  renderCalendar();
}
function handleCalendarYearInput() {
  const raw = String(document.getElementById('calendar-year-input')?.value || '');
  if (/^\d{4}$/.test(raw)) setCalendarMonthYear();
}
function goToTodayCalendar() {
  calendarYear = today.getFullYear();
  calendarMonth = today.getMonth();
  SELECTED_CALENDAR_DATE = formatDateKey(today);
  renderCalendar();
  selectCalendarDay(SELECTED_CALENDAR_DATE);
}
function renderCalendar() {
  const grid = document.getElementById('cal-grid'); if (!grid) return; grid.innerHTML = '';
  const monthStart = new Date(calendarYear, calendarMonth, 1);
  const monthEnd = new Date(calendarYear, calendarMonth + 1, 0);
  const leadingBlanks = (monthStart.getDay() + 6) % 7;
  updateCalendarControls(monthStart);
  for (let i = 0; i < leadingBlanks; i++) {
    const blank = document.createElement('div'); blank.className = 'cal-day empty rounded-lg py-2 px-1'; blank.style.minHeight = '64px'; grid.appendChild(blank);
  }
  const todayKey = formatDateKey(today);
  for (let day = 1; day <= monthEnd.getDate(); day++) {
    const dateKey = `${calendarYear}-${String(calendarMonth + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
    const events = CALENDAR_EVENTS.filter(ev => ev.date === dateKey);
    const weather = WEATHER_POINTS.find(item => item.date === dateKey);
    const traffic = TRAFFIC_POINTS.find(item => item.date === dateKey);
    const topEvent = events[0], sev = topEvent?.severity;
    const d = document.createElement('button'); d.type = 'button'; d.onclick = () => selectCalendarDay(dateKey);
    d.className = 'cal-day rounded-lg py-2 px-1 text-left ' + (sev === 'critical' ? 'critical' : sev === 'normal' ? 'normal' : 'empty') + (dateKey === todayKey ? ' today' : '') + (dateKey === SELECTED_CALENDAR_DATE ? ' selected' : '');
    d.style.minHeight = '64px';
    const eventLine = topEvent ? `<div class="mt-1 truncate text-[10px] font-semibold ${sev === 'critical' ? 'text-red-300' : 'text-amber-300'}">${topEvent.name}</div>` : '';
    const more = events.length > 1 ? `<div class="text-[10px] text-slate-500">+${events.length - 1} olay</div>` : '';
    const layers = `<div class="mt-1 flex gap-1 flex-wrap">${weather ? `<span class="text-[10px] text-blue-300 bg-blue-500/10 border border-blue-500/20 rounded px-1">${weather.temp}°C</span>` : ''}${traffic ? `<span class="text-[10px] text-purple-300 bg-purple-500/10 border border-purple-500/20 rounded px-1">%${traffic.load}</span>` : ''}</div>`;
    d.innerHTML = `<p class="text-xs font-semibold ${sev === 'critical' ? 'text-red-300' : sev === 'normal' ? 'text-amber-300' : 'text-slate-500'}">${day}</p>${eventLine}${more}${layers}`;
    grid.appendChild(d);
  }
  const trailing = (7 - ((leadingBlanks + monthEnd.getDate()) % 7)) % 7;
  for (let i = 0; i < trailing; i++) {
    const blank = document.createElement('div'); blank.className = 'cal-day empty rounded-lg py-2 px-1 opacity-40'; blank.style.minHeight = '64px'; grid.appendChild(blank);
  }
  const monthPrefix = `${calendarYear}-${String(calendarMonth + 1).padStart(2, '0')}-`;
  const cc = CALENDAR_EVENTS.filter(e => e.severity === 'critical' && String(e.date).startsWith(monthPrefix)).length;
  const total = CALENDAR_EVENTS.filter(e => e.severity === 'critical').length;
  const el = document.getElementById('cal-count'); if (el) el.textContent = cc + ' Kritik Gün' + (total !== cc ? ` · ${total} toplam` : '');
}
function renderCalEventsList() {
  const el = document.getElementById('cal-events-list'); if (!el) return; el.innerHTML = '';
  CALENDAR_EVENTS.slice().sort((a, b) => a.date.localeCompare(b.date)).forEach(ev => {
    const d = ev.date.split('-'), dateStr = `${d[2]}.${d[1]}.${d[0]}`;
    const div = document.createElement('div');
    div.className = `flex items-center justify-between p-2 rounded-lg border ${ev.severity === 'critical' ? 'bg-red-500/5 border-red-500/15' : 'bg-amber-500/5 border-amber-500/15'}`;
    div.innerHTML = `<button onclick="selectCalendarEvent(${ev.id})" class="flex items-center gap-2 text-left min-w-0"><span class="${ev.severity === 'critical' ? 'text-red-400' : 'text-amber-400'} text-xs"><i class="fas fa-circle"></i></span><div class="min-w-0"><p class="text-xs font-medium truncate ${ev.severity === 'critical' ? 'text-red-300' : 'text-amber-300'}">${ev.name}</p><p class="text-xs text-slate-600 mono">${dateStr} · %${ev.load} yük</p></div></button><button onclick="removeCalEventById(${ev.id})" class="text-slate-700 hover:text-red-400 text-xs"><i class="fas fa-times"></i></button>`;
    el.appendChild(div);
  });
}
function removeCalEventById(id) { CALENDAR_EVENTS = CALENDAR_EVENTS.filter(ev => ev.id !== id); renderCalendar(); renderCalEventsList(); }
function parseDate(value) { const parts = String(value || '').split('-').map(Number); return parts.length === 3 && !parts.some(Number.isNaN) ? new Date(parts[0], parts[1] - 1, parts[2]) : null; }
function formatDateKey(date) { return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`; }
function defaultTempForDate(date) { const d = parseDate(date); const temps = [-1, 2, 7, 13, 18, 23, 27, 27, 22, 15, 8, 2]; return d ? temps[d.getMonth()] : 22; }
function selectCalendarEvent(id) {
  const ev = CALENDAR_EVENTS.find(item => item.id === id);
  if (ev) {
    const d = parseDate(ev.date);
    if (d) { calendarYear = d.getFullYear(); calendarMonth = d.getMonth(); }
    SELECTED_CALENDAR_DATE = ev.date;
    renderCalendar();
    selectCalendarDay(ev.date);
  }
}
function selectCalendarDay(dateKey) {
  SELECTED_CALENDAR_DATE = dateKey;
  renderCalendar();
  const card = document.getElementById('cal-detail-card');
  const events = CALENDAR_EVENTS.filter(ev => ev.date === dateKey), weather = WEATHER_POINTS.find(item => item.date === dateKey), traffic = TRAFFIC_POINTS.find(item => item.date === dateKey);
  if (!card) return;
  if (events[0]) { document.getElementById('ev-date').value = events[0].date; document.getElementById('ev-load').value = events[0].load; }
  if (!events.length && !weather && !traffic) { card.innerHTML = `<div class="text-center py-6 text-xs text-slate-500 font-medium">${dateKey} için kayıt yok.</div>`; return; }
  const eventCards = events.map(ev => `<div class="rounded-lg border ${ev.severity === 'critical' ? 'border-red-500/20 bg-red-500/5 text-red-300' : 'border-amber-500/20 bg-amber-500/5 text-amber-300'} p-3"><div class="flex items-start justify-between gap-3"><div><p class="text-sm font-semibold">${ev.name}</p><p class="text-xs text-slate-500 mt-1 leading-relaxed">${ev.desc || 'Açıklama yok.'}</p></div><span class="chip">%${ev.load}</span></div><div class="grid grid-cols-3 gap-2 mt-3 text-xs"><div class="rounded-md bg-white/5 p-2"><span class="block text-slate-600">Dış sıcaklık</span><span class="mono text-slate-300">${ev.temp ?? weather?.temp ?? '-'}°C</span></div><div class="rounded-md bg-white/5 p-2"><span class="block text-slate-600">AI tedbir</span><span class="text-green-300">${ev.cooling || 'Standart izleme'}</span></div><button onclick="injectEventToSimulator(${Number(ev.temp ?? weather?.temp ?? 22)}, ${Number(ev.load ?? traffic?.load ?? 70)})" class="rounded-md bg-blue-600/20 border border-blue-500/20 text-blue-300 font-semibold px-2">Simülatöre Aktar</button></div></div>`).join('');
  card.innerHTML = `<div class="space-y-3"><div class="flex items-center justify-between"><span class="chip bg-blue-500/10 text-blue-300 border border-blue-500/20">${dateKey}</span><span class="text-xs text-slate-500">${events.length} olay · ${weather ? 'sıcaklık var' : 'sıcaklık yok'} · ${traffic ? 'yük var' : 'yük yok'}</span></div>${eventCards || '<div class="rounded-lg border border-white/10 bg-white/5 p-3 text-xs text-slate-500">Bu güne bağlı önemli tarih yok.</div>'}<div class="grid grid-cols-2 gap-3 text-xs"><div class="rounded-lg border border-blue-500/15 bg-blue-500/5 p-3"><span class="block text-slate-500 mb-1">Sıcaklık katmanı</span><span class="mono text-blue-300 font-semibold">${weather ? weather.temp + '°C' : 'Yok'}</span></div><div class="rounded-lg border border-purple-500/15 bg-purple-500/5 p-3"><span class="block text-slate-500 mb-1">Trafik/yük katmanı</span><span class="mono text-purple-300 font-semibold">${traffic ? '%' + traffic.load : 'Yok'}</span></div></div></div>`;
}
function injectEventToSimulator(temp, load) {
  const p = { temp: Number(temp) || 22, load: Number(load) || 70, hour: 14, chiller: 78, fan: 85, curPUE: Math.min(1.95, Math.max(1.15, 1.2 + (Number(temp) || 22) * 0.008 + (Number(load) || 70) * 0.004)), tgtPUE: 1.24, save: 287000 };
  p.tgtPUE = Math.max(1.12, Number((p.curPUE * 0.82).toFixed(2)));
  ['temp', 'load', 'hour', 'chiller', 'fan'].forEach(k => { const el = document.getElementById('sl-' + k); if (el) el.value = p[k]; });
  updateSim();
  setDemoStatus('demo-data-source', 'Takvim koşulu simülatöre aktarıldı');
}
async function uploadCalendarFile(file) {
  if (!file) return;
  const kind = document.getElementById('calendar-upload-kind').value, status = document.getElementById('calendar-upload-status');
  status.className = 'mt-3 text-xs rounded-lg border p-3 bg-blue-500/10 border-blue-500/20 text-blue-300'; status.textContent = kind === 'events' ? 'Backend dosyayı parse ediyor...' : 'Dosya arayüz içinde okunuyor...'; status.classList.remove('hidden');
  try {
    if (kind === 'events') { const fd = new FormData(); fd.append('file', file); const res = await fetch(`${API_BASE}/api/calendar/parse`, { method: 'POST', body: fd }); if (!res.ok) throw new Error('calendar parse failed'); const data = await res.json(); CALENDAR_EVENTS = data.events.map(normalizeCalendarEvent); jumpToFirstEvent(); status.className = 'mt-3 text-xs rounded-lg border p-3 bg-green-500/10 border-green-500/20 text-green-300'; status.textContent = `${data.accepted_count} önemli tarih takvime işlendi. Reddedilen satır: ${data.rejected_count}.`; }
    else if (kind === 'operations') { const parsed = parseOperationsSensorData(await file.text()); WEATHER_POINTS = parsed.weather; TRAFFIC_POINTS = parsed.traffic; status.className = 'mt-3 text-xs rounded-lg border p-3 bg-green-500/10 border-green-500/20 text-green-300'; status.textContent = `${parsed.sourceRows} sensör satırından ${WEATHER_POINTS.length} sıcaklık ve ${TRAFFIC_POINTS.length} yük günü üretildi.`; }
    else { const parsed = parseClientTimeSeries(await file.text(), kind); if (kind === 'weather') WEATHER_POINTS = parsed; else TRAFFIC_POINTS = parsed; status.className = 'mt-3 text-xs rounded-lg border p-3 bg-green-500/10 border-green-500/20 text-green-300'; status.textContent = `${parsed.length} kayıt takvime eklendi.`; }
    renderCalendar(); renderCalEventsList();
  } catch (error) { status.className = 'mt-3 text-xs rounded-lg border p-3 bg-red-500/10 border-red-500/20 text-red-300'; status.textContent = kind === 'events' ? "Takvim yüklenemedi. Backend'in 8001 portunda çalıştığını kontrol edin." : "Dosya okunamadı. Kolon adlarını ve tarih formatını kontrol edin."; }
}
function jumpToFirstEvent() { if (!CALENDAR_EVENTS.length) return; const first = [...CALENDAR_EVENTS].sort((a, b) => a.date.localeCompare(b.date))[0], d = parseDate(first.date); if (d) { calendarYear = d.getFullYear(); calendarMonth = d.getMonth(); SELECTED_CALENDAR_DATE = first.date; } }
function parseClientTimeSeries(text, kind) { const rows = parseDelimitedRows(text); return rows.map(row => { const date = normalizeDateKey(getRowValue(row, ['date', 'tarih', 'timestamp'])); const value = kind === 'weather' ? toNumber(getRowValue(row, ['temp', 'temperature', 'ambient_temp_c', 'sicaklik'])) : toNumber(getRowValue(row, ['load', 'traffic', 'server_workload_pct', 'yuk'])); return kind === 'weather' ? { date, temp: value } : { date, load: value }; }).filter(item => item.date && Number.isFinite(kind === 'weather' ? item.temp : item.load)); }
function parseOperationsSensorData(text) { const rows = parseDelimitedRows(text), daily = new Map(); rows.forEach(row => { const date = normalizeDateKey(getRowValue(row, ['timestamp', 'time', 'date'])); if (!date) return; const temp = toNumber(getRowValue(row, ['ambient_temperature(°c)', 'ambient_temperature_c', 'ambient_temp_c', 'sicaklik', 'temp'])); const load = toNumber(getRowValue(row, ['server_workload(%)', 'server_workload_pct', 'server_load', 'load', 'yuk'])); if (!daily.has(date)) daily.set(date, { tempSum: 0, tempCount: 0, loadSum: 0, loadCount: 0 }); const b = daily.get(date); if (Number.isFinite(temp)) { b.tempSum += temp; b.tempCount++; } if (Number.isFinite(load)) { b.loadSum += load; b.loadCount++; } }); const weather = [], traffic = []; daily.forEach((b, date) => { if (b.tempCount) weather.push({ date, temp: Number((b.tempSum / b.tempCount).toFixed(1)) }); if (b.loadCount) traffic.push({ date, load: Number((b.loadSum / b.loadCount).toFixed(1)) }); }); return { weather, traffic, sourceRows: rows.length }; }
function parseDelimitedRows(text) { const lines = text.split(/\r?\n/).map(line => line.trim()).filter(line => line && !line.startsWith('#')); if (lines.length < 2) return []; const delimiter = lines[0].includes('|') ? '|' : lines[0].includes(';') ? ';' : lines[0].includes('\t') ? '\t' : ','; const headers = lines[0].split(delimiter).map(normalizeHeader); return lines.slice(1).map(line => { const parts = line.split(delimiter).map(v => v.trim()); const row = {}; headers.forEach((h, i) => row[h] = parts[i]); return row; }); }
function normalizeHeader(value) { return String(value || '').trim().toLowerCase().replace(/\s+/g, '_'); }
function getRowValue(row, keys) { for (const key of keys) { const n = normalizeHeader(key); if (row[n] !== undefined && row[n] !== '') return row[n]; } return null; }
function toNumber(value) { return value === null || value === undefined || value === '' ? NaN : Number(String(value).replace(',', '.')); }
function normalizeDateKey(value) { if (!value) return null; const text = String(value).trim(); const m = text.match(/(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})/); if (m) return `${m[1]}-${m[2].padStart(2, '0')}-${m[3].padStart(2, '0')}`; const parsed = new Date(text); return Number.isNaN(parsed.getTime()) ? null : formatDateKey(parsed); }
function downloadCalendarSample() { const txt = ['# ThermaIQ takvim metin sablonu', '# Siralama: name | date | load | temp | desc | cooling', 'e-Devlet Genel Pik Gunu | 2026-05-19 | 78 | 24 | Pazartesi sabahi vatandas islem piki | +7C Sogutma Rezervi', 'YSK Secim Veri Sayim Gunu | 2026-06-01 | 98 | 28 | YSK sistemleri maksimum yuk altinda | +15C Kritik Ek Sogutma Modu'].join('\n'); const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([txt], { type: 'text/plain;charset=utf-8' })); a.download = 'thermaiq_calendar_template.txt'; a.click(); }

// ADAPT
let uploadedAdaptationFile = null;
function updateAdaptCode() {
  const name = document.getElementById('adapt-name').value.trim();
  const slug = name.toLowerCase().replace(/\\s+/g, '_').replace(/[^a-z0-9_]/g, '') || 'musteri';
  const el = document.getElementById('code-slug'); if (el) el.textContent = slug;
}
function simulateAdaptUpload() {
  const label = document.getElementById('adapt-upload-label'),
    pbar = document.getElementById('adapt-upload-pbar'),
    fill = document.getElementById('adapt-upload-fill');
  label.textContent = 'Yükleniyor...'; pbar.classList.remove('hidden'); let w = 0;
  const iv = setInterval(() => {
    w += Math.random() * 12 + 3; if (w >= 100) {
      w = 100; clearInterval(iv);
      label.textContent = '✓ veri_merkezi_2024.csv — 3.498 satır yüklendi';
      const btn = document.getElementById('adapt-run-btn'); btn.disabled = false; btn.style.opacity = '1'; btn.style.cursor = 'pointer';
    } fill.style.width = w + '%';
  }, 80);
}
async function uploadAdaptationFile(file) {
  if (!file) return;
  uploadedAdaptationFile = file;
  const label = document.getElementById('adapt-upload-label'), pbar = document.getElementById('adapt-upload-pbar'), fill = document.getElementById('adapt-upload-fill'), status = document.getElementById('adapt-upload-status');
  label.textContent = 'Backend dosyayı kontrol ediyor...'; pbar.classList.remove('hidden'); fill.style.width = '35%';
  status.className = 'mt-3 p-3 rounded-lg border text-xs bg-blue-500/10 border-blue-500/20 text-blue-300'; status.textContent = 'Dosya yükleniyor...'; status.classList.remove('hidden');
  try {
    const fd = new FormData(); fd.append('file', file); fd.append('facility_name', document.getElementById('adapt-name').value.trim() || APP_STATE.facilityName || 'musteri');
    const res = await fetch(`${API_BASE}/api/adaptation/upload`, { method: 'POST', body: fd }); if (!res.ok) throw new Error('upload failed');
    const data = await res.json(); fill.style.width = '100%'; label.textContent = `✓ ${file.name} — ${data.row_count} satır okundu`;
    status.className = 'mt-3 p-3 rounded-lg border text-xs bg-green-500/10 border-green-500/20 text-green-300'; status.textContent = `Kolonlar: ${data.columns.slice(0, 6).join(', ')}${data.columns.length > 6 ? '...' : ''}`;
    const btn = document.getElementById('adapt-run-btn'); btn.disabled = false; btn.style.opacity = '1'; btn.style.cursor = 'pointer';
  } catch (error) {
    fill.style.width = '0%'; label.textContent = 'CSV dosyasını sürükleyin veya tıklayın';
    status.className = 'mt-3 p-3 rounded-lg border text-xs bg-red-500/10 border-red-500/20 text-red-300'; status.textContent = "Dosya backend'e gönderilemedi. Backend'in 8001 portunda çalıştığını kontrol edin.";
  }
}
async function runAdaptation() {
  if (!uploadedAdaptationFile) { document.getElementById('adapt-file-input')?.click(); return; }
  const name = document.getElementById('adapt-name').value.trim() || APP_STATE.facilityName || 'musteri';
  const btn = document.getElementById('adapt-run-btn'), txt = document.getElementById('adapt-btn-txt'),
    pbar = document.getElementById('adapt-pbar'), fill = document.getElementById('adapt-fill'),
    suc = document.getElementById('adapt-success'), mname = document.getElementById('adapt-model-name');
  btn.disabled = true; txt.textContent = 'Warm-start çalışıyor...'; pbar.classList.remove('hidden'); fill.style.width = '45%';
  try {
    const fd = new FormData(); fd.append('file', uploadedAdaptationFile); fd.append('facility_name', name);
    const res = await fetch(`${API_BASE}/api/adaptation/run`, { method: 'POST', body: fd }); if (!res.ok) throw new Error('adaptation failed');
    const data = await res.json(); fill.style.width = '100%'; mname.textContent = data.model_name; suc.classList.remove('hidden'); txt.textContent = '✓ Tamamlandı';
  } catch (error) { txt.textContent = 'Backend hatası'; fill.style.width = '0%'; }
  finally { btn.disabled = false; }
}
