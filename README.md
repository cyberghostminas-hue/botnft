# IT Company · bot de Telegram (aiogram 3)

Juego idle de empresa de informática dentro del chat, con cartera de Bits, referidos y retiros en CUP a tarjeta Bandec.

## Instalar y correr
    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env   # rellénalo
    set -a; source .env; set +a
    python test_core.py    # pruebas del motor y la cartera
    python bot.py

Déjalo corriendo con systemd o Docker en un VPS (el bot usa polling: no necesita dominio ni HTTPS).

## Archivos
- engine.py  Motor del juego (puro): departamentos, contratar, mejorar, edificio 2, mejoras globales, prestigio, ingreso offline (máx. 8 h).
- store.py   SQLite: usuarios, estado, libro de Bits (solo se agrega), referidos, retiros, tarjeta cifrada AES-256-GCM.
- bot.py     Interfaz con aiogram: menús con botones, retiro por pasos, comandos de admin.
- test_core.py

## Comandos de admin (solo ADMIN_IDS)
/pendientes · /pagado ID · /rechazar ID motivo · /ledger USER_ID · /ban USER_ID · /unban USER_ID

## Flujo de dinero
Prestigio → puntos → Bits (tope diario + enfriamiento) → solicitud de retiro (mín. CUP, 1 pendiente, límite diario)
→ tú ves la tarjeta en /pendientes, transfieres desde tu banca y escribes /pagado ID. Si rechazas, los Bits vuelven solos.

## Seguridad
- Solo se pide el número de tarjeta (16 dígitos). Nunca PIN, claves ni códigos de verificación; el bot borra el mensaje con la tarjeta.
- El estado vive en el servidor: el jugador solo toca botones, no puede editar su dinero.
- Antispam por usuario (~3 acciones/s) y cuentas bloqueables.

## Pendiente (v0.2)
Decoración, eventos/desgracias, ofertas de trabajo, minijuegos y contratos del juego original; misiones de canal patrocinado; música (los MP3 del APK no se pueden reproducir como juego, pero sí enviar como audio); respaldo automático de la base.
Probar con jugadores reales cuánto tarda el primer prestigio (2e13 generados) y ajustar DAILY_BITS_CAP / CUP_PER_BIT.
