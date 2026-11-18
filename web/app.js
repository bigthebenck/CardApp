// Phone front end: the shared plumbing (worker, sheets, steppers, menus) and
// the Starting Order tool. The Free Tracking tool is in tracker.js. All
// shuffle math runs in Python (worker.js -> webbridge.py -> shuffle_solver);
// these files only draw the state they get back and send the user's edits.
"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const esc = (s) => String(s).replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const SUITS = "CHSD";
const RANKS = "A23456789TJQK";
const SUIT_SYM = { C: "♣", H: "♥", S: "♠", D: "♦" };
const INDIFFERENT = [["X", "Any card"], ["B", "Any high"], ["L", "Any low"]];
const BADGES = {
  ok: ["PASS", "success"], empty_sequence: ["PASS", "success"], failed: ["FAIL", "danger"],
  invalid_deck: ["WAITING", "warning"], invalid_steps: ["WAITING", "warning"],
};
const ACCENTS = { aurora: "#7c5cff", ocean: "#0a84ff", sunset: "#f2622e", forest: "#24a356",
                  graphite: "#5b6b82" };
const DEFAULT_X = { overhand_run: 5, cut: 26, packet_run: 5, partial: 13 };
const PARTIAL_DIRS = [["top", "top"], ["top", "bottom"], ["bottom", "top"], ["bottom", "bottom"]];
const SETUP_KEY = "shuffle-solver/setup";
const TRACKER_KEY = "shuffle-solver/tracker";
const PREFS_KEY = "shuffle-solver/prefs";
const TOOLS = {
  solver: { title: "Starting Order", views: ["final", "steps", "result"],
            about: "The order to set the deck in, for the order you want after your shuffles." },
  tracker: { title: "Free Tracking", views: ["tdeck", "tsteps", "ttable"],
             about: "Follow a deck through shuffles, piles, cards taken out or added, and more." },
};

let S = null;      // state from webbridge.state()
let M = null;      // webbridge.meta()
let prefs = loadPrefs();

// --- storage ------------------------------------------------------------------------

function loadPrefs() {
  try { return { lastX: {}, ...JSON.parse(localStorage.getItem(PREFS_KEY) || "{}") }; }
  catch (e) { return { lastX: {} }; }
}
function savePrefs() {
  try { localStorage.setItem(PREFS_KEY, JSON.stringify(prefs)); } catch (e) { /* private mode */ }
}
function store(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* ignore */ }
}
function stored(key) {
  try { return JSON.parse(localStorage.getItem(key) || "null"); } catch (e) { return null; }
}

// --- worker ---------------------------------------------------------------------------

const worker = new Worker("worker.js");
const pending = new Map();
let nextId = 1;

worker.onmessage = (event) => {
  const m = event.data;
  if (m.type === "progress") { $("#loading-text").textContent = m.text; return; }
  if (m.type === "ready") { warmCache(m.resources); return; }
  if (m.type === "failed") { showLoadFailure(m.text); return; }
  const p = pending.get(m.id);
  pending.delete(m.id);
  if (m.error) p.reject(new Error(m.error)); else p.resolve(m.result);
};
worker.onerror = (e) => showLoadFailure(e.message || "the solver could not start");

function api(op, args = {}) {
  return new Promise((resolve, reject) => {
    const id = nextId++;
    pending.set(id, { resolve, reject });
    worker.postMessage({ id, op, args });
  });
}

/** Run an op that changes the setup; draws the new state. Returns the reply. */
async function act(op, args = {}, opts = {}) {
  let reply;
  try {
    reply = await api(op, args);
  } catch (err) {
    toast(err.message);
    return { error: err.message };
  }
  if (reply.state) applyState(reply.state, opts);
  if (reply.tracker) applyTracker(reply.tracker, opts);
  if (reply.error && !opts.quiet) toast(reply.error);
  return reply;
}

function applyState(state, opts = {}) {
  S = state;
  store(SETUP_KEY, S.setup);
  render(opts);
}

function showLoadFailure(text) {
  $("#loading-text").textContent = `Couldn't start the solver: ${text}`;
  $(".spinner").hidden = true;
  if (!$("#retry")) {
    const b = document.createElement("button");
    b.id = "retry"; b.className = "btn btn-primary"; b.textContent = "Try again";
    b.onclick = () => location.reload();
    $("#loading").appendChild(b);
  }
}

function warmCache(urls) {
  if (!urls || !navigator.serviceWorker) return;
  navigator.serviceWorker.ready.then((reg) => reg.active?.postMessage({ type: "warm", urls }));
}

// --- cards ------------------------------------------------------------------------------

