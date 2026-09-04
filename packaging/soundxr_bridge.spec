# PyInstaller spec — builds the same app on Windows, macOS and Linux.
#   pyinstaller packaging/soundxr_bridge.spec --noconfirm
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
NAME = "SoundxR-OSC-Bridge"

a = Analysis(
    [str(ROOT / "run_app.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "soundxr_bridge" / "targets.json"), "soundxr_bridge")],
    hiddenimports=["pythonosc"],
    excludes=[
        # Qt ships a lot we never touch; dropping it keeps the binary sane
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQuick",
        "PySide6.QtQml", "PySide6.Qt3DCore", "PySide6.QtMultimedia",
        "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtBluetooth",
        "PySide6.QtPdf", "PySide6.QtDesigner", "tkinter", "matplotlib", "numpy",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name=NAME,
    console=False,          # windowed app; the log pane shows what it is doing
    disable_windowed_traceback=False,
    icon=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=NAME)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{NAME}.app",
        bundle_identifier="ch.zhdk.iaspace.soundxroscbridge",
        info_plist={
            "CFBundleShortVersionString": "1.4.0",
            "NSHighResolutionCapable": True,
            # macOS 15+ asks the user before an app may talk on the local network;
            # without this key the OSC sockets are silently blocked.
            "NSLocalNetworkUsageDescription":
                "The bridge receives and sends OSC on your local network.",
        },
    )
