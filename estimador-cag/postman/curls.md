# cURL de prueba — Estimador CAG

Servicio en `http://localhost:8000` (`docker compose up --build`). En Postman: **Import → Raw text**, pega un bloque y se crea la petición.
Alternativa: importa `estimador-cag.postman_collection.json` (incluye tests automáticos en cada petición).

> Las peticiones 02–16 usan el flujo de transcripción (`/api/v1/transcription/estimate`); 17–20, el contrato estructurado (`/api/v1/estimate`).
> Las peticiones 02–10, 16, 17 y 18 llaman al proveedor real (consumen tokens). Si usas Anthropic, cambia el `model` de la 08 por `claude-haiku-4-5`.
> En PowerShell usa `curl.exe` y comillas dobles escapadas, o ejecútalos desde Git Bash/WSL; en Postman basta con importarlos.

## 01 Health

```bash
curl http://localhost:8000/health
```

## 02 Estimate - defaults

```bash
curl -X POST http://localhost:8000/api/v1/transcription/estimate \
  -H 'Content-Type: application/json' \
  -d '{
  "transcription": "Reunión con Panadería La Espiga. Quieren una tienda en línea para vender pan y pasteles con entrega a domicilio. Necesitan catálogo con fotos, carrito, pago con tarjeta (Wompi), zonas de entrega con costo por barrio, panel para que el dueño gestione pedidos y productos, y avisos por WhatsApp al cliente cuando el pedido sale. Ah, y hablamos del clima, del fútbol... pero lo importante: quieren salir en 3 meses, presupuesto ajustado. Stack: no tienen preferencia, pero el sobrino del dueño sabe algo de WordPress. Al final dijeron que mejor no WordPress."
}'
```

## 03 Estimate - inline_cleaning

```bash
curl -X POST http://localhost:8000/api/v1/transcription/estimate \
  -H 'Content-Type: application/json' \
  -d '{
  "transcription": "Reunión con Panadería La Espiga. Quieren una tienda en línea para vender pan y pasteles con entrega a domicilio. Necesitan catálogo con fotos, carrito, pago con tarjeta (Wompi), zonas de entrega con costo por barrio, panel para que el dueño gestione pedidos y productos, y avisos por WhatsApp al cliente cuando el pedido sale. Ah, y hablamos del clima, del fútbol... pero lo importante: quieren salir en 3 meses, presupuesto ajustado. Stack: no tienen preferencia, pero el sobrino del dueño sabe algo de WordPress. Al final dijeron que mejor no WordPress.",
  "preprocessing": "inline_cleaning"
}'
```

## 04 Estimate - two_phase

```bash
curl -X POST http://localhost:8000/api/v1/transcription/estimate \
  -H 'Content-Type: application/json' \
  -d '{
  "transcription": "Reunión con Panadería La Espiga. Quieren una tienda en línea para vender pan y pasteles con entrega a domicilio. Necesitan catálogo con fotos, carrito, pago con tarjeta (Wompi), zonas de entrega con costo por barrio, panel para que el dueño gestione pedidos y productos, y avisos por WhatsApp al cliente cuando el pedido sale. Ah, y hablamos del clima, del fútbol... pero lo importante: quieren salir en 3 meses, presupuesto ajustado. Stack: no tienen preferencia, pero el sobrino del dueño sabe algo de WordPress. Al final dijeron que mejor no WordPress.",
  "preprocessing": "two_phase"
}'
```

## 05 Estimate - ejemplos JSON (3)

```bash
curl -X POST http://localhost:8000/api/v1/transcription/estimate \
  -H 'Content-Type: application/json' \
  -d '{
  "transcription": "Reunión con Panadería La Espiga. Quieren una tienda en línea para vender pan y pasteles con entrega a domicilio. Necesitan catálogo con fotos, carrito, pago con tarjeta (Wompi), zonas de entrega con costo por barrio, panel para que el dueño gestione pedidos y productos, y avisos por WhatsApp al cliente cuando el pedido sale. Ah, y hablamos del clima, del fútbol... pero lo importante: quieren salir en 3 meses, presupuesto ajustado. Stack: no tienen preferencia, pero el sobrino del dueño sabe algo de WordPress. Al final dijeron que mejor no WordPress.",
  "example_format": "json",
  "num_examples": 3
}'
```

## 06 Estimate - ejemplos narrativa (5)

```bash
curl -X POST http://localhost:8000/api/v1/transcription/estimate \
  -H 'Content-Type: application/json' \
  -d '{
  "transcription": "Reunión con Panadería La Espiga. Quieren una tienda en línea para vender pan y pasteles con entrega a domicilio. Necesitan catálogo con fotos, carrito, pago con tarjeta (Wompi), zonas de entrega con costo por barrio, panel para que el dueño gestione pedidos y productos, y avisos por WhatsApp al cliente cuando el pedido sale. Ah, y hablamos del clima, del fútbol... pero lo importante: quieren salir en 3 meses, presupuesto ajustado. Stack: no tienen preferencia, pero el sobrino del dueño sabe algo de WordPress. Al final dijeron que mejor no WordPress.",
  "example_format": "narrative",
  "num_examples": 5
}'
```

