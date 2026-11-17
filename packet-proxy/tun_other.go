//go:build !windows && !linux

package main

import "errors"

func runTunMode(core, ip, dns, bypassIP, tunUDS string, _ int) error {
	return errors.New("системный режим TUN поддерживается только в Windows-сборке")
}

func recoverTunState() (bool, error) {
	return false, nil
}
