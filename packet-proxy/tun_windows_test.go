//go:build windows

package main

import (
	"context"
	"os/exec"
	"testing"
	"time"
)

func TestWatchParentProcessCancelsForMissingPID(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	watchParentProcess(0, cancel)

	select {
	case <-ctx.Done():
	case <-time.After(time.Second):
		t.Fatal("TUN helper did not cancel when the parent PID was missing")
	}
}

func TestWatchParentProcessCancelsWhenGUIExits(t *testing.T) {
	parent := exec.Command("cmd.exe", "/c", "ping -n 20 127.0.0.1 >NUL")
	if err := parent.Start(); err != nil {
		t.Fatal(err)
	}
	defer func() {
		if parent.ProcessState == nil {
			_ = parent.Process.Kill()
			_ = parent.Wait()
		}
	}()

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// watchParentProcess opens the process handle synchronously, before we
	// terminate the test parent. This exercises the same path as the GUI PID.
	watchParentProcess(uint32(parent.Process.Pid), cancel)
	if err := parent.Process.Kill(); err != nil {
		t.Fatal(err)
	}
	_ = parent.Wait()

	select {
	case <-ctx.Done():
	case <-time.After(3 * time.Second):
		t.Fatal("TUN helper did not detect that the GUI process exited")
	}
}
