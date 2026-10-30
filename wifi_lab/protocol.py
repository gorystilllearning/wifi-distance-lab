"""One TCP stream: bounded newline JSON control frames, length-delimited payload."""
import json
import socket
import time

MAX_FRAME = 131072
PAYLOAD_BYTES = 10_000_000
PORT = 8765


class ProtocolError(ValueError):
    pass


class Wire:
    def __init__(self, sock):
        self.sock = sock
        self.buffer = bytearray()

    def send(self, frame, timeout=5):
        data = json.dumps(frame, separators=(',', ':'), allow_nan=False).encode() + b'\n'
        if len(data) > MAX_FRAME:
            raise ProtocolError('Control frame too large')
        self.sock.settimeout(timeout)
        self.sock.sendall(data)

    def read(self, deadline):
        while True:
            pos = self.buffer.find(b'\n')
            if pos >= 0:
                if pos > MAX_FRAME:
                    raise ProtocolError('Control frame too large')
                raw = bytes(self.buffer[:pos])
                del self.buffer[:pos + 1]
                try:
                    frame = json.loads(raw)
                except (ValueError, UnicodeError) as exc:
                    raise ProtocolError('Invalid JSON') from exc
                if not isinstance(frame, dict):
                    raise ProtocolError('Control frame must be an object')
                return frame
            if len(self.buffer) > MAX_FRAME:
                raise ProtocolError('Control frame too large')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Control deadline exceeded')
            self.sock.settimeout(remaining)
            data = self.sock.recv(4096)
            if not data:
                raise EOFError('Peer closed control connection')
            self.buffer.extend(data)

    def recv(self, maximum, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Payload deadline exceeded')
        if self.buffer:
            data = bytes(self.buffer[:maximum])
            del self.buffer[:maximum]
            return data
        self.sock.settimeout(remaining)
        return self.sock.recv(maximum)


def expect(wire, kind, deadline, **fields):
    frame = wire.read(deadline)
    if frame.get('type') != kind or any(frame.get(k) != v for k, v in fields.items()):
        raise ProtocolError(f'Expected {kind} with matching identity')
    return frame
