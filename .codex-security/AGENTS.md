# Codex Security workspace

Read `.agents/skills/codex-security/SKILL.md` before scans, finding validation,
or changes to this workspace. Read `README.md` for setup and commands.

Local installation and `pnpm check` are offline with respect to model inference.
Actual scans and validation require the isolated environment described in the
skill. A path selector or a clean Git worktree is not a security boundary.

Keep the package pinned and regenerate the lockfile when updating it. Validate
with the installed CLI's dry run before documenting new flags or configuration.
