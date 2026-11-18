// The Free Tracking tool: a deck entered by hand, followed pile by pile through
// shuffles, card and packet moves, and rearrangements. Like the desktop tab it
// solves nothing; Python (webbridge.py -> TrackerModel) pushes the cards forward
// and this file draws the tables it gets back. Shared helpers are in app.js.
"use strict";

// The colours a group can have (the desktop's theme.GROUP_COLORS).
const GROUP_COLORS = { Red: "#d9534f", Orange: "#f0883e", Yellow: "#e3b505", Green: "#4caf50",
                       Blue: "#3b82f6", Purple: "#9b59b6", Gray: "#8a8a8a" };
const TAKE_MODES = [["pile", "As a new pile"], ["each", "A pile each"], ["discard", "Discard"]];
const OP_TITLES = {
  take_out: "Take out cards", add_cards: "Add cards", name_cards: "Name X cards",
  split: "Split a pile", place: "Put a pile", gather: "Gather piles", rearrange: "Rearrange",
};
const CARD_KEYS = ["`", "-", "10", "X", "⌫"];

let T = null;          // state from webbridge.tracker_state()
let tOpen = null;      // index of the step being edited
let tStepsKey = "";
let tTextKey = null;   // the deck the shorthand box last described
let tTextTimer = null;
let tWalk = 0;         // which table the Table view shows (0 = the start)
let tHighlight = null; // card key followed through the tables
let tChipsKey = "";

function applyTracker(state, opts = {}) {
  T = state;
  store(TRACKER_KEY, T.setup);
  renderTracker(opts);
}

function trackerReset() {
  tOpen = null;
  tWalk = 0;
  tHighlight = null;
}

function trackerBadge() {
  if (!T) return null;
  if (!T.tables) return ["WAITING", "warning"];
  if (T.problem) return [`STEP ${T.problem[0] + 1} ✕`, "danger"];
  return ["OK", "success"];
}

function renderTracker(opts = {}) {
  updateBadge();
  setCount($("#t-step-count"), T.steps.length);
  renderTDeck(opts.fromText);
  renderTSteps();
  renderTTable();
  if (sheet.live) sheet.draw();
}

// --- deck -------------------------------------------------------------------------------------

function renderTDeck(fromText) {
  // As in Starting Order: rewrite the box only when the deck changed from elsewhere.
  const box = $("#t-shorthand");
  if (fromText) tTextKey = T.text;
  else if (!T.error && T.text !== tTextKey && tTextTimer === null) {
    box.value = T.text;
    tTextKey = T.text;
  }
  const err = $("#t-text-error");
  err.hidden = !T.error;
  err.textContent = T.error ? `⚠ ${T.error}` : "";
  const status = $("#t-deck-status");
  status.textContent = (T.deckOk ? "✓ " : "") + T.deckStatus;
  status.className = "status " + (T.deckOk ? "ok" : "bad");

  const start = T.tables?.[0]?.[0];
  $("#t-deck-panel").hidden = !start;
  if (start) {
    $("#t-deck-count").textContent = `${start.cards.length} card${start.cards.length !== 1 ? "s" : ""}, top first`;
    renderCards($("#t-deck-grid"), start.cards);
  }
}

function onTText() {
  clearTimeout(tTextTimer);
  tTextTimer = setTimeout(flushTrackerText, 350);
}

function flushTrackerText() {
  if (tTextTimer === null) return;
  clearTimeout(tTextTimer);
  tTextTimer = null;
  act("t_set_text", { text: $("#t-shorthand").value }, { fromText: true, quiet: true });
}

// --- steps ------------------------------------------------------------------------------------

const tInsert = () => (tOpen === null ? T.steps.length : tOpen + 1);
const tPiles = (index = tInsert()) => T.pilesAt[index] || [];
const groupOf = (i) => T.groups.find((g) => g.first <= i && i <= g.last);

/** The pile new shuffles go to at ``index``: the chosen one if it's there, else the first. */
function tTarget(index = tInsert()) {
  const names = tPiles(index).map((p) => p.name);
  return names.includes(T.targetPile) ? T.targetPile : (names[0] ?? "A");
}

const pileLabel = (p) => `${esc(p.name)}<small> · ${p.size ?? "?"}</small>`;

