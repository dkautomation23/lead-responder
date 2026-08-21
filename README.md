# lead-responder

Answers an inbound lead **in under a second** — scores it, writes a personal
reply, offers real call slots, escalates the good ones and quietly files the
job applications and SEO pitches.

```bash
python respond.py --demo
```

## Why

Most small businesses answer web enquiries whenever someone next opens the
inbox: after lunch, next morning, Monday. By then the person has messaged three
competitors. The fix is not a bigger CRM, it is answering while they are still
on the page — and not spending that speed on the spam that arrives with it.

This is the piece that does the answering. It is deliberately dumb: rules in a
YAML file, no model calls, no monthly cost, output you can read and argue with.

## What it does

- **Scores** the lead: buying words in the message, budget, business e-mail
  domain, phone present, how much they wrote, whether they named a company.
- **Filters** the noise: job applications, guest-post and backlink pitches score
  themselves out and get no reply at all.
- **Replies** with a template that uses their name, their company and their words.
- **Offers slots** that actually exist — inside office hours, never on a weekend,
  never in the next 60 minutes.
- **Escalates** hot leads to the owner by SMS and a notification.
- **Falls back to SMS** when someone typos their e-mail but leaves a number.
  That single case pays for the whole script.
- **Explains itself**: every result lists why each point was given.

Actions come out as structured JSON — hand them to whatever actually sends
(Twilio, SendGrid, n8n, your CRM). Nothing is sent from here, so you can dry-run
the whole thing safely.

## Sample output

```console
$ python respond.py samples/lead_hot.json

Dana Ruiz <dana.ruiz@meridian-logistics.com>  Meridian Logistics
  tier   : HOT  (100/100, decided in 0.09 ms)
  because: buying signal: 'quote'; budget 6000 >= 2000; phone provided;
           business domain (meridian-logistics.com); detailed message; company named
  slots  : Mon 24 Aug, 09:00, Mon 24 Aug, 09:30, Mon 24 Aug, 10:00
  -> email   dana.ruiz@meridian-logistics.com
       | Hi Dana,
       |
       | Thanks for reaching out - I read your message and this is something we do
       | often, so I can get you a straight answer quickly.
       |
       | I have kept these times open for a 20-minute call:
       | ...
  -> sms     +14155550134
       | Hi Dana, Alex from Northgate Automation here - got your enquiry and can
       | talk today. Times: Mon 24 Aug, 09:00 / Mon 24 Aug, 09:30. Reply with one.
  -> notify  sales@northgate.example
  -> crm     Qualified - call offered
```

The same run on an SEO pitch:

```console
Growth Team <outreach@rank-fast.example>
  tier   : IGNORE  (0/100, decided in 0.09 ms)
  because: disqualifier: 'guest post'
  actions: none - lead ignored on purpose
```

And on someone who mistyped their address:

```console
Marta Kelly <marta.kelly(at)brightside.example>  Brightside Retail
  tier   : WARM  (55/100)
  because: buying signal: 'pricing'; phone provided; email looks invalid; company named
  -> sms     +35315558842   (e-mail address is unusable)
  -> notify  sales@northgate.example
       | Marta Kelly left a broken e-mail - reached out by SMS. Worth a call.
```

## Install

```bash
git clone https://github.com/dkautomation23/lead-responder.git
cd lead-responder
pip install -r requirements.txt
cp rules.example.yaml rules.yaml     # then edit the wording and thresholds
python respond.py --selftest         # 19 checks, no network
```

Python 3.10+, one dependency (PyYAML).

## Wiring it up

```bash
python respond.py --serve 8080
```

Point your form, Typeform, Webflow or n8n webhook at
`http://your-host:8080/` and it answers with the full decision as JSON. The
listener is `http.server` from the standard library — fine behind nginx or a
tunnel for a pilot, not something to expose raw to the internet.

For a cron-style setup, pipe files instead:

```bash
python respond.py new_lead.json --json | your-sender
```

## Tuning it

Everything lives in `rules.yaml`:

| Section | What you change there |
| --- | --- |
| `business` | your name, the sender's name, the number in the templates, where hot leads are announced |
| `office_hours` | opening hours, slot length, how soon a call may be offered, which days count |
| `tiers` | the score needed to be hot or warm |
| `scoring` | buying words, disqualifiers, budget threshold, and what each signal is worth |
| `playbooks` | the actual e-mail and SMS wording per tier, CRM stage, who gets assigned |

Change the words, not the code. `--selftest` will tell you if a change broke
the routing.

## Honest limits

- Keyword scoring, not language understanding: someone who writes "I need help"
  with no other signal lands in warm, not hot. Adding the phrases your customers
  actually use is the tuning step, and it is worth doing after the first week.
- Slots are generated from office hours, not from a real calendar. Wire it to
  Google Calendar free/busy before promising exact times.
- Sending is out of scope on purpose — this decides, your existing stack
  delivers.
- No storage: one lead in, one decision out. Persistence belongs in your CRM.

## License

MIT
