"""Process event loops for PostgreSQL-backed runtimes on supported hosts."""

import asyncio
import sys


def create_event_loop() -> asyncio.AbstractEventLoop:
    """Use the selector required by psycopg async connections on Windows."""
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop()
    return asyncio.new_event_loop()
