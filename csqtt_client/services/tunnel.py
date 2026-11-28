"""Build the CSQTT core command for Windows and Linux."""
import os

from csqtt_client.config import ROOT, CORE_FILENAME


def resolve_turn_transport(profile, override=None):
    """Choose one concrete transport for a single core process."""
    if override in ("udp", "tcp"):
        return override
    configured = profile.turn_transport
    if configured in ("udp", "tcp"):
        return configured
    # UDP is preferred on a direct path. HTTP CONNECT proxies cannot carry TURN/UDP.
    return "tcp" if profile.internet_mode == "proxy" else "udp"


def core_command(profile, packet_port, tun_uds=None, transport_override=None):
    hashes = profile.validate()
    transport = resolve_turn_transport(profile, transport_override)
    args = [
        str(ROOT / "bin" / CORE_FILENAME),
        "--peer", profile.server.strip(),
        "--listen", f"127.0.0.1:{packet_port}",
        "--vk", ",".join(hashes),
        "--workers", profile.workers,
        "--exact-workers",
        "--turn-transport", transport,
        "--port", "443",
        "--obfs", profile.obfs,
        "--srtp-mode", profile.srtp,
        "--gen", profile.generation,
        "--salt", profile.salt,
    ]
    if tun_uds:
        args += ["--tun-uds", tun_uds]
    if profile.turn.strip():
        args += ["--turn", profile.turn.strip()]

    # Routing parameters are passed to the Rust core, which applies them to TUN packets.
    if profile.domain_routing_enabled == "1":
        args.append("--domain-routing")
    if profile.domain_is_whitelist == "1":
        args.append("--domain-whitelist")
    if profile.exclude_ru_zones == "1":
        args.append("--exclude-ru-zones")
    if profile.template_domains == "1":
        args.append("--template-domains")
    if profile.direct_domains.strip():
        args += ["--direct-domains", profile.direct_domains.strip()]
    if profile.ip_routing_enabled == "1":
        args.append("--ip-routing")
    if profile.ip_is_whitelist == "1":
        args.append("--ip-whitelist")
    if profile.direct_ips.strip():
        args += ["--direct-ips", profile.direct_ips.strip()]

    env = os.environ.copy()
    # Ignore inherited bypasses and proxy credentials. The core uses this explicit proxy.
    for key in list(env):
        if key.upper() in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
            del env[key]
    for key in ("CSQTT_HTTP_PROXY", "CSQTT_PROXY_USER", "CSQTT_PROXY_PASSWORD"):
        env.pop(key, None)
    env["CSQTT_PASSWORD"] = profile.password
    env["CSQTT_EVENTS"] = "1"
    if profile.internet_mode == "proxy":
        env.update(
            CSQTT_HTTP_PROXY=profile.proxy.strip(),
            CSQTT_PROXY_USER=profile.proxy_user,
            CSQTT_PROXY_PASSWORD=profile.proxy_password,
        )
    return args, env
