package client

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func valid() Profile {
	p := DefaultProfile()
	p.Server = "203.0.113.2:443"
	p.Password = "test-only-secret"
	p.Hashes = "https://vk.com/call/join/testhash123456?extra=1"
	return p
}
func TestConfigJSONProfileAndCommandCompatibility(t *testing.T) {
	configRoot := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", configRoot)
	t.Setenv("APPDATA", configRoot)
	t.Setenv("LOCALAPPDATA", t.TempDir())
	p := valid()
	p.ProxyUser = "test-user"
	p.ProxyPassword = "test-proxy-secret"
	p.Tun = "1"
	p.SystemProxy = "1"
	p.Salt = "test-salt"
	p.GoobyStrategy = "gentle"
	p.Fingerprint = "firefox"
	p.ClientIDs = "client-a,client-b"
	p.DomainRouting = true
	p.DomainWhitelist = true
	p.DirectDomains = "example.com,*.example.net"
	p.IPRouting = true
	p.DirectIPs = "192.0.2.0/24"
	directory := t.TempDir()
	if err := SaveProfile(directory, p, true); err != nil { t.Fatal(err) }
	configPath, err := ProfileConfigPath(directory)
	if err != nil { t.Fatal(err) }
	if filepath.Base(configPath) != "config.json" { t.Fatalf("unexpected config filename: %s", configPath) }
	loaded, err := LoadProfile(directory)
	if err != nil || p != loaded { t.Fatalf("config roundtrip: %v", err) }
	data, err := os.ReadFile(configPath)
	if err != nil { t.Fatal(err) }
	var decoded Profile
	if err := json.Unmarshal(data, &decoded); err != nil || decoded != p { t.Fatalf("invalid config.json: %v", err) }
	args, env, err := CoreCommand(directory, p, 19091)
	if err != nil { t.Fatal(err) }
	command := strings.Join(args, " ")
	if strings.Contains(command, p.Password) || strings.Contains(command, p.ProxyPassword) { t.Fatal("password in command") }
	if !strings.Contains(command, "--turn-transport tcp --obfs") || !strings.Contains(command, "--port 443") { t.Fatal(command) }
	for _, flag := range []string{"--fingerprint firefox", "--client-ids client-a,client-b", "--domain-routing", "--domain-whitelist", "--ip-routing", "--direct-ips 192.0.2.0/24"} {
		if !strings.Contains(command, flag) { t.Fatalf("missing core option %q in %s", flag, command) }
	}
	if !strings.Contains(strings.Join(env, "\\n"), "CSQTT_PROXY_PASSWORD="+p.ProxyPassword) { t.Fatal("missing proxy auth") }
	p.InternetMode = "direct"
	p.Proxy = ""
	p.TurnTransport = "udp"
	p.Gooby = false
	args, env, err = CoreCommand(directory, p, 19091)
	if err != nil { t.Fatal(err) }
	command = strings.Join(args, " ")
	if strings.Contains(command, "--port") { t.Fatalf("direct mode must use port from TURN URI: %s", command) }
	if !strings.Contains(command, "--turn-transport udp") { t.Fatal(command) }
	for _, value := range env {
		if strings.HasPrefix(value, "CSQTT_HTTP_PROXY=") || strings.HasPrefix(value, "CSQTT_PROXY_PASSWORD=") { t.Fatal("direct mode inherited proxy") }
	}
	p.TurnTransport = "tcp"
	p.Gooby = true
	p.GoobyStrategy = "extended"
	args, _, err = CoreCommand(directory, p, 19091)
	if err != nil { t.Fatal(err) }
	command = strings.Join(args, " ")
	if !strings.Contains(command, "--gooby --gooby-strategy extended") { t.Fatal(command) }
	if err := SaveProfile(directory, p, false); err != nil { t.Fatal(err) }
	if _, err := os.Stat(configPath); !os.IsNotExist(err) { t.Fatal("config.json not removed") }
}

func TestVKTurnSubnetPresetsAndLimits(t *testing.T) {
	one, err := ResolveTurnSubnet("95.163.34.0/24", "1")
	if err != nil || one != "95.163.34.48" { t.Fatalf("first candidate: %q, %v", one, err) }
	nine, err := ResolveTurnSubnet("91.231.135.0/24", "9")
	if err != nil || len(strings.Split(nine, ",")) != 9 { t.Fatalf("nine candidates: %q, %v", nine, err) }
	all, err := ResolveTurnSubnet("193.203.43.0/24", "ALL")
	if err != nil || len(strings.Split(all, ",")) != 47 { t.Fatalf("all candidates: got %d, err=%v", len(strings.Split(all, ",")), err) }
	auto, err := ResolveTurnSubnet("", "ALL")
	if err != nil || auto != "" { t.Fatalf("empty subnet must defer to VK response: %q, %v", auto, err) }
	if _, err := ResolveTurnSubnet("95.163.34.0/24", "3"); err == nil { t.Fatal("unsupported IP limit accepted") }
	if _, err := ResolveTurnSubnet("203.0.113.0/24", "ALL"); err == nil { t.Fatal("untrusted subnet accepted") }
}

