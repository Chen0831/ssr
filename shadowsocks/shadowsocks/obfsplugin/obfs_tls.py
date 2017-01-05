#!/usr/bin/env python
#
# Copyright 2015-2015 breakwa11
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from __future__ import absolute_import, division, print_function, \
    with_statement

import os
import sys
import hashlib
import logging
import binascii
import struct
import base64
import time
import random
import hmac
import hashlib
import string

from shadowsocks import common
from shadowsocks.obfsplugin import plain
from shadowsocks.common import to_bytes, to_str, ord
from shadowsocks import lru_cache

def create_tls_obfs(method):
    return tls_simple(method)

def create_tls_auth_obfs(method):
    return tls_auth(method)

def create_tls_ticket_auth_obfs(method):
    return tls_ticket_auth(method)

obfs_map = {
        'tls_simple': (create_tls_obfs,),
        'tls_simple_compatible': (create_tls_obfs,),
        'tls1.0_session_auth': (create_tls_auth_obfs,),
        'tls1.0_session_auth_compatible': (create_tls_auth_obfs,),
        'tls1.2_ticket_auth': (create_tls_ticket_auth_obfs,),
        'tls1.2_ticket_auth_compatible': (create_tls_ticket_auth_obfs,),
}

def match_begin(str1, str2):
    if len(str1) >= len(str2):
        if str1[:len(str2)] == str2:
            return True
    return False

class tls_simple(plain.plain):
    def __init__(self, method):
        self.method = method
        self.has_sent_header = False
        self.has_recv_header = False
        self.raw_trans_sent = False
        self.send_buffer = b''
        self.tls_version = b'\x03\x01'

    def client_encode(self, buf):
        if self.raw_trans_sent:
            return buf
        self.send_buffer += buf
        if not self.has_sent_header:
            self.has_sent_header = True
            data = self.tls_version + os.urandom(32) + binascii.unhexlify(b"000016c02bc02fc00ac009c013c01400330039002f0035000a0100006fff01000100000a00080006001700180019000b0002010000230000337400000010002900270568322d31360568322d31350568322d313402683208737064792f332e3108687474702f312e31000500050100000000000d001600140401050106010201040305030603020304020202")
            data = b"\x01\x00" + struct.pack('>H', len(data)) + data
            data = b"\x16" + self.tls_version + struct.pack('>H', len(data)) + data
            return data
        if self.has_recv_header:
            ret = self.send_buffer
            self.send_buffer = b''
            self.raw_trans_sent = True
            return ret
        return b''

    def client_decode(self, buf):
        if self.has_recv_header:
            return (buf, False)
        self.has_recv_header = True
        return (b'', True)

    def server_encode(self, buf):
        if self.has_sent_header:
            return buf
        self.has_sent_header = True
        # TODO
        data = self.tls_version + os.urandom(32)
        data = b"\x02\x00" + struct.pack('>H', len(data)) + data
        data = b"\x16" + self.tls_version + struct.pack('>H', len(data)) + data
        return data

    def decode_error_return(self, buf):
        self.has_sent_header = True
        if self.method == 'tls_simple':
            return (b'E', False, False)
        return (buf, True, False)

    def server_decode(self, buf):
        if self.has_recv_header:
            return (buf, True, False)

        self.has_recv_header = True
        if not match_begin(buf, b'\x16' + self.tls_version):
            return self.decode_error_return(buf)
        buf = buf[3:]
        if struct.unpack('>H', buf[:2])[0] != len(buf) - 2:
            return self.decode_error_return(buf)
        buf = buf[2:]
        if not match_begin(buf, b'\x01\x00'): #client hello
            return self.decode_error_return(buf)
        buf = buf[2:]
        if struct.unpack('>H', buf[:2])[0] != len(buf) - 2:
            return self.decode_error_return(buf)
        # (buffer_to_recv, is_need_decrypt, is_need_to_encode_and_send_back)
        return (b'', False, True)

class obfs_client_data(object):
    def __init__(self, cid):
        self.client_id = cid
        self.auth_code = {}

