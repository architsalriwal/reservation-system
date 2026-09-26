#!/bin/bash
# Appends a timestamped memory snapshot every 15 min via cron (see
# user-data.sh / the crontab entry it installs). This exists because the
# Sep 20 outage's root cause (steady memory growth over ~2 days, ending in
# repeated OOM kills) was never pinned down - there was no data, only a
# post-mortem of kernel logs after the fact. This gives a real, plottable
# series instead of another guess next time.
LOG=/home/ubuntu/memory.log
{
  printf '%s ' "$(date -u +%Y-%m-%dT%H:%M:%S)"
  free -m | awk '/^Mem:/{printf "total=%sM used=%sM free=%sM avail=%sM ", $2,$3,$4,$7} /^Swap:/{printf "swap_used=%sM", $3}'
  echo
} >> "$LOG"

# Keep the log from growing forever - 15 min * 4 * 24 * 30 =~ one month of history.
tail -n 2880 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
