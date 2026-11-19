//go:build linux

package main

import (
	"context"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/netip"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"
	"unsafe"

	"golang.org/x/sys/unix"
)

const (
	linuxTunName = "csqtt0"
	linuxTunMTU  = 1280
	tunSetIFF    = 0x400454ca
	iffTun       = 0x0001
	iffNoPI      = 0x1000
)

type linuxBypassRoute struct {
	IP      string `json:"ip"`
	Device  string `json:"device"`
	Gateway string `json:"gateway"`
	Add     bool   `json:"add"`
}

type linuxTunState struct {
	InterfaceName string             `json:"interface_name"`
	ProxyIP       string             `json:"proxy_ip,omitempty"`
	DNSIPs        []string           `json:"dns_ips"`
	ProxyRoute    bool               `json:"proxy_route,omitempty"`
	BypassRoutes  []linuxBypassRoute `json:"bypass_routes,omitempty"`
	HelperPID     int                `json:"helper_pid"`
}

type linuxPhysicalRoute struct {
	Device  string
	Gateway string
}

func runTunMode(ctx context.Context, core, ip, dns, bypassIP, tunUDS string, parentPID int, ready func() error) error {
	if err := loopback(core); err != nil { return err }
	if os.Geteuid() != 0 {
		return errors.New("Linux TUN requires administrator privileges; confirm the polkit request")
	}
	if tunUDS == "" {
		return errors.New("Linux TUN requires --tun-uds so the core can receive the native TUN file descriptor")
	}
	if parentPID <= 0 {
		return errors.New("Linux TUN requires a valid --parent-pid for crash cleanup")
	}
	if _, err := exec.LookPath("ip"); err != nil {
		return errors.New("iproute2 is required (install the iproute2 package)")
	}
	if _, err := exec.LookPath("resolvectl"); err != nil {
		return errors.New("systemd-resolved is required for per-interface DNS routing (install and start systemd-resolved)")
	}

	recovered, err := recoverTunState()
	if err != nil {
		return fmt.Errorf("cannot recover a previous Linux TUN session: %w", err)
	}
	if !recovered {
		exists, err := linuxTunStateExists()
		if err != nil {
			return err
		}
		if exists {
			return errors.New("another CSQTT TUN helper is already active")
		}
	}

	tunIP, err := netip.ParseAddr(ip)
	if err != nil || !tunIP.Is4() {
		return errors.New("--ip must be the IPv4 address supplied by TUNCONF")
	}
	bypassIPs, err := parseLinuxBypassIPs(bypassIP)
	if err != nil {
		return err
	}
	dnsServers, err := parseLinuxDNSServers(dns)
	if err != nil {
		return err
	}
	bypassRoutes := make([]linuxBypassRoute, 0, len(bypassIPs))
	for _, address := range bypassIPs {
		physical, routeErr := findLinuxPhysicalRoute(address)
		if routeErr != nil {
			return fmt.Errorf("cannot determine physical route to server %s: %w", address, routeErr)
		}
		if physical.Device == linuxTunName || physical.Device == "lo" {
			return fmt.Errorf("server %s must be reachable through a physical interface, got %s", address, physical.Device)
		}
		bypassRoutes = append(bypassRoutes, linuxBypassRoute{
			IP: address.String(), Device: physical.Device, Gateway: physical.Gateway,
			Add: true,
		})
	}

	for _, route := range bypassRoutes {
		prefix := route.IP + "/32"
		exists, err := exactLinuxRoutePrefixExists(prefix)
		if err != nil {
			return err
		}
		if exists {
			return fmt.Errorf("route %s already exists; refusing to overwrite an existing system route", prefix)
		}
	}
	for _, prefix := range []string{"0.0.0.0/1", "128.0.0.0/1"} {
		exists, err := exactLinuxRoutePrefixExists(prefix)
		if err != nil {
			return err
		}
		if exists {
			return fmt.Errorf("route %s already exists; refusing to overwrite an existing system route", prefix)
		}
	}
	for _, server := range dnsServers {
		if linuxBypassContains(bypassIPs, server) {
			continue
		}
		exists, err := exactLinuxRoutePrefixExists(server.String() + "/32")
		if err != nil {
			return err
		}
		if exists {
			return fmt.Errorf("DNS route %s/32 already exists; refusing to overwrite an existing system route", server)
		}
	}
	if _, err := net.InterfaceByName(linuxTunName); err == nil {
		return fmt.Errorf("interface %s already exists; remove it after checking that no other VPN is using it", linuxTunName)
	}

	device, ifName, err := createLinuxTun(linuxTunName)
	if err != nil {
		return fmt.Errorf("cannot create /dev/net/tun: %w", err)
	}
	defer device.Close()

	state := linuxTunState{
		InterfaceName: ifName,
		BypassRoutes: bypassRoutes,
		HelperPID: os.Getpid(),
	}
	for _, server := range dnsServers {
		if !linuxBypassContains(bypassIPs, server) {
			state.DNSIPs = append(state.DNSIPs, server.String())
		}
	}
	statePath, err := writeLinuxTunState(state)
	if err != nil {
		return err
	}
	cleanupNeeded := true
	defer func() {
		if cleanupNeeded {
			if cleanupErr := cleanupLinuxTun(state, statePath); cleanupErr != nil {
				fmt.Fprintln(os.Stderr, "TUN cleanup warning:", cleanupErr)
			}
		}
	}()

	if err := runIP("addr", "add", tunIP.String()+"/32", "dev", ifName); err != nil {
		return fmt.Errorf("cannot assign TUN address: %w", err)
	}
	if err := runIP("link", "set", "dev", ifName, "mtu", strconv.Itoa(linuxTunMTU), "up"); err != nil {
		return fmt.Errorf("cannot bring the TUN interface up: %w", err)
	}

	for _, route := range bypassRoutes {
		if !route.Add {
			continue
		}
		args := []string{"route", "add", route.IP + "/32"}
		if route.Gateway != "" {
			args = append(args, "via", route.Gateway)
		}
		args = append(args, "dev", route.Device)
		if err := runIP(args...); err != nil {
			return fmt.Errorf("cannot pin server route %s to physical interface %s: %w", route.IP, route.Device, err)
		}
	}

	for _, server := range dnsServers {
		if linuxBypassContains(bypassIPs, server) {
			continue
		}
		if err := runIP("route", "add", server.String()+"/32", "dev", ifName); err != nil {
			return fmt.Errorf("cannot route DNS server %s through TUN: %w", server, err)
		}
	}
	if err := runIP("route", "add", "0.0.0.0/1", "dev", ifName); err != nil {
		return fmt.Errorf("cannot add the first TUN default route: %w", err)
	}
	if err := runIP("route", "add", "128.0.0.0/1", "dev", ifName); err != nil {
		return fmt.Errorf("cannot add the second TUN default route: %w", err)
	}

	dnsArgs := []string{"dns", ifName}
	for _, server := range dnsServers {
		dnsArgs = append(dnsArgs, server.String())
	}
	if err := runResolveCtl(dnsArgs...); err != nil {
		return fmt.Errorf("cannot configure DNS on TUN: %w", err)
	}
	if err := runResolveCtl("domain", ifName, "~."); err != nil {
		return fmt.Errorf("cannot route system DNS queries through TUN: %w", err)
	}
	if err := runResolveCtl("default-route", ifName, "yes"); err != nil {
		return fmt.Errorf("cannot set TUN as the default DNS route: %w", err)
	}
	_ = runResolveCtl("flush-caches")

	if err := sendLinuxTunFD(tunUDS, device); err != nil {
		return fmt.Errorf("cannot pass the TUN file descriptor to the CSQTT core: %w", err)
	}

	if err := ready(); err != nil {
		return fmt.Errorf("cannot start local proxies over TUN: %w", err)
	}
	dnsText := make([]string, 0, len(dnsServers))
	for _, server := range dnsServers {
		dnsText = append(dnsText, server.String())
	}
	fmt.Printf("TUN_READY interface=%s ip=%s dns=%s\\n", ifName, tunIP, strings.Join(dnsText, ","))
	ticker := time.NewTicker(time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			fmt.Println("TUN_STOPPED")
			cleanupNeeded = false
			return cleanupLinuxTun(state, statePath)
		case <-ticker.C:
			if !linuxProcessIsRunning(parentPID) {
				fmt.Fprintln(os.Stderr, "GUI process exited; restoring Linux networking")
				cleanupNeeded = false
				return cleanupLinuxTun(state, statePath)
			}
		}
	}
}

