#!/bin/sh

killall -2 python

echo "sleep 5 seconds......"
sleep 5
~/monitor.sh

echo ""
echo "PS PYTHON"
echo ""
ps aux | grep python

