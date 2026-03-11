"""
Database setup script — creates all tables and seeds the companies table.

Usage:
    python scripts/setup_db.py

Requires: DATABASE_URL set in .env (Supabase free tier or local Postgres).
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

sys.path.insert(0, str(ROOT))


SCHEMA_PATH = ROOT / "src" / "database" / "schema.sql"

# Priority companies to seed — (name, domain, tier_enum)
SEED_COMPANIES = [
    # (name, domain, tier)
    ("Google", "google.com", "tier1_faang"),
    ("Amazon", "amazon.com", "tier1_faang"),
    ("Microsoft", "microsoft.com", "tier1_faang"),
    ("Meta", "meta.com", "tier1_faang"),
    ("Apple", "apple.com", "tier1_faang"),
    ("Stripe", "stripe.com", "tier2_enterprise"),
    ("Atlassian", "atlassian.com", "tier2_enterprise"),
    ("Databricks", "databricks.com", "tier2_enterprise"),
    ("Snowflake", "snowflake.com", "tier2_enterprise"),
    ("Coinbase", "coinbase.com", "tier2_enterprise"),
    ("Uber", "uber.com", "tier2_enterprise"),
    ("Flipkart", "flipkart.com", "tier3_india_unicorn"),
    ("Razorpay", "razorpay.com", "tier3_india_unicorn"),
    ("Swiggy", "swiggy.com", "tier3_india_unicorn"),
    ("PhonePe", "phonepe.com", "tier3_india_unicorn"),
    ("CRED", "cred.club", "tier3_india_unicorn"),
    ("Meesho", "meesho.com", "tier3_india_unicorn"),
    ("Groww", "groww.in", "tier3_india_unicorn"),
    ("Samsara", "samsara.com", "tier4_global_mid"),
    ("Retool", "retool.com", "tier4_global_mid"),
    ("Brex", "brex.com", "tier4_global_mid"),
    ("Ramp", "ramp.com", "tier4_global_mid"),
    ("Cisco", "cisco.com", "tier2_enterprise"),
    ("SAP", "sap.com", "tier2_enterprise"),
    ("ServiceNow", "servicenow.com", "tier2_enterprise"),
    ("Intuit", "intuit.com", "tier2_enterprise"),
    ("Oracle", "oracle.com", "tier2_enterprise"),
    ("BrowserStack", "browserstack.com", "tier4_global_mid"),
    ("Freshworks", "freshworks.com", "tier4_global_mid"),
    ("Chargebee", "chargebee.com", "tier4_global_mid"),
]


async def setup() -> None:
    import ssl

    import asyncpg

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        print("ERROR: DATABASE_URL not set. Add it to your .env file.")
        sys.exit(1)

    # Strip sslmode query param — asyncpg doesn't parse it from the URL.
    # Use explicit kwargs (not DSN) so the username with a dot
    # (postgres.projectref) is not mangled by URL parsing.
    db_url_clean = db_url.split("?")[0]

    # Parse the URL manually
    from urllib.parse import urlparse
    parsed = urlparse(db_url_clean)
    pg_host = parsed.hostname
    pg_port = parsed.port or 5432
    pg_user = parsed.username
    pg_password = parsed.password
    pg_database = (parsed.path or "/postgres").lstrip("/") or "postgres"

    print(f"Connecting to {pg_host}:{pg_port} as {pg_user}...")
    conn = await asyncpg.connect(
        host=pg_host,
        port=pg_port,
        user=pg_user,
        password=pg_password,
        database=pg_database,
        ssl='require',
    )

    try:
        # Run schema SQL — wrap in a transaction so partial failures don't corrupt state.
        # If schema objects already exist (e.g. ran via SQL editor), that's fine — skip.
        print(f"Running schema from {SCHEMA_PATH}...")
        schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
        try:
            await conn.execute(schema_sql)
            print("  ✓ Schema applied")
        except Exception as schema_err:
            if "already exists" in str(schema_err):
                print("  ✓ Schema already applied (tables/types exist — skipping)")
            else:
                raise

        # Seed companies
        print("Seeding companies table...")
        inserted = 0
        for name, domain, tier in SEED_COMPANIES:
            await conn.execute(
                """
                INSERT INTO companies (name, domain, tier)
                VALUES ($1, $2, $3)
                ON CONFLICT (name) DO UPDATE
                    SET tier = EXCLUDED.tier
                """,
                name, domain, tier,
            )
            inserted += 1
        print(f"  ✓ {inserted} companies seeded")

        # Verify
        count = await conn.fetchval("SELECT COUNT(*) FROM companies")
        print(f"  ✓ companies table has {count} rows")

        tables = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        )
        print(f"\nAll tables: {', '.join(r['tablename'] for r in tables)}")
        print("\n✅ Database setup complete!")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(setup())
