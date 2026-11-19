//go:build !windows

package main

// Linux desktop environments do not share a single system-proxy API.
// CSQTT exposes its local SOCKS/HTTP endpoints; system-wide proxy toggling
// remains a Windows-only feature and must not mutate desktop settings here.

type proxyController struct {
	address string
	enabled bool
}

func newProxyController(address string, enabled bool) *proxyController {
	return &proxyController{address: address, enabled: enabled}
}

func recoverProxyState() error {
	return nil
}

func (p *proxyController) setReady() error {
	return nil
}

func (p *proxyController) setEnabled(enabled bool) error {
	p.enabled = enabled
	return nil
}

func (p *proxyController) restore() {}
