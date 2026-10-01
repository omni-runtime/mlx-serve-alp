# Contributing

Use Python 3.12 or newer. Install the protocol and vllm-alp versions in
`pyproject.toml`, then `pip install -e '.[test]'`.

Run `pytest -q`, `ruff check src tests scripts`, and `python -m build` before
opening a pull request. Include a regression test for protocol/lifecycle changes.
Do not weaken the original protocol validator to improve model scores.

Live tests require an operator-provided engine and `ALP_API_KEY`. Use
`scripts/run_producer.py` with the original protocol test suite; keep raw output,
failed cases and the exact engine/model revisions. Never inject golden answers,
repair model output or report static fixtures as inference evidence.

Keep validation reports and raw evidence locally, outside the source tree. Do not
commit or push them to this repository. Use issues for reproducible bugs and pull
requests for changes; omit secrets, private network addresses and real user
prompts. Contributions are accepted under Apache-2.0.
