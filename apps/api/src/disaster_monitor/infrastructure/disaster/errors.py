"""Errors raised while translating external disaster feeds."""


class DisasterProviderError(RuntimeError):
    """Base error for a provider transport or response problem."""


class DisasterProviderResponseError(DisasterProviderError):
    """The provider returned an unsupported or malformed payload."""
