/* ===================================================================
   Weather Alert Platform — guided console
   ---------------------------------------------------------------
   Plain fetch + WebSocket client for the FastAPI backend documented
   in the project README. A couple of request/response field names
   (mainly for /auth/register and /auth/login) aren't verifiable from
   the repo listing alone, so this client is deliberately defensive:
   every request/response is written to the "Developer log" at the
   bottom of the page, and login auto-falls-back between a JSON body
   and an OAuth2-style form body. If a call 422s, open the log, check
   the payload against your actual pydantic schema, and adjust the
   small REQUEST SHAPES section below if needed.
   =================================================================== */

/* ------------------------- REQUEST SHAPES -------------------------
   Edit these if your backend's field names differ. */
const SHAPES = {
  register: (u) => ({ username: u.username, email: u.email, password: u.password }),
  loginJson: (u) => ({ username: u.identifier, email: u.identifier, password: u.password }),
  loginForm: (u) => new URLSearchParams({ username: u.identifier, password: u.password, grant_type: "password" }),
  location: (l) => ({ name: l.name, lat: Number(l.lat), lon: Number(l.lon) }),
  subscribe: (id) => ({ location_id: id, id: id }),
};

/* ------------------------- STATE ------------------------- */
const state = {
  apiBase: localStorage.getItem("wap.apiBase") || "http://localhost:8000",
  access: localStorage.getItem("wap.access") || null,
  refresh: localStorage.getItem("wap.refresh") || null,
  user: JSON.parse(localStorage.getItem("wap.user") || "null"),
  locations: [],       // [{id, name, lat, lon}]
  subscriptions: [],   // [{location_id, name}]
  ws: null,
  logCount: 0,
};

/* ------------------------- DOM SHORTCUTS ------------------------- */
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const el = {
  apiBase: $("#apiBase"),
  btnHealth: $("#btnHealth"),
  healthPill: $("#healthPill"),
  btnSettings: $("#btnSettings"),
  settingsPanel: $("#settingsPanel"),

  sessionDot: $("#sessionDot"),
  sessionLabel: $("#sessionLabel"),
  sessionTokens: $("#sessionTokens"),
  btnLogout: $("#btnLogout"),

  formLogin: $("#formLogin"),
  formRegister: $("#formRegister"),

  formLocation: $("#formLocation"),
  btnListLocations: $("#btnListLocations"),
  tblLocations: $("#tblLocations tbody"),

  btnListSubs: $("#btnListSubs"),
  tblSubs: $("#tblSubs tbody"),

  selWeatherLocation: $("#selWeatherLocation"),
  btnCurrent: $("#btnCurrent"),
  btnHistory: $("#btnHistory"),
  historyLimit: $("#historyLimit"),
  currentReading: $("#currentReading"),
  tblHistory: $("#tblHistory tbody"),

  wsSignal: $("#wsSignal"),
  wsStatusLabel: $("#wsStatusLabel"),
  btnWsConnect: $("#btnWsConnect"),
  btnWsDisconnect: $("#btnWsDisconnect"),
  alertFeed: $("#alertFeed"),

  console: $("#console"),
  consoleToggle: $("#consoleToggle"),
  consoleBody: $("#consoleBody"),
  consoleCount: $("#consoleCount"),
  btnClearConsole: $("#btnClearConsole"),

  toastHost: $("#toastHost"),
};

const LOCKABLE_PANEL_IDS = ["panel-locations", "panel-subs", "panel-weather", "panel-live"];

/* ------------------------- SMALL UTILS ------------------------- */
function toast(msg, kind = "ok") {
  const t = document.createElement("div");
  t.className = `toast ${kind}`;
  t.textContent = msg;
  el.toastHost.appendChild(t);
  setTimeout(() => t.remove(), 4200);
}

function setEmptyHint(tableId, isEmpty) {
  const hint = document.querySelector(`.empty-hint[data-empty-for="${tableId}"]`);
  if (hint) hint.classList.toggle("show", isEmpty);
}

