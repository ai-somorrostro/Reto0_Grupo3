<<<<<<< HEAD
FROM nodered/node-red:latest

USER root
RUN npm install --unsafe-perm --no-update-notifier --no-fund \
    node-red-contrib-influxdb \
    node-red-contrib-ai-flow-builder
USER node-red
=======
FROM nodered/node-red:4.0

USER root
RUN npm install --unsafe-perm --no-update-notifier --no-fund node-red-contrib-influxdb
COPY start-node-red.sh /usr/local/bin/start-node-red.sh
COPY provision_node_red_credentials.js /usr/local/bin/provision_node_red_credentials.js
RUN chmod +x /usr/local/bin/start-node-red.sh
USER node-red

ENTRYPOINT ["/usr/local/bin/start-node-red.sh"]
>>>>>>> 2dc7bc5d4398e1ebe70e70e8f252ce277e65a9e5
