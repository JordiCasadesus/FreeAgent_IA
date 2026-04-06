"""gui_views/log_viewer.py - Visor de logs con dos pestanas

Resultados : solo outputs exitosos (agente.log), se refresca en sitio
Historial  : agente_history.log completo con colores y filtro
"""

import os
import re
import json
import datetime

import yaml
import customtkinter as ctk


class LogViewerView(ctk.CTkFrame):

    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app     = app
        self._pos    = 0
        self._paused = False
        self._result_blocks: dict = {}   # {nombre: CTkTextbox}

        self._build()
        self._load_initial_historial()
        self._tail_historial()
        self._refresh_resultados()

    # =========================================================================
    # Layout principal con pestanas
    # =========================================================================

    def _build(self):
        self._tabs = ctk.CTkTabview(self, anchor="nw")
        self._tabs.pack(fill="both", expand=True, padx=8, pady=8)

        self._tabs.add("Resultados")
        self._tabs.add("Historial")

        self._build_resultados(self._tabs.tab("Resultados"))
        self._build_historial(self._tabs.tab("Historial"))

    # =========================================================================
    # Pestana Resultados
    # =========================================================================

    def _build_resultados(self, tab):
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)

        header = ctk.CTkFrame(tab, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))

        ctk.CTkLabel(header, text="Ultimos resultados exitosos",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")


        self._results_scroll = ctk.CTkScrollableFrame(
            tab, fg_color="transparent")
        self._results_scroll.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self._results_scroll.columnconfigure(0, weight=1)

    def _refresh_resultados(self):
        # 1. Todas las tareas y sus intervalos desde tareas.yaml
        tareas = {}
        try:
            with open(self.app.TAREAS_PATH, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            tareas = raw.get("tareas") or {}
        except Exception:
            pass

        # 2. Ultimas ejecuciones desde estado.json
        ultimas = {}
        try:
            with open(self.app.ESTADO_PATH, "r", encoding="utf-8") as f:
                estado = json.load(f)
            for k, v in estado.items():
                ultimas[k] = datetime.datetime.strptime(v, "%Y-%m-%d %H:%M:%S")
        except Exception:
            pass

        # 3. Outputs desde agente.log
        outputs = {}
        try:
            with open(self.app.LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            for bloque in content.split("=" * 48):
                bloque = bloque.strip()
                if not bloque:
                    continue
                lineas = bloque.splitlines()
                if lineas and lineas[0].startswith("OK"):
                    m = re.match(r"OK\s+\[(.+?)\]", lineas[0])
                    if m:
                        outputs[m.group(1)] = "\n".join(lineas[1:]).strip()
        except Exception:
            pass

        ahora = datetime.datetime.now()
        row   = 0

        for nombre, tarea in tareas.items():
            intervalo = int(tarea.get("intervalo", 60))
            ultima    = ultimas.get(nombre)
            proxima   = (ultima + datetime.timedelta(seconds=intervalo)) if ultima else None
            salida    = outputs.get(nombre, "")

            ts_ultima = ultima.strftime("%Y-%m-%d  %H:%M:%S") if ultima else "nunca"
            if proxima:
                diff = (proxima - ahora).total_seconds()
                if diff <= 0:
                    ts_proxima = "ahora"
                elif diff < 60:
                    ts_proxima = f"en {int(diff)}s"
                elif diff < 3600:
                    ts_proxima = f"en {int(diff//60)}m {int(diff%60)}s"
                else:
                    ts_proxima = proxima.strftime("%H:%M:%S")
            else:
                ts_proxima = "pendiente"

            if nombre not in self._result_blocks:
                frame = ctk.CTkFrame(self._results_scroll, fg_color="#1e1e2e",
                                     corner_radius=6)
                frame.grid(row=row, column=0, sticky="ew", pady=4, padx=2)
                frame.columnconfigure(0, weight=1)

                hdr = ctk.CTkFrame(frame, fg_color="#1a4a8a", corner_radius=6)
                hdr.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 2))

                ctk.CTkLabel(hdr, text=nombre,
                             font=ctk.CTkFont(size=12, weight="bold")).pack(
                    side="left", padx=10, pady=3)

                lbl_proxima = ctk.CTkLabel(hdr, text="", text_color="#aaffaa",
                                           font=ctk.CTkFont(size=11))
                lbl_proxima.pack(side="right", padx=10)

                lbl_ultima = ctk.CTkLabel(hdr, text="", text_color="#aaccff",
                                          font=ctk.CTkFont(size=11))
                lbl_ultima.pack(side="right", padx=(0, 4))

                tb = ctk.CTkTextbox(frame,
                                    font=ctk.CTkFont(family="Consolas", size=12),
                                    state="disabled", height=100,
                                    fg_color="#141414")
                tb.grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 6))

                self._result_blocks[nombre] = (lbl_ultima, lbl_proxima, tb)
                row += 1

            lbl_ultima, lbl_proxima, tb = self._result_blocks[nombre]
            lbl_ultima.configure(text=f"Última: {ts_ultima}")
            lbl_proxima.configure(text=f"Próxima: {ts_proxima}")

            texto_nuevo = salida if salida else "(sin resultado todavía)"
            texto_actual = tb._textbox.get("1.0", "end-1c")
            if texto_nuevo != texto_actual:
                # Guardar posicion del scroll exterior antes de cambiar altura
                canvas = self._results_scroll._parent_canvas
                scroll_pos = canvas.yview()[0]

                n_lineas = max(1, texto_nuevo.count("\n") + 1)
                nueva_altura = min(n_lineas * 18 + 8, 400)
                tb.configure(state="normal", height=nueva_altura)
                tb.delete("0.0", "end")
                tb.insert("0.0", texto_nuevo)
                tb.configure(state="disabled")

                # Restaurar posicion del scroll
                self.after(10, lambda p=scroll_pos: canvas.yview_moveto(p))

        self.after(5000, self._refresh_resultados)

    # =========================================================================
    # Pestana Historial
    # =========================================================================

    def _build_historial(self, tab):
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)

        # Una sola barra compacta con todo
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 4))

        ctk.CTkLabel(bar, text="Filtro:").pack(side="left", padx=(0, 4))
        self._filtro_var = ctk.StringVar()
        ctk.CTkEntry(bar, textvariable=self._filtro_var,
                     placeholder_text="Texto a buscar...",
                     width=220).pack(side="left")
        ctk.CTkButton(bar, text="Aplicar", width=70,
                      command=self._aplicar_filtro).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="Quitar", width=65,
                      command=self._quitar_filtro).pack(side="left", padx=(0, 12))

        ctk.CTkButton(bar, text="Limpiar", width=80,
                      command=self._clear).pack(side="right", padx=4)
        ctk.CTkButton(bar, text="↓ Final", width=75,
                      command=self._scroll_end).pack(side="right", padx=4)

        self._chk_autoscroll = ctk.CTkCheckBox(bar, text="Auto-scroll")
        self._chk_autoscroll.select()
        self._chk_autoscroll.pack(side="right", padx=8)

        self._chk_pause = ctk.CTkCheckBox(bar, text="Pausar",
                                           command=self._toggle_pause)
        self._chk_pause.pack(side="right", padx=4)

        self._lbl_info = ctk.CTkLabel(bar, text="", text_color="#888",
                                       font=ctk.CTkFont(size=11))
        self._lbl_info.pack(side="right", padx=8)

        self._text = ctk.CTkTextbox(
            tab, font=ctk.CTkFont(family="Consolas", size=12),
            wrap="none", state="disabled")
        self._text.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        tab.rowconfigure(1, weight=1)

        self._text._textbox.tag_config("ok",      foreground="#52c252")
        self._text._textbox.tag_config("err",     foreground="#e05252")
        self._text._textbox.tag_config("warn",    foreground="#f0a020")
        self._text._textbox.tag_config("section", foreground="#5599dd")

    # =========================================================================
    # Lectura historial
    # =========================================================================

    def _load_initial_historial(self):
        path = self.app.HISTORY_PATH
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lineas = f.readlines()
                self._pos = f.tell()
            self._write_lines(lineas[-200:])
        except Exception:
            pass

    def _tail_historial(self):
        if not self._paused:
            path = self.app.HISTORY_PATH
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(self._pos)
                        nuevas = f.readlines()
                        self._pos = f.tell()
                    if nuevas:
                        self._write_lines(nuevas)
                except Exception:
                    pass
        self.after(2000, self._tail_historial)

    def _write_lines(self, lineas: list):
        self._text.configure(state="normal")
        for linea in lineas:
            tag = self._tag_for(linea)
            if tag:
                self._text._textbox.insert("end", linea, tag)
            else:
                self._text._textbox.insert("end", linea)
        self._text.configure(state="disabled")
        if self._chk_autoscroll.get():
            self._scroll_end()
        total = int(self._text._textbox.index("end-1c").split(".")[0])
        self._lbl_info.configure(text=f"{total} lineas")

    @staticmethod
    def _tag_for(linea: str) -> str:
        l = linea.strip()
        if "OK  [" in l or "] Completado" in l:
            return "ok"
        if "ERR [" in l or "ERROR" in l or "fallo" in l.lower() or "Fallo" in l:
            return "err"
        if "ADVERTENCIA" in l or "Timeout" in l:
            return "warn"
        if "====" in l or "TAREA:" in l:
            return "section"
        return ""

    # =========================================================================
    # Controles historial
    # =========================================================================

    def _scroll_end(self):
        self._text._textbox.see("end")

    def _clear(self):
        self._text.configure(state="normal")
        self._text.delete("0.0", "end")
        self._text.configure(state="disabled")
        self._pos = 0
        self._load_initial_historial()

    def _toggle_pause(self):
        self._paused = bool(self._chk_pause.get())

    def _aplicar_filtro(self):
        texto = self._filtro_var.get().strip()
        if not texto:
            return
        path = self.app.HISTORY_PATH
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lineas = [l for l in f.readlines() if texto.lower() in l.lower()]
        except Exception:
            return
        self._text.configure(state="normal")
        self._text.delete("0.0", "end")
        self._text.configure(state="disabled")
        self._write_lines(lineas)
        self._lbl_info.configure(text=f"{len(lineas)} coincidencias para '{texto}'")

    def _quitar_filtro(self):
        self._filtro_var.set("")
        self._text.configure(state="normal")
        self._text.delete("0.0", "end")
        self._text.configure(state="disabled")
        self._pos = 0
        self._load_initial_historial()
