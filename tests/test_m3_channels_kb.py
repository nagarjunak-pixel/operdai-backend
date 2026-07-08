"""Tests for M3 — Channels and KB Embedding features."""

import math
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.kb_agent import KBAgent
from app.services.channels import (
    parse_twilio_sms,
    parse_twilio_whatsapp,
    verify_twilio_signature,
)
from app.services.embeddings import chunk_text, get_mock_embedding


class TestDocumentChunking:
    """Test text chunking utilities."""

    def test_empty_text(self):
        assert chunk_text("") == []
        assert chunk_text("   ") == []

    def test_small_text_single_chunk(self):
        text = "This is a small paragraph."
        chunks = chunk_text(text, chunk_size=100)
        assert chunks == [text]

    def test_chunk_splitting(self):
        text = (
            "Paragraph one is here.\n\n"
            "Paragraph two is slightly longer and contains more words.\n\n"
            "Paragraph three is also here."
        )
        # Set chunk_size small to force split
        chunks = chunk_text(text, chunk_size=40, chunk_overlap=10)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk) <= 100  # Sentence boundaries might make it slightly larger
            assert len(chunk.strip()) > 0


class TestMockEmbeddings:
    """Test mock embedding generator."""

    def test_vector_dimensions_and_types(self):
        vector = get_mock_embedding("Hello world")
        assert isinstance(vector, list)
        assert len(vector) == 1536
        assert all(isinstance(x, float) for x in vector)

    def test_determinism(self):
        text = "This is a test document content."
        vec1 = get_mock_embedding(text)
        vec2 = get_mock_embedding(text)
        assert vec1 == vec2

    def test_different_texts_different_vectors(self):
        vec1 = get_mock_embedding("Text A")
        vec2 = get_mock_embedding("Text B")
        assert vec1 != vec2

    def test_normalization(self):
        vector = get_mock_embedding("Standard text")
        norm = sum(x * x for x in vector)
        assert math.isclose(norm, 1.0, rel_tol=1e-5)


class TestTwilioChannels:
    """Test Twilio message parsing and verification."""

    def test_verify_signature(self):
        # Example from Twilio docs
        url = "https://mycompany.com/myapp.php?foo=1&bar=2"
        params = {
            "CallSid": "CA1234567890ABCDE",
            "From": "+14158675309",
            "To": "+14158675310",
        }
        token = "12345"

        # Dynamically compute signature to match twilio spec
        import base64
        import hashlib
        import hmac
        data = url
        for key in sorted(params.keys()):
            data += key + params[key]
        expected_sig = base64.b64encode(
            hmac.new(token.encode("utf-8"), data.encode("utf-8"), hashlib.sha1).digest()
        ).decode("utf-8")

        assert verify_twilio_signature(url, params, expected_sig, token) is True
        assert verify_twilio_signature(url, params, "wrong-sig", token) is False

    def test_parse_whatsapp(self):
        payload = {
            "From": "whatsapp:+15551234",
            "To": "whatsapp:+15555678",
            "Body": "Hello from WhatsApp",
            "MessageSid": "SM1111",
            "ProfileName": "Alice",
        }
        parsed = parse_twilio_whatsapp(payload)
        assert parsed["external_id"] == "+15551234"
        assert parsed["content"] == "Hello from WhatsApp"
        assert parsed["channel"] == "whatsapp"
        assert parsed["name"] == "Alice"
        assert parsed["phone"] == "+15551234"

    def test_parse_sms(self):
        payload = {
            "From": "+15551234",
            "To": "+15555678",
            "Body": "Hello SMS",
            "MessageSid": "SM2222",
        }
        parsed = parse_twilio_sms(payload)
        assert parsed["external_id"] == "+15551234"
        assert parsed["content"] == "Hello SMS"
        assert parsed["channel"] == "sms"
        assert parsed["phone"] == "+15551234"


class TestKBAgentSearch:
    """Test KBAgent search fallback and pgvector query building."""

    @pytest.mark.asyncio
    async def test_search_kb_fallback_to_keyword(self):
        # Test KBAgent.search_kb when no chunks are found (fallback to documents)
        agent = KBAgent()
        client_id = str(uuid.uuid4())

        # Mock KBDocument
        mock_doc = MagicMock()
        mock_doc.id = uuid.uuid4()
        mock_doc.title = "Company FAQ"
        mock_doc.content = "Our office is located in San Francisco and we are open 9am to 5pm."
        mock_doc.doc_type = "faq"

        mock_db_result = MagicMock()
        # First query count returns 0
        # Second query returns doc
        mock_db_result.scalar.return_value = 0
        mock_db_result.scalars.return_value.all.return_value = [mock_doc]

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_db_result

        with patch("app.agents.kb_agent.async_session_factory") as mock_session_factory:
            mock_session_factory.return_value.__aenter__.return_value = mock_db

            results = await agent.search_kb(query="office hours location", client_id=client_id)

            assert len(results) == 1
            assert results[0]["source_title"] == "Company FAQ"
            assert "office" in results[0]["content"].lower()
            assert results[0]["relevance"] > 0
