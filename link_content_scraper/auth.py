# ABOUTME: API key authentication middleware and Supabase database client.
# ABOUTME: Provides require_api_key FastAPI dependency and db_client singleton.

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Header, HTTPException

from .config import SUPABASE_KEY, SUPABASE_URL, TIER_LIMITS

logger = logging.getLogger(__name__)


@dataclass
class Customer:
    stripe_customer_id: str
    email: str
    tier: str
    active: bool


class DatabaseClient:
    """Async Supabase client with lazy initialization."""

    def __init__(self):
        self._supabase = None
        self._lock = asyncio.Lock()

    async def _get_supabase(self):
        async with self._lock:
            if self._supabase is None:
                from supabase import acreate_client
                self._supabase = await acreate_client(SUPABASE_URL, SUPABASE_KEY)
        return self._supabase

    async def get_customer_by_key(self, key_hash: str) -> Customer | None:
        client = await self._get_supabase()
        result = (
            await client.table("api_keys")
            .select("active, customers(stripe_customer_id, email, tier, active)")
            .eq("key_hash", key_hash)
            .maybe_single()
            .execute()
        )
        if not result or not result.data:
            return None
        key_active = result.data["active"]
        c = result.data["customers"]
        if c is None:
            logger.error("API key has no associated customer row (orphaned key)")
            return None
        return Customer(
            stripe_customer_id=c["stripe_customer_id"],
            email=c["email"],
            tier=c["tier"],
            active=key_active and c["active"],
        )

    async def get_usage(self, customer_id: str, month: str) -> int:
        client = await self._get_supabase()
        result = (
            await client.table("usage")
            .select("url_count")
            .eq("customer_id", customer_id)
            .eq("month", month)
            .maybe_single()
            .execute()
        )
        if not result or not result.data:
            return 0
        return result.data["url_count"]

    async def increment_usage(self, customer_id: str, month: str) -> None:
        # Uses a Postgres function for atomic upsert increment — avoids race conditions
        # when concurrent scrape jobs run for the same customer.
        client = await self._get_supabase()
        await client.rpc(
            "increment_usage",
            {"p_customer_id": customer_id, "p_month": month},
        ).execute()

    async def create_customer(self, stripe_customer_id: str, email: str, tier: str) -> None:
        client = await self._get_supabase()
        await client.table("customers").insert({
            "stripe_customer_id": stripe_customer_id,
            "email": email,
            "tier": tier,
        }).execute()

    async def create_api_key(self, key_hash: str, customer_id: str) -> None:
        client = await self._get_supabase()
        await client.table("api_keys").insert({
            "key_hash": key_hash,
            "customer_id": customer_id,
        }).execute()

    async def update_customer_tier(self, stripe_customer_id: str, tier: str) -> None:
        client = await self._get_supabase()
        await client.table("customers").update({"tier": tier}).eq(
            "stripe_customer_id", stripe_customer_id
        ).execute()

    async def deactivate_customer_keys(self, stripe_customer_id: str) -> None:
        client = await self._get_supabase()
        await client.table("api_keys").update({"active": False}).eq(
            "customer_id", stripe_customer_id
        ).execute()

    async def set_customer_active(self, stripe_customer_id: str, active: bool) -> None:
        client = await self._get_supabase()
        await client.table("customers").update({"active": active}).eq(
            "stripe_customer_id", stripe_customer_id
        ).execute()

    async def reactivate_customer_keys(self, stripe_customer_id: str) -> None:
        client = await self._get_supabase()
        await client.table("api_keys").update({"active": True}).eq(
            "customer_id", stripe_customer_id
        ).execute()


db_client = DatabaseClient()


async def require_api_key(x_api_key: str | None = Header(default=None)) -> Customer:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="API key required — include it in the X-API-Key header.")

    key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
    customer = await db_client.get_customer_by_key(key_hash)

    if not customer or not customer.active:
        raise HTTPException(status_code=401, detail="Invalid API key")

    limit = TIER_LIMITS.get(customer.tier)
    if limit is None:
        logger.error("Unknown tier %r for customer %s", customer.tier, customer.stripe_customer_id)
        raise HTTPException(status_code=500, detail="Account configuration error. Contact support.")

    month = datetime.now(UTC).strftime("%Y-%m")
    count = await db_client.get_usage(customer.stripe_customer_id, month)

    if count >= limit:
        next_month = (datetime.now(UTC).replace(day=1) + timedelta(days=32)).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        raise HTTPException(
            status_code=429,
            detail={
                "error": "quota_exceeded",
                "detail": f"Monthly limit of {limit:,} URLs reached.",
                "resetsAt": next_month.isoformat(),
            },
        )

    return customer
