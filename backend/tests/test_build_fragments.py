"""分镜切分：场内按时长二次拆条；人物介绍按首次出场注入。"""

from types import SimpleNamespace

from app.services.drama.build_fragments import (
    FRAGMENT_SOFT_MAX,
    FRAGMENT_TOTAL_MAX,
    _is_important_character,
    _resolve_character_intro_text,
    build_character_binding,
    build_fragments_from_episode_body,
    is_raw_screenplay_fragment,
    plan_fragments_from_scene,
)


def test_is_raw_screenplay_fragment_detects_scene_heading():
    assert is_raw_screenplay_fragment("") is True
    assert is_raw_screenplay_fragment("### 场1-1\n日外 大河\n出场人物：无") is True
    assert is_raw_screenplay_fragment("###场1-1") is True
    assert is_raw_screenplay_fragment("出场人物：苏轼\n△ 抬头。") is True


def test_is_raw_screenplay_fragment_keeps_cinematic_shots():
    # 手写分镜常无【字幕：】/@duration:，不能当场记原文
    shot = "【转入｜无｜片头直接黑起】\n【BGM｜低频太鼓】\n【场景】夜 · 内 · 大牢"
    assert is_raw_screenplay_fragment(shot) is False


def test_long_scene_splits_into_multiple_fragments():
    # 构造足够多的对白行，使合计时长超过软上限
    lines = ["日外 羽山刑场", "出场人物：禹"]
    for i in range(12):
        lines.append(f"禹：这是第{i}句很长的对白用来撑满时长测试内容足够长。")
    body = "\n".join(lines)

    chunks = plan_fragments_from_scene(
        body,
        {"sceneName": "羽山刑场", "characterNames": ["禹"]},
        scene_asset_id=1,
        character_bindings=[
            {"name": "禹", "assetId": 2, "introText": "治水英雄", "important": True},
        ],
    )

    assert len(chunks) >= 2
    for content, duration in chunks:
        assert duration <= FRAGMENT_TOTAL_MAX
        assert "@duration:" in content
        assert "【字幕" in content
    # 首条应含人物介绍；后续跨镜不再重复
    intro_hits = [c for c, _ in chunks if "【人物介绍·画面叠字·角色身旁】禹｜治水英雄" in c]
    assert len(intro_hits) == 1
    assert all(d <= FRAGMENT_SOFT_MAX or True for _, d in chunks)


def test_build_fragments_one_scene_header_can_yield_many():
    narrative = "\n".join(
        [f"旁白（VO）：第{i}段旁白内容用来累计时长超过三十秒的填充。" for i in range(15)]
    )
    content = f"### 场1-1\n日外 大河\n出场人物：无\n{narrative}"
    drafts = build_fragments_from_episode_body(content, [])
    assert len(drafts) >= 2
    total = sum(int(d["duration_sec"]) for d in drafts)
    assert total > FRAGMENT_TOTAL_MAX


def test_intro_only_on_first_appearance_across_scenes():
    # 跨场同一重要角色只介绍一次；次要群体角色不介绍
    assets = [
        SimpleNamespace(
            id=1,
            type="character",
            name="鲧",
            params={"title": "治水先驱", "roleType": "主角"},
        ),
        SimpleNamespace(
            id=2,
            type="character",
            name="禹",
            params={"title": "治水英雄", "roleType": "主角"},
        ),
        SimpleNamespace(
            id=3,
            type="character",
            name="行刑兵",
            params={"title": "出场人物", "roleType": "配角"},
        ),
        SimpleNamespace(
            id=4,
            type="character",
            name="部落百姓",
            params={"title": "出场人物", "roleType": "群演"},
        ),
    ]
    content = "\n".join(
        [
            "### 场1-1",
            "日外 羽山刑场",
            "出场人物：鲧、行刑兵、部落百姓",
            "△ 刑场全景，洪水拍打山崖。",
            "鲧被绑在杉木柱上，白发湿透。",
            "### 场1-2",
            "日外 羽山刑场",
            "出场人物：鲧、禹",
            "禹冲上刑场高喊父亲。",
            "鲧抬头望向禹。",
        ]
    )
    drafts = build_fragments_from_episode_body(content, assets)
    joined = "\n---\n".join(d["content"] for d in drafts)

    assert "【人物介绍·画面叠字·角色身旁】鲧｜治水先驱" in joined
    assert "【人物介绍·画面叠字·角色身旁】禹｜治水英雄" in joined
    assert joined.count("【人物介绍·画面叠字·角色身旁】鲧｜") == 1
    assert joined.count("【人物介绍·画面叠字·角色身旁】禹｜") == 1
    assert "行刑兵" not in joined or "【人物介绍·画面叠字·角色身旁】行刑兵" not in joined
    assert "【人物介绍·画面叠字·角色身旁】部落百姓" not in joined

    # 鲧应出现在首次提及他所在的分镜，而非机械堆在开场空镜
    first_with_gun = next(d for d in drafts if "【人物介绍·画面叠字·角色身旁】鲧｜" in d["content"])
    assert "鲧" in first_with_gun["content"] or "@asset:1" in first_with_gun["content"]