function fmtTime(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString(); } catch { return String(iso); }
}

function pick(obj, keys, fallback = "—") {
  for (const k of keys) {
    if (obj && obj[k] !== undefined && obj[k] !== null) return obj[k];
  }
  return fallback;
}

/* ------------------------- STEP LOCKING ------------------------- */
function updateLocks() {
  const signedIn = !!state.access;
  for (const id of LOCKABLE_PANEL_IDS) {
    const panel = document.getElementById(id);
    if (panel) panel.classList.toggle("locked", !signedIn);
  }
}

/* ------------------------- REQUEST LOG ------------------------- */
function logRequest({ method, url, body, status, ok, response, error }) {
  state.logCount++;
  el.consoleCount.textContent = state.logCount;

  const entry = document.createElement("div");
  entry.className = "log-entry";

  const statusText = error ? "ERR" : status;
  const statusClass = ok ? "ok" : "err";

  entry.innerHTML = `
    <div class="log-line1">
      <span class="log-method">${method}</span>
      <span class="log-url">${url}</span>
      <span class="log-status ${statusClass}">${statusText}</span>
      <span class="log-time">${new Date().toLocaleTimeString()}</span>
    </div>
    ${body ? `<div class="log-body">→ ${escapeHtml(truncate(stringify(body), 500))}</div>` : ""}
    <div class="log-body">← ${escapeHtml(truncate(stringify(error || response), 800))}</div>
  `;
  el.consoleBody.prepend(entry);
}

function stringify(v) {
  if (v === undefined) return "";
  if (typeof v === "string") return v;
  try { return JSON.stringify(v); } catch { return String(v); }
}
function truncate(s, n) { return s.length > n ? s.slice(0, n) + "…" : s; }
function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

el.consoleToggle.addEventListener("click", () => el.console.classList.toggle("open"));
el.btnClearConsole.addEventListener("click", (e) => {
  e.stopPropagation();
  el.consoleBody.innerHTML = "";
  state.logCount = 0;
  el.consoleCount.textContent = "0";
});

el.btnSettings.addEventListener("click", () => {
  const open = el.settingsPanel.classList.toggle("open");
  el.btnSettings.setAttribute("aria-expanded", String(open));
});

/* ------------------------- CORE FETCH WRAPPER ------------------------- */
async function apiFetch(path, { method = "GET", body, auth = true, isForm = false, retry = true } = {}) {
  const url = state.apiBase.replace(/\/$/, "") + path;
  const headers = {};
  if (body && !isForm) headers["Content-Type"] = "application/json";
  if (auth && state.access) headers["Authorization"] = `Bearer ${state.access}`;

  let resp, data, ok;
  try {
    resp = await fetch(url, {
      method,
      headers,
      body: body ? (isForm ? body : JSON.stringify(body)) : undefined,
    });
    ok = resp.ok;
    const text = await resp.text();
    try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  } catch (e) {
    logRequest({ method, url, body, error: e.message, ok: false });
    throw new Error(`Network error reaching ${url} — is the server running and CORS-enabled? (${e.message})`);
  }

  // Auto-refresh once on 401, then retry the original call.
  if (!ok && resp.status === 401 && retry && state.refresh && path !== "/auth/refresh") {
    const refreshed = await tryRefresh();
    if (refreshed) return apiFetch(path, { method, body, auth, isForm, retry: false });
  }

  logRequest({ method, url, body, status: resp.status, ok, response: data });

  if (!ok) {
    const msg = (data && (data.detail || data.message)) || `HTTP ${resp.status}`;
    const err = new Error(typeof msg === "string" ? msg : stringify(msg));
    err.status = resp.status;
    err.data = data;
    throw err;
  }
  return data;
}

/* ======================================================================
   AUTH
   ====================================================================== */

