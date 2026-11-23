import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Built via concatenation so raw grep scans of the repository do not self-match.
FORBIDDEN_PATTERNS = (
    "/Users" + "/",
    "C:\\" + "Users\\",
    "/work" + "space",
    "reproducible" + "-econ-ai",
    "reproducible" + "_econ_ai",
    "reproducible_economics" + "_llm",
)


def _tracked_files():
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        return [REPO_ROOT / rel for rel in result.stdout.splitlines() if rel.strip()]
    candidates = [REPO_ROOT / "README.md", REPO_ROOT / "pyproject.toml"]
    for folder in ("src", "tests", "references"):
        base = REPO_ROOT / folder
        if base.is_dir():
            candidates.extend(p for p in base.rglob("*") if p.is_file())
    return candidates


def test_no_private_paths_or_repo_names_in_tracked_files():
    violations = []
    for path in _tracked_files():
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pattern in FORBIDDEN_PATTERNS:
                if pattern in line:
                    violations.append(f"{rel}:{lineno}: matched {pattern!r}")
    assert not violations, "Public-safety leak check failed:\n" + "\n".join(violations)
