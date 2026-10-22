# Arquitectura de M7

Diagramas del módulo M7 (Tarifas, Pagos y Liquidaciones), sacados de la consigna y del contrato de M7. Están escritos con [Mermaid](https://mermaid.js.org/): GitHub los muestra como dibujos y se editan como texto, junto con el código (RNF-20).

## Contexto

Quién usa M7 y para qué. Cada flecha va de quien llama a quien responde.

```mermaid
flowchart LR
    M5["M5 Solicitud y Despacho"]
    M9["M9 Reservas"]
    M6["M6 Viajes"]
    OP["Operadores"]
    PER["Clientes y conductores"]
    M7(["M7 Tarifas, Pagos<br>y Liquidaciones"])
    BD[("Base de datos de M7<br>PostgreSQL")]
    M1["M1 Identidad y Acceso<br>Keycloak"]
    PAS["Pasarela de pago<br>simulada"]
    M8["M8 Notificaciones"]

    M5 -->|estimación| M7
    M9 -->|"estimación, cargo y reembolso<br>de una reserva cancelada"| M7
    M6 -->|"tarifa final, pago<br>y cargo por cancelación"| M7
    OP -->|"reglas de tarifa, reembolsos<br>y liquidaciones"| M7
    PER -->|"sus pagos, liquidaciones y saldo"| M7
    M7 --> BD
    M7 -.->|valida los tokens| M1
    M7 -->|pide el cobro| PAS
    PAS -->|avisa el resultado| M7
    M7 -.->|"eventos (TP2)"| M8
```

M7 no llama a M4 (Ubicación): la distancia y el tiempo de cada viaje los mandan M5, M6 y M9, que los obtienen de M4. Los eventos para M8 llegan en el TP2, con la mensajería.

## Capas

Por dónde pasa una solicitud dentro de M7.

```mermaid
flowchart TB
    SOL["Solicitud HTTP<br>de otro módulo, un operador o la pasarela"]
    subgraph API["M7, con FastAPI"]
        CORE["app/core<br>X-Request-Id y errores application/problem+json"]
        RUTAS["app/routers<br>las rutas del contrato"]
        ESQ["app/schemas<br>validan los cuerpos: si no tienen el formato, 400"]
        SERV["app/services<br>reglas de negocio y cálculos"]
        MOD["app/models<br>las tablas"]
    end
    BD[("PostgreSQL<br>base propia de M7")]

    SOL --> CORE --> RUTAS
    RUTAS --> ESQ
    RUTAS --> SERV --> MOD --> BD
```

## Recorrido de un viaje

Cómo se cobra un viaje y cómo se le liquida al conductor, como lo describe el contrato.

```mermaid
sequenceDiagram
    autonumber
    participant D as M5 o M9
    participant V as M6 Viajes
    participant M7 as M7
    participant P as Pasarela de pago
    participant O as Operador

    D->>M7: POST /api/v1/tarifas/estimaciones
    M7-->>D: 200 con el precio estimado, que no se guarda
    Note over V: El viaje termina
    V->>M7: POST /api/v1/tarifas/viajes/{viaje_id}/tarifa-final
    M7-->>V: 201 con la tarifa final, según la distancia y el tiempo reales
    V->>M7: POST /api/v1/pagos con Idempotency-Key
    alt En efectivo
        M7-->>V: 201 con el pago aprobado
    else Con tarjeta o billetera virtual
        M7->>P: pide el cobro
        M7-->>V: 201 con el pago pendiente
        P->>M7: POST /api/v1/pagos/webhooks/pasarela
        M7-->>P: 200 con el pago aprobado o rechazado
    end
    O->>M7: POST /api/v1/liquidaciones de un beneficiario y un período
    M7-->>O: 201 con la liquidación pendiente
    O->>M7: POST /api/v1/liquidaciones/{liquidacion_id}/transferencia
    M7-->>O: 200 con la liquidación transferida
```
