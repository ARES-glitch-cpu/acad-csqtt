#!/usr/bin/env python3
"""Patch the pinned Android CSQTTR source with conservative adaptive TURN transport."""

from __future__ import annotations

import pathlib
import sys


def replace_exact(path: pathlib.Path, old: str, new: str, expected: int = 1) -> None:
    source = path.read_text(encoding="utf-8")
    count = source.count(old)
    if count != expected:
        raise SystemExit(
            f"Refusing to patch {path}: expected {expected} occurrence(s), found {count}. "
            "The pinned upstream source may have changed."
        )
    path.write_text(source.replace(old, new), encoding="utf-8", newline="\n")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply_adaptive_transport.py PATH_TO_ANDROID_CLIENT")

    root = pathlib.Path(sys.argv[1])
    if not (root / "app/src/main/java/com/csqtt/client/TunnelManager.kt").is_file():
        raise SystemExit(f"Android CSQTTR source not found under: {root}")

    settings = root / "app/src/main/java/com/csqtt/client/SettingsStore.kt"
    old_transport_when = """when (prefs[getProfileKey(TURN_TRANSPORT, profile)]) {
            CsqttConstants.Tunnel.TURN_TRANSPORT_TCP_TLS -> CsqttConstants.Tunnel.TURN_TRANSPORT_TCP_TLS
            else -> CsqttConstants.Tunnel.DEFAULT_TURN_TRANSPORT
        }"""
    new_transport_when = """when (prefs[getProfileKey(TURN_TRANSPORT, profile)]) {
            AdaptiveTransportPolicy.AUTO -> AdaptiveTransportPolicy.AUTO
            CsqttConstants.Tunnel.TURN_TRANSPORT_TCP_TLS -> CsqttConstants.Tunnel.TURN_TRANSPORT_TCP_TLS
            "udp" -> CsqttConstants.Tunnel.DEFAULT_TURN_TRANSPORT
            else -> AdaptiveTransportPolicy.AUTO
        }"""
    replace_exact(settings, old_transport_when, new_transport_when, expected=1)

    old_save_transport = """prefs[getProfileKey(TURN_TRANSPORT, profile)] = when (transport) {
                CsqttConstants.Tunnel.TURN_TRANSPORT_TCP_TLS -> CsqttConstants.Tunnel.TURN_TRANSPORT_TCP_TLS
                else -> CsqttConstants.Tunnel.DEFAULT_TURN_TRANSPORT
            }"""
    new_save_transport = """prefs[getProfileKey(TURN_TRANSPORT, profile)] = when (transport) {
                AdaptiveTransportPolicy.AUTO -> AdaptiveTransportPolicy.AUTO
                CsqttConstants.Tunnel.TURN_TRANSPORT_TCP_TLS -> CsqttConstants.Tunnel.TURN_TRANSPORT_TCP_TLS
                else -> CsqttConstants.Tunnel.DEFAULT_TURN_TRANSPORT
            }"""
    replace_exact(settings, old_save_transport, new_save_transport)

    old_export_transport = """tunnel.put("turn_transport", prefs[getProfileKey(TURN_TRANSPORT, p)] ?: CsqttConstants.Tunnel.DEFAULT_TURN_TRANSPORT)"""
    new_export_transport = """tunnel.put("turn_transport", prefs[getProfileKey(TURN_TRANSPORT, p)] ?: AdaptiveTransportPolicy.AUTO)"""
    replace_exact(settings, old_export_transport, new_export_transport)

    v2_settings = root / "app/src/main/java/com/csqtt/client/ui/v2/screens/settings/V2SettingsScreen.kt"
    old_transport_key = """fun transportKey(label: String): String = if (label == "TCP") {
        CsqttConstants.Tunnel.TURN_TRANSPORT_TCP_TLS
    } else {
        CsqttConstants.Tunnel.DEFAULT_TURN_TRANSPORT
    }"""
    new_transport_key = """fun transportKey(label: String): String = when (label) {
        "Авто" -> AdaptiveTransportPolicy.AUTO
        "TCP" -> CsqttConstants.Tunnel.TURN_TRANSPORT_TCP_TLS
        else -> CsqttConstants.Tunnel.DEFAULT_TURN_TRANSPORT
    }"""
    replace_exact(v2_settings, old_transport_key, new_transport_key)

    old_dropdown = """title = "Транспорт",
                value = if (turnTransport == CsqttConstants.Tunnel.TURN_TRANSPORT_TCP_TLS) "TCP" else "UDP",
                options = listOf("UDP", "TCP"),"""
    new_dropdown = """title = "Транспорт",
                value = when (turnTransport) {
                    AdaptiveTransportPolicy.AUTO -> "Авто"
                    CsqttConstants.Tunnel.TURN_TRANSPORT_TCP_TLS -> "TCP"
                    else -> "UDP"
                },
                options = listOf("Авто", "UDP", "TCP"),"""
    replace_exact(v2_settings, old_dropdown, new_dropdown)

    replace_exact(
        v2_settings,
        """if (turnTransport == CsqttConstants.Tunnel.TURN_TRANSPORT_TCP_TLS) {""",
        """if (turnTransport == CsqttConstants.Tunnel.TURN_TRANSPORT_TCP_TLS ||
                turnTransport == AdaptiveTransportPolicy.AUTO) {""",
    )

    service = root / "app/src/main/java/com/csqtt/client/TunnelService.kt"
    old_service_transport = """turnTransport = intent.getStringExtra("turn_transport")
                                ?.takeIf { it == CsqttConstants.Tunnel.TURN_TRANSPORT_TCP_TLS }
                                ?: CsqttConstants.Tunnel.DEFAULT_TURN_TRANSPORT,"""
    new_service_transport = """turnTransport = intent.getStringExtra("turn_transport")
                                ?.takeIf {
                                    it == CsqttConstants.Tunnel.TURN_TRANSPORT_TCP_TLS ||
                                        it == AdaptiveTransportPolicy.AUTO
                                }
                                ?: store.turnTransport.first(),"""
    replace_exact(service, old_service_transport, new_service_transport)

    policy = root / "app/src/main/java/com/csqtt/client/TurnTransportPolicy.kt"
    policy_source = policy.read_text(encoding="utf-8")
    addition = """

/**
 * Runtime policy for the user-visible Авто transport choice.
 *
 * Keep the application preference as "auto"; only the process argument is resolved
 * to a concrete TURN transport. This lets internal restarts retain the user's choice.
 */
internal object AdaptiveTransportPolicy {
    const val AUTO = "auto"

    fun effectiveTransport(
        configuredTransport: String,
        attempt: Int,
        udpTransport: String,
        tcpTransport: String,
    ): String = when (configuredTransport) {
        AUTO -> if (attempt <= 0) udpTransport else tcpTransport
        tcpTransport -> tcpTransport
        else -> udpTransport
    }

    fun shouldFallbackToTcp(
        configuredTransport: String,
        attempt: Int,
        activeWorkers: Int,
    ): Boolean =
        configuredTransport == AUTO && attempt == 0 && activeWorkers == 0
}
"""
    if "internal object AdaptiveTransportPolicy" in policy_source:
        raise SystemExit("AdaptiveTransportPolicy already exists; refusing to append twice.")
    policy.write_text(policy_source.rstrip() + addition, encoding="utf-8", newline="\n")

    manager = root / "app/src/main/java/com/csqtt/client/TunnelManager.kt"
    replace_exact(
        manager,
        """private var wrapAuthTimeoutCount = 0
    private var lastVpnStartAttemptMs = 0L""",
        """private var wrapAuthTimeoutCount = 0
    @Volatile
    private var adaptiveTransportAttempt = 0
    private var lastVpnStartAttemptMs = 0L""",
    )

    replace_exact(
        manager,
        """if (event.active > 0) {
                    wrapAuthTimeoutCount = 0""",
        """if (event.active > 0) {
                    if (currentParams?.turnTransport == AdaptiveTransportPolicy.AUTO) {
                        adaptiveTransportAttempt = 0
                    }
                    wrapAuthTimeoutCount = 0""",
    )

    replace_exact(
        manager,
        """processStartedAtMs = 0L
                    currentParams = params""",
        """processStartedAtMs = 0L
                    adaptiveTransportAttempt = 0
                    currentParams = params""",
    )

    replace_exact(
        manager,
        """if (isSwitching) currentParams = params
                startProcessLocked(appContext, params, epoch)""",
        """if (isSwitching) {
                    if (currentParams != params) adaptiveTransportAttempt = 0
                    currentParams = params
                }
                startProcessLocked(appContext, params, epoch)""",
    )

    replace_exact(
        manager,
        """cmd.add("-turn-transport")
        cmd.add(params.turnTransport)
        cmd.addAll(GoobyPolicy.arguments(params.goobyEnabled, params.turnTransport, params.goobyStrategy))""",
        """val effectiveTurnTransport = AdaptiveTransportPolicy.effectiveTransport(
            configuredTransport = params.turnTransport,
            attempt = adaptiveTransportAttempt,
            udpTransport = CsqttConstants.Tunnel.DEFAULT_TURN_TRANSPORT,
            tcpTransport = CsqttConstants.Tunnel.TURN_TRANSPORT_TCP_TLS,
        )
        if (params.turnTransport == AdaptiveTransportPolicy.AUTO) {
            val label = if (effectiveTurnTransport == CsqttConstants.Tunnel.TURN_TRANSPORT_TCP_TLS) "TCP" else "UDP"
            updateLog(
                "adaptive_transport_attempt_$adaptiveTransportAttempt",
                "[АВТО] Проверка TURN через $label",
                20,
                false,
                LogLevel.TURN,
            )
        }
        cmd.add("-turn-transport")
        cmd.add(effectiveTurnTransport)
        cmd.addAll(GoobyPolicy.arguments(params.goobyEnabled, effectiveTurnTransport, params.goobyStrategy))""",
    )

    old_startup_branch = """TunnelStartupStage.WAITING_FOR_TURN_OR_PEER -> updateProcessLog(
                    identity,
                    "startup_waiting_turn",
                    "[ДИАГНОСТИКА] TURN-креды получены, но ни один allocation/handshake с сервером не завершился",
                    98,
                    true,
                )"""
    new_startup_branch = """TunnelStartupStage.WAITING_FOR_TURN_OR_PEER -> {
                    val params = currentParams
                    if (
                        params != null &&
                        AdaptiveTransportPolicy.shouldFallbackToTcp(
                            configuredTransport = params.turnTransport,
                            attempt = adaptiveTransportAttempt,
                            activeWorkers = activeWorkers.value,
                        )
                    ) {
                        adaptiveTransportAttempt = 1
                        updateProcessLog(
                            identity,
                            "adaptive_transport_fallback",
                            "[АВТО] UDP не поднял рабочий поток за 30 секунд · переключаем TURN на TCP",
                            25,
                            false,
                            LogLevel.TURN,
                        )
                        val context = activeContext()
                        if (context != null) {
                            requestTransportRestart(
                                context.applicationContext,
                                "adaptive_transport_tcp",
                                "[АВТО] Переподключение через TCP после неудачной проверки UDP",
                            )
                        } else {
                            updateProcessLog(
                                identity,
                                "adaptive_transport_context_missing",
                                "[АВТО] Не удалось переключить транспорт: контекст приложения недоступен",
                                98,
                                true,
                            )
                        }
                    } else {
                        val detail = if (params?.turnTransport == AdaptiveTransportPolicy.AUTO) {
                            "Автоподстройка проверила UDP и TCP, но рабочий поток не появился"
                        } else {
                            "TURN-креды получены, но ни один allocation/handshake с сервером не завершился"
                        }
                        updateProcessLog(
                            identity,
                            "startup_waiting_turn",
                            "[ДИАГНОСТИКА] $detail",
                            98,
                            true,
                        )
                    }
                }"""
    replace_exact(manager, old_startup_branch, new_startup_branch)

    tests = root / "app/src/test/java/com/csqtt/client/AdaptiveTransportPolicyTest.kt"
    if tests.exists():
        raise SystemExit(f"Refusing to overwrite existing test: {tests}")
    tests.write_text(
        """package com.csqtt.client

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AdaptiveTransportPolicyTest {
    @Test
    fun autoStartsWithUdpAndUsesTcpAfterOneFailedAttempt() {
        assertEquals(
            "udp",
            AdaptiveTransportPolicy.effectiveTransport(
                AdaptiveTransportPolicy.AUTO, 0, "udp", "tcp",
            ),
        )
        assertEquals(
            "tcp",
            AdaptiveTransportPolicy.effectiveTransport(
                AdaptiveTransportPolicy.AUTO, 1, "udp", "tcp",
            ),
        )
    }

    @Test
    fun explicitTransportIsNeverSilentlyChanged() {
        assertEquals(
            "udp",
            AdaptiveTransportPolicy.effectiveTransport("udp", 1, "udp", "tcp"),
        )
        assertEquals(
            "tcp",
            AdaptiveTransportPolicy.effectiveTransport("tcp", 0, "udp", "tcp"),
        )
    }

    @Test
    fun fallbackRunsOnlyForAutoModeWithoutWorkers() {
        assertTrue(AdaptiveTransportPolicy.shouldFallbackToTcp("auto", 0, 0))
        assertFalse(AdaptiveTransportPolicy.shouldFallbackToTcp("auto", 1, 0))
        assertFalse(AdaptiveTransportPolicy.shouldFallbackToTcp("auto", 0, 2))
        assertFalse(AdaptiveTransportPolicy.shouldFallbackToTcp("udp", 0, 0))
    }
}
""",
        encoding="utf-8",
        newline="\n",
    )

    print("Adaptive TURN transport patch applied and verified.")


if __name__ == "__main__":
    main()
