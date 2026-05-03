from flask import Flask, jsonify, request
from flask_cors import CORS
import os
from dotenv import load_dotenv

load_dotenv()

# --- FORZAR USO DE LABROLE ---
# Si las variables de entorno tienen los valores falsos por defecto, las eliminamos
# para que boto3 utilice automáticamente las credenciales del LabRole de la máquina EC2.
if os.environ.get('AWS_ACCESS_KEY_ID') == 'YOUR_AWS_ACCESS_KEY':
    del os.environ['AWS_ACCESS_KEY_ID']
if os.environ.get('AWS_SECRET_ACCESS_KEY') == 'YOUR_AWS_SECRET_KEY':
    del os.environ['AWS_SECRET_ACCESS_KEY']

app = Flask(__name__)
CORS(app)

# ---------------------------------------------------------------------------
# Athena client — only initialised when real AWS credentials are present.
# If they are absent the service starts in MOCK mode so it can be developed
# and tested without an AWS account.
# ---------------------------------------------------------------------------

AWS_KEY = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET = os.getenv('AWS_SECRET_ACCESS_KEY')
AWS_TOKEN = os.getenv('AWS_SESSION_TOKEN')
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
ATHENA_DATABASE = os.getenv('ATHENA_DATABASE', 'fintrend_athena-catalog')
if not ATHENA_DATABASE.endswith('-catalog'):
    ATHENA_DATABASE += '-catalog'
ATHENA_OUTPUT_BUCKET = os.getenv('ATHENA_OUTPUT_BUCKET')

# Si no hay llaves manuales, intentamos usar el IAM Role (LabRole)
MOCK_MODE = os.getenv('MOCK_MODE', 'false').lower() == 'true'
athena_client = None

try:
    import boto3
    # Forzamos la creación del cliente. Si no hay llaves, boto3 buscará el IAM Role automáticamente.
    if AWS_KEY and AWS_SECRET:
        athena_client = boto3.client(
            'athena',
            aws_access_key_id=AWS_KEY,
            aws_secret_access_key=AWS_SECRET,
            aws_session_token=AWS_TOKEN,
            region_name=AWS_REGION
        )
    else:
        # Modo IAM Role (LabRole)
        athena_client = boto3.client('athena', region_name=AWS_REGION)
    print("✅ Cliente Athena inicializado")
except Exception as e:
    print(f"⚠ Error inicializando cliente AWS: {e}")
    MOCK_MODE = True

# ---------------------------------------------------------------------------
# Mock data (used when MOCK_MODE is True)
# ---------------------------------------------------------------------------

MOCK_RENDIMIENTO_SECTOR = [
    {"sector": "Technology",  "rendimiento_promedio": "3.42", "total_acciones": "5"},
    {"sector": "Finance",     "rendimiento_promedio": "1.87", "total_acciones": "4"},
    {"sector": "Healthcare",  "rendimiento_promedio": "1.12", "total_acciones": "3"},
    {"sector": "Energy",      "rendimiento_promedio": "-0.55", "total_acciones": "2"},
]

MOCK_RENDIMIENTO_SIMBOLO = [
    {"simbolo": "AAPL", "fecha": "2024-01-15T09:30:00", "rendimiento": "1.23"},
    {"simbolo": "AAPL", "fecha": "2024-01-14T09:30:00", "rendimiento": "-0.45"},
    {"simbolo": "AAPL", "fecha": "2024-01-13T09:30:00", "rendimiento": "2.10"},
]

MOCK_TENDENCIAS = [
    {"dia": "2024-01-15", "precio_promedio": "482.50", "volumen_total": "125000000"},
    {"dia": "2024-01-14", "precio_promedio": "479.30", "volumen_total": "98000000"},
    {"dia": "2024-01-13", "precio_promedio": "477.80", "volumen_total": "112000000"},
]

# ---------------------------------------------------------------------------
# Athena helpers
# ---------------------------------------------------------------------------

def get_athena_client():
    if AWS_KEY and AWS_SECRET:
        return boto3.client(
            'athena',
            aws_access_key_id=AWS_KEY,
            aws_secret_access_key=AWS_SECRET,
            aws_session_token=AWS_TOKEN,
            region_name=AWS_REGION
        )
    return boto3.client('athena', region_name=AWS_REGION)

