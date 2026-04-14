"""agentmd CLI — all commands defined here."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from agentmd import __version__
from agentmd.exporter import export_context
from agentmd.parser import ParseError, find_all_agentmd_files, parse_file
from agentmd.resolver import ResolvedContext, resolve
from agentmd.scaffolder import (
    add_rule,
    add_skill,
    init_repo,
)

app = typer.Typer(
    name="agentmd",
    help="The open standard for AI context in codebases.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
list_app = typer.Typer(help="List agentmd artifacts in the repo.", no_args_is_help=True)
add_app = typer.Typer(help="Scaffold a new agentmd artifact.", no_args_is_help=True)
app.add_typer(list_app, name="list")
app.add_typer(add_app, name="add")

console = Console()
err_console = Console(stderr=True)


def version_callback(value: bool) -> None:
    if value:
        console.print(f"agentmd {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        Optional[bool],
        typer.Option("--version", "-V", callback=version_callback, is_eager=True, help="Show version."),
    ] = None,
) -> None:
    """agentmd — structured AI context for codebases.

    Defines three file types: AGENTS.md, SKILL.md, and RULE.md.
    """


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@app.command()
def init(
    path: Annotated[Path, typer.Argument(help="Directory to initialise (default: CWD).")] = Path("."),
    force: Annotated[bool, typer.Option("--force", "-f", help="Overwrite existing files.")] = False,
) -> None:
    """Bootstrap AGENTS.md, /skills, and /rules in a directory."""
    target = path.resolve()
    if not target.is_dir():
        err_console.print(f"[red]Error:[/red] {target} is not a directory.")
        raise typer.Exit(1)

    created = init_repo(target, force=force)
    if created:
        for p in created:
            console.print(f"  [green]created[/green]  {p}")
        console.print("\n[bold green]Done.[/bold green] Run [cyan]agentmd validate[/cyan] to check your setup.")
    else:
        console.print("[yellow]Nothing to do[/yellow] — all files already exist. Use [cyan]--force[/cyan] to overwrite.")


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


@app.command()
def validate(
    path: Annotated[Path, typer.Argument(help="Repo root to scan (default: CWD).")] = Path("."),
) -> None:
    """Validate all agentmd files in a repo."""
    root = path.resolve()
    files = find_all_agentmd_files(root)

    if not files:
        console.print("[yellow]No agentmd files found.[/yellow]")
        raise typer.Exit(0)

    errors: list[tuple[Path, str]] = []
    valid: list[Path] = []

    for fpath in files:
        try:
            parse_file(fpath)
            valid.append(fpath)
        except ParseError as exc:
            errors.append((fpath, str(exc)))

    table = Table(title="agentmd validate", show_header=True, header_style="bold cyan")
    table.add_column("File", style="dim", no_wrap=True)
    table.add_column("Status")
    table.add_column("Detail")

    for fpath in valid:
        rel = fpath.relative_to(root)
        table.add_row(str(rel), "[green]✓ valid[/green]", "")

    for fpath, msg in errors:
        rel = fpath.relative_to(root)
        table.add_row(str(rel), "[red]✗ error[/red]", msg)

    console.print(table)

    if errors:
        err_console.print(f"\n[red]{len(errors)} error(s) found.[/red]")
        raise typer.Exit(1)
    else:
        console.print(f"\n[green]All {len(valid)} file(s) valid.[/green]")


# ---------------------------------------------------------------------------
# resolve
# ---------------------------------------------------------------------------


@app.command(name="resolve")
def resolve_cmd(
    file: Annotated[Path, typer.Argument(help="Target file to resolve context for.")],
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON.")] = False,
) -> None:
    """Show resolved agentmd context for a given file path."""
    target = file.resolve()

    ctx: ResolvedContext = resolve(target)

    if output_json:
        console.print_json(json.dumps(export_context(ctx), indent=2))
        return

    _print_resolved_context(ctx, target)


def _print_resolved_context(ctx: ResolvedContext, target: Path) -> None:
    console.print(Panel(f"[bold]Resolved context for[/bold] [cyan]{target}[/cyan]", expand=False))

    if ctx.agents_file:
        a = ctx.agents_file
        console.print(f"\n[bold]AGENTS.md[/bold] — [dim]{ctx.source_files[0] if ctx.source_files else ''}[/dim]")
        console.print(f"  name:  {a.name}")
        console.print(f"  scope: {a.scope}")
        console.print(f"  stack: {', '.join(a.stack) or '(none)'}")
        if a.conventions:
            console.print("  conventions:")
            for c in a.conventions:
                console.print(f"    • {c}")
        if a.agent_instructions:
            console.print(f"  agent_instructions: [dim]{a.agent_instructions[:120].strip()}…[/dim]")
    else:
        console.print("\n[yellow]No AGENTS.md found in scope.[/yellow]")

    if ctx.active_skills:
        console.print(f"\n[bold]Active Skills[/bold] ({len(ctx.active_skills)})")
        for s in ctx.active_skills:
            console.print(f"  [cyan]{s.id}[/cyan] v{s.version} — {s.description}")
    else:
        console.print("\n[dim]No active skills.[/dim]")

    if ctx.active_rules:
        console.print(f"\n[bold]Active Rules[/bold] ({len(ctx.active_rules)})")
        for r in ctx.active_rules:
            severity_color = {"error": "red", "warning": "yellow", "info": "blue"}.get(r.severity, "white")
            console.print(f"  [{severity_color}]{r.severity}[/{severity_color}] [cyan]{r.id}[/cyan] — {r.description}")
    else:
        console.print("\n[dim]No active rules for this file.[/dim]")

    console.print(f"\n[dim]Source files: {len(ctx.source_files)}[/dim]")
    for sf in ctx.source_files:
        console.print(f"  [dim]{sf}[/dim]")


# ---------------------------------------------------------------------------
# list skills / list rules
# ---------------------------------------------------------------------------


@list_app.command(name="skills")
def list_skills(
    path: Annotated[Path, typer.Argument(help="Repo root to scan (default: CWD).")] = Path("."),
) -> None:
    """List all SKILL.md files in the repo."""
    from agentmd.models import SkillFile
    from agentmd.parser import find_all_agentmd_files, parse_file

    root = path.resolve()
    files = find_all_agentmd_files(root)

    skills: list[tuple[Path, SkillFile]] = []
    for fpath in files:
        try:
            parsed = parse_file(fpath)
            if isinstance(parsed, SkillFile):
                skills.append((fpath, parsed))
        except Exception:
            pass

    if not skills:
        console.print("[yellow]No SKILL.md files found.[/yellow]")
        return

    table = Table(title="Skills", show_header=True, header_style="bold cyan")
    table.add_column("ID")
    table.add_column("Version")
    table.add_column("Tags")
    table.add_column("Path", style="dim")

    for fpath, s in skills:
        rel = fpath.relative_to(root)
        table.add_row(s.id, s.version, ", ".join(s.tags) or "—", str(rel))

    console.print(table)


@list_app.command(name="rules")
def list_rules(
    path: Annotated[Path, typer.Argument(help="Repo root to scan (default: CWD).")] = Path("."),
) -> None:
    """List all RULE.md files in the repo."""
    from agentmd.models import RuleFile
    from agentmd.parser import find_all_agentmd_files, parse_file

    root = path.resolve()
    files = find_all_agentmd_files(root)

    rules: list[tuple[Path, RuleFile]] = []
    for fpath in files:
        try:
            parsed = parse_file(fpath)
            if isinstance(parsed, RuleFile):
                rules.append((fpath, parsed))
        except Exception:
            pass

    if not rules:
        console.print("[yellow]No RULE.md files found.[/yellow]")
        return

    table = Table(title="Rules", show_header=True, header_style="bold cyan")
    table.add_column("ID")
    table.add_column("Severity")
    table.add_column("Applies To")
    table.add_column("Path", style="dim")

    severity_styles = {"error": "red", "warning": "yellow", "info": "blue"}

    for fpath, r in rules:
        rel = fpath.relative_to(root)
        sev_style = severity_styles.get(r.severity, "white")
        table.add_row(
            r.id,
            Text(r.severity, style=sev_style),
            ", ".join(r.applies_to),
            str(rel),
        )

    console.print(table)


# ---------------------------------------------------------------------------
# add skill / add rule
# ---------------------------------------------------------------------------


@add_app.command(name="skill")
def add_skill_cmd(
    skill_id: Annotated[str, typer.Argument(help="Kebab-case skill ID (e.g. scaffold-component).")],
    path: Annotated[Path, typer.Argument(help="Directory to create the skill in (default: CWD).")] = Path("."),
    no_register: Annotated[bool, typer.Option("--no-register", help="Skip auto-registration in AGENTS.md.")] = False,
) -> None:
    """Scaffold a new SKILL.md from template."""
    target_dir = path.resolve()
    out_path = add_skill(skill_id, target_dir, register=not no_register)
    console.print(f"[green]created[/green]  {out_path}")
    if not no_register:
        console.print(f"[dim]Registered in nearest AGENTS.md (if found).[/dim]")


@add_app.command(name="rule")
def add_rule_cmd(
    rule_id: Annotated[str, typer.Argument(help="Kebab-case rule ID (e.g. no-raw-sql).")],
    path: Annotated[Path, typer.Argument(help="Directory to create the rule in (default: CWD).")] = Path("."),
    no_register: Annotated[bool, typer.Option("--no-register", help="Skip auto-registration in AGENTS.md.")] = False,
) -> None:
    """Scaffold a new RULE.md from template."""
    target_dir = path.resolve()
    out_path = add_rule(rule_id, target_dir, register=not no_register)
    console.print(f"[green]created[/green]  {out_path}")
    if not no_register:
        console.print(f"[dim]Registered in nearest AGENTS.md (if found).[/dim]")


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


@app.command()
def export(
    file: Annotated[Path, typer.Argument(help="Target file to export context for.")],
    output: Annotated[Optional[Path], typer.Option("--output", "-o", help="Write JSON to file.")] = None,
) -> None:
    """Export resolved context as JSON (for tool integration)."""
    target = file.resolve()
    ctx = resolve(target)
    data = export_context(ctx)
    json_str = json.dumps(data, indent=2)

    if output:
        output.write_text(json_str)
        console.print(f"[green]Exported[/green] context to {output}")
    else:
        sys.stdout.write(json_str + "\n")


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------


@app.command()
def check(
    file: Annotated[Path, typer.Argument(help="File to check rules against.")],
) -> None:
    """Check which rules apply to a file and report pattern violations."""
    from agentmd.checker import check_file

    target = file.resolve()
    ctx = resolve(target)

    if not ctx.active_rules:
        console.print(f"[green]No rules apply to[/green] {target}")
        return

    violations = check_file(target, ctx)

    table = Table(title=f"Rule Check: {target.name}", show_header=True, header_style="bold cyan")
    table.add_column("Rule ID")
    table.add_column("Severity")
    table.add_column("Status")
    table.add_column("Detail")

    severity_styles = {"error": "red", "warning": "yellow", "info": "blue"}
    has_errors = False

    for rule in ctx.active_rules:
        sev_style = severity_styles.get(rule.severity, "white")
        if rule.id in violations:
            detail = violations[rule.id]
            table.add_row(
                rule.id,
                Text(rule.severity, style=sev_style),
                "[red]✗ violation[/red]",
                detail,
            )
            if rule.severity == "error":
                has_errors = True
        else:
            table.add_row(rule.id, Text(rule.severity, style=sev_style), "[green]✓ ok[/green]", "")

    console.print(table)

    if has_errors:
        err_console.print("\n[red]Error-level rule violations found.[/red]")
        raise typer.Exit(1)
