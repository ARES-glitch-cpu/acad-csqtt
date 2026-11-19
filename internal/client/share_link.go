package client

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/sha256"
	"encoding/base64"
	"errors"
	"fmt"
	"net"
	"net/url"
	"regexp"
	"strconv"
	"strings"
)

const shareCipherSeed = "csqtt-chiper-key"
var shareBase64 = regexp.MustCompile(`^[A-Za-z0-9_+/-]+={0,2}$`)
var shareDomain = regexp.MustCompile(`^[A-Za-z0-9.-]+$`)

type ShareLink struct {
	Server   string
	Password string
	Hashes   string
}

// ParseShareLink supports current encrypted CSQTT links, connect?v=2 links,
// and the legacy password@host:port form emitted by older server panels.
func ParseShareLink(value string) (ShareLink, error) {
	text := strings.TrimSpace(value)
	if !strings.HasPrefix(strings.ToLower(text), "csqtt://") {
		return ShareLink{}, errors.New("Ссылка должна начинаться с csqtt://.")
	}
	if strings.Count(strings.ToLower(text), "csqtt://") != 1 {
		return ShareLink{}, errors.New("Вставьте одну полную ссылку CSQTT.")
	}
	rest := strings.TrimSpace(text[len("csqtt://"):])
	if rest == "" || strings.Contains(rest, "#") {
		return ShareLink{}, errors.New("Ссылка CSQTT пустая или повреждена.")
	}
	if strings.HasPrefix(strings.ToLower(rest), "connect?") {
		return parseConnectLink(rest[len("connect?"):])
	}
	if shareBase64.MatchString(rest) && !strings.ContainsAny(rest, "?:@") {
		if link, err := parseSealedLink(rest); err == nil {
			return link, nil
		}
		return ShareLink{}, errors.New("Не удалось проверить ссылку CSQTT. Скопируйте её заново из панели.")
	}
	return parseLegacyLink(rest)
}

func decodeShareBase64(value string) ([]byte, error) {
	value = strings.TrimSpace(value)
	encodings := []*base64.Encoding{
		base64.RawURLEncoding, base64.URLEncoding,
		base64.RawStdEncoding, base64.StdEncoding,
	}
	for _, enc := range encodings {
		if raw, err := enc.DecodeString(value); err == nil {
			return raw, nil
		}
	}
	return nil, errors.New("invalid base64")
}

func parseSealedLink(value string) (ShareLink, error) {
	raw, err := decodeShareBase64(value)
	if err != nil {
		return ShareLink{}, err
	}
	plain := raw
	if !strings.HasPrefix(strings.ToLower(string(raw)), "connect?") {
		if len(raw) < 12+16 {
			return ShareLink{}, errors.New("sealed link too short")
		}
		key := sha256.Sum256([]byte(shareCipherSeed))
		block, err := aes.NewCipher(key[:])
		if err != nil {
			return ShareLink{}, err
		}
		gcm, err := cipher.NewGCM(block)
		if err != nil {
			return ShareLink{}, err
		}
		plain, err = gcm.Open(nil, raw[:gcm.NonceSize()], raw[gcm.NonceSize():], nil)
		if err != nil {
			return ShareLink{}, err
		}
	}
	if !strings.HasPrefix(strings.ToLower(string(plain)), "connect?") {
		return ShareLink{}, errors.New("unexpected link payload")
	}
	return parseConnectLink(string(plain)[len("connect?"):])
}

func decodeShareValue(key, value string) (string, error) {
	decoded, err := url.QueryUnescape(value)
	if err != nil {
		return "", fmt.Errorf("В ссылке повреждён параметр %s.", key)
	}
	return decoded, nil
}