function parseCard(text) {
  if (!text) return null;
  const up = text.endsWith("`");
  const core = up ? text.slice(0, -1) : text;
  if ("XBL".includes(core[0])) return { rank: core[0], suit: "", up, ind: true, key: null };
  return { rank: core[0], suit: core[1], up, ind: false, key: core.slice(0, 2) };
}

function cardHTML(text) {
  const c = parseCard(text);
  if (!c) return '<span class="c ind">·</span>';
  const tick = c.up ? "`" : "";
  if (c.ind) return `<span class="c ind">${c.rank}${tick}</span>`;
  const rank = c.rank === "T" ? "10" : c.rank;
  const cls = "HD".includes(c.suit) ? "red" : "blk";
  return `<span class="c ${cls}">${rank}${SUIT_SYM[c.suit]}${tick}</span>`;
}

/** "split 7♠|K♦" with each card coloured by suit. */
function splitHTML(note) {
  if (!note) return "";
  return esc(note).replace(/(10|[A2-9JQK])([♣♥♠♦])/g,
    (_m, r, s) => `<span class="${"♥♦".includes(s) ? "red" : "blk"}">${r}${s}</span>`);
}

// --- rendering --------------------------------------------------------------------------

/** A grid of numbered cards, top first down each column (four columns, like the
    desktop's columns of 13 for a full deck). ``onTap(i, text)`` makes them buttons. */
function renderCards(container, cards, { highlight = null, onTap = null } = {}) {
  container.style.gridTemplateRows = `repeat(${Math.max(1, Math.ceil(cards.length / 4))}, auto)`;
  container.innerHTML = cards.map((text, i) => {
    const c = parseCard(text);
    const hl = highlight && c && c.key === highlight ? " hl" : "";
    return `<button class="slot${hl}" data-i="${i}" aria-label="Position ${i + 1}: ${esc(text)}">`
      + `<span class="n">${i + 1}</span>${cardHTML(text)}</button>`;
  }).join("");
  if (onTap) $$(".slot", container).forEach((b, i) => b.onclick = () => onTap(i, cards[i]));
}

function setBadge(el, text, tone) {
  el.textContent = text;
  el.className = el.className.replace(/\b(success|danger|warning)\b/g, "").trim() + " " + tone;
  el.hidden = false;
}

function setCount(el, n) {
  el.textContent = n;
  el.hidden = n === 0;
}

/** The title bar's badge, for whichever tool is showing. */
function updateBadge() {
  const badge = prefs.tool === "tracker" ? trackerBadge() : (S && BADGES[S.result.status]);
  if (badge) setBadge($("#badge"), ...badge);
  else $("#badge").hidden = true;
}

function render(opts = {}) {
  updateBadge();
  setBadge($("#result-badge"), ...BADGES[S.result.status]);
  setCount($("#step-count"), S.steps.length);
  renderFinal(opts.fromText);
  renderSteps();
  renderResult();
  if (sheet.live) sheet.draw();
}

// Final deck -----------------------------------------------------------------------------

let textSlots = null;   // the slots the shorthand box last described
let textTimer = null;

function buildFinalGrid() {
  const grid = $("#final-grid");
  for (let i = 0; i < 52; i++) {
    const b = document.createElement("button");
    b.className = "slot";
    b.dataset.i = i;
    b.onclick = () => openPicker(i);
    grid.appendChild(b);
  }
}

function renderFinal(fromText) {
  // Rewrite the shorthand only when the cards changed from somewhere else, so
  // the user's own formatting survives (the desktop app does the same).
  const box = $("#shorthand");
  const key = JSON.stringify(S.slots);
  if (fromText) textSlots = key;
  else if (!S.inputError && key !== textSlots && textTimer === null) {
    box.value = S.text;
    textSlots = key;
  }
  const err = $("#text-error");
  err.hidden = !S.inputError;
  err.textContent = S.inputError ? `⚠ ${S.inputError}` : "";

  const dups = new Set(S.dups);
  $$("#final-grid .slot").forEach((b, i) => {
    const text = S.slots[i];
    b.innerHTML = `<span class="n">${i + 1}</span>${cardHTML(text)}`;
    b.classList.toggle("empty-slot", !text);
    b.classList.toggle("dup", dups.has(i));
    b.classList.toggle("cur", sheet.kind === "picker" && pick.index === i);
    b.setAttribute("aria-label", `Card ${i + 1}: ${text || "empty"}`);
  });

  const status = $("#deck-status");
  status.textContent = (S.deckOk ? "✓ " : "") + S.deckStatus;
  status.className = "status " + (S.deckOk ? "ok" : "bad");
}

function onShorthandInput() {
  clearTimeout(textTimer);
  textTimer = setTimeout(flushShorthand, 350);
}

function flushShorthand() {
  if (textTimer === null) return;
  clearTimeout(textTimer);
  textTimer = null;
  act("set_text", { text: $("#shorthand").value }, { fromText: true, quiet: true });
}

