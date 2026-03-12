import json
import os
import threading
import traceback
from pathlib import Path

import chatgpt_register


def _to_int(value: object, default: int) -> int:
    try:
        parsed = int(str(value))
        return parsed if parsed > 0 else default
    except Exception:
        return default


def _load_runtime_config() -> dict:
    config_path = Path(os.getenv("CONFIG_PATH", "/app/config.json"))
    cfg: dict = {}
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text("utf-8"))
        except Exception:
            cfg = {}

    cfg["proxy"] = os.getenv("PROXY_URL", str(cfg.get("proxy", "")))
    cfg["total_accounts"] = _to_int(os.getenv("TOTAL_ACCOUNTS", cfg.get("total_accounts", 3)), 3)
    cfg["max_workers"] = _to_int(os.getenv("MAX_WORKERS", cfg.get("max_workers", 3)), 3)
    cfg["results_dir"] = os.getenv("RESULTS_DIR", str(cfg.get("results_dir", "/data/results")))
    return cfg


def main() -> None:
    stop_flag = Path(os.getenv("STOP_FLAG_PATH", "/data/stop.flag"))
    if stop_flag.exists():
        print("stop flag detected")
        return

    cfg = _load_runtime_config()
    chatgpt_register.reload_config(cfg)
    chatgpt_register.RUN_OUTPUT_DIR = None

    total = _to_int(cfg.get("total_accounts", 3), 3)
    workers = _to_int(cfg.get("max_workers", 3), 3)
    proxy = str(cfg.get("proxy", "")).strip() or None

    print(f"[worker] using latest chatgpt_register.py total={total} workers={workers} proxy={proxy or 'none'}")
    chatgpt_register.run_batch(
        total_accounts=total,
        max_workers=workers,
        proxy=proxy,
        stop_event=threading.Event(),
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[worker] fatal error: {exc}")
        traceback.print_exc()
        raise
