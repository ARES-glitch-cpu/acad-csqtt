package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"embed"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"

	"csqtt.desktop/internal/client"
	"golang.org/x/crypto/ssh"
	"github.com/wailsapp/wails/v2/pkg/runtime"
)

//go:embed assets/deploy.sh assets/server-downloads.json assets/csqtt.server-provenance.json
var deployAssets embed.FS

const (
	deploySSHTimeout = 20 * time.Second
	deployInventoryTimeout = 100 * time.Second
	deployActionTimeout = 45 * time.Minute
	deployMaxOutput = 2 << 20
	deployVersion = "2.5.3"
)

type DeployServer struct {
	Place string `json:"place"`
	Runtime string `json:"runtime"`
	State string `json:"state"`
	Version string `json:"version"`
	PeerPort int `json:"peerPort"`
	WebPort int `json:"webPort"`
	Name string `json:"name"`
}
type DeployBusyPort struct {
	Protocol string `json:"protocol"`
	Port int `json:"port"`
	Holder string `json:"holder"`
}
type DeployInventory struct {
	Servers []DeployServer `json:"servers"`
	Busy []DeployBusyPort `json:"busy"`
	Architecture string `json:"architecture"`
}
type DeployAction struct {
	ID string `json:"id"`
	Kind string `json:"kind"`
	Instance string `json:"instance"`
	Title string `json:"title"`
	Detail string `json:"detail"`
	PeerPort int `json:"peerPort"`
	WebPort int `json:"webPort"`
	Destructive bool `json:"destructive"`
}
type DeployResult struct {
	Host string `json:"host"`
	Port int `json:"port"`
	NeedsTrust bool `json:"needsTrust"`
	KeyChanged bool `json:"keyChanged"`
	PresentedFingerprint string `json:"presentedFingerprint"`
	ExpectedFingerprint string `json:"expectedFingerprint"`
	Inventory *DeployInventory `json:"inventory,omitempty"`
	Actions []DeployAction `json:"actions"`
	Notes []string `json:"notes"`
	Message string `json:"message"`
}
type DeployProgress struct {
	Percent float64 `json:"percent"`
	Message string `json:"message"`
	Done bool `json:"done"`
	Success bool `json:"success"`
}
type DeployHostKeyPrompt struct {
	Host string
	Port int
	Presented string
	Expected string
}

type serverArtifact struct {
	URL string `json:"url"`
	Size int64 `json:"size"`
	SHA256 string `json:"sha256"`
}
type serverManifest map[string]serverArtifact
type provenanceArtifact struct {
	AssetName string `json:"assetName"`
	BinarySHA256 string `json:"binarySha256"`
	BinarySize int64 `json:"binarySize"`
}
type serverProvenance struct {
	Marker string `json:"marker"`
	Version string `json:"version"`
	Artifacts []provenanceArtifact `json:"artifacts"`
}
type deployPlan struct {
	Actions []DeployAction
	Notes []string
}

type cappedBuffer struct {
	bytes.Buffer
	limit int
}
func (b *cappedBuffer) Write(p []byte) (int, error) {
	original := len(p)
	if b.limit > b.Len() {
		remaining := b.limit - b.Len()
		if len(p) > remaining { p = p[:remaining] }
		_, _ = b.Buffer.Write(p)
	}
	return original, nil
}

func shellQuote(value string) string { return "'" + strings.ReplaceAll(value, "'", "'\"'\"'") + "'" }
func systemdEnvValue(value string) string {
	value = strings.ReplaceAll(value, "\r", " ")
	value = strings.ReplaceAll(value, "\n", " ")
	value = strings.ReplaceAll(value, "\\", "\\\\")
	value = strings.ReplaceAll(value, "\"", "\\\"")
	return "\"" + value + "\""
}
func dockerEnvValue(value string) string {
	return strings.NewReplacer("\r", " ", "\n", " ").Replace(value)
}
func isValidPort(value string) (int, error) {
	n, err := strconv.Atoi(strings.TrimSpace(value))
	if err != nil || n < 1 || n > 65535 { return 0, fmt.Errorf("неверный порт %q", value) }
	return n, nil
}
func validateDeployProfile(p client.Profile) (string, int, error) {
	host := strings.TrimSpace(p.DeployHost)
	if host == "" || strings.ContainsAny(host, " /\\@?#\r\n\t") {
		return "", 0, errors.New("Укажите IP-адрес или домен VPS без порта.")
	}
	port, err := isValidPort(p.DeploySSHPort)
	if err != nil { return "", 0, fmt.Errorf("SSH-порт: %w", err) }
	if strings.TrimSpace(p.DeployUser) == "" || strings.ContainsAny(p.DeployUser, " \r\n\t") {
		return "", 0, errors.New("Укажите SSH-пользователя.")
	}
	if strings.TrimSpace(p.DeployPrivateKey) == "" && p.DeployPassword == "" {
		return "", 0, errors.New("Укажите пароль SSH или приватный ключ.")
	}
	if p.DeployMode != "" && p.DeployMode != "systemd" && p.DeployMode != "docker" {
		return "", 0, errors.New("Режим установки должен быть systemd или docker.")
	}
	if p.DeployInstance != "" && p.DeployInstance != "main" && p.DeployInstance != "side" {
		return "", 0, errors.New("Экземпляр сервера должен быть main или side.")
	}
	return host, port, nil
}

