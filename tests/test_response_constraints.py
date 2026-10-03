import copy
import json

import pytest
from starlette.datastructures import Headers

from mlx_serve_alp.catalog import Catalog, PayloadConstraints, ResponseConstraints, ServerConfig
from mlx_serve_alp.errors import ALPError
from mlx_serve_alp.parser import ALPParser
from mlx_serve_alp.protocol import ALPChatRequest, ALPOptions
from mlx_serve_alp.schema import MLXConstraintCompiler as Compiler
from mlx_serve_alp.task_context import bind_task_constraints, task_headers


def make(count=2):
    members = [{"operation": "agent_call", "payload": {
        "fixed_values": {"/instance_id": f"agent_{i}", "/input/task": f"Original {i}。", "/session_mode": "isolated"},
        "forbidden_fields": ["/expected_state_version"]}} for i in range(count)]
    cat = Catalog(allowed_operations=["agent_call"],
                  agents={f"agent_{i}": {"input_schema": {"type": "object"}} for i in range(count)},
                  response_constraints=ResponseConstraints(members=members))
    options = ALPOptions(protocol_version="0.4.0", allowed_operations=["agent_call"], catalog_ref="test")
    profile = Compiler().compile(options, cat)
    actions = [{"protocol_version": "0.4.0", "request_id": f"r{i}", "operation": "agent_call",
                "payload": {"instance_id": f"agent_{i}", "input": {"task": f"Original {i}。"}, "session_mode": "isolated"}}
               for i in range(count)]
    return cat, profile, actions


def parse(profile, actions):
    p = ALPParser(profile, profile.contracts, codec="canonical")
    p.feed(json.dumps(actions))
    return p.finish("stop")


@pytest.mark.parametrize("count", [1, 2, 16])
def test_ordered_host_response_cannot_drop_repeat_or_reorder_members(count):
    _, p, actions = make(count)
    assert parse(p, actions) == actions
    for bad in [actions[:-1], actions + [copy.deepcopy(actions[0])]]:
        with pytest.raises(ALPError):
            parse(p, bad)
    if count > 1:
        with pytest.raises(ALPError):
            parse(p, actions[::-1])
    bad = copy.deepcopy(actions)
    bad[0]["payload"]["expected_state_version"] = 1
    with pytest.raises(ALPError):
        parse(p, bad)


def test_host_v2_signature_cannot_widen_catalog_bounds_or_change_body(monkeypatch):
    monkeypatch.setenv("REVIEW_TASK_KEY", "k" * 32)
    cat, _, _ = make()
    config = ServerConfig(catalogs={"test": cat}, task_signing_key_env="REVIEW_TASK_KEY")
    req = ALPChatRequest(model="local/text", messages=[{"role": "user", "content": "two calls"}],
                         alp={"protocol_version": "0.4.0", "allowed_operations": ["agent_call"], "catalog_ref": "test"})
    header = task_headers(req, {}, key=b"k" * 32, response=cat.response_constraints)
    raw = type("Raw", (), {"headers": Headers(header)})()
    assert bind_task_constraints(req, cat, config, raw).response_constraints == cat.response_constraints
    changed = req.model_copy(update={"max_tokens": req.max_tokens + 1})
    with pytest.raises(ALPError):
        bind_task_constraints(changed, cat, config, raw)
    header = task_headers(req, {}, key=b"k" * 32, response=ResponseConstraints(max_calls=3))
    with pytest.raises(ALPError):
        bind_task_constraints(req, cat, config, type("Raw", (), {"headers": Headers(header)})())


@pytest.mark.parametrize("profiles", [[], ["sandbox.reviewed"]])
def test_no_environment_request_is_valid_with_any_visible_environment_domain(profiles):
    cat = Catalog(allowed_operations=["agent_definition_generate"], environment_profiles=profiles)
    p = Compiler().compile(ALPOptions(protocol_version="0.4.0", catalog_ref="test", allowed_operations=cat.allowed_operations), cat)
    a = {"protocol_version": "0.4.0", "request_id": "r0", "operation": "agent_definition_generate",
         "payload": {"name": "helper_agent", "description": "Help", "instructions": "Answer"}}
    assert parse(p, [a]) == [a]
    a["payload"]["environment_profile_ref"] = "unknown"
    with pytest.raises(ALPError):
        parse(p, [a])


