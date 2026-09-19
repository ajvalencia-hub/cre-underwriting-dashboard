# PyInstaller spec for the desktop app, macOS and Windows. Build with
# desktop/build_mac.sh or desktop/build_windows.ps1, which build the frontend
# first. Output:
#   macOS:   desktop/dist/CRE Underwriting.app
#   Windows: desktop/dist/CRE Underwriting/CRE Underwriting.exe (+ _internal/)
#
# onedir (not onefile): onefile unpacks to a temp dir on every launch, which
# costs seconds of startup and re-extracts ~200 MB each time.

import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

DESKTOP = Path(SPECPATH)
# One version, bumped in cre_desktop/version.py (the update check reads it).
VERSION = re.search(r'^VERSION = "([^"]+)"', (DESKTOP / "cre_desktop" / "version.py").read_text(), re.M).group(1)
REPO = DESKTOP.parent
BACKEND = REPO / "backend"
FRONTEND_DIST = REPO / "frontend" / "dist"
IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

if not (FRONTEND_DIST / "index.html").exists():
    raise SystemExit("frontend/dist is missing — run `npm run build` in frontend/ first.")

datas = [
    # Loaded by path from app/config.py, memo_service.py, goal_seek.py.
    (str(BACKEND / "app" / "data"), "app/data"),
    # Served by FastAPI (CRE_FRONTEND_DIST).
    (str(FRONTEND_DIST), "frontend_dist"),
    # Sample deal for `--self-test`.
    (str(BACKEND / "tests" / "fixtures" / "analytic_acquisition.json"), "selftest"),
]
# Template/font/resource files these libraries open by path.
for package in ("docx", "pptx", "reportlab", "pdfminer"):
    datas += collect_data_files(package)

hiddenimports = (
    # The backend is imported inside launcher.boot() after the environment
    # is prepared, so collect it explicitly.
    collect_submodules("app")
    + [
        "uvicorn.loops.asyncio",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.lifespan.on",
    ]
)
if IS_MAC:
    hiddenimports += ["keyring.backends.macOS", "webview.platforms.cocoa"]
if IS_WINDOWS:
    # pywebview picks its GUI backend by name at runtime; WinForms hosts the
    # Edge WebView2 control through pythonnet (clr / clr_loader). pywebview's
    # own hook bundles the WebView2 .NET assemblies from webview/lib.
    hiddenimports += [
        "keyring.backends.Windows",
        "webview.platforms.winforms",
        "webview.platforms.edgechromium",
        "clr",
        "clr_loader",
        "pythonnet",
    ]
    datas += collect_data_files("clr_loader")
    datas += collect_data_files("pythonnet")

a = Analysis(
    [str(DESKTOP / "launcher.py")],
    pathex=[str(DESKTOP), str(BACKEND)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=[
        "pytest",
        "_pytest",
        "tkinter",
        "IPython",
        # uvicorn[standard] extras: the launcher pins loop=asyncio, http=h11.
        "uvloop",
        "httptools",
        "watchfiles",
    ],
    noarchive=False,
    # python-docx opens templates via "<pkg>/parts/../templates/…", which
    # needs the docx/parts directory to exist on disk — keep its .py files
    # alongside the archived copy.
    module_collection_mode={"docx": "pyz+py"},
)
pyz = PYZ(a.pure)

def windows_version_info():
    """Explorer's Properties > Details (and the installer) read this."""
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    numbers = tuple((list(int(p) for p in VERSION.split(".")) + [0, 0, 0, 0])[:4])
    strings = {
        "CompanyName": "CRE Underwriting",
        "FileDescription": "CRE Underwriting",
        "FileVersion": VERSION,
        "InternalName": "CRE Underwriting",
        "LegalCopyright": "CRE Underwriting",
        "OriginalFilename": "CRE Underwriting.exe",
        "ProductName": "CRE Underwriting",
        "ProductVersion": VERSION,
    }
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=numbers, prodvers=numbers, mask=0x3F, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
        kids=[
            StringFileInfo([StringTable("040904B0", [StringStruct(k, v) for k, v in strings.items()])]),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ],
    )


WINDOWS_ICON = DESKTOP / "assets" / "AppIcon.ico"

if IS_WINDOWS:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="CRE Underwriting",
        console=False,  # windowed: no console window behind the app
        icon=str(WINDOWS_ICON) if WINDOWS_ICON.exists() else None,
        version=windows_version_info(),
        uac_admin=False,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="CRE Underwriting",
        console=False,
        argv_emulation=False,
    )
coll = COLLECT(exe, a.binaries, a.datas, name="CRE Underwriting")

if IS_MAC:
    app = BUNDLE(
        coll,
        name="CRE Underwriting.app",
        icon=str(DESKTOP / "assets" / "AppIcon.icns") if (DESKTOP / "assets" / "AppIcon.icns").exists() else None,
        bundle_identifier="com.cre-underwriting.desktop",
        info_plist={
            "CFBundleDisplayName": "CRE Underwriting",
            "CFBundleShortVersionString": VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
            # The app talks only to its own 127.0.0.1 server plus the public-data
            # APIs over HTTPS; no ATS exceptions needed beyond local networking.
            "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
        },
    )
