# MS5 - Analitica de Mercado

Servicio de analitica avanzada para consultas agregadas de mercado usando AWS Athena. Si no hay credenciales AWS, inicia en modo mock y devuelve datos de ejemplo.

![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.0-000000?style=for-the-badge&logo=flask&logoColor=white)
![AWS Athena](https://img.shields.io/badge/AWS_Athena-Analytics-FF9900?style=for-the-badge&logo=amazonaws&logoColor=white)
![Pandas](https://img.shields.io/badge/Pandas-Data-150458?style=for-the-badge&logo=pandas&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=for-the-badge&logo=docker&logoColor=white)

## Responsabilidad

- Consultar rendimiento promedio por sector.
- Consultar rendimiento historico por simbolo.
- Consultar tendencias agregadas del mercado.
- Ejecutar consultas Athena personalizadas.
- Arrancar en modo mock si no existen credenciales AWS.

## Requisitos

- Python 3.11+
- pip
- Credenciales AWS con acceso a Athena (opcional para desarrollo)
- Bucket S3 para resultados de Athena (produccion)

## Instalacion

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Variables de entorno

```env
AWS_ACCESS_KEY_ID=your_access_key_id
AWS_SECRET_ACCESS_KEY=your_secret_access_key
AWS_REGION=us-east-1
ATHENA_DATABASE=findtrend
ATHENA_OUTPUT_BUCKET=s3://findtrend-athena-results
```

Si `AWS_ACCESS_KEY_ID` o `AWS_SECRET_ACCESS_KEY` estan vacios, el servicio usa `MOCK MODE`.

## Ejecutar en desarrollo

```bash
python app/main.py
```

El servicio queda disponible en:

```text
http://localhost:5005
```

## Endpoints principales

| Metodo | Ruta | Descripcion |
| ------ | ---- | ----------- |
| GET | `/health` | Health check y modo actual |
| GET | `/api/analitica/rendimiento-sector` | Rendimiento promedio por sector |
| GET | `/api/analitica/rendimiento-simbolo?simbolo=AAPL` | Rendimiento por simbolo |
| GET | `/api/analitica/tendencias` | Tendencias agregadas del mercado |
| POST | `/api/analitica/ejecutar` | Ejecuta una query personalizada |

## Ejemplo

```bash
curl http://localhost:5005/api/analitica/rendimiento-sector
```

## Docker

```bash
docker build -t fintrend-ms5-analitica .
docker run --env-file .env -p 5005:5005 fintrend-ms5-analitica
```

## Estructura

```text
.
├── app/
│   └── main.py
├── requirements.txt
├── Dockerfile
├── .gitignore
└── .env.example
```

## Notas

- En modo mock los endpoints principales devuelven datos de ejemplo.
- Las queries personalizadas no estan disponibles en modo mock.
- En produccion, `ATHENA_OUTPUT_BUCKET` debe apuntar a un bucket S3 valido para resultados de Athena.
