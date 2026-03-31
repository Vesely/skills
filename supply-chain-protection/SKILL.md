---
name: supply-chain-protection
description: >
  One-time setup of supply-chain protections for a project. Detects the package manager,
  installs Socket Firewall (sfw), configures a 48-hour minimum package release age,
  and writes persistent dependency rules to CLAUDE.md.
  Trigger phrases: "supply chain protection", "secure dependencies", "setup sfw",
  "dependency protection", "supply chain security".
allowed-tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Bash(npm:*)
  - Bash(npx:*)
  - Bash(sfw:*)
  - Bash(which:*)
  - Bash(command:*)
  - Bash(cat:*)
context: fork
---

# Supply-Chain Protection Setup

One-time project setup to harden dependency management against supply-chain attacks.

## Goal

Configure the repository so all dependency operations use Socket Firewall (`sfw`) and enforce a 48-hour minimum release age policy on packages.

## Steps

### 1. Detect Package Manager

Inspect the repository root for lockfiles and config:

| Signal | Package Manager |
|---|---|
| `pnpm-lock.yaml` | pnpm |
| `yarn.lock` or `.yarnrc.yml` | Yarn |
| `bun.lock` / `bun.lockb` / `bunfig.toml` | Bun |
| `package-lock.json` | npm |

If multiple signals exist, pick the one actually used in scripts / CI. Report the decision before proceeding.

**Success criteria**: Package manager identified and stated.

### 2. Install Socket Firewall

- Run `command -v sfw` to check if `sfw` is already available.
- If missing, install globally: `npm install -g @socketsecurity/cli`
- Verify with `sfw --version`.

**Success criteria**: `sfw` command is available and version is confirmed.

### 3. Configure 48-Hour Minimum Release Age

Apply native config for the detected package manager. Preserve existing content in all config files.

**pnpm** — update `pnpm-workspace.yaml`:
```yaml
onlyBuiltDependenciesFile: ... # keep existing
minimumReleaseAge: 2880
```

**Yarn** — update `.yarnrc.yml`:
```yaml
npmMinimalAgeGate: "2d"
```

**Bun** — update `bunfig.toml`:
```toml
[install]
minimumReleaseAge = 172800
```

**npm** — no native setting exists. Skip config changes; the limitation will be noted in CLAUDE.md. Rely on `sfw` plus manual version-age checks.

**Rules**:
- Do not invent settings the package manager does not support.
- Do not remove unrelated existing config.
- Preserve formatting when practical.

**Success criteria**: Config file updated (or skipped for npm) with the correct minimum-age setting.

### 4. Update CLAUDE.md

Create or update `CLAUDE.md` in the project root. If the file exists, append the section; do not overwrite existing content. Add exactly this section (substitute detected values):

````markdown
## Dependency Supply-Chain Protection

### Rules

1. **Always prefix dependency commands with `sfw`.**
   Examples: `sfw pnpm add`, `sfw yarn add`, `sfw bun add`, `sfw npm install`.
   Applies to install, update, remove, and any command that changes dependencies.

2. **Respect the 48-hour minimum release age.**
   If the package manager enforces it natively, honor the config.
   If not (e.g. npm), manually verify the publish date of the target version
   and refuse versions newer than 48 hours.

3. **Prefer mature versions.** When the latest version is too new, pick the
   newest version that is at least 48 hours old.

4. **Do not bypass these protections** unless the human explicitly instructs it.
   If asked to bypass, explain which protection is skipped and the added risk.

5. **Minimize new dependencies.** Prefer built-in APIs or already-installed
   packages. Avoid packages for trivial tasks.

6. **Keep lockfiles consistent** with the project's chosen package manager.

### Operational Notes

- Package manager: `{{DETECTED_PM}}`
- Release-age config: `{{CONFIG_FILE_OR_NONE}}`
- Enforcement: `{{native | manual (sfw + age check)}}`
````

**Success criteria**: CLAUDE.md contains the supply-chain section with correct operational notes.

### 5. Summary

Output a concise summary:
- Detected package manager
- Whether `sfw` was installed or already present
- Which config file was changed (or "none" for npm)
- How the 48-hour rule is enforced
- Any limitations

**Success criteria**: User sees a clear summary of all changes.
