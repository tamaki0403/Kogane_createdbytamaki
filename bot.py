import os
import json
import random
import math
import copy
import time
import discord
from discord.ext import commands, tasks

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
    with open(BOT_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

bot_state = load_bot_state()

# =========================
# 管理者設定
# =========================
OWNER_ID = 1225788050894753865
BASE_CHANGE_GAIN = 1.20

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

# =========================
# 動的チャンネル作成・削除ヘルパー
# =========================
async def create_room_channels(guild, room_key: str, participant_ids: list = None):
    """進行ch + レート更新ch + 戦績入力ch + alpha/bravo VCを作成してbot_stateに保存（プライベート化）"""
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
    rate_log_ch = await guild.create_text_channel(
        name=f"レート更新-部屋{room_key}",
        category=category,
        overwrites=overwrites
    )
    stats_ch = await guild.create_text_channel(
        name=f"戦績入力-部屋{room_key}",
        category=category,
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
        "rate_log": rate_log_ch.id,
        "stats": stats_ch.id,
        "alpha_vc": alpha_vc.id,
        "bravo_vc": bravo_vc.id,
    }
    save_dynamic_channels(dc)
    return progress_ch, rate_log_ch, stats_ch, alpha_vc, bravo_vc


async def delete_room_channels(guild, room_key: str):
    """進行ch + レート更新ch + 戦績入力ch + alpha/bravo VCを削除してbot_stateから削除"""
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

def get_room_stats_channel(guild, room_key):
    """動的戦績入力チャンネルを取得"""
    dc = get_dynamic_channels()
    info = dc.get(f"room_{room_key}")
    if not info:
        return None
    return guild.get_channel(info.get("stats"))

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

PARTICIPATION_BONUS = 1
DISCONNECT_PENALTY = 50
DISCONNECT_REWARD = 8
DISCONNECT_GUILTY_THRESHOLD = 4
ROOM_CAPACITY = 8
TEAM_SIZE = 4

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
        "initial_applied": False,
        "can_apply_initial_bonus": True,
        "owned_badges": [],
        "selected_badge": None,
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


def get_xp_adjustment(xp: int):
    if xp <= 1500:   return -500
    if xp <= 1999:   return -400
    if xp <= 2199:   return -300
    if xp <= 2399:   return -200
    if xp <= 2499:   return -100
    if xp <= 2599:   return 0
    if xp <= 2799:   return 100
    if xp <= 2999:   return 150
    if xp <= 3099:   return 200
    if xp <= 3199:   return 250
    if xp <= 3299:   return 300
    if xp <= 3399:   return 350
    if xp <= 3499:   return 400
    if xp <= 3599:   return 450
    if xp <= 3699:   return 500
    return 700


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
    changed = False
    for member in members:
        profile = get_player_profile(member.id)
        if profile.get("can_apply_initial_bonus", True):
            profile["can_apply_initial_bonus"] = False
            changed = True
    if changed:
        save_player_profiles(player_profiles)


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

        text = (
            f"# 【領域展開「坐殺博徒」】\n\n"
            f"{drawer.display_name} ……！正に……豪運……！！\n\n"
            f"# <:Tobuze:1494883064806113430>「漲る呪力（ボーナス）でトぶぜ」\n\n"
            f"# 本人：レート +20 / コイン +2\n"
            f"ランダムで{len(selected)}人にレート +10\n\n"
            f"▼対象\n" + "\n".join(target_lines)
        )

        home_channel = guild.get_channel(HOME_CHANNEL_ID)
        if home_channel:
            try:
                await home_channel.send(text, delete_after=20)
            except Exception:
                pass

        for room_key in ("A", "B"):
            channel = get_progress_channel(guild, room_key)
            if channel:
                try:
                    await channel.send(text)
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
allowed_mentions=discord.AllowedMentions(everyone=True)
)


# =========================
# 状態管理
# =========================
badge_bulk_waiting = {}
bulk_rate_change_waiting = {}
bulk_profile_edit_waiting = {}
bulk_admin_waiting = {}

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
        "control_message": None,
        "disconnect_vote_message": None,
        "session_start_ratings": {},
        "session_participants": {},
        "phase1_choices": {},
        "disconnect_vote": None,
        "current_stage": None,
        "excluded_stages": [],
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
    room_state["control_message"] = None
    room_state["disconnect_vote_message"] = None
    room_state["phase1_choices"] = {}
    room_state["disconnect_vote"] = None
    room_state["current_stage"] = None
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
    channel = get_peak_rating_channel(guild)
    if channel is None:
        return

    top5 = get_top5_peak_ratings(guild)
    if not top5:
        return

    lines = ["# 【歴代最高レート TOP5】", ""]
    for i, (peak, member) in enumerate(top5):
        badge_text = get_current_badge_text(member)
        name = member.display_name
        if badge_text:
            display = f"{name} {badge_text}"
        else:
            display = name
        lines.append(f"## #{i + 1} {display} - {peak}")

    content = "\n".join(lines)

    guild_key = str(guild.id)
    saved_ids = bot_state.get("peak_rating_message_ids", {})
    saved_message_id = saved_ids.get(guild_key)

    if saved_message_id:
        try:
            msg = await channel.fetch_message(saved_message_id)
            await msg.edit(content=content)
            return
        except Exception:
            pass

    msg = await channel.send(content)
    if "peak_rating_message_ids" not in bot_state:
        bot_state["peak_rating_message_ids"] = {}
    bot_state["peak_rating_message_ids"][guild_key] = msg.id
    save_bot_state(bot_state)

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


def get_phase1_count(room_state, choice_name):
    return sum(1 for uid in get_joined_user_ids(room_state)
               if room_state["phase1_choices"].get(uid) == choice_name)


PATTERN_COUNT_TABLE = {
    (0, 0): 70, (0, 1): 35, (0, 2): 15, (0, 3): 5,  (0, 4): 1,
    (1, 0): 35, (1, 1): 20, (1, 2): 10, (1, 3): 4,  (1, 4): 1,
    (2, 0): 15, (2, 1): 10, (2, 2): 6,  (2, 3): 3,  (2, 4): 1,
    (3, 0): 5,  (3, 1): 4,  (3, 2): 3,  (3, 3): 2,  (3, 4): 1,
    (4, 0): 1,  (4, 1): 1,  (4, 2): 1,  (4, 3): 1,  (4, 4): 1,
}

