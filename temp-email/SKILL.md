---
name: temp-email
description: >
  Create and manage temporary/disposable email inboxes via tempmail.lol API (no dependencies, just curl).
  Use whenever the user needs a throwaway email — E2E testing, account registration, email verification,
  OTP confirmation, or any disposable inbox scenario. Triggers on: "temp email", "temporary email",
  "disposable email", "dočasný email", "dočasná schránka", "throwaway email", "fake email for testing",
  or when a task implies needing a temporary email (e.g. "sign up for X and verify", "test the registration flow").
---

# Temporary Email (tempmail.lol)

Disposable email inboxes via `curl`. No dependencies, no API key. Domains rotate automatically so addresses are unlikely to be blocklisted.

## Create inbox

```bash
INBOX=$(curl -s -X POST https://api.tempmail.lol/v2/inbox/create)
EMAIL=$(echo "$INBOX" | jq -r .address)
TOKEN=$(echo "$INBOX" | jq -r .token)
echo "Email: $EMAIL"
```

Save both `EMAIL` and `TOKEN` — you need the token to check messages.

## Check messages

```bash
curl -s "https://api.tempmail.lol/v2/inbox?token=$TOKEN" | jq
```

Returns `{"emails": [...], "expired": false}`. Each email has `from`, `subject`, `body` (HTML), and `date`.

## Poll for a message (wait up to 60s)

```bash
for i in $(seq 1 12); do
  MSGS=$(curl -s "https://api.tempmail.lol/v2/inbox?token=$TOKEN")
  COUNT=$(echo "$MSGS" | jq '.emails | length')
  if [ "$COUNT" -gt 0 ]; then
    echo "$MSGS" | jq '.emails'
    break
  fi
  [ $i -lt 12 ] && sleep 5
done
```

## Extract verification link or OTP

After receiving a message, parse the `body` field (HTML):

- **Verification URLs**: grep for `href=` containing `verify`, `confirm`, `activate`, `token=`, `code=`, `magic`, `login`
- **OTP codes**: look for standalone 4-8 digit numbers near words like "code", "kód", "verification"

```bash
# Example: extract first URL with verify/confirm
echo "$MSGS" | jq -r '.emails[0].body' | grep -oP 'href="[^"]*(?:verify|confirm|activate|token=|code=)[^"]*"'
```

## Notes

- Domains rotate (hush2u.com, leadharbor.org, cloudvxz.com, etc.) — never hardcode them.
- Inboxes expire after ~10 minutes of inactivity.
- For E2E tests: create at test start, poll during verification step, no explicit cleanup needed (auto-expires).
