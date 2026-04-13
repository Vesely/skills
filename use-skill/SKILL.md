---
name: use-skill
description: >
  Fetch and execute a remote skill on-the-fly without installing it permanently.
  Use when the user wants to try a skill once, run a skill from GitHub, use a remote skill without installing,
  or mentions "use-skill", "run remote skill", "try this skill", "fetch skill", "one-time skill",
  or provides a GitHub URL/shorthand pointing to a skill they want to execute.
  This is the go-to skill whenever someone wants to use a skill they haven't installed locally.
  Also use when the user mentions skills.sh or wants to search for available skills.
argument-hint: "<source> [skill-name] [-- args for the skill]"
arguments:
  - source
  - skill-name
  - args
---

# use-skill

Fetch a remote skill and execute it in the current session without installing it permanently. The skill is loaded, run, and discarded.

## Argument parsing

The user's input after `/use-skill` is flexible. Parse it using these rules in order:

### Format 1: Direct URL to SKILL.md
```
/use-skill https://raw.githubusercontent.com/owner/repo/main/skills/my-skill/SKILL.md
```
**Detection:** URL ends with `SKILL.md`.
**Action:** Fetch the URL directly with curl.

### Format 2: Full GitHub repo URL + optional skill name
```
/use-skill https://github.com/owner/repo skill-name
/use-skill https://github.com/owner/repo --skill skill-name
/use-skill https://github.com/owner/repo
```
**Detection:** Starts with `https://github.com/`.
**Action:** Extract `owner/repo` from the URL. If a skill name follows, resolve it. Otherwise list available skills in the repo and ask the user to pick.

### Format 3: GitHub shorthand + skill name
```
/use-skill anthropics/skills frontend-design
/use-skill owner/repo skill-name -- build a landing page
```
**Detection:** First argument contains exactly one `/` and does NOT start with `http`.
**Action:** Treat as `owner/repo`. Next argument is the skill name. Everything after `--` is the task for the fetched skill.

### Format 4: Skill name only (skills.sh search)
```
/use-skill frontend-design
/use-skill frontend-design -- build a landing page
```
**Detection:** First argument has no `/` and doesn't start with `http`.
**Action:** Search skills.sh registry. Everything after `--` is the task for the fetched skill.

## Resolution logic

### Resolving from a GitHub repo

Given `owner/repo` and optionally `skill-name`:

**If skill-name is provided**, try fetching in this order (stop at first HTTP 200):
```
https://raw.githubusercontent.com/{owner}/{repo}/main/skills/{skill-name}/SKILL.md
https://raw.githubusercontent.com/{owner}/{repo}/main/{skill-name}/SKILL.md
https://raw.githubusercontent.com/{owner}/{repo}/master/skills/{skill-name}/SKILL.md
https://raw.githubusercontent.com/{owner}/{repo}/master/{skill-name}/SKILL.md
```

**If no skill-name**, discover available skills via GitHub API:
```bash
curl -s "https://api.github.com/repos/{owner}/{repo}/contents/skills" \
  -H "Accept: application/vnd.github.v3+json"
```
Parse JSON for directory entries (`type: "dir"`). Present as a numbered list, ask user to pick, then fetch that skill's SKILL.md.

If `skills/` doesn't exist, try the repo root.

### Resolving by name via skills.sh

The skills.sh registry (by Vercel Labs) indexes skills from across the ecosystem. Use its search API:

```bash
curl -s "https://skills.sh/api/search?q={skill-name}"
```

The response looks like:
```json
{
  "query": "frontend-design",
  "skills": [
    {
      "id": "anthropics/skills/frontend-design",
      "skillId": "frontend-design",
      "name": "frontend-design",
      "installs": 45000,
      "source": "anthropics/skills"
    },
    {
      "id": "pbakaus/impeccable/frontend-design",
      "skillId": "frontend-design",
      "name": "frontend-design",
      "installs": 12000,
      "source": "pbakaus/impeccable"
    }
  ],
  "count": 5
}
```

