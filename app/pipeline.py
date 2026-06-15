from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np


APP_ROOT = Path(__file__).resolve().parents[1]


def detect_project_root() -> Path:
    configured = os.environ.get("VELVET_PROJECT_ROOT")
    if configured:
        return Path(configured).expanduser().resolve(strict=False)

    nested_music_root = APP_ROOT.parent.parent
    if (nested_music_root / "01_UNSORTED").exists() and (nested_music_root / "01_TRACKS").exists():
        return nested_music_root

    return APP_ROOT


PROJECT_ROOT = detect_project_root()
DEFAULT_SOURCE_DIR = PROJECT_ROOT / "01_UNSORTED" / "The Velvet Tiki Lounge" / "Oracle of Delphi Call Center Lounge"
AUDIO_EXTENSIONS = {".wav"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


@dataclass
class RenderOptions:
    source_dir: Path
    comp_id: str
    title: str
    output_dir: Path | None = None
    longform_image: Path | None = None
    shorts_image: Path | None = None
    silence_trim: bool = True
    drone_scan: bool = True
    use_placeholder_images: bool = True
    transition_mode: str = "smooth_crossfade"
    transition_seconds: float = 1.5
    move_sources_after_render: bool = True
    track_order: list[str] | None = None
    short_count: int = 5
    short_duration: float = 30.0


def run(cmd: list[str], capture: bool = False) -> str:
    proc = subprocess.run(
        cmd,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    if proc.returncode != 0:
        detail = ""
        if capture:
            detail = f"\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}{detail}")
    if capture:
        return (proc.stdout or "") + (proc.stderr or "")
    return ""


def ffprobe_json(path: Path, entries: str) -> dict[str, Any]:
    text = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            entries,
            "-of",
            "json",
            str(path),
        ],
        capture=True,
    )
    return json.loads(text)


def probe_duration(path: Path) -> float:
    data = ffprobe_json(path, "format=duration")
    return float(data["format"]["duration"])


def probe_streams(path: Path) -> dict[str, Any]:
    return ffprobe_json(
        path,
        "format=duration:stream=index,codec_type,codec_name,width,height,pix_fmt,sample_rate,channels,sample_fmt",
    )


