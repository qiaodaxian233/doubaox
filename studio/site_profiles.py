"""
站点 DOM 配置。每个 backend 对应一份 SiteProfile,worker 按这个配置驱动 Playwright。

注意:
- SPA 网站的 DOM 选择器随版本而变,这里的值是"探查得到的最佳猜测"
- 用户首次跑某个 backend 失败时,需要打开 Chromium DevTools 重新探查,
  把新选择器贴到 ~/.doubao-studio/site_profiles.json 覆盖即可
- 自动化失败会自动退化到「半自动」模式:浏览器打开站点 + 自动填 prompt + 等用户点生成 + 监听 Downloads
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import List, Dict
import json
from pathlib import Path


@dataclass
class SiteProfile:
    """单个站点的 DOM 操作配置。"""
    backend_id: str
    home_url: str
    # 登录态信号(cookie 名包含其一即视为已登录)
    auth_cookies: List[str] = field(default_factory=list)
    # 入口选择器 — 进入"生图/生视频"页面(部分站点首页就是)
    image_entry: str = ""        # 点击进入图片生成
    video_entry: str = ""        # 点击进入视频生成
    # 操作元素
    input_box: str = ""          # prompt 输入框
    upload_btn: str = ""         # 上传参考图按钮
    send_btn: str = ""           # 发送/生成按钮
    # 检测产出
    result_selector: str = ""    # 生成结果消息的容器
    result_image_in: str = ""    # 容器内的图片元素
    result_video_in: str = ""    # 容器内的视频元素
    download_btn: str = ""       # 下载按钮(若有原生下载)
    # 配额检测(可选)
    quota_selector: str = ""     # 页面上显示剩余额度的位置
    # 行为标志
    needs_login: bool = True
    supports_image: bool = False
    supports_video: bool = False


# === 默认配置(provisional;实际 DOM 需用 DevTools 探查) ===
# 三个 backend 的初版配置。配置错没事 — worker 会退化到半自动模式。

DEFAULT_PROFILES: Dict[str, SiteProfile] = {
    "gpt-mirror": SiteProfile(
        backend_id="gpt-mirror",
        home_url="https://gpt.aimonkey.plus/",
        auth_cookies=["session", "session_token", "_gpt_session"],
        # 这些选择器是猜的,SPA 用 DevTools 探查
        input_box='textarea, [contenteditable="true"]',
        upload_btn='input[type="file"]',
        send_btn='button[type="submit"], button:has(svg)',
        result_selector='[class*="message"]:last-child, [class*="assistant"]:last-child',
        result_image_in='img[src*="aimonkey"], img[src*="openai"], img[src^="http"]',
        supports_image=True,
        supports_video=False,
    ),
    "jimeng": SiteProfile(
        backend_id="jimeng",
        home_url="https://jimeng.jianying.com/",
        auth_cookies=["sessionid", "sid_tt", "uid_tt"],
        input_box='textarea',
        send_btn='button:has-text("生成")',
        result_image_in='img[src*="jimeng"], img[src*="ssl.bytedance"]',
        supports_image=True,
        supports_video=True,         # 即梦也能生视频
    ),
    "doubao": SiteProfile(
        backend_id="doubao",
        home_url="https://www.doubao.com/chat",
        auth_cookies=["sessionid", "sid_guard", "sid_tt"],
        input_box='textarea[data-testid="chat_input_input"], textarea',
        upload_btn='button[data-testid*="upload"], input[type="file"]',
        send_btn='button[data-testid="chat_input_send_button"]',
        result_selector='[data-testid*="message"][data-testid*="assistant"]',
        result_video_in='video',
        result_image_in='img[src*="lf3"], img[src*="byteimg"]',
        quota_selector='[data-testid*="quota"], [class*="quota"]',
        supports_image=True,
        supports_video=True,
    ),
}


def load_profiles(custom_file: Path = None) -> Dict[str, SiteProfile]:
    """加载 profiles,本地有 override 则用 override。"""
    profiles = {k: SiteProfile(**asdict(v)) for k, v in DEFAULT_PROFILES.items()}
    if custom_file and custom_file.exists():
        try:
            data = json.loads(custom_file.read_text(encoding="utf-8"))
            for backend_id, override in data.items():
                if backend_id in profiles:
                    for k, v in override.items():
                        if hasattr(profiles[backend_id], k):
                            setattr(profiles[backend_id], k, v)
                else:
                    profiles[backend_id] = SiteProfile(backend_id=backend_id, **override)
        except Exception as e:
            print(f"加载自定义 site_profiles 失败: {e}")
    return profiles


def save_profiles(profiles: Dict[str, SiteProfile], path: Path):
    data = {k: asdict(v) for k, v in profiles.items()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
