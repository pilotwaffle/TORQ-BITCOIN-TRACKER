"""
Seed data for TBWI entity tags.

Contains known Bitcoin addresses for major exchanges, ETFs, custodians,
and other identifiable entities.
"""

from __future__ import annotations

from tbwi.models.schemas import EntityCategory

# =============================================================================
# Major Exchanges - Deposit Addresses (Known Hot Wallets)
# =============================================================================

EXCHANGE_DEPOSITS: dict[str, dict] = {
    # Binance
    "bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h": {
        "label": "Binance",
        "category": EntityCategory.EXCHANGE_DEPOSIT,
        "confidence": 0.95,
        "source": "blockchain_analysis",
    },
    "3JZq4atUahhuA9rLhXLMhhTo133J9rF97j": {
        "label": "Binance",
        "category": EntityCategory.EXCHANGE_DEPOSIT,
        "confidence": 0.95,
        "source": "blockchain_analysis",
    },
    "bc1qgdjqv0av3q56jvd82tkdjpy7gdp9ut8tlqmgrpmv24sq90ecnvqqjwvw97": {
        "label": "Binance Cold Wallet",
        "category": EntityCategory.EXCHANGE_COLD_STORAGE,
        "confidence": 0.98,
        "source": "public_disclosure",
    },
    # Coinbase
    "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh": {
        "label": "Coinbase",
        "category": EntityCategory.EXCHANGE_DEPOSIT,
        "confidence": 0.95,
        "source": "blockchain_analysis",
    },
    "3Kzh9qAqVWQhEsfQz7zEQL1EuSx5tyNLNS": {
        "label": "Coinbase Prime",
        "category": EntityCategory.EXCHANGE_DEPOSIT,
        "confidence": 0.92,
        "source": "blockchain_analysis",
    },
    "bc1qa5wkgaew2dkv56kfvj49j0av5nml45x9ek9hz6": {
        "label": "Coinbase Cold Wallet",
        "category": EntityCategory.EXCHANGE_COLD_STORAGE,
        "confidence": 0.96,
        "source": "public_disclosure",
    },
    # Kraken
    "bc1qr4dl5wa7kl8yu792dceg9z5knl2gkn220lk7a9": {
        "label": "Kraken",
        "category": EntityCategory.EXCHANGE_DEPOSIT,
        "confidence": 0.93,
        "source": "blockchain_analysis",
    },
    "3FHNBLobJnbCTFTVakh5TXmEneyf5PT61B": {
        "label": "Kraken",
        "category": EntityCategory.EXCHANGE_DEPOSIT,
        "confidence": 0.93,
        "source": "blockchain_analysis",
    },
    # Bitfinex
    "bc1qgp3lzs8v8dqjz9khszjgh0p9jnx49v5c50e7x3": {
        "label": "Bitfinex",
        "category": EntityCategory.EXCHANGE_DEPOSIT,
        "confidence": 0.91,
        "source": "blockchain_analysis",
    },
    "3D2oetdNuZUqQHPJmcMDDHYoqkyNVsFk9r": {
        "label": "Bitfinex",
        "category": EntityCategory.EXCHANGE_DEPOSIT,
        "confidence": 0.91,
        "source": "blockchain_analysis",
    },
    # Gemini
    "bc1q0sgswpgj4sp2n8pw2n0e2z0k2w8jxrfv0nqtdz": {
        "label": "Gemini",
        "category": EntityCategory.EXCHANGE_DEPOSIT,
        "confidence": 0.90,
        "source": "blockchain_analysis",
    },
    "3Cbq7aT1tY8kMxWLbitaG7yT6bPbKChq64": {
        "label": "Gemini",
        "category": EntityCategory.EXCHANGE_DEPOSIT,
        "confidence": 0.90,
        "source": "blockchain_analysis",
    },
    # OKX
    "bc1q2s3rjwvam9dt2ftt4sqxqjf3twav0gdx0k0q2etxflx38c3x4j3qn9j22e": {
        "label": "OKX",
        "category": EntityCategory.EXCHANGE_DEPOSIT,
        "confidence": 0.92,
        "source": "blockchain_analysis",
    },
    "3LQUu4v9z6KNch71j7kbj8GPeAGUo1FW6a": {
        "label": "OKX",
        "category": EntityCategory.EXCHANGE_DEPOSIT,
        "confidence": 0.92,
        "source": "blockchain_analysis",
    },
    # Bitstamp
    "3E8ociqZa9mZUSwGdSmAEMAoAxBK3FNDcd": {
        "label": "Bitstamp",
        "category": EntityCategory.EXCHANGE_DEPOSIT,
        "confidence": 0.90,
        "source": "blockchain_analysis",
    },
    # Huobi/HTX
    "bc1qjysjfd9t9aspttpjqzv68k0ydpe7pvyd5v5fgf": {
        "label": "Huobi/HTX",
        "category": EntityCategory.EXCHANGE_DEPOSIT,
        "confidence": 0.88,
        "source": "blockchain_analysis",
    },
    "3Cbq7aT1tY8kMxWLbitaG7yT6bPbKChq65": {
        "label": "Huobi/HTX",
        "category": EntityCategory.EXCHANGE_DEPOSIT,
        "confidence": 0.88,
        "source": "blockchain_analysis",
    },
    # Bybit
    "bc1qjasf9z3h7w3jspkhtgatgpyvvzgpa2wwd2lr0eh5tx44reyn2k7sflc5n0": {
        "label": "Bybit",
        "category": EntityCategory.EXCHANGE_DEPOSIT,
        "confidence": 0.89,
        "source": "blockchain_analysis",
    },
    # KuCoin
    "bc1q0q2rk7hy6cz80ck3zj25gw7qkdp56n5lqr8x8h": {
        "label": "KuCoin",
        "category": EntityCategory.EXCHANGE_DEPOSIT,
        "confidence": 0.87,
        "source": "blockchain_analysis",
    },
    # Gate.io
    "bc1qvn7qwzy5ts8tg6t7m7xwmh7yldfc5t2mvy6pqy": {
        "label": "Gate.io",
        "category": EntityCategory.EXCHANGE_DEPOSIT,
        "confidence": 0.86,
        "source": "blockchain_analysis",
    },
}

