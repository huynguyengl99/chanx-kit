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
from chanx.messages.base import BaseMessage

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
REGISTRY = json.loads((REPO_ROOT / "copit-registry.json").read_text())
COMPONENTS: dict[str, Any] = REGISTRY["components"]
REPO_URL = "https://github.com/huynguyengl99/chanx-kit"

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
    module = importlib.import_module(f"kits.{package}")
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
