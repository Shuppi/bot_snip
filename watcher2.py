import os
import json
import time
import requests
from web3 import Web3
from web3.middleware import geth_poa_middleware

from telegram_alert import notify_valid_pair, notify_ignored_pair, notify_error
from config import (
    WSS_RPC_URL,
    HTTP_RPC_URL,
    FACTORY_ADDRESS,
    ROUTER_ADDRESS,
    BASE_TOKENS,
    MIN_LIQUIDITY,
    BSCSCAN_API_KEY,
    WALLET_ADDRESS,
    WBNB_ADDRESS
)
from token_checker import is_token_safe

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def connect_web3(max_attempts: int = 3, delay: int = 5) -> Web3:
    """
    Tente de se connecter au noeud WebSocket, puis HTTP en cas d'échec,
    jusqu'à max_attempts fois, avec délai entre chaque tentative.
    """
    for attempt in range(1, max_attempts + 1):
        for provider_url in (WSS_RPC_URL, HTTP_RPC_URL):
            try:
                print(f"🔌 Connexion Web3 via {provider_url} (tentative {attempt}/{max_attempts})…")
                w3 = Web3(Web3.WebsocketProvider(provider_url)) if provider_url.startswith('ws') else Web3(Web3.HTTPProvider(provider_url))
                if geth_poa_middleware not in w3.middleware_onion:
                    w3.middleware_onion.inject(geth_poa_middleware, layer=0)
                if w3.is_connected():
                    print(f"✅ Web3 connecté via {provider_url}")
                    return w3
            except Exception as e:
                print(f"❌ Erreur connexion {provider_url}: {e}")
        time.sleep(delay)
    notify_error("❌ Échec de connexion RPC après plusieurs tentatives")
    return None


def is_verified_contract(address: str) -> bool:
    """
    Vérifie via l'API BscScan si le contrat est vérifié (SourceCode non vide).
    """
    try:
        url = (
            f"https://api.bscscan.com/api?module=contract&action=getsourcecode"
            f"&address={address}&apikey={BSCSCAN_API_KEY}"
        )
        resp = requests.get(url, timeout=5).json()
        code = resp.get('result', [{}])[0].get('SourceCode', '')
        return bool(code)
    except Exception:
        return False


def watch_for_pairs():
    """
    Générateur détectant PairCreated pour n'importe quelle base de BASE_TOKENS,
    filtre :
      • base ∈ BASE_TOKENS
      • contrat vérifié
      • liquidité ≥ MIN_LIQUIDITY (OR)
      • honeypot-check via is_token_safe()
    Yield dict(token, base, pair).
    """
    w3 = connect_web3()
    if not w3:
        return

    # 1) Charger les ABIs
    try:
        factory_abi = json.load(open(os.path.join(BASE_DIR, "factory_abi.json")))
        pair_abi    = json.load(open(os.path.join(BASE_DIR, "pair_abi.json")))
        router_abi  = json.load(open(os.path.join(BASE_DIR, "router_abi.json")))
    except Exception as e:
        notify_error(f"❌ Erreur chargement ABIs: {e}")
        return

    # 2) Instancier factory & router
    factory = w3.eth.contract(
        address=Web3.to_checksum_address(FACTORY_ADDRESS),
        abi=factory_abi
    )
    router = w3.eth.contract(
        address=Web3.to_checksum_address(ROUTER_ADDRESS),
        abi=router_abi
    )

    # 3) Event PairCreated
    event_abi = next(
        (ev for ev in factory_abi if ev.get("type") == "event" and ev.get("name") == "PairCreated"),
        None
    )
    if not event_abi:
        notify_error("❌ ABI PairCreated introuvable dans factory_abi.json")
        return
    topic = w3.keccak(text="PairCreated(address,address,address,uint256)").hex()

    last_block = w3.eth.block_number
    seen = set()
    print(f"📡 Surveillance PairCreated démarrée au bloc {last_block}")

    while True:
        current = w3.eth.block_number
        if current <= last_block:
            time.sleep(0.5)
            continue

        # 4) Récupérer les logs PairCreated
        try:
            logs = w3.eth.get_logs({
                "fromBlock": last_block + 1,
                "toBlock":   current,
                "address":   Web3.to_checksum_address(FACTORY_ADDRESS),
                "topics":    [topic]
            })
        except Exception as e:
            notify_error(f"❌ get_logs PairCreated failed: {e}")
            time.sleep(1)
            continue

        print(f"🔍 {len(logs)} nouveaux PairCreated ({last_block+1}→{current})")
        for log in logs:
            try:
                evt = w3.codec.decode_log(event_abi, log["data"], log["topics"])
                t0, t1 = Web3.to_checksum_address(evt['args']['token0']), Web3.to_checksum_address(evt['args']['token1'])
                pair   = evt['args']['pair']
                blk    = log['blockNumber']

                # 5) Filtrer sur bases configurées
                if not (t0 in BASE_TOKENS or t1 in BASE_TOKENS):
                    continue
                base  = t0 if t0 in BASE_TOKENS else t1
                token = t1 if t0 in BASE_TOKENS else t0

                # 6) Un seul passage par pair
                if pair in seen:
                    continue
                seen.add(pair)

                # 7) Vérif liquidity minimale (OR)
                r0, r1, _ = w3.eth.contract(address=pair, abi=pair_abi).functions.getReserves().call()
                if r0 < MIN_LIQUIDITY or r1 < MIN_LIQUIDITY:
                    notify_ignored_pair("Liquidité insuffisante", token, base, pair)
                    continue

                # 8) Contrat vérifié sur BscScan
                if not is_verified_contract(token):
                    notify_ignored_pair("Contrat non vérifié", token, base, pair)
                    continue

                # 9) Honeypot / taxe
                safe, reason = is_token_safe(
                    web3=w3,
                    router=router,
                    token_address=token,
                    base_token=base,
                    wallet=WALLET_ADDRESS,
                    erc20_abi=pair_abi,
                    native_wrap=WBNB_ADDRESS
                )
                if not safe:
                    notify_ignored_pair(f"Honeypot/taxe fail: {reason}", token, base, pair)
                    continue

                # 10) OK → notifie + yield
                delay = int(time.time()) - w3.eth.get_block(blk).timestamp
                notify_valid_pair(token, base, pair, blk, delay, r0, r1)
                yield {"token": token, "base": base, "pair": pair}

            except Exception as e:
                notify_error(f"⚠️ Erreur processing log: {e}")

        last_block = current
        time.sleep(0.5)
