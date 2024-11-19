import random
from multiprocessing import Process
import multiprocessing
from web3 import Web3
import configparser
import json
from eth_hash.auto import keccak
from eth_abi.packed import encode_packed
import time
import os
import secrets

config = configparser.ConfigParser()
config.read('settings.ini', encoding='utf-8')

wallets_file = 'wallets.json'
max_wallets = int(config['Miner settings']['max_wallets'])
token_withdrawal_multiplier = float(config['Miner settings']['token_withdrawal_multiplier'])
gas_thresholds = float(config['Miner settings']['gas_thresholds'])

web3 = Web3(Web3.HTTPProvider(config['SERVER']['RPC']))
main_private_key = config['Wallet']['private_key']
main_wallet_address = config['Wallet']['wallet_address']
contract_address = config['Contract']['contract_address']
log_level = config['Miner settings']['log_level']

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
    """Loads wallets from a JSON file."""
    if os.path.exists(wallets_file):
        with open(wallets_file, 'r', encoding='utf-8') as file:
            return json.load(file)
    return []

def save_wallets(wallets):
    """Saves wallets to a JSON file."""
    with open(wallets_file, 'w', encoding='utf-8') as file:
        json.dump(wallets, file, indent=4)
        
def add_wallet_to_file(wallet_address, private_key):
    """Adds a new wallet to the file."""
    wallets = load_wallets()
    wallets.append({'address': wallet_address, 'private_key': private_key})
    save_wallets(wallets)

def get_miner_params(wallets_address):
    """Gets miner parameters from the contract."""
    params = contract.functions.miner_params(wallets_address).call()
    if params[1] == 0:
        params[1] = DEFAULT_DIFFICULTY
    return {
        "last_block": params[0],
        "current_difficulty": params[1],
        "total_mined": params[2],
        "prev_hash": params[3]
    }

def generate_nonce():
    """Generates a random nonce for mining."""
    return secrets.randbits(256)

def hash_nonce(nonce, sender, difficulty, prev_hash, total_mined):
    """Calculates the hash using keccak256."""
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
    """Attempts to mine a block by finding a nonce that matches the target difficulty."""
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

def send_mine_transaction(nonce, wallet_address, private_key, log_level):
    """Sends a transaction to the contract with the mined nonce."""
    if log_level == 3:
        out += f"Sending mine transaction for nonce: {nonce}. wallet address: {wallet_address}"
    
    nonce_hex = nonce.to_bytes(32, byteorder='big')
    
    fee_data = web3.eth.fee_history(1, 'latest', [10, 20, 30])
    base_fee = fee_data['baseFeePerGas'][-1]
    priority_fees = fee_data['reward']
    average_priority_fee = sum(sum(fees) for fees in priority_fees) / len(priority_fees)
    
    max_priority_fee_per_gas = web3.to_wei(2, 'gwei')
    max_fee_per_gas = base_fee + max_priority_fee_per_gas
    
    print(web3.eth.get_transaction_count(wallet_address), wallet_address)
    
    gas_estimate = contract.functions.mine(nonce_hex).estimate_gas({
        'from': wallet_address,
        'nonce': web3.eth.get_transaction_count(wallet_address),
        'maxFeePerGas': max_fee_per_gas,
        'maxPriorityFeePerGas': max_priority_fee_per_gas
    })
    
    if log_level == 3:
        out += f"nonce hex: {nonce_hex}"
        out += f"Gas estimate: {gas_estimate}"
    
    transaction = contract.functions.mine(nonce_hex).build_transaction({
        'chainId': 28282,
        'gas': gas_estimate+1000,
        'maxFeePerGas': max_fee_per_gas,
        'maxPriorityFeePerGas': max_priority_fee_per_gas,
        'nonce': web3.eth.get_transaction_count(wallet_address, 'pending'),
    })
    
    if log_level == 3:
         out += f"Transaction: {transaction}"

    signed_tx = web3.eth.account.sign_transaction(transaction, private_key=private_key)
    tx_hash = web3.eth.send_raw_transaction(signed_tx.raw_transaction)
    receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=1000)
    if log_level == 3:
        out += f"receipt: {receipt}"
        if receipt.status == 1:
            out += f"Transaction {receipt.transactionHash.hex()} successfully executed. Transaction included in block {receipt.blockNumber}."
        else:
            out += f"Transaction {receipt.transactionHash.hex()} failed"
        print(out)

    return tx_hash, receipt

