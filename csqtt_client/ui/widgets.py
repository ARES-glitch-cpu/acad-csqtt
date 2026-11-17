"""Reusable native Tk widgets."""
import tkinter as tk
from tkinter import ttk
from PIL import ImageTk

from csqtt_client.ui.theme import BG, PANEL, SOFT, TEXT, rounded_surface, ui_font


def label(parent, text=None, variable=None, size=10, color=TEXT, bold=False, **kwargs):
    return tk.Label(parent, text=text, textvariable=variable, bg=parent.cget("bg"), fg=color,
                    font=ui_font(size, bold), anchor=kwargs.pop("anchor", "w"), **kwargs)


def frame(parent, bg=None, **kwargs):
    return tk.Frame(parent, bg=bg or parent.cget("bg"), **kwargs)


class Panel(tk.Canvas):
    def __init__(self, parent, padding=20, radius=18, stretch=False, fill=PANEL, outline=SOFT, **kwargs):
        super().__init__(parent, bg=parent.cget("bg"), highlightthickness=0, bd=0, **kwargs)
        self.padding = padding
        self.fill, self.outline = fill, outline
        self.radius = round(radius * max(1, self.winfo_fpixels("1i") / 96))
        self.stretch = stretch
        self.inset_y = max(padding, self.radius) if stretch else padding
        self.surface = None
        self.last_size = None
        self.body = tk.Frame(self, bg=fill)
        self.surface_id = self.create_image(0, 0, anchor="nw")
        self.window = self.create_window(padding, self.inset_y, window=self.body, anchor="nw")
        self.bind("<Configure>", self.resize)
        if not stretch:
            self.body.bind("<Configure>", lambda event: self.configure(height=self.body.winfo_reqheight() + 2 * padding))

    def resize(self, event):
        if event.width < 2 or event.height < 2 or self.last_size == (event.width, event.height):
            return
        self.last_size = (event.width, event.height)
        image = rounded_surface(event.width, event.height, self.radius, self.fill, self.outline, self.cget("bg"))
        self.surface = ImageTk.PhotoImage(image, master=self)
        self.itemconfigure(self.surface_id, image=self.surface)
        self.itemconfigure(self.window, width=max(1, event.width - 2 * self.padding))
        if self.stretch:
            self.itemconfigure(self.window, height=max(1, event.height - 2 * self.inset_y))


class ScrollPage(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.canvas = tk.Canvas(self, bg=BG, bd=0, highlightthickness=0)
        self.scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.set_scroll)
        self.scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=BG)
        self.window = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(self.window, width=event.width))

    def set_scroll(self, first, last):
        self.scroll.set(first, last)
        # Keep the gutter's width constant: toggling it during layout caused a
        # cascade of canvas resizes and full panel redraws on every page change.
        self.scroll.state(["disabled"] if float(first) <= 0 and float(last) >= 0.999 else ["!disabled"])
