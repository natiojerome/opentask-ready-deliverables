#!/usr/bin/env python3
"""Verify an SPL-token payment from a Solana transaction signature."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

DEFAULT_RPC_URL = "https://api.mainnet-beta.solana.com"
FINALITY_RANK = {"processed": 0, "confirmed": 1, "finalized": 2}


class VerificationError(ValueError):
    """Raised when a payment cannot be proven from the transaction."""


Transport = Callable[[str, dict[str, Any], float], dict[str, Any]]


@dataclass(frozen=True)
class VerificationResult:
    verified: bool
    signature: str
    slot: int
    confirmation_status: str
    mint: str
    recipient: str
    expected_amount: str
    received_amount: str
    sender: str | None
    sender_decrease: str | None
    block_time: int | None


def http_transport(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "user-agent": "natio-solana-verifier/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise VerificationError(f"RPC HTTP error {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise VerificationError(f"RPC connection error: {exc.reason}") from exc
    except TimeoutError as exc:
        raise VerificationError("RPC request timed out") from exc
    except OSError as exc:
        raise VerificationError(f"RPC transport error: {exc}") from exc
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise VerificationError("RPC returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise VerificationError("RPC returned an unexpected response")
    return parsed


class RpcClient:
    def __init__(
        self,
        url: str = DEFAULT_RPC_URL,
        *,
        timeout: float = 15.0,
        transport: Transport = http_transport,
    ) -> None:
        self.url = url
        self.timeout = timeout
        self.transport = transport
        self._request_id = 0

    def call(self, method: str, params: list[Any]) -> Any:
        self._request_id += 1
        response = self.transport(
            self.url,
            {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": method,
                "params": params,
            },
            self.timeout,
        )
        if response.get("error") is not None:
            error = response["error"]
            message = (
                error.get("message", str(error))
                if isinstance(error, dict)
                else str(error)
            )
            raise VerificationError(f"RPC {method} failed: {message}")
        if "result" not in response:
            raise VerificationError(f"RPC {method} response has no result")
        return response["result"]


def parse_amount(value: str) -> Decimal:
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise VerificationError(f"Invalid amount: {value!r}") from exc
    if not amount.is_finite() or amount <= 0:
        raise VerificationError("Amount must be a positive finite decimal")
    return amount


def token_amount(entry: dict[str, Any]) -> Decimal:
    ui = entry.get("uiTokenAmount")
    if not isinstance(ui, dict):
        raise VerificationError("Transaction contains a malformed token balance")
    raw = ui.get("amount")
    decimals = ui.get("decimals")
    if not isinstance(raw, str) or not isinstance(decimals, int) or decimals < 0:
        raise VerificationError("Transaction contains a malformed token amount")
    try:
        return Decimal(raw).scaleb(-decimals)
    except InvalidOperation as exc:
        raise VerificationError(
            "Transaction contains a non-numeric token amount"
        ) from exc


def balances_by_owner(entries: Any, mint: str) -> tuple[dict[str, Decimal], set[int]]:
    if entries is None:
        return {}, set()
    if not isinstance(entries, list):
        raise VerificationError("Transaction token balances are malformed")
    balances: dict[str, Decimal] = {}
    indexes: set[int] = set()
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("mint") != mint:
            continue
        owner = entry.get("owner")
        account_index = entry.get("accountIndex")
        if not isinstance(owner, str) or not isinstance(account_index, int):
            continue
        balances[owner] = balances.get(owner, Decimal(0)) + token_amount(entry)
        indexes.add(account_index)
    return balances, indexes


def verify_payment(
    client: RpcClient,
    *,
    signature: str,
    recipient: str,
    mint: str,
    amount: Decimal,
    sender: str | None = None,
    minimum_finality: str = "confirmed",
) -> VerificationResult:
    if minimum_finality not in {"confirmed", "finalized"}:
        raise VerificationError(
            "Minimum finality must be confirmed or finalized; processed is not safe for payment verification"
        )

    statuses = client.call(
        "getSignatureStatuses", [[signature], {"searchTransactionHistory": True}]
    )
    values = statuses.get("value") if isinstance(statuses, dict) else None
    status = values[0] if isinstance(values, list) and values else None
    if not isinstance(status, dict):
        raise VerificationError("Transaction signature was not found")
    if status.get("err") is not None:
        raise VerificationError(f"Transaction failed: {status['err']}")
    confirmation_status = status.get("confirmationStatus")
    if confirmation_status not in FINALITY_RANK:
        raise VerificationError("Transaction has no recognized confirmation status")
    if FINALITY_RANK[confirmation_status] < FINALITY_RANK[minimum_finality]:
        raise VerificationError(
            f"Transaction is only {confirmation_status}; {minimum_finality} is required"
        )

    transaction = client.call(
        "getTransaction",
        [
            signature,
            {
                "encoding": "jsonParsed",
                "commitment": minimum_finality,
                "maxSupportedTransactionVersion": 0,
            },
        ],
    )
    if not isinstance(transaction, dict):
        raise VerificationError("Confirmed transaction details are unavailable")
    meta = transaction.get("meta")
    if not isinstance(meta, dict):
        raise VerificationError("Transaction metadata is unavailable")
    if meta.get("err") is not None:
        raise VerificationError(f"Transaction execution failed: {meta['err']}")

    pre, _ = balances_by_owner(meta.get("preTokenBalances"), mint)
    post, _ = balances_by_owner(meta.get("postTokenBalances"), mint)
    received = post.get(recipient, Decimal(0)) - pre.get(recipient, Decimal(0))
    if received < amount:
        raise VerificationError(
            f"Recipient received {received} {mint}, less than required {amount}"
        )

    sender_decrease: Decimal | None = None
    if sender is not None:
        sender_decrease = pre.get(sender, Decimal(0)) - post.get(sender, Decimal(0))
        if sender_decrease < amount:
            raise VerificationError(
                f"Sender decrease is {sender_decrease} {mint}, less than required {amount}"
            )

    slot = transaction.get("slot")
    if not isinstance(slot, int):
        raise VerificationError("Transaction slot is missing")
    block_time = transaction.get("blockTime")
    if block_time is not None and not isinstance(block_time, int):
        raise VerificationError("Transaction block time is malformed")

    return VerificationResult(
        verified=True,
        signature=signature,
        slot=slot,
        confirmation_status=confirmation_status,
        mint=mint,
        recipient=recipient,
        expected_amount=format(amount, "f"),
        received_amount=format(received, "f"),
        sender=sender,
        sender_decrease=format(sender_decrease, "f")
        if sender_decrease is not None
        else None,
        block_time=block_time,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("signature", help="Solana transaction signature")
    parser.add_argument(
        "--recipient", required=True, help="Expected recipient wallet owner"
    )
    parser.add_argument("--mint", required=True, help="Expected SPL token mint")
    parser.add_argument(
        "--amount", required=True, help="Minimum amount in UI token units"
    )
    parser.add_argument("--sender", help="Optional expected sender wallet owner")
    parser.add_argument(
        "--finality",
        choices=("confirmed", "finalized"),
        default="confirmed",
        help="Minimum finality",
    )
    parser.add_argument(
        "--rpc-url", default=DEFAULT_RPC_URL, help="Solana JSON-RPC URL"
    )
    parser.add_argument(
        "--timeout", type=float, default=15.0, help="RPC timeout in seconds"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.timeout <= 0:
            raise VerificationError("Timeout must be positive")
        result = verify_payment(
            RpcClient(args.rpc_url, timeout=args.timeout),
            signature=args.signature,
            recipient=args.recipient,
            mint=args.mint,
            amount=parse_amount(args.amount),
            sender=args.sender,
            minimum_finality=args.finality,
        )
    except VerificationError as exc:
        print(json.dumps({"verified": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(asdict(result), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
