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
from agentmd.scaffolder import add_rule, add_skill, init_repo

app = typer.Typer(
    name="agentmd",
    help="The open standard for AI context in codebases.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
list_app = typer.Typer(help="List agentmd artifacts in the repo.", no_args_is_help=True)
add_app = typer.Typer(help="Scaffold a new agentmd artifact.", no_args_is_help=True)
trust_app = typer.Typer(help="Manage the SKILL.md trust store.", no_args_is_help=True)
app.add_typer(list_app, name="list")
app.add_typer(add_app, name="add")
app.add_typer(trust_app, name="trust")

console = Console()
err_console = Console(stderr=True)

_SEV_COLOR = {"critical": "bold red", "error": "red", "warning": "yellow", "info": "blue"}
_TRUST_COLOR = {"trusted": "green", "changed": "red", "new": "yellow", "missing": "dim"}


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
    """agentmd — structured AI context for codebases."""


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
    check_drift: Annotated[bool, typer.Option("--drift", help="Also check for context drift.")] = False,
    check_trust: Annotated[bool, typer.Option("--trust", help="Also verify SKILL.md trust state.")] = False,
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
        rel = _rel(fpath, root)
        table.add_row(rel, "[green]✓ valid[/green]", "")
    for fpath, msg in errors:
        rel = _rel(fpath, root)
        table.add_row(rel, "[red]✗ error[/red]", msg[:120])

    console.print(table)

    exit_code = 0

    if errors:
        err_console.print(f"\n[red]{len(errors)} schema error(s) found.[/red]")
        exit_code = 1
    else:
        console.print(f"\n[green]All {len(valid)} file(s) valid.[/green]")

    # Optional drift check
    if check_drift:
        _print_drift(root)

    # Optional trust check
    if check_trust:
        _print_trust_summary(root)

    if exit_code:
        raise typer.Exit(exit_code)


def _print_drift(root: Path) -> None:
    from agentmd.discovery import check_drift as _check_drift
    from agentmd.models import AgentsFile

    agents_path = root / "AGENTS.md"
    if not agents_path.exists():
        console.print("\n[dim]Drift check skipped — no AGENTS.md at root.[/dim]")
        return

    try:
        parsed = parse_file(agents_path)
    except ParseError:
        return

    if not isinstance(parsed, AgentsFile):
        return

    issues = _check_drift(parsed, root)
    if not issues:
        console.print("\n[green]No context drift detected.[/green]")
        return

    table = Table(title="Context Drift", show_header=True, header_style="bold yellow")
    table.add_column("Kind")
    table.add_column("Issue")
    table.add_column("Suggestion", style="dim")

    for issue in issues:
        table.add_row(issue.kind, issue.message, issue.suggestion)

    console.print(table)
    console.print(f"\n[yellow]{len(issues)} drift issue(s) found.[/yellow]")


def _print_trust_summary(root: Path) -> None:
    from agentmd.trust import verify_all_skills

    results = verify_all_skills(root)
    if not results:
        console.print("\n[dim]No SKILL.md files to verify.[/dim]")
        return

    table = Table(title="SKILL.md Trust", show_header=True, header_style="bold cyan")
    table.add_column("File", style="dim")
    table.add_column("Status")
    table.add_column("Trusted At", style="dim")

    for r in results:
        color = _TRUST_COLOR.get(r.status, "white")
        rel = _rel(r.path, root)
        table.add_row(rel, Text(r.status, style=color), r.trusted_at or "—")

    console.print(table)

    untrusted = [r for r in results if r.status != "trusted"]
    if untrusted:
        console.print(
            f"\n[yellow]{len(untrusted)} untrusted SKILL.md file(s). "
            "Run [cyan]agentmd trust add <file>[/cyan] to mark as trusted.[/yellow]"
        )
    else:
        console.print(f"\n[green]All {len(results)} SKILL.md file(s) trusted.[/green]")


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
        sf = ctx.source_files[0] if ctx.source_files else ""
        console.print(f"\n[bold]AGENTS.md[/bold] — [dim]{sf}[/dim]")
        console.print(f"  name:  {a.name}")
        console.print(f"  scope: {a.scope}")

        # Show merged stack when it differs from agents_file.stack
        display_stack = ctx.merged_stack if ctx.merged_stack else a.stack
        console.print(f"  stack: {', '.join(display_stack) or '(none)'}")
        if ctx.merged_stack != a.stack:
            console.print(f"  [dim](merged from multiple AGENTS.md files)[/dim]")

        if ctx.merged_conventions:
            console.print("  conventions:")
            for c in ctx.merged_conventions[:8]:
                console.print(f"    • {c}")
            if len(ctx.merged_conventions) > 8:
                console.print(f"    [dim]… and {len(ctx.merged_conventions) - 8} more[/dim]")
        if a.agent_instructions:
            preview = a.agent_instructions[:120].strip()
            console.print(f"  agent_instructions: [dim]{preview}…[/dim]")
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
            color = _SEV_COLOR.get(r.severity, "white")
            immutable_tag = " [dim][immutable][/dim]" if r.immutable else ""
            console.print(
                f"  [{color}]{r.severity}[/{color}] [cyan]{r.id}[/cyan]{immutable_tag} — {r.description}"
            )
    else:
        console.print("\n[dim]No active rules for this file.[/dim]")

    if ctx.prompt_snippets:
        from rich.markup import escape

        console.print(f"\n[bold]Prompt Snippets[/bold] ({len(ctx.prompt_snippets)})")
        console.print(
            "  [dim]Paste these into your agent prompt or use via MCP (agentmd mcp).[/dim]"
        )
        for snippet in ctx.prompt_snippets:
            console.print(f"\n  [green]•[/green] {escape(snippet)}")
    else:
        console.print("\n[dim]No prompt snippets (no active skills in scope).[/dim]")

    if ctx.warnings:
        console.print(f"\n[bold yellow]Warnings[/bold yellow] ({len(ctx.warnings)})")
        for w in ctx.warnings:
            console.print(f"  [yellow]⚠[/yellow]  {w}")

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

    root = path.resolve()
    skills: list[tuple[Path, SkillFile]] = []
    for fpath in find_all_agentmd_files(root):
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
        table.add_row(s.id, s.version, ", ".join(s.tags) or "—", _rel(fpath, root))

    console.print(table)


@list_app.command(name="rules")
def list_rules(
    path: Annotated[Path, typer.Argument(help="Repo root to scan (default: CWD).")] = Path("."),
) -> None:
    """List all RULE.md files in the repo."""
    from agentmd.models import RuleFile

    root = path.resolve()
    rules: list[tuple[Path, RuleFile]] = []
    for fpath in find_all_agentmd_files(root):
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
    table.add_column("Immutable")
    table.add_column("Applies To")
    table.add_column("Path", style="dim")

    for fpath, r in rules:
        color = _SEV_COLOR.get(r.severity, "white")
        immutable_str = "[bold red]yes[/bold red]" if r.immutable else "—"
        table.add_row(
            r.id,
            Text(r.severity, style=color),
            immutable_str,
            ", ".join(r.applies_to),
            _rel(fpath, root),
        )

    console.print(table)


# ---------------------------------------------------------------------------
# add skill / add rule
# ---------------------------------------------------------------------------


@add_app.command(name="skill")
def add_skill_cmd(
    skill_id: Annotated[str, typer.Argument(help="Kebab-case skill ID.")],
    path: Annotated[Path, typer.Argument(help="Directory (default: CWD).")] = Path("."),
    no_register: Annotated[bool, typer.Option("--no-register", help="Skip auto-registration.")] = False,
) -> None:
    """Scaffold a new SKILL.md from template."""
    out_path = add_skill(skill_id, path.resolve(), register=not no_register)
    console.print(f"[green]created[/green]  {out_path}")
    if not no_register:
        console.print("[dim]Registered in nearest AGENTS.md (if found).[/dim]")


@add_app.command(name="rule")
def add_rule_cmd(
    rule_id: Annotated[str, typer.Argument(help="Kebab-case rule ID.")],
    path: Annotated[Path, typer.Argument(help="Directory (default: CWD).")] = Path("."),
    no_register: Annotated[bool, typer.Option("--no-register", help="Skip auto-registration.")] = False,
) -> None:
    """Scaffold a new RULE.md from template."""
    out_path = add_rule(rule_id, path.resolve(), register=not no_register)
    console.print(f"[green]created[/green]  {out_path}")
    if not no_register:
        console.print("[dim]Registered in nearest AGENTS.md (if found).[/dim]")


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


@app.command()
def export(
    file: Annotated[Path, typer.Argument(help="Target file to export context for.")],
    output: Annotated[Optional[Path], typer.Option("--output", "-o", help="Write JSON to file.")] = None,
    json_flag: Annotated[bool, typer.Option("--json/--no-json", help="Output as JSON (default; accepted for scripting compatibility).")] = False,
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
    """Check a file for rule violations (AST + pattern analysis)."""
    from agentmd.checker import check_file

    target = file.resolve()
    ctx = resolve(target)

    if not ctx.active_rules:
        console.print(f"[green]No rules apply to[/green] {target.name}")
        return

    violations = check_file(target, ctx)

    table = Table(title=f"Rule Check: {target.name}", show_header=True, header_style="bold cyan")
    table.add_column("Rule ID")
    table.add_column("Severity")
    table.add_column("Status")
    table.add_column("Violations")

    has_errors = False
    # Map rule ID → severity for display
    rule_map = {r.id: r for r in ctx.active_rules}

    for rule in ctx.active_rules:
        color = _SEV_COLOR.get(rule.severity, "white")
        if rule.id in violations:
            viols = violations[rule.id]
            detail_lines = []
            for v in viols[:5]:
                loc = f"line {v.line}" if v.line else "—"
                detail_lines.append(f"  {loc}: {v.message}")
            if len(viols) > 5:
                detail_lines.append(f"  … and {len(viols) - 5} more")
            detail = "\n".join(detail_lines)
            table.add_row(
                rule.id,
                Text(rule.severity, style=color),
                f"[red]✗ {len(viols)} violation(s)[/red]",
                detail,
            )
            if rule.severity == "error":
                has_errors = True
        else:
            table.add_row(rule.id, Text(rule.severity, style=color), "[green]✓ ok[/green]", "")

    console.print(table)

    if has_errors:
        err_console.print("\n[red]Error-level rule violations found.[/red]")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------


@app.command()
def audit(
    path: Annotated[Path, typer.Argument(help="Repo root (default: CWD).")] = Path("."),
    output_json: Annotated[bool, typer.Option("--json", help="Output full report as JSON.")] = False,
) -> None:
    """Comprehensive audit: validate + check all rules + drift + trust."""
    from agentmd.auditor import run_audit

    root = path.resolve()
    report = run_audit(root)

    if output_json:
        sys.stdout.write(json.dumps(report.to_dict(), indent=2) + "\n")
        return

    console.print(f"[bold]agentmd audit[/bold] — [dim]{root}[/dim]\n")

    # --- Schema validation ---
    _print_section("Schema Validation")
    if not report.validation:
        console.print("  [dim]No agentmd files found.[/dim]")
    else:
        for r in report.validation:
            if r.valid:
                console.print(f"  [green]✓[/green] {_rel(r.path, root)}")
            else:
                console.print(f"  [red]✗[/red] {_rel(r.path, root)}: {r.error}")

    # --- Rule violations ---
    _print_section("Rule Violations")
    if not report.violations:
        console.print("  [green]No violations found.[/green]")
    else:
        for fpath, fv in sorted(report.violations.items()):
            console.print(f"\n  [bold]{_rel(fpath, root)}[/bold]")
            for rule_id, viols in fv.violations.items():
                for v in viols:
                    loc = f":{v.line}" if v.line else ""
                    console.print(f"    [red]{rule_id}[/red]{loc} — {v.message}")

    # --- Drift ---
    _print_section("Context Drift")
    if not report.drift:
        console.print("  [green]No drift detected.[/green]")
    else:
        for issue in report.drift:
            console.print(f"  [yellow]⚠[/yellow]  {issue.message}")
            if issue.suggestion:
                console.print(f"     [dim]{issue.suggestion}[/dim]")

    # --- Trust ---
    _print_section("SKILL.md Trust")
    if not report.trust:
        console.print("  [dim]No SKILL.md files found.[/dim]")
    else:
        for r in report.trust:
            color = _TRUST_COLOR.get(r.status, "white")
            console.print(f"  [{color}]{r.status:8}[/{color}]  {_rel(r.path, root)}")

    # --- Summary ---
    _print_section("Summary")
    ok = "[green]✓[/green]"
    ng = "[red]✗[/red]"
    console.print(
        f"  {ok if not report.validation_errors else ng} "
        f"Schema: {len(report.validation) - len(report.validation_errors)}/{len(report.validation)} valid"
    )
    console.print(
        f"  {ok if report.error_violations == 0 else ng} "
        f"Rule violations: {report.total_violations} total, {report.error_violations} errors"
    )
    console.print(
        f"  {ok if not report.drift else '[yellow]⚠[/yellow]'} "
        f"Drift: {len(report.drift)} issue(s)"
    )
    console.print(
        f"  {ok if not report.untrusted_skills else '[yellow]⚠[/yellow]'} "
        f"Trust: {len(report.trust) - len(report.untrusted_skills)}/{len(report.trust)} trusted"
    )

    if report.passed:
        console.print("\n[bold green]Audit passed.[/bold green]")
    else:
        err_console.print("\n[bold red]Audit failed.[/bold red]")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# commit
# ---------------------------------------------------------------------------


@app.command()
def commit(
    root: Annotated[Path, typer.Argument(help="Repo root (default: CWD).")] = Path("."),
    check_only: Annotated[bool, typer.Option("--check-only", help="Exit with error on violations; do not print scope suggestion.")] = False,
    output_json: Annotated[bool, typer.Option("--json", help="Output full analysis as JSON.")] = False,
) -> None:
    """Guard staged files against rule violations and suggest a semantic commit scope.

    Checks every staged file against its active agentmd rules (including
    linter_command and linter_regex).  Critical-severity violations block the
    commit (exit 1).  Non-critical violations are shown as warnings.

    On a clean diff the command prints a suggested conventional-commit message
    template using the resolved scope and inferred commit type.

    Use as a pre-commit hook::

      agentmd commit --check-only
    """
    from agentmd.committer import analyze_staged

    repo_root = root.resolve()
    analysis = analyze_staged(repo_root)

    if output_json:
        import dataclasses

        def _serialise(obj: object) -> object:
            if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
                return {k: _serialise(v) for k, v in dataclasses.asdict(obj).items()}
            if isinstance(obj, Path):
                return str(obj)
            if isinstance(obj, list):
                return [_serialise(i) for i in obj]
            if isinstance(obj, dict):
                return {str(k): _serialise(v) for k, v in obj.items()}
            return obj

        out = {
            "staged_files": [str(f) for f in analysis.staged_files],
            "violations": [_serialise(v) for v in analysis.violations],
            "suggested_scope": analysis.suggested_scope,
            "suggested_type": analysis.suggested_type,
            "is_blocked": analysis.is_blocked,
            "suggested_message": analysis.format_message(),
        }
        sys.stdout.write(json.dumps(out, indent=2) + "\n")
        if analysis.is_blocked:
            raise typer.Exit(1)
        return

    if not analysis.staged_files:
        console.print("[dim]No staged files found. Run git add first.[/dim]")
        return

    # ---- Violation report ----
    if analysis.violations:
        table = Table(
            title="Staged File Violations",
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("File")
        table.add_column("Rule")
        table.add_column("Sev")
        table.add_column("Location")
        table.add_column("Message")

        for v in analysis.violations:
            color = _SEV_COLOR.get(v.severity, "white")
            loc = f":{v.line}" if v.line else ""
            rel = _rel(v.file, repo_root)
            table.add_row(
                rel,
                v.rule_id,
                Text(v.severity, style=color),
                f"{rel}{loc}",
                v.message[:80],
            )

        console.print(table)

        if analysis.critical_violations:
            err_console.print(
                f"\n[bold red]⛔  Commit blocked:[/bold red] "
                f"{len(analysis.critical_violations)} critical violation(s). "
                "Fix before committing."
            )
            raise typer.Exit(1)

        # Non-critical: warn but allow
        err_console.print(
            f"\n[yellow]⚠  {len(analysis.error_violations)} error violation(s) found.[/yellow] "
            "Commit is not blocked (no critical violations)."
        )
    else:
        console.print("[green]✓ No rule violations in staged files.[/green]")

    if check_only:
        return

    # ---- Scope suggestion ----
    console.print()
    _print_section("Suggested Commit")
    console.print(f"  [bold]{analysis.format_message()}[/bold]")
    if analysis.suggested_scope:
        console.print(f"  [dim]Scope detected from: agentmd context[/dim]")
    console.print(f"  [dim]Type inferred: {analysis.suggested_type}[/dim]")
    console.print(
        f"\n  Staged: {len(analysis.staged_files)} file(s) — "
        + ", ".join(_rel(f, repo_root) for f in analysis.staged_files[:4])
        + (" …" if len(analysis.staged_files) > 4 else "")
    )


# ---------------------------------------------------------------------------
# trust
# ---------------------------------------------------------------------------


@trust_app.command(name="add")
def trust_add(
    file: Annotated[Path, typer.Argument(help="SKILL.md file to trust.")],
    root: Annotated[Optional[Path], typer.Option("--root", help="Repo root for the trust store.")] = None,
) -> None:
    """Mark a SKILL.md file as trusted (record its checksum)."""
    from agentmd.trust import trust_file

    target = file.resolve()
    repo_root = root.resolve() if root else None
    result = trust_file(target, root=repo_root)
    console.print(f"[green]trusted[/green]  {target}")
    console.print(f"  sha256: [dim]{result.current_hash}[/dim]")
    console.print(f"  at:     [dim]{result.trusted_at}[/dim]")


@trust_app.command(name="remove")
def trust_remove(
    file: Annotated[Path, typer.Argument(help="SKILL.md file to untrust.")],
    root: Annotated[Optional[Path], typer.Option("--root", help="Repo root for the trust store.")] = None,
) -> None:
    """Remove a file from the trust store."""
    from agentmd.trust import untrust_file

    target = file.resolve()
    repo_root = root.resolve() if root else None
    removed = untrust_file(target, root=repo_root)
    if removed:
        console.print(f"[yellow]removed[/yellow]  {target}")
    else:
        console.print(f"[dim]Not in trust store:[/dim] {target}")


@trust_app.command(name="status")
def trust_status(
    path: Annotated[Path, typer.Argument(help="Repo root to scan (default: CWD).")] = Path("."),
) -> None:
    """Show trust status for all SKILL.md files."""
    from agentmd.trust import verify_all_skills

    root = path.resolve()
    results = verify_all_skills(root)

    if not results:
        console.print("[yellow]No SKILL.md files found.[/yellow]")
        return

    table = Table(title="SKILL.md Trust Status", show_header=True, header_style="bold cyan")
    table.add_column("Status")
    table.add_column("File", style="dim")
    table.add_column("Trusted At", style="dim")

    for r in results:
        color = _TRUST_COLOR.get(r.status, "white")
        table.add_row(
            Text(r.status, style=color),
            _rel(r.path, root),
            r.trusted_at or "—",
        )

    console.print(table)


# ---------------------------------------------------------------------------
# mcp
# ---------------------------------------------------------------------------


@app.command()
def mcp(
    root: Annotated[Optional[Path], typer.Option("--root", help="Repo root (default: CWD).")] = None,
) -> None:
    """Start the agentmd MCP server (JSON-RPC over stdio)."""
    from agentmd.mcp_server import run_server

    resolved_root = root.resolve() if root else Path(".").resolve()
    run_server(root=resolved_root)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _print_section(title: str) -> None:
    console.print(f"\n[bold cyan]{title}[/bold cyan]")
    console.print("─" * 60)
