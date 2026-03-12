"""
ChatGPT 批量注册工具 - FastAPI 后端
启动: python main.py
访问: http://localhost:8000
"""

from __future__ import annotations

import os
import re
import json
import time
import socket
import asyncio
import threading
import subprocess
import hashlib
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional, Any, Union
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel
from curl_cffi import requests as curl_requests

import chatgpt_register
import convert_tokens_to_sub2api as sub2api
from GetMail.mail_service import lookup_mailbox as getmail_lookup_mailbox

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
RESULTS_DIR_NAME = "results"
SUB2API_OUTPUT_NAME = "sub2api_accounts.json"


def _parse_proxy_endpoint(raw_proxy: str) -> Optional[tuple[str, int]]:
    proxy = str(raw_proxy or "").strip()
    if not proxy:
        return None
    parsed = urlparse(proxy if "://" in proxy else f"http://{proxy}")
    host = (parsed.hostname or "").strip()
    if not host:
        return None
    return host, int(parsed.port or 1080)


def _resolve_runtime_proxy(raw_proxy: str) -> tuple[str, Optional[str]]:
    proxy = str(raw_proxy or "").strip()
    if not proxy:
        return "", None

    endpoint = _parse_proxy_endpoint(proxy)
    if not endpoint:
        return proxy, None

    host, port = endpoint
    local_hosts = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}
    if host not in local_hosts:
        return proxy, None

    check_host = "127.0.0.1" if host in {"localhost", "0.0.0.0"} else host
    try:
        with socket.create_connection((check_host, port), timeout=0.5):
            return proxy, None
    except OSError as e:
        detail = str(e).strip() or e.__class__.__name__
        return "", f"本地代理 {proxy} 不可用（{detail}），本次任务已自动改为直连。"


# ==================== Pydantic Models ====================

class ConfigModel(BaseModel):
    total_accounts: int = 3
    resend_api_base: str = "https://api.resend.com"
    resend_api_key: str = ""
    resend_domain: str = ""
    proxy: str = ""
    output_file: str = "registered_accounts.txt"
    enable_oauth: bool = True
    oauth_required: bool = True
    oauth_issuer: str = "https://auth.openai.com"
    oauth_client_id: str = "app_EMoamEEZ73f0CkXaXp7hrann"
    oauth_redirect_uri: str = "http://localhost:1455/auth/callback"
    ak_file: str = "ak.txt"
    rk_file: str = "rk.txt"
    token_json_dir: str = "codex_tokens"
    results_dir: str = "results"
    max_workers: int = 3
    use_containers: bool = False
    container_count: int = 1
    docker_project_dir: str = "."
    docker_compose_file: str = "docker-compose.yml"
    docker_worker_service: str = "worker"
    docker_warp_service: str = "warp"
    sub2api_auto_upload: bool = True
    sub2api_upload_url: str = "https://www.codex.hair/api/v1/admin/accounts/data"
    sub2api_upload_bearer: str = ""
    sub2api_upload_cookie: str = ""
    sub2api_upload_user_agent: str = ""
    sub2api_upload_proxy: str = ""
    sub2api_skip_default_group_bind: bool = True
    sub2api_auto_group_bind: bool = True
    sub2api_group_id: int = 2


class StartTaskRequest(BaseModel):
    total_accounts: Optional[int] = None
    max_workers: Optional[int] = None
    proxy: Optional[str] = None
    use_containers: Optional[bool] = None
    container_count: Optional[int] = None


class ConvertRequest(BaseModel):
    source: str = "auto"           # auto | sub2api_json | codex_tokens | ak_rk | results_file
    run_id: Optional[str] = None   # specific run from results/
    concurrency: int = 10
    priority: int = 1
    rate_multiplier: float = 1.0
    auto_pause_on_expired: bool = True
    output_filename: str = SUB2API_OUTPUT_NAME


class MailboxCodeQueryRequest(BaseModel):
    mail_token: str
    timeout: int = 15


# ==================== Task Manager ====================

