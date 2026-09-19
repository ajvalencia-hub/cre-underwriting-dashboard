"""Update check against GitHub Releases (roadmap #31; owner's choice over
Sparkle). It only tells the user a newer version exists and links to the
release page — nothing is downloaded or installed by the app.

The request to api.github.com carries no user data: a User-Agent with the
app's version, nothing else. At launch it runs at most once a day (the
result is cached in desktop-settings.json); Settings has "Check now" and a
switch to turn it off."""

import json
import re
import time
import urllib.error
import urllib.request

from .version import VERSION

REPO = "ajvalencia-hub/cre-underwriting-dashboard"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
CHECK_INTERVAL_S = 24 * 3600
TIMEOUT_S = 6


def parse_version(text: str) -> tuple[int, int, int] | None:
    """'v1.2.3' / '1.2' -> (1, 2, 3) / (1, 2, 0); anything else -> None."""
    match = re.fullmatch(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(text or "").strip())
    if not match:
        return None
    return tuple(int(part or 0) for part in match.groups())  # type: ignore[return-value]


def fetch_latest(opener=urllib.request.urlopen) -> dict | None:
    """The latest published release as {tag, url, zipUrl, publishedAt}, or
    None when the repo has none yet. Raises OSError on network trouble."""
    request = urllib.request.Request(
        LATEST_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": f"CRE-Underwriting/{VERSION}"},
    )
    try:
        with opener(request, timeout=TIMEOUT_S) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    zip_asset = next(
        (a for a in data.get("assets") or [] if str(a.get("name", "")).endswith(".zip")), None
    )
    return {
        "tag": str(data.get("tag_name") or ""),
        "url": str(data.get("html_url") or RELEASES_PAGE),
        "zipUrl": zip_asset.get("browser_download_url") if zip_asset else None,
        "publishedAt": data.get("published_at"),
    }


def check(settings: dict, force: bool = False, now: float | None = None, fetch=fetch_latest) -> tuple[dict, dict]:
    """Returns (result for the UI, settings to save). Skips the network when
    turned off, or (unless forced) when the last check is under a day old."""
    now = time.time() if now is None else now
    enabled = settings.get("checkForUpdates", True) is not False
    base = {"currentVersion": VERSION, "enabled": enabled, "releasesPage": RELEASES_PAGE}
    if not enabled and not force:
        return {**base, "status": "off"}, settings
    cached = settings.get("lastUpdateCheck") or {}
    if not force and now - float(cached.get("at") or 0) < CHECK_INTERVAL_S and "latest" in cached:
        return _result(base, cached["latest"], cached["at"]), settings
    try:
        latest = fetch()
    except (OSError, ValueError) as exc:
        return {**base, "status": "error", "error": f"Couldn't reach GitHub: {exc}"}, settings
    saved = {**settings, "lastUpdateCheck": {"at": now, "latest": latest}}
    return _result(base, latest, now), saved


def _result(base: dict, latest: dict | None, checked_at: float) -> dict:
    out = {**base, "checkedAt": checked_at}
    if latest is None:
        return {**out, "status": "noReleases"}
    current, newest = parse_version(VERSION), parse_version(latest.get("tag", ""))
    if current is None or newest is None:
        return {**out, "status": "unknown", "latest": latest}
    return {**out, "status": "available" if newest > current else "current", "latest": latest}
