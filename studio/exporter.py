"""
M4 导出器:
- 视频拼接(ffmpeg concat demuxer)
- PDF 故事板导出(reportlab,可选;不装时退化到 HTML)
- 剪映工程文件 (.draft) — TODO 下一轮
"""
from __future__ import annotations
from pathlib import Path
from typing import List, Optional
import subprocess, shutil, tempfile, json, time

from . import storage as ST
from .models import Project, Episode, Shot, VideoSegment


# ---- ffmpeg ----

def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def concat_videos(input_files: List[Path], output_file: Path,
                  crossfade_seconds: float = 0.0) -> bool:
    """用 ffmpeg concat demuxer 拼接多个视频。
    
    参数:
      input_files:输入视频路径列表
      output_file:输出路径
      crossfade_seconds:段间叠化秒数(0 = 硬切)。0 时用 concat demuxer(无重编码,极快);
                       >0 时用 filter_complex(慢但能叠化)。
    返回 True 表示成功。
    """
    if not ffmpeg_available(): return False
    if not input_files: return False
    output_file.parent.mkdir(parents=True, exist_ok=True)

    if crossfade_seconds <= 0:
        # 快路径:concat demuxer
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            for p in input_files:
                f.write(f"file '{p.absolute()}'\n")
            list_file = f.name
        try:
            cmd = [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", list_file, "-c", "copy", str(output_file)
            ]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if r.returncode != 0:
                # concat demuxer 失败时(编码不一样),退化到重编码模式
                cmd2 = [
                    "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                    "-i", list_file, "-c:v", "libx264", "-c:a", "aac",
                    "-preset", "fast", "-crf", "23",
                    str(output_file)
                ]
                r = subprocess.run(cmd2, capture_output=True, text=True, timeout=900)
            return r.returncode == 0
        finally:
            Path(list_file).unlink(missing_ok=True)
    else:
        # 慢路径:filter_complex xfade
        n = len(input_files)
        if n < 2:
            shutil.copy2(input_files[0], output_file)
            return True
        # 简化:每对相邻片段叠化 crossfade_seconds 秒
        inputs = []
        for p in input_files: inputs.extend(["-i", str(p)])
        # 探测每段时长
        durations = []
        for p in input_files:
            d = _probe_duration(p)
            durations.append(d or 10.0)
        # 链式构造 xfade(略复杂,这里给个能跑的基础版)
        filter_parts = []
        last = "[0:v]"
        offset = durations[0] - crossfade_seconds
        for i in range(1, n):
            tag = f"[v{i}]"
            filter_parts.append(
                f"{last}[{i}:v]xfade=transition=fade:duration={crossfade_seconds}:offset={offset:.3f}{tag}"
            )
            last = tag
            if i < n - 1:
                offset += durations[i] - crossfade_seconds
        filter_str = ";".join(filter_parts)
        cmd = [
            "ffmpeg", "-y", *inputs, "-filter_complex", filter_str,
            "-map", last, "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            str(output_file)
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        return r.returncode == 0


def _probe_duration(p: Path) -> Optional[float]:
    if shutil.which("ffprobe") is None: return None
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(p)],
            capture_output=True, text=True, timeout=10
        )
        return float(r.stdout.strip())
    except Exception:
        return None


def concat_episode(project_id: str, episode_id: str, output_file: Path,
                   crossfade_seconds: float = 0.3) -> bool:
    """拼接一集的所有 VideoSegment 成最终视频。"""
    for ep in ST.list_episodes(project_id):
        if ep.id != episode_id: continue
        ordered_segs = sorted(ep.segments, key=lambda s: s.number)
        files = []
        for seg in ordered_segs:
            if not seg.generated_video: continue
            p = ST.asset_full_path(project_id, seg.generated_video)
            if p.exists(): files.append(p)
        if not files: return False
        return concat_videos(files, output_file, crossfade_seconds)
    return False


# ---- PDF 故事板导出 ----

try:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.lib.colors import HexColor
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False


