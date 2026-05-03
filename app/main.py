from flask import Flask, jsonify, request
from flask_cors import CORS
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

# ---------------------------------------------------------------------------
# Athena client
# ---------------------------------------------------------------------------

AWS_KEY = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET = os.getenv('AWS_SECRET_ACCESS_KEY')
AWS_TOKEN = os.getenv('AWS_SESSION_TOKEN')
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
ATHENA_DATABASE = os.getenv('ATHENA_DATABASE', 'fintrend_athena-catalog')
ATHENA_OUTPUT_BUCKET = os.getenv('ATHENA_OUTPUT_BUCKET')

MOCK_MODE = os.getenv('MOCK_MODE', 'false').lower() == 'true'
athena_client = None

try:
    import boto3
    if AWS_KEY and AWS_SECRET:
        athena_client = boto3.client('athena', aws_access_key_id=AWS_KEY, aws_secret_access_key=AWS_SECRET, aws_session_token=AWS_TOKEN, region_name=AWS_REGION)
    else:
        athena_client = boto3.client('athena', region_name=AWS_REGION)
    print("✅ Cliente Athena inicializado")
except Exception as e:
    print(f"⚠ Error inicializando cliente AWS: {e}")
    MOCK_MODE = True

# ---------------------------------------------------------------------------
# Mock data
# ---------------------------------------------------------------------------

MOCK_RENDIMIENTO_SECTOR = [{"sector": "Technology", "rendimiento_promedio": "3.42", "total_acciones": "5"}]
MOCK_TENDENCIAS = [{"dia": "2024-01-15", "precio_promedio": "482.50", "volumen_total": "125000000"}]

# ---------------------------------------------------------------------------
# Athena helpers
# ---------------------------------------------------------------------------

def ejecutar_query_athena(query):
    try:
        response = athena_client.start_query_execution(
            QueryString=query,
            QueryExecutionContext={'Database': ATHENA_DATABASE},
            ResultConfiguration={'OutputLocation': ATHENA_OUTPUT_BUCKET}
        )
        query_execution_id = response['QueryExecutionId']
        while True:
            result = athena_client.get_query_execution(QueryExecutionId=query_execution_id)
            status = result['QueryExecution']['Status']['State']
            if status in ['SUCCEEDED', 'FAILED', 'CANCELLED']: break
        if status != 'SUCCEEDED': return {'error': result['QueryExecution']['Status'].get('StateChangeReason', 'Error')}
        result_response = athena_client.get_query_results(QueryExecutionId=query_execution_id)
        return parse_athena_results(result_response)
    except Exception as e: return {'error': str(e)}

def parse_athena_results(response):
    metadata = response['ResultSet']['ResultSetMetadata']['ColumnInfo']
    columns = [col['Label'] for col in metadata]
    rows = response['ResultSet']['Rows']
    data_rows = rows[1:] if len(rows) > 1 else []
    return [dict(zip(columns, [list(d.values())[0] if d else None for d in row.get('Data', [])])) for row in data_rows]

def _respond(real_fn, mock_data):
    if MOCK_MODE: return jsonify(mock_data)
    res = real_fn()
    if isinstance(res, dict) and 'error' in res: return jsonify(res), 500
    return jsonify(res)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/api/analitica/rendimiento-detallado', methods=['GET'])
def rendimiento_por_sector():
    def query():
        return ejecutar_query_athena("""
            SELECT simbolo as sector, AVG(((close - open) / open * 100)) as rendimiento_medio, COUNT(*) as total_acciones
            FROM precios_acciones GROUP BY simbolo ORDER BY rendimiento_medio DESC LIMIT 10
        """)
    return _respond(query, MOCK_RENDIMIENTO_SECTOR)

@app.route('/api/analitica/rendimiento-simbolo', methods=['GET'])
def rendimiento_por_simbolo():
    simbolo = request.args.get('simbolo', 'AAPL').upper()
    def query():
        return ejecutar_query_athena(f"SELECT simbolo, fecha, ((close - open) / open * 100) as rendimiento FROM precios_acciones WHERE simbolo = '{simbolo}' ORDER BY fecha DESC LIMIT 100")
    return _respond(query, [])

@app.route('/api/analitica/tendencias', methods=['GET'])
def tendencias_mercado():
    def query():
        return ejecutar_query_athena("SELECT fecha as dia, AVG(close) as precio_promedio, SUM(volumen) as volumen_total FROM precios_acciones GROUP BY fecha ORDER BY fecha DESC LIMIT 30")
    return _respond(query, MOCK_TENDENCIAS)

@app.route('/api/analitica/popularidad-activos', methods=['GET'])
def popularidad_activos():
    def query():
        return ejecutar_query_athena("SELECT simbolo, COUNT(*) as menciones, 'Noticias' as estrategias FROM noticias GROUP BY simbolo ORDER BY menciones DESC LIMIT 10")
    return _respond(query, [])

@app.route('/api/analitica/impacto-noticias', methods=['GET'])
def impacto_noticias():
    def query():
        return ejecutar_query_athena("SELECT sentimiento, AVG(((close - open) / open * 100)) as rendimiento_post_noticia FROM noticias n JOIN precios_acciones pa ON n.simbolo = pa.simbolo GROUP BY sentimiento")
    return _respond(query, [])

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'mode': 'production' if not MOCK_MODE else 'mock'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5005, debug=True)
