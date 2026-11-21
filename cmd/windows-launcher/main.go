//go:build windows

package main

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"
	"unsafe"

	"golang.org/x/sys/windows"
	"golang.org/x/sys/windows/registry"
)

const (
	webView2ClientID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
)

type registryLocation struct {
	root registry.Key
	path string
}

func runtimeVersionSupported(version string) bool {
	parts := strings.Split(strings.TrimSpace(version), ".")
	required := []int{94, 0, 992, 31} // Wails v2.16.0 minimum WebView2 version.
	if len(parts) < len(required) {
		return false
	}
	for i, minimum := range required {
		current, err := strconv.Atoi(parts[i])
		if err != nil {
			return false
		}
		if current > minimum {
			return true
		}
		if current < minimum {
			return false
		}
	}
	return true
}

func runtimeInstalled() bool {
	locations := []registryLocation{
		{registry.LOCAL_MACHINE, `SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\` + webView2ClientID},
		{registry.LOCAL_MACHINE, `SOFTWARE\Microsoft\EdgeUpdate\Clients\` + webView2ClientID},
		{registry.CURRENT_USER, `Software\Microsoft\EdgeUpdate\Clients\` + webView2ClientID},
	}
	for _, location := range locations {
		key, err := registry.OpenKey(location.root, location.path, registry.QUERY_VALUE)
		if err != nil {
			continue
		}
		version, _, err := key.GetStringValue("pv")
		_ = key.Close()
		if err == nil && runtimeVersionSupported(version) {
			return true
		}
	}
	return false
}

func messageBox(message, title string, flags uintptr) {
	text, err := windows.UTF16PtrFromString(message)
	if err != nil {
		return
	}
	caption, err := windows.UTF16PtrFromString(title)
	if err != nil {
		return
	}
	user32 := windows.NewLazySystemDLL("user32.dll")
	proc := user32.NewProc("MessageBoxW")
	_, _, _ = proc.Call(0, uintptr(unsafe.Pointer(text)), uintptr(unsafe.Pointer(caption)), flags)
}

func installRuntime(appDir string) error {
	installer := filepath.Join(appDir, "bin", "MicrosoftEdgeWebView2RuntimeInstallerX64.exe")
	if _, err := os.Stat(installer); err != nil {
		return fmt.Errorf("не найден автономный установщик WebView2: %s", installer)
	}

	cmd := exec.Command(installer, "/silent", "/install")
	cmd.Dir = appDir
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	runErr := cmd.Run()

	// The installer can finish just before EdgeUpdate writes the registry value.
	deadline := time.Now().Add(20 * time.Second)
	for time.Now().Before(deadline) {
		if runtimeInstalled() {
			return nil
		}
		time.Sleep(250 * time.Millisecond)
	}

	if runErr != nil {
		var exitErr *exec.ExitError
		if errors.As(runErr, &exitErr) {
			return fmt.Errorf("установщик WebView2 завершился с кодом %d", exitErr.ExitCode())
		}
		return fmt.Errorf("не удалось запустить установщик WebView2: %w", runErr)
	}
	return errors.New("установщик завершился, но WebView2 Runtime не появился в реестре Windows")
}

func showRuntimeError(err error) {
	messageBox(
		fmt.Sprintf("Не удалось установить Microsoft Edge WebView2 Runtime автоматически.\n\n%s\n\nПопробуйте запустить файл\nbin\\MicrosoftEdgeWebView2RuntimeInstallerX64.exe\nот имени администратора, затем снова откройте CSQTT.", err),
		"CSQTT — требуется WebView2 Runtime",
		0x10,
	)
}

func runApplication(appDir string, args []string) int {
	appPath := filepath.Join(appDir, "CSQTT-App.exe")
	if _, err := os.Stat(appPath); err != nil {
		messageBox("Не найден файл CSQTT-App.exe. Распакуйте архив полностью и не перемещайте отдельные файлы.", "CSQTT", 0x10)
		return 1
	}

	cmd := exec.Command(appPath, args...)
	cmd.Dir = appDir
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	if err := cmd.Run(); err != nil {
		var exitErr *exec.ExitError
		if errors.As(err, &exitErr) {
			return exitErr.ExitCode()
		}
		messageBox("Не удалось запустить CSQTT: "+err.Error(), "CSQTT", 0x10)
		return 1
	}
	return 0
}

func main() {
	executable, err := os.Executable()
	if err != nil {
		messageBox("Не удалось определить папку CSQTT: "+err.Error(), "CSQTT", 0x10)
		os.Exit(1)
	}
	appDir := filepath.Dir(executable)

	if !runtimeInstalled() {
		messageBox("На компьютере не найден Microsoft Edge WebView2 Runtime. Сейчас будет выполнена локальная установка. Подождите завершения, после чего CSQTT запустится автоматически.", "CSQTT — подготовка запуска", 0x40)
		if err := installRuntime(appDir); err != nil {
			showRuntimeError(err)
			os.Exit(1)
		}
	}
	os.Exit(runApplication(appDir, os.Args[1:]))
}
