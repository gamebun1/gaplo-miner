from web3 import Web3
import json

RPC_url = 'https://pub1.aplocoin.com'
web3 = Web3(Web3.HTTPProvider(RPC_url))

if not web3.is_connected():
    print("Ошибка: Не удалось подключиться к сети Ethereum.")
    exit()

tx_hash = "3097b8a76bc97d783676990a26e6097c98c9d08711705fb580f2dad3ec71555c"


tx_receipt = web3.eth.get_transaction_receipt(tx_hash)

if tx_receipt is None:
    print("Транзакция не найдена или еще не включена в блок.")
    exit()

if tx_receipt['status'] == 0:
    print("Транзакция была откачена.")

    logs = tx_receipt['logs']

    if logs:
        print("Логи транзакции:")

        with open('abi.json', 'r') as f:
            contract_abi = json.load(f)

        contract = web3.eth.contract(address=tx_receipt['to'], abi=contract_abi)

        for log in logs:
            event_signature = log['topics'][0]
            event_abi = next(filter(lambda e: e['type'] == 'event' and web3.keccak(text=e['name'] + '(' + ','.join(i['type'] for i in e['inputs']) + ')') == event_signature, contract_abi))
            event_data = contract.events[event_abi['name']]().process_log(log)

            print(f"Событие: {event_abi['name']}")
            for input in event_abi['inputs']:
                print(f"{input['name']}: {event_data['args'][input['name']]}")
    else:
        print("Логи транзакции отсутствуют.")
else:
    print("Транзакция была успешно выполнена.")