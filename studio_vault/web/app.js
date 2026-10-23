"use strict";

// BAKKIS STUDIO VAULT v2 — UI. Talks to Python through window.pywebview.api (studio_vault/api.py);
// Python pushes scan progress, drops and toasts through vault.onEvent(event, data).
// All text from data is added with textContent (never innerHTML).

const $ = (sel, root = document) => root.querySelector(sel);
const api = () => window.pywebview.api;

const ui = {
  st: null,               // last api.state()
  view: "studio",
  snapshots: [],
  changeFilter: "all",
  studioChanges: null,
  newmac: { sourceId: "", data: null, filter: "missing", q: "", open: new Set() },
  cmp: { a: "", b: "", data: null, filter: "diff", q: "", open: new Set() },
  inv: { id: "", data: null, tab: "plugins", q: "", fmt: "", kind: "", vendor: "", arch: "", sort: "name", dir: 1 },
  about: null,
};

// ── helpers ──────────────────────────────────────────────────────────────────

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "style") node.style.cssText = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

const svg = (paths, cls = "") => {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 24 24");
  s.setAttribute("aria-hidden", "true");
  if (cls) s.setAttribute("class", cls);
  for (const d of paths) {
    const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
    p.setAttribute("d", d);
    s.append(p);
  }
  return s;
};
const searchIcon = () => svg(["M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z", "M20 20l-3.5-3.5"]);

function toast(text, level = "ok") {
  const t = el("div", { class: `toast ${level}`, role: level === "error" ? "alert" : "status" }, text);
  $("#toasts").append(t);
  setTimeout(() => t.remove(), level === "error" ? 7000 : 4000);
}

async function call(method, ...args) {
  try {
    const res = await api()[method](...args);
    if (res && res.ok === false) toast(res.error, "error");
    return res;
  } catch (e) {
    toast(`Something went wrong (${method}).`, "error");
    console.error(e);
    return { ok: false };
  }
}

const nf = new Intl.NumberFormat("en-US");
const num = (n) => nf.format(n || 0);

function parseDate(iso) {
  const d = new Date(iso);
  return isNaN(d) ? null : d;
}
function fmtDate(iso, withTime = true) {
  const d = parseDate(iso);
  if (!d) return iso || "";
  const opts = { day: "numeric", month: "short", year: "numeric" };
  if (withTime) Object.assign(opts, { hour: "2-digit", minute: "2-digit", hour12: false });
  return new Intl.DateTimeFormat("en-GB", opts).format(d);
}
function fmtWhen(iso) {
  const d = parseDate(iso);
  if (!d) return iso || "";
  const time = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false }).format(d);
  const today = new Date();
  const yesterday = new Date(Date.now() - 864e5);
  if (d.toDateString() === today.toDateString()) return `today at ${time}`;
  if (d.toDateString() === yesterday.toDateString()) return `yesterday at ${time}`;
  return `on ${fmtDate(iso, false)}`;
}
function fmtShort(iso) {
  const d = parseDate(iso);
  return d ? new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" }).format(d) : (iso || "");
}
function fmtBytes(n) {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  n = n || 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i >= 3 ? 1 : 0)} ${units[i]}`;
}
const plural = (n, word, many = `${word}s`) => `${num(n)} ${n === 1 ? word : many}`;

// ── modal ────────────────────────────────────────────────────────────────────

function modal({ title, text, input, confirmLabel = "OK", danger = false, choices = null }) {
  return new Promise((resolve) => {
    const wrap = $("#modal");
    const close = (value) => { wrap.classList.add("hidden"); wrap.replaceChildren(); resolve(value); };
    const field = input !== undefined ? el("input", { type: "text", value: input, "aria-label": title }) : null;
    const buttons = choices
      ? choices.map((c, i) => el("button", { class: `btn${i === choices.length - 1 ? " primary" : ""}`, onclick: () => close(c.value) }, c.label))
      : [el("button", { class: "btn primary", style: danger ? "background: var(--danger)" : null,
                        onclick: () => close(field ? field.value : true) }, confirmLabel)];
    const box = el("div", { class: "modal" },
      el("h2", { id: "modal-title" }, title),
      text ? el("p", { class: "soft", style: "margin: 0" }, text) : null,
      field,
      el("div", { class: "actions" }, el("button", { class: "btn", onclick: () => close(null) }, "Cancel"), buttons));
    wrap.setAttribute("aria-labelledby", "modal-title");
    wrap.replaceChildren(box);
    wrap.classList.remove("hidden");
    wrap.onclick = (e) => { if (e.target === wrap) close(null); };
    box.addEventListener("keydown", (e) => {
      if (e.key === "Escape") close(null);
      if (e.key === "Enter" && field) close(field.value);
    });
    (field || box.querySelector(".btn.primary")).focus();
    if (field) field.select();
  });
}

// ── navigation ───────────────────────────────────────────────────────────────

function show(view) {
  ui.view = view;
  document.querySelectorAll(".nav").forEach((b) => {
    const on = b.dataset.view === view;
    b.classList.toggle("active", on);
    if (on) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
  });
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${view}`));
  $("#main").scrollTop = 0;
  render();
}
document.querySelectorAll(".nav").forEach((b) => b.addEventListener("click", () => show(b.dataset.view)));

function render() {
  if (ui.view === "studio") renderStudio();
  else if (ui.view === "compare") loadCompare();
  else if (ui.view === "snapshots") renderSnapshots();
  else if (ui.view === "newmac") loadNewMac();
  else if (ui.view === "inventory") loadInventory();
}

async function refresh() {
  ui.st = await api().state();
  $("#version").textContent = `v${ui.st.version}`;
  const list = await api().snapshots();
  ui.snapshots = list.snapshots || [];
}

// The snapshot that best describes this Mac right now.
const thisMacSummary = () => ui.st.current || ui.st.latest;
const thisMacId = () => (ui.st.current ? "current" : (ui.st.latest ? ui.st.latest.id : ""));

// ── My Studio ────────────────────────────────────────────────────────────────

const FORMATS = [["AU", "--f-au"], ["VST3", "--f-vst3"], ["AAX", "--f-aax"], ["VST", "--f-vst"], ["CLAP", "--f-clap"]];

function scanButton() {
  const running = ui.st.scan.status === "running";
  return el("button", { class: "btn primary", disabled: running, onclick: startScan }, running ? "Scanning…" : "Scan now");
}

async function startScan() {
  const res = await call("scan_start");
  if (res.ok) { ui.st.scan = res.scan; if (ui.view === "studio") renderStudio(); }
}

