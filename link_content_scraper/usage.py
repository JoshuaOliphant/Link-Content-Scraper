# ABOUTME: Usage-metering abstraction that decouples scraping from billing/storage.
# ABOUTME: Lets the scraper record one unit per fetched URL without knowing Supabase.
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from . import auth


@runtime_checkable
class UsageRecorder(Protocol):
    """Records one unit of metered usage per successfully fetched URL.

    The scraper depends only on this protocol, not on how usage is persisted.
    """

    async def record(self) -> None: ...


class DbUsageRecorder:
    """Persists usage for a customer in the Supabase-backed usage table.

    Knows the storage details (the per-month bucket key) so the scraper does
    not have to. Records are attributed to a single customer for the calendar
    month in effect when the URL is fetched.
    """

    def __init__(self, customer_id: str) -> None:
        self._customer_id = customer_id

    async def record(self) -> None:
        month = datetime.now(UTC).strftime("%Y-%m")
        # Resolve db_client through the module so test monkeypatching of
        # auth.db_client is honored.
        await auth.db_client.increment_usage(self._customer_id, month)


def usage_recorder_for(customer_id: str | None) -> UsageRecorder | None:
    """Build a usage recorder for an authenticated customer, or None for anonymous."""
    return DbUsageRecorder(customer_id) if customer_id else None
