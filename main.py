import os
import re
import traceback
from flask import Flask, request, jsonify
from tradelocker import TLAPI

app = Flask(__name__)

TL_EMAIL = os.getenv("TL_EMAIL")
TL_PASSWORD = os.getenv("TL_PASSWORD")
TL_SERVER = os.getenv("TL_SERVER")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

INSTRUMENT_CACHE = {}

ACCOUNT_ID = 747681
ACC_NUM = 2


def clean_symbol(symbol):
    return re.sub(r"[^A-Z0-9]", "", str(symbol).upper())


def get_tl():
    tl = TLAPI(
        environment="https://live.tradelocker.com",
        username=TL_EMAIL,
        password=TL_PASSWORD,
        server=TL_SERVER,
        log_level="debug"
    )

    try:
        tl.set_account_id_and_acc_num(ACCOUNT_ID, ACC_NUM)
        print(f"FORCED ACCOUNT: {ACCOUNT_ID} / {ACC_NUM}", flush=True)
    except Exception as e:
        print("ACCOUNT FORCE WARNING:", str(e), flush=True)

    return tl


def load_instruments():
    global INSTRUMENT_CACHE

    print("Loading TradeLocker instruments...", flush=True)

    tl = get_tl()
    instruments = tl.get_all_instruments()

    cache = {}

    for _, row in instruments.iterrows():
        name = str(row.get("name", ""))
        instrument_id = row.get("tradableInstrumentId")

        if not name or not instrument_id:
            continue

        cleaned = clean_symbol(name)

        cache[cleaned] = {
            "id": int(instrument_id),
            "name": name
        }

        simplified = (
            cleaned
            .replace("B", "")
            .replace("R", "")
            .replace("M", "")
        )

        if simplified not in cache:
            cache[simplified] = {
                "id": int(instrument_id),
                "name": name
            }

    INSTRUMENT_CACHE = cache

    print(f"Loaded {len(INSTRUMENT_CACHE)} symbols", flush=True)


def find_instrument(symbol):
    if not INSTRUMENT_CACHE:
        load_instruments()

    cleaned = clean_symbol(symbol)

    if cleaned in INSTRUMENT_CACHE:
        return INSTRUMENT_CACHE[cleaned]

    for key, value in INSTRUMENT_CACHE.items():
        if cleaned in key or key in cleaned:
            return value

    raise Exception(f"No instrument found for {symbol}")


def get_current_price(tl, instrument_id):
    """
    Tries to get bid/ask/last price from TradeLocker.
    If wrapper response format differs, logs full error.
    """

    try:
        quote = tl.get_quotes([instrument_id])
        print("QUOTE RESPONSE:", quote, flush=True)

        if isinstance(quote, dict):
            q = list(quote.values())[0] if quote else {}
        else:
            q = quote.iloc[0].to_dict()

        bid = q.get("bid") or q.get("bidPrice")
        ask = q.get("ask") or q.get("askPrice")
        last = q.get("last") or q.get("price") or q.get("lastPrice")

        if bid and ask:
            return (float(bid) + float(ask)) / 2

        if last:
            return float(last)

    except Exception as e:
        print("QUOTE ERROR:", str(e), flush=True)

    return None


def calculate_sl_tp(action, entry_price, sl_distance, tp_distance):
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


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "online",
        "symbols_loaded": len(INSTRUMENT_CACHE),
        "account_id": ACCOUNT_ID,
        "acc_num": ACC_NUM
    })


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
        return jsonify({"status": "failed", "error": str(e)}), 500


@app.route("/find-symbol/<symbol>", methods=["GET"])
def find_symbol(symbol):
    try:
        match = find_instrument(symbol)
        return jsonify({
            "requested": symbol,
            "matched_symbol": match["name"],
            "instrument_id": match["id"]
        })
    except Exception as e:
        return jsonify({"status": "not_found", "error": str(e)}), 404


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json or {}
    print("WEBHOOK RECEIVED:", data, flush=True)

    if data.get("secret") != WEBHOOK_SECRET:
        return jsonify({"error": "bad secret"}), 403

    symbol = data.get("symbol")
    action = str(data.get("action", "")).lower()
    lots = float(data.get("lots", data.get("qty", 0.01)))

    sl_distance = data.get("sl")
    tp_distance = data.get("tp")
    alert_price = data.get("price")

    if action not in ["buy", "sell"]:
        return jsonify({"error": "action must be buy or sell"}), 400

    try:
        tl = get_tl()
        match = find_instrument(symbol)
        instrument_id = match["id"]

        print(
            f"ORDER REQUEST | {symbol} -> {match['name']} | ID={instrument_id} | {action} | lots={lots}",
            flush=True
        )

        entry_price = None

        if alert_price not in [None, "", "null"]:
            try:
                entry_price = float(alert_price)
            except Exception:
                entry_price = None

        if entry_price is None:
            entry_price = get_current_price(tl, instrument_id)

        sl_price = None
        tp_price = None

        if entry_price is not None:
            sl_price, tp_price = calculate_sl_tp(
                action,
                entry_price,
                sl_distance,
                tp_distance
            )

        print(
            f"ENTRY={entry_price} | SL={sl_price} | TP={tp_price}",
            flush=True
        )

        order_kwargs = {
            "instrument_id": instrument_id,
            "quantity": lots,
            "side": action,
            "type_": "market"
        }

        if sl_price is not None:
            order_kwargs["stop_loss"] = sl_price

        if tp_price is not None:
            order_kwargs["take_profit"] = tp_price

        try:
            order = tl.create_order(**order_kwargs)
        except TypeError:
            print("SL/TP not accepted by wrapper. Sending market order only.", flush=True)
            order = tl.create_order(
                instrument_id=instrument_id,
                quantity=lots,
                side=action,
                type_="market"
            )

        print("ORDER SENT:", order, flush=True)

        return jsonify({
            "status": "success",
            "requested_symbol": symbol,
            "matched_symbol": match["name"],
            "instrument_id": instrument_id,
            "action": action,
            "lots": lots,
            "entry_price": entry_price,
            "sl_price": sl_price,
            "tp_price": tp_price,
            "order": str(order)
        })

    except Exception as e:
        print("ORDER ERROR:", traceback.format_exc(), flush=True)

        return jsonify({
            "status": "failed",
            "error": str(e),
            "received": data
        }), 500


try:
    load_instruments()
except Exception as e:
    print("Startup preload failed:", str(e), flush=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)