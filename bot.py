import os
import json
import random
import discord
from discord.ext import commands

# =========================
# ファイルパス / 環境変数
# =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RATINGS_FILE = os.path.join(BASE_DIR, "ratings.json")
PLAYER_PROFILES_FILE = os.path.join(BASE_DIR, "player_profiles.json")
TOKEN = os.getenv("DISCORD_TOKEN")

# =========================
# Bot状態（追加）
# =========================
BOT_STATE_FILE = os.path.join(BASE_DIR, "bot_state.json")

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

# 中断用フラグ（なくてもOKだが安全）
CANCELABLE_STATES = ["mode_select", "recruiting", "ready"]

# =========================
# チャンネル設定
# =========================

RANKING_CHANNEL_ID = 1492896273358127235
PLAYER_REGISTER_CHANNEL_ID = 1493300698568462388
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


def get_room_state_by_channel(channel_id: int):
    room_key = get_room_key_by_channel_id(channel_id)
    if room_key is None:
        return None, None
    return room_key, room_states[room_key]

# =========================
# レート設定
# =========================

DEFAULT_RATING = 2500

# =========================
# バッジ定義（ここだけ編集）
# =========================
# ▼▼▼ BADGE AREA START ▼▼▼
BADGE_DEFINITIONS = {
    # フォーマット:
    # "badge_id": {"label": "表示名", "emoji": "絵文字"},

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
# ▲▲▲ BADGE AREA END ▲▲▲

K_FACTOR = 90
PARTICIPATION_BONUS = 1

DISCONNECT_PENALTY = 50
DISCONNECT_REWARD = 8
DISCONNECT_GUILTY_THRESHOLD = 4

ROOM_CAPACITY = 8
TEAM_SIZE = 4

## =========================
# 固定人数ごとのKテーブル
# =========================
K_TABLE = {
    (0, 0): 140, (0, 1): 140, (0, 2): 116, (0, 3): 90, (0, 4): 40,
    (1, 0): 140, (1, 1): 124, (1, 2): 106, (1, 3): 86, (1, 4): 40,
    (2, 0): 116, (2, 1): 106, (2, 2): 94, (2, 3): 78, (2, 4): 40,
    (3, 0): 90, (3, 1): 86, (3, 2): 78, (3, 3): 68, (3, 4): 40,
    (4, 0): 40, (4, 1): 40, (4, 2): 40, (4, 3): 40, (4, 4): 40,
}

# =========================
# レート関連
# =========================
def load_ratings():
    try:
        with open(RATINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_ratings(ratings_data):
    with open(RATINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(ratings_data, f, indent=2, ensure_ascii=False)


def elo_update(rA, rB, scoreA, K=K_FACTOR):
    expected_a = 1 / (1 + 10 ** ((rB - rA) / 400))
    return int(rA + K * (scoreA - expected_a))


ratings = load_ratings()

FIRST_PLACE_CLASS = "<:1st:1494005979594100877>"
SECOND_THIRD_CLASS = "👑"


def get_sorted_rating_user_ids():
    if not ratings:
        return []

    return [
        user_id
        for user_id, _ in sorted(
            ratings.items(),
            key=lambda x: (-x[1], x[0])
        )
    ]


def get_user_rank(user_id: int):
    target_id = str(user_id)

    sorted_items = sorted(
        ratings.items(),
        key=lambda x: (-x[1], x[0])
    )

    rank = 1
    prev_rate = None

    for i, (uid, rate) in enumerate(sorted_items):
        if prev_rate is not None and rate < prev_rate:
            rank = i + 1

        if uid == target_id:
            return rank

        prev_rate = rate

    return None

def get_top_player_id():
    sorted_ids = get_sorted_rating_user_ids()
    if not sorted_ids:
        return None
    return sorted_ids[0]

# =========================
# プレイヤープロフィール関連
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


def get_player_profile(user_id: int):
    uid = str(user_id)
    if uid not in player_profiles:
        player_profiles[uid] = {}

    profile = player_profiles[uid]

    if "weapon" not in profile:
        profile["weapon"] = None
    if "xp" not in profile:
        profile["xp"] = None
    if "initial_applied" not in profile:
        profile["initial_applied"] = False
    if "can_apply_initial_bonus" not in profile:
        profile["can_apply_initial_bonus"] = True
    if "owned_badges" not in profile:
        profile["owned_badges"] = []
    if "selected_badge" not in profile:
        profile["selected_badge"] = None
    if "coins" not in profile:
        profile["coins"] = 0
    if "tickets" not in profile:
        profile["tickets"] = []
    if "active_effect" not in profile:
        profile["active_effect"] = None
    if "next_coin_at" not in profile:
        profile["next_coin_at"] = None
    if "win_streak" not in profile:
        profile["win_streak"] = 0

    if profile["selected_badge"] and profile["selected_badge"] not in profile["owned_badges"]:
        profile["selected_badge"] = None

    return profile


for uid in list(player_profiles.keys()):
    get_player_profile(int(uid))

def get_weapon_text(user_id: int):
    profile = get_player_profile(user_id)
    weapon = profile.get("weapon")
    return weapon if weapon else "未登録"


def get_xp_adjustment(xp: int):
    if xp <= 1500:
        return -500
    if 1500 <= xp <= 1999:
        return -400
    if 2000 <= xp <= 2199:
        return -300
    if 2200 <= xp <= 2399:
        return -200
    if 2400 <= xp <= 2499:
        return -100
    if 2500 <= xp <= 2599:
        return 0
    if 2600 <= xp <= 2799:
        return 100
    if 2800 <= xp <= 2999:
        return 150
    if 3000 <= xp <= 3099:
        return 200
    if 3100 <= xp <= 3199:
        return 250
    if 3200 <= xp <= 3299:
        return 300
    if 3300 <= xp <= 3399:
        return 350
    if 3400 <= xp <= 3499:
        return 400
    if 3500 <= xp <= 3599:
        return 450
    if 3600 <= xp <= 3699:
        return 500
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
        return False

    try:
        next_dt = datetime.fromisoformat(next_coin_at)
    except Exception:
        set_next_coin_time(user_id)
        return False

    if now >= next_dt:
        if profile.get("coins", 0) < COIN_LIMIT:
            add_coin(user_id, 1)
        set_next_coin_time(user_id)
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
        weapon = get_weapon_text(user.id)
        line += f"（{weapon}）"

    if include_badge and badge_text:
        line += f" {badge_text}"

    if include_rating:
        current_rating = ratings.get(str(user.id), DEFAULT_RATING)
        line += f" {current_rating}"

    if include_rate_change:
        if old_rating is None:
            old_rating = ratings.get(str(user.id), DEFAULT_RATING)
        if new_rating is None:
            new_rating = ratings.get(str(user.id), DEFAULT_RATING)

        diff = new_rating - old_rating
        sign = "+" if diff >= 0 else ""
        line += f": {old_rating} → {new_rating} ({sign}{diff})"

    return line


def format_member_lines(
    members,
    *,
    mention=False,
    include_weapon=False,
    include_badge=False,
    include_rating=False,
):
    if not members:
        return "なし"

    return "\n".join(
        build_player_display(
            m,
            mention=mention,
            include_weapon=include_weapon,
            include_badge=include_badge,
            include_rating=include_rating,
        )
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
    "rate_x1_1_10": {
        "label": "10試合 レート変動率 1.1倍",
        "type": "rate_multiplier",
        "multiplier": 1.1,
        "remaining_matches": 10,
    },
    "rate_x1_2_10": {
        "label": "10試合 レート変動率 1.2倍",
        "type": "rate_multiplier",
        "multiplier": 1.2,
        "remaining_matches": 10,
    },
    "rate_x1_3_10": {
        "label": "10試合 レート変動率 1.3倍",
        "type": "rate_multiplier",
        "multiplier": 1.3,
        "remaining_matches": 10,
    },
    "rate_x1_5_5": {
        "label": "5試合 レート変動率 1.5倍",
        "type": "rate_multiplier",
        "multiplier": 1.5,
        "remaining_matches": 5,
    },
    "win_bonus_1_15": {
        "label": "15試合 連勝ごとにボーナス +1",
        "type": "win_streak_bonus",
        "bonus_per_streak": 1,
        "remaining_matches": 15,
    },
    "win_bonus_2_15": {
        "label": "15試合 連勝ごとにボーナス +2",
        "type": "win_streak_bonus",
        "bonus_per_streak": 2,
        "remaining_matches": 15,
    },
    "streak_5_win_20": {
        "label": "15試合中 5連勝で +20",
        "type": "streak_reward",
        "target_streak": 5,
        "reward": 20,
        "remaining_matches": 15,
    },
    "streak_7_win_50": {
        "label": "15試合中 7連勝で +50",
        "type": "streak_reward",
        "target_streak": 7,
        "reward": 50,
        "remaining_matches": 15,
    },
}

GACHA_ITEMS = [
    {"kind": "nothing", "value": None, "label": "何も起こらなかった", "weight": 35.0},
    {"kind": "rating", "value": 1, "label": "レート +1", "weight": 20.0},
    {"kind": "rating", "value": 5, "label": "レート +5", "weight": 15.0},
    {"kind": "rating", "value": 10, "label": "レート +10", "weight": 8.0},
    {"kind": "ticket", "value": "rate_x1_1_10", "label": "10試合 レート変動率 1.1倍", "weight": 7.0},
    {"kind": "ticket", "value": "rate_x1_2_10", "label": "10試合 レート変動率 1.2倍", "weight": 5.0},
    {"kind": "ticket", "value": "rate_x1_3_10", "label": "10試合 レート変動率 1.3倍", "weight": 4.0},
    {"kind": "ticket", "value": "win_bonus_1_15", "label": "15試合 連勝ごとにボーナス +1", "weight": 3.0},
    {"kind": "ticket", "value": "streak_5_win_20", "label": "15試合中 5連勝で +20", "weight": 2.0},
    {"kind": "ticket", "value": "rate_x1_5_5", "label": "5試合 レート変動率 1.5倍", "weight": 0.8},
    {"kind": "ticket", "value": "win_bonus_2_15", "label": "15試合 連勝ごとにボーナス +2", "weight": 0.7},
    {"kind": "ticket", "value": "streak_7_win_50", "label": "15試合中 7連勝で +50", "weight": 0.4},
    {"kind": "all_rating", "value": 10, "label": "自分+ランダム3人にレート +10", "weight": 0.1},
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
        ratings[uid] = ratings.get(uid, DEFAULT_RATING) + item["value"]
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
        if others:
            selected = random.sample(others, min(3, len(others)))
        else:
            selected = []

        targets = [drawer] + selected

        for member in targets:
            uid = str(member.id)
            ratings[uid] = ratings.get(uid, DEFAULT_RATING) + item["value"]

        save_ratings(ratings)

        drawer_name = drawer.display_name
        bonus_count = len(selected)
        target_lines = "\n".join([f"・{member.display_name}" for member in targets])

        text = f"""# 【領域展開「坐殺博徒」】

{drawer_name} ……！
正に……豪運……！！

# <:Tobuze:1494883064806113430>「漲る呪力（ボーナス）でトぶぜ」

レート +10

ランダムで{bonus_count}人にも同じ効果

▼対象
{target_lines}"""

        register_channel = get_player_register_channel(guild)
        if register_channel:
            try:
                await register_channel.send(text, delete_after=20)
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

bot = commands.Bot(command_prefix="!", intents=intents)


# =========================
# 状態管理
# =========================
badge_bulk_waiting = {}
# {guild_id: {mode, badge_id, user_id}}

bulk_rate_change_waiting = {}
# {guild_id: user_id}

bulk_profile_edit_waiting = {}
# {guild_id: {"user_id": int, "field": str, "mode": str}}

bulk_admin_waiting = {}
# {guild_id: user_id}

ROOM_KEYS = ("A", "B")

def create_room_state():
    return {
        "game_state": "idle",
        "joined_players": [],
        "current_match": None,
        "prepared_match": None,
        "last_rating_changes": None,
        "last_rating_detail": None,
        "last_profile_snapshots": None,
        "recruit_message": None,
        "selection_message": None,
        "confirm_message": None,
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

# =========================
# 共通ユーティリティ
# =========================
def reset_room_tracking(room_state):
    room_state["session_start_ratings"] = {}
    room_state["session_participants"] = {}


def reset_room_state(room_state):
    room_state["game_state"] = "idle"
    room_state["joined_players"] = []
    room_state["current_match"] = None
    room_state["prepared_match"] = None
    room_state["last_rating_changes"] = None
    room_state["last_rating_detail"] = None
    room_state["last_profile_snapshots"] = None

    room_state["recruit_message"] = None
    room_state["selection_message"] = None
    room_state["confirm_message"] = None
    room_state["disconnect_vote_message"] = None

    room_state["phase1_choices"] = {}
    room_state["phase2_choices"] = {}
    room_state["disconnect_vote"] = None


# =========================
# VC移動
# =========================
def get_progress_channel(guild, room_key):
    room_cfg = ROOM_CHANNELS.get(room_key)
    if room_cfg is None:
        return None
    return guild.get_channel(room_cfg["progress"])


def get_ranking_channel(guild):
    return guild.get_channel(RANKING_CHANNEL_ID)


def get_player_register_channel(guild):
    return guild.get_channel(PLAYER_REGISTER_CHANNEL_ID)


def get_admin_channel(guild):
    return guild.get_channel(ADMIN_CHANNEL_ID)


def get_room_voice_channels(guild, room_key):
    room_cfg = ROOM_CHANNELS.get(room_key)
    if room_cfg is None:
        return None, None, None

    lobby_vc = guild.get_channel(room_cfg["lobby_vc"])
    alpha_vc = guild.get_channel(room_cfg["alpha_vc"])
    bravo_vc = guild.get_channel(room_cfg["bravo_vc"])
    return lobby_vc, alpha_vc, bravo_vc


async def send_progress_message(guild, room_key, content, view=None):
    channel = get_progress_channel(guild, room_key)
    if channel is None:
        return None
    return await channel.send(content, view=view)


async def disable_room_messages(room_state):
    targets = [
        room_state.get("recruit_message"),
        room_state.get("selection_message"),
        room_state.get("confirm_message"),
        room_state.get("disconnect_vote_message"),
    ]

    for msg in targets:
        if msg is None:
            continue
        try:
            if msg.components:
                await msg.edit(view=None)
        except Exception:
            pass


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
        room_state["session_start_ratings"][user_id] = ratings.get(user_id, DEFAULT_RATING)


def get_joined_user_ids(room_state):
    return [str(u.id) for u in room_state["joined_players"]]


def is_joined(room_state, user):
    return user in room_state["joined_players"]


def get_avg_rating(team):
    if not team:
        return DEFAULT_RATING
    return sum(ratings.get(str(user.id), DEFAULT_RATING) for user in team) / len(team)


def get_phase1_count(room_state, choice_name):
    return sum(
        1
        for uid in get_joined_user_ids(room_state)
        if room_state["phase1_choices"].get(uid) == choice_name
    )


def get_alpha_fixed_count(room_state):
    return get_phase1_count(room_state, "alpha")


def get_bravo_fixed_count(room_state):
    return get_phase1_count(room_state, "bravo")


def get_match_k_factor(room_state):
    alpha = get_alpha_fixed_count(room_state)
    beta = get_bravo_fixed_count(room_state)
    return K_TABLE.get((alpha, beta), K_FACTOR)


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
        profile["active_effect"] = active_effect


def get_win_streak_bonus(user_id: int):
    profile = get_player_profile(user_id)
    active_effect = profile.get("active_effect")
    current_streak = profile.get("win_streak", 0)

    if not active_effect:
        return 0

    effect_type = active_effect.get("type")

    if effect_type == "win_streak_bonus":
        bonus_per_streak = int(active_effect.get("bonus_per_streak", 0))
        return current_streak * bonus_per_streak

    if effect_type == "streak_reward":
        target_streak = int(active_effect.get("target_streak", 0))
        reward = int(active_effect.get("reward", 0))
        if current_streak == target_streak:
            return reward

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
    return [
        u
        for u in room_state["joined_players"]
        if room_state["phase1_choices"].get(str(u.id)) == "random"
    ]


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
    if len(targets) == 2:
        return targets
    return []


async def get_member_display_name_by_id(guild, user_id: int):
    member = guild.get_member(user_id)
    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except Exception:
            member = None
    return member.display_name if member else f"ユーザーID:{user_id}"


def create_recruit_text(room_state):
    lines = [
        "【参加者募集】",
        f"{len(room_state['joined_players'])}/{ROOM_CAPACITY}",
        "",
        format_member_lines(
            room_state["joined_players"],
            mention=True,
            include_weapon=True,
            include_badge=False,
            include_rating=False,
        ),
        "",
        "8人揃うとチーム希望選択に進みます。",
    ]
    return "\n".join(lines)


def create_phase1_text(room_state):
    alpha_users = [
        u for u in room_state["joined_players"]
        if room_state["phase1_choices"].get(str(u.id)) == "alpha"
    ]
    bravo_users = [
        u for u in room_state["joined_players"]
        if room_state["phase1_choices"].get(str(u.id)) == "bravo"
    ]
    random_users = [
        u for u in room_state["joined_players"]
        if room_state["phase1_choices"].get(str(u.id)) == "random"
    ]

    lines = [
        "【第一選択】",
        "希望するチームを選んでください。",
        "押し直しで上書きできます。",
        "",
        f"【アルファ（{len(alpha_users)}/{TEAM_SIZE}）】",
        format_member_lines(
            alpha_users,
            mention=False,
            include_weapon=True,
            include_badge=False,
            include_rating=False,
        ),
        "",
        f"【ブラボー（{len(bravo_users)}/{TEAM_SIZE}）】",
        format_member_lines(
            bravo_users,
            mention=False,
            include_weapon=True,
            include_badge=False,
            include_rating=False,
        ),
        "",
        f"【ランダム（{len(random_users)}）】",
        format_member_lines(
            random_users,
            mention=False,
            include_weapon=True,
            include_badge=False,
            include_rating=False,
        ),
    ]
    return "\n".join(lines)


def create_phase2_text(room_state):
    random_users = get_random_users(room_state)
    split_users = [
        u for u in random_users
        if room_state["phase2_choices"].get(str(u.id)) == "split"
    ]
    normal_random_users = [
        u for u in random_users
        if room_state["phase2_choices"].get(str(u.id)) == "random"
    ]

    lines = [
        "【第二選択】",
        "分けを必要とする人はいますか？",
        "",
        f"【分ける（{len(split_users)}/2）】",
        format_member_lines(
            split_users,
            mention=False,
            include_weapon=True,
            include_badge=False,
            include_rating=False,
        ),
        "",
        "【ランダム】",
        format_member_lines(
            normal_random_users,
            mention=False,
            include_weapon=True,
            include_badge=False,
            include_rating=False,
        ),
        "",
        "※ ランダムを選んだ人のみ対象です",
        "※ 2人揃った場合のみ、その2人を別チームに配置します",
        "※ 1人のみの場合は無効です",
    ]
    return "\n".join(lines)


def create_confirm_text(room_state):
    alpha_users = [
        u for u in room_state["joined_players"]
        if room_state["phase1_choices"].get(str(u.id)) == "alpha"
    ]
    bravo_users = [
        u for u in room_state["joined_players"]
        if room_state["phase1_choices"].get(str(u.id)) == "bravo"
    ]
    random_users = [
        u for u in room_state["joined_players"]
        if room_state["phase1_choices"].get(str(u.id)) == "random"
    ]
    split_targets = get_effective_split_targets(room_state)

    lines = [
        "【確認】",
        "この役割で決定でいいですか？",
        "",
        "【アルファ固定】",
        format_member_lines(
            alpha_users,
            mention=False,
            include_weapon=True,
            include_badge=False,
            include_rating=False,
        ),
        "",
        "【ブラボー固定】",
        format_member_lines(
            bravo_users,
            mention=False,
            include_weapon=True,
            include_badge=False,
            include_rating=False,
        ),
        "",
        "【ランダム】",
        format_member_lines(
            random_users,
            mention=False,
            include_weapon=True,
            include_badge=False,
            include_rating=False,
        ),
        "",
        "【分け対象（有効時のみ）】",
        format_member_lines(
            split_targets,
            mention=False,
            include_weapon=True,
            include_badge=False,
            include_rating=False,
        ),
    ]
    return "\n".join(lines)


def create_result_prompt(team_alpha, team_bravo):
    def fmt(team):
        lines = []
        for user in team:
            lines.append(
                build_player_display(
                    user,
                    mention=False,
                    include_weapon=False,
                    include_badge=True,
                    include_rating=True,
                )
            )
        return "\n".join(lines)

    return (
        f"【アルファ】\n{fmt(team_alpha)}\n\n"
        f"【ブラボー】\n{fmt(team_bravo)}\n\n"
        f"!1 アルファ勝ち\n"
        f"!2 ブラボー勝ち\n"
        f"!3 @ユーザー 回線落ち"
    )


def create_finished_prompt():
    return (
        "!1 で次の試合開始\n"
        "!2 で終わる\n"
        "!3 で試合結果の訂正"
    )


def create_disconnect_vote_text(target):
    from datetime import datetime
    now_str = datetime.now().strftime("%Y年%m月%d日")

    target_text = build_player_display(
        target,
        mention=False,
        include_weapon=False,
        include_badge=False,
        include_rating=False,
    )

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


def create_disconnect_confess_text(target):
    target_text = build_player_display(
        target,
        mention=False,
        include_weapon=False,
        include_badge=False,
        include_rating=False,
    )

    return (
        "【回線落ち確定】\n\n"
        "<:Confession:1493076810521378866>\n"
        f"{target_text}「ああ俺の回線が悪かった、これは嘘でも否定でもない」"
    )


def create_disconnect_guilty_text():
    return (
        "【回線落ち確定】\n\n"
        "<:Guilty:1493076857602445485>\n"
        "**有罪**\n"
        "**没収**"
    )


def create_disconnect_not_established_text():
    return (
        "【回線落ち不成立】\n"
        "有罪票が規定数に達しなかったため、回線落ち処理は行いません。\n"
        "通常の試合結果入力に戻ります。"
    )


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
        end_rate = ratings.get(user_id, DEFAULT_RATING)
        diff = end_rate - start_rate
        rows.append((diff, end_rate, member, start_rate))
    rows.sort(key=lambda x: (-x[0], -x[1], x[2].display_name.lower()))

    lines = ["【今回の部屋のレート増減】"]

    for diff, end_rate, member, start_rate in rows:
        lines.append(
            build_player_display(
                member,
                mention=False,
                include_weapon=False,
                include_badge=True,
                include_rating=False,
                include_rate_change=True,
                old_rating=start_rate,
                new_rating=end_rate,
            )
        )

    return "\n".join(lines)


# =========================
# 武器登録 / XP登録
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
            old_rating = ratings.get(str(user.id), DEFAULT_RATING)
            ratings[str(user.id)] = new_rating
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
            user = interaction.user
            profile = get_player_profile(user.id)

            weapon = profile.get("weapon", "未登録")
            xp = profile.get("xp", "未登録")
            rate = ratings.get(str(user.id), DEFAULT_RATING)

            display_name = build_player_display(
                user,
                mention=False,
                include_weapon=False,
                include_badge=True,
                include_rating=False,
            )

            await admin_channel.send(
                "【登録通知】\n"
                f"{display_name} が登録を完了しました\n"
                f"武器: {weapon}\n"
                f"最高XP: {xp}\n"
                f"現在レート: {rate}"
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
            select = discord.ui.Select(
                placeholder="表示するバッジを選択",
                options=options,
                min_values=1,
                max_values=1
            )

            async def select_callback(interaction: discord.Interaction):
                if interaction.user.id != self.user.id:
                    await interaction.response.send_message("自分のバッジだけ変更できます", ephemeral=True)
                    return

                selected = select.values[0]
                profile = get_player_profile(self.user.id)
                profile["selected_badge"] = selected
                save_player_profiles(player_profiles)

                badge_data = BADGE_DEFINITIONS.get(selected, {})
                badge_label = badge_data.get("label", selected)

                await interaction.response.send_message(f"バッジを変更しました: {badge_label}", ephemeral=True)

            select.callback = select_callback
            self.add_item(select)


class CoinMenuView(discord.ui.View):
    def __init__(self, user):
        super().__init__(timeout=60)
        self.user = user

    @discord.ui.button(
        label="ガチャ",
        style=discord.ButtonStyle.success,
        row=0
    )    
    async def gacha_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("自分のメニューだけ操作できます", ephemeral=True)
            return

        coins = get_player_profile(self.user.id).get("coins", 0)

        if coins < GACHA_COST:
            await interaction.response.send_message("コインが足りません", ephemeral=True)
            return

        remove_coin(self.user.id, GACHA_COST)
        save_player_profiles(player_profiles)

        item = draw_gacha_item()
        await apply_gacha_result(interaction.guild, self.user.id, item)

        result_text = item["label"]

        admin_channel = get_admin_channel(interaction.guild)
        if admin_channel:
            name = build_player_display(
                interaction.user,
                mention=False,
                include_weapon=False,
                include_badge=True,
                include_rating=False,
            )
            await admin_channel.send(
                f"【ガチャ結果】\n{name}\n→ {result_text}"
            )

        await interaction.response.send_message(
            f"ガチャ結果\n→ {result_text}",
            ephemeral=True
        )

    @discord.ui.button(
        label="チケット一覧",
        style=discord.ButtonStyle.primary,
        row=0
    )
    async def ticket_list_button(self, interaction: discord.Interaction, button: discord.ui.Button):
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

    @discord.ui.button(
        label="チケット使用",
        style=discord.ButtonStyle.danger,
        row=0
    )
    async def ticket_use_button(self, interaction: discord.Interaction, button: discord.ui.Button):
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

        options = []
        for i, ticket in enumerate(tickets):
            options.append(
                discord.SelectOption(
                    label=ticket.get("label", ticket.get("ticket_id", "不明"))[:100],
                    value=str(i)
                )
            )

        select = discord.ui.Select(
            placeholder="使用するチケットを選択",
            options=options,
            min_values=1,
            max_values=1
        )

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
                name = build_player_display(
                    select_interaction.user,
                    mention=False,
                    include_weapon=False,
                    include_badge=True,
                    include_rating=False,
                )
                label = active_ticket.get("label", active_ticket.get("ticket_id", "不明"))

                await admin_channel.send(
                    f"【チケット使用】\n{name}\n→ {label}"
                )

            await select_interaction.response.send_message(
                "チケットを使用しました\n\n" + get_active_effect_text(self.user.id),
                ephemeral=True
            )

        select.callback = select_callback

        view = discord.ui.View(timeout=60)
        view.add_item(select)

        await interaction.response.send_message(
            "使用するチケットを選んでください",
            view=view,
            ephemeral=True
        )


class PlayerRegisterView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="プレイヤー登録",
        style=discord.ButtonStyle.primary,
        custom_id="player_register_button",
        row=0
    )
    async def register_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PlayerRegisterModal())

    @discord.ui.button(
        label="バッジ設定",
        style=discord.ButtonStyle.danger,
        custom_id="badge_select_button",
        row=0
    )
    async def badge_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        profile = get_player_profile(interaction.user.id)
        owned = profile.get("owned_badges", [])

        if not owned:
            await interaction.response.send_message("選べるバッジがありません", ephemeral=True)
            return

        await interaction.response.send_message(
            "表示するバッジを選択してください",
            view=BadgeSelectView(interaction.user),
            ephemeral=True
        )

    @discord.ui.button(
        label="コイン",
        style=discord.ButtonStyle.success,
        custom_id="coin_menu_button",
        row=0
    )
    async def coin_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try_claim_passive_coin(interaction.user.id)
        save_player_profiles(player_profiles)

        profile = get_player_profile(interaction.user.id)
        coins = profile.get("coins", 0)

        text = (
            f"現在 {coins} / {COIN_LIMIT} コインを持っています。どうしますか？\n\n"
            f"{get_active_effect_text(interaction.user.id)}"
        )

        await interaction.response.send_message(
            text,
            view=CoinMenuView(interaction.user),
            ephemeral=True
        )



async def post_player_register_message(guild):
    channel = get_player_register_channel(guild)
    if channel is None:
        return None

    content = (
        "【プレイヤー登録】\n\n"
        "武器登録と最高XP登録をしてください。\n"
        "サーバー加入直後とシーズン開始時は、登録したXPに応じてレートが補正されます。\n"
        "※ 初期補正権がある場合のみ、XP補正が適用されます。\n"
        "※ 一度でも試合に参加した後は、初期補正権を失います。\n"
        "※ ボタンを押した人にしか結果は表示されません。"
    )

    guild_key = str(guild.id)

    saved_ids = bot_state.get("player_register_message_ids", {})
    saved_message_id = saved_ids.get(guild_key)

    if saved_message_id:
        try:
            msg = await channel.fetch_message(saved_message_id)
            await msg.edit(content=content, view=PlayerRegisterView())
            return msg
        except Exception:
            pass

    msg = await channel.send(content, view=PlayerRegisterView())

    if "player_register_message_ids" not in bot_state:
        bot_state["player_register_message_ids"] = {}

    bot_state["player_register_message_ids"][guild_key] = msg.id
    save_bot_state(bot_state)

    return msg

# =========================
# メッセージ/ビュー制御
# =========================
class BaseControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    def disable_all_buttons(self):
        for child in self.children:
            child.disabled = True


class RecruitView(BaseControlView):
    def __init__(self, room_key, room_state):
        super().__init__()
        self.room_key = room_key
        self.room_state = room_state

    @discord.ui.button(label="参加", style=discord.ButtonStyle.primary)
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user

        if self.room_state["game_state"] != "recruiting":
            await interaction.response.send_message("今は募集していません", ephemeral=True)
            return

        if is_joined(self.room_state, user):
            await interaction.response.send_message("既に参加しています", ephemeral=True)
            return

        if len(self.room_state["joined_players"]) >= ROOM_CAPACITY:
            await interaction.response.send_message("満員です", ephemeral=True)
            return

        self.room_state["joined_players"].append(user)
        ensure_session_player(self.room_state, user)

        await interaction.response.edit_message(content=create_recruit_text(self.room_state), view=self)

        if len(self.room_state["joined_players"]) == ROOM_CAPACITY:
            host_id = str(interaction.user.id)
            ratings[host_id] = ratings.get(host_id, DEFAULT_RATING) + 5
            save_ratings(ratings)

            self.disable_all_buttons()
            await interaction.message.edit(view=self)
            await begin_phase1(interaction.guild, self.room_key)

    @discord.ui.button(label="抜ける", style=discord.ButtonStyle.gray)
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user

        if self.room_state["game_state"] != "recruiting":
            await interaction.response.send_message("今は抜けられません", ephemeral=True)
            return

        if user not in self.room_state["joined_players"]:
            await interaction.response.send_message("まだ参加していません", ephemeral=True)
            return

        self.room_state["joined_players"].remove(user)
        await interaction.response.edit_message(content=create_recruit_text(self.room_state), view=self)


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
        await interaction.response.edit_message(content=create_phase1_text(self.room_state), view=self)

        if all_joined_selected_phase1(self.room_state):
            self.disable_all_buttons()
            await interaction.message.edit(view=self)
            if should_show_phase2(self.room_state):
                await begin_phase2(interaction.guild, self.room_key)
            else:
                await begin_confirm(interaction.guild, self.room_key)

    @discord.ui.button(label="アルファ", style=discord.ButtonStyle.primary)
    async def alpha_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_choice(interaction, "alpha")

    @discord.ui.button(label="ブラボー", style=discord.ButtonStyle.primary)
    async def bravo_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_choice(interaction, "bravo")

    @discord.ui.button(label="ランダム", style=discord.ButtonStyle.secondary)
    async def random_button(self, interaction: discord.Interaction, button: discord.ui.Button):
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
            split_count = sum(
                1 for u in random_users
                if self.room_state["phase2_choices"].get(str(u.id)) == "split"
            )
            if current != "split" and split_count >= 2:
                await interaction.response.send_message("「分ける」は2人までです", ephemeral=True)
                return

        self.room_state["phase2_choices"][uid] = choice_name
        await interaction.response.edit_message(content=create_phase2_text(self.room_state), view=self)

        if all_random_selected_phase2(self.room_state):
            self.disable_all_buttons()
            await interaction.message.edit(view=self)
            await begin_confirm(interaction.guild, self.room_key)

    @discord.ui.button(label="分ける", style=discord.ButtonStyle.primary)
    async def split_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_choice(interaction, "split")

    @discord.ui.button(label="ランダム", style=discord.ButtonStyle.secondary)
    async def random_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_choice(interaction, "random")


class ConfirmView(BaseControlView):
    def __init__(self, room_key, room_state):
        super().__init__()
        self.room_key = room_key
        self.room_state = room_state

    @discord.ui.button(label="決定", style=discord.ButtonStyle.success)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        if user not in self.room_state["joined_players"]:
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
        await send_progress_message(interaction.guild, self.room_key, "試合開始するなら !1 を送ってください")

    @discord.ui.button(label="やり直し", style=discord.ButtonStyle.danger)
    async def redo_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        if user not in self.room_state["joined_players"]:
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


class DisconnectVoteView(BaseControlView):
    def __init__(self, room_key, room_state):
        super().__init__()
        self.room_key = room_key
        self.room_state = room_state

    async def record_self_vote(self, interaction: discord.Interaction, vote_value: str):
        if self.room_state["game_state"] != "disconnect_vote" or self.room_state["disconnect_vote"] is None:
            await interaction.response.send_message("今は投票中ではありません", ephemeral=True)
            return

        user = interaction.user
        uid = str(user.id)
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

        user = interaction.user
        uid = str(user.id)
        target_id = self.room_state["disconnect_vote"]["target_id"]

        if uid == target_id:
            await interaction.response.send_message("対象者本人は有罪/無罪を押せません", ephemeral=True)
            return

        if self.room_state["current_match"] is None:
            await interaction.response.send_message("試合情報がありません", ephemeral=True)
            return

        if user not in (self.room_state["current_match"][0] + self.room_state["current_match"][1]):
            await interaction.response.send_message("今回の試合参加者ではありません", ephemeral=True)
            return

        self.room_state["disconnect_vote"]["jury_votes"][uid] = vote_value
        await interaction.response.send_message("投票を受け付けました", ephemeral=True)

        guilty_count = sum(
            1 for v in self.room_state["disconnect_vote"]["jury_votes"].values()
            if v == "guilty"
        )
        voters = [
            u for u in (self.room_state["current_match"][0] + self.room_state["current_match"][1])
            if str(u.id) != target_id
        ]

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
    async def confess_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.record_self_vote(interaction, "confess")

    @discord.ui.button(label="否認", style=discord.ButtonStyle.secondary)
    async def deny_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.record_self_vote(interaction, "deny")

    @discord.ui.button(label="有罪", style=discord.ButtonStyle.primary)
    async def guilty_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.record_jury_vote(interaction, "guilty")

    @discord.ui.button(label="無罪", style=discord.ButtonStyle.success)
    async def innocent_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.record_jury_vote(interaction, "innocent")



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
        rate = ratings.get(str(member.id), DEFAULT_RATING)
        display_text = build_player_display(
            member,
            mention=False,
            include_weapon=False,
            include_badge=True,
            include_rating=False,
        )
        ranking_data.append((rate, member.display_name.lower(), display_text))

    ranking_data.sort(key=lambda x: (-x[0], x[1]))

    if not ranking_data:
        return ["# 【レートランキング】", "ランキング対象のメンバーがいません"]

    lines = ["# 【レートランキング】"]
    for i, (rate, _, display_text) in enumerate(ranking_data, start=1):
        lines.append(f"# #{i} {display_text} - {rate}")

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
async def begin_recruit(guild, room_key):
    room_state = room_states[room_key]

    room_state["game_state"] = "recruiting"
    view = RecruitView(room_key, room_state)
    room_state["recruit_message"] = await send_progress_message(
        guild,
        room_key,
        create_recruit_text(room_state),
        view=view
    )


async def begin_phase1(guild, room_key):
    room_state = room_states[room_key]

    room_state["game_state"] = "pref1"
    view = Phase1ChoiceView(room_key, room_state)
    room_state["selection_message"] = await send_progress_message(
        guild,
        room_key,
        create_phase1_text(room_state),
        view=view
    )


async def begin_phase2(guild, room_key):
    room_state = room_states[room_key]

    room_state["game_state"] = "pref2"
    random_users = get_random_users(room_state)
    for user in random_users:
        room_state["phase2_choices"].pop(str(user.id), None)

    view = Phase2ChoiceView(room_key, room_state)
    room_state["selection_message"] = await send_progress_message(
        guild,
        room_key,
        create_phase2_text(room_state),
        view=view
    )


async def begin_confirm(guild, room_key):
    room_state = room_states[room_key]

    room_state["game_state"] = "confirm"
    view = ConfirmView(room_key, room_state)
    room_state["confirm_message"] = await send_progress_message(
        guild,
        room_key,
        create_confirm_text(room_state),
        view=view
    )


async def start_game(ctx, room_key):
    room_state = room_states[room_key]

    if not room_state["prepared_match"]:
        await ctx.send("試合情報がないよ")
        return

    room_state["current_match"] = room_state["prepared_match"]
    room_state["prepared_match"] = None
    room_state["game_state"] = "playing"

    team_alpha, team_bravo = room_state["current_match"]
    mark_match_played_for_members(team_alpha + team_bravo)
    await move_members_to_vc(ctx.guild, room_key, team_alpha, team_bravo)
    await ctx.send(create_result_prompt(team_alpha, team_bravo))


async def next_game(ctx, room_key):
    room_state = room_states[room_key]

    if not room_state["prepared_match"]:
        try:
            room_state["prepared_match"] = make_teams_from_choices(room_state)
        except Exception as e:
            await ctx.send(f"次の試合情報を作れませんでした: {e}")
            return

    room_state["current_match"] = room_state["prepared_match"]
    room_state["prepared_match"] = None
    room_state["game_state"] = "playing"

    team_alpha, team_bravo = room_state["current_match"]
    mark_match_played_for_members(team_alpha + team_bravo)
    await move_members_to_vc(ctx.guild, room_key, team_alpha, team_bravo)
    await ctx.send(create_result_prompt(team_alpha, team_bravo))


def build_rating_update_lines(room_state, next_team_alpha, next_team_bravo, title="【レート更新】", bonus_text=None):
    if bonus_text:
        bonus_text = bonus_text.split("（")[0].strip()
        lines = [f"{title}{bonus_text}"]
    else:
        lines = [title]

    lines.append("")

    current_match = room_state.get("current_match")
    if current_match:
        team_alpha, team_bravo = current_match
        ordered_players = team_alpha + team_bravo
    else:
        ordered_players = next_team_alpha + next_team_bravo

    last_rating_changes = room_state.get("last_rating_changes") or {}
    detail_map = room_state.get("last_rating_detail") or {}

    for user in ordered_players:
        uid = str(user.id)

        old = last_rating_changes.get(uid, ratings.get(uid, DEFAULT_RATING))
        new = ratings.get(uid, DEFAULT_RATING)

        detail = detail_map.get(uid)

        name = build_player_display(
            user,
            mention=False,
            include_weapon=False,
            include_badge=True,
            include_rating=False,
            include_rate_change=False,
        )

        if detail:
            base = detail["base"]
            final = detail["final"]

            base_str = f"+{base}" if base >= 0 else f"{base}"
            final_str = f"+{final}" if final >= 0 else f"{final}"

            if base != final:
                change_text = f"({base_str} → {final_str})"
            else:
                change_text = f"({final_str})"
        else:
            diff = new - old
            diff_str = f"+{diff}" if diff >= 0 else f"{diff}"
            change_text = f"({diff_str})"

        lines.append(f"{name}: {old} → {new} {change_text}")

    lines.append("")
    lines.append("次回のチーム分け")

    alpha_names = " ".join(
        build_player_display(
            u,
            mention=False,
            include_weapon=False,
            include_badge=False,
            include_rating=False,
            include_rate_change=False,
        )
        for u in next_team_alpha
    )

    bravo_names = " ".join(
        build_player_display(
            u,
            mention=False,
            include_weapon=False,
            include_badge=False,
            include_rating=False,
            include_rate_change=False,
        )
        for u in next_team_bravo
    )

    lines.append(f"アルファ: {alpha_names}")
    lines.append(f"ブラボー: {bravo_names}")

    return lines


async def process_result(ctx, room_key, winner_num: int):
    room_state = room_states[room_key]

    if not room_state["current_match"]:
        await ctx.send("試合がないよ")
        return

    team_alpha, team_bravo = room_state["current_match"]
    avg_alpha = get_avg_rating(team_alpha)
    avg_bravo = get_avg_rating(team_bravo)

    s_alpha, s_bravo = (1, 0) if winner_num == 1 else (0, 1)

    match_k = get_match_k_factor(room_state)

    room_state["last_profile_snapshots"] = {}
    for user in team_alpha + team_bravo:
        uid = str(user.id)
        profile = get_player_profile(user.id)
        room_state["last_profile_snapshots"][uid] = {
            "win_streak": profile.get("win_streak", 0),
            "active_effect": json.loads(json.dumps(profile.get("active_effect"))),
            "tickets": json.loads(json.dumps(profile.get("tickets", []))),
        }

    if winner_num == 1:
        winners = team_alpha
        losers = team_bravo
    else:
        winners = team_bravo
        losers = team_alpha

    update_win_streaks(winners, losers)

    room_state["last_rating_changes"] = {}
    room_state["last_rating_detail"] = {}

    for user in team_alpha + team_bravo:
        room_state["last_rating_changes"][str(user.id)] = ratings.get(str(user.id), DEFAULT_RATING)

    for user in team_alpha:
        uid = str(user.id)
        old = ratings.get(uid, DEFAULT_RATING)

        base_new = elo_update(old, avg_bravo, s_alpha, K=match_k)
        base_change = base_new - old

        multiplier = get_rate_multiplier(user.id)
        after_effect = int(base_change * multiplier)

        streak_bonus = get_win_streak_bonus(user.id) if user in winners else 0
        final_change = after_effect + PARTICIPATION_BONUS + streak_bonus

        new = old + final_change
        ratings[uid] = new

        room_state["last_rating_detail"][uid] = {
            "base": base_change,
            "final": final_change,
            "multiplier": multiplier,
        }

    for user in team_bravo:
        uid = str(user.id)
        old = ratings.get(uid, DEFAULT_RATING)

        base_new = elo_update(old, avg_alpha, s_bravo, K=match_k)
        base_change = base_new - old

        multiplier = get_rate_multiplier(user.id)
        after_effect = int(base_change * multiplier)

        streak_bonus = get_win_streak_bonus(user.id) if user in winners else 0
        final_change = after_effect + PARTICIPATION_BONUS + streak_bonus

        new = old + final_change
        ratings[uid] = new

        room_state["last_rating_detail"][uid] = {
            "base": base_change,
            "final": final_change,
            "multiplier": multiplier,
        }

    for user in team_alpha + team_bravo:
        consume_active_effect_match(user.id)

    save_ratings(ratings)
    save_player_profiles(player_profiles)

    room_state["prepared_match"] = make_teams_from_choices(room_state)
    next_team_alpha, next_team_bravo = room_state["prepared_match"]

    lines = build_rating_update_lines(
        room_state,
        next_team_alpha,
        next_team_bravo,
        title="【レート更新】",
        bonus_text=f"全員に +{PARTICIPATION_BONUS} が追加されました（K={match_k}）",
    )

    room_state["game_state"] = "finished"

    await ctx.send("\n".join(lines))
    await ctx.send(create_finished_prompt())

async def end_room(ctx, room_key):
    room_state = room_states[room_key]
    summary_text = create_room_summary_text(room_state)

    grant_room_coin_lottery(room_state)

    await disable_room_messages(room_state)
    await move_members_to_lobby(ctx.guild, room_key, room_state)
    await post_ranking(ctx.guild)

    reset_room_state(room_state)
    reset_room_tracking(room_state)

    if summary_text:
        await ctx.send(summary_text)
    await ctx.send("部屋作成をやめました。次の募集をするときは !部屋作成 を使ってね")
    
async def start_disconnect_vote(ctx, room_key, member):
    room_state = room_states[room_key]

    if not room_state["current_match"]:
        await ctx.send("試合情報がないよ")
        return

    all_players = room_state["current_match"][0] + room_state["current_match"][1]
    if member not in all_players:
        await ctx.send("そのユーザーは今回の試合に参加していません")
        return

    room_state["disconnect_vote"] = {
        "target_id": str(member.id),
        "self_vote": None,
        "jury_votes": {},
    }
    room_state["game_state"] = "disconnect_vote"

    view = DisconnectVoteView(room_key, room_state)
    room_state["disconnect_vote_message"] = await ctx.send(
        create_disconnect_vote_text(member),
        view=view
    )


async def apply_disconnect_rating_change(ctx, room_key, member):
    room_state = room_states[room_key]

    team_alpha, team_bravo = room_state["current_match"]
    all_players = team_alpha + team_bravo

    room_state["last_rating_changes"] = {}
    room_state["last_rating_detail"] = None
    room_state["last_profile_snapshots"] = None

    for user in all_players:
        room_state["last_rating_changes"][str(user.id)] = ratings.get(str(user.id), DEFAULT_RATING)

    for user in all_players:
        uid = str(user.id)
        if user.id == member.id:
            ratings[uid] = ratings.get(uid, DEFAULT_RATING) - DISCONNECT_PENALTY
        else:
            ratings[uid] = ratings.get(uid, DEFAULT_RATING) + DISCONNECT_REWARD

    save_ratings(ratings)

    room_state["prepared_match"] = make_teams_from_choices(room_state)
    next_team_alpha, next_team_bravo = room_state["prepared_match"]

    lines = build_rating_update_lines(
        room_state,
        next_team_alpha,
        next_team_bravo,
        title="【レート更新】",
        bonus_text=f"回線落ち: -{DISCONNECT_PENALTY} / その他: +{DISCONNECT_REWARD}",
    )

    room_state["game_state"] = "finished"

    await ctx.send("\n".join(lines))
    await ctx.send(create_finished_prompt())


async def finalize_disconnect_vote(guild, room_key, member, forced_by_confession: bool):
    room_state = room_states[room_key]

    progress_channel = get_progress_channel(guild, room_key)
    if progress_channel is None:
        return

    if forced_by_confession:
        await progress_channel.send(create_disconnect_confess_text(member))
    else:
        await progress_channel.send(create_disconnect_guilty_text())

    fake_ctx = type("Ctx", (), {"guild": guild, "send": progress_channel.send})()
    await apply_disconnect_rating_change(fake_ctx, room_key, member)
    room_state["disconnect_vote"] = None


async def resolve_disconnect_not_established(guild, room_key):
    room_state = room_states[room_key]

    progress_channel = get_progress_channel(guild, room_key)
    if progress_channel is None:
        return

    room_state["game_state"] = "playing"
    room_state["disconnect_vote"] = None

    await progress_channel.send(create_disconnect_not_established_text())
    if room_state["current_match"]:
        team_alpha, team_bravo = room_state["current_match"]
        await progress_channel.send(create_result_prompt(team_alpha, team_bravo))


async def undo_result(ctx, room_key):
    room_state = room_states[room_key]

    if not room_state["last_rating_changes"]:
        await ctx.send("戻せる試合結果がありません")
        return

    for user_id, old_rate in room_state["last_rating_changes"].items():
        ratings[user_id] = old_rate

    snapshots = room_state.get("last_profile_snapshots") or {}
    for user_id, snapshot in snapshots.items():
        profile = get_player_profile(int(user_id))
        profile["win_streak"] = snapshot.get("win_streak", 0)
        profile["active_effect"] = snapshot.get("active_effect")
        profile["tickets"] = snapshot.get("tickets", [])

    save_ratings(ratings)
    save_player_profiles(player_profiles)

    room_state["last_rating_changes"] = None
    room_state["last_rating_detail"] = None
    room_state["last_profile_snapshots"] = None
    room_state["prepared_match"] = None
    room_state["disconnect_vote"] = None
    room_state["disconnect_vote_message"] = None
    room_state["game_state"] = "playing"

    await ctx.send("試合結果を訂正しました")
    if room_state["current_match"]:
        team_alpha, team_bravo = room_state["current_match"]
        await ctx.send(create_result_prompt(team_alpha, team_bravo))




# =========================
# 状態別コマンド処理
# =========================
async def handle_ready(ctx, room_key, cmd_num: int):
    if cmd_num == 1:
        await start_game(ctx, room_key)
    else:
        await ctx.send("今は !1 で試合開始")


async def handle_playing(ctx, room_key, cmd_num: int):
    if cmd_num == 1:
        await process_result(ctx, room_key, 1)
        return

    if cmd_num == 2:
        await process_result(ctx, room_key, 2)
        return

    if cmd_num == 3:
        if ctx.message.mentions:
            await start_disconnect_vote(ctx, room_key, ctx.message.mentions[0])
        else:
            await ctx.send("回線落ちは !3 @ユーザー で送ってくれ")
        return

    await ctx.send("試合中は !1 !2 !3 を使ってくれ")


async def handle_finished(ctx, room_key, cmd_num: int):
    if cmd_num == 1:
        await next_game(ctx, room_key)
        return

    if cmd_num == 2:
        await end_room(ctx, room_key)
        return

    if cmd_num == 3:
        await undo_result(ctx, room_key)
        return

    await ctx.send("今は !1 !2 !3 を使ってくれ")


async def handle_disconnect_vote_state(ctx, room_key, cmd_num: int):
    await ctx.send("今は投票中です。ボタンで投票してください。")


STATE_HANDLERS = {
    "ready": handle_ready,
    "playing": handle_playing,
    "finished": handle_finished,
    "disconnect_vote": handle_disconnect_vote_state,
}


async def dispatch_number_command(ctx, room_key, cmd_num: int):
    room_state = room_states[room_key]
    handler = STATE_HANDLERS.get(room_state["game_state"])
    if handler is None:
        await ctx.send(f"今は !{cmd_num} を受け付ける状態じゃない")
        return
    await handler(ctx, room_key, cmd_num)


# =========================
# チャンネル制限
# =========================

async def ensure_progress_channel(ctx):
    room_key = get_room_key_by_channel_id(ctx.channel.id)
    if room_key is None:
        await ctx.send("このコマンドは試合進行チャンネルで使ってください。")
        return False
    return True


async def ensure_admin_channel(ctx):
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("このコマンドは運営チャンネルで使ってください")
        return False
    return True

# =========================
# 初期補正権 管理
# =========================
async def get_human_members(guild):
    try:
        members = [member async for member in guild.fetch_members(limit=None)]
    except Exception:
        members = guild.members
    return [m for m in members if not m.bot]


def grant_initial_bonus_permission(user_id: int):
    profile = get_player_profile(user_id)
    profile["can_apply_initial_bonus"] = True
    profile["initial_applied"] = False


def revoke_initial_bonus_permission(user_id: int):
    profile = get_player_profile(user_id)
    profile["can_apply_initial_bonus"] = False


# =========================
# レート一括変更モード
# =========================
async def process_badge_bulk_message(message: discord.Message):
    guild = message.guild
    if guild is None:
        return False

    state = badge_bulk_waiting.get(guild.id)
    if not state:
        return False

    if state["user_id"] != message.author.id:
        return False

    content = message.content.strip()

    if not content:
        badge_bulk_waiting.pop(guild.id, None)
        await message.channel.send("入力が空だったので終了しました")
        return True

    if content in ("キャンセル", "中止", "!キャンセル"):
        badge_bulk_waiting.pop(guild.id, None)
        await message.channel.send("バッジ操作を終了しました")
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
    if not content:
        bulk_rate_change_waiting.pop(guild.id, None)
        await message.channel.send("入力が空だったのでレート値変更モードを終了しました。")
        return True

    if content in ("キャンセル", "中止", "!キャンセル", "!中止"):
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

        user_id = int(user_id_text)
        new_rating = int(new_rating_text)

        if new_rating < 0:
            error_lines.append(f"{line_no}行目: レートは0以上にしてください -> {line}")
            continue

        old_rating = ratings.get(str(user_id), DEFAULT_RATING)
        ratings[str(user_id)] = new_rating
        name = await get_member_display_name_by_id(guild, user_id)
        success_lines.append(f"{name}: {old_rating} → {new_rating}")
        changed_any = True

    if changed_any:
        save_ratings(ratings)

    bulk_rate_change_waiting.pop(guild.id, None)

    lines = ["【レート値変更結果】"]
    if success_lines:
        lines.append("")
        lines.append("【成功】")
        lines.extend(success_lines)

    if error_lines:
        lines.append("")
        lines.append("【失敗】")
        lines.extend(error_lines)

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
    if not state:
        return False

    if state["user_id"] != message.author.id:
        return False

    content = message.content.strip()

    if not content:
        bulk_profile_edit_waiting.pop(guild.id, None)
        await message.channel.send("入力が空だったのでプロフィール一括編集モードを終了しました。")
        return True

    if content in ("キャンセル", "中止", "!キャンセル", "!中止"):
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
            if mode == "clear":
                profile["weapon"] = None
                success_lines.append(f"{name}: {old_value} → None")
                changed_any = True
            else:
                profile["weapon"] = value_text
                success_lines.append(f"{name}: {old_value} → {value_text}")
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
                xp = int(value_text)
                profile["xp"] = xp
                success_lines.append(f"{name}: {old_value} → {xp}")
                changed_any = True

        elif field == "initial_applied":
            old_value = profile.get("initial_applied")
            new_value = (mode == "set_true")
            profile["initial_applied"] = new_value
            success_lines.append(f"{name}: {old_value} → {new_value}")
            changed_any = True

        elif field == "can_apply_initial_bonus":
            old_value = profile.get("can_apply_initial_bonus")
            new_value = (mode == "set_true")
            profile["can_apply_initial_bonus"] = new_value
            success_lines.append(f"{name}: {old_value} → {new_value}")
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
        lines.append("")
        lines.append("【成功】")
        lines.extend(success_lines)

    if error_lines:
        lines.append("")
        lines.append("【失敗】")
        lines.extend(error_lines)

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

    if not content:
        bulk_admin_waiting.pop(guild.id, None)
        await message.channel.send("入力が空だったので運営一括モードを終了しました。")
        return True

    if content in ("キャンセル", "中止", "!キャンセル", "!中止"):
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
            ratings[str(user_id)] = new_rating
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
            coins = int(args[0])
            if coins > COIN_LIMIT:
                coins = COIN_LIMIT
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
        lines.append("")
        lines.append("【成功】")
        lines.extend(success_lines)

    if error_lines:
        lines.append("")
        lines.append("【失敗】")
        lines.extend(error_lines)

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
    bot.add_view(PlayerRegisterView())

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    handled = await process_badge_bulk_message(message)
    if handled:
        return

    handled = await process_bulk_rate_change_message(message)
    if handled:
        return

    handled = await process_bulk_profile_edit_message(message)
    if handled:
        return

    handled = await process_bulk_admin_message(message)
    if handled:
        return

    await bot.process_commands(message)


@bot.command()
async def 部屋作成(ctx):
    room_key = get_room_key_by_channel_id(ctx.channel.id)
    if room_key is None:
        await ctx.send("このコマンドは試合進行チャンネルで使ってください。")
        return

    room_state = room_states[room_key]

    if room_state["game_state"] != "idle":
        await ctx.send("この部屋はすでに進行中です")
        return

    reset_room_state(room_state)
    reset_room_tracking(room_state)
    await begin_recruit(ctx.guild, room_key)


@bot.command(name="1")
async def command_one(ctx):
    room_key = get_room_key_by_channel_id(ctx.channel.id)
    if room_key is None:
        await ctx.send("このコマンドは試合進行チャンネルで使ってください。")
        return
    await dispatch_number_command(ctx, room_key, 1)


@bot.command(name="2")
async def command_two(ctx):
    room_key = get_room_key_by_channel_id(ctx.channel.id)
    if room_key is None:
        await ctx.send("このコマンドは試合進行チャンネルで使ってください。")
        return
    await dispatch_number_command(ctx, room_key, 2)


@bot.command(name="3")
async def command_three(ctx):
    room_key = get_room_key_by_channel_id(ctx.channel.id)
    if room_key is None:
        await ctx.send("このコマンドは試合進行チャンネルで使ってください。")
        return
    await dispatch_number_command(ctx, room_key, 3)


@bot.command(name="ランキング")
async def ランキング(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if not await ensure_admin_channel(ctx):
        return

    await post_ranking(ctx.guild)
    await ctx.send("ランキングを更新しました。")

@bot.command(name="武器一覧")
async def weapon_list(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if not await ensure_admin_channel(ctx):
        return

    try:
        members = [member async for member in ctx.guild.fetch_members(limit=None)]
    except Exception:
        members = ctx.guild.members

    human_members = [m for m in members if not m.bot]

    if not human_members:
        await ctx.send("プレイヤーがいません")
        return

    human_members.sort(key=lambda m: m.display_name.lower())

    lines = ["【武器一覧】"]

    for member in human_members:
        profile = get_player_profile(member.id)
        weapon = profile.get("weapon")

        if not weapon:
            weapon = "未登録"

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
    if not await ensure_admin_channel(ctx):
        return

    try:
        members = [member async for member in ctx.guild.fetch_members(limit=None)]
    except Exception:
        members = ctx.guild.members

    human_members = [m for m in members if not m.bot]

    if not human_members:
        await ctx.send("プレイヤーがいません")
        return

    human_members.sort(key=lambda m: m.display_name.lower())

    lines = ["【XP一覧】"]

    for member in human_members:
        profile = get_player_profile(member.id)
        xp = profile.get("xp")

        if xp is None:
            xp = "未登録"

        lines.append(f"{member.id} {xp}")

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

@bot.command(name="秘匿ランキング")
async def secret_ranking(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if not await ensure_admin_channel(ctx):
        return

    await post_secret_ranking(ctx.guild)
    await ctx.send("秘匿ランキングを送信しました。")


@bot.command(name="一括武器設定")
async def bulk_set_weapon(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if not await ensure_admin_channel(ctx):
        return

    bulk_profile_edit_waiting[ctx.guild.id] = {
        "user_id": ctx.author.id,
        "field": "weapon",
        "mode": "set",
    }

    await ctx.send(
        "武器一括設定モードに入りました。\n"
        "次の1メッセージで、1行に1人ずつ\n"
        "ユーザーID 武器名\n"
        "の形式で送ってください。\n\n"
        "例:\n"
        "123456789012345678 スシ\n"
        "987654321098765432 52ガロン\n\n"
        "やめるときは キャンセル と送ってください。"
    )


@bot.command(name="一括武器削除")
async def bulk_clear_weapon(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if not await ensure_admin_channel(ctx):
        return

    bulk_profile_edit_waiting[ctx.guild.id] = {
        "user_id": ctx.author.id,
        "field": "weapon",
        "mode": "clear",
    }

    await ctx.send(
        "武器一括削除モードに入りました。\n"
        "次の1メッセージで、1行に1人ずつ\n"
        "ユーザーID\n"
        "の形式で送ってください。\n\n"
        "例:\n"
        "123456789012345678\n"
        "987654321098765432\n\n"
        "やめるときは キャンセル と送ってください。"
    )

@bot.command(name="バッジ付与")
async def grant_badge(ctx, badge_id: str):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if not await ensure_admin_channel(ctx):
        return

    if badge_id not in BADGE_DEFINITIONS:
        await ctx.send("そのバッジIDは存在しません")
        return

    badge_bulk_waiting[ctx.guild.id] = {
        "mode": "grant",
        "badge_id": badge_id,
        "user_id": ctx.author.id,
    }

    await ctx.send(
        f"バッジ付与モードに入りました（{badge_id}）\n"
        "次の1メッセージでユーザーIDを1行ずつ送ってください。\n"
        "キャンセルで終了できます。"
    )

@bot.command(name="バッジ削除")
async def remove_badge(ctx, badge_id: str):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if not await ensure_admin_channel(ctx):
        return

    if badge_id not in BADGE_DEFINITIONS:
        await ctx.send("そのバッジIDは存在しません")
        return

    badge_bulk_waiting[ctx.guild.id] = {
        "mode": "remove",
        "badge_id": badge_id,
        "user_id": ctx.author.id,
    }

    await ctx.send(
        f"バッジ削除モードに入りました（{badge_id}）\n"
        "次の1メッセージでユーザーIDを1行ずつ送ってください。\n"
        "キャンセルで終了できます。"
    )


@bot.command(name="バッジ強制付与")
async def force_grant_badge(ctx, badge_id: str):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if not await ensure_admin_channel(ctx):
        return

    if badge_id not in BADGE_DEFINITIONS:
        await ctx.send("そのバッジIDは存在しません")
        return

    badge_bulk_waiting[ctx.guild.id] = {
        "mode": "force_grant",
        "badge_id": badge_id,
        "user_id": ctx.author.id,
    }

    await ctx.send(
        f"バッジ強制付与モードに入りました（{badge_id}）\n"
        "次の1メッセージでユーザーIDを1行ずつ送ってください。\n"
        "所持していなければ付与し、表示バッジもこのバッジに変更します。\n"
        "キャンセルで終了できます。"
    )


@bot.command(name="所持バッジ一覧")
async def list_user_badges(ctx, user_id: int):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if not await ensure_admin_channel(ctx):
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
        if emoji:
            lines.append(f"- {emoji} {label} ({b})")
        else:
            lines.append(f"- {label} ({b})")

    await ctx.send("\n".join(lines))


@bot.command(name="バッジ所持者一覧")
async def list_badge_owners(ctx, badge_id: str):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if not await ensure_admin_channel(ctx):
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
        await ctx.send("このコマンドは管理者専用です。")
        return
    if not await ensure_admin_channel(ctx):
        return

    bulk_rate_change_waiting[ctx.guild.id] = ctx.author.id
    await ctx.send(
        "レート値変更モードに入りました。\n"
        "次の1メッセージで、1行に1人ずつ\n"
        "ユーザーID レート値\n"
        "の形式で送ってください。\n\n"
        "例:\n"
        "123456789012345678 2500\n"
        "987654321098765432 2637\n\n"
        "やめるときは キャンセル と送ってください。"
    )


@bot.command(name="全員レートリセット")
async def reset_all_rates(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("このコマンドは管理者専用です。")
        return
    if not await ensure_admin_channel(ctx):
        return

    members = await get_human_members(ctx.guild)

    for member in members:
        ratings[str(member.id)] = DEFAULT_RATING
        profile = get_player_profile(member.id)
        profile["initial_applied"] = False
        profile["can_apply_initial_bonus"] = True
        profile["coins"] = 0
        profile["tickets"] = []
        profile["active_effect"] = None
        profile["next_coin_at"] = None
        profile["win_streak"] = 0

    save_ratings(ratings)
    save_player_profiles(player_profiles)
    await post_ranking(ctx.guild)
    await ctx.send(f"サーバー内の全プレイヤーのレートを {DEFAULT_RATING} にリセットしました。")
    await post_player_register_message(ctx.guild)

    register_channel = get_player_register_channel(ctx.guild)
    if register_channel is not None:
        await register_channel.send(
            "【シーズン開始】\n"
            "武器登録と最高XP登録をしてください。\n"
            "XP補正を反映したい人は、プレイヤー登録ボタンからもう一度登録してくれ。"
        )


@bot.command(name="全員初期補正権付与")
async def grant_all_initial_bonus_permission(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if not await ensure_admin_channel(ctx):
        return

    members = [m for m in ctx.guild.members if not m.bot]
    if not members:
        await ctx.send("対象のプレイヤーがいません")
        return

    names = []
    for member in members:
        profile = get_player_profile(member.id)
        profile["can_apply_initial_bonus"] = True
        profile["initial_applied"] = False
        names.append(member.display_name)

    save_player_profiles(player_profiles)

    text = "全員に初期補正権を付与しました\n" + "\n".join(names)
    if len(text) <= 1900:
        await ctx.send(text)
    else:
        await ctx.send(f"全員に初期補正権を付与しました\n対象: {len(names)}人")


@bot.command(name="全員初期補正権剥奪")
async def revoke_all_initial_bonus_permission(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if not await ensure_admin_channel(ctx):
        return

    members = [m for m in ctx.guild.members if not m.bot]
    if not members:
        await ctx.send("対象のプレイヤーがいません")
        return

    names = []
    for member in members:
        profile = get_player_profile(member.id)
        profile["can_apply_initial_bonus"] = False
        names.append(member.display_name)

    save_player_profiles(player_profiles)

    text = "全員の初期補正権を剥奪しました\n" + "\n".join(names)
    if len(text) <= 1900:
        await ctx.send(text)
    else:
        await ctx.send(f"全員の初期補正権を剥奪しました\n対象: {len(names)}人")


@bot.command(name="初期補正権付与")
async def grant_initial_bonus_permission_command(ctx, user_id: int):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if not await ensure_admin_channel(ctx):
        return

    profile = get_player_profile(user_id)
    profile["can_apply_initial_bonus"] = True
    profile["initial_applied"] = False
    save_player_profiles(player_profiles)

    name = await get_member_display_name_by_id(ctx.guild, user_id)
    await ctx.send(f"{name} に初期補正権を付与しました")


@bot.command(name="初期補正権剥奪")
async def revoke_initial_bonus_permission_command(ctx, user_id: int):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if not await ensure_admin_channel(ctx):
        return

    profile = get_player_profile(user_id)
    profile["can_apply_initial_bonus"] = False
    save_player_profiles(player_profiles)

    name = await get_member_display_name_by_id(ctx.guild, user_id)
    await ctx.send(f"{name} の初期補正権を剥奪しました")


@bot.command(name="登録メッセージ更新")
async def update_register_message(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if not await ensure_admin_channel(ctx):
        return

    await post_player_register_message(ctx.guild)
    await ctx.send("プレイヤー登録メッセージを更新しました")


@bot.command(name="運営一括")
async def bulk_admin_mode(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if not await ensure_admin_channel(ctx):
        return

    bulk_admin_waiting[ctx.guild.id] = ctx.author.id

    await ctx.send(
        "運営一括モードに入りました。\n"
        "次の1メッセージで、1行に1人ずつ\n"
        "ユーザーID コマンド 内容\n"
        "の形式で送ってください。\n\n"
        "例:\n"
        "123456789012345678 武器 スシ\n"
        "123456789012345678 バッジ付与 yuta\n"
        "123456789012345678 バッジ強制付与 yuta\n"
        "123456789012345678 レート 2700\n"
        "123456789012345678 初期補正付与\n"
        "123456789012345678 コイン 3\n"
        "123456789012345678 チケット付与 rate_x1_2_10 win_bonus_1_15\n\n"
        "やめるときは キャンセル と送ってください。"
    )

@bot.command(name="ユーザーID一覧")
async def user_id_list(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if not await ensure_admin_channel(ctx):
        return

    try:
        members = [member async for member in ctx.guild.fetch_members(limit=None)]
    except Exception:
        members = ctx.guild.members

    human_members = [m for m in members if not m.bot]

    if not human_members:
        await ctx.send("プレイヤーがいません")
        return

    human_members.sort(key=lambda m: m.display_name.lower())

    lines = ["【ユーザーID一覧】"]
    for member in human_members:
        lines.append(f"{member.display_name} {member.id}")

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


@bot.command(name="運営一覧")
async def admin_dump(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if not await ensure_admin_channel(ctx):
        return

    try:
        members = [member async for member in ctx.guild.fetch_members(limit=None)]
    except Exception:
        members = ctx.guild.members

    human_members = [m for m in members if not m.bot]

    if not human_members:
        await ctx.send("プレイヤーがいません")
        return

    human_members.sort(key=lambda m: m.display_name.lower())

    lines = []

    for member in human_members:
        uid = str(member.id)
        profile = get_player_profile(member.id)

        weapon = profile.get("weapon")
        if weapon:
            lines.append(f"{uid} 武器 {weapon}")
        else:
            lines.append(f"{uid} 武器削除")

        owned_badges = profile.get("owned_badges", [])
        selected_badge = profile.get("selected_badge")

        for badge_id in owned_badges:
            lines.append(f"{uid} バッジ付与 {badge_id}")

        if selected_badge:
            lines.append(f"{uid} バッジ強制付与 {selected_badge}")

        rate = ratings.get(uid, DEFAULT_RATING)
        lines.append(f"{uid} レート {rate}")

        if profile.get("can_apply_initial_bonus", True):
            lines.append(f"{uid} 初期補正付与")
        else:
            lines.append(f"{uid} 初期補正剥奪")

        coins = profile.get("coins", 0)
        lines.append(f"{uid} コイン {coins}")

        ticket_ids = []

        for ticket in profile.get("tickets", []):
            ticket_id = ticket.get("ticket_id")
            if ticket_id:
                ticket_ids.append(ticket_id)

        active_effect = profile.get("active_effect")
        if active_effect and active_effect.get("ticket_id"):
            ticket_ids.append(active_effect.get("ticket_id"))

        if ticket_ids:
            lines.append(f"{uid} チケット付与 " + " ".join(ticket_ids))

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

    await disable_room_messages(room_state)
    await move_members_to_lobby(ctx.guild, room_key, room_state)

    reset_room_state(room_state)
    reset_room_tracking(room_state)

    await ctx.send(f"{room_key}部屋の部屋作成を中断しました")

# =========================
# 起動
# =========================
if not TOKEN:
    raise ValueError("DISCORD_TOKEN が設定されていません。")

bot.run(TOKEN)
