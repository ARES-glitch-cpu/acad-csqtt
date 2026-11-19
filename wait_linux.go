//go:build linux

package main

import (
	"os"
	"strconv"
	"strings"
	"syscall"
	"time"
)

func waitForPrevious() {
	for _, arg := range os.Args {
		if !strings.HasPrefix(arg, "--wait-pid=") {
			continue
		}
		pid, err := strconv.Atoi(strings.TrimPrefix(arg, "--wait-pid="))
		if err != nil || pid <= 0 {
			continue
		}
		deadline := time.Now().Add(10 * time.Second)
		for time.Now().Before(deadline) {
			process, err := os.FindProcess(pid)
			if err != nil {
				return
			}
			err = process.Signal(syscall.Signal(0))
			if err != nil {
				return
			}
			time.Sleep(100 * time.Millisecond)
		}
	}
}
