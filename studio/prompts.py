"""
内置提示词模板库 —— 抽取自"蒙哥AI"知识库。
每个模板含占位符 {placeholder},应用时由 ui 层 .format() 注入实际值。
"""
from .models import PromptTemplate


DEFAULT_PROMPT_TEMPLATES = [
    # ==================== 角色定型 ====================
    PromptTemplate(
        id="tpl-char-001",
        category="角色",
        title="角色三视图定型卡",
        placeholders=["style", "name", "gender", "age"],
        content=(
            "{style}。角色:{name}({gender},{age});8K超高清,专业角色设定卡,"
            "纯白无杂质背景,16:9比例,画面布局工整、无重叠、无遮挡、无文字干扰。"
            "1. 左侧区域【角色面部特写模块】:同一角色的高清面部特写,极致细节,"
            "发丝、皮肤纹理、妆容、饰品清晰锐利,光影柔和统一;"
            "2. 右侧区域【三视图模块】:同一角色的正面、侧面、背面3张标准全身立绘,"
            "统一标准站姿,统一五官脸型、发型发色、基础体态,服装版型、配色、纹样、"
            "饰品、道具细节100%全局一致,人体结构精准无畸变,无穿模、无变形。"
        ),
    ),
    PromptTemplate(
        id="tpl-char-002",
        category="角色",
        title="角色结构化数据 JSON",
        placeholders=["face_shape", "eye_details", "nose_shape", "lip_shape",
                      "eyebrow_style", "jawline", "skin_details", "style_lock"],
        content=(
            "{{\n"
            '  "face_shape": "{face_shape}",\n'
            '  "eye_details": "{eye_details}",\n'
            '  "nose_shape": "{nose_shape}",\n'
            '  "lip_shape": "{lip_shape}",\n'
            '  "eyebrow_style": "{eyebrow_style}",\n'
            '  "jawline": "{jawline}",\n'
            '  "skin_details": "{skin_details}",\n'
            '  "style_lock": "{style_lock}"\n'
            "}}"
        ),
    ),

    # ==================== 场景定型 ====================
    PromptTemplate(
        id="tpl-scene-001",
        category="场景",
        title="场景固定描述 JSON",
        placeholders=["aspect_ratio", "asset_description",
                      "fixed_environment", "fixed_lighting", "fixed_background"],
        content=(
            "{{\n"
            '  "Aspect_Ratio": "{aspect_ratio}",\n'
            '  "Asset_Description": "{asset_description}",\n'
            '  "Scene_Fixed_Environment": "{fixed_environment}",\n'
            '  "Scene_Fixed_Lighting": "{fixed_lighting}",\n'
            '  "Scene_Fixed_Background": "{fixed_background}"\n'
            "}}"
        ),
    ),

    # ==================== 分镜板大图 (核心!) ====================
    PromptTemplate(
        id="tpl-board-001",
        category="分镜板",
        title="电影制作板/视觉规划表(8镜通用)",
        placeholders=[],
        content=(
            "创建一个电影制作板/视觉规划表,比例16:9,展示短片或商业广告的完整概念。"
            "布局应简洁、基于网格,并分为清晰标记的部分。 包含: "
            "共享创意指导(顶部栏):整体限制,如镜头数量、统一的调色板和一般的环境背景。 "
            "角色与风格参考部分: 一个从多个角度展示的模型(正面、背面、侧面、特写、放松姿态),"
            "配有服装和配饰参考。强调身份的一致性,同时允许在特定场景中进行细微变化。 "
            "环境和场景设计部分: 一个具有戏剧性自然特征的场景户外地点,以及一个俯视示意图,"
            "说明在空间中的移动路径。包括摄像机位置和沿路线标注的拍摄类型。 "
            "故事板部分: 一系列编号的帧(大约 8 个镜头)展示场景的进展。每个帧包括:"
            "摄像机类型/镜头感觉 镜头大小(广角、中景、特写、微距) "
            "运动方式(静态、跟踪、手持等) 动作和情绪进展的简要描述 "
            "灯光/情绪/风格备注: 与灯光条件、氛围和纹理相关的视觉示例和简短描述。"
            "包括一天中不同时间的过渡和光线质量的变化。 "
            "情绪和关键词块:指导作品的简洁情绪基调主题描述列表。 "
            "音频/音调部分: 环境声音、音乐风格和整体声音氛围的指示。 "
            "电影摄影笔记: 包括镜头特性、运动风格和后期处理感觉的总体视觉哲学。 "
            "整个版面应感觉连贯、电影化且专业设计——就像导演的预制作指南,"
            "能一眼传达出基调、节奏和视觉叙事。"
        ),
    ),
    PromptTemplate(
        id="tpl-board-002",
        category="分镜板",
        title="真人影视故事板(5区版)",
        placeholders=["character_design", "scene_design", "shot_list", "style_notes"],
        content=(
            "请生成一张高质量、专业影视预制作风格的故事板设定图,"
            "整体形式类似电影导演分镜板、短片提案板、AI视频预制作概念板。"
            "画面为横版,4K超清,信息丰富,排版清晰,设计感高级,图文结合,"
            "整体像一张专业的影视开发案故事板。 整张图分为五个主要区域:\n\n"
            "【一、左侧:角色设定区】\n{character_design}\n\n"
            "【二、中间:场景设计区】\n{scene_design}\n\n"
            "【三、中间下方:俯视走位与机位规划区】\n"
            "请绘制一个俯视图,用来展示这个场景中的人物位置、道具摆放,以及摄影机机位和镜头方向,"
            "类似专业分镜设计中的 top-down movement & camera plan。"
            "标注每个镜头的机位编号,与右侧8格分镜一一对应。\n\n"
            "【四、右侧:8格故事分镜区】\n{shot_list}\n\n"
            "【五、底部:风格说明文字区】\n{style_notes}"
        ),
    ),

    # ==================== 视频生成提示词 ====================
    PromptTemplate(
        id="tpl-vid-001",
        category="视频",
        title="按分镜板生成视频(最简版)",
        placeholders=[],
        content="请严格按照参考图分镜故事板制作10秒短视频即可!",
    ),
    PromptTemplate(
        id="tpl-vid-002",
        category="视频",
        title="按故事板生成(经典版)",
        placeholders=["story", "shots"],
        content=(
            "按照这个故事板来创作广告/电影。动态的摄像机运动,镜头中不出现摄像机设备,\n\n"
            "故事 = {story}\n\n"
            "{shots}\n\n"
            "避免场景过于相似"
        ),
    ),
    PromptTemplate(
        id="tpl-vid-003",
        category="视频",
        title="Master Visual Bible (JSON 专业版)",
        placeholders=["shots"],
        content=(
            "{{\n"
            '"instruction": {{\n'
            '  "core_directive": "Treat the uploaded image as the single highest-priority Master Visual Bible, '
            'serving as the execution blueprint for full video generation, not merely a style reference.",\n'
            '  "definition": "The image is a complete cinematic visual development board / character & environment '
            'master sheet / pre-production art board, containing character design, environment design, '
            'storyboard logic, camera movement, lighting mood, color system, cinematography parameters, '
            'and narrative direction.",\n'
            '  "goal": "Generate a complete, coherent, highly cinematic short film as if this board were '
            'directly translated into a finished production."\n'
            '}},\n'
            '"global_requirements": {{\n'
            '  "consistency": ["Character appearance and personality", "Costume, hairstyle, props, identity", '
            '"Environment and spatial atmosphere", "Storyboard order and narrative rhythm", '
            '"Camera movement language", "Lighting and color system", "Overall visual style"]\n'
            '}}\n'
            "}}\n\n"
            "{shots}"
        ),
    ),

    # ==================== 国漫写实风格(蒙哥模板2) ====================
    PromptTemplate(
        id="tpl-vid-004",
        category="视频",
        title="国漫写实分镜(Portrait引用版)",
        placeholders=["shots"],
        content=(
            "按照这个 {{Portrait 1}} 故事板来创作广告/电影。动态的摄像机运动,"
            "镜头中不出现摄像机设备,风格:国漫写实风格\n\n"
            "你是国际一流的动画电影分镜师,现在参与一部史诗奇幻剧集制作。\n"
            "内容=电影式的跟踪镜头。\n"
            "风格:国漫写实风格\n\n"
            "{shots}\n\n"
            "动态的镜头运动跟随动作展开,高速推进,运动模糊效果,体积光照透过树木洒下,"
            "逼真写实,8K分辨率,充满史诗般的奇幻氛围。"
        ),
    ),

    # ==================== 单镜动态时间轴(超细) ====================
    PromptTemplate(
        id="tpl-shot-001",
        category="分镜",
        title="单镜动态时间轴(蒙哥经典)",
        placeholders=["style", "main_subject", "shot_language",
                      "lighting", "quality_notes",
                      "time_action", "bgm", "sfx", "transition_anchor"],
        content=(
            "{style}。\n"
            '"主体描述":{main_subject}\n'
            '"镜头语言":{shot_language}\n'
            '"环境光影":{lighting}\n'
            '"画质修饰":{quality_notes}\n\n'
            "【动态时间轴动作流】\n{time_action}\n\n"
            "BGM参考:{bgm}\n"
            "音效参考:{sfx}\n"
            "【衔接说明】:本分镜结束姿态({transition_anchor})为下分镜的起始姿态,转场叠化0.3秒。"
        ),
    ),

    # ==================== 拆分镜辅助 ====================
    PromptTemplate(
        id="tpl-helper-001",
        category="拆分镜",
        title="从剧本拆分镜(给 AI 用)",
        placeholders=["script", "duration", "shot_count"],
        content=(
            "你是国际一流的动画电影分镜师。下面是一段剧本,请帮我拆成 {shot_count} 个分镜,"
            "总时长 {duration} 秒。每个分镜必须包含以下 6 个维度:\n"
            "1. 场景(scene)\n"
            "2. 视觉风格(visual style)\n"
            "3. 摄影参数(focal length, depth of field, ISO, aperture)\n"
            "4. 动作设计(action design)\n"
            "5. 光影设计(lighting design)\n"
            "6. 音效设计(sound design)\n\n"
            "并在每镜结尾标注【衔接锚点】:本镜结束姿态描述(必须能作为下一镜的起始姿态)。\n\n"
            "剧本:\n{script}"
        ),
    ),

    # ==================== 普通通用 ====================
    PromptTemplate(id="p-1", category="通用", title="小猫唱歌", placeholders=[],
                   content="生成10秒小猫唱歌视频,要可爱表情,卡通舞台背景,镜头慢推"),
    PromptTemplate(id="p-2", category="通用", title="古风打斗", placeholders=[],
                   content="生成10秒古风打斗视频,水墨风,飞檐走壁,慢动作飞跃"),

    # ==================== M3 AI 辅助:剧本→分镜表 ====================
    PromptTemplate(
        id="tpl-m3-split",
        category="拆分镜",
        title="剧本拆分镜(给 GPT-4o 用,返回 JSON)",
        placeholders=["script", "segment_count", "shots_per_segment", "style", "characters", "scenes"],
        content=(
            "你是国际一流的动画电影分镜师。下面是一段剧本,请帮我拆成 {segment_count} 个 10 秒视频片段,"
            "每段 {shots_per_segment} 个分镜。\n\n"
            "项目风格:{style}\n"
            "已定义角色:{characters}\n"
            "已定义场景:{scenes}\n\n"
            "**输出格式严格 JSON,不要任何解释文字,直接给我 JSON:**\n"
            "```json\n"
            "{{\n"
            '  "segments": [\n'
            '    {{\n'
            '      "number": 1,\n'
            '      "synopsis": "本段剧情",\n'
            '      "shots": [\n'
            '        {{\n'
            '          "number": 1,\n'
            '          "duration": 2.5,\n'
            '          "scene_name": "矿坑内部",\n'
            '          "character_names": ["陆渊"],\n'
            '          "shot_size": "中景",\n'
            '          "camera_movement": "推",\n'
            '          "action": "陆渊低头看左手",\n'
            '          "lighting": "紫光从下方照亮面部",\n'
            '          "sound": "卷轴翻动声",\n'
            '          "dialogue": "",\n'
            '          "transition_anchor": "陆渊低头看手姿态,紫光最亮"\n'
            '        }}\n'
            '      ]\n'
            '    }}\n'
            '  ]\n'
            "}}\n"
            "```\n\n"
            "**硬性要求:**\n"
            "- 每分镜 duration 必须 1.5-3.5 秒之间(单段 10s 装 3-5 个镜头)\n"
            "- 每镜的 transition_anchor 必须能作为下一镜的起始姿态(动作连贯)\n"
            "- character_names 用已定义角色,不要凭空造\n"
            "- shot_size 选项:远景/全景/中景/近景/特写/大特写/过肩/反打\n"
            "- camera_movement 选项:固定/推/拉/摇/移/跟/旋转/俯仰\n\n"
            "**剧本:**\n{script}"
        ),
    ),

    # M3:分镜板大图自动拼装(给 GPT 用)
    PromptTemplate(
        id="tpl-m3-board-compose",
        category="分镜板",
        title="分镜板大图自动拼装(段级)",
        placeholders=["aspect_ratio", "characters_block", "scenes_block", "shots_block",
                      "style", "mood"],
        content=(
            "请生成一张高质量、专业影视预制作风格的故事板设定图,横版 {aspect_ratio},4K 超清,"
            "图文结合,排版清晰,设计感高级。\n\n"
            "**整张图分为五个主要区域,主区采用写实电影感,机位俯视区采用极简 schematic 线稿风格"
            "(灰底白线,与主区视觉风格明显区分,机位用数字编号文字标注,不要红色圆点或摄像机图标):**\n\n"
            "【一、左侧:角色设定区 CHARACTER DESIGN】\n{characters_block}\n\n"
            "【二、中间:场景设计区 ENVIRONMENT】\n{scenes_block}\n\n"
            "【三、中间下方:俯视走位与机位规划区(schematic 线稿风格)】\n"
            "用极简灰底白线绘制俯视图,展示场景中的人物位置、道具摆放、摄影机机位和镜头方向。"
            "机位用阿拉伯数字编号文字标注(1, 2, 3...),不要红色圆点、不要摄像机图标、"
            "不要箭头,只用文字和细线条。\n\n"
            "【四、右侧:8 格故事分镜区 STORYBOARD】\n{shots_block}\n\n"
            "【五、底部:风格说明文字区】\n"
            "灯光/情绪/风格:{style}\n"
            "情绪关键词:{mood}\n\n"
            "**注意:**\n"
            "- 主分镜区(8 格)采用写实电影感,角色和场景细节饱满\n"
            "- 机位俯视区严格保持极简 schematic 线稿风格,不能与主区混淆\n"
            "- 不要在故事板任何区域出现红色圆点、摄像机图标、箭头编号(避免误入视频)"
        ),
    ),
]


def get_template(template_id: str) -> PromptTemplate:
    for t in DEFAULT_PROMPT_TEMPLATES:
        if t.id == template_id: return t
    return None


def render_template(t: PromptTemplate, **kwargs) -> str:
    """安全 format:缺失字段保留 {field} 占位。"""
    class _Safe(dict):
        def __missing__(self, key): return "{" + key + "}"
    try:
        return t.content.format_map(_Safe(kwargs))
    except Exception:
        return t.content