func deployAuthMethods(p client.Profile) ([]ssh.AuthMethod, error) {
	if strings.TrimSpace(p.DeployPrivateKey) != "" {
		key := []byte(strings.TrimSpace(p.DeployPrivateKey) + "\n")
		signer, err := ssh.ParsePrivateKey(key)
		if err != nil && p.DeployKeyPassphrase != "" {
			signer, err = ssh.ParsePrivateKeyWithPassphrase(key, []byte(p.DeployKeyPassphrase))
		}
		if err != nil { return nil, fmt.Errorf("не удалось прочитать приватный SSH-ключ: %w", err) }
		return []ssh.AuthMethod{ssh.PublicKeys(signer)}, nil
	}
	password := p.DeployPassword
	if password == "" { return nil, errors.New("пароль SSH не задан") }
	return []ssh.AuthMethod{
		ssh.Password(password),
		ssh.KeyboardInteractive(func(_ string, _ string, questions []string, _ []bool) ([]string, error) {
			answers := make([]string, len(questions))
			for i := range answers { answers[i] = password }
			return answers, nil
		}),
	}, nil
}

// connectDeploySSH never trusts an unknown key. The callback reports the SHA256 fingerprint to the UI
// and refuses the handshake until the user explicitly confirms that exact fingerprint.
func connectDeploySSH(p client.Profile) (*ssh.Client, string, error) {
	host, port, err := validateDeployProfile(p)
	if err != nil { return nil, "", err }
	auth, err := deployAuthMethods(p)
	if err != nil { return nil, "", err }
	var presented string
	config := &ssh.ClientConfig{
		User: p.DeployUser,
		Auth: auth,
		Timeout: deploySSHTimeout,
		HostKeyCallback: func(_ string, _ net.Addr, key ssh.PublicKey) error {
			presented = ssh.FingerprintSHA256(key)
			if p.DeployHostKey == "" { return errors.New("SSH host key требует подтверждения пользователя") }
			if presented != p.DeployHostKey { return errors.New("SSH host key изменился; требуется подтверждение пользователя") }
			return nil
		},
	}
	address := net.JoinHostPort(host, strconv.Itoa(port))
	netConn, err := net.DialTimeout("tcp", address, deploySSHTimeout)
	if err != nil { return nil, "", fmt.Errorf("не удалось подключиться к SSH %s: %w", address, err) }
	_ = netConn.SetDeadline(time.Now().Add(deploySSHTimeout))
	conn, chans, reqs, err := ssh.NewClientConn(netConn, address, config)
	if err != nil {
		_ = netConn.Close()
		if presented != "" && presented != p.DeployHostKey { return nil, presented, nil }
		return nil, presented, fmt.Errorf("SSH-аутентификация или handshake не удались: %w", err)
	}
	_ = netConn.SetDeadline(time.Time{})
	return ssh.NewClient(conn, chans, reqs), presented, nil
}

func runSSH(client *ssh.Client, command, stdinSecret string, timeout time.Duration) (string, int, error) {
	session, err := client.NewSession()
	if err != nil { return "", -1, err }
	defer session.Close()
	stdin, err := session.StdinPipe()
	if err != nil { return "", -1, err }
	stdout := &cappedBuffer{limit: deployMaxOutput}
	stderr := &cappedBuffer{limit: deployMaxOutput / 2}
	session.Stdout = stdout
	session.Stderr = stderr
	if err = session.Start(command); err != nil { return "", -1, err }
	if stdinSecret != "" { _, _ = io.WriteString(stdin, stdinSecret+"\n") }
	_ = stdin.Close()
	done := make(chan error, 1)
	go func() { done <- session.Wait() }()
	select {
	case waitErr := <-done:
		output := stdout.String()
		if stderr.Len() > 0 { output += "\n" + stderr.String() }
		if waitErr == nil { return output, 0, nil }
		var exitErr *ssh.ExitError
		if errors.As(waitErr, &exitErr) { return output, exitErr.ExitStatus(), nil }
		return output, -1, waitErr
	case <-time.After(timeout):
		_ = session.Close()
		return stdout.String()+"\n"+stderr.String(), -1, fmt.Errorf("истекло время ожидания SSH-команды (%s)", timeout)
	}
}

