# CLAUDE.md

Read `PLAN.md` first — it holds the v2 plan, scope, decisions and milestones.

- Talk to Andreas in Norwegian. Code, comments, commit messages, UI and docs in English (no other UI languages).
- v1 is `app/` + `main.py` (CustomTkinter). Keep it runnable until v2 ships; reuse its core scanners, not its UI.
- v2 lives in `studio_vault/` on `main` (merged and tagged `v2.0.0` on 2026-10-24; v1 is tag `v1-final`). macOS only. Same setup as BAKKIS MUSIC SORTER v2.
  Run it with `.venv/bin/python -m studio_vault` or `Start BAKKIS Studio Vault.command`; build the .app with `./build_mac_app.sh` (see PACKAGING.md) (set `STUDIO_VAULT_DATA_DIR` to a temp dir to keep test runs out of real user data).
- v2 is read-only: never move, change or delete plug-ins or apps. Writes go only to the app's data folder, the Keychain and user-chosen export files.
- The only network request is the update check (`studio_vault/updates.py`, one GitHub Releases call at startup, setting `check_for_updates`); the installer (`updater.py`) runs only when the user clicks. Tests never touch the network: patch `updates.check`.
- Handoff packing never changes the project folder: files are left out of the zip, not deleted.
- Tests never read the real `/Library/Audio`, call the real Keychain, or run `system_profiler`; use temp dirs and recorded fixtures.
- Speed matters: scans run on a worker thread; never block the UI.
- Keep the shared BAKKIS app palette (same tokens as Music Sorter): colours, `--fs-s/m/l/xl` only, 8 px grid.
