"""
DoubaoStudio v3 数据模型 —— 短剧工厂

短剧 = Project
  ├── Characters   (角色库,固定主角形象)
  ├── Scenes       (场景库,固定环境/光照)
  ├── Props        (道具库,可被 {{Image N}} 引用)
  └── Episodes     (集)
      ├── Shots    (分镜,每镜 1-3s,6维度+衔接锚点)
      └── Segments (10s 视频片段 = 多镜打包,豆包硬上限 10s)
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from datetime import datetime
import time, uuid


def _gid(prefix: str) -> str:
    return f"{prefix}-{int(time.time()*1000)}-{uuid.uuid4().hex[:4]}"


@dataclass
class Project:
    id: str = field(default_factory=lambda: _gid("proj"))
    name: str = "未命名项目"
    style: str = ""                # 国风仙侠 / 都市言情 / 校园 / 真人剧 / 仿真
    aspect_ratio: str = "9:16"     # 9:16 竖屏短剧 / 16:9 横屏
    target_duration: int = 60      # 成片秒数目标
    description: str = ""
    cover_image: str = ""          # 相对 assets/ 路径
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass
class Character:
    """主角 / 配角。结构化提示词模板 = 蒙哥 AI 模板"""
    id: str = field(default_factory=lambda: _gid("char"))
    project_id: str = ""
    name: str = ""
    role: str = "主角"             # 主角 / 配角 / 反派 / 群演
    age: str = ""
    gender: str = ""               # 男 / 女 / 其他

    # 结构化五官(锁定一致性)
    face_shape: str = ""           # 圆脸/方脸/瓜子脸…
    eye_details: str = ""
    nose_shape: str = ""
    lip_shape: str = ""
    eyebrow_style: str = ""
    jawline: str = ""
    skin_details: str = ""
    hair: str = ""                 # 发型 + 发色
    body: str = ""                 # 身高体态

    # 穿搭(可多套)
    outfits: List[Dict[str, str]] = field(default_factory=list)
    # 每套 = {"name": "日常装", "top": "...", "bottom": "...", "footwear": "..."}

    style_lock: str = "永久锁定五官脸型、发型体态、人体比例、核心特征不变"
    visual_style: str = "2D动画风格"   # 或 "超写实仿真人风格" / "3D超写实风格"

    reference_image: str = ""      # 主参考图 (相对 assets/ 路径)
    extra_images: List[str] = field(default_factory=list)  # 三视图等
    placeholder: str = ""          # 在 prompt 里的引用名,例如 {{Image 1}} / {{Portrait 1}}
    notes: str = ""


@dataclass
class Scene:
    """场景。配合 4 段固定描述保证跨镜一致性。"""
    id: str = field(default_factory=lambda: _gid("scene"))
    project_id: str = ""
    name: str = ""
    aspect_ratio: str = "16:9"
    visual_style: str = "3D超写实风格"

    asset_description: str = ""        # 整体描述
    fixed_environment: str = ""        # 固定环境(物体位置)
    fixed_lighting: str = ""           # 固定光照
    fixed_background: str = ""         # 固定背景
    reference_image: str = ""
    placeholder: str = ""              # 例如 {{Scene 1}}
    notes: str = ""


@dataclass
class Prop:
    """道具。可在分镜里通过 {{Image N}} 引用以保持视觉一致。"""
    id: str = field(default_factory=lambda: _gid("prop"))
    project_id: str = ""
    name: str = ""
    description: str = ""
    reference_image: str = ""
    placeholder: str = ""              # {{Image 3}} / {{Prop 1}}
    notes: str = ""


@dataclass
class Shot:
    """分镜 = 一镜。15s 视频通常 5-8 镜,10s 视频通常 3-5 镜。"""
    id: str = field(default_factory=lambda: _gid("shot"))
    episode_id: str = ""
    number: int = 1

    # 时间
    start_time: float = 0.0
    duration: float = 2.5     # 默认 2.5s → 4 镜/10s,符合 seedance 节奏(3-5 镜/10s 推荐)

    # 内容引用
    scene_id: str = ""
    character_ids: List[str] = field(default_factory=list)
    prop_ids: List[str] = field(default_factory=list)

    # 6 维度(参考蒙哥模板)
    shot_size: str = "中景"             # 远景/中景/近景/特写/大特写/过肩/反打 等
    camera_movement: str = "固定"       # 固定/推/拉/摇/移/跟/旋转/俯仰
    visual_style_note: str = ""         # 视觉风格细节
    camera_params: str = ""             # 焦段/光圈/ISO,例 "50mm f/2.8 ISO 400"
    action: str = ""                    # 动作设计
    lighting: str = ""                  # 光影设计
    sound: str = ""                     # 音效设计

    # 衔接锚点(关键!跨镜动作连贯性)
    transition_anchor: str = ""         # "本镜结束姿态描述"
    transition_duration: float = 0.3    # 与下一镜的叠化秒数

    # 台词
    dialogue: str = ""

    # prompts(可自动生成,也可手写覆盖)
    image_prompt_custom: str = ""
    video_prompt_custom: str = ""

    # 生成产物
    generated_image: str = ""           # 本镜静帧参考
    generated_video: str = ""           # 本镜独立小视频(可选)


@dataclass
class Episode:
    """一集。包含分镜表 + 视频片段表。"""
    id: str = field(default_factory=lambda: _gid("ep"))
    project_id: str = ""
    number: int = 1
    title: str = ""
    synopsis: str = ""                  # 剧情简介
    emotional_arc: str = ""             # 情绪曲线:平静→惊愕→恐慌→决绝
    script: str = ""                    # 剧本原文(markdown)
    shots: List[Shot] = field(default_factory=list)
    segments: List["VideoSegment"] = field(default_factory=list)


@dataclass
class VideoSegment:
    """10s 视频片段 = 多镜打包。豆包硬上限 10s。
    
    分镜密度建议(单段 10s):
      3 镜 / 3.3s 每镜 — 长镜头、慢节奏
      4 镜 / 2.5s 每镜 — 标准节奏 (推荐默认)
      5 镜 / 2.0s 每镜 — 快节奏、动作戏
      6 镜 / 1.7s 每镜 — 极限,模型会有压力
      7+ 镜       — 太赶,模型会自动合并/丢镜,强烈建议拆分
    """
    id: str = field(default_factory=lambda: _gid("seg"))
    episode_id: str = ""
    number: int = 1
    shot_ids: List[str] = field(default_factory=list)   # 这段包含哪些镜

    storyboard_image: str = ""          # 分镜板大图(给 seedance 当 master bible)
    storyboard_prompt: str = ""         # 生成分镜板大图所用的 prompt
    storyboard_backend: str = "gpt-mirror"  # 用哪个 backend 生成分镜板 (gpt-mirror / jimeng / manual)
    video_prompt: str = ""              # 生成视频用的 prompt (通常很短)
    video_backend: str = "doubao"       # 用哪个账号生成视频

    generated_video: str = ""           # 最终视频路径
    generated_by_account: str = ""      # 哪个账号生成的
    generated_at: float = 0.0
    duration: float = 10.0              # 硬上限 10s

    def shot_count(self) -> int:
        return len(self.shot_ids)

    def density_status(self) -> str:
        """返回 'ok' / 'tight' / 'overflow' """
        n = self.shot_count()
        if n == 0: return "empty"
        if n <= 5: return "ok"
        if n == 6: return "tight"
        return "overflow"


# ---- 多 Backend 抽象 ----
# v3 区分两类生成后端:
#   image-gen  (GPT 镜像站 / 即梦):生成角色三视图、道具图、分镜板大图
#   video-gen  (豆包 seedance):生成 10s 视频片段
# 每类下可有多个账号(多账号 = 跨账号轮转配额)。

BACKEND_IMAGE  = "image"
BACKEND_VIDEO  = "video"


@dataclass
class GenerationBackend:
    """生成后端配置。一个 backend 可挂多个 account(多账号轮转)。"""
    id: str
    name: str
    kind: str = BACKEND_IMAGE           # image / video
    url: str = ""                       # 入口 URL
    icon: str = "🤖"
    notes: str = ""                     # 登录方式说明等
    enabled: bool = True


@dataclass
class Account:
    """账号 = 算力槽。豆包每账号每天 5 个视频额度。"""
    id: str
    name: str
    backend_id: str = "doubao"          # 属于哪个 backend
    color: str = "#1e3a8a"
    online: bool = False
    status: str = "未启动"
    daily_quota_total: int = 5          # 每日额度(图片站可设大数或 0=不限)
    daily_quota_used: int = 0
    quota_reset_date: str = ""          # YYYY-MM-DD
    # 兼容旧版字段
    video_quota_total: int = 5
    video_quota_used: int = 0

    def remaining(self) -> int:
        self._maybe_reset()
        if self.is_unlimited(): return 999
        return max(0, self.daily_quota_total - self.daily_quota_used)

    def is_unlimited(self) -> bool:
        # 显式 daily_quota_total = 0 → 不限
        return self.daily_quota_total == 0

    def _maybe_reset(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if self.quota_reset_date != today:
            self.quota_reset_date = today
            self.daily_quota_used = 0
            self.video_quota_used = 0


@dataclass
class PromptTemplate:
    """提示词模板"""
    id: str
    title: str
    content: str
    category: str = "通用"               # 通用/角色/场景/分镜板/视频/拆分镜
    placeholders: List[str] = field(default_factory=list)  # {style}/{count}/{story}


def dict_to_dataclass(cls, data):
    """把 dict 反序列化成 dataclass(健壮:多余字段忽略,缺失用默认)"""
    if data is None: return cls()
    valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
    clean = {k: v for k, v in data.items() if k in valid_fields}
    obj = cls(**clean)
    # 嵌套
    if cls is Episode and "shots" in data:
        obj.shots = [dict_to_dataclass(Shot, s) for s in data.get("shots", [])]
    if cls is Episode and "segments" in data:
        obj.segments = [dict_to_dataclass(VideoSegment, s) for s in data.get("segments", [])]
    return obj
