"""The Nemotron container: started only when it is not serving, and every way it fails to start is named."""

import subprocess

import pytest

from agent import nemotron_server


@pytest.fixture
def compose(monkeypatch):
    """Record every docker call and answer it with the given exit code, or with Docker missing altogether."""
    calls = []

    def use(returncode=0, missing=False, stderr=""):
        def fake_run(args, **kwargs):
            calls.append(args)
            if missing:
                raise FileNotFoundError("docker")
            return subprocess.CompletedProcess(args, returncode, stdout="", stderr=stderr)

        monkeypatch.setattr(subprocess, "run", fake_run)
        return calls

    return use


async def test_a_serving_container_is_left_alone(monkeypatch, compose):
    """A container that already answers is not started again."""
    calls = compose()
    monkeypatch.setattr(nemotron_server, "ready", lambda: True)
    await nemotron_server.ensure()
    assert calls == []


async def test_a_stopped_container_is_brought_up_and_awaited(monkeypatch, compose):
    """Compose starts the service, and ensure returns once the container answers."""
    calls = compose()
    answers = iter([False, False, True])
    monkeypatch.setattr(nemotron_server, "ready", lambda: next(answers))
    await nemotron_server.ensure()
    assert calls == [["docker", "compose", "-f", str(nemotron_server.COMPOSE), "up", "-d", "nemotron"]]


async def test_missing_docker_is_named(monkeypatch, compose):
    """Without Docker the error says so, rather than surfacing a bare FileNotFoundError."""
    compose(missing=True)
    monkeypatch.setattr(nemotron_server, "ready", lambda: False)
    with pytest.raises(RuntimeError, match="Docker is not installed"):
        await nemotron_server.ensure()


async def test_a_failing_compose_passes_on_dockers_reason(monkeypatch, compose):
    """A compose failure, such as Docker Desktop not running, carries Docker's own message."""
    compose(returncode=1, stderr="cannot connect to the Docker daemon")
    monkeypatch.setattr(nemotron_server, "ready", lambda: False)
    with pytest.raises(RuntimeError, match="cannot connect to the Docker daemon"):
        await nemotron_server.ensure()


async def test_a_container_that_never_answers_times_out(monkeypatch, compose):
    """A container that starts but never serves ends the run with a pointer to its logs."""
    compose()
    monkeypatch.setattr(nemotron_server, "ready", lambda: False)
    monkeypatch.setattr(nemotron_server, "STARTUP_TIMEOUT", 0.0)
    with pytest.raises(RuntimeError, match="docker logs"):
        await nemotron_server.ensure()


class _Launch:
    """Stand in for the background compose process, finished with the given exit code or still running."""

    def __init__(self, returncode=None):
        self.returncode = returncode

    def poll(self):
        """Report the exit code, or None while still running."""
        return self.returncode


@pytest.fixture
def launches(monkeypatch):
    """Record every background start, beginning with none, and answer each with a process of the given exit code."""
    monkeypatch.setattr(nemotron_server, "_launch", None)
    started = []

    def use(returncode=None):
        def fake_popen(args, **kwargs):
            started.append(args)
            return _Launch(returncode)

        monkeypatch.setattr(subprocess, "Popen", fake_popen)
        return started

    return use


def test_other_stts_get_no_hint_and_start_nothing(monkeypatch, launches):
    """Picking any other STT leaves Docker alone."""
    started = launches()
    monkeypatch.setattr(nemotron_server, "ready", lambda: False)
    assert nemotron_server.hint("voxtral") == ""
    assert started == []


def test_picking_nemotron_starts_the_container_once(monkeypatch, launches):
    """The first look at the choice starts the container, and the dialog's repeated looks only report on it."""
    started = launches()
    monkeypatch.setattr(nemotron_server, "ready", lambda: False)
    assert "starting" in nemotron_server.hint("nemotron")
    assert "starting" in nemotron_server.hint("nemotron")
    assert len(started) == 1
    monkeypatch.setattr(nemotron_server, "ready", lambda: True)
    assert nemotron_server.hint("nemotron") == "Container running"


def test_a_serving_container_is_not_started_from_the_dialog(monkeypatch, launches):
    """A container that already answers is reported as running and not started again."""
    started = launches()
    monkeypatch.setattr(nemotron_server, "ready", lambda: True)
    assert nemotron_server.hint("nemotron") == "Container running"
    assert started == []


def test_a_failed_start_is_shown_and_not_retried(monkeypatch, launches):
    """A compose that exits with an error is named in the note, and the dialog does not keep retrying it."""
    started = launches(returncode=1)
    monkeypatch.setattr(nemotron_server, "ready", lambda: False)
    assert "Docker Desktop" in nemotron_server.hint("nemotron")
    assert "Docker Desktop" in nemotron_server.hint("nemotron")
    assert len(started) == 1


def test_missing_docker_is_shown_in_the_dialog(monkeypatch):
    """Without Docker the note says so instead of the dialog failing."""

    def no_docker(*args, **kwargs):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(nemotron_server, "_launch", None)
    monkeypatch.setattr(subprocess, "Popen", no_docker)
    monkeypatch.setattr(nemotron_server, "ready", lambda: False)
    assert nemotron_server.hint("nemotron") == "Docker is not installed"
