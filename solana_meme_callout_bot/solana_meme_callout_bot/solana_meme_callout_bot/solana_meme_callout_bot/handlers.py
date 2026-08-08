"""Telegram command handlers."""

from telegram import Update
from telegram.ext import ContextTypes

from .monitoring import AutoMonitor
from .scanner import ScannerError, scan_recent_solana_tokens

async def start_command(
update: Update,
context: ContextTypes.DEFAULT_TYPE,
) -> None:
"""Welcome a user who starts the bot."""
del context

```
if update.message is not None:
    await update.message.reply_text(
        "Welcome to Solana Meme Callout Bot.\n\n"
        "Use /scan to scan recent Solana candidates.\n"
        "Use /auto to turn automatic alerts ON.\n"
        "Use /stop to turn automatic alerts OFF."
    )
```

async def status_command(
update: Update,
context: ContextTypes.DEFAULT_TYPE,
) -> None:
"""Confirm that the bot is online."""
del context

```
if update.message is not None:
    await update.message.reply_text(
        "Solana Meme Callout Bot is running."
    )
```

def _monitor(
context: ContextTypes.DEFAULT_TYPE,
) -> AutoMonitor:
monitor = context.application.bot_data.get(
"auto_monitor"
)

```
if not isinstance(monitor, AutoMonitor):
    raise RuntimeError(
        "Automatic monitor is not configured."
    )

return monitor
```

async def auto_command(
update: Update,
context: ContextTypes.DEFAULT_TYPE,
) -> None:
"""Enable automatic monitoring for the current chat."""

```
if update.message is None:
    return

monitor = _monitor(context)

started = await monitor.start(
    update.effective_chat.id,
    context.application,
)

if started:
    await update.message.reply_text(
        "Automatic monitoring is ON. "
        "I will scan approximately every 30 seconds "
        "and only send qualifying 86+ alerts."
    )
else:
    await update.message.reply_text(
        "Automatic monitoring is already ON."
    )
```

async def stop_command(
update: Update,
context: ContextTypes.DEFAULT_TYPE,
) -> None:
"""Disable automatic monitoring for the current chat."""

```
if update.message is None:
    return

monitor = _monitor(context)

stopped = await monitor.stop(
    update.effective_chat.id
)

await update.message.reply_text(
    "Automatic monitoring is OFF."
    if stopped
    else "Automatic monitoring was already OFF."
)
```

async def autostatus_command(
update: Update,
context: ContextTypes.DEFAULT_TYPE,
) -> None:
"""Report automatic monitoring status."""

```
if update.message is None:
    return

monitor = _monitor(context)

state = (
    "ON"
    if monitor.is_enabled(
        update.effective_chat.id
    )
    else "OFF"
)

await update.message.reply_text(
    f"Automatic monitoring is {state}."
)
```

def _format_number(
value: float | int | None,
decimals: int = 2,
) -> str:
if value is None:
return "N/A"

```
return f"{value:,.{decimals}f}"
```

def _format_candidate(
position: int,
scored_candidate: object,
) -> str:
candidate = scored_candidate.candidate

```
buy_pressure = (
    f"{scored_candidate.buy_pressure_pct:.0f}%"
    if scored_candidate.buy_pressure_pct is not None
    else "N/A"
)

return (
    f"{position}. {scored_candidate.label} "
    f"${candidate.symbol} — "
    f"{scored_candidate.score}/100\n"
    f"{candidate.name}\n"
    f"Address: {candidate.mint_address}\n"
    f"Market cap: "
    f"${_format_number(candidate.market_cap, 0)}\n"
    f"Liquidity: "
    f"${_format_number(candidate.liquidity, 0)}\n"
    f"5m Volume: "
    f"${_format_number(candidate.volume_5m, 0)}\n"
    f"1h Volume: "
    f"${_format_number(candidate.volume_1h, 0)}\n"
    f"Buy Pressure: {buy_pressure}\n"
    f"5m: "
    f"{_format_number(candidate.price_change_5m)}% | "
    f"1h: "
    f"{_format_number(candidate.price_change_1h)}%\n"
    f"Transactions: 5m "
    f"{candidate.buys_5m if candidate.buys_5m is not None else 'N/A'} "
    f"buys / "
    f"{candidate.sells_5m if candidate.sells_5m is not None else 'N/A'} "
    f"sells\n"
    f"X/Twitter mentions: "
    f"{scored_candidate.twitter_mentions}\n"
    f"Risk: {scored_candidate.risk.score}/100\n\n"
    f"Risk checks:\n"
    + "\n".join(scored_candidate.risk.checks)
    + "\n\nWhy:\n"
    + "\n".join(scored_candidate.reasons)
)
```

async def scan_command(
update: Update,
context: ContextTypes.DEFAULT_TYPE,
) -> None:
"""Fetch and return qualifying Solana candidates."""
del context

```
if update.message is None:
    return

await update.message.reply_text(
    "Scanning recent Solana candidates..."
)

try:
    candidates = await scan_recent_solana_tokens()

except ScannerError as error:
    await update.message.reply_text(
        str(error)
    )
    return

if not candidates:
    await update.message.reply_text(
        "No Solana candidates currently meet "
        "all strict 86+ market, risk and "
        "X/Twitter requirements."
    )
    return

await update.message.reply_text(
    "🔥 Qualifying Solana candidates:"
)

for position, candidate in enumerate(
    candidates,
    start=1,
):
    await update.message.reply_text(
        _format_candidate(
            position,
            candidate,
        )
    )

await update.message.reply_text(
    "Alerts are based on observed public market "
    "and social signals. They are not financial "
    "advice and do not guarantee safety or profit. "
    "No wallet or trading activity is performed."
)
```
