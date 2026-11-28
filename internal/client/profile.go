package client

import (
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strconv"
	"strings"
)

// String fields keep existing portable profiles compatible without conversion.
type Profile struct {
	Role           string `json:"role"`
	ShareLink      string `json:"share_link"`
	ClientPassword string `json:"client_password"`
	DNS            string `json:"dns"`
	Server        string `json:"server"`
	Password      string `json:"password"`
	Hashes        string `json:"hashes"`
	Proxy         string `json:"proxy"`
	ProxyUser     string `json:"proxy_user"`
	ProxyPassword string `json:"proxy_password"`
	SocksPort     string `json:"socks_port"`
	HTTPPort      string `json:"http_port"`
	Workers       string `json:"workers"`
	Turn          string `json:"turn"`
	Obfs          string `json:"obfs"`
	SRTP          string `json:"srtp"`
	Generation    string `json:"generation"`
	Salt          string `json:"salt"`
	InternetMode  string `json:"internet_mode"`
	SystemProxy   string `json:"system_proxy"`
	Tun           string `json:"tun"`
	TurnTransport string `json:"turn_transport"`
	Gooby          bool   `json:"gooby"`
	GoobyStrategy string `json:"gooby_strategy"`
	Fingerprint   string `json:"fingerprint"`
	VkAuthMode    string `json:"vk_auth_mode"`
	ClientIDs     string `json:"client_ids"`
	CaptchaMode   string `json:"captcha_mode"`
	CustomTurnIPs string `json:"custom_turn_ips"`
	TurnSubnet    string `json:"turn_subnet"`
	TurnIPLimit   string `json:"turn_ip_limit"`
	DomainRouting bool   `json:"domain_routing"`
	ExcludeRUZones bool  `json:"exclude_ru_zones"`
	TemplateDomains bool `json:"template_domains"`
	DomainWhitelist bool `json:"domain_whitelist"`
	DirectDomains string `json:"direct_domains"`
	IPRouting     bool   `json:"ip_routing"`
	IPWhitelist   bool   `json:"ip_whitelist"`
	DirectIPs     string `json:"direct_ips"`
}

func DefaultProfile() Profile {
	return Profile{Role: "admin", Proxy: "10.0.0.1:3128", SocksPort: "1080", HTTPPort: "8080", Workers: "6", Obfs: "unified", SRTP: "auto", Generation: "0", InternetMode: "proxy", SystemProxy: "0", Tun: "0", TurnTransport: "tcp", GoobyStrategy: "current", Fingerprint: "chrome", VkAuthMode: "vkcalls", CaptchaMode: "auto", TurnIPLimit: "ALL"}
}

var separators = regexp.MustCompile(`[\s,;]+`)

func (p Profile) NormalizedHashes() ([]string, error) {
	result := []string{}
	seen := map[string]bool{}
	for _, token := range separators.Split(strings.TrimSpace(p.Hashes), -1) {
		token = strings.Trim(token, "<>\"'")
		if i := strings.Index(token, "/call/join/"); i >= 0 {
			token = token[i+11:]
		} else if strings.HasPrefix(token, "http://") || strings.HasPrefix(token, "https://") {
			return nil, errors.New("Ссылка VK должна содержать /call/join/.")
		}
		if i := strings.IndexAny(token, "?#/"); i >= 0 {
			token = token[:i]
		}
		if token != "" && !seen[token] {
			seen[token] = true
			result = append(result, token)
		}
	}
	return result, nil
}

