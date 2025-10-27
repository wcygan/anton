# Repository Guidelines

## Project Structure & Module Organization
- `templates/` holds the Makejinja sources that render Talos, Flux, and bootstrap manifests. Adjust these before regenerating cluster assets.
- `kubernetes/` stores rendered manifests grouped by `apps/`, `components/`, and `flux/`; keep environment-specific overlays in matching subdirectories.
- `talos/` captures Talos machine configs, while `bootstrap/` contains Helmfile bootstrap assets and encrypted secrets needed before Flux takes over.
- `scripts/` provides shell utilities that are shared by Taskfile targets; extend helpers in `scripts/lib` instead of duplicating logic.
- Configuration inputs live in `cluster.yaml`, `nodes.yaml`, and `cloudflare-tunnel.json`; treat them as the single source of truth for regeneration.

## Build, Test, and Development Commands
- `mise install` provisions toolchain versions listed in `.mise.toml` (talhelper, flux, kubeconform, etc.).
- `task template:init` copies sample configs, generates Age keys, and sets up Git deploy credentials.
- `task template:configure` runs schema checks, renders manifests, re-encrypts `.sops` files, and validates both Kubernetes and Talos output.
- `task reconcile` forces Flux to pull the latest Git state into a running cluster once your KUBECONFIG is pointed at it.

## Coding Style & Naming Conventions
- Follow `.editorconfig`: 2-space indentation for YAML/CUE, 4-space for shell and Markdown, and LF endings everywhere.
- Prefer lower-kebab naming for directories and Kubernetes objects (e.g., `talosconfig`, `helmrelease`). Keep HelmRelease `metadata.name` aligned with chart names.
- Use `yq`/`jq` or helpers in `scripts/lib` for edits instead of manual formatting; run `shellcheck` on new scripts to honor `.shellcheckrc`.

## Testing Guidelines
- Treat `task template:configure` as the minimum validation gate; it wraps `cue vet`, `kubeconform.sh`, and `talhelper validate`.
- Add new schema rules under `.taskfiles/template/resources` when introducing config knobs so `cue vet` enforces them.
- Validate live clusters with `task debug` before submitting fixes that touch controllers or networking components.

## Commit & Pull Request Guidelines
- Match the existing Conventional Commit style (`feat(component): …`, `fix: …`, `chore:`) visible in `git log`; include scopes when helpful and keep summaries under 72 characters.
- PRs should describe rendered changes, link related issues, and call out the manifests impacted.
- Include before/after context for secrets or credentials rotations.

## Secrets & Configuration Tips
- Age keys live in `age.key` and are wired through `.sops.yaml`; never commit personal overrides outside encrypted `.sops` files.
- Keep `cloudflare-tunnel.json` current before running configure tasks and store machine tokens in a secret manager.
