import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.middleware import RateLimitMiddleware
from app.api.v1.agencies import router as agencies_router
from app.api.v1.agent_runs import router as agent_runs_router
from app.api.v1.auth import router as auth_router
from app.api.v1.billing import router as billing_router
from app.api.v1.clients import router as clients_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.escalations import router as escalations_router
from app.api.v1.kb import router as kb_router
from app.api.v1.leads import router as leads_router
from app.api.v1.webhooks import router as webhooks_router
from app.api.v1.shares import router as shares_router
from app.api.v1.webrtc_routes import router as webrtc_router
from app.api.v1.integrations import router as integrations_router
from app.config import settings

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("operdai.api")

# Initialize Sentry
sentry_dsn = os.getenv("SENTRY_DSN")
if sentry_dsn and settings.environment != "test":
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        sentry_sdk.init(
            dsn=sentry_dsn,
            integrations=[FastApiIntegration()],
            traces_sample_rate=1.0,
            environment=settings.environment,
        )
        print("🔒 Sentry SDK initialized successfully")
    except ImportError:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown lifecycle."""
    # Startup
    print(f"🚀 OperdAI starting in {settings.environment} mode")
    yield
    # Shutdown
    print("👋 OperdAI shutting down")


app = FastAPI(
    title="OperdAI",
    description="White-label autonomous inbound-lead agent platform",
    version="0.2.0",
    lifespan=lifespan,
)

# Uncaught Exception Handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Log uncaught exceptions and return standardized error response."""
    logger.exception(f"Unhandled error occurred on path {request.url.path}: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal server error occurred. Please contact support."},
    )

# Rate Limiting Middleware
app.add_middleware(RateLimitMiddleware)

# CORS — permissive in dev, locked down in prod
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.debug else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API routes
app.include_router(auth_router, prefix="/api/v1")
app.include_router(agencies_router, prefix="/api/v1")
app.include_router(clients_router, prefix="/api/v1")
app.include_router(webhooks_router, prefix="/api/v1")
app.include_router(agent_runs_router, prefix="/api/v1")
app.include_router(leads_router, prefix="/api/v1")
app.include_router(escalations_router, prefix="/api/v1")
app.include_router(kb_router, prefix="/api/v1")
app.include_router(billing_router, prefix="/api/v1")
app.include_router(shares_router, prefix="/api/v1")
app.include_router(webrtc_router, prefix="/api/v1")
app.include_router(integrations_router, prefix="/api/v1")
app.include_router(dashboard_router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "version": "0.1.0",
        "environment": settings.environment,
    }


@app.get("/api/v1/branding/{agency_slug}")
async def get_branding(agency_slug: str):
    """
    Public branding endpoint — no auth.
    Frontend calls this at bootstrap to skin the UI per agency.
    """
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.models.agency import Agency

    async with async_session_factory() as db:
        result = await db.execute(select(Agency).where(Agency.slug == agency_slug))
        agency = result.scalar_one_or_none()
        if not agency:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Agency not found")
        return {
            "name": agency.name,
            "slug": agency.slug,
            "branding": agency.branding,
        }
