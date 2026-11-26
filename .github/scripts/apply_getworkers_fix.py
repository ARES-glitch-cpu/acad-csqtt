#!/usr/bin/env python3
"""Apply the narrowly scoped CSQTT worker-negotiation fix to the pinned Android source."""
from __future__ import annotations

import pathlib
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply_getworkers_fix.py PATH_TO_SESSION_RS")

path = pathlib.Path(sys.argv[1])
if not path.is_file():
    raise SystemExit(f"Rust session source not found: {path}")

source = path.read_text(encoding="utf-8")
old = """                            if config.get_config {
                                let req = crate::protocol::workers_request(
                                    &config.password,
                                    scale.configured,
                                );
                                let _ = writer.send_bytes(req.as_bytes()).await;
                            }
"""
new = """                            // get_config selects who delivers TUNCONF to the GUI,
                            // not who may negotiate the worker count. Any admitted
                            // worker must be able to request the configured count.
                            let req = crate::protocol::workers_request(
                                &config.password,
                                scale.configured,
                            );
                            writer
                                .send_bytes(req.as_bytes())
                                .await
                                .context("отправка GETWORKERS")?;
"""
count = source.count(old)
if count != 1:
    raise SystemExit(
        "Refusing to patch: expected exactly one original GETWORKERS block, "
        f"found {count}. The pinned source may have changed."
    )

patched = source.replace(old, new, 1)
path.write_text(patched, encoding="utf-8", newline="\n")

if old in path.read_text(encoding="utf-8"):
    raise SystemExit("Patch verification failed: old GETWORKERS block remains.")
if "context(\"отправка GETWORKERS\")?" not in path.read_text(encoding="utf-8"):
    raise SystemExit("Patch verification failed: new GETWORKERS block not found.")

print("GETWORKERS fix applied and verified.")