function renderTSteps() {
  if (tOpen !== null && tOpen >= T.steps.length) tOpen = null;
  const piles = tPiles();
  const target = tTarget();
  $("#t-pile-pick").hidden = piles.length <= 1;
  $("#t-pile-seg").innerHTML = piles.map((p) =>
    `<button data-pile="${esc(p.name)}" class="${p.name === target ? "on" : ""}">${pileLabel(p)}</button>`).join("");
  $$("#t-pile-seg button").forEach((b) => b.onclick = () => act("t_set_pile", { name: b.dataset.pile }));
  $("#t-insert-hint").textContent = tOpen === null ? "adds to the end" : `adds after step ${tOpen + 1}`;

  const list = $("#t-steps");
  const key = JSON.stringify([tOpen, T.steps.map((s) => s.kind), T.groups]);
  if (key !== tStepsKey) {
    tStepsKey = key;
    list.innerHTML = "";
    T.steps.forEach((_s, i) => {
      const g = T.groups.find((grp) => grp.first === i);
      if (g) list.appendChild(groupHead(g));
      list.appendChild(tStepItem(i));
    });
  }
  $$(".step[data-i]", list).forEach((li) => updateTStep(li, T.steps[Number(li.dataset.i)]));
  $("#t-steps-empty").hidden = T.steps.length > 0;
  $("#t-clear-steps").hidden = T.steps.length === 0;
}

function groupHead(g) {
  const li = document.createElement("li");
  li.className = "group-head";
  li.style.setProperty("--g", GROUP_COLORS[g.color] || g.color || "#8a8a8a");
  const span = g.first === g.last ? `#${g.first + 1}` : `#${g.first + 1}–#${g.last + 1}`;
  li.innerHTML = `<button><span class="g-title"></span><span class="hint">${span}</span>
    <svg viewBox="0 0 24 24"><path d="M9 5l7 7-7 7"/></svg></button>`;
  $(".g-title", li).textContent = g.title;
  $("button", li).onclick = () => openGroup(g.id);
  return li;
}

function tStepItem(i) {
  const li = document.createElement("li");
  li.className = "step" + (i === tOpen ? " open" : "");
  li.dataset.i = i;
  const g = groupOf(i);
  if (g) {
    li.classList.add("in-group");
    li.style.setProperty("--g", GROUP_COLORS[g.color] || "#8a8a8a");
  }
  li.innerHTML = `
    <button class="step-main" aria-expanded="${i === tOpen}">
      <span class="step-num">${i + 1}</span>
      <span class="step-text"><div class="step-label"></div><div class="step-split"></div>
        <div class="step-problem"></div></span>
    </button>`;
  $(".step-main", li).onclick = () => {
    tOpen = tOpen === i ? null : i;
    renderTSteps();
  };
  if (i === tOpen) li.appendChild(tStepEditor(li, i));
  return li;
}

function updateTStep(li, s) {
  $(".step-label", li).textContent = s.label;
  $(".step-split", li).innerHTML = splitHTML(s.split);
  $(".step-problem", li).textContent = s.problem ? `⚠ ${s.problem}` : "";
  li.classList.toggle("bad", !!s.problem);
  if (li._x) { li._x.setRange(s.min, Math.max(s.min, s.max)); li._x.set(s.form.x); }
  if (li._y) { li._y.setRange(1, s.form.x); li._y.set(s.form.y ?? s.form.x); }
}

