package main

import (
	"bufio"
	"context"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"strings"
	"testing"
	"time"

	"golang.zx2c4.com/wireguard/tun"
	"golang.zx2c4.com/wireguard/tun/netstack"
)

func networkPair(t *testing.T) (*netstack.Net, *netstack.Net) {
	t.Helper()
	da, a, err := netstack.CreateNetTUN([]netip.Addr{netip.MustParseAddr("10.50.0.1")}, nil, 1280)
	if err != nil {
		t.Fatal(err)
	}
	db, b, err := netstack.CreateNetTUN([]netip.Addr{netip.MustParseAddr("10.50.0.2")}, nil, 1280)
	if err != nil {
		t.Fatal(err)
	}
	pump := func(from, to tun.Device) {
		buffers := [][]byte{make([]byte, 65535)}
		sizes := make([]int, 1)
		for {
			n, err := from.Read(buffers, sizes, 0)
			if err != nil {
				return
			}
			for i := 0; i < n; i++ {
				if _, err := to.Write([][]byte{buffers[i][:sizes[i]]}, 0); err != nil {
					return
				}
			}
		}
	}
	go pump(da, db)
	go pump(db, da)
	t.Cleanup(func() { da.Close(); db.Close() })
	return a, b
}

func TestSOCKSAndHTTPOverIPPackets(t *testing.T) {
	a, b := networkPair(t)
	echo, err := b.ListenTCPAddrPort(netip.MustParseAddrPort("10.50.0.2:8022"))
	if err != nil {
		t.Fatal(err)
	}
	defer echo.Close()
	go func() {
		for {
			c, err := echo.Accept()
			if err != nil {
				return
			}
			go func() { defer c.Close(); io.Copy(c, c) }()
		}
	}()
	web, err := b.ListenTCPAddrPort(netip.MustParseAddrPort("10.50.0.2:8080"))
	if err != nil {
		t.Fatal(err)
	}
	defer web.Close()
	go http.Serve(web, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Proxy-Authorization") != "" {
			t.Error("Proxy credentials leaked to destination")
		}
		w.Write([]byte("tunnel-response"))
	}))
	socks, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer socks.Close()
	go func() {
		for {
			c, e := socks.Accept()
			if e != nil {
				return
			}
			go serveSOCKS(c, a.DialContext)
		}
	}()
	t.Run("SOCKS_CONNECT", func(t *testing.T) {
		c, e := net.Dial("tcp4", socks.Addr().String())
		if e != nil {
			t.Fatal(e)
		}
		defer c.Close()
		c.SetDeadline(time.Now().Add(5 * time.Second))
		c.Write([]byte{5, 1, 0})
		var method [2]byte
		io.ReadFull(c, method[:])
		if method != [2]byte{5, 0} {
			t.Fatal(method)
		}
		c.Write([]byte{5, 1, 0, 1, 10, 50, 0, 2, 0x1f, 0x56}) // 8022
		var result [10]byte
		if _, e = io.ReadFull(c, result[:]); e != nil || result[1] != 0 {
			t.Fatalf("SOCKS reply %v %v", result, e)
		}
		c.Write([]byte("hello"))
		var data [5]byte
		if _, e = io.ReadFull(c, data[:]); e != nil || string(data[:]) != "hello" {
			t.Fatalf("echo %s %v", data, e)
		}
	})
	t.Run("SOCKS_UDP_REJECTED", func(t *testing.T) {
		c, _ := net.Dial("tcp4", socks.Addr().String())
		defer c.Close()
		c.SetDeadline(time.Now().Add(5 * time.Second))
		c.Write([]byte{5, 1, 0})
		io.ReadFull(c, make([]byte, 2))
		c.Write([]byte{5, 3, 0, 1})
		var reply [10]byte
		if _, err := io.ReadFull(c, reply[:]); err != nil || reply[1] != 7 {
			t.Fatalf("UDP was not rejected: %v %v", reply, err)
		}
	})
	proxy := httptest.NewServer(proxyHandler(a.DialContext))
	defer proxy.Close()
	t.Run("HTTP_GET", func(t *testing.T) {
		c, _ := net.Dial("tcp4", strings.TrimPrefix(proxy.URL, "http://"))
		defer c.Close()
		c.SetDeadline(time.Now().Add(5 * time.Second))
		io.WriteString(c, "GET http://10.50.0.2:8080/ HTTP/1.1\r\nHost: 10.50.0.2:8080\r\nProxy-Authorization: Basic test\r\nConnection: close\r\n\r\n")
		response, err := http.ReadResponse(bufio.NewReader(c), nil)
		if err != nil {
			t.Fatal(err)
		}
		defer response.Body.Close()
		data, _ := io.ReadAll(response.Body)
		if response.StatusCode != 200 || string(data) != "tunnel-response" {
			t.Fatalf("%d %s", response.StatusCode, data)
		}
	})
	t.Run("HTTP_CONNECT_BUFFERED_BYTES", func(t *testing.T) {
		c, _ := net.Dial("tcp4", strings.TrimPrefix(proxy.URL, "http://"))
		defer c.Close()
		c.SetDeadline(time.Now().Add(5 * time.Second))
		io.WriteString(c, "CONNECT 10.50.0.2:8022 HTTP/1.1\r\nHost: 10.50.0.2:8022\r\n\r\nhello")
		reader := bufio.NewReader(c)
		response, err := http.ReadResponse(reader, &http.Request{Method: "CONNECT"})
		if err != nil || response.StatusCode != 200 {
			t.Fatalf("%v %v", response, err)
		}
		var data [5]byte
		if _, err = io.ReadFull(reader, data[:]); err != nil || string(data[:]) != "hello" {
			t.Fatalf("buffered echo %s %v", data, err)
		}
	})
}

func TestLoopbackOnly(t *testing.T) {
	for _, address := range []string{"0.0.0.0:1080", "10.0.0.1:1080", "localhost:1080", "127.0.0.1:0"} {
		if loopback(address) == nil {
			t.Fatal("accepted", address)
		}
	}
	if err := loopback("127.0.0.1:1080"); err != nil {
		t.Fatal(err)
	}
}

func TestSOCKSAuthRejected(t *testing.T) {
	c, s := net.Pipe()
	defer c.Close()
	go serveSOCKS(s, func(context.Context, string, string) (net.Conn, error) {
		t.Error("unexpected dial")
		return nil, io.EOF
	})
	c.SetDeadline(time.Now().Add(time.Second))
	c.Write([]byte{5, 1, 2})
	var reply [2]byte
	io.ReadFull(c, reply[:])
	if reply != [2]byte{5, 255} {
		t.Fatal(reply)
	}
}
