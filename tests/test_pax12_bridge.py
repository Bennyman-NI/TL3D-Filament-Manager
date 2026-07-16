from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from app.pax12_bridge import (
    DEFAULT_MATCHER_URL,
    KLIPPY_LOG_PATH,
    PRINTER_COMMAND_PATH,
    MoonrakerClient,
    Pax12Bridge,
    Pax12BridgeNetworkError,
    RfidMatcherHttpClient,
    build_console_messages,
    parse_pax12_rfid_line,
)


PAX12_LINE = (
    "[print_task_config] rfid info: Bambu PLA Basic "
    "{'nums': 1, 'alpha': 255, 'mode': 0, 'colors': ['0A2989']}"
)
PAX12_WHITE_LINE = (
    "[print_task_config] rfid info: Bambu PLA Basic "
    "{'nums': 1, 'alpha': 255, 'mode': 0, 'colors': ['FFFFFF']}"
)


class FakeMoonraker:
    def __init__(self, logs: list[str] | None = None) -> None:
        self.logs = logs or []
        self.sent_messages: list[str] = []
        self.log_calls = 0

    def get_klippy_log(self) -> str:
        self.log_calls += 1
        if not self.logs:
            return ""
        if len(self.logs) == 1:
            return self.logs[0]
        return self.logs.pop(0)

    def send_console_message(self, message: str) -> None:
        self.sent_messages.append(message)


class FlakyMoonraker(FakeMoonraker):
    def get_klippy_log(self) -> str:
        self.log_calls += 1
        if self.log_calls == 1:
            raise Pax12BridgeNetworkError("Moonraker unavailable")
        if len(self.logs) == 1:
            return self.logs[0]
        return self.logs.pop(0)


