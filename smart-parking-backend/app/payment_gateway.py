"""
A PRETEND payment gateway, so the whole booking flow can be demonstrated
without a real payment company (the SRS lists real payments as "future").

HOW A REAL GATEWAY WORKS (Razorpay, Stripe, PayU ...):
  1. Our server asks the gateway to create an "order" for the amount.
  2. The customer pays on the gateway's own screen (card numbers never touch our server).
  3. The gateway tells us the result, and we CHECK its signature before trusting it.

To plug in a real one, replace the two functions below. Nothing else changes.

DEMO RULES (so you can show both outcomes to your examiner):
  UPI : any valid id like  name@upi  succeeds.   An id starting with "fail" (fail@upi) is declined.
  CARD: send  card_token = "tok_ok"  to succeed, or  "tok_fail"  to be declined.
        (A real gateway gives the browser a token instead of exposing card numbers.)
"""
import re
import secrets

UPI_RE = re.compile(r"^[A-Za-z0-9.\-_]{2,}@[A-Za-z]{2,}$")


def create_order(method, amount):
    """Step 1: get a reference number for this payment attempt."""
    return "TXN" + secrets.token_hex(6).upper()


def verify_payment(method, payload):
    """
    Step 3: decide whether the payment went through.
    Returns (True, "") on success or (False, "reason") on failure.
    """
    if method == "UPI":
        upi_id = str(payload.get("upi_id", "")).strip()
        if not UPI_RE.match(upi_id):
            return False, "Please enter a valid UPI ID such as name@upi."
        if upi_id.lower().startswith("fail"):
            return False, "The payment was declined by the bank (demo)."
        return True, ""

    if method == "CARD":
        token = str(payload.get("card_token", "")).strip()
        if not token:
            return False, "A card token is required. Never send raw card numbers."
        if token == "tok_fail":
            return False, "The card was declined (demo)."
        return True, ""

    return False, "Unsupported payment method."
