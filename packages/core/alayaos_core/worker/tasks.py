"""TaskIQ task definitions for the three-job extraction pipeline."""

from alayaos_core.worker.broker import broker


@broker.task(timeout=120, retry_on_error=True, max_retries=3)
async def job_extract(event_id: str, extraction_run_id: str, workspace_id: str) -> dict:
    """Job 1: Extract — preprocess + LLM extraction + store raw result."""
    # Implementation will be connected in pipeline.py
    return {"event_id": event_id, "extraction_run_id": extraction_run_id, "status": "extracted"}


@broker.task(timeout=60, retry_on_error=True, max_retries=3)
async def job_write(extraction_run_id: str, workspace_id: str) -> dict:
    """Job 2: Write — resolve entities + atomic write."""
    return {"extraction_run_id": extraction_run_id, "status": "written"}


@broker.task(timeout=60, retry_on_error=True, max_retries=2)
async def job_enrich(extraction_run_id: str, workspace_id: str) -> dict:
    """Job 3: Enrich — embedding stub (deferred to Run 3)."""
    return {"extraction_run_id": extraction_run_id, "status": "enriched"}
