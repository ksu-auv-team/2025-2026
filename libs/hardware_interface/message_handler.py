from __future__ import annotations
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional, Union, Dict, Any, Tuple
import json
import struct
import re


class Command(IntEnum):
    """
    Command codes for the wire protocol.
    """
    RST  = 0x01  # Restart board
    PROG = 0x02  # Reboot into programming mode
    POST = 0x10  # Data-bearing message


@dataclass(frozen=True)
class Message:
    """
    @brief Decoded message container.
    @param version Protocol version (binary frames) or None (string frames that don't carry version)
    @param cmd Command enum (RST/PROG/POST)
    @param src_id Source device (0..255)
    @param dst_id Destination device (0..255)
    @param payload Raw payload bytes (may be empty)
    @param checksum_ok True if checksum validated (binary); None for string frames
    @param raw The original input (bytes or str) for tracing
    """
    version: Optional[int]
    cmd: Command
    src_id: int
    dst_id: int
    payload: bytes
    checksum_ok: Optional[bool]
    raw: Union[bytes, str]

    # Convenience helpers:
    def payload_text(self) -> Optional[str]:
        """@return UTF-8 text if decodable; else None."""
        try:
            return self.payload.decode("utf-8")
        except Exception:
            return None

    def payload_json(self) -> Optional[Any]:
        """@return JSON object if payload is valid UTF-8 JSON; else None."""
        t = self.payload_text()
        if t is None:
            return None
        try:
            return json.loads(t)
        except Exception:
            return None


@dataclass(frozen=True)
class MessageHandlerConfig:
    """
    @brief Configuration for message formatting/parsing.
    @param version Wire protocol version byte added to binary frames.
    @param string_open Delimiter opening character for string frames.
    @param string_close Delimiter closing character for string frames.
    @param string_sep Separator used between fields in string frames.
    @param json_indent Optional JSON pretty print for string payloads (None = compact).
    """
    version: int = 0x01
    string_open: str = "<"
    string_close: str = ">"
    string_sep: str = ","
    json_indent: Optional[int] = None