function persistSession() {
  localStorage.setItem("wap.apiBase", state.apiBase);
  if (state.access) localStorage.setItem("wap.access", state.access); else localStorage.removeItem("wap.access");
  if (state.refresh) localStorage.setItem("wap.refresh", state.refresh); else localStorage.removeItem("wap.refresh");
  if (state.user) localStorage.setItem("wap.user", JSON.stringify(state.user)); else localStorage.removeItem("wap.user");
}

function renderSession() {
  const signedIn = !!state.access;
  el.sessionDot.classList.toggle("on", signedIn);
  el.sessionLabel.textContent = signedIn
    ? `Signed in${state.user?.username ? " as " + state.user.username : ""}`
    : "Not signed in";
  el.sessionTokens.textContent = signedIn
    ? `access: ${state.access.slice(0, 24)}…   refresh: ${state.refresh ? state.refresh.slice(0, 16) + "…" : "none"}`
    : "";
  el.btnLogout.disabled = !signedIn;
  el.btnWsConnect.disabled = !signedIn || !!state.ws;
  updateLocks();
}

async function handleRegister(e) {
  e.preventDefault();
  const f = Object.fromEntries(new FormData(e.target).entries());
  try {
    await apiFetch("/auth/register", { method: "POST", body: SHAPES.register(f), auth: false });
    toast("Account created — now sign in.", "ok");
    e.target.reset();
    setTab("login");
  } catch (err) {
    toast(`Register failed: ${err.message}`, "err");
  }
}

async function handleLogin(e) {
  e.preventDefault();
  const f = Object.fromEntries(new FormData(e.target).entries());
  let data;
  try {
    // Attempt 1: JSON body (most custom FastAPI/pydantic login schemas).
    data = await apiFetch("/auth/login", { method: "POST", body: SHAPES.loginJson(f), auth: false });
  } catch (err1) {
    try {
      // Attempt 2: OAuth2PasswordRequestForm-style form body.
      data = await apiFetch("/auth/login", { method: "POST", body: SHAPES.loginForm(f), auth: false, isForm: true });
    } catch (err2) {
      toast(`Login failed: ${err2.message}`, "err");
      return;
    }
  }
  applyLoginResponse(data, f.identifier);
}

function applyLoginResponse(data, identifierGuess) {
  const access = pick(data, ["access_token", "accessToken", "token"], null);
  const refresh = pick(data, ["refresh_token", "refreshToken"], null);
  if (!access) {
    toast("Login response had no access_token — check the developer log for the actual shape.", "err");
    return;
  }
  state.access = access;
  state.refresh = refresh;
  state.user = data.user || { username: identifierGuess };
  persistSession();
  renderSession();
  toast("Signed in.", "ok");
  el.formLogin.reset();
  refreshAllData();
}

async function tryRefresh() {
  if (!state.refresh) return false;
  try {
    const data = await apiFetch("/auth/refresh", {
      method: "POST",
      body: { refresh_token: state.refresh },
      auth: false,
      retry: false,
    });
    const access = pick(data, ["access_token", "accessToken", "token"], null);
    if (!access) return false;
    state.access = access;
    if (data.refresh_token) state.refresh = data.refresh_token;
    persistSession();
    renderSession();
    return true;
  } catch {
    return false;
  }
}

async function handleLogout() {
  try {
    await apiFetch("/auth/logout", {
      method: "POST",
      body: { refresh_token: state.refresh },
    });
  } catch {
    /* best-effort — clear local state regardless */
  }
  wsDisconnect();
  state.access = null;
  state.refresh = null;
  state.user = null;
  persistSession();
  renderSession();
  state.subscriptions = [];
  renderSubs();
  toast("Signed out.", "ok");
}

/* ======================================================================
   LOCATIONS
   ====================================================================== */

