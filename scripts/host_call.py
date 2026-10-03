"""Send one reviewed host task with request-bound ALP constraints."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import httpx

from mlx_serve_alp.catalog import PayloadConstraints
from mlx_serve_alp.host_tasks import HOST_TASK, host_task_headers
from mlx_serve_alp.protocol import ALPChatRequest
from mlx_serve_alp.task_context import task_headers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    task_input = parser.add_mutually_exclusive_group(required=True)
    task_input.add_argument("--constraints", type=Path)
    task_input.add_argument("--task", type=Path, help="Typed AgentCallTask or DefinitionTask JSON")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--signing-key-env", default="ALP_HOST_TASK_KEY")
    parser.add_argument("--api-key-env", default="ALP_API_KEY")
    args = parser.parse_args()
    request = ALPChatRequest.model_validate_json(args.request.read_text())
    key = os.environ[args.signing_key_env].encode()
    if args.task:
        task = HOST_TASK.validate_json(args.task.read_text())
        headers = host_task_headers(request, task, key=key)
    else:
        constraints = {
            operation: PayloadConstraints.model_validate(value)
            for operation, value in json.loads(args.constraints.read_text()).items()
        }
        headers = task_headers(request, constraints, key=key)
    headers["Authorization"] = "Bearer " + os.environ[args.api_key_env]
    with httpx.Client(base_url=args.base_url, headers=headers, timeout=600, trust_env=False) as client:
        with client.stream("POST", "/v1/alp/chat/completions", json=request.model_dump()) as response:
            response.raise_for_status()
            for text in response.iter_text():
                print(text, end="", flush=True)


if __name__ == "__main__":
    main()
