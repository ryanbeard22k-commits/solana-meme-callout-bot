"""Background, alert-only monitoring for qualifying Solana candidates."""

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from telegram.error import TelegramError

from .scanner import (
ScannerError,
ScoredMemeCoinCandidate,
scan_recent_solana_tokens,
)

if TYPE_CHECKING:
from telegram.ext import Application

logger = logging.getLogger(**name**)

SCAN_INTERVAL_SECONDS = 30

MIN_LIQUIDITY_USD = 25_000
MIN_VOLUME_5M_USD = 10_000

MIN_OVERALL_SCORE = 86
MIN_RISK_SCORE = 70

CALLED_TOKENS_PATH = Path(
"auto_called_tokens.json"
)

MAX_STORED_ADDRESSES_PER_CHAT = 1_000

def _format_money(value: float | None) -> str:
return (
"Unknown"
if value is None
else f"${value:,.0f}"
)

def _format_percent(value: float | None) -> str:
return (
"Unknown"
if value is None
else f"{value:.2f}%"
)

def format_auto_callout(
scored: ScoredMemeCoinCandidate,
) -> str:
"""Format one automatic alert."""

```
candidate = scored.candidate

buy_pressure = (
    f"{scored.buy_pressure_pct:.0f}% buys"
    if scored.buy_pressure_pct is not None
    else "Unknown"
)

sell_pressure = (
    f"{100 - scored.buy_pressure_pct:.0f}% sells"
    if scored.buy_pressure_pct is not None
    else "Unknown"
)

risk_warnings = [
    check
    for check in scored.risk.checks
    if check.startswith("⚠️")
    or check.startswith("🚨")
    or "Unknown" in check
]

if not risk_warnings:
    risk_warnings = [
        "✅ No observed major risk warning"
    ]

reasons = "\n".join(
    scored.reasons[:5]
)

warnings = "\n".join(
    risk_warnings[:5]
)

market_link = (
    f"\nMarket data: {candidate.market_url}"
    if candidate.market_url
    else ""
)

return (
    f"🔥 AUTO CALL — "
    f"${candidate.symbol} "
    f"({candidate.name})\n"
    f"Overall score: {scored.score}/100\n"
    f"Risk score: {scored.risk.score}/100\n"
    f"X/Twitter mentions: "
    f"{scored.twitter_mentions}\n"
    f"Contract: {candidate.mint_address}\n"
    f"Market cap: "
    f"{_format_money(candidate.market_cap)}\n"
    f"Liquidity: "
    f"{_format_money(candidate.liquidity)}\n"
    f"5m volume: "
    f"{_format_money(candidate.volume_5m)}\n"
    f"1h volume: "
    f"{_format_money(candidate.volume_1h)}\n"
    f"Buy/sell pressure: "
    f"{buy_pressure} / {sell_pressure}\n"
    f"5m price change: "
    f"{_format_percent(candidate.price_change_5m)}\n"
    f"1h price change: "
    f"{_format_percent(candidate.price_change_1h)}\n"
    f"\nMain reasons:\n"
    f"{reasons}\n"
    f"\nMain risk warnings:\n"
    f"{warnings}\n"
    f"{market_link}\n\n"
    "Alert only. This is not financial advice "
    "and is not a guarantee of profit. "
    "No trade or wallet action was performed."
)
```

class AutoMonitor:
"""Own monitoring state and the background scan loop."""

```
def __init__(self) -> None:
    self.enabled_chats: set[int] = set()

    self.called_by_chat: dict[
        str,
        set[str],
    ] = self._load_called_tokens()

    self.task: asyncio.Task[None] | None = None

@staticmethod
def _load_called_tokens() -> dict[
    str,
    set[str],
]:
    try:
        raw = json.loads(
            CALLED_TOKENS_PATH.read_text()
        )

        if not isinstance(raw, dict):
            return {}

        return {
            str(chat_id): {
                address.lower()
                for address in addresses
                if isinstance(address, str)
            }
            for chat_id, addresses in raw.items()
            if isinstance(addresses, list)
        }

    except (
        FileNotFoundError,
        OSError,
        json.JSONDecodeError,
    ):
        return {}

def _save_called_tokens(self) -> None:
    payload = {
        chat_id: list(addresses)[
            -MAX_STORED_ADDRESSES_PER_CHAT:
        ]
        for chat_id, addresses
        in self.called_by_chat.items()
    }

    try:
        CALLED_TOKENS_PATH.write_text(
            json.dumps(
                payload,
                indent=2,
            )
        )

    except OSError:
        logger.warning(
            "Could not persist automatic "
            "callout addresses."
        )

def _is_qualifying(
    self,
    scored: ScoredMemeCoinCandidate,
) -> bool:
    candidate = scored.candidate

    return (
        scored.score >= MIN_OVERALL_SCORE
        and scored.risk.score >= MIN_RISK_SCORE
        and candidate.liquidity is not None
        and candidate.liquidity >= MIN_LIQUIDITY_USD
        and candidate.volume_5m is not None
        and candidate.volume_5m >= MIN_VOLUME_5M_USD
    )

async def start(
    self,
    chat_id: int,
    application: "Application",
) -> bool:
    """Enable monitoring for a chat."""

    was_enabled = (
        chat_id in self.enabled_chats
    )

    self.enabled_chats.add(chat_id)

    if (
        self.task is None
        or self.task.done()
    ):
        self.task = application.create_task(
            self._run(application),
            update=None,
            name="solana-auto-monitor",
        )

    return not was_enabled

async def stop(
    self,
    chat_id: int,
) -> bool:
    """Disable monitoring for a chat."""

    was_enabled = (
        chat_id in self.enabled_chats
    )

    self.enabled_chats.discard(chat_id)

    if (
        not self.enabled_chats
        and self.task is not None
    ):
        self.task.cancel()
        self.task = None

    return was_enabled

def is_enabled(
    self,
    chat_id: int,
) -> bool:
    return chat_id in self.enabled_chats

async def _run(
    self,
    application: "Application",
) -> None:
    """Scan immediately, then repeat."""

    while self.enabled_chats:
        try:
            await self._scan_and_alert(
                application
            )

        except asyncio.CancelledError:
            raise

        except Exception:
            logger.exception(
                "Automatic Solana scan failed; "
                "monitoring will continue."
            )

        try:
            await asyncio.sleep(
                SCAN_INTERVAL_SECONDS
            )

        except asyncio.CancelledError:
            raise

async def _scan_and_alert(
    self,
    application: "Application",
) -> None:
    try:
        candidates = (
            await scan_recent_solana_tokens()
        )

    except ScannerError:
        logger.warning(
            "Automatic scan skipped because "
            "market data was unavailable."
        )
        return

    for chat_id in list(
        self.enabled_chats
    ):
        called_addresses = (
            self.called_by_chat.setdefault(
                str(chat_id),
                set(),
            )
        )

        for scored in candidates:
            address = (
                scored.candidate.mint_address.lower()
            )

            if (
                address in called_addresses
                or not self._is_qualifying(
                    scored
                )
            ):
                continue

            try:
                await application.bot.send_message(
                    chat_id=chat_id,
                    text=format_auto_callout(
                        scored
                    ),
                )

            except TelegramError:
                logger.warning(
                    "Automatic callout could not "
                    "be sent to chat %s.",
                    chat_id,
                )
                continue

            called_addresses.add(address)
            self._save_called_tokens()
```
