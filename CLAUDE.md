# PowerBot — Agente de automatizacion con IA

Agente Python que usa modelos de IA (Ollama local o Google Gemini) para generar y ejecutar scripts Python de forma autonoma,
con notificaciones via Telegram.

## Archivos del proyecto

| Archivo | Descripcion |
|---|---|
| `agente.py` | Bucle principal. Lee YAML, gestiona tareas, cache, reintentos y Telegram |
| `funciones.py` | Funciones auxiliares: log, Telegram, YAML, modelos, generacion, verificacion, ejecucion |
| `gui.py` | Interfaz grafica (customtkinter). Sidebar con navegacion, inicio/parada del agente |
| `gui_views/dashboard.py` | Vista principal: estado de tareas, ultima ejecucion, etc. |
| `gui_views/log_viewer.py` | Vista del log en tiempo real |
| `gui_views/yaml_editor.py` | Editor de tareas.yaml integrado |
| `gui_views/cache_manager.py` | Gestion de scripts en cache |
| `gui_views/modelos.py` | Vista de modelos Ollama instalados |
| `tareas.yaml` | Configuracion global + definicion de tareas con sus prompts |
| `estado.json` | Persiste la fecha/hora del ultimo exito de cada tarea (auto-generado) |
| `scripts_cache/` | Scripts Python generados por el modelo, uno por tarea (.py + .hash MD5) |
| `logs/agente.log` | Log de estado actual (se sobreescribe con `refrescar_log`) |
| `logs/agente_history.log` | Log historico completo, solo rota por tamaño (max 10 MB) |
| `Lanzar.bat` | Lanzador del agente (usa `py`) |
| `Instalar_dependencias.bat` | Instala paquetes de requirements.txt con `py -m pip install -r` |
| `requirements.txt` | Dependencias Python: pyyaml, requests, psutil, customtkinter |
| `.vscode/tasks.json` | Tasks de VS Code: Ejecutar agente, Ejecutar GUI, Instalar dependencias |
| `.vscode/launch.json` | Configuraciones de debug: GUI y Agente |

## Como funciona

1. Lee `tareas.yaml` (hot-reload si cambia el archivo sin reiniciar)
2. Por cada tarea, cuando se cumple su `intervalo` en segundos:
   - Calcula MD5 del prompt completo — si coincide con el `.hash` en cache, usa el script cacheado
   - Si no hay cache valida, llama al modelo via API chat para generar el script
   - Ejecuta el script en un proceso hijo con timeout (fichero temporal en `/tmp`)
   - Verifica el resultado en la misma conversacion donde se genero el script (el modelo ve la salida real y juzga si es correcta)
   - Si falla: pide correccion al modelo (hasta `max_reintentos`)
   - Si timeout al generar: salta directamente al `modelo_fallback`
   - Si agota reintentos: usa `modelo_fallback`
   - Notifica resultado por Telegram con la salida del script
3. El log principal (`agente.log`) actua como tablon de estado: `refrescar_log` lo sobreescribe con el ultimo resultado de cada tarea. El historial completo va a `agente_history.log`.
4. Los scripts cacheados incluyen comentario con el modelo que los genero y la fecha.

## Router de modelos (llamar_modelo_chat)

- Modelos cuyo nombre empieza por `gemini-` → API REST de Google Gemini (`generativelanguage.googleapis.com`)
- El resto → Ollama local (`http://localhost:11434/api/chat`)
- La `api_key` se configura en `tareas.yaml`. El repo es local (sin remote git), no hay riesgo de exposicion.
- `ollama_options` (temperature, num_ctx, etc.) solo aplican a modelos Ollama; se ignoran silenciosamente para Gemini.

## Arquitectura de conversacion

Usa API chat (historial de mensajes) para mantener contexto:

```
Turno 1 (user)      → prompt de la tarea → genera script Python
                      ejecutar el script
Turno 2 (user)      → "el resultado fue: [salida]. ¿Es correcto?" → OK / ERROR
                      si ERROR → reintento con contexto del error
```

El modelo recuerda el contexto de lo que tenia que hacer al verificar el resultado.
La verificacion se ejecuta mediante `verificar_resultado_chat` en `funciones.py`.

## PROMPTS_SISTEMA_FIJOS (agente.py)

Lista definida en `agente.py` con reglas tecnicas que se inyectan **siempre** en todos los prompts,
independientemente de lo que haya en `tareas.yaml`. El autor de tareas no necesita conocerlas.

