# 0001. Lenguaje y framework de M7: Python y FastAPI

- **Estado:** propuesta, pendiente de aprobación de la cátedra (RNF-01)
- **Fecha:** 22/10/2026
- **Grupo:** Grupo 6, módulo M7 (Tarifas, Pagos y Liquidaciones)

## Contexto

RNF-01 deja elegir el lenguaje y el framework, con aprobación de la cátedra y una justificación técnica.

M7 es una API REST definida por un contrato OpenAPI 3.1 (`contratos/m7_tarifas/openapi.yml`), común con el Grupo 11. Para el TP1 tiene que correr en contenedores (RNF-04), con su propia base de datos (RNF-05), con la configuración fuera del repositorio (RNF-06), con pruebas unitarias y de integración (RNF-07) y sin cobros duplicados ante solicitudes simultáneas (RNF-08).

El grupo tiene 9 integrantes con poca experiencia en desarrollo.

## Decisión

Python 3.12 con FastAPI, servido con Uvicorn. Completan el stack:

- PostgreSQL 16 como base de datos propia de M7, usada con SQLAlchemy;
- pytest para las pruebas;
- Docker y Docker Compose para levantar la API, su base de datos y Keycloak (M1);
- PyJWT para validar los tokens que emite Keycloak.

## Por qué

| Necesidad | Cómo la cubre esta elección |
| --- | --- |
| Contrato OpenAPI y errores consistentes (RNF-03) | FastAPI genera la especificación OpenAPI y la página Swagger (`/docs`) a partir del código. Así se puede comparar la API con el contrato y probar cada operación, como muestra la filmina DS-04. |
| Validación de los datos | Pydantic valida cada cuerpo con los campos, tipos y valores permitidos del contrato. |
| Contenedores reproducibles (RNF-04) | Se usa la imagen oficial `python:3.12-slim` con un Dockerfile corto. Las dependencias van con versión exacta en `requirements.txt` y se instalan con `venv` y `pip`, como explica la filmina DS-02. |
| Pruebas (RNF-07) | pytest y el cliente de pruebas de FastAPI cubren las pruebas unitarias y las de integración. |
| Sin doble cobro (RNF-08) | Se usan transacciones de PostgreSQL y restricciones únicas (una clave de idempotencia, un solo pago activo por viaje), desde SQLAlchemy. |
| Un equipo con poca experiencia | El código es corto y fácil de leer, y parte de la documentación oficial de FastAPI está en español. El Grupo 11, que implementa el mismo módulo, usa el mismo stack: se pueden consultar dudas manteniendo implementaciones independientes (RNF-02). |

## Alternativas consideradas

- **Java con Spring Boot:** es el stack del ejemplo de la cátedra y trae incorporados la validación, las transacciones y los errores `problem+json`. Se descartó por la cantidad de archivos y configuración, la instalación del JDK y una curva de aprendizaje más larga para el grupo.
- **TypeScript con NestJS:** serviría también para una interfaz web en el TP3, pero obliga a aprender dos cosas nuevas a la vez: el lenguaje y el framework.

## Consecuencias

- El formato de errores `problem+json` (RFC 9457) se arma a mano, con un manejador de errores común para toda la API.
- FastAPI impone poca estructura, así que el proyecto sigue una organización fija: `routers`, `schemas`, `models`, `services` y `core`.

## Respuesta de la cátedra

Pendiente. Anotar acá la fecha y la respuesta.
