"""The MLX adapter must work without installing another ALP plugin."""
import subprocess
import sys
from pathlib import Path


def test_compile_and_endpoint_without_other_alp_plugins():
    script = '''
import importlib.abc, os, sys
class LocalOnly(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'alp_core', 'vllm_alp', 'vllm', 'vllm_omni', 'semantic_router_alp'}:
            raise AssertionError('Unexpected MLX dependency: ' + fullname)
sys.meta_path.insert(0, LocalOnly())
from mlx_serve_alp.app import MLXConfig, create_app
from mlx_serve_alp.protocol import ALPOptions
from mlx_serve_alp.schema import MLXConstraintCompiler
from mlx_serve_alp.mask_worker import StatefulMatcher
config = MLXConfig.from_file(sys.argv[1])
compiler = MLXConstraintCompiler()
for name, catalog in config.catalogs.items():
    for operation in catalog.allowed_operations:
        profile = compiler.compile(ALPOptions(catalog_ref=name, allowed_operations=[operation]), catalog)
        assert profile.grammar and profile.body_schemas
os.environ[config.api_key_env] = 'test-frontend'
os.environ[config.upstream_api_key_env] = 'test-engine'
app = create_app(config)
assert any(getattr(route, 'path', None) == '/v1/alp/chat/completions' for route in app.routes)
'''
    subprocess.run([sys.executable, "-c", script,
                    str(Path(__file__).parents[1] / "examples/config.json")], check=True)
