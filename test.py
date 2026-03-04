import argparse
import base64
import getpass
import json
import os
import re
import subprocess
import sys
import time
import uuid
import webbrowser
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlencode

import requests
from playwright.sync_api import Playwright, TimeoutError as PWTimeoutError, sync_playwright

import chatgpt_register


WATCH_MAP = {
    "openai_checkout": re.compile(r"https://chatgpt\.com/backend-api/payments/checkout"),
    "checkout_data": re.compile(r"https://chatgpt\.com/checkout/openai_llc/.+\.data"),
    "stripe_init": re.compile(r"https://api\.stripe\.com/v1/payment_pages/.+/init"),
    "stripe_payment_methods": re.compile(r"https://api\.stripe\.com/v1/payment_methods"),
    "stripe_confirm": re.compile(r"https://api\.stripe\.com/v1/payment_pages/.+/confirm"),
}


DEFAULT_CHECKOUT_PAYLOAD = {
    "plan_name": "chatgptteamplan",
    "team_plan_data": {
        "workspace_name": "Duckmail",
        "price_interval": "month",
        "seat_quantity": 5,
    },
    "billing_details": {
        "country": "KR",
        "currency": "USD",
    },
    "cancel_url": "https://chatgpt.com/?openaicom_referred=true#pricing",
    "promo_campaign": {
        "promo_campaign_id": "team-1-month-free",
        "is_coupon_from_query_param": False,
    },
    "checkout_ui_mode": "custom",
}

# Startup hardcoded defaults (as requested)
HARDCODED_EMAIL = "nwkl9ppecqs7@duckmail.sbs"
HARDCODED_PASSWORD = "0A5NpOduc*ruZ2"
HARDCODED_PROXY = "socks5h://127.0.0.1:7897"


def _match_key(url: str) -> str | None:
    for key, pattern in WATCH_MAP.items():
        if pattern.search(url):
            return key
    return None


def _safe_json_loads(text: str):
    try:
        return json.loads(text)
    except Exception:
        return text


def _parse_form_data(raw: str):
    if not raw:
        return {}
    try:
        q = parse_qs(raw, keep_blank_values=True)
        return {k: (v[0] if len(v) == 1 else v) for k, v in q.items()}
    except Exception:
        return {"raw": raw}

