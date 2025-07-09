from dotenv import load_dotenv
load_dotenv()

import os
import json
import time
from decimal import Decimal
from web3 import Web3
from web3.middleware import geth_poa_middleware

from config import (
    WSS_RPC_URL,
    PRIVATE_KEY,
    WALLET_ADDRESS,
    ROUTER_ADDRESS,
    WBNB_ADDRESS,
    SLIPPAGE,
    BUY_AMOUNT,
    TIMEOUT
)
from telegram_alert import notify_buy, notify_sell, notify_summary, notify_error

# ▶️ Take-profit levels
TP1 = 50    # % pour vente partielle
TP2 = 250   # % pour vente totale
HALF_SELL = 0.5
FULL_SELL = 1.0

# ⚙️ Web3 + PoA middleware
web3 = Web3(Web3.WebsocketProvider(WSS_RPC_URL))
web3.middleware_onion.inject(geth_poa_middleware, layer=0)
if not web3.is_connected():
    notify_error("Connexion Web3 échouée dans sniper")
    exit(1)

# 📦 Chargement des ABIs depuis le même dossier que ce script
BASE_DIR = os.path.dirname(__file__)
with open(os.path.join(BASE_DIR, "router_abi.json"), "r") as f:
    ROUTER_ABI = json.load(f)
with open(os.path.join(BASE_DIR, "erc20_abi.json"), "r") as f:
    ERC20_ABI = json.load(f)

router = web3.eth.contract(
    address=Web3.to_checksum_address(ROUTER_ADDRESS),
    abi=ROUTER_ABI
)

# 🔢 Cache des décimales
decimals_cache = {}
def get_decimals(token_addr: str) -> int:
    try:
        if token_addr not in decimals_cache:
            tok = web3.eth.contract(
                address=Web3.to_checksum_address(token_addr),
                abi=ERC20_ABI
            )
            decimals_cache[token_addr] = tok.functions.decimals().call()
        return decimals_cache[token_addr]
    except Exception as e:
        notify_error(f"Erreur récupération décimales pour {token_addr}: {e}")
        return 18  # fallback safe

def buy_token(token_address: str, base: str = WBNB_ADDRESS) -> Decimal:
    """
    Achète `token_address` en partant de `base` (par défaut WBNB).
    """
    try:
        # 1) Montant en entrée (en BNB → wei)
        amt_in = int(Decimal(BUY_AMOUNT) * 10**18)
        path = [
            Web3.to_checksum_address(base),
            Web3.to_checksum_address(token_address)
        ]

        # 2) Estimation de sortie + slippage
        out = router.functions.getAmountsOut(amt_in, path).call()[-1]
        min_out = int(out * (100 - SLIPPAGE) / 100)

        # 3) Frais EIP-1559
        latest   = web3.eth.get_block('latest')
        base_fee = latest.get('baseFeePerGas', web3.to_wei(5, 'gwei'))
        tip      = web3.to_wei(2, 'gwei')
        max_fee  = base_fee * 2 + tip

        # 4) Construction TX
        tx = router.functions.swapExactETHForTokensSupportingFeeOnTransferTokens(
            min_out, path,
            Web3.to_checksum_address(WALLET_ADDRESS),
            int(time.time()) + 60
        ).build_transaction({
            'from':                Web3.to_checksum_address(WALLET_ADDRESS),
            'value':               amt_in,
            'maxFeePerGas':        max_fee,
            'maxPriorityFeePerGas': tip,
            'nonce':               web3.eth.get_transaction_count(WALLET_ADDRESS)
        })

        # 5) Estimation et ajout de marge gas
        est = web3.eth.estimate_gas(tx)
        tx['gas'] = int(est * 1.1)

        # 6) Signature & envoi
        signed = web3.eth.account.sign_transaction(tx, PRIVATE_KEY)
        txh    = web3.eth.send_raw_transaction(signed.rawTransaction)
        print(f"🟢 Achat TX envoyée: {txh.hex()}")

        # 7) Attente du receipt
        receipt = web3.eth.wait_for_transaction_receipt(txh)
        if receipt.status != 1:
            notify_error(f"Achat échoué pour {token_address}, status={receipt.status}")
            return Decimal(0)

        # 8) Analyse du receipt
        blk       = receipt.blockNumber
        gas_used  = receipt.gasUsed
        gas_price = receipt.effectiveGasPrice
        gas_spent = Decimal(gas_used) * Decimal(gas_price)
        gas_bnb   = web3.from_wei(gas_spent, 'ether')

        # 9) Récupération du solde reçu
        tok      = web3.eth.contract(address=token_address, abi=ERC20_ABI)
        raw_bal  = tok.functions.balanceOf(WALLET_ADDRESS).call()
        decs     = get_decimals(token_address)
        amt_recv = Decimal(raw_bal) / Decimal(10**decs)

        # 10) Notification détaillée
        try:
            notify_buy(
                token=token_address,
                amount_in_bnb=BUY_AMOUNT,
                tx_hash=txh.hex(),
                block_number=blk,
                gas_used=gas_used,
                gas_fees_bnb=gas_bnb,
                amount_received=amt_recv
            )
        except Exception as e:
            notify_error(f"Erreur notification achat : {e}")

        return amt_recv

    except Exception as e:
        notify_error(f"Achat échoué sur {token_address}: {e}")
        return Decimal(0)


