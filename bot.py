import os
import json
import random
import math
import copy
import time
import discord
from discord.ext import commands

# =========================
# ファイルパス / 環境変数
# =========================
DATA_DIR = "/data"
os.makedirs(DATA_DIR, exist_ok=True)

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

# ホームチャンネル（旧プレイヤー登録チャンネル）
# プレイヤー登録・バッジ設定・コイン・募集作成ボタンをここに常駐
HOME_CHANNEL_ID = 1493300698568462388

# 募集チャンネル（新規作成してIDを入力）
RECRUIT_CHANNEL_ID = 1492899909093949480  # ← ここに募集チャンネルのIDを入力

# レート更新ログチャンネル（新規作成してIDを入力）
RATE_LOG_CHANNEL_ID = 1499607836911730778  # ← ここにレートログチャンネルのIDを入力

ADMIN_CHANNEL_ID = 1492883720082952302

ROOM_CHANNELS = {
    "A": {
        "progress": 1492082738679910512,
        "lobby_vc": 1492082738679910515,
        "alpha_vc": 1492138431583752252,
        "bravo_vc": 1492138468346957884,
    },
    "B": {
        "progress": 1494170122200420463,
        "lobby_vc": 1494170471841660948,
        "alpha_vc": 1494170530260189374,
        "bravo_vc": 1494170564707877085,
    },
}


def get_room_key_by_channel_id(channel_id: int):
    for room_key, cfg in ROOM_CHANNELS.items():
        if cfg["progress"] == channel_id:
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

FIRST_PLACE_CLASS = "<:1st:1494005979594100877>"
SECOND_THIRD_CLASS = "👑"


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
    if rank == 1:
        return FIRST_PLACE_CLASS
    if rank in (2, 3):
        return SECOND_THIRD_CLASS
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
}

GACHA_ITEMS = [
    {"kind": "nothing",    "value": None,            "label": "何も起こらなかった",                              "weight": 35.0},
    {"kind": "rating",     "value": 1,               "label": "レート +1",                                      "weight": 20.0},
    {"kind": "rating",     "value": 5,               "label": "レート +5",                                      "weight": 15.0},
    {"kind": "rating",     "value": 10,              "label": "レート +10",                                     "weight": 8.0},
    {"kind": "ticket",     "value": "rate_x1_1_10",  "label": "10試合 レート変動率 1.1倍",                      "weight": 7.0},
    {"kind": "ticket",     "value": "rate_x1_2_10",  "label": "10試合 レート変動率 1.2倍",                      "weight": 5.0},
    {"kind": "ticket",     "value": "rate_x1_3_10",  "label": "10試合 レート変動率 1.3倍",                      "weight": 4.0},
    {"kind": "ticket",     "value": "rate_plus_3_10","label": "10試合 レート変動に +3",                          "weight": 4.0},
    {"kind": "ticket",     "value": "rate_plus_5_10","label": "10試合 レート変動に +5",                          "weight": 2.5},
    {"kind": "ticket",     "value": "rate_plus_10_5","label": "5試合 レート変動に +10",                          "weight": 1.0},
    {"kind": "ticket",     "value": "win_bonus_1_15","label": "15試合 連勝ごとにボーナス +1",                    "weight": 3.0},
    {"kind": "ticket",     "value": "streak_5_win_20","label": "15試合中 5連勝で +20",                           "weight": 2.0},
    {"kind": "ticket",     "value": "rate_x1_5_5",   "label": "5試合 レート変動率 1.5倍",                       "weight": 0.8},
    {"kind": "ticket",     "value": "win_bonus_2_15","label": "15試合 連勝ごとにボーナス +2",                    "weight": 0.7},
    {"kind": "ticket",     "value": "streak_7_win_50","label": "15試合中 7連勝で +50",                           "weight": 0.4},
    {"kind": "all_rating", "value": 10,              "label": "自分はレート +20 / コイン +2、ランダム3人はレート +10", "weight": 0.1},
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
        target_lines.extend([f"・{m.display_name}（レート +10）" for m in selected])
        text = (
            f"# 【領域展開「坐殺博徒」】\n\n"
            f"{drawer.display_name} ……！正に……豪運……！！\n\n"
            f"# <:Tobuze:1494883064806113430>「漲る呪力（ボーナス）でトぶぜ」\n\n"
            f"# 本人：レート +20 / コイン +2\nランダムで{len(selected)}人にレート +10\n\n"
            f"▼対象\n" + "\n".join(target_lines)
        )

        home_channel = guild.get_channel(HOME_CHANNEL_ID)
        if home_channel:
            try:
                await home_channel.send(text, delete_after=20)
            except Exception:
                pass

        for room_key, cfg in ROOM_CHANNELS.items():
            channel = guild.get_channel(cfg["progress"])
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
        "control_message": None,        # 進行チャンネルの1枚管理メッセージ
        "disconnect_vote_message": None,
        "session_start_ratings": {},
        "session_participants": {},
        "phase1_choices": {},
        "phase2_choices": {},
        "disconnect_vote": None,
    }


