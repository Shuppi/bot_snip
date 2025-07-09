from dotenv import load_dotenv
load_dotenv()

import json
import os
import time
from web3 import Web3
from web3.middleware import geth_poa_middleware

from token_checker import is_token_safe
from config import (
    WSS_RPC_URL,
    FACTORY_ADDRESS,
    ROUTER_ADDRESS,
    SLIPPAGE,
    BUY_AMOUNT,
    TIMEOUT,
    MIN_LIQUIDITY,
    WALLET_ADDRESS
)
from achat import buy_token, monitor_and_sell
from telegram_alert import send_telegram_message, notify_error
from watcher2 import watch_for_pairs, connect_web3

# === Chargement des ABIs depuis le même dossier que ce script ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def load_abi(name: str):
    path = os.path.join(BASE_DIR, f"{name}.json")
    with open(path, "r") as f:
        return json.load(f)

ERC20_ABI  = load_abi("erc20_abi")
ROUTER_ABI = load_abi("router_abi")

# --- Script principal ---
def main():
    # 1) Connexion Web3 avec reconnexions
    w3 = connect_web3()
    if not w3:
        notify_error("Web3 non connecté après plusieurs tentatives sur bot BASE")
        return

    # 2) Injection sécurisée du middleware POA (pour BSC, etc.)
    if geth_poa_middleware not in w3.middleware_onion:
        w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    assert w3.is_connected(), "Web3 non connecté"

    # 3) Préparer le contrat router
    router = w3.eth.contract(
        address=Web3.to_checksum_address(ROUTER_ADDRESS),
        abi=ROUTER_ABI
    )

    # 4) Construire le message de démarrage
    params = {
        "RPC URL":        WSS_RPC_URL,
        "Factory":        FACTORY_ADDRESS,
        "Router":         ROUTER_ADDRESS,
        "Slippage":       f"{SLIPPAGE}%",
        "Buy Amount":     f"{BUY_AMOUNT} BNB",
        "Min Liquidity":  f"{int(MIN_LIQUIDITY / 1e18)} BNB",
        "Timeout":        f"{TIMEOUT}s"
    }
    lines = ["🤖 *Sniper BSC Bot démarré!*", "*Paramètres de la session :*"]
    for k, v in params.items():
        lines.append(f"• *{k}* : `{v}`")

    # 5) Ajouter le solde du wallet
    try:
        balance_wei = w3.eth.get_balance(WALLET_ADDRESS)
        balance_bnb = Web3.from_wei(balance_wei, 'ether')
        lines.append(f"• *Solde Wallet* : `{balance_bnb} ETH` 📊")
    except Exception as e:
        lines.append(f"⚠️ Impossible de lire le solde pour BASE: {e}")

    startup_msg = "\n".join(lines)

    # 6) Envoi Telegram + affichage console
    try:
        send_telegram_message(startup_msg)
    except Exception as e:
        print(f"⚠️ Erreur envoi Telegram : {e}")
    print("\n" + startup_msg.replace("*", "").replace("`", ""))

    # 7) Boucle principale : détection → achat → vente
    is_sniping = False
    try:
        for info in watch_for_pairs():
            if is_sniping:
                print("⏳ Sniping en cours, nouvel événement ignoré pour base ")
                continue

            token = info["token"]
            base  = info["base"]
            pair  = info["pair"]
            print(f"📝 Nouvelle paire détectée → Token: {token} | Base: {base} | Pair: {pair}")

            # 7.1) Anti-scam
            safe, reason = is_token_safe(
                w3, router, token, base, WALLET_ADDRESS, ERC20_ABI
            )
            if not safe:
                notify_error(f"Token bloqué pour base : {reason}")
                continue

            # 7.2) Lancement du sniping
            is_sniping = True
            amount = buy_token(token, base)
            if amount > 0:
                monitor_and_sell(token, base, amount)
            is_sniping = False

    except Exception as e:
        notify_error(str(e))


if __name__ == "__main__":
    main()