function renderStudio() {
  const root = $("#view-studio");
  const st = ui.st;
  const sum = thisMacSummary();
  const scan = st.scan;
  const running = scan.status === "running";

  let sub = "Not scanned yet.";
  if (st.current) sub = `Scanned ${fmtWhen(st.current.created_at)} · macOS ${st.macos}${st.current_saved_id ? " · saved as a snapshot" : ""}`;
  else if (st.latest) sub = `Showing the snapshot from ${fmtWhen(st.latest.created_at).replace(/^on /, "")} · scan to update`;

  const head = el("div", { class: "head" },
    el("div", {}, el("h1", { id: "studio-title" }, st.this_mac || "My Studio"), el("p", { class: "sub" }, sub)),
    el("div", { class: "actions" },
      sum ? el("button", { class: "btn", onclick: () => exportInventory(thisMacId()) }, "Export inventory…") : null,
      st.current && !st.current_saved_id ? el("button", { class: "btn", onclick: saveSnapshot }, "Save snapshot") : null,
      scanButton()));

  const parts = [head];

  if (running) {
    const order = ["plugins", "apps", "hardware"];
    const at = order.indexOf(scan.phase);
    const labels = { plugins: "Plug-ins", apps: "Music apps", hardware: "Hardware" };
    parts.push(el("div", { class: "card progress-line" },
      el("div", { class: "steps" }, order.map((p, i) =>
        el("span", { class: i < at ? "done" : (i === at ? "now" : "") }, `${i < at ? "✓ " : ""}${labels[p]}`))),
      el("div", { class: "meter indeterminate", role: "progressbar", "aria-label": "Scanning" }, el("div")),
      el("div", { style: "display: flex; justify-content: space-between; margin-top: 8px; font-size: var(--fs-s)" },
        el("span", { class: "muted" }, scan.message || "Working…"),
        el("button", { class: "link", onclick: () => call("scan_cancel") }, "Cancel"))));
  } else if (scan.error) {
    parts.push(el("p", { class: "card", style: "margin-top: 24px; color: var(--danger)" }, scan.error));
  }

  if (sum) {
    const stat = (value, label, note) => el("div", { class: "card stat" },
      el("b", {}, value), el("div", { class: "muted" }, label), el("small", { title: note }, note));
    parts.push(el("div", { class: "stats" },
      stat(num(sum.plugin_count), "Plug-ins", `${num(sum.product_count)} products · ${fmtBytes(sum.plugin_bytes)}`),
      stat(num(sum.app_count), "Music apps", sum.app_names.join(", ") + (sum.app_count > 3 ? " …" : "")),
      stat(num(sum.hardware_count), "Hardware", sum.hardware_count ? sum.hardware_names.join(", ") + (sum.hardware_count > 3 ? " …" : "") : "Nothing connected"),
      stat(num(sum.vendor_count), "Vendors", `${sum.matched_pct}% matched to an installer`)));

    const total = sum.plugin_count || 1;
    const present = FORMATS.filter(([f]) => sum.plugin_formats[f]);
    if (sum.intel_products) {
      const native = sum.cpu === "arm64";
      parts.push(el("div", { class: "card notice" },
        svg(["M12 3l9 16H3z", "M12 10v4", "M12 17v.5"]),
        el("div", { style: "flex: 1" },
          el("b", {}, `${plural(sum.intel_products, "plug-in")} ${sum.intel_products === 1 ? "is" : "are"} Intel-only`),
          el("div", { class: "soft", style: "font-size: var(--fs-s)" }, native
            ? `${plural(sum.intel_files, "file")}. On this Mac they only load in a DAW running under Rosetta. Look for Apple Silicon versions.`
            : `${plural(sum.intel_files, "file")}. They will not run natively on an Apple Silicon Mac. Look for updates before you move.`)),
        el("button", { class: "btn small", onclick: () => { Object.assign(ui.inv, { tab: "plugins", arch: "intel", kind: "", fmt: "", vendor: "", q: "" }); show("inventory"); } }, "Show them")));
    }
    parts.push(el("div", { class: "card formats" },
      el("div", { style: "display: flex; justify-content: space-between; color: var(--muted); font-size: var(--fs-s); margin-bottom: 8px" },
        el("span", {}, "Plug-in formats"), el("span", {}, `${num(sum.plugin_count)} files`)),
      el("div", { class: "bar", role: "img", "aria-label": present.map(([f]) => `${f} ${sum.plugin_formats[f]}`).join(", ") },
        present.map(([f, v]) => el("div", { style: `flex: ${sum.plugin_formats[f] / total}; background: var(${v})` }))),
      el("div", { class: "legend" }, present.map(([f, v]) =>
        el("span", {}, el("i", { style: `background: var(${v})` }), `${f} ${num(sum.plugin_formats[f])}`)))));
  }

  const ch = ui.studioChanges;
  if (ch) {
    const rows = groupChanges(ch.changes);
    const n = (k) => rows.filter((x) => x.kind === k).length;
    const filters = [["all", `All ${rows.length}`], ["added", `Added ${n("added")}`], ["updated", `Updated ${n("updated")}`], ["removed", `Removed ${n("removed")}`]];
    parts.push(el("div", { class: "changes-head" },
      el("h2", {}, `What changed since ${fmtShort(ch.old.created_at)}`),
      ch.empty ? null : el("div", { class: "chips", role: "group", "aria-label": "Filter changes" },
        filters.map(([k, label]) => el("button", {
          class: `chip${ui.changeFilter === k ? " on" : ""}`, "aria-pressed": String(ui.changeFilter === k),
          onclick: () => { ui.changeFilter = k; renderStudio(); } }, label)))));
    parts.push(ch.empty
      ? el("p", { class: "muted", style: "margin-top: 12px" }, "Nothing changed.")
      : changeList(ch.changes.filter((x) => ui.changeFilter === "all" || x.kind === ui.changeFilter)));
  } else if (st.current && !running) {
    parts.push(el("div", { class: "empty", style: "margin-top: 40px" },
      "This is the first snapshot of this Mac. Next time you scan, what changed shows up here."));
  } else if (!sum && !running) {
    parts.push(el("div", { class: "empty", style: "margin-top: 28px" }, "Scan this Mac to see your plug-ins, music apps and hardware."));
  }

  parts.push(el("p", { class: "foot-note" }, "Read-only. Nothing on your Mac is changed, and nothing leaves it."));
  root.replaceChildren(...parts);
}

// Plug-in changes come per format; show one row per product and kind, formats together.
function groupChanges(changes) {
  const out = [];
  const byKey = new Map();
  for (const c of changes) {
    if (c.category !== "plugins") { out.push(c); continue; }
    // Formats of one product often carry different version strings; only updates keep versions apart.
    const versions = c.kind === "updated" ? `|${c.old_version}|${c.new_version}` : "";
    const key = `${c.kind}|${c.name.toLowerCase()}${versions}`;
    const hit = byKey.get(key);
    if (hit) { hit.fmt = `${hit.fmt} · ${c.fmt}`; continue; }
    const row = { ...c };
    byKey.set(key, row);
    out.push(row);
  }
  return out;
}

