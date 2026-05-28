# 豆包 Studio (v2 · Playwright 重构)

桌面版多账号豆包管理工具,集成 [doubao-nomark](https://github.com/ihmily/doubao-nomark) 无水印图片/视频提取。

> **v2 架构变更**:从 QWebEngineView 全面切换到 **Playwright + 真实 Chromium**。理由:
> - QtWebEngine 容易被站点反爬识别;真 Chrome 反检测能力强很多
> - 真 cookies = 真登录状态,不再靠猜 cookie 名
> - `launch_persistent_context(user_data_dir)` 才是真正的"独立缓存账号池"
> - `page.evaluate()` 比 JS 注入稳得多
>
> 这套模式参考自同作者 [novel_ai](https://github.com/qiaodaxian233/novel_ai) 项目验证过的成功打法。

## 特性

- **真账号隔离** — 每账号一个 `~/.doubao-studio/profiles/<id>/chrome_data/`,Playwright 用 `launch_persistent_context` 挂载,完整 Chrome cookies/IDB/cache
- **真登录检测** — 每 2s 跑一次 `context.cookies()`,命中 `sessionid` / `sid_guard` 才置为已登录,所以"已登录" = 真的登录了
- **页面媒体自动识别** — Playwright `page.evaluate(SCAN_JS)` 每 4s 扫一次 `<img>` / `<video>`,匹配豆包 CDN,自动加入媒体列表,打"页面"标签
- **分享链接自动解析** — webview URL 命中 `/thread/...` / `video-sharing` 时,自动 import `doubao_parser` 拿无水印版本
- **一键发送到豆包** — 在 PyQt UI 里写好提示词 → 点「▶ 发送到豆包」→ Playwright 自动在真 Chrome 里 fill + click,跟 novel_ai 同款打法
- **截图预览** — 中间栏每 2.5s 抓一次 JPEG 显示,知道 Chrome 里正在发生什么
- **SITE_PROFILES** — 选择器集中在一个 dict 里,豆包 DOM 改了改这里就行
- **持久化** — 账号、提示词存 `~/.doubao-studio/*.json`
- **降级** — 没装 Playwright / doubao-nomark 都能跑,UI 完整,提示安装命令

## 安装

```bash
# 1. GUI 基础
pip install PySide6

# 2. Playwright(必须)+ 下载 Chromium 内核
pip install playwright
python -m playwright install chromium
# 系统已装 Chrome 的也可以,Playwright 会自动选,不用再下

# 3. (可选)装真实解析库
git clone https://github.com/ihmily/doubao-nomark
cd doubao-nomark && pip install -e .

# 4. 运行
python doubao_studio.py
```

## 使用流程

1. 左侧选一个账号(默认有3个)
2. 中间栏点右上「🚀 启动浏览器」→ Chromium 窗口弹出
3. **首次手动登录豆包**(在弹出的 Chrome 窗口里),登录态会持久化
4. 登录成功后:左侧账号卡片自动从"未登录"变成"已登录"(绿圆点),底部日志栏会打印 `登录确认 · 命中 sessionid`
5. 浏览豆包对话时,右侧媒体列表会自动出现页面上的图片/视频(打"页面"标签)
6. 复制一条分享链接(`/thread/...` 或 `video-sharing?...`)在 Chrome 里访问,自动触发 doubao-nomark 拿无水印版本(打"无水印"橙色标签)
7. 想发提示词:在中间底部输入框写,点「▶ 发送到豆包」,Playwright 在 Chrome 里自动填+点发送

## 文件结构

```
~/.doubao-studio/
├── accounts.json          # 账号列表
├── prompts.json           # 提示词
├── media/                 # 下载的媒体文件
└── profiles/
    └── acc-1/
        └── chrome_data/   # 完整 Chrome user-data-dir (cookies/cache/IDB)
    └── acc-2/...
    └── acc-3/...
```

删某个账号的 chrome_data 目录 = 该账号登出 + 清空所有缓存。

## SITE_PROFILES 调参

如果豆包 DOM 改了,发送提示词或抓媒体出问题,改 `doubao_studio.py` 顶部:

```python
SITE_PROFILES = {
    "doubao.com": {
        "input":    'textarea[data-testid="chat_input_input"], textarea',  # 输入框 selector
        "send_btn": 'button[data-testid="chat_input_send_button"], button[type="submit"]',
        "response": '[data-testid*="message"][data-testid*="assistant"], .markdown-body',
        # ...
    },
}

# DOM 扫描的 URL 匹配:漏抓时把豆包资源域名加进 PAGE_MEDIA_SCAN_JS 的正则
```

跟 novel_ai 的 SITE_PROFILES 一个套路,改 selector 不动逻辑。F12 在豆包页面看 DOM 抄选择器就行。

## 登录 cookie 调参

如果实测发现登录成功但状态没变,F12 → Application → Cookies → www.doubao.com,把真实鉴权 cookie 名加到 `AUTH_PRIMARY`:

```python
AUTH_PRIMARY = {"sessionid", "sid_guard"}  # 出现其一即判定已登录
```

底部「任务历史」会打印每次的 cookie 检测结果。

## 关于反检测

`launch_persistent_context` + `--disable-blink-features=AutomationControlled` 已经能过大部分简单反爬。如果遇到豆包做了更深的指纹检测:
- 给每个账号 profile 设不同 UA(在 PlaywrightWorker._async_main 里加 `user_agent=...`)
- 加代理:Playwright 启动参数 `proxy={"server": "..."}`
- 引入 [`playwright-stealth`](https://github.com/AtuboDad/playwright_stealth) 处理 navigator/canvas/WebGL 指纹

## 跟 v1 (QtWebEngine 版) 的区别

| 能力             | v1 QtWebEngine | v2 Playwright |
|------------------|----------------|---------------|
| 登录检测准确性    | 靠猜 cookie 名      | `context.cookies()` 真值 |
| 反爬识别         | 容易被识别          | 真 Chrome,过大部分检测 |
| 页面媒体抓取     | 注入 JS,易失效     | `page.evaluate()` 稳定 |
| 自动发送提示词   | 无               | ✓ SITE_PROFILES 驱动 |
| 中间栏          | 嵌入 webview       | 截图预览 + Chrome 独立窗口 |
| 账号 user-data-dir | Qt-managed     | 完整 Chrome 标准目录 |

v1 在 git 历史里还能找到,需要嵌入式 webview 那种 UX 就回退。
