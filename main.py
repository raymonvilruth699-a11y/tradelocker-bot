from flask import Flask, request, jsonify
from tradelocker import TLAPI
import os
import traceback
import re

app = Flask(__name__)

TL_EMAIL = os.getenv("TL_EMAIL")
TL_PASSWORD = os.getenv("TL_PASSWORD")
TL_SERVER = os.getenv("TL_SERVER")
TL_ENV = os.getenv("TL_ENV", "live")
TL_ACCOUNT_ID = os.getenv("TL_ACCOUNT_ID")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

INSTRUMENT_CACHE = {}
RAW_INSTRUMENTS = None


def clean_symbol(symbol):
    return re.sub(r"[^A-Z0-9]", "", str(symbol).upper())


def get_tl():
    tl = TLAPI(
        environment=TL_ENV,
        server=TL_SERVER,
        email=TL_EMAIL,
        password=TL_PASSWORD
    )

    tl.get_all_accounts()

    if TL_ACCOUNT_ID:
        try:
            tl.set_account(TL_ACCOUNT_ID)
        except Exception as e:
            print("ACCOUNT SET WARNING:", str(e), flush=True)

    return tl


def load_instruments():
    global INSTRUMENT_CACHE, RAW_INSTRUMENTS

    print("Loading TradeLocker instruments...", flush=True)

    tl = get_tl()
    instruments = tl.get_all_instruments()
    RAW_INSTRUMENTS = instruments

    cache = {}

    for _, row in instruments.iterrows():
        name = str(row.get("name", ""))
        instrument_id = row.get("tradableInstrumentId")

        if not name or not instrument_id:
            continue

        cleaned = clean_symbol(name)

        cache[cleaned] = {
            "id": instrument_id,
            "name": name
        }

        base = cleaned.replace("R", "").replace("M", "").replace("B", "")
        if base not in cache:
            cache[base] = {
                "id": instrument_id,
                "name": name
            }

    INSTRUMENT_CACHE = cache

    print(f"Loaded {len(INSTRUMENT_CACHE)} instrument mappings", flush=True)
    return cache


def find_instrument(symbol):
    if not INSTRUMENT_CACHE:
        load_instruments()

    requested = clean_symbol(symbol)

    if requested in INSTRUMENT_CACHE:
        return INSTRUMENT_CACHE[requested]

    matches = []
    for key, value in INSTRUMENT_CACHE.items():
        if requested in key or key in requested:
            matches.append(value)

    if matches:
        print("Possible matches:", matches[:10], flush=True)
        return matches[0]

    raise Exception(f"No instrument found for {symbol}")


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "bot online",
        "env": TL_ENV,
        "cached_symbols": len(INSTRUMENT_CACHE)
    })


@app.route("/reload-instruments", methods=["GET"])
def reload_instruments():
    try:
        load_instruments()
        return jsonify({
            "status": "reloaded",
            "cached_symbols": len(INSTRUMENT_CACHE)
        })
    except Exception as e:
        print("RELOAD ERROR:", traceback.format_exc(), flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/find-symbol/<symbol>", methods=["GET"])
def find_symbol(symbol):
    try:
        match = find_instrument(symbol)
        return jsonify({
            "requested": symbol,
            "matched_name": match["name"],
            "instrument_id": str(match["id"])
        })
    except Exception as e:
        return jsonify({"status": "not_found", "message": str(e)}), 404


@app.route("/test-login", methods=["GET"])
def test_login():
    try:
        load_instruments()
        return jsonify({
            "status": "login_success",
            "cached_symbols": len(INSTRUMENT_CACHE)
        })
    except Exception as e:
        print("LOGIN ERROR:", traceback.format_exc(), flush=True)
        return jsonify({"status": "login_failed", "error": str(e)}), 500


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json or {}
    print("WEBHOOK RECEIVED:", data, flush=True)

    if data.get("secret") != WEBHOOK_SECRET:
        return jsonify({"error": "bad secret"}), 403

    symbol = data.get("symbol")
    action = str(data.get("action", "")).lower()
    lots = float(data.get("lots", data.get("qty", 0.01)))

    if action not in ["buy", "sell"]:
        return jsonify({"error": "action must be buy or sell"}), 400

    try:
        tl = get_tl()

        match = find_instrument(symbol)
        instrument_id = match["id"]

        print(f"USING SYMBOL: {symbol} -> {match['name']} | ID: {instrument_id}", flush=True)

        order = tl.create_order(
            instrument_id,
            quantity=lots,
            side=action,
            type_="market"
        )

        print("ORDER SENT:", order, flush=True)

        return jsonify({
            "status": "order_sent",
            "requested_symbol": symbol,
            "matched_symbol": match["name"],
            "instrument_id": str(instrument_id),
            "action": action,
            "lots": lots,
            "order": str(order)
        })

    except Exception as e:
        print("ORDER ERROR:", traceback.format_exc(), flush=True)
        return jsonify({
            "status": "order_failed",
            "error": str(e),
            "received": data
        }), 500


try:
    load_instruments()
except Exception as e:
    print("Startup instrument preload failed:", str(e), flush=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)