"""获客短视频模板（并入科普模板库）。

结构来自共创营销 Demo 四平台骨架（小红书 / 抖音 / 点评 / 朋友圈）：
钩子→印象→分点体验→推荐给谁；0–3 秒钩子→画面→1–2 体验→CTA；
总体评价→环境服务→推荐理由→性价比→适合谁；一句感受→一个细节→轻推荐。

铁律：不编造用户没写的体验；卖点只能客观陈述；不用广告法绝对化用语。
category[0] 固定为「科普」，便于首页科普筛选；另挂「获客」「商业」。
sort_order 0–3：创建页「热门推荐」与默认模板会优先落到这四条。
"""

# 四条模板共用：事实边界 + 人称边界 + 合规（写入 llm_system_addon 前缀）
HUOKE_IRON_RULES = (
    "【获客铁律】只使用用户文案里出现的事实；没写到的价格、项目、口感、效果、服务细节一个字都不许编。"
    "信息不够就写短，绝不用想象补齐。"
    "【人称边界】第一人称（我试了/我看到/对我们）只能来自用户原文；"
    "商家卖点只能写成客观陈述（「他们家主打X」），禁止写成「我用了X特别好」。"
    "用户没提到的卖点不得放进「真实体验」分点。"
    "【合规】禁止最、第一、国家级、100%、永久、根治等绝对化用语；数字以用户文案为准；"
    "禁止编造成功率、案例人数、名人背书。"
    "【名称】用户文案里出现的店名、地址、产品名必须原样保留，禁止改成某店/某品牌；文案没有的名称一律不许编。"
    "【口播】短句口语，禁止通版广告腔。"
)

# 叠字：竖屏获客片顶部大字 + 底部口播字幕
_HUOKE_SUB_SPLIT = {
    "font": "SourceHanSans",
    "position": "split",
    "title_scale": 1.65,
    "sub_scale": 1.45,
    "caption_scale": 1.28,
}


def _tpl(
    *,
    tid: str,
    name: str,
    description: str,
    style_prefix: str,
    negative_prompt: str,
    default_ratio: str,
    shot_duration_min: int,
    shot_duration_max: int,
    structure_addon: str,
    seedream_config: dict,
    seedance_config: dict,
    audio_config: dict,
    subtitle_config: dict,
    sort_order: int,
    photoreal: bool = False,
    shot_count_min: int = 3,
    shot_count_max: int = 5,
) -> dict:
    """组装一条获客科普模板，字段与 TEMPLATES 条目一致。"""
    cfg = dict(seedream_config)
    if photoreal:
        cfg["photoreal"] = True
    cfg["shot_count_min"] = shot_count_min
    cfg["shot_count_max"] = shot_count_max
    cfg["allow_source_names"] = True
    return {
        "id": tid,
        "name": name,
        "description": description,
        "category": ["科普", "获客", "商业"],
        "preview_cover": f"/static/templates/covers/{tid}.png",
        "style_prefix": style_prefix,
        "negative_prompt": negative_prompt,
        "default_ratio": default_ratio,
        "shot_duration_min": shot_duration_min,
        "shot_duration_max": shot_duration_max,
        "llm_system_addon": HUOKE_IRON_RULES + structure_addon,
        "seedream_config": cfg,
        "seedance_config": seedance_config,
        "audio_config": audio_config,
        "subtitle_config": subtitle_config,
        "sort_order": sort_order,
        "is_active": True,
        "is_premium": False,
    }