func runRootSSH(client *ssh.Client, command, password string, timeout time.Duration) (string, int, error) {
	quoted := shellQuote(command)
	remote := "if [ \"$(id -u)\" = \"0\" ]; then bash -c "+quoted+
		"; elif command -v sudo >/dev/null 2>&1; then sudo -S -p '' bash -c "+quoted+
		"; else echo 'error: root privileges required and sudo not found' >&2; exit 1; fi"
	return runSSH(client, remote, password, timeout)
}

func uploadSSH(client *ssh.Client, remotePath string, data []byte, timeout time.Duration) error {
	session, err := client.NewSession()
	if err != nil { return err }
	defer session.Close()
	stdin, err := session.StdinPipe()
	if err != nil { return err }
	if err = session.Start("umask 077; cat > "+shellQuote(remotePath)); err != nil { return err }
	copyErr := make(chan error, 1)
	go func() { _, e := io.Copy(stdin, bytes.NewReader(data)); copyErr <- e }()
	select {
	case e := <-copyErr:
		if e != nil { return e }
		_ = stdin.Close()
	case <-time.After(timeout):
		_ = session.Close()
		return fmt.Errorf("загрузка файла %s превысила время ожидания", remotePath)
	}
	wait := make(chan error, 1)
	go func() { wait <- session.Wait() }()
	select {
	case err = <-wait: return err
	case <-time.After(timeout):
		_ = session.Close()
		return fmt.Errorf("сервер не подтвердил загрузку %s", remotePath)
	}
}

func parseDeployInventory(output string) (*DeployInventory, error) {
	inventory := &DeployInventory{Servers: []DeployServer{}, Busy: []DeployBusyPort{}}
	finished := false
	for _, raw := range strings.Split(output, "\n") {
		line := strings.TrimSpace(raw)
		if !strings.HasPrefix(line, "CSQTT_INV|") { continue }
		parts := strings.Split(line, "|")
		if len(parts) < 2 { continue }
		if parts[1] == "end" { finished = true; continue }
		fields := map[string]string{}
		for _, item := range parts[2:] {
			if idx := strings.IndexByte(item, '='); idx > 0 { fields[item[:idx]] = item[idx+1:] }
		}
		switch parts[1] {
		case "server":
			place := fields["place"]
			if place != "standard" && place != "side" && place != "panel" && place != "other" && place != "leftover" { continue }
			peer, _ := strconv.Atoi(fields["peer"])
			web, _ := strconv.Atoi(fields["web"])
			version := fields["version"]
			if version == "?" { version = "" }
			inventory.Servers = append(inventory.Servers, DeployServer{
				Place: place, Runtime: fields["runtime"], State: fields["state"], Version: version,
				PeerPort: peer, WebPort: web, Name: fields["name"],
			})
		case "busy":
			port, err := strconv.Atoi(fields["port"])
			if err == nil && port > 0 { inventory.Busy = append(inventory.Busy, DeployBusyPort{Protocol: fields["proto"],Port:port,Holder:fields["by"]}) }
		}
	}
	if !finished { return nil, errors.New("проверка сервера завершилась без маркера CSQTT_INV|end; результат неполный") }
	return inventory, nil
}

func versionAtLeast25(raw string) bool {
	raw = strings.TrimSpace(strings.TrimPrefix(strings.TrimSpace(raw), "v"))
	parts := strings.Split(raw, ".")
	if len(parts) < 2 { return false }
	major, _ := strconv.Atoi(parts[0])
	minor, _ := strconv.Atoi(parts[1])
	return major > 2 || (major == 2 && minor >= 5)
}

