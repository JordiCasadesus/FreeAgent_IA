"""gui.py - Ventana principal de FreeAgent_IA

Layout:
  - Menu bar superior (Archivo, Agente, Ayuda)
  - Sidebar izquierdo: navegacion + botones Iniciar/Detener
  - Area de contenido: vista activa (dashboard, log, yaml, cache)
"""

import os
import sys
import subprocess
import tkinter as tk
from typing import Optional, Any

import customtkinter as ctk
from PIL import Image

from gui_views.dashboard     import DashboardView
from gui_views.log_viewer    import LogViewerView
from gui_views.yaml_editor   import YamlEditorView
from gui_views.cache_manager import CacheManagerView

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
AGENTE_PY    = os.path.join(SCRIPT_DIR, "agente.py")
CONFIG_PATH  = os.path.join(SCRIPT_DIR, "config", "config.yaml")
TAREAS_PATH  = os.path.join(SCRIPT_DIR, "config", "tareas.yaml")
LOG_PATH     = os.path.join(SCRIPT_DIR, "logs", "agente.log")
HISTORY_PATH = os.path.join(SCRIPT_DIR, "logs", "agente_history.log")
CACHE_PATH   = os.path.join(SCRIPT_DIR, "scripts_cache")
STATE_DIR    = os.path.join(SCRIPT_DIR, "state")
ESTADO_PATH  = os.path.join(STATE_DIR, "estado.json")

ICONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "imagenes", "iconos", "32x32")

NAV_ITEMS = [
    ("Dashboard", "dashboard", "#1f6aa5", "Monitor.png"),
    ("Resultados", "log",       "#2a8a5a", "List.png"),
    ("Config",    "config",    "#c47a1a", "Settings.png"),
    ("Tareas",    "tareas",    "#7a3aaa", "To do list.png"),
    ("Cache",     "cache",     "#1a7a8a", "Save data.png"),
]

COLOR_ACTIVE   = "#1e1e2e"
COLOR_INACTIVE = "#232323"


