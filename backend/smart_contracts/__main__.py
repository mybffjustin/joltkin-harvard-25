# backend/smart_contracts/__main__.py
# SPDX-License-Identifier: Apache-2.0
# © 2025 Joltkin LLC.

import dataclasses
import importlib
import logging
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from shutil import rmtree

from algokit_utils.config import config
from dotenv import load_dotenv

config.configure(debug=True, trace_all=False)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-8s: %(message)s"
)
log = logging.getLogger(__name__)
load_dotenv()

root_path = Path(__file__).parent
artifact_root = root_path / "artifacts"

ALGOKIT_CLI = (
    os.environ.get("ALGOKIT_CLI")
    or shutil.which("algokit")
    or sys.executable + " -m algokit"
)


@dataclasses.dataclass
class SmartContract:
    path: Path
    name: str
    deploy: Callable[[], None] | None = None


def _has_contract_file(d: Path) -> bool:
    return (d / "contract.py").exists()


def _import_contract(folder: Path) -> Path:
    p = folder / "contract.py"
    if not p.exists():
        raise FileNotFoundError(f"No contract.py in {folder}")
    return p


def _import_deploy_if_exists(folder: Path) -> Callable[[], None] | None:
    try:
        mod_name = f"{folder.parent.name}.{folder.name}.deploy_config"
        return importlib.import_module(mod_name).deploy  # type: ignore[attr-defined]
    except Exception:
        return None


contracts: list[SmartContract] = [
    SmartContract(
        path=_import_contract(f), name=f.name, deploy=_import_deploy_if_exists(f)
    )
    for f in root_path.iterdir()
    if f.is_dir() and _has_contract_file(f) and not f.name.startswith("_")
]


def _out_path(out_dir: Path, ext: str) -> Path:
    return out_dir / (
        f"{{contract_name}}_client.{ext}"
        if ext == "py"
        else f"{{contract_name}}Client.{ext}"
    )


def _run(cmd: list[str]) -> None:
    log.debug("Running: %s", " ".join(cmd))
    res = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    if res.returncode:
        raise RuntimeError(res.stdout)


def build(out_dir: Path, contract_path: Path, client_ext: str = "py") -> Path:
    out_dir = out_dir.resolve()
    if out_dir.exists():
        rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    log.info("Compiling %s → %s", contract_path, out_dir)
    _run(
        [
            *ALGOKIT_CLI.split(),
            "--no-color",
            "compile",
            "python",
            str(contract_path.resolve()),
            f"--out-dir={out_dir}",
            "--no-output-arc32",
            "--output-arc56",
            "--output-source-map",
        ]
    )

    specs = list(out_dir.glob("*.arc56.json"))
    if not specs:
        log.warning(
            "No *.arc56.json produced (possibly a LogicSig). Skipping client generation."
        )
        return out_dir

    log.info("Generating typed client(s)")
    _run(
        [
            *ALGOKIT_CLI.split(),
            "generate",
            "client",
            str(out_dir),
            "--output",
            str(_out_path(out_dir, client_ext)),
        ]
    )
    return out_dir


def main(action: str, contract_name: str | None = None) -> None:
    targets = [c for c in contracts if contract_name is None or c.name == contract_name]
    artifact_root.mkdir(parents=True, exist_ok=True)

    if action == "build":
        for c in targets:
            build(artifact_root / c.name, c.path)
    elif action == "deploy":
        for c in targets:
            out = artifact_root / c.name
            if not any(out.glob("*.arc56.json")):
                raise FileNotFoundError(f"No .arc56.json in {out}. Build first.")
            if c.deploy:
                log.info("Deploying %s", c.name)
                c.deploy()
            else:
                log.info("No deploy() found for %s; skipping", c.name)
    elif action == "all":
        for c in targets:
            build(artifact_root / c.name, c.path)
            if c.deploy:
                log.info("Deploying %s", c.name)
                c.deploy()
    else:
        raise SystemExit(f"Unknown action: {action}")


if __name__ == "__main__":
    if len(sys.argv) > 2:
        main(sys.argv[1], sys.argv[2])
    elif len(sys.argv) > 1:
        main(sys.argv[1])
    else:
        main("all")
