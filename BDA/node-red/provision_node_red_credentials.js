const fs = require('fs');
const http = require('http');

const token = process.env.INFLUX_WRITE_TOKEN;
if (!token) {
  throw new Error('INFLUX_WRITE_TOKEN no está definido');
}

const flowFile = '/data/flows.json';
const flows = JSON.parse(fs.readFileSync(flowFile, 'utf8'));
const configNode = flows.find(node => node.id === 'esios-influx-config');
if (!configNode) {
  throw new Error('No se encontró esios-influx-config en flows.json');
}

configNode.credentials = { token };
const body = JSON.stringify(flows);

function request() {
  return new Promise((resolve, reject) => {
    const req = http.request({
      hostname: '127.0.0.1',
      port: 1880,
      path: '/flows',
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Node-RED-API-Version': 'v1',
        'Content-Length': Buffer.byteLength(body)
      }
    }, response => {
      response.resume();
      response.on('end', () => {
        if (response.statusCode >= 200 && response.statusCode < 300) {
          resolve();
        } else {
          reject(new Error(`Node-RED respondió HTTP ${response.statusCode}`));
        }
      });
    });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

async function main() {
  const deadline = Date.now() + 60000;
  while (Date.now() < deadline) {
    try {
      await request();
      console.log('Credenciales de InfluxDB provisionadas automáticamente.');
      return;
    } catch (error) {
      if (Date.now() >= deadline) throw error;
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
  }
}

main().catch(error => {
  console.error(`No se pudieron provisionar las credenciales de Node-RED: ${error.message}`);
  process.exitCode = 1;
});