def ejecutar_query_athena(query):
    """Execute a query against Athena and return parsed rows (list of dicts)."""
    try:
        client = get_athena_client()
        response = client.start_query_execution(
            QueryString=query,
            QueryExecutionContext={'Database': ATHENA_DATABASE},
            ResultConfiguration={'OutputLocation': ATHENA_OUTPUT_BUCKET}
        )

        query_execution_id = response['QueryExecutionId']

        while True:
            result = client.get_query_execution(QueryExecutionId=query_execution_id)
            status = result['QueryExecution']['Status']['State']
            if status in ['SUCCEEDED', 'FAILED', 'CANCELLED']:
                break

        if status != 'SUCCEEDED':
            error_msg = (
                result['QueryExecution']['Status']
                .get('StateChangeReason', f'Query finalizó con estado: {status}')
            )
            return {'error': error_msg}

        result_response = client.get_query_results(
            QueryExecutionId=query_execution_id
        )
        rows = parse_athena_results(result_response)
        if not rows:
            return []
        return rows

    except Exception as e:
        return {'error': str(e)}


def parse_athena_results(response):
    """Convert Athena ResultSet into a plain list of dicts, skipping the header row."""
    metadata = response['ResultSet']['ResultSetMetadata']['ColumnInfo']
    columns = [col['Label'] for col in metadata]
    rows = response['ResultSet']['Rows']

    # Row 0 is always the header in Athena results; skip it.
    data_rows = rows[1:] if len(rows) > 1 else []

    result = []
    for row in data_rows:
        values = [list(d.values())[0] if d else None for d in row.get('Data', [])]
        result.append(dict(zip(columns, values)))

    return result


def _respond(real_fn, mock_data):
    """Call real_fn() in production or return mock_data in MOCK_MODE."""
    if MOCK_MODE:
        return jsonify(mock_data)
    resultado = real_fn()
    if isinstance(resultado, dict) and 'error' in resultado:
        return jsonify(resultado), 500
    return jsonify(resultado)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/api/analitica/rendimiento-sector', methods=['GET'])
def rendimiento_por_sector():
    def query():
        return ejecutar_query_athena("""
            SELECT
                s.sector,
                AVG(((pa.close - pa.open) / pa.open * 100)) as rendimiento_promedio,
                COUNT(DISTINCT pa.simbolo) as total_acciones
            FROM precios_acciones pa
            JOIN simbolos s ON pa.simbolo = s.simbolo
            GROUP BY s.sector
            ORDER BY rendimiento_promedio DESC
        """)
    return _respond(query, MOCK_RENDIMIENTO_SECTOR)


@app.route('/api/analitica/rendimiento-simbolo', methods=['GET'])
def rendimiento_por_simbolo():
    simbolo = request.args.get('simbolo')
    if not simbolo:
        return jsonify({'error': 'Parámetro simbolo requerido'}), 400

    if MOCK_MODE:
        mock = [dict(r, simbolo=simbolo.upper()) for r in MOCK_RENDIMIENTO_SIMBOLO]
        return jsonify(mock)

    def query():
        sym = simbolo.upper().replace("'", "''")  # basic SQL injection guard
        return ejecutar_query_athena(f"""
            SELECT
                simbolo,
                fecha,
                ((close - open) / open * 100) as rendimiento
            FROM precios_acciones
            WHERE simbolo = '{sym}'
            ORDER BY fecha DESC
            LIMIT 100
        """)
    resultado = query()
    if isinstance(resultado, dict) and 'error' in resultado:
        return jsonify(resultado), 500
    return jsonify(resultado)


@app.route('/api/analitica/tendencias', methods=['GET'])
def tendencias_mercado():
    def query():
        return ejecutar_query_athena("""
            SELECT
                DATE_TRUNC('day', CAST(fecha AS TIMESTAMP)) as dia,
                AVG(close) as precio_promedio,
                SUM(volumen) as volumen_total
            FROM precios_acciones
            GROUP BY DATE_TRUNC('day', CAST(fecha AS TIMESTAMP))
            ORDER BY dia DESC
            LIMIT 30
        """)
    return _respond(query, MOCK_TENDENCIAS)


@app.route('/api/analitica/ejecutar', methods=['POST'])
def ejecutar_query_personalizado():
    data = request.get_json()
    if not data or not data.get('query'):
        return jsonify({'error': 'Query requerido en el cuerpo'}), 400

    if MOCK_MODE:
        return jsonify({'mock': True, 'mensaje': 'Queries personalizados no disponibles en MOCK MODE'})

    resultado = ejecutar_query_athena(data['query'])
    if isinstance(resultado, dict) and 'error' in resultado:
        return jsonify(resultado), 500
    return jsonify(resultado)


