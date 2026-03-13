from __future__ import annotations

"""
ChatGPT 批量自动注册工具 (并发版) - Resend 收件版
依赖: pip install curl_cffi
功能: 使用 Resend 接收入站邮件，并发自动注册 ChatGPT 账号，自动获取 OTP 验证码
"""

import os
import re
import uuid
import json
import importlib.util
import random
import string
import time
import sys
import threading
import traceback
import secrets
import hashlib
import base64
import hmac
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urlparse, parse_qs, urlencode

from curl_cffi import requests as curl_requests
from curl_cffi.requests import BrowserType
from sub2api_utils import build_account as build_sub2api_account, decode_jwt_payload

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MAILBOX_QUERY_TOKEN_SECRET_FILE = os.path.join(SCRIPT_DIR, ".mailbox_query_token_secret")
_mailbox_query_token_secret_cache = None
_mailbox_query_token_secret_lock = threading.Lock()

# ================= 加载配置 =================
def _load_config():
    """从 config.json 加载配置，环境变量优先级更高"""
    config = {
        "total_accounts": 3,
        "resend_api_base": "https://api.resend.com",
        "resend_api_key": "",
        "resend_domain": "",
        "proxy": "",
        "output_file": "registered_accounts.txt",
        "enable_oauth": True,
        "oauth_required": True,
        "oauth_issuer": "https://auth.openai.com",
        "oauth_client_id": "app_EMoamEEZ73f0CkXaXp7hrann",
        "oauth_redirect_uri": "http://localhost:1455/auth/callback",
        "ak_file": "ak.txt",
        "rk_file": "rk.txt",
        "token_json_dir": "codex_tokens",
        "results_dir": "results",
    }

    config_path = os.path.join(SCRIPT_DIR, "config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                file_config = json.load(f)
                config.update(file_config)
        except Exception as e:
            print(f"⚠️ 加载 config.json 失败: {e}")

    # 环境变量优先级更高
    config["resend_api_base"] = os.environ.get("RESEND_API_BASE", config["resend_api_base"])
    config["resend_api_key"] = os.environ.get("RESEND_API_KEY", config["resend_api_key"])
    config["resend_domain"] = os.environ.get("RESEND_DOMAIN", config["resend_domain"])
    config["proxy"] = os.environ.get("PROXY", config["proxy"])
    config["total_accounts"] = int(os.environ.get("TOTAL_ACCOUNTS", config["total_accounts"]))
    config["enable_oauth"] = os.environ.get("ENABLE_OAUTH", config["enable_oauth"])
    config["oauth_required"] = os.environ.get("OAUTH_REQUIRED", config["oauth_required"])
    config["oauth_issuer"] = os.environ.get("OAUTH_ISSUER", config["oauth_issuer"])
    config["oauth_client_id"] = os.environ.get("OAUTH_CLIENT_ID", config["oauth_client_id"])
    config["oauth_redirect_uri"] = os.environ.get("OAUTH_REDIRECT_URI", config["oauth_redirect_uri"])
    config["ak_file"] = os.environ.get("AK_FILE", config["ak_file"])
    config["rk_file"] = os.environ.get("RK_FILE", config["rk_file"])
    config["token_json_dir"] = os.environ.get("TOKEN_JSON_DIR", config["token_json_dir"])
    config["results_dir"] = os.environ.get("RESULTS_DIR", config["results_dir"])

    return config


def _as_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _normalize_resend_domain(value) -> str:
    text = str(value or "").strip().lower()
    if "@" in text:
        text = text.rsplit("@", 1)[-1].strip()
    return text


def _is_resend_managed_domain(domain: str) -> bool:
    return str(domain or "").strip().lower().endswith(".resend.app")


def _urlsafe_b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _urlsafe_b64decode(value: str) -> bytes:
    raw = str(value or "").strip().encode("ascii")
    if not raw:
        return b""
    return base64.urlsafe_b64decode(raw + (b"=" * (-len(raw) % 4)))


def _get_mailbox_query_token_secret() -> bytes:
    global _mailbox_query_token_secret_cache

    if _mailbox_query_token_secret_cache:
        return _mailbox_query_token_secret_cache

    env_secret = str(os.environ.get("MAILBOX_QUERY_TOKEN_SECRET", "")).strip()
    if env_secret:
        _mailbox_query_token_secret_cache = env_secret.encode("utf-8")
        return _mailbox_query_token_secret_cache

    with _mailbox_query_token_secret_lock:
        if _mailbox_query_token_secret_cache:
            return _mailbox_query_token_secret_cache

        secret = ""
        if os.path.exists(MAILBOX_QUERY_TOKEN_SECRET_FILE):
            try:
                with open(MAILBOX_QUERY_TOKEN_SECRET_FILE, "r", encoding="utf-8") as f:
                    secret = f.read().strip()
            except Exception:
                secret = ""

        if not secret:
            secret = secrets.token_urlsafe(48)
            try:
                with open(MAILBOX_QUERY_TOKEN_SECRET_FILE, "w", encoding="utf-8") as f:
                    f.write(secret)
            except Exception:
                pass

        _mailbox_query_token_secret_cache = secret.encode("utf-8")
        return _mailbox_query_token_secret_cache


def generate_mailbox_query_token(email: str, created_at: float) -> str:
    payload = {
        "v": 1,
        "email": str(email or "").strip().lower(),
        "created_at": round(float(created_at or time.time()), 3),
        "nonce": secrets.token_urlsafe(8),
    }
    payload_bytes = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = hmac.new(_get_mailbox_query_token_secret(), payload_bytes, hashlib.sha256).digest()
    return f"mbx_{_urlsafe_b64encode(payload_bytes)}.{_urlsafe_b64encode(signature)}"


def resolve_mailbox_query_token(token: str) -> dict:
    text = str(token or "").strip()
    if not text.startswith("mbx_"):
        raise ValueError("invalid mailbox query token format")

    try:
        payload_part, signature_part = text[4:].split(".", 1)
        payload_bytes = _urlsafe_b64decode(payload_part)
        signature = _urlsafe_b64decode(signature_part)
    except Exception as e:
        raise ValueError("invalid mailbox query token format") from e

    expected = hmac.new(_get_mailbox_query_token_secret(), payload_bytes, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        raise ValueError("invalid mailbox query token signature")

    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception as e:
        raise ValueError("invalid mailbox query token payload") from e

    email = str(payload.get("email") or "").strip().lower()
    created_at = float(payload.get("created_at") or 0.0)
    if not email:
        raise ValueError("invalid mailbox query token payload")

    return {
        "email": email,
        "created_at": created_at,
        "query_token": text,
    }


def extract_mailbox_query_token(mail_token) -> str:
    if isinstance(mail_token, dict):
        token = str(mail_token.get("query_token") or mail_token.get("mail_token") or "").strip()
        if token:
            return token

        email = str(mail_token.get("email") or "").strip().lower()
        created_at = float(mail_token.get("created_at") or 0.0) or time.time()
        if email:
            token = generate_mailbox_query_token(email, created_at)
            mail_token["query_token"] = token
            mail_token["created_at"] = created_at
            return token
        return ""

    text = str(mail_token or "").strip()
    if text.startswith("mbx_"):
        return text
    if "@" in text:
        return generate_mailbox_query_token(text, time.time())
    return ""


_CONFIG = _load_config()
RESEND_API_BASE = _CONFIG["resend_api_base"].rstrip("/")
RESEND_API_KEY = _CONFIG["resend_api_key"]
RESEND_DOMAIN = _normalize_resend_domain(_CONFIG.get("resend_domain", ""))
DEFAULT_TOTAL_ACCOUNTS = _CONFIG["total_accounts"]
DEFAULT_PROXY = _CONFIG["proxy"]
DEFAULT_OUTPUT_FILE = _CONFIG["output_file"]
ENABLE_OAUTH = _as_bool(_CONFIG.get("enable_oauth", True))
OAUTH_REQUIRED = _as_bool(_CONFIG.get("oauth_required", True))
OAUTH_ISSUER = _CONFIG["oauth_issuer"].rstrip("/")
OAUTH_CLIENT_ID = _CONFIG["oauth_client_id"]
OAUTH_REDIRECT_URI = _CONFIG["oauth_redirect_uri"]
AK_FILE = _CONFIG["ak_file"]
RK_FILE = _CONFIG["rk_file"]
TOKEN_JSON_DIR = _CONFIG["token_json_dir"]
RESULTS_DIR = _CONFIG["results_dir"]
RUN_OUTPUT_DIR = None

if not RESEND_API_KEY:
    print("⚠️ 警告: 未设置 RESEND_API_KEY，请在 config.json 中设置或设置环境变量")
    print("   文件: config.json -> resend_api_key")
    print("   环境变量: export RESEND_API_KEY='re_xxx'")
if not RESEND_DOMAIN:
    print("⚠️ 警告: 未设置 RESEND_DOMAIN，请在 config.json 中设置或设置环境变量")
    print("   文件: config.json -> resend_domain")
    print("   环境变量: export RESEND_DOMAIN='ilkoxpra.resend.app'")

# 全局线程锁
_print_lock = threading.Lock()
_file_lock = threading.Lock()
_mail_capability_lock = threading.Lock()
_resend_receiving_access_ok = False
_resend_receiving_access_error = ""
_test_module_cache = None
_test_module_lock = threading.Lock()

# 日志回调钩子 (供 FastAPI 层捕获日志)
_log_callback = None  # callable(level: str, tag: str, message: str) -> None


def set_log_callback(callback):
    global _log_callback
    _log_callback = callback


def _load_test_module():
    global _test_module_cache
    if _test_module_cache is not None:
        return _test_module_cache

    with _test_module_lock:
        if _test_module_cache is not None:
            return _test_module_cache

        module_path = os.path.join(SCRIPT_DIR, "test.py")
        spec = importlib.util.spec_from_file_location("gpt_py_test_module", module_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"无法加载 test.py: {module_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules["gpt_py_test_module"] = module
        spec.loader.exec_module(module)
        _test_module_cache = module
        return module


def _run_post_registration_flow(
    *,
    reg,
    email: str,
    password: str,
    proxy,
    mail_token,
    output_file: str,
    tag: str,
    tokens,
) -> dict:
    module = _load_test_module()
    runner = getattr(module, "run_registered_account_flow", None)
    if not callable(runner):
        raise RuntimeError("test.py 未提供 run_registered_account_flow")

    output_dir = RUN_OUTPUT_DIR or os.path.dirname(os.path.abspath(output_file))
    return runner(
        email=email,
        password=password,
        proxy=proxy,
        mail_token=mail_token,
        output_dir=output_dir,
        tag=tag,
        existing_reg=reg,
        existing_tokens=tokens if isinstance(tokens, dict) else None,
    )


def _ensure_resend_receiving_access(session_factory, impersonate: str = None):
    global _resend_receiving_access_ok, _resend_receiving_access_error
    if not impersonate:
        impersonate = _DEFAULT_IMPERSONATE

    with _mail_capability_lock:
        if _resend_receiving_access_ok:
            return
        if _resend_receiving_access_error:
            raise Exception(_resend_receiving_access_error)

        session = session_factory()
        try:
            resp = session.get(
                f"{RESEND_API_BASE}/emails/receiving",
                params={"limit": 1},
                timeout=20,
                impersonate=impersonate,
            )
        except Exception as e:
            raise Exception(f"Resend Receiving API 连接失败: {e}")

        if resp.status_code == 200:
            _resend_receiving_access_ok = True
            return

        detail = (resp.text or "")[:240]
        if resp.status_code == 401 and (
            "restricted_api_key" in detail or "only send emails" in detail
        ):
            _resend_receiving_access_error = (
                "当前 RESEND_API_KEY 仅支持发信，不支持 Receiving API。"
                "请在 Resend 后台创建具备读取入站邮件权限的 API Key。"
            )
            raise Exception(_resend_receiving_access_error)

        raise Exception(f"Resend Receiving API 校验失败: HTTP {resp.status_code} {detail}")


def reload_config(new_config: dict):
    """从字典重新加载配置到模块级全局变量"""
    global RESEND_API_BASE, RESEND_API_KEY, RESEND_DOMAIN, DEFAULT_TOTAL_ACCOUNTS
    global DEFAULT_PROXY, DEFAULT_OUTPUT_FILE, ENABLE_OAUTH, OAUTH_REQUIRED
    global OAUTH_ISSUER, OAUTH_CLIENT_ID, OAUTH_REDIRECT_URI
    global AK_FILE, RK_FILE, TOKEN_JSON_DIR, RESULTS_DIR, RUN_OUTPUT_DIR
    global _resend_receiving_access_ok, _resend_receiving_access_error

    RESEND_API_BASE = str(new_config.get("resend_api_base", RESEND_API_BASE) or RESEND_API_BASE).rstrip("/")
    RESEND_API_KEY = new_config.get("resend_api_key", RESEND_API_KEY)
    RESEND_DOMAIN = _normalize_resend_domain(new_config.get("resend_domain", RESEND_DOMAIN))
    DEFAULT_TOTAL_ACCOUNTS = int(new_config.get("total_accounts", DEFAULT_TOTAL_ACCOUNTS))
    DEFAULT_PROXY = new_config.get("proxy", DEFAULT_PROXY)
    DEFAULT_OUTPUT_FILE = new_config.get("output_file", DEFAULT_OUTPUT_FILE)
    ENABLE_OAUTH = _as_bool(new_config.get("enable_oauth", ENABLE_OAUTH))
    OAUTH_REQUIRED = _as_bool(new_config.get("oauth_required", OAUTH_REQUIRED))
    OAUTH_ISSUER = new_config.get("oauth_issuer", OAUTH_ISSUER).rstrip("/")
    OAUTH_CLIENT_ID = new_config.get("oauth_client_id", OAUTH_CLIENT_ID)
    OAUTH_REDIRECT_URI = new_config.get("oauth_redirect_uri", OAUTH_REDIRECT_URI)
    AK_FILE = new_config.get("ak_file", AK_FILE)
    RK_FILE = new_config.get("rk_file", RK_FILE)
    TOKEN_JSON_DIR = new_config.get("token_json_dir", TOKEN_JSON_DIR)
    RESULTS_DIR = new_config.get("results_dir", RESULTS_DIR)
    RUN_OUTPUT_DIR = None
    _resend_receiving_access_ok = False
    _resend_receiving_access_error = ""


# Chrome 指纹配置: impersonate 与 sec-ch-ua 必须匹配真实浏览器
_CHROME_PROFILES = [
    {
        "major": 131, "impersonate": "chrome131",
        "build": 6778, "patch_range": (69, 205),
        "sec_ch_ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    },
    {
        "major": 133, "impersonate": "chrome133a",
        "build": 6943, "patch_range": (33, 153),
        "sec_ch_ua": '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
    },
    {
        "major": 136, "impersonate": "chrome136",
        "build": 7103, "patch_range": (48, 175),
        "sec_ch_ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
    },
    {
        "major": 142, "impersonate": "chrome142",
        "build": 7540, "patch_range": (30, 150),
        "sec_ch_ua": '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
    },
]

_SUPPORTED_IMPERSONATES = {item.value for item in BrowserType}
_AVAILABLE_CHROME_PROFILES = [
    profile for profile in _CHROME_PROFILES
    if profile["impersonate"] in _SUPPORTED_IMPERSONATES
]
if not _AVAILABLE_CHROME_PROFILES:
    _AVAILABLE_CHROME_PROFILES = [profile for profile in _CHROME_PROFILES if profile["impersonate"] == "chrome131"] or _CHROME_PROFILES[:1]

# chatgpt.com 当前会对 chrome131 指纹直接返回 403，默认避开它。
_BLOCKED_OPENAI_IMPERSONATES = {"chrome131"}
_PREFERRED_CHROME_PROFILES = [
    profile for profile in _AVAILABLE_CHROME_PROFILES
    if profile["impersonate"] not in _BLOCKED_OPENAI_IMPERSONATES
]
if not _PREFERRED_CHROME_PROFILES:
    _PREFERRED_CHROME_PROFILES = list(_AVAILABLE_CHROME_PROFILES)
_PREFERRED_CHROME_PROFILES.sort(key=lambda item: item["major"], reverse=True)
_DEFAULT_IMPERSONATE = (_PREFERRED_CHROME_PROFILES or _AVAILABLE_CHROME_PROFILES or _CHROME_PROFILES)[0]["impersonate"]


def _pick_chrome_profile(exclude=None, allow_blocked=False):
    excluded = set(exclude or ())
    base_pool = _AVAILABLE_CHROME_PROFILES if allow_blocked else _PREFERRED_CHROME_PROFILES
    candidates = [profile for profile in base_pool if profile["impersonate"] not in excluded]
    if not candidates and not allow_blocked:
        candidates = [profile for profile in _AVAILABLE_CHROME_PROFILES if profile["impersonate"] not in excluded]
    if not candidates:
        candidates = list(base_pool) or list(_AVAILABLE_CHROME_PROFILES) or list(_CHROME_PROFILES)
    return random.choice(candidates)


def _random_chrome_version(exclude=None, allow_blocked=False):
    profile = _pick_chrome_profile(exclude=exclude, allow_blocked=allow_blocked)
    major = profile["major"]
    build = profile["build"]
    patch = random.randint(*profile["patch_range"])
    full_ver = f"{major}.0.{build}.{patch}"
    ua = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{full_ver} Safari/537.36"
    return profile["impersonate"], major, full_ver, ua, profile["sec_ch_ua"]


def _random_delay(low=0.3, high=1.0):
    time.sleep(random.uniform(low, high))


def _make_trace_headers():
    trace_id = random.randint(10**17, 10**18 - 1)
    parent_id = random.randint(10**17, 10**18 - 1)
    tp = f"00-{uuid.uuid4().hex}-{format(parent_id, '016x')}-01"
    return {
        "traceparent": tp, "tracestate": "dd=s:1;o:rum",
        "x-datadog-origin": "rum", "x-datadog-sampling-priority": "1",
        "x-datadog-trace-id": str(trace_id), "x-datadog-parent-id": str(parent_id),
    }


def _generate_pkce():
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


class SentinelTokenGenerator:
    """纯 Python 版本 sentinel token 生成器（PoW）"""

    MAX_ATTEMPTS = 500000
    ERROR_PREFIX = "wQ8Lk5FbGpA2NcR9dShT6gYjU7VxZ4D"

    def __init__(self, device_id=None, user_agent=None):
        self.device_id = device_id or str(uuid.uuid4())
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/145.0.0.0 Safari/537.36"
        )
        self.requirements_seed = str(random.random())
        self.sid = str(uuid.uuid4())

    @staticmethod
    def _fnv1a_32(text: str):
        h = 2166136261
        for ch in text:
            h ^= ord(ch)
            h = (h * 16777619) & 0xFFFFFFFF
        h ^= (h >> 16)
        h = (h * 2246822507) & 0xFFFFFFFF
        h ^= (h >> 13)
        h = (h * 3266489909) & 0xFFFFFFFF
        h ^= (h >> 16)
        h &= 0xFFFFFFFF
        return format(h, "08x")

    def _get_config(self):
        now_str = time.strftime(
            "%a %b %d %Y %H:%M:%S GMT+0000 (Coordinated Universal Time)",
            time.gmtime(),
        )
        perf_now = random.uniform(1000, 50000)
        time_origin = time.time() * 1000 - perf_now
        nav_prop = random.choice([
            "vendorSub", "productSub", "vendor", "maxTouchPoints",
            "scheduling", "userActivation", "doNotTrack", "geolocation",
            "connection", "plugins", "mimeTypes", "pdfViewerEnabled",
            "webkitTemporaryStorage", "webkitPersistentStorage",
            "hardwareConcurrency", "cookieEnabled", "credentials",
            "mediaDevices", "permissions", "locks", "ink",
        ])
        nav_val = f"{nav_prop}-undefined"

        return [
            "1920x1080",
            now_str,
            4294705152,
            random.random(),
            self.user_agent,
            "https://sentinel.openai.com/sentinel/20260124ceb8/sdk.js",
            None,
            None,
            "en-US",
            "en-US,en",
            random.random(),
            nav_val,
            random.choice(["location", "implementation", "URL", "documentURI", "compatMode"]),
            random.choice(["Object", "Function", "Array", "Number", "parseFloat", "undefined"]),
            perf_now,
            self.sid,
            "",
            random.choice([4, 8, 12, 16]),
            time_origin,
        ]

    @staticmethod
    def _base64_encode(data):
        raw = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return base64.b64encode(raw).decode("ascii")

    def _run_check(self, start_time, seed, difficulty, config, nonce):
        config[3] = nonce
        config[9] = round((time.time() - start_time) * 1000)
        data = self._base64_encode(config)
        hash_hex = self._fnv1a_32(seed + data)
        diff_len = len(difficulty)
        if hash_hex[:diff_len] <= difficulty:
            return data + "~S"
        return None

    def generate_token(self, seed=None, difficulty=None):
        seed = seed if seed is not None else self.requirements_seed
        difficulty = str(difficulty or "0")
        start_time = time.time()
        config = self._get_config()

        for i in range(self.MAX_ATTEMPTS):
            result = self._run_check(start_time, seed, difficulty, config, i)
            if result:
                return "gAAAAAB" + result
        return "gAAAAAB" + self.ERROR_PREFIX + self._base64_encode(str(None))

    def generate_requirements_token(self):
        config = self._get_config()
        config[3] = 1
        config[9] = round(random.uniform(5, 50))
        data = self._base64_encode(config)
        return "gAAAAAC" + data


def fetch_sentinel_challenge(session, device_id, flow="authorize_continue", user_agent=None,
                             sec_ch_ua=None, impersonate=None):
    generator = SentinelTokenGenerator(device_id=device_id, user_agent=user_agent)
    req_body = {
        "p": generator.generate_requirements_token(),
        "id": device_id,
        "flow": flow,
    }
    headers = {
        "Content-Type": "text/plain;charset=UTF-8",
        "Referer": "https://sentinel.openai.com/backend-api/sentinel/frame.html",
        "Origin": "https://sentinel.openai.com",
        "User-Agent": user_agent or "Mozilla/5.0",
        "sec-ch-ua": sec_ch_ua or '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }

    kwargs = {
        "data": json.dumps(req_body),
        "headers": headers,
        "timeout": 20,
    }
    if impersonate:
        kwargs["impersonate"] = impersonate

    try:
        resp = session.post("https://sentinel.openai.com/backend-api/sentinel/req", **kwargs)
    except Exception:
        return None

    if resp.status_code != 200:
        return None

    try:
        return resp.json()
    except Exception:
        return None


def build_sentinel_token(session, device_id, flow="authorize_continue", user_agent=None,
                         sec_ch_ua=None, impersonate=None):
    challenge = fetch_sentinel_challenge(
        session,
        device_id,
        flow=flow,
        user_agent=user_agent,
        sec_ch_ua=sec_ch_ua,
        impersonate=impersonate,
    )
    if not challenge:
        return None

    c_value = challenge.get("token", "")
    if not c_value:
        return None

    pow_data = challenge.get("proofofwork") or {}
    generator = SentinelTokenGenerator(device_id=device_id, user_agent=user_agent)

    if pow_data.get("required") and pow_data.get("seed"):
        p_value = generator.generate_token(
            seed=pow_data.get("seed"),
            difficulty=pow_data.get("difficulty", "0"),
        )
    else:
        p_value = generator.generate_requirements_token()

    return json.dumps({
        "p": p_value,
        "t": "",
        "c": c_value,
        "id": device_id,
        "flow": flow,
    }, separators=(",", ":"))


def _extract_code_from_url(url: str):
    if not url or "code=" not in url:
        return None
    try:
        return parse_qs(urlparse(url).query).get("code", [None])[0]
    except Exception:
        return None


def _save_codex_tokens(email: str, tokens: dict):
    access_token = tokens.get("access_token", "")
    refresh_token = tokens.get("refresh_token", "")
    id_token = tokens.get("id_token", "")

    if access_token:
        with _file_lock:
            ak_dir = os.path.dirname(os.path.abspath(AK_FILE))
            if ak_dir:
                os.makedirs(ak_dir, exist_ok=True)
            with open(AK_FILE, "a", encoding="utf-8") as f:
                f.write(f"{access_token}\n")

    if refresh_token:
        with _file_lock:
            rk_dir = os.path.dirname(os.path.abspath(RK_FILE))
            if rk_dir:
                os.makedirs(rk_dir, exist_ok=True)
            with open(RK_FILE, "a", encoding="utf-8") as f:
                f.write(f"{refresh_token}\n")

    if not access_token:
        return

    payload = decode_jwt_payload(access_token)
    auth_info = payload.get("https://api.openai.com/auth", {})
    account_id = auth_info.get("chatgpt_account_id", "")

    exp_timestamp = payload.get("exp")
    expired_str = ""
    if isinstance(exp_timestamp, int) and exp_timestamp > 0:
        from datetime import datetime, timezone, timedelta

        exp_dt = datetime.fromtimestamp(exp_timestamp, tz=timezone(timedelta(hours=8)))
        expired_str = exp_dt.strftime("%Y-%m-%dT%H:%M:%S+08:00")

    from datetime import datetime, timezone, timedelta

    now = datetime.now(tz=timezone(timedelta(hours=8)))
    token_data = {
        "type": "codex",
        "email": email,
        "expired": expired_str,
        "id_token": id_token,
        "account_id": account_id,
        "access_token": access_token,
        "last_refresh": now.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "refresh_token": refresh_token,
    }

    base_dir = os.path.dirname(os.path.abspath(__file__))
    token_dir = TOKEN_JSON_DIR if os.path.isabs(TOKEN_JSON_DIR) else os.path.join(base_dir, TOKEN_JSON_DIR)
    os.makedirs(token_dir, exist_ok=True)

    token_path = os.path.join(token_dir, f"{email}.json")
    with _file_lock:
        with open(token_path, "w", encoding="utf-8") as f:
            json.dump(token_data, f, ensure_ascii=False)

def _update_sub2api_json(access_token: str, refresh_token: str, id_token: str, email: str):
    if not access_token or not refresh_token:
        return

    if RUN_OUTPUT_DIR is None:
        _prepare_run_output_paths()

    output_path = os.path.join(_ensure_run_output_dir(), "sub2api_accounts.json")

    with _file_lock:
        if os.path.exists(output_path):
            try:
                output = json.loads(open(output_path, "r", encoding="utf-8").read())
            except Exception:
                output = {}
        else:
            output = {}

        accounts = output.get("accounts")
        if not isinstance(accounts, list):
            accounts = []

        exists = any(
            isinstance(item, dict)
            and (item.get("credentials") or {}).get("access_token") == access_token
            for item in accounts
        )
        if not exists:
            account = build_sub2api_account(
                idx=len(accounts) + 1,
                access_token=access_token,
                refresh_token=refresh_token,
                id_token=id_token,
                fallback_email=email,
            )
            accounts.append(account)

        from datetime import datetime, timezone

        output = {
            "exported_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "proxies": [],
            "accounts": accounts,
        }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)


def _ensure_run_output_dir():
    global RUN_OUTPUT_DIR
    if RUN_OUTPUT_DIR:
        return RUN_OUTPUT_DIR

    base_dir = os.path.dirname(os.path.abspath(__file__))
    results_base = RESULTS_DIR if os.path.isabs(RESULTS_DIR) else os.path.join(base_dir, RESULTS_DIR)
    os.makedirs(results_base, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    run_dir = os.path.join(results_base, timestamp)
    if os.path.exists(run_dir):
        for i in range(1, 1000):
            candidate = f"{run_dir}_{i}"
            if not os.path.exists(candidate):
                run_dir = candidate
                break

    os.makedirs(run_dir, exist_ok=True)
    RUN_OUTPUT_DIR = run_dir
    return RUN_OUTPUT_DIR


def _resolve_output_path(name: str, default_name: str) -> str:
    run_dir = _ensure_run_output_dir()
    base_name = os.path.basename(name) if name else default_name
    return os.path.join(run_dir, base_name)


def _prepare_run_output_paths():
    global DEFAULT_OUTPUT_FILE, AK_FILE, RK_FILE, TOKEN_JSON_DIR
    DEFAULT_OUTPUT_FILE = _resolve_output_path(DEFAULT_OUTPUT_FILE, "registered_accounts.txt")
    AK_FILE = _resolve_output_path(AK_FILE, "ak.txt")
    RK_FILE = _resolve_output_path(RK_FILE, "rk.txt")

    run_dir = _ensure_run_output_dir()
    token_dir_name = os.path.basename(TOKEN_JSON_DIR) if TOKEN_JSON_DIR else "codex_tokens"
    TOKEN_JSON_DIR = os.path.join(run_dir, token_dir_name)


def _generate_password(length=14):
    lower = string.ascii_lowercase
    upper = string.ascii_uppercase
    digits = string.digits
    special = "!@#$%&*"
    pwd = [random.choice(lower), random.choice(upper),
           random.choice(digits), random.choice(special)]
    all_chars = lower + upper + digits + special
    pwd += [random.choice(all_chars) for _ in range(length - 4)]
    random.shuffle(pwd)
    return "".join(pwd)


# ================= Resend 收件函数 =================

def _create_resend_session():
    """创建 Resend API 请求会话"""
    session = curl_requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {RESEND_API_KEY}",
    })
    return session


def _parse_resend_created_at(raw_value) -> float:
    text = str(raw_value or "").strip()
    if not text:
        return 0.0
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except Exception:
        return 0.0


def _normalize_mailbox_handle(mail_token) -> dict:
    if isinstance(mail_token, dict):
        email = str(mail_token.get("email", "")).strip().lower()
        created_at = float(mail_token.get("created_at") or 0.0)
        query_token = str(mail_token.get("query_token") or mail_token.get("mail_token") or "").strip()
        if query_token and (not email or not created_at):
            try:
                resolved = resolve_mailbox_query_token(query_token)
                email = email or resolved.get("email", "")
                created_at = created_at or float(resolved.get("created_at") or 0.0)
            except ValueError:
                pass
        return {"email": email, "created_at": created_at, "query_token": query_token}

    raw = str(mail_token or "").strip()
    if raw.startswith("mbx_"):
        resolved = resolve_mailbox_query_token(raw)
        return {
            "email": str(resolved.get("email") or "").strip().lower(),
            "created_at": float(resolved.get("created_at") or 0.0),
            "query_token": raw,
        }

    email = raw.lower()
    return {"email": email, "created_at": 0.0, "query_token": ""}


def _mailbox_debug_hint(mail_token) -> str:
    mailbox = _normalize_mailbox_handle(mail_token)
    email = mailbox.get("email") or "<unknown>"
    domain = _normalize_resend_domain(email.rsplit("@", 1)[-1] if "@" in email else RESEND_DOMAIN)
    if _is_resend_managed_domain(domain):
        return (
            f"Resend Receiving API 当前未看到发给 {email} 的入站邮件。"
            "这个地址属于 Resend 托管接收域，通常不需要你自己再配 MX。"
            "请确认验证码邮件确实发到了这个完整地址，并检查 Resend 后台该 receiving domain 是否可用。"
        )
    return (
        f"Resend Receiving API 当前未看到发给 {email} 的入站邮件。"
        "这通常说明邮件被你现有邮箱服务收到了，但没有进入 Resend。"
        "如果根域已经有自己的 MX，按 Resend 文档更推荐使用子域做收件，"
        "或者在现有邮箱服务里把该地址/catch-all 转发到 Resend。"
    )


def _extract_message_content(detail: dict) -> str:
    parts = [
        detail.get("text"),
        detail.get("html"),
        detail.get("raw"),
        detail.get("content"),
    ]
    for key in ("headers", "attachments"):
        value = detail.get(key)
        if value:
            parts.append(json.dumps(value, ensure_ascii=False))
    return "\n".join(str(part) for part in parts if part)


def _message_targets_mailbox(message: dict, mailbox_email: str) -> bool:
    recipients = message.get("to") or []
    if isinstance(recipients, str):
        recipients = [recipients]
    for item in recipients:
        if isinstance(item, str) and item.strip().lower() == mailbox_email:
            return True
        if isinstance(item, dict):
            addr = str(item.get("email") or item.get("address") or "").strip().lower()
            if addr == mailbox_email:
                return True
    return False


def create_temp_email():
    """创建 Resend 域名下的随机邮箱地址，返回 (email, password, mail_token)"""
    if not RESEND_API_KEY:
        raise Exception("RESEND_API_KEY 未设置，无法接收临时邮箱邮件")
    if not RESEND_DOMAIN:
        raise Exception("RESEND_DOMAIN 未设置，无法生成接收邮箱地址")
    _ensure_resend_receiving_access(_create_resend_session, _DEFAULT_IMPERSONATE)

    chars = string.ascii_lowercase + string.digits
    local_length = random.randint(10, 16)
    email_local = "".join(random.choice(chars) for _ in range(local_length))
    email = f"{email_local}@{RESEND_DOMAIN}"
    created_at = time.time()
    mail_token = {
        "email": email,
        "created_at": created_at,
        "query_token": generate_mailbox_query_token(email, created_at),
    }
    return email, "", mail_token


def _fetch_received_emails(mail_token):
    """从 Resend 接收 API 拉取指定邮箱的入站邮件列表"""
    mailbox = _normalize_mailbox_handle(mail_token)
    mailbox_email = mailbox["email"]
    if not mailbox_email:
        return []

    try:
        session = _create_resend_session()
        res = session.get(
            f"{RESEND_API_BASE}/emails/receiving",
            params={"limit": 100},
            timeout=20,
            impersonate=_DEFAULT_IMPERSONATE,
        )
        if res.status_code != 200:
            return []

        data = res.json()
        messages = data.get("data") if isinstance(data, dict) else []
        if not isinstance(messages, list):
            return []

        created_floor = max(0.0, mailbox["created_at"] - 30)
        filtered = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            if not _message_targets_mailbox(message, mailbox_email):
                continue
            created_at = _parse_resend_created_at(message.get("created_at"))
            if created_at and created_at < created_floor:
                continue
            filtered.append(message)

        filtered.sort(key=lambda item: _parse_resend_created_at(item.get("created_at")), reverse=True)
        return filtered
    except Exception:
        return []


def _fetch_email_detail(mail_token, msg_id: str):
    """获取 Resend 单封入站邮件详情"""
    if not msg_id:
        return None

    try:
        session = _create_resend_session()
        res = session.get(
            f"{RESEND_API_BASE}/emails/receiving/{msg_id}",
            timeout=20,
            impersonate=_DEFAULT_IMPERSONATE,
        )
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, dict) and isinstance(data.get("data"), dict):
                return data["data"]
            return data if isinstance(data, dict) else None
    except Exception:
        pass
    return None


def _extract_verification_code(email_content: str):
    """从邮件内容提取 6 位验证码"""
    if not email_content:
        return None

    patterns = [
        r"Verification code:?\s*(\d{6})",
        r"code is\s*(\d{6})",
        r"代码为[:：]?\s*(\d{6})",
        r"验证码[:：]?\s*(\d{6})",
        r">\s*(\d{6})\s*<",
        r"(?<![#&])\b(\d{6})\b",
    ]

    for pattern in patterns:
        matches = re.findall(pattern, email_content, re.IGNORECASE)
        for code in matches:
            if code == "177010":  # 已知误判
                continue
            return code
    return None


def wait_for_verification_email(mail_token: str, timeout: int = 120):
    """等待并提取 OpenAI 验证码"""
    start_time = time.time()
    ever_seen_message = False

    while time.time() - start_time < timeout:
        messages = _fetch_received_emails(mail_token)
        if messages and len(messages) > 0:
            ever_seen_message = True
            first_msg = messages[0]
            msg_id = first_msg.get("id")

            if msg_id:
                detail = _fetch_email_detail(mail_token, msg_id)
                if detail:
                    content = _extract_message_content(detail)
                    code = _extract_verification_code(content)
                    if code:
                        return code

        time.sleep(3)

    if not ever_seen_message:
        print(f"[OTP] {_mailbox_debug_hint(mail_token)}")
    return None


def _random_name():
    first = random.choice([
        "James", "Emma", "Liam", "Olivia", "Noah", "Ava", "Ethan", "Sophia",
        "Lucas", "Mia", "Mason", "Isabella", "Logan", "Charlotte", "Alexander",
        "Amelia", "Benjamin", "Harper", "William", "Evelyn", "Henry", "Abigail",
        "Sebastian", "Emily", "Jack", "Elizabeth",
    ])
    last = random.choice([
        "Smith", "Johnson", "Brown", "Davis", "Wilson", "Moore", "Taylor",
        "Clark", "Hall", "Young", "Anderson", "Thomas", "Jackson", "White",
        "Harris", "Martin", "Thompson", "Garcia", "Robinson", "Lewis",
        "Walker", "Allen", "King", "Wright", "Scott", "Green",
    ])
    return f"{first} {last}"


def _random_birthdate():
    y = random.randint(1985, 2002)
    m = random.randint(1, 12)
    d = random.randint(1, 28)
    return f"{y}-{m:02d}-{d:02d}"


class OpenAIBrowserBlockedError(Exception):
    """当前浏览器指纹被 OpenAI/ChatGPT 风控拦截。"""


class ChatGPTRegister:
    BASE = "https://chatgpt.com"
    AUTH = "https://auth.openai.com"

    def __init__(self, proxy: str = None, tag: str = ""):
        self.tag = tag  # 线程标识，用于日志
        self.device_id = str(uuid.uuid4())
        self.auth_session_logging_id = str(uuid.uuid4())
        self.proxy = proxy
        self._callback_url = None
        self._set_browser_profile()

    def _build_session(self):
        session = curl_requests.Session(impersonate=self.impersonate)
        if self.proxy:
            session.proxies = {"http": self.proxy, "https": self.proxy}

        session.headers.update({
            "User-Agent": self.ua,
            "Accept-Language": random.choice([
                "en-US,en;q=0.9", "en-US,en;q=0.9,zh-CN;q=0.8",
                "en,en-US;q=0.9", "en-US,en;q=0.8",
            ]),
            "sec-ch-ua": self.sec_ch_ua, "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"', "sec-ch-ua-arch": '"x86"',
            "sec-ch-ua-bitness": '"64"',
            "sec-ch-ua-full-version": f'"{self.chrome_full}"',
            "sec-ch-ua-platform-version": f'"{random.randint(10, 15)}.0.0"',
        })
        session.cookies.set("oai-did", self.device_id, domain="chatgpt.com")
        return session

    def _set_browser_profile(self, exclude=None, allow_blocked=False, reason: str = ""):
        previous = getattr(self, "impersonate", "")
        self.impersonate, self.chrome_major, self.chrome_full, self.ua, self.sec_ch_ua = _random_chrome_version(
            exclude=exclude,
            allow_blocked=allow_blocked,
        )
        self.session = self._build_session()
        if reason:
            prev_label = previous or "-"
            self._print(f"[warn] {reason}，切换浏览器指纹 {prev_label} -> {self.impersonate} ({self.chrome_full})")

    def _rotate_browser_profile(self, reason: str = "") -> bool:
        current = getattr(self, "impersonate", "")
        candidates = [
            profile for profile in _PREFERRED_CHROME_PROFILES
            if profile["impersonate"] != current
        ]
        if not candidates:
            candidates = [
                profile for profile in _AVAILABLE_CHROME_PROFILES
                if profile["impersonate"] != current
            ]
        if not candidates:
            return False
        self._set_browser_profile(exclude={current}, reason=reason)
        return True

    def _log(self, step, method, url, status, body=None):
        prefix = f"[{self.tag}] " if self.tag else ""
        lines = [
            f"\n{'='*60}",
            f"{prefix}[Step] {step}",
            f"{prefix}[{method}] {url}",
            f"{prefix}[Status] {status}",
        ]
        if body:
            try:
                lines.append(f"{prefix}[Response] {json.dumps(body, indent=2, ensure_ascii=False)[:1000]}")
            except Exception:
                lines.append(f"{prefix}[Response] {str(body)[:1000]}")
        lines.append(f"{'='*60}")
        with _print_lock:
            print("\n".join(lines))
        if _log_callback:
            try:
                _log_callback("info", self.tag or "", f"[{step}] {method} {url} -> {status}")
            except Exception:
                pass

    def _print(self, msg):
        prefix = f"[{self.tag}] " if self.tag else ""
        with _print_lock:
            print(f"{prefix}{msg}")
        if _log_callback:
            try:
                _log_callback("info", self.tag or "", msg)
            except Exception:
                pass

    def _json_or_none(self, resp):
        try:
            return resp.json()
        except Exception:
            return None

    # ==================== Resend 收件 ====================

    def _create_mail_session(self):
        """创建 Resend API 请求会话"""
        session = curl_requests.Session()
        session.headers.update({
            "User-Agent": self.ua,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {RESEND_API_KEY}",
        })
        if self.proxy:
            session.proxies = {"http": self.proxy, "https": self.proxy}
        return session

    def create_temp_email(self):
        """创建 Resend 域名下的随机邮箱地址，返回 (email, password, mail_token)"""
        if not RESEND_API_KEY:
            raise Exception("RESEND_API_KEY 未设置，无法接收入站邮件")
        if not RESEND_DOMAIN:
            raise Exception("RESEND_DOMAIN 未设置，无法生成接收邮箱地址")
        _ensure_resend_receiving_access(self._create_mail_session, self.impersonate)

        chars = string.ascii_lowercase + string.digits
        length = random.randint(10, 16)
        email_local = "".join(random.choice(chars) for _ in range(length))
        email = f"{email_local}@{RESEND_DOMAIN}"
        created_at = time.time()
        return email, "", {
            "email": email,
            "created_at": created_at,
            "query_token": generate_mailbox_query_token(email, created_at),
        }

    def _fetch_received_emails(self, mail_token):
        """从 Resend 获取指定邮箱收到的邮件列表"""
        mailbox = _normalize_mailbox_handle(mail_token)
        mailbox_email = mailbox["email"]
        if not mailbox_email:
            return []

        try:
            session = self._create_mail_session()
            res = session.get(
                f"{RESEND_API_BASE}/emails/receiving",
                params={"limit": 100},
                timeout=20,
                impersonate=self.impersonate,
            )

            if res.status_code != 200:
                return []

            data = res.json()
            messages = data.get("data") if isinstance(data, dict) else []
            if not isinstance(messages, list):
                return []

            created_floor = max(0.0, mailbox["created_at"] - 30)
            filtered = []
            for message in messages:
                if not isinstance(message, dict):
                    continue
                if not _message_targets_mailbox(message, mailbox_email):
                    continue
                created_at = _parse_resend_created_at(message.get("created_at"))
                if created_at and created_at < created_floor:
                    continue
                filtered.append(message)

            filtered.sort(key=lambda item: _parse_resend_created_at(item.get("created_at")), reverse=True)
            return filtered
        except Exception:
            return []

    def _fetch_email_detail(self, mail_token, msg_id: str):
        """获取 Resend 单封入站邮件详情"""
        if not msg_id:
            return None

        try:
            session = self._create_mail_session()
            res = session.get(
                f"{RESEND_API_BASE}/emails/receiving/{msg_id}",
                timeout=20,
                impersonate=self.impersonate,
            )

            if res.status_code == 200:
                data = res.json()
                if isinstance(data, dict) and isinstance(data.get("data"), dict):
                    return data["data"]
                return data if isinstance(data, dict) else None
        except Exception:
            pass
        return None

    def _extract_verification_code(self, email_content: str):
        """从邮件内容提取 6 位验证码"""
        if not email_content:
            return None

        patterns = [
            r"Verification code:?\s*(\d{6})",
            r"code is\s*(\d{6})",
            r"代码为[:：]?\s*(\d{6})",
            r"验证码[:：]?\s*(\d{6})",
            r">\s*(\d{6})\s*<",
            r"(?<![#&])\b(\d{6})\b",
        ]

        for pattern in patterns:
            matches = re.findall(pattern, email_content, re.IGNORECASE)
            for code in matches:
                if code == "177010":  # 已知误判
                    continue
                return code
        return None

    def wait_for_verification_email(self, mail_token: str, timeout: int = 120):
        """等待并提取 OpenAI 验证码"""
        self._print(f"[OTP] 等待验证码邮件 (最多 {timeout}s)...")
        start_time = time.time()
        ever_seen_message = False
        hint_logged = False

        while time.time() - start_time < timeout:
            messages = self._fetch_received_emails(mail_token)
            if messages and len(messages) > 0:
                ever_seen_message = True
                first_msg = messages[0]
                msg_id = first_msg.get("id")

                if msg_id:
                    detail = self._fetch_email_detail(mail_token, msg_id)
                    if detail:
                        content = _extract_message_content(detail)
                        code = self._extract_verification_code(content)
                        if code:
                            self._print(f"[OTP] 验证码: {code}")
                            return code
            elif not hint_logged and time.time() - start_time >= 15:
                self._print(f"[OTP] {_mailbox_debug_hint(mail_token)}")
                hint_logged = True

            elapsed = int(time.time() - start_time)
            self._print(f"[OTP] 等待中... ({elapsed}s/{timeout}s)")
            time.sleep(3)

        if not ever_seen_message and not hint_logged:
            self._print(f"[OTP] {_mailbox_debug_hint(mail_token)}")
        self._print(f"[OTP] 超时 ({timeout}s)")
        return None

    # ==================== 注册流程 ====================

    def visit_homepage(self):
        url = f"{self.BASE}/"
        r = self.session.get(url, headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
        }, allow_redirects=True)
        self._log("0. Visit homepage", "GET", url, r.status_code,
                   {"cookies_count": len(self.session.cookies)})
        if r.status_code == 403:
            raise OpenAIBrowserBlockedError(f"Homepage blocked (status={r.status_code})")
        return r.status_code

    def get_csrf(self) -> str:
        url = f"{self.BASE}/api/auth/csrf"
        last_status = None
        last_body = ""
        for attempt in range(1, 4):
            r = self.session.get(
                url,
                headers={"Accept": "application/json", "Referer": f"{self.BASE}/"},
                timeout=20,
            )
            data = self._json_or_none(r)
            token = data.get("csrfToken", "") if isinstance(data, dict) else ""
            self._log("1. Get CSRF", "GET", url, r.status_code, data or {"text": r.text[:300]})
            if token:
                return token

            last_status = r.status_code
            last_body = (r.text or "")[:300]
            if attempt < 3:
                self._print(f"[warn] csrf empty/non-json, retry {attempt}/3")
                time.sleep(1.0 * attempt)

        if last_status == 403:
            raise OpenAIBrowserBlockedError(f"Failed to get CSRF token (status={last_status}, body={last_body})")
        raise Exception(f"Failed to get CSRF token (status={last_status}, body={last_body})")

    def signin(self, email: str, csrf: str) -> str:
        url = f"{self.BASE}/api/auth/signin/openai"
        params = {
            "prompt": "login", "ext-oai-did": self.device_id,
            "auth_session_logging_id": self.auth_session_logging_id,
            "screen_hint": "login_or_signup", "login_hint": email,
        }
        form_data = {"callbackUrl": f"{self.BASE}/", "csrfToken": csrf, "json": "true"}
        r = self.session.post(url, params=params, data=form_data, headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json", "Referer": f"{self.BASE}/", "Origin": self.BASE,
        }, timeout=20)
        data = self._json_or_none(r)
        if not isinstance(data, dict):
            data = {"text": r.text[:500]}
        authorize_url = data.get("url", "")
        self._log("2. Signin", "POST", url, r.status_code, data)
        if not authorize_url:
            if r.status_code == 403:
                raise OpenAIBrowserBlockedError(
                    f"Failed to get authorize URL (status={r.status_code}, body={(r.text or '')[:300]})"
                )
            raise Exception(f"Failed to get authorize URL (status={r.status_code}, body={(r.text or '')[:300]})")
        return authorize_url

    def bootstrap_signup(self, email: str) -> str:
        last_error = None
        max_attempts = max(1, len(_PREFERRED_CHROME_PROFILES or _AVAILABLE_CHROME_PROFILES))
        for attempt in range(1, max_attempts + 1):
            try:
                self.visit_homepage()
                _random_delay(0.3, 0.8)
                csrf = self.get_csrf()
                _random_delay(0.2, 0.5)
                return self.signin(email, csrf)
            except OpenAIBrowserBlockedError as e:
                last_error = e
                if attempt >= max_attempts:
                    break
                rotated = self._rotate_browser_profile(reason=f"OpenAI 入口返回 403，准备重试 ({attempt}/{max_attempts})")
                if not rotated:
                    break
                _random_delay(0.8, 1.5)
        if last_error:
            raise last_error
        raise Exception("Failed to bootstrap signup session")

    def authorize(self, url: str) -> str:
        r = self.session.get(url, headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": f"{self.BASE}/", "Upgrade-Insecure-Requests": "1",
        }, allow_redirects=True)
        final_url = str(r.url)
        self._log("3. Authorize", "GET", url, r.status_code, {"final_url": final_url})
        return final_url

    def register(self, email: str, password: str):
        url = f"{self.AUTH}/api/accounts/user/register"
        headers = {"Content-Type": "application/json", "Accept": "application/json",
                    "Referer": f"{self.AUTH}/create-account/password", "Origin": self.AUTH}
        headers.update(_make_trace_headers())
        r = self.session.post(url, json={"username": email, "password": password}, headers=headers)
        try: data = r.json()
        except Exception: data = {"text": r.text[:500]}
        self._log("4. Register", "POST", url, r.status_code, data)
        return r.status_code, data

    def send_otp(self):
        url = f"{self.AUTH}/api/accounts/email-otp/send"
        r = self.session.get(url, headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": f"{self.AUTH}/create-account/password", "Upgrade-Insecure-Requests": "1",
        }, allow_redirects=True)
        try: data = r.json()
        except Exception: data = {"final_url": str(r.url), "status": r.status_code}
        self._log("5. Send OTP", "GET", url, r.status_code, data)
        return r.status_code, data

    def validate_otp(self, code: str):
        url = f"{self.AUTH}/api/accounts/email-otp/validate"
        headers = {"Content-Type": "application/json", "Accept": "application/json",
                    "Referer": f"{self.AUTH}/email-verification", "Origin": self.AUTH}
        headers.update(_make_trace_headers())
        r = self.session.post(url, json={"code": code}, headers=headers)
        try: data = r.json()
        except Exception: data = {"text": r.text[:500]}
        self._log("6. Validate OTP", "POST", url, r.status_code, data)
        return r.status_code, data

    def create_account(self, name: str, birthdate: str):
        url = f"{self.AUTH}/api/accounts/create_account"
        headers = {"Content-Type": "application/json", "Accept": "application/json",
                    "Referer": f"{self.AUTH}/about-you", "Origin": self.AUTH}
        headers.update(_make_trace_headers())
        r = self.session.post(url, json={"name": name, "birthdate": birthdate}, headers=headers)
        try: data = r.json()
        except Exception: data = {"text": r.text[:500]}
        self._log("7. Create Account", "POST", url, r.status_code, data)
        if isinstance(data, dict):
            cb = data.get("continue_url") or data.get("url") or data.get("redirect_url")
            if cb:
                self._callback_url = cb
        return r.status_code, data

    def callback(self, url: str = None):
        if not url:
            url = self._callback_url
        if not url:
            self._print("[!] No callback URL, skipping.")
            return None, None
        r = self.session.get(url, headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
        }, allow_redirects=True)
        self._log("8. Callback", "GET", url, r.status_code, {"final_url": str(r.url)})
        return r.status_code, {"final_url": str(r.url)}

    # ==================== 自动注册主流程 ====================

    def run_register(self, email, password, name, birthdate, mail_token):
        """使用 Resend 收件邮箱的注册流程"""
        auth_url = self.bootstrap_signup(email)
        _random_delay(0.3, 0.8)

        final_url = self.authorize(auth_url)
        final_path = urlparse(final_url).path
        _random_delay(0.3, 0.8)

        self._print(f"Authorize → {final_path}")

        need_otp = False

        if "create-account/password" in final_path:
            self._print("全新注册流程")
            _random_delay(0.5, 1.0)
            status, data = self.register(email, password)
            if status != 200:
                raise Exception(f"Register 失败 ({status}): {data}")
            # register 之后可能还需要 send_otp（全新注册流程中 OTP 不一定在 authorize 时发送）
            _random_delay(0.3, 0.8)
            self.send_otp()
            need_otp = True
        elif "email-verification" in final_path or "email-otp" in final_path:
            self._print("跳到 OTP 验证阶段 (authorize 已触发 OTP，不再重复发送)")
            # 不调用 send_otp()，因为 authorize 重定向到 email-verification 时服务器已发送 OTP
            need_otp = True
        elif "about-you" in final_path:
            self._print("跳到填写信息阶段")
            _random_delay(0.5, 1.0)
            self.create_account(name, birthdate)
            _random_delay(0.3, 0.5)
            self.callback()
            return True
        elif "callback" in final_path or "chatgpt.com" in final_url:
            self._print("账号已完成注册")
            return True
        else:
            self._print(f"未知跳转: {final_url}")
            self.register(email, password)
            self.send_otp()
            need_otp = True

        if need_otp:
            # 使用 Resend 收件箱等待验证码
            otp_code = self.wait_for_verification_email(mail_token)
            if not otp_code:
                raise Exception("未能获取验证码")

            _random_delay(0.3, 0.8)
            status, data = self.validate_otp(otp_code)
            if status != 200:
                self._print("验证码失败，重试...")
                self.send_otp()
                _random_delay(1.0, 2.0)
                otp_code = self.wait_for_verification_email(mail_token, timeout=60)
                if not otp_code:
                    raise Exception("重试后仍未获取验证码")
                _random_delay(0.3, 0.8)
                status, data = self.validate_otp(otp_code)
                if status != 200:
                    raise Exception(f"验证码失败 ({status}): {data}")

        _random_delay(0.5, 1.5)
        status, data = self.create_account(name, birthdate)
        if status != 200:
            raise Exception(f"Create account 失败 ({status}): {data}")
        _random_delay(0.2, 0.5)
        self.callback()
        return True

    def _decode_oauth_session_cookie(self):
        jar = getattr(self.session.cookies, "jar", None)
        if jar is not None:
            cookie_items = list(jar)
        else:
            cookie_items = []

        for c in cookie_items:
            name = getattr(c, "name", "") or ""
            if "oai-client-auth-session" not in name:
                continue

            raw_val = (getattr(c, "value", "") or "").strip()
            if not raw_val:
                continue

            candidates = [raw_val]
            try:
                from urllib.parse import unquote

                decoded = unquote(raw_val)
                if decoded != raw_val:
                    candidates.append(decoded)
            except Exception:
                pass

            for val in candidates:
                try:
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]

                    part = val.split(".")[0] if "." in val else val
                    pad = 4 - len(part) % 4
                    if pad != 4:
                        part += "=" * pad
                    raw = base64.urlsafe_b64decode(part)
                    data = json.loads(raw.decode("utf-8"))
                    if isinstance(data, dict):
                        return data
                except Exception:
                    continue
        return None

    def _oauth_allow_redirect_extract_code(self, url: str, referer: str = None):
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": self.ua,
        }
        if referer:
            headers["Referer"] = referer

        try:
            resp = self.session.get(
                url,
                headers=headers,
                allow_redirects=True,
                timeout=30,
                impersonate=self.impersonate,
            )
            final_url = str(resp.url)
            code = _extract_code_from_url(final_url)
            if code:
                self._print("[OAuth] allow_redirect 命中最终 URL code")
                return code

            for r in getattr(resp, "history", []) or []:
                loc = r.headers.get("Location", "")
                code = _extract_code_from_url(loc)
                if code:
                    self._print("[OAuth] allow_redirect 命中 history Location code")
                    return code
                code = _extract_code_from_url(str(r.url))
                if code:
                    self._print("[OAuth] allow_redirect 命中 history URL code")
                    return code
        except Exception as e:
            maybe_localhost = re.search(r'(https?://localhost[^\s\'\"]+)', str(e))
            if maybe_localhost:
                code = _extract_code_from_url(maybe_localhost.group(1))
                if code:
                    self._print("[OAuth] allow_redirect 从 localhost 异常提取 code")
                    return code
            self._print(f"[OAuth] allow_redirect 异常: {e}")

        return None

    def _oauth_follow_for_code(self, start_url: str, referer: str = None, max_hops: int = 16):
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": self.ua,
        }
        if referer:
            headers["Referer"] = referer

        current_url = start_url
        last_url = start_url

        for hop in range(max_hops):
            try:
                resp = self.session.get(
                    current_url,
                    headers=headers,
                    allow_redirects=False,
                    timeout=30,
                    impersonate=self.impersonate,
                )
            except Exception as e:
                maybe_localhost = re.search(r'(https?://localhost[^\s\'\"]+)', str(e))
                if maybe_localhost:
                    code = _extract_code_from_url(maybe_localhost.group(1))
                    if code:
                        self._print(f"[OAuth] follow[{hop + 1}] 命中 localhost 回调")
                        return code, maybe_localhost.group(1)
                self._print(f"[OAuth] follow[{hop + 1}] 请求异常: {e}")
                return None, last_url

            last_url = str(resp.url)
            self._print(f"[OAuth] follow[{hop + 1}] {resp.status_code} {last_url[:140]}")
            code = _extract_code_from_url(last_url)
            if code:
                return code, last_url

            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("Location", "")
                if not loc:
                    return None, last_url
                if loc.startswith("/"):
                    loc = f"{OAUTH_ISSUER}{loc}"
                code = _extract_code_from_url(loc)
                if code:
                    return code, loc
                current_url = loc
                headers["Referer"] = last_url
                continue

            return None, last_url

        return None, last_url

    def _oauth_submit_workspace_and_org(self, consent_url: str):
        session_data = self._decode_oauth_session_cookie()
        if not session_data:
            jar = getattr(self.session.cookies, "jar", None)
            if jar is not None:
                cookie_names = [getattr(c, "name", "") for c in list(jar)]
            else:
                cookie_names = list(self.session.cookies.keys())
            self._print(f"[OAuth] 无法解码 oai-client-auth-session, cookies={cookie_names[:12]}")
            return None

        workspaces = session_data.get("workspaces", [])
        if not workspaces:
            self._print("[OAuth] session 中没有 workspace 信息")
            return None

        workspace_id = (workspaces[0] or {}).get("id")
        if not workspace_id:
            self._print("[OAuth] workspace_id 为空")
            return None

        h = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": OAUTH_ISSUER,
            "Referer": consent_url,
            "User-Agent": self.ua,
            "oai-device-id": self.device_id,
        }
        h.update(_make_trace_headers())

        resp = self.session.post(
            f"{OAUTH_ISSUER}/api/accounts/workspace/select",
            json={"workspace_id": workspace_id},
            headers=h,
            allow_redirects=False,
            timeout=30,
            impersonate=self.impersonate,
        )
        self._print(f"[OAuth] workspace/select -> {resp.status_code}")

        if resp.status_code in (301, 302, 303, 307, 308):
            loc = resp.headers.get("Location", "")
            if loc.startswith("/"):
                loc = f"{OAUTH_ISSUER}{loc}"
            code = _extract_code_from_url(loc)
            if code:
                return code
            code, _ = self._oauth_follow_for_code(loc, referer=consent_url)
            if not code:
                code = self._oauth_allow_redirect_extract_code(loc, referer=consent_url)
            return code

        if resp.status_code != 200:
            self._print(f"[OAuth] workspace/select 失败: {resp.status_code}")
            return None

        try:
            ws_data = resp.json()
        except Exception:
            self._print("[OAuth] workspace/select 响应不是 JSON")
            return None

        ws_next = ws_data.get("continue_url", "")
        orgs = ws_data.get("data", {}).get("orgs", [])
        ws_page = (ws_data.get("page") or {}).get("type", "")
        self._print(f"[OAuth] workspace/select page={ws_page or '-'} next={(ws_next or '-')[:140]}")

        org_id = None
        project_id = None
        if orgs:
            org_id = (orgs[0] or {}).get("id")
            projects = (orgs[0] or {}).get("projects", [])
            if projects:
                project_id = (projects[0] or {}).get("id")

        if org_id:
            org_body = {"org_id": org_id}
            if project_id:
                org_body["project_id"] = project_id

            h_org = dict(h)
            if ws_next:
                h_org["Referer"] = ws_next if ws_next.startswith("http") else f"{OAUTH_ISSUER}{ws_next}"

            resp_org = self.session.post(
                f"{OAUTH_ISSUER}/api/accounts/organization/select",
                json=org_body,
                headers=h_org,
                allow_redirects=False,
                timeout=30,
                impersonate=self.impersonate,
            )
            self._print(f"[OAuth] organization/select -> {resp_org.status_code}")
            if resp_org.status_code in (301, 302, 303, 307, 308):
                loc = resp_org.headers.get("Location", "")
                if loc.startswith("/"):
                    loc = f"{OAUTH_ISSUER}{loc}"
                code = _extract_code_from_url(loc)
                if code:
                    return code
                code, _ = self._oauth_follow_for_code(loc, referer=h_org.get("Referer"))
                if not code:
                    code = self._oauth_allow_redirect_extract_code(loc, referer=h_org.get("Referer"))
                return code

            if resp_org.status_code == 200:
                try:
                    org_data = resp_org.json()
                except Exception:
                    self._print("[OAuth] organization/select 响应不是 JSON")
                    return None

                org_next = org_data.get("continue_url", "")
                org_page = (org_data.get("page") or {}).get("type", "")
                self._print(f"[OAuth] organization/select page={org_page or '-'} next={(org_next or '-')[:140]}")
                if org_next:
                    if org_next.startswith("/"):
                        org_next = f"{OAUTH_ISSUER}{org_next}"
                    code, _ = self._oauth_follow_for_code(org_next, referer=h_org.get("Referer"))
                    if not code:
                        code = self._oauth_allow_redirect_extract_code(org_next, referer=h_org.get("Referer"))
                    return code

        if ws_next:
            if ws_next.startswith("/"):
                ws_next = f"{OAUTH_ISSUER}{ws_next}"
            code, _ = self._oauth_follow_for_code(ws_next, referer=consent_url)
            if not code:
                code = self._oauth_allow_redirect_extract_code(ws_next, referer=consent_url)
            return code

        return None

    def perform_codex_oauth_login_http(self, email: str, password: str, mail_token: str = None):
        self._print("[OAuth] 开始执行 Codex OAuth 纯协议流程...")

        # 兼容两种 domain 形式，确保 auth 域也带 oai-did
        self.session.cookies.set("oai-did", self.device_id, domain=".auth.openai.com")
        self.session.cookies.set("oai-did", self.device_id, domain="auth.openai.com")

        code_verifier, code_challenge = _generate_pkce()
        state = secrets.token_urlsafe(24)

        authorize_params = {
            "response_type": "code",
            "client_id": OAUTH_CLIENT_ID,
            "redirect_uri": OAUTH_REDIRECT_URI,
            "scope": "openid profile email offline_access",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
        authorize_url = f"{OAUTH_ISSUER}/oauth/authorize?{urlencode(authorize_params)}"

        def _oauth_json_headers(referer: str):
            h = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": OAUTH_ISSUER,
                "Referer": referer,
                "User-Agent": self.ua,
                "oai-device-id": self.device_id,
            }
            h.update(_make_trace_headers())
            return h

        def _bootstrap_oauth_session():
            self._print("[OAuth] 1/7 GET /oauth/authorize")
            try:
                r = self.session.get(
                    authorize_url,
                    headers={
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Referer": f"{self.BASE}/",
                        "Upgrade-Insecure-Requests": "1",
                        "User-Agent": self.ua,
                    },
                    allow_redirects=True,
                    timeout=30,
                    impersonate=self.impersonate,
                )
            except Exception as e:
                self._print(f"[OAuth] /oauth/authorize 异常: {e}")
                return False, ""

            final_url = str(r.url)
            redirects = len(getattr(r, "history", []) or [])
            self._print(f"[OAuth] /oauth/authorize -> {r.status_code}, final={(final_url or '-')[:140]}, redirects={redirects}")

            has_login = any(getattr(c, "name", "") == "login_session" for c in self.session.cookies)
            self._print(f"[OAuth] login_session: {'已获取' if has_login else '未获取'}")

            if not has_login:
                self._print("[OAuth] 未拿到 login_session，尝试访问 oauth2 auth 入口")
                oauth2_url = f"{OAUTH_ISSUER}/api/oauth/oauth2/auth"
                try:
                    r2 = self.session.get(
                        oauth2_url,
                        headers={
                            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                            "Referer": authorize_url,
                            "Upgrade-Insecure-Requests": "1",
                            "User-Agent": self.ua,
                        },
                        params=authorize_params,
                        allow_redirects=True,
                        timeout=30,
                        impersonate=self.impersonate,
                    )
                    final_url = str(r2.url)
                    redirects2 = len(getattr(r2, "history", []) or [])
                    self._print(f"[OAuth] /api/oauth/oauth2/auth -> {r2.status_code}, final={(final_url or '-')[:140]}, redirects={redirects2}")
                except Exception as e:
                    self._print(f"[OAuth] /api/oauth/oauth2/auth 异常: {e}")

                has_login = any(getattr(c, "name", "") == "login_session" for c in self.session.cookies)
                self._print(f"[OAuth] login_session(重试): {'已获取' if has_login else '未获取'}")

            return has_login, final_url

        def _post_authorize_continue(referer_url: str):
            sentinel_authorize = build_sentinel_token(
                self.session,
                self.device_id,
                flow="authorize_continue",
                user_agent=self.ua,
                sec_ch_ua=self.sec_ch_ua,
                impersonate=self.impersonate,
            )
            if not sentinel_authorize:
                self._print("[OAuth] authorize_continue 的 sentinel token 获取失败")
                return None

            headers_continue = _oauth_json_headers(referer_url)
            headers_continue["openai-sentinel-token"] = sentinel_authorize

            try:
                return self.session.post(
                    f"{OAUTH_ISSUER}/api/accounts/authorize/continue",
                    json={"username": {"kind": "email", "value": email}},
                    headers=headers_continue,
                    timeout=30,
                    allow_redirects=False,
                    impersonate=self.impersonate,
                )
            except Exception as e:
                self._print(f"[OAuth] authorize/continue 异常: {e}")
                return None

        has_login_session, authorize_final_url = _bootstrap_oauth_session()
        if not authorize_final_url:
            return None

        continue_referer = authorize_final_url if authorize_final_url.startswith(OAUTH_ISSUER) else f"{OAUTH_ISSUER}/log-in"

        self._print("[OAuth] 2/7 POST /api/accounts/authorize/continue")
        resp_continue = _post_authorize_continue(continue_referer)
        if resp_continue is None:
            return None

        self._print(f"[OAuth] /authorize/continue -> {resp_continue.status_code}")
        if resp_continue.status_code == 400 and "invalid_auth_step" in (resp_continue.text or ""):
            self._print("[OAuth] invalid_auth_step，重新 bootstrap 后重试一次")
            has_login_session, authorize_final_url = _bootstrap_oauth_session()
            if not authorize_final_url:
                return None
            continue_referer = authorize_final_url if authorize_final_url.startswith(OAUTH_ISSUER) else f"{OAUTH_ISSUER}/log-in"
            resp_continue = _post_authorize_continue(continue_referer)
            if resp_continue is None:
                return None
            self._print(f"[OAuth] /authorize/continue(重试) -> {resp_continue.status_code}")

        if resp_continue.status_code != 200:
            self._print(f"[OAuth] 邮箱提交失败: {resp_continue.text[:180]}")
            return None

        try:
            continue_data = resp_continue.json()
        except Exception:
            self._print("[OAuth] authorize/continue 响应解析失败")
            return None

        continue_url = continue_data.get("continue_url", "")
        page_type = (continue_data.get("page") or {}).get("type", "")
        self._print(f"[OAuth] continue page={page_type or '-'} next={(continue_url or '-')[:140]}")

        self._print("[OAuth] 3/7 POST /api/accounts/password/verify")
        sentinel_pwd = build_sentinel_token(
            self.session,
            self.device_id,
            flow="password_verify",
            user_agent=self.ua,
            sec_ch_ua=self.sec_ch_ua,
            impersonate=self.impersonate,
        )
        if not sentinel_pwd:
            self._print("[OAuth] password_verify 的 sentinel token 获取失败")
            return None

        headers_verify = _oauth_json_headers(f"{OAUTH_ISSUER}/log-in/password")
        headers_verify["openai-sentinel-token"] = sentinel_pwd

        try:
            resp_verify = self.session.post(
                f"{OAUTH_ISSUER}/api/accounts/password/verify",
                json={"password": password},
                headers=headers_verify,
                timeout=30,
                allow_redirects=False,
                impersonate=self.impersonate,
            )
        except Exception as e:
            self._print(f"[OAuth] password/verify 异常: {e}")
            return None

        self._print(f"[OAuth] /password/verify -> {resp_verify.status_code}")
        if resp_verify.status_code != 200:
            self._print(f"[OAuth] 密码校验失败: {resp_verify.text[:180]}")
            return None

        try:
            verify_data = resp_verify.json()
        except Exception:
            self._print("[OAuth] password/verify 响应解析失败")
            return None

        continue_url = verify_data.get("continue_url", "") or continue_url
        page_type = (verify_data.get("page") or {}).get("type", "") or page_type
        self._print(f"[OAuth] verify page={page_type or '-'} next={(continue_url or '-')[:140]}")

        need_oauth_otp = (
            page_type == "email_otp_verification"
            or "email-verification" in (continue_url or "")
            or "email-otp" in (continue_url or "")
        )

        if need_oauth_otp:
            self._print("[OAuth] 4/7 检测到邮箱 OTP 验证")
            if not mail_token:
                self._print("[OAuth] OAuth 阶段需要邮箱 OTP，但未提供 mail_token")
                return None

            headers_otp = _oauth_json_headers(f"{OAUTH_ISSUER}/email-verification")
            tried_codes = set()
            otp_success = False
            otp_deadline = time.time() + 120
            oauth_hint_logged = False

            while time.time() < otp_deadline and not otp_success:
                messages = self._fetch_received_emails(mail_token) or []
                candidate_codes = []

                for msg in messages[:12]:
                    msg_id = msg.get("id")
                    if not msg_id:
                        continue
                    detail = self._fetch_email_detail(mail_token, msg_id)
                    if not detail:
                        continue
                    content = _extract_message_content(detail)
                    code = self._extract_verification_code(content)
                    if code and code not in tried_codes:
                        candidate_codes.append(code)

                if not candidate_codes:
                    if messages == [] and not oauth_hint_logged and time.time() >= otp_deadline - 105:
                        self._print(f"[OAuth] {_mailbox_debug_hint(mail_token)}")
                        oauth_hint_logged = True
                    elapsed = int(120 - max(0, otp_deadline - time.time()))
                    self._print(f"[OAuth] OTP 等待中... ({elapsed}s/120s)")
                    time.sleep(2)
                    continue

                for otp_code in candidate_codes:
                    tried_codes.add(otp_code)
                    self._print(f"[OAuth] 尝试 OTP: {otp_code}")
                    try:
                        resp_otp = self.session.post(
                            f"{OAUTH_ISSUER}/api/accounts/email-otp/validate",
                            json={"code": otp_code},
                            headers=headers_otp,
                            timeout=30,
                            allow_redirects=False,
                            impersonate=self.impersonate,
                        )
                    except Exception as e:
                        self._print(f"[OAuth] email-otp/validate 异常: {e}")
                        continue

                    self._print(f"[OAuth] /email-otp/validate -> {resp_otp.status_code}")
                    if resp_otp.status_code != 200:
                        self._print(f"[OAuth] OTP 无效，继续尝试下一条: {resp_otp.text[:160]}")
                        continue

                    try:
                        otp_data = resp_otp.json()
                    except Exception:
                        self._print("[OAuth] email-otp/validate 响应解析失败")
                        continue

                    continue_url = otp_data.get("continue_url", "") or continue_url
                    page_type = (otp_data.get("page") or {}).get("type", "") or page_type
                    self._print(f"[OAuth] OTP 验证通过 page={page_type or '-'} next={(continue_url or '-')[:140]}")
                    otp_success = True
                    break

                if not otp_success:
                    time.sleep(2)

            if not otp_success:
                self._print(f"[OAuth] OAuth 阶段 OTP 验证失败，已尝试 {len(tried_codes)} 个验证码")
                return None

        code = None
        consent_url = continue_url
        if consent_url and consent_url.startswith("/"):
            consent_url = f"{OAUTH_ISSUER}{consent_url}"

        if not consent_url and "consent" in page_type:
            consent_url = f"{OAUTH_ISSUER}/sign-in-with-chatgpt/codex/consent"

        if consent_url:
            code = _extract_code_from_url(consent_url)

        if not code and consent_url:
            self._print("[OAuth] 5/7 跟随 continue_url 提取 code")
            code, _ = self._oauth_follow_for_code(consent_url, referer=f"{OAUTH_ISSUER}/log-in/password")

        consent_hint = (
            ("consent" in (consent_url or ""))
            or ("sign-in-with-chatgpt" in (consent_url or ""))
            or ("workspace" in (consent_url or ""))
            or ("organization" in (consent_url or ""))
            or ("consent" in page_type)
            or ("organization" in page_type)
        )

        if not code and consent_hint:
            if not consent_url:
                consent_url = f"{OAUTH_ISSUER}/sign-in-with-chatgpt/codex/consent"
            self._print("[OAuth] 6/7 执行 workspace/org 选择")
            code = self._oauth_submit_workspace_and_org(consent_url)

        if not code:
            fallback_consent = f"{OAUTH_ISSUER}/sign-in-with-chatgpt/codex/consent"
            self._print("[OAuth] 6/7 回退 consent 路径重试")
            code = self._oauth_submit_workspace_and_org(fallback_consent)
            if not code:
                code, _ = self._oauth_follow_for_code(fallback_consent, referer=f"{OAUTH_ISSUER}/log-in/password")

        if not code:
            self._print("[OAuth] 未获取到 authorization code")
            return None

        self._print("[OAuth] 7/7 POST /oauth/token")
        token_resp = self.session.post(
            f"{OAUTH_ISSUER}/oauth/token",
            headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": self.ua},
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": OAUTH_REDIRECT_URI,
                "client_id": OAUTH_CLIENT_ID,
                "code_verifier": code_verifier,
            },
            timeout=60,
            impersonate=self.impersonate,
        )
        self._print(f"[OAuth] /oauth/token -> {token_resp.status_code}")

        if token_resp.status_code != 200:
            self._print(f"[OAuth] token 交换失败: {token_resp.status_code} {token_resp.text[:200]}")
            return None

        try:
            data = token_resp.json()
        except Exception:
            self._print("[OAuth] token 响应解析失败")
            return None

        if not data.get("access_token"):
            self._print("[OAuth] token 响应缺少 access_token")
            return None

        self._print("[OAuth] Codex Token 获取成功")
        return data


