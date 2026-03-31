# Skills

A collection of Claude Code skills for file hosting, disposable email, supply-chain security, skill creation, and more.

## Install

```
npx skills@latest add Vesely/skills/<skill-name>
```

Or via [skills.sh](https://skills.sh).

## Skills

### Utilities

- **catbox** — Upload files to catbox.moe for free, anonymous hosting with direct links. No account needed.

  ```
  npx skills@latest add Vesely/skills/catbox
  ```

- **temp-email** — Create disposable email inboxes via tempmail.lol. Rotating domains, no API key, just curl. Great for E2E tests and verification flows.

  ```
  npx skills@latest add Vesely/skills/temp-email
  ```

### Security

- **supply-chain-protection** — One-time setup to harden dependency management against supply-chain attacks. Detects your package manager (npm, pnpm, Yarn, Bun), installs Socket Firewall, configures a 48-hour minimum package release age, and writes persistent rules to CLAUDE.md.

  ```
  npx skills@latest add Vesely/skills/supply-chain-protection
  ```

### Meta

- **skillify** — Capture a session's repeatable process into a reusable SKILL.md file. Interactive interview-based workflow to turn any process into an installable skill.

  ```
  npx skills@latest add Vesely/skills/skillify
  ```
