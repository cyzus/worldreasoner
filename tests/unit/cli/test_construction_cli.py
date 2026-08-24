"""Construction CLI safety tests."""

from src.cli.commands import construction


class ReconfigurableStream:
    """Minimal stream exposing the Windows encoding hook."""

    def __init__(self) -> None:
        self.calls = []

    def reconfigure(self, **kwargs) -> None:
        self.calls.append(kwargs)


def test_configures_both_construction_streams_as_utf8(monkeypatch) -> None:
    stdout = ReconfigurableStream()
    stderr = ReconfigurableStream()
    monkeypatch.setattr(construction.sys, "stdout", stdout)
    monkeypatch.setattr(construction.sys, "stderr", stderr)

    construction._configure_utf8_streams()

    expected = [{"encoding": "utf-8", "errors": "replace"}]
    assert stdout.calls == expected
    assert stderr.calls == expected
