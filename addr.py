from __future__ import annotations

import argparse
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_PAYMENT_FILE = Path(__file__).with_name("payment.json")
EMAIL_DOMAINS = ("example.com", "example.net", "example.org")
FIRST_NAMES = (
    "James", "Emma", "Liam", "Olivia", "Noah", "Ava", "Ethan", "Sophia",
    "Lucas", "Mia", "Mason", "Isabella", "Logan", "Charlotte", "Alexander",
    "Amelia", "Benjamin", "Harper", "William", "Evelyn", "Henry", "Abigail",
    "Sebastian", "Emily", "Jack", "Elizabeth", "Daniel", "Grace", "Leo", "Chloe",
)
LAST_NAMES = (
    "Smith", "Johnson", "Brown", "Davis", "Wilson", "Moore", "Taylor",
    "Clark", "Hall", "Young", "Anderson", "Thomas", "Jackson", "White",
    "Harris", "Martin", "Thompson", "Garcia", "Robinson", "Lewis",
    "Walker", "Allen", "King", "Wright", "Scott", "Green", "Baker", "Adams",
)
STREET_NAMES = (
    "Maple", "Oak", "Cedar", "Pine", "Lake", "Sunset", "River", "Hill",
    "Washington", "Lincoln", "Park", "Cherry", "Willow", "Forest", "Aspen", "Madison",
)
STREET_SUFFIXES = ("St", "Ave", "Blvd", "Ln", "Dr", "Way", "Ct", "Rd")
CITY_STATE_POSTAL = (
    ("Los Angeles", "CA", "90001"),
    ("San Diego", "CA", "92101"),
    ("San Jose", "CA", "95112"),
    ("Seattle", "WA", "98101"),
    ("Bellevue", "WA", "98004"),
    ("Austin", "TX", "78701"),
    ("Dallas", "TX", "75201"),
    ("Houston", "TX", "77002"),
    ("Miami", "FL", "33101"),
    ("Orlando", "FL", "32801"),
    ("Chicago", "IL", "60601"),
    ("Boston", "MA", "02108"),
    ("New York", "NY", "10001"),
    ("Brooklyn", "NY", "11201"),
    ("Phoenix", "AZ", "85004"),
    ("Denver", "CO", "80202"),
    ("Atlanta", "GA", "30303"),
    ("Portland", "OR", "97205"),
)


@dataclass(frozen=True)
class BillingAddress:
    country: str
    line1: str
    city: str
    state: str
    postal_code: str

    @property
    def single_line(self) -> str:
        return f"{self.line1}, {self.city}, {self.state} {self.postal_code}, {self.country}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="为 payment.json 批量补充随机测试姓名、邮箱和账单地址字段。",
    )
    parser.add_argument(
        "--file",
        default=str(DEFAULT_PAYMENT_FILE),
        help="目标 payment.json 路径，默认使用 gpt_py/payment.json",
    )
    parser.add_argument(
        "--seed",
        type=int,
        help="可选随机种子，便于复现相同结果。",
    )
    parser.add_argument(
        "--only-missing",
        action="store_true",
        help="只补空字段；默认每次运行都会刷新测试身份字段。",
    )
    return parser.parse_args()