function tStepEditor(li, i) {
  const s = T.steps[i];
  const box = document.createElement("div");
  box.className = "step-edit";
  if (s.shuffle && s.min !== undefined) {
    li._x = stepper({ label: "X", min: s.min, max: Math.max(s.min, s.max), value: s.form.x,
                      onChange: (x) => act("t_set_x", { index: i, x }) });
    box.appendChild(li._x.el);
    if (s.kind === "packet_run") {
      li._y = stepper({ label: "Y", min: 1, max: s.form.x, value: s.form.y ?? s.form.x, all: true,
                        onChange: (y) => act("t_set_y", { index: i, y: y === T.steps[i].form.x ? null : y }) });
      box.appendChild(li._y.el);
    }
  } else if (!s.shuffle) {
    const edit = document.createElement("button");
    edit.className = "btn";
    edit.textContent = "Edit…";
    edit.onclick = () => openTOp(s.kind, i);
    box.appendChild(edit);
  }
  const g = groupOf(i);
  const actions = document.createElement("div");
  actions.className = "step-actions";
  actions.innerHTML = `
    <button class="btn" data-a="up" ${i === 0 ? "disabled" : ""}>↑ Up</button>
    <button class="btn" data-a="down" ${i === T.steps.length - 1 ? "disabled" : ""}>↓ Down</button>
    <button class="btn" data-a="dup">Copy</button>
    <button class="btn btn-danger" data-a="del">Delete</button>
    <button class="btn wide" data-a="group">${g ? "Edit group…" : "Group…"}</button>
    <button class="btn wide" data-a="table">See the table</button>`;
  const run = {
    up: () => { tOpen = i - 1; act("t_move", { index: i, delta: -1 }); },
    down: () => { tOpen = i + 1; act("t_move", { index: i, delta: 1 }); },
    dup: () => { tOpen = i + 1; act("t_duplicate", { first: i, last: i }); },
    del: () => { tOpen = null; act("t_remove", { index: i }); },
    group: () => (g ? openGroup(g.id) : openNewGroup(i)),
    table: () => {
      tWalk = Math.min(i + 1, (T.tables?.length ?? 1) - 1);
      showView("ttable");
      renderTTable();
    },
  };
  $$("[data-a]", actions).forEach((b) => b.onclick = run[b.dataset.a]);
  box.appendChild(actions);
  return box;
}

