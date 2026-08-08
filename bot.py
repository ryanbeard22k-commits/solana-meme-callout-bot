"""Entry point for the Solana Meme Callout Bot."""

from solana_meme_callout_bot.app import create_application
from solana_meme_callout_bot.config import get_settings

def main() -> None:
"""Build the Telegram application and start long polling."""
settings = get_settings()
application = create_application(settings)

```
print("Solana Meme Callout Bot is running. Press Ctrl+C to stop.")
application.run_polling(allowed_updates=["message"])
```

if **name** == "**main**":
main()