class TaskManager:
    def __init__(self):
        self.status = "idle"  # idle | running | stopping | finished
        self.mode = "local"   # local | containers
        self.task_id: Optional[str] = None
        self.start_time: Optional[float] = None
        self.success_count = 0
        self.fail_count = 0
        self.total_target = 0
        self.container_target = 0
        self.container_running = 0
        self.log_buffer: deque = deque(maxlen=5000)
        self.log_subscribers: list[asyncio.Queue] = []
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock = threading.Lock()
        self._compose_file: Optional[str] = None
        self._project_dir: Optional[str] = None
        self._worker_service: Optional[str] = None
        self._warp_service: Optional[str] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    def emit_log(self, level: str, tag: str, message: str):
        entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "level": level,
            "tag": tag,
            "message": message,
        }
        self.log_buffer.append(entry)

        if level == "success":
            with self._lock:
                self.success_count += 1
        elif level == "error" and "注册失败" in message:
            with self._lock:
                self.fail_count += 1

        if self._loop:
            for q in list(self.log_subscribers):
                try:
                    self._loop.call_soon_threadsafe(q.put_nowait, entry)
                except Exception:
                    pass

    def _run_compose(self, args: list[str], timeout: int = 120) -> str:
        project_dir = self._project_dir or str(BASE_DIR)
        compose_file = self._compose_file or "docker-compose.yml"
        command = [
            "docker", "compose",
            "--project-directory", project_dir,
            "-f", compose_file,
            *args,
        ]
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout or "docker compose command failed").strip()
            raise RuntimeError(msg)
        return (proc.stdout or "").strip()

    def _docker_running_workers(self) -> int:
        if not self._worker_service:
            return 0
        out = self._run_compose(["ps", "-q", self._worker_service], timeout=30)
        if not out:
            return 0
        return len([line for line in out.splitlines() if line.strip()])

    def _start_container_mode(self):
        worker_service = self._worker_service or "worker"
        target_total = max(1, self.total_target) * max(1, self.container_target)
        self.emit_log(
            "info",
            "system",
            f"容器模式启动: {worker_service} x {self.container_target} (目标 {target_total})",
        )

        if self._warp_service:
            self._run_compose(["up", "-d", self._warp_service], timeout=180)

        self._run_compose(
            ["up", "-d", "--scale", f"{worker_service}={self.container_target}", worker_service],
            timeout=300,
        )

        first_seen = False
        while True:
            if self._stop_event.is_set():
                self._run_compose(["stop", worker_service], timeout=120)
                self.status = "stopped"
                self.container_running = 0
                self.emit_log("info", "system", "容器任务已停止")
                return

            running = self._docker_running_workers()
            self.container_running = running

            scanned_total, scanned_success = self._scan_container_progress()
            if scanned_total >= target_total:
                self._run_compose(["stop", worker_service], timeout=120)
                self.container_running = 0
                self.success_count = scanned_success
                self.fail_count = max(0, scanned_total - scanned_success)
                self._auto_convert_and_upload()
                self.status = "finished"
                self.emit_log("info", "system", f"容器任务达到目标并已停止: {scanned_total}/{target_total}")
                return

            if running > 0:
                first_seen = True
            elif first_seen:
                self._auto_convert_and_upload()
                self.status = "finished"
                self.emit_log("info", "system", "容器任务结束: 所有 worker 已退出")
                return

            time.sleep(3)

    def _auto_convert_and_upload(self):
        config = _load_config()
        if not bool(config.get("sub2api_auto_upload", True)):
            self.emit_log("info", "system", "自动导入已关闭，跳过上传")
            return

        work_dir = _resolve_default_convert_dir(config, "auto")
        accounts = _collect_sub2api_accounts(work_dir, "auto", config)
        if not accounts:
            self.emit_log("error", "system", "自动转换失败: 未找到可导入账号")
            return

        from datetime import timezone as tz
        output = {
            "exported_at": datetime.now(tz.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "proxies": [],
            "accounts": accounts,
        }

        output_path = work_dir / "sub2api_accounts.json"
        output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        self.emit_log("info", "system", f"已自动转换 sub2api: {output_path}")

        uploaded = _load_uploaded_token_fingerprints()
        pending_accounts, skipped_uploaded, skipped_duplicate = _pick_pending_accounts(accounts, uploaded)
        if not pending_accounts:
            self.emit_log("info", "system", "自动上传跳过: 全部账号已上传或重复")
            return

        upload_output = {
            "exported_at": output["exported_at"],
            "proxies": [],
            "accounts": pending_accounts,
        }

        before_ok, before_data = _fetch_accounts_page(config, page=1, page_size=max(200, min(1000, len(pending_accounts) * 3)))
        before_ids: set[int] = set()
        if before_ok and isinstance(before_data, dict):
            items = (((before_data.get("data") or {}).get("items")) or [])
            if isinstance(items, list):
                before_ids = {x["id"] for x in items if isinstance(x, dict) and isinstance(x.get("id"), int)}

        ok, detail = _upload_sub2api_data(config, upload_output)
        if ok:
            added = _mark_uploaded_accounts(pending_accounts)
            self.emit_log("success", "system", f"已上传到中转站: {detail}")
            bind_ok, bind_detail = _bind_new_uploaded_accounts(config, before_ids, len(pending_accounts))
            if bind_ok:
                self.emit_log("info", "system", f"分组更新: {bind_detail}")
            else:
                self.emit_log("error", "system", f"分组更新失败: {bind_detail}")
            self.emit_log(
                "info",
                "system",
                f"上传统计: 本次 {len(pending_accounts)}，已记录 {added}，历史已上传跳过 {skipped_uploaded}，批内重复跳过 {skipped_duplicate}",
            )
        else:
            self.emit_log("error", "system", f"上传失败: {detail}")

    def start_batch(self, total_accounts: int, max_workers: int, proxy: str, *, use_containers: bool = False,
                    container_count: int = 1, config: Optional[dict] = None):
        if self.status == "running":
            raise RuntimeError("任务正在运行中")

        self._stop_event.clear()
        self.status = "running"
        self.mode = "containers" if use_containers else "local"
        self.task_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.start_time = time.time()
        self.success_count = 0
        self.fail_count = 0
        self.total_target = total_accounts
        self.container_target = max(1, int(container_count or 1))
        self.container_running = 0
        self.log_buffer.clear()

        if use_containers:
            cfg = config or {}
            project = Path(str(cfg.get("docker_project_dir", ".")))
            compose = Path(str(cfg.get("docker_compose_file", "docker-compose.yml")))
            if not project.is_absolute():
                project = (BASE_DIR / project).resolve()
            if not compose.is_absolute():
                compose = (project / compose).resolve()

            self._project_dir = str(project)
            self._compose_file = str(compose)
            self._worker_service = str(cfg.get("docker_worker_service", "worker"))
            self._warp_service = str(cfg.get("docker_warp_service", "warp"))

            stop_flag = project / "share" / "stop.flag"
            if stop_flag.exists():
                try:
                    stop_flag.unlink()
                    self.emit_log("info", "system", f"已清理停止标记: {stop_flag}")
                except Exception as e:
                    self.emit_log("error", "system", f"清理 stop.flag 失败: {e}")

            if not Path(self._compose_file).exists():
                raise RuntimeError(f"compose 文件不存在: {self._compose_file}")
        else:
            # Reset output dir so a new timestamp folder is created
            chatgpt_register.RUN_OUTPUT_DIR = None
            chatgpt_register.set_log_callback(self.emit_log)
            proxy, proxy_warning = _resolve_runtime_proxy(proxy)
            if proxy_warning:
                self.emit_log("error", "system", proxy_warning)

        def _run():
            try:
                if use_containers:
                    self._start_container_mode()
                else:
                    self.emit_log("info", "system", f"任务启动: {total_accounts} 个账号, 并发 {max_workers}")
                    chatgpt_register.run_batch(
                        total_accounts=total_accounts,
                        max_workers=max_workers,
                        proxy=proxy,
                        stop_event=self._stop_event,
                    )
            except Exception as e:
                self.emit_log("error", "system", f"任务异常终止: {e}")
                self.status = "stopped"
            finally:
                if not use_containers and self._stop_event.is_set():
                    self.status = "stopped"
                    self.emit_log("info", "system", "任务已停止")
                elif not use_containers and self.status != "stopped":
                    self._auto_convert_and_upload()
                    self.status = "finished"
                    self.emit_log("info", "system",
                                  f"任务完成: 成功 {self.success_count}, 失败 {self.fail_count}")

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def stop_batch(self):
        if self.status != "running":
            raise RuntimeError("没有正在运行的任务")
        self._stop_event.set()
        self.status = "stopping"

    def get_status(self) -> dict:
        elapsed = None
        if self.start_time:
            elapsed = round(time.time() - self.start_time, 1)

        success_count = self.success_count
        fail_count = self.fail_count
        total_target = self.total_target

        if self.mode == "containers":
            total_target = self.total_target * max(1, self.container_target)
            scanned_total, scanned_success = self._scan_container_progress()
            if scanned_total >= 0:
                success_count = scanned_success
                fail_count = max(0, scanned_total - scanned_success)

        return {
            "status": self.status,
            "mode": self.mode,
            "task_id": self.task_id,
            "start_time": datetime.fromtimestamp(self.start_time).strftime("%Y-%m-%d %H:%M:%S") if self.start_time else None,
            "success_count": success_count,
            "fail_count": fail_count,
            "total_target": total_target,
            "container_target": self.container_target,
            "container_running": self.container_running,
            "elapsed_seconds": elapsed,
        }

    def _scan_container_progress(self) -> tuple[int, int]:
        if not self.start_time:
            return -1, -1

        roots: list[Path] = []
        if self._project_dir:
            project = Path(self._project_dir)
            roots.extend([
                project / "app" / "results",
                project / "share" / "results",
            ])

        roots.append(BASE_DIR / "results")

        cutoff = self.start_time - 300
        total = 0
        success = 0
        found = False

        for root in roots:
            if not root.exists() or not root.is_dir():
                continue

            for run_dir in root.iterdir():
                if not run_dir.is_dir() or not re.match(r"\d{8}_\d{6}", run_dir.name):
                    continue

                reg_file = run_dir / "registered_accounts.txt"
                if not reg_file.exists():
                    continue

                try:
                    if reg_file.stat().st_mtime < cutoff:
                        continue
                except Exception:
                    continue

                found = True
                try:
                    for line in reg_file.read_text("utf-8").splitlines():
                        text = line.strip()
                        if not text:
                            continue
                        total += 1
                        if "oauth=ok" in text:
                            success += 1
                except Exception:
                    continue

        if not found:
            return -1, -1
        return total, success


task_manager = TaskManager()


# ==================== Config Helpers ====================

def _load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text("utf-8"))
    return {}