function changeList(changes, limit = 300) {
  changes = groupChanges(changes);
  const shown = changes.slice(0, limit);
  const label = { plugins: "", apps: "App", hardware: "Hardware" };
  const box = el("div", { style: "margin-top: 12px" }, shown.map((c) => {
    const detail = c.kind === "updated" ? `${c.old_version} → ${c.new_version}` : (c.fmt || label[c.category]);
    return el("div", { class: "change" },
      el("span", { class: `kind ${c.kind}` }, c.kind),
      el("span", { class: "name" }, c.name, c.vendor ? el("span", { class: "muted" }, ` · ${c.vendor}`) : null),
      el("span", { class: "muted" }, detail || ""));
  }));
  if (changes.length > limit) box.append(el("p", { class: "muted", style: "font-size: var(--fs-s)" }, `And ${num(changes.length - limit)} more.`));
  if (!changes.length) box.append(el("p", { class: "muted" }, "None."));
  return box;
}

async function loadStudioChanges() {
  const res = await api().changes();
  ui.studioChanges = res.changes;
}

async function saveSnapshot() {
  const name = await modal({ title: "Save snapshot", text: "Give it a name you will recognise later.", input: ui.st.this_mac, confirmLabel: "Save" });
  if (name === null) return;
  const res = await call("save_snapshot", name);
  if (res.ok) { toast("Snapshot saved."); await refresh(); render(); }
}

async function exportInventory(id) {
  const res = await call("export_inventory", id);
  if (res.ok && !res.cancelled) toast("Inventory exported.");
}

// ── Snapshots ────────────────────────────────────────────────────────────────

function renderSnapshots() {
  const root = $("#view-snapshots");
  const mine = ui.snapshots.filter((s) => s.is_this_mac);
  const other = ui.snapshots.filter((s) => !s.is_this_mac);
  const latestMine = mine.length ? mine[0].id : "";

  const card = (s) => {
    return el("div", { class: "snap" },
      el("div", { class: "grow", style: "flex: 1; min-width: 220px" },
        el("div", { class: "title" }, s.name, s.id === latestMine ? el("span", { class: "badge" }, "Latest") : null),
        el("div", { class: "meta" }, `${s.is_this_mac ? "" : "Imported · "}${fmtDate(s.created_at)} · ${plural(s.plugin_count, "plug-in")} · ${plural(s.app_count, "app")} · ${num(s.hardware_count)} hardware`)),
      thisMacId() && thisMacId() !== s.id ? el("button", { class: "link", onclick: () => openCompare(thisMacId(), s.id) }, "Compare") : null,
      s.is_this_mac ? null : el("button", { class: "link", onclick: () => { ui.newmac.sourceId = s.id; show("newmac"); } }, "Make checklist"),
      el("button", { class: "link", onclick: () => renameSnapshot(s) }, "Rename"),
      el("button", { class: "link", onclick: () => exportSnapshot(s.id) }, "Export…"),
      el("button", { class: "link danger", onclick: () => trashSnapshot(s) }, "Move to Trash"));
  };

  const parts = [el("div", { class: "head" },
    el("div", {}, el("h1", {}, "Snapshots"), el("p", { class: "sub" }, "Your studio over time. Export one to take it to another Mac.")),
    el("button", { class: "btn", onclick: importSnapshot }, "Import snapshot…"))];

  if (!ui.snapshots.length) {
    parts.push(el("div", { class: "empty", style: "margin-top: 28px" }, "No snapshots yet. Scan this Mac, or import one from another Mac."));
  } else {
    if (mine.length) parts.push(el("div", { class: "label" }, "THIS MAC"), ...mine.map(card));
    if (other.length) parts.push(el("div", { class: "label" }, "OTHER MACS"), ...other.map(card));
  }
  parts.push(el("div", { class: "dropzone" }, "Drop a .studiovault file anywhere in the window to import it"));

  root.replaceChildren(...parts);
}

async function renameSnapshot(s) {
  const name = await modal({ title: "Rename snapshot", input: s.name, confirmLabel: "Rename" });
  if (name === null) return;
  const res = await call("rename_snapshot", s.id, name);
  if (res.ok) { await refresh(); render(); }
}

async function exportSnapshot(id) {
  const res = await call("export_snapshot", id);
  if (res.ok && !res.cancelled) toast("Snapshot exported. Copy it to the other Mac and import it there.");
}

async function trashSnapshot(s) {
  const ok = await modal({ title: "Move to Trash?", text: `“${s.name}” goes to the Trash. You can put it back from there.`, confirmLabel: "Move to Trash", danger: true });
  if (!ok) return;
  const res = await call("delete_snapshot", s.id);
  if (res.ok) {
    await refresh();
    render();
  }
}

async function importSnapshot() {
  const res = await call("import_snapshot");
  if (res.ok && !res.cancelled) {
    toast(`Imported “${res.name}”.`);
    await refresh();
    ui.newmac.sourceId = res.id;
    render();
  }
  return res;
}

// ── Compare ──────────────────────────────────────────────────────────────────

function openCompare(a, b) {
  Object.assign(ui.cmp, { a, b, data: null });
  show("compare");
}

function compareOptions() {
  const opts = [];
  if (ui.st.current) opts.push(["current", `This Mac — scan ${fmtWhen(ui.st.current.created_at)}`]);
  const others = [...ui.snapshots].sort((x, y) => (x.is_this_mac === y.is_this_mac ? 0 : x.is_this_mac ? 1 : -1));
  for (const s of others) opts.push([s.id, `${s.name} — ${fmtDate(s.created_at, false)}`]);
  return opts;
}

function defaultCompare() {
  const a = thisMacId();
  const other = ui.snapshots.find((s) => !s.is_this_mac);
  const olderMine = ui.snapshots.filter((s) => s.is_this_mac && s.id !== a)[0];
  return [a, (other || olderMine || {}).id || ""];
}

async function loadCompare() {
  const c = ui.cmp;
  const valid = (id) => id === "current" ? !!ui.st.current : ui.snapshots.some((s) => s.id === id);
  if (!valid(c.a) || !valid(c.b)) { [c.a, c.b] = defaultCompare(); c.data = null; }
  if (c.a && c.b && c.a !== c.b && !c.data) {
    const res = await call("side_by_side", c.a, c.b);
    c.data = res.ok ? res.compare : null;
  }
  renderCompare();
}