class MutableClock:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def now(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class FakeMatcher:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.payloads: list[dict[str, object]] = []

    def match(self, payload: dict[str, object]) -> dict[str, object]:
        self.payloads.append(payload)
        return self.response


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self.status = status

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def getcode(self) -> int:
        return self.status

    def read(self) -> bytes:
        return self._body


class Pax12BridgeTests(unittest.TestCase):
    def test_parse_representative_pax12_log_line(self) -> None:
        event = parse_pax12_rfid_line(PAX12_LINE)

        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.manufacturer, "Bambu Lab")
        self.assertEqual(event.material, "PLA")
        self.assertEqual(event.variant, "Basic")
        self.assertEqual(event.colors, ("0A2989",))
        self.assertEqual(event.nums, 1)
        self.assertEqual(event.alpha, 255)
        self.assertEqual(event.mode, 0)
        self.assertEqual(
            event.to_matcher_payload(),
            {
                "manufacturer": "Bambu Lab",
                "material": "PLA",
                "variant": "Basic",
                "colors": ["0A2989"],
                "nums": 1,
                "alpha": 255,
                "mode": 0,
            },
        )

    def test_ignores_non_matching_or_invalid_lines(self) -> None:
        self.assertIsNone(parse_pax12_rfid_line("ordinary klippy log line"))
        self.assertIsNone(parse_pax12_rfid_line("[print_task_config] rfid info: Bambu PLA {'colors': ['0A2989']}"))
        self.assertIsNone(
            parse_pax12_rfid_line("[print_task_config] rfid info: Bambu PLA Basic {'colors': '0A2989'}")
        )

    def test_processes_only_new_log_content_and_suppresses_duplicate_rfid_lines(self) -> None:
        first_log = f"noise\n{PAX12_LINE}\n"
        second_log = f"{first_log}{PAX12_LINE}\n"
        moonraker = FakeMoonraker([first_log, second_log])
        matcher = FakeMatcher(_matched_response())
        bridge = Pax12Bridge(moonraker, matcher)

        self.assertEqual(bridge.poll_once(), 1)
        self.assertEqual(bridge.poll_once(), 0)

        self.assertEqual(len(matcher.payloads), 1)
        self.assertEqual(len(moonraker.sent_messages), 1)

    def test_historical_rfid_lines_are_ignored_on_startup(self) -> None:
        historical_log = f"startup noise\n{PAX12_LINE}\n"
        appended_log = f"{historical_log}{PAX12_WHITE_LINE}\n"
        moonraker = FakeMoonraker([historical_log, appended_log])
        matcher = FakeMatcher(_matched_response())
        bridge = Pax12Bridge(moonraker, matcher)

        bridge.initialize_log_offset()
        processed = bridge.poll_once()

        self.assertEqual(processed, 1)
        self.assertEqual(len(matcher.payloads), 1)
        self.assertEqual(matcher.payloads[0]["colors"], ["FFFFFF"])

    def test_immediate_duplicate_lines_are_suppressed(self) -> None:
        clock = MutableClock()
        moonraker = FakeMoonraker()
        matcher = FakeMatcher(_matched_response())
        bridge = Pax12Bridge(moonraker, matcher, time_source=clock.now)

        processed = bridge.process_log_content(f"{PAX12_LINE}\n{PAX12_LINE}\n")

        self.assertEqual(processed, 1)
        self.assertEqual(len(matcher.payloads), 1)

    def test_same_basic_blue_event_is_accepted_again_after_cooldown(self) -> None:
        clock = MutableClock()
        moonraker = FakeMoonraker()
        matcher = FakeMatcher(_matched_response())
        bridge = Pax12Bridge(moonraker, matcher, time_source=clock.now, duplicate_cooldown_seconds=10)

        self.assertEqual(bridge.process_log_content(f"{PAX12_LINE}\n"), 1)
        clock.advance(10)
        self.assertEqual(bridge.process_log_content(f"{PAX12_LINE}\n"), 1)

        self.assertEqual(len(matcher.payloads), 2)
        self.assertEqual(matcher.payloads[0]["colors"], ["0A2989"])
        self.assertEqual(matcher.payloads[1]["colors"], ["0A2989"])

    def test_basic_blue_is_accepted_again_immediately_after_different_colour_event(self) -> None:
        clock = MutableClock()
        moonraker = FakeMoonraker()
        matcher = FakeMatcher(_matched_response())
        bridge = Pax12Bridge(moonraker, matcher, time_source=clock.now, duplicate_cooldown_seconds=10)

        processed = bridge.process_log_content(f"{PAX12_LINE}\n{PAX12_WHITE_LINE}\n{PAX12_LINE}\n")

        self.assertEqual(processed, 3)
        self.assertEqual(
            [payload["colors"] for payload in matcher.payloads],
            [["0A2989"], ["FFFFFF"], ["0A2989"]],
        )

    def test_matched_event_sends_console_message_with_filament_weight_and_location(self) -> None:
        moonraker = FakeMoonraker([f"{PAX12_LINE}\n"])
        matcher = FakeMatcher(_matched_response())
        bridge = Pax12Bridge(moonraker, matcher)

        processed = bridge.poll_once()

        self.assertEqual(processed, 1)
        self.assertEqual(
            matcher.payloads,
            [
                {
                    "manufacturer": "Bambu Lab",
                    "material": "PLA",
                    "variant": "Basic",
                    "colors": ["0A2989"],
                    "nums": 1,
                    "alpha": 255,
                    "mode": 0,
                }
            ],
        )
        self.assertEqual(moonraker.sent_messages, ["TL3D RFID: Basic Blue (10601) | remaining 812.4g | location AMS 1"])

    def test_ambiguous_match_does_not_send_console_message(self) -> None:
        moonraker = FakeMoonraker([f"{PAX12_LINE}\n"])
        matcher = FakeMatcher({"matched": False, "status": "ambiguous", "candidates": [{"filament_id": 23}]})
        bridge = Pax12Bridge(moonraker, matcher)

        self.assertEqual(bridge.poll_once(), 1)
        self.assertEqual(moonraker.sent_messages, [])

    def test_log_truncation_resets_offset_for_reconnect_or_rotation(self) -> None:
        first_log = f"older noise\n{PAX12_LINE}\n"
        second_log = "[print_task_config] rfid info: Bambu PLA Matte {'colors': ['FFFFFF']}\n"
        moonraker = FakeMoonraker([first_log, second_log])
        matcher = FakeMatcher(_matched_response())
        bridge = Pax12Bridge(moonraker, matcher)

        self.assertEqual(bridge.poll_once(), 1)
        self.assertEqual(bridge.poll_once(), 1)

        self.assertEqual(matcher.payloads[1]["variant"], "Matte")

    def test_run_forever_reconnects_after_network_failure(self) -> None:
        historical_log = f"historical\n{PAX12_LINE}\n"
        appended_log = f"{historical_log}{PAX12_WHITE_LINE}\n"
        moonraker = FlakyMoonraker([historical_log, appended_log])
        matcher = FakeMatcher(_matched_response())
        sleep_calls: list[float] = []

        def stop_after_third_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)
            if len(sleep_calls) == 3:
                raise StopIteration

        bridge = Pax12Bridge(moonraker, matcher, sleep=stop_after_third_sleep)

        with patch("app.pax12_bridge.print"):
            with self.assertRaises(StopIteration):
                bridge.run_forever(poll_seconds=0.01)

        self.assertEqual(moonraker.log_calls, 3)
        self.assertEqual(len(matcher.payloads), 1)
        self.assertEqual(matcher.payloads[0]["colors"], ["FFFFFF"])
        self.assertEqual(sleep_calls, [0.01, 0.01, 0.01])

    def test_builds_one_console_message_per_matching_spool(self) -> None:
        messages = build_console_messages(
            {
                "matched": True,
                "filament_name": "Basic Blue (10601)",
                "spools": [
                    {"spool_id": 1, "remaining_weight": 812.4, "location": "AMS 1"},
                    {"spool_id": 2, "remaining_weight": 500, "location": None},
                ],
            }
        )

        self.assertEqual(
            messages,
            [
                "TL3D RFID: Basic Blue (10601) | remaining 812.4g | location AMS 1",
                "TL3D RFID: Basic Blue (10601) | remaining 500g | location unknown",
            ],
        )

    def test_moonraker_client_fetches_klippy_log_and_sends_m118_command(self) -> None:
        requests: list[object] = []

        def fake_urlopen(request: object, timeout: float) -> FakeResponse:
            requests.append(request)
            return FakeResponse(b"klippy log")

        with patch("app.pax12_bridge.urlopen", side_effect=fake_urlopen):
            client = MoonrakerClient("http://printer.local", timeout=3)
            self.assertEqual(client.get_klippy_log(), "klippy log")
            client.send_console_message("Hello\nRFID")

        get_request = requests[0]
        post_request = requests[1]
        self.assertEqual(get_request.full_url, f"http://printer.local{KLIPPY_LOG_PATH}")
        self.assertEqual(get_request.get_method(), "GET")
        self.assertEqual(post_request.full_url, f"http://printer.local{PRINTER_COMMAND_PATH}")
        self.assertEqual(post_request.get_method(), "POST")
        self.assertEqual(json.loads(post_request.data.decode("utf-8")), {"script": "M118 Hello RFID"})

    def test_matcher_http_client_posts_to_configured_matcher_url(self) -> None:
        requests: list[object] = []

        def fake_urlopen(request: object, timeout: float) -> FakeResponse:
            requests.append(request)
            return FakeResponse(json.dumps(_matched_response()).encode("utf-8"))

        with patch("app.pax12_bridge.urlopen", side_effect=fake_urlopen):
            result = RfidMatcherHttpClient(DEFAULT_MATCHER_URL, timeout=4).match({"colors": ["0A2989"]})

        request = requests[0]
        self.assertTrue(result["matched"])
        self.assertEqual(request.full_url, DEFAULT_MATCHER_URL)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data.decode("utf-8")), {"colors": ["0A2989"]})


def _matched_response() -> dict[str, object]:
    return {
        "matched": True,
        "status": "matched",
        "filament_id": 23,
        "filament_name": "Basic Blue (10601)",
        "vendor": "Bambu Lab",
        "material": "PLA",
        "color_hex": "0A2989",
        "spools": [{"spool_id": 101, "remaining_weight": 812.4, "location": "AMS 1"}],
    }


if __name__ == "__main__":
    unittest.main()
