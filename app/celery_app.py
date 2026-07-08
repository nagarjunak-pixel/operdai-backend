"""
Celery configuration and app instance.
"""

from celery import Celery

from app.config import settings

celery_app = Celery(
    "operdai",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.tasks.pipeline",
        "app.tasks.follow_up",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Run follow-up check regularly
    beat_schedule={
        "check-follow-ups-every-5-minutes": {
            "task": "app.tasks.follow_up.check_and_trigger_follow_ups",
            "schedule": 300.0,  # 5 minutes
        }
    }
)
