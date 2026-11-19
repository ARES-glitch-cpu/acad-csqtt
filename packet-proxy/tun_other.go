//go:build !windows && !linux

package main

import (
	"context"
	"errors"
)

func runTunMode(_ context.Context, _ string, _ string, _ string, _ string, _ string, _ int, _ func() error) error {
	return errors.New("системный режим TUN поддерживается только в Linux и Windows")
}

func recoverTunState() (bool, error) {
	return false, nil
}