**Resolution rules:**

1. **Single result** — use it directly. Extract `source` (owner/repo) and `skillId`, then fetch from GitHub.

2. **Multiple results with an exact name match** — if exactly one result has `skillId` matching the query exactly AND it has significantly more installs than alternatives, use it. Otherwise present options.

3. **Multiple results** — present them as a numbered list sorted by installs (most popular first), showing the source and install count:
   ```
   Found 3 skills matching "frontend-design":
     1. anthropics/skills/frontend-design (45,000 installs)
     2. pbakaus/impeccable/frontend-design (12,000 installs)
     3. someuser/repo/frontend-design (500 installs)
   Which one? (enter number)
   ```
   Wait for user to pick.

4. **No results** — tell the user: "No skills found matching '{skill-name}' on skills.sh. Try a different name or provide a GitHub URL directly."

Once a skill is selected from search results, extract `source` as `owner/repo` and `skillId` as the skill name, then resolve via the GitHub repo resolution logic above.

## Fetching the skill

Once you have the final URL to SKILL.md:

```bash
SKILL_CONTENT=$(curl -sf "{url}" 2>/dev/null)
```

If the fetch fails:
- **404**: "Skill not found at {url}. Check the skill name and repo."
- **Rate limit (403)**: "GitHub rate limit hit. Try providing a direct raw URL instead."
- **Other**: Show the HTTP status and URL.

## Executing the fetched skill

Once SKILL.md content is fetched:

1. **Show a brief status line:**
   ```
   Fetched "{skill-name}" from {source}. Running...
   ```

2. **Parse the frontmatter** to understand the skill's name and capabilities.

3. **Follow the skill's instructions exactly** as if it were a locally installed skill. Use the tools it specifies, produce the outputs it defines, follow its workflow.

4. **Pass through arguments.** Everything after `--` (or extra args after the skill-name) becomes the task/prompt for the fetched skill.

5. **Do NOT persist the skill.** Don't write it to disk or install it. If the user wants to keep it, suggest:
   ```
   To install permanently: npx skills add {source}
   ```

## Handling skill dependencies

Skills sometimes reference bundled files (scripts/, references/, assets/). When the skill instructions mention reading a file from a relative path:

1. Construct the full raw GitHub URL using the same base path where SKILL.md was found.
2. Fetch the referenced file with curl.
3. If a referenced file can't be fetched, inform the user and continue with what's available — the core instructions in SKILL.md are usually self-contained enough to be useful.

## Edge cases

- **Rate limiting**: GitHub API allows 60 unauthenticated requests/hour. The skills.sh API has its own limits. If rate-limited, suggest the user provide a direct URL.
- **Private repos**: Suggest the user clone locally or provide a raw URL with a token.
- **skills.sh URL format**: If the user provides a skills.sh URL like `https://skills.sh/package/github/owner/repo/skill-name`, extract `owner/repo` and `skill-name` from the path and resolve via GitHub.

## Examples

```
/use-skill frontend-design -- build a SaaS pricing page
→ Searches skills.sh for "frontend-design"
→ Picks top result (or asks user if ambiguous)
→ Fetches SKILL.md from GitHub
→ Executes with task "build a SaaS pricing page"

/use-skill anthropics/skills frontend-design
→ Fetches directly from anthropics/skills repo
→ Executes the skill, asks what user wants to do

/use-skill https://github.com/anthropics/skills
→ Lists all skills in the repo
→ User picks one → fetches and executes

/use-skill https://raw.githubusercontent.com/user/repo/main/skills/cool/SKILL.md -- do the thing
→ Direct fetch, no resolution needed
→ Executes with task "do the thing"

/use-skill https://skills.sh/package/github/anthropics/skills/frontend-design
→ Extracts owner/repo/skill from URL
→ Fetches from GitHub and executes
```
