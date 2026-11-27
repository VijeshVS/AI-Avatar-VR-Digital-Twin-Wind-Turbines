const HEALTH_OK = 0.75;
const HEALTH_WARN = 0.45;
const HISTORY_POINTS = 60;
const POLL_MS = 1000;

const state = {
  data: null,
  scenarios: [],
  catalog: null,
  injections: [],
  history: new Map(),
  scrubbing: false,
  loading: false,
  asking: false,
  error: null,
  pendingAsk: null,
  askedOnLoad: false,
};

const el = {
  dot: document.getElementById('conn-dot'),
  status: document.getElementById('status'),
  cards: document.getElementById('cards'),
  plant: document.getElementById('plant'),
  scenarios: document.getElementById('scenarios'),
  play: document.getElementById('play'),
  speed: document.getElementById('speed'),
  clock: document.getElementById('clock'),
  scrub: document.getElementById('scrub'),
  labPresets: document.getElementById('lab-presets'),
  labForm: document.getElementById('lab-form'),
  labType: document.getElementById('lab-type'),
  labSeverity: document.getElementById('lab-severity'),
  labSeverityVal: document.getElementById('lab-severity-val'),
  labOnsetNow: document.getElementById('lab-onset-now'),
  labOnsetH: document.getElementById('lab-onset-h'),
  labProgression: document.getElementById('lab-progression'),
  labDuration: document.getElementById('lab-duration'),
  labSignalWrap: document.getElementById('lab-signal-wrap'),
  labSignal: document.getElementById('lab-signal'),
  labActive: document.getElementById('lab-active'),
  labSignals: document.getElementById('lab-signals'),
  labReset: document.getElementById('lab-reset'),
  labSave: document.getElementById('lab-save'),
  labLoadBtn: document.getElementById('lab-load-btn'),
  labLoadFile: document.getElementById('lab-load-file'),
  presets: document.getElementById('ai-presets'),
  question: document.getElementById('ai-question'),
  mode: document.getElementById('ai-mode'),
  ask: document.getElementById('ai-ask'),
  empty: document.getElementById('ai-empty'),
  answer: document.getElementById('ai-answer'),
  meta: document.getElementById('ai-meta'),
  diagnosis: document.getElementById('ai-diagnosis'),
  tools: document.getElementById('ai-tools'),
  steps: document.getElementById('ai-steps'),
  disclaimer: document.getElementById('ai-disclaimer'),
};

const bandClass = (health) => (health >= HEALTH_OK ? 'ok' : health >= HEALTH_WARN ? 'warn' : 'bad');
const bandLabel = (value) => (value === 'healthy' ? 'nominal' : value === 'warning' ? 'degraded' : value);
const pretty = (id) => String(id || '').replaceAll('_', ' ');

const SIGNAL_LABELS = {
  wind_speed_ms: 'wind speed',
  ambient_temp_c: 'ambient temperature',
  rotor_rpm: 'rotor speed',
  active_power_kw: 'active power',
  power_ratio: 'power ratio',
  yaw_deg: 'yaw angle',
  gearbox_temp_c: 'gearbox oil temperature',
  gearbox_temp_rise_c: 'gearbox oil temperature rise',
  gearbox_vibration_mm_s: 'gearbox vibration',
  nacelle_vibration_mm_s: 'nacelle vibration',
  generator_winding_temp_c: 'generator winding temperature',
  converter_faults: 'converter fault count',
  pitch_angle_deg: 'pitch angle',
  pitch_position_error_deg: 'pitch position error',
  blade_pass_hz: 'blade pass frequency',
  rotor_angle_deg: 'rotor azimuth',
  rotor_imbalance_index: 'rotor imbalance index',
  main_bearing_temp: 'main bearing temperature',
  main_bearing_vibration: 'main bearing vibration',
};

const signalLabel = (id) => SIGNAL_LABELS[id] || pretty(id);

function scenarioLabel(id) {
  const match = state.scenarios.find((scenario) => scenario.id === id);
  return match ? match.label : id || '—';
}

function fmt(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  return Math.abs(number) >= 100 ? number.toFixed(0) : number.toFixed(2);
}

function chip(text, className = 'tool') {
  const span = document.createElement('span');
  span.className = `chip ${className}`;
  span.textContent = text;
  return span;
}