Actualmente incluye:
- No mezclar `capture_output=True` con `stdout=`/`stderr=` en subprocess.run(). Usar `text=True` y nunca `.decode()`.

Para anadir nuevas restricciones tecnicas recurrentes, editar `PROMPTS_SISTEMA_FIJOS` en `agente.py`,
**no** `tareas.yaml`.

## tareas.yaml — estructura

```yaml
modelo: qwen2.5-coder:7b           # Modelo principal (gemini-* = Google API, resto = Ollama local)
modelo_fallback: gemini-2.5-flash-lite  # Fallback si timeout o max_reintentos
api_key: "..."              # Solo necesaria si modelo empieza por gemini-
telegram_token: ...
telegram_chat_id: "..."
log_path: logs\agente.log
max_reintentos: 3
timeout_ollama: 500                # Segundos max para que el modelo responda
timeout_script: 120                # Segundos max para ejecutar el script generado
log_prompt:    false               # Loguear prompt enviado al modelo
log_respuesta: false               # Loguear respuesta completa del modelo
log_comandos:  false               # Loguear el script antes de ejecutarlo
log_salida:    false               # Loguear salida linea a linea

# Requisitos de dominio inyectados en todos los prompts (lista)
# NO incluir reglas tecnicas de Python aqui — van en PROMPTS_SISTEMA_FIJOS de agente.py
prompts_sistema:
  - Eres un agente de automatizacion en Windows. Genera solo scripts Python 3.
  - ...

# Verificadores: el modelo juzga si el resultado de ejecutar el script es correcto
prompts_verificador:
  - El resultado contiene datos reales y no esta vacio.
  - ...

tareas:
  nombre_tarea:
    intervalo: 60          # Segundos entre ejecuciones
    timeout_ollama: 300    # Opcional: sobreescribe el global
    timeout_script: 60     # Opcional: sobreescribe el global
    prompt_verificador: "verificacion especifica de esta tarea"  # Opcional
    prompt:
      - Linea 1 del prompt
      - Linea 2 del prompt
```

## Cache de scripts

- Al cambiar cualquier linea de `prompt` en el YAML, el MD5 cambia → cache miss → el modelo regenera
- Si un script en cache falla en ejecucion: se borra la cache y se regenera desde cero en el mismo ciclo
- Para forzar regeneracion manual: borrar `scripts_cache/<tarea>.py` y `scripts_cache/<tarea>.hash`
- Primera linea del .py cacheado: `# Generado por: <modelo> | <fecha>`

## Tareas configuradas

| Tarea | Intervalo | Descripcion |
|---|---|---|
| `backup_origen` | 3600s | Sincroniza C:\Proba_Agent_IA\Origen con robocopy /MIR, log en destino |
| `monitor_sistema` | 120s | CPU% con psutil.cpu_percent y RAM en GB con psutil.virtual_memory |
| `listar_directorio_NAS` | 120s | Lista /etc/ix2panel via ssh.exe con clave ~/.ssh/ix2panel_key |
| `top_procesos` | 300s | Top 5 procesos por CPU y por RAM, con aviso si superan umbrales |
| `resumen_diario` | 86400s | Espacio en C: y NAS, RAM, uptime, programas con >1GB RAM |
| `directorios_mas_grandes` | 600s | Top 10 carpetas de C: por tamaño en GB |
| `Artemis_II` | 60s | Consulta cuando volvieron los astronautas del vuelo Artemis 2 |

## SSH al NAS (192.168.1.196)

- Clave privada: `~/.ssh/ix2panel_key`
- Config en `~/.ssh/config` con StrictHostKeyChecking=no
- Usuario: jordi

## Lanzar el agente

```
py agente.py
```

O usar `Lanzar.bat`.  
El interprete correcto en este sistema es `py`, no `python` (que apunta al Microsoft Store).

## Hardware

### PC actual (i5-11400H) — maquina de desarrollo y ejecucion
- CPU: Intel Core i5-11400H (11a gen) — 6 nucleos / 12 hilos @ 2.70 GHz
- RAM: 16 GB DDR4 @ 3200 MHz (2x8GB)
- GPU: NVIDIA GeForce RTX 2050 (4 GB VRAM)
- OS: Windows 11 Pro
- Modelos viables en GPU: hasta 7B en Q4 caben en 4GB VRAM (`num_gpu: -1`)
- Modelos 14B: posible en modo mixto CPU+GPU (`num_gpu: ~20`)

