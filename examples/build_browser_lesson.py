"""Compile the state lesson's real recovered C exports for a static browser.

First run state_lab.py into a fresh directory, then supply that directory with
--evidence. The output directory must be new. No solver result is invented here.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


BRIDGE = """
/* Browser bridge: preserve the pure export's complete return and post-state. */
static rewynth_state last;
void lesson_call(uint64_t state, uint64_t increment) {
    last = rewynth_transition(state, increment);
}
uint64_t lesson_result(void) { return last.result; }
uint64_t lesson_state(void) { return last.memory[0]; }
uint64_t lesson_increment(void) { return last.memory[1]; }
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--compiler", default="clang")
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Choose a new output directory; existing results are preserved.")
    root = Path(__file__).resolve().parents[1]
    resources = root / "src/native_recovery/resources/examples"
    evidence_bytes = (args.evidence / "evidence.json").read_bytes()
    evidence = json.loads(evidence_bytes)
    original = evidence["recovered"]
    edited = evidence["lost_store_comparison"]
    if original["reconstruction"]["verification"]["status"] != "unsat":
        raise SystemExit("The recovered transition has no equality result.")
    if edited["verification"]["status"] != "sat":
        raise SystemExit("The edit has no recorded counterexample.")
    if original["model"] != edited["model"]:
        raise SystemExit("The exports refer to different instruction models.")
    if digest((resources / "pcg-basic.o").read_bytes()) != original["model"]["artifact_sha256"]:
        raise SystemExit("The evidence does not identify the bundled PCG artifact.")
    a, b = json.loads(original["expression"]), json.loads(edited["expression"])
    if a["return"] != b["return"] or b["memory"] != ["x0", a["memory"][1]]:
        raise SystemExit("Expected exactly the return-preserving lost-store edit.")
    witness = edited["verification"]["counterexample"]
    if witness["differences"] != ["memory[0]"]:
        raise SystemExit("The recorded witness does not isolate the state update.")
    model = original["model"]
    if model["assumptions"]["memory"]["words"] != 2 or model["assumptions"]["domain"] != [None, None]:
        raise SystemExit("This lesson requires the documented two-word, unrestricted model.")
    ref = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    compiler = subprocess.check_output([args.compiler, "--version"], text=True).splitlines()[0]
    notice = (resources / "pcg-basic-upstream.c").read_text().split("*/", 1)[0] + "*/\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rewynth-lesson-build-") as temporary:
        work = Path(temporary)
        for name, result in (("original", original), ("edited", edited)):
            source = notice + "\n/* Recovered model; the lost-store edit is ours, not an upstream PCG bug. */\n" + result["source"]
            (work / f"{name}.c").write_text(source)
            (work / f"{name}-bridge.c").write_text(f'#include "{name}.c"\n' + BRIDGE)
            command = [args.compiler, "--target=wasm32", "-std=c11", "-O2", "-nostdlib", "-ffreestanding", "-fno-builtin",
                       "-Wl,--no-entry", "-Wl,--strip-all", "-Wl,--initial-memory=131072", "-Wl,--max-memory=131072"]
            command += [f"-Wl,--export={symbol}" for symbol in ("lesson_call", "lesson_result", "lesson_state", "lesson_increment")]
            subprocess.run(command + [str(work / f"{name}-bridge.c"), "-o", str(work / f"{name}.wasm")], check=True, timeout=60)
        (work / "evidence.json").write_bytes(evidence_bytes)
        (work / "original-transition.json").write_text(original["expression"] + "\n")
        (work / "edited-transition.json").write_text(edited["expression"] + "\n")
        shutil.copyfile(resources / "pcg-APACHE-2.0.txt", work / "PCG-LICENSE.txt")
        shutil.copyfile(root / "LICENSE", work / "REWYNTH-LICENSE.txt")
        manifest = {
            "format": "rewynth-browser-state-lesson-v1",
            "source_ref": ref, "compiler": compiler, "target": "wasm32",
            "artifact_sha256": model["artifact_sha256"], "function_sha256": model["function_sha256"],
            "symbol": model["symbol"], "assumptions": model["assumptions"],
            "recorded_recovery_status": "unsat", "recorded_edit_status": "sat",
            "native_source_sha256": {name: digest((resources / name).read_bytes())
                                     for name in ("pcg-basic-upstream.c", "pcg_basic.h")},
            "default_inputs": ["0x853c49e6748fea9b", "0xda3e39cb94b95bdb"],
            "scope": "The browser runs recovered C models compiled to Wasm; it does not decode ARM64 or issue new solver queries.",
            "assets": {p.name: {"sha256": digest(p.read_bytes()), "bytes": p.stat().st_size}
                       for p in sorted(work.iterdir())},
        }
        (work / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        # Claim a new destination only after both compiles finish successfully.
        args.output.mkdir()
        for item in work.iterdir():
            with (args.output / item.name).open("xb") as stream:
                stream.write(item.read_bytes())
    print(json.dumps({"status": "compiled_exports", "source_ref": ref, "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
