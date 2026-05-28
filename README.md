# 豆包 Studio

桌面版多账号豆包管理工具,集成 [doubao-nomark](https://github.com/ihmily/doubao-nomark) 实现无水印图片/视频提取。

## 特性

- **真账号隔离**:每个账号一个 `QWebEngineProfile`,cookies / localStorage / cache 完全独立
- **直接调库**:`import doubao_parser` 直接调,不需要起 HTTP 服务
- **持久化**:账号、提示词存 `~/.doubao-studio/*.json`,profile 数据存 `~/.doubao-studio/profiles/<account_id>/`
- **可降级**:未装 doubao-nomark 时自动用 mock 数据演示;未装 PySide6-WebEngine 时显示占位说明
- **提示词快捷**:输入框上方可点击填充,右键删除,可自定义新增

## 安装

```bash
# 1. 基础 GUI
pip install PySide6

# 2. (可选)装真实解析库
git clone https://github.com/ihmily/doubao-nomark
cd doubao-nomark && pip install -e .

# 3. 运行
python doubao_studio.py
```

## 文件结构

```
~/.doubao-studio/
├── accounts.json          # 账号列表
├── prompts.json           # 提示词
├── media/                 # 下载的媒体文件(预留)
└── profiles/
    ├── acc-1/
    │   ├── storage/       # cookies, localStorage, IndexedDB
    │   └── cache/         # HTTP cache
    ├── acc-2/...
    └── acc-3/...
```

每个 profile 目录由 Qt 自动维护,删除即清空该账号所有登录态。

## 截图功能对照

| 界面元素     | 对应组件                | 文件位置                |
| ------------ | ----------------------- | ----------------------- |
| 账号管理(左) | `AccountPanel`          | 增删改账号,在线状态     |
| 豆包工作区(中) | `WorkspacePanel`        | QWebEngineView 真嵌入   |
| 媒体列表(右) | `MediaPanel`            | 粘贴链接 → 解析 → 卡片  |
| 任务日志(底) | `LogBar`                | 折叠式日志,模式标识      |

## 切换 API 模式

媒体列表右上角齿轮 ⚙ 展开配置面板:
- **Mock 数据**:本地假响应,用于演示
- **真实库**:直接调用 `doubao_parser.image.doubao_image_parse` / `video.doubao_video_parse`

无需任何 HTTP 服务,函数调用是异步的,在 `QThread` + `asyncio.run()` 里跑,不阻塞 UI。

## 关于反检测

`QWebEngineProfile` 只解决了**存储层隔离**(cookies/localStorage),如果豆包用了 canvas/字体/WebGL 指纹,
多账号还是可能被关联。需要的话可以:

- 给每个 profile 设不同的 UA(代码里 `setHttpUserAgent`)
- 加代理:`profile.setUrlRequestInterceptor(...)` 重写请求
- 更进一步要用反指纹方案(超出本工具范围)
