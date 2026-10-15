"""Actual packaged branch fixture through shared engine, CLI and loopback API.

Only the hash-pinned owned fixture and its generated C are loaded for native
comparison. Artifact uploads remain data-only in the product.
"""
import base64
import ctypes
import hashlib
import json
from pathlib import Path
import platform
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from native_recovery import recovery_core as core
from native_recovery.artifacts import Artifact
from native_recovery.engine import run_operation
from native_recovery.server import Workbench

RESOURCES = Path(core.__file__).parent / "resources/examples"
FIXTURE = RESOURCES / "branch-kernels.dylib"
FIXTURE_SHA = "924b18db41f4d4ee065d094a7264ae6f7264c732d3a9675e8f064bec1ba55d5c"
CASES = [("tone_curve32", 1, 32), ("guarded_morton32", 2, 32),
         ("window_tag64", 3, 64), ("record_hash64", 4, 64)]


def artifact():
    data = FIXTURE.read_bytes()
    assert hashlib.sha256(data).hexdigest() == FIXTURE_SHA
    return Artifact(data)


def operation(a, name, arity, bits, op, **fields):
    f, code = a.function("_" + name)
    return run_operation({"artifact": a.digest, "word_bits": bits, "arity": arity,
                          "operation": op, **fields}, code, f.address, f.name)


def reference(name, values):
    """Unsigned references independent of the lifter/expression compiler."""
    mask = (1 << (32 if name.endswith("32") else 64)) - 1
    if name == "tone_curve32":
        x, = values
        if x > 4095:
            return 4095
        if x < 512:
            y = (x * x + 255) >> 9
            return (y * 3 + x) >> 2
        if x < 3072:
            return x
        return 4095 - (((4095 - x) ** 2 + 511) >> 10)
    if name == "guarded_morton32":
        x, y = values
        if (x | y) > 65535:
            return mask
        return sum((((x >> i) & 1) << (2 * i)) | (((y >> i) & 1) << (2 * i + 1))
                   for i in range(16))
    if name == "window_tag64":
        value, low, high = values
        if value < low or value > high:
            return 0
        x = (value - low + 0x9E3779B97F4A7C15) & mask
        x ^= x >> 30
        x = (x * 0xBF58476D1CE4E5B9) & mask
        x ^= x >> 27
        x = (x * 0x94D049BB133111EB) & mask
        return x ^ (x >> 31)
    if name == "record_hash64":
        a, b, c, domain = values
        h = (a + ((b << 7) & mask) + (b >> 57)) & mask
        h ^= (c + 0x9E3779B97F4A7C15) & mask
        if domain:
            h ^= (domain * 0xBF58476D1CE4E5B9) & mask
            h ^= h >> 30
            h = (h * 0x94D049BB133111EB) & mask
        h ^= h >> 27
        h = (h * 0x9E3779B185EBCA87) & mask
        return h ^ (h >> 31)
    raise AssertionError(name)


def samples(name, arity, bits):
    mask = (1 << bits) - 1
    rng = random.Random(0xB6A0 + sum(map(ord, name)))
    values = [[rng.getrandbits(bits) for _ in range(arity)] for _ in range(100)]
    values += [[x] * arity for x in (0, 1, 511, 512, 3071, 3072, 4095, 4096,
                                   65535, 65536, 1 << (bits - 1), mask)]
    if name == "tone_curve32":
        values += [[x] for x in range(4097)]
    if name == "guarded_morton32":
        values += [[rng.randrange(65536), rng.randrange(65536)] for _ in range(150)]
    if name == "window_tag64":
        values += [[x, 17, 32] for x in (0, 16, 17, 18, 31, 32, 33, mask)]
        values += [[x, 32, 17] for x in (16, 17, 31, 32, 33)]
    if name == "record_hash64":
        values += [[rng.getrandbits(bits) for _ in range(3)] + [0] for _ in range(100)]
    return values