class MessageHandler:
    """
    @brief Formats and parses messages in binary or string form. No I/O.
    @details
      Binary frame (recommended):
        'B','R', version:u8, cmd:u8, src:u8, dst:u8, len:u16 (BE), payload[len], checksum:u16 (sum of all prior bytes)
      String frame (human-readable):
        <src_id,target_id,COMMAND[,payload]>
    """

    # ---------- Construction ----------
    def __init__(self, config: Optional[MessageHandlerConfig] = None, src_id: int = 0x00, dst_id: int = 0xFF):
        self.cfg = config or MessageHandlerConfig()
        self.src_id = src_id
        self.dst_id = dst_id

    # ---------- Encoding (public) ----------
    def build_rst(self, as_binary: bool = True) -> Union[bytes, str]:
        return self._build(cmd=Command.RST, src_id=self.src_id, dst_id=self.dst_id, payload=None, as_binary=as_binary)

    def build_prog(self, as_binary: bool = True) -> Union[bytes, str]:
        return self._build(cmd=Command.PROG, src_id=self.src_id, dst_id=self.dst_id, payload=None, as_binary=as_binary)

    def build_post(self, payload: Union[bytes, str, Dict[str, Any]], as_binary: bool = True) -> Union[bytes, str]:
        norm_payload = self._normalize_payload(payload)
        return self._build(cmd=Command.POST, src_id=self.src_id, dst_id=self.dst_id, payload=norm_payload, as_binary=as_binary)

    # ---------- Decoding (public) ----------
    def parse(self, data: Union[bytes, bytearray, str]) -> Message:
        """
        @brief Auto-detect and parse either a binary or string frame.
        @param data Bytes/bytearray or string.
        @return Message object with structured fields and helpers.
        @throws ValueError for format errors.
        """
        if isinstance(data, (bytes, bytearray)):
            if self._looks_like_binary(data):
                return self.parse_binary(bytes(data))
            # Could be a text string accidentally given as bytes; try decoding to str
            try:
                text = data.decode("utf-8")
                return self.parse_string(text)
            except Exception:
                raise ValueError("Unrecognized byte sequence: neither binary frame nor UTF-8 string.")
        elif isinstance(data, str):
            # String: either ASCII-ized binary (unlikely) or proper string frame
            return self.parse_string(data)
        else:
            raise TypeError("parse() expects bytes/bytearray or str")

    def parse_binary(self, frame: bytes) -> Message:
        """
        @brief Parse a binary frame.
        @param frame The raw bytes.
        @return Message with checksum_ok flag.
        @throws ValueError if the frame is invalid.
        """
        # Minimum header: 'B','R', v, cmd, src, dst, len(2), cksum(2) => 10 bytes even with 0 payload
        if len(frame) < 10:
            raise ValueError("Binary frame too short")

        if frame[0:2] != b"BR":
            raise ValueError("Invalid binary header (missing 'BR')")

        version = frame[2]
        cmd_val = frame[3]
        src_id = frame[4]
        dst_id = frame[5]
        plen = struct.unpack(">H", frame[6:8])[0]

        # Expected total length
        expected_len = 2 + 1 + 1 + 1 + 1 + 2 + plen + 2  # BR + v + cmd + src + dst + len + payload + cksum
        if len(frame) != expected_len:
            raise ValueError(f"Binary length mismatch (expected {expected_len}, got {len(frame)})")

        payload = frame[8:8+plen]
        recv_cksum = struct.unpack(">H", frame[8+plen:8+plen+2])[0]

        # Compute checksum across everything except the final checksum field
        calc_cksum = self._checksum16(frame[:-2])
        checksum_ok = (calc_cksum == recv_cksum)

        # Map command
        try:
            cmd = Command(cmd_val)
        except ValueError:
            raise ValueError(f"Unknown command: 0x{cmd_val:02X}")

        return Message(
            version=version,
            cmd=cmd,
            src_id=src_id,
            dst_id=dst_id,
            payload=payload,
            checksum_ok=checksum_ok,
            raw=frame,
        )

    def parse_string(self, text: str) -> Message:
        """
        @brief Parse a string frame: <src_id,target_id,COMMAND[,payload]>
        @param text The string representation (whitespace tolerant).
        @return Message with checksum_ok=None (not applicable).
        @throws ValueError if malformed.
        """
        s = text.strip()
        o, c = self.cfg.string_open, self.cfg.string_close
        if not (s.startswith(o) and s.endswith(c)):
            raise ValueError(f"String frame must be wrapped by {o}...{c}")

        inner = s[len(o):-len(c)].strip()
        # Split on separators, but allow commas inside JSON by doing a simple top-level split:
        # We expect either 3 tokens (src,dst,COMMAND) or 4 tokens (src,dst,COMMAND,payload)
        parts = self._top_level_split(inner, self.cfg.string_sep, maxsplit=3)

        if len(parts) < 3:
            raise ValueError("String frame missing required fields: src_id,dst_id,COMMAND")

        src_str, dst_str, cmd_str = parts[0].strip(), parts[1].strip(), parts[2].strip()
        payload_str = parts[3].strip() if len(parts) == 4 else None

        # Parse ids
        try:
            src_id = int(src_str, 0)
            dst_id = int(dst_str, 0)
        except Exception:
            raise ValueError("src_id and dst_id must be integers")

        self._validate_u8(src_id, "src_id")
        self._validate_u8(dst_id, "dst_id")

        # Parse command name
        try:
            cmd = Command[cmd_str]
        except KeyError:
            raise ValueError(f"Unknown COMMAND '{cmd_str}'")

        # Decode payload string → bytes
        payload_bytes = b""
        if payload_str is not None and payload_str != "":
            payload_bytes = self._decode_string_payload(payload_str)

        return Message(
            version=None,               # string frames don't carry version
            cmd=cmd,
            src_id=src_id,
            dst_id=dst_id,
            payload=payload_bytes,
            checksum_ok=None,          # not applicable for string frames
            raw=text,
        )

    # ---------- Encoding (internals) ----------
    def _build(self, cmd: Command, src_id: int, dst_id: int,
               payload: Optional[bytes], as_binary: bool) -> Union[bytes, str]:
        self._validate_u8(src_id, "src_id")
        self._validate_u8(dst_id, "dst_id")
        if as_binary:
            return self._build_binary(cmd, src_id, dst_id, payload or b"")
        else:
            return self._build_string(cmd, src_id, dst_id, payload)

    def _build_binary(self, cmd: Command, src_id: int, dst_id: int, payload: bytes) -> bytes:
        header = bytearray()
        header.extend(b"BR")
        header.append(self.cfg.version & 0xFF)
        header.append(int(cmd) & 0xFF)
        header.append(src_id & 0xFF)
        header.append(dst_id & 0xFF)
        header.extend(struct.pack(">H", len(payload)))
        frame_wo_ck = bytes(header) + payload
        cksum = self._checksum16(frame_wo_ck)
        return frame_wo_ck + struct.pack(">H", cksum)

    def _build_string(self, cmd: Command, src_id: int, dst_id: int, payload: Optional[bytes]) -> str:
        parts = [str(src_id), str(dst_id), cmd.name]
        if payload:
            # Prefer inline UTF-8 if possible; else hex
            try:
                parts.append(payload.decode("utf-8"))
            except UnicodeDecodeError:
                parts.append(payload.hex())
        return f"{self.cfg.string_open}{self.cfg.string_sep.join(parts)}{self.cfg.string_close}"

    # ---------- Helpers ----------
    @staticmethod
    def _checksum16(data: bytes) -> int:
        return sum(data) & 0xFFFF

    @staticmethod
    def _validate_u8(value: int, name: str) -> None:
        if not (0 <= int(value) <= 255):
            raise ValueError(f"{name} must be 0..255 (got {value}).")

    @staticmethod
    def _looks_like_binary(buf: bytes) -> bool:
        return len(buf) >= 2 and buf[0:2] == b"BR"

    @staticmethod
    def _normalize_payload(payload: Union[bytes, str, Dict[str, Any]]) -> bytes:
        if isinstance(payload, bytes):
            return payload
        if isinstance(payload, str):
            return payload.encode("utf-8")
        return json.dumps(payload, separators=(",", ":")).encode("utf-8")

    def _decode_string_payload(self, p: str) -> bytes:
        """
        @brief Convert a string payload to bytes.
        @details Tries JSON text (→ UTF-8), then hex (even length), else UTF-8 raw.
        """
        # Try JSON first (object/array/number/bool/null or quoted string)
        try:
            # Quick heuristic: only try JSON when it plausibly looks like JSON
            if p and p[0] in "{[\"-0123456789tfn]":
                _ = json.loads(p)
                return p.encode("utf-8")
        except Exception:
            pass

        # Try hex (even number of [0-9a-fA-F])
        if re.fullmatch(r"[0-9a-fA-F]{2,}", p) and len(p) % 2 == 0:
            try:
                return bytes.fromhex(p)
            except Exception:
                pass

        # Fallback: treat as UTF-8 text
        return p.encode("utf-8")

    @staticmethod
    def _top_level_split(s: str, sep: str, maxsplit: int) -> list[str]:
        """
        @brief Split at top level only (does not break inside balanced {...} or [...] quotes).
        @details Minimal heuristic for your use case: respects JSON-like braces/brackets and quotes.
        """
        out, token, depth, in_str, esc = [], [], 0, False, False
        quote_char = ""
        for ch in s:
            if in_str:
                token.append(ch)
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == quote_char:
                    in_str = False
            else:
                if ch in "\"'":
                    in_str = True
                    quote_char = ch
                    token.append(ch)
                elif ch in "{[":
                    depth += 1
                    token.append(ch)
                elif ch in "}]":
                    depth = max(0, depth - 1)
                    token.append(ch)
                elif ch == sep and depth == 0 and (maxsplit <= 0 or len(out) < maxsplit):
                    out.append("".join(token))
                    token = []
                else:
                    token.append(ch)
        out.append("".join(token))
        return out
