#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from sub2api_utils import (
    build_account,
    collect_from_ak_rk,
    collect_from_codex_tokens,
    collect_from_results_file,
    collect_from_sub2api_json,
    decode_jwt_payload,
    expires_in_from_ts,
    iso_cn_from_ts,
    load_json,
    pick_organization_id,
    read_non_empty_lines,
)

__all__ = [
    "build_account",
    "collect_from_ak_rk",
    "collect_from_codex_tokens",
    "collect_from_results_file",
    "collect_from_sub2api_json",
    "decode_jwt_payload",
    "expires_in_from_ts",
    "iso_cn_from_ts",
    "load_json",
    "pick_organization_id",
    "read_non_empty_lines",
]


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
    output_path = base_dir / args.output

    tokens_dir = base_dir / args.tokens_dir
    if tokens_dir.exists() and tokens_dir.is_dir():
        accounts = collect_from_codex_tokens(tokens_dir)
    else:
        accounts = []
    if not accounts:
        accounts = collect_from_results_file(base_dir / args.results_file)
    if not accounts:
        accounts = collect_from_ak_rk(base_dir / args.ak_file, base_dir / args.rk_file)
    if not accounts:
        accounts = collect_from_sub2api_json(output_path)

    output = {
        "exported_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "proxies": [],
        "accounts": accounts,
    }

    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[ok] accounts={len(accounts)}")
    print(f"[ok] output={output_path}")


if __name__ == "__main__":
    main()