def duration_label(seconds: float) -> str:
    minutes = int(seconds // 60)
    secs = seconds - minutes * 60
    return f"{minutes:02d}:{secs:06.3f}"


def safe_slug(text: str, fallback: str = "untitled") -> str:
    text = text.replace("&", " and ")
    text = re.sub(r"[^A-Za-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or fallback


def public_title(path: Path) -> str:
    title = path.stem.split("__", 1)[0].strip()
    title = re.sub(r"^\d+\.\s*", "", title)
    return title.strip() or path.stem


def natural_parts(text: str) -> tuple[tuple[int, int | str], ...]:
    parts: list[tuple[int, int | str]] = []
    for part in re.split(r"(\d+)", text.lower()):
        if not part:
            continue
        if part.isdigit():
            parts.append((0, int(part)))
        else:
            parts.append((1, part))
    return tuple(parts)


def source_id_from_path(path: Path) -> str:
    match = re.search(r"__([0-9a-fA-F-]{36})$", path.stem)
    if match:
        return match.group(1)
    match = re.search(r"([0-9a-fA-F-]{36})", path.stem)
    return match.group(1) if match else safe_slug(path.stem)


def order_key(path: Path) -> tuple[int, int, tuple[tuple[int, int | str], ...], tuple[tuple[int, int | str], ...]]:
    title = public_title(path)
    leading = re.match(r"^\s*(\d+)(?:[._\-\s]+)", path.name)
    if leading:
        return 0, int(leading.group(1)), natural_parts(title), natural_parts(path.name)

    prompt = re.search(r"(?:^|[^A-Za-z0-9])prompt\s*[_\-\s]*(\d+)(?=\D|$)", path.stem, flags=re.IGNORECASE)
    if prompt:
        return 1, int(prompt.group(1)), natural_parts(title), natural_parts(path.name)

    return 2, 9999, natural_parts(title), natural_parts(path.name)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def is_suno_defect_duration(seconds: float) -> bool:
    return 478.8 <= seconds <= 480.2 or abs(seconds - 479.4) <= 0.6


def next_comp_id(root: Path) -> str:
    max_num = 0
    candidates = [root / "01_TRACKS", root / "01_UNSORTED", root / "scripts"]
    pattern = re.compile(r"VM_COMP(\d{3})")
    for base in candidates:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            for match in pattern.finditer(path.name):
                max_num = max(max_num, int(match.group(1)))
    return f"VM_COMP{max_num + 1:03d}"


def default_output_base_dir(root: Path, source_dir: Path) -> Path:
    project_name = source_dir.parent.name if source_dir.parent.name != "01_UNSORTED" else "Velvet Meridian"
    return root / "01_TRACKS" / project_name / "Compilations"


def default_output_dir(root: Path, comp_id: str, title: str, source_dir: Path) -> Path:
    return resolve_output_dir(default_output_base_dir(root, source_dir), comp_id, title)


def output_folder_name(comp_id: str, title: str) -> str:
    return f"{comp_id}_{safe_slug(title)}"


def resolve_output_dir(selected_output_dir: Path | None, comp_id: str, title: str) -> Path:
    base = selected_output_dir or default_output_base_dir(PROJECT_ROOT, DEFAULT_SOURCE_DIR)
    base = base.expanduser().resolve(strict=False)
    if base.name.startswith(f"{comp_id}_"):
        return base
    if base.name == comp_id:
        return base.parent / output_folder_name(comp_id, title)
    return base / output_folder_name(comp_id, title)


def classify_image(path: Path) -> dict[str, Any]:
    data = probe_streams(path)
    stream = next((item for item in data.get("streams", []) if item.get("codec_type") == "video"), {})
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    ratio = (width / height) if width and height else 0
    if 1.6 <= ratio <= 1.9:
        kind = "16:9"
    elif 0.5 <= ratio <= 0.65:
        kind = "9:16"
    else:
        kind = "other"
    return {
        "path": str(path),
        "name": path.name,
        "width": width,
        "height": height,
        "ratio": round(ratio, 4) if ratio else None,
        "kind": kind,
        "area": width * height,
    }


def image_score(item: dict[str, Any], target_ratio: float) -> tuple[float, int]:
    ratio = float(item.get("ratio") or 0)
    area = int(item.get("area") or 0)
    return (abs(ratio - target_ratio), -area)


def best_image(image_candidates: list[dict[str, Any]], kind: str) -> dict[str, Any] | None:
    if kind == "16:9":
        candidates = [item for item in image_candidates if item["kind"] == "16:9"]
        target_ratio = 16 / 9
    elif kind == "9:16":
        candidates = [item for item in image_candidates if item["kind"] == "9:16"]
        target_ratio = 9 / 16
    else:
        return None
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: image_score(item, target_ratio))[0]


def manual_image_role(path: Path, role: str) -> dict[str, Any]:
    try:
        item = classify_image(path)
    except Exception:
        return {"path": str(path), "name": path.name, "role": role, "assignment": "manual"}
    item["role"] = role
    item["assignment"] = "manual"
    return item


def scan_project(
    source_dir: Path,
    comp_id: str | None = None,
    title: str | None = None,
    output_dir: Path | None = None,
    longform_image: Path | None = None,
    shorts_image: Path | None = None,
    compute_hashes: bool = True,
) -> dict[str, Any]:
    source_dir = source_dir.resolve()
    if not source_dir.exists() or not source_dir.is_dir():
        raise FileNotFoundError(f"Source folder not found: {source_dir}")

    comp_id = comp_id or next_comp_id(PROJECT_ROOT)
    title = title or source_dir.name
    selected_output_dir = output_dir or default_output_base_dir(PROJECT_ROOT, source_dir)
    output_dir = resolve_output_dir(selected_output_dir, comp_id, title)

    wavs = sorted([p for p in source_dir.iterdir() if p.suffix.lower() in AUDIO_EXTENSIONS], key=order_key)
    images = sorted([p for p in source_dir.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS], key=lambda p: p.name.lower())

    tracks: list[dict[str, Any]] = []
    seen_hashes: dict[str, str] = {}
    for idx, wav in enumerate(wavs, start=1):
        reasons: list[str] = []
        duration = probe_duration(wav)
        file_hash = sha256_file(wav) if compute_hashes else None
        if is_suno_defect_duration(duration):
            reasons.append("excluded_479s_suno_defect")
        if file_hash and file_hash in seen_hashes:
            reasons.append(f"duplicate_of:{seen_hashes[file_hash]}")
        elif file_hash:
            seen_hashes[file_hash] = wav.name
        json_sidecar = wav.with_suffix(".json")
        tracks.append(
            {
                "index": idx,
                "order": order_key(wav)[1],
                "path": str(wav),
                "name": wav.name,
                "title": public_title(wav),
                "duration": round(duration, 3),
                "duration_label": duration_label(duration),
                "json_sidecar": str(json_sidecar) if json_sidecar.exists() else None,
                "sha256": file_hash,
                "status": "excluded" if reasons else "included",
                "reasons": reasons,
            }
        )

    image_candidates = [classify_image(path) for path in images]
    selected_longform = str(longform_image.resolve()) if longform_image else None
    selected_shorts = str(shorts_image.resolve()) if shorts_image else None
    auto_longform_item = best_image(image_candidates, "16:9")
    auto_shorts_item = best_image(image_candidates, "9:16")
    auto_longform = auto_longform_item["path"] if auto_longform_item else None
    auto_shorts = auto_shorts_item["path"] if auto_shorts_item else None
    image_roles = {
        "longform": manual_image_role(longform_image.resolve(), "longform") if longform_image else (
            {**auto_longform_item, "role": "longform", "assignment": "auto"} if auto_longform_item else None
        ),
        "shorts": manual_image_role(shorts_image.resolve(), "shorts") if shorts_image else (
            {**auto_shorts_item, "role": "shorts", "assignment": "auto"} if auto_shorts_item else None
        ),
    }

    blockers: list[str] = []
    warnings: list[str] = []
    if not tracks:
        blockers.append("No WAV files found")
    if not any(track["status"] == "included" for track in tracks):
        blockers.append("No valid WAV files after exclusions")
    if selected_longform and not Path(selected_longform).exists():
        blockers.append(f"16:9 image not found: {selected_longform}")
    if selected_shorts and not Path(selected_shorts).exists():
        blockers.append(f"9:16 image not found: {selected_shorts}")
    if not selected_longform and not auto_longform:
        blockers.append("Missing 16:9 longform image")
    if not selected_shorts and not auto_shorts:
        blockers.append("Missing 9:16 shorts image")
    longform_candidates = [item for item in image_candidates if item["kind"] == "16:9"]
    shorts_candidates = [item for item in image_candidates if item["kind"] == "9:16"]
    if not selected_longform and len(longform_candidates) > 1:
        warnings.append(f"Multiple 16:9 images found; auto-selected {Path(auto_longform).name}")
    if not selected_shorts and len(shorts_candidates) > 1:
        warnings.append(f"Multiple 9:16 images found; auto-selected {Path(auto_shorts).name}")
    if output_dir.exists() and any(output_dir.iterdir()):
        warnings.append("Output folder exists and is not empty; render will overwrite phase outputs")

    included_duration = sum(track["duration"] for track in tracks if track["status"] == "included")
    return {
        "source_dir": str(source_dir),
        "comp_id": comp_id,
        "title": title,
        "output_dir": str(output_dir),
        "longform_image": selected_longform or auto_longform,
        "shorts_image": selected_shorts or auto_shorts,
        "image_roles": image_roles,
        "tracks": tracks,
        "images": image_candidates,
        "summary": {
            "wav_count": len(tracks),
            "included_count": sum(1 for track in tracks if track["status"] == "included"),
            "excluded_count": sum(1 for track in tracks if track["status"] == "excluded"),
            "included_duration": round(included_duration, 3),
            "included_duration_label": duration_label(included_duration),
            "image_count": len(image_candidates),
        },
        "blockers": blockers,
        "warnings": warnings,
        "render_ready": not blockers,
    }


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_tsv(path: Path, headers: list[str], rows: list[list[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(headers)
        writer.writerows(rows)


def parse_silence_events(text: str, duration: float) -> list[tuple[float, float]]:
    events: list[tuple[float, float]] = []
    current_start: float | None = None
    for line in text.splitlines():
        start = re.search(r"silence_start: ([0-9.]+)", line)
        if start:
            current_start = float(start.group(1))
        end = re.search(r"silence_end: ([0-9.]+)", line)
        if end and current_start is not None:
            events.append((current_start, float(end.group(1))))
            current_start = None
    if current_start is not None:
        events.append((current_start, duration))
    return events


def detect_silence_events(path: Path, duration: float, noise: str = "-50dB", min_duration: float = 0.5) -> list[tuple[float, float]]:
    text = run(
        [
            "ffmpeg",
            "-nostats",
            "-hide_banner",
            "-i",
            str(path),
            "-af",
            f"silencedetect=noise={noise}:d={min_duration:.3f}",
            "-f",
            "null",
            "-",
        ],
        capture=True,
    )
    return parse_silence_events(text, duration)


def detect_edge_silence(path: Path, duration: float) -> tuple[float, float, str]:
    events = detect_silence_events(path, duration, "-50dB", 0.5)

    trim_start = 0.0
    trim_end = duration
    notes: list[str] = []
    if events:
        first_start, first_end = events[0]
        if first_start <= 0.05 and first_end <= 5.0:
            trim_start = first_end
            notes.append(f"leading_silence:{first_end:.3f}")
        last_start, last_end = events[-1]
        if last_end >= duration - 0.25 and duration - last_start <= 10.0 and last_start > trim_start + 20.0:
            trim_end = last_start
            notes.append(f"tail_silence:{duration - last_start:.3f}")
    return trim_start, trim_end, ";".join(notes) if notes else "none"


def validate_master_no_internal_silence(master: Path, duration: float, report_path: Path) -> list[dict[str, Any]]:
    events = detect_silence_events(master, duration, "-50dB", 0.75)
    gaps: list[dict[str, Any]] = []
    for start, end in events:
        silence_duration = end - start
        if start <= 0.5 or end >= duration - 0.5:
            continue
        if silence_duration >= 0.75:
            gaps.append(
                {
                    "start": start,
                    "end": end,
                    "duration": silence_duration,
                    "start_label": duration_label(start),
                    "end_label": duration_label(end),
                }
            )

    write_tsv(
        report_path,
        ["start", "end", "duration", "start_label", "end_label", "decision"],
        [
            [
                f"{gap['start']:.3f}",
                f"{gap['end']:.3f}",
                f"{gap['duration']:.3f}",
                gap["start_label"],
                gap["end_label"],
                "block_render",
            ]
            for gap in gaps
        ],
    )
    return gaps


def load_audio_tail(path: Path, start: float, duration: float, sample_rate: int = 8000) -> np.ndarray:
    proc = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{duration:.3f}",
            "-i",
            str(path),
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-f",
            "f32le",
            "-",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace"))
    return np.frombuffer(proc.stdout, dtype=np.float32)


def detect_drone_tail(path: Path, trim_start: float, trim_end: float) -> tuple[float | None, float | None, str]:
    scan_duration = min(35.0, max(0.0, trim_end - trim_start))
    if scan_duration < 8.0:
        return None, None, "too_short"
    scan_start = max(trim_start, trim_end - scan_duration)
    rate = 8000
    audio = load_audio_tail(path, scan_start, scan_duration, rate)
    if audio.size < rate * 8:
        return None, None, "too_short"

    frame = rate
    freqs = np.fft.rfftfreq(frame, 1 / rate)
    mask = (freqs >= 80) & (freqs <= 5000)
    rows: list[tuple[float, float, float, float]] = []
    for offset in range(0, audio.size - frame + 1, frame):
        chunk = audio[offset : offset + frame]
        rms = float(np.sqrt(np.mean(chunk * chunk) + 1e-12))
        if rms < 0.004:
            continue
        spec = np.abs(np.fft.rfft(chunk * np.hanning(frame)))
        band = spec[mask]
        band_freqs = freqs[mask]
        peak_index = int(np.argmax(band))
        peak = float(band[peak_index])
        median = float(np.median(band) + 1e-9)
        rows.append((offset / rate, float(band_freqs[peak_index]), peak / median, rms))

    for suffix_len in range(min(18, len(rows)), 5, -1):
        suffix = rows[-suffix_len:]
        ratios = [row[2] for row in suffix]
        fvals = [row[1] for row in suffix]
        if min(ratios) > 120 and max(fvals) - min(fvals) < 4 and float(np.std(fvals)) < 2:
            cut = scan_start + suffix[0][0]
            if trim_end - cut >= 6.0 and cut >= trim_start + 20.0:
                return max(trim_start + 20.0, cut - 0.1), float(np.median(fvals)), f"stable_tail_{suffix_len}s"
    return None, None, "no_stable_tail"


def stem_name(comp_id: str, index: int, title: str) -> str:
    return f"{comp_id}_STEM{index:02d}_{safe_slug(title)}.wav"


def concat_line(path: Path) -> str:
    return "file '" + str(path).replace("'", "'\\''") + "'"


def normalize_transition(mode: str, seconds: float) -> tuple[str, float, float]:
    clean_mode = mode if mode in {"no_crossfade", "micro_fade", "smooth_crossfade"} else "smooth_crossfade"
    clean_seconds = max(0.0, min(float(seconds), 4.0))
    if clean_mode == "no_crossfade":
        return clean_mode, 0.0, 0.08
    if clean_mode == "micro_fade":
        return clean_mode, 0.0, max(0.05, min(clean_seconds or 0.3, 1.0))
    return clean_mode, clean_seconds, 0.02


def transition_slug(mode: str, seconds: float) -> str:
    if mode == "no_crossfade":
        return "NoCrossfade"
    if mode == "micro_fade":
        return f"MicroFade_{str(seconds).replace('.', 'p')}s"
    return f"SmoothCrossfade_{str(seconds).replace('.', 'p')}s"


def normalized_path_key(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve(strict=False))


def apply_track_order(tracks: list[dict[str, Any]], track_order: list[str] | None) -> list[dict[str, Any]]:
    included = [track for track in tracks if track["status"] == "included"]
    if not track_order:
        return included

    by_path = {normalized_path_key(track["path"]): track for track in included}
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_path in track_order:
        key = normalized_path_key(raw_path)
        if key in by_path and key not in seen:
            ordered.append(by_path[key])
            seen.add(key)

    ordered.extend(track for track in included if normalized_path_key(track["path"]) not in seen)
    return ordered


def build_master_wav(audio_dir: Path, options: RenderOptions, stems: list[dict[str, Any]], crossfade_seconds: float) -> Path:
    master = audio_dir / (
        f"{options.comp_id}_{safe_slug(options.title)}_NaturalFlow_"
        f"{transition_slug(options.transition_mode, options.transition_seconds)}_HQ48k_master.wav"
    )
    if not stems:
        raise RuntimeError("No stems to build master")
    if crossfade_seconds <= 0 or len(stems) == 1:
        concat_file = audio_dir / f"{options.comp_id}_concat.txt"
        concat_file.write_text("\n".join(concat_line(Path(item["stem"])) for item in stems) + "\n", encoding="utf-8")
        run(
            [
                "ffmpeg",
                "-y",
                "-nostats",
                "-loglevel",
                "warning",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_file),
                "-map",
                "0:a:0",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-c:a",
                "pcm_s24le",
                str(master),
            ]
        )
        return master

    min_duration = min(float(item["duration"]) for item in stems)
    if crossfade_seconds >= min_duration - 1.0:
        raise RuntimeError(f"Crossfade too long for shortest stem: {crossfade_seconds:.3f}s >= {min_duration:.3f}s")

    cmd = ["ffmpeg", "-y", "-nostats", "-loglevel", "warning"]
    for item in stems:
        cmd.extend(["-i", str(item["stem"])])

    filters: list[str] = []
    previous = "0:a"
    for index in range(1, len(stems)):
        out_label = f"a{index}"
        filters.append(
            f"[{previous}][{index}:a]acrossfade=d={crossfade_seconds:.3f}:c1=qsin:c2=qsin[{out_label}]"
        )
        previous = out_label

    cmd.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            f"[{previous}]",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "pcm_s24le",
            str(master),
        ]
    )
    run(cmd)
    return master


def move_original_sources(output_dir: Path, comp_id: str, stems: list[dict[str, Any]]) -> dict[str, Any]:
    sources_dir = output_dir / "sources" / "original"
    json_dir = output_dir / "sources" / "json"
    sources_dir.mkdir(parents=True, exist_ok=True)
    json_dir.mkdir(parents=True, exist_ok=True)

    rows: list[list[Any]] = []
    moved_sources = 0
    moved_json = 0
    for item in stems:
        source = Path(item["source"])
        source_id = source_id_from_path(source)
        source_name = f"{comp_id}_SRC{int(item['index']):02d}_{safe_slug(item['title'])}_{source_id}.wav"
        target = sources_dir / source_name
        json_source = source.with_suffix(".json")
        json_target = json_dir / f"{target.stem}.json"
        wav_action = "already_in_place"
        json_action = "missing"

        if source.resolve(strict=False) != target.resolve(strict=False):
            if target.exists():
                raise RuntimeError(f"Source target already exists: {target}")
            if not source.exists():
                raise RuntimeError(f"Source WAV missing before move: {source}")
            shutil.move(str(source), str(target))
            moved_sources += 1
            wav_action = "moved"

        if json_source.exists():
            if json_source.resolve(strict=False) != json_target.resolve(strict=False):
                if json_target.exists():
                    raise RuntimeError(f"JSON target already exists: {json_target}")
                shutil.move(str(json_source), str(json_target))
                moved_json += 1
                json_action = "moved"
            else:
                json_action = "already_in_place"

        item["source"] = str(target)
        rows.append(
            [
                item["index"],
                item["title"],
                source_id,
                source.name,
                target.name,
                json_target.name if json_target.exists() else "",
                f"{float(item['duration']):.3f}",
                wav_action,
                json_action,
            ]
        )

    manifest = output_dir / "SOURCE_MANIFEST.tsv"
    write_tsv(
        manifest,
        [
            "order",
            "public_title",
            "source_id",
            "original_wav_name",
            "renamed_wav",
            "json_sidecar",
            "stem_duration",
            "wav_action",
            "json_action",
        ],
        rows,
    )
    return {
        "sources_dir": str(sources_dir),
        "json_dir": str(json_dir),
        "manifest": str(manifest),
        "moved_sources": moved_sources,
        "moved_json": moved_json,
    }


def move_visual_sources(visuals_dir: Path, comp_id: str, title: str, longform_image: Path, shorts_image: Path) -> dict[str, Any]:
    visuals_dir.mkdir(parents=True, exist_ok=True)
    rows: list[list[Any]] = []
    moved = 0
    moved_by_source: dict[Path, Path] = {}

    for role, source in [("16x9", longform_image), ("9x16", shorts_image)]:
        source = source.resolve(strict=False)
        if source in moved_by_source:
            target = moved_by_source[source]
            action = "reused_same_source"
        else:
            ext = source.suffix.lower() or ".png"
            target = visuals_dir / f"{comp_id}_{role}_{safe_slug(title)}{ext}"
            if source == target.resolve(strict=False):
                action = "already_in_place"
            else:
                if target.exists():
                    raise RuntimeError(f"Visual target already exists: {target}")
                if not source.exists():
                    raise RuntimeError(f"Visual source missing before move: {source}")
                shutil.move(str(source), str(target))
                moved += 1
                action = "moved"
            moved_by_source[source] = target

        info = classify_image(target)
        rows.append([role, source.name, target.name, info.get("width", ""), info.get("height", ""), action])

    manifest = visuals_dir / "VISUALS_MANIFEST.tsv"
    write_tsv(
        manifest,
        ["role", "original_name", "renamed_file", "width", "height", "action"],
        rows,
    )
    return {
        "visuals_dir": str(visuals_dir),
        "manifest": str(manifest),
        "moved_visuals": moved,
        "files": [row[2] for row in rows],
    }


def render_longform_mp4(master: Path, longform_image: Path, longform_mp4: Path, duration: float | None = None) -> Path:
    master_duration = duration if duration is not None else probe_duration(master)
    longform_mp4.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "ffmpeg",
            "-y",
            "-nostats",
            "-loglevel",
            "warning",
            "-loop",
            "1",
            "-framerate",
            "2",
            "-i",
            str(longform_image),
            "-i",
            str(master),
            "-t",
            f"{master_duration:.3f}",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-vf",
            "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-r",
            "2",
            "-c:a",
            "aac",
            "-b:a",
            "320k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            str(longform_mp4),
        ]
    )
    return longform_mp4