async function tAdd(form) {
  const index = tInsert();
  const r = await act("t_add", { step: form, index }, { quiet: true });
  if (r.error) return r.error;
  tOpen = index;
  renderTSteps();
  $(`#t-steps .step[data-i="${index}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  return null;
}

async function tAddShuffle(kind) {
  flushTrackerText();
  const pile = tTarget();
  if (kind === "out_faro" || kind === "in_faro") {
    const error = await tAdd({ kind, pile });
    toast(error || `Added step ${tOpen + 1}`);
    return;
  }
  const r = await api("t_bounds", { index: tInsert(), pile });
  openAdd(kind, {
    bounds: r.bounds,
    where: tOpen !== null ? ` after step ${tOpen + 1}` : "",
    note: `To pile ${pile}` + (r.size !== null ? `, which has ${r.size} card${r.size !== 1 ? "s" : ""}.` : "."),
    add: (k, x, y) => tAdd({ kind: k, x, y, pile }),
    added: () => toast(`Added step ${tOpen + 1}`),
  });
}

// --- card and packet steps ---------------------------------------------------------------------

function tDefaults(kind, index) {
  const names = tPiles(index).map((p) => p.name);
  const pile = tTarget(index);
  return {
    take_out: { kind, cards: "", mode: "pile" },
    add_cards: { kind, cards: "", pile, position: 1 },
    name_cards: { kind, cards: "", pile, position: 1 },
    split: { kind, pile, sizes: "" },
    place: { kind, pile: names[names.length - 1], onto: names[0], top: true },
    gather: { kind, names: [] },
    rearrange: { kind, title: "", text: "" },
  }[kind];
}

/** The sheet for a step that isn't a shuffle: a new one, or step ``edit`` changed. */
async function openTOp(kind, edit = null) {
  flushTrackerText();
  const index = edit ?? tInsert();
  const piles = tPiles(index);
  const names = piles.map((p) => p.name);
  const sizeOf = (name) => piles.find((p) => p.name === name)?.size ?? null;
  const f = edit !== null ? { ...T.steps[edit].form } : tDefaults(kind, index);
  if (kind === "rearrange" && edit === null) {
    f.text = (await api("t_table_text", { index })).text;
  }
  let touched = edit !== null;
  let checkTimer = null;
  let checkSeq = 0;

  const seg = (id, label, options, value) => `
    <div class="section"><span class="field-label">${label}</span>
      <div class="seg wrap" id="${id}">${options.map(([v, text]) => `
        <button data-v="${esc(v)}" class="${v === value ? "on" : ""}">${text}</button>`).join("")}</div></div>`;
  const pileSeg = (id, label, value, extra = []) =>
    seg(id, label, [...piles.map((p) => [p.name, pileLabel(p)]), ...extra], value);
  const cardsField = (hint) => `
    <div class="section"><label class="field-label" for="op-cards">Cards</label>
      <input id="op-cards" class="text mono" type="text" autocapitalize="characters" autocomplete="off"
             autocorrect="off" spellcheck="false" placeholder="AC AH AS AD" value="${esc(f.cards)}">
      ${keybarHTML(CARD_KEYS)}<p class="hint">${hint}</p></div>`;

  function fields() {
    const tooFew = names.length < 2;
    switch (kind) {
      case "take_out":
        return cardsField("From whatever piles they are in. Spaces or commas between cards.")
          + seg("op-mode", "Put them", TAKE_MODES, f.mode);
      case "add_cards":
        return cardsField("New cards, not already in play. X5 adds five any cards.")
          + pileSeg("op-pile", "Into", f.pile ?? "", [["", "A new pile"]])
          + (f.pile ? '<div class="section" id="op-pos"></div>' : "");
      case "name_cards":
        return cardsField("The X cards from the position down become these cards, in earlier "
                          + "steps too.")
          + pileSeg("op-pile", "In pile", f.pile) + '<div class="section" id="op-pos"></div>';
      case "split": {
        const n = sizeOf(f.pile) ?? 0;
        const quick = [];
        if (n >= 2) quick.push(["Half", String(Math.floor(n / 2))]);
        if (n >= 4) quick.push(["Quarters", Array(3).fill(Math.floor(n / 4)).join(", ")]);
        if (n >= 5) quick.push(["Deal 4 off the top", "1, 1, 1, 1"]);
        return pileSeg("op-pile", "Pile", f.pile)
          + `<div class="section"><label class="field-label" for="op-sizes">Packet sizes, from the top</label>
              <input id="op-sizes" class="text mono" type="text" inputmode="text" autocomplete="off"
                     placeholder="e.g. 26, or 1,1,1,1,12,12,12,12" value="${esc(f.sizes)}">
              <div class="quick">${quick.map(([t, v]) => `<button class="chip" data-sizes="${v}">${t}</button>`).join("")}</div>
              <p class="hint">Cards left over make one more packet.</p></div>`;
      }
      case "place":
        if (tooFew) return '<p class="error">There is only one pile on the table.</p>';
        return pileSeg("op-pile", "Put pile", f.pile)
          + seg("op-top", "", [["1", "On top of"], ["0", "Under"]], f.top ? "1" : "0")
          + pileSeg("op-onto", "Pile", f.onto);
      case "gather":
        if (tooFew) return '<p class="error">There is only one pile on the table.</p>';
        return `<div class="section"><span class="field-label">Tap the piles in order, the first on top</span>
            <div class="seg wrap" id="op-names">${piles.map((p) => {
              const at = f.names.indexOf(p.name);
              return `<button data-v="${esc(p.name)}" class="${at >= 0 ? "on" : ""}">${at >= 0 ? `${at + 1}. ` : ""}${pileLabel(p)}</button>`;
            }).join("")}</div>
            <p class="hint">${f.names.length ? `Order: ${f.names.join(", ")} (pile ${f.names[0]} on top).`
              : "None picked: gathers every pile, in table order."}</p></div>`;
      case "rearrange":
        return `<div class="section"><label class="field-label" for="op-title">Title</label>
            <input id="op-title" class="text" type="text" placeholder="e.g. Card revelations"
                   value="${esc(f.title)}"></div>
          <div class="section"><label class="field-label" for="op-text">The table after this step, top first</label>
            <textarea id="op-text" rows="7" spellcheck="false" autocapitalize="characters"
                      autocomplete="off" autocorrect="off">${esc(f.text)}</textarea>
            ${keybarHTML(["|", ":", "`", "-", ",", "10", "X", "⌫"])}
            <p class="hint">Separate piles with | and name them with their letter, e.g.
              A: 2-KC, AC | B: 2-KH, AH. It must hold exactly the cards on the table.</p></div>`;
      default:
        return "";
    }
  }

  function check() {
    clearTimeout(checkTimer);
    checkTimer = setTimeout(async () => {
      const seq = ++checkSeq;
      const r = await api("t_check", { step: f, index, edit: edit !== null });
      const status = $("#op-status");
      if (seq !== checkSeq || !status || !touched) return;
      status.textContent = r.ok ? (r.message ? `✓ ${r.message}` : "✓ Ready") : `⚠ ${r.message}`;
      status.className = "status " + (r.ok ? "ok" : "bad");
    }, 250);
  }
  const changed = () => { touched = true; check(); };

  openSheet("top", (body) => {
    const blocked = (kind === "place" || kind === "gather") && names.length < 2;
    body.innerHTML = `
      <h3>${OP_TITLES[kind]}${edit !== null ? ` · step ${edit + 1}` : ""}</h3>
      ${fields()}
      <p class="status" id="op-status"></p>
      <div class="actions">
        <button class="btn" id="op-cancel">Cancel</button>
        <button class="btn btn-primary" id="op-ok" ${blocked ? "disabled" : ""}>${edit !== null ? "Save"
          : `Add${tOpen !== null ? ` after step ${tOpen + 1}` : " step"}`}</button>
      </div>`;

    const bindText = (sel, field) => {
      const el = $(sel, body);
      if (!el) return;
      el.addEventListener("input", () => { f[field] = el.value; changed(); });
      const bar = el.parentElement.querySelector(".keybar");
      if (bar) setupKeybar(bar, el, () => { f[field] = el.value; changed(); });
    };
    bindText("#op-cards", "cards");
    bindText("#op-sizes", "sizes");
    bindText("#op-title", "title");
    bindText("#op-text", "text");
    const onSeg = (id, apply) => $$(`#${id} button`, body).forEach((b) => b.onclick = () => {
      apply(b.dataset.v);
      touched = true;
      sheet.draw();
    });
    onSeg("op-mode", (v) => { f.mode = v; });
    onSeg("op-pile", (v) => { f.pile = v || null; f.position = 1; });
    onSeg("op-onto", (v) => { f.onto = v; });
    onSeg("op-top", (v) => { f.top = v === "1"; });
    onSeg("op-names", (v) => {
      f.names = f.names.includes(v) ? f.names.filter((n) => n !== v) : [...f.names, v];
    });
    $$("[data-sizes]", body).forEach((b) => b.onclick = () => {
      f.sizes = b.dataset.sizes;
      $("#op-sizes", body).value = f.sizes;
      changed();
    });
    const pos = $("#op-pos", body);
    if (pos) {
      const size = sizeOf(f.pile) ?? 52;
      const max = kind === "add_cards" ? size + 1 : Math.max(1, size);
      const st = stepper({ label: "Position", min: 1, max, value: Math.min(f.position, max),
                           onChange: (v) => { f.position = v; changed(); } });
      pos.appendChild(st.el);
      pos.insertAdjacentHTML("beforeend", '<p class="hint">1 = the top card.</p>');
    }
    $("#op-cancel", body).onclick = closeSheet;
    $("#op-ok", body).onclick = async () => {
      touched = true;
      let error;
      if (edit !== null) {
        const r = await act("t_replace", { index: edit, step: f }, { quiet: true });
        error = r.error;
      } else {
        error = await tAdd(f);
      }
      if (error) {
        const status = $("#op-status");
        status.textContent = `⚠ ${error}`;
        status.className = "status bad";
        return;
      }
      closeSheet();
      toast(edit !== null ? `Saved step ${edit + 1}` : `Added step ${tOpen + 1}`);
    };
    if (touched) check();
  });
}

