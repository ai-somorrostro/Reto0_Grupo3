FROM nodered/node-red:latest

USER root
RUN npm install --unsafe-perm --no-update-notifier --no-fund \
    node-red-contrib-influxdb \
    node-red-contrib-ai-flow-builder
USER node-red
