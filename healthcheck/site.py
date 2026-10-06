from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path
import random
import tempfile

from .core import (UTC, TOKEN_KEYS, clean_record, parse_time, read_json, save_results,
                   timestamp, window_stats, write_json)

ROOT = Path(__file__).resolve().parents[1]


def build_site(config: dict, data_dir: Path, output: Path, now=None, demo=False) -> dict:
    now = now or dt.datetime.now(UTC)
    output = output.resolve()
    if output == ROOT or output == data_dir.resolve() or ROOT.is_relative_to(output) or data_dir.resolve().is_relative_to(output):
        raise ValueError("Output must be a separate generated-site directory")
    output.mkdir(parents=True, exist_ok=True)
    assets = {source.name: source.read_bytes() for source in (ROOT / "web").iterdir() if source.is_file()}
    version = hashlib.sha256(b"".join(name.encode() + assets[name] for name in sorted(assets))).hexdigest()[:16]
    names = {name: f"{Path(name).stem}.{version}{Path(name).suffix}" if Path(name).suffix in (".mjs", ".css", ".svg") else name
             for name in assets}
    for name, content in assets.items():
        # Keep original URLs working while a CDN or browser still has the old HTML.
        (output / name).write_bytes(content)
        if Path(name).suffix in (".html", ".mjs", ".css"):
            for original, generated in names.items():
                content = content.replace(("./" + original).encode(), ("./" + generated).encode())
        (output / names[name]).write_bytes(content)
    (output / ".nojekyll").touch()
    meta = read_json(data_dir / "meta.json", {})
    latest = read_json(data_dir / "latest.json", {})
    records, history = [], []
    cutoff = (now.date() - dt.timedelta(days=config["retention_days"] - 1)).isoformat()
    for source in sorted((data_dir / "history").glob("*.json")):
        if source.stem < cutoff:
            continue
        checks = [clean_record(record) for record in read_json(source)["checks"]]
        records.extend(checks)
        history.append({"date": source.stem, "url": f"data/history/{source.name}"})
        write_json(output / "data" / "history" / source.name, {"schema_version": 1, "date": source.stem, "checks": checks})
    # Remove generated daily files no longer in the manifest, without touching source data.
    keep = {entry["date"] for entry in history}
    for generated in (output / "data" / "history").glob("*.json"):
        if generated.stem not in keep:
            generated.unlink()
    summaries = []
    for source in sorted((data_dir / "summaries").glob("*.json")):
        value = read_json(source)
        safe_models = {}
        for model_id, counts in value["models"].items():
            if model_id not in {model["id"] for model in config["models"]}:
                continue
            fields = ("success", "failure", "account_restricted", "unknown", "latency_sum_ms", "latency_count")
            safe_counts = {key: counts[key] for key in fields if type(counts.get(key)) is int and counts[key] >= 0}
            safe_counts["usage"] = {key: number for key, number in counts.get("usage", {}).items()
                                    if key in TOKEN_KEYS and type(number) is int and number >= 0}
            safe_models[model_id] = safe_counts
        summaries.append({"date": source.stem, "models": safe_models})
    write_json(output / "data" / "daily.json", {"schema_version": 1, "days": summaries})
    by_model = {model["id"]: [] for model in config["models"]}
    for record in records:
        if record["model"] in by_model:
            by_model[record["model"]].append(record)
    models = []
    for model in config["models"]:
        recent = clean_record(latest[model["id"]]) if model["id"] in latest else None
        age = (now - parse_time(recent["checked_at"])).total_seconds() if recent else None
        stale = age is None or age < -60 or age > config["stale_after_minutes"] * 60
        started = meta["model_started_at"].get(model["id"]) if "model_started_at" in meta else meta.get("monitor_started_at")
        models.append({"id": model["id"], "provider": model.get("provider", "Other"), "protocol": model["protocol"],
                       "started_at": started,
                       "latest": recent, "current_status": "unknown" if stale else recent["status"],
                       "stats": {str(hours): window_stats(by_model[model["id"]], now, hours, config["interval_minutes"], started)
                                 for hours in (24, 168, 720)}})
    manifest = {"schema_version": 1, "title": config["title"], "generated_at": timestamp(now),
                "last_run_at": meta.get("last_run_at"), "monitor_started_at": meta.get("monitor_started_at"),
                "interval_minutes": config["interval_minutes"], "stale_after_minutes": config["stale_after_minutes"],
                "timezone": config["timezone"], "probe_location": config["probe_location"], "is_demo": demo,
                "models": models, "history": history, "daily_url": "data/daily.json"}
    write_json(output / "data" / "status.json", manifest)
    return manifest


def build_demo(config: dict, output: Path) -> None:
    """Synthetic preview only: never read a key or call any inference endpoint."""
    now = dt.datetime.now(UTC).replace(second=0, microsecond=0)
    seconds = config["interval_minutes"] * 60
    now = dt.datetime.fromtimestamp(int(now.timestamp() // seconds) * seconds, UTC)
    rng, records = random.Random(42), []
    total_steps = 5 * 24 * 60 // config["interval_minutes"]
    for step in range(total_steps):
        checked_at = timestamp(now - dt.timedelta(minutes=config["interval_minutes"] * (total_steps - 1 - step)))
        for index, model in enumerate(config["models"]):
            if index == 10 and step >= total_steps - 5 or (step + index) % 83 == 0:
                continue
            status, reason = "success", "ok"
            if index == 12 and step >= total_steps - 7:
                status, reason = "failure", "timeout"
            elif index == 16 and step >= total_steps - 3:
                status, reason = "account_restricted", "rate_limited"
            elif rng.random() < .018:
                status, reason = "failure", "upstream_error"
            elif index == 2 and 365 < step < 382:
                status, reason = "failure", "empty_response"
            records.append({"model": model["id"], "checked_at": checked_at, "status": status, "reason": reason,
                "latency_ms": 60000 if reason == "timeout" else round(700 + index * 110 + rng.random() * 2000),
                "http_status": None if reason == "timeout" else 429 if reason == "rate_limited" else 502 if reason == "upstream_error" else 200,
                "usage": {"input_tokens": 8, "output_tokens": 2, "total_tokens": 10} if status == "success" else {}})
    with tempfile.TemporaryDirectory() as temporary:
        data_dir = Path(temporary)
        save_results(data_dir, records, config["retention_days"], now)
        build_site(config, data_dir, output, now, demo=True)
