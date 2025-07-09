from config import TELEGRAM_BOT_TOKEN as BOT_TOKEN, TELEGRAM_CHAT_ID as CHAT_ID
import requests
from datetime import datetime


def send_telegram_message(message: str):
    """
    Envoie un message formaté en Markdown via Telegram Bot API.
    """
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ Avertissement: BOT_TOKEN ou CHAT_ID manquant pour Telegram.")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }

    try:
        response = requests.post(url, json=payload)
        if response.status_code != 200:
            print(f"⚠️ Échec Telegram ({response.status_code}): {response.text}")
    except Exception as e:
        print(f"❌ Exception lors de l'envoi Telegram: {e}")


def _timestamp():
    return datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')


def notify_valid_pair(token0, token1, pair, block_number, delay, reserve0, reserve1):
    """
    🔔 Notifie la détection d'une nouvelle paire valide.
    """
    message = (
        f"🚀✨ *Nouvelle paire valide détectée sur BASE!* ✨🚀\n"
        f"🔗 *Pair:* `{pair}`\n"
        f"🪙 *Tokens:* `{token0}` ➡️ `{token1}`\n"
        f"⛓ *Bloc:* {block_number}\n"
        f"💧 *Liquidité:* {reserve0} / {reserve1}\n"
        f"⏱ *Délai de détection:* {delay}s\n"
        f"🕒 *Heure:* `{_timestamp()}`\n"
        f"🔍 [Voir sur BscScan](https://bscscan.com/address/{pair})"
    )
    send_telegram_message(message)


def notify_ignored_pair(reason, token0, token1, pair=None):
    """
    🚫 Notifie l'ignorance d'une paire pourt base base(filtrage).
    """
    message = (
        f"⚠️ *Paire ignorée* ⚠️\n"
        f"📝 *Raison:* _{reason}_\n"
        f"🪙 *Tokens:* `{token0}` / `{token1}`\n"
    )
    if pair:
        message += f"🔗 *Pair:* `{pair}`\n🔍 [Voir sur BscScan](https://bscscan.com/address/{pair})"
    send_telegram_message(message)


def notify_buy(token, amount_in_bnb, tx_hash, block_number, gas_used, gas_fees_bnb, amount_received):
    message = (
        f"🛒✨ *Achat de token réussi sur BASE !* ✨🛒\n"
        f"• *Token*         : `{token}`\n"
        f"• *Montant envoyé*: {amount_in_bnb} WETH\n"
        f"• *Montant reçu*  : {amount_received} tokens\n"
        f"• *Tx Hash*       : [Voir sur BscScan](https://bscscan.com/tx/{tx_hash})\n"
        f"• *Bloc*          : {block_number}\n"
        f"• *Gas utilisé*   : {gas_used} (≈{gas_fees_bnb:.6f} BNB)\n"
        f"• *Heure*         : `{_timestamp()}`"
    )
    send_telegram_message(message)



def notify_sell(token, received_bnb, tx_hash, profit=None):
    """
    💰 Notifie la vente de tokens et le profit sur BASE.
    """
    message = (
        f"💹🏦 *Vente exécutée!* 🏦💹\n"
        f"🪙 *Token:* `{token}`\n"
        f"💵 *Reçu:* {received_bnb} WETH\n"
        f"🔗 [Transaction BscScan](https://bscscan.com/tx/{tx_hash})"
    )
    if profit is not None:
        message += f"\n📈 *Profit estimé:* +{profit:.4f} ETH"
    message += f"\n🕒 *Heure:* `{_timestamp()}`"
    send_telegram_message(message)


def notify_summary(pnl, duration_sec, nb_trades):
    """
    📊 Envoie un résumé du cycle de sniping sur BASE.
    """
    minutes, seconds = divmod(duration_sec, 60)
    message = (
        f"🎯✅ *Résumé du Sniping* ✅🎯\n"
        f"🔁 *Trades effectués:* {nb_trades}\n"
        f"⏳ *Durée:* {int(minutes)}m {int(seconds)}s\n"
        f"💹 *PNL total:* {pnl:.4f} BNB\n"
        f"🕒 *Heure:* `{_timestamp()}`"
    )
    send_telegram_message(message)


def notify_error(error_msg):
    """
    🔥 Notifie une erreur critique sur bot BASE.
    """
    message = (
        f"❌🚨 *Erreur détectée!* 🚨❌\n"
        f"```\n{error_msg}\n```\n"
        f"🕒 *Heure:* `{_timestamp()}`"
    )
    send_telegram_message(message)
