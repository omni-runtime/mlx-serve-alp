"""Request-local grammar specialization at completed dependency declarations."""
from __future__ import annotations

import copy
import json
import re
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


def prefix_state(raw, catalog_tools=None):
    doc, complete = partial_document(raw)
    payload = doc.get('payload', {})
    if not isinstance(payload, dict):
        return {}, True
    for field, key in [('resource_requirements', 'slot'), ('exported_capabilities', 'name')]:
        values = [item[key] for item in payload.get(field, []) if isinstance(item, dict) and key in item]
        if len(values) != len(set(values)):
            return {}, False
    resources = payload.get('resource_requirements', [])
    resources = [r for r in resources if isinstance(r, dict)]
    by_slot = {r['slot']: r for r in resources if 'slot' in r}
    knowledge = {'knowledge.search', 'knowledge.read'}
    requested = payload.get('requested_tools', [])
    if len(requested) != len(set(requested)):
        return {}, False
    if ('payload', 'requested_tools') in complete and ('payload', 'resource_requirements') in complete:
        required = set(knowledge) if any(r.get('kind') == 'knowledge' for r in resources) else set()
        for r in resources:
            if r.get('kind') == 'mcp':
                required.update(r.get('tool_allowlist', []))
        if not required.issubset(requested):
            return {}, False
    for i, cap in enumerate(payload.get('exported_capabilities', [])):
        if not isinstance(cap, dict) or not isinstance(cap.get('execution'), dict):
            continue
        run = cap['execution']
        subset = run.get('resource_subset', {})
        slots = subset.get('slots', []) if isinstance(subset, dict) else []
        tools = run.get('tool_subset', [])
        if len(slots) != len(set(slots)) or len(tools) != len(set(tools)):
            return {}, False
        if ('payload', 'resource_requirements') in complete and not set(slots).issubset(by_slot):
            return {}, False
        path = ('payload', 'exported_capabilities', i, 'execution')
        # Generation places resource_subset before tool_subset. Once tools
        # start, an omitted subset means the protocol's empty selection.
        selected_complete = path + ('resource_subset', 'slots') in complete or 'tool_subset' in run and 'resource_subset' not in run
        if selected_complete:
            selected = [by_slot[s] for s in slots if s in by_slot]
            has_knowledge = any(r.get('kind') == 'knowledge' for r in selected)
            mcp_owners = {t: {r['slot'] for r in resources if r.get('kind') == 'mcp' and t in r.get('tool_allowlist', [])}
                          for r in resources if r.get('kind') == 'mcp' for t in r.get('tool_allowlist', [])}
            if any(t in knowledge and not has_knowledge or t in mcp_owners and not mcp_owners[t].intersection(slots) for t in tools):
                return {}, False
            if path + ('tool_subset',) in complete and has_knowledge and not knowledge.issubset(tools):
                return {}, False
        if path + ('tool_subset',) in complete and catalog_tools is not None and 'external_effect' in cap:
            levels = {'none': 0, 'read': 1, 'write': 2}
            actual = max((levels[catalog_tools[t].get('external_effect') or 'read'] for t in tools if t in catalog_tools), default=0)
            if levels.get(cap['external_effect']) != actual:
                return {}, False
    observed = {name: payload[name] for name in ('resource_requirements', 'requested_tools', 'state_schema')
                if ('payload', name) in complete}
    selections = {str(i): cap['execution']['resource_subset']['slots']
                  for i, cap in enumerate(payload.get('exported_capabilities', []))
                  if ('payload', 'exported_capabilities', i, 'execution', 'resource_subset', 'slots') in complete}
    if selections:
        observed['capability_resources'] = selections
    # Both fields follow state_schema in the sampling grammar. Its omission
    # means the protocol's closed empty state, even when capabilities are absent.
    if ('exported_capabilities' in payload or 'initial_state' in payload) and 'state_schema' not in observed:
        from .host_contracts import EMPTY_STATE
        observed['state_schema'] = EMPTY_STATE
    return observed, True



