"""Application identity and paths shared by source and portable builds."""
import os
from pathlib import Path
import subprocess
import sys

APP_NAME = "CSQTT"
ROOT = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
APP_VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
ASSETS = ROOT / "assets"
PROFILE = Path(os.environ.get("LOCALAPPDATA", str(ROOT))) / APP_NAME / "profile.dat"
# Only used to import profiles saved by versions <= 1.3.1.
LEGACY_PROFILE = PROFILE.parent.parent / "CSQTT-Kolenka" / "profile.dat"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
