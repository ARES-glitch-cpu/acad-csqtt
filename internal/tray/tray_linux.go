//go:build linux

package tray

import (
	"errors"
	"sync"
	"sync/atomic"

	"github.com/getlantern/systray"
)

var windowHide func()
var windowShow func()

func SetWindowCallbacks(hide, show func()) {
	windowHide, windowShow = hide, show
}

type Tray struct {
	ready atomic.Bool
	closed atomic.Bool
	done chan struct{}
	closeOnce sync.Once
}

func New(icon []byte, onExit func()) (*Tray, error) {
	if len(icon) == 0 {
		return nil, errors.New("иконка трея не задана")
	}
	t := &Tray{done: make(chan struct{})}
	go systray.Run(func() {
		systray.SetIcon(icon)
		systray.SetTitle("CSQTT")
		systray.SetTooltip("CSQTT — работает в фоне")
		openItem := systray.AddMenuItem("Открыть", "Восстановить окно CSQTT")
		systray.AddSeparator()
		exitItem := systray.AddMenuItem("Выход", "Завершить CSQTT и отключить соединение")
		t.ready.Store(true)
		go func() {
			for {
				select {
				case <-openItem.ClickedCh:
					if windowShow != nil {
						windowShow()
					}
				case <-exitItem.ClickedCh:
					if onExit != nil {
						onExit()
					}
					systray.Quit()
					return
				case <-t.done:
					return
				}
			}
		}()
	}, func() {
		t.ready.Store(false)
		close(t.done)
	})
	return t, nil
}

func (t *Tray) Hide() error {
	if t == nil || t.closed.Load() || !t.ready.Load() {
		return errors.New("системный трей недоступен — окно не скрыто")
	}
	if windowHide != nil {
		windowHide()
	}
	return nil
}

func (t *Tray) Show() {
	if t == nil || t.closed.Load() {
		return
	}
	if windowShow != nil {
		windowShow()
	}
}

func (t *Tray) Close() {
	if t == nil {
		return
	}
	t.closeOnce.Do(func() {
		t.closed.Store(true)
		systray.Quit()
	})
	<-t.done
}
