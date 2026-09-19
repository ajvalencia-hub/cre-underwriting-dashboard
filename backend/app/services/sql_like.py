"""LIKE-pattern escaping for user-supplied search text.

SQLAlchemy parametrizes the value (no injection), but `%` and `_` are still
LIKE metacharacters: a query of `__` matched every row and `%` disabled a
filter entirely. Every user-facing LIKE/ILIKE goes through `contains()` so
the text is matched literally, with a backslash as the escape character.
"""

LIKE_ESCAPE = "\\"


def escape_like(text: str) -> str:
    return (
        text.replace(LIKE_ESCAPE, LIKE_ESCAPE + LIKE_ESCAPE)
        .replace("%", LIKE_ESCAPE + "%")
        .replace("_", LIKE_ESCAPE + "_")
    )


def contains(text: str) -> str:
    """`%text%` with the text itself escaped — pass with `escape=LIKE_ESCAPE`."""
    return f"%{escape_like(text)}%"
