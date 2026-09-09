import os
import sqlite3
import subprocess
import sys
import shutil
import tempfile
import traceback
from datetime import datetime
import flet as ft

DIRECTORIO_APP = os.path.dirname(os.path.abspath(__file__))

# ==============================================================================
# ALMACENAMIENTO SEGURO
# ==============================================================================
def obtener_ruta_almacenamiento():
    if "ANDROID_DATA" in os.environ or "ANDROID_ROOT" in os.environ:
        directorio = os.path.expanduser("~")
        if not os.path.exists(directorio) or not os.access(directorio, os.W_OK):
            directorio = tempfile.gettempdir()
        return directorio
    return DIRECTORIO_APP

CARPETA_DATOS = obtener_ruta_almacenamiento()
DB_NAME = os.path.join(CARPETA_DATOS, "alfajores_local.db")

def get_db():
    return sqlite3.connect(DB_NAME)

def init_db():
    if not os.path.exists(DB_NAME):
        for posible in [
            os.path.join(DIRECTORIO_APP, "assets", "alfajores_local.db"),
            os.path.join(DIRECTORIO_APP, "alfajores_local.db")
        ]:
            if os.path.exists(posible):
                try:
                    shutil.copy(posible, DB_NAME)
                    break
                except Exception:
                    pass

    conn = get_db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL,
            telefono TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS productos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL,
            precio INTEGER NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS ventas (
            folio INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER,
            cliente TEXT NOT NULL,
            telefono TEXT,
            detalle TEXT NOT NULL,
            total INTEGER NOT NULL,
            estado TEXT NOT NULL,
            fecha_venta TEXT NOT NULL,
            fecha_pago TEXT,
            FOREIGN KEY (cliente_id) REFERENCES clientes(id)
        )
    """)
    c.execute("SELECT COUNT(*) FROM productos")
    if c.fetchone()[0] == 0:
        iniciales = [
            ("Alfajor Clásico Manjar", 1000),
            ("Alfajor Chocolate Blanco", 1000),
            ("Alfajor Nuez", 1000),
            ("Alfajor Maicena", 1000)
        ]
        c.executemany("INSERT INTO productos (nombre, precio) VALUES (?, ?)", iniciales)
    conn.commit()
    conn.close()

# ==============================================================================
# GENERACIÓN DE PDF (CON CARGA PROTEGIDA)
# ==============================================================================
def parsear_lineas_detalle(detalle_str):
    lineas = []
    partes = detalle_str.split(" | ")
    for p in partes:
        p = p.strip()
        if not p:
            continue
        try:
            cant_str, resto = p.split("x ", 1)
            nom, sub_str = resto.rsplit(" (", 1)
            sub_val = int(sub_str.replace(")", "").replace("$", "").replace(".", "").strip())
            cant_val = int(cant_str.strip())
            precio_u = sub_val // cant_val if cant_val > 0 else sub_val
            lineas.append({
                "cant": cant_val,
                "nombre": nom.strip(),
                "precio": f"${precio_u:,}".replace(",", "."),
                "subtotal": sub_val
            })
        except Exception:
            lineas.append({"cant": "1", "nombre": p, "precio": "-", "subtotal": 0})
    return lineas

def generar_pdf(folio_info, cliente, lineas_detalle, total, estado, tipo_doc="VENTA"):
    # Lazy import: Si reportlab falla en Android, la app NO se muere al abrir
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
    except ImportError:
        raise RuntimeError("ReportLab no está disponible en este entorno Android.")

    nombre_archivo = f"Recibo_{folio_info}_{tipo_doc}.pdf".replace(" ", "_").replace("#", "")
    ruta_completa = os.path.join(CARPETA_DATOS, nombre_archivo)

    p = canvas.Canvas(ruta_completa, pagesize=letter)
    
    posibles_nombres = [
        os.path.join(DIRECTORIO_APP, "assets", "logo.jpeg"),
        os.path.join(DIRECTORIO_APP, "logo.jpeg"),
        os.path.join(DIRECTORIO_APP, "assets", "logo.png"),
        os.path.join(DIRECTORIO_APP, "logo.png")
    ]
    ruta_logo = None
    for candidata in posibles_nombres:
        if os.path.exists(candidata):
            ruta_logo = candidata
            break

    if ruta_logo:
        try:
            p.drawImage(ruta_logo, 440, 675, width=95, height=95, preserveAspectRatio=True, mask='auto')
        except Exception:
            pass
    
    p.setFont("Helvetica-Bold", 18)
    p.drawString(50, 755, "DELICIAS CRISANT")
    
    p.setFont("Helvetica-Bold", 11)
    subtitulo = "COMPROBANTE DE VENTA" if tipo_doc == "VENTA" else "COMPROBANTE DE PAGO"
    p.drawString(50, 738, subtitulo)
    
    p.setFont("Helvetica-Bold", 10)
    p.drawString(50, 715, f"BOLETA N°: {folio_info}")
    
    p.setFont("Helvetica", 9)
    p.drawString(50, 700, f"Fecha de emisión: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    p.drawString(50, 685, f"Cliente: {cliente}")
    
    p.setFont("Helvetica-Bold", 10)
    p.drawString(50, 668, f"ESTADO: {estado.upper()}")
    
    p.setLineWidth(1)
    p.line(50, 655, 550, 655)
    
    p.setFont("Helvetica-Bold", 9)
    p.drawString(50, 640, "CANT.")
    p.drawString(95, 640, "DESCRIPCIÓN")
    p.drawString(370, 640, "P. UNIT")
    p.drawString(470, 640, "SUBTOTAL")
    
    p.setLineWidth(0.5)
    p.line(50, 633, 550, 633)
    
    p.setFont("Helvetica", 9)
    y = 618
    for item in lineas_detalle:
        p.drawString(50, y, str(item['cant']))
        p.drawString(95, y, str(item['nombre'])[:40])
        p.drawString(370, y, str(item['precio']))
        p.drawString(470, y, f"${item['subtotal']:,}".replace(",", "."))
        y -= 16
        
    p.line(50, y + 4, 550, y + 4)
    y -= 16
    
    p.setFont("Helvetica-Bold", 13)
    p.drawString(340, y, f"TOTAL: ${int(total):,}".replace(",", "."))
    
    if "PENDIENTE" in estado.upper():
        recuadro_top = y - 30
        p.setLineWidth(1)
        p.rect(50, recuadro_top - 105, 500, 105, stroke=1, fill=0)
        
        p.setFont("Helvetica-Bold", 10)
        p.drawString(65, recuadro_top - 18, "DATOS PARA TRANSFERENCIA BANCARIA:")
        
        p.setFont("Helvetica", 9)
        p.drawString(65, recuadro_top - 34, "Titular: Patricio Hernán Mella Rebolledo")
        p.drawString(65, recuadro_top - 48, "RUT: 17.510.208-6")
        p.drawString(65, recuadro_top - 62, "Banco / Entidad: Mercado Pago")
        p.drawString(65, recuadro_top - 76, "Tipo de cuenta: Cuenta Vista")
        p.drawString(65, recuadro_top - 90, "N° de cuenta: 1021634489")
        p.drawString(65, recuadro_top - 104, "Correo: patricio.mella.rebolledo@hotmail.com")
    else:
        y -= 30
        p.setFont("Helvetica-Bold", 11)
        p.drawString(50, y, "✔ CUENTA SALDADA / PAGO RECIBIDO EXITOSAMENTE ($0 DEUDA)")
        p.setFont("Helvetica-Oblique", 9)
        p.drawString(50, y - 15, "¡Muchas gracias por su preferencia!")
        
    p.showPage()
    p.save()
    return ruta_completa

# ==============================================================================
# APLICACIÓN PRINCIPAL CON PROTECTOR DE ARRANQUE
# ==============================================================================
def compartir_o_abrir_pdf(ruta_pdf):
        if not ruta_pdf or not os.path.exists(ruta_pdf):
            mostrar_snack("El archivo PDF no existe.", ft.Colors.RED_700)
            return

        nombre_archivo = os.path.basename(ruta_pdf)
        ruta_final = ruta_pdf

        # Si estamos en Android, copiamos el archivo a la carpeta pública Download (Descargas)
        if "ANDROID_DATA" in os.environ or "ANDROID_ROOT" in os.environ:
            posibles_descargas = [
                "/storage/emulated/0/Download",
                "/sdcard/Download",
            ]
            for carpeta_pub in posibles_descargas:
                if os.path.exists(carpeta_pub):
                    try:
                        destino = os.path.join(carpeta_pub, nombre_archivo)
                        shutil.copyfile(ruta_pdf, destino)
                        ruta_final = destino
                        break
                    except Exception:
                        pass

        # 1. Intentar abrir la hoja nativa de compartir de Android (WhatsApp, Drive, etc.)
        try:
            if hasattr(page, "share_files") and callable(page.share_files):
                page.share_files([ruta_final], text=f"Boleta {nombre_archivo}")
                return
        except Exception:
            pass

        try:
            if hasattr(page, "share") and page.share:
                sf = ft.ShareFile.from_path(ruta_final, name=nombre_archivo)
                page.share.share_files([sf], text=f"Boleta {nombre_archivo}")
                return
        except Exception:
            pass

        # 2. Si está en PC, abrir con el visor predeterminado
        try:
            if sys.platform == "win32":
                os.startfile(ruta_final)
            elif sys.platform == "darwin":
                subprocess.run(["open", ruta_final], check=False)
            else:
                subprocess.run(["xdg-open", ruta_final], check=False)
        except Exception:
            mostrar_snack(f"PDF guardado en Descargas: {nombre_archivo}", ft.Colors.GREEN_800)

    # --------------------------------------------------------------------------
    # PESTAÑA 1: VENTAS
    # --------------------------------------------------------------------------
    carrito = []
    productos_en_memoria = []

    txt_cliente_nuevo = ft.TextField(label="Nombre del cliente", dense=True)
    txt_telefono = ft.TextField(label="Teléfono (Opcional)", dense=True)
    
    lbl_producto_seleccionado = ft.Text("Cargando productos...", weight=ft.FontWeight.BOLD)
    prod_seleccionado_data = {"nombre": None, "precio": 0}

    txt_cantidad = ft.TextField(label="Cant.", value="1", width=90, dense=True, keyboard_type=ft.KeyboardType.NUMBER)
    columna_carrito = ft.Column(scroll=ft.ScrollMode.AUTO, height=140, spacing=2)
    lbl_total = ft.Text("Total: $0", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.BROWN_800)
    chk_pagado = ft.Checkbox(label="¿Pagó ahora? (Desmarcado = Queda Fiado)", value=False)

    def refrescar_vista_carrito():
        columna_carrito.controls.clear()
        for idx, item in enumerate(carrito):
            columna_carrito.controls.append(
                ft.ListTile(
                    leading=ft.Icon(ft.Icons.COOKIE, color=ft.Colors.BROWN),
                    title=ft.Text(f"{item['cant']}x {item['nombre']}"),
                    subtitle=ft.Text(f"Subtotal: ${item['subtotal']:,}".replace(",", ".")),
                    trailing=ft.IconButton(
                        icon=ft.Icons.DELETE_OUTLINE,
                        icon_color=ft.Colors.RED_600,
                        tooltip="Quitar del carrito",
                        on_click=lambda ev, i=idx: eliminar_del_carrito(i)
                    ),
                    dense=True
                )
            )
        total_acum = sum(x["subtotal"] for x in carrito)
        lbl_total.value = f"Total: ${total_acum:,}".replace(",", ".")
        page.update()

    def eliminar_del_carrito(indice):
        if 0 <= indice < len(carrito):
            eliminado = carrito.pop(indice)
            refrescar_vista_carrito()
            mostrar_snack(f"Se quitó {eliminado['nombre']}", ft.Colors.ORANGE_800)

    def abrir_dialogo_clientes(e):
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT nombre, telefono FROM clientes ORDER BY nombre ASC")
        lista_clientes = c.fetchall()
        conn.close()

        lista_ui = ft.ListView(spacing=5, height=300)

        def elegir_cli(nom, tel, dlg):
            txt_cliente_nuevo.value = nom
            txt_telefono.value = tel if tel else ""
            dlg.open = False
            page.update()

        for nom, tel in lista_clientes:
            lista_ui.controls.append(
                ft.ListTile(
                    leading=ft.Icon(ft.Icons.PERSON, color=ft.Colors.BROWN_600),
                    title=ft.Text(nom, weight=ft.FontWeight.BOLD),
                    subtitle=ft.Text(tel if tel else "Sin teléfono"),
                    on_click=lambda ev, n=nom, t=tel: elegir_cli(n, t, dlg_cli)
                )
            )

        def cerrar_dialogo(ev):
            dlg_cli.open = False
            page.update()

        dlg_cli = ft.AlertDialog(
            title=ft.Text("Seleccionar Cliente"),
            content=lista_ui if lista_clientes else ft.Text("No hay clientes registrados aún."),
            open=True,
            actions=[ft.TextButton("Cerrar", on_click=cerrar_dialogo)]
        )
        page.overlay.append(dlg_cli)
        page.update()

    def abrir_dialogo_productos(e):
        lista_ui = ft.ListView(spacing=5, height=300)

        def elegir_prod(nom, pr, dlg):
            prod_seleccionado_data["nombre"] = nom
            prod_seleccionado_data["precio"] = pr
            lbl_producto_seleccionado.value = f"{nom} (${pr:,})".replace(",", ".")
            dlg.open = False
            page.update()

        for pid, nom, pr in productos_en_memoria:
            lista_ui.controls.append(
                ft.ListTile(
                    leading=ft.Icon(ft.Icons.COOKIE, color=ft.Colors.BROWN_600),
                    title=ft.Text(nom, weight=ft.FontWeight.BOLD),
                    subtitle=ft.Text(f"${pr:,} CLP".replace(",", ".")),
                    on_click=lambda ev, n=nom, p=pr: elegir_prod(n, p, dlg_prod)
                )
            )

        def cerrar_dialogo(ev):
            dlg_prod.open = False
            page.update()

        dlg_prod = ft.AlertDialog(
            title=ft.Text("Seleccionar Producto"),
            content=lista_ui if productos_en_memoria else ft.Text("No hay productos registrados."),
            open=True,
            actions=[ft.TextButton("Cerrar", on_click=cerrar_dialogo)]
        )
        page.overlay.append(dlg_prod)
        page.update()

    def cargar_datos_ventas():
        nonlocal productos_en_memoria
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT id, nombre, precio FROM productos ORDER BY nombre ASC")
        productos_en_memoria = c.fetchall()
        
        nombres_disponibles = [p[1] for p in productos_en_memoria]
        if prod_seleccionado_data["nombre"] not in nombres_disponibles:
            if productos_en_memoria:
                prod_seleccionado_data["nombre"] = productos_en_memoria[0][1]
                prod_seleccionado_data["precio"] = productos_en_memoria[0][2]
                lbl_producto_seleccionado.value = f"{productos_en_memoria[0][1]} (${productos_en_memoria[0][2]:,})".replace(",", ".")
            else:
                prod_seleccionado_data["nombre"] = None
                prod_seleccionado_data["precio"] = 0
                lbl_producto_seleccionado.value = "Ningún producto seleccionado"
        conn.close()

    def agregar_al_carrito(e):
        if not prod_seleccionado_data["nombre"]:
            mostrar_snack("Selecciona un producto primero", ft.Colors.RED_700)
            return
        try:
            cant = int(txt_cantidad.value)
            if cant <= 0:
                raise ValueError
        except Exception:
            mostrar_snack("Ingresa una cantidad válida mayor a 0", ft.Colors.RED_700)
            return

        nombre = prod_seleccionado_data["nombre"]
        precio = prod_seleccionado_data["precio"]
        subtotal = cant * precio

        carrito.append({
            "nombre": nombre,
            "precio": f"${precio:,}".replace(",", "."),
            "cant": cant,
            "subtotal": subtotal
        })

        txt_cantidad.value = "1"
        refrescar_vista_carrito()

    def finalizar_venta(e):
        cliente = txt_cliente_nuevo.value.strip()
        telefono = txt_telefono.value.strip()
        if not cliente:
            mostrar_snack("Escribe o selecciona el nombre del cliente", ft.Colors.RED_700)
            return
        if not carrito:
            mostrar_snack("Agrega al menos un producto al carrito", ft.Colors.RED_700)
            return

        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT id FROM clientes WHERE LOWER(nombre) = LOWER(?)", (cliente,))
        res = c.fetchone()
        if res:
            cliente_id = res[0]
            if telefono:
                c.execute("UPDATE clientes SET telefono = ? WHERE id = ?", (telefono, cliente_id))
        else:
            c.execute("INSERT INTO clientes (nombre, telefono) VALUES (?, ?)", (cliente, telefono))
            cliente_id = c.lastrowid

        total = sum(x["subtotal"] for x in carrito)
        estado = "PAGADO" if chk_pagado.value else "PENDIENTE"
        fecha_ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        fecha_pago = fecha_ahora if chk_pagado.value else None
        detalle_db = " | ".join([f"{x['cant']}x {x['nombre']} (${x['subtotal']})" for x in carrito])

        c.execute("""
            INSERT INTO ventas (cliente_id, cliente, telefono, detalle, total, estado, fecha_venta, fecha_pago)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (cliente_id, cliente, telefono, detalle_db, total, estado, fecha_ahora, fecha_pago))
        conn.commit()
        folio = c.lastrowid
        conn.close()

        # Generar PDF con manejo de errores
        ruta_pdf = None
        try:
            ruta_pdf = generar_pdf(f"{folio:05d}", cliente, carrito, total, estado, "VENTA")
        except Exception as ex_pdf:
            mostrar_snack(f"Venta guardada. PDF no disponible: {ex_pdf}", ft.Colors.ORANGE_800)

        carrito.clear()
        refrescar_vista_carrito()
        txt_cliente_nuevo.value = ""
        txt_telefono.value = ""
        chk_pagado.value = False
        lbl_total.value = "Total: $0"
        cargar_datos_ventas()

        if ruta_pdf:
            def cerrar_exito(ev):
                dlg_exito.open = False
                page.update()

            def compartir_exito(ev):
                dlg_exito.open = False
                page.update()
                compartir_o_abrir_pdf(ruta_pdf)

            dlg_exito = ft.AlertDialog(
                title=ft.Text("Venta Registrada con Éxito"),
                content=ft.Text(f"Boleta #{folio:05d} lista. ¿Deseas enviarla al cliente?"),
                open=True,
                actions=[
                    ft.TextButton("Cerrar", on_click=cerrar_exito),
                    ft.FilledButton("Compartir PDF", icon=ft.Icons.SHARE, on_click=compartir_exito)
                ]
            )
            page.overlay.append(dlg_exito)
            page.update()

    btn_seleccionar_cliente = ft.OutlinedButton(
        "Buscar / Elegir Cliente Habitual",
        icon=ft.Icons.PERSON_SEARCH,
        on_click=abrir_dialogo_clientes
    )

    btn_seleccionar_producto = ft.OutlinedButton(
        "Cambiar Producto",
        icon=ft.Icons.COOKIE,
        on_click=abrir_dialogo_productos
    )

    vista_ventas = ft.ListView(
        padding=15,
        spacing=10,
        controls=[
            ft.Text("Nueva Venta", size=18, weight=ft.FontWeight.BOLD),
            btn_seleccionar_cliente,
            txt_cliente_nuevo,
            txt_telefono,
            ft.Divider(height=1),
            ft.Text("Producto Seleccionado:", weight=ft.FontWeight.BOLD),
            ft.Row([
                lbl_producto_seleccionado,
                btn_seleccionar_producto
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Row([
                txt_cantidad, 
                ft.FilledButton("+ Agregar al Carrito", icon=ft.Icons.ADD_SHOPPING_CART, on_click=agregar_al_carrito, expand=True)
            ]),
            ft.Text("Productos en la orden:", weight=ft.FontWeight.BOLD),
            ft.Container(
                content=columna_carrito, 
                border=ft.Border.all(1, ft.Colors.BLACK26), 
                border_radius=8, 
                padding=6
            ),
            lbl_total,
            chk_pagado,
            ft.FilledButton(
                "Finalizar Venta y Generar Boleta",
                icon=ft.Icons.RECEIPT_LONG,
                style=ft.ButtonStyle(bgcolor=ft.Colors.BROWN_700),
                height=50,
                on_click=finalizar_venta
            )
        ]
    )

    # --------------------------------------------------------------------------
    # PESTAÑA 2: FIADOS
    # --------------------------------------------------------------------------
    columna_fiados = ft.ListView(padding=15, spacing=10)

    def cobrar_todo(cliente, total_deuda, boletas, dlg):
        fecha_pago = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        folios = [b[0] for b in boletas]
        conn = get_db()
        c = conn.cursor()
        c.execute(f"UPDATE ventas SET estado = 'PAGADO', fecha_pago = ? WHERE folio IN ({','.join(['?']*len(folios))})", [fecha_pago] + folios)
        conn.commit()
        conn.close()

        lineas_recibo = [
            {"cant": "1", "nombre": f"Boleta #{b[0]:05d} ({b[2][:25]})", "precio": f"${b[1]:,}".replace(",", "."), "subtotal": b[1]}
            for b in boletas
        ]
        folios_str = ", ".join([f"#{f:05d}" for f in folios])
        
        dlg.open = False
        cargar_fiados()
        mostrar_snack(f"Cuenta de {cliente} cancelada con éxito")
        
        try:
            ruta_pago = generar_pdf(folios_str, cliente, lineas_recibo, total_deuda, "PAGADO (CANCELADO)", "PAGO")
            compartir_o_abrir_pdf(ruta_pago)
        except Exception:
            pass
        page.update()

    def ver_deuda_cliente(cliente, total_deuda):
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT folio, total, detalle FROM ventas WHERE estado = 'PENDIENTE' AND cliente = ? ORDER BY folio ASC", (cliente,))
        boletas = c.fetchall()
        conn.close()

        contenido_dlg = ft.Column(
            tight=True,
            scroll=ft.ScrollMode.AUTO,
            controls=[
                ft.Text(f"Deuda Total: ${int(total_deuda):,}".replace(",", "."), weight=ft.FontWeight.BOLD, size=16, color=ft.Colors.RED_700),
                ft.Divider()
            ] + [ft.Text(f"• Boleta #{b[0]:05d}: ${b[1]:,} ({b[2]})") for b in boletas]
        )

        def cerrar_dialogo(e):
            dlg.open = False
            page.update()

        dlg = ft.AlertDialog(
            title=ft.Text(f"Detalle: {cliente}"),
            content=contenido_dlg,
            open=True,
            actions=[
                ft.TextButton("Cerrar", on_click=cerrar_dialogo),
                ft.FilledButton(
                    f"Cobrar Todo (${int(total_deuda):,})".replace(",", "."),
                    style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_700),
                    on_click=lambda e: cobrar_todo(cliente, total_deuda, boletas, dlg)
                )
            ]
        )
        page.overlay.append(dlg)
        page.update()

    def cargar_fiados():
        columna_fiados.controls.clear()
        conn = get_db()
        c = conn.cursor()
        c.execute("""
            SELECT cliente, COUNT(folio), SUM(total)
            FROM ventas
            WHERE estado = 'PENDIENTE'
            GROUP BY cliente
            ORDER BY SUM(total) DESC
        """)
        filas = c.fetchall()
        conn.close()

        if not filas:
            columna_fiados.controls.append(ft.Text("No hay cuentas pendientes.", italic=True))
        else:
            for cli, cant, total in filas:
                columna_fiados.controls.append(
                    ft.Card(
                        content=ft.ListTile(
                            leading=ft.Icon(ft.Icons.PENDING_ACTIONS, color=ft.Colors.ORANGE_800),
                            title=ft.Text(f"{cli} ({cant} boleta{'s' if cant > 1 else ''})", weight=ft.FontWeight.BOLD),
                            subtitle=ft.Text(f"Deuda Total: ${int(total):,}".replace(",", ".")),
                            trailing=ft.Icon(ft.Icons.ARROW_FORWARD_IOS, size=16),
                            on_click=lambda e, c_name=cli, t=total: ver_deuda_cliente(c_name, t)
                        )
                    )
                )

    # --------------------------------------------------------------------------
    # PESTAÑA 3: HISTORIAL
    # --------------------------------------------------------------------------
    txt_buscar_historial = ft.TextField(label="Buscar cliente o folio", dense=True, prefix_icon=ft.Icons.SEARCH)
    
    rg_filtro_estado = ft.RadioGroup(
        content=ft.Row(
            controls=[
                ft.Radio(value="TODAS", label="Todas"),
                ft.Radio(value="PENDIENTE", label="Pendientes"),
                ft.Radio(value="PAGADO", label="Pagadas"),
            ],
            alignment=ft.MainAxisAlignment.START,
            spacing=15
        ),
        value="TODAS"
    )
    columna_historial = ft.ListView(spacing=8, height=440)

    def compartir_boleta_historial(folio, cliente, total, estado, detalle_db):
        lineas = parsear_lineas_detalle(detalle_db)
        tipo = "VENTA" if "PENDIENTE" in estado.upper() else "PAGO"
        try:
            ruta = generar_pdf(f"{folio:05d}", cliente, lineas, total, estado, tipo)
            compartir_o_abrir_pdf(ruta)
        except Exception as err:
            mostrar_snack(f"No se pudo generar PDF: {err}", ft.Colors.RED_700)

    def filtrar_historial(e=None):
        columna_historial.controls.clear()
        busqueda = txt_buscar_historial.value.strip().lower() if txt_buscar_historial.value else ""
        estado_sel = rg_filtro_estado.value or "TODAS"

        conn = get_db()
        c = conn.cursor()
        query = "SELECT folio, cliente, total, estado, fecha_venta, detalle FROM ventas WHERE 1=1"
        params = []

        if estado_sel != "TODAS":
            query += " AND UPPER(estado) = ?"
            params.append(estado_sel)

        if busqueda:
            query += " AND (LOWER(cliente) LIKE ? OR CAST(folio AS TEXT) LIKE ?)"
            params.extend([f"%{busqueda}%", f"%{busqueda}%"])

        query += " ORDER BY folio DESC LIMIT 50"
        c.execute(query, params)
        ventas = c.fetchall()
        conn.close()

        if not ventas:
            columna_historial.controls.append(
                ft.Container(
                    content=ft.Text("No se encontraron boletas para este filtro.", italic=True, color=ft.Colors.GREY_600),
                    padding=10
                )
            )
        else:
            for f, cli, tot, est, fecha, det in ventas:
                color_icono = ft.Colors.GREEN_700 if est.upper() == "PAGADO" else ft.Colors.ORANGE_800
                columna_historial.controls.append(
                    ft.Card(
                        content=ft.ListTile(
                            leading=ft.Icon(ft.Icons.DESCRIPTION, color=color_icono),
                            title=ft.Text(f"Boleta #{f:05d} - {cli}"),
                            subtitle=ft.Text(f"${tot:,} | {est} | {fecha[:10]}".replace(",", ".")),
                            trailing=ft.IconButton(
                                icon=ft.Icons.SHARE,
                                icon_color=ft.Colors.BLUE_700,
                                tooltip="Compartir PDF",
                                on_click=lambda ev, fol=f, c_name=cli, t_val=tot, s_val=est, d_str=det: compartir_boleta_historial(fol, c_name, t_val, s_val, d_str)
                            )
                        )
                    )
                )
        page.update()

    txt_buscar_historial.on_change = filtrar_historial
    rg_filtro_estado.on_change = filtrar_historial

    vista_historial = ft.ListView(
        padding=15,
        spacing=10,
        controls=[
            ft.Text("Historial de Boletas", size=18, weight=ft.FontWeight.BOLD),
            txt_buscar_historial,
            ft.Text("Filtrar por estado:", weight=ft.FontWeight.BOLD, size=13),
            rg_filtro_estado,
            ft.Divider(height=1),
            columna_historial
        ]
    )

    # --------------------------------------------------------------------------
    # PESTAÑA 4: PRECIOS Y CATÁLOGO
    # --------------------------------------------------------------------------
    txt_nombre_prod = ft.TextField(label="Nombre del Producto", dense=True)
    txt_precio_prod = ft.TextField(label="Precio CLP", dense=True, keyboard_type=ft.KeyboardType.NUMBER)
    columna_catalogo = ft.ListView(spacing=8, height=360)

    def confirmar_eliminar_producto(producto_id, nombre_prod):
        def borrar_prod(ev):
            conn = get_db()
            c = conn.cursor()
            c.execute("DELETE FROM productos WHERE id = ?", (producto_id,))
            conn.commit()
            conn.close()

            dlg_conf.open = False
            cargar_catalogo()
            cargar_datos_ventas()
            mostrar_snack(f"Producto '{nombre_prod}' eliminado", ft.Colors.RED_700)
            page.update()

        def cerrar_dialogo(ev):
            dlg_conf.open = False
            page.update()

        dlg_conf = ft.AlertDialog(
            title=ft.Text("Confirmar Eliminación"),
            content=ft.Text(f"¿Estás seguro de eliminar '{nombre_prod}' del catálogo?"),
            open=True,
            actions=[
                ft.TextButton("Cancelar", on_click=cerrar_dialogo),
                ft.FilledButton("Eliminar", style=ft.ButtonStyle(bgcolor=ft.Colors.RED_700), on_click=borrar_prod)
            ]
        )
        page.overlay.append(dlg_conf)
        page.update()

    def guardar_producto(e):
        nombre = txt_nombre_prod.value.strip()
        precio_str = txt_precio_prod.value.strip()
        if not nombre or not precio_str.isdigit():
            mostrar_snack("Ingresa un nombre y precio válido", ft.Colors.RED_700)
            return

        precio = int(precio_str)
        conn = get_db()
        c = conn.cursor()
        c.execute("""
            INSERT INTO productos (nombre, precio) VALUES (?, ?)
            ON CONFLICT(nombre) DO UPDATE SET precio = excluded.precio
        """, (nombre, precio))
        conn.commit()
        conn.close()

        txt_nombre_prod.value = ""
        txt_precio_prod.value = ""
        cargar_catalogo()
        cargar_datos_ventas()
        mostrar_snack(f"Guardado: {nombre} a ${precio:,}".replace(",", "."))
        page.update()

    def cargar_para_editar(nombre, precio):
        txt_nombre_prod.value = nombre
        txt_precio_prod.value = str(precio)
        page.update()

    def cargar_catalogo():
        columna_catalogo.controls.clear()
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT id, nombre, precio FROM productos ORDER BY nombre ASC")
        prods = c.fetchall()
        conn.close()

        for pid, nom, pr in prods:
            columna_catalogo.controls.append(
                ft.ListTile(
                    leading=ft.Icon(ft.Icons.LOCAL_OFFER, color=ft.Colors.BROWN),
                    title=ft.Text(nom, weight=ft.FontWeight.BOLD),
                    subtitle=ft.Text(f"${pr:,} CLP".replace(",", ".")),
                    trailing=ft.Row([
                        ft.IconButton(
                            icon=ft.Icons.EDIT, 
                            tooltip="Editar precio",
                            on_click=lambda ev, n=nom, p=pr: cargar_para_editar(n, p)
                        ),
                        ft.IconButton(
                            icon=ft.Icons.DELETE_OUTLINE, 
                            icon_color=ft.Colors.RED_700, 
                            tooltip="Eliminar producto",
                            on_click=lambda ev, p_id=pid, n=nom: confirmar_eliminar_producto(p_id, n)
                        )
                    ], tight=True)
                )
            )

    vista_precios = ft.ListView(
        padding=15,
        spacing=10,
        controls=[
            ft.Text("Catálogo y Precios", size=18, weight=ft.FontWeight.BOLD),
            txt_nombre_prod,
            txt_precio_prod,
            ft.FilledButton("Guardar / Modificar", icon=ft.Icons.SAVE, on_click=guardar_producto, style=ft.ButtonStyle(bgcolor=ft.Colors.BROWN_700)),
            ft.Divider(),
            ft.Text("Lista de Productos:", weight=ft.FontWeight.BOLD),
            columna_catalogo
        ]
    )

    # --------------------------------------------------------------------------
    # NAVEGACIÓN PRINCIPAL
    # --------------------------------------------------------------------------
    contenedor_principal = ft.Container(content=vista_ventas, expand=True)

    def cambiar_tab(e):
        idx = e.control.selected_index
        if idx == 0:
            cargar_datos_ventas()
            contenedor_principal.content = vista_ventas
        elif idx == 1:
            cargar_fiados()
            contenedor_principal.content = columna_fiados
        elif idx == 2:
            filtrar_historial()
            contenedor_principal.content = vista_historial
        elif idx == 3:
            cargar_catalogo()
            contenedor_principal.content = vista_precios
        page.update()

    page.appbar = ft.AppBar(
        title=ft.Text("Delicias Crisant", color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
        bgcolor=ft.Colors.BROWN_800,
        center_title=True
    )

    page.navigation_bar = ft.NavigationBar(
        selected_index=0,
        on_change=cambiar_tab,
        destinations=[
            ft.NavigationBarDestination(icon=ft.Icons.POINT_OF_SALE, label="Ventas"),
            ft.NavigationBarDestination(icon=ft.Icons.PENDING_ACTIONS, label="Fiados"),
            ft.NavigationBarDestination(icon=ft.Icons.HISTORY, label="Historial"),
            ft.NavigationBarDestination(icon=ft.Icons.SELL, label="Precios"),
        ]
    )

    cargar_datos_ventas()
    page.add(contenedor_principal)

# ==============================================================================
# ENTRY POINT CON CAPTURA VISUAL DE ERRORES (CRITICAL CATCHER)
# ==============================================================================
def main(page: ft.Page):
    page.title = "Delicias Crisant - POS"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0

    try:
        app_principal(page)
    except Exception:
        err_msg = traceback.format_exc()
        page.clean()
        page.add(
            ft.Container(
                padding=20,
                content=ft.Column(
                    scroll=ft.ScrollMode.AUTO,
                    controls=[
                        ft.Text("Error al iniciar la aplicación:", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.RED_800),
                        ft.Text(err_msg, selectable=True, size=11, font_family="monospace")
                    ]
                )
            )
        )
        page.update()

if __name__ == "__main__":
    ft.run(main)
