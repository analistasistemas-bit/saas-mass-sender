import importlib
from pathlib import Path


def test_load_dotenv_file_populates_missing_env(monkeypatch, tmp_path):
    monkeypatch.delenv('WHATSAPP_PROVIDER', raising=False)
    monkeypatch.delenv('DB_PATH', raising=False)

    env_file = tmp_path / '.env'
    env_file.write_text('WHATSAPP_PROVIDER=bridge\nDB_PATH=custom.db\n', encoding='utf-8')

    config = importlib.import_module('utils.config')
    importlib.reload(config)
    config.load_app_env(env_file)

    assert config.os.getenv('WHATSAPP_PROVIDER') == 'bridge'
    assert config.os.getenv('DB_PATH') == 'custom.db'


def test_load_dotenv_does_not_override_existing_env(monkeypatch, tmp_path):
    monkeypatch.setenv('WHATSAPP_PROVIDER', 'evolution')
    env_file = tmp_path / '.env'
    env_file.write_text('WHATSAPP_PROVIDER=bridge\n', encoding='utf-8')

    config = importlib.import_module('utils.config')
    importlib.reload(config)
    config.load_app_env(env_file)

    assert config.os.getenv('WHATSAPP_PROVIDER') == 'evolution'


def test_load_dotenv_populates_inbound_ai_env(monkeypatch, tmp_path):
    for key in [
        'INBOUND_WEBHOOK_TOKEN',
        'OPENROUTER_API_KEY',
        'OPENROUTER_MODEL',
        'HUMAN_HANDOFF_PHONE',
    ]:
        monkeypatch.delenv(key, raising=False)

    env_file = tmp_path / '.env'
    env_file.write_text(
        '\n'.join(
            [
                'INBOUND_WEBHOOK_TOKEN=secret-token',
                'OPENROUTER_API_KEY=or-key',
                'OPENROUTER_MODEL=openai/gpt-4.1-mini',
                'HUMAN_HANDOFF_PHONE=+5581888888888',
            ]
        )
        + '\n',
        encoding='utf-8',
    )

    config = importlib.import_module('utils.config')
    importlib.reload(config)
    config.load_app_env(env_file)

    assert config.os.getenv('INBOUND_WEBHOOK_TOKEN') == 'secret-token'
    assert config.os.getenv('OPENROUTER_API_KEY') == 'or-key'
    assert config.os.getenv('OPENROUTER_MODEL') == 'openai/gpt-4.1-mini'
    assert config.os.getenv('HUMAN_HANDOFF_PHONE') == '+5581888888888'
