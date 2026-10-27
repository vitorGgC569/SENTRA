"""The pipx core must not start optional Web services implicitly."""
import os
import sys
from types import SimpleNamespace

from sentra_cli import core_entry
from sentra_cli import __main__ as cli


def test_core_defaults_to_local_without_reusing_credentials(monkeypatch):
    monkeypatch.setattr(os, 'environ', os.environ.copy())
    for name in ('SENTRA_CLI_MODEL', 'OPENAI_API_KEY', 'SENTRA_CLI_AUTO_START_GATEWAY'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(sys, 'argv', ['sentra', '--help'])
    seen = []
    monkeypatch.setattr(cli, 'main', lambda args: seen.append(args) or 0)
    assert core_entry.main() == 0
    assert seen == [['--help', '--no-auto-start']]
    assert __import__('os').environ['OPENAI_API_KEY'] == 'none'
    assert __import__('os').environ['SENTRA_CLI_MODEL'] == 'local'


def test_core_respects_explicit_web_opt_in_and_api_model(monkeypatch):
    monkeypatch.setattr(os, 'environ', os.environ.copy())
    monkeypatch.setenv('SENTRA_CLI_AUTO_START_GATEWAY', '1')
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    monkeypatch.delenv('SENTRA_CLI_MODEL', raising=False)
    monkeypatch.setattr(sys, 'argv', ['sentra', '-p', 'hello'])
    seen = []
    monkeypatch.setattr(cli, 'main', lambda args: seen.append(args) or 0)
    core_entry.main()
    assert seen == [['-p', 'hello']]
    assert __import__('os').environ['SENTRA_CLI_MODEL'] == 'gpt-4o'


def test_none_api_key_routes_to_local_without_web(monkeypatch):
    from sentra_cli.client import ModelClient
    monkeypatch.setenv('OPENAI_API_KEY', 'none')
    config = SimpleNamespace(model='local', openai_api_key='', local_base_url='http://localhost:11434/v1',
                             local_api_key='local', local_model_name='fixture-local')
    client = ModelClient(config)
    monkeypatch.setattr(client, 'probe_health', lambda: {'gateway': False, 'local': True})
    calls = []
    monkeypatch.setattr(client, '_chat_completions_stream',
                        lambda base, key, messages, model, provider: iter([calls.append((model, provider)) or 'ok']))
    assert ''.join(client._chat_stream([{'role': 'user', 'content': 'hi'}])) == 'ok'
    assert calls == [('fixture-local', 'local')]


def test_local_environment_overrides_package_config(tmp_path, monkeypatch):
    from sentra_cli.config import CLIConfig
    monkeypatch.setenv('SENTRA_LOCAL_BASE_URL', 'http://127.0.0.1:12345/v1')
    monkeypatch.setenv('SENTRA_LOCAL_MODEL', 'fixture-model')
    config = CLIConfig(workspace=tmp_path, model='local')
    assert config.local_base_url == 'http://127.0.0.1:12345/v1'
    assert config.local_model_name == 'fixture-model'
