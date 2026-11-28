//go:build linux

package tray

import (
	"errors"
	"sync"
	"time"
	"runtime"

	"github.com/getlantern/systray"
)

type Tray struct {
	onOpen func()
	onExit func()
	done chan struct{}
	close sync.Once
}

func New(_ []byte, iconPNG []byte, onOpen, onExit func()) (*Tray, error) {
	if len(iconPNG) == 0 {
		return nil, errors.New("не задан PNG значок системного трея")
	}
	t := &Tray{onOpen: onOpen, onExit: onExit, done: make(chan struct{})}
	ready := make(chan struct{})
	go func() {
		runtime.LockOSThread()
		defer runtime.UnlockOSThread()
		defer close(t.done)
		systray.Run(func() {
			systray.SetIcon(iconPNG)
			systray.SetTitle("CSQTT")
			openItem := systray.AddMenuItem("Открыть CSQTT", "Показать окно CSQTT")
			systray.AddSeparator()
			exitItem := systray.AddMenuItem("Выход", "Остановить соединение и закрыть CSQTT")
			close(ready)
			for {
				select {
				case <-openItem.ClickedCh:
					if t.onOpen != nil { go t.onOpen() }
				case <-exitItem.ClickedCh:
					if t.onExit != nil { go t.onExit() }
				case <-t.done:
					return
				}
			}
		}, func() {})
	}()
	select {
	case <-ready:
		return t, nil
	case <-time.After(8 * time.Second):
		systray.Quit()
		return nil, errors.New("Linux системный трей не запустился (проверьте AppIndicator/StatusNotifier)")
	}
}

// The tray icon remains visible; the application window is hidden by App.HideToTray.
func (*Tray) Hide() error { return nil }

func (t *Tray) Show() {
	if t != nil && t.onOpen != nil { go t.onOpen() }
}

func (t *Tray) Close() {
	if t == nil { return }
	t.close.Do(func() { systray.Quit() })
	select { case <-t.done: case <-time.After(3*time.Second): }
}
