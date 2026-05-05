# FreeAgent_IA

Agente de automatización con IA que genera y ejecuta scripts Python de forma autónoma, con notificaciones via Telegram.

Describe en lenguaje natural lo que quieres que haga cada tarea. El agente llama al modelo de IA, genera el script Python, lo ejecuta, verifica el resultado y lo reintenta si falla — sin intervención manual.

## Requisitos

- Python 3.10+
- [Ollama](https://ollama.com/download) instalado y en ejecución — opcional si solo usas Google AI Studio
- API key de [Google AI Studio](https://aistudio.google.com) — opcional si solo usas Ollama
- Bot de Telegram con token y chat_id — opcional

## Instalación

```
Instalar_dependencias.bat
```

O manualmente:

```
pip install -r requirements.txt
```

## Uso

```
py agente.py        # solo el agente (consola)
py gui.py           # interfaz gráfica
Lanzar.bat          # equivalente a py agente.py
```

> En Windows, el intérprete correcto es `py`, no `python` (que puede apuntar al Microsoft Store).

## Configuración

La configuración está dividida en dos ficheros YAML en la carpeta `config/`:

| Fichero | Contenido |
|---|---|
| `config/config.yaml` | Modelo, Telegram, logging, opciones Ollama, prompts del sistema |
| `config/tareas.yaml` | Definición de las tareas automatizadas |

Edítalos desde la GUI (sección *Config* / *Tareas*) o directamente como texto plano.

### config/config.yaml

```yaml
# powerbot:config
modelo: "qwen2.5-coder:7b"    # Modelo principal (nombre:tag para Ollama, gemini-* para Google)
modelo_fallback: "gemini-2.5-flash-lite"
api_key: ""                    # Solo necesaria para modelos gemini-*
telegram_token: ""
telegram_chat_id: ""
telegram_activo: true
telegram_intervalo: 300        # Segundos mínimos entre notificaciones
log_path: logs\agente.log
log_prompt: false
log_respuesta: false
log_comandos: false
log_salida: false
ollama_options:
  temperature: 0.1
  num_ctx: 8192
  num_gpu: -1                  # -1 = usar GPU automáticamente
prompts_sistema:
  - Eres un agente de automatización en Windows...
prompts_verificador:
  - El resultado contiene datos reales y no está vacío.
```

### config/tareas.yaml

```yaml
# powerbot:tareas
tareas:
  nombre_tarea:
    programacion:
      tipo: intervalo          # "intervalo" | "diario" | "semanal"
      valor: 3600              # segundos (solo para tipo=intervalo)
      hora: "08:00"            # HH:MM (para tipo=diario o semanal)
      dias: [lun, mie, vie]    # (solo para tipo=semanal)
    timeout_ollama: 300        # Opcional: sobreescribe el global de config.yaml
    timeout_script: 60         # Opcional: sobreescribe el global
    max_reintentos: 3          # Opcional: sobreescribe el global
    prompt:
      - Línea 1 del prompt
      - Línea 2 del prompt
```

## Modelos de IA

### Ollama (local, gratuito)

Ejecuta modelos en tu propio ordenador. Consulta el catálogo completo en [ollama.com/library](https://ollama.com/library).

| Hardware | Modelos recomendados |
|---|---|
| GPU con 4 GB VRAM | Modelos hasta ~7B parámetros en Q4 |
| GPU con 8 GB VRAM | Modelos hasta ~13B parámetros |
| Solo CPU / RAM abundante | Cualquier tamaño, pero lento |

Instala modelos desde la GUI (sección *Config → Modelos Ollama*) o con:

```
ollama pull nombre:tag
```

### Google AI Studio (nube, requiere API key)

Usa modelos `gemini-*`. Tier gratuito disponible en [aistudio.google.com](https://aistudio.google.com).  
Configura la `api_key` en `config/config.yaml`. El modelo fallback por defecto es `gemini-2.5-flash-lite`.

## Cómo funciona

1. Lee `config/tareas.yaml` con hot-reload (detecta cambios sin reiniciar)
2. Por cada tarea, cuando llega su momento según `programacion`:
   - Calcula MD5 del prompt — si coincide con el `.hash` en caché, reutiliza el script guardado
   - Si no hay caché válida, llama al modelo para generar el script Python
   - Ejecuta el script con timeout en un proceso hijo
   - Verifica el resultado en la misma conversación (el modelo juzga si la salida es correcta)
   - Si falla: pide corrección al modelo (hasta `max_reintentos`)
   - Si timeout o agota reintentos: usa `modelo_fallback`
   - Notifica el resultado por Telegram

## Planificación de tareas

| tipo | comportamiento |
|---|---|
| `intervalo` | cada N segundos |
| `diario` | a una hora HH:MM fija cada día |
| `semanal` | a una hora HH:MM en días concretos de la semana |

## Caché de scripts

- El MD5 del prompt es la clave de caché — cambiar el prompt invalida el caché de esa tarea
- Si un script falla en ejecución: se borra el caché y se regenera en el mismo ciclo
- Para forzar regeneración: borrar `scripts_cache/<tarea>.py` y `scripts_cache/<tarea>.hash`
- Los scripts cacheados incluyen en la primera línea el modelo que los generó y la fecha

## Estructura del proyecto

| Archivo | Descripción |
|---|---|
| `agente.py` | Bucle principal: lee YAML, gestiona tareas, caché, reintentos y Telegram |
| `funciones.py` | Funciones auxiliares: log, Telegram, YAML, modelos, generación, verificación, ejecución |
| `gui.py` | Interfaz gráfica (customtkinter) |
| `gui_views/dashboard.py` | Vista principal: estado de tareas y última ejecución |
| `gui_views/log_viewer.py` | Vista del log en tiempo real |
| `gui_views/yaml_editor.py` | Editor integrado de config y tareas |
| `gui_views/cache_manager.py` | Gestión de scripts en caché |
| `config/config.yaml` | Configuración global |
| `config/tareas.yaml` | Definición de tareas |
| `scripts_cache/` | Scripts Python generados por el modelo |
| `logs/agente.log` | Estado actual (se sobreescribe en cada ciclo) |
| `logs/agente_history.log` | Log histórico completo (rota a 10 MB) |
