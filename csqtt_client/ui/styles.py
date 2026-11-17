"""ttk styles and state images."""
from tkinter import font as tk_font, ttk
from PIL import Image, ImageDraw, ImageTk

from csqtt_client.ui.theme import (
    BG, PANEL, FIELD, TEXT, MUTED, DIM, LINE, SOFT, PRIMARY, MINT, HEADER, ui_font, surface_tile,
)


def configure_style(root, scale, resources):
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
        tk_font.nametofont(name, root=root).configure(family="Nunito Sans", size=10)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=PANEL, foreground=TEXT, font=ui_font(), bordercolor=LINE)
    style.configure("TEntry", fieldbackground=FIELD, foreground=TEXT, insertcolor=TEXT,
                    bordercolor=LINE, lightcolor=LINE, darkcolor=LINE, padding=0, borderwidth=0)
    style.map("TEntry", bordercolor=[("focus", "#8e929d")], lightcolor=[("focus", "#8e929d")])
    style.configure("TCombobox", fieldbackground=FIELD, background=FIELD, foreground=TEXT,
                    arrowcolor=MUTED, bordercolor=LINE, lightcolor=LINE, darkcolor=LINE, padding=0)
    style.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", TEXT)],
              selectbackground=[("readonly", FIELD)], selectforeground=[("readonly", TEXT)])
    radius, inset_y = round(10*scale), round(8*scale)
    images = []
    for outline in (LINE, "#8e929d", SOFT):
        photo = ImageTk.PhotoImage(surface_tile(radius, FIELD, outline, PANEL), master=root)
        images.append(photo)
        resources.append(photo)
    style.element_create("RoundedEntry.field", "image", images[0], ("focus", images[1]),
                         ("disabled", images[2]), border=(radius, inset_y, radius, inset_y), sticky="nsew")
    style.layout("TEntry", [("RoundedEntry.field", {"sticky": "nsew", "children": [
        ("Entry.padding", {"sticky": "nsew", "children": [("Entry.textarea", {"sticky": "nsew"})]})]})])
    style.layout("TCombobox", [("RoundedEntry.field", {"sticky": "nsew", "children": [
        ("Combobox.downarrow", {"side": "right", "sticky": "ns"}),
        ("Combobox.padding", {"sticky": "nsew", "children": [("Combobox.textarea", {"sticky": "nsew"})]})]})])
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", LINE)
    root.option_add("*TCombobox*Listbox.font", ("Nunito Sans", 10))
    style.configure("TCheckbutton", background=BG, foreground=MUTED, indicatorbackground=FIELD,
                    indicatorforeground=TEXT, indicatorsize=18, padding=4)
    style.map("TCheckbutton", background=[("active", BG)], foreground=[("active", TEXT)])
    checks = []
    for checked in (False, True):
        image = Image.new("RGBA", (64, 64), BG)
        drawing = ImageDraw.Draw(image)
        drawing.rounded_rectangle((5, 5, 58, 58), radius=12, fill=FIELD, outline=MINT if checked else LINE, width=3)
        if checked:
            drawing.line((18, 32, 28, 42, 46, 22), fill=MINT, width=5, joint="curve")
        photo = ImageTk.PhotoImage(image.resize((24, 24), Image.Resampling.LANCZOS), master=root)
        resources.append(photo)
        checks.append(photo)
    style.element_create("Profile.indicator", "image", checks[0], ("selected", checks[1]), width=30, sticky="w")
    style.layout("TCheckbutton", [("Checkbutton.padding", {"sticky": "nsew", "children": [
        ("Profile.indicator", {"side": "left", "sticky": "w"}),
        ("Checkbutton.focus", {"side": "left", "sticky": "w", "children": [("Checkbutton.label", {"sticky": "nsew"})]})]})])
    style.configure("Vertical.TScrollbar", background=LINE, troughcolor=BG, borderwidth=0,
                    lightcolor=BG, darkcolor=BG, arrowcolor=DIM, arrowsize=12)
    style.map("Vertical.TScrollbar", background=[("active", "#555860"), ("!active", LINE)],
              troughcolor=[("!disabled", BG)], arrowcolor=[("!disabled", DIM)])
    for name, normal, hover, fg, surface in (("TButton", FIELD, "#303238", TEXT, PANEL),
                                  ("Footer.TButton", FIELD, "#303238", TEXT, BG),
                                  ("Primary.TButton", PRIMARY, "#f4f4f6", "#25262b", BG),
                                  ("Nav.TButton", PANEL, FIELD, MUTED, PANEL),
                                  ("Selected.Nav.TButton", PRIMARY, "#f4f4f6", "#25262b", PANEL),
                                  ("Chrome.TButton", HEADER, FIELD, MUTED, HEADER),
                                  ("Close.Chrome.TButton", HEADER, "#a83e4a", TEXT, HEADER)):
        element = name + ".surface"
        images = []
        radius = round((14 if "Nav" in name else 6 if "Chrome" in name else 10) * scale)
        pressed = "#c9cbd1" if normal == PRIMARY else LINE
        for color, outline in ((normal, normal), (hover, hover), (pressed, pressed), (FIELD, FIELD), (normal, MINT)):
            photo = ImageTk.PhotoImage(surface_tile(radius, color, outline, surface), master=root)
            images.append(photo)
            resources.append(photo)
        style.element_create(element, "image", images[0], ("disabled", images[3]),
                             ("pressed", images[2]), ("active", images[1]), ("focus", images[4]), border=radius, sticky="nsew")
        style.layout(name, [(element, {"sticky": "nsew", "children": [
            ("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]})]})])
        style.configure(name, foreground=fg, background=surface, padding=(8, 3), font=ui_font(10, True), anchor="center")
        style.map(name, foreground=[("disabled", DIM)], background=[("disabled", surface), ("!disabled", surface)])
    style.configure("Footer.TButton", background=BG)
    style.map("Footer.TButton", background=[("disabled", BG), ("!disabled", BG)])
    style.configure("Nav.TButton", padding=0, font=ui_font(8))
    style.configure("Selected.Nav.TButton", padding=0, font=ui_font(8, True))
    style.configure("Chrome.TButton", padding=(1, 0), font=ui_font(12))
    style.configure("Close.Chrome.TButton", padding=(1, 0), font=ui_font(14))
