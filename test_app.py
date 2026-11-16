import base64
from dataclasses import replace
import json
import os
import socket
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

import app


class ClientTests(unittest.TestCase):
    def profile(self):
        return app.Profile(server="203.0.113.2:443", password="server-test-secret",
                           hashes="testhash123456", proxy_user="proxy-test-user", proxy_password="proxy-test-secret")

    def test_tcp_proxy_command_and_secret_environment(self):
        profile = self.profile()
        args, env = app.core_command(profile, 9000)
        self.assertEqual(args[args.index("--turn-transport") + 1], "tcp")
        self.assertEqual(args[args.index("--port") + 1], "443")
        self.assertNotIn(profile.password, args)
        self.assertNotIn(profile.proxy_password, args)
        self.assertEqual(env["CSQTT_PASSWORD"], profile.password)
        self.assertEqual(env["CSQTT_PROXY_PASSWORD"], profile.proxy_password)
        self.assertNotIn("NO_PROXY", env)

    def test_hash_normalization_and_validation(self):
        self.assertEqual(app.normalize_hashes("https://vk.com/call/join/abc123?x=1\nabc123;def456"), ["abc123", "def456"])
        for profile in [replace(self.profile(), hashes=""), replace(self.profile(), socks_port="8080"),
                        replace(self.profile(), workers="0"), replace(self.profile(), proxy="proxy.invalid:3128"),
                        replace(self.profile(), turn="turn:example.com:443"), replace(self.profile(), password="")]:
            with self.assertRaises(ValueError):
                profile.validate()

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI")
    def test_profile_encryption_roundtrip(self):
        plain = json.dumps({"secret": "test-only-secret"}).encode()
        encrypted = app.dpapi(plain)
        self.assertNotIn(b"test-only-secret", encrypted)
        self.assertEqual(app.dpapi(encrypted, decrypt=True), plain)

    def fake_proxy(self, status):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        captured = []
        def handle():
            try:
                with listener.accept()[0] as conn:
                    data = bytearray()
                    while not data.endswith(b"\r\n\r\n"):
                        data.extend(conn.recv(1))
                    captured.append(bytes(data))
                    conn.sendall(f"HTTP/1.1 {status}\r\n\r\n".encode())
            finally:
                listener.close()
        thread = threading.Thread(target=handle)
        thread.start()
        return f"127.0.0.1:{listener.getsockname()[1]}", captured, thread

    def test_authenticated_connect(self):
        address, captured, thread = self.fake_proxy("200 Connection established")
        profile = replace(self.profile(), proxy=address)
        app.proxy_connect(profile, "turn.example:443")
        thread.join(timeout=3)
        expected = base64.b64encode(f"{profile.proxy_user}:{profile.proxy_password}".encode())
        self.assertIn(b"CONNECT turn.example:443 HTTP/1.1", captured[0])
        self.assertIn(b"Proxy-Authorization: Basic " + expected, captured[0])

    def test_proxy_auth_failure(self):
        address, captured, thread = self.fake_proxy("407 Proxy Authentication Required")
        with self.assertRaisesRegex(ValueError, "407"):
            app.proxy_connect(replace(self.profile(), proxy=address), "turn.example:443")
        thread.join(timeout=3)

    @unittest.skipUnless((app.ROOT / "bin/csqtt-core.exe").exists(), "Build the Windows core first")
    def test_built_core_routes_vk_through_authenticated_proxy(self):
        address, captured, thread = self.fake_proxy("407 Proxy Authentication Required")
        profile = replace(self.profile(), proxy=address)
        args, env = app.core_command(profile, 19090)
        process = subprocess.Popen(args, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, creationflags=app.NO_WINDOW)
        try:
            thread.join(timeout=12)
            self.assertTrue(captured, "Built core did not contact the explicit proxy")
            self.assertIn(b"CONNECT api.vk.me:443 HTTP/1.1", captured[0])
            expected = base64.b64encode(f"{profile.proxy_user}:{profile.proxy_password}".encode())
            self.assertIn(b"proxy-authorization: basic " + expected.lower(), captured[0].lower())
            output, _ = process.communicate(b"STOP\n", timeout=8)
            self.assertNotIn(profile.password.encode(), output)
            self.assertNotIn(profile.proxy_password.encode(), output)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()


@unittest.skipUnless(os.name == "nt", "Windows native GUI")
class LogExportTests(unittest.TestCase):
    def setUp(self):
        self.root = app.tk.Tk()
        self.root.withdraw()
        with patch.object(app, "load_profile", return_value=app.Profile()):
            self.ui = app.App(self.root)
        self.ui.secrets = ["test-only-password", "test-only-hash"]
        self.ui.append("Ошибка потока 18: test-only-password test-only-hash")
        self.expected = self.ui.log.get("1.0", "end-1c")

    def tearDown(self):
        self.root.destroy()

    def test_copy_disabled_log_and_selection(self):
        self.ui.copy_log()
        self.assertEqual(self.root.clipboard_get(), self.expected)
        self.assertNotIn("test-only-password", self.root.clipboard_get())
        self.assertNotIn("test-only-hash", self.root.clipboard_get())
        self.assertIn("[скрыто]", self.root.clipboard_get())
        self.ui.log.tag_add("sel", "1.0", "1.5")
        selected = self.ui.log.get("sel.first", "sel.last")
        self.ui.copy_log(selected=True)
        self.assertEqual(self.root.clipboard_get(), selected)
        self.ui.select_log()
        self.assertEqual(self.ui.log.get("sel.first", "sel.last"), self.expected)
        self.assertEqual(self.ui.log.cget("state"), "disabled")

    def test_save_masked_utf8_log(self):
        with tempfile.TemporaryDirectory() as directory:
            filename = app.Path(directory) / "журнал.txt"
            with patch.object(app.filedialog, "asksaveasfilename", return_value=str(filename)):
                self.ui.save_log()
            self.assertEqual(filename.read_text(encoding="utf-8"), self.expected)


if __name__ == "__main__":
    unittest.main()
