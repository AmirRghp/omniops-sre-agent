"""Shared pytest configuration for the OmniOps test suite."""

import asyncio
import sys

# psycopg's async connections (used by AsyncPostgresSaver) cannot run on the
# ProactorEventLoop, which is the Windows default for asyncio.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