/** Wire a row of insert keys to text box ``box``; ``onInput()`` runs after each key. */
function setupKeybar(bar, box, onInput) {
  $$("button", bar).forEach((b) => {
    // Keep the text box focused (and the keyboard up) while tapping a key.
    b.addEventListener("pointerdown", (e) => e.preventDefault());
    b.addEventListener("click", () => {
      if (document.activeElement !== box) {
        box.focus();
        box.setSelectionRange(box.value.length, box.value.length);
      }
      const ins = b.dataset.ins;
      let { selectionStart: s, selectionEnd: e } = box;
      if (ins === "⌫") {
        if (s === e && s > 0) s -= 1;
        box.setRangeText("", s, e, "end");
      } else {
        box.setRangeText(ins, s, e, "end");
      }
      onInput();
    });
  });
}

/** A row of the usual shorthand keys, as HTML (for text boxes made on the fly). */
function keybarHTML(keys = ["`", "-", ",", "(", ")", "10", "X", "⌫"]) {
  return `<div class="keybar" style="grid-template-columns: repeat(${keys.length}, 1fr)">${keys.map((k) =>
    `<button type="button" data-ins="${esc(k === "," ? ", " : k)}">${esc(k)}</button>`).join("")}</div>`;
}

// Card picker sheet ------------------------------------------------------------------------

const pick = { index: 0, suit: "S" };

function openPicker(index) {
  flushShorthand();
  pick.index = index;
  const c = parseCard(S.slots[index]);
  if (c && !c.ind) pick.suit = c.suit;
  openSheet("picker", drawPicker, { live: true });
  renderFinal();
}

function drawPicker(body) {
  const i = pick.index;
  const current = parseCard(S.slots[i]);
  const used = new Set(S.slots.filter((t, k) => t && k !== i).map((t) => parseCard(t).key));
  const up = current ? current.up : false;

  body.innerHTML = `
    <h3>
      <button class="icon-btn" id="pk-prev" aria-label="Previous card" ${i === 0 ? "disabled" : ""}>
        <svg viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7"/></svg></button>
      <span>Card ${i + 1}</span>
      <button class="icon-btn" id="pk-next" aria-label="Next card" ${i === 51 ? "disabled" : ""}>
        <svg viewBox="0 0 24 24"><path d="M9 5l7 7-7 7"/></svg></button>
      <span class="spacer"></span>
      <button class="btn btn-quiet" id="pk-done">Done</button>
    </h3>
    <div class="seg suit-seg">${[...SUITS].map((s) => `
      <button data-suit="${s}" class="${s === pick.suit ? "on" : ""} ${"HD".includes(s) ? "red" : "blk"}"
              aria-label="${s}">${SUIT_SYM[s]}</button>`).join("")}</div>
    <div class="section picker-ranks">${[...RANKS].map((r) => {
      const key = r + pick.suit;
      const on = current && current.key === key;
      return `<button data-rank="${r}" class="${on ? "on" : ("HD".includes(pick.suit) ? "red" : "blk")}"
                ${used.has(key) ? "disabled" : ""}>${r === "T" ? "10" : r}</button>`;
    }).join("")}</div>
    <div class="section picker-extra">${INDIFFERENT.map(([r, name]) => `
      <button data-ind="${r}" class="${current && current.rank === r ? "on" : ""}">${r} · ${name}</button>`).join("")}</div>
    <div class="section row">
      <label class="check"><input type="checkbox" id="pk-up" ${up ? "checked" : ""}> Face up</label>
      <span class="spacer" style="flex:1"></span>
      <button class="btn btn-danger" id="pk-clear" ${current ? "" : "disabled"}>Empty slot</button>
    </div>
    <p class="hint">Picking a card moves on to the next slot. Cards already used are greyed out.</p>`;

  const go = (k) => { pick.index = Math.max(0, Math.min(51, k)); renderFinal(); sheet.draw(); };
  $("#pk-prev", body).onclick = () => go(i - 1);
  $("#pk-next", body).onclick = () => go(i + 1);
  $("#pk-done", body).onclick = closeSheet;
  $$("[data-suit]", body).forEach((b) => b.onclick = () => { pick.suit = b.dataset.suit; sheet.draw(); });
  const choose = async (text) => {
    const flag = $("#pk-up", body).checked ? "`" : "";
    const r = await act("set_slot", { index: i, card: text + flag });
    if (!r.error && i < 51) go(i + 1);
  };
  $$("[data-rank]", body).forEach((b) => b.onclick = () => choose(b.dataset.rank + pick.suit));
  $$("[data-ind]", body).forEach((b) => b.onclick = () => choose(b.dataset.ind));
  $("#pk-up", body).onchange = (e) => {
    if (current) {
      const base = S.slots[i].replace("`", "");
      act("set_slot", { index: i, card: base + (e.target.checked ? "`" : "") });
    }
  };
  $("#pk-clear", body).onclick = () => act("set_slot", { index: i, card: null });
}

