import os
import json
import random
import math
import copy
import time
import asyncio
import csv
import io
import re
import zipfile
import discord
from discord.ext import commands, tasks
from itertools import combinations
from PIL import Image, ImageDraw, ImageFont

# =========================
# ファイルパス / 環境変数
# =========================
DATA_DIR = "/data"
os.makedirs(DATA_DIR, exist_ok=True)

MATCH_HISTORY_FILE = os.path.join(DATA_DIR, "match_history.json")

def load_match_history():
    try:
        with open(MATCH_HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_match_history(data):
    with open(MATCH_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

RATINGS_FILE = os.path.join(DATA_DIR, "ratings.json")
PLAYER_PROFILES_FILE = os.path.join(DATA_DIR, "player_profiles.json")
TOKEN = os.getenv("DISCORD_TOKEN")

# =========================
# Bot状態
# =========================
BOT_STATE_FILE = os.path.join(DATA_DIR, "bot_state.json")

def load_bot_state():
    try:
        with open(BOT_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_bot_state(data):
    tmp_file = f"{BOT_STATE_FILE}.tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_file, BOT_STATE_FILE)

bot_state = load_bot_state()

# =========================
# 管理者設定
# =========================
OWNER_ID = 1225788050894753865
BASE_CHANGE_GAIN = 1.20
RECRUIT_NOTIFICATION_ROLE_ID = 1549685991969923183
RECRUIT_COOLDOWN_SECONDS = 10 * 60

# =========================
# チャンネル設定
# =========================
RANKING_CHANNEL_ID = 1492896273358127235

# ホームチャンネル
HOME_CHANNEL_ID = 1493300698568462388

# 募集チャンネル
RECRUIT_CHANNEL_ID = 1492899909093949480

# レート更新ログチャンネル
RATE_LOG_CHANNEL_ID = 1499607836911730778
ADMIN_CHANNEL_ID = 1492883720082952302
ADMIN_BUTTON_CHANNEL_ID = 1519220264347373568
PEAK_RATING_CHANNEL_ID = 1500892639338434580

# OTP杯
OTP_CATEGORY_ID = 1549775177921863710
OTP_ADMIN_CHANNEL_ID = 1549775297321242624
OTP_TEAM_SUMMARY_CHANNEL_ID = 1549775429991137420
OTP_TEAM_APPROVAL_CHANNEL_ID = 1550008154904072234
OTP_STAFF_MENTION = "<@1225788050894753865>"
OTP_FORM_WEBHOOK_SECRET = os.getenv("OTP_FORM_WEBHOOK_SECRET", "")

# ロビーVC（既存・削除しない）
ROOM_LOBBY_VC = {
    "A": 1492082738679910515,
    "B": 1494170471841660948,
}
DRAFT_LOBBY_VC_ID = 1500399929569574942
DYNAMIC_CATEGORY_ID = 1503603086370013224

# ★ 進行ch・alpha/bravo VCは動的作成するためIDをここでは持たない
# bot_state["dynamic_channels"] に保存する
# {
#   "room_A": {"progress": id, "alpha_vc": id, "bravo_vc": id},
#   "room_B": {"progress": id, "alpha_vc": id, "bravo_vc": id},
#   "draft_main": id,
#   "draft_A": {"progress": id, "alpha_vc": id, "bravo_vc": id},
#   "draft_B": {"progress": id, "alpha_vc": id, "bravo_vc": id},
# }

def get_dynamic_channels():
    return bot_state.get("dynamic_channels", {})

def save_dynamic_channels(data):
    bot_state["dynamic_channels"] = data
    save_bot_state(bot_state)


def get_otp_teams():
    return bot_state.setdefault("otp_teams", {})


def save_otp_teams():
    save_bot_state(bot_state)


def get_recruit_notification_role(guild: discord.Guild):
    """募集通知を受け取るためのオプトイン・ロールを返す。"""
    return guild.get_role(RECRUIT_NOTIFICATION_ROLE_ID)


def get_recruit_cooldowns():
    return bot_state.setdefault("recruit_cooldowns", {})


def get_recruit_cooldown_remaining(guild_id: int, user_id: int) -> int:
    last_created_at = get_recruit_cooldowns().get(f"{guild_id}:{user_id}", 0)
    return max(0, math.ceil(RECRUIT_COOLDOWN_SECONDS - (time.time() - last_created_at)))


def record_recruit_creation(guild_id: int, user_id: int):
    get_recruit_cooldowns()[f"{guild_id}:{user_id}"] = time.time()
    save_bot_state(bot_state)


def role_can_be_managed(guild: discord.Guild, role: discord.Role | None) -> bool:
    me = guild.me
    return bool(role and me and not role.managed and role < me.top_role)

# =========================
# 動的チャンネル作成・削除ヘルパー
# =========================
async def create_room_channels(guild, room_key: str, participant_ids: list = None):
    """進行ch + レート更新ch + alpha/bravo VCを作成してbot_stateに保存（プライベート化）"""
    dc = get_dynamic_channels()
    category = guild.get_channel(DYNAMIC_CATEGORY_ID)

    # パーミッション設定
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False, connect=False),
        guild.me: discord.PermissionOverwrite(view_channel=True, connect=True, send_messages=True),
    }

    # たまき（OWNER）
    owner = guild.get_member(OWNER_ID)
    if owner:
        overwrites[owner] = discord.PermissionOverwrite(view_channel=True, connect=True, send_messages=True)

    # 参加者
    if participant_ids:
        for uid in participant_ids:
            member = guild.get_member(int(uid))
            if member:
                overwrites[member] = discord.PermissionOverwrite(view_channel=True, connect=True, send_messages=True)

    progress_ch = await guild.create_text_channel(
        name=f"進行-部屋{room_key}",
        category=category,
        topic=f"{room_key}部屋の試合進行チャンネル",
        overwrites=overwrites
    )
    alpha_vc = await guild.create_voice_channel(
        name=f"アルファ-部屋{room_key}",
        category=category,
        overwrites=overwrites
    )
    bravo_vc = await guild.create_voice_channel(
        name=f"ブラボー-部屋{room_key}",
        category=category,
        overwrites=overwrites
    )

    dc[f"room_{room_key}"] = {
        "progress": progress_ch.id,
        "alpha_vc": alpha_vc.id,
        "bravo_vc": bravo_vc.id,
    }
    save_dynamic_channels(dc)
    return progress_ch, None, alpha_vc, bravo_vc


async def delete_room_channels(guild, room_key: str):
    """進行ch + レート更新ch + alpha/bravo VCを削除してbot_stateから削除"""
    dc = get_dynamic_channels()
    key = f"room_{room_key}"
    info = dc.get(key)
    if not info:
        return

    for ch_id in info.values():
        ch = guild.get_channel(ch_id)
        if ch:
            try:
                await ch.delete()
            except Exception:
                pass

    dc.pop(key, None)
    save_dynamic_channels(dc)






# =========================
# チャンネル取得（動的版）
# =========================
def get_progress_channel(guild, room_key):
    dc = get_dynamic_channels()
    info = dc.get(f"room_{room_key}")
    if not info:
        return None
    return guild.get_channel(info["progress"])

def get_room_rate_log_channel(guild, room_key):
    """動的レート更新チャンネルを取得"""
    dc = get_dynamic_channels()
    info = dc.get(f"room_{room_key}")
    if not info:
        return None
    return guild.get_channel(info.get("rate_log"))

def get_room_voice_channels(guild, room_key):
    dc = get_dynamic_channels()
    info = dc.get(f"room_{room_key}")
    lobby_id = ROOM_LOBBY_VC.get(room_key)
    lobby = guild.get_channel(lobby_id) if lobby_id else None
    if not info:
        return lobby, None, None
    return (
        lobby,
        guild.get_channel(info["alpha_vc"]),
        guild.get_channel(info["bravo_vc"]),
    )


def get_room_key_by_channel_id(channel_id: int):
    dc = get_dynamic_channels()
    for room_key in ("A", "B"):
        info = dc.get(f"room_{room_key}")
        if info and info.get("progress") == channel_id:
            return room_key
    return None

# =========================
# レート設定
# =========================
DEFAULT_RATING = 2500

# =========================
# バッジ定義
# =========================
BADGE_DEFINITIONS = {
    "ishigouri": {
        "label": "石狩",
        "emoji": "<:Ishigouri:1494024739591819465>"
    },
    "yuta": {
        "label": "悠太",
        "emoji": "<:Yuta:1494025087257673768>"
    },
    "rika": {
        "label": "里香",
        "emoji": "<:Rika:1494025347115516085>"
    },
    "ThanksfortheArt": {
        "label": "Thanks for the Art",
        "emoji": "<:ThanksfortheArt:1494173875439669330>"
    },
}

BANNER_DEFINITIONS = {
    "banner_default": {
        "label": "デフォルト",
        "url": ""
    },
}

PARTICIPATION_BONUS = 1
DISCONNECT_PENALTY = 50
DISCONNECT_REWARD = 8
DISCONNECT_GUILTY_THRESHOLD = 4
ROOM_CAPACITY = 8
TEAM_SIZE = 4

ROLE_BACKLINE = "backline"
ROLE_FLEX_BACKLINE = "flex_backline"
ROLE_OTHER = "other"
ROLE_LIMITS = {
    ROLE_BACKLINE: 2,
    ROLE_FLEX_BACKLINE: 2,
    ROLE_OTHER: 8,
}

# =========================
# Glicko-2
# =========================
GLICKO2_SCALE = 173.7178
DEFAULT_RD = 120.0
RD_MAX = 120.0
RD_MIN = 100.0
RD_DECAY = 0.85
DEFAULT_VOLATILITY = 0.06
TAU = 0.5
EPSILON = 0.000001


def load_ratings():
    try:
        with open(RATINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}

    normalized = {}
    for uid, value in data.items():
        if isinstance(value, (int, float)):
            normalized[uid] = {
                "rating": float(value),
                "rd": DEFAULT_RD,
                "volatility": DEFAULT_VOLATILITY,
            }
        elif isinstance(value, dict):
            normalized[uid] = {
                "rating": float(value.get("rating", DEFAULT_RATING)),
                "rd": float(value.get("rd", DEFAULT_RD)),
                "volatility": float(value.get("volatility", DEFAULT_VOLATILITY)),
            }
        else:
            normalized[uid] = {
                "rating": float(DEFAULT_RATING),
                "rd": DEFAULT_RD,
                "volatility": DEFAULT_VOLATILITY,
            }
    return normalized


def save_ratings(ratings_data):
    with open(RATINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(ratings_data, f, indent=2, ensure_ascii=False)


def get_rating_entry(user_id: int | str):
    uid = str(user_id)
    entry = ratings.get(uid)

    if entry is None:
        entry = {
            "rating": float(DEFAULT_RATING),
            "rd": DEFAULT_RD,
            "volatility": DEFAULT_VOLATILITY,
        }
        ratings[uid] = entry
    elif isinstance(entry, (int, float)):
        entry = {
            "rating": float(entry),
            "rd": DEFAULT_RD,
            "volatility": DEFAULT_VOLATILITY,
        }
        ratings[uid] = entry
    else:
        if "rating" not in entry:
            entry["rating"] = float(DEFAULT_RATING)
        if "rd" not in entry:
            entry["rd"] = DEFAULT_RD
        if "volatility" not in entry:
            entry["volatility"] = DEFAULT_VOLATILITY

    return entry


def get_user_rating(user_id: int | str):
    return int(round(get_rating_entry(user_id)["rating"]))


def set_user_rating(user_id: int | str, new_rating: float):
    get_rating_entry(user_id)["rating"] = float(new_rating)


def get_user_rd(user_id: int | str):
    return float(get_rating_entry(user_id)["rd"])


def set_user_rd(user_id: int | str, new_rd: float):
    get_rating_entry(user_id)["rd"] = float(new_rd)


def get_user_volatility(user_id: int | str):
    return float(get_rating_entry(user_id)["volatility"])


def set_user_volatility(user_id: int | str, new_v: float):
    get_rating_entry(user_id)["volatility"] = float(new_v)


def _g(phi):
    return 1.0 / math.sqrt(1.0 + 3.0 * (phi ** 2) / (math.pi ** 2))


def _E(mu, mu_j, phi_j):
    return 1.0 / (1.0 + math.exp(-_g(phi_j) * (mu - mu_j)))


def _f(x, delta, phi, v, a, tau):
    exp_x = math.exp(x)
    numerator = exp_x * (delta ** 2 - phi ** 2 - v - exp_x)
    denominator = 2.0 * ((phi ** 2 + v + exp_x) ** 2)
    return (numerator / denominator) - ((x - a) / (tau ** 2))


def glicko2_update(rating, rd, volatility, matches):
    if not matches:
        phi = rd / GLICKO2_SCALE
        phi_star = math.sqrt(phi ** 2 + volatility ** 2)
        return rating, phi_star * GLICKO2_SCALE, volatility

    mu = (rating - 1500.0) / GLICKO2_SCALE
    phi = rd / GLICKO2_SCALE

    converted = []
    for opp_rating, opp_rd, score in matches:
        mu_j = (opp_rating - 1500.0) / GLICKO2_SCALE
        phi_j = opp_rd / GLICKO2_SCALE
        converted.append((mu_j, phi_j, score))

    v_inv = sum((_g(phi_j) ** 2) * _E(mu, mu_j, phi_j) * (1.0 - _E(mu, mu_j, phi_j))
                for mu_j, phi_j, _ in converted)
    v = 1.0 / v_inv

    delta = v * sum(_g(phi_j) * (score - _E(mu, mu_j, phi_j))
                    for mu_j, phi_j, score in converted)

    a = math.log(volatility ** 2)
    A = a

    if delta ** 2 > phi ** 2 + v:
        B = math.log(delta ** 2 - phi ** 2 - v)
    else:
        k = 1
        while _f(a - k * TAU, delta, phi, v, a, TAU) < 0:
            k += 1
        B = a - k * TAU

    fA = _f(A, delta, phi, v, a, TAU)
    fB = _f(B, delta, phi, v, a, TAU)

    while abs(B - A) > EPSILON:
        C = A + (A - B) * fA / (fB - fA)
        fC = _f(C, delta, phi, v, a, TAU)
        if fC * fB < 0:
            A = B
            fA = fB
        else:
            fA /= 2.0
        B = C
        fB = fC

    new_volatility = math.exp(A / 2.0)
    phi_star = math.sqrt(phi ** 2 + new_volatility ** 2)
    new_phi = 1.0 / math.sqrt((1.0 / (phi_star ** 2)) + (1.0 / v))
    new_mu = mu + (new_phi ** 2) * sum(_g(phi_j) * (score - _E(mu, mu_j, phi_j))
                                        for mu_j, phi_j, score in converted)

    return 1500.0 + GLICKO2_SCALE * new_mu, GLICKO2_SCALE * new_phi, new_volatility


ratings = load_ratings()

RANK_EMOJI_1ST   = "<:1st:1494005979594100877>"
RANK_EMOJI_2_3   = "<:2nd_3rd:1496003826073993307>"
RANK_EMOJI_4_10  = "<:4th_10th:1496005097598091264>"
RANK_EMOJI_11_20 = "<:11th_20th:1496005336849711176>"


def get_sorted_rating_user_ids():
    if not ratings:
        return []
    return [uid for uid, _ in sorted(ratings.items(), key=lambda x: (-x[1]["rating"], x[0]))]


def get_user_rank(user_id: int):
    target_id = str(user_id)
    sorted_items = sorted(ratings.items(), key=lambda x: (-x[1]["rating"], x[0]))

    rank = 1
    prev_rate = None
    for i, (uid, data) in enumerate(sorted_items):
        rate = data["rating"]
        if prev_rate is not None and rate < prev_rate:
            rank = i + 1
        if uid == target_id:
            return rank
        prev_rate = rate
    return None


def build_private_rating_text(user_id: int, recent_limit: int = 5):
    """本人だけに返す現在レートと直近試合の表示を組み立てる。"""
    uid = str(user_id)
    current = get_user_rating(uid)
    peak = get_peak_rating(user_id)
    rank = get_user_rank(user_id)
    total = len(ratings)

    rank_text = f"{rank}位 / {total}人" if rank is not None else "記録なし"
    lines = [
        "# あなたのレート情報",
        "",
        f"現在レート：{current:,}",
        f"最高レート：{int(round(peak)):,}",
        f"現在順位：{rank_text}",
        "",
        f"## 直近{recent_limit}試合のレート推移",
    ]

    recent_matches = []
    for match in reversed(load_match_history()):
        alpha = match.get("alpha", [])
        bravo = match.get("bravo", [])
        if uid not in alpha and uid not in bravo:
            continue

        after = match.get("ratings_after", {}).get(uid)
        if after is None:
            continue

        my_team = "alpha" if uid in alpha else "bravo"
        result = "勝利" if match.get("winner") == my_team else "敗北"
        before = match.get("ratings_before", {}).get(uid)
        change = match.get("rating_changes", {}).get(uid)
        detail = match.get("rating_details", {}).get(uid, {})
        recent_matches.append({
            "result": result,
            "stage": match.get("stage") or "ステージ不明",
            "before": before,
            "after": after,
            "change": change,
            "ticket_label": detail.get("ticket_label"),
        })
        if len(recent_matches) >= recent_limit:
            break

    if not recent_matches:
        lines.extend(["", "試合記録がありません。"])
    else:
        for item in recent_matches:
            lines.extend(["", f"{item['result']}｜{item['stage']}"])
            before = item["before"]
            after = int(round(item["after"]))
            change = item["change"]
            if before is None or change is None:
                lines.append(f"試合後レート：{after:,}（過去データのため増減記録なし）")
            else:
                before = int(round(before))
                change = int(round(change))
                sign = "+" if change >= 0 else ""
                lines.append(f"{before:,} → {after:,}（{sign}{change}）")
            if item["ticket_label"]:
                lines.append(f"適用効果：{item['ticket_label']}")

    lines.extend(["", "この内容は、あなたにだけ表示されています。"])
    return "\n".join(lines)


# =========================
# プレイヤープロフィール
# =========================
def load_player_profiles():
    try:
        with open(PLAYER_PROFILES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_player_profiles(data):
    with open(PLAYER_PROFILES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


player_profiles = load_player_profiles()


def initialize_player_profile(user_id: int):
    uid = str(user_id)
    if uid not in player_profiles:
        player_profiles[uid] = {}

    profile = player_profiles[uid]
    changed = False

    defaults = {
        "weapon": None,
        "xp": None,
        "owned_badges": [],
        "selected_badge": None,
        "owned_banners": [],
        "selected_banner": None,
        "coins": 0,
        "tickets": [],
        "active_effect": None,
        "next_coin_at": None,
        "win_streak": 0,
        "last_played": None,
        "peak_rating": None,
    }

    for key, default_val in defaults.items():
        if key not in profile:
            profile[key] = default_val
            changed = True

    if profile["selected_badge"] and profile["selected_badge"] not in profile["owned_badges"]:
        profile["selected_badge"] = None
        changed = True

    if changed:
        save_player_profiles(player_profiles)

    return profile


def get_player_profile(user_id: int):
    uid = str(user_id)
    if uid not in player_profiles:
        return initialize_player_profile(user_id)
    return player_profiles[uid]


for uid in list(player_profiles.keys()):
    initialize_player_profile(int(uid))


def get_weapon_text(user_id: int):
    profile = get_player_profile(user_id)
    weapon = profile.get("weapon")
    return weapon if weapon else "未登録"

def get_current_class_text(user):
    rank = get_user_rank(user.id)
    if rank is None:
        return ""
    if rank == 1:
        return RANK_EMOJI_1ST
    if rank <= 3:
        return RANK_EMOJI_2_3
    if rank <= 10:
        return RANK_EMOJI_4_10
    if rank <= 20:
        return RANK_EMOJI_11_20
    return ""


def add_coin(user_id: int, amount: int):
    profile = get_player_profile(user_id)
    profile["coins"] = min(COIN_LIMIT, profile.get("coins", 0) + amount)


def remove_coin(user_id: int, amount: int):
    profile = get_player_profile(user_id)
    profile["coins"] = max(0, profile.get("coins", 0) - amount)


def roll_next_coin_seconds():
    return int(random.triangular(8 * 3600, 16 * 3600, 12 * 3600))


def set_next_coin_time(user_id: int):
    from datetime import datetime, timedelta
    profile = get_player_profile(user_id)
    next_dt = datetime.utcnow() + timedelta(seconds=roll_next_coin_seconds())
    profile["next_coin_at"] = next_dt.isoformat()


def try_claim_passive_coin(user_id: int):
    from datetime import datetime
    profile = get_player_profile(user_id)
    now = datetime.utcnow()
    next_coin_at = profile.get("next_coin_at")

    if not next_coin_at:
        set_next_coin_time(user_id)
        save_player_profiles(player_profiles)
        return False

    try:
        next_dt = datetime.fromisoformat(next_coin_at)
    except Exception:
        set_next_coin_time(user_id)
        save_player_profiles(player_profiles)
        return False

    if now >= next_dt:
        if profile.get("coins", 0) < COIN_LIMIT:
            add_coin(user_id, 1)
        set_next_coin_time(user_id)
        save_player_profiles(player_profiles)
        return True

    return False


def get_current_badge_text(user):
    profile = get_player_profile(user.id)
    selected_badge = profile.get("selected_badge")
    owned_badges = profile.get("owned_badges", [])

    if not selected_badge:
        return ""
    if selected_badge not in owned_badges:
        profile["selected_badge"] = None
        save_player_profiles(player_profiles)
        return ""

    badge_data = BADGE_DEFINITIONS.get(selected_badge)
    if not badge_data:
        return ""
    return badge_data.get("emoji", "")


def get_base_name(user, mention=False):
    return user.mention if mention else user.display_name


def build_player_display(
    user,
    *,
    mention=False,
    include_weapon=False,
    include_badge=False,
    include_rating=False,
    include_rate_change=False,
    old_rating=None,
    new_rating=None,
):
    class_text = get_current_class_text(user)
    badge_text = get_current_badge_text(user)
    name_text = get_base_name(user, mention=mention)

    line = name_text
    if class_text:
        line = f"{class_text} {line}"
    if include_weapon:
        line += f"（{get_weapon_text(user.id)}）"
    if include_badge and badge_text:
        line += f" {badge_text}"
    if include_rating:
        line += f" {get_user_rating(user.id)}"
    if include_rate_change:
        if old_rating is None:
            old_rating = get_user_rating(user.id)
        if new_rating is None:
            new_rating = get_user_rating(user.id)
        diff = new_rating - old_rating
        sign = "+" if diff >= 0 else ""
        line += f": {old_rating} → {new_rating} ({sign}{diff})"

    return line


def format_member_lines(members, *, mention=False, include_weapon=False, include_badge=False, include_rating=False):
    if not members:
        return "なし"
    return "\n".join(
        build_player_display(m, mention=mention, include_weapon=include_weapon,
                             include_badge=include_badge, include_rating=include_rating)
        for m in members
    )


def mark_match_played_for_members(members):
    pass


# =========================
# チケット定義
# =========================
TICKET_LIMIT = 3

TICKET_DEFINITIONS = {
    "rate_x1_1_10": {"label": "10試合 レート変動率 1.1倍", "type": "rate_multiplier", "multiplier": 1.1, "remaining_matches": 10},
    "rate_x1_2_10": {"label": "10試合 レート変動率 1.2倍", "type": "rate_multiplier", "multiplier": 1.2, "remaining_matches": 10},
    "rate_x1_3_10": {"label": "10試合 レート変動率 1.3倍", "type": "rate_multiplier", "multiplier": 1.3, "remaining_matches": 10},
    "rate_x1_5_5":  {"label": "5試合 レート変動率 1.5倍",  "type": "rate_multiplier", "multiplier": 1.5, "remaining_matches": 5},
    "rate_plus_3_10": {"label": "10試合 レート変動に +3", "type": "flat_bonus", "value": 3, "remaining_matches": 10},
    "rate_plus_5_10": {"label": "10試合 レート変動に +5", "type": "flat_bonus", "value": 5, "remaining_matches": 10},
    "rate_plus_10_5": {"label": "5試合 レート変動に +10", "type": "flat_bonus", "value": 10, "remaining_matches": 5},
    "win_bonus_1_15": {"label": "15試合 連勝ごとにボーナス +1", "type": "win_streak_bonus", "bonus_per_streak": 1, "remaining_matches": 15},
    "win_bonus_2_15": {"label": "15試合 連勝ごとにボーナス +2", "type": "win_streak_bonus", "bonus_per_streak": 2, "remaining_matches": 15},
    "streak_5_win_20": {"label": "15試合中 5連勝で +20", "type": "streak_reward", "target_streak": 5, "reward": 20, "remaining_matches": 15},
    "streak_7_win_50": {"label": "15試合中 7連勝で +50", "type": "streak_reward", "target_streak": 7, "reward": 50, "remaining_matches": 15},
    "weapon_jack": {"label": "武器ルーレット操作", "type": "weapon_jack", "remaining_matches": 1},
}
GACHA_ITEMS = [
    {"kind": "trivia",     "value": None,            "label": "雑学",                                           "weight": 63.0},
    {"kind": "rating",     "value": 1,               "label": "レート +1",                                      "weight": 3.0},
    {"kind": "rating",     "value": 5,               "label": "レート +5",                                      "weight": 1.0},
    {"kind": "rating",     "value": 10,              "label": "レート +10",                                     "weight": 0.5},
    {"kind": "ticket",     "value": "rate_x1_1_10",  "label": "10試合 レート変動率 1.1倍",                      "weight": 7.0},
    {"kind": "ticket",     "value": "rate_x1_2_10",  "label": "10試合 レート変動率 1.2倍",                      "weight": 5.0},
    {"kind": "ticket",     "value": "rate_x1_3_10",  "label": "10試合 レート変動率 1.3倍",                      "weight": 4.0},
    {"kind": "ticket",     "value": "rate_plus_3_10","label": "10試合 レート変動に +3",                          "weight": 0.2},
    {"kind": "ticket",     "value": "rate_plus_5_10","label": "10試合 レート変動に +5",                          "weight": 0.1},
    {"kind": "ticket",     "value": "rate_plus_10_5","label": "5試合 レート変動に +10",                          "weight": 1.0},
    {"kind": "ticket",     "value": "win_bonus_1_15","label": "15試合 連勝ごとにボーナス +1",                    "weight": 3.0},
    {"kind": "ticket",     "value": "streak_5_win_20","label": "15試合中 5連勝で +20",                           "weight": 2.0},
    {"kind": "ticket",     "value": "rate_x1_5_5",   "label": "5試合 レート変動率 1.5倍",                       "weight": 0.8},
    {"kind": "ticket",     "value": "win_bonus_2_15","label": "15試合 連勝ごとにボーナス +2",                    "weight": 0.7},
    {"kind": "ticket",     "value": "streak_7_win_50","label": "15試合中 7連勝で +50",                           "weight": 0.4},
    {"kind": "ticket",     "value": "weapon_jack",    "label": "武器ルーレット操作",                             "weight": 9.0},
    {"kind": "all_rating", "value": 10,              "label": "自分はレート +20 / コイン +2、ランダム3人はレート +10", "weight": 0.1},
]

TRIVIA_LIST = [
    "タコの心臓は3つある。",
    "ナマケモノは水中では意外と速く泳げる。",
    "サメには骨がなく、軟骨でできている。",
    "クマムシは宇宙空間でも生存できる。",
    "ペンギンにも膝がある。",
    "カタツムリには歯がある。",
    "イカの血は青い。",
    "ワニは舌をほとんど動かせない。",
    "コアラの指紋は人間と非常に似ている。",
    "シロアリはアリではなくゴキブリに近い。",
    "カメレオンは感情でも体色が変わる。",
    "イルカは片目ずつ眠れる。",
    "カエルは皮膚からも呼吸する。",
    "アリは自分の体重の数十倍を運べる。",
    "ダチョウの目は脳より大きい。",
    "カモノハシは卵を産む哺乳類である。",
    "ホタルはほとんど熱を出さずに発光する。",
    "シマウマの縞模様は1頭ごとに違う。",
    "ナマコは内臓を吐き出して身を守る。",
    "フクロウは首を270度近く回せる。",
    "ヒトデには脳がない。",
    "ゴリラも風邪をひく。",
    "ハトは鏡で自分を認識できる場合がある。",
    "カンガルーは後ろ向きに跳べない。",
    "ミツバチはダンスで仲間に場所を伝える。",
    "ペンギンは石をプレゼントして求愛することがある。",
    "ゾウはジャンプできない。",
    "カラスは道具を使えるほど賢い。",
    "シロナガスクジラは地球最大の動物である。",
    "ヘビはまぶたがない。",
    "ハムスターは片目ずつ独立して見やすい。",
    "カエルの中には凍っても生き返る種がいる。",
    "キツツキは脳震盪を起こしにくい構造を持つ。",
    "クラゲには心臓がない。",
    "ネコは甘味を感じにくい。",
    "犬の鼻紋は人間の指紋のように個体差がある。",
    "シロクマの毛は実は透明である。",
    "チーターは数秒しか全力疾走できない。",
    "アホウドリは飛びながら眠れる。",
    "人間のDNAはバナナとも約半分共通している。",
    "タツノオトシゴではオスが出産する。",
    "カメはお尻でも呼吸できる種類がいる。",
    "ゴキブリは頭がなくても数日生きられる。",
    "カラスは人の顔を覚える。",
    "カエルの舌は前向きに飛び出す。",
    "ハリネズミは泳げる。",
    "パンダの主食は竹だが肉も食べられる。",
    "ネズミは笑うことがある。",
    "クジャクが派手なのは主にオスである。",
    "カモメは海水を飲める。",
    "サケは生まれた川に戻ってくる。",
    "クモの糸は同じ太さの鋼鉄より強い場合がある。",
    "オオカミは遠吠えで仲間と連絡を取る。",
    "ゾウは低周波で長距離通信する。",
    "モグラはほとんど目が見えない。",
    "ラッコは寝るとき手をつなぐことがある。",
    "ヒヨコは卵の中で鳴く。",
    "フラミンゴがピンクなのは食べ物の色素の影響である。",
    "ナメクジにも脳がある。",
    "クジラの祖先は陸上動物だった。",
    "ワニは鳥に近い系統である。",
    "ハエは味を足で感じる。",
    "キリンの舌は青黒い。",
    "クマは冬眠中ほとんど排泄しない。",
    "ペンギンは海中を飛ぶように泳ぐ。",
    "サルにも利き手がある。",
    "ウミガメは地球の磁場を利用して移動する。",
    "ミミズには5つの心臓に似た器官がある。",
    "カタツムリは雌雄同体が多い。",
    "アザラシは潜水中に心拍数を下げる。",
    "トンボの複眼は数万個の目の集まりである。",
    "ナマズは電気を感じ取れる。",
    "ハチドリは後ろ向きに飛べる。",
    "ワニの涙は本当に出る。",
    "カピバラはネズミの仲間として最大級である。",
    "リスは冬用の食料を埋めた場所を忘れることがある。",
    "ダンゴムシはエビやカニに近い。",
    "ヤモリは足裏の微細構造で壁に張り付く。",
    "クラゲは95%以上が水分である。",
    "ペリカンのくちばしは大きく伸びる。",
    "サンゴは動物である。",
    "アリクイの舌は非常に長い。",
    "ハチは紫外線を見ることができる。",
    "モルモットはビタミンCを体内合成できない。",
    "シロナガスクジラの心臓は小型車ほどの大きさがある。",
    "クモは昆虫ではなく節足動物である。",
    "カエルの目は飲み込みを助ける役割もある。",
    "イモリは失った手足を再生できる。",
    "アルマジロは丸くなる種類がいる。",
    "エリア51には公開されていない地下区画が存在する。",
    "きさらぎ駅は実在する異界駅である。",
    "鏡を向かい合わせにすると異界への通路が開く。",
    "ネッシーは複数体存在している。",
    "UFOは軍事基地周辺に集まっている。",
    "電車の終点には存在しないホームが隠されている。",
    "深夜のトンネルでは時間感覚が狂う。",
    "廃病院には霊が集まり続けている。",
    "スレンダーマンは実在している。",
    "赤い服の霊は特に危険である。",
    "深夜の公衆電話は異世界に繋がっている。",
    "古い人形には魂が宿る。",
    "トンネルの壁を数えながら歩くと異界へ迷い込む。",
    "山奥には地図に載らない集落が存在する。",
    "深夜の学校では必ず誰かの足音が聞こえる。",
    "鏡を長時間見続けると別人が映る。",
    "エレベーターには押してはいけない順番が存在する。",
    "ネット掲示板には本物の怪異体験談が紛れている。",
    "深夜のコンビニには人間ではない店員が現れる。",
    "心霊スポット帰りには霊がついてくる。",
    "バックルームは現実世界の裏側に存在する。",
    "深夜ラジオには霊が集まりやすい。",
    "山道では同じ場所を永遠にループする現象が起きる。",
    "海の心霊スポットでは霊に引き込まれる。",
    "深夜の神社では空気そのものが変化する。",
    "動物は人間に見えない存在を認識している。",
    "古いトンネルには霊道が通っている。",
    "トイレの花子さんは全国の学校に存在する。",
    "未来人は災害前になると現れる。",
    "深夜の病院では誰もいない部屋からナースコールが鳴る。",
    "都市伝説は政府や組織によって隠蔽されている。",
    "日本語の「サボる」はフランス語由来と言われている。",
    "「アルバイト」はドイツ語由来の言葉である。",
    "漢字の「々」は正式には踊り字と呼ばれる。",
    "「コンセント」は和製英語である。",
    "「バイキング」は日本独自の食べ放題表現である。",
    "世界には文字を持たない言語も存在する。",
    "日本語の縦書き文化は世界的には少数派である。",
    "キリスト教では魚がシンボルとして使われることがある。",
    "イスラム教では左手を不浄と考える文化圏がある。",
    "神道には明確な開祖がいない。",
    "仏教には肉食を避ける文化がある。",
    "ユダヤ教では食事規定が非常に細かい。",
    "シク教では髪を切らない戒律がある。",
    "神社にいる狛犬は左右で役割が違う。",
    "パンダの模様って、でかいほくろらしい。",
    "でんのはるくんはバレル使い。",
    "コインは毎日19時に2枚付与される。",
    "コインの上限は5枚。",
]

COIN_LIMIT = 5
GACHA_COST = 1


def build_ticket_instance(ticket_id: str):
    data = TICKET_DEFINITIONS[ticket_id]
    return {
        "ticket_id": ticket_id,
        "label": data["label"],
        "type": data["type"],
        "remaining_matches": data["remaining_matches"],
        "multiplier": data.get("multiplier"),
        "value": data.get("value"),
        "bonus_per_streak": data.get("bonus_per_streak"),
        "target_streak": data.get("target_streak"),
        "reward": data.get("reward"),
    }


def get_active_effect_text(user_id: int):
    profile = get_player_profile(user_id)
    active_effect = profile.get("active_effect")
    if not active_effect:
        return "現在有効な効果はありません"
    label = active_effect.get("label", active_effect.get("ticket_id", "不明"))
    remaining = active_effect.get("remaining_matches")
    if remaining is None:
        return f"現在有効な効果:\n・{label}"
    return f"現在有効な効果:\n・{label}（残り{remaining}試合）"


def draw_gacha_item():
    weights = [item["weight"] for item in GACHA_ITEMS]
    return random.choices(GACHA_ITEMS, weights=weights, k=1)[0]

async def apply_gacha_result(guild, user_id: int, item):
    if item["kind"] == "trivia":
        return

    if item["kind"] == "rating":
        uid = str(user_id)
        set_user_rating(uid, get_user_rating(uid) + item["value"])
        save_ratings(ratings)

    elif item["kind"] == "ticket":
        profile = get_player_profile(user_id)
        tickets = profile.get("tickets", [])

        if len(tickets) >= TICKET_LIMIT:
            tickets.pop(0)

        tickets.append(build_ticket_instance(item["value"]))
        profile["tickets"] = tickets
        save_player_profiles(player_profiles)

    elif item["kind"] == "all_rating":
        try:
            members = [m async for m in guild.fetch_members(limit=None)]
        except Exception:
            members = guild.members

        human_members = [m for m in members if not m.bot]

        drawer = guild.get_member(user_id)
        if drawer is None:
            try:
                drawer = await guild.fetch_member(user_id)
            except Exception:
                return

        others = [m for m in human_members if m.id != user_id]
        selected = random.sample(others, min(3, len(others))) if others else []

        drawer_uid = str(drawer.id)
        set_user_rating(drawer_uid, get_user_rating(drawer_uid) + 20)

        profile = get_player_profile(drawer.id)
        profile["coins"] = min(profile.get("coins", 0) + 2, COIN_LIMIT)

        for member in selected:
            uid = str(member.id)
            set_user_rating(uid, get_user_rating(uid) + item["value"])

        save_ratings(ratings)
        save_player_profiles(player_profiles)

        target_lines = [f"・{drawer.display_name}（レート +20 / コイン +2）"]
        target_lines.extend(
            [f"・{m.display_name}（レート +10）" for m in selected]
        )

        admin_text = (
            f"# 【領域展開「坐殺博徒」】\n\n"
            f"{drawer.display_name} ……！正に……豪運……！！\n\n"
            f"# <:Tobuze:1494883064806113430>「漲る呪力（ボーナス）でトぶぜ」\n\n"
            f"# 本人：レート +20 / コイン +2\n"
            f"ランダムで{len(selected)}人にレート +10\n\n"
            f"▼対象\n" + "\n".join(target_lines)
        )

        public_text = (
            f"# 【領域展開「坐殺博徒」】\n\n"
            f"{drawer.display_name} ……！正に……豪運……！！\n\n"
            "特別報酬が発生しました。報酬内容は本人のみ確認できます。"
        )

        admin_channel = get_admin_channel(guild)
        if admin_channel:
            try:
                await admin_channel.send(admin_text)
            except Exception:
                pass

        home_channel = guild.get_channel(HOME_CHANNEL_ID)
        if home_channel:
            try:
                await home_channel.send(public_text, delete_after=20)
            except Exception:
                pass

        for room_key in ("A", "B"):
            channel = get_progress_channel(guild, room_key)
            if channel:
                try:
                    await channel.send(public_text)
                except Exception:
                    pass

# =========================
# Discord設定
# =========================
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True

bot = commands.Bot(
command_prefix="!",
intents=intents,
allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True)
)


# =========================
# 状態管理
# =========================
badge_bulk_waiting = {}
bulk_rate_change_waiting = {}
bulk_profile_edit_waiting = {}
bulk_admin_waiting = {}
otp_demo_bulk_waiting = {}

ROOM_KEYS = ("A", "B")

STAGES = [
    "ユノハナ大渓谷", "ゴンズイ地区", "ヤガラ市場", "マテガイ放水路",
    "ナメロウ金属", "マサバ海峡大橋", "キンメダイ美術館", "マヒマヒリゾート&スパ",
    "海女美術大学", "チョウザメ造船", "ザトウマーケット", "スメーシーワールド",
    "クサヤ温泉", "ヒラメが丘団地", "ナンプラー遺跡", "マンタマリア号",
    "タラポートショッピングパーク", "コンブトラック", "タカアシ経済特区",
    "オヒョウ海運", "バイガイ亭", "ネギトロ炭鉱", "カジキ空港",
    "リュウグウターミナル", "デカライン高架下",
]

def create_room_state():
    return {
        "game_state": "idle",
        "host_id": None,
        "joined_players": [],
        "current_match": None,
        "prepared_match": None,
        "last_rating_changes": None,
        "last_rating_detail": None,
        "last_profile_snapshots": None,
        "last_match_timestamp": None,
        "control_message": None,
        "disconnect_vote_message": None,
        "session_start_ratings": {},
        "session_participants": {},
        "recruit_roles": {},
        "team_pattern_count": 70,
        "disconnect_vote": None,
        "current_stage": None,
        "next_stage": None,
        "excluded_stages": [],
        "lost_enabled": False,
        "lost_stages": [],
    }


room_states = {
    "A": create_room_state(),
    "B": create_room_state(),
}

active_recruits = {}

# =========================
# ユーティリティ
# =========================
def reset_room_tracking(room_state):
    room_state["session_start_ratings"] = {}
    room_state["session_participants"] = {}


def reset_room_state(room_state):
    room_state["game_state"] = "idle"
    room_state["host_id"] = None
    room_state["joined_players"] = []
    room_state["current_match"] = None
    room_state["prepared_match"] = None
    room_state["last_rating_changes"] = None
    room_state["last_rating_detail"] = None
    room_state["last_profile_snapshots"] = None
    room_state["last_match_timestamp"] = None
    room_state["control_message"] = None
    room_state["disconnect_vote_message"] = None
    room_state["recruit_roles"] = {}
    room_state["team_pattern_count"] = 70
    room_state["disconnect_vote"] = None
    room_state["current_stage"] = None
    room_state["next_stage"] = None
    room_state["excluded_stages"] = []


def get_home_channel(guild):
    return guild.get_channel(HOME_CHANNEL_ID)


def get_recruit_channel(guild):
    return guild.get_channel(RECRUIT_CHANNEL_ID)


def get_rate_log_channel(guild):
    return guild.get_channel(RATE_LOG_CHANNEL_ID)


def get_ranking_channel(guild):
    return guild.get_channel(RANKING_CHANNEL_ID)


def get_admin_channel(guild):
    return guild.get_channel(ADMIN_CHANNEL_ID)

def get_peak_rating_channel(guild):
    return guild.get_channel(PEAK_RATING_CHANNEL_ID)

def update_peak_rating(user_id: int):
    profile = get_player_profile(user_id)
    current = get_user_rating(user_id)
    peak = profile.get("peak_rating")
    if peak is None or current > peak:
        profile["peak_rating"] = current
        return True
    return False

def get_peak_rating(user_id: int):
    profile = get_player_profile(user_id)
    peak = profile.get("peak_rating")
    if peak is None:
        return get_user_rating(user_id)
    return peak

def get_top5_peak_ratings(guild):
    result = []
    for member in guild.members:
        if member.bot:
            continue
        peak = get_peak_rating(member.id)
        result.append((peak, member))
    result.sort(key=lambda x: (-x[0], x[1].display_name.lower()))
    return result[:5]

async def post_peak_ranking(guild):
    # 最高レートの公開表示はWebに集約する。
    return

async def check_and_update_peak_ranking(guild, user_ids: list):
    changed = False
    for user_id in user_ids:
        if update_peak_rating(int(user_id)):
            changed = True

    if changed:
        save_player_profiles(player_profiles)
        await post_peak_ranking(guild)

def calc_team_avg(team):
    if not team:
        return 0
    return int(sum(get_user_rating(u.id) for u in team) / len(team))


async def move_members_to_vc(guild, room_key, team_alpha, team_bravo):
    _, vc_alpha, vc_bravo = get_room_voice_channels(guild, room_key)
    if vc_alpha is None or vc_bravo is None:
        return
    for member in team_alpha:
        if member.voice:
            try:
                await member.move_to(vc_alpha)
            except Exception:
                pass
    for member in team_bravo:
        if member.voice:
            try:
                await member.move_to(vc_bravo)
            except Exception:
                pass


async def move_members_to_lobby(guild, room_key, room_state):
    lobby_vc, _, _ = get_room_voice_channels(guild, room_key)
    if lobby_vc is None:
        return
    moved_ids = set()
    for member in room_state["session_participants"].values():
        if member.id in moved_ids:
            continue
        if member.voice:
            try:
                await member.move_to(lobby_vc)
                moved_ids.add(member.id)
            except Exception:
                pass


def ensure_session_player(room_state, user):
    user_id = str(user.id)
    room_state["session_participants"][user_id] = user
    if user_id not in room_state["session_start_ratings"]:
        room_state["session_start_ratings"][user_id] = get_user_rating(user_id)
    profile = get_player_profile(user.id)
    profile["display_name"] = user.display_name
    save_player_profiles(player_profiles)


def get_joined_user_ids(room_state):
    return [str(u.id) for u in room_state["joined_players"]]


def is_joined(room_state, user):
    return user in room_state["joined_players"]


PATTERN_MULTIPLIER_TABLE = {70: 1.75, 40: 1.69, 24: 1.56}


def get_pattern_multiplier(room_state):
    count = room_state.get("team_pattern_count", 70)
    return PATTERN_MULTIPLIER_TABLE.get(count, 1.75)


def apply_rd_decay_recovery(user_id: int | str):
    uid = str(user_id)
    entry = get_rating_entry(uid)
    profile = get_player_profile(int(uid))
    now = time.time()
    last_played = profile.get("last_played")

    if last_played is None:
        profile["last_played"] = now
        return

    days_passed = (now - last_played) / 86400.0
    if days_passed <= 0:
        return

    recovery = min(10.0, days_passed * 1.5)
    entry["rd"] = min(RD_MAX, float(entry["rd"]) + recovery)
    profile["last_played"] = now


def get_rate_multiplier(user_id: int):
    profile = get_player_profile(user_id)
    active_effect = profile.get("active_effect")
    if not active_effect:
        return 1.0
    if active_effect.get("type") == "rate_multiplier":
        return float(active_effect.get("multiplier", 1.0))
    return 1.0


def consume_active_effect_match(user_id: int):
    profile = get_player_profile(user_id)
    active_effect = profile.get("active_effect")
    if not active_effect:
        return
    remaining = active_effect.get("remaining_matches")
    if remaining is None:
        return
    remaining -= 1
    if remaining <= 0:
        profile["active_effect"] = None
    else:
        active_effect["remaining_matches"] = remaining


def get_win_streak_bonus(user_id: int):
    profile = get_player_profile(user_id)
    active_effect = profile.get("active_effect")
    current_streak = profile.get("win_streak", 0)
    if not active_effect:
        return 0
    effect_type = active_effect.get("type")
    if effect_type == "win_streak_bonus":
        return current_streak * int(active_effect.get("bonus_per_streak", 0))
    if effect_type == "streak_reward":
        if current_streak == int(active_effect.get("target_streak", 0)):
            return int(active_effect.get("reward", 0))
    return 0


def grant_room_coin_lottery(room_state):
    changed = False
    for member in room_state["session_participants"].values():
        if random.random() < 0.8:
            profile = get_player_profile(member.id)
            old_coins = profile.get("coins", 0)
            new_coins = min(COIN_LIMIT, old_coins + 1)
            if new_coins != old_coins:
                profile["coins"] = new_coins
                changed = True
    if changed:
        save_player_profiles(player_profiles)


def update_win_streaks(winners, losers):
    for user in winners:
        profile = get_player_profile(user.id)
        profile["win_streak"] = profile.get("win_streak", 0) + 1
    for user in losers:
        profile = get_player_profile(user.id)
        profile["win_streak"] = 0


async def get_member_display_name_by_id(guild, user_id: int):
    member = guild.get_member(user_id)
    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except Exception:
            member = None
    return member.display_name if member else f"ユーザーID:{user_id}"

TEAM_ROLE_COMPOSITIONS = {
    (0, 0): ((0, 0, 4), (0, 0, 4)),
    (0, 1): ((0, 1, 3), (0, 0, 4)),
    (0, 2): ((0, 1, 3), (0, 1, 3)),
    (1, 0): ((1, 0, 3), (0, 0, 4)),
    (1, 1): ((1, 0, 3), (0, 1, 3)),
    (1, 2): ((1, 1, 2), (0, 1, 3)),
    (2, 0): ((1, 0, 3), (1, 0, 3)),
    (2, 1): ((1, 1, 2), (1, 0, 3)),
    (2, 2): ((1, 1, 2), (1, 1, 2)),
}


def get_team_role_composition(team, roles):
    return (
        sum(roles.get(str(u.id)) == ROLE_BACKLINE for u in team),
        sum(roles.get(str(u.id)) == ROLE_FLEX_BACKLINE for u in team),
        sum(roles.get(str(u.id)) == ROLE_OTHER for u in team),
    )


def make_teams_from_roles(room_state):
    players = room_state["joined_players"]
    roles = room_state.get("recruit_roles", {})
    if len(players) != ROOM_CAPACITY or any(str(u.id) not in roles for u in players):
        raise ValueError("8人全員の募集時役割が必要です。")

    backline_count = sum(roles[str(u.id)] == ROLE_BACKLINE for u in players)
    flex_count = sum(roles[str(u.id)] == ROLE_FLEX_BACKLINE for u in players)
    required = TEAM_ROLE_COMPOSITIONS.get((backline_count, flex_count))
    if required is None:
        raise ValueError("後衛の人数構成が不正です。")

    required_sides = {required[0], required[1]}
    candidates = []
    for alpha_combo in combinations(players, TEAM_SIZE):
        alpha = list(alpha_combo)
        alpha_ids = {u.id for u in alpha}
        bravo = [u for u in players if u.id not in alpha_ids]
        alpha_comp = get_team_role_composition(alpha, roles)
        bravo_comp = get_team_role_composition(bravo, roles)
        if alpha_comp not in required_sides or bravo_comp not in required_sides:
            continue
        if sorted((alpha_comp, bravo_comp)) != sorted(required):
            continue
        alpha_sum = sum(get_user_rating(u.id) for u in alpha)
        bravo_sum = sum(get_user_rating(u.id) for u in bravo)
        candidates.append((abs(alpha_sum - bravo_sum), alpha, bravo))

    if not candidates:
        raise ValueError("役割条件を満たすチーム編成がありません。")

    candidates.sort(key=lambda item: item[0])
    room_state["team_pattern_count"] = len(candidates)
    top_candidates = candidates[:5]
    weights = [5, 4, 3, 2, 1][:len(top_candidates)]
    _, team_alpha, team_bravo = random.choices(top_candidates, weights=weights, k=1)[0]
    return team_alpha, team_bravo


def create_room_summary_text(room_state):
    if not room_state["session_participants"]:
        return None

    rows = []
    for user_id, member in room_state["session_participants"].items():
        start_rate = room_state["session_start_ratings"].get(user_id, DEFAULT_RATING)
        end_rate = get_user_rating(user_id)
        diff = end_rate - start_rate
        rows.append((diff, end_rate, member, start_rate))
    rows.sort(key=lambda x: (-x[0], -x[1], x[2].display_name.lower()))

    lines = ["【今回の部屋のレート増減】"]
    for diff, end_rate, member, start_rate in rows:
        lines.append(build_player_display(
            member, include_badge=True, include_rate_change=True,
            old_rating=start_rate, new_rating=end_rate,
        ))

    trivia = random.choice(TRIVIA_LIST)
    lines.append("")
    lines.append(f"# 今日の雑学: {trivia}")

    return "\n".join(lines)

# =========================
# コントロールメッセージ（進行チャンネル1枚管理）
# =========================
async def update_control_message(guild, room_key, content, view=None):
    room_state = room_states[room_key]
    channel = get_progress_channel(guild, room_key)
    if channel is None:
        return

    existing = room_state.get("control_message")
    if existing:
        try:
            await existing.edit(content=content, view=view)
            return
        except Exception:
            pass

    msg = await channel.send(content, view=view)
    room_state["control_message"] = msg


async def delete_control_message(room_state):
    msg = room_state.get("control_message")
    if msg:
        try:
            await msg.delete()
        except Exception:
            pass
    room_state["control_message"] = None


# =========================
# テキスト生成
# =========================
def create_ready_text(room_state):
    team_alpha, team_bravo = room_state["prepared_match"]
    mention_list = " ".join(u.mention for u in room_state["joined_players"])

    alpha_names = " ".join(build_player_display(u) for u in team_alpha)
    bravo_names = " ".join(build_player_display(u) for u in team_bravo)

    lines = [
        "【チーム分け完了】",
        mention_list,
        "",
        f"アルファ: {alpha_names}",
        f"ブラボー: {bravo_names}",
        "",
        "開始時刻になったら試合を始めるボタンを押してください",
    ]
    return "\n".join(lines)

def create_playing_text(team_alpha, team_bravo, room_key=None):
    excluded = []
    lost_stages = []
    lost_enabled = False
    preset_stage = None
    if room_key:
        excluded = room_states[room_key].get("excluded_stages", [])
        lost_enabled = room_states[room_key].get("lost_enabled", False)
        lost_stages = room_states[room_key].get("lost_stages", [])
        preset_stage = room_states[room_key].pop("next_stage", None)

    if preset_stage:
        stage = preset_stage
    else:
        if lost_enabled:
            available_stages = [s for s in STAGES if s not in excluded and s not in lost_stages]
            if not available_stages:
                room_states[room_key]["lost_stages"] = []
                lost_stages = []
                available_stages = [s for s in STAGES if s not in excluded]
        else:
            available_stages = [s for s in STAGES if s not in excluded]

        if not available_stages:
            available_stages = STAGES

        stage = random.choice(available_stages)

    if room_key:
        room_states[room_key]["current_stage"] = stage
        if lost_enabled and stage not in room_states[room_key]["lost_stages"]:
            room_states[room_key]["lost_stages"].append(stage)

    def fmt(team):
        return "\n".join(
            build_player_display(u, include_badge=True)
            for u in team
        )

    return (
        f"【試合中】\n\n"
        f"ステージ: {stage}\n\n"
        f"【アルファ】\n{fmt(team_alpha)}\n\n"
        f"【ブラボー】\n{fmt(team_bravo)}"
    )

def create_finished_text(room_state, room_key=None):
    lines = ["【試合終了】次の行動を選んでください。", ""]

    prepared = room_state.get("prepared_match")
    if prepared:
        next_team_alpha, next_team_bravo = prepared

        if room_key:
            excluded = room_state.get("excluded_stages", [])
            lost_enabled = room_state.get("lost_enabled", False)
            lost_stages = room_state.get("lost_stages", [])
            if lost_enabled:
                available = [s for s in STAGES if s not in excluded and s not in lost_stages]
                if not available:
                    available = [s for s in STAGES if s not in excluded]
            else:
                available = [s for s in STAGES if s not in excluded]
            if not available:
                available = STAGES
            next_stage = random.choice(available)
            room_state["next_stage"] = next_stage
        else:
            next_stage = None

        if next_stage:
            lines.append(f"【次のステージ】{next_stage}")
            lines.append("")

        alpha_names = " ".join(build_player_display(u) for u in next_team_alpha)
        bravo_names = " ".join(build_player_display(u) for u in next_team_bravo)
        lines.append("【次回チーム分け】")
        lines.append(f"アルファ: {alpha_names}")
        lines.append(f"ブラボー: {bravo_names}")

    return "\n".join(lines)


def create_disconnect_vote_text(target):
    from datetime import datetime
    now_str = datetime.now().strftime("%Y年%m月%d日")
    target_text = build_player_display(target)
    return (
        "【領域展開「誅伏賜死」】\n\n"
        "<:Judgeman:1493076764816314508>\n"
        f"{target_text} は {now_str}\n"
        "試合途中にラグや回線落ちをした疑いがある。\n\n"
        "対象者本人は「自白」または「否認」\n"
        "試合参加者は「有罪」または「無罪」を選択してください。\n\n"
        "※ 投票は匿名です\n"
        f"※ 有罪が{DISCONNECT_GUILTY_THRESHOLD}票以上で回線落ち処理を行います\n"
        "※ 有罪が3票以下の場合は通常の試合結果入力に戻ります"
    )


# =========================
# 募集モーダル
# =========================
class LostModeSelectView(discord.ui.View):
    def __init__(self, host_name, plave_content, start_time, user_id, excluded_stages):
        super().__init__(timeout=60)
        self.host_name = host_name
        self.plave_content = plave_content
        self.start_time = start_time
        self.user_id = user_id
        self.excluded_stages = excluded_stages

    @discord.ui.button(label="ロスト制あり", style=discord.ButtonStyle.primary)
    async def lost_yes(self, interaction: discord.Interaction, button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("自分の募集のみ操作できます", ephemeral=True)
            return
        await finalize_recruit_creation(
            interaction, self.plave_content, self.start_time, self.host_name,
            self.excluded_stages, lost_enabled=True
        )

    @discord.ui.button(label="ロスト制なし", style=discord.ButtonStyle.secondary)
    async def lost_no(self, interaction: discord.Interaction, button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("自分の募集のみ操作できます", ephemeral=True)
            return
        await finalize_recruit_creation(
            interaction, self.plave_content, self.start_time, self.host_name,
            self.excluded_stages, lost_enabled=False
        )
        
class StageExcludeView(discord.ui.View):
    def __init__(self, host_name: str, plave_content: str, start_time: str, user_id: int):
        super().__init__(timeout=60)
        self.host_name = host_name
        self.plave_content = plave_content
        self.start_time = start_time
        self.user_id = user_id

        options = [
            discord.SelectOption(label=stage, value=stage)
            for stage in STAGES
        ]
        select = discord.ui.Select(
            placeholder="除外するステージを選択（複数可、スキップ可）",
            options=options,
            min_values=0,
            max_values=len(STAGES),
        )

        async def select_callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("自分の募集のみ操作できます", ephemeral=True)
                return
            excluded = select.values
            await interaction.response.edit_message(
                content="ロスト制の設定を選んでください",
                view=LostModeSelectView(self.host_name, self.plave_content, self.start_time, self.user_id, excluded)
            )

        select.callback = select_callback
        self.add_item(select)

    @discord.ui.button(label="除外なしで次へ", style=discord.ButtonStyle.secondary)
    async def skip_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("自分の募集のみ操作できます", ephemeral=True)
            return
        await interaction.response.edit_message(
            content="ロスト制の設定を選んでください",
            view=LostModeSelectView(self.host_name, self.plave_content, self.start_time, self.user_id, [])
        )


class RecruitModal(discord.ui.Modal, title="募集作成"):
    content_input = discord.ui.TextInput(
        label="プラベ内容",
        placeholder="例：エリアプラベ",
        max_length=50,
    )
    start_time_input = discord.ui.TextInput(
        label="開始時刻",
        placeholder="例：21:00から1時間",
        max_length=50,
    )

    def __init__(self, host_name: str):
        super().__init__()
        self.host_name = host_name

    async def on_submit(self, interaction: discord.Interaction):
        plave_content = str(self.content_input).strip()
        start_time = str(self.start_time_input).strip()
        await interaction.response.send_message(
            "除外するステージを選択してください（スキップも可能）",
            view=StageExcludeView(self.host_name, plave_content, start_time, interaction.user.id),
            ephemeral=True
        )


async def finalize_recruit_creation(interaction: discord.Interaction, plave_content: str, start_time: str, host_name: str, excluded_stages: list, lost_enabled: bool = False):
    recruit_channel = get_recruit_channel(interaction.guild)
    if recruit_channel is None:
        await interaction.response.send_message("募集チャンネルが見つかりません", ephemeral=True)
        return

    cooldown_remaining = get_recruit_cooldown_remaining(interaction.guild.id, interaction.user.id)
    if cooldown_remaining:
        minutes, seconds = divmod(cooldown_remaining, 60)
        wait_text = f"{minutes}分{seconds}秒" if minutes else f"{seconds}秒"
        await interaction.response.send_message(
            f"募集は10分に1回までです。あと{wait_text}待ってから作成してください。",
            ephemeral=True,
        )
        return

    notification_role = get_recruit_notification_role(interaction.guild)
    if notification_role is None:
        await interaction.response.send_message("募集通知ロールが見つかりません。運営に連絡してください。", ephemeral=True)
        return

    stage_text = "一部除外" if excluded_stages else "除外なし"
    lost_text = "ロスト制あり" if lost_enabled else ""

    await recruit_channel.send(
        notification_role.mention,
        allowed_mentions=discord.AllowedMentions(roles=[notification_role]),
    )

    lines = [
        f"【募集】参加する場合は下のボタンをおしてください！",
        f"プラベ内容: {plave_content}",
        f"開始時刻: {start_time}",
        f"ステージ: {stage_text}",
    ]
    if lost_text:
        lines.append(f"ロスト制: {lost_text}")
    lines += [
        f"募集主: {host_name}",
        "",
        f"0/{ROOM_CAPACITY}人",
        "",
        "参加者なし",
    ]
    content = "\n".join(lines)

    view = RecruitView()

    msg = await recruit_channel.send(content, view=view)
    record_recruit_creation(interaction.guild.id, interaction.user.id)

    active_recruits[msg.id] = {
        "joined_players": [],
        "roles": {},
        "host_id": interaction.user.id,
        "host_name": host_name,
        "plave_content": plave_content,
        "start_time": start_time,
        "excluded_stages": excluded_stages,
        "lost_enabled": lost_enabled,
        "message_id": msg.id,
        "capacity": ROOM_CAPACITY,
        "notify_message_id": None,
    }

    await interaction.response.edit_message(content="募集を作成しました！", view=None)
HELP_TEXTS = {
    "flow": (
        "【試合の流れ】\n\n"
        "① 募集作成\n"
        "ホームの「募集作成」ボタンを押して、プラベ内容と開始時刻を入力します。\n"
        "除外するステージを選択後、募集チャンネルに募集メッセージが投稿されます。\n\n"
        "② 参加\n"
        "参加したい人は「後衛」「後衛でもいい」「その他」から役割を選びます。\n"
        "人数が集まると自動で確定します。\n\n"
        "③ 部屋作成・自動チーム分け\n"
        "「部屋を作成」を押すと、役割とレートを基に自動でチーム分けします。\n\n"
        "④ 試合開始\n"
        "チームを確認して「試合を始める」ボタンを押します。\n"
        "VCに自動で振り分けられます。\n\n"
        "⑤ 結果入力\n"
        "試合が終わったら募集主が「アルファ勝ち」か「ブラボー勝ち」を押します。\n"
        "レートが自動で更新されます。\n\n"
        "⑥ 続ける・終わる\n"
        "「次の試合」で続けるか「終了」で部屋を閉じます。\n"
        "間違えた場合は「結果訂正」で1つ戻せます。\n\n"
        "⑦ 緊急中断\n"
        "何かトラブルがあった場合は、進行チャンネルで\n"
        "「!やめる」と送ると部屋を強制終了できます。"
    ),
    "coin": (
        "【コイン・ガチャ・チケット】\n\n"
        "🪙 コイン\n"
        "・毎日19時に全員へ2枚配布されます\n"
        "・上限は5枚です\n\n"
        "🎰 ガチャ\n"
        "・コイン1枚でガチャを1回引けます\n"
        "・当たる内容：レートボーナス・チケット・雑学\n"
        "・稀に秤金次が出てくることがあります\n\n"
        "🎫 チケット\n"
        "・ガチャで入手できます\n"
        "・最大3枚まで所持できます\n"
        "・一度に使えるのは1枚だけです\n"
        "・効果中は新しいチケットを使えません\n\n"
        "チケットの種類：\n"
        "・レート変動率 1.1〜1.5倍（5〜10試合）\n"
        "・レート変動に +3〜+10（5〜10試合）\n"
        "・連勝ごとにボーナス +1〜+2（15試合）\n"
        "・5連勝で +20、7連勝で +50（15試合）\n"
        "・武器ルーレット操作：次の武器ルーレットプラベで\n"
        "　全員の武器を自分が指定した武器に固定できます"
    ),
    "rate": (
        "【レートについて】\n\n"
        "📊 基本\n"
        "・初期レートは2500です\n"
        "・試合結果に応じてレートが増減します\n\n"
        "📈 レート変動\n"
        "・勝利：相手チームとのレート差や試合のパターンに\n"
        "　応じて変動します\n"
        "・敗北：同様に減少します\n"
        "・参加ボーナス：試合に参加するだけで+1されます\n"
        "・募集主ボーナス：募集を作成すると+5されます\n\n"
        "⚠️ 回線落ち\n"
        "・回線落ち投票で有罪になると -50されます\n"
        "・その試合の他の参加者は +8されます\n\n"
        "ランキングと最高レートはWebサイトで確認できます。\n"
        "Discordでは専用チャンネルのボタンから、自分の情報だけ確認できます。"
    ),
}


class HelpSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

        select = discord.ui.Select(
            placeholder="何について知りたいですか？",
            options=[
                discord.SelectOption(label="試合の流れ", value="flow"),
                discord.SelectOption(label="コイン・ガチャ・チケット", value="coin"),
                discord.SelectOption(label="レートについて", value="rate"),
            ]
        )

        async def select_callback(interaction: discord.Interaction):
            text = HELP_TEXTS.get(select.values[0], "説明が見つかりませんでした")
            await interaction.response.send_message(text, ephemeral=True)

        select.callback = select_callback
        self.add_item(select)

class TriviaModal(discord.ui.Modal, title="雑学投稿"):
    trivia_input = discord.ui.TextInput(
        label="雑学の内容",
        placeholder="例：タコの心臓は3つある。",
        max_length=100,
        style=discord.TextStyle.paragraph,
    )

    async def on_submit(self, interaction: discord.Interaction):
        trivia = str(self.trivia_input).strip()
        admin_channel = get_admin_channel(interaction.guild)
        if admin_channel:
            name = build_player_display(interaction.user, include_badge=True)
            await admin_channel.send(f"【雑学投稿】\n{name}\n→ {trivia}")
        await interaction.response.send_message(
            "投稿しました！反映には少し時間がかかります。",
            ephemeral=True
        )


# =========================
# 募集View
# =========================
class RecruitView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        labels = {
            "recruit_backline": ("後衛", ROLE_BACKLINE),
            "recruit_flex_backline": ("後衛でもいい", ROLE_FLEX_BACKLINE),
            "recruit_other": ("その他", ROLE_OTHER),
        }
        for child in self.children:
            if child.custom_id in labels:
                label, _ = labels[child.custom_id]
                child.label = f"{label}（0/{ROLE_LIMITS[labels[child.custom_id][1]]}）"

    def update_button_counts(self, recruit_data):
        labels = {
            "recruit_backline": ("後衛", ROLE_BACKLINE),
            "recruit_flex_backline": ("後衛でもいい", ROLE_FLEX_BACKLINE),
            "recruit_other": ("その他", ROLE_OTHER),
        }
        roles = recruit_data.get("roles", {})
        for child in self.children:
            if child.custom_id in labels:
                label, role = labels[child.custom_id]
                count = sum(value == role for value in roles.values())
                child.label = f"{label}（{count}/{ROLE_LIMITS[role]}）"

    def build_content(self, recruit_data):
        players = recruit_data["joined_players"]
        roles = recruit_data.get("roles", {})
        plave_content = recruit_data.get("plave_content", "プラベ")
        start_time = recruit_data["start_time"]
        host_name = recruit_data.get("host_name", "")
        excluded_stages = recruit_data.get("excluded_stages", [])
        stage_text = "一部除外" if excluded_stages else "除外なし"
        lost_enabled = recruit_data.get("lost_enabled", False)
        capacity = recruit_data.get("capacity", ROOM_CAPACITY)
        total = len(players)

        role_sections = []
        for role, label in (
            (ROLE_BACKLINE, "後衛"),
            (ROLE_FLEX_BACKLINE, "後衛でもいい"),
            (ROLE_OTHER, "その他"),
        ):
            members = [p for p in players if roles.get(str(p.id)) == role]
            member_lines = "\n".join(f"・{build_player_display(p, include_weapon=True)}" for p in members) or "・なし"
            role_sections.append(f"【{label} {len(members)}/{ROLE_LIMITS[role]}】\n{member_lines}")

        content_lines = [
            f"【募集】参加する場合は下のボタンをおしてください！",
            f"プラベ内容: {plave_content}",
            f"開始時刻: {start_time}",
            f"ステージ: {stage_text}",
        ]
        if lost_enabled:
            content_lines.append("ロスト制: ロスト制あり")
        content_lines += [
            f"募集主: {host_name}",
            "",
            f"{total}/{capacity}人",
            "",
            "\n\n".join(role_sections),
        ]
        return "\n".join(content_lines)

    async def send_notify_message(self, recruit_channel, recruit_data):
        capacity = recruit_data.get("capacity", ROOM_CAPACITY)
        plave_content = recruit_data.get("plave_content", "プラベ")
        total = len(recruit_data["joined_players"])
        remaining = capacity - total

        old_notify_id = recruit_data.get("notify_message_id")
        if old_notify_id:
            try:
                old_msg = await recruit_channel.fetch_message(old_notify_id)
                await old_msg.delete()
            except Exception:
                pass
            recruit_data["notify_message_id"] = None

        if total >= capacity:
            return

        notify_msg = await recruit_channel.send(f"{plave_content}@{remaining}")
        recruit_data["notify_message_id"] = notify_msg.id

    async def handle_role(self, interaction: discord.Interaction, role: str):
        recruit_data = active_recruits.get(interaction.message.id)
        if recruit_data is None:
            await interaction.response.send_message("この募集は無効です", ephemeral=True)
            return

        user = interaction.user
        players = recruit_data["joined_players"]
        roles = recruit_data.setdefault("roles", {})
        capacity = recruit_data.get("capacity", ROOM_CAPACITY)
        uid = str(user.id)
        current_role = roles.get(uid)
        role_count = sum(value == role for key, value in roles.items() if key != uid)
        if role_count >= ROLE_LIMITS[role]:
            await interaction.response.send_message("この役割は満員です", ephemeral=True)
            return

        if current_role is None and len(players) >= capacity:
            await interaction.response.send_message("満員です", ephemeral=True)
            return

        if current_role is None:
            players.append(user)
        roles[uid] = role
        total = len(players)
        self.update_button_counts(recruit_data)
        content = self.build_content(recruit_data)
        recruit_channel = get_recruit_channel(interaction.guild)

        if total >= capacity:
            await interaction.response.edit_message(content=content, view=self)
            old_notify_id = recruit_data.get("notify_message_id")
            if old_notify_id and recruit_channel:
                try:
                    old_msg = await recruit_channel.fetch_message(old_notify_id)
                    await old_msg.delete()
                except Exception:
                    pass
                recruit_data["notify_message_id"] = None
            await self.finalize_recruit(interaction, recruit_data)
        else:
            await interaction.response.edit_message(content=content, view=self)
            if recruit_channel:
                await self.send_notify_message(recruit_channel, recruit_data)

    @discord.ui.button(label="後衛（0/2）", style=discord.ButtonStyle.primary, custom_id="recruit_backline")
    async def backline_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_role(interaction, ROLE_BACKLINE)

    @discord.ui.button(label="後衛でもいい（0/2）", style=discord.ButtonStyle.primary, custom_id="recruit_flex_backline")
    async def flex_backline_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_role(interaction, ROLE_FLEX_BACKLINE)

    @discord.ui.button(label="その他（0/8）", style=discord.ButtonStyle.secondary, custom_id="recruit_other")
    async def other_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_role(interaction, ROLE_OTHER)

    @discord.ui.button(label="抜ける", style=discord.ButtonStyle.secondary, custom_id="recruit_leave")
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        recruit_data = active_recruits.get(interaction.message.id)
        if recruit_data is None:
            await interaction.response.send_message("この募集は無効です", ephemeral=True)
            return

        user = interaction.user
        players = recruit_data["joined_players"]

        if not any(p.id == user.id for p in players):
            await interaction.response.send_message("参加していません", ephemeral=True)
            return

        recruit_data["joined_players"] = [p for p in players if p.id != user.id]
        recruit_data.setdefault("roles", {}).pop(str(user.id), None)
        self.update_button_counts(recruit_data)
        content = self.build_content(recruit_data)
        await interaction.response.edit_message(content=content, view=self)

        recruit_channel = get_recruit_channel(interaction.guild)
        if recruit_channel:
            await self.send_notify_message(recruit_channel, recruit_data)

    async def finalize_recruit(self, interaction: discord.Interaction, recruit_data):
        players = recruit_data["joined_players"]
        roles = recruit_data.get("roles", {})
        recruit_channel = get_recruit_channel(interaction.guild)
        plave_content = recruit_data.get("plave_content", "プラベ")
        excluded_stages = recruit_data.get("excluded_stages", [])
        stage_text = "一部除外" if excluded_stages else "除外なし"
        host_name = recruit_data.get("host_name", "")

        mention_list = " ".join(p.mention for p in players)
        role_labels = {
            ROLE_BACKLINE: "後衛",
            ROLE_FLEX_BACKLINE: "後衛でもいい",
            ROLE_OTHER: "その他",
        }
        lines = [f"{build_player_display(p, include_weapon=True)}（{role_labels[roles[str(p.id)]]}）" for p in players]
        player_lines = "\n".join(lines)

        content = (
            f"【募集確定】\n"
            f"プラベ内容: {plave_content}\n"
            f"開始時刻: {recruit_data['start_time']}\n"
            f"ステージ: {stage_text}\n"
            f"募集主: {host_name}\n\n"
            f"{mention_list}\n\n"
            f"▼参加者\n{player_lines}\n\n"
            f"開始時刻になったら部屋を作成してください"
        )

        try:
            await interaction.message.delete()
        except Exception:
            pass

        view = RecruitConfirmView()
        new_msg = await recruit_channel.send(content, view=view)

        active_recruits[new_msg.id] = recruit_data
        active_recruits.pop(recruit_data["message_id"], None)
        recruit_data["message_id"] = new_msg.id
        recruit_data["confirm_message_id"] = new_msg.id


class RecruitConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="部屋を作成", style=discord.ButtonStyle.success, custom_id="recruit_start_game")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        recruit_data = active_recruits.get(interaction.message.id)
        if recruit_data is None:
            await interaction.response.send_message("この募集データが見つかりません", ephemeral=True)
            return

        players = recruit_data["joined_players"]

        if not any(p.id == interaction.user.id for p in players):
            await interaction.response.send_message("参加者のみ押せます", ephemeral=True)
            return

        room_key = None
        for rk in ROOM_KEYS:
            if room_states[rk]["game_state"] == "idle":
                room_key = rk
                break

        if room_key is None:
            await interaction.response.send_message("現在空いている部屋がありません", ephemeral=True)
            return

        await interaction.response.send_message("チャンネルを作成しています...", ephemeral=True)

        room_state = room_states[room_key]
        reset_room_state(room_state)
        reset_room_tracking(room_state)

        room_state["joined_players"] = players[:]
        room_state["recruit_roles"] = dict(recruit_data.get("roles", {}))
        room_state["host_id"] = str(recruit_data["host_id"])
        room_state["excluded_stages"] = recruit_data.get("excluded_stages", [])
        room_state["lost_enabled"] = recruit_data.get("lost_enabled", False)
        room_state["lost_stages"] = []

        for player in players:
            ensure_session_player(room_state, player)

        participant_ids = [str(p.id) for p in players]
        await create_room_channels(interaction.guild, room_key, participant_ids)

        host_id = recruit_data["host_id"]
        old = get_user_rating(host_id)
        set_user_rating(host_id, old + 5)
        save_ratings(ratings)

        try:
            room_state["prepared_match"] = make_teams_from_roles(room_state)
        except Exception as e:
            await interaction.followup.send(f"チーム分けに失敗しました: {e}", ephemeral=True)
            set_user_rating(host_id, old)
            save_ratings(ratings)
            await delete_room_channels(interaction.guild, room_key)
            reset_room_state(room_state)
            reset_room_tracking(room_state)
            return
        room_state["game_state"] = "ready"

        try:
            await interaction.message.delete()
        except Exception:
            pass

        active_recruits.pop(interaction.message.id, None)

        await begin_ready(interaction.guild, room_key)

# =========================
# 進行View（ボタン化）
# =========================
class BaseControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    def disable_all_buttons(self):
        for child in self.children:
            child.disabled = True


class ReadyView(BaseControlView):
    def __init__(self, room_key, room_state):
        super().__init__()
        self.room_key = room_key
        self.room_state = room_state

    @discord.ui.button(label="試合を始める", style=discord.ButtonStyle.success)
    async def start_button(self, interaction: discord.Interaction, button):
        if interaction.user not in self.room_state["joined_players"]:
            await interaction.response.send_message("この部屋の参加者ではありません", ephemeral=True)
            return

        if self.room_state["game_state"] != "ready":
            await interaction.response.send_message("今は試合開始できません", ephemeral=True)
            return

        self.disable_all_buttons()
        await interaction.response.edit_message(content=create_ready_text(self.room_state), view=self)
        await start_game(interaction.guild, self.room_key)

class PlayingView(BaseControlView):
    def __init__(self, room_key, room_state):
        super().__init__()
        self.room_key = room_key
        self.room_state = room_state

    def _is_host(self, user):
        return str(user.id) == str(self.room_state.get("host_id", ""))

    @discord.ui.button(label="アルファ勝ち", style=discord.ButtonStyle.primary)
    async def alpha_win_button(self, interaction: discord.Interaction, button):
        await self.handle_result(interaction, 1)

    @discord.ui.button(label="ブラボー勝ち", style=discord.ButtonStyle.primary)
    async def bravo_win_button(self, interaction: discord.Interaction, button):
        await self.handle_result(interaction, 2)

    @discord.ui.button(label="回線落ち", style=discord.ButtonStyle.danger)
    async def disconnect_button(self, interaction: discord.Interaction, button):
        if interaction.user not in self.room_state["joined_players"]:
            await interaction.response.send_message("この部屋の参加者ではありません", ephemeral=True)
            return

        if self.room_state["game_state"] != "playing":
            await interaction.response.send_message("今は試合中ではありません", ephemeral=True)
            return

        if not self.room_state["current_match"]:
            await interaction.response.send_message("試合情報がありません", ephemeral=True)
            return

        all_players = self.room_state["current_match"][0] + self.room_state["current_match"][1]
        options = [
            discord.SelectOption(label=p.display_name, value=str(p.id))
            for p in all_players
        ]

        select = discord.ui.Select(placeholder="回線落ちしたプレイヤーを選択", options=options)

        async def select_callback(select_interaction: discord.Interaction):
            if select_interaction.user not in self.room_state["joined_players"]:
                await select_interaction.response.send_message("この部屋の参加者ではありません", ephemeral=True)
                return

            target_id = int(select.values[0])
            target_member = select_interaction.guild.get_member(target_id)
            if target_member is None:
                try:
                    target_member = await select_interaction.guild.fetch_member(target_id)
                except Exception:
                    await select_interaction.response.send_message("メンバーが見つかりません", ephemeral=True)
                    return

            await select_interaction.response.send_message("回線落ち投票を開始します", ephemeral=True)
            await start_disconnect_vote(select_interaction.guild, self.room_key, target_member)

        select.callback = select_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.response.send_message("回線落ちしたプレイヤーを選んでください", view=view, ephemeral=True)

    async def handle_result(self, interaction: discord.Interaction, winner_num: int):
        if not self._is_host(interaction.user):
            await interaction.response.send_message("募集主のみ押せます", ephemeral=True)
            return

        if self.room_state["game_state"] != "playing":
            await interaction.response.send_message("今は試合中ではありません", ephemeral=True)
            return

        self.disable_all_buttons()
        await interaction.response.edit_message(view=self)
        await process_result(interaction.guild, self.room_key, winner_num)

class FinishedView(BaseControlView):
    def __init__(self, room_key, room_state):
        super().__init__()
        self.room_key = room_key
        self.room_state = room_state

    @discord.ui.button(label="次の試合", style=discord.ButtonStyle.success)
    async def next_button(self, interaction: discord.Interaction, button):
        if interaction.user not in self.room_state["joined_players"]:
            await interaction.response.send_message("この部屋の参加者ではありません", ephemeral=True)
            return

        if self.room_state["game_state"] != "finished":
            await interaction.response.send_message("今は次の試合を開始できません", ephemeral=True)
            return

        self.disable_all_buttons()
        await interaction.response.edit_message(view=self)
        await next_game(interaction.guild, self.room_key)

    @discord.ui.button(label="終了", style=discord.ButtonStyle.danger)
    async def end_button(self, interaction: discord.Interaction, button):
        if interaction.user not in self.room_state["joined_players"]:
            await interaction.response.send_message("この部屋の参加者ではありません", ephemeral=True)
            return

        if self.room_state["game_state"] != "finished":
            await interaction.response.send_message("今は終了できません", ephemeral=True)
            return

        self.disable_all_buttons()
        await interaction.response.edit_message(view=self)
        await end_room(interaction.guild, self.room_key)

    @discord.ui.button(label="結果訂正", style=discord.ButtonStyle.secondary)
    async def undo_button(self, interaction: discord.Interaction, button):
        if interaction.user not in self.room_state["joined_players"]:
            await interaction.response.send_message("この部屋の参加者ではありません", ephemeral=True)
            return

        if self.room_state["game_state"] != "finished":
            await interaction.response.send_message("今は訂正できません", ephemeral=True)
            return

        self.disable_all_buttons()
        await interaction.response.edit_message(view=self)
        await undo_result(interaction.guild, self.room_key)


class DisconnectVoteView(BaseControlView):
    def __init__(self, room_key, room_state):
        super().__init__()
        self.room_key = room_key
        self.room_state = room_state

    async def record_self_vote(self, interaction: discord.Interaction, vote_value: str):
        if self.room_state["game_state"] != "disconnect_vote" or self.room_state["disconnect_vote"] is None:
            await interaction.response.send_message("今は投票中ではありません", ephemeral=True)
            return

        uid = str(interaction.user.id)
        target_id = self.room_state["disconnect_vote"]["target_id"]

        if uid != target_id:
            await interaction.response.send_message("このボタンは対象者本人のみ押せます", ephemeral=True)
            return

        self.room_state["disconnect_vote"]["self_vote"] = vote_value
        await interaction.response.send_message("投票を受け付けました", ephemeral=True)

        if vote_value == "confess":
            self.disable_all_buttons()
            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass
            target_member = self.room_state["session_participants"].get(target_id)
            if target_member:
                await finalize_disconnect_vote(interaction.guild, self.room_key, target_member, forced_by_confession=True)

    async def record_jury_vote(self, interaction: discord.Interaction, vote_value: str):
        if self.room_state["game_state"] != "disconnect_vote" or self.room_state["disconnect_vote"] is None:
            await interaction.response.send_message("今は投票中ではありません", ephemeral=True)
            return

        uid = str(interaction.user.id)
        target_id = self.room_state["disconnect_vote"]["target_id"]

        if uid == target_id:
            await interaction.response.send_message("対象者本人は有罪/無罪を押せません", ephemeral=True)
            return

        if self.room_state["current_match"] is None:
            await interaction.response.send_message("試合情報がありません", ephemeral=True)
            return

        if interaction.user not in (self.room_state["current_match"][0] + self.room_state["current_match"][1]):
            await interaction.response.send_message("今回の試合参加者ではありません", ephemeral=True)
            return

        self.room_state["disconnect_vote"]["jury_votes"][uid] = vote_value
        await interaction.response.send_message("投票を受け付けました", ephemeral=True)

        guilty_count = sum(1 for v in self.room_state["disconnect_vote"]["jury_votes"].values() if v == "guilty")
        voters = [u for u in (self.room_state["current_match"][0] + self.room_state["current_match"][1])
                  if str(u.id) != target_id]

        if guilty_count >= DISCONNECT_GUILTY_THRESHOLD:
            self.disable_all_buttons()
            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass
            target_member = self.room_state["session_participants"].get(target_id)
            if target_member:
                await finalize_disconnect_vote(interaction.guild, self.room_key, target_member, forced_by_confession=False)
            return

        if len(self.room_state["disconnect_vote"]["jury_votes"]) == len(voters):
            self.disable_all_buttons()
            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass
            await resolve_disconnect_not_established(interaction.guild, self.room_key)

    @discord.ui.button(label="自白", style=discord.ButtonStyle.danger)
    async def confess_button(self, interaction, button):
        await self.record_self_vote(interaction, "confess")

    @discord.ui.button(label="否認", style=discord.ButtonStyle.secondary)
    async def deny_button(self, interaction, button):
        await self.record_self_vote(interaction, "deny")

    @discord.ui.button(label="有罪", style=discord.ButtonStyle.primary)
    async def guilty_button(self, interaction, button):
        await self.record_jury_vote(interaction, "guilty")

    @discord.ui.button(label="無罪", style=discord.ButtonStyle.success)
    async def innocent_button(self, interaction, button):
        await self.record_jury_vote(interaction, "innocent")


# =========================
# 本人用レート確認View
# =========================
class RateCheckView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="自分のレートを見る",
        style=discord.ButtonStyle.primary,
        custom_id="rate_check_self",
    )
    async def rate_check_button(self, interaction: discord.Interaction, button):
        text = build_private_rating_text(interaction.user.id)
        await interaction.response.send_message(text, ephemeral=True)


# =========================
# ホームView
# =========================
class PlayerRegisterModal(discord.ui.Modal, title="プレイヤー登録"):
    weapon_input = discord.ui.TextInput(
        label="持ち武器",
        placeholder="例：スシ、52、ハイドラ",
        max_length=100,
    )
    xp_input = discord.ui.TextInput(
        label="最高XP",
        placeholder="500〜5000の整数を入力",
        max_length=10,
    )

    async def on_submit(self, interaction: discord.Interaction):
        user = interaction.user
        profile = get_player_profile(user.id)

        weapon = str(self.weapon_input).strip()
        xp_text = str(self.xp_input).strip()

        if not weapon:
            await interaction.response.send_message("持ち武器を入力してくれ。", ephemeral=True)
            return

        if not xp_text.isdigit():
            await interaction.response.send_message("最高XPは500〜5000の整数で入力してくれ。", ephemeral=True)
            return

        xp = int(xp_text)
        if xp < 500 or xp > 5000:
            await interaction.response.send_message("最高XPは500〜5000の範囲で入力してくれ。", ephemeral=True)
            return

        profile["weapon"] = weapon
        profile["xp"] = xp

        lines = [
            f"持ち武器を登録したぞ！ → {weapon}",
            f"最高XPを登録したぞ！ → {xp}",
        ]

        save_player_profiles(player_profiles)
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

        admin_channel = get_admin_channel(interaction.guild)
        if admin_channel:
            display_name = build_player_display(user, include_badge=True)
            await admin_channel.send(
                f"【登録通知】\n{display_name} が登録を完了しました\n"
                f"武器: {weapon}\n最高XP: {xp}\n現在レート: {get_user_rating(user.id)}"
            )


class BadgeSelectView(discord.ui.View):
    def __init__(self, user):
        super().__init__(timeout=60)
        self.user = user

        profile = get_player_profile(user.id)
        owned = profile.get("owned_badges", [])

        options = []
        for badge_id in owned:
            badge_data = BADGE_DEFINITIONS.get(badge_id, {})
            label = badge_data.get("label", badge_id)
            emoji = badge_data.get("emoji")
            if emoji:
                options.append(discord.SelectOption(label=label, value=badge_id, emoji=emoji))
            else:
                options.append(discord.SelectOption(label=label, value=badge_id))

        if not options:
            self.add_item(discord.ui.Select(
                placeholder="選べるバッジがありません",
                options=[discord.SelectOption(label="なし", value="none")],
                disabled=True
            ))
        else:
            select = discord.ui.Select(placeholder="表示するバッジを選択", options=options)

            async def select_callback(interaction: discord.Interaction):
                if interaction.user.id != self.user.id:
                    await interaction.response.send_message("自分のバッジだけ変更できます", ephemeral=True)
                    return
                selected = select.values[0]
                profile = get_player_profile(self.user.id)
                profile["selected_badge"] = selected
                save_player_profiles(player_profiles)
                badge_data = BADGE_DEFINITIONS.get(selected, {})
                await interaction.response.send_message(f"バッジを変更しました: {badge_data.get('label', selected)}", ephemeral=True)

            select.callback = select_callback
            self.add_item(select)

class CoinMenuView(discord.ui.View):
    def __init__(self, user):
        super().__init__(timeout=60)
        self.user = user

    @discord.ui.button(label="ガチャ", style=discord.ButtonStyle.success)
    async def gacha_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("自分のメニューだけ操作できます", ephemeral=True)
            return

        if get_player_profile(self.user.id).get("coins", 0) < GACHA_COST:
            await interaction.response.send_message("コインが足りません", ephemeral=True)
            return

        remove_coin(self.user.id, GACHA_COST)
        save_player_profiles(player_profiles)

        item = draw_gacha_item()
        await apply_gacha_result(interaction.guild, self.user.id, item)

        admin_channel = get_admin_channel(interaction.guild)
        if admin_channel:
            name = build_player_display(interaction.user, include_badge=True)
            if item["kind"] == "trivia":
                trivia = random.choice(TRIVIA_LIST)
                await admin_channel.send(f"【ガチャ結果】\n{name}\n→ 雑学: {trivia}")
                result_text = trivia
            else:
                await admin_channel.send(f"【ガチャ結果】\n{name}\n→ {item['label']}")

        if item["kind"] == "ticket":
            result_text = f"〈チケット〉{item['label']}"
        elif item["kind"] != "trivia":
            result_text = item["label"]

        await interaction.response.send_message(f"ガチャ結果\n→ {result_text}", ephemeral=True)

    @discord.ui.button(label="チケット一覧", style=discord.ButtonStyle.primary)
    async def ticket_list_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("自分のメニューだけ操作できます", ephemeral=True)
            return

        profile = get_player_profile(self.user.id)
        tickets = profile.get("tickets", [])
        lines = []
        if tickets:
            lines.append("保持チケット:")
            for i, ticket in enumerate(tickets, start=1):
                lines.append(f"{i}. {ticket.get('label', ticket.get('ticket_id', '不明'))}")
        else:
            lines.append("保持チケットはありません")
        lines.append("")
        lines.append(get_active_effect_text(self.user.id))
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @discord.ui.button(label="チケット使用", style=discord.ButtonStyle.danger)
    async def ticket_use_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("自分のメニューだけ操作できます", ephemeral=True)
            return

        profile = get_player_profile(self.user.id)
        tickets = profile.get("tickets", [])

        if profile.get("active_effect"):
            await interaction.response.send_message(
                "すでに効果中のチケットがあります\n\n" + get_active_effect_text(self.user.id),
                ephemeral=True
            )
            return

        if not tickets:
            await interaction.response.send_message("使用できるチケットがありません", ephemeral=True)
            return

        options = [
            discord.SelectOption(
                label=t.get("label", t.get("ticket_id", "不明"))[:100],
                value=str(i)
            )
            for i, t in enumerate(tickets)
        ]
        select = discord.ui.Select(placeholder="使用するチケットを選択", options=options)

        async def select_callback(select_interaction: discord.Interaction):
            if select_interaction.user.id != self.user.id:
                await select_interaction.response.send_message("自分のチケットだけ使用できます", ephemeral=True)
                return

            index = int(select.values[0])
            profile = get_player_profile(self.user.id)
            tickets = profile.get("tickets", [])

            if index < 0 or index >= len(tickets):
                await select_interaction.response.send_message("そのチケットは存在しません", ephemeral=True)
                return

            active_ticket = tickets.pop(index)
            profile["tickets"] = tickets

            if active_ticket.get("type") == "weapon_jack":
                profile["tickets"] = tickets
                save_player_profiles(player_profiles)
                await select_interaction.response.send_message(
                    "武器ルーレット操作チケットはこのモードでは使用できません",
                    ephemeral=True
                )
                return

            profile["active_effect"] = active_ticket
            save_player_profiles(player_profiles)

            admin_channel = get_admin_channel(select_interaction.guild)
            if admin_channel:
                name = build_player_display(select_interaction.user, include_badge=True)
                label = active_ticket.get("label", active_ticket.get("ticket_id", "不明"))
                await admin_channel.send(f"【チケット使用】\n{name}\n→ {label}")

            await select_interaction.response.send_message(
                "チケットを使用しました\n\n" + get_active_effect_text(self.user.id),
                ephemeral=True
            )

        select.callback = select_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.response.send_message("使用するチケットを選んでください", view=view, ephemeral=True)

OTP_SLOT_LABELS = ["チームリーダー", "メンバー1", "メンバー2", "メンバー3"]
OTP_STATUS_CHANNEL_EMOJIS = {
    "未承認 ☑️": "☑️",
    "承認 ✅": "✅",
    "棄権 ❌": "❌",
}


def otp_player_block(label: str, player: dict, name: str, circle: str) -> str:
    player = player or {}
    weapons = "、".join(player.get("weapons", [])) or "未入力"
    rate = player.get("top_weapon_rate")
    rate_text = f"{rate}%" if rate is not None else "未入力"
    return (
        f"{label}｜{name or '未入力'}（{circle or '未入力'}）\n"
        f"XP {player.get('xp', '未入力')}｜{weapons}｜補正 {rate_text}｜補正XP {player.get('corrected_xp', '未計算')}"
    )


def otp_team_summary(team: dict) -> str:
    players = team.get("players", {})
    member_names = (team.get("member_names", []) + ["未入力"] * 3)[:3]
    member_circles = (team.get("member_circles", []) + ["未入力"] * 3)[:3]
    player_names = [team.get("leader_name", "未入力"), *member_names]
    player_circles = [team.get("leader_circle", "未入力"), *member_circles]
    corrected = [p.get("corrected_xp") for p in players.values() if p.get("corrected_xp") is not None]
    average = "計算待ち" if len(corrected) != 4 else f"{sum(corrected) / 4:.2f}"
    lines = [
        f"【チーム{team['number']}｜{team.get('team_name') or '未入力'}】",
        f"{team.get('status', '未承認 ☑️')}｜補正XP平均：{average}",
        f"一言：{team.get('enthusiasm') or '未入力'}",
        "",
    ]
    summary_labels = ["リーダー", "メンバー1", "メンバー2", "メンバー3"]
    for index, label in enumerate(summary_labels):
        lines.extend([otp_player_block(label, players.get(str(index)), player_names[index], player_circles[index]), ""])
    return "\n".join(lines).strip()


async def refresh_otp_team_messages(guild: discord.Guild, team: dict):
    content = otp_team_summary(team)
    message_id = team.get("summary_message_id")
    channel = guild.get_channel(OTP_TEAM_SUMMARY_CHANNEL_ID)
    if not channel or not message_id:
        return
    try:
        message = await channel.fetch_message(message_id)
        await message.edit(content=content)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        pass


async def remove_otp_team_channel_summaries(guild: discord.Guild):
    """旧仕様で作成したチーム個別チャンネル内の情報サマリーだけを削除する。"""
    changed = False
    for team in get_otp_teams().values():
        message_id = team.get("channel_message_id")
        channel = guild.get_channel(team.get("channel_id"))
        if message_id and channel:
            try:
                message = await channel.fetch_message(message_id)
                await message.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        if "channel_message_id" in team:
            team.pop("channel_message_id", None)
            changed = True
    if changed:
        save_otp_teams()


def otp_team_intro(team: dict) -> str:
    leader = team.get("leader_name", "チームリーダー")
    members = team.get("member_names", ["メンバー1", "メンバー2", "メンバー3"])
    return (
        f"*{leader}*さん、申請ありがとうございます！\n\n"
        "① メンバー招待\nチームメンバー全員を、このDiscordサーバーへ招待してください。\n\n"
        "② サマリー提出\nサマリーは動画でこのテキストチャンネルに提出してください。\n\n"
        "③ プレイヤー情報入力\nチームメンバー4人それぞれが、自分に対応するボタンを押して情報を入力してください。\n"
        f"・チームリーダー：{leader}\n・メンバー1：{members[0]}\n・メンバー2：{members[1]}\n・メンバー3：{members[2]}\n\n"
        "入力する情報\n・最高XP\n・2026 Sizzle Seasonのブキ使用率上位3つ\n・使用率1位ブキの使用率（%）\n\n"
        "補正XPは「最高XP − 使用率1位ブキの使用率」で自動計算します。\n\n"
        f"④ 確認\n4人全員の入力が完了したら、運営（{OTP_STAFF_MENTION}）が内容を確認します。\n"
        "確認が終わるまで、このチャンネルでお待ちください。\n\n大会までよろしくお願いします！"
    )


async def update_otp_team_intros(guild: discord.Guild):
    """既存チームの案内文も最新の内容へ統一する。"""
    for team in get_otp_teams().values():
        channel = guild.get_channel(team.get("channel_id"))
        if not channel:
            continue
        message_id = team.get("intro_message_id")
        try:
            if message_id:
                message = await channel.fetch_message(message_id)
                await message.edit(content=otp_team_intro(team))
                continue
            async for message in channel.history(limit=50):
                if message.author.id == bot.user.id and "申請ありがとうございます！" in (message.content or ""):
                    await message.edit(content=otp_team_intro(team))
                    team["intro_message_id"] = message.id
                    save_otp_teams()
                    break
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass


class OTPPlayerModal(discord.ui.Modal):
    def __init__(self, team_key: str, slot: int):
        super().__init__(title=f"{OTP_SLOT_LABELS[slot]}の情報")
        self.team_key = team_key
        self.slot = slot
        self.xp = discord.ui.TextInput(label="最高XP", placeholder="数字だけ", required=True, max_length=10)
        self.weapon1 = discord.ui.TextInput(label="使用率1位ブキ", required=True, max_length=100)
        self.weapon2 = discord.ui.TextInput(label="使用率2位ブキ", required=True, max_length=100)
        self.weapon3 = discord.ui.TextInput(label="使用率3位ブキ", required=True, max_length=100)
        self.rate = discord.ui.TextInput(label="使用率1位ブキの使用率（%）", placeholder="数字だけ", required=True, max_length=10)
        for field in (self.xp, self.weapon1, self.weapon2, self.weapon3, self.rate):
            self.add_item(field)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            xp = float(str(self.xp.value).strip())
            rate = float(str(self.rate.value).strip().replace("%", ""))
            if xp < 0 or not 0 <= rate <= 100:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("最高XPは0以上、使用率は0〜100の数字で入力してください。", ephemeral=True)
            return
        team = get_otp_teams().get(self.team_key)
        if not team:
            await interaction.response.send_message("このチーム情報は見つかりません。", ephemeral=True)
            return
        corrected = xp - rate
        team.setdefault("players", {})[str(self.slot)] = {
            "xp": int(xp) if xp.is_integer() else xp,
            "weapons": [str(self.weapon1.value).strip(), str(self.weapon2.value).strip(), str(self.weapon3.value).strip()],
            "top_weapon_rate": int(rate) if rate.is_integer() else rate,
            "corrected_xp": int(corrected) if corrected.is_integer() else corrected,
        }
        save_otp_teams()
        await refresh_otp_team_messages(interaction.guild, team)
        await interaction.response.send_message(f"{OTP_SLOT_LABELS[self.slot]}の情報を更新しました。", ephemeral=True)


class OTPTeamInputView(discord.ui.View):
    def __init__(self, team_key: str):
        super().__init__(timeout=None)
        self.team_key = team_key
        for index, label in enumerate(OTP_SLOT_LABELS):
            button = discord.ui.Button(label=label, style=discord.ButtonStyle.primary, custom_id=f"otp_player:{team_key}:{index}")
            button.callback = self.make_callback(index)
            self.add_item(button)

    def make_callback(self, slot: int):
        async def callback(interaction: discord.Interaction):
            await interaction.response.send_modal(OTPPlayerModal(self.team_key, slot))
        return callback


class OTPStatusSelect(discord.ui.Select):
    def __init__(self, team_key: str, team_name: str):
        options = [
            discord.SelectOption(label="未承認 ☑️", value="未承認 ☑️"),
            discord.SelectOption(label="承認 ✅", value="承認 ✅"),
            discord.SelectOption(label="棄権 ❌", value="棄権 ❌"),
        ]
        super().__init__(placeholder="ステータスを選択", options=options, min_values=1, max_values=1)
        self.team_key = team_key
        self.team_name = team_name

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("この操作は運営のみ実行できます。", ephemeral=True)
            return
        team = get_otp_teams().get(self.team_key)
        if not team:
            await interaction.response.send_message("チームが見つかりません。", ephemeral=True)
            return
        team["team_name"] = self.team_name
        team["status"] = self.values[0]
        save_otp_teams()
        team_channel = interaction.guild.get_channel(team.get("channel_id"))
        if team_channel:
            emoji = OTP_STATUS_CHANNEL_EMOJIS.get(team["status"], "☑️")
            try:
                await team_channel.edit(name=f"{emoji}{self.team_name}", reason="OTP杯チームのステータス更新")
            except (discord.Forbidden, discord.HTTPException):
                pass
        await refresh_otp_team_messages(interaction.guild, team)
        await interaction.response.edit_message(
            content=f"チーム{team['number']}を「{self.team_name}」として、ステータスを「{team['status']}」に更新しました。",
            view=None,
        )


class OTPStatusSelectView(discord.ui.View):
    def __init__(self, team_key: str, team_name: str):
        super().__init__(timeout=120)
        self.add_item(OTPStatusSelect(team_key, team_name))


class OTPTeamManagementModal(discord.ui.Modal, title="チーム情報を更新"):
    team_number = discord.ui.TextInput(label="チーム番号", placeholder="例：1", required=True, max_length=6)
    team_name = discord.ui.TextInput(label="チーム名", placeholder="例：Kogane", required=True, max_length=100)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("この操作は運営のみ実行できます。", ephemeral=True)
            return
        team_key = str(self.team_number.value).strip()
        team = get_otp_teams().get(team_key)
        if not team:
            await interaction.response.send_message(f"チーム{team_key}は見つかりません。", ephemeral=True)
            return
        await interaction.response.send_message(
            f"チーム{team['number']}「{self.team_name.value.strip()}」のステータスを選んでください。",
            view=OTPStatusSelectView(team_key, self.team_name.value.strip()),
            ephemeral=True,
        )


class OTPAdminControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="チーム情報を更新", style=discord.ButtonStyle.success, custom_id="otp_admin_team_update")
    async def update_team(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("この操作は運営のみ実行できます。", ephemeral=True)
            return
        await interaction.response.send_modal(OTPTeamManagementModal())


async def ensure_otp_admin_control(guild: discord.Guild):
    """チーム承認用チャンネルに管理ボタンを1つだけ維持する。"""
    channel = guild.get_channel(OTP_TEAM_APPROVAL_CHANNEL_ID)
    if not channel:
        return
    message_id = bot_state.get("otp_admin_control_message_id")
    message_channel_id = bot_state.get("otp_admin_control_channel_id", OTP_ADMIN_CHANNEL_ID)
    if message_id and message_channel_id == OTP_TEAM_APPROVAL_CHANNEL_ID:
        try:
            await channel.fetch_message(message_id)
            return
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass
    if message_id and message_channel_id != OTP_TEAM_APPROVAL_CHANNEL_ID:
        old_channel = guild.get_channel(message_channel_id)
        if old_channel:
            try:
                old_message = await old_channel.fetch_message(message_id)
                await old_message.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
    message = await channel.send("【OTP杯・運営操作】\nチーム名とステータスを更新します。", view=OTPAdminControlView())
    bot_state["otp_admin_control_message_id"] = message.id
    bot_state["otp_admin_control_channel_id"] = channel.id
    save_bot_state(bot_state)


async def create_otp_team_from_form(payload: dict):
    category = bot.get_channel(OTP_CATEGORY_ID)
    admin_channel = bot.get_channel(OTP_ADMIN_CHANNEL_ID)
    summary_channel = bot.get_channel(OTP_TEAM_SUMMARY_CHANNEL_ID)
    if not isinstance(category, discord.CategoryChannel) or not admin_channel or not summary_channel:
        raise RuntimeError("OTP杯のカテゴリーまたは運営チャンネルが見つかりません。")
    guild = category.guild
    teams = get_otp_teams()
    number = max((int(t.get("number", 0)) for t in teams.values()), default=0) + 1
    team_key = str(number)
    team_channel = await guild.create_text_channel(f"☑️チーム{number}", category=category, reason="OTP杯フォーム申請")
    leader = payload.get("leader_name", "チームリーダー")
    members = payload.get("member_names", ["メンバー1", "メンバー2", "メンバー3"])
    member_circles = payload.get("member_circles", ["", "", ""])
    team = {
        "number": number, "channel_id": team_channel.id, "team_name": "", "status": "未承認 ☑️",
        "leader_name": leader, "leader_circle": payload.get("leader_circle", ""), "x_id": payload.get("x_id", ""),
        "member_names": members, "member_circles": member_circles,
        "enthusiasm": payload.get("enthusiasm", ""), "players": {},
    }
    teams[team_key] = team
    intro_message = await team_channel.send(otp_team_intro(team), view=OTPTeamInputView(team_key))
    team["intro_message_id"] = intro_message.id
    central_summary = await summary_channel.send(otp_team_summary(team))
    team["summary_message_id"] = central_summary.id
    invite = await team_channel.create_invite(max_age=24 * 60 * 60, max_uses=0, unique=True, reason="OTP杯申請チームへの案内")
    dm_copy = (
        "大会参加申請ありがとうございます！\n"
        "Discordサーバーへご案内しますので、以下の招待リンクから参加をお願いします。\n\n"
        "この招待リンクは24時間で無効になります。お早めにご参加ください。\n\n"
        f"サーバー参加後は「☑️チーム{number}」チャンネルに、申請から大会参加までの流れを記載しています。\n\n"
        "大会までよろしくお願いします！\n\n"
        f"招待リンク：\n{invite.url}"
    )
    await admin_channel.send(
        f"【大会申請】\n@{payload.get('x_id', '未入力')} から申請が届きました。\n\n"
        "次のメッセージだけをコピーして、XのDMで送ってください。"
    )
    await admin_channel.send(dm_copy)
    save_otp_teams()
    return team


OTP_DEMO_STAGES = [
    "マサバ海峡大橋", "スメーシーワールド", "クサヤ温泉", "コンブトラック",
    "タカアシ経済特区", "ネギトロ炭鉱", "デカライン高架下",
]

OTP_DEMO_TEAM_STATUSES = {
    "pending": "未承認 ☑️",
    "approved": "承認 ✅",
    "withdrawn": "棄権 ❌",
    "needs_review": "再確認 ☑️",
}


def get_otp_tournaments():
    return bot_state.setdefault("otp_tournaments", {})


def save_otp_tournaments():
    save_bot_state(bot_state)


def normalize_otp_application_id(value: str) -> tuple[str, int | None]:
    text = str(value or "").strip().upper()
    match = re.search(r"(\d+)", text)
    if not match:
        return text, None
    number = int(match.group(1))
    return f"OTP-{number:03d}", number


def otp_demo_team_key(tournament_id: str, application_id: str) -> str:
    normalized, _ = normalize_otp_application_id(application_id)
    return f"{tournament_id}:{normalized}"


def parse_optional_float(raw):
    text = str(raw or "").strip().replace("%", "")
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    return int(value) if value.is_integer() else value


def parse_otp_demo_bulk_text(text: str) -> tuple[dict | None, list[str]]:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    errors = []
    application_id = None
    team_name = None
    table_start = None
    for index, line in enumerate(lines):
        if line.startswith("申請番号"):
            application_id = line.split("：", 1)[-1].split(":", 1)[-1].strip()
        elif line.startswith("チーム名"):
            team_name = line.split("：", 1)[-1].split(":", 1)[-1].strip()
        elif "\t" in line:
            table_start = index
            break
    if not application_id:
        errors.append("申請番号が見つかりません。")
    if not team_name:
        errors.append("チーム名が見つかりません。")
    if table_start is None:
        errors.append("タブ区切りのメンバー表が見つかりません。")
    if errors:
        return None, errors

    rows = []
    for line_no, line in enumerate(lines[table_start:], start=table_start + 1):
        cols = [col.strip() for col in line.split("\t")]
        if cols and cols[0] in ("役割", "ロール"):
            continue
        if len(cols) != 9:
            errors.append(f"{line_no}行目: 列数が9ではありません。")
            continue
        role, player_name, circle, discord_id, xp, weapon1, weapon2, weapon3, top_rate = cols
        rows.append({
            "role": role,
            "player_name": player_name,
            "circle": circle,
            "discord_id": discord_id,
            "xp": parse_optional_float(xp),
            "weapons": [weapon1, weapon2, weapon3],
            "top_weapon_rate": parse_optional_float(top_rate),
            "line_no": line_no,
        })
    normalized, number = normalize_otp_application_id(application_id)
    return {"application_id": normalized, "application_number": number, "team_name": team_name, "members": rows}, errors


async def validate_otp_demo_team(guild: discord.Guild, tournament: dict, team_data: dict, existing_key: str | None = None) -> list[str]:
    errors = []
    members = team_data.get("members", [])
    leader_count = sum(m["role"] == "リーダー" for m in members)
    if len(members) < 1:
        errors.append("メンバーが0人です。")
    if len(members) > int(tournament.get("max_members", 4)):
        errors.append("メンバーが5人以上です。")
    if leader_count != 1:
        errors.append("リーダー行は必ず1行だけ必要です。")
    seen_ids = set()
    all_team_ids = {}
    for key, team in tournament.get("teams", {}).items():
        if key == existing_key:
            continue
        for member in team.get("members", []):
            did = str(member.get("discord_id") or "")
            if did:
                all_team_ids[did] = team.get("team_name", key)
    for member in members:
        prefix = f"{member.get('line_no', '?')}行目"
        did = str(member.get("discord_id") or "").strip()
        if not re.fullmatch(r"\d{15,25}", did):
            errors.append(f"{prefix}: Discord IDの形式が不正です。")
            continue
        if did in seen_ids:
            errors.append(f"{prefix}: 同じチーム内でDiscord IDが重複しています。")
        seen_ids.add(did)
        if did in all_team_ids:
            errors.append(f"{prefix}: {all_team_ids[did]} と二重所属です。")
        member_obj = guild.get_member(int(did))
        if member_obj is None:
            try:
                member_obj = await guild.fetch_member(int(did))
            except Exception:
                member_obj = None
        if member_obj is None:
            errors.append(f"{prefix}: 対象サーバーにいないユーザーです。")
        elif member_obj.bot:
            errors.append(f"{prefix}: Botアカウントは登録できません。")
        xp = member.get("xp")
        rate = member.get("top_weapon_rate")
        if xp is not None and xp < 0:
            errors.append(f"{prefix}: XPは0以上の数値にしてください。")
        if rate is not None and not 0 <= rate <= 100:
            errors.append(f"{prefix}: 使用率は0〜100の数値にしてください。")
    if tournament.get("kind") == "main" and len(members) != 4:
        errors.append("本大会設定では4人登録が必要です。")
    return errors


def otp_demo_corrected_xp(member: dict):
    xp = member.get("xp")
    rate = member.get("top_weapon_rate")
    if xp is None or rate is None:
        return None
    return xp - rate


def otp_demo_team_average(team: dict):
    corrected = [otp_demo_corrected_xp(m) for m in team.get("members", [])]
    if not corrected or any(v is None for v in corrected):
        return None
    return math.floor(sum(corrected) / len(corrected))


def otp_demo_team_ready(tournament: dict, team: dict) -> tuple[bool, str]:
    if team.get("status") != "approved":
        return False, OTP_DEMO_TEAM_STATUSES.get(team.get("status"), "未承認")
    members = team.get("members", [])
    if not (int(tournament.get("min_members", 1)) <= len(members) <= int(tournament.get("max_members", 4))):
        return False, "人数条件を満たしていません"
    average = otp_demo_team_average(team)
    if average is None:
        return False, "XPまたは使用率が未入力です"
    if average > int(tournament.get("xp_limit", 2700)):
        return False, f"補正XP平均が{tournament.get('xp_limit', 2700)}を超えています"
    return True, "参加可能"


def otp_demo_public_team_text(team: dict, tournament: dict) -> str:
    average = otp_demo_team_average(team)
    avg_text = "計算待ち" if average is None else f"{average}（デモ・登録{len(team.get('members', []))}人の平均）"
    lines = [
        f"【{team.get('application_id')}｜{team.get('team_name')}】",
        f"{OTP_DEMO_TEAM_STATUSES.get(team.get('status'), team.get('status'))}｜人数 {len(team.get('members', []))}｜補正XP平均 {avg_text}",
        "",
    ]
    for member in team.get("members", []):
        corrected = otp_demo_corrected_xp(member)
        corrected_text = "計算待ち" if corrected is None else corrected
        weapons = "、".join(w or "未入力" for w in member.get("weapons", []))
        lines.append(
            f"{member.get('role')}｜{member.get('player_name') or '未入力'}（{member.get('circle') or '所属未入力'}）\n"
            f"XP {member.get('xp') if member.get('xp') is not None else '未入力'}｜{weapons}｜"
            f"1位使用率 {member.get('top_weapon_rate') if member.get('top_weapon_rate') is not None else '未入力'}%｜補正XP {corrected_text}"
        )
    ready, reason = otp_demo_team_ready(tournament, team)
    lines.extend(["", f"参加判定：{'OK' if ready else reason}"])
    return "\n".join(lines)


def calculate_otp_demo_blocks(team_keys: list[str]) -> list[list[str]] | None:
    n = len(team_keys)
    best = None
    for four_count in range(n // 4, -1, -1):
        rest = n - four_count * 4
        if rest % 3 == 0:
            three_count = rest // 3
            best = [4] * four_count + [3] * three_count
            break
    if not best:
        return None
    shuffled = team_keys[:]
    random.shuffle(shuffled)
    blocks = []
    offset = 0
    for size in best:
        blocks.append(shuffled[offset:offset + size])
        offset += size
    return blocks


def make_round_robin_matches(blocks: list[list[str]]) -> dict:
    matches = {}
    order = []
    match_no = 1
    for block_index, teams in enumerate(blocks, start=1):
        for a, b in combinations(teams, 2):
            match_id = f"Q{match_no:03d}"
            matches[match_id] = {
                "id": match_id, "phase": "qualifier", "block": block_index,
                "teams": [a, b], "best_of": 3, "target_wins": 2,
                "status": "waiting", "battle_index": 1, "wins": {a: 0, b: 0},
                "battles": [], "stage_pool": OTP_DEMO_STAGES[:],
                "current_stage": None, "reports": {}, "report_generation": 1,
                "channel_id": None,
            }
            order.append(match_id)
            match_no += 1
    return {"matches": matches, "order": order}


def otp_demo_available_matches(tournament: dict) -> list[dict]:
    active_teams = set()
    for match in tournament.get("matches", {}).values():
        if match.get("status") in ("active", "disputed", "hold", "stage_select"):
            active_teams.update(match.get("teams", []))
    result = []
    for match_id in tournament.get("match_order", []):
        match = tournament["matches"][match_id]
        if match.get("status") != "waiting":
            continue
        if any(team in active_teams for team in match.get("teams", [])):
            continue
        result.append(match)
    return result


def otp_demo_pick_stage(match: dict) -> str:
    pool = match.setdefault("stage_pool", OTP_DEMO_STAGES[:])
    if not pool:
        pool = OTP_DEMO_STAGES[:]
        match["stage_pool"] = pool
    stage = random.choice(pool)
    pool.remove(stage)
    match["current_stage"] = stage
    return stage


async def otp_demo_start_waiting_matches(guild: discord.Guild, tournament: dict):
    if tournament.get("paused") or tournament.get("status") != "running":
        return
    active_teams = set()
    for existing in tournament.get("matches", {}).values():
        if existing.get("status") in ("active", "disputed", "hold", "stage_select"):
            active_teams.update(existing.get("teams", []))
    for match in otp_demo_available_matches(tournament):
        if any(team in active_teams for team in match.get("teams", [])):
            continue
        match["status"] = "active"
        active_teams.update(match.get("teams", []))
        if not match.get("current_stage"):
            otp_demo_pick_stage(match)
        await otp_demo_announce_match(guild, tournament, match)
    save_otp_tournaments()


def otp_demo_match_text(tournament: dict, match: dict) -> str:
    return otp_demo_match_report_text(tournament, match)


def otp_demo_match_guide_text(tournament: dict, match: dict) -> str:
    teams = tournament.get("teams", {})
    a, b = match["teams"]
    if tournament.get("solo_test_mode"):
        visibility = (
            "このチャンネルは1人テスト用なので、運営とBotだけで確認します。\n"
            "通常版では、両チームの登録メンバー、運営、Botだけが見られる非公開チャンネルにします。"
        )
        report_rule = (
            "この1人テストでは、運営が報告ボタンを押して進行します。\n"
            "通常版では、各チームの登録リーダーだけが報告ボタンを押せます。"
        )
    else:
        visibility = "このチャンネルは、両チームの登録メンバー、運営、Botだけが見られる対戦部屋です。"
        report_rule = "各チームの登録リーダーだけが報告ボタンを押せます。両チームの報告が一致したときだけ結果が確定します。"
    return (
        f"# OTP杯 対戦部屋\n"
        f"## {teams[a]['team_name']} vs {teams[b]['team_name']}\n\n"
        f"{visibility}\n\n"
        "試合の連絡、部屋立て、確認はこのチャンネルで行ってください。\n"
        "勝敗報告は、下に出る「試合報告」メッセージのボタンから行います。\n\n"
        f"{report_rule}\n\n"
        "回線落ちなど通常の勝敗報告だけで扱えない問題が起きた場合は、運営が手動で保留します。"
    )


def otp_demo_match_report_text(tournament: dict, match: dict) -> str:
    teams = tournament.get("teams", {})
    a, b = match["teams"]
    score = f"{match['wins'].get(a, 0)}-{match['wins'].get(b, 0)}"
    team_a = teams[a]["team_name"]
    team_b = teams[b]["team_name"]
    if tournament.get("solo_test_mode"):
        operation_text = (
            "【1人テストモード】\n"
            "このチャンネルは運営とBotだけで確認する仮部屋です。\n"
            "通常版では、このテキストチャンネルは各チームの登録メンバー、運営、Botだけが見られる想定です。\n"
            "通常版では、試合報告ボタンは各チームの登録リーダーのみ押せます。\n"
            "通常版では、両チームの報告が同じ勝者を示したときだけ結果が確定します。\n"
            "この1人テストではDiscord IDなしの仮チームなので、運営が下の勝者ボタンで代わりに進めます。"
        )
    else:
        operation_text = (
            "1本終わったら、各チームの登録リーダーが下の勝者ボタンを押してください。\n"
            "片側だけの報告では進みません。両チームの報告が一致したときだけ結果が確定します。\n"
            "報告が食い違った場合は再入力になります。再び食い違った場合は運営裁定待ちになります。"
        )
    return (
        f"# 試合報告 {match['id']}\n"
        f"## {match.get('battle_index', 1)}本目\n\n"
        f"{team_a} vs {team_b}\n\n"
        f"形式：{'BO5' if match.get('best_of') == 5 else 'BO3'}\n"
        f"スコア：{score}\n"
        f"ステージ：**{match.get('current_stage') or '抽選待ち'}**\n\n"
        f"下のボタンで、この1本の勝者を報告してください。\n\n"
        f"{operation_text}"
    )


def otp_demo_match_report_embed(tournament: dict, match: dict) -> discord.Embed:
    teams = tournament.get("teams", {})
    a, b = match["teams"]
    team_a = teams[a]["team_name"]
    team_b = teams[b]["team_name"]
    score = f"{match['wins'].get(a, 0)} - {match['wins'].get(b, 0)}"
    phase_label = "予選" if match.get("phase") == "qualifier" else ("上位トーナメント" if match.get("phase") == "upper" else "下位トーナメント")
    title = f"{phase_label}・{match['id']}・{match.get('battle_index', 1)}本目"
    embed = discord.Embed(title=title, color=0x5865F2)
    embed.add_field(name="対戦カード", value=f"**{team_a}**  vs  **{team_b}**", inline=False)
    embed.add_field(name="現在スコア", value=f"**{score}**", inline=True)
    embed.add_field(name="形式", value="BO5" if match.get("best_of") == 5 else "BO3", inline=True)
    embed.add_field(name="指定ステージ", value=f"**{match.get('current_stage') or '抽選待ち'}**", inline=False)
    if tournament.get("solo_test_mode"):
        note = (
            "1人テストでは運営が勝者ボタンで代行入力します。\n"
            "通常版では各チームリーダーだけが押せます。"
        )
    else:
        note = (
            "各チームの登録リーダーが、この1本の勝者ボタンを押してください。\n"
            "両チームの報告が一致したときだけ結果が確定します。"
        )
    embed.add_field(name="報告方法", value=note, inline=False)
    embed.set_footer(text="回線落ち・再試合など通常報告で扱えない場合は運営が保留します")
    return embed


class OTPMatchReportView(discord.ui.View):
    def __init__(self, tournament_id: str, match_id: str, generation: int, team_labels: list[str]):
        super().__init__(timeout=None)
        self.tournament_id = tournament_id
        self.match_id = match_id
        self.generation = int(generation)
        for index, label in enumerate(team_labels):
            button = discord.ui.Button(
                label=f"{label} 勝ち",
                style=discord.ButtonStyle.primary,
                custom_id=f"otp_match_win:{tournament_id}:{match_id}:{self.generation}:{index}",
            )
            button.callback = self.make_callback(index)
            self.add_item(button)

    def make_callback(self, winner_index: int):
        async def callback(interaction: discord.Interaction):
            tournaments = get_otp_tournaments()
            tournament = tournaments.get(self.tournament_id)
            if not tournament:
                await interaction.response.send_message("大会が見つかりません。", ephemeral=True)
                return
            match = tournament.get("matches", {}).get(self.match_id)
            if not match or match.get("status") not in ("active", "disputed", "hold"):
                await interaction.response.send_message("この対戦は現在報告できません。", ephemeral=True)
                return
            if int(match.get("report_generation", 1)) != self.generation:
                await interaction.response.send_message("このボタンは古い本数のものです。最新の対戦メッセージから操作してください。", ephemeral=True)
                return
            if winner_index >= len(match.get("teams", [])):
                await interaction.response.send_message("勝者情報が見つかりません。", ephemeral=True)
                return

            winner_key = match["teams"][winner_index]
            teams = tournament.get("teams", {})
            winner_app = teams[winner_key].get("application_id", "不明")

            if tournament.get("solo_test_mode"):
                if not otp_demo_is_operator(interaction.user, tournament):
                    await interaction.response.send_message("1人テストでは運営だけが結果を進められます。", ephemeral=True)
                    return
                otp_demo_record_battle_result(tournament, match, winner_key, "solo_test_operator_button", interaction.user.id)
                maybe_finish_qualifiers_and_build_brackets(tournament)
                save_otp_tournaments()
                for child in self.children:
                    child.disabled = True
                await interaction.response.edit_message(view=self)
                await interaction.followup.send(
                    f"{self.match_id} {winner_app} 勝ちで1人テスト確定しました。\n"
                    "通常版では、両チームリーダーの報告一致または運営裁定で確定します。"
                )
                await otp_demo_after_match_progress(interaction.guild, tournament, match)
                return

            reporter_team = None
            for team_key in match["teams"]:
                if otp_demo_get_leader_id(teams[team_key]) == str(interaction.user.id):
                    reporter_team = team_key
                    break
            if reporter_team is None:
                await interaction.response.send_message("この対戦の登録リーダーだけが報告できます。", ephemeral=True)
                return
            if match.get("status") == "hold":
                await interaction.response.send_message("この対戦は保留中です。参加者入力では解除できません。", ephemeral=True)
                return

            reports = match.setdefault("reports", {})
            reports[reporter_team] = {
                "winner": winner_key,
                "reporter_id": str(interaction.user.id),
                "generation": match.get("report_generation", 1),
                "reported_at": time.time(),
            }
            if len(reports) < 2:
                save_otp_tournaments()
                await interaction.response.send_message("報告を受け付けました。もう一方のリーダー報告を待っています。", ephemeral=True)
                return

            winners = {r["winner"] for r in reports.values()}
            if len(winners) == 1:
                otp_demo_record_battle_result(tournament, match, winner_key, "leaders_button", interaction.user.id)
                maybe_finish_qualifiers_and_build_brackets(tournament)
                save_otp_tournaments()
                for child in self.children:
                    child.disabled = True
                await interaction.response.edit_message(view=self)
                await interaction.followup.send(f"{self.match_id} {winner_app} 勝ちで確定しました。")
                await otp_demo_after_match_progress(interaction.guild, tournament, match)
                return

            mismatch_count = match.get("mismatch_count", 0) + 1
            match["mismatch_count"] = mismatch_count
            match["reports"] = {}
            match["report_generation"] = match.get("report_generation", 1) + 1
            match["status"] = "disputed" if mismatch_count < 2 else "hold"
            save_otp_tournaments()
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(view=self)
            if mismatch_count < 2:
                await interaction.followup.send(f"{self.match_id} の報告が不一致でした。最新の対戦メッセージで双方が再入力してください。")
                await otp_demo_announce_match(interaction.guild, tournament, match)
            else:
                await interaction.followup.send(f"{self.match_id} は再不一致のため運営裁定待ちです。")
        return callback


class OTPMatchCheckinView(discord.ui.View):
    def __init__(self, tournament_id: str, match_id: str, team_labels: list[str]):
        super().__init__(timeout=None)
        self.tournament_id = tournament_id
        self.match_id = match_id
        for index, label in enumerate(team_labels):
            button = discord.ui.Button(
                label=f"{label} 準備OK",
                style=discord.ButtonStyle.success,
                custom_id=f"otp_match_checkin:{tournament_id}:{match_id}:{index}",
            )
            button.callback = self.make_callback(index)
            self.add_item(button)

    def make_callback(self, team_index: int):
        async def callback(interaction: discord.Interaction):
            tournament = get_otp_tournaments().get(self.tournament_id)
            if not tournament:
                await interaction.response.send_message("大会が見つかりません。", ephemeral=True)
                return
            match = tournament.get("matches", {}).get(self.match_id)
            if not match or match.get("status") not in ("active", "disputed"):
                await interaction.response.send_message("この対戦は準備確認できません。", ephemeral=True)
                return
            if team_index >= len(match.get("teams", [])):
                await interaction.response.send_message("チーム情報が見つかりません。", ephemeral=True)
                return
            team_key = match["teams"][team_index]
            if tournament.get("solo_test_mode"):
                if not otp_demo_is_operator(interaction.user, tournament):
                    await interaction.response.send_message("1人テストでは運営だけが準備確認できます。", ephemeral=True)
                    return
            elif otp_demo_get_leader_id(tournament["teams"][team_key]) != str(interaction.user.id):
                await interaction.response.send_message("このチームの登録リーダーだけが準備OKできます。", ephemeral=True)
                return

            checkins = match.setdefault("checkins", {})
            checkins[team_key] = {"user_id": str(interaction.user.id), "checked_at": time.time()}
            save_otp_tournaments()
            if len(checkins) < len(match.get("teams", [])):
                await interaction.response.edit_message(content=otp_demo_checkin_text(tournament, match), view=self)
                await interaction.followup.send("準備OKを受け付けました。相手チームの準備を待っています。", ephemeral=True)
                return

            await interaction.response.defer(ephemeral=True)
            await otp_demo_delete_checkin_message(interaction.guild, tournament, match)
            channel = await otp_demo_create_match_channel(interaction.guild, tournament, match)
            if not channel:
                await interaction.followup.send("対戦チャンネルの作成に失敗しました。Botのチャンネル管理権限を確認してください。", ephemeral=True)
                return
            guide_message = await channel.send(otp_demo_match_guide_text(tournament, match))
            match["guide_message_id"] = guide_message.id
            await otp_demo_send_match_report_message(channel, tournament, match)
            save_otp_tournaments()
            await interaction.followup.send(f"両チームの準備が揃いました。{channel.mention} を作成しました。", ephemeral=True)
        return callback


async def otp_demo_delete_match_report_message(guild: discord.Guild, match: dict):
    channel = guild.get_channel(match.get("channel_id"))
    message_id = match.get("report_message_id")
    if channel and message_id:
        try:
            message = await channel.fetch_message(message_id)
            await message.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass
    match.pop("report_message_id", None)


def otp_demo_build_match_overwrites(guild: discord.Guild, tournament: dict, match: dict):
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
    }
    owner = guild.get_member(OWNER_ID)
    if owner:
        overwrites[owner] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
    role_id = tournament.get("operator_role_id")
    role = guild.get_role(int(role_id)) if role_id else None
    if role:
        overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
    if not tournament.get("solo_test_mode"):
        for team_key in match.get("teams", []):
            for member_data in tournament.get("teams", {}).get(team_key, {}).get("members", []):
                discord_id = str(member_data.get("discord_id") or "")
                if not discord_id.isdigit():
                    continue
                member = guild.get_member(int(discord_id))
                if member:
                    overwrites[member] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
    return overwrites


async def otp_demo_create_match_channel(guild: discord.Guild, tournament: dict, match: dict):
    if match.get("channel_id"):
        channel = guild.get_channel(match.get("channel_id"))
        if channel:
            return channel
    category = guild.get_channel(tournament.get("category_id"))
    teams = tournament.get("teams", {})
    a, b = match["teams"]
    base_name = f"{teams[a]['team_name']}-vs-{teams[b]['team_name']}"
    safe_name = re.sub(r"[^0-9A-Za-zぁ-んァ-ン一-龥ー-]+", "-", base_name).strip("-").lower()[:48] or match["id"].lower()
    try:
        channel = await guild.create_text_channel(
            name=f"otp-{match['id'].lower()}-{safe_name}",
            category=category if isinstance(category, discord.CategoryChannel) else None,
            overwrites=otp_demo_build_match_overwrites(guild, tournament, match),
            reason="OTP杯デモ対戦チャンネル",
        )
        match["channel_id"] = channel.id
        return channel
    except (discord.Forbidden, discord.HTTPException):
        return None


async def otp_demo_delete_checkin_message(guild: discord.Guild, tournament: dict, match: dict):
    channel = guild.get_channel(tournament.get("progress_channel_id")) or guild.get_channel(tournament.get("admin_channel_id"))
    message_id = match.get("checkin_message_id")
    if channel and message_id:
        try:
            message = await channel.fetch_message(message_id)
            await message.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass
    match.pop("checkin_message_id", None)


async def otp_demo_delete_match_channel(guild: discord.Guild, match: dict):
    channel = guild.get_channel(match.get("channel_id"))
    if channel:
        try:
            await channel.delete(reason="OTP杯デモ対戦終了")
        except (discord.Forbidden, discord.HTTPException):
            match["cleanup_failed"] = True
            return
    match["channel_deleted_at"] = time.time()
    match.pop("channel_id", None)
    match.pop("guide_message_id", None)
    match.pop("report_message_id", None)


async def otp_demo_delayed_delete_match_channel(guild: discord.Guild, tournament: dict, match_id: str, delay_seconds: int = 120):
    await asyncio.sleep(delay_seconds)
    tournament = get_otp_tournaments().get(tournament.get("id"))
    if not tournament:
        return
    match = tournament.get("matches", {}).get(match_id)
    if not match or match.get("status") != "done":
        return
    await otp_demo_delete_match_channel(guild, match)
    save_otp_tournaments()


async def otp_demo_post_match_finish_message(guild: discord.Guild, tournament: dict, match: dict):
    channel = guild.get_channel(match.get("channel_id"))
    if not channel:
        return
    teams = tournament.get("teams", {})
    winner = teams.get(match.get("winner"), {}).get("team_name", "不明")
    a, b = match["teams"]
    score = f"{match['wins'].get(a, 0)} - {match['wins'].get(b, 0)}"
    await channel.send(
        "# 対戦終了\n\n"
        f"勝者：**{winner}**\n"
        f"最終スコア：**{score}**\n\n"
        "結果は保存されました。\n"
        "このチャンネルは2分後に削除されます。"
    )
    asyncio.create_task(otp_demo_delayed_delete_match_channel(guild, tournament, match["id"], 120))


async def otp_demo_send_match_report_message(channel: discord.abc.Messageable, tournament: dict, match: dict):
    teams = tournament.get("teams", {})
    labels = [teams[key]["team_name"] for key in match.get("teams", [])]
    view = OTPMatchReportView(tournament["id"], match["id"], match.get("report_generation", 1), labels)
    message = await channel.send(embed=otp_demo_match_report_embed(tournament, match), view=view)
    match["report_message_id"] = message.id
    return message


def otp_demo_checkin_text(tournament: dict, match: dict) -> str:
    teams = tournament.get("teams", {})
    a, b = match["teams"]
    checkins = match.get("checkins", {})
    a_mark = "OK" if a in checkins else "待ち"
    b_mark = "OK" if b in checkins else "待ち"
    if tournament.get("solo_test_mode"):
        note = "1人テストでは運営が両チーム分の準備OKを押します。"
    else:
        note = "各チームの登録リーダーが準備OKを押してください。両チームが揃うと対戦チャンネルを作成します。"
    return (
        f"# 対戦準備 {match['id']}\n"
        f"{teams[a]['team_name']} vs {teams[b]['team_name']}\n\n"
        f"{teams[a]['team_name']}：{a_mark}\n"
        f"{teams[b]['team_name']}：{b_mark}\n\n"
        f"{note}\n"
        "対戦チャンネルは準備OKが揃ってから表示されます。"
    )


async def otp_demo_send_checkin_message(channel: discord.abc.Messageable, tournament: dict, match: dict):
    teams = tournament.get("teams", {})
    labels = [teams[key]["team_name"] for key in match.get("teams", [])]
    view = OTPMatchCheckinView(tournament["id"], match["id"], labels)
    message = await channel.send(otp_demo_checkin_text(tournament, match), view=view)
    match["checkin_message_id"] = message.id
    return message


async def otp_demo_after_match_progress(guild: discord.Guild, tournament: dict, match: dict):
    if match.get("status") == "done":
        await otp_demo_delete_match_report_message(guild, match)
        await otp_demo_post_match_finish_message(guild, tournament, match)
    else:
        await otp_demo_delete_match_report_message(guild, match)
        await otp_demo_announce_match(guild, tournament, match)
    await otp_demo_start_waiting_matches(guild, tournament)
    save_otp_tournaments()


async def otp_demo_delete_all_match_channels(guild: discord.Guild, tournament: dict):
    for match in tournament.get("matches", {}).values():
        await otp_demo_delete_match_channel(guild, match)


def build_otp_progress_placeholder_file(tournament: dict) -> discord.File:
    width, height = 1200, 675
    image = Image.new("RGB", (width, height), (18, 20, 28))
    draw = ImageDraw.Draw(image)
    try:
        font_title = ImageFont.truetype("/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc", 52)
        font_body = ImageFont.truetype("/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc", 32)
    except Exception:
        font_title = ImageFont.load_default()
        font_body = ImageFont.load_default()
    draw.rectangle((0, 0, width, 92), fill=(37, 99, 235))
    draw.text((48, 22), "OTP杯デモ 進行画像", fill=(255, 255, 255), font=font_title)
    lines = [
        f"大会ID: {tournament.get('id')}",
        "ここに予選表・上位トーナメント・下位トーナメントを表示します。",
        "現在は画像差し替え機能の確認用プレースホルダーです。",
        "本実装ではこの投稿を編集し、最新の進行画像へ更新します。",
    ]
    y = 150
    for line in lines:
        draw.text((64, y), line, fill=(238, 242, 255), font=font_body)
        y += 58
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return discord.File(buffer, filename=f"otp_progress_{tournament.get('id', 'demo')}.png")


async def otp_demo_post_progress_placeholder(guild: discord.Guild, tournament: dict):
    channel = guild.get_channel(tournament.get("progress_channel_id"))
    if not channel:
        return
    text = (
        f"【OTP杯デモ進行｜{tournament.get('id')}】\n"
        "ここに予選表・上位トーナメント・下位トーナメントの画像を貼ります。\n"
        "画像生成アプリ側の実装後、この投稿を編集して最新画像に差し替える予定です。"
    )
    message_id = tournament.get("progress_placeholder_message_id")
    if message_id:
        try:
            message = await channel.fetch_message(message_id)
            await message.edit(content=text)
            return
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass
    try:
        message = await channel.send(text, file=build_otp_progress_placeholder_file(tournament))
        tournament["progress_placeholder_message_id"] = message.id
    except (discord.Forbidden, discord.HTTPException):
        pass


async def otp_demo_announce_match(guild: discord.Guild, tournament: dict, match: dict):
    channel = guild.get_channel(tournament.get("progress_channel_id")) or guild.get_channel(tournament.get("admin_channel_id"))
    if not channel:
        return
    await otp_demo_post_progress_placeholder(guild, tournament)

    match_channel = guild.get_channel(match.get("channel_id")) if match.get("channel_id") else None
    if not match_channel:
        if not match.get("checkin_message_id"):
            await otp_demo_send_checkin_message(channel, tournament, match)
        return

    if match_channel:
        if not match.get("guide_message_id"):
            guide_message = await match_channel.send(otp_demo_match_guide_text(tournament, match))
            match["guide_message_id"] = guide_message.id
        await otp_demo_send_match_report_message(match_channel, tournament, match)


def otp_demo_find_team_by_application(tournament: dict, application_id: str) -> str | None:
    normalized, _ = normalize_otp_application_id(application_id)
    for key, team in tournament.get("teams", {}).items():
        if team.get("application_id") == normalized:
            return key
    return None


def otp_demo_get_leader_id(team: dict) -> str | None:
    for member in team.get("members", []):
        if member.get("role") == "リーダー":
            return str(member.get("discord_id"))
    return None


def rank_otp_demo_block(tournament: dict, block_index: int) -> list[str]:
    block_teams = tournament.get("blocks", [])[block_index - 1]
    stats = {team: {"match_wins": 0, "battle_wins": 0, "battle_losses": 0, "order": tournament["teams"][team].get("application_number") or 999999} for team in block_teams}
    direct = {}
    for match in tournament.get("matches", {}).values():
        if match.get("block") != block_index or match.get("status") != "done":
            continue
        a, b = match["teams"]
        aw = match["wins"].get(a, 0)
        bw = match["wins"].get(b, 0)
        stats[a]["battle_wins"] += aw
        stats[a]["battle_losses"] += bw
        stats[b]["battle_wins"] += bw
        stats[b]["battle_losses"] += aw
        winner = a if aw > bw else b
        stats[winner]["match_wins"] += 1
        direct[frozenset((a, b))] = winner

    def base(team):
        s = stats[team]
        return (-s["match_wins"], -s["battle_wins"], s["battle_losses"], s["order"])

    ranked = sorted(block_teams, key=base)
    changed = True
    while changed:
        changed = False
        for i in range(len(ranked) - 1):
            a, b = ranked[i], ranked[i + 1]
            sa, sb = stats[a], stats[b]
            if (sa["match_wins"], sa["battle_wins"], sa["battle_losses"]) == (sb["match_wins"], sb["battle_wins"], sb["battle_losses"]):
                tied = [t for t in block_teams if (stats[t]["match_wins"], stats[t]["battle_wins"], stats[t]["battle_losses"]) == (sa["match_wins"], sa["battle_wins"], sa["battle_losses"])]
                if len(tied) == 2 and direct.get(frozenset((a, b))) == b:
                    ranked[i], ranked[i + 1] = b, a
                    changed = True
    return ranked


def build_single_elim_bracket(tournament: dict, team_keys: list[str], bracket_name: str) -> tuple[dict, list[str]]:
    if len(team_keys) <= 1:
        return {}, []
    size = 1
    while size < len(team_keys):
        size *= 2
    byes = set(random.sample(team_keys, size - len(team_keys))) if size > len(team_keys) else set()
    slots = [None] * size
    bye_positions = list(range(size))
    random.shuffle(bye_positions)
    remaining = [t for t in team_keys if t not in byes]
    for team, pos in zip(byes, bye_positions):
        slots[pos] = team
    for team in remaining:
        for i, value in enumerate(slots):
            if value is None:
                slots[i] = team
                break
    matches = {}
    order = []
    pair_no = 1
    auto_advancers = []
    for i in range(0, size, 2):
        a, b = slots[i], slots[i + 1]
        if a and b:
            match_id = f"{bracket_name[0].upper()}{pair_no:03d}"
            matches[match_id] = {
                "id": match_id, "phase": bracket_name, "round": 1, "teams": [a, b],
                "best_of": 5 if size == 2 else 3, "target_wins": 3 if size == 2 else 2,
                "status": "waiting", "battle_index": 1, "wins": {a: 0, b: 0},
                "battles": [], "stage_pool": OTP_DEMO_STAGES[:], "current_stage": None,
                "reports": {}, "report_generation": 1, "channel_id": None,
            }
            order.append(match_id)
            pair_no += 1
        elif a or b:
            auto_advancers.append(a or b)
    tournament.setdefault("brackets", {})[bracket_name] = {
        "slots": slots, "byes": list(byes), "auto_advancers": auto_advancers, "round": 1,
        "active_team_count": len(team_keys),
    }
    return matches, order


def maybe_finish_qualifiers_and_build_brackets(tournament: dict):
    if tournament.get("phase") != "qualifier":
        return
    qualifier_matches = [m for m in tournament.get("matches", {}).values() if m.get("phase") == "qualifier"]
    if not qualifier_matches or any(m.get("status") != "done" for m in qualifier_matches):
        return
    upper = []
    lower = []
    tournament["block_rankings"] = {}
    for idx in range(1, len(tournament.get("blocks", [])) + 1):
        ranked = rank_otp_demo_block(tournament, idx)
        tournament["block_rankings"][str(idx)] = ranked
        upper.extend(ranked[:2])
        lower.extend(ranked[2:])
    new_matches = {}
    new_order = []
    upper_matches, upper_order = build_single_elim_bracket(tournament, upper, "upper")
    lower_matches, lower_order = build_single_elim_bracket(tournament, lower, "lower")
    new_matches.update(upper_matches)
    new_matches.update(lower_matches)
    new_order.extend(upper_order)
    new_order.extend(lower_order)
    tournament["matches"].update(new_matches)
    tournament["match_order"].extend(new_order)
    tournament["phase"] = "bracket" if new_matches else "done"
    tournament["status"] = "running" if new_matches else "done"


def otp_demo_record_battle_result(tournament: dict, match: dict, winner_key: str, decided_by: str, operator_id: int):
    a, b = match["teams"]
    loser_key = b if winner_key == a else a
    match["battles"].append({
        "battle": match.get("battle_index", 1),
        "stage": match.get("current_stage"),
        "winner": winner_key,
        "loser": loser_key,
        "decided_by": decided_by,
        "operator_id": str(operator_id),
        "reports": copy.deepcopy(match.get("reports", {})),
        "generation": match.get("report_generation", 1),
        "decided_at": time.time(),
    })
    match["wins"][winner_key] = match["wins"].get(winner_key, 0) + 1
    match["reports"] = {}
    match["report_generation"] = match.get("report_generation", 1) + 1
    match["current_stage"] = None
    if match["wins"][winner_key] >= match.get("target_wins", 2):
        match["status"] = "done"
        match["winner"] = winner_key
        match["finished_at"] = time.time()
    else:
        match["battle_index"] = match.get("battle_index", 1) + 1
        otp_demo_pick_stage(match)
        match["status"] = "active"


def otp_demo_summary_text(tournament: dict) -> str:
    teams = tournament.get("teams", {})
    counts = {"approved": 0, "pending": 0, "needs_review": 0, "withdrawn": 0}
    ready_count = 0
    for team in teams.values():
        counts[team.get("status", "pending")] = counts.get(team.get("status", "pending"), 0) + 1
        ready, _ = otp_demo_team_ready(tournament, team)
        if ready:
            ready_count += 1
    lines = [
        f"【OTP杯デモ状況｜{tournament.get('id')}】",
        f"状態：{tournament.get('status')}｜フェーズ：{tournament.get('phase', 'setup')}｜一時停止：{'はい' if tournament.get('paused') else 'いいえ'}",
        f"登録チーム：{len(teams)}｜登録人数：{sum(len(t.get('members', [])) for t in teams.values())}｜参加可能：{ready_count}",
        f"承認 {counts.get('approved', 0)}｜入力/確認待ち {counts.get('pending', 0) + counts.get('needs_review', 0)}｜棄権 {counts.get('withdrawn', 0)}",
        "",
    ]
    for key, team in sorted(teams.items(), key=lambda item: item[1].get("application_number") or 999999):
        ready, reason = otp_demo_team_ready(tournament, team)
        avg = otp_demo_team_average(team)
        lines.append(f"{team.get('application_id')} {team.get('team_name')}｜{OTP_DEMO_TEAM_STATUSES.get(team.get('status'), team.get('status'))}｜{len(team.get('members', []))}人｜平均 {avg if avg is not None else '計算待ち'}｜{'OK' if ready else reason}")
    active = [m for m in tournament.get("matches", {}).values() if m.get("status") in ("active", "disputed", "hold")]
    if active:
        lines.extend(["", "進行中/対応待ち"])
        for match in active:
            a, b = match["teams"]
            lines.append(f"{match['id']} {teams[a]['team_name']} vs {teams[b]['team_name']}｜{match['status']}｜{match['wins'].get(a, 0)}-{match['wins'].get(b, 0)}")
    return "\n".join(lines)


def otp_demo_preview_messages(tournament: dict) -> list[tuple[str, str]]:
    sample_tournament = copy.deepcopy(tournament)
    sample_tournament.setdefault("id", tournament.get("id", "demo-20261006"))
    sample_tournament.setdefault("status", "setup")
    sample_tournament.setdefault("phase", "setup")
    sample_tournament.setdefault("paused", False)
    sample_tournament.setdefault("min_members", 1)
    sample_tournament.setdefault("max_members", 4)
    sample_tournament.setdefault("xp_limit", 2700)
    team_a_key = otp_demo_team_key(sample_tournament["id"], "OTP-001")
    team_b_key = otp_demo_team_key(sample_tournament["id"], "OTP-002")
    sample_tournament["teams"] = {
        team_a_key: {
            "key": team_a_key,
            "application_id": "OTP-001",
            "application_number": 1,
            "team_name": "テストA",
            "status": "approved",
            "members": [
                {
                    "role": "リーダー",
                    "player_name": "テストAリーダー",
                    "circle": "Kogane",
                    "discord_id": "111111111111111111",
                    "xp": 2680,
                    "weapons": ["スプラシューター", "52ガロン", "わかばシューター"],
                    "top_weapon_rate": 12.5,
                }
            ],
        },
        team_b_key: {
            "key": team_b_key,
            "application_id": "OTP-002",
            "application_number": 2,
            "team_name": "テストB",
            "status": "pending",
            "members": [
                {
                    "role": "リーダー",
                    "player_name": "テストBリーダー",
                    "circle": "Kogane",
                    "discord_id": "222222222222222222",
                    "xp": 2650,
                    "weapons": ["シャープマーカー", "ボトルガイザー", "ジムワイパー"],
                    "top_weapon_rate": 10,
                }
            ],
        },
    }
    sample_match = {
        "id": "Q001",
        "phase": "qualifier",
        "block": 1,
        "teams": [team_a_key, team_b_key],
        "best_of": 3,
        "target_wins": 2,
        "status": "active",
        "battle_index": 1,
        "wins": {team_a_key: 0, team_b_key: 0},
        "battles": [],
        "stage_pool": OTP_DEMO_STAGES[1:],
        "current_stage": OTP_DEMO_STAGES[0],
        "reports": {},
        "report_generation": 1,
    }
    sample_tournament["matches"] = {"Q001": sample_match}
    sample_tournament["match_order"] = ["Q001"]

    registration_prompt = (
        "OTPデモ一括登録モードに入りました。次の形式で貼り付けてください。キャンセルで終了します。\n\n"
        "申請番号：OTP-001\n"
        "チーム名：テストA\n"
        "役割\tプレイヤー名\t所属\tDiscord ID\t最高XP\t1位ブキ\t2位ブキ\t3位ブキ\t1位ブキ使用率\n"
        "リーダー\tたまき\tKogane\t1225788050894753865\t2680\tスシ\t52ガロン\tわかば\t12.5"
    )
    start_check = (
        "開始対象 1チーム\n"
        "・OTP-001 テストA\n\n"
        "除外対象\n"
        "OTP-002 テストB｜未承認 ☑️\n\n"
        "予選ブロック構成\n"
        "開催不可\n\n"
        f"開始する場合は `!OTPデモ開始 {sample_tournament['id']} 確定` を実行してください。"
    )
    return [
        ("設定完了", f"OTPデモ `{sample_tournament['id']}` を設定しました。\n未指定値を本番定数から補完していません。次は `!OTPデモ登録 {{tournament_id}}` で登録できます。"),
        ("登録モード開始", registration_prompt),
        ("登録後のチーム表示", otp_demo_public_team_text(sample_tournament["teams"][team_a_key], sample_tournament)),
        ("登録エラー例", "登録できません:\n4行目: Discord IDの形式が不正です。\n5行目: 同じチーム内でDiscord IDが重複しています。"),
        ("承認完了", "OTP-001 テストA を承認しました。"),
        ("承認不可例", "承認できません: XPまたは使用率が未入力です"),
        ("棄権設定", "OTP-001 を棄権にしました。"),
        ("状況表示", otp_demo_summary_text(sample_tournament)),
        ("開始確認", start_check),
        ("開始完了", f"OTPデモ `{sample_tournament['id']}` を開始しました。予選ブロック: 3"),
        ("対戦案内", otp_demo_match_text(sample_tournament, sample_match)),
        ("片側報告", "片側の報告を受け付けました。もう一方のリーダー報告を待っています。"),
        ("1本確定", "Q001 OTP-001 勝ちで確定しました。"),
        ("報告不一致", "Q001 の報告が不一致でした。双方の新しい回答だけで再入力してください。"),
        ("運営裁定待ち", f"Q001 は再不一致のため運営裁定待ちです。`!OTP裁定 {sample_tournament['id']} Q001 勝者申請番号` で確定してください。"),
        ("裁定完了", "Q001 を運営裁定で確定しました。"),
        ("手動保留", "Q001 を保留しました。参加者入力では解除されません。"),
        ("保留解除", "Q001 の保留を解除しました。"),
        ("一時停止", "一時停止しました。新たな対戦開始は行いません。"),
        ("再開", "再開しました。"),
        ("終了", "OTPデモを終了扱いにしました。記録は bot_state.json に保持されています。"),
        ("権限エラー", "この大会の運営のみ実行できます。"),
        ("対象外操作", "開始後の一括登録更新は初版の対象外です。"),
    ]


def otp_demo_is_operator(member: discord.Member, tournament: dict) -> bool:
    if member.id == OWNER_ID:
        return True
    role_id = tournament.get("operator_role_id")
    return bool(role_id and any(role.id == int(role_id) for role in getattr(member, "roles", [])))


def build_otp_solo_test_team(tournament_id: str, number: int, name: str) -> tuple[str, dict]:
    application_id = f"OTP-{number:03d}"
    key = otp_demo_team_key(tournament_id, application_id)
    member = {
        "role": "リーダー",
        "player_name": f"{name}リーダー",
        "circle": "1人テスト",
        "discord_id": "",
        "xp": 2600 + number * 10,
        "weapons": ["スプラシューター", "52ガロン", "わかばシューター"],
        "top_weapon_rate": 10,
    }
    return key, {
        "key": key,
        "tournament_id": tournament_id,
        "application_id": application_id,
        "application_number": number,
        "team_name": name,
        "status": "approved",
        "members": [member],
        "created_at": time.time(),
        "updated_at": time.time(),
        "solo_test": True,
    }


async def start_otp_solo_test(guild: discord.Guild, operator: discord.Member, tournament: dict) -> str:
    if tournament.get("status") == "running":
        return "すでに進行中です。別の大会IDを使うか、現在のデモを終了してください。"
    teams = {}
    for number, name in ((1, "一人テストA"), (2, "一人テストB"), (3, "一人テストC")):
        key, team = build_otp_solo_test_team(tournament["id"], number, name)
        teams[key] = team
    blocks = calculate_otp_demo_blocks(list(teams.keys()))
    rr = make_round_robin_matches(blocks)
    tournament.update({
        "status": "running",
        "phase": "qualifier",
        "paused": False,
        "solo_test_mode": True,
        "solo_test_note": "Discord IDなしの仮チームで、運営が全チーム分の報告を代行する確認モードです。",
        "started_at": time.time(),
        "started_by": str(operator.id),
        "eligible_team_keys": list(teams.keys()),
        "teams": teams,
        "blocks": blocks,
        "matches": rr["matches"],
        "match_order": rr["order"],
        "brackets": {},
    })
    save_otp_tournaments()
    await otp_demo_start_waiting_matches(guild, tournament)
    return (
        f"OTPデモ `{tournament['id']}` を1人テストモードで開始しました。\n"
        "Discord IDなしの仮3チームを作成しました。対戦チャンネルを作り、通常版との差分も表示します。\n"
        "結果入力は対戦チャンネル内の勝者ボタンで行います。コマンド入力も予備として残しています。"
    )


class OTPDemoControlView(discord.ui.View):
    def __init__(self, tournament_id: str):
        super().__init__(timeout=None)
        self.tournament_id = tournament_id

    def get_tournament(self):
        return get_otp_tournaments().get(self.tournament_id)

    async def require_operator(self, interaction: discord.Interaction):
        tournament = self.get_tournament()
        if not tournament or not otp_demo_is_operator(interaction.user, tournament):
            await interaction.response.send_message("大会が見つからないか、権限がありません。", ephemeral=True)
            return None
        return tournament

    @discord.ui.button(label="1人テスト開始", style=discord.ButtonStyle.success, custom_id="otp_demo_panel_solo_start")
    async def solo_start(self, interaction: discord.Interaction, button: discord.ui.Button):
        tournament = await self.require_operator(interaction)
        if not tournament:
            return
        await interaction.response.defer(ephemeral=True)
        message = await start_otp_solo_test(interaction.guild, interaction.user, tournament)
        await interaction.followup.send(message, ephemeral=True)

    @discord.ui.button(label="状況表示", style=discord.ButtonStyle.primary, custom_id="otp_demo_panel_status")
    async def status_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        tournament = await self.require_operator(interaction)
        if not tournament:
            return
        await interaction.response.send_message(otp_demo_summary_text(tournament)[:1900], ephemeral=True)

    @discord.ui.button(label="文面一覧", style=discord.ButtonStyle.secondary, custom_id="otp_demo_panel_texts")
    async def texts_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        tournament = await self.require_operator(interaction)
        if not tournament:
            return
        await interaction.response.send_message("文面一覧をこのチャンネルに投稿します。", ephemeral=True)
        await interaction.channel.send(
            f"【OTPデモ文面一覧｜{self.tournament_id}】\n"
            "文章確認用のプレビューです。実際の大会状態は変更しません。"
        )
        for title, body in otp_demo_preview_messages(tournament):
            text = f"## {title}\n{body}"
            for i in range(0, len(text), 1900):
                await interaction.channel.send(text[i:i + 1900])

    @discord.ui.button(label="デモ終了", style=discord.ButtonStyle.danger, custom_id="otp_demo_panel_finish")
    async def finish_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        tournament = await self.require_operator(interaction)
        if not tournament:
            return
        await interaction.response.defer(ephemeral=True)
        await otp_demo_delete_all_match_channels(interaction.guild, tournament)
        tournament["status"] = "done"
        tournament["finished_at"] = time.time()
        tournament["finished_by"] = str(interaction.user.id)
        save_otp_tournaments()
        await interaction.followup.send("OTPデモを終了扱いにしました。対応する対戦チャンネルは削除しました。", ephemeral=True)


async def process_otp_demo_bulk_message(message):
    waiting = otp_demo_bulk_waiting.get(message.guild.id if message.guild else None)
    if not waiting or waiting.get("user_id") != message.author.id:
        return False
    if message.content.strip() == "キャンセル":
        otp_demo_bulk_waiting.pop(message.guild.id, None)
        await message.channel.send("OTPデモ一括登録をキャンセルしました。")
        return True
    tournaments = get_otp_tournaments()
    tournament = tournaments.get(waiting["tournament_id"])
    if not tournament:
        otp_demo_bulk_waiting.pop(message.guild.id, None)
        await message.channel.send("大会設定が見つからないため終了しました。")
        return True
    parsed, parse_errors = parse_otp_demo_bulk_text(message.content)
    if parse_errors:
        await message.channel.send("入力エラー:\n" + "\n".join(parse_errors))
        return True
    key = otp_demo_team_key(tournament["id"], parsed["application_id"])
    errors = await validate_otp_demo_team(message.guild, tournament, parsed, existing_key=key)
    if errors:
        await message.channel.send("登録できません:\n" + "\n".join(errors))
        return True
    existing = tournament.setdefault("teams", {}).get(key)
    status = "pending"
    if existing and existing.get("status") == "approved":
        status = "needs_review"
    team = copy.deepcopy(existing) if existing else {}
    team.update(parsed)
    team.update({
        "key": key,
        "tournament_id": tournament["id"],
        "status": status if not existing else status,
        "updated_at": time.time(),
        "updated_by": str(message.author.id),
    })
    if existing:
        team.setdefault("created_at", existing.get("created_at", time.time()))
    else:
        team["created_at"] = time.time()
    tournament["teams"][key] = team
    save_otp_tournaments()
    await message.channel.send(
        ("更新しました。承認済みチームは再確認が必要です。\n" if existing else "新規登録しました。\n")
        + otp_demo_public_team_text(team, tournament)
    )
    return True


class HomeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="募集作成", style=discord.ButtonStyle.success,
                       custom_id="home_create_recruit", row=0)
    async def create_recruit_button(self, interaction: discord.Interaction, button):
        await interaction.response.send_modal(
            RecruitModal(host_name=interaction.user.display_name)
        )

    @discord.ui.button(label="コイン", style=discord.ButtonStyle.primary,
                       custom_id="home_coin_menu", row=0)
    async def coin_button(self, interaction: discord.Interaction, button):
        profile = get_player_profile(interaction.user.id)
        coins = profile.get("coins", 0)
        text = (
            f"現在 {coins} / {COIN_LIMIT} コインを持っています。どうしますか？\n\n"
            f"{get_active_effect_text(interaction.user.id)}"
        )
        await interaction.response.send_message(text, view=CoinMenuView(interaction.user), ephemeral=True)

    @discord.ui.button(label="バッジ設定", style=discord.ButtonStyle.success,
                       custom_id="home_badge_select", row=0)
    async def badge_button(self, interaction: discord.Interaction, button):
        profile = get_player_profile(interaction.user.id)
        if not profile.get("owned_badges", []):
            await interaction.response.send_message("選べるバッジがありません", ephemeral=True)
            return
        await interaction.response.send_message(
            "表示するバッジを選択してください",
            view=BadgeSelectView(interaction.user),
            ephemeral=True
        )

    @discord.ui.button(label="プレイヤー登録", style=discord.ButtonStyle.danger,
                       custom_id="home_player_register", row=0)
    async def register_button(self, interaction: discord.Interaction, button):
        await interaction.response.send_modal(PlayerRegisterModal())

    @discord.ui.button(label="雑学投稿", style=discord.ButtonStyle.secondary,
                       custom_id="home_trivia_post", row=1)
    async def trivia_button(self, interaction: discord.Interaction, button):
        await interaction.response.send_modal(TriviaModal())

    @discord.ui.button(label="使い方", style=discord.ButtonStyle.secondary,
                       custom_id="home_help", row=1)
    async def help_button(self, interaction: discord.Interaction, button):
        await interaction.response.send_message(
            "何について知りたいですか？",
            view=HelpSelectView(),
            ephemeral=True
        )

    @discord.ui.button(label="募集通知ON/OFF", style=discord.ButtonStyle.primary,
                       custom_id="home_recruit_notifications", row=1)
    async def recruit_notifications_button(self, interaction: discord.Interaction, button):
        role = get_recruit_notification_role(interaction.guild)
        if role is None:
            await interaction.response.send_message("募集通知ロールが見つかりません。運営に連絡してください。", ephemeral=True)
            return
        if not role_can_be_managed(interaction.guild, role):
            await interaction.response.send_message(
                "募集通知ロールを操作できません。Botに「ロールの管理」権限を与え、Botのロールを対象ロールより上に置いてください。",
                ephemeral=True,
            )
            return

        try:
            if role in interaction.user.roles:
                await interaction.user.remove_roles(role, reason="募集通知を本人がOFFにしたため")
                message = "募集通知をOFFにしました。"
            else:
                await interaction.user.add_roles(role, reason="募集通知を本人がONにしたため")
                message = "募集通知をONにしました。新しい募集が投稿されると通知されます。"
        except discord.Forbidden:
            message = "ロールを操作できません。Botの権限とロールの上下関係を確認してください。"
        except discord.HTTPException:
            message = "ロールの更新に失敗しました。少し待ってからもう一度試してください。"
        await interaction.response.send_message(message, ephemeral=True)

class AdminConfirmView(discord.ui.View):
    """管理者ボタン用の確認ダイアログ"""
    def __init__(self, action_label: str, callback):
        super().__init__(timeout=30)
        self.callback_fn = callback

    @discord.ui.button(label="実行する", style=discord.ButtonStyle.danger)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.disable_all_buttons()
        await interaction.response.edit_message(view=self)
        await self.callback_fn(interaction)

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.disable_all_buttons()
        await interaction.response.edit_message(content="キャンセルしました", view=self)

    def disable_all_buttons(self):
        for child in self.children:
            child.disabled = True
            
class AdminButtonView_Ranking(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="ランキング更新", style=discord.ButtonStyle.primary, custom_id="admin_ranking")
    async def ranking_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        async def do_action(i):
            await post_ranking(i.guild)
            await post_peak_ranking(i.guild)
            await i.followup.send("ランキングを更新しました", ephemeral=True)
        await interaction.response.send_message(
            "ランキング更新を実行しますか？",
            view=AdminConfirmView("ランキング更新", do_action),
            ephemeral=True
        )

    @discord.ui.button(label="秘匿ランキング", style=discord.ButtonStyle.primary, custom_id="admin_secret_ranking")
    async def secret_ranking_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        async def do_action(i):
            await post_secret_ranking(i.guild)
            await i.followup.send("秘匿ランキングを送信しました", ephemeral=True)
        await interaction.response.send_message(
            "秘匿ランキングを送信しますか？",
            view=AdminConfirmView("秘匿ランキング", do_action),
            ephemeral=True
        )

    @discord.ui.button(label="ホーム更新", style=discord.ButtonStyle.primary, custom_id="admin_home_update")
    async def home_update_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        async def do_action(i):
            await post_home_message(i.guild)
            await i.followup.send("ホームを更新しました", ephemeral=True)
        await interaction.response.send_message(
            "ホームを更新しますか？",
            view=AdminConfirmView("ホーム更新", do_action),
            ephemeral=True
        )

class AdminButtonView_List(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="武器一覧", style=discord.ButtonStyle.secondary, custom_id="admin_weapon_list")
    async def weapon_list_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        await interaction.response.send_message("取得中...", ephemeral=True)
        try:
            members = [member async for member in interaction.guild.fetch_members(limit=None)]
        except Exception:
            members = interaction.guild.members
        human_members = sorted([m for m in members if not m.bot], key=lambda m: m.display_name.lower())
        lines = ["【武器一覧】"]
        for member in human_members:
            weapon = get_player_profile(member.id).get("weapon") or "未登録"
            lines.append(f"{member.id} {weapon}")
        text = "\n".join(lines)
        admin_ch = get_admin_channel(interaction.guild)
        if admin_ch:
            if len(text) <= 1900:
                await admin_ch.send(text)
            else:
                chunk = ""
                for line in lines:
                    if len(chunk) + len(line) + 1 > 1900:
                        await admin_ch.send(chunk)
                        chunk = line
                    else:
                        chunk += ("\n" if chunk else "") + line
                if chunk:
                    await admin_ch.send(chunk)
        await interaction.edit_original_response(content="武器一覧を送信しました")

    @discord.ui.button(label="XP一覧", style=discord.ButtonStyle.secondary, custom_id="admin_xp_list")
    async def xp_list_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        await interaction.response.send_message("取得中...", ephemeral=True)
        try:
            members = [member async for member in interaction.guild.fetch_members(limit=None)]
        except Exception:
            members = interaction.guild.members
        human_members = sorted([m for m in members if not m.bot], key=lambda m: m.display_name.lower())
        lines = ["【XP一覧】"]
        for member in human_members:
            xp = get_player_profile(member.id).get("xp")
            lines.append(f"{member.id} {xp if xp is not None else '未登録'}")
        text = "\n".join(lines)
        admin_ch = get_admin_channel(interaction.guild)
        if admin_ch:
            if len(text) <= 1900:
                await admin_ch.send(text)
            else:
                chunk = ""
                for line in lines:
                    if len(chunk) + len(line) + 1 > 1900:
                        await admin_ch.send(chunk)
                        chunk = line
                    else:
                        chunk += ("\n" if chunk else "") + line
                if chunk:
                    await admin_ch.send(chunk)
        await interaction.edit_original_response(content="XP一覧を送信しました")

    @discord.ui.button(label="ユーザーID一覧", style=discord.ButtonStyle.secondary, custom_id="admin_user_id_list")
    async def user_id_list_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        await interaction.response.send_message("取得中...", ephemeral=True)
        try:
            members = [member async for member in interaction.guild.fetch_members(limit=None)]
        except Exception:
            members = interaction.guild.members
        human_members = sorted([m for m in members if not m.bot], key=lambda m: m.display_name.lower())
        lines = ["【ユーザーID一覧】"] + [f"{m.display_name} {m.id}" for m in human_members]
        text = "\n".join(lines)
        admin_ch = get_admin_channel(interaction.guild)
        if admin_ch:
            if len(text) <= 1900:
                await admin_ch.send(text)
            else:
                chunk = ""
                for line in lines:
                    if len(chunk) + len(line) + 1 > 1900:
                        await admin_ch.send(chunk)
                        chunk = line
                    else:
                        chunk += ("\n" if chunk else "") + line
                if chunk:
                    await admin_ch.send(chunk)
        await interaction.edit_original_response(content="ユーザーID一覧を送信しました")

    


class AdminButtonView_Badge(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="バッジ付与", style=discord.ButtonStyle.success, custom_id="admin_badge_grant")
    async def badge_grant_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        options = [discord.SelectOption(label=v["label"], value=k) for k, v in BADGE_DEFINITIONS.items()]
        select = discord.ui.Select(placeholder="バッジを選択", options=options)
        async def callback(i: discord.Interaction):
            badge_id = select.values[0]
            async def do_action(i2):
                badge_bulk_waiting[i2.guild.id] = {"mode": "grant", "badge_id": badge_id, "user_id": i2.user.id}
                admin_ch = get_admin_channel(i2.guild)
                if admin_ch:
                    await admin_ch.send(f"バッジ付与モード（{badge_id}）\nユーザーIDを1行ずつ送ってください。キャンセルで終了。")
                await i2.followup.send("運営チャンネルでユーザーIDを送ってください", ephemeral=True)
            await i.response.send_message(
                f"バッジ「{badge_id}」の付与モードを開始しますか？",
                view=AdminConfirmView("バッジ付与", do_action),
                ephemeral=True
            )
        select.callback = callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.response.send_message("付与するバッジを選択してください", view=view, ephemeral=True)

    @discord.ui.button(label="バッジ削除", style=discord.ButtonStyle.success, custom_id="admin_badge_remove")
    async def badge_remove_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        options = [discord.SelectOption(label=v["label"], value=k) for k, v in BADGE_DEFINITIONS.items()]
        select = discord.ui.Select(placeholder="バッジを選択", options=options)
        async def callback(i: discord.Interaction):
            badge_id = select.values[0]
            async def do_action(i2):
                badge_bulk_waiting[i2.guild.id] = {"mode": "remove", "badge_id": badge_id, "user_id": i2.user.id}
                admin_ch = get_admin_channel(i2.guild)
                if admin_ch:
                    await admin_ch.send(f"バッジ削除モード（{badge_id}）\nユーザーIDを1行ずつ送ってください。キャンセルで終了。")
                await i2.followup.send("運営チャンネルでユーザーIDを送ってください", ephemeral=True)
            await i.response.send_message(
                f"バッジ「{badge_id}」の削除モードを開始しますか？",
                view=AdminConfirmView("バッジ削除", do_action),
                ephemeral=True
            )
        select.callback = callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.response.send_message("削除するバッジを選択してください", view=view, ephemeral=True)

    @discord.ui.button(label="バッジ強制付与", style=discord.ButtonStyle.success, custom_id="admin_badge_force")
    async def badge_force_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        options = [discord.SelectOption(label=v["label"], value=k) for k, v in BADGE_DEFINITIONS.items()]
        select = discord.ui.Select(placeholder="バッジを選択", options=options)
        async def callback(i: discord.Interaction):
            badge_id = select.values[0]
            async def do_action(i2):
                badge_bulk_waiting[i2.guild.id] = {"mode": "force_grant", "badge_id": badge_id, "user_id": i2.user.id}
                admin_ch = get_admin_channel(i2.guild)
                if admin_ch:
                    await admin_ch.send(f"バッジ強制付与モード（{badge_id}）\nユーザーIDを1行ずつ送ってください。キャンセルで終了。")
                await i2.followup.send("運営チャンネルでユーザーIDを送ってください", ephemeral=True)
            await i.response.send_message(
                f"バッジ「{badge_id}」の強制付与モードを開始しますか？",
                view=AdminConfirmView("バッジ強制付与", do_action),
                ephemeral=True
            )
        select.callback = callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.response.send_message("強制付与するバッジを選択してください", view=view, ephemeral=True)

    @discord.ui.button(label="所持バッジ一覧", style=discord.ButtonStyle.success, custom_id="admin_badge_list_user")
    async def badge_list_user_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        await interaction.response.send_message("運営チャンネルで `!所持バッジ一覧 ユーザーID` を使ってください", ephemeral=True)

    @discord.ui.button(label="バッジ所持者一覧", style=discord.ButtonStyle.success, custom_id="admin_badge_list_badge")
    async def badge_list_badge_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        options = [discord.SelectOption(label=v["label"], value=k) for k, v in BADGE_DEFINITIONS.items()]
        select = discord.ui.Select(placeholder="バッジを選択", options=options)
        async def callback(i: discord.Interaction):
            badge_id = select.values[0]
            result = []
            for uid, profile in player_profiles.items():
                if badge_id in profile.get("owned_badges", []):
                    name = i.guild.get_member(int(uid))
                    result.append(name.display_name if name else uid)
            badge_data = BADGE_DEFINITIONS.get(badge_id, {})
            label = badge_data.get("label", badge_id)
            text = f"{label} の所持者:\n" + ("\n".join(result) if result else "所持者なし")
            admin_ch = get_admin_channel(i.guild)
            if admin_ch:
                await admin_ch.send(text)
            await i.response.send_message("運営チャンネルに送信しました", ephemeral=True)
        select.callback = callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.response.send_message("バッジを選択してください", view=view, ephemeral=True)

class AdminButtonView_Rate(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="レート値変更", style=discord.ButtonStyle.danger, custom_id="admin_rate_change")
    async def rate_change_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        async def do_action(i):
            bulk_rate_change_waiting[i.guild.id] = i.user.id
            admin_ch = get_admin_channel(i.guild)
            if admin_ch:
                await admin_ch.send("レート値変更モード\nユーザーID レート値 を1行ずつ送ってください。キャンセルで終了。")
            await i.followup.send("運営チャンネルで入力してください", ephemeral=True)
        await interaction.response.send_message(
            "レート値変更モードを開始しますか？",
            view=AdminConfirmView("レート値変更", do_action),
            ephemeral=True
        )

    @discord.ui.button(label="全員RD設定", style=discord.ButtonStyle.danger, custom_id="admin_rd_set")
    async def rd_set_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        await interaction.response.send_message("運営チャンネルで `!全員RD設定 値` を使ってください", ephemeral=True)

    @discord.ui.button(label="全員レートリセット", style=discord.ButtonStyle.danger, custom_id="admin_rate_reset")
    async def rate_reset_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        async def do_action(i):
            members = await get_human_members(i.guild)
            for member in members:
                uid = str(member.id)
                ratings[uid] = {"rating": float(DEFAULT_RATING), "rd": DEFAULT_RD, "volatility": DEFAULT_VOLATILITY}
                profile = get_player_profile(member.id)
                profile.update({
                    "initial_applied": False, "can_apply_initial_bonus": True,
                    "coins": 0, "tickets": [], "active_effect": None,
                    "next_coin_at": None, "win_streak": 0, "last_played": None,
                })
            save_ratings(ratings)
            save_player_profiles(player_profiles)
            await post_ranking(i.guild)
            await post_home_message(i.guild)
            home_channel = get_home_channel(i.guild)
            if home_channel:
                await home_channel.send(
                    "【シーズン開始】\n武器登録と最高XP登録をしてください。\n"
                    "XP補正を反映したい人は、プレイヤー登録ボタンからもう一度登録してくれ。"
                )
            await i.followup.send(f"全プレイヤーのレートを {DEFAULT_RATING} にリセットしました", ephemeral=True)
        await interaction.response.send_message(
            "⚠️ 全員のレートをリセットします。本当に実行しますか？",
            view=AdminConfirmView("全員レートリセット", do_action),
            ephemeral=True
        )

    @discord.ui.button(label="最高レート初期化", style=discord.ButtonStyle.danger, custom_id="admin_peak_init")
    async def peak_init_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        async def do_action(i):
            count = 0
            for uid, profile in player_profiles.items():
                if profile.get("peak_rating") is None:
                    current = get_user_rating(uid)
                    profile["peak_rating"] = current
                    count += 1
            save_player_profiles(player_profiles)
            await i.followup.send(f"{count}人の最高レートを初期化しました", ephemeral=True)
        await interaction.response.send_message(
            "最高レートを初期化しますか？",
            view=AdminConfirmView("最高レート初期化", do_action),
            ephemeral=True
        )
class AdminButtonView_Bulk(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="募集通知ロールを全員に付与", style=discord.ButtonStyle.danger,
                       custom_id="admin_recruit_notification_role_grant")
    async def grant_recruit_notification_role_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return

        role = get_recruit_notification_role(interaction.guild)
        if role is None:
            await interaction.response.send_message("募集通知ロールが見つかりません。", ephemeral=True)
            return
        if not role_can_be_managed(interaction.guild, role):
            await interaction.response.send_message(
                "Botに「ロールの管理」権限を与え、Botのロールを募集通知ロールより上に置いてください。",
                ephemeral=True,
            )
            return

        async def do_action(i):
            members = await get_human_members(i.guild)
            added = 0
            already_assigned = 0
            failed = 0
            for member in members:
                if role in member.roles:
                    already_assigned += 1
                    continue
                try:
                    await member.add_roles(role, reason="運営による募集通知ロールの初回一括付与")
                    added += 1
                except (discord.Forbidden, discord.HTTPException):
                    failed += 1

            result = f"募集通知ロールを {added}人に付与しました（すでに所持: {already_assigned}人）"
            if failed:
                result += f"。{failed}人は付与できませんでした"
            await i.followup.send(result, ephemeral=True)

        await interaction.response.send_message(
            "現在いるBot以外の全メンバーへ募集通知ロールを付与します。各自はホームから後で通知をOFFにできます。実行しますか？",
            view=AdminConfirmView("募集通知ロールを全員に付与", do_action),
            ephemeral=True,
        )

    @discord.ui.button(label="運営一括", style=discord.ButtonStyle.secondary, custom_id="admin_bulk")
    async def bulk_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        async def do_action(i):
            bulk_admin_waiting[i.guild.id] = i.user.id
            admin_ch = get_admin_channel(i.guild)
            if admin_ch:
                await admin_ch.send(
                    "運営一括モード\nユーザーID コマンド 内容 を1行ずつ送ってください。\n\n"
                    "使えるコマンド:\n武器 / 武器削除 / XP / XP削除\n"
                    "バッジ付与 / バッジ削除 / バッジ強制付与\n"
                    "レート / 初期補正付与 / 初期補正剥奪\nコイン / チケット付与\n\n"
                    "やめるときは キャンセル"
                )
            await i.followup.send("運営チャンネルで入力してください", ephemeral=True)
        await interaction.response.send_message(
            "運営一括モードを開始しますか？",
            view=AdminConfirmView("運営一括", do_action),
            ephemeral=True
        )

    @discord.ui.button(label="運営一覧1", style=discord.ButtonStyle.secondary, custom_id="admin_dump_1")
    async def dump1_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        await interaction.response.send_message("取得中...", ephemeral=True)
        try:
            members = [member async for member in interaction.guild.fetch_members(limit=None)]
        except Exception:
            members = interaction.guild.members
        human_members = sorted([m for m in members if not m.bot], key=lambda m: m.display_name.lower())
        lines = []
        for member in human_members:
            uid = str(member.id)
            profile = get_player_profile(member.id)
            if profile.get("weapon"):
                lines.append(f"{uid} 武器 {profile['weapon']}")
            if profile.get("xp") is not None:
                lines.append(f"{uid} XP {profile['xp']}")
        admin_ch = get_admin_channel(interaction.guild)
        if admin_ch and lines:
            text = "\n".join(lines)
            if len(text) <= 1900:
                await admin_ch.send(text)
            else:
                chunk = ""
                for line in lines:
                    if len(chunk) + len(line) + 1 > 1900:
                        await admin_ch.send(chunk)
                        chunk = line
                    else:
                        chunk += ("\n" if chunk else "") + line
                if chunk:
                    await admin_ch.send(chunk)
        await interaction.edit_original_response(content="運営一覧1を送信しました")

    @discord.ui.button(label="運営一覧2", style=discord.ButtonStyle.secondary, custom_id="admin_dump_2")
    async def dump2_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        await interaction.response.send_message("取得中...", ephemeral=True)
        try:
            members = [member async for member in interaction.guild.fetch_members(limit=None)]
        except Exception:
            members = interaction.guild.members
        human_members = sorted([m for m in members if not m.bot], key=lambda m: m.display_name.lower())
        lines = []
        for member in human_members:
            uid = str(member.id)
            for badge_id in get_player_profile(member.id).get("owned_badges", []):
                lines.append(f"{uid} バッジ付与 {badge_id}")
        admin_ch = get_admin_channel(interaction.guild)
        if admin_ch and lines:
            text = "\n".join(lines)
            if len(text) <= 1900:
                await admin_ch.send(text)
            else:
                chunk = ""
                for line in lines:
                    if len(chunk) + len(line) + 1 > 1900:
                        await admin_ch.send(chunk)
                        chunk = line
                    else:
                        chunk += ("\n" if chunk else "") + line
                if chunk:
                    await admin_ch.send(chunk)
        await interaction.edit_original_response(content="運営一覧2を送信しました")

    @discord.ui.button(label="運営一覧3", style=discord.ButtonStyle.secondary, custom_id="admin_dump_3")
    async def dump3_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        await interaction.response.send_message("取得中...", ephemeral=True)
        try:
            members = [member async for member in interaction.guild.fetch_members(limit=None)]
        except Exception:
            members = interaction.guild.members
        human_members = sorted([m for m in members if not m.bot], key=lambda m: m.display_name.lower())
        lines = []
        for member in human_members:
            uid = str(member.id)
            selected = get_player_profile(member.id).get("selected_badge")
            if selected:
                lines.append(f"{uid} バッジ強制付与 {selected}")
        admin_ch = get_admin_channel(interaction.guild)
        if admin_ch and lines:
            text = "\n".join(lines)
            if len(text) <= 1900:
                await admin_ch.send(text)
            else:
                chunk = ""
                for line in lines:
                    if len(chunk) + len(line) + 1 > 1900:
                        await admin_ch.send(chunk)
                        chunk = line
                    else:
                        chunk += ("\n" if chunk else "") + line
                if chunk:
                    await admin_ch.send(chunk)
        await interaction.edit_original_response(content="運営一覧3を送信しました")

    @discord.ui.button(label="運営一覧4", style=discord.ButtonStyle.secondary, custom_id="admin_dump_4")
    async def dump4_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        await interaction.response.send_message("取得中...", ephemeral=True)
        try:
            members = [member async for member in interaction.guild.fetch_members(limit=None)]
        except Exception:
            members = interaction.guild.members
        human_members = sorted([m for m in members if not m.bot], key=lambda m: m.display_name.lower())
        lines = [f"{str(m.id)} コイン {get_player_profile(m.id).get('coins', 0)}" for m in human_members]
        admin_ch = get_admin_channel(interaction.guild)
        if admin_ch and lines:
            text = "\n".join(lines)
            if len(text) <= 1900:
                await admin_ch.send(text)
            else:
                chunk = ""
                for line in lines:
                    if len(chunk) + len(line) + 1 > 1900:
                        await admin_ch.send(chunk)
                        chunk = line
                    else:
                        chunk += ("\n" if chunk else "") + line
                if chunk:
                    await admin_ch.send(chunk)
        await interaction.edit_original_response(content="運営一覧4を送信しました")

    @discord.ui.button(label="運営一覧5", style=discord.ButtonStyle.secondary, custom_id="admin_dump_5")
    async def dump5_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        await interaction.response.send_message("取得中...", ephemeral=True)
        try:
            members = [member async for member in interaction.guild.fetch_members(limit=None)]
        except Exception:
            members = interaction.guild.members
        human_members = sorted([m for m in members if not m.bot], key=lambda m: m.display_name.lower())
        lines = []
        for member in human_members:
            uid = str(member.id)
            profile = get_player_profile(member.id)
            ticket_ids = [t.get("ticket_id") for t in profile.get("tickets", []) if t.get("ticket_id")]
            ae = profile.get("active_effect")
            if ae and ae.get("ticket_id"):
                ticket_ids.append(ae.get("ticket_id"))
            if ticket_ids:
                lines.append(f"{uid} チケット付与 " + " ".join(ticket_ids))
        admin_ch = get_admin_channel(interaction.guild)
        if admin_ch and lines:
            text = "\n".join(lines)
            if len(text) <= 1900:
                await admin_ch.send(text)
            else:
                chunk = ""
                for line in lines:
                    if len(chunk) + len(line) + 1 > 1900:
                        await admin_ch.send(chunk)
                        chunk = line
                    else:
                        chunk += ("\n" if chunk else "") + line
                if chunk:
                    await admin_ch.send(chunk)
        await interaction.edit_original_response(content="運営一覧5を送信しました")

    @discord.ui.button(label="運営一覧6", style=discord.ButtonStyle.secondary, custom_id="admin_dump_6")
    async def dump6_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        await interaction.response.send_message("取得中...", ephemeral=True)
        try:
            members = [member async for member in interaction.guild.fetch_members(limit=None)]
        except Exception:
            members = interaction.guild.members
        human_members = sorted([m for m in members if not m.bot], key=lambda m: m.display_name.lower())
        lines = [f"{str(m.id)} レート {get_user_rating(m.id)}" for m in human_members]
        admin_ch = get_admin_channel(interaction.guild)
        if admin_ch and lines:
            text = "\n".join(lines)
            if len(text) <= 1900:
                await admin_ch.send(text)
            else:
                chunk = ""
                for line in lines:
                    if len(chunk) + len(line) + 1 > 1900:
                        await admin_ch.send(chunk)
                        chunk = line
                    else:
                        chunk += ("\n" if chunk else "") + line
                if chunk:
                    await admin_ch.send(chunk)
        await interaction.edit_original_response(content="運営一覧6を送信しました")

    @discord.ui.button(label="運営一覧7", style=discord.ButtonStyle.secondary, custom_id="admin_dump_7")
    async def dump7_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        await interaction.response.send_message("取得中...", ephemeral=True)
        try:
            members = [member async for member in interaction.guild.fetch_members(limit=None)]
        except Exception:
            members = interaction.guild.members
        human_members = sorted([m for m in members if not m.bot], key=lambda m: m.display_name.lower())
        lines = [f"{str(m.id)} 最高レート {get_peak_rating(m.id)}" for m in human_members]
        admin_ch = get_admin_channel(interaction.guild)
        if admin_ch and lines:
            text = "\n".join(lines)
            if len(text) <= 1900:
                await admin_ch.send(text)
            else:
                chunk = ""
                for line in lines:
                    if len(chunk) + len(line) + 1 > 1900:
                        await admin_ch.send(chunk)
                        chunk = line
                    else:
                        chunk += ("\n" if chunk else "") + line
                if chunk:
                    await admin_ch.send(chunk)
        await interaction.edit_original_response(content="運営一覧7を送信しました")

    @discord.ui.button(label="名前更新", style=discord.ButtonStyle.secondary, custom_id="admin_name_update")
    async def name_update_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        async def do_action(i):
            try:
                members = [member async for member in i.guild.fetch_members(limit=None)]
            except Exception:
                members = i.guild.members
            count = 0
            for member in members:
                if member.bot:
                    continue
                profile = get_player_profile(member.id)
                profile["display_name"] = member.display_name
                count += 1
            save_player_profiles(player_profiles)
            await i.followup.send(f"{count}人の名前を更新しました", ephemeral=True)
        await interaction.response.send_message(
            "全員の名前を更新しますか？",
            view=AdminConfirmView("名前更新", do_action),
            ephemeral=True
        )

    @discord.ui.button(label="アバター更新", style=discord.ButtonStyle.secondary, custom_id="admin_avatar_update")
    async def avatar_update_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        async def do_action(i):
            try:
                members = [member async for member in i.guild.fetch_members(limit=None)]
            except Exception:
                members = i.guild.members
            count = 0
            for member in members:
                if member.bot:
                    continue
                profile = get_player_profile(member.id)
                if member.avatar:
                    profile["avatar_url"] = str(member.avatar.url)
                else:
                    profile["avatar_url"] = "https://cdn.discordapp.com/embed/avatars/0.png"
                count += 1
            save_player_profiles(player_profiles)
            await i.followup.send(f"{count}人のアバターを更新しました", ephemeral=True)
        await interaction.response.send_message(
            "全員のアバターを更新しますか？",
            view=AdminConfirmView("アバター更新", do_action),
            ephemeral=True
        )

async def post_admin_buttons(guild):
    channel = guild.get_channel(ADMIN_BUTTON_CHANNEL_ID)
    if channel is None:
        return

    guild_key = str(guild.id)
    saved_ids = bot_state.get("admin_button_message_ids", {})

    existing = saved_ids.get(guild_key, {})
    for msg_id in existing.values():
        try:
            msg = await channel.fetch_message(msg_id)
            await msg.delete()
        except Exception:
            pass

    new_ids = {}

    msg0 = await channel.send("【ランキング・ホーム系】", view=AdminButtonView_Ranking())
    new_ids["ranking"] = msg0.id

    msg1 = await channel.send("【一覧系】", view=AdminButtonView_List())
    new_ids["list"] = msg1.id

    msg2 = await channel.send("【バッジ系】", view=AdminButtonView_Badge())
    new_ids["badge"] = msg2.id

    msg3 = await channel.send("【レート・補正系】", view=AdminButtonView_Rate())
    new_ids["rate"] = msg3.id

    msg4 = await channel.send("【一括系】", view=AdminButtonView_Bulk())
    new_ids["bulk"] = msg4.id

    if "admin_button_message_ids" not in bot_state:
        bot_state["admin_button_message_ids"] = {}
    bot_state["admin_button_message_ids"][guild_key] = new_ids
    save_bot_state(bot_state)

async def post_home_message(guild):
    channel = get_home_channel(guild)
    if channel is None:
        return None

    content = (
        "【ホーム】\n\n"
        "・募集作成：プラベの募集を作成します\n"
        "・プレイヤー登録：武器・最高XPを登録します\n"
        "・バッジ設定：表示バッジを変更します\n"
        "・コイン：コインの確認・ガチャ・チケット操作ができます\n"
        "・雑学投稿：ガチャに表示される雑学を投稿できます\n"
        "・募集通知ON/OFF：新しい募集の通知を受け取るか設定できます"
    )

    guild_key = str(guild.id)
    saved_ids = bot_state.get("home_message_ids", {})
    saved_message_id = saved_ids.get(guild_key)

    if saved_message_id:
        try:
            msg = await channel.fetch_message(saved_message_id)
            await msg.edit(content=content, view=HomeView())
            return msg
        except Exception:
            pass

    msg = await channel.send(content, view=HomeView())

    if "home_message_ids" not in bot_state:
        bot_state["home_message_ids"] = {}
    bot_state["home_message_ids"][guild_key] = msg.id
    save_bot_state(bot_state)

    return msg


# =========================
# ランキング
# =========================
async def build_ranking_lines(guild):
    try:
        members = [member async for member in guild.fetch_members(limit=None)]
    except Exception:
        members = guild.members

    human_members = [m for m in members if not m.bot]
    ranking_data = []
    for member in human_members:
        rate = get_user_rating(member.id)
        display_text = build_player_display(member, include_badge=True)
        ranking_data.append((rate, member.display_name.lower(), display_text))

    ranking_data.sort(key=lambda x: (-x[0], x[1]))

    if not ranking_data:
        return ["# 【レートランキング】", "ランキング対象のメンバーがいません"]

    lines = ["# 【レートランキング】"]
    for i, (rate, _, display_text) in enumerate(ranking_data, start=1):
        lines.append(f"## #{i} {display_text} - {rate}")

    return lines


async def delete_old_ranking_messages(guild):
    ranking_channel = get_ranking_channel(guild)
    if ranking_channel is None:
        return
    async for msg in ranking_channel.history(limit=100):
        if msg.author == bot.user and (
            msg.content.startswith("【レートランキング】")
            or msg.content.startswith("# 【レートランキング】")
        ):
            try:
                await msg.delete()
            except Exception:
                pass


async def post_ranking(guild):
    # 公開ランキングはWebに集約する。
    return


async def post_secret_ranking(guild):
    admin_channel = get_admin_channel(guild)
    if admin_channel is None:
        return
    lines = await build_ranking_lines(guild)
    message = ""
    for line in lines:
        if len(message) + len(line) + 1 > 1900:
            await admin_channel.send(message)
            message = line
        else:
            message += ("\n" if message else "") + line
    if message:
        await admin_channel.send(message)


# =========================
# 進行制御
# =========================


async def begin_ready(guild, room_key):
    room_state = room_states[room_key]
    view = ReadyView(room_key, room_state)
    await update_control_message(guild, room_key, create_ready_text(room_state), view=view)


async def start_game(guild, room_key):
    room_state = room_states[room_key]

    if not room_state["prepared_match"]:
        return

    room_state["current_match"] = room_state["prepared_match"]
    room_state["prepared_match"] = None
    room_state["game_state"] = "playing"

    team_alpha, team_bravo = room_state["current_match"]
    mark_match_played_for_members(team_alpha + team_bravo)
    await move_members_to_vc(guild, room_key, team_alpha, team_bravo)

    view = PlayingView(room_key, room_state)
    await update_control_message(guild, room_key, create_playing_text(team_alpha, team_bravo, room_key), view=view)


async def next_game(guild, room_key):
    room_state = room_states[room_key]

    if room_state["game_state"] != "finished":
        return

    if not room_state["prepared_match"]:
        channel = get_progress_channel(guild, room_key)
        if channel:
            await channel.send("次の試合情報がありません")
        return

    room_state["current_match"] = room_state["prepared_match"]
    room_state["prepared_match"] = None
    room_state["game_state"] = "playing"

    team_alpha, team_bravo = room_state["current_match"]
    mark_match_played_for_members(team_alpha + team_bravo)
    await move_members_to_vc(guild, room_key, team_alpha, team_bravo)

    view = PlayingView(room_key, room_state)
    await update_control_message(guild, room_key, create_playing_text(team_alpha, team_bravo, room_key), view=view)


# =========================
# レート計算（共通関数）
# =========================
def calc_rating_change_for_player(user, enemy_team, score, winners, pattern_multiplier):
    uid = str(user.id)
    entry = get_rating_entry(uid)
    old_rating = float(entry["rating"])
    old_rd = float(entry["rd"])
    old_volatility = float(entry["volatility"])

    enemy_avg_rating = sum(float(get_rating_entry(str(e.id))["rating"]) for e in enemy_team) / len(enemy_team)
    enemy_avg_rd = sum(float(get_rating_entry(str(e.id))["rd"]) for e in enemy_team) / len(enemy_team)

    new_rating_raw, new_rd_raw, new_volatility = glicko2_update(
        old_rating, old_rd, old_volatility, [(enemy_avg_rating, enemy_avg_rd, score)]
    )

    glicko_change = new_rating_raw - old_rating
    base_adjusted = glicko_change * BASE_CHANGE_GAIN
    pattern_adjusted = base_adjusted * pattern_multiplier

    rating_gap = enemy_avg_rating - old_rating
    gap_multiplier = max(0.85, min(1.15, 1.0 + (rating_gap / 1000.0) * 0.25))
    gap_adjusted = pattern_adjusted * gap_multiplier

    ticket_multiplier = get_rate_multiplier(user.id)
    multiplied = gap_adjusted * ticket_multiplier

    active_effect = get_player_profile(user.id).get("active_effect")
    ticket_flat_bonus = int(active_effect.get("value", 0)) if active_effect and active_effect.get("type") == "flat_bonus" else 0
    streak_bonus = get_win_streak_bonus(user.id) if user in winners else 0

    raw_final_change = int(round(multiplied)) + PARTICIPATION_BONUS + streak_bonus + ticket_flat_bonus
    final_change = int(round(raw_final_change / 2.5))
    final_rating = old_rating + final_change
    ticket_label = active_effect.get("label") if active_effect else None

    return float(final_rating), float(new_rd_raw), float(new_volatility), final_change, ticket_label

async def process_result(guild, room_key, winner_num: int):
    room_state = room_states[room_key]

    if not room_state["current_match"]:
        return

    team_alpha, team_bravo = room_state["current_match"]

    room_state["last_profile_snapshots"] = {}
    for user in team_alpha + team_bravo:
        uid = str(user.id)
        apply_rd_decay_recovery(uid)
        profile = get_player_profile(user.id)
        entry = get_rating_entry(uid)
        room_state["last_profile_snapshots"][uid] = {
            "win_streak": profile.get("win_streak", 0),
            "active_effect": copy.deepcopy(profile.get("active_effect")),
            "tickets": copy.deepcopy(profile.get("tickets", [])),
            "last_played": profile.get("last_played"),
            "rating": float(entry["rating"]),
            "rd": float(entry["rd"]),
            "volatility": float(entry["volatility"]),
        }

    if winner_num == 1:
        winners, losers = team_alpha, team_bravo
        alpha_score, bravo_score = 1.0, 0.0
    else:
        winners, losers = team_bravo, team_alpha
        alpha_score, bravo_score = 0.0, 1.0

    update_win_streaks(winners, losers)

    room_state["last_rating_changes"] = {str(u.id): get_user_rating(u.id) for u in team_alpha + team_bravo}
    room_state["last_rating_detail"] = {}

    pending_updates = {}
    pattern_multiplier = get_pattern_multiplier(room_state)

    for user, enemy_team, score in [(u, team_bravo, alpha_score) for u in team_alpha] + \
                                   [(u, team_alpha, bravo_score) for u in team_bravo]:
        uid = str(user.id)
        final_rating, new_rd, new_volatility, final_change, ticket_label = calc_rating_change_for_player(
            user, enemy_team, score, winners, pattern_multiplier
        )
        pending_updates[uid] = {"rating": final_rating, "rd": new_rd, "volatility": new_volatility}
        room_state["last_rating_detail"][uid] = {"final": final_change, "ticket_label": ticket_label}

    for uid, data in pending_updates.items():
        entry = get_rating_entry(uid)
        entry["rating"] = float(data["rating"])
        old_rd = float(entry["rd"])
        entry["rd"] = max(RD_MIN, min(RD_MAX, RD_MIN + (old_rd - RD_MIN) * RD_DECAY))
        entry["volatility"] = float(data["volatility"])

    for user in team_alpha + team_bravo:
        consume_active_effect_match(user.id)
        get_player_profile(user.id)["last_played"] = time.time()

    save_ratings(ratings)
    save_player_profiles(player_profiles)

    from datetime import datetime
    stage = room_state.get("current_stage")
    match_record = {
        "timestamp": datetime.utcnow().isoformat(),
        "stage": stage,
        "alpha": [str(u.id) for u in team_alpha],
        "bravo": [str(u.id) for u in team_bravo],
        "winner": "alpha" if winner_num == 1 else "bravo",
        "ratings_before": dict(room_state["last_rating_changes"]),
        "ratings_after": {str(u.id): get_user_rating(u.id) for u in team_alpha + team_bravo},
        "rating_changes": {
            str(u.id): get_user_rating(u.id) - room_state["last_rating_changes"][str(u.id)]
            for u in team_alpha + team_bravo
        },
        "rating_details": copy.deepcopy(room_state["last_rating_detail"]),
    }
    history = load_match_history()
    history.append(match_record)
    save_match_history(history)
    room_state["last_match_timestamp"] = match_record["timestamp"]

    await check_and_update_peak_ranking(
        guild, [str(u.id) for u in team_alpha + team_bravo]
    )

    room_state["prepared_match"] = make_teams_from_roles(room_state)

    await send_rate_log(guild, room_state, team_alpha, team_bravo, room_key)

    room_state["game_state"] = "finished"
    view = FinishedView(room_key, room_state)
    await update_control_message(guild, room_key, create_finished_text(room_state, room_key), view=view)

async def send_rate_log(guild, room_state, team_alpha, team_bravo, room_key):
    # 試合結果の数値は共有チャンネルへ投稿しない。
    return


async def end_room(guild, room_key):
    room_state = room_states[room_key]

    grant_room_coin_lottery(room_state)
    await move_members_to_lobby(guild, room_key, room_state)

    channel = get_progress_channel(guild, room_key)
    if channel:
        await channel.send(
            "部屋を終了しました。レートは専用チャンネルのボタンから確認できます。\n"
            "次の募集は「ホーム」の「募集作成」ボタンから作成してください。"
        )

    reset_room_state(room_state)
    reset_room_tracking(room_state)

    # ★ チャンネル削除
    await delete_room_channels(guild, room_key)


async def undo_result(guild, room_key):
    room_state = room_states[room_key]
    channel = get_progress_channel(guild, room_key)

    if not room_state["last_rating_changes"]:
        if channel:
            await channel.send("戻せる試合結果がありません")
        return

    snapshots = room_state.get("last_profile_snapshots") or {}

    for user_id, old_rate in room_state["last_rating_changes"].items():
        snapshot = snapshots.get(user_id)
        if snapshot:
            set_user_rating(user_id, snapshot.get("rating", old_rate))
            set_user_rd(user_id, snapshot.get("rd", DEFAULT_RD))
            set_user_volatility(user_id, snapshot.get("volatility", DEFAULT_VOLATILITY))
        else:
            set_user_rating(user_id, old_rate)

    for user_id, snapshot in snapshots.items():
        profile = get_player_profile(int(user_id))
        profile["win_streak"] = snapshot.get("win_streak", 0)
        profile["active_effect"] = snapshot.get("active_effect")
        profile["tickets"] = snapshot.get("tickets", [])
        profile["last_played"] = snapshot.get("last_played")

    save_ratings(ratings)
    save_player_profiles(player_profiles)

    last_match_timestamp = room_state.get("last_match_timestamp")
    if last_match_timestamp:
        history = load_match_history()
        for index in range(len(history) - 1, -1, -1):
            if history[index].get("timestamp") == last_match_timestamp:
                history.pop(index)
                save_match_history(history)
                break

    room_state["last_rating_changes"] = None
    room_state["last_rating_detail"] = None
    room_state["last_profile_snapshots"] = None
    room_state["last_match_timestamp"] = None
    room_state["prepared_match"] = None
    room_state["disconnect_vote"] = None
    room_state["disconnect_vote_message"] = None
    room_state["game_state"] = "playing"

    if room_state["current_match"]:
        team_alpha, team_bravo = room_state["current_match"]
        view = PlayingView(room_key, room_state)
        await update_control_message(guild, room_key, create_playing_text(team_alpha, team_bravo), view=view)


async def start_disconnect_vote(guild, room_key, member):
    room_state = room_states[room_key]
    channel = get_progress_channel(guild, room_key)

    if not room_state["current_match"]:
        if channel:
            await channel.send("試合情報がないよ")
        return

    all_players = room_state["current_match"][0] + room_state["current_match"][1]
    if member not in all_players:
        if channel:
            await channel.send("そのユーザーは今回の試合に参加していません")
        return

    room_state["disconnect_vote"] = {
        "target_id": str(member.id),
        "self_vote": None,
        "jury_votes": {},
    }
    room_state["game_state"] = "disconnect_vote"

    view = DisconnectVoteView(room_key, room_state)
    if channel:
        room_state["disconnect_vote_message"] = await channel.send(
            create_disconnect_vote_text(member), view=view
        )


async def apply_disconnect_rating_change(guild, room_key, member):
    room_state = room_states[room_key]
    channel = get_progress_channel(guild, room_key)

    team_alpha, team_bravo = room_state["current_match"]
    all_players = team_alpha + team_bravo

    room_state["last_rating_changes"] = {}
    room_state["last_rating_detail"] = None
    room_state["last_profile_snapshots"] = {}

    for user in all_players:
        uid = str(user.id)
        entry = get_rating_entry(uid)
        profile = get_player_profile(user.id)

        room_state["last_rating_changes"][uid] = get_user_rating(uid)
        room_state["last_profile_snapshots"][uid] = {
            "win_streak": profile.get("win_streak", 0),
            "active_effect": copy.deepcopy(profile.get("active_effect")),
            "tickets": copy.deepcopy(profile.get("tickets", [])),
            "last_played": profile.get("last_played"),
            "rating": float(entry["rating"]),
            "rd": float(entry["rd"]),
            "volatility": float(entry["volatility"]),
        }

    for user in all_players:
        uid = str(user.id)
        entry = get_rating_entry(uid)
        old_rating = float(entry["rating"])
        old_rd = float(entry["rd"])

        if user.id == member.id:
            new_rating = old_rating - DISCONNECT_PENALTY
        else:
            new_rating = old_rating + DISCONNECT_REWARD

        entry["rating"] = float(new_rating)
        entry["rd"] = float(old_rd)

    save_ratings(ratings)

    all_player_ids = [str(u.id) for u in team_alpha + team_bravo]
    await check_and_update_peak_ranking(guild, all_player_ids)

    room_state["prepared_match"] = make_teams_from_roles(room_state)

    room_state["game_state"] = "finished"
    view = FinishedView(room_key, room_state)
    await update_control_message(guild, room_key, create_finished_text(room_state), view=view)


async def finalize_disconnect_vote(guild, room_key, member, forced_by_confession: bool):
    room_state = room_states[room_key]
    channel = get_progress_channel(guild, room_key)

    if channel:
        if forced_by_confession:
            target_text = build_player_display(member)
            await channel.send(
                f"【回線落ち確定】\n\n<:Confession:1493076810521378866>\n"
                f"{target_text}「ああ俺の回線が悪かった、これは嘘でも否定でもない」"
            )
        else:
            await channel.send(
                "【回線落ち確定】\n\n<:Guilty:1493076857602445485>\n**有罪**\n**没収**"
            )

    await apply_disconnect_rating_change(guild, room_key, member)
    room_state["disconnect_vote"] = None


async def resolve_disconnect_not_established(guild, room_key):
    room_state = room_states[room_key]
    channel = get_progress_channel(guild, room_key)

    room_state["game_state"] = "playing"
    room_state["disconnect_vote"] = None

    if channel:
        await channel.send(
            "【回線落ち不成立】\n有罪票が規定数に達しなかったため、回線落ち処理は行いません。"
        )

    if room_state["current_match"]:
        team_alpha, team_bravo = room_state["current_match"]
        view = PlayingView(room_key, room_state)
        await update_control_message(guild, room_key, create_playing_text(team_alpha, team_bravo), view=view)


async def get_human_members(guild):
    try:
        members = [member async for member in guild.fetch_members(limit=None)]
    except Exception:
        members = guild.members
    return [m for m in members if not m.bot]


# =========================
# バルク処理
# =========================
async def process_badge_bulk_message(message: discord.Message):
    guild = message.guild
    if guild is None:
        return False

    state = badge_bulk_waiting.get(guild.id)
    if not state or state["user_id"] != message.author.id:
        return False

    content = message.content.strip()

    if not content or content in ("キャンセル", "中止", "!キャンセル"):
        badge_bulk_waiting.pop(guild.id, None)
        await message.channel.send("バッジ操作を終了しました" if content else "入力が空だったので終了しました")
        return True

    mode = state["mode"]
    badge_id = state["badge_id"]
    success = []
    errors = []

    for line_no, raw in enumerate(content.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        if not line.isdigit():
            errors.append(f"{line_no}行目: IDが不正 -> {line}")
            continue

        uid = int(line)
        profile = get_player_profile(uid)

        if mode == "grant":
            if badge_id not in profile["owned_badges"]:
                profile["owned_badges"].append(badge_id)
                success.append(f"{uid}")
            else:
                errors.append(f"{line_no}行目: 既に所持 -> {uid}")
        elif mode == "force_grant":
            if badge_id not in profile["owned_badges"]:
                profile["owned_badges"].append(badge_id)
            profile["selected_badge"] = badge_id
            success.append(f"{uid}")
        elif mode == "remove":
            if badge_id in profile["owned_badges"]:
                profile["owned_badges"].remove(badge_id)
                if profile.get("selected_badge") == badge_id:
                    profile["selected_badge"] = None
                success.append(f"{uid}")
            else:
                errors.append(f"{line_no}行目: 未所持 -> {uid}")

    save_player_profiles(player_profiles)
    badge_bulk_waiting.pop(guild.id, None)

    lines = ["【バッジ一括処理結果】"]
    if success:
        lines.append("\n【成功】")
        lines.extend(success)
    if errors:
        lines.append("\n【失敗】")
        lines.extend(errors)

    await message.channel.send("\n".join(lines))
    return True


async def process_bulk_rate_change_message(message: discord.Message):
    guild = message.guild
    if guild is None:
        return False

    waiting_user_id = bulk_rate_change_waiting.get(guild.id)
    if waiting_user_id != message.author.id:
        return False

    content = message.content.strip()
    if not content or content in ("キャンセル", "中止", "!キャンセル", "!中止"):
        bulk_rate_change_waiting.pop(guild.id, None)
        await message.channel.send("レート値変更モードを終了しました。")
        return True

    success_lines = []
    error_lines = []
    changed_any = False

    for line_no, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        parts = line.split()
        if len(parts) != 2:
            error_lines.append(f"{line_no}行目: 形式が違います -> {line}")
            continue

        user_id_text, new_rating_text = parts

        if not user_id_text.isdigit():
            error_lines.append(f"{line_no}行目: ユーザーIDが数字ではありません -> {line}")
            continue

        if not new_rating_text.lstrip("-").isdigit():
            error_lines.append(f"{line_no}行目: レート値が整数ではありません -> {line}")
            continue

        new_rating = int(new_rating_text)
        if new_rating < 0:
            error_lines.append(f"{line_no}行目: レートは0以上にしてください -> {line}")
            continue

        user_id = int(user_id_text)
        old_rating = get_user_rating(user_id)
        set_user_rating(user_id, new_rating)
        name = await get_member_display_name_by_id(guild, user_id)
        success_lines.append(f"{name}: {old_rating} → {new_rating}")
        changed_any = True

    if changed_any:
        save_ratings(ratings)

    bulk_rate_change_waiting.pop(guild.id, None)

    lines = ["【レート値変更結果】"]
    if success_lines:
        lines.extend(["", "【成功】"] + success_lines)
    if error_lines:
        lines.extend(["", "【失敗】"] + error_lines)
    if not success_lines and not error_lines:
        lines.append("有効な入力がありませんでした。")

    text = "\n".join(lines)
    if len(text) <= 1900:
        await message.channel.send(text)
    else:
        chunk = ""
        for line in lines:
            if len(chunk) + len(line) + 1 > 1900:
                await message.channel.send(chunk)
                chunk = line
            else:
                chunk += ("\n" if chunk else "") + line
        if chunk:
            await message.channel.send(chunk)

    return True


async def process_bulk_profile_edit_message(message: discord.Message):
    guild = message.guild
    if guild is None:
        return False

    state = bulk_profile_edit_waiting.get(guild.id)
    if not state or state["user_id"] != message.author.id:
        return False

    content = message.content.strip()

    if not content or content in ("キャンセル", "中止", "!キャンセル", "!中止"):
        bulk_profile_edit_waiting.pop(guild.id, None)
        await message.channel.send("プロフィール一括編集モードを終了しました。")
        return True

    field = state["field"]
    mode = state["mode"]
    success_lines = []
    error_lines = []
    changed_any = False

    for line_no, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        parts = line.split(maxsplit=1)

        if mode == "clear":
            user_id_text = line
            value_text = None
        else:
            if len(parts) != 2:
                error_lines.append(f"{line_no}行目: 形式が違います -> {line}")
                continue
            user_id_text, value_text = parts

        if not user_id_text.isdigit():
            error_lines.append(f"{line_no}行目: ユーザーIDが数字ではありません -> {line}")
            continue

        user_id = int(user_id_text)
        profile = get_player_profile(user_id)
        name = await get_member_display_name_by_id(guild, user_id)

        if field == "weapon":
            old_value = profile.get("weapon")
            profile["weapon"] = None if mode == "clear" else value_text
            success_lines.append(f"{name}: {old_value} → {profile['weapon']}")
            changed_any = True

        elif field == "xp":
            old_value = profile.get("xp")
            if mode == "clear":
                profile["xp"] = None
                success_lines.append(f"{name}: {old_value} → None")
                changed_any = True
            else:
                if not value_text.isdigit():
                    error_lines.append(f"{line_no}行目: XPが整数ではありません -> {line}")
                    continue
                profile["xp"] = int(value_text)
                success_lines.append(f"{name}: {old_value} → {profile['xp']}")
                changed_any = True

        elif field in ("initial_applied", "can_apply_initial_bonus"):
            old_value = profile.get(field)
            profile[field] = (mode == "set_true")
            success_lines.append(f"{name}: {old_value} → {profile[field]}")
            changed_any = True

        elif field == "selected_badge":
            old_value = profile.get("selected_badge")
            if mode == "clear":
                profile["selected_badge"] = None
                success_lines.append(f"{name}: {old_value} → None")
                changed_any = True
            else:
                if value_text not in BADGE_DEFINITIONS:
                    error_lines.append(f"{line_no}行目: 存在しないバッジIDです -> {line}")
                    continue
                if value_text not in profile.get("owned_badges", []):
                    error_lines.append(f"{line_no}行目: そのユーザーはそのバッジを未所持です -> {line}")
                    continue
                profile["selected_badge"] = value_text
                success_lines.append(f"{name}: {old_value} → {value_text}")
                changed_any = True
        else:
            error_lines.append(f"{line_no}行目: 未対応フィールドです -> {field}")

    if changed_any:
        save_player_profiles(player_profiles)

    bulk_profile_edit_waiting.pop(guild.id, None)

    lines = [f"【{field} 一括編集結果】"]
    if success_lines:
        lines.extend(["", "【成功】"] + success_lines)
    if error_lines:
        lines.extend(["", "【失敗】"] + error_lines)
    if not success_lines and not error_lines:
        lines.append("有効な入力がありませんでした。")

    text = "\n".join(lines)
    if len(text) <= 1900:
        await message.channel.send(text)
    else:
        chunk = ""
        for line in lines:
            if len(chunk) + len(line) + 1 > 1900:
                await message.channel.send(chunk)
                chunk = line
            else:
                chunk += ("\n" if chunk else "") + line
        if chunk:
            await message.channel.send(chunk)

    return True


async def process_bulk_admin_message(message: discord.Message):
    guild = message.guild
    if guild is None:
        return False

    waiting_user_id = bulk_admin_waiting.get(guild.id)
    if waiting_user_id != message.author.id:
        return False

    content = message.content.strip()

    if not content or content in ("キャンセル", "中止", "!キャンセル", "!中止"):
        bulk_admin_waiting.pop(guild.id, None)
        await message.channel.send("運営一括モードを終了しました。")
        return True

    success_lines = []
    error_lines = []
    changed_profiles = False
    changed_ratings = False

    for line_no, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        parts = line.split()
        if len(parts) < 2:
            error_lines.append(f"{line_no}行目: 形式が違います -> {line}")
            continue

        user_id_text = parts[0]
        command_name = parts[1]
        args = parts[2:]

        if not user_id_text.isdigit():
            error_lines.append(f"{line_no}行目: ユーザーIDが数字ではありません -> {line}")
            continue

        user_id = int(user_id_text)
        profile = get_player_profile(user_id)

        if command_name == "武器":
            if not args:
                error_lines.append(f"{line_no}行目: 武器名がありません -> {line}")
                continue
            profile["weapon"] = " ".join(args)
            changed_profiles = True
            success_lines.append(line)

        elif command_name == "武器削除":
            profile["weapon"] = None
            changed_profiles = True
            success_lines.append(line)

        elif command_name == "XP":
            if len(args) != 1 or not args[0].isdigit():
                error_lines.append(f"{line_no}行目: XPが不正です -> {line}")
                continue
            profile["xp"] = int(args[0])
            changed_profiles = True
            success_lines.append(line)

        elif command_name == "XP削除":
            profile["xp"] = None
            changed_profiles = True
            success_lines.append(line)

        elif command_name == "バッジ付与":
            if len(args) != 1:
                error_lines.append(f"{line_no}行目: バッジIDを1つ指定してください -> {line}")
                continue
            badge_id = args[0]
            if badge_id not in BADGE_DEFINITIONS:
                error_lines.append(f"{line_no}行目: 存在しないバッジIDです -> {line}")
                continue
            if badge_id not in profile["owned_badges"]:
                profile["owned_badges"].append(badge_id)
            changed_profiles = True
            success_lines.append(line)

        elif command_name == "バッジ削除":
            if len(args) != 1:
                error_lines.append(f"{line_no}行目: バッジIDを1つ指定してください -> {line}")
                continue
            badge_id = args[0]
            if badge_id not in BADGE_DEFINITIONS:
                error_lines.append(f"{line_no}行目: 存在しないバッジIDです -> {line}")
                continue
            if badge_id in profile["owned_badges"]:
                profile["owned_badges"].remove(badge_id)
            if profile.get("selected_badge") == badge_id:
                profile["selected_badge"] = None
            changed_profiles = True
            success_lines.append(line)

        elif command_name == "バッジ強制付与":
            if len(args) != 1:
                error_lines.append(f"{line_no}行目: バッジIDを1つ指定してください -> {line}")
                continue
            badge_id = args[0]
            if badge_id not in BADGE_DEFINITIONS:
                error_lines.append(f"{line_no}行目: 存在しないバッジIDです -> {line}")
                continue
            if badge_id not in profile["owned_badges"]:
                profile["owned_badges"].append(badge_id)
            profile["selected_badge"] = badge_id
            changed_profiles = True
            success_lines.append(line)

        elif command_name == "レート":
            if len(args) != 1 or not args[0].lstrip("-").isdigit():
                error_lines.append(f"{line_no}行目: レート値が不正です -> {line}")
                continue
            new_rating = int(args[0])
            if new_rating < 0:
                error_lines.append(f"{line_no}行目: レートは0以上にしてください -> {line}")
                continue
            set_user_rating(user_id, new_rating)
            changed_ratings = True
            success_lines.append(line)

        elif command_name == "バナー付与":
            if len(args) != 1:
                error_lines.append(f"{line_no}行目: バナーIDを1つ指定してください -> {line}")
                continue
            banner_id = args[0]
            if banner_id not in BANNER_DEFINITIONS:
                error_lines.append(f"{line_no}行目: 存在しないバナーIDです -> {line}")
                continue
            if banner_id not in profile.get("owned_banners", []):
                profile["owned_banners"] = profile.get("owned_banners", []) + [banner_id]
            changed_profiles = True
            success_lines.append(line)

        elif command_name == "バナー削除":
            if len(args) != 1:
                error_lines.append(f"{line_no}行目: バナーIDを1つ指定してください -> {line}")
                continue
            banner_id = args[0]
            owned = profile.get("owned_banners", [])
            if banner_id in owned:
                owned.remove(banner_id)
                profile["owned_banners"] = owned
            if profile.get("selected_banner") == banner_id:
                profile["selected_banner"] = None
            changed_profiles = True
            success_lines.append(line)

        elif command_name == "最高レート":
            if len(args) != 1 or not args[0].lstrip("-").isdigit():
                error_lines.append(f"{line_no}行目: レート値が不正です -> {line}")
                continue
            new_peak = int(args[0])
            if new_peak < 0:
                error_lines.append(f"{line_no}行目: レートは0以上にしてください -> {line}")
                continue
            profile["peak_rating"] = new_peak
            changed_profiles = True
            success_lines.append(line)

        elif command_name == "コイン":
            if len(args) != 1 or not args[0].isdigit():
                error_lines.append(f"{line_no}行目: コイン数が不正です -> {line}")
                continue
            coins = min(int(args[0]), COIN_LIMIT)
            profile["coins"] = coins
            changed_profiles = True
            success_lines.append(f"{user_id} コイン {coins}")

        elif command_name == "チケット付与":
            if not args:
                error_lines.append(f"{line_no}行目: チケットIDがありません -> {line}")
                continue
            for ticket_id in args:
                if ticket_id not in TICKET_DEFINITIONS:
                    error_lines.append(f"{line_no}行目: 存在しないチケットIDです -> {ticket_id}")
                    break
            else:
                tickets = profile.get("tickets", [])
                for ticket_id in args:
                    if len(tickets) >= TICKET_LIMIT:
                        tickets.pop(0)
                    tickets.append(build_ticket_instance(ticket_id))
                profile["tickets"] = tickets
                changed_profiles = True
                success_lines.append(line)
                continue

        else:
            error_lines.append(f"{line_no}行目: 未対応コマンドです -> {command_name}")

    if changed_profiles:
        save_player_profiles(player_profiles)
    if changed_ratings:
        save_ratings(ratings)

    bulk_admin_waiting.pop(guild.id, None)

    lines = ["【運営一括結果】"]
    if success_lines:
        lines.extend(["", "【成功】"] + success_lines)
    if error_lines:
        lines.extend(["", "【失敗】"] + error_lines)
    if not success_lines and not error_lines:
        lines.append("有効な入力がありませんでした。")

    text = "\n".join(lines)
    if len(text) <= 1900:
        await message.channel.send(text)
    else:
        chunk = ""
        for line in lines:
            if len(chunk) + len(line) + 1 > 1900:
                await message.channel.send(chunk)
                chunk = line
            else:
                chunk += ("\n" if chunk else "") + line
        if chunk:
            await message.channel.send(chunk)

    return True


# =========================
# コマンド
# =========================
@bot.event
async def on_ready():
    print(f"ログインしたよ: {bot.user}")
    bot.add_view(HomeView())
    bot.add_view(RateCheckView())
    bot.add_view(RecruitView())
    bot.add_view(RecruitConfirmView())
    bot.add_view(AdminButtonView_Ranking())
    bot.add_view(AdminButtonView_List())
    bot.add_view(AdminButtonView_Badge())
    bot.add_view(AdminButtonView_Rate())
    bot.add_view(AdminButtonView_Bulk())
    bot.add_view(OTPAdminControlView())
    for team_key in get_otp_teams():
        bot.add_view(OTPTeamInputView(team_key))
    daily_coin_distribution.start()
    for guild in bot.guilds:
        await remove_otp_team_channel_summaries(guild)
        await update_otp_team_intros(guild)
        await post_admin_buttons(guild)
        await ensure_otp_admin_control(guild)

@tasks.loop(time=discord.utils.utcnow().replace(hour=10, minute=0, second=0, microsecond=0).timetz())
async def daily_coin_distribution():
    for uid, profile in player_profiles.items():
        coins = profile.get("coins", 0)
        profile["coins"] = min(COIN_LIMIT, coins + 2)
    save_player_profiles(player_profiles)
    print("コイン定時配布完了")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # =========================
    # 他の処理
    # =========================
    for handler in [
        process_badge_bulk_message,
        process_bulk_rate_change_message,
        process_bulk_profile_edit_message,
        process_bulk_admin_message,
        process_otp_demo_bulk_message,
    ]:
        if await handler(message):
            return

    await bot.process_commands(message)


@bot.command(name="やめる")
async def cancel_room(ctx):
    room_key = get_room_key_by_channel_id(ctx.channel.id)
    if room_key is None:
        await ctx.send("このコマンドは試合進行チャンネルで使ってください。")
        return

    room_state = room_states[room_key]

    if room_state["game_state"] == "idle":
        await ctx.send("今は中断する部屋がありません")
        return

    await move_members_to_lobby(ctx.guild, room_key, room_state)
    await delete_control_message(room_state)

    reset_room_state(room_state)
    reset_room_tracking(room_state)

    await ctx.send(f"{room_key}部屋を中断しました")

    # ★ チャンネル削除
    await delete_room_channels(ctx.guild, room_key)


@bot.command(name="回線落ち")
async def disconnect_command(ctx):
    room_key = get_room_key_by_channel_id(ctx.channel.id)
    if room_key is None:
        await ctx.send("このコマンドは試合進行チャンネルで使ってください。")
        return

    room_state = room_states[room_key]

    if room_state["game_state"] != "playing":
        await ctx.send("今は試合中ではありません")
        return

    if not ctx.message.mentions:
        await ctx.send("!回線落ち @ユーザー の形式で送ってください")
        return

    await start_disconnect_vote(ctx.guild, room_key, ctx.message.mentions[0])


@bot.command(name="ランキング")
async def ランキング(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("このコマンドは運営チャンネルで使ってください")
        return
    await post_ranking(ctx.guild)
    await post_peak_ranking(ctx.guild)
    await ctx.send("ランキングを更新しました。")


@bot.command(name="レート確認設置")
async def setup_rate_check(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return

    content = (
        "# 自分のレートを確認\n\n"
        "下のボタンを押すと、現在のレート・順位・最高レート・"
        "直近の試合結果を確認できます。\n\n"
        "表示内容は、ボタンを押した本人にだけ表示されます。"
    )
    await ctx.send(content, view=RateCheckView())


@bot.command(name="秘匿ランキング")
async def secret_ranking(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("このコマンドは運営チャンネルで使ってください")
        return
    await post_secret_ranking(ctx.guild)
    await ctx.send("秘匿ランキングを送信しました。")


@bot.command(name="ホーム更新")
async def update_home_message(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("このコマンドは運営チャンネルで使ってください")
        return
    await post_home_message(ctx.guild)
    await ctx.send("ホームメッセージを更新しました")


@bot.command(name="武器一覧")
async def weapon_list(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("このコマンドは運営チャンネルで使ってください")
        return

    try:
        members = [member async for member in ctx.guild.fetch_members(limit=None)]
    except Exception:
        members = ctx.guild.members

    human_members = sorted([m for m in members if not m.bot], key=lambda m: m.display_name.lower())

    if not human_members:
        await ctx.send("プレイヤーがいません")
        return

    lines = ["【武器一覧】"]
    for member in human_members:
        weapon = get_player_profile(member.id).get("weapon") or "未登録"
        lines.append(f"{member.id} {weapon}")

    text = "\n".join(lines)
    if len(text) <= 1900:
        await ctx.send(text)
    else:
        chunk = ""
        for line in lines:
            if len(chunk) + len(line) + 1 > 1900:
                await ctx.send(chunk)
                chunk = line
            else:
                chunk += ("\n" if chunk else "") + line
        if chunk:
            await ctx.send(chunk)


@bot.command(name="XP一覧")
async def xp_list(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("このコマンドは運営チャンネルで使ってください")
        return

    try:
        members = [member async for member in ctx.guild.fetch_members(limit=None)]
    except Exception:
        members = ctx.guild.members

    human_members = sorted([m for m in members if not m.bot], key=lambda m: m.display_name.lower())

    if not human_members:
        await ctx.send("プレイヤーがいません")
        return

    lines = ["【XP一覧】"]
    for member in human_members:
        xp = get_player_profile(member.id).get("xp")
        lines.append(f"{member.id} {xp if xp is not None else '未登録'}")

    text = "\n".join(lines)
    if len(text) <= 1900:
        await ctx.send(text)
    else:
        chunk = ""
        for line in lines:
            if len(chunk) + len(line) + 1 > 1900:
                await ctx.send(chunk)
                chunk = line
            else:
                chunk += ("\n" if chunk else "") + line
        if chunk:
            await ctx.send(chunk)


@bot.command(name="バッジ付与")
async def grant_badge(ctx, badge_id: str):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("このコマンドは運営チャンネルで使ってください")
        return
    if badge_id not in BADGE_DEFINITIONS:
        await ctx.send("そのバッジIDは存在しません")
        return

    badge_bulk_waiting[ctx.guild.id] = {"mode": "grant", "badge_id": badge_id, "user_id": ctx.author.id}
    await ctx.send(f"バッジ付与モードに入りました（{badge_id}）\nユーザーIDを1行ずつ送ってください。\nキャンセルで終了。")


@bot.command(name="バッジ削除")
async def remove_badge(ctx, badge_id: str):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("このコマンドは運営チャンネルで使ってください")
        return
    if badge_id not in BADGE_DEFINITIONS:
        await ctx.send("そのバッジIDは存在しません")
        return

    badge_bulk_waiting[ctx.guild.id] = {"mode": "remove", "badge_id": badge_id, "user_id": ctx.author.id}
    await ctx.send(f"バッジ削除モードに入りました（{badge_id}）\nユーザーIDを1行ずつ送ってください。\nキャンセルで終了。")


@bot.command(name="バッジ強制付与")
async def force_grant_badge(ctx, badge_id: str):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("このコマンドは運営チャンネルで使ってください")
        return
    if badge_id not in BADGE_DEFINITIONS:
        await ctx.send("そのバッジIDは存在しません")
        return

    badge_bulk_waiting[ctx.guild.id] = {"mode": "force_grant", "badge_id": badge_id, "user_id": ctx.author.id}
    await ctx.send(f"バッジ強制付与モードに入りました（{badge_id}）\nユーザーIDを1行ずつ送ってください。\nキャンセルで終了。")


@bot.command(name="所持バッジ一覧")
async def list_user_badges(ctx, user_id: int):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("このコマンドは運営チャンネルで使ってください")
        return

    profile = get_player_profile(user_id)
    badges = profile.get("owned_badges", [])
    name = await get_member_display_name_by_id(ctx.guild, user_id)

    if not badges:
        await ctx.send(f"{name} はバッジを持っていません")
        return

    lines = [f"{name} の所持バッジ:"]
    for b in badges:
        badge_data = BADGE_DEFINITIONS.get(b, {})
        label = badge_data.get("label", b)
        emoji = badge_data.get("emoji", "")
        lines.append(f"- {emoji} {label} ({b})" if emoji else f"- {label} ({b})")

    await ctx.send("\n".join(lines))


@bot.command(name="バッジ所持者一覧")
async def list_badge_owners(ctx, badge_id: str):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("このコマンドは運営チャンネルで使ってください")
        return
    if badge_id not in BADGE_DEFINITIONS:
        await ctx.send("そのバッジIDは存在しません")
        return

    result = []
    for uid, profile in player_profiles.items():
        if badge_id in profile.get("owned_badges", []):
            name = await get_member_display_name_by_id(ctx.guild, int(uid))
            result.append(name)

    if not result:
        await ctx.send("所持者はいません")
        return

    badge_data = BADGE_DEFINITIONS.get(badge_id, {})
    label = badge_data.get("label", badge_id)
    emoji = badge_data.get("emoji", "")
    title = f"{emoji} {label} ({badge_id}) の所持者:" if emoji else f"{label} ({badge_id}) の所持者:"
    await ctx.send(title + "\n" + "\n".join(result))


@bot.command(name="レート値変更")
async def bulk_change_rate_mode(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("このコマンドは運営チャンネルで使ってください")
        return

    bulk_rate_change_waiting[ctx.guild.id] = ctx.author.id
    await ctx.send(
        "レート値変更モードに入りました。\n"
        "ユーザーID レート値 を1行ずつ送ってください。\nキャンセルで終了。"
    )


@bot.command(name="全員RD設定")
async def set_all_rd(ctx, value: float):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("このコマンドは運営チャンネルで使ってください")
        return

    value = max(RD_MIN, min(RD_MAX, value))
    members = await get_human_members(ctx.guild)
    for member in members:
        get_rating_entry(member.id)["rd"] = float(value)
    save_ratings(ratings)
    await ctx.send(f"全プレイヤーのRDを {value} に設定しました。")


@bot.command(name="全員レートリセット")
async def reset_all_rates(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("このコマンドは運営チャンネルで使ってください")
        return

    members = await get_human_members(ctx.guild)
    for member in members:
        uid = str(member.id)
        ratings[uid] = {"rating": float(DEFAULT_RATING), "rd": DEFAULT_RD, "volatility": DEFAULT_VOLATILITY}
        profile = get_player_profile(member.id)
        profile.update({
            "initial_applied": False, "can_apply_initial_bonus": True,
            "coins": 0, "tickets": [], "active_effect": None,
            "next_coin_at": None, "win_streak": 0, "last_played": None,
        })

    save_ratings(ratings)
    save_player_profiles(player_profiles)
    await post_ranking(ctx.guild)
    await ctx.send(f"全プレイヤーのレートを {DEFAULT_RATING} にリセットしました。")
    await post_home_message(ctx.guild)

    home_channel = get_home_channel(ctx.guild)
    if home_channel:
        await home_channel.send(
            "【シーズン開始】\n武器登録と最高XP登録をしてください。\n"
            "XP補正を反映したい人は、プレイヤー登録ボタンからもう一度登録してくれ。"
        )



@bot.command(name="ホームメッセージ更新")
async def update_home(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("このコマンドは運営チャンネルで使ってください")
        return
    await post_home_message(ctx.guild)
    await ctx.send("ホームメッセージを更新しました")


@bot.command(name="運営一括")
async def bulk_admin_mode(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("このコマンドは運営チャンネルで使ってください")
        return

    bulk_admin_waiting[ctx.guild.id] = ctx.author.id
    await ctx.send(
        "運営一括モードに入りました。\nユーザーID コマンド 内容 を1行ずつ送ってください。\n\n"
        "使えるコマンド:\n武器 / 武器削除 / XP / XP削除\n"
        "バッジ付与 / バッジ削除 / バッジ強制付与\n"
        "レート / 初期補正付与 / 初期補正剥奪\nコイン / チケット付与\n\n"
        "やめるときは キャンセル"
    )


@bot.command(name="ユーザーID一覧")
async def user_id_list(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("このコマンドは運営チャンネルで使ってください")
        return

    try:
        members = [member async for member in ctx.guild.fetch_members(limit=None)]
    except Exception:
        members = ctx.guild.members

    human_members = sorted([m for m in members if not m.bot], key=lambda m: m.display_name.lower())
    if not human_members:
        await ctx.send("プレイヤーがいません")
        return

    lines = ["【ユーザーID一覧】"] + [f"{m.display_name} {m.id}" for m in human_members]
    text = "\n".join(lines)
    if len(text) <= 1900:
        await ctx.send(text)
    else:
        chunk = ""
        for line in lines:
            if len(chunk) + len(line) + 1 > 1900:
                await ctx.send(chunk)
                chunk = line
            else:
                chunk += ("\n" if chunk else "") + line
        if chunk:
            await ctx.send(chunk)


@bot.command(name="OTPデモ設定")
async def otp_demo_setup(ctx, tournament_id: str, category_id: int, admin_channel_id: int, summary_channel_id: int, progress_channel_id: int, operator_role_id: int = 0):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if not isinstance(ctx.guild.get_channel(category_id), discord.CategoryChannel):
        await ctx.send("試験用カテゴリーIDが見つかりません。")
        return
    for ch_id, label in ((admin_channel_id, "運営チャンネル"), (summary_channel_id, "まとめチャンネル"), (progress_channel_id, "公開進行チャンネル")):
        if ctx.guild.get_channel(ch_id) is None:
            await ctx.send(f"{label}が見つかりません。")
            return
    if operator_role_id and ctx.guild.get_role(operator_role_id) is None:
        await ctx.send("運営ロールが見つかりません。")
        return
    tournaments = get_otp_tournaments()
    tournaments[tournament_id] = {
        "id": tournament_id,
        "kind": "demo",
        "guild_id": ctx.guild.id,
        "category_id": category_id,
        "admin_channel_id": admin_channel_id,
        "summary_channel_id": summary_channel_id,
        "progress_channel_id": progress_channel_id,
        "operator_role_id": operator_role_id or None,
        "status": "setup",
        "phase": "setup",
        "paused": False,
        "min_members": 1,
        "max_members": 4,
        "xp_limit": 2700,
        "teams": tournaments.get(tournament_id, {}).get("teams", {}),
        "matches": tournaments.get(tournament_id, {}).get("matches", {}),
        "match_order": tournaments.get(tournament_id, {}).get("match_order", []),
        "blocks": tournaments.get(tournament_id, {}).get("blocks", []),
        "created_at": tournaments.get(tournament_id, {}).get("created_at", time.time()),
        "updated_at": time.time(),
    }
    save_otp_tournaments()
    await ctx.send(
        f"OTPデモ `{tournament_id}` を設定しました。\n"
        "未指定値を本番定数から補完していません。次は `!OTPデモ登録 {tournament_id}` で登録できます。"
    )


@bot.command(name="OTPデモ登録")
async def otp_demo_bulk_register(ctx, tournament_id: str):
    tournaments = get_otp_tournaments()
    tournament = tournaments.get(tournament_id)
    if not tournament:
        await ctx.send("大会IDが見つかりません。先に `!OTPデモ設定` を実行してください。")
        return
    if not otp_demo_is_operator(ctx.author, tournament):
        await ctx.send("この大会の運営のみ実行できます。")
        return
    if tournament.get("status") not in ("setup", "paused"):
        await ctx.send("開始後の一括登録更新は初版の対象外です。")
        return
    otp_demo_bulk_waiting[ctx.guild.id] = {"user_id": ctx.author.id, "tournament_id": tournament_id}
    await ctx.send(
        "OTPデモ一括登録モードに入りました。次の形式で貼り付けてください。キャンセルで終了します。\n\n"
        "申請番号：OTP-001\n"
        "チーム名：テストA\n"
        "役割\tプレイヤー名\t所属\tDiscord ID\t最高XP\t1位ブキ\t2位ブキ\t3位ブキ\t1位ブキ使用率\n"
        "リーダー\tたまき\tKogane\t1225788050894753865\t2680\tスシ\t52ガロン\tわかば\t12.5"
    )


@bot.command(name="OTPデモ承認")
async def otp_demo_approve(ctx, tournament_id: str, application_id: str):
    tournament = get_otp_tournaments().get(tournament_id)
    if not tournament or not otp_demo_is_operator(ctx.author, tournament):
        await ctx.send("大会が見つからないか、権限がありません。")
        return
    key = otp_demo_find_team_by_application(tournament, application_id)
    if not key:
        await ctx.send("対象チームが見つかりません。")
        return
    team = tournament["teams"][key]
    errors = await validate_otp_demo_team(ctx.guild, tournament, team, existing_key=key)
    if errors:
        await ctx.send("承認できません:\n" + "\n".join(errors))
        return
    ready, reason = otp_demo_team_ready({**tournament, "teams": {key: {**team, "status": "approved"}}}, {**team, "status": "approved"})
    if not ready:
        await ctx.send(f"承認できません: {reason}")
        return
    team["status"] = "approved"
    team["approved_by"] = str(ctx.author.id)
    team["approved_at"] = time.time()
    save_otp_tournaments()
    await ctx.send(f"{team['application_id']} {team['team_name']} を承認しました。")


@bot.command(name="OTPデモ棄権")
async def otp_demo_withdraw(ctx, tournament_id: str, application_id: str):
    tournament = get_otp_tournaments().get(tournament_id)
    if not tournament or not otp_demo_is_operator(ctx.author, tournament):
        await ctx.send("大会が見つからないか、権限がありません。")
        return
    if tournament.get("status") == "running":
        await ctx.send("開始後の棄権処理は初版の対象外です。手動保留で試用を中断してください。")
        return
    key = otp_demo_find_team_by_application(tournament, application_id)
    if not key:
        await ctx.send("対象チームが見つかりません。")
        return
    tournament["teams"][key]["status"] = "withdrawn"
    save_otp_tournaments()
    await ctx.send(f"{application_id} を棄権にしました。")


@bot.command(name="OTPデモ状況")
async def otp_demo_status(ctx, tournament_id: str):
    tournament = get_otp_tournaments().get(tournament_id)
    if not tournament:
        await ctx.send("大会IDが見つかりません。")
        return
    text = otp_demo_summary_text(tournament)
    for i in range(0, len(text), 1900):
        await ctx.send(text[i:i + 1900])


@bot.command(name="OTPデモ文面一覧")
async def otp_demo_text_preview(ctx, tournament_id: str, channel_id: int = 0):
    tournament = get_otp_tournaments().get(tournament_id)
    if not tournament or not otp_demo_is_operator(ctx.author, tournament):
        await ctx.send("大会が見つからないか、権限がありません。")
        return
    target_channel = ctx.guild.get_channel(channel_id) if channel_id else ctx.channel
    if target_channel is None:
        await ctx.send("投稿先チャンネルが見つかりません。")
        return
    await ctx.send(f"OTPデモ `{tournament_id}` の文面一覧を {target_channel.mention} に投稿します。")
    await target_channel.send(
        f"【OTPデモ文面一覧｜{tournament_id}】\n"
        "文章確認用のプレビューです。実際の大会状態は変更しません。"
    )
    for title, body in otp_demo_preview_messages(tournament):
        text = f"## {title}\n{body}"
        for i in range(0, len(text), 1900):
            await target_channel.send(text[i:i + 1900])


@bot.command(name="OTP一人テスト作成")
async def otp_solo_test_create(ctx, tournament_id: str):
    tournament = get_otp_tournaments().get(tournament_id)
    if not tournament or not otp_demo_is_operator(ctx.author, tournament):
        await ctx.send("大会が見つからないか、権限がありません。")
        return
    await ctx.send(await start_otp_solo_test(ctx.guild, ctx.author, tournament))


@bot.command(name="OTPデモ操作パネル")
async def otp_demo_control_panel(ctx, tournament_id: str):
    tournament = get_otp_tournaments().get(tournament_id)
    if not tournament or not otp_demo_is_operator(ctx.author, tournament):
        await ctx.send("大会が見つからないか、権限がありません。")
        return
    await ctx.send(
        f"【OTP杯デモ操作｜{tournament_id}】\n"
        "コマンド入力が必要な操作を、このボタンから実行できます。\n"
        "まずは「1人テスト開始」で表示と進行を確認してください。",
        view=OTPDemoControlView(tournament_id),
    )


@bot.command(name="OTPデモ開始確認")
async def otp_demo_start_check(ctx, tournament_id: str):
    tournament = get_otp_tournaments().get(tournament_id)
    if not tournament or not otp_demo_is_operator(ctx.author, tournament):
        await ctx.send("大会が見つからないか、権限がありません。")
        return
    candidates = []
    excluded = []
    for key, team in tournament.get("teams", {}).items():
        ready, reason = otp_demo_team_ready(tournament, team)
        if ready:
            candidates.append(key)
        else:
            excluded.append(f"{team.get('application_id')} {team.get('team_name')}｜{reason}")
    blocks = calculate_otp_demo_blocks(candidates)
    lines = [f"開始対象 {len(candidates)}チーム"]
    lines.extend(f"・{tournament['teams'][key]['application_id']} {tournament['teams'][key]['team_name']}" for key in sorted(candidates, key=lambda k: tournament["teams"][k].get("application_number") or 999999))
    lines.extend(["", "除外対象"])
    lines.extend(excluded or ["なし"])
    lines.extend(["", "予選ブロック構成", "開催不可" if blocks is None else " / ".join(str(len(b)) for b in blocks)])
    lines.append("")
    lines.append(f"開始する場合は `!OTPデモ開始 {tournament_id} 確定` を実行してください。")
    await ctx.send("\n".join(lines))


@bot.command(name="OTPデモ開始")
async def otp_demo_start(ctx, tournament_id: str, confirm: str = ""):
    tournament = get_otp_tournaments().get(tournament_id)
    if not tournament or not otp_demo_is_operator(ctx.author, tournament):
        await ctx.send("大会が見つからないか、権限がありません。")
        return
    if confirm != "確定":
        await ctx.send(f"先に `!OTPデモ開始確認 {tournament_id}` を確認し、開始する場合は `!OTPデモ開始 {tournament_id} 確定` と送ってください。")
        return
    if tournament.get("status") not in ("setup", "paused"):
        await ctx.send("この大会は開始可能な状態ではありません。")
        return
    candidates = [key for key, team in tournament.get("teams", {}).items() if otp_demo_team_ready(tournament, team)[0]]
    blocks = calculate_otp_demo_blocks(candidates)
    if blocks is None:
        await ctx.send("このチーム数では大会を開催できません。登録は継続できます。")
        return
    rr = make_round_robin_matches(blocks)
    tournament.update({
        "status": "running",
        "phase": "qualifier",
        "paused": False,
        "started_at": time.time(),
        "started_by": str(ctx.author.id),
        "eligible_team_keys": candidates,
        "blocks": blocks,
        "matches": rr["matches"],
        "match_order": rr["order"],
        "brackets": {},
    })
    save_otp_tournaments()
    await ctx.send(f"OTPデモ `{tournament_id}` を開始しました。予選ブロック: " + " / ".join(str(len(b)) for b in blocks))
    await otp_demo_start_waiting_matches(ctx.guild, tournament)


@bot.command(name="OTP勝ち")
async def otp_demo_report_win(ctx, tournament_id: str, match_id: str, winner_application_id: str):
    tournament = get_otp_tournaments().get(tournament_id)
    if not tournament:
        await ctx.send("大会IDが見つかりません。")
        return
    match = tournament.get("matches", {}).get(match_id)
    if not match or match.get("status") not in ("active", "disputed"):
        await ctx.send("報告可能な対戦が見つかりません。")
        return
    winner_key = otp_demo_find_team_by_application(tournament, winner_application_id)
    if winner_key not in match.get("teams", []):
        await ctx.send("勝者はこの対戦のチームから指定してください。")
        return
    reporter_team = None
    for team_key in match["teams"]:
        if otp_demo_get_leader_id(tournament["teams"][team_key]) == str(ctx.author.id):
            reporter_team = team_key
            break
    if reporter_team is None:
        await ctx.send("この対戦の登録リーダーだけが報告できます。")
        return
    if match.get("status") == "hold":
        await ctx.send("この対戦は保留中です。参加者入力では解除できません。")
        return
    reports = match.setdefault("reports", {})
    reports[reporter_team] = {"winner": winner_key, "reporter_id": str(ctx.author.id), "generation": match.get("report_generation", 1), "reported_at": time.time()}
    if len(reports) < 2:
        save_otp_tournaments()
        await ctx.send("片側の報告を受け付けました。もう一方のリーダー報告を待っています。")
        return
    winners = {r["winner"] for r in reports.values()}
    if len(winners) == 1:
        otp_demo_record_battle_result(tournament, match, winner_key, "leaders", ctx.author.id)
        maybe_finish_qualifiers_and_build_brackets(tournament)
        save_otp_tournaments()
        await ctx.send(f"{match_id} {winner_application_id} 勝ちで確定しました。")
        await otp_demo_after_match_progress(ctx.guild, tournament, match)
        return
    mismatch_count = match.get("mismatch_count", 0) + 1
    match["mismatch_count"] = mismatch_count
    match["reports"] = {}
    match["report_generation"] = match.get("report_generation", 1) + 1
    match["status"] = "disputed" if mismatch_count < 2 else "hold"
    save_otp_tournaments()
    if mismatch_count < 2:
        await ctx.send(f"{match_id} の報告が不一致でした。双方の新しい回答だけで再入力してください。")
    else:
        await ctx.send(f"{match_id} は再不一致のため運営裁定待ちです。`!OTP裁定 {tournament_id} {match_id} 勝者申請番号` で確定してください。")


@bot.command(name="OTP一人勝ち")
async def otp_solo_test_win(ctx, tournament_id: str, match_id: str, winner_application_id: str):
    tournament = get_otp_tournaments().get(tournament_id)
    if not tournament or not otp_demo_is_operator(ctx.author, tournament):
        await ctx.send("大会が見つからないか、権限がありません。")
        return
    if not tournament.get("solo_test_mode"):
        await ctx.send("このコマンドは1人テストモード専用です。通常デモでは `!OTP勝ち` または `!OTP裁定` を使ってください。")
        return
    match = tournament.get("matches", {}).get(match_id)
    winner_key = otp_demo_find_team_by_application(tournament, winner_application_id)
    if not match or match.get("status") not in ("active", "disputed", "hold"):
        await ctx.send("報告可能な対戦が見つかりません。")
        return
    if winner_key not in match.get("teams", []):
        await ctx.send("勝者はこの対戦のチームから指定してください。")
        return
    otp_demo_record_battle_result(tournament, match, winner_key, "solo_test_operator", ctx.author.id)
    maybe_finish_qualifiers_and_build_brackets(tournament)
    save_otp_tournaments()
    await ctx.send(
        f"{match_id} {winner_application_id} 勝ちで1人テスト確定しました。\n"
        "通常版では、両チームリーダーの報告一致または運営裁定で確定します。"
    )
    await otp_demo_after_match_progress(ctx.guild, tournament, match)


@bot.command(name="OTP裁定")
async def otp_demo_judge(ctx, tournament_id: str, match_id: str, winner_application_id: str):
    tournament = get_otp_tournaments().get(tournament_id)
    if not tournament or not otp_demo_is_operator(ctx.author, tournament):
        await ctx.send("大会が見つからないか、権限がありません。")
        return
    match = tournament.get("matches", {}).get(match_id)
    winner_key = otp_demo_find_team_by_application(tournament, winner_application_id)
    if not match or winner_key not in match.get("teams", []):
        await ctx.send("対象対戦または勝者指定が不正です。")
        return
    if match.get("status") == "done":
        await ctx.send("確定済み対戦の巻き戻しは初版の対象外です。")
        return
    otp_demo_record_battle_result(tournament, match, winner_key, "operator", ctx.author.id)
    maybe_finish_qualifiers_and_build_brackets(tournament)
    save_otp_tournaments()
    await ctx.send(f"{match_id} を運営裁定で確定しました。")
    await otp_demo_after_match_progress(ctx.guild, tournament, match)


@bot.command(name="OTP保留")
async def otp_demo_hold(ctx, tournament_id: str, match_id: str, *, reason: str = ""):
    tournament = get_otp_tournaments().get(tournament_id)
    if not tournament or not otp_demo_is_operator(ctx.author, tournament):
        await ctx.send("大会が見つからないか、権限がありません。")
        return
    match = tournament.get("matches", {}).get(match_id)
    if not match or match.get("status") == "done":
        await ctx.send("保留できる対戦が見つかりません。")
        return
    match["status"] = "hold"
    match.setdefault("holds", []).append({"operator_id": str(ctx.author.id), "reason": reason or "理由未記入", "held_at": time.time()})
    save_otp_tournaments()
    await ctx.send(f"{match_id} を保留しました。参加者入力では解除されません。")


@bot.command(name="OTP保留解除")
async def otp_demo_unhold(ctx, tournament_id: str, match_id: str):
    tournament = get_otp_tournaments().get(tournament_id)
    if not tournament or not otp_demo_is_operator(ctx.author, tournament):
        await ctx.send("大会が見つからないか、権限がありません。")
        return
    match = tournament.get("matches", {}).get(match_id)
    if not match or match.get("status") != "hold":
        await ctx.send("保留中の対戦が見つかりません。")
        return
    match["status"] = "active"
    match.setdefault("holds", []).append({"operator_id": str(ctx.author.id), "reason": "保留解除", "resumed_at": time.time()})
    save_otp_tournaments()
    await ctx.send(f"{match_id} の保留を解除しました。")


@bot.command(name="OTPデモ一時停止")
async def otp_demo_pause(ctx, tournament_id: str):
    tournament = get_otp_tournaments().get(tournament_id)
    if not tournament or not otp_demo_is_operator(ctx.author, tournament):
        await ctx.send("大会が見つからないか、権限がありません。")
        return
    tournament["paused"] = True
    tournament["paused_at"] = time.time()
    save_otp_tournaments()
    await ctx.send("一時停止しました。新たな対戦開始は行いません。")


@bot.command(name="OTPデモ再開")
async def otp_demo_resume(ctx, tournament_id: str):
    tournament = get_otp_tournaments().get(tournament_id)
    if not tournament or not otp_demo_is_operator(ctx.author, tournament):
        await ctx.send("大会が見つからないか、権限がありません。")
        return
    tournament["paused"] = False
    tournament["resumed_at"] = time.time()
    save_otp_tournaments()
    await ctx.send("再開しました。")
    await otp_demo_start_waiting_matches(ctx.guild, tournament)


@bot.command(name="OTPデモ終了")
async def otp_demo_finish(ctx, tournament_id: str):
    tournament = get_otp_tournaments().get(tournament_id)
    if not tournament or not otp_demo_is_operator(ctx.author, tournament):
        await ctx.send("大会が見つからないか、権限がありません。")
        return
    await otp_demo_delete_all_match_channels(ctx.guild, tournament)
    tournament["status"] = "done"
    tournament["finished_at"] = time.time()
    tournament["finished_by"] = str(ctx.author.id)
    save_otp_tournaments()
    await ctx.send("OTPデモを終了扱いにしました。対応する対戦チャンネルは削除しました。記録は bot_state.json に保持されています。")


async def dump_admin_list(ctx, lines):
    if not lines:
        await ctx.send("出力対象がありません")
        return
    text = "\n".join(lines)
    if len(text) <= 1900:
        await ctx.send(text)
    else:
        chunk = ""
        for line in lines:
            if len(chunk) + len(line) + 1 > 1900:
                await ctx.send(chunk)
                chunk = line
            else:
                chunk += ("\n" if chunk else "") + line
        if chunk:
            await ctx.send(chunk)


@bot.command(name="運営一覧1")
async def admin_dump_1(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("このコマンドは運営チャンネルで使ってください")
        return

    try:
        members = [member async for member in ctx.guild.fetch_members(limit=None)]
    except Exception:
        members = ctx.guild.members

    human_members = sorted([m for m in members if not m.bot], key=lambda m: m.display_name.lower())
    lines = []
    for member in human_members:
        uid = str(member.id)
        profile = get_player_profile(member.id)
        if profile.get("weapon"):
            lines.append(f"{uid} 武器 {profile['weapon']}")
        if profile.get("xp") is not None:
            lines.append(f"{uid} XP {profile['xp']}")

    await dump_admin_list(ctx, lines)


@bot.command(name="運営一覧2")
async def admin_dump_2(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("このコマンドは運営チャンネルで使ってください")
        return

    try:
        members = [member async for member in ctx.guild.fetch_members(limit=None)]
    except Exception:
        members = ctx.guild.members

    human_members = sorted([m for m in members if not m.bot], key=lambda m: m.display_name.lower())
    lines = []
    for member in human_members:
        uid = str(member.id)
        for badge_id in get_player_profile(member.id).get("owned_badges", []):
            lines.append(f"{uid} バッジ付与 {badge_id}")

    await dump_admin_list(ctx, lines)


@bot.command(name="運営一覧3")
async def admin_dump_3(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("このコマンドは運営チャンネルで使ってください")
        return

    try:
        members = [member async for member in ctx.guild.fetch_members(limit=None)]
    except Exception:
        members = ctx.guild.members

    human_members = sorted([m for m in members if not m.bot], key=lambda m: m.display_name.lower())
    lines = []
    for member in human_members:
        uid = str(member.id)
        selected = get_player_profile(member.id).get("selected_badge")
        if selected:
            lines.append(f"{uid} バッジ強制付与 {selected}")

    await dump_admin_list(ctx, lines)


@bot.command(name="運営一覧4")
async def admin_dump_4(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("このコマンドは運営チャンネルで使ってください")
        return

    try:
        members = [member async for member in ctx.guild.fetch_members(limit=None)]
    except Exception:
        members = ctx.guild.members

    human_members = sorted([m for m in members if not m.bot], key=lambda m: m.display_name.lower())
    lines = [f"{str(m.id)} コイン {get_player_profile(m.id).get('coins', 0)}" for m in human_members]
    await dump_admin_list(ctx, lines)


@bot.command(name="運営一覧5")
async def admin_dump_5(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("このコマンドは運営チャンネルで使ってください")
        return

    try:
        members = [member async for member in ctx.guild.fetch_members(limit=None)]
    except Exception:
        members = ctx.guild.members

    human_members = sorted([m for m in members if not m.bot], key=lambda m: m.display_name.lower())
    lines = []
    for member in human_members:
        uid = str(member.id)
        profile = get_player_profile(member.id)
        ticket_ids = [t.get("ticket_id") for t in profile.get("tickets", []) if t.get("ticket_id")]
        ae = profile.get("active_effect")
        if ae and ae.get("ticket_id"):
            ticket_ids.append(ae.get("ticket_id"))
        if ticket_ids:
            lines.append(f"{uid} チケット付与 " + " ".join(ticket_ids))

    await dump_admin_list(ctx, lines)


@bot.command(name="運営一覧6")
async def admin_dump_6(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("このコマンドは運営チャンネルで使ってください")
        return

    try:
        members = [member async for member in ctx.guild.fetch_members(limit=None)]
    except Exception:
        members = ctx.guild.members

    human_members = sorted([m for m in members if not m.bot], key=lambda m: m.display_name.lower())
    lines = [f"{str(m.id)} レート {get_user_rating(m.id)}" for m in human_members]
    await dump_admin_list(ctx, lines)

@bot.command(name="運営一覧7")
async def admin_dump_7(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("このコマンドは運営チャンネルで使ってください")
        return

    try:
        members = [member async for member in ctx.guild.fetch_members(limit=None)]
    except Exception:
        members = ctx.guild.members

    human_members = sorted([m for m in members if not m.bot], key=lambda m: m.display_name.lower())
    lines = [f"{str(m.id)} 最高レート {get_peak_rating(m.id)}" for m in human_members]
    await dump_admin_list(ctx, lines)
    
@bot.command(name="名前更新")
async def update_display_names(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("このコマンドは運営チャンネルで使ってください")
        return

    try:
        members = [member async for member in ctx.guild.fetch_members(limit=None)]
    except Exception:
        members = ctx.guild.members

    count = 0
    for member in members:
        if member.bot:
            continue
        profile = get_player_profile(member.id)
        profile["display_name"] = member.display_name
        count += 1

    save_player_profiles(player_profiles)
    await ctx.send(f"{count}人の名前を更新しました！")

@bot.command(name="アバター更新")
async def update_avatars(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("このコマンドは運営チャンネルで使ってください")
        return

    try:
        members = [member async for member in ctx.guild.fetch_members(limit=None)]
    except Exception:
        members = ctx.guild.members

    count = 0
    for member in members:
        if member.bot:
            continue
        profile = get_player_profile(member.id)
        profile["avatar_url"] = str(member.display_avatar.url)
        count += 1

    save_player_profiles(player_profiles)
    await ctx.send(f"{count}人のアバターを更新しました！")


def make_avatar_archive(entries):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as zip_file:
        manifest = io.StringIO(newline="")
        writer = csv.writer(manifest)
        writer.writerow(["display_name", "discord_user_id", "filename"])

        for entry in entries:
            zip_file.writestr(entry["filename"], entry["data"])
            writer.writerow([entry["display_name"], entry["user_id"], entry["filename"]])

        zip_file.writestr("members.csv", "\ufeff" + manifest.getvalue())

    archive.seek(0)
    return archive


@bot.command(name="アイコン書き出し")
async def export_member_avatars(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("このコマンドは運営チャンネルで使ってください")
        return

    status_message = await ctx.send("在籍メンバーを取得しています。完了まで少し待ってください。")

    try:
        members = [member async for member in ctx.guild.fetch_members(limit=None)]
    except Exception as exc:
        await status_message.edit(
            content=(
                "メンバー一覧を取得できませんでした。"
                "Discord Developer PortalのServer Members IntentとBotの権限を確認してください。\n"
                f"エラー: {type(exc).__name__}"
            )
        )
        return

    human_members = sorted(
        [member for member in members if not member.bot],
        key=lambda member: (member.display_name.casefold(), member.id),
    )
    if not human_members:
        await status_message.edit(content="書き出し対象のメンバーが見つかりませんでした。")
        return

    # PNGはすでに圧縮済みなので、ZIPの容量を予測しやすいよう無圧縮で格納する。
    upload_limit = int(getattr(ctx.guild, "filesize_limit", 10 * 1024 * 1024))
    archive_target_size = max(1024 * 1024, upload_limit - 512 * 1024)
    chunks = []
    current_chunk = []
    current_size = 0
    failed_members = []

    for index, member in enumerate(human_members, start=1):
        try:
            avatar = member.display_avatar.replace(size=512, format="png")
            avatar_data = await avatar.read()
        except Exception:
            failed_members.append(f"{member.display_name} ({member.id})")
            continue

        safe_name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", member.display_name).strip(" .")
        if not safe_name:
            safe_name = "user"
        filename = f"{safe_name}_{member.id}.png"
        entry = {
            "display_name": member.display_name,
            "user_id": str(member.id),
            "filename": filename,
            "data": avatar_data,
        }

        estimated_size = len(avatar_data) + len(filename.encode("utf-8")) + 2048
        if current_chunk and current_size + estimated_size > archive_target_size:
            chunks.append(current_chunk)
            current_chunk = []
            current_size = 0
        current_chunk.append(entry)
        current_size += estimated_size

        if index % 25 == 0:
            await status_message.edit(
                content=f"アイコンを取得しています。{index}/{len(human_members)}人"
            )

    if current_chunk:
        chunks.append(current_chunk)

    if not chunks:
        await status_message.edit(content="アイコンを1件も取得できませんでした。")
        return

    archives = [make_avatar_archive(chunk) for chunk in chunks]
    total_exported = sum(len(chunk) for chunk in chunks)
    await status_message.edit(
        content=(
            f"{total_exported}人分のアイコンを取得しました。"
            f"ZIPファイルを{len(archives)}個送信します。"
        )
    )

    for index, archive in enumerate(archives, start=1):
        filename = f"kogane_member_icons_{index:02d}.zip"
        await ctx.send(
            f"アイコン書き出し {index}/{len(archives)}",
            file=discord.File(archive, filename=filename),
        )

    result = f"完了しました。成功: {total_exported}人 / 失敗: {len(failed_members)}人"
    if failed_members:
        shown = failed_members[:20]
        result += "\n取得失敗:\n" + "\n".join(shown)
        if len(failed_members) > len(shown):
            result += f"\nほか{len(failed_members) - len(shown)}人"
    await ctx.send(result)
    
@bot.command(name="最高レート初期化")
async def init_peak_rating(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("このコマンドは運営チャンネルで使ってください")
        return

    count = 0
    for uid, profile in player_profiles.items():
        if profile.get("peak_rating") is None:
            current = get_user_rating(uid)
            profile["peak_rating"] = current
            count += 1

    save_player_profiles(player_profiles)
    await ctx.send(f"{count}人の最高レートを現在のレートで初期化しました！")

@bot.command(name="botアイコン")
async def bot_icon(ctx):
    if ctx.author.id != OWNER_ID:
        return
    bot_user = bot.user
    if bot_user.avatar:
        await ctx.send(str(bot_user.avatar.url))
    else:
        await ctx.send("アイコンが設定されていません")

# =========================
# 起動
# =========================
import threading
import uuid
import uvicorn
from fastapi import FastAPI, Request, File, UploadFile, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

api = FastAPI()


@api.post("/api/otp/form-submission")
async def otp_form_submission(request: Request):
    """Google Apps Script からのフォーム回答受信口。認証キー必須。"""
    if not OTP_FORM_WEBHOOK_SECRET:
        return JSONResponse(content={"error": "webhook is not configured"}, status_code=503)
    payload = await request.json()
    if payload.get("secret") != OTP_FORM_WEBHOOK_SECRET:
        return JSONResponse(content={"error": "unauthorized"}, status_code=401)
    if not bot.is_ready():
        return JSONResponse(content={"error": "bot is not ready"}, status_code=503)
    required = ("leader_name", "x_id", "member_names", "enthusiasm")
    if not all(key in payload for key in required) or len(payload.get("member_names", [])) != 3:
        return JSONResponse(content={"error": "invalid payload"}, status_code=400)
    future = asyncio.run_coroutine_threadsafe(create_otp_team_from_form(payload), bot.loop)
    try:
        team = await asyncio.wrap_future(future)
    except Exception as exc:
        print(f"OTP杯フォーム処理エラー: {exc}")
        return JSONResponse(content={"error": "failed to create team"}, status_code=500)
    return JSONResponse(content={"success": True, "team_number": team["number"]})

# =========================
# 画像アップロード（バッジ・バナー用）
# =========================
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
# "/" の catch-all マウント（このファイル末尾）より前に登録する必要がある
api.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
ALLOWED_IMAGE_CONTENT_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
MAX_UPLOAD_SIZE_BYTES = 5 * 1024 * 1024  # 5MB

@api.post("/api/upload_image")
async def upload_image(user_id: str = Form(...), file: UploadFile = File(...)):
    """バッジ・バナー用の画像をアップロードする（OWNER_IDのみ）"""
    if user_id != str(OWNER_ID):
        return JSONResponse(content={"error": "権限がありません"}, status_code=403)

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS or file.content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        return JSONResponse(content={"error": "対応していない画像形式です（png/jpg/jpeg/gif/webpのみ）"}, status_code=400)

    data = await file.read()
    if len(data) > MAX_UPLOAD_SIZE_BYTES:
        return JSONResponse(content={"error": "ファイルサイズが大きすぎます（5MBまで）"}, status_code=400)
    if not data:
        return JSONResponse(content={"error": "ファイルが空です"}, status_code=400)

    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(data)

    return JSONResponse(content={"success": True, "url": f"/uploads/{filename}"})


# =========================
# Web用バッジ・バナー定義（/data/に保存）
# =========================
# 以下をbot.pyのFastAPI部分（@api.get("/api/health") の直前あたり）に追加してください

WEB_BADGE_FILE = os.path.join(DATA_DIR, "web_badge_definitions.json")
WEB_BANNER_FILE = os.path.join(DATA_DIR, "web_banner_definitions.json")

def load_web_badges():
    try:
        with open(WEB_BADGE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_web_badges(data):
    with open(WEB_BADGE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_web_banners():
    try:
        with open(WEB_BANNER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_web_banners(data):
    with open(WEB_BANNER_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# =========================
# バッジ CRUD API
# =========================

@api.get("/api/web_badges")
def get_web_badges():
    return JSONResponse(content={"badges": load_web_badges()})

@api.post("/api/web_badges")
async def create_web_badge(request: Request):
    body = await request.json()
    user_id = body.get("user_id")
    if user_id != str(OWNER_ID):
        return JSONResponse(content={"error": "権限がありません"}, status_code=403)

    label = body.get("label", "").strip()
    image_url = body.get("image_url", "").strip()

    if not label:
        return JSONResponse(content={"error": "ラベルは必須です"}, status_code=400)

    badges = load_web_badges()
    import uuid
    new_badge = {
        "id": str(uuid.uuid4())[:8],
        "label": label,
        "image_url": image_url,
    }
    badges.append(new_badge)
    save_web_badges(badges)
    return JSONResponse(content={"success": True, "badge": new_badge})

@api.put("/api/web_badges/{badge_id}")
async def update_web_badge(badge_id: str, request: Request):
    body = await request.json()
    user_id = body.get("user_id")
    if user_id != str(OWNER_ID):
        return JSONResponse(content={"error": "権限がありません"}, status_code=403)

    badges = load_web_badges()
    for badge in badges:
        if badge["id"] == badge_id:
            badge["label"] = body.get("label", badge["label"]).strip()
            badge["image_url"] = body.get("image_url", badge["image_url"]).strip()
            save_web_badges(badges)
            return JSONResponse(content={"success": True, "badge": badge})

    return JSONResponse(content={"error": "バッジが見つかりません"}, status_code=404)

@api.delete("/api/web_badges/{badge_id}")
async def delete_web_badge(badge_id: str, request: Request):
    body = await request.json()
    user_id = body.get("user_id")
    if user_id != str(OWNER_ID):
        return JSONResponse(content={"error": "権限がありません"}, status_code=403)

    badges = load_web_badges()
    new_badges = [b for b in badges if b["id"] != badge_id]
    if len(new_badges) == len(badges):
        return JSONResponse(content={"error": "バッジが見つかりません"}, status_code=404)

    save_web_badges(new_badges)
    return JSONResponse(content={"success": True})


# =========================
# バナー CRUD API
# =========================

@api.get("/api/web_banners")
def get_web_banners():
    return JSONResponse(content={"banners": load_web_banners()})

@api.post("/api/web_banners")
async def create_web_banner(request: Request):
    body = await request.json()
    user_id = body.get("user_id")
    if user_id != str(OWNER_ID):
        return JSONResponse(content={"error": "権限がありません"}, status_code=403)

    label = body.get("label", "").strip()
    image_url = body.get("image_url", "").strip()

    if not label:
        return JSONResponse(content={"error": "ラベルは必須です"}, status_code=400)

    banners = load_web_banners()
    import uuid
    new_banner = {
        "id": str(uuid.uuid4())[:8],
        "label": label,
        "image_url": image_url,
    }
    banners.append(new_banner)
    save_web_banners(banners)
    return JSONResponse(content={"success": True, "banner": new_banner})

@api.put("/api/web_banners/{banner_id}")
async def update_web_banner(banner_id: str, request: Request):
    body = await request.json()
    user_id = body.get("user_id")
    if user_id != str(OWNER_ID):
        return JSONResponse(content={"error": "権限がありません"}, status_code=403)

    banners = load_web_banners()
    for banner in banners:
        if banner["id"] == banner_id:
            banner["label"] = body.get("label", banner["label"]).strip()
            banner["image_url"] = body.get("image_url", banner["image_url"]).strip()
            save_web_banners(banners)
            return JSONResponse(content={"success": True, "banner": banner})

    return JSONResponse(content={"error": "バナーが見つかりません"}, status_code=404)

@api.delete("/api/web_banners/{banner_id}")
async def delete_web_banner(banner_id: str, request: Request):
    body = await request.json()
    user_id = body.get("user_id")
    if user_id != str(OWNER_ID):
        return JSONResponse(content={"error": "権限がありません"}, status_code=403)

    banners = load_web_banners()
    new_banners = [b for b in banners if b["id"] != banner_id]
    if len(new_banners) == len(banners):
        return JSONResponse(content={"error": "バナーが見つかりません"}, status_code=404)

    save_web_banners(new_banners)
    return JSONResponse(content={"success": True})


# =========================
# プレイヤーへのバッジ・バナー付与 API
# =========================

@api.post("/api/web_badge/grant")
async def grant_web_badge(request: Request):
    """プレイヤーにWebバッジを付与する"""
    body = await request.json()
    user_id = body.get("user_id")      # 付与する側（管理者）
    target_id = body.get("target_id")  # 付与される側のユーザーID
    badge_id = body.get("badge_id")

    if user_id != str(OWNER_ID):
        return JSONResponse(content={"error": "権限がありません"}, status_code=403)

    badges = load_web_badges()
    badge_ids = [b["id"] for b in badges]
    if badge_id not in badge_ids:
        return JSONResponse(content={"error": "バッジが存在しません"}, status_code=404)

    profile = get_player_profile(int(target_id))
    owned = profile.get("owned_web_badges", [])
    if badge_id not in owned:
        owned.append(badge_id)
        profile["owned_web_badges"] = owned
        save_player_profiles(player_profiles)

    return JSONResponse(content={"success": True})

@api.post("/api/web_banner/grant")
async def grant_web_banner(request: Request):
    """プレイヤーにWebバナーを付与する"""
    body = await request.json()
    user_id = body.get("user_id")
    target_id = body.get("target_id")
    banner_id = body.get("banner_id")

    if user_id != str(OWNER_ID):
        return JSONResponse(content={"error": "権限がありません"}, status_code=403)

    banners = load_web_banners()
    banner_ids = [b["id"] for b in banners]
    if banner_id not in banner_ids:
        return JSONResponse(content={"error": "バナーが存在しません"}, status_code=404)

    profile = get_player_profile(int(target_id))
    owned = profile.get("owned_web_banners", [])
    if banner_id not in owned:
        owned.append(banner_id)
        profile["owned_web_banners"] = owned
        save_player_profiles(player_profiles)

    return JSONResponse(content={"success": True})

@api.post("/api/web_badge/set")
async def set_web_badge(request: Request):
    """プレイヤーが自分のWebバッジを設定する"""
    body = await request.json()
    user_id = body.get("user_id")
    badge_id = body.get("badge_id")  # Noneまたは空文字で解除

    if not user_id:
        return JSONResponse(content={"error": "user_id is required"}, status_code=400)

    profile = get_player_profile(int(user_id))

    if not badge_id:
        profile["selected_web_badge"] = None
    else:
        owned = profile.get("owned_web_badges", [])
        if badge_id not in owned:
            return JSONResponse(content={"error": "そのバッジは所持していません"}, status_code=403)
        profile["selected_web_badge"] = badge_id

    save_player_profiles(player_profiles)
    return JSONResponse(content={"success": True})

@api.post("/api/web_banner/set")
async def set_web_banner(request: Request):
    """プレイヤーが自分のWebバナーを設定する"""
    body = await request.json()
    user_id = body.get("user_id")
    banner_id = body.get("banner_id")

    if not user_id:
        return JSONResponse(content={"error": "user_id is required"}, status_code=400)

    profile = get_player_profile(int(user_id))

    if not banner_id:
        profile["selected_web_banner"] = None
    else:
        owned = profile.get("owned_web_banners", [])
        if banner_id not in owned:
            return JSONResponse(content={"error": "そのバナーは所持していません"}, status_code=403)
        profile["selected_web_banner"] = banner_id

    save_player_profiles(player_profiles)
    return JSONResponse(content={"success": True})

@api.get("/api/health")
def health():
    return JSONResponse(content={"status": "ok"}, media_type="application/json; charset=utf-8")

def resolve_web_badge_banner(profile: dict, web_badges: dict, web_banners: dict) -> tuple:
    """プロフィールのselected_web_badge/selected_web_bannerを画像URLに解決する"""
    badge_def = web_badges.get(profile.get("selected_web_badge"))
    banner_def = web_banners.get(profile.get("selected_web_banner"))

    badge_url = badge_def["image_url"] if badge_def else None
    banner_url = banner_def["image_url"] if banner_def else None
    return badge_url, banner_url


@api.get("/api/ranking")
def get_ranking():
    ratings_data = load_ratings()
    profiles = load_player_profiles()
    web_badges = {b["id"]: b for b in load_web_badges()}
    web_banners = {b["id"]: b for b in load_web_banners()}

    players = []
    for uid, data in ratings_data.items():
        if isinstance(data, dict):
            rating = int(round(data.get("rating", DEFAULT_RATING)))
        else:
            rating = int(round(float(data)))

        profile = profiles.get(uid, {})
        badge_url, banner_url = resolve_web_badge_banner(profile, web_badges, web_banners)
        players.append({
            "user_id": uid,
            "rating": rating,
            "display_name": profile.get("display_name"),
            "peak_rating": profile.get("peak_rating"),
            "avatar_url": profile.get("avatar_url") or "https://cdn.discordapp.com/embed/avatars/0.png",
            "selected_badge_url": badge_url,
            "selected_banner_url": banner_url,
        })

    players.sort(key=lambda x: -x["rating"])
    for i, p in enumerate(players):
        p["rank"] = i + 1

    return JSONResponse(content={"players": players}, media_type="application/json; charset=utf-8")

@api.get("/api/peak_ranking")
def get_peak_ranking():
    profiles = load_player_profiles()
    web_badges = {b["id"]: b for b in load_web_badges()}
    web_banners = {b["id"]: b for b in load_web_banners()}

    players = []
    for uid, profile in profiles.items():
        peak = profile.get("peak_rating")
        if peak is None:
            continue
        badge_url, banner_url = resolve_web_badge_banner(profile, web_badges, web_banners)
        players.append({
            "user_id": uid,
            "display_name": profile.get("display_name") or uid,
            "peak_rating": peak,
            "avatar_url": profile.get("avatar_url") or "https://cdn.discordapp.com/embed/avatars/0.png",
            "selected_badge_url": badge_url,
            "selected_banner_url": banner_url,
        })

    players.sort(key=lambda x: -x["peak_rating"])
    for i, p in enumerate(players):
        p["rank"] = i + 1

    return JSONResponse(content={"players": players}, media_type="application/json; charset=utf-8")

def calc_play_type(user_id: str, history: list, all_profiles: dict):
    """勝利試合のみを参照してプレイタイプを判定（サーバー内相対比較）"""

    # 全プレイヤーの勝利試合統計を集計
    server_stats = {}
    for match in history:
        winner = match.get("winner")
        if not winner:
            continue
        winning_team = match.get(winner, [])
        player_stats = match.get("player_stats", {})
        for pid in winning_team:
            stats = player_stats.get(pid)
            if not stats:
                continue
            if pid not in server_stats:
                server_stats[pid] = {"paint": [], "kill": [], "death": [], "special": []}
            server_stats[pid]["paint"].append(stats.get("paint", 0))
            server_stats[pid]["kill"].append(stats.get("kill", 0))
            server_stats[pid]["death"].append(stats.get("death", 0))
            server_stats[pid]["special"].append(stats.get("special", 0))

    def avg(lst):
        return sum(lst) / len(lst) if lst else 0

    # サーバー全体平均を計算
    all_paint, all_kill, all_death, all_special = [], [], [], []
    for pid, s in server_stats.items():
        all_paint.append(avg(s["paint"]))
        all_kill.append(avg(s["kill"]))
        all_death.append(avg(s["death"]))
        all_special.append(avg(s["special"]))

    if not all_paint:
        return "データ収集中", None

    server_avg = {
        "paint": avg(all_paint),
        "kill": avg(all_kill),
        "death": avg(all_death),
        "special": avg(all_special),
    }

    # 対象プレイヤーの統計
    my_stats = server_stats.get(user_id)
    if not my_stats:
        return "データ収集中", None

    my_avg = {
        "paint": avg(my_stats["paint"]),
        "kill": avg(my_stats["kill"]),
        "death": avg(my_stats["death"]),
        "special": avg(my_stats["special"]),
    }

    # 相対比較（サーバー平均との比率）
    def ratio(my_val, server_val):
        if server_val == 0:
            return 1.0
        return my_val / server_val

    r_paint = ratio(my_avg["paint"], server_avg["paint"])
    r_kill = ratio(my_avg["kill"], server_avg["kill"])
    r_death = ratio(my_avg["death"], server_avg["death"])
    r_special = ratio(my_avg["special"], server_avg["special"])

    THRESHOLD = 1.2
    LOW = 1 / THRESHOLD

    # 優先順位: エース→アンカー→ユーティリティ→コントローラー→スペースメーカー→アタッカー→オールラウンダー
    play_type = None
    if r_kill >= THRESHOLD and r_death <= LOW:
        play_type = "エース"
    elif r_death <= LOW:
        play_type = "アンカー"
    elif r_special >= THRESHOLD:
        play_type = "ユーティリティ"
    elif r_paint >= THRESHOLD:
        play_type = "コントローラー"
    elif r_death >= THRESHOLD and r_kill <= LOW:
        play_type = "スペースメーカー"
    elif r_kill >= THRESHOLD and r_death >= THRESHOLD:
        play_type = "アタッカー"
    else:
        play_type = "オールラウンダー"

    DESCRIPTIONS = {
        "エース": "チームの要。的確に敵を倒しながら自らは倒されない、高い戦闘センスを持つプレイヤー",
        "アンカー": "冷静な判断力で生き残り続け、チームの安定した土台を作るプレイヤー",
        "ユーティリティ": "スペシャルを駆使してチームをサポートし、局面を変える力を持つプレイヤー",
        "コントローラー": "圧倒的な塗り能力でフィールドを支配し、チームに有利な状況を作り出すプレイヤー",
        "スペースメーカー": "自らを囮にして敵の注意を引きつけ、味方が動きやすいスペースを作り出すプレイヤー",
        "アタッカー": "果敢に前線へ飛び込み、激しい戦闘でチームを引っ張るプレイヤー",
        "オールラウンダー": "特定の突出した特徴はないが、状況に応じて柔軟に対応できるプレイヤー",
    }

    return play_type, DESCRIPTIONS.get(play_type, "")


ACCESS_LOG_FILE = os.path.join(DATA_DIR, "access_log.json")

def load_access_log():
    try:
        with open(ACCESS_LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"site": [], "mypage": {}}

def save_access_log(data):
    with open(ACCESS_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

@api.get("/api/player_stats/{user_id}")
def get_player_stats(user_id: str):
    from datetime import datetime
    log = load_access_log()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if "site" not in log:
        log["site"] = []
    if not log["site"] or log["site"][-1]["date"] != today:
        log["site"].append({"date": today, "count": 1})
    else:
        log["site"][-1]["count"] += 1
    if "mypage" not in log:
        log["mypage"] = {}
    if user_id not in log["mypage"]:
        log["mypage"][user_id] = 0
    log["mypage"][user_id] += 1
    save_access_log(log)

    profiles = load_player_profiles()
    ratings_data = load_ratings()
    history = load_match_history()

    profile = profiles.get(user_id)
    if profile is None:
        return JSONResponse(content={"error": "プレイヤーが見つかりません"}, media_type="application/json; charset=utf-8")

    data = ratings_data.get(user_id, {})
    rating = int(round(data.get("rating", 2500))) if isinstance(data, dict) else int(round(float(data)))

    # 全体勝率
    wins = 0
    losses = 0
    stage_stats = {}
    total_paint, total_kill, total_death, total_special, stat_count = 0, 0, 0, 0, 0

    for match in history:
        alpha = match.get("alpha", [])
        bravo = match.get("bravo", [])
        winner = match.get("winner")
        stage = match.get("stage") or "不明"

        if user_id in alpha:
            team = "alpha"
        elif user_id in bravo:
            team = "bravo"
        else:
            continue

        won = (team == winner)
        if won:
            wins += 1
        else:
            losses += 1

        if stage not in stage_stats:
            stage_stats[stage] = {"wins": 0, "losses": 0}
        if won:
            stage_stats[stage]["wins"] += 1
        else:
            stage_stats[stage]["losses"] += 1

        # 戦績統計
        player_stats = match.get("player_stats", {})
        my_stats = player_stats.get(user_id)
        if my_stats:
            total_paint += my_stats.get("paint", 0)
            total_kill += my_stats.get("kill", 0)
            total_death += my_stats.get("death", 0)
            total_special += my_stats.get("special", 0)
            stat_count += 1

    total = wins + losses
    win_rate = round(wins / total * 100, 1) if total > 0 else None

    avg_paint = round(total_paint / stat_count, 1) if stat_count > 0 else None
    avg_kill = round(total_kill / stat_count, 1) if stat_count > 0 else None
    avg_death = round(total_death / stat_count, 1) if stat_count > 0 else None
    avg_special = round(total_special / stat_count, 1) if stat_count > 0 else None
    kd = round(avg_kill / avg_death, 2) if avg_kill is not None and avg_death and avg_death > 0 else None

    stage_list = []
    for stage, s in stage_stats.items():
        t = s["wins"] + s["losses"]
        stage_list.append({
            "stage": stage,
            "wins": s["wins"],
            "losses": s["losses"],
            "total": t,
            "win_rate": round(s["wins"] / t * 100, 1) if t > 0 else None,
        })
    stage_list.sort(key=lambda x: -x["total"])

    # レート変動履歴（直近30戦）
    rate_history = []
    for match in history:
        alpha = match.get("alpha", [])
        bravo = match.get("bravo", [])
        if user_id not in alpha and user_id not in bravo:
            continue
        ratings_after = match.get("ratings_after", {})
        if user_id in ratings_after:
            rate_history.append({
                "timestamp": match.get("timestamp"),
                "rating": ratings_after[user_id],
                "stage": match.get("stage"),
            })
    rate_history = rate_history[-30:]

    # 対プレイヤー勝率
    vs_stats = {}
    for match in history:
        alpha = match.get("alpha", [])
        bravo = match.get("bravo", [])
        winner = match.get("winner")

        if user_id in alpha:
            my_team = "alpha"
            enemies = bravo
        elif user_id in bravo:
            my_team = "bravo"
            enemies = alpha
        else:
            continue

        won = (my_team == winner)
        for enemy_id in enemies:
            if enemy_id not in vs_stats:
                vs_stats[enemy_id] = {"wins": 0, "losses": 0}
            if won:
                vs_stats[enemy_id]["wins"] += 1
            else:
                vs_stats[enemy_id]["losses"] += 1

    vs_list = []
    for enemy_id, s in vs_stats.items():
        t = s["wins"] + s["losses"]
        enemy_profile = profiles.get(enemy_id, {})
        vs_list.append({
            "user_id": enemy_id,
            "display_name": enemy_profile.get("display_name") or enemy_id,
            "wins": s["wins"],
            "losses": s["losses"],
            "total": t,
            "win_rate": round(s["wins"] / t * 100, 1) if t > 0 else None,
        })
    vs_list.sort(key=lambda x: -x["total"])

    # プレイタイプ判定
    play_type, play_type_desc = calc_play_type(user_id, history, profiles)

    return JSONResponse(content={
        "user_id": user_id,
        "display_name": profile.get("display_name") or user_id,
        "rating": rating,
        "peak_rating": profile.get("peak_rating"),
        "owned_badges": profile.get("owned_badges", []),
        "selected_badge": profile.get("selected_badge"),
        "owned_banners": profile.get("owned_banners", []),
        "selected_banner": profile.get("selected_banner"),
        "coins": profile.get("coins", 0),
        "tickets": profile.get("tickets", []),
        "active_effect": profile.get("active_effect"),
        "wins": wins,
        "losses": losses,
        "total": total,
        "win_rate": win_rate,
        "avg_paint": avg_paint,
        "avg_kill": avg_kill,
        "avg_death": avg_death,
        "avg_special": avg_special,
        "kd": kd,
        "play_type": play_type,
        "play_type_desc": play_type_desc,
        "stage_stats": stage_list,
        "avatar_url": profile.get("avatar_url") or "https://cdn.discordapp.com/embed/avatars/0.png",
        "rate_history": rate_history,
        "vs_stats": vs_list,
    }, media_type="application/json; charset=utf-8")
    
import httpx
from fastapi.responses import RedirectResponse

DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI = "https://koganecreatedbytamaki-production-9bb5.up.railway.app/auth/callback"

@api.get("/auth/login")
def auth_login():
    url = (
        "https://discord.com/oauth2/authorize"
        f"?client_id={DISCORD_CLIENT_ID}"
        "&response_type=code"
        f"&redirect_uri={DISCORD_REDIRECT_URI}"
        "&scope=identify"
    )
    return RedirectResponse(url)

@api.get("/auth/callback")
async def auth_callback(code: str):
    async with httpx.AsyncClient() as client:
        token_res = await client.post(
            "https://discord.com/api/oauth2/token",
            data={
                "client_id": DISCORD_CLIENT_ID,
                "client_secret": DISCORD_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": DISCORD_REDIRECT_URI,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        token_data = token_res.json()
        access_token = token_data.get("access_token")

        user_res = await client.get(
            "https://discord.com/api/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        user_data = user_res.json()
        user_id = user_data.get("id")
        avatar = user_data.get("avatar")

    avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.png" if avatar else "https://cdn.discordapp.com/embed/avatars/0.png"

    return RedirectResponse(f"/?id={user_id}&avatar={avatar_url}")

@api.post("/api/join_request")
async def join_request(request: Request):
    body = await request.json()
    user_id = body.get("user_id")
    name = body.get("name")
    x_id = body.get("x_id")

    if not user_id or not name or not x_id:
        return JSONResponse(content={"error": "入力が不足しています"}, status_code=400)

    async def send_message():
        for guild in bot.guilds:
            channel = guild.get_channel(ADMIN_CHANNEL_ID)
            if channel:
                await channel.send(
                    f"【加入申請】\n"
                    f"Discord ID: {user_id}\n"
                    f"名前: {name}\n"
                    f"X: @{x_id}"
                )
                break

    import asyncio
    future = asyncio.run_coroutine_threadsafe(send_message(), bot.loop)
    try:
        future.result(timeout=10)
    except Exception as e:
        print(f"join_request send error: {e}")

    return JSONResponse(content={"success": True})

@api.post("/api/badge/set")
async def set_badge(request: Request):
    body = await request.json()
    user_id = body.get("user_id")
    badge_id = body.get("badge_id")

    if not user_id:
        return JSONResponse(content={"error": "user_id is required"}, status_code=400)

    profile = get_player_profile(int(user_id))

    if badge_id is None or badge_id == "":
        profile["selected_badge"] = None
    else:
        if badge_id not in profile.get("owned_badges", []):
            return JSONResponse(content={"error": "そのバッジは所持していません"}, status_code=403)
        profile["selected_badge"] = badge_id

    save_player_profiles(player_profiles)
    return JSONResponse(content={"success": True})


@api.post("/api/banner/set")
async def set_banner(request: Request):
    body = await request.json()
    user_id = body.get("user_id")
    banner_id = body.get("banner_id")

    if not user_id:
        return JSONResponse(content={"error": "user_id is required"}, status_code=400)

    profile = get_player_profile(int(user_id))

    if banner_id is None or banner_id == "":
        profile["selected_banner"] = None
    else:
        if banner_id not in profile.get("owned_banners", []):
            return JSONResponse(content={"error": "そのバナーは所持していません"}, status_code=403)
        profile["selected_banner"] = banner_id

    save_player_profiles(player_profiles)
    return JSONResponse(content={"success": True})


@api.post("/api/gacha")
async def web_gacha(request: Request):
    body = await request.json()
    user_id = body.get("user_id")

    if not user_id:
        return JSONResponse(content={"error": "user_id is required"}, status_code=400)

    profile = get_player_profile(int(user_id))
    coins = profile.get("coins", 0)

    if coins < GACHA_COST:
        return JSONResponse(content={"error": "コインが足りません"}, status_code=400)

    remove_coin(int(user_id), GACHA_COST)
    item = draw_gacha_item()

    guild = None
    for g in bot.guilds:
        guild = g
        break

    if guild:
        await apply_gacha_result(guild, int(user_id), item)

    save_player_profiles(player_profiles)

    if item["kind"] == "trivia":
        import random as _random
        result_label = _random.choice(TRIVIA_LIST)
    else:
        result_label = item["label"]

    return JSONResponse(content={
        "success": True,
        "kind": item["kind"],
        "label": result_label,
        "coins_remaining": profile.get("coins", 0),
    })


@api.post("/api/ticket/use")
async def web_ticket_use(request: Request):
    body = await request.json()
    user_id = body.get("user_id")
    ticket_index = body.get("ticket_index")

    if not user_id:
        return JSONResponse(content={"error": "user_id is required"}, status_code=400)

    profile = get_player_profile(int(user_id))

    if profile.get("active_effect"):
        return JSONResponse(content={"error": "すでに効果中のチケットがあります"}, status_code=400)

    tickets = profile.get("tickets", [])
    if ticket_index is None or ticket_index < 0 or ticket_index >= len(tickets):
        return JSONResponse(content={"error": "チケットが見つかりません"}, status_code=400)

    ticket = tickets.pop(ticket_index)

    if ticket.get("type") == "weapon_jack":
        tickets.insert(ticket_index, ticket)
        return JSONResponse(content={"error": "このチケットはWebからは使用できません"}, status_code=400)

    profile["active_effect"] = ticket
    profile["tickets"] = tickets
    save_player_profiles(player_profiles)

    return JSONResponse(content={"success": True, "label": ticket.get("label", "不明")})


@api.post("/api/stats/input")
async def web_stats_input(request: Request):
    body = await request.json()
    user_id = body.get("user_id")
    match_id = body.get("match_id")
    paint = body.get("paint")
    kill = body.get("kill")
    death = body.get("death")
    special = body.get("special")

    if not user_id or not match_id:
        return JSONResponse(content={"error": "入力が不足しています"}, status_code=400)

    try:
        paint = int(paint)
        kill = int(kill)
        death = int(death)
        special = int(special)
    except Exception:
        return JSONResponse(content={"error": "数値を入力してください"}, status_code=400)

    history = load_match_history()
    found = False
    for match in reversed(history):
        if match.get("timestamp") == match_id:
            if user_id not in match.get("alpha", []) and user_id not in match.get("bravo", []):
                return JSONResponse(content={"error": "この試合の参加者ではありません"}, status_code=403)
            if "player_stats" not in match:
                match["player_stats"] = {}
            match["player_stats"][user_id] = {
                "paint": paint, "kill": kill,
                "death": death, "special": special,
            }
            found = True
            break

    if not found:
        return JSONResponse(content={"error": "試合が見つかりません"}, status_code=404)

    save_match_history(history)
    return JSONResponse(content={"success": True})


@api.get("/api/my_matches_all/{user_id}")
def get_my_matches_all(user_id: str):
    history = load_match_history()
    user_matches = [
        m for m in history
        if user_id in m.get("alpha", []) or user_id in m.get("bravo", [])
    ]
    result = []
    for m in reversed(user_matches):
        stats = m.get("player_stats", {}).get(user_id)
        result.append({
            "timestamp": m.get("timestamp"),
            "stage": m.get("stage") or "不明",
            "winner": m.get("winner"),
            "my_team": "alpha" if user_id in m.get("alpha", []) else "bravo",
            "already_input": stats is not None,
            "stats": stats,
        })
    return JSONResponse(content={"matches": result})


@api.get("/api/admin/stats")
def get_admin_stats(user_id: str = ""):
    if user_id != str(OWNER_ID):
        return JSONResponse(content={"error": "権限がありません"}, status_code=403)

    log = load_access_log()
    profiles = load_player_profiles()

    mypage_stats = []
    for uid, count in log.get("mypage", {}).items():
        profile = profiles.get(uid, {})
        mypage_stats.append({
            "user_id": uid,
            "display_name": profile.get("display_name") or uid,
            "count": count,
        })
    mypage_stats.sort(key=lambda x: -x["count"])

    return JSONResponse(content={
        "site_log": log.get("site", [])[-30:],
        "mypage_stats": mypage_stats,
    })


@api.get("/api/player/{user_id}")
def get_player(user_id: str):
    ratings_data = load_ratings()
    profiles = load_player_profiles()

    data = ratings_data.get(user_id)
    if data is None:
        return JSONResponse(content={"error": "プレイヤーが見つかりません"}, media_type="application/json; charset=utf-8")

    if isinstance(data, dict):
        rating = int(round(data.get("rating", DEFAULT_RATING)))
        rd = data.get("rd", 120.0)
    else:
        rating = int(round(float(data)))
        rd = 120.0

    profile = profiles.get(user_id, {})
    return JSONResponse(content={
        "user_id": user_id,
        "rating": rating,
        "rd": round(rd, 1),
        "weapon": profile.get("weapon") or "未登録",
        "xp": profile.get("xp"),
        "peak_rating": profile.get("peak_rating"),
        "coins": profile.get("coins", 0),
        "win_streak": profile.get("win_streak", 0),
    }, media_type="application/json; charset=utf-8")

static_dir = os.path.join(os.path.dirname(__file__), "web", "static")
if os.path.exists(static_dir):
    api.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

def run_api():
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(api, host="0.0.0.0", port=port)

if not TOKEN:
    raise ValueError("DISCORD_TOKEN が設定されていません。")

api_thread = threading.Thread(target=run_api, daemon=True)
api_thread.start()
bot.run(TOKEN)
