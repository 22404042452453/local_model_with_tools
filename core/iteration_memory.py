"""
core/iteration_memory.py — Structured memory between pipeline iterations

Problem: passing raw review text to the next coder iteration is noisy.
The model gets "CRITICAL: Import 'pygame' failed" as a string and may still
try pygame again, or touch functions that already work.

Solution (MemoCoder / APR research pattern):
  - Track what's broken (file + line + error)
  - Track what was already tried (avoid repeating)
  - Track what works (don't touch it)
  - Track confirmed bad imports (never use again)

Usage:
    memory = IterationMemory()
    memory.update_from_review(review_md)
    memory.update_from_tests(test_output)
    memory.update_from_syntax_errors(py_files, workspace)

    # next coder iteration gets:
    prompt_block = memory.render_for_prompt()
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class BrokenLocation:
    file:     str
    line:     int | None
    error:    str
    function: str = ""   # which function is broken (if known)

    def __str__(self) -> str:
        loc = f"{self.file}" + (f" line {self.line}" if self.line else "")
        fn  = f" in {self.function}()" if self.function else ""
        return f"{loc}{fn}: {self.error}"


@dataclass
class IterationMemory:
    """
    Structured memory accumulated across pipeline iterations.
    Passed to Coder at revision N to avoid repeating mistakes.
    """
    revision:          int         = 0

    # What's broken — exact locations
    broken:            list[BrokenLocation] = field(default_factory=list)

    # What was tried and failed — model should NOT repeat these
    tried_fixes:       list[str]   = field(default_factory=list)

    # Confirmed working imports — safe to use
    working_imports:   set[str]    = field(default_factory=set)

    # Confirmed failing imports — never import these
    failed_imports:    set[str]    = field(default_factory=set)

    # Functions / classes confirmed to work — don't touch them
    working_functions: list[str]   = field(default_factory=list)

    # Raw pytest failures — specific assert lines
    test_failures:     list[str]   = field(default_factory=list)

    # ── Update methods ────────────────────────────────────────────────────────

    def update_from_review(self, review_md: str) -> None:
        """Parse review.md for CRITICAL issues, broken locations, failed imports."""
        if not review_md:
            return

        for line in review_md.splitlines():
            line = line.strip()
            if not line:
                continue

            # Import failures: "Import 'pygame' failed" / "No module named 'pygame'"
            imp_match = re.search(
                r"[Ii]mport ['\"]?(\w+)['\"]? fail|[Nn]o module named ['\"]?(\w+)['\"]?",
                line
            )
            if imp_match:
                pkg = imp_match.group(1) or imp_match.group(2)
                if pkg:
                    self.failed_imports.add(pkg)

            # Syntax errors: "line 45: unindent" / "SyntaxError line 12"
            syn_match = re.search(r'[Ss]yntax\s+[Ee]rror.*?line\s+(\d+)[:\s]+(.+)', line)
            if syn_match:
                lineno = int(syn_match.group(1))
                msg    = syn_match.group(2).strip()
                # Try to find the file name nearby in the same line
                file_match = re.search(r'(\w+\.py)', line)
                fname = file_match.group(1) if file_match else "main.py"
                self._add_broken(fname, lineno, msg)

            # CRITICAL lines with file/line info
            if "CRITICAL" in line:
                file_match = re.search(r'(\w+\.py)', line)
                line_match = re.search(r'line[:\s]+(\d+)', line)
                fname  = file_match.group(1) if file_match else ""
                lineno = int(line_match.group(1)) if line_match else None
                # Strip CRITICAL prefix for the error message
                err = re.sub(r'^\d+\.\s*CRITICAL[:\s]*', '', line).strip()
                if fname or err:
                    self._add_broken(fname or "main.py", lineno, err)

            # Runtime errors with AttributeError / TypeError / NameError
            runtime_match = re.search(
                r'(AttributeError|TypeError|NameError|RuntimeError)[:\s]+(.+)', line
            )
            if runtime_match:
                err_type = runtime_match.group(1)
                err_msg  = runtime_match.group(2).strip()
                file_match = re.search(r'(\w+\.py)', line)
                line_match = re.search(r'line[:\s]+(\d+)', line)
                fname  = file_match.group(1) if file_match else "main.py"
                lineno = int(line_match.group(1)) if line_match else None
                self._add_broken(fname, lineno, f"{err_type}: {err_msg}")

    def update_from_tests(self, test_output: str) -> None:
        """Parse pytest output for specific assertion failures and errors."""
        if not test_output:
            return

        for line in test_output.splitlines():
            line = line.strip()
            # FAILED test lines
            if line.startswith("FAILED") or "AssertionError" in line:
                self.test_failures.append(line[:200])
            # Import errors in test run
            imp_match = re.search(r"[Nn]o module named ['\"]?(\w+)['\"]?", line)
            if imp_match:
                self.failed_imports.add(imp_match.group(1))

        # Keep last 10 failures to avoid prompt bloat
        self.test_failures = self.test_failures[-10:]

    def update_from_syntax_errors(
        self, py_files: list[Path], workspace: Path | None = None
    ) -> None:
        """AST-check all py files and record syntax errors."""
        for fpath in py_files:
            try:
                source = fpath.read_text(encoding="utf-8")
                ast.parse(source)
                # File parses OK → scan its imports as working
                tree = ast.parse(source)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            pkg = alias.name.split(".")[0]
                            if pkg not in self.failed_imports:
                                self.working_imports.add(pkg)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        pkg = node.module.split(".")[0]
                        if pkg not in self.failed_imports:
                            self.working_imports.add(pkg)
            except SyntaxError as e:
                name = fpath.name
                self._add_broken(name, e.lineno, str(e.msg))

    def record_tried_fix(self, description: str) -> None:
        """Call this when the coder attempts a fix, so we can track it."""
        if description and description not in self.tried_fixes:
            self.tried_fixes.append(description[:200])
        # Keep last 8 tried fixes
        self.tried_fixes = self.tried_fixes[-8:]

    def mark_function_working(self, func_name: str) -> None:
        if func_name not in self.working_functions:
            self.working_functions.append(func_name)

    def advance(self) -> None:
        """Call at the start of each new iteration."""
        self.revision += 1
        # Clear broken list — will be repopulated from fresh review
        # Keep tried_fixes and working_* so the model avoids past mistakes
        self.broken.clear()

    # ── Render for prompt ─────────────────────────────────────────────────────

    def render_for_prompt(self) -> str:
        """
        Produce a compact, structured block to inject into the Coder's prompt.
        Designed to be scannable by a small model — no prose, bullet points only.
        """
        if self.revision == 0 and not self.broken:
            return ""

        lines = [f"── REVISION {self.revision} MEMORY ──"]

        # Working — don't touch
        if self.working_functions:
            fns = ", ".join(self.working_functions[:8])
            lines.append(f"✅ DO NOT TOUCH (working): {fns}")

        if self.working_imports:
            imps = ", ".join(sorted(self.working_imports)[:12])
            lines.append(f"✅ Safe imports: {imps}")

        # What's broken — fix these
        if self.broken:
            lines.append("❌ FIX THESE:")
            for b in self.broken[:8]:
                lines.append(f"   • {b}")

        # Failed imports — never use
        if self.failed_imports:
            bad = ", ".join(sorted(self.failed_imports))
            lines.append(f"🚫 NEVER import (not installed): {bad}")

        # Test failures
        if self.test_failures:
            lines.append("🧪 Test failures:")
            for tf in self.test_failures[:5]:
                lines.append(f"   • {tf}")

        # Already tried — avoid repeating
        if self.tried_fixes:
            lines.append("⛔ Already tried (don't repeat):")
            for tf in self.tried_fixes[:5]:
                lines.append(f"   • {tf}")

        lines.append("──────────────────────────────")
        return "\n".join(lines)

    def has_issues(self) -> bool:
        return bool(self.broken or self.failed_imports or self.test_failures)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _add_broken(self, file: str, line: int | None, error: str) -> None:
        """Add a broken location, deduplicating by (file, line)."""
        # Deduplicate
        for existing in self.broken:
            if existing.file == file and existing.line == line:
                return
        self.broken.append(BrokenLocation(file=file, line=line, error=error[:150]))


# ── Factory: build from pipeline outputs ─────────────────────────────────────

def build_memory_from_iteration(
    review_md:   str,
    test_output: str,
    py_files:    list[Path],
    previous:    IterationMemory | None = None,
) -> IterationMemory:
    """
    Build (or update) IterationMemory from one pipeline iteration's outputs.
    Call at the end of Reviewer step, before the next Coder iteration.
    """
    if previous is None:
        memory = IterationMemory()
    else:
        memory = previous
        memory.advance()

    memory.update_from_review(review_md)
    memory.update_from_tests(test_output)
    memory.update_from_syntax_errors(py_files)

    return memory
