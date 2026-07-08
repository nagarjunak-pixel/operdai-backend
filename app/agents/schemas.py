"""Agent I/O schemas — Pydantic models for every agent's input and output."""

from __future__ import annotations

from pydantic import BaseModel, Field

# === Classifier ===

class ClassifierInput(BaseModel):
    message: str
    conversation_history: list[dict] = Field(default_factory=list)


class ClassifierOutput(BaseModel):
    intent: str = Field(
        ...,
        description="One of: inquiry, booking_request, complaint, pricing_question, "
                     "follow_up, spam, off_topic, greeting, farewell, thank_you"
    )
    urgency: str = Field(
        ..., description="One of: low, medium, high, critical"
    )
    language: str = Field(
        ..., description="ISO 639-1 code, e.g., 'en', 'es', 'fr'"
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence in the classification"
    )


# === Qualifier ===

class QualifierInput(BaseModel):
    lead_data: dict
    conversation_history: list[dict]
    qualification_criteria: list[str] = Field(default_factory=list)


class QualifierOutput(BaseModel):
    lead_score: float = Field(ge=0.0, le=1.0)
    questions_to_ask: list[str] = Field(default_factory=list)
    gathered_info: dict = Field(default_factory=dict)
    status: str = Field(
        default="in_progress",
        description="One of: in_progress, qualified, not_qualified"
    )


# === KB Agent ===

class KBQueryInput(BaseModel):
    query: str
    client_id: str
    max_results: int = 5


class KBFact(BaseModel):
    content: str
    source_title: str
    source_id: str
    relevance_score: float = 0.0


class KBQueryOutput(BaseModel):
    facts: list[KBFact] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    query_understood: bool = True


# === Responder ===

class ResponderInput(BaseModel):
    conversation_history: list[dict]
    lead_message: str
    classifier_output: ClassifierOutput
    kb_facts: list[KBFact] = Field(default_factory=list)
    brand_voice: dict = Field(default_factory=dict)
    client_name: str = ""
    qualifier_questions: list[str] = Field(default_factory=list)


class ResponderOutput(BaseModel):
    message: str = Field(..., description="The draft reply to send to the lead")
    tone_match_score: float = Field(
        ge=0.0, le=1.0, default=0.8,
        description="How well the response matches the brand voice"
    )
    grounding_refs: list[str] = Field(
        default_factory=list,
        description="KB fact IDs used to generate this response"
    )
    reasoning: str = Field(
        default="", description="Why this response was crafted this way"
    )


# === Critic ===

class CriticInput(BaseModel):
    draft_message: str
    brand_voice: dict
    never_say_list: dict
    kb_facts: list[KBFact]
    conversation_history: list[dict]
    classifier_output: ClassifierOutput


class CriticIssue(BaseModel):
    type: str  # ungrounded_claim, never_say_violation, tone_mismatch, policy_violation
    description: str
    severity: str  # low, medium, high, critical


class CriticOutput(BaseModel):
    approved: bool
    issues: list[CriticIssue] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = ""


# === Supervisor ===

class SupervisorInput(BaseModel):
    conversation_id: str
    message_id: str
    client_id: str
    agency_id: str


class AgentStepResult(BaseModel):
    agent: str
    input_data: dict = Field(default_factory=dict)
    output_data: dict = Field(default_factory=dict)
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_cents: float = 0.0
    duration_ms: int = 0
    timestamp: str = ""


class SupervisorOutput(BaseModel):
    decision: str = Field(
        ..., description="One of: send, escalate, script_fallback, block"
    )
    confidence_score: float = Field(ge=0.0, le=1.0)
    policy_flags: list[str] = Field(default_factory=list)
    steps: list[AgentStepResult] = Field(default_factory=list)
    draft_message: str | None = None
    escalation_reason: str | None = None
    total_tokens: int = 0
    total_cost_cents: float = 0.0
