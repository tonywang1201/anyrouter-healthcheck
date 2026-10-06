from __future__ import annotations

import concurrent.futures
import copy
import datetime as dt
import http.client
import json
import math
import os
from pathlib import Path
import re
import socket
import ssl
import time
from urllib.parse import urlsplit

UTC = dt.timezone.utc
PROTOCOL_PATHS = {
    "messages": "/v1/messages",
    "responses": "/v1/responses",
    "chat_completions": "/v1/chat/completions",
}
STATUSES = {"success", "failure", "account_restricted", "unknown"}
REASONS = {
    "ok", "invalid_api_key", "permission_denied", "quota_exceeded", "rate_limited",
    "endpoint_or_model_not_found", "invalid_request", "upstream_error", "access_denied",
    "http_error", "timeout", "network_error", "invalid_json", "invalid_response",
    "empty_response", "incomplete_response", "response_too_large", "monitor_error",
    "monitor_not_configured",
}
TOKEN_KEYS = {
    "input_tokens", "output_tokens", "total_tokens", "cached_tokens", "reasoning_tokens",
    "cache_creation_input_tokens", "cache_read_input_tokens",
}
MAX_RESPONSE_BYTES = 128 * 1024


def timestamp(value: dt.datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must have a timezone")
    return parsed.astimezone(UTC)


def read_json(path: Path, default=None):
    if not path.exists():
        return copy.deepcopy(default)
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_config(path: Path) -> dict:
    config = read_json(path)
    if not isinstance(config, dict) or not isinstance(config.get("models"), list) or not config["models"]:
        raise ValueError("Config must contain a nonempty models list")
    defaults = {"interval_minutes": 15, "stale_after_minutes": 30, "retention_days": 90,
                "timeout_seconds": 60, "concurrency": 2, "api_key_env": "ANYROUTER_API_KEY",
                "prompt": "Reply with OK only.", "title": "AnyRouter 模型状态",
                "timezone": "Asia/Hong_Kong", "probe_location": "GitHub Actions / Ubuntu"}
    config = {**defaults, **config}
    for field in ("interval_minutes", "stale_after_minutes", "retention_days", "timeout_seconds", "concurrency"):
        value = config[field]
        if type(value) is not int or value < 1:
            raise ValueError(f"{field} must be a positive integer")
    if config["concurrency"] > 8 or config["timeout_seconds"] > 300:
        raise ValueError("concurrency must be <= 8 and timeout_seconds <= 300")
    if config["stale_after_minutes"] < config["interval_minutes"]:
        raise ValueError("stale_after_minutes must be >= interval_minutes")
    seen = set()
    for model in config["models"]:
        model_id = model.get("id", "")
        if not isinstance(model_id, str) or not re.fullmatch(r"[\w./:-]{1,150}", model_id, flags=re.ASCII) or model_id in seen:
            raise ValueError("Model IDs must be unique and contain only letters, numbers, _, ., /, :, -")
        seen.add(model_id)
        if model.get("protocol") not in PROTOCOL_PATHS:
            raise ValueError(f"Unknown protocol for {model_id}")
        base = urlsplit(model.get("base_url", config.get("base_url", "")))
        if base.scheme != "https" or not base.hostname or base.username or base.password or base.query or base.fragment or base.path not in ("", "/"):
            raise ValueError(f"base_url for {model_id} must be an HTTPS origin; use path for the endpoint")
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", model.get("api_key_env", config["api_key_env"])):
            raise ValueError(f"Invalid api_key_env for {model_id}")
        if model.get("auth", "bearer") not in {"bearer", "x-api-key"}:
            raise ValueError(f"Invalid auth for {model_id}")
        endpoint = model.get("path", PROTOCOL_PATHS[model["protocol"]])
        if not isinstance(endpoint, str) or not endpoint.startswith("/") or endpoint.startswith("//") or any(c in endpoint for c in "?#\r\n"):
            raise ValueError(f"Invalid endpoint path for {model_id}")
        parameters = model.get("parameters", {})
        if not isinstance(parameters, dict) or {"model", "messages", "input", "stream"} & parameters.keys():
            raise ValueError(f"parameters must not override model, messages, input or stream for {model_id}")
        budget_name = "max_output_tokens" if model["protocol"] == "responses" else "max_tokens" if model["protocol"] == "messages" else None
        budget = parameters.get(budget_name) if budget_name else parameters.get("max_completion_tokens", parameters.get("max_tokens"))
        if type(budget) is not int or budget < 1 or budget > 8192:
            raise ValueError(f"An output token limit between 1 and 8192 is required for {model_id}")
    return config


def request_spec(config: dict, model: dict, key: str) -> tuple[str, dict, bytes]:
    protocol = model["protocol"]
    url = model.get("base_url", config["base_url"]).rstrip("/") + model.get("path", PROTOCOL_PATHS[protocol])
    headers = {"Content-Type": "application/json", "Accept": "application/json", "Accept-Encoding": "identity",
               "User-Agent": "anyrouter-healthcheck/1.0"}
    headers["x-api-key" if model.get("auth", "bearer") == "x-api-key" else "Authorization"] = key if model.get("auth") == "x-api-key" else "Bearer " + key
    body = {"model": model["id"], "stream": False, **model.get("parameters", {})}
    if protocol == "responses":
        body["input"] = config["prompt"]
    else:
        body["messages"] = [{"role": "user", "content": config["prompt"]}]
    if protocol == "messages":
        headers["anthropic-version"] = "2023-06-01"
    return url, headers, json.dumps(body).encode("utf-8")


class ResponseTooLarge(Exception):
    pass


def http_post(url: str, headers: dict, body: bytes, timeout: int) -> tuple[int, bytes]:
    """One request, no redirects/retries, with a total network deadline and bounded body."""
    parsed = urlsplit(url)
    connection_type = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    kwargs = {"timeout": timeout}
    if parsed.scheme == "https":
        kwargs["context"] = ssl.create_default_context()
    connection = connection_type(parsed.hostname, parsed.port, **kwargs)
    deadline = time.monotonic() + timeout

    def remaining() -> float:
        result = deadline - time.monotonic()
        if result <= 0:
            raise TimeoutError("Request deadline exceeded")
        return result

    try:
        connection.connect()
        network_socket = connection.sock
        network_socket.settimeout(remaining())
        connection.request("POST", parsed.path or "/", body=body, headers=headers)
        network_socket.settimeout(remaining())
        response = connection.getresponse()
        if response.getheader("Content-Length", "").isdigit() and int(response.getheader("Content-Length")) > MAX_RESPONSE_BYTES:
            raise ResponseTooLarge()
        chunks, size = [], 0
        while not response.isclosed():
            network_socket.settimeout(remaining())
            chunk = response.read1(min(8192, MAX_RESPONSE_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise ResponseTooLarge()
        return response.status, b"".join(chunks)
    finally:
        connection.close()


def error_category(http_status: int, payload) -> tuple[str, str]:
    # Error text is used only for classification and is never persisted or logged.
    text = json.dumps(payload, ensure_ascii=False).lower() if isinstance(payload, dict) else ""
    if http_status == 401:
        return "account_restricted", "invalid_api_key"
    if http_status == 429:
        return "account_restricted", "rate_limited"
    if http_status == 402 or any(term in text for term in ("insufficient_quota", "insufficient balance", "credit balance", "余额不足", "额度不足", "quota_exceeded")):
        return "account_restricted", "quota_exceeded"
    if any(term in text for term in ("invalid_api_key", "invalid api key", "令牌无效")):
        return "account_restricted", "invalid_api_key"
    if http_status == 403:
        return ("account_restricted", "permission_denied") if isinstance(payload, dict) else ("failure", "access_denied")
    if http_status == 404:
        return "failure", "endpoint_or_model_not_found"
    if http_status in (400, 422):
        return "failure", "invalid_request"
    if http_status >= 500 or isinstance(payload, dict) and payload.get("error"):
        return "failure", "upstream_error"
    return "failure", "http_error"


def safe_usage(payload: dict) -> dict:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return {}
    values = {"input_tokens": usage.get("input_tokens", usage.get("prompt_tokens")),
              "output_tokens": usage.get("output_tokens", usage.get("completion_tokens")),
              "total_tokens": usage.get("total_tokens"),
              "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
              "cache_read_input_tokens": usage.get("cache_read_input_tokens")}
    for source, target in (("input_tokens_details", "cached_tokens"), ("prompt_tokens_details", "cached_tokens"),
                           ("output_tokens_details", "reasoning_tokens"), ("completion_tokens_details", "reasoning_tokens")):
        details = usage.get(source)
        if isinstance(details, dict):
            values[target] = details.get(target)
    result = {key: value for key, value in values.items() if type(value) is int and value >= 0}
    if "total_tokens" not in result and "input_tokens" in result and "output_tokens" in result:
        result["total_tokens"] = result["input_tokens"] + result["output_tokens"]
    return result


def interpret_response(protocol: str, http_status: int, raw: bytes) -> tuple[str, str, dict]:
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        status, reason = error_category(http_status, None) if not 200 <= http_status < 300 else ("failure", "invalid_json")
        return status, reason, {}
    if not isinstance(payload, dict):
        return "failure", "invalid_response", {}
    usage = safe_usage(payload)
    if not 200 <= http_status < 300 or payload.get("error"):
        return (*error_category(http_status, payload), usage)
    try:
        if protocol == "responses":
            if payload.get("status") != "completed" or payload.get("incomplete_details"):
                return "failure", "incomplete_response", usage
            texts = [part.get("text", "") for item in payload.get("output", []) if item.get("type") == "message"
                     for part in item.get("content", []) if part.get("type") == "output_text"]
        elif protocol == "messages":
            if payload.get("type") != "message" or payload.get("role") != "assistant":
                return "failure", "invalid_response", usage
            texts = [part.get("text", "") for part in payload.get("content", []) if part.get("type") == "text"]
        else:
            choices = payload.get("choices", [])
            message = choices[0]["message"] if choices else {}
            if message.get("role") != "assistant":
                return "failure", "invalid_response", usage
            content = message.get("content", "")
            texts = [content] if isinstance(content, str) else [part.get("text", "") for part in content if part.get("type") in ("text", "output_text")]
        if any(isinstance(text, str) and text.strip() for text in texts):
            return "success", "ok", usage
        return "failure", "empty_response", usage
    except (AttributeError, KeyError, IndexError, TypeError):
        return "failure", "invalid_response", usage


def probe(config: dict, model: dict, transport=http_post, now=None) -> dict:
    checked_at = timestamp(now or dt.datetime.now(UTC))
    result = {"model": model["id"], "checked_at": checked_at, "status": "unknown",
              "reason": "monitor_not_configured", "latency_ms": None, "http_status": None, "usage": {}}
    key = os.environ.get(model.get("api_key_env", config["api_key_env"]), "").strip()
    if not key:
        return result
    started = time.monotonic()
    try:
        url, headers, body = request_spec(config, model, key)
        http_status, raw = transport(url, headers, body, config["timeout_seconds"])
        result["http_status"] = http_status
        result["status"], result["reason"], result["usage"] = interpret_response(model["protocol"], http_status, raw)
    except (TimeoutError, socket.timeout):
        result.update(status="failure", reason="timeout")
    except ResponseTooLarge:
        result.update(status="failure", reason="response_too_large")
    except (OSError, http.client.HTTPException):
        result.update(status="failure", reason="network_error")
    except Exception:
        # An unexpected local error must not be mislabeled as an upstream outage.
        result.update(status="unknown", reason="monitor_error")
    result["latency_ms"] = round((time.monotonic() - started) * 1000)
    return result


def run_probes(config: dict, model_ids: list[str] | None = None, transport=http_post) -> list[dict]:
    models = config["models"]
    if model_ids:
        unknown = set(model_ids) - {model["id"] for model in models}
        if unknown:
            raise ValueError("Requested model does not exist in config")
        models = [model for model in models if model["id"] in model_ids]
    if not any(os.environ.get(model.get("api_key_env", config["api_key_env"]), "").strip() for model in models):
        raise ValueError("API key is not configured; no probes were made and history was not changed")
    with concurrent.futures.ThreadPoolExecutor(max_workers=config["concurrency"]) as executor:
        return list(executor.map(lambda model: probe(config, model, transport), models))


def clean_record(record: dict) -> dict:
    """Allowlist the public schema, including when rebuilding from stored records."""
    model = record["model"]
    if not isinstance(model, str) or not re.fullmatch(r"[\w./:-]{1,150}", model, flags=re.ASCII):
        raise ValueError("Invalid model in history")
    checked_at = timestamp(parse_time(record["checked_at"]))
    status, reason = record["status"], record["reason"]
    if status not in STATUSES or reason not in REASONS:
        raise ValueError("Invalid status or reason in history")
    latency = record.get("latency_ms")
    http_status = record.get("http_status")
    if latency is not None and (type(latency) is not int or latency < 0):
        raise ValueError("Invalid latency in history")
    if http_status is not None and (type(http_status) is not int or not 100 <= http_status <= 599):
        raise ValueError("Invalid HTTP status in history")
    usage = record.get("usage", {})
    return {"model": model, "checked_at": checked_at, "status": status, "reason": reason,
            "latency_ms": latency, "http_status": http_status,
            "usage": {key: value for key, value in usage.items() if key in TOKEN_KEYS and type(value) is int and value >= 0}}


def daily_summary(date: str, records: list[dict]) -> dict:
    models = {}
    for record in records:
        counts = models.setdefault(record["model"], {"success": 0, "failure": 0, "account_restricted": 0, "unknown": 0,
            "latency_sum_ms": 0, "latency_count": 0, "usage": {}})
        counts[record["status"]] += 1
        if record["status"] == "success" and record["latency_ms"] is not None:
            counts["latency_sum_ms"] += record["latency_ms"]
            counts["latency_count"] += 1
        for key, value in record["usage"].items():
            counts["usage"][key] = counts["usage"].get(key, 0) + value
    return {"schema_version": 1, "date": date, "models": models}


def save_results(data_dir: Path, records: list[dict], retention_days: int, now=None) -> None:
    now = now or dt.datetime.now(UTC)
    records = [clean_record(record) for record in records]
    latest = {key: clean_record(value) for key, value in read_json(data_dir / "latest.json", {}).items()}
    meta = read_json(data_dir / "meta.json", {})
    for date in sorted({record["checked_at"][:10] for record in records}):
        path = data_dir / "history" / f"{date}.json"
        existing = [clean_record(record) for record in read_json(path, {"checks": []})["checks"]]
        by_key = {(record["model"], record["checked_at"]): record for record in existing}
        by_key.update({(record["model"], record["checked_at"]): record for record in records if record["checked_at"].startswith(date)})
        combined = sorted(by_key.values(), key=lambda record: (record["checked_at"], record["model"]))
        write_json(path, {"schema_version": 1, "date": date, "checks": combined})
        write_json(data_dir / "summaries" / f"{date}.json", daily_summary(date, combined))
    for record in records:
        if record["model"] not in latest or record["checked_at"] >= latest[record["model"]]["checked_at"]:
            latest[record["model"]] = record
        starts = meta.setdefault("model_started_at", {})
        starts[record["model"]] = min(starts.get(record["model"], record["checked_at"]), record["checked_at"])
    if records:
        earliest = min(record["checked_at"] for record in records)
        meta["monitor_started_at"] = min(meta.get("monitor_started_at", earliest), earliest)
        meta["last_run_at"] = max(meta.get("last_run_at", earliest), max(record["checked_at"] for record in records))
    write_json(data_dir / "latest.json", latest)
    write_json(data_dir / "meta.json", meta)
    cutoff = (now.astimezone(UTC).date() - dt.timedelta(days=retention_days - 1)).isoformat()
    for path in sorted((data_dir / "history").glob("*.json")):
        if path.stem < cutoff:
            old = [clean_record(record) for record in read_json(path)["checks"]]
            write_json(data_dir / "summaries" / path.name, daily_summary(path.stem, old))
            path.unlink()


def window_stats(records: list[dict], now: dt.datetime, hours: int, interval_minutes: int, started_at: str | None) -> dict:
    since = now - dt.timedelta(hours=hours)
    checks = [record for record in records if since <= parse_time(record["checked_at"]) <= now and record["status"] != "unknown"]
    successes = sum(record["status"] == "success" for record in checks)
    latencies = sorted(record["latency_ms"] for record in checks if record["status"] == "success" and record["latency_ms"] is not None)
    effective_since = max(since, parse_time(started_at)) if started_at else now
    seconds = interval_minutes * 60
    expected = max(0, math.floor(now.timestamp() / seconds) - math.floor(effective_since.timestamp() / seconds) + 1) if started_at else 0
    slots = {math.floor(parse_time(record["checked_at"]).timestamp() / seconds) for record in checks}
    return {"attempts": len(checks), "successes": successes,
            "success_rate": round(successes / len(checks) * 100, 2) if checks else None,
            "coverage": round(min(1, len(slots) / expected) * 100, 2) if expected else None,
            "expected_samples": expected,
            "p50_ms": latencies[(len(latencies) - 1) // 2] if latencies else None,
            "p95_ms": latencies[max(0, math.ceil(len(latencies) * .95) - 1)] if latencies else None}
