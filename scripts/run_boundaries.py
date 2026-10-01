"""Live transport/lifecycle checks against an already running ALP endpoint."""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path

import httpx


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-url", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--agent", default="demo_assistant")
    p.add_argument("--catalog", default="demo-text")
    args = p.parse_args()
    if args.output.exists():
        p.error("Output exists; preserve earlier evidence")
    body = {
        "model": args.model,
        "messages": [{"role": "user", "content": f"Discover the capabilities of {args.agent}."}],
        "alp": {
            "catalog_ref": args.catalog,
            "allowed_operations": ["list_agent_capabilities"],
        },
        "temperature": 0,
        "max_tokens": 256,
        "include_raw": True,
    }
    results = []
    with httpx.Client(
        base_url=args.base_url,
        timeout=180,
        trust_env=False,
        headers={"Authorization": "Bearer " + os.environ["ALP_API_KEY"]},
    ) as client:

        def check(name, data, expected, **kwargs):
            response = client.post("/v1/alp/chat/completions", json=data, **kwargs)
            ok = response.status_code in expected
            results.append({"test": name, "status": response.status_code, "passed": ok})
            return response

        check(
            "unauthenticated", body, {401}, headers={"Authorization": "Bearer incorrect-test-key"}
        )
        invalid = copy.deepcopy(body)
        invalid["alp"]["catalog_ref"] = "unpublished-catalog"
        check("unknown_catalog", invalid, {400, 404})
        invalid = copy.deepcopy(body)
        invalid["alp"]["allowed_operations"] = ["execute_shell"]
        check("unknown_operation", invalid, {400, 422})
        invalid = copy.deepcopy(body)
        invalid["tools"] = [{"type": "function"}]
        check("client_tool_override", invalid, {400, 422})
        invalid = copy.deepcopy(body)
        invalid["model"] = "not-an-installed-model"
        check("unknown_model", invalid, {404, 502})
        response = check("nonstream_completion", body, {200})
        if response.status_code == 200:
            value = response.json()
            results[-1]["passed"] &= (
                value["alp"]["validated"]
                and not value["alp"]["executed"]
                and not value["alp"]["authorized"]
            )
            results[-1]["passed"] &= (
                value["choices"][0]["message"]["agent_calls"][0]["request"]["operation"]
                == "list_agent_capabilities"
            )
        truncated = copy.deepcopy(body)
        truncated.update(max_tokens=1, stream=True)
        response = check("truncated_stream", truncated, {200})
        events = [
            json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
        ]
        results[-1]["passed"] &= bool(events and events[-1]["type"] == "agent_call.failed")
        results[-1]["passed"] &= not any(e["type"] == "agent_call.completed" for e in events)
        results[-1]["terminal_event"] = events[-1] if events else None
        results.append(
            {"test": "health_after_requests", "passed": client.get("/health").status_code == 200}
        )
    report = {
        "mode": "live_endpoint_boundaries",
        "results": results,
        "passed": sum(bool(r["passed"]) for r in results),
        "total": len(results),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return int(any(not r["passed"] for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
