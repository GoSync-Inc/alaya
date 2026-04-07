"""TaskIQ broker — Redis Streams backed broker for extraction pipeline jobs."""

from taskiq_redis import RedisStreamBroker

from alayaos_core.config import Settings


def create_broker() -> RedisStreamBroker:
    settings = Settings()
    broker = RedisStreamBroker(url=settings.REDIS_URL)
    return broker


broker = create_broker()