## 07 Estimate - sin ejemplos

```bash
curl -X POST http://localhost:8000/api/v1/transcription/estimate \
  -H 'Content-Type: application/json' \
  -d '{
  "transcription": "Reunión con Panadería La Espiga. Quieren una tienda en línea para vender pan y pasteles con entrega a domicilio. Necesitan catálogo con fotos, carrito, pago con tarjeta (Wompi), zonas de entrega con costo por barrio, panel para que el dueño gestione pedidos y productos, y avisos por WhatsApp al cliente cuando el pedido sale. Ah, y hablamos del clima, del fútbol... pero lo importante: quieren salir en 3 meses, presupuesto ajustado. Stack: no tienen preferencia, pero el sobrino del dueño sabe algo de WordPress. Al final dijeron que mejor no WordPress.",
  "use_examples": false
}'
```

## 08 Estimate - model + max_tokens

```bash
curl -X POST http://localhost:8000/api/v1/transcription/estimate \
  -H 'Content-Type: application/json' \
  -d '{
  "transcription": "Reunión con Panadería La Espiga. Quieren una tienda en línea para vender pan y pasteles con entrega a domicilio. Necesitan catálogo con fotos, carrito, pago con tarjeta (Wompi), zonas de entrega con costo por barrio, panel para que el dueño gestione pedidos y productos, y avisos por WhatsApp al cliente cuando el pedido sale. Ah, y hablamos del clima, del fútbol... pero lo importante: quieren salir en 3 meses, presupuesto ajustado. Stack: no tienen preferencia, pero el sobrino del dueño sabe algo de WordPress. Al final dijeron que mejor no WordPress.",
  "model": "gpt-4o-mini",
  "max_tokens": 3000
}'
```

## 09 Estimate - truncada (max_tokens=200)

```bash
curl -X POST http://localhost:8000/api/v1/transcription/estimate \
  -H 'Content-Type: application/json' \
  -d '{
  "transcription": "Reunión con Panadería La Espiga. Quieren una tienda en línea para vender pan y pasteles con entrega a domicilio. Necesitan catálogo con fotos, carrito, pago con tarjeta (Wompi), zonas de entrega con costo por barrio, panel para que el dueño gestione pedidos y productos, y avisos por WhatsApp al cliente cuando el pedido sale. Ah, y hablamos del clima, del fútbol... pero lo importante: quieren salir en 3 meses, presupuesto ajustado. Stack: no tienen preferencia, pero el sobrino del dueño sabe algo de WordPress. Al final dijeron que mejor no WordPress.",
  "max_tokens": 200
}'
```

## 10 Estimate - evaluate=false

```bash
curl -X POST http://localhost:8000/api/v1/transcription/estimate \
  -H 'Content-Type: application/json' \
  -d '{
  "transcription": "Reunión con Panadería La Espiga. Quieren una tienda en línea para vender pan y pasteles con entrega a domicilio. Necesitan catálogo con fotos, carrito, pago con tarjeta (Wompi), zonas de entrega con costo por barrio, panel para que el dueño gestione pedidos y productos, y avisos por WhatsApp al cliente cuando el pedido sale. Ah, y hablamos del clima, del fútbol... pero lo importante: quieren salir en 3 meses, presupuesto ajustado. Stack: no tienen preferencia, pero el sobrino del dueño sabe algo de WordPress. Al final dijeron que mejor no WordPress.",
  "evaluate": false
}'
```

## 11 Validacion - preprocessing invalido

```bash
curl -X POST http://localhost:8000/api/v1/transcription/estimate \
  -H 'Content-Type: application/json' \
  -d '{
  "transcription": "Reunión con Panadería La Espiga. Quieren una tienda en línea para vender pan y pasteles con entrega a domicilio. Necesitan catálogo con fotos, carrito, pago con tarjeta (Wompi), zonas de entrega con costo por barrio, panel para que el dueño gestione pedidos y productos, y avisos por WhatsApp al cliente cuando el pedido sale. Ah, y hablamos del clima, del fútbol... pero lo importante: quieren salir en 3 meses, presupuesto ajustado. Stack: no tienen preferencia, pero el sobrino del dueño sabe algo de WordPress. Al final dijeron que mejor no WordPress.",
  "preprocessing": "magia"
}'
```

## 12 Validacion - num_examples=6

```bash
curl -X POST http://localhost:8000/api/v1/transcription/estimate \
  -H 'Content-Type: application/json' \
  -d '{
  "transcription": "Reunión con Panadería La Espiga. Quieren una tienda en línea para vender pan y pasteles con entrega a domicilio. Necesitan catálogo con fotos, carrito, pago con tarjeta (Wompi), zonas de entrega con costo por barrio, panel para que el dueño gestione pedidos y productos, y avisos por WhatsApp al cliente cuando el pedido sale. Ah, y hablamos del clima, del fútbol... pero lo importante: quieren salir en 3 meses, presupuesto ajustado. Stack: no tienen preferencia, pero el sobrino del dueño sabe algo de WordPress. Al final dijeron que mejor no WordPress.",
  "num_examples": 6
}'
```

