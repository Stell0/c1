#!/usr/bin/env bash
# Sample host memory/swap and top resident processes every 30 s until the gate exit file exists.
out=docs/evidence/M09/regression-live-host-samples.txt
until [[ -e docs/evidence/M09/regression-live-exit.txt ]]; do
  {
    printf '%s ' "$(date -u +%H:%M:%S)"
    free -m | awk '/Mem:/{printf "mem_used=%s avail=%s ", $3, $7} /Swap:/{printf "swap_used=%s ", $3}'
    ps -eo rss,comm --sort=-rss | awk 'NR>1 && NR<=5 {printf "%s:%dMB ", $2, $1/1024}'
    printf 'load=%s\n' "$(cut -d' ' -f1 /proc/loadavg)"
  } >> "$out"
  sleep 30
done
