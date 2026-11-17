"""Entry point for python -m csqtt_client."""
import ctypes
import sys
import tkinter as tk

from csqtt_client.application import App


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CSQTT.Desktop")
    root = tk.Tk()
    ui = App(root)
    if sys.platform == "win32":
        ui.start_tray()
    if "--smoke" in sys.argv:
        root.after(700, ui.close)
    root.mainloop()


if __name__ == "__main__":
    main()
