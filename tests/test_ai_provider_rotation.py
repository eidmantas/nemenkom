import pytest

from services.scraper.ai.parser import (
    create_parsing_prompt,
    get_ai_agent,
    get_model_rotation,
    run_agent_prompt,
    validate_ai_output,
)


@pytest.mark.ai_integration
def test_ai_provider_rotation_smoke():
    """
    Lean smoke test that cycles through the configured AI rotation and reports per-model status.

    This test passes if at least one provider/model returns valid output.
    """
    rotation = get_model_rotation()
    failures: list[str] = []
    successes: list[str] = []

    test_input = "Test Village"
    prompt = create_parsing_prompt(test_input)

    for provider_name, model_id in rotation:
        label = f"{provider_name}:{model_id}"
        try:
            agent = get_ai_agent(provider_name, model_id)
            response = run_agent_prompt(agent, prompt)
            output = (
                getattr(response, "output", None)
                or getattr(response, "data", None)
                or getattr(response, "result", None)
            )
            if output is None:
                raise ValueError("Missing response output")
            parsed_json = output.model_dump() if hasattr(output, "model_dump") else output
            is_valid, error_msg = validate_ai_output(parsed_json)
            if not is_valid:
                raise ValueError(f"Invalid output: {error_msg}")
            successes.append(label)
            print(f"[OK] {label}")
        except Exception as exc:
            failures.append(f"{label} -> {exc}")
            print(f"[FAIL] {label} -> {exc}")

    print(f"AI rotation summary: {len(successes)} OK, {len(failures)} failed")

    assert successes, "No AI providers responded successfully in rotation smoke test."
