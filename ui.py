"""Graphite desktop interface. Connection and process management stay in app.py."""
import ctypes
import tkinter as tk
from tkinter import font as tk_font, ttk

from PIL import Image, ImageDraw, ImageTk

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


def label(parent, text=None, variable=None, size=10, color=TEXT, bold=False, **kwargs):
    return tk.Label(parent, text=text, textvariable=variable, bg=parent.cget("bg"), fg=color,
                    font=("Nunito Sans", size, "bold" if bold else "normal"), anchor=kwargs.pop("anchor", "w"), **kwargs)


def frame(parent, bg=None, **kwargs):
    return tk.Frame(parent, bg=bg or parent.cget("bg"), **kwargs)


class Panel(tk.Canvas):
    def __init__(self, parent, padding=20, **kwargs):
        super().__init__(parent, bg=parent.cget("bg"), highlightthickness=0, bd=0, **kwargs)
        self.padding = padding
        self.body = tk.Frame(self, bg=PANEL)
        self.window = self.create_window(padding, padding, window=self.body, anchor="nw")
        self.bind("<Configure>", self.resize)
        self.body.bind("<Configure>", lambda event: self.configure(height=self.body.winfo_reqheight() + 2 * padding))

    def resize(self, event):
        w, h, r = event.width - 1, event.height - 1, 14
        self.delete("surface")
        self.create_polygon(r, 0, w-r, 0, w, 0, w, r, w, h-r, w, h, w-r, h,
                            r, h, 0, h, 0, h-r, 0, r, 0, 0,
                            smooth=True, fill=PANEL, outline=SOFT, tags="surface")
        self.tag_lower("surface")
        self.itemconfigure(self.window, width=max(1, event.width - 2 * self.padding))


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
        if float(first) <= 0 and float(last) >= 0.999:
            self.scroll.pack_forget()
        elif not self.scroll.winfo_manager():
            self.scroll.pack(side="right", fill="y", before=self.canvas)


