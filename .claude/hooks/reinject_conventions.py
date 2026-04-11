#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""SessionStart:compact hook — re-inject anton's non-negotiable conventions.

After a context compaction, CLAUDE.md nuance is often summarized away. This
hook restates the five rules that most commonly cause damage when forgotten.
"""
import sys

REMINDERS = """## Anton conventions (post-compact reminder)

1. SOPS: never write plaintext to `*.sops.*` files, `age.key`,
   `github-deploy.key`, or `cloudflare-tunnel.json`. Use `sops <file>` to
   edit encrypted files in place, and run `task configure` before committing.

2. Flux 3-file pattern for every app under kubernetes/apps/{ns}/{app}/:
   - ks.yaml
   - app/kustomization.yaml
   - app/helmrelease.yaml
   - app/ocirepository.yaml

3. Destructive ops require explicit user approval — never run without it:
   `task talos:reset`, `task template:reset`, `talosctl reset`,
   `kubectl delete namespace/pv/pvc`, cluster-wide `flux suspend`,
   `talosctl apply-config` without `--mode`.

4. Always verify `kubectl config current-context` and `talosctl config info`
   match the anton cluster before running any mutating command.

5. Never commit the real tailnet name — use `<tailnet-name>.ts.net`.

Prefer jj over git in this repo. Hooks will block mutating git commands with
a jj-equivalent hint; override with `JJ_OVERRIDE=1` only when jj genuinely
cannot do what you need.
"""


def main() -> int:
    print(REMINDERS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
