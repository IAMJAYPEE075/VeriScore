from __future__ import annotations

import pytest

from src import fetcher


VITALIK = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
UNISWAP_ROUTER = "0x7a250d5630B4cF539739df2C5dAcb4c659F2488D"
AAVE_POOL = "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2"
COMPOUND_CUSDC = "0x39AA39c021dfbaE8faC545936693aC917d5E7563"
USDC = "0xA0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def json(self) -> dict:
        return self.payload

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(self, *args, **kwargs) -> None:
        return None

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def post(self, url: str, json: dict) -> FakeResponse:
        method = json["method"]
        if method == "alchemy_getAssetTransfers":
            params = json["params"][0]
            if "fromAddress" in params:
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "transfers": [
                            {
                                "hash": "0xswap",
                                "blockNum": "0x10",
                                "from": VITALIK,
                                "to": UNISWAP_ROUTER,
                                "asset": "ETH",
                                "value": 1.2,
                            },
                            {
                                "hash": "0xlend",
                                "blockNum": "0x11",
                                "from": VITALIK,
                                "to": AAVE_POOL,
                                "asset": "WETH",
                                "value": 0.8,
                            },
                            {
                                "hash": "0xrepay",
                                "blockNum": "0x12",
                                "from": VITALIK,
                                "to": AAVE_POOL,
                                "asset": "cUSDC",
                                "value": 120.0,
                                "rawContract": {"address": COMPOUND_CUSDC},
                            },
                        ]
                    },
                }
            else:
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "transfers": [
                            {
                                "hash": "0xrepay",
                                "blockNum": "0x12",
                                "from": AAVE_POOL,
                                "to": VITALIK,
                                "asset": "USDC",
                                "value": 135.0,
                                "rawContract": {"address": USDC},
                            }
                        ]
                    },
                }
            return FakeResponse(payload)

        if method == "alchemy_getTokenBalances":
            return FakeResponse(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "address": VITALIK,
                        "tokenBalances": [
                            {
                                "contractAddress": COMPOUND_CUSDC,
                                "tokenBalance": "0x01",
                            }
                        ],
                    },
                }
            )

        raise AssertionError(f"Unexpected RPC method: {method}")


@pytest.mark.asyncio
async def test_evm_real_protocols(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALCHEMY_API_KEY", "test-alchemy-key")
    monkeypatch.setattr(fetcher.aiohttp, "ClientSession", FakeSession)

    metrics = await fetcher.fetch_evm_decoded(VITALIK, "ethereum")

    assert metrics["unique_protocols"] > 0
    assert isinstance(metrics["repayment_count"], int)
    assert metrics["repayment_count"] >= 0
    assert isinstance(metrics["liquidation_count"], int)
    assert metrics["liquidation_count"] >= 0
