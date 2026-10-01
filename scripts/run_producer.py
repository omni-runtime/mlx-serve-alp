"""Run original producer tasks through a real ALP endpoint; no answer repair or retry."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import time
from pathlib import Path

import httpx
from alp_schema_mcp.catalog import ContractCatalog


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--suite", type=Path, required=True)
    p.add_argument("--base-url", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--codec", choices=["tagged", "canonical"], required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--case", action="append")
    p.add_argument("--max-tokens", type=int, default=4096)
    args = p.parse_args()
    spec = importlib.util.spec_from_file_location(
        "producer", args.suite / "examples/check_producer.py"
    )
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    contracts = ContractCatalog()
    suite = checker.load_suite(contracts)
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output / "report.json").exists():
        p.error("Use a new output directory to preserve previous evidence")
    results = []
    headers = {"Authorization": "Bearer " + os.environ["ALP_API_KEY"]}
    with httpx.Client(
        base_url=args.base_url, headers=headers, timeout=600, trust_env=False
    ) as client:
        for case in suite["positive"]:
            if args.case and case["id"] not in args.case:
                continue
            operation = next(a["equals"] for a in case["assertions"] if a["path"] == "/operation")
            prompt = (
                suite["producer_instructions"] + "\n" + suite["format_instructions"][args.codec]
            )
            prompt += "\nContext:\n" + case["context"] + "\nTask:\n" + case["prompt"]
            body = {
                "model": args.model,
                "messages": [{"role": "user", "content": prompt}],
                "alp": {
                    "allowed_operations": [operation],
                    "choice": {"operation": operation},
                    "catalog_ref": "conformance-json"
                    if case["id"] == "P16"
                    else "conformance-text",
                },
                "stream": True,
                "include_raw": True,
                "temperature": 0.0,
                "seed": 42,
                "max_tokens": args.max_tokens,
            }
            start = time.monotonic()
            raw, events, error = "", [], None
            try:
                with client.stream("POST", "/v1/alp/chat/completions", json=body) as response:
                    status = response.status_code
                    if status != 200:
                        error = response.read().decode()
                    else:
                        for line in response.iter_lines():
                            if not line.startswith("data: "):
                                continue
                            event = json.loads(line[6:])
                            events.append(event)
                            if event["type"] == "agent_call.arguments.delta":
                                raw += event["delta"]
            except httpx.HTTPError as exc:
                status, error = 0, type(exc).__name__
            filename = case["id"] + (
                ".canonical.json" if args.codec == "canonical" else ".tagged.txt"
            )
            (args.output / filename).write_text(raw)
            (args.output / (case["id"] + ".request.json")).write_text(
                json.dumps(body, ensure_ascii=False, indent=2)
            )
            (args.output / (case["id"] + ".events.json")).write_text(
                json.dumps(events, ensure_ascii=False, indent=2)
            )
            checked = checker.check_output(raw, args.codec, contracts, case)
            checked.pop("canonical")
            completed = bool(events and events[-1]["type"] == "agent_call.completed")
            if completed:
                result = events[-1]["response"]
                completed = (
                    result.get("raw") == raw
                    and result["alp"]["validated"] is True
                    and result["alp"]["executed"] is False
                    and result["alp"]["authorized"] is False
                )
            row = {
                "id": case["id"],
                **checked,
                "accepted": completed,
                "http_status": status,
                "passed": checked["passed"] and completed,
                "seconds": round(time.monotonic() - start, 3),
                "transport_error": error,
                "terminal_event": events[-1]["type"] if events else None,
            }
            results.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
            report = {
                "mode": "real_model_output",
                "model": args.model,
                "codec": args.codec,
                "retry_count": 0,
                "max_tokens": args.max_tokens,
                "temperature": 0.0,
                "seed": 42,
                "operation_selection": "explicit per task; no golden answers in prompts",
                "contract_sha256": suite["contract_sha256"],
                "passed": sum(r["passed"] for r in results),
                "total": len(results),
                "failed": sum(not r["passed"] for r in results),
                "results": results,
                "runtime_execution": "not_run",
                "executed": False,
                "authorized": False,
            }
            (args.output / "report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2)
            )
    return int(any(not r["passed"] for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
