# supply-chain-protection

One-time setup to harden dependency management against supply-chain attacks. Detects your package manager (npm, pnpm, Yarn, Bun), installs Socket Firewall, configures a 48-hour minimum package release age, and writes persistent rules to CLAUDE.md.

## Install

```
npx skills@latest add Vesely/skills/supply-chain-protection
```