func createLinuxTun(name string) (*os.File, string, error) {
	fd, err := unix.Open("/dev/net/tun", unix.O_RDWR|unix.O_CLOEXEC, 0)
	if err != nil {
		return nil, "", err
	}
	request := make([]byte, unix.IFNAMSIZ+24)
	copy(request[:unix.IFNAMSIZ], name)
	binary.NativeEndian.PutUint16(request[unix.IFNAMSIZ:unix.IFNAMSIZ+2], iffTun|iffNoPI)
	_, _, errno := unix.Syscall(unix.SYS_IOCTL, uintptr(fd), uintptr(tunSetIFF), uintptr(unsafe.Pointer(&request[0])))
	if errno != 0 {
		_ = unix.Close(fd)
		return nil, "", errno
	}
	actual := strings.TrimRight(string(request[:unix.IFNAMSIZ]), "\x00")
	return os.NewFile(uintptr(fd), "/dev/net/tun"), actual, nil
}

func sendLinuxTunFD(name string, device *os.File) error {
	address := &net.UnixAddr{Name: "@" + name, Net: "unix"}
	deadline := time.Now().Add(30 * time.Second)
	var lastErr error
	for time.Now().Before(deadline) {
		connection, err := net.DialUnix("unix", nil, address)
		if err != nil {
			lastErr = err
			time.Sleep(150 * time.Millisecond)
			continue
		}
		_ = connection.SetDeadline(time.Now().Add(5 * time.Second))
		control := unix.UnixRights(int(device.Fd()))
		_, _, err = connection.WriteMsgUnix([]byte{1}, control, nil)
		if err == nil {
			ack := []byte{0}
			_, err = io.ReadFull(connection, ack)
			if err == nil && ack[0] != 1 {
				err = errors.New("CSQTT core rejected the TUN file descriptor")
			}
		}
		_ = connection.Close()
		if err == nil {
			return nil
		}
		lastErr = err
		time.Sleep(150 * time.Millisecond)
	}
	return fmt.Errorf("Unix FD socket %q did not accept the TUN device within 30 seconds: %w", name, lastErr)
}

