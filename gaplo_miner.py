import random
from multiprocessing import Process
from web3 import Web3
import configparser
import json
from eth_hash.auto import keccak
from eth_abi.packed import encode_packed
import time
import os

config = configparser.ConfigParser()
config.read('settings.ini', encoding='utf-8')

wallets_file = 'wallets.json'
max_wallets = int(config['Miner settings']['max_wallets'])

gas_thresholds = float(config['Miner settings']['gas_thresholds'])

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

def load_wallets():
    """Загружает кошельки из JSON-файла."""
    if os.path.exists(wallets_file):
        with open(wallets_file, 'r', encoding='utf-8') as file:
            return json.load(file)
    return []

def save_wallets(wallets):
    """Сохраняет кошельки в JSON-файл."""
    with open(wallets_file, 'w', encoding='utf-8') as file:
        json.dump(wallets, file, indent=4)
        
def add_wallet_to_file(wallet_address, private_key):
    """Добавляет новый кошелек в файл."""
    wallets = load_wallets()
    wallets.append({'address': wallet_address, 'private_key': private_key})
    save_wallets(wallets)

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

def mine_block(wallet_address, private_key):
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

def send_mine_transaction(nonce, wallet_address, private_key):
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
        'gas': gas_estimate,
        'maxFeePerGas': max_fee_per_gas,
        'maxPriorityFeePerGas': max_priority_fee_per_gas,
        'nonce': web3.eth.get_transaction_count(wallet_address, 'pending'),
    })

    signed_tx = web3.eth.account.sign_transaction(transaction, private_key=private_key)
    tx_hash = web3.eth.send_raw_transaction(signed_tx.raw_transaction)

    return tx_hash

def create_new_wallet():
    """Создает новый кошелек и возвращает его адрес и приватный ключ."""
    account = web3.eth.account.create()
    return account.address, account.key.hex()

def transfer_gas_to_new_wallet(new_wallet_address, amount):
    """
    Переводит минимально необходимое количество газа на новый кошелек.
    Рассчитывает газ для транзакции и передает точное количество.
    """
    
    fee_data = web3.eth.fee_history(1, 'latest', [10, 20, 30])
    base_fee = fee_data['baseFeePerGas'][-1]
    priority_fees = fee_data['reward']
    average_priority_fee = sum(sum(fees) for fees in priority_fees) / len(priority_fees)
    
    max_priority_fee_per_gas = web3.to_wei(1.3, 'gwei')
    max_fee_per_gas = base_fee + max_priority_fee_per_gas
    
    gas_estimate = contract.functions.transfer(new_wallet_address, web3.to_wei(amount, 'ether')).estimate_gas({
        'from': wallet_address,
        'nonce': web3.eth.get_transaction_count(wallet_address),
        'maxFeePerGas': max_fee_per_gas,
        'maxPriorityFeePerGas': max_priority_fee_per_gas
    })
    
    if gas_estimate == 0:
        gas_estimate = 21000
    
    transaction = contract.functions.transfer(new_wallet_address, web3.to_wei(amount, 'ether')).build_transaction({
        'chainId': 28282,
        'gas': gas_estimate,
        'maxFeePerGas': max_fee_per_gas,
        'maxPriorityFeePerGas': max_priority_fee_per_gas,
        'nonce': web3.eth.get_transaction_count(wallet_address),
    })

    signed_tx = web3.eth.account.sign_transaction(transaction, private_key=private_key)
    tx_hash = web3.eth.send_raw_transaction(signed_tx.raw_transaction)
    receipt = web3.eth.wait_for_transaction_receipt(tx_hash)
    print(f"Транзакция {receipt.transactionHash.hex()} успешно выполнена. Транзакция попала в блок {receipt.blockNumber}.")



    return tx_hash

def miner_thread(wallet_address, private_key):
    """Поток для майнинга с использованием нового кошелька."""
    while True:
        miner_params = get_miner_params()
        
        nonce = mine_block(wallet_address, private_key)
        tx_hash = send_mine_transaction(nonce, wallet_address, private_key)
        print(f"Токен добыт и отправлен в транзакции: {tx_hash.hex()}")
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=1000)
        print(f"транзакция добавлена в блок: {receipt.blockNumber}")
        
        block_count1 = web3.eth.block_number
        block_count2 = web3.eth.block_number
        while block_count2 - block_count1 < 20:
            block_count2 = web3.eth.block_number
            time.sleep(1)

def main():
    global wallets
    
    wallets = load_wallets()

    while len(wallets) < max_wallets:
        new_wallet_address, new_private_key = create_new_wallet()
        try:
            tx_hash = transfer_gas_to_new_wallet(new_wallet_address, gas_thresholds)
            print(f"Gas transferred to {new_wallet_address}. Transaction hash: {tx_hash.hex()}")
        
            add_wallet_to_file(new_wallet_address, new_private_key)
            
            wallets.append({'address': new_wallet_address, 'private_key': new_private_key})
            
            Process(target=miner_thread, args=(new_wallet_address, new_private_key)).start()
        except Exception as e:
            print(f"Error during wallet setup: {e}")
            
    if 0 < len(wallets) <= max_wallets:
        for wallet in wallets:
            if wallet['address'] and wallet['private_key']:
                if web3.eth.get_balance(wallet['address']) > gas_thresholds:
                    print(f"Starting miner thread for wallet: {wallet['address']}")
                    Process(target=miner_thread, args=(wallet['address'], wallet['private_key'])).start()
                else:
                    print(f"Insufficient balance for wallet: {wallet['address']}.")
                    tx_hash = transfer_gas_to_new_wallet(wallet['address'], gas_thresholds)
                    print(f"Gas transferred to {wallet['address']}. Transaction hash: {tx_hash.hex()}")
                    Process(target=miner_thread, args=(wallet['address'], wallet['private_key'])).start()
            else:
                print("Invalid wallet data. Skipping miner thread.")
    else:
        print("No valid wallets available for mining.")



if __name__ == "__main__":
    main()