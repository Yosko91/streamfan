"""Streamfan -- public deployment.

Same real TikTok Login Kit + Content Posting API flow as the local demo,
adapted to run on a real host (Render) instead of localhost:
  - listens on $PORT (Render's convention) instead of a hardcoded port
  - no self-signed cert: Render terminates HTTPS at its edge, so this
    process just serves plain HTTP internally
  - a real descriptive home page instead of a bare stub, so this reads as
    a developed product to a human reviewer, not a placeholder
  - secrets come from Render's environment variables, never committed
"""
import os
import secrets
from urllib.parse import urlencode

import requests
from flask import Flask, abort, redirect, render_template, request, session, url_for

CLIENT_KEY = os.environ.get("TIKTOK_CLIENT_KEY", "").strip()
CLIENT_SECRET = os.environ.get("TIKTOK_CLIENT_SECRET", "").strip()
# Not set until the real Render URL is known -- must not crash the app at
# startup (that would fail the whole deploy) even before it's filled in.
REDIRECT_URI = os.environ.get("TIKTOK_REDIRECT_URI", "").strip()

AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
POST_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(16)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")),  # HTTPS only on Render
)

# TikTok site-verification tokens (one per verified URL prefix). Each token is
# served at /tiktok<token>.txt with the exact content the dashboard expects.
TIKTOK_VERIFICATION_TOKENS = {
    "yB8uopVKkZIBGhYaAF0lQjK1VTOLiK8n",  # clipfarm-poster.onrender.com (old service)
    "5h5Ni8fahtYiwHjGD1flyBP8H1kBZEMJ",  # streamfan.onrender.com
}


@app.route("/tiktok<token>.txt")
def tiktok_site_verification(token):
    # Proves ownership of this domain to TikTok's app review.
    if token not in TIKTOK_VERIFICATION_TOKENS:
        abort(404)
    return f"tiktok-developers-site-verification={token}", 200, {"Content-Type": "text/plain"}


@app.route("/")
def home():
    return render_template(
        "home.html",
        access_token=session.get("access_token"),
        open_id=session.get("open_id"),
        message=session.pop("message", None),
    )


@app.route("/privacy-policy")
def privacy():
    return render_template("privacy.html")


@app.route("/terms-of-service")
def terms():
    return render_template("terms.html")


# Old / alternative addresses keep working and point at the canonical pages.
@app.route("/privacy")
@app.route("/privacy.html")
def privacy_alias():
    return redirect(url_for("privacy"), code=301)


@app.route("/terms")
@app.route("/tos")
@app.route("/tos.html")
def terms_alias():
    return redirect(url_for("terms"), code=301)


@app.route("/favicon.ico")
def favicon():
    return redirect(url_for("static", filename="favicon.ico"), code=301)


@app.route("/login")
def login():
    state = secrets.token_hex(8)
    session["oauth_state"] = state
    params = {
        "client_key": CLIENT_KEY,
        "response_type": "code",
        "scope": "user.info.basic,video.publish",
        "redirect_uri": REDIRECT_URI,
        "state": state,
    }
    return redirect(f"{AUTHORIZE_URL}?{urlencode(params)}")


@app.route("/callback")
def callback():
    if request.args.get("state") != session.get("oauth_state"):
        return "State mismatch (possible CSRF) -- aborting.", 400
    if request.args.get("error"):
        return f"TikTok denied authorization: {request.args.get('error')} -- {request.args.get('error_description')}", 400

    resp = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": CLIENT_KEY,
            "client_secret": CLIENT_SECRET,
            "code": request.args["code"],
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
        },
        timeout=30,
    )
    data = resp.json()
    if "access_token" not in data:
        return f"Token exchange failed: {data}", 400

    session["access_token"] = data["access_token"]
    session["open_id"] = data.get("open_id")
    return redirect("/")


@app.route("/post", methods=["POST"])
def post_video():
    access_token = session.get("access_token")
    if not access_token:
        return redirect("/login")

    # A real clip produced by the actual pipeline this app posts for --
    # reviewers see the genuine end-to-end flow, not a generic stand-in.
    video_url = "https://yosko91.github.io/streamfan/clips/short_01_final.mp4"

    init = requests.post(
        POST_INIT_URL,
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json; charset=UTF-8"},
        json={
            "post_info": {"title": "Streamfan -- review test post", "privacy_level": "SELF_ONLY", "is_aigc": False},
            "source_info": {"source": "PULL_FROM_URL", "video_url": video_url},
        },
        timeout=30,
    ).json()

    error = init.get("error", {})
    if error.get("code") not in (None, "ok"):
        session["message"] = f"Post failed: {error}"
    else:
        session["message"] = f"Posted. publish_id: {init['data']['publish_id']} (sandbox/private visibility)"

    return redirect("/")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
