"""Launch a pinned MLX engine or ALP adapter from one private deployment file."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("component", choices=["engine", "adapter"])
    parser.add_argument("--settings", type=Path, required=True)
    args = parser.parse_args()
    settings = json.loads(args.settings.read_text())
    for name, path in settings["secret_files"].items():
        value = Path(path).read_text().strip()
        if not value:
            raise ValueError("Empty credential file")
        os.environ[name] = value
    if args.component == "engine":
        binary = settings["engine_binary"]
        command = [
            binary,
            "--model",
            settings["model_directory"],
            "--serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(settings.get("engine_port", 11236)),
            "--ctx-size",
            str(settings.get("context_length", 32768)),
            "--api-key-env",
            "MLX_ALP_ENGINE_KEY",
            "--api-key-strict",
            "--no-pld",
            "--prefix-cache-entries",
            "2",
            "--prefix-cache-mem",
            "256MB",
            "--max-resident-models",
            "1",
            "--no-prevent-sleep",
        ]
    else:
        binary = settings["python"]
        command = [
            binary,
            "-m",
            "mlx_serve_alp",
            "serve",
            "--config",
            settings["config"],
            "--host",
            settings.get("listen", "127.0.0.1"),
            "--port",
            str(settings.get("port", 11237)),
        ]
    os.execv(binary, command)


if __name__ == "__main__":
    main()
