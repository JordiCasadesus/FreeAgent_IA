"""gui_views/yaml_editor.py - Editor estructurado de tareas.yaml

Layout:
  - Panel izquierdo: navegacion por secciones (config global, ollama options,
    prompts sistema, prompts verificador, y una entrada por cada tarea)
  - Panel derecho: formulario de la seccion seleccionada

Al navegar entre secciones, los cambios del formulario actual se recogen
en self._data. Al pulsar Guardar se escribe el YAML completo.

AVISO: los comentarios del YAML original se pierden al guardar desde el
editor estructurado. Usa "Abrir texto" para editar el YAML en crudo si
necesitas conservar los comentarios.
"""

import os
import yaml
import subprocess
import customtkinter as ctk
from PIL import Image

_ICONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "imagenes", "iconos", "32x32")

def _icon(name: str, size: int = 16) -> ctk.CTkImage | None:
    try:
        return ctk.CTkImage(Image.open(os.path.join(_ICONS_DIR, name)), size=(size, size))
    except Exception:
        return None


# Colores de acento por seccion
_C = {
    "config":     "#1a4a8a",
    "ollama":     "#1a5555",
    "telegram":   "#1a5a8a",
    "sistema":    "#1a6040",
    "verificador":"#4a1a8a",
    "tarea":      "#5a3010",
    "tarea_hover":"#7a4820",
}


