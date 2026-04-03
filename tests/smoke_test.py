from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import cache
from src import api as api_module
from src.api import get_score_response, make_cache_key
from src.fetcher import WalletFetcher as BaseWalletFetcher


DEFAULT_SOLANA_WALLET = os.getenv(
    "VERISCORE_SMOKE_SOLANA_WALLET",
    "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM",
)
ETHEREUM_WALLET = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
HTTP_CALL_TIMEOUT_SECONDS = int(os.getenv("VERISCORE_SMOKE_HTTP_TIMEOUT_SECONDS", "30"))
REQUEST_TIMEOUT_SECONDS = int(os.getenv("VERISCORE_SMOKE_TIMEOUT_SECONDS", "30"))


class SmokeWalletFetcher(BaseWalletFetcher):
    def __init__(self, wallet_address: str, chain: str, **kwargs) -> None:
        kwargs.setdefault("timeout", HTTP_CALL_TIMEOUT_SECONDS)
        super().__init__(wallet_address, chain, **kwargs)


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'").strip('"'))


def print_result(title: str, wallet_label: str, payload: dict) -> None:
    print(f"[{title}] {wallet_label}")
    print(f"  Score:        {payload['score']}")
    print(f"  Cached:       {payload['cached']}")
    print(f"  Payment Hash: {payload['attestation'].get('payment_hash') or '-'}")
    print(f"  Proof URL:    {payload['attestation'].get('proof_url') or '-'}")
    print(f"  Scored At:    {payload['scored_at']}")
    print()


async def run() -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    api_module.WalletFetcher = SmokeWalletFetcher

    solana_key = make_cache_key("solana", DEFAULT_SOLANA_WALLET)
    ethereum_key = make_cache_key("ethereum", ETHEREUM_WALLET)
    cache.delete(solana_key)
    cache.delete(ethereum_key)

    solana_result = await asyncio.wait_for(
        get_score_response(DEFAULT_SOLANA_WALLET, "solana"),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    ethereum_result = await asyncio.wait_for(
        get_score_response(ETHEREUM_WALLET, "ethereum"),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    solana_payload = solana_result.model_dump(mode="json")
    ethereum_payload = ethereum_result.model_dump(mode="json")

    print("=== VeriScore Smoke Test ===")
    print_result("SOLANA", DEFAULT_SOLANA_WALLET, solana_payload)
    print_result("ETHEREUM", "vitalik.eth", ethereum_payload)

    valid = all(
        isinstance(payload["score"], int) and 0 <= payload["score"] <= 100
        for payload in (solana_payload, ethereum_payload)
    )
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
