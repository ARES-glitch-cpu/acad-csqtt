//go:build linux

package client

import (
	"errors"
	"os"
	"os/exec"
	"strconv"
)

func hidden(_ *exec.Cmd) {}

func IsAdmin() bool {
	return os.Geteuid() == 0
}

func Elevate(executable, directory string) error {
	pkexec, err := exec.LookPath("pkexec")
	if err != nil {
		return errors.New("Для режима TUN установите polkit/pkexec или запустите CSQTT от root.")
	}
	args := []string{executable, "--connect", "--wait-pid=" + strconv.Itoa(os.Getpid())}
	cmd := exec.Command(pkexec, args...)
	cmd.Dir = directory
	if err := cmd.Start(); err != nil {
		return errors.New("Не удалось запросить права администратора через pkexec.")
	}
	return nil
}

func legacyProfile() ([]byte, error) {
	return nil, os.ErrNotExist
}

func forgetLegacy() error {
	return nil
}
