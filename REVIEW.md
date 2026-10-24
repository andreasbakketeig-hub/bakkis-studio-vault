# Review brief: BAKKIS STUDIO VAULT v2

You are reviewing branch `v2-pywebview` against `main`. **Read only: do not edit, create or delete any file,
and do not run anything that writes outside a temp folder.** Report findings; they will be fixed separately.

Read `CLAUDE.md` and `PLAN.md` first. In short: a free, offline macOS app (Python + pywebview, plain
HTML/CSS/JS) that scans a studio Mac (plug-ins, music apps, hardware, presets folders), keeps snapshots,
compares Macs, builds a new-Mac checklist, checks Ableton Live projects, and the new **Handoff** module that
checks a Live Set before sending it to a collaborator.

Code: `studio_vault/` (v2). `app/` and `main.py` are the old v1 and out of scope. Tests: `tests/v2/`
(run with `.venv/bin/python -m pytest`).

## What to look for (in this order)

1. **Correctness bugs** with a concrete input that breaks them. Wrong results matter more than style.
2. **The hard rules in CLAUDE.md**
   - Read-only: the app never moves, changes or deletes plug-ins, apps or project files. Writes only go to
     its data folder (`~/Library/Application Support/BAKKIS STUDIO VAULT/`) and files the user picks in a
     save dialog. Anything else writing to disk is a bug.
   - Privacy: snapshot files and `.handoffplugins` lists must not contain user names in paths, raw hardware
     ids, serials or license keys.
   - Tests never read real user folders (`/Library/Audio`, `~/Music` …), never call the real Keychain or
     `system_profiler`.
3. **`studio_vault/handoff/`** (newest, standard library only, must not import the rest of `studio_vault`)
   - `als.py`: Live Set reader. Malformed, huge, hostile (XML bombs, odd encodings) or old (Live 9/10) files;
     FileRef path types; freeze-file detection; anything that could write to the .als.
   - `pluginlist.py`: receiver's plug-in export; names must match what Live stores (AU vendor + name,
     VST3 class names, VST bundle names).
   - `check.py`: traffic-light rules (red = certainly missing for the receiver, yellow = check, green = ready).
     Are any reds really yellows or the other way round? Missed cases?
4. **`studio_vault/api.py` and `app.py`**: threads (scan job, project-check job) and the shared lock; pywebview
   calls each API method on its own thread. Races, stale state, exceptions that escape. `open_url` must only
   open `https:` and `mailto:`; `reveal`/`copy_path` must not be abusable.
5. **`studio_vault/web/app.js`**: data from files must never become HTML (look for `innerHTML` or attributes
   built from data); stale view state after scans, imports, drops; keyboard and screen-reader basics.
6. **Scanners and matching**: `scanners/plugins.py` (Mach-O arch reading, size cache), `projects.py` and
   `handoff/check.py` name matching (false "missing" or false "installed"), `content.py` (vendor folder
   matching, time budget), `compare.py`, `checklist.py`.

## How to report

A numbered list, most severe first. For each: file and line, what is wrong, a concrete input or sequence that
triggers it, and a suggested fix in one or two sentences. Say "verified" if you ran something to confirm it,
otherwise "suspected". Skip pure style and formatting. End with anything you think is missing from the tests.