func uniqueDeployPorts(p client.Profile) (int, int, error) {
	peer, err := isValidPort(p.DeployPeerPort)
	if err != nil { return 0, 0, fmt.Errorf("UDP peer-порт: %w", err) }
	web, err := isValidPort(p.DeployWebPort)
	if err != nil { return 0, 0, fmt.Errorf("WEB-порт: %w", err) }
	sshPort, err := isValidPort(p.DeploySSHPort)
	if err != nil { return 0, 0, err }
	if peer == web || peer == sshPort || web == sshPort { return 0, 0, errors.New("SSH, peer и WEB должны использовать разные порты") }
	return peer, web, nil
}

func makeDeployPlan(inv *DeployInventory, p client.Profile, appVersion string) deployPlan {
	plan := deployPlan{Actions: []DeployAction{}, Notes: []string{}}
	for _, s := range inv.Servers {
		if s.Place == "panel" {
			plan.Notes = append(plan.Notes, "Обнаружена установка под управлением swg-panel. Управляйте этим сервером через саму панель.")
			return plan
		}
	}
	var standard, side *DeployServer
	var foreign bool
	var leftovers []string
	for i := range inv.Servers {
		s := &inv.Servers[i]
		if s.Place == "standard" && s.State != "leftover" { standard = s }
		if s.Place == "side" && s.State != "leftover" { side = s }
		if s.Place == "other" { foreign = true; plan.Notes = append(plan.Notes, "Обнаружен неуправляемый сервер "+s.Name+"; стандартный деплой не будет его останавливать.") }
		if s.Place == "leftover" { leftovers = append(leftovers, s.Name) }
	}
	busy := map[string]bool{}
	for _, b := range inv.Busy { busy[fmt.Sprintf("%s:%d",b.Protocol,b.Port)] = true }
	activePorts := map[int]bool{}
	for _, s := range inv.Servers { if s.State != "leftover" { if s.PeerPort>0 {activePorts[s.PeerPort]=true}; if s.WebPort>0 {activePorts[s.WebPort]=true} } }
	add := func(action DeployAction) {
		if action.PeerPort <= 0 || action.WebPort <= 0 || action.PeerPort == action.WebPort || action.PeerPort == pDeploySSHPort(p) || action.WebPort == pDeploySSHPort(p) {
			plan.Notes=append(plan.Notes,"Проверьте порты: SSH, peer и WEB должны отличаться.")
			return
		}
		if action.Kind == "install" {
			if busy[fmt.Sprintf("udp:%d",action.PeerPort)] || busy[fmt.Sprintf("tcp:%d",action.WebPort)] || activePorts[action.PeerPort] || activePorts[action.WebPort] {
				plan.Notes=append(plan.Notes,fmt.Sprintf("Новые порты %d/%d заняты другим процессом или сервером.",action.PeerPort,action.WebPort))
				return
			}
		}
		plan.Actions=append(plan.Actions,action)
	}
	if standard != nil && versionAtLeast25(standard.Version) && !foreign {
		peer,web:=standard.PeerPort,standard.WebPort
		if peer==0 {peer=46000}; if web==0 {web=46002}
		add(DeployAction{ID:"update-main",Kind:"update",Instance:"main",Title:"Обновить основной сервер",Detail:fmt.Sprintf("Обновить %s до v%s на текущих портах; конфигурация и база сохраняются.",versionOrUnknown(standard.Version),appVersion),PeerPort:peer,WebPort:web})
	}
	if side != nil {
		peer,web:=side.PeerPort,side.WebPort
		if peer==0 {peer=46100}; if web==0 {web=46102}
		add(DeployAction{ID:"update-side",Kind:"update",Instance:"side",Title:"Обновить второй сервер",Detail:fmt.Sprintf("Обновить второй экземпляр до v%s; основной сервер не затрагивается.",appVersion),PeerPort:peer,WebPort:web})
	}
	if standard != nil && !versionAtLeast25(standard.Version) && side == nil {
		add(DeployAction{ID:"install-side",Kind:"install",Instance:"side",Title:"Установить рядом со старым",Detail:"Новый сервер установится на отдельные порты 46100/46102. Старый сервер продолжит работать.",PeerPort:46100,WebPort:46102})
		if !foreign {
			peer,web:=standard.PeerPort,standard.WebPort
			if peer==0 {peer=46000}; if web==0 {web=46002}
			plan.Actions=append(plan.Actions,DeployAction{ID:"replace-main",Kind:"reinstall",Instance:"main",Title:"Заменить старый сервер",Detail:"Действие удалит прежнюю установку и её локальную базу. Выполнять только после резервной копии.",PeerPort:peer,WebPort:web,Destructive:true})
		}
	}
	if standard == nil && side == nil {
		if foreign || p.DeployInstance == "side" {
			add(DeployAction{ID:"install-side",Kind:"install",Instance:"side",Title:"Установить отдельный экземпляр",Detail:"Новый экземпляр будет установлен на отдельные порты 46100/46102, не затрагивая основной сервер.",PeerPort:46100,WebPort:46102})
		} else {
			peer,web,err:=uniqueDeployPorts(p)
			if err!=nil { plan.Notes=append(plan.Notes,err.Error()) } else {
				if len(leftovers)>0 { plan.Notes=append(plan.Notes,"Найдены остатки прежней установки: "+strings.Join(leftovers,", ")+".") }
				add(DeployAction{ID:"install-main",Kind:"install",Instance:"main",Title:"Установить CSQTT",Detail:fmt.Sprintf("Установить сервер v%s на UDP %d и WEB %d.",appVersion,peer,web),PeerPort:peer,WebPort:web})
			}
		}
	}
	if standard != nil && !foreign {
		peer,web:=standard.PeerPort,standard.WebPort
		if peer==0 {peer=46000}; if web==0 {web=46002}
		plan.Actions=append(plan.Actions,DeployAction{ID:"reinstall-main",Kind:"reinstall",Instance:"main",Title:"Чистая переустановка",Detail:"Текущая конфигурация, база и сертификаты будут удалены. Сделайте резервную копию.",PeerPort:peer,WebPort:web,Destructive:true})
		plan.Actions=append(plan.Actions,DeployAction{ID:"uninstall-main",Kind:"uninstall",Instance:"main",Title:"Удалить основной сервер",Detail:"Скрипт удалит сервер на стандартном месте и его управляемые файлы.",PeerPort:peer,WebPort:web,Destructive:true})
	}
	if side != nil {
		peer,web:=side.PeerPort,side.WebPort
		if peer==0 {peer=46100}; if web==0 {web=46102}
		plan.Actions=append(plan.Actions,DeployAction{ID:"reinstall-side",Kind:"reinstall",Instance:"side",Title:"Чистая переустановка второго",Detail:"Будут удалены конфигурация и база второго экземпляра; основной CSQTT не затрагивается.",PeerPort:peer,WebPort:web,Destructive:true})
		plan.Actions=append(plan.Actions,DeployAction{ID:"uninstall-side",Kind:"uninstall",Instance:"side",Title:"Удалить второй сервер",Detail:"Удаляется только отдельный экземпляр csqtt25.",PeerPort:peer,WebPort:web,Destructive:true})
	}
	return plan
}
func pDeploySSHPort(p client.Profile) int { n,_:=strconv.Atoi(p.DeploySSHPort); return n }
func versionOrUnknown(s string) string { if s=="" { return "неизвестную версию" }; return "v"+s }