func parseLinuxBypassIPs(value string) ([]netip.Addr, error) {
	seen := map[netip.Addr]bool{}
	var result []netip.Addr
	for _, item := range strings.Split(value, ",") {
		address, err := netip.ParseAddr(strings.TrimSpace(item))
		if err == nil && address.Is4() && !seen[address] {
			seen[address] = true
			result = append(result, address)
		}
	}
	if len(result) == 0 {
		return nil, errors.New("--bypass-ip must contain at least one TURN server or HTTP proxy IPv4 address")
	}
	return result, nil
}

func linuxBypassContains(addresses []netip.Addr, value netip.Addr) bool {
	for _, address := range addresses {
		if address == value {
			return true
		}
	}
	return false
}

func parseLinuxDNSServers(value string) ([]netip.Addr, error) {
	seen := map[netip.Addr]bool{}
	var result []netip.Addr
	for _, item := range strings.Split(value, ",") {
		address, err := netip.ParseAddr(strings.TrimSpace(item))
		if err == nil && address.Is4() && !seen[address] {
			seen[address] = true
			result = append(result, address)
		}
	}
	if len(result) == 0 {
		return nil, errors.New("TUNCONF does not contain a valid DNS IPv4 address")
	}
	return result, nil
}

func findLinuxPhysicalRoute(target netip.Addr) (linuxPhysicalRoute, error) {
	output, err := exec.Command("ip", "-4", "route", "get", target.String()).CombinedOutput()
	if err != nil {
		return linuxPhysicalRoute{}, fmt.Errorf("ip route get: %w: %s", err, strings.TrimSpace(string(output)))
	}
	fields := strings.Fields(string(output))
	var result linuxPhysicalRoute
	for index := 0; index+1 < len(fields); index++ {
		switch fields[index] {
		case "dev":
			result.Device = fields[index+1]
		case "via":
			result.Gateway = fields[index+1]
		}
	}
	if result.Device == "" {
		return linuxPhysicalRoute{}, fmt.Errorf("ip route get returned no physical interface: %s", strings.TrimSpace(string(output)))
	}
	if _, err := net.InterfaceByName(result.Device); err != nil {
		return linuxPhysicalRoute{}, err
	}
	return result, nil
}

