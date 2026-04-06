"""funciones.py - Funciones auxiliares del agente PowerBot (Python)

Funciones:
  escribir_log           -> guarda mensajes con timestamp en el log
  enviar_telegram        -> manda mensajes al bot de Telegram
  leer_yaml              -> parsea tareas.yaml con pyyaml
  validar_config         -> valida campos obligatorios y tipos
  llamar_ollama_chat     -> POST a Ollama /api/chat con historial
  llamar_gemini_chat     -> POST a Google Gemini API con historial
  llamar_modelo_chat     -> router: Gemini si empieza por "gemini-", si no Ollama
  extraer_script         -> extrae bloque ```python``` de la respuesta
  generar_script         -> llama al modelo y devuelve {script, mensajes}
  verificar_resultado    -> continua la conversacion para verificar el resultado
  ejecutar_script        -> ejecuta el .py en proceso hijo con timeout
"""

import os
import re
import sys
import time
import datetime
import tempfile
import subprocess
import threading
from typing import Optional

import yaml
import requests


# =============================================================================
# Escribir-Log
# =============================================================================

def escribir_log(mensaje: str, log_path: str, max_log_mb: int = 10,
                 con_timestamp: bool = False, no_newline: bool = False):
    carpeta = os.path.dirname(log_path)
    if carpeta and not os.path.exists(carpeta):
        os.makedirs(carpeta, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    linea = f"[{timestamp}] {mensaje}" if con_timestamp else mensaje

    if no_newline:
        print(linea, end="", flush=True)
    else:
        print(linea)

    _append_log(log_path, linea, max_log_mb)
    _append_log(log_path.replace(".log", "_history.log"),
                f"[{timestamp}] {mensaje}", max_log_mb)


def _append_log(path: str, linea: str, max_log_mb: int):
    if os.path.exists(path) and os.path.getsize(path) / (1024 * 1024) >= max_log_mb:
        rotado = path.replace(".log", f"_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        os.rename(path, rotado)
    with open(path, "a", encoding="utf-8") as f:
        f.write(linea + "\n")


# =============================================================================
# Enviar-Telegram
# =============================================================================

def enviar_telegram(mensaje: str, token: str, chat_id: str, log_path: str):
    if not token or not chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, data={"chat_id": chat_id, "text": mensaje}, timeout=10)
    except Exception as e:
        escribir_log(f"ADVERTENCIA: No se pudo enviar Telegram: {e}", log_path)


def publicar_resultados_telegram(ultimos_resultados: dict, tareas: dict,
                                  token: str, chat_id: str,
                                  state_path: str, log_path: str):
    """Borra todos los mensajes de resultado anteriores y reenvia uno por tarea en orden."""
    if not token or not chat_id:
        return

    import json as _json

    base = f"https://api.telegram.org/bot{token}"

    # 1. Leer IDs anteriores y borrarlos todos
    ids_anteriores = {}
    try:
        if os.path.exists(state_path):
            with open(state_path, "r", encoding="utf-8") as f:
                ids_anteriores = _json.load(f)
    except Exception:
        pass

    for msg_id in ids_anteriores.values():
        try:
            requests.post(f"{base}/deleteMessage",
                          json={"chat_id": chat_id, "message_id": msg_id},
                          timeout=10)
        except Exception:
            pass

    # 2. Enviar un mensaje por cada tarea en orden
    nuevos_ids = {}
    for nombre in tareas:
        resultado = ultimos_resultados.get(nombre, "")
        if resultado.startswith("OK"):
            partes = resultado.split("\n", 1)
            cuerpo  = partes[1].strip() if len(partes) > 1 else ""
            texto   = f"✅ {nombre}\n{cuerpo}" if cuerpo else f"✅ {nombre}"
        elif resultado.startswith("ERR"):
            partes = resultado.split("\n", 1)
            cuerpo  = partes[1].strip() if len(partes) > 1 else partes[0]
            texto   = f"❌ {nombre}\n{cuerpo}"
        else:
            texto = f"⏳ {nombre}"

        try:
            r = requests.post(f"{base}/sendMessage",
                              json={"chat_id": chat_id, "text": texto},
                              timeout=10)
            if r.status_code == 200:
                nuevos_ids[nombre] = r.json()["result"]["message_id"]
        except Exception as e:
            escribir_log(f"ADVERTENCIA: Telegram {nombre}: {e}", log_path)

    # 3. Guardar nuevos IDs
    try:
        with open(state_path, "w", encoding="utf-8") as f:
            _json.dump(nuevos_ids, f)
    except Exception:
        pass


# =============================================================================
# Leer-Yaml
# =============================================================================

def leer_yaml(config_path: str, tareas_path: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    if not config:
        raise ValueError(f"config.yaml vacio o malformado: '{config_path}'")
    with open(tareas_path, "r", encoding="utf-8") as f:
        raw_tareas = yaml.safe_load(f)
    tareas = (raw_tareas or {}).get("tareas") or {}
    return {"config": config, "tareas": tareas}


# =============================================================================
# Validar-Config
# =============================================================================

def validar_config(cfg: dict, tareas: dict):
    errores = []
    if not cfg.get("modelo"):
        errores.append("Falta el campo 'modelo'")
    if not cfg.get("modelo_fallback"):
        errores.append("Falta 'modelo_fallback'")
    if not cfg.get("telegram_chat_id"):
        errores.append("Falta 'telegram_chat_id'")
    if not tareas:
        errores.append("No hay tareas definidas en la seccion 'tareas:'")
    for nombre, t in tareas.items():
        if not t.get("prompt"):
            errores.append(f"Tarea '{nombre}': falta 'prompt'")
        elif not isinstance(t["prompt"], list):
            errores.append(f"Tarea '{nombre}': 'prompt' debe ser una lista YAML (items con '- ')")
        intervalo = t.get("intervalo")
        if intervalo is not None:
            if not isinstance(intervalo, int):
                errores.append(f"Tarea '{nombre}': 'intervalo' debe ser un entero (es: {intervalo})")
            elif intervalo <= 0:
                errores.append(f"Tarea '{nombre}': 'intervalo' debe ser positivo (es: {intervalo})")
    if errores:
        raise ValueError("Errores de configuracion en tareas.yaml:\n" + "\n".join(errores))


# =============================================================================
# _llamar_con_timeout  (interno)
# =============================================================================

def _llamar_con_timeout(url: str, body: dict, modelo: str, log_path: str,
                        timeout_segundos: int, extract_fn,
                        timeout_msg: str, error_prefix: str) -> Optional[str]:
    result = [None]
    error  = [None]

    def do_request():
        try:
            r = requests.post(url, json=body, timeout=timeout_segundos + 120)
            result[0] = extract_fn(r.json())
        except Exception as e:
            error[0] = str(e)

    t = threading.Thread(target=do_request, daemon=True)
    t.start()

    inicio  = time.time()
    bar_len = 30
    while t.is_alive():
        elapsed = time.time() - inicio
        if elapsed >= timeout_segundos:
            escribir_log(timeout_msg, log_path)
            print()
            return None
        filled = int((elapsed / timeout_segundos) * bar_len)
        bar    = "#" * filled + "-" * (bar_len - filled)
        print(f"\r[{modelo}] {int(elapsed)}s/{timeout_segundos}s [{bar}]   ", end="", flush=True)
        time.sleep(1)
    print()

    t.join()
    segundos = round(time.time() - inicio, 1)

    if result[0] is not None:
        escribir_log(f"{modelo} respondio en {segundos}s.", log_path)
        return result[0]
    err = error[0] or "Sin respuesta"
    escribir_log(f"{error_prefix}: {err}", log_path)
    return None


# =============================================================================
# Llamar-OllamaChat
# =============================================================================

def llamar_ollama_chat(modelo: str, messages: list, log_path: str,
                       timeout_segundos: int = 300,
                       opciones: Optional[dict] = None) -> Optional[str]:
    body = {"model": modelo, "messages": messages, "stream": False}
    if opciones:
        body["options"] = opciones

    return _llamar_con_timeout(
        url="http://localhost:11434/api/chat",
        body=body,
        modelo=modelo,
        log_path=log_path,
        timeout_segundos=timeout_segundos,
        extract_fn=lambda r: r["message"]["content"],
        timeout_msg=f"Ollama supero el timeout de {timeout_segundos}s. Proceso terminado.",
        error_prefix=f"Error llamando al modelo de Ollama {modelo}",
    )


# =============================================================================
# Llamar-GeminiChat
# =============================================================================

def llamar_gemini_chat(modelo: str, messages: list, api_key: str,
                       log_path: str, timeout_segundos: int = 300) -> Optional[str]:
    contents = []
    for msg in messages:
        role = "model" if msg["role"] == "assistant" else msg["role"]
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})

    body = {
        "contents": contents,
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 4000},
    }
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{modelo}:generateContent?key={api_key}")

    return _llamar_con_timeout(
        url=url,
        body=body,
        modelo=modelo,
        log_path=log_path,
        timeout_segundos=timeout_segundos,
        extract_fn=lambda r: r["candidates"][0]["content"]["parts"][0]["text"],
        timeout_msg=f"Gemini supero el timeout de {timeout_segundos}s.",
        error_prefix=f"Error llamando al modelo Gemini {modelo}",
    )


