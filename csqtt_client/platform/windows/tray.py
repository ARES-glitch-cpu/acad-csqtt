"""Windows tray callbacks are delivered to Tk through the application's queue."""
import threading

import pystray
from PIL import Image

from csqtt_client.config import ASSETS


class TrayIcon:
    def __init__(self, events, title):
        self.events = events
        self.ready = threading.Event()
        self.closed = threading.Event()
        with Image.open(ASSETS / "icons/CS_logo.png") as source:
            image = source.convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)
        self.icon = pystray.Icon("csqtt", image, title, menu=pystray.Menu(
            pystray.MenuItem("Открыть", lambda: events.put(("tray_open", None)), default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Выход", lambda: events.put(("tray_exit", None))),
        ))
        self.thread = threading.Thread(target=self.run, name="csqtt-tray", daemon=True)
        self.thread.start()

    def run(self):
        try:
            self.icon.run(self.setup)
        except Exception as error:
            self.events.put(("tray_error", str(error)))

    def setup(self, icon):
        try:
            if self.closed.is_set():
                icon.stop()
            else:
                icon.visible = True
                self.ready.set()
        except Exception as error:
            self.events.put(("tray_error", str(error)))
            icon.stop()

    def stop(self):
        self.closed.set()
        self.icon.stop()
        if threading.current_thread() is not self.thread:
            self.thread.join(timeout=2)
