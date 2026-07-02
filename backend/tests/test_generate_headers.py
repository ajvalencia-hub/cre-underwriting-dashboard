"""Regression tests for FINDINGS.md H6: Content-Disposition must survive
non-ASCII and quote-containing template filenames (ASGI headers are latin-1).
"""

from urllib.parse import unquote

from app.routers.generate import _content_disposition


def test_plain_ascii_filename_unchanged():
    header = _content_disposition("model.xlsx")
    assert 'filename="model.xlsx"' in header
    header.encode("latin-1")  # must not raise


def test_non_ascii_filename_is_latin1_safe_and_carried_in_rfc5987():
    header = _content_disposition("Modèle Financier.xlsx")
    header.encode("latin-1")  # pre-fix: UnicodeEncodeError -> 500 on download
    # The real name round-trips through the RFC 5987 parameter:
    encoded = header.split("filename*=UTF-8''")[1]
    assert unquote(encoded) == "Modèle Financier.xlsx"


def test_embedded_double_quote_cannot_break_the_header():
    header = _content_disposition('my "final" model.xlsx')
    fallback = header.split('filename="')[1].split('"')[0]
    assert '"' not in fallback
    header.encode("latin-1")
