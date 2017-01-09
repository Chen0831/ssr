#!/usr/bin/env bash
PATH=/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin:/usr/local/sbin:~/bin
# Check OS
function checkos(){
    if [ -f /etc/redhat-release ];then
        OS='CentOS'
    elif [ ! -z "`cat /etc/issue | grep bian`" ];then
        OS='Debian'
    elif [ ! -z "`cat /etc/issue | grep Ubuntu`" ];then
        OS='Ubuntu'
    else
        echo "Not support OS, Please reinstall OS and retry!"
        exit 1
    fi
}

function checkenv(){
		if [[ $OS = "centos" ]]; then
			yum install -y git
		else
			#apt-get update
			apt-get -y install git			
		fi
}

git clone https://github.com/aiastia/123.git 

cd ~/123/shadowsocks/shadowsocks

chmod 777 run.sh

./run.sh  


