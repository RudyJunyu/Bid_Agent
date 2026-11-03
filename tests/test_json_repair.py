from bid_agent.infrastructure.json_repair import JsonRepairError, repair_json


def test_repair_json_from_fenced_and_think_tags():
    raw = '<think>reasoning</think>\n```json\n{"ok": true, "n": 1}\n```'
    assert repair_json(raw) == {'ok': True, 'n': 1}


def test_repair_json_balanced_object_in_prose():
    raw = '结果如下：{"items":[{"title":"保证金","severity":"high"}]} 结束'
    data = repair_json(raw)
    assert data['items'][0]['title'] == '保证金'


def test_repair_json_raises_without_llm_fallback():
    try:
        repair_json('not json at all', repair_chat_fn=None, max_llm_attempts=0)
        assert False, 'expected JsonRepairError'
    except JsonRepairError:
        pass