// --- groups ------------------------------------------------------------------------------------

function colourSwatches(current) {
  return `<div class="swatches wrap">${Object.entries(GROUP_COLORS).map(([name, color]) => `
    <button class="swatch ${name === current ? "on" : ""}" data-c="${name}" aria-label="${name}"
            style="background:${color}"></button>`).join("")}</div>`;
}

function bindSwatches(body, f) {
  $$("[data-c]", body).forEach((b) => b.onclick = () => {
    f.color = b.dataset.c;
    $$("[data-c]", body).forEach((x) => x.classList.toggle("on", x === b));
  });
}

function openNewGroup(i) {
  const n = T.steps.length;
  const f = { first: i, last: i, title: "", color: "Blue" };
  openSheet("group", (body) => {
    body.innerHTML = `
      <h3>Group steps</h3>
      <p class="hint">Title and colour a run of steps, e.g. one trick of a routine.</p>
      <div class="section" id="gp-first"></div>
      <div class="section" id="gp-last"></div>
      <p class="hint" id="gp-range"></p>
      <div class="section"><label class="field-label" for="gp-title">Title</label>
        <input id="gp-title" class="text" type="text" placeholder="e.g. Trick 1"></div>
      <div class="section"><span class="field-label">Colour</span>${colourSwatches(f.color)}</div>
      <p class="error" id="gp-err" hidden></p>
      <div class="actions">
        <button class="btn" id="gp-cancel">Cancel</button>
        <button class="btn btn-primary" id="gp-ok">Group</button>
      </div>`;
    const showRange = () => {
      const labels = T.steps.slice(f.first, f.last + 1).map((s) => s.label);
      $("#gp-range", body).textContent = labels.length > 3
        ? `${labels.slice(0, 2).join(" · ")} … ${labels[labels.length - 1]}` : labels.join(" · ");
    };
    const first = stepper({ label: "From", min: 1, max: n, value: f.first + 1,
                            onChange: (v) => { f.first = v - 1; if (f.last < f.first) { f.last = f.first; last.set(v); } showRange(); } });
    const last = stepper({ label: "To", min: 1, max: n, value: f.last + 1,
                           onChange: (v) => { f.last = v - 1; if (f.first > f.last) { f.first = f.last; first.set(v); } showRange(); } });
    $("#gp-first", body).appendChild(first.el);
    $("#gp-last", body).appendChild(last.el);
    showRange();
    const title = $("#gp-title", body);
    title.value = f.title;
    title.oninput = () => { f.title = title.value; };
    bindSwatches(body, f);
    $("#gp-cancel", body).onclick = closeSheet;
    $("#gp-ok", body).onclick = async () => {
      const r = await act("t_group_add", f, { quiet: true });
      if (r.error) {
        $("#gp-err", body).textContent = r.error;
        $("#gp-err", body).hidden = false;
        return;
      }
      closeSheet();
    };
  });
}

