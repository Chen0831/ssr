#!/bin/bash
PATH=/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin:/usr/local/sbin
export PATH

git clone https://github.com/aiastia/123.git

cd ~/123/shadowsocks/shadowsocks

chmod 777 run.sh

./run.sh
