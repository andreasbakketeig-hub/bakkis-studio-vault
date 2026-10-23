"""
Static vendor registry — maps plug-in and app developers to how you get their
software back on a new Mac: the installer/manager app, the license system and
the download page.

Read-only reference data; never opens network connections. When in doubt a
vendor's license system is left as UNKNOWN rather than guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Protocol

# ── License systems ───────────────────────────────────────────────────────────

LICENSE_ACCOUNT = "Vendor account"      # sign in to the vendor's app or site
LICENSE_ILOK = "iLok"                   # iLok License Manager / iLok Cloud
LICENSE_SERIAL = "Serial or license file"
LICENSE_APP_STORE = "Mac App Store"
LICENSE_UNKNOWN = "Unknown"


@dataclass(frozen=True)
class Vendor:
    key: str
    name: str
    developer_patterns: tuple[str, ...]   # matched against plug-in/app developer
    bundle_prefixes: tuple[str, ...]      # matched against CFBundleIdentifier
    manager_app: str                      # "" = download from the website
    manager_hints: tuple[str, ...]        # substrings of installed app names
    license_system: str
    download_url: str

    @property
    def website_only(self) -> bool:
        return not self.manager_app


def _v(key, name, patterns, prefixes, manager, hints, license_system, url) -> Vendor:
    return Vendor(key, name, tuple(patterns), tuple(prefixes), manager, tuple(hints), license_system, url)


VENDORS: tuple[Vendor, ...] = (
    _v("native_instruments", "Native Instruments", ["native instruments"], ["com.native-instruments."],
       "Native Access", ["native access"], LICENSE_ACCOUNT, "https://www.native-instruments.com/en/specials/native-access/"),
    _v("izotope", "iZotope", ["izotope"], ["com.izotope."],
       "Native Access", ["native access", "izotope product portal"], LICENSE_ACCOUNT, "https://www.izotope.com/"),
    _v("waves", "Waves", ["waves audio", "wavesaudio", "waves"], ["com.waves.", "com.wavesaudio."],
       "Waves Central", ["waves central"], LICENSE_ACCOUNT, "https://www.waves.com/downloads/central"),
    _v("arturia", "Arturia", ["arturia"], ["com.arturia."],
       "Arturia Software Center", ["arturia software center"], LICENSE_ACCOUNT, "https://www.arturia.com/support/downloads-manuals"),
    _v("plugin_alliance", "Plugin Alliance", ["plugin alliance", "brainworx"], ["com.plugin-alliance.", "com.brainworx."],
       "Plugin Alliance Installation Manager", ["plugin alliance"], LICENSE_ACCOUNT, "https://www.plugin-alliance.com/"),
    _v("universal_audio", "Universal Audio", ["universal audio", "uaudio"], ["com.uaudio."],
       "UA Connect", ["ua connect"], LICENSE_ACCOUNT, "https://www.uaudio.com/downloads"),
    _v("ssl", "Solid State Logic", ["solid state logic"], ["com.solidstatelogic.", "com.ssl."],
       "SSL 360", ["ssl 360"], LICENSE_ACCOUNT, "https://www.solidstatelogic.com/support/downloads"),
    _v("softube", "Softube", ["softube"], ["com.softube."],
       "Softube Central", ["softube central"], LICENSE_ACCOUNT, "https://www.softube.com/softube-central"),
    _v("output", "Output", ["^output$", "output inc", "output, inc", "output llc"], ["com.output."],
       "Output Hub", ["output hub"], LICENSE_ACCOUNT, "https://output.com/"),
    _v("spitfire", "Spitfire Audio", ["spitfire audio", "spitfire"], ["com.spitfireaudio."],
       "Spitfire Audio", ["spitfire audio"], LICENSE_ACCOUNT, "https://www.spitfireaudio.com/"),
    _v("loopcloud", "Loopcloud", ["loopmasters", "loopcloud"], ["com.loopmasters.", "com.loopcloud."],
       "Loopcloud", ["loopcloud"], LICENSE_ACCOUNT, "https://www.loopcloud.com/"),
    _v("steinberg", "Steinberg", ["steinberg"], ["com.steinberg."],
       "Steinberg Download Assistant", ["steinberg download assistant", "steinberg activation manager"],
       LICENSE_ACCOUNT, "https://www.steinberg.net/"),
    _v("soundtoys", "Soundtoys", ["soundtoys"], ["com.soundtoys."],
       "", [], LICENSE_ILOK, "https://www.soundtoys.com/"),
    _v("avid", "Avid", ["avid technology", "avid"], ["com.avid."],
       "Avid Link", ["avid link"], LICENSE_ILOK, "https://www.avid.com/"),
    _v("eventide", "Eventide", ["eventide"], ["com.eventide."],
       "", [], LICENSE_ILOK, "https://www.eventideaudio.com/"),
    _v("toontrack", "Toontrack", ["toontrack"], ["com.toontrack."],
       "Toontrack Product Manager", ["toontrack product manager"], LICENSE_ACCOUNT, "https://www.toontrack.com/"),
    _v("xln", "XLN Audio", ["xln audio", "xlnaudio"], ["com.xlnaudio."],
       "XLN Online Installer", ["xln online installer"], LICENSE_ACCOUNT, "https://www.xlnaudio.com/"),
    _v("ik", "IK Multimedia", ["ik multimedia"], ["com.ikmultimedia."],
       "IK Product Manager", ["ik product manager"], LICENSE_ACCOUNT, "https://www.ikmultimedia.com/"),
    _v("roland", "Roland", ["roland"], ["com.roland."],
       "Roland Cloud Manager", ["roland cloud manager"], LICENSE_ACCOUNT, "https://www.rolandcloud.com/"),
    _v("kilohearts", "Kilohearts", ["kilohearts"], ["com.kilohearts."],
       "Kilohearts Installer", ["kilohearts installer"], LICENSE_ACCOUNT, "https://kilohearts.com/"),
    _v("fabfilter", "FabFilter", ["fabfilter"], ["com.fabfilter."],
       "", [], LICENSE_SERIAL, "https://www.fabfilter.com/download"),
    _v("valhalla", "Valhalla DSP", ["valhalla dsp", "valhalla"], ["com.valhalladsp."],
       "", [], LICENSE_SERIAL, "https://valhalladsp.com/"),
    _v("xfer", "Xfer Records", ["xfer records", "xfer"], ["com.xferrecords."],
       "", [], LICENSE_SERIAL, "https://xferrecords.com/"),
    _v("uhe", "u-he", ["u-he", "u he"], ["com.u-he."],
       "", [], LICENSE_SERIAL, "https://u-he.com/"),
    _v("spectrasonics", "Spectrasonics", ["spectrasonics"], ["com.spectrasonics."],
       "", [], LICENSE_ACCOUNT, "https://www.spectrasonics.net/"),
    _v("ableton", "Ableton", ["ableton"], ["com.ableton."],
       "", [], LICENSE_ACCOUNT, "https://www.ableton.com/en/account/"),
    _v("celemony", "Celemony", ["celemony"], ["com.celemony."],
       "", [], LICENSE_ACCOUNT, "https://www.celemony.com/"),
    _v("korg", "Korg", ["korg"], ["com.korg."],
       "", [], LICENSE_ACCOUNT, "https://www.korg.com/us/support/download/"),
    _v("mixed_in_key", "Mixed In Key", ["mixed in key", "mixedinkey"], ["com.mixedinkey."],
       "", [], LICENSE_ACCOUNT, "https://mixedinkey.com/"),
    _v("sonarworks", "Sonarworks", ["sonarworks"], ["com.sonarworks."],
       "SoundID Reference", ["soundid reference"], LICENSE_ACCOUNT, "https://www.sonarworks.com/"),
    _v("antares", "Antares", ["antares"], ["com.antarestech.", "com.antares."],
       "Antares Central", ["antares central"], LICENSE_ACCOUNT, "https://www.antarestech.com/"),
    _v("splice", "Splice", ["splice"], ["com.splice."],
       "Splice", ["splice"], LICENSE_ACCOUNT, "https://splice.com/"),
    _v("ujam", "UJAM", ["ujam"], ["com.ujam."],
       "UJAM App", ["ujam"], LICENSE_ACCOUNT, "https://www.ujam.com/"),
    _v("safari_pedals", "Safari Pedals", ["safari pedals", "safaripedals"], ["com.safaripedals."],
       "", [], LICENSE_UNKNOWN, "https://safaripedals.com/"),
    _v("oeksound", "oeksound", ["oeksound"], ["com.oeksound."],
       "", [], LICENSE_UNKNOWN, "https://oeksound.com/"),
    _v("philspeiser", "Phil Speiser", ["philspeiser", "phil speiser"], ["com.philspeiser.", "com.myphilspeiser."],
       "", [], LICENSE_UNKNOWN, "https://www.philspeiser.com/"),
    _v("apple", "Apple", ["apple"], ["com.apple."],
       "", [], LICENSE_APP_STORE, "https://apps.apple.com/"),
)

_BY_KEY: dict[str, Vendor] = {v.key: v for v in VENDORS}


class NamedApp(Protocol):
    name: str


OTHER_GROUP_KEY = "other"
_COMPANY_SUFFIX = re.compile(r"[\s,]+(inc|llc|ltd|gmbh|ab|bv|as|co|corp|limited)\.?$", re.IGNORECASE)


def developer_group(developer: str) -> tuple[str, str]:
    """(group key, display name) for a developer without a registry entry."""
    name = _COMPANY_SUFFIX.sub("", (developer or "").strip()).strip(" ,.-_")
    key = re.sub(r"[^a-z0-9]+", "", name.lower())
    if not key or not re.search(r"[a-z]", key):   # "", "2024", "2004–2025"
        return OTHER_GROUP_KEY, "Other"
    return f"dev:{key}", name


def vendor_group(developer: str = "", bundle_id: str = "") -> tuple[str, str, Vendor | None]:
    """(group key, display name, registry entry or None) used to group items by vendor."""
    vendor = match_vendor(developer, bundle_id)
    if vendor is not None:
        return vendor.key, vendor.name, vendor
    key, name = developer_group(developer)
    return key, name, None


# ── Matching ──────────────────────────────────────────────────────────────────

def _pattern_matches(pattern: str, developer: str) -> bool:
    """
    Multi-word patterns use phrase containment, ^...$ patterns are regexes,
    single words must match as a whole word (not inside another word).
    """
    pat = pattern.strip().lower()
    dev = developer.strip().lower()
    if not pat or not dev:
        return False
    if pat.startswith("^") and pat.endswith("$"):
        return bool(re.search(pat, dev))
    if " " in pat or "-" in pat:
        return pat in dev
    return bool(re.search(rf"\b{re.escape(pat)}\b", dev))


def match_vendor(developer: str = "", bundle_id: str = "") -> Vendor | None:
    """Return the vendor for a plug-in/app by bundle id first, then developer name."""
    bid = (bundle_id or "").strip().lower()
    if bid:
        for vendor in VENDORS:
            if any(bid.startswith(prefix) for prefix in vendor.bundle_prefixes):
                return vendor
    dev = (developer or "").strip()
    if dev:
        for vendor in VENDORS:
            if any(_pattern_matches(p, dev) for p in vendor.developer_patterns):
                return vendor
    return None


def vendor_by_key(key: str) -> Vendor | None:
    return _BY_KEY.get(key)


def installed_manager(vendor: Vendor, apps: Iterable[NamedApp]) -> str:
    """Name of the installed manager app for *vendor*, or "" when not installed."""
    if not vendor.manager_hints:
        return ""
    for app in apps:
        name = app.name.lower()
        if any(hint in name for hint in vendor.manager_hints):
            return app.name
    return ""
