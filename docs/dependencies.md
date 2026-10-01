# Private dependency access

This adapter is Apache-2.0 open source. It depends on two **private** repositories:

| Package | Required version | Repository |
|---|---|---|
| alp-schema-mcp | 0.3.0 | https://github.com/omni-runtime/alp_schema_mcp |
| vllm-alp | 0.1.1 | https://github.com/omni-runtime/vllm-alp |

Obtain access or authorized wheels from their maintainers. Their code and
contracts are not included in this repository and are not covered by this
adapter's license. We do not change their visibility or claim to license them.

After authentication with your own Git credential helper:

```bash
git clone https://github.com/omni-runtime/alp_schema_mcp.git /path/to/alp_schema_mcp
git clone https://github.com/omni-runtime/vllm-alp.git /path/to/vllm-alp
python -m pip install /path/to/alp_schema_mcp /path/to/vllm-alp
python -m pip install -e '.[test]'
```

For reproducible installs, use these pinned source revisions (also used by the
opt-in CI job):

- `alp_schema_mcp`: `c2ced6e565fe430ef7d3ccb9d9fe61dc4e45c1c8`
- `vllm-alp`: `cf65664da05176b0b6775a718edbc9bf5384073b`

Do not embed access tokens in clone URLs, requirements files, logs or reports. The original producer
suite remains in the authorized protocol checkout; `run_producer.py --suite`
loads it from there. Configure its test catalogs privately; `examples/config.json`
is an independent demonstration catalog and does not implement the private suite.

Public CI builds source and wheel artifacts and runs lint without installing
private dependencies. An opt-in test job requires repository variable
`PRIVATE_DEPENDENCY_TESTS=enabled` and a maintainer-provided read-only
`PRIVATE_DEPENDENCIES_TOKEN` with access to both dependencies. Without that setup,
the private-dependency test job is **skipped**, not reported as executed.
