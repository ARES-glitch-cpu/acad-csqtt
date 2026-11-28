//go:build !windows

package client

func protectProfileSecrets(p Profile) (Profile, error) { return p, nil }
func unprotectProfileSecrets(p Profile) (Profile, error) { return p, nil }
