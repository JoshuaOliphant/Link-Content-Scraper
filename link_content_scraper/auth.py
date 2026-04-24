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

    async def get_customer_by_email(self, email: str) -> "Customer | None":
        client = await self._get_supabase()
        result = (
            await client.table("customers")
            .select("stripe_customer_id, email, tier, active")
            .eq("email", email)
            .maybe_single()
            .execute()
        )
        if not result or not result.data:
            return None
        c = result.data
        return Customer(
            stripe_customer_id=c["stripe_customer_id"],
            email=c["email"],
            tier=c["tier"],
            active=c["active"],
        )

    async def get_customer_by_id(self, stripe_customer_id: str) -> "Customer | None":
        client = await self._get_supabase()
        result = (
            await client.table("customers")
            .select("stripe_customer_id, email, tier, active")
            .eq("stripe_customer_id", stripe_customer_id)
            .maybe_single()
            .execute()
        )
        if not result or not result.data:
            return None
        c = result.data
        return Customer(
            stripe_customer_id=c["stripe_customer_id"],
            email=c["email"],
            tier=c["tier"],
            active=c["active"],
        )

    async def has_api_key_for_customer(self, customer_id: str) -> bool:
        client = await self._get_supabase()
        result = (
            await client.table("api_keys")
            .select("key_hash")
            .eq("customer_id", customer_id)
            .limit(1)
            .execute()
        )
        return bool(result and result.data)

    async def delete_customer(self, stripe_customer_id: str) -> None:
        client = await self._get_supabase()
        await client.table("customers").delete().eq(
            "stripe_customer_id", stripe_customer_id
        ).execute()

    async def store_pending_key(
        self, session_id: str, raw_key: str, email: str, ttl_hours: int = 24
    ) -> None:
        from datetime import timedelta
        client = await self._get_supabase()
        expires_at = (datetime.now(UTC) + timedelta(hours=ttl_hours)).isoformat()
        await client.table("pending_keys").upsert({
            "session_id": session_id,
            "raw_key": raw_key,
            "email": email,
            "expires_at": expires_at,
        }).execute()

    async def claim_pending_key(self, session_id: str, email: str) -> str | None:
        client = await self._get_supabase()
        result = (
            await client.table("pending_keys")
            .select("raw_key, email")
            .eq("session_id", session_id)
            .gt("expires_at", datetime.now(UTC).isoformat())
            .maybe_single()
            .execute()
        )
        if not result or not result.data:
            logger.warning("Pending key not found or expired for session %s", session_id)
            return None
        if result.data["email"] != email:
            logger.warning("Email mismatch for pending key session %s", session_id)
            return None
        raw_key = result.data["raw_key"]
        await client.table("pending_keys").delete().eq("session_id", session_id).execute()
        return raw_key


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
