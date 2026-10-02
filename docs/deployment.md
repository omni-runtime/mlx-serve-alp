# Native macOS deployment

## Build the strict MLX text engine

Use a separate checkout of upstream MLX-Serve tag **26.9.6**, not a production
binary or working tree. This bridge is tied to that source version; the preparation
script checks every patch anchor and refuses already-patched/incompatible trees.
It builds a dedicated MLX text engine without the embedded GGUF/ds4 backends.
Keep the stock engine for other workloads.

```bash
git clone --branch 26.9.6 https://github.com/ddalcu/mlx-serve.git /path/to/mlx-source
python scripts/prepare_native.py /path/to/mlx-source
cd /path/to/mlx-source
bash scripts/fetch-zig.sh
# Prepare the MLX C/C++ libraries and embedded frontend dependencies following
# this upstream tag's build instructions, then:
.zig-toolchain/zig build -Doptimize=ReleaseFast -Dversion=26.9.6-alp1
```

The tag's fetch script pins Zig 0.17.0-dev.2248+3f6a02acd. Keep compatible
`libmlx`, `libmlxc`, Metal resources and WebP available at the runtime library
paths embedded in the resulting binary. A relocatable deployment may use
`@executable_path/lib`, adjusted dylib install names and an ad-hoc signature;
verify `otool -L`, `otool -l`, `codesign --verify` and `--version` on the target
machine. Do not copy a binary alone without its native libraries/resources.

The bridge source is in `native/`; engine source, libraries, model weights and
build outputs are not redistributed by this package. Preserve upstream licenses
when distributing your own build. The upstream embedded `opencode2-mlx-serve`
dependency must also be available; the tested source revision was
`e42d118772ef70638a6f019588f4a6768183756d`. Record source revisions and library
versions with your build artifacts.

## Run the three components

Keep one private `settings.json` based on `examples/settings.json`. It contains
absolute executable/model/config paths, `mask_socket`, and credential-file
references. Use file mode 0600 for settings and keys, and 0700 for the private
socket/secret directory. Install matching adapter and shared vllm-alp sources;
version 0.2.0 artifacts predating the strict bridge are not interchangeable.

Start the mask worker before the engine and adapter, in separate processes:

```bash
/path/to/venv/bin/python scripts/service.py mask --settings /path/to/settings.json
/path/to/venv/bin/python scripts/service.py engine --settings /path/to/settings.json
/path/to/venv/bin/python scripts/service.py adapter --settings /path/to/settings.json
```

For persistence, use three launchd LaunchDaemons with those argument arrays,
RunAtLoad, KeepAlive, a throttle interval and separate log paths. A stale socket
requires checking that the old worker is stopped before removing it. Use absolute
paths. Keys enter child environments, never command arguments. Bind the native
engine to loopback; expose only the authenticated adapter through the trusted
network or TLS gateway. The adapter requires `alp_strict_grammar_v1` in engine
model capabilities and rejects a stock or metadata-less engine before inference.

The model path, capacity and process residency are operator-owned configuration.
`local/alp` is an API alias independent of the model-directory name. Health alone
does not establish simultaneous inference capacity. The adapter does not register
routes in Semantic Router or Envoy; chat, video and embedding routes remain
independently configured.

To update, install matching packages, run unit/boundary tests and restart all
components affected by the change. Keep previous binaries/settings for rollback.
Use the separately supplied producer suite for real model tests and retain reports
locally. See [decoding guarantees and limits](strict-decoding.md).
