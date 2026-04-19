# docs/

Docusaurus static site that publishes the homelab's long-form notes to `wcygan.github.io/anton`. Narrative docs referenced from repo CLAUDE.md files (e.g. `docs/docs/notes/adding-a-2nd-domain.md`) live here so they render on the site with Mermaid diagrams and navigation — short inline notes stay in repo markdown.

## Contents

- `docs/` — published MDX pages; `intro.md` is the landing page, `notes/` holds the homelab write-ups, `playground/` is a scratch area
- `src/`, `static/` — custom theme overrides and static assets (rarely touched)
- `docusaurus.config.ts` — site config; `baseUrl: /anton/`, Mermaid enabled, deploys to `wcygan/anton` GitHub Pages
- `sidebars.ts` — sidebar is auto-generated from `docs/` folder structure; edit only to override ordering
- `package.json` — Bun-managed, Docusaurus 3 + React 19

## Usage

This directory is self-contained — it does not touch the cluster. Run `bun install` once, then `bun start` for the hot-reload dev server, `bun run build` to validate production output, or `bun run typecheck` before committing config changes. `bun run deploy` pushes to the `gh-pages` branch (use `USE_SSH=true` off-LAN).

To add a note, drop a new `.md` file under `docs/docs/notes/` with frontmatter (`sidebar_position`, optional `slug`) — the sidebar picks it up automatically. When linking from a repo CLAUDE.md, use the on-disk path (`docs/docs/notes/<name>.md`) so agents can Read it directly without fetching the rendered site.