func (a *App) currentDeployProfile() client.Profile {
	a.mu.Lock(); defer a.mu.Unlock(); return a.profile
}
func (a *App) InspectDeployServer() (DeployResult, error) {
	p:=a.currentDeployProfile()
	host,port,err:=validateDeployProfile(p)
	if err!=nil { return DeployResult{},err }
	sshClient,presented,err:=connectDeploySSH(p)
	if presented!="" && presented!=p.DeployHostKey {
		prompt:=&DeployHostKeyPrompt{Host:host,Port:port,Presented:presented,Expected:p.DeployHostKey}
		a.deployMu.Lock(); a.pendingDeployHostKey=prompt; a.deployLast=nil; a.deployMu.Unlock()
		return DeployResult{Host:host,Port:port,NeedsTrust:true,KeyChanged:p.DeployHostKey!="",PresentedFingerprint:presented,ExpectedFingerprint:p.DeployHostKey,Message:"Сверьте отпечаток SSH host key с консолью VPS. Соединение пока не аутентифицировано и сервер не изменяется."},nil
	}
	if err!=nil { return DeployResult{},err }
	defer sshClient.Close()
	if p.DeployPassword=="" && strings.TrimSpace(p.DeployPrivateKey)=="" { return DeployResult{},errors.New("укажите SSH-пароль или приватный ключ") }
	if err:=uploadSSH(sshClient,"/tmp/deploy.sh",mustReadDeployScript(),20*time.Second); err!=nil { return DeployResult{},fmt.Errorf("загрузка проверочного deploy.sh: %w",err) }
	out,code,err:=runRootSSH(sshClient,"bash /tmp/deploy.sh inventory",p.DeployPassword,deployInventoryTimeout)
	if err!=nil { return DeployResult{},err }
	if code!=0 { return DeployResult{},fmt.Errorf("проверка сервера завершилась с кодом %d: %s",code,tailText(out,1200)) }
	inv,err:=parseDeployInventory(out)
	if err!=nil { return DeployResult{},err }
	archOut,archCode,archErr:=runSSH(sshClient,"uname -m","",10*time.Second)
	if archErr==nil && archCode==0 { inv.Architecture=strings.TrimSpace(archOut) }
	plan:=makeDeployPlan(inv,p,deployVersion)
	result:=DeployResult{Host:host,Port:port,PresentedFingerprint:presented,Inventory:inv,Actions:plan.Actions,Notes:plan.Notes,Message:"Инвентаризация завершена. Сервер не изменялся."}
	a.deployMu.Lock(); a.pendingDeployHostKey=nil; a.deployLast=&result; a.deployMu.Unlock()
	return result,nil
}