def comp_parts_from_dir(path: Path) -> tuple[str, str]:
    match = re.match(r"^(VM_COMP\d{3})_(.+)$", path.name)
    if not match:
        return "VM_COMP000", path.name
    return match.group(1), match.group(2)


def find_existing_master(output_dir: Path) -> Path | None:
    summary_path = output_dir / "RENDER_SUMMARY.json"
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            master = Path(summary.get("master_wav", "")).expanduser()
            if master.exists():
                return master
        except Exception:
            pass

    candidates = sorted((output_dir / "audio").glob("*master.wav"))
    if not candidates:
        candidates = sorted(output_dir.glob("**/*master.wav"))
    return candidates[0] if candidates else None


def find_existing_longform_image(output_dir: Path) -> Path | None:
    visual_candidates = [
        path
        for path in (output_dir / "visuals").glob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS and "16x9" in path.name.lower()
    ]
    if not visual_candidates:
        visual_candidates = [
            path
            for path in (output_dir / "visuals").glob("*")
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        ]
    for candidate in sorted(visual_candidates, key=lambda item: item.name.lower()):
        try:
            if classify_image(candidate)["kind"] == "16:9":
                return candidate
        except Exception:
            continue
    return visual_candidates[0] if visual_candidates else None


def find_existing_longform_mp4(output_dir: Path) -> Path | None:
    candidates = sorted((output_dir / "visuals").glob("*Longform.mp4"))
    if not candidates:
        candidates = sorted((output_dir / "visuals").glob("*.mp4"))
    return candidates[0] if candidates else None


