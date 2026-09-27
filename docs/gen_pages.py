"""Generate the kit pages at docs build time. Every page derives from the code (the
registry index, kit READMEs, message classes), so docs cannot drift from the wire
format. Run by ``mkdocs-gen-files``, not standalone.
"""

from __future__ import annotations

import importlib
import inspect
import json
import re
import sys
from pathlib import Path
from typing import Any

import mkdocs_gen_files
import yaml
from chanx.messages.base import BaseMessage

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
REGISTRY = json.loads((REPO_ROOT / "copit-registry.json").read_text())
COMPONENTS: dict[str, Any] = REGISTRY["components"]
UI_COMPONENTS: dict[str, Any] = json.loads(
    (REPO_ROOT / "ui" / "copit-registry.json").read_text()
)["components"]
REPO_URL = "https://github.com/huynguyengl99/chanx-kit"
SHADCN_URL = "https://huynguyengl99.github.io/chanx-kit/r"


def manifest(component: dict[str, Any]) -> dict[str, Any]:
    return yaml.safe_load((REPO_ROOT / component["path"] / "kit.yaml").read_text())


# Contracts live in kit.yaml, not the published index.
SERVERS_OF: dict[str, list[str]] = {}
UIS_OF: dict[str, list[str]] = {}
for _name, _component in COMPONENTS.items():
    _meta = manifest(_component)
    for _contract in [_meta.get("defines"), *(_meta.get("implements") or [])]:
        if _contract:
            SERVERS_OF.setdefault(_contract, []).append(_name)
for _name, _component in UI_COMPONENTS.items():
    for _contract in manifest(_component).get("consumes") or []:
        UIS_OF.setdefault(_contract, []).append(_name)


def contracts_of(component: dict[str, Any]) -> list[str]:
    meta = manifest(component)
    found = [meta.get("defines"), *(meta.get("implements") or [])]
    return [contract for contract in found if contract] + list(
        meta.get("consumes") or []
    )


def link_list(names: list[str], prefix: str) -> str:
    return ", ".join(f"[`{name}`]({prefix}{name}.md)" for name in names)


def contract_facts(component: dict[str, Any], *, ui: bool) -> list[str]:
    """Each contract, and the kits on the other side of it."""
    rows = []
    for contract in contracts_of(component):
        rows.append(f"| **Contract** | `{contract}` |")
        other, label, prefix = (
            (SERVERS_OF, "Works with", "../kits/")
            if ui
            else (UIS_OF, "UI kits", "../ui/")
        )
        if other.get(contract):
            rows.append(f"| **{label}** | {link_list(other[contract], prefix)} |")
    return rows


nav_lines: list[str] = []


