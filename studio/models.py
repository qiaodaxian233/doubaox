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
    duration: float = 2.0

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
    """10s 视频片段 = 多镜打包。豆包硬上限 10s。"""
    id: str = field(default_factory=lambda: _gid("seg"))
    episode_id: str = ""
    number: int = 1
    shot_ids: List[str] = field(default_factory=list)   # 这段包含哪些镜

    storyboard_image: str = ""          # 分镜板大图(给 seedance 当 master bible)
    storyboard_prompt: str = ""         # 生成分镜板大图所用的 prompt
    video_prompt: str = ""              # 生成视频用的 prompt (通常很短)

    generated_video: str = ""           # 最终视频路径
    generated_by_account: str = ""      # 哪个账号生成的
    generated_at: float = 0.0
    duration: float = 10.0


@dataclass
class Account:
    """账号 = 算力槽。豆包每账号每天 5 个视频额度。"""
    id: str
    name: str
    color: str = "#1e3a8a"
    online: bool = False
    status: str = "未启动"
    video_quota_total: int = 5          # 每日视频额度
    video_quota_used: int = 0
    quota_reset_date: str = ""          # YYYY-MM-DD

    def remaining(self) -> int:
        self._maybe_reset()
        return max(0, self.video_quota_total - self.video_quota_used)

    def _maybe_reset(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if self.quota_reset_date != today:
            self.quota_reset_date = today
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