def inspect_longform_repair(output_dir: Path, longform_image: Path | None = None) -> dict[str, Any]:
    output_dir = output_dir.expanduser().resolve(strict=False)
    blockers: list[str] = []
    warnings: list[str] = []
    if not output_dir.exists() or not output_dir.is_dir():
        blockers.append(f"Finished COMP folder not found: {output_dir}")

    comp_id, title_slug = comp_parts_from_dir(output_dir)
    title = title_slug.replace("_", " ")
    master = find_existing_master(output_dir) if output_dir.exists() else None
    detected_image = find_existing_longform_image(output_dir) if output_dir.exists() else None
    selected_image = longform_image.expanduser().resolve(strict=False) if longform_image else detected_image
    existing_mp4 = find_existing_longform_mp4(output_dir) if output_dir.exists() else None

    if not master:
        blockers.append("Master WAV not found in finished folder")
    elif master.exists():
        try:
            reports_dir = output_dir / "reports"
            gaps = validate_master_no_internal_silence(
                master,
                probe_duration(master),
                reports_dir / "LONGFORM_REPAIR_MASTER_SILENCE_GAPS.tsv",
            )
            if gaps:
                first_gap = gaps[0]
                blockers.append(
                    "Master WAV contains internal silence: "
                    f"{first_gap['start_label']}-{first_gap['end_label']} "
                    f"({first_gap['duration']:.3f}s)"
                )
        except Exception as exc:
            blockers.append(f"Could not validate master silence: {exc}")
    if selected_image and not selected_image.exists():
        blockers.append(f"16:9 image not found: {selected_image}")
    if not selected_image:
        blockers.append("16:9 image not found in visuals folder")
    elif selected_image.exists():
        try:
            info = classify_image(selected_image)
            if info["kind"] != "16:9":
                warnings.append(f"Selected image is {info.get('width')}x{info.get('height')}, not clearly 16:9")
        except Exception as exc:
            warnings.append(f"Could not validate image ratio: {exc}")

    target_mp4 = existing_mp4 or output_dir / "visuals" / f"{comp_id}_16x9_{safe_slug(title)}_Longform.mp4"
    return {
        "output_dir": str(output_dir),
        "comp_id": comp_id,
        "title": title,
        "master_wav": str(master) if master else "",
        "longform_image": str(selected_image) if selected_image else "",
        "current_longform_mp4": str(existing_mp4) if existing_mp4 else "",
        "target_longform_mp4": str(target_mp4),
        "blockers": blockers,
        "warnings": warnings,
        "ready": not blockers,
    }


