# M7: Tarifas, Pagos y Liquidaciones (Grupo 6)

Servicio de tarifas, pagos y liquidaciones de la plataforma de movilidad del TPI 2026 de Desarrollo de Software (UTN FRRe). Cumple el contrato que compartimos con el Grupo 11, que está en el submódulo `contratos`, en `contratos/contratos/m7_tarifas/openapi.yml`. Por ahora el submódulo apunta a la versión 1.1.0 del contrato, la del PR #19 de la cátedra (medios de pago del cliente), que todavía no se aceptó; cuando se acepte, vuelve a apuntar al contrato oficial.

**Estado:** responden las 26 rutas del contrato 1.1.0: tarifas, pagos, aviso de la pasarela, historial, cargos por cancelación, reembolsos, medios de pago, liquidaciones y saldos. Cada ruta valida el token de Keycloak y su permiso. Faltan sumar en `keycloak/` el archivo del realm `ds-2026-realm` (el de la cátedra todavía no tiene los permisos de M7) y los eventos con RabbitMQ, que son del TP2.

## Integrantes

- Bubrosky, Rodrigo Axel Exequiel
- De Bortoli, Jorge Luis
- Dominguez, Luciano Oriel
- Gomez Arizaga, German
- Manattini, Maximo
- Moreno, Maximo
- Rivero, Tiago
- Sujoluzky, Alan
- Svriz, José Emanuel

## Qué hace M7

Según la consigna, M7 se encarga de la estimación, el cobro, la cancelación, el reintegro y la liquidación de los viajes.

| Requerimiento | Cómo lo resuelve M7 |
| --- | --- |
| RF-7.1 Estimación de tarifa | Reglas de tarifa por tipo de vehículo, que configura un operador. Con la regla activa calcula la estimación antes del viaje y la tarifa final cuando termina |
| RF-7.2 Método de pago | El cliente registra sus medios de pago (tarjeta, billetera virtual o efectivo) y elige uno como predeterminado. M7 lo usa en sus cobros; si no tiene ninguno, el viaje se paga en efectivo |
| RF-7.3 Autorización y captura | Simuladas: en efectivo el pago se aprueba en el acto; con tarjeta o billetera virtual queda pendiente hasta que la pasarela avisa si lo aprobó o lo rechazó |
| RF-7.4 Cargo de cancelación | Si una cancelación lleva cargo, cobra el monto fijo de la regla activa con una tarjeta o billetera virtual del cliente. Si no tiene ninguna, el cargo espera hasta que registre una |
| RF-7.5 Reintegro | Reembolsos totales o parciales de un pago aprobado |
| RF-7.6 Idempotencia de pago | El pago, el cargo y el reembolso exigen `Idempotency-Key`: repetir la misma orden no cobra ni reembolsa dos veces |
| RF-7.7 Historial financiero | Cada pago guarda sus movimientos (registro, aprobación o rechazo y reembolsos), que no se modifican ni se borran |
| RF-7.8 Liquidación al conductor | Liquida a cada beneficiario por período: lo cobrado, menos la comisión de la plataforma y lo que ya cobró en efectivo |

## Con quién se integra

| Quién | Para qué |
| --- | --- |
| M1 Identidad y Acceso (Keycloak) | Emite los tokens. M7 controla el permiso de cada ruta y, si el token es de una persona, su rol |
| M5 Solicitud y Despacho | Pide la estimación antes de confirmar un viaje |
| M9 Reservas | Pide la estimación de una reserva y registra el cargo o el reembolso de una reserva cancelada |
| M6 Viajes | Cuando el viaje termina, registra la tarifa final y el pago. Si una cancelación lleva cargo, lo registra |
| M4 Ubicación | No la llama M7: la distancia y el tiempo los mandan M5, M6 y M9, que los obtienen de M4 |
| M8 Notificaciones | Va a recibir los eventos de M7 cuando llegue la mensajería, en el TP2 |
| Pasarela de pago (simulada) | M7 le pide los cobros con tarjeta o billetera virtual, y ella avisa si los aprobó o los rechazó |
| Operadores | Configuran las reglas de tarifa, hacen reembolsos y generan las liquidaciones |
| Clientes | Registran sus medios de pago y consultan sus pagos |
| Conductores | Consultan sus liquidaciones y su saldo |