function openGroup(id) {
  const g = T.groups.find((grp) => grp.id === id);
  if (!g) return;
  const f = { id, title: g.title, color: g.color };
  const count = g.last - g.first + 1;
  openSheet("group", (body) => {
    body.innerHTML = `
      <h3>Group · steps ${g.first + 1}–${g.last + 1}</h3>
      <div class="section"><label class="field-label" for="gp-title">Title</label>
        <input id="gp-title" class="text" type="text"></div>
      <div class="section"><span class="field-label">Colour</span>${colourSwatches(f.color)}</div>
      <div class="section step-actions">
        <button class="btn wide" id="gp-copy">Copy group</button>
        <button class="btn wide" id="gp-ungroup">Ungroup</button>
        <button class="btn btn-danger wide" id="gp-delete">Delete its ${count} step${count !== 1 ? "s" : ""}</button>
        <button class="btn wide" id="gp-table">See the table</button>
      </div>
      <div class="actions">
        <button class="btn" id="gp-cancel">Cancel</button>
        <button class="btn btn-primary" id="gp-ok">Save</button>
      </div>`;
    const title = $("#gp-title", body);
    title.value = f.title;
    title.oninput = () => { f.title = title.value; };
    bindSwatches(body, f);
    $("#gp-cancel", body).onclick = closeSheet;
    $("#gp-ok", body).onclick = async () => { await act("t_group_edit", f); closeSheet(); };
    $("#gp-copy", body).onclick = async () => {
      closeSheet();
      const r = await act("t_duplicate", { first: g.first, last: g.last });
      if (!r.error) toast(`Copied to steps ${g.last + 2}–${g.last + 1 + count}`);
    };
    $("#gp-ungroup", body).onclick = async () => { closeSheet(); await act("t_group_remove", { id }); };
    $("#gp-delete", body).onclick = async () => {
      if (!confirm(`Delete steps ${g.first + 1}–${g.last + 1}?`)) return;
      closeSheet();
      tOpen = null;
      await act("t_remove_range", { first: g.first, last: g.last });
    };
    $("#gp-table", body).onclick = () => {
      closeSheet();
      tWalk = Math.min(g.last + 1, (T.tables?.length ?? 1) - 1);
      showView("ttable");
      renderTTable();
    };
  });
}

// --- table -------------------------------------------------------------------------------------