// Shuffles -----------------------------------------------------------------------------------

let openStep = null;  // index of the step being edited
let stepsKey = "";

const kindInfo = (kind) => M.kinds.find((k) => k.kind === kind);
const insertIndex = () => (openStep === null ? S.steps.length : openStep + 1);

function renderSteps() {
  if (openStep !== null && openStep >= S.steps.length) openStep = null;
  const list = $("#steps");
  const key = JSON.stringify([openStep, S.steps.map((s) => s.kind)]);
  if (key !== stepsKey) {
    stepsKey = key;
    list.innerHTML = "";
    S.steps.forEach((_s, i) => list.appendChild(stepItem(i)));
  }
  S.steps.forEach((s, i) => updateStepItem(list.children[i], s));
  $("#steps-empty").hidden = S.steps.length > 0;
  $("#clear-steps").hidden = S.steps.length === 0;
  $("#insert-hint").textContent = openStep === null ? "adds to the end"
    : `adds after step ${openStep + 1}`;
  const err = $("#steps-error");
  const bad = S.result.status === "invalid_steps";
  err.hidden = !bad;
  err.textContent = bad ? S.result.messages.join(" ") : "";
}

function stepItem(i) {
  const li = document.createElement("li");
  li.className = "step" + (i === openStep ? " open" : "");
  li.innerHTML = `
    <button class="step-main" aria-expanded="${i === openStep}">
      <span class="step-num">${i + 1}</span>
      <span class="step-text"><div class="step-label"></div><div class="step-split"></div></span>
    </button>`;
  $(".step-main", li).onclick = () => {
    openStep = openStep === i ? null : i;
    renderSteps();
  };
  if (i === openStep) li.appendChild(stepEditor(li, i));
  return li;
}

function updateStepItem(li, s) {
  $(".step-label", li).textContent = s.label;
  $(".step-split", li).innerHTML = splitHTML(s.split);
  if (li._x) li._x.set(s.x);
  if (li._y) { li._y.setRange(1, s.x); li._y.set(s.y ?? s.x); }
}

function stepEditor(li, i) {
  const s = S.steps[i];
  const info = kindInfo(s.kind);
  const box = document.createElement("div");
  box.className = "step-edit";
  if (info.hasX) {
    li._x = stepper({ label: "X", min: info.min, max: info.max, value: s.x,
                      onChange: (x) => act("set_x", { index: i, x }) });
    box.appendChild(li._x.el);
  }
  if (info.hasY) {
    li._y = stepper({ label: "Y", min: 1, max: s.x, value: s.y ?? s.x, all: true,
                      onChange: (y) => act("set_y", { index: i, y: y === S.steps[i].x ? null : y }) });
    box.appendChild(li._y.el);
  }
  const actions = document.createElement("div");
  actions.className = "step-actions";
  actions.innerHTML = `
    <button class="btn" data-a="up" ${i === 0 ? "disabled" : ""}>↑ Up</button>
    <button class="btn" data-a="down" ${i === S.steps.length - 1 ? "disabled" : ""}>↓ Down</button>
    <button class="btn" data-a="dup">Copy</button>
    <button class="btn btn-danger" data-a="del">Delete</button>`;
  const run = {
    up: () => { openStep = i - 1; act("move_step", { index: i, delta: -1 }); },
    down: () => { openStep = i + 1; act("move_step", { index: i, delta: 1 }); },
    dup: () => { openStep = i + 1; act("duplicate_step", { index: i }); },
    del: () => { openStep = null; act("remove_step", { index: i }); },
  };
  $$("[data-a]", actions).forEach((b) => b.onclick = run[b.dataset.a]);
  box.appendChild(actions);
  return box;
}

/** A number control: − / + buttons, a box to type in, and a slider for big jumps.
    With ``all``, the top value means "all of them" (a packet run's Y). */
