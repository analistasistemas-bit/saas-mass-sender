from services.openrouter_client import OpenRouterClient


def test_parse_json_content_accepts_plain_json():
    client = OpenRouterClient()

    payload = client._parse_json_content('{"action":"reply","reply_text":"Oi","handoff_reason":"","confidence":0.9}')

    assert payload['action'] == 'reply'
    assert payload['reply_text'] == 'Oi'


def test_parse_json_content_accepts_fenced_json():
    client = OpenRouterClient()

    payload = client._parse_json_content(
        '```json\n{"action":"reply","reply_text":"Oi fenced","handoff_reason":"","confidence":0.7}\n```'
    )

    assert payload['action'] == 'reply'
    assert payload['reply_text'] == 'Oi fenced'


def test_parse_json_content_accepts_text_wrapped_json():
    client = OpenRouterClient()

    payload = client._parse_json_content(
        'Aqui está o resultado:\n{"action":"handoff","reply_text":"","handoff_reason":"purchase_intent","confidence":0.8}\nObrigado.'
    )

    assert payload['action'] == 'handoff'
    assert payload['handoff_reason'] == 'purchase_intent'
