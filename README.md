# VeriScore

VeriScore is a wallet reputation and trust-scoring tool for Solana and major EVM chains. It combines:

- on-chain activity fetching
- a deterministic scoring engine
- an optional OpenGradient Trusted Execution Environment (TEE) inference layer
- attestation metadata so callers can verify how a score was produced

The project includes a FastAPI backend and a single-file frontend in `index.html` styled to match the OpenGradient visual language.

## What VeriScore Does

Given a wallet address, VeriScore:

1. Detects or accepts the target chain
2. Fetches wallet activity from supported indexers
3. Normalizes that activity into a shared metric schema
4. Computes a deterministic score from those metrics
5. Optionally sends the normalized payload to OpenGradient for TEE inference
6. Returns the final score, explanation, attestation metadata, cache state, and timestamp

The result is a wallet score that is easy to consume in a frontend, API integration, demo, or attested trust workflow.

## Core Features

- Multichain wallet scoring across Solana, Ethereum, Base, Arbitrum, Optimism, and Polygon
- Frontend chain auto-detection for pasted wallet addresses
- Solana enhanced transaction indexing through Helius
- EVM aggregate activity indexing through Etherscan V2
- EVM decoded protocol, repayment, and liquidation signals through Alchemy Enhanced APIs
- Deterministic score from normalized wallet metrics
- OpenGradient TEE inference with attestation metadata capture
- Score caching with one-hour TTL
- Cache verification endpoint for proof lookups
- Health endpoint for OPG balance checks
- Smoke test script for end-to-end sanity checking

## Product Goals

VeriScore is designed to answer a simple question:

> "Can this wallet be trusted based on observable on-chain behavior, and can I verify how that score was produced?"

It is especially useful for:

- DeFi frontends that want a wallet trust signal before allowing access to higher-risk actions
- Analytics dashboards that need one normalized score across chains
- Credit or lending experiments that want wallet behavior summaries
- TEE-based demos showing cryptographically verifiable AI inference

## High-Level Architecture

```text
Frontend (index.html)
        |
        v
FastAPI app (src/api.py)
        |
        +--> WalletFetcher (src/fetcher.py)
        |       |
        |       +--> Solana -> Helius
        |       +--> EVM -> Etherscan V2
        |       +--> EVM decoded signals -> Alchemy Enhanced APIs
        |
        +--> CreditScorer (src/scorer.py)
        |
        +--> OpenGradientScorer (src/model.py)
        |       |
        |       +--> OPG approval
        |       +--> TEE inference
        |       +--> attestation extraction
        |
        +--> TTL cache (src/cache.py)
```

## Project Structure

```text
.
|-- index.html
|-- README.md
|-- requirements.txt
|-- .env.example
|-- src
|   |-- api.py
|   |-- cache.py
|   |-- fetcher.py
|   |-- model.py
|   `-- scorer.py
`-- tests
    |-- smoke_test.py
    |-- test_api.py
    `-- test_fetcher.py
