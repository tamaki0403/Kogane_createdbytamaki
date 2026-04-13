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
TOKEN = os.getenv("DISCORD_TOKEN")

# =========================
# 管理者設定
# =========================
OWNER_ID = 1225788050894753865

# =========================
# チャンネル設定
# =========================
PROGRESS_CHANNEL_ID = 1492082738679910512
RANKING_CHANNEL_ID = 1492896273358127235

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
K_FACTOR = 140
PARTICIPATION_BONUS = 5

DISCONNECT_PENALTY = 50
DISCONNECT_REWARD = 8
DISCONNECT_GUILTY_THRESHOLD = 4

ROOM_CAPACITY = 8
TEAM_SIZE = 4

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
current_match = None        # (team_alpha, team_bravo)
prepared_match = None       # (team_alpha, team_bravo)
last_rating_changes = None

recruit_message = None
selection_message = None
confirm_message = None
disconnect_vote_message = None

# 部屋開始から終了までの増減確認用
session_start_ratings = {}
session_participants = {}

# チーム希望
phase1_choices = {}         # user_id(str) -> "alpha" / "bravo" / "random"
phase2_choices = {}         # user_id(str) -> "split" / "random"

# 回線落ち投票
disconnect_vote = None
# {
#   "target_id": str,
#   "self_vote": None / "confess" / "deny",
#   "jury_votes": {user_id(str): "guilty" / "innocent"},
# }

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


def display_name(user):
    return user.display_name


def get_progress_channel(guild):
    return guild.get_channel(PROGRESS_CHANNEL_ID)


def get_ranking_channel(guild):
    return guild.get_channel(RANKING_CHANNEL_ID)


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


def format_member_lines(members):
    return "\n".join(display_name(m) for m in members) if members else "なし"


def get_avg_rating(team):
    if not team:
        return DEFAULT_RATING
    return sum(ratings.get(str(user.id), DEFAULT_RATING) for user in team) / len(team)


def get_phase1_count(choice_name):
    return sum(1 for uid in get_joined_user_ids() if phase1_choices.get(uid) == choice_name)


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


def create_recruit_text():
    lines = [
        "【参加者募集】",
        f"{len(joined_players)}/{ROOM_CAPACITY}",
        "",
        format_member_lines(joined_players),
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
        format_member_lines(alpha_users),
        "",
        f"【ブラボー（{len(bravo_users)}/{TEAM_SIZE}）】",
        format_member_lines(bravo_users),
        "",
        f"【ランダム（{len(random_users)}）】",
        format_member_lines(random_users),
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
        format_member_lines(split_users),
        "",
        "【ランダム】",
        format_member_lines(normal_random_users),
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
        format_member_lines(alpha_users),
        "",
        "【ブラボー固定】",
        format_member_lines(bravo_users),
        "",
        "【ランダム】",
        format_member_lines(random_users),
        "",
        "【分け対象（有効時のみ）】",
        format_member_lines(split_targets),
    ]
    return "\n".join(lines)