def load_profiles(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path} 不是 JSON 数组")

    profiles: list[dict[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"{path} 第 {index} 个元素不是对象")
        profiles.append(item)
    return profiles


def save_profiles(path: Path, profiles: list[dict[str, Any]]) -> None:
    path.write_text(
        json.dumps(profiles, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def text_value(value: Any) -> str:
    return str(value or "").strip()


def pick_existing(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = text_value(item.get(key))
        if value:
            return value
    return ""


def slugify_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def random_name(rng: random.Random) -> str:
    return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"


def random_email(rng: random.Random, name: str, used_emails: set[str]) -> str:
    base = slugify_name(name) or "tester"
    while True:
        suffix = rng.randint(1000, 999999)
        email = f"{base}{suffix}@{rng.choice(EMAIL_DOMAINS)}"
        if email not in used_emails:
            used_emails.add(email)
            return email


def random_address(rng: random.Random) -> BillingAddress:
    city, state, postal_code = rng.choice(CITY_STATE_POSTAL)
    line1 = f"{rng.randint(100, 9999)} {rng.choice(STREET_NAMES)} {rng.choice(STREET_SUFFIXES)}"
    return BillingAddress(
        country="US",
        line1=line1,
        city=city,
        state=state,
        postal_code=postal_code,
    )


def set_field(item: dict[str, Any], key: str, value: Any, only_missing: bool) -> None:
    if only_missing:
        current = item.get(key)
        if isinstance(current, dict):
            if current:
                return
        elif text_value(current):
            return
    item[key] = value


def build_profile_values(
    item: dict[str, Any],
    rng: random.Random,
    used_emails: set[str],
    only_missing: bool,
) -> tuple[str, str, BillingAddress]:
    if only_missing:
        name = pick_existing(item, "name", "cardholder_name", "payment_cardholder_name")
        if not name:
            name = random_name(rng)

        email = pick_existing(item, "account", "email", "billing_email")
        if email:
            used_emails.add(email.lower())
        else:
            email = random_email(rng, name, used_emails)

        country = pick_existing(item, "billing_country", "country") or "US"
        line1 = pick_existing(item, "billing_line1", "line1")
        city = pick_existing(item, "billing_city", "city")
        state = pick_existing(item, "billing_state", "state")
        postal_code = pick_existing(item, "billing_postal", "postal_code")
        if not (line1 and city and state and postal_code):
            generated = random_address(rng)
            line1 = line1 or generated.line1
            city = city or generated.city
            state = state or generated.state
            postal_code = postal_code or generated.postal_code
            country = country or generated.country
        address = BillingAddress(
            country=country,
            line1=line1,
            city=city,
            state=state,
            postal_code=postal_code,
        )
        return name, email, address

    name = random_name(rng)
    email = random_email(rng, name, used_emails)
    address = random_address(rng)
    return name, email, address


def enrich_profile(
    item: dict[str, Any],
    rng: random.Random,
    used_emails: set[str],
    only_missing: bool,
) -> None:
    name, email, address = build_profile_values(item, rng, used_emails, only_missing)

    fields: dict[str, Any] = {
        "account": email.lower(),
        "email": email.lower(),
        "billing_email": email.lower(),
        "name": name,
        "cardholder_name": name,
        "payment_cardholder_name": name,
        "billing_country": address.country,
        "billing_line1": address.line1,
        "billing_city": address.city,
        "billing_state": address.state,
        "billing_postal": address.postal_code,
        "country": address.country,
        "line1": address.line1,
        "city": address.city,
        "state": address.state,
        "postal_code": address.postal_code,
        "address": address.single_line,
        "billing_address": {
            "country": address.country,
            "line1": address.line1,
            "city": address.city,
            "state": address.state,
            "postal_code": address.postal_code,
        },
    }

    for key, value in fields.items():
        set_field(item, key, value, only_missing=only_missing)


def main() -> int:
    args = parse_args()
    target = Path(args.file).expanduser()
    if not target.is_absolute():
        target = (Path.cwd() / target).resolve()

    rng = random.Random(args.seed)
    profiles = load_profiles(target)
    used_emails = {
        pick_existing(item, "account", "email", "billing_email").lower()
        for item in profiles
        if pick_existing(item, "account", "email", "billing_email")
    }

    for item in profiles:
        enrich_profile(item, rng, used_emails, only_missing=bool(args.only_missing))

    save_profiles(target, profiles)
    mode = "只补空字段" if args.only_missing else "刷新测试身份字段"
    print(f"已更新 {target}，共处理 {len(profiles)} 条记录，模式: {mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
