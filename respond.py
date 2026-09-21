"""Answer an inbound lead in seconds: score it, reply to it, book it, escalate it.

    python respond.py --demo
    python respond.py samples/lead_hot.json
    python respond.py samples/lead_hot.json --rules rules.yaml --json
    python respond.py --serve 8080          # tiny webhook listener, stdlib only
    python respond.py --selftest

Everything is driven by rules.yaml, so the person who owns the sales process can
change the scoring, the wording and the office hours without touching Python.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, time as clock, timedelta
from pathlib import Path

import yaml

HERE = Path(__file__).parent
DEFAULT_RULES = HERE / "rules.yaml"
EXAMPLE_RULES = HERE / "rules.example.yaml"

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[a-z]{2,}$", re.I)
DIGITS_RE = re.compile(r"[^\d+]")
MONEY_RE = re.compile(r"(\d[\d\s.,]*)\s*(k|тыс|thousand)?", re.I)
FREE_MAIL = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "gmx.de", "web.de", "icloud.com"}


# ---------------------------------------------------------------- rules

def load_rules(path: Path | None = None) -> dict:
    """rules.yaml if present, otherwise the committed example."""
    chosen = path or (DEFAULT_RULES if DEFAULT_RULES.exists() else EXAMPLE_RULES)
    if not chosen.exists():
        sys.exit(f"no rules file found (looked for {chosen})")
    return yaml.safe_load(chosen.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- parsing

def clean(value, limit=500) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def parse_phone(value, default_cc="+1") -> str:
    raw = DIGITS_RE.sub("", clean(value, 40))
    if not raw:
        return ""
    if raw.startswith("00"):
        raw = "+" + raw[2:]
    elif not raw.startswith("+"):
        raw = default_cc + raw.lstrip("0")
    return raw if 8 <= len(raw) <= 16 else ""


def parse_budget(value) -> float | None:
    """'about 5k', '$4,000', 4000 -> 5000.0 / 4000.0 / 4000.0; junk -> None."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = MONEY_RE.search(str(value).lower())
    if not match:
        return None
    number = match.group(1).replace(" ", "").replace(",", "")
    if number.count(".") == 1 and len(number.split(".")[1]) == 3:
        number = number.replace(".", "")
    try:
        amount = float(number)
    except ValueError:
        return None
    return amount * 1000 if match.group(2) else amount


def email_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower() if "@" in email else ""


# ---------------------------------------------------------------- scoring

@dataclass
class Lead:
    name: str = ""
    email: str = ""
    phone: str = ""
    company: str = ""
    message: str = ""
    budget: float | None = None
    source: str = "unknown"
    page: str = ""
    received_at: str = ""

    @classmethod
    def from_payload(cls, payload: dict, default_cc="+1") -> "Lead":
        return cls(
            name=clean(payload.get("name"), 120),
            email=clean(payload.get("email"), 200).lower(),
            phone=parse_phone(payload.get("phone"), default_cc),
            company=clean(payload.get("company"), 120),
            message=clean(payload.get("message") or payload.get("comments"), 4000),
            budget=parse_budget(payload.get("budget")),
            source=clean(payload.get("source"), 60) or "unknown",
            page=clean(payload.get("page") or payload.get("url"), 300),
            received_at=clean(payload.get("received_at"), 40) or datetime.now().isoformat(timespec="seconds"),
        )

    @property
    def first_name(self) -> str:
        if not self.name:
            return "there"
        word = self.name.split(" ")[0]
        return word.title() if word.isupper() or word.islower() else word


@dataclass
class Verdict:
    tier: str
    score: int
    reasons: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