```

## Supported Chains

| Chain | Slug | Detection | Indexer Path | Data Quality |
| --- | --- | --- | --- | --- |
| Solana | `solana` | Native address regex | Helius Enhanced Transactions | Full |
| Ethereum | `ethereum` | Probed for EVM activity | Etherscan V2 + Alchemy decoded signals | Full |
| Base | `base` | Probed for EVM activity | Etherscan V2 + Alchemy decoded signals | Full |
| Arbitrum | `arbitrum` | Probed for EVM activity | Etherscan V2 + Alchemy decoded signals | Full |
| Optimism | `optimism` | Probed for EVM activity | Etherscan V2 + Alchemy decoded signals | Full |
| Polygon | `polygon` | Probed for EVM activity | Etherscan V2 + Alchemy decoded signals | Full |

### Important note on EVM chain detection

A raw `0x...` address does not contain chain information. VeriScore cannot know the true chain from the address alone.

Instead, the backend probes supported EVM chains and picks the best candidate based on observed wallet activity:

- total transactions
- unique protocols
- resulting deterministic score

If all supported EVM chains look inactive, the system defaults to `ethereum`.

That means chain detection is best-effort, not cryptographic certainty.

## Wallet Data Model

All fetchers normalize chain-specific activity into the same metric shape:

```json
{
  "wallet_age_days": 0,
  "total_transactions": 0,
  "unique_protocols": 0,
  "avg_transaction_value_usd": 0.0,
  "liquidation_count": 0,
  "repayment_count": 0,
  "last_active_days_ago": 0,
  "usdc_volume_30d": 0.0
}
```

This normalization layer is what makes a shared scoring engine possible.

## How Data Is Fetched

### Solana path

Solana wallets are fetched with Helius enhanced transaction history.

The fetcher derives:

- wallet age from oldest observed transaction
- total transaction count
- unique protocols from instruction program IDs
- average stablecoin transaction value
- liquidation count from transaction descriptions and logs
- repayment count from lending + repayment keyword matches
- recency from last activity
- 30-day USDC volume

### EVM path

EVM wallets use two data sources:

1. Etherscan V2 for broad account and token transfer history
2. Alchemy Enhanced APIs for decoded DeFi signals

From Etherscan, VeriScore derives:

- wallet age
- total transactions
- average stablecoin value
- last active days
- 30-day USDC volume

From Alchemy decoded transfers and balances, VeriScore derives:

- `unique_protocols`
  Count of distinct contracts or active position tokens that match a seeded DeFi registry
- `repayment_count`
  Count of outgoing transfers that look like debt-token repayment flows
- `liquidation_count`
  Count of liquidation-like events, including debt outflow plus collateral inflow in the same transaction group

### EVM decoded protocol registry

The EVM fetcher ships with a seeded per-chain registry of known DeFi addresses, including examples such as:

- Uniswap
- Aave
- Compound
- Curve
- Balancer
- 1inch
- SushiSwap
- Aerodrome
- GMX
- Camelot
- QuickSwap

This registry is intentionally small and opinionated. It is meant to improve reliability over naive token-transfer heuristics, not to be a complete market map.

### Fallback behavior

If Alchemy is unavailable or decoding fails:

- EVM scoring still works
- `unique_protocols`, `repayment_count`, and `liquidation_count` fall back to heuristic Etherscan-derived values
- a warning is logged server-side

## Scoring Model

The deterministic score is computed in `src/scorer.py`.

It is a bounded 0-100 score based on the normalized metrics above.

### Score components

| Metric | Max Points | Notes |
| --- | --- | --- |
| `wallet_age_days` | 20 | Full score at 365 days |
| `total_transactions` | 15 | Full score at 500 transactions |
| `unique_protocols` | 15 | Full score at 10 protocols |
| `avg_transaction_value_usd` | 10 | Full score at $1,000 |
| `repayment_count` | 20 | Full score at 20 repayments |
| `last_active_days_ago` | 10 | Highest score for recent activity |
| `usdc_volume_30d` | 10 | Full score at $10,000 |
| `liquidation_count` | Negative penalty | `-10` per liquidation, capped at `-100` |

### Risk tiers

| Score Range | Tier |
| --- | --- |
| `0-39` | `POOR` |
| `40-59` | `FAIR` |
| `60-74` | `GOOD` |
| `75-100` | `EXCELLENT` |

### Why deterministic scoring exists

The deterministic score gives you:

- a predictable baseline
- an explainable fallback if TEE inference fails
- a cheap and stable ranking signal even when attestation is unavailable

## TEE Inference and Attestation

The OpenGradient integration lives in `src/model.py`.

When `OG_PRIVATE_KEY` is configured, VeriScore attempts to:

1. create an OpenGradient LLM client
2. ensure OPG approval
3. run the wallet summary through TEE inference
4. extract attestation metadata from the response

### Approval hardening

Approval is retried up to three times with exponential backoff before failing.

If approval or inference fails:

- deterministic scoring still completes
- the API returns a local score result
- attestation fields are empty

### Attestation fields returned

Every score response includes:

```json
{
  "attestation": {
    "payment_hash": "0x...",
    "proof_url": "https://explorer.opengradient.ai/proof/...",
    "raw": {}
  }
}
```

The system captures any of the following fields when present:

- `payment_hash`
- `attestation`
- `proof`
- `tee_attestation`
- `receipt`

### How `proof_url` is built

- If `proof` exists, VeriScore builds:
  `https://explorer.opengradient.ai/proof/<proof>`
