"""
Eval Harness — runs evaluation cases against the agent pipeline and scores results.

Eval cases are defined in YAML files under tests/evals/cases/.
Each case specifies an input message, client config, expected outputs, and scoring criteria.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from app.agents.classifier import ClassifierAgent
from app.agents.llm import MockProvider
from app.agents.schemas import ClassifierInput, ClassifierOutput


class EvalExpected(BaseModel):
    """Expected outputs for an eval case."""
    intent: str | None = None
    urgency: str | None = None
    language: str | None = None
    should_escalate: bool | None = None
    should_contain: list[str] = Field(default_factory=list)
    should_not_contain: list[str] = Field(default_factory=list)
    grounding_required: bool = False
    min_confidence: float | None = None
    decision: str | None = None


class EvalCase(BaseModel):
    """A single evaluation case."""
    id: str
    name: str
    description: str = ""
    category: str  # intent_classification, grounding, escalation, brand_voice, adversarial
    message: str
    conversation_history: list[dict] = Field(default_factory=list)
    client_config: dict = Field(default_factory=dict)
    kb_facts: list[dict] = Field(default_factory=list)
    expected: EvalExpected


class EvalScore(BaseModel):
    """Score for a single eval case."""
    case_id: str
    case_name: str
    category: str
    passed: bool
    scores: dict = Field(default_factory=dict)
    details: str = ""
    actual: dict = Field(default_factory=dict)


class EvalSummary(BaseModel):
    """Summary of all eval results."""
    total: int = 0
    passed: int = 0
    failed: int = 0
    pass_rate: float = 0.0
    by_category: dict[str, dict] = Field(default_factory=dict)
    results: list[EvalScore] = Field(default_factory=list)


def load_eval_cases(cases_dir: str | None = None) -> list[EvalCase]:
    """Load all eval cases from YAML files."""
    if cases_dir is None:
        cases_dir = str(Path(__file__).parent / "cases")

    cases = []
    cases_path = Path(cases_dir)
    if not cases_path.exists():
        return cases

    for yaml_file in sorted(cases_path.glob("*.yaml")):
        with open(yaml_file) as f:
            data = yaml.safe_load(f)
            if isinstance(data, list):
                for item in data:
                    cases.append(EvalCase(**item))
            elif isinstance(data, dict) and "cases" in data:
                for item in data["cases"]:
                    cases.append(EvalCase(**item))

    return cases


async def run_classifier_eval(
    case: EvalCase,
    mock_response: str | None = None,
) -> EvalScore:
    """
    Run a classifier eval case and score the result.

    If mock_response is provided, use it instead of calling the real LLM.
    """
    # For testing, use mock provider with the expected output
    if mock_response:
        provider = MockProvider(responses={"classifier": mock_response})
    else:
        # In CI with real API: use real provider
        from app.agents.llm import get_llm_provider
        provider = get_llm_provider()

    classifier = ClassifierAgent(llm=provider)
    input_data = ClassifierInput(
        message=case.message,
        conversation_history=case.conversation_history,
    )

    output, step = await classifier.run(input_data)

    # Score
    scores = {}
    issues = []

    if output and isinstance(output, ClassifierOutput):
        actual = output.model_dump()

        # Intent accuracy
        if case.expected.intent:
            intent_correct = output.intent == case.expected.intent
            scores["intent_accuracy"] = 1.0 if intent_correct else 0.0
            if not intent_correct:
                issues.append(f"Intent: expected={case.expected.intent}, got={output.intent}")

        # Urgency
        if case.expected.urgency:
            urgency_correct = output.urgency == case.expected.urgency
            scores["urgency_accuracy"] = 1.0 if urgency_correct else 0.0

        # Language
        if case.expected.language:
            lang_correct = output.language == case.expected.language
            scores["language_accuracy"] = 1.0 if lang_correct else 0.0

        # Confidence threshold
        if case.expected.min_confidence is not None:
            conf_ok = output.confidence >= case.expected.min_confidence
            scores["confidence_threshold"] = 1.0 if conf_ok else 0.0
            if not conf_ok:
                issues.append(
                    f"Confidence: expected >= {case.expected.min_confidence}, got {output.confidence}"
                )
    else:
        actual = {"error": "No structured output"}
        scores["intent_accuracy"] = 0.0
        issues.append("Failed to get structured output")

    passed = all(v >= 0.5 for v in scores.values()) and len(issues) == 0

    return EvalScore(
        case_id=case.id,
        case_name=case.name,
        category=case.category,
        passed=passed,
        scores=scores,
        details="; ".join(issues) if issues else "All checks passed",
        actual=actual,
    )


def compute_summary(results: list[EvalScore]) -> EvalSummary:
    """Compute aggregate summary from eval results."""
    total = len(results)
    passed = sum(1 for r in results if r.passed)

    by_category: dict[str, dict] = {}
    for r in results:
        cat = r.category
        if cat not in by_category:
            by_category[cat] = {"total": 0, "passed": 0}
        by_category[cat]["total"] += 1
        if r.passed:
            by_category[cat]["passed"] += 1

    for cat in by_category:
        t = by_category[cat]["total"]
        p = by_category[cat]["passed"]
        by_category[cat]["pass_rate"] = p / t if t > 0 else 0.0

    return EvalSummary(
        total=total,
        passed=passed,
        failed=total - passed,
        pass_rate=passed / total if total > 0 else 0.0,
        by_category=by_category,
        results=results,
    )
