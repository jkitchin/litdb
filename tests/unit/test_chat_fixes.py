"""Regression tests for bugs fixed in litdb.chat."""

from types import SimpleNamespace
from unittest import mock

import litellm
import pytest

from litdb import chat


@pytest.fixture
def no_docling(monkeypatch):
    """Make docling fail so files are read as text."""

    class Converter:
        def convert(self, path):
            raise RuntimeError("unsupported")

    monkeypatch.setattr(chat, "DocumentConverter", Converter)


@pytest.mark.unit
def test_file_expansion_replaces_brackets(tmp_path, no_docling):
    f = tmp_path / "note.txt"
    f.write_text("hello")
    assert chat.expand_prompt(f"see [[{f}]] now") == "see hello now"


@pytest.mark.unit
def test_file_contents_are_not_expanded(tmp_path, no_docling):
    """A file or web page with a < line must not run a shell command."""
    marker = tmp_path / "ran"
    f = tmp_path / "evil.txt"
    f.write_text(f"<touch {marker}\nand `numpy.linspace`")
    out = chat.expand_prompt(f"[[{f}]]")
    assert not marker.exists()
    assert out == f.read_text()


@pytest.mark.unit
def test_missing_file_does_not_crash(tmp_path, no_docling):
    prompt = f"[[{tmp_path / 'nope.txt'}]]"
    assert chat.expand_prompt(prompt) == prompt


@pytest.mark.unit
def test_inline_code_is_left_alone():
    assert chat.expand_prompt("what does `x = 1` do") == "what does `x = 1` do"
    assert chat.expand_prompt("`numpy.nonexistent_thing`") == (
        "`numpy.nonexistent_thing`"
    )


@pytest.mark.unit
def test_docstring_expansion_still_works():
    assert "linspace" in chat.expand_prompt("`numpy.linspace`")


@pytest.mark.unit
def test_shell_expansion_still_works():
    assert chat.expand_prompt("a\n<echo hi\nb") == "a\nhi\n\nb"


@pytest.mark.unit
def test_read_prompt_line_continuation():
    with mock.patch("builtins.input", side_effect=["one \\", "two \\", "three"]):
        assert chat._read_prompt() == "one \ntwo \nthree"


def _stream(text):
    delta = SimpleNamespace(content=text)
    return [SimpleNamespace(choices=[SimpleNamespace(delta=delta)])]


@pytest.mark.unit
def test_get_completion_does_not_retry_auth_errors():
    err = litellm.AuthenticationError("bad key", llm_provider="x", model="m")
    with (
        mock.patch.object(chat, "completion", side_effect=err) as c,
        pytest.raises(litellm.AuthenticationError),
    ):
        chat.get_completion("m", [])
    assert c.call_count == 1


@pytest.fixture
def chat_session(monkeypatch):
    """Run chat() with a fake db, RAG and LLM; return the messages sent."""
    db = mock.MagicMock()
    db.execute.return_value.fetchall.return_value = [("old prompt",)]
    monkeypatch.setattr(chat, "get_db", lambda: db)
    monkeypatch.setattr(chat, "get_config", lambda: {"llm": {"model": "m"}})
    monkeypatch.setattr(
        chat, "get_rag_content", lambda prompt, n: ("FULL PAPER TEXT", "")
    )
    sent = []

    def fake_completion(model, messages):
        sent.append([m["content"] for m in messages])
        return "answer"

    monkeypatch.setattr(chat, "get_completion", fake_completion)
    return sent


@pytest.mark.unit
def test_chat_exits_on_ctrl_d(chat_session):
    with mock.patch("builtins.input", side_effect=EOFError):
        chat.chat()


@pytest.mark.unit
def test_chat_loads_history(chat_session):
    with (
        mock.patch.object(chat.readline, "add_history") as add,
        mock.patch("builtins.input", side_effect=EOFError),
    ):
        chat.chat()
    add.assert_called_with("old prompt")


@pytest.mark.unit
def test_chat_history_keeps_question_not_rag_text(chat_session):
    with mock.patch("builtins.input", side_effect=["q1", "q2", EOFError]):
        chat.chat()
    first, second = chat_session
    assert "FULL PAPER TEXT" in first[-1]
    # The earlier turn is kept as asked; only the new turn has retrieved text.
    assert second[:2] == ["q1", "answer"]
    assert "FULL PAPER TEXT" in second[-1]
