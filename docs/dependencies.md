# Private dependency access

This Apache-2.0 adapter requires only one private protocol dependency:
`alp-schema-mcp==0.3.0`, from https://github.com/omni-runtime/alp_schema_mcp.
Obtain access or an authorized wheel from its maintainers. Its canonical schemas,
operation map and validator remain authoritative and are not redistributed here.
The adapter does not require vllm-alp or a separately installed alp-core.

```bash
git clone https://github.com/omni-runtime/alp_schema_mcp.git /path/to/alp_schema_mcp
git -C /path/to/alp_schema_mcp checkout 459257275b29865d3f60facb67283c8bfab1262e
python -m pip install /path/to/alp_schema_mcp
python -m pip install -e '.[test]'
```

Do not embed access tokens in URLs, source or reports. The original producer suite
remains external; pass its authorized path to `run_producer.py --suite`.

Public CI builds the package and runs lint without private dependencies. The
opt-in test job requires `PRIVATE_DEPENDENCY_TESTS=enabled` and a read-only
`PRIVATE_DEPENDENCIES_TOKEN` for alp_schema_mcp. Without those settings it is
skipped, not reported as executed.
