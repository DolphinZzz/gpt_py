#!/usr/bin/env python3
import argparse
import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


TZ_CN = timezone(timedelta(hours=8))


def decode_jwt_payload(token: str) -> Dict:
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


def load_json(path: Path) -> Dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def parse_proxy(raw_proxy: str, proxy_name: str) -> Tuple[str, Dict]:
    proxy = (raw_proxy or "").strip()
    if not proxy:
        protocol = "http"
        host = "127.0.0.1"
        port = 1080
    else:
        protocol = "http"
        body = proxy
        if "://" in body:
            protocol, body = body.split("://", 1)
        body = body.rsplit("@", 1)[-1]
        if ":" in body:
            host, port_text = body.rsplit(":", 1)
            try:
                port = int(port_text)
            except Exception:
                port = 1080
        else:
            host = body
            port = 1080
        host = host or "127.0.0.1"

    if host in {"127.0.0.1", "localhost"}:
        host = "host.docker.internal"

    proxy_key = f"{protocol}|{host}|{port}||"
    proxy_obj = {
        "proxy_key": proxy_key,
        "name": proxy_name,
        "protocol": protocol,
        "host": host,
        "port": port,
        "status": "active",
    }
    return proxy_key, proxy_obj


def pick_organization_id(access_payload: Dict, id_payload: Dict) -> str:
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
) -> Dict:
    access_payload = decode_jwt_payload(access_token)
    id_payload = decode_jwt_payload(id_token) if id_token else {}

    auth = access_payload.get("https://api.openai.com/auth", {}) or {}
    profile = access_payload.get("https://api.openai.com/profile", {}) or {}

    email = profile.get("email") or id_payload.get("email") or fallback_email or ""
    exp_ts = access_payload.get("exp")

    org_id = pick_organization_id(access_payload, id_payload)

    account = {
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
    return account


def collect_from_codex_tokens(tokens_dir: Path) -> List[Dict]:
    accounts: List[Dict] = []
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
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if text:
            lines.append(text)
    return lines


def collect_from_ak_rk(ak_file: Path, rk_file: Path) -> List[Dict]:
    aks = read_non_empty_lines(ak_file)
    rks = read_non_empty_lines(rk_file)
    size = min(len(aks), len(rks))
    accounts: List[Dict] = []

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


def collect_from_results_file(results_file: Path) -> List[Dict]:
    if not results_file.exists():
        return []

    accounts: List[Dict] = []
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert existing tokens to sub2api JSON format")
    parser.add_argument("--base-dir", default=".", help="Project directory containing config/tokens")
    parser.add_argument("--tokens-dir", default="codex_tokens", help="Directory of per-account token json")
    parser.add_argument("--ak-file", default="ak.txt", help="Access-token line file")
    parser.add_argument("--rk-file", default="rk.txt", help="Refresh-token line file")
    parser.add_argument("--results-file", default="registered_accounts.txt", help="Registered accounts file with tokens")
    parser.add_argument("--output", default="sub2api_accounts.json", help="Output JSON filename")
    args = parser.parse_args()

    base_dir = Path(args.base_dir).resolve()

    tokens_dir = base_dir / args.tokens_dir
    if tokens_dir.exists() and tokens_dir.is_dir():
        accounts = collect_from_codex_tokens(tokens_dir)
    else:
        accounts = []

    if not accounts:
        accounts = collect_from_results_file(base_dir / args.results_file)

    if not accounts:
        accounts = collect_from_ak_rk(base_dir / args.ak_file, base_dir / args.rk_file)

    output = {
        "exported_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "proxies": [],
        "accounts": accounts,
    }

    output_path = base_dir / args.output
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[ok] accounts={len(accounts)}")
    print(f"[ok] output={output_path}")


if __name__ == "__main__":
    main()
