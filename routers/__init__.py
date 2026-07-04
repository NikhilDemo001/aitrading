"""FastAPI routers extracted from main.py (see docs/AUDIT-2026-07-04.md P3-14).

Each module exposes `router` (an APIRouter) and, where it needs main-owned state
(IST clock, live client config), a `configure(...)` function main calls before
`app.include_router(...)` — dependency injection instead of circular imports.
"""