@pytest.mark.parametrize("count", [9, 16])
def test_large_resource_domain_is_supported_without_subset_enumeration(count):
    resources = [{"kind": "asset", "slot": f"asset_{i}", "description": "Asset", "required": False,
                  "profile_ref": f"asset.profile_{i}", "version": "1.0.0", "access_mode": "read"} for i in range(count)]
    cat = Catalog(allowed_operations=["agent_definition_generate"], payload_constraints={"agent_definition_generate":
        PayloadConstraints(fixed_values={"/resource_requirements": resources})})
    p = Compiler().compile(ALPOptions(protocol_version="0.4.0", catalog_ref="test", allowed_operations=cat.allowed_operations), cat)
    a = {"protocol_version": "0.4.0", "request_id": "r0", "operation": "agent_definition_generate",
         "payload": {"name": "helper_agent", "description": "Help", "instructions": "Answer",
                     "resource_requirements": resources}}
    assert parse(p, [a]) == [a]


def test_response_plan_and_presence_conflicts_fail_before_generation():
    with pytest.raises(ValueError):
        PayloadConstraints(fixed_values={"/input/task": "x"}, forbidden_fields=["/input"])
    with pytest.raises(ValueError):
        ResponseConstraints(members=[{"operation": "agent_final"}, {"operation": "agent_call"}])
    cat, _, _ = make()
    with pytest.raises(ALPError):
        Compiler().compile(ALPOptions(catalog_ref="test", allowed_operations=cat.allowed_operations), cat)

