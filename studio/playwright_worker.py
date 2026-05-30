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
            # 桥接 session 内部调试日志 → UI log(挂一次就够,setter 幂等)
            try: sess.set_log_callback(self.log.emit)
            except Exception: pass
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
            # 把 session 的内部调试日志(导航/快照)桥接到 worker log,UI 看得见
            try: session.set_log_callback(self.log.emit)
            except Exception: pass
            if not session.status.online:
                session.start(headless=False)
                self.log.emit(f"[{acc.name}] 浏览器已启动")
            session.goto(profile.home_url)

            # 4. 检查登录 — 软检测:cookie 命中 OR 没有可见登录按钮 = 视为已登录
            #    乐观策略:不阻塞任务,直接尝试做;真的没登录后续操作会报错
            if profile.needs_login and not session.is_logged_in(profile.auth_cookies):
                # 二次确认:再等 5 秒(给页面加载时间),还是 false 才警告
                time.sleep(3)
                if not session.is_logged_in(profile.auth_cookies):
                    self.log.emit(
                        f"[{acc.name}] ⚠ 检测不到登录 cookie/页面仍有登录按钮 — "
                        f"尝试继续(若实际已登录,任务会正常跑;否则会报具体错误)"
                    )
                    # 不 return,不阻塞,继续走

            # 4.5 视频任务:若 profile 配了 video_entry,先点切到视频模式
            # (豆包: 顶部"视频生成"tab;即梦/未来其它平台同理)
            from .models import TASK_TYPE_VIDEO as _TT_V
            if task.task_type == _TT_V and profile.video_entry:
                page = session.page()
                if page:
                    clicked = False
                    for vsel in [s.strip() for s in profile.video_entry.split(',') if s.strip()]:
                        try:
                            page.click(vsel, timeout=2000)
                            clicked = True
                            self.log.emit(f"[{task.title}] 已切到视频生成模式 ({vsel[:40]})")
                            time.sleep(0.8)  # 等界面切换
                            break
                        except Exception: continue
                    if not clicked:
                        self.log.emit(
                            f"[{task.title}] 视频入口点击都失败 — 假设页面已在视频模式,继续"
                        )

            # 5. 填 prompt — 长 prompt 自动走 TXT 附件(用户反馈 GPT 镜像吃不下大段)
            threshold = getattr(profile, "txt_upload_threshold", 4000)
            prompt_len = len(task.prompt or "")
            use_txt_mode = (threshold > 0 and prompt_len > threshold and
                           profile.upload_btn)

            # auto_filled:fill 完且确认进去了 → 后面才能自动点发送
            # 任何一条 fill 路径失败(包括 readback 长度不对)都不要点送,
            # 因为用户大概率在手动粘贴,我们再 click 一下就把他还没粘完的东西发出去了
            auto_filled = False

            if use_txt_mode:
                # TXT 模式:写 .txt 文件 + 智能上传 + 输入框写短指令
                self.log.emit(
                    f"[{task.title}] prompt 长度 {prompt_len} > {threshold},"
                    f"改用 TXT 附件上传(避免截断)"
                )
                fname = f"prompt_{task.id[:12]}.txt"
                use_bom = getattr(profile, "txt_use_bom", True)
                # 先写文件(只写,不注入 — session.upload_txt 的写文件逻辑)
                upload_root = session.downloads_dir / "_uploads"
                upload_root.mkdir(parents=True, exist_ok=True)
                txt_path = upload_root / fname
                try:
                    prefix = "\ufeff" if use_bom else ""
                    txt_path.write_text(prefix + task.prompt, encoding="utf-8")
                except Exception as e:
                    self.log.emit(f"[{task.title}] 写 .txt 失败: {e}")
                    txt_path = None

                upload_ok = False
                if txt_path and txt_path.exists():
                    # 用 _smart_upload(支持 GPT input 模式 + 豆包 chooser 模式)
                    upload_ok = self._smart_upload(session, profile, [txt_path])

                if upload_ok:
                    bom_tag = "+BOM" if use_bom else "-BOM"
                    self.log.emit(f"[{task.title}] TXT 附件上传完成 ({bom_tag})")
                    # 等附件预览出现
                    try:
                        page = session.page()
                        if page:
                            page.wait_for_selector(
                                '[data-testid*="file-preview"], [data-testid*="attachment"], '
                                '[class*="attachment"], [class*="filePreview"], '
                                '[class*="upload-preview"], [class*="FilePreview"]',
                                timeout=8000
                            )
                    except Exception: pass
                    # 输入框写短指令
                    instruction = getattr(profile, "txt_upload_instruction",
                                          "请严格按附件 TXT 里的内容执行任务。")
                    if profile.input_box:
                        ok = session.fill_clipboard_paste(profile.input_box, instruction)
                        auto_filled = bool(ok)
                    else:
                        auto_filled = True  # 不需要输入框,TXT 上完算成功
                else:
                    self.log.emit(f"[{task.title}] TXT 上传失败,退化到直接填 prompt")
                    if profile.input_box:
                        ok = session.fill_clipboard_paste(profile.input_box, task.prompt)
                        auto_filled = bool(ok)
                        self._copy_to_clipboard(task.prompt)
            elif profile.input_box:
                # 普通模式:走诊断版,失败时把详情吐到 log + 写快照
                diag = session.fill_with_diagnostics(profile.input_box, task.prompt)
                method = diag.get("fill_method") or "?"
                navigated = diag.get("navigated", False)
                if diag.get("ok"):
                    nav_tag = " (点击触发了页面跳转,已自动重定位)" if navigated else ""
                    self.log.emit(
                        f"[{task.title}] 已自动填入 prompt ({prompt_len} 字, "
                        f"方式={method}){nav_tag}"
                    )
                    auto_filled = True
                else:
                    self.log.emit(f"[{task.title}] 自动填 prompt 失败,请在浏览器手动粘贴(已在剪贴板)")
                    # === 详细诊断 ===
                    cands = diag.get("candidates") or []
                    if cands:
                        summary = "; ".join(
                            f"{c['selector'][:32]}({c['count']})"
                            for c in cands
                        )
                        self.log.emit(f"[{task.title}] 选择器命中数: {summary}")
                    chosen = diag.get("chosen_selector") or ""
                    ci = diag.get("chosen_info") or {}
                    if chosen:
                        self.log.emit(
                            f"[{task.title}] 取到的元素: tag={ci.get('tag')} "
                            f"id={ci.get('id')} visible={ci.get('visible')} "
                            f"disabled={ci.get('disabled')} editable={ci.get('editable')}"
                        )
                        if ci.get("placeholder"):
                            self.log.emit(f"[{task.title}] 元素 placeholder: {ci['placeholder']!r}")
                    ub, ua = diag.get("url_before") or "", diag.get("url_after") or ""
                    if navigated:
                        self.log.emit(f"[{task.title}] ⚠ click 触发了页面跳转: {ub} → {ua}")
                    else:
                        self.log.emit(f"[{task.title}] url 未变: {ua}")
                    self.log.emit(
                        f"[{task.title}] 注入路径={method} readback={diag.get('typed_length')} 字 "
                        f"error={diag.get('error')!r}"
                    )
                    # 写完整快照(截图 + DOM + probe)
                    try:
                        snap = session.snapshot_page(label=f"fill_fail_{task.id[:8]}")
                        if snap.get("dir"):
                            self.log.emit(f"[{task.title}] 调试快照已写到 {snap['dir']}")
                        probe = snap.get("probe") or {}
                        if probe:
                            self.log.emit(
                                f"[{task.title}] 页面 probe: "
                                f"textareas={probe.get('input_textareas')}/visible={len(probe.get('visible_textareas') or [])} "
                                f"editables={probe.get('input_editables')}/visible={len(probe.get('visible_editables') or [])} "
                                f"file_inputs={probe.get('file_inputs')} "
                                f"send_btns={len(probe.get('send_buttons') or [])}"
                            )
                            if probe.get("error_banners"):
                                self.log.emit(f"[{task.title}] ⚠ 页面提示元素: {probe['error_banners']}")
                            if probe.get("visible_login_hints"):
                                self.log.emit(f"[{task.title}] ⚠ 页面仍可见登录按钮: {probe['visible_login_hints']}")
                    except Exception as e:
                        self.log.emit(f"[{task.title}] 快照过程异常: {e}")
                    self._copy_to_clipboard(task.prompt)

            # 6. 上传参考图(若有)— 用 _smart_upload(兼容 GPT 直注入 + 豆包 chooser)
            if task.reference_images and profile.upload_btn:
                try:
                    ok = self._smart_upload(session, profile, task.reference_images)
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

            # 7b-pre: 自动点发送(只在 fill 确认成功的前提下,免得抢用户手动操作)
            # 视频任务额外要求 profile 显式允许,免得一不小心烧了珍贵的视频额度
            auto_send_ok = getattr(profile, "auto_send_after_fill", True)
            if (auto_filled and profile.send_btn and auto_send_ok):
                # 给 SPA 一点时间把 send 按钮从 disabled 变 enabled(React state 同步)
                try:
                    page = session.page()
                    if page:
                        # 用 :not([disabled]):not([aria-disabled="true"]) 等可点击状态
                        first_send_sel = profile.send_btn.split(',')[0].strip()
                        try:
                            page.wait_for_selector(
                                f'{first_send_sel}:not([disabled])', timeout=5000
                            )
                        except Exception:
                            # 没等到也试一下 — 有些镜像 disabled 属性不规范
                            pass
                        time.sleep(0.4)
                except Exception: pass
                clicked = False
                last_err = None
                for ssel in [s.strip() for s in profile.send_btn.split(',') if s.strip()]:
                    try:
                        session.click(ssel)
                        clicked = True
                        self.log.emit(f"[{task.title}] 已自动点发送 ({ssel[:40]})")
                        break
                    except Exception as e:
                        last_err = e
                        continue
                if not clicked:
                    self.log.emit(
                        f"[{task.title}] 自动点发送失败,请手动点 ({last_err})"
                    )
            elif not auto_filled and profile.send_btn:
                self.log.emit(f"[{task.title}] (fill 没成功,跳过自动点发送 — 避免抢你手动操作)")

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

            # 层 1: 自动点下载(豆包 hover 才显示下载按钮 → 先 hover 容器)
            if profile.download_btn:
                try:
                    page = session.page()
                    if page:
                        # 先等生成完成的标志(result_selector 出现)
                        if profile.result_selector:
                            try:
                                page.wait_for_selector(profile.result_selector, timeout=300_000)
                                time.sleep(2)  # 给 SPA 一点渲染时间
                            except Exception: pass

                        # 先 hover 到结果容器,让 hover-only 按钮显示(豆包)
                        if profile.result_selector:
                            try:
                                # 取第一个 selector(去掉逗号兜底)
                                first_sel = profile.result_selector.split(',')[0].strip()
                                # 取最后一个匹配元素(最新生成)
                                els = page.query_selector_all(first_sel)
                                if els:
                                    els[-1].scroll_into_view_if_needed()
                                    els[-1].hover()
                                    time.sleep(0.4)   # 等 hover 按钮动画
                            except Exception: pass

                        # 多 selector 试点击:取第一个能 expect_download 成功的
                        download = None
                        last_err = None
                        for dsel in [s.strip() for s in profile.download_btn.split(',') if s.strip()]:
                            try:
                                with page.expect_download(timeout=15_000) as dl_info:
                                    page.click(dsel, timeout=5000, force=True)
                                download = dl_info.value
                                break
                            except Exception as e:
                                last_err = e
                                continue

                        if download:
                            target = session_downloads / download.suggested_filename
                            download.save_as(str(target))
                            if target.exists():
                                found_file = target
                                self.log.emit(f"[{task.title}] 自动下载成功: {target.name}")
                        else:
                            self.log.emit(f"[{task.title}] 下载按钮都点不出 download 事件 ({last_err})")
                except Exception as e:
                    self.log.emit(f"[{task.title}] 自动下载失败 ({e}),退化到 HTTP 抓 src")

            # 层 2: 抓 img/video src 直接 HTTP 下
            if not found_file and (profile.result_image_in or profile.result_video_in):
                try:
                    page = session.page()
                    if page:
                        sel = profile.result_video_in if task.task_type == TASK_TYPE_VIDEO else profile.result_image_in
                        if sel:
                            # 上面 marker 已经命中过 → result_selector 大概率已经在 DOM 里;
                            # 即便没命中(profile 没配 completion_text_marker),也别再等 5 分钟,
                            # 给个 10s 短等够了。这是之前"抓的太慢"的真凶 —
                            # aimonkey 镜像不用 [data-message-author-role=assistant] 这个属性,
                            # 老代码 timeout=300_000 把 5 分钟全耗完才走到 query。
                            if profile.result_selector:
                                try: page.wait_for_selector(profile.result_selector, timeout=10_000)
                                except Exception: pass
                            time.sleep(1.0)  # 给 SPA 一点渲染时间(从 2s 砍到 1s)
                            els = page.query_selector_all(sel)
                            # 兜底:specific CDN selectors 全 miss → 退到「最新消息容器内最大的 img」
                            if not els and task.task_type != TASK_TYPE_VIDEO:
                                fallback_js = """
                                (resultSel) => {
                                  // 找最新 message 容器
                                  let containers = [];
                                  if (resultSel) {
                                    for (const s of resultSel.split(',')) {
                                      const arr = document.querySelectorAll(s.trim());
                                      if (arr.length) { containers = [...arr]; break; }
                                    }
                                  }
                                  const scope = containers.length
                                    ? containers[containers.length - 1]
                                    : document.body;
                                  // 在 scope 里挑面积最大的 img
                                  let best = null, bestArea = 0;
                                  scope.querySelectorAll('img').forEach(img => {
                                    if (!img.src || img.src.startsWith('data:')) return;
                                    const w = img.naturalWidth || img.width || 0;
                                    const h = img.naturalHeight || img.height || 0;
                                    const area = w * h;
                                    if (area > bestArea && area > 100*100) {
                                      best = img; bestArea = area;
                                    }
                                  });
                                  return best ? {
                                    src: best.src,
                                    naturalW: best.naturalWidth, naturalH: best.naturalHeight,
                                    parentHref: best.closest('a') ? best.closest('a').href : '',
                                  } : null;
                                }
                                """
                                try:
                                    fb = page.evaluate(fallback_js, profile.result_selector or "")
                                except Exception:
                                    fb = None
                                if fb:
                                    src_url = fb.get("parentHref") or fb.get("src")
                                    self.log.emit(
                                        f"[{task.title}] 兜底找到大图: "
                                        f"{fb['naturalW']}x{fb['naturalH']} "
                                        f"src={('a[href]' if fb.get('parentHref') else 'img[src]')}"
                                    )
                                    referer = ""
                                    try: referer = page.url or ""
                                    except Exception: pass
                                    found_file = self._download_via_http(
                                        src_url, session_downloads, referer=referer,
                                    )
                                    if not found_file:
                                        found_file = self._download_via_browser(
                                            page, src_url, session_downloads,
                                        )
                                    if found_file:
                                        self.log.emit(f"[{task.title}] HTTP 抓产物成功(兜底): {found_file.name}")
                            elif els:
                                # 命中了 selector chain — 取最后一个(最新生成的)
                                # 优先用 parent <a href>(很多镜像 img 是缩略图,href 才是原图)
                                last_el = els[-1]
                                src = None
                                src_kind = "img[src]"
                                try:
                                    href = last_el.evaluate(
                                        "el => { const a = el.closest('a'); return a ? a.href : ''; }"
                                    )
                                    if href and not href.startswith("javascript"):
                                        src = href
                                        src_kind = "a[href] (原图链接)"
                                except Exception: pass
                                if not src:
                                    src = last_el.get_attribute("src") or last_el.get_attribute("data-src")
                                # 记录尺寸
                                try:
                                    dims = last_el.evaluate(
                                        "el => ({ nw: el.naturalWidth||0, nh: el.naturalHeight||0 })"
                                    )
                                    self.log.emit(
                                        f"[{task.title}] 选中产物: {src_kind} "
                                        f"img 原始尺寸 {dims.get('nw')}x{dims.get('nh')}"
                                    )
                                except Exception: pass
                                if src:
                                    referer = ""
                                    try: referer = page.url or ""
                                    except Exception: pass
                                    found_file = self._download_via_http(
                                        src, session_downloads, referer=referer,
                                    )
                                    # 若 urllib 失败(签名校验/CORS),退到浏览器内 fetch + base64 回传
                                    if not found_file:
                                        found_file = self._download_via_browser(
                                            page, src, session_downloads,
                                        )
                                    if found_file:
                                        self.log.emit(f"[{task.title}] HTTP 抓产物成功: {found_file.name}")
                except Exception as e:
                    self.log.emit(f"[{task.title}] HTTP 抓产物失败 ({e})")

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

    def _smart_upload(self, session, profile, files: list) -> bool:
        """智能文件上传 — 兼容两种站点设计:

        模式 A (GPT 镜像):页面已有 hidden input[type=file],直接 set_input_files 注入。
        模式 B (豆包):upload_btn 是 dropdown menuitem,点了才弹原生 file chooser。
                     需先点 upload_trigger 打开菜单,再点 menuitem,
                     用 page.expect_file_chooser 抓 chooser 后 set_files。
        """
        page = session.page()
        if not page or not profile.upload_btn: return False
        raw_paths = [str(f) for f in (files if isinstance(files, list) else [files])]

        # 多账号关键:上传前把本账号页面拉到前台,避免被 Chrome 当后台窗口降频
        # (后台窗口的上传 XHR 会被掐到 0%)
        try:
            page.bring_to_front()
        except Exception:
            pass

        # ─── 0. 校验文件:不存在 / 0 字节会让站点上传永远卡 0% ───
        paths = []
        for p in raw_paths:
            fp = Path(p)
            if not fp.exists():
                self.log.emit(f"  ⚠ 上传文件不存在,跳过: {p}")
                continue
            try:
                sz = fp.stat().st_size
            except Exception:
                sz = 0
            if sz < 100:
                self.log.emit(f"  ⚠ 文件过小/疑似空 ({sz}B),跳过: {fp.name}")
                continue
            paths.append(p)
            self.log.emit(f"  ↳ 待上传: {fp.name} ({sz // 1024}KB)")
        if not paths:
            self.log.emit("  ⚠ 没有有效文件可上传(全部不存在或为空) — 检查参考图路径")
            return False

        # 诊断:页面上有几个 file input(0 个 = 选择器/站点 DOM 不对)
        try:
            n_inputs = page.eval_on_selector_all('input[type="file"]', "els => els.length")
            self.log.emit(f"  ↳ 页面 file input 数量: {n_inputs}")
        except Exception:
            pass

        # 拆分多 selector(逗号分隔)
        all_sels = [s.strip() for s in profile.upload_btn.split(',') if s.strip()]
        input_sels = [s for s in all_sels if 'input' in s.lower() and 'file' in s.lower()]
        click_sels = [s for s in all_sels if s not in input_sels]

        # ─── 模式 A: 直接注入 input[type=file] ───
        for sel in input_sels:
            try:
                if page.query_selector(sel):
                    page.set_input_files(sel, paths, timeout=5000)
                    # React-safe:主动派发 input/change,确保 SPA 的上传 handler 接到
                    try:
                        page.eval_on_selector(sel, """el => {
                            el.dispatchEvent(new Event('input', { bubbles: true }));
                            el.dispatchEvent(new Event('change', { bubbles: true }));
                        }""")
                    except Exception:
                        pass
                    self.log.emit(f"  ↳ 上传模式 A (set_input_files): {sel[:50]}")
                    # 验证有没有冒出上传预览/缩略图(说明站点真的接住了文件)
                    if self._verify_upload_appeared(page):
                        self.log.emit("  ↳ ✓ 检测到上传预览,文件已被站点接收")
                    else:
                        self.log.emit(
                            "  ⚠ 已注入但没检测到上传预览 —— 可能注入到了错误的隐藏 input,"
                            "或站点上传卡住(若进度条停 0%,多半是站点/网络端)"
                        )
                    return True
            except Exception as e:
                self.log.emit(f"  ↳ 模式 A 失败 ({sel[:30]}): {e}")
                continue

        # ─── 模式 B: click 触发 + 抓 file chooser ───
        if click_sels or profile.upload_trigger:
            try:
                with page.expect_file_chooser(timeout=8000) as fc_info:
                    # 先点首层触发器(可选 — 豆包的"+"按钮)
                    if profile.upload_trigger:
                        for tsel in [s.strip() for s in profile.upload_trigger.split(',') if s.strip()]:
                            try:
                                page.click(tsel, timeout=2000)
                                time.sleep(0.5)   # 等 dropdown 动画
                                break
                            except Exception: continue
                    # 再点 menuitem
                    clicked = False
                    for csel in click_sels:
                        try:
                            page.click(csel, timeout=2000)
                            clicked = True
                            break
                        except Exception: continue
                    if not clicked and not profile.upload_trigger:
                        return False
                fc = fc_info.value
                fc.set_files(paths)
                self.log.emit(f"  ↳ 上传模式 B (file_chooser): {len(paths)} 个文件")
                if self._verify_upload_appeared(page):
                    self.log.emit("  ↳ ✓ 检测到上传预览,文件已被站点接收")
                else:
                    self.log.emit("  ⚠ chooser 已交付文件但没检测到预览,可能站点上传卡住")
                return True
            except Exception as e:
                self.log.emit(f"  ↳ chooser 模式失败: {e}")
                return False

        return False

    def _verify_upload_appeared(self, page, timeout_ms: int = 4000) -> bool:
        """注入文件后,轮询看页面有没有冒出上传预览/缩略图。
        有 = 站点接住了文件(哪怕还在传);没有 = 注入可能没生效。
        纯诊断用,不影响上传本身的成败判断。"""
        import time as _t
        selectors = [
            '[class*="upload-preview"]', '[class*="FilePreview"]',
            '[class*="image-preview"]', '[class*="ImagePreview"]',
            '[class*="attachment"]', '[class*="thumbnail"]',
            '[class*="file-item"]', '[class*="uploaded"]',
            'img[src^="blob:"]', 'img[src^="data:image"]',
        ]
        deadline = _t.time() + timeout_ms / 1000.0
        while _t.time() < deadline:
            for s in selectors:
                try:
                    if page.query_selector(s):
                        return True
                except Exception:
                    pass
            _t.sleep(0.3)
        return False

    def _download_via_http(self, src_url: str, save_dir: Path,
                           referer: str = "") -> Optional[Path]:
        """直接 HTTP GET 图片/视频 src(blob:/data: URL 跳过)。

        referer:豆包 douyinvod 等签名 URL 需要正确 Referer 才不被 403。
        """
        import urllib.request, urllib.parse, uuid as _uuid
        if not src_url: return None
        save_dir.mkdir(parents=True, exist_ok=True)
        try:
            if src_url.startswith("blob:") or src_url.startswith("data:"):
                return None
            parsed = urllib.parse.urlparse(src_url)
            ext = Path(parsed.path).suffix or ".png"
            if len(ext) > 6: ext = ".png"
            target = save_dir / f"http_{_uuid.uuid4().hex[:8]}{ext}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/126.0.0.0 Safari/537.36",
            }
            if referer:
                headers["Referer"] = referer
                # 推断 Origin(豆包 douyinvod 也认这个)
                try:
                    p = urllib.parse.urlparse(referer)
                    headers["Origin"] = f"{p.scheme}://{p.netloc}"
                except Exception: pass
            req = urllib.request.Request(src_url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as r:
                target.write_bytes(r.read())
            return target if target.exists() and target.stat().st_size > 1024 else None
        except Exception:
            return None

    def _download_via_browser(self, page, src_url: str, save_dir: Path) -> Optional[Path]:
        """在浏览器内 fetch + base64 回传(走浏览器的 cookies/CORS)。
        
        用于 blob: URL 或签名验证严格的 CDN(豆包 douyinvod 等)。
        urllib 拿不到的,这条路通常能拿到。
        """
        import base64, uuid as _uuid, urllib.parse
        if not src_url or not page: return None
        save_dir.mkdir(parents=True, exist_ok=True)
        try:
            # 在浏览器内 fetch + 转 base64
            js = """
            async (url) => {
                try {
                    const r = await fetch(url, { credentials: 'include' });
                    if (!r.ok) return null;
                    const blob = await r.blob();
                    const buf = await blob.arrayBuffer();
                    const bytes = new Uint8Array(buf);
                    let bin = '';
                    for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
                    return { b64: btoa(bin), type: blob.type, size: blob.size };
                } catch(e) { return { error: String(e) }; }
            }
            """
            result = page.evaluate(js, src_url)
            if not result or "b64" not in result: return None
            mime = result.get("type", "")
            ext = ".mp4" if "mp4" in mime else (
                  ".png" if "png" in mime else (
                  ".jpg" if "jpeg" in mime else ".bin"))
            target = save_dir / f"br_{_uuid.uuid4().hex[:8]}{ext}"
            target.write_bytes(base64.b64decode(result["b64"]))
            return target if target.exists() and target.stat().st_size > 1024 else None
        except Exception:
            return None

    def _extract_last_frame(self, pid: str, video_rel: str,
                            target_stem: str) -> str:
        """从已归档的视频抽末帧,保存到 project assets/,返回相对路径。
        失败返回空字符串。用于'末帧→下一段首帧'跨镜衔接。"""
        import shutil, subprocess
        if not shutil.which("ffmpeg"):
            self.log.emit("⚠ ffmpeg 不在 PATH 里,跳过末帧抽取(下一镜不会自动衔接)")
            return ""
        try:
            video_full = ST.asset_full_path(pid, video_rel)
            if not video_full or not video_full.exists():
                return ""
            # 写到临时位置,然后 import_asset 进 assets/ 走归档+重名避让
            tmp_dir = ST.project_dir(pid) / "_tmp"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            tmp = tmp_dir / f"{target_stem}.jpg"
            # -sseof -0.1:seek 到末尾前 0.1s,抽 1 帧
            # 注意 -sseof 必须放在 -i 前,Format 时间是相对文件尾的负数
            result = subprocess.run(
                ["ffmpeg", "-y", "-sseof", "-0.1", "-i", str(video_full),
                 "-vframes", "1", "-q:v", "2", str(tmp)],
                capture_output=True, timeout=15,
            )
            if result.returncode != 0 or not tmp.exists():
                # 部分编码 -sseof 可能 seek 失败,退化到 -ss 末尾前 0.3s + duration
                # 拿 duration 用 ffprobe(也是 ffmpeg 套件)
                try:
                    pr = subprocess.run(
                        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                         "-of", "default=noprint_wrappers=1:nokey=1", str(video_full)],
                        capture_output=True, timeout=5, text=True,
                    )
                    duration = float((pr.stdout or "0").strip() or 0)
                except Exception:
                    duration = 0
                if duration > 0.5:
                    seek = max(0.1, duration - 0.3)
                    result2 = subprocess.run(
                        ["ffmpeg", "-y", "-ss", f"{seek}", "-i", str(video_full),
                         "-vframes", "1", "-q:v", "2", str(tmp)],
                        capture_output=True, timeout=15,
                    )
                    if result2.returncode != 0 or not tmp.exists():
                        self.log.emit(f"⚠ 末帧抽取失败 (ffmpeg 两次都不行)")
                        return ""
            # 归档进 assets/
            rel = ST.import_asset(pid, tmp, target_name=f"{target_stem}.jpg")
            try: tmp.unlink()
            except Exception: pass
            if rel:
                self.log.emit(f"  ↳ 末帧已抽出: {rel}(供下一镜首帧参考)")
            return rel
        except Exception as e:
            self.log.emit(f"⚠ 末帧抽取异常: {e}")
            return ""

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
                            # 抽末帧 — 给下一镜当首帧参考(跨镜连续性)
                            lf = self._extract_last_frame(pid, asset_rel,
                                                          f"lastframe_shot_{shot.id}")
                            if lf:
                                shot.last_frame_image = lf
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
                            lf = self._extract_last_frame(pid, asset_rel,
                                                          f"lastframe_seg_{seg.id}")
                            if lf:
                                seg.last_frame_image = lf
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
        """把 AI 返回的 JSON 写回相应对象。
        目前支持的 target_kind:
          - episode: 拆分镜回写(M3.5)
          - character_facescan: 看图识别五官 → 回填 Character 结构化字段
          - document_parse: 整篇剧本文档解析 → 批量创建 Characters / Scenes / Episodes
          - episode_continue: 续写下一集 → 创建新 Episode + 追加世界圣经
        """
        from .models import Shot, VideoSegment
        pid = task.project_id

        # ---- 续写下一集:创建新 Episode + 追加世界圣经'已发生事件' ----
        if task.target_kind == "episode_continue":
            if not isinstance(parsed, dict):
                self.log.emit(f"[{task.title}] 解析的不是 dict,跳过")
                return
            from .models import Episode
            eps = ST.list_episodes(pid)
            next_num = (max([e.number for e in eps], default=0)) + 1
            title = (parsed.get("title") or f"第 {next_num} 集").strip()
            new_ep = Episode(
                project_id=pid,
                number=next_num,
                title=title,
                synopsis=(parsed.get("synopsis") or "").strip(),
                emotional_arc=(parsed.get("emotional_arc") or "").strip(),
                script=(parsed.get("script") or "").strip(),
            )
            ST.save_episode(pid, new_ep)
            # 把 world_updates 追加到 world_bible '已发生事件' 区段
            updates = (parsed.get("world_updates") or "").strip()
            cliff = (parsed.get("cliffhanger") or "").strip()
            if updates or cliff:
                try:
                    wb = ST.load_world_bible(pid)
                    append = [f"\n\n### 第 {next_num} 集 · {title}"]
                    if updates:
                        for line in updates.split("\n"):
                            line = line.strip()
                            if line: append.append(f"- {line}")
                    if cliff:
                        append.append(f"- 🪝 本集勾子:{cliff}")
                    # 插入到 '已发生事件' 章节后面;找不到就追加到文末
                    marker = "## 📜 时间线 / 已发生事件"
                    appended = "\n".join(append)
                    if marker in wb:
                        # 插到下一个 ## 章节之前(找下一个 \n## 位置)
                        head = wb.split(marker, 1)
                        rest = head[1]
                        next_section = rest.find("\n## ")
                        if next_section >= 0:
                            wb = (head[0] + marker + rest[:next_section]
                                  + appended + "\n" + rest[next_section:])
                        else:
                            wb = head[0] + marker + rest + appended
                    else:
                        wb = wb + f"\n\n## 📜 时间线 / 已发生事件{appended}\n"
                    ST.save_world_bible(pid, wb)
                except Exception as e:
                    self.log.emit(f"[{task.title}] 写回世界圣经失败: {e}")
            self.log.emit(
                f"[{task.title}] ✅ 第 {next_num} 集已创建:{title}。"
                f"下一步打开本集点 '🧠 AI 拆分镜' 拆出分镜表。"
            )
            return

        # ---- 整篇剧本文档解析:批量创建素材 ----
        if task.target_kind == "document_parse":
            if not isinstance(parsed, dict):
                self.log.emit(f"[{task.title}] 解析的不是 dict,跳过写回")
                return
            counts = {"chars": 0, "scenes": 0, "eps": 0}
            # 1. 角色
            chars_in = parsed.get("characters") or []
            if isinstance(chars_in, list) and chars_in:
                existing_chars = ST.load_characters(pid)
                existing_names = {c.name for c in existing_chars}
                from .models import Character
                for cd in chars_in:
                    if not isinstance(cd, dict): continue
                    name = (cd.get("name") or "").strip()
                    if not name or name in existing_names: continue
                    existing_names.add(name)
                    existing_chars.append(Character(
                        project_id=pid,
                        name=name,
                        role=(cd.get("role") or "主角").strip(),
                        gender=(cd.get("gender") or "").strip(),
                        age=(cd.get("age") or "").strip(),
                        visual_style=(cd.get("visual_style") or "2D 写实国漫").strip(),
                        hair=(cd.get("hair") or "").strip(),
                        body=(cd.get("body") or "").strip(),
                        face_shape=(cd.get("face_shape") or "").strip(),
                        eye_details=(cd.get("eye_details") or "").strip(),
                        nose_shape=(cd.get("nose_shape") or "").strip(),
                        lip_shape=(cd.get("lip_shape") or "").strip(),
                        eyebrow_style=(cd.get("eyebrow_style") or "").strip(),
                        jawline=(cd.get("jawline") or "").strip(),
                        skin_details=(cd.get("skin_details") or "").strip(),
                        style_lock=(cd.get("style_lock") or "").strip(),
                        notes=(cd.get("notes") or "").strip(),
                    ))
                    counts["chars"] += 1
                if counts["chars"]:
                    ST.save_characters(pid, existing_chars)
            # 2. 场景
            scenes_in = parsed.get("scenes") or []
            if isinstance(scenes_in, list) and scenes_in:
                existing_scenes = ST.load_scenes(pid)
                existing_names = {s.name for s in existing_scenes}
                from .models import Scene
                for sd in scenes_in:
                    if not isinstance(sd, dict): continue
                    name = (sd.get("name") or "").strip()
                    if not name or name in existing_names: continue
                    existing_names.add(name)
                    existing_scenes.append(Scene(
                        project_id=pid,
                        name=name,
                        visual_style=(sd.get("visual_style") or "3D 超写实").strip(),
                        asset_description=(sd.get("asset_description") or "").strip(),
                        fixed_environment=(sd.get("fixed_environment") or "").strip(),
                        fixed_lighting=(sd.get("fixed_lighting") or "").strip(),
                        fixed_background=(sd.get("fixed_background") or "").strip(),
                        notes=(sd.get("notes") or "").strip(),
                    ))
                    counts["scenes"] += 1
                if counts["scenes"]:
                    ST.save_scenes(pid, existing_scenes)
            # 3. 集
            eps_in = parsed.get("episodes") or []
            if isinstance(eps_in, list) and eps_in:
                existing_eps = ST.list_episodes(pid)
                next_num = (max([e.number for e in existing_eps], default=0)) + 1
                existing_titles = {e.title for e in existing_eps}
                from .models import Episode
                for ed in eps_in:
                    if not isinstance(ed, dict): continue
                    title = (ed.get("title") or "").strip()
                    if title and title in existing_titles: continue
                    if title: existing_titles.add(title)
                    new_ep = Episode(
                        project_id=pid,
                        number=next_num,
                        title=title or f"第 {next_num} 集",
                        synopsis=(ed.get("synopsis") or "").strip(),
                        emotional_arc=(ed.get("emotional_arc") or "").strip(),
                        script=(ed.get("script") or "").strip(),
                    )
                    ST.save_episode(pid, new_ep)
                    next_num += 1
                    counts["eps"] += 1
            self.log.emit(
                f"[{task.title}] 整篇剧本解析完成 — "
                f"新建 {counts['chars']} 角色 / {counts['scenes']} 场景 / "
                f"{counts['eps']} 集。下一步:打开集详情点 '🧠 AI 拆分镜' 把每集拆成分镜。"
            )
            return

        # ---- 角色五官识别 ----
        if task.target_kind == "character_facescan":
            if not isinstance(parsed, dict):
                self.log.emit(f"[{task.title}] 解析的不是 dict,跳过写回")
                return
            chars = ST.load_characters(pid)
            ch = next((c for c in chars if c.id == task.target_id), None)
            if not ch:
                self.log.emit(f"[{task.title}] 找不到目标角色 (id={task.target_id})")
                return
            # 字段一一对应,只覆盖 GPT 给了非空值的字段(避免把用户已填的清掉)
            fields_map = {
                "face_shape": "face_shape", "eye_details": "eye_details",
                "nose_shape": "nose_shape", "lip_shape": "lip_shape",
                "eyebrow_style": "eyebrow_style", "jawline": "jawline",
                "skin_details": "skin_details", "style_lock": "style_lock",
                "hair": "hair", "body": "body",
            }
            filled = []
            for k_json, k_attr in fields_map.items():
                v = parsed.get(k_json)
                if v is None: continue
                v_str = str(v).strip()
                if not v_str: continue
                # 只在原字段为空 OR GPT 给的值跟原值显著不同时才覆盖
                # —— 不强覆盖避免用户手填的精确描述被换掉
                cur = (getattr(ch, k_attr, "") or "").strip()
                if cur and cur == v_str: continue
                setattr(ch, k_attr, v_str)
                filled.append(k_attr)
            if filled:
                ST.save_characters(pid, chars)
                self.log.emit(
                    f"[{task.title}] 已识别并写回 {len(filled)} 个字段: "
                    f"{', '.join(filled)}"
                )
            else:
                self.log.emit(f"[{task.title}] GPT 没给出任何有效字段")
            return

        # ---- 拆分镜回写(原有) ----
        if task.target_kind != "episode": return
        eps = ST.list_episodes(pid)
        ep = next((e for e in eps if e.id == task.target_id), None)
        if not ep: return

        if not isinstance(parsed, dict): return
        segments_data = parsed.get("segments") or []
        if not isinstance(segments_data, list): return

        # 硬卡:GPT 不听话生成超 5 镜/段时,自动拆段(豆包 10s 装 6+ 镜稳赶工漏镜)
        # 每段切成 ceil(N/5) 段,每段 ≤5 镜,number 重排
        def _split_oversized_segments(raw_segs):
            out = []
            for sd in raw_segs:
                if not isinstance(sd, dict):
                    out.append(sd); continue
                shots = sd.get("shots") or []
                if not isinstance(shots, list) or len(shots) <= 5:
                    out.append(sd); continue
                # 超 5 镜 → 切段
                self.log.emit(
                    f"[{task.title}] ⚠ GPT 返回段 {sd.get('number','?')} "
                    f"有 {len(shots)} 镜(超 5 上限),自动拆成 "
                    f"{(len(shots) + 4) // 5} 段免得豆包赶工漏镜"
                )
                # 每 4-5 镜一组,避免最后一组太少:目标每组 4 镜,余数往前补
                chunks = []
                i = 0
                remain = len(shots)
                while remain > 0:
                    take = 4 if remain >= 8 else min(5, remain)
                    chunks.append(shots[i:i+take])
                    i += take; remain -= take
                base_syn = sd.get("synopsis") or ""
                for ci, chunk in enumerate(chunks):
                    new_sd = dict(sd)
                    new_sd["shots"] = chunk
                    new_sd["synopsis"] = (
                        f"{base_syn}(自动拆段 {ci+1}/{len(chunks)})"
                        if base_syn else f"自动拆段 {ci+1}/{len(chunks)}"
                    )
                    out.append(new_sd)
            return out
        segments_data = _split_oversized_segments(segments_data)

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
