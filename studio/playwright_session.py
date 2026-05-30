"""
Playwright session 管理。每个账号一个独立 Chromium(launch_persistent_context),
独立 cookie / 历史 / Downloads,避免账号互相污染。

设计原则(沿用 novel_ai 项目验证过的模式):
- 用 launch_persistent_context 而不是 launch + new_context → 状态自动持久化
- 每账号一个 user_data_dir → ~/.doubao-studio/profiles/<acc_id>/chrome_data/
- channel="chrome" 优先用本机 Chrome(指纹更真实,反爬过率高)
- 显式 viewport + 模拟真人 user-agent
- 单独 downloads_path → 工具能定位下载文件
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional, Callable, Dict
from dataclasses import dataclass
import asyncio, threading, time

from .models import Account
from . import storage as ST


# Playwright 是可选依赖,未装时模块仍可 import(M2 才用到)
try:
    from playwright.sync_api import sync_playwright, BrowserContext, Page
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


@dataclass
class SessionStatus:
    account_id: str
    online: bool = False
    logged_in: bool = False
    current_url: str = ""
    error: str = ""


class AccountSession:
    """单个账号的 Chromium 会话。线程不安全:必须在专属线程内使用。"""

    def __init__(self, account: Account):
        if not HAS_PLAYWRIGHT:
            raise RuntimeError(
                "Playwright 未安装。运行: pip install playwright && playwright install chromium"
            )
        self.account = account
        self.status = SessionStatus(account_id=account.id)
        self._pw = None
        self._ctx: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self.downloads_dir = ST.PROFILES_DIR / account.id / "downloads"
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        self.user_data_dir = ST.PROFILES_DIR / account.id / "chrome_data"
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        # 调试日志回调:worker / UI 通过 set_log_callback 注入,导航事件和填写诊断会回吐到这里
        self._log_cb: Optional[Callable[[str], None]] = None

    def set_log_callback(self, cb: Optional[Callable[[str], None]]):
        """让调用方接收来自 session 内部的调试日志(导航/失败/快照路径等)。"""
        self._log_cb = cb

    def _log(self, msg: str):
        if self._log_cb:
            try: self._log_cb(f"[{self.account.name}/调试] {msg}")
            except Exception: pass

    def _attach_nav_logger(self):
        """给当前 _page 挂导航/load 监听,记录任何 URL 跳转 — 检测"点生成后页面刷新"用。
        每个 page 对象只挂一次(挂在 page._doubaox_nav_attached 标记上)。"""
        page = self._page
        if not page: return
        try:
            if getattr(page, "_doubaox_nav_attached", False):
                return
        except Exception:
            pass

        def on_framenavigated(frame):
            try:
                if frame == page.main_frame:
                    self._log(f"页面导航 → {frame.url}")
            except Exception: pass

        def on_load():
            try:
                self._log(f"页面 load 完成 url={page.url}")
            except Exception: pass

        def on_requestfailed(req):
            try:
                # 只关心主文档 / xhr 失败
                if req.resource_type in ("document", "xhr", "fetch"):
                    self._log(
                        f"请求失败 {req.method} {req.url[:120]} - {req.failure}"
                    )
            except Exception: pass

        try: page.on("framenavigated", on_framenavigated)
        except Exception: pass
        try: page.on("load", on_load)
        except Exception: pass
        try: page.on("requestfailed", on_requestfailed)
        except Exception: pass
        try:
            page._doubaox_nav_attached = True  # type: ignore
        except Exception:
            pass

    def start(self, headless: bool = False):
        """启动 Chromium。headless=False(默认)便于扫码登录。"""
        if self._ctx: return
        self._pw = sync_playwright().start()
        try:
            self._ctx = self._pw.chromium.launch_persistent_context(
                user_data_dir=str(self.user_data_dir),
                channel="chrome",     # 本机 Chrome 优先
                headless=headless,
                viewport={"width": 1366, "height": 900},
                accept_downloads=True,
                downloads_path=str(self.downloads_dir),
                args=[
                    "--no-default-browser-check",
                    "--disable-blink-features=AutomationControlled",
                    # ↓ 多账号关键:禁后台标签/窗口降频,否则非前台账号的上传 XHR
                    #   会被 Chrome 掐到几乎不动 → 上传进度条永远卡 0%
                    "--disable-background-timer-throttling",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-renderer-backgrounding",
                    "--disable-features=CalculateNativeWinOcclusion",
                ],
            )
        except Exception:
            # 本机没装 Chrome → 退化到 chromium
            self._ctx = self._pw.chromium.launch_persistent_context(
                user_data_dir=str(self.user_data_dir),
                headless=headless,
                viewport={"width": 1366, "height": 900},
                accept_downloads=True,
                downloads_path=str(self.downloads_dir),
                args=[
                    "--no-default-browser-check",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-background-timer-throttling",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-renderer-backgrounding",
                    "--disable-features=CalculateNativeWinOcclusion",
                ],
            )
        # 注册 close 回调 — 用户手关浏览器时同步 online=False
        try:
            self._ctx.on("close", lambda _ctx=None: self._on_ctx_closed())
        except Exception:
            pass
        # 第一个页面
        pages = self._ctx.pages
        self._page = pages[0] if pages else self._ctx.new_page()
        # 页面关闭也记一下
        try:
            self._page.on("close", lambda _p=None: self._on_page_closed())
        except Exception:
            pass
        self._attach_nav_logger()
        self.status.online = True
        self.status.error = ""

    def attach_cdp(self, cdp_url: str = "http://localhost:9222"):
        """挂载到已运行的 Chrome(用户用 --remote-debugging-port=9222 启动的)。

        用法:
          1. 关掉所有 Chrome 窗口(否则 --user-data-dir 会被锁)
          2. 终端跑:
             macOS: /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --remote-debugging-port=9222
             Win:   "C:/Program Files/Google/Chrome/Application/chrome.exe" --remote-debugging-port=9222
             Linux: google-chrome --remote-debugging-port=9222
          3. 在新开的 Chrome 里登好账号
          4. 工具调本方法,通过 CDP 连过去
        """
        if self._ctx: return
        self._pw = sync_playwright().start()
        # connect_over_cdp 返回 Browser 对象,默认有一个 context
        browser = self._pw.chromium.connect_over_cdp(cdp_url)
        contexts = browser.contexts
        if not contexts:
            self._ctx = browser.new_context()
        else:
            self._ctx = contexts[0]
        # 拿第一个已有页面或新建
        pages = self._ctx.pages
        self._page = pages[0] if pages else self._ctx.new_page()
        try:
            self._page.on("close", lambda _p=None: self._on_page_closed())
        except Exception:
            pass
        self._attach_nav_logger()
        self._browser_attached = browser  # 保引用避免 GC
        self.status.online = True
        self.status.current_url = self._page.url if self._page else ""
        self.status.error = ""

    def _on_ctx_closed(self):
        self.status.online = False
        self._ctx = None
        self._page = None

    def _on_page_closed(self):
        # 页面没了,但 ctx 可能还活着(用户只关了 tab)。尝试取第一个 page
        try:
            if self._ctx and self._ctx.pages:
                self._page = self._ctx.pages[0]
                self._attach_nav_logger()
                return
        except Exception:
            pass
        # 没救了
        self.status.online = False
        self._page = None

    def stop(self):
        try:
            if self._ctx: self._ctx.close()
            if self._pw: self._pw.stop()
        except Exception:
            pass
        self._ctx = None
        self._page = None
        self._pw = None
        self.status.online = False

    def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 30_000):
        """打开 URL。若浏览器已被手动关闭,自动重启再试一次。"""
        if not self._page or not self.status.online:
            # 已掉线 → 重启再试
            self.stop()
            self.start(headless=False)
        try:
            self._page.goto(url, wait_until=wait_until, timeout=timeout)
            self.status.current_url = url
        except Exception as e:
            err = str(e).lower()
            # 检测 closed:Page.goto/Target page/browser has been closed
            closed_signals = ("has been closed", "target closed", "target page",
                              "browser has been closed", "context was closed")
            if any(s in err for s in closed_signals):
                # 重启 + 重试一次
                self.stop()
                self.start(headless=False)
                self._page.goto(url, wait_until=wait_until, timeout=timeout)
                self.status.current_url = url
                return
            raise

    def page(self) -> Optional[Page]:
        return self._page

    def fill_clipboard_paste(self, selector: str, text: str) -> bool:
        """填 prompt 的薄包装 — 内部走 fill_with_diagnostics 的 robust 路径,
        只返回成功 bool。失败原因依旧落到 self.status.error。

        历史上叫这个名字是因为最早实现是 clipboard paste,后来换 keyboard.type,
        现在又换成 React-safe value setter / execCommand insertText — 名字保留兼容。
        """
        diag = self.fill_with_diagnostics(selector, text)
        return bool(diag.get("ok"))

    def fill_with_diagnostics(self, selector_chain: str, text: str) -> dict:
        """诊断版填写。策略:
          1. 探每个 selector 的命中数(用于失败时定位)
          2. 抓命中元素详情(tag/id/可见/可编辑/placeholder)
          3. click 一下(触发任何 SPA 路由 + 上焦点),然后等导航/loadState 稳定
          4. **重新找元素**(click 触发了 / 跳转,原 ref 已失效)
          5. 用 React-safe 注入(value setter + dispatch input/change 事件 ||
             contenteditable 用 execCommand insertText)— 不走 keyboard.type,
             避免 prompt 里的 \\n 在 ChatGPT 类应用被当作 Enter 提前发送(分段发 bug)
          6. readback 验证写进去了
        返回的 dict 包含全部诊断字段供调用方落 log。
        """
        info = {
            "ok": False, "error": "",
            "url_before": "", "url_after": "", "navigated": False,
            "candidates": [], "chosen_selector": "", "chosen_info": {},
            "fill_method": "",
            "typed_value": "", "typed_length": 0,
        }
        page = self._page
        if not page:
            info["error"] = "page 不存在(session 未启动?)"
            return info
        try: info["url_before"] = page.url
        except Exception: pass

        selectors = [s.strip() for s in selector_chain.split(",") if s.strip()]

        def first_match():
            for sel in selectors:
                try:
                    if page.query_selector_all(sel):
                        return sel
                except Exception: continue
            return None

        # 1. 探每个 selector 的命中数
        for sel in selectors:
            try:
                count = len(page.query_selector_all(sel))
            except Exception:
                count = -1
            info["candidates"].append({"selector": sel[:60], "count": count})

        chosen = first_match()
        if not chosen:
            info["error"] = "所有 selector 在页面上都 0 命中"
            try: info["url_after"] = page.url
            except Exception: pass
            return info
        info["chosen_selector"] = chosen

        # 2. 元素详情(在 click 前抓,因为之后可能就跳到新页了)
        try:
            el = page.query_selector(chosen)
            if el:
                ci = {}
                try: ci["tag"] = el.evaluate("e => e.tagName")
                except Exception: ci["tag"] = "?"
                try: ci["id"] = (el.get_attribute("id") or "")[:40]
                except Exception: ci["id"] = ""
                try: ci["classes"] = (el.get_attribute("class") or "")[:80]
                except Exception: ci["classes"] = ""
                try: ci["placeholder"] = (el.get_attribute("placeholder") or "")[:60]
                except Exception: ci["placeholder"] = ""
                try: ci["visible"] = el.is_visible()
                except Exception: ci["visible"] = None
                try: ci["disabled"] = el.is_disabled()
                except Exception: ci["disabled"] = None
                try: ci["editable"] = el.is_editable()
                except Exception: ci["editable"] = None
                try:
                    bb = el.bounding_box() or {}
                    ci["bbox"] = {k: round(bb[k]) if isinstance(bb.get(k), (int, float)) else bb.get(k)
                                  for k in ("x", "y", "width", "height") if k in bb}
                except Exception: ci["bbox"] = {}
                info["chosen_info"] = ci
        except Exception as e:
            info["chosen_info"] = {"probe_error": str(e)}

        # 3. click → 等导航 → 重新找元素 → React-safe 注入
        try:
            el = page.wait_for_selector(chosen, timeout=5000)
            if not el:
                info["error"] = "wait_for_selector 返回 None(刚探到但 5s 内又消失了)"
                try: info["url_after"] = page.url
                except Exception: pass
                return info

            try:
                el.click(timeout=3000)
            except Exception as ce:
                info["error"] = f"click 失败: {ce}"
                try: info["url_after"] = page.url
                except Exception: pass
                return info

            # 等任何潜在的 SPA 路由/重渲染稳下来
            try: page.wait_for_load_state("domcontentloaded", timeout=3000)
            except Exception: pass
            try: page.wait_for_load_state("networkidle", timeout=2500)
            except Exception: pass
            try: info["url_after"] = page.url
            except Exception: pass
            info["navigated"] = bool(info["url_before"] and info["url_after"]
                                      and info["url_before"] != info["url_after"])

            # 关键:重新找元素(URL 变没变都重找一次最稳)
            new_chosen = first_match()
            if not new_chosen:
                info["error"] = "click 后所有 selector 都 0 命中"
                if info["navigated"]:
                    info["error"] += f"(且页面跳到了 {info['url_after']},新页 DOM 可能还在渲染)"
                return info
            if new_chosen != chosen:
                info["chosen_selector"] = f"{chosen} → {new_chosen}"
                chosen = new_chosen

            el = page.query_selector(chosen)
            if not el:
                info["error"] = "click 后 query_selector 返回 None"
                return info

            # 焦点
            try: el.focus()
            except Exception: pass

            # 4. React-safe 注入:
            #    - textarea / input: 用原生 value setter + dispatch input/change
            #      (React 用 fiber 跟踪 value,直接 .value = ... 不会触发 onChange,
            #       必须通过 prototype 上的 setter 才能写入 React 内部状态)
            #    - contenteditable: 用 execCommand('insertText'),
            #      这是 Slate / ProseMirror / Lexical 都听的标准编辑器 API
            injection_script = r"""
            (el, val) => {
              try {
                const tag = el.tagName;
                if (tag === 'TEXTAREA' || tag === 'INPUT') {
                  const proto = tag === 'TEXTAREA'
                    ? window.HTMLTextAreaElement.prototype
                    : window.HTMLInputElement.prototype;
                  const desc = Object.getOwnPropertyDescriptor(proto, 'value');
                  const setter = desc && desc.set;
                  if (setter) setter.call(el, val);
                  else el.value = val;
                  el.dispatchEvent(new Event('input', { bubbles: true, cancelable: true }));
                  el.dispatchEvent(new Event('change', { bubbles: true }));
                  return 'value_setter';
                }
                // contenteditable
                el.focus();
                const range = document.createRange();
                range.selectNodeContents(el);
                const sel = window.getSelection();
                sel.removeAllRanges();
                sel.addRange(range);
                // execCommand insertText 走浏览器内置 insertion pipeline,
                // 富文本编辑器(Slate/ProseMirror/Lexical/Quill)都监听这个
                const ok = document.execCommand && document.execCommand('insertText', false, val);
                if (ok) return 'contenteditable_execCommand';
                // 退化方案:直接 textContent + InputEvent
                el.textContent = val;
                el.dispatchEvent(new InputEvent('input', {
                  bubbles: true, inputType: 'insertText', data: val,
                }));
                return 'contenteditable_textContent';
              } catch (e) {
                return 'error:' + (e && e.message || String(e));
              }
            }
            """
            try:
                method = el.evaluate(injection_script, text)
            except Exception as ie:
                info["error"] = f"value 注入异常: {ie}"
                return info
            info["fill_method"] = method or ""
            if isinstance(method, str) and method.startswith("error:"):
                info["error"] = method
                return info

            # 5. readback 验证
            try:
                v = el.evaluate(
                    "e => (e.value !== undefined && e.value !== null) "
                    "? e.value : (e.textContent || '')"
                )
                info["typed_value"] = (v or "")[:200]
                info["typed_length"] = len(v or "")
            except Exception as re_:
                info.setdefault("chosen_info", {})["readback_error"] = str(re_)

            # 容差 90%(部分编辑器会把 \r\n 合并成 \n 之类)
            info["ok"] = info["typed_length"] >= max(1, int(len(text) * 0.9))
            if not info["ok"] and not info["error"]:
                info["error"] = (
                    f"注入完成 ({info['fill_method']}) 但 readback 只有 "
                    f"{info['typed_length']}/{len(text)} 字 — 元素可能是只读或被框架反写了"
                )
        except Exception as e:
            info["error"] = f"诊断 fill 过程异常: {e}"
            try: info["url_after"] = page.url
            except Exception: pass

        self.status.error = info["error"]
        return info

    def snapshot_page(self, label: str = "snapshot") -> dict:
        """生成一份页面调试快照(截图 + HTML + DOM probe)写到 ~/.doubao-studio/debug/<label>_<ts>/。

        返回 dict 含 dir / files / url / title / probe(textareas/buttons/file_inputs/error_banners)。
        调用方可以把 dir 路径报给用户让其打开。
        """
        info = {
            "label": label, "url": "", "title": "",
            "html_len": 0, "files": [], "error": "", "dir": "",
        }
        if not self._page:
            info["error"] = "page 不存在"
            return info
        try:
            info["url"] = self._page.url
        except Exception: pass
        try:
            info["title"] = self._page.title()
        except Exception: pass

        import time as _t
        debug_dir = ST.APP_DIR / "debug" / f"{label}_{int(_t.time())}"
        try:
            debug_dir.mkdir(parents=True, exist_ok=True)
            info["dir"] = str(debug_dir)
        except Exception as e:
            info["error"] = f"建调试目录失败: {e}"
            return info

        # 1. 截图(不强制 full_page,避免长页 OOM)
        try:
            png = debug_dir / "screenshot.png"
            self._page.screenshot(path=str(png), full_page=False)
            info["files"].append(str(png))
        except Exception as e:
            info["screenshot_error"] = str(e)

        # 2. HTML dump(完整 DOM)
        try:
            html = self._page.content()
            info["html_len"] = len(html)
            html_path = debug_dir / "page.html"
            html_path.write_text(html, encoding="utf-8")
            info["files"].append(str(html_path))
        except Exception as e:
            info["html_error"] = str(e)

        # 3. 在页面里跑一段轻量 DOM probe,看几个关键控件的状态
        probe_js = r"""
        (() => {
          const out = {
            input_textareas: 0,
            input_editables: 0,
            visible_textareas: [],
            visible_editables: [],
            send_buttons: [],
            file_inputs: 0,
            error_banners: [],
            visible_login_hints: [],
          };
          document.querySelectorAll('textarea').forEach(t => {
            out.input_textareas++;
            const r = t.getBoundingClientRect();
            if (r.width >= 80 && r.height >= 20 && t.offsetParent) {
              out.visible_textareas.push({
                id: t.id || '', name: t.name || '',
                placeholder: (t.placeholder || '').slice(0,60),
                cls: (t.className || '').toString().slice(0,80),
                disabled: t.disabled, readonly: t.readOnly,
                w: Math.round(r.width), h: Math.round(r.height),
              });
            }
          });
          document.querySelectorAll('[contenteditable="true"]').forEach(t => {
            out.input_editables++;
            const r = t.getBoundingClientRect();
            if (r.width >= 80 && r.height >= 20 && t.offsetParent) {
              out.visible_editables.push({
                tag: t.tagName, id: t.id || '',
                cls: (t.className || '').toString().slice(0,80),
                w: Math.round(r.width), h: Math.round(r.height),
              });
            }
          });
          out.file_inputs = document.querySelectorAll('input[type="file"]').length;
          document.querySelectorAll('button, [role="button"]').forEach(b => {
            const text = (b.innerText || '').trim().slice(0, 30);
            const aria = b.getAttribute('aria-label') || '';
            const testid = b.getAttribute('data-testid') || '';
            if (/send|发送|生成|提交|submit/i.test(text + aria + testid)) {
              out.send_buttons.push({
                text, aria, testid,
                disabled: b.disabled || b.getAttribute('aria-disabled') === 'true',
              });
            }
          });
          document.querySelectorAll('[class*="error"],[class*="banner"],[role="alert"]').forEach(e => {
            if (!e.offsetParent) return;
            const t = (e.innerText || '').trim().slice(0, 100);
            if (t) out.error_banners.push(t);
          });
          out.error_banners = [...new Set(out.error_banners)].slice(0, 5);
          document.querySelectorAll('button, a').forEach(e => {
            const t = (e.innerText || '').trim();
            if (/^(登录|Login|Sign in|Sign In)$/i.test(t) && e.offsetParent) {
              out.visible_login_hints.push(t);
            }
          });
          out.visible_login_hints = [...new Set(out.visible_login_hints)].slice(0, 3);
          return out;
        })()
        """
        try:
            probe = self._page.evaluate(probe_js)
            info["probe"] = probe
            import json as _j
            (debug_dir / "probe.json").write_text(
                _j.dumps(probe, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            info["files"].append(str(debug_dir / "probe.json"))
        except Exception as e:
            info["probe_error"] = str(e)

        # 4. 总览写个 summary.txt 方便用户直接打开看
        try:
            lines = [
                f"label: {label}",
                f"url: {info['url']}",
                f"title: {info['title']}",
                f"html_len: {info['html_len']}",
            ]
            p = info.get("probe", {})
            if p:
                lines.append("--- DOM Probe ---")
                lines.append(f"  textareas:        {p.get('input_textareas')} (visible: {len(p.get('visible_textareas') or [])})")
                lines.append(f"  contenteditables: {p.get('input_editables')} (visible: {len(p.get('visible_editables') or [])})")
                lines.append(f"  file inputs:      {p.get('file_inputs')}")
                lines.append(f"  send buttons:     {len(p.get('send_buttons') or [])}")
                if p.get("send_buttons"):
                    for b in p["send_buttons"][:5]:
                        lines.append(f"    - {b!r}")
                if p.get("visible_textareas"):
                    lines.append("  visible textareas:")
                    for t in p["visible_textareas"][:5]:
                        lines.append(f"    - {t!r}")
                if p.get("error_banners"):
                    lines.append(f"  error banners:    {p['error_banners']}")
                if p.get("visible_login_hints"):
                    lines.append(f"  login buttons visible: {p['visible_login_hints']}")
            (debug_dir / "summary.txt").write_text("\n".join(lines), encoding="utf-8")
            info["files"].append(str(debug_dir / "summary.txt"))
        except Exception:
            pass
        return info

    def click(self, selector: str) -> bool:
        if not self._page: return False
        try:
            self._page.click(selector, timeout=5000)
            return True
        except Exception:
            return False

    def set_input_files(self, selector: str, files) -> bool:
        """把文件注入到 file input(用于 TXT 附件上传、参考图上传)。

        files: 单个 str/Path 或列表
        """
        if not self._page: return False
        if not isinstance(files, (list, tuple)):
            files = [files]
        paths = [str(p) for p in files]
        # 多 selector 用逗号拆,挨个试
        for sel in [s.strip() for s in selector.split(',') if s.strip()]:
            try:
                # set_input_files 对 hidden input 也工作
                self._page.set_input_files(sel, paths, timeout=5000)
                return True
            except Exception:
                continue
        return False

    def upload_txt(self, text: str, file_name: str = "script.txt",
                   upload_selector: str = "", use_bom: bool = True) -> bool:
        """把文本写成 .txt 文件 + 注入到 file input。

        - use_bom=True (默认):头部加 \\uFEFF (UTF-8 BOM),给 GPT 镜像/ChatGPT 用,防中文乱码
        - use_bom=False:豆包/即梦 等国产平台,原生吃 UTF-8 无 BOM
        - 临时文件存到 downloads_dir/_uploads/
        - 调 set_input_files 注入
        """
        if not self._page: return False
        upload_root = self.downloads_dir / "_uploads"
        upload_root.mkdir(parents=True, exist_ok=True)
        target = upload_root / file_name
        try:
            prefix = "\ufeff" if use_bom else ""
            target.write_text(prefix + text, encoding="utf-8")
        except Exception:
            return False
        if not upload_selector:
            upload_selector = (
                '#upload-files, '
                'input[type="file"][multiple], '
                'input[type="file"]'
            )
        return self.set_input_files(upload_selector, [target])

    def is_logged_in(self, cookie_names: list) -> bool:
        """双层检测:cookie 匹配 > DOM heuristic 兜底 > 乐观默认。

        cookie_names 经验值不一定准(很多国内镜像用 token/access_token/jwt 等),
        所以单层硬匹配会误判。这里:
          1. cookie 命中任一名字 → 已登录 ✓
          2. 没命中但 DOM 里没有可见"登录"按钮 → 视为已登录(乐观)
          3. DOM 里有可见登录按钮 → 真未登录
        宁可放假阳性进任务跑,也不要阻塞 60 秒等用户。
        """
        if not self._ctx: return False
        try:
            # Layer 1: cookie 名匹配
            if cookie_names:
                try:
                    cookies = self._ctx.cookies()
                    names = {c.get("name", "") for c in cookies}
                    # 用户实测过的精确名 + 通用候选
                    extended = list(cookie_names) + [
                        "token", "access_token", "auth_token", "jwt", "Authorization",
                        "userToken", "user_token", "auth", "_session",
                    ]
                    if any(c in names for c in extended):
                        self.status.logged_in = True
                        return True
                    # cookie 数量 >= 5 (登录态通常会带一堆 cookies)
                    # 这是个 weak signal,只在有 page 时才用
                    has_many_cookies = len(cookies) >= 5
                except Exception:
                    has_many_cookies = False
            else:
                has_many_cookies = False

            # Layer 2: DOM — 没有可见"登录/Login/Sign in"按钮 = 视为已登录
            page = self._page
            if not page:
                # 没法检测,但若 cookies 够多就乐观
                self.status.logged_in = has_many_cookies
                return has_many_cookies

            try:
                for selector in [
                    'button:has-text("登录"):visible',
                    'button:has-text("Login"):visible',
                    'button:has-text("Sign in"):visible',
                    'button:has-text("Sign In"):visible',
                    'a:has-text("登录"):visible',
                    'a:has-text("Login"):visible',
                    '[data-testid*="login-button"]:visible',
                ]:
                    el = page.query_selector(selector)
                    if el:
                        try:
                            if el.is_visible():
                                return False
                        except Exception:
                            pass
                # 没找到登录按钮 → 已登录
                self.status.logged_in = True
                return True
            except Exception:
                # DOM 检测异常 → 乐观假设(已经走到这步说明浏览器在跑)
                self.status.logged_in = True
                return True
        except Exception:
            return False


# ---- 全局会话池 ----
class SessionPool:
    """每个账号最多一个会话。"""
    def __init__(self):
        self._sessions: Dict[str, AccountSession] = {}
        self._lock = threading.RLock()

    def get_or_create(self, account: Account) -> AccountSession:
        with self._lock:
            if account.id not in self._sessions:
                self._sessions[account.id] = AccountSession(account)
            return self._sessions[account.id]

    def get(self, acc_id: str) -> Optional[AccountSession]:
        return self._sessions.get(acc_id)

    def close_all(self):
        with self._lock:
            for s in self._sessions.values():
                try: s.stop()
                except Exception: pass
            self._sessions.clear()


_pool: Optional[SessionPool] = None

def get_pool() -> SessionPool:
    global _pool
    if _pool is None:
        _pool = SessionPool()
    return _pool
