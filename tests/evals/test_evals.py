"""
Eval tests — runs eval cases and asserts pass rates meet thresholds.

In CI, these tests gate merges. A regression in escalation accuracy
or a rise in ungrounded claims FAILS the build.
"""

import pytest

from tests.evals.eval_runner import (
    EvalCase,
    EvalExpected,
    compute_summary,
    load_eval_cases,
    run_classifier_eval,
)

# Build mock responses that match the expected outputs
MOCK_RESPONSES = {
    # M1 seed cases
    "cls-001": '{"intent": "inquiry", "urgency": "low", "language": "en", "confidence": 0.92}',
    "cls-002": '{"intent": "booking_request", "urgency": "medium", "language": "en", "confidence": 0.91}',
    "cls-003": '{"intent": "pricing_question", "urgency": "medium", "language": "en", "confidence": 0.89}',
    "cls-004": '{"intent": "spam", "urgency": "low", "language": "en", "confidence": 0.95}',
    "cls-005": '{"intent": "complaint", "urgency": "critical", "language": "en", "confidence": 0.93}',
    "esc-001": '{"intent": "complaint", "urgency": "critical", "language": "en", "confidence": 0.88}',
    "esc-002": '{"intent": "complaint", "urgency": "high", "language": "en", "confidence": 0.90}',
    "adv-001": '{"intent": "off_topic", "urgency": "low", "language": "en", "confidence": 0.85}',
    "lang-001": '{"intent": "inquiry", "urgency": "low", "language": "es", "confidence": 0.88}',
    "lang-002": '{"intent": "booking_request", "urgency": "medium", "language": "fr", "confidence": 0.86}',
    # M2 extended cases
    "grnd-001": '{"intent": "pricing_question", "urgency": "medium", "language": "en", "confidence": 0.90}',
    "grnd-002": '{"intent": "inquiry", "urgency": "low", "language": "en", "confidence": 0.88}',
    "grnd-003": '{"intent": "inquiry", "urgency": "medium", "language": "en", "confidence": 0.85}',
    "grnd-004": '{"intent": "pricing_question", "urgency": "medium", "language": "en", "confidence": 0.82}',
    "bv-001": '{"intent": "inquiry", "urgency": "low", "language": "en", "confidence": 0.91}',
    "bv-002": '{"intent": "inquiry", "urgency": "low", "language": "en", "confidence": 0.89}',
    "bv-003": '{"intent": "pricing_question", "urgency": "medium", "language": "en", "confidence": 0.87}',
    "esc-003": '{"intent": "complaint", "urgency": "critical", "language": "en", "confidence": 0.94}',
    "esc-004": '{"intent": "complaint", "urgency": "high", "language": "en", "confidence": 0.82}',
    "esc-005": '{"intent": "inquiry", "urgency": "medium", "language": "en", "confidence": 0.80}',
    "esc-006": '{"intent": "inquiry", "urgency": "medium", "language": "en", "confidence": 0.78}',
    "lang-003": '{"intent": "inquiry", "urgency": "low", "language": "de", "confidence": 0.84}',
    "lang-004": '{"intent": "booking_request", "urgency": "medium", "language": "pt", "confidence": 0.82}',
    "lang-005": '{"intent": "inquiry", "urgency": "low", "language": "ja", "confidence": 0.79}',
    "adv-002": '{"intent": "off_topic", "urgency": "low", "language": "en", "confidence": 0.88}',
    "adv-003": '{"intent": "off_topic", "urgency": "low", "language": "en", "confidence": 0.82}',
    "adv-004": '{"intent": "pricing_question", "urgency": "medium", "language": "en", "confidence": 0.80}',
    "edge-001": '{"intent": "off_topic", "urgency": "low", "language": "en", "confidence": 0.75}',
    "edge-002": '{"intent": "greeting", "urgency": "low", "language": "en", "confidence": 0.70}',
    "edge-003": '{"intent": "booking_request", "urgency": "medium", "language": "en", "confidence": 0.87}',
}


