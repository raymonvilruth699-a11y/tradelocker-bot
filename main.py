from flask import Flask, request, jsonify
from tradelocker import TLAPI
import os
import traceback
import re

app = Flask(__name__)

# ==================================================
# ENV VARIABLES
# ==================================================

TL_EMAIL = os.getenv("TL_EMAIL")
TL_PASSWORD = os.getenv("TL_PASSWORD")
TL_SERVER = os.getenv("TL_SERVER")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

# ==================================================
# GLOBALS
# ==================================================

INSTRUMENT_CACHE = {}

# ==================================================
# HELPERS
# ==================================================

def clean_symbol(symbol):
    return re.sub(r"[^A-Z0-9]", "", str(symbol).upper())

# ==================================================
# LOGIN
# ==================================================

def get_tl():

    tl = TLAPI(
        environment="https://live.tradelocker.com",
        username=TL_EMAIL,
        password=TL_PASSWORD,
        server=TL_SERVER,
        log_level="debug"
    )

    return tl

# ==================================================
# LOAD INSTRUMENTS
# ==================================================

def load_instruments():

    global INSTRUMENT_CACHE

    print("Loading TradeLocker instruments...", flush=True)

    tl = get_tl()

    instruments = tl.get_all_instruments()

    cache = {}

    for _, row in instruments.iterrows():

        try:

            name = str(row.get("name", "")).upper()

            instrument_id = int(
                row.get("tradableInstrumentId")
            )

            cleaned = clean_symbol(name)

            cache[cleaned] = {
                "id": instrument_id,
                "name": name
            }

            simplified = (
                cleaned
                .replace(".B", "")
                .replace(".M", "")
                .replace(".R", "")
            )

            if simplified not in cache:

                cache[simplified] = {
                    "id": instrument_id,
                    "name": name
                }

        except Exception:
            pass

    INSTRUMENT_CACHE = cache

    print(
        f"Loaded {len(INSTRUMENT_CACHE)} symbols",
        flush=True
    )

# ==================================================
# FIND INSTRUMENT
# ==================================================

def find_instrument(symbol):

    requested = clean_symbol(symbol)

    # EXACT MATCH
    if requested in INSTRUMENT_CACHE:
        return INSTRUMENT_CACHE[requested]

    # PARTIAL MATCH
    for key, value in INSTRUMENT_CACHE.items():

        if requested in key or key in requested:
            return value

    raise Exception(
        f"No instrument found for {symbol}"
    )

# ==================================================
# CALCULATE SL / TP
# ==================================================

def calculate_sl_tp(
    action,
    entry_price,
    sl_distance,
    tp_distance
):

    action = action.lower()

    sl_price = None
    tp_price = None

    if sl_distance is not None:

        sl_distance = float(sl_distance)

        if action == "buy":
            sl_price = entry_price - sl_distance
        else:
            sl_price = entry_price + sl_distance

    if tp_distance is not None:

        tp_distance = float(tp_distance)

        if action == "buy":
            tp_price = entry_price + tp_distance
        else:
            tp_price = entry_price - tp_distance

    return sl_price, tp_price

# ==================================================
# HOME
# ==================================================

@app.route("/")
def home():

    return jsonify({
        "status": "online",
        "symbols_loaded": len(INSTRUMENT_CACHE)
    })

# ==================================================
# FIND SYMBOL
# ==================================================

@app.route("/find-symbol/<symbol>")
def find_symbol(symbol):

    try:

        result = find_instrument(symbol)

        return jsonify({
            "requested": symbol,
            "matched_name": result["name"],
            "instrument_id": result["id"]
        })

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 404

# ==================================================
# WEBHOOK
# ==================================================

@app.route("/webhook", methods=["POST"])
def webhook():

    try:

        data = request.json or {}

        print(
            f"WEBHOOK RECEIVED: {data}",
            flush=True
        )

        # ==========================================
        # SECRET CHECK
        # ==========================================

        if data.get("secret") != WEBHOOK_SECRET:

            return jsonify({
                "error": "Invalid secret"
            }), 403

        # ==========================================
        # INPUTS
        # ==========================================

        symbol = str(
            data.get("symbol", "")
        ).upper()

        action = str(
            data.get("action", "")
        ).lower()

        lots = float(
            data.get("lots", 0.01)
        )

        entry_price = float(
            data.get("price")
        )

        sl_distance = data.get("sl")
        tp_distance = data.get("tp")

        # ==========================================
        # VALIDATION
        # ==========================================

        if action not in ["buy", "sell"]:

            return jsonify({
                "error": "Invalid action"
            }), 400

        # ==========================================
        # FIND SYMBOL
        # ==========================================

        instrument = find_instrument(symbol)

        print(
            f"MATCHED SYMBOL: {instrument}",
            flush=True
        )

        # ==========================================
        # CALCULATE SL TP
        # ==========================================

        sl_price, tp_price = calculate_sl_tp(
            action,
            entry_price,
            sl_distance,
            tp_distance
        )

        print(
            f"ENTRY={entry_price} | "
            f"SL={sl_price} | "
            f"TP={tp_price}",
            flush=True
        )

        # ==========================================
        # LOGIN
        # ==========================================

        tl = get_tl()

        # ==========================================
        # ORDER KWARGS
        # ==========================================

        order_kwargs = {

            "instrument_id": instrument["id"],

            "quantity": lots,

            "side": action,

            "type_": "market",

            "stop_loss": sl_price,
            "stop_loss_type": "absolute",

            "take_profit": tp_price,
            "take_profit_type": "absolute"
        }

        print(
            f"ORDER KWARGS: {order_kwargs}",
            flush=True
        )
# ==========================================
# CHECK FOR OPEN POSITIONS
# ==========================================

positions = tl.get_all_positions()

same_trade_open = False
try:
    position_rows = positions.iterrows()
except Exception:
    position_rows = []

for _, pos in position_rows:

    pos_instrument_id = str(pos.get("tradableInstrumentId", ""))
    pos_side = str(pos.get("side", "")).lower()

    if (
        pos_instrument_id == str(instrument["id"])
        and pos_side == action.lower()
    ):
        same_trade_open = True
        break

# ==========================================
# BLOCK DUPLICATE TRADE
# ==========================================

if same_trade_open:

    print(
        f"SKIPPING: {symbol} {action} already open",
        flush=True
    )

    return jsonify({
        "success": False,
        "message": "Trade already open"
    })
        # ==========================================
        # CREATE ORDER
        # ==========================================

        order = tl.create_order(
            **order_kwargs
        )

        print(
            f"ORDER SUCCESS: {order}",
            flush=True
        )

        return jsonify({
            "success": True,
            "symbol": symbol,
            "matched": instrument["name"],
            "action": action,
            "lots": lots,
            "entry": entry_price,
            "sl_price": sl_price,
            "tp_price": tp_price,
            "order": str(order)
        })

    except Exception as e:

        error = traceback.format_exc()

        print(
            f"ORDER ERROR: {error}",
            flush=True
        )

        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": error
        }), 500

# ==================================================
# STARTUP
# ==================================================

try:

    load_instruments()

except Exception as e:

    print(
        f"STARTUP ERROR: {e}",
        flush=True
    )

# ==================================================
# RUN
# ==================================================

if __name__ == "__main__":

    port = int(
        os.environ.get("PORT", 8080)
    )

    app.run(
        host="0.0.0.0",
        port=port
    )