def create_result_prompt(team_alpha, team_bravo):
    def fmt(team):
        lines = []
        for user in team:
            rate = ratings.get(str(user.id), DEFAULT_RATING)
            lines.append(f"{display_name(user)} {rate}")
        return "\n".join(lines)

    return (
        f"【アルファ】\n{fmt(team_alpha)}\n\n"
        f"【ブラボー】\n{fmt(team_bravo)}\n\n"
        "!1 アルファ勝ち\n"
        "!2 ブラボー勝ち\n"
        "!3 @ユーザー 回線落ち"
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
    return (
        "【領域展開「誅伏賜死」】\n\n"
        "<:Judgeman:1493076764816314508>\n"
        f"{display_name(target)} は {now_str}\n"
        "試合途中にラグや回線落ちをした疑いがある。\n\n"
        "対象者本人は「自白」または「否認」\n"
        "試合参加者は「有罪」または「無罪」を選択してください。\n\n"
        "※ 投票は匿名です\n"
        f"※ 有罪が{DISCONNECT_GUILTY_THRESHOLD}票以上で回線落ち処理を行います\n"
        "※ 有罪が3票以下の場合は通常の試合結果入力に戻ります"
    )


def create_disconnect_confess_text(target):
    return (
        "【回線落ち確定】\n\n"
        "<:Confession:1493076810521378866>\n"
        f"{display_name(target)}「ああ俺の回線が悪かった、これは嘘でも否定でもない」"
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
        rows.append((diff, end_rate, member.display_name, start_rate))

    rows.sort(key=lambda x: (-x[0], -x[1], x[2].lower()))

    lines = ["【今回の部屋のレート増減】"]
    for diff, end_rate, name, start_rate in rows:
        sign = "+" if diff >= 0 else ""
        lines.append(f"{name}: {start_rate} → {end_rate} ({sign}{diff})")
    return "\n".join(lines)


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
        ranking_data.append((rate, member.display_name))

    ranking_data.sort(key=lambda x: (-x[0], x[1].lower()))

    if not ranking_data:
        return ["【レートランキング】", "ランキング対象のメンバーがいません"]

    lines = ["【レートランキング】"]
    for i, (rate, name) in enumerate(ranking_data, start=1):
        lines.append(f"#{i} {name} - {rate}")
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
        old = last_rating_changes[str(user.id)]
        new = ratings[str(user.id)]
        diff = new - old
        sign = "+" if diff >= 0 else ""
        lines.append(f"{display_name(user)}: {old} → {new} ({sign}{diff})")

    lines.extend(["", "【ブラボー】"])
    for user in next_team_bravo:
        old = last_rating_changes[str(user.id)]
        new = ratings[str(user.id)]
        diff = new - old
        sign = "+" if diff >= 0 else ""
        lines.append(f"{display_name(user)}: {old} → {new} ({sign}{diff})")

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

    last_rating_changes = {}
    for user in team_alpha + team_bravo:
        last_rating_changes[str(user.id)] = ratings.get(str(user.id), DEFAULT_RATING)

    for user in team_alpha:
        old = ratings.get(str(user.id), DEFAULT_RATING)
        new = elo_update(old, avg_bravo, s_alpha) + PARTICIPATION_BONUS
        ratings[str(user.id)] = new

    for user in team_bravo:
        old = ratings.get(str(user.id), DEFAULT_RATING)
        new = elo_update(old, avg_alpha, s_bravo) + PARTICIPATION_BONUS
        ratings[str(user.id)] = new

    save_ratings(ratings)

    prepared_match = make_teams_from_choices()
    next_team_alpha, next_team_bravo = prepared_match

    lines = build_rating_update_lines(
        next_team_alpha,
        next_team_bravo,
        title="【レート更新】",
        bonus_text=f"全員に +{PARTICIPATION_BONUS} が追加されました",
    )

    game_state = "finished"

    await ctx.send("\n".join(lines))
    await post_ranking(ctx.guild)
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
    await post_ranking(ctx.guild)
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


# =========================
# コマンド
# =========================
@bot.event
async def on_ready():
    print(f"ログインしたよ: {bot.user}")


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


@bot.command()
async def ランキング(ctx):
    await post_ranking(ctx.guild)
    await ctx.send("ランキングを更新しました。")


@bot.command()
async def setrate(ctx, user_id: int, new_rating: int):
    if ctx.author.id != OWNER_ID:
        await ctx.send("このコマンドは管理者専用です。")
        return

    if new_rating < 0:
        await ctx.send("レートは0以上を指定してくれ")
        return

    user_id_str = str(user_id)
    old_rating = ratings.get(user_id_str, DEFAULT_RATING)
    ratings[user_id_str] = new_rating
    save_ratings(ratings)

    member = ctx.guild.get_member(user_id)
    if member is None:
        try:
            member = await ctx.guild.fetch_member(user_id)
        except Exception:
            member = None

    name = member.display_name if member else f"ユーザーID:{user_id}"

    await ctx.send(
        f"{name} のレートを変更しました\n"
        f"{old_rating} → {new_rating}"
    )
    await post_ranking(ctx.guild)


@bot.command()
async def resetallrates(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("このコマンドは管理者専用です。")
        return

    try:
        members = [member async for member in ctx.guild.fetch_members(limit=None)]
    except Exception:
        members = ctx.guild.members

    human_members = [m for m in members if not m.bot]

    for member in human_members:
        ratings[str(member.id)] = DEFAULT_RATING

    save_ratings(ratings)
    await post_ranking(ctx.guild)
    await ctx.send(f"サーバー内の全プレイヤーのレートを {DEFAULT_RATING} にリセットしました。")


@bot.command()
async def result(ctx, num: int):
    if not await ensure_progress_channel(ctx):
        return

    if game_state != "playing":
        await ctx.send("今は result を使える状態ではありません")
        return

    if num == 1:
        await process_result(ctx, 1)
    elif num == 2:
        await process_result(ctx, 2)
    else:
        await ctx.send("今は !result 1 か !result 2 だけ使えます")


if __name__ == "__main__":
    if not TOKEN:
        raise ValueError("DISCORD_TOKEN が設定されていません")
    reset_room_state()
    reset_room_tracking()
    bot.run(TOKEN)
