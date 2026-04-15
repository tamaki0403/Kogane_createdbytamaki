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

# =========================
# チャンネル設定
# =========================

PROGRESS_CHANNEL_ID = 1492082738679910512
RANKING_CHANNEL_ID = 1492896273358127235
PLAYER_REGISTER_CHANNEL_ID = 1493300698568462388
ADMIN_CHANNEL_ID = 1492883720082952302

# =========================
# VC ID
# =========================
VC_ALPHA_ID = 1492138431583752252
VC_BRAVO_ID = 1492138468346957884
VC_LOBBY_ID = 1492082738679910515

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
    (0, 0): 70, (0, 1): 70, (0, 2): 58, (0, 3): 45, (0, 4): 20,
    (1, 0): 70, (1, 1): 62, (1, 2): 53, (1, 3): 43, (1, 4): 20,
    (2, 0): 58, (2, 1): 53, (2, 2): 47, (2, 3): 39, (2, 4): 20,
    (3, 0): 45, (3, 1): 43, (3, 2): 39, (3, 3): 34, (3, 4): 20,
    (4, 0): 20, (4, 1): 20, (4, 2): 20, (4, 3): 20, (4, 4): 20,
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
game_state = "idle"

badge_bulk_waiting = {}
# {guild_id: {mode, badge_id, user_id}}
# idle
# recruiting
# pref1
# pref2
# confirm
# ready
# playing
# finished
# disconnect_vote

joined_players = []
current_match = None
prepared_match = None
last_rating_changes = None

recruit_message = None
selection_message = None
confirm_message = None
disconnect_vote_message = None

# 部屋開始から終了までの増減確認用
session_start_ratings = {}
session_participants = {}

# チーム希望
phase1_choices = {}
phase2_choices = {}

# 回線落ち投票
disconnect_vote = None

# レート一括変更モード
bulk_rate_change_waiting = {}
# {guild_id: user_id}

# =========================
# 共通ユーティリティ
# =========================
def reset_room_tracking():
    global session_start_ratings, session_participants
    session_start_ratings = {}
    session_participants = {}


def reset_room_state():
    global game_state
    global joined_players, current_match, prepared_match, last_rating_changes
    global recruit_message, selection_message, confirm_message, disconnect_vote_message
    global phase1_choices, phase2_choices, disconnect_vote

    game_state = "idle"
    joined_players = []
    current_match = None
    prepared_match = None
    last_rating_changes = None

    recruit_message = None
    selection_message = None
    confirm_message = None
    disconnect_vote_message = None

    phase1_choices = {}
    phase2_choices = {}
    disconnect_vote = None


def get_progress_channel(guild):
    return guild.get_channel(PROGRESS_CHANNEL_ID)


def get_ranking_channel(guild):
    return guild.get_channel(RANKING_CHANNEL_ID)


def get_player_register_channel(guild):
    return guild.get_channel(PLAYER_REGISTER_CHANNEL_ID)


def get_admin_channel(guild):
    return guild.get_channel(ADMIN_CHANNEL_ID)


async def send_progress_message(guild, content, view=None):
    channel = get_progress_channel(guild)
    if channel is None:
        return None
    return await channel.send(content, view=view)


def ensure_session_player(user):
    user_id = str(user.id)
    session_participants[user_id] = user
    if user_id not in session_start_ratings:
        session_start_ratings[user_id] = ratings.get(user_id, DEFAULT_RATING)


def get_joined_user_ids():
    return [str(u.id) for u in joined_players]


def is_joined(user):
    return user in joined_players


def get_avg_rating(team):
    if not team:
        return DEFAULT_RATING
    return sum(ratings.get(str(user.id), DEFAULT_RATING) for user in team) / len(team)


def get_phase1_count(choice_name):
    return sum(1 for uid in get_joined_user_ids() if phase1_choices.get(uid) == choice_name)


def get_alpha_fixed_count():
    return get_phase1_count("alpha")


def get_bravo_fixed_count():
    return get_phase1_count("bravo")


