import click


@click.group()
def cli() -> None:
    """Sites Report — site analytics reports from GA4, GSC, and Vercel."""