room_states = {
    "A": create_room_state(),
    "B": create_room_state(),
}

# 募集状態管理
# {recruit_message_id: {joined_players, host_id, description, start_time, room_key}}
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
    room_state["phase2_choices"] = {}
    room_state["disconnect_vote"] = None


def get_home_channel(guild):
    return guild.get_channel(HOME_CHANNEL_ID)


def get_recruit_channel(guild):
    return guild.get_channel(RECRUIT_CHANNEL_ID)


def get_rate_log_channel(guild):
    return guild.get_channel(RATE_LOG_CHANNEL_ID)


def get_progress_channel(guild, room_key):
    room_cfg = ROOM_CHANNELS.get(room_key)
    if room_cfg is None:
        return None
    return guild.get_channel(room_cfg["progress"])


def get_ranking_channel(guild):
    return guild.get_channel(RANKING_CHANNEL_ID)


def get_admin_channel(guild):
    return guild.get_channel(ADMIN_CHANNEL_ID)


def calc_team_avg(team):
    if not team:
        return 0
    return int(sum(get_user_rating(u.id) for u in team) / len(team))


def get_room_voice_channels(guild, room_key):
    room_cfg = ROOM_CHANNELS.get(room_key)
    if room_cfg is None:
        return None, None, None
    return (
        guild.get_channel(room_cfg["lobby_vc"]),
        guild.get_channel(room_cfg["alpha_vc"]),
        guild.get_channel(room_cfg["bravo_vc"]),
    )


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
        if random.random() < 0.3:
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


def should_show_phase2(room_state):
    random_users = get_random_users(room_state)
    alpha_slots = TEAM_SIZE - get_phase1_count(room_state, "alpha")
    bravo_slots = TEAM_SIZE - get_phase1_count(room_state, "bravo")
    return len(random_users) >= 2 and alpha_slots >= 1 and bravo_slots >= 1


def all_joined_selected_phase1(room_state):
    return (
        len(room_state["joined_players"]) == ROOM_CAPACITY
        and all(str(u.id) in room_state["phase1_choices"] for u in room_state["joined_players"])
    )


def all_random_selected_phase2(room_state):
    random_users = get_random_users(room_state)
    return all(str(u.id) in room_state["phase2_choices"] for u in random_users)


def get_effective_split_targets(room_state):
    random_users = get_random_users(room_state)
    targets = [u for u in random_users if room_state["phase2_choices"].get(str(u.id)) == "split"]
    return targets if len(targets) == 2 else []


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

    split_targets = get_effective_split_targets(room_state)
    if len(split_targets) == 2:
        shuffled_split = split_targets[:]
        random.shuffle(shuffled_split)
        team_alpha.append(shuffled_split[0])
        team_bravo.append(shuffled_split[1])

    remaining_random = [u for u in random_users if u not in split_targets]
    random.shuffle(remaining_random)

    slot_labels = ["alpha"] * (TEAM_SIZE - len(team_alpha)) + ["bravo"] * (TEAM_SIZE - len(team_bravo))
    random.shuffle(slot_labels)

    for user, slot in zip(remaining_random, slot_labels):
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
    return "\n".join(lines)