// -- health cards -----------------------------------------------------------

function cardHtml(component, trend) {
  const health = Number(component.health);
  const color = bandClass(health);
  const factor = (component.factors || []).find((item) => item.severity > 0);
  const why = factor
    ? `${signalLabel(factor.signal)} ${fmt(factor.value)} ${factor.unit || ''} (warn ${fmt(factor.warn)})`
    : 'all signals within envelope';

  let eta = '—';
  if (trend) {
    if (trend.band === 'critical') eta = 'at critical threshold';
    else if (trend.band === 'stable') eta = 'stable';
    else if (trend.band === 'unknown') eta = 'no history yet';
    else eta = `≈ ${trend.band} to critical`;
  }

  return `
    <article class="card ${color}" data-id="${component.id}" tabindex="0"
             role="button" aria-label="Focus ${component.label}">
      <header>
        <span class="name">${component.label}</span>
        <span class="chip ${color}">${bandLabel(component.state)}</span>
      </header>
      <div class="bar"><div class="fill ${color}" style="width:${Math.max(0, Math.min(100, health * 100))}%"></div></div>
      <div class="numbers">
        <span class="pct">${Math.round(health * 100)}%</span>
        <span class="eta">${eta}</span>
      </div>
      <div class="why">${why}</div>
      <canvas id="spark-${component.id}" width="520" height="72"></canvas>
    </article>`;
}

