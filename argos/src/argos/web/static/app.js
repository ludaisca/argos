"use strict";

/* ── utilidades ─────────────────────────────────────────────────────── */

const TOKEN =
  new URLSearchParams(location.search).get("token") ||
  localStorage.getItem("argos_token") ||
  "";
if (TOKEN) localStorage.setItem("argos_token", TOKEN);

const $ = (id) => document.getElementById(id);

async function api(path, { method = "GET", body } = {}) {
  const sep = path.includes("?") ? "&" : "?";
  const url = TOKEN ? `${path}${sep}token=${encodeURIComponent(TOKEN)}` : path;
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  let data = null;
  try { data = await res.json(); } catch { /* sin cuerpo */ }
  if (!res.ok) {
    throw new Error((data && (data.detail || data.error)) || `HTTP ${res.status}`);
  }
  return data;
}

let toastTimer = null;
function toast(msg, bad = false) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  el.classList.toggle("bad", bad);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), 3400);
}

/* markdown mínimo (headings, listas, bold/italic, code, links, hr) */
function mdToHtml(src) {
  const esc = (s) =>
    s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const inline = (s) =>
    s
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(
        /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
        '<a href="$2" target="_blank" rel="noopener">$1</a>'
      );
  const lines = esc(src).split(/\r?\n/);
  let html = "";
  let inCode = false;
  let inList = false;
  const closeList = () => { if (inList) { html += "</ul>"; inList = false; } };
  for (const line of lines) {
    if (line.trimStart().startsWith("```")) {
      closeList();
      html += inCode ? "</code></pre>" : "<pre><code>";
      inCode = !inCode;
      continue;
    }
    if (inCode) { html += line + "\n"; continue; }
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) {
      closeList();
      const level = Math.min(h[1].length + 2, 6);
      html += `<h${level}>${inline(h[2])}</h${level}>`;
      continue;
    }
    const li = line.match(/^\s*[-*]\s+(.*)$/);
    if (li) {
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${inline(li[1])}</li>`;
      continue;
    }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) { closeList(); html += "<hr>"; continue; }
    if (!line.trim()) { closeList(); continue; }
    html += `<p>${inline(line)}</p>`;
  }
  closeList();
  if (inCode) html += "</code></pre>";
  return html;
}

const platformLabel = (p) => p.charAt(0).toUpperCase() + p.slice(1);

/* ── estado ─────────────────────────────────────────────────────────── */

const state = {
  meta: null,
  status: null,
  run: null,
  daemon: null,
  selectedRun: null,
};

/* ── tabs ───────────────────────────────────────────────────────────── */

document.querySelectorAll("nav#tabs button").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("nav#tabs button").forEach((b) =>
      b.classList.toggle("active", b === btn)
    );
    document.querySelectorAll(".tab").forEach((s) =>
      s.classList.toggle("active", s.id === `tab-${btn.dataset.tab}`)
    );
    if (btn.dataset.tab === "results") refreshRuns();
    if (btn.dataset.tab === "run") pollOnce();
  });
});

/* ── plataformas y targets ──────────────────────────────────────────── */

function selectedPlatforms() {
  return [...document.querySelectorAll("#b-platforms input[data-platform]")]
    .filter((cb) => cb.checked)
    .map((cb) => cb.dataset.platform);
}

function renderPlatformChecks(selected) {
  const box = $("b-platforms");
  box.innerHTML = "";
  (state.meta?.platforms || []).forEach((p) => {
    const label = document.createElement("label");
    label.className = "inline";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.dataset.platform = p;
    cb.checked = !selected || selected.includes(p);
    cb.addEventListener("change", () => {
      if (!selectedPlatforms().length) { cb.checked = true; toast("Al menos una plataforma", true); }
      pruneTargetRows();
    });
    label.append(cb, document.createTextNode(" " + platformLabel(p)));
    box.append(label);
  });
}

function typeOptions() {
  const types = [];
  for (const p of selectedPlatforms()) {
    for (const t of state.meta?.target_types?.[p] || []) types.push(t);
  }
  return types;
}

function kindOptionsFor(type) {
  return state.meta?.kinds?.[type] || [];
}

function pruneTargetRows() {
  const allowed = new Set(typeOptions());
  document.querySelectorAll("#targets-table tbody tr").forEach((tr) => {
    const sel = tr.querySelector("td select");
    if (sel && !allowed.has(sel.value)) tr.remove();
  });
}

function fillKindSelect(select, type, current) {
  select.innerHTML = "";
  const options = ["", ...kindOptionsFor(type)];
  options.forEach((k) => {
    const o = document.createElement("option");
    o.value = k;
    o.textContent = k || "—";
    select.append(o);
  });
  select.value = current && options.includes(current) ? current : "";
}

function addTargetRow(target = {}) {
  const tbody = $("targets-table").querySelector("tbody");
  const tr = document.createElement("tr");
  const td = (el) => { const c = document.createElement("td"); c.append(el); return c; };

  const typeSel = document.createElement("select");
  const types = typeOptions();
  types.forEach((t) => {
    const o = document.createElement("option");
    o.value = t; o.textContent = t;
    typeSel.append(o);
  });
  if (target.type && types.includes(target.type)) typeSel.value = target.type;

  const valueIn = document.createElement("input");
  valueIn.placeholder = "usuario / etiqueta / término / URL";
  valueIn.value = target.value || "";

  const limitIn = document.createElement("input");
  limitIn.type = "number";
  limitIn.min = 1;
  limitIn.max = state.meta?.target_limit_cap || 20;
  limitIn.value = target.limit || 12;

  const kindSel = document.createElement("select");
  fillKindSelect(kindSel, typeSel.value, target.kind);
  typeSel.addEventListener("change", () => fillKindSelect(kindSel, typeSel.value, null));

  const del = document.createElement("button");
  del.textContent = "✕";
  del.title = "Quitar";
  del.addEventListener("click", () => tr.remove());

  tr.append(td(typeSel), td(valueIn), td(limitIn), td(kindSel), td(del));
  tr.lastChild.classList.add("actions");
  tbody.append(tr);
}

function collectTargets() {
  return [...document.querySelectorAll("#targets-table tbody tr")]
    .map((tr) => {
      const cells = [...tr.querySelectorAll("td")];
      const type = cells[0].querySelector("select").value;
      const value = cells[1].querySelector("input").value.trim();
      const limit = parseInt(cells[2].querySelector("input").value, 10) || 12;
      const kind = cells[3].querySelector("select").value;
      const item = { type, limit };
      if (value) item.value = value;
      if (kind) item.kind = kind;
      return item;
    })
    .filter((t) => t.value || t.type === "fb_groups_feed");
}

function briefPayloadFromForm() {
  return {
    job: $("b-job").value.trim() || "research",
    objective: $("b-objective").value.trim(),
    questions: $("b-questions").value.split("\n").map((s) => s.trim()).filter(Boolean),
    platforms: selectedPlatforms(),
    targets: collectTargets(),
    max_targets: parseInt($("b-max-targets").value, 10) || 6,
  };
}

async function loadBrief() {
  const data = await api("/api/brief");
  if (data.source === "none") {
    $("b-source").textContent = "sin brief configurado todavía";
    return;
  }
  $("b-job").value = data.job || "";
  $("b-objective").value = data.objective || "";
  $("b-questions").value = (data.questions || []).join("\n");
  $("b-max-targets").value = data.max_targets || 6;
  renderPlatformChecks(data.platforms);
  const tbody = $("targets-table").querySelector("tbody");
  tbody.innerHTML = "";
  (data.targets || []).forEach((t) => addTargetRow(t));
  const labels = {
    home: "volumen (brief.yaml)",
    env: "texto de entorno",
    "env-file": "archivo por entorno",
  };
  $("b-source").textContent = `fuente: ${labels[data.source] || data.source}`;
}

async function saveBrief() {
  const payload = briefPayloadFromForm();
  if (!payload.objective) { toast("Falta el objetivo", true); return; }
  const saved = await api("/api/brief", { method: "PUT", body: payload });
  toast("Brief guardado");
  $("b-source").textContent = `fuente: volumen (${saved.job})`;
  pollOnce();
}

async function planNow() {
  const out = $("plan-out");
  out.classList.remove("hidden");
  out.textContent = "Consultando al LLM…";
  try {
    const data = await api("/api/plan", { method: "POST" });
    const rows = (data.targets || [])
      .map((t) => `• ${t.type}: ${t.value || "(feed)"} (límite ${t.limit}${t.kind ? ", kind " + t.kind : ""})`)
      .join("\n");
    out.textContent = `Plan propuesto — ${data.targets.length} objetivo(s):\n\n${rows}`;
  } catch (e) {
    out.textContent = `Error: ${e.message}`;
    toast("Falló el plan", true);
  }
}

/* ── corrida ────────────────────────────────────────────────────────── */

function renderRun(rec) {
  const running = rec.status === "running";
  $("r-run").disabled = running;
  $("r-cancel").classList.toggle("hidden", !running);
  $("r-state").textContent = rec.status;
  $("r-state").className =
    "pill " + (running ? "warn" : rec.status === "ok" ? "ok" : "bad");
  if (rec.log || rec.status !== "running") {
    $("log-label").textContent = `— ${rec.label}`;
    $("console").textContent = rec.log || "(sin salida)";
    $("console").scrollTop = $("console").scrollHeight;
  }
  if (!running) {
    refreshRuns();
    if (rec.result) {
      const results = rec.result.results || [];
      const ok = results.filter((x) => x.status === "ok").length;
      if (rec.status === "ok") {
        toast(`Corrida ok: ${ok}/${results.length} objetivos · ${rec.result.run_name || ""}`);
      }
    }
  }
}

async function startRun() {
  try {
    const rec = await api("/api/run", { method: "POST", body: { source: "brief" } });
    state.run = rec;
    renderRun(rec);
    toast("Corrida iniciada");
  } catch (e) { toast(e.message, true); }
}

async function startJob(file) {
  try {
    const rec = await api("/api/run", { method: "POST", body: { source: "job", job: file } });
    state.run = rec;
    renderRun(rec);
    toast(`Trabajo ${file} en marcha`);
  } catch (e) { toast(e.message, true); }
}

async function cancelRun() {
  if (!state.run) return;
  try {
    const rec = await api(`/api/run/${state.run.id}`, { method: "DELETE" });
    state.run = rec;
    renderRun(rec);
    toast("Corrida detenida");
  } catch (e) { toast(e.message, true); }
}

/* ── daemon ─────────────────────────────────────────────────────────── */

function renderDaemon(d) {
  const running = !!d.running;
  $("d-state").textContent = running ? "on" : "off";
  $("d-state").className = "pill " + (running ? "ok" : "");
  $("d-start").disabled = running;
  $("d-stop").disabled = !running;
  $("d-info").textContent = running && d.record
    ? `corriendo desde ${d.record.started_at} · ${d.record.label}`
    : "";
  $("daemon-pill").textContent = `daemon: ${running ? "on" : "off"}`;
  $("daemon-pill").className = "pill " + (running ? "ok" : "");
}

async function daemonStart() {
  const interval = parseFloat($("d-interval").value) || 12;
  try {
    await api("/api/daemon", { method: "POST", body: { interval_hours: interval } });
    toast(`Daemon iniciado (cada ${interval} h)`);
  } catch (e) { toast(e.message, true); }
}

async function daemonStop() {
  try {
    await api("/api/daemon", { method: "DELETE" });
    toast("Daemon detenido");
  } catch (e) { toast(e.message, true); }
}

/* ── jobs ───────────────────────────────────────────────────────────── */

async function refreshJobs() {
  const data = await api("/api/jobs");
  const box = $("jobs-list");
  box.innerHTML = "";
  const pending = data.pending || [];
  if (!pending.length) {
    box.innerHTML = `<p class="muted small">Sin trabajos en cola (${data.done.length} hechos, ${data.failed.length} fallidos).</p>`;
    return;
  }
  const wrap = document.createElement("div");
  wrap.className = "jobs";
  pending.forEach((job) => {
    const row = document.createElement("div");
    row.className = "job";
    const info = document.createElement("div");
    info.className = "t";
    const b = document.createElement("b");
    b.textContent = job.job || job.file;
    const span = document.createElement("span");
    span.textContent = job.error ? `⚠ ${job.error}` : (job.objective || "").slice(0, 90);
    info.append(b, span);
    const runBtn = document.createElement("button");
    runBtn.textContent = "▶";
    runBtn.title = "Correr ahora";
    runBtn.addEventListener("click", () => startJob(job.file));
    const delBtn = document.createElement("button");
    delBtn.textContent = "🗑";
    delBtn.className = "danger";
    delBtn.title = "Borrar";
    delBtn.addEventListener("click", async () => {
      try {
        await api(`/api/jobs/${encodeURIComponent(job.file)}`, { method: "DELETE" });
        refreshJobs();
        toast("Trabajo borrado");
      } catch (e) { toast(e.message, true); }
    });
    row.append(info, runBtn, delBtn);
    wrap.append(row);
  });
  box.append(wrap);
}

async function queueCurrentBrief() {
  const payload = briefPayloadFromForm();
  payload.overwrite = true;
  if (!payload.objective) { toast("Falta el objetivo", true); return; }
  try {
    const res = await api("/api/jobs", { method: "POST", body: payload });
    toast(`Encolado: ${res.file}`);
    refreshJobs();
  } catch (e) { toast(e.message, true); }
}

/* ── resultados ─────────────────────────────────────────────────────── */

async function refreshRuns() {
  const data = await api("/api/runs");
  const list = $("runs-list");
  const runs = data.runs || [];
  if (!runs.length) {
    list.className = "muted";
    list.textContent = "Sin corridas todavía.";
    return;
  }
  list.className = "runs";
  list.innerHTML = "";
  runs.forEach((run) => {
    const row = document.createElement("div");
    row.className = "run" + (state.selectedRun === run.name ? " active" : "");
    const info = document.createElement("div");
    info.className = "t";
    const b = document.createElement("b");
    b.textContent = run.job;
    const span = document.createElement("span");
    span.textContent = `${run.name} · ${run.ok}/${run.total} ok · plan: ${run.plan_source || "?"}${run.analysis ? " · 📄" : ""}`;
    info.append(b, span);
    const open = document.createElement("span");
    open.textContent = "›";
    row.append(info, open);
    row.addEventListener("click", () => selectRun(run.name));
    list.append(row);
  });
}

async function selectRun(name) {
  state.selectedRun = name;
  document.querySelectorAll("#runs-list .run").forEach((el) =>
    el.classList.toggle("active", el.textContent.includes(name))
  );
  const detail = $("run-detail");
  detail.innerHTML = '<p class="muted">Cargando…</p>';
  try {
    const data = await api(`/api/runs/${encodeURIComponent(name)}`);
    $("run-title").textContent = name;
    const meta = data.meta || {};
    const parts = [];
    parts.push(`<p><b>${meta.job || name}</b> — plan: ${meta.plan_source || "?"} · ${meta.generated_at || ""}</p>`);
    if (meta.objective) parts.push(`<p class="muted">${meta.objective}</p>`);
    const results = meta.results || [];
    if (results.length) {
      parts.push(
        "<p>" +
          results
            .map((r) => `<span class="pill ${r.status === "ok" ? "ok" : "bad"}">${r.target}: ${r.status}</span>`)
            .join(" ") +
          "</p>"
      );
    }
    if (data.analysis) {
      parts.push('<h3 style="color:var(--accent)">Informe</h3>');
      parts.push(`<div class="md">${mdToHtml(data.analysis)}</div>`);
    } else {
      parts.push('<p class="muted">(sin analysis.md — ¿falló el análisis?)</p>');
    }
    if ((data.files || []).length) {
      const links = data.files
        .map((f) => {
          const href = `/api/runs/${encodeURIComponent(name)}/file/${f.path}${TOKEN ? `?token=${encodeURIComponent(TOKEN)}` : ""}`;
          return `<a href="${href}" target="_blank">${f.path}</a>`;
        })
        .join("");
      parts.push(`<div class="files">${links}</div>`);
    }
    detail.innerHTML = parts.join("");
  } catch (e) {
    detail.innerHTML = `<p class="bad">Error: ${e.message}</p>`;
  }
}

/* ── ajustes ────────────────────────────────────────────────────────── */

async function loadSettings() {
  const s = await api("/api/settings");
  $("s-base").value = s.llm_base_url || "";
  $("s-model").value = s.llm_model || "";
  $("s-key-current").textContent = s.llm_key_set
    ? `actual: ${s.llm_key_masked} (${s.llm_key_source})`
    : "sin API key configurada";
  $("s-interval").value = s.interval_hours || 12;
  $("d-interval").value = s.interval_hours || 12;
  return s;
}

async function saveSettings() {
  const payload = {
    llm_base_url: $("s-base").value.trim(),
    llm_model: $("s-model").value.trim(),
  };
  const key = $("s-key").value.trim();
  if (key) payload.llm_api_key = key;
  const s = await api("/api/settings", { method: "PUT", body: payload });
  $("s-key").value = "";
  toast("Ajustes guardados");
  $("s-key-current").textContent = s.llm_key_set
    ? `actual: ${s.llm_key_masked} (${s.llm_key_source})`
    : "sin API key configurada";
  pollOnce();
}

async function saveInterval() {
  const value = parseFloat($("s-interval").value) || 12;
  await api("/api/settings", { method: "PUT", body: { interval_hours: value } });
  $("d-interval").value = value;
  toast(`Cadencia: cada ${value} h`);
}

async function testLLM() {
  const out = $("s-test-out");
  out.classList.remove("hidden");
  out.textContent = "Probando…";
  try {
    const res = await api("/api/settings/test-llm", { method: "POST" });
    out.textContent = res.ok
      ? `✅ ${res.model} respondió: ${res.reply}`
      : `❌ ${res.model}: ${res.error}`;
    toast(res.ok ? "LLM ok" : "El LLM falló", !res.ok);
  } catch (e) {
    out.textContent = `❌ ${e.message}`;
    toast("El LLM falló", true);
  }
}

function renderSessions() {
  const box = $("s-sessions");
  const sessions = state.status?.sessions || {};
  box.innerHTML = Object.entries(sessions)
    .map(([platform, info]) => {
      const ok = info.cookies > 0 || info.profile;
      return `<span class="pill ${ok ? "ok" : "bad"}" title="cookies en config / perfil en disco">${platformLabel(platform)}: ${info.cookies} cookies · perfil ${info.profile ? "✓" : "—"}</span>`;
    })
    .join(" ");
}

async function runDoctor() {
  const out = $("doctor-out");
  out.classList.remove("hidden");
  out.textContent = "Chequeando sesiones (abre el navegador un momento)…";
  try {
    const data = await api("/api/doctor", { method: "POST" });
    const rows = Object.entries(data.platforms || {})
      .map(([name, st]) => {
        const good = st.status === "ok";
        return `<p><span class="pill ${good ? "ok" : "warn"}">${name}: ${st.status}</span> ${st.detail || ""}${st.hint ? ` <span class="muted">(${st.hint})</span>` : ""}</p>`;
      })
      .join("");
    out.innerHTML = `<p class="muted">navegador: ${data.browser?.detail || "?"}</p>${rows}`;
  } catch (e) {
    out.textContent = `❌ ${e.message}`;
  }
}

/* ── estado general ─────────────────────────────────────────────────── */

function renderStatus() {
  const s = state.status;
  if (!s) return;
  const llm = s.llm || {};
  $("llm-pill").textContent = llm.llm_configured
    ? `LLM: ${llm.llm_model}`
    : "LLM: sin configurar";
  $("llm-pill").className = "pill " + (llm.llm_configured ? "ok" : "bad");
  const sessions = s.sessions || {};
  const sessOk = Object.values(sessions).every((v) => v.cookies > 0 || v.profile);
  $("sessions-pill").textContent =
    "sesiones: " + Object.keys(sessions).map((p) => `${platformLabel(p)} ${sessions[p].cookies > 0 || sessions[p].profile ? "✓" : "—"}`).join(" · ");
  $("sessions-pill").className = "pill " + (sessOk ? "ok" : "warn");

  const q = s.quota || {};
  $("quota").innerHTML = Object.entries(q)
    .map(([platform, info]) => {
      const used = info.used ?? 0;
      const limit = info.daily_limit ?? 0;
      const pct = limit ? Math.round((used / limit) * 100) : 0;
      return `<div class="q">${platformLabel(platform)}: <b>${used}</b>/${limit} hoy (${pct}%) · quedan ${info.remaining ?? "?"}</div>`;
    })
    .join("");

  const paths = s.home ? `estado: ${s.home}` : "";
  if ($("s-paths")) $("s-paths").textContent = paths;
  renderSessions();
}

async function pollOnce() {
  try {
    const status = await api("/api/status");
    state.status = status;
    renderStatus();
    if (state.run && state.run.status === "running") {
      const rec = await api(`/api/run/${state.run.id}`);
      state.run = rec;
      renderRun(rec);
    }
    const d = await api("/api/daemon");
    state.daemon = d;
    renderDaemon(d);
    if (!state.run || state.run.status !== "running") {
      if (d.running && d.record) {
        $("log-label").textContent = "— daemon";
        $("console").textContent = d.record.log || "…";
        $("console").scrollTop = $("console").scrollHeight;
      }
    }
    await refreshJobs();
  } catch { /* servidor caído: reintenta en el próximo tick */ }
}

/* ── arranque ───────────────────────────────────────────────────────── */

async function boot() {
  try {
    state.meta = await api("/api/meta");
  } catch {
    toast("No se pudo hablar con el servidor", true);
    return;
  }
  renderPlatformChecks(null);
  addTargetRow();
  await bootLoad();
  setInterval(pollOnce, 3000);
}

async function bootLoad() {
  try { await loadBrief(); } catch (e) { toast(`Brief: ${e.message}`, true); }
  try { await loadSettings(); } catch (e) { toast(`Ajustes: ${e.message}`, true); }
  await pollOnce();
  await refreshRuns();
}

$("b-save").addEventListener("click", () => saveBrief().catch((e) => toast(e.message, true)));
$("b-plan").addEventListener("click", planNow);
$("t-add").addEventListener("click", () => addTargetRow());
$("r-run").addEventListener("click", startRun);
$("r-cancel").addEventListener("click", cancelRun);
$("j-queue").addEventListener("click", queueCurrentBrief);
$("d-start").addEventListener("click", daemonStart);
$("d-stop").addEventListener("click", daemonStop);
$("s-save").addEventListener("click", () => saveSettings().catch((e) => toast(e.message, true)));
$("s-test").addEventListener("click", testLLM);
$("s-save-interval").addEventListener("click", () => saveInterval().catch((e) => toast(e.message, true)));
$("s-doctor").addEventListener("click", runDoctor);

boot();
