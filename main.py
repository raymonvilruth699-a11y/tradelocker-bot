from flask import Flask, request, jsonify
from tradelocker import TLAPI
import os
import traceback

app = Flask(__name__)

# ENV VARIABLES
TL_EMAIL = os.getenv("TL_EMAIL")
TL_PASSWORD = os.getenv("TL_PASSWORD")
TL_SERVER = os.getenv("TL_SERVER")
TL_ENV = os.getenv("TL_ENV")
TL_ACCOUNT_ID = os.getenv("TL_ACCOUNT_ID")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

# LOGIN TO TRADELOCKER
def login():
    tl = TLAPI(
        environment=TL_ENV,
        server=TL_SERVER,
        email=TL_EMAIL,
        password=TL_PASSWORD
    )

    tl.get_all_accounts()

    if TL_ACCOUNT_ID:
        tl.set_account(TL_ACCOUNT_ID)

    return tl


@app.route("/")
def home():
    return jsonify({
        "status": "running",
        "bot": "TradeLocker Railway Bot"
    })


@app.route("/health")
def health():
    try:
        tl = login()

        return jsonify({
            "status": "login_success",
            "has_access_token": True
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@app.route("/webhook", methods=["POST"])
def webhook():

    try:
        data = request.json

        print("ALERT RECEIVED:")
        print(data)

        secret = data.get("secret")

        if secret != WEBHOOK_SECRET:
            return jsonify({
                "error": "Invalid secret"
            }), 403

        symbol = data.get("symbol")
        action = data.get("action")
        lots = float(data.get("lots", 0.01))
        sl = float(data.get("sl", 0))
        tp = float(data.get("tp", 0))

        tl = login()

        print("LOGIN SUCCESS")

        # GET ALL INSTRUMENTS
        all_instruments = tl.get_all_instruments()

        print("SEARCHING FOR SYMBOL:", symbol)

        # SEARCH MATCHES
        matches = all_instruments[
            all_instruments["name"].str.contains(symbol, case=False, na=False)
        ]

        print("MATCHING SYMBOLS:")
        print(matches[["tradableInstrumentId", "name"]])

        if matches.empty:
            return jsonify({
                "error": f"No matching instrument for {symbol}"
            }), 400

        # USE FIRST MATCH
        instrument_id = matches.iloc[0]["tradableInstrumentId"]

        print("USING INSTRUMENT ID:", instrument_id)

        # PLACE ORDER
        order = tl.create_order(
            instrument_id=instrument_id,
            quantity=lots,
            side=action,
            type_="market",
            stop_loss=sl,
            take_profit=tp
        )

        print("ORDER SUCCESS:")
        print(order)

        return jsonify({
            "status": "success",
            "symbol": symbol,
            "action": action,
            "lots": lots,
            "sl": sl,
            "tp": tp,
            "order": str(order)
        })

    except Exception as e:

        print("ORDER ERROR:")
        traceback.print_exc()

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)