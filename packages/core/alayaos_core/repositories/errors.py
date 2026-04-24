"""Repository-level domain errors."""


class HierarchyViolationError(ValueError):
    """Raised when a relation would violate the entity-type hierarchy or be self-referential."""