def score_lead(lead: Lead, rules: dict) -> Verdict:
    """Points in, tier out. Every point that moved is explained in `reasons`."""
    scoring = rules["scoring"]
    score = 0
    reasons: list[str] = []
    flags: list[str] = []
    text = f"{lead.message} {lead.page}".lower()

    for word in scoring.get("buying_signals", []):
        if word.lower() in text:
            score += scoring["points"]["buying_signal"]
            reasons.append(f"buying signal: '{word}'")
            break

    for word in scoring.get("disqualifiers", []):
        if word.lower() in text:
            score += scoring["points"]["disqualifier"]
            reasons.append(f"disqualifier: '{word}'")
            flags.append("disqualified")
            break

    if lead.budget is not None:
        threshold = scoring["budget_threshold"]
        if lead.budget >= threshold:
            score += scoring["points"]["budget_over_threshold"]
            reasons.append(f"budget {lead.budget:.0f} >= {threshold}")
        else:
            reasons.append(f"budget {lead.budget:.0f} below {threshold}")

    if lead.phone:
        score += scoring["points"]["has_phone"]
        reasons.append("phone provided")

    domain = email_domain(lead.email)
    if not EMAIL_RE.match(lead.email):
        flags.append("email_invalid")
        reasons.append("email looks invalid")
    elif domain and domain not in FREE_MAIL:
        score += scoring["points"]["business_email"]
        reasons.append(f"business domain ({domain})")

    if len(lead.message) >= scoring["detailed_message_chars"]:
        score += scoring["points"]["detailed_message"]
        reasons.append("detailed message")

    if lead.company:
        score += scoring["points"]["company_named"]
        reasons.append("company named")

    score = max(0, min(100, score))
    tiers = rules["tiers"]
    if "disqualified" in flags:
        tier = "ignore"
    elif score >= tiers["hot"]:
        tier = "hot"
    elif score >= tiers["warm"]:
        tier = "warm"
    else:
        tier = "cold"
    return Verdict(tier=tier, score=score, reasons=reasons, flags=flags)


# ---------------------------------------------------------------- slots

def next_slots(rules: dict, count: int = 3, now: datetime | None = None) -> list[str]:
    """The next few bookable openings inside office hours, skipping weekends."""
    hours = rules["office_hours"]
    now = now or datetime.now()
    start_h, end_h = int(hours["start"]), int(hours["end"])
    step = timedelta(minutes=int(hours.get("slot_minutes", 30)))
    lead_time = timedelta(minutes=int(hours.get("earliest_after_minutes", 60)))
    workdays = set(hours.get("workdays", [0, 1, 2, 3, 4]))

    cursor = now + lead_time
    minute = (cursor.minute // 30 + 1) * 30
    cursor = cursor.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=minute)

    slots: list[str] = []
    guard = 0
    while len(slots) < count and guard < 500:
        guard += 1
        if cursor.weekday() not in workdays:
            cursor = datetime.combine(cursor.date() + timedelta(days=1), clock(start_h, 0))
            continue
        if cursor.time() < clock(start_h, 0):
            cursor = cursor.replace(hour=start_h, minute=0)
            continue
        if cursor.time() >= clock(end_h, 0):
            cursor = datetime.combine(cursor.date() + timedelta(days=1), clock(start_h, 0))
            continue
        slots.append(cursor.strftime("%a %d %b, %H:%M"))
        cursor += step
    return slots


# ---------------------------------------------------------------- reply

def render(template: str, lead: Lead, slots: list[str], rules: dict) -> str:
    bullets = "\n".join(f"  - {slot}" for slot in slots)
    return template.format(
        first_name=lead.first_name,
        name=lead.name or "there",
        company=lead.company or "your team",
        message=lead.message[:160],
        slots=bullets,                      # bulleted list, for e-mail
        slots_inline=" / ".join(slots),     # one line, for SMS
        agent=rules["business"]["agent_name"],
        business=rules["business"]["name"],
        phone=rules["business"].get("phone", ""),
    ).strip()


