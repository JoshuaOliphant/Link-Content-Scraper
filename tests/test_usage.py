# ABOUTME: Unit tests for the usage-metering seam (UsageRecorder / DbUsageRecorder).
# ABOUTME: Verifies recorder construction and that records hit db_client per-month.
from datetime import UTC, datetime

import link_content_scraper.auth as auth_module
from link_content_scraper.usage import (
    DbUsageRecorder,
    UsageRecorder,
    usage_recorder_for,
)


def test_usage_recorder_for_anonymous_is_none():
    assert usage_recorder_for(None) is None
    assert usage_recorder_for("") is None


def test_usage_recorder_for_customer_builds_recorder():
    recorder = usage_recorder_for("cus_x")
    assert isinstance(recorder, DbUsageRecorder)
    assert isinstance(recorder, UsageRecorder)


async def test_record_increments_usage_for_current_month(monkeypatch):
    calls = []

    class _SpyDb:
        async def increment_usage(self, customer_id, month):
            calls.append((customer_id, month))

    monkeypatch.setattr(auth_module, "db_client", _SpyDb())

    await DbUsageRecorder("cus_x").record()

    expected_month = datetime.now(UTC).strftime("%Y-%m")
    assert calls == [("cus_x", expected_month)]


async def test_record_resolves_db_client_dynamically(monkeypatch):
    """Patching auth.db_client after the recorder is built must still take effect."""
    recorder = usage_recorder_for("cus_y")

    seen = []

    class _SpyDb:
        async def increment_usage(self, customer_id, month):
            seen.append(customer_id)

    monkeypatch.setattr(auth_module, "db_client", _SpyDb())
    await recorder.record()
    assert seen == ["cus_y"]
