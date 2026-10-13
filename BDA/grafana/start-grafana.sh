#!/bin/sh
set -eu

token_file=/run/influx-secrets/INFLUX_READ_TOKEN
test -s "$token_file"
export INFLUX_READ_TOKEN="$(cat "$token_file")"
exec /run.sh "$@"