# ==================== 并发批量注册 ====================

def _register_one(idx, total, proxy, output_file):
    """单个注册任务 (在线程中运行) - 使用 Resend 域名收件"""
    reg = None
    try:
        reg = ChatGPTRegister(proxy=proxy, tag=f"{idx}")
        tokens = None
        access_token = ""
        refresh_token = ""
        id_token = ""

        # 1. 生成 Resend 域名下的随机接收地址
        reg._print("[Resend] 生成接收邮箱地址...")
        email, email_pwd, mail_token = reg.create_temp_email()
        tag = email.split("@")[0]
        reg.tag = tag  # 更新 tag

        chatgpt_password = _generate_password()
        name = _random_name()
        birthdate = _random_birthdate()

        with _print_lock:
            print(f"\n{'='*60}")
            print(f"  [{idx}/{total}] 注册: {email}")
            print(f"  ChatGPT密码: {chatgpt_password}")
            print(f"  邮箱服务: Resend ({RESEND_DOMAIN})")
            print(f"  姓名: {name} | 生日: {birthdate}")
            print(f"{'='*60}")

        # 2. 执行注册流程
        reg.run_register(email, chatgpt_password, name, birthdate, mail_token)

        # 3. OAuth（可选）
        oauth_ok = True
        if ENABLE_OAUTH:
            reg._print("[OAuth] 开始获取 Codex Token...")
            tokens = reg.perform_codex_oauth_login_http(email, chatgpt_password, mail_token=mail_token)
            tokens_data = tokens if isinstance(tokens, dict) else {}
            oauth_ok = bool(tokens_data.get("access_token"))
            if oauth_ok:
                _save_codex_tokens(email, tokens_data)
                access_token = (tokens_data.get("access_token") or "").strip()
                refresh_token = (tokens_data.get("refresh_token") or "").strip()
                id_token = (tokens_data.get("id_token") or "").strip()
                reg._print("[OAuth] Token 已保存")
            else:
                msg = "OAuth 获取失败"
                if OAUTH_REQUIRED:
                    raise Exception(f"{msg}（oauth_required=true）")
                reg._print(f"[OAuth] {msg}（按配置继续）")

        # 4. 线程安全写入结果
        with _file_lock:
            output_dir = os.path.dirname(os.path.abspath(output_file))
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(output_file, "a", encoding="utf-8") as out:
                line = f"{email}----{chatgpt_password}----{email_pwd}----oauth={'ok' if oauth_ok else 'fail'}"
                mailbox_query_token = extract_mailbox_query_token(mail_token)
                if mailbox_query_token:
                    line = f"{email}----{chatgpt_password}----{email_pwd}----mail_token={mailbox_query_token}----oauth={'ok' if oauth_ok else 'fail'}"
                if access_token and refresh_token:
                    line += f"----access_token={access_token}----refresh_token={refresh_token}"
                    if id_token:
                        line += f"----id_token={id_token}"
                out.write(f"{line}\n")

        if access_token and refresh_token:
            _update_sub2api_json(access_token, refresh_token, id_token, email)

        with _print_lock:
            print(f"\n[OK] [{tag}] {email} 注册成功!")
        if _log_callback:
            try:
                _log_callback("success", tag or str(idx), f"[register] 注册成功: {email}")
            except Exception:
                pass

        try:
            post_result = _run_post_registration_flow(
                reg=reg,
                email=email,
                password=chatgpt_password,
                proxy=proxy,
                mail_token=mail_token,
                output_file=output_file,
                tag=tag or str(idx),
                tokens=tokens if isinstance(tokens, dict) else None,
            )
            if not bool((post_result or {}).get("ok")):
                post_status = str((post_result or {}).get("status") or "").strip().lower()
                if post_status == "pending":
                    reg._print("[post] 订阅待人工付款，注册结果已保留")
                else:
                    reg._print("[post] 订阅失败，注册结果已保留")
        except Exception as post_exc:
            post_msg = f"test.py 自动链路异常: {post_exc}"
            reg._print(f"[post] {post_msg}")
            if _log_callback:
                try:
                    _log_callback("error", tag or str(idx), post_msg)
                except Exception:
                    pass

        return True, email, None

    except Exception as e:
        error_msg = str(e)
        with _print_lock:
            print(f"\n[FAIL] [{idx}] 注册失败: {error_msg}")
            traceback.print_exc()
        if _log_callback:
            try:
                _log_callback("error", str(idx), f"[register] 注册失败: {error_msg}")
            except Exception:
                pass
        return False, None, error_msg


