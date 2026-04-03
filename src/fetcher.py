from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp
import httpx


logger = logging.getLogger(__name__)

ALCHEMY_NETWORKS = {
    "ethereum": "eth-mainnet",
    "base": "base-mainnet",
    "arbitrum": "arb-mainnet",
    "optimism": "opt-mainnet",
    "polygon": "polygon-mainnet",
}

COMMON_DEBT_TOKEN_KEYWORDS = (
    "atoken",
    "ctoken",
    "variabledebt",
    "stabledebt",
    "debt",
)

EVM_CHAIN_REGISTRY: dict[str, dict[str, dict[str, str] | set[str]]] = {
    "ethereum": {
        "protocol_addresses": {
            "0x3fc91a3afd70395cd496c647d5a6cc9d4b2b7fad": "Uniswap",
            "0x7a250d5630b4cf539739df2c5dacb4c659f2488d": "Uniswap",
            "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45": "Uniswap",
            "0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2": "Aave",
            "0xba12222222228d8ba445958a75a0704d566bf2c8": "Balancer",
            "0x111111125421ca6dc452d289314280a0f8842a65": "1inch",
            "0xbbbbbbbbbb9cc5e90e3b3af64bdaf62c37eeffcb": "Morpho",
            "0xbebc44782c7db0a1a60cb6fe97d0b483032ff1c7": "Curve",
            "0xdc24316b9ae028f1497c275eb9192a3ea0f67022": "Curve",
            "0xd9e1ce17f2641f24ae83637ab66a2cca9c378b9f": "SushiSwap",
            "0xc3d688b66703497daa19211eedff47f25384cdc3": "Compound",
        },
        "position_token_addresses": {
            "0x39aa39c021dfbae8fac545936693ac917d5e7563": "Compound",
            "0x5d3a536e4d6dbd6114cc1ead35777bab948e3643": "Compound",
            "0x4d5f47fa6a74757f35c14fd3a6ef8e3c9bc514e8": "Aave",
            "0x98c23e9d8f34fefb1b7bd6a18e1b7c1f7eb3c1b0": "Aave",
        },
        "debt_token_addresses": {
            "0x39aa39c021dfbae8fac545936693ac917d5e7563",
            "0x5d3a536e4d6dbd6114cc1ead35777bab948e3643",
            "0x4d5f47fa6a74757f35c14fd3a6ef8e3c9bc514e8",
            "0x98c23e9d8f34fefb1b7bd6a18e1b7c1f7eb3c1b0",
        },
        "collateral_token_addresses": {
            "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
            "0xdac17f958d2ee523a2206206994597c13d831ec7",
            "0x6b175474e89094c44da98b954eedeac495271d0f",
            "0xc02aa39b223fe8d0a0e5c4f27ead9083c756cc2",
            "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599",
        },
        "liquidation_bots": set(),
    },
    "base": {
        "protocol_addresses": {
            "0xa238dd80c259a72e81d7e4664a9801593f98d1c5": "Aave",
            "0xcf77a3ba9a5ca399b7c97c74d54e5b005960eac8": "Aerodrome",
            "0x111111125421ca6dc452d289314280a0f8842a65": "1inch",
            "0xba12222222228d8ba445958a75a0704d566bf2c8": "Balancer",
            "0x6ff5693b99212da76ad316178a184ab56d299b43": "Uniswap",
        },
        "position_token_addresses": {
            "0x4e65fe4dba92790696d040ac24aa414708f5c0ab": "Moonwell",
        },
        "debt_token_addresses": {"0x4e65fe4dba92790696d040ac24aa414708f5c0ab"},
        "collateral_token_addresses": {
            "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
            "0x4200000000000000000000000000000000000006",
            "0x50c5725949a6f0c72e6c4a641f24049a917db0cb",
        },
        "liquidation_bots": set(),
    },
    "arbitrum": {
        "protocol_addresses": {
            "0x794a61358d6845594f94dc1db02a252b5b4814ad": "Aave",
            "0xba12222222228d8ba445958a75a0704d566bf2c8": "Balancer",
            "0x111111125421ca6dc452d289314280a0f8842a65": "1inch",
            "0xc873fecbd354f5a56e00e710b90ef4201db2448d": "Camelot",
            "0xb87a436b93ffe9d75c5cfa7bacfff96430b09868": "GMX",
            "0x3fc91a3afd70395cd496c647d5a6cc9d4b2b7fad": "Uniswap",
        },
        "position_token_addresses": {},
        "debt_token_addresses": set(),
        "collateral_token_addresses": {
            "0xaf88d065e77c8cc2239327c5edb3a432268e5831",
            "0xff970a61a04b1ca14834a43f5de4533ebddb5cc8",
            "0x82af49447d8a07e3bd95bd0d56f35241523fbab1",
            "0xda10009cbd5d07dd0cecc66161fc93d7c9000da1",
            "0x2f2a2543b76a4166549f7aab2e75bef0aefc5b0f",
        },
        "liquidation_bots": set(),
    },
    "optimism": {
        "protocol_addresses": {
            "0x794a61358d6845594f94dc1db02a252b5b4814ad": "Aave",
            "0xa132dab612db5cb9fc9ac426a0cc215a3423f9c9": "Velodrome",
            "0xba12222222228d8ba445958a75a0704d566bf2c8": "Balancer",
            "0x111111125421ca6dc452d289314280a0f8842a65": "1inch",
            "0x3fc91a3afd70395cd496c647d5a6cc9d4b2b7fad": "Uniswap",
        },
        "position_token_addresses": {},
        "debt_token_addresses": set(),
        "collateral_token_addresses": {
            "0x0b2c639c533813f4aa9d7837caf62653d097ff85",
            "0x7f5c764cbc14f9669b88837ca1490cca17c31607",
            "0x4200000000000000000000000000000000000006",
            "0xda10009cbd5d07dd0cecc66161fc93d7c9000da1",
            "0x68f180fcce6836688e9084f035309e29bf0a2095",
        },
        "liquidation_bots": set(),
    },
    "polygon": {
        "protocol_addresses": {
            "0x794a61358d6845594f94dc1db02a252b5b4814ad": "Aave",
            "0xa5e0829caced8ffdd4de3c43696c57f7d7a678ff": "QuickSwap",
            "0xba12222222228d8ba445958a75a0704d566bf2c8": "Balancer",
            "0x111111125421ca6dc452d289314280a0f8842a65": "1inch",
            "0x3fc91a3afd70395cd496c647d5a6cc9d4b2b7fad": "Uniswap",
        },
        "position_token_addresses": {},
        "debt_token_addresses": set(),
        "collateral_token_addresses": {
            "0x2791bca1f2de4661ed88a30c99a7a9449aa84174",
            "0x7ceb23fd6bc0add59e62ac25578270cff1b9f619",
            "0x8f3cf7ad23cd3cadbd9735aff958023239c6a063",
            "0x1bfd67037b42cf73acf2047067bd4f2c47d9bfd6",
        },
        "liquidation_bots": set(),
    },
}

