"""Observe only the statically traced service -> local-driver settings registry.

Fixed audited offsets, loopback ADB, bounded reads, no calls, hooks or writes.
No arbitrary heap search, account strings, network queries, or UI operations.
The snapshot is non-atomic; a changed ownership chain is rejected.
"""
import argparse
import hashlib
import json
import struct
import subprocess
from pathlib import Path

AUDITED_SHA = "c6b2482a2f1fbd2e15c99df7fb18ba3d5596b77b3a81930d3638241a3c37fe55"
SERIAL = "unbound-select-configured-instance"
SERVICE_ROOT_VA = 0x1d34ae0
REGISTRY_OFFSET = 0x3c8
MASK = 0x00ffffffffffffff
REGISTRY_TABLE_VA = 0x1c04c18
SETTINGS_TABLE_VA = 0x1c0ccb8
REGISTRY_SLOTS = {0x20: 0x1049b18, 0x30: 0x104af90,
                  0x38: 0x104afa0, 0x40: 0x104b2f8}
ROW_LIMIT = 64


def validate_identity(identity):
    if identity.get("serial") != SERIAL or identity.get("library_sha256") != AUDITED_SHA:
        raise ValueError("only the audited local emulator and build are supported")
    pid = identity.get("pid")
    if type(pid) is not int or not 0 < pid < 1 << 22:
        raise ValueError("invalid process identity")
    base = int(identity["base"], 0)
    end = int(identity["executable_end"], 0)
    if base <= 0 or base % 4096 or end - base != 0x1b3d000:
        raise ValueError("unexpected library mapping")
    anchors = identity.get("jni_exports", [])
    if not anchors or any(not 0 < item["size"] <= 0x1000
                          or not base <= base + int(item["va"], 0)
                          < base + int(item["va"], 0) + item["size"] <= end
                          for item in anchors):
        raise ValueError("missing or excessive identity anchors")
    return base, end


def checked_range(address, size, mappings, used=0):
    address &= MASK
    if type(size) is not int or not 0 < size <= 0x1000 or used + size > 0x10000:
        raise ValueError("read exceeds per-read or total budget")
    # A single object can straddle adjacent readable VMAs (e.g. two Scudo
    # allocations). Require coverage of every byte, not one containing VMA.
    covered = address
    for low, high, mode in sorted(mappings):
        if high <= covered:
            continue
        if low > covered or "r" not in mode:
            break
        covered = high
        if covered >= address + size:
            break
    if not address or covered < address + size:
        raise ValueError("not a readable mapped range")
    return address


def validate_table_address(identity, table):
    base, end = validate_identity(identity)
    table &= MASK
    if table % 8 or not end <= table < base + 0x1c70000 - 0x48:
        raise ValueError("registry table lies outside audited class window")
    return table


def classify_table(identity, table, raw_slots):
    base, end = validate_identity(identity)
    table = validate_table_address(identity, table)
    if table - base != REGISTRY_TABLE_VA:
        raise ValueError("settings registry concrete type changed")
    slots = {}
    for slot, raw in raw_slots.items():
        if slot not in REGISTRY_SLOTS:
            raise ValueError("unsupported registry slot")
        pointer = raw & MASK
        if pointer % 4 or not base + 0x880000 <= pointer < end:
            raise ValueError("registry callback is not audited internal code")
        if pointer - base != REGISTRY_SLOTS[slot]:
            raise ValueError("settings registry callback changed")
        slots[hex(slot)] = hex(pointer - base)
    if set(raw_slots) != set(REGISTRY_SLOTS):
        raise ValueError("incomplete registry interface")
    return slots


def string_storage(header):
    """Decode only the observed 16-byte native string storage convention."""
    if len(header) != 16:
        raise ValueError("short native string header")
    length = struct.unpack_from("<i", header, 4)[0]
    if not 0 <= length <= 96:
        raise ValueError("excessive or invalid test setting name")
    if length < 8:
        return length, header[8:8 + length], None
    pointer = struct.unpack_from("<Q", header, 8)[0] & MASK
    if not pointer:
        raise ValueError("nonempty test setting name has no storage")
    return length, None, pointer


def registry_bounds(raw):
    """Registry +0x30: pointer, capacity, count, as proven by its getters."""
    if len(raw) != 16:
        raise ValueError("short settings vector header")
    pointer, capacity, count = struct.unpack("<Qii", raw)
    pointer &= MASK
    if not 0 <= count <= capacity <= 4096 or count and (not pointer or pointer % 8):
        raise ValueError("invalid or excessive settings vector")
    return pointer, count


def automatic_setting(snapshot, iteration):
    """Offline model of the inspected name-selection builder, not a game call."""
    if type(iteration) is not int or not 0 <= iteration <= 0x7fffffff:
        raise ValueError("invalid bounded iteration")
    if not snapshot.get("all_settings_observed"):
        raise ValueError("partial settings snapshots cannot determine selection")
    eligible = [row["name"] for row in snapshot["settings"]
                if row["selected_by_builder_at_0x61"]]
    return eligible[iteration % len(eligible)] if eligible else None


