"""Stage 7 Research: report builder murni (offline, tanpa DB)."""

from uuid import uuid4

from jarvis.knowledge.evaluation import evaluate_answer
from jarvis.knowledge.retrieval import Evidence
from jarvis.research.service import MAX_REPORT_CHARS, build_report


def ev(i, text="fakta penting tentang kopi tubruk"):
    return Evidence(f"S{i}", f"Dokumen {i}", f"paragraf {i}", text)


def test_report_carries_labels_and_provenance():
    report = build_report(goal="apa itu kopi?", evidence=[ev(1), ev(2)], run_id=uuid4(), attempt=1)
    assert "[S1]" in report and "[S2]" in report
    assert "Dokumen 1 — paragraf 1" in report
    verdict = evaluate_answer(
        answer=report,
        sources=[{"label": "S1"}, {"label": "S2"}],
        supported=2,
        total=2,
    )
    assert verdict.passed


def test_report_is_bounded():
    big = [ev(i, "x" * 2000) for i in range(1, 10)]
    report = build_report(goal="g", evidence=big, run_id=uuid4(), attempt=3)
    assert len(report) <= MAX_REPORT_CHARS


def test_empty_evidence_yields_no_citation():
    report = build_report(goal="g", evidence=[], run_id=uuid4(), attempt=1)
    assert "[S1]" not in report
