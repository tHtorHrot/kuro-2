"""Internal-only parser service. No credentials or database mounts in Compose."""

import asyncio
import json
import os
import signal
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, Request
from starlette.responses import JSONResponse

from jarvis.knowledge.config import KINDS, MAX_FILE, MAX_RESULT, PARSER_SECONDS

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
slot = asyncio.Semaphore(1)


@app.get("/health")
async def health():
    return {"parser": "ready"}


@app.post("/extract")
async def extract_request(request: Request, kind: str, ocr: str = "auto"):
    if kind not in KINDS or ocr not in {"auto", "always", "never"}:
        return JSONResponse({"code": "unsupported_file_type"}, status_code=400)
    if slot.locked():
        return JSONResponse({"code": "parser_busy"}, status_code=503)
    async with slot:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / ("input." + kind)
            output = Path(directory) / "result.json"
            size = 0
            try:
                async with asyncio.timeout(30):
                    with source.open("wb") as stream:
                        async for chunk in request.stream():
                            size += len(chunk)
                            if size > MAX_FILE:
                                return JSONResponse({"code": "file_too_large"}, status_code=413)
                            stream.write(chunk)
            except TimeoutError:
                return JSONResponse({"code": "upload_timeout"}, status_code=408)
            if size == 0:
                return JSONResponse({"code": "empty_file"}, status_code=400)
            with output.open("wb") as stdout:
                child = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "jarvis.knowledge.parser_app",
                    str(source),
                    kind,
                    ocr,
                    stdout=stdout,
                    stderr=asyncio.subprocess.DEVNULL,
                    start_new_session=True,
                )
                try:
                    await asyncio.wait_for(child.wait(), PARSER_SECONDS)
                except (TimeoutError, asyncio.CancelledError):
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    await child.wait()
                    return JSONResponse({"code": "parser_timeout"}, status_code=422)
            if output.stat().st_size > MAX_RESULT or child.returncode:
                return JSONResponse({"code": "parser_resource_limit"}, status_code=422)
            try:
                result = json.loads(output.read_bytes())
            except (ValueError, OSError):
                return JSONResponse({"code": "parser_failed"}, status_code=422)
            return JSONResponse(result, status_code=422 if "code" in result else 200)


def child_main():
    try:
        import resource  # POSIX only; Windows has no resource module

        resource.setrlimit(resource.RLIMIT_AS, (768 * 1024**2, 768 * 1024**2))
        resource.setrlimit(resource.RLIMIT_CPU, (PARSER_SECONDS, PARSER_SECONDS))
        resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024**2, 32 * 1024**2))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    except ImportError:
        pass
    from jarvis.knowledge.config import KnowledgeError
    from jarvis.knowledge.extraction import extract

    try:
        rows = extract(Path(sys.argv[1]), sys.argv[2], sys.argv[3])
        print(json.dumps({"segments": [asdict(s) for s in rows]}, ensure_ascii=False))
    except KnowledgeError as exc:
        print(json.dumps({"code": str(exc)}))
    except Exception:
        print(json.dumps({"code": "parser_rejected"}))


if __name__ == "__main__":
    child_main()
