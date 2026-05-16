"""Entry point for `python -m cobo`."""

from cobo.cli import app


def main() -> None:
    """Invoke the Typer app."""
    app()


if __name__ == "__main__":
    main()
