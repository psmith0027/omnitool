import json
import os
import subprocess
from pathlib import Path

import typer

app = typer.Typer()

DEV_CONTAINER_DIR = ".devcontainer"
DEV_CONTAINER_JSON = "devcontainer.json"
DEV_CONTAINER_JSON_ALT = ".devcontainer.json"


def _find_devcontainer() -> Path | None:
    cwd = Path.cwd()

    for p in [cwd / DEV_CONTAINER_DIR, cwd / DEV_CONTAINER_JSON_ALT]:
        if p.exists():
            return p

    for child in cwd.iterdir():
        if child.is_dir() and not child.name.startswith("."):
            dev_dir = child / DEV_CONTAINER_DIR
            if dev_dir.exists():
                return dev_dir

    for child in cwd.iterdir():
        if child.is_dir() and not child.name.startswith("."):
            dev_json = child / DEV_CONTAINER_JSON_ALT
            if dev_json.exists():
                return dev_json

    return None


def _load_config(path: Path) -> dict:
    if path.is_dir():
        json_path = path / DEV_CONTAINER_JSON
    else:
        json_path = path

    with open(json_path) as f:
        return json.load(f)


def _container_name(config: dict, devcontainer_path: Path) -> str:
    name = config.get("name") or devcontainer_path.parent.stem
    return name.lower().replace("_", "-").replace(" ", "-")


def _build_image(config: dict, devcontainer_path: Path, image_tag: str):
    build = config.get("build", {})
    dockerfile = build.get("dockerfile", "Dockerfile")

    if devcontainer_path.is_dir():
        dockerfile_path = devcontainer_path / dockerfile
        context = devcontainer_path / build.get("context", ".")
    else:
        dockerfile_path = devcontainer_path.parent / dockerfile
        context = devcontainer_path.parent / build.get("context", ".")

    dockerfile_path = dockerfile_path.resolve()
    context = context.resolve()

    if not dockerfile_path.exists():
        typer.echo(f"Dockerfile not found: {dockerfile_path}")
        raise typer.Exit(1)

    typer.echo(f"Building image from {dockerfile_path}...")
    result = subprocess.run(
        ["docker", "build", "-f", str(dockerfile_path), "-t", image_tag, str(context)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        typer.echo(f"Build failed:\n{result.stderr}")
        raise typer.Exit(1)
    typer.echo("Build complete.")


def _running_container(name: str) -> str | None:
    result = subprocess.run(
        ["docker", "ps", "--filter", f"name=^{name}$", "--format", "{{.Names}}"],
        capture_output=True, text=True,
    )
    names = result.stdout.strip().split("\n")
    for n in names:
        if n == name:
            return n
    return None


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


@app.command()
def list():
    """List running containers."""
    result = subprocess.run(
        ["docker", "ps", "--filter", "label=devcontainer", "--format", "table {{.ID}}\t{{.Names}}\t{{.Status}}"],
        capture_output=True, text=True,
    )
    if result.stdout.strip():
        typer.echo(result.stdout)
    else:
        typer.echo("No dev containers running.")


def _start_container(name: str, config: dict, devcontainer_path: Path):
    image_tag = f"devcontainer-{name}:latest"

    _build_image(config, devcontainer_path, image_tag)

    workspace_folder = config.get("workspaceFolder", "/workspace")
    workspace_mount = Path.cwd()

    typer.echo(f"Starting container '{name}'...")
    result = subprocess.run([
        "docker", "run", "-d",
        "--name", name,
        "--label", "devcontainer",
        "-w", workspace_folder,
        "-v", f"{workspace_mount}:{workspace_folder}",
        image_tag,
        "sleep", "infinity",
    ], capture_output=True, text=True)

    if result.returncode != 0:
        typer.echo(f"Failed to start container:\n{result.stderr}")
        raise typer.Exit(1)

    typer.echo(f"Container '{name}' started.")


def _resolve() -> tuple[dict, str, Path] | None:
    devcontainer_path = _find_devcontainer()
    if not devcontainer_path:
        return None
    config = _load_config(devcontainer_path)
    name = _container_name(config, devcontainer_path)
    return config, name, devcontainer_path


@app.command()
def up():
    """Build (if needed) and start the dev container."""
    resolved = _resolve()
    if not resolved:
        typer.echo("No dev container configuration found in current directory or subdirectories.")
        raise typer.Exit(1)

    config, name, devcontainer_path = resolved

    if _running_container(name):
        typer.echo(f"Container '{name}' is already running.")
        return

    _start_container(name, config, devcontainer_path)


@app.command(name="down")
def down():
    """Stop and remove the dev container."""
    resolved = _resolve()
    if not resolved:
        typer.echo("No dev container configuration found.")
        raise typer.Exit(1)

    _, name, _ = resolved

    if not _running_container(name):
        typer.echo(f"Container '{name}' is not running.")
        return

    typer.echo(f"Stopping '{name}'...")
    subprocess.run(["docker", "stop", name], capture_output=True, text=True)
    subprocess.run(["docker", "rm", name], capture_output=True, text=True)
    typer.echo(f"Container '{name}' removed.")


@app.command()
def attach():
    """Attach to the running dev container (exec into it)."""
    resolved = _resolve()
    if not resolved:
        typer.echo("No dev container configuration found.")
        raise typer.Exit(1)

    _, name, _ = resolved

    if not _running_container(name):
        typer.echo(f"Container '{name}' is not running. Start it with 'omni containers up'.")
        raise typer.Exit(1)

    typer.echo(f"Attaching to '{name}'...")
    os.execvp("docker", ["docker", "exec", "-it", name, "/bin/bash"])


@app.command()
def shell():
    """Start (if needed) and enter the dev container interactively."""
    resolved = _resolve()
    if not resolved:
        typer.echo("No dev container configuration found.")
        raise typer.Exit(1)

    config, name, devcontainer_path = resolved

    if not _running_container(name):
        typer.echo(f"Container '{name}' is not running — starting it...")
        _start_container(name, config, devcontainer_path)
        if not _running_container(name):
            typer.echo("Failed to start container.")
            raise typer.Exit(1)

    os.execvp("docker", ["docker", "exec", "-it", name, "/bin/bash"])