def handle(payload: dict, rules: dict, now: datetime | None = None) -> dict:
    """Score one lead and produce every action that should follow it."""
    started = time.perf_counter()
    lead = Lead.from_payload(payload, rules["business"].get("default_country_code", "+1"))
    verdict = score_lead(lead, rules)
    playbook = rules["playbooks"][verdict.tier]

    slots = next_slots(rules, playbook.get("offer_slots", 0), now) if playbook.get("offer_slots") else []
    actions: list[dict] = []

    if playbook.get("reply") and lead.email and "email_invalid" not in verdict.flags:
        actions.append({
            "type": "email",
            "to": lead.email,
            "subject": playbook["subject"].format(company=lead.company or "your enquiry",
                                                  business=rules["business"]["name"]),
            "body": render(playbook["reply"], lead, slots, rules),
        })

    if playbook.get("sms") and lead.phone:
        actions.append({"type": "sms", "to": lead.phone, "body": render(playbook["sms"], lead, slots, rules)})

    # A typo in the e-mail field is the cheapest way to lose a real customer.
    # If we cannot write to them but they left a number, fall back to SMS and
    # tell the owner why.
    email_broken = "email_invalid" in verdict.flags or not lead.email
    if email_broken and lead.phone and rules["business"].get("sms_fallback_when_email_invalid", True)             and verdict.tier != "ignore":
        actions.append({
            "type": "sms",
            "to": lead.phone,
            "body": render(rules["business"]["sms_fallback"], lead, slots, rules),
            "why": "email address is unusable",
        })
        actions.append({
            "type": "notify",
            "to": rules["business"]["owner_channel"],
            "body": f"{lead.name or 'Lead'} left a broken e-mail ({lead.email or 'empty'}) - "
                    f"reached out by SMS to {lead.phone}. Worth a call.",
        })

    if playbook.get("notify_owner"):
        actions.append({
            "type": "notify",
            "to": rules["business"]["owner_channel"],
            "body": (f"{verdict.tier.upper()} lead ({verdict.score}/100): {lead.name or 'no name'} "
                     f"<{lead.email}> {lead.company}. {lead.message[:120]}"),
        })

    if playbook.get("crm_stage"):
        actions.append({"type": "crm", "stage": playbook["crm_stage"], "owner": playbook.get("assign_to", "unassigned")})

    return {
        "lead": {
            "name": lead.name, "email": lead.email, "phone": lead.phone, "company": lead.company,
            "budget": lead.budget, "source": lead.source, "received_at": lead.received_at,
        },
        "tier": verdict.tier,
        "score": verdict.score,
        "reasons": verdict.reasons,
        "flags": verdict.flags,
        "slots_offered": slots,
        "actions": actions,
        "decided_in_ms": round((time.perf_counter() - started) * 1000, 2),
    }


# ---------------------------------------------------------------- output

def print_human(result: dict) -> None:
    lead = result["lead"]
    print(f"\n{lead['name'] or '(no name)'} <{lead['email']}>  {lead['company'] or ''}".rstrip())
    print(f"  tier   : {result['tier'].upper()}  ({result['score']}/100, decided in {result['decided_in_ms']} ms)")
    print(f"  because: {'; '.join(result['reasons']) or 'nothing scored'}")
    if result["slots_offered"]:
        print(f"  slots  : {', '.join(result['slots_offered'])}")
    if not result["actions"]:
        print("  actions: none - lead ignored on purpose")
    for action in result["actions"]:
        target = action.get("to") or action.get("stage", "")
        print(f"  -> {action['type']:<7} {target}")
        body = action.get("body", "")
        for line in body.splitlines()[:6]:
            print(f"       | {line}")
        if len(body.splitlines()) > 6:
            print("       | ...")


# ---------------------------------------------------------------- webhook

