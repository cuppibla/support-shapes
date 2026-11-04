import os

from dotenv import load_dotenv

load_dotenv()

MODEL = os.getenv("ADK_MODEL", "gemini-2.5-flash")
