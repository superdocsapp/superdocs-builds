"""Domain exceptions."""


class StrGenError(Exception):
    """Base class for all STR Pack errors."""


class NotFound(StrGenError):
    """An entity (property, block, photo...) does not exist."""


class AlreadyExists(StrGenError):
    """An entity with the same identifier already exists."""


class MissingLink(StrGenError):
    """A property references a shared block that no longer exists."""

    def __init__(self, property_id: str, kind: str, block_id: str):
        self.property_id = property_id
        self.kind = kind
        self.block_id = block_id
        super().__init__(
            f"Property '{property_id}' references missing '{kind}' block '{block_id}'. "
            f"Fix with: python main.py block link {property_id} {kind} <block_id>"
        )


class SuperDocsError(StrGenError):
    """The SuperDocs MCP service failed or is unreachable."""
