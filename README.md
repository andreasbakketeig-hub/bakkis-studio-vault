# BAKKIS STUDIO VAULT

**Know your studio. Move it anywhere.**

A free macOS app for producers and DJs that lists every plug-in, music app and piece of studio gear on your Mac, keeps snapshots of your setup over time, and turns a snapshot of your old Mac into a checklist for the new one: what to install, which app installs it, and how it is licensed.

Made by [BAKKIS](https://bakkis.com), DJ and producer from Norway.

- Finds AU, VST3, CLAP, VST and AAX plug-ins, your DAWs and installer apps, audio interfaces and MIDI gear
- Shows what changed since your last snapshot: new plug-ins, updates and anything that disappeared
- New Mac checklist grouped by vendor, with the installer app (Native Access, Waves Central, UA Connect …), the license system (account, iLok, serial) and a download link
- Compare two Macs side by side, for example your studio Mac and your touring laptop: what each one lacks, per vendor
- Checks Ableton Live projects: which plug-ins each set needs, and which are missing on this Mac or on another Mac (for example your touring laptop)
- Flags Intel-only plug-ins (they only load under Rosetta on Apple Silicon) and plug-ins that need a newer macOS, read straight from the files, no online database
- **Read-only**: it never moves, changes or deletes a plug-in, and nothing leaves your Mac

---

## Install

**Requirements:** macOS 13 Ventura or later, Apple Silicon or Intel.

1. Download the latest `BAKKIS-STUDIO-VAULT-x.y.z.zip` from the [Releases page](https://github.com/andreasbakketeig-hub/bakkis-studio-vault/releases).
2. Open the zip (Safari usually unzips it for you) and drag **BAKKIS STUDIO VAULT** into your **Applications** folder.
3. Open it once as described below. You only need to do this the first time.

### First launch of an unsigned app

The app is not signed with an Apple Developer ID yet, so macOS asks you to confirm that you trust it.

**macOS 15 Sequoia and later**

1. Double-click **BAKKIS STUDIO VAULT** in Applications. macOS says it could not verify the app. Click **Done**.
2. Open **System Settings → Privacy & Security**.
3. Scroll down to **Security**. Next to *"BAKKIS STUDIO VAULT" was blocked to protect your Mac*, click **Open Anyway**.
4. Enter your Mac password, then click **Open Anyway** once more.

**macOS 13 Ventura and macOS 14 Sonoma**

1. In Applications, **right-click** (or Control-click) **BAKKIS STUDIO VAULT** and choose **Open**.
2. Click **Open** in the dialog.

After that the app opens normally with a double-click.

**If macOS says the app "is damaged and can't be opened"**, the download was quarantined. Open Terminal and run:

```bash
xattr -dr com.apple.quarantine "/Applications/BAKKIS STUDIO VAULT.app"
```

Then open the app again.

---

## Getting started

1. Click **Scan this Mac**. A full scan takes a few seconds.
2. The scan is saved as a **snapshot**: a record of everything on this Mac on that day.
3. Scan again any time. **My Studio** then shows what changed since the last snapshot.

### Moving to a new Mac

1. On the **old Mac**: open **New Mac → Before you leave the old Mac**. It lists what to do there first: scan and export the snapshot (one `.studiovault` file), and deactivate licenses that are tied to that computer (Waves, iLok activations, Steinberg).
2. Copy that file to the **new Mac** (AirDrop, iCloud Drive or a USB stick).
3. On the new Mac: open the app and choose **Import from another Mac…**, or drag the file into the window.
4. Open **New Mac**. Everything from the old Mac is listed per vendor with what to do: *Open Native Access, sign in and install the missing items*, *Activate in iLok License Manager*, and so on.
5. Install things in any order and press **Scan now** now and then. Items tick themselves off when the scan finds them; tick the rest by hand. **Print or export…** gives you the checklist as a web page or a spreadsheet.

Hardware is on the list too: connect each device and install its driver; it ticks off once the Mac sees it.

---

## The screens

| Screen | What it is for |
|---|---|
| **My Studio** | Counts of plug-ins (per product and format), music apps, hardware and vendors, and what changed since the last snapshot. |
| **Compare** | Two Macs (or two snapshots of one Mac) side by side, grouped by vendor: what is only on A, only on B, or installed in a different version or with other formats. |
| **New Mac** | *On the new Mac*: the checklist built from a snapshot of the old Mac. Filter by missing or done, search, tick, print or export. *Before you leave the old Mac*: export the snapshot and deactivate licenses tied to that computer. |
| **Projects** | Check Ableton Live sets (pick files or a whole folder, or drop `.als` files on the window) against this Mac or another Mac's snapshot: which projects open with every plug-in, which plug-ins are missing across them, and where a project uses a format (AU, VST, VST3) that is not installed. |
| **Inventory** | Every plug-in (one row per product, all formats together), app and device. Filter by type (instrument, effect, MIDI), vendor and format; show in Finder; copy the path; export as CSV. |
| **Snapshots** | Every saved scan of this Mac and the ones you imported from other Macs. Rename, export, compare with this Mac, or move to Trash. |

Press **⌘1–⌘6** to switch screens. Settings (the gear icon) has scanning options, extra plug-in folders, and About.

### What it reads

- Plug-ins in the standard macOS folders (`/Library/Audio/Plug-Ins/…`, `~/Library/Audio/Plug-Ins/…`, Avid's AAX folder) plus any extra folders you add in Settings.
- Version, vendor, type and minimum macOS from each plug-in's `Info.plist` and VST3 `moduleinfo.json`, and the processor (Apple Silicon, Intel or both) from the header of its binary. Plug-ins are never loaded or run.
- Music apps in `/Applications` and `~/Applications`.
- Ableton Live sets you choose in **Projects** (only the list of plug-in devices; projects are never changed).
- Audio, MIDI and USB devices through macOS `system_profiler` and Core MIDI.

---

## Privacy

- The app works entirely on your Mac. It makes no network requests at all.
- Snapshot files are made to be shared: paths are stored as `~/…` without your macOS user name, and the Mac's hardware id is replaced by a one-way hash. No serials, passwords or license keys are ever stored.
- Links (download pages, Follow BAKKIS, Support, Report a problem) open in your browser or mail app.

## Settings and uninstalling

Settings, snapshots and checklist ticks are stored in:

```
~/Library/Application Support/BAKKIS STUDIO VAULT/
```

To uninstall, delete the app from Applications and, if you like, that folder.

---

## Troubleshooting

- **The app won't open**: see [First launch of an unsigned app](#first-launch-of-an-unsigned-app).
- **A plug-in is missing**: if it lives outside the standard folders (for example on an external disk), add that folder in **Settings → Extra plug-in folders** and scan again.
- **Hardware shows 0**: devices only show up while they are connected and switched on.
- **Anything else**: use **Settings → About → Report a problem**. It opens an e-mail with your app and macOS version filled in.

---

## Contact and support

- E-mail: [bakkis@bakkis.com](mailto:bakkis@bakkis.com)
- If the app saves you time, you can [buy me a coffee on Ko-fi](https://ko-fi.com/bakkis) ☕

**Follow BAKKIS**

- Website: [bakkis.com](https://bakkis.com)
- Instagram: [@bakkismusic](https://www.instagram.com/bakkismusic/)
- All streaming links: [songshare.com/artist/z7iy15wo](https://songshare.com/artist/z7iy15wo)

---

## Disclaimer

BAKKIS STUDIO VAULT only reads your Mac: it never moves, changes or deletes plug-ins or apps. Vendor information (installer apps, license systems, download pages) is collected by hand and can be out of date; check with the vendor when in doubt. The app is free software provided **as is, without warranty of any kind** (see the [license](LICENSE)).

## License

The code is free and open source under the [MIT License](LICENSE).

The **BAKKIS** name and logo are not covered by the license and may not be used in other projects or derived apps without permission.

---

## For developers

The app is a Python backend with a plain HTML/CSS/JS frontend shown in a native macOS window ([pywebview](https://pywebview.flowrl.com/), WKWebView). The page calls Python through pywebview's JS bridge; there is no network server apart from pywebview's own local file server.

### Run from source

Use [python.org Python 3.12](https://www.python.org/downloads/macos/) (universal2).

```bash
/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m studio_vault
```

Or double-click `Start BAKKIS Studio Vault.command` (it quits a running copy and starts the newest code).

Set `STUDIO_VAULT_DEBUG=1` to enable the Web Inspector. Set `STUDIO_VAULT_DATA_DIR=/some/folder` to use a separate data folder, for example for testing.

### Tests

```bash
.venv/bin/python -m pytest
```

The tests only use temporary folders and recorded `system_profiler` output. They never read your real plug-in folders.

### Layout

```
studio_vault/
  scanners/      plugins (AU/VST3/CLAP/VST/AAX, type, size cache), apps, audio, MIDI, hardware
  vendors.py     vendor registry: installer app, license system, download page
  snapshot.py    snapshot files (schema v2), import of v1 files, privacy scrubbing
  compare.py     added / removed / updated between two snapshots
  checklist.py   new-Mac checklist per vendor, manual ticks
  report.py      printable HTML checklist, CSV exports
  config.py      data folder and settings
  api.py         backend methods exposed to the page
  app.py         pywebview window, file dialogs, drag and drop, Finder, Trash
  web/           index.html, app.css, app.js
tests/v2/        pytest suite for studio_vault
```

`app/` and `main.py` are the original v1 (CustomTkinter, "Bakkis Studio Manager") and are kept for reference until v2 is released; its tests are in `tests/`. The plan and decisions for v2 are in [PLAN.md](PLAN.md).

The app icon is drawn by `tools/make_icon.py` (writes `assets/icon/icon-1024.png` and `AppIcon.icns`).

Building the `.app` is described in [PACKAGING.md](PACKAGING.md).
