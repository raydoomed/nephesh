import logging
import os
import sys


# Ensure the app module can be imported
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Set global logging level
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logging.getLogger("werkzeug").setLevel(
    logging.WARNING
)  # Set werkzeug logging level to WARNING

from app.config import config


# Ensure to reload the latest configuration before starting
config.reload_config()

from app.web.app import app


if __name__ == "__main__":
    # Get server configuration from the application config instance
    server_config = config.server_config

    # Get host and port from the configuration
    host = server_config.get("host")
    port = server_config.get("port")

    if not host or not port:
        logging.error(
            "The configuration file is missing necessary host or port settings"
        )
        sys.exit(1)

    logging.info(
        f"Starting the service with the following configuration: host={host}, port={port}"
    )
    print(f"Starting OpenManus Web interface...")
    print(f"Please visit in your browser: http://{host}:{port}")

    # Start the application using the values from the configuration file
    app.run(host=host, port=port, debug=True, use_reloader=True)
