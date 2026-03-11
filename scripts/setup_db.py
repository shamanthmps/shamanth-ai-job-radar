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

# Priority companies to seed — tier 1 = FAANG+, tier 2 = unicorns, tier 3 = others
SEED_COMPANIES = [
    # (name, domain, tier, ats_type)
    ("Google", "google.com", 1, "greenhouse"),
    ("Amazon", "amazon.com", 1, "workday"),
    ("Microsoft", "microsoft.com", 1, "workday"),
    ("Meta", "meta.com", 1, "greenhouse"),
    ("Apple", "apple.com", 1, "greenhouse"),
    ("Stripe", "stripe.com", 1, "greenhouse"),
    ("Atlassian", "atlassian.com", 1, "greenhouse"),
    ("Databricks", "databricks.com", 1, "greenhouse"),
    ("Snowflake", "snowflake.com", 1, "greenhouse"),
    ("Coinbase", "coinbase.com", 1, "greenhouse"),
    ("Uber", "uber.com", 2, "lever"),
    ("Flipkart", "flipkart.com", 2, "workday"),
    ("Razorpay", "razorpay.com", 2, "wellfound"),
    ("Swiggy", "swiggy.com", 2, "lever"),
    ("PhonePe", "phonepe.com", 2, "greenhouse"),
    ("CRED", "cred.club", 2, "wellfound"),
    ("Meesho", "meesho.com", 2, "wellfound"),
    ("Groww", "groww.in", 2, "wellfound"),
    ("Samsara", "samsara.com", 2, "ashby"),
    ("Retool", "retool.com", 2, "ashby"),
    ("Brex", "brex.com", 2, "ashby"),
    ("Ramp", "ramp.com", 2, "ashby"),
    ("Cisco", "cisco.com", 3, "workday"),
    ("SAP", "sap.com", 3, "workday"),
    ("ServiceNow", "servicenow.com", 3, "workday"),
    ("Intuit", "intuit.com", 3, "workday"),
    ("Oracle", "oracle.com", 3, "workday"),
    ("BrowserStack", "browserstack.com", 3, "lever"),
    ("Freshworks", "freshworks.com", 3, "greenhouse"),
    ("Chargebee", "chargebee.com", 3, "greenhouse"),
]


async def setup() -> None:
    import asyncpg

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        print("ERROR: DATABASE_URL not set. Add it to your .env file.")
        sys.exit(1)

    print(f"Connecting to database...")
    conn = await asyncpg.connect(db_url)

    try:
        # Run schema SQL
        print(f"Running schema from {SCHEMA_PATH}...")
        schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
        await conn.execute(schema_sql)
        print("  ✓ Schema applied")

        # Seed companies
        print("Seeding companies table...")
        inserted = 0
        for name, domain, tier, ats_type in SEED_COMPANIES:
            await conn.execute(
                """
                INSERT INTO companies (name, domain, tier, ats_type)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (domain) DO UPDATE
                    SET tier = EXCLUDED.tier, ats_type = EXCLUDED.ats_type
                """,
                name, domain, tier, ats_type,
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