func parseConnectLink(query string) (ShareLink, error) {
	query = strings.ReplaceAll(query, "&amp;", "&")
	if query == "" {
		return ShareLink{}, errors.New("В ссылке CSQTT отсутствуют параметры.")
	}
	known := map[string]bool{"v": true, "host": true, "peer": true, "password": true, "hashes": true, "token": true}
	raw := map[string]string{}
	for _, item := range strings.FieldsFunc(query, func(r rune) bool { return r == '&' || r == ';' }) {
		keyRaw, valueRaw, found := strings.Cut(item, "=")
		if !found {
			continue
		}
		key, err := decodeShareValue("имя параметра", keyRaw)
		if err != nil {
			return ShareLink{}, err
		}
		key = strings.ToLower(key)
		if !known[key] {
			continue
		}
		if _, exists := raw[key]; exists {
			return ShareLink{}, fmt.Errorf("Параметр %s в ссылке повторяется.", key)
		}
		raw[key] = valueRaw
	}
	decoded := map[string]string{}
	for _, key := range []string{"v", "host", "peer", "password", "token"} {
		if value, ok := raw[key]; ok {
			result, err := decodeShareValue(key, value)
			if err != nil {
				return ShareLink{}, err
			}
			decoded[key] = result
		}
	}
	if decoded["v"] != "2" {
		return ShareLink{}, errors.New("Поддерживается только версия ссылки CSQTT v=2.")
	}
	if _, supplied := raw["token"]; supplied {
		return ShareLink{}, errors.New("Ссылка с VK-токеном не поддерживается. Запросите ссылку с хешами звонков.")
	}
	host, port := strings.TrimSpace(decoded["host"]), strings.TrimSpace(decoded["peer"])
	if host == "" || port == "" {
		return ShareLink{}, errors.New("В ссылке CSQTT не указан адрес или порт сервера.")
	}
	portNumber, err := strconv.Atoi(port)
	if err != nil || portNumber < 1 || portNumber > 65535 {
		return ShareLink{}, errors.New("В ссылке CSQTT неверный порт сервера.")
	}
	server, err := formatShareServer(host, portNumber)
	if err != nil {
		return ShareLink{}, err
	}
	password := decoded["password"]
	if _, supplied := raw["password"]; supplied && password == "" {
		return ShareLink{}, errors.New("В ссылке CSQTT указан пустой пароль.")
	}
	if strings.ContainsAny(password, " \t\r\n|") {
		return ShareLink{}, errors.New("Пароль в ссылке CSQTT содержит недопустимые символы.")
	}
	hashes := []string{}
	if rawHashes, ok := raw["hashes"]; ok {
		if rawHashes == "" {
			return ShareLink{}, errors.New("В ссылке CSQTT указан пустой список звонков.")
		}
		for _, part := range strings.Split(rawHashes, "+") {
			decodedHash, err := decodeShareValue("hashes", part)
			if err != nil {
				return ShareLink{}, err
			}
			candidate := normalizeShareHash(decodedHash)
			if len(candidate) < 16 {
				return ShareLink{}, errors.New("Хеш звонка в ссылке CSQTT слишком короткий.")
			}
			found := false
			for _, existing := range hashes {
				if existing == candidate {
					found = true
					break
				}
			}
			if !found {
				hashes = append(hashes, candidate)
			}
		}
		if len(hashes) == 0 || len(hashes) > 6 {
			return ShareLink{}, errors.New("Ссылка CSQTT должна содержать от 1 до 6 хешей звонков.")
		}
	}
	return ShareLink{Server: server, Password: password, Hashes: strings.Join(hashes, "\n")}, nil
}

func normalizeShareHash(value string) string {
	value = strings.Trim(value, "<>\"'")
	if i := strings.Index(value, "/call/join/"); i >= 0 {
		value = value[i+len("/call/join/"):]
	} else if strings.HasPrefix(value, "http://") || strings.HasPrefix(value, "https://") {
		return ""
	}
	if i := strings.IndexAny(value, "?#/"); i >= 0 {
		value = value[:i]
	}
	return strings.TrimSpace(value)
}

func formatShareServer(host string, port int) (string, error) {
	host = strings.TrimSpace(host)
	host = strings.TrimPrefix(strings.TrimSuffix(host, "]"), "[")
	if host == "" || strings.ContainsAny(host, " /\\@?#\r\n\t") {
		return "", errors.New("В ссылке CSQTT неверный адрес сервера.")
	}
	if ip := net.ParseIP(host); ip != nil {
		return net.JoinHostPort(ip.String(), strconv.Itoa(port)), nil
	}
	if strings.Contains(host, ":") || len(host) > 253 || !shareDomain.MatchString(host) ||
		strings.HasPrefix(host, ".") || strings.HasSuffix(host, ".") || strings.Contains(host, "..") {
		return "", errors.New("В ссылке CSQTT неверный адрес сервера.")
	}
	return net.JoinHostPort(host, strconv.Itoa(port)), nil
}

func parseLegacyLink(rest string) (ShareLink, error) {
	rest = strings.TrimSuffix(rest, "/")
	if strings.ContainsAny(rest, "/?#") {
		return ShareLink{}, errors.New("Неизвестный формат ссылки. Используйте csqtt:// из панели CSQTT.")
	}
	at := strings.LastIndex(rest, "@")
	if at < 1 || at == len(rest)-1 {
		return ShareLink{}, errors.New("Неизвестный формат ссылки. Используйте csqtt:// из панели CSQTT.")
	}
	password, err := decodeShareValue("password", rest[:at])
	if err != nil || password == "" || strings.ContainsAny(password, " \t\r\n|") {
		return ShareLink{}, errors.New("В старой ссылке CSQTT отсутствует корректный пароль.")
	}
	endpoint := rest[at+1:]
	host, portText, err := net.SplitHostPort(endpoint)
	if err != nil {
		if strings.HasPrefix(endpoint, "[") && strings.Contains(endpoint, "]") {
			return ShareLink{}, errors.New("В ссылке CSQTT неверно указан адрес IPv6.")
		}
		return ShareLink{}, errors.New("В ссылке CSQTT не указан порт сервера.")
	}
	port, err := strconv.Atoi(portText)
	if err != nil || port < 1 || port > 65535 {
		return ShareLink{}, errors.New("В ссылке CSQTT неверный порт сервера.")
	}
	server, err := formatShareServer(host, port)
	if err != nil {
		return ShareLink{}, err
	}
	return ShareLink{Server: server, Password: password}, nil
}