function renderCompare() {
  const root = $("#view-compare");
  const c = ui.cmp;
  const d = c.data;
  const head = el("div", { class: "head" },
    el("div", {}, el("h1", {}, "Compare"), el("p", { class: "sub" }, "Two Macs side by side: what one has that the other lacks, grouped by vendor.")));
  const opts = compareOptions();
  if (opts.length < 2) {
    root.replaceChildren(head, el("div", { class: "empty", style: "margin-top: 28px" },
      el("p", { style: "margin: 0 0 16px" }, "You need two snapshots: scan this Mac, then import a snapshot from your other Mac (or scan again later to compare over time)."),
      el("button", { class: "btn primary", onclick: importSnapshot }, "Import snapshot…")));
    return;
  }
  const select = (key, label) => el("label", {}, label, el("select", { class: "select",
    onchange: (e) => { c[key] = e.target.value; c.data = null; c.open.clear(); loadCompare(); } },
    opts.map(([v, t]) => el("option", { value: v, selected: c[key] === v }, t))));
  const swap = el("button", { class: "btn", "aria-label": "Swap A and B", title: "Swap A and B",
    onclick: () => { [c.a, c.b] = [c.b, c.a]; c.data = null; loadCompare(); } }, "⇄");
  const parts = [head, el("div", { class: "card", style: "margin-top: 24px" },
    el("div", { class: "pick" }, select("a", "A"), swap, select("b", "B")))];

  if (c.a === c.b) { parts.push(el("div", { class: "empty", style: "margin-top: 16px" }, "Pick two different snapshots.")); root.replaceChildren(...parts); return; }
  if (!d) { root.replaceChildren(...parts); return; }

  const nameA = d.a.machine_name || d.a.name, nameB = d.b.machine_name || d.b.name;
  const sameMac = nameA === nameB;
  const la = sameMac ? fmtShort(d.a.created_at) : nameA, lb = sameMac ? fmtShort(d.b.created_at) : nameB;
  const label = { only_a: "Only on A", only_b: "Only on B", different: "Different", same: "Same" };
  const stat = (key, n, text) => el("button", { class: c.filter === key ? "on" : "", "aria-pressed": String(c.filter === key),
    onclick: () => { c.filter = key; renderCompare(); } }, el("b", {}, num(n)), el("small", {}, text));
  const k = d.counts;
  parts.push(el("div", { class: "cmp-stats" },
    stat("only_a", k.only_a, `Only on ${la} (A)`), stat("only_b", k.only_b, `Only on ${lb} (B)`),
    stat("different", k.different, "Different version or formats"), stat("diff", k.only_a + k.only_b + k.different, "All differences")));
  parts.push(el("div", { class: "toolbar" }, el("span"),
    el("label", { class: "search" }, searchIcon(), el("span", { class: "sr" }, "Search"),
      el("input", { type: "search", placeholder: "Search vendors and plug-ins", value: c.q, oninput: (e) => { c.q = e.target.value; renderRows(); } }))));
  const box = el("div", { id: "cmp-groups" });
  parts.push(box);
  root.replaceChildren(...parts);
  renderRows();

  function keep(r) {
    if (c.filter === "diff") return r.status !== "same";
    return r.status === c.filter;
  }
  function cell(formats, version) {
    if (!formats.length && !version) return el("span", { class: "cell none" }, "—");
    return el("span", { class: "cell" }, [formats.join(" · "), version].filter(Boolean).join("  ·  v"));
  }
  function row(r) {
    const has = (side) => r.category === "hardware" ? (r.status === "same" || r.status === `only_${side}`) : null;
    const a = r.category === "hardware" ? el("span", { class: `cell${has("a") ? "" : " none"}` }, has("a") ? "✓" : "—") : cell(r.a_formats, r.a_version);
    const b = r.category === "hardware" ? el("span", { class: `cell${has("b") ? "" : " none"}` }, has("b") ? "✓" : "—") : cell(r.b_formats, r.b_version);
    return el("div", { class: "cmp-row" },
      el("span", {}, r.name, r.category === "apps" ? el("span", { class: "muted" }, " · app") : null),
      a, b, el("span", { class: `st ${r.status}` }, label[r.status]),
      r.note && r.category !== "hardware" ? el("span", { class: "note" }, r.note) : null);
  }
  function renderRows() {
    const q = c.q.trim().toLowerCase();
    const hit = (g, r) => !q || r.name.toLowerCase().includes(q) || (g && g.name.toLowerCase().includes(q));
    const cards = [];
    const header = () => el("div", { class: "cmp-row head" }, el("span", {}, "Name"), el("span", { class: "cell" }, `A · ${la}`), el("span", { class: "cell" }, `B · ${lb}`), el("span"));
    for (const g of d.groups) {
      const rows = g.rows.filter((r) => keep(r) && hit(g, r));
      if (!rows.length) continue;
      const open = c.open.has(g.key) || q;
      const visible = open ? rows : rows.slice(0, 6);
      cards.push(el("section", { class: "card group" },
        el("div", { class: "group-head" }, el("h2", {}, g.name),
          el("span", { style: "display: flex; gap: 12px; align-items: baseline" },
            g.download_url ? el("button", { class: "pill", style: "background: none", onclick: () => call("open_url", g.download_url) }, "Download page ↗") : null,
            el("span", { class: "muted", style: "font-size: var(--fs-s)" }, plural(rows.length, "item")))),
        header(), visible.map(row),
        rows.length > visible.length ? el("div", { style: "padding-top: 8px; border-top: 1px solid var(--line)" },
          el("button", { class: "link", onclick: () => { c.open.add(g.key); renderRows(); } }, `Show ${num(rows.length - visible.length)} more`)) : null));
    }
    const hw = d.hardware.filter((r) => keep(r) && hit(null, r));
    if (hw.length) cards.push(el("section", { class: "card group" }, el("div", { class: "group-head" }, el("h2", {}, "Hardware")), header(), hw.map(row)));
    if (!cards.length) cards.push(el("div", { class: "empty" }, q ? "Nothing matches." : (c.filter === "diff" ? "No differences. These two are in sync." : "None.")));
    $("#cmp-groups").replaceChildren(...cards);
  }
}

// ── New Mac ──────────────────────────────────────────────────────────────────

function defaultSource() {
  const other = ui.snapshots.find((s) => !s.is_this_mac);
  return other ? other.id : (ui.snapshots[0] ? ui.snapshots[0].id : "");
}

async function loadNewMac() {
  const nm = ui.newmac;
  if (!nm.sourceId || !ui.snapshots.some((s) => s.id === nm.sourceId)) nm.sourceId = defaultSource();
  if (!nm.sourceId) { nm.data = null; return renderNewMac(); }
  const res = await call("checklist", nm.sourceId);
  nm.data = res.ok ? res.checklist : null;
  renderNewMac();
}

function itemStatus(i) {
  if (i.status === "installed") return el("span", { class: "st ok" }, i.kind === "hardware" ? "Connected" : "Installed");
  if (i.manual_done) return el("span", { class: "st tick" }, "Ticked");
  if (i.status === "partial") return el("span", { class: "st part" }, `Missing ${i.missing_formats.join(", ")}`);
  return el("span", { class: "st miss" }, i.kind === "hardware" ? "Not seen yet" : "Missing");
}

