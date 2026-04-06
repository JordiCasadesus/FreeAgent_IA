"""agente.py - Agente de automatizacion con Ollama + Telegram (Python)

ARQUITECTURA:
  - Lee tareas.yaml (modelo global + lista de tareas con sus prompts)
  - Por cada tarea, cuando llega su intervalo:
      1. Construye el prompt con el contexto de la tarea
      2. El modelo genera un script Python
      3. Se ejecuta el script generado
      4. Si falla, pide correccion al modelo (autocorreccion)
      5. Notifica resultado por Telegram

USO:
  python agente.py
  Para detener: Ctrl+C
"""

import os
import re
import sys
import json
import time
import hashlib
import datetime

from funciones import (
    escribir_log,
    enviar_telegram,
    publicar_resultados_telegram,
    leer_yaml,
    validar_config,
    generar_script,
    verificar_resultado_chat,
    ejecutar_script,
    sanear_script,
    clasificar_error,
)

SCRIPT_DIR        = os.path.dirname(os.path.abspath(__file__))
STATE_DIR         = os.path.join(SCRIPT_DIR, "state")
TAREA_ACTUAL_PATH = os.path.join(STATE_DIR, "tarea_actual.json")
TELEGRAM_MSG_PATH = os.path.join(STATE_DIR, "telegram_msg.json")


def _set_tarea_actual(nombre: str):
    try:
        with open(TAREA_ACTUAL_PATH, "w", encoding="utf-8") as f:
            json.dump({"tarea": nombre}, f)
    except Exception:
        pass

def _clear_tarea_actual():
    try:
        with open(TAREA_ACTUAL_PATH, "w", encoding="utf-8") as f:
            json.dump({}, f)
    except Exception:
        pass


# =============================================================================
# Helpers de prompt
# =============================================================================

def obtener_prompt_sistema(cfg: dict) -> str:
    def _to_list(v):
        if not v:           return []
        if isinstance(v, list): return list(v)
        return v.split("\n")
    lista = _to_list(cfg.get("prompts_sistema")) + _to_list(cfg.get("prompts_sistema_fijos"))
    lineas = "\n".join(f"- {l}" for l in lista)
    return f"Requisitos obligatorios:\n{lineas}"


def obtener_prompt_verificador(cfg: dict) -> str:
    valor = cfg.get("prompts_verificador")
    if valor:
        lista  = valor if isinstance(valor, list) else valor.split("\n")
        lineas = "\n".join(f"- {l}" for l in lista)
        return f"Verifica y analiza el script que acabas de generar:\n{lineas}"
    return ""


# =============================================================================
# Refrescar-Log  (tablón de estado)
# =============================================================================


def refrescar_log(ultimos_resultados: dict, tareas: dict, log_path: str):
    if not ultimos_resultados:
        return
    lineas = []
    for nombre in tareas:
        if nombre not in ultimos_resultados:
            continue
        texto = ultimos_resultados[nombre]
        if not texto.startswith("OK"):
            continue
        lineas.append("=" * 48)
        texto = texto.replace("\r\n", "\n").replace("\r", "\n")
        lineas.extend(texto.split("\n"))
    if lineas:
        lineas.append("=" * 48)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas) + "\n")


# =============================================================================
# Utilidades
# =============================================================================

def md5_texto(texto: str) -> str:
    return hashlib.md5(texto.encode("utf-8")).hexdigest().upper()


def guardar_estado(ruta: str, ultimas_ejecuciones: dict):
    obj = {k: v.strftime("%Y-%m-%d %H:%M:%S") for k, v in ultimas_ejecuciones.items()}
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)


# =============================================================================
# MAIN
# =============================================================================

