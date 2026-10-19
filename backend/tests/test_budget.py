from app.budget import RunBudget


def test_cost_cap_and_unknown_model_default():
    b = RunBudget(max_cost_usd=0.01, max_iterations=3)
    b.add_usage("gemini-2.5-flash", 10_000, 1_000)
    assert round(b.cost_usd, 6) == 0.0055 and not b.exhausted
    b.add_usage("mystery-model", 1_000, 1_000)
    assert b.cost_usd > 0.0055 + 0.0112 and b.exhausted
    assert (b.tokens_in, b.tokens_out) == (11_000, 2_000)


def test_repeat_queries_blocked_after_normalizing():
    b = RunBudget(1, 3)
    assert b.register_query("Bank of England  rates?")
    assert not b.register_query("bank of england, RATES")
    assert b.register_query("bank of england rates 2024")
