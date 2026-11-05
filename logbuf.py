"""In-memory log tail for the /logs page."""
import collections
import logging
import threading

_LOCK = threading.Lock()
_BUFFER = collections.deque(maxlen=400)


class BufferHandler(logging.Handler):
    def emit(self, record):
        with _LOCK:
            _BUFFER.append(self.format(record))


def lines():
    with _LOCK:
        return list(_BUFFER)