@pytest.mark.parametrize('count', [1, 2, 16])
def test_native_mask_allows_eos_only_after_exact_host_count(count):
    import xgrammar as xgr

    from mlx_serve_alp.decoding_state import StatefulMatcher, context_for
    _, p, actions = make(count)
    vocab = [bytes([i]) for i in range(256)] + [b'']
    native = xgr.GrammarCompiler(xgr.TokenizerInfo(vocab, vocab_type=xgr.VocabType.RAW, stop_token_ids=[256]))
    matcher = StatefulMatcher(native, p.grammar, vocab, context_for(p, codec='canonical'))
    mask = xgr.allocate_token_bitmask(1, len(vocab))
    def allowed(token):
        matcher.fill_next_token_bitmask(mask)
        return bool((int(mask[0, token // 32]) >> (token % 32)) & 1)
    canonical = True
    if canonical:
        assert matcher.accept_token(ord('['))
    for index, action in enumerate(actions):
        if canonical:
            raw = json.dumps(action, ensure_ascii=False, separators=(',', ':')).encode()
            if index:
                assert matcher.accept_token(ord(','))
        else:
            body = {k: v for k, v in action.items() if k != 'operation'}
            raw = ('<agent_call>' + json.dumps(body, ensure_ascii=False, separators=(',', ':')) + '</agent_call>').encode()
        for token in raw:
            assert allowed(token)
            assert matcher.accept_token(token)
        if canonical:
            assert allowed(ord(']')) is (index == count - 1)
        else:
            assert allowed(256) is (index == count - 1)
    if canonical:
        assert matcher.accept_token(ord(']'))
    assert allowed(256) and matcher.is_completed()
    assert not allowed(ord('<' if not canonical else ','))


def test_compilation_is_stable_across_sorted_context_transport():
    from mlx_serve_alp.catalog import stable_json
    resources = [{"kind": "asset", "slot": "template", "description": "Template",
                  "required": True, "profile_ref": "asset.template", "version": "1.0.0", "access_mode": "read"}]
    cat = Catalog(allowed_operations=["agent_definition_generate"],
                  response_constraints={"members": [{"operation": "agent_definition_generate", "payload": {
                      "fixed_values": {"/resource_requirements": resources, "/requested_tools": []}}}]})
    opts = ALPOptions(protocol_version="0.4.0", catalog_ref="test", allowed_operations=cat.allowed_operations)
    a = Compiler().compile(opts, cat)
    b = Compiler().compile(opts, Catalog.model_validate_json(stable_json(cat.model_dump())))
    assert a.digest == b.digest
    assert a.grammar == b.grammar


@pytest.mark.parametrize("resource_count", [1, 16])
def test_resource_selection_cannot_close_before_required_tools_are_possible(resource_count):
    import xgrammar as xgr
    from alp_schema_mcp.catalog import ContractCatalog

    from mlx_serve_alp.catalog import stable_json
    from mlx_serve_alp.decoding_state import StatefulMatcher, context_for
    resources = [{"kind": "knowledge", "slot": "docs", "description": "Docs", "required": True,
                  "profile_ref": "retrieval.docs", "access_mode": "retrieval"}]
    resources += [{"kind": "asset", "slot": f"asset_{i}", "description": "Asset", "required": False,
                   "profile_ref": f"asset.profile_{i}", "version": "1.0.0", "access_mode": "read"}
                  for i in range(resource_count - 1)]
    contracts = ContractCatalog('0.4.0')
    names = ['knowledge.search', 'knowledge.read']
    tools = {n: {k: contracts.resource_tools[n][k] for k in ('input_schema', 'external_effect', 'state_effect')} for n in names}
    interface = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
    cat = Catalog(allowed_operations=['agent_definition_generate'], tools=tools,
                  response_constraints={'members': [{'operation': 'agent_definition_generate', 'payload': {
                      'fixed_values': {'/resource_requirements': resources, '/requested_tools': names},
                      'capabilities': {'answer_docs': {'input_schema': interface, 'output_schema': {'type':'string'},
                                                     'external_effect':'read'}}}}]})
    p = Compiler().compile(ALPOptions(protocol_version='0.4.0', catalog_ref='test', allowed_operations=cat.allowed_operations), cat)
    payload = {'resource_requirements': json.loads(stable_json(resources)), 'requested_tools': names,
               'name':'helper_agent', 'description':'Help', 'instructions':'Answer',
               'exported_capabilities':[{'name':'answer_docs', 'description':'Answer',
                 'input_schema':json.loads(stable_json(interface)), 'output_schema':{'type':'string'},
                 'execution':{'kind':'agent_run', 'instructions':'Read', 'resource_subset':{'slots':[]},
                              'tool_subset':names}, 'state_effect':'read','external_effect':'read'}]}
    action={'protocol_version':'0.4.0','request_id':'r','operation':'agent_definition_generate','payload':payload}
    canonical=True
    raw=json.dumps([action],ensure_ascii=False,separators=(',',':')) if canonical else '<agent_definition_generate>'+json.dumps({k:v for k,v in action.items() if k!='operation'},ensure_ascii=False,separators=(',',':'))+'</agent_definition_generate>'
    prefix=raw.split('"slots":[]',1)[0]+'"slots":['
    vocab=[bytes([i]) for i in range(256)]+[b'']
    native=xgr.GrammarCompiler(xgr.TokenizerInfo(vocab,vocab_type=xgr.VocabType.RAW,stop_token_ids=[256]))
    context=json.loads(stable_json(context_for(p, codec='canonical' if canonical else 'tagged')))
    matcher=StatefulMatcher(native,p.grammar,vocab,context)
    for token in prefix.encode():
        assert matcher.accept_token(token)
    mask=xgr.allocate_token_bitmask(1,len(vocab))
    matcher.fill_next_token_bitmask(mask)
    assert not (int(mask[0,ord(']')//32])>>(ord(']')%32))&1
    assert not matcher._probe((prefix + '"docs","docs"]').encode())[0]
    for token in b'"docs"]':
        assert matcher.accept_token(token)
    suffix=raw.split('"slots":[]',1)[1]
    for token in suffix.encode():
        assert matcher.accept_token(token)
    assert matcher.is_completed()
