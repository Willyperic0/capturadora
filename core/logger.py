import logging
import os
from datetime import datetime

# Crear directorio logs si no existe
os.makedirs('logs', exist_ok=True)

# Generar nombre de archivo con timestamp
log_filename = datetime.now().strftime('osiris_%Y%m%d_%H%M%S.log')
log_filepath = os.path.join('logs', log_filename)

# Configurar el logger raíz
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] [%(name)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(log_filepath, encoding='utf-8'),
        logging.StreamHandler()  # También imprimir en consola para desarrollo
    ]
)

# Obtener el logger raíz
logger = logging.getLogger()