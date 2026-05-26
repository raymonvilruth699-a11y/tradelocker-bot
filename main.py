from flask import Flask, request, jsonify
from tradelocker import TLAPI
import os
import traceback
import re

app = Flask(__name__)

# =========================
# ENV VARIABLES
# =========================
TL_EMAIL = os.getenv("TL_EMAIL")
TL_PASSWORD = os.getenv("TL_PASSWORD")
TL_SERVER = os.getenv("TL_SERVER")
TL_ENV = os.getenv("TL_ENV", "live")
TL_ACCOUNT_ID = os.getenv("TL_ACCOUNT_ID")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

INSTRUMENT_CACHE = {}


# =========================
# CLEAN SYMBOL
# =========================
def clean_symbol(symbol):
    return re.sub(r"[^A-Z0-9]", "", str(symbol).upper())


# =========================
# LOGIN
# =========================
def get_tl():

    env_url = (
        "https://live.tradelocker.com"
        if TL_ENV == "live"
        else "https://demo.tradelocker.com"
    )

    print(f"CONNECTING TO: {env_url}", flush=True)

    tl = TLAPI(
        environment=env_url,
        username=TL_EMAIL,
        password=TL_PASSWORD,
        server=TL_SERVER
    )

    # FORCE ACCOUNT
    if TL_ACCOUNT_ID:
        try:
            print(f"FORCING ACCOUNT ID: {TL_ACCOUNT_ID}", flush=True)

            tl.set_account_id_and_acc_num(
                int(TL_ACCOUNT_ID),
                2
            )

        except Exception as e:
            print("ACCOUNT FORCE ERROR:", str(e), flush=True)

    return tl


# =========================
# LOAD INSTRUMENTS
# =========================
def load_instruments():

    global INSTRUMENT_CACHE

    print("Loading TradeLocker instruments...", flush=True)

    tl = get_tl()

    instruments = tl.get_all_instruments()

    cache = {}

    print(instruments.head(), flush=True)

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

        # simplified aliases
        simplified = (
            cleaned
            .replace(".B", "")
            .replace(".R", "")
            .replace(".M", "")
        )

        if simplified not in cache:
            cache[simplified] = {
                "id": instrument_id,
                "name": name
            }

    INSTRUMENT_CACHE = cache

    print(f"Loaded {len(INSTRUMENT_CACHE)} symbols", flush=True)


# =========================
# FIND SYMBOL
# =========================
def find_instrument(symbol):

    if not INSTRUMENT_CACHE:
        load_instruments()

    cleaned = clean_symbol(symbol)

    # exact match
    if cleaned in INSTRUMENT_CACHE:
        return INSTRUMENT_CACHE[cleaned]

    # partial match
    for key, value in INSTRUMENT_CACHE.items():

        if cleaned in key or key in cleaned:

            print(
                f"PARTIAL MATCH: {symbol} -> {value}",
                flush=True
            )

            return value

    raise Exception(f"No instrument found for {symbol}")


# =========================
# HOME
# =========================
@app.route("/", methods=["GET"])
def home():

    return jsonify({
        "status": "online",
        "environment": TL_ENV,
        "account_id": TL_ACCOUNT_ID,
        "symbols_loaded": len(INSTRUMENT_CACHE)
    })


# =========================
# TEST LOGIN
# =========================
@app.route("/test-login", methods=["GET"])
def test_login():

    try:

        load_instruments()

        return jsonify({
            "status": "success",
            "account_id": TL_ACCOUNT_ID,
            "symbols_loaded": len(INSTRUMENT_CACHE)
        })

    except Exception as e:

        print(traceback.format_exc(), flush=True)

        return jsonify({
            "status": "failed",
            "error": str(e)
        }), 500


# =========================
# RELOAD SYMBOLS
# =========================
@app.route("/reload-instruments", methods=["GET"])
def reload_instruments():

    try:

        load_instruments()

        return jsonify({
            "status": "reloaded",
            "symbols_loaded": len(INSTRUMENT_CACHE)
        })

    except Exception as e:

        print(traceback.format_exc(), flush=True)

        return jsonify({
            "status": "failed",
            "error": str(e)
        }), 500


# =========================
# FIND SYMBOL ROUTE
# =========================
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

        return jsonify({
            "status": "not_found",
            "error": str(e)
        }), 404


# =========================
# WEBHOOK
# =========================
@app.route("/webhook", methods=["POST"])
def webhook():

    data = request.json or {}

    print("WEBHOOK RECEIVED:", data, flush=True)

    if data.get("secret") != WEBHOOK_SECRET:
        return jsonify({
            "error": "bad secret"
        }), 403

    symbol = data.get("symbol")
    action = str(data.get("action", "")).lower()

    lots = float(
        data.get(
            "lots",
            data.get("qty", 0.01)
        )
    )

    if action not in ["buy", "sell"]:

        return jsonify({
            "error": "action must be buy or sell"
        }), 400

    try:

        tl = get_tl()

        match = find_instrument(symbol)

        instrument_id = match["id"]

        print(
            f"USING ACCOUNT={TL_ACCOUNT_ID} | "
            f"SYMBOL={symbol} -> {match['name']} | "
            f"ID={instrument_id} | "
            f"ACTION={action} | "
            f"LOTS={lots}",
            flush=True
        )

        order = tl.create_order(
            instrument_id=instrument_id,
            quantity=lots,
            side=action,
            type_="market"
        )

        print("ORDER SENT:", order, flush=True)

        return jsonify({
            "status": "success",
            "account_id": TL_ACCOUNT_ID,
            "requested_symbol": symbol,
            "matched_symbol": match["name"],
            "instrument_id": str(instrument_id),
            "action": action,
            "lots": lots,
            "order": str(order)
        })

    except Exception as e:

        print(
            "ORDER ERROR:",
            traceback.format_exc(),
            flush=True
        )

        return jsonify({
            "status": "failed",
            "error": str(e),
            "received": data
        }), 500


# =========================
# STARTUP
# =========================
try:

    load_instruments()

except Exception as e:

    print(
        "Startup preload failed:",
        str(e),
        flush=True
    )


# =========================
# RUN
# =========================
if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=8080
    )