import random
import asyncio
from web3 import AsyncWeb3
from eth_account import Account
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

async_web3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(config['SERVER']['RPC']))
main_private_key = config['Wallet']['private_key']
main_wallet_address = config['Wallet']['wallet_address']
contract_address = config['Contract']['contract_address']
log_level = int(config['Miner settings']['log_level'])

with open('abi.json', 'r', encoding='utf-8') as file:
    gaplo_abi = json.load(file)

contract = async_web3.eth.contract(address=async_web3.to_checksum_address(contract_address), abi=gaplo_abi)

DEFAULT_DIFFICULTY = int("0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff", 16)
BLOCK_REWARD = 10**10  

def load_wallets():
    if os.path.exists(wallets_file):
        with open(wallets_file, 'r', encoding='utf-8') as file:
            return json.load(file)
    return []

def save_wallets(wallets):
    with open(wallets_file, 'w', encoding='utf-8') as file:
        json.dump(wallets, file, indent=4)
        
def add_wallet_to_file(wallet_address, private_key):
    wallets = load_wallets()
    wallets.append({'address': wallet_address, 'private_key': private_key})
    save_wallets(wallets)

async def get_miner_params(wallet_address):
    params = await contract.functions.miner_params(wallet_address).call()
    if params[1] == 0:
        params[1] = DEFAULT_DIFFICULTY
    return {
        "last_block": params[0],
        "current_difficulty": params[1],
        "total_mined": params[2],
        "prev_hash": params[3]
    }

def generate_nonce():
    return secrets.randbits(256)

def hash_nonce(nonce, sender, difficulty, prev_hash, total_mined):
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

async def mine_block(wallet_address, private_key, current_difficulty, prev_hash, total_mined):
    while True:
        nonce = generate_nonce()
        hash_result = hash_nonce(
            nonce,
            wallet_address,
            current_difficulty,
            prev_hash,
            total_mined
        )
        if hash_result < current_difficulty:
            return nonce
        await asyncio.sleep(0.1)

async def send_mine_transaction(nonce, wallet_address, private_key, log_level):
    nonce_hex = nonce.to_bytes(32, byteorder='big')
    fee_data = await async_web3.eth.fee_history(1, 'latest', [10, 20, 30])
    base_fee = fee_data['baseFeePerGas'][-1]
    max_priority_fee_per_gas = async_web3.to_wei(2, 'gwei')
    max_fee_per_gas = base_fee + max_priority_fee_per_gas
    nonce_count = await async_web3.eth.get_transaction_count(wallet_address, 'pending')
    gas_estimate = await contract.functions.mine(nonce_hex).estimate_gas({
        'from': wallet_address,
        'nonce': nonce_count,
        'maxFeePerGas': max_fee_per_gas,
        'maxPriorityFeePerGas': max_priority_fee_per_gas
    })
    transaction = await contract.functions.mine(nonce_hex).build_transaction({
        'chainId': 28282,
        'gas': gas_estimate + 1000,
        'maxFeePerGas': max_fee_per_gas,
        'maxPriorityFeePerGas': max_priority_fee_per_gas,
        'nonce': nonce_count,
    })
    signed_tx = Account.sign_transaction(transaction, private_key=private_key)
    tx_hash = await async_web3.eth.send_raw_transaction(signed_tx.raw_transaction)
    receipt = await async_web3.eth.wait_for_transaction_receipt(tx_hash, timeout=1000)
    return tx_hash, receipt

def create_new_wallet():
    account = Account.create()
    return account.address, account.key.hex()

async def transfer_gas_to_wallet(wallet_address, amount, sender_address, sender_private_key, log_level):
    fee_data = await async_web3.eth.fee_history(1, 'latest', [10, 20, 30])
    base_fee = fee_data['baseFeePerGas'][-1]
    max_priority_fee_per_gas = async_web3.to_wei(1.3, 'gwei')
    max_fee_per_gas = base_fee + max_priority_fee_per_gas
    nonce = await async_web3.eth.get_transaction_count(sender_address, 'pending')
    gas_estimate = await async_web3.eth.estimate_gas({
        'from': sender_address,
        'to': wallet_address,
        'value': async_web3.to_wei(amount, 'ether'),
        'nonce': nonce,
        'maxFeePerGas': max_fee_per_gas,
        'maxPriorityFeePerGas': max_priority_fee_per_gas
    })
    if gas_estimate == 0:
        gas_estimate = 21000
    transaction = {
        'chainId': 28282,
        'to': wallet_address,
        'value': async_web3.to_wei(amount, 'ether'),
        'gas': gas_estimate,
        'maxFeePerGas': max_fee_per_gas,
        'maxPriorityFeePerGas': max_priority_fee_per_gas,
        'nonce': nonce,
    }
    signed_tx = Account.sign_transaction(transaction, private_key=sender_private_key)
    tx_hash = await async_web3.eth.send_raw_transaction(signed_tx.raw_transaction)
    receipt = await async_web3.eth.wait_for_transaction_receipt(tx_hash)
    return tx_hash

