//go:build !windows && !linux

package tray

import "fmt"

type Tray struct{}

func New(_, _ []byte, _ func(), _ func()) (*Tray, error) {
	return nil, fmt.Errorf("трей поддерживается только в Windows")
}
func (*Tray) Hide() error { return fmt.Errorf("трей недоступен") }
func (*Tray) Show()       {}
func (*Tray) Close()      {}
