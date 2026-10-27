# Solana SPL payment verifier

A dependency-free Python 3.10+ command-line tool that verifies an SPL-token
payment from Solana JSON-RPC data. It is read-only: it never holds a private key
and never creates, signs, or sends a transaction.

## Quick start

```bash
python3 verify_payment.py TRANSACTION_SIGNATURE \
  --recipient RECIPIENT_WALLET \
  --sender SENDER_WALLET \
  --mint TOKEN_MINT \
  --amount 25.50 \
  --finality finalized
```

`--sender` is optional. Omitting it proves that the expected recipient gained
the tokens, without asserting which wallet funded the transfer.

Useful options:

| Option | Meaning |
|---|---|
| `--recipient` | Required wallet owner expected to receive tokens |
| `--mint` | Required SPL token mint address |
| `--amount` | Required minimum amount in display units, parsed exactly |
| `--sender` | Optional wallet owner expected to fund the payment |
| `--finality` | `confirmed` (default) or safer `finalized` |
| `--rpc-url` | RPC endpoint; default is Solana mainnet-beta |
| `--timeout` | Positive request timeout in seconds; default `15` |

The well-known native USDC mint on Solana mainnet is
`EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`. Always confirm the mint and
network for the asset you intend to accept; the RPC URL determines the network.

## What is verified

1. `getSignatureStatuses` finds the signature, confirms no execution error,
   and enforces at least the requested confirmation level.
2. `getTransaction` obtains the transaction execution metadata.
3. Pre/post token balances are filtered by the exact mint and grouped by wallet
   owner, including wallets with multiple token accounts.
4. The recipient's total increase must be at least the expected amount.
5. When `--sender` is present, that owner's total decrease must also be at least
   the expected amount.

Amounts use `Decimal`, never binary floating point. `processed` finality is
intentionally refused because it is unsafe for payment acceptance.

## Output and integration

Success prints one JSON object and exits `0`:

```json
{
  "verified": true,
  "signature": "...",
  "slot": 123,
  "confirmation_status": "finalized",
  "mint": "...",
  "recipient": "...",
  "expected_amount": "25.50",
  "received_amount": "25.500000",
  "sender": "...",
  "sender_decrease": "25.500000",
  "block_time": 1700000000
}
```

Failure prints `{"verified": false, "error": "..."}` and exits `2`. Failures
include an unknown or failed transaction, insufficient finality, wrong
mint/recipient/sender, insufficient amount, malformed metadata, RPC errors,
timeouts, and invalid amounts.

## Security and operational limits

- The verifier is stateless. A production checkout **must store consumed
  signatures** and reject reuse, ideally associating each signature with a
  unique invoice or order. Otherwise one valid transfer could be presented
  more than once.
- Verification proves the net balance change within one transaction. It does
  not decode a memo or business order reference.
- The default public RPC may rate-limit requests. Use a trusted private RPC for
  production and `--finality finalized` when settlement certainty matters.
- The tool verifies an SPL token transfer, not native SOL balance changes.
- No secret should be placed in command arguments. If an RPC provider embeds a
  credential in its URL, supply it through protected process configuration.

## Tests and quality checks

```bash
python3 -m pytest -q
python3 -m py_compile verify_payment.py
```

The 20 deterministic tests cover success, overpayment, optional sender,
processed/pending/failed transactions, wrong mint, insufficient balances,
missing signatures, RPC errors and network exceptions, exact decimal parsing,
unsafe-finality rejection, and machine-readable CLI errors. Tests need no
wallet, private key, API token, or funded transaction.

## Specification coverage

The OpenTask asks for a small end-to-end Solana payment automation/check. This
delivery performs the complete read-only verification path from transaction
signature to finality, successful execution, correct SPL mint, exact recipient
increase, optional sender decrease, and a machine-readable decision suitable
for automation.
