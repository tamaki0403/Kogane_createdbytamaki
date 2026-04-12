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

# 初期レート
DEFAULT_RATING = 2500

# =========================
# レート関連
# =========================
def load_ratings():
    try:
        with open(RATINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_ratings(ratings):
    with open(RATINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(ratings, f, indent=2, ensure_ascii=False)


def elo_update(rA, rB, scoreA, K=32):
    expected_a = 1 / (1 + 10 ** ((rB - rA) / 400))
    return int(rA + K * (scoreA - expected_a))


ratings = load_ratings()

# =========================
# Discord設定
# =========================
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix="!", intents=intents)

# =========================
# VC ID
# =========================
VC_ALPHA_ID = 1492138431583752252
VC_BRAVO_ID = 1492138468346957884

# =========================
# モード設定
# =========================
MODE_CONFIGS = {
    "a": {
        "name": "後衛分け",
        "display": "後衛2 / その他6",
        "roles": [
            {"key": "back", "label": "後衛", "cap": 2},
            {"key": "other", "label": "その他", "cap": 6},
        ],
    },
    "b": {
        "name": "後衛塗り分け",
        "display": "後衛2 / 塗り2 / その他4",
        "roles": [
            {"key": "back", "label": "後衛", "cap": 2},
            {"key": "paint", "label": "塗り", "cap": 2},
            {"key": "other", "label": "その他", "cap": 4},
        ],
    },
    "c": {
        "name": "ナワバリ",
        "display": "エナスタ2 / ラクト2 / その他4",
        "roles": [
            {"key": "energy", "label": "エナスタ", "cap": 2},
            {"key": "lact", "label": "ラクト", "cap": 2},
            {"key": "other", "label": "その他", "cap": 4},
        ],
    },
    "d": {
        "name": "ランダム",
        "display": "参加8",
        "roles": [
            {"key": "other", "label": "参加", "cap": 8},
        ],
    },
}

# =========================
# 状態管理
# =========================
players = {}
current_mode = None
game_state = "idle"
# idle         : 何もしていない
# mode_select  : !部屋作成後のモード選択中
# waiting      : 募集中
# ready        : 初回のチーム決定後、開始待ち
# playing      : 試合中
# finished     : レート更新後、次試合/終了/訂正待ち

last_match = None
last_rating_changes = None
recruit_message = None

# =========================
# 共通ユーティリティ
# =========================
def reset_players():
    global players
    players = {
        "back": [],
        "paint": [],
        "energy": [],
        "lact": [],
        "other": [],
    }


def get_mode_config():
    if current_mode is None:
        return None
    return MODE_CONFIGS[current_mode]


def get_role_config(role_key):
    config = get_mode_config()
    if not config:
        return None
    for role in config["roles"]:
        if role["key"] == role_key:
            return role
    return None


def get_role_label(role_key):
    role = get_role_config(role_key)
    return role["label"] if role else role_key


def get_all_joined_users():
    users = []
    for role_users in players.values():
        users.extend(role_users)
    return users


def is_user_joined(user):
    return user in get_all_joined_users()


def create_mode_select_text():
    return (
        "俺はコガネ！泳者と死滅回遊を繋ぐ窓口さ！\n"
        "試合するモードを選んでくれ！\n\n"
        "!1 後衛分け\n"
        "!2 後衛塗り分け\n"
        "!3 ナワバリ\n"
        "!4 ランダム\n"
        "!5 やっぱりやめる"
    )


def create_recruit_text():
    config = get_mode_config()
    if not config:
        return "モードが未選択です"

    lines = [f"【{config['name']}】 {config['display']}", ""]
    for role in config["roles"]:
        role_users = players[role["key"]]
        mentions = "\n".join([u.mention for u in role_users]) or "なし"
        lines.append(f"【{role['label']}（{len(role_users)}/{role['cap']}）】")
        lines.append(mentions)
        lines.append("")
    return "\n".join(lines).strip()


def create_team_text(team1, team2, require_start=True):
    def fmt(team):
        return "\n".join([user.mention for user in team])

    suffix = "試合開始するなら !1 を送ってください" if require_start else "試合を開始します"
    mode_name = get_mode_config()["name"] if get_mode_config() else "不明"

    return (
        f"🔥チーム決定🔥\n"
        f"モード：{mode_name}\n\n"
        f"【アルファ】\n{fmt(team1)}\n\n"
        f"【ブラボー】\n{fmt(team2)}\n\n"
        f"{suffix}"
    )


def create_result_prompt(team1, team2):
    def fmt(team):
        lines = []
        for user in team:
            rate = ratings.get(str(user.id), DEFAULT_RATING)
            lines.append(f"{user.display_name} {rate}")
        return "\n".join(lines)

    return (
        f"【アルファ】\n{fmt(team1)}\n\n"
        f"【ブラボー】\n{fmt(team2)}\n\n"
        f"!1 アルファ勝ち\n"
        f"!2 ブラボー勝ち\n"
        f"!3 @ユーザー 回線落ち"
    )


def create_finished_prompt():
    return (
        "次の試合に進みますか？\n\n"
        "!1 で続ける\n"
        "!2 で終わる\n"
        "!3 で試合結果の訂正"
    )


def is_mode_full():
    config = get_mode_config()
    if not config:
        return False

    for role in config["roles"]:
        if len(players[role["key"]]) != role["cap"]:
            return False
    return True


# =========================
# モード別チーム生成
# =========================
def make_teams_mode_a():
    random.shuffle(players["back"])
    random.shuffle(players["other"])
    team1 = [players["back"][0]] + players["other"][:3]
    team2 = [players["back"][1]] + players["other"][3:6]
    return team1, team2


def make_teams_mode_b():
    random.shuffle(players["back"])
    random.shuffle(players["paint"])
    random.shuffle(players["other"])
    team1 = [players["back"][0], players["paint"][0]] + players["other"][:2]
    team2 = [players["back"][1], players["paint"][1]] + players["other"][2:4]
    return team1, team2


def make_teams_mode_c():
    random.shuffle(players["energy"])
    random.shuffle(players["lact"])
    random.shuffle(players["other"])
    team1 = [players["energy"][0], players["lact"][0]] + players["other"][:2]
    team2 = [players["energy"][1], players["lact"][1]] + players["other"][2:4]
    return team1, team2


def make_teams_mode_d():
    all_players = players["other"][:]
    random.shuffle(all_players)
    return all_players[:4], all_players[4:8]


TEAM_BUILDERS = {
    "a": make_teams_mode_a,
    "b": make_teams_mode_b,
    "c": make_teams_mode_c,
    "d": make_teams_mode_d,
}


def make_teams():
    builder = TEAM_BUILDERS.get(current_mode)
    if builder is None:
        return [], []
    return builder()


# =========================
# VC移動
# =========================
async def move_members_to_vc(guild, team1, team2):
    vc_alpha = guild.get_channel(VC_ALPHA_ID)
    vc_bravo = guild.get_channel(VC_BRAVO_ID)

    if vc_alpha is None or vc_bravo is None:
        return

    for member in team1:
        if member.voice:
            await member.move_to(vc_alpha)

    for member in team2:
        if member.voice:
            await member.move_to(vc_bravo)


# =========================
# 募集ボタン
# =========================
class RoleJoinButton(discord.ui.Button):
    def __init__(self, role_key, label):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.role_key = role_key

    async def callback(self, interaction: discord.Interaction):
        global game_state
        user = interaction.user

        if game_state != "waiting":
            await interaction.response.send_message("今は募集していません", ephemeral=True)
            return

        if is_user_joined(user):
            await interaction.response.send_message("既に参加しています", ephemeral=True)
            return

        role = get_role_config(self.role_key)
        if role is None:
            await interaction.response.send_message("その役割は使えません", ephemeral=True)
            return

        if len(players[self.role_key]) >= role["cap"]:
            await interaction.response.send_message(f"{role['label']}は満員！", ephemeral=True)
            return

        players[self.role_key].append(user)
        await interaction.response.edit_message(content=create_recruit_text(), view=self.view)
        await check_full(interaction)


class LeaveButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="抜ける", style=discord.ButtonStyle.gray)

    async def callback(self, interaction: discord.Interaction):
        global game_state
        user = interaction.user

        if game_state != "waiting":
            await interaction.response.send_message("試合準備が進んでいるので今は抜けられません", ephemeral=True)
            return

        removed = False
        for role_key in players:
            if user in players[role_key]:
                players[role_key].remove(user)
                removed = True
                break

        if not removed:
            await interaction.response.send_message("まだ参加していません", ephemeral=True)
            return

        await interaction.response.edit_message(content=create_recruit_text(), view=self.view)