class obfs_auth_data(object):
    def __init__(self):
        self.client_data = lru_cache.LRUCache(60 * 5)
        self.client_id = os.urandom(32)
        self.startup_time = int(time.time() - 60 * 30) & 0xFFFFFFFF

class tls_auth(plain.plain):
    def __init__(self, method):
        self.method = method
        self.has_sent_header = False
        self.has_recv_header = False
        self.raw_trans_sent = False
        self.raw_trans_recv = False
        self.send_buffer = b''
        self.client_id = b''
        self.max_time_dif = 60 * 60 # time dif (second) setting
        self.tls_version = b'\x03\x01'

    def init_data(self):
        return obfs_auth_data()

    def pack_auth_data(self, client_id):
        utc_time = int(time.time()) & 0xFFFFFFFF
        data = struct.pack('>I', utc_time) + os.urandom(18)
        data += hmac.new(self.server_info.key + client_id, data, hashlib.sha1).digest()[:10]
        return data

    def client_encode(self, buf):
        if self.raw_trans_sent:
            return buf
        self.send_buffer += buf
        if not self.has_sent_header:
            self.has_sent_header = True
            data = self.tls_version + self.pack_auth_data(self.server_info.data.client_id) + b"\x20" + self.server_info.data.client_id + binascii.unhexlify(b"0016c02bc02fc00ac009c013c01400330039002f0035000a0100006fff01000100000a00080006001700180019000b0002010000230000337400000010002900270568322d31360568322d31350568322d313402683208737064792f332e3108687474702f312e31000500050100000000000d001600140401050106010201040305030603020304020202")
            data = b"\x01\x00" + struct.pack('>H', len(data)) + data
            data = b"\x16" + self.tls_version + struct.pack('>H', len(data)) + data
            return data
        if self.has_recv_header:
            data = b"\x14" + self.tls_version + "\x00\x01\x01" #ChangeCipherSpec
            data += b"\x16" + self.tls_version + "\x00\x20" + os.urandom(22) #Finished
            data += hmac.new(self.server_info.key + self.server_info.data.client_id, data, hashlib.sha1).digest()[:10]
            ret = data + self.send_buffer
            self.send_buffer = b''
            self.raw_trans_sent = True
            return ret
        return b''

    def client_decode(self, buf):
        if self.has_recv_header:
            return (buf, False)
        if len(buf) < 11 + 32 + 1 + 32:
            raise Exception('client_decode data error')
        verify = buf[11:33]
        if hmac.new(self.server_info.key + self.server_info.data.client_id, verify, hashlib.sha1).digest()[:10] != buf[33:43]:
            raise Exception('client_decode data error')
        self.has_recv_header = True
        return (b'', True)

    def server_encode(self, buf):
        if self.raw_trans_sent or self.has_sent_header:
            return buf
        self.has_sent_header = True
        data = self.tls_version + self.pack_auth_data(self.client_id) + b"\x20" + self.client_id + binascii.unhexlify(b"0016c02bc02fc00ac009c013c01400330039002f0035000a0100006fff01000100000a00080006001700180019000b0002010000230000337400000010002900270568322d31360568322d31350568322d313402683208737064792f332e3108687474702f312e31000500050100000000000d001600140401050106010201040305030603020304020202")
        data = b"\x02\x00" + struct.pack('>H', len(data)) + data #server hello
        data = b"\x16" + self.tls_version + struct.pack('>H', len(data)) + data
        data += b"\x14" + self.tls_version + "\x00\x01\x01" #ChangeCipherSpec
        data += b"\x16" + self.tls_version + "\x00\x20" + os.urandom(22) #Finished
        data += hmac.new(self.server_info.key + self.client_id, data, hashlib.sha1).digest()[:10]
        return data

    def decode_error_return(self, buf):
        self.raw_trans_sent = True
        self.raw_trans_recv = True
        if self.method == 'tls1.0_session_auth':
            return (b'E', False, False)
        return (buf, True, False)

    def server_decode(self, buf):
        if self.raw_trans_recv:
            return (buf, True, False)

        if self.has_recv_header:
            verify = buf
            verify_len = 43 - 10
            if len(buf) < 43:
                raise Exception('server_decode data error')
            if not match_begin(buf, b"\x14" + self.tls_version + "\x00\x01\x01"): #ChangeCipherSpec
                raise Exception('server_decode data error')
            buf = buf[6:]
            if not match_begin(buf, b"\x16" + self.tls_version + "\x00\x20"): #Finished
                raise Exception('server_decode data error')
            if hmac.new(self.server_info.key + self.client_id, verify[:verify_len], hashlib.sha1).digest()[:10] != verify[verify_len:verify_len+10]:
                raise Exception('server_decode data error')
            if len(buf) < 37:
                raise Exception('server_decode data error')
            buf = buf[37:]
            self.raw_trans_recv = True
            return (buf, True, False)

        self.has_recv_header = True
        ogn_buf = buf
        if not match_begin(buf, b'\x16' + self.tls_version):
            return self.decode_error_return(ogn_buf)
        buf = buf[3:]
        if struct.unpack('>H', buf[:2])[0] != len(buf) - 2:
            return self.decode_error_return(ogn_buf)
        buf = buf[2:]
        if not match_begin(buf, b'\x01\x00'): #client hello
            return self.decode_error_return(ogn_buf)
        buf = buf[2:]
        if struct.unpack('>H', buf[:2])[0] != len(buf) - 2:
            return self.decode_error_return(ogn_buf)
        buf = buf[2:]
        if not match_begin(buf, self.tls_version):
            return self.decode_error_return(ogn_buf)
        buf = buf[2:]
        verifyid = buf[:32]
        buf = buf[32:]
        sessionid_len = ord(buf[0])
        if sessionid_len < 32:
            logging.info("tls_auth wrong sessionid_len")
            return self.decode_error_return(ogn_buf)
        sessionid = buf[1:sessionid_len + 1]
        buf = buf[sessionid_len+1:]
        self.client_id = sessionid
        sha1 = hmac.new(self.server_info.key + sessionid, verifyid[:22], hashlib.sha1).digest()[:10]
        utc_time = struct.unpack('>I', verifyid[:4])[0]
        time_dif = common.int32((int(time.time()) & 0xffffffff) - utc_time)
        if time_dif < -self.max_time_dif or time_dif > self.max_time_dif \
                or common.int32(utc_time - self.server_info.data.startup_time) < -self.max_time_dif / 2:
            logging.info("tls_auth wrong time")
            return self.decode_error_return(ogn_buf)
        if sha1 != verifyid[22:]:
            logging.info("tls_auth wrong sha1")
            return self.decode_error_return(ogn_buf)
        if self.server_info.data.client_data.get(verifyid[:22]):
            logging.info("replay attack detect, id = %s" % (binascii.hexlify(verifyid)))
            return self.decode_error_return(ogn_buf)
        self.server_info.data.client_data.sweep()
        self.server_info.data.client_data[verifyid[:22]] = sessionid
        # (buffer_to_recv, is_need_decrypt, is_need_to_encode_and_send_back)
        return (b'', False, True)

