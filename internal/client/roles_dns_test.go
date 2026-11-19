package client

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/sha256"
	"encoding/base64"
	"testing"
)

func TestDNSOverrideValidation(t *testing.T) {
	p := valid()
	p.DNS = "1.1.1.1, 8.8.8.8"
	if _, err := p.Validate(); err != nil {
		t.Fatalf("multiple valid IPv4 DNS addresses rejected: %v", err)
	}
	p.DNS = "dns.google"
	if _, err := p.Validate(); err == nil {
		t.Fatal("DNS hostname must be rejected: helper accepts IPv4 addresses")
	}
	p.DNS = "1.1.1.1, 1.1.1.1"
	if _, err := p.Validate(); err == nil {
		t.Fatal("duplicate DNS address must be rejected")
	}
}

func TestParseClientShareLinks(t *testing.T) {
	t.Run("v2 plaintext query", func(t *testing.T) {
		link, err := ParseShareLink("csqtt://connect?v=2&host=203.0.113.10&peer=46000&password=shared-pass&hashes=abcdef1234567890")
		if err != nil {
			t.Fatal(err)
		}
		if link.Server != "203.0.113.10:46000" || link.Password != "shared-pass" || link.Hashes != "abcdef1234567890" {
			t.Fatalf("unexpected parsed link: %#v", link)
		}
	})
	t.Run("encrypted URL-safe payload", func(t *testing.T) {
		key := sha256.Sum256([]byte(shareCipherSeed))
		block, err := aes.NewCipher(key[:])
		if err != nil {
			t.Fatal(err)
		}
		gcm, err := cipher.NewGCM(block)
		if err != nil {
			t.Fatal(err)
		}
		nonce := []byte("0123456789ab")
		plain := []byte("connect?v=2&host=csqtt.example.net&peer=46000&password=sealed-pass&hashes=abcdef1234567890")
		sealed := gcm.Seal(append([]byte{}, nonce...), nonce, plain, nil)
		encoded := base64.RawURLEncoding.EncodeToString(sealed)
		link, err := ParseShareLink("csqtt://" + encoded)
		if err != nil {
			t.Fatal(err)
		}
		if link.Server != "csqtt.example.net:46000" || link.Password != "sealed-pass" {
			t.Fatalf("unexpected parsed encrypted link: %#v", link)
		}
	})
	t.Run("plus password and multiple hashes", func(t *testing.T) {
		link, err := ParseShareLink("csqtt://connect?v=2&host=203.0.113.10&peer=46000&password=plus+password&hashes=abcdef1234567890%2Cfedcba0987654321")
		if err != nil {
			t.Fatal(err)
		}
		if link.Password != "plus+password" || link.Hashes != "abcdef1234567890\nfedcba0987654321" {
			t.Fatalf("unexpected parsed link: %#v", link)
		}
	})
	t.Run("legacy link", func(t *testing.T) {
		link, err := ParseShareLink("csqtt://legacy-pass@203.0.113.11:46001")
		if err != nil {
			t.Fatal(err)
		}
		if link.Server != "203.0.113.11:46001" || link.Password != "legacy-pass" {
			t.Fatalf("unexpected legacy link: %#v", link)
		}
	})
	t.Run("unsupported token field", func(t *testing.T) {
		if _, err := ParseShareLink("csqtt://connect?v=2&host=203.0.113.10&peer=46000&password=p&hashes=abcdef1234567890&token="); err == nil {
			t.Fatal("empty token field must not be accepted")
		}
	})
}
