# PyInstaller spec for BAKKIS STUDIO VAULT v2. Built by ../build_mac_app.sh; see ../PACKAGING.md.
#
# A universal2 (Apple Silicon + Intel) windowed .app. pywebview uses the system WebKit, so no browser
# is bundled. Set CODESIGN_IDENTITY to sign with a Developer ID (hardened runtime).
import os
import re
from pathlib import Path

ROOT = Path(SPECPATH).parent
APP_NAME = "BAKKIS STUDIO VAULT"
VERSION = re.search(r'__version__ = "([^"]+)"', (ROOT / "studio_vault" / "__init__.py").read_text()).group(1)
IDENTITY = os.environ.get("CODESIGN_IDENTITY") or None

a = Analysis(
    [str(ROOT / "studio_vault" / "__main__.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "studio_vault" / "web"), "studio_vault/web"),
           (str(ROOT / "studio_vault" / "finder"), "studio_vault/finder")],
    hiddenimports=["webview.platforms.cocoa"],
    # v1 (app/, CustomTkinter) and dev tools stay out of the bundle.
    excludes=["tkinter", "customtkinter", "PIL", "app", "pytest", "pyflakes", "PyInstaller", "setuptools"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    console=False,
    target_arch="universal2",
    codesign_identity=IDENTITY,
    entitlements_file=str(ROOT / "packaging" / "entitlements.plist") if IDENTITY else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME)
app = BUNDLE(
    coll,
    name=f"{APP_NAME}.app",
    icon=str(ROOT / "assets" / "icon" / "AppIcon.icns"),
    bundle_identifier="com.bakkis.studio-vault",
    version=VERSION,
    info_plist={
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSMinimumSystemVersion": "13.0",
        "LSApplicationCategoryType": "public.app-category.music",
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "© 2026 Andreas Bakketeig (BAKKIS). MIT License.",
        # "Open with" from Finder and drops on the Dock icon: Live Sets and project folders go to Handoff,
        # plug-in lists and snapshots are loaded. The app only reads them.
        "CFBundleDocumentTypes": [
            {"CFBundleTypeName": "Ableton Live Set", "CFBundleTypeRole": "Viewer",
             "CFBundleTypeExtensions": ["als"], "LSHandlerRank": "Alternate"},
            {"CFBundleTypeName": "Folder", "CFBundleTypeRole": "Viewer",
             "LSItemContentTypes": ["public.folder"], "LSHandlerRank": "None"},
            {"CFBundleTypeName": "Studio Vault snapshot", "CFBundleTypeRole": "Editor",
             "LSItemContentTypes": ["com.bakkis.studio-vault.snapshot"], "LSHandlerRank": "Owner"},
            {"CFBundleTypeName": "Handoff plug-in list", "CFBundleTypeRole": "Editor",
             "LSItemContentTypes": ["com.bakkis.studio-vault.handoffplugins"], "LSHandlerRank": "Owner"},
        ],
        "UTExportedTypeDeclarations": [
            {"UTTypeIdentifier": "com.bakkis.studio-vault.snapshot", "UTTypeDescription": "Studio Vault snapshot",
             "UTTypeConformsTo": ["public.json"], "UTTypeTagSpecification": {"public.filename-extension": ["studiovault"]}},
            {"UTTypeIdentifier": "com.bakkis.studio-vault.handoffplugins", "UTTypeDescription": "Handoff plug-in list",
             "UTTypeConformsTo": ["public.json"], "UTTypeTagSpecification": {"public.filename-extension": ["handoffplugins"]}},
        ],
    },
)
