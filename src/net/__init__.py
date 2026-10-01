import aiohttp

_session: aiohttp.ClientSession | None = None


def session() -> aiohttp.ClientSession:
    """Shared HTTP session so connections are reused between requests."""
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession()
    return _session


async def close() -> None:
    if _session is not None and not _session.closed:
        await _session.close()