function itemRow(i) {
  const auto = i.status === "installed";
  const id = `it-${i.id}`;
  const detail = i.kind === "plugin" ? i.formats.join(" · ") : (i.kind === "app" ? "app" : [i.vendor, i.category].filter(Boolean).join(" · "));
  return el("div", { class: "item" },
    el("input", { type: "checkbox", id, checked: i.done, disabled: auto,
                  title: auto ? "Found on this Mac" : "Tick when done", onchange: (e) => tick(i.id, e.target.checked) }),
    el("label", { for: id, class: "name" }, i.name, detail ? el("span", { class: "muted" }, ` · ${detail}`) : null,
      (i.warnings || []).map((w) => el("span", { class: "warn-note" }, w))),
    i.download_url ? el("button", { class: "link", onclick: () => call("open_url", i.download_url) }, "Drivers ↗") : null,
    itemStatus(i));
}

async function tick(itemId, done) {
  const nm = ui.newmac;
  const keep = $("#main").scrollTop;
  const res = await call("checklist_tick", nm.sourceId, itemId, done);
  if (res.ok) { nm.data = res.checklist; renderNewMac(); $("#main").scrollTop = keep; }
}

function matchesFilter(i) {
  const nm = ui.newmac;
  if (nm.filter === "missing" && i.done) return false;
  if (nm.filter === "done" && !i.done) return false;
  return true;
}

function renderNewMac() {
  const root = $("#view-newmac");
  const nm = ui.newmac;
  const c = nm.data;
  const head = el("div", { class: "head" },
    el("div", {}, el("h1", {}, "New Mac"), el("p", { class: "sub" }, "Everything from your old Mac, grouped by where you get it back.")),
    c ? el("div", { class: "actions" },
      el("button", { class: "btn", onclick: exportChecklist }, "Print or export…"),
      scanButton()) : null);

  if (!c) {
    root.replaceChildren(head, el("div", { class: "empty", style: "margin-top: 28px" },
      el("p", { style: "margin: 0 0 16px" }, "No snapshot to work from yet. On the old Mac: scan, then export the snapshot. On this Mac: import it here."),
      el("button", { class: "btn primary", onclick: importSnapshot }, "Import snapshot…")));
    return;
  }

  const pct = c.total ? Math.round(100 * c.done_count / c.total) : 100;
  const select = el("select", { class: "select", onchange: (e) => { nm.sourceId = e.target.value; nm.open.clear(); loadNewMac(); } },
    [...ui.snapshots].sort((a, b) => (a.is_this_mac === b.is_this_mac ? 0 : a.is_this_mac ? 1 : -1))
      .map((s) => el("option", { value: s.id, selected: s.id === nm.sourceId }, `${s.name} — ${fmtDate(s.created_at, false)}`)));
  const source = el("div", { class: "card source" },
    el("div", { class: "source-row" },
      el("label", {}, "From snapshot", select),
      el("div", { class: "big" }, num(c.done_count), el("span", {}, ` of ${num(c.total)} done`))),
    el("div", { class: "meter", style: "margin-top: 16px; height: 8px", role: "progressbar", "aria-valuenow": pct, "aria-valuemin": 0, "aria-valuemax": 100, "aria-label": "Checklist progress" },
      el("div", { style: `width: ${pct}%` })));

  const all = [...c.groups.flatMap((g) => g.items), ...c.hardware];
  const missing = all.filter((i) => !i.done).length;
  const filters = [["all", "All"], ["missing", `Missing ${num(missing)}`], ["done", `Done ${num(c.done_count)}`]];
  const q = nm.q.trim().toLowerCase();
  const hit = (g, i) => !q || i.name.toLowerCase().includes(q) || (g && g.name.toLowerCase().includes(q));

  const toolbar = el("div", { class: "toolbar" },
    el("div", { class: "chips", role: "group", "aria-label": "Show" }, filters.map(([k, label]) =>
      el("button", { class: `chip${nm.filter === k ? " on" : ""}`, "aria-pressed": String(nm.filter === k),
                     onclick: () => { nm.filter = k; renderNewMac(); } }, label))),
    el("label", { class: "search" }, searchIcon(), el("span", { class: "sr" }, "Search checklist"),
      el("input", { type: "search", placeholder: "Search vendors and plug-ins", value: nm.q,
                    oninput: (e) => { nm.q = e.target.value; renderGroupsOnly(); } })));

  const groupsBox = el("div", { id: "nm-groups" });
  root.replaceChildren(head, source, toolbar, groupsBox);
  renderGroupsOnly();

  function renderGroupsOnly() {
    const box = $("#nm-groups");
    const cards = [];
    const doneCards = [];
    const ordered = [...c.groups].sort((x, y) => (x.done_count === x.items.length) - (y.done_count === y.items.length));
    for (const g of ordered) {
      const items = g.items.filter((i) => hit(g, i) && matchesFilter(i));
      const allDone = g.done_count === g.items.length;
      if (!items.length && !(allDone && nm.filter === "all" && hit(g, { name: "" }))) continue;
      const facts = el("div", { class: "group-facts" },
        g.manager_app ? el("span", { class: `pill${g.manager_installed ? " ok" : ""}` },
          g.manager_installed ? `✓ ${g.manager_installed} installed` : `Installer: ${g.manager_app}`) : null,
        g.license_system && g.license_system !== "Unknown" ? el("span", { class: "pill" }, g.license_system) : null,
        g.download_url ? el("button", { class: "pill", style: "background: none", onclick: () => call("open_url", g.download_url) }, "Download page ↗") : null);
      if (allDone && nm.filter !== "done") {
        doneCards.push(el("div", { class: "done-row" },
          el("span", {}, g.name), el("span", { class: "done-count" }, `✓ ${g.done_count} of ${g.items.length}`)));
        continue;
      }
      const expanded = nm.open.has(g.key) || q;
      const visible = expanded ? items : items.slice(0, 4);
      cards.push(el("section", { class: "card group" },
        el("div", { class: "group-head" }, el("h2", {}, g.name), el("span", { class: "muted", style: "font-size: var(--fs-s)" }, `${num(g.done_count)} of ${num(g.items.length)} done`)),
        facts.childElementCount ? facts : null,
        el("p", { class: "step" }, g.next_step),
        el("div", {}, visible.map(itemRow),
          items.length > visible.length ? el("div", { style: "padding-top: 8px; border-top: 1px solid var(--line)" },
            el("button", { class: "link", onclick: () => { nm.open.add(g.key); renderGroupsOnly(); } }, `Show ${num(items.length - visible.length)} more`)) : null)));
    }
    const hw = c.hardware.filter((i) => hit(null, i) && matchesFilter(i));
    if (hw.length) {
      const connected = c.hardware.filter((i) => i.done).length;
      cards.push(el("section", { class: "card group" },
        el("div", { class: "group-head" }, el("h2", {}, "Hardware"), el("span", { class: "muted", style: "font-size: var(--fs-s)" }, `${connected} of ${c.hardware.length} connected`)),
        el("p", { class: "step" }, "Connect each device and install its driver or control app."),
        el("div", {}, hw.map(itemRow))));
    }
    if (doneCards.length) {
      cards.push(el("section", { class: "card group" },
        el("div", { class: "group-head" }, el("h2", {}, "Already done"), el("span", { class: "done-count" }, `✓ ${doneCards.length} vendors`)),
        el("div", { class: "done-grid" }, doneCards)));
    }
    if (!cards.length) cards.push(el("div", { class: "empty" }, nm.filter === "missing" && !q ? "Everything is back. Nice." : "Nothing matches."));
    box.replaceChildren(...cards);
  }
}

