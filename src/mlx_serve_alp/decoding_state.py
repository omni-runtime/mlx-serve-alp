"""Request-local grammar specialization at completed dependency declarations."""
from __future__ import annotations

import copy
import json
from collections import OrderedDict

import xgrammar as xgr

from .catalog import Catalog, stable_json
from .errors import ALPError
from .protocol import ALPOptions

_MISSING = object()


def partial_document(raw):
    """Read only complete scalar values from a syntactically valid JSON prefix.

    Partial containers are returned for name/slot uniqueness checks. Completed
    paths distinguish a finished array from a prefix of that array.
    """
    start = raw.find('{')
    if start < 0:
        return {}, set()
    raw = raw[start:]
    decoder = json.JSONDecoder()
    complete = set()

    def whitespace(index):
        while index < len(raw) and raw[index].isspace():
            index += 1
        return index

    def parse(index, path, depth=0):
        if depth > 64:
            raise ValueError('Prefix nesting limit exceeded')
        index = whitespace(index)
        if index >= len(raw):
            return _MISSING, index, False
        char = raw[index]
        if char not in '[{':
            try:
                value, end = decoder.raw_decode(raw, index)
            except ValueError:
                return _MISSING, len(raw), False
            complete.add(path)
            return value, end, True
        result = {} if char == '{' else []
        closer = '}' if char == '{' else ']'
        index += 1
        while True:
            index = whitespace(index)
            if index >= len(raw):
                return result, index, False
            if raw[index] == closer:
                complete.add(path)
                return result, index + 1, True
            if char == '{':
                try:
                    key, index = decoder.raw_decode(raw, index)
                except ValueError:
                    return result, len(raw), False
                index = whitespace(index)
                if index >= len(raw) or raw[index] != ':':
                    return result, index, False
                value, index, done = parse(index + 1, (*path, key), depth + 1)
                if value is not _MISSING:
                    result[key] = value
            else:
                value, index, done = parse(index, (*path, len(result)), depth + 1)
                if value is not _MISSING:
                    result.append(value)
            if not done:
                return result, index, False
            index = whitespace(index)
            if index >= len(raw):
                return result, index, False
            if raw[index] == closer:
                complete.add(path)
                return result, index + 1, True
            if raw[index] != ',':
                return result, index, False
            index += 1

    value, _, _ = parse(0, ())
    return value if isinstance(value, dict) else {}, complete


def prefix_state(raw):
    doc, complete = partial_document(raw)
    payload = doc.get('payload', {})
    if not isinstance(payload, dict):
        return {}, True
    for field, key in [('resource_requirements', 'slot'), ('exported_capabilities', 'name')]:
        values = [item[key] for item in payload.get(field, []) if isinstance(item, dict) and key in item]
        if len(values) != len(set(values)):
            return {}, False
    observed = {name: payload[name] for name in ('resource_requirements', 'requested_tools', 'state_schema')
                if ('payload', name) in complete}
    if 'exported_capabilities' in payload and 'state_schema' not in observed:
        from .host_contracts import EMPTY_STATE
        observed['state_schema'] = EMPTY_STATE
    return observed, True


def context_for(profile, codec='tagged'):
    return {'catalog': profile.catalog.model_dump(), 'operations': list(profile.operations), 'codec': codec}


class StatefulMatcher:
    """A native matcher plus dependency-aware masks; never edits generated text.

    At a completed resources/tools field, rebuild the grammar for later fields.
    Candidate tokens crossing that boundary are checked against the new grammar
    BEFORE sampling, including tokens which contain multiple JSON delimiters.
    """
    def __init__(self, compiler, grammar, vocab, context=None):
        self.compiler = compiler
        self.vocab = vocab
        self.context = context
        self.base_grammar = grammar
        self.raw = b''
        self.observed = {}
        self._cache = OrderedDict()
        self.matcher = xgr.GrammarMatcher(compiler.compile_grammar(grammar))
        self.active = context is not None and 'agent_definition_generate' in context['operations']
        self.candidates = [i for i, token in enumerate(vocab) if token and any(c in token for c in (b']', b'}', b'"'))]

    def _specialized(self, observed):
        key = stable_json(observed)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        if self.context['codec'] != 'canonical':
            raise ALPError("UNSUPPORTED_CODEC", "MLX requires canonical ALP output.")
        from .schema import MLXConstraintCompiler

        compiler = MLXConstraintCompiler(observed_definition=observed)
        profile = compiler.compile(
            ALPOptions(catalog_ref='decoding-state', allowed_operations=self.context['operations']),
            Catalog.model_validate(self.context['catalog']),
        )
        result = self.compiler.compile_grammar(profile.grammar)
        self._cache[key] = result
        if len(self._cache) > 32:
            self._cache.popitem(last=False)
        return result

    def _probe(self, raw):
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError:
            # XGrammar owns partial UTF-8 validity. No JSON structural byte
            # can be hidden in an unfinished multibyte sequence.
            text = raw.decode('utf-8', errors='ignore')
        observed, valid = prefix_state(text)
        if not valid:
            return False, None, observed
        if observed == self.observed:
            return True, None, observed
        try:
            matcher = xgr.GrammarMatcher(self._specialized(observed))
            return matcher.accept_string(raw), matcher, observed
        except (ValueError, RuntimeError, ALPError):
            return False, None, observed

    def fill_next_token_bitmask(self, bitmask):
        self.matcher.fill_next_token_bitmask(bitmask)
        if not self.active:
            return
        words = bitmask.numpy().reshape(-1)
        for token in self.candidates:
            if (int(words[token // 32]) >> (token % 32)) & 1:
                valid, _, _ = self._probe(self.raw + self.vocab[token])
                if not valid:
                    unsigned = int(words[token // 32]) & 0xffffffff & ~(1 << (token % 32))
                    words[token // 32] = unsigned if unsigned < 0x80000000 else unsigned - 0x100000000

    def accept_token(self, token):
        if not 0 <= token < len(self.vocab):
            return False
        raw = self.raw + self.vocab[token]
        if self.active:
            valid, matcher, observed = self._probe(raw)
            if not valid:
                return False
            if matcher is not None:
                self.matcher = matcher
                self.observed = copy.deepcopy(observed)
                self.raw = raw
                return True
        if not self.matcher.accept_token(token):
            return False
        self.raw = raw
        return True

    def is_completed(self):
        return self.matcher.is_completed()