def serve(port: int, rules: dict) -> None:
    """Minimal webhook listener - no framework, so nothing to install."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                self.send_response(400)
                self.end_headers()
                return
            result = handle(payload, rules)
            body = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            print_human(result)

        def log_message(self, *_):  # keep the console readable
            pass

    print(f"listening on http://127.0.0.1:{port}/  (POST your form payloads here, Ctrl+C to stop)")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()


# ---------------------------------------------------------------- selftest

def selftest(rules: dict) -> int:
    """Checks the scoring and the slot maths without any external files."""
    checks, failures = 0, []

    def check(label, condition):
        nonlocal checks
        checks += 1
        if not condition:
            failures.append(label)

    hot = handle({"name": "Dana Ruiz", "email": "dana@meridian-logistics.example", "phone": "+1 415 555 0134",
                  "company": "Meridian Logistics", "budget": "about 6k",
                  "message": "We need a quote for automating our daily order export. Fairly urgent."}, rules)
    check("hot lead is tier hot", hot["tier"] == "hot")
    check("hot lead gets slots", len(hot["slots_offered"]) >= 1)
    check("hot lead emails the lead", any(a["type"] == "email" for a in hot["actions"]))
    check("hot lead pings the owner", any(a["type"] == "notify" for a in hot["actions"]))
    check("reply is personalised", "Dana" in hot["actions"][0]["body"])

    cold = handle({"name": "sam", "email": "sam@example.com", "message": "how much?"}, rules)
    check("thin lead is not hot", cold["tier"] in {"warm", "cold"})

    job = handle({"name": "Applicant", "email": "a@example.com",
                  "message": "I am looking for a job, sending my CV and resume."}, rules)
    check("job application is ignored", job["tier"] == "ignore")
    check("ignored lead triggers no email", not any(a["type"] == "email" for a in job["actions"]))

    bad = handle({"name": "Typo", "email": "typo(at)example.com", "message": "quote please"}, rules)
    check("invalid email is flagged", "email_invalid" in bad["flags"])
    check("no email action for invalid address", not any(a["type"] == "email" for a in bad["actions"]))

    typo_with_phone = handle({"name": "Marta Kelly", "email": "marta(at)shop.example",
                              "phone": "+353 1 555 8842", "message": "please send pricing"}, rules)
    check("broken e-mail falls back to SMS", any(a["type"] == "sms" for a in typo_with_phone["actions"]))
    check("owner is told why", any("broken e-mail" in a.get("body", "") for a in typo_with_phone["actions"]))

    check("budget parser handles 5k", parse_budget("about 5k") == 5000)
    check("budget parser handles $4,000", parse_budget("$4,000") == 4000)
    check("budget parser rejects junk", parse_budget("no idea") is None)
    check("phone parser normalises", parse_phone("00 44 20 7946 0958") == "+442079460958")

    friday_night = datetime(2026, 8, 21, 22, 30)          # Friday, after hours
    slots = next_slots(rules, 3, friday_night)
    check("slots skip the weekend", all("Sat" not in s and "Sun" not in s for s in slots))
    check("slots start inside office hours", slots and int(slots[0].split(", ")[1][:2]) >= rules["office_hours"]["start"])

    speed = handle({"email": "x@example.com", "message": "pricing"}, rules)["decided_in_ms"]
    check("decision is fast", speed < 50)

    print(f"selftest: {checks - len(failures)}/{checks} passed")
    for failure in failures:
        print("  FAILED:", failure)
    return 1 if failures else 0


# ---------------------------------------------------------------- cli

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Score, answer and route an inbound lead.")
    parser.add_argument("payload", nargs="?", help="JSON file with the form submission")
    parser.add_argument("--rules", type=Path, help="rules file (default: rules.yaml, else rules.example.yaml)")
    parser.add_argument("--demo", action="store_true", help="run every sample in samples/")
    parser.add_argument("--serve", type=int, metavar="PORT", help="listen for webhooks on this port")
    parser.add_argument("--json", action="store_true", help="print the raw result")
    parser.add_argument("--selftest", action="store_true", help="verify the rules engine and exit")
    args = parser.parse_args(argv)

    rules = load_rules(args.rules)

    if args.selftest:
        return selftest(rules)
    if args.serve:
        serve(args.serve, rules)
        return 0
    if args.demo:
        files = sorted((HERE / "samples").glob("*.json"))
        if not files:
            sys.exit("no samples found")
        for file in files:
            result = handle(json.loads(file.read_text(encoding="utf-8")), rules)
            print(f"\n=== {file.name}")
            print_human(result)
        return 0
    if not args.payload:
        parser.error("pass a JSON file, or use --demo / --serve / --selftest")

    result = handle(json.loads(Path(args.payload).read_text(encoding="utf-8")), rules)
    print(json.dumps(result, indent=2, ensure_ascii=False)) if args.json else print_human(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
