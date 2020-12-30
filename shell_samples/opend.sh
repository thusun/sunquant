#!/bin/sh

#crontab -e
#20 12 * * * ~/opend.sh

killall -9 FutuOpenD

sleep 5

cd ~/FutuOpenD_2.6.600_Centos7

nohup ./FutuOpenD -console=0 1>>opend.log 2>>opend.log

