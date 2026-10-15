"""Scriptable recovery through the same engine as the local workbench."""

import argparse
import json
import multiprocessing as mp
from pathlib import Path
import sys
from .artifacts import Artifact, MAX_ARTIFACT
from .words import pattern


def artifact_selector(parser):
    parser.add_argument("artifact", type=Path, nargs="?")
    examples = parser.add_mutually_exclusive_group()
    examples.add_argument(
        "--example", action="store_true", help="Use the shipped compiled fixture as data"
    )
    examples.add_argument(
        "--example-wide", action="store_true", help="Use the shipped 64-bit transform fixture as data"
    )
    examples.add_argument(
        "--example-branches", action="store_true", help="Use the shipped bounded conditional-branch fixture as data"
    )


def bounded_operation(request, code, address, name):
    from .server import compute

    context = mp.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=compute, args=(sender, request, code, address, name), daemon=True
    )
    try:
        process.start()
        sender.close()
        if not receiver.poll(20):
            raise ValueError(
                "Analysis exceeded the 20-second deadline. No equivalence conclusion."
            )
        result = receiver.recv()
        if result["state"] != "done":
            raise ValueError(result.get("error", "Analysis failed."))
        return result["result"]
    except EOFError:
        raise ValueError("Analysis process ended without a result.") from None
    finally:
        if process.pid:
            if process.is_alive():
                process.terminate()
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
        receiver.close()
        sender.close()


def main():
    parser = argparse.ArgumentParser(
        prog="rewynth",
        description="Recover and challenge selected ARM64 integer function semantics locally.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Open the loopback workbench")
    serve.add_argument("--port", type=int, default=6343)
    inspect = sub.add_parser(
        "inspect", help="Read an artifact inventory without running it"
    )
    artifact_selector(inspect)
    for operation in ["recover", "verify", "inverse", "evaluate", "derive_inverse"]:
        child = sub.add_parser(operation)
        artifact_selector(child)
        child.add_argument(
            "--word-bits",
            type=int,
            choices=(32, 64),
            default=32,
            help="Declare the argument and result width; defaults to 32",
        )
        child.add_argument("--function", required=True)
        child.add_argument("--arguments", type=int, choices=range(1, 5), required=True)
        child.add_argument(
            "--domain",
            help="JSON list of null or {min,max,signed} entries; omitted means all patterns of the selected word size",
        )
        if operation == "verify":
            child.add_argument(
                "--expression",
                type=Path,
                required=True,
                help="Safe expression text file; never arbitrary Python or C",
            )
        if operation == "inverse":
            child.add_argument("--target", type=lambda s: int(s, 0), required=True)
        if operation == "evaluate":
            child.add_argument(
                "--inputs", type=lambda s: int(s, 0), nargs="+", required=True
            )
    args = parser.parse_args()
    try:
        if args.command == "serve":
            from .server import main as serve_main

            sys.argv = ["rewynth serve", "--port", str(args.port)]
            return serve_main()
        if sum(bool(v) for v in (args.example, args.example_wide, args.example_branches, args.artifact)) != 1:
            raise ValueError(
                "Select an artifact path, --example, --example-wide or --example-branches, exactly one."
            )
        selected_path = (
            Path(__file__).parent
            / (
                "resources/examples/branch-kernels.dylib"
                if args.example_branches
                else "resources/examples/wide-kernels.dylib"
                if args.example_wide
                else "resources/examples/kernels.dylib"
            )
            if args.example or args.example_wide or args.example_branches
            else args.artifact
        )
        with selected_path.open("rb") as stream:
            artifact = Artifact(stream.read(MAX_ARTIFACT + 1))
        if args.command == "inspect":
            result = artifact.public()
        else:
            function, code = artifact.function(args.function)
            request = {
                "operation": args.command,
                "artifact": artifact.digest,
                "arity": args.arguments,
                "word_bits": args.word_bits,
            }
            if args.domain:
                request["domain"] = json.loads(args.domain)
            if args.command == "verify":
                with args.expression.open("r") as stream:
                    request["expression"] = stream.read(65537)
            if args.command == "inverse":
                request["target"] = pattern(args.target, args.word_bits, signed=True)
            if args.command == "evaluate":
                request["inputs"] = [
                    pattern(v, args.word_bits, signed=True) for v in args.inputs
                ]
            result = bounded_operation(request, code, function.address, function.name)
        print(json.dumps(result, indent=2, allow_nan=False))
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
