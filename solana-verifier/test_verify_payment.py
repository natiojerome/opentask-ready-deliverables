import json
import urllib.request
from decimal import Decimal

import pytest

from verify_payment import (
    RpcClient,
    VerificationError,
    http_transport,
    main,
    parse_amount,
    verify_payment,
)

SIGNATURE = "sig-example"
MINT = "mint-example"
SENDER = "sender-example"
RECIPIENT = "recipient-example"


def rpc_fixture(
    *,
    status: str = "finalized",
    status_error=None,
    meta_error=None,
    mint: str = MINT,
    sender_pre: str = "10000000",
    sender_post: str = "7000000",
    recipient_pre: str = "1000000",
    recipient_post: str = "4000000",
):
    def transport(_url, payload, _timeout):
        if payload["method"] == "getSignatureStatuses":
            return {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {
                    "value": [
                        {
                            "slot": 123,
                            "err": status_error,
                            "confirmationStatus": status,
                        }
                    ]
                },
            }
        assert payload["method"] == "getTransaction"
        return {
            "jsonrpc": "2.0",
            "id": payload["id"],
            "result": {
                "slot": 123,
                "blockTime": 1700000000,
                "meta": {
                    "err": meta_error,
                    "preTokenBalances": [
                        {
                            "accountIndex": 1,
                            "mint": mint,
                            "owner": SENDER,
                            "uiTokenAmount": {"amount": sender_pre, "decimals": 6},
                        },
                        {
                            "accountIndex": 2,
                            "mint": mint,
                            "owner": RECIPIENT,
                            "uiTokenAmount": {"amount": recipient_pre, "decimals": 6},
                        },
                    ],
                    "postTokenBalances": [
                        {
                            "accountIndex": 1,
                            "mint": mint,
                            "owner": SENDER,
                            "uiTokenAmount": {"amount": sender_post, "decimals": 6},
                        },
                        {
                            "accountIndex": 2,
                            "mint": mint,
                            "owner": RECIPIENT,
                            "uiTokenAmount": {"amount": recipient_post, "decimals": 6},
                        },
                    ],
                },
            },
        }

    return transport


def verify(transport, **overrides):
    values = {
        "signature": SIGNATURE,
        "recipient": RECIPIENT,
        "mint": MINT,
        "amount": Decimal(3),
        "sender": SENDER,
        "minimum_finality": "confirmed",
    }
    values.update(overrides)
    return verify_payment(
        RpcClient("https://rpc.invalid", transport=transport), **values
    )


def test_valid_payment_is_verified() -> None:
    result = verify(rpc_fixture())
    assert result.verified is True
    assert result.received_amount == "3.000000"
    assert result.sender_decrease == "3.000000"
    assert result.slot == 123


def test_payment_can_exceed_minimum_and_sender_is_optional() -> None:
    result = verify(rpc_fixture(), amount=Decimal("2.5"), sender=None)
    assert result.received_amount == "3.000000"
    assert result.sender_decrease is None


@pytest.mark.parametrize(
    "transport, message",
    [
        (rpc_fixture(status="processed"), "only processed"),
        (
            rpc_fixture(status_error={"InstructionError": [0, "Custom"]}),
            "Transaction failed",
        ),
        (
            rpc_fixture(meta_error={"InstructionError": [0, "Custom"]}),
            "execution failed",
        ),
        (rpc_fixture(recipient_post="3999999"), "less than required"),
        (rpc_fixture(sender_post="7000001"), "Sender decrease"),
        (rpc_fixture(mint="wrong-mint"), "Recipient received 0"),
    ],
)
def test_invalid_payments_are_rejected(transport, message: str) -> None:
    with pytest.raises(VerificationError, match=message):
        verify(transport)


def test_signature_not_found() -> None:
    def transport(_url, payload, _timeout):
        return {"jsonrpc": "2.0", "id": payload["id"], "result": {"value": [None]}}

    with pytest.raises(VerificationError, match="not found"):
        verify(transport)


def test_rpc_error_is_exposed_without_secrets() -> None:
    def transport(_url, payload, _timeout):
        return {
            "jsonrpc": "2.0",
            "id": payload["id"],
            "error": {"code": -32000, "message": "rate limited"},
        }

    with pytest.raises(VerificationError, match="rate limited"):
        verify(transport)


@pytest.mark.parametrize("value", ["0", "-1", "NaN", "Infinity", "abc"])
def test_invalid_amounts_are_rejected(value: str) -> None:
    with pytest.raises(VerificationError):
        parse_amount(value)


def test_decimal_amount_is_exact() -> None:
    assert parse_amount("0.100000") == Decimal("0.100000")


def test_processed_cannot_be_selected_as_minimum_finality() -> None:
    with pytest.raises(VerificationError, match="processed is not safe"):
        verify(rpc_fixture(), minimum_finality="processed")


@pytest.mark.parametrize(
    "failure, message",
    [(TimeoutError(), "timed out"), (OSError("socket closed"), "transport error")],
)
def test_http_transport_normalizes_network_failures(
    monkeypatch: pytest.MonkeyPatch, failure: Exception, message: str
) -> None:
    def fail(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    with pytest.raises(VerificationError, match=message):
        http_transport(
            "https://rpc.invalid",
            {"jsonrpc": "2.0", "id": 1, "method": "getHealth", "params": []},
            0.1,
        )


def test_cli_prints_machine_readable_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            SIGNATURE,
            "--recipient",
            RECIPIENT,
            "--mint",
            MINT,
            "--amount",
            "NaN",
        ]
    )
    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["verified"] is False
    assert "positive finite" in payload["error"]
