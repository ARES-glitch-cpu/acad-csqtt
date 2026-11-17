"""Convert the supplied PNG to a multi-resolution Windows ICO."""
from pathlib import Path

from PIL import Image

icons = Path(__file__).resolve().parents[1] / "assets/icons"
with Image.open(icons / "CS_logo.png") as source:
    source.convert("RGBA").save(icons / "CSQTT.ico", format="ICO",
                               sizes=[(n, n) for n in (16, 20, 24, 32, 40, 48, 64, 128, 256)])