def repair_longform(output_dir: Path, longform_image: Path | None = None, backup_existing: bool = True) -> dict[str, Any]:
    inspection = inspect_longform_repair(output_dir, longform_image)
    if inspection["blockers"]:
        raise RuntimeError("; ".join(inspection["blockers"]))

    output_dir = Path(inspection["output_dir"])
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    master = Path(inspection["master_wav"])
    image = Path(inspection["longform_image"])
    target = Path(inspection["target_longform_mp4"])
    backup_path = ""
    duration = probe_duration(master)
    silence_gaps = validate_master_no_internal_silence(master, duration, reports_dir / "LONGFORM_REPAIR_MASTER_SILENCE_GAPS.tsv")
    if silence_gaps:
        first_gap = silence_gaps[0]
        raise RuntimeError(
            "Internal silence detected in master WAV; refusing longform repair render: "
            f"{first_gap['start_label']}-{first_gap['end_label']} "
            f"({first_gap['duration']:.3f}s). See {reports_dir / 'LONGFORM_REPAIR_MASTER_SILENCE_GAPS.tsv'}"
        )

    if backup_existing and target.exists():
        backup_dir = output_dir / "backups" / "longform"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = backup_dir / f"{target.stem}_{stamp}{target.suffix}"
        shutil.move(str(target), str(backup))
        backup_path = str(backup)

    render_longform_mp4(master, image, target, duration)
    validation = media_validation_row(target)
    write_tsv(
        reports_dir / "LONGFORM_REPAIR_VALIDATION.tsv",
        ["file", "duration", "width", "height", "video_codec", "pix_fmt", "audio_codec", "sample_rate", "channels"],
        [validation],
    )
    result = {
        "kind": "longform_repair",
        "output_dir": str(output_dir),
        "master_wav": str(master),
        "longform_image": str(image),
        "longform_mp4": str(target),
        "backup": backup_path,
        "master_duration": round(duration, 3),
        "master_duration_label": duration_label(duration),
        "reports": {
            "validation": str(reports_dir / "LONGFORM_REPAIR_VALIDATION.tsv"),
            "master_silence_gaps": str(reports_dir / "LONGFORM_REPAIR_MASTER_SILENCE_GAPS.tsv"),
        },
    }
    write_json(reports_dir / "LONGFORM_REPAIR_SUMMARY.json", result)
    return result


