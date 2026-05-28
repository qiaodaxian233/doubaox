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
    # TXT 上传(用户反馈:GPT 镜像偶尔吃不下大段 prompt,得改用 TXT 附件)
    # 字符阈值:prompt 超过这个长度 → 自动改用 TXT 附件 + 短指令
    # 设为 0 = 永不走 TXT;默认 4000 对中文剧本够用
    txt_upload_threshold: int = 4000
    # TXT 附件触发后的占位指令(写到输入框,告诉 GPT 看 TXT 附件)
    txt_upload_instruction: str = "请严格按附件 TXT 里的内容执行任务。"
    # 生成完成的文本标志(中文 GPT 镜像通常出 "图片已创建" 三字)
    # 用 || 分隔多个候选(任一出现即视为完成)
    completion_text_marker: str = ""


# === 默认配置 ===
# GPT 镜像 selectors 来源:乔大仙 v6.3.0 user script(实战验证过)
# 即梦 / 豆包 仍是猜测,首次跑失败时用 DevTools 探查后写到
# ~/.doubao-studio/site_profiles.json 覆盖即可。

DEFAULT_PROFILES: Dict[str, SiteProfile] = {
    "gpt-mirror": SiteProfile(
        backend_id="gpt-mirror",
        home_url="https://gpt.aimonkey.plus/",
        auth_cookies=["session", "__Secure-next-auth.session-token", "cf_clearance"],
        # 多 selector fallback chain — 任何一个命中就行
        # 输入框:#prompt-textarea 是 ChatGPT 标准,后面是国内镜像变种
        input_box=(
            '#prompt-textarea, '
            'textarea[data-id="root"], '
            '[contenteditable="true"][data-testid], '
            '[contenteditable="true"], '
            'textarea'
        ),
        # 文件上传 input — GPT 用 #upload-files,镜像各种
        upload_btn=(
            '#upload-files, '
            'input[type="file"][multiple], '
            'input[type="file"]:not([accept]), '
            'input[type="file"][accept*="image"], '
            'input[type="file"]'
        ),
        # 发送按钮多种变种
        send_btn=(
            '[data-testid="send-button"], '
            'button[aria-label="Send message"], '
            'button[aria-label="发送消息"], '
            'button[aria-label="Send"], '
            'button[data-testid="fruitjuice-send-button"]'
        ),
        # 生成完成标志:出现 assistant 消息块(role-message-author-role=assistant)
        result_selector='[data-message-author-role="assistant"]',
        # 生成图特征 — 三个 OpenAI CDN 域名(乔大仙 v6.3.0 验证)
        result_image_in=(
            'img[src*="oaidalleapiprodscus.blob.core.windows.net"], '
            'img[src*="files.oaiusercontent.com"], '
            'img[src*="oaistatics.com"], '
            'img[src*="aimonkey"], '
            'img[src*="openai"]'
        ),
        # 强信号:中文 GPT 镜像生成完成时会出 "图片已创建"
        completion_text_marker="图片已创建||Image created||image generated",
        supports_image=True,
        supports_video=False,
    ),
    "jimeng": SiteProfile(
        backend_id="jimeng",
        home_url="https://jimeng.jianying.com/",
        auth_cookies=["sessionid", "sid_tt", "uid_tt"],
        input_box='textarea, [contenteditable="true"]',
        upload_btn='input[type="file"][accept*="image"], input[type="file"]',
        send_btn='button:has-text("生成"), button[class*="generate"]',
        result_selector='[class*="result"], [class*="output"]',
        result_image_in='img[src*="jimeng"], img[src*="ssl.bytedance"], img[src*="byteimg"]',
        result_video_in='video[src*="jimeng"], video[src*="byteimg"]',
        supports_image=True,
        supports_video=True,
    ),
    "doubao": SiteProfile(
        backend_id="doubao",
        home_url="https://www.doubao.com/chat",
        auth_cookies=["sessionid", "sid_guard", "sid_tt"],
        input_box='textarea[data-testid="chat_input_input"], textarea',
        upload_btn=(
            'input[type="file"][multiple], '
            'input[type="file"]:not([accept]), '
            'button[data-testid*="upload"], '
            'input[type="file"]'
        ),
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
