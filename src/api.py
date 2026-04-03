from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from . import cache
from .fetcher import WalletFetcher
from .model import AttestationResult, OpenGradientScorer, ScoreResult
from .scorer import CreditScorer


logger = logging.getLogger(__name__)

EVM_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
SOLANA_ADDRESS_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


class ScoreRequest(BaseModel):
    wallet_address: str
    chain: str = "solana"


class AttestationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payment_hash: str | None = None
    proof_url: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class ScoreResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: int = Field(ge=0, le=100)
    explanation: str
    attestation: AttestationPayload
    model: str
    chain: str
    wallet: str
    scored_at: datetime
    cached: bool
    cache_expires_at: datetime


class VerifyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chain: str
    wallet: str
    attestation: AttestationPayload
    scored_at: datetime
    cache_expires_at: datetime


class ChainsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chains: list[str]


class CacheDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deleted: bool
    chain: str
    wallet: str


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "low_balance", "no_balance"]
    opg_balance: float


app = FastAPI(title="VeriScore API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(Path(__file__).resolve().parent.parent / "index.html")


@app.get("/health", response_model=HealthResponse)
async def health() -> JSONResponse:
    og_private_key = os.getenv("OG_PRIVATE_KEY", "").strip()
    scorer = OpenGradientScorer(og_private_key)
    opg_balance = await scorer.get_opg_balance()

    if opg_balance <= 0:
        payload = HealthResponse(status="no_balance", opg_balance=0.0)
        return JSONResponse(status_code=503, content=payload.model_dump(mode="json"))

    status_value: Literal["ok", "low_balance", "no_balance"]
    status_value = "ok" if opg_balance >= OpenGradientScorer.MIN_OPG_BALANCE else "low_balance"
    payload = HealthResponse(status=status_value, opg_balance=round(opg_balance, 6))
    return JSONResponse(status_code=200, content=payload.model_dump(mode="json"))


@app.get("/chains", response_model=ChainsResponse)
async def list_supported_chains() -> ChainsResponse:
    return ChainsResponse(chains=WalletFetcher.supported_chains())


@app.post("/score", response_model=ScoreResponse)
async def score_wallet_post(payload: ScoreRequest) -> ScoreResponse:
    return await get_score_response(payload.wallet_address, payload.chain)


@app.get("/score/{wallet_address}", response_model=ScoreResponse)
async def score_wallet_get(wallet_address: str) -> ScoreResponse:
    return await get_score_response(wallet_address, "solana")


@app.get("/score/{chain}/{wallet_address}", response_model=ScoreResponse)
async def score_wallet_by_chain_get(chain: str, wallet_address: str) -> ScoreResponse:
    return await get_score_response(wallet_address, chain)


@app.delete("/score/{chain}/{wallet_address}", response_model=CacheDeleteResponse)
async def bust_score_cache(chain: str, wallet_address: str) -> CacheDeleteResponse:
    normalized_chain, normalized_wallet = normalize_request(chain, wallet_address)
    deleted = cache.delete(make_cache_key(normalized_chain, normalized_wallet))
    return CacheDeleteResponse(
        deleted=deleted,
        chain=normalized_chain,
        wallet=normalized_wallet,
    )


@app.get("/verify/{chain}/{wallet_address}", response_model=VerifyResponse)
async def verify_wallet_score(chain: str, wallet_address: str) -> VerifyResponse:
    normalized_chain, normalized_wallet = normalize_request(chain, wallet_address)
    cached = cache.get(make_cache_key(normalized_chain, normalized_wallet))
    if not cached:
        raise HTTPException(status_code=404, detail="No cached score found for this wallet.")

    payload = VerifyResponse.model_validate(
        {
            "chain": cached.get("chain", normalized_chain),
            "wallet": cached.get("wallet", normalized_wallet),
            "attestation": cached["attestation"],
            "scored_at": cached["scored_at"],
            "cache_expires_at": cached["cache_expires_at"],
        }
    )
    return payload


async def get_score_response(wallet_address: str, chain: str) -> ScoreResponse:
    normalized_chain, normalized_wallet = normalize_request(chain, wallet_address)
    cache_key = make_cache_key(normalized_chain, normalized_wallet)
    cached = cache.get(cache_key)
    if cached:
        return ScoreResponse.model_validate({**cached, "cached": True})

    base_result = await generate_score_result(normalized_wallet, normalized_chain)
    cache_payload = {
        **base_result,
        "cached": False,
        "cache_expires_at": cache_expiry_iso(),
    }
    validated = ScoreResponse.model_validate(cache_payload)
    cache.set(cache_key, validated.model_dump(mode="json"))
    return validated


async def generate_score_result(wallet_address: str, chain: str) -> dict[str, Any]:
    helius_api_key = os.getenv("HELIUS_API_KEY", "").strip()
    etherscan_api_key = os.getenv("ETHERSCAN_API_KEY", "").strip()
    alchemy_api_key = os.getenv("ALCHEMY_API_KEY", "").strip()

    if chain == "solana" and not helius_api_key:
        raise HTTPException(status_code=500, detail="HELIUS_API_KEY is not configured.")
    if chain != "solana" and not etherscan_api_key:
        raise HTTPException(status_code=500, detail="ETHERSCAN_API_KEY is not configured.")

    fetcher = WalletFetcher(
        wallet_address,
        chain,
        helius_api_key=helius_api_key,
        etherscan_api_key=etherscan_api_key,
        alchemy_api_key=alchemy_api_key,
    )
    wallet_data = await fetcher.fetch()
    deterministic = CreditScorer().score_wallet(wallet_data)
    fallback_explanation = build_explanation(deterministic, wallet_data)

    og_private_key = os.getenv("OG_PRIVATE_KEY", "").strip()
    if og_private_key:
        scorer = OpenGradientScorer(og_private_key)
        inference_payload = {
            "chain": chain,
            "wallet_address": wallet_address,
            "wallet_metrics": wallet_data,
            "deterministic_score": deterministic["score"],
            "risk_tier": deterministic["risk_tier"],
            "breakdown": deterministic["breakdown"],
        }
        try:
            result = await scorer.run_verifiable_inference(
                inference_payload,
                score=deterministic["score"],
                chain=chain,
                wallet=wallet_address,
                fallback_explanation=fallback_explanation,
            )
            return result.to_dict()
        except Exception as exc:
            logger.warning("OpenGradient inference failed for %s on %s: %s", wallet_address, chain, exc)

    return build_local_score_result(
        score=deterministic["score"],
        explanation=fallback_explanation,
        chain=chain,
        wallet=wallet_address,
    )


def build_local_score_result(
    *,
    score: int,
    explanation: str,
    chain: str,
    wallet: str,
) -> dict[str, Any]:
    return ScoreResult(
        score=score,
        explanation=explanation,
        attestation=AttestationResult(payment_hash=None, proof_url=None, raw={}),
        model=OpenGradientScorer.MODEL_NAME,
        chain=chain,
        wallet=wallet,
        scored_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    ).to_dict()


def build_explanation(score_result: dict[str, Any], wallet_data: dict[str, Any]) -> str:
    def metric(name: str) -> int:
        try:
            return int(float(wallet_data.get(name, 0) or 0))
        except (TypeError, ValueError):
            return 0

    return (
        f"{score_result['risk_tier'].title()} reputation from "
        f"{metric('total_transactions')} transactions, "
        f"{metric('unique_protocols')} protocols, "
        f"{metric('repayment_count')} repayments, and "
        f"{metric('liquidation_count')} liquidations."
    )


def normalize_request(chain: str, wallet_address: str) -> tuple[str, str]:
    normalized_wallet = wallet_address.strip()
    normalized_chain = WalletFetcher.normalize_chain(chain)
    if not normalized_chain:
        raise HTTPException(status_code=400, detail="Unsupported chain.")
    validate_wallet_address(normalized_wallet, normalized_chain)
    return normalized_chain, normalized_wallet


def make_cache_key(chain: str, wallet_address: str) -> str:
    if chain == "solana":
        return f"{chain}:{wallet_address}"
    return f"{chain}:{wallet_address.lower()}"


def cache_expiry_iso() -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=cache.TTL)).isoformat().replace(
        "+00:00",
        "Z",
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.api:app", host="0.0.0.0", port=8000, reload=True)


def validate_wallet_address(wallet_address: str, chain: str) -> None:
    if chain == "solana":
        if not SOLANA_ADDRESS_RE.fullmatch(wallet_address):
            raise HTTPException(status_code=400, detail="Invalid Solana wallet address.")
        return

    if not EVM_ADDRESS_RE.fullmatch(wallet_address):
        raise HTTPException(
            status_code=400,
            detail="Invalid EVM wallet address. Expected a 0x-prefixed address.",
        )
