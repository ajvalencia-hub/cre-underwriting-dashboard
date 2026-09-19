"""P1: classifier regression — an Offering Memorandum that never once uses
the literal phrase "offering memorandum" (a real, observed broker template:
pure marketing + fact sheet + zoning + photo pages, no financials at all)
used to lose to "rent_roll" purely from scattered generic real-estate
boilerplate ("Unit Count", "SF") on its fact-sheet page, at a CONFIDENT
score (0.31, well clear of the ambiguity margin) — so it never even reached
the LLM fallback. Traced from an actual deal package.

Fix has three parts, each covered below: word-boundary keyword matching (no
more "sf" false-hits inside unrelated substrings), a broader OM keyword set
covering common section headers, and a higher confidence floor so a handful
of scattered hits can't masquerade as a clear win. Also checks the fix
didn't regress plain rent-roll/T-12 classification.
"""

from app.services import document_classifier
from tests.extraction_corpus import builders


def test_marketing_only_om_classifies_correctly(tmp_path):
    path = tmp_path / "om.pdf"
    builders.build_marketing_om_without_literal_phrase_pdf(path)

    result = document_classifier.classify_document(path, path.name)

    assert result["documentType"] == "offering_memorandum"
    assert result["confidence"] >= 0.6


def test_word_boundary_matching_ignores_substring_false_hits():
    """"sf" must match the real standalone token ("5,677 SF") but NOT as a
    substring inside an unrelated word."""
    scores_with_hit = document_classifier._score_keywords(
        "Bldg Area: 5,677 SF", {"rent_roll": {"sf"}}
    )
    assert scores_with_hit["rent_roll"] == 1.0

    scores_without_hit = document_classifier._score_keywords(
        "This is a misfit classifieds ad", {"rent_roll": {"sf"}}
    )
    assert scores_without_hit["rent_roll"] == 0.0


def test_yardi_rent_roll_still_classifies_as_rent_roll(tmp_path):
    path = tmp_path / "rent_roll.xlsx"
    builders.build_yardi_rent_roll(path)

    result = document_classifier.classify_document(path, path.name)
    assert result["documentType"] == "rent_roll"


def test_yardi_t12_still_classifies_as_t12(tmp_path):
    path = tmp_path / "t12.xlsx"
    builders.build_yardi_t12(path)

    result = document_classifier.classify_document(path, path.name)
    assert result["documentType"] == "t12_operating_statement"


def test_om_titled_doc_with_a_real_rent_roll_table_is_reported_as_ambiguous(tmp_path):
    """build_broker_om_pdf is genuinely ambiguous content — an "Offering
    Memorandum" title banner over a real 5-row, 2-page Unit/Tenant/SF/Rent
    table. The dominant signal (a real table worth deterministic extraction)
    correctly wins on raw score, but the higher confidence floor must catch
    that this is a close call rather than reporting false certainty."""
    path = tmp_path / "om_with_table.pdf"
    builders.build_broker_om_pdf(path)

    result = document_classifier.classify_document(path, path.name)
    assert result["documentType"] == "rent_roll"
    assert result["confidence"] < 0.6
    assert "ambiguous" in result["rationale"].lower()


def test_weak_confident_score_no_longer_reports_as_clearly_ahead():
    """A handful of scattered hits (well under the new confidence floor)
    must not be reported with a "clearly ahead" rationale — that's exactly
    the false-confidence pattern that let the real bug through un-flagged."""
    scores = {"rent_roll": 0.31, "t12_operating_statement": 0.05, "offering_memorandum": 0.09}
    top2 = document_classifier._best_two(scores)
    top_type, top_score = top2[0]
    assert top_score < document_classifier._MIN_CONFIDENT_SCORE
