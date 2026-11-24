"""The figures agent's view of the template, its advice after a save, its
coverage receipt, the workbench decision and the definitions."""
from __future__ import annotations

from collections import Counter

import pytest
from pydantic_ai.messages import BinaryContent, ModelRequest, ToolReturnPart

from app import db
from app.agents import history, workbench
from app.catalog import definitions, lookup
from app.extraction import coverage, feedback, outline as ol, outline_text
from app.extraction.coverage import CoverageLine
from tests import reading_fakes as fakes
from tests.conftest import make_run

SOFP = "mfrs-company-sofp-cunoncu-v1"


@pytest.fixture
def sofp():
    run_id = make_run()
    with db.connect() as conn:
        family = lookup.run_family(conn, run_id)
        return ol.build(conn, family), lookup.template_concepts(conn, SOFP), lookup.edges_for(conn, {SOFP})


def test_every_field_has_its_own_id_and_a_repeated_label_is_told_apart_by_its_path(sofp):
    outline, concepts, _ = sofp
    assert len(outline.fields) == len(concepts) == len(outline.by_uuid)
    assert all(outline.get(f.id.lower()) is f for f in outline.fields.values())
    repeated = Counter(c.plain_label.lower() for c in concepts if c.kind != "ABSTRACT")
    assert sum(n for n in repeated.values() if n > 1) > 80          # the trap v1 fell into
    places = Counter(f.where for f in outline.fields.values() if f.kind != ol.HEADING)
    assert [where for where, n in places.items() if n > 1] == []
    current = outline.fields["FP-s141"]
    assert current.where == ("Current assets › Trade and other current receivables › Current trade receivables › "
                             "Trade receivables due from holding company")
    assert outline.fields["FP-s99"].where.startswith("Non-current assets › Trade and other non-current receivables")


def test_headings_are_marked_and_every_total_names_its_parts_with_their_signs(sofp):
    outline, concepts, edges = sofp
    for c in concepts:
        f = outline.for_uuid(c.concept_uuid)
        assert (f.kind == ol.HEADING) == (c.kind == "ABSTRACT")
        if c.concept_uuid in edges:
            assert f.kind == ol.TOTAL
            assert sorted((outline.for_uuid(ch).id, k) for ch, k in edges[c.concept_uuid]) == sorted(f.parts)
    assert ("FP-42", -1.0) in outline.fields["FP-47"].parts     # total equity subtracts treasury shares
    assert outline.overall_sign("FP-42") == (-1.0, "FP-47")


def test_a_face_formula_row_carries_its_sub_sheet_lines(sofp):
    outline, _, _ = sofp
    ppe = outline.fields["FP-s39"]
    assert ppe.on_face and ppe.face_label == "Property, plant and equipment" and "FP-s39" in outline.roots["SOFP"]
    assert "FP-s28" in outline.descendants("FP-s39") and outline.fields["FP-s28"].parent == "FP-s39"
    text = outline_text.render(outline, "SOFP")
    assert "FP-s39 total (face row): *Property, plant and equipment = FP-s20 + FP-s26" in text
    assert "FP-7 heading: Non-current assets" in text
    assert "FP-47 total: *Total equity = FP-41 - FP-42 + FP-46" in text
    assert all(fid in text for fid, f in outline.fields.items() if f.kind != ol.HEADING)
    assert len(text) < 40_000     # fits the first message


def _saved(outline, values: dict) -> dict:
    return {(outline.fields[fid].concept_uuid, period): {"value": v, "stated_value": None, "children_status": None}
            for (fid, period), v in values.items()}


def test_advice_after_a_save_names_signs_double_bookings_catch_alls_and_empty_face_rows(sofp):
    outline, _, _ = sofp
    saved = _saved(outline, {("FP-42", "CY"): -50.0, ("FP-41", "CY"): -10.0, ("FP-s139", "CY"): 700.0,
                             ("FP-s181", "CY"): 700.0, ("FP-s404", "CY"): 30.0, ("FP-s147", "CY"): 30.0})
    saved[(outline.fields["FP-s39"].concept_uuid, "CY")] = {"value": 900.0, "stated_value": 900.0,
                                                           "children_status": "aggregate_only"}
    points = feedback.points(outline, saved, [("FP-42", "CY"), ("FP-41", "CY"), ("FP-s139", "CY"),
                                              ("FP-s147", "CY"), ("FP-s39", "CY")], ("CY", "PY"))
    text = "\n".join(points)
    assert "FP-42 Treasury shares is saved as -50 for this year, but Total equity subtracts this field" in text
    assert "FP-41 Retained earnings is saved as -10 for this year, so it reduces Total equity" in text
    # Cash and receivables both add into total assets, so the same amount there counts twice; an asset and a
    # liability (other receivables and trade payables, 30 each) share no total, so they are not named.
    assert "FP-s139 Trade receivables and FP-s181 Cash in hand both hold 700 for this year" in text
    assert "FP-s404" not in text
    assert "FP-s147 Other current trade receivables is filled while the dedicated fields beside it are empty: " \
           "FP-s140 Trade receivables due from contract customers" in text
    assert "FP-s39 Property, plant and equipment is a face row fed by its sub-sheet lines" in text
    assert "replaced by the formula in mTool" in text
    assert feedback.points(outline, _saved(outline, {("FP-s28", "CY"): 5.0}), [("FP-s28", "CY")],
                           ("CY", "PY")) == []


