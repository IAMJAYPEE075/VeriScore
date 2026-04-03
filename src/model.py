from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import opengradient as og


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AttestationResult:
    payment_hash: str | None
    proof_url: str | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScoreResult:
    score: int
    explanation: str
    attestation: AttestationResult
    model: str
    chain: str
    wallet: str
    scored_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OpenGradientScorer:
    """Run verifiable wallet inference with the OpenGradient SDK."""

    MODEL_NAME = "TEE_LLM"
    MIN_OPG_BALANCE = 5.0

    def __init__(self, private_key: str) -> None:
        self.private_key = private_key.strip()

    async def run_verifiable_inference(
        self,
        wallet_data: dict[str, Any],
        *,
        score: int,
        chain: str,
        wallet: str,
        fallback_explanation: str,
    ) -> ScoreResult:
        if not self.private_key:
            raise RuntimeError("OG_PRIVATE_KEY is not set.")

        llm = og.LLM(private_key=self.private_key)
        approval_result = await self._ensure_opg_approval(llm)
        logger.info("OpenGradient approval result: %s", self._extract_approval_reference(approval_result))

        prompt = (
            "You are a DeFi credit analyst.\n"
            "Given this normalized wallet analysis payload:\n"
            f"{json.dumps(wallet_data, sort_keys=True)}\n"
            "Output ONLY a JSON object with these exact fields:\n"
            "signal: string either CREDITWORTHY or RISKY\n"
            "confidence: float between 0 and 1\n"
            "reasoning: string max 20 words explaining the decision"
        )

        chat_kwargs: dict[str, Any] = {
            "model": self._resolve_model(),
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 200,
            "temperature": 0.0,
        }
        settlement_mode = self._resolve_settlement_mode()
        if settlement_mode is not None:
            chat_kwargs["x402_settlement_mode"] = settlement_mode

        response = await llm.chat(**chat_kwargs)
        parsed = self._parse_model_output(response)
        attestation = self._extract_attestation(response)
        explanation = (
            parsed["reasoning"]
            if parsed["signal"] != "UNAVAILABLE" and parsed["reasoning"]
            else fallback_explanation
        )

        return ScoreResult(
            score=max(0, min(int(score), 100)),
            explanation=explanation,
            attestation=attestation,
            model=self.MODEL_NAME,
            chain=chain,
            wallet=wallet,
            scored_at=self._utc_iso_now(),
        )

    async def get_opg_balance(self) -> float:
        if not self.private_key or self._is_zero_private_key(self.private_key):
            return 0.0

        llm = og.LLM(private_key=self.private_key)
        candidates: list[Callable[[], Any]] = [
            lambda: getattr(llm, "get_opg_balance")(),
            lambda: getattr(llm, "opg_balance")(),
            lambda: getattr(llm, "get_balance")("OPG"),
            lambda: getattr(llm, "get_balance")(token="OPG"),
            lambda: getattr(llm, "balance")("OPG"),
            lambda: getattr(getattr(llm, "wallet", None), "get_opg_balance")(),
            lambda: getattr(getattr(llm, "wallet", None), "get_balance")("OPG"),
            lambda: getattr(og, "get_opg_balance")(private_key=self.private_key),
            lambda: getattr(og, "get_balance")(private_key=self.private_key, token="OPG"),
        ]

        last_error: Exception | None = None
        for candidate in candidates:
            try:
                result = candidate()
                if inspect.isawaitable(result):
                    result = await result
                balance = self._coerce_balance(result)
                if balance is not None:
                    return balance
            except AttributeError:
                continue
            except Exception as exc:  # pragma: no cover - defensive for SDK drift
                last_error = exc

        if last_error is not None:
            logger.warning("Unable to fetch OPG balance via SDK helpers: %s", last_error)
        return 0.0

    async def _ensure_opg_approval(self, llm: Any) -> Any:
        last_error: Exception | None = None

        for attempt in range(3):
            try:
                result = self._invoke_approval(llm)
                if inspect.isawaitable(result):
                    result = await result
                return result
            except Exception as exc:
                last_error = exc
                if attempt == 2:
                    raise RuntimeError(f"OPG approval failed after 3 attempts: {exc}") from exc
                await asyncio.sleep(2**attempt)

        raise RuntimeError(f"OPG approval failed after 3 attempts: {last_error}")

    @staticmethod
    def _invoke_approval(llm: Any) -> Any:
        try:
            return llm.ensure_opg_approval(opg_amount=5.0)
        except TypeError:
            return llm.ensure_opg_approval(min_allowance=5)

    def _extract_attestation(self, response: Any) -> AttestationResult:
        attestation_meta: dict[str, Any] = {}
        chat_output = getattr(response, "chat_output", None)

        for field in ["payment_hash", "attestation", "proof", "tee_attestation", "receipt"]:
            value = self._get_field_value(chat_output, field) or self._get_field_value(response, field)
            if value:
                attestation_meta[field] = self._make_json_safe(value)

        payment_hash = self._extract_nested_string(
            attestation_meta,
            ("payment_hash", "paymentHash", "hash", "tx_hash"),
        )
        proof_ref = self._extract_reference(attestation_meta.get("proof"))
        tee_ref = self._extract_reference(attestation_meta.get("tee_attestation"))
        proof_url = None
        if proof_ref:
            proof_url = f"https://explorer.opengradient.ai/proof/{proof_ref}"
        elif tee_ref:
            proof_url = f"https://explorer.opengradient.ai/attestation/{tee_ref}"

        return AttestationResult(
            payment_hash=payment_hash,
            proof_url=proof_url,
            raw=attestation_meta,
        )

    @staticmethod
    def _get_field_value(container: Any, field: str) -> Any:
        if container is None:
            return None
        if isinstance(container, dict):
            return container.get(field)
        return getattr(container, field, None)

    @staticmethod
    def _extract_reference(value: Any) -> str | None:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            for key in ("id", "hash", "proof", "attestation", "value"):
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()
        return None

    @staticmethod
    def _extract_nested_string(value: Any, candidate_keys: tuple[str, ...]) -> str | None:
        if isinstance(value, dict):
            for key in candidate_keys:
                direct = value.get(key)
                if isinstance(direct, str) and direct.strip():
                    return direct.strip()
            for nested in value.values():
                found = OpenGradientScorer._extract_nested_string(nested, candidate_keys)
                if found:
                    return found
        if isinstance(value, list):
            for item in value:
                found = OpenGradientScorer._extract_nested_string(item, candidate_keys)
                if found:
                    return found
        return None

    def _parse_model_output(self, response: Any) -> dict[str, Any]:
        raw_content = self._extract_response_content(response)
        json_blob = self._extract_json_blob(raw_content)

        if json_blob is None:
            return {
                "signal": "UNAVAILABLE",
                "confidence": 0.0,
                "reasoning": "OpenGradient returned non-JSON output.",
            }

        try:
            payload = json.loads(json_blob)
        except json.JSONDecodeError:
            return {
                "signal": "UNAVAILABLE",
                "confidence": 0.0,
                "reasoning": "OpenGradient JSON parsing failed.",
            }

        signal = str(payload.get("signal") or "UNAVAILABLE").upper()
        if signal not in {"CREDITWORTHY", "RISKY"}:
            signal = "UNAVAILABLE"

        confidence = payload.get("confidence", 0.0)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        reasoning = str(payload.get("reasoning") or "").strip()
        if not reasoning:
            reasoning = "No reasoning returned."
        reasoning = " ".join(reasoning.split()[:20])

        return {
            "signal": signal,
            "confidence": confidence,
            "reasoning": reasoning,
        }

    @staticmethod
    def _extract_response_content(response: Any) -> str:
        chat_output = getattr(response, "chat_output", None)

        if isinstance(chat_output, dict):
            for key in ("content", "text", "message"):
                value = chat_output.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
                if isinstance(value, list):
                    collected = OpenGradientScorer._flatten_content_blocks(value)
                    if collected:
                        return collected
        elif isinstance(chat_output, str) and chat_output.strip():
            return chat_output.strip()
        elif isinstance(chat_output, list):
            collected = OpenGradientScorer._flatten_content_blocks(chat_output)
            if collected:
                return collected

        if isinstance(response, dict):
            for key in ("content", "text", "message"):
                value = response.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        return str(chat_output or response or "").strip()

    @staticmethod
    def _flatten_content_blocks(blocks: list[Any]) -> str:
        pieces: list[str] = []
        for item in blocks:
            if isinstance(item, str) and item.strip():
                pieces.append(item.strip())
            elif isinstance(item, dict):
                for key in ("text", "content"):
                    value = item.get(key)
                    if isinstance(value, str) and value.strip():
                        pieces.append(value.strip())
        return "\n".join(pieces).strip()

    @staticmethod
    def _extract_json_blob(text: str) -> str | None:
        if not text:
            return None

        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?", "", stripped, flags=re.IGNORECASE).strip()
            stripped = re.sub(r"```$", "", stripped).strip()

        if stripped.startswith("{") and stripped.endswith("}"):
            return stripped

        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        return match.group(0) if match else None

    @staticmethod
    def _make_json_safe(value: Any) -> Any:
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, dict):
            return {
                str(key): OpenGradientScorer._make_json_safe(inner)
                for key, inner in value.items()
            }
        if isinstance(value, (list, tuple, set)):
            return [OpenGradientScorer._make_json_safe(item) for item in value]
        return str(value)

    @staticmethod
    def _coerce_balance(value: Any) -> float | None:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
        if isinstance(value, dict):
            for key in ("opg_balance", "balance", "amount", "value", "formatted"):
                candidate = value.get(key)
                parsed = OpenGradientScorer._coerce_balance(candidate)
                if parsed is not None:
                    return parsed
        return None

    @staticmethod
    def _extract_approval_reference(result: Any) -> Any:
        if result is None:
            return None
        if isinstance(result, dict):
            return result.get("tx_hash") or result.get("transaction_hash") or result
        for attr in ("tx_hash", "transaction_hash", "allowance_after", "allowance_before"):
            value = getattr(result, attr, None)
            if value is not None:
                return value
        return result

    @staticmethod
    def _utc_iso_now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _is_zero_private_key(private_key: str) -> bool:
        normalized = private_key.strip().lower()
        normalized = normalized[2:] if normalized.startswith("0x") else normalized
        return bool(normalized) and set(normalized) == {"0"}

    @staticmethod
    def _resolve_model() -> Any:
        tee_llm = getattr(og, "TEE_LLM", None)
        if tee_llm is None:
            return "openai/gpt-5"

        for attr_name in (
            "GPT_5",
            "GPT_5_2",
            "GPT_5_MINI",
            "GPT_4_1_2025_04_14",
        ):
            if hasattr(tee_llm, attr_name):
                return getattr(tee_llm, attr_name)

        return "openai/gpt-5"

    @staticmethod
    def _resolve_settlement_mode() -> Any:
        settlement_modes = getattr(og, "x402SettlementMode", None)
        if settlement_modes is None:
            return None

        for attr_name in ("INDIVIDUAL_FULL", "BATCH_HASHED", "PRIVATE"):
            if hasattr(settlement_modes, attr_name):
                return getattr(settlement_modes, attr_name)

        return None
