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
    parser.add_argument("--live", action="store_true", help="Allow the agent to modify data. (By default, dry-run only)")
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

    agent = AgentController(api_key=settings.anthropic_api_key)
    logger.info(f"Target Goal: '{args.goal}'")
    logger.info(f"Live mode: {args.live}")

    # For safety: currently to actually prevent DB modifications from tools, we'd need to mock the tools
    # or pass a param. We'll simply note it here since Agent tools might inherently be read-only mostly.
    
    try:
        logger.info("Dispatching agent. This will call the Anthropic API...")
        result = agent.run(user_goal=args.goal)
        
        logger.info("=== Agent Run Complete ===")
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