func (a *App) TrustDeployHostKey(fingerprint string) error {
	a.deployMu.Lock()
	prompt:=a.pendingDeployHostKey
	a.deployMu.Unlock()
	if prompt==nil || prompt.Presented=="" || prompt.Presented!=strings.TrimSpace(fingerprint) {
		return errors.New("отпечаток больше не соответствует ожидающему подтверждения SSH-ключу; запустите проверку заново")
	}
	p:=a.currentDeployProfile()
	host,port,err:=validateDeployProfile(p)
	if err!=nil { return err }
	if !strings.EqualFold(host,prompt.Host) || port!=prompt.Port {
		return errors.New("адрес VPS изменился после получения отпечатка; выполните новую проверку")
	}
	p.DeployHostKey=prompt.Presented
	if err:=a.SaveProfile(p,true); err!=nil { return err }
	a.deployMu.Lock(); a.pendingDeployHostKey=nil; a.deployLast=nil; a.deployMu.Unlock()
	return nil
}

func (a *App) StartDeploy(actionID, destructiveConfirmation string) error {
	a.deployMu.Lock()
	if a.deployRunning { a.deployMu.Unlock(); return errors.New("операция на сервере уже выполняется") }
	if a.deployLast==nil { a.deployMu.Unlock(); return errors.New("сначала выполните проверку SSH-соединения и сервера") }
	var selected *DeployAction
	for i:=range a.deployLast.Actions {
		if a.deployLast.Actions[i].ID==actionID { selected=&a.deployLast.Actions[i]; break }
	}
	if selected==nil { a.deployMu.Unlock(); return errors.New("действие отсутствует в последней проверенной инвентаризации") }
	if selected.Destructive && destructiveConfirmation!="УДАЛИТЬ CSQTT" {
		a.deployMu.Unlock()
		return errors.New("для удаления или переустановки требуется подтверждение фразой «УДАЛИТЬ CSQTT»")
	}
	a.deployRunning=true
	a.deployMu.Unlock()
	go func(){
		ok:=false
		err:=a.executeDeploy(actionID)
		if err!=nil { a.emitDeploy(1,err.Error(),true,false) } else { ok=true; a.emitDeploy(1,"Операция завершена",true,true) }
		a.deployMu.Lock(); a.deployRunning=false; a.deployLast=nil; a.deployMu.Unlock()
		_ = ok
	}()
	return nil
}
func (a *App) emitDeploy(percent float64,message string,done,success bool){
	if a.ctx!=nil { runtime.EventsEmit(a.ctx,"deploy-progress",DeployProgress{Percent:percent,Message:message,Done:done,Success:success}) }
}
func (a *App) executeDeploy(actionID string) error {
	result,err:=a.InspectDeployServer()
	if err!=nil { return err }
	if result.NeedsTrust { return errors.New("сервер представил неизвестный SSH host key. Сверьте и подтвердите отпечаток перед деплоем") }
	var action *DeployAction
	for i:=range result.Actions { if result.Actions[i].ID==actionID { action=&result.Actions[i]; break } }
	if action==nil { return errors.New("это действие больше не разрешено результатом проверки. Обновите инвентаризацию") }
	p:=a.currentDeployProfile()
	if action.Kind=="update" && result.Inventory!=nil {
		for _,server:=range result.Inventory.Servers {
			if (action.Instance=="main" && server.Place=="standard") || (action.Instance=="side" && server.Place=="side") {
				if server.Runtime=="docker" { p.DeployMode="docker" } else if server.Runtime=="systemd" { p.DeployMode="systemd" }
			}
		}
	}
	sshClient,presented,err:=connectDeploySSH(p)
	if presented!="" && presented!=p.DeployHostKey { return errors.New("SSH host key изменился после проверки. Подтвердите новый отпечаток") }
	if err!=nil { return err }
	defer sshClient.Close()
	progress:=func(pct float64,msg string){ a.emitDeploy(pct,msg,false,false) }
	progress(0.02,"Подключение по доверенному SSH-ключу…")
	if err:=uploadSSH(sshClient,"/tmp/deploy.sh",mustReadDeployScript(),30*time.Second); err!=nil { return err }
	if action.Kind=="uninstall" {
		command:=deployEnvCommand(p,action)+" bash /tmp/deploy.sh uninstall"
		progress(0.15,"Запуск штатного удаления…")
		out,code,err:=runRootSSH(sshClient,command,p.DeployPassword,30*time.Minute)
		if err!=nil { return err }
		if code!=0 || !strings.Contains(out,"CSQTT_UNINSTALL_OK") { return fmt.Errorf("удаление не подтверждено серверным маркером: %s",tailText(out,1200)) }
		return nil
	}
	progress(0.05,"Определение архитектуры VPS…")
	archOut,code,err:=runSSH(sshClient,"uname -m","",10*time.Second)
	if err!=nil || code!=0 { return fmt.Errorf("не удалось определить архитектуру VPS: %s",tailText(archOut,300)) }
	assetName,err:=assetForArchitecture(strings.TrimSpace(archOut))
	if err!=nil { return err }
	progress(0.08,"Загрузка и проверка серверного ядра SHA-256…")
	binary,err:=downloadServerArtifact(assetName)
	if err!=nil { return err }
	if err:=uploadSSH(sshClient,"/tmp/.csqtt-upload-server",binary,2*time.Minute); err!=nil { return fmt.Errorf("загрузка серверного ядра: %w",err) }
	mode:=p.DeployMode; if mode=="" { mode="systemd" }
	instance:=action.Instance
	if instance=="" { instance="main" }
	if action.Kind=="reinstall" {
		progress(0.13,"Очистка прежней установки по запросу…")
		purge:=deployEnvCommand(p,action)+" bash /tmp/deploy.sh purge"
		out,code,err:=runRootSSH(sshClient,purge,p.DeployPassword,10*time.Minute)
		if err!=nil || code!=0 { return fmt.Errorf("очистка прежней установки не удалась: %s",tailText(out,1200)) }
	}
	if action.Kind!="update" {
		if strings.TrimSpace(p.DeployWebLogin)=="" || strings.TrimSpace(p.DeployWebPassword)=="" || p.DeployMainPassword=="" {
			return errors.New("для новой установки заполните логин/пароль веб-панели и главный пароль CSQTT")
		}
		env:=deployEnvironmentFile(p,mode)
		if err:=uploadSSH(sshClient,"/tmp/.csqtt-upload-web.env",[]byte(env),20*time.Second); err!=nil { return fmt.Errorf("загрузка веб-конфигурации: %w",err) }
		overrides,_:=json.Marshal(map[string]string{"main_password":p.DeployMainPassword})
		if err:=uploadSSH(sshClient,"/tmp/.csqtt-upload-overrides.json",append(overrides,'\n'),20*time.Second); err!=nil { return fmt.Errorf("загрузка deploy-конфигурации: %w",err) }
	}
	actionCommand:="install"
	if action.Kind=="update" { actionCommand="update" }
	command:=deployEnvCommand(p,action)+" bash /tmp/deploy.sh "+actionCommand
	progress(0.18,"Установка/обновление CSQTT на VPS…")
	out,code,err:=runRootSSH(sshClient,command,p.DeployPassword,deployActionTimeout)
	if err!=nil { return err }
	if code!=0 || !strings.Contains(out,"CSQTT_DEPLOY_OK") {
		return fmt.Errorf("сервер не подтвердил успешный деплой (код %d): %s",code,tailText(out,1800))
	}
	return nil
}

