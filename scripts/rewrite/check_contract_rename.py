"""Exercise the Go and Home proposal contract by renaming a field in a private copy."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def change(path: Path, old: str, new: str) -> None:
    source = path.read_text()
    if old not in source:
        raise ValueError(f"expected {old!r} in {path.name}")
    path.write_text(source.replace(old, new))


def run(cwd: Path, *command: str, expected: tuple[str, ...] = ()) -> None:
    result = subprocess.run(command, check=False, cwd=cwd, capture_output=True, text=True)
    output = result.stdout + result.stderr
    if expected:
        diagnostic = next(
            (
                line
                for line in output.splitlines()
                if all(text in line for text in expected)
            ),
            None,
        )
        if result.returncode == 0 or diagnostic is None:
            raise SystemExit(f"unexpected result for {' '.join(command)}\n{output}")
        print(diagnostic)
    elif result.returncode:
        raise SystemExit(f"{' '.join(command)} failed\n{output}")
    else:
        print(f"passed: {' '.join(command)}")


def verify(work: Path) -> None:
    for relative in [
        "Makefile",
        "scripts/run",
        "scripts/env.sh",
        "scripts/api-types.py",
    ]:
        dest = work / relative
        dest.parent.mkdir(exist_ok=True)
        shutil.copy2(ROOT / relative, dest)
    shutil.copytree(ROOT / "backend-go", work / "backend-go")
    frontend = work / "frontend"
    shutil.copytree(
        ROOT / "frontend",
        frontend,
        ignore=shutil.ignore_patterns(
            "node_modules",
            "dist",
            "*.tsbuildinfo",
            "test-results",
            "playwright-report",
        ),
    )
    (frontend / "node_modules").symlink_to(
        ROOT / "frontend/node_modules", target_is_directory=True
    )
    contract = work / "backend-go/api/openapi.json"
    doc = json.loads(contract.read_text())
    summary = doc["components"]["schemas"]["ProposalSummary"]
    summary["properties"]["proposed_change_count"] = summary["properties"].pop(
        "change_count"
    )
    required = summary["required"]
    required[required.index("change_count")] = "proposed_change_count"
    contract.write_text(json.dumps(doc, indent=2) + "\n")

    run(work, "make", "check-api-types", expected=("api.gen.go differs",))
    run(work, "make", "generate-api-types")
    run(work, "make", "check-api-types")

    module = work / "backend-go"
    run(
        module,
        "go",
        "build",
        "./...",
        expected=("internal/httpapi/proposals.go:", "unknown field ChangeCount"),
    )
    run(
        frontend,
        "npm",
        "run",
        "typecheck",
        expected=("src/pages/Home.tsx(", "Property 'change_count' does not exist"),
    )

    change(
        module / "internal/httpapi/proposals.go",
        "ChangeCount:",
        "ProposedChangeCount:",
    )
    for name in ["src/pages/Home.tsx", "src/api/types/coach.ts", "tests/home.test.tsx"]:
        change(frontend / name, "change_count", "proposed_change_count")
    run(module, "go", "build", "./...")
    run(frontend, "npm", "run", "typecheck")


if __name__ == "__main__":
    # The copied Makefile uses its own private/ path. Also expose tools from
    # the actual checkout so this works after the usual make setup-go.
    os.environ["PATH"] = (
        str(ROOT / "private/go-tools/bin") + os.pathsep + os.environ["PATH"]
    )
    scratch = ROOT / "private"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=scratch, prefix="proposal-rename-"
    ) as directory:
        verify(Path(directory))
