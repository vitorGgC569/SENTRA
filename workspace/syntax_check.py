"""Trusted syntax profile; parses project Python without executing it or writing pyc."""
import ast
import sys
from pathlib import Path

# Executed by absolute path with -I against arbitrary authorized repositories.
sys.path.insert(0, str(Path(__file__).parent))
from paths import iter_workspace_files


def main():
    checked = 0
    errors = []
    root = Path(sys.argv[1]).resolve()
    for path in iter_workspace_files(root):
        if path.suffix != ".py":
            continue
        checked += 1
        try:
            ast.parse(path.read_bytes(), filename=str(path.relative_to(root)))
        except (SyntaxError, ValueError) as exc:
            errors.append(str(exc))
    print(f"SYNTAX checked={checked} errors={len(errors)}")
    for error in errors[:30]:
        print(error)
    return 1 if errors or not checked else 0


if __name__ == "__main__":
    raise SystemExit(main())
