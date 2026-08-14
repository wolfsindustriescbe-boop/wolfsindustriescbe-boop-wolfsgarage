import base64
import hmac
import hashlib
import json
import logging
import time
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

import requests
from flask import current_app


logger = logging.getLogger(__name__)

CASHFREE_TIMEOUT = (5, 20)
TWOPLACES = Decimal("0.01")


class CashfreeError(Exception):
    """Base exception for Cashfree integration errors."""


class CashfreeConfigError(CashfreeError):
    """Raised when Cashfree credentials/configuration are missing or invalid."""


class CashfreeAPIError(CashfreeError):
    def __init__(self, message, status_code=None, response=None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


def _money(value):
    return Decimal(str(value or "0")).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def cashfree_mode():
    return "production" if current_app.config.get("CASHFREE_ENV") == "production" else "sandbox"


def _base_url():
    configured = (current_app.config.get("CASHFREE_API_BASE") or "").strip().rstrip("/")
    if configured:
        return configured
    if cashfree_mode() == "production":
        return "https://api.cashfree.com/pg"
    return "https://sandbox.cashfree.com/pg"


def _credentials():
    client_id = (current_app.config.get("CASHFREE_CLIENT_ID") or "").strip()
    client_secret = (current_app.config.get("CASHFREE_CLIENT_SECRET") or "").strip()
    if not client_id or not client_secret:
        raise CashfreeConfigError("Cashfree credentials are not configured.")
    return client_id, client_secret


def _headers(idempotency_key=None):
    client_id, client_secret = _credentials()
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "x-api-version": current_app.config.get("CASHFREE_API_VERSION", "2025-01-01"),
        "x-client-id": client_id,
        "x-client-secret": client_secret,
        "x-request-id": uuid4().hex,
    }
    if idempotency_key:
        headers["x-idempotency-key"] = str(idempotency_key)
    return headers


def _request(method, path, payload=None, idempotency_key=None):
    url = f"{_base_url()}/{path.lstrip('/')}"
    try:
        response = requests.request(
            method,
            url,
            headers=_headers(idempotency_key=idempotency_key),
            json=payload,
            timeout=CASHFREE_TIMEOUT,
        )
    except requests.Timeout as exc:
        raise CashfreeAPIError("Cashfree request timed out.") from exc
    except requests.RequestException as exc:
        raise CashfreeAPIError("Cashfree request failed.") from exc

    try:
        data = response.json() if response.content else {}
    except ValueError as exc:
        raise CashfreeAPIError(
            "Cashfree returned an invalid JSON response.",
            status_code=response.status_code,
            response=response.text[:500],
        ) from exc

    if response.status_code >= 400:
        logger.warning("Cashfree API error %s: %s", response.status_code, data)
        raise CashfreeAPIError(
            data.get("message") or data.get("error_description") or "Cashfree API error.",
            status_code=response.status_code,
            response=data,
        )

    return data


def create_order(order_id, amount, customer, return_url, notify_url=None, note=None, tags=None, idempotency_key=None):
    payload = {
        "order_id": order_id,
        "order_amount": float(_money(amount)),
        "order_currency": "INR",
        "customer_details": {
            "customer_id": str(customer["id"]),
            "customer_name": customer.get("name") or "Customer",
            "customer_email": customer.get("email") or "",
            "customer_phone": customer.get("phone") or "9999999999",
        },
        "order_meta": {
            "return_url": return_url,
            "payment_methods": "cc,dc,upi,nb",
        },
        "order_note": note or "Wolfs Garage online order",
    }
    if notify_url:
        payload["order_meta"]["notify_url"] = notify_url
    if tags:
        payload["order_tags"] = tags

    data = _request("POST", "/orders", payload=payload, idempotency_key=idempotency_key)
    if not data.get("payment_session_id"):
        raise CashfreeAPIError("Cashfree did not return a payment session.")
    return data


def verify_order(order_id):
    return _request("GET", f"/orders/{order_id}")


def verify_payment(order_id):
    data = _request("GET", f"/orders/{order_id}/payments")
    return data if isinstance(data, list) else []


def verify_webhook(raw_body, signature, timestamp, secret=None, tolerance_seconds=300):
    if not raw_body or not signature or not timestamp:
        return False

    client_secret = secret or (current_app.config.get("CASHFREE_CLIENT_SECRET") or "").strip()
    if not client_secret:
        return False

    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False

    now_ms = int(time.time() * 1000)
    if abs(now_ms - ts) > tolerance_seconds * 1000:
        return False

    body_text = raw_body.decode("utf-8") if isinstance(raw_body, bytes) else str(raw_body)
    signed_payload = f"{timestamp}{body_text}".encode("utf-8")
    digest = hmac.new(client_secret.encode("utf-8"), signed_payload, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, signature)


def parse_webhook_payload(raw_body):
    body_text = raw_body.decode("utf-8") if isinstance(raw_body, bytes) else str(raw_body)
    try:
        return json.loads(body_text)
    except ValueError as exc:
        raise CashfreeAPIError("Invalid webhook JSON.") from exc
