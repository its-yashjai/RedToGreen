"""Safety rules for patches. Enforced in code, never only in the prompt.

A prompt can be ignored or overridden by injected text. These checks cannot.
"""

from dataclasses import dataclass
from fnmatch import fnmatch


def is_protected(path: str, patterns: list[str]) -> bool:
    path = path.replace("\\", "/").removeprefix("./")
    return any(fnmatch(path, pattern) for pattern in patterns)


@dataclass
class PatchStats:
    files: list[str]
    added: int
    removed: int


def check_patch(stats: PatchStats, protected: list[str], max_files: int, max_lines: int) -> list[str]:
    """Return a list of human-readable violations (empty list = patch is allowed)."""
    violations = []
    touched = [f for f in stats.files if is_protected(f, protected)]
    if touched:
        violations.append(
            f"Changed protected files {touched}. Tests, CI config and dependency files must not be "
            "edited; fix the source code instead."
        )
    if len(stats.files) > max_files:
        violations.append(f"Changed {len(stats.files)} files; the limit is {max_files}. Keep the fix small.")
    if stats.added + stats.removed > max_lines:
        violations.append(
            f"Changed {stats.added + stats.removed} lines; the limit is {max_lines}. Keep the fix small."
        )
    return violations
