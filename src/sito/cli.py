"""Command line: ``sito serve`` and ``sito demo``."""

from __future__ import annotations

import argparse

from sito import __version__
from sito.config import AppConfig


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", help="interface to bind (default 127.0.0.1, env SITO_HOST)")
    parser.add_argument("--port", type=int, help="port (default 8765, env SITO_PORT)")
    parser.add_argument("--data-dir", help="where the database, exports and plugins live (env SITO_DATA_DIR)")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="sito", description="Visual, modular keyword research pipeline.")
    parser.add_argument("--version", action="version", version=f"sito {__version__}")
    sub = parser.add_subparsers(dest="command")
    _add_common(sub.add_parser("serve", help="start the web app (default)"))
    demo = sub.add_parser(
        "demo", help="create a sample project with synthetic data, run its pipeline offline, then start the app"
    )
    _add_common(demo)
    demo.add_argument("--no-serve", action="store_true", help="only create and run the demo project")
    args = parser.parse_args(argv)

    overrides = {
        "host": getattr(args, "host", None),
        "port": getattr(args, "port", None),
        "data_dir": getattr(args, "data_dir", None),
    }
    config = AppConfig.from_env(**{k: v for k, v in overrides.items() if v})

    from sito.web.app import create_app

    # A one-off `demo --no-serve` may share the data folder with a running server: don't
    # mark that server's runs as interrupted.
    app = create_app(config, recover=not (args.command == "demo" and args.no_serve))
    base = f"http://{config.host}:{config.port}"

    if args.command == "demo":
        from sito.demo import create_demo

        state = app.state.sito
        print("Creating the demo project and running its pipeline with the offline demo connectors…")
        project_id = create_demo(state.session_factory, state.registry, config)
        print(f"Done. Open {base}/projects/{project_id}/keywords (all data in it is synthetic).")
        if args.no_serve:
            return

    import uvicorn

    print(f"sito {__version__} → {base}   (data: {config.data_dir})")
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":  # pragma: no cover
    main()