func deployEnvCommand(p client.Profile,a *DeployAction) string {
	mode:=p.DeployMode; if mode=="" { mode="systemd" }
	return "env CSQTT_PEER_PORT="+strconv.Itoa(a.PeerPort)+
		" CSQTT_SSH_PORT="+p.DeploySSHPort+
		" CSQTT_WEB_PORT="+strconv.Itoa(a.WebPort)+
		" CSQTT_PUBLIC_IP="+shellQuote(strings.TrimSpace(p.DeployHost))+
		" CSQTT_DEPLOY_MODE="+mode+
		" CSQTT_INSTANCE="+a.Instance
}
func deployEnvironmentFile(p client.Profile,mode string) string {
	format:=systemdEnvValue
	if mode=="docker" { format=dockerEnvValue }
	var b strings.Builder
	fmt.Fprintf(&b,"CSQTT_WEB_USER=%s\n",format(p.DeployWebLogin))
	fmt.Fprintf(&b,"CSQTT_WEB_PASS=%s\n",format(p.DeployWebPassword))
	fmt.Fprintf(&b,"CSQTT_PUBLIC_IP=%s\n",format(p.DeployHost))
	if strings.TrimSpace(p.DeploySecretPath)!="" { fmt.Fprintf(&b,"CSQTT_WEB_SECRET_PATH=%s\n",format(p.DeploySecretPath)) }
	return b.String()
}
func assetForArchitecture(machine string) (string,error) {
	switch strings.ToLower(machine) {
	case "x86_64","amd64": return "csqtt-linux-amd64",nil
	case "aarch64","arm64": return "csqtt-linux-arm64",nil
	case "armv7l","armv7","armhf": return "csqtt-linux-armv7",nil
	default: return "",fmt.Errorf("архитектура VPS %s пока не поддерживается (x86_64, ARM64, ARMv7)",machine)
	}
}
func mustReadDeployScript() []byte { data,err:=deployAssets.ReadFile("assets/deploy.sh"); if err!=nil { panic(err) }; return data }
func tailText(value string,max int) string { value=strings.TrimSpace(value); if len(value)>max { value=value[len(value)-max:] }; return value }

