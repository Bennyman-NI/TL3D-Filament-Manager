from __future__ import annotations

import argparse
import ast
import json
import os
import re
import socket
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_PRINTER_URL = os.environ.get("TL3D_PRINTER_URL", "http://localhost:7125")
DEFAULT_MATCHER_URL = "http://localhost:8123/api/rfid/match"
DEFAULT_POLL_SECONDS = 2.0
DEFAULT_DUPLICATE_COOLDOWN_SECONDS = 10.0
DEFAULT_TIMEOUT_SECONDS = 10.0

KLIPPY_LOG_PATH = "/server/files/klippy.log"
PRINTER_COMMAND_PATH = "/printer/gcode/script"
RFID_LINE_RE = re.compile(r"\[print_task_config\]\s+rfid info:\s+Bambu\s+(.+?)\s+({.*})\s*$")


class Pax12BridgeError(Exception):
    """Base exception for PAX12 bridge failures."""


class Pax12BridgeNetworkError(Pax12BridgeError):
    """Raised when Moonraker or the RFID matcher cannot be reached."""


@dataclass(frozen=True)
class Pax12RfidEvent:
    manufacturer: str
    material: str
    variant: str
    colors: tuple[str, ...]
    nums: int | None = None
    alpha: int | None = None
    mode: int | None = None

    def to_matcher_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "manufacturer": self.manufacturer,
            "material": self.material,
            "variant": self.variant,
            "colors": list(self.colors),
        }
        if self.nums is not None:
            payload["nums"] = self.nums
        if self.alpha is not None:
            payload["alpha"] = self.alpha
        if self.mode is not None:
            payload["mode"] = self.mode
        return payload

    def duplicate_key(self) -> tuple[Any, ...]:
        return (self.manufacturer, self.material, self.variant, self.colors, self.nums, self.alpha, self.mode)


