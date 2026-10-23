# BAKKIS STUDIO VAULT v2 — rebuild plan

Status: milestone 1 done 2026-10-23 (package scaffold, config, scanners ported with CLAP + size cache, tests in `tests/v2/`). Next: milestone 2. Branch `v2-pywebview` (off `feature/license-vault`).
Owner: Andreas (BAKKIS). Communicate with him in Norwegian; code, comments and commits in English.

## Goal

Turn the broad "studio manager" (v1, CustomTkinter, ~23,000 lines, 15 modules) into a **small, focused, free macOS app**
that answers one question well:

> **"What is in my studio, what changed, and what do I need to reinstall and re-authorize on a new Mac?"**

Same setup as BAKKIS MUSIC SORTER v2: pywebview + HTML/CSS/JS frontend, Python backend, open source (MIT), shared as a
double-clickable app via GitHub Releases. The app doubles as a discreet promo tool for BAKKIS.

## Why this niche (market check, 2026-10-23)

Plug-in managers are crowded: PluginHub, Plugin Station, Pluginize!, PlugPane (free), KVR Studio Manager (free),
Plugoff (free), OwlPlug (open source), VST Manager, Sonisto, ProducerGrid. They compete on **update checking**,
**uninstall**, **enable/disable** and **license key vaults**. We do **not** compete there.

All of them are **plug-in only**. None covers the whole studio (plug-ins + music apps + audio interfaces + MIDI +
hardware) as a **snapshot over time** with a **new-Mac migration checklist**. That is the gap v2 fills.

## Scope

### In (v2.0)

| Area | What |
|---|---|
| Scan | Plug-ins (AU, VST, VST3, AAX, **CLAP**), music apps (DAWs, managers like Native Access / iLok / Waves Central), audio interfaces, MIDI devices, other studio hardware. Background thread, progress, cancel. |
| Snapshots | Every scan can be saved as a snapshot. A timeline of snapshots per Mac. One schema (v2) replacing the two v1 formats. |
| What changed | Compare the current scan with the last snapshot (or any two snapshots): added, removed, version changed. Shown on the home screen after each scan. |
| Migration checklist | From a snapshot of the old Mac, build a checklist for the new Mac, grouped **by vendor**: what to install, which manager app installs it (Native Access, Plugin Alliance, Waves Central …), which license system it uses (iLok, vendor account, serial), and a link to the vendor's download page. Items tick off automatically when a rescan finds them; manual tick for the rest. Progress saved. |
| Hardware checklist | Interfaces / controllers from the old snapshot: "connect and install driver", with the vendor link where known. |
| Export | Snapshot file (`.studiovault`, JSON) to move between Macs (AirDrop / iCloud / USB). Printable HTML report and CSV of the checklist. |
| Inventory | Searchable tables for plug-ins, apps and hardware (read-only). Format coverage per plug-in (folds in v1 "Format Analysis" as a column). |

### Out (not in v2, maybe never)

- Online update checking, version databases, shop links.
- Uninstall, enable/disable, quarantine, cleanup recommendations. **v2 never moves, changes or deletes plug-ins.**
- Plug-in Health, Plugin Insights, the v1 Studio Overview dashboard, the 1,500-line Settings view.
- Any network traffic except opening links in the browser. No accounts, no cloud sync, no analytics.

## Decisions (approved by Andreas, 2026-10-23)

| Topic | Decision |
|---|---|
| UI toolkit | Leave CustomTkinter. **pywebview** (WKWebView) + HTML/CSS/JS, no build step, no framework. Same as Music Sorter. |
| Backend bridge | pywebview `js_api` (no local HTTP server needed — there is no audio to stream). |
| Read-only | Hard rule: the app only reads the system. Writes go to its own data folder, the Keychain, and export files the user picks. |
| Storage | JSON snapshot files (source of truth) + one small JSON settings/checklist-state file. **Drop the SQLite layer** from v1 (`app/db/`). |
| App name | **BAKKIS STUDIO VAULT** (matches the repo; v1 used "Bakkis Studio Manager"). Bundle id `com.bakkis.studio-vault`, version 2.0.0. |
| Data folder | `~/Library/Application Support/BAKKIS STUDIO VAULT/` (snapshots/, settings.json, checklists/). Import v1 snapshots from `~/Library/Application Support/BakkisStudioManager/` on first launch. |
| Privacy in shared files | Snapshot exports contain no serials, no Keychain data, and replace the home folder in paths with `~`. Machine id is a salted hash, not the raw IOPlatformUUID. Hostname kept (user can rename the snapshot). |
| Platform | macOS only. Universal app (Apple Silicon + Intel), python.org Python 3.12 universal2, minimum macOS 13 Ventura. |
| Signing | Build script supports unsigned (default) and Developer ID signed + notarized, as Music Sorter. |
| Distribution | GitHub Releases, zip per version. |
| License | MIT. BAKKIS name and logo excluded (same wording as Music Sorter). Audit git history for personal data before the repo goes public. |
| Promo & support | Discreet, as Music Sorter: About section with follow links (bakkis.com, Instagram, songshare), Ko-fi, `.github/FUNDING.yml`. No popups. |
| Contact | `bakkis@bakkis.com` in README and Settings → About; "Report a problem" (prefilled e-mail with app + macOS version). |
| Language | English everywhere: UI, README, docs. |
| License notes | **Postponed to v2.1.** v2.0 ships scan, snapshots, compare and checklist; the checklist already shows each vendor's license system. |

