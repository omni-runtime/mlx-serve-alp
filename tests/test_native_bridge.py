"""Exercise the real C socket shim against the Python mask worker, without a GPU."""
import ctypes
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest
from vllm_alp.strict_grammar import strict_json_grammar


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    library = tmp_path / ('bridge.dylib' if sys.platform == 'darwin' else 'bridge.so')
    source = Path(__file__).parents[1] / 'native/alp_mask_bridge.c'
    subprocess.run(['cc', '-shared', '-fPIC', '-O2', str(source), '-o', str(library)], check=True)
    socket_root = tempfile.TemporaryDirectory(prefix='alp-mask-', dir='/tmp')
    socket_path = Path(socket_root.name) / 'mask.sock'
    monkeypatch.setenv('MLX_ALP_MASK_SOCKET', str(socket_path))
    process = subprocess.Popen([sys.executable, '-m', 'mlx_serve_alp.mask_worker', '--socket', str(socket_path)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    for _ in range(200):
        if socket_path.exists():
            break
        if process.poll() is not None:
            pytest.fail(process.stderr.read().decode())
        time.sleep(0.05)
    assert socket_path.exists()
    assert os.stat(socket_path).st_mode & 0o777 == 0o600
    lib = ctypes.CDLL(str(library))
    lib.alp_mask_open.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_size_t), ctypes.c_size_t, ctypes.c_uint32]
    lib.alp_mask_open.restype = ctypes.c_void_p
    lib.alp_mask_fill.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_size_t, ctypes.POINTER(ctypes.c_int)]
    lib.alp_mask_accept.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    lib.alp_mask_close.argtypes = [ctypes.c_void_p]
    buffers = [ctypes.create_string_buffer(bytes([i])) for i in range(256)]
    pointers = (ctypes.c_void_p * 257)(*[ctypes.cast(b, ctypes.c_void_p) for b in buffers], None)
    lengths = (ctypes.c_size_t * 257)(*([1] * 256), 0)
    handles = []

    def open_mask(schema):
        grammar = strict_json_grammar(schema).encode()
        handle = lib.alp_mask_open(grammar, len(grammar), pointers, lengths, 257, 256)
        assert handle
        handles.append(handle)
        return handle

    yield lib, process, open_mask
    for handle in handles:
        lib.alp_mask_close(handle)
    if process.poll() is None:
        process.terminate()
    process.wait(timeout=10)
    process.stderr.close()
    socket_root.cleanup()


def test_native_bridge_masks_union_correlations_and_worker_failure(bridge):
    lib, process, open_mask = bridge
    schema = {'anyOf': [
        {'type': 'object', 'properties': {'kind': {'const': 'read'}, 'write': {'const': False}}, 'required': ['kind', 'write'], 'additionalProperties': False},
        {'type': 'object', 'properties': {'kind': {'const': 'write'}, 'write': {'const': True}}, 'required': ['kind', 'write'], 'additionalProperties': False},
    ]}
    handle = open_mask(schema)
    mask, complete = (ctypes.c_ubyte * 257)(), ctypes.c_int()
    for token in b'{"kind":"read","write":':
        assert lib.alp_mask_fill(handle, mask, 257, ctypes.byref(complete)) > 0
        assert mask[token]
        assert lib.alp_mask_accept(handle, token) == 1
    assert lib.alp_mask_fill(handle, mask, 257, ctypes.byref(complete)) > 0
    assert mask[ord('f')] and not mask[ord('t')]
    for token in b'false}':
        assert lib.alp_mask_accept(handle, token) == 1
    assert lib.alp_mask_fill(handle, mask, 257, ctypes.byref(complete)) > 0
    assert complete.value == 1 and mask[256]
    other = open_mask({'type': 'string'})
    process.terminate()
    process.wait(timeout=10)
    assert lib.alp_mask_fill(other, mask, 257, ctypes.byref(complete)) == -1


def test_native_bridge_accepts_nested_schemas_and_rejects_wrong_types(bridge):
    lib, _, open_mask = bridge
    handle = open_mask({'type': 'object', 'properties': {'properties': {
        'type': 'object', 'additionalProperties': {'type': 'object', 'properties': {'type': {'const': 'string'}}, 'required': ['type'], 'additionalProperties': False},
    }}, 'required': ['properties'], 'additionalProperties': False})
    mask, complete = (ctypes.c_ubyte * 257)(), ctypes.c_int()
    for token in b'{"properties":{"script":':
        assert lib.alp_mask_accept(handle, token) == 1
    assert lib.alp_mask_fill(handle, mask, 257, ctypes.byref(complete)) > 0
    assert mask[ord('{')] and not mask[ord('"')]
