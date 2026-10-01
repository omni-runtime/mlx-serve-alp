from __future__ import annotations

import argparse
import json

from vllm_alp.errors import ALPError
from vllm_alp.protocol import ALPOptions

from .app import MLXConfig, create_app
from .schema import MLXConstraintCompiler


def main(argv=None):
    parser = argparse.ArgumentParser(description="ALP endpoint for native MLX-Serve")
    parser.add_argument("command", choices=["serve", "check"])
    parser.add_argument("--config", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=11237, type=int)
    args = parser.parse_args(argv)
    try:
        config = MLXConfig.from_file(args.config)
        if args.command == "check":
            compiler = MLXConstraintCompiler()
            profiles = {}
            for name, catalog in config.catalogs.items():
                p = compiler.compile(
                    ALPOptions(catalog_ref=name, allowed_operations=catalog.allowed_operations),
                    catalog,
                )
                profiles[name] = {"digest": p.digest, "residual_checks": p.residual_checks}
            print(json.dumps({"catalogs": profiles, "gpu_inference_tested": False}, indent=2))
        else:
            import uvicorn

            uvicorn.run(create_app(config), host=args.host, port=args.port, access_log=False)
    except (ALPError, ValueError) as exc:
        print(json.dumps(exc.envelope() if isinstance(exc, ALPError) else {"error": str(exc)}))
        return 2
    return 0
