import os
import json
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI()

DATA_DIR = "/data"
RATINGS_FILE = os.path.join(DATA_DIR, "ratings.json")
PLAYER_PROFILES_FILE = os.path.join(DATA_DIR, "player_profiles.json")

DEFAULT_RATING = 2500


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


@app.get("/api/ranking")
def get_ranking():
    """レートランキングを返す"""
    ratings = load_json(RATINGS_FILE)
    profiles = load_json(PLAYER_PROFILES_FILE)

    players = []
    for uid, data in ratings.items():
        if isinstance(data, dict):
            rating = int(round(data.get("rating", DEFAULT_RATING)))
        else:
            rating = int(round(float(data)))

        profile = profiles.get(uid, {})
        players.append({
            "user_id": uid,
            "rating": rating,
            "weapon": profile.get("weapon") or "未登録",
            "xp": profile.get("xp"),
            "peak_rating": profile.get("peak_rating"),
        })

    players.sort(key=lambda x: -x["rating"])
    for i, p in enumerate(players):
        p["rank"] = i + 1

    return {"players": players}


@app.get("/api/player/{user_id}")
def get_player(user_id: str):
    """特定プレイヤーの情報を返す"""
    ratings = load_json(RATINGS_FILE)
    profiles = load_json(PLAYER_PROFILES_FILE)

    data = ratings.get(user_id)
    if data is None:
        return {"error": "プレイヤーが見つかりません"}

    if isinstance(data, dict):
        rating = int(round(data.get("rating", DEFAULT_RATING)))
        rd = data.get("rd", 120.0)
    else:
        rating = int(round(float(data)))
        rd = 120.0

    profile = profiles.get(user_id, {})

    return {
        "user_id": user_id,
        "rating": rating,
        "rd": round(rd, 1),
        "weapon": profile.get("weapon") or "未登録",
        "xp": profile.get("xp"),
        "peak_rating": profile.get("peak_rating"),
        "coins": profile.get("coins", 0),
        "win_streak": profile.get("win_streak", 0),
    }


@app.get("/api/health")
def health():
    return {"status": "ok"}


# 静的ファイル（HTML）の配信
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
