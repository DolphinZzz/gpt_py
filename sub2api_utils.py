from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


TZ_CN = timezone(timedelta(hours=8))


def decode_jwt_payload(token: str) -> Dict[str, Any]:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return {}
        payload = parts[1]
        pad = (-len(payload)) % 4
        if pad:
            payload += "=" * pad
        return json.loads(base64.urlsafe_b64decode(payload.encode("ascii")).decode("utf-8"))
    except Exception:
        return {}


def load_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def pick_organization_id(access_payload: Dict[str, Any], id_payload: Dict[str, Any]) -> str:
    auth_a = access_payload.get("https://api.openai.com/auth", {}) or {}
    auth_i = id_payload.get("https://api.openai.com/auth", {}) or {}

    for source in (auth_a, auth_i):
        oid = source.get("organization_id")
        if oid:
            return oid
        orgs = source.get("organizations")
        if isinstance(orgs, list) and orgs:
            first = orgs[0] or {}
            if isinstance(first, dict) and first.get("id"):
                return first["id"]
    return ""


def iso_cn_from_ts(ts: Optional[int]) -> str:
    if not isinstance(ts, int) or ts <= 0:
        return ""
    return datetime.fromtimestamp(ts, tz=TZ_CN).isoformat(timespec="seconds")


def expires_in_from_ts(ts: Optional[int]) -> int:
    if not isinstance(ts, int):
        return 0
    remain = int(ts - datetime.now(timezone.utc).timestamp())
    return remain if remain > 0 else 0


def build_account(
    idx: int,
    access_token: str,
    refresh_token: str,
    id_token: str,
    fallback_email: str,
    platform: str = "openai",
) -> Dict[str, Any]:
    access_payload = decode_jwt_payload(access_token)
    id_payload = decode_jwt_payload(id_token) if id_token else {}

    auth = access_payload.get("https://api.openai.com/auth", {}) or {}
    profile = access_payload.get("https://api.openai.com/profile", {}) or {}

    email = profile.get("email") or id_payload.get("email") or fallback_email or ""
    exp_ts = access_payload.get("exp")
    org_id = pick_organization_id(access_payload, id_payload)

    return {
        "name": str(idx),
        "platform": platform,
        "type": "oauth",
        "credentials": {
            "access_token": access_token,
            "chatgpt_account_id": auth.get("chatgpt_account_id", ""),
            "chatgpt_user_id": auth.get("chatgpt_user_id") or auth.get("user_id", ""),
            "email": email,
            "expires_at": iso_cn_from_ts(exp_ts),
            "expires_in": expires_in_from_ts(exp_ts),
            "id_token": id_token,
            "organization_id": org_id,
            "refresh_token": refresh_token,
        },
        "extra": {
            "email": email,
        },
        "concurrency": 10,
        "priority": 1,
        "rate_multiplier": 1,
        "auto_pause_on_expired": True,
    }


def collect_from_sub2api_json(path: Path) -> List[Dict[str, Any]]:
    data = load_json(path)
    accounts = data.get("accounts") if isinstance(data, dict) else []
    if not isinstance(accounts, list):
        return []
    return [item for item in accounts if isinstance(item, dict)]


def collect_from_codex_tokens(tokens_dir: Path) -> List[Dict[str, Any]]:
    accounts: List[Dict[str, Any]] = []
    files = sorted(tokens_dir.glob("*.json"))
    idx = 1

    for file in files:
        data = load_json(file)
        access_token = (data.get("access_token") or "").strip()
        refresh_token = (data.get("refresh_token") or "").strip()
        id_token = (data.get("id_token") or "").strip()
        email = (data.get("email") or file.stem).strip()

        if not access_token or not refresh_token:
            continue

        accounts.append(
            build_account(
                idx=idx,
                access_token=access_token,
                refresh_token=refresh_token,
                id_token=id_token,
                fallback_email=email,
            )
        )
        idx += 1

    return accounts


def read_non_empty_lines(path: Path) -> List[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def collect_from_ak_rk(ak_file: Path, rk_file: Path) -> List[Dict[str, Any]]:
    aks = read_non_empty_lines(ak_file)
    rks = read_non_empty_lines(rk_file)
    size = min(len(aks), len(rks))
    accounts: List[Dict[str, Any]] = []

    for i in range(size):
        access_token = aks[i]
        refresh_token = rks[i]
        payload = decode_jwt_payload(access_token)
        profile = payload.get("https://api.openai.com/profile", {}) or {}
        email = profile.get("email", "")

        accounts.append(
            build_account(
                idx=i + 1,
                access_token=access_token,
                refresh_token=refresh_token,
                id_token="",
                fallback_email=email,
            )
        )

    return accounts


def collect_from_results_file(results_file: Path) -> List[Dict[str, Any]]:
    if not results_file.exists():
        return []

    accounts: List[Dict[str, Any]] = []
    idx = 1

    for line in results_file.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue

        parts = text.split("----")
        if len(parts) < 4:
            continue

        email = parts[0].strip()
        access_token = ""
        refresh_token = ""
        id_token = ""

        for part in parts[3:]:
            if part.startswith("access_token="):
                access_token = part.split("=", 1)[1].strip()
            elif part.startswith("refresh_token="):
                refresh_token = part.split("=", 1)[1].strip()
            elif part.startswith("id_token="):
                id_token = part.split("=", 1)[1].strip()

        if not access_token or not refresh_token:
            continue

        accounts.append(
            build_account(
                idx=idx,
                access_token=access_token,
                refresh_token=refresh_token,
                id_token=id_token,
                fallback_email=email,
            )
        )
        idx += 1

    return accounts