async function handleCreateLocation(e) {
  e.preventDefault();
  const f = Object.fromEntries(new FormData(e.target).entries());
  try {
    await apiFetch("/locations", { method: "POST", body: SHAPES.location(f) });
    toast("Location saved.", "ok");
    e.target.reset();
    await loadLocations();
  } catch (err) {
    toast(`Could not add location: ${err.message}`, "err");
  }
}

async function loadLocations() {
  try {
    const data = await apiFetch("/locations", { method: "GET" });
    state.locations = Array.isArray(data) ? data : (data.items || data.locations || []);
    renderLocations();
  } catch (err) {
    toast(`Could not load locations: ${err.message}`, "err");
  }
}

function renderLocations() {
  el.tblLocations.innerHTML = "";
  setEmptyHint("tblLocations", state.locations.length === 0);
  for (const loc of state.locations) {
    const id = pick(loc, ["id", "location_id"]);
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${pick(loc, ["name"])}</td>
      <td>${pick(loc, ["lat", "latitude"])}</td>
      <td>${pick(loc, ["lon", "lng", "longitude"])}</td>
      <td><button class="btn btn-secondary btn-tiny" data-subscribe="${id}">Subscribe</button></td>
    `;
    el.tblLocations.appendChild(tr);
  }
  el.tblLocations.querySelectorAll("[data-subscribe]").forEach((btn) => {
    btn.addEventListener("click", () => subscribeTo(btn.dataset.subscribe));
  });
  renderWeatherLocationSelect();
}

function renderWeatherLocationSelect() {
  const current = el.selWeatherLocation.value;
  el.selWeatherLocation.innerHTML = `<option value="">— choose a location —</option>`;
  for (const loc of state.locations) {
    const id = pick(loc, ["id", "location_id"]);
    const opt = document.createElement("option");
    opt.value = id;
    opt.textContent = `${pick(loc, ["name"])} (#${id})`;
    el.selWeatherLocation.appendChild(opt);
  }
  if ([...el.selWeatherLocation.options].some((o) => o.value === current)) {
    el.selWeatherLocation.value = current;
  }
}

/* ======================================================================
   SUBSCRIPTIONS
   ====================================================================== */

async function subscribeTo(locationId) {
  try {
    await apiFetch("/subscriptions", { method: "POST", body: SHAPES.subscribe(locationId) });
    toast("Subscribed.", "ok");
    await loadSubs();
  } catch (err) {
    toast(`Could not subscribe: ${err.message}`, "err");
  }
}

async function unsubscribeFrom(locationId) {
  try {
    await apiFetch(`/subscriptions/${locationId}`, { method: "DELETE" });
    toast("Unsubscribed.", "ok");
    await loadSubs();
  } catch (err) {
    toast(`Could not unsubscribe: ${err.message}`, "err");
  }
}

async function loadSubs() {
  try {
    const data = await apiFetch("/subscriptions", { method: "GET" });
    state.subscriptions = Array.isArray(data) ? data : (data.items || data.subscriptions || []);
    renderSubs();
  } catch (err) {
    toast(`Could not load subscriptions: ${err.message}`, "err");
  }
}

function renderSubs() {
  el.tblSubs.innerHTML = "";
  setEmptyHint("tblSubs", state.subscriptions.length === 0);
  for (const sub of state.subscriptions) {
    const id = pick(sub, ["location_id", "id"]);
    const loc = state.locations.find((l) => String(pick(l, ["id", "location_id"])) === String(id));
    const name = pick(sub, ["name"], loc ? pick(loc, ["name"]) : `#${id}`);
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${name}</td>
      <td><button class="btn btn-danger btn-tiny" data-unsub="${id}">Unsubscribe</button></td>
    `;
    el.tblSubs.appendChild(tr);
  }
  el.tblSubs.querySelectorAll("[data-unsub]").forEach((btn) => {
    btn.addEventListener("click", () => unsubscribeFrom(btn.dataset.unsub));
  });
}

/* ======================================================================
   WEATHER
   ====================================================================== */

async function handleGetCurrent() {
  const id = el.selWeatherLocation.value;
  if (!id) return toast("Choose a location first.", "err");
  try {
    const data = await apiFetch(`/weather/${id}/current`, { method: "GET" });
    renderCurrent(data);
  } catch (err) {
    toast(`Could not fetch current weather: ${err.message}`, "err");
  }
}

function renderCurrent(data) {
  el.currentReading.classList.remove("empty");
  const temp = pick(data, ["temperature", "temp", "temperature_c"]);
  const wind = pick(data, ["wind_speed", "windSpeed", "wind_kmh"]);
  const precip = pick(data, ["precipitation", "precip", "precipitation_mm"]);
  const code = pick(data, ["weather_code", "code"]);
  const time = pick(data, ["timestamp", "time", "recorded_at"]);
  el.currentReading.innerHTML = `
    <div class="stat"><b>${temp}</b><span>Temp °C</span></div>
    <div class="stat"><b>${wind}</b><span>Wind km/h</span></div>
    <div class="stat"><b>${precip}</b><span>Precip mm</span></div>
    <div class="stat"><b>${code}</b><span>WMO code</span></div>
    <div class="stat"><b>${fmtTime(time)}</b><span>As of</span></div>
  `;
}

async function handleGetHistory() {
  const id = el.selWeatherLocation.value;
  if (!id) return toast("Choose a location first.", "err");
  const limit = el.historyLimit.value || 10;
  try {
    const data = await apiFetch(`/weather/${id}/history?limit=${encodeURIComponent(limit)}`, { method: "GET" });
    const rows = Array.isArray(data) ? data : (data.items || data.readings || []);
    renderHistory(rows);
  } catch (err) {
    toast(`Could not fetch history: ${err.message}`, "err");
  }
}

function renderHistory(rows) {
  el.tblHistory.innerHTML = "";
  setEmptyHint("tblHistory", rows.length === 0);
  for (const r of rows) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${fmtTime(pick(r, ["timestamp", "time", "recorded_at"]))}</td>
      <td>${pick(r, ["temperature", "temp", "temperature_c"])}</td>
      <td>${pick(r, ["wind_speed", "windSpeed", "wind_kmh"])}</td>
      <td>${pick(r, ["precipitation", "precip", "precipitation_mm"])}</td>
      <td>${pick(r, ["weather_code", "code"])}</td>
    `;
    el.tblHistory.appendChild(tr);
  }
}

/* ======================================================================
   WEBSOCKET — LIVE ALERTS
   ====================================================================== */

function wsConnect() {
  if (!state.access) return toast("Sign in first.", "err");
  const wsBase = state.apiBase.replace(/^http/, "ws").replace(/\/$/, "");
  const url = `${wsBase}/ws/alerts?token=${encodeURIComponent(state.access)}`;

  let socket;
  try {
    socket = new WebSocket(url);
  } catch (e) {
    return toast(`Could not open socket: ${e.message}`, "err");
  }
  state.ws = socket;
  setWsUi("connecting");

  socket.onopen = () => {
    setWsUi("live");
    logRequest({ method: "WS", url, ok: true, status: "open", response: "connection opened" });
  };

  socket.onmessage = (evt) => {
    let msg;
    try { msg = JSON.parse(evt.data); } catch { msg = evt.data; }
    logRequest({ method: "WS", url, ok: true, status: "message", response: msg });
    renderIncoming(msg);
  };

  socket.onerror = () => {
    logRequest({ method: "WS", url, ok: false, status: "error", error: "socket error" });
  };

  socket.onclose = (evt) => {
    logRequest({ method: "WS", url, ok: evt.wasClean, status: `closed (${evt.code})`, response: evt.reason || "" });
    state.ws = null;
    setWsUi("closed");
  };
}

function wsDisconnect() {
  if (state.ws) state.ws.close(1000, "client disconnect");
  state.ws = null;
  setWsUi("closed");
}

function setWsUi(status) {
  el.wsSignal.classList.toggle("live", status === "live");
  el.wsStatusLabel.textContent =
    status === "live" ? "connected" : status === "connecting" ? "connecting…" : "disconnected";
  el.btnWsConnect.disabled = status === "live" || status === "connecting" || !state.access;
  el.btnWsDisconnect.disabled = !(status === "live" || status === "connecting");
}

function renderIncoming(msg) {
  const empty = el.alertFeed.querySelector(".empty-hint");
  if (empty) empty.remove();

  const type = (msg && (msg.type || msg.event)) || "";
  const isConnected = String(type).toLowerCase().includes("connect") || (msg && msg.message === "connected");

  const severity = (msg && pick(msg, ["severity", "tier", "level"], "")) || "";
  const tierClass = isConnected
    ? "tier-info"
    : /severe/i.test(severity)
    ? "tier-severe"
    : /warn/i.test(severity)
    ? "tier-warning"
    : /watch/i.test(severity)
    ? "tier-watch"
    : "tier-info";

  const title = isConnected
    ? "Connected"
    : pick(msg, ["title", "message", "category"], "Alert received");

  const detail = isConnected
    ? `Subscribed location_ids: ${stringify(pick(msg, ["location_ids", "locations"], []))}`
    : stringify(msg);

  const card = document.createElement("div");
  card.className = `alert-card ${tierClass}`;
  card.innerHTML = `
    <div class="row1"><span class="badge">${severity || (isConnected ? "info" : "alert")}</span><span>${new Date().toLocaleTimeString()}</span></div>
    <div class="row2">${escapeHtml(String(title))}</div>
    <div class="log-body">${escapeHtml(truncate(detail, 400))}</div>
  `;
  el.alertFeed.prepend(card);
}

/* ======================================================================
   HEALTH CHECK
   ====================================================================== */

async function checkHealth() {
  el.healthPill.className = "pill pill-unknown";
  el.healthPill.textContent = "checking…";
  try {
    await apiFetch("/health", { method: "GET", auth: false });
    el.healthPill.className = "pill pill-ok";
    el.healthPill.textContent = "server online";
  } catch (err) {
    el.healthPill.className = "pill pill-bad";
    el.healthPill.textContent = "server unreachable";
  }
}

/* ======================================================================
   TABS
   ====================================================================== */

function setTab(name) {
  $$(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab-panel").forEach((p) => p.classList.toggle("active", p.dataset.tabPanel === name));
}

/* ======================================================================
   WIRING
   ====================================================================== */

function refreshAllData() {
  loadLocations();
  loadSubs();
}

el.apiBase.value = state.apiBase;
el.apiBase.addEventListener("change", () => {
  state.apiBase = el.apiBase.value.trim() || "http://localhost:8000";
  persistSession();
  checkHealth();
});

el.btnHealth.addEventListener("click", checkHealth);

$$(".tab-btn").forEach((btn) => btn.addEventListener("click", () => setTab(btn.dataset.tab)));

el.formLogin.addEventListener("submit", handleLogin);
el.formRegister.addEventListener("submit", handleRegister);
el.btnLogout.addEventListener("click", handleLogout);

el.formLocation.addEventListener("submit", handleCreateLocation);
el.btnListLocations.addEventListener("click", loadLocations);
el.btnListSubs.addEventListener("click", loadSubs);

el.btnCurrent.addEventListener("click", handleGetCurrent);
el.btnHistory.addEventListener("click", handleGetHistory);

el.btnWsConnect.addEventListener("click", wsConnect);
el.btnWsDisconnect.addEventListener("click", wsDisconnect);

/* ------------------------- INIT ------------------------- */
(function init() {
  renderSession();
  setEmptyHint("tblLocations", true);
  setEmptyHint("tblSubs", true);
  setEmptyHint("tblHistory", true);
  checkHealth();
  if (state.access) refreshAllData();
})();