# Anton

A Talos Kubernetes homelab for public applications, private services, and contained
learning. Flux reconciles committed Kubernetes intent.

Start with the [platform capabilities](docs/docs/overview/capabilities.md),
[architecture](docs/docs/overview/architecture.md), or
[routine operations](docs/docs/guides/operations.md).
[Decisions](docs/docs/decisions/index.md) explain architectural choices;
[records](docs/docs/records/index.md) summarize historical findings.

## Work in the repository

`kubernetes/` and `bootstrap/` are hand-edited. Talos configuration is generated
from `talos/talconfig.yaml`, `talos/talenv.yaml`, and patches. There is no general
repository template-render step.

```sh
mise exec -- task --list
mise exec -- task hooks:install
mise exec -- task contracts:validate
```

The deploy gate validates every commit on `main`; see
[deploying changes](docs/docs/guides/deploys.md). Read [AGENTS.md](AGENTS.md) and the matching `.agents/skills/` procedure before
operational changes. These procedures are shared across agent harnesses. Live
cluster actions require explicit approval; repository validation does not grant it.

## Documentation

```sh
mise exec -- bun run --cwd docs start --host 127.0.0.1
mise exec -- bun run --cwd docs typecheck
mise exec -- bun run --cwd docs build
```

The local site uses `/anton/`. Everything in its source and assets is public.
Detailed inventories, sensitive evidence, and working plans stay outside the site.
See [documentation policy](docs/docs/reference/documentation.md).

Anton began from [onedr0p/cluster-template](https://github.com/onedr0p/cluster-template).
