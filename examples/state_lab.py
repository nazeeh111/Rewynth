"""Recover a state transition and expose a return-preserving lost update.

The compiled original PCG object is read as data, never loaded or executed.
Run against an installed Rewynth: python examples/state_lab.py --output state-lab
"""

import argparse
import json
from pathlib import Path
from native_recovery.artifacts import Artifact
from native_recovery.cli import bounded_operation
import native_recovery


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("state-lab"))
    args = parser.parse_args()
    artifact = Artifact((Path(native_recovery.__file__).parent / "resources/examples/pcg-basic.o").read_bytes())
    function, code = artifact.function("_pcg32_random_r")
    settings = {"artifact": artifact.digest, "arity": 1, "word_bits": 64, "memory": {"argument": 0, "words": 2}}

    def run(operation, **extra):
        return bounded_operation({**settings, "operation": operation, **extra}, code, function.address, function.name)

    recovered = run("recover")
    if recovered.get("reconstruction", {}).get("verification", {}).get("status") != "unsat":
        raise SystemExit("No verified transition recovered; no example conclusion.")
    edit = json.loads(recovered["expression"])
    edit["memory"][0] = "x0"
    lost_store = json.dumps(edit, indent=2)
    compared = run("verify", expression=lost_store)
    proof = compared["verification"]
    if proof["status"] != "sat":
        raise SystemExit("Expected a counterexample to the lost-state update.")
    witness = proof["counterexample"]
    if witness["original_output_u64"] != witness["candidate_output_u64"] or witness["differences"] != ["memory[0]"]:
        raise SystemExit("Counterexample must preserve return and differ in state only.")
    first = run("evaluate", inputs=["0x853c49e6748fea9b", "0xda3e39cb94b95bdb"])
    second = run("evaluate", inputs=first["witness"]["memory_u64"])
    # These are model observations, not new native measurements.
    args.output.mkdir(parents=True, exist_ok=True)
    outputs = {
        "transition.json": recovered["expression"],
        "lost-store.json": lost_store,
        "transition.c": recovered["source"],
        "evidence.json": json.dumps({"scope": "Data-only ARM64 model; original PCG source compiled locally; no target execution", "recovered": recovered, "lost_store_comparison": compared, "first_call": first, "second_call": second}, indent=2),
    }
    for name, text in outputs.items():
        destination = args.output / name
        # Existing files are user data. Choose a new output directory to rerun.
        with destination.open("x") as stream:
            stream.write(text + "\n")
    print(json.dumps({"status": "state_counterexample", "immediate_return_equal": True, "changed": witness["differences"], "first_output_u64": first["witness"]["output_u64"], "next_output_u64": second["witness"]["output_u64"], "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
