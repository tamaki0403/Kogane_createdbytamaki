#!/usr/bin/env python3
"""Render Kogane OTP tournament boards from JSON data."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
DEFAULT_SAMPLE = ROOT / "samples" / "sample_tournament.json"
DEFAULT_CONFIG = ROOT / "configs" / "qualifier_4team.json"
DEFAULT_OUTPUT = ROOT / "output" / "qualifier_A.png"

STATUS_LABELS = {
    "done": "終了",
    "played": "終了",
    "playing": "進行中",
    "waiting": "待機",
    "ready": "開始待ち",
    "active": "対戦中",
    "hold": "保留",
    "bye": "不戦勝",
    "no_match": "試合なし",
}

STATUS_ALIASES = {
    "played": "done",
    "playing": "active",
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def find_font(config: dict[str, Any]) -> str | None:
    for candidate in config.get("fonts", {}).get("preferred", []):
        if Path(candidate).exists():
            return candidate
    for pattern in (
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-*.ttc",
        "/usr/share/fonts/truetype/noto/*CJK*.ttc",
        "/usr/share/fonts/truetype/noto/*CJK*.otf",
        "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
        "/System/Library/Fonts/*角*W6.ttc",
        "/System/Library/Fonts/*角*W5.ttc",
        "/System/Library/Fonts/*角*W4.ttc",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
    ):
        matches = sorted(Path("/").glob(pattern.lstrip("/")))
        if matches:
            return str(matches[0])
    return None


def font(font_path: str | None, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if font_path:
        return ImageFont.truetype(font_path, size=size)
    return ImageFont.load_default()


def text_size(draw: ImageDraw.ImageDraw, text: str, face: ImageFont.ImageFont) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=face)
    return box[2] - box[0], box[3] - box[1]


def fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_path: str | None,
    max_size: int,
    max_width: int,
    max_height: int,
    min_size: int = 18,
) -> ImageFont.ImageFont:
    for size in range(max_size, min_size - 1, -2):
        face = font(font_path, size)
        width, height = text_size(draw, text, face)
        if width <= max_width and height <= max_height:
            return face
    return font(font_path, min_size)


def draw_fit_text(
    draw: ImageDraw.ImageDraw,
    xywh: list[int],
    text: str,
    font_path: str | None,
    max_size: int,
    fill: str,
    anchor: str = "mm",
    align: str = "center",
    min_size: int = 18,
) -> None:
    x, y, w, h = xywh
    face = fit_font(draw, text, font_path, max_size, w, h, min_size)
    if anchor == "lm":
        draw.text((x, y + h / 2), text, font=face, fill=fill, anchor="lm", align=align)
    else:
        draw.text((x + w / 2, y + h / 2), text, font=face, fill=fill, anchor=anchor, align=align)


def rounded_box(draw: ImageDraw.ImageDraw, xywh: list[int], fill: str, outline: str, width: int = 4) -> None:
    x, y, w, h = xywh
    draw.rounded_rectangle((x, y, x + w, y + h), radius=18, fill=fill, outline=outline, width=width)


def draw_color_stripes(draw: ImageDraw.ImageDraw, x: int, y: int, width: int, height: int, colors: dict[str, str]) -> None:
    stripe_w = width // 3
    skew = max(height, 8)
    parts = [
        (x, x + stripe_w, colors["cyan"]),
        (x + stripe_w, x + stripe_w * 2, colors["accent"]),
        (x + stripe_w * 2, x + width, colors["lime"]),
    ]
    for left, right, fill in parts:
        draw.polygon(
            [(left + skew, y), (right + skew, y), (right, y + height), (left, y + height)],
            fill=fill,
        )


def draw_splatter(draw: ImageDraw.ImageDraw, size: tuple[int, int], colors: dict[str, str]) -> None:
    rng = random.Random(20261006)
    width, height = size
    palette = [colors["cyan"], colors["accent"], colors["lime"]]
    clusters = [
        (10, 10, 260, 180, 58),
        (width - 340, 0, width - 18, 190, 58),
        (0, 210, 110, height - 170, 72),
        (width - 108, 180, width, height - 120, 64),
        (0, height - 160, 360, height, 58),
        (width - 420, height - 145, width, height, 54),
    ]
    for zx1, zy1, zx2, zy2, count in clusters:
        for _ in range(count):
            x = rng.randint(zx1, zx2)
            y = rng.randint(zy1, zy2)
            radius = rng.randint(3, 24)
            fill = rng.choice(palette)
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)
            if rng.random() < 0.32:
                tail_x = x + rng.randint(-42, 42)
                tail_y = y + rng.randint(-42, 42)
                draw.line((x, y, tail_x, tail_y), fill=fill, width=rng.randint(2, 7))

    for _ in range(220):
        edge = rng.choice(("top", "left", "right", "bottom"))
        if edge == "top":
            x, y = rng.randint(0, width), rng.randint(0, 84)
        elif edge == "bottom":
            x, y = rng.randint(0, width), rng.randint(height - 84, height)
        elif edge == "left":
            x, y = rng.randint(0, 88), rng.randint(0, height)
        else:
            x, y = rng.randint(width - 88, width), rng.randint(0, height)
        radius = rng.randint(1, 6)
        fill = rng.choice(palette + ["#ffffff"])
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)


def paper_polygon(width: int, height: int, margin: int, cut: int) -> list[tuple[int, int]]:
    return [
        (margin + cut, margin),
        (width - margin, margin),
        (width - margin, height - margin - cut),
        (width - margin - cut, height - margin),
        (margin + cut, height - margin),
        (margin, height - margin - cut),
        (margin, margin + cut),
    ]


def placeholder_background(size: tuple[int, int], colors: dict[str, str]) -> Image.Image:
    image = Image.new("RGB", size, "#050608")
    draw = ImageDraw.Draw(image)
    width, height = size
    draw_splatter(draw, size, colors)
    margin = 76
    cut = 34
    paper = paper_polygon(width, height, margin, cut)
    draw.line(paper + [paper[0]], fill=colors["cyan"], width=18, joint="curve")
    shifted = [(x + 10, y + 10) for x, y in paper]
    draw.line(shifted + [shifted[0]], fill=colors["accent"], width=14, joint="curve")
    shifted = [(x + 18, y + 18) for x, y in paper]
    draw.line(shifted + [shifted[0]], fill=colors["lime"], width=12, joint="curve")
    draw.polygon(paper, fill=colors["panel"])
    draw.line(paper + [paper[0]], fill=colors["line"], width=8, joint="curve")

    inner = paper_polygon(width, height, margin + 22, cut - 4)
    draw.line(inner + [inner[0]], fill=colors["line"], width=3, joint="curve")
    draw_color_stripes(draw, margin + 38, margin + 96, width - margin * 2 - 76, 10, colors)
    draw_color_stripes(draw, margin + 38, height - margin - 48, width - margin * 2 - 76, 10, colors)
    return image


def load_canvas(config: dict[str, Any]) -> Image.Image:
    canvas = config["canvas"]
    size = (canvas["width"], canvas["height"])
    template = resolve_path(canvas["template"])
    if template.exists():
        return Image.open(template).convert("RGB").resize(size)
    return placeholder_background(size, config["colors"] | {"background": canvas["background"]})


def canvas_with_size(config: dict[str, Any], width: int, height: int) -> Image.Image:
    canvas = config["canvas"]
    template = resolve_path(canvas["template"])
    if template.exists():
        return Image.open(template).convert("RGB").resize((width, height))
    return placeholder_background((width, height), config["colors"] | {"background": canvas["background"]})


def team_lookup(block: dict[str, Any]) -> dict[str, dict[str, str]]:
    lookup = {}
    for team in block["teams"]:
        for key in ("team_key", "id", "application_id"):
            if key in team:
                lookup[team[key]] = team
    return lookup


def team_id(team: dict[str, Any]) -> str:
    return team.get("application_id") or team.get("id") or team.get("team_key", "")


def team_stats(team: dict[str, Any]) -> str:
    parts = []
    if "match_wins" in team:
        losses = team.get("match_losses", 0)
        parts.append(f"{team['match_wins']}勝{losses}敗")
    if "battle_wins" in team:
        parts.append(f"本数 {team['battle_wins']}-{team.get('battle_losses', 0)}")
    return " / ".join(parts)


def sorted_teams(teams: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        teams,
        key=lambda team: (
            team.get("rank", 999),
            team_id(team),
        ),
    )


def status_color(status: str, colors: dict[str, str]) -> str:
    return colors.get(STATUS_ALIASES.get(status, status), colors["waiting"])


def render_team_rows(
    draw: ImageDraw.ImageDraw,
    block: dict[str, Any],
    config: dict[str, Any],
    font_path: str | None,
) -> None:
    colors = config["colors"]
    spec = config["team_rows"]
    draw_fit_text(draw, spec["header_box"], spec["title"], font_path, 30, colors["muted"], min_size=18)
    hx, hy, hw, hh = spec["header_box"]
    draw_color_stripes(draw, hx + hw - 176, hy + hh - 10, 150, 8, colors)

    for row, team in zip(spec["rows"], sorted_teams(block["teams"])):
        rounded_box(draw, row, colors["panel"], colors["line"])
        x, y, w, h = row
        rank = f"{team.get('rank', '-') }位"
        rank_box = [x + 20, y + 20, 82, h - 40]
        id_box = [x + 110, y + 22, spec["id_width"], h - 44]
        name_box = [x + 110 + spec["id_width"] + 22, y + 16, w - spec["id_width"] - 158, 48]
        stat_box = [x + 110 + spec["id_width"] + 22, y + 66, w - spec["id_width"] - 158, 24]
        draw_fit_text(draw, rank_box, rank, font_path, spec["id_font_size"], colors["accent"], min_size=18)
        draw_fit_text(draw, id_box, team_id(team), font_path, spec["id_font_size"], colors["muted"], min_size=17)
        draw_fit_text(draw, name_box, team["name"], font_path, spec["name_font_size"], colors["ink"], anchor="lm", min_size=22)
        if team_stats(team):
            draw_fit_text(draw, stat_box, team_stats(team), font_path, spec["stat_font_size"], colors["muted"], anchor="lm", min_size=14)


def render_match_rows(
    draw: ImageDraw.ImageDraw,
    block: dict[str, Any],
    config: dict[str, Any],
    font_path: str | None,
) -> None:
    colors = config["colors"]
    spec = config["matches"]
    teams = team_lookup(block)
    draw_fit_text(draw, spec["header_box"], spec["title"], font_path, 30, colors["muted"], min_size=18)
    hx, hy, hw, hh = spec["header_box"]
    draw_color_stripes(draw, hx + hw - 176, hy + hh - 10, 150, 8, colors)

    for index, (row, match) in enumerate(zip(spec["rows"], block["matches"]), start=1):
        rounded_box(draw, row, colors["panel_alt"], colors["line"])
        x, y, w, h = row
        team_a = teams[match["teams"][0]]
        team_b = teams[match["teams"][1]]
        score = match.get("score")
        status = match.get("status")
        match_no = match.get("match_no", f"第{index}試合")
        winner = match.get("winner")
        team_a_color = colors["accent"] if winner == match["teams"][0] else colors["ink"]
        team_b_color = colors["accent"] if winner == match["teams"][1] else colors["ink"]

        draw_fit_text(draw, [x + 22, y + 8, 78, 24], match_no, font_path, spec["label_font_size"], colors["muted"], min_size=14)
        draw_fit_text(draw, [x + 34, y + 34, 230, 36], team_a["name"], font_path, spec["team_font_size"], team_a_color, anchor="lm", min_size=18)
        draw_fit_text(draw, [x + 522, y + 34, 186, 36], team_b["name"], font_path, spec["team_font_size"], team_b_color, anchor="lm", min_size=18)
        if score is None:
            draw_fit_text(draw, [x + 298, y + 26, 216, 48], "未入力", font_path, 30, colors["muted"], min_size=18)
        else:
            draw_fit_text(draw, [x + 302, y + 22, 88, 50], str(score[0]), font_path, spec["score_font_size"], team_a_color, min_size=24)
            draw_fit_text(draw, [x + 424, y + 22, 88, 50], str(score[1]), font_path, spec["score_font_size"], team_b_color, min_size=24)
            draw_fit_text(draw, [x + 394, y + 24, 30, 46], "-", font_path, 34, colors["muted"], min_size=20)

        if status:
            label = STATUS_LABELS.get(status, status)
            pill = [x + w - 130, y + 12, 92, 28]
            px, py, pw, ph = pill
            draw.rounded_rectangle((px, py, px + pw, py + ph), radius=17, fill=status_color(status, colors))
            draw_fit_text(draw, pill, label, font_path, spec["status_font_size"], "#ffffff", min_size=17)


def render_board(data: dict[str, Any], config: dict[str, Any], output: Path) -> None:
    image = load_canvas(config)
    draw = ImageDraw.Draw(image)
    font_path = find_font(config)
    colors = config["colors"]
    block = data["block"]

    draw_fit_text(draw, config["title"]["box"], f"Kogane OTP杯 {block['name']}", font_path, config["title"]["font_size"], colors["ink"], min_size=28)
    render_team_rows(draw, block, config, font_path)
    render_match_rows(draw, block, config, font_path)
    draw_fit_text(draw, config["footer"]["box"], f"tournament_id: {data['tournament_id']} / generated locally", font_path, config["footer"]["font_size"], colors["muted"], min_size=16)

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


def blocks_from_data(data: dict[str, Any]) -> list[dict[str, Any]]:
    if "qualifiers" in data:
        return data.get("qualifiers", {}).get("blocks", [])
    if "blocks" in data:
        return data["blocks"]
    if "block" in data:
        return [data["block"]]
    return []


def render_section_label(
    draw: ImageDraw.ImageDraw,
    xywh: list[int],
    label: str,
    config: dict[str, Any],
    font_path: str | None,
) -> None:
    colors = config["colors"]
    x, y, w, h = xywh
    draw.rectangle((x, y, x + min(w, 190), y + h), fill=colors["line"])
    draw_fit_text(draw, [x + 14, y, min(w, 170), h], label, font_path, 26, "#ffffff", anchor="lm", min_size=16)
    draw_color_stripes(draw, x + min(w, 202), y + 6, 86, h - 12, colors)


def choose_overview_columns(block_count: int, max_columns: int = 4) -> int:
    if block_count <= 4:
        return 1
    if block_count <= 10:
        return 2
    if block_count <= 15:
        return 3
    return min(max_columns, 4)


def overview_layout(config: dict[str, Any], block_count: int) -> dict[str, int]:
    overview = config["overview"]
    canvas = config["canvas"]
    cols = overview.get("columns", "auto")
    if cols == "auto":
        cols = choose_overview_columns(block_count, overview.get("max_columns", 4))
    rows = max(1, (block_count + cols - 1) // cols)
    width = canvas["width"]
    height = canvas["height"]
    margin_x = overview.get("margin_x", 116)
    start_y = overview.get("start_y", 204)
    footer_space = overview.get("footer_space", 150)
    gap_x = overview.get("gap_x", 32)
    gap_y = overview.get("gap_y", 12)
    col_w = (width - margin_x * 2 - gap_x * (cols - 1)) // cols
    block_h = (height - start_y - footer_space - gap_y * (rows - 1)) // rows
    if block_count <= 4:
        block_h = max(190, min(300, block_h))
        configured_team_gap = overview.get("team_gap_y_small", 34)
    else:
        block_h = max(112, min(150, block_h))
        configured_team_gap = max(17, min(22, (block_h - overview.get("team_start_y", 42) - 10) // 4))
    return {
        "cols": cols,
        "rows": rows,
        "width": width,
        "height": height,
        "start_x": margin_x,
        "start_y": start_y,
        "col_w": col_w,
        "block_h": block_h,
        "gap_x": gap_x,
        "gap_y": gap_y,
        "team_start_y": overview.get("team_start_y", 42),
        "team_gap_y": configured_team_gap,
        "block_label_height": overview.get("block_label_height", 28),
    }


def render_overview(data: dict[str, Any], config: dict[str, Any], output: Path) -> None:
    blocks = blocks_from_data(data)
    layout = overview_layout(config, len(blocks))
    image = canvas_with_size(config, layout["width"], layout["height"])
    draw = ImageDraw.Draw(image)
    font_path = find_font(config)
    colors = config["colors"]
    overview = config["overview"]

    title = overview.get("title", "Kogane OTP杯 出場チーム一覧")
    draw_fit_text(draw, config["title"]["box"], title, font_path, config["title"]["font_size"], colors["ink"], min_size=28)

    cols = layout["cols"]
    start_x = layout["start_x"]
    start_y = layout["start_y"]
    col_w = layout["col_w"]
    block_h = layout["block_h"]
    gap_x = layout["gap_x"]
    gap_y = layout["gap_y"]
    team_start_y = layout["team_start_y"]
    team_gap_y = layout["team_gap_y"]
    block_label_height = layout["block_label_height"]

    for index, block in enumerate(blocks):
        col = index % cols
        row = index // cols
        x = start_x + col * (col_w + gap_x)
        y = start_y + row * (block_h + gap_y)
        rounded_box(draw, [x, y, col_w, block_h], colors["panel"], colors["line"], width=3)
        render_section_label(draw, [x + 16, y + 10, col_w - 32, block_label_height], block.get("name", block.get("block_id", "")), config, font_path)

        for team_index, team in enumerate(sorted_teams(block.get("teams", []))[:4]):
            ty = y + team_start_y + team_index * team_gap_y
            rank = f"{team.get('rank', team_index + 1)}位"
            draw_fit_text(draw, [x + 18, ty, 52, 19], rank, font_path, 17, colors["accent"], min_size=12)
            draw_fit_text(draw, [x + 76, ty, 82, 19], team_id(team), font_path, 15, colors["muted"], min_size=10)
            draw_fit_text(draw, [x + 166, ty, col_w - 184, 19], team["name"], font_path, 18, colors["ink"], anchor="lm", min_size=11)

    updated = data.get("updated_at", "")
    footer = f"tournament_id: {data.get('tournament_id', '-')} / updated: {updated or '-'}"
    footer_box = config["footer"].get("box")
    if footer_box == "auto":
        footer_box = [100, layout["height"] - 150, layout["width"] - 200, 36]
    draw_fit_text(draw, footer_box, footer, font_path, config["footer"]["font_size"], colors["muted"], min_size=14)

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


def bracket_from_data(data: dict[str, Any]) -> dict[str, Any]:
    if "bracket" in data:
        return data["bracket"]
    if "brackets" in data:
        bracket_id = data.get("bracket_id") or data.get("target_bracket") or "upper"
        return data["brackets"][bracket_id]
    return data


def bracket_team_text(team_key: str | None, teams: dict[str, Any]) -> tuple[str, str]:
    if not team_key:
        return "未定", ""
    team = teams.get(team_key, {})
    name = team.get("name", team_key)
    meta_parts = []
    if team.get("application_id"):
        meta_parts.append(team["application_id"])
    if team.get("qualifier_block") and team.get("qualifier_rank"):
        meta_parts.append(f"{team['qualifier_block']}ブロック{team['qualifier_rank']}位")
    return name, " / ".join(meta_parts)


def score_text(score: list[Any] | None) -> str:
    if not score or score[0] is None or score[1] is None:
        return "-"
    return f"{score[0]}-{score[1]}"


def render_bracket_team_slot(
    draw: ImageDraw.ImageDraw,
    box: list[int],
    team_key: str | None,
    teams: dict[str, Any],
    winner: str | None,
    score: Any,
    note: str | None,
    config: dict[str, Any],
    font_path: str | None,
) -> None:
    colors = config["colors"]
    x, y, w, h = box
    is_winner = team_key is not None and team_key == winner
    fill = "#fff7fc" if is_winner else colors["panel"]
    outline = colors["accent"] if is_winner else colors["line"]
    compact = h < 40
    draw.rounded_rectangle((x, y, x + w, y + h), radius=7 if compact else 10, fill=fill, outline=outline, width=3 if is_winner else 2)

    name, meta = bracket_team_text(team_key, teams)
    text_color = colors["accent"] if is_winner else colors["ink"]
    if compact:
        compact_name = name if not meta else f"{name} / {meta.split(' / ')[0]}"
        draw_fit_text(draw, [x + 8, y + 2, w - 58, h - 4], compact_name, font_path, 15, text_color, anchor="lm", min_size=8)
        if note:
            draw_fit_text(draw, [x + w - 100, y + 2, 46, h - 4], note, font_path, 9, colors["accent"], min_size=7)
        draw_fit_text(draw, [x + w - 42, y + 2, 30, h - 4], "" if score is None else str(score), font_path, 15, text_color, min_size=8)
    else:
        draw_fit_text(draw, [x + 12, y + 6, w - 64, 30], name, font_path, 24, text_color, anchor="lm", min_size=12)
        if meta:
            draw_fit_text(draw, [x + 12, y + 36, w - 82, 20], meta, font_path, 14, colors["muted"], anchor="lm", min_size=9)
        if note:
            draw_fit_text(draw, [x + w - 72, y + 36, 58, 20], note, font_path, 13, colors["accent"], min_size=9)
        draw_fit_text(draw, [x + w - 52, y + 12, 40, 34], "" if score is None else str(score), font_path, 24, text_color, min_size=12)


def render_bracket_match(
    draw: ImageDraw.ImageDraw,
    box: list[int],
    match: dict[str, Any],
    teams: dict[str, Any],
    config: dict[str, Any],
    font_path: str | None,
) -> None:
    colors = config["colors"]
    x, y, w, h = box
    rounded_box(draw, box, colors["panel_alt"], colors["line"], width=3)
    label = match.get("label") or f"{match.get('round_label', '')} #{match.get('match_no', '')}"
    compact = h < 120
    label_h = 18 if compact else 22
    label_size = 12 if compact else 16
    draw_fit_text(draw, [x + 10, y + 4, w - 108, label_h], label, font_path, label_size, colors["muted"], anchor="lm", min_size=8)
    status = match.get("status")
    if status:
        status_label = STATUS_LABELS.get(status, status)
        pill = [x + w - 90, y + 4, 72, label_h]
        px, py, pw, ph = pill
        draw.rounded_rectangle((px, py, px + pw, py + ph), radius=11, fill=status_color(status, colors))
        draw_fit_text(draw, pill, status_label, font_path, 10 if compact else 13, "#ffffff", min_size=8)

    team_keys = match.get("teams", [None, None])
    scores = match.get("score") or [None, None]
    notes = match.get("advance_reasons") or [None, None]
    if compact:
        slot_h = 25
        render_bracket_team_slot(draw, [x + 10, y + 24, w - 20, slot_h], team_keys[0], teams, match.get("winner"), scores[0], "不戦勝" if notes[0] == "bye" else None, config, font_path)
        render_bracket_team_slot(draw, [x + 10, y + 52, w - 20, slot_h], team_keys[1], teams, match.get("winner"), scores[1], "不戦勝" if notes[1] == "bye" else None, config, font_path)
    else:
        render_bracket_team_slot(draw, [x + 12, y + 34, w - 24, 58], team_keys[0], teams, match.get("winner"), scores[0], "不戦勝" if notes[0] == "bye" else None, config, font_path)
        render_bracket_team_slot(draw, [x + 12, y + 98, w - 24, 58], team_keys[1], teams, match.get("winner"), scores[1], "不戦勝" if notes[1] == "bye" else None, config, font_path)


def bracket_round_positions(
    by_round: dict[int, list[dict[str, Any]]],
    round_numbers: list[int],
    spec: dict[str, Any],
) -> dict[str, list[int]]:
    positions = {}
    start_x, start_y = spec["start"]
    col_w = spec["column_width"]
    col_gap = spec["column_gap"]
    match_h = spec["match_height"]
    max_col_h = spec["max_column_height"]

    for col_index, round_no in enumerate(round_numbers):
        round_matches = sorted(by_round.get(round_no, []), key=lambda item: item.get("match_no", 0))
        x = start_x + col_index * (col_w + col_gap)
        if not round_matches:
            continue
        gap = max(18, (max_col_h - match_h * len(round_matches)) // max(1, len(round_matches) - 1))
        total_h = match_h * len(round_matches) + gap * (len(round_matches) - 1)
        y0 = start_y + max(0, (max_col_h - total_h) // 2)
        for match_index, match in enumerate(round_matches):
            y = y0 + match_index * (match_h + gap)
            positions[match["match_id"]] = [x, y, col_w, match_h]
    return positions


def draw_bracket_connector(
    draw: ImageDraw.ImageDraw,
    source_box: list[int],
    target_box: list[int],
    target_slot: int | None,
    colors: dict[str, str],
) -> None:
    sx, sy, sw, sh = source_box
    tx, ty, tw, th = target_box
    start = (sx + sw, sy + sh // 2)
    slot_y = ty + (64 if target_slot == 0 else 128)
    end = (tx, slot_y)
    mid_x = start[0] + max(20, (end[0] - start[0]) // 2)
    draw.line((start[0], start[1], mid_x, start[1]), fill=colors["line"], width=3)
    draw.line((mid_x, start[1], mid_x, end[1]), fill=colors["line"], width=3)
    draw.line((mid_x, end[1], end[0], end[1]), fill=colors["line"], width=3)


def rounds_use_slots(rounds: list[dict[str, Any]]) -> bool:
    return any("slots" in round_data for round_data in rounds)


def grouped_round_slots(round_data: dict[str, Any]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    order = []
    for slot in round_data.get("slots", []):
        match_id = slot.get("match_id") or slot.get("slot_id", "")
        if match_id not in groups:
            groups[match_id] = []
            order.append(match_id)
        groups[match_id].append(slot)

    matches = []
    for index, match_id in enumerate(order, start=1):
        slots = sorted(groups[match_id], key=lambda slot: slot.get("slot_index", 0))
        while len(slots) < 2:
            slots.append({
                "slot_id": f"{match_id}-empty-{len(slots)}",
                "match_id": match_id,
                "slot_index": len(slots),
                "team_key": None,
                "score": None,
                "status": "waiting",
                "is_winner": False,
                "note": "未定",
            })
        status = next((slot.get("status") for slot in slots if slot.get("status")), "waiting")
        matches.append({
            "match_id": match_id,
            "round": round_data["round"],
            "round_label": round_data.get("label", ""),
            "match_no": index,
            "label": f"{round_data.get('label', '')} 第{index}試合",
            "slots": slots[:2],
            "status": status,
        })
    return matches


def render_bracket_slot_match(
    draw: ImageDraw.ImageDraw,
    box: list[int],
    match: dict[str, Any],
    teams: dict[str, Any],
    config: dict[str, Any],
    font_path: str | None,
) -> None:
    colors = config["colors"]
    x, y, w, h = box
    compact = h < 120
    rounded_box(draw, box, colors["panel_alt"], colors["line"], width=3)
    label_h = 18 if compact else 22
    draw_fit_text(draw, [x + 10, y + 4, w - 108, label_h], match["label"], font_path, 12 if compact else 16, colors["muted"], anchor="lm", min_size=8)
    status_label = STATUS_LABELS.get(match.get("status", "waiting"), match.get("status", "waiting"))
    pill = [x + w - 90, y + 4, 72, label_h]
    px, py, pw, ph = pill
    draw.rounded_rectangle((px, py, px + pw, py + ph), radius=11, fill=status_color(match.get("status", "waiting"), colors))
    draw_fit_text(draw, pill, status_label, font_path, 10 if compact else 13, "#ffffff", min_size=8)

    slots = match["slots"]
    slot_h = 25 if compact else 58
    slot_gap = 3 if compact else 6
    slot_y = y + (24 if compact else 34)
    for index, slot in enumerate(slots):
        note = slot.get("note")
        team_key = slot.get("team_key")
        if not team_key and note:
            temp_teams = teams | {"__note__": {"name": note}}
            render_key = "__note__"
            note_text = None
        else:
            temp_teams = teams
            render_key = team_key
            note_text = note
        render_bracket_team_slot(
            draw,
            [x + 10, slot_y + index * (slot_h + slot_gap), w - 20, slot_h],
            render_key,
            temp_teams,
            render_key if slot.get("is_winner") and render_key else None,
            slot.get("score"),
            note_text,
            config,
            font_path,
        )


def slot_round_positions(
    round_matches: dict[int, list[dict[str, Any]]],
    round_numbers: list[int],
    spec: dict[str, Any],
) -> dict[str, list[int]]:
    positions = {}
    start_x, start_y = spec["start"]
    col_w = spec["column_width"]
    col_gap = spec["column_gap"]
    match_h = spec["match_height"]
    max_col_h = spec["max_column_height"]

    for col_index, round_no in enumerate(round_numbers):
        matches = round_matches.get(round_no, [])
        x = start_x + col_index * (col_w + col_gap)
        if not matches:
            continue
        gap = max(10, (max_col_h - match_h * len(matches)) // max(1, len(matches) - 1))
        total_h = match_h * len(matches) + gap * (len(matches) - 1)
        y0 = start_y + max(0, (max_col_h - total_h) // 2)
        for match_index, match in enumerate(matches):
            positions[match["match_id"]] = [x, y0 + match_index * (match_h + gap), col_w, match_h]
    return positions


def draw_slot_connectors(
    draw: ImageDraw.ImageDraw,
    positions: dict[str, list[int]],
    round_matches: dict[int, list[dict[str, Any]]],
    round_numbers: list[int],
    colors: dict[str, str],
) -> None:
    for round_index, round_no in enumerate(round_numbers[:-1]):
        current = round_matches.get(round_no, [])
        next_round = round_matches.get(round_numbers[round_index + 1], [])
        for index, match in enumerate(current):
            target_index = index // 2
            if target_index >= len(next_round):
                continue
            source_box = positions.get(match["match_id"])
            target_box = positions.get(next_round[target_index]["match_id"])
            if source_box and target_box:
                draw_bracket_connector(draw, source_box, target_box, index % 2, colors)


def render_bracket_slots(data: dict[str, Any], config: dict[str, Any], output: Path) -> None:
    bracket = bracket_from_data(data)
    image = load_canvas(config)
    draw = ImageDraw.Draw(image)
    font_path = find_font(config)
    colors = config["colors"]
    spec = config["bracket"]
    rounds = bracket.get("rounds", [])
    teams = bracket.get("teams", {})
    title = bracket.get("title", spec.get("title", "トーナメント"))

    draw_fit_text(draw, config["title"]["box"], f"Kogane OTP杯 {title}", font_path, config["title"]["font_size"], colors["ink"], min_size=28)

    round_numbers = [round_data["round"] for round_data in rounds]
    round_matches = {round_data["round"]: grouped_round_slots(round_data) for round_data in rounds}
    positions = slot_round_positions(round_matches, round_numbers, spec)
    start_x, start_y = spec["start"]
    col_w = spec["column_width"]
    col_gap = spec["column_gap"]

    for col_index, round_data in enumerate(rounds):
        x = start_x + col_index * (col_w + col_gap)
        render_section_label(draw, [x, start_y - 48, col_w, 30], round_data.get("label", f"R{round_data['round']}"), config, font_path)

    draw_slot_connectors(draw, positions, round_matches, round_numbers, colors)

    for round_no in round_numbers:
        for match in round_matches.get(round_no, []):
            render_bracket_slot_match(draw, positions[match["match_id"]], match, teams, config, font_path)

    updated = data.get("updated_at") or bracket.get("updated_at", "")
    footer_id = data.get("tournament_id") or bracket.get("bracket_id", "-")
    footer = f"tournament_id: {footer_id} / updated: {updated or '-'}"
    footer_box = list(config["footer"]["box"])
    footer_box[1] += height - config["canvas"]["height"]
    draw_fit_text(draw, footer_box, footer, font_path, config["footer"]["font_size"], colors["muted"], min_size=14)

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


def render_bracket(data: dict[str, Any], config: dict[str, Any], output: Path) -> None:
    bracket = bracket_from_data(data)
    if config.get("render_type") == "bracket_tree":
        render_bracket_tree(data, config, output)
        return
    if config.get("render_type") == "bracket_visual":
        render_bracket_visual(data, config, output)
        return
    if rounds_use_slots(bracket.get("rounds", [])):
        render_bracket_slots(data, config, output)
        return
    image = load_canvas(config)
    draw = ImageDraw.Draw(image)
    font_path = find_font(config)
    colors = config["colors"]
    spec = config["bracket"]
    title = bracket.get("title", spec.get("title", "トーナメント"))

    draw_fit_text(draw, config["title"]["box"], f"Kogane OTP杯 {title}", font_path, config["title"]["font_size"], colors["ink"], min_size=28)

    rounds = bracket.get("rounds", [])
    matches = bracket.get("matches", [])
    teams = bracket.get("teams", {})
    round_labels = {item["round"]: item.get("label", str(item["round"])) for item in rounds}
    by_round: dict[int, list[dict[str, Any]]] = {}
    for match in matches:
        by_round.setdefault(match["round"], []).append(match)

    round_numbers = [item["round"] for item in rounds] or sorted(by_round)
    start_x, start_y = spec["start"]
    col_w = spec["column_width"]
    col_gap = spec["column_gap"]
    match_h = spec["match_height"]
    positions = bracket_round_positions(by_round, round_numbers, spec)

    for col_index, round_no in enumerate(round_numbers):
        round_matches = sorted(by_round.get(round_no, []), key=lambda item: item.get("match_no", 0))
        x = start_x + col_index * (col_w + col_gap)
        label = round_labels.get(round_no, f"R{round_no}")
        render_section_label(draw, [x, start_y - 48, col_w, 30], label, config, font_path)

    for match in matches:
        next_match_id = match.get("next_match_id")
        if next_match_id and match.get("match_id") in positions and next_match_id in positions:
            draw_bracket_connector(draw, positions[match["match_id"]], positions[next_match_id], match.get("next_slot"), colors)

    for round_no in round_numbers:
        for match in sorted(by_round.get(round_no, []), key=lambda item: item.get("match_no", 0)):
            if match["match_id"] in positions:
                render_bracket_match(draw, positions[match["match_id"]], match, teams, config, font_path)

    updated = data.get("updated_at", "")
    footer = f"tournament_id: {data.get('tournament_id', '-')} / updated: {updated}"
    draw_fit_text(draw, config["footer"]["box"], footer, font_path, config["footer"]["font_size"], colors["muted"], min_size=14)

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


def visual_team_slot(
    draw: ImageDraw.ImageDraw,
    box: list[int],
    entry: dict[str, Any],
    teams: dict[str, Any],
    config: dict[str, Any],
    font_path: str | None,
) -> None:
    colors = config["colors"]
    x, y, w, h = box
    team_key = entry.get("team_key")
    is_winner = entry.get("is_winner", False)
    note = entry.get("note")
    score = entry.get("score")
    fill = "#fff7fc" if is_winner else colors["panel"]
    outline = colors["accent"] if is_winner else colors["line"]
    draw.rectangle((x, y, x + w, y + h), fill=fill, outline=outline, width=3 if is_winner else 2)
    if team_key:
        name, meta = bracket_team_text(team_key, teams)
        display = name if not meta else f"{name} / {meta.split(' / ')[0]}"
    else:
        display = note or "未定"
    draw_fit_text(draw, [x + 8, y + 2, w - 64, h - 4], display, font_path, 14, colors["accent"] if is_winner else colors["ink"], anchor="lm", min_size=8)
    if note and team_key:
        draw_fit_text(draw, [x + w - 104, y + 2, 52, h - 4], note, font_path, 9, colors["accent"], min_size=7)
    draw_fit_text(draw, [x + w - 42, y + 2, 30, h - 4], "" if score is None else str(score), font_path, 15, colors["accent"] if is_winner else colors["ink"], min_size=8)


def render_visual_node(
    draw: ImageDraw.ImageDraw,
    box: list[int],
    node: dict[str, Any],
    teams: dict[str, Any],
    config: dict[str, Any],
    font_path: str | None,
) -> None:
    colors = config["colors"]
    x, y, w, h = box
    label = node.get("label") or node.get("node_id", "")
    status = node.get("status", "waiting")
    draw_fit_text(draw, [x + 2, y - 18, w - 88, 16], label, font_path, 11, colors["muted"], anchor="lm", min_size=8)
    pill = [x + w - 74, y - 18, 70, 16]
    px, py, pw, ph = pill
    draw.rounded_rectangle((px, py, px + pw, py + ph), radius=9, fill=status_color(status, colors))
    draw_fit_text(draw, pill, STATUS_LABELS.get(status, status), font_path, 9, "#ffffff", min_size=7)
    entries = node.get("teams", [])
    while len(entries) < 2:
        entries.append({"team_key": None, "note": "未定"})
    visual_team_slot(draw, [x, y, w, 28], entries[0], teams, config, font_path)
    visual_team_slot(draw, [x, y + 32, w, 28], entries[1], teams, config, font_path)


def draw_visual_connector(draw: ImageDraw.ImageDraw, source: list[int], target: list[int], target_slot: int, colors: dict[str, str]) -> None:
    sx, sy, sw, sh = source
    tx, ty, tw, th = target
    start = (sx + sw, sy + sh // 2)
    end_y = ty + (14 if target_slot == 0 else 46)
    end = (tx, end_y)
    mid_x = start[0] + max(28, (end[0] - start[0]) // 2)
    draw.line((start[0], start[1], mid_x, start[1]), fill=colors["line"], width=3)
    draw.line((mid_x, start[1], mid_x, end[1]), fill=colors["line"], width=3)
    draw.line((mid_x, end[1], end[0], end[1]), fill=colors["line"], width=3)


def round_sort_key(round_data: dict[str, Any]) -> int:
    if "round_index" in round_data:
        return int(round_data["round_index"])
    if "round" in round_data:
        return int(round_data["round"]) - 1
    labels = {"r1": 0, "r2": 1, "qf": 2, "sf": 3, "final": 4, "winner": 5}
    return labels.get(str(round_data.get("key", "")).lower(), 999)


def bracket_round_index(round_data: dict[str, Any], fallback: int) -> int:
    value = round_data.get("round_index")
    if value is not None:
        return int(value)
    if "round" in round_data:
        return int(round_data["round"]) - 1
    return fallback


def slot_bracket_index(slot: dict[str, Any], fallback: int) -> int:
    value = slot.get("bracket_index")
    if value is not None:
        return int(value)
    value = slot.get("display_index")
    if value is not None:
        return int(value)
    return fallback


def bracket_slot_display(slot: dict[str, Any], teams: dict[str, Any]) -> tuple[str, str, str]:
    team_key = slot.get("team_key")
    if team_key:
        team = teams.get(team_key, {})
        name = slot.get("team_name") or team.get("name") or team_key
        application = slot.get("application_id") or team.get("application_id")
        if not application and slot.get("entry_no") is not None:
            application = f"#{slot['entry_no']}"
        block = slot.get("block") or team.get("qualifier_block")
        seed_rank = slot.get("seed_rank") or slot.get("qualifier_rank") or team.get("qualifier_rank")
        meta_parts = [part for part in (application, f"{block}{seed_rank}位" if block and seed_rank else None) if part]
        return name, " / ".join(meta_parts), slot.get("note") or ""
    return slot.get("note") or "未定", "", ""


def normalize_tree_slot(slot: dict[str, Any], teams: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(slot)
    if normalized.get("status") in STATUS_ALIASES:
        normalized["status"] = STATUS_ALIASES[normalized["status"]]
    if normalized.get("team_key") and not normalized.get("team_name"):
        team = teams.get(normalized["team_key"], {})
        normalized["team_name"] = team.get("name")
    if normalized.get("entry_no") is None:
        application = normalized.get("application_id")
        if application and str(application).startswith("OTP-"):
            normalized["entry_no"] = str(application).removeprefix("OTP-")
    if normalized.get("block") is None:
        team = teams.get(normalized.get("team_key"), {})
        normalized["block"] = team.get("qualifier_block")
    if normalized.get("rank") is None:
        team = teams.get(normalized.get("team_key"), {})
        normalized["rank"] = team.get("qualifier_rank")
    return normalized


def slot_status(slots: list[dict[str, Any]]) -> str:
    priority = ("active", "ready", "done", "bye", "waiting", "no_match")
    statuses = {STATUS_ALIASES.get(slot.get("status"), slot.get("status")) for slot in slots if slot.get("status")}
    for status in priority:
        if status in statuses:
            return status
    return "waiting"


def normalize_match_rounds(bracket: dict[str, Any]) -> list[dict[str, Any]]:
    rounds = sorted(bracket.get("rounds", []), key=round_sort_key)
    if any(round_data.get("matches") for round_data in rounds):
        normalized_rounds = []
        for fallback_index, round_data in enumerate(rounds):
            round_key = round_data.get("key") or f"r{round_data.get('round', fallback_index + 1)}"
            matches = []
            for match_index, match in enumerate(round_data.get("matches", [])):
                match_key = match.get("match_key") or match.get("match_id") or f"{round_key}_m{match_index + 1}"
                slots = [normalize_tree_slot(slot, bracket.get("teams", {})) for slot in match.get("slots", [])[:2]]
                while len(slots) < 2:
                    slots.append({"team_key": None, "score": None, "status": "waiting", "note": "未定"})
                matches.append({
                    **match,
                    "match_key": match_key,
                    "match_index": match.get("match_index", match_index),
                    "label": match.get("label") or f"{round_data.get('label', round_key)} #{match_index + 1}",
                    "bo": match.get("bo") or round_data.get("bo") or round_data.get("best_of") or (5 if "final" in str(round_key).lower() else 3),
                    "status": match.get("status") or slot_status(slots),
                    "slots": slots,
                })
            normalized_rounds.append({
                **round_data,
                "key": round_key,
                "round_index": bracket_round_index(round_data, fallback_index),
                "matches": matches,
            })
        return normalized_rounds

    if any(round_data.get("slots") for round_data in rounds):
        normalized_rounds = []
        for fallback_index, round_data in enumerate(rounds):
            round_key = round_data.get("key") or f"r{round_data.get('round', fallback_index + 1)}"
            slots = round_data.get("slots", [])
            matches = []
            for match_index in range((len(slots) + 1) // 2):
                pair = [normalize_tree_slot(slot, bracket.get("teams", {})) for slot in slots[match_index * 2:match_index * 2 + 2]]
                while len(pair) < 2:
                    pair.append({"team_key": None, "score": None, "status": "waiting", "note": "未定"})
                match_key = pair[0].get("match_id") or pair[1].get("match_id") or f"{round_key}_m{match_index + 1}"
                matches.append({
                    "match_key": match_key,
                    "match_index": match_index,
                    "label": f"{round_data.get('label', round_key)} #{match_index + 1}",
                    "bo": round_data.get("bo") or round_data.get("best_of") or (5 if match_index == 0 and fallback_index == len(rounds) - 1 else 3),
                    "status": slot_status(pair),
                    "slots": pair,
                })
            normalized_rounds.append({
                **round_data,
                "key": round_key,
                "round_index": bracket_round_index(round_data, fallback_index),
                "matches": matches,
            })
        return normalized_rounds

    by_round: dict[int, list[dict[str, Any]]] = {}
    for match in bracket.get("matches", []):
        by_round.setdefault(int(match.get("round", 1)), []).append(match)
    normalized_rounds = []
    for fallback_index, round_data in enumerate(rounds):
        round_no = int(round_data.get("round", fallback_index + 1))
        round_key = round_data.get("key") or f"r{round_no}"
        matches = []
        for match_index, match in enumerate(sorted(by_round.get(round_no, []), key=lambda item: item.get("match_no", 0))):
            scores = match.get("score") or [None, None]
            advance_reasons = match.get("advance_reasons") or [None, None]
            team_keys = match.get("teams") or [None, None]
            slots = []
            for slot_index in range(2):
                team_key = team_keys[slot_index] if slot_index < len(team_keys) else None
                slots.append(normalize_tree_slot({
                    "team_key": team_key,
                    "score": scores[slot_index] if slot_index < len(scores) else None,
                    "status": match.get("status", "waiting"),
                    "is_winner": bool(team_key and team_key == match.get("winner")),
                    "note": "不戦勝" if slot_index < len(advance_reasons) and advance_reasons[slot_index] == "bye" else None,
                }, bracket.get("teams", {})))
            matches.append({
                "match_key": match.get("match_id") or f"{round_key}_m{match_index + 1}",
                "match_index": match_index,
                "label": match.get("label") or f"{round_data.get('label', round_key)} #{match_index + 1}",
                "bo": match.get("best_of") or round_data.get("best_of") or 3,
                "status": match.get("status", "waiting"),
                "slots": slots,
                "winner_to": {
                    "match_key": match.get("next_match_id"),
                    "slot_index": match.get("next_slot"),
                } if match.get("next_match_id") else None,
            })
        normalized_rounds.append({
            **round_data,
            "key": round_key,
            "round_index": fallback_index,
            "matches": matches,
        })
    return normalized_rounds


def draw_tree_slot(
    draw: ImageDraw.ImageDraw,
    box: list[int],
    slot: dict[str, Any],
    teams: dict[str, Any],
    config: dict[str, Any],
    font_path: str | None,
) -> None:
    colors = config["colors"]
    x, y, w, h = box
    is_winner = bool(slot.get("is_winner"))
    status = slot.get("status", "waiting")
    fill = "#fff8fc" if is_winner else colors["panel"]
    outline = colors["accent"] if is_winner else colors["line"]
    draw.rectangle((x, y, x + w, y + h), fill=fill, outline=outline, width=3 if is_winner else 2)
    draw.rectangle((x, y, x + 8, y + h), fill=status_color(status, colors))

    name, meta, note = bracket_slot_display(slot, teams)
    score = slot.get("score")
    name_color = colors["accent"] if is_winner else colors["ink"]
    meta_text = meta
    if note and slot.get("team_key"):
        meta_text = f"{meta} / {note}" if meta else note
    draw_fit_text(draw, [x + 14, y + 3, w - 64, 20], name, font_path, 17, name_color, anchor="lm", min_size=8)
    if h >= 40 and meta_text:
        draw_fit_text(draw, [x + 14, y + 24, w - 70, 15], meta_text, font_path, 10, colors["muted"], anchor="lm", min_size=7)
    draw_fit_text(draw, [x + w - 48, y + 3, 36, h - 6], "" if score is None else str(score), font_path, 18, name_color, min_size=8)


def draw_tree_match_card(
    draw: ImageDraw.ImageDraw,
    box: list[int],
    match: dict[str, Any],
    teams: dict[str, Any],
    config: dict[str, Any],
    font_path: str | None,
) -> None:
    colors = config["colors"]
    spec = config["bracket_tree"]
    x, y, w, h = box
    is_final = bool(match.get("is_final")) or int(match.get("bo", 3)) == 5
    outline = colors["lime"] if is_final else colors["line"]
    fill = colors["final_panel"] if is_final and "final_panel" in colors else colors["panel_alt"]
    radius = spec.get("card_radius", 8)
    draw.rounded_rectangle((x, y, x + w, y + h), radius=radius, fill=fill, outline=outline, width=4 if is_final else 3)
    compact = h < 104
    header_h = 22 if compact else 28
    draw.rectangle((x, y, x + w, y + header_h), fill=colors["header"])
    label = match.get("label") or match.get("match_key", "")
    draw_fit_text(draw, [x + 12, y + 3, w - 120, header_h - 6], label, font_path, spec.get("label_font_size", 16) if not compact else 12, colors["muted"], anchor="lm", min_size=8)
    bo = f"BO{match.get('bo', 5 if is_final else 3)}"
    status = STATUS_LABELS.get(match.get("status", "waiting"), match.get("status", "waiting"))
    draw_fit_text(draw, [x + w - 100, y + 3, 38, header_h - 6], bo, font_path, spec.get("bo_font_size", 14) if not compact else 11, colors["lime"] if is_final else colors["cyan"], min_size=8)
    pill = [x + w - 58, y + 4, 46, max(14, header_h - 8)]
    draw.rounded_rectangle((pill[0], pill[1], pill[0] + pill[2], pill[1] + pill[3]), radius=9, fill=status_color(match.get("status", "waiting"), colors))
    draw_fit_text(draw, pill, status, font_path, 9, "#ffffff", min_size=7)

    slot_gap = 4 if compact else spec.get("slot_gap", 8)
    slot_y = y + (header_h + 5 if compact else spec.get("card_header_height", 34))
    slot_h = max(21, min(spec.get("slot_height", 44), (y + h - slot_y - slot_gap - 6) // 2))
    for index, slot in enumerate(match.get("slots", [])[:2]):
        draw_tree_slot(draw, [x + 10, slot_y + index * (slot_h + slot_gap), w - 20, slot_h], slot, teams, config, font_path)


def tree_target_slot_y(target_box: list[int], slot_index: int | None, config: dict[str, Any]) -> int:
    spec = config["bracket_tree"]
    compact = target_box[3] < 104
    header_h = 22 if compact else 28
    slot_gap = 4 if compact else spec.get("slot_gap", 8)
    slot_y = target_box[1] + (header_h + 5 if compact else spec.get("card_header_height", 34))
    slot_h = max(21, min(spec.get("slot_height", 44), (target_box[1] + target_box[3] - slot_y - slot_gap - 6) // 2))
    index = 0 if slot_index in (None, 0) else 1
    return slot_y + index * (slot_h + slot_gap) + slot_h // 2


def tree_source_slot_y(source_box: list[int], match: dict[str, Any], config: dict[str, Any]) -> int:
    spec = config["bracket_tree"]
    slots = match.get("slots", [])
    winner_index = next((index for index, slot in enumerate(slots[:2]) if slot.get("is_winner")), None)
    if winner_index is None:
        return source_box[1] + source_box[3] // 2
    compact = source_box[3] < 104
    header_h = 22 if compact else 28
    slot_gap = 4 if compact else spec.get("slot_gap", 8)
    slot_y = source_box[1] + (header_h + 5 if compact else spec.get("card_header_height", 34))
    slot_h = max(21, min(spec.get("slot_height", 44), (source_box[1] + source_box[3] - slot_y - slot_gap - 6) // 2))
    return slot_y + winner_index * (slot_h + slot_gap) + slot_h // 2


def draw_tree_match_connector(
    draw: ImageDraw.ImageDraw,
    source_box: list[int],
    target_box: list[int],
    source_match: dict[str, Any],
    target_slot: int | None,
    config: dict[str, Any],
) -> None:
    colors = config["colors"]
    spec = config["bracket_tree"]
    line_w = spec.get("line_width", 4)
    sx, sy, sw, sh = source_box
    tx, _, _, _ = target_box
    start_x = sx + sw
    start_y = tree_source_slot_y(source_box, source_match, config)
    end_x = tx
    end_y = tree_target_slot_y(target_box, target_slot, config)
    mid_x = start_x + max(spec.get("connector_stub", 40), (end_x - start_x) // 2)
    draw.line((start_x, start_y, mid_x, start_y), fill=colors["line"], width=line_w)
    draw.line((mid_x, start_y, mid_x, end_y), fill=colors["line"], width=line_w)
    draw.line((mid_x, end_y, end_x, end_y), fill=colors["line"], width=line_w)


def draw_tree_connectors(
    draw: ImageDraw.ImageDraw,
    positions: dict[str, list[int]],
    matches: dict[str, dict[str, Any]],
    ordered_rounds: list[dict[str, Any]],
    config: dict[str, Any],
) -> None:
    for round_index, round_data in enumerate(ordered_rounds[:-1]):
        next_round = ordered_rounds[round_index + 1]
        next_matches = next_round.get("matches", [])
        current_matches = round_data.get("matches", [])
        if len(current_matches) == len(next_matches) * 2:
            for target_index, target_match in enumerate(next_matches):
                top_index = target_index * 2
                bottom_index = top_index + 1
                if bottom_index >= len(current_matches):
                    continue
                top_key = current_matches[top_index]["match_key"]
                bottom_key = current_matches[bottom_index]["match_key"]
                target_key = target_match["match_key"]
                if top_key not in positions or bottom_key not in positions or target_key not in positions:
                    continue
                top = positions[top_key]
                bottom = positions[bottom_key]
                target = positions[target_key]
                source_x = top[0] + top[2]
                join_x = source_x + max(config["bracket_tree"].get("connector_stub", 40), (target[0] - source_x) // 2)
                top_y = top[1] + top[3] // 2
                bottom_y = bottom[1] + bottom[3] // 2
                target_y = target[1] + target[3] // 2
                line_w = config["bracket_tree"].get("line_width", 4)
                colors = config["colors"]
                draw.line((source_x, top_y, join_x, top_y), fill=colors["line"], width=line_w)
                draw.line((source_x, bottom_y, join_x, bottom_y), fill=colors["line"], width=line_w)
                draw.line((join_x, top_y, join_x, bottom_y), fill=colors["line"], width=line_w)
                draw.line((join_x, target_y, target[0], target_y), fill=colors["line"], width=line_w)
            continue

        for match_index, match in enumerate(round_data.get("matches", [])):
            winner_to = match.get("winner_to") or {}
            target_key = winner_to.get("match_key")
            target_slot = winner_to.get("slot_index")
            if not target_key:
                continue
            source_key = match["match_key"]
            if source_key in positions and target_key in positions and target_key in matches:
                draw_tree_match_connector(draw, positions[source_key], positions[target_key], match, target_slot, config)


def render_bracket_tree(data: dict[str, Any], config: dict[str, Any], output: Path) -> None:
    bracket = bracket_from_data(data)
    width = bracket.get("image", {}).get("width") or config["canvas"]["width"]
    height = bracket.get("image", {}).get("height") or config["canvas"]["height"]
    image = canvas_with_size(config, width, height)
    draw = ImageDraw.Draw(image)
    font_path = find_font(config)
    colors = config["colors"]
    spec = config["bracket_tree"]
    teams = bracket.get("teams", {})
    title = bracket.get("title", spec.get("title", "トーナメント"))
    subtitle = bracket.get("subtitle") or spec.get("subtitle", "")

    draw_fit_text(draw, config["title"]["box"], title, font_path, config["title"]["font_size"], colors["ink"], min_size=30)
    if subtitle:
        draw_fit_text(draw, spec["subtitle_box"], subtitle, font_path, spec.get("subtitle_font_size", 22), colors["muted"], min_size=14)

    rounds = normalize_match_rounds(bracket)
    start_x, start_y = spec["start"]
    col_w = spec.get("card_width", spec.get("slot_width", 300))
    col_gap = spec["column_gap"]
    card_h = spec.get("card_height", 132)
    final_card_h = spec.get("final_card_height", card_h + 20)
    max_y = height - spec.get("bottom_margin", 150)
    available_h = max_y - start_y
    positions: dict[str, list[int]] = {}
    match_map: dict[str, dict[str, Any]] = {}
    round_heights: dict[int, int] = {}

    for fallback_index, round_data in enumerate(rounds):
        round_index = int(round_data.get("round_index", fallback_index))
        x = start_x + round_index * (col_w + col_gap)
        label = round_data.get("label", f"R{round_index + 1}")
        render_section_label(draw, [x, start_y - 64, col_w, 30], label, config, font_path)
        matches = round_data.get("matches", [])
        if not matches:
            continue
        is_final_round = str(round_data.get("key", "")).lower() == "final" or str(label).lower() == "final" or round_data.get("bo") == 5
        ideal_h = final_card_h if is_final_round else card_h
        min_gap = spec.get("min_match_gap", 18)
        current_h = ideal_h
        if len(matches) > 1 and current_h * len(matches) + min_gap * (len(matches) - 1) > available_h:
            current_h = max(spec.get("min_card_height", 68), (available_h - min_gap * (len(matches) - 1)) // len(matches))
        round_heights[round_index] = current_h

    for fallback_index, round_data in enumerate(rounds):
        round_index = int(round_data.get("round_index", fallback_index))
        x = start_x + round_index * (col_w + col_gap)
        matches = round_data.get("matches", [])
        if not matches:
            continue
        current_h = round_heights[round_index]
        prev_round = rounds[fallback_index - 1] if fallback_index > 0 else None
        prev_matches = prev_round.get("matches", []) if prev_round else []

        if prev_round and len(prev_matches) == len(matches) * 2:
            for match_index, match in enumerate(matches):
                top_key = prev_matches[match_index * 2]["match_key"]
                bottom_key = prev_matches[match_index * 2 + 1]["match_key"]
                if top_key in positions and bottom_key in positions:
                    top = positions[top_key]
                    bottom = positions[bottom_key]
                    center_y = (top[1] + top[3] // 2 + bottom[1] + bottom[3] // 2) // 2
                    y = int(center_y - current_h / 2)
                else:
                    y = start_y
                positions[match["match_key"]] = [x, y, col_w, current_h]
                match_map[match["match_key"]] = match
            continue

        min_gap = spec.get("min_match_gap", 18)
        gap = max(min_gap, (available_h - current_h * len(matches)) // max(1, len(matches) - 1))
        if len(matches) == 1:
            y0 = start_y + max(0, (available_h - current_h) // 2)
        else:
            total_h = current_h * len(matches) + gap * (len(matches) - 1)
            y0 = start_y + max(0, (available_h - total_h) // 2)
        for match_index, match in enumerate(matches):
            y = y0 + match_index * (current_h + gap)
            positions[match["match_key"]] = [x, y, col_w, current_h]
            match_map[match["match_key"]] = match

    draw_tree_connectors(draw, positions, match_map, rounds, config)

    for round_data in rounds:
        for match in round_data.get("matches", []):
            draw_tree_match_card(draw, positions[match["match_key"]], match, teams, config, font_path)

    winner = bracket.get("winner")
    if winner:
        winner_slot = winner if isinstance(winner, dict) else {"team_key": winner, "status": "done", "is_winner": True, "note": "優勝"}
        last_round = max(int(round_data.get("round_index", index)) for index, round_data in enumerate(rounds)) if rounds else 4
        x = start_x + (last_round + 1) * (col_w + col_gap)
        y_center = start_y + available_h // 2
        draw_fit_text(draw, [x, start_y - 64, col_w, 30], "Winner", font_path, 24, colors["muted"], min_size=14)
        box = [x, int(y_center - spec.get("slot_height", 44) / 2), col_w, spec.get("slot_height", 44)]
        draw_tree_slot(draw, box, winner_slot, teams, config, font_path)
        final_matches = rounds[-1].get("matches", []) if rounds else []
        if final_matches and final_matches[0]["match_key"] in positions:
            final = positions[final_matches[0]["match_key"]]
            draw.line((final[0] + final[2], final[1] + final[3] // 2, box[0], box[1] + box[3] // 2), fill=colors["line"], width=spec.get("line_width", 4))

    updated = data.get("updated_at") or bracket.get("updated_at", "")
    footer_id = data.get("tournament_id") or bracket.get("bracket_id", "-")
    footer = f"tournament_id: {footer_id} / updated: {updated or '-'}"
    footer_box = list(config["footer"]["box"])
    footer_box[1] += height - config["canvas"]["height"]
    draw_fit_text(draw, footer_box, footer, font_path, config["footer"]["font_size"], colors["muted"], min_size=14)

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


def render_bracket_visual(data: dict[str, Any], config: dict[str, Any], output: Path) -> None:
    bracket = bracket_from_data(data)
    image = load_canvas(config)
    draw = ImageDraw.Draw(image)
    font_path = find_font(config)
    colors = config["colors"]
    spec = config["bracket_visual"]
    teams = bracket.get("teams", {})
    title = bracket.get("title", "トーナメント")
    draw_fit_text(draw, config["title"]["box"], f"Kogane OTP杯 {title}", font_path, config["title"]["font_size"], colors["ink"], min_size=28)

    rounds = bracket.get("rounds", [])
    round_numbers = [round_data["round"] for round_data in rounds]
    round_nodes = {round_data["round"]: round_data.get("nodes", []) for round_data in rounds}
    node_map = {node["node_id"]: node for nodes in round_nodes.values() for node in nodes}
    positions = {}
    start_x, start_y = spec["start"]
    col_w = spec["column_width"]
    col_gap = spec["column_gap"]
    node_h = spec["node_height"]
    max_h = spec["max_column_height"]

    for col_index, round_data in enumerate(rounds):
        nodes = round_data.get("nodes", [])
        x = start_x + col_index * (col_w + col_gap)
        render_section_label(draw, [x, start_y - 48, col_w, 30], round_data.get("label", f"R{round_data['round']}"), config, font_path)
        if not nodes:
            continue
        gap = max(18, (max_h - node_h * len(nodes)) // max(1, len(nodes) - 1))
        total_h = node_h * len(nodes) + gap * (len(nodes) - 1)
        y0 = start_y + max(0, (max_h - total_h) // 2)
        for index, node in enumerate(nodes):
            positions[node["node_id"]] = [x, y0 + index * (node_h + gap), col_w, node_h]

    for node in node_map.values():
        next_id = node.get("next_node_id")
        if next_id in positions and node["node_id"] in positions:
            draw_visual_connector(draw, positions[node["node_id"]], positions[next_id], node.get("next_slot", 0), colors)

    for round_no in round_numbers:
        for node in round_nodes.get(round_no, []):
            render_visual_node(draw, positions[node["node_id"]], node, teams, config, font_path)

    updated = data.get("updated_at") or bracket.get("updated_at", "")
    footer_id = data.get("tournament_id") or bracket.get("bracket_id", "-")
    footer = f"tournament_id: {footer_id} / updated: {updated or '-'}"
    draw_fit_text(draw, config["footer"]["box"], footer, font_path, config["footer"]["font_size"], colors["muted"], min_size=14)

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render Kogane OTP tournament board PNGs.")
    parser.add_argument("--input", type=Path, default=DEFAULT_SAMPLE, help="Tournament JSON path.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Renderer config JSON path.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output PNG path.")
    args = parser.parse_args()

    data = load_json(args.input)
    config = load_json(args.config)
    render_type = config.get("render_type", "qualifier_block")
    if render_type == "qualifier_overview":
        render_overview(data, config, args.output)
    elif render_type in ("bracket", "bracket_visual", "bracket_tree"):
        render_bracket(data, config, args.output)
    else:
        render_board(data, config, args.output)
    print(f"Rendered {args.output}")


if __name__ == "__main__":
    main()
