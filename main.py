import argparse
import asyncio
import sys

from src.orchestrator import Orchestrator
from src.utils import load_config, setup_logging


def main():
    parser = argparse.ArgumentParser(
        description="Safco Dental Product Scraper - AI Agent-based extraction system"
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to configuration file (default: config.yaml)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from last checkpoint",
    )
    parser.add_argument(
        "--output-dir",
        help="Override output directory from config",
    )
    parser.add_argument(
        "--categories",
        nargs="+",
        help="Override target category URLs",
    )
    args = parser.parse_args()

    # Load config
    config = load_config(args.config)

    # Apply CLI overrides
    if args.output_dir:
        config["output"]["directory"] = args.output_dir

    # Setup logging
    logger = setup_logging(config)
    logger.info("Safco Dental Scraper starting...")

    # Create orchestrator and run
    orchestrator = Orchestrator(config)

    try:
        if args.resume:
            logger.info("Resuming from checkpoint...")
            products = asyncio.run(orchestrator.resume())
        else:
            category_urls = args.categories or None
            products = asyncio.run(orchestrator.run(category_urls))

        logger.info(f"Done! Extracted {len(products)} products.")
        logger.info(f"Output saved to: {config.get('output', {}).get('directory', 'output')}/")
    except KeyboardInterrupt:
        logger.info("Interrupted. Progress saved to checkpoint.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