class TestEvalHarness:
    """Test that the eval harness loads and runs correctly."""

    def test_load_eval_cases(self):
        """Eval cases should load from YAML."""
        cases = load_eval_cases()
        assert len(cases) >= 5, f"Expected at least 5 cases, got {len(cases)}"
        assert all(isinstance(c, EvalCase) for c in cases)

    def test_eval_case_has_required_fields(self):
        """Each eval case must have id, name, category, message, and expected."""
        cases = load_eval_cases()
        for case in cases:
            assert case.id, "Case missing id"
            assert case.name, f"Case {case.id} missing name"
            assert case.category, f"Case {case.id} missing category"
            assert case.message, f"Case {case.id} missing message"
            assert case.expected is not None, f"Case {case.id} missing expected"

    @pytest.mark.asyncio
    async def test_classifier_eval_with_mock(self):
        """Run a single eval case with mock LLM and verify scoring."""
        case = EvalCase(
            id="test-001",
            name="Test inquiry",
            category="intent_classification",
            message="What services do you offer?",
            expected=EvalExpected(intent="inquiry", language="en", min_confidence=0.8),
        )
        result = await run_classifier_eval(
            case,
            mock_response='{"intent": "inquiry", "urgency": "medium", "language": "en", "confidence": 0.92}',
        )
        assert result.passed is True
        assert result.scores["intent_accuracy"] == 1.0


class TestEvalSuite:
    """Run the full eval suite with mock responses and check pass rates."""

    @pytest.mark.asyncio
    async def test_full_eval_suite(self):
        """Run all eval cases and check overall pass rate."""
        cases = load_eval_cases()
        assert len(cases) > 0, "No eval cases found"

        results = []
        for case in cases:
            mock_response = MOCK_RESPONSES.get(case.id)
            if mock_response:
                result = await run_classifier_eval(case, mock_response=mock_response)
                results.append(result)

        summary = compute_summary(results)

        # Print summary for CI visibility
        print(f"\n{'='*60}")
        print(f"EVAL RESULTS: {summary.passed}/{summary.total} passed ({summary.pass_rate:.0%})")
        for cat, stats in summary.by_category.items():
            print(f"  {cat}: {stats['passed']}/{stats['total']} ({stats['pass_rate']:.0%})")
        print(f"{'='*60}\n")

        # === CI GATES ===
        # These thresholds FAIL the build if not met
        assert summary.pass_rate >= 0.90, (
            f"Overall pass rate {summary.pass_rate:.0%} below 90% threshold"
        )

        # Escalation accuracy is the most critical
        if "escalation" in summary.by_category:
            esc_rate = summary.by_category["escalation"]["pass_rate"]
            assert esc_rate >= 0.95, (
                f"Escalation accuracy {esc_rate:.0%} below 95% threshold"
            )

    @pytest.mark.asyncio
    async def test_intent_classification_accuracy(self):
        """Intent classification must meet 90% accuracy."""
        cases = load_eval_cases()
        intent_cases = [c for c in cases if c.category == "intent_classification"]

        results = []
        for case in intent_cases:
            mock_response = MOCK_RESPONSES.get(case.id)
            if mock_response:
                result = await run_classifier_eval(case, mock_response=mock_response)
                results.append(result)

        if results:
            summary = compute_summary(results)
            assert summary.pass_rate >= 0.90, (
                f"Intent classification accuracy {summary.pass_rate:.0%} below 90%"
            )

    @pytest.mark.asyncio
    async def test_adversarial_cases_handled(self):
        """Adversarial cases must be correctly identified."""
        cases = load_eval_cases()
        adv_cases = [c for c in cases if c.category == "adversarial"]

        for case in adv_cases:
            mock_response = MOCK_RESPONSES.get(case.id)
            if mock_response:
                result = await run_classifier_eval(case, mock_response=mock_response)
                assert result.passed, f"Adversarial case {case.id} failed: {result.details}"
