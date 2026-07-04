"""Orkaive backend package.

Module-level env loading only. No validation here — see `app.config.settings`
for `Settings`, and `app.main:lifespan` for runtime validation.
"""

from dotenv import load_dotenv

load_dotenv()
