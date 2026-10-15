"""A runnable lesson in recovery, counterexamples and explicit input domains.

Run with the Python environment where Rewynth 0.3 is installed:
    python examples/conditional_lab.py --output branch-lab

The shipped ARM64 fixture is read as data, never executed. All output goes to
a new directory. Partial results survive a failed operation; choose a new
directory for another run. REPORT.md is written only after all checks pass.
"""

import argparse
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def require(condition, message):
    if not condition:
        raise ValueError(message)


def save(folder, name, value):
    text = value if isinstance(value, str) else json.dumps(value, indent=2) + "\n"
    if name == "REPORT.md":
        # Publish only a fully written report, atomically and without replacing
        # a file added during the run. A failed write retains only a temp file.
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=folder, prefix=".report-",
            suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        os.link(temporary, folder / name)
        try:
            temporary.unlink()
        except OSError:
            pass  # A leftover temp file does not invalidate the complete report.
        return
    with (folder / name).open("x", encoding="utf-8") as stream:
        stream.write(text)


def run(operation, *options):
    command = [
        sys.executable, "-m", "native_recovery.cli", operation,
        "--example-branches", "--function", "_tone_curve32", "--arguments", "1",
        *options,
    ]
    completed = subprocess.run(
        command, capture_output=True, text=True, timeout=30,
    )
    if completed.returncode:
        raise ValueError(completed.stderr.strip() or "Rewynth analysis failed")
    return json.loads(completed.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("branch-lab"))
    args = parser.parse_args()
    folder = args.output
    created = False
    try:
        installed_version = version("rewynth")
        folder.mkdir()  # Deliberately refuses existing directories and symlinks.
        created = True
        save(folder, "READ-ME.txt", "Results are incomplete unless REPORT.md exists.\n")

        recovered = run("recover")
        require(recovered["reconstruction"]["status"] == "verified_model",
                "Recovery did not reach verified_model; no lesson conclusion.")
        identity = recovered["model"]

        def record(name, value):
            model = value["model"]
            for key in ("artifact_sha256", "function_sha256", "symbol"):
                require(model[key] == identity[key], "Artifact/function binding changed.")
            save(folder, name, value)

        record("recovery.json", recovered)
        require(identity["assumptions"]["domain"] == [None],
                "Recovery did not use the full unsigned 32-bit domain.")
        save(folder, "original.c", recovered["source"])
        save(folder, "recovered.txt", recovered["expression"])
        save(folder, "identity.txt", "x0\n")

        unchanged = run("verify", "--expression", str(folder / "recovered.txt"))
        record("unchanged.json", unchanged)
        require(unchanged["verification"]["assumptions"]["domain"] == [None],
                "Unchanged comparison did not use the full word domain.")
        require(unchanged["verification"]["status"] == "unsat",
                "Recovered source comparison was not UNSAT; inspect unchanged.json.")

        edited = run("verify", "--expression", str(folder / "identity.txt"))
        record("identity-full-domain.json", edited)
        require(edited["verification"]["assumptions"]["domain"] == [None],
                "Identity comparison did not use the full word domain.")
        require(edited["verification"]["status"] == "sat",
                "Identity comparison was not SAT; inspect identity-full-domain.json.")
        save(folder, "identity.c", edited["source"])
        witness = edited["verification"]["counterexample"]
        x = witness["inputs_u32"][0]
        original = witness["original_output_u32"]
        candidate = witness["candidate_output_u32"]
        require(original != candidate and candidate == x, "Invalid identity witness.")

        domain = [{"min": 512, "max": 3071, "signed": False}]
        restricted = run("verify", "--expression", str(folder / "identity.txt"),
                         "--domain", json.dumps(domain))
        record("identity-middle-domain.json", restricted)
        require(restricted["verification"]["assumptions"]["domain"] == domain,
                "Restricted comparison did not retain the requested input domain.")
        require(restricted["verification"]["status"] == "unsat",
                "Middle-domain comparison was not UNSAT; inspect its evidence.")

        rows = []
        for value in dict.fromkeys([511, 512, 3071, 3072, 4096, x]):
            trace = run("evaluate", "--inputs", str(value))
            record(f"trace-{value}.json", trace)
            observed = trace["witness"]
            events = observed["trace"]
            require(sum(e.get("kind") == "return" for e in events) == 1,
                    "Expected exactly one executed return in each trace.")
            result = observed["output_u32"]
            if value == x:
                require(result == original, "Counterexample replay disagreed.")
            rows.append(f"| {value} | {result} | {value} |")

        files = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(folder.iterdir()) if path.is_file()
        }
        save(folder, "SHA256.json", files)
        save(folder, "REPORT.md", f"""# One edit, two input domains

Rewynth {installed_version} recovered the shipped compiled `_tone_curve32`
as editable source. The ARM64 artifact was analyzed as bytes, never executed.

| Comparison | Input domain | Solver result |
|---|---|---|
| Recovered source vs original instruction model | All unsigned 32-bit patterns | UNSAT |
| Identity edit `x0` vs original model | All unsigned 32-bit patterns | SAT |
| Same identity edit vs original model | Unsigned 512 through 3071 inclusive | UNSAT |

SAT supplies a contradicting input: **{x}**. The original model returns
**{original}**; the identity edit returns **{candidate}**. Its saved concrete
trace replays the original result. The middle segment really is identity,
so restricting the comparison changes the question and its answer.

| Input | Original model | Identity edit |
|---:|---:|---:|
{chr(10).join(rows)}

UNSAT means no output mismatch in the implemented instruction model and
stated domain. It does not certify the CPU, lifter, arbitrary functions or
the edit outside that domain. Solver UNKNOWN would stop this lesson without
a completion report; it would never become UNSAT.

## Inspect and reuse

- `recovery.json`: actual assembly, assumptions and recovered expression.
- `unchanged.json`: unchanged-source comparison over the full word domain.
- `identity-full-domain.json`: actual counterexample and executed trace.
- `identity-middle-domain.json`: restricted result and exact input bounds.
- `trace-*.json`: concrete executions of the instruction model, one return each.
- `original.c`: recovered full-domain behavior, standalone defined-width C.
- `identity.c`: deliberately different full-domain identity C.
- `SHA256.json`: hashes of the evidence files written before this report.

Both C functions are named `recovered`; compile them separately. Neither
needs Rewynth or Z3 at runtime. The domain is part of the comparison evidence,
not a runtime input guard added to `identity.c`.

Fixture artifact SHA-256: `{identity['artifact_sha256']}`.
Selected function SHA-256: `{identity['function_sha256']}`.
This original controlled luminance example makes no perceptual-quality claim.
The native fixture's source and provenance ship with Rewynth.
""")
        print(f"Saved complete lesson: {folder / 'REPORT.md'}")
        return 0
    except (OSError, ValueError, KeyError, PackageNotFoundError,
            subprocess.TimeoutExpired) as exc:
        print(f"Lesson incomplete: {exc}", file=sys.stderr)
        if created:
            print(f"Partial evidence retained in {folder}; choose a new output directory.",
                  file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