function stepper({ label, min, max, value, onChange, all = false }) {
  const el = document.createElement("div");
  el.className = "stepper";
  el.innerHTML = `
    <div class="stepper-row">
      <span class="lbl">${esc(label)}</span>
      <button class="btn" data-d="-1" aria-label="${esc(label)} down">−</button>
      <input type="number" inputmode="numeric" pattern="[0-9]*" aria-label="${esc(label)}">
      <button class="btn" data-d="1" aria-label="${esc(label)} up">+</button>
      <span class="range-note"></span>
    </div>
    <input type="range" aria-label="${esc(label)} slider">`;
  const num = $("input[type=number]", el);
  const rng = $("input[type=range]", el);
  const note = $(".range-note", el);
  let cur = value, lo = min, hi = max;

  function show() {
    rng.min = lo; rng.max = hi;
    if (document.activeElement !== num) num.value = cur;
    if (document.activeElement !== rng) rng.value = cur;
    rng.disabled = lo === hi;
    note.textContent = all && cur === hi ? `${lo}–${hi} · all` : `${lo}–${hi}`;
  }
  function commit(v) {
    if (!Number.isFinite(v)) { show(); return; }
    v = Math.max(lo, Math.min(hi, Math.round(v)));
    const changed = v !== cur;
    cur = v;
    show();
    if (changed) onChange(v);
  }
  $$("[data-d]", el).forEach((b) => b.onclick = () => commit(cur + Number(b.dataset.d)));
  num.addEventListener("change", () => { commit(Number(num.value)); num.value = cur; });
  num.addEventListener("keydown", (e) => { if (e.key === "Enter") num.blur(); });
  rng.addEventListener("input", () => commit(Number(rng.value)));
  show();
  return {
    el,
    get: () => cur,
    set(v) { cur = v; show(); },
    setRange(a, b) { lo = a; hi = b; cur = Math.max(lo, Math.min(hi, cur)); show(); },
  };
}

// Add-a-shuffle sheet ------------------------------------------------------------------------

async function addStep(kind, x = null, y = null) {
  const index = insertIndex();
  const r = await act("add_step", { kind, x, y, index }, { quiet: true });
  if (r.error) return r.error;
  openStep = index;
  renderSteps();
  $("#steps").children[index]?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  return null;
}

/** The Starting Order's way of adding a shuffle (see ``openAdd``). */
function solverAddContext() {
  return {
    bounds: null,
    where: S.steps.length && openStep !== null ? ` after step ${openStep + 1}` : "",
    note: "",
    add: addStep,
    added: () => toast(`Added step ${openStep + 1}`),
  };
}

/** The sheet for a shuffle that takes X (and Y). ``ctx.bounds`` overrides each kind's
    X range (a smaller pile); ``ctx.add(kind, x, y)`` adds it and returns an error or null. */
function openAdd(group, ctx = solverAddContext()) {
  const st = { source: prefs.partialSource || "top", dest: prefs.partialDest || "top",
               out: prefs.partialOut ?? true };
  const kindOf = () => (group === "partial"
    ? M.kinds.find((k) => k.source === st.source && k.dest === st.dest && k.out === st.out).kind
    : group);
  openSheet("add", (body) => {
    const kind = kindOf();
    const [min, max] = ctx.bounds?.[kind] ?? [kindInfo(kind).min, kindInfo(kind).max];
    const info = { ...kindInfo(kind), min, max };
    const title = group === "partial" ? "Partial Faro" : info.label;
    const tooSmall = min > max;
    body.innerHTML = `
      <h3>Add ${esc(title)}</h3>
      ${ctx.note ? `<p class="hint">${esc(ctx.note)}</p>` : ""}
      ${group === "partial" ? `
        <div class="section"><span class="field-label">Packet</span>
          <div class="seg wrap" id="ad-dir">${PARTIAL_DIRS.map(([s, d]) => `
            <button data-s="${s}" data-d="${d}" class="${s === st.source && d === st.dest ? "on" : ""}">
              ${s} into ${d}</button>`).join("")}</div></div>
        <div class="section"><div class="seg" id="ad-out">
          <button data-out="1" class="${st.out ? "on" : ""}">Out</button>
          <button data-out="0" class="${st.out ? "" : "on"}">In</button></div></div>` : ""}
      <div class="section" id="ad-x"></div>
      <div class="section" id="ad-y"></div>
      <p class="error" id="ad-err" ${tooSmall ? "" : "hidden"}>${tooSmall
        ? "The pile has too few cards for this shuffle." : ""}</p>
      <div class="actions">
        <button class="btn" id="ad-cancel">Cancel</button>
        <button class="btn btn-primary" id="ad-ok" ${tooSmall ? "disabled" : ""}>Add${esc(ctx.where)}</button>
      </div>`;

    const remembered = prefs.lastX[group] ?? DEFAULT_X[group];
    const clampX = (v) => Math.max(info.min, Math.min(info.max, v));
    let ys = null;
    const xs = stepper({ label: "X", min: info.min, max: Math.max(info.min, info.max),
                         value: clampX(remembered),
                         onChange: (v) => { if (ys) ys.setRange(1, v); } });
    if (!tooSmall) $("#ad-x", body).appendChild(xs.el);
    if (info.hasY && !tooSmall) {
      ys = stepper({ label: "Y", min: 1, max: xs.get(), value: xs.get(), all: true,
                     onChange: () => {} });
      $("#ad-y", body).appendChild(ys.el);
      $("#ad-y", body).insertAdjacentHTML("beforeend",
        '<p class="hint">Y is how many of the X cards you run; the top value runs them all.</p>');
    }

    if (group === "partial") {
      const redraw = () => { prefs.lastX[group] = xs.get(); sheet.draw(); };
      $$("#ad-dir button", body).forEach((b) => b.onclick = () => {
        st.source = b.dataset.s; st.dest = b.dataset.d; redraw();
      });
      $$("#ad-out button", body).forEach((b) => b.onclick = () => {
        st.out = b.dataset.out === "1"; redraw();
      });
    }
    $("#ad-cancel", body).onclick = closeSheet;
    $("#ad-ok", body).onclick = async () => {
      const x = xs.get();
      const y = ys ? ys.get() : null;
      prefs.lastX[group] = x;
      Object.assign(prefs, { partialSource: st.source, partialDest: st.dest, partialOut: st.out });
      savePrefs();
      const error = await ctx.add(kindOf(), x, y === x ? null : y);
      if (error) {
        $("#ad-err", body).textContent = error;
        $("#ad-err", body).hidden = false;
      } else {
        closeSheet();
        ctx.added();
      }
    };
  });
}

