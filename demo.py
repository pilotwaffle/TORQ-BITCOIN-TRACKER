#!/usr/bin/env python3
"""
TBWI Demo Mode - Run with real Bitcoin data without full infrastructure.

Uses mempool.space WebSocket API for real transaction data.
Uses SQLite for local storage (no PostgreSQL needed).
No Redis required - uses in-memory queue.
"""

from __future__ import annotations

import asyncio
import json
import signal
import sys
from datetime import datetime
from typing import Any

import httpx
import websockets
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.panel import Panel

console = Console()

# Configuration
MEMPOOL_WS_URL = "wss://mempool.space/api/v1/ws"
WHALE_THRESHOLD_BTC = 10.0  # Lower for demo to see more activity
KNOWN_EXCHANGES = {
    "bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h": "Binance",
    "3JZq4atUahhuA9rLhXLMhhTo133J9rF97j": "Binance",
    "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh": "Coinbase",
    "3Kzh9qAqVWQhEsfQz7zEQL1EuSx5tyNLNS": "Coinbase Prime",
    "bc1qr4dl5wa7kl8yu792dceg9z5knl2gkn220lk7a9": "Kraken",
    "3FHNBLobJnbCTFTVakh5TXmEneyf5PT61B": "Kraken",
    "bc1qgp3lzs8v8dqjz9khszjgh0p9jnx49v5c50e7x3": "Bitfinex",
    "bc1qe75775tzuvspl59cw77ycc472jl0sgue69x3up": "Grayscale GBTC",
}