PATTERN_MULTIPLIER_TABLE = {
    70: 1.75, 35: 1.62, 20: 1.50, 15: 1.38, 10: 1.24,
    6: 1.08,  5: 0.98,  4: 0.88,  3: 0.74,  2: 0.62, 1: 0.50,
}


def get_pattern_multiplier(room_state):
    alpha = get_phase1_count(room_state, "alpha")
    bravo = get_phase1_count(room_state, "bravo")
    count = PATTERN_COUNT_TABLE.get((alpha, bravo), 1)
    return PATTERN_MULTIPLIER_TABLE.get(count, 1.0)


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


def get_random_users(room_state):
    return [u for u in room_state["joined_players"]
            if room_state["phase1_choices"].get(str(u.id)) == "random"]


def all_joined_selected_phase1(room_state):
    return (
        len(room_state["joined_players"]) > 0
        and all(str(u.id) in room_state["phase1_choices"] for u in room_state["joined_players"])
    )


async def get_member_display_name_by_id(guild, user_id: int):
    member = guild.get_member(user_id)
    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except Exception:
            member = None
    return member.display_name if member else f"ユーザーID:{user_id}"


def make_teams_from_choices(room_state):
    joined_players = room_state["joined_players"]
    phase1_choices = room_state["phase1_choices"]

    alpha_fixed = [u for u in joined_players if phase1_choices.get(str(u.id)) == "alpha"]
    bravo_fixed = [u for u in joined_players if phase1_choices.get(str(u.id)) == "bravo"]
    random_users = [u for u in joined_players if phase1_choices.get(str(u.id)) == "random"]

    team_alpha = alpha_fixed[:]
    team_bravo = bravo_fixed[:]

    random.shuffle(random_users)

    slot_labels = ["alpha"] * (TEAM_SIZE - len(team_alpha)) + ["bravo"] * (TEAM_SIZE - len(team_bravo))
    random.shuffle(slot_labels)

    for user, slot in zip(random_users, slot_labels):
        if slot == "alpha":
            team_alpha.append(user)
        else:
            team_bravo.append(user)

    if len(team_alpha) != TEAM_SIZE or len(team_bravo) != TEAM_SIZE:
        raise ValueError("チーム分けに失敗しました。希望人数の設定を確認してください。")

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
def create_phase1_text(room_state):
    alpha_users = [u for u in room_state["joined_players"] if room_state["phase1_choices"].get(str(u.id)) == "alpha"]
    bravo_users = [u for u in room_state["joined_players"] if room_state["phase1_choices"].get(str(u.id)) == "bravo"]
    random_users = [u for u in room_state["joined_players"] if room_state["phase1_choices"].get(str(u.id)) == "random"]

    mention_line = " ".join(u.mention for u in room_state["joined_players"])

    lines = [
        mention_line,
        "",
        "【第一選択】希望するチームを選んでください。押し直しで上書きできます。",
        "",
        f"【アルファ（{len(alpha_users)}/{TEAM_SIZE}）】",
        format_member_lines(alpha_users, include_weapon=True),
        "",
        f"【ブラボー（{len(bravo_users)}/{TEAM_SIZE}）】",
        format_member_lines(bravo_users, include_weapon=True),
        "",
        f"【ランダム（{len(random_users)}）】",
        format_member_lines(random_users, include_weapon=True),
    ]
    return "\n".join(lines)


def create_confirm_text(room_state):
    alpha_users = [u for u in room_state["joined_players"] if room_state["phase1_choices"].get(str(u.id)) == "alpha"]
    bravo_users = [u for u in room_state["joined_players"] if room_state["phase1_choices"].get(str(u.id)) == "bravo"]
    random_users = [u for u in room_state["joined_players"] if room_state["phase1_choices"].get(str(u.id)) == "random"]

    lines = [
        "【確認】この役割で決定でいいですか？",
        "",
        "【アルファ固定】", format_member_lines(alpha_users, include_weapon=True),
        "",
        "【ブラボー固定】", format_member_lines(bravo_users, include_weapon=True),
        "",
        "【ランダム】", format_member_lines(random_users, include_weapon=True),
    ]
    return "\n".join(lines)

def create_ready_text(room_state):
    team_alpha, team_bravo = room_state["prepared_match"]
    mention_list = " ".join(u.mention for u in room_state["joined_players"])

    lines = [
        "【試合準備完了】",
        mention_list,
        "",
        "開始時刻になったら試合開始ボタンを押してください",
    ]
    return "\n".join(lines)

def create_playing_text(team_alpha, team_bravo, room_key=None):
    excluded = []
    if room_key:
        excluded = room_states[room_key].get("excluded_stages", [])

    available_stages = [s for s in STAGES if s not in excluded]
    if not available_stages:
        available_stages = STAGES

    stage = random.choice(available_stages)
    if room_key:
        room_states[room_key]["current_stage"] = stage

    def fmt(team):
        return "\n".join(
            build_player_display(u, include_badge=True, include_rating=True)
            for u in team
        )

    return (
        f"【試合中】\n\n"
        f"ステージ: {stage}\n\n"
        f"【アルファ】\n{fmt(team_alpha)}\n\n"
        f"【ブラボー】\n{fmt(team_bravo)}"
    )