function drawSpark(id) {
  const canvas = document.getElementById(`spark-${id}`);
  if (!canvas) return;

  const ctx = canvas.getContext('2d');
  const width = canvas.width;
  const height = canvas.height;
  const pad = 6;
  ctx.clearRect(0, 0, width, height);

  // Envelope bands, so a flat line still reads against the thresholds.
  ctx.setLineDash([4, 6]);
  ctx.lineWidth = 1;
  for (const [value, color] of [[HEALTH_WARN, 'rgba(255,82,87,0.35)'], [HEALTH_OK, 'rgba(255,176,32,0.25)']]) {
    const y = pad + (1 - value) * (height - pad * 2);
    ctx.strokeStyle = color;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }
  ctx.setLineDash([]);

  const points = state.history.get(id) || [];
  if (points.length === 0) return;

  const color = points[points.length - 1] >= HEALTH_OK
    ? '#3ddc84'
    : points[points.length - 1] >= HEALTH_WARN ? '#ffb020' : '#ff5257';

  ctx.strokeStyle = color;
  ctx.lineWidth = 2.5;
  ctx.lineJoin = 'round';
  ctx.beginPath();

  points.forEach((value, index) => {
    const x = points.length === 1 ? width / 2 : (index / (points.length - 1)) * width;
    const y = pad + (1 - value) * (height - pad * 2);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function renderHealth(payload) {
  const { session, frame, prognosis } = payload;

  const trends = new Map(((prognosis && prognosis.components) || []).map((item) => [item.component_id, item]));

  for (const component of frame.components) {
    const history = state.history.get(component.id) || [];
    history.push(component.health);
    if (history.length > HISTORY_POINTS) history.shift();
    state.history.set(component.id, history);
  }

  el.cards.innerHTML = frame.components
    .map((component) => cardHtml(component, trends.get(component.id)))
    .join('');
  for (const component of frame.components) drawSpark(component.id);

  const worst = frame.components.reduce((a, b) => (a.health <= b.health ? a : b));
  const critical = frame.components.filter((component) => component.health < HEALTH_WARN).length;
  const watch = frame.components.filter(
    (component) => component.health >= HEALTH_WARN && component.health < HEALTH_OK,
  ).length;
  el.plant.textContent =
    `worst ${worst.label} ${Math.round(worst.health * 100)}%     ·     ` +
    `${critical} critical     ·     ${watch} watch`;

  const speed = session.playing ? `${session.speed}×` : 'paused';
  el.status.textContent = `${scenarioLabel(session.scenario)}  ·  t=${session.t.toFixed(1)} s  ·  ${speed}`;
  el.status.className = 'status';
  el.dot.className = 'dot ok';
  state.error = null;

  el.play.textContent = session.playing ? 'Pause' : 'Resume';
  if (document.activeElement !== el.speed) el.speed.value = String(session.speed);
  if (document.activeElement !== el.scrub) el.scrub.value = String(Math.min(session.t, Number(el.scrub.max)));
  el.clock.textContent = `t = ${session.t.toFixed(1)} s`;

  for (const button of el.scenarios.querySelectorAll('button')) {
    button.classList.toggle('active', button.dataset.scenario === session.scenario);
  }
  for (const card of el.cards.querySelectorAll('.card')) {
    card.classList.toggle('focused', card.dataset.id === session.focus);
  }
  renderLabSignals(frame);
}

// -- scenario lab -----------------------------------------------------------

const LAB_SIGNAL_IDS = [
  'wind_speed_ms',
  'ambient_temp_c',
  'gearbox_temp_c',
  'gearbox_vibration_mm_s',
  'generator_winding_temp_c',
  'main_bearing_temp',
  'main_bearing_vibration',
  'pitch_angle_deg',
  'pitch_position_error_deg',
  'active_power_kw',
];

function renderLabSignals(frame) {
  if (!el.labSignals || !frame || !Array.isArray(frame.signals)) return;
  const byId = new Map(frame.signals.map((s) => [s.id, s]));
  el.labSignals.replaceChildren();
  for (const id of LAB_SIGNAL_IDS) {
    const sig = byId.get(id);
    if (!sig) continue;
    const item = document.createElement('span');
    item.className = 'lab-sig-pill';
    item.textContent = `${signalLabel(id)}: ${fmt(sig.measured)} ${sig.unit}`;
    el.labSignals.append(item);
  }
}

function catalogEntryById(typeId) {
  if (!state.catalog || !Array.isArray(state.catalog.entries)) return null;
  return state.catalog.entries.find((entry) => entry.id === typeId) || null;
}

function syncLabDefaults() {
  const entry = catalogEntryById(el.labType.value);
  if (!entry) return;
  const prog = entry.default_progression || {};
  if (prog.kind) el.labProgression.value = prog.kind;
  if (prog.duration_h !== undefined) el.labDuration.value = String(prog.duration_h);

  const isSensor = entry.category === 'sensor';
  el.labSignalWrap.hidden = !isSensor;
  if (isSensor && entry.default_params && entry.default_params.signal) {
    el.labSignal.value = entry.default_params.signal;
  }
}

function renderActiveInjections() {
  if (!el.labActive) return;
  el.labActive.replaceChildren();
  if (!state.injections.length) {
    const empty = document.createElement('span');
    empty.className = 'hint';
    empty.textContent = 'No active injections — nominal physics running.';
    el.labActive.append(empty);
    return;
  }

  for (const inj of state.injections) {
    const entry = catalogEntryById(inj.type);
    const label = entry ? entry.label : inj.type;
    const prog = inj.progression || {};
    const paramNote = inj.params && inj.params.signal ? ` · ${inj.params.signal}` : '';

    const row = document.createElement('div');
    row.className = 'lab-active-item';

    const info = document.createElement('span');
    info.className = 'lab-active-info';
    info.textContent =
      `${label}${paramNote} · sev ${Number(inj.severity).toFixed(2)} · ` +
      `onset ${Number(inj.onset_asset_h).toFixed(1)} h · ` +
      `${prog.kind || 'ramp'} (${prog.duration_h ?? 0} h)`;

    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'lab-remove';
    removeBtn.dataset.removeId = inj.id;
    removeBtn.textContent = 'Remove';

    row.append(info, removeBtn);
    el.labActive.append(row);
  }
}

async function loadInjections() {
  try {
    const response = await fetch('/api/inject', { cache: 'no-store' });
    if (!response.ok) return;
    const payload = await response.json();
    state.injections = payload.injections || [];
    renderActiveInjections();
  } catch (_) {
    // Keep last known injection list when polling offline.
  }
}

async function loadCatalog() {
  try {
    const response = await fetch('/api/inject/catalog', { cache: 'no-store' });
    if (!response.ok) return;
    const catalog = await response.json();
    state.catalog = catalog;

    el.labType.replaceChildren();
    for (const cat of catalog.categories || []) {
      const group = document.createElement('optgroup');
      group.label = cat.label;
      for (const entry of (catalog.entries || []).filter((item) => item.category === cat.id)) {
        const option = document.createElement('option');
        option.value = entry.id;
        option.textContent = entry.label;
        group.append(option);
      }
      if (group.children.length > 0) el.labType.append(group);
    }

    el.labSignal.replaceChildren();
    for (const signalId of catalog.signals || []) {
      const option = document.createElement('option');
      option.value = signalId;
      option.textContent = `${signalLabel(signalId)} (${signalId})`;
      el.labSignal.append(option);
    }

    el.labPresets.replaceChildren();
    for (const preset of catalog.presets || []) {
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.presetId = preset.id;
      button.title = preset.description || '';
      button.textContent = preset.label;
      el.labPresets.append(button);
    }

    syncLabDefaults();
  } catch (_) {
    el.labType.innerHTML = '<option value="">catalog unavailable</option>';
  }
}

async function applyPreset(presetId) {
  if (!state.catalog) return;
  const preset = (state.catalog.presets || []).find((item) => item.id === presetId);
  if (!preset) return;

  try {
    await fetch('/api/inject/reset', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reset_t: Boolean(preset.reset_t) }),
    });
    await fetch('/api/session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        scenario: preset.scenario || 'nominal',
        reset_t: Boolean(preset.reset_t),
        playing: preset.playing !== undefined ? Boolean(preset.playing) : true,
        speed: preset.speed || 1.0,
      }),
    });
    for (const inj of preset.injections || []) {
      await fetch('/api/inject', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(inj),
      });
    }
    state.history.clear();
    await loadInjections();
    await load();
  } catch (error) {
    renderOffline(String(error));
  }
}