// Result -----------------------------------------------------------------------------------

let walkIndex = 0;
let highlight = null;  // card key followed through the steps
let chipsKey = "";

function buildWalkGrid() {
  const grid = $("#walk-grid");
  for (let i = 0; i < 52; i++) {
    const b = document.createElement("button");
    b.className = "slot";
    b.onclick = () => {
      const c = parseCard(S.result.states?.[walkIndex]?.[i]);
      if (!c || c.ind) return;
      highlight = highlight === c.key ? null : c.key;
      renderWalk();
    };
    grid.appendChild(b);
  }
}

function renderResult() {
  const res = S.result;
  $("#result-msg").textContent = res.messages.join(" ");
  const has = !!res.start;
  $("#walk-panel").hidden = !has;
  $("#copy-short").disabled = !(has && res.verified);
  $("#copy-list").disabled = !has;
  $("#share").disabled = !(has && res.verified);
  if (has) renderWalk();
}

function renderWalk() {
  const res = S.result;
  const n = S.steps.length;
  walkIndex = Math.min(walkIndex, n);

  const chips = $("#walk-chips");
  const key = String(n);
  if (key !== chipsKey) {
    chipsKey = key;
    chips.innerHTML = Array.from({ length: n + 1 }, (_v, k) =>
      `<button class="chip" role="tab" data-k="${k}">${k === 0 ? "Start" : "#" + k}</button>`).join("");
    $$(".chip", chips).forEach((b) => b.onclick = () => {
      walkIndex = Number(b.dataset.k);
      renderWalk();
      b.scrollIntoView({ block: "nearest", inline: "center", behavior: "smooth" });
    });
  }
  chips.hidden = n === 0;
  $$(".chip", chips).forEach((b, k) => {
    b.classList.toggle("on", k === walkIndex);
    b.setAttribute("aria-selected", k === walkIndex);
  });

  const last = walkIndex === n;
  $("#walk-title").textContent = walkIndex === 0 ? "Starting order" : `After step ${walkIndex}`;
  $("#walk-hint").textContent = walkIndex === 0 ? "set up the deck like this, top first"
    : last ? "should match your final deck" : "top first";
  const next = S.steps[walkIndex];
  const stepNote = $("#walk-step");
  stepNote.hidden = !next;
  if (next) {
    stepNote.innerHTML = `Next: <b>#${walkIndex + 1} ${esc(next.label)}</b>`
      + (next.split ? `<span class="step-split">${splitHTML(next.split)}</span>` : "");
  }

  const deck = res.states[walkIndex];
  $$("#walk-grid .slot").forEach((b, i) => {
    const text = deck[i];
    const c = parseCard(text);
    b.innerHTML = `<span class="n">${i + 1}</span>${cardHTML(text)}`;
    b.classList.toggle("hl", !!(highlight && c && c.key === highlight));
    b.setAttribute("aria-label", `Position ${i + 1}: ${text}`);
  });
}

async function copyStart(kind) {
  const r = await api("start_text", { kind });
  if (r.error) { toast(r.error); return; }
  await copyText(r.text);
  toast(kind === "shorthand" ? "Shorthand copied" : "List copied");
}

