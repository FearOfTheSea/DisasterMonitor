"""Consumer-owned ports for optional humanitarian context."""

from typing import Protocol

from disaster_monitor.domain.humanitarian import (
    HumanitarianIndicator,
    OperationalPresence,
)


class HumanitarianIndicatorProvider(Protocol):
    @property
    def source_id(self) -> str: ...

    async def indicators(
        self, country_code: str
    ) -> tuple[HumanitarianIndicator, ...]: ...


class OperationalPresenceProvider(Protocol):
    @property
    def source_id(self) -> str: ...

    async def operational_presence(
        self, country_code: str
    ) -> tuple[OperationalPresence, ...]: ...
