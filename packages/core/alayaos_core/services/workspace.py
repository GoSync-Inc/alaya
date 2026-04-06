from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from alayaos_core.models.workspace import Workspace
from alayaos_core.repositories.entity_type import EntityTypeRepository
from alayaos_core.repositories.predicate import PredicateRepository
from alayaos_core.repositories.workspace import WorkspaceRepository

CORE_ENTITY_TYPES = [
    {"slug": "person", "display_name": "Person", "description": "A person in the organization"},
    {"slug": "project", "display_name": "Project", "description": "A project or initiative"},
    {"slug": "team", "display_name": "Team", "description": "A team or group"},
    {"slug": "document", "display_name": "Document", "description": "A document or file"},
    {"slug": "decision", "display_name": "Decision", "description": "A decision made"},
    {"slug": "meeting", "display_name": "Meeting", "description": "A meeting or discussion"},
    {"slug": "topic", "display_name": "Topic", "description": "A topic or theme"},
    {"slug": "tool", "display_name": "Tool", "description": "A tool or service"},
    {"slug": "process", "display_name": "Process", "description": "A process or workflow"},
    {"slug": "event", "display_name": "Event", "description": "An organizational event"},
]

CORE_PREDICATES = [
    {"slug": "deadline", "display_name": "Deadline", "value_type": "date"},
    {"slug": "status", "display_name": "Status", "value_type": "text"},
    {"slug": "owner", "display_name": "Owner", "value_type": "entity_ref"},
    {"slug": "role", "display_name": "Role", "value_type": "text"},
    {"slug": "title", "display_name": "Title", "value_type": "text"},
    {"slug": "member_of", "display_name": "Member Of", "value_type": "entity_ref"},
    {"slug": "reports_to", "display_name": "Reports To", "value_type": "entity_ref"},
    {"slug": "blocks", "display_name": "Blocks", "value_type": "entity_ref", "inverse_slug": "blocked_by"},
    {"slug": "blocked_by", "display_name": "Blocked By", "value_type": "entity_ref", "inverse_slug": "blocks"},
    {"slug": "depends_on", "display_name": "Depends On", "value_type": "entity_ref"},
    {"slug": "priority", "display_name": "Priority", "value_type": "text"},
    {"slug": "budget", "display_name": "Budget", "value_type": "number"},
    {"slug": "decision", "display_name": "Decision", "value_type": "text"},
    {"slug": "description", "display_name": "Description", "value_type": "text"},
    {"slug": "location", "display_name": "Location", "value_type": "text"},
    {"slug": "start_date", "display_name": "Start Date", "value_type": "date"},
    {"slug": "end_date", "display_name": "End Date", "value_type": "date"},
    {"slug": "communication_style", "display_name": "Communication Style", "value_type": "text"},
    {"slug": "tone_of_voice", "display_name": "Tone of Voice", "value_type": "text"},
    {"slug": "preferred_language", "display_name": "Preferred Language", "value_type": "text"},
]


async def create_workspace(session: AsyncSession, name: str, slug: str, settings: dict | None = None) -> Workspace:
    """Create workspace and seed core entity types and predicates."""
    ws_repo = WorkspaceRepository(session)
    et_repo = EntityTypeRepository(session)
    pred_repo = PredicateRepository(session)

    workspace = await ws_repo.create(name=name, slug=slug, settings=settings)
    await session.flush()  # ensure workspace.id is available

    # SET LOCAL for RLS — seeded tables are workspace-scoped
    await session.execute(text("SET LOCAL app.workspace_id = :wid"), {"wid": str(workspace.id)})

    for et in CORE_ENTITY_TYPES:
        await et_repo.upsert_core(workspace_id=workspace.id, **et)

    for pred in CORE_PREDICATES:
        await pred_repo.upsert_core(workspace_id=workspace.id, is_core=True, **pred)

    return workspace


async def seed_core_metadata(session: AsyncSession, workspace: Workspace) -> None:
    """Re-run core entity type and predicate upserts for an existing workspace."""
    et_repo = EntityTypeRepository(session)
    pred_repo = PredicateRepository(session)

    await session.execute(text("SET LOCAL app.workspace_id = :wid"), {"wid": str(workspace.id)})

    for et in CORE_ENTITY_TYPES:
        await et_repo.upsert_core(workspace_id=workspace.id, **et)

    for pred in CORE_PREDICATES:
        await pred_repo.upsert_core(workspace_id=workspace.id, is_core=True, **pred)