async function exportChecklist() {
  const fmt = await modal({ title: "Print or export", text: "The web page prints well and opens in any browser.",
    choices: [{ label: "CSV for a spreadsheet", value: "csv" }, { label: "Web page", value: "html" }] });
  if (!fmt) return;
  const res = await call("export_checklist", ui.newmac.sourceId, fmt);
  if (res.ok && !res.cancelled) toast("Checklist exported.");
}

// ── Inventory ────────────────────────────────────────────────────────────────

async function loadInventory() {
  const inv = ui.inv;
  const want = inv.id && (inv.id === "current" ? ui.st.current : ui.snapshots.some((s) => s.id === inv.id)) ? inv.id : thisMacId() || (ui.snapshots[0] || {}).id || "";
  if (!want) { inv.data = null; return renderInventory(); }
  if (want !== inv.id || !inv.data) {
    inv.id = want;
    const res = await call("inventory", want);
    inv.data = res.ok ? res : null;
  }
  renderInventory();
}

function renderInventory() {
  const root = $("#view-inventory");
  const inv = ui.inv;
  const d = inv.data;
  const options = [];
  if (ui.st.current) options.push(el("option", { value: "current", selected: inv.id === "current" }, `This Mac — scan ${fmtWhen(ui.st.current.created_at)}`));
  for (const s of ui.snapshots) options.push(el("option", { value: s.id, selected: inv.id === s.id }, `${s.name} — ${fmtDate(s.created_at, false)}`));

  const head = el("div", { class: "head" },
    el("div", {}, el("h1", {}, "Inventory"), el("p", { class: "sub" }, d ? `From ${d.snapshot.id === ui.st.current?.id ? "the scan" : `“${d.snapshot.name}”`} ${fmtWhen(d.snapshot.created_at)}` : "Nothing scanned yet.")),
    d ? el("div", { class: "actions" },
      options.length > 1 ? el("select", { class: "select", style: "min-width: 240px", "aria-label": "Snapshot",
        onchange: (e) => { inv.id = e.target.value; inv.data = null; loadInventory(); } }, options) : null,
      el("button", { class: "btn", onclick: () => exportInventory(inv.id) }, "Export CSV…")) : null);
  if (!d) { root.replaceChildren(head, el("div", { class: "empty", style: "margin-top: 28px" }, "Scan this Mac first.")); return; }

  const tabs = el("div", { class: "tabs", role: "tablist", "aria-label": "Inventory" },
    [["plugins", "Plug-ins", d.products.length], ["apps", "Apps", d.apps.length], ["hardware", "Hardware", d.hardware.length]].map(([k, label, n]) =>
      el("button", { class: `tab${inv.tab === k ? " on" : ""}`, role: "tab", "aria-selected": String(inv.tab === k),
                     onclick: () => { Object.assign(inv, { tab: k, q: "", fmt: "", kind: "", vendor: "", arch: "", sort: "name", dir: 1 }); renderInventory(); } },
        `${label} `, el("span", { class: "muted", style: "font-weight: 400" }, num(n)))));

  // Chip groups filter the plug-in table: key is the inv field, values [value, label].
  const chipGroup = (key, label, values) => el("div", { class: "chips", role: "group", "aria-label": label },
    values.map(([v, text]) => el("button", { class: `chip${inv[key] === v ? " on" : ""}`, "aria-pressed": String(inv[key] === v),
      "data-key": key, "data-v": v, onclick: () => { inv[key] = v; renderTable(); syncChips(); } }, text)));
  const plugins = inv.tab === "plugins";
  const kinds = new Set(d.products.map((p) => p.kind));
  const vendors = [...new Set(d.products.map((p) => p.vendor).filter(Boolean))].sort((a, b) => a.localeCompare(b, "en", { sensitivity: "base" }));

  const toolbar = el("div", { class: "toolbar", style: "margin-top: 16px" },
    el("label", { class: "search", style: "flex: 1; max-width: 420px" }, searchIcon(), el("span", { class: "sr" }, "Search"),
      el("input", { type: "search", placeholder: "Search name or vendor", value: inv.q, oninput: (e) => { inv.q = e.target.value; renderTable(); } })),
    plugins ? el("select", { class: "select", style: "min-width: 220px", "aria-label": "Vendor",
      onchange: (e) => { inv.vendor = e.target.value; renderTable(); } },
      el("option", { value: "" }, `All vendors (${num(vendors.length)})`),
      vendors.map((v) => el("option", { value: v, selected: inv.vendor === v }, v))) : null);
  const filters = plugins ? el("div", { class: "toolbar", style: "margin-top: 0" },
    chipGroup("kind", "Type", [["", "All types"], ...[["Instrument", "Instruments"], ["Effect", "Effects"], ["MIDI", "MIDI"]].filter(([k]) => kinds.has(k))]),
    d.products.some((p) => p.arch) ? chipGroup("arch", "Processor", [["", "Any processor"], ["intel", "Intel only"]]) : null,
    chipGroup("fmt", "Format", [["", "All formats"], ["VST3", "VST3"], ["AU", "AU"], ["CLAP", "CLAP"], ["VST", "VST"], ["AAX", "AAX"]])) : null;

  const tableBox = el("div", { id: "inv-table" });
  root.replaceChildren(head, tabs, toolbar, filters || "", tableBox);
  renderTable();

  function syncChips() {
    root.querySelectorAll(".chip[data-key]").forEach((b) => {
      const on = inv[b.dataset.key] === b.dataset.v;
      b.classList.toggle("on", on);
      b.setAttribute("aria-pressed", String(on));
    });
  }

  function actions(path) {
    return el("td", { class: "nw" },
      el("button", { class: "icon-btn row-btn", "aria-label": "Show in Finder", title: "Show in Finder", onclick: () => call("reveal", path) },
        svg(["M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"])),
      el("button", { class: "icon-btn row-btn", "aria-label": "Copy path", title: "Copy path", onclick: async () => {
        const r = await call("copy_path", path); if (r.ok) toast("Path copied."); } },
        svg(["M9 9h10v10H9z", "M5 15V5h10"])));
  }

  function sortHeader(key, label, cls = "") {
    const on = inv.sort === key;
    return el("th", { class: cls, "aria-sort": on ? (inv.dir > 0 ? "ascending" : "descending") : null },
      el("button", { onclick: () => { inv.dir = on ? -inv.dir : 1; inv.sort = key; renderTable(); } }, label, on ? (inv.dir > 0 ? " ↑" : " ↓") : ""));
  }

  function renderTable() {
    const q = inv.q.trim().toLowerCase();
    let rows, header, row;
    if (inv.tab === "plugins") {
      rows = d.products.filter((p) => (!q || p.name.toLowerCase().includes(q) || (p.vendor || "").toLowerCase().includes(q))
        && (!inv.fmt || p.formats.includes(inv.fmt)) && (!inv.kind || p.kind === inv.kind) && (!inv.vendor || p.vendor === inv.vendor)
        && (!inv.arch || p.arch));
      header = [sortHeader("name", "Product"), sortHeader("kind", "Type"), sortHeader("vendor", "Vendor"), el("th", {}, "Formats"), el("th", {}, "Version"), sortHeader("size", "Size", "num"), el("th", {}, el("span", { class: "sr" }, "Actions"))];
      row = (p) => el("tr", {},
        el("td", {}, p.name, p.arch ? el("span", { class: "intel-tag", title: "No Apple Silicon code in these formats" },
          p.arch === "intel" ? "Intel only" : `Intel: ${p.intel_formats.join(", ")}`) : null),
        el("td", { class: "soft" }, p.kind || "—"),
        el("td", {}, p.vendor_url
          ? el("button", { class: "vendor-link", title: `Open ${p.vendor}'s download page`, onclick: () => call("open_url", p.vendor_url) }, p.vendor, " ↗")
          : el("span", { class: "soft" }, p.vendor || "—")),
        el("td", { class: "nw" }, p.formats.map((f) => el("span", { class: "f" }, f))),
        el("td", { class: "soft nw" }, p.version || "—"), el("td", { class: "num soft" }, fmtBytes(p.size)),
        actions(p.path));
    } else if (inv.tab === "apps") {
      rows = d.apps.filter((a) => !q || a.name.toLowerCase().includes(q) || (a.developer || "").toLowerCase().includes(q));
      header = [sortHeader("name", "App"), sortHeader("developer", "Developer"), sortHeader("category", "Category"), el("th", {}, "Version"), el("th", {}, el("span", { class: "sr" }, "Actions"))];
      row = (a) => el("tr", {},
        el("td", {}, a.name), el("td", { class: "soft" }, a.developer || "—"), el("td", { class: "soft" }, a.category || "—"),
        el("td", { class: "soft" }, a.version || "—"),
        actions(a.path));
    } else {
      rows = d.hardware.filter((h) => !q || h.name.toLowerCase().includes(q) || (h.vendor || "").toLowerCase().includes(q));
      header = [sortHeader("name", "Device"), sortHeader("vendor", "Vendor"), sortHeader("device_type", "Type"), el("th", {}, "Connection")];
      row = (h) => el("tr", {}, el("td", {}, h.name), el("td", { class: "soft" }, h.vendor || "—"),
        el("td", { class: "soft" }, h.device_type || "—"), el("td", { class: "soft" }, h.connection_type || "—"));
    }
    const k = inv.sort;
    rows = [...rows].sort((a, b) => {
      const x = a[k] ?? "", y = b[k] ?? "";
      return (typeof x === "number" ? x - y : String(x).localeCompare(String(y), "en", { sensitivity: "base" })) * inv.dir;
    });
    const total = inv.tab === "plugins" ? d.products.length : d[inv.tab].length;
    const noun = inv.tab === "plugins" ? "products" : inv.tab === "apps" ? "apps" : "devices";
    $("#inv-table").replaceChildren(
      rows.length ? el("div", { class: "table-wrap" }, el("table", {}, el("thead", {}, el("tr", {}, header)), el("tbody", {}, rows.map(row))))
        : el("div", { class: "empty" }, total ? "Nothing matches." : `No ${noun} in this snapshot.`),
      el("p", { class: "muted", style: "margin-top: 12px; font-size: var(--fs-s)" },
        `Showing ${num(rows.length)} of ${num(total)} ${noun}${inv.tab === "plugins" ? " · one row per product, all formats together" : ""}`));
  }
}

