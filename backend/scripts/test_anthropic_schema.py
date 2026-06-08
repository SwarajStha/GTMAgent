import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.agent.controller import AgentController

agent = AgentController(api_key="fake_key_to_skip_auth_and_test_validation_only")
try:
    agent.run("test")
except Exception as e:
    import traceback
    traceback.print_exc()
