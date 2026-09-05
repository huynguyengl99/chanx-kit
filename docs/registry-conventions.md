# Our registry

The index format is **copit's**, not ours. See
[copit's registry documentation](https://huynguyengl99.github.io/copit/registry/) for
`copit-registry.json`, `[registries.*]` and the JSON Schema. This page records the choices
ChanX Kit makes *within* that format, and why.

`scripts/registry.py` generates `copit-registry.json` from `registry.yaml` plus every
`kits/*/kit.yaml`, and validates the result against copit's schema
(`scripts/registry.schema.json`, a vendored copy) before writing it.

## Ids use dashes, directories use underscores

`room-chat` is the id; `kits/room_chat/` is the directory.

The directory name is what a user imports, so it has to be a valid Python identifier.
The id appears on the command line, where dashes read better. CI checks that
`id.replace("-", "_")` equals the directory name.

```bash
copit add @chanx-kit/room-chat        # then: from .ws_kits.room_chat import ...
```

## Tier is metadata, not a directory

Every kit sits directly in `kits/`. `tier: core` or `tier: contrib` lives in
`kit.yaml`.

Two reasons, and the second one is the load-bearing one:

1. **Promotion is free.** Moving a kit from `contrib` to `core` is a one-line change:
   no move, no id change, and nothing breaks for anyone who already installed it.
2. **Relative imports keep working.** copit installs kits side by side into one
   directory. If this repository nested them under `core/` and `contrib/`, then
   `from ..presence.store import PresenceStore` would need a different depth here than
   in a user's project, and would break on install.

`scripts/registry.py` enforces the dependency direction from the metadata: `core` may
only depend on `core`; `contrib` may depend on either.

## Framework-specific kits declare `only_variants`

Most kits import only `chanx.core` and run on both backends. A few cannot: one shipping
Django models, migrations, admin and DRF views has nothing to port to fast-channels.
Those declare the variant they need:

```yaml
# kits/django_message_store/kit.yaml
only_variants:
  - django
```

copit then refuses to install the kit unless the project selects that variant, and says
what to pass. The check covers kits pulled in through `requires` too, so a restricted
dependency fails the install rather than landing unusable.

This is not the same as `variants`, which only *adds* files and packages. `variants` is
still unused here, because no kit needs a per-framework adapter:
`chanx.utils.scope` handles the differences at runtime.

Two rules follow, both enforced by `scripts/registry.py`:

- every name must appear in `registry.yaml`'s `variants`, otherwise the kit would be
  uninstallable everywhere;
- a kit may not depend on a more restricted kit than itself. An unrestricted kit
  requiring a Django-only one would promise an install copit will refuse.

The same metadata decides what the test suite collects: the root `conftest.py` reads
`only_variants` from the index and skips those kits on the backend that does not provide
the variant, so there is no separate marker to keep in sync.

## Tests are published as an optional group

```yaml
install:
  optional:
    tests:
      - "tests/**"
```

A normal install leaves tests out. Someone who intends to modify a kit can opt in:

```bash
copit add @chanx-kit/presence --with tests
```

Selecting a group is recorded on the source entry, so `copit update` reproduces it.

### The harness the tests need is scoped to the group

Copied tests import the `chanx-testing` harness, which is a kit in its own right. Putting
it in a kit's `requires` would copy a test harness into every project, including the ones
that never asked for tests. So the kit declares it on the group instead:

```yaml
# kits/presence/kit.yaml
optional:
  tests:
    requires:
      - chanx-testing
```

copit resolves that only when `--with tests` is passed, in the same pass as ordinary
`requires`: ordered first, transitive, and subject to `only_variants`. `scripts/registry.py`
publishes a group as a bare file list until a kit declares something it needs, and applies
the same tier and cycle checks to a group's requirement as to a component's.

This needs copit 0.6.0 or newer.

## What is never published

```yaml
exclude:
  - "kit.yaml"                # registry metadata
  - "__pycache__/**"
```

`files` in the index is materialised at build time, so copit copies exactly that list, and
metadata cannot reach a user's project even by accident. A test asserts it
(`test_tests_are_not_shipped_to_users`).

## `package_marker`

```yaml
install:
  package_marker: __init__.py
```

copit creates this in the target directory and in each kit directory, so a freshly
installed `ws_kits/` is importable without the user having to notice.

## Variants

`django` and `fastapi` are declared, so a kit *can* ship a per-framework adapter. None
currently needs one, because kits import only `chanx.core` and `chanx.messages` and
framework differences are handled at runtime by `chanx.utils.scope`. The declaration
exists for kits that end up genuinely needing a split, such as an ORM-backed store.

## Conformance

chanx-kit doubles as copit's integration fixture: it exercises kit-to-kit dependencies,
tiers, package dependencies and optional groups for real. CI installs every kit into a
throwaway project with copit and imports the result, so a change that breaks installation
fails here rather than in a user's project.
