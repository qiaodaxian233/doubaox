"""
JSON 文件持久化。每项目一个子目录。
~/.doubao-studio/
├── accounts.json
├── prompts.json
└── projects/
    └── proj-xxx/
        ├── meta.json
        ├── characters.json
        ├── scenes.json
        ├── props.json
        ├── episodes/
        │   └── ep-xxx.json   (包含 shots + segments)
        └── assets/           (上传的参考图)
"""
from __future__ import annotations
import json, shutil
from pathlib import Path
from dataclasses import asdict
from typing import List, Optional
from .models import (
    Project, Character, Scene, Prop, Episode, Account, PromptTemplate,
    GenerationBackend, BACKEND_IMAGE, BACKEND_VIDEO,
    dict_to_dataclass,
)

APP_DIR      = Path.home() / ".doubao-studio"
PROJECTS_DIR = APP_DIR / "projects"
ACCOUNTS_FILE = APP_DIR / "accounts.json"
BACKENDS_FILE = APP_DIR / "backends.json"
PROMPTS_FILE = APP_DIR / "prompts.json"
PROFILES_DIR = APP_DIR / "profiles"      # Playwright per-account user-data-dir

for d in (APP_DIR, PROJECTS_DIR, PROFILES_DIR):
    d.mkdir(parents=True, exist_ok=True)


def _read(path: Path, default):
    if not path.exists(): return default
    try: return json.loads(path.read_text(encoding="utf-8"))
    except Exception: return default

def _write(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def project_dir(pid: str) -> Path:
    p = PROJECTS_DIR / pid
    for sub in ("episodes", "assets"):
        (p / sub).mkdir(parents=True, exist_ok=True)
    return p


# ---- Project ----
def list_projects() -> List[Project]:
    out = []
    for d in sorted(PROJECTS_DIR.iterdir()):
        if not d.is_dir(): continue
        meta = _read(d / "meta.json", None)
        if meta: out.append(dict_to_dataclass(Project, meta))
    return out

def save_project(p: Project):
    _write(project_dir(p.id) / "meta.json", asdict(p))

def delete_project(pid: str):
    d = PROJECTS_DIR / pid
    if d.exists(): shutil.rmtree(d, ignore_errors=True)


# ---- Characters / Scenes / Props (整组存为一个 JSON 数组,简单粗暴) ----
def _load_list(pid, name, cls):
    arr = _read(project_dir(pid) / f"{name}.json", [])
    return [dict_to_dataclass(cls, x) for x in arr]

def _save_list(pid, name, items):
    _write(project_dir(pid) / f"{name}.json", [asdict(x) for x in items])

def load_characters(pid): return _load_list(pid, "characters", Character)
def save_characters(pid, items): _save_list(pid, "characters", items)
def load_scenes(pid):     return _load_list(pid, "scenes", Scene)
def save_scenes(pid, items): _save_list(pid, "scenes", items)
def load_props(pid):      return _load_list(pid, "props", Prop)
def save_props(pid, items): _save_list(pid, "props", items)


# ---- Episodes (每集一个文件,含 shots + segments) ----
def list_episodes(pid: str) -> List[Episode]:
    ep_dir = project_dir(pid) / "episodes"
    out = []
    for f in sorted(ep_dir.glob("*.json")):
        out.append(dict_to_dataclass(Episode, _read(f, {})))
    out.sort(key=lambda e: e.number)
    return out

def save_episode(pid: str, ep: Episode):
    _write(project_dir(pid) / "episodes" / f"{ep.id}.json", asdict(ep))

def delete_episode(pid: str, eid: str):
    f = project_dir(pid) / "episodes" / f"{eid}.json"
    if f.exists(): f.unlink()


# ---- Accounts (全局共享) ----
def load_accounts() -> List[Account]:
    data = _read(ACCOUNTS_FILE, [])
    return [dict_to_dataclass(Account, x) for x in data]

def save_accounts(accounts: List[Account]):
    _write(ACCOUNTS_FILE, [asdict(a) for a in accounts])


# ---- Generation Backends (全局共享) ----
DEFAULT_BACKENDS = [
    GenerationBackend(
        id="gpt-mirror",
        name="紫刀 GPT 镜像",
        kind=BACKEND_IMAGE,
        url="https://gpt.aimonkey.plus/",
        icon="🖼",
        notes="用 GPT-4o/DALL-E 生角色三视图、道具图、分镜板大图。微信扫码登录。",
    ),
    GenerationBackend(
        id="jimeng",
        name="即梦 (字节)",
        kind=BACKEND_IMAGE,
        url="https://jimeng.jianying.com/",
        icon="🎨",
        notes="备选图片后端。即梦 image2 生成参考图。",
        enabled=False,
    ),
    GenerationBackend(
        id="doubao",
        name="豆包 seedance",
        kind=BACKEND_VIDEO,
        url="https://www.doubao.com/chat",
        icon="🎬",
        notes="seedance2.0 视频。单段硬上限 10s,每账号每天 5 个视频。",
    ),
]


def load_backends() -> List[GenerationBackend]:
    data = _read(BACKENDS_FILE, None)
    if data is None:
        # 首启写入默认
        save_backends(DEFAULT_BACKENDS)
        return list(DEFAULT_BACKENDS)
    return [dict_to_dataclass(GenerationBackend, x) for x in data]


def save_backends(backends: List[GenerationBackend]):
    _write(BACKENDS_FILE, [asdict(b) for b in backends])


def get_backend(backend_id: str) -> GenerationBackend:
    for b in load_backends():
        if b.id == backend_id: return b
    return None


# ---- PromptTemplates (全局共享) ----
def load_prompts() -> List[PromptTemplate]:
    data = _read(PROMPTS_FILE, None)
    if data is None:
        from .prompts import DEFAULT_PROMPT_TEMPLATES
        return list(DEFAULT_PROMPT_TEMPLATES)
    return [dict_to_dataclass(PromptTemplate, x) for x in data]

def save_prompts(prompts: List[PromptTemplate]):
    _write(PROMPTS_FILE, [asdict(p) for p in prompts])


# ---- Assets (参考图等本地文件) ----
def import_asset(pid: str, src_path: Path, target_name: Optional[str] = None) -> str:
    """复制外部文件到 project assets/,返回相对路径。"""
    src = Path(src_path)
    if not src.exists(): return ""
    tgt_dir = project_dir(pid) / "assets"
    tgt = tgt_dir / (target_name or src.name)
    # 避重名
    i = 1
    while tgt.exists() and tgt.stat().st_size != src.stat().st_size:
        tgt = tgt_dir / f"{src.stem}_{i}{src.suffix}"
        i += 1
    if not tgt.exists():
        shutil.copy2(src, tgt)
    return f"assets/{tgt.name}"

def asset_full_path(pid: str, rel: str) -> Path:
    if not rel: return Path()
    return project_dir(pid) / rel