def create_finished_text(room_state):
    lines = ["【試合終了】次の行動を選んでください。", ""]

    prepared = room_state.get("prepared_match")
    if prepared:
        next_team_alpha, next_team_bravo = prepared
        alpha_avg = calc_team_avg(next_team_alpha)
        bravo_avg = calc_team_avg(next_team_bravo)
        alpha_names = " ".join(build_player_display(u) for u in next_team_alpha)
        bravo_names = " ".join(build_player_display(u) for u in next_team_bravo)
        lines.append("【次回チーム分け】")
        lines.append(f"アルファ（平均 {alpha_avg}）: {alpha_names}")
        lines.append(f"ブラボー（平均 {bravo_avg}）: {bravo_names}")

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
            await finalize_recruit_creation(
                interaction, self.plave_content, self.start_time, self.host_name, excluded
            )

        select.callback = select_callback
        self.add_item(select)

    @discord.ui.button(label="除外なしで作成", style=discord.ButtonStyle.secondary)
    async def skip_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("自分の募集のみ操作できます", ephemeral=True)
            return
        await finalize_recruit_creation(
            interaction, self.plave_content, self.start_time, self.host_name, []
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


async def finalize_recruit_creation(interaction: discord.Interaction, plave_content: str, start_time: str, host_name: str, excluded_stages: list):
    recruit_channel = get_recruit_channel(interaction.guild)
    if recruit_channel is None:
        await interaction.response.send_message("募集チャンネルが見つかりません", ephemeral=True)
        return

    stage_text = "一部除外" if excluded_stages else "除外なし"

    await recruit_channel.send("@everyone")

    content = (
        f"【募集】参加する場合は下のボタンをおしてください！\n"
        f"プラベ内容: {plave_content}\n"
        f"開始時刻: {start_time}\n"
        f"ステージ: {stage_text}\n"
        f"募集主: {host_name}\n\n"
        f"0/{ROOM_CAPACITY}人\n\n"
        f"参加者なし"
    )

    view = RecruitView.__new__(RecruitView)
    discord.ui.View.__init__(view, timeout=None)
    RecruitView.__init__(view)

    msg = await recruit_channel.send(content, view=view)

    active_recruits[msg.id] = {
        "joined_players": [],
        "reserved_players": [],
        "host_id": interaction.user.id,
        "host_name": host_name,
        "plave_content": plave_content,
        "start_time": start_time,
        "excluded_stages": excluded_stages,
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
        "参加したい人は「参加」ボタンを押します。\n"
        "他サーバーからの参加は「他鯖から」ボタンで名前を予約できます。\n"
        "人数が集まると自動で確定します。\n\n"
        "③ チーム選択\n"
        "進行チャンネルにチーム選択ボタンが表示されます。\n"
        "アルファ・ブラボー・ランダムから希望を選んでください。\n"
        "全員が選ぶと次に進みます。\n\n"
        "④ 試合開始\n"
        "チームが確定したら「試合開始」ボタンを押します。\n"
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
        "・プレイヤー登録時に最高XPに応じて補正が入ります\n"
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
        "🏆 ランキング\n"
        "・レートランキングは専用チャンネルで確認できます\n"
        "・歴代最高レートチャンネルでTOP5が確認できます\n"
        "・ランキングは試合終了時に自動更新されます"
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
class GuestNameModal(discord.ui.Modal, title="他鯖からの参加"):
    name_input = discord.ui.TextInput(
        label="プレイヤー名",
        placeholder="例：たまき",
        max_length=50,
    )

    def __init__(self, message_id: int):
        super().__init__()
        self.message_id = message_id

    async def on_submit(self, interaction: discord.Interaction):
        recruit_data = active_recruits.get(self.message_id)
        if recruit_data is None:
            await interaction.response.send_message("この募集は無効です", ephemeral=True)
            return

        guest_name = str(self.name_input).strip()
        capacity = recruit_data.get("capacity", ROOM_CAPACITY)
        total = len(recruit_data["joined_players"]) + len(recruit_data.get("reserved_players", []))

        if total >= capacity:
            await interaction.response.send_message("満員です", ephemeral=True)
            return

        if "reserved_players" not in recruit_data:
            recruit_data["reserved_players"] = []
        recruit_data["reserved_players"].append({"name": guest_name})

        view = RecruitView()
        content = RecruitView().build_content(recruit_data)
        await interaction.response.edit_message(content=content, view=view)


class RecruitView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    def build_content(self, recruit_data):
        players = recruit_data["joined_players"]
        reserved = recruit_data.get("reserved_players", [])
        plave_content = recruit_data.get("plave_content", "プラベ")
        start_time = recruit_data["start_time"]
        host_name = recruit_data.get("host_name", "")
        excluded_stages = recruit_data.get("excluded_stages", [])
        stage_text = "一部除外" if excluded_stages else "除外なし"
        capacity = recruit_data.get("capacity", ROOM_CAPACITY)
        total = len(players) + len(reserved)

        lines = []
        for p in players:
            lines.append(build_player_display(p, include_weapon=True))
        for r in reserved:
            lines.append(f"予約：{r['name']}（未参加）")

        player_lines = "\n".join(lines) if lines else "参加者なし"

        return (
            f"【募集】参加する場合は下のボタンをおしてください！\n"
            f"プラベ内容: {plave_content}\n"
            f"開始時刻: {start_time}\n"
            f"ステージ: {stage_text}\n"
            f"募集主: {host_name}\n\n"
            f"{total}/{capacity}人\n\n"
            f"{player_lines}"
        )

    async def send_notify_message(self, recruit_channel, recruit_data):
        capacity = recruit_data.get("capacity", ROOM_CAPACITY)
        plave_content = recruit_data.get("plave_content", "プラベ")
        total = len(recruit_data["joined_players"]) + len(recruit_data.get("reserved_players", []))
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

        notify_msg = await recruit_channel.send(f"{plave_content} あと{remaining}人")
        recruit_data["notify_message_id"] = notify_msg.id

    @discord.ui.button(label="参加", style=discord.ButtonStyle.primary, custom_id="recruit_join")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        recruit_data = active_recruits.get(interaction.message.id)
        if recruit_data is None:
            await interaction.response.send_message("この募集は無効です", ephemeral=True)
            return

        user = interaction.user
        players = recruit_data["joined_players"]
        reserved = recruit_data.get("reserved_players", [])
        capacity = recruit_data.get("capacity", ROOM_CAPACITY)
        total = len(players) + len(reserved)

        if any(p.id == user.id for p in players):
            await interaction.response.send_message("既に参加しています", ephemeral=True)
            return

        if total >= capacity:
            await interaction.response.send_message("満員です", ephemeral=True)
            return

        players.append(user)
        total = len(players) + len(reserved)
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
        content = self.build_content(recruit_data)
        await interaction.response.edit_message(content=content, view=self)

        recruit_channel = get_recruit_channel(interaction.guild)
        if recruit_channel:
            await self.send_notify_message(recruit_channel, recruit_data)

    @discord.ui.button(label="他鯖から", style=discord.ButtonStyle.secondary, custom_id="recruit_guest")
    async def guest_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        recruit_data = active_recruits.get(interaction.message.id)
        if recruit_data is None:
            await interaction.response.send_message("この募集は無効です", ephemeral=True)
            return

        capacity = recruit_data.get("capacity", ROOM_CAPACITY)
        total = len(recruit_data["joined_players"]) + len(recruit_data.get("reserved_players", []))
        if total >= capacity:
            await interaction.response.send_message("満員です", ephemeral=True)
            return

        await interaction.response.send_modal(GuestNameModal(interaction.message.id))

    async def finalize_recruit(self, interaction: discord.Interaction, recruit_data):
        players = recruit_data["joined_players"]
        reserved = recruit_data.get("reserved_players", [])
        recruit_channel = get_recruit_channel(interaction.guild)
        plave_content = recruit_data.get("plave_content", "プラベ")
        excluded_stages = recruit_data.get("excluded_stages", [])
        stage_text = "一部除外" if excluded_stages else "除外なし"
        host_name = recruit_data.get("host_name", "")

        mention_list = " ".join(p.mention for p in players)
        lines = []
        for p in players:
            lines.append(build_player_display(p, include_weapon=True))
        for r in reserved:
            lines.append(f"予約：{r['name']}（未参加）")
        player_lines = "\n".join(lines)

        content = (
            f"【募集確定】\n"
            f"プラベ内容: {plave_content}\n"
            f"開始時刻: {recruit_data['start_time']}\n"
            f"ステージ: {stage_text}\n"
            f"募集主: {host_name}\n\n"
            f"{mention_list}\n\n"
            f"▼参加者\n{player_lines}\n\n"
            f"開始時刻になったら試合開始ボタンを押してください"
        )

        try:
            await interaction.message.delete()
        except Exception:
            pass

        view = RecruitConfirmView(recruit_data["message_id"], players, reserved)
        new_msg = await recruit_channel.send(content, view=view)

        active_recruits[new_msg.id] = recruit_data
        active_recruits.pop(recruit_data["message_id"], None)
        recruit_data["message_id"] = new_msg.id
        recruit_data["confirm_message_id"] = new_msg.id
class RecruitConfirmView(discord.ui.View):
    def __init__(self, recruit_message_id: int, players: list, reserved: list = None):
        super().__init__(timeout=None)
        self.recruit_message_id = recruit_message_id
        self.players = players
        self.reserved = reserved or []

        # 予約ボタンを動的に追加
        for r in self.reserved:
            name = r["name"]
            btn = discord.ui.Button(
                label=f"予約：{name}",
                style=discord.ButtonStyle.secondary,
                custom_id=f"reserve_{name}"
            )
            def make_callback(reserved_name=name, reserved_entry=r):
                async def callback(interaction: discord.Interaction):
                    recruit_data = active_recruits.get(interaction.message.id)
                    if recruit_data is None:
                        await interaction.response.send_message("この募集は無効です", ephemeral=True)
                        return
                    recruit_data["reserved_players"] = [
                        x for x in recruit_data.get("reserved_players", [])
                        if x["name"] != reserved_name
                    ]
                    recruit_data["joined_players"].append(interaction.user)

                    new_view = RecruitConfirmView(
                        recruit_data["message_id"],
                        recruit_data["joined_players"],
                        recruit_data.get("reserved_players", [])
                    )
                    plave_content = recruit_data.get("plave_content", "プラベ")
                    excluded_stages = recruit_data.get("excluded_stages", [])
                    stage_text = "一部除外" if excluded_stages else "除外なし"
                    host_name = recruit_data.get("host_name", "")
                    mention_list = " ".join(p.mention for p in recruit_data["joined_players"])
                    lines = []
                    for p in recruit_data["joined_players"]:
                        lines.append(build_player_display(p, include_weapon=True))
                    for rv in recruit_data.get("reserved_players", []):
                        lines.append(f"予約：{rv['name']}（未参加）")
                    player_lines = "\n".join(lines)
                    content = (
                        f"【募集確定】\n"
                        f"プラベ内容: {plave_content}\n"
                        f"開始時刻: {recruit_data['start_time']}\n"
                        f"ステージ: {stage_text}\n"
                        f"募集主: {host_name}\n\n"
                        f"{mention_list}\n\n"
                        f"▼参加者\n{player_lines}\n\n"
                        f"開始時刻になったら試合開始ボタンを押してください"
                    )
                    await interaction.response.edit_message(content=content, view=new_view)
                return callback
            btn.callback = make_callback()
            self.add_item(btn)

    @discord.ui.button(label="試合開始", style=discord.ButtonStyle.success, custom_id="recruit_start_game")
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
        room_state["host_id"] = str(recruit_data["host_id"])
        room_state["excluded_stages"] = recruit_data.get("excluded_stages", [])

        for player in players:
            ensure_session_player(room_state, player)

        participant_ids = [str(p.id) for p in players]
        await create_room_channels(interaction.guild, room_key, participant_ids)

        host_id = recruit_data["host_id"]
        old = get_user_rating(host_id)
        set_user_rating(host_id, old + 5)
        save_ratings(ratings)

        try:
            await interaction.message.delete()
        except Exception:
            pass

        active_recruits.pop(interaction.message.id, None)

        await begin_phase1(interaction.guild, room_key)

# =========================
# 進行View（ボタン化）
# =========================
class BaseControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    def disable_all_buttons(self):
        for child in self.children:
            child.disabled = True


class Phase1ChoiceView(BaseControlView):
    def __init__(self, room_key, room_state):
        super().__init__()
        self.room_key = room_key
        self.room_state = room_state

    async def handle_choice(self, interaction: discord.Interaction, choice_name: str):
        user = interaction.user
        uid = str(user.id)

        if self.room_state["game_state"] != "pref1":
            await interaction.response.send_message("今は第一選択ではありません", ephemeral=True)
            return

        if user not in self.room_state["joined_players"]:
            await interaction.response.send_message("この部屋の参加者ではありません", ephemeral=True)
            return

        current = self.room_state["phase1_choices"].get(uid)

        if choice_name == "alpha":
            if current != "alpha" and get_phase1_count(self.room_state, "alpha") >= TEAM_SIZE:
                await interaction.response.send_message("アルファは満員です", ephemeral=True)
                return

        if choice_name == "bravo":
            if current != "bravo" and get_phase1_count(self.room_state, "bravo") >= TEAM_SIZE:
                await interaction.response.send_message("ブラボーは満員です", ephemeral=True)
                return

        self.room_state["phase1_choices"][uid] = choice_name

        if all_joined_selected_phase1(self.room_state):
            self.disable_all_buttons()
            await interaction.response.edit_message(
                content=create_phase1_text(self.room_state), view=self
            )
            await begin_confirm(interaction.guild, self.room_key)
        else:
            await interaction.response.edit_message(
                content=create_phase1_text(self.room_state), view=self
            )

    @discord.ui.button(label="アルファ", style=discord.ButtonStyle.primary)
    async def alpha_button(self, interaction, button):
        await self.handle_choice(interaction, "alpha")

    @discord.ui.button(label="ブラボー", style=discord.ButtonStyle.primary)
    async def bravo_button(self, interaction, button):
        await self.handle_choice(interaction, "bravo")

    @discord.ui.button(label="ランダム", style=discord.ButtonStyle.secondary)
    async def random_button(self, interaction, button):
        await self.handle_choice(interaction, "random")

class ConfirmView(BaseControlView):
    def __init__(self, room_key, room_state):
        super().__init__()
        self.room_key = room_key
        self.room_state = room_state

    @discord.ui.button(label="決定", style=discord.ButtonStyle.success)
    async def confirm_button(self, interaction: discord.Interaction, button):
        if interaction.user not in self.room_state["joined_players"]:
            await interaction.response.send_message("この部屋の参加者ではありません", ephemeral=True)
            return

        if self.room_state["game_state"] != "confirm":
            await interaction.response.send_message("今は確認段階ではありません", ephemeral=True)
            return

        try:
            self.room_state["prepared_match"] = make_teams_from_choices(self.room_state)
        except Exception as e:
            await interaction.response.send_message(f"チーム分けに失敗しました: {e}", ephemeral=True)
            return

        self.room_state["game_state"] = "ready"
        self.disable_all_buttons()
        await interaction.response.edit_message(content=create_confirm_text(self.room_state), view=self)
        await begin_ready(interaction.guild, self.room_key)

    @discord.ui.button(label="やり直し", style=discord.ButtonStyle.danger)
    async def redo_button(self, interaction: discord.Interaction, button):
        if interaction.user not in self.room_state["joined_players"]:
            await interaction.response.send_message("この部屋の参加者ではありません", ephemeral=True)
            return

        if self.room_state["game_state"] != "confirm":
            await interaction.response.send_message("今は確認段階ではありません", ephemeral=True)
            return

        self.room_state["phase1_choices"] = {}
        self.room_state["game_state"] = "pref1"
        self.disable_all_buttons()
        await interaction.response.edit_message(content=create_confirm_text(self.room_state), view=self)
        await begin_phase1(interaction.guild, self.room_key)


class ReadyView(BaseControlView):
    def __init__(self, room_key, room_state):
        super().__init__()
        self.room_key = room_key
        self.room_state = room_state

    @discord.ui.button(label="試合開始", style=discord.ButtonStyle.success)
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

class StatsInputModal(discord.ui.Modal, title="戦績入力"):
    paint_input = discord.ui.TextInput(
        label="塗りポイント",
        placeholder="例：1200",
        max_length=6,
    )
    kill_input = discord.ui.TextInput(
        label="キル数",
        placeholder="例：5",
        max_length=3,
    )
    death_input = discord.ui.TextInput(
        label="デス数",
        placeholder="例：3",
        max_length=3,
    )
    special_input = discord.ui.TextInput(
        label="スペシャル数",
        placeholder="例：2",
        max_length=3,
    )

    def __init__(self, match_id: str, room_key: str):
        super().__init__()
        self.match_id = match_id
        self.room_key = room_key

    async def on_submit(self, interaction: discord.Interaction):
        paint = str(self.paint_input).strip()
        kill = str(self.kill_input).strip()
        death = str(self.death_input).strip()
        special = str(self.special_input).strip()

        if not all(v.isdigit() for v in [paint, kill, death, special]):
            await interaction.response.send_message("数字のみ入力してください", ephemeral=True)
            return

        history = load_match_history()
        for match in reversed(history):
            if match.get("timestamp") == self.match_id:
                if "player_stats" not in match:
                    match["player_stats"] = {}
                match["player_stats"][str(interaction.user.id)] = {
                    "paint": int(paint),
                    "kill": int(kill),
                    "death": int(death),
                    "special": int(special),
                }
                break
        save_match_history(history)
        await interaction.response.send_message("戦績を入力しました！", ephemeral=True)


class StatsInputView(discord.ui.View):
    def __init__(self, match_id: str, room_key: str):
        super().__init__(timeout=None)
        self.match_id = match_id
        self.room_key = room_key

    @discord.ui.button(label="戦績を入力する", style=discord.ButtonStyle.primary)
    async def stats_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(StatsInputModal(self.match_id, self.room_key))


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

        can_apply = profile.get("can_apply_initial_bonus", True)
        already_applied = profile.get("initial_applied", False)

        if can_apply and not already_applied:
            adjustment = get_xp_adjustment(xp)
            new_rating = DEFAULT_RATING + adjustment
            old_rating = get_user_rating(user.id)
            set_user_rating(user.id, new_rating)
            save_ratings(ratings)
            profile["initial_applied"] = True
            lines.append(f"XP補正を反映したぞ！ {old_rating} → {new_rating}")
        else:
            if not can_apply:
                lines.append("このプレイヤーは初期補正権がないため、XP補正は適用されない。")
            else:
                lines.append("XP情報は更新したが、レート補正は既に適用済みだ。")

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

class PastStatsSelectView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=60)
        self.user_id = user_id

        history = load_match_history()
        user_matches = [
            m for m in history
            if str(user_id) in m.get("alpha", []) or str(user_id) in m.get("bravo", [])
        ]
        recent = user_matches[-5:][::-1]

        if not recent:
            self.add_item(discord.ui.Select(
                placeholder="参加した試合がありません",
                options=[discord.SelectOption(label="なし", value="none")],
                disabled=True
            ))
            return

        options = []
        for m in recent:
            ts = m.get("timestamp", "")
            stage = m.get("stage") or "不明"
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(ts)
                label = f"{dt.strftime('%m/%d %H:%M')} {stage}"
            except Exception:
                label = f"{ts[:16]} {stage}"
            options.append(discord.SelectOption(label=label[:100], value=ts))

        select = discord.ui.Select(
            placeholder="戦績を入力する試合を選択",
            options=options
        )

        async def select_callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("自分の操作のみ可能です", ephemeral=True)
                return
            match_id = select.values[0]
            await interaction.response.send_modal(StatsInputModal(match_id, None))

        select.callback = select_callback
        self.add_item(select)


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

    @discord.ui.button(label="過去の戦績を入力", style=discord.ButtonStyle.secondary,
                       custom_id="home_past_stats", row=1)
    async def past_stats_button(self, interaction: discord.Interaction, button):
        await interaction.response.send_message(
            "戦績を入力する試合を選んでください",
            view=PastStatsSelectView(interaction.user.id),
            ephemeral=True
        )

class AdminButtonView_Ranking(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="ランキング更新", style=discord.ButtonStyle.primary, custom_id="admin_ranking")
    async def ranking_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        await interaction.response.send_message("更新中...", ephemeral=True)
        await post_ranking(interaction.guild)
        await post_peak_ranking(interaction.guild)
        await interaction.edit_original_response(content="ランキングを更新しました")

    @discord.ui.button(label="秘匿ランキング", style=discord.ButtonStyle.primary, custom_id="admin_secret_ranking")
    async def secret_ranking_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        await interaction.response.send_message("送信中...", ephemeral=True)
        await post_secret_ranking(interaction.guild)
        await interaction.edit_original_response(content="秘匿ランキングを送信しました")

    @discord.ui.button(label="ホーム更新", style=discord.ButtonStyle.primary, custom_id="admin_home_update")
    async def home_update_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        await interaction.response.send_message("更新中...", ephemeral=True)
        await post_home_message(interaction.guild)
        await interaction.edit_original_response(content="ホームを更新しました")


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

    @discord.ui.button(label="名前更新", style=discord.ButtonStyle.secondary, custom_id="admin_name_update")
    async def name_update_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        await interaction.response.send_message("更新中...", ephemeral=True)
        try:
            members = [member async for member in interaction.guild.fetch_members(limit=None)]
        except Exception:
            members = interaction.guild.members
        count = 0
        for member in members:
            if member.bot:
                continue
            profile = get_player_profile(member.id)
            profile["display_name"] = member.display_name
            count += 1
        save_player_profiles(player_profiles)
        await interaction.edit_original_response(content=f"{count}人の名前を更新しました")

    @discord.ui.button(label="アバター更新", style=discord.ButtonStyle.secondary, custom_id="admin_avatar_update")
    async def avatar_update_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        await interaction.response.send_message("更新中...", ephemeral=True)
        try:
            members = [member async for member in interaction.guild.fetch_members(limit=None)]
        except Exception:
            members = interaction.guild.members
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
        await interaction.edit_original_response(content=f"{count}人のアバターを更新しました")


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
            badge_bulk_waiting[i.guild.id] = {"mode": "grant", "badge_id": badge_id, "user_id": i.user.id}
            admin_ch = get_admin_channel(i.guild)
            if admin_ch:
                await admin_ch.send(f"バッジ付与モード（{badge_id}）\nユーザーIDを1行ずつ送ってください。キャンセルで終了。")
            await i.response.send_message("運営チャンネルでユーザーIDを送ってください", ephemeral=True)
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
            badge_bulk_waiting[i.guild.id] = {"mode": "remove", "badge_id": badge_id, "user_id": i.user.id}
            admin_ch = get_admin_channel(i.guild)
            if admin_ch:
                await admin_ch.send(f"バッジ削除モード（{badge_id}）\nユーザーIDを1行ずつ送ってください。キャンセルで終了。")
            await i.response.send_message("運営チャンネルでユーザーIDを送ってください", ephemeral=True)
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
            badge_bulk_waiting[i.guild.id] = {"mode": "force_grant", "badge_id": badge_id, "user_id": i.user.id}
            admin_ch = get_admin_channel(i.guild)
            if admin_ch:
                await admin_ch.send(f"バッジ強制付与モード（{badge_id}）\nユーザーIDを1行ずつ送ってください。キャンセルで終了。")
            await i.response.send_message("運営チャンネルでユーザーIDを送ってください", ephemeral=True)
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
        bulk_rate_change_waiting[interaction.guild.id] = interaction.user.id
        admin_ch = get_admin_channel(interaction.guild)
        if admin_ch:
            await admin_ch.send("レート値変更モード\nユーザーID レート値 を1行ずつ送ってください。キャンセルで終了。")
        await interaction.response.send_message("運営チャンネルで入力してください", ephemeral=True)

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
        await interaction.response.send_message("⚠️ 本当にリセットしますか？\n確認のため `!全員レートリセット` を運営チャンネルで実行してください", ephemeral=True)

    @discord.ui.button(label="最高レート初期化", style=discord.ButtonStyle.danger, custom_id="admin_peak_init")
    async def peak_init_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        await interaction.response.send_message("初期化中...", ephemeral=True)
        count = 0
        for uid, profile in player_profiles.items():
            if profile.get("peak_rating") is None:
                current = get_user_rating(uid)
                profile["peak_rating"] = current
                count += 1
        save_player_profiles(player_profiles)
        await interaction.edit_original_response(content=f"{count}人の最高レートを初期化しました")

    @discord.ui.button(label="全員初期補正付与", style=discord.ButtonStyle.danger, custom_id="admin_bonus_grant_all")
    async def bonus_grant_all_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        await interaction.response.send_message("付与中...", ephemeral=True)
        members = [m for m in interaction.guild.members if not m.bot]
        for member in members:
            profile = get_player_profile(member.id)
            profile["can_apply_initial_bonus"] = True
            profile["initial_applied"] = False
        save_player_profiles(player_profiles)
        await interaction.edit_original_response(content=f"全員に初期補正権を付与しました（{len(members)}人）")

    @discord.ui.button(label="全員初期補正剥奪", style=discord.ButtonStyle.danger, custom_id="admin_bonus_revoke_all")
    async def bonus_revoke_all_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        await interaction.response.send_message("剥奪中...", ephemeral=True)
        members = [m for m in interaction.guild.members if not m.bot]
        for member in members:
            get_player_profile(member.id)["can_apply_initial_bonus"] = False
        save_player_profiles(player_profiles)
        await interaction.edit_original_response(content=f"全員の初期補正権を剥奪しました（{len(members)}人）")

    @discord.ui.button(label="初期補正権付与", style=discord.ButtonStyle.danger, custom_id="admin_bonus_grant")
    async def bonus_grant_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        await interaction.response.send_message("運営チャンネルで `!初期補正権付与 ユーザーID` を使ってください", ephemeral=True)

    @discord.ui.button(label="初期補正権剥奪", style=discord.ButtonStyle.danger, custom_id="admin_bonus_revoke")
    async def bonus_revoke_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        await interaction.response.send_message("運営チャンネルで `!初期補正権剥奪 ユーザーID` を使ってください", ephemeral=True)


class AdminButtonView_Bulk(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="運営一括", style=discord.ButtonStyle.secondary, custom_id="admin_bulk")
    async def bulk_button(self, interaction: discord.Interaction, button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("管理者専用です", ephemeral=True)
            return
        bulk_admin_waiting[interaction.guild.id] = interaction.user.id
        admin_ch = get_admin_channel(interaction.guild)
        if admin_ch:
            await admin_ch.send(
                "運営一括モード\nユーザーID コマンド 内容 を1行ずつ送ってください。\n\n"
                "使えるコマンド:\n武器 / 武器削除 / XP / XP削除\n"
                "バッジ付与 / バッジ削除 / バッジ強制付与\n"
                "レート / 初期補正付与 / 初期補正剥奪\nコイン / チケット付与\n\n"
                "やめるときは キャンセル"
            )
        await interaction.response.send_message("運営チャンネルで入力してください", ephemeral=True)

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
        "・過去の戦績を入力：過去5戦分の戦績を入力できます"
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
    ranking_channel = get_ranking_channel(guild)
    if ranking_channel is None:
        return
    await delete_old_ranking_messages(guild)
    lines = await build_ranking_lines(guild)
    message = ""
    for line in lines:
        if len(message) + len(line) + 1 > 1900:
            await ranking_channel.send(message)
            message = line
        else:
            message += ("\n" if message else "") + line
    if message:
        await ranking_channel.send(message)


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


async def begin_phase1(guild, room_key):
    room_state = room_states[room_key]
    room_state["game_state"] = "pref1"
    view = Phase1ChoiceView(room_key, room_state)
    await update_control_message(guild, room_key, create_phase1_text(room_state), view=view)

async def begin_confirm(guild, room_key):
    room_state = room_states[room_key]
    room_state["game_state"] = "confirm"
    view = ConfirmView(room_key, room_state)
    await update_control_message(guild, room_key, create_confirm_text(room_state), view=view)


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

    final_change = int(round(multiplied)) + PARTICIPATION_BONUS + streak_bonus + ticket_flat_bonus
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
        "ratings_after": {str(u.id): get_user_rating(u.id) for u in team_alpha + team_bravo},
    }
    history = load_match_history()
    history.append(match_record)
    save_match_history(history)

    await check_and_update_peak_ranking(
        guild, [str(u.id) for u in team_alpha + team_bravo]
    )

    room_state["prepared_match"] = make_teams_from_choices(room_state)

    await send_rate_log(guild, room_state, team_alpha, team_bravo, room_key)

    room_state["game_state"] = "finished"
    view = FinishedView(room_key, room_state)
    await update_control_message(guild, room_key, create_finished_text(room_state), view=view)

    # 戦績入力ボタンを戦績入力チャンネルに送信
    stats_ch = get_room_stats_channel(guild, room_key)
    if stats_ch:
        match_id = match_record["timestamp"]
        await stats_ch.send(
            "試合が終わりました！戦績を入力してください。",
            view=StatsInputView(match_id, room_key)
        )


async def send_rate_log(guild, room_state, team_alpha, team_bravo, room_key):
    rate_log_channel = get_room_rate_log_channel(guild, room_key)
    if rate_log_channel is None:
        return

    last_rating_changes = room_state.get("last_rating_changes") or {}
    detail_map = room_state.get("last_rating_detail") or {}

    lines = ["# 【レート更新】", ""]

    for user in team_alpha + team_bravo:
        uid = str(user.id)
        old = last_rating_changes.get(uid, get_user_rating(uid))
        new = get_user_rating(uid)
        detail = detail_map.get(uid)

        name = build_player_display(user, include_badge=True)

        if detail:
            final = detail["final"]
            final_str = f"+{final}" if final >= 0 else f"{final}"
            ticket_label = detail.get("ticket_label")
            change_text = f"({final_str} : {ticket_label})" if ticket_label else f"({final_str})"
        else:
            diff = new - old
            diff_str = f"+{diff}" if diff >= 0 else f"{diff}"
            change_text = f"({diff_str})"

        lines.append(f"{name}: {old} → {new} {change_text}")

    text = "\n".join(lines)
    if len(text) <= 1900:
        await rate_log_channel.send(text)
    else:
        chunk = ""
        for line in lines:
            if len(chunk) + len(line) + 1 > 1900:
                await rate_log_channel.send(chunk)
                chunk = line
            else:
                chunk += ("\n" if chunk else "") + line
        if chunk:
            await rate_log_channel.send(chunk)


async def end_room(guild, room_key):
    room_state = room_states[room_key]
    summary_text = create_room_summary_text(room_state)

    grant_room_coin_lottery(room_state)
    await move_members_to_lobby(guild, room_key, room_state)
    await post_ranking(guild)

    if summary_text:
        rate_log_channel = get_rate_log_channel(guild)
        if rate_log_channel:
            await rate_log_channel.send(summary_text)

    channel = get_progress_channel(guild, room_key)
    if channel:
        await channel.send("部屋を終了しました。次の募集は「ホーム」の「募集作成」ボタンから作成してください。")

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

    room_state["last_rating_changes"] = None
    room_state["last_rating_detail"] = None
    room_state["last_profile_snapshots"] = None
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

    room_state["prepared_match"] = make_teams_from_choices(room_state)

    rate_log_channel = get_room_rate_log_channel(guild, room_key)
    if rate_log_channel:
        lines = [
            "# 【レート更新（回線落ち）】",
            f"回線落ち: -{DISCONNECT_PENALTY} / その他: +{DISCONNECT_REWARD}",
            ""
        ]
        for user in all_players:
            uid = str(user.id)
            old = room_state["last_rating_changes"].get(uid, get_user_rating(uid))
            new = get_user_rating(uid)
            diff = new - old
            diff_str = f"+{diff}" if diff >= 0 else f"{diff}"
            name = build_player_display(user, include_badge=True)
            lines.append(f"{name}: {old} → {new} ({diff_str})")

        text = "\n".join(lines)
        if len(text) <= 1900:
            await rate_log_channel.send(text)

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

        elif command_name == "初期補正付与":
            if args:
                error_lines.append(f"{line_no}行目: 余分な入力があります -> {line}")
                continue
            profile["can_apply_initial_bonus"] = True
            profile["initial_applied"] = False
            changed_profiles = True
            success_lines.append(line)

        elif command_name == "初期補正剥奪":
            if args:
                error_lines.append(f"{line_no}行目: 余分な入力があります -> {line}")
                continue
            profile["can_apply_initial_bonus"] = False
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
    bot.add_view(RecruitView())
    bot.add_view(AdminButtonView_Ranking())
    bot.add_view(AdminButtonView_List())
    bot.add_view(AdminButtonView_Badge())
    bot.add_view(AdminButtonView_Rate())
    bot.add_view(AdminButtonView_Bulk())
    daily_coin_distribution.start()
    for guild in bot.guilds:
        await post_admin_buttons(guild)  

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


@bot.command(name="全員初期補正権付与")
async def grant_all_initial_bonus(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("このコマンドは運営チャンネルで使ってください")
        return

    members = [m for m in ctx.guild.members if not m.bot]
    for member in members:
        profile = get_player_profile(member.id)
        profile["can_apply_initial_bonus"] = True
        profile["initial_applied"] = False

    save_player_profiles(player_profiles)
    await ctx.send(f"全員に初期補正権を付与しました（{len(members)}人）")


@bot.command(name="全員初期補正権剥奪")
async def revoke_all_initial_bonus(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("このコマンドは運営チャンネルで使ってください")
        return

    members = [m for m in ctx.guild.members if not m.bot]
    for member in members:
        get_player_profile(member.id)["can_apply_initial_bonus"] = False

    save_player_profiles(player_profiles)
    await ctx.send(f"全員の初期補正権を剥奪しました（{len(members)}人）")


@bot.command(name="初期補正権付与")
async def grant_initial_bonus(ctx, user_id: int):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("このコマンドは運営チャンネルで使ってください")
        return

    profile = get_player_profile(user_id)
    profile["can_apply_initial_bonus"] = True
    profile["initial_applied"] = False
    save_player_profiles(player_profiles)
    name = await get_member_display_name_by_id(ctx.guild, user_id)
    await ctx.send(f"{name} に初期補正権を付与しました")


@bot.command(name="初期補正権剥奪")
async def revoke_initial_bonus(ctx, user_id: int):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("このコマンドは運営チャンネルで使ってください")
        return

    get_player_profile(user_id)["can_apply_initial_bonus"] = False
    save_player_profiles(player_profiles)
    name = await get_member_display_name_by_id(ctx.guild, user_id)
    await ctx.send(f"{name} の初期補正権を剥奪しました")


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
        if member.avatar:
            profile["avatar_url"] = str(member.avatar.url)
        else:
            profile["avatar_url"] = f"https://cdn.discordapp.com/embed/avatars/0.png"
        count += 1

    save_player_profiles(player_profiles)
    await ctx.send(f"{count}人のアバターを更新しました！")
    
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
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

api = FastAPI()

@api.get("/api/health")
def health():
    return JSONResponse(content={"status": "ok"}, media_type="application/json; charset=utf-8")

@api.get("/api/ranking")
def get_ranking():
    ratings_data = load_ratings()
    profiles = load_player_profiles()

    players = []
    for uid, data in ratings_data.items():
        if isinstance(data, dict):
            rating = int(round(data.get("rating", DEFAULT_RATING)))
        else:
            rating = int(round(float(data)))

        profile = profiles.get(uid, {})
        players.append({
            "user_id": uid,
            "rating": rating,
            "display_name": profile.get("display_name"),
            "peak_rating": profile.get("peak_rating"),
            "avatar_url": profile.get("avatar_url") or "https://cdn.discordapp.com/embed/avatars/0.png",
        })

    players.sort(key=lambda x: -x["rating"])
    for i, p in enumerate(players):
        p["rank"] = i + 1

    return JSONResponse(content={"players": players}, media_type="application/json; charset=utf-8")

@api.get("/api/peak_ranking")
def get_peak_ranking():
    profiles = load_player_profiles()

    players = []
    for uid, profile in profiles.items():
        peak = profile.get("peak_rating")
        if peak is None:
            continue
        players.append({
            "user_id": uid,
            "display_name": profile.get("display_name") or uid,
            "peak_rating": peak,
            "avatar_url": profile.get("avatar_url") or "https://cdn.discordapp.com/embed/avatars/0.png",
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


@api.get("/api/player_stats/{user_id}")
def get_player_stats(user_id: str):
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
