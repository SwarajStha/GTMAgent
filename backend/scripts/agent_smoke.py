import argparse
import logging
import os
import sys

# Change to repo root backend dir so Settings picks up .env properly
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from app.agent.controller import AgentController
from app.core.config import get_settings

logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description="Smoke test for the ReAct Agent Controller.")
    parser.add_argument("--goal", type=str, default="Find me a recent German tender for road construction and draft a summary.",
                        help="The goal/prompt to feed to the agent")
    parser.add_argument("--live", action="store_true", help="Allow write-capable tools (ingest_*, download_dossiers) to hit the live API and write to the DB. By default the agent runs in dry-run/read-only mode.")
    parser.add_argument("--quiet", action="store_true", help="Suppress detailed execution logs")
    args = parser.parse_args()

    log_level = logging.WARNING if args.quiet else logging.INFO
    logging.basicConfig(level=log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    logger.info("Initializing AgentController...")
    settings = get_settings()
    
    if not settings.anthropic_api_key:
        logger.error("ANTHROPIC_API_KEY is missing in your .env file. The script will likely fail.")
        if not args.live:
            logger.info("Operating in dry-run/test mode without API key can only validate schema (which will fail auth).")

    dry_run = not args.live
    agent = AgentController(api_key=settings.anthropic_api_key, dry_run=dry_run)
    logger.info(f"Target Goal: '{args.goal}'")
    logger.info(f"Live mode: {args.live} (write-capable tools dry_run={dry_run})")
    if not dry_run:
        logger.warning("Live mode enabled — ingest_tenders/ingest_awards/download_dossiers may hit the live TED API and write to the DB.")

    try:
        logger.info("Dispatching agent. This will call the Anthropic API...")
        result = agent.run(user_goal=args.goal)
        
        logger.info("=== Agent Run Complete ===")
        if result.get("truncated"):
            logger.warning("Agent hit max_turns before reaching a final answer — output is partial.")
        logger.info(f"Tool Steps Taken: {len(result['steps'])}")
        
        for i, step in enumerate(result['steps'], 1):
            logger.info(f"  [{i}] Tool: {step['tool']} | Args: {step['args']}")
        
        logger.info("=== Final Agent Output ===")
        print(f"\n{result['output']}\n")

    except Exception as e:
        logger.exception(f"Agent execution failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