function openShare() {
  openSheet("share", (body) => {
    body.innerHTML = `
      <h3>Share the setup</h3>
      <label class="field-label" for="sh-notes">Notes (optional), added to the end</label>
      <textarea id="sh-notes" rows="3" placeholder="e.g. for the Thursday show"></textarea>
      <p class="hint">Includes the shuffle sequence with where to split, the starting order,
        and its shorthand.</p>
      <div class="actions">
        <button class="btn" id="sh-save">Save .txt</button>
        <button class="btn" id="sh-copy">Copy</button>
        ${navigator.share ? '<button class="btn btn-primary" id="sh-share">Share</button>' : ""}
      </div>`;
    const text = async () => {
      const r = await api("export_text", { notes: $("#sh-notes", body).value.trim() });
      if (r.error) { toast(r.error); return null; }
      return r.text;
    };
    $("#sh-save", body).onclick = async () => {
      const t = await text();
      if (t !== null) { download("starting-order.txt", t, "text/plain"); closeSheet(); }
    };
    $("#sh-copy", body).onclick = async () => {
      const t = await text();
      if (t !== null) { await copyText(t); toast("Copied"); closeSheet(); }
    };
    if (navigator.share) {
      $("#sh-share", body).onclick = async () => {
        const t = await text();
        if (t === null) return;
        try { await navigator.share({ title: "Starting order", text: t }); closeSheet(); }
        catch (e) { /* the user closed the share sheet */ }
      };
    }
  });
}

// Menu --------------------------------------------------------------------------------------

function openMenu() {
  openSheet("menu", (body) => {
    const theme = prefs.theme || "auto";
    const accent = prefs.accent || "aurora";
    body.innerHTML = `
      <h3>Shuffle Solver</h3>
      <div class="menu-list">
        <button class="btn" id="mn-save">Save ${prefs.tool === "tracker" ? "tracking project" : "setup"} (.json)</button>
        <button class="btn" id="mn-open">Open a file…</button>
      </div>
      <p class="hint">Opens Starting Order setups and Free Tracking projects, from here or from
        the desktop app (File &gt; Open).</p>
      <div class="section"><span class="field-label">Theme</span>
        <div class="seg" id="mn-theme">${["auto", "light", "dark"].map((t) => `
          <button data-t="${t}" class="${t === theme ? "on" : ""}">${t[0].toUpperCase() + t.slice(1)}</button>`).join("")}
        </div></div>
      <div class="section"><span class="field-label">Accent</span>
        <div class="swatches">${Object.entries(ACCENTS).map(([name, color]) => `
          <button class="swatch ${name === accent ? "on" : ""}" data-a="${name}" aria-label="${name}"
                  style="background:${color}"></button>`).join("")}</div></div>
      <p class="about">Version ${esc(M.version)} · the solver runs on your phone, offline once loaded.</p>`;
    $("#mn-save", body).onclick = () => {
      const [name, setup] = prefs.tool === "tracker" ? ["tracking-project.json", T.setup]
        : ["shuffle-setup.json", S.setup];
      download(name, JSON.stringify(setup, null, 2), "application/json");
      closeSheet();
    };
    $("#mn-open", body).onclick = () => $("#file-input").click();
    $$("#mn-theme button", body).forEach((b) => b.onclick = () => {
      prefs.theme = b.dataset.t; savePrefs(); applyTheme(); sheet.draw();
    });
    $$(".swatch", body).forEach((b) => b.onclick = () => {
      prefs.accent = b.dataset.a; savePrefs(); applyTheme(); sheet.draw();
    });
  });
}

function applyTheme() {
  const root = document.documentElement;
  if (prefs.theme && prefs.theme !== "auto") root.dataset.theme = prefs.theme;
  else delete root.dataset.theme;
  if (prefs.accent && prefs.accent !== "aurora") root.dataset.accent = prefs.accent;
  else delete root.dataset.accent;
}

async function openFile(file) {
  let setup;
  try { setup = JSON.parse(await file.text()); }
  catch (e) { toast("That file isn't a setup (.json) file"); return; }
  const tracking = setup && setup.type === "free_tracking";
  const r = await act(tracking ? "t_load" : "load", { setup });
  if (!r.error) {
    if (tracking) trackerReset(); else { openStep = null; walkIndex = 0; }
    closeSheet();
    switchTool(tracking ? "tracker" : "solver");
    toast(`Opened ${file.name}`);
  }
}

// --- tools ----------------------------------------------------------------------------------

function openTools() {
  openSheet("tools", (body) => {
    body.innerHTML = `<h3>Tools</h3><div class="menu-list">${Object.entries(TOOLS).map(([key, t]) => `
      <button class="tool-choice ${key === prefs.tool ? "on" : ""}" data-tool="${key}">
        <b>${esc(t.title)}</b><span>${esc(t.about)}</span></button>`).join("")}</div>
      <p class="hint">Each tool keeps its own work. Coming later: X to Y, the trainer and stacking.</p>`;
    $$("[data-tool]", body).forEach((b) => b.onclick = () => {
      closeSheet();
      switchTool(b.dataset.tool);
    });
  });
}

