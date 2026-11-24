"""A sideways or upside-down page is turned upright. The model names the edge
the top of the letters points to, code works out the turn, and a turned page
is looked at once more, turned, to confirm it reads upright. Fake models."""
from __future__ import annotations

import json

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app import db
from app.reading.content import PageContent
from tests import reading_fakes as fakes
from tests.test_reading_pages import make_reading_run, stored_pages, transcribe_only


def test_the_edge_the_text_faces_gives_the_clockwise_turn():
    page = {"folio": None, "kind": "notes", "blocks": [{"type": "paragraph", "text": "x"}]}
    assert [PageContent(**page, text_top=t).rotation for t in ("top", "left", "bottom", "right")] == [0, 90, 180, 270]
    # Content stored before the edge was asked for keeps its turn.
    assert PageContent(**page, rotation=270).rotation == 270
    assert "rotation" not in json.dumps(PageContent.model_json_schema()["properties"])


def _model(text_top: str, seen_turned: str, prompts: list[str]):
    """Transcribes every page as facing `text_top`; the check of a turned page sees `seen_turned`."""
    def answer(messages, info: AgentInfo) -> ModelResponse:
        prompt = next(item for m in messages for p in getattr(m, "parts", [])
                      for item in (p.content if isinstance(getattr(p, "content", None), list) else [])
                      if isinstance(item, str))
        prompts.append(prompt)
        if "turned" in prompt:
            args = {"text_top": seen_turned}
        else:
            args = {**fakes.good_page(fakes.page_of(messages)), "text_top": text_top}
            args.pop("rotation")
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, json.dumps(args))])
    return FunctionModel(answer)


async def test_a_turn_the_check_contradicts_is_corrected_and_recorded():
    run_id = make_reading_run(fakes.build_pdf(blank_last=False))
    prompts: list[str] = []
    # Read as facing right (270); turned 270 it is still upside down, so the real turn is 90.
    await transcribe_only(run_id, _model("right", "bottom", prompts))
    content, error = stored_pages(run_id)[1]
    assert error is None
    assert (content["rotation"], content["text_top"], content["turn_corrected_from"]) == (90, "left", 270)
    assert sum("turned 270 degrees" in p for p in prompts) == 3
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM model_calls WHERE run_id = ?", (run_id,)).fetchone()[0] == 6


async def test_a_confirmed_turn_is_kept_and_an_upright_page_needs_no_check():
    run_id = make_reading_run(fakes.build_pdf(blank_last=False))
    prompts: list[str] = []
    await transcribe_only(run_id, _model("left", "top", prompts))
    content = stored_pages(run_id)[2][0]
    assert (content["rotation"], content["text_top"]) == (90, "left") and "turn_corrected_from" not in content

    upright = make_reading_run(fakes.build_pdf(blank_last=False))
    prompts.clear()
    await transcribe_only(upright, _model("top", "top", prompts))
    assert stored_pages(upright)[3][0]["rotation"] == 0
    assert not any("turned" in p for p in prompts)


async def test_a_failed_turn_check_keeps_the_transcription_with_its_first_turn_and_records_the_check():
    from app.reading.transcribe import records_dir

    run_id = make_reading_run(fakes.build_pdf(blank_last=False))
    prompts: list[str] = []
    # The check answers with an edge that does not exist, twice: its answer is malformed.
    await transcribe_only(run_id, _model("right", "sideways", prompts))
    content, error = stored_pages(run_id)[1]
    assert error is None and content["rotation"] == 270 and "turn_corrected_from" not in content
    records = [json.loads(p.read_text()) for p in records_dir(run_id).glob("page-001-*.json")]
    assert len(records) == 1 and records[0]["status"] == "read"
    check = records[0]["turn_check"]
    assert check["error"].startswith("UnexpectedModelBehavior")
    assert any("turned 270 degrees" in json.dumps(m) for m in check["messages"])
    # The transcription's own messages stay whole beside the check's.
    assert not any("turned 270 degrees" in json.dumps(m) for m in records[0]["messages"])


async def test_a_good_turn_check_keeps_its_messages_in_the_page_record():
    from app.reading.transcribe import records_dir

    run_id = make_reading_run(fakes.build_pdf(blank_last=False))
    await transcribe_only(run_id, _model("left", "top", []))
    record = json.loads(next(records_dir(run_id).glob("page-001-*.json")).read_text())
    assert record["turn_check"]["error"] is None
    assert any("turned 90 degrees" in json.dumps(m) for m in record["turn_check"]["messages"])
