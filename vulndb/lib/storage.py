import msgpack

import vulndb.lib.config as config
from vulndb.lib.utils import serialize_vuln_list


read_size = 256


def store(datas, db_file=config.vulndb_bin_file, index_file=config.vulndb_bin_index):
    """Store data in the table

    :param datas: Data list to store
    :param db_file: DB file to use
    """
    data_list = serialize_vuln_list(datas)
    index_list = [
        {
            "name": data["details"]["package"],
            "version": data["details"]["max_affected_version"],
        }
        for data in data_list
    ]
    packed_obj = msgpack.packb(data_list, use_bin_type=True)
    with open(db_file, mode="ab") as fp:
        fp.write(packed_obj)
    index_obj = msgpack.packb(index_list, use_bin_type=True)
    with open(index_file, mode="ab") as fp:
        fp.write(index_obj)
    return packed_obj


def stream_read(db_file=config.vulndb_bin_file):
    """
    """
    data_list = []
    with open(db_file, mode="rb") as fp:
        unpacker = msgpack.Unpacker(fp, read_size=read_size, use_list=1, raw=False)
        for unpacked in unpacker:
            if unpacked:
                data_list += unpacked
    return data_list


def stream_bulk_search(match_list, key_func, db_file=config.vulndb_bin_file):
    """
    """
    res = []
    with open(db_file, mode="rb") as fp:
        unpacker = msgpack.Unpacker(fp, read_size=read_size, use_list=1, raw=False)
        for unpacked in unpacker:
            if isinstance(unpacked, list):
                for data in unpacked:
                    if key_func(data) in match_list:
                        res.append(data)
            else:
                if key_func(unpacked) in match_list:
                    res.append(unpacked)
    return res