class tls_ticket_auth(plain.plain):
    def __init__(self, method):
        self.method = method
        self.handshake_status = 0
        self.send_buffer = b''
        self.recv_buffer = b''
        self.client_id = b''
        self.max_time_dif = 60 * 60 # time dif (second) setting
        self.tls_version = b'\x03\x03'

    def init_data(self):
        return obfs_auth_data()

    def sni(self, url):
        url = common.to_bytes(url)
        data = b"\x00" + struct.pack('>H', len(url)) + url
        data = b"\x00\x00" + struct.pack('>H', len(data) + 2) + struct.pack('>H', len(data)) + data
        return data

    def pack_auth_data(self, client_id):
        utc_time = int(time.time()) & 0xFFFFFFFF
        data = struct.pack('>I', utc_time) + os.urandom(18)
        data += hmac.new(self.server_info.key + client_id, data, hashlib.sha1).digest()[:10]
        return data

    def client_encode(self, buf):
        if self.handshake_status == -1:
            return buf
        if self.handshake_status == 8:
            return b"\x17" + self.tls_version + struct.pack('>H', len(buf)) + buf
        self.send_buffer += b"\x17" + self.tls_version + struct.pack('>H', len(buf)) + buf
        if self.handshake_status == 0:
            self.handshake_status = 1
            data = self.tls_version + self.pack_auth_data(self.server_info.data.client_id) + b"\x20" + self.server_info.data.client_id + binascii.unhexlify(b"001cc02bc02fcca9cca8cc14cc13c00ac014c009c013009c0035002f000a" + b"0100")
            ext = binascii.unhexlify(b"ff01000100")
            host = self.server_info.obfs_param or self.server_info.host
            if host and host[-1] in string.digits:
                host = ''
            ext += self.sni(host)
            ext += b"\x00\x17\x00\x00"
            ext += b"\x00\x23\x00\xd0" + os.urandom(208) # ticket
            ext += binascii.unhexlify(b"000d001600140601060305010503040104030301030302010203")
            ext += binascii.unhexlify(b"000500050100000000")
            ext += binascii.unhexlify(b"00120000")
            ext += binascii.unhexlify(b"75500000")
            ext += binascii.unhexlify(b"000b00020100")
            ext += binascii.unhexlify(b"000a0006000400170018")
            data += struct.pack('>H', len(ext)) + ext
            data = b"\x01\x00" + struct.pack('>H', len(data)) + data
            data = b"\x16\x03\x01" + struct.pack('>H', len(data)) + data
            return data
        elif self.handshake_status == 1 and len(buf) == 0:
            data = b"\x14" + self.tls_version + "\x00\x01\x01" #ChangeCipherSpec
            data += b"\x16" + self.tls_version + "\x00\x20" + os.urandom(22) #Finished
            data += hmac.new(self.server_info.key + self.server_info.data.client_id, data, hashlib.sha1).digest()[:10]
            ret = data + self.send_buffer
            self.send_buffer = b''
            self.handshake_status = 8
            return ret
        return b''

    def client_decode(self, buf):
        if self.handshake_status == -1:
            return (buf, False)

        if self.handshake_status == 8:
            ret = b''
            self.recv_buffer += buf
            while len(self.recv_buffer) > 5:
                if ord(self.recv_buffer[0]) != 0x17:
                    logging.info("data = %s" % (binascii.hexlify(self.recv_buffer)))
                    raise Exception('server_decode appdata error')
                size = struct.unpack('>H', self.recv_buffer[3:5])[0]
                if len(self.recv_buffer) < size + 5:
                    break
                buf = self.recv_buffer[5:size+5]
                ret += buf
                self.recv_buffer = self.recv_buffer[size+5:]
            return (ret, False)

        if len(buf) < 11 + 32 + 1 + 32:
            raise Exception('client_decode data error')
        verify = buf[11:33]
        if hmac.new(self.server_info.key + self.server_info.data.client_id, verify, hashlib.sha1).digest()[:10] != buf[33:43]:
            raise Exception('client_decode data error')
        return (b'', True)

    def server_encode(self, buf):
        if self.handshake_status == -1:
            return buf
        if self.handshake_status == 8:
            ret = b''
            while len(buf) > 8192:
                ret += b"\x17" + self.tls_version + struct.pack('>H', 8192) + buf[:8192]
                buf = buf[8192:]
            if len(buf) > 0:
                ret += b"\x17" + self.tls_version + struct.pack('>H', len(buf)) + buf
            return ret
        self.handshake_status = 3
        data = self.tls_version + self.pack_auth_data(self.client_id) + b"\x20" + self.client_id + binascii.unhexlify(b"c02f000005ff01000100")
        data = b"\x02\x00" + struct.pack('>H', len(data)) + data #server hello
        data = b"\x16\x03\x03" + struct.pack('>H', len(data)) + data
        data += b"\x14" + self.tls_version + "\x00\x01\x01" #ChangeCipherSpec
        data += b"\x16" + self.tls_version + "\x00\x20" + os.urandom(22) #Finished
        data += hmac.new(self.server_info.key + self.client_id, data, hashlib.sha1).digest()[:10]
        return data

    def decode_error_return(self, buf):
        self.handshake_status = -1
        if self.method == 'tls1.2_session_auth':
            return (b'E', False, False)
        return (buf, True, False)

    def server_decode(self, buf):
        if self.handshake_status == -1:
            return (buf, True, False)

        if self.handshake_status == 8:
            ret = b''
            self.recv_buffer += buf
            while len(self.recv_buffer) > 5:
                if ord(self.recv_buffer[0]) != 0x17:
                    logging.info("data = %s" % (binascii.hexlify(self.recv_buffer)))
                    raise Exception('server_decode appdata error')
                size = struct.unpack('>H', self.recv_buffer[3:5])[0]
                if len(self.recv_buffer) < size + 5:
                    break
                ret += self.recv_buffer[5:size+5]
                self.recv_buffer = self.recv_buffer[size+5:]
            return (ret, True, False)

        if self.handshake_status == 3:
            verify = buf
            verify_len = 43 - 10
            if len(buf) < 43:
                raise Exception('server_decode data error')
            if not match_begin(buf, b"\x14" + self.tls_version + "\x00\x01\x01"): #ChangeCipherSpec
                raise Exception('server_decode data error')
            buf = buf[6:]
            if not match_begin(buf, b"\x16" + self.tls_version + "\x00\x20"): #Finished
                raise Exception('server_decode data error')
            if hmac.new(self.server_info.key + self.client_id, verify[:verify_len], hashlib.sha1).digest()[:10] != verify[verify_len:verify_len+10]:
                raise Exception('server_decode data error')
            if len(buf) < 37:
                raise Exception('server_decode data error')
            self.recv_buffer = buf[37:]
            self.handshake_status = 8
            return self.server_decode(b'')

        #raise Exception("handshake data = %s" % (binascii.hexlify(buf)))
        self.handshake_status = 2
        ogn_buf = buf
        if not match_begin(buf, b'\x16\x03\x01'):
            return self.decode_error_return(ogn_buf)
        buf = buf[3:]
        if struct.unpack('>H', buf[:2])[0] != len(buf) - 2:
            logging.info("tls_auth wrong tls head size")
            return self.decode_error_return(ogn_buf)
        buf = buf[2:]
        if not match_begin(buf, b'\x01\x00'): #client hello
            logging.info("tls_auth not client hello message")
            return self.decode_error_return(ogn_buf)
        buf = buf[2:]
        if struct.unpack('>H', buf[:2])[0] != len(buf) - 2:
            logging.info("tls_auth wrong message size")
            return self.decode_error_return(ogn_buf)
        buf = buf[2:]
        if not match_begin(buf, self.tls_version):
            logging.info("tls_auth wrong tls version")
            return self.decode_error_return(ogn_buf)
        buf = buf[2:]
        verifyid = buf[:32]
        buf = buf[32:]
        sessionid_len = ord(buf[0])
        if sessionid_len < 32:
            logging.info("tls_auth wrong sessionid_len")
            return self.decode_error_return(ogn_buf)
        sessionid = buf[1:sessionid_len + 1]
        buf = buf[sessionid_len+1:]
        self.client_id = sessionid
        sha1 = hmac.new(self.server_info.key + sessionid, verifyid[:22], hashlib.sha1).digest()[:10]
        utc_time = struct.unpack('>I', verifyid[:4])[0]
        time_dif = common.int32((int(time.time()) & 0xffffffff) - utc_time)
        if time_dif < -self.max_time_dif or time_dif > self.max_time_dif \
                or common.int32(utc_time - self.server_info.data.startup_time) < -self.max_time_dif / 2:
            logging.info("tls_auth wrong time")
            return self.decode_error_return(ogn_buf)
        if sha1 != verifyid[22:]:
            logging.info("tls_auth wrong sha1")
            return self.decode_error_return(ogn_buf)
        if self.server_info.data.client_data.get(verifyid[:22]):
            logging.info("replay attack detect, id = %s" % (binascii.hexlify(verifyid)))
            return self.decode_error_return(ogn_buf)
        self.server_info.data.client_data.sweep()
        self.server_info.data.client_data[verifyid[:22]] = sessionid
        # (buffer_to_recv, is_need_decrypt, is_need_to_encode_and_send_back)
        return (b'', False, True)

