"""Clipfarm Poster -- public deployment.

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
from flask import Flask, redirect, render_template_string, request, session

CLIENT_KEY = os.environ.get("TIKTOK_CLIENT_KEY", "")
CLIENT_SECRET = os.environ.get("TIKTOK_CLIENT_SECRET", "")
# Not set until the real Render URL is known -- must not crash the app at
# startup (that would fail the whole deploy) even before it's filled in.
REDIRECT_URI = os.environ.get("TIKTOK_REDIRECT_URI", "")

AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
POST_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

PAGE = """
<!doctype html><html><head><title>Clipfarm Poster</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{font-family:system-ui,sans-serif;max-width:680px;margin:0 auto;padding:48px 24px;color:#161823;line-height:1.55}
h1{margin-bottom:4px}
.tag{color:#666;margin-top:0}
.card{background:#f7f7f8;border-radius:12px;padding:20px 24px;margin:24px 0}
.step{display:flex;gap:12px;margin-bottom:14px}
.step b{flex:none;width:22px}
a.btn,button{display:inline-block;padding:13px 26px;background:#000;color:#fff;
text-decoration:none;border-radius:8px;font-size:16px;border:none;cursor:pointer;margin-top:8px}
.msg{margin-top:20px;padding:12px 16px;border-radius:8px;background:#eef7ee}
code{background:#eee;padding:2px 6px;border-radius:4px;font-size:14px}
</style></head><body>

<h1>Clipfarm Poster</h1>
<p class="tag">Publishes short clips to TikTok on behalf of the account that connects below.</p>

<div class="card">
  <p><strong>What this does:</strong> a clipping tool downloads long-form video, an AI step
  picks the highlight moments that fit a campaign's brief, edits them into vertical clips
  with captions, then this page hands off to TikTok's own login so the connecting account
  can publish the result directly through TikTok's Content Posting API -- no separate
  account system, no password of ours involved.</p>
  <div class="step"><b>1.</b> Click "Log in with TikTok" below.</div>
  <div class="step"><b>2.</b> Authenticate with your own TikTok account, on TikTok's own page.</div>
  <div class="step"><b>3.</b> Once connected, click "Post test clip" to publish a short video
  through the Content Posting API (sandbox visibility until this app is audited).</div>
</div>

{% if not access_token %}
  <a class="btn" href="/login">Log in with TikTok</a>
{% else %}
  <p>Connected -- open_id: <code>{{ open_id }}</code></p>
  <form method="post" action="/post"><button type="submit">Post test clip</button></form>
{% endif %}
{% if message %}<div class="msg">{{ message }}</div>{% endif %}

</body></html>
"""


@app.route("/tiktokyB8uopVKkZIBGhYaAF0lQjK1VTOLiK8n.txt")
def tiktok_site_verification():
    # Proves ownership of this domain to TikTok's app review -- content and
    # filename must match exactly what the dashboard's verification step issued.
    return "tiktok-developers-site-verification=yB8uopVKkZIBGhYaAF0lQjK1VTOLiK8n", 200, {"Content-Type": "text/plain"}


@app.route("/")
def home():
    return render_template_string(
        PAGE,
        access_token=session.get("access_token"),
        open_id=session.get("open_id"),
        message=session.pop("message", None),
    )


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
            "post_info": {"title": "Clipfarm Poster -- review test post", "privacy_level": "SELF_ONLY", "is_aigc": False},
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
