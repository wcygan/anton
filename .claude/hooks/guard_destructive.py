#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""PreToolUse guard: block destructive Bash commands without explicit override.

SIMPLE PATTERN GUARD, NOT a shell parser. Matches regex patterns against the
raw command string and blocks with exit 2 on a hit. Design rule: prefer false
negatives (miss a destructive command) over false positives (block routine
work). A hook that wedges the session on every long kubectl call or blocks
`git commit -m "docs: kubectl delete namespace notes"` is worse than no hook
at all.

Canonical blocklist source is CLAUDE.md "Hard rules" plus bootstrap/CLAUDE.md
for `helmfile destroy` and the talos bootstrap footguns.

BLOCKS (exit 2):
  task talos:reset            wipes the cluster
  talosctl reset              wipes a Talos node
  talosctl apply-config       blocked unless --mode / -m is present
  kubectl delete {namespace|ns|pv|pvc|crd|customresourcedefinition}
                              (+ plural forms: namespaces, pvs, pvcs, crds...)
  kubectl drain --delete-emptydir-data
                              destroys emptyDir volumes on the drained node
  helmfile destroy            nukes every bootstrap Helm release
  flux uninstall              tears down the GitOps operator
  flux suspend                blocked unless scoped with -n / --namespace / -A
  rm -rf / -fr / --recursive --force at filesystem roots
                              (/, /*, ~, $HOME, /Users/<user>/)

ALLOWS (exit 0):
  * `ANTON_DESTRUCTIVE_OK=1 <command>` — PREFIX ONLY. An interior match
    like `echo ANTON_DESTRUCTIVE_OK=1; task talos:reset` does NOT bypass.
  * Read-only kubectl / talosctl / flux verbs (get, describe, logs, etc.)
  * Narrow-scope deletes: `kubectl delete pod foo`, `kubectl delete deployment`
  * `kubectl delete -f manifest.yaml` — can't read the manifest from here;
    the user has to review it
  * Scoped flux suspend: `flux suspend ks foo -n bar` / `--namespace=bar` / `-A`
  * talosctl apply-config with `--mode=auto` / `-m auto` / etc.
  * `rm -rf /tmp/foo` and any non-root recursive rm
  * A destructive pattern appearing INSIDE a string literal passed to a
    non-destructive program: `echo "kubectl delete ns foo"`,
    `git commit -m "docs: talos reset"`, `grep "kubectl delete namespace"`.
    See COMMAND-START ANCHOR below.
  * Non-Bash tool calls and malformed JSON (fail-open)

OVERRIDE: when the user has explicitly authorized a destructive op, prefix
the command with `ANTON_DESTRUCTIVE_OK=1 ` (note the trailing space):
  ANTON_DESTRUCTIVE_OK=1 kubectl delete namespace test-ns

COMMAND-START ANCHOR: every pattern requires the destructive binary to sit at
a "command start" position — the start of the whole command, or immediately
after a chain/pipe/newline/subshell separator (`&& || ; | \\n $(`), with an
optional leading env-var prefix (`FOO=bar task ...`). This is what lets
`echo "kubectl delete ns foo"` and `git commit -m "kubectl delete ns foo"`
pass: the `kubectl` sits inside a string literal, not at a command-start
position, so no pattern matches.

KNOWN LIMITATIONS — this hook will MISS:
  * Variable expansion: `X=reset; task talos:$X`
  * Command substitution: `task $(echo talos):reset`
  * eval / source / bash -c "<destructive>" / base64-decoded payloads
  * Aliases, functions, wrapper scripts whose names we don't match
  * Destructive commands inside manifests passed to `kubectl apply -f`
  * Flag interposition past the 200-char bounded tail between binary and verb

KNOWN LIMITATIONS — this hook will FALSE-POSITIVE on:
  * A destructive literal inside a heredoc body — newlines count as chain
    separators, so `cat <<EOF\\nkubectl delete ns foo\\nEOF` WILL block.
    Break up the literal, or use the override prefix.
  * A destructive literal after an in-string `;` / `|`: `echo "x;task talos:reset"`.
    Contrived; break up the literal or use the override.

ADDING A PATTERN: append to DESTRUCTIVE_PATTERNS as (compiled regex, reason).
Prepend `_CMD_START` to require the binary to sit at a command-start position,
and use `_TAIL` between a binary and its destructive verb if flag interposition
is realistic. Reason style: "<what it destroys>. Confirm with the user first."
"""
import json
import re
import sys

# Command-start anchor: pattern must match at the beginning of the command,
# or immediately after a chain/pipe/subshell separator, with an optional
# env-var prefix (`FOO=bar task ...`). This is a substring of a shell
# parser's job — enough to separate `echo "destructive"` (no) from
# `echo x && destructive` (yes) without trying to track quote state.
_CMD_START = r"(?:^|[;&|\n]|\$\()\s*(?:\w+=\S+\s+)*"

# Bounded tail between a binary and its destructive verb, to tolerate
# common flag interposition like `kubectl --context foo delete ns bar`
# without enabling catastrophic backtracking. The negated character class
# excludes command-chain separators so a pattern can't span `&&` or `;`.
# 200 chars handles every realistic kubectl/talosctl invocation; longer
# pathological commands simply don't match (false negative by design).
_TAIL = r"[^;&|\n`]{0,200}"

DESTRUCTIVE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        # (?!-) prevents false-positive on hypothetical future verbs like
        # `task talos:reset-node`.
        re.compile(_CMD_START + r"task\s+talos:reset\b(?!-)"),
        "task talos:reset wipes the entire cluster. Confirm with the user first.",
    ),
    (
        re.compile(_CMD_START + r"talosctl\b" + _TAIL + r"\breset\b(?!-)"),
        "talosctl reset wipes a Talos node. Confirm with the user first.",
    ),
    (
        re.compile(
            _CMD_START + r"kubectl\b" + _TAIL + r"\bdelete\b" + _TAIL
            + r"\b(?:namespaces?|ns"
              r"|pv|pvs|persistentvolumes?"
              r"|pvc|pvcs|persistentvolumeclaims?"
              r"|crds?|customresourcedefinitions?)\b"
        ),
        "kubectl delete namespace/pv/pvc/crd cascades to dependent resources.",
    ),
    (
        # `\s--delete-emptydir-data(?=\s|=|$)` is used instead of `\b...\b`
        # because `\b` doesn't fire between a space and `-` (both non-word).
        # The lookahead accepts the `=true`/`=false` suffix form while
        # rejecting `--delete-emptydir-data-extra`. `--delete-local-data` is
        # the deprecated pre-1.25 alias.
        re.compile(
            _CMD_START + r"kubectl\b" + _TAIL + r"\bdrain\b" + _TAIL
            + r"\s--(?:delete-emptydir-data|delete-local-data)(?=\s|=|$)"
        ),
        "kubectl drain --delete-emptydir-data destroys emptyDir volumes on the drained node.",
    ),
    (
        re.compile(_CMD_START + r"helmfile\s+destroy\b"),
        "helmfile destroy removes every bootstrap Helm release.",
    ),
    (
        re.compile(_CMD_START + r"flux\s+uninstall\b"),
        "flux uninstall tears down the GitOps operator.",
    ),
    (
        # rm -rf / -fr / -rfv / --recursive --force at a filesystem root.
        # Terminal root form: `/` or `/*`, `~`, `$HOME`, or `/Users/<user>/`,
        # each followed by whitespace or end-of-string. `/tmp/foo`, `./build`,
        # and any non-root path are deliberately NOT caught.
        re.compile(
            _CMD_START + r"rm\b"
            r"(?:\s+(?:-[rfv]*[rf][rfv]*|--recursive|--force))+"
            r"\s+"
            r"(?:/(?:\s|$|\*)"
            r"|~(?:/|\s|$)"
            r"|\$HOME(?:/|\s|$)"
            r"|/Users/[^/\s]+/?(?:\s|$))"
        ),
        "Recursive rm at HOME or filesystem root is catastrophic.",
    ),
]

# Secondary rule: talosctl apply-config must specify a mode explicitly so
# the caller knows whether it's live, staged, try, or reboot.
APPLY_CONFIG = re.compile(_CMD_START + r"talosctl\b" + _TAIL + r"\bapply-config\b")
HAS_MODE = re.compile(r"(?:--mode(?:=|\s+)\S|(?:^|\s)-m(?:=|\s+)\S)")

# Secondary rule: cluster-wide `flux suspend` halts every reconciliation.
# Scoped suspends (`-n <ns>`, `-nfoo`, `--namespace=<ns>`, `-A`,
# `--all-namespaces`) are fine.
FLUX_SUSPEND = re.compile(_CMD_START + r"flux\s+suspend\b")
FLUX_HAS_SCOPE = re.compile(
    r"(?:-n\S|-n\s+\S"
    r"|--namespace(?:=|\s+)\S"
    r"|(?:^|\s)-A\b"
    r"|--all-namespaces\b)"
)

# Override prefix: start of command only (optional leading whitespace).
# `echo ANTON_DESTRUCTIVE_OK=1; task talos:reset` does NOT match.
_OVERRIDE_PREFIX = re.compile(r"^\s*ANTON_DESTRUCTIVE_OK=1\s+")


def _block(reason: str) -> int:
    print(
        f"Blocked destructive command.\n"
        f"→ {reason}\n"
        f"→ If the user has explicitly authorized this, prefix the command "
        f"with `ANTON_DESTRUCTIVE_OK=1 ` (including the trailing space).",
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

    for pattern, reason in DESTRUCTIVE_PATTERNS:
        if pattern.search(cmd):
            return _block(reason)

    if APPLY_CONFIG.search(cmd) and not HAS_MODE.search(cmd):
        return _block(
            "talosctl apply-config without explicit --mode / -m. Pass "
            "--mode=auto|staged|try|reboot so intent is unambiguous."
        )

    if FLUX_SUSPEND.search(cmd) and not FLUX_HAS_SCOPE.search(cmd):
        return _block(
            "cluster-wide `flux suspend` halts all reconciliation. Scope it "
            "with `-n <namespace>`, `--namespace=<ns>`, or `-A` (which you "
            "must type explicitly if you really mean every namespace)."
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
