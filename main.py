from flask import Flask, request, jsonify
from tradelocker import TLAPI
import os
import traceback

app = Flask(__name__)

ENV_URL = "https://live.tradelocker.com" if os.getenv("TL_ENV") == "live" else "https://demo.tradelocker.com"

def get_tl():
    return TLAPI(
        environment=ENV_URL,
        username=os.getenv("TL_EMAIL"),
        password=os.getenv("TL_PASSWORD"),
        server=os.getenv("TL_SERVER")
    )

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "bot online", "env": ENV_URL})

@app.route("/test-login", methods=["GET"])
def test_login():
    try:
        tl = get_tl()
        instruments = tl.get_all_instruments()
        return jsonify({
            "status": "login_success",
            "instruments_loaded": True,
            "count": len(instruments) if hasattr(instruments, "__len__") else "unknown"
        })
    except Exception as e:
        print("LOGIN ERROR:", traceback.format_exc(), flush=True)
        return jsonify({"status": "login_failed", "error": str(e)}), 500

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json or {}
    print("WEBHOOK RECEIVED:", data, flush=True)

    if data.get("secret") != os.getenv("WEBHOOK_SECRET"):
        return jsonify({"error": "bad secret"}), 403

    symbol = data.get("symbol")
    action = str(data.get("action", "")).lower()
    qty = float(data.get("lots", data.get("qty", 0.01)))

    if action not in ["buy", "sell"]:
        return jsonify({"error": "action must be buy or sell"}), 400

    try:
        tl = get_tl()

        instrument_id = tl.get_instrument_id_from_symbol_name(symbol)
        print(f"Instrument found: {symbol} -> {instrument_id}", flush=True)

        order_id = tl.create_order(
            instrument_id,
            quantity=qty,
            side=action,
            type_="market"
        )

        print(f"ORDER SENT: {action.upper()} {symbol} {qty} order_id={order_id}", flush=True)

        return jsonify({
            "status": "order_sent",
            "symbol": symbol,
            "action": action,
            "lots": qty,
            "instrument_id": instrument_id,
            "order_id": order_id
        })

    except Exception as e:
        print("ORDER ERROR:", traceback.format_exc(), flush=True)
        return jsonify({
            "status": "order_failed",
            "error": str(e),
            "received": data
        }), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)