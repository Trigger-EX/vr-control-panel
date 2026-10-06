#!/bin/bash
# usage: run_sweep.sh PANEL W OUTFILE
P=$1; W=$2; OUT=$3; : > $OUT
for LH in 0 1; do for TH in 0 1; do for H in 640 680 720 760 800; do
  FT=40 timeout 50 xvfb-run -a -s "-screen 0 1600x1200x24" ${PY:-python3} t_cell.py $P $W $H $LH $TH > cell.$W.tmp 2>&1
  rc=$?
  last=$(grep "^\.\." cell.$W.tmp | tail -1)
  if ! grep -q "^CELL" cell.$W.tmp; then echo "HANG/CRASH rc=$rc W=$W H=$H log_hidden=$LH term_hidden=$TH at: $last" >> $OUT; grep -A8 "Timeout\|Traceback" cell.$W.tmp | head -12 >> $OUT; fi
  grep "^FAIL\|^CELL" cell.$W.tmp >> $OUT
done; done; done
echo DONE >> $OUT