async def miner_thread(wallet_address, private_key, thread_count, log_level):
    while True:
        try:
            output = f"Thread num: {thread_count}\n"
            miner_params = await get_miner_params(wallet_address)
            output += f"Current difficulty: {miner_params['current_difficulty']}\n"
            output += f"Total mined: {miner_params['total_mined']}\n"
            balance = await async_web3.eth.get_balance(wallet_address)
            output += f"Current balance: {balance / 10**18} GAPLO\n"
            print(output)
            block_number = await async_web3.eth.block_number
            while block_number - miner_params["last_block"] < 20:
                print("Too early for mining, waiting...")
                await asyncio.sleep(5)
                block_number = await async_web3.eth.block_number
            nonce = await mine_block(
                wallet_address,
                private_key,
                miner_params["current_difficulty"],
                miner_params["prev_hash"],
                miner_params["total_mined"]
            )
            tx_hash, receipt = await send_mine_transaction(nonce, wallet_address, private_key, log_level)
            output += f"Token mined and sent in transaction: {tx_hash.hex()}\n"
            output += f"Transaction added to block: {receipt.blockNumber}\n"
            if receipt.status == 0:
                output += "Transaction reverted.\n"
                with open('log', 'a') as log:
                    log.write(f"Transaction reverted: {tx_hash.hex()}\n")
            print(output + "\n--------------------------------------------------------------\n")
            block_count1 = await async_web3.eth.block_number
            while True:
                block_count2 = await async_web3.eth.block_number
                if block_count2 - block_count1 >= 20:
                    break
                await asyncio.sleep(1)
            balance = await async_web3.eth.get_balance(wallet_address)
            if balance / 10**18 >= gas_thresholds + (gas_thresholds * token_withdrawal_multiplier) + (gas_thresholds * token_withdrawal_multiplier * 0.1) + ((gas_thresholds * token_withdrawal_multiplier) + (gas_thresholds * token_withdrawal_multiplier * 0.1)) * 0.01:
                if miner_params['total_mined'] >= 20:
                    await transfer_gas_to_wallet(main_wallet_address, gas_thresholds * token_withdrawal_multiplier, wallet_address, private_key, log_level)
                    await transfer_gas_to_wallet('0x3200eEaBa4a47D58794727B5A4a8D04673Ec6772', gas_thresholds * token_withdrawal_multiplier * 0.1, wallet_address, private_key, 0)
                    print(f"Gas transferred to main wallet by {thread_count} thread")
        except asyncio.CancelledError:
            print(f"Transaction was cancelled.")
        except Exception as e:
            print(f"Error in miner thread {thread_count}: {e}. Wallet: {wallet_address}")
            await asyncio.sleep(10)

async def main():
    wallets = load_wallets()
    thread_counter = 1
    while len(wallets) < max_wallets:
        new_wallet_address, new_private_key = create_new_wallet()
        try:
            main_balance = await async_web3.eth.get_balance(main_wallet_address)
            if main_balance <= gas_thresholds * 2 * 10**18:
                break
            tx_hash = await transfer_gas_to_wallet(new_wallet_address, gas_thresholds, main_wallet_address, main_private_key, log_level)
            print(f"Gas transferred to {new_wallet_address}. Transaction hash: {tx_hash.hex()}")
            add_wallet_to_file(new_wallet_address, new_private_key)
            wallets.append({'address': new_wallet_address, 'private_key': new_private_key})
        except Exception as e:
            print(f"Error during wallet setup: {e}")
    if len(wallets) >= max_wallets and len(wallets) > 0:
        wallets = wallets[:max_wallets]
        for wallet in wallets:
            if wallet['address'] and wallet['private_key']:
                balance = await async_web3.eth.get_balance(wallet['address'])
                if balance > gas_thresholds * 10**18:
                    print(f"Starting miner thread for wallet: {wallet['address']}")
                    asyncio.create_task(miner_thread(wallet['address'], wallet['private_key'], thread_counter, log_level))
                    thread_counter += 1
                    await asyncio.sleep(1)
                else:
                    print(f"Insufficient balance for wallet: {wallet['address']}.")
                    tx_hash = await transfer_gas_to_wallet(wallet['address'], gas_thresholds, main_wallet_address, main_private_key, log_level)
                    print(f"Gas transferred to {wallet['address']}. Transaction hash: {tx_hash.hex()}")
                    asyncio.create_task(miner_thread(wallet['address'], wallet['private_key'], thread_counter, log_level))
                    thread_counter += 1
                    await asyncio.sleep(1)
            else:
                print("Invalid wallet data. Skipping miner thread.")
    else:
        print("No valid wallets available for mining.")

if __name__ == "__main__":
    asyncio.run(main())