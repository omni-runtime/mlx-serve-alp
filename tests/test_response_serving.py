import json

import pytest

from mlx_serve_alp.catalog import CatalogRegistry, ServerConfig
from mlx_serve_alp.constraints import ContractCompiler
from mlx_serve_alp.errors import ALPError
from mlx_serve_alp.parser import ALPParser
from mlx_serve_alp.protocol import ALPChatRequest
from mlx_serve_alp.serving import ALPServing
from mlx_serve_alp.streaming import GenerationChunk


@pytest.mark.parametrize('late_bad', [False, True])
async def test_completed_event_releases_all_members_only_after_whole_stream(late_bad):
    values = [{'protocol_version': '0.4.0', 'request_id': f'r{i}',
               'operation': 'list_agent_capabilities', 'payload': {'instance_id': 'agt_001'}} for i in range(2)]
    class Backend:
        closed = False
        async def generate(self, request, messages, profile, raw_request):
            try:
                yield GenerationChunk(text=json.dumps(values))
                if late_bad:
                    yield GenerationChunk(text=' trailing text')
                yield GenerationChunk(finish_reason='stop')
            finally:
                self.closed = True
    backend = Backend()
    config = ServerConfig(catalogs={'test': {'allowed_operations': ['list_agent_capabilities'],
                          'agents': {'agt_001': {'input_schema': {'type': 'object'}}}}})
    serving = ALPServing(backend, CatalogRegistry(config), ContractCompiler(),
                         parser_factory=lambda p, c: ALPParser(p, c, 'canonical'))
    request = ALPChatRequest.model_validate({'model': 'test', 'messages': [{'role': 'user', 'content': 'list'}],
        'alp': {'protocol_version': '0.4.0', 'allowed_operations': ['list_agent_capabilities'], 'catalog_ref': 'test'}})
    prepared = await serving.prepare(request)
    events = []
    if late_bad:
        with pytest.raises(ALPError):
            async for event in serving.events(prepared):
                events.append(event)
        assert all(event['type'] != 'agent_call.completed' for event in events)
    else:
        events = [event async for event in serving.events(prepared)]
        completed = [event for event in events if event['type'] == 'agent_call.completed']
        assert len(completed) == 1
        response = completed[0]['response']
        calls = response['choices'][0]['message']['agent_calls']
        assert [call['request'] for call in calls] == values
        assert len({call['id'] for call in calls}) == 2
        assert len(response['alp']['task_constraint_coverage']) == 2
        assert response['alp']['protocol_version'] == '0.4.0'
    assert backend.closed