def resolve(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    """Follow a local ``$ref`` one level."""
    ref = schema.get("$ref")
    if not ref:
        return schema
    name = ref.rsplit("/", 1)[-1]
    return root.get("$defs", {}).get(name, {})


def type_label(schema: dict[str, Any]) -> str:
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    if "const" in schema:
        return f"`{schema['const']}`"
    if "enum" in schema:
        return " | ".join(f"`{value}`" for value in schema["enum"])
    for key in ("anyOf", "oneOf"):
        if key in schema:
            return " | ".join(type_label(option) for option in schema[key])
    if schema.get("type") == "array":
        return f"{type_label(schema.get('items', {}))}[]"
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        return " | ".join(str(item) for item in schema_type)
    return str(schema_type or "any")


def payload_table(message_schema: dict[str, Any]) -> str:
    payload = message_schema.get("properties", {}).get("payload")
    if not payload:
        return ""

    resolved = resolve(payload, message_schema)
    properties = resolved.get("properties")
    if not properties:
        return f"Payload: `{type_label(payload)}`\n"

    required = set(resolved.get("required", []))
    rows = ["| Field | Type | Required |", "|---|---|---|"]
    for name, prop in properties.items():
        # An unescaped pipe in a union type would split the table cell.
        label = type_label(prop).replace("|", "\\|")
        rows.append(f"| `{name}` | {label} | {'yes' if name in required else 'no'} |")
    return "\n".join(rows) + "\n"


def rewrite_links(markdown: str) -> str:
    """Point a kit README's repo-relative links at their docs-site equivalents."""
    replacements = {
        "../docs/authoring-a-kit.md": "../../authoring-a-kit.md",
        "../CONTRIBUTING.md": f"{REPO_URL}/blob/main/CONTRIBUTING.md",
        "(kits/": f"({REPO_URL}/tree/main/kits/",
    }
    for old, new in replacements.items():
        markdown = markdown.replace(old, new)
    return markdown


def kit_messages(package: str) -> dict[str, tuple[str, dict[str, Any]]]:
    """Message classes a kit defines, keyed by action."""
    try:
        module = importlib.import_module(f"kits.{package}")
    except ModuleNotFoundError as error:
        # A bridge kit whose library the docs build does not install.
        if (error.name or "").startswith("kits"):
            raise
        return {}
    found: dict[str, tuple[str, dict[str, Any]]] = {}

    for _, obj in inspect.getmembers(module, inspect.isclass):
        if not issubclass(obj, BaseMessage) or obj is BaseMessage:
            continue
        if not obj.__module__.startswith(module.__name__):
            continue
        action = obj.model_fields["action"].default
        found[action] = (obj.__name__, obj.model_json_schema())

    return dict(sorted(found.items()))


def kit_page(name: str, component: dict[str, Any]) -> str:
    directory = REPO_ROOT / component["path"]
    readme = (directory / "README.md").read_text()

    # The metadata header below replaces the README's own H1.
    body = re.sub(r"\A#\s+.*\n+", "", readme, count=1)

    tier = component["tier"]
    requires = component.get("requires") or []
    dependencies = component.get("dependencies") or []
    only_variants = component.get("only_variants") or []

    header = [
        f"# {component['title']}",
        "",
        f'!!! info "{tier} · v{component["version"]}"',
        f"    {component['description']}",
        "",
    ]

    variant_flags = " ".join(f"--variant {variant}" for variant in only_variants)
    install = f"copit add @chanx-kit/{name}"
    if variant_flags:
        install = f"{install} {variant_flags}"

    facts = ["| | |", "|---|---|", f"| **Install** | `{install}` |"]
    if only_variants:
        facts.append(
            "| **Only on** | "
            + ", ".join(f"`{variant}`" for variant in only_variants)
            + " |"
        )
    facts.append(f"| **Import from** | `{Path(component['path']).name}` |")
    if requires:
        links = ", ".join(f"[`{r}`]({r}.md)" for r in requires)
        facts.append(f"| **Requires kits** | {links} |")
    if parts := component.get("parts"):
        listed = ", ".join(
            f"`{part}` ({', '.join(f for f in spec['include'] if '/' not in f)})"
            for part, spec in parts.items()
        )
        facts.append(
            f"| **Parts** | {listed}: all by default, "
            f"or `copit add @chanx-kit/{name} --only <part>` |"
        )
    facts += contract_facts(component, ui=False)
    if dependencies:
        facts.append(
            "| **Python packages** | "
            + ", ".join(f"`{d}`" for d in dependencies)
            + " |"
        )
    if component.get("tags"):
        facts.append(
            "| **Tags** | " + ", ".join(f"`{t}`" for t in component["tags"]) + " |"
        )
    facts.append(
        f"| **Source** | [{component['path']}]({REPO_URL}/tree/main/{component['path']}) |"
    )

    sections = ["\n".join(header), "\n".join(facts), "", rewrite_links(body)]

    messages = kit_messages(Path(component["path"]).name)
    if messages:
        sections.append("\n## Message reference\n")
        sections.append("_Generated from the kit's message classes._\n")
        for action, (class_name, schema) in messages.items():
            sections.append(f"### `{action}`\n")
            sections.append(f"`{class_name}`\n")
            table = payload_table(schema)
            if table:
                sections.append(table)

    return "\n".join(sections)


# --- kit pages ------------------------------------------------------------------
index_rows = [
    "# Kits",
    "",
    "Each kit is copied into your project and owned by you. Install one with"
    " [copit](https://github.com/huynguyengl99/copit):",
    "",
    "```bash",
    "copit add @chanx-kit/notification",
    "```",
    "",
    "| Kit | Tier | Runs on | Description |",
    "|---|---|---|---|",
]

for name in sorted(COMPONENTS):
    component = COMPONENTS[name]
    runs_on = ", ".join(component.get("only_variants") or []) or "both"
    index_rows.append(
        f"| [`{name}`]({name}.md) | {component['tier']} | {runs_on} "
        f"| {component['description']} |"
    )

with mkdocs_gen_files.open("kits/index.md", "w") as handle:
    handle.write("\n".join(index_rows) + "\n")

nav_lines.append("* [Kits](kits/index.md)")
for name in sorted(COMPONENTS):
    with mkdocs_gen_files.open(f"kits/{name}.md", "w") as handle:
        handle.write(kit_page(name, COMPONENTS[name]))
    mkdocs_gen_files.set_edit_path(
        f"kits/{name}.md", f"{COMPONENTS[name]['path']}/README.md"
    )
    nav_lines.append(f"    * [{COMPONENTS[name]['title']}](kits/{name}.md)")


# --- UI kit pages ---------------------------------------------------------------
def ui_page(name: str, component: dict[str, Any]) -> str:
    readme = (REPO_ROOT / component["path"] / "README.md").read_text()
    body = re.sub(r"\A#\s+.*\n+", "", readme, count=1)

    facts = [
        "| | |",
        "|---|---|",
        f"| **Install** | `copit add @chanx-kit-ui/{name}` |",
        f"| **Or with shadcn** | `npx shadcn add {SHADCN_URL}/{name}.json` |",
    ]
    facts += contract_facts(component, ui=True)
    if component.get("requires"):
        facts.append(
            f"| **Requires UI kits** | {link_list(component['requires'], '')} |"
        )
    variants = ", ".join(f"`{variant}`" for variant in component.get("variants", {}))
    if variants:
        facts.append(f"| **Frameworks** | {variants} (the core is framework-free) |")
    facts.append(
        "| **npm packages** | "
        + ", ".join(f"`{d}`" for d in component["dependencies"])
        + " |"
    )
    facts.append(
        f"| **Source** | [{component['path']}]({REPO_URL}/tree/main/{component['path']}) |"
    )

    header = [
        f"# {component['title']}",
        "",
        f'!!! info "UI · v{component["version"]}"',
        f"    {component['description']}",
        "",
    ]
    return "\n".join(["\n".join(header), "\n".join(facts), "", rewrite_links(body)])


ui_index = [
    "# UI kits",
    "",
    "Copy-in UI that binds to a **contract**, the messages on a topic, rather than to"
    " one server kit, so it works with every server speaking that contract. Each has a"
    " framework-free core and React components; styling is one CSS file driven by"
    " `--chanx-*` variables. Set the registry up once, choosing your framework:",
    "",
    "```bash",
    "copit registry add chanx-kit-ui github:huynguyengl99/chanx-kit@<tag> \\",
    "  --index ui/copit-registry.json --to web/src/chanx-kit --variant react",
    "copit add @chanx-kit/notification @chanx-kit-ui/notification",
    "```",
    "",
    "| UI kit | Contract | Description |",
    "|---|---|---|",
]
for name in sorted(UI_COMPONENTS):
    component = UI_COMPONENTS[name]
    contract = ", ".join(f"`{c}`" for c in contracts_of(component))
    ui_index.append(
        f"| [`{name}`]({name}.md) | {contract} | {component['description']} |"
    )

with mkdocs_gen_files.open("ui/index.md", "w") as handle:
    handle.write("\n".join(ui_index) + "\n")

nav_lines.append("* [UI kits](ui/index.md)")
for name in sorted(UI_COMPONENTS):
    with mkdocs_gen_files.open(f"ui/{name}.md", "w") as handle:
        handle.write(ui_page(name, UI_COMPONENTS[name]))
    mkdocs_gen_files.set_edit_path(
        f"ui/{name}.md", f"{UI_COMPONENTS[name]['path']}/README.md"
    )
    nav_lines.append(f"    * [{UI_COMPONENTS[name]['title']}](ui/{name}.md)")

# --- contributing page ----------------------------------------------------------
# Rendered from the repository's own CONTRIBUTING.md so the two cannot disagree. Its
# links are written for someone reading the file on GitHub, so they are repointed the
# way kit READMEs are.
contributing = (REPO_ROOT / "CONTRIBUTING.md").read_text()
for old, new in {
    "(docs/": "(",
    "(kits/README.md)": f"({REPO_URL}/blob/main/kits/README.md)",
}.items():
    contributing = contributing.replace(old, new)

with mkdocs_gen_files.open("contributing.md", "w") as handle:
    handle.write(contributing)
mkdocs_gen_files.set_edit_path("contributing.md", "CONTRIBUTING.md")

# --- navigation -----------------------------------------------------------------
with mkdocs_gen_files.open("SUMMARY.md", "w") as handle:
    handle.write(
        "\n".join(
            [
                "* [Home](index.md)",
                "* [Getting started](getting-started.md)",
                "* Guides",
                "    * [UI kits](ui-kits.md)",
                "    * [Add voice](voice.md)",
                *nav_lines,
                "* Contributing",
                "    * [Checklist and workflow](contributing.md)",
                "    * [Authoring a kit](authoring-a-kit.md)",
                "    * [Questions](questions.md)",
                "    * [Our registry](registry-conventions.md)",
            ]
        )
        + "\n"
    )