class YamlEditorView(ctk.CTkFrame):

    def __init__(self, parent, app, path: str = None):
        super().__init__(parent, fg_color="transparent")
        self.app              = app
        self._path            = path or app.TAREAS_PATH
        self._data: dict      = {}
        self._current_section = None   # str key, ej. "config_global" o "tarea:backup"
        self._widget_refs     = {}     # {key: ("entry"|"checkbox"|"textbox", widget)}
        self._modificado      = False
        self._raw_mode        = False  # modo texto plano
        self._build()
        self.cargar_archivo(self._path)

    def _cargar_modelos_ollama(self):
        try:
            r = subprocess.run(["ollama", "list"], capture_output=True, text=True)
            lineas = r.stdout.strip().splitlines()
            return [l.split()[0] for l in lineas[1:] if l.strip()]
        except Exception:
            return []

    def _cargar_modelos_gemini(self) -> list[str]:
        import requests as _req
        api_key = self._data.get("api_key", "")
        if not api_key:
            return []
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
            r = _req.get(url, timeout=8)
            if r.status_code != 200:
                return []
            return [
                m["name"].replace("models/", "")
                for m in r.json().get("models", [])
                if "generateContent" in m.get("supportedGenerationMethods", [])
            ]
        except Exception:
            return []

    # =========================================================================
    # Construccion del layout fijo
    # =========================================================================

    def _build(self):
        # ── Header ───────────────────────────────────────────────────────────
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(12, 6))

        ctk.CTkLabel(header, text="YAML",
                     font=ctk.CTkFont(size=20, weight="bold")).pack(side="left")

        self._btn_guardar = ctk.CTkButton(
            header, text="Guardar", width=90,
            fg_color="#1a6b2a", hover_color="#228b36",
            command=self.guardar)
        self._btn_guardar.pack(side="right", padx=4)

        ctk.CTkButton(header, text="Recargar", width=90,
                      command=self._recargar).pack(side="right", padx=4)

        self._btn_toggle = ctk.CTkButton(
            header, text="Ver texto", width=90,
            fg_color="#555", hover_color="#666",
            command=self._toggle_raw)
        self._btn_toggle.pack(side="right", padx=4)

        self._lbl_path = ctk.CTkLabel(
            header, text="", text_color="#888",
            font=ctk.CTkFont(size=11))
        self._lbl_path.pack(side="left", padx=12)

        self._lbl_estado = ctk.CTkLabel(
            header, text="", text_color="#52c252",
            font=ctk.CTkFont(size=11))
        self._lbl_estado.pack(side="right", padx=8)

        # ── Panel principal ───────────────────────────────────────────────────
        self._main = ctk.CTkFrame(self, fg_color="transparent")
        self._main.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        self._main.columnconfigure(1, weight=1)
        self._main.rowconfigure(0, weight=1)

        # Nav izquierdo
        self._nav = ctk.CTkScrollableFrame(self._main, width=200,
                                           label_text="Secciones")
        self._nav.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        # Contenedor de formulario / texto
        self._form_container = ctk.CTkFrame(self._main, fg_color="transparent")
        self._form_container.grid(row=0, column=1, sticky="nsew")
        self._form_container.rowconfigure(0, weight=1)
        self._form_container.columnconfigure(0, weight=1)

        self._form_scroll = None   # creado en _clear_form()
        self._raw_editor  = None   # CTkTextbox para modo texto

    # =========================================================================
    # Navegacion
    # =========================================================================

    def _es_config(self) -> bool:
        return os.path.basename(self._path) == "config.yaml"

    def _rebuild_nav(self):
        for w in self._nav.winfo_children():
            w.destroy()

        if self._es_config():
            secciones = [
                ("Config global",        "config_global",       _C["config"],      "Properties.png"),
                ("Ollama Options",       "ollama_options",      _C["ollama"],      "Tools.png"),
                ("Telegram",             "telegram",            _C["telegram"],    "E-mail.png"),
                ("Prompts sistema",      "prompts_sistema",     _C["sistema"],     "Comment.png"),
                ("Prompts verificador",  "prompts_verificador", _C["verificador"], "Check boxes.png"),
                ("Reglas tecnicas",      "prompts_fijos",       "#6a1a6a",         "Critical details.png"),
            ]
            for label, key, hover, icon_file in secciones:
                ctk.CTkButton(
                    self._nav, text=f"  {label}", anchor="w",
                    image=_icon(icon_file), compound="left",
                    height=32, font=ctk.CTkFont(size=12),
                    fg_color="#2b2b2b", hover_color=hover,
                    command=lambda k=key: self._navigate(k),
                ).pack(fill="x", pady=2)
        else:
            ctk.CTkLabel(self._nav, text="── TAREAS ──",
                         text_color="#666",
                         font=ctk.CTkFont(size=11)).pack(pady=(10, 4))

            _icono_tarea = _icon("Script.png")
            for nombre in (self._data.get("tareas") or {}).keys():
                ctk.CTkButton(
                    self._nav, text=f"  {nombre}", anchor="w",
                    image=_icono_tarea, compound="left",
                    height=32, font=ctk.CTkFont(size=12),
                    fg_color="#2b2b2b", hover_color=_C["tarea_hover"],
                    command=lambda n=nombre: self._navigate(f"tarea:{n}"),
                ).pack(fill="x", pady=2)

            ctk.CTkButton(
                self._nav, text="+ Nueva tarea",
                height=32, font=ctk.CTkFont(size=12),
                fg_color="#1a5a1a", hover_color="#228b22",
                command=self._nueva_tarea,
            ).pack(fill="x", pady=(10, 2))

    def _navigate(self, section_key: str):
        if self._raw_mode:
            return
        self._save_current_section()
        self._current_section = section_key
        self._clear_form()

        dispatch = {
            "config_global":       self._form_config_global,
            "ollama_options":      self._form_ollama_options,
            "telegram":            self._form_telegram,
            "prompts_sistema":     lambda: self._form_prompts_list("prompts_sistema"),
            "prompts_verificador": lambda: self._form_prompts_list("prompts_verificador"),
            "prompts_fijos":       self._form_prompts_fijos,
        }
        if section_key in dispatch:
            dispatch[section_key]()
        elif section_key.startswith("tarea:"):
            self._form_tarea(section_key[6:])

    def _clear_form(self):
        if self._form_scroll:
            self._form_scroll.destroy()
        self._form_scroll = ctk.CTkScrollableFrame(
            self._form_container, fg_color="transparent")
        self._form_scroll.grid(row=0, column=0, sticky="nsew")
        self._form_scroll.columnconfigure(1, weight=1)
        self._widget_refs = {}

    # =========================================================================
    # Helpers de formulario
    # =========================================================================

    def _sec_header(self, parent, row: int, titulo: str, color: str):
        f = ctk.CTkFrame(parent, fg_color=color, corner_radius=6)
        f.grid(row=row, column=0, columnspan=2, sticky="ew", padx=16, pady=(14, 6))
        ctk.CTkLabel(f, text=titulo,
                     font=ctk.CTkFont(size=13, weight="bold")).pack(
            side="left", padx=12, pady=5)

    def _field(self, parent, row: int, label: str, value,
               key: str, masked=False, width=300):
        ctk.CTkLabel(parent, text=label, anchor="e", width=190,
                     font=ctk.CTkFont(size=12)).grid(
            row=row, column=0, sticky="e", padx=(16, 8), pady=3)
        var = ctk.StringVar(value=str(value) if value is not None else "")
        ctk.CTkEntry(parent, textvariable=var,
                     show="•" if masked else "",
                     width=width).grid(
            row=row, column=1, sticky="w", padx=(0, 16), pady=3)
        self._widget_refs[key] = ("entry", var)


    def _combo(self, parent, row, label, value, key, opciones):
        ctk.CTkLabel(parent, text=label, anchor="e", width=190,
                    font=ctk.CTkFont(size=12)).grid(
            row=row, column=0, sticky="e", padx=(16, 8), pady=3)
        combo = ctk.CTkComboBox(parent, values=opciones, width=300)
        combo.set(str(value) if value else "")
        combo.grid(row=row, column=1, sticky="w", padx=(0, 16), pady=3)
        self._widget_refs[key] = ("combo", combo)


    def _check(self, parent, row: int, label: str, value, key: str):
        ctk.CTkLabel(parent, text=label, anchor="e", width=190,
                     font=ctk.CTkFont(size=12)).grid(
            row=row, column=0, sticky="e", padx=(16, 8), pady=3)
        chk = ctk.CTkCheckBox(parent, text="")
        if value:
            chk.select()
        chk.grid(row=row, column=1, sticky="w", padx=(0, 16), pady=3)
        self._widget_refs[key] = ("checkbox", chk)

    def _textbox(self, parent, row: int, label: str, items,
                 key: str, height=120):
        """Textbox en columna 1 (alineado con los Entry). Para texto corto."""
        ctk.CTkLabel(parent, text=label, anchor="ne", width=190,
                     font=ctk.CTkFont(size=12)).grid(
            row=row, column=0, sticky="ne", padx=(16, 8), pady=3)
        tb = ctk.CTkTextbox(parent, height=height,
                            font=ctk.CTkFont(family="Consolas", size=12))
        tb.grid(row=row, column=1, sticky="ew", padx=(0, 16), pady=3)
        content = ("\n".join(items)
                   if isinstance(items, list)
                   else (items or ""))
        tb.insert("0.0", content)
        self._widget_refs[key] = ("textbox", tb)

    def _textbox_full(self, parent, row: int, label: str, items,
                      key: str, height=200):
        """Textbox a ancho completo: label encima, textbox debajo.
        Ocupa 2 filas — el caller debe hacer r += 2."""
        ctk.CTkLabel(parent, text=label, anchor="w",
                     font=ctk.CTkFont(size=12)).grid(
            row=row, column=0, columnspan=2,
            sticky="w", padx=16, pady=(6, 1))
        tb = ctk.CTkTextbox(parent, height=height,
                            font=ctk.CTkFont(family="Consolas", size=12))
        tb.grid(row=row + 1, column=0, columnspan=2,
                sticky="ew", padx=16, pady=(0, 6))
        content = ("\n".join(items)
                   if isinstance(items, list)
                   else (items or ""))
        tb.insert("0.0", content)
        self._widget_refs[key] = ("textbox", tb)

    def _check_desc(self, parent, row: int, label: str, value, key: str, desc: str):
        """Checkbox con descripcion inline a la derecha."""
        ctk.CTkLabel(parent, text=label, anchor="e", width=190,
                     font=ctk.CTkFont(size=12)).grid(
            row=row, column=0, sticky="e", padx=(16, 8), pady=3)
        inner = ctk.CTkFrame(parent, fg_color="transparent")
        inner.grid(row=row, column=1, sticky="w", padx=(0, 16), pady=3)
        chk = ctk.CTkCheckBox(inner, text="")
        if value:
            chk.select()
        chk.pack(side="left")
        ctk.CTkLabel(inner, text=desc, text_color="#888",
                     font=ctk.CTkFont(size=11),
                     wraplength=500, justify="left").pack(side="left", padx=8)
        self._widget_refs[key] = ("checkbox", chk)

    def _modelo_boxes(self, parent, row: int, c: dict, ollama: list, gemini: list) -> int:
        """Dos cajas lado a lado: Ollama | Google API. Devuelve la siguiente fila."""
        _es_google = lambda v: v and (v.startswith("gemini-") or v.startswith("gemma-"))

        val_m  = c.get("modelo", "")
        val_fb = c.get("modelo_fallback", "")
        val_key = c.get("api_key", "")

        var_m   = ctk.StringVar(value=val_m)
        var_fb  = ctk.StringVar(value=val_fb)
        var_key = ctk.StringVar(value=val_key)
        self._widget_refs["modelo"]          = ("entry", var_m)
        self._widget_refs["modelo_fallback"] = ("entry", var_fb)
        self._widget_refs["api_key"]         = ("entry", var_key)

        container = ctk.CTkFrame(parent, fg_color="transparent")
        container.grid(row=row, column=0, columnspan=2, sticky="ew", padx=16, pady=6)
        container.columnconfigure(0, weight=1)
        container.columnconfigure(1, weight=1)

        # ── Caja Ollama ───────────────────────────────────────────────────────
        box_ol = ctk.CTkFrame(container, fg_color="#0e1e30", corner_radius=8,
                               border_width=1, border_color="#2255aa")
        box_ol.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        box_ol.columnconfigure(0, weight=1)

        ctk.CTkLabel(box_ol, text="Ollama  —  local",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color="#88bbff").grid(
            row=0, column=0, sticky="w", padx=10, pady=(8, 4))

        ctk.CTkLabel(box_ol, text="modelo:", anchor="w",
                     font=ctk.CTkFont(size=11), text_color="#aaa").grid(
            row=1, column=0, sticky="w", padx=10)
        cb_ol_m = ctk.CTkComboBox(box_ol, values=ollama or ["(sin modelos)"])
        cb_ol_m.set(val_m if val_m and not _es_google(val_m) else "")
        cb_ol_m.grid(row=2, column=0, sticky="ew", padx=10, pady=(2, 6))

        ctk.CTkLabel(box_ol, text="fallback:", anchor="w",
                     font=ctk.CTkFont(size=11), text_color="#aaa").grid(
            row=3, column=0, sticky="w", padx=10)
        cb_ol_fb = ctk.CTkComboBox(box_ol, values=ollama or ["(sin modelos)"])
        cb_ol_fb.set(val_fb if val_fb and not _es_google(val_fb) else "")
        cb_ol_fb.grid(row=4, column=0, sticky="ew", padx=10, pady=(2, 10))

        # ── Caja Google API ───────────────────────────────────────────────────
        box_g = ctk.CTkFrame(container, fg_color="#0e1e30", corner_radius=8,
                              border_width=1, border_color="#2255aa")
        box_g.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        box_g.columnconfigure(0, weight=1)

        ctk.CTkLabel(box_g, text="Google AI Studio",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color="#88bbff").grid(
            row=0, column=0, sticky="w", padx=10, pady=(8, 4))

        ctk.CTkLabel(box_g, text="modelo:", anchor="w",
                     font=ctk.CTkFont(size=11), text_color="#aaa").grid(
            row=1, column=0, sticky="w", padx=10)
        cb_g_m = ctk.CTkComboBox(box_g, values=gemini or ["(sin api_key)"])
        cb_g_m.set(val_m if _es_google(val_m) else "")
        cb_g_m.grid(row=2, column=0, sticky="ew", padx=10, pady=(2, 6))

        ctk.CTkLabel(box_g, text="fallback:", anchor="w",
                     font=ctk.CTkFont(size=11), text_color="#aaa").grid(
            row=3, column=0, sticky="w", padx=10)
        cb_g_fb = ctk.CTkComboBox(box_g, values=gemini or ["(sin api_key)"])
        cb_g_fb.set(val_fb if _es_google(val_fb) else "")
        cb_g_fb.grid(row=4, column=0, sticky="ew", padx=10, pady=(2, 6))

        kf = ctk.CTkFrame(box_g, fg_color="transparent")
        kf.grid(row=5, column=0, sticky="ew", padx=10, pady=(4, 10))
        kf.columnconfigure(1, weight=1)
        ctk.CTkLabel(kf, text="api_key:", font=ctk.CTkFont(size=11),
                     text_color="#aaa").grid(row=0, column=0, sticky="w", padx=(0, 4))
        ctk.CTkEntry(kf, textvariable=var_key, show="•").grid(
            row=0, column=1, sticky="ew")

        # Callbacks — seleccionar de una caja limpia la otra
        def _on_ol_m(v):
            if v and v != "(sin modelos)": var_m.set(v);  cb_g_m.set("")
        def _on_ol_fb(v):
            if v and v != "(sin modelos)": var_fb.set(v); cb_g_fb.set("")
        def _on_g_m(v):
            if v and v != "(sin api_key)": var_m.set(v);  cb_ol_m.set("")
        def _on_g_fb(v):
            if v and v != "(sin api_key)": var_fb.set(v); cb_ol_fb.set("")

        cb_ol_m.configure(command=_on_ol_m)
        cb_ol_fb.configure(command=_on_ol_fb)
        cb_g_m.configure(command=_on_g_m)
        cb_g_fb.configure(command=_on_g_fb)

        return row + 1

    def _info(self, parent, row: int, texto: str):
        ctk.CTkLabel(parent, text=texto, text_color="#888",
                     font=ctk.CTkFont(size=11), anchor="w").grid(
            row=row, column=0, columnspan=2, sticky="w", padx=16, pady=(0, 4))

    # =========================================================================
    # Formularios por seccion
    # =========================================================================

    def _form_config_global(self):
        f, c = self._form_scroll, self._data
        r = 0

        self._sec_header(f, r, "Modelos de IA", _C["config"]); r += 1
        r = self._modelo_boxes(f, r, c,
                               ollama=self._cargar_modelos_ollama(),
                               gemini=self._cargar_modelos_gemini())


        self._sec_header(f, r, "Logging  (solo afectan al historial completo)", _C["config"]); r += 1
        self._check_desc(f, r, "log_prompt",    c.get("log_prompt",    False), "log_prompt",    "Prompt completo enviado al modelo antes de cada generacion."); r += 1
        self._check_desc(f, r, "log_respuesta", c.get("log_respuesta", False), "log_respuesta", "Respuesta cruda completa que devuelve el modelo.");            r += 1
        self._check_desc(f, r, "log_comandos",  c.get("log_comandos",  False), "log_comandos",  "Codigo Python del script justo antes de ejecutarlo.");         r += 1
        self._check_desc(f, r, "log_salida",    c.get("log_salida",    False), "log_salida",    "Cada linea de salida (stdout) del script en tiempo real.");    r += 1

    def _form_telegram(self):
        f = self._form_scroll
        c = self._data
        r = 0

        self._sec_header(f, r, "Configuracion Telegram", _C["telegram"]); r += 1
        self._check_desc(f, r, "telegram_activo", c.get("telegram_activo", True), "telegram_activo",
                         "Enviar notificaciones al bot de Telegram."); r += 1
        self._field(f, r, "telegram_token",    c.get("telegram_token",    ""), "telegram_token",    masked=True); r += 1
        self._field(f, r, "telegram_chat_id",  c.get("telegram_chat_id",  ""), "telegram_chat_id",  width=200);   r += 1
        self._info(f, r, "  Obtén el chat_id enviando un mensaje a tu bot y consultando /getUpdates."); r += 1
        self._field(f, r, "telegram_intervalo (s)", c.get("telegram_intervalo", 300), "telegram_intervalo", width=120); r += 1
        self._info(f, r, "  Segundos minimos entre actualizaciones del tablon de estado en Telegram."); r += 1

    def _form_ollama_options(self):
        f    = self._form_scroll
        opts = self._data.get("ollama_options") or {}
        r    = 0

        self._sec_header(f, r, "Opciones de Ollama", _C["ollama"]); r += 1
        self._info(f, r, "Deja vacio para usar el valor por defecto del modelo."); r += 1

        campos = [
            ("temperature",    "temperature (0.0 - 1.0)"),
            ("num_predict",    "num_predict  (max tokens)"),
            ("num_ctx",        "num_ctx  (ventana contexto)"),
            ("num_gpu",        "num_gpu  (-1=todas, 0=CPU)"),
            ("top_k",          "top_k"),
            ("top_p",          "top_p"),
            ("repeat_penalty", "repeat_penalty"),
            ("num_thread",     "num_thread  (hilos CPU)"),
            ("num_batch",      "num_batch"),
        ]
        for campo, label in campos:
            val = opts.get(campo, "")
            self._field(f, r, label,
                        val if val != "" else "",
                        f"ollama_{campo}", width=120)
            r += 1

    def _form_prompts_list(self, key: str):
        f     = self._form_scroll
        items = self._data.get(key) or []
        titulo = ("Prompts del sistema"
                  if key == "prompts_sistema"
                  else "Prompts verificador")
        color = _C["sistema"] if key == "prompts_sistema" else _C["verificador"]
        r = 0

        self._sec_header(f, r, titulo, color); r += 1
        self._info(f, r, "Una linea = un item de la lista YAML."); r += 1
        self._textbox_full(f, r, "Items:", items, key, height=340)

    def _form_prompts_fijos(self):
        f = self._form_scroll
        r = 0

        self._sec_header(f, r, "Reglas tecnicas fijas", "#6a1a6a"); r += 1

        # Descripcion amplia
        desc = (
            "Estas reglas se inyectan SIEMPRE en todos los prompts, independientemente\n"
            "de lo que haya en 'Prompts sistema' o en cada tarea.\n\n"
            "Su proposito es corregir errores recurrentes que los modelos pequeños\n"
            "cometen sistematicamente al generar scripts Python:\n"
            "  - Patrones de librerias que requieren inicializacion previa (psutil, etc.)\n"
            "  - Manejo incorrecto de errores o valores nulos\n"
            "  - Comportamientos que el modelo 'olvida' aunque esten documentados\n\n"
            "A diferencia de 'Prompts sistema' (que describen el contexto general\n"
            "del agente y pueden incluir instrucciones de dominio), estas reglas son\n"
            "puramente tecnicas de Python y no deberia ser necesario que el autor\n"
            "de una tarea las conozca o las repita en cada prompt.\n\n"
            "Añade aqui cualquier patron que el modelo falle repetidamente."
        )
        lbl = ctk.CTkLabel(f, text=desc, anchor="w", justify="left",
                           text_color="#aaaaaa", font=ctk.CTkFont(size=11),
                           wraplength=600)
        lbl.grid(row=r, column=0, columnspan=3, sticky="w", padx=10, pady=(4, 12))
        r += 1

        items = self._data.get("prompts_sistema_fijos") or []
        self._textbox_full(f, r, "Reglas:", items, "prompts_sistema_fijos", height=280)

    def _form_tarea(self, nombre: str):
        f     = self._form_scroll
        tarea = (self._data.get("tareas") or {}).get(nombre, {})
        r     = 0

        self._sec_header(f, r, f"Tarea: {nombre}", _C["tarea"]); r += 1

        self._field(f, r, "intervalo (s)",      tarea.get("intervalo", 60),       f"{nombre}__intervalo",       width=120); r += 1
        self._field(f, r, "timeout agente (s)", tarea.get("timeout_ollama", ""), f"{nombre}__timeout_ollama",  width=120); r += 1
        self._field(f, r, "timeout_script (s)", tarea.get("timeout_script", ""), f"{nombre}__timeout_script",  width=120); r += 1
        self._field(f, r, "max_reintentos",     tarea.get("max_reintentos", ""), f"{nombre}__max_reintentos",  width=120); r += 1
        self._info(f, r, "Vacio = usa el valor global. 1 = falla rapido y va al fallback."); r += 1

        pv = tarea.get("prompt_verificador")
        self._textbox_full(f, r, "prompt_verificador:", pv if pv else [],
                           f"{nombre}__pv", height=70); r += 2

        self._sec_header(f, r, "Prompt (una linea = un item)", _C["tarea"]); r += 1
        self._textbox_full(f, r, "Lineas:", tarea.get("prompt", []),
                           f"{nombre}__prompt", height=280); r += 2

        btns = ctk.CTkFrame(f, fg_color="transparent")
        btns.grid(row=r, column=0, columnspan=2, sticky="w", padx=16, pady=(16, 8))

        ctk.CTkButton(
            btns, text="▶  Ejecutar ahora",
            fg_color="#1a6b2a", hover_color="#228b36", width=150,
            command=lambda n=nombre: self._forzar_tarea(n),
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btns, text=f"Eliminar tarea",
            fg_color="#8b1a1a", hover_color="#a82020",
            command=lambda: self._eliminar_tarea(nombre),
        ).pack(side="left")

    # =========================================================================
    # Recoleccion del formulario actual → self._data
    # =========================================================================

    def _save_current_section(self):
        if not self._current_section or not self._widget_refs:
            return

        key = self._current_section

        if key == "config_global":
            _str  = ["modelo", "modelo_fallback", "api_key"]
            _int  = []
            _bool = ["log_prompt", "log_respuesta", "log_comandos", "log_salida"]
            for k in _str:
                v = self._val(k)
                if v is not None:
                    self._data[k] = v
            for k in _int:
                v = self._val(k)
                if v is not None:
                    try: self._data[k] = int(v)
                    except ValueError: pass
            for k in _bool:
                v = self._val(k)
                if v is not None:
                    self._data[k] = bool(v)

        elif key == "telegram":
            for campo in ["telegram_token", "telegram_chat_id"]:
                v = self._val(campo)
                if v is not None:
                    self._data[campo] = v
            v = self._val("telegram_activo")
            if v is not None:
                self._data["telegram_activo"] = bool(v)
            v = self._val("telegram_intervalo")
            if v is not None:
                try:
                    self._data["telegram_intervalo"] = int(v)
                except ValueError:
                    pass

        elif key == "ollama_options":
            opts = {}
            for campo in ["temperature", "num_predict", "num_ctx", "num_gpu",
                          "top_k", "top_p", "repeat_penalty", "num_thread", "num_batch"]:
                v = self._val(f"ollama_{campo}")
                if v and str(v).strip():
                    try:
                        opts[campo] = (float(v) if "." in str(v) else int(v))
                    except ValueError:
                        opts[campo] = v
            self._data["ollama_options"] = opts if opts else None

        elif key in ("prompts_sistema", "prompts_verificador"):
            v = self._val(key)
            if isinstance(v, str):
                self._data[key] = [l.rstrip() for l in v.splitlines() if l.strip()]

        elif key == "prompts_fijos":
            v = self._val("prompts_sistema_fijos")
            if isinstance(v, str):
                self._data["prompts_sistema_fijos"] = [l.rstrip() for l in v.splitlines() if l.strip()]

        elif key.startswith("tarea:"):
            nombre = key[6:]
            if "tareas" not in self._data:
                self._data["tareas"] = {}
            tarea = dict(self._data["tareas"].get(nombre, {}))

            v = self._val(f"{nombre}__intervalo")
            if v:
                try: tarea["intervalo"] = int(v)
                except ValueError: pass

            for campo in ["timeout_ollama", "timeout_script", "max_reintentos"]:
                v = self._val(f"{nombre}__{campo}")
                if v and str(v).strip():
                    try: tarea[campo] = int(v)
                    except ValueError: pass
                elif campo in tarea:
                    del tarea[campo]

            v = self._val(f"{nombre}__pv")
            if isinstance(v, str):
                lineas = [l.rstrip() for l in v.splitlines() if l.strip()]
                if lineas:
                    tarea["prompt_verificador"] = lineas
                elif "prompt_verificador" in tarea:
                    del tarea["prompt_verificador"]

            v = self._val(f"{nombre}__prompt")
            if isinstance(v, str):
                tarea["prompt"] = [l.rstrip() for l in v.splitlines() if l.strip()]

            self._data["tareas"][nombre] = tarea

        self._set_modified()

    def _val(self, key):
        ref = self._widget_refs.get(key)
        if ref is None:
            return None
        tipo, widget = ref
        if tipo == "entry":    return widget.get()
        if tipo == "combo":    return widget.get() 
        if tipo == "checkbox": return bool(widget.get())
        if tipo == "textbox":  return widget.get("0.0", "end-1c")
        return None

    def _set_modified(self):
        self._modificado = True
        self._lbl_estado.configure(text="Sin guardar *", text_color="#f0a020")

    # =========================================================================
    # Modo texto (raw)
    # =========================================================================

    def _toggle_raw(self):
        if not self._raw_mode:
            # Guardar form actual y pasar a texto
            self._save_current_section()
            self._raw_mode = True
            self._btn_toggle.configure(text="Ver formulario")
            if self._form_scroll:
                self._form_scroll.grid_forget()
            if self._raw_editor:
                self._raw_editor.destroy()
            self._raw_editor = ctk.CTkTextbox(
                self._form_container,
                font=ctk.CTkFont(family="Consolas", size=12),
            )
            self._raw_editor.grid(row=0, column=0, sticky="nsew")
            try:
                with open(self._path, "r", encoding="utf-8") as fh:
                    self._raw_editor.insert("0.0", fh.read())
            except Exception:
                pass
        else:
            # Volver a formulario
            self._raw_mode = False
            self._btn_toggle.configure(text="Ver texto")
            raw_text = self._raw_editor.get("0.0", "end-1c") if self._raw_editor else ""
            if self._raw_editor:
                self._raw_editor.destroy()
                self._raw_editor = None
            try:
                self._data = yaml.safe_load(raw_text) or {}
                self._rebuild_nav()
                if self._current_section:
                    self._navigate(self._current_section)
                elif self._es_config():
                    self._navigate("config_global")
                else:
                    primera = next(iter((self._data.get("tareas") or {})), None)
                    if primera:
                        self._navigate(f"tarea:{primera}")
            except Exception as e:
                self._lbl_estado.configure(
                    text=f"YAML invalido: {e}", text_color="#e05252")
                self._raw_mode = True
                self._btn_toggle.configure(text="Ver formulario")

    # =========================================================================
    # Nueva tarea / eliminar tarea
    # =========================================================================

    def _forzar_tarea(self, nombre: str):
        import json
        ruta = os.path.join(self.app.SCRIPT_DIR, "state", "forzar_tarea.json")
        try:
            with open(ruta, "w", encoding="utf-8") as f:
                json.dump({"tarea": nombre}, f)
        except Exception:
            pass

    def _nueva_tarea(self):
        win = ctk.CTkToplevel(self)
        win.title("Nueva tarea")
        win.geometry("320x140")
        win.resizable(False, False)
        win.grab_set()
        ctk.CTkLabel(win, text="Nombre de la nueva tarea:").pack(pady=(20, 6))
        var = ctk.StringVar()
        entry = ctk.CTkEntry(win, textvariable=var, width=200)
        entry.pack()
        entry.focus()

        def _crear():
            nombre = var.get().strip().replace(" ", "_")
            if not nombre:
                return
            if "tareas" not in self._data:
                self._data["tareas"] = {}
            self._data["tareas"][nombre] = {
                "intervalo":      60,
                "timeout_ollama": 300,
                "timeout_script": 120,
                "max_reintentos": 3,
                "prompt": ["Describe aqui lo que debe hacer el script."],
            }
            win.destroy()
            self._rebuild_nav()
            self._navigate(f"tarea:{nombre}")

        ctk.CTkButton(win, text="Crear", command=_crear, width=100).pack(pady=14)
        win.bind("<Return>", lambda e: _crear())

    def _eliminar_tarea(self, nombre: str):
        win = ctk.CTkToplevel(self)
        win.title("Confirmar")
        win.geometry("300x120")
        win.resizable(False, False)
        win.grab_set()
        ctk.CTkLabel(win, text=f"¿Eliminar tarea '{nombre}'?",
                     font=ctk.CTkFont(size=13)).pack(pady=16)
        frame = ctk.CTkFrame(win, fg_color="transparent")
        frame.pack()

        def _ok():
            tareas = self._data.get("tareas") or {}
            if nombre in tareas:
                del tareas[nombre]
            self._current_section = None
            self._widget_refs = {}
            win.destroy()
            self._rebuild_nav()
            self._clear_form()

        ctk.CTkButton(frame, text="Eliminar", fg_color="#8b1a1a",
                      command=_ok).pack(side="left", padx=8)
        ctk.CTkButton(frame, text="Cancelar",
                      command=win.destroy).pack(side="left", padx=8)

    # =========================================================================
    # Carga / guardado
    # =========================================================================

    def cargar_archivo(self, path: str):
        self._path = path
        try:
            with open(path, "r", encoding="utf-8") as fh:
                self._data = yaml.safe_load(fh) or {}
            self._current_section = None
            self._widget_refs = {}
            self._modificado  = False
            self._raw_mode    = False
            self._lbl_path.configure(text=os.path.basename(path))
            self._lbl_estado.configure(text="Cargado", text_color="#52c252")
            self.after(2000, lambda: self._lbl_estado.configure(text=""))
            self._rebuild_nav()
            if self._es_config():
                self._navigate("config_global")
            else:
                primera = next(iter((self._data.get("tareas") or {})), None)
                if primera:
                    self._navigate(f"tarea:{primera}")
        except Exception as e:
            self._lbl_estado.configure(text=f"Error: {e}", text_color="#e05252")

    def guardar(self):
        if self._raw_mode and self._raw_editor:
            raw = self._raw_editor.get("0.0", "end-1c")
            try:
                yaml.safe_load(raw)   # validar
            except Exception as e:
                self._lbl_estado.configure(
                    text=f"YAML invalido: {e}", text_color="#e05252")
                return
            with open(self._path, "w", encoding="utf-8") as fh:
                fh.write(raw)
        else:
            self._save_current_section()
            try:
                with open(self._path, "w", encoding="utf-8") as fh:
                    yaml.dump(self._data, fh,
                              default_flow_style=False,
                              allow_unicode=True,
                              sort_keys=False,
                              indent=2)
            except Exception as e:
                self._lbl_estado.configure(
                    text=f"Error al guardar: {e}", text_color="#e05252")
                return

        self._modificado = False
        self._lbl_estado.configure(text="Guardado ✓", text_color="#52c252")
        self.after(2000, lambda: self._lbl_estado.configure(text=""))

    def _recargar(self):
        if self._modificado:
            win = ctk.CTkToplevel(self)
            win.title("Confirmar")
            win.geometry("320x130")
            win.resizable(False, False)
            win.grab_set()
            ctk.CTkLabel(win,
                         text="Hay cambios sin guardar.\n¿Recargar de todas formas?",
                         justify="center").pack(pady=20)
            frame = ctk.CTkFrame(win, fg_color="transparent")
            frame.pack()
            ctk.CTkButton(frame, text="Recargar", fg_color="#8b1a1a",
                          command=lambda: (win.destroy(),
                                          self.cargar_archivo(self._path))
                          ).pack(side="left", padx=8)
            ctk.CTkButton(frame, text="Cancelar",
                          command=win.destroy).pack(side="left", padx=8)
        else:
            self.cargar_archivo(self._path)
