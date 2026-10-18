"""Multi-turn UI and fresh evidence acceptance with synthetic local documents."""
import json

from mdr_rag import conversations as chats, app_services as services, pipeline
from mdr_rag.qa_types import AnswerResult
from test_app_services import workspace, app
from test_question_services import documents, model, submit


def button(ui, label):
    return next(b for b in ui.button if b.label == label)


def test_bounded_context_and_failure_fallback(monkeypatch):
    conversation = chats.Conversation()
    for n in range(20):
        conversation.messages.append(chats.Turn(str(n), str(n) + "x" * 5000,
            AnswerResult(str(n), answer="y" * 5000), "query", "v1", ("legal/a.pdf",)))
    seen = []
    def rewrite(rules, prompt, schema):
        seen.append(json.loads(prompt))
        assert "may be wrong" in rules and "untrusted" in rules
        return schema(query="Which annex describes safety requirements?")
    monkeypatch.setattr(pipeline, "llm_parse", rewrite)
    query, fallback = chats.contextualize("Which annex mentions them?", conversation)
    assert "safety" in query and not fallback
    history = seen[0]["history"]
    assert len(history) <= 6 and sum(len(m["content"]) for m in history) <= 6000
    assert all("0xxx" not in m["content"] for m in history)
    def fail(*args):
        raise ConnectionError("private")
    monkeypatch.setattr(pipeline, "llm_parse", fail)
    assert chats.contextualize("What about that?", conversation) == ("What about that?", True)
    assert chats.contextualize("Unrelated?", chats.Conversation()) == ("Unrelated?", False)


def test_followup_retrieves_fresh_and_verifies_with_original_question(documents, monkeypatch):
    calls = model(monkeypatch)
    generate = pipeline.llm_parse
    def rewrite_or_answer(rules, prompt, schema):
        if schema is chats.StandaloneQuestion:
            return schema(query="What calibration records are discussed?")
        return generate(rules, prompt, schema)
    monkeypatch.setattr(pipeline, "llm_parse", rewrite_or_answer)
    retrieved = []
    search = pipeline.hybrid_search
    def retrieve(query, kind, k, **kwargs):
        retrieved.append((query, kwargs.get("sources")))
        return search(query, kind, k, **kwargs)
    monkeypatch.setattr(pipeline, "hybrid_search", retrieve)
    conversation = chats.Conversation(selected_sources=["legal/alpha.pdf"])
    first = chats.submit_turn(conversation, "What records?", "one")
    assert first.result.status == "supported" and len(calls) == 2
    conversation.selected_sources = ["device/alpha.docx"]
    second = chats.submit_turn(conversation, "What about those?", "two")
    assert len(calls) == 4 and second.result.status == "supported"
    assert retrieved[-1] == ("What calibration records are discussed?", {"device/alpha.docx"})
    assert second.result.question == "What about those?"
    assert {s.source for s in second.result.sources} == {"device/alpha.docx"}
    assert first.selected_sources == ("legal/alpha.pdf",)
    assert chats.submit_turn(conversation, "What about those?", "two") is second
    assert len(calls) == 4 and len(conversation.messages) == 2


def test_ui_conversations_reruns_filters_and_stale_history(documents, monkeypatch):
    calls = model(monkeypatch)
    ui = app()
    ui.multiselect[0].set_value(["legal/alpha.pdf"]).run()
    submit(ui)
    assert not ui.exception and len(ui.chat_message) == 2
    first_id = ui.session_state["active_conversation"]
    count = len(calls)
    ui.run()
    assert len(calls) == count and len(ui.chat_message) == 2
    ui.multiselect[0].set_value(["device/alpha.docx"]).run()
    assert any("legal/alpha.pdf" in e.label for e in ui.expander)
    button(ui, "New conversation").click().run()
    second_id = ui.session_state["active_conversation"]
    assert second_id != first_id and not ui.chat_message
    submit(ui, "What calibration records?")
    assert len(calls) == count + 2  # No contextualization call from the first chat.
    selector = next(s for s in ui.selectbox if s.label == "Conversation")
    selector.set_value(first_id).run()
    assert len(ui.chat_message) == 2
    assert ui.multiselect[0].value == ["device/alpha.docx"]
    (documents[0] / "device" / "changed.txt").write_text("SYNTHETIC changed source")
    ui.run()
    assert ui.chat_input[0].disabled and len(ui.chat_message) == 2
    assert any("earlier index version" in w.value for w in ui.warning)
    assert services.index_documents().success
    ui.run()
    assert not ui.chat_input[0].disabled
    assert any("earlier index version" in w.value for w in ui.warning)
    button(ui, "Clear current conversation").click().run()
    assert not ui.chat_message
    next(s for s in ui.selectbox if s.label == "Conversation").set_value(second_id).run()
    assert len(ui.chat_message) == 2


def test_failed_request_no_duplicate_and_stale_submission_blocked(documents, monkeypatch):
    calls = model(monkeypatch, failure="generation_error")
    ui = app()
    submit(ui)
    assert ui.error and len(ui.chat_message) == 2
    count = len(calls)
    ui.run()
    assert len(calls) == count and len(ui.chat_message) == 2
    conversation = ui.session_state["conversations"][ui.session_state["active_conversation"]]
    prior = conversation.messages[0]
    assert chats.submit_turn(conversation, prior.question, prior.request_id) is prior
    assert len(calls) == count
    (documents[0] / "legal" / "alpha.pdf").unlink()
    assert chats.submit_turn(conversation, "New question?", "blocked") is None
    assert len(conversation.messages) == 1


def test_changed_index_during_inference_withholds_answer(monkeypatch):
    versions = iter(["before", "after"])
    monkeypatch.setattr(services, "get_question_context", lambda: services.QuestionContext(
        ("legal/a.pdf",), next(versions)))
    monkeypatch.setattr(services, "ask_question", lambda *args, **kwargs:
                        AnswerResult("Question?", answer="Old index answer", status="supported"))
    conversation = chats.Conversation(selected_sources=["legal/a.pdf"])
    turn = chats.submit_turn(conversation, "Question?", "request")
    assert turn.result.status == "index_invalid" and turn.result.error
    assert not turn.result.answer and not turn.result.sources


def test_first_index_populates_chat_selection(workspace):
    ui = app()
    assert ui.chat_input[0].disabled
    (workspace[0] / "device" / "new.txt").write_text("SYNTHETIC readable text")
    assert services.index_documents().success
    ui.run()
    assert not ui.exception and ui.multiselect[0].value == ["device/new.txt"]
    assert not ui.chat_input[0].disabled