# =============================================================================
# Llamar-ModeloChat  (router)
# =============================================================================

def llamar_modelo_chat(modelo: str, messages: list, api_key: str = "",
                       log_path: str = "", timeout_segundos: int = 300,
                       opciones: Optional[dict] = None) -> Optional[str]:
    _GOOGLE_API = ("gemini-", "gemma-")
    if modelo.startswith(_GOOGLE_API):
        return llamar_gemini_chat(modelo, messages, api_key, log_path, timeout_segundos)
    return llamar_ollama_chat(modelo, messages, log_path, timeout_segundos, opciones)


# =============================================================================
# Extraer-Script
# =============================================================================
# Clasificar-Error
# =============================================================================

_HINTS_ERROR = [
    (r"may not be used with capture_output",
     "No combines capture_output=True con stdout= o stderr= explicitos."),
    (r"'NoneType'.*attribute|NoneType.*has no attribute",
     "Accedes a una variable que es None. Verifica que capturas stdout/stderr con capture_output=True, text=True antes de usarlos."),
    (r"PermissionError",
     "Hay rutas sin permisos de acceso. Captura PermissionError en el except y continua con las demas entradas."),
    (r"FileNotFoundError|WinError 2",
     "Un comando o fichero no existe en Windows. No uses comandos Linux (du, ls, grep...). Usa os, pathlib o psutil."),
    (r"unexpected keyword argument",
     "Estas usando un argumento que no existe en esa funcion. Consulta la firma correcta de la API."),
    (r"stdout and stderr arguments",
     "capture_output=True ya captura stdout y stderr. No añadas stdout= ni stderr= cuando uses capture_output=True."),
    (r"cannot find the file|sistema no puede encontrar",
     "El ejecutable o ruta no existe en Windows. Verifica que el comando es valido en Windows."),
    (r"no se pudo obtener|no tengo informacion|Error al ejecutar el comando",
     "No tienes acceso a esa informacion. No inventes comandos ni busquedas. Imprime directamente 'Error: no tengo informacion suficiente para responder.' y termina con sys.exit(1)."),
]

