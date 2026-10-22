# docs/

Goal: Maintain Anton's Docusaurus documentation site as published long-form cluster notes.

Success means:
- Published pages live under `docs/docs/`.
- Site config changes stay inside the Docusaurus app.
- Repo guidance links to on-disk markdown paths so agents can read sources directly.

Stop when: docs build or typecheck evidence matches the files changed.

## Layout

- `docs/docs/`: public overview, guides, reference, decisions, and brief historical records.
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

## Publication boundary

All site sources and assets are public. Do not include private endpoints, hardware
serials, private workload identities, detailed inventories, or raw incident captures.
Keep shared agent procedures in `.agents/skills/` and private execution records
outside the site. Preserve decision IDs and supersession; accepted public bodies
are stable after the explicitly marked 2026 condensation migration.

## Visual authoring contract

Follow [the visual design reference](docs/reference/visual-design.md). This system
belongs to Anton; do not modify or depend on personal/global visualization skills.
Use inline semantic roles in Mermaid flowcharts. For custom visuals, compose
`src/components/Diagram` primitives in a component and import it into Markdown.
The shared component owns the panel, accessibility metadata, colors, and arrows.
No raw SVG or inline styles in pages; no per-figure color literals or Mermaid
styling directives. Authoritative light/dark tokens live in `src/css/tokens.css`.

Run `bun run check:design`, `bun run typecheck`, and `bun run build` in `docs/`.
The production build runs the design guard; do not bypass it. When editing the
guard, run `python3 -m unittest discover -s scripts/tests -p test_docs_design.py`
from the repository root. Inspect the visual reference and home page at desktop
and phone widths in both themes. Confirm labels, group crossings, arrowheads,
and accessible descriptions; automated contrast checks alone are insufficient.