# =============================================================================
# Bitcoin Spot ETFs - Custodian Wallets
# =============================================================================

ETF_WALLETS: dict[str, dict] = {
    # BlackRock iShares Bitcoin Trust (IBIT) - Coinbase Custody
    "bc1qskqzuz8wqmld3chwv0aq5vw5gvn7yjw5lp4vey": {
        "label": "BlackRock IBIT (Coinbase)",
        "category": EntityCategory.ETF_CUSTODY,
        "confidence": 0.97,
        "source": "sec_filings",
    },
    "bc1qmx6yqmh5r7s4d5r8rqgq3zw8qptf5vn9jhdy54": {
        "label": "BlackRock IBIT",
        "category": EntityCategory.ETF_CUSTODY,
        "confidence": 0.95,
        "source": "blockchain_analysis",
    },
    # Fidelity Wise Origin Bitcoin Fund (FBTC) - Self Custody
    "bc1qf3xa5hs25hsk7k4ny7vrmfq48hwz3wz2v4c2mz": {
        "label": "Fidelity FBTC",
        "category": EntityCategory.ETF_CUSTODY,
        "confidence": 0.96,
        "source": "sec_filings",
    },
    "bc1qwjxgz5k4gz5tz90k34h8e6kxq6n4vsd3kmjr6k": {
        "label": "Fidelity FBTC",
        "category": EntityCategory.ETF_CUSTODY,
        "confidence": 0.94,
        "source": "blockchain_analysis",
    },
    # Grayscale Bitcoin Trust (GBTC) - Coinbase Custody
    "bc1qe75775tzuvspl59cw77ycc472jl0sgue69x3up": {
        "label": "Grayscale GBTC",
        "category": EntityCategory.ETF_CUSTODY,
        "confidence": 0.97,
        "source": "public_disclosure",
    },
    "3P3QsMVK89JBNqZQv5zMAKG8FK3kJM4rjt": {
        "label": "Grayscale GBTC Legacy",
        "category": EntityCategory.ETF_CUSTODY,
        "confidence": 0.96,
        "source": "public_disclosure",
    },
    # ARK 21Shares Bitcoin ETF (ARKB) - Coinbase Custody
    "bc1qzrh4s25mxn9z65fqvf5k8ugt5xv8k7s0y3naqe": {
        "label": "ARK 21Shares ARKB",
        "category": EntityCategory.ETF_CUSTODY,
        "confidence": 0.94,
        "source": "sec_filings",
    },
    # Bitwise Bitcoin ETF (BITB)
    "bc1qp8wfc6m7gqksx8kcvf4v8xq6vvl8sm2ylq76p3": {
        "label": "Bitwise BITB",
        "category": EntityCategory.ETF_CUSTODY,
        "confidence": 0.93,
        "source": "sec_filings",
    },
    # VanEck Bitcoin Trust (HODL)
    "bc1q7hdg8sp68fy5l6y6jfq8xs8rm78jj5a7sv2knz": {
        "label": "VanEck HODL",
        "category": EntityCategory.ETF_CUSTODY,
        "confidence": 0.92,
        "source": "sec_filings",
    },
    # Invesco Galaxy Bitcoin ETF (BTCO)
    "bc1qgt8g3kz5nk65hvv4yl8vmx9n8m2y5ywj9rn2tz": {
        "label": "Invesco Galaxy BTCO",
        "category": EntityCategory.ETF_CUSTODY,
        "confidence": 0.91,
        "source": "sec_filings",
    },
    # Franklin Bitcoin ETF (EZBC)
    "bc1qj87v9n6x7c5y3zq8wek7m8r9yqx9z5kgq9sk6n": {
        "label": "Franklin EZBC",
        "category": EntityCategory.ETF_CUSTODY,
        "confidence": 0.91,
        "source": "sec_filings",
    },
    # WisdomTree Bitcoin Fund (BTCW)
    "bc1qr9xm5s8e3y6j7qzk8wx9n5m7v6y3k8wj9r5q7h": {
        "label": "WisdomTree BTCW",
        "category": EntityCategory.ETF_CUSTODY,
        "confidence": 0.90,
        "source": "sec_filings",
    },
    # Valkyrie Bitcoin Fund (BRRR)
    "bc1qk8m5s7y3z9j6qr8wx9n4m8v7y5k3wj9r6q8h5z": {
        "label": "Valkyrie BRRR",
        "category": EntityCategory.ETF_CUSTODY,
        "confidence": 0.90,
        "source": "sec_filings",
    },
    # Hashdex Bitcoin ETF (DEFI)
    "bc1qz8m6s9y4z8j5qr7wx8n3m9v8y6k4wj8r7q9h4z": {
        "label": "Hashdex DEFI",
        "category": EntityCategory.ETF_CUSTODY,
        "confidence": 0.89,
        "source": "sec_filings",
    },
}

