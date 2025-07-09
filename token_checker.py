from web3 import Web3
from decimal import Decimal
from typing import Tuple, List
import time


def is_token_safe(
    web3: Web3,
    router,
    token_address: str,
    base_token: str,
    wallet: str,
    erc20_abi: List[dict],
    native_wrap: str,
    test_amount: Decimal = Decimal('0.01'),
    max_tax_percent: Decimal = Decimal('30')
) -> Tuple[bool, str]:
    """
    Vérifie si un token est sécuritaire :
    1) Swappable à l'achat
    2) Achat simulé possible
    3) Revente simulée possible
    4) Taxe raisonnable (< max_tax_percent)

    Gère BNB natif (swapExactETH...) ou base ERC20 (swapExactTokens...).
    """
    try:
        # Normalisation adresses
        token_addr = Web3.to_checksum_address(token_address)
        base_addr = Web3.to_checksum_address(base_token)
        wallet_addr = Web3.to_checksum_address(wallet)
        wrap_addr = Web3.to_checksum_address(native_wrap)

        # Contrat token & base
        token = web3.eth.contract(address=token_addr, abi=erc20_abi)
        base_contract = None
        if base_addr != wrap_addr:
            base_contract = web3.eth.contract(address=base_addr, abi=erc20_abi)

        # Montant test
        if base_addr == wrap_addr:
            buy_amount = web3.to_wei(test_amount, 'ether')
        else:
            decimals = base_contract.functions.decimals().call()
            buy_amount = int(test_amount * Decimal(10**decimals))

        buy_path = [base_addr, token_addr]
        sell_path = [token_addr, base_addr]

        # 1) Estimation getAmountsOut
        try:
            router.functions.getAmountsOut(buy_amount, buy_path).call()
        except Exception:
            return False, "Non swapable à l'achat (getAmountsOut échoué)"

        # 2) Achat simulé
        if base_addr == wrap_addr:
            try:
                router.functions.swapExactETHForTokensSupportingFeeOnTransferTokens(
                    0, buy_path, wallet_addr, int(time.time()) + 60
                ).call({'from': wallet_addr, 'value': buy_amount})
            except Exception:
                return False, "Achat simulé refusé (blacklist/honeypot)"
        else:
            try:
                base_contract.functions.approve(router.address, buy_amount).call({'from': wallet_addr})
                router.functions.swapExactTokensForTokensSupportingFeeOnTransferTokens(
                    buy_amount, 0, buy_path, wallet_addr, int(time.time()) + 60
                ).call({'from': wallet_addr})
            except Exception:
                return False, "Achat simulé refusé (honeypot ou approval)"

        # 3) Revente simulée
        balance = token.functions.balanceOf(wallet_addr).call()
        if balance == 0:
            return False, "Balance = 0 après achat simulé"

        if base_addr == wrap_addr:
            try:
                token.functions.approve(router.address, balance).call({'from': wallet_addr})
                router.functions.swapExactTokensForETHSupportingFeeOnTransferTokens(
                    balance, 0, sell_path, wallet_addr, int(time.time()) + 60
                ).call({'from': wallet_addr})
            except Exception:
                return False, "Revente simulée refusée (honeypot)"
        else:
            try:
                token.functions.approve(router.address, balance).call({'from': wallet_addr})
                router.functions.swapExactTokensForTokensSupportingFeeOnTransferTokens(
                    balance, 0, sell_path, wallet_addr, int(time.time()) + 60
                ).call({'from': wallet_addr})
            except Exception:
                return False, "Revente simulée refusée (honeypot)"

        # 4) Vérification taxe
        out_est = router.functions.getAmountsOut(buy_amount, buy_path).call()[-1]
        back_est = router.functions.getAmountsOut(out_est, sell_path).call()[-1]
        loss_pct = (Decimal(buy_amount) - Decimal(back_est)) / Decimal(buy_amount) * 100
        if loss_pct > max_tax_percent:
            return False, f"Taxe suspecte >{max_tax_percent}% ({loss_pct:.1f}%)"

        return True, "Token sûr ✅"

    except Exception as e:
        return False, f"Erreur vérif token : {e}"