func downloadServerArtifact(assetName string) ([]byte,error) {
	manifestBytes,err:=deployAssets.ReadFile("assets/server-downloads.json")
	if err!=nil { return nil,err }
	var manifest serverManifest
	if err=json.Unmarshal(manifestBytes,&manifest); err!=nil { return nil,fmt.Errorf("манифест серверных сборок повреждён: %w",err) }
	artifact,ok:=manifest[assetName]
	if !ok { return nil,fmt.Errorf("серверная сборка %s отсутствует в манифесте",assetName) }
	parsed,err:=url.Parse(artifact.URL)
	if err!=nil || parsed.Scheme!="https" || parsed.Host!="github.com" { return nil,errors.New("небезопасный URL серверной сборки") }
	if artifact.Size<=0 || artifact.Size>64<<20 || len(artifact.SHA256)!=64 { return nil,errors.New("некорректный размер или SHA-256 серверной сборки") }
	provenanceBytes,err:=deployAssets.ReadFile("assets/csqtt.server-provenance.json")
	if err!=nil { return nil,err }
	var provenance serverProvenance
	if err=json.Unmarshal(provenanceBytes,&provenance); err!=nil || provenance.Marker!="CSQTT_RUST_SERVER_PRODUCTION_V1" || provenance.Version!=deployVersion { return nil,errors.New("provenance серверного бинарника не соответствует ожидаемой версии") }
	matched:=false
	for _,candidate:=range provenance.Artifacts {
		if candidate.AssetName==assetName && candidate.BinarySize==artifact.Size && strings.EqualFold(candidate.BinarySHA256,artifact.SHA256) { matched=true; break }
	}
	if !matched { return nil,errors.New("манифест и provenance серверной сборки расходятся") }
	ctx,cancel:=context.WithTimeout(context.Background(),3*time.Minute); defer cancel()
	req,err:=http.NewRequestWithContext(ctx,http.MethodGet,artifact.URL,nil); if err!=nil { return nil,err }
	resp,err:=http.DefaultClient.Do(req); if err!=nil { return nil,fmt.Errorf("загрузка серверной сборки: %w",err) }
	defer resp.Body.Close()
	if resp.StatusCode!=http.StatusOK { return nil,fmt.Errorf("GitHub вернул HTTP %d при загрузке серверной сборки",resp.StatusCode) }
	data,err:=io.ReadAll(io.LimitReader(resp.Body,artifact.Size+1)); if err!=nil { return nil,err }
	if int64(len(data))!=artifact.Size { return nil,fmt.Errorf("размер серверной сборки не совпадает с манифестом: %d != %d",len(data),artifact.Size) }
	sum:=sha256.Sum256(data)
	if !strings.EqualFold(hex.EncodeToString(sum[:]),artifact.SHA256) { return nil,errors.New("SHA-256 серверной сборки не совпал; файл не будет загружен на VPS") }
	return data,nil
}
