"""Desktop pages, navigation, and connection feedback."""
import ctypes
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageDraw, ImageTk

from csqtt_client.ui.theme import (
    BG, PANEL, FIELD, DEEP, TEXT, MUTED, DIM, LINE, SOFT, MINT, AMBER, RED, HEADER, ui_font,
)
from csqtt_client.ui.styles import configure_style
from csqtt_client.ui.widgets import Panel, ScrollPage, label, frame
from csqtt_client.models.admin_txt import parse_admin_txt


class DesktopUI:
    def __init__(self, app, root, profile, version, directory):
        self.app, self.root = app, root
        self.page = None
        self.role = "admin"
        self.images = []
        self.entries = {}
        self.secret_buttons = {}
        self.scale = max(1, root.winfo_fpixels("1i") / 96)
        if hasattr(ctypes, "windll"):
            for path in (directory / "assets/fonts").glob("*.ttf"):
                ctypes.windll.gdi32.AddFontResourceExW(str(path), 0x10, None)
        configure_style(root, self.scale, self.images)
        with Image.open(directory / "assets/icons/CS_logo.png") as source:
            self.logo = source.convert("RGBA")
        self.window_icon = ImageTk.PhotoImage(self.logo.resize((256, 256), Image.Resampling.LANCZOS), master=root)
        root.iconphoto(True, self.window_icon)
        if sys.platform == "win32":
            root.iconbitmap(default=str(directory / "assets/icons/CSQTT.ico"))
        root.configure(bg=BG)
        root.title(f"CSQTT v{version}")
        scale = max(1, root.winfo_fpixels("1i") / 96)
        self.scale = scale
        width = min(int(1120 * scale), root.winfo_screenwidth()-80)
        height = min(int(900 * scale), root.winfo_screenheight()-100)
        root.geometry(f"{width}x{height}")
        root.minsize(min(980, width), min(700, height))
        from csqtt_client.platform.windows.chrome import WindowChrome
        self.chrome = WindowChrome(root, scale)
        self.title_bar(version)

        sidebar = Panel(root, padding=9, radius=24, stretch=True, width=max(106, int(88 * scale)))
        sidebar.pack(side="left", fill="y", padx=(18, 0), pady=18)
        sidebar.pack_propagate(False)
        rail = sidebar.body
        logo_size = round(38*self.scale)
        self.rail_logo = ImageTk.PhotoImage(self.logo.resize((logo_size, logo_size), Image.Resampling.LANCZOS), master=root)
        tk.Label(rail, image=self.rail_logo, bg=PANEL).pack(fill="x", pady=(8, 18))
        self.nav = {}
        self.nav_images = {}
        for key, text, icon in (("connection", "Подкл.", "connection"),
                                ("settings", "Туннель", "settings"),
                                ("routing", "Роутинг", "routing"),
                                ("deploy", "Деплой", "deploy"),
                                ("logs", "Журнал", "logs")):
            self.nav_images[key] = (self.icon(icon), self.icon(icon, "#25262b"))
            button = ttk.Button(rail, text=text, image=self.nav_images[key][0], compound="top",
                                width=9, style="Nav.TButton",
                                command=lambda k=key: self.show_page(k), takefocus=True)
            button.pack(fill="x", pady=6)
            self.tooltip(button, text)
            self.nav[key] = button
        label(rail, f"v{version}", size=8, color=DIM, anchor="center").pack(side="bottom", fill="x", pady=(8, 2))
        label(rail, "TCP / 443", size=8, color=MUTED, anchor="center").pack(side="bottom", fill="x")

        main = frame(root)
        main.pack(side="left", fill="both", expand=True, padx=(24, 24), pady=(24, 18))
        header = frame(main)
        header.pack(fill="x", pady=(0, 18))
        titles = frame(header)
        titles.pack(side="left", fill="x", expand=True)
        self.heading = label(titles, "Подключение", size=21, bold=True)
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
        self.routing_page(profile)
        self.deploy_page(profile)
        self.logs_page()
        self.show_page("connection")
        self.apply_role("Администратор")
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

    def title_bar(self, version):
        bar = tk.Frame(self.root, bg=HEADER, height=round(46*self.scale))
        bar.pack(side="top", fill="x")
        bar.pack_propagate(False)
        tk.Frame(self.root, height=1, bg=SOFT).pack(side="top", fill="x")
        logo_size = round(24*self.scale)
        self.caption_logo = ImageTk.PhotoImage(self.logo.resize((logo_size, logo_size), Image.Resampling.LANCZOS), master=self.root)
        logo = tk.Label(bar, image=self.caption_logo, bg=HEADER)
        logo.pack(side="left", padx=(18, 8))
        brand = label(bar, "CSQTT", size=12, bold=True)
        brand.pack(side="left", padx=(0, 12))
        version_label = label(bar, f"v{version}", size=8, color=DIM)
        version_label.pack(side="left")
        label(bar, "Роль", size=9, color=MUTED).pack(side="left", padx=(22, 7))
        self.role_choice = tk.StringVar(value="Администратор")
        role_box = ttk.Combobox(
            bar, textvariable=self.role_choice,
            values=("Администратор", "Клиент"),
            state="readonly", width=16,
        )
        role_box.pack(side="left", pady=7)
        role_box.bind("<<ComboboxSelected>>", self.change_role)
        drag_space = frame(bar)
        drag_space.pack(side="left", fill="both", expand=True)
        for widget in (bar, logo, brand, version_label, drag_space):
            widget.bind("<ButtonPress-1>", self.chrome.drag)
            widget.bind("<B1-Motion>", self.chrome.drag_motion)
            widget.bind("<ButtonRelease-1>", self.chrome.drag_end)
            widget.bind("<Double-Button-1>", self.chrome.maximize)
        controls = frame(bar)
        controls.pack(side="right", fill="y", padx=8, pady=7)
        for text, hint, command, style in (("—", "Свернуть в трей", self.app.hide_to_tray, "Chrome.TButton"),
                      ("□", "Развернуть / восстановить", self.chrome.maximize, "Chrome.TButton"),
                      ("×", "Скрыть в трей", self.app.hide_to_tray, "Close.Chrome.TButton")):
            button = ttk.Button(controls, text=text, width=2, command=command, style=style)
            button.pack(side="left", fill="y", padx=2)
            self.tooltip(button, hint)
            if text == "—":
                self.minimize_button = button
            elif text == "□":
                self.maximize_button = button
            else:
                self.hide_button = button
        self.titlebar = bar

    def tooltip(self, widget, text):
        pending, popup = None, None
        def hide(event=None):
            nonlocal pending, popup
            if pending:
                self.root.after_cancel(pending)
                pending = None
            if popup:
                popup.destroy()
                popup = None
        def show():
            nonlocal popup, pending
            pending = None
            popup = tk.Toplevel(self.root)
            popup.overrideredirect(True)
            popup.configure(bg=LINE)
            tk.Label(popup, text=text, bg=FIELD, fg=TEXT, font=ui_font(9), padx=10, pady=5).pack(padx=1, pady=1)
            x = min(widget.winfo_rootx()+widget.winfo_width()+7, self.root.winfo_screenwidth()-240)
            popup.geometry(f"+{x}+{widget.winfo_rooty()+widget.winfo_height()+4}")
        def enter(event):
            nonlocal pending
            hide()
            pending = self.root.after(450, show)
        for event in ("<Enter>", "<FocusIn>"):
            widget.bind(event, enter, add="+")
        for event in ("<Leave>", "<FocusOut>", "<ButtonPress-1>"):
            widget.bind(event, hide, add="+")



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
        elif name == "routing":
            draw.ellipse((6, 7, 18, 19), outline=color, width=3)
            draw.ellipse((30, 7, 42, 19), outline=color, width=3)
            draw.ellipse((18, 30, 30, 42), outline=color, width=3)
            draw.line((17, 15, 31, 15), fill=color, width=3)
            draw.line((14, 18, 22, 31), fill=color, width=3)
            draw.line((34, 18, 26, 31), fill=color, width=3)
        elif name == "deploy":
            draw.rounded_rectangle((7, 9, 41, 39), radius=4, outline=color, width=3)
            draw.line((13, 17, 35, 17), fill=color, width=3)
            draw.line((13, 25, 27, 25), fill=color, width=3)
            draw.line((13, 33, 22, 33), fill=color, width=3)
            draw.line((31, 29, 37, 29), fill=color, width=3)
            draw.line((34, 25, 38, 29, 34, 33), fill=color, width=3)
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
        label(panel.body, title, size=11, bold=True).pack(anchor="w", pady=(0, 4))
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

    def text(self, parent, height, expand=False, **kwargs):
        surface = Panel(parent, padding=12, radius=10, stretch=expand, fill=DEEP, outline=LINE)
        widget = tk.Text(surface.body, height=height, width=1, bg=DEEP, fg=TEXT, insertbackground=TEXT,
                         selectbackground="#43564c", selectforeground=TEXT, highlightthickness=0,
                         relief="flat", bd=0, padx=0, pady=0, font=("Consolas", 10), wrap="word", **kwargs)
        widget.pack(fill="both", expand=True)
        widget.surface = surface
        return widget

    def connection_page(self, profile):
        body = self.page_frame("connection")
        body.columnconfigure(0, weight=3, uniform="connection")
        body.columnconfigure(1, weight=2, uniform="connection")
        server = self.section(body, "Сервер csqtt", "Данные подключения с вашего сервера.")
        server.grid(row=0, column=0, sticky="new", padx=(0, 14))
        self.admin_server_group = frame(server.body)
        self.admin_server_group.pack(fill="x")
        self.field(self.admin_server_group, "Сервер · IP или домен и порт", "server")
        self.field(self.admin_server_group, "Пароль csqtt", "password", secret=True)
        self.import_txt_button = ttk.Button(
            self.admin_server_group, text="Загрузить настройки из TXT…",
            command=self.import_admin_txt,
        )
        self.import_txt_button.pack(anchor="w", pady=(14, 0))

        self.client_link_group = frame(server.body)
        self.field(self.client_link_group, "Ссылка подключения csqtt://", "share_link", secret=True)
        self.field(
            self.client_link_group,
            "Пароль CSQTT (если не указан в ссылке)",
            "client_password",
            secret=True,
        )
        label(
            self.client_link_group,
            "Ссылка должна быть скопирована целиком из панели CSQTT. Если в ней нет пароля — укажите его здесь.",
            color=DIM, size=8, wraplength=520, justify="left",
        ).pack(anchor="w", pady=(7, 2))
        self.client_link_group.pack_forget()

        self.hashes_group = frame(server.body)
        self.hashes_group.pack(fill="x", pady=(14, 0))
        label(
            self.hashes_group,
            "Хеши VK или ссылки звонков (если их нет в csqtt://)",
            color=MUTED, size=9,
        ).pack(anchor="w", pady=(0, 5))
        self.app.hashes = self.text(self.hashes_group, height=4)
        self.app.hashes.surface.pack(fill="x")
        self.app.hashes.insert("1.0", profile.hashes)
        label(
            self.hashes_group, "По одному на строку · до 6 хешей",
            color=DIM, size=8,
        ).pack(anchor="w", pady=(7, 2))
        side = frame(body)
        side.grid(row=0, column=1, sticky="new")
        internet = self.section(side, "Доступ в интернет", "Прямое подключение через домашний Wi-Fi или мобильную сеть либо корпоративный HTTP-прокси.")
        internet.pack(fill="x")
        self.internet_choice = tk.StringVar(value="Напрямую (Wi-Fi / мобильный интернет)" if self.app.vars["internet_mode"].get() == "direct" else "Через HTTP-прокси")
        internet_box = ttk.Combobox(internet.body, textvariable=self.internet_choice,
                                    values=("Напрямую (Wi-Fi / мобильный интернет)", "Через HTTP-прокси"), state="readonly")
        self.internet_box = internet_box
        internet_box.pack(fill="x", pady=(8, 4))
        proxy = self.section(side, "Параметры HTTP-прокси", "Нужны только при выборе соответствующего способа доступа.")
        proxy.pack(fill="x", pady=(12, 0))
        self.field(proxy.body, "Адрес прокси · IP:порт", "proxy")
        self.field(proxy.body, "Логин", "proxy_user")
        self.field(proxy.body, "Пароль прокси", "proxy_password", secret=True)
        self.app.check_proxy_button = ttk.Button(proxy.body, text="Проверить прокси :443", command=self.app.check_proxy)
        self.app.check_proxy_button.pack(anchor="w", pady=(14, 0))
        self.proxy_feedback = label(proxy.body, "Прокси ещё не проверен", size=9, color=DIM,
                                    wraplength=360, justify="left")
        self.proxy_feedback.pack(fill="x", pady=(10, 0))
        self.proxy_feedback.bind("<Configure>", lambda e: self.proxy_feedback.configure(wraplength=max(120, e.width)))
        def update_internet_mode(_event=None):
            direct = self.internet_choice.get().startswith("Напрямую")
            self.app.vars["internet_mode"].set("direct" if direct else "proxy")
            state = "disabled" if direct else "normal"
            for key in ("proxy", "proxy_user", "proxy_password"):
                self.entries[key].configure(state=state)
            self.app.check_proxy_button.configure(state=state)
        self.update_internet_mode = update_internet_mode
        internet_box.bind("<<ComboboxSelected>>", update_internet_mode)
        update_internet_mode()
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
        config_group = self.section(server.body, "Конфигурация", "Можно импортировать TXT, JSON-профиль или ссылку csqtt:// из файла. Автозагрузка использует указанный файл при запуске.")
        config_group.pack(fill="x", pady=(14, 0))
        self.app.vars["config_file"] = tk.StringVar(value=self.app.vars["config_file"].get())
        config_row = frame(config_group.body)
        config_row.pack(fill="x")
        config_entry = ttk.Entry(config_row, textvariable=self.app.vars["config_file"], width=1)
        config_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(config_row, text="Выбрать…", command=self.select_config_file).pack(side="right", padx=(8, 0))
        ttk.Button(config_group.body, text="Импортировать сейчас", command=self.import_config_file).pack(anchor="w", pady=(8, 0))
        auto_load = ttk.Checkbutton(config_group.body, text="Автоматически загружать файл при запуске", variable=self.app.vars["auto_load_config"], onvalue="1", offvalue="0")
        auto_load.pack(anchor="w", pady=(8, 0))
        remember = ttk.Checkbutton(body, text="Запомнить профиль на этом компьютере", variable=self.app.remember)
        remember.grid(row=1, column=0, columnspan=2, sticky="w", pady=(12, 0))
        self.adapt_columns(body, server, side, "connection", remember)

    def change_role(self, _event=None):
        selected = self.role_choice.get()
        if (self.app.core or self.app.helper) and not self.app.stopping:
            messagebox.showwarning(
                "Подключение активно",
                "Отключите текущую сессию перед сменой роли.",
                parent=self.root,
            )
            self.role_choice.set("Клиент" if self.role == "client" else "Администратор")
            return
        self.apply_role(selected)

    def apply_role(self, selected):
        self.role = "client" if selected == "Клиент" else "admin"
        if self.role == "client":
            self.admin_server_group.pack_forget()
            self.client_link_group.pack(fill="x", before=self.hashes_group)
        else:
            self.client_link_group.pack_forget()
            self.admin_server_group.pack(fill="x", before=self.hashes_group)

    def select_config_file(self):
        filename = filedialog.askopenfilename(
            parent=self.root, title="Выбрать конфигурацию CSQTT",
            filetypes=[("Конфигурации", "*.txt *.json *.csqtt"), ("Все файлы", "*.*")],
        )
        if filename:
            self.app.vars["config_file"].set(filename)
            self.app.vars["auto_load_config"].set("1")

    def import_config_file(self, path=None, startup=False):
        path = path or self.app.vars["config_file"].get().strip()
        if not path:
            if not startup:
                messagebox.showwarning("Файл не выбран", "Выберите файл конфигурации.", parent=self.root)
            return False
        try:
            from pathlib import Path
            from dataclasses import fields
            import json
            source = Path(path)
            raw = source.read_text(encoding="utf-8-sig")
            if source.suffix.lower() == ".json":
                data = json.loads(raw)
                if isinstance(data, dict) and isinstance(data.get("profile"), dict):
                    data = data["profile"]
                if not isinstance(data, dict):
                    raise ValueError("JSON должен содержать объект профиля.")
                allowed = {item.name for item in fields(self.app.profile())}
                for key, value in data.items():
                    if key in allowed and key != "hashes" and value is not None:
                        self.app.vars[key].set(str(value))
                if "hashes" in data:
                    self.app.hashes.delete("1.0", "end")
                    self.app.hashes.insert("1.0", str(data["hashes"]))
                if hasattr(self, "route_domains") and "direct_domains" in data:
                    self.route_domains.delete("1.0", "end")
                    self.route_domains.insert("1.0", str(data["direct_domains"] or ""))
                if hasattr(self, "route_ips") and "direct_ips" in data:
                    self.route_ips.delete("1.0", "end")
                    self.route_ips.insert("1.0", str(data["direct_ips"] or ""))
                self.apply_role("Администратор")
            elif "csqtt://" in raw:
                link = next((line.strip() for line in raw.splitlines() if "csqtt://" in line), raw.strip())
                self.app.vars["share_link"].set(link)
                self.apply_role("Клиент")
            else:
                try:
                    values = parse_admin_txt(raw)
                except UnicodeDecodeError:
                    values = parse_admin_txt(source.read_text(encoding="cp1251"))
                for key in ("server", "password", "proxy", "proxy_user", "proxy_password", "internet_mode"):
                    if key in values:
                        self.app.vars[key].set(values[key])
                if "hashes" in values:
                    self.app.hashes.delete("1.0", "end")
                    self.app.hashes.insert("1.0", values["hashes"])
                if "internet_mode" in values:
                    self.internet_choice.set("Через HTTP-прокси" if values["internet_mode"] == "proxy" else "Напрямую (Wi-Fi / мобильный интернет)")
                    self.update_internet_mode()
                self.apply_role("Администратор")
            if not startup:
                messagebox.showinfo("Конфигурация загружена", "Данные импортированы. Проверьте настройки перед подключением.", parent=self.root)
            return True
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
            if not startup:
                messagebox.showerror("Ошибка конфигурации", str(error), parent=self.root)
            else:
                self.app.append(f"Автозагрузка конфигурации не удалась: {error}")
            return False

    def import_admin_txt(self):
        filename = filedialog.askopenfilename(
            parent=self.root,
            title="Загрузить конфигурацию администратора",
            filetypes=[("Текстовые файлы", "*.txt"), ("Все файлы", "*.*")],
        )
        if not filename:
            return
        try:
            from pathlib import Path
            path = Path(filename)
            try:
                content = path.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError:
                content = path.read_text(encoding="cp1251")
            values = parse_admin_txt(content)
            for key in (
                "server", "password", "proxy", "proxy_user",
                "proxy_password", "internet_mode",
            ):
                if key in values:
                    self.app.vars[key].set(values[key])
            if "hashes" in values:
                self.app.hashes.delete("1.0", "end")
                self.app.hashes.insert("1.0", values["hashes"])
            if "internet_mode" in values:
                self.internet_choice.set(
                    "Через HTTP-прокси"
                    if values["internet_mode"] == "proxy"
                    else "Напрямую (Wi-Fi / мобильный интернет)"
                )
                self.update_internet_mode()
            messagebox.showinfo(
                "Конфигурация загружена",
                "Параметры TXT-файла внесены в поля администратора. Проверьте их перед подключением.",
                parent=self.root,
            )
        except (OSError, UnicodeError, ValueError) as error:
            messagebox.showerror("Ошибка TXT-конфигурации", str(error), parent=self.root)

    def settings_page(self):
        body = self.page_frame("settings")
        body.columnconfigure(0, weight=1, uniform="settings")
        body.columnconfigure(1, weight=1, uniform="settings")
        transport = self.section(body, "Параметры туннеля", "Режимы должны соответствовать настройкам сервера.")
        transport.grid(row=0, column=0, sticky="new", padx=(0, 14))
        label(transport.body, "Режим подключения", size=9, color=MUTED).pack(anchor="w", pady=(8, 5))
        mode_choice = tk.StringVar(value="TUN" if self.app.vars["mode"].get() == "tun" else "Прокси")
        mode_box = ttk.Combobox(transport.body, textvariable=mode_choice,
                                values=("Прокси", "TUN"), state="readonly")
        mode_box.pack(fill="x")
        mode_box.bind("<<ComboboxSelected>>", lambda _event: self.app.vars["mode"].set(
            "tun" if mode_choice.get() == "TUN" else "proxy"))
        tun_help = (
            "Прокси — SOCKS5/HTTP для выбранных приложений. TUN — системный IPv4 через Linux /dev/net/tun; при подключении потребуется подтверждение polkit и systemd-resolved. IPv6 пока не перенаправляется."
            if sys.platform == "linux" else
            "Прокси — SOCKS5/HTTP для выбранных приложений. TUN — системный IPv4 через Wintun; нужен запуск от имени администратора. IPv6 пока не перенаправляется."
        )
        label(transport.body, tun_help, color=DIM, size=8, wraplength=500, justify="left").pack(fill="x", pady=(7, 4))
        self.field(transport.body, "Потоки · workers", "workers")

        label(transport.body, "Транспорт TURN", size=9, color=MUTED).pack(anchor="w", pady=(14, 5))
        self.transport_choice = tk.StringVar(value={"auto": "Авто", "udp": "UDP", "tcp": "TCP"}.get(self.app.vars["turn_transport"].get(), "Авто"))
        transport_box = ttk.Combobox(transport.body, textvariable=self.transport_choice,
                                     values=("Авто", "UDP", "TCP"), state="readonly")
        transport_box.pack(fill="x")
        def update_transport(_event=None):
            self.app.vars["turn_transport"].set({"Авто": "auto", "UDP": "udp", "TCP": "tcp"}[self.transport_choice.get()])
        transport_box.bind("<<ComboboxSelected>>", update_transport)
        update_transport()

        for title, key, values, labels in (
            ("Маскировка · SRTP", "srtp", ("auto", "wrap", "dtls"), ("Авто", "WRAP-SRTP", "DTLS-SRTP")),
            ("TLS-отпечаток", "fingerprint", ("chrome", "firefox", "edge", "opera", "safari"), ("Chrome", "Firefox", "Edge", "Opera", "Safari")),
            ("Метод капчи", "captcha_mode", ("auto", "wv", "rjs"), ("Авто", "WebView", "Rust JS")),
        ):
            label(transport.body, title, size=9, color=MUTED).pack(anchor="w", pady=(14, 5))
            display = tk.StringVar(value=labels[values.index(self.app.vars[key].get())] if self.app.vars[key].get() in values else labels[0])
            picker = ttk.Combobox(transport.body, textvariable=display, values=labels, state="readonly")
            picker.pack(fill="x")
            def apply_choice(_event=None, key=key, values=values, labels=labels, display=display):
                self.app.vars[key].set(values[labels.index(display.get())])
            picker.bind("<<ComboboxSelected>>", apply_choice)
            apply_choice()

        self.field(transport.body, "TLS Client IDs (через запятую)", "client_ids")
        self.field(transport.body, "TURN-хост · необязательно", "turn")

        from csqtt_client.models.turn_subnets import subnet_titles
        label(transport.body, "TURN подсеть", size=9, color=MUTED).pack(anchor="w", pady=(14, 5))
        subnet_labels = ("Авто · адреса из ответа VK",) + subnet_titles()
        active_subnet = self.app.vars["turn_subnet"].get()
        subnet_choice = tk.StringVar(value=active_subnet if active_subnet else subnet_labels[0])
        subnet_box = ttk.Combobox(transport.body, textvariable=subnet_choice,
                                  values=subnet_labels, state="readonly")
        subnet_box.pack(fill="x")
        def update_subnet(_event=None):
            selected = subnet_choice.get()
            self.app.vars["turn_subnet"].set("" if selected == subnet_labels[0] else selected)
        subnet_box.bind("<<ComboboxSelected>>", update_subnet)
        update_subnet()

        label(transport.body, "Количество TURN-IP", size=9, color=MUTED).pack(anchor="w", pady=(10, 5))
        limit_labels = {"ALL": "Все", "1": "1", "2": "2", "4": "4", "9": "9"}
        reverse_limits = {value: key for key, value in limit_labels.items()}
        limit_choice = tk.StringVar(value=limit_labels.get(self.app.vars["turn_ip_limit"].get(), "Все"))
        limit_box = ttk.Combobox(transport.body, textvariable=limit_choice,
                                 values=tuple(limit_labels.values()), state="readonly")
        limit_box.pack(fill="x")
        def update_limit(_event=None):
            self.app.vars["turn_ip_limit"].set(reverse_limits[limit_choice.get()])
        limit_box.bind("<<ComboboxSelected>>", update_limit)
        update_limit()

        self.field(transport.body, "Свой список TURN-IP (необязательно)", "custom_turn_ips")
        self.field(transport.body, "DNS-сервер (переопределение)", "dns_override")
        label(transport.body, "Подсеть выбирает только кандидаты VK TURN. Свой список адресов имеет приоритет; пустые значения используют адреса из ответа VK.", color=DIM, size=8, wraplength=500, justify="left").pack(fill="x", pady=(6, 0))
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

    def routing_page(self, profile):
        body = self.page_frame("routing")
        body.columnconfigure(0, weight=1, uniform="routing")
        body.columnconfigure(1, weight=1, uniform="routing")

        domains = self.section(
            body,
            "Маршрутизация по доменам",
            "Чёрный список — эти домены идут напрямую, остальные через CSQTT. Белый список — только указанные домены через CSQTT, остальные напрямую.",
        )
        domains.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        self.domain_enabled = ttk.Checkbutton(
            domains.body, text="Включить правила доменов",
            variable=self.app.vars["domain_routing_enabled"], onvalue="1", offvalue="0",
        )
        self.domain_enabled.pack(anchor="w", pady=(6, 8))
        domain_mode = tk.StringVar(value="Белый список" if profile.domain_is_whitelist == "1" else "Чёрный список")
        domain_box = ttk.Combobox(domains.body, textvariable=domain_mode,
                                  values=("Чёрный список", "Белый список"), state="readonly")
        domain_box.pack(fill="x", pady=(0, 8))
        domain_box.bind("<<ComboboxSelected>>", lambda _e: self.app.vars["domain_is_whitelist"].set(
            "1" if domain_mode.get() == "Белый список" else "0"))
        self.app.vars["domain_is_whitelist"].set("1" if domain_mode.get() == "Белый список" else "0")
        self.route_domains = self.text(domains.body, height=10, expand=True)
        self.route_domains.surface.pack(fill="both", expand=True)
        self.route_domains.insert("1.0", profile.direct_domains)
        label(domains.body, "По одному на строку: vk.com, example.org", size=8, color=DIM).pack(anchor="w", pady=(7, 0))
        ttk.Checkbutton(
            domains.body, text="Исключать зоны RU / SU / РФ (только для чёрного списка)",
            variable=self.app.vars["exclude_ru_zones"], onvalue="1", offvalue="0",
        ).pack(anchor="w", pady=(9, 0))
        ttk.Checkbutton(
            domains.body, text="Использовать шаблонные домены",
            variable=self.app.vars["template_domains"], onvalue="1", offvalue="0",
        ).pack(anchor="w", pady=(6, 0))

        ips = self.section(
            body,
            "Маршрутизация по IP",
            "Поддерживаются IPv4, CIDR и диапазоны адресов.",
        )
        ips.grid(row=0, column=1, sticky="nsew")
        ttk.Checkbutton(
            ips.body, text="Включить правила IP",
            variable=self.app.vars["ip_routing_enabled"], onvalue="1", offvalue="0",
        ).pack(anchor="w", pady=(6, 8))
        ip_mode = tk.StringVar(value="Белый список" if profile.ip_is_whitelist == "1" else "Чёрный список")
        ip_box = ttk.Combobox(ips.body, textvariable=ip_mode,
                              values=("Чёрный список", "Белый список"), state="readonly")
        ip_box.pack(fill="x", pady=(0, 8))
        ip_box.bind("<<ComboboxSelected>>", lambda _e: self.app.vars["ip_is_whitelist"].set(
            "1" if ip_mode.get() == "Белый список" else "0"))
        self.app.vars["ip_is_whitelist"].set("1" if ip_mode.get() == "Белый список" else "0")
        self.route_ips = self.text(ips.body, height=10, expand=True)
        self.route_ips.surface.pack(fill="both", expand=True)
        self.route_ips.insert("1.0", profile.direct_ips)
        label(ips.body, "Примеры: 1.1.1.1 · 10.0.0.0/8 · 192.0.2.1-192.0.2.25",
              size=8, color=DIM).pack(anchor="w", pady=(7, 0))

        info = self.section(
            body,
            "Применение правил",
            "Правила передаются непосредственно Rust-ядру CSQTT и применяются к системному TUN. Для локального режима SOCKS5/HTTP маршрутизация ОС не меняется.",
        )
        info.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        label(info.body, "Изменения вступят в силу при следующем подключении.",
              color=MUTED, size=9).pack(anchor="w")

    def deploy_page(self, profile):
        body = self.page_frame("deploy")
        panel = self.section(
            body,
            "Управление сервером CSQTT",
            "Веб-панель сервера позволяет управлять пользователями, паролями, хешами звонков, лимитами и ссылками подключения.",
        )
        panel.pack(fill="x")
        self.field(panel.body, "Ссылка веб-панели", "panel_url")
        actions = frame(panel.body)
        actions.pack(fill="x", pady=(12, 0))
        ttk.Button(actions, text="Открыть веб-панель", command=self.app.open_panel).pack(side="left")
        ttk.Button(actions, text="Копировать ссылку", command=self.app.copy_panel_url).pack(side="left", padx=8)

        limits = self.section(
            body,
            "Что доступно в этой настольной сборке",
            "Подключение к существующему серверу, импорт профиля, работа с потоками, TURN, TUN, DNS, правила доменов и IP, проверка интернета и экспорт журнала.",
        )
        limits.pack(fill="x", pady=(14, 0))
        label(
            limits.body,
            "Полный SSH-деплой из Android-приложения (установка, обновление, переустановка и удаление серверной части) пока не перенесён в Windows/Linux-оболочку. Здесь не показываются фиктивные кнопки установки: используйте веб-панель либо SSH-инструменты администратора.",
            color=AMBER, size=9, wraplength=700, justify="left",
        ).pack(fill="x", pady=(4, 0))

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
        self.app.log = self.text(body, height=10, expand=True, state="disabled")
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.app.log.yview)
        scrollbar.pack(side="right", fill="y")
        self.app.log.configure(yscrollcommand=scrollbar.set)
        self.app.log.surface.pack(fill="both", expand=True)
        self.log_empty = label(self.app.log, "Журнал пока пуст\n\nЗдесь появятся события после подключения.",
                               color=DIM, size=11, anchor="center", justify="center")
        self.log_empty.place(relx=0.5, rely=0.45, anchor="center")
        self.app.log.tag_configure("error", foreground=RED)
        self.app.log.tag_configure("retry", foreground=AMBER)
        self.app.log.tag_configure("ready", foreground=MINT)
        label(body, "Пароли и хеши скрываются.   Ctrl+A — выделить всё   ·   Ctrl+C — копировать", size=9, color=DIM).pack(anchor="w", pady=(9, 0))

    def show_page(self, key):
        if key == self.page:
            return
        self.page = key
        for name in ("connection", "settings", "routing", "deploy", "logs"):
            page = getattr(self, name)
            if not hasattr(page, "focus_targets"):
                page.focus_targets = []
                def collect(widget):
                    if isinstance(widget, (ttk.Entry, ttk.Button, ttk.Checkbutton, tk.Text)):
                        page.focus_targets.append((widget, widget.cget("takefocus")))
                    for child in widget.winfo_children():
                        collect(child)
                collect(page)
                for widget, original in page.focus_targets:
                    def can_focus(window, name=name, widget=widget, original=original):
                        if self.page != name or str(original) == "0":
                            return False
                        return not isinstance(widget, ttk.Widget) or not widget.instate(["disabled"])
                    widget.configure(takefocus=can_focus)
        focused = self.root.focus_get()
        if focused and str(focused).startswith(str(self.pages)) and not str(focused).startswith(str(getattr(self, key))):
            self.nav[key].focus_set()
        titles = {
            "connection": ("Подключение", "Профили, сервер CSQTT, VK-хеши и способ выхода в интернет."),
            "settings": ("Туннель", "Режим TUN или прокси, транспорт TURN, маскировка и параметры сессии."),
            "routing": ("Роутинг", "Маршрутизация IPv4 и доменов через туннель или напрямую."),
            "deploy": ("Деплой", "Веб-панель и управление существующим сервером CSQTT."),
            "logs": ("Журнал", "Состояние ядра, потоки, трафик и диагностика подключения."),
        }
        title, subtitle = titles[key]
        self.heading.configure(text=title)
        self.subtitle.configure(text=subtitle)
        for name, button in self.nav.items():
            button.configure(style="Selected.Nav.TButton" if name == key else "Nav.TButton",
                             image=self.nav_images[name][1 if name == key else 0])
        getattr(self, key).tkraise()

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

    def show_proxy_result(self, state, message):
        color = {"checking": AMBER, "success": MINT, "error": RED}[state]
        self.proxy_feedback.configure(text=message, fg=color)
        self.root.after_idle(self.reveal_proxy_result)

    def reveal_proxy_result(self):
        if self.page != "connection" or not self.proxy_feedback.winfo_ismapped():
            return
        page = self.connection
        bottom = self.proxy_feedback.winfo_rooty() - page.body.winfo_rooty() + self.proxy_feedback.winfo_height() + 10
        visible_bottom = page.canvas.canvasy(0) + page.canvas.winfo_height()
        if bottom > visible_bottom:
            page.canvas.yview_moveto(max(0, bottom - page.canvas.winfo_height()) / max(1, page.body.winfo_height()))

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
