from __future__ import annotations

import platform
from pathlib import Path
import shutil
import subprocess
from threading import Lock, Thread
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .pipeline import (
    DEFAULT_SOURCE_DIR,
    PROJECT_ROOT,
    RenderOptions,
    default_output_base_dir,
    default_output_dir,
    next_comp_id,
    render_project,
    scan_project,
)


APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"

app = FastAPI(title="Velvet Video Maker")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

jobs: dict[str, dict[str, Any]] = {}
jobs_lock = Lock()
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


class ScanRequest(BaseModel):
    source_dir: str
    comp_id: str | None = None
    title: str | None = None
    output_dir: str | None = None
    longform_image: str | None = None
    shorts_image: str | None = None
    compute_hashes: bool = True


class RenderRequest(ScanRequest):
    silence_trim: bool = True
    drone_scan: bool = True
    use_placeholder_images: bool = True
    transition_mode: str = "smooth_crossfade"
    transition_seconds: float = 1.5
    move_sources_after_render: bool = True
    track_order: list[str] = Field(default_factory=list)
    short_count: int = 5
    short_duration: float = 30.0


class MkdirRequest(BaseModel):
    parent: str
    name: str


class DialogRequest(BaseModel):
    current_path: str | None = None
    mode: str = "folder"
    prompt: str | None = None


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/defaults")
def defaults() -> dict[str, Any]:
    comp_id = next_comp_id(PROJECT_ROOT)
    title = Path(DEFAULT_SOURCE_DIR).name
    return {
        "project_root": str(PROJECT_ROOT),
        "source_dir": str(DEFAULT_SOURCE_DIR),
        "comp_id": comp_id,
        "title": title,
        "output_dir": str(default_output_base_dir(PROJECT_ROOT, DEFAULT_SOURCE_DIR)),
        "final_output_dir": str(default_output_dir(PROJECT_ROOT, comp_id, title, DEFAULT_SOURCE_DIR)),
    }


@app.get("/api/runtime")
def runtime() -> dict[str, Any]:
    native_dialog_available = platform.system() == "Darwin" and shutil.which("osascript") is not None
    return {
        "platform": platform.system(),
        "project_root": str(PROJECT_ROOT),
        "native_dialog_available": native_dialog_available,
        "native_dialog_reason": "" if native_dialog_available else "Native Finder dialogs require this app to run locally on macOS.",
    }


@app.get("/api/fs/list")
def list_fs(path: str | None = None, mode: str = "folder") -> dict[str, Any]:
    requested = Path(path).expanduser() if path else PROJECT_ROOT
    try:
        base = requested.resolve(strict=False)
        if base.is_file():
            base = base.parent
        while not base.exists() and base.parent != base:
            base = base.parent
        if not base.exists() or not base.is_dir():
            raise FileNotFoundError(f"Folder not found: {base}")

        entries = []
        for child in base.iterdir():
            if child.name.startswith("."):
                continue
            try:
                is_dir = child.is_dir()
                is_file = child.is_file()
            except OSError:
                continue
            if is_dir:
                entries.append({"name": child.name, "path": str(child), "kind": "folder"})
            elif mode == "image" and is_file and child.suffix.lower() in IMAGE_SUFFIXES:
                entries.append({"name": child.name, "path": str(child), "kind": "image"})
        entries.sort(key=lambda item: (item["kind"] != "folder", item["name"].lower()))
        return {
            "path": str(base),
            "parent": str(base.parent) if base.parent != base else None,
            "entries": entries,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/fs/mkdir")
def mkdir(req: MkdirRequest) -> dict[str, str]:
    parent = Path(req.parent).expanduser().resolve()
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Folder name is required")
    if "/" in name or "\\" in name or name in {".", ".."}:
        raise HTTPException(status_code=400, detail="Folder name must be a single folder name")
    try:
        target = parent / name
        target.mkdir(parents=False, exist_ok=False)
        return {"path": str(target)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/dialog/choose")
def choose_path(req: DialogRequest) -> dict[str, str | None]:
    try:
        if platform.system() != "Darwin" or shutil.which("osascript") is None:
            raise RuntimeError("Native Finder dialogs are only available when the app runs locally on macOS.")
        start = nearest_existing_path(Path(req.current_path).expanduser() if req.current_path else PROJECT_ROOT)
        prompt = req.prompt or ("Bild auswählen" if req.mode == "image" else "Ordner auswählen")
        if req.mode == "image":
            script = (
                "set pickedFile to choose file with prompt "
                f"{applescript_quote(prompt)} default location POSIX file {applescript_quote(str(start))} "
                'of type {"public.png", "public.jpeg", "public.webp", "PNG", "JPEG", "JPG", "WEBP"}\n'
                "return POSIX path of pickedFile"
            )
        else:
            script = (
                "set pickedFolder to choose folder with prompt "
                f"{applescript_quote(prompt)} default location POSIX file {applescript_quote(str(start))}\n"
                "return POSIX path of pickedFolder"
            )
        proc = subprocess.run(
            ["osascript", "-e", script],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if proc.returncode != 0:
            if "User canceled" in proc.stderr:
                return {"path": None}
            raise RuntimeError(proc.stderr.strip() or "macOS dialog failed")
        return {"path": proc.stdout.strip()}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/scan")
def scan(req: ScanRequest) -> dict[str, Any]:
    try:
        return scan_project(
            source_dir=Path(req.source_dir).expanduser(),
            comp_id=req.comp_id,
            title=req.title,
            output_dir=Path(req.output_dir).expanduser() if req.output_dir else None,
            longform_image=Path(req.longform_image).expanduser() if req.longform_image else None,
            shorts_image=Path(req.shorts_image).expanduser() if req.shorts_image else None,
            compute_hashes=req.compute_hashes,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/render")
def render(req: RenderRequest) -> dict[str, str]:
    job_id = uuid4().hex
    with jobs_lock:
        jobs[job_id] = {"status": "queued", "messages": [], "result": None, "error": None}

    def log(message: str) -> None:
        with jobs_lock:
            jobs[job_id]["messages"].append(message)

    def run_job() -> None:
        with jobs_lock:
            jobs[job_id]["status"] = "running"
        try:
            options = RenderOptions(
                source_dir=Path(req.source_dir).expanduser(),
                comp_id=req.comp_id or next_comp_id(PROJECT_ROOT),
                title=req.title or Path(req.source_dir).name,
                output_dir=Path(req.output_dir).expanduser() if req.output_dir else None,
                longform_image=Path(req.longform_image).expanduser() if req.longform_image else None,
                shorts_image=Path(req.shorts_image).expanduser() if req.shorts_image else None,
                silence_trim=req.silence_trim,
                drone_scan=req.drone_scan,
                use_placeholder_images=req.use_placeholder_images,
                transition_mode=req.transition_mode,
                transition_seconds=req.transition_seconds,
                move_sources_after_render=req.move_sources_after_render,
                track_order=req.track_order,
                short_count=req.short_count,
                short_duration=req.short_duration,
            )
            result = render_project(options, log=log)
            with jobs_lock:
                jobs[job_id]["status"] = "done"
                jobs[job_id]["result"] = result
        except Exception as exc:
            with jobs_lock:
                jobs[job_id]["status"] = "error"
                jobs[job_id]["error"] = str(exc)

    Thread(target=run_job, daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Unknown job")
        return dict(job)


def nearest_existing_path(path: Path) -> Path:
    candidate = path.resolve(strict=False)
    if candidate.is_file():
        candidate = candidate.parent
    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent
    if not candidate.exists() or not candidate.is_dir():
        return PROJECT_ROOT
    return candidate


def applescript_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