class App(ctk.CTk):

    # Paths accesibles por las vistas via self.app.XXX
    SCRIPT_DIR   = SCRIPT_DIR
    CONFIG_PATH  = CONFIG_PATH
    TAREAS_PATH  = TAREAS_PATH
    LOG_PATH     = LOG_PATH
    HISTORY_PATH = HISTORY_PATH
    CACHE_PATH   = CACHE_PATH
    ESTADO_PATH  = ESTADO_PATH

    def __init__(self):
        super().__init__()
        self.title("FreeAgent_IA")
        self.geometry("1280x720")
        self.minsize(900, 550)

        self.agent_process: Optional[subprocess.Popen] = None

        self._build_menu()
        self._build_sidebar()
        self._build_content()
        self._poll_agent_status()

        self.show_view("dashboard")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # =========================================================================
    # Menu bar
    # =========================================================================

    def _build_menu(self):
        menubar = tk.Menu(self, bg="#2b2b2b", fg="white",
                          activebackground="#1f6aa5", activeforeground="white")

        m_archivo = tk.Menu(menubar, tearoff=0, bg="#2b2b2b", fg="white",
                            activebackground="#1f6aa5", activeforeground="white")

        m_cfg = tk.Menu(m_archivo, tearoff=0, bg="#2b2b2b", fg="white",
                        activebackground="#1f6aa5", activeforeground="white")
        m_cfg.add_command(label="Abrir...",       command=lambda: self._abrir_yaml("config"))
        m_cfg.add_command(label="Guardar",        command=lambda: self._guardar_yaml("config"))
        m_cfg.add_command(label="Guardar como...", command=lambda: self._guardar_yaml_como("config"))
        m_archivo.add_cascade(label="Configuracion", menu=m_cfg)

        m_tar = tk.Menu(m_archivo, tearoff=0, bg="#2b2b2b", fg="white",
                        activebackground="#1f6aa5", activeforeground="white")
        m_tar.add_command(label="Abrir...",       command=lambda: self._abrir_yaml("tareas"))
        m_tar.add_command(label="Guardar",        command=lambda: self._guardar_yaml("tareas"))
        m_tar.add_command(label="Guardar como...", command=lambda: self._guardar_yaml_como("tareas"))
        m_archivo.add_cascade(label="Tareas", menu=m_tar)

        m_archivo.add_separator()
        m_archivo.add_command(label="Salir",      command=self._on_close)
        menubar.add_cascade(label="Archivo", menu=m_archivo)

        m_agente = tk.Menu(menubar, tearoff=0, bg="#2b2b2b", fg="white",
                           activebackground="#1f6aa5", activeforeground="white")
        m_agente.add_command(label="Iniciar agente", command=self.iniciar_agente)
        m_agente.add_command(label="Detener agente", command=self.detener_agente)
        m_agente.add_separator()
        m_agente.add_command(label="Limpiar cache",  command=self._limpiar_cache)
        menubar.add_cascade(label="Agente", menu=m_agente)

        m_ayuda = tk.Menu(menubar, tearoff=0, bg="#2b2b2b", fg="white",
                          activebackground="#1f6aa5", activeforeground="white")
        m_ayuda.add_command(label="Acerca de", command=self._acerca_de)
        menubar.add_cascade(label="Ayuda", menu=m_ayuda)

        self.configure(menu=menubar)

    # =========================================================================
    # Sidebar
    # =========================================================================

    def _build_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=200, corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        ctk.CTkLabel(self.sidebar, text="⚡ FreeAgent_IA",
                     font=ctk.CTkFont(size=20, weight="bold"),
                     text_color="#5aacff").pack(pady=(22, 2), padx=10)

        self.status_dot = ctk.CTkLabel(self.sidebar, text="● Detenido",
                                       text_color="#e05252",
                                       font=ctk.CTkFont(size=11))
        self.status_dot.pack(pady=(0, 12))

        ctk.CTkFrame(self.sidebar, height=1, fg_color="#3a3a3a").pack(fill="x", padx=12, pady=(0, 8))

        self._nav_buttons = {}
        self._nav_accents = {}
        self._nav_colors  = {}

        for label, key, color, icon_file in NAV_ITEMS:
            self._nav_colors[key] = color

            try:
                img = ctk.CTkImage(Image.open(os.path.join(ICONS_DIR, icon_file)), size=(22, 22))
            except Exception:
                img = None

            row = ctk.CTkFrame(self.sidebar, fg_color=COLOR_INACTIVE, corner_radius=8, height=42)
            row.pack(fill="x", padx=10, pady=3)
            row.pack_propagate(False)

            accent = ctk.CTkFrame(row, width=4, fg_color="#444", corner_radius=2)
            accent.pack(side="left", fill="y", padx=(4, 0), pady=4)
            self._nav_accents[key] = accent

            btn = ctk.CTkButton(
                row, text=label, anchor="w",
                image=img, compound="left",
                font=ctk.CTkFont(size=13, weight="bold"),
                fg_color="transparent", hover_color="#2a2a3a",
                text_color="#cccccc",
                command=lambda k=key: self.show_view(k),
            )
            btn.pack(side="left", fill="both", expand=True, padx=4, pady=2)
            self._nav_buttons[key] = (row, btn)

        ctk.CTkFrame(self.sidebar, height=1, fg_color="#3a3a3a").pack(fill="x", padx=12, pady=10)

        # Ficheros activos
        info = ctk.CTkFrame(self.sidebar, fg_color="#1e1e2e", corner_radius=6)
        info.pack(fill="x", padx=10, pady=(0, 6))
        ctk.CTkLabel(info, text="Ficheros activos",
                     font=ctk.CTkFont(size=10), text_color="#666").pack(anchor="w", padx=8, pady=(6, 2))
        self._lbl_cfg_file = ctk.CTkLabel(info, text="", font=ctk.CTkFont(size=10),
                                           text_color="#aaa", anchor="w", wraplength=160)
        self._lbl_cfg_file.pack(anchor="w", padx=8)
        self._lbl_tar_file = ctk.CTkLabel(info, text="", font=ctk.CTkFont(size=10),
                                           text_color="#aaa", anchor="w", wraplength=160)
        self._lbl_tar_file.pack(anchor="w", padx=8, pady=(0, 6))

        # Start / Stop at bottom
        self._btn_stop = ctk.CTkButton(
            self.sidebar, text="■  Detener",
            command=self.detener_agente,
            fg_color="#8b1a1a", hover_color="#a82020",
        )
        self._btn_stop.pack(side="bottom", pady=(5, 10), padx=10, fill="x")

        self._btn_start = ctk.CTkButton(
            self.sidebar, text="▶  Iniciar",
            command=self.iniciar_agente,
            fg_color="#1a6b2a", hover_color="#228b36",
        )
        self._btn_start.pack(side="bottom", pady=5, padx=10, fill="x")

    # =========================================================================
    # Content area
    # =========================================================================

    def _build_content(self):
        self._content_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self._content_frame.pack(side="right", fill="both", expand=True)

        self._views: dict[str, Any] = {
            "dashboard": DashboardView(self._content_frame, self),
            "log":       LogViewerView(self._content_frame, self),
            "config":    YamlEditorView(self._content_frame, self, path=CONFIG_PATH, tipo="config"),
            "tareas":    YamlEditorView(self._content_frame, self, path=TAREAS_PATH, tipo="tareas"),
            "cache":     CacheManagerView(self._content_frame, self),
        }
        self._current_view: Optional[str] = None
        self.after(100, self._actualizar_labels_ficheros)

    def show_view(self, key: str):
        if self._current_view:
            self._views[self._current_view].pack_forget()
        self._views[key].pack(fill="both", expand=True, padx=0, pady=0)
        self._current_view = key
        if key == "cache":
            self._views["cache"].actualizar()
        for k, (row, btn) in self._nav_buttons.items():
            active = k == key
            row.configure(fg_color=COLOR_ACTIVE if active else COLOR_INACTIVE)
            btn.configure(text_color="white" if active else "#cccccc")
            self._nav_accents[k].configure(
                fg_color=self._nav_colors[k] if active else "#444")

    # =========================================================================
    # Agent control
    # =========================================================================

    def iniciar_agente(self):
        if self.agent_process and self.agent_process.poll() is None:
            return
        error = self._validar_config_inicio()
        if error:
            from tkinter import messagebox
            messagebox.showerror("No se puede iniciar el agente", error)
            return
        self.agent_process = subprocess.Popen(
            [sys.executable, AGENTE_PY],
            cwd=SCRIPT_DIR,
        )
        self._update_status_label()

    def _validar_config_inicio(self) -> str:
        try:
            import yaml
            with open(self._views["config"]._path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            with open(self._views["tareas"]._path, "r", encoding="utf-8") as f:
                tar = yaml.safe_load(f) or {}
        except Exception as e:
            return f"No se pudo leer la configuración:\n{e}"

        if not cfg.get("modelo", "").strip():
            return "Falta el modelo principal.\nConfigúralo en Config → Modelo principal."
        if not tar.get("tareas"):
            return "No hay tareas definidas en tareas.yaml."
        return ""

    def detener_agente(self):
        if self.agent_process and self.agent_process.poll() is None:
            self.agent_process.terminate()
        self.agent_process = None
        self._update_status_label()

    def _poll_agent_status(self):
        self._update_status_label()
        self.after(3000, self._poll_agent_status)

    def _update_status_label(self):
        running = self.agent_process and self.agent_process.poll() is None
        if running:
            self.status_dot.configure(text="● Ejecutando", text_color="#52c252")
            self._btn_start.configure(state="disabled")
            self._btn_stop.configure(state="normal")
        else:
            self.status_dot.configure(text="● Detenido",   text_color="#e05252")
            self._btn_start.configure(state="normal")
            self._btn_stop.configure(state="disabled")

    # =========================================================================
    # Menu handlers
    # =========================================================================

    def _actualizar_labels_ficheros(self):
        cfg_name = os.path.basename(self._views["config"]._path)
        tar_name = os.path.basename(self._views["tareas"]._path)
        self._lbl_cfg_file.configure(text=f"⚙ {cfg_name}")
        self._lbl_tar_file.configure(text=f"📋 {tar_name}")

    def _abrir_yaml(self, vista: str):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            initialdir=os.path.join(SCRIPT_DIR, "config"),
            filetypes=[("YAML", "*.yaml *.yml"), ("Todos", "*.*")],
        )
        if not path:
            return
        path_anterior = self._views[vista]._path
        self._views[vista].cargar_archivo(path)
        # Si el fichero cambió realmente, parar agente y limpiar log
        if self._views[vista]._path != path_anterior:
            self.detener_agente()
            try:
                open(LOG_PATH, "w").close()
            except Exception:
                pass
        self._actualizar_labels_ficheros()
        self.show_view(vista)

    def _guardar_yaml(self, vista: str):
        self.show_view(vista)
        self._views[vista].guardar()

    def _guardar_yaml_como(self, vista: str):
        self.show_view(vista)
        self._views[vista].guardar_como()

    def _limpiar_cache(self):
        self._views["cache"].eliminar_todo()

    def _acerca_de(self):
        win = ctk.CTkToplevel(self)
        win.title("Acerca de")
        win.geometry("340x160")
        win.resizable(False, False)
        win.grab_set()
        ctk.CTkLabel(win, text="FreeAgent_IA",
                     font=ctk.CTkFont(size=20, weight="bold")).pack(pady=(24, 4))
        ctk.CTkLabel(win, text="Agente de automatizacion con IA\nOllama + Gemini + Telegram",
                     justify="center").pack()
        ctk.CTkButton(win, text="Cerrar", command=win.destroy, width=100).pack(pady=18)

    def _on_close(self):
        self.detener_agente()
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()
