import os 
from datetime import *
import logging

today_date = datetime.now().strftime('%Y-%m-%d')
log_base_directory = 'logs'
log_subdirectory = os.path.join(log_base_directory, today_date)
os.makedirs(log_subdirectory, exist_ok=True)

# Define the path to the log file inside the day-wise subdirectory
log_file_path = os.path.join(log_subdirectory, 'app.log')

logging.basicConfig(
    level=logging.INFO,  # Set the default logging level (e.g., DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Log message format
    handlers=[
        logging.FileHandler(log_file_path, encoding='utf-8'),  # Output logs to the log file with UTF-8 encoding
        logging.StreamHandler()  # Output logs to the console (optional)
    ]
)

# Configure StreamHandler to handle Unicode properly on Windows
import sys
for handler in logging.root.handlers:
    if isinstance(handler, logging.StreamHandler) and handler.stream == sys.stderr:
        # Set errors='replace' to replace unencodable characters instead of crashing
        handler.stream.reconfigure(errors='replace') if hasattr(handler.stream, 'reconfigure') else None

logger= logging.getLogger('api_logger')
# Hosted authentication uses credential-bearing URLs; omit HTTP client INFO URLs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