function renderTTable() {
  const tables = T.tables;
  const n = tables ? tables.length - 1 : 0;  // tables after the steps that worked
  tWalk = Math.max(0, Math.min(tWalk, n));

  const chips = $("#t-chips");
  const key = String(tables ? n : -1);
  if (key !== tChipsKey) {
    tChipsKey = key;
    chips.innerHTML = tables ? Array.from({ length: n + 1 }, (_v, k) =>
      `<button class="chip" role="tab" data-k="${k}">${k === 0 ? "Start" : "#" + k}</button>`).join("") : "";
    $$(".chip", chips).forEach((b) => b.onclick = () => {
      tWalk = Number(b.dataset.k);
      renderTTable();
      b.scrollIntoView({ block: "nearest", inline: "center", behavior: "smooth" });
    });
  }
  chips.hidden = !tables || n === 0;
  $$(".chip", chips).forEach((b, k) => {
    b.classList.toggle("on", k === tWalk);
    b.setAttribute("aria-selected", k === tWalk);
  });

  const problem = $("#t-problem");
  const failsNext = T.problem && tWalk === n;
  problem.hidden = !(failsNext || !tables);
  problem.textContent = !tables || failsNext ? T.missing : "";
  $("#t-table-actions").hidden = !tables;
  if (!tables) {
    $("#t-table-title").textContent = "Table";
    $("#t-table-hint").textContent = "";
    $("#t-next").hidden = true;
    $("#t-piles").innerHTML = "";
    return;
  }

  $("#t-table-title").textContent = tWalk === 0 ? "Starting deck" : `After step ${tWalk}`;
  $("#t-table-hint").textContent = tWalk === 0 ? "top first" : T.steps[tWalk - 1].label;
  const next = T.steps[tWalk];
  const nextEl = $("#t-next");
  nextEl.hidden = !next || failsNext;
  if (next && !failsNext) {
    nextEl.innerHTML = `Next: <b>#${tWalk + 1} ${esc(next.label)}</b>`
      + (next.split ? `<span class="step-split">${splitHTML(next.split)}</span>` : "");
  }

  const table = tables[tWalk];
  const host = $("#t-piles");
  if (!table.length) {
    host.innerHTML = '<p class="empty">No cards left on the table.</p>';
  } else {
    host.innerHTML = table.map((p) => `
      <div class="pile">
        <div class="pile-head"><b>Pile ${esc(p.name)}</b>
          <span class="hint">${p.cards.length} card${p.cards.length !== 1 ? "s" : ""}</span></div>
        <div class="deck-grid readonly"></div>
      </div>`).join("");
    $$(".pile .deck-grid", host).forEach((grid, k) => renderCards(grid, table[k].cards, {
      highlight: tHighlight,
      onTap: (_i, text) => {
        const c = parseCard(text);
        if (!c || c.ind) return;
        tHighlight = tHighlight === c.key ? null : c.key;
        renderTTable();
      },
    }));
  }
  $("#t-to-solver").disabled = table.length !== 1;
}

async function copyTable() {
  const r = await api("t_table_text", { index: tWalk });
  if (!r.text) { toast("No cards to copy"); return; }
  await copyText(r.text);
  toast("Shorthand copied");
}

/** Like the desktop's "Open in": this table's one pile becomes Starting Order's final deck. */
async function tableToSolver() {
  const table = T.tables?.[tWalk];
  if (!table || table.length !== 1) {
    toast("The cards are in several piles; gather them into one first");
    return;
  }
  if (S.slots.some(Boolean) && !confirm("Replace Starting Order's final deck with these cards?")) return;
  const { text } = await api("t_table_text", { index: tWalk });
  const r = await act("set_text", { text });
  if (r.error) return;
  switchTool("solver");
  showView("final");
  toast(S.inputError ? "Opened, but it needs fixing" : "Set as Starting Order's final deck");
}

// --- wiring -----------------------------------------------------------------------------------

function wireTracker() {
  const box = $("#t-shorthand");
  setupKeybar($("#t-keybar"), box, onTText);
  box.addEventListener("input", onTText);
  box.addEventListener("blur", flushTrackerText);

  const preset = $("#t-preset");
  preset.onchange = () => {
    if (preset.value) act("t_preset", { name: preset.value });
    preset.value = "";
  };
  $("#t-clear").onclick = () => {
    if (T.count && !confirm("Clear the deck to track?")) return;
    act("t_clear");
  };
  $$("[data-tadd]").forEach((b) => b.onclick = () => tAddShuffle(b.dataset.tadd));
  $$("[data-top]").forEach((b) => b.onclick = () => openTOp(b.dataset.top));
  $("#t-clear-steps").onclick = () => {
    if (!confirm(`Remove all ${T.steps.length} steps (and their groups)?`)) return;
    tOpen = null;
    act("t_clear_steps");
  };
  $("#t-copy").onclick = copyTable;
  $("#t-to-solver").onclick = tableToSolver;
}
