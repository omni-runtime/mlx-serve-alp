import json

import pytest
import xgrammar as xgr

from mlx_serve_alp.catalog import Catalog
from mlx_serve_alp.decoding_state import StatefulMatcher, context_for, response_prefix_state
from mlx_serve_alp.protocol import ALPOptions
from mlx_serve_alp.schema import MLXConstraintCompiler

CODEC = 'canonical'


def action(index, operation='list_agent_capabilities'):
    payload = {'instance_id': 'agt_001'} if operation == 'list_agent_capabilities' else {'output': {'format': 'text', 'value': 'ok'}}
    return {'protocol_version': '0.4.0', 'request_id': f'r{index}', 'operation': operation, 'payload': payload}


def wire(profile, actions):
    return json.dumps(actions, separators=(',', ':')) if CODEC == 'canonical' else '\n'.join(profile.contracts.representations(a)['tagged'] for a in actions)


@pytest.fixture(scope='module')
def profile():
    catalog = Catalog(allowed_operations=['list_agent_capabilities', 'agent_final'], agents={'agt_001': {'input_schema': {'type': 'object'}}})
    return MLXConstraintCompiler().compile(ALPOptions(protocol_version='0.4.0', catalog_ref='test', allowed_operations=catalog.allowed_operations), catalog)


@pytest.mark.parametrize('count', [0, 1, 2, 16, 17])
def test_native_grammar_collection_cardinality(profile, count):
    c = xgr.GrammarCompiler(xgr.TokenizerInfo([]))
    matcher = xgr.GrammarMatcher(c.compile_grammar(profile.grammar))
    raw = wire(profile, [action(i) for i in range(count)])
    accepted = matcher.accept_string(raw) and matcher.is_completed()
    assert accepted == (1 <= count <= 16)


def test_native_grammar_final_is_exclusive(profile):
    c = xgr.GrammarCompiler(xgr.TokenizerInfo([]))
    for actions, valid in [([action(0, 'agent_final')], True), ([action(0), action(1, 'agent_final')], False)]:
        m = xgr.GrammarMatcher(c.compile_grammar(profile.grammar))
        assert (m.accept_string(wire(profile, actions)) and m.is_completed()) == valid


def test_prefix_uniqueness_is_per_response(profile):
    assert response_prefix_state(wire(profile, [action(0), action(1)]), CODEC)[1]
    assert not response_prefix_state(wire(profile, [action(0), action(0)]), CODEC)[1]


def test_definition_facts_are_per_member():
    values = []
    for i in range(2):
        values.append({'protocol_version': '0.4.0', 'request_id': f'd{i}', 'operation': 'agent_definition_generate',
                       'payload': {'resource_requirements': [], 'requested_tools': [f'tool_{i}']}})
    from alp_schema_mcp.catalog import ContractCatalog
    contracts = ContractCatalog('0.4.0')
    raw = json.dumps(values) if CODEC == 'canonical' else '\n'.join(contracts.representations(a)['tagged'] for a in values)
    facts, valid = response_prefix_state(raw, CODEC)
    assert valid and facts['actions']['0']['requested_tools'] == ['tool_0']
    assert facts['actions']['1']['requested_tools'] == ['tool_1']


def test_native_specialization_replays_two_independent_definitions():
    catalog = Catalog(allowed_operations=['agent_definition_generate'])
    compiler = MLXConstraintCompiler()
    p = compiler.compile(ALPOptions(protocol_version='0.4.0', catalog_ref='test', allowed_operations=catalog.allowed_operations), catalog)
    values = []
    for i in range(2):
        values.append({'protocol_version': '0.4.0', 'request_id': f'd{i}', 'operation': 'agent_definition_generate',
                       'payload': {'resource_requirements': [], 'requested_tools': [], 'name': f'helper_{i}',
                                   'description': 'A helper', 'instructions': 'Summarize provided materials.', 'output': {'format': 'text'}}})
    raw = wire(p, values)
    native = xgr.GrammarCompiler(xgr.TokenizerInfo([]))
    state = StatefulMatcher(native, p.grammar, [], context_for(p, CODEC))
    valid, matcher, observed = state._probe(raw.encode())
    assert valid and observed['actions']['0'] == observed['actions']['1']
    assert matcher is not None and matcher.is_completed()


@pytest.mark.parametrize('raw,token,needed', [
    (b'{"payload":{"instructions":"text', b'"', False),
    (b'{"payload":{"instructions":"text', b' } ] { ', False),
    (b'{"payload":{"instructions":"text', b'"}', True),
    (b'{"request_id":"r0', b'"', True),
    (b'{"payload":{"name":', b'"helper"', True),
    (b'{"payload":{"slot":"docs', b'"', True),
    (b'{"payload":{"instructions":"text', b'","requested_tools":[', True),
    (b'{"payload":{"requested_tools":["a"', b']', True),
])
def test_probe_guard_keeps_dependency_and_id_boundaries(raw, token, needed):
    from mlx_serve_alp.decoding_state import candidate_changes_structure, prefix_lexical_state
    assert candidate_changes_structure(token, *prefix_lexical_state(raw)) == needed


@pytest.mark.parametrize('version', ['0.3.0', '0.4.0'])
@pytest.mark.parametrize('explicit_schema', [False, True])
@pytest.mark.parametrize('initial_state', [{}, {'active': False}])
def test_initial_state_defaults_are_enforced_before_sampling(version, explicit_schema, initial_state):
    catalog = Catalog(allowed_operations=['agent_definition_generate'])
    p = MLXConstraintCompiler().compile(ALPOptions(protocol_version=version, catalog_ref='test', allowed_operations=catalog.allowed_operations), catalog)
    payload = {'resource_requirements': [], 'requested_tools': []}
    if explicit_schema:
        payload['state_schema'] = {'type': 'object', 'properties': {'active': {'type': 'boolean'}}, 'required': [], 'additionalProperties': False}
    payload.update(name='helper', description='Helper', instructions='Summarize the input.',
                   output={'format': 'text'}, initial_state=initial_state)
    value = {'protocol_version': version, 'request_id': 'state_probe', 'operation': 'agent_definition_generate', 'payload': payload}
    raw = (json.dumps([value] if version == '0.4.0' else value) if CODEC == 'canonical'
           else '<agent_definition_generate>' + json.dumps({k: v for k, v in value.items() if k != 'operation'}, separators=(',', ':')) + '</agent_definition_generate>')
    native = xgr.GrammarCompiler(xgr.TokenizerInfo([]))
    state = StatefulMatcher(native, p.grammar, [], context_for(p, CODEC))
    valid, matcher, _ = state._probe(raw.encode())
    assert (valid and matcher is not None and matcher.is_completed()) == (explicit_schema or initial_state == {})