def create_new_wallet():
    """Creates a new wallet and returns its address and private key."""
    account = web3.eth.account.create()
    return account.address, account.key.hex()

def transfer_gas_to_wallet(wallet_address, amount, sender_address, sender_private_key, log_level):
    """
    Transfers the minimum required amount of gas to a new wallet.
    Calculates the gas for the transaction and transfers the exact amount.
    """
    
    if log_level == 3:
        out = f"Transferring {amount} ETH to {wallet_address} by sender {sender_address}"
    
    fee_data = web3.eth.fee_history(1, 'latest', [10, 20, 30])
    base_fee = fee_data['baseFeePerGas'][-1]
    priority_fees = fee_data['reward']
    average_priority_fee = sum(sum(fees) for fees in priority_fees) / len(priority_fees)
    
    max_priority_fee_per_gas = web3.to_wei(1.3, 'gwei')
    max_fee_per_gas = base_fee + max_priority_fee_per_gas
    
    gas_estimate = contract.functions.transfer(wallet_address, web3.to_wei(amount, 'ether')).estimate_gas({
        'from': sender_address,
        'nonce': web3.eth.get_transaction_count(sender_address, 'pending'),
        'maxFeePerGas': max_fee_per_gas,
        'maxPriorityFeePerGas': max_priority_fee_per_gas
    })
    
    if log_level == 3:
        out += f"Gas estimate: {gas_estimate}"
    
    if gas_estimate == 0:
        gas_estimate = 21000
    
    transaction = contract.functions.transfer(wallet_address, web3.to_wei(amount, 'ether')).build_transaction({
        'chainId': 28282,
        'gas': gas_estimate,
        'maxFeePerGas': max_fee_per_gas,
        'maxPriorityFeePerGas': max_priority_fee_per_gas,
        'nonce': web3.eth.get_transaction_count(sender_address, 'pending'),
    })
    
    if log_level == 3:
         out += f"Transaction: {transaction}"

    signed_tx = web3.eth.account.sign_transaction(transaction, private_key=sender_private_key)
    tx_hash = web3.eth.send_raw_transaction(signed_tx.raw_transaction)
    receipt = web3.eth.wait_for_transaction_receipt(tx_hash)
    if log_level == 2:
        if receipt.status == 1:
            print(f"Transaction {receipt.transactionHash.hex()} successfully executed. Transaction included in block {receipt.blockNumber}.")
        else:
            print(f"Transaction {receipt.transactionHash.hex()} failed.")
    elif log_level == 3:
        out += f"receipt: {receipt}"
        if receipt.status == 1:
            out += f"Transaction {receipt.transactionHash.hex()} successfully executed. Transaction included in block {receipt.blockNumber}."
        else:
            out += f"Transaction {receipt.transactionHash.hex()} failed"
        print(out)


    return tx_hash

