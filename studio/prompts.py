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
        title="角色三视图定型卡 (简洁版,推荐)",
        placeholders=["style", "name", "gender", "age", "appearance"],
        content=(
            "{style}。生成角色 {name}({gender}, {age}) 的角色定型卡,"
            "8K 超高清,**纯白干净背景**,16:9 横版布局,画面工整、无重叠、无遮挡、"
            "**严格只放人物本体**,人物之间留有清晰间距。"
            "\n\n"
            "**布局要求(严格执行,不要自由发挥)**:\n"
            "- 左侧上下两排,共 6 格**面部多角度肖像**:\n"
            "  · 上排三格:正面表情、左侧 3/4 侧脸、右侧 3/4 侧脸\n"
            "  · 下排三格:正脸放松微笑、侧脸冷峻、半侧脸凝视(各种神情)\n"
            "- 右侧三格:**全身三视图**,标准 A-pose 站姿\n"
            "  · 正面立绘、左侧面立绘、背面立绘\n"
            "- 全身三格之间间距均匀,人物身高对齐\n"
            "\n"
            "**角色外观描述**:{appearance}\n"
            "\n"
            "**一致性要求(关键)**:\n"
            "- 9 格内同一人五官、脸型、发型、发色、肤色、瞳色 100% 一致\n"
            "- 服装(版型/配色/纹样/扣子/腰带/鞋款) 100% 一致\n"
            "- 人体结构精准、无畸变、无穿模、无多余手指\n"
            "\n"
            "**严格禁止(负面词)**:\n"
            "- ❌ 不要武器、不要道具、不要法器、不要持有物\n"
            "- ❌ 不要能量特效、不要粒子、不要光纹、不要符文飘浮\n"
            "- ❌ 不要色彩参考板(palette swatches)、不要材质参考块\n"
            "- ❌ 不要场景背景、不要环境装饰、不要建筑、不要烟雾\n"
            "- ❌ 不要文字标注、不要标签、不要英文标题、不要分数刻度\n"
            "- ❌ 不要 \"专业角色设定板 layout\"、不要 AAA 游戏概念图那种花哨堆叠\n"
            "- ❌ 不要低清晰度、模糊、人物崩坏、Q版、塑料感皮肤"
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
            "**硬性要求 — 违反任何一条都会让生成视频报废,请逐条遵守:**\n"
            "- 🚫 **绝对禁止单段超过 5 镜**。豆包 seedance 把 10s 内塞 6+ 镜会强行赶工、漏镜、动作丢帧。\n"
            "  内容过密时:**多分几段**(每段还是 10s),**不要**把镜数往单段塞。\n"
            "- 每段 shots 数严格在 3-5 之间;少于 3 会让段空荡,多于 5 会赶工。\n"
            "- 每镜 duration 严格 2.0-3.5 秒;单段所有 duration 求和必须 ≈ 10.0 ± 0.5 秒。\n"
            "- 每镜的 transition_anchor 必须能作为下一镜的起始姿态(动作连贯,不跳切)。\n"
            "- character_names 用已定义角色,不要凭空造。\n"
            "- shot_size 选项:远景/全景/中景/近景/特写/大特写/过肩/反打。\n"
            "- camera_movement 选项:固定/推/拉/摇/移/跟/旋转/俯仰。\n\n"
            "**剧本:**\n{script}"
        ),
    ),

    PromptTemplate(
        id="tpl-episode-continue",
        category="拆分镜",
        title="续写下一集剧本(给 GPT 用,基于世界圣经 + 已完成集)",
        placeholders=["world_bible", "past_episodes", "user_brief",
                      "forbidden_reveals", "target_duration_seconds",
                      "next_ep_number"],
        content=(
            "你是一名顶级影视编剧。下面给你 ① 项目的世界圣经,② 已完成的前 N 集剧情摘要,"
            "③ 用户对下一集的方向意图,④ 本集禁止揭露的关键悬念。\n"
            "请根据这些写出**第 {next_ep_number} 集**的完整剧本。\n\n"
            "**输出格式严格 JSON,只输出 JSON 代码块,不要任何前后文字:**\n"
            "```json\n"
            "{{\n"
            '  "title": "第 N 集 · 副标题",\n'
            '  "synopsis": "一句话本集梗概(给观众看的)",\n'
            '  "emotional_arc": "本集情绪曲线,例:平静→焦灼→震惊→悬念",\n'
            '  "script": "本集完整剧情文本(包含台词、动作、转场、留白)",\n'
            '  "world_updates": "本集发生后,应当追加到世界圣经'
            "'已发生事件'里的事实"
            '(用 \\n 分行,每行一条;若没有新事实就空字符串)",\n'
            '  "cliffhanger": "本集结尾的勾子/悬念(给下一集留的钩子,必须有)"\n'
            "}}\n"
            "```\n\n"
            "**绝对硬约束:**\n"
            "- 🚫 **以下悬念绝对不能在本集揭露**(未到时机):\n"
            "  {forbidden_reveals}\n"
            "- ✅ 本集必须**以悬念/勾子结尾**,不能闭合。观众必须想看下一集。\n"
            "- ⚖️ 角色性格、外貌、能力必须严格符合世界圣经,**不要前后矛盾**。\n"
            "- 📏 本集 script 文字目标长度对应 **{target_duration_seconds} 秒**成片,"
            "即约 {target_duration_seconds} ÷ 10 = N 段 × 10s,每段 3-5 镜。\n"
            "  → script 内**用 '【段 N】xxxxxx' 段落分隔**,段数 = 目标秒数 ÷ 10,"
            "便于后续 AI 拆分镜自动按段切。\n"
            "- 🎯 本集要推进至少一个角色弧或一个主线进展,不能纯灌水。\n"
            "- 🎬 这是**电影级连续剧**,不是 15s 爽点短剧 — 节奏可以慢、可以铺、可以留白,"
            "禁止'一集到底'这种短剧手法。\n\n"
            "**① 世界圣经:**\n{world_bible}\n\n"
            "**② 已完成集摘要:**\n{past_episodes}\n\n"
            "**③ 用户对本集的方向意图(可空,空就你自己决定走向):**\n{user_brief}\n"
        ),
    ),


    PromptTemplate(
        id="tpl-m3-doc-parse",
        category="拆分镜",
        title="整篇剧本文档解析(给 GPT 用,返回 JSON)",
        placeholders=["document"],
        content=(
            "你是一位资深的动画项目策划。下面是用户给出的完整剧本文档,里面可能包含:"
            "世界观、角色 Prompt、场景 Prompt、多段剧情台词、故事板梗概、统一风格关键词、负面词等。\n"
            "请你解析这份文档,提取出可作为项目素材的结构化数据。\n\n"
            "**输出格式严格 JSON,不要任何解释或前后文字:**\n"
            "```json\n"
            "{{\n"
            '  "world_setting": "本项目世界观一句话总结(没写则空字符串)",\n'
            '  "style_keywords": "统一风格关键词(逗号分隔),例:东方玄幻,暗黑神话,虚幻5电影CG",\n'
            '  "negative_keywords": "统一负面词(逗号分隔)",\n'
            '  "characters": [\n'
            '    {{\n'
            '      "name": "角色名,例:黑暗天神",\n'
            '      "role": "主角/配角/反派/群演",\n'
            '      "gender": "男/女/未指定",\n'
            '      "age": "年龄段或具体岁数",\n'
            '      "visual_style": "视觉风格,例:东方玄幻暗黑神话",\n'
            '      "hair": "发型 + 发色 + 长度",\n'
            '      "body": "体型 + 大致身高",\n'
            '      "face_shape": "脸型 + 下颌轮廓",\n'
            '      "eye_details": "眼形 + 眼神 + 瞳色等",\n'
            '      "nose_shape": "鼻型",\n'
            '      "lip_shape": "唇形",\n'
            '      "eyebrow_style": "眉形",\n'
            '      "jawline": "下颌线",\n'
            '      "skin_details": "肤色 + 肌肤质感",\n'
            '      "style_lock": "整体气质锁,例:沉稳压迫感",\n'
            '      "notes": "其他设定备注,例:服装/能量特效/法器/标志特征"\n'
            '    }}\n'
            '  ],\n'
            '  "scenes": [\n'
            '    {{\n'
            '      "name": "场景名,例:天界之巅",\n'
            '      "visual_style": "视觉风格",\n'
            '      "asset_description": "整体描述,可直接当 prompt 用",\n'
            '      "fixed_environment": "固定环境元素",\n'
            '      "fixed_lighting": "固定光照",\n'
            '      "fixed_background": "固定背景",\n'
            '      "notes": "氛围词等额外备注"\n'
            '    }}\n'
            '  ],\n'
            '  "episodes": [\n'
            '    {{\n'
            '      "title": "第一集 / 黑暗天神归来 等",\n'
            '      "synopsis": "本集梗概",\n'
            '      "emotional_arc": "情绪曲线,例:平静→惊愕→恐慌→决绝",\n'
            '      "script": "本集的剧情台词+动作文本(给 AI 拆分镜继续处理用)"\n'
            '    }}\n'
            '  ]\n'
            "}}\n"
            "```\n\n"
            "**硬性要求:**\n"
            "- 文档里 \"## 黑暗天神 三视图 Prompt\" 这类章节,务必逐一提取成 character\n"
            "- \"## 场景 Prompt / ## 天界之巅\" 这类务必提取成 scene\n"
            "- \"## 10秒短剧开篇\" 或 \"## 故事板\" 类章节合并提取成 episode(同一集可包含多段)\n"
            "- script 字段只放剧情台词+动作,**不要把 Prompt 章节塞进 script**\n"
            "- **如果文档里已经明确分段(如'第一段故事板'、'【0-2秒】'),"
            "请把分段标题保留在 script 里作为段落分隔(便于后续 AI 拆分镜时按段切)。**\n"
            "- 每段对应一个 10 秒视频(豆包硬上限),后续拆分镜会按段创建 3-5 镜/段。\n"
            "  所以 episode.script 里的段落数 = 后续视频段数 = 10 秒视频数。\n"
            "- 字段不知道就给空字符串,**不要凭想象编造**\n"
            "- 角色字段值要具体可视觉化,避免'普通'、'标准'这种模糊词\n\n"
            "**剧本文档:**\n{document}"
        ),
    ),

    # 老的拆分镜模板
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

    # ==================== 用户实战框架:故事板大图(参考图N + 6维度) ====================
    PromptTemplate(
        id="tpl-storyboard-master",
        category="分镜板",
        title="故事板大图主框架(参考图N 实战版)",
        placeholders=[
            "style", "main_subject", "shot_language", "lighting", "quality_notes",
        ],
        content=(
            "按照这个故事板参考图1来创作广告/电影。动态的摄像机运动,"
            "镜头中不出现摄像机设备,故事=\n"
            "{style}。"
            '"主体描述":"{main_subject}",'
            '"镜头语言":"{shot_language}",'
            '"环境光影":"{lighting}",'
            '"画质修饰":"{quality_notes}"\n'
            "这上面是故事。\n"
            "避免场景过于相似创建一个电影制作板/视觉规划表,比例16:9,展示短片或商业广告的完整概念。"
            "布局应简洁、基于网格,并分为清晰标记的部分。 包含:"
            "共享创意指导(顶部栏):整体限制,如镜头数量、统一的调色板和一般的环境背景。"
            "角色与风格参考部分:一个从多个角度展示的模型(正面、背面、侧面、特写、放松姿态),"
            "配有服装和配饰参考。强调身份的一致性,同时允许在特定场景中进行细微变化。 "
            "环境和场景设计部分:一个具有戏剧性自然特征的场景户外地点,以及一个俯视示意图,"
            "说明在空间中的移动路径。包括摄像机位置和沿路线标注的拍摄类型。 "
            "故事板部分:一系列编号的帧(大约8个镜头)展示场景的进展。"
            "每个帧包括:摄像机类型/镜头感觉 镜头大小(广角、中景、特写、微距) "
            "运动方式(静态、跟踪、手持等) 动作和情绪进展的简要描述 "
            "灯光/情绪/风格备注:与灯光条件、氛围和纹理相关的视觉示例和简短描述。"
            "包括一天中不同时间的过渡和光线质量的变化。 "
            "情绪和关键词块:指导作品的简洁情绪基调主题描述列表。 "
            "音频/音调部分:环境声音、音乐风格和整体声音氛围的指示。 "
            "电影摄影笔记:包括镜头特性、运动风格和后期处理感觉的总体视觉哲学。 "
            "整个版面应感觉连贯、电影化且专业设计——就像导演的预制作指南,"
            "能一眼传达出基调、节奏和视觉叙事。"
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
