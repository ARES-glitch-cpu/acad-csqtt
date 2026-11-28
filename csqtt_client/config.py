"""Application identity and per-user configuration paths."""
import os
from pathlib import Path
import subprocess
import sys

APP_NAME = "CSQTT"
ROOT = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
if os.name == "nt":
    CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / APP_NAME
    CONFIG_JSON = CONFIG_DIR / "config.json"
    # Backward-compatible encrypted profile files from previous desktop versions.
    PROFILE = CONFIG_DIR / "profile.dat"
    LEGACY_PROFILE = CONFIG_DIR.parent / "CSQTT-Kolenka" / "profile.dat"
else:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    CONFIG_DIR = config_home / APP_NAME
    CONFIG_JSON = CONFIG_DIR / "config.json"
    # Existing Linux versions used profile.json and profile-legacy.json.
    PROFILE = CONFIG_DIR / "profile.json"
    LEGACY_PROFILE = CONFIG_DIR / "profile-legacy.json"

CORE_FILENAME = "csqtt-core.exe" if os.name == "nt" else "csqtt-core"
HELPER_FILENAME = "packet-proxy.exe" if os.name == "nt" else "packet-proxy"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
