from eth_account import Account
import configparser

config = configparser.ConfigParser()
config.read('settings.ini', encoding='utf-8')


seed_phrase=config['Wallet']['seed_phrase']

Account.enable_unaudited_hdwallet_features()
account = Account.from_mnemonic(seed_phrase)

# Получаем закрытый ключ
private_key = account._private_key.hex()
wallet_address = account.address

print(f"Ваш адрес: {wallet_address}")
print(f"Ваш закрытый ключ: {private_key}")

config['Wallet']['wallet_address'] = wallet_address
config['Wallet']['private_key'] = private_key
