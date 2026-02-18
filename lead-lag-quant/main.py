"""Lead-Lag Quant application entry point."""
from utils.config import get_config
from utils.logging import configure_logging, get_logger
from ui.app import create_app


def main():
    configure_logging()
    log = get_logger("main")
    config = get_config()
    log.info("starting_app", db_path=config.db_path, plan_tier=config.plan_tier.value)
    app = create_app(config)
    app.launch(server_name="0.0.0.0", server_port=7860)


if __name__ == "__main__":
    main()