// -- copilot ----------------------------------------------------------------

function setAsking(busy) {
  state.asking = busy;
  el.ask.disabled = busy;
  el.ask.textContent = busy ? 'Asking…' : 'Ask';
  for (const button of el.presets.querySelectorAll('button')) button.disabled = busy;
}

function renderDiagnosis(diagnosis) {
  const hasDiagnosis = diagnosis && diagnosis.component_id;
  el.diagnosis.hidden = !hasDiagnosis;
  el.diagnosis.replaceChildren();
  if (!hasDiagnosis) return;

  el.diagnosis.append(
    chip(`${diagnosis.label} · ${diagnosis.health_pct}% · ${bandLabel(diagnosis.state)}`, bandClass(diagnosis.health)),
  );
  if (diagnosis.band && diagnosis.band !== 'unknown') {
    el.diagnosis.append(
      chip(
        diagnosis.band === 'critical' ? 'at critical threshold' : `${diagnosis.band} to critical`,
        'tool',
      ),
    );
  }
  if (diagnosis.top_factor) {
    const factor = diagnosis.top_factor;
    el.diagnosis.append(
      chip(`${signalLabel(factor.signal)} ${fmt(factor.value)} ${factor.unit}`, 'tool'),
    );
  }
}

function renderTools(tools) {
  const hasTools = Array.isArray(tools) && tools.length > 0;
  el.tools.hidden = !hasTools;
  el.tools.replaceChildren();
  if (!hasTools) return;

  const label = document.createElement('span');
  label.className = 'tools-label';
  label.textContent = 'tools';
  el.tools.append(label, ...tools.map((tool) => chip(tool, 'tool')));
}

function renderSteps(procedure) {
  const hasSteps = procedure && Array.isArray(procedure.steps) && procedure.steps.length > 0;
  el.steps.hidden = !hasSteps;
  el.steps.replaceChildren();
  if (!hasSteps) return;

  const list = document.createElement('ol');
  list.className = 'step-list';

  for (const step of procedure.steps) {
    const item = document.createElement('li');
    item.className = step.safety ? 'step safety' : 'step';

    const head = document.createElement('div');
    head.className = 'step-head';

    const action = document.createElement('span');
    action.className = 'step-action';
    action.textContent = step.action;
    head.append(action);

    if (step.safety) head.append(chip('safety', 'bad'));
    if (step.tool) head.append(chip(step.tool, 'tool'));

    const why = document.createElement('p');
    why.className = 'step-why';
    why.textContent = step.why;

    item.append(head, why);
    list.append(item);
  }

  el.steps.append(list);
}

