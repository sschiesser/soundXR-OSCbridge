# PyInstaller spec — one app for Windows, macOS and Linux.
#   pyinstaller packaging/soundxr_bridge.spec --noconfirm --clean
#
# The interface is served over HTTP and opened in the default browser, so no
# Qt, no webview and no system browser engine is bundled. NiceGUI's static
# assets do have to be collected, or the page loads blank.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parent
NAME = "SoundxR-OSC-Bridge"

# the single source of truth, so the .app bundle version always matches the
# number the app itself prints
sys.path.insert(0, str(ROOT))
from soundxr_bridge import __version__ as VERSION  # noqa: E402

nicegui_datas, nicegui_binaries, nicegui_hidden = collect_all("nicegui")

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT)],
    datas=nicegui_datas + [
        (str(ROOT / "soundxr_bridge" / "targets.json"), "soundxr_bridge"),
    ],
    binaries=nicegui_binaries,
    hiddenimports=nicegui_hidden + [
        "pythonosc",
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
    ],
    excludes=[
        "PySide6", "PyQt5", "PyQt6", "tkinter", "matplotlib", "numpy",
        "pandas", "selenium", "webview", "IPython",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name=NAME,
    # a console is useful on Windows and Linux: it prints the URL to open and
    # any bind error. The macOS .app has no console, so it is windowed there.
    console=sys.platform != "darwin",
    disable_windowed_traceback=False,
    icon=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=NAME)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{NAME}.app",
        bundle_identifier="ch.zhdk.iaspace.soundxroscbridge",
        version=VERSION,
        info_plist={
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            # macOS 15+ asks before an app may use the local network; without
            # this key the OSC sockets are silently blocked.
            "NSLocalNetworkUsageDescription":
                "The bridge receives and sends OSC on your local network.",
            "NSBonjourServices": ["_osc._udp"],
        },
    )