def render_project(options: RenderOptions, log: Callable[[str], None] | None = None) -> dict[str, Any]:
    def emit(message: str) -> None:
        if log:
            log(message)

    scan = scan_project(
        source_dir=options.source_dir,
        comp_id=options.comp_id,
        title=options.title,
        output_dir=options.output_dir,
        longform_image=options.longform_image,
        shorts_image=options.shorts_image,
        compute_hashes=True,
    )
    if options.use_placeholder_images and any("Missing " in blocker and "image" in blocker for blocker in scan["blockers"]):
        output_dir = Path(scan["output_dir"])
        assets_dir = output_dir / "generated_assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        if not scan["longform_image"]:
            options.longform_image = generate_placeholder_image(assets_dir / f"{options.comp_id}_placeholder_16x9.png", "1920x1080")
            emit("Generated 16:9 test placeholder image")
        if not scan["shorts_image"]:
            options.shorts_image = generate_placeholder_image(assets_dir / f"{options.comp_id}_placeholder_9x16.png", "1080x1920")
            emit("Generated 9:16 test placeholder image")
        scan = scan_project(
            source_dir=options.source_dir,
            comp_id=options.comp_id,
            title=options.title,
            output_dir=options.output_dir,
            longform_image=options.longform_image,
            shorts_image=options.shorts_image,
            compute_hashes=True,
        )
    if scan["blockers"]:
        raise RuntimeError("; ".join(scan["blockers"]))

    output_dir = Path(scan["output_dir"])
    audio_dir = output_dir / "audio"
    stems_dir = output_dir / "stems"
    visuals_dir = output_dir / "visuals"
    shorts_dir = output_dir / "shorts"
    reports_dir = output_dir / "reports"
    for directory in (audio_dir, stems_dir, visuals_dir, shorts_dir, reports_dir):
        directory.mkdir(parents=True, exist_ok=True)

    write_json(reports_dir / "DRY_RUN.json", scan)
    emit("Dry-run report written")

    transition_mode, crossfade_seconds, stem_fade_seconds = normalize_transition(
        options.transition_mode,
        options.transition_seconds,
    )
    options.transition_mode = transition_mode
    options.transition_seconds = crossfade_seconds if transition_mode == "smooth_crossfade" else stem_fade_seconds
    emit(f"Transition mode: {transition_mode} ({options.transition_seconds:.1f}s)")

    included = apply_track_order(scan["tracks"], options.track_order)
    write_tsv(
        reports_dir / "TRACK_ORDER.tsv",
        ["order", "source_wav", "title", "duration", "path"],
        [
            [index, Path(track["path"]).name, track["title"], f"{float(track['duration']):.3f}", track["path"]]
            for index, track in enumerate(included, start=1)
        ],
    )
    stem_rows: list[list[Any]] = []
    drone_rows: list[list[Any]] = []
    rendered_stems: list[dict[str, Any]] = []

    for index, track in enumerate(included, start=1):
        source = Path(track["path"])
        original_duration = float(track["duration"])
        trim_start = 0.0
        trim_end = original_duration
        trim_note = "none"
        if options.silence_trim:
            trim_start, trim_end, trim_note = detect_edge_silence(source, original_duration)

        drone_cut = None
        drone_freq = None
        drone_note = "disabled"
        if options.drone_scan:
            drone_cut, drone_freq, drone_note = detect_drone_tail(source, trim_start, trim_end)
            if drone_cut is not None and trim_start + 20.0 < drone_cut < trim_end:
                trim_end = drone_cut

        trimmed_duration = trim_end - trim_start
        if trimmed_duration < original_duration * 0.80:
            raise RuntimeError(
                f"Trim too aggressive for {source.name}: {original_duration:.3f}s -> {trimmed_duration:.3f}s"
            )

        stem = stems_dir / stem_name(options.comp_id, index, track["title"])
        fade_start = max(0.0, trimmed_duration - stem_fade_seconds)
        emit(f"Building stem {index}/{len(included)}: {track['title']}")
        run(
            [
                "ffmpeg",
                "-y",
                "-nostats",
                "-loglevel",
                "warning",
                "-ss",
                f"{trim_start:.3f}",
                "-t",
                f"{trimmed_duration:.3f}",
                "-i",
                str(source),
                "-af",
                f"afade=t=out:st={fade_start:.3f}:d={stem_fade_seconds:.3f}",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-c:a",
                "pcm_s24le",
                str(stem),
            ]
        )
        actual_duration = probe_duration(stem)
        rendered_stems.append(
            {
                "index": index,
                "title": track["title"],
                "source": str(source),
                "stem": str(stem),
                "duration": actual_duration,
            }
        )
        stem_rows.append(
            [
                index,
                track["title"],
                source.name,
                f"{original_duration:.3f}",
                f"{trim_start:.3f}",
                f"{trim_end:.3f}",
                f"{actual_duration:.3f}",
                trim_note,
            ]
        )
        drone_rows.append(
            [
                index,
                track["title"],
                source.name,
                drone_note,
                f"{drone_cut:.3f}" if drone_cut is not None else "",
                f"{drone_freq:.2f}" if drone_freq is not None else "",
                "cut_tail" if drone_cut is not None else "keep",
            ]
        )

    write_tsv(
        reports_dir / "STEM_TRIM_REPORT.tsv",
        ["order", "title", "source_wav", "original_duration", "trim_start", "trim_end", "stem_duration", "silence_note"],
        stem_rows,
    )
    write_tsv(
        output_dir / "DRONE_ARTIFACT_REPORT.tsv",
        ["order", "title", "source_wav", "scan_result", "artifact_start", "artifact_frequency_hz", "decision"],
        drone_rows,
    )
    write_tsv(
        reports_dir / "TRANSITION_REPORT.tsv",
        ["mode", "crossfade_seconds", "stem_fade_seconds", "curve", "tracks"],
        [[transition_mode, f"{crossfade_seconds:.3f}", f"{stem_fade_seconds:.3f}", "qsin" if crossfade_seconds else "", len(rendered_stems)]],
    )

    emit("Building master WAV")
    master = build_master_wav(audio_dir, options, rendered_stems, crossfade_seconds)
    master_duration = probe_duration(master)
    silence_gaps = validate_master_no_internal_silence(master, master_duration, reports_dir / "MASTER_SILENCE_GAPS.tsv")
    if silence_gaps:
        first_gap = silence_gaps[0]
        raise RuntimeError(
            "Internal silence detected in master WAV: "
            f"{first_gap['start_label']}-{first_gap['end_label']} "
            f"({first_gap['duration']:.3f}s). See {reports_dir / 'MASTER_SILENCE_GAPS.tsv'}"
        )
    audio_validation = probe_streams(master)
    silence_validation = run(
        [
            "ffmpeg",
            "-nostats",
            "-hide_banner",
            "-i",
            str(master),
            "-af",
            "silencedetect=noise=-50dB:d=1.0",
            "-f",
            "null",
            "-",
        ],
        capture=True,
    )
    (reports_dir / "AUDIO_VALIDATION.txt").write_text(
        json.dumps(audio_validation, indent=2, ensure_ascii=False) + "\n\n" + silence_validation,
        encoding="utf-8",
    )

    tracklist_rows: list[list[Any]] = []
    cursor = 0.0
    for index, item in enumerate(rendered_stems):
        item["master_start"] = cursor
        tracklist_rows.append([item["index"], duration_label(cursor), item["title"], f"{item['duration']:.3f}"])
        cursor += item["duration"]
        if index < len(rendered_stems) - 1:
            cursor -= crossfade_seconds
    write_tsv(output_dir / "TRACKLIST.tsv", ["order", "timestamp", "title", "duration"], tracklist_rows)

    longform_image = Path(scan["longform_image"])
    shorts_image = Path(scan["shorts_image"])
    longform_mp4 = visuals_dir / f"{options.comp_id}_16x9_{safe_slug(options.title)}_Longform.mp4"
    emit("Rendering 16:9 longform MP4")
    render_longform_mp4(master, longform_image, longform_mp4, master_duration)

    short_picks = choose_short_picks(rendered_stems, options.short_count, options.short_duration)
    shorts_rows: list[list[Any]] = []
    emit("Rendering shorts")
    for short_index, pick in enumerate(short_picks, start=1):
        slug = safe_slug(pick["title"])
        out = shorts_dir / f"{options.comp_id}_SHORT{short_index:02d}_{slug}_9x16_30s.mp4"
        run(
            [
                "ffmpeg",
                "-y",
                "-nostats",
                "-loglevel",
                "warning",
                "-loop",
                "1",
                "-framerate",
                "2",
                "-i",
                str(shorts_image),
                "-ss",
                f"{pick['start']:.3f}",
                "-t",
                f"{options.short_duration:.3f}",
                "-i",
                str(master),
                "-t",
                f"{options.short_duration:.3f}",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-vf",
                "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
                "-af",
                f"atrim=0:{options.short_duration:.3f},asetpts=PTS-STARTPTS",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-r",
                "2",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-movflags",
                "+faststart",
                str(out),
            ]
        )
        shorts_rows.append([f"SHORT{short_index:02d}", duration_label(pick["start"]), pick["title"], str(out)])

    write_tsv(output_dir / "SHORTS_PLAN.tsv", ["short", "master_start", "track", "file"], shorts_rows)

    video_validation_rows = [media_validation_row(longform_mp4)]
    short_validation_rows = [media_validation_row(Path(row[3])) for row in shorts_rows]
    headers = ["file", "duration", "width", "height", "video_codec", "pix_fmt", "audio_codec", "sample_rate", "channels"]
    write_tsv(reports_dir / "VIDEO_VALIDATION.tsv", headers, video_validation_rows)
    write_tsv(shorts_dir / "SHORTS_VALIDATION.tsv", headers, short_validation_rows)

    emit("Moving selected images into visuals folder")
    visual_package = move_visual_sources(visuals_dir, options.comp_id, options.title, longform_image, shorts_image)

    source_package = None
    if options.move_sources_after_render:
        emit("Moving original tracks into target folder")
        source_package = move_original_sources(output_dir, options.comp_id, rendered_stems)

    metadata_path = output_dir / "YOUTUBE_METADATA.md"
    metadata_path.write_text(build_metadata_template(options, tracklist_rows, master_duration), encoding="utf-8")

    summary = {
        "output_dir": str(output_dir),
        "master_wav": str(master),
        "longform_mp4": str(longform_mp4),
        "shorts": [row[3] for row in shorts_rows],
        "master_duration": round(master_duration, 3),
        "master_duration_label": duration_label(master_duration),
        "included_tracks": len(included),
        "excluded_tracks": scan["summary"]["excluded_count"],
        "transition": {
            "mode": transition_mode,
            "crossfade_seconds": round(crossfade_seconds, 3),
            "stem_fade_seconds": round(stem_fade_seconds, 3),
        },
        "visual_package": visual_package,
        "source_package": source_package,
        "reports": {
            "dry_run": str(reports_dir / "DRY_RUN.json"),
            "tracklist": str(output_dir / "TRACKLIST.tsv"),
            "drone": str(output_dir / "DRONE_ARTIFACT_REPORT.tsv"),
            "transition": str(reports_dir / "TRANSITION_REPORT.tsv"),
            "track_order": str(reports_dir / "TRACK_ORDER.tsv"),
            "master_silence_gaps": str(reports_dir / "MASTER_SILENCE_GAPS.tsv"),
            "visuals_manifest": visual_package["manifest"],
            "source_manifest": source_package["manifest"] if source_package else "",
            "audio_validation": str(reports_dir / "AUDIO_VALIDATION.txt"),
            "video_validation": str(reports_dir / "VIDEO_VALIDATION.tsv"),
            "shorts_validation": str(shorts_dir / "SHORTS_VALIDATION.tsv"),
            "metadata": str(metadata_path),
        },
    }
    write_json(output_dir / "RENDER_SUMMARY.json", summary)
    emit("Render complete")
    return summary


