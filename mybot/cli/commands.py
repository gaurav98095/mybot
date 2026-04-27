import typer

app = typer.Typer()

@app.command()
def onboard():
    print("Hello World")


@app.command()
def gk():
    print("Hello GK")