"""Build an explicit TCP-only core command and its private environment."""
import os

from csqtt_client.config import ROOT, CORE_FILENAME


def core_command(profile, packet_port, tun_uds=None):
    hashes = profile.validate()
    args = [str(ROOT / "bin" / CORE_FILENAME), "--peer", profile.server.strip(),
            "--listen", f"127.0.0.1:{packet_port}", "--vk", ",".join(hashes),
            "--workers", profile.workers, "--exact-workers", "--turn-transport", "tcp", "--port", "443",
            "--obfs", profile.obfs, "--srtp-mode", profile.srtp, "--gen", profile.generation, "--salt", profile.salt]
    if tun_uds:
        args += ["--tun-uds", tun_uds]
    if profile.turn.strip():
        args += ["--turn", profile.turn.strip()]
    env = os.environ.copy()
    # Ignore inherited bypasses and proxy credentials. The core uses this explicit proxy.
    for key in list(env):
        if key.upper() in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
            del env[key]
    env.update(CSQTT_PASSWORD=profile.password, CSQTT_HTTP_PROXY=profile.proxy.strip(),
               CSQTT_PROXY_USER=profile.proxy_user, CSQTT_PROXY_PASSWORD=profile.proxy_password,
               CSQTT_EVENTS="1")
    return args, env