def run_batch(total_accounts: int = 3, output_file="registered_accounts.txt",
              max_workers=3, proxy=None, stop_event=None):
    """并发批量注册 - Resend 收件版"""

    if RUN_OUTPUT_DIR is None:
        _prepare_run_output_paths()
        output_file = DEFAULT_OUTPUT_FILE
    elif not os.path.isabs(output_file):
        output_file = os.path.join(RUN_OUTPUT_DIR, os.path.basename(output_file))

    if not RESEND_API_KEY or not RESEND_DOMAIN:
        print("❌ 错误: 未设置完整的 Resend 接收配置")
        print("   需要: resend_api_key, resend_domain")
        print("   环境变量: RESEND_API_KEY / RESEND_DOMAIN")
        return 0, 0

    actual_workers = min(max_workers, total_accounts)
    print(f"\n{'#'*60}")
    print(f"  ChatGPT 批量自动注册 (Resend 收件版)")
    print(f"  注册数量: {total_accounts} | 并发数: {actual_workers}")
    print(f"  Resend API: {RESEND_API_BASE}")
    print(f"  收件域名: {RESEND_DOMAIN}")
    print(f"  OAuth: {'开启' if ENABLE_OAUTH else '关闭'} | required: {'是' if OAUTH_REQUIRED else '否'}")
    if ENABLE_OAUTH:
        print(f"  OAuth Issuer: {OAUTH_ISSUER}")
        print(f"  OAuth Client: {OAUTH_CLIENT_ID}")
        print(f"  Token输出: {TOKEN_JSON_DIR}/, {AK_FILE}, {RK_FILE}")
    print(f"  输出文件: {output_file}")
    if RUN_OUTPUT_DIR:
        print(f"  结果目录: {RUN_OUTPUT_DIR}")
    print(f"{'#'*60}\n")

    if _log_callback:
        _log_callback("info", "system", f"开始注册 {total_accounts} 个账号, 并发数 {actual_workers}")

    success_count = 0
    fail_count = 0
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=actual_workers) as executor:
        futures = {}
        for idx in range(1, total_accounts + 1):
            if stop_event and stop_event.is_set():
                break
            future = executor.submit(
                _register_one, idx, total_accounts, proxy, output_file
            )
            futures[future] = idx

        for future in as_completed(futures):
            if stop_event and stop_event.is_set():
                for f in futures:
                    f.cancel()
                break
            idx = futures[future]
            try:
                ok, email, err = future.result()
                if ok:
                    success_count += 1
                else:
                    fail_count += 1
                    print(f"  [账号 {idx}] 失败: {err}")
            except Exception as e:
                fail_count += 1
                with _print_lock:
                    print(f"[FAIL] 账号 {idx} 线程异常: {e}")

    elapsed = time.time() - start_time
    avg = elapsed / total_accounts if total_accounts else 0
    summary = f"注册完成! 耗时 {elapsed:.1f}s | 总数: {total_accounts} | 注册成功: {success_count} | 注册失败: {fail_count}"
    print(f"\n{'#'*60}")
    print(f"  {summary}")
    print(f"  平均速度: {avg:.1f} 秒/个")
    if success_count > 0:
        print(f"  结果文件: {output_file}")
    print(f"{'#'*60}")
    if _log_callback:
        _log_callback("info", "system", summary)
    return success_count, fail_count


