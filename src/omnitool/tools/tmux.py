import os
import signal
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


def _get_descendant_pids(pid: int) -> list[int]:
    """Recursively find all descendant PIDs of a given PID using ps."""
    try:
        result = subprocess.run(
            ["ps", "-eo", "ppid,pid"], capture_output=True, text=True
        )
        if result.returncode != 0:
            return []

        children: dict[int, list[int]] = {}
        for line in result.stdout.strip().split("\n")[1:]:
            parts = line.strip().split()
            if len(parts) == 2:
                ppid = int(parts[0])
                child = int(parts[1])
                children.setdefault(ppid, []).append(child)

        descendants: list[int] = []
        stack = [pid]
        while stack:
            p = stack.pop()
            for child in children.get(p, []):
                descendants.append(child)
                stack.append(child)
        return descendants
    except Exception:
        return []


@app.command(name="kill-all")
def kill_all():
    """Kill all tmux sessions, forcefully terminating every pane process."""
    my_pid = os.getpid()

    current_result = _tmux("display-message", "-p", "#{pane_id}")
    current_pane = current_result.stdout.strip() if current_result.returncode == 0 else None

    result = _tmux("list-panes", "-a", "-F", "#{pane_id}:#{pane_pid}")
    if result.returncode == 0 and result.stdout.strip():
        killed: set[int] = set()
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if not line or ":" not in line:
                continue
            pane_id, pid_str = line.split(":", 1)
            try:
                pid = int(pid_str)
            except ValueError:
                continue

            # Hard-kill all descendant processes (editors, servers, builds, etc.)
            for p in _get_descendant_pids(pid):
                if p != my_pid and p not in killed:
                    try:
                        os.kill(p, signal.SIGKILL)
                        killed.add(p)
                    except ProcessLookupError:
                        pass

            # Hard-kill the pane process itself, unless it's our own pane
            if pane_id != current_pane and pid not in killed:
                try:
                    os.kill(pid, signal.SIGKILL)
                    killed.add(pid)
                except ProcessLookupError:
                    pass

    result = _tmux("kill-server")
    if result.returncode == 0:
        typer.echo("All tmux sessions closed and all processes killed.")
    else:
        typer.echo("No tmux server running.")


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