func exactLinuxRoutePrefixExists(prefix string) (bool, error) {
	output, err := exec.Command("ip", "-4", "route", "show", "exact", prefix).CombinedOutput()
	if err != nil {
		return false, fmt.Errorf("ip route show exact %s: %w: %s", prefix, err, strings.TrimSpace(string(output)))
	}
	return strings.TrimSpace(string(output)) != "", nil
}

func runIP(args ...string) error {
	output, err := exec.Command("ip", args...).CombinedOutput()
	if err != nil {
		return fmt.Errorf("ip %s: %w: %s", strings.Join(args, " "), err, strings.TrimSpace(string(output)))
	}
	return nil
}

func runResolveCtl(args ...string) error {
	output, err := exec.Command("resolvectl", args...).CombinedOutput()
	if err != nil {
		return fmt.Errorf("resolvectl %s: %w: %s", strings.Join(args, " "), err, strings.TrimSpace(string(output)))
	}
	return nil
}

func linuxTunStatePath() (string, error) {
	directory := "/run/csqtt"
	if err := os.MkdirAll(directory, 0700); err != nil {
		return "", err
	}
	return filepath.Join(directory, "tun-state.json"), nil
}

func writeLinuxTunState(state linuxTunState) (string, error) {
	path, err := linuxTunStatePath()
	if err != nil {
		return "", err
	}
	data, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return "", err
	}
	temp := path + ".tmp"
	if err := os.WriteFile(temp, data, 0600); err != nil {
		return "", err
	}
	if err := os.Rename(temp, path); err != nil {
		_ = os.Remove(temp)
		return "", err
	}
	return path, nil
}

func linuxTunStateExists() (bool, error) {
	path, err := linuxTunStatePath()
	if err != nil {
		return false, err
	}
	_, err = os.Stat(path)
	if errors.Is(err, os.ErrNotExist) {
		return false, nil
	}
	return err == nil, err
}

func recoverTunState() (bool, error) {
	path, err := linuxTunStatePath()
	if err != nil {
		return false, err
	}
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	var state linuxTunState
	if err := json.Unmarshal(data, &state); err != nil {
		return false, fmt.Errorf("corrupt Linux TUN recovery state: %w", err)
	}
	if state.HelperPID > 0 && linuxProcessIsRunning(state.HelperPID) {
		return false, nil
	}
	if err := cleanupLinuxTun(state, path); err != nil {
		return false, err
	}
	return true, nil
}

func cleanupLinuxTun(state linuxTunState, path string) error {
	var problems []string
	if _, err := exec.LookPath("resolvectl"); err == nil && state.InterfaceName != "" {
		// After a hard crash, closing the last TUN FD may already have removed
		// the link and its resolver state. Revert only while the link still exists.
		if _, linkErr := net.InterfaceByName(state.InterfaceName); linkErr == nil {
			if err := runResolveCtl("revert", state.InterfaceName); err != nil {
				problems = append(problems, err.Error())
			}
		}
	}
	for _, route := range []string{"0.0.0.0/1", "128.0.0.0/1"} {
		_ = exec.Command("ip", "route", "del", route, "dev", state.InterfaceName).Run()
	}
	for _, server := range state.DNSIPs {
		_ = exec.Command("ip", "route", "del", server+"/32", "dev", state.InterfaceName).Run()
	}
	if len(state.BypassRoutes) > 0 {
		for _, route := range state.BypassRoutes {
			if route.Add {
				_ = exec.Command("ip", "route", "del", route.IP+"/32").Run()
			}
		}
	} else if state.ProxyRoute && state.ProxyIP != "" {
		// Backward-compatible cleanup for old recovery state files.
		_ = exec.Command("ip", "route", "del", state.ProxyIP+"/32").Run()
	}
	if state.InterfaceName != "" {
		_ = exec.Command("ip", "link", "delete", "dev", state.InterfaceName).Run()
	}
	if len(problems) == 0 {
		if err := os.Remove(path); err != nil && !errors.Is(err, os.ErrNotExist) {
			problems = append(problems, err.Error())
		}
	}
	if len(problems) > 0 {
		return errors.New(strings.Join(problems, "; "))
	}
	return nil
}

func linuxProcessIsRunning(pid int) bool {
	if pid <= 0 {
		return false
	}
	err := unix.Kill(pid, 0)
	return err == nil || errors.Is(err, unix.EPERM)
}
