from __future__ import annotations

from celery import Celery

from app.config import settings

celery_app = Celery(
    "flowmind",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "scan-schedules": {
            "task": "flowmind.scan_schedules",
            "schedule": 30.0,
        }
    },
)