def clasificar_error(error: str) -> str:
    """Analiza el error y devuelve un hint especifico para guiar la correccion."""
    for patron, hint in _HINTS_ERROR:
        if re.search(patron, error, re.IGNORECASE):
            return f"\nHint: {hint}"
    return ""


# =============================================================================
# Sanear-Script
# =============================================================================

def sanear_script(script: str, log_path: str) -> str:
    """Corrige automaticamente patrones problematicos conocidos en scripts generados."""
    original = script

    # Si el script accede a result.stdout/stderr pero no los captura, añadir capture_output=True
    accede_salida  = "result.stdout" in script or "result.stderr" in script
    captura_stdout = "capture_output=True" in script or "stdout=subprocess.PIPE" in script
    captura_stderr = "capture_output=True" in script or "stderr=subprocess.PIPE" in script
    if accede_salida and not captura_stdout:
        script = re.sub(r"\btext\s*=\s*True", "capture_output=True, text=True", script)
        script = re.sub(r",\s*stderr\s*=\s*subprocess\.DEVNULL", "", script)
        script = re.sub(r"stderr\s*=\s*subprocess\.DEVNULL\s*,\s*", "", script)
    # Si accede a result.stderr pero stderr esta descartado con DEVNULL, capturarlo
    if "result.stderr" in script and not captura_stderr:
        script = re.sub(r"stderr\s*=\s*subprocess\.DEVNULL", "stderr=subprocess.PIPE", script)
    # Si stdout=PIPE pero falta text=True, añadirlo
    if "stdout=subprocess.PIPE" in script and "text=True" not in script:
        script = re.sub(r"stdout\s*=\s*subprocess\.PIPE", "stdout=subprocess.PIPE, text=True", script)

    if "capture_output=True" in script:
        # capture_output=True es incompatible con stdout= y stderr= explicitos
        script = re.sub(r",\s*stderr\s*=\s*subprocess\.(DEVNULL|PIPE|STDOUT)", "", script)
        script = re.sub(r"stderr\s*=\s*subprocess\.(DEVNULL|PIPE|STDOUT)\s*,\s*", "", script)
        script = re.sub(r",\s*stdout\s*=\s*subprocess\.(PIPE|DEVNULL)",           "", script)
        script = re.sub(r"stdout\s*=\s*subprocess\.(PIPE|DEVNULL)\s*,\s*",        "", script)

    # .decode() es innecesario con text=True
    script = re.sub(r'\.decode\(["\']utf-?8["\']\)', "", script)
    script = re.sub(r'\.decode\(\)',                  "", script)

    # Auto-añadir imports que faltan
    imports_necesarios = {
        "sys":        r'\bsys\.',
        "os":         r'\bos\.',
        "subprocess": r'\bsubprocess\.',
        "datetime":   r'\bdatetime\.',
        "json":       r'\bjson\.',
        "re":         r'\bre\.',
    }
    lineas = script.splitlines()
    imports_existentes = "\n".join(l for l in lineas if l.startswith("import ") or l.startswith("from "))
    nuevos_imports = []
    for modulo, patron in imports_necesarios.items():
        if re.search(patron, script) and f"import {modulo}" not in imports_existentes:
            nuevos_imports.append(f"import {modulo}")
    if nuevos_imports:
        script = "\n".join(nuevos_imports) + "\n" + script

    if script != original:
        escribir_log("Script saneado: se corrigieron patrones problematicos.", log_path)

    return script


