from __future__ import annotations

from flask import Flask

from app import create_app


def get_app() -> Flask:
    return create_app()


app = get_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