def main():
    print("=" * 60)
    print("  ChatGPT 批量自动注册工具 (Resend 收件版)")
    print("=" * 60)

    # 检查 Resend 配置
    if not RESEND_API_KEY or not RESEND_DOMAIN:
        print("\n⚠️  警告: 未设置完整的 Resend 接收配置")
        print("   请编辑 config.json 设置 resend_api_key / resend_domain，或设置环境变量:")
        print("   Windows: set RESEND_API_KEY=re_xxx && set RESEND_DOMAIN=ilkoxpra.resend.app")
        print("   Linux/Mac: export RESEND_API_KEY='re_xxx' && export RESEND_DOMAIN='ilkoxpra.resend.app'")
        print("\n   按 Enter 继续尝试运行 (可能会失败)...")
        input()

    # 交互式代理配置
    proxy = DEFAULT_PROXY
    if proxy:
        print(f"[Info] 检测到默认代理: {proxy}")
        use_default = input("使用此代理? (Y/n): ").strip().lower()
        if use_default == "n":
            proxy = input("输入代理地址 (留空=不使用代理): ").strip() or None
    else:
        env_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") \
                 or os.environ.get("ALL_PROXY") or os.environ.get("all_proxy")
        if env_proxy:
            print(f"[Info] 检测到环境变量代理: {env_proxy}")
            use_env = input("使用此代理? (Y/n): ").strip().lower()
            if use_env == "n":
                proxy = input("输入代理地址 (留空=不使用代理): ").strip() or None
            else:
                proxy = env_proxy
        else:
            proxy = input("输入代理地址 (如 http://127.0.0.1:7890，留空=不使用代理): ").strip() or None

    if proxy:
        print(f"[Info] 使用代理: {proxy}")
    else:
        print("[Info] 不使用代理")

    # 输入注册数量
    count_input = input(f"\n注册账号数量 (默认 {DEFAULT_TOTAL_ACCOUNTS}): ").strip()
    total_accounts = int(count_input) if count_input.isdigit() and int(count_input) > 0 else DEFAULT_TOTAL_ACCOUNTS

    workers_input = input("并发数 (默认 3): ").strip()
    max_workers = int(workers_input) if workers_input.isdigit() and int(workers_input) > 0 else 3

    _prepare_run_output_paths()

    run_batch(total_accounts=total_accounts, output_file=DEFAULT_OUTPUT_FILE,
              max_workers=max_workers, proxy=proxy)


if __name__ == "__main__":
    main()