class JoinView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        config = get_mode_config()
        if config:
            for role in config["roles"]:
                self.add_item(RoleJoinButton(role["key"], role["label"]))
        self.add_item(LeaveButton())

    def disable_all_buttons(self):
        for item in self.children:
            item.disabled = True


# =========================
# 試合進行
# =========================
async def start_recruit(ctx):
    global recruit_message
    recruit_message = await ctx.send(create_recruit_text())
    view = JoinView()
    await recruit_message.edit(content=create_recruit_text(), view=view)


async def check_full(interaction):
    global last_match, game_state

    if not is_mode_full():
        return

    team1, team2 = make_teams()
    last_match = (team1, team2)
    game_state = "ready"

    await interaction.followup.send(create_team_text(team1, team2, require_start=True))

    view = JoinView()
    view.disable_all_buttons()
    await interaction.message.edit(view=view)


async def start_game(ctx):
    global game_state, last_match

    if not last_match:
        await ctx.send("試合情報がないよ")
        return

    team1, team2 = last_match
    game_state = "playing"

    await ctx.send("試合を開始します")
    await move_members_to_vc(ctx.guild, team1, team2)
    await ctx.send(create_result_prompt(team1, team2))


async def next_game(ctx):
    global game_state, last_match

    team1, team2 = make_teams()
    last_match = (team1, team2)
    game_state = "playing"

    await ctx.send(create_team_text(team1, team2, require_start=False))
    await move_members_to_vc(ctx.guild, team1, team2)
    await ctx.send(create_result_prompt(team1, team2))