function renderAssistant(payload) {
  el.empty.hidden = true;
  el.answer.hidden = false;
  el.answer.textContent = payload.answer;

  el.meta.hidden = false;
  el.meta.replaceChildren();
  el.meta.append(chip(payload.source === 'llm' ? 'LLM' : 'rules', payload.source === 'llm' ? 'ok' : 'warn'));

  const context = document.createElement('span');
  context.textContent =
    `${scenarioLabel(payload.scenario)} · t=${Number(payload.t).toFixed(1)} s` +
    (payload.worst ? ` · worst ${payload.worst.label}` : '') +
    (payload.detail ? ` · ${payload.detail}` : '');
  el.meta.append(context);

  if (payload.mode === 'procedure' && payload.procedure) {
    renderDiagnosis(payload.diagnosis);
    renderTools(payload.procedure.tools);
    renderSteps(payload.procedure);
    el.disclaimer.hidden = false;
    el.disclaimer.textContent = payload.disclaimer || '';
  } else {
    el.diagnosis.hidden = true;
    el.tools.hidden = true;
    el.steps.hidden = true;
    el.disclaimer.hidden = true;
  }

  applyActions(payload.actions);
}

async function applyActions(actions) {
  for (const action of actions || []) {
    if (action.type === 'focus_component') await command({ focus: action.component_id });
    else if (action.type === 'set_scenario') await command({ scenario: action.scenario, reset_t: true });
    else if (action.type === 'set_time') await command({ t: action.seconds });
  }
}

async function ask(mode) {
  if (state.asking) return;

  const question = el.question.value.trim() || 'What is wrong with the turbine?';
  const answerMode = mode || el.mode.value;

  setAsking(true);
  el.empty.hidden = true;
  el.answer.hidden = false;
  el.answer.classList.remove('bad');
  el.answer.textContent = 'Thinking…';
  el.meta.hidden = true;
  el.diagnosis.hidden = true;
  el.tools.hidden = true;
  el.steps.hidden = true;
  el.disclaimer.hidden = true;

  try {
    const response = await fetch('/api/assistant', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, mode: answerMode }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderAssistant(await response.json());
  } catch (error) {
    el.answer.textContent =
      `Copilot unavailable: ${error}. The clock and health cards keep working.`;
    el.answer.classList.add('bad');
  } finally {
    setAsking(false);
  }
}

function maybeAskOnLoad() {
  if (!state.pendingAsk || state.askedOnLoad) return;
  state.askedOnLoad = true;
  el.question.value = state.pendingAsk.question;
  el.mode.value = state.pendingAsk.mode;
  ask(state.pendingAsk.mode);
}

// -- polling and commands ---------------------------------------------------

function renderOffline(message) {
  state.error = message;
  el.status.textContent = 'service unreachable — retrying';
  el.status.className = 'status bad';
  el.dot.className = 'dot bad';
}

async function load() {
  if (state.loading) return;
  state.loading = true;
  try {
    const response = await fetch('/api/state', { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    state.data = payload;
    renderHealth(payload);
    maybeAskOnLoad();
  } catch (error) {
    renderOffline(String(error));
  } finally {
    state.loading = false;
  }
}

async function command(body) {
  try {
    const response = await fetch('/api/session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    await load();
  } catch (error) {
    renderOffline(String(error));
  }
}

async function loadScenarios() {
  try {
    const response = await fetch('/api/scenarios', { cache: 'no-store' });
    const payload = await response.json();
    state.scenarios = payload.scenarios || [];
    el.scenarios.innerHTML = state.scenarios
      .map((scenario) => `<button data-scenario="${scenario.id}">${scenario.label}</button>`)
      .join('');
  } catch (error) {
    el.scenarios.innerHTML = '<span class="hint">scenario catalogue unavailable</span>';
  }
}

// -- events -----------------------------------------------------------------

el.play.addEventListener('click', () => {
  if (!state.data) return;
  command({ playing: !state.data.session.playing });
});

el.speed.addEventListener('change', () => command({ speed: Number(el.speed.value) }));

el.scrub.addEventListener('pointerdown', () => { state.scrubbing = true; });
el.scrub.addEventListener('input', () => {
  el.clock.textContent = `t = ${Number(el.scrub.value).toFixed(1)} s`;
});
el.scrub.addEventListener('change', () => {
  state.scrubbing = false;
  command({ t: Number(el.scrub.value) });
});

el.scenarios.addEventListener('click', (event) => {
  const button = event.target.closest('button[data-scenario]');
  if (button) command({ scenario: button.dataset.scenario, reset_t: true });
});

el.cards.addEventListener('click', (event) => {
  const card = event.target.closest('.card[data-id]');
  if (card) command({ focus: card.dataset.id });
});

el.cards.addEventListener('keydown', (event) => {
  if (event.key !== 'Enter' && event.key !== ' ') return;
  const card = event.target.closest('.card[data-id]');
  if (card) {
    event.preventDefault();
    command({ focus: card.dataset.id });
  }
});

el.presets.addEventListener('click', (event) => {
  const button = event.target.closest('button[data-question]');
  if (!button) return;
  el.question.value = button.dataset.question;
  el.mode.value = button.dataset.mode;
  ask(button.dataset.mode);
});

el.ask.addEventListener('click', () => ask());

el.question.addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    event.preventDefault();
    ask();
  }
});

