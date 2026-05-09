import os

from celery import Celery

celery = Celery("qa_platform")

celery.conf.update(
    broker_url=os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0"),
    result_backend=os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1"),
    accept_content=["json"],
    task_serializer="json",
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    beat_schedule={},
)

celery.autodiscover_tasks(["app.tasks"])