## Problems found in v1 (fix or avoid in v2)

1. **Two snapshot systems** with different schemas: `app/core/studio_snapshots.py` (schema v1, plug-ins + software + hardware) and `app/core/migration_assistant.py` (plug-ins + apps, own compare + CSV/HTML export). Merge into one.
2. **Name mismatch**: repo "Studio Vault", README/UI "Bakkis Studio Manager", data folder `BakkisStudioManager`.
3. `_app_version()` reads package metadata for `bakkis-studio-manager`, which is never installed → snapshots always have an empty `app_version`.
4. **Snapshots leak personal data** when shared: raw IOPlatformUUID, full paths with the macOS username.
5. **Plug-in scanner misses CLAP** and computes bundle size with a full `rglob` on every scan (slow for large sample-based plug-ins). Cache size by path + mtime, or compute lazily.
6. **Quarantine moves plug-in files** — the riskiest code in the app and outside the new scope. Drop it.
7. **Not runnable on this Mac right now**: `.venv` points at a Python 3.12 that is no longer installed (only `/usr/bin/python3` 3.9 is present) and the UI uses `match` (3.10+). Core tests pass on 3.9 (290 passed). Install python.org 3.12 universal2 before milestone 1.
8. **README is outdated** (lists modules as "Coming soon" that exist), no LICENSE, no packaging script, `.gitignore` ignores every `*.csv`.
9. **`main` is behind**: all work since "Cleanup Recommendation Actionability Layer" lives on `feature/license-vault`. Stale branch `cursor/format-analysis-view` is already merged.
10. **Core MIDI fallback in `hardware_scanner.py` segfaults** on this Mac (pointers passed to `CFRelease` without argtypes get truncated). Only hit when `system_profiler SPMIDIDataType` is empty, which it is here. Fixed in v2 by reusing the MIDI scanner's Core MIDI reader; v1 still has the bug.

## What to reuse from v1

Port and trim (keep their tests):

| v1 | v2 |
|---|---|
| `app/core/scanner.py` | `scanners/plugins.py` (+ CLAP, size cache) |
| `app/core/music_software_scanner.py` | `scanners/apps.py` |
| `app/core/audio_device_scanner.py` | `scanners/audio.py` |
| `app/core/midi_scanner.py` | `scanners/midi.py` |
| `app/core/hardware_scanner.py` | `scanners/hardware.py` |
| `app/core/vendor_registry.py` + manager defs in `license_vault.py` | `vendors.py` (one registry: vendor → manager app, license system, download URL) |
| `app/core/studio_snapshots.py` + `migration_assistant.py` | `snapshot.py` + `compare.py` + `report.py` |

Everything else in `app/` (UI, db, quarantine, cleanup, health, insights) stays in v1 only.

## Architecture

```
studio_vault/
  __init__.py      version, APP_NAME
  config.py        paths (bundle dir, user data dir), settings load/save, v1 data import
  scanners/        plugins.py, apps.py, audio.py, midi.py, hardware.py — pure functions returning dataclasses,
                   each with progress callback + cancel flag; system_profiler/ioreg calls behind one helper so tests can fake them
  vendors.py       static vendor registry: patterns, manager app, license system, download URL
  snapshot.py      schema v2 dataclasses, save/load/list, import of v1 files (both formats), privacy scrubbing on export
  compare.py       diff two snapshots (added / removed / version changed), per category
  checklist.py     build migration checklist from a snapshot + current scan; persisted tick state per checklist
  keychain.py      (v2.1) license notes via `security add-generic-password` / `find-generic-password` (service "BAKKIS STUDIO VAULT")
  report.py        HTML report (printable) and CSV export
  api.py           the js_api class: thin, JSON in/out, long work on a worker thread, results pushed with evaluate_js
  app.py           pywebview window, file dialogs, reveal in Finder, open links, shutdown
  web/             index.html, app.css, app.js
main.py            entry point
tests/             pytest: scanners (with recorded system_profiler fixtures), snapshot round-trip + v1 import, compare, checklist, keychain (mocked, v2.1)
```

