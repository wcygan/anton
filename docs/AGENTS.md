# docs/

Goal: Maintain Anton's Docusaurus documentation site as published long-form cluster notes.

Success means:
- Published pages live under `docs/docs/`.
- Site config changes stay inside the Docusaurus app.
- Repo guidance links to on-disk markdown paths so agents can read sources directly.

Stop when: docs build or typecheck evidence matches the files changed.

## Layout

- `docs/docs/`: published pages, notes, runbooks, and playground material.
- `docs/src/` and `docs/static/`: theme and static assets.
- `docusaurus.config.ts`: site config with `baseUrl: /anton/`.
- `sidebars.ts`: sidebar behavior.
- `package.json`: Bun-managed Docusaurus commands.

## Commands

```sh
cd docs && bun install
cd docs && bun start
cd docs && bun run build
cd docs && bun run typecheck
```

Use `bun run deploy` only when explicitly publishing to GitHub Pages.
