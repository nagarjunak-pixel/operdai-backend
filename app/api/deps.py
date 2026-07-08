"""API dependencies — auth middleware, tenant context, DB sessions."""

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.schemas.auth import TokenPayload
from app.services.auth import AuthService


async def get_db():
    """Yields a raw DB session (no tenant context)."""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


async def get_current_user_token(
    authorization: Annotated[str | None, Header()] = None,
) -> TokenPayload:
    """Extract and validate JWT from Authorization header."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header",
        )
    token = authorization.removeprefix("Bearer ")
    try:
        return AuthService.decode_token(token)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )


async def get_tenant_db(
    token: Annotated[TokenPayload, Depends(get_current_user_token)],
) -> AsyncSession:
    """
    Yields a DB session with RLS context set from the JWT.
    This is the primary dependency for all tenant-scoped endpoints.
    """
    async with async_session_factory() as session:
        try:
            # Set RLS session variables
            if token.agency_id:
                await session.execute(
                    text(f"SET app.current_agency_id = '{token.agency_id}'")
                )
            await session.execute(
                text(f"SET app.current_role = '{token.role}'")
            )
            if token.client_id:
                await session.execute(
                    text(f"SET app.current_client_id = '{token.client_id}'")
                )
            yield session
        finally:
            await session.close()


def require_role(*allowed_roles: str):
    """Dependency factory: requires the current user to have one of the specified roles."""
    async def _check(token: Annotated[TokenPayload, Depends(get_current_user_token)]):
        if token.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{token.role}' not authorized. Required: {allowed_roles}",
            )
        return token
    return _check


# Typed dependencies for cleaner route signatures
CurrentUser = Annotated[TokenPayload, Depends(get_current_user_token)]
TenantDB = Annotated[AsyncSession, Depends(get_tenant_db)]
RawDB = Annotated[AsyncSession, Depends(get_db)]

# Role-specific dependencies
PlatformAdmin = Annotated[TokenPayload, Depends(require_role("platform_admin"))]
AgencyAdmin = Annotated[TokenPayload, Depends(require_role("platform_admin", "agency_admin"))]
AgencyMember = Annotated[
    TokenPayload,
    Depends(require_role("platform_admin", "agency_admin", "agency_member")),
]


async def get_current_user(
    token: Annotated[TokenPayload, Depends(get_current_user_token)],
    db: AsyncSession = Depends(get_db),
):
    """Retrieve the User record matching the active token payload."""
    from sqlalchemy import select
    from uuid import UUID
    from app.models.user import User

    result = await db.execute(select(User).where(User.id == UUID(token.sub)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found or deactivated",
        )
    return user
