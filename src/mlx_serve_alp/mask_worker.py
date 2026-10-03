"""Local XGrammar token-mask service for the native MLX-Serve bridge.

Only a mode-0600 Unix socket is exposed. Every connection owns its matcher;
transport/compilation/matching errors close the connection (never unmask).
"""
from __future__ import annotations

import argparse
import json
import os
import socketserver
import struct
import threading
from collections import OrderedDict
from pathlib import Path

import numpy as np
import xgrammar as xgr

from mlx_serve_alp.decoding_state import StatefulMatcher

MAX_VOCAB = 300_000
MAX_GRAMMAR = 8 * 1024 * 1024
MAX_TOKEN_BYTES = 1024 * 1024
_CACHE = OrderedDict()
_LOCK = threading.Lock()


def read_exact(stream, size):
    value = stream.read(size)
    if len(value) != size:
        raise EOFError('Incomplete mask protocol frame')
    return value


def read_u32(stream):
    return struct.unpack('!I', read_exact(stream, 4))[0]


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(60)
        try:
            if read_exact(self.rfile, 4) != b'ALP1':
                raise ValueError('Invalid mask protocol')
            length = read_u32(self.rfile)
            if length > MAX_GRAMMAR:
                raise ValueError('Grammar too large')
            grammar = read_exact(self.rfile, length).decode()
            context = None
            if grammar.startswith('{'):
                envelope = json.loads(grammar)
                grammar, context = envelope['grammar'], envelope['context']
            size, eos = read_u32(self.rfile), read_u32(self.rfile)
            if not 1 <= size <= MAX_VOCAB or eos >= size:
                raise ValueError('Invalid vocabulary')
            vocab, excluded, total = [], [], 0
            for i in range(size):
                length = read_u32(self.rfile)
                if length == 0xffffffff:
                    vocab.append(b'')
                    excluded.append(i)
                    continue
                total += length
                if length > MAX_TOKEN_BYTES or total > 64 * 1024 * 1024:
                    raise ValueError('Vocabulary too large')
                vocab.append(read_exact(self.rfile, length))
                if not length:
                    excluded.append(i)
            key = (tuple(vocab), eos)
            with _LOCK:
                compiler = _CACHE.get(key)
                if compiler is None:
                    info = xgr.TokenizerInfo(vocab, vocab_type=xgr.VocabType.RAW, vocab_size=size, stop_token_ids=[eos])
                    compiler = xgr.GrammarCompiler(info, max_threads=1, cache_limit_bytes=256 * 1024 * 1024)
                    _CACHE[key] = compiler
                    if len(_CACHE) > 2:
                        _CACHE.popitem(last=False)
                else:
                    _CACHE.move_to_end(key)
            matcher = StatefulMatcher(compiler, grammar, vocab, context)
            bitmask = xgr.allocate_token_bitmask(1, size)
            self.wfile.write(b'\x01')
            self.wfile.flush()
            while command := self.rfile.read(1):
                if command == b'M':
                    matcher.fill_next_token_bitmask(bitmask)
                    bits = np.unpackbits(bitmask.numpy().view(np.uint8), bitorder='little')[:size]
                    bits[excluded] = 0
                    complete = matcher.is_completed()
                    bits[eos] = int(complete)
                    self.wfile.write(bytes([int(complete)]) + struct.pack('!I', size) + bits.tobytes())
                elif command == b'A':
                    token = read_u32(self.rfile)
                    if token >= size or not matcher.accept_token(token):
                        raise ValueError('Rejected sampled token')
                    self.wfile.write(b'\x01')
                else:
                    raise ValueError('Invalid mask command')
                self.wfile.flush()
        except (EOFError, OSError, ValueError, RuntimeError):
            # No payloads or vocabulary contents in logs; EOF is the fail-closed
            # wire response and the native engine terminates this generation.
            return


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--socket', type=Path, required=True)
    args = parser.parse_args()
    if args.socket.exists():
        raise SystemExit('Socket already exists; check its owner before removing it')
    args.socket.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    old_mask = os.umask(0o177)
    try:
        server = Server(str(args.socket), Handler)
    finally:
        os.umask(old_mask)
    try:
        with server:
            server.serve_forever()
    finally:
        args.socket.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
