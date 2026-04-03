from __future__ import annotations

from typing import Any


class CreditScorer:
    """Compute a wallet credit score, category breakdown, and risk tier."""

    def score(self, wallet_data: dict[str, Any]) -> dict[str, Any]:
        age_points = self._linear_points(wallet_data.get("wallet_age_days"), 365, 20)
        tx_points = self._linear_points(wallet_data.get("total_transactions"), 500, 15)
        protocol_points = self._linear_points(wallet_data.get("unique_protocols"), 10, 15)
        avg_value_points = self._linear_points(
            wallet_data.get("avg_transaction_value_usd"), 1000, 10
        )
        repayment_points = self._linear_points(wallet_data.get("repayment_count"), 20, 20)
        activity_points = self._activity_points(wallet_data.get("last_active_days_ago"))
        usdc_points = self._linear_points(wallet_data.get("usdc_volume_30d"), 10_000, 10)

        liquidation_count = max(self._coerce_number(wallet_data.get("liquidation_count")), 0.0)
        liquidation_penalty = round(min(liquidation_count * 10, 100), 2) * -1

        breakdown = {
            "wallet_age_days": age_points,
            "total_transactions": tx_points,
            "unique_protocols": protocol_points,
            "avg_transaction_value_usd": avg_value_points,
            "liquidation_penalty": liquidation_penalty,
            "repayment_count": repayment_points,
            "last_active_days_ago": activity_points,
            "usdc_volume_30d": usdc_points,
        }

        total = round(sum(breakdown.values()))
        score = max(0, min(100, int(total)))

        return {
            "score": score,
            "breakdown": breakdown,
            "risk_tier": self._risk_tier(score),
        }

    def score_wallet(self, wallet_data: dict[str, Any]) -> dict[str, Any]:
        return self.score(wallet_data)

    @staticmethod
    def _linear_points(value: Any, full_score_at: float, max_points: float) -> float:
        number = max(CreditScorer._coerce_number(value), 0.0)
        if full_score_at <= 0:
            return round(max_points, 2)
        return round(min(number / full_score_at, 1.0) * max_points, 2)

    @staticmethod
    def _activity_points(value: Any) -> float:
        days_ago = max(CreditScorer._coerce_number(value), 0.0)
        if days_ago <= 7:
            return 10.0
        if days_ago >= 60:
            return 0.0
        return round((1 - ((days_ago - 7) / 53)) * 10, 2)

    @staticmethod
    def _risk_tier(score: int) -> str:
        if score <= 39:
            return "POOR"
        if score <= 59:
            return "FAIR"
        if score <= 74:
            return "GOOD"
        return "EXCELLENT"

    @staticmethod
    def _coerce_number(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