class MoonrakerClient:
    def __init__(self, printer_url: str = DEFAULT_PRINTER_URL, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.printer_url = printer_url.rstrip("/")
        self.timeout = timeout

    def get_klippy_log(self) -> str:
        payload = self._request("GET", KLIPPY_LOG_PATH)
        return payload.decode("utf-8", errors="replace")

    def send_console_message(self, message: str) -> None:
        command = f"M118 {_single_line(message)}"
        self._request("POST", PRINTER_COMMAND_PATH, {"script": command})

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> bytes:
        request_body = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Accept": "application/json"}
        if request_body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(f"{self.printer_url}{path}", data=request_body, method=method, headers=headers)

        try:
            with urlopen(request, timeout=self.timeout) as response:
                status = getattr(response, "status", response.getcode())
                response_body = response.read()
        except HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            exc.close()
            raise Pax12BridgeNetworkError(
                f"Moonraker returned HTTP {exc.code} {exc.reason}: {response_body}"
            ) from exc
        except (URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise Pax12BridgeNetworkError(f"Could not reach Moonraker at {self.printer_url}: {exc}") from exc

        if status < 200 or status >= 300:
            raise Pax12BridgeNetworkError(f"Moonraker returned HTTP {status}: {response_body!r}")
        return response_body


class RfidMatcherHttpClient:
    def __init__(self, matcher_url: str = DEFAULT_MATCHER_URL, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.matcher_url = matcher_url
        self.timeout = timeout

    def match(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_body = json.dumps(payload).encode("utf-8")
        request = Request(
            self.matcher_url,
            data=request_body,
            method="POST",
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                status = getattr(response, "status", response.getcode())
                response_body = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            exc.close()
            raise Pax12BridgeNetworkError(
                f"RFID matcher returned HTTP {exc.code} {exc.reason}: {response_body}"
            ) from exc
        except (URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise Pax12BridgeNetworkError(f"Could not reach RFID matcher at {self.matcher_url}: {exc}") from exc

        if status < 200 or status >= 300:
            raise Pax12BridgeNetworkError(f"RFID matcher returned HTTP {status}: {response_body}")

        try:
            payload = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise Pax12BridgeNetworkError(f"RFID matcher returned invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise Pax12BridgeNetworkError("RFID matcher returned a non-object JSON response.")
        return payload


class Pax12Bridge:
    def __init__(
        self,
        moonraker: MoonrakerClient,
        matcher: RfidMatcherHttpClient,
        *,
        sleep: Callable[[float], None] = time.sleep,
        time_source: Callable[[], float] = time.monotonic,
        duplicate_cooldown_seconds: float = DEFAULT_DUPLICATE_COOLDOWN_SECONDS,
    ) -> None:
        self.moonraker = moonraker
        self.matcher = matcher
        self.sleep = sleep
        self.time_source = time_source
        self.duplicate_cooldown_seconds = duplicate_cooldown_seconds
        self._log_offset = 0
        self._last_event_key: tuple[Any, ...] | None = None
        self._last_event_time: float | None = None
        self._initialized = False

    def initialize_log_offset(self) -> None:
        self._log_offset = len(self.moonraker.get_klippy_log())
        self._initialized = True

    def poll_once(self) -> int:
        log_content = self.moonraker.get_klippy_log()
        if len(log_content) < self._log_offset:
            self._log_offset = 0

        new_content = log_content[self._log_offset :]
        self._log_offset = len(log_content)
        return self.process_log_content(new_content)

    def process_log_content(self, content: str) -> int:
        processed = 0
        for line in content.splitlines():
            event = parse_pax12_rfid_line(line)
            if event is None:
                continue

            now = self.time_source()
            if self._is_immediate_duplicate(event, now):
                continue

            match_result = self.matcher.match(event.to_matcher_payload())
            if match_result.get("matched") is True:
                for message in build_console_messages(match_result):
                    self.moonraker.send_console_message(message)

            self._last_event_key = event.duplicate_key()
            self._last_event_time = now
            processed += 1
        return processed

    def run_forever(self, *, poll_seconds: float = DEFAULT_POLL_SECONDS) -> None:
        while True:
            try:
                if self._initialized:
                    self.poll_once()
                else:
                    self.initialize_log_offset()
            except Pax12BridgeNetworkError as exc:
                print(f"PAX12 bridge network error; retrying: {exc}")
            self.sleep(poll_seconds)

    def _is_immediate_duplicate(self, event: Pax12RfidEvent, now: float) -> bool:
        if self._last_event_key != event.duplicate_key() or self._last_event_time is None:
            return False
        return now - self._last_event_time < self.duplicate_cooldown_seconds


def parse_pax12_rfid_line(line: str) -> Pax12RfidEvent | None:
    match = RFID_LINE_RE.search(line)
    if match is None:
        return None

    descriptor = match.group(1).strip()
    parts = descriptor.split(maxsplit=1)
    if len(parts) != 2:
        return None
    material, variant = parts

    try:
        rfid_info = ast.literal_eval(match.group(2))
    except (SyntaxError, ValueError):
        return None
    if not isinstance(rfid_info, dict):
        return None

    colors_value = rfid_info.get("colors")
    if not isinstance(colors_value, list) or not all(isinstance(item, str) for item in colors_value):
        return None

    return Pax12RfidEvent(
        manufacturer="Bambu Lab",
        material=material,
        variant=variant,
        colors=tuple(colors_value),
        nums=_optional_int(rfid_info.get("nums")),
        alpha=_optional_int(rfid_info.get("alpha")),
        mode=_optional_int(rfid_info.get("mode")),
    )


def build_console_messages(match_result: dict[str, Any]) -> list[str]:
    filament_name = str(match_result.get("filament_name") or "Unknown filament")
    spools = match_result.get("spools")
    if not isinstance(spools, list) or not spools:
        return [f"TL3D RFID: {filament_name} | remaining unknown | location unknown"]

    messages: list[str] = []
    for spool in spools:
        if not isinstance(spool, dict):
            continue
        remaining = _format_remaining_weight(spool.get("remaining_weight"))
        location = str(spool.get("location") or "unknown")
        messages.append(f"TL3D RFID: {filament_name} | remaining {remaining} | location {location}")
    return messages or [f"TL3D RFID: {filament_name} | remaining unknown | location unknown"]


def run_bridge(
    *,
    printer_url: str = DEFAULT_PRINTER_URL,
    matcher_url: str = DEFAULT_MATCHER_URL,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    duplicate_cooldown_seconds: float = DEFAULT_DUPLICATE_COOLDOWN_SECONDS,
) -> None:
    bridge = Pax12Bridge(
        MoonrakerClient(printer_url),
        RfidMatcherHttpClient(matcher_url),
        duplicate_cooldown_seconds=duplicate_cooldown_seconds,
    )
    bridge.run_forever(poll_seconds=poll_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bridge PAX12 RFID klippy log lines to TL3D RFID matching.")
    parser.add_argument("--printer-url", default=DEFAULT_PRINTER_URL, help="Moonraker printer URL.")
    parser.add_argument("--matcher-url", default=DEFAULT_MATCHER_URL, help="Local RFID matcher endpoint URL.")
    parser.add_argument("--poll-seconds", default=DEFAULT_POLL_SECONDS, type=float, help="Polling interval.")
    parser.add_argument(
        "--duplicate-cooldown-seconds",
        default=DEFAULT_DUPLICATE_COOLDOWN_SECONDS,
        type=float,
        help="Seconds before accepting the same RFID event again.",
    )
    args = parser.parse_args(argv)

    run_bridge(
        printer_url=args.printer_url,
        matcher_url=args.matcher_url,
        poll_seconds=args.poll_seconds,
        duplicate_cooldown_seconds=args.duplicate_cooldown_seconds,
    )
    return 0


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _format_remaining_weight(value: Any) -> str:
    try:
        weight = float(value)
    except (TypeError, ValueError):
        return "unknown"
    return f"{weight:g}g"


def _single_line(value: str) -> str:
    return " ".join(value.split())


if __name__ == "__main__":
    raise SystemExit(main())