def generate_placeholder_image(path: Path, size: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "ffmpeg",
            "-y",
            "-nostats",
            "-loglevel",
            "warning",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x151515:s={size}",
            "-frames:v",
            "1",
            "-update",
            "1",
            str(path),
        ]
    )
    return path


def choose_short_picks(stems: list[dict[str, Any]], count: int, duration: float) -> list[dict[str, Any]]:
    if not stems:
        return []
    count = max(1, min(count, len(stems)))
    if count == 1:
        indexes = [0]
    else:
        indexes = sorted({round(i * (len(stems) - 1) / (count - 1)) for i in range(count)})
    picks = []
    for index in indexes[:count]:
        item = stems[index]
        offset = min(10.0, max(0.0, item["duration"] - duration))
        picks.append({"title": item["title"], "start": item["master_start"] + offset})
    return picks


def media_validation_row(path: Path) -> list[Any]:
    data = probe_streams(path)
    duration = float(data.get("format", {}).get("duration", 0.0))
    video = next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"), {})
    audio = next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "audio"), {})
    return [
        path.name,
        f"{duration:.3f}",
        video.get("width", ""),
        video.get("height", ""),
        video.get("codec_name", ""),
        video.get("pix_fmt", ""),
        audio.get("codec_name", ""),
        audio.get("sample_rate", ""),
        audio.get("channels", ""),
    ]


def build_metadata_template(options: RenderOptions, tracklist_rows: list[list[Any]], duration: float) -> str:
    lines = [
        f"# {options.comp_id} YouTube Metadata Draft",
        "",
        "## Verwendeter Titel",
        "",
        f"{options.title} | Lounge Music for Hotel Bars and Cocktail Lounges",
        "",
        "## Hauptbeschreibung",
        "",
        (
            f"{options.title} is a Velvet Meridian longform lounge session for hotel bars, "
            "cocktail lounges, restaurant lounges and late dinner ambience."
        ),
        "",
        "## Tracklist",
        "",
    ]
    for order, timestamp, title, _stem_duration in tracklist_rows:
        lines.append(f"{timestamp} {title}")
    lines.extend(
        [
            "",
            "## Produktionsnotiz",
            "",
            f"Master duration: {duration_label(duration)}.",
            f"Transition mode: {options.transition_mode}, {options.transition_seconds:.1f}s.",
            "This v0 metadata file is a render placeholder, not the final channel-optimized upload copy.",
            "",
        ]
    )
    return "\n".join(lines)