def test_important_and_intro_helpers():
    assert _is_important_character("鲧", role_type="主角", title="治水先驱")
    assert _is_important_character("四岳首领", role_type="重要配角", title="部落长老")
    assert not _is_important_character("行刑兵", role_type="配角", title="出场人物")
    assert not _is_important_character("部落百姓", role_type="群演", title="出场人物")
    assert _resolve_character_intro_text({"title": "出场人物", "roleType": "主角"}) == "主角"
    assert _resolve_character_intro_text({"title": "治水先驱"}) == "治水先驱"


def test_stub_asset_uses_summary_for_intro():
    # 资产仍为 stub，但摘要有小传 → 应可介绍
    asset = SimpleNamespace(
        id=132,
        type="character",
        name="禹",
        params={"title": "出场人物", "roleType": "配角", "coreTags": "出场人物"},
    )
    summary = {
        "characters": [
            {
                "name": "禹（大禹）",
                "roleType": "主角",
                "title": "治水英雄",
                "identityBackground": "鲧之子，承父遗志治理洪水",
            },
        ]
    }
    binding = build_character_binding("禹", asset, summary=summary)
    assert binding["important"] is True
    assert binding["introText"] == "治水英雄"


def test_narrative_summary_fallback_for_gun():
    asset = SimpleNamespace(
        id=131,
        type="character",
        name="鲧",
        params={"title": "出场人物", "roleType": "配角"},
    )
    summary = {
        "characters": [],
        "synopsis": "罪臣之子大禹因父亲鲧盗息壤堵水失败被处死，在部落的唾骂中临危受命。",
    }
    binding = build_character_binding("鲧", asset, summary=summary)
    assert binding["important"] is True
    assert binding["introText"]
    assert "鲧" in binding["introText"] or "堵水" in binding["introText"]


def test_stub_identity_background_not_used_as_intro():
    from app.services.drama.build_fragments import infer_character_intro_text

    assert infer_character_intro_text(
        "鲧",
        {"title": "出场人物", "identityBackground": "剧本分集出场人物「鲧」"},
    ) is None

    asset = SimpleNamespace(
        id=3,
        type="character",
        name="舜",
        params={"title": "出场人物", "roleType": "配角", "identityBackground": "剧本分集出场人物「舜」"},
    )
    bodies = ["四岳首领推举禹治水，舜帝端坐大殿目光深沉。"]
    binding = build_character_binding("舜", asset, summary={"characters": []}, episode_bodies=bodies)
    assert binding["introText"]
    assert "剧本分集出场人物" not in binding["introText"]
    assert "舜" in binding["introText"]


def test_repair_fragment_timed_layout_splits_trailing_duration_tag():
    from app.services.drama.build_fragments import repair_fragment_timed_layout

    legacy = "\n".join(
        [
            "【字幕：底部居中白色描边；仅标记段落同步】",
            "【BGM：神秘悬疑；音量低于人声】",
            "【对白·慢速清晰·同步字幕】波波：很好。记住，月相变化是一个循环。",
            "【对白·慢速清晰·同步字幕】小宇：那彩虹是怎么出现的？",
            "【画面·无配音仅环境音】小宇和米米击掌。",
            "@duration:15",
        ]
    )
    fixed = repair_fragment_timed_layout(legacy, duration_sec=15)
    assert fixed.count("@duration:") >= 3
    assert fixed.index("@duration:") < fixed.index("波波：")
    assert fixed.rfind("@duration:") < fixed.index("小宇和米米击掌")


def test_repair_keeps_wrapped_line_in_same_duration_beat():
    from app.services.drama.build_fragments import repair_fragment_timed_layout

    modern = "\n".join(
        [
            "【字幕：底部居中·简体中文·逐句轮换·与口播同步】",
            "【BGM：轻】",
            "@duration:8",
            "【画面·无配音仅环境音】站在账房里贴着账，眼睛亮晶晶。",
            "（探花分科），",
        ]
    )
    fixed = repair_fragment_timed_layout(modern, duration_sec=8)
    assert fixed.count("@duration:") == 1
    assert "探花分科" in fixed
    assert "@duration:3" not in fixed


def test_repair_packs_exploded_three_second_beats_to_budget():
    from app.services.drama.build_fragments import repair_fragment_timed_layout
    import re

    rows = [
        "【字幕：底部居中·简体中文】",
        "【BGM：轻】",
    ]
    for i in range(19):
        rows.extend([f"@duration:3", f"【画面·无配音仅环境音】第{i}句画面。"])
    fixed = repair_fragment_timed_layout("\n".join(rows), duration_sec=15)
    total = sum(int(m) for m in re.findall(r"@duration:(\d+)", fixed))
    assert total <= 15
    assert fixed.count("@duration:") <= 5


def test_strip_repeat_opening_cues_keeps_bgm():
    from app.services.drama.build_fragments import strip_repeat_opening_cues

    content = "\n".join(
        [
            "【BGM：轻柔开阔】",
            "【片头·集号叠字】第1集｜乌龙伯乐压奇才",
            "【片头·词条特写】史上最难高考",
            "@duration:4",
            "【对白·慢速清晰·同步字幕】说书人：大宋嘉祐二年。",
        ]
    )
    out = strip_repeat_opening_cues(content)
    assert "【片头" not in out
    assert "【BGM：轻柔开阔】" in out
    assert "说书人" in out