- If `tee_attestation` exists, VeriScore builds:
  `https://explorer.opengradient.ai/attestation/<tee_attestation>`

### Verifying a score

To verify a score:

1. call a score endpoint
2. read `attestation.payment_hash`
3. open `attestation.proof_url` if present
4. compare the explorer record with the wallet and inference timing you expect

You can also call `GET /verify/{chain}/{wallet_address}` to fetch the cached attestation block for the last score without rescoring the wallet.

## Cache Design

VeriScore uses a simple in-memory TTL cache in `src/cache.py`.

- TTL: `3600` seconds
- key format:
  - Solana: `solana:<wallet>`
  - EVM: `<chain>:<wallet-lowercased>`

### Cache behavior

- first score request returns `"cached": false`
- repeated requests within TTL return `"cached": true`
- all score responses include `cache_expires_at`
- `DELETE /score/{chain}/{wallet_address}` removes the cached entry for that wallet

### Important operational note

This cache is process-local and non-persistent.

That means:

- restarting the API clears the cache
- multiple API instances do not share cache state
- `/verify` only works for scores produced by the current process unless you swap in shared storage such as Redis

## Frontend Behavior

The frontend lives entirely in `index.html`.

### UI characteristics

- OpenGradient-inspired aqua and teal palette
- frosted glass panels
- DM Sans and DM Mono typography
- desktop and mobile chain selectors
- animated score gauge
- attestation panel with proof link

### Scoring flow in the browser

When a user pastes a wallet and clicks `Score Wallet`:

1. the UI validates the address format
2. Solana addresses are mapped directly to `solana`
3. EVM addresses call `GET /detect/{wallet_address}`
4. the frontend updates the active chain pill
5. the frontend calls the matching score endpoint
6. the response is rendered into the score card

### No fake fallback

The frontend no longer fabricates demo score results when the API fails.

Current behavior is:

- successful API call -> render real result
- failed API call -> render an error state

This is important because fabricated scores undermine the trust value of the product.

## API Reference

The API is served by FastAPI from `src/api.py`.

### `GET /`

Serves the static frontend file.

### `GET /chains`

Returns supported chain slugs.

Example response:

```json
{
  "chains": ["solana", "ethereum", "base", "arbitrum", "optimism", "polygon"]
}
```

### `GET /detect/{wallet_address}`

Best-effort chain detection for pasted wallet addresses.

Behavior:

- Solana address -> returns `solana`
- EVM address -> probes supported EVM chains and returns the strongest candidate
- invalid format -> HTTP `400`

Example response:

```json
{
  "wallet": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
  "chain": "ethereum",
  "auto_detected": true,
  "candidates": [
    {
      "chain": "ethereum",
      "total_transactions": 123,
      "unique_protocols": 4,
      "score": 82
    }
  ]
}
```

### `POST /score`

Scores a wallet using a request body.

Request body:

```json
{
  "wallet_address": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
  "chain": "ethereum"
}
```

### `GET /score/{chain}/{wallet_address}`

Scores a wallet on a specific chain.

### `GET /score/{wallet_address}`

Backward-compatible shorthand for Solana wallets.

This endpoint assumes the wallet is on `solana`.