func Address(value string) (string, int, error) {
	host, port, e := net.SplitHostPort(strings.TrimSpace(value))
	if e != nil {
		return "", 0, errors.New("Укажите адрес в формате IP:порт или домен:порт.")
	}
	number, e := strconv.Atoi(port)
	if e != nil || number < 1 || number > 65535 || host == "" || strings.ContainsAny(host, " /@?#\r\n\t") {
		return "", 0, errors.New("Неверный адрес или порт.")
	}
	return host, number, nil
}
func (p Profile) Validate() ([]string, error) {
	if p.Role != "" && p.Role != "admin" && p.Role != "client" {
		return nil, errors.New("Выберите роль администратора или клиента.")
	}
	seenDNS := map[string]bool{}
	for _, value := range strings.Split(p.DNS, ",") {
		value = strings.TrimSpace(value)
		if value == "" { continue }
		ip := net.ParseIP(value)
		if ip == nil || ip.To4() == nil {
			return nil, errors.New("DNS: укажите IPv4-адреса через запятую, например 1.1.1.1, 8.8.8.8.")
		}
		if seenDNS[value] { return nil, errors.New("DNS: адрес повторяется.") }
		seenDNS[value] = true
	}
	if _, _, e := Address(p.Server); e != nil {
		return nil, fmt.Errorf("Сервер CSQTT: %w", e)
	}
	if p.Password == "" {
		return nil, errors.New("Введите пароль сервера CSQTT.")
	}
	if p.InternetMode != "proxy" && p.InternetMode != "direct" {
		return nil, errors.New("Неверный режим подключения.")
	}
	if (p.Tun != "0" && p.Tun != "1") || (p.SystemProxy != "0" && p.SystemProxy != "1") {
		return nil, errors.New("Неверный режим туннеля.")
	}
	if p.InternetMode == "proxy" {
		host, _, e := Address(p.Proxy)
		if e != nil || net.ParseIP(host) == nil || net.ParseIP(host).To4() == nil {
			return nil, errors.New("Корпоративный прокси: нужен IPv4:порт.")
		}
		if p.ProxyUser != "" && p.ProxyPassword == "" {
			return nil, errors.New("Введите пароль корпоративного прокси.")
		}
		if strings.Contains(p.ProxyUser, ":") || strings.ContainsAny(p.ProxyUser+p.ProxyPassword, "\r\n") {
			return nil, errors.New("Недопустимые символы в авторизации прокси.")
		}
	}
	hashes, e := p.NormalizedHashes()
	if e != nil {
		return nil, e
	}
	if len(hashes) < 1 || len(hashes) > 6 {
		return nil, errors.New("Нужно от 1 до 6 хешей VK или ссылок звонков.")
	}
	if strings.ContainsAny(p.Turn, ":/ \r\n\t") {
		return nil, errors.New("TURN: IPv4 или домен без порта и схемы.")
	}
	socks, e := strconv.Atoi(p.SocksPort)
	httpPort, e2 := strconv.Atoi(p.HTTPPort)
	if e != nil || e2 != nil || socks < 1024 || socks > 65535 || httpPort < 1024 || httpPort > 65535 || socks == httpPort {
		return nil, errors.New("Локальные порты: разные числа от 1024 до 65535.")
	}
	workers, e := strconv.Atoi(p.Workers)
	if e != nil || workers < 1 || workers > 100 {
		return nil, errors.New("Потоки: от 1 до 100.")
	}
	if _, e := strconv.ParseUint(p.Generation, 10, 64); e != nil {
		return nil, errors.New("Поколение: целое неотрицательное число.")
	}
	if p.Obfs != "unified" && p.Obfs != "audio" && p.Obfs != "video" {
		return nil, errors.New("Неверная обфускация.")
	}
	transport := p.TurnTransport
	if transport == "" {
		if p.InternetMode == "proxy" { transport = "tcp" } else { transport = "udp" }
	}
	if transport != "udp" && transport != "tcp" {
		return nil, errors.New("TURN: выберите UDP или TCP.")
	}
	if p.InternetMode == "proxy" && transport != "tcp" {
		return nil, errors.New("Корпоративный HTTP CONNECT требует TURN TCP.")
	}
	if p.Gooby && (transport != "tcp" || p.InternetMode == "proxy") {
		return nil, errors.New("Gooby доступен только при прямом подключении через TURN TCP.")
	}
	if _, e := ResolveTurnSubnet(p.TurnSubnet, p.TurnIPLimit); e != nil { return nil, e }
	if p.GoobyStrategy != "" && p.GoobyStrategy != "current" && p.GoobyStrategy != "gentle" && p.GoobyStrategy != "extended" {
		return nil, errors.New("Выберите стратегию Gooby: current, gentle или extended.")
	}
	if p.VkAuthMode != "" && p.VkAuthMode != "vkcalls" {
		return nil, errors.New("Неизвестный режим VK авторизации.")
	}
	if p.Fingerprint != "" && p.Fingerprint != "chrome" && p.Fingerprint != "safari" && p.Fingerprint != "firefox" && p.Fingerprint != "edge" && p.Fingerprint != "opera" {
		return nil, errors.New("Неизвестный TLS Client fingerprint.")
	}
	if p.CaptchaMode != "" && p.CaptchaMode != "auto" && p.CaptchaMode != "rjs" && p.CaptchaMode != "wv" {
		return nil, errors.New("Неизвестный режим капчи.")
	}
	if p.SRTP != "auto" && p.SRTP != "wrap" && p.SRTP != "dtls" {
		return nil, errors.New("Неверный режим SRTP.")
	}
	return hashes, nil
}
// ProfileConfigPath keeps user settings outside the installation directory.
func ProfileConfigPath(_ string) (string, error) {
	base, err := os.UserConfigDir()
	if err != nil { return "", err }
	return filepath.Join(base, "CSQTT", "config.json"), nil
}

func LoadProfile(directory string) (Profile, error) {
	profile := DefaultProfile()
	configPath, configErr := ProfileConfigPath(directory)
	var data []byte
	var err error
	migrate := false
	if configErr == nil {
		data, err = os.ReadFile(configPath)
	}
	if os.IsNotExist(err) || configErr != nil {
		data, err = os.ReadFile(filepath.Join(directory, "profile.json"))
		migrate = err == nil
	}
	if os.IsNotExist(err) {
		data, err = legacyProfile()
	}
	if os.IsNotExist(err) {
		return profile, nil
	}
	if err != nil {
		return profile, err
	}
	if err = json.Unmarshal([]byte(strings.TrimPrefix(string(data), "\ufeff")), &profile); err != nil {
		return DefaultProfile(), errors.New("Не удалось прочитать config.json или старый профиль. Исходный файл сохранён.")
	}
	if migrate && configErr == nil {
		if err := SaveProfile(directory, profile, true); err != nil {
			return profile, fmt.Errorf("профиль прочитан, но миграция в config.json не удалась: %w", err)
		}
	}
	return profile, nil
}

