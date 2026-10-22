FROM nodered/node-red:4.0

USER root
RUN npm install --unsafe-perm --no-update-notifier --no-fund node-red-contrib-influxdb@0.7.0
COPY start-node-red.sh /usr/local/bin/start-node-red.sh
COPY provision_node_red_credentials.js /usr/local/bin/provision_node_red_credentials.js
RUN chmod +x /usr/local/bin/start-node-red.sh
USER node-red

ENTRYPOINT ["/usr/local/bin/start-node-red.sh"]
