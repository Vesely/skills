#!/usr/bin/env python3
"""Check every SKILL.md parses the way `npx skills add` will parse it.

A skill with invalid frontmatter is not a broken skill, it is an *absent* one:
the installer prints "Skipped ... YAML parse error" and carries on, so the
failure never shows up here, only on whoever tried to install it. That is how
an unquoted `Variant: dyslexia-friendly ...` sat in tldr's description for
weeks -- YAML reads the ": " inside a plain scalar as a nested mapping, so the
whole file was dropped and `skills add Vesely/skills/tldr` found nothing.

ERRORs mirror skills@1.5.x parseSkillMd(), the code path `skills add` uses:
frontmatter block -> YAML parse -> name and description present and strings.
Anything flagged as an error will not install.

WARNs are the registry-index rules (isValidSkillName, 1024-char description)
from the same CLI. Those only apply when publishing through a
.well-known/agent-skills/index.json, so they do not fail the run -- both
oversized descriptions here install and load fine today.

PyYAML is used when it imports, but the ": " lint runs either way and points
at the offending column, which a generic parser error does not.
"""

import re
import sys
from pathlib import Path

# The CLI's own frontmatter regex. Notably it tolerates CRLF and a missing
# trailing newline, so matching it exactly avoids flagging files it accepts.
FRONTMATTER = re.compile(r"^---\r?\n([\s\S]*?)\r?\n---\r?\n?", re.MULTILINE)
KEY_LINE = re.compile(r"^([A-Za-z0-9_.-]+):(?:[ \t]+(.*))?$")
BLOCK_SCALAR = re.compile(r"^[|>][+\-0-9]*$")
VALID_NAME = re.compile(r"^[a-z0-9-]+$")

MAX_NAME = 64
MAX_DESCRIPTION = 1024


class Report:
    def __init__(self):
        self.errors = 0
        self.warnings = 0

    def error(self, where, message, detail=None):
        self.errors += 1
        print(f"\033[31m✗\033[0m {where}  {message}")
        if detail:
            print(detail)

    def warn(self, where, message):
        self.warnings += 1
        print(f"\033[33m!\033[0m {where}  {message}")


def point_at(value, column, width=76):
    """Excerpt around a column with a caret under it, for long descriptions."""
    start = max(0, column - width // 2)
    excerpt = value[start:start + width]
    prefix = "..." if start else ""
    suffix = "..." if start + width < len(value) else ""
    return f"    {prefix}{excerpt}{suffix}\n" + " " * (4 + len(prefix) + column - start) + "^"


def lint_plain_scalars(body, path, report):
    """Flag the traps that silently drop or truncate a plain (unquoted) value.

    Walks top-level keys, tracking block scalars and multi-line plain values so
    their continuation lines get checked too -- an indented `foo: bar` under a
    plain description breaks it exactly the same way.
    """
    lines = body.split("\n")
    key = None          # top-level key whose plain value we are still inside
    in_block = False    # inside a `|`/`>` scalar, where ": " is harmless

    for i, line in enumerate(lines, start=2):  # +2: `---` is line 1
        indented = line[:1] in (" ", "\t")
        if not line.strip():
            continue

        if not indented:
            match = KEY_LINE.match(line)
            if not match:
                key, in_block = None, False
                continue
            name, value = match.group(1), match.group(2) or ""
            in_block = bool(BLOCK_SCALAR.match(value))
            quoted = value[:1] in ('"', "'")
            key = None if (in_block or quoted or not value) else name
            offset = len(name) + 2
        elif in_block or key is None:
            continue
        else:
            offset = 0  # continuation of a multi-line plain scalar

        if key is None:
            continue

        text = line[offset:] if not indented else line.lstrip()
        colon = text.find(": ")
        if colon != -1 or text.endswith(":"):
            column = colon if colon != -1 else len(text) - 1
            report.error(
                f"{path}:{i}",
                f'plain value for `{key}` contains ": " — YAML reads it as a nested mapping',
                point_at(text, column) + "\n    fix: use a `>-` block scalar, quote the"
                " value, or write the colon as an em dash",
            )
        comment = text.find(" #")
        if comment != -1:
            report.warn(
                f"{path}:{i}",
                f'plain value for `{key}` contains " #" — YAML truncates it there'
                f" (keeps {comment} of {len(text)} chars)",
            )


def check(skill_md, report):
    path = f"{skill_md.parent.name}/{skill_md.name}"
    raw = skill_md.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        report.error(path, "starts with a UTF-8 BOM, which breaks the `---` match")
        return
    text = raw.decode("utf-8")

    match = FRONTMATTER.match(text)
    if not match:
        report.error(path, "no `---` frontmatter block: installer sees no name or description")
        return
    body = match.group(1)

    if "\t" in body:
        report.error(path, "tab character in frontmatter (YAML forbids tabs for indentation)")

    before = report.errors
    lint_plain_scalars(body, path, report)
    pinpointed = report.errors > before

    try:
        import yaml
    except ImportError:
        data = None
    else:
        try:
            data = yaml.safe_load(body)
        except yaml.YAMLError as err:
            # The lint above already named the line and column; the parser's own
            # message adds nothing except a second entry in the error count.
            if not pinpointed:
                report.error(path, f"YAML parse error: {str(err).splitlines()[0]}")
            return
        if not isinstance(data, dict):
            report.error(path, f"frontmatter is not a mapping (parsed as {type(data).__name__})")
            return

    if data is None:  # no PyYAML: fall back to the top-level keys we can see
        data = {m.group(1): (m.group(2) or "") for m in
                (KEY_LINE.match(l) for l in body.split("\n")) if m}

    for field in ("name", "description"):
        value = data.get(field)
        if not value:
            report.error(path, f"missing required frontmatter field: {field}")
        elif not isinstance(value, str):
            report.error(path, f"`{field}` must be a string, got {type(value).__name__}")

    name, description = data.get("name"), data.get("description")
    if isinstance(name, str) and name:
        if name != skill_md.parent.name:
            report.warn(path, f"name `{name}` does not match directory `{skill_md.parent.name}`")
        if not VALID_NAME.match(name) or name.startswith("-") or name.endswith("-") or "--" in name:
            report.warn(path, f"name `{name}` is not registry-safe (lowercase, digits, single hyphens)")
        if len(name) > MAX_NAME:
            report.warn(path, f"name is {len(name)} chars, registry limit is {MAX_NAME}")
    if isinstance(description, str) and len(description) > MAX_DESCRIPTION:
        report.warn(path, f"description is {len(description)} chars, registry limit is {MAX_DESCRIPTION}")


def install_hook(root):
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.write_text(
        "#!/bin/sh\n"
        "# Installed by scripts/validate-skills.py --install-hook\n"
        '# Skip rather than block on branches that predate the validator.\n'
        'validator="$(git rev-parse --show-toplevel)/scripts/validate-skills.py"\n'
        '[ -f "$validator" ] || exit 0\n'
        'exec python3 "$validator"\n'
    )
    hook.chmod(0o755)
    print(f"installed {hook}")


def main():
    root = Path(__file__).resolve().parent.parent
    args = sys.argv[1:]
    if "--install-hook" in args:
        install_hook(root)
        return 0

    paths = [Path(a) for a in args] or sorted(root.glob("*/SKILL.md"))
    report = Report()
    for skill_md in paths:
        check(skill_md, report)

    counts = f"{len(paths)} skills, {report.errors} errors, {report.warnings} warnings"
    if report.errors:
        print(f"\n\033[31m{counts}\033[0m — errored skills will not install")
    else:
        print(f"\n\033[32m✓\033[0m {counts}")
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
