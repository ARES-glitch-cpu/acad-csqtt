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
python -c "import tkinter" || { echo "Python Tk support is required; install Tcl/Tk development packages" >&2; exit 1; }

cargo build --release --locked --manifest-path core/rust-client/Cargo.toml
mkdir -p bin
install -m 0755 core/rust-client/target/release/client bin/csqtt-core

(
  cd packet-proxy
  CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags '-s -w' -o ../bin/packet-proxy .
)
chmod 0755 bin/csqtt-core bin/packet-proxy

python -m PyInstaller --noconfirm --clean --onedir --windowed --hidden-import=PIL._tkinter_finder --collect-submodules=pystray --collect-submodules=Xlib --name CSQTT main.py
PACKAGE="$ROOT_DIR/dist/CSQTT"
mkdir -p "$PACKAGE"
cp -a bin "$PACKAGE/"
cp -a README.md LICENSE NOTICE.md VERSION assets "$PACKAGE/"
python scripts/collect_licenses.py "$PACKAGE"

if ! command -v xvfb-run >/dev/null; then
  echo "xvfb-run is required for the Linux GUI smoke test" >&2
  exit 1
fi
xvfb-run -a "$PACKAGE/CSQTT" --smoke

find "$PACKAGE" -type f ! -name SHA256SUMS.txt -print0 | sort -z | while IFS= read -r -d "" file; do
  relative="${file#"$PACKAGE"/}"
  (cd "$PACKAGE" && sha256sum "$relative")
done > "$PACKAGE/SHA256SUMS.txt"

ARCHIVE="$ROOT_DIR/CSQTT-v${VERSION}-Linux-x86_64.tar.gz"
tar --sort=name --mtime="UTC 2020-01-01" --owner=0 --group=0 --numeric-owner -czf "$ARCHIVE" -C "$ROOT_DIR/dist" CSQTT
tar -tzf "$ARCHIVE" >/dev/null
(cd "$PACKAGE" && sha256sum -c SHA256SUMS.txt)
sha256sum "$ARCHIVE" > "${ARCHIVE}.sha256"
echo "Built $ARCHIVE"
