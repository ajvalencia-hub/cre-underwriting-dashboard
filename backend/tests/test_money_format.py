from app.services.memo_service import format_value
from app.services.money_format import money


def test_negative_dollars_put_the_sign_first():
    assert format_value(-2_116_364.4, "currency") == "-$2,116,364"
    assert format_value(2_116_364, "currency") == "$2,116,364"
    assert money(-0.4) == "$0"
    assert money(-1.25, "{:,.1f}M") == "-$1.2M"
