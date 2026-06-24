"""Collections QA audit prompts — Indian collections call centre."""

COLLECTIONS = "collections"


def get_collections_prompt() -> str:
    """Lazy import to avoid circular dependency with processor."""
    from processor import SCORING_PROMPT
    return SCORING_PROMPT
