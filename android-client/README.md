# Android CSQTTR test build

This isolated build recipe checks out the public `Afteroid/csqttr` tag `v2.5.3`, applies one narrowly scoped worker-negotiation fix, runs Android unit tests, and uploads debug APKs for ARM devices.

## Fix

The original client sends `GETWORKERS` only from the `get_config` worker. The fix allows every admitted worker that receives `TUNCONF` to send the same authenticated `GETWORKERS` request. This addresses a stale worker-count / owner-worker rejection scenario without changing the wire format or server implementation.

The patch script fails closed if the exact original block is not found exactly once.

## Isolation and compatibility

- The build uses a separate debug application ID suffix: `.getworkersfix`.
- It does not overwrite the installed CSQTTR application.
- It does not modify or deploy the server.
- The build is pinned to Android client tag `v2.5.3`.
- APKs are unsigned by a private release key; they are debug-signed for testing.
- This is a diagnostic test build, not a production release.

GitHub Actions workflow: `.github/workflows/android-csqttr-test.yml`.
