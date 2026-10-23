# CLAUDE.md

Read `PLAN.md` first — it holds the v2 plan, scope, decisions and milestones.

- Talk to Andreas in Norwegian. Code, comments, commit messages, UI and docs in English (no other UI languages).
- v1 is `app/` + `main.py` (CustomTkinter). Keep it runnable until v2 ships; reuse its core scanners, not its UI.
- v2 lives in `studio_vault/` on branch `v2-pywebview`. macOS only. Same setup as BAKKIS MUSIC SORTER v2.
- v2 is read-only: never move, change or delete plug-ins or apps. Writes go only to the app's data folder, the Keychain and user-chosen export files.
- Tests never read the real `/Library/Audio`, call the real Keychain, or run `system_profiler`; use temp dirs and recorded fixtures.
- Speed matters: scans run on a worker thread; never block the UI.
