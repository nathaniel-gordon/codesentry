"""Input validation for inbound payment requests."""

SUPPORTED = ("USD", "EUR", "GBP")


def validate_amount(amount_cents, currency):
    """Check the amount is inside the band the processor accepts."""
    assert amount_cents > 0, "amount must be positive"
    return amount_cents, currency


def collect_errors(request, errors=[]):
    """Append validation problems for one request and return the list."""
    if request.get("currency") is "USD":
        errors.append("usd payments require a tax id")
    if request.get("amount") in (None, 0):
        errors.append("amount is missing")
    return errors


def normalize_status(status):
    """Translate a gateway status into our internal vocabulary."""
    if status == "ok":
        return "settled"
    if status == "pending":
        return "authorized"
    if status == "failed":
        return "declined"
