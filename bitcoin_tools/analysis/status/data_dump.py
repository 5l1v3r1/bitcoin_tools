from bitcoin_tools import CFG
from bitcoin_tools.analysis.status import FEE_STEP
from bitcoin_tools.analysis.status.utils import check_multisig, get_min_input_size, roundup_rate, check_multisig_type, \
    get_serialized_size_fast, get_est_input_size, load_estimation_data, check_native_segwit
import ujson
from subprocess import call
from os import remove
from collections import OrderedDict


def transaction_dump(fin_name, fout_name):
    # Transaction dump

    # ToDo: Find an alternative way of sorting this to avoid storing redundant data when dumping the level_db
    # Sort the decoded utxo data by transaction id.
    call(["sort", CFG.data_path + fin_name, "-o", CFG.data_path + '/sorted_decoded_utxos.json'])

    # Set the input and output files
    fin = open(CFG.data_path + '/sorted_decoded_utxos.json', 'r')
    fout = open(CFG.data_path + fout_name, 'w')

    # Initial definition
    tx = dict()

    # Read the ordered file and aggregate the data by transaction.
    for line in fin:
        data = ujson.loads(line[:-1])
        utxo = data['value']

        # If the read line contains information of the same transaction we are analyzing we add it to our dictionary
        if utxo.get('tx_id') == tx.get('tx_id'):
            tx['num_utxos'] += 1
            tx['total_value'] += utxo.get('out').get('amount')
            tx['total_len'] += data['len']

        # Otherwise, we save the transaction data to the output file and start aggregating the next transaction data
        else:
            # Save previous transaction data
            if tx:
                fout.write(ujson.dumps(tx) + '\n')

            # Create the new transaction
            tx['tx_id'] = utxo.get('tx_id')
            tx['num_utxos'] = 1
            tx['total_value'] = utxo.get('out').get('amount')
            tx['total_len'] = data['len']
            tx['height'] = utxo["height"]
            tx['coinbase'] = utxo["coinbase"]

    fin.close()
    fout.close()
    remove(CFG.data_path + '/sorted_decoded_utxos.json')


def utxo_dump(fin_name, fout_name, coin, count_p2sh=False, non_std_only=False, ordered_dict=False):
    # UTXO dump

    # Input file
    fin = open(CFG.data_path + fin_name, 'r')
    # Output file
    fout = open(CFG.data_path + fout_name, 'w')

    # Standard UTXO types
    std_types = [0, 1, 2, 3, 4, 5]

    p2pkh_pksize, p2sh_scriptsize, nonstd_scriptsize, p2wsh_scriptsize = load_estimation_data(coin)

    for line in fin:
        data = ujson.loads(line[:-1])
        utxo = data['value']
        tx_id = utxo.get('tx_id')
        out = utxo.get("out")

        # Checks whether we are looking for every type of UTXO or just for non-standard ones.
        if not non_std_only or (non_std_only and out["out_type"] not in std_types and not check_multisig(out['data'])):

            # Calculates the dust threshold for every UTXO value and every fee per byte ratio between min and max.
            min_size = get_min_input_size(out, utxo["height"], count_p2sh, coin)

            # For 0.15 onwards an estimation of the length of the transaction that will include the UTXO is
            # computed.
            out_size = get_serialized_size_fast(out)
            # prev_tx_id (32 bytes) + prev_out_index (4 bytes) + scripSig_len (1 byte) + (PUSH sig + 72-byte
            # sig) (73 bytes) + (PUSH pk + compressed pk) (34 bytes) + nSequence (4 bytes)
            in_size = 32 + 4 + 1 + 73 + 34 + 4
            raw_dust = out["amount"] / float(out_size + in_size)

            raw_np = out["amount"] / float(min_size)
            raw_np_est = out["amount"] / float(get_est_input_size(out, utxo["height"], p2pkh_pksize, p2sh_scriptsize,
                                                                  nonstd_scriptsize, p2wsh_scriptsize))

            dust = roundup_rate(raw_dust, FEE_STEP)
            np = roundup_rate(raw_np, FEE_STEP)
            np_est = roundup_rate(raw_np_est, FEE_STEP)

            # Adds multisig type info
            if out["out_type"] in [0, 1, 2, 3, 4, 5]:
                non_std_type = "std"
            else:
                multisig = check_multisig_type(out["data"])
                segwit = check_native_segwit(out["data"])
                if multisig:
                    non_std_type = multisig
                elif segwit[0]:
                    non_std_type = segwit[1]
                else:
                    non_std_type = False

            # Builds the output dictionary
            if ordered_dict:
                # ToDo: Check if this could be optimized.
                # Slower, but ensures that the order of keys is preserved (useful for ordering purposes)
                result = OrderedDict()
                result["key"] = data["key"]
                result["tx_id"] = tx_id
                result["tx_height"] = utxo["height"]
                result["utxo_data_len"] = len(out["data"]) / 2
                result["dust"] = dust
                result["non_profitable"] = np
                result["non_profitable_est"] = np_est
                result["non_std_type"] = non_std_type

            else:
                result = {"tx_id": tx_id,
                          "tx_height": utxo["height"],
                          "utxo_data_len": len(out["data"]) / 2,
                          "dust": dust,
                          "non_profitable": np,
                          "non_profitable_est": np_est,
                          "non_std_type": non_std_type,
                          "index": utxo['index'],
                          "register_len": data['len']}

                # Additional data used to explain dust figures (describes the size taken into account by each metric
                # when computing dust/unprofitability). It is not used in most of the cases, and generates overhead
                # in both size and time of execution, so ity is not added by default. Uncomment if necessary.

                # result["dust_size"] = out_size + in_size
                # result["min_size"] = min_size
                # result["est_size"] = get_est_input_size(out, utxo["height"], p2pkh_pksize, p2sh_scriptsize,
                #                                         nonstd_scriptsize, p2wsh_scriptsize)}

            # Updates the dictionary with the remaining data from out, and stores it in disk.
            result.update(out)
            fout.write(ujson.dumps(result) + '\n')
    fin.close()
    fout.close()
