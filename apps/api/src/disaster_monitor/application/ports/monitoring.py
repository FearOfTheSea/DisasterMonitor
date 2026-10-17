"""Explicit runtime prerequisite for scheduled operator workflows."""


class ScheduledMonitoringUnavailableError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "Scheduled monitoring is unavailable. It requires durable operational "
            "storage and explicitly configured scheduler/worker processes. "
            "Manual browsing and retained records remain available."
        )
