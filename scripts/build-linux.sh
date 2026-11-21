#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VERSION="$(tr -d '[:space:]' < VERSION)"
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "VERSION must be semantic version x.y.z" >&2
  exit 1
fi
if [[ "${GITHUB_REF_TYPE:-}" == "tag" && "${GITHUB_REF_NAME:-}" != "v${VERSION}" ]]; then
  echo "Tag ${GITHUB_REF_NAME} does not match VERSION ${VERSION}" >&2
  exit 1
fi

command -v cargo >/dev/null || { echo "Rust toolchain is required" >&2; exit 1; }
command -v go >/dev/null || { echo "Go toolchain is required" >&2; exit 1; }
command -v node >/dev/null || { echo "Node.js is required" >&2; exit 1; }
command -v npm >/dev/null || { echo "npm is required" >&2; exit 1; }
command -v xvfb-run >/dev/null || { echo "xvfb-run is required for GUI smoke test" >&2; exit 1; }

go mod tidy
go test ./internal/...
go -C packet-proxy test ./...

cargo build --release --locked --manifest-path core/rust-client/Cargo.toml
mkdir -p bin .tools/bin build
install -m 0755 core/rust-client/target/release/client bin/csqtt-core

(
  cd packet-proxy
  CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags '-s -w' -o ../bin/packet-proxy .
)
chmod 0755 bin/csqtt-core bin/packet-proxy
cp assets/icons/CS_logo.png build/appicon.png

if [[ ! -x .tools/bin/wails ]]; then
  GOBIN="$ROOT_DIR/.tools/bin" go install github.com/wailsapp/wails/v2/cmd/wails@v2.16.0
fi

pushd frontend >/dev/null
npm ci --no-audit --no-fund
npm run build
popd >/dev/null

.tools/bin/wails build -s -skipbindings -trimpath -platform linux/amd64 -tags webkit2_41

PACKAGE="$ROOT_DIR/dist/CSQTT"
rm -rf "$PACKAGE"
mkdir -p "$PACKAGE/bin" "$PACKAGE/_internal"
APP_BIN="$ROOT_DIR/build/bin/CSQTT"
[[ -x "$APP_BIN" ]] || { echo "Wails output not found: $APP_BIN" >&2; find build -maxdepth 3 -type f -print; exit 1; }

install -m 0755 "$APP_BIN" "$PACKAGE/CSQTT"
install -m 0755 bin/csqtt-core "$PACKAGE/bin/csqtt-core"
install -m 0755 bin/packet-proxy "$PACKAGE/bin/packet-proxy"
install -m 0644 VERSION "$PACKAGE/_internal/VERSION"
cp README.md LICENSE NOTICE.md "$PACKAGE/"
cp -a assets "$PACKAGE/assets"

go run scripts/package.go notices "$PACKAGE"

if ldd "$PACKAGE/CSQTT" | grep -q "not found"; then
  echo "Linux binary has unresolved runtime libraries:" >&2
  ldd "$PACKAGE/CSQTT" | grep "not found" >&2 || true
  exit 1
fi

xvfb-run -a env GDK_BACKEND=x11 "$PACKAGE/CSQTT" --smoke

find "$PACKAGE" -type f ! -name SHA256SUMS.txt -print0 | sort -z | while IFS= read -r -d "" file; do
  relative="${file#"$PACKAGE"/}"
  (cd "$PACKAGE" && sha256sum "$relative")
done > "$PACKAGE/SHA256SUMS.txt"
(cd "$PACKAGE" && sha256sum -c SHA256SUMS.txt)

ARCHIVE="$ROOT_DIR/CSQTT-v${VERSION}-Linux-x86_64.tar.gz"
tar --sort=name --mtime="UTC 2020-01-01" --owner=0 --group=0 --numeric-owner -czf "$ARCHIVE" -C "$ROOT_DIR/dist" CSQTT
tar -tzf "$ARCHIVE" >/dev/null
(cd "$ROOT_DIR" && sha256sum "$(basename "$ARCHIVE")") > "${ARCHIVE}.sha256"
echo "Built $ARCHIVE"
