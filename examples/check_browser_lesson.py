"""Check the shipped Wasm lesson against freshly compiled, licensed PCG C.

This controlled fixture check never executes a caller-supplied binary.
Run with Python, Node and Clang available; no model or network service is used.
"""

import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile


class State(ctypes.Structure):
    _fields_ = [("state", ctypes.c_uint64), ("inc", ctypes.c_uint64)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    compiler, node = shutil.which("clang"), shutil.which("node")
    if not compiler or not node:
        raise SystemExit("Clang and Node are required for this fixture check.")
    model = args.model or root / "docs/lesson/model"
    resources = root / "src/native_recovery/resources/examples"
    manifest = json.loads((model / "manifest.json").read_text())
    for name, expected in manifest["native_source_sha256"].items():
        if hashlib.sha256((resources / name).read_bytes()).hexdigest() != expected:
            raise SystemExit("The native PCG source no longer matches this lesson's provenance.")
    maximum = (1 << 64) - 1
    inputs = [(0x853c49e6748fea9b, 0xda3e39cb94b95bdb), (0, 0), (0, 1), (1, 1),
              (maximum, maximum), (1 << 63, 1), ((1 << 32) - 1, 1 << 63), (1, maximum)]
    random_source = random.Random(0x5257594e)
    inputs.extend((random_source.getrandbits(64), random_source.getrandbits(64)) for _ in range(24))
    with tempfile.TemporaryDirectory(prefix="rewynth-browser-controls-") as temporary:
        work = Path(temporary)
        library = work / ("pcg.dylib" if sys.platform == "darwin" else "pcg.so")
        flags = ["-dynamiclib"] if sys.platform == "darwin" else ["-shared", "-fPIC"]
        subprocess.run([compiler, "-O2", *flags, str(resources / "pcg-basic-upstream.c"), "-o", str(library)], check=True, timeout=60)
        native = ctypes.CDLL(str(library))
        native.pcg32_random_r.argtypes = [ctypes.POINTER(State)]
        native.pcg32_random_r.restype = ctypes.c_uint32
        records = []
        for state, increment in inputs:
            left = State(state, increment)
            calls = []
            for _ in range(3):
                result = native.pcg32_random_r(ctypes.byref(left))
                # The controlled edit drops the write, so its next input stays put.
                held = State(state, increment)
                edited_return = native.pcg32_random_r(ctypes.byref(held))
                calls.append({"original": [hex(result), hex(left.state), hex(left.inc)],
                              "edited": [hex(edited_return), hex(state), hex(increment)]})
            records.append({"inputs": [hex(state), hex(increment)], "calls": calls})
        expected = work / "native.json"
        expected.write_text(json.dumps(records))
        run = subprocess.run([node, str(root / "examples/check_browser_lesson.mjs"), str(expected), str(model.resolve())], check=True, capture_output=True, text=True, timeout=60)
        receipt = json.loads(run.stdout)
        receipt["native_calls"] = len(inputs) * 3 * 2
        receipt["native_host"] = sys.platform
        receipt["source_ref"] = manifest["source_ref"]
        receipt["artifact_sha256"] = manifest["artifact_sha256"]
        receipt["wasm_sha256"] = {name: manifest["assets"][name + ".wasm"]["sha256"]
                                  for name in ("original", "edited")}
        if args.receipt:
            with args.receipt.open("x") as stream:
                json.dump({"summary": receipt, "controls": records}, stream, indent=2)
                stream.write("\n")
        print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
