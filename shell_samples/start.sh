#!/bin/sh

market="futuus-sun"
strategy="shannon"


cd  ~/
if [ ! -d "sunquant/${market}" ]; then
        mkdir ~/sunquant
        mkdir ~/sunquant/${market}
fi

python /home/sunquant-master/tradeengine/trade_engine_futu.py -m ${market} -s ${strategy} 1>>~/sunquant/${market}/console.log 2>>~/sunquant/${market}/console.log &

echo "sleep 2 seconds......"
sleep 2
~/monitor.sh

echo ""
ps aux | grep python
