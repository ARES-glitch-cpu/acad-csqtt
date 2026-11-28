import unittest
from dataclasses import replace

from csqtt_client.models.profile import Profile
from csqtt_client.services.tunnel import core_command, resolve_turn_transport


def base_profile():
    return Profile(
        server="203.0.113.2:443",
        password="server-test-secret",
        hashes="testhash123456",
    )


class DesktopAndroidPortTests(unittest.TestCase):
    def test_direct_transport_keeps_vk_uri_port(self):
        profile = base_profile()
        args, _ = core_command(profile, 9000)
        self.assertNotIn("--port", args)

    def test_proxy_mode_pins_turn_to_443(self):
        profile = replace(
            base_profile(),
            internet_mode="proxy",
            proxy="192.0.2.10:3128",
        )
        args, _ = core_command(profile, 9000)
        self.assertEqual(args[args.index("--turn-transport") + 1], "tcp")
        self.assertEqual(args[args.index("--port") + 1], "443")

    def test_auto_transport_selects_udp_direct_and_tcp_via_proxy(self):
        direct = base_profile()
        proxy = replace(direct, internet_mode="proxy", proxy="192.0.2.10:3128")
        self.assertEqual(resolve_turn_transport(direct), "udp")
        self.assertEqual(resolve_turn_transport(proxy), "tcp")
        self.assertEqual(resolve_turn_transport(direct, "tcp"), "tcp")
        self.assertEqual(resolve_turn_transport(proxy, "udp"), "udp")

    def test_core_command_passes_turn_fingerprint_and_captcha_settings(self):
        profile = replace(
            base_profile(),
            turn_transport="tcp",
            fingerprint="firefox",
            captcha_mode="rjs",
            client_ids="8202606,6287487",
            custom_turn_ips="192.0.2.10:443, 192.0.2.11:443",
        )
        args, _ = core_command(profile, 9000)
        self.assertEqual(args[args.index("--turn-transport") + 1], "tcp")
        self.assertEqual(args[args.index("--fingerprint") + 1], "firefox")
        self.assertEqual(args[args.index("--captcha-mode") + 1], "rjs")
        self.assertEqual(args[args.index("--client-ids") + 1], "8202606,6287487")
        self.assertEqual(
            args[args.index("--custom-turn-ips") + 1],
            "192.0.2.10:443, 192.0.2.11:443",
        )

    def test_core_command_passes_domain_and_ip_routing(self):
        profile = replace(
            base_profile(),
            mode="tun",
            domain_routing_enabled="1",
            domain_is_whitelist="1",
            direct_domains="vk.com\nexample.org",
            ip_routing_enabled="1",
            ip_is_whitelist="0",
            direct_ips="10.0.0.0/8\n192.0.2.1-192.0.2.20",
            exclude_ru_zones="1",
            template_domains="1",
        )
        args, _ = core_command(profile, 9000)
        for option in (
            "--domain-routing",
            "--domain-whitelist",
            "--exclude-ru-zones",
            "--template-domains",
            "--ip-routing",
        ):
            self.assertIn(option, args)
        self.assertEqual(
            args[args.index("--direct-domains") + 1],
            "vk.com\nexample.org",
        )
        self.assertEqual(
            args[args.index("--direct-ips") + 1],
            "10.0.0.0/8\n192.0.2.1-192.0.2.20",
        )

    def test_route_validation_accepts_whitespace_separated_rules(self):
        profile = replace(
            base_profile(),
            domain_routing_enabled="1",
            direct_domains="vk.com\nexample.org",
            ip_routing_enabled="1",
            direct_ips="10.0.0.0/8\n192.0.2.10-192.0.2.20",
        )
        self.assertEqual(profile.validate(), ["testhash123456"])

    def test_proxy_forbids_explicit_udp(self):
        profile = replace(
            base_profile(),
            internet_mode="proxy",
            proxy="192.0.2.10:3128",
            turn_transport="udp",
        )
        with self.assertRaisesRegex(ValueError, "UDP недоступен"):
            profile.validate()


if __name__ == "__main__":
    unittest.main()
