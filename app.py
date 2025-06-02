import os 
import json
from flask import Flask, render_template, request, redirect, url_for, flash
import pdfplumber
from datetime import datetime, date
from flask import send_file, abort, send_from_directory
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "Marioka"

UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')
DATA_FILE = 'data/pedidos.json'

os.makedirs('comprobantes', exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs('data', exist_ok=True)

def cargar_pedidos():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def guardar_pedidos(pedidos):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(pedidos, f, ensure_ascii=False, indent=4)

def extraer_datos_pdf(ruta_pdf):
    datos = {
        "nombre_cliente": None,
        "fecha_pedido": None,
        "fecha_entrega": None,
        "ciudad_entrega": None,
        "articulos": [],
        "cantidades": [],
        "dias_fabricacion": None
    }

    with pdfplumber.open(ruta_pdf) as pdf:
        for pagina in pdf.pages:
            texto = pagina.extract_text()
            if not texto:
                continue

            lineas = texto.split('\n')
            for linea in lineas:
                if "NOMBRE CLIENTE" in linea:
                    partes = linea.split("NOMBRE CLIENTE")
                    datos["nombre_cliente"] = partes[-1].strip()
                if "FECHA PEDIDO" in linea:
                    partes = linea.split("FECHA PEDIDO")
                    datos["fecha_pedido"] = partes[-1].strip()
                if "FECHA DE ENTREGA" in linea:
                    partes = linea.split("FECHA DE ENTREGA")
                    datos["fecha_entrega"] = partes[-1].strip()
                if "CIUDAD DE ENTREGA" in linea:
                    partes = linea.split("CIUDAD DE ENTREGA")
                    datos["ciudad_entrega"] = partes[-1].strip()

            tablas = pagina.extract_tables()
            for tabla in tablas:
                encabezado_real_idx = None
                for i, fila in enumerate(tabla):
                    fila_limpia = [cel.upper().strip() if cel else '' for cel in fila]
                    if "PRODUCTO" in fila_limpia and "CANTIDAD" in fila_limpia:
                        encabezado_real_idx = i
                        break

                if encabezado_real_idx is not None:
                    encabezado = [cel.upper().strip() if cel else '' for cel in tabla[encabezado_real_idx]]
                    idx_producto = encabezado.index("PRODUCTO")
                    idx_cantidad = encabezado.index("CANTIDAD")

                    for fila in tabla[encabezado_real_idx + 1:]:
                        producto = fila[idx_producto] if idx_producto < len(fila) and fila[idx_producto] is not None else ""
                        cantidad = fila[idx_cantidad] if idx_cantidad < len(fila) and fila[idx_cantidad] is not None else ""
                        producto = str(producto).replace('\n', ' ').strip()
                        cantidad = str(cantidad).strip()
                        if producto or cantidad:
                            datos["articulos"].append(producto)
                            datos["cantidades"].append(cantidad)

    # Calcular días de fabricación
    try:
        fecha_inicio = datetime.strptime(datos["fecha_pedido"], "%d/%m/%Y")
        fecha_entrega = datetime.strptime(datos["fecha_entrega"], "%d/%m/%Y")
        datos["dias_fabricacion"] = (fecha_entrega - fecha_inicio).days
    except Exception:
        datos["dias_fabricacion"] = None

    return datos

@app.route('/', methods=['GET', 'POST'])
def index():
    pedidos = cargar_pedidos()

    if request.method == 'POST':
        if 'archivo' in request.files:
            archivo = request.files['archivo']
            if archivo.filename.endswith('.pdf'):
                ruta = os.path.join(UPLOAD_FOLDER, archivo.filename)
                archivo.save(ruta)
                datos = extraer_datos_pdf(ruta)
                datos["nombre_archivo"] = archivo.filename

                # Generar nombre_pedido_safe para identificar unívocamente el pedido
                datos["nombre_pedido_safe"] = (datos["nombre_cliente"] + "_" + datos["fecha_entrega"]).replace("/", "-").replace(" ", "_")

                # Calcular días transcurridos y etapa "Debe estar en"
                dias_transcurridos = None
                debe_estar = None
                try:
                    fecha_pedido = datetime.strptime(datos["fecha_pedido"], "%d/%m/%Y").date()
                    fecha_actual = date.today()
                    dias_transcurridos = (fecha_actual - fecha_pedido).days

                    if datos["dias_fabricacion"]:
                        ratio = dias_transcurridos / datos["dias_fabricacion"]
                        if ratio < 0.3:
                            debe_estar = "Estructura"
                        elif 0.3 <= ratio < 0.4:
                            debe_estar = "Pintura"
                        elif 0.4 <= ratio < 0.9:
                            debe_estar = "Tejido"
                        else:
                            debe_estar = "Embalaje"
                    else:
                        debe_estar = "N/A"
                except Exception:
                    dias_transcurridos = None
                    debe_estar = "N/A"

                datos["dias_transcurridos"] = dias_transcurridos
                datos["debe_estar"] = debe_estar
                datos["pares_articulos"] = list(zip(datos["articulos"], datos["cantidades"]))
                datos["estados_actuales"] = ["Estructura"] * len(datos["pares_articulos"])

                pedidos.append(datos)
                guardar_pedidos(pedidos)

                return redirect(url_for('index'))

        if request.form.get('accion') == 'guardar_cambios':
            for i, pedido in enumerate(pedidos):
                nuevos_estados = []
                for j in range(len(pedido['pares_articulos'])):
                    key = f'estado_{i}_{j}'
                    nuevo_estado = request.form.get(key)
                    if nuevo_estado:
                        nuevos_estados.append(nuevo_estado)
                    else:
                        nuevos_estados.append(pedido['estados_actuales'][j])
                pedido['estados_actuales'] = nuevos_estados
            guardar_pedidos(pedidos)
            return redirect(url_for('index'))

    return render_template('index.html', pedidos=pedidos)


@app.route('/pedidos_listos')
def pedidos_listos():
    pedidos = cargar_pedidos()
    pedidos_listos = []

    # Filtramos los pedidos que están listos (todos sus estados en 'Embalaje')
    for pedido in pedidos:
        if all(estado == "Embalaje" for estado in pedido.get("estados_actuales", [])):
            pedidos_listos.append(pedido)

    # Intentamos listar los archivos de la carpeta 'comprobantes'
    try:
        archivos_comprobantes = os.listdir('comprobantes')
    except FileNotFoundError:
        archivos_comprobantes = []

    # Asignamos el archivo comprobante a cada pedido listo (si existe)
    for pedido in pedidos_listos:
        nombre_pedido_safe = pedido.get("nombre_pedido_safe")
        if nombre_pedido_safe:
            nombre_archivo_esperado = f"{nombre_pedido_safe}.pdf"
            if nombre_archivo_esperado in archivos_comprobantes:
                pedido["comprobante"] = nombre_archivo_esperado
            else:
                pedido["comprobante"] = None
        else:
            pedido["comprobante"] = None

    # Renderizamos la plantilla con los pedidos listos
    return render_template(
        'listos.html',
        pedidos=pedidos_listos,
        archivos_comprobantes=archivos_comprobantes
    )



@app.route('/eliminar/<int:indice>', methods=['POST'])
def eliminar(indice):
    pedidos = cargar_pedidos()
    if 0 <= indice < len(pedidos):
        pedidos.pop(indice)
        guardar_pedidos(pedidos)
        # Leer el valor enviado por el formulario
    next_url = request.form.get('next')
    if next_url:
        return redirect(next_url)
    else:
        return redirect(url_for('index'))


@app.route('/eliminar_primer_pedido', methods=['POST'])
def eliminar_primer_pedido():
    pedidos = cargar_pedidos()
    if pedidos:
        pedidos.pop(0)
        guardar_pedidos(pedidos)
    return 'ok'


@app.route('/descargar_pdf/<nombre_archivo>')
def descargar_pdf(nombre_archivo):
    return send_from_directory(UPLOAD_FOLDER, nombre_archivo, as_attachment=True)


@app.route('/subir_comprobante', methods=['POST'])
def subir_comprobante():
    archivo = request.files.get('comprobante')               # Obtenemos el archivo subido
    nombre_pedido = request.form.get('nombre_pedido')        # Obtenemos el nombre del pedido desde el formulario
    

    if archivo and archivo.filename:
        # Normalizamos el nombre para que sea seguro como nombre de archivo
        nombre_limpio = nombre_pedido.replace("/", "-").replace(" ", "_")
        
        # Forzamos que la extensión sea .pdf (asumiendo que solo se permiten PDFs)
        nombre_archivo_guardar = f"{nombre_limpio}.pdf"
    
        # Ruta donde se guardará el comprobante
        ruta_guardado = os.path.join('comprobantes', nombre_archivo_guardar)
        archivo.save(ruta_guardado)
        
        # Actualizamos el pedido correspondiente
        pedidos = cargar_pedidos()
        for pedido in pedidos:
            if pedido.get("nombre_pedido_safe") == nombre_limpio:
                pedido["comprobante"] = nombre_archivo_guardar
                break

        guardar_pedidos(pedidos)

    return redirect(url_for('pedidos_listos'))


@app.route('/descargar_comprobante/<nombre_archivo>')
def descargar_comprobante(nombre_archivo):
    ruta = os.path.join('comprobantes', nombre_archivo)
    if os.path.exists(ruta):
        return send_file(ruta, as_attachment=True)
    else:
        abort(404)

if __name__ == '__main__':
    app.run(debug=True)
