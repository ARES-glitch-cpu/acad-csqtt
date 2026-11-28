package main

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	goruntime "runtime"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"csqtt.desktop/internal/client"
	"csqtt.desktop/internal/tray"
	"github.com/wailsapp/wails/v2/pkg/runtime"
)

type Initial struct {
	Profile client.Profile `json:"profile"`
	State   client.State   `json:"state"`
	Version string         `json:"version"`
	Error   string         `json:"error"`
}
type App struct {
	ctx                context.Context
	manager            *client.Manager
	directory, version string
	mu                 sync.Mutex
	profile            client.Profile
	remember           bool
	loadError          string
	tray               atomic.Pointer[tray.Tray]
	exiting            atomic.Bool
	smoke              bool
	draft              bool
	saveTimer          *time.Timer
	deployMu           sync.Mutex
	pendingDeployHostKey *DeployHostKeyPrompt
	deployLast         *DeployResult
	deployRunning      bool
}

func NewApp(directory, version string, smoke bool) *App {
	p, e := client.LoadProfile(directory)
	a := &App{directory: directory, version: version, profile: p, remember: true, smoke: smoke, manager: client.NewManager(directory, version)}
	if e != nil {
		a.loadError = e.Error()
	}
	if e == nil && !smoke {
		if configPath, err := client.ProfileConfigPath(directory); err == nil {
			if _, statErr := os.Stat(configPath); os.IsNotExist(statErr) && p.Server != "" {
				a.draft = true
			}
		}
	}
	return a
}
func (a *App) startup(ctx context.Context) {
	a.ctx = ctx
	if !a.smoke {
		if icon, e := tray.New(trayIcon, trayIconPNG, a.restoreWindow, a.Quit); e == nil {
			a.tray.Store(icon)
		} else {
			a.mu.Lock()
			a.loadError = "Системный трей недоступен: " + e.Error()
			a.mu.Unlock()
		}
	}
}
func (a *App) domReady(ctx context.Context) {
	if a.smoke {
		go func() { time.Sleep(400 * time.Millisecond); a.Quit() }()
		return
	}
	go a.manager.Recover(false)
	go func() {
		ticker := time.NewTicker(250 * time.Millisecond)
		defer ticker.Stop()
		var revision uint64
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				s := a.manager.Snapshot()
				if s.Revision != revision {
					revision = s.Revision
					runtime.EventsEmit(ctx, "state", s)
				}
			}
		}
	}()
	go func() {
		time.Sleep(time.Second)
		a.CheckUpdates()
		if hasArgument("--connect") {
			_ = a.connect()
		}
		ticker := time.NewTicker(6 * time.Hour)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				a.CheckUpdates()
			}
		}
	}()
}
func (a *App) Initial() Initial {
	a.mu.Lock()
	defer a.mu.Unlock()
	return Initial{a.profile, a.manager.Snapshot(), a.version, a.loadError}
}
func (a *App) SaveProfile(p client.Profile, remember bool) error {
	a.mu.Lock()
	defer a.mu.Unlock()
	if e := client.SaveProfile(a.directory, p, remember); e != nil {
		return errors.New("Не удалось сохранить профиль. Проверьте доступ к записи в папку программы.")
	}
	a.profile = p
	a.remember = remember
	a.loadError = ""
	a.draft = false
	return nil
}

func (a *App) ConfigPath() (string, error) {
	return client.ProfileConfigPath(a.directory)
}

// ExportProfile writes a portable JSON profile. It is intentionally not DPAPI-wrapped:
// the exported file can be imported on another computer and must be treated like a password.
func (a *App) ExportProfile() error {
	path, err := runtime.SaveFileDialog(a.ctx, runtime.SaveDialogOptions{
		DefaultFilename: "csqtt-profile.json",
		Filters: []runtime.FileFilter{{DisplayName: "Профиль CSQTT (JSON)", Pattern: "*.json"}},
	})
	if err != nil || path == "" { return err }
	a.mu.Lock()
	profile := a.profile
	a.mu.Unlock()
	payload := struct {
		Format string `json:"format"`
		Version int `json:"version"`
		Profile client.Profile `json:"profile"`
	}{Format:"csqtt-profile-export",Version:1,Profile:profile}
	data, err := json.MarshalIndent(payload,"","  ")
	if err != nil { return err }
	return os.WriteFile(path,append(data,'\\n'),0600)
}