function switchTool(tool) {
  prefs.tool = tool;
  $("#tool-title").textContent = TOOLS[tool].title;
  document.title = `${TOOLS[tool].title} · Shuffle Solver`;
  $$(".tabbar button").forEach((b) => { b.hidden = b.dataset.tool !== tool; });
  const tabs = prefs.tabs || {};
  showView(tabs[tool] || TOOLS[tool].views[0]);
  updateBadge();
}

// --- sheet (bottom drawer) -----------------------------------------------------------------

const sheet = { kind: null, draw: null, live: false };

function openSheet(kind, draw, { live = false } = {}) {
  const wasOpen = sheet.kind !== null;
  Object.assign(sheet, { kind, live, draw: () => draw($("#sheet-body")) });
  sheet.draw();
  $("#sheet").hidden = false;
  $("#scrim").hidden = false;
  // Let the phone's Back button close the sheet.
  if (!wasOpen) history.pushState({ sheet: true }, "");
}

function hideSheet() {
  if (sheet.kind === null) return;
  const was = sheet.kind;
  Object.assign(sheet, { kind: null, draw: null, live: false });
  $("#sheet").hidden = true;
  $("#scrim").hidden = true;
  $("#sheet-body").innerHTML = "";
  if (was === "picker") renderFinal();
}

function closeSheet() {
  if (sheet.kind === null) return;
  if (history.state && history.state.sheet) history.back();  // popstate hides it
  else hideSheet();
}

// --- helpers --------------------------------------------------------------------------------

let toastTimer = null;
function toast(text) {
  const t = $("#toast");
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 1800);
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch (e) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
}

function download(name, text, type) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

function showView(name) {
  flushShorthand();
  flushTrackerText();
  $$(".view").forEach((v) => { v.hidden = v.dataset.view !== name; });
  $$(".tabbar button").forEach((b) => b.classList.toggle("active", b.dataset.go === name));
  const tool = Object.keys(TOOLS).find((t) => TOOLS[t].views.includes(name));
  prefs.tabs = { ...prefs.tabs, [tool]: name };
  savePrefs();
  window.scrollTo(0, 0);
}

// --- start up ---------------------------------------------------------------------------------

function wire() {
  buildFinalGrid();
  buildWalkGrid();
  const box = $("#shorthand");
  setupKeybar($("#keybar"), box, onShorthandInput);
  box.addEventListener("input", onShorthandInput);
  box.addEventListener("blur", flushShorthand);

  const preset = $("#preset");
  preset.onchange = () => {
    if (preset.value) act("preset", { name: preset.value });
    preset.value = "";
  };
  $("#clear-final").onclick = () => {
    if (S.slots.some(Boolean) && !confirm("Clear all 52 cards of the final deck?")) return;
    act("clear_final");
  };

  $$("[data-add]").forEach((b) => b.onclick = async () => {
    const kind = b.dataset.add;
    if (kind === "out_faro" || kind === "in_faro") {
      const error = await addStep(kind);
      toast(error || `Added step ${openStep + 1}`);
    } else {
      openAdd(kind);
    }
  });
  $("#clear-steps").onclick = () => {
    if (confirm(`Remove all ${S.steps.length} shuffles?`)) { openStep = null; act("clear_steps"); }
  };

  $("#copy-short").onclick = () => copyStart("shorthand");
  $("#copy-list").onclick = () => copyStart("list");
  $("#share").onclick = openShare;

  $$(".tabbar button").forEach((b) => b.onclick = () => showView(b.dataset.go));
  $("#menu-btn").onclick = openMenu;
  $("#tool-btn").onclick = openTools;
  wireTracker();
  $("#scrim").onclick = closeSheet;
  window.addEventListener("popstate", hideSheet);
  $("#file-input").onchange = (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    if (file) openFile(file);
  };
}

/** Load what was saved last time, or start empty if it no longer loads. */
async function restore(loadOp, stateOp, key, saved) {
  let reply = null;
  if (saved) reply = await api(loadOp, { setup: saved });
  if (!reply || reply.error) reply = await api(stateOp);
  return reply[key];
}

async function start() {
  wire();
  switchTool(TOOLS[prefs.tool] ? prefs.tool : "solver");
  if ("serviceWorker" in navigator && window.isSecureContext) {
    navigator.serviceWorker.register("sw.js").catch(() => { /* works without offline */ });
  }
  try {
    M = await api("meta");
    for (const sel of [$("#preset"), $("#t-preset")]) {
      for (const name of M.presets) sel.add(new Option(name, name));
    }
    applyState(await restore("load", "state", "state", stored(SETUP_KEY)));
    applyTracker(await restore("t_load", "t_state", "tracker", stored(TRACKER_KEY)));
    $("#loading").hidden = true;
  } catch (err) {
    showLoadFailure(err.message);
  }
}
// start() runs from index.html once tracker.js has loaded too.
