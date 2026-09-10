"""Bounded nanopb varint-delimited stream framing, independent of packet boundaries."""
MAX_FRAME = 65536


def frame(payload: bytes) -> bytes:
    if not 0 < len(payload) <= MAX_FRAME:
        raise ValueError("Invalid protobuf frame size")
    n = len(payload)
    prefix = bytearray()
    while n > 127:
        prefix.append((n & 127) | 128)
        n >>= 7
    prefix.append(n)
    return bytes(prefix) + payload


class Decoder:
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        if len(data) > MAX_FRAME:
            raise ValueError("Transport chunk too large")
        self.buffer.extend(data)
        result = []
        while self.buffer:
            size = 0
            for i, b in enumerate(self.buffer[:5]):
                size |= (b & 127) << (7 * i)
                if b < 128:
                    if not 0 < size <= MAX_FRAME:
                        raise ValueError("Invalid protobuf length")
                    if len(self.buffer) < i + 1 + size:
                        return result
                    result.append(bytes(self.buffer[i + 1:i + 1 + size]))
                    del self.buffer[:i + 1 + size]
                    break
            else:
                if len(self.buffer) >= 5:
                    raise ValueError("Invalid varint length")
                return result
        return result
