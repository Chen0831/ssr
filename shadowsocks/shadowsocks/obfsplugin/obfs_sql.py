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

from shadowsocks import common
from shadowsocks.obfsplugin import plain
from shadowsocks.common import to_bytes, to_str, ord
from shadowsocks import lru_cache

def create_mysql_simple_obfs(method):
    return mysql_simple(method)

obfs_map = {
        'mysql_simple': (create_mysql_simple_obfs,),
        'mysql_simple_compatible': (create_mysql_simple_obfs,),
}

def match_begin(str1, str2):
    if len(str1) >= len(str2):
        if str1[:len(str2)] == str2:
            return True
    return False

class mysql_simple(plain.plain):
    def __init__(self, method):
        self.method = method
        self.raw_trans = False
        self.recv_buffer = b''
        self.send_pack_num = 0
        self.recv_pack_num = 0

    def client_encode(self, buf):
        data = struct.pack('<I', len(buf) | (self.send_pack_num << 24)) + buf
        return data

    def client_decode(self, buf):
        self.recv_buffer += buf
        ret = b''
        while len(self.recv_buffer) > 4:
            size = struct.unpack('<I', self.recv_buffer[:4])[0]
            size &= 0xffffff
            if size + 4 >= len(self.recv_buffer):
                break
            ret += self.recv_buffer[4:size + 4]
            self.recv_pack_num += 1
            self.recv_buffer = self.recv_buffer[size + 4:]
        return (ret, False)

    def server_encode(self, buf):
        if self.raw_trans:
            return buf
        data = struct.pack('<I', len(buf) | (self.send_pack_num << 24)) + buf
        self.send_pack_num += 1
        return data

    def decode_error_return(self, buf):
        self.raw_trans = True
        if self.method == 'mysql_simple':
            return (b'E', False, False)
        return (buf, True, False)

    def server_decode(self, buf):
        if self.raw_trans:
            return (buf, True, False)

        self.recv_buffer += buf
        ret = b''
        while len(self.recv_buffer) > 4:
            size = struct.unpack('<I', self.recv_buffer[:4])[0]
            if self.recv_pack_num == 0 and size > 0xffff:
                return self.decode_error_return(buf)
            size &= 0xffffff
            if size + 4 >= len(self.recv_buffer):
                break
            ret += self.recv_buffer[4:size + 4]
            self.recv_pack_num += 1
            self.send_pack_num = 0
            self.recv_buffer = self.recv_buffer[size + 4:]
        # (buffer_to_recv, is_need_decrypt, is_need_to_encode_and_send_back)
        return (ret, False, True)


