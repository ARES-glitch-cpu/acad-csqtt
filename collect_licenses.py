"""Include license texts from the exact local dependency source caches."""
import json
import importlib.metadata
import os
from pathlib import Path
import shutil
import subprocess
import sys

root = Path(__file__).parent
destination = Path(sys.argv[1]) / "licenses"
destination.mkdir(parents=True, exist_ok=True)


def copy_notices(source, name):
    if not source.is_dir():
        return
    target = destination / name
    for path in source.iterdir():
        if path.is_file() and path.name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE", "AUTHORS", "COPYRIGHT")):
            target.mkdir(parents=True, exist_ok=True)
            copied = target / path.name
            shutil.copy2(path, copied)
            copied.chmod(0o644)


copy_notices(Path(sys.base_prefix), "Python")
for item in importlib.metadata.files("pyinstaller") or []:
    if "dist-info/licenses/" in str(item).replace("\\", "/"):
        path = Path(item.locate())
        if path.is_file():
            copy_notices(path.parent, "PyInstaller")
for tcl in (Path(sys.base_prefix) / "tcl").glob("*"):
    copy_notices(tcl, "TclTk-" + tcl.name)
copy_notices(root / "core", "CSQTT")
copy_notices(root / "core/rust-client/vendor/primp", "primp-vendored")
copy_notices(root / "core/rust-client/vendor/netstack-smoltcp", "netstack-smoltcp-vendored")
cargo_home = Path(os.environ.get("CARGO_HOME", str(Path.home() / ".cargo")))
for registry in (cargo_home / "registry/src").glob("*"):
    for crate in registry.iterdir():
        copy_notices(crate, "rust-" + crate.name)
go = shutil.which("go") or r"C:\Go\bin\go.exe"
modules = subprocess.check_output([go, "list", "-m", "-json", "all"], cwd=root / "packet-proxy", text=True)
decoder = json.JSONDecoder()
while modules.strip():
    module, end = decoder.raw_decode(modules.lstrip())
    modules = modules.lstrip()[end:]
    if "Dir" in module:
        copy_notices(Path(module["Dir"]), "go-" + module["Path"].replace("/", "_") + "-" + module.get("Version", "local"))
print("Dependency notices collected.")