def _register_cjk_font():
    """尝试注册中文字体。"""
    if not HAS_REPORTLAB: return False
    candidates = [
        ("/System/Library/Fonts/PingFang.ttc", "PingFang"),
        ("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", "WQYMicroHei"),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "NotoSansCJK"),
        ("C:/Windows/Fonts/msyh.ttc", "YaHei"),
        ("C:/Windows/Fonts/simhei.ttf", "SimHei"),
    ]
    for path, name in candidates:
        if Path(path).exists():
            try:
                pdfmetrics.registerFont(TTFont(name, path))
                return name
            except Exception: continue
    return None


def export_storyboard_pdf(project_id: str, episode_id: str, output_pdf: Path) -> bool:
    """导出 PDF 故事板。一镜一页,含编号/景别/动作/衔接锚点 + 缩略图(若有)。"""
    if not HAS_REPORTLAB:
        # 退化到 HTML
        return _export_storyboard_html(project_id, episode_id, output_pdf.with_suffix(".html"))

    font_name = _register_cjk_font() or "Helvetica"
    ep = None
    for e in ST.list_episodes(project_id):
        if e.id == episode_id: ep = e; break
    if not ep: return False

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    page_size = landscape(A4)  # 横版
    c = canvas.Canvas(str(output_pdf), pagesize=page_size)
    W, H = page_size

    # 封面
    c.setFont(font_name, 28)
    c.setFillColor(HexColor("#0a0a0a"))
    c.drawString(40, H - 80, ep.title or f"第 {ep.number} 集")
    c.setFont(font_name, 11)
    c.setFillColor(HexColor("#71717a"))
    c.drawString(40, H - 110, f"分镜数 {len(ep.shots)} · 情绪曲线 {ep.emotional_arc or '—'}")
    if ep.synopsis:
        c.setFont(font_name, 10)
        c.setFillColor(HexColor("#3f3f46"))
        y = H - 150
        for line in ep.synopsis.split("\n")[:10]:
            c.drawString(40, y, line[:80]); y -= 14
    c.showPage()

    # 每镜一页
    for shot in ep.shots:
        c.setFont(font_name, 18)
        c.setFillColor(HexColor("#dc5a3a"))
        c.drawString(40, H - 50, f"分镜 #{shot.number}")
        c.setFont(font_name, 10)
        c.setFillColor(HexColor("#71717a"))
        c.drawString(40, H - 68, f"{shot.start_time:.1f}s + {shot.duration}s · "
                                  f"{shot.shot_size} / {shot.camera_movement}")

        # 参考图(左半页)
        thumb_x = 40; thumb_y = 80; thumb_w = (W - 80) * 0.45; thumb_h = H - 180
        c.setStrokeColor(HexColor("#e7e5e0"))
        c.rect(thumb_x, thumb_y, thumb_w, thumb_h, stroke=1, fill=0)
        if shot.generated_image:
            img_path = ST.asset_full_path(project_id, shot.generated_image)
            if img_path.exists():
                try:
                    c.drawImage(str(img_path), thumb_x, thumb_y, thumb_w, thumb_h,
                                preserveAspectRatio=True, anchor="c")
                except Exception:
                    c.setFillColor(HexColor("#71717a"))
                    c.drawCentredString(thumb_x + thumb_w/2, thumb_y + thumb_h/2, "(参考图加载失败)")
        else:
            c.setFillColor(HexColor("#a3a3a3"))
            c.setFont(font_name, 10)
            c.drawCentredString(thumb_x + thumb_w/2, thumb_y + thumb_h/2, "(未生成参考图)")

        # 文字区(右半页)
        text_x = thumb_x + thumb_w + 30
        text_w = W - text_x - 40
        y = H - 100

        def write_section(label: str, body: str, body_size: int = 10):
            nonlocal y
            if not body: return
            c.setFont(font_name, 8)
            c.setFillColor(HexColor("#71717a"))
            c.drawString(text_x, y, label.upper())
            y -= 14
            c.setFont(font_name, body_size)
            c.setFillColor(HexColor("#0a0a0a"))
            # 简单换行
            words = body.replace("\n", "  ").split(" ") if " " in body else list(body)
            line = ""
            for w in words:
                test = line + (w if line.endswith(" ") else " " + w if line else w)
                if c.stringWidth(test, font_name, body_size) > text_w:
                    c.drawString(text_x, y, line); y -= 12; line = w
                else:
                    line = test
                if y < 80: break
            if line: c.drawString(text_x, y, line); y -= 14
            y -= 6

        write_section("视觉风格", shot.visual_style_note)
        write_section("摄影参数", shot.camera_params)
        write_section("动作设计", shot.action)
        write_section("光影设计", shot.lighting)
        write_section("音效", shot.sound)
        if shot.dialogue:
            write_section("台词", shot.dialogue)
        if shot.transition_anchor:
            write_section("衔接锚点", shot.transition_anchor)

        c.showPage()

    c.save()
    return True


