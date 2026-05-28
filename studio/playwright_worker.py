"""
Worker. 在后台线程里循环:
1. 从 TaskQueue 取一个 pending task
2. pick_account(同 backend、配额最多)
3. 启动/复用该账号 Playwright session
4. 跳转到 backend home_url → 自动填 prompt → (如果有参考图)上传 → 提交
5. 进入「awaiting」状态:工具等用户在浏览器里 review/确认(扫码登录、修参数、下载)
   同时启动 DownloadsWatcher 监听
6. 监听到新文件 → 归档到项目 assets/ → mark_done
7. 配额 -1

设计权衡(M2 当前阶段):
- 不强求"全自动" — DOM 变了/反爬触发了/扫码登录都会卡住
- 半自动模式:工具帮你打开浏览器 + 填 prompt + 等结果 + 归档
- 用户在浏览器里完成"我看着挺好,下载它"这一步,工具自动入库
"""
from __future__ import annotations
from typing import Optional, List, Callable
from pathlib import Path
import threading, time, shutil

from PySide6.QtCore import QObject, Signal

from .models import (
    GenerationTask, Account,
    TASK_PENDING, TASK_RUNNING, TASK_AWAITING, TASK_DONE, TASK_FAILED,
    TASK_TYPE_VIDEO,
)
from . import storage as ST
from .task_queue import get_queue, pick_account
from .site_profiles import load_profiles
from .downloads_watcher import DownloadsWatcher
from .playwright_session import get_pool, HAS_PLAYWRIGHT