### NAS (ix2panel)
- IP: 192.168.1.196
- Acceso SSH con usuario jordi y clave ~/.ssh/ix2panel_key
- No corre Ollama

## Modelo fallback

- Se activa si: timeout generando el script O agota `max_reintentos` ejecutando
- Actualmente: `gemini-2.5-flash-lite` (Google API, bajo consumo de tokens)
- Si el fallback tiene exito, el script se guarda en cache con el modelo fallback como autor

## Funciones clave en funciones.py

| Funcion | Descripcion |
|---|---|
| `llamar_ollama_chat` | POST a `/api/chat` con historial de mensajes. Barra de progreso. Devuelve texto o None |
| `llamar_gemini_chat` | POST a la API de Gemini. Convierte formato `{role,content}` a formato Gemini. Devuelve texto o None |
| `llamar_modelo_chat` | Router: si el modelo empieza por `gemini-` llama a Gemini, si no a Ollama |
| `extraer_script` | Extrae bloque ` ```python``` ` de la respuesta. Elimina bloques `<think>` antes de buscar |
| `generar_script` | Construye la conversacion, llama al modelo. Devuelve `{script, mensajes}` o None |
| `verificar_resultado_chat` | Continua la conversacion con la salida real del script. Devuelve `{ok, razon}` |
| `ejecutar_script` | Valida sintaxis, escribe fichero temporal, ejecuta con subprocess y timeout. Devuelve `{exito, error, exit_code, salida}` |
| `leer_yaml` | Usa pyyaml (`yaml.safe_load`). Devuelve `{config, tareas}` |
| `validar_config` | Comprueba campos obligatorios y tipos. Lanza ValueError con todos los errores si falla |

## Historial de cambios importantes (conversaciones anteriores)

### 2026-04-01 — Bugs en el flujo de reintentos
- `generar_script` con `error_anterior` creaba conversacion nueva perdiendo el contexto. Fix: parametro `mensajes_anteriores` para continuar la conversacion existente.
- `verificar_resultado_chat` devolvia solo `False`. Cambiado a `{ok, razon}` para pasar el motivo al reintento.

### 2026-04-01 — Cache y robocopy
- El hash MD5 de cache es **por tarea e independiente** — cambiar el prompt de una tarea no invalida el cache de las demas.
- Bug robocopy: log dentro del directorio destino + /MIR causaba error 32. Fix: anadir `/XF robocopy.log` al prompt de `backup_origen`.

### 2026-04-03 — Verificador permisivo
- El verificador aprobaba scripts con errores evidentes. Fix en `prompts_verificador`: palabras clave concretas que fuerzan respuesta ERROR.

### 2026-04-04 — Parser YAML, planificacion, verificacion
- `leer_yaml` usa pyyaml (`yaml.safe_load`). Los booleans se leen nativos.
- Nueva funcion `validar_config`: valida campos obligatorios al inicio y aborta con mensaje claro.
- Planificacion por `next_run`: el sleep es inteligente (duerme hasta la proxima tarea, max 30s para hot-reload).
- `verificar_resultado_chat` con timeout devuelve `{ok: False}` para forzar reintento.

### 2026-04-05 — Modelos, Telegram y bugfixes
- `ejecutar_script`: retorno por timeout incluye siempre la clave `salida`.
- Modelo principal: `qwen2.5-coder:7b` (Ollama local). Fallback: `gemini-2.5-flash-lite`.
- `num_gpu: -1` en ollama_options (GPU RTX 2050 disponible).
- Todas las notificaciones Telegram activadas (inicio, exito con cambios, fallback, fallo).

### 2026-04-12 — PROMPTS_SISTEMA_FIJOS y GUI
- Migrado completamente de PowerShell a Python.
- Creada GUI con customtkinter (`gui.py` + `gui_views/`).
- Creado `PROMPTS_SISTEMA_FIJOS` en `agente.py`: reglas tecnicas de Python inyectadas siempre en los prompts sin necesidad de ponerlas en tareas.yaml. Actualmente: uso correcto de subprocess.run con capture_output.
- `.vscode/tasks.json` y `launch.json` creados. Tasks usan `py` (no `python`).
- `Instalar_dependencias.bat` para instalar requirements.txt con un doble clic.

### Nota sobre historial de sesiones
- El repo git es local sin remote configurado (`git remote -v` devuelve vacio).
- El interprete Python en este sistema es `py`, no `python`.
