from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from src import cache
from src.api import app
import src.api as api


ETH_WALLET = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"


def sample_score_payload(*, wallet: str = ETH_WALLET, chain: str = "ethereum", score: int = 91) -> dict:
    return {
        "score": score,
        "explanation": "Long-lived DeFi wallet with active protocol usage and no liquidation history.",
        "attestation": {
            "payment_hash": "0xabc123",
            "proof_url": "https://explorer.opengradient.ai/proof/proof-123",
            "raw": {
                "payment_hash": "0xabc123",
                "proof": "proof-123",
            },
        },
        "model": "TEE_LLM",
        "chain": chain,
        "wallet": wallet,
        "scored_at": "2026-04-03T12:00:00Z",
    }


def test_post_score_response_contains_attestation(monkeypatch) -> None:
    cache.clear()

    async def fake_generate(wallet_address: str, chain: str) -> dict:
        return sample_score_payload(wallet=wallet_address, chain=chain)

    monkeypatch.setattr(api, "generate_score_result", fake_generate)
    client = TestClient(app)

    response = client.post("/score", json={"wallet_address": ETH_WALLET, "chain": "ethereum"})
    assert response.status_code == 200

    payload = response.json()
    assert payload["attestation"]["payment_hash"] == "0xabc123"
    assert payload["model"] == "TEE_LLM"
    assert payload["cached"] is False
    parsed = datetime.fromisoformat(payload["scored_at"].replace("Z", "+00:00"))
    assert parsed.year == 2026


def test_score_cache_round_trip(monkeypatch) -> None:
    cache.clear()
    calls = {"count": 0}

    async def fake_generate(wallet_address: str, chain: str) -> dict:
        calls["count"] += 1
        return sample_score_payload(wallet=wallet_address, chain=chain, score=88)

    monkeypatch.setattr(api, "generate_score_result", fake_generate)
    client = TestClient(app)

    first = client.get(f"/score/ethereum/{ETH_WALLET}")
    second = client.get(f"/score/ethereum/{ETH_WALLET}")
    deleted = client.delete(f"/score/ethereum/{ETH_WALLET}")
    third = client.get(f"/score/ethereum/{ETH_WALLET}")

    assert first.status_code == 200
    assert second.status_code == 200
    assert deleted.status_code == 200
    assert third.status_code == 200

    first_payload = first.json()
    second_payload = second.json()
    third_payload = third.json()

    assert first_payload["cached"] is False
    assert second_payload["cached"] is True
    assert first_payload["score"] == second_payload["score"]
    assert third_payload["cached"] is False
    assert calls["count"] == 2


def test_verify_returns_cached_attestation(monkeypatch) -> None:
    cache.clear()

    async def fake_generate(wallet_address: str, chain: str) -> dict:
        return sample_score_payload(wallet=wallet_address, chain=chain)

    monkeypatch.setattr(api, "generate_score_result", fake_generate)
    client = TestClient(app)

    score_response = client.get(f"/score/ethereum/{ETH_WALLET}")
    verify_response = client.get(f"/verify/ethereum/{ETH_WALLET}")

    assert score_response.status_code == 200
    assert verify_response.status_code == 200
    assert verify_response.json()["attestation"]["proof_url"] == score_response.json()["attestation"]["proof_url"]


def test_health_ok(monkeypatch) -> None:
    cache.clear()
    monkeypatch.setenv("OG_PRIVATE_KEY", "0x" + "1" * 64)

    async def fake_balance(self) -> float:
        return 8.75

    monkeypatch.setattr(api.OpenGradientScorer, "get_opg_balance", fake_balance)
    client = TestClient(app)

    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_no_balance(monkeypatch) -> None:
    cache.clear()
    monkeypatch.setenv("OG_PRIVATE_KEY", "0x" + "0" * 64)
    client = TestClient(app)

    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["status"] == "no_balance"
