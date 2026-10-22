import subprocess

import pytest

import mcpb_docker_fixture as fixture


@pytest.mark.parametrize('kind', ['image', 'daemon'])
@pytest.mark.parametrize('failure', ['timeout', 'missing', 'connection'])
def test_read_only_probe_unavailability_is_bounded_without_retry(monkeypatch, kind, failure):
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(command, kwargs['timeout'])
        if failure == 'missing':
            raise FileNotFoundError('unavailable test CLI')
        return subprocess.CompletedProcess(command, 1, '', 'daemon unavailable')
    monkeypatch.setattr(fixture.subprocess, 'run', run)
    result = fixture.probe('trusted-test-docker', kind)
    assert result.returncode != 0 and not result.stdout
    assert len(calls) == 1 and calls[0][1]['timeout'] == 5
    assert calls[0][0][1] in {'image', 'info'}


def test_probe_cannot_be_used_for_an_effect(monkeypatch):
    monkeypatch.setattr(fixture.subprocess, 'run', lambda *a, **kw: pytest.fail('effect launched'))
    with pytest.raises(KeyError):
        fixture.probe('docker', 'rm')


def test_available_probe_preserves_exact_image_identity(monkeypatch):
    image = 'sha256:' + 'a' * 64 + '\n'
    monkeypatch.setattr(fixture.subprocess, 'run', lambda command, **kw: subprocess.CompletedProcess(command, 0, image, ''))
    assert fixture.probe('docker', 'image').stdout == image


def test_trusted_cli_unavailable_never_falls_back_to_path(monkeypatch):
    def unavailable():
        raise PermissionError('trusted Docker CLI binary unavailable')
    monkeypatch.setattr(fixture, '_trusted_docker', unavailable)
    assert fixture.trusted_docker() is None
