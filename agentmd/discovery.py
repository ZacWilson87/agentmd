"""Anti-drift discovery: extract stack and conventions from project files."""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentmd.models import AgentsFile


# ---------------------------------------------------------------------------
# Known framework / library mappings
# ---------------------------------------------------------------------------

# Python package name (lowercase) → canonical stack label
_PYTHON_FRAMEWORKS: dict[str, str] = {
    "fastapi": "fastapi",
    "django": "django",
    "flask": "flask",
    "tornado": "tornado",
    "starlette": "starlette",
    "litestar": "litestar",
    "aiohttp": "aiohttp",
    "sqlalchemy": "sqlalchemy",
    "pydantic": "pydantic",
    "typer": "typer",
    "click": "click",
    "celery": "celery",
    "redis": "redis",
    "pymongo": "mongodb",
    "motor": "mongodb",
    "asyncpg": "postgresql",
    "psycopg2": "postgresql",
    "psycopg": "postgresql",
    "aiomysql": "mysql",
    "pymysql": "mysql",
    "boto3": "aws",
    "anthropic": "claude",
    "openai": "openai",
    "pytest": "pytest",
}

# JS/TS package name → canonical stack label
_JS_FRAMEWORKS: dict[str, str] = {
    "react": "react",
    "react-dom": "react",
    "next": "nextjs",
    "nuxt": "nuxt",
    "vue": "vue",
    "svelte": "svelte",
    "@sveltejs/kit": "sveltekit",
    "angular": "angular",
    "@angular/core": "angular",
    "express": "express",
    "fastify": "fastify",
    "hono": "hono",
    "vite": "vite",
    "@vitejs/plugin-react": "vite",
    "vitest": "vitest",
    "jest": "jest",
    "typescript": "typescript",
    "tailwindcss": "tailwind",
    "prisma": "prisma",
    "@prisma/client": "prisma",
    "drizzle-orm": "drizzle",
    "zod": "zod",
    "trpc": "trpc",
    "@trpc/server": "trpc",
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DriftIssue:
    """A single mismatch between declared AGENTS.md state and project reality."""

    kind: str  # "undeclared_stack" | "missing_file" | "convention_gap"
    message: str
    suggestion: str = ""


@dataclass
class DiscoveredContext:
    """What was found by inspecting project files."""

    stack: list[str] = field(default_factory=list)
    package_managers: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    linter_conventions: list[str] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Stack discovery
# ---------------------------------------------------------------------------


def _parse_pyproject(path: Path, ctx: DiscoveredContext) -> None:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return

    ctx.languages.append("python")
    ctx.stack.append("python")
    ctx.source_files.append(str(path))

    # uv / hatch / poetry / flit build system
    bs = data.get("build-system", {}).get("build-backend", "")
    if "hatch" in bs:
        ctx.package_managers.append("hatch")
    elif "poetry" in bs:
        ctx.package_managers.append("poetry")
    elif "flit" in bs:
        ctx.package_managers.append("flit")

    # Check if uv.lock exists alongside
    if (path.parent / "uv.lock").exists():
        ctx.package_managers.append("uv")

    # Extract dependencies
    project_deps: list[str] = data.get("project", {}).get("dependencies", [])
    for dep_str in project_deps:
        pkg_name = _normalise_pkg_name(dep_str)
        label = _PYTHON_FRAMEWORKS.get(pkg_name)
        if label and label not in ctx.stack:
            ctx.stack.append(label)

    # Also check tool.poetry.dependencies
    poetry_deps: dict[str, Any] = (
        data.get("tool", {}).get("poetry", {}).get("dependencies", {})
    )
    for pkg_name_raw in poetry_deps:
        pkg_name = _normalise_pkg_name(pkg_name_raw)
        label = _PYTHON_FRAMEWORKS.get(pkg_name)
        if label and label not in ctx.stack:
            ctx.stack.append(label)

    # Ruff config → linting conventions
    ruff = data.get("tool", {}).get("ruff", {})
    if ruff:
        line_len = ruff.get("line-length")
        if line_len:
            ctx.linter_conventions.append(f"Line length: {line_len} (ruff)")
        per_file = ruff.get("per-file-ignores") or ruff.get("lint", {}).get(
            "per-file-ignores"
        )
        if per_file:
            ctx.linter_conventions.append("Per-file ruff ignores configured")


def _parse_requirements_txt(path: Path, ctx: DiscoveredContext) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return

    ctx.source_files.append(str(path))
    if "python" not in ctx.languages:
        ctx.languages.append("python")
        ctx.stack.append("python")

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        pkg_name = _normalise_pkg_name(line)
        label = _PYTHON_FRAMEWORKS.get(pkg_name)
        if label and label not in ctx.stack:
            ctx.stack.append(label)


def _parse_package_json(path: Path, ctx: DiscoveredContext) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return

    ctx.source_files.append(str(path))
    if "nodejs" not in ctx.languages:
        ctx.languages.append("nodejs")
        ctx.stack.append("nodejs")

    # Check for TypeScript
    all_deps: dict[str, str] = {
        **data.get("dependencies", {}),
        **data.get("devDependencies", {}),
    }
    for pkg_name, _ in all_deps.items():
        label = _JS_FRAMEWORKS.get(pkg_name.lower())
        if label and label not in ctx.stack:
            ctx.stack.append(label)

    # Package manager hints
    if (path.parent / "pnpm-lock.yaml").exists():
        ctx.package_managers.append("pnpm")
    elif (path.parent / "yarn.lock").exists():
        ctx.package_managers.append("yarn")
    elif (path.parent / "bun.lockb").exists() or (path.parent / "bun.lock").exists():
        ctx.package_managers.append("bun")
    elif (path.parent / "package-lock.json").exists():
        ctx.package_managers.append("npm")

    # ESLint → linting conventions
    for eslint_name in (
        ".eslintrc",
        ".eslintrc.js",
        ".eslintrc.json",
        ".eslintrc.yaml",
        ".eslintrc.yml",
        "eslint.config.js",
        "eslint.config.ts",
    ):
        if (path.parent / eslint_name).exists():
            ctx.linter_conventions.append("ESLint configured")
            break

    # Prettier
    if any(
        (path.parent / f).exists()
        for f in (".prettierrc", ".prettierrc.json", "prettier.config.js")
    ):
        ctx.linter_conventions.append("Prettier configured")


def _parse_go_mod(path: Path, ctx: DiscoveredContext) -> None:
    ctx.source_files.append(str(path))
    ctx.languages.append("go")
    ctx.stack.append("go")


def _parse_cargo_toml(path: Path, ctx: DiscoveredContext) -> None:
    ctx.source_files.append(str(path))
    ctx.languages.append("rust")
    ctx.stack.append("rust")


def _normalise_pkg_name(dep_str: str) -> str:
    """Strip version specifiers and normalise to lowercase."""
    for sep in (">=", "<=", "!=", "~=", "==", ">", "<", "[", ";", " "):
        dep_str = dep_str.split(sep)[0]
    return dep_str.strip().lower().replace("-", "_").replace(".", "_")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def discover(root: Path) -> DiscoveredContext:
    """Inspect root directory and return a DiscoveredContext."""
    ctx = DiscoveredContext()

    # Python
    for name in ("pyproject.toml",):
        p = root / name
        if p.exists():
            _parse_pyproject(p, ctx)

    for name in ("requirements.txt", "requirements-dev.txt", "requirements/base.txt"):
        p = root / name
        if p.exists():
            _parse_requirements_txt(p, ctx)

    # JavaScript / TypeScript
    p = root / "package.json"
    if p.exists():
        _parse_package_json(p, ctx)

    # Go
    p = root / "go.mod"
    if p.exists():
        _parse_go_mod(p, ctx)

    # Rust
    p = root / "Cargo.toml"
    if p.exists():
        _parse_cargo_toml(p, ctx)

    # Deduplicate while preserving order
    ctx.stack = list(dict.fromkeys(ctx.stack))
    ctx.languages = list(dict.fromkeys(ctx.languages))
    ctx.package_managers = list(dict.fromkeys(ctx.package_managers))

    return ctx


def check_drift(agents_file: AgentsFile, root: Path) -> list[DriftIssue]:
    """Compare declared AGENTS.md state against discovered project reality.

    Returns a list of DriftIssue objects describing mismatches.
    """
    issues: list[DriftIssue] = []
    discovered = discover(root)
    declared_stack = {s.lower() for s in agents_file.stack}

    # Items found in the project but not declared
    for item in discovered.stack:
        if item.lower() not in declared_stack:
            issues.append(
                DriftIssue(
                    kind="undeclared_stack",
                    message=f"'{item}' detected in project files but not listed in AGENTS.md stack.",
                    suggestion=f"Add '{item}' to the stack list in AGENTS.md.",
                )
            )

    # Linter conventions detected but not mentioned in AGENTS.md conventions
    conventions_text = " ".join(agents_file.conventions).lower()
    for lc in discovered.linter_conventions:
        keyword = lc.split()[0].lower()  # e.g. "eslint" from "ESLint configured"
        if keyword not in conventions_text:
            issues.append(
                DriftIssue(
                    kind="convention_gap",
                    message=f"{lc} but no related convention declared in AGENTS.md.",
                    suggestion="Add a matching convention entry to AGENTS.md.",
                )
            )

    return issues
