import os


def _read_int_env(name: str, default: int = 0) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


ADMIN_ID = _read_int_env("ADMIN_ID")
