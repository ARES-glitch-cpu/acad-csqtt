"""Application identity and paths shared by source and portable builds."""
import os
from pathlib import Path
import subprocess
import sys

APP_NAME = "CSQTT"
ROOT = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
APP_VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
ASSETS = ROOT / "assets"
if os.name == "nt":
    PROFILE = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / APP_NAME / "profile.dat"
    LEGACY_PROFILE = PROFILE.parent.parent / "CSQTT-Kolenka" / "profile.dat"
else:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    PROFILE = config_home / APP_NAME / "profile.json"
    LEGACY_PROFILE = PROFILE.with_name("profile-legacy.json")

CORE_FILENAME = "csqtt-core.exe" if os.name == "nt" else "csqtt-core"
HELPER_FILENAME = "packet-proxy.exe" if os.name == "nt" else "packet-proxy"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