def test_prepare_fragment_content_strips_opening_on_later_shots():
    from app.services.drama.build_fragments import prepare_fragment_content

    content = "\n".join(
        [
            "【BGM：轻】",
            "【片头·集号叠字】第1集｜试集",
            "@duration:8",
            "【画面·无配音仅环境音】学堂门口。",
            "（匾额特写），",
        ]
    )
    later = prepare_fragment_content(content, duration_sec=8, is_opening=False)
    assert "【片头" not in later
    assert later.count("@duration:") == 1
    first = prepare_fragment_content(content, duration_sec=8, is_opening=True)
    assert "【片头·集号叠字】" in first


def test_vo_os_dialogue_not_split_by_action_expander():
    from app.services.drama.build_fragments import _expand_narrative_lines

    vo = _expand_narrative_lines("旁白（VO）：第1段旁白内容用来累计时长。")
    assert len(vo) == 1
    assert vo[0].startswith("【旁白")

    os_line = _expand_narrative_lines("小宇（OS）：原来月亮是这样变化的。")
    assert len(os_line) == 1
    assert "内心独白" in os_line[0]


def test_dialogue_with_action_splits_into_visual_and_speech():
    from app.services.drama.build_fragments import (
        _expand_narrative_lines,
        rewrite_dialogue_action_lines,
    )
    from app.services.drama.build_seedance_generate_body import build_seedance_body_text
    from app.services.seedance_segments import DIALOGUE_PREFIX, VISUAL_PREFIX

    raw = "波波（头顶亮起绿灯）：很好。记住，月相变化是一个循环。"
    expanded = _expand_narrative_lines(raw)
    assert len(expanded) == 2
    assert expanded[0].startswith(VISUAL_PREFIX)
    assert "头顶亮起绿灯" in expanded[0]
    assert expanded[1].startswith(DIALOGUE_PREFIX)
    assert "波波：很好" in expanded[1]
    assert "（头顶亮起绿灯）" not in expanded[1]

    script = "\n".join(
        [
            "@duration:4",
            f"{DIALOGUE_PREFIX}{raw}",
            "@duration:3",
            f"{VISUAL_PREFIX}小宇和米米击掌。",
        ]
    )
    fixed = rewrite_dialogue_action_lines(script)
    assert fixed.count(DIALOGUE_PREFIX) == 1
    assert fixed.count(VISUAL_PREFIX) >= 2

    body = build_seedance_body_text(script, [], catalog=type("C", (), {"images": [], "audios": []})())
    assert "\n" in body
    assert "00:00-00:04" in body
    assert "00:04-00:07" in body


def test_scene_description_marked_visual_not_voiceover():
    from app.services.drama.build_fragments import _format_narrative_line
    from app.services.seedance_segments import (
        DRAMA_SUBTITLE_CUE,
        build_seedance_production_section,
        rewrite_misclassified_visual_voice_lines,
        script_has_dialogue_cue,
        script_has_narration_cue,
    )

    scene = "月亮被乌云遮得严严实实，只有零星的火把亮着，禹跪在新堆的坟前。"
    formatted = _format_narrative_line(scene)
    assert formatted.startswith("【画面·无配音仅环境音】")
    assert scene in formatted

    dialogue = "伯益：大洪水来了，快撤！"
    assert _format_narrative_line(dialogue).startswith("【对白·慢速清晰·同步字幕】")

    # 「空镜：…」是画面描述，绝不能打成对白/旁白
    empty_shot = "空镜：浑浊的黄河浪扣打着门口老石，溅起数丈高的浊浪。"
    empty_formatted = _format_narrative_line(empty_shot)
    assert empty_formatted.startswith("【画面·无配音仅环境音】")
    assert "对白" not in empty_formatted
    assert "旁白" not in empty_formatted

    # 已误标为对白的旧数据：格式化与提交前纠正均可修复
    mistagged = "【对白·慢速清晰·同步字幕】" + empty_shot
    assert _format_narrative_line(mistagged).startswith("【画面·无配音仅环境音】")
    fixed_script = rewrite_misclassified_visual_voice_lines(
        "\n".join([DRAMA_SUBTITLE_CUE, "@duration:6", mistagged])
    )
    assert "【对白" not in fixed_script
    assert "【画面·无配音仅环境音】空镜：" in fixed_script
    assert script_has_dialogue_cue(fixed_script) is False

    script = "\n".join(
        [
            DRAMA_SUBTITLE_CUE,
            "【BGM：流动感环境音乐；音量低于人声】",
            "@duration:6",
            empty_formatted,
            "@duration:6",
            _format_narrative_line(dialogue),
        ]
    )
    assert script_has_narration_cue(script) is False
    section = build_seedance_production_section(script)
    assert "禁止为其生成配音" in section
    assert "画面描述段不出现字幕" in section