func SaveProfile(directory string, profile Profile, remember bool) error {
	path, err := ProfileConfigPath(directory)
	if err != nil { return err }
	if !remember {
		if err := os.Remove(path); err != nil && !os.IsNotExist(err) { return err }
		if err := os.Remove(filepath.Join(directory, "profile.json")); err != nil && !os.IsNotExist(err) { return err }
		return forgetLegacy()
	}
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil { return err }
	data, err := json.MarshalIndent(profile, "", "  ")
	if err != nil { return err }
	temp := path + ".tmp"
	defer os.Remove(temp)
	if err = os.WriteFile(temp, append(data, '\n'), 0600); err != nil { return err }
	if runtime.GOOS != "windows" {
		if err = os.Chmod(temp, 0600); err != nil { return err }
	}
	return os.Rename(temp, path)
}
func CoreBinaryName() string { if runtime.GOOS == "windows" { return "csqtt-core.exe" }; return "csqtt-core" }
func HelperBinaryName() string { if runtime.GOOS == "windows" { return "packet-proxy.exe" }; return "packet-proxy" }
func tunSocketName() string { return fmt.Sprintf("csqtt-tun-%d", os.Getpid()) }

func CoreCommand(directory string, p Profile, port int) ([]string, []string, error) {
	hashes, err := p.Validate()
	if err != nil { return nil, nil, err }
	transport := p.TurnTransport
	if transport == "" { transport = "tcp" }
	args := []string{
		filepath.Join(directory, "bin", CoreBinaryName()),
		"--peer", strings.TrimSpace(p.Server),
		"--listen", fmt.Sprintf("127.0.0.1:%d", port),
		"--vk", strings.Join(hashes, ","),
		"--workers", p.Workers,
		"--exact-workers",
		"--turn-transport", transport,
		"--obfs", p.Obfs,
		"--srtp-mode", p.SRTP,
		"--gen", p.Generation,
		"--salt", p.Salt,
		"--fingerprint", valueOr(p.Fingerprint, "chrome"),
		"--vk-auth-mode", valueOr(p.VkAuthMode, "vkcalls"),
		"--captcha-mode", valueOr(p.CaptchaMode, "auto"),
	}
	if p.InternetMode == "proxy" {
		args = append(args, "--port", "443")
	}
	if p.Gooby {
		args = append(args, "--gooby", "--gooby-strategy", valueOr(p.GoobyStrategy, "current"))
	}
	if strings.TrimSpace(p.ClientIDs) != "" {
		args = append(args, "--client-ids", strings.TrimSpace(p.ClientIDs))
	}
	turnIPs := strings.TrimSpace(p.CustomTurnIPs)
	if turnIPs == "" {
		turnIPs, err = ResolveTurnSubnet(p.TurnSubnet, p.TurnIPLimit)
		if err != nil { return nil, nil, err }
	}
	if turnIPs != "" {
		args = append(args, "--custom-turn-ips", turnIPs)
	}
	if strings.TrimSpace(p.Turn) != "" {
		args = append(args, "--turn", strings.TrimSpace(p.Turn))
	}
	if p.Tun == "1" && runtime.GOOS == "linux" {
		args = append(args, "--tun-uds", tunSocketName())
	}
	if p.DomainRouting { args = append(args, "--domain-routing") }
	if p.ExcludeRUZones { args = append(args, "--exclude-ru-zones") }
	if p.TemplateDomains { args = append(args, "--template-domains") }
	if p.DomainWhitelist { args = append(args, "--domain-whitelist") }
	if strings.TrimSpace(p.DirectDomains) != "" {
		args = append(args, "--direct-domains", strings.TrimSpace(p.DirectDomains))
	}
	if p.IPRouting { args = append(args, "--ip-routing") }
	if p.IPWhitelist { args = append(args, "--ip-whitelist") }
	if strings.TrimSpace(p.DirectIPs) != "" {
		args = append(args, "--direct-ips", strings.TrimSpace(p.DirectIPs))
	}
	env := []string{}
	for _, item := range os.Environ() {
		key := strings.ToUpper(strings.SplitN(item, "=", 2)[0])
		switch key {
		case "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "CSQTT_HTTP_PROXY", "CSQTT_PROXY_USER", "CSQTT_PROXY_PASSWORD", "CSQTT_PASSWORD", "CSQTT_EVENTS":
			continue
		}
		env = append(env, item)
	}
	env = append(env, "CSQTT_PASSWORD="+p.Password, "CSQTT_EVENTS=1")
	if p.InternetMode == "proxy" {
		env = append(env, "CSQTT_HTTP_PROXY="+strings.TrimSpace(p.Proxy), "CSQTT_PROXY_USER="+p.ProxyUser, "CSQTT_PROXY_PASSWORD="+p.ProxyPassword)
	}
	return args, env, nil
}

func valueOr(value, fallback string) string {
	if strings.TrimSpace(value) == "" { return fallback }
	return value
}
