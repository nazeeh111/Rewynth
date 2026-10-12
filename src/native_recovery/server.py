"""Loopback-only workbench. Artifact bytes are data, never native code to run."""

import argparse
import base64
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import multiprocessing as mp
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import urlsplit

from .artifacts import Artifact, ArtifactError, MAX_ARTIFACT
from .words import normalize_request

ROOT = Path(__file__).resolve().parent / "resources"
MAX_BODY = 45 * 1024 * 1024
MAX_STORED = 64 * 1024 * 1024


def compute(connection, request, code, address, name):
    """A process boundary bounds even a blocked solver or disassembler."""
    try:
        import resource
        import sys

        resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
        if sys.platform.startswith("linux"):
            resource.setrlimit(
                resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024)
            )
        from .engine import run_operation

        result = run_operation(request, code, address, name)
        connection.send({"state": "done", "result": result})
    except Exception as exc:
        connection.send({"state": "error", "error": str(exc)[:2048]})
    finally:
        connection.close()


class Workbench(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port=0):
        super().__init__(("127.0.0.1", port), Handler)
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.artifacts = OrderedDict()
        self.jobs = OrderedDict()
        self.context = mp.get_context("spawn")
        self.origin = f"http://127.0.0.1:{self.server_port}"

    def add_artifact(self, data):
        artifact = Artifact(data)
        with self.lock:
            if artifact.digest in self.artifacts:
                return self.artifacts[artifact.digest]
            while self.artifacts and (
                len(self.artifacts) >= 8
                or sum(len(a.data) for a in self.artifacts.values()) + len(data)
                > MAX_STORED
            ):
                self.artifacts.popitem(last=False)
            self.artifacts[artifact.digest] = artifact
        return artifact

    def start_job(self, body):
        if type(body.get("arity")) is not int or not 1 <= body["arity"] <= 4:
            raise ValueError("Select one to four integer arguments.")
        if body.get("operation") not in (
            "recover",
            "verify",
            "inverse",
            "evaluate",
            "derive_inverse",
        ):
            raise ValueError("Unknown operation.")
        if not isinstance(body.get("symbol"), str) or len(body["symbol"]) > 1024:
            raise ValueError("Invalid function name.")
        if set(body) - {
            "artifact",
            "symbol",
            "arity",
            "word_bits",
            "domain",
            "operation",
            "expression",
            "target",
            "inputs",
        }:
            raise ValueError("Unknown operation fields.")
        body = normalize_request(body, wire=True)
        with self.lock:
            if sum(j["state"] == "running" for j in self.jobs.values()) >= 2:
                raise ValueError(
                    "Two analyses are already running. Cancel one or wait."
                )
            artifact = self.artifacts.get(body.get("artifact"))
            if artifact is None:
                raise ValueError(
                    "Artifact expired from the bounded session. Reopen it."
                )
            function, code = artifact.function(body["symbol"])
            job_id = secrets.token_hex(16)
            receiver, sender = self.context.Pipe(duplex=False)
            process = self.context.Process(
                target=compute,
                args=(sender, body, code, function.address, function.name),
                daemon=True,
            )
            job = {
                "state": "running",
                "process": process,
                "receiver": receiver,
                "result": None,
                "started": time.monotonic(),
            }
            self.jobs[job_id] = job
            while len(self.jobs) > 32:
                old_id = next(
                    (k for k, j in self.jobs.items() if j["state"] != "running"), None
                )
                if old_id is None:
                    break
                self.jobs.pop(old_id)
            process.start()
            sender.close()
        threading.Thread(target=self._watch, args=(job_id,), daemon=True).start()
        return job_id

    def _watch(self, job_id):
        job = self.jobs[job_id]
        try:
            if job["receiver"].poll(20):
                result = job["receiver"].recv()
            else:
                result = {
                    "state": "error",
                    "error": "Analysis exceeded the 20-second process deadline. No equivalence conclusion.",
                }
        except (EOFError, OSError):
            result = {
                "state": "error",
                "error": "Analysis process ended without a result. No equivalence conclusion.",
            }
        finally:
            process = job["process"]
            if process.is_alive():
                process.terminate()
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
            job["receiver"].close()
        with self.lock:
            if job["state"] == "running":
                job.update(result)

    def cancel(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise ValueError("Unknown job.")
            if job["state"] == "running":
                job["state"] = "cancelled"
                if job["process"].is_alive():
                    job["process"].terminate()

    def close_jobs(self):
        for job_id in list(self.jobs):
            self.cancel(job_id)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def _send(self, value, status=200, content_type="application/json"):
        data = (
            json.dumps(value, allow_nan=False).encode()
            if content_type == "application/json"
            else value
        )
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        )
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _host(self):
        expected = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host") != expected:
            self._send(
                {"error": "Only the loopback workbench origin is accepted."}, 403
            )
            return False
        return True

    def do_GET(self):
        if not self._host():
            return
        path = urlsplit(self.path).path
        if path == "/api/bootstrap":
            return self._send({"token": self.server.token, "version": "0.2.0"})
        if path.startswith("/api/jobs/"):
            with self.server.lock:
                job = self.server.jobs.get(path.rsplit("/", 1)[1])
                if job is None:
                    return self._send({"error": "Unknown job."}, 404)
                return self._send(
                    {k: job[k] for k in ("state", "result", "error") if k in job}
                )
        assets = {
            "/": ("web/index.html", "text/html; charset=utf-8"),
            "/app.js": ("web/app.js", "text/javascript; charset=utf-8"),
            "/style.css": ("web/style.css", "text/css; charset=utf-8"),
            "/bitvector.js": ("web/bitvector.js", "text/javascript; charset=utf-8"),
            "/example": ("examples/kernels.dylib", "application/octet-stream"),
            "/example-wide": (
                "examples/wide-kernels.dylib",
                "application/octet-stream",
            ),
        }
        if path not in assets:
            return self._send({"error": "Not found."}, 404)
        filename, content_type = assets[path]
        try:
            self._send((ROOT / filename).read_bytes(), content_type=content_type)
        except FileNotFoundError:
            self._send({"error": "Packaged asset unavailable."}, 404)

    def do_POST(self):
        if not self._host():
            return
        if (
            self.headers.get("Origin") != self.server.origin
            or self.headers.get("X-Workbench-Token") != self.server.token
        ):
            return self._send(
                {"error": "Request must originate in this workbench."}, 403
            )
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if (
                not 0 < length <= MAX_BODY
                or self.headers.get_content_type() != "application/json"
            ):
                raise ValueError("Invalid JSON request size or media type.")
            self.connection.settimeout(15)
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("Request must be an object.")
            path = urlsplit(self.path).path
            if path == "/api/artifacts":
                encoded = body.get("data")
                if (
                    not isinstance(encoded, str)
                    or len(encoded) > (MAX_ARTIFACT + 2) // 3 * 4
                ):
                    raise ValueError("Invalid artifact encoding size.")
                artifact = self.server.add_artifact(
                    base64.b64decode(encoded, validate=True)
                )
                return self._send(artifact.public())
            if path == "/api/jobs":
                return self._send({"job": self.server.start_job(body)}, 202)
            if path.startswith("/api/cancel/"):
                self.server.cancel(path.rsplit("/", 1)[1])
                return self._send({"state": "cancelled"})
            return self._send({"error": "Not found."}, 404)
        except (ValueError, TypeError, OverflowError, ArtifactError) as exc:
            self._send({"error": str(exc)[:2048]}, 400)
        except Exception:
            self._send(
                {"error": "Request failed without changing artifact bytes."}, 500
            )


def main():
    parser = argparse.ArgumentParser(
        description="Local native-function recovery workbench"
    )
    parser.add_argument("--port", type=int, default=6343)
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("Port must be between 0 and 65535.")
    server = Workbench(args.port)
    print(f"Open {server.origin}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.close_jobs()
        server.server_close()


if __name__ == "__main__":
    main()
