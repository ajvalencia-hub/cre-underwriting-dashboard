# PyInstaller spec for the macOS app. Build with desktop/build_mac.sh, which
# builds the frontend first. Output: desktop/dist/CRE Underwriting.app
#
# onedir (not onefile): onefile unpacks to a temp dir on every launch, which
# costs seconds of startup and re-extracts ~200 MB each time.

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

DESKTOP = Path(SPECPATH)
REPO = DESKTOP.parent
BACKEND = REPO / "backend"
FRONTEND_DIST = REPO / "frontend" / "dist"

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
        "keyring.backends.macOS",
        "webview.platforms.cocoa",
    ]
)

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

app = BUNDLE(
    coll,
    name="CRE Underwriting.app",
    icon=str(DESKTOP / "assets" / "AppIcon.icns") if (DESKTOP / "assets" / "AppIcon.icns").exists() else None,
    bundle_identifier="com.cre-underwriting.desktop",
    info_plist={
        "CFBundleDisplayName": "CRE Underwriting",
        "CFBundleShortVersionString": "1.0.0",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "12.0",
        # The app talks only to its own 127.0.0.1 server plus the public-data
        # APIs over HTTPS; no ATS exceptions needed beyond local networking.
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
    },
)
