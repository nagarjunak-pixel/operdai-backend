"""Tests for auth service — password hashing, JWT tokens."""

import pytest

from app.services.auth import AuthService


class TestPasswordHashing:
    def test_hash_and_verify(self):
        password = "secure_password_123"
        hashed = AuthService.hash_password(password)
        assert AuthService.verify_password(password, hashed) is True

    def test_wrong_password_fails(self):
        hashed = AuthService.hash_password("correct_password")
        assert AuthService.verify_password("wrong_password", hashed) is False

    def test_hash_is_not_plaintext(self):
        password = "my_password"
        hashed = AuthService.hash_password(password)
        assert hashed != password


class TestJWTTokens:
    def test_create_and_decode_access_token(self):
        token = AuthService.create_access_token(
            user_id="test-user-123",
            role="agency_admin",
            agency_id="agency-456",
        )
        payload = AuthService.decode_token(token)
        assert payload.sub == "test-user-123"
        assert payload.role == "agency_admin"
        assert payload.agency_id == "agency-456"
        assert payload.type == "access"

    def test_create_and_decode_refresh_token(self):
        token = AuthService.create_refresh_token("test-user-123")
        payload = AuthService.decode_token(token)
        assert payload.sub == "test-user-123"
        assert payload.type == "refresh"

    def test_token_carries_client_id(self):
        token = AuthService.create_access_token(
            user_id="viewer-1",
            role="client_viewer",
            agency_id="agency-1",
            client_id="client-1",
        )
        payload = AuthService.decode_token(token)
        assert payload.client_id == "client-1"
        assert payload.role == "client_viewer"

    def test_invalid_token_raises(self):
        with pytest.raises(ValueError, match="Invalid token"):
            AuthService.decode_token("not.a.valid.token")

    def test_platform_admin_token_has_no_agency(self):
        token = AuthService.create_access_token(
            user_id="admin-1",
            role="platform_admin",
        )
        payload = AuthService.decode_token(token)
        assert payload.role == "platform_admin"
        assert payload.agency_id is None