def _save_config(data: dict):
    CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    chatgpt_register.reload_config(data)


def _resolve_compose_paths(config: dict) -> tuple[str, str]:
    project = Path(str(config.get("docker_project_dir", ".")))
    compose = Path(str(config.get("docker_compose_file", "docker-compose.yml")))
    if not project.is_absolute():
        project = (BASE_DIR / project).resolve()
    if not compose.is_absolute():
        compose = (project / compose).resolve()
    return str(project), str(compose)


def _result_roots() -> list[Path]:
    roots: list[Path] = [BASE_DIR / RESULTS_DIR_NAME]
    config = _load_config()
    project = Path(str(config.get("docker_project_dir", ".")))
    if not project.is_absolute():
        project = (BASE_DIR / project).resolve()
    roots.extend([
        project / "app" / "results",
        project / "share" / "results",
    ])

    seen: set[str] = set()
    uniq: list[Path] = []
    for root in roots:
        key = str(root.resolve()) if root.exists() else str(root)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(root)
    return uniq


def _locate_run_dir(run_id: str) -> Optional[Path]:
    for root in _result_roots():
        candidate = root / run_id
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


def _has_non_empty_file(path: Path) -> bool:
    return path.exists() and path.is_file() and path.stat().st_size > 0


def _detect_convert_sources(work_dir: Path, config: dict) -> list[str]:
    sources: list[str] = []
    token_dir_name = str(config.get("token_json_dir", "codex_tokens"))
    output_name = str(config.get("output_file", "registered_accounts.txt"))
    ak_name = str(config.get("ak_file", "ak.txt"))
    rk_name = str(config.get("rk_file", "rk.txt"))

    tokens_dir = work_dir / token_dir_name
    if _has_non_empty_file(work_dir / SUB2API_OUTPUT_NAME):
        sources.append("sub2api_json")
    if tokens_dir.exists() and tokens_dir.is_dir() and any(tokens_dir.glob("*.json")):
        sources.append("codex_tokens")
    if _has_non_empty_file(work_dir / output_name):
        sources.append("results_file")
    if _has_non_empty_file(work_dir / ak_name) and _has_non_empty_file(work_dir / rk_name):
        sources.append("ak_rk")
    return sources


