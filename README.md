# Bakkis Studio Manager

A macOS desktop app for managing your professional studio setup — built with Python and CustomTkinter.

## Features

| Module | Status |
|--------|--------|
| Plug-in Scanner | ✅ Available |
| License Manager | 🔜 Coming soon |
| Hardware Inventory | ✅ Available (connected device scan) |
| MIDI Devices | 🔜 Coming soon |
| Studio Mapper | 🔜 Coming soon |

## Plug-in Scanner

Scans standard macOS plug-in directories for:

- **VST** — `.vst`
- **VST3** — `.vst3`
- **AU (AudioUnit)** — `.component`
- **AAX** — `.aaxplugin`

Results are shown in a searchable table. Export any result set to CSV with one click.

### Scanned paths

```
/Library/Audio/Plug-Ins/VST
/Library/Audio/Plug-Ins/VST3
/Library/Audio/Plug-Ins/Components
/Library/Application Support/Avid/Audio/Plug-Ins
~/Library/Audio/Plug-Ins/VST
~/Library/Audio/Plug-Ins/VST3
~/Library/Audio/Plug-Ins/Components
```

## Setup

```bash
# 1. Create a virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the app
python main.py
```

## Project structure

```
bakkis-studio-manager/
├── main.py                     # Entry point
├── requirements.txt
├── app/
│   ├── core/
│   │   ├── scanner.py          # Plug-in discovery logic
│   │   └── exporter.py         # CSV export
│   ├── ui/
│   │   ├── sidebar.py          # Navigation rail
│   │   ├── main_window.py      # Root window & view router
│   │   └── views/
│   │       ├── plugin_scanner.py   # Plug-in Scanner module
│   │       └── coming_soon.py      # Placeholder for future modules
│   └── utils/
│       └── helpers.py
```

## Requirements

- macOS 12+
- Python 3.10+
- CustomTkinter 5.2+