## 13 Validacion - max_tokens=0

```bash
curl -X POST http://localhost:8000/api/v1/transcription/estimate \
  -H 'Content-Type: application/json' \
  -d '{
  "transcription": "Reunión con Panadería La Espiga. Quieren una tienda en línea para vender pan y pasteles con entrega a domicilio. Necesitan catálogo con fotos, carrito, pago con tarjeta (Wompi), zonas de entrega con costo por barrio, panel para que el dueño gestione pedidos y productos, y avisos por WhatsApp al cliente cuando el pedido sale. Ah, y hablamos del clima, del fútbol... pero lo importante: quieren salir en 3 meses, presupuesto ajustado. Stack: no tienen preferencia, pero el sobrino del dueño sabe algo de WordPress. Al final dijeron que mejor no WordPress.",
  "max_tokens": 0
}'
```

## 14 Validacion - model con caracteres invalidos

```bash
curl -X POST http://localhost:8000/api/v1/transcription/estimate \
  -H 'Content-Type: application/json' \
  -d '{
  "transcription": "Reunión con Panadería La Espiga. Quieren una tienda en línea para vender pan y pasteles con entrega a domicilio. Necesitan catálogo con fotos, carrito, pago con tarjeta (Wompi), zonas de entrega con costo por barrio, panel para que el dueño gestione pedidos y productos, y avisos por WhatsApp al cliente cuando el pedido sale. Ah, y hablamos del clima, del fútbol... pero lo importante: quieren salir en 3 meses, presupuesto ajustado. Stack: no tienen preferencia, pero el sobrino del dueño sabe algo de WordPress. Al final dijeron que mejor no WordPress.",
  "model": "gpt 4o; drop"
}'
```

## 15 Validacion - transcripcion corta

```bash
curl -X POST http://localhost:8000/api/v1/transcription/estimate \
  -H 'Content-Type: application/json' \
  -d '{
  "transcription": "Corto"
}'
```

## 16 Error controlado - modelo inexistente

```bash
curl -X POST http://localhost:8000/api/v1/transcription/estimate \
  -H 'Content-Type: application/json' \
  -d '{
  "transcription": "Reunión con Panadería La Espiga. Quieren una tienda en línea para vender pan y pasteles con entrega a domicilio. Necesitan catálogo con fotos, carrito, pago con tarjeta (Wompi), zonas de entrega con costo por barrio, panel para que el dueño gestione pedidos y productos, y avisos por WhatsApp al cliente cuando el pedido sale. Ah, y hablamos del clima, del fútbol... pero lo importante: quieren salir en 3 meses, presupuesto ajustado. Stack: no tienen preferencia, pero el sobrino del dueño sabe algo de WordPress. Al final dijeron que mejor no WordPress.",
  "model": "modelo-que-no-existe"
}'
```

## 17 Estructurada - v1 tabla de fases

```bash
curl -X POST http://localhost:8000/api/v1/estimate \
  -H 'Content-Type: application/json' \
  -d '{
  "description": "Aplicación web para que una panadería venda pan y pasteles con entrega a domicilio: catálogo con fotos, carrito, pago con tarjeta, zonas de entrega por barrio y panel de pedidos.",
  "project_type": "web_saas",
  "detail_level": "medium",
  "output_format": "phases_table"
}'
```

## 18 Estructurada - v2 narrativa con referencias

```bash
curl -X POST 'http://localhost:8000/api/v1/estimate?prompt_version=v2' \
  -H 'Content-Type: application/json' \
  -d '{
  "description": "Aplicación web para que una panadería venda pan y pasteles con entrega a domicilio: catálogo con fotos, carrito, pago con tarjeta, zonas de entrega por barrio y panel de pedidos.",
  "project_type": "web_saas",
  "detail_level": "detailed",
  "output_format": "narrative",
  "reference_projects": [
    {"name": "Tienda online de floristería", "description": "Catálogo, pagos y repartos por zonas", "actual_hours": 420}
  ]
}'
```

## 19 Estructurada - descripcion corta (422)

```bash
curl -X POST http://localhost:8000/api/v1/estimate \
  -H 'Content-Type: application/json' \
  -d '{"description": "Corta", "project_type": "web_saas", "detail_level": "medium", "output_format": "phases_table"}'
```

## 20 Estructurada - prompt_version inexistente (422)

```bash
curl -X POST 'http://localhost:8000/api/v1/estimate?prompt_version=v9' \
  -H 'Content-Type: application/json' \
  -d '{"description": "Aplicación web para que una panadería venda pan con entrega a domicilio.", "project_type": "web_saas", "detail_level": "medium", "output_format": "phases_table"}'
```