def _resolve_default_convert_dir(config: dict, source: str) -> Path:
    histories = _scan_history()

    for item in histories:
        d = Path(str(item.get("path", "")))
        if not d.exists() or not d.is_dir():
            continue

        sources = _detect_convert_sources(d, config)
        if source == "auto" and sources:
            return d
        if source in sources:
            return d

    return BASE_DIR


def _upload_state_path() -> Path:
    return BASE_DIR / "uploaded_sub2api_tokens.json"


def _load_uploaded_token_fingerprints() -> set[str]:
    path = _upload_state_path()
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text("utf-8"))
    except Exception:
        return set()
    items = data.get("uploaded_fingerprints") if isinstance(data, dict) else []
    if not isinstance(items, list):
        return set()
    return {str(x).strip() for x in items if str(x).strip()}


def _save_uploaded_token_fingerprints(values: set[str]) -> None:
    path = _upload_state_path()
    from datetime import timezone as tz
    payload = {
        "updated_at": datetime.now(tz.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "uploaded_fingerprints": sorted(values),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _token_fingerprint(access_token: str) -> str:
    token = (access_token or "").strip()
    if not token:
        return ""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _pick_pending_accounts(accounts: list[dict], uploaded: set[str]) -> tuple[list[dict], int, int]:
    pending: list[dict] = []
    seen_in_batch: set[str] = set()
    skipped_uploaded = 0
    skipped_duplicate = 0

    for acc in accounts:
        if not isinstance(acc, dict):
            continue
        creds = acc.get("credentials") or {}
        access_token = ""
        if isinstance(creds, dict):
            access_token = str(creds.get("access_token") or "").strip()
        fp = _token_fingerprint(access_token)
        if not fp:
            continue
        if fp in uploaded:
            skipped_uploaded += 1
            continue
        if fp in seen_in_batch:
            skipped_duplicate += 1
            continue
        seen_in_batch.add(fp)
        pending.append(acc)

    return pending, skipped_uploaded, skipped_duplicate


def _mark_uploaded_accounts(accounts: list[dict]) -> int:
    uploaded = _load_uploaded_token_fingerprints()
    before = len(uploaded)
    for acc in accounts:
        if not isinstance(acc, dict):
            continue
        creds = acc.get("credentials") or {}
        if not isinstance(creds, dict):
            continue
        fp = _token_fingerprint(str(creds.get("access_token") or ""))
        if fp:
            uploaded.add(fp)
    if len(uploaded) != before:
        _save_uploaded_token_fingerprints(uploaded)
    return len(uploaded) - before


def _collect_sub2api_accounts(work_dir: Path, source: str, config: dict) -> list[dict]:
    source_order = ["sub2api_json", "codex_tokens", "results_file", "ak_rk"] if source == "auto" else [source]

    for item in source_order:
        if item == "sub2api_json":
            accounts = sub2api.collect_from_sub2api_json(work_dir / SUB2API_OUTPUT_NAME)
        elif item == "codex_tokens":
            tokens_dir = work_dir / config.get("token_json_dir", "codex_tokens")
            accounts = sub2api.collect_from_codex_tokens(tokens_dir) if tokens_dir.exists() and tokens_dir.is_dir() else []
        elif item == "results_file":
            results_file = work_dir / config.get("output_file", "registered_accounts.txt")
            accounts = sub2api.collect_from_results_file(results_file)
        elif item == "ak_rk":
            ak_file = work_dir / config.get("ak_file", "ak.txt")
            rk_file = work_dir / config.get("rk_file", "rk.txt")
            accounts = sub2api.collect_from_ak_rk(ak_file, rk_file)
        else:
            accounts = []

        if accounts:
            return accounts

    return []


def _normalize_bearer(raw: str) -> str:
    token = str(raw or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token


def _build_codex_headers(config: dict, referer: str) -> dict:
    bearer = _normalize_bearer(str(config.get("sub2api_upload_bearer", "")))
    upload_cookie = str(config.get("sub2api_upload_cookie", "")).strip()
    user_agent = str(config.get("sub2api_upload_user_agent", "")).strip()

    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {bearer}",
        "Origin": "https://www.codex.hair",
        "Referer": referer,
    }
    if user_agent:
        headers["User-Agent"] = user_agent
    if upload_cookie:
        headers["Cookie"] = upload_cookie
    return headers


def _build_codex_kwargs(config: dict, referer: str, timeout: int = 60) -> dict[str, Any]:
    proxy = str(config.get("sub2api_upload_proxy", "")).strip()
    kwargs: dict[str, Any] = {
        "headers": _build_codex_headers(config, referer),
        "timeout": timeout,
        "impersonate": "chrome136",
    }
    if proxy:
        kwargs["proxies"] = {"http": proxy, "https": proxy}
    return kwargs


def _fetch_accounts_page(config: dict, page: int, page_size: int) -> tuple[bool, Union[dict, str]]:
    url = str(config.get("sub2api_upload_url", "")).replace("/data", "")
    if not url.endswith("/accounts"):
        url = "https://www.codex.hair/api/v1/admin/accounts"

    kwargs = _build_codex_kwargs(config, "https://www.codex.hair/admin/accounts", timeout=45)
    kwargs["params"] = {
        "page": page,
        "page_size": page_size,
        "platform": "",
        "type": "",
        "status": "",
        "group": "",
        "search": "",
        "timezone": "Asia/Shanghai",
    }
    try:
        resp = curl_requests.get(url, **kwargs)
    except Exception as e:
        return False, str(e)

    if resp.status_code != 200:
        return False, f"http {resp.status_code}: {(resp.text or '')[:200]}"
    try:
        data = resp.json()
    except Exception:
        return False, "invalid json"
    if not isinstance(data, dict) or data.get("code") != 0:
        return False, (resp.text or "")[:200]
    return True, data


def _bulk_bind_group(config: dict, account_ids: list[int], group_id: int) -> tuple[bool, str]:
    if not account_ids:
        return True, "no ids"
    url = "https://www.codex.hair/api/v1/admin/accounts/bulk-update"
    kwargs = _build_codex_kwargs(config, "https://www.codex.hair/admin/accounts", timeout=60)
    kwargs["json"] = {"account_ids": account_ids, "group_ids": [group_id]}
    try:
        resp = curl_requests.post(url, **kwargs)
    except Exception as e:
        return False, str(e)
    if resp.status_code != 200:
        return False, f"http {resp.status_code}: {(resp.text or '')[:200]}"
    return True, "ok"


def _bind_new_uploaded_accounts(config: dict, before_ids: set[int], expected_count: int) -> tuple[bool, str]:
    if not bool(config.get("sub2api_auto_group_bind", True)):
        return True, "group bind disabled"

    group_id = int(config.get("sub2api_group_id", 2) or 2)
    if group_id <= 0:
        return False, "invalid sub2api_group_id"

    need = max(50, min(1000, expected_count * 3 if expected_count > 0 else 100))
    page = 1
    max_pages = 10
    new_items: list[dict] = []

    while page <= max_pages:
        ok, data_or_err = _fetch_accounts_page(config, page=page, page_size=need)
        if not ok:
            return False, f"fetch accounts failed: {data_or_err}"
        data = data_or_err if isinstance(data_or_err, dict) else {}
        items = (((data.get("data") or {}).get("items")) or []) if isinstance(data, dict) else []
        if not isinstance(items, list) or not items:
            break

        for item in items:
            if not isinstance(item, dict):
                continue
            aid = item.get("id")
            if isinstance(aid, int) and aid not in before_ids:
                new_items.append(item)

        if expected_count > 0 and len(new_items) >= expected_count:
            break
        page += 1

    if not new_items:
        return True, "no new ids detected"

    missing_ids: list[int] = []
    seen: set[int] = set()
    for item in new_items:
        aid = item.get("id")
        if not isinstance(aid, int) or aid in seen:
            continue
        seen.add(aid)
        group_ids = item.get("group_ids")
        if isinstance(group_ids, list) and group_id in group_ids:
            continue
        missing_ids.append(aid)

    if not missing_ids:
        return True, f"group {group_id} already bound"

    ok, detail = _bulk_bind_group(config, missing_ids, group_id)
    if not ok:
        return False, f"bulk bind failed: {detail}"
    return True, f"group {group_id} bound for {len(missing_ids)} accounts"


def _upload_sub2api_data(config: dict, data: dict) -> tuple[bool, str]:
    if not bool(config.get("sub2api_auto_upload", True)):
        return False, "auto upload disabled"

    upload_url = str(config.get("sub2api_upload_url", "")).strip()
    bearer = _normalize_bearer(str(config.get("sub2api_upload_bearer", "")))
    upload_cookie = str(config.get("sub2api_upload_cookie", "")).strip()
    if not upload_url:
        return False, "upload url not configured"
    if not bearer:
        return False, "upload bearer token not configured"

    body = {
        "data": data,
        "skip_default_group_bind": bool(config.get("sub2api_skip_default_group_bind", True)),
    }
    kwargs = _build_codex_kwargs(config, "https://www.codex.hair/admin/accounts", timeout=60)
    kwargs["json"] = body

    try:
        resp = curl_requests.post(upload_url, **kwargs)
    except Exception as e:
        return False, str(e)

    if 200 <= resp.status_code < 300:
        return True, f"http {resp.status_code}"

    detail = (resp.text or "")[:300]
    if resp.status_code == 403 and not upload_cookie:
        return False, f"http 403: Cloudflare blocked. Set sub2api_upload_cookie (cf_clearance=...) in config. resp={detail}"
    return False, f"http {resp.status_code}: {detail}"


# ==================== History / Accounts Helpers ====================

def _scan_history() -> list[dict]:
    runs = []
    for root in _result_roots():
        if not root.exists() or not root.is_dir():
            continue
        for d in sorted(root.iterdir(), reverse=True):
            if not d.is_dir() or not re.match(r"\d{8}_\d{6}", d.name):
                continue
            info: dict[str, Any] = {"run_id": d.name, "path": str(d), "source": str(root)}
            try:
                ts = datetime.strptime(d.name[:15], "%Y%m%d_%H%M%S")
                info["timestamp"] = ts.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                info["timestamp"] = d.name

            reg_file = d / "registered_accounts.txt"
            total = 0
            success = 0
            if reg_file.exists():
                for line in reg_file.read_text("utf-8").splitlines():
                    if line.strip():
                        total += 1
                        if "oauth=ok" in line:
                            success += 1
            info["total_accounts"] = total
            info["success_count"] = success
            info["fail_count"] = total - success
            runs.append(info)
    runs.sort(key=lambda x: str(x.get("timestamp", "")), reverse=True)
    return runs


def _parse_accounts(run_id: Optional[str] = None) -> list[dict]:
    reg_file: Optional[Path] = None
    if run_id:
        for root in _result_roots():
            candidate = root / run_id / "registered_accounts.txt"
            if candidate.exists():
                reg_file = candidate
                break
    else:
        # Find latest
        history = _scan_history()
        if not history:
            return []
        reg_file = Path(history[0]["path"]) / "registered_accounts.txt"

    if not reg_file or not reg_file.exists():
        return []

    accounts = []
    for line in reg_file.read_text("utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("----")
        acc = {
            "email": parts[0] if len(parts) > 0 else "",
            "password": parts[1] if len(parts) > 1 else "",
            "email_password": "",
            "oauth_status": "",
        }
        extra_parts = []
        if len(parts) > 2:
            third = parts[2]
            if "=" not in third:
                acc["email_password"] = third
                extra_parts = parts[3:]
            else:
                extra_parts = parts[2:]

        for p in extra_parts:
            if p.startswith("oauth="):
                acc["oauth_status"] = p[6:]
            elif p.startswith("mail_token="):
                acc["mail_token"] = p[11:]
            if p.startswith("access_token="):
                acc["access_token"] = p[13:]
            elif p.startswith("refresh_token="):
                acc["refresh_token"] = p[14:]
            elif p.startswith("id_token="):
                acc["id_token"] = p[9:]
        accounts.append(acc)
    return accounts


def _query_mailbox_code(mail_token: str, timeout: int = 15) -> dict:
    try:
        result = getmail_lookup_mailbox(mail_token, timeout=timeout, limit=10)
    except ValueError as e:
        raise HTTPException(400, f"mail_token 无效: {e}") from e
    return {
        "status": result.get("status"),
        "email": result.get("email"),
        "verification_code": result.get("verification_code"),
        "subject": result.get("latest_subject"),
        "message_id": result.get("latest_message_id"),
        "received_at": result.get("latest_received_at"),
        "message": result.get("message"),
        "hint": result.get("hint"),
    }


def _get_stats() -> dict:
    history = _scan_history()
    total_accounts = sum(r["total_accounts"] for r in history)
    total_success = sum(r["success_count"] for r in history)
    total_fail = sum(r["fail_count"] for r in history)
    success_rate = round(total_success / total_accounts * 100, 1) if total_accounts else 0

    # Daily breakdown
    daily = {}
    for r in history:
        day = r["timestamp"][:10] if "timestamp" in r else r["run_id"][:8]
        if day not in daily:
            daily[day] = {"date": day, "success": 0, "fail": 0}
        daily[day]["success"] += r["success_count"]
        daily[day]["fail"] += r["fail_count"]

    return {
        "total_accounts": total_accounts,
        "total_success": total_success,
        "total_fail": total_fail,
        "success_rate": success_rate,
        "total_runs": len(history),
        "daily": sorted(daily.values(), key=lambda x: x["date"]),
    }


# ==================== FastAPI App ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    task_manager.set_loop(asyncio.get_event_loop())
    yield

app = FastAPI(title="ChatGPT 批量注册工具", lifespan=lifespan)


# --- Config ---

@app.get("/api/config")
async def get_config():
    return _load_config()


@app.put("/api/config")
async def update_config(config: ConfigModel):
    data = config.model_dump()
    _save_config(data)
    return {"status": "ok"}


# --- Tasks ---

@app.post("/api/tasks/start")
async def start_task(req: Optional[StartTaskRequest] = None):
    config = _load_config()
    total = req.total_accounts if req and req.total_accounts is not None else config.get("total_accounts", 3)
    workers = req.max_workers if req and req.max_workers is not None else config.get("max_workers", 3)
    proxy = req.proxy if req and req.proxy is not None else config.get("proxy", "")
    use_containers = config.get("use_containers", False)
    if req and req.use_containers is not None:
        use_containers = req.use_containers
    container_count = req.container_count if req and req.container_count is not None else config.get("container_count", 1)
    try:
        task_manager.start_batch(
            total,
            workers,
            proxy,
            use_containers=bool(use_containers),
            container_count=int(container_count or 1),
            config=config,
        )
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    return {
        "status": "started",
        "task_id": task_manager.task_id,
        "mode": task_manager.mode,
        "container_count": task_manager.container_target,
    }


@app.post("/api/tasks/stop")
async def stop_task():
    try:
        task_manager.stop_batch()
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    return {"status": "stopping"}


@app.get("/api/tasks/status")
async def get_task_status():
    return task_manager.get_status()


# --- History ---

@app.get("/api/tasks/history")
async def get_history():
    return _scan_history()


# --- Accounts ---

@app.get("/api/accounts")
async def list_accounts(run_id: Optional[str] = None):
    return _parse_accounts(run_id)


@app.post("/api/mailbox/code")
def query_mailbox_code(req: MailboxCodeQueryRequest):
    return _query_mailbox_code(req.mail_token, req.timeout)


@app.get("/api/accounts/{run_id}/download/{file_type}")
async def download_file(run_id: str, file_type: str):
    allowed = {"ak": "ak.txt", "rk": "rk.txt", "sub2api": "sub2api_accounts.json", "accounts": "registered_accounts.txt"}
    if file_type not in allowed:
        raise HTTPException(400, f"不支持的文件类型: {file_type}")
    fp = BASE_DIR / RESULTS_DIR_NAME / run_id / allowed[file_type]
    if not fp.exists():
        raise HTTPException(404, "文件不存在")
    return FileResponse(fp, filename=allowed[file_type])


# --- Stats ---

@app.get("/api/stats")
async def get_stats():
    return _get_stats()


# --- Sub2API Convert ---

@app.post("/api/convert")
async def convert_to_sub2api(req: ConvertRequest):
    config = _load_config()

    # Determine base directory (specific run or project root)
    if req.run_id:
        located = _locate_run_dir(req.run_id)
        if not located:
            raise HTTPException(404, f"批次目录不存在: {req.run_id}")
        work_dir = located
    else:
        work_dir = _resolve_default_convert_dir(config, req.source)

    accounts = _collect_sub2api_accounts(work_dir, req.source, config)

    # Apply per-account overrides from request
    for acc in accounts:
        acc["concurrency"] = req.concurrency
        acc["priority"] = req.priority
        acc["rate_multiplier"] = req.rate_multiplier
        acc["auto_pause_on_expired"] = req.auto_pause_on_expired

    from datetime import timezone as tz
    output = {
        "exported_at": datetime.now(tz.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "proxies": [],
        "accounts": accounts,
    }

    output_path = work_dir / req.output_filename
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "status": "ok",
        "accounts_count": len(accounts),
        "output_path": str(output_path),
    }


@app.post("/api/upload/backfill")
async def upload_backfill_accounts():
    config = _load_config()

    all_accounts: list[dict] = []
    seen_paths: set[str] = set()

    latest_dir = _resolve_default_convert_dir(config, "auto")
    if latest_dir.exists() and latest_dir.is_dir():
        key = str(latest_dir.resolve())
        if key not in seen_paths:
            seen_paths.add(key)
            all_accounts.extend(_collect_sub2api_accounts(latest_dir, "auto", config))

    for item in _scan_history():
        p = Path(str(item.get("path", "")))
        if not p.exists() or not p.is_dir():
            continue
        key = str(p.resolve())
        if key in seen_paths:
            continue
        seen_paths.add(key)
        all_accounts.extend(_collect_sub2api_accounts(p, "auto", config))

    uploaded = _load_uploaded_token_fingerprints()
    pending_accounts, skipped_uploaded, skipped_duplicate = _pick_pending_accounts(all_accounts, uploaded)

    if not pending_accounts:
        return {
            "status": "ok",
            "message": "没有可补传账号（已上传或重复）",
            "scanned": len(all_accounts),
            "uploaded_now": 0,
            "skipped_uploaded": skipped_uploaded,
            "skipped_duplicate": skipped_duplicate,
        }

    from datetime import timezone as tz
    payload_data = {
        "exported_at": datetime.now(tz.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "proxies": [],
        "accounts": pending_accounts,
    }

    before_ok, before_data = _fetch_accounts_page(config, page=1, page_size=max(200, min(1000, len(pending_accounts) * 3)))
    before_ids: set[int] = set()
    if before_ok and isinstance(before_data, dict):
        items = (((before_data.get("data") or {}).get("items")) or [])
        if isinstance(items, list):
            before_ids = {x["id"] for x in items if isinstance(x, dict) and isinstance(x.get("id"), int)}

    ok, detail = _upload_sub2api_data(config, payload_data)
    if not ok:
        raise HTTPException(500, f"补传失败: {detail}")

    added = _mark_uploaded_accounts(pending_accounts)
    bind_ok, bind_detail = _bind_new_uploaded_accounts(config, before_ids, len(pending_accounts))
    return {
        "status": "ok",
        "message": f"补传成功: {len(pending_accounts)}",
        "scanned": len(all_accounts),
        "uploaded_now": len(pending_accounts),
        "tracked_added": added,
        "group_bind": bind_detail,
        "group_bind_ok": bind_ok,
        "skipped_uploaded": skipped_uploaded,
        "skipped_duplicate": skipped_duplicate,
    }


@app.get("/api/convert/runs")
async def list_convertible_runs():
    """List runs that have convertible token data."""
    runs = []
    # Check project root
    config = _load_config()
    root_sources = _detect_convert_sources(BASE_DIR, config)
    if root_sources:
        runs.append({"run_id": "", "label": "项目根目录", "sources": root_sources})

    # Check all result roots, dedupe by run_id
    by_run: dict[str, dict[str, Any]] = {}
    for results_dir in _result_roots():
        if not results_dir.exists() or not results_dir.is_dir():
            continue
        for d in sorted(results_dir.iterdir(), reverse=True):
            if not d.is_dir() or not re.match(r"\d{8}_\d{6}", d.name):
                continue
            sources = _detect_convert_sources(d, config)
            if not sources:
                continue

            try:
                ts = datetime.strptime(d.name[:15], "%Y%m%d_%H%M%S")
                label = ts.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                label = d.name

            if d.name not in by_run:
                by_run[d.name] = {
                    "run_id": d.name,
                    "label": label,
                    "sources": list(sources),
                }
            else:
                merged = set(by_run[d.name].get("sources", []))
                merged.update(sources)
                by_run[d.name]["sources"] = sorted(merged)

    runs.extend(sorted(by_run.values(), key=lambda x: x.get("run_id", ""), reverse=True))
    return runs


# --- WebSocket Logs ---

@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    await websocket.accept()
    queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
    task_manager.log_subscribers.append(queue)

    # Send buffered logs
    try:
        for entry in list(task_manager.log_buffer):
            await websocket.send_json(entry)
    except Exception:
        pass

    try:
        while True:
            entry = await queue.get()
            await websocket.send_json(entry)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if queue in task_manager.log_subscribers:
            task_manager.log_subscribers.remove(queue)


@app.websocket("/ws/container-logs")
async def websocket_container_logs(websocket: WebSocket, service: str = "worker", container: str = "", tail: int = 0):
    await websocket.accept()
    config = _load_config()

    project_dir, compose_file = _resolve_compose_paths(config)
    if not Path(compose_file).exists():
        await websocket.send_json({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "level": "error",
            "tag": "docker",
            "message": f"compose 文件不存在: {compose_file}",
        })
        await websocket.close()
        return

    if container.strip():
        command = [
            "docker", "logs", "-f", "--tail", str(max(0, min(tail, 5000))), container.strip(),
        ]
    else:
        command = [
            "docker", "compose",
            "--project-directory", project_dir,
            "-f", compose_file,
            "logs", "-f", "--tail", str(max(0, min(tail, 5000))), "--no-color", service,
        ]

    proc = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    try:
        while True:
            if proc.stdout is None:
                break
            line = await proc.stdout.readline()
            if not line:
                break
            await websocket.send_json({
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "level": "info",
                "tag": container.strip() or service,
                "message": line.decode("utf-8", "replace").rstrip(),
            })
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "level": "error",
                "tag": "docker",
                "message": f"容器日志连接异常: {e}",
            })
        except Exception:
            pass
    finally:
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2)
            except Exception:
                proc.kill()


@app.get("/api/docker/containers")
async def list_docker_containers(service: str = "worker"):
    config = _load_config()
    project_dir, compose_file = _resolve_compose_paths(config)
    if not Path(compose_file).exists():
        raise HTTPException(404, f"compose 文件不存在: {compose_file}")

    command = [
        "docker", "compose",
        "--project-directory", project_dir,
        "-f", compose_file,
        "ps", "--format", "json",
    ]
    proc = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "docker compose ps failed").strip()
        raise HTTPException(500, msg)

    names: list[str] = []
    text = (proc.stdout or "").strip()
    if text:
        for line in text.splitlines():
            row = line.strip()
            if not row:
                continue
            try:
                item = json.loads(row)
            except Exception:
                continue
            if not isinstance(item, dict):
                continue
            if str(item.get("Service", "")) != service:
                continue
            state = str(item.get("State", "")).lower()
            if not state.startswith("running"):
                continue
            name = str(item.get("Name") or item.get("Names") or "").strip()
            if name:
                names.append(name)

    return sorted(names)