# =========================
# コントロールメッセージ（進行チャンネル1枚管理）
# =========================
async def update_control_message(guild, room_key, content, view=None):
    """進行チャンネルの1枚管理メッセージを更新（なければ作成）"""
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

    lines = [
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


def create_phase2_text(room_state):
    random_users = get_random_users(room_state)
    split_users = [u for u in random_users if room_state["phase2_choices"].get(str(u.id)) == "split"]
    normal_random_users = [u for u in random_users if room_state["phase2_choices"].get(str(u.id)) == "random"]

    lines = [
        "【第二選択】分けを必要とする人はいますか？",
        "",
        f"【分ける（{len(split_users)}/2）】",
        format_member_lines(split_users, include_weapon=True),
        "",
        "【ランダム】",
        format_member_lines(normal_random_users, include_weapon=True),
        "",
        "※ ランダムを選んだ人のみ対象です",
        "※ 2人揃った場合のみ、その2人を別チームに配置します",
    ]
    return "\n".join(lines)


def create_confirm_text(room_state):
    alpha_users = [u for u in room_state["joined_players"] if room_state["phase1_choices"].get(str(u.id)) == "alpha"]
    bravo_users = [u for u in room_state["joined_players"] if room_state["phase1_choices"].get(str(u.id)) == "bravo"]
    random_users = [u for u in room_state["joined_players"] if room_state["phase1_choices"].get(str(u.id)) == "random"]
    split_targets = get_effective_split_targets(room_state)

    lines = [
        "【確認】この役割で決定でいいですか？",
        "",
        "【アルファ固定】", format_member_lines(alpha_users, include_weapon=True),
        "",
        "【ブラボー固定】", format_member_lines(bravo_users, include_weapon=True),
        "",
        "【ランダム】", format_member_lines(random_users, include_weapon=True),
        "",
        "【分け対象（有効時のみ）】", format_member_lines(split_targets, include_weapon=True),
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


def create_playing_text(team_alpha, team_bravo):
    def fmt(team):
        return "\n".join(build_player_display(u, include_badge=True, include_rating=True) for u in team)

    return (
        f"【試合中】\n\n"
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
class RecruitModal(discord.ui.Modal, title="募集作成"):
    description_input = discord.ui.TextInput(
        label="募集内容",
        placeholder="例：エリアプラベ@7 後衛@2まで",
        max_length=200,
    )
    start_time_input = discord.ui.TextInput(
        label="開始時刻",
        placeholder="例：21:00から1時間",
        max_length=50,
    )

    async def on_submit(self, interaction: discord.Interaction):
        description = str(self.description_input).strip()
        start_time = str(self.start_time_input).strip()

        recruit_channel = get_recruit_channel(interaction.guild)
        if recruit_channel is None:
            await interaction.response.send_message("募集チャンネルが見つかりません", ephemeral=True)
            return

        content = (
            f"【募集】参加する場合は下のボタンをおしてください！\n"
            f"@everyone\n"
            f"{description}\n"
            f"開始時刻: {start_time}\n\n"
            f"0/{ROOM_CAPACITY}人\n\n"
            f"参加者なし"
        )

        view = RecruitView.__new__(RecruitView)
        discord.ui.View.__init__(view, timeout=None)
        RecruitView.__init__(view)

        msg = await recruit_channel.send(content, view=view)

        active_recruits[msg.id] = {
            "joined_players": [],
            "host_id": interaction.user.id,
            "description": description,
            "start_time": start_time,
            "message_id": msg.id,
        }

        await interaction.response.send_message("募集を作成しました！", ephemeral=True)


# =========================
# 募集View
# =========================
class RecruitView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    def build_content(self, recruit_data):
        players = recruit_data["joined_players"]
        description = recruit_data["description"]
        start_time = recruit_data["start_time"]

        if players:
            player_lines = "\n".join(
                build_player_display(p, include_weapon=True) for p in players
            )
        else:
            player_lines = "参加者なし"

        return (
            f"【募集】\n"
            f"{description}\n"
            f"開始時刻: {start_time}\n\n"
            f"{len(players)}/{ROOM_CAPACITY}人\n\n"
            f"{player_lines}"
        )

    @discord.ui.button(label="参加", style=discord.ButtonStyle.primary, custom_id="recruit_join")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        recruit_data = active_recruits.get(interaction.message.id)
        if recruit_data is None:
            await interaction.response.send_message("この募集は無効です", ephemeral=True)
            return

        user = interaction.user
        players = recruit_data["joined_players"]

        if any(p.id == user.id for p in players):
            await interaction.response.send_message("既に参加しています", ephemeral=True)
            return

        if len(players) >= ROOM_CAPACITY:
            await interaction.response.send_message("満員です", ephemeral=True)
            return

        players.append(user)
        content = self.build_content(recruit_data)

        if len(players) == ROOM_CAPACITY:
            # 8人確定 → メッセージを削除して確定メッセージに差し替え
            await interaction.response.edit_message(content=content, view=self)
            await self.finalize_recruit(interaction, recruit_data)
        else:
            await interaction.response.edit_message(content=content, view=self)

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

    async def finalize_recruit(self, interaction: discord.Interaction, recruit_data):
        """8人確定後の処理"""
        players = recruit_data["joined_players"]
        recruit_channel = get_recruit_channel(interaction.guild)

        mention_list = " ".join(p.mention for p in players)
        player_lines = "\n".join(build_player_display(p, include_weapon=True) for p in players)

        content = (
            f"【募集確定】\n"
            f"開始時刻: {recruit_data['start_time']}\n\n"
            f"{mention_list}\n\n"
            f"▼参加者\n{player_lines}\n\n"
            f"開始時刻になったら試合開始ボタンを押してください"
        )

        # 元のメッセージを削除して確定メッセージを投稿
        try:
            await interaction.message.delete()
        except Exception:
            pass

        view = RecruitConfirmView(recruit_data["message_id"], players)
        new_msg = await recruit_channel.send(content, view=view)

        # active_recruitsのキーを新しいメッセージIDに付け替え
        active_recruits[new_msg.id] = recruit_data
        active_recruits.pop(recruit_data["message_id"], None)
        recruit_data["message_id"] = new_msg.id
        recruit_data["confirm_message_id"] = new_msg.id


class RecruitConfirmView(discord.ui.View):
    """8人確定後の試合開始ボタン"""
    def __init__(self, recruit_message_id: int, players: list):
        super().__init__(timeout=None)
        self.recruit_message_id = recruit_message_id
        self.players = players

    @discord.ui.button(label="試合開始", style=discord.ButtonStyle.success, custom_id="recruit_start_game")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        recruit_data = active_recruits.get(interaction.message.id)
        if recruit_data is None:
            await interaction.response.send_message("この募集データが見つかりません", ephemeral=True)
            return

        players = recruit_data["joined_players"]

        # 参加者全員が押せる
        if not any(p.id == interaction.user.id for p in players):
            await interaction.response.send_message("参加者のみ押せます", ephemeral=True)
            return

        # 空いている部屋を探す
        room_key = None
        for rk in ROOM_KEYS:
            if room_states[rk]["game_state"] == "idle":
                room_key = rk
                break

        if room_key is None:
            await interaction.response.send_message("現在空いている部屋がありません", ephemeral=True)
            return

        room_state = room_states[room_key]
        reset_room_state(room_state)
        reset_room_tracking(room_state)

        room_state["joined_players"] = players[:]
        room_state["host_id"] = str(recruit_data["host_id"])

        for player in players:
            ensure_session_player(room_state, player)

        # ホスト報酬
        host_id = recruit_data["host_id"]
        old = get_user_rating(host_id)
        set_user_rating(host_id, old + 5)
        save_ratings(ratings)

        # 募集確定メッセージを削除
        try:
            await interaction.message.delete()
        except Exception:
            pass

        active_recruits.pop(interaction.message.id, None)

        await interaction.response.send_message(
            f"{room_key}部屋で試合を開始します！",
            ephemeral=True
        )

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
            if should_show_phase2(self.room_state):
                await begin_phase2(interaction.guild, self.room_key)
            else:
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


class Phase2ChoiceView(BaseControlView):
    def __init__(self, room_key, room_state):
        super().__init__()
        self.room_key = room_key
        self.room_state = room_state

    async def handle_choice(self, interaction: discord.Interaction, choice_name: str):
        user = interaction.user
        uid = str(user.id)
        random_users = get_random_users(self.room_state)

        if self.room_state["game_state"] != "pref2":
            await interaction.response.send_message("今は第二選択ではありません", ephemeral=True)
            return

        if user not in random_users:
            await interaction.response.send_message("第二選択の対象者ではありません", ephemeral=True)
            return

        current = self.room_state["phase2_choices"].get(uid)

        if choice_name == "split":
            split_count = sum(1 for u in random_users
                              if self.room_state["phase2_choices"].get(str(u.id)) == "split")
            if current != "split" and split_count >= 2:
                await interaction.response.send_message("「分ける」は2人までです", ephemeral=True)
                return

        self.room_state["phase2_choices"][uid] = choice_name

        if all_random_selected_phase2(self.room_state):
            self.disable_all_buttons()
            await interaction.response.edit_message(
                content=create_phase2_text(self.room_state), view=self
            )
            await begin_confirm(interaction.guild, self.room_key)
        else:
            await interaction.response.edit_message(
                content=create_phase2_text(self.room_state), view=self
            )

    @discord.ui.button(label="分ける", style=discord.ButtonStyle.primary)
    async def split_button(self, interaction, button):
        await self.handle_choice(interaction, "split")

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
        self.room_state["phase2_choices"] = {}
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

    @discord.ui.button(label="アルファ勝ち", style=discord.ButtonStyle.primary)
    async def alpha_win_button(self, interaction: discord.Interaction, button):
        await self.handle_result(interaction, 1)

    @discord.ui.button(label="ブラボー勝ち", style=discord.ButtonStyle.primary)
    async def bravo_win_button(self, interaction: discord.Interaction, button):
        await self.handle_result(interaction, 2)

    async def handle_result(self, interaction: discord.Interaction, winner_num: int):
        if interaction.user not in self.room_state["joined_players"]:
            await interaction.response.send_message("この部屋の参加者ではありません", ephemeral=True)
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
# ホームView（プレイヤー登録・バッジ・コイン・募集作成）
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
            await admin_channel.send(f"【ガチャ結果】\n{name}\n→ {item['label']}")

        await interaction.response.send_message(f"ガチャ結果\n→ {item['label']}", ephemeral=True)

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


class HomeView(discord.ui.View):
    """ホームチャンネル常駐View"""
    def __init__(self):
        super().__init__(timeout=None)

    # 左から: 緑・青・緑・赤 の順
    @discord.ui.button(label="募集作成", style=discord.ButtonStyle.success,
                       custom_id="home_create_recruit", row=0)
    async def create_recruit_button(self, interaction: discord.Interaction, button):
        await interaction.response.send_modal(RecruitModal())

    @discord.ui.button(label="コイン", style=discord.ButtonStyle.primary,
                       custom_id="home_coin_menu", row=0)
    async def coin_button(self, interaction: discord.Interaction, button):
        try_claim_passive_coin(interaction.user.id)
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


async def post_home_message(guild):
    channel = get_home_channel(guild)
    if channel is None:
        return None

    content = (
        "【ホーム】\n\n"
        "・募集作成：内部戦の募集を作成します\n"
        "・プレイヤー登録：武器・最高XPを登録します\n"
        "・バッジ設定：表示バッジを変更します\n"
        "・コイン：コインの確認・ガチャ・チケット操作ができます"
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


async def begin_phase2(guild, room_key):
    room_state = room_states[room_key]
    room_state["game_state"] = "pref2"
    random_users = get_random_users(room_state)
    for user in random_users:
        room_state["phase2_choices"].pop(str(user.id), None)
    view = Phase2ChoiceView(room_key, room_state)
    await update_control_message(guild, room_key, create_phase2_text(room_state), view=view)


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
    await update_control_message(guild, room_key, create_playing_text(team_alpha, team_bravo), view=view)


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
    await update_control_message(guild, room_key, create_playing_text(team_alpha, team_bravo), view=view)


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

    room_state["prepared_match"] = make_teams_from_choices(room_state)
    next_team_alpha, next_team_bravo = room_state["prepared_match"]

    # レート更新ログを別チャンネルに送信
    await send_rate_log(guild, room_state, team_alpha, team_bravo)

    room_state["game_state"] = "finished"

    view = FinishedView(room_key, room_state)
    await update_control_message(guild, room_key, create_finished_text(room_state), view=view)


async def send_rate_log(guild, room_state, team_alpha, team_bravo):
    """レート更新ログをRATE_LOG_CHANNELに送信"""
    rate_log_channel = get_rate_log_channel(guild)
    if rate_log_channel is None:
        return

    last_rating_changes = room_state.get("last_rating_changes") or {}
    detail_map = room_state.get("last_rating_detail") or {}

    lines = ["【レート更新】", f"全員に +{PARTICIPATION_BONUS} が追加されました", ""]

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

    channel = get_progress_channel(guild, room_key)

    reset_room_state(room_state)
    reset_room_tracking(room_state)

    if channel:
        if summary_text:
            await channel.send(summary_text)
        await channel.send("部屋を終了しました。次の募集は「ホーム」の「募集作成」ボタンから作成してください。")


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
        # 回線落ちはRDを変化させない（試合不成立扱い）
        entry["rd"] = float(old_rd)

    save_ratings(ratings)

    room_state["prepared_match"] = make_teams_from_choices(room_state)
    next_team_alpha, next_team_bravo = room_state["prepared_match"]

    # レート更新ログを別チャンネルに送信
    rate_log_channel = get_rate_log_channel(guild)
    if rate_log_channel:
        lines = [
            "【レート更新（回線落ち）】",
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

@bot.event
async def on_message(message):
    if message.author.bot:
        return

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


@bot.command(name="回線落ち")
async def disconnect_command(ctx):
    """!回線落ち @ユーザー"""
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


# =========================
# 起動
# =========================
if not TOKEN:
    raise ValueError("DISCORD_TOKEN が設定されていません。")

bot.run(TOKEN)