def get_match_k_factor():
    alpha = get_alpha_fixed_count()
    beta = get_bravo_fixed_count()
    return K_TABLE.get((alpha, beta), K_FACTOR)


def get_random_users():
    return [u for u in joined_players if phase1_choices.get(str(u.id)) == "random"]


def should_show_phase2():
    random_users = get_random_users()
    alpha_slots = TEAM_SIZE - get_phase1_count("alpha")
    bravo_slots = TEAM_SIZE - get_phase1_count("bravo")
    return len(random_users) >= 2 and alpha_slots >= 1 and bravo_slots >= 1


def all_joined_selected_phase1():
    return len(joined_players) == ROOM_CAPACITY and all(str(u.id) in phase1_choices for u in joined_players)


def all_random_selected_phase2():
    random_users = get_random_users()
    return all(str(u.id) in phase2_choices for u in random_users)


def get_effective_split_targets():
    random_users = get_random_users()
    targets = [u for u in random_users if phase2_choices.get(str(u.id)) == "split"]
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


def create_recruit_text():
    lines = [
        "【参加者募集】",
        f"{len(joined_players)}/{ROOM_CAPACITY}",
        "",
        format_member_lines(
            joined_players,
            mention=True,
            include_weapon=True,
            include_badge=False,
            include_rating=False,
        ),
        "",
        "8人揃うとチーム希望選択に進みます。",
    ]
    return "\n".join(lines)


def create_phase1_text():
    alpha_users = [u for u in joined_players if phase1_choices.get(str(u.id)) == "alpha"]
    bravo_users = [u for u in joined_players if phase1_choices.get(str(u.id)) == "bravo"]
    random_users = [u for u in joined_players if phase1_choices.get(str(u.id)) == "random"]

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


def create_phase2_text():
    random_users = get_random_users()
    split_users = [u for u in random_users if phase2_choices.get(str(u.id)) == "split"]
    normal_random_users = [u for u in random_users if phase2_choices.get(str(u.id)) == "random"]

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


def create_confirm_text():
    alpha_users = [u for u in joined_players if phase1_choices.get(str(u.id)) == "alpha"]
    bravo_users = [u for u in joined_players if phase1_choices.get(str(u.id)) == "bravo"]
    random_users = [u for u in joined_players if phase1_choices.get(str(u.id)) == "random"]
    split_targets = get_effective_split_targets()

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
        "次の試合に進みますか？\n\n"
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


def make_teams_from_choices():
    alpha_fixed = [u for u in joined_players if phase1_choices.get(str(u.id)) == "alpha"]
    bravo_fixed = [u for u in joined_players if phase1_choices.get(str(u.id)) == "bravo"]
    random_users = [u for u in joined_players if phase1_choices.get(str(u.id)) == "random"]

    team_alpha = alpha_fixed[:]
    team_bravo = bravo_fixed[:]

    split_targets = get_effective_split_targets()
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


def create_room_summary_text():
    if not session_participants:
        return None

    rows = []
    for user_id, member in session_participants.items():
        start_rate = session_start_ratings.get(user_id, DEFAULT_RATING)
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