### Score response shape

All score endpoints return the same shape:

```json
{
  "score": 91,
  "explanation": "Long-lived wallet with strong repayment behavior and no liquidation history.",
  "attestation": {
    "payment_hash": "0xabc123",
    "proof_url": "https://explorer.opengradient.ai/proof/proof-123",
    "raw": {
      "payment_hash": "0xabc123",
      "proof": "proof-123"
    }
  },
  "model": "TEE_LLM",
  "chain": "ethereum",
  "wallet": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
  "scored_at": "2026-04-03T12:00:00Z",
  "cached": false,
  "cache_expires_at": "2026-04-03T13:00:00Z"
}
```

### `GET /verify/{chain}/{wallet_address}`

Returns the cached attestation block for the wallet's latest score result.

Example response:

```json
{
  "chain": "ethereum",
  "wallet": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
  "attestation": {
    "payment_hash": "0xabc123",
    "proof_url": "https://explorer.opengradient.ai/proof/proof-123",
    "raw": {
      "payment_hash": "0xabc123",
      "proof": "proof-123"
    }
  },
  "scored_at": "2026-04-03T12:00:00Z",
  "cache_expires_at": "2026-04-03T13:00:00Z"
}
```

If the wallet has not been scored in the current cache window, this endpoint returns `404`.

### `DELETE /score/{chain}/{wallet_address}`

Busts the cached score for that wallet.

Example response:

```json
{
  "deleted": true,
  "chain": "ethereum",
  "wallet": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
}
```

### `GET /health`

Checks the configured OPG balance for the OpenGradient private key.

Response values:

- `ok` -> OPG balance is healthy
- `low_balance` -> balance exists but is below the minimum threshold
- `no_balance` -> missing key, zeroed key, or no usable OPG balance

Example response:

```json
{
  "status": "ok",
  "opg_balance": 8.75
}
```

The endpoint returns HTTP `503` when status is `no_balance`.

## Local Development

### Requirements

- Python 3.11+
- API keys for the networks you want to score
- OpenGradient CLI or SDK-compatible environment for TEE inference

### Install

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Configure environment

Copy `.env.example` to `.env` and fill in the needed values.

```bash
HELIUS_API_KEY=your_helius_key_here
ETHERSCAN_API_KEY=your_etherscan_v2_key_here
ALCHEMY_API_KEY=your_alchemy_api_key_here
OG_PRIVATE_KEY=0x_your_base_sepolia_private_key_here
```

### Run the API

```bash
uvicorn src.api:app --reload
```

Then open:

- frontend: `http://localhost:8000/`
- docs UI if enabled by FastAPI defaults: `http://localhost:8000/docs`

## Environment Variables

| Variable | Required | Used By | Purpose |
| --- | --- | --- | --- |
| `HELIUS_API_KEY` | Required for Solana scoring | `src/fetcher.py` | Solana enhanced transaction history |
| `ETHERSCAN_API_KEY` | Required for EVM scoring | `src/fetcher.py` | EVM account and token transfer history |
| `ALCHEMY_API_KEY` | Strongly recommended for EVM scoring | `src/fetcher.py` | Decoded EVM protocol, repayment, and liquidation signals |
| `OG_PRIVATE_KEY` | Required for real TEE scoring | `src/model.py` | OpenGradient approval, inference, attestation, and health checks |
| `VERISCORE_SMOKE_SOLANA_WALLET` | Optional | `tests/smoke_test.py` | Override default Solana smoke-test wallet |
| `VERISCORE_SMOKE_HTTP_TIMEOUT_SECONDS` | Optional | `tests/smoke_test.py` | Override fetcher HTTP timeout |
| `VERISCORE_SMOKE_TIMEOUT_SECONDS` | Optional | `tests/smoke_test.py` | Override overall smoke-test request timeout |

## Testing

### Unit and API tests

Run:

```bash
pytest
```

The test suite covers:

- EVM decoded metric extraction
- score response shape
- cache hit and cache bust flow
- verify endpoint behavior
- health endpoint behavior
- chain detection behavior

### Smoke test

Run:

```bash
python tests/smoke_test.py
```

The smoke script:

1. loads `.env`
2. clears relevant cache entries
3. scores a lightweight public Solana wallet
4. scores Vitalik's Ethereum wallet
5. prints a formatted report
6. exits `0` only if both scores are integers in the `0-100` range

### Smoke-test defaults

- Solana wallet:
  `9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM`
- Ethereum wallet:
  `0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045`
- per-fetch HTTP timeout:
  `30` seconds
- per-score timeout:
  `30` seconds

## Deployment Notes

### Minimum deployment checklist

- set the required environment variables
- ensure the `OG_PRIVATE_KEY` wallet has enough OPG if you want real attested inference
- run `pytest`
- run `python tests/smoke_test.py`
- restrict CORS to your real frontend origin before public launch
- add rate limiting or authentication if the scoring endpoints will be public

### Frontend deployment

The frontend is served directly from the backend root endpoint, but you can also host `index.html` separately if it points to the backend API.

### Backend deployment

Any environment capable of running FastAPI and outbound HTTP requests to:

- Helius
- Etherscan
- Alchemy
- OpenGradient

can host the backend.

## Known Limitations

VeriScore is useful today, but there are still important limitations.

### 1. EVM chain detection is heuristic

An EVM address does not inherently reveal its home chain. Detection is based on activity observed on supported mainnets.

### 2. The EVM protocol registry is not exhaustive

Decoded protocol detection is only as good as the seeded registry and tracked token sets.

### 3. The cache is in-memory only

`/verify` is tied to the current process cache unless you replace it with shared storage.

### 4. Attestation depends on working OpenGradient funding and network access

If the OpenGradient wallet is underfunded, approval fails or inference falls back to the deterministic path. In that case:

- scores still return
- attestation may be empty

### 5. Public launch still needs hardening

For a real public deployment, you should add:

- stricter CORS
- rate limiting
- auth or quota control for paid inference
- structured logging and monitoring
- persistent cache or job storage if you scale horizontally

## Operational Caveats

### Why a wallet may score unexpectedly low

Common reasons:

- the wallet has little or no history on supported chains
- activity is mostly on unsupported networks or testnets
- the wallet interacts with protocols not present in the registry
- indexers returned partial or empty data

### Why attestation may be missing

Common reasons:

- `OG_PRIVATE_KEY` is not set
- the configured wallet has insufficient OPG
- OpenGradient approval failed
- OpenGradient inference failed or returned no proof-like fields
- outbound network access is blocked in the current environment

### Why the UI chain may change after paste

This is expected when an EVM wallet is entered. The frontend asks the backend to detect the most likely chain and updates the active chain pill.

## Security Notes

- Never commit `.env`
- Never expose `OG_PRIVATE_KEY` in the browser
- Treat API keys as secrets
- If you upload files manually to GitHub, upload `.env.example`, not `.env`
- If you expose the API publicly, protect it from abuse because inference can incur real cost

## Example End-to-End Flow

Here is the normal happy path:

1. user pastes a wallet into `index.html`
2. frontend detects address type
3. backend fetches normalized chain activity
4. `CreditScorer` computes a deterministic score
5. OpenGradient inference adds a short attested explanation
6. response is cached
7. UI renders score, chain, model, cache state, payment hash, and proof link

## Future Improvements

Logical next steps for the project:

- expand the EVM protocol registry
- add ENS and SNS name resolution
- add Redis-backed cache
- store historical score snapshots
- support more chains
- expose metric-level details in the API
- add signed score receipts for third-party integrations

## Quick Start

If you want the shortest path to a working local demo:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn src.api:app --reload
```

Then open `http://localhost:8000/`, paste a wallet, and score it.
