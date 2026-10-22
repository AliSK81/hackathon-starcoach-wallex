"""A LangChain cache that saves every AI call and answer in SQLite.

Live runs only record: each call is new, because the data changes every cycle.
With replay on, a call that was saved before gets the saved answer, so a judge
can re-run a past cycle and see the same decisions (research files 04 and 09).
The key is the full prompt and the model settings, hashed.
"""

import hashlib
import sqlite3
import threading
import warnings
from pathlib import Path

from langchain_core.caches import RETURN_VAL_TYPE, BaseCache
from langchain_core.load import dumps, loads


class SQLiteLLMCache(BaseCache):
    def __init__(self, path: Path, replay: bool = False):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.replay = replay
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS calls "
                         "(key TEXT PRIMARY KEY, prompt TEXT, model TEXT, answer TEXT)")
        self._db.commit()

    @staticmethod
    def key(prompt: str, llm_string: str) -> str:
        return hashlib.sha256((llm_string + "\n" + prompt).encode()).hexdigest()

    def lookup(self, prompt: str, llm_string: str) -> RETURN_VAL_TYPE | None:
        if not self.replay:
            return None
        with self._lock:
            row = self._db.execute("SELECT answer FROM calls WHERE key = ?", (self.key(prompt, llm_string),)).fetchone()
        if not row:
            return None
        with warnings.catch_warnings():  # loads() is marked beta; the saved answers are our own
            warnings.simplefilter("ignore")
            return loads(row[0])

    def update(self, prompt: str, llm_string: str, return_val: RETURN_VAL_TYPE) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO calls VALUES (?, ?, ?, ?)",
                             (self.key(prompt, llm_string), prompt, llm_string, dumps(return_val)))
            self._db.commit()

    def clear(self, **kwargs) -> None:
        with self._lock:
            self._db.execute("DELETE FROM calls")
            self._db.commit()