func (a *App) ImportProfile() (client.Profile, error) {
	path, err := runtime.OpenFileDialog(a.ctx, runtime.OpenDialogOptions{
		Title: "Импортировать профиль CSQTT",
		Filters: []runtime.FileFilter{{DisplayName: "Профиль CSQTT (JSON)", Pattern: "*.json"}},
	})
	if err != nil || path == "" { return client.Profile{}, err }
	data, err := os.ReadFile(path)
	if err != nil { return client.Profile{}, err }
	profile := client.DefaultProfile()
	var envelope struct {
		Format string `json:"format"`
		Version int `json:"version"`
		Profile json.RawMessage `json:"profile"`
	}
	if err := json.Unmarshal(data,&envelope); err != nil { return client.Profile{}, errors.New("Файл не является корректным JSON-профилем CSQTT.") }
	if envelope.Format == "csqtt-profile-export" {
		if envelope.Version != 1 || len(envelope.Profile)==0 { return client.Profile{}, errors.New("Версия или содержимое профиля не поддерживаются.") }
		if err := json.Unmarshal(envelope.Profile,&profile); err != nil { return client.Profile{}, errors.New("Не удалось прочитать профиль внутри JSON-файла.") }
	} else {
		if err := json.Unmarshal(data,&profile); err != nil { return client.Profile{}, errors.New("Файл не является корректным JSON-профилем CSQTT.") }
	}
	if err := a.SaveProfile(profile,true); err != nil { return client.Profile{}, err }
	return profile,nil
}

func (a *App) OpenConfigFolder() error {
	path, err := client.ProfileConfigPath(a.directory)
	if err != nil { return err }
	folder := filepath.Dir(path)
	if err := os.MkdirAll(folder,0700); err != nil { return err }
	var command *exec.Cmd
	switch goruntime.GOOS {
	case "windows": command = exec.Command("explorer.exe",folder)
	case "linux": command = exec.Command("xdg-open",folder)
	default: return errors.New("Открытие папки конфигурации не поддерживается в этой ОС.")
	}
	return command.Start()
}