class ReadOnlySession:
    def __init__(self, identity):
        self.identity = identity
        self.base, self.end = validate_identity(identity)
        self.adb = ["adb", "-s", SERIAL]
        self.pid = identity["pid"]
        self.used = 0
        maps = self.verify()
        self.mappings = []
        for line in maps.splitlines():
            fields = line.split()
            low, high = (int(value, 16) for value in fields[0].split("-"))
            self.mappings.append((low, high, fields[1]))
        if self.read(self.base, 4) != b"\x7fELF":
            raise RuntimeError("library base does not contain an ELF header")
        for anchor in identity["jni_exports"]:
            data = self.read(self.base + int(anchor["va"], 0), anchor["size"])
            if hashlib.sha256(data).hexdigest() != anchor["sha256"]:
                raise RuntimeError("JNI identity anchor changed")

    def verify(self):
        stat = subprocess.check_output(
            self.adb + ["shell", f"cat /proc/{self.pid}/stat"], text=True, timeout=10)
        maps = subprocess.check_output(
            self.adb + ["shell", f"cat /proc/{self.pid}/maps"], text=True, timeout=10)
        if (stat[stat.rfind(")") + 2:].split()[19] != self.identity["process_start_time"]
                or self.identity["mapping"] not in maps.splitlines()):
            raise RuntimeError("process identity changed")
        return maps

    def read(self, address, size):
        address = checked_range(address, size, self.mappings, self.used)
        self.used += size
        offset = address % 4096
        command = (f"dd if=/proc/{self.pid}/mem bs=4096 skip={address // 4096} "
                   f"count={(offset + size + 4095) // 4096} 2>/dev/null")
        raw = subprocess.check_output(self.adb + ["exec-out", command], timeout=10)
        data = raw[offset:offset + size]
        if len(data) != size:
            raise RuntimeError("short bounded memory read")
        return data

    def pointer(self, address):
        return struct.unpack("<Q", self.read(address, 8))[0] & MASK


def observe(identity):
    session = ReadOnlySession(identity)
    root = session.pointer(session.base + SERVICE_ROOT_VA)
    services = session.pointer(root + 0x20) if root else 0
    registry = session.pointer(services + REGISTRY_OFFSET) if services else 0
    table = session.pointer(registry) if registry else 0
    if table:
        validate_table_address(identity, table)
    raw_slots = ({slot: session.pointer(table + slot) for slot in REGISTRY_SLOTS}
                 if table else {})
    slots = classify_table(identity, table, raw_slots) if table else {}
    count, observed, entries = None, 0, []
    if registry:
        # Bind the selected field reads to the actual getter encodings first.
        for va, word in ((0x1049b18, 0xb9403c00), (0x104afac, 0xf9401808),
                         (0x1040f98, 0x9100a000)):
            if session.read(session.base + va, 4) != struct.pack("<I", word):
                raise RuntimeError("settings field accessor changed")
        vector_header = session.read(registry + 0x30, 16)
        data_pointer, count = registry_bounds(vector_header)
        observed = min(count, ROW_LIMIT)
        vector_bytes = session.read(data_pointer, observed * 8) if observed else b""
        pointers = struct.unpack(f"<{observed}Q", vector_bytes)
        for index, raw_pointer in enumerate(pointers):
            entry = raw_pointer & MASK
            if not entry:
                raise RuntimeError("null settings entry in observed prefix")
            entry_table = session.pointer(entry)
            validate_table_address(identity, entry_table)
            if entry_table - session.base != SETTINGS_TABLE_VA:
                raise RuntimeError("test setting concrete type changed")
            name_header = session.read(entry + 0x28, 16)
            length, inline, pointer = string_storage(name_header)
            name_bytes = inline if inline is not None else session.read(pointer, length)
            name = name_bytes.decode("utf-8", errors="strict")
            if any(ord(char) < 32 or ord(char) == 127 for char in name):
                raise RuntimeError("unexpected control characters in test setting name")
            fields = session.read(entry + 0x60, 0x20)
            entries.append(dict(index=index, name=name, object=hex(entry),
                                vtable_va=hex(entry_table - session.base),
                                selected_by_builder_at_0x61=bool(fields[1]),
                                mode_at_0x64=struct.unpack_from("<i", fields, 4)[0],
                                configured_card_count_at_0x7c=struct.unpack_from("<i", fields, 0x1c)[0]))
            if (session.pointer(entry) != entry_table
                    or session.read(entry + 0x28, 16) != name_header
                    or pointer and session.read(pointer, length) != name_bytes
                    or session.read(entry + 0x60, 0x20) != fields):
                raise RuntimeError("test setting changed during observation")
        if (session.read(registry + 0x30, 16) != vector_header
                or observed and session.read(data_pointer, observed * 8) != vector_bytes):
            raise RuntimeError("settings vector changed during observation")
    if session.pointer(session.base + SERVICE_ROOT_VA) != root:
        raise RuntimeError("service root changed during observation")
    if root and session.pointer(root + 0x20) != services:
        raise RuntimeError("services changed during observation")
    if services and session.pointer(services + REGISTRY_OFFSET) != registry:
        raise RuntimeError("settings registry changed during observation")
    if registry and session.pointer(registry) != table:
        raise RuntimeError("settings registry type changed during observation")
    if table and any(session.pointer(table + slot) != raw_slots[slot]
                     for slot in REGISTRY_SLOTS):
        raise RuntimeError("settings registry callbacks changed during observation")
    session.verify()
    return dict(evidence_kind="bounded non-atomic read-only registry observation",
                pid=identity["pid"], process_start_time=identity["process_start_time"],
                library_sha256=identity["library_sha256"], base=identity["base"],
                service_root_slot_va=hex(SERVICE_ROOT_VA), root=hex(root),
                services_at_root_0x20=hex(services),
                registry_at_services_0x3c8=hex(registry),
                registry_table_va=hex(table - session.base) if table else None,
                registry_slots=slots, logical_bytes_read=session.used,
                settings_count=count, observed_settings_count=observed,
                all_settings_observed=count == observed if count is not None else False,
                settings=entries,
                runtime_executed=False,
                limitations=["non-atomic snapshot with repeated ownership checks",
                             "registry existence is not proof of usable settings",
                             "no getters invoked and no local battle started"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--identity", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = observe(json.loads(args.identity.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
