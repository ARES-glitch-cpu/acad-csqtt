//go:build linux

package main

import (
	"context"
	"time"
)

func watchParentProcess(pid uint32, cancel context.CancelFunc) {
	if pid == 0 {
		return
	}
	go func() {
		ticker := time.NewTicker(500 * time.Millisecond)
		defer ticker.Stop()
		for {
			select {
			case <-ticker.C:
				if !linuxProcessIsRunning(int(pid)) {
					cancel()
					return
				}
			}
		}
	}()
}