class Worker(QObject):
    """单线程 worker。多账号并发?暂时不,M2 先稳。"""
    log = Signal(str)

    def __init__(self):
        super().__init__()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self.profiles = load_profiles(ST.APP_DIR / "site_profiles.json")
        self._task_done_callbacks: List[Callable] = []

    def start(self):
        if self._running: return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.log.emit("Worker 已启动")

    def stop(self):
        self._running = False
        self.log.emit("Worker 即将停止")

    def is_available(self) -> bool:
        return HAS_PLAYWRIGHT

    def _loop(self):
        q = get_queue()
        while self._running:
            try:
                pending = q.pending()
                if not pending:
                    time.sleep(1.0); continue
                task = pending[0]
                self._execute(task)
            except Exception as e:
                self.log.emit(f"Worker 异常: {e}")
                time.sleep(2.0)

    def _execute(self, task: GenerationTask):
        q = get_queue()
        if not HAS_PLAYWRIGHT:
            q.mark_failed(task.id, "Playwright 未安装。pip install playwright + playwright install chromium")
            self.log.emit(f"[{task.title}] Playwright 未安装,跳过")
            return

        # 1. 选账号
        accounts = ST.load_accounts()
        acc = pick_account(task, accounts)
        if not acc:
            q.mark_failed(task.id, f"找不到 {task.backend_id} 后端的可用账号(或额度耗尽)")
            self.log.emit(f"[{task.title}] 找不到可用账号")
            return

        # 2. profile
        profile = self.profiles.get(task.backend_id)
        if not profile:
            q.mark_failed(task.id, f"backend {task.backend_id} 没有 site profile")
            return

        # 3. 启动会话
        q.mark_running(task.id, acc.id)
        self.log.emit(f"[{task.title}] 派发给 {acc.name}")
        try:
            session = get_pool().get_or_create(acc)
            if not session.status.online:
                session.start(headless=False)
                self.log.emit(f"[{acc.name}] 浏览器已启动")
            session.goto(profile.home_url)

            # 4. 检查登录
            if profile.needs_login and not session.is_logged_in(profile.auth_cookies):
                self.log.emit(f"[{acc.name}] 未登录,请在弹出的浏览器扫码")
                # 等用户登录:轮询 60s
                for _ in range(60):
                    time.sleep(1.0)
                    if session.is_logged_in(profile.auth_cookies):
                        self.log.emit(f"[{acc.name}] 登录成功"); break
                else:
                    q.mark_failed(task.id, "60 秒未完成登录")
                    return

            # 5. 填 prompt
            if profile.input_box:
                ok = session.fill_clipboard_paste(profile.input_box, task.prompt)
                if not ok:
                    self.log.emit(f"[{task.title}] 自动填 prompt 失败,请在浏览器手动粘贴(已在剪贴板)")
                    # fallback: 把 prompt 拷到剪贴板
                    self._copy_to_clipboard(task.prompt)
                else:
                    self.log.emit(f"[{task.title}] 已自动填入 prompt")

            # 6. 上传参考图(如果有)
            if task.reference_images and profile.upload_btn:
                try:
                    page = session.page()
                    if page:
                        # 通常 click 触发 file chooser
                        with page.expect_file_chooser() as fc_info:
                            session.click(profile.upload_btn)
                        fc = fc_info.value
                        fc.set_files(task.reference_images)
                        self.log.emit(f"[{task.title}] 已上传 {len(task.reference_images)} 张参考图")
                except Exception as e:
                    self.log.emit(f"[{task.title}] 自动上传失败 ({e}),请手动")

            # 7. 进入 awaiting 模式 — 启动 downloads 监听
            q.mark_awaiting(task.id)
            self.log.emit(f"[{task.title}] 等用户在浏览器完成生成 + 下载...")

            # 8. 监听下载目录
            session_downloads = session.downloads_dir
            os_downloads = self._guess_os_downloads()
            found_file = self._wait_for_download(
                [session_downloads, os_downloads],
                timeout=600  # 10 min
            )

            if not found_file:
                q.mark_failed(task.id, "10 分钟内没监听到新文件")
                return

            # 9. 归档到项目 assets/
            rel = ST.import_asset(task.project_id, found_file)
            q.mark_done(task.id, result_files=[rel])
            self.log.emit(f"[{task.title}] 已归档: {rel}")

            # 10. 配额 -1
            if task.task_type == TASK_TYPE_VIDEO and not acc.is_unlimited():
                acc.daily_quota_used = min(acc.daily_quota_total, acc.daily_quota_used + 1)
                acc.video_quota_used = acc.daily_quota_used
                ST.save_accounts(accounts)

            # 11. 回写到目标对象(角色参考图、分镜参考图等)
            self._writeback(task, rel)

            for cb in self._task_done_callbacks:
                try: cb(task)
                except Exception: pass

        except Exception as e:
            q.mark_failed(task.id, str(e))
            self.log.emit(f"[{task.title}] 失败: {e}")

    def _guess_os_downloads(self) -> Path:
        from .downloads_watcher import default_downloads_dir
        return default_downloads_dir()

    def _wait_for_download(self, watch_dirs: List[Path], timeout: int = 600) -> Optional[Path]:
        """轮询多个目录,返回第一个出现的新文件。"""
        # 记初始快照
        snapshots = {}
        media_exts = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".webm"}
        for d in watch_dirs:
            if d.exists():
                snapshots[d] = {p.name for p in d.iterdir()
                                if p.is_file() and p.suffix.lower() in media_exts}
            else:
                snapshots[d] = set()

        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self._running:
                return None
            for d in watch_dirs:
                if not d.exists(): continue
                current = {p.name for p in d.iterdir()
                           if p.is_file() and p.suffix.lower() in media_exts}
                new_names = current - snapshots[d]
                for name in new_names:
                    p = d / name
                    # 等大小稳定
                    try:
                        s1 = p.stat().st_size; time.sleep(0.4); s2 = p.stat().st_size
                        if s1 == s2 and s1 > 0:
                            return p
                    except Exception:
                        pass
            time.sleep(1.0)
        return None

    def _writeback(self, task: GenerationTask, asset_rel: str):
        """任务完成后,把结果文件路径回填到对应业务对象。"""
        if not task.target_kind or not task.target_id: return
        pid = task.project_id

        if task.target_kind == "character":
            chars = ST.load_characters(pid)
            for c in chars:
                if c.id == task.target_id:
                    if not c.reference_image:
                        c.reference_image = asset_rel
                    else:
                        c.extra_images.append(asset_rel)
                    ST.save_characters(pid, chars); break
        elif task.target_kind == "scene":
            scenes = ST.load_scenes(pid)
            for s in scenes:
                if s.id == task.target_id:
                    s.reference_image = asset_rel
                    ST.save_scenes(pid, scenes); break
        elif task.target_kind == "prop":
            props = ST.load_props(pid)
            for p in props:
                if p.id == task.target_id:
                    p.reference_image = asset_rel
                    ST.save_props(pid, props); break
        elif task.target_kind == "shot":
            # 找到 shot 所在 episode
            for ep in ST.list_episodes(pid):
                for shot in ep.shots:
                    if shot.id == task.target_id:
                        if task.task_type == TASK_TYPE_VIDEO:
                            shot.generated_video = asset_rel
                        else:
                            shot.generated_image = asset_rel
                        ST.save_episode(pid, ep)
                        return
        elif task.target_kind == "segment":
            for ep in ST.list_episodes(pid):
                for seg in ep.segments:
                    if seg.id == task.target_id:
                        if task.task_type == TASK_TYPE_VIDEO:
                            seg.generated_video = asset_rel
                        else:
                            seg.storyboard_image = asset_rel
                        ST.save_episode(pid, ep)
                        return

    def _copy_to_clipboard(self, text: str):
        try:
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(text)
        except Exception:
            pass

    def on_task_done(self, callback: Callable):
        self._task_done_callbacks.append(callback)


# 单例
_worker_singleton: Optional[Worker] = None

def get_worker() -> Worker:
    global _worker_singleton
    if _worker_singleton is None:
        _worker_singleton = Worker()
    return _worker_singleton