async def process_result(ctx, winner_num: int):
    global last_match, ratings, game_state, last_rating_changes

    if not last_match:
        await ctx.send("試合がないよ")
        return

    team1, team2 = last_match

    def avg(team):
        return sum([ratings.get(str(user.id), DEFAULT_RATING) for user in team]) / len(team)

    avg1 = avg(team1)
    avg2 = avg(team2)

    s1, s2 = (1, 0) if winner_num == 1 else (0, 1)

    last_rating_changes = {}
    result_text = "【レート更新】\n5点が追加されました\n\n"

    for user in team1:
        old = ratings.get(str(user.id), DEFAULT_RATING)
        new = elo_update(old, avg2, s1)
        last_rating_changes[str(user.id)] = old
        ratings[str(user.id)] = new
        result_text += f"{user.display_name}: {old} → {new}\n"

    result_text += "\n"

    for user in team2:
        old = ratings.get(str(user.id), DEFAULT_RATING)
        new = elo_update(old, avg1, s2)
        last_rating_changes[str(user.id)] = old
        ratings[str(user.id)] = new
        result_text += f"{user.display_name}: {old} → {new}\n"

    save_ratings(ratings)
    game_state = "finished"

    await ctx.send(result_text)
    await ctx.send(create_finished_prompt())


