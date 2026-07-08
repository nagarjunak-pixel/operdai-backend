"""Auth service — password hashing, JWT token creation/validation, user CRUD."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import bcrypt
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import User
from app.schemas.auth import TokenPayload, TokenResponse, UserRegister


class AuthService:
    """Handles authentication: password hashing, JWT tokens, user lookup."""

    @staticmethod
    def hash_password(password: str) -> str:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    @staticmethod
    def verify_password(password: str, hashed: str) -> bool:
        return bcrypt.checkpw(password.encode(), hashed.encode())

    @staticmethod
    def create_access_token(
        user_id: str,
        role: str,
        agency_id: str | None = None,
        client_id: str | None = None,
    ) -> str:
        expire = datetime.now(UTC) + timedelta(
            minutes=settings.jwt_access_token_expire_minutes
        )
        payload = {
            "sub": user_id,
            "role": role,
            "agency_id": agency_id,
            "client_id": client_id,
            "exp": int(expire.timestamp()),
            "type": "access",
        }
        return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

    @staticmethod
    def create_refresh_token(user_id: str) -> str:
        expire = datetime.now(UTC) + timedelta(
            days=settings.jwt_refresh_token_expire_days
        )
        payload = {
            "sub": user_id,
            "exp": int(expire.timestamp()),
            "type": "refresh",
        }
        return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

    @staticmethod
    def decode_token(token: str) -> TokenPayload:
        try:
            payload = jwt.decode(
                token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
            )
            return TokenPayload(**payload)
        except jwt.ExpiredSignatureError:
            raise ValueError("Token has expired")
        except jwt.InvalidTokenError:
            raise ValueError("Invalid token")

    @staticmethod
    def create_token_response(user: User) -> TokenResponse:
        access_token = AuthService.create_access_token(
            user_id=str(user.id),
            role=user.role,
            agency_id=str(user.agency_id) if user.agency_id else None,
            client_id=str(user.client_id) if user.client_id else None,
        )
        refresh_token = AuthService.create_refresh_token(str(user.id))
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.jwt_access_token_expire_minutes * 60,
        )

    @staticmethod
    async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
        result = await db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_user_by_id(db: AsyncSession, user_id: UUID) -> User | None:
        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def create_user(db: AsyncSession, data: UserRegister) -> User:
        user = User(
            email=data.email,
            name=data.name,
            password_hash=AuthService.hash_password(data.password),
            role=data.role,
            agency_id=data.agency_id,
            client_id=data.client_id,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user
