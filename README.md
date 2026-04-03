# VeriScore

VeriScore is a Python 3.11 demo that scores wallet reputation across Solana and major EVM chains, then adds a verifiable OpenGradient TEE inference layer on top of the deterministic score.

## Setup

1. `pip install -r requirements.txt`
2. `opengradient config init`
3. Fund the configured Base Sepolia wallet with test `$OPG`
4. Copy `.env.example` to `.env` and fill in the required keys
5. `uvicorn src.api:app --reload`

The API runs on port `8000` by default. You can open `index.html` directly or visit `http://localhost:8000/`.

## API

- `POST /score`
  Body: `{"wallet_address":"<address>","chain":"solana|ethereum|base|arbitrum|optimism|polygon"}`
- `GET /score/{chain}/{wallet_address}`
- `GET /score/{wallet_address}`
  Backward-compatible Solana shortcut
- `GET /verify/{chain}/{wallet_address}`
- `DELETE /score/{chain}/{wallet_address}`
- `GET /chains`
- `GET /health`

Each score response follows the frontend contract:

```json
{
  "score": 91,
  "explanation": "Long-lived wallet with strong repayment behavior and no recent liquidation signals.",
  "attestation": {
    "payment_hash": "0x...",
    "proof_url": "https://explorer.opengradient.ai/proof/...",
    "raw": {}
  },
  "model": "TEE_LLM",
  "chain": "ethereum",
  "wallet": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
  "scored_at": "2026-04-03T12:00:00Z",
  "cached": false,
  "cache_expires_at": "2026-04-03T13:00:00Z"
}
```

## Attestation & Verifiability

VeriScore returns OpenGradient attestation metadata in every score response.

- `attestation.payment_hash` is the payment-linked reference returned by the OpenGradient SDK.
- `attestation.proof_url` is built when a real proof or TEE attestation reference is present.
- `attestation.raw` preserves all captured proof fields for downstream verification tooling.

To verify a result:

1. Call a score endpoint or `GET /verify/{chain}/{wallet_address}`.
2. Open `attestation.proof_url`.
3. Confirm the explorer record matches the wallet, model, and inference timing you expect.

## Chains Supported

| Chain Slug | Indexer Used | Data Quality |
| --- | --- | --- |
| `solana` | Helius Enhanced Transactions | Full |
| `ethereum` | Alchemy Enhanced APIs for decoded protocol signals, Etherscan V2 for aggregate activity metrics | Full |
| `base` | Alchemy Enhanced APIs for decoded protocol signals, Etherscan V2 for aggregate activity metrics | Full |
| `arbitrum` | Alchemy Enhanced APIs for decoded protocol signals, Etherscan V2 for aggregate activity metrics | Full |
| `optimism` | Alchemy Enhanced APIs for decoded protocol signals, Etherscan V2 for aggregate activity metrics | Full |
| `polygon` | Alchemy Enhanced APIs for decoded protocol signals, Etherscan V2 for aggregate activity metrics | Full |

If Alchemy is unavailable, EVM protocol counts, repayments, and liquidations fall back to the older Etherscan-based heuristic path.

## Caching

Scores are cached in-memory for 1 hour.

- TTL: `3600` seconds
- Cache hit behavior: score endpoints return the cached payload with `"cached": true`
- Cache miss behavior: the wallet is re-fetched and re-scored, then cached with a fresh `cache_expires_at`
- Cache bust: `DELETE /score/{chain}/{wallet_address}`

`GET /verify/{chain}/{wallet_address}` reads the latest cached score and returns its attestation block without re-running inference.

## Environment Variables

| Variable | Required | Purpose |
| --- | --- | --- |
| `ALCHEMY_API_KEY` | EVM only | Decoded EVM transfers, protocol interactions, repayment detection, liquidation detection |
| `HELIUS_API_KEY` | Solana only | Solana enhanced transaction history |
| `ETHERSCAN_API_KEY` | EVM only | EVM fallback and aggregate account/token metrics |
| `OG_PRIVATE_KEY` | For TEE scoring | OpenGradient inference, Permit2 approval, and OPG health checks |

Example:

```bash
HELIUS_API_KEY=your_helius_key_here
ETHERSCAN_API_KEY=your_etherscan_v2_key_here
ALCHEMY_API_KEY=your_alchemy_api_key_here
OG_PRIVATE_KEY=0x_your_base_sepolia_private_key_here
```

## Smoke Test

Run:

```bash
python tests/smoke_test.py
```

The smoke script:

1. Loads `.env`
2. Scores a public Solana address
3. Scores Vitalik's Ethereum wallet
4. Prints the score, cache state, payment hash, proof URL, and timestamp
5. Exits `0` only if both scores are integers between `0` and `100`

You can override the default Solana address with `VERISCORE_SMOKE_SOLANA_WALLET`.