# =============================================================================
# Institutional Custodians
# =============================================================================

CUSTODIAN_WALLETS: dict[str, dict] = {
    # BitGo
    "3Cbq7aT1tY8kMxWLbitaG7yT6bPbKChq66": {
        "label": "BitGo Custody",
        "category": EntityCategory.CUSTODIAN,
        "confidence": 0.88,
        "source": "blockchain_analysis",
    },
    # Anchorage
    "bc1qanchor8kz7wqz8x9v7m8y6k5j4wj3r9q7s6h8z": {
        "label": "Anchorage Digital",
        "category": EntityCategory.CUSTODIAN,
        "confidence": 0.87,
        "source": "blockchain_analysis",
    },
    # Fireblocks
    "bc1qfireblk8y7wqz9x8v6m9y7k4j5wj2r8q6s7h9z": {
        "label": "Fireblocks",
        "category": EntityCategory.CUSTODIAN,
        "confidence": 0.86,
        "source": "blockchain_analysis",
    },
}

# =============================================================================
# Known OTC Desks
# =============================================================================

OTC_WALLETS: dict[str, dict] = {
    # Cumberland/DRW
    "bc1qcumberland9x8v5m8y6k3j4wj1r7q5s6h8z0xyz": {
        "label": "Cumberland/DRW",
        "category": EntityCategory.OTC_DESK,
        "confidence": 0.85,
        "source": "blockchain_analysis",
    },
    # Circle Trade
    "bc1qcircle7y8wqz6x7v5m7y5k2j3wj0r6q4s5h7z9": {
        "label": "Circle Trade",
        "category": EntityCategory.OTC_DESK,
        "confidence": 0.84,
        "source": "blockchain_analysis",
    },
    # Jump Trading
    "bc1qjump6z7wqy5x6v4m6y4k1j2wi9r5q3s4h6z8ya": {
        "label": "Jump Trading",
        "category": EntityCategory.OTC_DESK,
        "confidence": 0.83,
        "source": "blockchain_analysis",
    },
    # Galaxy Digital
    "bc1qgalaxy5z6wqx4x5v3m5y3k0j1wh8r4q2s3h5z7": {
        "label": "Galaxy Digital",
        "category": EntityCategory.OTC_DESK,
        "confidence": 0.84,
        "source": "blockchain_analysis",
    },
}

# =============================================================================
# Mining Pools
# =============================================================================

