// CSQTT local TCP proxies over a user-space IP stack. No OS adapter or routes.
package main

import (
	"bufio"
	"context"
	"encoding/binary"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/netip"
	"strings"
	"time"

	"golang.zx2c4.com/wireguard/tun/netstack"
)

type dialer func(context.Context, string, string) (net.Conn, error)

func main() {
	core := flag.String("core", "127.0.0.1:9000", "Local CSQTT IP packet socket")
	ip := flag.String("ip", "", "IPv4 assigned by TUNCONF")
	dns := flag.String("dns", "1.1.1.1", "Tunnel DNS IPv4, comma separated")
	socks := flag.String("socks", "127.0.0.1:1080", "SOCKS5 listener")
	web := flag.String("http", "127.0.0.1:8080", "HTTP proxy listener")
	flag.Parse()
	localIP, err := netip.ParseAddr(*ip)
	if err != nil || !localIP.Is4() {
		log.Fatal("--ip must be an IPv4 assigned by CSQTT")
	}
	var servers []netip.Addr
	for _, value := range strings.Split(*dns, ",") {
		address, err := netip.ParseAddr(strings.TrimSpace(value))
		if err == nil && address.Is4() {
			servers = append(servers, address)
		}
	}
	if len(servers) == 0 {
		log.Fatal("No valid tunnel DNS IPv4")
	}
	if err := loopback(*core); err != nil {
		log.Fatal(err)
	}
	if err := loopback(*socks); err != nil {
		log.Fatal(err)
	}
	if err := loopback(*web); err != nil {
		log.Fatal(err)
	}
	dev, network, err := netstack.CreateNetTUN([]netip.Addr{localIP}, servers, 1280)
	if err != nil {
		log.Fatal(err)
	}
	address, _ := net.ResolveUDPAddr("udp4", *core)
	wire, err := net.DialUDP("udp4", &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1)}, address)
	if err != nil {
		log.Fatal(err)
	}
	go func() {
		buffers := [][]byte{make([]byte, 65535)}
		sizes := make([]int, 1)
		for {
			count, err := dev.Read(buffers, sizes, 0)
			if err != nil {
				log.Fatal("Packet stack read: ", err)
			}
			for i := 0; i < count; i++ {
				if _, err := wire.Write(buffers[i][:sizes[i]]); err != nil {
					log.Fatal(err)
				}
			}
		}
	}()
	go func() {
		buffer := make([]byte, 65535)
		for {
			size, err := wire.Read(buffer)
			// Windows can report ICMP port unreachable until the core finishes binding.
			if err != nil {
				time.Sleep(100 * time.Millisecond)
				continue
			}
			if _, err := dev.Write([][]byte{buffer[:size]}, 0); err != nil {
				log.Fatal(err)
			}
		}
	}()
	listener, err := net.Listen("tcp4", *socks)
	if err != nil {
		log.Fatal(err)
	}
	httpListener, err := net.Listen("tcp4", *web)
	if err != nil {
		log.Fatal(err)
	}
	dial := dialer(network.DialContext)
	go func() { log.Fatal(http.Serve(httpListener, proxyHandler(dial))) }()
	fmt.Printf("PROXY_READY SOCKS5=%s HTTP=%s\n", *socks, *web)
	for {
		conn, err := listener.Accept()
		if err != nil {
			log.Fatal(err)
		}
		go serveSOCKS(conn, dial)
	}
}

func loopback(value string) error {
	address, err := netip.ParseAddrPort(value)
	if err != nil || !address.Addr().IsLoopback() || address.Port() == 0 {
		return fmt.Errorf("only a loopback IP:port is permitted: %s", value)
	}
	return nil
}

func bridge(client net.Conn, remote net.Conn) {
	defer remote.Close()
	done := make(chan struct{})
	go func() {
		io.Copy(remote, client)
		if closer, ok := remote.(interface{ CloseWrite() error }); ok {
			closer.CloseWrite()
		}
		close(done)
	}()
	io.Copy(client, remote)
	client.Close()
	remote.Close()
	<-done
}

