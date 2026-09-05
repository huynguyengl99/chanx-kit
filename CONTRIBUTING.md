# Contributing

Welcome to ChanX Kits. All contributions are welcome, as long as they give real usage to
the community. To keep the quality of the package high, there are a few prerequisites you
should follow:

- **Coding with an AI assistant is acceptable**, as long as you review every line
  carefully, without blindly accepting the changes. Your name is on the PR: if it breaks,
  you fix it.
- **It should come from your own need.** Use the kit yourself before proposing it, in a
  real deployment; a hobby project counts. Code that someone actually runs is better than
  code that merely passes review, and it is what these kits are for.
- **Do not leave trivial comments in the code.** A comment earns its place when it
  explains complex maths, a workaround, or some dark magic (we do not like dark magic,
  but occasionally we need it). AI assistants write far too many of the other kind, so
  prune those before you commit.

Read a neighbouring kit before you start. Generated code that ignores the topic
conventions or the message style will be sent back.

Everything else follows from how kits are delivered: everything in `kits/` is copied into
user projects, and nothing here is installed. A change reaches people only when they run
`copit update`, and it must not silently break them. Runtime helpers live in chanx; the
test harness is itself a kit (`kits/chanx_testing/`). A helper only one kit needs belongs
in that kit.

New kits start at `tier: contrib`. One that proves useful and stable is promoted to
`core` by changing that one line: no move, no id change, and nothing breaks for anyone
who already installed it. The flat layout is deliberate; see
[kits/README.md](kits/README.md).

## Setup

```bash
uv sync
uv run pre-commit install
```

`uv sync` installs both frameworks, lint, docs and tooling. Pre-commit formats, and when
you touch a kit checks that `copit-registry.json` is still current, which is the thing
easiest to forget and most annoying to discover in CI.

## Checklist for a new kit

1. `kits/<package_name>/` with a directory name that is a valid Python identifier
   (`room_chat`, while its id is `room-chat`)
2. `kit.yaml`, the registry metadata; see below
3. `messages.py`, giving every message an action `Literal` and a Pydantic payload
4. `topics.py`; see [docs/authoring-a-kit.md](docs/authoring-a-kit.md)
5. `README.md` with an install line, minimal usage, a hook table and production caveats
6. `tests/test_<kit>.py`, which must pass on **both** backends. If the kit wraps a
   third-party library, cover the *default* path too, not just a stubbed override.
   A kit that genuinely cannot run on both declares `only_variants` instead; see below
7. Mount it in `sandbox/consumers.py`, so its messages reach the AsyncAPI schema that
   freezes the wire contract
8. `uv run python scripts/registry.py build` to regenerate the index

The README and the tests are not optional: `scripts/registry.py` refuses to build an
index for a kit missing either.

## kit.yaml

Each kit describes itself in one file. `scripts/registry.py` reads every
`kits/*/kit.yaml` plus the repo-wide `registry.yaml`, and generates the committed
`copit-registry.json` that the CLI fetches.

```yaml
name: room-chat
title: Room chat
description: >-
  A chat room: persisted history replayed on connect, plus a live roster from the
  presence kit. Pluggable store.
version: 0.1.0
tier: core
tags: [chat, rooms, history, persistence]
authors: ["Your Name <you@example.com>"]

requires:
  - presence

dependencies:
  - "chanx>=2.10.0,<3"

optional:
  tests:
    requires:
      - chanx-testing
```

- **name**: the registry id, in dashes. The directory must be
  `name.replace("-", "_")`, because that is the package a user imports.
- **title**, **description**: what the docs site and the kit index show. The description
  is folded to a single line when the index is built, so a YAML block scalar is fine.
- **version**: the kit's own version, independent of any repo tag. Bump it whenever you
  change the kit; it is how a user can tell what they copied.
- **tier**: `core` or `contrib`, defaulting to `contrib`. A `core` kit may only require
  other `core` kits, which is what keeps the maintained core self-contained.
