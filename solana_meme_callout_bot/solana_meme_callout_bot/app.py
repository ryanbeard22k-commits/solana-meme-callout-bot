"""Telegram application factory."""

from telegram.ext import Application, CommandHandler

from .config import Settings
from .handlers import (
auto_command,
autostatus_command,
scan_command,
start_command,
status_command,
stop_command,
)
from .monitoring import AutoMonitor

def create_application(settings: Settings) -> Application:
"""Create the Telegram application and register supported commands."""
application = (
Application.builder()
.token(settings.telegram_bot_token)
.build()
)

```
application.bot_data["auto_monitor"] = AutoMonitor()

application.add_handler(
    CommandHandler("start", start_command)
)
application.add_handler(
    CommandHandler("status", status_command)
)
application.add_handler(
    CommandHandler("scan", scan_command)
)
application.add_handler(
    CommandHandler("auto", auto_command)
)
application.add_handler(
    CommandHandler("stop", stop_command)
)
application.add_handler(
    CommandHandler("autostatus", autostatus_command)
)

return application
```