## Tecnologías

| Tecnología | Para qué |
| --- | --- |
| Python 3.12 y FastAPI | La API REST ([decisión 0001](docs/decisiones/0001-python-fastapi.md)) |
| Pydantic | Validar los cuerpos con los esquemas del contrato |
| PyJWT | Validar los tokens de Keycloak con sus claves públicas |
| SQLAlchemy y PostgreSQL 16 | La base de datos propia de M7 |
| Keycloak 24 | El M1 en local, que emite los tokens |
| Docker y Docker Compose | Levantar la API, su base y Keycloak con un solo comando |
| pytest | Pruebas unitarias y de integración |
| OpenAPI 3.1 | El contrato de la API |

## Arquitectura

M7 es un servicio independiente con su propia base de datos (RNF-02 y RNF-05). Por dentro está en capas: las rutas reciben cada solicitud, los servicios aplican las reglas de negocio y los modelos leen y guardan en la base. En [Estructura](#estructura) está la carpeta de cada capa.

Los diagramas de contexto, de capas y del recorrido de un viaje están en [docs/arquitectura.md](docs/arquitectura.md).

## Base de datos

PostgreSQL, propia de M7: los demás módulos no consultan sus tablas, usan la API (RNF-05). La API crea las tablas que falten al arrancar, a partir de `app/models`. No cambia las tablas que ya existen: si se cambia una tabla, en local hay que borrar la base con `docker compose down -v`.

| Tabla | Qué guarda |
| --- | --- |
| `claves_idempotencia` | Cada `Idempotency-Key` usada, con la huella del cuerpo y la respuesta que se devolvió (RF-7.6) |
| `reglas_tarifa` | Las reglas de tarifa de cada tipo de vehículo. Un índice único deja una sola activa por tipo |
| `tarifas_finales` | La tarifa final de cada viaje terminado, con su desglose. El viaje es la clave primaria: hay una sola por viaje |
| `medios_pago` | Las tarjetas, billeteras virtuales y el efectivo de cada cliente. De una tarjeta guarda solo el token de la pasarela y los últimos 4 dígitos (RNF-19). Un índice único deja un solo predeterminado por cliente. Un medio dado de baja no se borra |
| `pagos` | Los pagos de los viajes y los cargos por cancelación, con su estado. Índices únicos dejan un solo pago y un solo cargo no rechazados por viaje (RNF-08) |
| `movimientos_pago` | El historial de cada pago: registro, aprobación, rechazo y reembolsos, con quién lo hizo (RF-7.7). No se modifica ni se borra |
| `reembolsos` | Los reembolsos totales o parciales de cada pago (RF-7.5) |
| `liquidaciones` | Las liquidaciones de cada beneficiario por período, con sus pagos e importes (RF-7.8). Cada pago anota en qué liquidación está |

## API

Las rutas del contrato. El detalle de cada una (cuerpos, respuestas y errores) está en el contrato, y con la API levantada, http://localhost:8000/docs permite probarlas (el botón **Authorize** recibe el token).

| Método | Ruta | Qué hace |
| --- | --- | --- |
| GET | `/health` | Disponibilidad del servicio y de su base |
| POST | `/api/v1/tarifas/estimaciones` | Estimar la tarifa de un viaje |
| POST | `/api/v1/tarifas/viajes/{viaje_id}/tarifa-final` | Calcular y registrar la tarifa final de un viaje terminado |
| GET | `/api/v1/tarifas/viajes/{viaje_id}/tarifa-final` | Consultar la tarifa final de un viaje |
| GET | `/api/v1/tarifas/reglas` | Listar las reglas de tarifa |
| POST | `/api/v1/tarifas/reglas` | Crear una regla de tarifa |
| GET | `/api/v1/tarifas/reglas/{regla_id}` | Consultar una regla de tarifa |
| PATCH | `/api/v1/tarifas/reglas/{regla_id}` | Modificar una regla de tarifa |
| POST | `/api/v1/pagos` | Registrar el pago de un viaje |
| GET | `/api/v1/pagos` | Listar pagos |
| GET | `/api/v1/pagos/{pago_id}` | Consultar un pago |
| GET | `/api/v1/pagos/{pago_id}/movimientos` | Historial de un pago |
| POST | `/api/v1/pagos/{pago_id}/reembolsos` | Reembolsar todo o parte de un pago |
| GET | `/api/v1/pagos/{pago_id}/reembolsos` | Listar los reembolsos de un pago |
| POST | `/api/v1/pagos/webhooks/pasarela` | Recibir el resultado que informa la pasarela |
| POST | `/api/v1/cargos-cancelacion` | Registrar el cargo fijo por una cancelación |
| POST | `/api/v1/medios-pago` | Registrar un medio de pago del cliente |
| GET | `/api/v1/medios-pago` | Listar los medios de pago |
| PATCH | `/api/v1/medios-pago/{medio_pago_id}` | Elegir el medio predeterminado o cambiar su alias |
| DELETE | `/api/v1/medios-pago/{medio_pago_id}` | Dar de baja un medio de pago |
| POST | `/api/v1/liquidaciones` | Generar la liquidación de un beneficiario |
| GET | `/api/v1/liquidaciones` | Listar liquidaciones |
| GET | `/api/v1/liquidaciones/saldos/{beneficiario_id}` | Consultar el saldo de un beneficiario |
| GET | `/api/v1/liquidaciones/{liquidacion_id}` | Consultar una liquidación |
| POST | `/api/v1/liquidaciones/{liquidacion_id}/transferencia` | Registrar la transferencia al beneficiario |
| POST | `/api/v1/liquidaciones/{liquidacion_id}/anulacion` | Anular una liquidación pendiente |

## Tokens y permisos

Cada ruta, menos `GET /health` y el aviso de la pasarela, pide un token de Keycloak (M1) en `Authorization: Bearer <token>` con el permiso que dice el contrato (`tarifas:read`, `pagos:write`, etc.). M7 controla la firma del token con las claves públicas de Keycloak, que no esté vencido y que sea del realm `ds-2026-realm`. Sin token, o con uno inválido, responde `401`; sin el permiso, `403`; si Keycloak no responde, `503`.

Si el token es de una persona, M7 también mira su rol (RF-1.3), en `realm_access.roles`:

- un `CLIENTE` solo ve sus pagos y maneja sus medios de pago; no puede registrar pagos, cargos ni reembolsos;
- un `CONDUCTOR` solo ve sus liquidaciones y su saldo;
- un `OPERADOR` ve todo.

El `sub` del token de la persona es su `cliente_id` o su `beneficiario_id`. Los módulos usan su cuenta de servicio, sin esos roles.

El realm de la cátedra todavía no tiene los permisos de M7. Mientras tanto, para desarrollar o integrarse con otro módulo, se puede poner `AUTH_DISABLED=true` en el `.env`: M7 deja de pedir el token.

## Pasarela de pago simulada

Con tarjeta o billetera virtual, M7 le pide el cobro a una pasarela simulada (`app/services/pasarela.py`, RF-7.3): el pago queda `pendiente`, con su `referencia_externa`. Para simular el aviso de la pasarela, se llama a la ruta del aviso con el secreto del `.env`:

```bash
curl -X POST http://localhost:8000/api/v1/pagos/webhooks/pasarela \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: <PASARELA_WEBHOOK_SECRET>" \
  -d '{"pago_id": "<id del pago>", "referencia_externa": "<referencia_externa del pago>", "estado": "aprobado"}'
```

Con `"estado": "rechazado"`, el pago queda rechazado y el viaje se puede volver a cobrar.

## Eventos

M7 propone para el catálogo común de eventos (RNF-03): pago aprobado, pago rechazado, reembolso registrado, cargo por cancelación registrado y liquidación generada. Sus nombres y su formato los define el catálogo común. La mensajería con RabbitMQ llega en el TP2.

## Cómo levantarlo con Docker

Hace falta Docker Desktop.

1. Clonar el repo con el submódulo de contratos:

   ```bash
   git clone --recurse-submodules https://github.com/FRRe-DS/2026-06-TPI.git
   cd 2026-06-TPI
   ```

2. Crear el `.env` y completar las claves vacías:

   ```bash
   cp .env.example .env
   ```

3. Levantar la API, su base de datos y Keycloak:

   ```bash
   docker compose up --build -d
   docker compose ps
   ```

4. Probar:
   - http://localhost:8000/health responde `{"status": "ok"}`;
   - http://localhost:8000/docs muestra la API para probarla;
   - http://localhost:8080 es la consola de Keycloak (usuario `admin` y la clave del `.env`).

Para ver qué hace la API: `docker compose logs -f m7-api`. Para apagar todo: `docker compose down` (con `-v` también se borran los datos de la base).

## Cómo correrlo sin Docker

Hace falta Python 3.12. La base de datos sí corre en Docker:

```bash
docker compose up -d m7-db
cd m7-tarifas
python -m venv .venv
source .venv/bin/activate        # en Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

En el `.env`, la clave de `DATABASE_URL` tiene que ser la misma que `POSTGRES_PASSWORD`.

## Pruebas

```bash
cd m7-tarifas
pytest
```

Así nomás, las pruebas usan un archivo SQLite temporal y corren sin Docker. Para correrlas contra PostgreSQL, la misma base que usa M7 (pruebas de integración, RNF-07), se crea una base solo para las pruebas y se la indica en `PRUEBAS_DATABASE_URL`:

```bash
docker compose up -d m7-db
docker compose exec m7-db createdb -U m7 m7_pruebas
export PRUEBAS_DATABASE_URL=postgresql+psycopg://m7:<clave>@localhost:5432/m7_pruebas
# en Windows (PowerShell): $env:PRUEBAS_DATABASE_URL = "postgresql+psycopg://m7:<clave>@localhost:5432/m7_pruebas"
pytest
```

`<clave>` es la de `POSTGRES_PASSWORD`. Cada prueba borra los datos de esa base: nunca hay que apuntarla a la base `m7`, la de desarrollo.

`tests/test_contrato.py` controla que cada operación de la API esté en el contrato oficial. Se saltea mientras el submódulo no tenga el contrato con sus rutas.

Casi todas las pruebas corren sin token (`AUTH_DISABLED=true`) para probar las reglas de negocio. `tests/test_seguridad.py` vuelve a pedir el token: levanta un "Keycloak de prueba" que publica una clave pública, firma los tokens con su clave privada y controla que cada ruta pida el permiso del contrato.

## Dependencias

`m7-tarifas/requirements.txt` tiene la versión exacta de cada dependencia, para que la instalación sea igual en todas las máquinas (filmina DS-02). Para sumar una librería: `pip install <librería>`, después `pip freeze > requirements.txt`, y se suben los dos cambios juntos.

## Variables de entorno

| Variable | Para qué |
| --- | --- |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Base de datos de M7 |
| `KEYCLOAK_ADMIN_PASSWORD` | Clave del usuario `admin` de Keycloak en local |
| `AUTH_DISABLED` | `true` saltea la validación del token; solo para desarrollar o integrarse mientras el realm no tenga los permisos de M7 |
| `PASARELA_WEBHOOK_SECRET` | Clave que manda la pasarela simulada en `X-Webhook-Secret` |
| `COMISION_PLATAFORMA` | Comisión de las liquidaciones (`0.20` es 20%) |
| `KEYCLOAK_ISSUER_URI`, `KEYCLOAK_JWKS_URI` | Quién emite los tokens y de dónde se bajan sus claves públicas. Ya vienen en `docker-compose.yml` |
| `DATABASE_URL` | Conexión a la base, solo para correr sin Docker |

## Estructura

```text
contratos/            submódulo con los contratos de la cátedra
m7-tarifas/           el servicio
  app/main.py         arranca FastAPI y suma las rutas
  app/core/           lo común a todas las rutas: configuración, base de datos, errores,
                      X-Request-Id, control de cuerpos, paginación e Idempotency-Key
  app/routers/        las rutas, agrupadas como en el contrato
  app/schemas/        los cuerpos del contrato
  app/models/         las tablas de la base
  app/services/       las reglas de negocio
  tests/              pruebas
keycloak/             el realm ds-2026-realm que importa Keycloak al arrancar
docs/arquitectura.md  diagramas de contexto, de capas y del recorrido de un viaje
docs/decisiones/      registro de decisiones
```

## Decisiones

- [0001. Python y FastAPI](docs/decisiones/0001-python-fastapi.md)
