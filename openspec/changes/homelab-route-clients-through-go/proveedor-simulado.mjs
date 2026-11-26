// Proveedor de IA simulado para probar la salida HTTPS de estimador-cag (13.2). Nunca contacta proveedores reales.
// Sirve TLS con el certificado autofirmado que genera verificar-red-bloque4.sh y responde JSON fijo.
import { readFileSync } from "node:fs";
import https from "node:https";

const dir = process.env.CERT_DIR ?? "/certs";
https.createServer({ key: readFileSync(`${dir}/key.pem`), cert: readFileSync(`${dir}/cert.pem`) }, (req, res) => {
  res.writeHead(200, { "content-type": "application/json" });
  res.end(JSON.stringify({ proveedor: "simulado", ruta: req.url }));
}).listen(8443, "0.0.0.0", () => console.log("proveedor simulado en :8443"));