class PlayerRegisterView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="プレイヤー登録",
        style=discord.ButtonStyle.primary,
        custom_id="player_register_button"
    )
    async def register_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PlayerRegisterModal())

    @discord.ui.button(
        label="バッジ設定",
        style=discord.ButtonStyle.secondary,
        custom_id="badge_select_button"
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
    @discord.ui.button(label="参加", style=discord.ButtonStyle.primary)
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        global game_state

        user = interaction.user

        if game_state != "recruiting":
            await interaction.response.send_message("今は募集していません", ephemeral=True)
            return

        if is_joined(user):
            await interaction.response.send_message("既に参加しています", ephemeral=True)
            return

        if len(joined_players) >= ROOM_CAPACITY:
            await interaction.response.send_message("満員です", ephemeral=True)
            return

        joined_players.append(user)
        ensure_session_player(user)

        await interaction.response.edit_message(content=create_recruit_text(), view=self)

        if len(joined_players) == ROOM_CAPACITY:
            host_id = str(interaction.user.id)
            ratings[host_id] = ratings.get(host_id, DEFAULT_RATING) + 5
            save_ratings(ratings)

            self.disable_all_buttons()
            await interaction.message.edit(view=self)
            await begin_phase1(interaction.guild)

    @discord.ui.button(label="抜ける", style=discord.ButtonStyle.gray)
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user

        if game_state != "recruiting":
            await interaction.response.send_message("今は抜けられません", ephemeral=True)
            return

        if user not in joined_players:
            await interaction.response.send_message("まだ参加していません", ephemeral=True)
            return

        joined_players.remove(user)
        await interaction.response.edit_message(content=create_recruit_text(), view=self)


class Phase1ChoiceView(BaseControlView):
    async def handle_choice(self, interaction: discord.Interaction, choice_name: str):
        global game_state

        user = interaction.user
        uid = str(user.id)

        if game_state != "pref1":
            await interaction.response.send_message("今は第一選択ではありません", ephemeral=True)
            return

        if user not in joined_players:
            await interaction.response.send_message("この部屋の参加者ではありません", ephemeral=True)
            return

        current = phase1_choices.get(uid)

        if choice_name == "alpha":
            if current != "alpha" and get_phase1_count("alpha") >= TEAM_SIZE:
                await interaction.response.send_message("アルファは満員です", ephemeral=True)
                return

        if choice_name == "bravo":
            if current != "bravo" and get_phase1_count("bravo") >= TEAM_SIZE:
                await interaction.response.send_message("ブラボーは満員です", ephemeral=True)
                return

        phase1_choices[uid] = choice_name
        await interaction.response.edit_message(content=create_phase1_text(), view=self)

        if all_joined_selected_phase1():
            self.disable_all_buttons()
            await interaction.message.edit(view=self)
            if should_show_phase2():
                await begin_phase2(interaction.guild)
            else:
                await begin_confirm(interaction.guild)

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
    async def handle_choice(self, interaction: discord.Interaction, choice_name: str):
        global game_state

        user = interaction.user
        uid = str(user.id)
        random_users = get_random_users()

        if game_state != "pref2":
            await interaction.response.send_message("今は第二選択ではありません", ephemeral=True)
            return

        if user not in random_users:
            await interaction.response.send_message("第二選択の対象者ではありません", ephemeral=True)
            return

        current = phase2_choices.get(uid)

        if choice_name == "split":
            split_count = sum(1 for u in random_users if phase2_choices.get(str(u.id)) == "split")
            if current != "split" and split_count >= 2:
                await interaction.response.send_message("「分ける」は2人までです", ephemeral=True)
                return

        phase2_choices[uid] = choice_name
        await interaction.response.edit_message(content=create_phase2_text(), view=self)

        if all_random_selected_phase2():
            self.disable_all_buttons()
            await interaction.message.edit(view=self)
            await begin_confirm(interaction.guild)

    @discord.ui.button(label="分ける", style=discord.ButtonStyle.primary)
    async def split_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_choice(interaction, "split")

    @discord.ui.button(label="ランダム", style=discord.ButtonStyle.secondary)
    async def random_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_choice(interaction, "random")


class ConfirmView(BaseControlView):
    @discord.ui.button(label="決定", style=discord.ButtonStyle.success)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        global game_state, prepared_match

        user = interaction.user
        if user not in joined_players:
            await interaction.response.send_message("この部屋の参加者ではありません", ephemeral=True)
            return

        if game_state != "confirm":
            await interaction.response.send_message("今は確認段階ではありません", ephemeral=True)
            return

        try:
            prepared_match = make_teams_from_choices()
        except Exception as e:
            await interaction.response.send_message(f"チーム分けに失敗しました: {e}", ephemeral=True)
            return

        game_state = "ready"
        self.disable_all_buttons()
        await interaction.response.edit_message(content=create_confirm_text(), view=self)
        await send_progress_message(interaction.guild, "試合開始するなら !1 を送ってください")

    @discord.ui.button(label="やり直し", style=discord.ButtonStyle.danger)
    async def redo_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        global game_state, phase1_choices, phase2_choices

        user = interaction.user
        if user not in joined_players:
            await interaction.response.send_message("この部屋の参加者ではありません", ephemeral=True)
            return

        if game_state != "confirm":
            await interaction.response.send_message("今は確認段階ではありません", ephemeral=True)
            return

        phase1_choices = {}
        phase2_choices = {}
        game_state = "pref1"
        self.disable_all_buttons()
        await interaction.response.edit_message(content=create_confirm_text(), view=self)
        await begin_phase1(interaction.guild)


class DisconnectVoteView(BaseControlView):
    async def record_self_vote(self, interaction: discord.Interaction, vote_value: str):
        global disconnect_vote

        if game_state != "disconnect_vote" or disconnect_vote is None:
            await interaction.response.send_message("今は投票中ではありません", ephemeral=True)
            return

        user = interaction.user
        uid = str(user.id)
        target_id = disconnect_vote["target_id"]

        if uid != target_id:
            await interaction.response.send_message("このボタンは対象者本人のみ押せます", ephemeral=True)
            return

        disconnect_vote["self_vote"] = vote_value
        await interaction.response.send_message("投票を受け付けました", ephemeral=True)

        if vote_value == "confess":
            self.disable_all_buttons()
            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass
            target_member = session_participants.get(target_id)
            if target_member:
                await finalize_disconnect_vote(interaction.guild, target_member, forced_by_confession=True)

    async def record_jury_vote(self, interaction: discord.Interaction, vote_value: str):
        global disconnect_vote

        if game_state != "disconnect_vote" or disconnect_vote is None:
            await interaction.response.send_message("今は投票中ではありません", ephemeral=True)
            return

        user = interaction.user
        uid = str(user.id)
        target_id = disconnect_vote["target_id"]

        if uid == target_id:
            await interaction.response.send_message("対象者本人は有罪/無罪を押せません", ephemeral=True)
            return

        if current_match is None:
            await interaction.response.send_message("試合情報がありません", ephemeral=True)
            return

        if user not in (current_match[0] + current_match[1]):
            await interaction.response.send_message("今回の試合参加者ではありません", ephemeral=True)
            return

        disconnect_vote["jury_votes"][uid] = vote_value
        await interaction.response.send_message("投票を受け付けました", ephemeral=True)

        guilty_count = sum(1 for v in disconnect_vote["jury_votes"].values() if v == "guilty")
        voters = [u for u in (current_match[0] + current_match[1]) if str(u.id) != target_id]

        if guilty_count >= DISCONNECT_GUILTY_THRESHOLD:
            self.disable_all_buttons()
            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass
            target_member = session_participants.get(target_id)
            if target_member:
                await finalize_disconnect_vote(interaction.guild, target_member, forced_by_confession=False)
            return

        if len(disconnect_vote["jury_votes"]) == len(voters):
            self.disable_all_buttons()
            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass
            await resolve_disconnect_not_established(interaction.guild)

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
# VC移動
# =========================
async def move_members_to_vc(guild, team_alpha, team_bravo):
    vc_alpha = guild.get_channel(VC_ALPHA_ID)
    vc_bravo = guild.get_channel(VC_BRAVO_ID)

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


async def move_members_to_lobby(guild):
    lobby_vc = guild.get_channel(VC_LOBBY_ID)
    if lobby_vc is None:
        return

    moved_ids = set()
    for member in session_participants.values():
        if member.id in moved_ids:
            continue
        if member.voice:
            try:
                await member.move_to(lobby_vc)
                moved_ids.add(member.id)
            except Exception:
                pass


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
        return ["【レートランキング】", "ランキング対象のメンバーがいません"]

    lines = ["【レートランキング】"]
    for i, (rate, _, display_text) in enumerate(ranking_data, start=1):
        lines.append(f"#{i} {display_text} - {rate}")
    return lines


async def delete_old_ranking_messages(guild):
    ranking_channel = get_ranking_channel(guild)
    if ranking_channel is None:
        return

    async for msg in ranking_channel.history(limit=100):
        if msg.author == bot.user and msg.content.startswith("【レートランキング】"):
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
async def begin_recruit(guild):
    global game_state, recruit_message

    game_state = "recruiting"
    view = RecruitView()
    recruit_message = await send_progress_message(guild, create_recruit_text(), view=view)


async def begin_phase1(guild):
    global game_state, selection_message

    game_state = "pref1"
    view = Phase1ChoiceView()
    selection_message = await send_progress_message(guild, create_phase1_text(), view=view)


async def begin_phase2(guild):
    global game_state, selection_message

    game_state = "pref2"
    random_users = get_random_users()
    for user in random_users:
        phase2_choices.pop(str(user.id), None)

    view = Phase2ChoiceView()
    selection_message = await send_progress_message(guild, create_phase2_text(), view=view)


async def begin_confirm(guild):
    global game_state, confirm_message

    game_state = "confirm"
    view = ConfirmView()
    confirm_message = await send_progress_message(guild, create_confirm_text(), view=view)


async def start_game(ctx):
    global game_state, current_match, prepared_match

    if not prepared_match:
        await ctx.send("試合情報がないよ")
        return

    current_match = prepared_match
    prepared_match = None
    game_state = "playing"

    team_alpha, team_bravo = current_match
    mark_match_played_for_members(team_alpha + team_bravo)
    await move_members_to_vc(ctx.guild, team_alpha, team_bravo)
    await ctx.send(create_result_prompt(team_alpha, team_bravo))


async def next_game(ctx):
    global game_state, current_match, prepared_match

    if not prepared_match:
        try:
            prepared_match = make_teams_from_choices()
        except Exception as e:
            await ctx.send(f"次の試合情報を作れませんでした: {e}")
            return

    current_match = prepared_match
    prepared_match = None
    game_state = "playing"

    team_alpha, team_bravo = current_match
    mark_match_played_for_members(team_alpha + team_bravo)
    await move_members_to_vc(ctx.guild, team_alpha, team_bravo)
    await ctx.send(create_result_prompt(team_alpha, team_bravo))

def build_rating_update_lines(next_team_alpha, next_team_bravo, title="【レート更新】", bonus_text=None):
    lines = [title]

    if bonus_text:
        lines.append(bonus_text)

    lines.extend([
        "",
        "※ 以下は次回のチーム分けです",
        "",
        "【アルファ】"
    ])

    for user in next_team_alpha:
        old = last_rating_changes.get(str(user.id), ratings.get(str(user.id), DEFAULT_RATING))
        new = ratings.get(str(user.id), DEFAULT_RATING)

        lines.append(
            build_player_display(
                user,
                mention=False,
                include_weapon=False,
                include_badge=True,
                include_rating=False,
                include_rate_change=True,
                old_rating=old,
                new_rating=new,
            )
        )

    lines.extend([
        "",
        "【ブラボー】"
    ])

    for user in next_team_bravo:
        old = last_rating_changes.get(str(user.id), ratings.get(str(user.id), DEFAULT_RATING))
        new = ratings.get(str(user.id), DEFAULT_RATING)

        lines.append(
            build_player_display(
                user,
                mention=False,
                include_weapon=False,
                include_badge=True,
                include_rating=False,
                include_rate_change=True,
                old_rating=old,
                new_rating=new,
            )
        )

    return lines

async def process_result(ctx, winner_num: int):
    global current_match, prepared_match, ratings, game_state, last_rating_changes

    if not current_match:
        await ctx.send("試合がないよ")
        return

    team_alpha, team_bravo = current_match
    avg_alpha = get_avg_rating(team_alpha)
    avg_bravo = get_avg_rating(team_bravo)

    s_alpha, s_bravo = (1, 0) if winner_num == 1 else (0, 1)

    match_k = get_match_k_factor()

    last_rating_changes = {}
    for user in team_alpha + team_bravo:
        last_rating_changes[str(user.id)] = ratings.get(str(user.id), DEFAULT_RATING)

    for user in team_alpha:
        old = ratings.get(str(user.id), DEFAULT_RATING)
        new = elo_update(old, avg_bravo, s_alpha, K=match_k) + PARTICIPATION_BONUS
        ratings[str(user.id)] = new

    for user in team_bravo:
        old = ratings.get(str(user.id), DEFAULT_RATING)
        new = elo_update(old, avg_alpha, s_bravo, K=match_k) + PARTICIPATION_BONUS
        ratings[str(user.id)] = new

    save_ratings(ratings)

    prepared_match = make_teams_from_choices()
    next_team_alpha, next_team_bravo = prepared_match

    lines = build_rating_update_lines(
        next_team_alpha,
        next_team_bravo,
        title="【レート更新】",
        bonus_text=f"全員に +{PARTICIPATION_BONUS} が追加されました（K={match_k}）",
    )

    game_state = "finished"

    await ctx.send("\n".join(lines))
    await ctx.send(create_finished_prompt())


async def start_disconnect_vote(ctx, member):
    global game_state, disconnect_vote, disconnect_vote_message

    if not current_match:
        await ctx.send("試合情報がないよ")
        return

    all_players = current_match[0] + current_match[1]
    if member not in all_players:
        await ctx.send("そのユーザーは今回の試合に参加していません")
        return

    disconnect_vote = {
        "target_id": str(member.id),
        "self_vote": None,
        "jury_votes": {},
    }
    game_state = "disconnect_vote"

    view = DisconnectVoteView()
    disconnect_vote_message = await ctx.send(create_disconnect_vote_text(member), view=view)


async def apply_disconnect_rating_change(ctx, member):
    global ratings, game_state, last_rating_changes, prepared_match

    team_alpha, team_bravo = current_match
    all_players = team_alpha + team_bravo

    last_rating_changes = {}
    for user in all_players:
        last_rating_changes[str(user.id)] = ratings.get(str(user.id), DEFAULT_RATING)

    for user in all_players:
        uid = str(user.id)
        if user.id == member.id:
            ratings[uid] = ratings.get(uid, DEFAULT_RATING) - DISCONNECT_PENALTY
        else:
            ratings[uid] = ratings.get(uid, DEFAULT_RATING) + DISCONNECT_REWARD

    save_ratings(ratings)

    prepared_match = make_teams_from_choices()
    next_team_alpha, next_team_bravo = prepared_match

    lines = build_rating_update_lines(
        next_team_alpha,
        next_team_bravo,
        title="【レート更新】",
        bonus_text=f"回線落ち: -{DISCONNECT_PENALTY} / その他: +{DISCONNECT_REWARD}",
    )

    game_state = "finished"

    await ctx.send("\n".join(lines))
    await ctx.send(create_finished_prompt())

async def finalize_disconnect_vote(guild, member, forced_by_confession: bool):
    global disconnect_vote

    progress_channel = get_progress_channel(guild)
    if progress_channel is None:
        return

    if forced_by_confession:
        await progress_channel.send(create_disconnect_confess_text(member))
    else:
        await progress_channel.send(create_disconnect_guilty_text())

    fake_ctx = type("Ctx", (), {"guild": guild, "send": progress_channel.send})()
    await apply_disconnect_rating_change(fake_ctx, member)
    disconnect_vote = None


async def resolve_disconnect_not_established(guild):
    global game_state, disconnect_vote

    progress_channel = get_progress_channel(guild)
    if progress_channel is None:
        return

    game_state = "playing"
    disconnect_vote = None

    await progress_channel.send(create_disconnect_not_established_text())
    if current_match:
        team_alpha, team_bravo = current_match
        await progress_channel.send(create_result_prompt(team_alpha, team_bravo))


async def undo_result(ctx):
    global ratings, last_rating_changes, game_state, prepared_match

    if not last_rating_changes:
        await ctx.send("戻せる試合結果がありません")
        return

    for user_id, old_rate in last_rating_changes.items():
        ratings[user_id] = old_rate

    save_ratings(ratings)
    last_rating_changes = None
    prepared_match = None
    game_state = "playing"

    await ctx.send("試合結果を訂正しました")
    if current_match:
        team_alpha, team_bravo = current_match
        await ctx.send(create_result_prompt(team_alpha, team_bravo))


async def end_room(ctx):
    summary_text = create_room_summary_text()

    await move_members_to_lobby(ctx.guild)
    await post_ranking(ctx.guild)

    reset_room_state()
    reset_room_tracking()

    if summary_text:
        await ctx.send(summary_text)
    await ctx.send("部屋作成をやめました。次の募集をするときは !部屋作成 を使ってね")

# =========================
# 状態別コマンド処理
# =========================
async def handle_ready(ctx, cmd_num: int):
    if cmd_num == 1:
        await start_game(ctx)
    else:
        await ctx.send("今は !1 で試合開始")


async def handle_playing(ctx, cmd_num: int):
    if cmd_num == 1:
        await process_result(ctx, 1)
        return

    if cmd_num == 2:
        await process_result(ctx, 2)
        return

    if cmd_num == 3:
        if ctx.message.mentions:
            await start_disconnect_vote(ctx, ctx.message.mentions[0])
        else:
            await ctx.send("回線落ちは !3 @ユーザー で送ってくれ")
        return

    await ctx.send("試合中は !1 !2 !3 を使ってくれ")


async def handle_finished(ctx, cmd_num: int):
    if cmd_num == 1:
        await next_game(ctx)
        return

    if cmd_num == 2:
        await end_room(ctx)
        return

    if cmd_num == 3:
        await undo_result(ctx)
        return

    await ctx.send("今は !1 !2 !3 を使ってくれ")


async def handle_disconnect_vote_state(ctx, cmd_num: int):
    await ctx.send("今は投票中です。ボタンで投票してください。")


STATE_HANDLERS = {
    "ready": handle_ready,
    "playing": handle_playing,
    "finished": handle_finished,
    "disconnect_vote": handle_disconnect_vote_state,
}


async def dispatch_number_command(ctx, cmd_num: int):
    handler = STATE_HANDLERS.get(game_state)
    if handler is None:
        await ctx.send(f"今は !{cmd_num} を受け付ける状態じゃない")
        return
    await handler(ctx, cmd_num)


# =========================
# チャンネル制限
# =========================

async def ensure_progress_channel(ctx):
    if ctx.channel.id != PROGRESS_CHANNEL_ID:
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

    await bot.process_commands(message)


@bot.command()
async def 部屋作成(ctx):
    if not await ensure_progress_channel(ctx):
        return

    if game_state != "idle":
        await ctx.send("すでに部屋進行中です")
        return

    reset_room_state()
    reset_room_tracking()
    await begin_recruit(ctx.guild)


@bot.command(name="1")
async def command_one(ctx):
    if not await ensure_progress_channel(ctx):
        return
    await dispatch_number_command(ctx, 1)


@bot.command(name="2")
async def command_two(ctx):
    if not await ensure_progress_channel(ctx):
        return
    await dispatch_number_command(ctx, 2)


@bot.command(name="3")
async def command_three(ctx):
    if not await ensure_progress_channel(ctx):
        return
    await dispatch_number_command(ctx, 3)


@bot.command(name="ランキング")
async def ランキング(ctx):
    await post_ranking(ctx.guild)
    await ctx.send("ランキングを更新しました。")


@bot.command(name="秘匿ランキング")
async def secret_ranking(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
        return
    if not await ensure_admin_channel(ctx):
        return

    await post_secret_ranking(ctx.guild)
    await ctx.send("秘匿ランキングを送信しました。")


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

    members = await get_human_members(ctx.guild)

    for member in members:
        ratings[str(member.id)] = DEFAULT_RATING
        profile = get_player_profile(member.id)
        profile["initial_applied"] = False
        profile["can_apply_initial_bonus"] = True

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

    await post_player_register_message(ctx.guild)
    await ctx.send("プレイヤー登録メッセージを更新しました")

@bot.command(name="ユーザーID一覧")
async def user_id_list(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("管理者専用です")
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

# =========================
# 起動
# =========================
if not TOKEN:
    raise ValueError("DISCORD_TOKEN が設定されていません。")

bot.run(TOKEN)