def default_wallet_metrics() -> dict[str, Any]:
    return {
        "wallet_age_days": 0,
        "total_transactions": 0,
        "unique_protocols": 0,
        "avg_transaction_value_usd": 0.0,
        "liquidation_count": 0,
        "repayment_count": 0,
        "last_active_days_ago": 0,
        "usdc_volume_30d": 0.0,
    }


def coerce_datetime(timestamp: Any) -> datetime | None:
    if timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def coerce_amount(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if math.isnan(value) or math.isinf(value):
            return None
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    if isinstance(value, dict):
        for nested_key in ("uiAmount", "ui_amount"):
            nested_value = value.get(nested_key)
            if nested_value is not None:
                nested_amount = coerce_amount(nested_value)
                if nested_amount is not None:
                    return nested_amount

        raw_amount = value.get("amount")
        decimals = value.get("decimals")
        if raw_amount is not None and decimals is not None:
            try:
                return float(raw_amount) / (10 ** int(decimals))
            except (TypeError, ValueError, ZeroDivisionError):
                return None

        nested_amount = coerce_amount(value.get("tokenAmount"))
        if nested_amount is not None:
            return nested_amount

    return None


def _normalize_address(value: Any) -> str:
    return str(value or "").strip().lower()


def _parse_hex_balance(value: Any) -> int:
    if isinstance(value, str):
        try:
            return int(value, 16) if value.startswith("0x") else int(value)
        except ValueError:
            return 0
    if isinstance(value, int):
        return value
    return 0


async def _alchemy_post(
    session: aiohttp.ClientSession,
    url: str,
    method: str,
    params: list[Any],
) -> dict[str, Any]:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    async with session.post(url, json=payload) as response:
        response.raise_for_status()
        data = await response.json()

    if not isinstance(data, dict):
        raise RuntimeError(f"Unexpected Alchemy response type for {method}.")
    if data.get("error"):
        raise RuntimeError(f"Alchemy {method} failed: {data['error']}")
    return data


async def _fetch_alchemy_transfers(
    session: aiohttp.ClientSession,
    url: str,
    *,
    wallet: str,
    direction: str,
    max_pages: int = 3,
) -> list[dict[str, Any]]:
    if direction not in {"from", "to"}:
        return []

    params: dict[str, Any] = {
        "fromBlock": "0x0",
        "excludeZeroValue": False,
        "withMetadata": True,
        "category": ["external", "internal", "erc20"],
        "order": "desc",
        "maxCount": "0x3e8",
    }
    params["fromAddress" if direction == "from" else "toAddress"] = wallet

    transfers: list[dict[str, Any]] = []
    page_key: str | None = None

    for _ in range(max_pages):
        page_params = dict(params)
        if page_key:
            page_params["pageKey"] = page_key

        data = await _alchemy_post(session, url, "alchemy_getAssetTransfers", [page_params])
        result = data.get("result") or {}
        page_rows = result.get("transfers") or []
        if not isinstance(page_rows, list):
            break

        transfers.extend(row for row in page_rows if isinstance(row, dict))
        page_key = result.get("pageKey")
        if not page_key:
            break

    return transfers


async def _fetch_alchemy_token_balances(
    session: aiohttp.ClientSession,
    url: str,
    *,
    wallet: str,
    tracked_tokens: list[str],
) -> list[dict[str, Any]]:
    if not tracked_tokens:
        return []

    data = await _alchemy_post(
        session,
        url,
        "alchemy_getTokenBalances",
        [wallet, tracked_tokens],
    )
    result = data.get("result") or {}
    balances = result.get("tokenBalances") or []
    return [row for row in balances if isinstance(row, dict)]


def _transfer_is_outgoing(transfer: dict[str, Any], wallet: str) -> bool:
    return _normalize_address(transfer.get("from")) == wallet


def _transfer_is_incoming(transfer: dict[str, Any], wallet: str) -> bool:
    return _normalize_address(transfer.get("to")) == wallet


def _transfer_contract_address(transfer: dict[str, Any]) -> str:
    raw_contract = transfer.get("rawContract")
    if not isinstance(raw_contract, dict):
        return ""
    return _normalize_address(raw_contract.get("address"))


def _is_debt_token_transfer(transfer: dict[str, Any], debt_tokens: set[str]) -> bool:
    contract_address = _transfer_contract_address(transfer)
    if contract_address and contract_address in debt_tokens:
        return True

    asset_name = str(transfer.get("asset") or "").strip().lower()
    return any(keyword in asset_name for keyword in COMMON_DEBT_TOKEN_KEYWORDS)


def _is_collateral_transfer(
    transfer: dict[str, Any],
    collateral_tokens: set[str],
) -> bool:
    contract_address = _transfer_contract_address(transfer)
    if contract_address and contract_address in collateral_tokens:
        return True

    amount = coerce_amount(transfer.get("value"))
    return amount is not None and amount > 0


def _collect_unique_protocols(
    outgoing_transfers: list[dict[str, Any]],
    active_balances: list[dict[str, Any]],
    protocol_addresses: dict[str, str],
    position_token_addresses: dict[str, str],
) -> int:
    matched_protocols: set[str] = set()

    for transfer in outgoing_transfers:
        protocol_name = protocol_addresses.get(_normalize_address(transfer.get("to")))
        if protocol_name:
            matched_protocols.add(protocol_name)

        token_protocol = position_token_addresses.get(_transfer_contract_address(transfer))
        if token_protocol:
            matched_protocols.add(token_protocol)

    for balance in active_balances:
        if _parse_hex_balance(balance.get("tokenBalance")) <= 0:
            continue

        protocol_name = position_token_addresses.get(
            _normalize_address(balance.get("contractAddress"))
        )
        if protocol_name:
            matched_protocols.add(protocol_name)

    return len(matched_protocols)


def _count_repayments(
    outgoing_transfers: list[dict[str, Any]],
    wallet: str,
    debt_tokens: set[str],
) -> int:
    repayment_hashes: set[str] = set()

    for transfer in outgoing_transfers:
        if not _transfer_is_outgoing(transfer, wallet):
            continue
        if not _is_debt_token_transfer(transfer, debt_tokens):
            continue

        tx_hash = _normalize_address(transfer.get("hash"))
        unique_id = _normalize_address(transfer.get("uniqueId"))
        repayment_hashes.add(tx_hash or unique_id or json.dumps(transfer, sort_keys=True))

    return len(repayment_hashes)


def _count_liquidations(
    transfers: list[dict[str, Any]],
    wallet: str,
    *,
    debt_tokens: set[str],
    collateral_tokens: set[str],
    liquidation_bots: set[str],
) -> int:
    grouped: dict[str, list[dict[str, Any]]] = {}

    for transfer in transfers:
        tx_hash = _normalize_address(transfer.get("hash"))
        block_num = str(transfer.get("blockNum") or "").strip().lower()
        group_key = tx_hash or f"block:{block_num}:{_normalize_address(transfer.get('uniqueId'))}"
        grouped.setdefault(group_key, []).append(transfer)

    liquidation_events = 0
    for group_transfers in grouped.values():
        bot_match = any(
            _normalize_address(transfer.get("from")) in liquidation_bots
            or _normalize_address(transfer.get("to")) in liquidation_bots
            for transfer in group_transfers
        )
        outgoing_debt = any(
            _transfer_is_outgoing(transfer, wallet)
            and _is_debt_token_transfer(transfer, debt_tokens)
            for transfer in group_transfers
        )
        incoming_collateral = any(
            _transfer_is_incoming(transfer, wallet)
            and _is_collateral_transfer(transfer, collateral_tokens)
            for transfer in group_transfers
        )

        if bot_match or (outgoing_debt and incoming_collateral):
            liquidation_events += 1

    return liquidation_events


async def fetch_evm_decoded(
    wallet: str,
    chain: str,
    *,
    alchemy_api_key: str | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    normalized_wallet = _normalize_address(wallet)
    normalized_chain = WalletFetcher.normalize_chain(chain)
    network = ALCHEMY_NETWORKS.get(normalized_chain)
    registry = EVM_CHAIN_REGISTRY.get(normalized_chain)

    if not normalized_wallet or not network or registry is None:
        return {
            "unique_protocols": 0,
            "repayment_count": 0,
            "liquidation_count": 0,
        }

    api_key = (alchemy_api_key or os.getenv("ALCHEMY_API_KEY", "")).strip()
    if not api_key:
        raise RuntimeError("ALCHEMY_API_KEY is not configured.")

    protocol_addresses = dict(registry.get("protocol_addresses", {}))
    position_token_addresses = dict(registry.get("position_token_addresses", {}))
    debt_tokens = set(registry.get("debt_token_addresses", set()))
    collateral_tokens = set(registry.get("collateral_token_addresses", set()))
    liquidation_bots = set(registry.get("liquidation_bots", set()))
    tracked_tokens = sorted(position_token_addresses)
    base_url = f"https://{network}.g.alchemy.com/v2/{api_key}"

    client_timeout = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession(timeout=client_timeout) as session:
        outgoing_transfers, incoming_transfers, token_balances = await asyncio.gather(
            _fetch_alchemy_transfers(
                session,
                base_url,
                wallet=normalized_wallet,
                direction="from",
            ),
            _fetch_alchemy_transfers(
                session,
                base_url,
                wallet=normalized_wallet,
                direction="to",
            ),
            _fetch_alchemy_token_balances(
                session,
                base_url,
                wallet=normalized_wallet,
                tracked_tokens=tracked_tokens,
            ),
        )

    all_transfers = [*outgoing_transfers, *incoming_transfers]
    return {
        "unique_protocols": _collect_unique_protocols(
            outgoing_transfers,
            token_balances,
            protocol_addresses,
            position_token_addresses,
        ),
        "repayment_count": _count_repayments(outgoing_transfers, normalized_wallet, debt_tokens),
        "liquidation_count": _count_liquidations(
            all_transfers,
            normalized_wallet,
            debt_tokens=debt_tokens,
            collateral_tokens=collateral_tokens,
            liquidation_bots=liquidation_bots,
        ),
    }


class WalletFetcher:
    """Fetch normalized wallet data for Solana or EVM chains."""

    SUPPORTED_CHAINS = {
        "solana": "solana",
        "eth": "ethereum",
        "ethereum": "ethereum",
        "base": "base",
        "arb": "arbitrum",
        "arbitrum": "arbitrum",
        "op": "optimism",
        "optimism": "optimism",
        "matic": "polygon",
        "polygon": "polygon",
    }

    def __init__(
        self,
        wallet_address: str,
        chain: str,
        *,
        helius_api_key: str = "",
        etherscan_api_key: str = "",
        alchemy_api_key: str = "",
        timeout: float = 20.0,
        max_pages: int | None = None,
    ) -> None:
        self.wallet_address = wallet_address.strip()
        self.chain = self.normalize_chain(chain)
        self.helius_api_key = helius_api_key.strip()
        self.etherscan_api_key = etherscan_api_key.strip()
        self.alchemy_api_key = alchemy_api_key.strip()
        self.timeout = timeout
        self.max_pages = max_pages

    async def fetch(self) -> dict[str, Any]:
        if self.chain == "solana":
            fetcher = SolanaWalletFetcher(
                self.wallet_address,
                self.helius_api_key,
                timeout=self.timeout,
                max_pages=self.max_pages,
            )
            return await fetcher.fetch()

        if self.chain in EVMWalletFetcher.CHAIN_IDS:
            fetcher = EVMWalletFetcher(
                self.wallet_address,
                self.chain,
                self.etherscan_api_key,
                alchemy_api_key=self.alchemy_api_key,
                timeout=self.timeout,
                max_pages=self.max_pages,
            )
            return await fetcher.fetch()

        return default_wallet_metrics()

    async def fetch_wallet_data(self) -> dict[str, Any]:
        return await self.fetch()

    @classmethod
    def normalize_chain(cls, chain: str | None) -> str:
        return cls.SUPPORTED_CHAINS.get((chain or "solana").strip().lower(), "")

    @classmethod
    def supported_chains(cls) -> list[str]:
        ordered = ["solana", "ethereum", "base", "arbitrum", "optimism", "polygon"]
        return [chain for chain in ordered if chain in set(cls.SUPPORTED_CHAINS.values())]


class SolanaWalletFetcher:
    HELIUS_URL = "https://api.helius.xyz/v0/addresses/{address}/transactions"
    PAGE_SIZE = 100
    MAX_RETRIES = 5
    USD_STABLE_SYMBOLS = {"USDC", "USDT", "USDS", "PYUSD", "USDE", "USDY"}
    USDC_SYMBOLS = {"USDC"}
    LENDING_PROTOCOL_KEYWORDS = {
        "kamino",
        "solend",
        "marginfi",
        "port",
        "mango",
        "francium",
        "jet",
        "save",
        "drift",
        "sharky",
    }
    REPAYMENT_KEYWORDS = {
        "repay",
        "repayment",
        "repayreserve",
        "repayobligationliquidity",
        "loan_repayment",
        "settle",
    }

    def __init__(
        self,
        wallet_address: str,
        helius_api_key: str,
        *,
        timeout: float,
        max_pages: int | None,
    ) -> None:
        self.wallet_address = wallet_address.strip()
        self.helius_api_key = helius_api_key.strip()
        self.timeout = timeout
        self.max_pages = max_pages

    async def fetch(self) -> dict[str, Any]:
        metrics = default_wallet_metrics()
        if not self.wallet_address or not self.helius_api_key:
            return metrics

        transactions = await self._fetch_all_transactions()
        if not transactions:
            return metrics

        now = datetime.now(timezone.utc)
        timestamps: list[datetime] = []
        protocol_ids: set[str] = set()
        stable_values: list[float] = []
        liquidation_count = 0
        repayment_count = 0
        usdc_volume_30d = 0.0
        cutoff_30d = now - timedelta(days=30)

        for tx in transactions:
            tx_time = coerce_datetime(tx.get("timestamp"))
            if tx_time is not None:
                timestamps.append(tx_time)

            protocol_ids.update(self._extract_program_ids(tx))

            tx_value = self._extract_stablecoin_value_usd(tx)
            if tx_value > 0:
                stable_values.append(tx_value)

            if tx_time and tx_time >= cutoff_30d:
                usdc_volume_30d += self._extract_usdc_value(tx)

            if self._is_liquidation(tx):
                liquidation_count += 1

            if self._is_repayment(tx):
                repayment_count += 1

        oldest_tx = min(timestamps) if timestamps else None
        newest_tx = max(timestamps) if timestamps else None

        metrics["wallet_age_days"] = max((now - oldest_tx).days, 0) if oldest_tx else 0
        metrics["total_transactions"] = len(transactions)
        metrics["unique_protocols"] = len(protocol_ids)
        metrics["avg_transaction_value_usd"] = (
            round(sum(stable_values) / len(stable_values), 2) if stable_values else 0.0
        )
        metrics["liquidation_count"] = liquidation_count
        metrics["repayment_count"] = repayment_count
        metrics["last_active_days_ago"] = (
            max((now - newest_tx).days, 0) if newest_tx else 0
        )
        metrics["usdc_volume_30d"] = round(usdc_volume_30d, 2)
        return metrics

    async def _fetch_all_transactions(self) -> list[dict[str, Any]]:
        endpoint = self.HELIUS_URL.format(address=self.wallet_address)
        before_signature: str | None = None
        pages = 0
        transactions: list[dict[str, Any]] = []
        seen_signatures: set[str] = set()

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            while True:
                if self.max_pages is not None and pages >= self.max_pages:
                    break

                page = await self._fetch_page(client, endpoint, before_signature)
                pages += 1

                if not page:
                    break

                fresh_rows = 0
                for tx in page:
                    if not isinstance(tx, dict):
                        continue
                    signature = str(tx.get("signature") or "").strip()
                    if signature and signature in seen_signatures:
                        continue
                    if signature:
                        seen_signatures.add(signature)
                    transactions.append(tx)
                    fresh_rows += 1

                if fresh_rows == 0 or len(page) < self.PAGE_SIZE:
                    break

                before_signature = str(page[-1].get("signature") or "").strip() or None
                if not before_signature:
                    break

        return transactions

    async def _fetch_page(
        self,
        client: httpx.AsyncClient,
        endpoint: str,
        before_signature: str | None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "api-key": self.helius_api_key,
            "limit": self.PAGE_SIZE,
            "sort-order": "desc",
            "token-accounts": "all",
        }
        if before_signature:
            params["before-signature"] = before_signature

        for attempt in range(self.MAX_RETRIES):
            try:
                response = await client.get(endpoint, params=params)

                if response.status_code == 400 and before_signature:
                    fallback_params = dict(params)
                    fallback_params.pop("before-signature", None)
                    fallback_params["before"] = before_signature
                    response = await client.get(endpoint, params=fallback_params)

                if response.status_code == 429:
                    await asyncio.sleep(min(2**attempt, 30))
                    continue

                response.raise_for_status()
                payload = response.json()
                return payload if isinstance(payload, list) else []
            except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.RemoteProtocolError):
                await asyncio.sleep(min(2**attempt, 30))
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in {500, 502, 503, 504}:
                    await asyncio.sleep(min(2**attempt, 30))
                    continue
                return []
            except (httpx.RequestError, ValueError):
                await asyncio.sleep(min(2**attempt, 30))

        return []

    def _extract_program_ids(self, tx: dict[str, Any]) -> set[str]:
        program_ids: set[str] = set()

        def visit_instruction(instruction: Any) -> None:
            if not isinstance(instruction, dict):
                return

            candidates = [instruction.get("programId"), instruction.get("program_id")]
            program_info = instruction.get("programInfo")
            if isinstance(program_info, dict):
                candidates.extend(
                    [
                        program_info.get("programId"),
                        program_info.get("program_id"),
                    ]
                )

            for candidate in candidates:
                if isinstance(candidate, str) and candidate.strip():
                    program_ids.add(candidate.strip())

            for inner in instruction.get("innerInstructions", []) or []:
                visit_instruction(inner)

        for instruction in tx.get("instructions", []) or []:
            visit_instruction(instruction)

        return program_ids

    def _extract_stablecoin_value_usd(self, tx: dict[str, Any]) -> float:
        total = 0.0
        for transfer in tx.get("tokenTransfers", []) or []:
            if not self._transfer_is_wallet_related(transfer, tx):
                continue
            if not self._is_stable_transfer(transfer):
                continue
            total += self._extract_transfer_amount(transfer)
        return round(total, 6)

    def _extract_usdc_value(self, tx: dict[str, Any]) -> float:
        total = 0.0
        for transfer in tx.get("tokenTransfers", []) or []:
            if not self._transfer_is_wallet_related(transfer, tx):
                continue
            if not self._is_usdc_transfer(transfer):
                continue
            total += self._extract_transfer_amount(transfer)
        return round(total, 6)

    def _transfer_is_wallet_related(
        self,
        transfer: Any,
        tx: dict[str, Any] | None = None,
    ) -> bool:
        if not isinstance(transfer, dict):
            return False

        owners = {
            str(transfer.get("fromUserAccount") or ""),
            str(transfer.get("toUserAccount") or ""),
            str(transfer.get("fromOwner") or ""),
            str(transfer.get("toOwner") or ""),
            str(transfer.get("authority") or ""),
        }
        owners = {owner for owner in owners if owner}

        if self.wallet_address in owners:
            return True

        if tx and str(tx.get("feePayer") or "").strip() == self.wallet_address:
            return True

        return False

    def _extract_transfer_amount(self, transfer: dict[str, Any]) -> float:
        for candidate in (
            transfer.get("tokenAmount"),
            transfer.get("amount"),
            transfer.get("uiAmount"),
            transfer.get("tokenAmountUi"),
        ):
            amount = coerce_amount(candidate)
            if amount is not None:
                return abs(amount)
        return 0.0

    def _is_stable_transfer(self, transfer: dict[str, Any]) -> bool:
        symbol = str(transfer.get("symbol") or transfer.get("tokenSymbol") or "").upper()
        return symbol in self.USD_STABLE_SYMBOLS

    def _is_usdc_transfer(self, transfer: dict[str, Any]) -> bool:
        symbol = str(transfer.get("symbol") or transfer.get("tokenSymbol") or "").upper()
        return symbol in self.USDC_SYMBOLS

    def _is_liquidation(self, tx: dict[str, Any]) -> bool:
        searchable = self._build_search_text(tx)
        return "liquidate" in searchable or str(tx.get("type") or "").upper() == "LIQUIDATE"

    def _is_repayment(self, tx: dict[str, Any]) -> bool:
        searchable = self._build_search_text(tx)
        protocol_match = any(keyword in searchable for keyword in self.LENDING_PROTOCOL_KEYWORDS)
        repayment_match = any(keyword in searchable for keyword in self.REPAYMENT_KEYWORDS)
        return protocol_match and repayment_match

    def _build_search_text(self, tx: dict[str, Any]) -> str:
        parts: list[str] = [
            str(tx.get("type") or ""),
            str(tx.get("source") or ""),
            str(tx.get("description") or ""),
        ]

        for instruction in tx.get("instructions", []) or []:
            if not isinstance(instruction, dict):
                continue
            parts.extend(
                [
                    str(instruction.get("programId") or ""),
                    str(instruction.get("programName") or ""),
                    str(instruction.get("name") or ""),
                ]
            )
            program_info = instruction.get("programInfo")
            if isinstance(program_info, dict):
                parts.extend(
                    [
                        str(program_info.get("programName") or ""),
                        str(program_info.get("source") or ""),
                    ]
                )

        for log in tx.get("logMessages", []) or []:
            parts.append(str(log))

        events = tx.get("events")
        if events:
            try:
                parts.append(json.dumps(events, default=str))
            except TypeError:
                parts.append(str(events))

        return " ".join(parts).lower()


class EVMWalletFetcher:
    ETHERSCAN_URL = "https://api.etherscan.io/v2/api"
    PAGE_SIZE = 100
    MAX_RETRIES = 5
    CHAIN_IDS = {
        "ethereum": 1,
        "base": 8453,
        "arbitrum": 42161,
        "optimism": 10,
        "polygon": 137,
    }
    USD_STABLE_SYMBOLS = {
        "USDC",
        "USDC.E",
        "USDT",
        "USDT.E",
        "DAI",
        "PYUSD",
        "USDS",
        "GHO",
        "USDE",
    }
    USDC_SYMBOLS = {"USDC", "USDC.E"}
    LENDING_PROTOCOL_KEYWORDS = {
        "aave",
        "compound",
        "spark",
        "morpho",
        "maker",
        "radiant",
        "venus",
        "silo",
        "euler",
        "moonwell",
        "fluid",
        "gearbox",
    }
    REPAYMENT_KEYWORDS = {"repay", "repayment", "payback", "closeposition", "paybackall"}
    LIQUIDATION_KEYWORDS = {"liquidate", "liquidation", "liquidationcall"}

    def __init__(
        self,
        wallet_address: str,
        chain: str,
        etherscan_api_key: str,
        *,
        alchemy_api_key: str = "",
        timeout: float,
        max_pages: int | None,
    ) -> None:
        self.wallet_address = wallet_address.strip().lower()
        self.chain = chain
        self.etherscan_api_key = etherscan_api_key.strip()
        self.alchemy_api_key = alchemy_api_key.strip()
        self.timeout = timeout
        self.max_pages = max_pages

    async def fetch(self) -> dict[str, Any]:
        metrics = default_wallet_metrics()
        if not self.wallet_address or not self.etherscan_api_key:
            return metrics

        normal_txs, token_txs = await asyncio.gather(
            self._fetch_account_action("txlist"),
            self._fetch_account_action("tokentx"),
        )

        if not normal_txs and not token_txs:
            return metrics

        now = datetime.now(timezone.utc)
        cutoff_30d = now - timedelta(days=30)
        timestamps = [
            tx_time
            for tx_time in [*(self._extract_timestamps(normal_txs)), *(self._extract_timestamps(token_txs))]
            if tx_time is not None
        ]

        stable_value_by_hash: dict[str, float] = {}
        usdc_volume_30d = 0.0
        protocol_ids: set[str] = set()

        for tx in normal_txs:
            to_address = str(tx.get("to") or "").strip().lower()
            if to_address and to_address != self.wallet_address:
                protocol_ids.add(to_address)

        for tx in token_txs:
            tx_hash = str(tx.get("hash") or "").strip().lower()
            symbol = str(tx.get("tokenSymbol") or "").upper()
            amount = self._extract_token_amount(tx)

            contract_address = str(tx.get("contractAddress") or "").strip().lower()
            if contract_address:
                protocol_ids.add(contract_address)

            if symbol in self.USD_STABLE_SYMBOLS and amount > 0:
                stable_value_by_hash[tx_hash or f"nohash-{len(stable_value_by_hash)}"] = (
                    stable_value_by_hash.get(tx_hash, 0.0) + amount
                )

            tx_time = coerce_datetime(tx.get("timeStamp"))
            if tx_time and tx_time >= cutoff_30d and symbol in self.USDC_SYMBOLS:
                usdc_volume_30d += amount

        avg_transaction_value_usd = (
            round(sum(stable_value_by_hash.values()) / len(stable_value_by_hash), 2)
            if stable_value_by_hash
            else 0.0
        )

        liquidation_count = self._count_matching_hashes(normal_txs, self.LIQUIDATION_KEYWORDS)
        repayment_count = self._count_repayments(normal_txs)
        oldest_tx = min(timestamps) if timestamps else None
        newest_tx = max(timestamps) if timestamps else None

        metrics["wallet_age_days"] = max((now - oldest_tx).days, 0) if oldest_tx else 0
        metrics["total_transactions"] = len(
            {str(tx.get("hash") or "").strip().lower() for tx in normal_txs if tx.get("hash")}
        )
        metrics["unique_protocols"] = len(protocol_ids)
        metrics["avg_transaction_value_usd"] = avg_transaction_value_usd
        metrics["liquidation_count"] = liquidation_count
        metrics["repayment_count"] = repayment_count
        metrics["last_active_days_ago"] = (
            max((now - newest_tx).days, 0) if newest_tx else 0
        )
        metrics["usdc_volume_30d"] = round(usdc_volume_30d, 2)

        if self.alchemy_api_key:
            try:
                decoded_metrics = await fetch_evm_decoded(
                    self.wallet_address,
                    self.chain,
                    alchemy_api_key=self.alchemy_api_key,
                    timeout=self.timeout,
                )
                metrics["unique_protocols"] = int(decoded_metrics.get("unique_protocols", 0))
                metrics["repayment_count"] = int(decoded_metrics.get("repayment_count", 0))
                metrics["liquidation_count"] = int(decoded_metrics.get("liquidation_count", 0))
            except Exception as exc:
                logger.warning(
                    "Falling back to heuristic EVM metrics for %s on %s: %s",
                    self.wallet_address,
                    self.chain,
                    exc,
                )

        return metrics

    async def _fetch_account_action(self, action: str) -> list[dict[str, Any]]:
        chain_id = self.CHAIN_IDS.get(self.chain)
        if chain_id is None:
            return []

        rows: list[dict[str, Any]] = []
        page = 1
        pages = 0

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            while True:
                if self.max_pages is not None and pages >= self.max_pages:
                    break

                params = {
                    "chainid": chain_id,
                    "module": "account",
                    "action": action,
                    "address": self.wallet_address,
                    "page": page,
                    "offset": self.PAGE_SIZE,
                    "sort": "desc",
                    "apikey": self.etherscan_api_key,
                }
                page_rows = await self._fetch_page(client, params)
                pages += 1
                if not page_rows:
                    break

                rows.extend(page_rows)
                if len(page_rows) < self.PAGE_SIZE:
                    break

                page += 1

        return rows

    async def _fetch_page(
        self,
        client: httpx.AsyncClient,
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        for attempt in range(self.MAX_RETRIES):
            try:
                response = await client.get(self.ETHERSCAN_URL, params=params)
                if response.status_code == 429:
                    await asyncio.sleep(min(2**attempt, 30))
                    continue

                response.raise_for_status()
                payload = response.json()
                return self._parse_page_payload(payload)
            except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.RemoteProtocolError):
                await asyncio.sleep(min(2**attempt, 30))
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in {500, 502, 503, 504}:
                    await asyncio.sleep(min(2**attempt, 30))
                    continue
                return []
            except (httpx.RequestError, ValueError):
                await asyncio.sleep(min(2**attempt, 30))

        return []

    def _parse_page_payload(self, payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            return []

        status = str(payload.get("status") or "")
        message = str(payload.get("message") or "")
        result = payload.get("result")

        if isinstance(result, list):
            return [row for row in result if isinstance(row, dict)]

        if isinstance(result, str):
            lowered = result.lower()
            if "no transactions found" in lowered:
                return []
            if "rate limit" in lowered:
                raise ValueError("Rate limited by Etherscan.")
            if status == "0" and message.upper() == "NOTOK":
                return []

        return []

    def _extract_token_amount(self, tx: dict[str, Any]) -> float:
        value = tx.get("value")
        decimals = tx.get("tokenDecimal")
        try:
            return abs(float(value) / (10 ** int(decimals)))
        except (TypeError, ValueError, ZeroDivisionError):
            return 0.0

    def _extract_timestamps(self, rows: list[dict[str, Any]]) -> list[datetime | None]:
        return [coerce_datetime(row.get("timeStamp")) for row in rows]

    def _count_matching_hashes(
        self,
        rows: list[dict[str, Any]],
        keywords: set[str],
    ) -> int:
        matching_hashes: set[str] = set()
        for row in rows:
            searchable = self._build_search_text(row)
            if any(keyword in searchable for keyword in keywords):
                row_hash = str(row.get("hash") or "").strip().lower()
                if row_hash:
                    matching_hashes.add(row_hash)
        return len(matching_hashes)

    def _count_repayments(self, rows: list[dict[str, Any]]) -> int:
        matching_hashes: set[str] = set()
        for row in rows:
            searchable = self._build_search_text(row)
            protocol_match = any(keyword in searchable for keyword in self.LENDING_PROTOCOL_KEYWORDS)
            repayment_match = any(keyword in searchable for keyword in self.REPAYMENT_KEYWORDS)
            if protocol_match and repayment_match:
                row_hash = str(row.get("hash") or "").strip().lower()
                if row_hash:
                    matching_hashes.add(row_hash)
        return len(matching_hashes)

    @staticmethod
    def _build_search_text(row: dict[str, Any]) -> str:
        parts = [
            str(row.get("functionName") or ""),
            str(row.get("methodId") or ""),
            str(row.get("to") or ""),
            str(row.get("contractAddress") or ""),
            str(row.get("tokenName") or ""),
            str(row.get("tokenSymbol") or ""),
            str(row.get("input") or ""),
        ]
        return " ".join(parts).lower()