// ── Settings drawer ──────────────────────────────────────────────────────────

async function openSettings() {
  ui.about = ui.about || await api().about();
  renderSettings();
  $("#scrim").classList.remove("hidden");
  $("#drawer").classList.remove("hidden");
  $("#drawer").querySelector("button").focus();
}
function closeSettings() {
  $("#scrim").classList.add("hidden");
  $("#drawer").classList.add("hidden");
  $("#settings-btn").focus();
}
$("#settings-btn").addEventListener("click", openSettings);
$("#scrim").addEventListener("click", closeSettings);

async function setSetting(key, value) {
  const res = await call("set_settings", { [key]: value });
  if (res.ok) ui.st.settings = res.settings;
}

function renderSettings() {
  const s = ui.st.settings;
  const a = ui.about;
  const toggle = (key, title, note) => el("label", { class: "set" },
    el("input", { type: "checkbox", checked: s[key], onchange: (e) => setSetting(key, e.target.checked) }),
    el("span", {}, title, el("br"), el("span", { class: "muted", style: "font-size: var(--fs-s)" }, note)));
  const link = (label, url) => el("button", { class: "lk", onclick: () => call("open_url", url) }, el("span", {}, label), el("span", { class: "muted" }, "↗"));

  $("#drawer").replaceChildren(
    el("div", { class: "drawer-head" }, el("h1", { style: "font-size: var(--fs-l)" }, "Settings"),
      el("button", { class: "icon-btn", "aria-label": "Close settings", onclick: closeSettings }, svg(["M6 6l12 12", "M18 6L6 18"]))),
    el("div", { class: "label", style: "margin-top: 24px" }, "SCANNING"),
    toggle("scan_on_launch", "Scan when the app opens", "Off by default. The last snapshot shows instantly either way."),
    toggle("auto_save_snapshot", "Save a snapshot when something changed", "Unchanged scans are not saved again."),
    el("div", { class: "set", style: "flex-direction: column; gap: 8px" },
      el("span", {}, "Extra plug-in folders"),
      s.extra_plugin_folders.length ? null : el("span", { class: "muted", style: "font-size: var(--fs-s)" }, "The standard macOS plug-in folders are always scanned."),
      s.extra_plugin_folders.map((f) => el("div", { class: "folder" }, el("span", { title: f }, f),
        el("button", { class: "link", onclick: async () => { const r = await call("remove_plugin_folder", f); if (r.ok) { ui.st.settings = r.settings; renderSettings(); } } }, "Remove"))),
      el("button", { class: "btn small", style: "align-self: flex-start", onclick: async () => {
        const r = await call("add_plugin_folder"); if (r.ok && !r.cancelled) { ui.st.settings = r.settings; renderSettings(); } } }, "Add folder…")),
    el("div", { class: "label", style: "margin-top: 28px" }, "ABOUT"),
    el("p", { style: "margin: 8px 0 16px", class: "soft" }, `${a.app_name} ${a.version} · macOS ${a.macos}`, el("br"),
      el("span", { class: "muted", style: "font-size: var(--fs-s)" }, "Free and open source. Made by BAKKIS, DJ and producer from Norway.")),
    el("button", { class: "lk", onclick: () => { closeSettings(); showHello(); } }, el("span", {}, "Why I built this"), el("span", { class: "muted" }, "›")),
    link("bakkis.com", a.links.website),
    link("Instagram", a.links.instagram),
    link("Listen on Spotify, SoundCloud, Beatport …", a.links.music),
    link("Support on Ko-fi", a.links.support),
    el("div", { class: "actions", style: "margin-top: 16px; align-items: center" },
      el("button", { class: "btn small", onclick: () => call("open_url", a.report_url) }, "Report a problem"),
      el("button", { class: "link", onclick: () => call("open_url", a.links.contact) }, "bakkis@bakkis.com")));
}