# 使用韩国画像
def _open_url_visible_default(
    url: str,
    wait_ms: int = 25000,
    screenshot_file: str = "checkout_headless_kr.png",
    keep_open: bool = False,
) -> dict:
    target = str(url or "").strip()
    if not target:
        return {"ok": False, "error": "empty url"}

    launch_kwargs: dict[str, Any] = {"headless": False}
    if sys.platform.startswith("linux"):
        launch_kwargs["args"] = _linux_launch_args()
    if os.name == "nt":
        launch_kwargs["channel"] = "chrome"

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(**launch_kwargs)
            except Exception:
                fallback: dict[str, Any] = {"headless": False}
                if sys.platform.startswith("linux"):
                    fallback["args"] = _linux_launch_args()
                browser = p.chromium.launch(**fallback)
            context = browser.new_context()
            page = context.new_page()
            page.on("requestfailed", lambda req: print(f"[pw][requestfailed] {req.method} {req.url} -> {req.failure}"))
            page.on("console", lambda msg: print(f"[pw][console][{msg.type}] {msg.text}"))
            page.on("pageerror", lambda err: print(f"[pw][pageerror] {err}"))
            page.on("popup", lambda pop: print(f"[pw][popup] {pop.url}"))

            resp = page.goto(target, wait_until="domcontentloaded", timeout=90000)
            try:
                page.wait_for_load_state("networkidle", timeout=30000)
            except Exception:
                pass
            page.wait_for_timeout(max(0, int(wait_ms)))
            shot = str(Path(screenshot_file).resolve())
            try:
                page.screenshot(path=shot, full_page=True)
            except Exception:
                shot = ""
            result = {
                "ok": True,
                "method": "playwright_headed_default",
                "status": (resp.status if resp else None),
                "final_url": page.url,
                "title": page.title(),
                "screenshot": shot,
            }
            if keep_open:
                print("[action] 浏览器已打开，按回车后关闭浏览器并继续...")
                try:
                    input()
                except Exception:
                    pass
            context.close()
            browser.close()
            return result
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _open_url_in_system_browser(url: str) -> dict:
    target = str(url or "").strip()
    if not target:
        return {"ok": False, "error": "empty url"}

    candidates = [
        os.environ.get("CHROME_PATH", "").strip(),
        "chrome",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for cmd in candidates:
        if not cmd:
            continue
        if os.path.isabs(cmd) and not os.path.exists(cmd):
            continue
        try:
            subprocess.Popen([cmd, target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return {"ok": True, "method": "system_chrome", "cmd": cmd}
        except Exception:
            continue

    try:
        if webbrowser.open(target, new=2):
            return {"ok": True, "method": "system_default"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "cannot open system browser"}


def _try_click_first(page, candidates: list[str], timeout_ms: int = 6000) -> bool:
    for name in candidates:
        try:
            page.get_by_role("button", name=re.compile(name, re.I)).first.click(timeout=timeout_ms)
            return True
        except Exception:
            continue
    return False


def _try_click_link_or_button(page, labels: list[str], timeout_ms: int = 6000) -> bool:
    for label in labels:
        pat = re.compile(label, re.I)
        try:
            page.get_by_role("button", name=pat).first.click(timeout=timeout_ms)
            return True
        except Exception:
            pass
        try:
            page.get_by_role("link", name=pat).first.click(timeout=timeout_ms)
            return True
        except Exception:
            pass
    return False


def _fill_in_any_frame(page, selectors: list[str], value: str, timeout_ms: int = 20000) -> bool:
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        for frame in page.frames:
            for sel in selectors:
                try:
                    el = frame.query_selector(sel)
                    if el:
                        el.fill(value)
                        return True
                except Exception:
                    continue
        page.wait_for_timeout(300)
    return False


def _save_debug(page, prefix: str = "login_debug"):
    ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    html_path = Path(f"{prefix}_{ts}.html").resolve()
    png_path = Path(f"{prefix}_{ts}.png").resolve()
    try:
        html_path.write_text(page.content(), encoding="utf-8")
    except Exception:
        pass
    try:
        page.screenshot(path=str(png_path), full_page=True)
    except Exception:
        pass
    print(f"[debug] saved: {html_path}")
    print(f"[debug] saved: {png_path}")


def _extract_curl_cookies(session) -> list[dict]:
    result: list[dict] = []
    jar = getattr(session.cookies, "jar", None)
    if jar is None:
        return result

    for c in list(jar):
        name = getattr(c, "name", "") or ""
        value = getattr(c, "value", "") or ""
        domain = getattr(c, "domain", "") or ""
        path = getattr(c, "path", "/") or "/"
        if not name or not value or not domain:
            continue
        item = {
            "name": name,
            "value": value,
            "domain": domain,
            "path": path,
            "httpOnly": False,
            "secure": bool(getattr(c, "secure", False)),
            "sameSite": "Lax",
        }
        result.append(item)
    return result


def _protocol_login_bootstrap(context, email: str, password: str, proxy: str | None, mail_token: str | None):
    reg = chatgpt_register.ChatGPTRegister(proxy=proxy or "", tag="capture")
    reg._print("[capture] trying protocol login via chatgpt_register")
    tokens = reg.perform_codex_oauth_login_http(email=email, password=password, mail_token=mail_token or "")
    if not isinstance(tokens, dict) or not tokens.get("access_token"):
        return False, "protocol login failed"

    cookies = _extract_curl_cookies(reg.session)
    if not cookies:
        return False, "protocol login got no cookies"

    try:
        context.add_cookies(cookies)
    except Exception as e:
        return False, f"add_cookies failed: {e}"

    return True, "ok"


def _protocol_login_session(email: str, password: str, proxy: str | None, mail_token: str | None):
    reg = chatgpt_register.ChatGPTRegister(proxy=proxy or "", tag="capture")
    reg._print("[capture] trying protocol login via chatgpt_register")
    tokens = reg.perform_codex_oauth_login_http(email=email, password=password, mail_token=mail_token or "")
    if not isinstance(tokens, dict) or not tokens.get("access_token"):
        hint = ""
        if not (mail_token or "").strip():
            hint = "; hint: pass --mail-token or set MAIL_TOKEN for OAuth email OTP"
        return None, None, f"protocol login failed{hint}"
    return reg, tokens, "ok"


def _jwt_expiry(access_token: str) -> int:
    try:
        parts = access_token.split(".")
        if len(parts) < 2:
            return 0
        payload = parts[1]
        payload += "=" * ((4 - len(payload) % 4) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload.encode("utf-8")).decode("utf-8"))
        return int(data.get("exp") or 0)
    except Exception:
        return 0


def _save_auth_cache(cache_file: Path, email: str, tokens: dict, cookies: list[dict]):
    try:
        cache_file.write_text(
            json.dumps(
                {
                    "email": email,
                    "saved_at": int(time.time()),
                    "access_token_exp": _jwt_expiry(str(tokens.get("access_token") or "")),
                    "tokens": tokens,
                    "cookies": cookies,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"[ok] auth cache saved -> {cache_file}")
    except Exception as e:
        print(f"[warn] auth cache save failed: {e}")


def _load_auth_cache(cache_file: Path, email: str) -> dict | None:
    try:
        if not cache_file.exists():
            return None
        raw = json.loads(cache_file.read_text(encoding="utf-8"))
        if str(raw.get("email") or "").strip().lower() != email.strip().lower():
            return None
        exp = int(raw.get("access_token_exp") or 0)
        now = int(time.time())
        if exp and exp <= now + 120:
            return None
        tokens = raw.get("tokens") or {}
        access_token = str(tokens.get("access_token") or "")
        if not access_token:
            return None
        return raw
    except Exception:
        return None


def _protocol_login_session_with_cache(
    email: str,
    password: str,
    proxy: str | None,
    mail_token: str | None,
    cache_file: Path,
    no_cache: bool,
    refresh_auth: bool,
):
    if not no_cache and not refresh_auth:
        cache = _load_auth_cache(cache_file, email=email)
        if cache:
            reg = chatgpt_register.ChatGPTRegister(proxy=proxy or "", tag="capture")
            for c in cache.get("cookies") or []:
                name = str(c.get("name") or "")
                value = str(c.get("value") or "")
                domain = str(c.get("domain") or "")
                path = str(c.get("path") or "/")
                if name and value and domain:
                    try:
                        reg.session.cookies.set(name, value, domain=domain, path=path)
                    except Exception:
                        pass
            print(f"[ok] auth cache loaded <- {cache_file}")
            return reg, (cache.get("tokens") or {}), "ok(cache)"

    reg, tokens, msg = _protocol_login_session(email=email, password=password, proxy=proxy, mail_token=mail_token)
    if reg and isinstance(tokens, dict) and tokens.get("access_token") and not no_cache:
        _save_auth_cache(cache_file, email=email, tokens=tokens, cookies=_extract_curl_cookies(reg.session))
    return reg, tokens, msg


def _perform_login(page, email: str, password: str, timeout_ms: int = 60000):
    page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=timeout_ms)
    page.wait_for_timeout(1500)
    _try_click_link_or_button(page, ["Log in", "登录", "Sign in"], timeout_ms=5000)
    page.wait_for_timeout(1500)
    if "/auth/" not in page.url and "auth.openai.com" not in page.url:
        page.goto("https://chatgpt.com/auth/login", wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(1500)

    # Sometimes there is an intermediate auth choice page
    _try_click_link_or_button(page, ["Continue with email", "Use email", "邮箱", "Email"], timeout_ms=4000)

    email_selectors = ["input[type='email']", "input[name='username']", "input#email", "input[name='email']"]
    if not _fill_in_any_frame(page, email_selectors, email, timeout_ms=25000):
        _save_debug(page)
        raise RuntimeError(f"Cannot find email input, current url={page.url}")

    _try_click_first(page, ["Continue", "继续", "Next", "Log in", "登录"], timeout_ms=12000)

    pwd_selectors = ["input[type='password']", "input[name='password']", "input#password"]
    if not _fill_in_any_frame(page, pwd_selectors, password, timeout_ms=30000):
        _save_debug(page)
        raise RuntimeError(f"Cannot find password input, current url={page.url}")

    _try_click_first(page, ["Continue", "继续", "Log in", "登录", "Sign in"], timeout_ms=12000)

    deadline = time.time() + 120
    while time.time() < deadline:
        cur = page.url
        if "chatgpt.com" in cur and "/auth/" not in cur:
            return
        page.wait_for_timeout(1000)

    raise RuntimeError("Login timeout (captcha/MFA may be required)")


def _linux_launch_args() -> list[str]:
    return [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--disable-software-rasterizer",
        "--disable-background-networking",
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
    ]


def _normalize_playwright_proxy(proxy: str | None) -> str | None:
    if not proxy:
        return None
    p = proxy.strip()
    if p.startswith("socks5h://"):
        return "socks5://" + p[len("socks5h://") :]
    return p


def _read_default_proxy_from_config() -> str:
    try:
        cfg_path = Path(__file__).with_name("config.json")
        if not cfg_path.exists():
            return ""
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        return str(cfg.get("proxy", "") or "").strip()
    except Exception:
        return ""


def _read_optional_json(path_or_json: str, fallback: dict) -> dict:
    text = (path_or_json or "").strip()
    if not text:
        return fallback
    p = Path(text)
    if p.exists() and p.is_file():
        return json.loads(p.read_text(encoding="utf-8"))
    return json.loads(text)


def _pick_device_id_from_cookies(session) -> str:
    try:
        did = session.cookies.get("oai-did") or session.cookies.get("dotcom-did")
        if did:
            return str(did)
    except Exception:
        pass
    return str(uuid.uuid4())


def _openai_checkout_headers(access_token: str, device_id: str, sentinel_token: str = "") -> dict:
    headers = {
        "oai-language": "zh-CN",
        "authorization": f"Bearer {access_token}",
        "content-type": "application/json",
        "accept": "*/*",
        "origin": "https://chatgpt.com",
        "referer": "https://chatgpt.com/?openaicom_referred=true",
        "oai-device-id": device_id,
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    }
    if sentinel_token:
        headers["openai-sentinel-token"] = sentinel_token
    return headers


def _stripe_confirm_headers() -> dict:
    return {
        "content-type": "application/x-www-form-urlencoded",
        "accept": "application/json",
        "origin": "https://js.stripe.com",
        "referer": "https://js.stripe.com/",
        "sec-fetch-site": "same-site",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    }


def _prompt_text(label: str, default: str = "", secret: bool = False) -> str:
    tip = f" [{default}]" if default else ""
    while True:
        if secret:
            value = getpass.getpass(f"{label}{tip}: ")
        else:
            value = input(f"{label}{tip}: ").strip()
        if value:
            return value
        if default:
            return default


def _prompt_yes_no(label: str, default: bool = False) -> bool:
    suffix = " [Y/n]" if default else " [y/N]"
    while True:
        raw = input(f"{label}{suffix}: ").strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes", "1", "true"}:
            return True
        if raw in {"n", "no", "0", "false"}:
            return False


def _stripe_init_payload(checkout_data: dict, stripe_js_id: str, locale: str = "zh-CN") -> str:
    key = str(checkout_data.get("publishable_key") or "")
    data = {
        "browser_locale": locale,
        "browser_timezone": "Asia/Shanghai",
        "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
        "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
        "elements_session_client[elements_init_source]": "custom_checkout",
        "elements_session_client[referrer_host]": "chatgpt.com",
        "elements_session_client[stripe_js_id]": stripe_js_id,
        "elements_session_client[locale]": locale,
        "elements_session_client[is_aggregation_expected]": "false",
        "key": key,
        "_stripe_version": "2025-03-31.basil; checkout_server_update_beta=v1; checkout_manual_approval_preview=v1",
    }
    return urlencode(data)


def _stripe_payment_method_payload(
    checkout_data: dict,
    init_data: dict,
    checkout_session_id: str,
    stripe_js_id: str,
    card_number: str,
    card_cvc: str,
    exp_month: str,
    exp_year: str,
    cardholder_name: str,
    billing_email: str,
    billing_country: str,
    billing_line1: str,
    billing_city: str,
    billing_postal: str,
    billing_state: str,
    guid: str,
    muid: str,
    sid: str,
    radar_hcaptcha_token: str,
) -> str:
    data = {
        "billing_details[name]": cardholder_name,
        "billing_details[email]": billing_email,
        "billing_details[address][country]": billing_country,
        "billing_details[address][line1]": billing_line1,
        "billing_details[address][city]": billing_city,
        "billing_details[address][postal_code]": billing_postal,
        "billing_details[address][state]": billing_state,
        "type": "card",
        "card[number]": re.sub(r"\s+", "", card_number),
        "card[cvc]": card_cvc,
        "card[exp_year]": exp_year,
        "card[exp_month]": exp_month.zfill(2),
        "allow_redisplay": "unspecified",
        "pasted_fields": "number",
        "payment_user_agent": "stripe.js/e4b3a3b372; stripe-js-v3/e4b3a3b372; payment-element; deferred-intent",
        "referrer": "https://chatgpt.com",
        "time_on_page": "120000",
        "client_attribution_metadata[client_session_id]": stripe_js_id,
        "client_attribution_metadata[checkout_session_id]": checkout_session_id,
        "client_attribution_metadata[merchant_integration_source]": "elements",
        "client_attribution_metadata[merchant_integration_subtype]": "payment-element",
        "client_attribution_metadata[merchant_integration_version]": "2021",
        "client_attribution_metadata[payment_intent_creation_flow]": "deferred",
        "client_attribution_metadata[payment_method_selection_flow]": "automatic",
        "client_attribution_metadata[elements_session_config_id]": str(init_data.get("config_id") or ""),
        "client_attribution_metadata[checkout_config_id]": str(init_data.get("config_id") or ""),
        "client_attribution_metadata[merchant_integration_additional_elements][0]": "payment",
        "client_attribution_metadata[merchant_integration_additional_elements][1]": "address",
        "guid": guid,
        "muid": muid,
        "sid": sid,
        "key": str(checkout_data.get("publishable_key") or ""),
        "_stripe_version": "2025-03-31.basil; checkout_server_update_beta=v1; checkout_manual_approval_preview=v1",
    }
    if radar_hcaptcha_token:
        data["radar_options[hcaptcha_token]"] = radar_hcaptcha_token
    return urlencode(data)


def _stripe_confirm_payload(
    checkout_data: dict,
    init_data: dict,
    checkout_session_id: str,
    payment_method_id: str,
    guid: str,
    muid: str,
    sid: str,
    passive_captcha_token: str,
    js_checksum: str,
    rv_timestamp: str,
) -> str:
    base_return = str(init_data.get("stripe_hosted_url") or "")
    if not base_return:
        base_return = f"https://checkout.stripe.com/c/pay/{checkout_session_id}?returned_from_redirect=true"

    data = {
        "guid": guid,
        "muid": muid,
        "sid": sid,
        "payment_method": payment_method_id,
        "init_checksum": str(init_data.get("init_checksum") or ""),
        "version": "e4b3a3b372",
        "expected_amount": "0",
        "expected_payment_method_type": "card",
        "return_url": base_return,
        "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
        "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
        "elements_session_client[elements_init_source]": "custom_checkout",
        "elements_session_client[referrer_host]": "chatgpt.com",
        "elements_session_client[locale]": "zh",
        "elements_session_client[is_aggregation_expected]": "false",
        "client_attribution_metadata[client_session_id]": guid,
        "client_attribution_metadata[checkout_session_id]": checkout_session_id,
        "client_attribution_metadata[merchant_integration_source]": "checkout",
        "client_attribution_metadata[merchant_integration_version]": "custom",
        "client_attribution_metadata[merchant_integration_subtype]": "payment-element",
        "client_attribution_metadata[merchant_integration_additional_elements][0]": "payment",
        "client_attribution_metadata[merchant_integration_additional_elements][1]": "address",
        "client_attribution_metadata[payment_intent_creation_flow]": "deferred",
        "client_attribution_metadata[payment_method_selection_flow]": "automatic",
        "client_attribution_metadata[elements_session_config_id]": str(init_data.get("config_id") or ""),
        "client_attribution_metadata[checkout_config_id]": str(init_data.get("config_id") or ""),
        "key": str(checkout_data.get("publishable_key") or ""),
        "_stripe_version": "2025-03-31.basil; checkout_server_update_beta=v1; checkout_manual_approval_preview=v1",
    }
    if passive_captcha_token:
        data["passive_captcha_token"] = passive_captcha_token
    if js_checksum:
        data["js_checksum"] = js_checksum
    if rv_timestamp:
        data["rv_timestamp"] = rv_timestamp
    return urlencode(data)


def _context_cookie_header(context) -> str:
    try:
        cookies = context.cookies()
        parts = []
        for c in cookies:
            name = str(c.get("name", "") or "").strip()
            value = str(c.get("value", "") or "")
            if name:
                parts.append(f"{name}={value}")
        return "; ".join(parts)
    except Exception:
        return ""


def _build_replay_headers(raw_headers: dict, cookie_header: str = "") -> dict:
    drop = {
        "content-length",
        "host",
        "connection",
        "transfer-encoding",
        "accept-encoding",
    }
    headers: dict[str, str] = {}
    for k, v in (raw_headers or {}).items():
        key = str(k).strip()
        if not key:
            continue
        if key.lower() in drop:
            continue
        headers[key] = str(v)
    if cookie_header:
        headers["cookie"] = cookie_header
    return headers


def _decode_payload_b64(payload_b64: str | None) -> bytes | None:
    if not payload_b64:
        return None
    try:
        return base64.b64decode(payload_b64)
    except Exception:
        return None


def _fetch_checkout_data_route(checkout_session_id: str, session=None, timeout_sec: int = 60) -> dict:
    url = (
        f"https://chatgpt.com/checkout/openai_llc/{checkout_session_id}.data"
        "?_routes=routes%2Fcheckout.%24entity.%24checkoutId"
    )
    try:
        if session is not None:
            resp = session.get(url, timeout=timeout_sec)
        else:
            resp = requests.get(url, timeout=timeout_sec)
        return {
            "ok": True,
            "url": url,
            "status": resp.status_code,
            "headers": dict(resp.headers),
            "body": resp.text[:40000],
        }
    except Exception as e:
        return {"ok": False, "url": url, "error": str(e)}


def _auto_capture_stripe_from_checkout(
    proxy: str | None,
    cookies: list[dict],
    checkout_session_id: str,
    storage_state_file: Path,
    max_wait_ms: int = 90000,
) -> dict:
    launch_kwargs = {"headless": False, "args": _linux_launch_args()}
    pw_proxy = _normalize_playwright_proxy(proxy)
    if pw_proxy:
        launch_kwargs["proxy"] = {"server": pw_proxy}

    latest: dict[str, dict] = {}
    captures: list[dict] = []
    browser = None
    context = None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(**launch_kwargs)
            if storage_state_file.exists():
                context = browser.new_context(
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                    storage_state=str(storage_state_file),
                )
                print(f"[info] loaded browser storage state <- {storage_state_file}")
            else:
                context = browser.new_context(locale="zh-CN", timezone_id="Asia/Shanghai")

            if cookies and not storage_state_file.exists():
                context.add_cookies(cast(list[Any], cookies))
                try:
                    context.storage_state(path=str(storage_state_file))
                    print(f"[ok] bootstrapped browser storage state -> {storage_state_file}")
                except Exception as e:
                    print(f"[warn] bootstrap storage state save failed: {e}")

            page = context.new_page()

            def on_response(resp):
                try:
                    req = resp.request
                    key = _match_key(req.url)
                    if key not in {"stripe_init", "stripe_payment_methods", "stripe_confirm", "checkout_data"}:
                        return

                    req_headers = req.headers
                    req_ct = (req_headers.get("content-type") or "").lower()
                    req_body_raw = req.post_data or ""

                    if "application/json" in req_ct:
                        req_body = _safe_json_loads(req_body_raw)
                    elif "application/x-www-form-urlencoded" in req_ct:
                        req_body = _parse_form_data(req_body_raw)
                    else:
                        req_body = req_body_raw

                    item = {
                        "ts": int(time.time()),
                        "kind": key,
                        "method": req.method,
                        "url": req.url,
                        "request_headers": req_headers,
                        "request_body_raw": req_body_raw,
                        "request_body": req_body,
                        "response_status": resp.status,
                        "response_headers": dict(resp.headers),
                        "response_body": (resp.text() or "")[:40000],
                    }
                    captures.append(item)
                    latest[key] = item
                    print(f"[captured-auto] {key} {req.method} -> {resp.status}")
                except Exception as e:
                    print(f"[warn] auto-capture failed: {e}")

            page.on("response", on_response)

            data_url = (
                f"https://chatgpt.com/checkout/openai_llc/{checkout_session_id}.data"
                "?_routes=routes%2Fcheckout.%24entity.%24checkoutId"
            )
            target = f"https://chatgpt.com/checkout/openai_llc/{checkout_session_id}"

            print(f"[info] opening data route first: {data_url}")
            try:
                page.goto(data_url, wait_until="domcontentloaded", timeout=90000)
                page.wait_for_timeout(1200)
            except Exception as e:
                print(f"[warn] open data route failed: {e}")

            page.goto(target, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(2000)

            if "auth.openai.com" in page.url or "/auth/" in page.url:
                print("[warn] browser not logged in; please complete login manually in opened browser")
                login_deadline = time.time() + 300
                while time.time() < login_deadline:
                    if "chatgpt.com" in page.url and "auth.openai.com" not in page.url and "/auth/" not in page.url:
                        break
                    page.wait_for_timeout(1000)
                if not ("chatgpt.com" in page.url and "auth.openai.com" not in page.url and "/auth/" not in page.url):
                    return {
                        "ok": False,
                        "error": "manual login timeout in browser",
                        "latest": latest,
                        "captures": captures,
                        "final_url": page.url,
                    }
                print("[ok] browser manual login detected")
                try:
                    context.storage_state(path=str(storage_state_file))
                    print(f"[ok] saved browser storage state -> {storage_state_file}")
                except Exception as e:
                    print(f"[warn] save browser storage state failed: {e}")

                try:
                    page.goto(data_url, wait_until="domcontentloaded", timeout=90000)
                    page.wait_for_timeout(1200)
                except Exception as e:
                    print(f"[warn] reopen data route failed: {e}")

                page.goto(target, wait_until="domcontentloaded", timeout=90000)
                page.wait_for_timeout(2000)

            print("[action] 浏览器已打开，请在页面中手动输入卡号/CVC并点击支付")
            print("[action] 脚本会自动抓取 payment_methods/confirm 真实参数")

            deadline = time.time() + max_wait_ms / 1000
            last_log = 0.0
            while True:
                while time.time() < deadline:
                    if _confirm_response_paid(latest.get("stripe_confirm")):
                        print("[ok] detected paid state in stripe_confirm")
                        break
                    now = time.time()
                    if now - last_log >= 5:
                        paid = _confirm_response_paid(latest.get("stripe_confirm"))
                        print(f"[wait] captured={sorted(list(latest.keys()))} paid={paid}")
                        last_log = now
                    page.wait_for_timeout(1000)

                if _confirm_response_paid(latest.get("stripe_confirm")):
                    break

                print("[warn] wait timeout reached, payment not paid yet")
                ans = input("[input] 继续等待支付完成? [Y/n]: ").strip().lower()
                if ans in {"n", "no", "0"}:
                    break
                deadline = time.time() + max_wait_ms / 1000

            return {
                "ok": True,
                "target": target,
                "latest": latest,
                "captures": captures,
                "final_url": page.url,
                "final_paid": _confirm_response_paid(latest.get("stripe_confirm")),
            }
    except Exception as e:
        return {"ok": False, "error": str(e), "latest": latest, "captures": captures}
    finally:
        try:
            if context:
                context.storage_state(path=str(storage_state_file))
                print(f"[ok] saved browser storage state -> {storage_state_file}")
        except Exception as e:
            print(f"[warn] final storage state save failed: {e}")
        try:
            if context:
                context.close()
        except Exception:
            pass
        try:
            if browser:
                browser.close()
        except Exception:
            pass


def _first_val(x) -> str:
    if isinstance(x, list):
        return str(x[0] if x else "")
    return str(x or "")


def _confirm_response_paid(item: dict | None) -> bool:
    if not isinstance(item, dict):
        return False
    body = item.get("response_body")
    if not isinstance(body, str) or not body:
        return False
    data = _safe_json_loads(body)
    if not isinstance(data, dict):
        return False
    payment_status = str(data.get("payment_status") or "").lower()
    status = str(data.get("status") or "").lower()
    state = str(data.get("state") or "").lower()
    if payment_status == "paid":
        return True
    if status == "complete" and state in {"succeeded", "complete"}:
        return True
    return False


def _extract_runtime_params(latest: dict[str, dict]) -> dict:
    pm_item = latest.get("stripe_payment_methods") or {}
    cf_item = latest.get("stripe_confirm") or {}
    pm_body = pm_item.get("request_body")
    cf_body = cf_item.get("request_body")
    pm_form: dict[str, Any] = pm_body if isinstance(pm_body, dict) else {}
    cf_form: dict[str, Any] = cf_body if isinstance(cf_body, dict) else {}
    return {
        "guid": _first_val(cf_form.get("guid") or pm_form.get("guid")),
        "muid": _first_val(cf_form.get("muid") or pm_form.get("muid")),
        "sid": _first_val(cf_form.get("sid") or pm_form.get("sid")),
        "radar_hcaptcha_token": _first_val(pm_form.get("radar_options[hcaptcha_token]")),
        "js_checksum": _first_val(cf_form.get("js_checksum")),
        "rv_timestamp": _first_val(cf_form.get("rv_timestamp")),
        "passive_captcha_token": _first_val(cf_form.get("passive_captcha_token")),
        "payment_method": _first_val(cf_form.get("payment_method")),
        "init_checksum": _first_val(cf_form.get("init_checksum")),
    }


def _run_protocol_only(
    email: str,
    password: str,
    out_file: Path,
    proxy: str | None,
    checkout_payload_json: str,
    openai_sentinel_token: str,
    stripe_confirm_url: str,
    stripe_confirm_payload_b64: str,
    max_wait_ms: int,
    mail_token: str | None,
    auth_cache_file: Path,
    browser_state_file: Path,
    no_auth_cache: bool,
    refresh_auth: bool,
    skip_runtime_capture: bool,
    stripe_open_mode: str,
):
    reg, tokens, msg = _protocol_login_session_with_cache(
        email=email,
        password=password,
        proxy=proxy,
        mail_token=mail_token,
        cache_file=auth_cache_file,
        no_cache=no_auth_cache,
        refresh_auth=refresh_auth,
    )
    if not reg or not tokens:
        raise RuntimeError(msg)

    access_token = str(tokens.get("access_token") or "").strip()
    if not access_token:
        raise RuntimeError("access_token missing")

    device_id = _pick_device_id_from_cookies(reg.session)
    checkout_payload = _read_optional_json(checkout_payload_json, DEFAULT_CHECKOUT_PAYLOAD)
    checkout_headers = _openai_checkout_headers(
        access_token=access_token,
        device_id=device_id,
        sentinel_token=(openai_sentinel_token or "").strip(),
    )

    proxies = None
    if proxy:
        proxies = {"http": proxy, "https": proxy}

    checkout_result: dict
    checkout_data: dict = {}
    try:
        resp = reg.session.post(
            "https://chatgpt.com/backend-api/payments/checkout",
            headers=checkout_headers,
            json=checkout_payload,
            timeout=60,
        )
        parsed = _safe_json_loads(resp.text)
        if isinstance(parsed, dict):
            checkout_data = parsed
        checkout_result = {
            "ok": True,
            "status": resp.status_code,
            "headers": dict(resp.headers),
            "body": resp.text[:40000],
        }
        print(f"[ok] protocol checkout status={resp.status_code}")
    except Exception as e:
        checkout_result = {"ok": False, "error": str(e)}
        print(f"[error] protocol checkout failed: {e}")

    init_result: dict = {"ok": False, "reason": "checkout failed"}
    payment_method_result: dict = {"ok": False, "reason": "runtime capture not executed"}
    stripe_result: dict = {"ok": False, "reason": "runtime capture not executed"}
    runtime_capture: dict = {"ok": False, "reason": "checkout failed"}
    runtime_params: dict = {}
    checkout_data_route_result: dict = {"ok": False, "reason": "checkout failed"}
    checkout_url = ""
    checkout_data_url = ""
    stripe_hosted_url = ""

    checkout_session_id = str(checkout_data.get("checkout_session_id") or "").strip()
    processor_entity = str(checkout_data.get("processor_entity") or "openai_llc").strip() or "openai_llc"
    if checkout_session_id:
        checkout_url = f"https://chatgpt.com/checkout/{processor_entity}/{checkout_session_id}"
        checkout_data_url = (
            f"https://chatgpt.com/checkout/{processor_entity}/{checkout_session_id}.data"
            "?_routes=routes%2Fcheckout.%24entity.%24checkoutId"
        )

    if checkout_result.get("ok") and checkout_session_id:
        checkout_data_route_result = _fetch_checkout_data_route(checkout_session_id, session=reg.session)
        if checkout_data_route_result.get("ok"):
            print(f"[ok] checkout .data fetch status={checkout_data_route_result.get('status')}")
        else:
            print(f"[warn] checkout .data fetch failed: {checkout_data_route_result.get('error')}")

        print(f"[ok] checkout url: {checkout_url}")
        print(f"[ok] checkout data url: {checkout_data_url}")

        stripe_init_url = f"https://api.stripe.com/v1/payment_pages/{checkout_session_id}/init"
        stripe_headers = _stripe_confirm_headers()

        init_payload = _stripe_init_payload(checkout_data, stripe_js_id=str(uuid.uuid4()), locale="zh-CN")
        try:
            init_resp = requests.post(
                stripe_init_url,
                headers=stripe_headers,
                data=init_payload,
                timeout=60,
                proxies=proxies,
            )
            init_parsed = _safe_json_loads(init_resp.text)
            if isinstance(init_parsed, dict):
                stripe_hosted_url = str(init_parsed.get("stripe_hosted_url") or "").strip()
            init_result = {
                "ok": True,
                "status": init_resp.status_code,
                "headers": dict(init_resp.headers),
                "body": init_resp.text[:40000],
            }
            print(f"[ok] protocol stripe_init status={init_resp.status_code}")
            if stripe_hosted_url:
                print(f"[ok] stripe hosted url: {stripe_hosted_url}")
                if (stripe_open_mode or "").strip().lower() == "system":
                    stripe_open_res = _open_url_in_system_browser(stripe_hosted_url)
                else:
                    stripe_open_res = _open_url_visible_default(
                        stripe_hosted_url,
                        wait_ms=25000,
                        screenshot_file="stripe_headed_kr.png",
                        keep_open=True,
                    )
                if stripe_open_res.get("ok"):
                    print(
                        f"[ok] opened stripe hosted url "
                        f"method={stripe_open_res.get('method')} status={stripe_open_res.get('status')} final={stripe_open_res.get('final_url')}"
                    )
                else:
                    print(f"[warn] failed to open stripe hosted url: {stripe_open_res.get('error')}")
        except Exception as e:
            init_result = {"ok": False, "error": str(e)}
            print(f"[error] protocol stripe_init failed: {e}")

        if not skip_runtime_capture:
            print("[info] 接下来会打开真实浏览器，请手动输入卡号/CVC并点击支付")
            runtime_capture = _auto_capture_stripe_from_checkout(
                proxy=proxy,
                cookies=_extract_curl_cookies(reg.session),
                checkout_session_id=checkout_session_id,
                storage_state_file=browser_state_file,
                max_wait_ms=max_wait_ms,
            )
        else:
            payment_method_result = {"ok": False, "reason": "skipped (--skip-runtime-capture)"}
            stripe_result = {"ok": False, "reason": "skipped (--skip-runtime-capture)"}

            latest = (runtime_capture.get("latest") or {}) if isinstance(runtime_capture, dict) else {}
            runtime_params = _extract_runtime_params(latest if isinstance(latest, dict) else {})

            pm_item = latest.get("stripe_payment_methods") if isinstance(latest, dict) else None
            cf_item = latest.get("stripe_confirm") if isinstance(latest, dict) else None

            if isinstance(pm_item, dict):
                payment_method_result = {
                    "ok": True,
                    "url": pm_item.get("url"),
                    "status": pm_item.get("response_status"),
                    "request_headers": pm_item.get("request_headers"),
                    "request_body_raw": pm_item.get("request_body_raw"),
                    "response_headers": pm_item.get("response_headers"),
                    "response_body": pm_item.get("response_body"),
                }
            else:
                payment_method_result = {"ok": False, "reason": "stripe_payment_methods not captured"}

            if isinstance(cf_item, dict):
                confirm_paid = _confirm_response_paid(cf_item)
                confirm_body = _safe_json_loads(str(cf_item.get("response_body") or ""))
                confirm_session_id = ""
                if isinstance(confirm_body, dict):
                    confirm_session_id = str(confirm_body.get("session_id") or "").strip()
                stripe_result = {
                    "ok": True,
                    "paid": confirm_paid,
                    "url": cf_item.get("url"),
                    "status": cf_item.get("response_status"),
                    "request_headers": cf_item.get("request_headers"),
                    "request_body_raw": cf_item.get("request_body_raw"),
                    "response_headers": cf_item.get("response_headers"),
                    "response_body": cf_item.get("response_body"),
                    "session_id": confirm_session_id,
                }
                if not confirm_paid:
                    print("[warn] stripe_confirm captured but not paid yet; complete challenge in browser")
                if confirm_session_id and confirm_session_id != checkout_session_id:
                    print(f"[warn] session mismatch: checkout={checkout_session_id} runtime={confirm_session_id}")
            else:
                stripe_result = {"ok": False, "reason": "stripe_confirm not captured"}

    result = {
        "mode": "protocol_only",
        "checkout_payload": checkout_payload,
        "checkout_data": checkout_data,
        "checkout_result": checkout_result,
        "checkout_url": checkout_url,
        "checkout_data_url": checkout_data_url,
        "stripe_hosted_url": stripe_hosted_url,
        "checkout_data_route_result": checkout_data_route_result,
        "runtime_capture": runtime_capture,
        "runtime_params": runtime_params,
        "stripe_confirm_url_override": stripe_confirm_url,
        "stripe_confirm_payload_override_b64": bool((stripe_confirm_payload_b64 or "").strip()),
        "stripe_init_result": init_result,
        "stripe_payment_method_result": payment_method_result,
        "stripe_confirm_result": stripe_result,
    }
    out_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] protocol results -> {out_file}")


def _body_to_bytes(body) -> bytes:
    if body is None:
        return b""
    if isinstance(body, bytes):
        return body
    if isinstance(body, str):
        return body.encode("utf-8")
    if isinstance(body, (dict, list)):
        return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return str(body).encode("utf-8")


def _captured_body_to_bytes(item: dict, fallback_body=None) -> bytes:
    raw = item.get("request_body_raw")
    if isinstance(raw, str) and raw:
        return raw.encode("utf-8")
    if isinstance(raw, bytes) and raw:
        return raw
    return _body_to_bytes(fallback_body if fallback_body is not None else item.get("request_body"))


def _ensure_stripe_js_loaded(page, timeout_ms: int = 20000):
    page.goto("https://js.stripe.com/v3/", wait_until="domcontentloaded", timeout=timeout_ms)
    page.wait_for_timeout(1200)


def _replay_openai_checkout(
    latest: dict[str, dict],
    context,
    proxy: str | None,
    payload_b64: str | None,
    timeout_sec: int = 60,
) -> dict:
    item = latest.get("openai_checkout") or {}
    if not item:
        return {"ok": False, "reason": "openai_checkout not captured"}

    url = str(item.get("url") or "https://chatgpt.com/backend-api/payments/checkout")
    req_headers = item.get("request_headers") or {}
    req_body = item.get("request_body")

    payload_override = _decode_payload_b64(payload_b64)
    payload_bytes = payload_override if payload_override is not None else _captured_body_to_bytes(item, fallback_body=req_body)

    cookie_header = _context_cookie_header(context)
    headers = _build_replay_headers(req_headers, cookie_header=cookie_header)

    proxies = None
    if proxy:
        proxies = {"http": proxy, "https": proxy}

    try:
        resp = requests.post(url, headers=headers, data=payload_bytes, timeout=timeout_sec, proxies=proxies)
        return {
            "ok": True,
            "url": url,
            "status": resp.status_code,
            "request_header_keys": sorted(list(headers.keys())),
            "request_payload_size": len(payload_bytes),
            "response_headers": dict(resp.headers),
            "response_body": resp.text[:40000],
        }
    except Exception as e:
        return {
            "ok": False,
            "url": url,
            "error": str(e),
            "request_header_keys": sorted(list(headers.keys())),
            "request_payload_size": len(payload_bytes),
        }


def _replay_stripe_confirm(
    latest: dict[str, dict],
    context,
    page,
    proxy: str | None,
    payload_b64: str | None,
    timeout_sec: int = 60,
) -> dict:
    item = latest.get("stripe_confirm") or {}
    if not item:
        return {"ok": False, "reason": "stripe_confirm not captured"}

    try:
        _ensure_stripe_js_loaded(page)
    except Exception as e:
        return {"ok": False, "reason": f"load js.stripe.com failed: {e}"}

    url = str(item.get("url") or "")
    if not url:
        return {"ok": False, "reason": "stripe_confirm url missing"}

    req_headers = item.get("request_headers") or {}
    payload_override = _decode_payload_b64(payload_b64)
    payload_bytes = payload_override if payload_override is not None else _captured_body_to_bytes(item)
    headers = _build_replay_headers(req_headers, cookie_header="")

    proxies = None
    if proxy:
        proxies = {"http": proxy, "https": proxy}

    try:
        resp = requests.post(url, headers=headers, data=payload_bytes, timeout=timeout_sec, proxies=proxies)
        return {
            "ok": True,
            "url": url,
            "status": resp.status_code,
            "request_header_keys": sorted(list(headers.keys())),
            "request_payload_size": len(payload_bytes),
            "response_headers": dict(resp.headers),
            "response_body": resp.text[:40000],
        }
    except Exception as e:
        return {
            "ok": False,
            "url": url,
            "error": str(e),
            "request_header_keys": sorted(list(headers.keys())),
            "request_payload_size": len(payload_bytes),
        }


def _run(
    playwright: Playwright,
    email: str,
    password: str,
    out_file: Path,
    max_wait_ms: int,
    proxy: str | None,
    replay_checkout: bool,
    checkout_payload_b64: str | None,
    replay_stripe_confirm: bool,
    stripe_confirm_payload_b64: str | None,
    mail_token: str | None,
):
    # 强制无头，不弹窗，适配 Linux 服务器
    launch_kwargs = {"headless": True, "args": _linux_launch_args()}
    pw_proxy = _normalize_playwright_proxy(proxy)
    if pw_proxy:
        launch_kwargs["proxy"] = {"server": pw_proxy}
        print(f"[info] playwright proxy: {pw_proxy}")
    else:
        print("[warn] no proxy configured; auth.openai.com may return 403")

    browser = playwright.chromium.launch(**launch_kwargs)
    context = browser.new_context(locale="zh-CN", timezone_id="Asia/Shanghai")

    # 降资源占用：拦截图片/字体
    context.route(
        "**/*",
        lambda route: route.abort()
        if route.request.resource_type in {"image", "font", "media"}
        else route.continue_(),
    )

    page = context.new_page()
    captures: list[dict] = []
    latest: dict[str, dict] = {}
    replay_result: dict = {"ok": False, "reason": "not executed"}
    stripe_confirm_replay_result: dict = {"ok": False, "reason": "not executed"}

    def on_response(resp):
        try:
            req = resp.request
            key = _match_key(req.url)
            if not key:
                return

            req_headers = req.headers
            req_ct = (req_headers.get("content-type") or "").lower()
            req_body_raw = req.post_data or ""

            if "application/json" in req_ct:
                req_body = _safe_json_loads(req_body_raw)
            elif "application/x-www-form-urlencoded" in req_ct:
                req_body = _parse_form_data(req_body_raw)
            else:
                req_body = req_body_raw

            resp_text = ""
            try:
                resp_text = resp.text()
            except Exception:
                resp_text = ""

            item = {
                "ts": int(time.time()),
                "kind": key,
                "method": req.method,
                "url": req.url,
                "request_headers": req_headers,
                "request_body_raw": req_body_raw,
                "request_body": req_body,
                "response_status": resp.status,
                "response_headers": dict(resp.headers),
                "response_body": resp_text[:40000],
            }
            captures.append(item)
            latest[key] = item
            print(f"[captured] {key} {req.method} -> {resp.status}")
        except Exception as e:
            print(f"[warn] capture failed: {e}")

    page.on("response", on_response)

    try:
        protocol_ok, protocol_msg = _protocol_login_bootstrap(
            context,
            email=email,
            password=password,
            proxy=proxy,
            mail_token=mail_token,
        )
        if protocol_ok:
            print("[ok] protocol login bootstrap success")
            page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=90000)
        else:
            print(f"[warn] protocol login unavailable: {protocol_msg}; fallback to UI login")
            _perform_login(page, email=email, password=password)
            print("[ok] ui login success")

        page.goto("https://chatgpt.com/#pricing", wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(3000)

        # 尝试触发 Team/Business 升级链路
        _try_click_first(page, ["Team", "Business", "Upgrade", "升级", "Get started", "开始使用"], timeout_ms=8000)
        page.wait_for_timeout(6000)
        _try_click_first(page, ["Continue", "继续", "Checkout", "结账", "确认"], timeout_ms=8000)

        # 等到关键链路抓到，或超时
        begin = time.time()
        needed: set[str] = set()
        if replay_checkout:
            needed.add("openai_checkout")
        if replay_stripe_confirm:
            needed.add("stripe_confirm")
        if not needed:
            needed.add("openai_checkout")

        print(f"[info] waiting captures, needed={sorted(list(needed))}")
        last_log = 0.0
        while (time.time() - begin) * 1000 < max_wait_ms:
            got = set(latest.keys())
            if needed.issubset(got):
                break
            now = time.time()
            if now - last_log >= 5:
                missing = sorted(list(needed - got))
                print(f"[wait] captured={sorted(list(got))} missing={missing}")
                last_log = now
            page.wait_for_timeout(1000)

        got = set(latest.keys())
        if not needed.issubset(got):
            missing = sorted(list(needed - got))
            print(f"[warn] capture wait timeout, missing={missing}")
        else:
            print(f"[ok] capture condition satisfied: {sorted(list(needed))}")

        if replay_checkout:
            replay_result = _replay_openai_checkout(
                latest=latest,
                context=context,
                proxy=proxy,
                payload_b64=checkout_payload_b64,
            )
            if replay_result.get("ok"):
                print(f"[ok] replay checkout status={replay_result.get('status')}")
            else:
                print(f"[warn] replay checkout failed: {replay_result.get('reason') or replay_result.get('error')}")

        if replay_stripe_confirm:
            stripe_confirm_replay_result = _replay_stripe_confirm(
                latest=latest,
                context=context,
                page=page,
                proxy=proxy,
                payload_b64=stripe_confirm_payload_b64,
            )
            if stripe_confirm_replay_result.get("ok"):
                print(f"[ok] replay stripe_confirm status={stripe_confirm_replay_result.get('status')}")
            else:
                print(
                    f"[warn] replay stripe_confirm failed: "
                    f"{stripe_confirm_replay_result.get('reason') or stripe_confirm_replay_result.get('error')}"
                )

    except PWTimeoutError as e:
        print(f"[error] timeout: {e}")
    finally:
        out_file.write_text(
            json.dumps(
                {
                    "captures": captures,
                    "latest": latest,
                    "replay_checkout": replay_result,
                    "replay_stripe_confirm": stripe_confirm_replay_result,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        chain_file = out_file.with_name(out_file.stem + "_chain.json")
        chain_file.write_text(
            json.dumps(
                {
                    "latest": latest,
                    "replay_checkout": replay_result,
                    "replay_stripe_confirm": stripe_confirm_replay_result,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"[ok] captures={len(captures)} -> {out_file}")
        print(f"[ok] latest chain -> {chain_file}")
        context.close()
        browser.close()


def main():
    parser = argparse.ArgumentParser(description="Headless Playwright: login and capture checkout request chain")
    parser.add_argument("--email", default=os.environ.get("OPENAI_EMAIL", ""), help="Login email")
    parser.add_argument("--password", default=os.environ.get("OPENAI_PASSWORD", ""), help="Login password")
    parser.add_argument("--output", default="checkout_capture.json", help="Output JSON path")
    parser.add_argument("--max-wait-ms", type=int, default=600000, help="Max capture wait time after trigger")
    parser.add_argument("--proxy", default="", help="Optional proxy url like socks5h://127.0.0.1:1080")
    parser.add_argument(
        "--checkout-payload-b64",
        default="",
        help="Optional base64 payload to override captured openai_checkout request body",
    )
    parser.add_argument(
        "--no-replay-checkout",
        action="store_true",
        help="Disable protocol replay for openai_checkout after capture",
    )
    parser.add_argument(
        "--stripe-confirm-payload-b64",
        default="",
        help="Optional base64 payload to override captured stripe_confirm request body",
    )
    parser.add_argument(
        "--no-replay-stripe-confirm",
        action="store_true",
        help="Disable protocol replay for stripe_confirm after capture",
    )
    parser.add_argument(
        "--protocol-only",
        action="store_true",
        help="Use pure protocol chain (no UI trigger/capture)",
    )
    parser.add_argument(
        "--checkout-payload-json",
        default="",
        help="Checkout JSON string or JSON file path (used in --protocol-only)",
    )
    parser.add_argument(
        "--openai-sentinel-token",
        default="",
        help="Optional openai-sentinel-token header (used in --protocol-only)",
    )
    parser.add_argument(
        "--stripe-confirm-url",
        default="",
        help="Stripe confirm url (used in --protocol-only)",
    )
    parser.add_argument(
        "--mail-token",
        default=os.environ.get("MAIL_TOKEN", ""),
        help="Mail API token for auto OTP during OAuth (DuckMail token)",
    )
    parser.add_argument(
        "--auth-cache-file",
        default="auth_cache.json",
        help="Auth cache file path for reusing login session",
    )
    parser.add_argument(
        "--no-auth-cache",
        action="store_true",
        help="Disable reading/writing auth cache",
    )
    parser.add_argument(
        "--refresh-auth",
        action="store_true",
        help="Force fresh login and overwrite auth cache",
    )
    parser.add_argument(
        "--browser-state-file",
        default="browser_state.json",
        help="Playwright browser storage state file for logged-in session",
    )
    parser.add_argument(
        "--skip-runtime-capture",
        action="store_true",
        help="Skip runtime browser capture for payment_methods/confirm",
    )
    parser.add_argument(
        "--stripe-open-mode",
        choices=["playwright", "system"],
        default="playwright",
        help="How to open stripe hosted url: playwright or system browser",
    )
    parser.add_argument(
        "--no-browser-capture",
        action="store_true",
        help="Deprecated alias of --skip-runtime-capture",
    )
    parser.add_argument(
        "--stripe-system-browser",
        action="store_true",
        help="Deprecated alias of --stripe-open-mode system",
    )
    args = parser.parse_args()

    interactive = len(sys.argv) == 1
    if interactive:
        print("[info] detected no CLI args, entering interactive mode")
        args.protocol_only = True

    proxy_default = (args.proxy or os.environ.get("PROXY", "") or _read_default_proxy_from_config()).strip()

    if interactive:
        args.email = HARDCODED_EMAIL
        args.password = HARDCODED_PASSWORD
        args.proxy = HARDCODED_PROXY or proxy_default
        args.output = args.output or "checkout_capture.json"
        # 是否抓包
        args.skip_runtime_capture = True
        # playwright | system
        args.stripe_open_mode = "system"
        print(f"[info] using hardcoded email={args.email} proxy={args.proxy}")
    else:
        if not args.email:
            args.email = _prompt_text("OpenAI Email")
        if not args.password:
            args.password = _prompt_text("OpenAI Password", secret=True)

    if not args.email or not args.password:
        raise SystemExit("Missing email/password")

    proxy = (args.proxy or proxy_default).strip() or None

    if bool(args.no_browser_capture):
        args.skip_runtime_capture = True
    if bool(args.stripe_system_browser):
        args.stripe_open_mode = "system"

    out_file = Path(args.output).resolve()
    if args.protocol_only:
        _run_protocol_only(
            email=args.email,
            password=args.password,
            out_file=out_file,
            proxy=proxy,
            checkout_payload_json=args.checkout_payload_json,
            openai_sentinel_token=args.openai_sentinel_token,
            stripe_confirm_url=args.stripe_confirm_url,
            stripe_confirm_payload_b64=(args.stripe_confirm_payload_b64 or "").strip(),
            max_wait_ms=args.max_wait_ms,
            mail_token=(args.mail_token or "").strip() or None,
            auth_cache_file=Path(args.auth_cache_file).resolve(),
            browser_state_file=Path(args.browser_state_file).resolve(),
            no_auth_cache=bool(args.no_auth_cache),
            refresh_auth=bool(args.refresh_auth),
            skip_runtime_capture=bool(args.skip_runtime_capture),
            stripe_open_mode=str(args.stripe_open_mode),
        )
        return

    with sync_playwright() as p:
        _run(
            p,
            email=args.email,
            password=args.password,
            out_file=out_file,
            max_wait_ms=args.max_wait_ms,
            proxy=proxy,
            replay_checkout=not args.no_replay_checkout,
            checkout_payload_b64=(args.checkout_payload_b64 or "").strip() or None,
            replay_stripe_confirm=not args.no_replay_stripe_confirm,
            stripe_confirm_payload_b64=(args.stripe_confirm_payload_b64 or "").strip() or None,
            mail_token=(args.mail_token or "").strip() or None,
        )


if __name__ == "__main__":
    main()
