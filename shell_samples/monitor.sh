#!/bin/sh

market="futuus-sun"
strategy="shannon"

echo ""
echo "Success"
echo ""
grep Success sunquant/${market}/${strategy}.log

echo ""
echo "WARN"
echo ""
grep WARN sunquant/${market}/${strategy}.log

echo ""
echo "ERROR"
echo ""
grep ERROR sunquant/${market}/${strategy}.log

echo ""
echo "Exception"
echo ""
grep "Exception" sunquant/${market}/${strategy}.log

echo ""
echo "Success Sum"
echo ""
#grep Success sunquant/${market}/${strategy}.log | awk -F '  |-:|=|e_' '{print $1," ",$4," ",$6," ",$9,"@",$7}'
grep Success sunquant/${market}/${strategy}.log | awk -F '  |-:|=' '{print $4}' | sort | uniq -c
grep Success sunquant/${market}/${strategy}.log | awk -F ' ' '{print $1}' | sort | uniq -c
grep Success sunquant/${market}/${strategy}.log | wc -l
grep Success sunquant/${market}/${strategy}.log | awk -F  awk -F '  |-:|=|,----------|Success---------' '{print $1," ",$4," ",$6," ",$10,"@",$8}'

echo ""
echo "CONSOLE:"
echo ""
tail ~/sunquant/${market}/console.log
echo ""
echo "LOG:"
echo ""
tail sunquant/${market}/${strategy}.log