def _export_storyboard_html(project_id: str, episode_id: str, output_html: Path) -> bool:
    """没 reportlab 时退化方案。"""
    ep = None
    for e in ST.list_episodes(project_id):
        if e.id == episode_id: ep = e; break
    if not ep: return False

    output_html.parent.mkdir(parents=True, exist_ok=True)
    parts = [
        f"<!doctype html><html lang='zh'><head><meta charset='utf-8'>",
        f"<title>{ep.title or f'第 {ep.number} 集'}</title>",
        "<style>body{font-family:-apple-system,'PingFang SC',sans-serif;",
        "max-width:1100px;margin:40px auto;padding:0 24px;color:#0a0a0a;background:#faf9f5}",
        "h1{font-family:'Fraunces',serif}",
        ".shot{display:grid;grid-template-columns:280px 1fr;gap:18px;margin:24px 0;",
        "background:#fff;border:1px solid #e7e5e0;border-radius:8px;padding:16px}",
        ".thumb{background:#f4f3ee;border-radius:6px;min-height:160px;",
        "display:flex;align-items:center;justify-content:center;color:#a3a3a3}",
        ".thumb img{max-width:100%;max-height:200px;border-radius:6px}",
        ".num{color:#dc5a3a;font-weight:600;font-size:18px}",
        ".field{margin:6px 0}.label{color:#71717a;font-size:11px;text-transform:uppercase;",
        "letter-spacing:.5px}</style></head><body>",
        f"<h1>{ep.title or f'第 {ep.number} 集'}</h1>",
        f"<p style='color:#71717a'>{len(ep.shots)} 镜 · 情绪曲线 {ep.emotional_arc or '—'}</p>",
        f"<p>{(ep.synopsis or '').replace(chr(10), '<br>')}</p>",
    ]
    for shot in ep.shots:
        img_html = ""
        if shot.generated_image:
            p = ST.asset_full_path(project_id, shot.generated_image)
            if p.exists():
                import base64, mimetypes
                mt, _ = mimetypes.guess_type(str(p))
                with open(p, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                img_html = f"<img src='data:{mt or 'image/jpeg'};base64,{b64}'>"
        thumb = img_html or "(未生成参考图)"
        parts.append(f"""
        <div class="shot">
          <div class="thumb">{thumb}</div>
          <div>
            <div class="num">分镜 #{shot.number}</div>
            <div style="color:#71717a;font-size:12px;margin:4px 0 12px">
              {shot.start_time:.1f}s + {shot.duration}s · {shot.shot_size} / {shot.camera_movement}
            </div>
            <div class="field"><span class="label">动作</span><br>{shot.action}</div>
            <div class="field"><span class="label">光影</span><br>{shot.lighting}</div>
            <div class="field"><span class="label">音效</span><br>{shot.sound}</div>
            <div class="field"><span class="label">衔接锚点</span><br>{shot.transition_anchor}</div>
          </div>
        </div>
        """)
    parts.append("</body></html>")
    output_html.write_text("".join(parts), encoding="utf-8")
    return True


# ============================================================
# M4.5 剪映工程导出 (.draft 目录)
# ============================================================
# 剪映 5.9 及以下:draft_content.json 明文 JSON,可生成
# 剪映 6+:加密了,生成的明文文件需用户手动操作或装兼容版本
# 推荐:用户复制生成目录到剪映"草稿"目录,启动剪映让它自动补全
#   macOS: ~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft/
#   Windows: %APPDATA%/JianyingPro/User Data/Projects/com.lveditor.draft/
# 优先用 pyJianYingDraft 库;不装时手写 minimal JSON

try:
    import pyJianYingDraft as _jydraft
    HAS_PYJYDRAFT = True
except ImportError:
    HAS_PYJYDRAFT = False


def jianying_draft_folder() -> Optional[Path]:
    """猜剪映草稿目录位置(macOS / Windows / CapCut 多候选)。"""
    home = Path.home()
    candidates = [
        home / "Movies/JianyingPro/User Data/Projects/com.lveditor.draft",
        home / "AppData/Local/JianyingPro/User Data/Projects/com.lveditor.draft",
        home / "AppData/Roaming/JianyingPro/User Data/Projects/com.lveditor.draft",
        home / "Movies/CapCut/User Data/Projects/com.lveditor.draft",
    ]
    for p in candidates:
        if p.exists(): return p
    return None


def export_jianying_draft(project_id: str, episode_id: str,
                          output_dir: Path,
                          width: int = 1920, height: int = 1080) -> bool:
    """导出剪映工程草稿目录。
    
    生成结构:
      output_dir/
        ├── draft_content.json
        └── draft_meta_info.json
    """
    ep = None
    for e in ST.list_episodes(project_id):
        if e.id == episode_id: ep = e; break
    if not ep: return False

    # 收集片段:优先 segment.generated_video,fallback shot.generated_video
    clips = []
    if ep.segments:
        for seg in sorted(ep.segments, key=lambda s: s.number):
            if not seg.generated_video: continue
            p = ST.asset_full_path(project_id, seg.generated_video)
            if p.exists():
                d = _probe_duration(p) or seg.duration or 10.0
                clips.append((p, d, f"段 #{seg.number}"))
    if not clips:
        for shot in ep.shots:
            if not shot.generated_video: continue
            p = ST.asset_full_path(project_id, shot.generated_video)
            if p.exists():
                d = _probe_duration(p) or shot.duration or 2.5
                clips.append((p, d, f"镜 #{shot.number}"))
    if not clips: return False

    output_dir.mkdir(parents=True, exist_ok=True)

    if HAS_PYJYDRAFT:
        if _export_with_pyjydraft(clips, output_dir, width, height):
            return True
        # 失败回退
    return _export_manual_json(clips, output_dir, width, height)


def _export_with_pyjydraft(clips: list, output_dir: Path, width: int, height: int) -> bool:
    """用 pyJianYingDraft 生成 draft。"""
    try:
        # API 命名兼容(两套版本)
        try:
            ScriptFile = _jydraft.Script_file
            TrackType = _jydraft.Track_type
            VideoMaterial = _jydraft.Video_material
            VideoSegment = _jydraft.Video_segment
            trange = _jydraft.trange
        except AttributeError:
            ScriptFile = _jydraft.ScriptFile
            TrackType = _jydraft.TrackType
            VideoMaterial = _jydraft.VideoMaterial
            VideoSegment = _jydraft.VideoSegment
            trange = _jydraft.trange

        script = ScriptFile(width, height)
        script.add_track(TrackType.video)
        cur = 0.0
        for path, dur, _label in clips:
            mat = VideoMaterial(str(path))
            script.add_material(mat)
            seg = VideoSegment(mat, trange(f"{cur:.2f}s", f"{dur:.2f}s"))
            script.add_segment(seg)
            cur += dur

        script.dump(str(output_dir / "draft_content.json"))
        _write_minimal_meta(output_dir, name=output_dir.name)
        return True
    except Exception as e:
        print(f"pyJianYingDraft 导出失败: {e},回退到手写 JSON")
        return False


def _export_manual_json(clips: list, output_dir: Path, width: int, height: int) -> bool:
    """手写 minimal draft_content.json,剪映 5.x 打开后会自动补齐缺失字段。"""
    import uuid as _uuid

    materials = []
    segments = []
    cur_us = 0
    track_id = _uuid.uuid4().hex.upper()
    canvas_id = _uuid.uuid4().hex.upper()

    for path, dur_s, _label in clips:
        mat_id = _uuid.uuid4().hex.upper()
        seg_id = _uuid.uuid4().hex.upper()
        dur_us = int(dur_s * 1_000_000)

        materials.append({
            "id": mat_id,
            "type": "video",
            "path": str(path.absolute()).replace("\\", "/"),
            "material_name": path.name,
            "width": width,
            "height": height,
            "duration": dur_us,
            "has_audio": True,
            "extra_type_option": 0,
            "create_time": int(time.time()),
            "category_id": "",
            "category_name": "local",
            "check_flag": 63487,
            "crop": {
                "lower_left_x": 0.0, "lower_left_y": 1.0,
                "lower_right_x": 1.0, "lower_right_y": 1.0,
                "upper_left_x": 0.0, "upper_left_y": 0.0,
                "upper_right_x": 1.0, "upper_right_y": 0.0,
            },
            "crop_ratio": "free",
            "crop_scale": 1.0,
            "formula_id": "",
            "is_ai_generate_content": False,
            "is_unified_beauty_mode": False,
            "live_photo_cover_path": "",
            "matting": {"flag": 0, "interactiveTime": [], "path": "", "strokes": []},
            "media_path": "",
            "object_locked": None,
            "origin_material_id": "",
            "picture_from": "none",
            "picture_set_category_id": "",
            "picture_set_category_name": "",
            "request_id": "",
            "reverse_intensifies_path": "",
            "reverse_path": "",
            "smart_motion": None,
            "source": 0,
            "source_platform": 0,
            "stable": {
                "matrix_path": "", "stable_level": 0, "time_range": {"duration": 0, "start": 0},
            },
            "team_id": "",
            "video_algorithm": {
                "algorithms": [], "deflicker": None, "motion_blur_config": None,
                "noise_reduction": None, "path": "", "quality_enhance": None,
                "time_range": None,
            },
        })

        segments.append({
            "id": seg_id,
            "material_id": mat_id,
            "target_timerange": {"start": cur_us, "duration": dur_us},
            "source_timerange": {"start": 0, "duration": dur_us},
            "extra_material_refs": [],
            "speed": 1.0,
            "visible": True,
            "volume": 1.0,
            "cartoon": False,
            "clip": {
                "alpha": 1.0,
                "flip": {"horizontal": False, "vertical": False},
                "rotation": 0.0,
                "scale": {"x": 1.0, "y": 1.0},
                "transform": {"x": 0.0, "y": 0.0},
            },
            "common_keyframes": [],
            "enable_adjust": True, "enable_color_correct_adjust": False,
            "enable_color_curves": True, "enable_color_match_adjust": False,
            "enable_color_wheels": True, "enable_lut": True, "enable_smart_color_adjust": False,
            "group_id": "", "hdr_settings": {"intensity": 1.0, "mode": 1, "nits": 1000},
            "intensifies_audio": False, "is_placeholder": False,
            "is_tone_modify": False, "keyframe_refs": [], "last_nonzero_volume": 1.0,
            "render_index": 0, "render_size_proportion": 1.0,
            "responsive_layout": {"enable": False, "horizontal_pos_layout": 0,
                                  "size_layout": 0, "target_follow": "", "vertical_pos_layout": 0},
            "reverse": False, "template_id": "", "template_scene": "default",
            "track_attribute": 0, "track_render_index": 0,
            "uniform_scale": {"on": True, "value": 1.0},
        })
        cur_us += dur_us

    total_us = cur_us

    content = {
        "canvas_config": {"height": height, "ratio": "16:9", "width": width},
        "color_space": 0,
        "config": {
            "adjust_max_index": 1, "attachment_info": [], "combination_max_index": 1,
            "export_range": None, "extract_audio_last_index": 1,
            "lyrics_recognition_id": "", "lyrics_taskinfo": [],
            "maintrack_adsorb": True, "material_save_mode": 0, "original_sound_last_index": 1,
            "record_audio_last_index": 1, "sticker_max_index": 1, "subtitle_recognition_id": "",
            "subtitle_taskinfo": [], "system_font_list": [], "video_mute": False,
            "zoom_info_params": None,
        },
        "cover": None,
        "create_time": int(time.time()),
        "duration": total_us,
        "extra_info": None,
        "fps": 30.0,
        "free_render_index_mode_on": False,
        "group_container": None,
        "id": _uuid.uuid4().hex.upper(),
        "keyframe_graph_list": [],
        "keyframes": {
            "adjusts": [], "audios": [], "effects": [], "filters": [], "handwrites": [],
            "stickers": [], "texts": [], "videos": [],
        },
        "last_modified_platform": {
            "app_id": 3704, "app_source": "lv", "app_version": "5.9.0",
            "device_id": "00000000000000", "hard_disk_id": "00000000000000",
            "mac_address": "000000000000", "os": "mac", "os_version": "14.0",
        },
        "materials": {
            "ai_translates": [], "audio_balances": [], "audio_effects": [],
            "audio_fades": [], "audios": [], "beats": [], "canvases": [
                {"album_image": "", "blur": 0.0, "color": "", "id": canvas_id,
                 "image": "", "image_id": "", "image_name": "", "source_platform": 0,
                 "team_id": "", "type": "canvas_color"}
            ],
            "chromas": [], "color_curves": [], "digital_humans": [], "drafts": [],
            "effects": [], "flowers": [], "green_screens": [],
            "handwrites": [], "hsl": [], "images": [], "log_color_wheels": [],
            "loudnesses": [], "manual_deformations": [], "masks": [], "material_animations": [],
            "material_colors": [], "multi_language_refs": [], "placeholders": [],
            "plugin_effects": [], "primary_color_wheels": [], "realtime_denoises": [],
            "shapes": [], "smart_crops": [], "smart_relights": [], "sound_channel_mappings": [],
            "speeds": [], "stickers": [], "tail_leaders": [], "text_templates": [],
            "texts": [], "time_marks": [], "transitions": [], "video_effects": [],
            "video_trackings": [], "videos": materials,
            "vocal_beautifys": [], "vocal_separations": [],
        },
        "mutable_config": None,
        "name": "",
        "new_version": "70.0.0",
        "platform": {
            "app_id": 3704, "app_source": "lv", "app_version": "5.9.0",
            "device_id": "00000000000000", "hard_disk_id": "00000000000000",
            "mac_address": "000000000000", "os": "mac", "os_version": "14.0",
        },
        "relationships": [],
        "render_index_track_mode_on": False,
        "retouch_cover": None,
        "source": "default",
        "static_cover_image_path": "",
        "time_marks": None,
        "tracks": [{
            "attribute": 0, "flag": 0, "id": track_id,
            "is_default_name": True, "name": "", "segments": segments, "type": "video",
        }],
        "update_time": int(time.time()),
        "version": 360000,
    }

    (output_dir / "draft_content.json").write_text(
        json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_minimal_meta(output_dir, name=output_dir.name)
    return True


def _write_minimal_meta(output_dir: Path, name: str):
    """draft_meta_info.json"""
    import uuid as _uuid
    meta = {
        "cloud_package_completed_time": "",
        "draft_cloud_capcut_purchase_info": "",
        "draft_cloud_last_action_download": False,
        "draft_cloud_materials": [],
        "draft_cloud_purchase_info": "",
        "draft_cloud_template_id": "",
        "draft_cloud_tutorial_info": "",
        "draft_cloud_videocut_purchase_info": "",
        "draft_cover": "draft_cover.jpg",
        "draft_deeplink_url": "",
        "draft_enterprise_info": {"draft_enterprise_extra": "",
                                  "draft_enterprise_id": "", "draft_enterprise_name": "",
                                  "enterprise_material": []},
        "draft_fold_path": str(output_dir.absolute()),
        "draft_id": _uuid.uuid4().hex.upper(),
        "draft_is_ai_packaging_used": False,
        "draft_is_ai_shorts": False,
        "draft_is_ai_translate": False,
        "draft_is_article_video_draft": False,
        "draft_is_from_deeplink": "false",
        "draft_is_invisible": False,
        "draft_materials": [{"type": 0, "value": []}],
        "draft_materials_copied_info": [],
        "draft_name": name,
        "draft_new_version": "",
        "draft_removable_storage_device": "",
        "draft_root_path": str(output_dir.parent.absolute()),
        "draft_segment_extra_info": [],
        "draft_timeline_materials_size_": 0,
        "draft_type": "",
        "tm_draft_cloud_completed": "",
        "tm_draft_cloud_modified": 0,
        "tm_draft_create": int(time.time() * 1_000_000),
        "tm_draft_modified": int(time.time() * 1_000_000),
        "tm_draft_removed": 0,
        "tm_duration": 0,
    }
    (output_dir / "draft_meta_info.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
