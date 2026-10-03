"""Safe file operations inside one job's copy of the repository.

Every path the LLM sends is untrusted. `resolve()` makes sure it cannot escape the
workspace (no "../../etc/passwd", no absolute paths, no symlinks pointing out, no .git).
"""

import re
import shutil
import subprocess
from pathlib import Path

from redtogreen.policy import PatchStats, is_protected

SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".pytest_cache", ".mypy_cache"}
MAX_READ_LINES = 400
MAX_FILE_BYTES = 1_000_000


class WorkspaceError(Exception):
    """A request the workspace refuses (bad path, missing text, protected file...)."""


def _git(root: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-c", "core.quotepath=off", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise WorkspaceError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


class Workspace:
    def __init__(self, root: Path, protected: list[str]):
        self.root = root.resolve()
        self.protected = protected

    # ---------- setup ----------
    @classmethod
    def from_directory(cls, source: Path, dest: Path, protected: list[str]) -> "Workspace":
        """Copy a local project into `dest` and snapshot it as a git baseline commit."""
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(source, dest, ignore=shutil.ignore_patterns(*SKIP_DIRS))
        ws = cls(dest, protected)
        ws.init_baseline()
        return ws

    def init_baseline(self) -> None:
        _git(self.root, "init", "-q")
        _git(self.root, "add", "-A")
        _git(
            self.root,
            "-c", "user.email=bot@redtogreen.local",
            "-c", "user.name=redtogreen",
            "commit", "-q", "--allow-empty", "-m", "baseline",
        )

    # ---------- path safety ----------
    def resolve(self, path: str) -> Path:
        if not path or "\x00" in path:
            raise WorkspaceError("Empty or invalid path.")
        candidate = Path(path)
        if candidate.is_absolute():
            raise WorkspaceError("Use a path relative to the repository root.")
        full = (self.root / candidate).resolve()
        if full != self.root and self.root not in full.parents:
            raise WorkspaceError(f"Path '{path}' is outside the repository.")
        rel_parts = full.relative_to(self.root).parts
        if rel_parts and rel_parts[0] == ".git":
            raise WorkspaceError("The .git directory is off limits.")
        return full

    def rel(self, full: Path) -> str:
        return full.relative_to(self.root).as_posix()

    # ---------- read-only tools ----------
    def list_files(self, directory: str = ".", limit: int = 300) -> list[str]:
        base = self.resolve(directory)
        if not base.is_dir():
            raise WorkspaceError(f"'{directory}' is not a directory.")
        out = []
        for p in sorted(base.rglob("*")):
            if any(part in SKIP_DIRS for part in p.relative_to(self.root).parts):
                continue
            if p.is_file():
                out.append(self.rel(p))
                if len(out) >= limit:
                    out.append(f"... (stopped at {limit} files)")
                    break
        return out

    def read_file(self, path: str, start_line: int = 1, end_line: int = 0) -> str:
        full = self.resolve(path)
        if not full.is_file():
            raise WorkspaceError(f"File '{path}' does not exist.")
        if full.stat().st_size > MAX_FILE_BYTES:
            raise WorkspaceError(f"File '{path}' is too large to read.")
        lines = full.read_text(errors="replace").splitlines()
        start = max(start_line, 1)
        end = len(lines) if end_line <= 0 else min(end_line, len(lines))
        end = min(end, start + MAX_READ_LINES - 1)
        body = "\n".join(f"{i:>5}  {lines[i - 1]}" for i in range(start, end + 1))
        note = ""
        if end < len(lines):
            note = f"\n... ({len(lines) - end} more lines; call again with start_line={end + 1})"
        return f"{self.rel(full)} (lines {start}-{end} of {len(lines)})\n{body}{note}"

    def search(self, pattern: str, file_glob: str = "", max_results: int = 50) -> list[str]:
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            raise WorkspaceError(f"Invalid regex: {exc}") from exc
        hits = []
        for rel_path in self.list_files(limit=5000):
            if rel_path.startswith("... ("):
                continue
            if file_glob and not Path(rel_path).match(file_glob):
                continue
            full = self.root / rel_path
            if full.stat().st_size > MAX_FILE_BYTES:
                continue
            try:
                text = full.read_text()
            except UnicodeDecodeError:
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    hits.append(f"{rel_path}:{lineno}: {line.strip()[:200]}")
                    if len(hits) >= max_results:
                        return hits + [f"... (stopped at {max_results} matches)"]
        return hits

    # ---------- the only write tool ----------
    def replace_in_file(self, path: str, old_text: str, new_text: str) -> str:
        full = self.resolve(path)
        rel_path = self.rel(full)
        if is_protected(rel_path, self.protected):
            raise WorkspaceError(
                f"'{rel_path}' is protected (tests, CI or config). You must fix the source code, "
                "not the tests."
            )
        if not full.is_file():
            raise WorkspaceError(f"File '{path}' does not exist.")
        if not old_text:
            raise WorkspaceError("old_text must not be empty.")
        content = full.read_text()
        count = content.count(old_text)
        if count == 0:
            raise WorkspaceError(
                f"old_text was not found in '{rel_path}'. Read the file again and copy the exact text, "
                "including indentation."
            )
        if count > 1:
            raise WorkspaceError(
                f"old_text appears {count} times in '{rel_path}'. Include more surrounding lines so it "
                "matches exactly once."
            )
        full.write_text(content.replace(old_text, new_text, 1))
        return f"Edited {rel_path}."

    # ---------- git helpers (used by the pipeline, not the LLM) ----------
    def diff(self) -> str:
        return _git(self.root, "diff", "--no-color")

    def patch_stats(self) -> PatchStats:
        files, added, removed = [], 0, 0
        for line in _git(self.root, "diff", "--numstat").splitlines():
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            a, r, name = parts
            files.append(name)
            added += int(a) if a.isdigit() else 0
            removed += int(r) if r.isdigit() else 0
        # Brand-new files are not part of `git diff`; count them too.
        for name in _git(self.root, "ls-files", "--others", "--exclude-standard").splitlines():
            files.append(name)
            added += len((self.root / name).read_text(errors="replace").splitlines())
        return PatchStats(files=files, added=added, removed=removed)

    def changed_files(self) -> list[str]:
        return self.patch_stats().files

    def reset(self) -> None:
        """Throw away every change since the baseline commit."""
        _git(self.root, "checkout", "--", ".")
        _git(self.root, "clean", "-fdq")

    def revert_paths(self, paths: list[str]) -> None:
        tracked = set(_git(self.root, "ls-files").splitlines())
        for p in paths:
            if p in tracked:
                _git(self.root, "checkout", "--", p)
            else:
                (self.root / p).unlink(missing_ok=True)

    def file_text(self, path: str) -> str:
        return self.resolve(path).read_text()
