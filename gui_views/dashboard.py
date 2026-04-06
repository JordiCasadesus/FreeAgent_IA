"""gui_views/dashboard.py - Vista de estado de las tareas

Muestra una tarjeta por cada tarea con:
  - Nombre de la tarea
  - Estado (OK / ERR / Pendiente)
  - Ultima ejecucion y tiempo transcurrido
  - Preview de la ultima salida
  - Boton para ver el resultado completo en un popup
"""

import os
import json
import datetime

import customtkinter as ctk

STATUS_OK      = "#52c252"
STATUS_ERR     = "#e05252"
STATUS_PENDING = "#f0a020"
STATUS_UNKNOWN = "#888888"


class DashboardView(ctk.CTkScrollableFrame):

    _SPINNER = ["◐", "◓", "◑", "◒"]

    def __init__(self, parent, app):
        super().__init__(parent, label_text="", fg_color="transparent")
        self.app           = app
        self._cards        = {}
        self._statuses     = {}
        self._spinner_idx  = 0
        self._tarea_activa = None
        self._build_header()
        self._refresh()
        self._animar_spinner()

    # =========================================================================
    # Layout
    # =========================================================================

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(16, 8))

        ctk.CTkLabel(header, text="Dashboard",
                     font=ctk.CTkFont(size=20, weight="bold")).pack(side="left")

        ctk.CTkButton(header, text="↺ Actualizar", width=110,
                      command=self._refresh).pack(side="right")

        # Leyenda de colores
        leyenda = ctk.CTkFrame(header, fg_color="transparent")
        leyenda.pack(side="right", padx=16)
        for color, texto in [
            (STATUS_OK,      "OK"),
            (STATUS_PENDING, "Pendiente"),
            (STATUS_ERR,     "Error"),
            (STATUS_UNKNOWN, "Sin datos"),
        ]:
            ctk.CTkLabel(leyenda, text=f"● {texto}",
                         text_color=color,
                         font=ctk.CTkFont(size=11)).pack(side="left", padx=6)

        self._lbl_updated = ctk.CTkLabel(header, text="", text_color="#888",
                                          font=ctk.CTkFont(size=11))
        self._lbl_updated.pack(side="right", padx=12)

    def _build_card(self, nombre: str) -> dict:
        card = ctk.CTkFrame(self, corner_radius=8)
        card.pack(fill="x", padx=16, pady=3)
        card.columnconfigure(2, weight=1)

        # Col 0 — indicador de color
        dot = ctk.CTkLabel(card, text="●", font=ctk.CTkFont(size=16),
                            text_color=STATUS_UNKNOWN, width=28)
        dot.grid(row=0, column=0, padx=(10, 2), pady=6)

        # Col 1 — nombre
        lbl_nombre = ctk.CTkLabel(card, text=nombre,
                                   font=ctk.CTkFont(size=13, weight="bold"),
                                   anchor="w")
        lbl_nombre.grid(row=0, column=1, sticky="w", padx=4, pady=6)

        # Col 2 — preview salida
        lbl_salida = ctk.CTkLabel(card, text="", anchor="w",
                                   text_color="#888", font=ctk.CTkFont(size=11))
        lbl_salida.grid(row=0, column=2, sticky="ew", padx=4, pady=6)

        # Col 3 — badge OK/ERR
        lbl_estado = ctk.CTkLabel(card, text="—", width=50, anchor="center",
                                   font=ctk.CTkFont(size=11, weight="bold"),
                                   text_color=STATUS_UNKNOWN)
        lbl_estado.grid(row=0, column=3, padx=4, pady=6)

        # Col 4 — tiempo
        lbl_tiempo = ctk.CTkLabel(card, text="—", width=100, anchor="e",
                                   text_color="#888", font=ctk.CTkFont(size=11))
        lbl_tiempo.grid(row=0, column=4, padx=(0, 4), pady=6)

        # Col 5 — boton ejecutar
        btn_run = ctk.CTkButton(
            card, text="▶", width=32, height=26,
            fg_color="#1a6b2a", hover_color="#228b36",
            command=lambda n=nombre: self._forzar_tarea(n),
        )
        btn_run.grid(row=0, column=5, padx=(0, 4), pady=6)

        # Col 6 — boton detalle
        btn_detalle = ctk.CTkButton(
            card, text="Ver ↗", width=60, height=26,
            fg_color="#2b2b2b", hover_color="#3a3a3a",
            command=lambda n=nombre: self._mostrar_detalle(n),
        )
        btn_detalle.grid(row=0, column=6, padx=(0, 10), pady=6)

        return {
            "frame":   card,
            "dot":     dot,
            "estado":  lbl_estado,
            "salida":  lbl_salida,
            "tiempo":  lbl_tiempo,
            "btn_run": btn_run,
            "btn":     btn_detalle,
        }

    # =========================================================================
    # Popup de detalle
    # =========================================================================

    def _forzar_tarea(self, nombre: str):
        ruta = os.path.join(self.app.SCRIPT_DIR, "state", "forzar_tarea.json")
        try:
            with open(ruta, "w", encoding="utf-8") as f:
                json.dump({"tarea": nombre}, f)
        except Exception:
            pass

    def _mostrar_detalle(self, nombre: str):
        st     = self._statuses.get(nombre, {})
        tipo   = st.get("tipo", "—")
        header = st.get("header", "")
        salida = st.get("salida", "")

        color_titulo = STATUS_OK if tipo == "OK" else (
                       STATUS_ERR if tipo == "ERR" else STATUS_UNKNOWN)

        win = ctk.CTkToplevel(self)
        win.title(f"Resultado — {nombre}")
        win.geometry("820x540")
        win.minsize(600, 400)

        # Cabecera del popup
        top = ctk.CTkFrame(win, fg_color="#1e1e1e", corner_radius=0)
        top.pack(fill="x")

        ctk.CTkLabel(top, text=f"● {nombre}",
                     text_color=color_titulo,
                     font=ctk.CTkFont(size=16, weight="bold")).pack(
            side="left", padx=16, pady=10)

        ctk.CTkLabel(top, text=header,
                     text_color="#888",
                     font=ctk.CTkFont(size=12)).pack(
            side="left", padx=8)

        ctk.CTkButton(top, text="Cerrar", width=80,
                      command=win.destroy).pack(side="right", padx=12, pady=8)

        # Contenido
        tb = ctk.CTkTextbox(win,
                            font=ctk.CTkFont(family="Consolas", size=12),
                            wrap="none")
        tb.pack(fill="both", expand=True, padx=12, pady=12)

        if salida.strip():
            tb.insert("0.0", salida)
        else:
            tb.insert("0.0", "(sin salida registrada)")

        tb.configure(state="disabled")
        win.grab_set()

    # =========================================================================
    # Refresco de datos
    # =========================================================================

    def _refresh(self):
        estado     = self._leer_estado()
        statuses   = self._leer_log_status()
        tareas     = self._leer_tareas_nombres()
        intervalos = self._leer_intervalos()

        self._tarea_activa = self._leer_tarea_actual()
        self._statuses = statuses

        # Eliminar tarjetas de tareas que ya no existen
        for nombre in list(self._cards):
            if nombre not in tareas:
                self._cards[nombre]["frame"].destroy()
                del self._cards[nombre]

        # Crear tarjetas nuevas
        for nombre in tareas:
            if nombre not in self._cards:
                self._cards[nombre] = self._build_card(nombre)

        ahora = datetime.datetime.now()
        for nombre, widgets in self._cards.items():
            ultima = estado.get(nombre)
            st     = statuses.get(nombre, {})

            # Tiempo
            widgets["tiempo"].configure(
                text=self._fmt_delta(ahora - ultima) if ultima else "Nunca")

            # Estado
            tipo = st.get("tipo", "")
            if tipo == "OK":
                color, badge = STATUS_OK,  "OK"
            elif tipo == "ERR":
                color, badge = STATUS_ERR, "ERR"
            elif ultima:
                intervalo = intervalos.get(nombre, 0)
                segundos  = (ahora - ultima).total_seconds()
                if intervalo and segundos < intervalo:
                    color, badge = STATUS_OK, "OK"      # ejecucion reciente en estado.json
                else:
                    color, badge = STATUS_PENDING, "?"  # hace demasiado tiempo
            else:
                color, badge = STATUS_UNKNOWN, "—"

            if nombre != self._tarea_activa:
                widgets["dot"].configure(text="●", text_color=color)
            else:
                widgets["dot"].configure(text_color=color)  # spinner maneja el texto
            widgets["estado"].configure(text=badge, text_color=color)

            # Preview: 2 lineas de la salida
            salida = st.get("salida", "")
            lineas = [l for l in salida.splitlines() if l.strip()][:2]
            preview = "  |  ".join(lineas) if lineas else ""
            widgets["salida"].configure(text=preview)

            # Activar/desactivar boton segun haya datos
            widgets["btn"].configure(
                state="normal" if salida.strip() else "disabled")

        self._lbl_updated.configure(
            text=f"Actualizado: {ahora.strftime('%H:%M:%S')}")

        self.after(5000, self._refresh)

    # =========================================================================
    # Lectura de datos
    # =========================================================================

    def _leer_estado(self) -> dict:
        try:
            with open(self.app.ESTADO_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return {
                k: datetime.datetime.strptime(v, "%Y-%m-%d %H:%M:%S")
                for k, v in raw.items()
            }
        except Exception:
            return {}

    def _leer_log_status(self) -> dict:
        """Parsea agente.log (tablon de estado) → {nombre: {tipo, header, salida}}."""
        try:
            with open(self.app.LOG_PATH, "r", encoding="utf-8") as f:
                contenido = f.read()
        except Exception:
            return {}

        result = {}
        for bloque in contenido.split("=" * 48):
            bloque = bloque.strip()
            if not bloque:
                continue
            lineas  = bloque.split("\n")
            primera = lineas[0].strip()
            resto   = "\n".join(lineas[1:]).strip()

            if primera.startswith("OK  ["):
                try:
                    nombre = primera[5:primera.index("]")]
                    result[nombre] = {
                        "tipo":   "OK",
                        "header": primera,
                        "salida": resto,
                    }
                except ValueError:
                    pass
            elif primera.startswith("ERR ["):
                try:
                    nombre = primera[5:primera.index("]")]
                    result[nombre] = {
                        "tipo":   "ERR",
                        "header": primera,
                        "salida": primera + ("\n" + resto if resto else ""),
                    }
                except ValueError:
                    pass

        return result

    def _leer_intervalos(self) -> dict:
        """Devuelve {nombre_tarea: intervalo_segundos}."""
        try:
            import yaml
            with open(self.app.TAREAS_PATH, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            return {
                nombre: int(t.get("intervalo", 0))
                for nombre, t in raw.get("tareas", {}).items()
            }
        except Exception:
            return {}

    def _leer_tarea_actual(self) -> str:
        try:
            ruta = os.path.join(self.app.SCRIPT_DIR, "state", "tarea_actual.json")
            with open(ruta, "r", encoding="utf-8") as f:
                return json.load(f).get("tarea", "")
        except Exception:
            return ""

    def _agente_corriendo(self) -> bool:
        p = self.app.agent_process
        return p is not None and p.poll() is None

    def _animar_spinner(self):
        if self._agente_corriendo() and self._tarea_activa and self._tarea_activa in self._cards:
            frame = self._SPINNER[self._spinner_idx % len(self._SPINNER)]
            self._cards[self._tarea_activa]["dot"].configure(text=frame)
            self._spinner_idx += 1
        self.after(200, self._animar_spinner)

    def _leer_tareas_nombres(self) -> list:
        try:
            import yaml
            with open(self.app.TAREAS_PATH, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            return list(raw.get("tareas", {}).keys())
        except Exception:
            return list(self._cards.keys())

    @staticmethod
    def _fmt_delta(delta: datetime.timedelta) -> str:
        s = int(delta.total_seconds())
        if s < 0:    return "ahora"
        if s < 60:   return f"hace {s}s"
        if s < 3600: return f"hace {s // 60}m {s % 60}s"
        return f"hace {s // 3600}h {(s % 3600) // 60}m"
