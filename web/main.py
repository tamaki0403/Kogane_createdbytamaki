import os
import json
import uuid
from fastapi import FastAPI, File, UploadFile, Form, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from fastapi.responses import JSONResponse
import json

app = FastAPI(default_response_class=JSONResponse)


DATA_DIR = os.path.join(os.path.dirname(__file__), "test_data")
RATINGS_FILE = os.path.join(DATA_DIR, "ratings.json")
PLAYER_PROFILES_FILE = os.path.join(DATA_DIR, "player_profiles.json")
WEB_BADGE_FILE = os.path.join(DATA_DIR, "web_badge_definitions.json")
WEB_BANNER_FILE = os.path.join(DATA_DIR, "web_banner_definitions.json")

DEFAULT_RATING = 2500

# 運営（OWNER）のDiscordユーザーID。bot.py側と同じ値を使用する。
OWNER_ID = 1225788050894753865


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def load_json_list(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# =========================
# 画像アップロード（バッジ・バナー用のスタブ実装。bot.py側と同仕様）
# =========================
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
# "/" の catch-all マウント（このファイル末尾）より前に登録する必要がある
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
ALLOWED_IMAGE_CONTENT_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
MAX_UPLOAD_SIZE_BYTES = 5 * 1024 * 1024  # 5MB


@app.post("/api/upload_image")
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
# Web用バッジ・バナー CRUD（bot.py側と同仕様のスタブ実装）
# =========================
@app.get("/api/web_badges")
def get_web_badges():
    return {"badges": load_json_list(WEB_BADGE_FILE)}


@app.post("/api/web_badges")
async def create_web_badge(request: Request):
    body = await request.json()
    user_id = body.get("user_id")
    if user_id != str(OWNER_ID):
        return JSONResponse(content={"error": "権限がありません"}, status_code=403)

    label = body.get("label", "").strip()
    image_url = body.get("image_url", "").strip()
    if not label:
        return JSONResponse(content={"error": "ラベルは必須です"}, status_code=400)

    badges = load_json_list(WEB_BADGE_FILE)
    new_badge = {"id": uuid.uuid4().hex[:8], "label": label, "image_url": image_url}
    badges.append(new_badge)
    save_json(WEB_BADGE_FILE, badges)
    return {"success": True, "badge": new_badge}


@app.put("/api/web_badges/{badge_id}")
async def update_web_badge(badge_id: str, request: Request):
    body = await request.json()
    user_id = body.get("user_id")
    if user_id != str(OWNER_ID):
        return JSONResponse(content={"error": "権限がありません"}, status_code=403)

    badges = load_json_list(WEB_BADGE_FILE)
    for badge in badges:
        if badge["id"] == badge_id:
            badge["label"] = body.get("label", badge["label"]).strip()
            badge["image_url"] = body.get("image_url", badge["image_url"]).strip()
            save_json(WEB_BADGE_FILE, badges)
            return {"success": True, "badge": badge}
    return JSONResponse(content={"error": "バッジが見つかりません"}, status_code=404)


@app.delete("/api/web_badges/{badge_id}")
async def delete_web_badge(badge_id: str, request: Request):
    body = await request.json()
    user_id = body.get("user_id")
    if user_id != str(OWNER_ID):
        return JSONResponse(content={"error": "権限がありません"}, status_code=403)

    badges = load_json_list(WEB_BADGE_FILE)
    new_badges = [b for b in badges if b["id"] != badge_id]
    if len(new_badges) == len(badges):
        return JSONResponse(content={"error": "バッジが見つかりません"}, status_code=404)
    save_json(WEB_BADGE_FILE, new_badges)
    return {"success": True}


@app.get("/api/web_banners")
def get_web_banners():
    return {"banners": load_json_list(WEB_BANNER_FILE)}


@app.post("/api/web_banners")
async def create_web_banner(request: Request):
    body = await request.json()
    user_id = body.get("user_id")
    if user_id != str(OWNER_ID):
        return JSONResponse(content={"error": "権限がありません"}, status_code=403)

    label = body.get("label", "").strip()
    image_url = body.get("image_url", "").strip()
    if not label:
        return JSONResponse(content={"error": "ラベルは必須です"}, status_code=400)

    banners = load_json_list(WEB_BANNER_FILE)
    new_banner = {"id": uuid.uuid4().hex[:8], "label": label, "image_url": image_url}
    banners.append(new_banner)
    save_json(WEB_BANNER_FILE, banners)
    return {"success": True, "banner": new_banner}


@app.put("/api/web_banners/{banner_id}")
async def update_web_banner(banner_id: str, request: Request):
    body = await request.json()
    user_id = body.get("user_id")
    if user_id != str(OWNER_ID):
        return JSONResponse(content={"error": "権限がありません"}, status_code=403)

    banners = load_json_list(WEB_BANNER_FILE)
    for banner in banners:
        if banner["id"] == banner_id:
            banner["label"] = body.get("label", banner["label"]).strip()
            banner["image_url"] = body.get("image_url", banner["image_url"]).strip()
            save_json(WEB_BANNER_FILE, banners)
            return {"success": True, "banner": banner}
    return JSONResponse(content={"error": "バナーが見つかりません"}, status_code=404)


@app.delete("/api/web_banners/{banner_id}")
async def delete_web_banner(banner_id: str, request: Request):
    body = await request.json()
    user_id = body.get("user_id")
    if user_id != str(OWNER_ID):
        return JSONResponse(content={"error": "権限がありません"}, status_code=403)

    banners = load_json_list(WEB_BANNER_FILE)
    new_banners = [b for b in banners if b["id"] != banner_id]
    if len(new_banners) == len(banners):
        return JSONResponse(content={"error": "バナーが見つかりません"}, status_code=404)
    save_json(WEB_BANNER_FILE, new_banners)
    return {"success": True}


# =========================
# プレイヤーへのバッジ・バナー付与（bot.py側と同仕様のスタブ実装）
# =========================
def get_player_profile_dict(user_id: str):
    profiles = load_json(PLAYER_PROFILES_FILE)
    if user_id not in profiles:
        profiles[user_id] = {}
    return profiles, profiles[user_id]


@app.post("/api/web_badge/grant")
async def grant_web_badge(request: Request):
    body = await request.json()
    user_id = body.get("user_id")
    target_id = body.get("target_id")
    badge_id = body.get("badge_id")

    if user_id != str(OWNER_ID):
        return JSONResponse(content={"error": "権限がありません"}, status_code=403)

    badge_ids = [b["id"] for b in load_json_list(WEB_BADGE_FILE)]
    if badge_id not in badge_ids:
        return JSONResponse(content={"error": "バッジが存在しません"}, status_code=404)

    profiles, profile = get_player_profile_dict(str(target_id))
    owned = profile.get("owned_web_badges", [])
    if badge_id not in owned:
        owned.append(badge_id)
        profile["owned_web_badges"] = owned
        save_json(PLAYER_PROFILES_FILE, profiles)

    return {"success": True}


@app.post("/api/web_banner/grant")
async def grant_web_banner(request: Request):
    body = await request.json()
    user_id = body.get("user_id")
    target_id = body.get("target_id")
    banner_id = body.get("banner_id")

    if user_id != str(OWNER_ID):
        return JSONResponse(content={"error": "権限がありません"}, status_code=403)

    banner_ids = [b["id"] for b in load_json_list(WEB_BANNER_FILE)]
    if banner_id not in banner_ids:
        return JSONResponse(content={"error": "バナーが存在しません"}, status_code=404)

    profiles, profile = get_player_profile_dict(str(target_id))
    owned = profile.get("owned_web_banners", [])
    if banner_id not in owned:
        owned.append(banner_id)
        profile["owned_web_banners"] = owned
        save_json(PLAYER_PROFILES_FILE, profiles)

    return {"success": True}


@app.get("/api/admin/stats")
def get_admin_stats(user_id: str = ""):
    if user_id != str(OWNER_ID):
        return JSONResponse(content={"error": "権限がありません"}, status_code=403)
    # スタブサーバーではアクセスログを保持しないため空データを返す
    return {"site_log": [], "mypage_stats": []}


def resolve_web_badge_banner(profile, web_badges, web_banners):
    """プロフィールのselected_web_badge/selected_web_bannerを画像URLに解決する（bot.py側と同仕様）"""
    badge_def = web_badges.get(profile.get("selected_web_badge"))
    banner_def = web_banners.get(profile.get("selected_web_banner"))

    badge_url = badge_def["image_url"] if badge_def else None
    banner_url = banner_def["image_url"] if banner_def else None
    return badge_url, banner_url


@app.get("/api/ranking")
def get_ranking():
    """レートランキングを返す"""
    ratings = load_json(RATINGS_FILE)
    profiles = load_json(PLAYER_PROFILES_FILE)
    web_badges = {b["id"]: b for b in load_json_list(WEB_BADGE_FILE)}
    web_banners = {b["id"]: b for b in load_json_list(WEB_BANNER_FILE)}

    players = []
    for uid, data in ratings.items():
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
            "weapon": profile.get("weapon") or "未登録",
            "xp": profile.get("xp"),
            "peak_rating": profile.get("peak_rating"),
            "avatar_url": profile.get("avatar_url"),
            "selected_badge_url": badge_url,
            "selected_banner_url": banner_url,
        })

    players.sort(key=lambda x: -x["rating"])
    for i, p in enumerate(players):
        p["rank"] = i + 1

    return {"players": players}


@app.get("/api/peak_ranking")
def get_peak_ranking():
    """最高レートランキングを返す"""
    profiles = load_json(PLAYER_PROFILES_FILE)
    web_badges = {b["id"]: b for b in load_json_list(WEB_BADGE_FILE)}
    web_banners = {b["id"]: b for b in load_json_list(WEB_BANNER_FILE)}

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
            "avatar_url": profile.get("avatar_url"),
            "selected_badge_url": badge_url,
            "selected_banner_url": banner_url,
        })

    players.sort(key=lambda x: -x["peak_rating"])
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
