import os
import re
import traceback
from flask import Flask, request, jsonify
from tradelocker import TLAPI

# ============================================
# CONFIG
# ============================================

TL_ENV = os.getenv("TL_ENV")
TL_EMAIL = os.getenv("TL_EMAIL")
TL_PASSWORD = os.getenv("TL_PASSWORD")
TL_SERVER = os.getenv("TL_SERVER")
TL_ACCOUNT_ID = int(os.getenv("TL_ACCOUNT_ID"))
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

# ============================================
# FLASK
# ============================================

app = Flask(__name__)

# ============================================
# HELPERS
# ============================================

INSTRUMENT_CACHE = {}

def clean_symbol(symbol):
    return re.sub(r"[^A-Z0-9]", "", str(symbol).upper())

# ============================================
# LOGIN
# ============================================

def get_tl():

    print("CONNECTING TO:", TL_ENV)

    tl = TLAPI(
        environment=TL_ENV,
        username=TL_EMAIL,
        password=TL_PASSWORD,
        server=TL_SERVER,
        log_level="debug"
    )

    # FORCE CORRECT ACCOUNT
    tl.set_account_id_and_acc_num(TL_ACCOUNT_ID, 2)

    return tl

# ============================================
# LOAD INSTRUMENTS
# ============================================

def load_instruments():

    global INSTRUMENT_CACHE

    print("Loading TradeLocker instruments...")

    tl = get_tl()

    instruments = tl.get_all_instruments()

    cache = {}

    for _, row in instruments.iterrows():

        try:

            instrument_name = str(row.get("name", "")).upper()
            tradable_id = str(row.get("tradableInstrumentId"))

            clean = clean_symbol(instrument_name)

            cache[clean] = tradable_id

        except Exception:
            pass

    INSTRUMENT_CACHE = cache

    print(f"Loaded {len(INSTRUMENT_CACHE)} symbols")

# ============================================
# FIND INSTRUMENT
# ============================================

def find_instrument(symbol):

    requested = clean_symbol(symbol)

    for cached_symbol, instrument_id in INSTRUMENT_CACHE.items():

        compare = clean_symbol(cached_symbol)

        if requested in compare or compare in requested:

            return {
                "instrument_id": instrument_id,
                "matched_name": cached_symbol,
                "requested": requested
            }

    return None

# ============================================
# WEBHOOK
# ============================================

@app.route("/webhook", methods=["POST"])
def webhook():

    try:

        data = request.json

        print("WEBHOOK RECEIVED:", data)

        # ============================
        # SECRET CHECK
        # ============================

        if data.get("secret") != WEBHOOK_SECRET:
            return jsonify({
                "error": "invalid secret"
            }), 403

        # ============================
        # INPUTS
        # ============================

        symbol = str(data.get("symbol", "")).upper()
        action = str(data.get("action", "")).lower()
        lots = float(data.get("lots", 0.01))

        sl = data.get("sl")
        tp = data.get("tp")

        # ============================
        # VALIDATION
        # ============================

        if action not in ["buy", "sell"]:
            return jsonify({
                "error": "action must be buy or sell"
            }), 400

        # ============================
        # FIND SYMBOL
        # ============================

        result = find_instrument(symbol)

        if not result:
            return jsonify({
                "error": f"symbol not found: {symbol}"
            }), 404

        instrument_id = int(result["instrument_id"])

        print("MATCHED:", result)

        # ============================
        # CONNECT
        # ============================

        tl = get_tl()

        # ============================
        # CREATE ORDER
        # ============================

        order = tl.create_order(
            instrument_id=instrument_id,
            quantity=lots,
            side=action,
            type_="market"
        )

        print("ORDER SUCCESS:", order)

        return jsonify({
            "success": True,
            "symbol": symbol,
            "matched": result["matched_name"],
            "action": action,
            "lots": lots,
            "order": str(order)
        })

    except Exception as e:

        error = traceback.format_exc()

        print("ORDER ERROR:", error)

        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": error
        }), 500

# ============================================
# TEST ROUTE
# ============================================

@app.route("/")
def home():

    return jsonify({
        "status": "online",
        "symbols_loaded": len(INSTRUMENT_CACHE)
    })

# ============================================
# STARTUP
# ============================================

try:
    load_instruments()
except Exception as e:
    print("Startup instrument preload failed:", str(e))

# ============================================
# RUN
# ============================================

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 8080))

    app.run(
        host="0.0.0.0",
        port=port
    )