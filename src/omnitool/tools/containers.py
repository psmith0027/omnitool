import json
import os
import subprocess
import time
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


def _container_running(name: str) -> bool:
    result = subprocess.run(
        ["docker", "ps", "--filter", f"name=^{name}$", "--format", "{{.Names}}"],
        capture_output=True, text=True,
    )
    return name in result.stdout.strip().split("\n")


def _container_exists(name: str) -> bool:
    result = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.Names}}"],
        capture_output=True, text=True,
    )
    return name in result.stdout.strip().split("\n")


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

    if _container_exists(name):
        typer.echo(f"Removing existing container '{name}'...")
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, text=True)

    workspace_folder = config.get("workspaceFolder", "/workspace")
    workspace_mount = Path.cwd()

    docker_args = [
        "docker", "run", "-d",
        "--name", name,
        "--label", "devcontainer",
        "-w", workspace_folder,
        "-v", f"{workspace_mount}:{workspace_folder}",
    ]

    netrc = Path.home() / ".netrc"
    if netrc.exists():
        docker_args.extend(["-v", f"{netrc}:/root/.netrc:ro"])

    ssh_sock = os.environ.get("SSH_AUTH_SOCK")
    if ssh_sock and os.path.exists(ssh_sock):
        docker_args.extend(["-v", f"{ssh_sock}:{ssh_sock}", "-e", f"SSH_AUTH_SOCK={ssh_sock}"])

    gitconfig = Path.home() / ".gitconfig"
    if gitconfig.exists():
        docker_args.extend(["-v", f"{gitconfig}:/root/.gitconfig:ro"])

    docker_args.append(image_tag)
    docker_args.append("sleep infinity")

    typer.echo(f"Starting container '{name}'...")
    result = subprocess.run(docker_args, capture_output=True, text=True)

    if result.returncode != 0:
        typer.echo(f"Failed to start container:\n{result.stderr}")
        raise typer.Exit(1)

    for _ in range(10):
        if _container_running(name):
            typer.echo(f"Container '{name}' started.")
            return
        time.sleep(0.5)

    typer.echo(f"Failed to start container:\nContainer exited immediately.")
    raise typer.Exit(1)


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

    if _container_running(name):
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

    if not _container_exists(name):
        typer.echo(f"Container '{name}' does not exist.")
        return

    if _container_running(name):
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

    if not _container_running(name):
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

    if not _container_running(name):
        typer.echo(f"Container '{name}' is not running — starting it...")
        _start_container(name, config, devcontainer_path)

    os.execvp("docker", ["docker", "exec", "-it", name, "/bin/bash"])
