from eth_account import Account
import configparser

config = configparser.ConfigParser()
config.read('settings.ini', encoding='utf-8')


seed_phrase='pool gather divide mistake dial because tragic travel among name cricket bamboo'

Account.enable_unaudited_hdwallet_features()
account = Account.from_mnemonic(seed_phrase)

# Получаем закрытый ключ
private_key = account._private_key.hex()
wallet_address = account.address

print(f"Ваш адрес: {wallet_address}")
print(f"Ваш закрытый ключ: {private_key}")
