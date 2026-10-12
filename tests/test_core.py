from mdr_rag.core import chunks, is_real_quote, parse_pages, validate_ids
from mdr_rag.schemas import (
    Answer, AnswerClaim, AnswerSupportVerification, ClaimEvidence
)
from mdr_rag import pipeline
from mdr_rag.Q_Mix_report_writer import write_markdown


def test_parse_pages():
    assert parse_pages("2,4-6", 10) == {2, 4, 5, 6}


def test_parse_pages_invalid():
    import pytest
    with pytest.raises(ValueError):
        parse_pages("0,2", 10)
    with pytest.raises(ValueError):
        parse_pages("12", 10)


def test_chunks_retain_full_text():
    parts = list(chunks("This is a demonstration. " * 120, size=110, overlap=25))
    assert len(parts) > 1
    assert all(len(x) <= 110 for x in parts)


def test_quote_validation():
    assert is_real_quote("provide risk management documentation", "Must provide risk management\n documentation.")
    assert not is_real_quote("not present in evidence", "A different text.")


def test_prevent_hallucinated_citations():
    found = [{"id": "D-123"}]
    assert validate_ids(["D-wrong", "D-123", "D-123"], found) == ["D-123"]


def test_report_generates(tmp_path):
    example = {
        "generated_at_utc": "2026-10-11T00:00:00Z", "legal_version_label": "Original 2017",
        "legal_source": "legal/mdr.pdf", "selected_pdf_pages": [90],
        "device_profile": {"device_name": "Example"}, "model": "mock",
        "assessed_requirements": 0, "total_extracted_requirements": 0,
        "partial_run": False, "status_counts": {}, "findings": [],
        "limitations": [], "human_validated": False,
    }
    target = tmp_path / "report.md"
    write_markdown(example, target)
    assert "Not a declaration of conformity" in target.read_text()


def test_ask_abstains_when_model_citations_are_unverified(monkeypatch, capsys):
    passage = {
        "id": "L-verified",
        "text": "Risk management requirements in this source.",
        "meta": {"source": "legal/mdr.pdf", "page": 12, "block": 1},
    }
    monkeypatch.setattr(pipeline, "check_manifest", lambda: {})
    monkeypatch.setattr(
        pipeline, "hybrid_search",
        lambda question, kind, k: [passage] if kind == "legal" else [],
    )
    monkeypatch.setattr(
        pipeline, "llm_parse",
        lambda instructions, input_text, model_type: Answer(
            answer="Unsupported regulatory claim.", source_ids=["L-invented"], limitations=[]
        ),
    )

    pipeline.run_ask("What are the requirements?")

    output = capsys.readouterr().out
    assert "Unsupported regulatory claim." not in output
    assert "Insufficient evidence to provide a source-grounded answer." in output
    assert "L-invented" not in output


def test_ask_displays_answer_with_verified_citation(monkeypatch, capsys):
    passage = {
        "id": "L-verified",
        "text": "Risk management requirements in this source.",
        "meta": {"source": "legal/mdr.pdf", "page": 12, "block": 1},
    }
    monkeypatch.setattr(pipeline, "check_manifest", lambda: {})
    monkeypatch.setattr(
        pipeline, "hybrid_search",
        lambda question, kind, k: [passage] if kind == "legal" else [],
    )
    responses = iter([
        Answer(
            answer="The source discusses risk management.",
            source_ids=["L-verified"],
            limitations=[],
        ),
        AnswerSupportVerification(claims=[
            AnswerClaim(
                claim="The source discusses risk management.",
                supported=True,
                evidence=[ClaimEvidence(
                    source_id="L-verified",
                    exact_quote="Risk management requirements in this source.",
                )],
            )
        ]),
    ])
    monkeypatch.setattr(pipeline, "llm_parse", lambda *args: next(responses))

    pipeline.run_ask("What are the requirements?")

    output = capsys.readouterr().out
    assert "The source discusses risk management." in output
    assert "[L-verified] legal/mdr.pdf, PDF page 12" in output


def test_ask_abstains_when_claim_verifier_rejects_answer(monkeypatch, capsys):
    passage = {
        "id": "L-verified",
        "text": "Risk management requirements in this source.",
        "meta": {"source": "legal/mdr.pdf", "page": 12, "block": 1},
    }
    monkeypatch.setattr(pipeline, "check_manifest", lambda: {})
    monkeypatch.setattr(
        pipeline, "hybrid_search",
        lambda question, kind, k: [passage] if kind == "legal" else [],
    )
    responses = iter([
        Answer(
            answer="The source proves that the device is compliant.",
            source_ids=["L-verified"],
            limitations=[],
        ),
        AnswerSupportVerification(claims=[
            AnswerClaim(
                claim="The device is compliant.",
                supported=False,
                evidence=[],
            )
        ]),
    ])
    monkeypatch.setattr(pipeline, "llm_parse", lambda *args: next(responses))

    pipeline.run_ask("Is the device compliant?")

    output = capsys.readouterr().out
    assert "proves that the device is compliant" not in output
    assert "Insufficient evidence to provide a fully source-supported answer." in output


def test_answer_support_requires_valid_citations_and_exact_quotes():
    passages = [{
        "id": "L-verified",
        "text": "The manufacturer shall establish, document and maintain a risk management system.",
    }]
    supported = AnswerSupportVerification(claims=[
        AnswerClaim(
            claim="The manufacturer must maintain risk management.",
            supported=True,
            evidence=[ClaimEvidence(
                source_id="L-verified",
                exact_quote="establish, document and maintain a risk management system",
            )],
        )
    ])
    wrong_quote = AnswerSupportVerification(claims=[
        AnswerClaim(
            claim="The manufacturer must maintain risk management.",
            supported=True,
            evidence=[ClaimEvidence(source_id="L-verified", exact_quote="The device is compliant.")],
        )
    ])
    wrong_id = AnswerSupportVerification(claims=[
        AnswerClaim(
            claim="The manufacturer must maintain risk management.",
            supported=True,
            evidence=[ClaimEvidence(source_id="L-invented", exact_quote="risk management system")],
        )
    ])
    assert pipeline.answer_claims_are_supported(supported, passages)
    assert not pipeline.answer_claims_are_supported(wrong_quote, passages)
    assert not pipeline.answer_claims_are_supported(wrong_id, passages)
    assert not pipeline.answer_claims_are_supported(
        AnswerSupportVerification(claims=[]), passages
    )