def main():
    ruta_config = os.path.join(SCRIPT_DIR, "config", "config.yaml")
    ruta_tareas = os.path.join(SCRIPT_DIR, "config", "tareas.yaml")
    for ruta, nombre in [(ruta_config, "config/config.yaml"), (ruta_tareas, "config/tareas.yaml")]:
        if not os.path.exists(ruta):
            print(f"ERROR: No se encuentra {nombre}")
            sys.exit(1)

    try:
        yaml_data = leer_yaml(ruta_config, ruta_tareas)
    except Exception as e:
        print(f"ERROR: No se pudo leer la configuracion: {e}")
        sys.exit(1)

    cfg    = yaml_data["config"]
    tareas = yaml_data["tareas"]

    if not tareas:
        print("ERROR: No hay tareas definidas en tareas.yaml")
        sys.exit(1)

    # Extraer configuracion global
    modelo          = cfg["modelo"]
    modelo_fallback = cfg.get("modelo_fallback", "")
    api_key  = cfg.get("api_key", "")
    telegram_activo  = bool(cfg.get("telegram_activo", True))
    telegram_token   = cfg.get("telegram_token", "") if telegram_activo else ""
    telegram_chat_id    = str(cfg.get("telegram_chat_id", "")) if telegram_activo else ""
    telegram_intervalo  = int(cfg.get("telegram_intervalo", 300))
    log_prompt          = bool(cfg.get("log_prompt", False))
    log_respuesta   = bool(cfg.get("log_respuesta", False))
    log_comandos    = bool(cfg.get("log_comandos", False))
    log_salida      = bool(cfg.get("log_salida", False))
    opciones_globales = cfg.get("ollama_options") or {}

    try:
        validar_config(cfg, tareas)
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    log_path = cfg.get("log_path", r"logs\agente.log").replace("\\", "/")
    if not os.path.isabs(log_path):
        log_path = os.path.join(SCRIPT_DIR, log_path)

    ruta_cache = os.path.join(SCRIPT_DIR, "scripts_cache")
    os.makedirs(ruta_cache, exist_ok=True)

    # Limpiar log al inicio
    if os.path.exists(log_path):
        open(log_path, "w").close()

    mensaje_inicio = f"Agente iniciado. Modelo: {modelo} | Tareas: {', '.join(tareas.keys())}"
    escribir_log(mensaje_inicio, log_path)
    enviar_telegram(f"Agente iniciado.\n{mensaje_inicio}",
                    telegram_token, telegram_chat_id, log_path)

    yaml_ultima_mod = max(os.path.getmtime(ruta_config), os.path.getmtime(ruta_tareas))

    # Estado persistente
    ruta_estado        = os.path.join(STATE_DIR, "estado.json")
    ultimas_ejecuciones: dict = {}
    ultimos_resultados: dict  = {}

    if os.path.exists(ruta_estado):
        try:
            with open(ruta_estado, "r", encoding="utf-8") as f:
                estado = json.load(f)
            for k, v in estado.items():
                ultimas_ejecuciones[k] = datetime.datetime.strptime(v, "%Y-%m-%d %H:%M:%S")
            escribir_log("Estado cargado desde estado.json", log_path)
        except Exception:
            escribir_log("ADVERTENCIA: No se pudo leer estado.json, se empieza desde cero.",
                         log_path)

    telegram_ultima = datetime.datetime.min  # control cooldown Telegram

    # Planificacion next_run
    next_run: dict = {}
    for nombre, tarea in tareas.items():
        iv = int(tarea.get("intervalo", 60))
        if nombre in ultimas_ejecuciones:
            next_run[nombre] = ultimas_ejecuciones[nombre] + datetime.timedelta(seconds=iv)
        else:
            next_run[nombre] = datetime.datetime.min

    def _telegram_si_toca():
        nonlocal telegram_ultima
        ahora = datetime.datetime.now()
        if (ahora - telegram_ultima).total_seconds() >= telegram_intervalo:
            publicar_resultados_telegram(
                ultimos_resultados, tareas,
                telegram_token, telegram_chat_id,
                TELEGRAM_MSG_PATH, log_path)
            telegram_ultima = ahora

    # =========================================================================
    # BUCLE PRINCIPAL
    # =========================================================================

    while True:
        try:
            ahora = datetime.datetime.now()

            # Ejecucion forzada desde GUI
            ruta_forzar = os.path.join(STATE_DIR, "forzar_tarea.json")
            if os.path.exists(ruta_forzar):
                try:
                    with open(ruta_forzar, "r", encoding="utf-8") as f:
                        nombre_forzar = json.load(f).get("tarea", "")
                    os.remove(ruta_forzar)
                    if nombre_forzar in next_run:
                        next_run[nombre_forzar] = datetime.datetime.min
                        escribir_log(f"[{nombre_forzar}] Ejecucion forzada desde GUI.", log_path)
                except Exception:
                    pass

            # Hot-reload YAML
            yaml_mod = max(os.path.getmtime(ruta_config), os.path.getmtime(ruta_tareas))
            if yaml_mod > yaml_ultima_mod:
                yaml_data       = leer_yaml(ruta_config, ruta_tareas)
                cfg             = yaml_data["config"]
                tareas          = yaml_data["tareas"]
                modelo          = cfg["modelo"]
                modelo_fallback = cfg.get("modelo_fallback", "")
                api_key          = cfg.get("api_key", "")
                telegram_activo  = bool(cfg.get("telegram_activo", True))
                telegram_token   = cfg.get("telegram_token", "") if telegram_activo else ""
                telegram_chat_id   = str(cfg.get("telegram_chat_id", "")) if telegram_activo else ""
                telegram_intervalo = int(cfg.get("telegram_intervalo", 300))
                log_prompt         = bool(cfg.get("log_prompt", False))
                log_respuesta   = bool(cfg.get("log_respuesta", False))
                log_comandos    = bool(cfg.get("log_comandos", False))
                log_salida      = bool(cfg.get("log_salida", False))
                opciones_globales = cfg.get("ollama_options") or {}
                yaml_ultima_mod = yaml_mod
                escribir_log("YAML recargado.", log_path)

                # Limpiar tareas eliminadas
                tareas_eliminadas = [n for n in list(next_run) if n not in tareas]
                for nombre in tareas_eliminadas:
                    for ext in [".py", ".hash"]:
                        fp = os.path.join(ruta_cache, f"{nombre}{ext}")
                        if os.path.exists(fp):
                            os.remove(fp)
                    ultimas_ejecuciones.pop(nombre, None)
                    ultimos_resultados.pop(nombre, None)
                    next_run.pop(nombre, None)
                    escribir_log(f"[{nombre}] Tarea eliminada: cache y estado limpiados.", log_path)
                if tareas_eliminadas:
                    guardar_estado(ruta_estado, ultimas_ejecuciones)

                for nombre in tareas:
                    if nombre not in next_run:
                        iv = int(tareas[nombre].get("intervalo", 60))
                        next_run[nombre] = (
                            ultimas_ejecuciones[nombre] + datetime.timedelta(seconds=iv)
                            if nombre in ultimas_ejecuciones
                            else datetime.datetime.min
                        )

            # -----------------------------------------------------------------
            for nombre_tarea, tarea in tareas.items():
                intervalo      = int(tarea.get("intervalo", 60))
                timeout_ollama = int(tarea.get("timeout_ollama") or 300)
                timeout_script = int(tarea.get("timeout_script") or 120)
                max_reintentos = int(tarea.get("max_reintentos") or 3)

                opciones = dict(opciones_globales)
                opciones.update(tarea.get("ollama_options") or {})

                if nombre_tarea not in next_run:
                    iv = intervalo
                    next_run[nombre_tarea] = (
                        ultimas_ejecuciones[nombre_tarea] + datetime.timedelta(seconds=iv)
                        if nombre_tarea in ultimas_ejecuciones
                        else datetime.datetime.min
                    )

                if ahora < next_run[nombre_tarea]:
                    continue

                # -------------------------------------------------------------
                # Tarea en marcha
                # -------------------------------------------------------------
                escribir_log("=" * 48, log_path)
                escribir_log(f"           TAREA: {nombre_tarea}", log_path, con_timestamp=True)
                escribir_log("=" * 48, log_path)
                _set_tarea_actual(nombre_tarea)

                prompt_raw   = tarea.get("prompt", [])
                prompt_tarea = "\n".join(prompt_raw) if isinstance(prompt_raw, list) else str(prompt_raw)

                prompt_sistema     = obtener_prompt_sistema(cfg)
                prompt_verificador = obtener_prompt_verificador(cfg)

                pv_tarea = tarea.get("prompt_verificador")
                if pv_tarea:
                    pvs = pv_tarea if isinstance(pv_tarea, list) else [pv_tarea]
                    for pvl in pvs:
                        prompt_verificador += f"\n- {pvl}"

                prompt_completo = (
                    f"{prompt_sistema}\n{prompt_tarea}\n\n"
                    "Responde solo con el bloque ```python```."
                )

                # -------------------------------------------------------------
                # Cache: MD5 del prompt
                # -------------------------------------------------------------
                hash_actual    = md5_texto(prompt_completo)
                archivo_script = os.path.join(ruta_cache, f"{nombre_tarea}.py")
                archivo_hash   = os.path.join(ruta_cache, f"{nombre_tarea}.hash")

                script_actual = None
                desde_cache   = False

                if os.path.exists(archivo_script) and os.path.exists(archivo_hash):
                    with open(archivo_hash, "r", encoding="utf-8") as f:
                        hash_guardado = f.read().strip()
                    if hash_guardado == hash_actual:
                        with open(archivo_script, "r", encoding="utf-8") as f:
                            script_actual = f.read()
                        script_actual = sanear_script(script_actual, log_path)
                        desde_cache = True
                        escribir_log(f"[{nombre_tarea}] Ejecutando cache.", log_path)

                # -------------------------------------------------------------
                # Generar si no hay cache valida
                # -------------------------------------------------------------
                mensajes_actuales = None
                modelo_actual     = modelo

                if not script_actual:
                    escribir_log(
                        f"[{nombre_tarea}] Creando script (modelo: {modelo})... ",
                        log_path, no_newline=True)
                    gen = generar_script(
                        modelo=modelo, prompt=prompt_completo,
                        log_path=log_path, api_key=api_key,
                        log_prompt=log_prompt, log_respuesta=log_respuesta,
                        timeout_segundos=timeout_ollama, opciones=opciones,
                    )
                    if gen is None and modelo_fallback:
                        escribir_log(
                            f"[{nombre_tarea}] Timeout generando. Usando fallback: {modelo_fallback}...",
                            log_path)
                        modelo_actual = modelo_fallback
                        gen = generar_script(
                            modelo=modelo_fallback, prompt=prompt_completo,
                            log_path=log_path, api_key=api_key,
                            log_prompt=log_prompt, log_respuesta=log_respuesta,
                            timeout_segundos=timeout_ollama, opciones=opciones,
                        )
                    if gen is None:
                        escribir_log(
                            f"[{nombre_tarea}] No se genero script. Ciclo omitido.", log_path)
                        ultimas_ejecuciones[nombre_tarea] = datetime.datetime.now()
                        next_run[nombre_tarea] = (datetime.datetime.now()
                                                  + datetime.timedelta(seconds=intervalo))
                        continue

                    script_actual     = gen["script"]
                    mensajes_actuales = gen["mensajes"]

                # -------------------------------------------------------------
                # Bucle de reintentos
                # -------------------------------------------------------------
                for intento in range(1, max_reintentos + 1):
                    escribir_log(
                        f"Ejecutando script (intento {intento}/{max_reintentos})...", log_path)

                    resultado = ejecutar_script(
                        script=script_actual, log_path=log_path,
                        log_comandos=log_comandos, log_salida=log_salida,
                        timeout_segundos=timeout_script,
                    )

                    # Comprobar output vacio
                    if resultado["exito"] and not resultado["salida"]:
                        escribir_log(
                            f"[{nombre_tarea}] Script sin output. Se considera fallo.", log_path)
                        resultado = {
                            "exito": False,
                            "error": "El script no produjo ninguna salida.",
                            "exit_code": 1, "salida": "",
                        }

                    # Verificacion conversacional
                    if resultado["exito"] and mensajes_actuales and prompt_verificador:
                        salida_ok = verificar_resultado_chat(
                            mensajes=mensajes_actuales, salida=resultado["salida"],
                            modelo=modelo_actual, log_path=log_path,
                            api_key=api_key, prompt_verificador=prompt_verificador,
                            timeout_segundos=timeout_ollama, opciones=opciones,
                        )
                        if not salida_ok["ok"]:
                            razon = salida_ok.get("razon", "resultado incorrecto")
                            resultado = {
                                "exito": False,
                                "error": f"Verificacion: {razon}\nSTDOUT:\n{resultado['salida']}",
                                "exit_code": 1, "salida": resultado["salida"],
                            }

                    # ── EXITO ─────────────────────────────────────────────────
                    if resultado["exito"]:
                        if not desde_cache:
                            cabecera = (f"# Generado por: {modelo_actual} | "
                                        f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                            with open(archivo_script, "w", encoding="utf-8") as f:
                                f.write(cabecera + script_actual)
                            with open(archivo_hash, "w", encoding="utf-8") as f:
                                f.write(hash_actual)
                            escribir_log(f"[{nombre_tarea}] Script guardado en cache.", log_path)

                        ultimas_ejecuciones[nombre_tarea] = datetime.datetime.now()
                        next_run[nombre_tarea] = (datetime.datetime.now()
                                                  + datetime.timedelta(seconds=intervalo))
                        guardar_estado(ruta_estado, ultimas_ejecuciones)

                        salida_texto    = f"\n{resultado['salida']}" if resultado["salida"] else ""
                        salida_anterior = ultimos_resultados.get(nombre_tarea)
                        salida_anterior_limpia = (
                            re.sub(r"^OK  \[.*?\] \d\d:\d\d:\d\d", "", salida_anterior)
                            if salida_anterior else None
                        )
                        hay_cambio = salida_anterior_limpia != salida_texto

                        ultimos_resultados[nombre_tarea] = (
                            f"OK  [{nombre_tarea}] "
                            f"{datetime.datetime.now().strftime('%H:%M:%S')}{salida_texto}"
                        )
                        if hay_cambio:
                            print(f"[{nombre_tarea}] Completado.{salida_texto}")
                        else:
                            print(f"[{nombre_tarea}] Completado (sin cambios).")
                        refrescar_log(ultimos_resultados, tareas, log_path)
                        _telegram_si_toca()
                        break

                    # ── FALLO ─────────────────────────────────────────────────
                    escribir_log(
                        f"[{nombre_tarea}] Script fallo. Error: {resultado['error']}", log_path)

                    # Cache invalida — borrar y regenerar desde cero
                    if desde_cache:
                        for fp in [archivo_script, archivo_hash]:
                            if os.path.exists(fp):
                                os.remove(fp)
                        escribir_log(
                            f"[{nombre_tarea}] Cache eliminada. Regenerando desde cero...", log_path)
                        gen = generar_script(
                            modelo=modelo, prompt=prompt_completo,
                            log_path=log_path, api_key=api_key,
                            log_prompt=log_prompt, log_respuesta=log_respuesta,
                            timeout_segundos=timeout_ollama, opciones=opciones,
                        )
                        if gen is None and modelo_fallback:
                            escribir_log(
                                f"[{nombre_tarea}] Timeout regenerando. Usando fallback: {modelo_fallback}...",
                                log_path)
                            modelo_actual = modelo_fallback
                            gen = generar_script(
                                modelo=modelo_fallback, prompt=prompt_completo,
                                log_path=log_path, api_key=api_key,
                                log_prompt=log_prompt, log_respuesta=log_respuesta,
                                timeout_segundos=timeout_ollama, opciones=opciones,
                            )
                        if gen is None:
                            escribir_log(
                                f"[{nombre_tarea}] No se genero script. Ciclo omitido.", log_path)
                            break
                        script_actual     = gen["script"]
                        mensajes_actuales = gen["mensajes"]
                        desde_cache       = False
                        continue

                    # Reintento con correccion
                    if intento < max_reintentos:
                        escribir_log("Pidiendo correccion al modelo...", log_path)
                        modelo_actual  = modelo
                        hint = clasificar_error(resultado["error"])
                        contexto_error = (f"ExitCode: {resultado['exit_code']}\n"
                                          f"STDOUT:\n{resultado['salida']}\n"
                                          f"STDERR:\n{resultado['error']}{hint}")
                        gen = generar_script(
                            modelo=modelo, error_anterior=contexto_error,
                            script_anterior=script_actual,
                            mensajes_anteriores=mensajes_actuales,
                            log_path=log_path, api_key=api_key,
                            log_prompt=log_prompt, log_respuesta=log_respuesta,
                            timeout_segundos=timeout_ollama, opciones=opciones,
                        )
                        if gen is None and modelo_fallback:
                            escribir_log(
                                f"[{nombre_tarea}] Timeout corrigiendo. Usando fallback: {modelo_fallback}...",
                                log_path)
                            modelo_actual = modelo_fallback
                            gen = generar_script(
                                modelo=modelo_fallback,
                                error_anterior=resultado["error"],
                                script_anterior=script_actual,
                                log_path=log_path, api_key=api_key,
                                log_prompt=log_prompt, log_respuesta=log_respuesta,
                                timeout_segundos=timeout_ollama, opciones=opciones,
                            )
                        if gen is None:
                            escribir_log("No se genero correccion. Abandonando tarea.", log_path)
                            break
                        script_actual     = gen["script"]
                        mensajes_actuales = gen["mensajes"]

                    else:
                        # Fallback final tras agotar reintentos
                        if modelo_fallback:
                            escribir_log(
                                f"[{nombre_tarea}] Fallo local. Intentando con modelo fallback: {modelo_fallback}...",
                                log_path)
                            gen_fb = generar_script(
                                modelo=modelo_fallback, prompt=prompt_completo,
                                log_path=log_path, api_key=api_key,
                                log_prompt=log_prompt, log_respuesta=log_respuesta,
                                timeout_segundos=timeout_ollama, opciones=opciones,
                            )
                            if gen_fb:
                                resultado_fb = ejecutar_script(
                                    script=gen_fb["script"], log_path=log_path,
                                    log_comandos=log_comandos, log_salida=log_salida,
                                )
                                if resultado_fb["exito"] and not resultado_fb["salida"]:
                                    escribir_log(
                                        f"[{nombre_tarea}] Fallback sin output. Se considera fallo.",
                                        log_path)
                                    resultado_fb = {"exito": False, "salida": ""}

                                if resultado_fb.get("exito") and gen_fb.get("mensajes") and prompt_verificador:
                                    salida_ok_fb = verificar_resultado_chat(
                                        mensajes=gen_fb["mensajes"],
                                        salida=resultado_fb["salida"],
                                        modelo=modelo_fallback, log_path=log_path,
                                        api_key=api_key,
                                        prompt_verificador=prompt_verificador,
                                        timeout_segundos=timeout_ollama, opciones=opciones,
                                    )
                                    if not salida_ok_fb["ok"]:
                                        escribir_log(
                                            f"[{nombre_tarea}] Fallback verificacion fallida.",
                                            log_path)
                                        resultado_fb = {"exito": False, "salida": ""}

                                if resultado_fb.get("exito"):
                                    cabecera = (
                                        f"# Generado por: {modelo_fallback} | "
                                        f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                                    )
                                    with open(archivo_script, "w", encoding="utf-8") as f:
                                        f.write(cabecera + gen_fb["script"])
                                    with open(archivo_hash, "w", encoding="utf-8") as f:
                                        f.write(hash_actual)
                                    ultimas_ejecuciones[nombre_tarea] = datetime.datetime.now()
                                    next_run[nombre_tarea] = (datetime.datetime.now()
                                                              + datetime.timedelta(seconds=intervalo))
                                    guardar_estado(ruta_estado, ultimas_ejecuciones)

                                    salida_texto    = f"\n{resultado_fb['salida']}" if resultado_fb.get("salida") else ""
                                    salida_anterior = ultimos_resultados.get(nombre_tarea)
                                    salida_anterior_limpia = (
                                        re.sub(r"^OK  \[.*?\] \d\d:\d\d:\d\d.*?\n?", "", salida_anterior)
                                        if salida_anterior else None
                                    )
                                    hay_cambio = salida_anterior_limpia != salida_texto
                                    ultimos_resultados[nombre_tarea] = (
                                        f"OK  [{nombre_tarea}] "
                                        f"{datetime.datetime.now().strftime('%H:%M:%S')} "
                                        f"(fallback){salida_texto}"
                                    )
                                    if hay_cambio:
                                        print(f"[{nombre_tarea}] Completado con modelo fallback.{salida_texto}")
                                    else:
                                        print(f"[{nombre_tarea}] Completado fallback (sin cambios).")
                                    refrescar_log(ultimos_resultados, tareas, log_path)
                                    publicar_resultados_telegram(
                                        ultimos_resultados, tareas,
                                        telegram_token, telegram_chat_id,
                                        TELEGRAM_MSG_PATH, log_path)
                                    break

                            escribir_log(f"[{nombre_tarea}] Fallback tambien fallo.", log_path)

                        msg = f"[{nombre_tarea}] Fallo tras {max_reintentos} intentos."
                        ultimos_resultados[nombre_tarea] = (
                            f"ERR [{nombre_tarea}] "
                            f"{datetime.datetime.now().strftime('%H:%M:%S')} "
                            f"Fallo tras {max_reintentos} intentos."
                        )
                        escribir_log(msg, log_path)
                        refrescar_log(ultimos_resultados, tareas, log_path)
                        _telegram_si_toca()
                        # No guardamos en estado.json: al reiniciar el agente reintentara
                        next_run[nombre_tarea] = (datetime.datetime.now()
                                                  + datetime.timedelta(seconds=intervalo))

                _clear_tarea_actual()

        except KeyboardInterrupt:
            escribir_log("Agente detenido por el usuario.", log_path)
            break
        except Exception as e:
            lineno = sys.exc_info()[2].tb_lineno if sys.exc_info()[2] else "?"
            msg_error = f"Error inesperado: {e} | Linea: {lineno}"
            escribir_log(msg_error, log_path)
            try:
                enviar_telegram(msg_error, telegram_token, telegram_chat_id, log_path)
            except Exception:
                pass

        # Dormir hasta la proxima tarea (max 30s para hot-reload)
        if next_run:
            proximo  = min(next_run.values())
            hasta    = max(1.0, (proximo - datetime.datetime.now()).total_seconds())
            segundos = min(int(hasta) + 1, 30)
        else:
            segundos = 10
        time.sleep(segundos)

    escribir_log("Agente finalizado.", log_path)


if __name__ == "__main__":
    main()
