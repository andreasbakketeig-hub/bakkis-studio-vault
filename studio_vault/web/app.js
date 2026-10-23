"use strict";

// Minimal shell for milestone 4: My Studio (scan, counts, what changed) and Snapshots.
// The full UI comes in milestone 5.

const $ = (sel) => document.querySelector(sel);
const api = () => window.pywebview.api;

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children) node.append(c instanceof Node ? c : document.createTextNode(String(c ?? "")));
  return node;
}

function toast(text, level = "ok") {
  const t = el("div", { class: `toast ${level}` }, text);
  $("#toasts").append(t);
  setTimeout(() => t.remove(), 4000);
}

function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function fmtBytes(n) {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i ? 1 : 0)} ${units[i]}`;
}

// ── Navigation ────────────────────────────────────────────────────────────────

function show(view) {
  document.querySelectorAll(".nav").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${view}`));
  if (view === "snapshots") loadSnapshots();
}
document.querySelectorAll(".nav").forEach((b) => b.addEventListener("click", () => show(b.dataset.view)));

// ── My Studio ─────────────────────────────────────────────────────────────────

function renderScan(scan) {
  const running = scan.status === "running";
  $("#scan-btn").disabled = running;
  $("#scan-btn").textContent = running ? "Scanning…" : "Scan now";
  $("#cancel-btn").classList.toggle("hidden", !running);
  $("#scan-msg").textContent = running ? scan.message : scan.error || "";
}

function renderCurrent(current) {
  const box = $("#counts");
  box.replaceChildren();
  if (!current) return;
  const formats = Object.entries(current.plugin_formats).sort((a, b) => b[1] - a[1])
    .map(([f, n]) => `${f} ${n}`).join(" · ");
  box.append(
    el("div", { class: "card" }, el("b", {}, current.plugin_count), el("small", {}, `Plug-ins · ${fmtBytes(current.plugin_bytes)}`)),
    el("div", { class: "card" }, el("b", {}, current.app_count), el("small", {}, "Music apps")),
    el("div", { class: "card" }, el("b", {}, current.hardware_count), el("small", {}, "Hardware")),
  );
  $("#studio-sub").textContent = `Scanned ${fmtDate(current.created_at)} · ${formats}`;
}

async function renderChanges() {
  const res = await api().changes();
  const box = $("#changes");
  box.replaceChildren();
  const ch = res.changes;
  if (!ch) return;
  box.append(el("h2", {}, `What changed since ${fmtDate(ch.old.created_at)}`));
  if (ch.empty) { box.append(el("p", { class: "muted" }, "Nothing changed.")); return; }
  for (const c of ch.changes.slice(0, 200)) {
    const ver = c.kind === "updated" ? `${c.old_version} → ${c.new_version}` : (c.new_version || c.old_version);
    box.append(el("div", { class: "change" },
      el("span", { class: `tag ${c.kind}` }, c.kind),
      el("span", {}, `${c.name}${c.fmt ? ` (${c.fmt})` : ""}`),
      el("span", { class: "muted" }, ver || "")));
  }
}

async function refreshState() {
  const st = await api().state();
  $("#version").textContent = `v${st.version} · macOS ${st.macos}`;
  $("#studio-title").textContent = st.this_mac || "My Studio";
  renderScan(st.scan);
  renderCurrent(st.current || st.latest);
  return st;
}

$("#scan-btn").addEventListener("click", async () => renderScan((await api().scan_start()).scan));
$("#cancel-btn").addEventListener("click", () => api().scan_cancel());

// ── Snapshots ─────────────────────────────────────────────────────────────────

async function loadSnapshots() {
  const res = await api().snapshots();
  const list = $("#snapshot-list");
  list.replaceChildren();
  if (!res.snapshots.length) {
    list.append(el("p", { class: "muted" }, "No snapshots yet. Scan this Mac, or import one from another Mac."));
    return;
  }
  for (const s of res.snapshots) {
    const name = el("div", {}, s.name);
    if (s.is_this_mac) name.append(el("span", { class: "badge" }, "This Mac"));
    list.append(el("div", { class: "snap" },
      el("div", { class: "grow" }, name,
        el("small", { class: "muted" }, `${fmtDate(s.created_at)} · ${s.plugin_count} plug-ins · ${s.app_count} apps · ${s.hardware_count} hardware`)),
      el("button", { class: "link", onclick: () => exportSnapshot(s.id) }, "Export…"),
      el("button", { class: "link", onclick: () => deleteSnapshot(s) }, "Move to Trash")));
  }
}

async function exportSnapshot(id) {
  const res = await api().export_snapshot(id);
  if (!res.ok) toast(res.error, "error");
  else if (!res.cancelled) toast("Snapshot exported.");
}

async function deleteSnapshot(s) {
  if (!confirm(`Move “${s.name}” to the Trash?`)) return;
  const res = await api().delete_snapshot(s.id);
  if (!res.ok) toast(res.error, "error");
  loadSnapshots();
}

$("#import-btn").addEventListener("click", async () => {
  const res = await api().import_snapshot();
  if (!res.ok) toast(res.error, "error");
  else if (!res.cancelled) { toast(`Imported “${res.name}”.`); loadSnapshots(); }
});

// ── Events from Python ────────────────────────────────────────────────────────

window.vault = {
  onEvent(event, data) {
    if (event === "scan") {
      renderScan(data);
      if (data.status === "done") { refreshState(); renderChanges(); loadSnapshots(); }
      if (data.status === "failed") toast(data.error, "error");
    } else if (event === "snapshots") {
      loadSnapshots();
    } else if (event === "toast") {
      toast(data.text, data.level);
    }
  },
};

// Stop the web view from opening dropped files itself; Python handles snapshot drops.
["dragover", "drop"].forEach((t) => window.addEventListener(t, (e) => e.preventDefault()));

window.addEventListener("pywebviewready", async () => {
  const st = await refreshState();
  renderChanges();
  if (st.settings.scan_on_launch && st.scan.status !== "running") renderScan((await api().scan_start()).scan);
});
