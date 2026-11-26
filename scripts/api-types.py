"""Generate TypeScript from the mounted FastAPI endpoints with shared contracts."""

import argparse
import json
import subprocess
from pathlib import Path

from app.api.coach import get_proposals
from app.main import app
from fastapi.openapi.utils import get_openapi
from fastapi.routing import iter_route_contexts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="check the committed types without writing"
    )
    args = parser.parse_args()

    (proposal_list,) = (
        route
        for route in iter_route_contexts(app.routes)
        if route.endpoint is get_proposals
    )
    schema = get_openapi(title=app.title, version=app.version, routes=[proposal_list])
    frontend = Path(__file__).resolve().parents[1] / "frontend"
    command = [
        "node_modules/.bin/openapi-typescript",
        "-o",
        "src/api/generated/proposalList.ts",
    ]
    if args.check:
        command.append("--check")
    subprocess.run(
        command, cwd=frontend, input=json.dumps(schema), text=True, check=True
    )


if __name__ == "__main__":
    main()
