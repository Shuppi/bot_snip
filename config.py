import os
from dotenv import load_dotenv
from web3 import Web3

load_dotenv()

# --- RPC endpoints ---
WSS_RPC_URL  = os.getenv("WSS_RPC_URL")
HTTP_RPC_URL = os.getenv("HTTP_RPC_URL")

# --- Keys & addresses ---
PRIVATE_KEY     = os.getenv("PRIVATE_KEY")
WALLET_ADDRESS  = Web3.to_checksum_address(os.getenv("WALLET_ADDRESS"))

FACTORY_ADDRESS = Web3.to_checksum_address(os.getenv("FACTORY_ADDRESS"))
ROUTER_ADDRESS  = Web3.to_checksum_address(os.getenv("ROUTER_ADDRESS"))
BSCSCAN_API_KEY   = os.getenv("BSCSCAN_API_KEY")

# --- Sniper settings ---
SLIPPAGE      = int(os.getenv("SLIPPAGE", "10"))
BUY_AMOUNT    = float(os.getenv("BUY_AMOUNT", "0.01"))
MIN_LIQUIDITY = int(os.getenv("MIN_LIQUIDITY", str(1 * 10**18)))
TIMEOUT       = int(os.getenv("TIMEOUT", "40"))

# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")

# --- Base tokens (splittés par virgule) ---
BASE_TOKENS = [
    Web3.to_checksum_address(addr)
    for addr in os.getenv("BASE_TOKENS", "").split(",")
    if addr
]