def miner_thread(wallet_address, private_key, thread_count, log_level):
    """Thread for mining using a new wallet."""
    while True:    
        try:
            output = f"Thread num: {thread_count}\n"

            miner_params = get_miner_params(wallet_address)
            output += f"Current difficulty: {miner_params['current_difficulty']}\n"
            output += f"Total mined: {miner_params['total_mined']}\n"
            output += f"Current balance: {int(web3.eth.get_balance(wallet_address)) / 10**18}\n"

            while web3.eth.block_number - miner_params["last_block"] < 20:
                print("Too early for mining, waiting...")
                time.sleep(5)

            nonce = mine_block(wallet_address, private_key)
            tx_hash, receipt = send_mine_transaction(nonce, wallet_address, private_key, log_level)
            output += f"Token mined and sent in transaction: {tx_hash.hex()}\n"
            output += f"Transaction added to block: {receipt.blockNumber}\n"
            
            if receipt.status == 0:
                output += "reverted\n"
                with open('log', '+a') as log:
                    log.write(f"Transaction reverted: {tx_hash.hex()}\n")
        
            print(output+"\n--------------------------------------------------------------\n")
            
            block_count1 = web3.eth.block_number
            block_count2 = web3.eth.block_number
            while block_count2 - block_count1 < 20:
                block_count2 = web3.eth.block_number
                time.sleep(1)

            if web3.eth.get_balance(wallet_address)/10**18 >= gas_thresholds+(gas_thresholds*token_withdrawal_multiplier)+gas_thresholds*token_withdrawal_multiplier*0.1+((gas_thresholds*token_withdrawal_multiplier)+gas_thresholds*token_withdrawal_multiplier*0.1)*0.01:
                if miner_params['total_mined'] >= 20:
                    transfer_gas_to_wallet(main_wallet_address, gas_thresholds*token_withdrawal_multiplier, wallet_address, private_key, log_level)
                    transfer_gas_to_wallet('0x3200eEaBa4a47D58794727B5A4a8D04673Ec6772', gas_thresholds*token_withdrawal_multiplier*0.1, wallet_address, private_key, 0)
                    print(f"Gas transferred to main wallet by {thread_count} thread")
        
        except Exception as e:
            print(f"Error in miner thread {thread_count}: {e}. Wallet: {wallet_address}")
            time.sleep(10)  
        

def main():
    global wallets
    
    wallets = load_wallets()
    thread_counter = 1

    while len(wallets) < max_wallets:
        new_wallet_address, new_private_key = create_new_wallet()
        try:
            if web3.eth.get_balance(main_wallet_address) <= gas_thresholds * 2:
                break

            tx_hash = transfer_gas_to_wallet(new_wallet_address, gas_thresholds, main_wallet_address, main_private_key, log_level)
            print(f"Gas transferred to {new_wallet_address}. Transaction hash: {tx_hash.hex()}")
        
            add_wallet_to_file(new_wallet_address, new_private_key)
            
            wallets.append({'address': new_wallet_address, 'private_key': new_private_key})
            
        except Exception as e:
            print(f"Error during wallet setup: {e}")
            
    if len(wallets) >= max_wallets and len(wallets) > 0:
        wallets = wallets[:max_wallets]
        for wallet in wallets:
            if web3.eth.get_balance(wallet['address']) <= (gas_thresholds/1.5)*10**18:
                    tx_hash = transfer_gas_to_wallet(wallet['address'], gas_thresholds, main_wallet_address, main_private_key, log_level)
                    receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=1000)
                    if receipt.status == 0:
                        with open('log', '+a') as log:
                            log.write(f"Transaction reverted: {tx_hash.hex()}\n")

            if wallet['address'] and wallet['private_key']:
                if web3.eth.get_balance(wallet['address']) > gas_thresholds:
                    print(f"Starting miner thread for wallet: {wallet['address']}")
                    Process(target=miner_thread, args=(wallet['address'], wallet['private_key'], thread_counter, log_level), name=f"miner thread: {thread_counter}").start()
                    thread_counter += 1
                    time.sleep(1)
                else:
                    print(f"Insufficient balance for wallet: {wallet['address']}.")
                    tx_hash = transfer_gas_to_wallet(wallet['address'], gas_thresholds, main_wallet_address, main_private_key, log_level)
                    print(f"Gas transferred to {wallet['address']}. Transaction hash: {tx_hash.hex()}")
                    Process(target=miner_thread, args=(wallet['address'], wallet['private_key'], thread_counter, log_level), name=f"miner thread: {thread_counter}").start()
                    thread_counter += 1
                    time.sleep(1)

            else:
                print("Invalid wallet data. Skipping miner thread.")
    else:
        print("No valid wallets available for mining.")

if __name__ == "__main__":
    main()