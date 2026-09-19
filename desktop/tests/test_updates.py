"""Roadmap #31: the GitHub Releases update check (no network in tests)."""

import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cre_desktop import updates  # noqa: E402

RELEASE = {"tag": "v9.0.0", "url": "https://github.com/x/releases/tag/v9.0.0", "zipUrl": None, "publishedAt": None}


def test_parse_version():
    assert updates.parse_version("v1.2.3") == (1, 2, 3)
    assert updates.parse_version("1.4") == (1, 4, 0)
    assert updates.parse_version("nightly") is None


def test_a_newer_release_is_available_and_cached():
    result, saved = updates.check({}, now=1000, fetch=lambda: RELEASE)
    assert result["status"] == "available"
    assert result["latest"]["tag"] == "v9.0.0"
    assert saved["lastUpdateCheck"]["at"] == 1000


def test_the_same_or_older_release_is_current():
    result, _ = updates.check({}, fetch=lambda: {**RELEASE, "tag": f"v{updates.VERSION}"})
    assert result["status"] == "current"
    result, _ = updates.check({}, fetch=lambda: {**RELEASE, "tag": "v0.1.0"})
    assert result["status"] == "current"


def test_at_most_once_a_day_unless_forced():
    def boom():
        raise AssertionError("should use the cache")

    settings = {"lastUpdateCheck": {"at": 1000, "latest": RELEASE}}
    result, _ = updates.check(settings, now=1000 + 3600, fetch=boom)
    assert result["status"] == "available"
    result, _ = updates.check(settings, now=1000 + 3600, force=True, fetch=lambda: {**RELEASE, "tag": "v0.0.1"})
    assert result["status"] == "current"


def test_turned_off_means_no_request():
    def boom():
        raise AssertionError("no network when off")

    result, _ = updates.check({"checkForUpdates": False}, fetch=boom)
    assert result["status"] == "off"


def test_network_trouble_is_reported_not_raised():
    def offline():
        raise OSError("no route to host")

    result, saved = updates.check({}, fetch=offline)
    assert result["status"] == "error"
    assert "lastUpdateCheck" not in saved


def test_no_releases_yet():
    result, _ = updates.check({}, fetch=lambda: None)
    assert result["status"] == "noReleases"


def test_fetch_reads_the_github_payload_and_sends_no_user_data():
    seen = {}
    payload = {
        "tag_name": "v1.1.0",
        "html_url": "https://github.com/r/releases/tag/v1.1.0",
        "assets": [{"name": "CRE-Underwriting-mac.zip", "browser_download_url": "https://example/zip"}],
    }

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def opener(request, timeout):
        seen["headers"] = dict(request.header_items())
        seen["url"] = request.full_url
        return Response(json.dumps(payload).encode())

    latest = updates.fetch_latest(opener, platform="darwin")
    assert latest == {
        "tag": "v1.1.0",
        "url": payload["html_url"],
        "downloadUrl": "https://example/zip",
        "zipUrl": "https://example/zip",
        "publishedAt": None,
    }
    assert seen["url"] == updates.LATEST_URL
    assert set(seen["headers"]) == {"Accept", "User-agent"}


def test_fetch_treats_404_as_no_releases():
    def opener(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    assert updates.fetch_latest(opener) is None


@pytest.mark.parametrize("tag", ["v1.0.1", "1.1", "v2.0.0"])
def test_any_higher_version_counts(tag):
    assert updates.check({}, fetch=lambda: {**RELEASE, "tag": tag})[0]["status"] == "available"


ASSETS = [
    {"name": "CRE-Underwriting-mac.zip", "browser_download_url": "https://example/mac.zip"},
    {"name": "CRE-Underwriting-mac.dmg", "browser_download_url": "https://example/mac.dmg"},
    {"name": "CRE-Underwriting-windows-portable.zip", "browser_download_url": "https://example/win.zip"},
    {"name": "CRE-Underwriting-Setup-1.1.0.exe", "browser_download_url": "https://example/setup.exe"},
]


def _url(asset):
    return asset["browser_download_url"] if asset else None


def test_each_os_gets_its_own_download():
    assert _url(updates.select_asset(ASSETS, "win32")) == "https://example/setup.exe"
    assert _url(updates.select_asset(ASSETS, "darwin")) == "https://example/mac.dmg"
    assert updates.select_asset(ASSETS, "linux") is None


def test_download_fallbacks_when_the_preferred_asset_is_missing():
    no_installer = [a for a in ASSETS if not a["name"].endswith(".exe")]
    assert _url(updates.select_asset(no_installer, "win32")) == "https://example/win.zip"
    no_dmg = [a for a in ASSETS if not a["name"].endswith(".dmg")]
    assert _url(updates.select_asset(no_dmg, "darwin")) == "https://example/mac.zip"
    # A mac-only release offers Windows nothing (the UI links to the release page).
    mac_only = [a for a in ASSETS if "mac" in a["name"]]
    assert updates.select_asset(mac_only, "win32") is None
    # A Windows-only release never hands a Mac the Windows zip.
    win_only = [a for a in ASSETS if "mac" not in a["name"]]
    assert updates.select_asset(win_only, "darwin") is None


def test_fetch_picks_the_windows_installer_on_windows():
    payload = {"tag_name": "v1.1.0", "html_url": "https://github.com/r/releases/tag/v1.1.0", "assets": ASSETS}

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    latest = updates.fetch_latest(lambda request, timeout: Response(json.dumps(payload).encode()), platform="win32")
    assert latest["downloadUrl"] == latest["zipUrl"] == "https://example/setup.exe"