class WhaleTracker:
    """Real-time whale transaction tracker."""

    def __init__(self):
        self.transactions: list[dict] = []
        self.whale_events: list[dict] = []
        self.stats = {
            "total_tx": 0,
            "whale_tx": 0,
            "total_btc": 0.0,
            "exchange_deposits": 0,
            "exchange_withdrawals": 0,
        }
        self.btc_price: float | None = None
        self.running = True

    async def fetch_btc_price(self) -> None:
        """Fetch current BTC price."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.coingecko.com/api/v3/simple/price",
                    params={"ids": "bitcoin", "vs_currencies": "usd"},
                )
                data = resp.json()
                self.btc_price = data["bitcoin"]["usd"]
        except Exception as e:
            console.print(f"[yellow]Price fetch failed: {e}[/yellow]")

    def classify_transaction(self, tx: dict) -> dict | None:
        """Classify a transaction and detect whale activity."""
        try:
            # Calculate total value
            total_sats = sum(out.get("value", 0) for out in tx.get("vout", []))
            total_btc = total_sats / 100_000_000

            if total_btc < WHALE_THRESHOLD_BTC:
                return None

            self.stats["total_tx"] += 1
            self.stats["whale_tx"] += 1
            self.stats["total_btc"] += total_btc

            # Check for known entities
            entities = []
            tx_type = "LARGE_TRANSFER"

            for vout in tx.get("vout", []):
                addr = vout.get("scriptpubkey_address", "")
                if addr in KNOWN_EXCHANGES:
                    entities.append(KNOWN_EXCHANGES[addr])
                    tx_type = "EXCHANGE_DEPOSIT"
                    self.stats["exchange_deposits"] += 1

            for vin in tx.get("vin", []):
                prev_addr = vin.get("prevout", {}).get("scriptpubkey_address", "")
                if prev_addr in KNOWN_EXCHANGES:
                    entities.append(f"{KNOWN_EXCHANGES[prev_addr]} (from)")
                    tx_type = "EXCHANGE_WITHDRAWAL"
                    self.stats["exchange_withdrawals"] += 1

            usd_value = total_btc * self.btc_price if self.btc_price else None

            return {
                "txid": tx.get("txid", "")[:16] + "...",
                "btc": total_btc,
                "usd": usd_value,
                "type": tx_type,
                "entities": entities or ["Unknown"],
                "time": datetime.now().strftime("%H:%M:%S"),
            }

        except Exception as e:
            console.print(f"[red]Classification error: {e}[/red]")
            return None

    def create_display(self) -> Table:
        """Create the display table."""
        # Stats panel
        stats_text = (
            f"[bold cyan]Total Whale TXs:[/] {self.stats['whale_tx']} | "
            f"[bold green]Total BTC:[/] {self.stats['total_btc']:.2f} | "
            f"[bold yellow]BTC Price:[/] ${self.btc_price:,.0f}" if self.btc_price else "Loading..."
        )

        # Recent transactions table
        table = Table(title="🐋 TBWI - Live Whale Transactions", caption=stats_text)
        table.add_column("Time", style="cyan", width=10)
        table.add_column("TXID", style="dim", width=20)
        table.add_column("BTC", justify="right", style="green", width=12)
        table.add_column("USD", justify="right", style="yellow", width=15)
        table.add_column("Type", style="magenta", width=20)
        table.add_column("Entity", style="blue", width=20)

        # Show last 15 transactions
        for tx in self.transactions[-15:]:
            usd_str = f"${tx['usd']:,.0f}" if tx['usd'] else "N/A"
            table.add_row(
                tx["time"],
                tx["txid"],
                f"{tx['btc']:.4f}",
                usd_str,
                tx["type"],
                ", ".join(tx["entities"][:2]),
            )

        return table

    async def stream_transactions(self) -> None:
        """Stream transactions from mempool.space."""
        console.print("[bold green]Connecting to mempool.space...[/bold green]")

        while self.running:
            try:
                async with websockets.connect(MEMPOOL_WS_URL) as ws:
                    # Subscribe to new transactions
                    await ws.send(json.dumps({"action": "want", "data": ["mempool-blocks", "live-2h-chart"]}))
                    console.print("[bold green]Connected! Streaming live Bitcoin transactions...[/bold green]")
                    console.print(f"[dim]Whale threshold: {WHALE_THRESHOLD_BTC} BTC[/dim]\n")

                    async for message in ws:
                        if not self.running:
                            break

                        try:
                            data = json.loads(message)

                            # Handle different message types
                            if "transactions" in data:
                                for tx in data["transactions"]:
                                    classified = self.classify_transaction(tx)
                                    if classified:
                                        self.transactions.append(classified)
                                        yield classified

                            elif "tx" in data:
                                classified = self.classify_transaction(data["tx"])
                                if classified:
                                    self.transactions.append(classified)
                                    yield classified

                        except json.JSONDecodeError:
                            continue

            except websockets.exceptions.ConnectionClosed:
                console.print("[yellow]Connection lost, reconnecting...[/yellow]")
                await asyncio.sleep(2)
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
                await asyncio.sleep(5)

    async def run(self) -> None:
        """Run the whale tracker."""
        # Fetch initial price
        await self.fetch_btc_price()

        # Price update task
        async def update_price():
            while self.running:
                await asyncio.sleep(60)
                await self.fetch_btc_price()

        price_task = asyncio.create_task(update_price())

        try:
            with Live(self.create_display(), refresh_per_second=2, console=console) as live:
                async for tx in self.stream_transactions():
                    live.update(self.create_display())

                    # Print whale alert
                    if tx["btc"] >= 100:
                        console.print(
                            f"\n[bold red]🚨 WHALE ALERT![/bold red] "
                            f"{tx['btc']:.2f} BTC ({tx['type']}) - {', '.join(tx['entities'])}\n"
                        )

        finally:
            price_task.cancel()
            try:
                await price_task
            except asyncio.CancelledError:
                pass


async def main():
    """Main entry point."""
    console.print(Panel.fit(
        "[bold cyan]Torq Bitcoin Whale Intelligence (TBWI)[/bold cyan]\n"
        "[dim]Real-time whale transaction monitoring[/dim]",
        border_style="cyan",
    ))

    tracker = WhaleTracker()

    # Handle shutdown
    def signal_handler(sig, frame):
        console.print("\n[yellow]Shutting down...[/yellow]")
        tracker.running = False
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    await tracker.run()


if __name__ == "__main__":
    asyncio.run(main())
