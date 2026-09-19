"""The few things the launcher and bridge do differently on macOS and Windows.

- Single-instance lock: fcntl.flock on POSIX, msvcrt.locking on Windows.
- Child-process cleanup on quit: `pgrep -P` on POSIX; on Windows the process
  table (Toolhelp32 snapshot, stdlib ctypes) and `taskkill /T /F` per child so
  LibreOffice's soffice.exe -> soffice.bin tree goes too.
- Relaunch after "Restart to apply".
- Opening / revealing files and links (Finder vs Explorer).
- The Microsoft Edge WebView2 runtime check and native message boxes.

macOS behaviour is exactly what launcher.py/bridge.py did before this module.
"""

import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

# Spawned helpers (taskkill, explorer) must not flash a console window from a
# windowed (console=False) app.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Names shown to the user for the OS secret store and file browser.
SECRET_STORE_LABEL = "Credential Manager" if IS_WINDOWS else "Keychain"
FILE_BROWSER_LABEL = "Explorer" if IS_WINDOWS else "Finder"

WEBVIEW2_DOWNLOAD_PAGE = "https://developer.microsoft.com/microsoft-edge/webview2/"
# The Evergreen WebView2 runtime's client key (same GUID for every install).
_WEBVIEW2_CLIENT = r"Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


# --- single instance -------------------------------------------------------


class InstanceLock:
    """Held for the life of the app; close() releases it."""

    def __init__(self, handle):
        self._handle = handle

    def close(self) -> None:
        if self._handle is None:
            return
        if IS_WINDOWS:
            import msvcrt

            try:
                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        self._handle.close()
        self._handle = None


def acquire_single_instance_lock(lock_path: Path) -> InstanceLock | None:
    """Two copies would share one SQLite file and both run backup schedulers.
    Returns None when another copy already holds the lock."""
    if IS_WINDOWS:
        import msvcrt

        try:
            # "a+" never truncates, so opening can't disturb the holder's lock.
            handle = open(lock_path, "a+")  # noqa: SIM115 — held for the app's lifetime
        except OSError:
            return None
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            handle.close()
            return None
        return InstanceLock(handle)

    import fcntl

    handle = open(lock_path, "w")  # noqa: SIM115 — held for the app's lifetime
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return InstanceLock(handle)


# --- child processes -------------------------------------------------------

# WebView2's own browser processes are children of the app on Windows; they
# exit by themselves once the window is gone and must be left to flush
# localStorage, so quit cleanup never kills them.
_WINDOWS_KEEP_CHILDREN = {"msedgewebview2.exe"}


def _windows_process_table() -> list[tuple[int, int, str]]:
    """(pid, parent pid, exe name) for every process, via Toolhelp32."""
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if not snapshot or snapshot == ctypes.c_void_p(-1).value:
        return []
    table: list[tuple[int, int, str]] = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            table.append((entry.th32ProcessID, entry.th32ParentProcessID, entry.szExeFile))
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return table


