import typer

from .tools import containers, tmux

app = typer.Typer()


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


app.add_typer(containers.app, name="containers", help="Manage containers.")
app.add_typer(tmux.app, name="tmux", help="Manage tmux sessions.")


@app.command()
def hello():
    """Say hello."""
    typer.echo("Hello from omnitool!")


@app.command()
def version():
    """Show the version."""
    typer.echo("omnitool v0.1.0")


if __name__ == "__main__":
    app()
