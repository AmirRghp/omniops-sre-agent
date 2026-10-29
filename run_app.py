"""Entrypoint runner for Chainlit on Windows with proper event loop and clean data layer."""

import asyncio
import os
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Unset DATABASE_URL from os.environ so Chainlit does not mistakenly treat SQLAlchemy's URL
# as Chainlit's internal thread data layer (which expects postgresql:// and causes DSN error).
# OmniOps uses LangGraph's AsyncPostgresSaver for complete durable state persistence.
if "DATABASE_URL" in os.environ and "postgresql+asyncpg" in os.environ["DATABASE_URL"]:
    del os.environ["DATABASE_URL"]

from chainlit.cli import run_chainlit

if __name__ == "__main__":
    port = os.environ.get("CHAINLIT_PORT", "8001")
    os.environ["CHAINLIT_PORT"] = port
    run_chainlit("app.py")
