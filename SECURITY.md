# Security Policy

## Supported Versions

There are no tagged releases yet. Only the latest commit on `main` is
supported. If you are running an older commit, update to the latest `main`
before reporting.

## Reporting a Vulnerability

Report privately, not as a public issue:

- Preferred: GitHub's Private Vulnerability Reporting — open the repo's
  **Security** tab and click **"Report a vulnerability"**.
- If that option is not available to you: email hello@dkautomation.dev.

Do not open a public issue for a suspected vulnerability.

You will get a first response within 3 business days.

A good report includes:

- Steps to reproduce, ideally a minimal `payload` JSON that triggers it (see
  `samples/` for the shape a payload takes).
- The affected file and function, e.g. `respond.py:render`.
- The impact: what an attacker gains, and who is exposed — the business
  running this, the lead, or both.

## Scope

`respond.py` takes an inbound lead payload (name, email, phone, company,
message, budget, source, page) that nobody has authenticated, scores it, and
turns it into outgoing actions: an email, an SMS, an owner notification, a
CRM stage. The boundary that matters here is that lead-supplied fields are
content, not control data. They may end up quoted in a reply; they must never
decide who receives a message.

### Treated as a vulnerability here

- A crafted `name`, `company`, `message`, `budget`, `source`, or `page` value
  that changes the `to` address of an email or SMS action built by `handle()`,
  instead of only affecting scoring or the wording of a reply.
- A crafted lead field that adds a second recipient, a CC/BCC, or extra
  headers to an email or SMS action produced by `render()` / `handle()`.
- A crafted lead field that reaches or overrides
  `rules["business"]["owner_channel"]` (the notification target for hot leads
  and broken-email fallbacks) — that address must only ever come from the
  loaded rules file, never from the payload.
- A crafted `email` or `phone` value that gets past `clean()`, `EMAIL_RE`, or
  `parse_phone()` and still ends up as the `to` of an outgoing action while
  carrying something other than a plain address or number — embedded
  whitespace, control characters, or a second address.
- Any path by which `respond.py` sends a generated message to an address that
  did not come from that same lead's own `email` or `phone` field.

### Not treated as a vulnerability here

- The reply or SMS body quoting back the lead's own `name`, `company`, or
  `message`. `render()` only ever substitutes lead data as `str.format()`
  values into a template string that comes from `rules.yaml`, never as the
  template itself, so this is expected personalization, not injection. If the
  wording looks wrong, report it as a normal bug, not a security issue.
- A lead landing in the wrong tier (`hot` / `warm` / `cold` / `ignore`)
  because of weak keyword scoring — that is a `rules.yaml` tuning problem,
  already covered in the README's "Honest limits", not a vulnerability.
- Exposing the `--serve` listener directly to the internet without a reverse
  proxy — the README already states it belongs behind nginx or a tunnel, not
  taking raw traffic.
