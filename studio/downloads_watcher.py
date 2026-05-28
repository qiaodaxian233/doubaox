"""
监听 ~/Downloads (或 Playwright context 的 downloads 目录) 的新文件,
返回新文件路径供 worker 自动归档到项目 assets/。

实现:轮询(简单可靠,跨平台),每 1.5s 扫一次目录。
"""
from __future__ import annotations
from pathlib import Path
from typing import Callable, List, Set
import time, threading


def default_downloads_dir() -> Path:
    """系统下载目录(跨平台)。"""
    home = Path.home()
    # macOS/Linux
    for cand in ("Downloads", "下载"):
        p = home / cand
        if p.exists(): return p
    # Windows
    p = home / "Downloads"
    p.mkdir(parents=True, exist_ok=True)
    return p


class DownloadsWatcher:
    """轮询监听器。start 后台跑;callback 在主线程(Qt 队列)调用要自己 marshal。"""
    MEDIA_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".webm", ".gif"}

    def __init__(self, watch_dir: Path = None, interval: float = 1.5):
        self.watch_dir = watch_dir or default_downloads_dir()
        self.interval = interval
        self._known: Set[Path] = set()
        self._running = False
        self._thread = None
        self._callbacks: List[Callable[[Path], None]] = []

    def on_new(self, callback: Callable[[Path], None]):
        self._callbacks.append(callback)

    def start(self):
        if self._running: return
        # 初始化已知文件(开始前已存在的,不算 new)
        self._known = self._scan()
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _scan(self) -> Set[Path]:
        if not self.watch_dir.exists(): return set()
        return {p for p in self.watch_dir.iterdir()
                if p.is_file() and p.suffix.lower() in self.MEDIA_EXTS}

    def _loop(self):
        while self._running:
            try:
                current = self._scan()
                new_files = current - self._known
                # 等文件大小稳定(避免下载中)
                for p in new_files:
                    if self._is_stable(p):
                        for cb in self._callbacks:
                            try: cb(p)
                            except Exception: pass
                        self._known.add(p)
            except Exception:
                pass
            time.sleep(self.interval)

    def _is_stable(self, p: Path, samples: int = 2, delay: float = 0.4) -> bool:
        """连续 N 次 size 不变 → 视为下载完成。"""
        try:
            s1 = p.stat().st_size
            time.sleep(delay)
            s2 = p.stat().st_size
            return s1 == s2 and s1 > 0
        except Exception:
            return False