// ── First launch ─────────────────────────────────────────────────────────────

function renderWelcome() {
  const point = (paths, bold, rest) => el("div", {}, svg(paths), el("span", {}, el("b", {}, bold), " ", el("span", { class: "soft" }, rest)));
  const w = $("#welcome");
  w.replaceChildren(el("div", { class: "inner" },
    el("div", { class: "brand", style: "padding: 0" }, el("span", { class: "logo logo-wordmark", role: "img", "aria-label": "BAKKIS", style: "height: 18px" }), el("span", { class: "brand-sub" }, "STUDIO VAULT")),
    el("h1", {}, "Know your studio.", el("br"), "Move it anywhere."),
    el("p", { class: "lead" }, "See every plug-in, music app and piece of gear on this Mac, keep snapshots over time, and get a checklist when you set up a new one."),
    el("div", { class: "points" },
      point(["M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z", "M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z"], "Read-only.", "It never moves, changes or deletes your plug-ins."),
      point(["M6 11h12a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-6a2 2 0 0 1 2-2z", "M8 11V7a4 4 0 0 1 8 0v4"], "Private.", "Nothing leaves your Mac. No account, no cloud."),
      point(["M13 2L4 14h7l-1 8 9-12h-7z"], "Fast.", "A full scan takes a few seconds.")),
    el("div", { class: "actions" },
      el("button", { class: "btn primary", onclick: () => { w.classList.add("hidden"); show("studio"); startScan(); } }, "Scan this Mac"),
      el("button", { class: "btn", onclick: async () => {
        const r = await importSnapshot();
        if (r.ok && !r.cancelled) { w.classList.add("hidden"); show("newmac"); } } }, "Import from another Mac…")),
    el("p", { class: "muted", style: "margin-top: 16px; font-size: var(--fs-s)" }, "Moving to a new Mac? Scan the old one first, export the snapshot, then import it here.")));
  w.classList.remove("hidden");
  w.querySelector(".btn.primary").focus();
}

// ── "Hi, I'm BAKKIS": once on first launch, and from About ───────────────────

const SUPPORT_URL = "https://ko-fi.com/bakkis";

function showHello() {
  const wrap = $("#hello");
  const close = async () => {
    wrap.classList.add("hidden");
    wrap.replaceChildren();
    if (!ui.st.settings.welcome_seen) await setSetting("welcome_seen", true);
    const next = $("#welcome .btn.primary");
    if (next && !$("#welcome").classList.contains("hidden")) next.focus();
  };
  const go = el("button", { class: "btn primary", onclick: close }, "Let's go");
  wrap.replaceChildren(el("div", { class: "modal hello" },
    el("span", { class: "logo logo-boxed", role: "img", "aria-label": "BAKKIS" }),
    el("h2", { id: "hello-title", style: "font-size: var(--fs-l); margin: 4px 0 0" }, "Hi, I'm BAKKIS."),
    el("p", {}, "Every time I set up a new Mac, I lost days hunting for installers, serials and logins for hundreds of plug-ins, and I always forgot something. So I built the app I wanted: scan the old Mac, get a checklist for the new one."),
    el("p", {}, "It only reads your Mac. It never moves, changes or deletes a plug-in, and nothing leaves your computer."),
    el("div", { class: "actions" }, go),
    el("p", { class: "foot" }, "Free and open source. ",
      el("button", { onclick: () => call("open_url", SUPPORT_URL) }, "Buy me a coffee ☕"))));
  wrap.onclick = (e) => { if (e.target === wrap) close(); };
  wrap.onkeydown = (e) => { if (e.key === "Escape" || e.key === "Enter") { e.preventDefault(); close(); } };
  wrap.classList.remove("hidden");
  go.focus();
}

// ── events from Python ───────────────────────────────────────────────────────

window.vault = {
  async onEvent(event, data) {
    if (event === "scan") {
      ui.st.scan = data;
      if (data.status === "done") {
        await refresh();
        await loadStudioChanges();
        ui.inv.data = null;
        ui.cmp.data = null;
        if (ui.inv.id !== "current") ui.inv.id = "";
        render();
        const ch = ui.studioChanges;
        const n = ch && !ch.empty ? groupChanges(ch.changes).length : 0;
        toast(n ? `Scan done · ${n} change${n === 1 ? "" : "s"}.` : "Scan done.");
      } else if (data.status === "failed") {
        toast(data.error, "error");
        render();
      } else if (data.status === "cancelled") {
        toast("Scan cancelled.", "warning");
        render();
      } else if (ui.view === "studio") {
        renderStudio();
      } else if (ui.view === "newmac") {
        $("#view-newmac .actions .btn.primary")?.replaceWith(scanButton());
      }
    } else if (event === "snapshots") {
      await refresh();
      ui.cmp.data = null;
      $("#welcome").classList.add("hidden");
      render();
    } else if (event === "toast") {
      toast(data.text, data.level);
    }
  },
};

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("#drawer").classList.contains("hidden")) closeSettings();
  if (e.metaKey && ["1", "2", "3", "4", "5"].includes(e.key)) {
    e.preventDefault();
    show(["studio", "compare", "newmac", "inventory", "snapshots"][Number(e.key) - 1]);
  }
});
// Stop the web view from opening dropped files itself; Python imports snapshot drops.
["dragover", "drop"].forEach((t) => window.addEventListener(t, (e) => e.preventDefault()));

window.addEventListener("pywebviewready", async () => {
  await refresh();
  await loadStudioChanges();
  render();
  if (!ui.st.has_snapshots && !ui.st.current && ui.st.scan.status !== "running") renderWelcome();
  else if (ui.st.settings.scan_on_launch && ui.st.scan.status !== "running") startScan();
  if (!ui.st.settings.welcome_seen) showHello();
});
