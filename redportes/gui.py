"""Interfaz gráfica mínima de Redportes (tkinter, viene con Python)."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import traceback
import webbrowser
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

from redportes import __version__, escaneo, informe, visitas
from redportes.escaneo import todos_los_hallazgos
from redportes.puertos import lista_de_puertos
from redportes.red import listar_interfaces
from redportes.sistema import ES_MAC, ES_WINDOWS

OPCIONES_PUERTOS = {
    "Rápido (21 puertos comunes)": "rapido",
    "Completo (36 puertos)": "completo",
    "Ninguno (solo descubrir equipos)": "ninguno",
}
COLOR_NIVEL = {"alto": "#fde2e2", "medio": "#ffedd5", "bajo": "#fef9c3"}
RECURSOS = Path(__file__).parent / "recursos"


def carpeta_informes() -> Path:
    from redportes.sistema import carpeta_programa, es_portable

    if es_portable():
        d = carpeta_programa() / "Informes"
        d.mkdir(parents=True, exist_ok=True)
        return d
    docs = Path.home() / "Documents"
    if not ES_WINDOWS and not ES_MAC:
        from redportes.sistema import ejecutar, tiene

        xdg = ejecutar(["xdg-user-dir", "DOCUMENTS"]).strip() if tiene("xdg-user-dir") else ""
        if xdg and Path(xdg).exists() and Path(xdg) != Path.home():
            docs = Path(xdg)  # «Documentos» en un escritorio en castellano
    if not docs.exists():
        docs = Path.home() / "Documentos" if (Path.home() / "Documentos").exists() else Path.home()
    d = docs / "Redportes"
    d.mkdir(parents=True, exist_ok=True)
    return d


def abrir(ruta: Path) -> None:
    if ES_WINDOWS:
        os.startfile(str(ruta))  # noqa: S606
    elif ES_MAC:
        subprocess.Popen(["open", str(ruta)])
    elif ruta.is_dir():
        subprocess.Popen(["xdg-open", str(ruta)])
    else:
        webbrowser.open(ruta.resolve().as_uri())


class App:
    def __init__(self, raiz: tk.Tk):
        self.raiz = raiz
        self.cola: queue.Queue = queue.Queue()
        self.resultado: dict | None = None
        self.ruta_informe: Path | None = None
        self.hallazgos_vista: dict[str, object] = {}
        self.interfaces = []

        from redportes.sistema import es_portable

        raiz.title(f"Redportes {__version__}" + (" (portable)" if es_portable() else ""))
        raiz.geometry("1060x700")
        raiz.minsize(860, 560)
        try:
            if ES_WINDOWS and (RECURSOS / "icono.ico").exists():
                raiz.iconbitmap(default=str(RECURSOS / "icono.ico"))
            else:
                self._icono = tk.PhotoImage(file=str(RECURSOS / "icono.png"))
                raiz.iconphoto(True, self._icono)
        except tk.TclError:
            pass

        estilo = ttk.Style()
        if "vista" not in estilo.theme_names():
            estilo.theme_use("clam")
        estilo.configure("Treeview", rowheight=24)
        estilo.configure("Accion.TButton", font=("TkDefaultFont", 10, "bold"), padding=(16, 6))

        self.banner = tk.Frame(raiz, background="#fef3c7")
        self.l_banner = tk.Label(self.banner, background="#fef3c7", foreground="#713f12",
                                 font=("TkDefaultFont", 10, "bold"))
        self.l_banner.pack(side="left", padx=12, pady=6)
        tk.Button(self.banner, text="✕", relief="flat", background="#fef3c7", cursor="hand2",
                  command=self.banner.pack_forget).pack(side="right", padx=6)
        self.b_notas = ttk.Button(self.banner, text="Qué hay de nuevo")
        self.b_notas.pack(side="right", padx=4, pady=4)
        self.b_bajar = ttk.Button(self.banner, text="Descargar")
        self.b_bajar.pack(side="right", padx=4, pady=4)

        self._armar_menu()
        self._armar_formulario()
        self._armar_pie()        # se empaqueta antes que las pestañas para que siempre quede visible
        self._armar_pestanas()
        self._cargar_interfaces()
        self._cargar_visitas()
        self._actualizar_cb_avisar()
        raiz.after(100, self._leer_cola)
        raiz.after(800, self._inicio)

    # ------------------------------------------------------------ armado

    def _armar_menu(self):
        from redportes import config

        barra = tk.Menu(self.raiz)
        herr = tk.Menu(barra, tearoff=0)
        herr.add_command(label="Automatizar (Telegram y escaneo diario)…", command=self.abrir_automatizar)
        herr.add_command(label="Exportar inventario (Excel)…", command=self.exportar_inventario)
        self.v_usar_nmap = tk.BooleanVar(value=config.leer().get("usar_nmap", True))
        herr.add_checkbutton(label="Usar nmap (si está instalado)", variable=self.v_usar_nmap,
                             command=self._guardar_usar_nmap)
        herr.add_command(label="Actualizar la lista de fabricantes", command=self.actualizar_oui)
        herr.add_command(label="Página de mi proveedor que muestra la IP interna…", command=self.configurar_proveedor)
        herr.add_separator()
        herr.add_command(label="Abrir la carpeta de informes", command=lambda: abrir(carpeta_informes()))
        if not ES_WINDOWS and not ES_MAC:
            herr.add_command(label="Agregar Redportes al menú de aplicaciones", command=self.agregar_al_menu)
        barra.add_cascade(label="Herramientas", menu=herr)

        ayuda = tk.Menu(barra, tearoff=0)
        ayuda.add_command(label="Buscar actualizaciones", command=self.buscar_actualizaciones)
        self.v_aviso_auto = tk.BooleanVar(value=bool(config.leer().get("actualizaciones", {}).get("activado")))
        ayuda.add_checkbutton(label="Avisar de versiones nuevas al abrir", variable=self.v_aviso_auto,
                              command=self._cambiar_aviso_auto)
        ayuda.add_separator()
        ayuda.add_command(label="Sitio de Redportes", command=lambda: webbrowser.open("https://redportes.blucaro.site"))
        ayuda.add_command(label="Reportar un error o proponer una idea",
                          command=lambda: webbrowser.open("https://github.com/Fracunzera/Redportes/issues/new/choose"))
        ayuda.add_command(label="Qué hay de nuevo",
                          command=lambda: webbrowser.open("https://github.com/Fracunzera/Redportes/blob/main/CHANGELOG.md"))
        ayuda.add_separator()
        ayuda.add_command(label="Acerca de Redportes", command=self._acerca_de)
        barra.add_cascade(label="Ayuda", menu=ayuda)
        self.raiz.configure(menu=barra)

    def agregar_al_menu(self):
        from redportes import escritorio

        try:
            ruta = escritorio.instalar_acceso()
        except (OSError, RuntimeError) as e:
            messagebox.showerror("Redportes", f"No se pudo crear el acceso: {e}")
            return
        messagebox.showinfo("Redportes", "Listo: Redportes aparece en el menú de aplicaciones "
                            f"(puede tardar unos segundos).\n\n{ruta}")

    def configurar_proveedor(self):
        from tkinter import simpledialog

        from redportes import config, internet

        cfg = config.leer()
        conocidos = "\n".join(f"• {p['nombre']}: {p['base']}" for p in internet.PROVEEDORES)
        url = simpledialog.askstring(
            "Proveedor de Internet",
            "Algunos proveedores tienen una página (por ejemplo su speedtest) que muestra la IP interna "
            "del cliente cuando hay CGNAT. Si el tuyo tiene una, pegá la dirección. Dejalo vacío para no usar ninguna.\n\n"
            f"Ya incluidos:\n{conocidos}",
            initialvalue=cfg.get("url_proveedor", ""), parent=self.raiz)
        if url is None:
            return
        cfg["url_proveedor"] = url.strip()
        config.guardar(cfg)
        self.v_estado.set("Página del proveedor guardada: se usa al escanear con «salida a Internet».")

    def _guardar_usar_nmap(self):
        from redportes import config

        cfg = config.leer()
        cfg["usar_nmap"] = self.v_usar_nmap.get()
        config.guardar(cfg)
        self.v_estado.set("nmap " + ("activado." if self.v_usar_nmap.get() else "desactivado: se usa la búsqueda propia."))

    def _cambiar_aviso_auto(self):
        from redportes import config

        cfg = config.leer()
        cfg.setdefault("actualizaciones", {})["activado"] = self.v_aviso_auto.get()
        config.guardar(cfg)
        self.v_estado.set("Aviso de versiones nuevas " + ("activado." if self.v_aviso_auto.get() else "desactivado."))

    def buscar_actualizaciones(self):
        self.v_estado.set("Buscando actualizaciones…")

        def trabajo():
            from redportes import actualizaciones

            self.cola.put(("buscada", actualizaciones.consultar()))

        threading.Thread(target=trabajo, daemon=True).start()

    def _resultado_busqueda(self, info: dict | None):
        from redportes import actualizaciones, config

        if info is None:
            self.v_estado.set("No se pudo consultar GitHub.")
            if messagebox.askyesno("Buscar actualizaciones", "No se pudo consultar si hay una versión nueva "
                                   "(¿hay Internet?).\n\n¿Querés abrir la página de descargas?"):
                webbrowser.open(actualizaciones.PAGINA)
            return
        cfg = config.leer()
        cfg.setdefault("actualizaciones", {}).update(ultima_version=info["version"])
        config.guardar(cfg)
        if not actualizaciones.es_mas_nueva(info["version"]):
            self.v_estado.set(f"Tenés la última versión ({__version__}).")
            messagebox.showinfo("Buscar actualizaciones", f"Tenés la última versión de Redportes ({__version__}).")
            return
        self._mostrar_nueva(info)
        self.actualizar_ahora(info)

    # ------------------------------------------------------------ actualizar desde la app

    def actualizar_ahora(self, info: dict):
        from redportes import actualizador

        forma = actualizador.forma_de_uso()
        if forma == "pip":
            self.raiz.clipboard_clear()
            self.raiz.clipboard_append(actualizador.COMANDO_PIP)
            messagebox.showinfo("Actualizar", "Redportes está instalado con pip. Para actualizarlo, corré en "
                                f"una terminal (ya está copiado):\n\n{actualizador.COMANDO_PIP}")
            return
        if not messagebox.askyesno("Actualizar Redportes",
                                   f"¿Descargar e instalar la versión {info['version']} ahora?\n\n"
                                   "Redportes se va a cerrar y abrir de nuevo. Tus datos, historial e informes "
                                   "no se tocan."):
            return
        v = tk.Toplevel(self.raiz)
        v.title("Actualizando Redportes")
        v.geometry("420x150")
        v.transient(self.raiz)
        v.resizable(False, False)
        ttk.Label(v, text=f"Descargando Redportes {info['version']}…").pack(anchor="w", padx=16, pady=(16, 6))
        barra = ttk.Progressbar(v, mode="determinate", maximum=100)
        barra.pack(fill="x", padx=16)
        l_det = ttk.Label(v, text="", foreground="#64748b")
        l_det.pack(anchor="w", padx=16, pady=(4, 0))
        cancelar = {"si": False}
        ttk.Button(v, text="Cancelar", command=lambda: cancelar.update(si=True)).pack(anchor="e", padx=16, pady=8)
        self._act = {"ventana": v, "barra": barra, "detalle": l_det}

        def trabajo():
            from redportes import actualizaciones

            try:
                datos = info if info.get("archivos") else actualizaciones.consultar()
                if not datos:
                    raise RuntimeError("No se pudo consultar GitHub. Revisá la conexión.")
                ultimo = [0]

                def progreso(hecho, total):
                    pct = int(hecho * 100 / total) if total else 0
                    if pct != ultimo[0]:
                        ultimo[0] = pct
                        self.cola.put(("act_progreso", (hecho, total)))

                prep = actualizador.preparar(datos, progreso, lambda: cancelar["si"])
                self.cola.put(("act_listo", prep))
            except actualizador.Cancelado:
                self.cola.put(("act_error", None))
            except Exception as e:  # noqa: BLE001
                self.cola.put(("act_error", str(e)))

        threading.Thread(target=trabajo, daemon=True).start()

    def _act_progreso(self, hecho: int, total: int):
        if total:
            self._act["barra"]["value"] = hecho * 100 / total
        self._act["detalle"].configure(text=f"{hecho / 2**20:.1f} de {total / 2**20:.1f} MB" if total
                                       else f"{hecho / 2**20:.1f} MB")

    def _act_fin(self, prep: dict | None, error: str | None):
        from redportes import actualizador

        self._act["ventana"].destroy()
        if prep is None:
            if error:
                messagebox.showerror("Actualizar Redportes", error)
            else:
                self.v_estado.set("Actualización cancelada.")
            return
        messagebox.showinfo("Actualizar Redportes", actualizador.mensaje(prep))
        try:
            actualizador.aplicar(prep)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Actualizar Redportes", f"No se pudo instalar: {e}")
            return
        self.raiz.destroy()

    def _acerca_de(self):
        from redportes.sistema import carpeta_datos, es_portable

        messagebox.showinfo(
            "Acerca de Redportes",
            f"Redportes {__version__}" + (" (portable)" if es_portable() else "") + "\n"
            "Escáner de red gratis y de código abierto (licencia MIT).\n\n"
            "https://redportes.blucaro.site\nhttps://github.com/Fracunzera/Redportes\n\n"
            f"Datos e historial: {carpeta_datos()}\nInformes: {carpeta_informes()}")

    def _armar_formulario(self):
        f = self.f_form = ttk.Frame(self.raiz, padding=(12, 12, 12, 6))
        f.pack(fill="x")
        for c in (1, 3):
            f.columnconfigure(c, weight=1)

        ttk.Label(f, text="Cliente / sitio:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.v_cliente = tk.StringVar()
        ttk.Entry(f, textvariable=self.v_cliente).grid(row=0, column=1, sticky="ew", padx=(0, 18))

        ttk.Label(f, text="Interfaz:").grid(row=0, column=2, sticky="w", padx=(0, 6))
        self.v_interfaz = tk.StringVar()
        self.cb_interfaz = ttk.Combobox(f, textvariable=self.v_interfaz, state="readonly")
        self.cb_interfaz.grid(row=0, column=3, sticky="ew")
        self.cb_interfaz.bind("<<ComboboxSelected>>", self._cambio_interfaz)

        ttk.Label(f, text="Red:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.v_red = tk.StringVar()
        ttk.Entry(f, textvariable=self.v_red).grid(row=1, column=1, sticky="ew", padx=(0, 18), pady=(8, 0))

        ttk.Label(f, text="Puertos:").grid(row=1, column=2, sticky="w", pady=(8, 0))
        self.v_puertos = tk.StringVar(value=next(iter(OPCIONES_PUERTOS)))
        cb = ttk.Combobox(f, textvariable=self.v_puertos, values=list(OPCIONES_PUERTOS))
        cb.grid(row=1, column=3, sticky="ew", pady=(8, 0))

        opciones = ttk.Frame(f)
        opciones.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        # Los botones se empaquetan primero para que nunca se queden sin lugar.
        acciones = ttk.Frame(opciones)
        acciones.pack(side="right")
        self.v_internet = tk.BooleanVar(value=False)
        self.v_guardar = tk.BooleanVar(value=True)
        ttk.Checkbutton(opciones, text="Analizar salida a Internet",
                        variable=self.v_internet).pack(side="left")
        ttk.Checkbutton(opciones, text="Guardar en el historial",
                        variable=self.v_guardar).pack(side="left", padx=14)
        self.v_avisar = tk.BooleanVar(value=False)
        self.cb_avisar = ttk.Checkbutton(opciones, text="Avisar por Telegram",
                                         variable=self.v_avisar)
        self.cb_avisar.pack(side="left")
        self.b_escanear = ttk.Button(acciones, text="Escanear", style="Accion.TButton",
                                     command=self.escanear)
        self.b_escanear.pack(side="right")
        self.b_reiniciar = ttk.Button(acciones, text="Reiniciar", command=self.reiniciar)
        self.b_detener = ttk.Button(acciones, text="Detener", style="Accion.TButton", command=self.detener)
        self.control = None
        self._reiniciar_pendiente = False

        estado = ttk.Frame(self.raiz, padding=(12, 0, 12, 6))
        estado.pack(fill="x")
        self.barra = ttk.Progressbar(estado, mode="indeterminate", length=180)
        self.barra.pack(side="left")
        self.v_estado = tk.StringVar(value="Listo para escanear.")
        ttk.Label(estado, textvariable=self.v_estado).pack(side="left", padx=10)
        self.l_salud = tk.Label(estado, text="", font=("TkDefaultFont", 11, "bold"))
        self.l_salud.pack(side="right")

    def _tabla(self, padre, columnas: dict[str, int]) -> ttk.Treeview:
        marco = ttk.Frame(padre)
        marco.pack(fill="both", expand=True)
        t = ttk.Treeview(marco, columns=list(columnas), show="headings", selectmode="browse")
        for col, ancho in columnas.items():
            t.heading(col, text=col)
            t.column(col, width=ancho, stretch=col in ("Fabricante", "Puertos", "Tema", "Detalle", "Resultado"))
        sb = ttk.Scrollbar(marco, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        t.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for nivel, color in COLOR_NIVEL.items():
            t.tag_configure(nivel, background=color)
        return t

    def _armar_pestanas(self):
        self.nb = ttk.Notebook(self.raiz)
        self.nb.pack(fill="both", expand=True, padx=12)

        p1 = ttk.Frame(self.nb, padding=6)
        self.t_equipos = self._tabla(p1, {"IP": 120, "Tipo": 190, "Fabricante": 200, "Nombre": 150,
                                          "Sistema": 170, "Puertos": 200})
        self.nb.add(p1, text="Equipos")

        p2 = ttk.Frame(self.nb, padding=6)
        arriba = ttk.Frame(p2)
        arriba.pack(fill="both", expand=True)
        self.t_hall = self._tabla(arriba, {"Nivel": 70, "Tema": 260, "IP": 120, "Equipo": 180,
                                           "Detalle": 260})
        self.t_hall.bind("<<TreeviewSelect>>", self._mostrar_hallazgo)
        self.txt_hall = tk.Text(p2, height=9, wrap="word", relief="flat", padx=8, pady=6,
                                background="#f8fafc", font="TkDefaultFont")
        self.txt_hall.pack(fill="x", pady=(6, 0))
        self.txt_hall.tag_configure("cmd", font=("Consolas" if ES_WINDOWS else "Courier", 10),
                                    background="#e2e8f0")
        self.txt_hall.tag_configure("b", font=(tkfont.nametofont("TkDefaultFont").actual("family"), 10, "bold"))
        self.txt_hall.insert("end", "Elegí un hallazgo para ver qué es y qué hacer.")
        self.txt_hall.configure(state="disabled")
        self.nb.add(p2, text="Para revisar")

        p3 = ttk.Frame(self.nb, padding=6)
        barra3 = ttk.Frame(p3)
        barra3.pack(fill="x", pady=(0, 6))
        self.b_solo_inet = ttk.Button(barra3, text="Probar solo Internet", style="Accion.TButton",
                                      command=self.probar_solo_internet)
        self.b_solo_inet.pack(side="left")
        self.b_det_inet = ttk.Button(barra3, text="Detener", command=self.detener, state="disabled")
        self.b_det_inet.pack(side="left", padx=6)
        ttk.Button(barra3, text="Copiar", command=self._copiar_internet).pack(side="left")
        ttk.Label(barra3, text="IP WAN del router, CGNAT, traceroute, IP pública y conexión, sin escanear la red local.",
                  foreground="#64748b").pack(side="left", padx=8)
        self.txt_internet = tk.Text(p3, wrap="word", relief="flat", padx=8, pady=6)
        self.txt_internet.pack(fill="both", expand=True)
        self.nb.add(p3, text="Internet")

        p6 = ttk.Frame(self.nb, padding=8)
        fila1 = ttk.Frame(p6)
        fila1.pack(fill="x")
        self.b_diag = ttk.Button(fila1, text="Probar mi conexión", style="Accion.TButton",
                                 command=self.diagnosticar)
        self.b_diag.pack(side="left")
        ttk.Label(fila1, text="¿Anda bien Internet acá? Prueba el router, Internet, el DNS y la navegación.",
                  foreground="#64748b").pack(side="left", padx=10)

        caja = ttk.LabelFrame(p6, text=" ¿No abre una página? ", padding=8)
        caja.pack(fill="x", pady=(10, 0))
        ttk.Label(caja, text="Pegá la dirección:").pack(side="left")
        self.v_pagina = tk.StringVar()
        e_pag = ttk.Entry(caja, textvariable=self.v_pagina)
        e_pag.pack(side="left", fill="x", expand=True, padx=6)
        e_pag.bind("<Return>", lambda _e: self.averiguar_pagina())
        self.b_pagina = ttk.Button(caja, text="Averiguar por qué", style="Accion.TButton",
                                   command=self.averiguar_pagina)
        self.b_pagina.pack(side="left")

        self.l_veredicto = tk.Label(p6, text="Elegí una de las dos pruebas.", anchor="w", justify="left",
                                    font=("TkDefaultFont", 12, "bold"), background="#e2e8f0", foreground="#0f172a",
                                    padx=12, pady=10, wraplength=900)
        self.l_veredicto.pack(fill="x", pady=(12, 0))
        self.txt_hacer = tk.Text(p6, height=4, wrap="word", relief="flat", padx=12, pady=6,
                                 background="#f8fafc", font="TkDefaultFont")
        self.txt_hacer.pack(fill="x")
        self.t_diag = self._tabla(p6, {"Prueba": 260, "Resultado": 600})
        for est, color in (("ok", "#dcfce7"), ("aviso", "#fef9c3"), ("falla", "#fde2e2"),
                           ("omitido", "#ffffff"), ("info", "#f1f5f9")):
            self.t_diag.tag_configure(est, background=color)
        self.t_diag.tag_configure("omitido", foreground="#94a3b8")
        self.t_diag.configure(height=7)
        self.b_copiar_diag = ttk.Button(caja, text="Copiar resultado", command=self.copiar_resultado,
                                        state="disabled")
        self.b_copiar_diag.pack(side="left", padx=(6, 0))
        self.texto_resultado = ""
        self.diag: dict | None = None
        self.nb.add(p6, text="Diagnóstico")

        p7 = ttk.Frame(self.nb, padding=6)
        barra7 = ttk.Frame(p7)
        barra7.pack(fill="x", pady=(0, 6))
        self.b_local = ttk.Button(barra7, text="Ver configuración", style="Accion.TButton",
                                  command=self.ver_equipo_local)
        self.b_local.pack(side="left")
        self.b_copiar_local = ttk.Button(barra7, text="Copiar resultado", command=self.copiar_equipo_local,
                                         state="disabled")
        self.b_copiar_local.pack(side="left", padx=6)
        ttk.Label(barra7, text="Red, Wi-Fi y sistema de esta computadora. Solo lectura.",
                  foreground="#64748b").pack(side="left", padx=8)
        self.t_local = self._tabla(p7, {"Dato": 260, "Valor": 580})
        self.t_local.column("Valor", stretch=True)
        self.t_local.tag_configure("seccion", background="#e2e8f0", font=("TkDefaultFont", 10, "bold"))
        self.txt_local = tk.Text(p7, height=6, wrap="word", relief="flat", padx=8, pady=6,
                                 background="#f8fafc", font="TkDefaultFont")
        self.txt_local.pack(fill="x", pady=(6, 0))
        for est, color in (("falla", "#b91c1c"), ("aviso", "#a16207"), ("info", "#334155"), ("ok", "#15803d")):
            self.txt_local.tag_configure(est, foreground=color)
        self.local: dict | None = None
        self.nb.add(p7, text="Este equipo")
        self.p_local = p7
        self.nb.bind("<<NotebookTabChanged>>", self._cambio_pestana)

        p4 = ttk.Frame(self.nb, padding=6)
        self.t_visitas = self._tabla(p4, {"N.º": 50, "Fecha": 160, "Cliente": 260, "Red": 160,
                                          "Equipos": 80})
        self.t_visitas.bind("<Double-1>", lambda _e: self.abrir_visita())
        bv = ttk.Frame(p4)
        bv.pack(fill="x", pady=(6, 0))
        ttk.Button(bv, text="Abrir informe de la visita", command=self.abrir_visita).pack(side="left")
        ttk.Button(bv, text="Informe mensual", command=self.informe_mensual).pack(side="left", padx=6)
        ttk.Button(bv, text="Actualizar", command=self._cargar_visitas).pack(side="left")
        self.nb.add(p4, text="Visitas")

        p5 = ttk.Frame(self.nb, padding=6)
        self.txt_log = tk.Text(p5, wrap="word", relief="flat", padx=8, pady=6, height=10)
        self.txt_log.pack(fill="both", expand=True)
        self.nb.add(p5, text="Registro")

    def _armar_pie(self):
        pie = ttk.Frame(self.raiz, padding=12)
        pie.pack(fill="x", side="bottom")
        self.b_informe = ttk.Button(pie, text="Abrir informe", command=self.abrir_informe,
                                    state="disabled")
        self.b_informe.pack(side="left")
        self.b_guardar = ttk.Button(pie, text="Guardar como…", command=self.guardar_como,
                                    state="disabled")
        self.b_guardar.pack(side="left", padx=6)
        self.b_compartir = ttk.Button(pie, text="Informe para compartir", command=self.informe_compartir,
                                      state="disabled")
        self.b_compartir.pack(side="left")
        ttk.Button(pie, text="Carpeta de informes",
                   command=lambda: abrir(carpeta_informes())).pack(side="left")
        ttk.Button(pie, text="Inventario (Excel)", command=self.exportar_inventario).pack(side="left", padx=6)
        ttk.Button(pie, text="Automatizar…", command=self.abrir_automatizar).pack(side="left")



    # ------------------------------------------------------------ datos

    def _cargar_interfaces(self):
        try:
            self.interfaces = listar_interfaces()
        except Exception as e:  # noqa: BLE001
            self.interfaces = []
            self._log(f"No se pudieron leer las interfaces: {e}")
        nombres = [f"{i.nombre} — {i.ip} ({i.red})" for i in self.interfaces]
        self.cb_interfaz["values"] = nombres
        if nombres:
            self.cb_interfaz.current(0)
            self._cambio_interfaz()
        else:
            self.v_estado.set("No hay ninguna interfaz de red activa.")

    def _cambio_interfaz(self, _evento=None):
        i = self.cb_interfaz.current()
        if 0 <= i < len(self.interfaces):
            self.v_red.set(self.interfaces[i].red)

    def _cargar_visitas(self):
        self.t_visitas.delete(*self.t_visitas.get_children())
        try:
            filas = visitas.listar()
        except Exception as e:  # noqa: BLE001
            self._log(f"No se pudo leer el historial: {e}")
            return
        for i, cliente, fecha, red, n in reversed(filas):
            self.t_visitas.insert("", "end", iid=str(i),
                                  values=(i, fecha.replace("T", " "), cliente or "—", red, n))

    def _log(self, msg: str):
        self.txt_log.insert("end", msg + "\n")
        self.txt_log.see("end")

    # ------------------------------------------------------------ escaneo

    def escanear(self):
        i = self.cb_interfaz.current()
        nombre_itf = self.interfaces[i].nombre if 0 <= i < len(self.interfaces) else None
        texto_puertos = self.v_puertos.get().strip()
        try:
            puertos = lista_de_puertos(OPCIONES_PUERTOS.get(texto_puertos, texto_puertos))
            itf, red = escaneo.resolver_red(nombre_itf, self.v_red.get())
        except ValueError as e:
            messagebox.showerror("Redportes", str(e))
            return
        forzar = False
        import ipaddress

        tam = ipaddress.IPv4Network(red).num_addresses
        if tam > escaneo.MAX_HOSTS:
            if not messagebox.askyesno("Red grande", f"La red {red} tiene {tam} direcciones y puede "
                                       "tardar bastante. ¿Escanear igual?"):
                return
            forzar = True

        from redportes.control import Control

        self.control = Control(progreso=lambda m: self.cola.put(("progreso", m)))
        self._botones_escaneando(True)
        self.barra.start(12)
        self.txt_log.delete("1.0", "end")
        self.v_estado.set(f"Escaneando {red}…")
        args = dict(cliente=self.v_cliente.get().strip(), con_internet=self.v_internet.get(),
                    forzar=forzar, guardar=self.v_guardar.get(), usar_nmap=self.v_usar_nmap.get(),
                    avisar=self.v_avisar.get() and self._telegram_ok())
        threading.Thread(target=self._trabajo, args=(itf, red, puertos, args), daemon=True).start()

    def _botones_escaneando(self, si: bool):
        if si:
            self.b_escanear.pack_forget()
            self.b_detener.configure(state="normal")
            self.b_detener.pack(side="right")
            self.b_reiniciar.pack(side="right", padx=(0, 6))
        else:
            self.b_detener.pack_forget()
            self.b_reiniciar.pack_forget()
            self.b_escanear.configure(state="normal")
            self.b_escanear.pack(side="right")

    def probar_solo_internet(self):
        from redportes.control import Cancelado, Control

        self.control = Control(progreso=lambda m: self.cola.put(("progreso", m)))
        self.b_solo_inet.configure(state="disabled")
        self.b_det_inet.configure(state="normal")
        self.barra.start(12)
        self.txt_internet.delete("1.0", "end")
        self.txt_internet.insert("end", "Analizando la salida a Internet… (puede tardar hasta un par de minutos)\n")

        def trabajo():
            try:
                self.cola.put(("internet", escaneo.solo_internet(control=self.control)))
            except Cancelado:
                self.cola.put(("internet", {"cancelado": True}))
            except Exception as e:  # noqa: BLE001
                self.cola.put(("internet", {"error": str(e)}))

        threading.Thread(target=trabajo, daemon=True).start()

    def _mostrar_solo_internet(self, r: dict):
        self.barra.stop()
        self.barra["value"] = 0
        self.b_solo_inet.configure(state="normal")
        self.b_det_inet.configure(state="disabled")
        self.txt_internet.delete("1.0", "end")
        if r.get("cancelado"):
            self.txt_internet.insert("end", "Detenido.")
            self.v_estado.set("Prueba de Internet detenida.")
            return
        if r.get("error"):
            self.txt_internet.insert("end", f"No se pudo terminar: {r['error']}")
            return
        self.txt_internet.insert("end", escaneo.texto_internet(r))
        self.v_estado.set("Prueba de Internet lista.")

    def _copiar_internet(self):
        texto = self.txt_internet.get("1.0", "end").strip()
        if texto:
            self.raiz.clipboard_clear()
            self.raiz.clipboard_append(texto)
            self.v_estado.set("Resultado copiado.")

    def detener(self):
        if self.control:
            self.control.detener()
            self.b_detener.configure(state="disabled")
            self.v_estado.set("Deteniendo…")

    def reiniciar(self):
        self._reiniciar_pendiente = True
        self.detener()

    def _trabajo(self, itf, red, puertos, args):
        from redportes.control import Cancelado

        try:
            r = escaneo.ejecutar(itf, red, puertos, cliente=args["cliente"],
                                 con_internet=args["con_internet"], forzar=args["forzar"],
                                 usar_nmap=args["usar_nmap"], control=self.control)
            cambios, previo = None, None
            if args["guardar"]:
                previo = visitas.anterior(r["cliente"], r["red"])
                visitas.guardar(r)
                if previo:
                    cambios = visitas.comparar(previo, r)
            if args["avisar"]:
                from redportes import telegram

                texto = telegram.armar_aviso(r, cambios, previo)
                if texto:
                    try:
                        telegram.enviar(texto)
                        self.cola.put(("progreso", "Aviso enviado por Telegram."))
                    except telegram.ErrorTelegram as e:
                        self.cola.put(("progreso", f"No se pudo avisar por Telegram: {e}"))
                else:
                    self.cola.put(("progreso", "Sin novedades: no se manda aviso por Telegram."))
            ruta = carpeta_informes() / informe.nombre_archivo(r["cliente"], r["red"])
            ruta.write_text(informe.generar(r, cambios), encoding="utf-8")
            self.cola.put(("fin", (r, cambios, ruta)))
        except Cancelado:
            self.cola.put(("cancelado", None))
        except Exception as e:  # noqa: BLE001
            self.cola.put(("error", f"{e}\n\n{traceback.format_exc()}"))

    def _leer_cola(self):
        try:
            while True:
                tipo, dato = self.cola.get_nowait()
                if tipo == "progreso":
                    self.v_estado.set(dato)
                    self._log(dato)
                elif tipo == "act_progreso":
                    self._act_progreso(*dato)
                elif tipo == "act_listo":
                    self._act_fin(dato, None)
                elif tipo == "act_error":
                    self._act_fin(None, dato)
                elif tipo == "buscada":
                    self._resultado_busqueda(dato)
                elif tipo == "nueva":
                    self._mostrar_nueva(dato)
                elif tipo == "local":
                    self._mostrar_equipo_local(dato)
                elif tipo == "pagina":
                    self._mostrar_pagina(dato)
                elif tipo == "diag":
                    self._mostrar_diagnostico(dato)
                elif tipo == "oui":
                    self.v_estado.set(dato)
                    self._log(dato)
                elif tipo == "fin":
                    self._terminar(*dato)
                elif tipo == "cancelado":
                    self.barra.stop()
                    self.barra["value"] = 0
                    self._botones_escaneando(False)
                    self.v_estado.set("Escaneo detenido.")
                    self._log("Escaneo detenido por el usuario.")
                    if self._reiniciar_pendiente:
                        self._reiniciar_pendiente = False
                        self.raiz.after(300, self.escanear)
                elif tipo == "internet":
                    self._mostrar_solo_internet(dato)
                elif tipo == "error":
                    self.barra.stop()
                    self._botones_escaneando(False)
                    self.v_estado.set("Error en el escaneo.")
                    self._log(dato)
                    messagebox.showerror("Redportes", dato.split("\n\n")[0])
        except queue.Empty:
            pass
        self.raiz.after(100, self._leer_cola)

    def _terminar(self, r: dict, cambios: dict | None, ruta: Path):
        self.barra.stop()
        self.barra["value"] = 0
        self._botones_escaneando(False)
        for a in r.get("avisos") or []:
            self._log(f"⚠ {a['texto']} {a.get('recomendacion', '')}")
        self.resultado, self.ruta_informe = r, ruta
        self.b_informe.configure(state="normal")
        self.b_guardar.configure(state="normal")
        self.b_compartir.configure(state="normal")
        self.cambios = cambios

        peor = {}
        hall = todos_los_hallazgos(r)
        for h in reversed(hall):  # el primero (más grave) queda
            peor[h.ip] = h.nivel

        self.t_equipos.delete(*self.t_equipos.get_children())
        for e in r["equipos"]:
            marca = " ★" if e["es_este_equipo"] else (" (GW)" if e["es_puerta"] else "")
            puertos = ", ".join(str(p["numero"]) for p in e["puertos"])
            self.t_equipos.insert("", "end", values=(
                e["ip"] + marca, e["tipo"], e["fabricante"], e["nombre"], e["sistema"], puertos),
                tags=(peor.get(e["ip"], ""),))

        nombres = {e["ip"]: e.get("nombre") or e.get("fabricante") or e.get("tipo") for e in r["equipos"]}
        self.t_hall.delete(*self.t_hall.get_children())
        self.hallazgos_vista.clear()
        for n, h in enumerate(hall):
            iid = str(n)
            self.hallazgos_vista[iid] = h
            self.t_hall.insert("", "end", iid=iid, tags=(h.nivel,), values=(
                h.nivel.upper(), h.titulo, h.ip, nombres.get(h.ip, ""), h.detalle))

        self.txt_internet.delete("1.0", "end")
        w = r.get("wan") or {}
        if w.get("ip"):
            self.txt_internet.insert("end", f"IP WAN del router: {w['ip']} (vía {w['metodo']})\n")
        if w.get("texto"):
            self.txt_internet.insert("end", w["texto"] + "\n\n")
        inet = r.get("internet")
        if inet:
            if inet.get("ip_publica"):
                self.txt_internet.insert("end", f"IP pública: {inet['ip_publica']}\n\n")
            for c in inet["conclusiones"]:
                self.txt_internet.insert("end", f"• {c}\n\n")
            if inet.get("exposicion"):
                self.txt_internet.insert("end", f"Qué se ve desde Internet (Shodan): {inet['exposicion']}\n\n")
            self.txt_internet.insert("end", "Saltos:\n")
            for s in inet["saltos"]:
                ms = f"{s['ms']:.0f} ms" if s.get("ms") is not None else ""
                self.txt_internet.insert("end", f"  {s['n']:>2}  {s['ip'] or '*':16} {s['tipo']:14} {ms}\n")
        else:
            self.txt_internet.insert("end", "No se analizó. Marcá «Analizar salida a Internet» "
                                            "antes de escanear.\n")
        if r.get("dns"):
            self.txt_internet.insert("end", "\nDNS: " + ", ".join(
                f"{d['ip']} ({d['quien']})" for d in r["dns"]) + "\n")

        sd = r.get("salud") or {}
        if sd:
            self.l_salud.configure(text=f"Salud: {sd['puntaje']}/100 · {sd['estado']}", fg=sd["color"])
        resumen = f"{len(r['equipos'])} equipos, {len(hall)} cosas para revisar."
        if cambios:
            resumen += (f" Desde la visita anterior: {len(cambios['nuevos'])} nuevos, "
                        f"{len(cambios['faltan'])} ya no están.")
        self.v_estado.set(resumen)
        self._log(resumen)
        self._log(f"Informe: {ruta}")
        self._cargar_visitas()
        if hall:
            self.nb.select(1)
        else:
            self.nb.select(0)

    # ------------------------------------------------------------ acciones

    def _mostrar_hallazgo(self, _evento=None):
        sel = self.t_hall.selection()
        if not sel:
            return
        h = self.hallazgos_vista[sel[0]]
        t = self.txt_hall
        t.configure(state="normal")
        t.delete("1.0", "end")
        t.insert("end", f"{h.titulo} — {h.ip}\n", "b")
        t.insert("end", h.que_es + "\n")
        t.insert("end", "Qué hacer: ", "b")
        t.insert("end", h.que_hacer)
        if h.comando:
            t.insert("end", "\n\nComando (podés seleccionarlo y copiarlo):\n", "b")
            t.insert("end", h.comando, "cmd")
        t.configure(state="normal")  # se deja editable para poder seleccionar y copiar
        t.bind("<Key>", lambda ev: None if (ev.state & 4 and ev.keysym.lower() in ("c", "a")) else "break")

    # ------------------------------------------------------------ inventario / mensual

    def _telegram_ok(self) -> bool:
        from redportes import telegram

        return telegram.configurado()

    def _actualizar_cb_avisar(self):
        ok = self._telegram_ok()
        self.cb_avisar.configure(state="normal" if ok else "disabled")
        if not ok:
            self.v_avisar.set(False)

    def exportar_inventario(self):
        from redportes import inventario

        cliente = self.v_cliente.get().strip()
        red = self.v_red.get().strip() or None
        try:
            filas = inventario.armar(cliente, red)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Redportes", str(e))
            return
        if not filas:
            messagebox.showinfo("Redportes", "No hay visitas guardadas de ese cliente y red. "
                                "Escaneá primero (con «Guardar en el historial» tildado).")
            return
        nombre = f"inventario_{(cliente or 'red').replace(' ', '_')}.csv"
        destino = filedialog.asksaveasfilename(defaultextension=".csv", initialfile=nombre,
                                               initialdir=str(carpeta_informes()),
                                               filetypes=[("CSV para Excel", "*.csv")])
        if destino:
            inventario.exportar_csv(filas, Path(destino))
            abrir(Path(destino))

    def informe_mensual(self):
        from redportes import mensual

        sel = self.t_visitas.selection()
        if not sel:
            messagebox.showinfo("Redportes", "Elegí una visita: se arma el informe del mes de esa visita, "
                                "para ese cliente y red.")
            return
        valores = self.t_visitas.item(sel[0], "values")
        fecha, cliente, red = valores[1], valores[2], valores[3]
        cliente = "" if cliente == "—" else cliente
        try:
            d = mensual.datos(cliente, red, fecha[:7])
        except mensual.SinVisitas as e:
            messagebox.showinfo("Redportes", str(e))
            return
        ruta = carpeta_informes() / mensual.nombre_archivo(cliente, red, fecha[:7])
        ruta.write_text(mensual.generar(d), encoding="utf-8")
        abrir(ruta)

    def abrir_automatizar(self):
        Automatizar(self)

    # ------------------------------------------------------------ este equipo

    def _cambio_pestana(self, _evento=None):
        if self.local is None and str(self.nb.select()) == str(self.p_local) \
                and str(self.b_local["state"]) != "disabled":
            self.ver_equipo_local()

    def ver_equipo_local(self):
        from redportes import equipo_local

        self.b_local.configure(state="disabled")

        def trabajo():
            try:
                self.cola.put(("local", equipo_local.recolectar()))
            except Exception as e:  # noqa: BLE001
                self.cola.put(("local", {"error": str(e)}))

        threading.Thread(target=trabajo, daemon=True).start()

    def _mostrar_equipo_local(self, d: dict):
        self.b_local.configure(state="normal")
        t = self.t_local
        t.delete(*t.get_children())
        self.txt_local.delete("1.0", "end")
        if "error" in d:
            self.txt_local.insert("end", f"No se pudo leer la configuración: {d['error']}")
            return
        self.local = d

        def seccion(nombre, extra=""):
            t.insert("", "end", values=(nombre, extra), tags=("seccion",))

        def fila(dato, valor):
            if valor not in (None, "", []):
                t.insert("", "end", values=(f"   {dato}", valor))

        s = d["sistema"]
        seccion("Sistema")
        fila("Nombre del equipo", s["nombre"])
        fila("Sistema operativo", f"{s['version']} ({s['arquitectura']})")
        fila("Encendido hace", f"{s['encendido_horas']} horas")
        fila("Procesadores / RAM", f"{s['cpus']} núcleos · {s['ram_gb']} GB ({s['ram_uso']}% en uso)")
        fila("Disco del sistema", f"{s['disco_libre_gb']} GB libres ({s['disco_uso']}% usado)")
        for i in d["interfaces"]:
            seccion(i["nombre"], i["tipo"] + (" · conexión principal" if i["principal"] else "")
                    + (" · virtual" if i["virtual"] else ""))
            fila("Dirección IP", f"{i['ip']} / {i['mascara']}")
            fila("MAC", i["mac"])
            if "dhcp" in i:
                fila("Configuración", ("DHCP" + (f" (servidor {i['servidor_dhcp']})" if i.get("servidor_dhcp")
                                                 else "")) if i["dhcp"] else "IP fija (manual)")
            if i.get("velocidad_mbps"):
                fila("Velocidad del enlace", f"{i['velocidad_mbps']} Mb/s"
                     + (f", dúplex {i['duplex']}" if i.get("duplex") else ""))
            fila("MTU", i.get("mtu"))
        seccion("Ruteo y DNS")
        fila("Puerta de enlace", d.get("puerta") or "—")
        fila("Servidores DNS", ", ".join(d.get("dns") or []) or "—")
        w = d.get("wifi") or {}
        if w:
            seccion("Wi-Fi")
            fila("Red (SSID)", w.get("ssid"))
            fila("Señal", f"{w['senal']}%" if w.get("senal") is not None else "")
            fila("Canal / banda", f"{w.get('canal', '')} · {w.get('banda', '')}")
            fila("Estándar", w.get("estandar"))
            fila("Seguridad", " · ".join(x for x in (w.get("seguridad"), w.get("cifrado")) if x))
            fila("Velocidad", f"{w.get('recepcion')} Mb/s" if w.get("recepcion") else "")
            fila("Punto de acceso (BSSID)", w.get("bssid"))
            fila("Adaptador", w.get("adaptador"))
        seccion("Otros ajustes")
        fila("Proxy", d.get("proxy") or "ninguno")
        fw = d.get("firewall") or {}
        if fw:
            fila("Firewall de Windows", f"activo en {fw['activos']} de {fw['perfiles']} perfiles")
        fila("Archivo hosts", f"{len(d['hosts'])} entrada(s) agregada(s)" if d.get("hosts") else "sin cambios")
        for h in d.get("hosts", [])[:10]:
            fila("", h)
        icono = {"falla": "✖ ", "aviso": "⚠ ", "info": "• ", "ok": "✔ "}
        for x in d["observaciones"]:
            self.txt_local.insert("end", icono[x["estado"]] + x["texto"] + "\n", x["estado"])
        self.b_copiar_local.configure(state="normal")

    def copiar_equipo_local(self):
        from redportes import equipo_local

        if self.local:
            self.raiz.clipboard_clear()
            self.raiz.clipboard_append(equipo_local.como_texto(self.local))
            self.v_estado.set("Configuración copiada.")

    # ------------------------------------------------------------ diagnóstico

    def _ocupado(self, si: bool):
        estado = "disabled" if si else "normal"
        self.b_diag.configure(state=estado)
        self.b_pagina.configure(state=estado)
        if si:
            self.barra.start(12)
        else:
            self.barra.stop()
            self.barra["value"] = 0

    def _resultado(self, estado: str, veredicto: str, que_hacer: list[str], pasos: list[tuple], texto: str):
        colores = {"ok": ("#dcfce7", "#14532d"), "aviso": ("#fef9c3", "#713f12"), "falla": ("#fde2e2", "#7f1d1d")}
        fondo, letra = colores.get(estado, ("#e2e8f0", "#0f172a"))
        icono = {"ok": "✔  ", "aviso": "⚠  ", "falla": "✖  "}.get(estado, "")
        self.l_veredicto.configure(text=icono + veredicto, background=fondo, foreground=letra)
        self.txt_hacer.delete("1.0", "end")
        self.txt_hacer.insert("end", "\n".join(f"• {q}" for q in que_hacer))
        self.t_diag.delete(*self.t_diag.get_children())
        marca = {"ok": "✔", "aviso": "⚠", "falla": "✖", "omitido": "·", "info": "ℹ"}
        for nombre, est, detalle in pasos:
            self.t_diag.insert("", "end", values=(f"{marca.get(est, '')} {nombre}", detalle), tags=(est,))
        self.texto_resultado = texto
        self.b_copiar_diag.configure(state="normal")

    def diagnosticar(self):
        from redportes import diagnostico

        self._ocupado(True)
        self.l_veredicto.configure(text="Probando la conexión… (unos 15 segundos)", background="#e2e8f0",
                                   foreground="#0f172a")

        def trabajo():
            try:
                self.cola.put(("diag", diagnostico.ejecutar()))
            except Exception as e:  # noqa: BLE001
                self.cola.put(("diag", {"error": str(e)}))

        threading.Thread(target=trabajo, daemon=True).start()

    def _mostrar_diagnostico(self, d: dict):
        from redportes import diagnostico

        self._ocupado(False)
        if "error" in d:
            self._resultado("falla", f"No se pudo hacer la prueba: {d['error']}", [], [], "")
            return
        self.diag = d
        estados = [p["estado"] for p in d["pruebas"]]
        estado = "falla" if "falla" in estados else "aviso" if "aviso" in estados else "ok"
        concl = d["conclusiones"]
        self._resultado(estado, concl[0], concl[1:],
                        [(p["nombre"], p["estado"], p["resultado"]) for p in d["pruebas"]],
                        diagnostico.como_texto(d))
        self.v_estado.set("Prueba de conexión terminada.")

    def averiguar_pagina(self):
        from redportes import consulta_dns, pagina

        texto = self.v_pagina.get()
        if "." not in consulta_dns.limpiar(texto):
            messagebox.showinfo("Redportes", "Pegá la dirección de la página que no abre, por ejemplo "
                                "www.ejemplo.com.ar o https://www.ejemplo.com.ar/algo")
            return
        self._ocupado(True)
        self.l_veredicto.configure(text=f"Averiguando por qué no abre {consulta_dns.limpiar(texto)}…",
                                   background="#e2e8f0", foreground="#0f172a")

        def trabajo():
            try:
                self.cola.put(("pagina", pagina.investigar(texto, lambda m: self.cola.put(("progreso", m)))))
            except Exception as e:  # noqa: BLE001
                self.cola.put(("pagina", {"error": str(e)}))

        threading.Thread(target=trabajo, daemon=True).start()

    def _mostrar_pagina(self, r: dict):
        from redportes import pagina

        self._ocupado(False)
        if "error" in r:
            self._resultado("falla", r["error"], [], [], "")
            return
        self.v_pagina.set(r["dominio"])
        self._resultado(r["estado"], r["veredicto"], r["que_hacer"],
                        [(p["nombre"], p["estado"], p["detalle"]) for p in r["pasos"]], pagina.como_texto(r))
        self.v_estado.set(f"Listo: {r['dominio']}.")

    def copiar_resultado(self):
        if self.texto_resultado:
            self.raiz.clipboard_clear()
            self.raiz.clipboard_append(self.texto_resultado)
            self.v_estado.set("Resultado copiado: pegalo en WhatsApp, Telegram o en el ticket.")

    # ------------------------------------------------------------ al abrir

    def _inicio(self):
        from redportes import actualizador

        actualizador.limpiar_restos()
        self._ofrecer_oui()
        self._preguntar_actualizaciones()

    def _preguntar_actualizaciones(self):
        from redportes import config

        cfg = config.leer()
        act = cfg.setdefault("actualizaciones", {})
        if "activado" not in act:
            act["activado"] = messagebox.askyesno(
                "Redportes", "¿Querés que Redportes te avise cuando salga una versión nueva?\n\n"
                "Al abrirse consulta GitHub como mucho una vez por día. No envía ningún dato de tus redes.\n\n"
                "Lo podés cambiar cuando quieras en Ayuda.")
            config.guardar(cfg)
            self.v_aviso_auto.set(act["activado"])
        if not act["activado"]:
            return

        def trabajo():
            from redportes import actualizaciones

            c = config.leer()
            info = actualizaciones.hay_nueva(c)
            config.guardar(c)
            if info:
                self.cola.put(("nueva", info))

        threading.Thread(target=trabajo, daemon=True).start()

    def _mostrar_nueva(self, info: dict):
        from redportes import actualizaciones

        self.l_banner.configure(text=f"Hay una versión nueva de Redportes: {info['version']} "
                                     f"(tenés la {__version__}).")
        self.b_bajar.configure(text="Actualizar ahora", command=lambda: self.actualizar_ahora(info))
        self.b_notas.configure(command=lambda: webbrowser.open(info.get("url") or actualizaciones.PAGINA))
        self.banner.pack(fill="x", before=self.f_form)

    def _ofrecer_oui(self):
        """La primera vez, si no hay base completa de fabricantes, ofrece bajarla."""
        from redportes import oui
        from redportes.sistema import carpeta_datos

        marca = carpeta_datos() / "oui_ofrecido"
        if oui.cantidad() >= 1000 or marca.exists():
            return
        marca.write_text("1")
        self.actualizar_oui(primera_vez=True)

    def actualizar_oui(self, primera_vez: bool = False):
        from redportes import oui

        intro = ("Para mostrar la marca de cada equipo conviene tener la base completa de "
                 "fabricantes.\n\n") if primera_vez else ""
        if not messagebox.askyesno(
                "Actualizar fabricantes",
                intro + f"Hoy se conocen {oui.cantidad():,} fabricantes. ".replace(",", ".")
                + "Se va a bajar la base completa (unos 5 MB) de la IEEE o, si no responde, "
                "de Wireshark. ¿Continuar?"):
            return
        self.v_estado.set("Bajando la base de fabricantes…")

        def trabajo():
            try:
                n = oui.actualizar_base()
                self.cola.put(("oui", f"Base de fabricantes actualizada: {n:,} registros.".replace(",", ".")))
            except Exception as e:  # noqa: BLE001
                self.cola.put(("oui", f"No se pudo bajar la base de fabricantes: {e}"))

        threading.Thread(target=trabajo, daemon=True).start()

    def abrir_informe(self):
        if self.ruta_informe:
            abrir(self.ruta_informe)

    def informe_compartir(self):
        if not self.resultado:
            return
        r = self.resultado
        ruta = carpeta_informes() / informe.nombre_archivo(r["cliente"], r["red"], compartir=True)
        ruta.write_text(informe.generar_compartible(r, getattr(self, "cambios", None)), encoding="utf-8")
        self.v_estado.set("Informe para compartir listo: IPs, MACs y nombres tapados.")
        abrir(ruta)

    def guardar_como(self):
        if not self.ruta_informe:
            return
        destino = filedialog.asksaveasfilename(
            defaultextension=".html", initialfile=self.ruta_informe.name,
            filetypes=[("Informe HTML", "*.html")])
        if destino:
            Path(destino).write_text(self.ruta_informe.read_text(encoding="utf-8"), encoding="utf-8")

    def abrir_visita(self):
        sel = self.t_visitas.selection()
        if not sel:
            messagebox.showinfo("Redportes", "Elegí una visita de la lista.")
            return
        id_visita = int(sel[0])
        r = visitas.obtener(id_visita)
        if not r:
            return
        previo = visitas.anterior(r["cliente"], r["red"], antes_de=id_visita)
        cambios = visitas.comparar(previo, r) if previo else None
        ruta = carpeta_informes() / f"visita_{id_visita}_{informe.nombre_archivo(r['cliente'], r['red'])}"
        ruta.write_text(informe.generar(r, cambios), encoding="utf-8")
        abrir(ruta)


class Automatizar:
    """Configura los avisos por Telegram y el escaneo diario automático."""

    def __init__(self, app: App):
        from redportes import telegram

        self.app = app
        self.cancelar = False
        self.q: queue.Queue = queue.Queue()
        v = self.v = tk.Toplevel(app.raiz)
        v.title("Automatizar")
        v.geometry("620x560")
        v.transient(app.raiz)

        # --- Telegram
        f = ttk.LabelFrame(v, text=" 1. Avisos por Telegram ", padding=12)
        f.pack(fill="x", padx=12, pady=(12, 6))
        pasos = ("1) En Telegram, abrí @BotFather, mandá /newbot y seguí los pasos.\n"
                 "2) Copiá el token que te da y pegalo acá abajo.\n"
                 "3) Tocá «Conectar» y mandale cualquier mensaje a tu bot\n"
                 "    (o agregalo a un grupo y escribí en el grupo, para que avise a todos).")
        ttk.Label(f, text=pasos, justify="left").pack(anchor="w")
        fila = ttk.Frame(f)
        fila.pack(fill="x", pady=(8, 0))
        ttk.Label(fila, text="Token:").pack(side="left")
        self.v_token = tk.StringVar(value=(telegram.leer_config().get("telegram") or {}).get("token", ""))
        ttk.Entry(fila, textvariable=self.v_token, show="•").pack(side="left", fill="x", expand=True, padx=6)
        self.b_conectar = ttk.Button(fila, text="Conectar", command=self.conectar)
        self.b_conectar.pack(side="left")
        ttk.Button(fila, text="Probar", command=self.probar).pack(side="left", padx=(6, 0))
        self.v_tg = tk.StringVar()
        ttk.Label(f, textvariable=self.v_tg, foreground="#2563eb", wraplength=560).pack(anchor="w", pady=(8, 0))
        self._estado_tg()

        # --- Programación
        g = ttk.LabelFrame(v, text=" 2. Escaneo automático diario ", padding=12)
        g.pack(fill="both", expand=True, padx=12, pady=6)
        from redportes.sistema import es_portable

        if es_portable():
            ttk.Label(g, text="Versión portable: la tarea apunta a esta carpeta. Si la movés o el pendrive "
                              "cambia de letra, volvé a programarla.", foreground="#a16207",
                      wraplength=560).pack(anchor="w", pady=(0, 6))
        cliente = app.v_cliente.get().strip() or "(sin nombre)"
        ttk.Label(g, text=f"Cliente: {cliente}    Red: {app.v_red.get()}\n"
                          "Se usan los datos cargados en la ventana principal. Si hay novedades "
                          "(equipos nuevos, problemas graves nuevos o baja la salud) avisa por Telegram.",
                  wraplength=560, justify="left").pack(anchor="w")
        fila2 = ttk.Frame(g)
        fila2.pack(fill="x", pady=8)
        ttk.Label(fila2, text="Todos los días a las").pack(side="left")
        self.v_hora = tk.StringVar(value="08:30")
        ttk.Entry(fila2, textvariable=self.v_hora, width=6).pack(side="left", padx=6)
        self.v_inet = tk.BooleanVar(value=app.v_internet.get())
        ttk.Checkbutton(fila2, text="con salida a Internet", variable=self.v_inet).pack(side="left", padx=6)
        ttk.Button(fila2, text="Programar", command=self.programar).pack(side="right")
        ttk.Label(g, text="Escaneos programados:").pack(anchor="w", pady=(6, 2))
        self.lista = tk.Listbox(g, height=5)
        self.lista.pack(fill="both", expand=True)
        ttk.Button(g, text="Borrar el seleccionado", command=self.borrar).pack(anchor="e", pady=(6, 0))
        self._cargar_tareas()
        v.protocol("WM_DELETE_WINDOW", self.cerrar)

    def cerrar(self):
        self.cancelar = True
        self.app._actualizar_cb_avisar()
        self.v.destroy()

    def _estado_tg(self):
        from redportes import telegram

        t = telegram.leer_config().get("telegram") or {}
        if t.get("chat_id"):
            self.v_tg.set(f"✔ Conectado: los avisos llegan a «{t.get('chat') or t['chat_id']}» "
                          f"mediante {t.get('bot', 'tu bot')}.")
        else:
            self.v_tg.set("Todavía no está configurado.")

    def conectar(self):
        from redportes import telegram

        token = self.v_token.get().strip()
        if not token:
            messagebox.showinfo("Telegram", "Pegá primero el token que te dio @BotFather.", parent=self.v)
            return
        self.b_conectar.configure(state="disabled")
        self.v_tg.set("Verificando el token…")

        def trabajo():
            try:
                bot = telegram.nombre_bot(token)
                self.q.put(("estado", f"Ahora mandale cualquier mensaje a {bot} en Telegram "
                            "(o escribí en el grupo donde lo agregaste). Esperando hasta 2 minutos…"))
                chat_id, nombre = telegram.esperar_chat(token, cancelado=lambda: self.cancelar)
                cfg = telegram.leer_config()
                cfg["telegram"] = {"token": token, "chat_id": chat_id, "chat": nombre, "bot": bot}
                telegram.guardar_config(cfg)
                telegram.enviar("✅ <b>Redportes</b> conectado. Los avisos van a llegar a este chat.")
                msg = None
            except telegram.ErrorTelegram as e:
                msg = str(e)
            except Exception as e:  # noqa: BLE001
                msg = f"Error: {e}"
            self.q.put(("fin", msg))

        threading.Thread(target=trabajo, daemon=True).start()
        self.v.after(200, self._poll)

    def _poll(self):
        if self.cancelar:
            return
        try:
            while True:
                tipo, dato = self.q.get_nowait()
                if tipo == "estado":
                    self.v_tg.set(dato)
                else:
                    self._fin_conectar(dato)
                    return
        except queue.Empty:
            pass
        self.v.after(200, self._poll)

    def _fin_conectar(self, error):
        self.b_conectar.configure(state="normal")
        if error:
            self.v_tg.set(error)
        else:
            self._estado_tg()
            self.app._actualizar_cb_avisar()
            self.app.v_avisar.set(True)

    def probar(self):
        from redportes import telegram

        try:
            telegram.enviar("✅ <b>Redportes</b>: los avisos funcionan.")
            messagebox.showinfo("Telegram", "Mensaje de prueba enviado.", parent=self.v)
        except telegram.ErrorTelegram as e:
            messagebox.showerror("Telegram", str(e), parent=self.v)

    def _cargar_tareas(self):
        from redportes import programar

        self.lista.delete(0, "end")
        try:
            for t in programar.listar():
                self.lista.insert("end", t)
        except Exception:  # noqa: BLE001
            pass

    def programar(self):
        from redportes import programar, telegram

        red = self.app.v_red.get().strip()
        if not red:
            messagebox.showinfo("Redportes", "Completá la red en la ventana principal.", parent=self.v)
            return
        if not telegram.configurado() and not messagebox.askyesno(
                "Redportes", "Los avisos por Telegram no están configurados: el escaneo va a correr y "
                "guardar el informe, pero no te va a avisar. ¿Programar igual?", parent=self.v):
            return
        try:
            texto = programar.crear(self.app.v_cliente.get().strip(), red, self.v_hora.get(),
                                    str(carpeta_informes()), self.v_inet.get())
        except (ValueError, RuntimeError) as e:
            messagebox.showerror("Redportes", str(e), parent=self.v)
            return
        messagebox.showinfo("Redportes", texto, parent=self.v)
        self._cargar_tareas()

    def borrar(self):
        from redportes import programar

        sel = self.lista.curselection()
        if not sel:
            return
        nombre = self.lista.get(sel[0])
        if messagebox.askyesno("Redportes", f"¿Borrar «{nombre}»?", parent=self.v):
            try:
                programar.borrar(nombre)
            except RuntimeError as e:
                messagebox.showerror("Redportes", str(e), parent=self.v)
            self._cargar_tareas()


def _modo_programado(args: list[str]) -> int:
    """Escaneo sin ventana (tarea programada). La salida va a un log en la carpeta de datos."""
    from redportes import cli
    from redportes.sistema import carpeta_datos

    log = (carpeta_datos() / "programado.log").open("a", encoding="utf-8")
    sys.stdout = sys.stderr = log
    from datetime import datetime

    print(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} {' '.join(args)}")
    try:
        return cli.main(args)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return 1
    finally:
        log.flush()


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--programado":
        return _modo_programado(sys.argv[2:])
    if len(sys.argv) > 1 and not ES_WINDOWS:
        # En Linux/macOS el mismo ejecutable (por ejemplo el AppImage) sirve de consola:
        # ./Redportes.AppImage escanear -c "Oficina"
        from redportes import cli

        return cli.main(sys.argv[1:])
    if ES_WINDOWS:
        try:  # nitidez en pantallas con escala
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass
    raiz = tk.Tk(className="Redportes")
    App(raiz)
    raiz.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
