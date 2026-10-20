"""One fact-check run: normalize the input, run the pipeline, stream trace events."""

from __future__ import annotations

import uuid
from typing import Callable

from . import agents, llm, orchestrator, prompts
from .budget import RunBudget
from .config import Settings
from .schemas import FinalReport, InputType, NormalizedInput, Step, StepStatus

MAX_TEXT_CHARS = 20000
MAX_IMAGE_BYTES = 5 * 1024 * 1024


class RunInputError(Exception):
    """Bad or unusable input. code is one of the error codes in docs/api-contract.md."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _normalize(req: dict, emit: Callable[[dict], None], run_id: str) -> NormalizedInput:
    from . import inputs

    kind = req.get("kind")
    if any(not isinstance(req.get(f), (str, type(None))) for f in ("text", "url", "image_b64", "mime")):
        raise RunInputError("bad_input", "That request wasn't in the format I expected.")
    try:
        if kind == "text":
            text = (req.get("text") or "").strip()
            if not text:
                raise RunInputError("bad_input", "Please paste some text to check.")
            if len(text) > MAX_TEXT_CHARS:
                text = text[:MAX_TEXT_CHARS]
                orchestrator.trace(emit, run_id, Step.NORMALIZE, StepStatus.COMPLETED,
                                   message=f"Text was longer than {MAX_TEXT_CHARS} characters and was cut.")
            return NormalizedInput(input_type=InputType.TEXT, text=text)
        if kind == "url":
            return inputs.normalize_url(req.get("url") or "")
        if kind == "image":
            b64 = req.get("image_b64") or ""
            if len(b64) * 3 // 4 > MAX_IMAGE_BYTES:
                raise RunInputError("bad_input", "That image is too large (5 MB limit).")
            return inputs.normalize_image(b64, req.get("mime") or "")
    except inputs.InputError as e:
        raise RunInputError(e.code, e.message) from e
    raise RunInputError("bad_input", "Unsupported input kind.")


_ROLE_STEP = {"ocr": Step.NORMALIZE, "extract": Step.EXTRACT, "evidence": Step.RETRIEVE,
              "judge": Step.VERDICT, "review": Step.REVIEW}


def run_check(req: dict, emit: Callable[[dict], None], settings: Settings,
              search_fn: orchestrator.SearchFn, budget: RunBudget) -> FinalReport:
    run_id = req.get("run_id") or uuid.uuid4().hex[:12]
    calls = llm.begin_run()
    seen, announced = 0, set()

    def notify() -> None:
        nonlocal seen
        for c in calls.calls[seen:]:
            if c.fallback_used and c.model not in announced:
                announced.add(c.model)
                orchestrator.trace(emit, run_id, _ROLE_STEP.get(c.role, Step.VERDICT), StepStatus.COMPLETED,
                                   message=f"Switched to the backup model {c.model}")
        seen = len(calls.calls)

    def emit_noting(event: dict) -> None:
        notify()
        emit(event)

    agents.set_usage_sink(budget.add_usage)
    orchestrator.trace(emit_noting, run_id, Step.NORMALIZE, StepStatus.STARTED)
    inp = _normalize(req, emit_noting, run_id)
    orchestrator.trace(emit_noting, run_id, Step.NORMALIZE, StepStatus.COMPLETED, message=inp.input_type.value)
    report = orchestrator.check_input(inp, search_fn, settings, budget, emit_noting, run_id)
    notify()
    report.models_used = calls.models_used
    report.prompt_version = getattr(prompts, "PROMPT_VERSION", None)
    return report
