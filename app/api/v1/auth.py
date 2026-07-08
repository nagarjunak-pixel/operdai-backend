"""Auth API routes — register, login, refresh, me."""

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, RawDB
from app.schemas.auth import TokenRefresh, TokenResponse, UserLogin, UserRegister, UserResponse
from app.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(data: UserRegister, db: RawDB):
    """Register a new user."""
    existing = await AuthService.get_user_by_email(db, data.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    user = await AuthService.create_user(db, data)
    return AuthService.create_token_response(user)


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin, db: RawDB):
    """Login with email + password."""
    user = await AuthService.get_user_by_email(db, data.email)
    if not user or not user.password_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not AuthService.verify_password(data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )
    return AuthService.create_token_response(user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(data: TokenRefresh, db: RawDB):
    """Refresh an access token using a refresh token."""
    try:
        payload = AuthService.decode_token(data.refresh_token)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))

    if payload.type != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )

    from uuid import UUID
    user = await AuthService.get_user_by_id(db, UUID(payload.sub))
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated",
        )
    return AuthService.create_token_response(user)


@router.get("/me", response_model=UserResponse)
async def get_current_user(token: CurrentUser, db: RawDB):
    """Get the current authenticated user."""
    from uuid import UUID
    user = await AuthService.get_user_by_id(db, UUID(token.sub))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user