class DesktopUI:
    def __init__(self, app, root, profile, version, directory):
        self.app, self.root = app, root
        self.page = "connection"
        self.images = []
        self.entries = {}
        self.secret_buttons = {}
        if hasattr(ctypes, "windll"):
            for path in (directory / "assets/fonts").glob("*.ttf"):
                ctypes.windll.gdi32.AddFontResourceExW(str(path), 0x10, None)
        self.style()
        root.configure(bg=BG)
        root.title(f"CSQTT v{version}")
        scale = max(1, root.winfo_fpixels("1i") / 96)
        self.scale = scale
        width = min(int(1120 * scale), root.winfo_screenwidth()-80)
        height = min(int(900 * scale), root.winfo_screenheight()-100)
        root.geometry(f"{width}x{height}")
        root.minsize(min(980, width), min(700, height))
        root.after_idle(self.dark_titlebar)

        sidebar = Panel(root, padding=9, width=max(100, int(76 * scale)))
        sidebar.pack(side="left", fill="y", padx=(18, 0), pady=18)
        sidebar.pack_propagate(False)
        rail = sidebar.body
        label(rail, "CS", size=20, bold=True, anchor="center").pack(fill="x", pady=(8, 18))
        self.nav = {}
        self.nav_images = {}
        for key, text, icon in (("connection", "Туннель", "connection"),
                                ("settings", "Опции", "settings"), ("logs", "Журнал", "logs")):
            self.nav_images[key] = (self.icon(icon), self.icon(icon, "#25262b"))
            button = ttk.Button(rail, text=text, image=self.nav_images[key][0], compound="top",
                                style="Nav.TButton", command=lambda k=key: self.show_page(k), takefocus=True)
            button.pack(fill="x", pady=5)
            self.nav[key] = button
        label(rail, f"v{version}", size=8, color=DIM, anchor="center").pack(side="bottom", fill="x", pady=(8, 2))
        label(rail, "TCP / 443", size=8, color=MUTED, anchor="center").pack(side="bottom", fill="x")

        main = frame(root)
        main.pack(side="left", fill="both", expand=True, padx=(24, 24), pady=(24, 18))
        header = frame(main)
        header.pack(fill="x", pady=(0, 18))
        titles = frame(header)
        titles.pack(side="left", fill="x", expand=True)
        self.heading = label(titles, "Подключение", size=23, bold=True)
        self.heading.pack(anchor="w")
        self.subtitle = label(titles, "Интернет через ваш сервер csqtt и корпоративный прокси.", color=MUTED)
        self.subtitle.pack(anchor="w", pady=(5, 0))
        self.badge = label(header, "●  Отключено", color=DIM, size=10)
        self.badge.pack(side="right", padx=(12, 0))

        stats = frame(main)
        stats.pack(fill="x", pady=(0, 16))
        for column, (name, title, unit) in enumerate((("active_count", "Активные потоки", ""),
                  ("upload_total", "Отправлено", "МБ"), ("download_total", "Получено", "МБ"))):
            stats.columnconfigure(column, weight=1, uniform="metric")
            panel = Panel(stats, padding=14)
            panel.grid(row=0, column=column, sticky="ew", padx=(0, 12 if column < 2 else 0))
            label(panel.body, title, size=9, color=MUTED).pack(anchor="w")
            value = frame(panel.body)
            value.pack(fill="x", pady=(4, 0))
            variable = tk.StringVar(value="0" if not unit else "0.00")
            setattr(app, name, variable)
            label(value, variable=variable, size=21, bold=True).pack(side="left")
            if unit:
                label(value, unit, size=9, color=DIM).pack(side="left", padx=(8, 0), pady=(10, 0))
        compact = frame(main)
        summary = tk.StringVar()
        label(compact, variable=summary, size=9, color=MUTED).pack(anchor="w")
        def update_summary(*args):
            summary.set(f"Потоки: {app.active_count.get()}     ↑ {app.upload_total.get()} МБ     ↓ {app.download_total.get()} МБ")
        for variable in (app.active_count, app.upload_total, app.download_total):
            variable.trace_add("write", update_summary)
        update_summary()

        # Controls and connection state remain visible when changing pages.
        footer = frame(main)
        footer.pack(side="bottom", fill="x", pady=(16, 0))
        tk.Frame(footer, height=1, bg=SOFT).pack(fill="x", pady=(0, 12))
        self.status_label = label(footer, variable=app.status, color=MUTED, justify="left", wraplength=900)
        self.status_label.pack(fill="x", pady=(0, 12))
        self.status_label.bind("<Configure>", lambda e: self.status_label.configure(wraplength=max(200, e.width)))
        actions = frame(footer)
        actions.pack(fill="x")
        app.start_button = ttk.Button(actions, text="Подключить", style="Primary.TButton", command=app.start)
        app.start_button.pack(side="left")
        app.stop_button = ttk.Button(actions, text="Отключить", style="Footer.TButton", command=app.stop, state="disabled")
        app.stop_button.pack(side="left", padx=10)
        app.test_button = ttk.Button(actions, text="Проверить интернет", style="Footer.TButton", command=app.check_internet, state="disabled")
        app.test_button.pack(side="right")

        self.pages = frame(main)
        self.pages.pack(fill="both", expand=True)
        self.pages.rowconfigure(0, weight=1)
        self.pages.columnconfigure(0, weight=1)
        self.connection_page(profile)
        self.settings_page()
        self.logs_page()
        self.show_page("connection")
        previous_compact = None
        def resize_window(event):
            nonlocal previous_compact
            if event.widget is not root:
                return
            small = event.height / self.scale < 720
            if small == previous_compact:
                return
            previous_compact = small
            if small:
                stats.pack_forget()
                compact.pack(fill="x", pady=(0, 14), before=self.pages)
            else:
                compact.pack_forget()
                stats.pack(fill="x", pady=(0, 16), before=self.pages)
        root.bind("<Configure>", resize_window, add="+")
        root.bind("<MouseWheel>", self.scroll_page)

    def style(self):
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
            tk_font.nametofont(name, root=self.root).configure(family="Nunito Sans", size=10)
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", background=PANEL, foreground=TEXT, font=("Nunito Sans", 10), bordercolor=LINE)
        style.configure("TEntry", fieldbackground=FIELD, foreground=TEXT, insertcolor=TEXT,
                        bordercolor=LINE, lightcolor=LINE, darkcolor=LINE, padding=(10, 8), borderwidth=1)
        style.map("TEntry", bordercolor=[("focus", "#8e929d")], lightcolor=[("focus", "#8e929d")])
        style.configure("TCombobox", fieldbackground=FIELD, background=FIELD, foreground=TEXT,
                        arrowcolor=MUTED, bordercolor=LINE, lightcolor=LINE, darkcolor=LINE, padding=(10, 8))
        style.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", TEXT)],
                  selectbackground=[("readonly", FIELD)], selectforeground=[("readonly", TEXT)])
        self.root.option_add("*TCombobox*Listbox.background", FIELD)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", LINE)
        self.root.option_add("*TCombobox*Listbox.font", ("Nunito Sans", 10))
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
            photo = ImageTk.PhotoImage(image.resize((24, 24), Image.Resampling.LANCZOS), master=self.root)
            self.images.append(photo)
            checks.append(photo)
        style.element_create("Profile.indicator", "image", checks[0], ("selected", checks[1]), width=30, sticky="w")
        style.layout("TCheckbutton", [("Checkbutton.padding", {"sticky": "nsew", "children": [
            ("Profile.indicator", {"side": "left", "sticky": "w"}),
            ("Checkbutton.focus", {"side": "left", "sticky": "w", "children": [("Checkbutton.label", {"sticky": "nsew"})]})]})])
        style.configure("Vertical.TScrollbar", background=LINE, troughcolor=BG, borderwidth=0,
                        lightcolor=BG, darkcolor=BG, arrowcolor=DIM, arrowsize=12)
        style.map("Vertical.TScrollbar", background=[("active", "#555860"), ("!active", LINE)],
                  troughcolor=[("!disabled", BG)], arrowcolor=[("!disabled", DIM)])
        for name, normal, hover, fg in (("TButton", FIELD, "#303238", TEXT),
                                      ("Primary.TButton", PRIMARY, "#f4f4f6", "#25262b"),
                                      ("Nav.TButton", PANEL, FIELD, MUTED),
                                      ("Selected.Nav.TButton", PRIMARY, "#f4f4f6", "#25262b")):
            element = name + ".surface"
            images = []
            pressed = "#c9cbd1" if normal == PRIMARY else LINE
            for color, outline in ((normal, normal), (hover, hover), (pressed, pressed), (FIELD, FIELD), (normal, MINT)):
                image = Image.new("RGBA", (64, 64))
                ImageDraw.Draw(image).rounded_rectangle((1, 1, 62, 62), radius=16, fill=color, outline=outline, width=2)
                photo = ImageTk.PhotoImage(image.resize((32, 32), Image.Resampling.LANCZOS), master=self.root)
                self.images.append(photo)
                images.append(photo)
            style.element_create(element, "image", images[0], ("disabled", images[3]),
                                 ("pressed", images[2]), ("active", images[1]), ("focus", images[4]), border=9, sticky="nsew")
            style.layout(name, [(element, {"sticky": "nsew", "children": [
                ("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]})]})])
            surface = BG if name == "Primary.TButton" else PANEL
            style.configure(name, foreground=fg, background=surface, padding=(15, 10), font=("Nunito Sans", 10, "bold"), anchor="center")
            style.map(name, foreground=[("disabled", DIM)], background=[("disabled", surface), ("!disabled", surface)])
        style.configure("Footer.TButton", background=BG)
        style.map("Footer.TButton", background=[("disabled", BG), ("!disabled", BG)])
        style.configure("Nav.TButton", padding=(2, 13), font=("Nunito Sans", 8))
        style.configure("Selected.Nav.TButton", padding=(2, 13), font=("Nunito Sans", 8, "bold"))

    def icon(self, name, color=MUTED):
        image = Image.new("RGBA", (48, 48))
        draw = ImageDraw.Draw(image)
        if name == "connection":
            draw.rounded_rectangle((8, 8, 39, 31), radius=3, outline=color, width=3)
            draw.line((24, 32, 24, 40), fill=color, width=3)
            draw.line((15, 40, 33, 40), fill=color, width=3)
        elif name == "settings":
            for y, x in ((16, 17), (33, 31)):
                draw.line((7, y, 41, y), fill=color, width=3)
                draw.line((x, y-7, x, y+7), fill=color, width=4)
        else:
            draw.rounded_rectangle((10, 6, 38, 42), radius=3, outline=color, width=3)
            for y in (16, 24, 32):
                draw.line((17, y, 31, y), fill=color, width=2)
        photo = ImageTk.PhotoImage(image.resize((24, 24), Image.Resampling.LANCZOS), master=self.root)
        self.images.append(photo)
        return photo

    def page_frame(self, key):
        page = ScrollPage(self.pages)
        page.grid(row=0, column=0, sticky="nsew")
        setattr(self, key, page)
        return page.body

    def section(self, parent, title, description=None):
        panel = Panel(parent)
        label(panel.body, title, size=12, bold=True).pack(anchor="w", pady=(0, 4))
        if description:
            hint = label(panel.body, description, color=MUTED, size=9, wraplength=520, justify="left")
            hint.pack(fill="x", pady=(0, 10))
            hint.bind("<Configure>", lambda e: hint.configure(wraplength=max(100, e.width)))
        return panel

    def field(self, parent, title, key, secret=False):
        group = frame(parent)
        group.pack(fill="x", pady=(10, 0))
        label(group, title, color=MUTED, size=9).pack(anchor="w", pady=(0, 5))
        row = frame(group)
        row.pack(fill="x")
        entry = ttk.Entry(row, width=1, textvariable=self.app.vars[key], show="•" if secret else "")
        self.entries[key] = entry
        entry.pack(side="left", fill="x", expand=True)
        if secret:
            def toggle():
                hidden = bool(entry.cget("show"))
                entry.configure(show="" if hidden else "•")
                button.configure(text="Скрыть" if hidden else "Показать")
            button = ttk.Button(row, text="Показать", command=toggle, width=8)
            button.pack(side="right", padx=(7, 0))
            self.secret_buttons[key] = button
        return entry

    def text(self, parent, height, **kwargs):
        return tk.Text(parent, height=height, width=1, bg=DEEP, fg=TEXT, insertbackground=TEXT,
                       selectbackground="#43564c", selectforeground=TEXT, highlightthickness=1,
                       highlightbackground=LINE, highlightcolor=MINT, relief="flat", bd=0,
                       padx=12, pady=10, font=("Consolas", 10), wrap="word", **kwargs)

    def connection_page(self, profile):
        body = self.page_frame("connection")
        body.columnconfigure(0, weight=3, uniform="connection")
        body.columnconfigure(1, weight=2, uniform="connection")
        server = self.section(body, "Сервер csqtt", "Данные подключения с вашего сервера.")
        server.grid(row=0, column=0, sticky="new", padx=(0, 14))
        self.field(server.body, "Сервер · IP или домен и порт", "server")
        self.field(server.body, "Пароль csqtt", "password", secret=True)
        label(server.body, "Хеши VK или ссылки звонков", color=MUTED, size=9).pack(anchor="w", pady=(14, 5))
        self.app.hashes = self.text(server.body, height=4)
        self.app.hashes.pack(fill="x")
        self.app.hashes.insert("1.0", profile.hashes)
        label(server.body, "По одному на строку · до 6 хешей", color=DIM, size=8).pack(anchor="w", pady=(7, 2))
        side = frame(body)
        side.grid(row=0, column=1, sticky="new")
        proxy = self.section(side, "Корпоративный прокси", "HTTP CONNECT · авторизация Basic")
        proxy.pack(fill="x")
        self.field(proxy.body, "Адрес прокси · IP:порт", "proxy")
        self.field(proxy.body, "Логин", "proxy_user")
        self.field(proxy.body, "Пароль прокси", "proxy_password", secret=True)
        self.app.check_proxy_button = ttk.Button(proxy.body, text="Проверить прокси :443", command=self.app.check_proxy)
        self.app.check_proxy_button.pack(anchor="w", pady=(14, 0))
        local = self.section(side, "Локальные прокси")
        local.pack(fill="x", pady=(14, 0))
        self.endpoints = {}
        for kind, key in (("SOCKS5", "socks_port"), ("HTTP", "http_port")):
            row = frame(local.body)
            row.pack(fill="x", pady=(8, 0))
            text = tk.StringVar()
            self.endpoints[key] = text
            label(row, variable=text, size=9, color=MUTED).pack(side="left")
            ttk.Button(row, text="Копировать", command=lambda k=key, t=kind: self.copy_endpoint(k, t)).pack(side="right")
            self.app.vars[key].trace_add("write", lambda *args: self.update_endpoints())
        self.update_endpoints()
        remember = ttk.Checkbutton(body, text="Запомнить профиль на этом компьютере", variable=self.app.remember)
        remember.grid(row=1, column=0, columnspan=2, sticky="w", pady=(12, 0))
        self.adapt_columns(body, server, side, "connection", remember)

    def settings_page(self):
        body = self.page_frame("settings")
        body.columnconfigure(0, weight=1, uniform="settings")
        body.columnconfigure(1, weight=1, uniform="settings")
        transport = self.section(body, "Параметры туннеля", "Режимы должны соответствовать настройкам сервера.")
        transport.grid(row=0, column=0, sticky="new", padx=(0, 14))
        self.field(transport.body, "Потоки · workers", "workers")
        for title, key, values in (("Обфускация", "obfs", ("unified", "audio", "video")),
                                   ("SRTP", "srtp", ("auto", "wrap", "dtls"))):
            label(transport.body, title, size=9, color=MUTED).pack(anchor="w", pady=(14, 5))
            ttk.Combobox(transport.body, textvariable=self.app.vars[key], values=values, state="readonly").pack(fill="x")
        self.field(transport.body, "TURN-хост · необязательно", "turn")
        right = frame(body)
        right.grid(row=0, column=1, sticky="new")
        ports = self.section(right, "Локальные порты", "Доступны только на этом компьютере: 127.0.0.1.")
        ports.pack(fill="x")
        self.field(ports.body, "SOCKS5", "socks_port")
        self.field(ports.body, "HTTP", "http_port")
        session = self.section(right, "Параметры сессии", "Заполняйте, только если они выданы сервером.")
        session.pack(fill="x", pady=(14, 0))
        self.field(session.body, "Поколение", "generation")
        self.field(session.body, "Salt", "salt", secret=True)
        self.adapt_columns(body, transport, right, "settings")

    def adapt_columns(self, body, left, right, group, remember=None):
        previous = None
        def adapt(event):
            nonlocal previous
            stacked = event.width / self.scale < 760
            if stacked == previous:
                return
            previous = stacked
            body.columnconfigure(0, weight=1 if stacked else (3 if group == "connection" else 1), uniform="" if stacked else group)
            body.columnconfigure(1, weight=0 if stacked else (2 if group == "connection" else 1), uniform="" if stacked else group)
            left.grid_configure(padx=0 if stacked else (0, 14))
            right.grid_configure(row=1 if stacked else 0, column=0 if stacked else 1, pady=(14, 0) if stacked else 0)
            if remember:
                remember.grid_configure(row=2 if stacked else 1, columnspan=1 if stacked else 2)
        body.bind("<Configure>", adapt, add="+")

    def logs_page(self):
        body = frame(self.pages)
        body.grid(row=0, column=0, sticky="nsew")
        self.logs = body
        tools = frame(body)
        tools.pack(fill="x", pady=(0, 12))
        label(tools, "События подключения", size=12, bold=True).pack(side="left")
        self.app.copy_log_button = ttk.Button(tools, text="Скопировать журнал", command=self.app.copy_log)
        self.app.copy_log_button.pack(side="right")
        ttk.Button(tools, text="Сохранить…", command=self.app.save_log).pack(side="right", padx=10)
        self.app.log = self.text(body, height=10, state="disabled")
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.app.log.yview)
        scrollbar.pack(side="right", fill="y")
        self.app.log.configure(yscrollcommand=scrollbar.set)
        self.app.log.pack(fill="both", expand=True)
        self.log_empty = label(self.app.log, "Журнал пока пуст\n\nЗдесь появятся события после подключения.",
                               color=DIM, size=11, anchor="center", justify="center")
        self.log_empty.place(relx=0.5, rely=0.45, anchor="center")
        self.app.log.tag_configure("error", foreground=RED)
        self.app.log.tag_configure("retry", foreground=AMBER)
        self.app.log.tag_configure("ready", foreground=MINT)
        label(body, "Пароли и хеши скрываются.   Ctrl+A — выделить всё   ·   Ctrl+C — копировать", size=9, color=DIM).pack(anchor="w", pady=(9, 0))

    def show_page(self, key):
        self.page = key
        for name in ("connection", "settings", "logs"):
            if name == key:
                getattr(self, name).grid()
            else:
                getattr(self, name).grid_remove()
        titles = {"connection": ("Подключение", "Интернет через ваш сервер csqtt и корпоративный прокси."),
                  "settings": ("Параметры", "Транспорт, локальные порты и параметры сессии."),
                  "logs": ("Журнал", "События ядра, состояние туннеля и диагностика.")}
        title, subtitle = titles[key]
        self.heading.configure(text=title)
        self.subtitle.configure(text=subtitle)
        for name, button in self.nav.items():
            button.configure(style="Selected.Nav.TButton" if name == key else "Nav.TButton",
                             image=self.nav_images[name][1 if name == key else 0])

    def scroll_page(self, event):
        if self.page != "logs" and not isinstance(event.widget, tk.Text):
            canvas = getattr(self, self.page).canvas
            if canvas.yview() != (0.0, 1.0):
                canvas.yview_scroll(-int(event.delta / 120), "units")

    def set_state(self, state):
        text, color = {"offline": ("Отключено", DIM), "connecting": ("Подключение", AMBER),
                       "checking": ("Проверка интернета", AMBER), "online": ("Подключено", MINT),
                       "unconfirmed": ("Интернет не подтверждён", AMBER),
                       "recovering": ("Восстановление", AMBER), "stopping": ("Отключение", DIM)}[state]
        self.badge.configure(text=f"●  {text}", fg=color)
        self.status_label.configure(fg=color if state in ("online", "unconfirmed", "recovering") else MUTED)
        self.update_endpoints()

    def update_endpoints(self):
        for key, variable in self.endpoints.items():
            profile = self.app.running_profile if self.app.helper else None
            port = getattr(profile, key) if profile else self.app.vars[key].get()
            kind = "SOCKS5" if key == "socks_port" else "HTTP"
            variable.set(f"{kind}   127.0.0.1:{port}")

    def copy_endpoint(self, key, kind):
        profile = self.app.running_profile if self.app.helper else None
        port = getattr(profile, key) if profile else self.app.vars[key].get()
        self.root.clipboard_clear()
        self.root.clipboard_append(f"{'socks5h' if kind == 'SOCKS5' else 'http'}://127.0.0.1:{port}")

    def dark_titlebar(self):
        try:
            window = ctypes.windll.user32.GetParent(self.root.winfo_id())
            enabled = ctypes.c_int(1)
            for attribute in (20, 19):
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(window, attribute, ctypes.byref(enabled), 4) == 0:
                    break
        except (AttributeError, OSError):
            pass