class BranchProductTests(unittest.TestCase):
    def test_packaged_identity_and_all_four_recoveries(self):
        a = artifact()
        provenance = json.loads((RESOURCES / "branch-provenance.json").read_text())
        self.assertEqual(provenance["artifact_sha256"], a.digest)
        self.assertEqual(provenance["source_sha256"], hashlib.sha256(
            (RESOURCES / "branch-kernels.c").read_bytes()).hexdigest())
        for name, arity, bits in CASES:
            with self.subTest(name=name):
                result = operation(a, name, arity, bits, "recover")
                self.assertEqual(result["reconstruction"]["status"], "verified_model", result)
                self.assertIn(f"uint{bits}_t recovered(", result["source"])
                self.assertIn("ifelse", result["expression"])
                flow = result["model"]["assumptions"]["control_flow"]
                self.assertEqual(flow["kind"], "acyclic_direct")
                self.assertGreater(flow["branches"], 0)
                if name == "record_hash64":
                    self.assertGreater(flow["backward_edges"], 0)
        self.assertEqual(FIXTURE_SHA, hashlib.sha256(FIXTURE.read_bytes()).hexdigest())

    def test_actual_branch_paths_edit_counterexample_and_lossy_inverse(self):
        a = artifact()
        valid = operation(a, "guarded_morton32", 2, 32, "evaluate", inputs=[1, 2])
        invalid = operation(a, "guarded_morton32", 2, 32, "evaluate", inputs=[65536, 0])
        self.assertEqual(valid["witness"]["output_u32"], 9)
        self.assertEqual(invalid["witness"]["output_u32"], 0xFFFFFFFF)
        for result, taken in [(valid, False), (invalid, True)]:
            trace = result["witness"]["trace"]
            branches = [i for i in trace if i.get("kind") == "branch"]
            self.assertEqual(len(branches), 1)
            self.assertEqual(branches[0]["condition_taken"], taken)
            self.assertEqual(trace[-1]["kind"], "return")
            self.assertEqual(sum(i.get("kind") == "return" for i in trace), 1)
        self.assertLess(len(invalid["witness"]["trace"]), len(valid["witness"]["trace"]))
        bad = operation(a, "tone_curve32", 1, 32, "verify", expression="x0")
        self.assertEqual(bad["verification"]["status"], "sat", bad)
        counterexample = bad["verification"]["counterexample"]
        self.assertNotEqual(counterexample["original_output_u32"], counterexample["candidate_output_u32"])
        self.assertNotEqual(operation(a, "tone_curve32", 1, 32, "derive_inverse")["inverse_program"]["status"], "verified_inverse_model")
        wide = operation(a, "window_tag64", 3, 64, "evaluate", inputs=["18", "17", "32"])
        self.assertEqual(wide["witness"]["output_u64"], "0x910a2dec89025cc1")
        self.assertEqual(operation(a, "window_tag64", 3, 64, "evaluate", inputs=["16", "17", "32"])["witness"]["output_u64"], 0)

    def test_cli_example_switches_conflicts_and_artifact_preservation(self):
        before = FIXTURE.read_bytes()
        command = [sys.executable, "-m", "native_recovery.cli"]
        result = subprocess.run(command + ["inspect", "--example-branches"], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["sha256"], FIXTURE_SHA)
        result = subprocess.run(command + ["evaluate", "--example-branches", "--function", "_tone_curve32", "--arguments", "1", "--inputs", "4096"], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["witness"]["output_u32"], 4095)
        for selectors in [["--example", "--example-branches"], ["--example-wide", "--example-branches"], [str(FIXTURE), "--example-branches"]]:
            rejected = subprocess.run(command + ["inspect"] + selectors, text=True, capture_output=True)
            self.assertEqual(rejected.returncode, 2, rejected)
            self.assertFalse(rejected.stdout)
        self.assertEqual(FIXTURE.read_bytes(), before)

    def test_loopback_example_and_real_api_job(self):
        try:
            server = Workbench(0)
        except PermissionError as error:
            self.skipTest(f"Native loopback permission unavailable: {error}")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(server.origin + "/example-branches", timeout=5) as response:
                data = response.read()
                self.assertEqual(response.headers["Content-Type"], "application/octet-stream")
            self.assertEqual(hashlib.sha256(data).hexdigest(), FIXTURE_SHA)
            with urlopen(server.origin + "/api/bootstrap", timeout=5) as response:
                token = json.load(response)["token"]
            headers = {"Content-Type": "application/json", "Origin": server.origin,
                       "X-Workbench-Token": token}
            def post(path, payload):
                request = Request(server.origin + path, data=json.dumps(payload).encode(), headers=headers)
                with urlopen(request, timeout=5) as response:
                    return json.load(response)
            opened = post("/api/artifacts", {"data": base64.b64encode(data).decode()})
            job = post("/api/jobs", {"artifact": opened["sha256"], "symbol": "_tone_curve32", "arity": 1,
                                     "word_bits": 32, "operation": "evaluate", "inputs": [4096]})
            deadline = time.monotonic() + 22
            while True:
                with urlopen(server.origin + "/api/jobs/" + job["job"], timeout=5) as response:
                    status = json.load(response)
                if status["state"] != "running":
                    break
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.02)
            self.assertEqual(status["state"], "done", status)
            self.assertEqual(status["result"]["witness"]["output_u32"], 4095)
            self.assertEqual(status["result"]["witness"]["trace"][-1]["kind"], "return")
            with self.assertRaises(HTTPError) as denied:
                urlopen(Request(server.origin + "/api/jobs", data=b"{}", headers={"Content-Type": "application/json"}), timeout=5)
            self.assertEqual(denied.exception.code, 403)
            denied.exception.close()
        finally:
            server.close_jobs()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    @unittest.skipUnless(platform.system() == "Darwin" and platform.machine() == "arm64"
                         and shutil.which("clang"), "Controlled owned ARM64 fixture execution requires macOS ARM64 and Clang")
    def test_generated_c_original_cpu_and_python_reference_four_families(self):
        a = artifact()
        original = ctypes.CDLL(str(FIXTURE.resolve()))
        exports = []
        for name, arity, bits in CASES:
            result = operation(a, name, arity, bits, "recover")
            self.assertEqual(result["reconstruction"]["status"], "verified_model", result)
            exports.append(result["source"].replace(f"uint{bits}_t recovered(", f"uint{bits}_t exported_{name}("))
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "exports.c"
            library = Path(directory) / "exports.dylib"
            source.write_text("\n".join(exports))
            subprocess.run([shutil.which("clang"), "-O2", "-dynamiclib", str(source), "-o", str(library)], check=True, capture_output=True)
            rebuilt = ctypes.CDLL(str(library))
            count = 0
            for name, arity, bits in CASES:
                f = getattr(original, name)
                g = getattr(rebuilt, "exported_" + name)
                ctype = ctypes.c_uint32 if bits == 32 else ctypes.c_uint64
                for function in (f, g):
                    function.argtypes = [ctype] * arity
                    function.restype = ctype
                model = core.load_function(FIXTURE, name, arity, word_bits=bits)
                for values in samples(name, arity, bits):
                    expected = reference(name, values)
                    self.assertEqual(f(*values), expected, (name, values, "CPU"))
                    self.assertEqual(g(*values), expected, (name, values, "export"))
                    self.assertEqual(model.evaluate(values), expected, (name, values, "model"))
                    count += 1
            print("BRANCH_PRODUCT_NATIVE_EVIDENCE", {"cases": count, "fixture_sha256": FIXTURE_SHA})


if __name__ == "__main__":
    unittest.main()