if (el.labType) {
  el.labType.addEventListener('change', syncLabDefaults);
}

if (el.labSeverity) {
  el.labSeverity.addEventListener('input', () => {
    el.labSeverityVal.textContent = Number(el.labSeverity.value).toFixed(2);
  });
}

if (el.labOnsetNow) {
  el.labOnsetNow.addEventListener('change', () => {
    el.labOnsetH.disabled = el.labOnsetNow.checked;
  });
}

if (el.labForm) {
  el.labForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const type = el.labType.value;
    if (!type) return;
    const entry = catalogEntryById(type);
    const params = {};
    if (entry && entry.category === 'sensor' && el.labSignal.value) {
      params.signal = el.labSignal.value;
    }
    const body = {
      type,
      severity: Number(el.labSeverity.value),
      onset_asset_h: el.labOnsetNow.checked ? 'now' : Number(el.labOnsetH.value || 0),
      progression: {
        kind: el.labProgression.value,
        duration_h: Number(el.labDuration.value || 0),
      },
      params,
    };
    try {
      const response = await fetch('/api/inject', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      await loadInjections();
      await load();
    } catch (error) {
      renderOffline(String(error));
    }
  });
}

if (el.labPresets) {
  el.labPresets.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-preset-id]');
    if (button) applyPreset(button.dataset.presetId);
  });
}

if (el.labActive) {
  el.labActive.addEventListener('click', async (event) => {
    const button = event.target.closest('button[data-remove-id]');
    if (!button) return;
    try {
      const response = await fetch(`/api/inject/${encodeURIComponent(button.dataset.removeId)}`, {
        method: 'DELETE',
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      await loadInjections();
      await load();
    } catch (error) {
      renderOffline(String(error));
    }
  });
}

if (el.labReset) {
  el.labReset.addEventListener('click', async () => {
    try {
      const response = await fetch('/api/inject/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reset_t: false }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      state.history.clear();
      await loadInjections();
      await load();
    } catch (error) {
      renderOffline(String(error));
    }
  });
}

if (el.labSave) {
  el.labSave.addEventListener('click', async () => {
    try {
      const response = await fetch('/api/inject/export', { cache: 'no-store' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'scenario_injections.json';
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      renderOffline(String(error));
    }
  });
}

if (el.labLoadBtn && el.labLoadFile) {
  el.labLoadBtn.addEventListener('click', () => el.labLoadFile.click());
  el.labLoadFile.addEventListener('change', async () => {
    const file = el.labLoadFile.files && el.labLoadFile.files[0];
    if (!file) return;
    try {
      const parsed = JSON.parse(await file.text());
      const response = await fetch('/api/inject/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(parsed),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      state.history.clear();
      await loadInjections();
      await load();
    } catch (error) {
      renderOffline(String(error));
    } finally {
      el.labLoadFile.value = '';
    }
  });
}

const presets = {
  what: { question: 'What is wrong with the turbine?', mode: 'summary' },
  why: { question: 'Why is it failing?', mode: 'summary' },
  fix: { question: 'How do I fix it?', mode: 'procedure' },
};

const askParam = new URLSearchParams(location.search).get('ask');
if (askParam) {
  state.pendingAsk = presets[askParam] || { question: askParam, mode: 'summary' };
}

loadScenarios();
loadCatalog();
loadInjections();
load();
setInterval(() => {
  load();
  loadInjections();
}, POLL_MS);
