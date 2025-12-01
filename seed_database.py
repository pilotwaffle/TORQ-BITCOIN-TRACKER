#!/usr/bin/env python3
"""
Seed the TBWI database with known exchange addresses.

Run this once to load entity tags for exchange detection.
"""

import asyncio
from tbwi.db.session import get_db_session, init_db
from tbwi.db.seeds import seed_entity_tags, get_all_seed_tags


async def main():
    print("🌱 Seeding TBWI database with exchange addresses...")

    # Initialize database
    await init_db()

    # Seed entity tags
    async with get_db_session() as session:
        count = await seed_entity_tags(session)

    total_addresses = len(get_all_seed_tags())
    print(f"✅ Loaded {count} new addresses ({total_addresses} total in seed data)")
    print("\n📊 Categories seeded:")
    print("   - Major Exchanges (Binance, Coinbase, Kraken, etc.)")
    print("   - Bitcoin ETFs (BlackRock, Fidelity, Grayscale, etc.)")
    print("   - Mining Pools (Foundry, AntPool, F2Pool, etc.)")
    print("   - OTC Desks (Cumberland, Galaxy, Jump, etc.)")
    print("   - Government Seized Wallets")
    print("\n🐋 Now transactions to these addresses will be classified as:")
    print("   - EXCHANGE_DEPOSIT_CANDIDATE → Bearish (selling pressure)")
    print("   - EXCHANGE_WITHDRAWAL_CANDIDATE → Bullish (accumulation)")


if __name__ == "__main__":
    asyncio.run(main())
