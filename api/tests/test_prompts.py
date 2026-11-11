from types import SimpleNamespace

import pytest
from langfuse.api import NotFoundError

from app import prompts
from app.note_taker.lecture_notes import skill_library


@pytest.fixture(autouse=True)
def no_skill_sync(monkeypatch: pytest.MonkeyPatch) -> list:
    """Skills are pushed and pulled with the prompts; their sync is tested in
    test_lecture_notes.py."""
    calls: list = []
    monkeypatch.setattr(skill_library, "push", lambda client, force=False: calls.append("push"))
    monkeypatch.setattr(skill_library, "pull", lambda client: calls.append("pull"))
    return calls


class FakeLangfuse:
    """Stands in for the Langfuse client: one stored text prompt per name."""

    def __init__(self, stored: dict[str, str]) -> None:
        self.stored = stored
        self.created: list[dict] = []
        self.fetched: list[dict] = []

    def get_prompt(self, name, *, label, type, fallback=None, cache_ttl_seconds=None):
        self.fetched.append({"name": name, "label": label, "type": type, "fallback": fallback})
        if name not in self.stored:
            if fallback is None:
                raise NotFoundError(body=None)
            return self._client(fallback, version=None)
        return self._client(self.stored[name], version=1)

    def create_prompt(self, *, name, type, prompt, labels, commit_message):
        self.created.append({"name": name, "type": type, "prompt": prompt, "labels": labels})
        return SimpleNamespace(version=2)

    @staticmethod
    def _client(text, version):
        from langfuse.api import Prompt_Text
        from langfuse.model import TextPromptClient

        return TextPromptClient(
            Prompt_Text(name="x", version=version or 0, prompt=text, config={}, labels=[], tags=[]),
            is_fallback=version is None,
        )


def use(monkeypatch: pytest.MonkeyPatch, client: FakeLangfuse) -> FakeLangfuse:
    monkeypatch.setattr(prompts, "langfuse_client", lambda: client)
    return client


def test_every_prompt_has_a_fallback_file() -> None:
    for name in prompts.PROMPTS:
        assert prompts.read_fallback(name)


def test_fetches_production_text_prompt_and_compiles_variables(monkeypatch, tmp_path) -> None:
    fallback = tmp_path / "template.md"
    fallback.write_text("Local {{count}}\n", encoding="utf-8")
    monkeypatch.setattr(prompts, "PROMPTS", {"note-taker/template": fallback})
    client = use(monkeypatch, FakeLangfuse({"note-taker/template": "Run {{count}}"}))
    assert prompts.get_prompt("note-taker/template", count=3) == "Run 3"
    fetched = client.fetched[0]
    assert (fetched["label"], fetched["type"]) == ("production", "text")
    assert fetched["fallback"] == "Local {{count}}"


def test_falls_back_to_the_markdown_file(monkeypatch, tmp_path) -> None:
    fallback = tmp_path / "template.md"
    fallback.write_text("Local {{count}}\n", encoding="utf-8")
    monkeypatch.setattr(prompts, "PROMPTS", {"note-taker/template": fallback})
    monkeypatch.setattr(prompts, "langfuse_client", lambda: None)
    assert prompts.get_prompt("note-taker/template", count=3) == "Local 3"
    use(monkeypatch, FakeLangfuse({}))
    assert prompts.get_prompt("note-taker/template", count=3) == "Local 3"


def test_push_creates_missing_prompts_and_keeps_langfuse_edits(monkeypatch, capsys) -> None:
    unchanged = prompts.read_fallback("note-taker/orchestrator")
    client = use(
        monkeypatch,
        FakeLangfuse({"note-taker/orchestrator": unchanged, "note-taker/moodle": "old"}),
    )
    prompts.push()
    # Only the prompts Langfuse does not have are created; the edited one is left alone.
    assert {c["name"] for c in client.created} == set(prompts.PROMPTS) - {
        "note-taker/orchestrator",
        "note-taker/moodle",
    }
    out = capsys.readouterr().out
    assert "note-taker/orchestrator: unchanged (version 1)" in out
    assert "note-taker/moodle: differs from Langfuse version 1" in out


def test_push_creates_a_prompt_langfuse_does_not_have(monkeypatch) -> None:
    client = use(monkeypatch, FakeLangfuse({}))
    prompts.push()
    created = {c["name"]: c for c in client.created}
    assert set(created) == set(prompts.PROMPTS)
    assert all(c["labels"] == ["production"] and c["type"] == "text" for c in created.values())


def test_push_force_overwrites_a_changed_prompt(monkeypatch) -> None:
    client = use(monkeypatch, FakeLangfuse({"note-taker/moodle": "old"}))
    prompts.push(force=True)
    created = {c["name"]: c for c in client.created}
    assert created["note-taker/moodle"]["prompt"] == prompts.read_fallback("note-taker/moodle")


def test_pull_writes_langfuse_text_to_the_markdown_files(monkeypatch, tmp_path) -> None:
    fallback = tmp_path / "orchestrator.md"
    fallback.write_text("local\n", encoding="utf-8")
    monkeypatch.setattr(prompts, "PROMPTS", {"note-taker/orchestrator": fallback})
    use(monkeypatch, FakeLangfuse({"note-taker/orchestrator": "edited in Langfuse"}))
    prompts.pull()
    assert fallback.read_text(encoding="utf-8") == "edited in Langfuse\n"