def sell_token(token_address: str, fraction: float = 1.0, base: str = WBNB_ADDRESS) -> str:
    """
    Vend la fraction `fraction` de `token_address` contre `base`.
    """
    try:
        tok    = web3.eth.contract(address=token_address, abi=ERC20_ABI)
        bal    = tok.functions.balanceOf(WALLET_ADDRESS).call()
        amt    = int(bal * fraction)

        # 1) Approve
        ap_tx  = tok.functions.approve(ROUTER_ADDRESS, amt).build_transaction({
            'from':  Web3.to_checksum_address(WALLET_ADDRESS),
            'nonce': web3.eth.get_transaction_count(WALLET_ADDRESS)
        })
        sap    = web3.eth.account.sign_transaction(ap_tx, PRIVATE_KEY)
        tx_ap  = web3.eth.send_raw_transaction(sap.rawTransaction)
        web3.eth.wait_for_transaction_receipt(tx_ap)

        # 2) Swap back
        path   = [
            Web3.to_checksum_address(token_address),
            Web3.to_checksum_address(base)
        ]
        sw_tx  = router.functions.swapExactTokensForETHSupportingFeeOnTransferTokens(
            amt, 0, path,
            WALLET_ADDRESS,
            int(time.time()) + 60
        ).build_transaction({
            'from':  Web3.to_checksum_address(WALLET_ADDRESS),
            'nonce': web3.eth.get_transaction_count(WALLET_ADDRESS)
        })
        ssw    = web3.eth.account.sign_transaction(sw_tx, PRIVATE_KEY)
        txh    = web3.eth.send_raw_transaction(ssw.rawTransaction)
        web3.eth.wait_for_transaction_receipt(txh)

        try:
            notify_sell(token_address, fraction, txh.hex())
        except Exception:
            pass

        return txh.hex()

    except Exception as e:
        notify_error(f"Vente échouée pour {token_address}: {e}")
        return None


def monitor_and_sell(token_address: str, amount_bought: Decimal, base: str = WBNB_ADDRESS):
    """
    Surveille le PnL et vend à TP1, TP2 ou au TIMEOUT.
    """
    start      = time.time()
    sold_half  = False
    trades     = 0
    decs       = get_decimals(token_address)

    # 1) Estimation du prix initial
    try:
        init_out = router.functions.getAmountsOut(
            int(amount_bought * 10**decs),
            [token_address, base]
        ).call()[-1]
    except Exception as e:
        notify_error(f"Erreur estimation init PnL: {e}")
        return

    # 2) Boucle de surveillance
    while True:
        elapsed = time.time() - start
        try:
            cur_out = router.functions.getAmountsOut(
                int(amount_bought * 10**decs),
                [token_address, base]
            ).call()[-1]
            pnl = (Decimal(cur_out) / Decimal(init_out) - 1) * 100

            if pnl >= TP1 and not sold_half:
                sell_token(token_address, HALF_SELL, base)
                trades += 1
                sold_half = True
            elif pnl >= TP2:
                sell_token(token_address, FULL_SELL, base)
                trades += 1
                break
            elif elapsed >= TIMEOUT:
                sell_token(token_address, FULL_SELL, base)
                trades += 1
                break
        except Exception as e:
            notify_error(f"Erreur suivi PnL: {e}")
            break

        time.sleep(0.5)

    # 3) Envoi du résumé
    try:
        final_out = router.functions.getAmountsOut(
            int(amount_bought * 10**decs),
            [token_address, base]
        ).call()[-1]
        net_pnl   = (Decimal(final_out) / Decimal(init_out) - 1) * BUY_AMOUNT
        notify_summary(net_pnl, int(time.time() - start), trades)
    except Exception as e:
        notify_error(f"Erreur résumé final: {e}")