- **tags**, **authors**: metadata only.
- **requires**: other kits in this registry, resolved transitively at install time and
  checked for cycles. This applies to every install, so only list what the kit itself
  imports.
- **dependencies**: real packages, installed by the user's package manager.
- **optional**: what a file group needs in order to work, resolved only when someone
  installs with `--with <group>`. The `tests` group is where `chanx-testing` belongs,
  since a user who did not ask for tests should not get a test harness. Which files the
  group contains is decided by `registry.yaml`, not here.
- **only_variants**: the frameworks the kit needs. Omit it unless the kit truly cannot
  run on both; see below.

Nothing about *which files get copied* lives here: the include and exclude rules, the
`tests` optional group and the install target are registry-wide, in `registry.yaml`, and
the file list is materialised at build time. See
[docs/registry-conventions.md](docs/registry-conventions.md) for those choices and why
they are made once rather than per kit.

## Framework-specific kits

The both-backends rule is what keeps kits reusable, and it is enforced by the CI matrix
rather than by a lint: a kit importing `django` simply fails the fast-channels leg.

Some kits cannot follow it. Django models, migrations, admin and DRF views have no
fast-channels equivalent, and a fake one helps nobody. Those declare what they need:

```yaml
only_variants:
  - django
```

That one line does three things: copit refuses to install the kit into a project that
has not selected the variant, the test suite stops collecting it on the other backend,
and the docs group it separately. So opting out of a backend is also what lifts the
"import only `chanx.core`" rule, because you are no longer claiming to run there.

Use it only when porting is genuinely impossible. A pluggable store with a
framework-specific implementation (as `django-message-store` is for `room-chat`) is the
shape that works: the portable kit keeps the wire contract, and the restricted one is an
implementation of its store protocol.

## Before you open a PR

Run the hooks, both backends, the type checker and the registry checks. CI runs the same
things, one framework at a time and across Python 3.11 to 3.14.

```bash
uv run pre-commit run --all-files

CHANX_KIT_BACKEND=fast_channels uv run pytest kits tests
CHANX_KIT_BACKEND=channels      uv run pytest kits tests

uv run pyright
uv run python scripts/registry.py check
uv run mkdocs build --strict
```

pyright runs in strict mode and no suppressions are accepted, because composing kits must
not force users to disable error classes.

Two checks are slower and easy to leave to CI, but worth running when the change touches
installs or the framework boundary:

```bash
# one framework installed, which is what actually proves a kit does not need the other
CHANX_KIT_BACKEND=channels uv run --no-default-groups \
    --extra django --group dev-django --group registry pytest kits tests

uv run python scripts/conformance.py    # install every kit with copit and import it
```

Conformance needs copit 0.6 or newer, which `uv sync` installs. To check against a local
copit build instead:
`COPIT=../copit/target/release/copit uv run python scripts/conformance.py`. Or run the
whole matrix with `tox`.

A weekly job re-resolves every dependency to its newest version and runs the suite
against it. Kits are copied, so upstream breakage reaches users through *their* next
install rather than through a release here.

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org), which is what
`[tool.commitizen]` in `pyproject.toml` expects when it derives a version and a
changelog. The type prefix is what matters; the scope is optional and is usually the kit
id.

```
feat(presence): add a Redis-backed store
fix(room-chat): replay history before the roster
docs: explain the topic pattern namespace
chore: bump the chanx floor
```

## Changing an existing kit

- Changing a message shape changes the generated TypeScript types, so CI fails until
  you regenerate them (`npm --prefix sandbox/ui run gen`). Bump the kit's `version` and
  explain the migration in its README.
- Adding an optional field is backwards compatible. Renaming or removing one is not;
  prefer adding the new field and deprecating the old.
- New hooks need defaults that preserve current behaviour.

## Review

Expect questions about the store abstraction (is the default honest about its limits?),
group naming (is it namespaced?), and whether hooks are overridable without forking.
Those three decide whether a kit is reusable or just published.