def test_coverage_finds_the_printed_lines_and_tolerates_wording():
    contents = {2: fakes.good_page(2)}
    printed = coverage.printed_lines(contents, [2])
    assert [(p.label, p.page) for p in printed] == [("Plant and equipment", 2), ("Trade payables", 2)]
    report = [CoverageLine(label="Plant & equipment (Note 1)", page=2, action="written", fields=["FP-s28"])]
    assert [m.label for m in coverage.unaccounted(printed, report)] == ["Trade payables"]
    twice = [coverage.Printed("Lease liabilities", 6, 0), coverage.Printed("Lease liabilities", 6, 1)]
    one = [CoverageLine(label="Lease liabilities", page=6, action="skipped", reason="test")]
    missing = coverage.unaccounted(twice, one)
    assert coverage.describe(missing[0], twice) == "'Lease liabilities' (page 6, the second time it is printed there)"


def test_one_place_decides_the_code_workbench():
    on = {"code_workbench": True, "claude_sandbox_real_documents": False}
    assert workbench.decide("gpt-6-luna", settings=on).on
    assert not workbench.decide("gpt-6-luna", wanted=False, settings=on).on
    off = workbench.decide("gpt-6-luna", settings={**on, "code_workbench": False})
    assert not off.on and "Settings page" in off.why
    claude = workbench.decide("claude-sonnet-4-6", settings=on)
    assert not claude.on and "test documents" in claude.why
    assert workbench.decide("claude-sonnet-4-6", settings={**on, "claude_sandbox_real_documents": True}).on


def test_the_gateway_gives_claude_no_workbench(monkeypatch):
    monkeypatch.setenv("LLM_PROXY_URL", "https://gateway.example/v1")
    settings = {"code_workbench": True, "claude_sandbox_real_documents": True}
    assert not workbench.decide("claude-sonnet-4-6", settings=settings).on
    assert workbench.decide("gpt-6-luna", settings=settings).on


def test_official_definitions_by_field_and_by_words(sofp):
    outline, _, _ = sofp
    text = definitions.definition_of("mfrs", outline.fields["FP-s141"].primary_concept)
    assert "holding company" in text.lower()
    assert definitions.search("mfrs", "trade receivables")[0]["label"]
    with pytest.raises(ValueError):
        definitions.load("ifrs")


def _picture(call_id: str) -> ModelRequest:
    picture = ["PDF page 1:", BinaryContent(b"x", media_type="image/png")]
    return ModelRequest(parts=[ToolReturnPart("view_pages", picture, tool_call_id=call_id)])


def test_page_pictures_stay_until_the_first_save_then_are_cut_in_one_go():
    trimmer = history.Trimmer(text_tools=frozenset(), saved=lambda messages: any(
        isinstance(p, ToolReturnPart) and p.tool_name == "save_figures" for m in messages for p in m.parts),
        picture_budget=4, dropped_note="dropped")
    pictures = [_picture(f"p{i}") for i in range(6)]
    assert trimmer(pictures) == pictures                       # nothing goes before the first save
    saved = pictures + [ModelRequest(parts=[ToolReturnPart("save_figures", "Saved 1", tool_call_id="s")])]
    shaped = trimmer(saved)
    kept = [m for m in shaped[:6] if any(isinstance(i, BinaryContent) for i in m.parts[0].content)]
    assert len(kept) == 2 and shaped[0].parts[0].content[-1] == "dropped"
    assert trimmer(saved + [_picture("p6")])[5] is shaped[5]   # under the budget again: nothing more is cut


def test_separately_printed_lines_that_end_up_in_one_face_field_get_advice(sofp):
    from types import SimpleNamespace

    from app.extraction import checking
    from app.extraction.coverage import CoverageLine

    outline = sofp[0] if isinstance(sofp, tuple) else sofp
    deps = SimpleNamespace(outline=outline, statement_pages=[5])
    face_lines = [CoverageLine(label="Plant and equipment", page=5, action="written", fields=["FP-s28"]),
                  CoverageLine(label="Motor vehicles", page=5, action="written", fields=["FP-s24"])]
    advice = checking.shared_face_fields(deps, face_lines)
    assert len(advice) == 1 and "FP-s39" in advice[0] and "Motor vehicles" in advice[0]
    # Note lines (not on the statement page) and a single line per face field get no advice.
    note_lines = [CoverageLine(label=x.label, page=17, action="written", fields=x.fields) for x in face_lines]
    assert checking.shared_face_fields(deps, note_lines) == []
    assert checking.shared_face_fields(deps, face_lines[:1]) == []
