from __future__ import annotations

import base64
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


TZ_CN = timezone(timedelta(hours=8))
HELPER_CSV_HEADERS = [
    "email",
    "token",
    "refresh_token",
    "id_token",
    "chatgpt_account_id",
    "oai_device_id",
    "expire_at",
]


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


def helper_expire_at_from_ts(ts: Optional[int]) -> str:
    if not isinstance(ts, int) or ts <= 0:
        return ""
    return datetime.fromtimestamp(ts, tz=TZ_CN).strftime("%Y/%m/%d %H:%M:%S")


def parse_helper_expire_at(value: str) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None

    patterns = (
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    )
    for pattern in patterns:
        try:
            parsed = datetime.strptime(raw, pattern)
            return parsed.replace(tzinfo=TZ_CN)
        except ValueError:
            continue
    return None


def helper_expire_at_to_iso(value: str) -> str:
    parsed = parse_helper_expire_at(value)
    if not parsed:
        return ""
    return parsed.isoformat(timespec="seconds")


def expires_in_from_dt(value: Optional[datetime]) -> int:
    if value is None:
        return 0
    remain = int(value.astimezone(timezone.utc).timestamp() - datetime.now(timezone.utc).timestamp())
    return remain if remain > 0 else 0


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


def build_helper_csv_row(
    idx: int,
    access_token: str,
    refresh_token: str,
    id_token: str,
    fallback_email: str,
) -> Dict[str, str]:
    account = build_account(
        idx=idx,
        access_token=access_token,
        refresh_token=refresh_token,
        id_token=id_token,
        fallback_email=fallback_email,
    )
    credentials = account.get("credentials", {}) if isinstance(account, dict) else {}
    if not isinstance(credentials, dict):
        credentials = {}

    payload = decode_jwt_payload(access_token)
    auth = payload.get("https://api.openai.com/auth", {}) or {}
    exp_ts = payload.get("exp")

    return {
        "email": str(credentials.get("email") or fallback_email or "").strip(),
        "token": access_token,
        "refresh_token": refresh_token,
        "id_token": id_token,
        "chatgpt_account_id": str(credentials.get("chatgpt_account_id") or auth.get("chatgpt_account_id") or "").strip(),
        "oai_device_id": "",
        "expire_at": helper_expire_at_from_ts(exp_ts),
    }


def account_to_helper_csv_row(account: Dict[str, Any]) -> Dict[str, str]:
    credentials = account.get("credentials", {}) if isinstance(account, dict) else {}
    extra = account.get("extra", {}) if isinstance(account, dict) else {}
    if not isinstance(credentials, dict):
        credentials = {}
    if not isinstance(extra, dict):
        extra = {}

    token = str(credentials.get("access_token") or "").strip()
    refresh_token = str(credentials.get("refresh_token") or "").strip()
    id_token = str(credentials.get("id_token") or "").strip()
    email = str(credentials.get("email") or extra.get("email") or "").strip()
    chatgpt_account_id = str(credentials.get("chatgpt_account_id") or "").strip()
    expire_at_iso = str(credentials.get("expires_at") or "").strip()
    expire_at = ""

    if expire_at_iso:
        try:
            expire_at = datetime.fromisoformat(expire_at_iso).astimezone(TZ_CN).strftime("%Y/%m/%d %H:%M:%S")
        except Exception:
            parsed = parse_helper_expire_at(expire_at_iso)
            expire_at = parsed.strftime("%Y/%m/%d %H:%M:%S") if parsed else ""

    if not expire_at and token:
        exp_ts = decode_jwt_payload(token).get("exp")
        expire_at = helper_expire_at_from_ts(exp_ts)

    return {
        "email": email,
        "token": token,
        "refresh_token": refresh_token,
        "id_token": id_token,
        "chatgpt_account_id": chatgpt_account_id,
        "oai_device_id": "",
        "expire_at": expire_at,
    }


def write_helper_csv(path: Path, accounts: List[Dict[str, Any]]) -> None:
    rows = [account_to_helper_csv_row(account) for account in accounts if isinstance(account, dict)]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HELPER_CSV_HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: str(row.get(key, "") or "") for key in HELPER_CSV_HEADERS})


def collect_from_sub2api_json(path: Path) -> List[Dict[str, Any]]:
    data = load_json(path)
    accounts = data.get("accounts") if isinstance(data, dict) else []
    if not isinstance(accounts, list):
        return []
    return [item for item in accounts if isinstance(item, dict)]


def collect_from_helper_csv(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []

    accounts: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for idx, row in enumerate(reader, start=1):
            if not isinstance(row, dict):
                continue

            access_token = str(row.get("token") or row.get("access_token") or "").strip()
            refresh_token = str(row.get("refresh_token") or "").strip()
            id_token = str(row.get("id_token") or "").strip()
            email = str(row.get("email") or "").strip()
            chatgpt_account_id = str(row.get("chatgpt_account_id") or row.get("account_id") or "").strip()
            expire_at = str(row.get("expire_at") or row.get("expires_at") or "").strip()

            if not access_token or not refresh_token:
                continue

            account = build_account(
                idx=idx,
                access_token=access_token,
                refresh_token=refresh_token,
                id_token=id_token,
                fallback_email=email,
            )
            credentials = account.get("credentials", {})
            if not isinstance(credentials, dict):
                continue

            if chatgpt_account_id:
                credentials["chatgpt_account_id"] = chatgpt_account_id

            expire_dt = parse_helper_expire_at(expire_at)
            if expire_dt:
                credentials["expires_at"] = expire_dt.isoformat(timespec="seconds")
                credentials["expires_in"] = expires_in_from_dt(expire_dt)

            if email:
                credentials["email"] = email
                account.setdefault("extra", {})["email"] = email

            accounts.append(account)

    return accounts


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