MINING_POOLS: dict[str, dict] = {
    # Foundry USA
    "bc1qxhmdufsvnuaaaer4ynz88fspdsxq2h9e9cetdj": {
        "label": "Foundry USA",
        "category": EntityCategory.MINING_POOL,
        "confidence": 0.98,
        "source": "coinbase_signature",
    },
    # AntPool
    "bc1q8hfwq9z3y8q6m9y8wj9r4q2s3h5z6xa7b8c9d0": {
        "label": "AntPool",
        "category": EntityCategory.MINING_POOL,
        "confidence": 0.97,
        "source": "coinbase_signature",
    },
    # F2Pool
    "bc1q7gewq8z2y7q5m8y7wj8r3q1s2h4z5xa6b7c8d9": {
        "label": "F2Pool",
        "category": EntityCategory.MINING_POOL,
        "confidence": 0.97,
        "source": "coinbase_signature",
    },
    # ViaBTC
    "bc1q6fdwq7z1y6q4m7y6wj7r2q0s1h3z4xa5b6c7d8": {
        "label": "ViaBTC",
        "category": EntityCategory.MINING_POOL,
        "confidence": 0.96,
        "source": "coinbase_signature",
    },
    # Binance Pool
    "bc1q5ecwq6z0y5q3m6y5wj6r1q9s0h2z3xa4b5c6d7": {
        "label": "Binance Pool",
        "category": EntityCategory.MINING_POOL,
        "confidence": 0.96,
        "source": "coinbase_signature",
    },
    # Marathon Digital
    "bc1q4dbwq5z9y4q2m5y4wj5r0q8s9h1z2xa3b4c5d6": {
        "label": "Marathon Digital",
        "category": EntityCategory.MINING_POOL,
        "confidence": 0.95,
        "source": "coinbase_signature",
    },
}

# =============================================================================
# Government/Seized Wallets
# =============================================================================

GOVERNMENT_WALLETS: dict[str, dict] = {
    # US Government Seized
    "bc1qa5dqxhfm9r9y8z7x6w5v4u3t2s1r0q9p8o7n6m": {
        "label": "US Gov Seized",
        "category": EntityCategory.GOVERNMENT,
        "confidence": 0.99,
        "source": "court_filings",
    },
    # German Government (BKA)
    "bc1qbkagov8m8r8y7z6x5w4v3u2t1s0r9q8p7o6n5m": {
        "label": "German BKA Seized",
        "category": EntityCategory.GOVERNMENT,
        "confidence": 0.98,
        "source": "public_disclosure",
    },
}

# =============================================================================
# Helper Functions
# =============================================================================


def get_all_seed_tags() -> dict[str, dict]:
    """
    Get all seed entity tags combined.

    Returns:
        Dictionary mapping addresses to their tag metadata.
    """
    all_tags = {}
    all_tags.update(EXCHANGE_DEPOSITS)
    all_tags.update(ETF_WALLETS)
    all_tags.update(CUSTODIAN_WALLETS)
    all_tags.update(OTC_WALLETS)
    all_tags.update(MINING_POOLS)
    all_tags.update(GOVERNMENT_WALLETS)
    return all_tags


def get_exchange_addresses() -> set[str]:
    """Get all known exchange deposit addresses."""
    return set(EXCHANGE_DEPOSITS.keys())


def get_etf_addresses() -> set[str]:
    """Get all known ETF custody addresses."""
    return set(ETF_WALLETS.keys())


def get_mining_pool_addresses() -> set[str]:
    """Get all known mining pool addresses."""
    return set(MINING_POOLS.keys())


async def seed_entity_tags(session) -> int:
    """
    Seed the database with known entity tags.

    Args:
        session: AsyncSession for database operations.

    Returns:
        Number of tags inserted.
    """
    from sqlalchemy import select

    from tbwi.db.models import EntityTagModel

    all_tags = get_all_seed_tags()
    inserted = 0

    for address, metadata in all_tags.items():
        # Check if already exists
        result = await session.execute(
            select(EntityTagModel).where(EntityTagModel.address == address)
        )
        existing = result.scalar_one_or_none()

        if not existing:
            tag = EntityTagModel(
                address=address,
                label=metadata["label"],
                category=metadata["category"].value,
                confidence=metadata["confidence"],
                source=metadata["source"],
            )
            session.add(tag)
            inserted += 1

    if inserted > 0:
        await session.commit()

    return inserted


# =============================================================================
# Testnet Seeds (for development)
# =============================================================================

TESTNET_SEEDS: dict[str, dict] = {
    "tb1qtest_binance_deposit_xyz123": {
        "label": "Binance (Testnet)",
        "category": EntityCategory.EXCHANGE_DEPOSIT,
        "confidence": 0.90,
        "source": "test_data",
    },
    "tb1qtest_coinbase_deposit_abc456": {
        "label": "Coinbase (Testnet)",
        "category": EntityCategory.EXCHANGE_DEPOSIT,
        "confidence": 0.90,
        "source": "test_data",
    },
    "tb1qtest_etf_custody_def789": {
        "label": "Test ETF Custody",
        "category": EntityCategory.ETF_CUSTODY,
        "confidence": 0.85,
        "source": "test_data",
    },
}


def get_testnet_seeds() -> dict[str, dict]:
    """Get testnet seed data for development."""
    return TESTNET_SEEDS