def response_prefix_state(raw, codec, catalog_tools=None, completed_cache=None):
    """Inspect each complete/partial member without treating tags in strings as frames."""
    decoder = json.JSONDecoder()
    index, action, ids, observed = 0, 0, set(), {}
    raw = raw.lstrip()
    if codec == 'canonical':
        if not raw.startswith('['):
            return {}, True
        index = 1
    while index < len(raw) and action < 16:
        while index < len(raw) and (raw[index].isspace() or codec == 'canonical' and raw[index] == ','):
            index += 1
        start = index
        cached = (completed_cache or {}).get(action)
        if cached and cached[0] == start and raw.startswith(cached[1], start):
            _, _, index, request_id, facts = cached
            if request_id in ids:
                return {}, False
            ids.add(request_id)
            if facts:
                observed[str(action)] = facts
            action += 1
            continue
        facts = {}
        operation = None
        if codec == 'tagged':
            if index >= len(raw) or raw[index] != '<':
                break
            end = raw.find('>', index)
            if end < 0:
                break
            operation = raw[index + 1:end]
            index = end + 1
        part = raw[index:].lstrip()
        index += len(raw[index:]) - len(part)
        if not part.startswith('{'):
            break
        doc, complete = partial_document(part)
        request_id = doc.get('request_id')
        if ('request_id',) in complete:
            if request_id in ids:
                return {}, False
            ids.add(request_id)
        operation = operation or doc.get('operation')
        if operation == 'agent_definition_generate':
            facts, valid = prefix_state(part, catalog_tools)
            if not valid:
                return {}, False
            if facts:
                observed[str(action)] = facts
        try:
            _, end = decoder.raw_decode(raw, index)
        except ValueError:
            break
        index = end
        if codec == 'tagged':
            # The decoder found the actual JSON end, including escaped tag data.
            close = '</' + operation + '>'
            while index < len(raw) and raw[index].isspace():
                index += 1
            if not raw.startswith(close, index):
                break
            index += len(close)
        if completed_cache is not None:
            completed_cache[action] = (start, raw[start:index], index, request_id, facts)
        action += 1
    return {'actions': observed} if observed else {}, True


def context_for(profile, codec='tagged'):
    return {'catalog': profile.catalog.model_dump(), 'operations': list(profile.operations), 'codec': codec, 'protocol_version': profile.protocol_version}



def candidate_changes_structure(token, in_string, escaped, watch_identifier):
    """Conservative lexical guard before reparsing the entire JSON prefix.

    Dependency facts only change when containers start/end or a name/slot/ID
    scalar completes. A colon can start such a scalar within this same token.
    Braces and escaped quotes inside ordinary task text have no structural effect.
    """
    for char in token:
        if in_string:
            if escaped:
                escaped = False
            elif char == 92:
                escaped = True
            elif char == 34:
                in_string = False
                if watch_identifier:
                    return True
        elif char in (58, 91, 93, 123, 125):
            return True
        elif char == 34:
            in_string = True
    return False


def prefix_lexical_state(raw):
    in_string = escaped = False
    for char in raw:
        if in_string:
            if escaped:
                escaped = False
            elif char == 92:
                escaped = True
            elif char == 34:
                in_string = False
        elif char == 34:
            in_string = True
    watch = re.search(rb'"(?:request_id|name|slot)"\s*:\s*(?:"(?:[^"\\]|\\.)*)?$', raw) is not None
    return in_string, escaped, watch or b'"slots"' in raw or b'"tool_subset"' in raw or b'"requested_tools"' in raw


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
        self._prefix_cache = {}
        self.matcher = xgr.GrammarMatcher(compiler.compile_grammar(grammar))
        self.active = context is not None and (context.get('protocol_version') == '0.4.0' or 'agent_definition_generate' in context['operations'])
        self.candidates = [i for i, token in enumerate(vocab) if token and any(c in token for c in (b':', b'[', b']', b'{', b'}', b'"'))]

    def _specialized(self, observed):
        key = stable_json(observed)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        if self.context['codec'] != 'canonical':
            raise ALPError("UNSUPPORTED_CODEC", "MLX requires canonical ALP output.")
        from alp_schema_mcp.catalog import ContractCatalog

        from .schema import MLXConstraintCompiler
        version = self.context.get('protocol_version', '0.3.0')
        compiler = MLXConstraintCompiler(contracts=ContractCatalog(version), observed_definition=observed)
        profile = compiler.compile(
            ALPOptions(protocol_version=version, catalog_ref='decoding-state', allowed_operations=self.context['operations']),
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
        observed, valid = (response_prefix_state(text, self.context['codec'], self.context['catalog'].get('tools', {}), self._prefix_cache)
                           if self.context.get('protocol_version') == '0.4.0' else prefix_state(text, self.context['catalog'].get('tools', {})))
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
        lexical = prefix_lexical_state(self.raw)
        words = bitmask.numpy().reshape(-1)
        for token in self.candidates:
            if ((int(words[token // 32]) >> (token % 32)) & 1
                    and candidate_changes_structure(self.vocab[token], *lexical)):
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