async def handle_disconnect(ctx, member):
    global ratings, game_state, last_rating_changes, last_match

    if not last_match:
        await ctx.send("試合情報がないよ")
        return

    team1, team2 = last_match
    all_players = team1 + team2

    if member not in all_players:
        await ctx.send("そのユーザーは今回の試合に参加していません")
        return

    penalty = 21
    receivers = [user for user in all_players if user != member]

    if len(receivers) == 0:
        await ctx.send("分配先がいません")
        return

    if penalty % len(receivers) != 0:
        await ctx.send("均等配分できない設定になっています")
        return

    reward_each = penalty // len(receivers)

    last_rating_changes = {}

    old_member_rate = ratings.get(str(member.id), DEFAULT_RATING)
    last_rating_changes[str(member.id)] = old_member_rate
    ratings[str(member.id)] = old_member_rate - penalty

    result_lines = [
        "【回線落ち処理】",
        "「有罪（ギルティ）」",
        "「没収（コンフィスケイション）」",
        f"{member.display_name}: {old_member_rate} → {ratings[str(member.id)]} (-{penalty})",
        ""
    ]

    for user in receivers:
        old_rate = ratings.get(str(user.id), DEFAULT_RATING)
        last_rating_changes[str(user.id)] = old_rate
        new_rate = old_rate + reward_each
        ratings[str(user.id)] = new_rate
        result_lines.append(f"{user.display_name}: {old_rate} → {new_rate} (+{reward_each})")

    save_ratings(ratings)
    game_state = "finished"

    await ctx.send("\n".join(result_lines))
    await ctx.send(create_finished_prompt())


async def undo_result(ctx):
    global ratings, last_rating_changes, game_state

    if not last_rating_changes:
        await ctx.send("戻せる試合結果がありません")
        return

    for user_id, old_rate in last_rating_changes.items():
        ratings[user_id] = old_rate

    save_ratings(ratings)
    last_rating_changes = None
    game_state = "playing"

    await ctx.send("試合結果を訂正しました")
    if last_match:
        team1, team2 = last_match
        await ctx.send(create_result_prompt(team1, team2))


async def end_room(ctx):
    global current_mode, game_state, last_match, recruit_message, last_rating_changes

    reset_players()
    current_mode = None
    last_match = None
    recruit_message = None
    last_rating_changes = None
    game_state = "idle"

    await ctx.send("部屋作成をやめました。次の募集をするときは !部屋作成 を使ってね")


# =========================
# 状態別コマンド処理
# =========================
async def handle_mode_select(ctx, cmd_num: int):
    global current_mode, game_state

    mode_map = {
        1: "a",
        2: "b",
        3: "c",
        4: "d",
    }

    if cmd_num == 5:
        await end_room(ctx)
        return

    selected_mode = mode_map.get(cmd_num)
    if selected_mode is None:
        await ctx.send("モード選択は !1〜!5")
        return

    current_mode = selected_mode
    game_state = "waiting"
    await start_recruit(ctx)


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
            await handle_disconnect(ctx, ctx.message.mentions[0])
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


STATE_HANDLERS = {
    "mode_select": handle_mode_select,
    "ready": handle_ready,
    "playing": handle_playing,
    "finished": handle_finished,
}


async def dispatch_number_command(ctx, cmd_num: int):
    handler = STATE_HANDLERS.get(game_state)
    if handler is None:
        await ctx.send(f"今は !{cmd_num} を受け付ける状態じゃない")
        return
    await handler(ctx, cmd_num)


# =========================
# コマンド
# =========================
@bot.event
async def on_ready():
    print(f"ログインしたよ: {bot.user}")


@bot.command()
async def 部屋作成(ctx):
    global current_mode, game_state, last_match, recruit_message, last_rating_changes

    reset_players()
    current_mode = None
    last_match = None
    recruit_message = None
    last_rating_changes = None
    game_state = "mode_select"

    await ctx.send(create_mode_select_text())


@bot.command(name="1")
async def command_one(ctx):
    await dispatch_number_command(ctx, 1)


@bot.command(name="2")
async def command_two(ctx):
    await dispatch_number_command(ctx, 2)


@bot.command(name="3")
async def command_three(ctx):
    await dispatch_number_command(ctx, 3)


@bot.command(name="4")
async def command_four(ctx):
    await dispatch_number_command(ctx, 4)


@bot.command(name="5")
async def command_five(ctx):
    await dispatch_number_command(ctx, 5)


@bot.command()
async def result(ctx, num: int):
    if num == 1:
        await process_result(ctx, 1)
    elif num == 2:
        await process_result(ctx, 2)
    else:
        await ctx.send("今は !result 1 か !result 2 だけ使えます")


if __name__ == "__main__":
    if not TOKEN:
        raise ValueError("DISCORD_TOKEN が設定されていません")
    reset_players()
    bot.run(TOKEN)
