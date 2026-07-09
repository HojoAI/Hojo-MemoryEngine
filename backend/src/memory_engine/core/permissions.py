"""API key permission matching with wildcard support."""


def permission_granted(granted: set[str], required: str) -> bool:
    """Return True if any granted pattern covers the required permission."""
    if required in granted:
        return True
    for pattern in granted:
        if pattern == "*":
            return True
        if pattern.endswith(":*"):
            prefix = pattern[:-1]
            if required == prefix.rstrip(":") or required.startswith(prefix):
                return True
    return False