# --- Serve Frontend ---

frontend_dist = BASE_DIR / "frontend" / "dist"
frontend_assets = frontend_dist / "assets"
frontend_index = frontend_dist / "index.html"

def _frontend_placeholder() -> HTMLResponse:
    html = """
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>GPT 注册工具</title>
        <style>
            :root {
                color-scheme: light;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            }
            body {
                margin: 0;
                background: linear-gradient(135deg, #0f172a, #1e293b 55%, #334155);
                color: #e2e8f0;
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 24px;
            }
            main {
                width: min(720px, 100%);
                background: rgba(15, 23, 42, 0.9);
                border: 1px solid rgba(148, 163, 184, 0.25);
                border-radius: 16px;
                padding: 28px;
                box-shadow: 0 18px 50px rgba(15, 23, 42, 0.35);
            }
            h1 {
                margin: 0 0 12px;
                font-size: 28px;
            }
            p, li {
                line-height: 1.7;
                color: #cbd5e1;
            }
            code {
                background: rgba(148, 163, 184, 0.12);
                border-radius: 6px;
                padding: 2px 6px;
            }
            a {
                color: #7dd3fc;
            }
            ul {
                padding-left: 20px;
                margin: 12px 0 0;
            }
        </style>
    </head>
    <body>
        <main>
            <h1>前端尚未构建</h1>
            <p>后端服务已经启动，但当前目录下缺少 <code>frontend/dist/index.html</code>，所以仪表板页面无法直接显示。</p>
            <ul>
                <li>API 文档：<a href="/docs">/docs</a></li>
                <li>健康检查可直接访问现有接口，例如 <a href="/api/config">/api/config</a></li>
                <li>如需仪表板，请在 <code>frontend/</code> 下安装依赖并执行 <code>npm run build</code>，然后重启 <code>python3 main.py</code></li>
            </ul>
        </main>
    </body>
    </html>
    """
    return HTMLResponse(html)

@app.get("/", include_in_schema=False)
async def serve_root():
    if frontend_index.exists():
        return FileResponse(frontend_index)
    return _frontend_placeholder()


@app.get("/assets/{asset_path:path}", include_in_schema=False)
async def serve_frontend_assets(asset_path: str):
    file_path = frontend_assets / asset_path
    if file_path.exists() and file_path.is_file():
        return FileResponse(file_path)
    raise HTTPException(404, "Not Found")


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_spa(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(404, "Not Found")
    if full_path in {"docs", "redoc", "openapi.json"}:
        raise HTTPException(404, "Not Found")

    # Try to serve the exact file first
    file_path = frontend_dist / full_path
    if full_path and file_path.exists() and file_path.is_file():
        return FileResponse(file_path)
    if frontend_index.exists():
        return FileResponse(frontend_index)
    return _frontend_placeholder()


# ==================== Entry Point ====================

if __name__ == "__main__":
    import uvicorn
    port = 18000
    print("=" * 50)
    print(f"  ChatGPT 批量注册工具 - Dashboard")
    print(f"  http://localhost:{port}")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=port)
