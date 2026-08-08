```python
"""Strict, read-only Solana meme-coin market-data scanner.

This module only reads public market/social data. It does not connect to a
wallet, sign transactions, or place trades.

IMPORTANT:
These filters are designed to reject obvious/high-risk candidates. They do
NOT guarantee that a token is safe or cannot rug.
"""

import asyncio
from dataclasses import dataclass
import json
import os
import time
import urllib.parse
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


TOKEN_BOOSTS_URL = (
    "https://api.dexscreener.com/token-boosts/latest/v1"
)

TOKEN_PAIRS_URL = (
    "https://api.dexscreener.com/latest/dex/tokens"
)

X_RECENT_SEARCH_URL = (
    "https://api.x.com/2/tweets/search/recent"
)

REQUEST_TIMEOUT_SECONDS = 15
MAX_TOKENS_TO_FETCH = 30

# ============================================================
# STRICT CALL-OUT SETTINGS
# ============================================================

# A candidate must pass these filters before it can be called out.

MIN_LIQUIDITY_USD = 25_000
MIN_VOLUME_5M_USD = 10_000
MIN_VOLUME_1H_USD = 50_000
MIN_TRANSACTIONS_5M = 25

MIN_BUY_PRESSURE_PCT = 55
MAX_SELL_PRESSURE_PCT = 45

MAX_MARKET_CAP_LIQUIDITY_RATIO = 10

# Do not call extremely new pairs.
MIN_TOKEN_AGE_HOURS = 6

# User requested above 85%.
# Therefore 86+ qualifies.
MIN_CALL_OUT_SCORE = 86

# Minimum recent X/Twitter mentions.
# Set to 0 if you do not want social mentions to be a hard filter.
MIN_X_MENTIONS = 5


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass(frozen=True)
class MemeCoinCandidate:
    """Market data for one Solana token/pair."""

    mint_address: str
    symbol: str
    name: str
    market_cap: float | None
    liquidity: float | None
    volume_5m: float | None
    volume_1h: float | None
    price_change_5m: float | None
    price_change_1h: float | None
    buys_5m: int | None
    sells_5m: int | None
    pair_created_at_ms: int | None
    market_url: str | None = None


@dataclass(frozen=True)
class RiskAnalysis:
    """Observed market-data risk analysis."""

    score: int
    checks: tuple[str, ...]
    serious_flags: bool
    token_age_days: float | None


@dataclass(frozen=True)
class ScoredMemeCoinCandidate:
    """A market candidate with a transparent 0-100 callout score."""

    candidate: MemeCoinCandidate
    market_score: int
    score: int
    label: str
    buy_pressure_pct: float | None
    reasons: tuple[str, ...]
    risk: RiskAnalysis

    # Number of recent X/Twitter mentions found.
    twitter_mentions: int = 0


class MemeCoinScanner(Protocol):
    """Interface for a market-data scanner implementation."""

    async def scan(self) -> list[MemeCoinCandidate]:
        """Return recent Solana token candidates."""
        ...


class ScannerError(RuntimeError):
    """Raised when public market data cannot be retrieved or parsed."""


# ============================================================
# BASIC HELPERS
# ============================================================

def _as_float(value: object) -> float | None:
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: object) -> int | None:
    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _get_json(url: str) -> object:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Solana-Meme-Callout-Bot/1.0",
        },
    )

    try:
        with urlopen(
            request,
            timeout=REQUEST_TIMEOUT_SECONDS,
        ) as response:
            return json.load(response)

    except (
        HTTPError,
        URLError,
        TimeoutError,
        json.JSONDecodeError,
    ) as error:
        raise ScannerError(
            "Public market data is temporarily unavailable."
        ) from error


def _metric(
    pair: dict[str, object],
    group: str,
    field: str,
) -> object:
    values = pair.get(group)

    if isinstance(values, dict):
        return values.get(field)

    return None


def _points_for(
    value: float | None,
    tiers: tuple[tuple[float, int], ...],
) -> int:
    """Return points for the highest threshold reached."""

    if value is None:
        return 0

    points = 0

    for minimum, tier_points in tiers:
        if value >= minimum:
            points = tier_points

    return points


# ============================================================
# MARKET METRICS
# ============================================================

def _buy_pressure_pct(
    candidate: MemeCoinCandidate,
) -> float | None:
    """Calculate the five-minute percentage of transactions that were buys."""

    if (
        candidate.buys_5m is None
        or candidate.sells_5m is None
    ):
        return None

    total_transactions = (
        candidate.buys_5m + candidate.sells_5m
    )

    if total_transactions <= 0:
        return None

    return (
        candidate.buys_5m
        / total_transactions
        * 100
    )


def _token_age_days(
    candidate: MemeCoinCandidate,
) -> float | None:
    """Return pair age in days."""

    if candidate.pair_created_at_ms is None:
        return None

    age_seconds = (
        time.time()
        - candidate.pair_created_at_ms / 1000
    )

    if age_seconds < 0:
        return None

    return age_seconds / 86_400


def _market_cap_liquidity_ratio(
    candidate: MemeCoinCandidate,
) -> float | None:
    if (
        candidate.market_cap is None
        or candidate.liquidity is None
        or candidate.liquidity <= 0
    ):
        return None

    return candidate.market_cap / candidate.liquidity


# ============================================================
# RISK ANALYSIS
# ============================================================

def _risk_analysis(
    candidate: MemeCoinCandidate,
) -> RiskAnalysis:
    """
    Analyze observable market-data risks.

    This does not prove a token is safe. It only penalizes observable
    warning signs.
    """

    ratio = _market_cap_liquidity_ratio(candidate)
    age_days = _token_age_days(candidate)

    total_transactions = (
        candidate.buys_5m + candidate.sells_5m
        if (
            candidate.buys_5m is not None
            and candidate.sells_5m is not None
        )
        else None
    )

    pressure_pct = _buy_pressure_pct(candidate)

    sell_pressure_pct = (
        100 - pressure_pct
        if pressure_pct is not None
        else None
    )

    penalty = 0
    serious_flags = False

    # --------------------------------------------------------
    # Liquidity / market cap
    # --------------------------------------------------------

    if ratio is None:
        liquidity_check = (
            "⚪ Liquidity relative to market cap: Unknown"
        )
        ratio_check = (
            "⚪ Market-cap-to-liquidity ratio: Unknown"
        )

    else:
        if ratio > 20:
            penalty += 30
            liquidity_check = (
                "🚨 Very low liquidity relative to market cap"
            )
            serious_flags = True

        elif ratio > 10:
            penalty += 18
            liquidity_check = (
                "⚠️ Low liquidity relative to market cap"
            )

        elif ratio > 5:
            penalty += 8
            liquidity_check = (
                "⚠️ Moderate liquidity relative to market cap"
            )

        else:
            liquidity_check = (
                "✅ Good liquidity relative to market cap"
            )

        if ratio > 20:
            penalty += 25
            ratio_check = (
                "🚨 Extremely high market-cap-to-liquidity ratio"
            )
            serious_flags = True

        elif ratio > 10:
            penalty += 12
            ratio_check = (
                "⚠️ Elevated market-cap-to-liquidity ratio"
            )

        else:
            ratio_check = (
                "✅ Reasonable market-cap-to-liquidity ratio"
            )

    # --------------------------------------------------------
    # Trading activity
    # --------------------------------------------------------

    if (
        total_transactions is None
        or candidate.volume_5m is None
    ):
        activity_check = (
            "⚪ Trading activity: Unknown"
        )

    elif (
        total_transactions < 10
        or candidate.volume_5m < 500
    ):
        penalty += 20
        activity_check = (
            "🚨 Very low trading activity"
        )
        serious_flags = True

    elif (
        total_transactions < 25
        or candidate.volume_5m < 1_000
    ):
        penalty += 10
        activity_check = (
            "⚠️ Low trading activity"
        )

    else:
        activity_check = (
            "✅ Healthy trading activity"
        )

    # --------------------------------------------------------
    # Sell pressure
    # --------------------------------------------------------

    if sell_pressure_pct is None:
        sell_check = "⚪ Sell pressure: Unknown"

    elif sell_pressure_pct >= 65:
        penalty += 25
        sell_check = "🚨 Heavy sell pressure"
        serious_flags = True

    elif sell_pressure_pct >= 55:
        penalty += 15
        sell_check = "⚠️ Elevated sell pressure"

    else:
        sell_check = "✅ Sell pressure is not elevated"

    # These cannot currently be established from this data source.
    liquidity_change_check = (
        "⚪ Sudden liquidity decrease: Unknown"
    )

    holder_check = (
        "⚪ Holder concentration: Unknown"
    )

    developer_check = (
        "⚪ Developer wallet/token creator activity: Unknown"
    )

    # --------------------------------------------------------
    # Token age
    # --------------------------------------------------------

    if age_days is None:
        age_check = "⚪ Token age: Unknown"

    elif age_days < 1 / 24:
        penalty += 20
        age_check = (
            "🚨 Token pair is less than 1 hour old"
        )
        serious_flags = True

    elif age_days < 6 / 24:
        penalty += 12
        age_check = (
            "⚠️ Token pair is less than 6 hours old"
        )

    elif age_days < 1:
        penalty += 6
        age_check = (
            "⚠️ Token pair is less than 1 day old"
        )

    else:
        age_check = (
            "✅ Token pair is at least 1 day old"
        )

    return RiskAnalysis(
        score=max(0, 100 - penalty),
        checks=(
            liquidity_check,
            ratio_check,
            activity_check,
            sell_check,
            liquidity_change_check,
            holder_check,
            developer_check,
            age_check,
        ),
        serious_flags=serious_flags,
        token_age_days=age_days,
    )


# ============================================================
# X / TWITTER
# ============================================================

def _get_x_mentions(
    candidate: MemeCoinCandidate,
) -> int:
    """
    Search recent X posts for the contract address and token symbol.

    X API access is optional. If X_BEARER_TOKEN is not configured,
    this returns zero.

    Social mentions are supporting evidence only. They do not override
    the hard market/risk filters.
    """

    bearer_token = os.environ.get("X_BEARER_TOKEN")

    if not bearer_token:
        return 0

    queries = [
        f'"{candidate.mint_address}"',
        f'"${candidate.symbol}" -is:retweet',
    ]

    total_mentions = 0

    for query in queries:
        encoded_query = urllib.parse.quote(query)

        url = (
            f"{X_RECENT_SEARCH_URL}"
            f"?query={encoded_query}"
            f"&max_results=100"
        )

        request = Request(
            url,
            headers={
                "Authorization": (
                    f"Bearer {bearer_token}"
                ),
                "Accept": "application/json",
                "User-Agent": (
                    "Solana-Meme-Callout-Bot/1.0"
                ),
            },
        )

        try:
            with urlopen(
                request,
                timeout=REQUEST_TIMEOUT_SECONDS,
            ) as response:
                payload = json.load(response)

            if not isinstance(payload, dict):
                continue

            posts = payload.get("data")

            if isinstance(posts, list):
                total_mentions += len(posts)

        except (
            HTTPError,
            URLError,
            TimeoutError,
            json.JSONDecodeError,
        ):
            # Social data must never stop the market scanner.
            continue

    return total_mentions


def _twitter_points(
    mentions: int,
) -> int:
    """
    Convert recent X mentions into a maximum of 10 points.

    This deliberately has a small influence compared with trading data.
    """

    if mentions >= 100:
        return 10

    if mentions >= 50:
        return 8

    if mentions >= 25:
        return 6

    if mentions >= 10:
        return 4

    if mentions >= 5:
        return 2

    return 0


# ============================================================
# HARD SAFETY / TRADING FILTER
# ============================================================

def _hard_safety_filter(
    candidate: MemeCoinCandidate,
) -> tuple[bool, tuple[str, ...]]:
    """
    Reject candidates that do not meet the minimum market requirements.

    Passing these filters does NOT guarantee that a token is safe.
    """

    failures: list[str] = []

    liquidity = candidate.liquidity or 0
    volume_5m = candidate.volume_5m or 0
    volume_1h = candidate.volume_1h or 0

    # --------------------------------------------------------
    # Liquidity
    # --------------------------------------------------------

    if liquidity < MIN_LIQUIDITY_USD:
        failures.append(
            f"Liquidity below ${MIN_LIQUIDITY_USD:,.0f}"
        )

    # --------------------------------------------------------
    # Volume
    # --------------------------------------------------------

    if volume_5m < MIN_VOLUME_5M_USD:
        failures.append(
            f"5m volume below ${MIN_VOLUME_5M_USD:,.0f}"
        )

    if volume_1h < MIN_VOLUME_1H_USD:
        failures.append(
            f"1h volume below ${MIN_VOLUME_1H_USD:,.0f}"
        )

    # --------------------------------------------------------
    # Transactions / buy pressure
    # --------------------------------------------------------

    if (
        candidate.buys_5m is None
        or candidate.sells_5m is None
    ):
        failures.append(
            "5m transaction data unavailable"
        )

    else:
        total_transactions = (
            candidate.buys_5m
            + candidate.sells_5m
        )

        if total_transactions < MIN_TRANSACTIONS_5M:
            failures.append(
                f"Fewer than {MIN_TRANSACTIONS_5M} "
                "transactions in 5m"
            )

        buy_pressure = _buy_pressure_pct(candidate)

        if (
            buy_pressure is None
            or buy_pressure < MIN_BUY_PRESSURE_PCT
        ):
            failures.append(
                f"Buy pressure below "
                f"{MIN_BUY_PRESSURE_PCT}%"
            )

        if buy_pressure is not None:
            sell_pressure = 100 - buy_pressure

            if sell_pressure >= MAX_SELL_PRESSURE_PCT:
                failures.append(
                    f"Sell pressure at or above "
                    f"{MAX_SELL_PRESSURE_PCT}%"
                )

    # --------------------------------------------------------
    # Market cap / liquidity
    # --------------------------------------------------------

    ratio = _market_cap_liquidity_ratio(candidate)

    if (
        ratio is None
        or ratio > MAX_MARKET_CAP_LIQUIDITY_RATIO
    ):
        failures.append(
            "Market-cap/liquidity ratio too high "
            "or unavailable"
        )

    # --------------------------------------------------------
    # Age
    # --------------------------------------------------------

    age_days = _token_age_days(candidate)

    if (
        age_days is None
        or age_days < MIN_TOKEN_AGE_HOURS / 24
    ):
        failures.append(
            f"Token pair is younger than "
            f"{MIN_TOKEN_AGE_HOURS} hours"
        )

    # --------------------------------------------------------
    # Risk analysis
    # --------------------------------------------------------

    risk = _risk_analysis(candidate)

    if risk.serious_flags:
        failures.append(
            "Serious market-risk flag detected"
        )

    return (
        len(failures) == 0,
        tuple(failures),
    )


# ============================================================
# MAIN SCORING
# ============================================================

def _score_candidate(
    candidate: MemeCoinCandidate,
) -> ScoredMemeCoinCandidate | None:
    """
    Score a candidate.

    A candidate must:
      1. Pass the hard market/risk filters.
      2. Have enough X/Twitter backing.
      3. Finish with a score above 85.

    Only qualifying candidates are returned.
    """

    # --------------------------------------------------------
    # HARD FILTERS FIRST
    # --------------------------------------------------------

    passed_filters, _ = _hard_safety_filter(candidate)

    if not passed_filters:
        return None

    # --------------------------------------------------------
    # MARKET SCORE
    # --------------------------------------------------------

    liquidity_points = _points_for(
        candidate.liquidity,
        (
            (5_000, 6),
            (10_000, 12),
            (25_000, 17),
            (50_000, 20),
        ),
    )

    volume_points = _points_for(
        candidate.volume_5m,
        (
            (1_000, 5),
            (2_500, 10),
            (10_000, 15),
            (25_000, 18),
            (50_000, 20),
        ),
    )

    pressure_pct = _buy_pressure_pct(candidate)

    pressure_points = _points_for(
        pressure_pct,
        (
            (45, 5),
            (55, 10),
            (65, 15),
            (75, 20),
        ),
    )

    momentum_5m_points = _points_for(
        candidate.price_change_5m,
        (
            (0, 4),
            (5, 8),
            (10, 12),
            (20, 15),
        ),
    )

    momentum_1h_points = _points_for(
        candidate.price_change_1h,
        (
            (0, 2),
            (10, 5),
            (25, 8),
            (50, 10),
        ),
    )

    ratio = _market_cap_liquidity_ratio(candidate)

    ratio_points = 0

    if ratio is not None:
        if ratio <= 2:
            ratio_points = 15
        elif ratio <= 5:
            ratio_points = 12
        elif ratio <= 10:
            ratio_points = 8
        elif ratio <= 20:
            ratio_points = 4

    market_score = (
        liquidity_points
        + volume_points
        + pressure_points
        + momentum_5m_points
        + momentum_1h_points
        + ratio_points
    )

    # --------------------------------------------------------
    # X / TWITTER BACKING
    # --------------------------------------------------------

    twitter_mentions = _get_x_mentions(candidate)

    # Require actual social backing.
    if twitter_mentions < MIN_X_MENTIONS:
        return None

    twitter_points = _twitter_points(
        twitter_mentions
    )

    score = min(
        100,
        market_score + twitter_points,
    )

    # --------------------------------------------------------
    # RISK ADJUSTMENT
    # --------------------------------------------------------

    risk = _risk_analysis(candidate)

    adjusted_score = max(
        0,
        score - round(
            (100 - risk.score) * 0.5
        ),
    )

    # Serious risk flags can NEVER become a CALL.
    if risk.serious_flags:
        return None

    # User requested above 85.
    if adjusted_score < MIN_CALL_OUT_SCORE:
        return None

    # --------------------------------------------------------
    # REASONS
    # --------------------------------------------------------

    reasons = (
        (
            "🔥 Strong liquidity"
            if liquidity_points >= 17
            else "⚠️ Thin liquidity"
            if liquidity_points <= 6
            else "✅ Solid liquidity"
        ),
        (
            "🔥 High 5m volume"
            if volume_points >= 15
            else "⚠️ Low 5m volume"
            if volume_points <= 5
            else "✅ Active 5m volume"
        ),
        (
            "🔥 Strong buy pressure"
            if pressure_points >= 15
            else "⚠️ Weak buy pressure"
            if pressure_points <= 5
            else "✅ Positive buy pressure"
        ),
        (
            "🔥 Positive 5m momentum"
            if momentum_5m_points >= 8
            else "⚠️ Negative 5m momentum"
            if momentum_5m_points == 0
            else "✅ Mild 5m momentum"
        ),
        (
            "🔥 Positive 1h momentum"
            if momentum_1h_points >= 5
            else "⚠️ Negative 1h momentum"
            if momentum_1h_points == 0
            else "✅ Mild 1h momentum"
        ),
        (
            "🔥 Healthy market-cap/liquidity ratio"
            if ratio_points >= 12
            else "⚠️ High market-cap/liquidity ratio"
            if ratio_points <= 4
            else "✅ Acceptable "
            "market-cap/liquidity ratio"
        ),
        (
            f"🐦 X/Twitter backing: "
            f"{twitter_mentions} recent mentions"
        ),
    )

    return ScoredMemeCoinCandidate(
        candidate=candidate,
        market_score=market_score,
        score=adjusted_score,
        label="🔥 CALL",
        buy_pressure_pct=pressure_pct,
        reasons=reasons,
        risk=risk,
        twitter_mentions=twitter_mentions,
    )


# ============================================================
# DEXSCREENER PAIR HANDLING
# ============================================================

def _pair_rank(
    pair: dict[str, object],
) -> tuple[float, float, float]:
    liquidity = (
        _as_float(
            _metric(pair, "liquidity", "usd")
        )
        or 0
    )

    volume_1h = (
        _as_float(
            _metric(pair, "volume", "h1")
        )
        or 0
    )

    volume_5m = (
        _as_float(
            _metric(pair, "volume", "m5")
        )
        or 0
    )

    return (
        liquidity,
        volume_1h,
        volume_5m,
    )


def _candidate_from_pair(
    pair: dict[str, object],
) -> MemeCoinCandidate | None:
    base_token = pair.get("baseToken")

    if not isinstance(base_token, dict):
        return None

    address = base_token.get("address")
    symbol = base_token.get("symbol")
    name = base_token.get("name")

    if not all(
        isinstance(value, str) and value
        for value in (
            address,
            symbol,
            name,
        )
    ):
        return None

    market_cap = _as_float(
        pair.get("marketCap")
    )

    if market_cap is None:
        market_cap = _as_float(
            pair.get("fdv")
        )

    txns_5m = _metric(
        pair,
        "txns",
        "m5",
    )

    buys_5m = None
    sells_5m = None

    if isinstance(txns_5m, dict):
        buys_5m = _as_int(
            txns_5m.get("buys")
        )

        sells_5m = _as_int(
            txns_5m.get("sells")
        )

    return MemeCoinCandidate(
        mint_address=address,
        symbol=symbol,
        name=name,
        market_cap=market_cap,
        liquidity=_as_float(
            _metric(
                pair,
                "liquidity",
                "usd",
            )
        ),
        volume_5m=_as_float(
            _metric(
                pair,
                "volume",
                "m5",
            )
        ),
        volume_1h=_as_float(
            _metric(
                pair,
                "volume",
                "h1",
            )
        ),
        price_change_5m=_as_float(
            _metric(
                pair,
                "priceChange",
                "m5",
            )
        ),
        price_change_1h=_as_float(
            _metric(
                pair,
                "priceChange",
                "h1",
            )
        ),
        buys_5m=buys_5m,
        sells_5m=sells_5m,
        pair_created_at_ms=_as_int(
            pair.get("pairCreatedAt")
        ),
        market_url=(
            pair.get("url")
            if isinstance(
                pair.get("url"),
                str,
            )
            else None
        ),
    )


def _recent_solana_addresses(
    payload: object,
) -> list[str]:
    if not isinstance(payload, list):
        raise ScannerError(
            "Dexscreener returned an unexpected token list."
        )

    addresses: list[str] = []
    seen: set[str] = set()

    for token in payload:
        if (
            not isinstance(token, dict)
            or token.get("chainId") != "solana"
        ):
            continue

        address = token.get("tokenAddress")

        if (
            isinstance(address, str)
            and address
            and address.lower() not in seen
        ):
            seen.add(address.lower())
            addresses.append(address)

        if len(addresses) >= MAX_TOKENS_TO_FETCH:
            break

    return addresses


def _best_pair_per_token(
    payload: object,
) -> list[MemeCoinCandidate]:
    if (
        not isinstance(payload, dict)
        or not isinstance(
            payload.get("pairs"),
            list,
        )
    ):
        raise ScannerError(
            "Dexscreener returned an unexpected pair list."
        )

    pairs_by_token: dict[
        str,
        list[dict[str, object]],
    ] = {}

    for raw_pair in payload["pairs"]:
        if (
            not isinstance(raw_pair, dict)
            or raw_pair.get("chainId") != "solana"
        ):
            continue

        base_token = raw_pair.get(
            "baseToken"
        )

        if not isinstance(
            base_token,
            dict,
        ):
            continue

        address = base_token.get(
            "address"
        )

        if isinstance(address, str):
            pairs_by_token.setdefault(
                address.lower(),
                [],
            ).append(raw_pair)

    candidates: list[
        MemeCoinCandidate
    ] = []

    for pairs in pairs_by_token.values():
        candidate = _candidate_from_pair(
            max(
                pairs,
                key=_pair_rank,
            )
        )

        if candidate is not None:
            candidates.append(candidate)

    return sorted(
        candidates,
        key=lambda candidate: (
            candidate.volume_5m or 0,
            candidate.volume_1h or 0,
            candidate.liquidity or 0,
        ),
        reverse=True,
    )


# ============================================================
# MAIN SCANNER
# ============================================================

async def scan_recent_solana_tokens(
) -> list[ScoredMemeCoinCandidate]:
    """
    Fetch, filter and score Solana candidates.

    Only candidates that pass all strict filters and score 86+
    are returned.
    """

    boosted_tokens = await asyncio.to_thread(
        _get_json,
        TOKEN_BOOSTS_URL,
    )

    addresses = _recent_solana_addresses(
        boosted_tokens
    )

    if not addresses:
        return []

    pairs_url = (
        f"{TOKEN_PAIRS_URL}/"
        f"{','.join(addresses)}"
    )

    pair_data = await asyncio.to_thread(
        _get_json,
        pairs_url,
    )

    candidates = _best_pair_per_token(
        pair_data
    )

    scored_candidates: list[
        ScoredMemeCoinCandidate
    ] = []

    for candidate in candidates:
        scored = _score_candidate(
            candidate
        )

        if scored is not None:
            scored_candidates.append(
                scored
            )

    return sorted(
        scored_candidates,
        key=lambda candidate: (
            candidate.score,
            candidate.twitter_mentions,
            candidate.candidate.volume_5m or 0,
        ),
        reverse=True,
    )[:5]
```


