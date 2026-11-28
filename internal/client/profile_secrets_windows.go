//go:build windows

package client

import (
	"encoding/base64"
	"fmt"
	"strings"
	"unsafe"

	"golang.org/x/sys/windows"
)

func protectProfileSecret(value string) (string, error) {
	if value == "" || strings.HasPrefix(value, "dpapi:") { return value, nil }
	raw := []byte(value)
	if len(raw) == 0 { return value, nil }
	input := windows.DataBlob{Size:uint32(len(raw)), Data:&raw[0]}
	var output windows.DataBlob
	if err := windows.CryptProtectData(&input, nil, nil, 0, nil, 1, &output); err != nil {
		return "", err
	}
	defer windows.LocalFree(windows.Handle(unsafe.Pointer(output.Data)))
	ciphertext := append([]byte(nil), unsafe.Slice(output.Data, output.Size)...)
	return "dpapi:" + base64.RawStdEncoding.EncodeToString(ciphertext), nil
}

func unprotectProfileSecret(value string) (string, error) {
	if !strings.HasPrefix(value, "dpapi:") { return value, nil }
	ciphertext, err := base64.RawStdEncoding.DecodeString(strings.TrimPrefix(value, "dpapi:"))
	if err != nil { return "", err }
	if len(ciphertext) == 0 { return "", fmt.Errorf("пустое DPAPI-значение") }
	input := windows.DataBlob{Size:uint32(len(ciphertext)), Data:&ciphertext[0]}
	var output windows.DataBlob
	if err := windows.CryptUnprotectData(&input, nil, nil, 0, nil, 1, &output); err != nil {
		return "", err
	}
	defer windows.LocalFree(windows.Handle(unsafe.Pointer(output.Data)))
	return string(append([]byte(nil), unsafe.Slice(output.Data, output.Size)...)), nil
}

func protectProfileSecrets(p Profile) (Profile, error) {
	fields := []*string{
		&p.ShareLink, &p.ClientPassword, &p.Password, &p.Hashes, &p.ProxyPassword, &p.Salt,
		&p.DeployPassword, &p.DeployPrivateKey, &p.DeployKeyPassphrase,
		&p.DeployMainPassword, &p.DeployWebPassword, &p.DeploySecretPath,
	}
	for _, field := range fields {
		value, err := protectProfileSecret(*field)
		if err != nil { return Profile{}, err }
		*field = value
	}
	return p, nil
}

func unprotectProfileSecrets(p Profile) (Profile, error) {
	fields := []*string{
		&p.ShareLink, &p.ClientPassword, &p.Password, &p.Hashes, &p.ProxyPassword, &p.Salt,
		&p.DeployPassword, &p.DeployPrivateKey, &p.DeployKeyPassphrase,
		&p.DeployMainPassword, &p.DeployWebPassword, &p.DeploySecretPath,
	}
	for _, field := range fields {
		value, err := unprotectProfileSecret(*field)
		if err != nil { return Profile{}, err }
		*field = value
	}
	return p, nil
}