func TestManualTurnIPsOverrideSubnetPreset(t *testing.T) {
	p := valid()
	p.CustomTurnIPs = "192.0.2.10:443,192.0.2.11:443"
	p.TurnSubnet = "95.163.34.0/24"
	p.TurnIPLimit = "1"
	args, _, err := CoreCommand(t.TempDir(), p, 19091)
	if err != nil { t.Fatal(err) }
	joined := strings.Join(args, " ")
	if !strings.Contains(joined, "--custom-turn-ips 192.0.2.10:443,192.0.2.11:443") || strings.Contains(joined, "95.163.34.48") {
		t.Fatalf("manual IP list must override subnet preset: %s", joined)
	}
	p.CustomTurnIPs = ""
	args, _, err = CoreCommand(t.TempDir(), p, 19091)
	if err != nil { t.Fatal(err) }
	joined = strings.Join(args, " ")
	if !strings.Contains(joined, "95.163.34.48") || strings.Count(joined, "95.163.34.") != 1 {
		t.Fatalf("subnet and limit not applied: %s", joined)
	}
}

func TestUpdateOpensReleasePageAndRejectsUntrustedAssets(t *testing.T) {
	tag := "v1.4.2"
	asset := map[string]string{"name": "CSQTT-" + tag + "-Win10-x64.zip", "state": "uploaded", "browser_download_url": "https://github.com/" + repository + "/releases/download/" + tag + "/CSQTT-" + tag + "-Win10-x64.zip"}
	data, _ := json.Marshal(map[string]interface{}{"tag_name": tag, "assets": []interface{}{asset}})
	u, e := ParseUpdate(data, "1.4.1")
	if e != nil || u == nil || u.URL != "https://github.com/"+repository+"/releases/tag/"+tag {
		t.Fatal("update must open the release page")
	}
	asset["browser_download_url"] = "https://example.com/bad.zip"
	data, _ = json.Marshal(map[string]interface{}{"tag_name": tag, "assets": []interface{}{asset}})
	if u, _ := ParseUpdate(data, "1.4.1"); u != nil {
		t.Fatal("untrusted download accepted")
	}
	if newer("1.4.0", "1.4.1") || !newer("1.10.0", "1.9.0") {
		t.Fatal("version ordering")
	}
}
func TestAuthenticatedConnect(t *testing.T) {
	l, e := net.Listen("tcp4", "127.0.0.1:0")
	if e != nil {
		t.Fatal(e)
	}
	defer l.Close()
	received := make(chan string, 1)
	go func() {
		c, e := l.Accept()
		if e != nil {
			return
		}
		defer c.Close()
		c.SetDeadline(time.Now().Add(3 * time.Second))
		var b [8192]byte
		n, _ := c.Read(b[:])
		received <- string(b[:n])
		fmt.Fprint(c, "HTTP/1.1 200 Connection Established\r\n\r\n")
	}()
	p := valid()
	p.Proxy = l.Addr().String()
	p.ProxyUser = "test-user"
	p.ProxyPassword = "test-secret"
	if e := CheckProxy(context.Background(), p); e != nil {
		t.Fatal(e)
	}
	request := <-received
	if !strings.Contains(request, "CONNECT dns.google:443") || !strings.Contains(request, base64.StdEncoding.EncodeToString([]byte("test-user:test-secret"))) {
		t.Fatal("CONNECT authorization missing")
	}
}
func TestEventFloodIsBoundedAndMasksSecrets(t *testing.T) {
	m := NewManager(t.TempDir(), "1.4.1")
	defer m.Close()
	m.session = 1
	m.secrets = []string{"sensitive-value"}
	start := time.Now()
	for i := 0; i < 10000; i++ {
		m.consume(1, "core", fmt.Sprintf("failed %d sensitive-value password=hidden", i))
	}
	s := m.Snapshot()
	if len(s.Logs) > 400 {
		t.Fatal("unbounded journal")
	}
	for _, line := range s.Logs {
		if strings.Contains(line.Message, "sensitive-value") || strings.Contains(line.Message, "password=hidden") {
			t.Fatal("secret leak")
		}
	}
	if time.Since(start) > 3*time.Second {
		t.Fatal("event handling stalled")
	}
	m.consume(1, "core", "__CSQTT_EVENT__|STATS|{\"active\":6,\"bytes_up\":123,\"bytes_down\":456}")
	s = m.Snapshot()
	if s.Active != 6 || s.Upload != 123 || s.Download != 456 {
		t.Fatal("stats event lost")
	}
}
func TestBuiltCoreRemainsCompatibleWithController(t *testing.T) {
	root, e := filepath.Abs("../..")
	if e != nil {
		t.Fatal(e)
	}
	if _, e = os.Stat(filepath.Join(root, "bin/csqtt-core.exe")); e != nil {
		t.Skip("core not built")
	}
	l, e := net.Listen("tcp4", "127.0.0.1:0")
	if e != nil {
		t.Fatal(e)
	}
	defer l.Close()
	seen := make(chan string, 1)
	go func() {
		c, e := l.Accept()
		if e != nil {
			return
		}
		defer c.Close()
		c.SetDeadline(time.Now().Add(5 * time.Second))
		b := make([]byte, 8192)
		n, _ := c.Read(b)
		seen <- string(b[:n])
		io.WriteString(c, "HTTP/1.1 407 Proxy Authentication Required\r\nContent-Length: 0\r\n\r\n")
	}()
	p := valid()
	p.Proxy = l.Addr().String()
	m := NewManager(root, "1.4.1")
	defer m.Close()
	if e := m.Start(p); e != nil {
		t.Fatal(e)
	}
	select {
	case request := <-seen:
		if !strings.Contains(strings.ToLower(request), "connect api.vk.me:443") {
			t.Fatal("unexpected core request")
		}
	case <-time.After(8 * time.Second):
		t.Fatal("core did not use explicit CONNECT")
	}
	m.Stop()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if m.Snapshot().Status == "offline" {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("disconnect stalled")
}
