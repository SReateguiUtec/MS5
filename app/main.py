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
    periodo = request.args.get('periodo', '30d')
    
    if periodo == 'diario':
        sql = """
            SELECT
                s.sector,
                AVG(((pa.close - pa.open) / pa.open * 100)) as rendimiento_promedio,
                COUNT(DISTINCT pa.simbolo) as total_acciones
            FROM precios_acciones pa
            JOIN simbolos s ON pa.simbolo = s.simbolo
            GROUP BY s.sector
            ORDER BY rendimiento_promedio DESC
        """
        mock = [
            {"sector": "Technology", "rendimiento_promedio": "0.15", "total_acciones": "5"},
            {"sector": "Finance",    "rendimiento_promedio": "0.08", "total_acciones": "4"},
        ]
    elif periodo == '6m':
        sql = """
            SELECT 
                s.sector,
                AVG(r.rendimiento_6m) as rendimiento_promedio,
                COUNT(DISTINCT r.simbolo) as total_acciones
            FROM (
                SELECT 
                    simbolo,
                    ((max_by(close, fecha) - min_by(open, fecha)) / min_by(open, fecha) * 100) as rendimiento_6m
                FROM precios_acciones
                WHERE TRY_CAST(fecha AS TIMESTAMP) >= current_date - interval '180' day
                GROUP BY simbolo
            ) r
            JOIN simbolos s ON r.simbolo = s.simbolo
            GROUP BY s.sector
            ORDER BY rendimiento_promedio DESC
        """
        mock = [
            {"sector": "Technology", "rendimiento_promedio": "45.20", "total_acciones": "5"},
            {"sector": "Finance",    "rendimiento_promedio": "22.15", "total_acciones": "4"},
        ]
    else: # Default 30d
        sql = """
            SELECT 
                s.sector,
                AVG(r.rendimiento_30d) as rendimiento_promedio,
                COUNT(DISTINCT r.simbolo) as total_acciones
            FROM (
                SELECT 
                    simbolo,
                    ((max_by(close, fecha) - min_by(open, fecha)) / min_by(open, fecha) * 100) as rendimiento_30d
                FROM precios_acciones
                WHERE TRY_CAST(fecha AS TIMESTAMP) >= current_date - interval '30' day
                GROUP BY simbolo
            ) r
            JOIN simbolos s ON r.simbolo = s.simbolo
            GROUP BY s.sector
            ORDER BY rendimiento_promedio DESC
        """
        mock = [
            {"sector": "Technology", "rendimiento_promedio": "12.45", "total_acciones": "5"},
            {"sector": "Finance",    "rendimiento_promedio": "8.32", "total_acciones": "4"},
        ]

    def query():
        return ejecutar_query_athena(sql)
    
    return _respond(query, mock)


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
                close as precio_cierre,
                volumen,
                ((high - low) / low * 100) as volatilidad,
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
                DATE_TRUNC('day', TRY_CAST(fecha AS TIMESTAMP)) as dia,
                AVG(close) as precio_promedio,
                SUM(volumen) as volumen_total
            FROM precios_acciones
            GROUP BY DATE_TRUNC('day', TRY_CAST(fecha AS TIMESTAMP))
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
# Endpoints Complejos (Usando Vistas de Athena)
# ---------------------------------------------------------------------------

@app.route('/api/analitica/rendimiento-detallado', methods=['GET'])
def rendimiento_detallado():
    """Consume la vista rápida vista_noticias_sectoriales definida en Athena"""
    def query():
        return ejecutar_query_athena("""
            SELECT
                sector,
                CASE
                    WHEN sentimiento = '0' OR sentimiento IS NULL THEN 'Neutral'
                    ELSE sentimiento
                END as sentimiento,
                SUM(CAST(volumen_noticias AS BIGINT)) as volumen_noticias
            FROM vista_noticias_sectoriales
            GROUP BY sector, 2
            ORDER BY volumen_noticias DESC
            LIMIT 20
        """)
    return _respond(query, [{"sector": "Technology", "sentimiento": "Bullish", "volumen_noticias": "42"}])

@app.route('/api/analitica/alertas-contradiccion', methods=['GET'])
def alertas_contradiccion():
    """Consume la vista vista_alertas_contradiccion: activos con alta volatilidad y noticias bullish"""
    def query():
        return ejecutar_query_athena("""
            SELECT *
            FROM vista_alertas_contradiccion
            ORDER BY volatilidad_promedio DESC
            LIMIT 10
        """)
    return _respond(query, [
        {"simbolo": "AAPL", "volatilidad_promedio": "3.21", "noticias_bullish": "12", "noticias_bearish": "2", "total_noticias": "14"},
        {"simbolo": "TSLA", "volatilidad_promedio": "2.85", "noticias_bullish": "8",  "noticias_bearish": "5", "total_noticias": "13"},
    ])

# NOTA: sentimiento-sectorial desactivado — la vista vista_sentimiento_sectorial
# es duplicada de vista_noticias_sectoriales y será eliminada del catálogo.
# @app.route('/api/analitica/sentimiento-sectorial', methods=['GET'])


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


@app.route('/api/analitica/impacto-noticias', methods=['GET'])
def impacto_noticias():
    """JOIN Mongo + Postgres: noticias + precios_acciones"""
    def query():
        return ejecutar_query_athena("""
            SELECT 
                CASE 
                    WHEN n.sentimiento = '0' OR n.sentimiento IS NULL THEN 'Neutral'
                    ELSE n.sentimiento
                END as sentimiento,
                AVG(((pa.close - pa.open) / pa.open * 100)) as rendimiento_post_noticia
            FROM noticias n
            JOIN precios_acciones pa ON n.simbolo = pa.simbolo 
                AND DATE(TRY_CAST(n.fechaPublicacion AS TIMESTAMP)) = DATE(TRY_CAST(pa.fecha AS TIMESTAMP))
            GROUP BY 1
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
    app.run(host='0.0.0.0', port=5005, debug=True)
