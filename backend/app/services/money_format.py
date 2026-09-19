"""Dollar amounts for generated documents (memo, deck, share page, charts)."""


def money(value: float, pattern: str = "{:,.0f}") -> str:
    """Sign first: -$2,116,364 (Python's f"${v:,.0f}" gives "$-2,116,364").
    A value that rounds to zero has no sign."""
    text = pattern.format(abs(value))
    negative = value < 0 and any(ch in "123456789" for ch in text)
    return f"-${text}" if negative else f"${text}"