HUOKE_TEMPLATES: list[dict] = [
    _tpl(
        tid="huoke_douyin_hook",
        name="获客·抖音钩子",
        description="竖屏口播节奏：前 3 秒钩子→场景画面→1–2 个可核验体验→到店/下单号召。适合投放获客。",
        style_prefix=(
            "竖屏获客短视频静帧：门店外立面、产品特写、服务动作或操作界面交替出现，"
            "强对比自然光，主体清晰、留白便于叠大字，电影级产品演示质感，非卡通非动漫"
        ),
        negative_prompt=(
            "卡通，动漫，赛璐璐，二次元，霓虹赛博大屏，任务清单，画面乱码文字，"
            "字幕水印，logo 乱码，虚假奖杯证书，夸张促销海报堆叠"
        ),
        default_ratio="9:16",
        shot_duration_min=3,
        shot_duration_max=6,
        structure_addon=(
            "这是抖音获客口播片。【分镜数量】按 3–4 镜拆，忽略更长的默认区间；"
            "事实不够就合并节拍，宁可少镜也不许编。"
            "节拍：①【0-3秒钩子】反差/悬念/痛点，title 极短；"
            "②【场景画面】交代在哪、做什么，只写用户文案里有的场景；"
            "③【核心体验】最多 2 个可核验点，禁止凑满去编；"
            "④【行动号召】到店/下单/私信的具体下一步，不承诺结果。"
            "每镜 segments：visual 与 narration 交替；旁白短句能一口气读完；"
            "title=钩子词，subtitle=卖点客观句，text=口播。"
        ),
        seedream_config={
            "ref_images": [],
            "strength": 0.72,
            "consistency_mode": "style",
            "extra_prompt": (
                "竖屏主体清晰，顶部与底部留白叠字；各镜构图必须不同；画面内不要出现文字"
            ),
        },
        seedance_config={
            "motion_bias": "轻微手持推进，产品或门店细节切换",
            "character_consistency": False,
            "generate_audio": True,
        },
        audio_config={"voice_preset": "urban_editorial", "bgm_mood": "轻快专业"},
        subtitle_config=dict(_HUOKE_SUB_SPLIT),
        sort_order=0,
        photoreal=True,
        shot_count_min=3,
        shot_count_max=4,
    ),
    _tpl(
        tid="huoke_xhs_recommend",
        name="获客·小红书安利",
        description="竖屏闺蜜安利结构：钩子标题→第一印象→分点真实体验→推荐给谁。封面信息量高、口语化。",
        style_prefix=(
            "竖屏生活安利静帧：明亮自然光，浅色桌面或门店角落，产品/空间细节清楚，"
            "杂志封面气质、留白分层，适合叠标题，非浓妆棚拍、非卡通"
        ),
        negative_prompt=(
            "阴暗脏乱，赛博霓虹，卡通动漫，硬广海报堆字，假抠图，水印乱码"
        ),
        default_ratio="9:16",
        shot_duration_min=4,
        shot_duration_max=8,
        structure_addon=(
            "这是小红书获客安利片。【分镜数量】按 3–5 镜拆，忽略更长的默认区间；"
            "事实不够就少镜，禁止编体验凑镜。"
            "节拍：①钩子标题（情绪或反差，不像广告）；"
            "②我为什么来 / 第一印象（只来自用户原文）；"
            "③分点真实体验（每镜一个细节）；"
            "④推荐给谁 / 值不值得（场景来自文案，给不出就客观收束）。"
            "口播像跟闺蜜说话；title 短、subtitle 带一个具体细节。"
            "每镜 segments：visual 与 narration 交替。"
        ),
        seedream_config={
            "ref_images": [],
            "strength": 0.7,
            "consistency_mode": "style",
            "extra_prompt": "明亮竖屏，顶部大留白叠标题，画面内不要出现文字，各镜场景不同",
        },
        seedance_config={
            "motion_bias": "缓慢平移与轻微推近细节",
            "character_consistency": False,
            "generate_audio": True,
        },
        audio_config={"voice_preset": "warm_storyteller", "bgm_mood": "温暖人文"},
        subtitle_config=dict(_HUOKE_SUB_SPLIT),
        sort_order=1,
        photoreal=True,
        shot_count_min=3,
        shot_count_max=5,
    ),
    _tpl(
        tid="huoke_review_facts",
        name="获客·口碑拆解",
        description="横屏客观详实：总体评价→环境/服务→推荐项+理由→性价比→适合谁。帮别人做决策，不抒情。",
        style_prefix=(
            "干净讲解静帧：浅色桌面或门店信息分区，产品/空间/价目氛围（无可读文字），"
            "信息层级清楚、光线均匀，纪录片式克制，非卡通非霓虹"
        ),
        negative_prompt=(
            "卡通，动漫，夸张表情包，霓虹赛博，假证书奖杯，画面乱码文字，促销爆炸贴"
        ),
        default_ratio="16:9",
        shot_duration_min=5,
        shot_duration_max=10,
        structure_addon=(
            "这是口碑/点评式获客讲解片。【分镜数量】按 3–5 镜拆，忽略更长的默认区间；"
            "没写到的栏目直接跳过，禁止编事实凑镜。"
            "节拍：①总体评价一句话（来自用户文案，禁止自行打分）；"
            "②环境或服务（只写提到的）；"
            "③推荐项+具体理由（理由必须来自原文）；"
            "④人均与性价比（用户没写价格就不要猜，改讲「怎么选」）；"
            "⑤适合场景与结论（给谁来、不适合谁，不承诺效果）。"
            "旁白像认真写评价，信息密度高、少形容词。"
            "每镜 segments：visual 与 narration 交替；title=栏目名，subtitle=可核验短句。"
        ),
        seedream_config={
            "ref_images": [],
            "strength": 0.7,
            "consistency_mode": "style",
            "extra_prompt": "横屏讲解构图，左右或上下留白叠字，画面内不要出现文字，各镜明显不同",
        },
        seedance_config={
            "motion_bias": "缓慢推近产品或空间细节",
            "character_consistency": False,
            "generate_audio": True,
        },
        audio_config={"voice_preset": "narrator_calm", "bgm_mood": "冷静纪实"},
        subtitle_config={
            "font": "SourceHanSans",
            "position": "split",
            "title_scale": 1.5,
            "sub_scale": 1.35,
            "caption_scale": 1.2,
        },
        sort_order=2,
        photoreal=True,
        shot_count_min=3,
        shot_count_max=5,
    ),
    _tpl(
        tid="huoke_soft_invite",
        name="获客·熟人轻推",
        description="竖屏生活化短片：一句真实感受→一个具体细节→一句轻推荐。克制、不像广告，适合转发给熟人。",
        style_prefix=(
            "竖屏生活纪实静帧：窗光、街角、桌面一角或门店日常，暖色克制，"
            "真实材质与皮肤，像随手拍的一张，非棚拍硬广、非卡通"
        ),
        negative_prompt=(
            "棚拍浓妆，硬广海报，卡通动漫，霓虹赛博，假笑模特，水印乱码，爆炸贴"
        ),
        default_ratio="9:16",
        shot_duration_min=4,
        shot_duration_max=8,
        structure_addon=(
            "这是朋友圈/熟人获客短片。【分镜数量】按 2–3 镜拆，忽略更长的默认区间；更短更好。"
            "节拍：①一句真实感受（尽量靠近用户原话语感）；"
            "②一个具体细节或画面（只取文案里最具体的那一点）；"
            "③可选轻推荐（想来可以问我 / 自己去看看），不要强 CTA、不要优惠堆砌。"
            "不加话题标签腔；emoji 不要写进旁白。"
            "每镜 segments：visual 与 narration 交替；title 极短或不抢戏。"
        ),
        seedream_config={
            "ref_images": [],
            "strength": 0.72,
            "consistency_mode": "style",
            "character_prompt": "生活感路人视角，可露侧脸或只出手部与场景，着装日常，全片气质统一",
            "extra_prompt": "暖色窗光，竖屏生活感，顶部可留白，画面内不要出现文字",
        },
        seedance_config={
            "motion_bias": "轻微手持呼吸感，缓慢平移",
            "character_consistency": False,
            "generate_audio": True,
        },
        audio_config={"voice_preset": "warm_storyteller", "bgm_mood": "温暖人文"},
        subtitle_config={"font": "SourceHanSans", "position": "top", "caption_scale": 1.25},
        sort_order=3,
        photoreal=True,
        shot_count_min=2,
        shot_count_max=3,
    ),
]
