# Packaging BAKKIS STUDIO VAULT for macOS

This builds the v2 app (`studio_vault/`). v1 (`app/`, `main.py`, CustomTkinter) is not packaged.

## What you get

- `dist/BAKKIS STUDIO VAULT.app`: a **universal** app (Apple Silicon and Intel), macOS 13 Ventura or later.
- `dist/BAKKIS-STUDIO-VAULT-<version>.zip`: the file to upload to GitHub Releases (about 17 MB).

Everything is inside the app: Python and pywebview. The window uses the system WebKit, so there is **no Homebrew dependency**. The build script stops with an error if anything links to Homebrew.

User data is never inside the app. It lives in `~/Library/Application Support/BAKKIS STUDIO VAULT/` (settings, snapshots, checklist ticks, plug-in size cache).

## Build

Requirements on the build Mac:

- Xcode Command Line Tools (`xcode-select --install`).
- **python.org Python 3.12** (the "macOS 64-bit universal2 installer"). Its Python is universal, which a universal app needs. The script creates `.venv` from it if `.venv` is missing.

```bash
./build_mac_app.sh
```

The script:

1. installs `requirements.txt` and PyInstaller into `.venv`,
2. builds with `packaging/studio_vault.spec` (version from `studio_vault/__init__.py`, icon from `assets/icon/AppIcon.icns`, bundle id `com.bakkis.studio-vault`),
3. checks that both architectures are present and nothing links to Homebrew,
4. zips the app with `ditto` (keeps the bundle intact for Gatekeeper).

To change the icon: edit and run `tools/make_icon.py`, then rebuild.

## Unsigned builds (default)

Without a Developer ID the app is ad-hoc signed. On first launch macOS asks people to confirm; the steps are in the README ("First launch of an unsigned app"):

- macOS 15 and later: open it once, click **Done**, then **System Settings → Privacy & Security → Open Anyway**.
- macOS 13–14: right-click the app → **Open** → **Open**.

## Signed and notarized builds (needs an Apple Developer account)

One-time setup:

1. Join the Apple Developer Program (Individual is simplest; it shows your own name).
2. In **Xcode → Settings → Accounts → Manage Certificates**, create a **Developer ID Application** certificate.
3. Create an app-specific password at appleid.apple.com, then store notarization credentials in your keychain:
   ```bash
   xcrun notarytool store-credentials bakkis-notary --apple-id you@example.com --team-id YOURTEAMID
   ```

Each release:

```bash
CODESIGN_IDENTITY="Developer ID Application: Your Name (YOURTEAMID)" \
NOTARY_PROFILE="bakkis-notary" \
./build_mac_app.sh
```

The app is signed with the hardened runtime (`packaging/entitlements.plist` allows what a bundled Python needs), sent to Apple for notarization (a few minutes), stapled, and zipped. It then opens with a double-click on any Mac, no warning.

## Releasing

1. Set the version in `studio_vault/__init__.py` (for example `2.0.0`) and commit.
2. Run `./build_mac_app.sh`.
3. Test the app from `dist/`, ideally on a second Mac or a fresh user account without your settings.
4. On GitHub: **Releases → Draft a new release**, tag `v2.0.0`, attach `dist/BAKKIS-STUDIO-VAULT-2.0.0.zip`, and write what is new.
5. Publish it (not as a pre-release). Installed apps see it at their next launch.

### How the in-app update works

At startup the app asks `api.github.com/repos/andreasbakketeig-hub/bakkis-studio-vault/releases/latest` once (Settings › *Check for new versions*). Drafts and pre-releases are ignored. *Update now* then needs:

- an asset named `BAKKIS-STUDIO-VAULT-<version>.zip` (what `build_mac_app.sh` makes); GitHub publishes its SHA-256 and the download is checked against it,
- inside it one `.app` with bundle id `com.bakkis.studio-vault` and `CFBundleShortVersionString` equal to the tag without `v`.

The app is unpacked next to the installed one, swapped in after the app quits (the old one comes back if the swap fails), and reopened. When the app runs from a translocated location (opened straight from Downloads) or a folder it cannot write to, it offers *Download* instead. Test against a local file with `BAKKIS_UPDATE_API=file:///path/release.json`.

## Troubleshooting

- **"App is damaged and can't be opened"**: the download was quarantined. `xattr -dr com.apple.quarantine "/Applications/BAKKIS STUDIO VAULT.app"`, or sign and notarize the build.
- **Blank window**: run the app's executable from Terminal to see errors:
  `"/Applications/BAKKIS STUDIO VAULT.app/Contents/MacOS/BAKKIS STUDIO VAULT"`. Set `STUDIO_VAULT_DEBUG=1` for the Web Inspector.
- **Build fails on a missing module**: add it to `hiddenimports` in `packaging/studio_vault.spec`.
