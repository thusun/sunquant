# encoding: UTF-8
# author email: szy@tsinghua.org.cn

import threading

class SQLock:
    def __init__(self):
        self._locker = threading.Lock()

    def __enter__(self):
        if self._locker.acquire(timeout=30):
            return self
        return None

    def __exit__(self, exc_type, exc_value, exc_tb):
        self._locker.release()
        return False
