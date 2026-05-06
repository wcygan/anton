#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""PreToolUse guard: block kubectl reads that would expose Secret data.

Stops the two-mode leak we hit on 2026-05-06:
  1. Deliberate dump:  `kubectl get secret X -o jsonpath='{.data}'`
  2. Accidental dump:  `kubectl get secret X -o jsonpath='<malformed>'` —
     kubectl's error path serialises the entire object (incl. .data) into
     stderr.

Both share a signature: `kubectl ... get ... secret(s) ... -o <data-format>`.
The hook denies that signature uniformly. It does NOT try to read jsonpath
expressions to decide whether a given path "really" touches `.data` —
intent-detection is brittle, and kubectl's error path defeats it anyway.

The safe affordance for inspecting Secrets is `kubectl describe secret X`,
which prints byte counts (`password:  95 bytes`) without revealing values.
For ESO sync verification, the ExternalSecret's `Ready / secret synced`
condition is sufficient — no Secret read needed.

BLOCKS (exit 2):
  kubectl get secret(s) [-A | -n ns | <name>] -o yaml
  kubectl get secret(s) ...                    -o json
  kubectl get secret(s) ...                    -o jsonpath[=...]
  kubectl get secret(s) ...                    -o jsonpath-as-json[=...]
  kubectl get secret(s) ...                    -o jsonpath-file=...
  kubectl get secret(s) ...                    -o go-template[-file]=...
  kubectl get secret(s) ...                    -o custom-columns[-file]=...
  kubectl get secret(s) ...                    -o template=...
  Long form `--output=...` and no-space `-oyaml` / `-o=yaml` are equivalent.
  Resource forms covered: `secret`, `secrets`, `secret/<n>`, `secrets/<n>`,
  `secrets.v1`, fully-qualified `secrets.v1.`.

ALLOWS (exit 0):
  kubectl describe secret X            byte counts only
  kubectl get secret X                 NAME / TYPE / DATA columns, no values
  kubectl get secret X -o name         resource ref
  kubectl get secret X -o wide         no extra data
  kubectl get externalsecret X -o yaml status object, no secret values
  kubectl get pod X -o yaml            different resource
  Pipeline siblings: `kubectl get secret X -o name | xargs ...` is fine
                    because `-o name` is the dangerous-output check's
                    explicit allowlist.
  String literals: `git commit -m "kubectl get secret X -o yaml"` —
                   kubectl is not at a command-start position.
  Non-Bash tool calls and malformed JSON (fail-open).

OVERRIDE: when the operator explicitly needs the data (e.g., debugging an
ESO data-mismatch bug), prefix with `ANTON_ALLOW_SECRET_READ=1 `:
  ANTON_ALLOW_SECRET_READ=1 kubectl get secret X -n flux-system -o yaml

KNOWN LIMITATIONS:
  * Splits the command on `&&`, `||`, `;`, `|`, newline, and `$(` so that
    each pipeline segment is evaluated independently. Patterns inside
    string literals after one of those separators may false-positive
    (same as guard_destructive.py).
  * Does not catch indirect reads: `kubectl get secret X -o name |
    xargs kubectl get -o yaml` would slip through because no single
    segment names a Secret resource literally. The risk is low — the
    operator would have to deliberately construct it.
  * Does not catch secret reads via go-client / kubectl plugins / custom
    binaries. Out of scope.
"""
import json
import re
import sys

_TAIL = r"[^;&|\n`]{0,200}"

# Segment splitter: chain operators, pipes, newlines, and the opening
# of a `$(...)` substitution (its body is a fresh command context).
_SEGMENT_SEP = re.compile(r"&&|\|\||;|\||\n|\$\(")

# Anchored at segment start, with optional env-var prefix
# (`FOO=bar kubectl get ...`).
_KUBECTL_GET_SECRET = re.compile(
    r"^\s*(?:\w+=\S+\s+)*kubectl\b" + _TAIL + r"\bget\b" + _TAIL
    # Resource: secret/secrets, optional `.v1` API-group qualifier,
    # optional `/name` suffix.
    + r"\bsecrets?(?:\.v1)?(?:\b|/)"
)

# Output formats that can serialise Secret.data:
#   yaml, json, jsonpath[-as-json|-file], go-template[-file],
#   custom-columns[-file], template
# Notably absent (allowed): name, wide.
#
# Flag forms tolerated:
#   -o yaml      (space)
#   -o=yaml      (equals)
#   -oyaml       (no separator)
#   --output yaml
#   --output=yaml
_DANGEROUS_OUTPUT = re.compile(
    r"(?:^|\s)"
    r"(?:-o\s*=?\s*|--output(?:\s*=\s*|\s+))"
    r"(?:yaml|json|jsonpath(?:-as-json|-file)?|go-template(?:-file)?|"
    r"custom-columns(?:-file)?|template)\b"
)

_OVERRIDE_PREFIX = re.compile(r"^\s*ANTON_ALLOW_SECRET_READ=1\s+")


def _block(cmd_excerpt: str) -> int:
    print(
        "Blocked kubectl Secret read that would expose `.data` values.\n"
        f"→ Matched segment: {cmd_excerpt}\n"
        "→ For ESO sync verification, check the ExternalSecret status "
        "(`kubectl get externalsecret X -o jsonpath='{.status.conditions...}'`).\n"
        "→ For Secret content sanity-check, use `kubectl describe secret X` "
        "(prints byte counts without values).\n"
        "→ If the operator has explicitly authorised reading the data, "
        "prefix the command with `ANTON_ALLOW_SECRET_READ=1 ` "
        "(including the trailing space).",
        file=sys.stderr,
    )
    return 2


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    if data.get("tool_name") != "Bash":
        return 0

    cmd: str = (data.get("tool_input") or {}).get("command", "")
    if not cmd:
        return 0

    if _OVERRIDE_PREFIX.match(cmd):
        return 0

    for segment in _SEGMENT_SEP.split(cmd):
        if _KUBECTL_GET_SECRET.search(segment) and _DANGEROUS_OUTPUT.search(segment):
            excerpt = segment.strip()
            if len(excerpt) > 160:
                excerpt = excerpt[:157] + "..."
            return _block(excerpt)

    return 0


if __name__ == "__main__":
    sys.exit(main())
