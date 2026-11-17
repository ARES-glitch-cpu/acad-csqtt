"""Palette, typography, and reusable rounded surfaces."""
from functools import lru_cache
from PIL import Image, ImageDraw

BG = "#141517"
PANEL = "#1c1e21"
FIELD = "#25272c"
DEEP = "#181a1d"
TEXT = "#eeeef0"
MUTED = "#9b9da5"
DIM = "#81848e"
LINE = "#37393f"
SOFT = "#2b2d32"
PRIMARY = "#e0e1e5"
MINT = "#79c9a4"
AMBER = "#dab877"
RED = "#df9499"
HEADER = "#18191c"


def ui_font(size=10, bold=False):
    # Windows exposes the bundled 600 face as a separate family. Do not synthesize 700.
    return ("Nunito Sans SemiBold" if bold else "Nunito Sans", size, "normal")


@lru_cache(maxsize=64)
def surface_tile(radius, fill, outline, background):
    size, aa = radius * 2 + 4, 4
    image = Image.new("RGB", (size * aa, size * aa), background)
    ImageDraw.Draw(image).rounded_rectangle((0, 0, size*aa-1, size*aa-1),
        radius=radius*aa, fill=fill, outline=outline, width=aa)
    return image.resize((size, size), Image.Resampling.LANCZOS)


def rounded_surface(width, height, radius, fill=PANEL, outline=SOFT, background=BG):
    radius = max(1, min(radius, width // 2, height // 2))
    tile = surface_tile(radius, fill, outline, background)
    end = tile.width
    image = Image.new("RGB", (width, height), fill)
    drawing = ImageDraw.Draw(image)
    drawing.line((radius, 0, width-radius-1, 0), fill=outline)
    drawing.line((radius, height-1, width-radius-1, height-1), fill=outline)
    drawing.line((0, radius, 0, height-radius-1), fill=outline)
    drawing.line((width-1, radius, width-1, height-radius-1), fill=outline)
    for source, target in (((0, 0, radius, radius), (0, 0)),
                           ((end-radius, 0, end, radius), (width-radius, 0)),
                           ((0, end-radius, radius, end), (0, height-radius)),
                           ((end-radius, end-radius, end, end), (width-radius, height-radius))):
        image.paste(tile.crop(source), target)
    return image
