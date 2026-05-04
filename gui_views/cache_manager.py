"""gui_views/cache_manager.py - Gestor de scripts en cache

Muestra los scripts .py generados en scripts_cache/.
Permite ver su contenido y eliminarlos individualmente o todos.
"""

import os
import datetime

import customtkinter as ctk
from PIL import Image
from pygments import lex
from pygments.lexers import PythonLexer
from pygments.token import Token

_ICONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "imagenes", "iconos", "32x32")

def _icon(name: str, size: int = 16) -> ctk.CTkImage | None:
    try:
        return ctk.CTkImage(Image.open(os.path.join(_ICONS_DIR, name)), size=(size, size))
    except Exception:
        return None


class CacheManagerView(ctk.CTkFrame):

    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app          = app
        self._seleccionado = None

        self._build()
        self.actualizar()

    # =========================================================================
    # Layout
    # =========================================================================

    def _build(self):
        # ── Toolbar ──────────────────────────────────────────────────────────
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=16, pady=(12, 6))

        ctk.CTkLabel(toolbar, text="Cache de scripts",
                     font=ctk.CTkFont(size=20, weight="bold")).pack(side="left")

        ctk.CTkButton(toolbar, text="Eliminar todo",
                      fg_color="#8b1a1a", hover_color="#a82020", width=110,
                      command=self.eliminar_todo).pack(side="right", padx=4)

        ctk.CTkButton(toolbar, text="Eliminar seleccionado", width=150,
                      fg_color="#6b3a1a", hover_color="#8b5020",
                      command=self._eliminar_seleccionado).pack(side="right", padx=4)

        ctk.CTkButton(toolbar, text="↺ Actualizar", width=100,
                      command=self.actualizar).pack(side="right", padx=4)

        self._lbl_info = ctk.CTkLabel(toolbar, text="", text_color="#888",
                                       font=ctk.CTkFont(size=11))
        self._lbl_info.pack(side="right", padx=10)

        # ── Panel principal: lista izquierda + visor derecho ─────────────────
        panel = ctk.CTkFrame(self, fg_color="transparent")
        panel.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        panel.columnconfigure(1, weight=1)
        panel.rowconfigure(0, weight=1)

        # Lista de scripts
        self._lista_frame = ctk.CTkScrollableFrame(panel, width=210, label_text="Scripts")
        self._lista_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self._item_buttons: list[ctk.CTkButton] = []

        # Panel derecho
        derecho = ctk.CTkFrame(panel, fg_color="transparent")
        derecho.grid(row=0, column=1, sticky="nsew")
        derecho.rowconfigure(2, weight=1)
        derecho.columnconfigure(0, weight=1)

        # Info del archivo seleccionado
        self._lbl_meta = ctk.CTkLabel(derecho, text="Selecciona un script de la lista",
                                       text_color="#888", anchor="w",
                                       font=ctk.CTkFont(size=12))
        self._lbl_meta.grid(row=0, column=0, sticky="w", pady=(0, 4))

        # Botones de acción
        acciones = ctk.CTkFrame(derecho, fg_color="transparent")
        acciones.grid(row=1, column=0, sticky="ew", pady=(0, 6))

        self._btn_copiar = ctk.CTkButton(
            acciones, text="📋 Copiar", width=150,
            fg_color="#1a4a7a", hover_color="#1f6aa5", state="disabled",
            command=self._copiar_para_ia,
        )
        self._btn_copiar.pack(side="left", padx=(0, 8))

        self._btn_reemplazar = ctk.CTkButton(
            acciones, text="✏ Reemplazar script", width=160,
            fg_color="#5a3a1a", hover_color="#8b5a20", state="disabled",
            command=self._reemplazar_script,
        )
        self._btn_reemplazar.pack(side="left")

        # Visor de contenido
        self._visor = ctk.CTkTextbox(
            derecho, font=ctk.CTkFont(family="Consolas", size=12),
            wrap="none", state="disabled",
        )
        self._visor.grid(row=2, column=0, sticky="nsew")
        self._setup_tags()

    # =========================================================================
    # Syntax highlighting
    # =========================================================================

    def _setup_tags(self):
        t = self._visor._textbox
        t.tag_config("keyword",   foreground="#569CD6")
        t.tag_config("builtin",   foreground="#4EC9B0")
        t.tag_config("string",    foreground="#CE9178")
        t.tag_config("comment",   foreground="#6A9955")
        t.tag_config("number",    foreground="#B5CEA8")
        t.tag_config("operator",  foreground="#D4D4D4")
        t.tag_config("decorator", foreground="#DCDCAA")
        t.tag_config("funcname",  foreground="#DCDCAA")
        t.tag_config("classname", foreground="#4EC9B0")

    def _token_tag(self, ttype) -> str:
        if ttype in Token.Keyword or ttype in Token.Keyword.Namespace:
            return "keyword"
        if ttype in Token.Name.Builtin or ttype in Token.Name.Builtin.Pseudo:
            return "builtin"
        if ttype in Token.Name.Decorator:
            return "decorator"
        if ttype in Token.Name.Function:
            return "funcname"
        if ttype in Token.Name.Class:
            return "classname"
        if ttype in Token.Literal.String or ttype in Token.String:
            return "string"
        if ttype in Token.Comment:
            return "comment"
        if ttype in Token.Literal.Number or ttype in Token.Number:
            return "number"
        if ttype in Token.Operator or ttype in Token.Punctuation:
            return "operator"
        return ""

    def _insertar_con_colores(self, codigo: str):
        t = self._visor._textbox
        t.configure(state="normal")
        t.delete("1.0", "end")
        for ttype, value in lex(codigo, PythonLexer()):
            tag = self._token_tag(ttype)
            if tag:
                t.insert("end", value, tag)
            else:
                t.insert("end", value)
        t.configure(state="disabled")

    # =========================================================================
    # Actualizacion de la lista
    # =========================================================================

    def actualizar(self):
        # Limpiar lista anterior
        for btn in self._item_buttons:
            btn.destroy()
        self._item_buttons.clear()

        cache = self.app.CACHE_PATH
        try:
            archivos = sorted([
                f for f in os.listdir(cache)
                if f.endswith(".py")
            ])
        except Exception:
            archivos = []

        _icono = _icon("Graphic file.png")
        for nombre in archivos:
            path = os.path.join(cache, nombre)
            btn = ctk.CTkButton(
                self._lista_frame,
                text=f"  {nombre.replace('.py', '')}",
                anchor="w",
                image=_icono, compound="left",
                height=32, font=ctk.CTkFont(size=12),
                fg_color="#2b2b2b", hover_color="#3a3a3a",
                command=lambda p=path, n=nombre: self._seleccionar(p, n),
            )
            btn.pack(fill="x", pady=2)
            self._item_buttons.append(btn)

        total = len(archivos)
        self._lbl_info.configure(
            text=f"{total} script{'s' if total != 1 else ''} en cache"
        )

        if self._seleccionado and os.path.exists(self._seleccionado):
            self._seleccionar(self._seleccionado,
                              os.path.basename(self._seleccionado))

    def _seleccionar(self, path: str, nombre: str):
        self._seleccionado = path

        # Resaltar boton seleccionado
        for btn in self._item_buttons:
            color = "#1f6aa5" if btn.cget("text") == nombre.replace(".py", "") else "#2b2b2b"
            btn.configure(fg_color=color)

        # Leer contenido
        try:
            with open(path, "r", encoding="utf-8") as f:
                contenido = f.read()
            stat = os.stat(path)
            tamanio = stat.st_size
            fecha   = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            # Primera linea = "# Generado por: modelo | fecha"
            primera = contenido.split("\n")[0] if contenido else ""
            modelo  = primera.replace("# Generado por: ", "") if primera.startswith("#") else "—"
            meta = f"{nombre}  |  {tamanio} bytes  |  Modificado: {fecha}  |  {modelo}"
        except Exception as e:
            contenido = f"Error al leer: {e}"
            meta = nombre

        self._lbl_meta.configure(text=meta)
        self._insertar_con_colores(contenido)
        self._btn_copiar.configure(state="normal")
        self._btn_reemplazar.configure(state="normal")

    # =========================================================================
    # Copiar para IA / Reemplazar
    # =========================================================================

    def _copiar_para_ia(self):
        if not self._seleccionado:
            return
        nombre_tarea = os.path.basename(self._seleccionado).replace(".py", "")

        # Leer prompts_sistema desde config.yaml
        prompts_sistema = []
        try:
            import yaml
            with open(self.app.CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            prompts_sistema = cfg.get("prompts_sistema") or []
        except Exception:
            pass

        # Leer prompt de la tarea desde tareas.yaml
        prompt_tarea = []
        try:
            import yaml
            with open(self.app.TAREAS_PATH, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            tarea = (raw.get("tareas") or {}).get(nombre_tarea, {})
            prompt_tarea = tarea.get("prompt") or []
        except Exception:
            pass

        # Leer script del cache
        try:
            with open(self._seleccionado, "r", encoding="utf-8") as f:
                script = f.read()
        except Exception:
            script = ""

        partes = [
            "=== CONTEXTO DEL AGENTE ===",
            "\n".join(prompts_sistema),
            "",
            f"=== TAREA: {nombre_tarea} ===",
            "\n".join(prompt_tarea),
            "",
            "=== SCRIPT GENERADO ===",
            script,
            "",
            "=== SOLICITUD ===",
            "Revisa este script Python. ¿Es correcto para la tarea descrita?",
            "Si tiene errores o puede mejorar, propón una versión corregida completa.",
        ]
        texto = "\n".join(partes)
        self.clipboard_clear()
        self.clipboard_append(texto)
        self._btn_copiar.configure(text="✓ Copiado!")
        self.after(2000, lambda: self._btn_copiar.configure(text="📋 Copiar para IA"))

    def _reemplazar_script(self):
        if not self._seleccionado:
            return

        win = ctk.CTkToplevel(self)
        win.title("Reemplazar script")
        win.geometry("820x580")
        win.minsize(600, 400)
        win.grab_set()

        ctk.CTkLabel(win, text="Pega aquí el script corregido:",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(
            anchor="w", padx=16, pady=(14, 4))

        editor = ctk.CTkTextbox(win, font=ctk.CTkFont(family="Consolas", size=12), wrap="none")
        editor.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        # Precarga el script actual
        try:
            with open(self._seleccionado, "r", encoding="utf-8") as f:
                editor.insert("0.0", f.read())
        except Exception:
            pass

        def aplicar():
            nuevo = editor.get("0.0", "end-1c").strip()
            if not nuevo:
                return
            try:
                with open(self._seleccionado, "w", encoding="utf-8") as f:
                    f.write(nuevo)
                hash_path = self._seleccionado.replace(".py", ".hash")
                if os.path.exists(hash_path):
                    os.remove(hash_path)
            except Exception as e:
                ctk.CTkLabel(win, text=f"Error: {e}", text_color="#e05252").pack()
                return
            win.destroy()
            self.actualizar()

        bar = ctk.CTkFrame(win, fg_color="transparent")
        bar.pack(fill="x", padx=16, pady=(0, 14))
        ctk.CTkButton(bar, text="Aplicar", fg_color="#1a6b2a", hover_color="#228b36",
                      command=aplicar).pack(side="right", padx=(8, 0))
        ctk.CTkButton(bar, text="Cancelar", fg_color="#555", hover_color="#666",
                      command=win.destroy).pack(side="right")

    # =========================================================================
    # Eliminacion
    # =========================================================================

    def _eliminar_seleccionado(self):
        if not self._seleccionado or not os.path.exists(self._seleccionado):
            return
        hash_path = self._seleccionado.replace(".py", ".hash")
        try:
            os.remove(self._seleccionado)
            if os.path.exists(hash_path):
                os.remove(hash_path)
        except Exception as e:
            self._lbl_info.configure(text=f"Error: {e}", text_color="#e05252")
            return
        self._seleccionado = None
        self._visor.configure(state="normal")
        self._visor.delete("0.0", "end")
        self._visor.configure(state="disabled")
        self._lbl_meta.configure(text="Selecciona un script de la lista")
        self.actualizar()

    def eliminar_todo(self):
        cache = self.app.CACHE_PATH
        win = ctk.CTkToplevel(self)
        win.title("Confirmar")
        win.geometry("320x130")
        win.resizable(False, False)
        win.grab_set()
        ctk.CTkLabel(win, text="Eliminar TODOS los scripts en cache?\nEl agente los regenerara en el proximo ciclo.",
                     justify="center").pack(pady=16)
        frame = ctk.CTkFrame(win, fg_color="transparent")
        frame.pack()

        def _confirmar():
            win.destroy()
            try:
                for f in os.listdir(cache):
                    if f.endswith(".py") or f.endswith(".hash"):
                        os.remove(os.path.join(cache, f))
            except Exception:
                pass
            self._seleccionado = None
            self._visor.configure(state="normal")
            self._visor.delete("0.0", "end")
            self._visor.configure(state="disabled")
            self._lbl_meta.configure(text="Selecciona un script de la lista")
            self.actualizar()

        ctk.CTkButton(frame, text="Eliminar todo",
                      fg_color="#8b1a1a", command=_confirmar).pack(side="left", padx=8)
        ctk.CTkButton(frame, text="Cancelar",
                      command=win.destroy).pack(side="left", padx=8)
