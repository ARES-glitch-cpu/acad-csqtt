import base64
import hashlib
import unittest

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from csqtt_client.models.share_link import parse_csqtt_link
from csqtt_client.models.admin_txt import parse_admin_txt


class ShareLinkTests(unittest.TestCase):
    def encrypted_link(self, plain: bytes) -> str:
        nonce = bytes(range(12))
        key = hashlib.sha256(b"csqtt-chiper-key").digest()
        cipher_text = AESGCM(key).encrypt(nonce, plain, None)
        return "csqtt://" + base64.urlsafe_b64encode(nonce + cipher_text).decode().rstrip("=")

    def test_encrypted_panel_link(self):
        plain = (
            b"connect?v=2&host=server.example&peer=46000&"
            b"password=server%2Bpassword&hashes=abcdefghijklmnop1234"
            b"+zyxwvutsrqponmlk4321"
        )
        parsed = parse_csqtt_link(self.encrypted_link(plain))
        self.assertEqual(parsed.server, "server.example:46000")
        self.assertEqual(parsed.password, "server+password")
        self.assertEqual(parsed.hashes, ("abcdefghijklmnop1234", "zyxwvutsrqponmlk4321"))

    def test_encrypted_link_without_call_hashes(self):
        plain = b"connect?v=2&host=10.20.30.40&peer=46000&password=secret"
        parsed = parse_csqtt_link(self.encrypted_link(plain))
        self.assertEqual(parsed.server, "10.20.30.40:46000")
        self.assertEqual(parsed.password, "secret")
        self.assertEqual(parsed.hashes, ())

    def test_plain_base64_fallback(self):
        plain = b"connect?v=2&host=csqtt.example&peer=46000&password=secret"
        encoded = base64.urlsafe_b64encode(plain).decode().rstrip("=")
        parsed = parse_csqtt_link("csqtt://" + encoded)
        self.assertEqual(parsed.server, "csqtt.example:46000")

    def test_explicit_connect_link(self):
        parsed = parse_csqtt_link(
            "csqtt://connect?v=2&host=csqtt.example&peer=46000&password=p%40ss"
        )
        self.assertEqual(parsed.password, "p@ss")

    def test_legacy_link(self):
        parsed = parse_csqtt_link("csqtt://secret@127.0.0.1:46000")
        self.assertEqual(parsed.server, "127.0.0.1:46000")
        self.assertEqual(parsed.password, "secret")

    def test_bad_link_does_not_echo_secret(self):
        secret = "not-a-real-secret"
        with self.assertRaises(ValueError) as error:
            parse_csqtt_link("csqtt://connect?v=2&host=bad&password=" + secret + "&password=second")
        self.assertNotIn(secret, str(error.exception))


class AdminTxtTests(unittest.TestCase):
    def test_admin_txt_with_multiple_call_links(self):
        values = parse_admin_txt(
            "server=10.0.0.5:46000\n"
            "server_password=server-secret\n"
            "call=https://vk.com/call/join/abcdefghijklmnop1234\n"
            "call=zyxwvutsrqponmlk4321\n"
            "proxy=192.0.2.10:3128\n"
            "proxy_login=operator\n"
            "proxy_password=proxy-secret\n"
            "internet_mode=proxy\n"
        )
        self.assertEqual(values["server"], "10.0.0.5:46000")
        self.assertEqual(values["password"], "server-secret")
        self.assertEqual(values["proxy"], "192.0.2.10:3128")
        self.assertEqual(values["proxy_user"], "operator")
        self.assertEqual(values["proxy_password"], "proxy-secret")
        self.assertEqual(values["internet_mode"], "proxy")
        self.assertEqual(values["hashes"].splitlines(), ["abcdefghijklmnop1234", "zyxwvutsrqponmlk4321"])

    def test_admin_txt_requires_complete_host_port_pair(self):
        with self.assertRaisesRegex(ValueError, "оба параметра"):
            parse_admin_txt("server_host=10.0.0.5\n")

    def test_admin_txt_rejects_unknown_keys(self):
        with self.assertRaisesRegex(ValueError, "неизвестный параметр"):
            parse_admin_txt("mystery=value\n")

    def test_admin_txt_without_proxy_clears_proxy_and_call_fields(self):
        values = parse_admin_txt(
            "server=csqtt.example:46000\n"
            "server_password=server-secret\n"
        )
        self.assertEqual(values["internet_mode"], "direct")
        self.assertEqual(values["proxy"], "")
        self.assertEqual(values["proxy_user"], "")
        self.assertEqual(values["proxy_password"], "")
        self.assertEqual(values["hashes"], "")

    def test_admin_txt_requires_server_and_server_password(self):
        with self.assertRaisesRegex(ValueError, "не указан server"):
            parse_admin_txt("server_password=secret\n")
        with self.assertRaisesRegex(ValueError, "не указан пароль сервера"):
            parse_admin_txt("server=csqtt.example:46000\n")


if __name__ == "__main__":
    unittest.main()
