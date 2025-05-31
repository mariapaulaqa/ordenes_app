import os 
import json
from flask import Flask, render_template, request, redirect, url_for
import pdfplumber
from datetime import datetime, date

app = Flask(__name__)

UPLOAD_FOLDER = 'uploads'
DATA_FILE = 'data/pedidos.json'

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


@app.route('/eliminar/<int:indice>', methods=['POST'])
def eliminar(indice):
    pedidos = cargar_pedidos()
    if 0 <= indice < len(pedidos):
        pedidos.pop(indice)
        guardar_pedidos(pedidos)
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True)