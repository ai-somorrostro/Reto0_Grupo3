#!/bin/sh
set -eu

# Copy the source-controlled flow into the writable Node-RED volume so the
# container always starts with the repository version and Deploy can replace it.
cp /opt/node-red/flows.json /data/flows.json

npm start -- --userDir /data &
node_red_pid=$!

cleanup() {
    kill "$node_red_pid" 2>/dev/null || true
}
trap cleanup INT TERM

node /usr/local/bin/provision_node_red_credentials.js
wait "$node_red_pid"
