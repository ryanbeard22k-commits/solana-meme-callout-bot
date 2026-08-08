"""Runtime configuration loaded from environment variables."""

from dataclasses import dataclass
import os

@dataclass(frozen=True)
class Settings:
"""Settings required to connect to Telegram."""

```
telegram_bot_token: str
```

def get_settings() -> Settings:
"""Load settings and fail clearly when the token is missing."""
token = os.getenv("TELEGRAM_BOT_TOKEN")

```
if not token:
    raise RuntimeError(
        "TELEGRAM_BOT_TOKEN is not set. "
        "Add it as a Railway environment variable."
    )

return Settings(telegram_bot_token=token)
```