def _windows_creation_time(pid: int) -> int | None:
    """Process start time (FILETIME ticks), or None if it can't be read."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel32.GetProcessTimes(handle, *[ctypes.byref(t) for t in times]):
            return None
        created = times[0]
        return (created.dwHighDateTime << 32) | created.dwLowDateTime
    finally:
        kernel32.CloseHandle(handle)


def child_pids(parent: int | None = None) -> list[int]:
    """Direct children of `parent` (default: this process)."""
    parent = os.getpid() if parent is None else parent
    if IS_WINDOWS:
        # Windows reuses PIDs and never re-parents orphans, so a process whose
        # parent PID merely *equals* ours may predate us: keep only processes
        # started after this one.
        own_start = _windows_creation_time(parent)
        pids = []
        for pid, ppid, exe in _windows_process_table():
            if ppid != parent or pid == parent or exe.lower() in _WINDOWS_KEEP_CHILDREN:
                continue
            started = _windows_creation_time(pid)
            if own_start is not None and started is not None and started < own_start:
                continue
            pids.append(pid)
        return pids
    try:
        out = subprocess.run(["pgrep", "-P", str(parent)], capture_output=True, text=True, timeout=5, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [int(p) for p in out.split() if p.strip().isdigit()]


def terminate_child_processes(timeout: float = 5.0) -> int:
    """LibreOffice (recalc / memo PDF) runs as a child via subprocess.run; a
    conversion still in flight at quit would otherwise outlive the app.
    Returns how many children were stopped."""
    pids = child_pids()
    if IS_WINDOWS:
        for pid in pids:
            try:
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(pid)],
                    capture_output=True,
                    check=False,
                    timeout=timeout,
                    creationflags=_NO_WINDOW,
                )
            except (OSError, subprocess.SubprocessError):
                pass
        return len(pids)

    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + timeout
    for pid in pids:
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    return len(pids)


# --- relaunch --------------------------------------------------------------


def relaunch_command(launcher_script: Path) -> list[str]:
    if getattr(sys, "frozen", False):
        if IS_WINDOWS:
            return [sys.executable]
        # Contents/MacOS/<exe> -> the .app bundle; `open -n` starts a new instance.
        app_bundle = Path(sys.executable).resolve().parents[2]
        return ["/usr/bin/open", "-n", str(app_bundle)]
    return [sys.executable, str(launcher_script)]


def relaunch(launcher_script: Path) -> None:
    """Settings > "Restart to apply": start a fresh copy after this one exits.
    Detached so it survives this process exiting; the single-instance lock
    is already released by the time the new copy tries to take it."""
    cmd = relaunch_command(launcher_script)
    if IS_WINDOWS:
        env = dict(os.environ)
        # PyInstaller: the new copy is an independent instance, not a child
        # that should inherit this one's unpacked-bundle environment.
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        subprocess.Popen(cmd, env=env, creationflags=flags, close_fds=True)
        return
    subprocess.Popen(cmd, start_new_session=True)


# --- files and links ---------------------------------------------------------


def reveal_in_file_browser(path: str) -> None:
    """Show the file selected in Finder / Explorer."""
    if IS_WINDOWS:
        # A string command line: explorer wants /select,"path" verbatim.
        subprocess.run(f'explorer /select,"{path}"', check=False)
        return
    subprocess.run(["/usr/bin/open", "-R", path], check=False)


def open_with_default_app(target: str) -> None:
    """Open a file in its default app, or an https URL in the browser."""
    if IS_WINDOWS:
        try:
            os.startfile(target)  # type: ignore[attr-defined]  # Windows only
        except OSError:
            log.exception("Couldn't open %s", target)
        return
    subprocess.run(["/usr/bin/open", target], check=False)


# --- Windows: WebView2 runtime + message boxes ------------------------------


def webview2_version(read_value=None) -> str | None:
    """The installed Evergreen WebView2 runtime version, or None if missing.
    Checks the per-machine key (32-bit view on 64-bit Windows, then native)
    and the per-user key, as Microsoft documents."""
    if read_value is None:
        read_value = _read_registry_value
    for hive, key in (
        ("HKLM", r"SOFTWARE\WOW6432Node" + "\\" + _WEBVIEW2_CLIENT),
        ("HKLM", r"SOFTWARE" + "\\" + _WEBVIEW2_CLIENT),
        ("HKCU", r"Software" + "\\" + _WEBVIEW2_CLIENT),
    ):
        value = read_value(hive, key, "pv")
        if value and value != "0.0.0.0":
            return str(value)
    return None


def _read_registry_value(hive: str, key: str, name: str) -> str | None:
    import winreg

    root = winreg.HKEY_LOCAL_MACHINE if hive == "HKLM" else winreg.HKEY_CURRENT_USER
    try:
        with winreg.OpenKey(root, key) as handle:
            value, _type = winreg.QueryValueEx(handle, name)
            return str(value)
    except OSError:
        return None


MB_OK = 0x0
MB_YESNO = 0x4
MB_ICONERROR = 0x10
MB_ICONWARNING = 0x30
MB_ICONINFORMATION = 0x40
IDYES = 6


def message_box(text: str, title: str, flags: int = MB_OK | MB_ICONINFORMATION) -> int:
    """Native Windows message box (no window toolkit needed). Returns the
    button pressed (IDYES, ...), or 0 when not on Windows."""
    if not IS_WINDOWS:
        return 0
    import ctypes

    return int(ctypes.windll.user32.MessageBoxW(None, text, title, flags | 0x10000))  # MB_SETFOREGROUND


def ensure_webview2(app_name: str, read_value=None, ask=message_box, open_url=open_with_default_app) -> bool:
    """True when the window can open. Otherwise explains, offers the
    download page, and returns False (the launcher then exits quietly)."""
    if not IS_WINDOWS and read_value is None:
        return True
    version = webview2_version(read_value)
    if version:
        log.info("WebView2 runtime %s", version)
        return True
    log.error("Microsoft Edge WebView2 runtime not found")
    answer = ask(
        f"{app_name} shows its window with the Microsoft Edge WebView2 Runtime, "
        "which isn't installed on this PC.\n\n"
        "It's a free, small download from Microsoft (most PCs already have it). "
        "Choose the \"Evergreen Bootstrapper\" on the page, run it, then open "
        f"{app_name} again.\n\nOpen the download page now?",
        f"{app_name} needs WebView2",
        MB_YESNO | MB_ICONWARNING,
    )
    if answer == IDYES:
        open_url(WEBVIEW2_DOWNLOAD_PAGE)
    return False
