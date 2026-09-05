import typer

from policygraph import extract, fetch, graph, insights, normalize, resolve

app = typer.Typer(no_args_is_help=True)
for name, mod in (
    ("fetch", fetch),
    ("normalize", normalize),
    ("extract", extract),
    ("resolve", resolve),
    ("graph", graph),
    ("insights", insights),
):
    app.command(name)(mod.run)

if __name__ == "__main__":
    app()