@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'ok',
        'mode': 'mock' if MOCK_MODE else 'production',
        'athena_database': ATHENA_DATABASE
    })
    
# ---------------------------------------------------------------------------
# Gestión de Vistas Athena
# ---------------------------------------------------------------------------

def crear_vistas():
    """Inicializa las vistas de Athena si no existen."""
    if MOCK_MODE: return
    
    vistas = {
        "vista_rendimiento_estrategia": f"""
            CREATE OR REPLACE VIEW vista_rendimiento_estrategia AS
            SELECT 
                p.nombre as estrategia,
                f.simbolo,
                AVG(((pa.close - pa.open) / pa.open * 100)) as rendimiento_promedio
            FROM portafolios p
            JOIN favoritos f ON p.id = f.portafolio_id
            JOIN precios_acciones pa ON f.simbolo = pa.simbolo
            GROUP BY p.nombre, f.simbolo
        """,
        "vista_sentimiento_sectorial": f"""
            CREATE OR REPLACE VIEW vista_sentimiento_sectorial AS
            SELECT 
                s.sector,
                n.sentimiento,
                COUNT(*) as total_noticias
            FROM noticias n
            JOIN simbolos s ON n.simbolo = s.simbolo
            GROUP BY s.sector, n.sentimiento
        """
    }
    
    for nombre, sql in vistas.items():
        print(f"Creando vista {nombre}...")
        ejecutar_query_athena(sql)

# ---------------------------------------------------------------------------
# Endpoints Complejos (JOINs)
# ---------------------------------------------------------------------------

@app.route('/api/analitica/popularidad-activos', methods=['GET'])
def popularidad_activos():
    """JOIN MySQL: portafolios + favoritos"""
    def query():
        return ejecutar_query_athena("""
            SELECT 
                f.simbolo, 
                COUNT(*) as menciones,
                ARRAY_JOIN(ARRAY_AGG(DISTINCT p.nombre), ', ') as estrategias
            FROM favoritos f
            JOIN portafolios p ON f.portafolio_id = p.id
            GROUP BY f.simbolo
            ORDER BY menciones DESC
            LIMIT 10
        """)
    return _respond(query, [{"simbolo": "AAPL", "menciones": 150, "estrategias": "Growth, Tech"}])

@app.route('/api/analitica/rendimiento-detallado', methods=['GET'])
def rendimiento_detallado():
    """JOIN Postgres: precios_acciones + simbolos"""
    def query():
        return ejecutar_query_athena("""
            SELECT 
                s.sector,
                s.industria,
                AVG(((pa.close - pa.open) / pa.open * 100)) as rendimiento_medio
            FROM precios_acciones pa
            JOIN simbolos s ON pa.simbolo = s.simbolo
            GROUP BY s.sector, s.industria
            ORDER BY rendimiento_medio DESC
        """)
    return _respond(query, [{"sector": "Technology", "industria": "Software", "rendimiento_medio": "2.5"}])

@app.route('/api/analitica/impacto-noticias', methods=['GET'])
def impacto_noticias():
    """JOIN Mongo + Postgres: noticias + precios_acciones"""
    def query():
        return ejecutar_query_athena("""
            SELECT 
                n.sentimiento,
                AVG(((pa.close - pa.open) / pa.open * 100)) as rendimiento_post_noticia
            FROM noticias n
            JOIN precios_acciones pa ON n.simbolo = pa.simbolo 
                AND DATE(CAST(n.fechaPublicacion AS TIMESTAMP)) = DATE(CAST(pa.fecha AS TIMESTAMP))
            GROUP BY n.sentimiento
        """)
    return _respond(query, [{"sentimiento": "Bullish", "rendimiento_post_noticia": "1.8"}])

@app.route('/api/analitica/volumen-bolsa', methods=['GET'])
def volumen_bolsa():
    """JOIN Postgres: precios_acciones + simbolos"""
    def query():
        return ejecutar_query_athena("""
            SELECT 
                s.bolsa,
                SUM(pa.volumen) as volumen_total
            FROM precios_acciones pa
            JOIN simbolos s ON pa.simbolo = s.simbolo
            GROUP BY s.bolsa
        """)
    return _respond(query, [{"bolsa": "NASDAQ", "volumen_total": "5000000000"}])

if __name__ == '__main__':
    # Intentar crear vistas al arrancar
    try:
        crear_vistas()
    except Exception as e:
        print(f"⚠ Aviso al crear vistas iniciales: {e}")
        
    app.run(host='0.0.0.0', port=5005, debug=True)
