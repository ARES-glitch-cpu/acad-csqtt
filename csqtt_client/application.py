"""Desktop controller: UI events and the connection process lifecycle."""
from dataclasses import asdict, replace
import ctypes
import os
import http.client
import ipaddress
import json
from pathlib import Path
import queue
import re
import socket
import ssl
import subprocess
import threading
import shutil
import sys
import uuid
import time
import tkinter as tk
from tkinter import filedialog, messagebox

from csqtt_client.config import APP_VERSION, ROOT, NO_WINDOW, CORE_FILENAME, HELPER_FILENAME
from csqtt_client.models.profile import Profile
from csqtt_client.models.share_link import parse_csqtt_link
if os.name == "nt":
    from csqtt_client.platform.windows.profiles import load_profile, save_profile, delete_profile, profile_exists
else:
    from csqtt_client.platform.linux.profiles import load_profile, save_profile, delete_profile, profile_exists
from csqtt_client.services.proxy import proxy_connect
from csqtt_client.services.tunnel import core_command


class App:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.core = self.helper = None
        self.session = 0
        self.ready = False
        self.config = None
        self.running_profile = None
        self.secrets = []
        self.closing = False
        self.stopping = False
        self.tray = None
        self.tun_recovery_error = None
        self.tun_uds = None
        self.tun_bypass_ips = []
        try:
            profile = load_profile()
        except Exception:
            profile = Profile()
        self.vars = {k: tk.StringVar(value=str(v)) for k, v in asdict(profile).items()}
        self.remember = tk.BooleanVar(value=profile_exists())
        self.status = tk.StringVar(value="Укажите сервер и прокси, затем нажмите «Подключить».")
        from csqtt_client.ui.desktop import DesktopUI
        self.ui = DesktopUI(self, root, profile, APP_VERSION, ROOT)
        self.log.bind("<Control-a>", self.select_log)
        self.log.bind("<Control-A>", self.select_log)
        self.log.bind("<Control-c>", lambda event: self.copy_log(selected=True))
        self.log.bind("<Control-C>", lambda event: self.copy_log(selected=True))
        self.log_menu = tk.Menu(root, tearoff=False, bg="#25272c", fg="#eeeef0",
                                activebackground="#37393f", activeforeground="#ffffff")
        self.log_menu.add_command(label="Копировать выделение", command=lambda: self.copy_log(selected=True))
        self.log_menu.add_command(label="Скопировать весь журнал", command=self.copy_log)
        self.log_menu.add_command(label="Выделить всё", command=self.select_log)
        self.log.bind("<Button-3>", self.show_log_menu)
        self.recover_tun_state()
        root.protocol("WM_DELETE_WINDOW", self.hide_to_tray if os.name == "nt" else self.close)
        root.bind("<Unmap>", self.on_minimize)
        root.bind("<Destroy>", self.on_destroy, add="+")
        root.after(100, self.poll)

    def recover_tun_state(self):
        """Remove stale TUN routes left by an interrupted previous run."""
        helper = ROOT / "bin" / HELPER_FILENAME
        if os.name != "nt" or not helper.exists():
            return
        try:
            result = subprocess.run(
                [str(helper), "--recover-tun"], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=20, creationflags=NO_WINDOW,
            )
            output = (result.stdout or result.stderr or "").strip()
            if result.returncode:
                self.tun_recovery_error = output or f"Код {result.returncode}"
                self.append("Не удалось восстановить сетевые настройки после предыдущего TUN-сеанса: " + self.tun_recovery_error)
            elif "TUN_RECOVERED" in output:
                self.append("Восстановлены маршруты и DNS после прерванного TUN-сеанса.")
        except Exception as error:
            self.tun_recovery_error = str(error)
            self.append(f"Проверка аварийного восстановления TUN не выполнена: {error}")

    def start_tray(self):
        from csqtt_client.platform.windows.tray import TrayIcon
        self.tray = TrayIcon(self.events, f"CSQTT v{APP_VERSION}")

    def hide_to_tray(self):
        if self.closing:
            return
        if self.tray and self.tray.ready.is_set():
            self.root.withdraw()
        elif self.tray:
            self.show_window()
        else:
            self.close()

    def on_minimize(self, event):
        if os.name == "nt" and event.widget is self.root and self.root.state() == "iconic":
            self.hide_to_tray()

    def show_window(self):
        if not self.closing:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()

    def on_destroy(self, event):
        if event.widget is self.root:
            self.ui.chrome.stop()
            for callback in self.root.tk.call("after", "info"):
                self.root.after_cancel(callback)
            if self.tray:
                self.tray.stop()
                self.tray = None

    def select_log(self, event=None):
        self.log.focus_set()
        self.log.tag_add("sel", "1.0", "end-1c")
        return "break"

    def copy_log(self, selected=False):
        # Export the text already masked by append(), never the raw process output.
        try:
            text = self.log.get("sel.first", "sel.last") if selected else self.log.get("1.0", "end-1c")
        except tk.TclError:
            text = self.log.get("1.0", "end-1c")
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.copy_log_button.configure(text="Скопировано")
        self.root.after(1800, lambda: self.copy_log_button.configure(text="Скопировать журнал"))
        return "break"

    def save_log(self):
        filename = filedialog.asksaveasfilename(
            parent=self.root, title="Сохранить журнал CSQTT", defaultextension=".txt",
            initialfile="csqtt-log.txt", filetypes=[("Текстовый журнал", "*.txt"), ("Все файлы", "*.*")],
        )
        if filename:
            try:
                Path(filename).write_text(self.log.get("1.0", "end-1c"), encoding="utf-8")
            except OSError as error:
                messagebox.showerror("Не удалось сохранить журнал", str(error), parent=self.root)

    def show_log_menu(self, event):
        try:
            self.log_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.log_menu.grab_release()
        return "break"

    def profile(self):
        return Profile(**{**{k: v.get() for k, v in self.vars.items()}, "hashes": self.hashes.get("1.0", "end").strip()})

    def append(self, message):
        # Core messages can contain partial hashes; mask these as well as passwords.
        for value in self.secrets:
            if value:
                message = message.replace(value, "[скрыто]")
        message = re.sub(r"(?i)(access_token|client_secret|password|secret)=([^\s&]+)", r"\1=[скрыто]", message)
        self.log.configure(state="normal")
        self.ui.log_empty.place_forget()
        lower = message.lower()
        tag = "error" if any(s in lower for s in ("ошиб", "fatal", "denied", "failed")) else (
            "retry" if any(s in lower for s in ("retry", "timeout", "повтор")) else (
                "ready" if any(s in lower for s in ("[ready]", "успеш", "интернет через csqtt работает")) else ""))
        self.log.insert("end", time.strftime("%H:%M:%S ") + message.rstrip() + "\n", tag)
        if int(self.log.index("end-1c").split(".")[0]) > 450:
            self.log.delete("1.0", "100.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def background(self, function):
        threading.Thread(target=function, daemon=True).start()

    def check_proxy(self):
        profile = self.profile()
        if profile.internet_mode != "proxy":
            self.ui.show_proxy_result("error", "Выбран прямой режим. HTTP-прокси не используется.")
            return
        self.check_proxy_button.configure(state="disabled")
        self.ui.show_proxy_result("checking", "Проверяю прокси…")
        def work():
            try:
                target = f"{profile.turn.strip() or 'dns.google'}:443"
                proxy_connect(profile, target)
                self.events.put(("proxy_result", (True, f"Прокси {profile.proxy} доступен. CONNECT :443 разрешён.")))
            except Exception as error:
                message = str(error)
                if profile.proxy_password:
                    message = message.replace(profile.proxy_password, "[скрыто]")
                self.events.put(("proxy_result", (False, f"Не удалось подключиться к прокси {profile.proxy}.\n{message}")))
        self.background(work)

    def start(self):
        try:
            profile = self.profile()
            if self.ui.role == "client":
                share = parse_csqtt_link(self.vars["share_link"].get())
                server_password = share.password or profile.client_password
                if not server_password:
                    raise ValueError(
                        "В ссылке нет пароля CSQTT. Введите его в поле ниже или попросите администратора выдать ссылку с паролем."
                    )
                profile = replace(
                    profile,
                    server=share.server,
                    password=server_password,
                    hashes="\n".join(share.hashes) if share.hashes else profile.hashes,
                )
            hashes = profile.validate()
            if not (ROOT / "bin" / CORE_FILENAME).exists() or not (ROOT / "bin" / HELPER_FILENAME).exists():
                raise ValueError(f"Не найдены bin/{CORE_FILENAME} и bin/{HELPER_FILENAME}. Распакуйте portable целиком.")
            if profile.mode == "tun":
                if self.tun_recovery_error:
                    raise ValueError("Сначала восстановите сетевые настройки Windows: " + self.tun_recovery_error)
                if os.name == "nt" and not ctypes.windll.shell32.IsUserAnAdmin():
                    raise ValueError("Режим TUN требует прав администратора. Закройте CSQTT и запустите его через «Запуск от имени администратора». Режим Proxy работает без повышения прав.")
                if sys.platform == "linux" and os.geteuid() != 0 and not shutil.which("pkexec"):
                    raise ValueError("Для Linux TUN установите polkit (команда pkexec) и запустите приложение из графического сеанса.")
            else:
                # Check listener conflicts before establishing local proxies.
                for port in (profile.socks_port, profile.http_port):
                    with socket.socket() as check:
                        check.bind(("127.0.0.1", int(port)))
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as check:
                check.bind(("127.0.0.1", 0))
                self.packet_port = check.getsockname()[1]
            self.tun_uds = f"csqtt-{uuid.uuid4().hex}" if profile.mode == "tun" and sys.platform == "linux" else None
            args, env = core_command(profile, self.packet_port, self.tun_uds)
            if self.remember.get():
                save_profile(profile)
            else:
                delete_profile()
            self.session += 1
            self.ready = False
            self.config = None
            self.running_profile = profile
            self.tun_bypass_ips = []
            self.secrets = sorted([profile.password, profile.client_password, profile.proxy_password, profile.salt, profile.share_link, *hashes, *(h[:8] for h in hashes)], key=len, reverse=True)
            self.core = subprocess.Popen(args, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
            self.read_process(self.core, "core", self.session)
            self.status.set("Подключение: получаю TURN-сессию и конфигурацию сервера…")
            self.ui.set_state("connecting")
            self.active_count.set("0")
            self.upload_total.set("0.00")
            self.download_total.set("0.00")
            self.start_button.configure(state="disabled")
            self.stop_button.configure(state="normal")
            mode_text = ("системный TUN (Linux /dev/net/tun)" if sys.platform == "linux" else "системный TUN (Wintun)") if profile.mode == "tun" else "локальные SOCKS5/HTTP-прокси"
            internet_text = "прямое TCP-подключение через интернет" if profile.internet_mode == "direct" else "через корпоративный HTTP CONNECT"
            self.append(f"Запущено ядро: {internet_text}; TURN :443; режим: {mode_text}. Потоков запрошено: {profile.workers}, хешей: {len(hashes)}.")
        except Exception as error:
            self.ui.show_page("connection")
            messagebox.showerror("Не удалось начать подключение", str(error))

    def read_process(self, process, kind, session):
        def read():
            for line in process.stdout:
                self.events.put(("process", (session, kind, line.rstrip())))
            self.events.put(("exit", (session, kind, process.wait())))
        self.background(read)

    def start_helper(self):
        if self.helper or not self.ready or not self.config:
            return
        profile = self.running_profile
        ip, dns = self.config
        args = [str(ROOT / "bin" / HELPER_FILENAME), "--mode", profile.mode,
                "--core", f"127.0.0.1:{self.packet_port}", "--ip", ip, "--dns", dns]
        if profile.mode == "tun":
            if profile.internet_mode == "proxy":
                bypass_ips = [profile.proxy.rsplit(":", 1)[0]]
            else:
                bypass_ips = list(self.tun_bypass_ips)
                if profile.turn.strip():
                    try:
                        for result in socket.getaddrinfo(profile.turn.strip(), 443, socket.AF_INET, socket.SOCK_STREAM):
                            address = result[4][0]
                            if address not in bypass_ips:
                                bypass_ips.append(address)
                    except OSError as error:
                        self.append(f"Не удалось разрешить TURN-хост для обходного маршрута: {error}")
                if not bypass_ips:
                    self.append("Не получены адреса TURN для обходного маршрута. TUN не запускаю, чтобы не зациклить соединение.")
                    self.stop()
                    return
            args += ["--bypass-ip", ",".join(bypass_ips)]
            # The native helper must watch the GUI process on every OS.
            # Linux additionally receives the TUN file descriptor over UDS.
            args += ["--parent-pid", str(os.getpid())]
            if self.tun_uds:
                args += ["--tun-uds", self.tun_uds]
            if sys.platform == "linux" and os.geteuid() != 0:
                args.insert(0, shutil.which("pkexec"))
        else:
            args += ["--socks", f"127.0.0.1:{profile.socks_port}",
                     "--http", f"127.0.0.1:{profile.http_port}"]
        try:
            self.helper = subprocess.Popen(args, stdin=subprocess.PIPE if profile.mode == "tun" else None,
                                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                           encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
            self.read_process(self.helper, "helper", self.session)
        except Exception as error:
            self.append(f"Не запущен локальный прокси: {error}")
            self.stop()

    def process_line(self, kind, line):
        if kind == "core" and line.startswith("TUN_BYPASS:"):
            try:
                address = str(ipaddress.IPv4Address(line.split(":", 1)[1].strip()))
                if address not in self.tun_bypass_ips:
                    self.tun_bypass_ips.append(address)
            except ValueError:
                self.append("Пропущен некорректный адрес TURN для обходного маршрута TUN.")
            return
        if kind == "helper" and (line.startswith("PROXY_READY") or line.startswith("TUN_READY")):
            if line.startswith("TUN_READY"):
                self.status.set("Системный TUN поднят. Проверяю доступ в интернет…")
                description = "Linux /dev/net/tun" if sys.platform == "linux" else "Wintun"
                self.append(f"{description} и системные маршруты настроены; внешний транспорт CSQTT исключён из TUN.")
            else:
                self.status.set("Туннель готов, локальные прокси запущены. Проверяю интернет…")
            self.ui.set_state("checking")
            self.test_button.configure(state="normal")
            self.check_internet()
        if line.startswith("__CSQTT_EVENT__|"):
            try:
                _, name, data = line.split("|", 2)
                payload = json.loads(data)
                if name == "CONFIG":
                    fields = payload["config"].split(":")
                    if fields[0] != "TUNCONF" or len(fields) < 3:
                        raise ValueError("Сервер не выдал конфигурацию TUNCONF.")
                    ipaddress.IPv4Address(fields[1])
                    config = (fields[1], fields[2])
                    if self.config and self.config != config:
                        self.append("Сервер изменил IP/DNS: переподключите клиент.")
                        self.stop()
                        return
                    self.config = config
                elif name == "READY":
                    self.ready = True
                elif name == "STATS":
                    self.active_count.set(str(payload.get("active", 0)))
                    self.upload_total.set(f"{payload.get('bytes_up', 0)/1048576:.2f}")
                    self.download_total.set(f"{payload.get('bytes_down', 0)/1048576:.2f}")
                elif name in ("ACTIVE_ZERO", "SERVER_RESTART", "NETWORK_SUSPECT"):
                    self.status.set("Связь с сервером потеряна; ядро пытается восстановить туннель…")
                    self.ui.set_state("recovering")
                elif name == "ERROR":
                    self.append(str(payload.get("message", payload)))
                self.start_helper()
            except (ValueError, KeyError) as error:
                self.append(f"Ошибка события ядра: {error}")
            return
        self.append(line)

    def check_internet(self):
        if not self.helper or not self.running_profile:
            return
        profile, session = self.running_profile, self.session
        self.test_button.configure(state="disabled")
        def work():
            conn = None
            succeeded = False
            try:
                if profile.mode == "tun":
                    # The Windows /1 routes direct this request through Wintun.
                    conn = http.client.HTTPSConnection("api.ipify.org", 443, timeout=25, context=ssl.create_default_context())
                    conn.request("GET", "/", headers={"Host": "api.ipify.org", "Connection": "close"})
                else:
                    # Explicit CONNECT to the LOCAL proxy, unaffected by proxy environment variables.
                    conn = http.client.HTTPSConnection("127.0.0.1", int(profile.http_port), timeout=25, context=ssl.create_default_context())
                    conn.set_tunnel("api.ipify.org", 443)
                    conn.request("GET", "/", headers={"Host": "api.ipify.org", "Connection": "close"})
                response = conn.getresponse()
                if response.status != 200:
                    raise ValueError(f"Проверка IP вернула HTTP {response.status}")
                address = str(ipaddress.ip_address(response.read(128).decode().strip()))
                result = f"Интернет через csqtt работает. Внешний IP: {address}"
                succeeded = True
            except Exception:
                result = "Туннель запущен, но интернет не подтверждён. Проверьте журнал, DNS и параметры сервера." if profile.mode == "tun" else "Локальные прокси запущены, но интернет не подтверждён. Проверьте журнал и параметры сервера."
            finally:
                if conn:
                    conn.close()
                self.events.put(("internet", (session, result, succeeded)))
        self.background(work)

    def stop(self):
        if self.stopping:
            return
        self.stopping = True
        self.session += 1
        processes = [p for p in (self.helper, self.core) if p]
        self.helper = self.core = None
        for process in processes:
            if process.stdin:
                try:
                    process.stdin.write("STOP\n")
                    process.stdin.flush()
                except (OSError, ValueError):
                    pass
        def cleanup():
            for process in processes:
                try:
                    process.wait(timeout=8 if process.stdin else 3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                if process.stdin:
                    process.stdin.close()
                if process.stdout:
                    process.stdout.close()
            self.events.put(("cleaned", None))
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="disabled")
        self.test_button.configure(state="disabled")
        self.status.set("Отключение…")
        self.ui.set_state("stopping")
        # Keep cleanup alive if the window closes while STOP is pending.
        threading.Thread(target=cleanup, daemon=False).start()

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.root.withdraw()
        self.stop()

    def poll(self):
        for _ in range(200):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "process":
                session, source, line = value
                if session == self.session:
                    self.process_line(source, line)
            elif kind == "exit":
                session, source, code = value
                if session == self.session:
                    self.append(f"{source}: процесс завершился (код {code}).")
                    self.stop()
            elif kind == "message":
                self.append(value)
            elif kind == "proxy_result":
                success, message = value
                self.ui.show_proxy_result("success" if success else "error", message)
                self.append(message)
                self.check_proxy_button.configure(state="normal")
            elif kind == "internet":
                session, result, succeeded = value
                if session == self.session:
                    self.status.set(result)
                    self.ui.set_state("online" if succeeded else "unconfirmed")
                    self.append(result)
                    self.test_button.configure(state="normal")
            elif kind == "cleaned":
                self.stopping = False
                if self.closing:
                    self.root.destroy()
                    return
                self.status.set("Отключено")
                self.active_count.set("0")
                self.ui.set_state("offline")
                self.start_button.configure(state="normal")
            elif kind == "tray_open":
                self.show_window()
            elif kind == "tray_exit":
                self.close()
            elif kind == "tray_error":
                if self.tray:
                    self.tray.stop()
                    self.tray = None
                self.show_window()
                self.append(f"Не удалось создать значок в трее: {value}")
        self.root.after(100, self.poll)