## Performance requirements

- Window visible in < 1 s; last snapshot shown immediately from disk, no scan on launch unless the user asks (setting).
- Full scan of ~1,000 plug-ins in < 10 s on Apple Silicon; UI never blocks, progress per category.
- Tables of several thousand rows filter as you type (virtualized list or plain DOM with debounced filter).

## UX design (direction, to agree in chat)

One window, left rail with four items, dark theme like Music Sorter (`-apple-system`, 8 px grid, one accent).

1. **My Studio** (home): counts per category, date of last snapshot, big **Scan now**. After a scan: "What changed since <date>" (added / removed / updated), then **Save snapshot**.
2. **Snapshots**: timeline of saved snapshots for this Mac and imported ones from other Macs. Compare any two. Export / import `.studiovault` file. Drag a snapshot file onto the window to import.
3. **New Mac**: pick a snapshot from the old Mac → checklist grouped by vendor, with manager app, license system, download link, notes button (Keychain). Filters: all / missing / done. Hardware section at the bottom. Print / export.
4. **Inventory**: tabs Plug-ins · Apps · Hardware, search, format coverage column, reveal in Finder, CSV export.

Settings and About are a drawer (gear icon), not a page. First launch: one screen explaining "read-only, nothing is changed, nothing leaves your Mac" + **Scan now**.

## Settings & data locations

`~/Library/Application Support/BAKKIS STUDIO VAULT/`
- `settings.json` — scan on launch, extra plug-in folders, auto-save snapshot after scan
- `snapshots/*.studiovault` — JSON, schema v2
- `checklists/<snapshot-id>.json` — tick state

Keychain (v2.1): generic passwords, service `BAKKIS STUDIO VAULT`, account = vendor key.

## Packaging (macOS)

As Music Sorter: `build_mac_app.sh` with PyInstaller, universal2, unsigned by default, `--sign` path for Developer ID +
notarization, zip named `BAKKIS-STUDIO-VAULT-x.y.z.zip`. `PACKAGING.md` documents it. Test on a clean user account.

## Repo hygiene

- Add `LICENSE` (MIT + logo exclusion), `.github/FUNDING.yml` (`ko_fi: bakkis`), `pytest.ini`, `requirements-dev.txt`, `requirements-packaging.txt`.
- Rewrite `README.md` for v2 (what it does, install, first launch of an unsigned app, privacy, follow/support links).
- `.gitignore`: stop ignoring all `*.csv` (only ignore exports in the repo root), add `.pytest_cache/`.
- Done 2026-10-23: `feature/license-vault` merged into `main`, tagged `v1-final`.
- Done 2026-10-23: merged branch `cursor/format-analysis-view` deleted.

## Milestones

1. Install Python 3.12 universal2, fresh `.venv`. Scaffold `studio_vault/`, `config.py`, port scanners + tests (add CLAP, size cache, fake `system_profiler`).
2. `vendors.py`, `snapshot.py` (schema v2, v1 import, privacy scrubbing), `compare.py` + tests.
3. `checklist.py`, `report.py` + tests.
4. `api.py` + `app.py`: pywebview window, background scan with progress, file dialogs, drag-and-drop import.
5. Frontend: My Studio, Snapshots, New Mac, Inventory, settings drawer, first-launch screen.
6. Packaging (universal, unsigned + signed), README, PACKAGING.md, LICENSE, FUNDING.yml. Test on a clean account.
7. Real-world test: snapshot Andreas' studio Mac, restore checklist on a second Mac or user account. Fix gaps in `vendors.py`.
8. Merge to `main`, tag `v2.0.0`, GitHub Release.
9. v2.1: license notes per vendor in the macOS Keychain (`keychain.py`, notes button in the checklist). Never written to snapshot files.

## Testing

- `pytest` for everything under `studio_vault/` except `app.py`; scanners tested against recorded `system_profiler` JSON and temp-dir plug-in bundles with fake `Info.plist`.
- Never call the real Keychain in tests (mock `security`). Never read the real `/Library/Audio` in tests.
- Snapshot round-trip and v1-import tests use the two real v1 formats as fixtures.