func (a *App) SetDraft(p client.Profile, remember bool) {
	a.mu.Lock()
	a.profile = p
	a.remember = remember
	a.draft = true
	if a.saveTimer != nil {
		a.saveTimer.Stop()
	}
	a.saveTimer = time.AfterFunc(400*time.Millisecond, func() {
		a.mu.Lock()
		defer a.mu.Unlock()
		if !a.draft {
			return
		}
		if e := client.SaveProfile(a.directory, a.profile, a.remember); e != nil {
			runtime.EventsEmit(a.ctx, "profile-save", "Не удалось сохранить профиль. Проверьте доступ к папке программы.")
		} else {
			a.draft = false
			runtime.EventsEmit(a.ctx, "profile-save", "")
		}
	})
	a.mu.Unlock()
}
func (a *App) Connect() (client.State, error) { e := a.connect(); return a.manager.Snapshot(), e }
func (a *App) connect() error {
	a.mu.Lock()
	p, remember := a.profile, a.remember
	a.mu.Unlock()
	if p.Role == "client" {
		shared, err := client.ParseShareLink(p.ShareLink)
		if err != nil { return err }
		p.Server = shared.Server
		p.Password = shared.Password
		if p.Password == "" { p.Password = p.ClientPassword }
		if shared.Hashes != "" { p.Hashes = shared.Hashes }
		if p.Password == "" {
			return errors.New("В ссылке нет пароля. Укажите пароль клиента или попросите ссылку с паролем.")
		}
	}
	if _, e := p.Validate(); e != nil {
		return e
	}
	if p.Tun == "1" && !client.IsAdmin() {
		if !remember {
			return errors.New("Включите сохранение профиля для перезапуска TUN или запустите приложение от имени администратора.")
		}
		exe, _ := os.Executable()
		if e := client.Elevate(exe, a.directory); e != nil {
			return e
		}
		a.Quit()
		return nil
	}
	return a.manager.Start(p)
}
func (a *App) Disconnect() client.State          { a.manager.Stop(); return a.manager.Snapshot() }
func (a *App) SetSystemProxy(enabled bool)       { a.manager.SetSystemProxy(enabled) }
func (a *App) CheckProxy(p client.Profile) error { return client.CheckProxy(a.ctx, p) }
func (a *App) CheckInternet()                    { go a.manager.CheckInternet() }
func (a *App) CheckUpdates()                     { a.mu.Lock(); p := a.profile; a.mu.Unlock(); a.manager.CheckUpdates(p) }
func (a *App) OpenUpdate() error {
	u := a.manager.Snapshot().Update
	if u == nil {
		return errors.New("Новая версия не найдена.")
	}
	runtime.BrowserOpenURL(a.ctx, u.URL)
	return nil
}
func (a *App) ExportLog() error {
	path, e := runtime.SaveFileDialog(a.ctx, runtime.SaveDialogOptions{DefaultFilename: "csqtt-log.txt", Filters: []runtime.FileFilter{{DisplayName: "Журнал", Pattern: "*.txt"}}})
	if e != nil || path == "" {
		return e
	}
	lines := []string{}
	for _, line := range a.manager.Snapshot().Logs {
		lines = append(lines, line.Time+" "+line.Message)
	}
	return os.WriteFile(path, []byte(strings.Join(lines, "\r\n")), 0600)
}
func (a *App) HideToTray() error {
	icon := a.tray.Load()
	if icon == nil {
		return errors.New("Системный трей недоступен. Окно не будет скрыто.")
	}
	if err := icon.Hide(); err != nil { return err }
	// Windows tray.Hide intercepts the native Wails HWND itself. Linux keeps
	// the StatusNotifier icon visible and hides the Wails window via runtime.
	if goruntime.GOOS == "linux" && a.ctx != nil {
		runtime.WindowHide(a.ctx)
	}
	return nil
}
func (a *App) restoreWindow() {
	if goruntime.GOOS == "windows" {
		if icon := a.tray.Load(); icon != nil { icon.Show(); return }
	}
	if a.ctx != nil { runtime.WindowShow(a.ctx) }
}
func (a *App) beforeClose(context.Context) bool {
	if goruntime.GOOS != "windows" && goruntime.GOOS != "linux" {
		return false
	}
	if a.exiting.Load() { return false }
	if err := a.HideToTray(); err != nil {
		// If the tray could not start, do not trap the user in an unclosable window.
		return false
	}
	return true
}
func (a *App) Quit() {
	if a.exiting.CompareAndSwap(false, true) {
		runtime.Quit(a.ctx)
	}
}
func (a *App) shutdown(context.Context) {
	a.mu.Lock()
	if a.saveTimer != nil {
		a.saveTimer.Stop()
	}
	if a.draft {
		_ = client.SaveProfile(a.directory, a.profile, a.remember)
	}
	a.mu.Unlock()
	a.manager.Close()
	if icon := a.tray.Swap(nil); icon != nil {
		icon.Close()
	}
}
func appDirectory() string {
	exe, _ := os.Executable()
	directory := filepath.Dir(exe)
	if _, e := os.Stat(filepath.Join(directory, "bin", client.CoreBinaryName())); e == nil {
		return directory
	}
	wd, _ := os.Getwd()
	if _, e := os.Stat(filepath.Join(wd, "VERSION")); e == nil && fileExists(filepath.Join(wd, "bin", client.CoreBinaryName())) {
		return wd
	}
	return directory
}
func fileExists(path string) bool { _, err := os.Stat(path); return err == nil }
func hasArgument(value string) bool {
	for _, arg := range os.Args {
		if arg == value {
			return true
		}
	}
	return false
}
