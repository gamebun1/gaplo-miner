import random
from web3 import Web3
import configparser
import json
from eth_hash.auto import keccak
from eth_abi.packed import encode_packed
import time

config = configparser.ConfigParser()
config.read('settings.ini', encoding='utf-8')

web3 = Web3(Web3.HTTPProvider(config['SERVER']['RPC']))
private_key = config['Wallet']['private_key']
wallet_address = config['Wallet']['wallet_address']
contract_address = config['Contract']['contract_address']

with open('abi.json', 'r', encoding='utf-8') as file:
    gaplo_abi = json.load(file)

contract = web3.eth.contract(address=Web3.to_checksum_address(contract_address), abi=gaplo_abi)

DEFAULT_DIFFICULTY = int("0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff", 16)
BLOCK_REWARD = 10**10  

miner_params = {
    "last_block": 0,
    "current_difficulty": DEFAULT_DIFFICULTY,
    "total_mined": 0,
    "prev_hash": 0 
}


def get_miner_params():
    """Получает параметры майнера из контракта."""
    params = contract.functions.miner_params(wallet_address).call()
    if params[1] == 0:
        params[1] = DEFAULT_DIFFICULTY
    return {
        "last_block": params[0],
        "current_difficulty": params[1],
        "total_mined": params[2],
        "prev_hash": params[3]
    }

def generate_nonce():
    """Генерирует случайный nonce для майнинга."""
    return random.getrandbits(256)

def hash_nonce(nonce, sender, difficulty, prev_hash, total_mined):
    """Вычисляет хэш используя keccak256."""
    nonce_bytes = nonce.to_bytes(32, byteorder='big')
    
    packed_data = encode_packed(
        ['address', 'bytes32', 'uint256', 'uint256', 'uint256'],
        [
            sender,
            nonce_bytes,
            difficulty,
            prev_hash,
            total_mined
        ]
    )
    
    hash_value = keccak(packed_data)
    return int.from_bytes(hash_value, byteorder='big')

def mine_block():
    """Пытается замайнить блок, находя nonce, который соответствует целевой сложности."""
    while True:
        nonce = generate_nonce()
        hash_result = hash_nonce(
            nonce,
            wallet_address,
            miner_params["current_difficulty"],
            miner_params["prev_hash"],
            miner_params["total_mined"]
        )

        if hash_result < miner_params["current_difficulty"]:
            miner_params["total_mined"] += 1
            miner_params["last_block"] = web3.eth.block_number
            miner_params["prev_hash"] = hash_result

            return nonce
        else:
            continue

def send_mine_transaction(nonce):
    """Отправляет транзакцию в контракт с замайненным nonce."""
    nonce_hex = nonce.to_bytes(32, byteorder='big')
    
    fee_data = web3.eth.fee_history(1, 'latest', [10, 20, 30])
    base_fee = fee_data['baseFeePerGas'][-1]
    priority_fees = fee_data['reward']
    average_priority_fee = sum(sum(fees) for fees in priority_fees) / len(priority_fees)
    
    max_priority_fee_per_gas = web3.to_wei(2, 'gwei')
    max_fee_per_gas = base_fee + max_priority_fee_per_gas
    
    gas_estimate = contract.functions.mine(nonce_hex).estimate_gas({
        'from': wallet_address,
        'nonce': web3.eth.get_transaction_count(wallet_address),
        'maxFeePerGas': max_fee_per_gas,
        'maxPriorityFeePerGas': max_priority_fee_per_gas
    })
    
    transaction = contract.functions.mine(nonce_hex).build_transaction({
        'chainId': 28282,
        'gas': gas_estimate+1000,
        'maxFeePerGas': max_fee_per_gas,
        'maxPriorityFeePerGas': max_priority_fee_per_gas,
        'nonce': web3.eth.get_transaction_count(wallet_address, 'pending'),
    })

    signed_tx = web3.eth.account.sign_transaction(transaction, private_key=private_key)
    tx_hash = web3.eth.send_raw_transaction(signed_tx.raw_transaction)

    return tx_hash

while True:
    miner_params = get_miner_params()
    print(f"Текущая сложность: {miner_params['current_difficulty']}")
    print(f"Всего замайнено: {miner_params['total_mined']}")

    while web3.eth.block_number - miner_params["last_block"] < 20:
        print("Слишком рано для майнинга, ждем...")
        time.sleep(5)

    
    nonce = mine_block()
    tx_hash = send_mine_transaction(nonce)
    print(f"Токен добыт и отправлен в транзакции: {tx_hash.hex()}")
    receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=1000)
    print(f"транзакция добавлена в блок: {receipt.blockNumber}")
    if receipt.status == 0:
        print("reverted")
    
    
    block_count1 = web3.eth.block_number
    block_count2 = web3.eth.block_number
    while block_count2 - block_count1 < 20:
        block_count2 = web3.eth.block_number
        time.sleep(1)
    print("--------------------------------------------------------------")
