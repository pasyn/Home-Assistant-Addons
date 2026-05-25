#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
export LD_LIBRARY_PATH=/usr/local/lib64

if bashio::config.true 'rtltcpdebug'; then
  exec /usr/local/bin/rtl_tcp -a 0.0.0.0 -p 1234
else
  exec /usr/local/bin/rtl_tcp -a 0.0.0.0 -p 1234 2>/dev/null
fi
