"""Check one claim from the terminal: python -m app.cli "Claim text"."""

import sys

from .budget import RunBudget
from .config import load_settings
from .agents import embed
from .retrievers.search import make_search_fn
from .run import run_check


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print('usage: python -m app.cli "claim text"')
        return 2
    settings = load_settings()
    budget = RunBudget(settings.max_cost_usd_per_run, settings.max_iterations)

    def show(event: dict) -> None:
        if event["type"] == "trace":
            print(f"[{event['step']}/{event['status']}] {event.get('message', '')}")

    report = run_check({"kind": "text", "text": " ".join(argv[1:])}, show, settings,
                       make_search_fn(settings, budget, embed_fn=embed), budget)
    for c in report.claims:
        print(f"\n{c.claim.text}\n  -> {c.label.value} ({c.confidence:.2f}): {c.answer}")
        for cit in c.citations:
            print(f"     [{cit.evidence_id}] \"{cit.quote}\"")
    print(f"\ncost ${budget.cost_usd:.4f}  tokens {budget.tokens_in}/{budget.tokens_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
