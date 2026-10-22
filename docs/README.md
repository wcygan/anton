# Anton documentation

Docusaurus publishes the public platform overview, guides, reference, decisions,
and short historical records from `docs/`. Agent procedures live in the repository's
`.agents/skills/`; private evidence and working records are outside this site.

From the repository root:

```sh
mise exec -- bun run --cwd docs start --host 127.0.0.1
mise exec -- bun run --cwd docs typecheck
mise exec -- bun run --cwd docs build
```

The site uses `/anton/` as its base path. Publishing requires explicit authorization.
See `docs/reference/documentation.md` for content ownership and maintenance.
