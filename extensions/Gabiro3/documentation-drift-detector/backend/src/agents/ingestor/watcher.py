import hashlib
import time
from pathlib import Path
from typing import Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from core.config import WATCHED_DIR


class DocChangeHandler(FileSystemEventHandler):
    def __init__(self, callback):
        self._callback = callback
        self._debounce: dict[str, float] = {}
        self._debounce_seconds = 2.0

    def on_modified(self, event):
        if event.is_directory:
            return
        path = event.src_path
        now = time.time()
        last = self._debounce.get(path, 0)
        if now - last < self._debounce_seconds:
            return
        self._debounce[path] = now
        self._callback(path)

    def on_created(self, event):
        if not event.is_directory:
            self.on_modified(event)


class DocWatcher:
    def __init__(self, watched_dir: Optional[str] = None, callback=None):
        self.watched_dir = Path(watched_dir or WATCHED_DIR)
        self.watched_dir.mkdir(parents=True, exist_ok=True)
        self._observer: Optional[Observer] = None
        self._callback = callback
        self._known_hashes: dict[str, str] = {}

    def scan_and_hash(self) -> dict[str, str]:
        current: dict[str, str] = {}
        for p in self.watched_dir.iterdir():
            if p.is_file() and self._is_doc(p):
                current[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
        return current

    def diff(self) -> list[str]:
        current = self.scan_and_hash()
        changed = []
        for path, h in current.items():
            prev = self._known_hashes.get(path)
            if prev is None:
                changed.append(path)
            elif prev != h:
                changed.append(path)
        for path in list(self._known_hashes):
            if path not in current:
                del self._known_hashes[path]
        self._known_hashes.update(current)
        return changed

    def on_file_event(self, path: str):
        rel = str(Path(path).relative_to(self.watched_dir))
        if not self._is_doc(Path(path)):
            return
        changed = self.diff()
        if self._callback:
            for c in changed:
                self._callback(c)

    def start(self) -> None:
        self._known_hashes = self.scan_and_hash()
        self._observer = Observer()
        handler = DocChangeHandler(self.on_file_event)
        self._observer.schedule(handler, str(self.watched_dir), recursive=True)
        self._observer.start()

    def stop(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join()

    @staticmethod
    def _is_doc(path: Path) -> bool:
        return path.suffix.lower() in {
            ".md", ".html", ".htm", ".txt", ".docx", ".pdf", ".rtf", ".tex"
        }