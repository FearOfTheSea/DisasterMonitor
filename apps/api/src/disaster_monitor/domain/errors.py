"""Errors owned by the application domain."""


class InvalidQuestionError(ValueError):
    """Raised when a user question cannot be answered safely."""


class ConversationNotFoundError(LookupError):
    """Raised when a requested durable conversation does not exist."""

    def __init__(self, conversation_id: str) -> None:
        super().__init__(f"Conversation {conversation_id!r} does not exist.")


class ModelRuntimeError(RuntimeError):
    """Raised when the configured local model runtime cannot respond."""


class ModelResponseError(RuntimeError):
    """Raised when the model runtime returns an unusable response."""


class MultimodalInputError(ValueError):
    """Raised when a supplied media payload is malformed or exceeds policy."""