# =============================================================================

def extraer_script(respuesta: str, log_path: str) -> Optional[str]:
    respuesta = re.sub(r"(?s)<think>.*?</think>", "", respuesta)

    patrones = [
        r"(?s)```python\s*\n(.*?)```",
        r"(?s)```\s*\n(.*?)```",
        r"(?s)```python\s*\n(.*)",
        r"(?s)```\s*\n(.*)",
    ]
    script_extraido = None
    for patron in patrones:
        for m in re.finditer(patron, respuesta):
            candidato = m.group(1).strip()
            if script_extraido is None or len(candidato) > len(script_extraido):
                script_extraido = candidato
        if script_extraido:
            break

    if script_extraido:
        lineas = [l for l in script_extraido.split("\n") if not l.startswith("```")]
        script_extraido = "\n".join(lineas).strip()
        escribir_log(f"Script extraido correctamente ({len(script_extraido)} chars).", log_path)
        return script_extraido

    escribir_log("ERROR: No se encontro bloque de codigo en la respuesta.", log_path)
    return None


# =============================================================================
# Generar-Script
# =============================================================================

def generar_script(modelo: str, prompt: str = "", error_anterior: str = "",
                   script_anterior: str = "", mensajes_anteriores: Optional[list] = None,
                   log_path: str = "", api_key: str = "", log_prompt: bool = False,
                   log_respuesta: bool = False, timeout_segundos: int = 300,
                   opciones: Optional[dict] = None) -> Optional[dict]:

    if error_anterior:
        user_content = (
            f"El siguiente script de Python fallo con este error:\n{error_anterior}\n\n"
            f"Script que fallo:\n{script_anterior}\n\n"
            "Corrige el script. Responde solo con el bloque ```python```."
        )
        messages = list(mensajes_anteriores) if mensajes_anteriores else []
    else:
        user_content = prompt
        messages = []

    if log_prompt:
        escribir_log(">>> PROMPT AL MODELO:", log_path)
        for linea in user_content.split("\n"):
            escribir_log(f"    {linea}", log_path)

    messages.append({"role": "user", "content": user_content})

    respuesta = llamar_modelo_chat(modelo, messages, api_key, log_path,
                                   timeout_segundos, opciones)
    if not respuesta:
        return None

    if log_respuesta:
        escribir_log("<<< RESPUESTA MODELO:", log_path)
        for linea in respuesta.split("\n"):
            escribir_log(f"    {linea}", log_path)

    script = extraer_script(respuesta, log_path)
    if not script:
        return None
    script = sanear_script(script, log_path)

    messages.append({"role": "assistant", "content": respuesta})
    return {"script": script, "mensajes": messages}


