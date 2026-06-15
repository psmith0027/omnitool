import os
import subprocess
from typing import Optional

import typer

app = typer.Typer()


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


def _tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", *args], capture_output=True, text=True)


@app.command()
def list():
    """List tmux sessions."""
    result = _tmux("list-sessions")
    if result.returncode == 0:
        typer.echo(result.stdout)
    else:
        typer.echo("No tmux sessions found.")


@app.command()
def capture(
    target: str = typer.Argument(
        ":.", help="Pane to capture (e.g. 'mysession:main.0', ':.', ':top')."
    ),
    start: Optional[int] = typer.Option(
        None, "--start", "-S", help="Start line (0 = first line, negative = from end)."
    ),
    end: Optional[int] = typer.Option(
        None, "--end", "-E", help="End line (-1 = last line, negative = from end)."
    ),
):
    """Capture pane contents (defaults to full history)."""
    cmd = ["capture-pane", "-t", target, "-p"]
    if start is not None:
        cmd.extend(["-S", str(start)])
    if end is not None:
        cmd.extend(["-E", str(end)])
    result = _tmux(*cmd)
    if result.returncode == 0:
        typer.echo(result.stdout)
    else:
        typer.echo(f"Failed to capture pane:\n{result.stderr}")
        raise typer.Exit(1)


@app.command()
def new(
    session: str = typer.Argument(
        "myproject", help="Session name to create."
    ),
    path: str = typer.Option(".", "--path", "-p", help="Working directory."),
    attach: bool = typer.Option(True, "--attach/--no-attach", help="Attach after creation."),
):
    """Create a new tmux session with a predefined layout."""
    _tmux("kill-session", "-t", session)
    _tmux("new-session", "-d", "-s", session, "-n", "main", "-c", path)
    _tmux("split-window", "-h", "-p", "30", "-t", f"{session}:main", "-c", path)
    _tmux("split-window", "-v", "-p", "25", "-t", f"{session}:main.1", "-c", path)
    _tmux("select-pane", "-t", f"{session}:main.0")
    typer.echo(f"Session '{session}' created.")
    if attach:
        os.execvp("tmux", ["tmux", "attach", "-t", session])