func serveSOCKS(client net.Conn, dial dialer) {
	defer client.Close()
	client.SetDeadline(time.Now().Add(30 * time.Second))
	var head [2]byte
	if _, err := io.ReadFull(client, head[:]); err != nil || head[0] != 5 || head[1] == 0 {
		return
	}
	methods := make([]byte, int(head[1]))
	if _, err := io.ReadFull(client, methods); err != nil {
		return
	}
	found := false
	for _, method := range methods {
		found = found || method == 0
	}
	if !found {
		client.Write([]byte{5, 255})
		return
	}
	if _, err := client.Write([]byte{5, 0}); err != nil {
		return
	}
	var req [4]byte
	if _, err := io.ReadFull(client, req[:]); err != nil || req[0] != 5 || req[2] != 0 {
		return
	}
	reply := func(code byte) { client.Write([]byte{5, code, 0, 1, 127, 0, 0, 1, 0, 0}) }
	if req[1] != 1 {
		reply(7)
		return
	} // No UDP ASSOCIATE or BIND.
	var host string
	switch req[3] {
	case 1:
		var value [4]byte
		if _, err := io.ReadFull(client, value[:]); err != nil {
			return
		}
		host = net.IP(value[:]).String()
	case 3:
		var size [1]byte
		if _, err := io.ReadFull(client, size[:]); err != nil || size[0] == 0 {
			return
		}
		value := make([]byte, int(size[0]))
		if _, err := io.ReadFull(client, value); err != nil {
			return
		}
		host = string(value)
	default:
		reply(8)
		return
	}
	var port [2]byte
	if _, err := io.ReadFull(client, port[:]); err != nil {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 25*time.Second)
	defer cancel()
	remote, err := dial(ctx, "tcp4", net.JoinHostPort(host, fmt.Sprint(binary.BigEndian.Uint16(port[:]))))
	if err != nil {
		reply(4)
		return
	}
	reply(0)
	client.SetDeadline(time.Time{})
	bridge(client, remote)
}

// Preserve bytes already buffered by net/http after CONNECT (e.g. TLS ClientHello).
type bufferedConn struct {
	net.Conn
	reader *bufio.Reader
}

func (c *bufferedConn) Read(p []byte) (int, error) { return c.reader.Read(p) }

func proxyHandler(dial dialer) http.Handler {
	transport := &http.Transport{DialContext: dial, Proxy: nil, ResponseHeaderTimeout: 30 * time.Second}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodConnect {
			host, port, err := net.SplitHostPort(r.Host)
			if err != nil || host == "" || port == "" {
				http.Error(w, "CONNECT requires host:port", 400)
				return
			}
			ctx, cancel := context.WithTimeout(r.Context(), 25*time.Second)
			defer cancel()
			remote, err := dial(ctx, "tcp4", r.Host)
			if err != nil {
				http.Error(w, "Tunnel connection failed", 502)
				return
			}
			hijacker, ok := w.(http.Hijacker)
			if !ok {
				remote.Close()
				http.Error(w, "Hijack unavailable", 500)
				return
			}
			client, buffer, err := hijacker.Hijack()
			if err != nil {
				remote.Close()
				return
			}
			if _, err = buffer.WriteString("HTTP/1.1 200 Connection Established\r\n\r\n"); err != nil {
				client.Close()
				remote.Close()
				return
			}
			if err = buffer.Flush(); err != nil {
				client.Close()
				remote.Close()
				return
			}
			bridge(&bufferedConn{client, buffer.Reader}, remote)
			return
		}
		if !r.URL.IsAbs() || (r.URL.Scheme != "http" && r.URL.Scheme != "https") {
			http.Error(w, "Absolute proxy URL required", 400)
			return
		}
		out := r.Clone(r.Context())
		out.RequestURI = ""
		out.Header = out.Header.Clone()
		removeHopHeaders(out.Header)
		response, err := transport.RoundTrip(out)
		if err != nil {
			if !errors.Is(err, context.Canceled) {
				http.Error(w, "Tunnel request failed", 502)
			}
			return
		}
		defer response.Body.Close()
		removeHopHeaders(response.Header)
		for key, values := range response.Header {
			for _, value := range values {
				w.Header().Add(key, value)
			}
		}
		w.WriteHeader(response.StatusCode)
		io.Copy(w, response.Body)
	})
}

func removeHopHeaders(h http.Header) {
	for _, line := range h.Values("Connection") {
		for _, key := range strings.Split(line, ",") {
			h.Del(strings.TrimSpace(key))
		}
	}
	for _, key := range []string{"Connection", "Proxy-Connection", "Proxy-Authorization", "Proxy-Authenticate", "Keep-Alive", "TE", "Trailer", "Transfer-Encoding", "Upgrade"} {
		h.Del(key)
	}
}
