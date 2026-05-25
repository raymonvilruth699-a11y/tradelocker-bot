from flask import Flask, request, jsonify
import os
import requests

app = Flask(__name__)

BASE = "https://live.tradelocker.com/backend-api" if os.getenv("TL_ENV") == "live" else "https://demo.tradelocker.com/backend-api"

def login():
    payload = {
        "email": os.getenv("TL_EMAIL"),
        "password": os.getenv("TL_PASSWORD"),
        "server": os.getenv("TL_SERVER")
    }

    r = requests.post(f"{BASE}/auth/jwt/token", json=payload, timeout=20)
    r.raise_for_status()
    return r.json()

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "bot online"})

@app.route("/test-login", methods=["GET"])
def test_login():
    try:
        token_data = login()
        return jsonify({
            "status": "login_success",
            "has_access_token": "accessToken" in token_data
        })
    except Exception as e:
        return jsonify({"status": "login_failed", "error": str(e)}), 500

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json or {}

    if data.get("secret") != os.getenv("WEBHOOK_SECRET"):
        return jsonify({"error": "bad secret"}), 403

    return jsonify({
        "status": "received",
        "data": data
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)