# =============================================================================
# Verificar-Resultado-Chat
# =============================================================================

def verificar_resultado_chat(mensajes: list, salida: str, modelo: str,
                             log_path: str, api_key: str = "",
                             prompt_verificador: str = "",
                             timeout_segundos: int = 120,
                             opciones: Optional[dict] = None) -> dict:
    if not mensajes or not prompt_verificador:
        return {"ok": True}

    salida_texto = salida if salida else "(sin salida)"
    pregunta = (
        f"He ejecutado el script y este es el resultado:\n{salida_texto}\n\n"
        f"{prompt_verificador}\n"
        "Responde unicamente OK si el resultado es correcto, "
        "o ERROR seguido de la explicacion si no lo es."
    )

    msgs = list(mensajes)
    msgs.append({"role": "user", "content": pregunta})

    escribir_log("Verificando resultado en misma conversacion...", log_path)
    respuesta = llamar_modelo_chat(modelo, msgs, api_key, log_path,
                                   timeout_segundos, opciones)

    if not respuesta:
        escribir_log(
            "Verificacion resultado: timeout. No se puede verificar - se trata como fallo.",
            log_path)
        return {"ok": False, "razon": "Timeout en la verificacion: resultado no verificado"}

    resumen = respuesta[:300]
    escribir_log(f"Verificacion resultado: {resumen}", log_path)

    tiene_ok    = bool(re.search(r"\bOK\b", respuesta))
    tiene_error = bool(re.search(r"\bERROR\b", respuesta))
    if tiene_ok and not tiene_error:
        return {"ok": True}
    return {"ok": False, "razon": respuesta}


# =============================================================================
# Ejecutar-Script
# =============================================================================

def ejecutar_script(script: str, log_path: str, log_comandos: bool = False,
                    log_salida: bool = False, timeout_segundos: int = 120) -> dict:
    if log_comandos:
        escribir_log("=== SCRIPT A EJECUTAR ===", log_path)
        for linea in script.split("\n"):
            escribir_log(f"    {linea}", log_path)
        escribir_log("=== FIN SCRIPT ===", log_path)

    # Validacion sintactica
    try:
        compile(script, "<script>", "exec")
    except SyntaxError as e:
        escribir_log(f"Script invalido sintacticamente: {e}", log_path)
        return {"exito": False,
                "error": f"Script invalido sintacticamente: {e}",
                "exit_code": -1, "salida": ""}

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    )
    tmp.write(script)
    tmp.close()

    try:
        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            proc = subprocess.run(
                [sys.executable, tmp.name],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_segundos,
                env=env,
            )
        except subprocess.TimeoutExpired:
            escribir_log(
                f"Script supero el timeout de {timeout_segundos}s. Proceso terminado.",
                log_path)
            return {"exito": False,
                    "error": f"Timeout tras {timeout_segundos}s.",
                    "exit_code": -1, "salida": ""}

        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()

        if log_salida and stdout:
            escribir_log("=== SALIDA DEL SCRIPT ===", log_path)
            for linea in stdout.split("\n"):
                if linea.strip():
                    escribir_log(f"  OUT >> {linea}", log_path)

        if proc.returncode != 0:
            escribir_log(f"Script fallo (exit {proc.returncode}): {stderr}", log_path)
            return {
                "exito": False,
                "error": (f"ExitCode: {proc.returncode}\n"
                          f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}"),
                "exit_code": proc.returncode,
                "salida": stdout,
            }

        escribir_log(f"Script ejecutado correctamente (exit {proc.returncode}).", log_path)
        return {"exito": True, "error": "", "exit_code": proc.returncode, "salida": stdout}
    finally:
        os.unlink(tmp.name)
