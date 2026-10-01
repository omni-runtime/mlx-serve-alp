# Native macOS deployment

Keep one private `settings.json` based on `examples/settings.json`. It contains
absolute executable/model/config paths and references two credential files.
Use file mode 0600 for settings and keys, and 0700 for the secret directory.

Start the two components separately:

```bash
/path/to/venv/bin/python scripts/service.py engine --settings /path/to/settings.json
/path/to/venv/bin/python scripts/service.py adapter --settings /path/to/settings.json
```

For persistence, use two launchd LaunchDaemons with those argument arrays,
RunAtLoad and KeepAlive, a throttle interval, and separate log paths. launchd
should invoke the virtualenv Python by absolute path. The launcher loads key
contents into the child environment and does not place them in command arguments.
The native engine binds loopback only. Expose the authenticated frontend through
your trusted network or TLS gateway.

The trial deployment uses a separate native MLX-Serve process for ALP so existing
H3 and embedding model processes can coexist. Model paths and services are
operator-owned configuration and are not embedded in the package. `local/alp`
is an API alias independent of the upstream model directory name.

The adapter does not register an ALP route in Semantic Router or Envoy. Use its
direct endpoint unless you explicitly configure a gateway route. Existing chat
and embedding routes are independent.

To update, install the pinned dependency versions, run unit and boundary tests,
then restart the adapter. Restart the engine only for engine/model changes.
Keep previous settings and model files for rollback. The private producer suite
requires a separate operator-managed conformance catalog; the public example is
a demonstration only.
