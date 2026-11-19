//go:build linux

package main

import (
	"net/netip"
	"testing"
)

func TestParseLinuxDNSServers(t *testing.T) {
	got, err := parseLinuxDNSServers("1.1.1.1, 8.8.8.8, 1.1.1.1")
	if err != nil {
		t.Fatal(err)
	}
	want := []netip.Addr{netip.MustParseAddr("1.1.1.1"), netip.MustParseAddr("8.8.8.8")}
	if len(got) != len(want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("got %v, want %v", got, want)
		}
	}
}

func TestParseLinuxDNSServersRejectsInvalid(t *testing.T) {
	for _, value := range []string{"", "dns.google", "1.1.1.1, not-an-ip", "2001:4860:4860::8888"} {
		if _, err := parseLinuxDNSServers(value); err == nil {
			t.Fatalf("expected DNS validation error for %q", value)
		}
	}
}

func TestParseLinuxBypassIPsDeduplicates(t *testing.T) {
	got, err := parseLinuxBypassIPs("203.0.113.1, 203.0.113.2,203.0.113.1")
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 2 {
		t.Fatalf("got %v, want two addresses", got)
	}
}
