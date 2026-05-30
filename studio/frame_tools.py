"""
frame_tools.py — 手动工作流辅助:从视频抽取末帧 / 首帧。

用途:纯手动出片时,把上一段视频的最后一帧抽出来,当下一段的首帧参考图,
保证镜头衔接(豆包/即梦的"首帧参考图"上传)。

不依赖 Playwright / 自动化,只用 ffmpeg(系统 PATH 里需有 ffmpeg)。
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional


def ffmpeg_available() -> bool:
    """ffmpeg 是否在 PATH 里。"""
    return shutil.which("ffmpeg") is not None


def _probe_duration(video: Path) -> Optional[float]:
    """用 ffprobe 拿视频时长(秒)。拿不到返回 None。"""
    if not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
            capture_output=True, text=True, timeout=30,
        )
        return float(out.stdout.strip())
    except Exception:
        return None


def extract_frame(video_path: str, out_path: str,
                  position: str = "last") -> tuple[bool, str]:
    """
    从视频抽一帧存成图片。

    video_path: 输入视频路径
    out_path:   输出图片路径(.png / .jpg)
    position:   "last"=末帧(默认,用于衔接下一镜首帧)
                "first"=首帧
                也可传形如 "3.5" 的字符串 = 第 3.5 秒

    返回 (成功?, 提示信息)。
    """
    if not ffmpeg_available():
        return False, "ffmpeg 不在 PATH 里。请先安装 ffmpeg(https://ffmpeg.org)。"

    video = Path(video_path)
    if not video.exists():
        return False, f"视频文件不存在:{video_path}"

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # ---- 首帧 ----
    if position == "first":
        try:
            r = subprocess.run(
                ["ffmpeg", "-y", "-i", str(video), "-vframes", "1",
                 "-q:v", "2", str(out)],
                capture_output=True, text=True, timeout=60,
            )
            if out.exists() and out.stat().st_size > 100:
                return True, f"已抽取首帧 → {out}"
            return False, f"首帧抽取失败:{r.stderr[-300:]}"
        except Exception as e:
            return False, f"首帧抽取异常:{e}"

    # ---- 指定秒 ----
    if position not in ("last", "first"):
        try:
            seek = float(position)
            r = subprocess.run(
                ["ffmpeg", "-y", "-ss", f"{seek}", "-i", str(video),
                 "-vframes", "1", "-q:v", "2", str(out)],
                capture_output=True, text=True, timeout=60,
            )
            if out.exists() and out.stat().st_size > 100:
                return True, f"已抽取第 {seek}s 的帧 → {out}"
            return False, f"抽帧失败:{r.stderr[-300:]}"
        except ValueError:
            return False, f"position 参数无法识别:{position}(应为 last/first/秒数)"
        except Exception as e:
            return False, f"抽帧异常:{e}"

    # ---- 末帧(默认)----
    # 方法 A:-sseof -0.1 seek 到文件尾前 0.1s,抽 1 帧(-sseof 必须在 -i 前)
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-sseof", "-0.1", "-i", str(video),
             "-vframes", "1", "-q:v", "2", str(out)],
            capture_output=True, text=True, timeout=60,
        )
        if out.exists() and out.stat().st_size > 100:
            return True, f"已抽取末帧 → {out}"
    except Exception:
        pass

    # 方法 B:部分编码 -sseof seek 不准,退化到 ffprobe 拿时长 → -ss(时长-0.3)
    dur = _probe_duration(video)
    if dur and dur > 0.3:
        seek = max(0.0, dur - 0.3)
        try:
            r = subprocess.run(
                ["ffmpeg", "-y", "-ss", f"{seek}", "-i", str(video),
                 "-vframes", "1", "-q:v", "2", str(out)],
                capture_output=True, text=True, timeout=60,
            )
            if out.exists() and out.stat().st_size > 100:
                return True, f"已抽取末帧(回退法,文件尾前 0.3s)→ {out}"
            return False, f"末帧抽取失败(两种方法都不行):{r.stderr[-300:]}"
        except Exception as e:
            return False, f"末帧抽取异常:{e}"

    return False, "末帧抽取失败:-sseof 不支持且拿不到视频时长(ffprobe 缺失?)"


# ---- 命令行直接用(可选)----
# 用法:python -m studio.frame_tools 视频.mp4 [输出.png] [last|first|秒数]
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python -m studio.frame_tools <视频路径> [输出图片路径] [last|first|秒数]")
        sys.exit(1)
    vid = sys.argv[1]
    outp = sys.argv[2] if len(sys.argv) > 2 else str(Path(vid).with_suffix("")) + "_lastframe.png"
    pos = sys.argv[3] if len(sys.argv) > 3 else "last"
    ok, msg = extract_frame(vid, outp, pos)
    print(("✓ " if ok else "✗ ") + msg)
    sys.exit(0 if ok else 1)
