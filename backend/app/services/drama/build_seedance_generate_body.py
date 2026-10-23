"""组装漫剧分镜提交 Seedance 的多模态请求体。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, TypedDict

from app.config import get_settings
from app.services.logical_model_router import resolve_logical_model_id, resolve_upstream_model
from app.models_drama import DramaAsset
from app.services.drama.build_fragments import rewrite_dialogue_action_lines
from app.services.drama.fragment_content_duration import (
    replace_duration_mentions_with_time_ranges,
    resolve_seedance_duration_from_content,
)
from app.services.drama.image_styles import (
    STYLE_BOARD_PROMPT_HINT,
    resolve_image_style_prompt,
)
from app.services.seedance_segments import (
    VOICE_CUE_PREFIX_RE,
    build_seedance_production_section,
    classify_voice_body,
    is_production_meta_line,
    rewrite_misclassified_visual_voice_lines,
    script_has_narration_cue,
    strip_character_intro_cues,
    strip_model_burn_subtitle_cues,
)

ASSET_MENTION_TOKEN_PATTERN = re.compile(r"@asset:(\d+)")
# 仅压缩行内空白，保留换行以便 Seedance 按时间轴段落演绎
INLINE_WHITESPACE_PATTERN = re.compile(r"[^\S\n]+")

SEEDANCE_VISUAL_STYLE_SECTION_INTRO = (
    "【强制约束：视频画面风格】全片画面必须严格遵循以下风格描述，"
    "严禁偏离、弱化或混用其他画风与镜头美学："
)
# 音色难控：暂不提交 reference_audio、不写音色约束；口播由 Seedance generate_audio 自发挥。
# 恢复绑定/提交时改回 True。
SEEDANCE_ATTACH_REFERENCE_AUDIO = False
SEEDANCE_CHARACTER_VOICE_SECTION_HEADER = (
    "【强制约束：角色音色】以下角色说话的音色、语气、节奏与发声质感必须与对应参考音频严格一致，"
    "语速自然偏慢、吐字清晰，严禁加速赶词、替换、混用其他声线或自行改写："
)
SEEDANCE_NARRATION_VOICE_SECTION_HEADER = (
    "【强制约束：旁白音色】以下旁白说话的音色、语气、节奏与发声质感必须与对应参考音频严格一致，"
    "语速自然偏慢、吐字清晰，严禁加速赶词、替换、混用其他声线或自行改写："
)
SEEDANCE_CHARACTER_APPEARANCE_SECTION_HEADER = (
    "【强制约束：角色形象】以下角色的面容、体型、发型、服饰与整体气质必须与对应参考图严格一致，"
    "严禁换脸、形象漂移或重绘为其他人物："
)
SEEDANCE_SCENE_SECTION_HEADER = (
    "【强制约束：场景】以下场景的空间结构、环境陈设、光影氛围必须与对应参考图严格一致，"
    "严禁替换为其他场景或大幅偏离参考画面："
)
SEEDANCE_PROP_SECTION_HEADER = (
    "【强制约束：道具】以下道具的外形、材质与关键细节必须与对应参考图严格一致，"
    "严禁替换为其他物品或丢失标志性特征："
)


class BuildSeedanceGenerateBodyInput(TypedDict, total=False):
    content: str | None
    reference: list[dict[str, Any]] | None
    model_id: str | None
    aspect_ratio: str | None
    resolution: str | None
    video_style_id: str | None
    duration_fallback: int | None
    # 上一镜尾帧公网/本地 URL；有参考媒体时作 reference_image（不可与 first_frame 混用）
    continuity_first_frame_url: str | None
    # 画风板公网 URL（角色/场景图之后、衔接尾帧之前）
    style_board_url: str | None
    # True=模型烧录字幕；False=后期叠字（禁止画面内字幕）
    burn_subtitles: bool
    # True=角色身旁人物介绍叠字；False=禁止人物介绍字卡
    character_intro: bool


# 兼容历史布尔 / 字符串，解析分集 params 开关
def _resolve_episode_bool_flag(
    params: dict[str, Any] | None,
    *,
    mode_key: str,
    enabled_key: str,
    on_mode: str,
    off_mode: str,
    default: bool = True,
) -> bool:
    raw = params if isinstance(params, dict) else {}
    mode = raw.get(mode_key)
    if mode == off_mode:
        return False
    if mode == on_mode:
        return True
    enabled = raw.get(enabled_key)
    if enabled is None:
        return default
    if isinstance(enabled, str):
        return enabled.strip().lower() not in {"0", "false", "no", "off", ""}
    if isinstance(enabled, (int, float)):
        return enabled != 0
    return bool(enabled)


# 从分集 params 解析是否由模型烧录字幕（默认后期拼接 → False）
def resolve_episode_burn_subtitles(params: dict[str, Any] | None) -> bool:
    return _resolve_episode_bool_flag(
        params,
        mode_key="subtitleMode",
        enabled_key="subtitleEnabled",
        on_mode="model",
        off_mode="post",
        default=False,
    )


# 从分集 params 解析是否注入人物介绍叠字（默认关闭 → False）
def resolve_episode_character_intro(params: dict[str, Any] | None) -> bool:
    return _resolve_episode_bool_flag(
        params,
        mode_key="characterIntroMode",
        enabled_key="characterIntroEnabled",
        on_mode="model",
        off_mode="off",
        default=False,
    )


@dataclass
class SeedanceReferenceFile:
    asset_id: int
    url: str


@dataclass
class SeedanceReferenceCatalog:
    images: list[SeedanceReferenceFile] = field(default_factory=list)
    audios: list[SeedanceReferenceFile] = field(default_factory=list)
    image_index_by_asset_id: dict[int, int] = field(default_factory=dict)
    audio_index_by_asset_id: dict[int, int] = field(default_factory=dict)


# 将 ORM 资产转为 Seedance 引用 payload
def drama_asset_to_payload(asset: DramaAsset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "type": asset.type,
        "assetType": asset.asset_type,
        "name": asset.name,
        "cover": asset.cover,
        "url": asset.url,
        "params": asset.params or {},
    }


# 读取角色绑定的参考音频 URL（兼容 voiceAudio 与 canvas.voiceAudio）
def read_asset_voice_audio_url(params: Any) -> str | None:
    if not isinstance(params, dict):
        return None

    for key in ("voiceAudio",):
        voice_audio = params.get(key)
        if isinstance(voice_audio, dict):
            url = voice_audio.get("url") or voice_audio.get("previewUrl")
            if isinstance(url, str) and url.strip():
                return url.strip()

    canvas = params.get("canvas")
    if isinstance(canvas, dict):
        voice_audio = canvas.get("voiceAudio")
        if isinstance(voice_audio, dict):
            url = voice_audio.get("url") or voice_audio.get("previewUrl")
            if isinstance(url, str) and url.strip():
                return url.strip()

    return None


# 解析资产可用的图片 URL
def resolve_reference_image_url(asset: dict[str, Any]) -> str | None:
    cover = (asset.get("cover") or "").strip()
    url = (asset.get("url") or "").strip()
    asset_type = asset.get("assetType")
    category_type = asset.get("type")

    if asset_type == "image" or category_type in ("character", "scene", "prop", "material"):
        return cover or url or None

    return cover or None


# 解析写入提示词的资产名称
def resolve_asset_prompt_name(asset: dict[str, Any], fallback: str) -> str:
    params = asset.get("params") if isinstance(asset.get("params"), dict) else {}
    entity = ""
    if isinstance(params, dict):
        entity = str(params.get("entityName") or params.get("name") or "").strip()
    return entity or (asset.get("name") or "").strip() or fallback


def resolve_character_prompt_name(asset: dict[str, Any]) -> str:
    return resolve_asset_prompt_name(asset, "角色")


def resolve_narration_prompt_name(asset: dict[str, Any]) -> str:
    return resolve_asset_prompt_name(asset, "旁白")


def resolve_scene_prompt_name(asset: dict[str, Any]) -> str:
    return resolve_asset_prompt_name(asset, "场景")


def resolve_other_asset_prompt_name(asset: dict[str, Any]) -> str:
    return resolve_asset_prompt_name(asset, f"资产#{asset.get('id')}")


def _prepare_voice_script(content: str | None) -> str:
    """提交前脚本：拆舞台指示、纠正空镜误标、角色 VO 改对白。"""
    normalized = rewrite_dialogue_action_lines(content or "")
    return rewrite_misclassified_visual_voice_lines(normalized)


def collect_speaking_character_names(
    script: str,
    reference: list[dict[str, Any]] | None,
) -> set[str]:
    """从对白/旁白/独白行收集本镜开口的角色名（含 @asset 引用）。"""
    names_by_id: dict[int, str] = {}
    aliases: list[str] = []
    for asset in reference or []:
        if asset.get("type") != "character":
            continue
        prompt_name = resolve_character_prompt_name(asset)
        names_by_id[int(asset["id"])] = prompt_name
        aliases.append(prompt_name)
        raw_name = str(asset.get("name") or "").strip()
        if raw_name:
            aliases.append(raw_name)
    aliases = sorted({name for name in aliases if name}, key=len, reverse=True)
    spoken: set[str] = set()
    for raw in (script or "").replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line or line.startswith("@duration:") or is_production_meta_line(line):
            continue
        if line.startswith("【画面") or line.startswith("【空镜"):
            continue
        body = VOICE_CUE_PREFIX_RE.sub("", line).strip()
        kind = classify_voice_body(body)
        if kind not in {"dialogue", "inner"}:
            continue
        for token in ASSET_MENTION_TOKEN_PATTERN.findall(body):
            mapped = names_by_id.get(int(token))
            if mapped:
                spoken.add(mapped)
        for name in aliases:
            if _name_is_token_prefix(body, name):
                spoken.add(name)
                break
    return spoken


def _should_attach_reference_audio(
    asset: dict[str, Any],
    *,
    filter_audio: bool,
    speaking: set[str],
    has_narration: bool,
) -> bool:
    """未开口角色不挂音色；无第三人称旁白则不挂旁白音色。"""
    if not filter_audio:
        return True
    kind = asset.get("type")
    if kind == "character":
        prompt_name = resolve_character_prompt_name(asset)
        raw_name = str(asset.get("name") or "").strip()
        return prompt_name in speaking or raw_name in speaking
    if kind == "narration":
        return has_narration
    return True


# 从引用资产构建参考图/音频目录
def build_seedance_reference_catalog(
    reference: list[dict[str, Any]] | None,
    script: str | None = None,
) -> SeedanceReferenceCatalog:
    catalog = SeedanceReferenceCatalog()
    seen_image_asset_ids: set[int] = set()
    seen_audio_asset_ids: set[int] = set()
    filter_audio = script is not None
    voice_script = _prepare_voice_script(script) if filter_audio else ""
    speaking = (
        collect_speaking_character_names(voice_script, reference) if filter_audio else set()
    )
    has_narration = script_has_narration_cue(voice_script) if filter_audio else True

    for asset in reference or []:
        asset_id = int(asset["id"])
        image_url = resolve_reference_image_url(asset)

        if image_url and asset_id not in seen_image_asset_ids:
            seen_image_asset_ids.add(asset_id)
            catalog.images.append(SeedanceReferenceFile(asset_id=asset_id, url=image_url))

        # 已绑定的试听暂不挂进 content[]，避免 reference_audio 抢模型口播
        if SEEDANCE_ATTACH_REFERENCE_AUDIO and asset.get("type") in {"character", "narration"}:
            if not _should_attach_reference_audio(
                asset,
                filter_audio=filter_audio,
                speaking=speaking,
                has_narration=has_narration,
            ):
                continue
            voice_audio_url = read_asset_voice_audio_url(asset.get("params"))
            if voice_audio_url and asset_id not in seen_audio_asset_ids:
                seen_audio_asset_ids.add(asset_id)
                catalog.audios.append(SeedanceReferenceFile(asset_id=asset_id, url=voice_audio_url))

    catalog.image_index_by_asset_id = {
        item.asset_id: index + 1 for index, item in enumerate(catalog.images)
    }
    catalog.audio_index_by_asset_id = {
        item.asset_id: index + 1 for index, item in enumerate(catalog.audios)
    }
    return catalog


_KIND_ZH = {
    "character": "角色",
    "scene": "场景",
    "prop": "道具",
    "narration": "旁白",
}


# 按 content[] 下标生成可读标签（与 build_seedance_content_items 顺序一致）
def describe_seedance_content_slots(
    reference: list[dict[str, Any]] | None,
    continuity_first_frame_url: str | None = None,
    *,
    has_text: bool = True,
    style_board_url: str | None = None,
    content: str | None = None,
) -> list[str]:
    catalog = build_seedance_reference_catalog(reference, script=content)
    asset_by_id = {
        int(asset["id"]): asset
        for asset in (reference or [])
        if isinstance(asset, dict) and asset.get("id") is not None
    }
    labels: list[str] = []
    if has_text:
        labels.append("分镜文案")
    for image in catalog.images:
        asset = asset_by_id.get(image.asset_id) or {}
        kind = str(asset.get("type") or "").lower()
        kind_zh = _KIND_ZH.get(kind, "参考图")
        name = str(asset.get("name") or "").strip() or f"资产#{image.asset_id}"
        labels.append(f"{kind_zh}「{name}」")
    board = (style_board_url or "").strip() if catalog.images else ""
    if board:
        labels.append("画风板")
    for audio in catalog.audios:
        asset = asset_by_id.get(audio.asset_id) or {}
        kind = str(asset.get("type") or "").lower()
        kind_zh = _KIND_ZH.get(kind, "音色")
        name = str(asset.get("name") or "").strip() or f"资产#{audio.asset_id}"
        labels.append(f"{kind_zh}音色「{name}」")
    if (continuity_first_frame_url or "").strip():
        labels.append("上一镜尾帧")
    return labels


# 正文中的 @asset 替换文案
def format_body_asset_mention(name: str, image_index: int | None) -> str:
    if image_index is not None:
        return f"{name}（参考图{image_index}）"
    return name


def _asset_prompt_name_for_mention(asset: dict[str, Any] | None) -> str:
    """按资产类型解析写入提示词的显示名。"""
    if not asset:
        return ""
    category = asset.get("type")
    if category == "character":
        return resolve_character_prompt_name(asset)
    if category == "scene":
        return resolve_scene_prompt_name(asset)
    return resolve_other_asset_prompt_name(asset)


_NAME_TOKEN_BOUNDARIES = frozenset(" \t，,、；;：:。．.!！?？）)]】」』\"'（([【「『“”和与跟及同在到向对把被让给的地得了着过也又再就都还从带")


def _name_is_token_suffix(text: str, name: str) -> bool:
    """text 是否以独立的 name 结尾（避免 大禹 吃掉 禹）。"""
    if not name or not text.endswith(name):
        return False
    prefix = text[: -len(name)]
    return (not prefix) or prefix[-1] in _NAME_TOKEN_BOUNDARIES


def _name_is_token_prefix(text: str, name: str) -> bool:
    """text 是否以独立的 name 开头（避免 禹王 被当成 禹）。"""
    if not name or not text.startswith(name):
        return False
    rest = text[len(name) :]
    return (not rest) or rest[0] in _NAME_TOKEN_BOUNDARIES


# 将单个 @asset 占位符替换为正文描述
def replace_asset_mention_token(
    asset_id: int,
    asset_by_id: dict[int, dict[str, Any]],
    catalog: SeedanceReferenceCatalog,
) -> str:
    asset = asset_by_id.get(asset_id)
    if not asset:
        return ""
    index_map = getattr(catalog, "image_index_by_asset_id", {}) or {}
    image_index = index_map.get(int(asset["id"]))
    return format_body_asset_mention(_asset_prompt_name_for_mention(asset), image_index)


def replace_asset_mentions_without_duplicate_names(
    text: str,
    asset_by_id: dict[int, dict[str, Any]],
    catalog: SeedanceReferenceCatalog,
) -> str:
    """把 @asset:id 换成「名称（参考图N）」，吞掉前后已经写过的同名。"""
    pieces: list[str] = []
    pos = 0
    for match in ASSET_MENTION_TOKEN_PATTERN.finditer(text):
        pieces.append(text[pos : match.start()])
        asset_id = int(match.group(1))
        token = replace_asset_mention_token(asset_id, asset_by_id, catalog)
        name = _asset_prompt_name_for_mention(asset_by_id.get(asset_id))
        index_map = getattr(catalog, "image_index_by_asset_id", {}) or {}
        image_index = index_map.get(asset_id)
        if name and _name_is_token_suffix("".join(pieces).rstrip(), name):
            token = f"（参考图{image_index}）" if image_index is not None else ""
        end = match.end()
        skip = 0
        if name:
            rest = text[end:]
            stripped = rest.lstrip()
            ws = len(rest) - len(stripped)
            if _name_is_token_prefix(stripped, name):
                skip = ws + len(name)
        pieces.append(token)
        pos = end + skip
    pieces.append(text[pos:])
    return "".join(pieces)


# 组装画面风格声明块；有画风板时强调只借气质、禁止抄主体
def build_visual_style_section(
    video_style_id: str | None,
    *,
    has_style_board: bool = False,
) -> str | None:
    style_prompt = resolve_image_style_prompt(video_style_id)
    if not style_prompt:
        return None
    extra = f"\n{STYLE_BOARD_PROMPT_HINT}" if has_style_board else ""
    return f"{SEEDANCE_VISUAL_STYLE_SECTION_INTRO}\n{style_prompt}{extra}"


def build_reference_index_section(
    reference: list[dict[str, Any]] | None,
    category_type: str,
    index_map: dict[int, int],
    header: str,
    index_label: str,
    resolve_name: Any,
) -> str | None:
    lines: list[str] = []
    seen_asset_ids: set[int] = set()

    for asset in reference or []:
        asset_id = int(asset["id"])
        if asset.get("type") != category_type or asset_id in seen_asset_ids:
            continue
        seen_asset_ids.add(asset_id)
        reference_index = index_map.get(asset_id)
        if reference_index is None:
            continue
        lines.append(f"{resolve_name(asset)}：{index_label}{reference_index}")

    if not lines:
        return None
    return "\n".join([header, *lines])


# 将分镜脚本转为正文提示词
def _normalize_body_whitespace(text: str) -> str:
    lines = [
        INLINE_WHITESPACE_PATTERN.sub(" ", raw).strip()
        for raw in text.replace("\r\n", "\n").split("\n")
    ]
    return "\n".join(line for line in lines if line).strip()


def build_seedance_body_text(
    content: str | None,
    reference: list[dict[str, Any]] | None,
    catalog: SeedanceReferenceCatalog,
) -> str:
    # 拆分对白内舞台指示，并纠正误标为对白/旁白的空镜画面行
    normalized = rewrite_dialogue_action_lines(content or "")
    normalized = rewrite_misclassified_visual_voice_lines(normalized)
    asset_by_id = {int(asset["id"]): asset for asset in (reference or [])}
    replaced = replace_duration_mentions_with_time_ranges(normalized)
    replaced = replace_asset_mentions_without_duplicate_names(replaced, asset_by_id, catalog)
    return _normalize_body_whitespace(replaced)


def build_seedance_prompt_text(
    content: str | None,
    reference: list[dict[str, Any]] | None,
    catalog: SeedanceReferenceCatalog | None = None,
    video_style_id: str | None = None,
    *,
    burn_subtitles: bool = True,
    character_intro: bool = True,
    has_style_board: bool = False,
) -> str:
    # 提交前拆分对白舞台指示并纠正空镜误标，保证强制约束与正文一致
    normalized = rewrite_dialogue_action_lines(content or "")
    normalized = rewrite_misclassified_visual_voice_lines(normalized)
    if not burn_subtitles:
        # 后期模式：去掉字幕 cue /「同步字幕」前缀，避免模型仍按字烧屏
        normalized = strip_model_burn_subtitle_cues(normalized)
    if not character_intro:
        normalized = strip_character_intro_cues(normalized)
    resolved_catalog = catalog or build_seedance_reference_catalog(reference, script=normalized)
    sections = [
        build_visual_style_section(video_style_id, has_style_board=has_style_board),
        build_seedance_production_section(
            normalized,
            burn_subtitles=burn_subtitles,
            character_intro=character_intro,
        ),
        *(
            [
                build_reference_index_section(
                    reference,
                    "character",
                    resolved_catalog.audio_index_by_asset_id,
                    SEEDANCE_CHARACTER_VOICE_SECTION_HEADER,
                    "参考音频",
                    resolve_character_prompt_name,
                ),
                build_reference_index_section(
                    reference,
                    "narration",
                    resolved_catalog.audio_index_by_asset_id,
                    SEEDANCE_NARRATION_VOICE_SECTION_HEADER,
                    "参考音频",
                    resolve_narration_prompt_name,
                ),
            ]
            if SEEDANCE_ATTACH_REFERENCE_AUDIO
            else []
        ),
        build_reference_index_section(
            reference,
            "character",
            resolved_catalog.image_index_by_asset_id,
            SEEDANCE_CHARACTER_APPEARANCE_SECTION_HEADER,
            "参考图",
            resolve_character_prompt_name,
        ),
        build_reference_index_section(
            reference,
            "scene",
            resolved_catalog.image_index_by_asset_id,
            SEEDANCE_SCENE_SECTION_HEADER,
            "参考图",
            resolve_scene_prompt_name,
        ),
        build_reference_index_section(
            reference,
            "prop",
            resolved_catalog.image_index_by_asset_id,
            SEEDANCE_PROP_SECTION_HEADER,
            "参考图",
            resolve_other_asset_prompt_name,
        ),
        build_seedance_body_text(normalized, reference, resolved_catalog),
    ]
    return "\n\n".join(section for section in sections if section)


# 从引用资产组装 Seedance content 多模态数组
def build_seedance_content_items(
    content: str | None,
    reference: list[dict[str, Any]] | None,
    video_style_id: str | None = None,
    continuity_first_frame_url: str | None = None,
    *,
    burn_subtitles: bool = True,
    character_intro: bool = True,
    style_board_url: str | None = None,
) -> list[dict[str, Any]]:
    catalog = build_seedance_reference_catalog(reference, script=content)
    # 无角色/场景图时不挂画风板，避免板子变成唯一画面参考
    board = (style_board_url or "").strip() if catalog.images else ""
    prompt_text = build_seedance_prompt_text(
        content,
        reference,
        catalog,
        video_style_id,
        burn_subtitles=burn_subtitles,
        character_intro=character_intro,
        has_style_board=bool(board),
    )
    items: list[dict[str, Any]] = []

    continuity = (continuity_first_frame_url or "").strip()
    has_reference_media = bool(catalog.images or catalog.audios)

    if continuity and prompt_text:
        # Seedance：first/last_frame 不能与 reference_* 混用；有角色/场景参考时改挂 reference_image
        if has_reference_media:
            prompt_text = (
                "【强制约束：镜头衔接】另附上一镜尾帧作为参考图（参考图序列最后一张）。"
                "本段开场须从该尾帧画面自然续接，保持主体、场景与光影连贯，禁止跳切到无关画面。\n\n"
                + prompt_text
            )
        else:
            prompt_text = (
                "【强制约束：镜头衔接】本段视频必须以首帧图为开场画面自然续接，"
                "保持主体、场景与光影连贯，禁止跳切到无关画面。\n\n"
                + prompt_text
            )

    if prompt_text:
        items.append({"type": "text", "text": prompt_text})

    for image in catalog.images:
        items.append(
            {"type": "image_url", "image_url": {"url": image.url}, "role": "reference_image"}
        )

    if board:
        items.append(
            {"type": "image_url", "image_url": {"url": board}, "role": "reference_image"}
        )

    for audio in catalog.audios:
        items.append(
            {"type": "audio_url", "audio_url": {"url": audio.url}, "role": "reference_audio"}
        )

    if continuity:
        if has_reference_media:
            items.append(
                {
                    "type": "image_url",
                    "image_url": {"url": continuity},
                    "role": "reference_image",
                }
            )
        else:
            # 无参考媒体时可用 first_frame，并在外层省略 ratio
            items.append(
                {
                    "type": "image_url",
                    "image_url": {"url": continuity},
                    "role": "first_frame",
                }
            )

    return items


def resolve_seedance_model_endpoint(model_id: str | None) -> str:
    settings = get_settings()
    raw = (model_id or "").strip()
    logical_id = resolve_logical_model_id("video", model_id)
    routed = resolve_upstream_model("video", logical_id or (raw if raw else None))
    if routed:
        return routed
    if not raw:
        return settings.model_video or (settings.model_video_2 or "").strip()
    lowered = raw.lower()
    if lowered in {"seedance-2", "seedance-1.5", "seedance-1"}:
        return (settings.model_video_2 or "").strip() or settings.model_video or raw
    if lowered == "seedance-2.5":
        return settings.model_video or (settings.model_video_2 or "").strip() or raw
    return raw


def resolve_seedance_ratio(aspect_ratio: str | None) -> str:
    # 与漫剧默认竖屏一致；缺失时不得回落到横屏 16:9
    return (aspect_ratio or "9:16").strip() or "9:16"


def resolve_seedance_resolution(
    resolution: str | None,
    *,
    model_id: str | None = None,
) -> str:
    """解析并按模型能力钳制清晰度。"""
    from app.services.seedance_resolutions import clamp_video_resolution

    return clamp_video_resolution(model_id, resolution)


# 将分镜参数转为 Seedance 请求体
def build_seedance_generate_body(input_params: BuildSeedanceGenerateBodyInput) -> dict[str, Any]:
    from app.services.seedance_resolutions import clamp_video_duration

    content = input_params.get("content")
    fallback = int(input_params.get("duration_fallback") or 8)
    continuity = (input_params.get("continuity_first_frame_url") or "").strip() or None
    reference = input_params.get("reference")
    catalog = build_seedance_reference_catalog(reference, script=content)
    # 仅「纯首帧、无参考媒体」时省略 ratio；混用参考时必须保留 ratio、且尾帧用 reference_image
    style_board_url = (input_params.get("style_board_url") or "").strip() or None
    if not catalog.images:
        style_board_url = None
    use_first_frame_mode = bool(continuity) and not (catalog.images or catalog.audios)
    burn_subtitles = input_params.get("burn_subtitles")
    if burn_subtitles is None:
        burn_subtitles = True
    character_intro = input_params.get("character_intro")
    if character_intro is None:
        character_intro = True

    mid = input_params.get("model_id")
    raw_duration = resolve_seedance_duration_from_content(content, fallback=fallback)
    body: dict[str, Any] = {
        "model": resolve_seedance_model_endpoint(mid),
        "content": build_seedance_content_items(
            content,
            reference,
            input_params.get("video_style_id"),
            continuity_first_frame_url=continuity,
            burn_subtitles=bool(burn_subtitles),
            character_intro=bool(character_intro),
            style_board_url=style_board_url,
        ),
        "duration": clamp_video_duration(mid, raw_duration),
        "resolution": resolve_seedance_resolution(
            input_params.get("resolution"),
            model_id=mid,
        ),
        "watermark": False,
        # Seedance 原生配音；字幕/人物介绍叠字由对应开关控制提示词
        "generate_audio": True,
        "return_last_frame": True,
    }
    if not use_first_frame_mode:
        body["ratio"] = resolve_seedance_ratio(input_params.get("aspect_ratio"))
    return body
