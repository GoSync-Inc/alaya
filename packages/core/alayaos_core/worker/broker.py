"""TaskIQ broker — Redis Streams backed broker for extraction pipeline jobs."""

from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_redis import RedisStreamBroker

from alayaos_core.config import Settings


def create_broker() -> RedisStreamBroker:
    settings = Settings()
    broker = RedisStreamBroker(url=settings.REDIS_URL.get_secret_value())
    return broker


broker = create_broker()

# Scheduler reads cron labels from task definitions and triggers them periodically.
# Run with: taskiq scheduler alayaos_core.worker.broker:scheduler
scheduler = TaskiqScheduler(broker=broker, sources=[LabelScheduleSource(broker)])
