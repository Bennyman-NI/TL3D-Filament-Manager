from __future__ import annotations

import argparse
import queue
import sys
from dataclasses import dataclass
from typing import Any, Callable, Iterable


DEFAULT_READER_NAME = "ACR1255U-J1"
GET_UID_APDU = [0xFF, 0xCA, 0x00, 0x00, 0x00]


@dataclass(frozen=True)
class PcscApi:
    card_connection: Any
    card_monitor: Callable[[], Any]
    card_connection_exception: type[Exception]
    no_card_exception: type[Exception]
    no_readers_exception: type[Exception]
    readers: Callable[[], Iterable[object]]


@dataclass(frozen=True)
class TagIdentity:
    reader_name: str
    atr: str
    uid: str | None
    uid_error: str | None = None

    @property
    def repeat_key(self) -> tuple[str, str | None, str]:
        return (self.reader_name, self.uid, self.atr)


class CardEventObserver:
    def __init__(self, events: "queue.Queue[tuple[str, object]]") -> None:
        self.events = events

    def update(self, observable: object, actions: tuple[list[object], list[object]]) -> None:
        added_cards, removed_cards = actions
        for card in added_cards:
            self.events.put(("added", card))
        for card in removed_cards:
            self.events.put(("removed", card))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        pcsc = load_pcsc_api()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    available_readers = list_pcsc_readers(pcsc)
    print_readers(available_readers)

    try:
        selected_reader = select_reader(
            available_readers,
            reader_name=args.reader_name,
            any_reader=args.any_reader,
        )
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print()
    print(f"Selected reader: {selected_reader}")
    print("Waiting for a tag. Press Ctrl+C to stop.")

    return monitor_tags(selected_reader, pcsc)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only ACR1255U-J1 PC/SC tag identifier for TL3D RFID exploration."
    )
    parser.add_argument(
        "--reader-name",
        default=DEFAULT_READER_NAME,
        help=f"Reader name substring to select. Default: {DEFAULT_READER_NAME}",
    )
    parser.add_argument(
        "--any-reader",
        action="store_true",
        help="Use the first PC/SC reader instead of requiring an ACR1255U-J1 match.",
    )
    return parser.parse_args(argv)


def load_pcsc_api() -> PcscApi:
    try:
        from smartcard.CardConnection import CardConnection
        from smartcard.CardMonitoring import CardMonitor
        from smartcard.Exceptions import CardConnectionException, NoCardException, NoReadersException
        from smartcard.System import readers
    except ImportError as exc:  # pragma: no cover - depends on local environment
        raise RuntimeError(
            "Missing dependency: pyscard. Install with "
            "`python -m pip install -r tools/bambu_rfid_identifier/requirements.txt`."
        ) from exc

    return PcscApi(
        card_connection=CardConnection,
        card_monitor=CardMonitor,
        card_connection_exception=CardConnectionException,
        no_card_exception=NoCardException,
        no_readers_exception=NoReadersException,
        readers=readers,
    )


def list_pcsc_readers(pcsc: PcscApi) -> list[object]:
    try:
        return list(pcsc.readers())
    except pcsc.no_readers_exception:
        return []


def print_readers(available_readers: Iterable[object]) -> None:
    reader_list = list(available_readers)
    print("Available PC/SC readers:")
    if not reader_list:
        print("  none")
        return
    for index, reader in enumerate(reader_list, start=1):
        print(f"  {index}. {reader}")


def select_reader(available_readers: list[object], *, reader_name: str, any_reader: bool) -> object:
    if not available_readers:
        raise RuntimeError("No PC/SC readers were found. Check the reader connection, driver, and Windows Smart Card service.")

    if any_reader:
        return available_readers[0]

    expected = reader_name.casefold()
    for reader in available_readers:
        if expected in str(reader).casefold():
            return reader

    raise RuntimeError(
        f"No reader name contained '{reader_name}'. "
        "Connect the ACS ACR1255U-J1 or rerun with --reader-name using one of the displayed reader names."
    )


def monitor_tags(selected_reader: object, pcsc: PcscApi) -> int:
    try:
        card_monitor = pcsc.card_monitor()
    except Exception as exc:
        print(f"ERROR: Could not start PC/SC card monitor: {exc}", file=sys.stderr)
        return 3

    events: "queue.Queue[tuple[str, object]]" = queue.Queue()
    observer = CardEventObserver(events)
    last_present_key: tuple[str, str | None, str] | None = None

    try:
        card_monitor.addObserver(observer)
    except Exception as exc:
        print(f"ERROR: Could not subscribe to PC/SC card events: {exc}", file=sys.stderr)
        return 3

    try:
        while True:
            event_type, card = events.get()
            card_reader_name = str(getattr(card, "reader", ""))
            if card_reader_name != str(selected_reader):
                continue

            if event_type == "removed":
                print(f"Tag removed from {card_reader_name}.")
                last_present_key = None
                continue

            identity = identify_card(card, pcsc)
            if identity.repeat_key == last_present_key:
                continue

            print_tag_identity(identity)
            last_present_key = identity.repeat_key
    except KeyboardInterrupt:
        print()
        print("Stopped.")
        return 0
    finally:
        card_monitor.deleteObserver(observer)


def identify_card(card: object, pcsc: PcscApi) -> TagIdentity:
    reader_name = str(getattr(card, "reader", "unknown reader"))
    atr = bytes_to_hex(getattr(card, "atr", []))

    try:
        connection = card.createConnection()
    except AttributeError:
        return TagIdentity(reader_name=reader_name, atr=atr, uid=None, uid_error="Unsupported card object from pyscard.")

    try:
        connection.connect(pcsc.card_connection.T1_protocol)
    except (pcsc.card_connection_exception, pcsc.no_card_exception):
        try:
            connection.connect()
        except (pcsc.card_connection_exception, pcsc.no_card_exception) as exc:
            return TagIdentity(reader_name=reader_name, atr=atr, uid=None, uid_error=f"Could not connect to tag: {exc}")

    try:
        data, sw1, sw2 = connection.transmit(GET_UID_APDU)
    except (pcsc.card_connection_exception, pcsc.no_card_exception) as exc:
        disconnect_quietly(connection)
        return TagIdentity(reader_name=reader_name, atr=atr, uid=None, uid_error=f"UID command failed: {exc}")
    finally:
        disconnect_quietly(connection)

    if (sw1, sw2) != (0x90, 0x00):
        return TagIdentity(
            reader_name=reader_name,
            atr=atr,
            uid=None,
            uid_error=f"UID command unsupported or rejected. Status: {sw1:02X} {sw2:02X}",
        )

    if not data:
        return TagIdentity(reader_name=reader_name, atr=atr, uid=None, uid_error="UID command returned no data.")

    return TagIdentity(reader_name=reader_name, atr=atr, uid=bytes_to_hex(data))


def disconnect_quietly(connection: object) -> None:
    try:
        connection.disconnect()
    except Exception:
        return


def print_tag_identity(identity: TagIdentity) -> None:
    print()
    print(f"Tag detected on {identity.reader_name}")
    print(f"  ATR: {identity.atr or 'unavailable'}")
    if identity.uid is not None:
        print(f"  UID: {identity.uid}")
    else:
        print(f"  UID: unavailable ({identity.uid_error})")


def bytes_to_hex(values: Iterable[int]) -> str:
    return "".join(f"{int(value):02X}" for value in values)


if __name__ == "__main__":
    raise SystemExit(main())
