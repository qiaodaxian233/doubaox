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
import threading, time, shutil, queue

from PySide6.QtCore import QObject, Signal

from .models import (
    GenerationTask, Account,
    TASK_PENDING, TASK_RUNNING, TASK_AWAITING, TASK_DONE, TASK_FAILED,
    TASK_TYPE_VIDEO, TASK_TYPE_AI_CHAT,
)
from . import storage as ST
from .task_queue import get_queue, pick_account
from .site_profiles import load_profiles
from .downloads_watcher import DownloadsWatcher
from .playwright_session import get_pool, HAS_PLAYWRIGHT


class Worker(QObject):
    """单线程 worker — 所有 Playwright 操作必须在这个线程内做(避免 greenlet 跨线程错误)。
    
    UI 线程绝不直接调 sess.start() / sess.goto():通过 request_open_browser /
    request_stop_browser / request_navigate 把命令丢进控制队列,在 _loop 里处理。
    """
    log = Signal(str)
    task_done = Signal(str)
    task_failed = Signal(str, str)
    # 浏览器控制相关 — UI 通过这些信号知道结果
    browser_opened = Signal(str)         # acc_id
    browser_failed = Signal(str, str)    # acc_id, error
    browser_stopped = Signal(str)        # acc_id

    def __init__(self):
        super().__init__()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self.profiles = load_profiles(ST.APP_DIR / "site_profiles.json")
        # 控制命令队列(线程安全)— UI 线程往里写,worker 线程消费
        self._control_queue: queue.Queue = queue.Queue()
        self._pending_open_acc_ids: set = set()  # 去重:同一账号正在处理就不重复入队

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

    # ============ 浏览器控制命令(UI 线程调,worker 线程执行)============

    def request_open_browser(self, acc_id: str):
        """UI 线程要求 worker 启动该账号浏览器。线程安全。"""
        if not HAS_PLAYWRIGHT:
            self.browser_failed.emit(acc_id, "Playwright 未安装")
            return
        if acc_id in self._pending_open_acc_ids:
            self.log.emit(f"[{acc_id}] 已在处理队列,稍候")
            return
        self._pending_open_acc_ids.add(acc_id)
        self._control_queue.put(("open_browser", acc_id))
        # 确保 worker 在跑
        if not self._running:
            self.start()

    def request_stop_browser(self, acc_id: str):
        """UI 线程要求 worker 停止该账号浏览器。线程安全。"""
        self._control_queue.put(("stop_browser", acc_id))
        if not self._running and HAS_PLAYWRIGHT:
            self.start()

    def _poll_control_queue(self):
        """处理所有积压的控制命令。在 _loop / 长等待内周期调用。"""
        try:
            while True:
                cmd, arg = self._control_queue.get_nowait()
                if cmd == "open_browser":
                    self._handle_open_browser(arg)
                elif cmd == "stop_browser":
                    self._handle_stop_browser(arg)
        except queue.Empty:
            pass
        except Exception as e:
            self.log.emit(f"控制命令异常: {e}")

    def _handle_open_browser(self, acc_id: str):
        """在 worker 线程里启动账号浏览器 + 跳到 backend 主页。"""
        try:
            accounts = ST.load_accounts()
            acc = next((a for a in accounts if a.id == acc_id), None)
            if not acc:
                self.browser_failed.emit(acc_id, "找不到账号")
                return
            from . import storage as _ST
            backend = _ST.get_backend(acc.backend_id)
            if not backend:
                self.browser_failed.emit(acc_id, f"找不到 backend: {acc.backend_id}")
                return
            from .playwright_session import get_pool
            pool = get_pool()
            sess = pool.get_or_create(acc)
            if not sess.status.online:
                if acc.attach_cdp_url:
                    self.log.emit(f"[{acc.name}] 挂载 CDP {acc.attach_cdp_url}...")
                    sess.attach_cdp(acc.attach_cdp_url)
                else:
                    self.log.emit(f"[{acc.name}] 启动 Chromium...")
                    sess.start(headless=False)
                self.log.emit(f"[{acc.name}] 浏览器在线")
            sess.goto(backend.url)
            self.log.emit(
                f"[{acc.name}] 已打开 {backend.name} — 请在浏览器里扫码登录\n"
                f"  cookie 自动保存到 ~/.doubao-studio/profiles/{acc_id}/"
            )
            self.browser_opened.emit(acc_id)
        except Exception as e:
            err = str(e)
            self.log.emit(f"[{acc_id}] 启动失败: {err}")
            self.browser_failed.emit(acc_id, err)
        finally:
            self._pending_open_acc_ids.discard(acc_id)

    def _handle_stop_browser(self, acc_id: str):
        try:
            from .playwright_session import get_pool
            sess = get_pool().get(acc_id)
            if sess:
                sess.stop()
            self.browser_stopped.emit(acc_id)
        except Exception as e:
            self.log.emit(f"[{acc_id}] 停止失败: {e}")

    def _loop(self):
        q = get_queue()
        while self._running:
            try:
                # 1. 控制命令优先(浏览器登录、停止)
                self._poll_control_queue()
                # 2. 任务队列
                pending = q.pending()
                if not pending:
                    time.sleep(0.5); continue
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

            # 5. 填 prompt — 长 prompt 自动走 TXT 附件(用户反馈 GPT 镜像吃不下大段)
            threshold = getattr(profile, "txt_upload_threshold", 4000)
            prompt_len = len(task.prompt or "")
            use_txt_mode = (threshold > 0 and prompt_len > threshold and
                           profile.upload_btn)

            if use_txt_mode:
                # TXT 模式:写 .txt 文件 + 注入 file input + 输入框写短指令
                self.log.emit(
                    f"[{task.title}] prompt 长度 {prompt_len} > {threshold},"
                    f"改用 TXT 附件上传(避免 GPT 截断)"
                )
                # 文件名带 task id 便于追踪
                fname = f"prompt_{task.id[:12]}.txt"
                use_bom = getattr(profile, "txt_use_bom", True)
                upload_ok = session.upload_txt(
                    task.prompt, file_name=fname,
                    upload_selector=profile.upload_btn,
                    use_bom=use_bom,
                )
                if upload_ok:
                    bom_tag = "+BOM" if use_bom else "-BOM"
                    self.log.emit(f"[{task.title}] TXT 附件上传完成 ({bom_tag})")
                    # 等附件预览出现(确认 GPT 收到了)
                    try:
                        page = session.page()
                        if page:
                            page.wait_for_selector(
                                '[data-testid*="file-preview"], [data-testid*="attachment"], '
                                '[class*="attachment"], [class*="filePreview"], '
                                '[class*="upload-preview"]',
                                timeout=8000
                            )
                    except Exception: pass
                    # 输入框写短指令
                    instruction = getattr(profile, "txt_upload_instruction",
                                          "请严格按附件 TXT 里的内容执行任务。")
                    if profile.input_box:
                        session.fill_clipboard_paste(profile.input_box, instruction)
                else:
                    self.log.emit(f"[{task.title}] TXT 上传失败,退化到直接填 prompt")
                    if profile.input_box:
                        session.fill_clipboard_paste(profile.input_box, task.prompt)
                        self._copy_to_clipboard(task.prompt)
            elif profile.input_box:
                # 普通模式:直接填 prompt
                ok = session.fill_clipboard_paste(profile.input_box, task.prompt)
                if not ok:
                    self.log.emit(f"[{task.title}] 自动填 prompt 失败,请在浏览器手动粘贴(已在剪贴板)")
                    self._copy_to_clipboard(task.prompt)
                else:
                    self.log.emit(f"[{task.title}] 已自动填入 prompt ({prompt_len} 字)")

            # 6. 上传参考图(若有)— 用 set_input_files 直接注入,避开 file chooser 浮窗
            if task.reference_images and profile.upload_btn:
                try:
                    ok = session.set_input_files(profile.upload_btn, task.reference_images)
                    if ok:
                        self.log.emit(f"[{task.title}] 已上传 {len(task.reference_images)} 张参考图")
                    else:
                        self.log.emit(f"[{task.title}] 自动上传失败,请手动")
                except Exception as e:
                    self.log.emit(f"[{task.title}] 自动上传异常 ({e}),请手动")

            # 7. 进入 awaiting 模式
            q.mark_awaiting(task.id)

            # 7a. AI 聊天任务:不下载文件,而是抓 DOM 文本
            if task.task_type == TASK_TYPE_AI_CHAT:
                self.log.emit(f"[{task.title}] 等 GPT 返回 + 自动解析...")
                if profile.send_btn:
                    try: session.click(profile.send_btn)
                    except Exception: pass
                response_text = self._wait_for_chat_response(session, profile, timeout=300)
                if not response_text:
                    q.mark_failed(task.id, "5 分钟内没拿到 GPT 回复")
                    self.task_failed.emit(task.id, "no response")
                    return
                parsed = self._parse_json_block(response_text)
                if not parsed:
                    q.mark_failed(task.id, "未在 GPT 回复中找到合法 JSON")
                    self.task_failed.emit(task.id, "no json block")
                    self.log.emit(f"[{task.title}] GPT 回复长度 {len(response_text)} 但 JSON 解析失败")
                    return
                self._writeback_ai_chat(task, parsed, response_text)
                q.mark_done(task.id, result_text=response_text)
                self.log.emit(f"[{task.title}] AI 反解成功 — 已写回")
                self.task_done.emit(task.id)
                return

            # 7b. 图片/视频任务:三层 fallback 取产物
            #   层 0(预等): completion_text_marker 出现(中文 GPT 出"图片已创建")
            #   层 1: 配了 download_btn → page.expect_download() + 自动点击
            #   层 2: 配了 result_image_in / result_video_in → 直接抓图片 src 用 requests 下载
            #   层 3: 啥都没配 → 监听 Downloads 目录(等用户手动右键保存)
            self.log.emit(f"[{task.title}] 等生成完成 + 取产物...")
            session_downloads = session.downloads_dir
            os_downloads = self._guess_os_downloads()

            # 层 0: 等明确的"生成完成"文本(乔大仙的'图片已创建'检测术,只适用于图片任务)
            marker = getattr(profile, "completion_text_marker", "") or ""
            if marker and task.task_type != TASK_TYPE_VIDEO:
                try:
                    markers = [m.strip() for m in marker.split("||") if m.strip()]
                    hit = self._wait_for_text_marker(session, markers, timeout=300)
                    if hit:
                        self.log.emit(f"[{task.title}] 命中完成标志:'{hit}'")
                except Exception: pass

            found_file = None

            # 层 1: 自动点下载
            if profile.download_btn:
                try:
                    page = session.page()
                    if page:
                        # 先等生成完成的标志(result_selector 出现)
                        if profile.result_selector:
                            try:
                                page.wait_for_selector(profile.result_selector, timeout=300_000)
                                time.sleep(2)  # 给 SPA 一点渲染时间
                            except Exception:
                                pass
                        # 用 expect_download 抓下载事件
                        with page.expect_download(timeout=60_000) as dl_info:
                            session.click(profile.download_btn)
                        download = dl_info.value
                        target = session_downloads / download.suggested_filename
                        download.save_as(str(target))
                        if target.exists():
                            found_file = target
                            self.log.emit(f"[{task.title}] 自动下载成功: {target.name}")
                except Exception as e:
                    self.log.emit(f"[{task.title}] 自动下载失败 ({e}),退化到监听模式")

            # 层 2: 抓 img/video src 直接 HTTP 下
            if not found_file and (profile.result_image_in or profile.result_video_in):
                try:
                    page = session.page()
                    if page:
                        sel = profile.result_video_in if task.task_type == TASK_TYPE_VIDEO else profile.result_image_in
                        if sel:
                            if profile.result_selector:
                                try: page.wait_for_selector(profile.result_selector, timeout=300_000)
                                except Exception: pass
                            time.sleep(2)
                            els = page.query_selector_all(sel)
                            if els:
                                # 取最后一个(最新生成)
                                src = els[-1].get_attribute("src") or els[-1].get_attribute("data-src")
                                if src:
                                    found_file = self._download_via_http(src, session_downloads)
                                    if found_file:
                                        self.log.emit(f"[{task.title}] HTTP 抓图成功: {found_file.name}")
                except Exception as e:
                    self.log.emit(f"[{task.title}] HTTP 抓图失败 ({e})")

            # 层 3: 监听 Downloads 目录(用户手动下载)
            if not found_file:
                self.log.emit(f"[{task.title}] 等用户在浏览器手动下载...")
                found_file = self._wait_for_download(
                    [session_downloads, os_downloads],
                    timeout=600
                )

            if not found_file:
                q.mark_failed(task.id, "10 分钟内没监听到新文件")
                self.task_failed.emit(task.id, "no download")
                return

            # 8. 归档
            rel = ST.import_asset(task.project_id, found_file)
            q.mark_done(task.id, result_files=[rel])
            self.log.emit(f"[{task.title}] 已归档: {rel}")

            # 9. 配额 -1
            if task.task_type == TASK_TYPE_VIDEO and not acc.is_unlimited():
                acc.daily_quota_used = min(acc.daily_quota_total, acc.daily_quota_used + 1)
                acc.video_quota_used = acc.daily_quota_used
                ST.save_accounts(accounts)

            # 10. 回写
            self._writeback(task, rel)
            self.task_done.emit(task.id)

        except Exception as e:
            q.mark_failed(task.id, str(e))
            self.log.emit(f"[{task.title}] 失败: {e}")
            self.task_failed.emit(task.id, str(e))

    def _download_via_http(self, src_url: str, save_dir: Path) -> Optional[Path]:
        """直接 HTTP GET 图片/视频 src(blob: URL 用 Playwright 的 fetch)。"""
        import urllib.request, urllib.parse, uuid as _uuid
        if not src_url: return None
        save_dir.mkdir(parents=True, exist_ok=True)
        try:
            # blob: URL 不能用 urllib;留给后面用 page.evaluate
            if src_url.startswith("blob:") or src_url.startswith("data:"):
                return None
            # 推断扩展
            parsed = urllib.parse.urlparse(src_url)
            ext = Path(parsed.path).suffix or ".png"
            if len(ext) > 6: ext = ".png"
            target = save_dir / f"http_{_uuid.uuid4().hex[:8]}{ext}"
            req = urllib.request.Request(src_url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            })
            with urllib.request.urlopen(req, timeout=30) as r:
                target.write_bytes(r.read())
            return target if target.exists() and target.stat().st_size > 1024 else None
        except Exception:
            return None

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
            # 长等待中也处理控制命令(让用户能同时登录其它账号)
            self._poll_control_queue()
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
        elif task.target_kind == "canvas_item":
            items = ST.load_canvas_items(pid)
            for it in items:
                if it.id == task.target_id:
                    it.status = "done"
                    it.result_file = asset_rel
                    it.kind = "image" if task.task_type != "video" else "video"
                    ST.save_canvas_items(pid, items)
                    return

    # ============ M3.5: AI 聊天任务的 DOM 抓取 + JSON 反解 ============

    def _wait_for_text_marker(self, session, markers: list, timeout: int = 300) -> str:
        """轮询 body innerText,等任一标志出现。返回命中的标志,超时返回 ''。

        用于检测 GPT 镜像的'图片已创建'等生成完成强信号。
        """
        page = session.page() if session else None
        if not page or not markers: return ""
        deadline = time.time() + timeout
        last_count = 0
        while time.time() < deadline:
            if not self._running: return ""
            self._poll_control_queue()
            try:
                text = page.evaluate("() => document.body.innerText") or ""
                for m in markers:
                    if m and m in text:
                        return m
                # 进度日志(可选):每 10 次轮询打一次提示文本变化
                if len(text) != last_count and (time.time() - deadline + timeout) % 10 < 1:
                    last_count = len(text)
            except Exception: pass
            time.sleep(1.0)
        return ""

    def _wait_for_chat_response(self, session, profile, timeout: int = 300) -> str:
        """轮询 DOM 等 GPT 回复 + 稳定。
        连续 3 秒文本无变化 + 长度 > 50 字 → 视为完成。
        """
        if not profile.result_selector or not session.page():
            return ""
        page = session.page()
        last_text = ""
        stable_count = 0
        deadline = time.time() + timeout

        while time.time() < deadline:
            if not self._running: return last_text
            self._poll_control_queue()   # 同时处理其它账号的登录请求
            try:
                els = page.query_selector_all(profile.result_selector)
                if els:
                    text = els[-1].inner_text() or ""
                else:
                    text = page.evaluate("() => document.body.innerText")[-3000:]
                text = text.strip()
                if text and text == last_text and len(text) > 50:
                    stable_count += 1
                    if stable_count >= 3:
                        return text
                else:
                    stable_count = 0
                    last_text = text
            except Exception:
                pass
            time.sleep(1.0)
        return last_text

    def _parse_json_block(self, text: str):
        """从 markdown 文本里提 ```json ... ``` 块,失败则尝试平衡花括号扫描。"""
        import re, json as _json
        # 1. fenced code block
        m = re.search(r"```(?:json)?\s*\n?(.+?)\n?```", text, re.DOTALL)
        if m:
            block = m.group(1).strip()
            try: return _json.loads(block)
            except Exception: pass
        # 2. 平衡花括号扫描
        depth = 0; start = -1
        for i, ch in enumerate(text):
            if ch == "{":
                if depth == 0: start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start >= 0:
                    block = text[start:i + 1]
                    try: return _json.loads(block)
                    except Exception: continue
        return None

    def _writeback_ai_chat(self, task: GenerationTask, parsed: dict, raw_text: str):
        """把 AI 返回的 JSON 拆分镜数据写回 episode."""
        from .models import Shot, VideoSegment
        pid = task.project_id

        if task.target_kind != "episode": return
        eps = ST.list_episodes(pid)
        ep = next((e for e in eps if e.id == task.target_id), None)
        if not ep: return

        if not isinstance(parsed, dict): return
        segments_data = parsed.get("segments") or []
        if not isinstance(segments_data, list): return

        chars_by_name = {c.name: c.id for c in ST.load_characters(pid)}
        scenes_by_name = {s.name: s.id for s in ST.load_scenes(pid)}

        # 重置(用户主动调 AI 拆分镜 = 重新拆)
        ep.shots = []
        ep.segments = []

        cur_time = 0.0
        seg_number = 0
        for seg_data in segments_data:
            seg_number += 1
            shots_data = seg_data.get("shots", [])
            seg_shot_ids = []
            for sd in shots_data:
                shot = Shot(
                    episode_id=ep.id,
                    number=len(ep.shots) + 1,
                    duration=float(sd.get("duration", 2.5)),
                    start_time=cur_time,
                    action=sd.get("action", ""),
                    lighting=sd.get("lighting", ""),
                    sound=sd.get("sound", ""),
                    dialogue=sd.get("dialogue", ""),
                    shot_size=sd.get("shot_size", "中景"),
                    camera_movement=sd.get("camera_movement", "固定"),
                    transition_anchor=sd.get("transition_anchor", ""),
                )
                for name in sd.get("character_names", []):
                    if name in chars_by_name:
                        shot.character_ids.append(chars_by_name[name])
                scene_name = sd.get("scene_name", "")
                if scene_name and scene_name in scenes_by_name:
                    shot.scene_id = scenes_by_name[scene_name]
                ep.shots.append(shot)
                seg_shot_ids.append(shot.id)
                cur_time += shot.duration
            ep.segments.append(VideoSegment(
                episode_id=ep.id,
                number=seg_number,
                shot_ids=seg_shot_ids,
            ))

        if segments_data and segments_data[0].get("synopsis"):
            ep.synopsis = segments_data[0]["synopsis"]

        ST.save_episode(pid, ep)
        self.log.emit(f"AI 反解写入: {len(ep.shots)} 镜 / {len(ep.segments)} 段")

    def _copy_to_clipboard(self, text: str):
        try:
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(text)
        except Exception:
            pass


# 单例
_worker_singleton: Optional[Worker] = None

def get_worker() -> Worker:
    global _worker_singleton
    if _worker_singleton is None:
        _worker_singleton = Worker()
    return _worker_singleton
